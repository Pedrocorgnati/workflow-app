"""
CommandQueueWidget — 280px right panel showing the command queue.

States:
  - Empty: placeholder (vazio)
  - With commands: scrollable list of CommandItemWidget rows + [+] button at bottom

Width: fixed 280px (min 240px, max 360px)
"""

from __future__ import annotations

import copy
import json
import logging
import shlex
from dataclasses import dataclass
from pathlib import Path
import os
import re
import sys
from typing import Any, Optional

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from workflow_app import dcp as dcp_pkg
from workflow_app.command_queue.command_item_widget import CommandItemWidget
from workflow_app.command_queue.double_phase_button import DoublePhaseButton
from workflow_app.command_queue.kimi_whitelist import is_kimi_compatible
from workflow_app.services.delivery_invalid_formatter import (
    format_delivery_invalid_popup,
)
from workflow_app.dialogs.confirm_cancel_modal import ConfirmCancelModal
from workflow_app.domain import CommandSpec, CommandStatus, EffortLevel, FlagSpec, InteractionType, ModelName
from workflow_app.signal_bus import signal_bus
from workflow_app.templates.quick_templates import (
    COMMAND_FLAG_SPECS,
    TEMPLATE_BLOG,
    TEMPLATE_BLOG_STOCKPILE,
    TEMPLATE_BOILERPLATE,
    TEMPLATE_BRIEF_NEW,
    TEMPLATE_DAILY,
    TEMPLATE_HOSTGATOR,
    TEMPLATE_INTAKE_REVIEW,
    TEMPLATE_INTAKE_SEED,
    TEMPLATE_JSON,
    TEMPLATE_MICRO_ARCHITECTURE,
    TEMPLATE_MIGRATION,
    TEMPLATE_MKT,
    TEMPLATE_MODULES,
    TEMPLATE_STUDY,
)

_DROP_INDICATOR_COLOR = QColor("#F59E0B")  # Amber-400
_DROP_INDICATOR_WIDTH = 2

_SECTION_HEADER_STYLE = (
    "QPushButton { background-color: #1E1E21; color: #A1A1AA;"
    "  border: none; border-bottom: 1px solid #3F3F46;"
    "  border-radius: 0; text-align: left; padding: 3px 8px;"
    "  font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }"
    "QPushButton:hover { background-color: #2D2D30; color: #D4D4D8; }"
)

_SECTION_BTN_STYLE = (
    "QPushButton { background-color: #3F3F46; color: #D4D4D8;"
    "  border: 1px solid #52525B; border-radius: 4px;"
    "  font-size: 10px; font-weight: 600; padding: 2px 3px; }"
    "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
    "QPushButton:pressed { background-color: #FBBF24; color: #18181B; border-color: #FBBF24; }"
)

_TAB_ACTIVE_STYLE = (
    "QPushButton { background-color: #FBBF24; color: #18181B;"
    "  border: none; border-radius: 3px;"
    "  font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }"
)
_TAB_INACTIVE_STYLE = (
    "QPushButton { background-color: transparent; color: #A1A1AA;"
    "  border: none; border-radius: 3px;"
    "  font-size: 10px; font-weight: 600; letter-spacing: 0.5px; }"
    "QPushButton:hover { color: #D4D4D8; background-color: #2D2D30; }"
)

logger = logging.getLogger(__name__)

_MODEL_MAP = {
    "opus": ModelName.OPUS,
    "sonnet": ModelName.SONNET,
    "haiku": ModelName.HAIKU,
}

_EFFORT_MAP = {
    "low": EffortLevel.LOW,
    "medium": EffortLevel.STANDARD,
    "high": EffortLevel.HIGH,
    "max": EffortLevel.MAX,
}

# GROUP_MAP — regras de injecao de /clear, /model, /effort por grupo de comando.
# Centralizado aqui para eliminar hardcode por botao (WORKFLOW-APP-RULES.md).
GROUP_MAP: dict[str, dict[str, Any]] = {
    "loop": {
        "model": ModelName.OPUS,
        "effort": EffortLevel.HIGH,
    },
    "daily_loop": {
        "model": ModelName.SONNET,
        "effort": EffortLevel.STANDARD,
    },
    "cmd_single": {
        "model": ModelName.OPUS,
        "effort": EffortLevel.HIGH,
    },
    "study": {
        "model": ModelName.OPUS,
        "effort": EffortLevel.HIGH,
    },
}


def _build_prep_specs(group: str, start_position: int = 1) -> list[CommandSpec]:
    """Retorna /clear, /model, /effort como CommandSpecs conforme GROUP_MAP."""
    cfg = GROUP_MAP.get(group, {})
    model = cfg.get("model", ModelName.OPUS)
    effort = cfg.get("effort", EffortLevel.HIGH)
    model_str = model.value.lower()
    effort_str = effort.value
    return [
        CommandSpec(name="/clear", model=model, interaction_type=InteractionType.AUTO, position=start_position),
        CommandSpec(name=f"/model {model_str}", model=model, interaction_type=InteractionType.AUTO, position=start_position + 1),
        CommandSpec(name=f"/effort {effort_str}", model=model, interaction_type=InteractionType.AUTO, position=start_position + 2),
    ]


@dataclass(frozen=True)
class DcpBuildContext:
    """Result of `_dcp_build_preflight` when all 6 gates pass.

    `delivery` is forward-referenced (file has `from __future__ import
    annotations`) to keep `workflow_app.models.delivery.Delivery` import
    lazy, matching how `_on_dcp_build_pipeline_clicked` resolves it.
    """

    cm_id: str
    module_state: str
    regenerate: bool
    wbs_root: Path
    delivery: "Delivery"  # noqa: F821 — resolved lazily via __future__ annotations


class _CollapsibleSection(QWidget):
    """Expandable/collapsible section with chevron header and 3-column button grid."""

    def __init__(
        self,
        title: str,
        expanded: bool = False,
        cols: int = 3,
        parent: QWidget | None = None,
        *,
        testid: str = "",
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._expanded = expanded
        self._cols = cols
        self._row = 0
        self._col = 0
        if testid:
            self.setProperty("testid", testid)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._toggle_btn = QPushButton(self._header_text())
        self._toggle_btn.setFixedHeight(24)
        self._toggle_btn.setStyleSheet(_SECTION_HEADER_STYLE)
        self._toggle_btn.clicked.connect(self._toggle)
        outer.addWidget(self._toggle_btn)

        self._content = QWidget()
        self._content.setStyleSheet("background-color: #27272A;")
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(5, 4, 5, 5)
        self._grid.setSpacing(3)
        self._content.setVisible(expanded)
        outer.addWidget(self._content)

    def _header_text(self) -> str:
        arrow = "▼" if self._expanded else "▶"
        return f"  {arrow}  {self._title.upper()}"

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._toggle_btn.setText(self._header_text())

    def add_button(self, label: str, tooltip: str, callback, *, testid: str = "") -> QPushButton:
        btn = QPushButton(label)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(_SECTION_BTN_STYLE)
        btn.clicked.connect(callback)
        self._grid.addWidget(btn, self._row, self._col)
        self._col += 1
        if self._col >= self._cols:
            self._col = 0
            self._row += 1
        return btn


class _DroppableContainer(QWidget):
    """QWidget subclass that paints a drop-position indicator line."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drop_indicator_pos: int | None = None

    def set_drop_indicator(self, pos: int | None) -> None:
        self._drop_indicator_pos = pos
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._drop_indicator_pos is None:
            return
        layout = self.layout()
        if layout is None:
            return
        count = layout.count()
        idx = self._drop_indicator_pos
        y: int
        if idx <= 0:
            y = 0
        elif idx >= count:
            last = layout.itemAt(count - 1)
            if last and last.widget():
                y = last.widget().geometry().bottom()
            else:
                y = self.height()
        else:
            item = layout.itemAt(idx)
            if item and item.widget():
                y = item.widget().geometry().top()
            else:
                y = 0
        painter = QPainter(self)
        pen = QPen(_DROP_INDICATOR_COLOR, _DROP_INDICATOR_WIDTH)
        painter.setPen(pen)
        painter.drawLine(4, y, self.width() - 4, y)
        painter.end()


class CommandQueueWidget(QWidget):
    """Right sidebar showing the pipeline command queue."""

    add_command_requested = Signal()
    reorder_requested = Signal(int, int)  # from_pos, to_pos (spec positions / indicator idx)
    save_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandQueueWidget")
        self.setMinimumWidth(200)
        self.setStyleSheet(
            "background-color: #18181B; border-left: 1px solid #3F3F46;"
        )

        self._items: list[CommandItemWidget] = []
        self._pipeline_manager = None
        self._cli_binary = "clauded"  # Active CLI instance (updated via instance_selected)

        # Pending modal-confirmation Enter (currently used by /effort to
        # auto-dismiss Claude Code's confirmation prompt). Stored so the
        # next dispatch can cancel it — otherwise the late Enter fires
        # into AskUserQuestion menus or other interactive prompts of the
        # next command and selects the default option.
        self._pending_modal_enter_timer: QTimer | None = None

        # Tracks whether the LAST workspace dispatch was /clear. The next
        # blue-arrow Kimi dispatch reads this to add 2s extra delay before
        # Enter (Kimi takes longer to render its prompt right after a clear
        # because the whole TUI is being repainted from scratch).
        self._last_workspace_dispatch_was_clear: bool = False

        # Onda 4: SPECIFIC-FLOW.json path of the currently-loaded DCP queue,
        # set by `_on_dcp_specific_flow_clicked` after a successful load.
        # When set, [Remove] persists the deleted command name to
        # overrides.skipped[] in this file so the next reload (or regen
        # without --reset-overrides) honors the deletion. Cleared by any
        # other pipeline_ready emission to avoid leaking DCP context into
        # legacy templates.
        self._current_dcp_flow_path: Path | None = None

        # DCP B-dcp pipeline context awaiting the final local-action
        # (`dcp-load-specific-flow`) at queue position 6. Armed by
        # `_on_dcp_build_pipeline_clicked` after preflight succeeds and the
        # 5-slash + 1-local-action specs are enqueued. Consumed by
        # `_handle_dcp_load_specific_flow` (Task 13) to locate the freshly
        # regenerated SPECIFIC-FLOW.json and emit it as the next pipeline.
        self._pending_dcp_load_ctx: Optional[DcpBuildContext] = None

        self._setup_ui()
        self._connect_signals()

        # Register the in-process local action consumed at queue position 6
        # of the B-dcp pipeline. The callable is the bound method
        # `_handle_dcp_load_specific_flow` (implemented by Task 13).
        # `register_local_action` overwrites any prior registration, so
        # re-instantiating the widget is safe.
        from workflow_app.command_queue.local_actions import register_local_action
        register_local_action(
            "dcp-load-specific-flow",
            self._handle_dcp_load_specific_flow,
        )

    # ─────────────────────────────────────────────── Attachment proxy ─── #

    class _AttachmentProxy:
        """Proxy que implementa a interface pill para DoublePhaseButton."""

        def __init__(self, widget, loader):
            self._widget = widget
            self._loader = loader

        def has_attachment(self):
            from workflow_app.config.app_state import app_state
            return app_state.has_config and app_state.config is not None

        def generate_from_attachment(self):
            self._loader()

    def _on_daily_command_ready(self, command_line: str) -> None:
        spec = CommandSpec(
            name=command_line,
            model=ModelName.OPUS,
            interaction_type=InteractionType.INTERACTIVE,
            position=len(self._items) + 1,
        )
        self.add_command(spec)
        self._template_label.setText("  \U0001f4cb  Daily")
        self._template_label.setVisible(True)
        self._maybe_auto_save("Daily")

    def _on_daily_loop_command_ready(self, command_line: str) -> None:
        dl_cfg = GROUP_MAP.get("daily_loop", {})
        dl_model = dl_cfg.get("model", ModelName.SONNET)
        dl_effort = dl_cfg.get("effort", EffortLevel.STANDARD)
        specs = _build_prep_specs("daily_loop", start_position=1)
        specs.append(
            CommandSpec(
                name=command_line,
                model=dl_model,
                interaction_type=InteractionType.INTERACTIVE,
                config_path="",
                effort=dl_effort,
                position=len(specs) + 1,
            )
        )
        self.load_pipeline(specs)
        self._template_label.setText("  \U0001f4cb  Daily Loop")
        self._template_label.setVisible(True)
        self._maybe_auto_save("Daily Loop")

    def _candidate_md_roots(self, path_arg: str) -> list[Path]:
        """Candidatos de base_dir para resolver path_arg relativo de um .md.

        Ordem: project_dir carregado -> cwd -> raiz do SystemForge detectada
        a partir de __file__ (mesmo ancora usada pela terminal subprocess
        do output_panel, onde Claude Code de fato executa).
        Cobre o caso onde workflow-app foi lancado de /home/pedro mas o spec
        vive em /home/pedro/Repositorios/<repo>/blacksmith/...
        """
        from workflow_app.config.app_state import app_state

        p = Path(path_arg)
        if p.is_absolute():
            return [p]

        candidates: list[Path] = []
        seen: set[Path] = set()

        def add(base: Path | None) -> None:
            if base is None:
                return
            try:
                resolved = (base / p).resolve()
            except OSError:
                return
            if resolved not in seen:
                seen.add(resolved)
                candidates.append(resolved)

        if app_state.has_config and app_state.config is not None:
            add(app_state.config.project_dir)

        add(Path.cwd())

        sf_root = self._find_systemforge_root()
        add(sf_root)

        return candidates

    @staticmethod
    def _find_systemforge_root() -> Path | None:
        """Anda para cima a partir de __file__ ate achar marcador SystemForge
        (.claude/commands/ + ai-forge/ + CLAUDE.md). Mesma heuristica de
        output_panel._find_systemforge_root."""
        candidate = Path(__file__).resolve().parent
        while candidate != candidate.parent:
            if (
                (candidate / ".claude" / "commands").is_dir()
                and (candidate / "ai-forge").is_dir()
                and (candidate / "CLAUDE.md").is_file()
            ):
                return candidate
            candidate = candidate.parent
        return None

    def _resolve_relative_md(self, path_arg: str) -> Path | None:
        """Primeiro candidato existente em _candidate_md_roots; None se nenhum."""
        for c in self._candidate_md_roots(path_arg):
            if c.exists():
                return c
        return None

    @classmethod
    def _existing_loop_slug_from_path(cls, path_arg: str) -> str | None:
        """Detecta IDENTIDADE de loop ja persistido em disco.

        Delega para `ai-forge/scripts/normalize_loop_name.py` (single
        source of truth). Retorna o slug preservado quando o helper
        canonico classifica o path como re-entry; retorna None caso
        contrario.

        Usado pelo collision guard em `_on_loop_command_ready` ANTES de
        invocar o normalizador completo, para detectar conflito entre
        `--name` explicito do usuario e loop existente em disco.
        """
        try:
            result = cls._invoke_loop_normalizer(path=path_arg)
        except Exception:
            return None
        if result is None or not result.get("was_re_entry"):
            return None
        return result.get("slug")

    @classmethod
    def _derive_loop_slug_from_path(cls, path_arg: str) -> str:
        """Fallback determinista quando NAO ha `--name` explicito.

        Delega para `ai-forge/scripts/normalize_loop_name.py`, que
        implementa as 4 regras canonicas em sintonia com o markdown
        spec `/loop:create-structure`:
          1. Re-entry (source.md + _LOOP-CONFIG.json em disco): preserva
             slug do parent dir AS-IS (forward-only policy).
          2. Fresh path: aplica mm-dd + kebab + strip stopwords pt-BR
             + cap 46 chars conforme regex `^\\d{2}-\\d{2}-[a-z0-9]...$`.

        Single source of truth ELIMINA drift entre widget e markdown
        spec (per adversarial review com /skill:mcp-codex 2026-05-14).

        Fallback de seguranca: se subprocess falhar (script ausente,
        erro inesperado), cai em `Path.stem` para evitar travamento da
        fila. Mesmo nesse caso pior, `/loop:create-structure` aplica sua
        propria normalizacao em runtime.
        """
        try:
            result = cls._invoke_loop_normalizer(path=path_arg)
        except Exception:
            return Path(path_arg).stem
        if result is None or "slug" not in result:
            return Path(path_arg).stem
        return result["slug"]

    @classmethod
    def _canonical_loop_slug(
        cls,
        name_arg: str | None,
        path_arg: str,
    ) -> str | None:
        """Computa slug FINAL canonico para enfileirar todas as fases do /loop.

        Garante que `/loop:create-structure`, `/loop:individual-analysis`,
        `/loop:integration`, `/loop:review`, `/loop:workflow-app` (e
        `/loop:mark-type`, `/loop:check-tasks-and-cmd` em --both) recebam
        EXATAMENTE o mesmo `--name` final que `/loop:create-structure`
        materializara em disco. Sem isso, fases 2..N apontariam para
        diretorio inexistente quando o helper normaliza `foo` -> `05-14-foo`.

        Retorna None se o helper falhar — caller deve abortar com toast.
        """
        try:
            result = cls._invoke_loop_normalizer(name=name_arg, path=path_arg)
        except Exception:
            return None
        if result is None or "slug" not in result:
            return None
        return result["slug"]

    @classmethod
    def _invoke_loop_normalizer(
        cls,
        name: str | None = None,
        path: str | None = None,
    ) -> dict | None:
        """Wrapper sobre `ai-forge/scripts/normalize_loop_name.py`.

        Subprocess intencional (em vez de import direto) por 3 razoes:
          - workflow-app vive em submodulo separado de ai-forge/scripts;
          - mantem interface uniforme entre widget (Python) e markdown
            spec (Bash) — ambos chamam via CLI;
          - latencia ~100ms aceitavel para flow de click no botao.

        Path resolution: paths relativos sao tentados primeiro contra
        candidate_md_roots (cwd, project_dir, repo root) do widget. Sem
        essa pre-resolucao, o helper enxergaria apenas cwd e poderia
        falhar em detectar re-entry/colisao quando o usuario digita
        path relativo a outro working dir (per codex review 2026-05-14).

        Retorna dict do JSON parseado em sucesso; None em qualquer falha
        (script ausente, exit non-zero, JSON mal-formado, timeout).
        """
        import json as _json
        import subprocess as _subprocess

        repo_root = cls._find_systemforge_root_for_class()
        if repo_root is None:
            return None
        script = repo_root / "ai-forge" / "scripts" / "normalize_loop_name.py"
        if not script.exists():
            return None

        resolved_path: str | None = path
        if path:
            try:
                p = Path(path).expanduser()
                if not p.is_absolute():
                    for candidate in cls._candidate_md_roots_static(path, repo_root):
                        if candidate.exists():
                            resolved_path = str(candidate)
                            break
            except (OSError, RuntimeError):
                resolved_path = path

        argv = [sys.executable, str(script), "--json"]
        if name:
            argv.extend(["--name", name])
        if resolved_path:
            argv.extend(["--path", resolved_path])

        try:
            proc = _subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
                cwd=str(repo_root),
            )
        except (OSError, _subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        try:
            return _json.loads(proc.stdout)
        except _json.JSONDecodeError:
            return None

    @staticmethod
    def _candidate_md_roots_static(path_arg: str, repo_root: Path) -> list[Path]:
        """Versao classmethod-friendly de `_candidate_md_roots`.

        Tenta resolver `path_arg` relativo contra: cwd, project_dir (se
        config carregada), e repo_root. Permite que `_invoke_loop_normalizer`
        funcione sem instancia de widget (chamada em classmethod).
        """
        try:
            from workflow_app.config.app_state import app_state
        except ImportError:
            app_state = None  # type: ignore[assignment]

        raw = Path(path_arg).expanduser()
        if raw.is_absolute():
            return [raw]

        roots: list[Path] = []
        try:
            roots.append(Path.cwd() / raw)
        except (OSError, RuntimeError):
            pass
        if app_state is not None and getattr(app_state, "has_config", False):
            cfg = getattr(app_state, "config", None)
            if cfg is not None and getattr(cfg, "project_dir", None):
                roots.append(Path(cfg.project_dir) / raw)
        roots.append(repo_root / raw)
        return roots

    @staticmethod
    def _find_systemforge_root_for_class() -> Path | None:
        """Versao class-level de _find_systemforge_root (sem self)."""
        candidate = Path(__file__).resolve().parent
        while candidate != candidate.parent:
            if (
                (candidate / ".claude" / "commands").is_dir()
                and (candidate / "ai-forge").is_dir()
                and (candidate / "CLAUDE.md").is_file()
            ):
                return candidate
            candidate = candidate.parent
        return None

    def _on_unified_command_ready(self, command_line: str) -> None:
        """Handler unico para queue-btn-loop, queue-btn-daily-loop e queue-btn-cmd-single.

        Delega para o processamento especifico de cada comando, garantindo
        que todos usem o mesmo DoublePhaseArgumentDialog refatorado.
        """
        tokens = command_line.strip().split()
        if not tokens:
            return

        base_cmd = tokens[0]
        if base_cmd == "/loop":
            self._on_loop_command_ready(command_line)
        elif base_cmd == "/daily-loop":
            self._on_daily_loop_command_ready(command_line)
        else:
            # Fallback generico: adiciona como comando simples
            spec = CommandSpec(
                name=command_line,
                model=ModelName.OPUS,
                interaction_type=InteractionType.INTERACTIVE,
                position=len(self._items) + 1,
            )
            self.add_command(spec)
            self._template_label.setText(f"  \U0001f4cb  {base_cmd}")
            self._template_label.setVisible(True)
            self._maybe_auto_save(base_cmd)

    def _on_loop_command_ready(self, command_line: str) -> None:
        """Expand `/loop --{mode} <path.md> [--name <slug>]` into its
        canonical sub-command sequence per `.claude/commands/loop.md` FASE 2.

        Antes (legado): empilhava o comando centralizador como UMA entrada
        unica na fila — o que forcava o orquestrador `/loop` a sequenciar as
        sub-fases dentro de uma unica conversa, perdendo o pareamento canonico
        `/clear` + `/model` + `/effort` entre fases.

        Agora: faz o splice em runtime, materializando as 5 (--task/--cmd),
        7 (--both) ou sub-pipeline reduzida (--cmd-single) sub-fases como
        especs separadas, todas com OPUS/HIGH e `/clear` entre elas, conforme
        `ai-forge/workflow-rules/WORKFLOW-APP-RULES.md`.
        """
        tokens = command_line.strip().split()
        mode = None
        path_arg = ""
        name_arg = ""

        if len(tokens) >= 2 and tokens[0] == "/loop":
            i = 1
            while i < len(tokens):
                t = tokens[i]
                if t in ("--task", "--cmd", "--cmd-single", "--both"):
                    mode = t
                    if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                        path_arg = tokens[i + 1]
                        i += 2
                        continue
                elif t == "--name" and i + 1 < len(tokens):
                    name_arg = tokens[i + 1]
                    i += 2
                    continue
                i += 1

        if mode is None or not path_arg:
            spec = CommandSpec(
                name=command_line,
                model=ModelName.OPUS,
                interaction_type=InteractionType.INTERACTIVE,
                position=len(self._items) + 1,
            )
            self.add_command(spec)
            self._template_label.setText("  \U0001f4cb  Loop")
            self._template_label.setVisible(True)
            self._maybe_auto_save("Loop")
            return

        # Collision guard (per codex adversarial review 2026-05-14):
        # quando o usuario fornece --name explicito MAS o path aponta para
        # um loop ja persistido em disco com slug DIFERENTE, abortar com
        # toast claro. Criar diretorio paralelo nessa situacao orfanaria
        # o loop existente silenciosamente.
        existing_slug = self._existing_loop_slug_from_path(path_arg)
        if name_arg and existing_slug and name_arg != existing_slug:
            signal_bus.toast_requested.emit(
                f"Conflito: --name '{name_arg}' divergente do loop existente "
                f"'{existing_slug}' em {path_arg}. Para reutilizar, omita "
                f"--name ou use --name {existing_slug}. Para criar loop "
                f"novo, aponte para um source.md fora desse diretorio.",
                "error",
            )
            return

        # Slug FINAL canonico (post-normalizacao mm-dd + kebab + stopwords).
        # Delega para ai-forge/scripts/normalize_loop_name.py — single source
        # of truth compartilhada com `/loop:create-structure` markdown spec.
        # Sem isso, fases 2..N enfileiradas com slug pre-normalizacao
        # apontariam para diretorio inexistente em runtime (bug e2e
        # identificado pelo codex review).
        slug = self._canonical_loop_slug(name_arg or None, path_arg)
        if slug is None:
            signal_bus.toast_requested.emit(
                f"Erro ao normalizar nome do loop. Verifique "
                f"ai-forge/scripts/normalize_loop_name.py e tente novamente "
                f"com --name explicito.",
                "error",
            )
            return

        loop_cfg = GROUP_MAP.get("loop", {})
        loop_model = loop_cfg.get("model", ModelName.OPUS)
        loop_effort = loop_cfg.get("effort", EffortLevel.HIGH)

        if mode == "--cmd-single":
            from workflow_app.config.app_state import app_state

            md_path = self._resolve_relative_md(path_arg)
            if md_path is None or not md_path.exists():
                tried = self._candidate_md_roots(path_arg)
                tried_str = "\n  - ".join(str(p) for p in tried) or path_arg
                signal_bus.toast_requested.emit(
                    f"Erro ao ler {path_arg}: arquivo nao encontrado em:\n  - {tried_str}",
                    "error",
                )
                return
            try:
                content = md_path.read_text(encoding="utf-8")
            except OSError as exc:
                signal_bus.toast_requested.emit(
                    f"Erro ao ler {md_path}: {exc}", "error"
                )
                return

            base_dir = md_path.parent
            for parent in (md_path.parent, *md_path.parent.parents):
                if (parent / ".claude").is_dir():
                    base_dir = parent
                    break
            if app_state.has_config and app_state.config is not None:
                base_dir = app_state.config.project_dir

            cmd_target_slash = ""
            fm_match = re.search(r"^cmd_target:\s*([^\r\n]+)", content, re.MULTILINE)
            if fm_match:
                cmd_target_slash = fm_match.group(1).strip()
            if not cmd_target_slash:
                heading_match = re.search(r"^#\s+(/[^\s\n]+)", content, re.MULTILINE)
                if heading_match:
                    cmd_target_slash = heading_match.group(1).strip()
            if not cmd_target_slash:
                signal_bus.toast_requested.emit(
                    f"MD {md_path.name} sem heading canonico (# /grupo:nome) "
                    "nem cmd_target no header. Abortando.",
                    "error",
                )
                return

            target_disk = cmd_target_slash.lstrip("/").replace(":", "/")
            cmd_file_path = base_dir / ".claude" / "commands" / f"{target_disk}.md"
            cmd_action = "update" if cmd_file_path.exists() else "create"

            md_path_str = str(md_path)
            kimi_slug = cmd_target_slash.lstrip("/")
            report_path = f"blacksmith/{kimi_slug}-kimi-pair-report.md"
            specs = _build_prep_specs("cmd_single", start_position=1)
            specs.append(
                CommandSpec(
                    name=f"/cmd:{cmd_action} {md_path_str}",
                    model=loop_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=loop_effort,
                    position=len(specs) + 1,
                )
            )
            specs.extend(_build_prep_specs("cmd_single", start_position=len(specs) + 1))
            specs.append(
                CommandSpec(
                    name=f"/cmd:kimi-pair-analyse {cmd_target_slash}",
                    model=loop_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=loop_effort,
                    position=len(specs) + 1,
                )
            )
            specs.append(
                CommandSpec(
                    name=f"/cmd:kimi-pair-execute {report_path}",
                    model=loop_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=loop_effort,
                    position=len(specs) + 1,
                )
            )
            specs.extend(_build_prep_specs("cmd_single", start_position=len(specs) + 1))
            specs.append(
                CommandSpec(
                    name=f"/cmd:review {cmd_target_slash} {md_path_str}",
                    model=loop_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=loop_effort,
                    position=len(specs) + 1,
                )
            )
            specs.extend(_build_prep_specs("cmd_single", start_position=len(specs) + 1))
            specs.append(
                CommandSpec(
                    name="/cmd:readme-upd",
                    model=loop_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=loop_effort,
                    position=len(specs) + 1,
                )
            )
            label = f"  \U0001f4cb  Loop --cmd-single: {cmd_target_slash} ({cmd_action})"
            auto_save_label = f"Loop --cmd-single {cmd_target_slash}"
        else:
            mode_flag = mode
            if mode == "--task":
                sub_names = [
                    f"/loop:create-structure {mode_flag} {path_arg} --name {slug}",
                    f"/loop:individual-analysis --name {slug}",
                    f"/loop:integration --name {slug}",
                    f"/loop:review --name {slug}",
                    f"/loop:workflow-app --name {slug}",
                ]
            elif mode == "--cmd":
                sub_names = [
                    f"/loop:create-structure {mode_flag} {path_arg} --name {slug}",
                    f"/loop:individual-analysis {mode_flag} --name {slug}",
                    f"/loop:integration {mode_flag} --name {slug}",
                    f"/loop:review {mode_flag} --name {slug}",
                    f"/loop:workflow-app {mode_flag} --name {slug}",
                ]
            else:  # --both
                sub_names = [
                    f"/loop:create-structure {mode_flag} {path_arg} --name {slug}",
                    f"/loop:mark-type --name {slug}",
                    f"/loop:individual-analysis {mode_flag} --name {slug}",
                    f"/loop:integration {mode_flag} --name {slug}",
                    f"/loop:review {mode_flag} --name {slug}",
                    f"/loop:check-tasks-and-cmd --name {slug}",
                    f"/loop:workflow-app {mode_flag} --name {slug}",
                ]

            specs: list[CommandSpec] = []
            specs.extend(_build_prep_specs("loop", start_position=1))
            specs.append(
                CommandSpec(
                    name=sub_names[0],
                    model=loop_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=loop_effort,
                    position=len(specs) + 1,
                )
            )
            for sub in sub_names[1:]:
                specs.extend(_build_prep_specs("loop", start_position=len(specs) + 1))
                specs.append(
                    CommandSpec(
                        name=sub,
                        model=loop_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=loop_effort,
                        position=len(specs) + 1,
                    )
                )

            label = f"  \U0001f4cb  Loop {mode}: {slug} ({len(sub_names)} fases)"
            auto_save_label = f"Loop {mode} {slug}"

        self._template_label.setText(label)
        self._template_label.setVisible(True)
        self._maybe_auto_save(auto_save_label)
        signal_bus.pipeline_ready.emit(specs)
        signal_bus.toast_requested.emit(
            f"Fila renderizada: {len(specs)} comandos.", "success"
        )

    def _on_study_command_ready(self, command_line: str) -> None:
        """Expand `/study "<prompt>" [path.md] [--name <slug>] [--simple|--deep|--heavy] [--loop <path.md>]`
        em sua sequencia canonica de subcomandos por modo, conforme
        `.claude/commands/study.md` FASE 2 (7 fases em --simple, 9 em --deep/--heavy),
        com /clear + /model + /effort entre cada fase (GROUP_MAP["study"] = Opus/HIGH).

        Antes (legado): empilhava o orquestrador /study como UMA entrada unica,
        forcando-o a sequenciar fases dentro de uma unica conversa — sem pareamento
        canonico /clear + /model + /effort entre subcomandos.

        Agora: faz splice em runtime, materializando cada subcomando como spec
        separada na fila, alinhado a forma como queue-btn-loop ja opera.

        --loop <path.md>: preserva contrato Task-023 — anexa
        /tools:auq-interview --optimize <path> como ultimo item (com dedup vs spec
        anterior dentro do mesmo batch).
        """
        try:
            tokens = shlex.split(command_line)
        except ValueError:
            tokens = command_line.strip().split()

        if not tokens or tokens[0] != "/study":
            spec = CommandSpec(
                name=command_line,
                model=ModelName.OPUS,
                interaction_type=InteractionType.INTERACTIVE,
                position=len(self._items) + 1,
            )
            self.add_command(spec)
            self._template_label.setText("  \U0001f4cb  Study")
            self._template_label.setVisible(True)
            self._maybe_auto_save("Study")
            return

        mode = "--simple"
        name_arg = ""
        loop_path: str | None = None
        positional: list[str] = []
        i = 1
        while i < len(tokens):
            t = tokens[i]
            if t in ("--simple", "--deep", "--heavy"):
                mode = t
                i += 1
            elif t == "--name" and i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                name_arg = tokens[i + 1]
                i += 2
            elif t == "--loop" and i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                loop_path = tokens[i + 1]
                i += 2
            else:
                positional.append(t)
                i += 1

        # Fallback canonico (.claude/commands/study.md FASE 1, regra 44):
        # sem posicional + --loop <path> presente -> loop_path vira {input_path}
        # implicito da PRIMEIRA fase (/study:scope[/-decompose]), alem de seguir
        # como write-back destination em /study:publish. Sem isso, scope-decompose
        # roda cego e nao sabe o que estudar.
        if not positional and loop_path:
            positional = [loop_path]

        slug = name_arg
        if not slug:
            for p in positional:
                if p.endswith(".md"):
                    slug = Path(p).stem
                    break
        if not slug and positional:
            first = positional[0]
            slug = re.sub(r"[^a-z0-9]+", "-", first.lower()).strip("-")[:60] or "study"
        if not slug:
            slug = "study"

        positional_tail = " ".join(shlex.quote(p) for p in positional)
        scope_args = f"{positional_tail} --name {slug}".strip() if positional_tail else f"--name {slug}"
        publish_suffix = (
            f" --loop {shlex.quote(loop_path)}" if loop_path else ""
        )

        if mode == "--heavy":
            sub_names = [
                f"/study:scope-decompose {scope_args}",
                f"/study:enumerate --name {slug}",
                f"/study:loop-research --name {slug}",
                f"/study:loop-synth --name {slug}",
                f"/study:consolidate-user --name {slug}",
                f"/study:review-user --name {slug}",
                f"/study:consolidate-tech --name {slug}",
                f"/study:validate --name {slug}",
                f"/study:publish --name {slug}{publish_suffix}",
            ]
        elif mode == "--deep":
            sub_names = [
                f"/study:scope {scope_args}",
                f"/study:research --name {slug}",
                f"/study:triangulate --name {slug}",
                f"/study:write-user --name {slug}",
                f"/study:debate --name {slug}",
                f"/study:review-user --name {slug}",
                f"/study:write-tech --name {slug}",
                f"/study:validate --name {slug}",
                f"/study:publish --name {slug}{publish_suffix}",
            ]
        else:
            mode = "--simple"
            sub_names = [
                f"/study:scope {scope_args}",
                f"/study:research --name {slug}",
                f"/study:write-user --name {slug}",
                f"/study:review-user --name {slug}",
                f"/study:write-tech --name {slug}",
                f"/study:validate --name {slug}",
                f"/study:publish --name {slug}{publish_suffix}",
            ]

        study_cfg = GROUP_MAP.get("study", {})
        study_model = study_cfg.get("model", ModelName.OPUS)
        study_effort = study_cfg.get("effort", EffortLevel.HIGH)

        specs: list[CommandSpec] = []
        specs.extend(_build_prep_specs("study", start_position=1))
        specs.append(
            CommandSpec(
                name=sub_names[0],
                model=study_model,
                interaction_type=InteractionType.AUTO,
                config_path="",
                effort=study_effort,
                position=len(specs) + 1,
            )
        )
        for sub in sub_names[1:]:
            specs.extend(_build_prep_specs("study", start_position=len(specs) + 1))
            specs.append(
                CommandSpec(
                    name=sub,
                    model=study_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=study_effort,
                    position=len(specs) + 1,
                )
            )

        if loop_path:
            auq_name = f"/tools:auq-interview --optimize {loop_path}"
            if not specs or specs[-1].name != auq_name:
                specs.extend(_build_prep_specs("study", start_position=len(specs) + 1))
                specs.append(
                    CommandSpec(
                        name=auq_name,
                        model=ModelName.SONNET,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=EffortLevel.STANDARD,
                        position=len(specs) + 1,
                    )
                )

        label = f"  \U0001f4cb  Study {mode}: {slug} ({len(sub_names)} fases)"
        self._template_label.setText(label)
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"Study {mode} {slug}")
        signal_bus.pipeline_ready.emit(specs)
        signal_bus.toast_requested.emit(
            f"Fila renderizada: {len(specs)} comandos.", "success"
        )

    @staticmethod
    def _extract_loop_path(command_line: str) -> str | None:
        """Extrai o valor de `--loop <path>` de um command_line shell-like.

        Suporta paths quoted (shlex). Retorna None se a flag estiver ausente,
        sem valor, ou se o proximo token for outra flag (`--xxx`).
        """
        try:
            tokens = shlex.split(command_line)
        except ValueError:
            return None
        for i, tok in enumerate(tokens):
            if tok == "--loop" and i + 1 < len(tokens):
                nxt = tokens[i + 1]
                if nxt and not nxt.startswith("--"):
                    return nxt
        return None

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        # Task 2 (loop 05-13-workflow-app-layout-2): margin-top 10 no container main-command-queue.
        main_layout.setContentsMargins(0, 10, 0, 0)
        main_layout.setSpacing(0)

        # Header — tab row (Daily | Workflow | Auxiliar) + accordion content
        header = QWidget()
        header.setObjectName("CommandQueueHeader")
        header.setProperty("testid", "output-toolbar-left")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setStyleSheet(
            "QWidget#CommandQueueHeader { background-color: #27272A;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        header_layout = QVBoxLayout(header)
        # Task 1 (loop 05-13-workflow-app-layout-2): margin-top 10 no container output-toolbar-left.
        header_layout.setContentsMargins(4, 14, 4, 4)
        header_layout.setSpacing(0)

        # ── Tab bar (3 buttons in a row) ─────────────────────────────────
        tab_bar = QWidget()
        tab_bar.setFixedHeight(28)
        tab_bar.setStyleSheet("background-color: #1E1E21;")
        tab_bar_layout = QHBoxLayout(tab_bar)
        tab_bar_layout.setContentsMargins(4, 3, 4, 3)
        tab_bar_layout.setSpacing(3)

        self._sec_tabs: list[QPushButton] = []
        _tab_testids = (
            "queue-tab-pipelines",
            "queue-tab-workflow",
            "queue-tab-auxiliar",
            "queue-tab-prompts",
            "queue-tab-actions",
        )
        for i, label in enumerate(("Pipelines", "Workflow", "Auxiliar", "Prompts", "Actions")):
            btn = QPushButton(label.upper())
            btn.setFixedHeight(22)
            btn.setProperty("testid", _tab_testids[i])
            btn.clicked.connect(lambda _ch=False, idx=i: self._switch_section(idx))
            tab_bar_layout.addWidget(btn, stretch=1)
            self._sec_tabs.append(btn)

        # Exposed so MainWindow can append extras (terminal-route-toggles + gear)
        # after the 5 section tabs via attach_tab_bar_extras().
        self._tab_bar_layout = tab_bar_layout

        header_layout.addWidget(tab_bar)

        # ── Section contents (only one visible at a time) ────────────────
        self._sec_contents: list[QWidget] = []

        # Pipelines
        daily_pill = self._AttachmentProxy(
            self, lambda: self._load_quick_template(TEMPLATE_DAILY, name="Daily")
        )
        daily_btn = DoublePhaseButton(
            label="daily",
            pipeline_name="/daily",
            argument_hint="[descricao da task] [config.json] [--tasklist <path.md>]",
            default_md_dir="blacksmith/daily/",
            radio_summaries={},
            pill=daily_pill,
            on_command_ready=self._on_daily_command_ready,
            parent=self,
        )
        daily_btn.setProperty("testid", "queue-btn-daily")
        daily_btn.setStyleSheet(_SECTION_BTN_STYLE)

        daily_loop_pill = self._AttachmentProxy(
            self, self._on_daily_loop_clicked
        )
        daily_loop_spec = COMMAND_FLAG_SPECS.get("/daily-loop")
        daily_loop_btn = DoublePhaseButton(
            label="daily-loop",
            pipeline_name="/daily-loop",
            argument_hint="[descricao da task] [config.json] [--tasklist <path.md>]",
            default_md_dir="blacksmith/daily-loop/",
            radio_summaries={},
            flags_boolean=daily_loop_spec.flags_boolean if daily_loop_spec else None,
            flags_with_value=daily_loop_spec.flags_with_value if daily_loop_spec else None,
            pill=daily_loop_pill,
            on_command_ready=self._on_unified_command_ready,
            parent=self,
        )
        daily_loop_btn.setProperty("testid", "queue-btn-daily-loop")
        daily_loop_btn.setToolTip(
            "Execute Daily Loop — expande a fila finita gerada por Create. "
            "Le _LOOP-CONFIG.json + PROGRESS.md do projeto carregado e cria "
            "para CADA item pendente: /daily-loop:do (bucket model/effort) + "
            "/daily-loop:review-done (Opus/standard, /skill:double-mcp Level 3 "
            "CROSS_ADVERSARIAL — analogo per-item de /review-executed-task, "
            "reverte+corrige+re-acceptance se achar regressao). Final: "
            "/daily-loop:review global em Opus/HIGH. /clear/model/effort "
            "dedupados entre buckets."
        )
        daily_loop_btn.setStyleSheet(_SECTION_BTN_STYLE)

        loop_pill = self._AttachmentProxy(
            self, self._on_loop_clicked
        )
        loop_spec = COMMAND_FLAG_SPECS.get("/loop")
        loop_btn = DoublePhaseButton(
            label="loop",
            pipeline_name="/loop",
            argument_hint="--task <path.md> [--name <slug>] | --cmd <path.md> [--name <slug>] | --cmd-single <path.md> | --both <path.md> [--name <slug>]",
            default_md_dir="blacksmith/loop/",
            radio_summaries={
                "--task": "para iterar execucao de tasks ja criadas em modulo ou micro-architecture",
                "--cmd": "para criar ou atualizar varios slash-commands do SystemForge em batch completo",
                "--cmd-single": "para criar ou atualizar um unico slash-command via sub-pipeline reduzida direta",
                "--both": "para fluxos que vao conter tasks variadas e criacao de comandos",
            },
            flags_boolean=loop_spec.flags_boolean if loop_spec else None,
            flags_with_value=loop_spec.flags_with_value if loop_spec else None,
            pill=loop_pill,
            on_command_ready=self._on_unified_command_ready,
            parent=self,
        )
        loop_btn.setProperty("testid", "queue-btn-loop")
        loop_btn.setToolTip(
            "Loop — expande fila finita gerada por /loop (--task|--cmd|--cmd-single|--both). "
            "Le _LOOP-CONFIG.json + PROGRESS.md do projeto carregado e cria "
            "para CADA item pendente: /daily-loop:do (bucket model/effort) + "
            "/daily-loop:review-done (Opus/standard, /skill:double-mcp Level 3 "
            "CROSS_ADVERSARIAL). Final: /daily-loop:review global em Opus/HIGH. "
            "/clear/model/effort dedupados entre buckets."
        )
        loop_btn.setStyleSheet(_SECTION_BTN_STYLE)

        study_pill = self._AttachmentProxy(
            self, lambda: self._load_quick_template(TEMPLATE_STUDY, name="Study")
        )
        study_btn = DoublePhaseButton(
            label="study",
            pipeline_name="/study",
            argument_hint='"<duvida>" [path.md] [--loop <path.md>] [--name <slug>] [--simple|--deep|--heavy]',
            default_md_dir="blacksmith/study/",
            radio_summaries={
                "--simple": "para estudo rapido com 1 fonte e output enxuto pra revisao imediata",
                "--deep": "para estudo intermediario com triangulacao de fontes e debate moderado de hipoteses",
                "--heavy": "para estudo denso com scope-decompose, loops de pesquisa e sintese profunda final",
            },
            pill=study_pill,
            on_command_ready=self._on_study_command_ready,
            parent=self,
        )
        study_btn.setProperty("testid", "queue-btn-study")
        study_btn.setToolTip(
            "Study — pesquisa estruturada com output dual (user-friendly + tecnico). "
            "3 modos: --simple (rapido, 1 fonte), --deep (triangulacao, debate), "
            "--heavy (scope-decompose, sintese profunda). Gera "
            "forged-goods/research/{name}.md."
        )
        study_btn.setStyleSheet(_SECTION_BTN_STYLE)

        pipelines_content = self._build_section_grid([
            daily_btn,
            daily_loop_btn,
            loop_btn,
            study_btn,
            ("blog", "Blog SEO: estratégia → keywords → clusters → artigos → deploy",
             lambda: self._load_quick_template(TEMPLATE_BLOG, name="Blog SEO"),
             "queue-btn-blog"),
            ("blog stockpile",
             "Blog Stockpile — gera + push remoto do stockpile. "
             "Fase 1 (geracao): expand-keywords → cluster-keywords → prioritize-topics → "
             "deduplicate-topics → generate-briefs → write-articles (stockpile) → "
             "review-seo → quality-gate (--mode stockpile). "
             "Fase 2 (push): stockpile-push (commit + push idempotente). "
             "Promote para content/{locale}/blog/ e hreflang sao responsabilidade "
             "do workflow GitHub Actions cron 13h UTC (promote-from-stockpile.yml).",
             lambda: self._load_quick_template(TEMPLATE_BLOG_STOCKPILE, name="Blog Stockpile"),
             "queue-btn-blog-stockpile"),
        ])
        header_layout.addWidget(pipelines_content)
        self._sec_contents.append(pipelines_content)

        # Workflow
        workflow_content = self._build_section_grid([
            ("json", "/project-json — Cria/atualiza project.json",
             lambda: self._load_quick_template(TEMPLATE_JSON, name="JSON"),
             "queue-btn-json"),
            ("brief new", "/first-brief-create → intake → PRD (novo projeto)",
             lambda: self._load_quick_template(TEMPLATE_BRIEF_NEW, name="Brief \u2014 Novo Projeto"),
             "queue-btn-brief-new"),
            ("micro-arch",
             "Pipeline DCP-lite /micro:* \u2014 5 comandos que produzem PRD + USER-STORIES + "
             "ARCHITECTURE + _micro-flow-hints + modules consumiveis diretamente por "
             "queue-btn-dcp-build (sem passo intermediario): "
             "/micro:brief \u2192 /micro:architecture \u2192 /micro:specific-flow-prep \u2192 "
             "/micro:modularize \u2192 /micro:review (com /clear + /model + /effort por boundary).",
             lambda: self._load_quick_template(TEMPLATE_MICRO_ARCHITECTURE, name="Micro-Arch"),
             "queue-btn-micro-arch"),
            ("Modules (Creation)", "Fase A do canonical loop — cria estrutura WBS, MODULE-META.json e delivery.json. Pre-requisito de [DCP: Build Module Pipeline].",
             self._on_modules_clicked,
             "queue-btn-modules"),
            ("DCP: Build + Load (pipeline)",
             "Enfileira pipeline B-dcp completo (5 cmds /dcp:* + carga local de SPECIFIC-FLOW) "
             "em queue-command-list para o modulo atual.\n"
             "Apos o pipeline rodar com sucesso, a fila e substituida pelos comandos do "
             "SPECIFIC-FLOW.json gerado. Compativel com producer canonico e producer micro.\n"
             "DESTRUTIVO quando SPECIFIC-FLOW.json ja existe (passa --regenerate, salva .bak-{ISO}). "
             "Modal de confirmacao antes da pipeline rodar.",
             self._on_dcp_build_pipeline_clicked, "queue-btn-dcp-build"),
            ("DCP: Specific-Flow (load)",
             "FALLBACK MANUAL: usar apenas quando o operador editou SPECIFIC-FLOW.json a mao "
             "apos um build anterior. O caminho default agora e [DCP: Build + Load (pipeline)] "
             "(queue-btn-dcp-build), que enfileira a pipeline B-dcp completa e ja carrega o "
             "flow gerado no 6o item.\n"
             "Le o SPECIFIC-FLOW.json do modulo atual e carrega os comandos na fila para "
             "execucao manual.\n"
             "ATENCAO: deletes/reorder na fila visual sao TRANSIENT — re-clicar este botao "
             "recarrega do disco e os itens removidos voltam. Para fix permanente, edite "
             "MODULE-META.json e regenere via [DCP: Build + Load (pipeline)].",
             self._on_dcp_specific_flow_clicked, "queue-btn-dcp-specific-flow"),
        ])
        self._apply_dcp_reader_gating(workflow_content)
        header_layout.addWidget(workflow_content)
        self._sec_contents.append(workflow_content)

        # Auxiliar
        auxiliar_content = self._build_section_grid([
            ("rocksmash",
             "rocksmash — le metrics-project-pill (_LOOP-CONFIG.json kind=daily-loop), "
             "expande para fila /loop-rocksmash:prepare + N pares :do/:review-done + "
             "/loop-rocksmash:rename. Items kind=preparo/finalizacao sao ignorados; "
             "directives /clear, /model, /effort auto-injetadas por bucket boundary.",
             self._on_rocksmash_clicked,
             "queue-btn-rocksmash"),
            ("mkt", "Marketing: portfolio, LinkedIn, Instagram",
             lambda: self._load_quick_template(TEMPLATE_MKT, name="Marketing"),
             "queue-btn-mkt"),
            ("boilerplate", "Boilerplate: scan → convert-nextjs → cleanup → persona → mockify → persona-assets → enhance-fe → gen-sql → finalize. Abre modal para path do repo (NAO le project.json).",
             self._on_boilerplate_clicked, "queue-btn-boilerplate"),
            # Cmd Single: modal simplificado com fixed_flag="cmd-single".
            # Mostra apenas o input de path — sem checkbox, sem campo condicional.
            # Monta automaticamente: /loop --cmd-single <path.md>
            (lambda btn=None: (
                btn := DoublePhaseButton(
                    label="Cmd Single",
                    pipeline_name="/loop",
                    argument_hint="",
                    default_md_dir="blacksmith/loop/",
                    radio_summaries={},
                    flags_boolean=[],
                    flags_with_value=[],
                    fixed_flag="cmd-single",
                    pill=None,
                    on_command_ready=self._on_unified_command_ready,
                    parent=self,
                ),
                btn.setProperty("testid", "queue-btn-cmd-single"),
                btn.setToolTip(
                    "Cmd Single — pipeline reduzida para criar/atualizar UM comando "
                    "avulso. Informe o path do .md da spec do comando."
                ),
                btn.setStyleSheet(_SECTION_BTN_STYLE),
                btn,
            )[-1])(),
            ("intake-seed", "Intake Seed — prepara base maximamente expandida para o intake-review. Dupla função: (1) /intake:obvious melhora o INTAKE.md original; (2) /intake-review:seed gera INTAKE.seeded.md + MILESTONES.seeded.md consolidando features em docs_root/features/*. Passa project.json da pill.",
             lambda: self._load_quick_template(TEMPLATE_INTAKE_SEED, name="Intake Seed"),
             "queue-btn-intake-seed"),
            ("intake-review", "Intake Review (F9): create-checklist → list-improove → compare → create-gaplist → execute-gaplist-p0 → execute-gaplist-p1 → execute-gaplist-p2 → review-executed → clear",
             lambda: self._load_quick_template(TEMPLATE_INTAKE_REVIEW, name="Intake Review"),
             "queue-btn-intake-review"),
        ])
        header_layout.addWidget(auxiliar_content)
        self._sec_contents.append(auxiliar_content)

        # Prompts tab (refactor 2026-05-15 output-toolbar-left consolidation):
        # buttons antes alocados em toolbar-prompts-row (deletada). Populado por
        # MainWindow via populate_prompts_tab() porque os handlers dependem de
        # estado vivo no MainWindow (signal_bus, _publish_to_terminal, etc).
        prompts_content = QWidget()
        prompts_content.setStyleSheet("background-color: #27272A;")
        self._prompts_content_layout = QHBoxLayout(prompts_content)
        self._prompts_content_layout.setContentsMargins(5, 4, 5, 5)
        self._prompts_content_layout.setSpacing(4)
        self._prompts_content_layout.addStretch(1)
        header_layout.addWidget(prompts_content)
        self._sec_contents.append(prompts_content)

        # Actions tab (refactor 2026-05-15): JSON/WS + mcp-codex/mcp-kimi/
        # double-mcp/asq-user antes alocados em output-toolbar-actions-row
        # (deletada). Brief/Docs descartados. Populado por MainWindow via
        # populate_actions_tab().
        actions_content = QWidget()
        actions_content.setStyleSheet("background-color: #27272A;")
        self._actions_content_layout = QHBoxLayout(actions_content)
        self._actions_content_layout.setContentsMargins(5, 4, 5, 5)
        self._actions_content_layout.setSpacing(4)
        self._actions_content_layout.addStretch(1)
        header_layout.addWidget(actions_content)
        self._sec_contents.append(actions_content)

        # Default: Workflow active (index 1)
        self._active_section = 1
        self._apply_section_styles()

        # Exposed so MainWindow can place it as a sibling of output-toolbar.
        self.header_widget = header

        # Play bar — big play button
        play_bar = QWidget()
        play_bar.setStyleSheet(
            "background-color: #1C1C1F; border-bottom: 1px solid #3F3F46;"
        )
        play_bar.setFixedHeight(82)
        pl = QVBoxLayout(play_bar)
        pl.setContentsMargins(8, 5, 8, 5)
        pl.setSpacing(4)

        play_row_top = QHBoxLayout()
        play_row_top.setContentsMargins(0, 0, 0, 0)
        play_row_top.setSpacing(8)
        play_row_bottom = QHBoxLayout()
        play_row_bottom.setContentsMargins(0, 0, 0, 0)
        play_row_bottom.setSpacing(8)
        pl.addLayout(play_row_top)
        pl.addLayout(play_row_bottom)

        # "Rodar próximo" — botão dominante da play bar (primeira posição,
        # verde #16A34A, stretch=7). Executa o proximo item pendente da fila e
        # para. Funciona em qualquer item (auto ou interactive). Diferente do
        # _btn_next ("Continuar: X") que aparece SO em pause de interactive.
        self._play_btn = QPushButton("▶  Rodar próximo")
        self._play_btn.setProperty("testid", "queue-btn-play-next")
        self._play_btn.setFixedHeight(32)
        self._play_btn.setMinimumWidth(84)
        self._play_btn.setToolTip(
            "Executa o proximo item pendente da fila e para.\n"
            "Funciona com qualquer item — auto ou interactive."
        )
        self._play_btn.setStyleSheet(
            "QPushButton { background-color: #16A34A; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 13px; font-weight: 700; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:pressed { background-color: #166534; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._play_btn.clicked.connect(self._on_step_btn_clicked)

        # Container "div" envolvendo o queue-btn-play-next para alvo de testes
        # de UI (data-testid). Mantem o stretch=2 original do play_btn.
        self._play_btn_container = QWidget()
        self._play_btn_container.setProperty("testid", "queue-btn-play-next-container")
        _play_btn_container_layout = QHBoxLayout(self._play_btn_container)
        _play_btn_container_layout.setContentsMargins(0, 0, 0, 0)
        _play_btn_container_layout.setSpacing(0)
        _play_btn_container_layout.addWidget(self._play_btn)
        play_row_top.addWidget(self._play_btn_container, stretch=2)

        # Autocast (segunda posicao — invertido com schedule em Iter 12).
        # Width dobrada vs original (minimumWidth 140) e setinha dupla ▶▶.
        # Emite via signal_bus para a state machine em metrics_bar.
        self._btn_autocast = QPushButton("▶▶  autocast")
        self._btn_autocast.setProperty("testid", "autocast-btn")
        self._btn_autocast.setCheckable(True)
        self._btn_autocast.setFixedHeight(32)
        self._btn_autocast.setMinimumWidth(84)
        self._btn_autocast.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_autocast.setToolTip(
            "Autocast: dispara [Rodar proximo] em loop ate a fila esvaziar"
        )
        self._btn_autocast.setStyleSheet(
            "QPushButton { background-color: #1E3A8A; color: #FAFAFA;"
            "  border: 1px solid #3B82F6; border-radius: 5px;"
            "  font-size: 12px; font-weight: 700; padding: 0 10px; }"
            "QPushButton:hover { background-color: #1D4ED8; }"
            "QPushButton:checked { background-color: #DC2626; border-color: #EF4444; }"
            "QPushButton:checked:hover { background-color: #B91C1C; }"
        )

        def _on_autocast_play_toggled(checked: bool) -> None:
            self._btn_autocast.setText("▶▶  parar" if checked else "▶▶  autocast")
            signal_bus.autocast_toggle_requested.emit(bool(checked))

        def _on_autocast_state_synced(checked: bool) -> None:
            # Programmatic state change (e.g., arm timeout auto-stop). Update
            # the play bar button without re-emitting toggle_requested to
            # avoid recursive feedback into the state machine.
            if self._btn_autocast.isChecked() == bool(checked):
                return
            self._btn_autocast.blockSignals(True)
            self._btn_autocast.setChecked(bool(checked))
            self._btn_autocast.setText("▶▶  parar" if checked else "▶▶  autocast")
            self._btn_autocast.blockSignals(False)

        self._btn_autocast.toggled.connect(_on_autocast_play_toggled)
        signal_bus.autocast_state_changed.connect(_on_autocast_state_synced)
        play_row_top.addWidget(self._btn_autocast, stretch=2)

        # Schedule-autocast (terceira posicao — invertido com autocast em
        # Iter 12). Width menor (minimumWidth=42) que o autocast adjacente.
        self._btn_schedule_autocast = QPushButton("agendar")
        self._btn_schedule_autocast.setProperty("testid", "schedule-autocast-btn")
        self._btn_schedule_autocast.setFixedHeight(32)
        self._btn_schedule_autocast.setMinimumWidth(42)
        self._btn_schedule_autocast.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_schedule_autocast.setToolTip(
            "Agendar disparo automatico do autocast"
        )
        self._btn_schedule_autocast.setStyleSheet(
            "QPushButton { background-color: #27272A; color: #D4D4D8;"
            "  border: 1px solid #52525B; border-radius: 5px;"
            "  font-size: 11px; font-weight: 600; padding: 0 8px; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FAFAFA; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; }"
        )
        self._btn_schedule_autocast.clicked.connect(
            lambda: signal_bus.schedule_autocast_requested.emit()
        )

        def _on_schedule_visual_changed(label: str, qss: str, tooltip: str) -> None:
            self._btn_schedule_autocast.setText(label)
            self._btn_schedule_autocast.setStyleSheet(qss)
            self._btn_schedule_autocast.setToolTip(tooltip)

        signal_bus.schedule_autocast_visual_changed.connect(_on_schedule_visual_changed)
        play_row_bottom.addWidget(self._btn_schedule_autocast, stretch=1)
        # schedule-autocast-btn e queue-div-use-kimi compartilham o mesmo
        # stretch para se redimensionarem identicamente conforme a janela.

        # Use Kimi checkbox — quando marcado, [Rodar próximo] (queue-btn-play-next)
        # clica na seta AZUL (kimi) ao inves da VERDE (claude) para items que
        # estao na whitelist Kimi (kimi_whitelist.is_kimi_compatible). Items
        # fora da whitelist seguem rodando no Claude independente do estado do
        # checkbox. Ocupa o slot que antes era do botão Autocast (removido).
        _kimi_box = QWidget()
        _kimi_box.setProperty("testid", "queue-div-use-kimi")
        _kimi_box.setFixedHeight(32)
        _kimi_box.setStyleSheet(
            "QWidget { background-color: #1C1C1F; border: 1px solid #3F3F46;"
            "  border-radius: 5px; }"
        )
        _kbl = QHBoxLayout(_kimi_box)
        _kbl.setContentsMargins(10, 0, 10, 0)
        _kbl.setSpacing(8)
        self._use_kimi_chk = QCheckBox("Use Kimi")
        self._use_kimi_chk.setProperty("testid", "queue-chk-use-kimi")
        self._use_kimi_chk.setToolTip(
            "Quando marcado, [Rodar próximo] dispara via Kimi (seta azul) para\n"
            "items kimi-compatible. Items fora da whitelist seguem rodando no\n"
            "Claude (seta verde) — checkbox e ignorado nesse caso."
        )
        self._use_kimi_chk.setStyleSheet(
            "QCheckBox { color: #FAFAFA; font-size: 11px; font-weight: 600;"
            "  background: transparent; border: none; padding: 0; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
            "QCheckBox::indicator:unchecked { background-color: #3F3F46;"
            "  border: 1px solid #52525B; border-radius: 3px; }"
            "QCheckBox::indicator:checked { background-color: #3B82F6;"
            "  border: 1px solid #3B82F6; border-radius: 3px; }"
            "QCheckBox::indicator:hover { border-color: #93C5FD; }"
        )
        _kbl.addWidget(self._use_kimi_chk)
        play_row_bottom.addWidget(_kimi_box, stretch=1)

        # --force Kimi checkbox (terceira posicao em play_row_bottom). Quando
        # marcado, o fluxo da seta verde (per-item e "Rodar proximo") passa a
        # cuspir no terminal-workspace-output em vez do interactive, /model e
        # /effort viram apenas bolinha amarela sem dispatch, /clear vai SO para
        # o workspace, e cada comando ganha 'skill:' apos a barra inicial
        # (/create-task -> /skill:create-task). Sem o check, comportamento
        # permanece identico ao anterior. Copia do layout do queue-div-use-kimi.
        _force_kimi_box = QWidget()
        _force_kimi_box.setProperty("testid", "queue-div-force-kimi")
        _force_kimi_box.setFixedHeight(32)
        _force_kimi_box.setStyleSheet(
            "QWidget { background-color: #1C1C1F; border: 1px solid #3F3F46;"
            "  border-radius: 5px; }"
        )
        _fkbl = QHBoxLayout(_force_kimi_box)
        _fkbl.setContentsMargins(10, 0, 10, 0)
        _fkbl.setSpacing(8)
        self._force_kimi_chk = QCheckBox("--force Kimi")
        self._force_kimi_chk.setProperty("testid", "queue-chk-force-kimi")
        self._force_kimi_chk.setToolTip(
            "Quando marcado, a seta verde dispara comandos no terminal\n"
            "workspace com prefixo /skill: ; /model e /effort viram apenas\n"
            "bolinha amarela; /clear vai so para o workspace. Sem o check,\n"
            "comportamento permanece identico ao anterior."
        )
        self._force_kimi_chk.setStyleSheet(
            "QCheckBox { color: #FAFAFA; font-size: 11px; font-weight: 600;"
            "  background: transparent; border: none; padding: 0; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
            "QCheckBox::indicator:unchecked { background-color: #3F3F46;"
            "  border: 1px solid #52525B; border-radius: 3px; }"
            "QCheckBox::indicator:checked { background-color: #3B82F6;"
            "  border: 1px solid #3B82F6; border-radius: 3px; }"
            "QCheckBox::indicator:hover { border-color: #93C5FD; }"
        )
        _fkbl.addWidget(self._force_kimi_chk)
        play_row_bottom.addWidget(_force_kimi_box, stretch=1)

        # Mutual exclusivity entre Use Kimi e --force Kimi (review MEDIUM 5).
        # Tambem esconde a seta azul per-item quando --force Kimi esta ativo
        # (review HIGH 1: spec "seta azul nao usada" interpretada como prescritiva).
        self._force_kimi_chk.toggled.connect(self._on_force_kimi_toggled)
        self._use_kimi_chk.toggled.connect(self._on_use_kimi_toggled)

        main_layout.addWidget(play_bar)

        # Template indicator label — shows which template/button was clicked
        self._template_label = QLabel("")
        self._template_label.setProperty("testid", "queue-template-label")
        self._template_label.setFixedHeight(28)
        self._template_label.setStyleSheet(
            "background-color: #1C1C1F; color: #A1A1AA;"
            " border-bottom: 1px solid #3F3F46;"
            " padding: 4px 10px; font-size: 11px;"
        )
        self._template_label.setVisible(False)
        main_layout.addWidget(self._template_label)

        # Last command played — shows the last ▶ command, one token per line
        self._last_cmd_label = QLabel("")
        self._last_cmd_label.setProperty("testid", "queue-last-command")
        self._last_cmd_label.setStyleSheet(
            "background-color: #1C1C1F; color: #D4D4D8;"
            " border-bottom: 1px solid #3F3F46;"
            " padding: 4px 10px; font-size: 11px; font-family: monospace;"
        )
        self._last_cmd_label.setWordWrap(True)
        self._last_cmd_label.setVisible(False)
        main_layout.addWidget(self._last_cmd_label)

        # Stacked content (empty state vs list)
        # Notepad foi removido em Iter 12 — _content_stack agora ocupa toda a
        # area abaixo da play_bar sem splitter intermediario.
        self._content_stack = QWidget()
        content_layout = QVBoxLayout(self._content_stack)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self._content_stack.setMinimumHeight(100)
        main_layout.addWidget(self._content_stack, stretch=1)

        # Empty state — placeholder vazio (texto e botao "Criar Pipeline"
        # removidos; criacao de pipeline acontece via outros fluxos).
        self._empty_widget = QWidget()
        el = QVBoxLayout(self._empty_widget)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.setSpacing(0)

        # List view
        self._list_widget = QWidget()
        list_layout = QVBoxLayout(self._list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background-color: #18181B; }"
            " QScrollBar:horizontal { background: #1C1C1F; height: 8px; border: none; }"
            " QScrollBar::handle:horizontal { background: #52525B; border-radius: 4px; min-width: 30px; }"
            " QScrollBar::handle:horizontal:hover { background: #71717A; }"
            " QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }"
            " QScrollBar:vertical { background: #1C1C1F; width: 8px; border: none; }"
            " QScrollBar::handle:vertical { background: #52525B; border-radius: 4px; min-height: 30px; }"
            " QScrollBar::handle:vertical:hover { background: #71717A; }"
            " QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._items_container = _DroppableContainer()
        self._items_container.setProperty("testid", "queue-command-list")
        self._items_container.setStyleSheet("background-color: #18181B;")
        self._items_container.setAcceptDrops(True)
        self._items_container.installEventFilter(self)
        self._items_layout = QVBoxLayout(self._items_container)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(0)
        self._items_layout.addStretch()

        scroll.setWidget(self._items_container)
        list_layout.addWidget(scroll, stretch=1)

        # Add button footer
        add_bar = QWidget()
        add_bar.setProperty("testid", "queue-add-bar")
        add_bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        add_bar.setFixedHeight(36)
        al = QHBoxLayout(add_bar)
        al.setContentsMargins(8, 4, 8, 4)
        add_btn = QPushButton("[+] Adicionar Comando")
        add_btn.setProperty("testid", "queue-btn-add-command")
        add_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #FBBF24;"
            "  border: none; font-size: 12px; }"
            "QPushButton:hover { color: #FDE68A; }"
        )
        add_btn.clicked.connect(self._on_inline_add_clicked)
        al.addWidget(add_btn)

        save_btn = QPushButton("💾 Salvar")
        save_btn.setProperty("testid", "queue-btn-save")
        save_btn.setToolTip("Salvar fila no JSON do projeto (Ctrl+S)")
        save_btn.setFixedHeight(26)
        save_btn.setEnabled(False)
        save_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 3px;"
            "  font-size: 11px; padding: 2px 8px; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; border-color: #FBBF24; }"
            "QPushButton:disabled { background-color: #27272A; color: #52525B; border-color: #3F3F46; }"
        )
        save_btn.clicked.connect(self.save_requested)
        al.addWidget(save_btn)
        self._save_btn = save_btn

        # "Próximo" button — shown only when an interactive command awaits advance
        next_bar = QWidget()
        next_bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        next_bar.setFixedHeight(40)
        nl = QHBoxLayout(next_bar)
        nl.setContentsMargins(8, 4, 8, 4)
        self._btn_next = QPushButton("Próximo →")
        self._btn_next.setFixedHeight(30)
        self._btn_next.setStyleSheet(
            "QPushButton { background-color: #16A34A; color: #FAFAF9;"
            "  border: none; border-radius: 4px; padding: 4px 16px;"
            "  font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._btn_next.setEnabled(False)
        self._btn_next.setVisible(False)
        nl.addWidget(self._btn_next, alignment=Qt.AlignmentFlag.AlignCenter)
        list_layout.addWidget(next_bar)
        self._next_bar = next_bar
        self._next_bar.setVisible(False)

        content_layout.addWidget(self._empty_widget)
        content_layout.addWidget(self._list_widget)
        self._list_widget.setVisible(False)
        self._add_bar = add_bar
        content_layout.addWidget(self._add_bar)

    def _connect_signals(self) -> None:
        signal_bus.pipeline_ready.connect(self.load_pipeline)
        signal_bus.command_started.connect(self._on_command_started)
        signal_bus.command_completed.connect(self._on_command_completed)
        signal_bus.command_failed.connect(self._on_command_failed)
        signal_bus.command_skipped.connect(self._on_command_skipped)
        signal_bus.pipeline_error_occurred.connect(self._on_pipeline_error_with_message)
        signal_bus.interactive_advance_ready.connect(self._on_interactive_advance_ready)
        signal_bus.instance_selected.connect(self._on_instance_selected)
        signal_bus.autocast_step_requested.connect(self._on_autocast_step_requested)
        self._btn_next.clicked.connect(self._on_btn_next_clicked)

    def _on_autocast_step_requested(self) -> None:
        """Programmatic click on `queue-btn-play-next` driven by the autocast loop.

        Emits no-op when the button is disabled (e.g. queue empty or already
        running) — the autocast state machine in MetricsBar interprets the
        absence of a busy transition as 'queue empty' and stops itself.
        """
        if self._play_btn.isEnabled():
            self._play_btn.click()

    # ──────────────────────────────────── Section tabs (accordion) ─── #

    def _build_section_grid(
        self, buttons: list[tuple[str, str, object, str] | QWidget], cols: int = 3
    ) -> QWidget:
        """Create a content widget with a 3-column grid of styled buttons."""
        content = QWidget()
        content.setStyleSheet("background-color: #27272A;")
        grid = QGridLayout(content)
        grid.setContentsMargins(5, 4, 5, 5)
        grid.setSpacing(3)
        for i, item in enumerate(buttons):
            if isinstance(item, QWidget):
                grid.addWidget(item, i // cols, i % cols)
            else:
                label, tooltip, callback, testid = item
                btn = QPushButton(label)
                btn.setToolTip(tooltip)
                btn.setStyleSheet(_SECTION_BTN_STYLE)
                if testid:
                    btn.setProperty("testid", testid)
                btn.clicked.connect(callback)
                grid.addWidget(btn, i // cols, i % cols)
        return content

    def _switch_section(self, index: int) -> None:
        """Switch to a section tab (accordion: only one open at a time)."""
        if index == self._active_section:
            return
        self._active_section = index
        self._apply_section_styles()

    def _apply_section_styles(self) -> None:
        """Update tab button styles and content visibility."""
        for i, (btn, content) in enumerate(zip(self._sec_tabs, self._sec_contents)):
            active = i == self._active_section
            btn.setStyleSheet(_TAB_ACTIVE_STYLE if active else _TAB_INACTIVE_STYLE)
            content.setVisible(active)

    # ──────────────────────────────────────────────────── Public API ─── #

    def set_pipeline_manager(self, pipeline_manager) -> None:
        """Inject the PipelineManager to enable can_reorder guards."""
        self._pipeline_manager = pipeline_manager

    def populate_prompts_tab(self, widgets: list[QWidget]) -> None:
        """Anexa os botoes de prompt-slot (MCP-test, Online Review, Progress, slot livre).

        Chamado por MainWindow apos build porque os handlers (clipboard,
        toast, _publish_to_terminal) dependem de estado vivo do MainWindow.
        Idempotente: limpa o layout antes de inserir.
        """
        layout = self._prompts_content_layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for w in widgets:
            layout.addWidget(w)
        layout.addStretch(1)

    def populate_actions_tab(self, widgets: list[QWidget]) -> None:
        """Anexa botoes da actions-tab (JSON, WS, mcp-codex, mcp-kimi, double-mcp, asq-user).

        Idempotente. Ver populate_prompts_tab para racional.
        """
        layout = self._actions_content_layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for w in widgets:
            layout.addWidget(w)
        layout.addStretch(1)

    def attach_tab_bar_extras(self, *extras: QWidget) -> None:
        """Anexa widgets ao tab_bar apos as 5 section tabs.

        Usado para terminal-route-toggles + toolbar-prompts-config-gear,
        que vivem visualmente como "abas extras" mas nao tem section
        content associado.
        """
        for w in extras:
            self._tab_bar_layout.addWidget(w)

    def _load_single_command(
        self,
        name: str,
        model: ModelName,
        interaction: InteractionType = InteractionType.INTERACTIVE,
    ) -> None:
        """Load a single command as a 1-item pipeline."""
        self._template_label.setText(f"  \U0001f4cb  {name}")
        self._template_label.setVisible(True)
        spec = CommandSpec(name=name, model=model, interaction_type=interaction, position=1)
        signal_bus.pipeline_ready.emit([spec])
        self._maybe_auto_save(name)

    def _load_quick_template(self, template: list[CommandSpec], *, name: str = "") -> None:
        """Emit pipeline_ready with a fresh copy of a factory template.

        Inserts a '/model X' row before each command where the model changes,
        so the user only needs to switch models at transition points.
        The model rows carry no config_path.
        Skips /clear for model tracking — no /model haiku before /clear.
        """
        if name:
            self._template_label.setText(f"  \U0001f4cb  {name}")
            self._template_label.setVisible(True)
            self._maybe_auto_save(name)

        raw = copy.deepcopy(template)

        expanded: list[CommandSpec] = []
        current_model = None
        for spec in raw:
            # Skip /clear for model tracking — it doesn't use a model
            if spec.name == "/clear":
                expanded.append(spec)
                continue  # Keep current_model — no /model needed if model didn't change
            # Skip injection when spec is already a /model switch (template has it explicit)
            if spec.name.startswith("/model "):
                current_model = spec.model
                expanded.append(spec)
                continue
            if spec.model != current_model:
                model_spec = CommandSpec(
                    name=f"/model {spec.model.value.lower()}",
                    model=spec.model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",  # no json appended for model-switch rows
                    position=0,      # renumbered below
                )
                expanded.append(model_spec)
                current_model = spec.model
            expanded.append(spec)

        for i, spec in enumerate(expanded, start=1):
            spec.position = i

        signal_bus.pipeline_ready.emit(expanded)

    def _on_brief_clicked(self) -> None:
        """Open Brief modal with [New] and [Feature] options."""
        from workflow_app.dialogs.brief_template_dialog import BriefTemplateDialog

        dlg = BriefTemplateDialog(parent=self)
        if dlg.exec() == BriefTemplateDialog.Accepted:
            self._load_quick_template(dlg.selected_template)

    # ────────────────────────────────────────────────────────── DCP ── #

    def _apply_dcp_reader_gating(self, workflow_content: QWidget) -> None:
        """Init-time gating for the workflow tab's DCP buttons.

        `[DCP: Specific-Flow]` is disabled when `workflow_app.dcp.READER_AVAILABLE`
        is false — it requires delivery_reader (T-035) to resolve the module and
        locate SPECIFIC-FLOW.json.

        Reading `dcp_pkg.READER_AVAILABLE` (instead of the imported symbol)
        lets pytest monkeypatch the flag without `importlib.reload`.
        """
        if dcp_pkg.READER_AVAILABLE:
            return
        logger.warning(
            "[DCP] reader ausente — DCP: Specific-Flow desabilitado"
        )
        for btn in workflow_content.findChildren(QPushButton):
            if btn.property("testid") == "queue-btn-dcp-specific-flow":
                btn.setEnabled(False)
                btn.setToolTip("Requer T-035 (reader)")
                break

    def _on_modules_clicked(self) -> None:
        """Carrega TEMPLATE_MODULES com fallback defensivo para ROCK-MAP.md.

        3 cenarios de fallback (conforme _DECISIONS-ITERS-9-11.md > Iter 9 > GAP 2.6
        e GAP 5.1):
          (a) ROCK-MAP.md ausente: toast info, log informativo.
          (b) ROCK-MAP.md malformado (parse error): toast warning, log com error_class.
          (c) ROCK-MAP.md com 0 rocks alem do skeleton: toast info "0 rocks, fila
              estatica (feature trivial)".

        Em todos os 3 cenarios, carrega TEMPLATE_MODULES estatico via
        `_load_quick_template` (alinhado com §21.4 v2). Expansao dinamica por
        N rocks fica para o module `modules-phase` (Sem 3).
        """
        import logging
        from pathlib import Path

        from workflow_app.config.app_state import app_state

        log = logging.getLogger(__name__)

        rock_map_path: Path | None = None
        fallback_reason = "missing"
        try:
            if app_state.has_config and app_state.config is not None:
                brief_root = getattr(app_state.config, "brief_root", None)
                project_dir = getattr(app_state.config, "project_dir", None)
                if brief_root and project_dir:
                    rock_map_path = Path(project_dir) / brief_root / "ROCK-MAP.md"
        except Exception as exc:  # noqa: BLE001 - defensivo, qualquer erro = fallback
            log.warning("[modules] erro ao resolver brief_root: %s: %s",
                        type(exc).__name__, exc)

        if rock_map_path is None or not rock_map_path.exists():
            log.info(
                "[modules] ROCK-MAP.md ausente (path=%s); usando TEMPLATE_MODULES "
                "estatico (operador nao rodou /break-intake ou projeto e single-rock).",
                rock_map_path,
            )
            signal_bus.toast_requested.emit("Sem ROCK-MAP, fila estatica", "info")
            return self._load_quick_template(TEMPLATE_MODULES, name="Modules")

        # ROCK-MAP.md existe; tentar parse defensivo
        try:
            content = rock_map_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning(
                "[modules] ROCK-MAP.md mal formado em %s (%s: %s); fallback para "
                "TEMPLATE_MODULES estatico. Re-rode /break-intake ou edite manualmente.",
                rock_map_path, type(exc).__name__, exc,
            )
            signal_bus.toast_requested.emit(
                "ROCK-MAP corrompido, fila estatica", "warning"
            )
            return self._load_quick_template(TEMPLATE_MODULES, name="Modules")

        # Conta rocks: linhas com pattern INTAKE-ROCK-{N}.md (exclui skeleton)
        import re

        try:
            rock_matches = re.findall(r"INTAKE-ROCK-(\d+)\.md", content)
            n_rocks = len(set(rock_matches))
        except Exception as exc:  # noqa: BLE001 - parse defensivo
            log.warning(
                "[modules] ROCK-MAP.md parse falhou em %s (%s: %s); fallback estatico.",
                rock_map_path, type(exc).__name__, exc,
            )
            signal_bus.toast_requested.emit(
                "ROCK-MAP corrompido, fila estatica", "warning"
            )
            return self._load_quick_template(TEMPLATE_MODULES, name="Modules")

        if n_rocks == 0:
            log.info(
                "[modules] ROCK-MAP.md tem 0 rocks alem do skeleton em %s; "
                "feature trivial, usando TEMPLATE_MODULES estatico "
                "(sem checklist-loop expansion).",
                rock_map_path,
            )
            signal_bus.toast_requested.emit(
                "0 rocks, fila estatica (feature trivial)", "info"
            )
            return self._load_quick_template(TEMPLATE_MODULES, name="Modules")

        # ROCK-MAP valido com N rocks - expansao dinamica fica para Sem 3 module.
        # Por enquanto carrega template base + log informativo.
        log.info(
            "[modules] ROCK-MAP.md OK em %s (%d rocks); carregando TEMPLATE_MODULES "
            "base (expansao dinamica pendente do module modules-phase).",
            rock_map_path, n_rocks,
        )
        return self._load_quick_template(TEMPLATE_MODULES, name="Modules")

    def _dcp_build_preflight(self) -> Optional[DcpBuildContext]:
        """Run the 6 MVP gates for `queue-btn-dcp-build` and return context.

        Gates (per Codex review T-013/T-052):
          1. has_config (project loaded)
          2. delivery.json exists + DeliveryFound (CLI requires it; no bootstrap)
          3. execution_mode != parallel-independent (or block ambiguous case)
          4. current_module exists, module exists, state != done
          5. MODULE-META.json exists, parses, has minimal canonical fields
          6. dependency readiness for pending → creation transitions

        On failure: emits the appropriate ``QMessageBox`` and returns ``None``
        (caller must abort). On success: returns ``DcpBuildContext`` with
        ``regenerate=True`` when module state is past pending so the
        SPECIFIC-FLOW is re-emitted without re-transitioning state.

        Reader-unavailable fallback (bare paste) is handled by the caller and
        is NOT a gate failure — preflight only runs when reader is available.
        """
        from PySide6.QtWidgets import QMessageBox

        from workflow_app.config.app_state import app_state

        # Gate 1 — project loaded
        if not app_state.has_config or app_state.config is None:
            logger.info("[DCP] build clicked without project — showing prompt")
            QMessageBox.information(
                self,
                "DCP",
                "Carregue um projeto (pill superior) antes de gerar pipeline DCP.",
            )
            return None
        config = app_state.config

        from workflow_app.dcp.specific_flow_handler import _resolve_wbs_root
        from workflow_app.services.delivery_reader import (
            DeliveryFound,
            DeliveryFutureVersion,
            DeliveryInvalid,
            DeliveryMissing,
            DeliveryReader,
        )

        wbs_root = _resolve_wbs_root(config)
        result = DeliveryReader().load(wbs_root)

        # Gate 2 — delivery.json present and structurally OK
        if isinstance(result, DeliveryMissing):
            QMessageBox.information(
                self, "DCP",
                "delivery.json ausente. Rode primeiro a Phase A:\n"
                "  1. Brief — Novo Projeto (queue-btn-brief-new), e\n"
                "  2. Modules (Creation) (queue-btn-modules)\n"
                "Depois volte ao DCP: Gerar Pipeline.",
            )
            return None
        if isinstance(result, DeliveryInvalid):
            body, clipboard_text = format_delivery_invalid_popup(
                result.path, result.error, result.details,
            )
            project_slug = (
                getattr(config, "project_name", None)
                or getattr(config, "name", None)
                or "(desconhecido)"
            )
            # Telemetry: count of distinct schema errors and project slug so
            # operators can correlate popups with logs without re-parsing JSON.
            try:
                _err_count = (
                    len(json.loads(result.details))
                    if result.details
                    else 0
                )
            except (json.JSONDecodeError, TypeError):
                _err_count = 0
            logger.info(
                "DCP preflight Gate 2 fail: %d errors in delivery.json (project=%s)",
                _err_count, project_slug,
            )
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("DCP build cancelado: delivery.json invalido")
            box.setText(body)
            box.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            copy_btn = box.addButton(
                "Copiar erros", QMessageBox.ButtonRole.ActionRole
            )
            close_btn = box.addButton(
                "Fechar", QMessageBox.ButtonRole.RejectRole
            )
            box.setDefaultButton(close_btn)
            box.exec()
            if box.clickedButton() is copy_btn:
                QApplication.clipboard().setText(clipboard_text)
                signal_bus.toast_requested.emit(
                    "Erros copiados para o clipboard.", "info"
                )
            return None
        if isinstance(result, DeliveryFutureVersion):
            QMessageBox.information(self, "DCP", result.message)
            return None

        assert isinstance(result, DeliveryFound)
        delivery = result.delivery

        # Gate 3 — parallel-independent requires explicit module selection
        if delivery.execution_mode == "parallel-independent":
            QMessageBox.information(
                self, "DCP",
                "execution_mode=parallel-independent requer selecao explicita "
                "do modulo. Use o botao DCP no card do modulo desejado.",
            )
            return None

        # Gate 4 — current_module is set, exists in modules, not done
        cm_id = delivery.current_module
        if not cm_id:
            QMessageBox.information(
                self, "DCP",
                "current_module nao definido em delivery.json. "
                "Rode /modules:create-structure ou /delivery:validate.",
            )
            return None
        if delivery.modules and all(
            m.state == "done" for m in delivery.modules.values()
        ):
            QMessageBox.information(
                self, "DCP", "Todos os modulos estao concluidos."
            )
            return None
        module = delivery.modules.get(cm_id)
        if module is None:
            QMessageBox.information(
                self, "DCP",
                f"current_module={cm_id!r} nao existe em modules. "
                "Rode /delivery:validate.",
            )
            return None
        if module.state == "done":
            QMessageBox.information(
                self, "DCP",
                f"Modulo {cm_id!r} ja concluido. "
                "Use /delivery:sign-off ou inicie o proximo modulo.",
            )
            return None

        # Gate 5 — MODULE-META.json exists, parses, has minimal canonical fields
        meta_path = wbs_root / "modules" / cm_id / "MODULE-META.json"
        if not meta_path.exists():
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json ausente em {meta_path.name}. Phase A nao "
                "foi completada. Rode Modules (queue-btn-modules).",
            )
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json corrupto: {exc}. "
                "Re-rode Modules (queue-btn-modules).",
            )
            return None
        required_keys = {"module_id", "module_name", "module_type"}
        missing = required_keys - set(meta.keys())
        if missing:
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json incompleto. Faltam: {sorted(missing)}. "
                "Re-rode Modules (queue-btn-modules).",
            )
            return None
        # Identity check — meta.module_id MUST match delivery.json[modules] key,
        # otherwise we'd run pipeline against the wrong module's spec.
        if meta.get("module_id") != cm_id:
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json identifica module_id={meta.get('module_id')!r} "
                f"mas delivery.json aponta current_module={cm_id!r}. "
                "Resolva o desalinhamento antes de prosseguir.",
            )
            return None

        # Gate 6 — dependency readiness (mirrors CLI invariant I-10, step 11).
        # Only for pending → creation; modules past pending were already gated at
        # their own transition. Without this check the button pastes a command
        # destined to exit 1 with a cryptic CLI message.
        if module.state == "pending" and module.dependencies:
            blockers = [
                dep_id
                for dep_id in module.dependencies
                if dep_id not in delivery.modules
                or delivery.modules[dep_id].state != "done"
            ]
            if blockers:
                dep_lines = []
                for dep_id in blockers:
                    dep = delivery.modules.get(dep_id)
                    state_label = dep.state if dep else "ausente"
                    dep_lines.append(f"  • {dep_id} — {state_label}")
                QMessageBox.warning(
                    self,
                    "DCP — Dependências não concluídas",
                    f"Módulo {cm_id!r} não pode iniciar (pending → creation).\n\n"
                    "Dependências pendentes:\n" + "\n".join(dep_lines) + "\n\n"
                    "Complete o loop de cada dependência até state=done primeiro.",
                )
                return None

        # All gates passed — choose --regenerate when module is past pending
        regenerate = module.state != "pending"
        return DcpBuildContext(
            cm_id=cm_id,
            module_state=module.state,
            regenerate=regenerate,
            wbs_root=wbs_root,
            delivery=delivery,
        )

    @staticmethod
    def _read_flow_cmd_count(flow_path: Path) -> int | None:
        """Return the length of `commands[]` in SPECIFIC-FLOW.json, or None
        when the file cannot be parsed. Shared by the legacy paste handler
        and the new B-dcp pipeline handler so both surface the same
        metadata in the destructive-guard modal.
        """
        try:
            flow_data = json.loads(flow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(flow_data, dict):
            return None
        commands_raw = flow_data.get("commands")
        if not isinstance(commands_raw, list):
            return None
        return len(commands_raw)

    def _on_dcp_build_pipeline_clicked(self) -> None:
        """Enqueue the B-dcp pipeline with 6 visible items in queue-command-list.

        Pipeline shape (positions 1..6):
            1. /build-module-pipeline [--regenerate] --module {N} {rel_cfg}
            2. /dcp:congruence-check --module {N}
            3. /dcp:temporality-check --module {N}
            4. /dcp:meta-completeness --module {N}
            5. /dcp:directive-injector --module {N} --in-place
            6. (local-action) dcp-load-specific-flow

        Uses `_dcp_build_preflight` for gate evaluation, including the
        destructive guard (ConfirmRegenerateSpecificFlowModal) when
        `--regenerate` would overwrite an existing SPECIFIC-FLOW.json.

        Arms `self._pending_dcp_load_ctx` so the local action at position 6
        (`_handle_dcp_load_specific_flow`) can pick up the same module
        context after the 5 slash commands have regenerated the flow file.
        """
        from workflow_app.config.app_state import app_state

        ctx = self._dcp_build_preflight()
        if ctx is None:
            return

        # Defensive: preflight requires has_config==True, so config is non-None.
        config = app_state.config
        assert config is not None

        # Destructive guard — when --regenerate AND SPECIFIC-FLOW.json
        # already exists on disk, surface metadata + warn about manual-edit
        # loss before enqueueing. Mirrors the legacy paste handler.
        if ctx.regenerate:
            flow_path = ctx.wbs_root / "modules" / ctx.cm_id / "SPECIFIC-FLOW.json"
            if flow_path.exists():
                from workflow_app.dialogs.confirm_regenerate_specific_flow_modal import (
                    ConfirmRegenerateSpecificFlowModal,
                )
                command_count = self._read_flow_cmd_count(flow_path)
                modal = ConfirmRegenerateSpecificFlowModal(
                    flow_path=flow_path,
                    command_count=command_count,
                    cm_id=ctx.cm_id,
                    parent=self,
                )
                if modal.exec() != QDialog.DialogCode.Accepted:
                    logger.info(
                        "[DCP] pipeline regen cancelado pelo usuario "
                        "(modulo=%s, cmds=%s)",
                        ctx.cm_id, command_count,
                    )
                    return

        # Resolve helpers (kept lazy to avoid a heavy import at module load).
        from workflow_app.dcp.specific_flow_handler import (
            _module_number,
            _relative_config_path,
        )

        rel_cfg = _relative_config_path(config.config_path)
        module_num = _module_number(ctx.cm_id)
        regen_flag = " --regenerate" if ctx.regenerate else ""

        specs: list[CommandSpec] = [
            CommandSpec(
                name=f"/build-module-pipeline{regen_flag} --module {module_num} {rel_cfg}",
                model=ModelName.OPUS,
                interaction_type=InteractionType.AUTO,
                position=1,
                effort=EffortLevel.HIGH,
            ),
            CommandSpec(
                name=f"/dcp:congruence-check --module {module_num}",
                model=ModelName.HAIKU,
                interaction_type=InteractionType.AUTO,
                position=2,
                effort=EffortLevel.HIGH,
            ),
            CommandSpec(
                name=f"/dcp:temporality-check --module {module_num}",
                model=ModelName.HAIKU,
                interaction_type=InteractionType.AUTO,
                position=3,
                effort=EffortLevel.STANDARD,
            ),
            CommandSpec(
                name=f"/dcp:meta-completeness --module {module_num}",
                model=ModelName.HAIKU,
                interaction_type=InteractionType.AUTO,
                position=4,
                effort=EffortLevel.STANDARD,
            ),
            CommandSpec(
                name=f"/dcp:directive-injector --module {module_num} --in-place",
                model=ModelName.HAIKU,
                interaction_type=InteractionType.AUTO,
                position=5,
                effort=EffortLevel.STANDARD,
            ),
            CommandSpec(
                name="DCP: Carregar Specific-Flow",
                model=ModelName.HAIKU,
                interaction_type=InteractionType.AUTO,
                position=6,
                effort=EffortLevel.LOW,
                kind="local-action",
                local_action_id="dcp-load-specific-flow",
            ),
        ]

        self._pending_dcp_load_ctx = ctx
        logger.info(
            "[DCP] enqueueing B-dcp pipeline (modulo=%s, regenerate=%s, items=%d)",
            ctx.cm_id, ctx.regenerate, len(specs),
        )
        signal_bus.pipeline_ready.emit(specs)

    @staticmethod
    def _emit_dcp_meta_toast(module_dir: Path, *, verbose: bool = False) -> None:
        """Read ``meta-gaps-report.json`` from ``module_dir`` and emit a
        non-blocking toast via ``signal_bus.toast_requested``.

        Mapping (anti Zero Silencio):
          - ``total_gaps == 0`` AND ``verbose``  -> "success" (5s).
          - ``total_gaps == 0`` AND NOT verbose  -> suppressed (avoid noise).
          - ``total_gaps > 0`` AND any gap has ``confidence == "low"`` ->
            "warning" (6s) — pushes operator to act.
          - ``total_gaps > 0`` AND all gaps ``high``/``medium`` -> "info" (5s).

        The B-dcp gate 4 (``/dcp:meta-completeness``) is advisory: it
        writes ``meta-gaps-report.json`` with ``total_gaps`` and
        ``by_confidence`` aggregates. This handler runs at position 6 of
        the pipeline (after gate 4), reads the report and surfaces it as
        a toast so the operator never has to grep the audit dir.

        Silent no-op when the report is missing or malformed — gate 4
        may have skipped if MODULE-META was already validated within the
        300s idempotency TTL (and even in that case it does NOT bump
        the report). In NO_OP mode the report still exists; only true
        absence (gate 4 never ran for this module) yields silence here,
        which is acceptable because earlier validation gates already
        surfaced their own toasts.
        """
        report_path = module_dir / "meta-gaps-report.json"
        if not report_path.exists():
            return
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(report, dict):
            return

        total_gaps = report.get("total_gaps")
        if not isinstance(total_gaps, int):
            return
        by_confidence = report.get("by_confidence") or {}
        low_count = int(by_confidence.get("low", 0) or 0)

        if total_gaps == 0:
            if verbose:
                signal_bus.toast_requested.emit("Meta: completo (0 gaps)", "success")
            return

        if low_count > 0:
            signal_bus.toast_requested.emit(
                f"Meta: {total_gaps} gaps ({low_count} low confidence) "
                f"-- ver meta-gaps-report.json",
                "warning",
            )
        else:
            signal_bus.toast_requested.emit(
                f"Meta: {total_gaps} gaps (advisory) "
                f"-- ver meta-gaps-report.json",
                "info",
            )

    @staticmethod
    def _audit_display_dcp_reports(module_dir: Path, cm_id: str) -> None:
        """Surface congruence-report.json / temporality-report.json as a
        non-blocking informational toast.

        Replaces the legacy ``_check_dcp_validation_reports`` gate
        (task-028). Post-matrix architecture: the matrix already carries
        ``filter[]`` with bits flipped by the B-dcp gates, so the queue
        derived from it cannot contain commands that violated congruence
        or temporality. There is no "load anyway with violations" path
        because violations already zeroed the corresponding bits.

        The reports are kept as audit-only mirror: this method reads
        their flip counts and emits a single info toast so the operator
        has a one-glance summary without grepping the audit dir.

        Silent no-op when both reports are missing or unreadable
        (e.g. bare /dcp:specific-flow path without preflight).
        """
        flips_congruence = 0
        flips_temporality = 0
        for fname, count_key, target in (
            ("congruence-report.json", "incoherent_count", "congruence"),
            ("temporality-report.json", "violations_count", "temporality"),
        ):
            report_path = module_dir / fname
            if not report_path.exists():
                continue
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(report, dict):
                continue
            if report.get("module_id") and report["module_id"] != cm_id:
                continue
            count = report.get(count_key, 0)
            if isinstance(count, int) and count > 0:
                if target == "congruence":
                    flips_congruence = count
                else:
                    flips_temporality = count

        if flips_congruence == 0 and flips_temporality == 0:
            return

        signal_bus.toast_requested.emit(
            f"DCP: congruence flippou {flips_congruence} bits, "
            f"temporality {flips_temporality} bits",
            "info",
        )

    def _handle_dcp_load_specific_flow(self, spec: CommandSpec) -> bool:
        """Local-action callable invoked at queue position 6 of the B-dcp
        pipeline. Consumes `self._pending_dcp_load_ctx` to locate the
        freshly regenerated SPECIFIC-FLOW.json and emit it via
        `_enqueue_specific_flow`.

        Steps:
          1. Pop `_pending_dcp_load_ctx`; refuse with a toast if absent.
          2. Re-read delivery.json (mutated by the 5 previous pipeline steps).
          3. Resolve SPECIFIC-FLOW.json for the same module via DCP-9.2 cascade.
          4. Delegate to `_enqueue_specific_flow` (shared with the manual
             [DCP: Specific-Flow] button and `/dcp:build-and-load`).

        Returns True only when the enqueue succeeds; False on any guard
        miss (no context, delivery indisponivel, flow ausente, enqueue
        rejeitado). Always clears `_pending_dcp_load_ctx` before returning
        so a subsequent click rearms cleanly.
        """
        from workflow_app.config.app_state import app_state
        from workflow_app.services.delivery_reader import (
            DeliveryFound,
            DeliveryReader,
            resolve_specific_flow,
        )

        ctx = self._pending_dcp_load_ctx
        if ctx is None:
            signal_bus.toast_requested.emit(
                "DCP load chamado sem contexto pending. "
                "Re-clique [DCP: Build Module Pipeline].",
                "error",
            )
            logger.warning(
                "[DCP] dcp-load-specific-flow disparado sem contexto pendente "
                "(spec=%s); ignorando.", spec.name,
            )
            return False

        self._pending_dcp_load_ctx = None

        result = DeliveryReader().load(ctx.wbs_root)
        if not isinstance(result, DeliveryFound):
            signal_bus.toast_requested.emit(
                f"delivery.json indisponivel apos pipeline DCP: "
                f"{type(result).__name__}",
                "error",
            )
            return False

        config = app_state.config
        if config is None:
            signal_bus.toast_requested.emit(
                "Projeto descarregado entre build e load. "
                "Recarregue o projeto e re-clique [DCP: Build Module Pipeline].",
                "error",
            )
            return False

        flow_path = resolve_specific_flow(
            result.delivery,
            ctx.cm_id,
            config.project_dir,
            custom_workflow_root=config.custom_workflow_root or None,
        )
        if flow_path is None or not flow_path.exists():
            signal_bus.toast_requested.emit(
                f"Pipeline rodou mas SPECIFIC-FLOW.json nao apareceu para "
                f"{ctx.cm_id}. Verifique logs de /build-module-pipeline na "
                f"sessao Claude.",
                "warning",
            )
            return False

        module_dir = flow_path.parent

        # Surface advisory output of gate 4 (/dcp:meta-completeness) as a
        # non-blocking toast. Does not block the load — meta-completeness is
        # advisory by contract (NUNCA flippa filter[], NUNCA bloqueia paste).
        self._emit_dcp_meta_toast(module_dir, verbose=False)

        # task-028 (st-05): congruence/temporality reports are audit-only
        # now. Violations have already flipped filter[] bits in the matrix;
        # the queue derived from it cannot contain commands tied to flipped
        # bits, so there is no "load anyway" path. We surface flip counts
        # as a single info toast for operator awareness.
        self._audit_display_dcp_reports(module_dir, ctx.cm_id)

        # task-027 (st-05): matrix-driven in-memory derivation supersedes the
        # SPECIFIC-FLOW.json read path. We try the matrix first; on
        # FileNotFoundError / ValidationError the legacy disk-based path is
        # used so the widget keeps working in environments where
        # DCP-COMMAND-MATRIX.json has not yet been generated.
        matrix_queue = self._derive_queue_from_matrix_inmemory(ctx, config)
        if matrix_queue is not None:
            signal_bus.pipeline_ready.emit(matrix_queue)
            logger.info(
                "[DCP] queue derivada in-memory (matrix) | modulo=%s count=%d",
                ctx.cm_id, len(matrix_queue),
            )
            return True

        return self._enqueue_specific_flow(
            flow_path=flow_path,
            cm_id=ctx.cm_id,
            default_project_name=config.project_name,
            prefix_commands=None,
        )

    def _derive_queue_from_matrix_inmemory(
        self,
        ctx: "DcpBuildContext",
        config: "PipelineConfig",
    ) -> Optional[list[CommandSpec]]:
        """Try to derive the queue in-memory from DCP-COMMAND-MATRIX.json.

        Returns the rendered `list[CommandSpec]` when the matrix is present
        and validates against the Pydantic model (task-027 / st-05 algorithm
        9-17). Returns None when the matrix is absent OR cannot be validated;
        the caller falls back to the legacy SPECIFIC-FLOW.json read path.

        Side effects on success:
          - Appends a `load-queue` entry to the in-memory matrix module trail.
            Persistence is left to the next gate that writes the matrix back
            (write-on-mutate gates already cover this; we never write back
            from here to keep the load read-only at I/O level).
        """
        from workflow_app.dcp.queue_derivation import (
            build_load_queue_trail_entry,
            derive_queue_from_matrix,
            load_matrix,
        )
        from workflow_app.models.dcp_command_matrix import TrailEntry

        dcp_root_raw = getattr(config, "dcp_root", "") or ""
        if not dcp_root_raw:
            return None
        dcp_root = Path(dcp_root_raw)
        if not dcp_root.is_absolute():
            dcp_root = (Path(config.project_dir) / dcp_root_raw).resolve()

        try:
            matrix = load_matrix(dcp_root)
        except FileNotFoundError:
            return None
        except Exception as exc:  # ValidationError + JSON errors
            signal_bus.toast_requested.emit(
                f"DCP-COMMAND-MATRIX.json invalido ({type(exc).__name__}): "
                f"caindo para SPECIFIC-FLOW.json.",
                "warning",
            )
            logger.warning(
                "[DCP] matrix invalida em %s: %s — fallback para SPECIFIC-FLOW.json",
                dcp_root, exc,
            )
            return None

        # task-028 (st-05): matrix-driven identity guard.
        # Replaces the legacy scope_module check (still kept in
        # _enqueue_specific_flow for the legacy fallback path). When the
        # operator-active module is absent from the matrix, we cannot
        # safely derive a queue in-memory — fall back to legacy with an
        # explicit operator toast pointing at the regeneration entrypoint.
        matrix_module = matrix.modules.get(ctx.cm_id)
        if matrix_module is None:
            signal_bus.toast_requested.emit(
                f"modulo {ctx.cm_id} ausente da matrix - "
                f"regenerar via [DCP: Build Module Pipeline]",
                "warning",
            )
            logger.warning(
                "[DCP] cm_id=%s ausente em matrix.modules — fallback para SPECIFIC-FLOW.json",
                ctx.cm_id,
            )
            return None

        # Soft warning: current_module pode estar stale entre build-matrix
        # e load (sequencial da pipeline e quem garante coerencia). Nao
        # bloqueia, apenas sinaliza.
        if matrix.current_module and matrix.current_module != ctx.cm_id:
            signal_bus.toast_requested.emit(
                f"matrix.current_module={matrix.current_module} difere do "
                f"modulo ativo {ctx.cm_id} (warning soft)",
                "info",
            )
            logger.info(
                "[DCP] current_module stale: matrix=%s ativo=%s",
                matrix.current_module, ctx.cm_id,
            )

        # Defense-in-depth: schema_version range + filter length cross-check.
        # Pydantic ja valida ambos via Literal["1.0.1"] e validators internos,
        # mas mantemos a checagem explicita para detectar drift caso o
        # contrato relaxe no futuro.
        supported_schemas = {"1.0.1"}
        if matrix.schema_version not in supported_schemas:
            signal_bus.toast_requested.emit(
                f"matrix.schema_version={matrix.schema_version} fora da "
                f"faixa suportada ({sorted(supported_schemas)}). "
                f"Caindo para SPECIFIC-FLOW.json.",
                "warning",
            )
            return None
        if len(matrix_module.filter) != len(matrix.command_index):
            signal_bus.toast_requested.emit(
                f"matrix modules[{ctx.cm_id}].filter length "
                f"({len(matrix_module.filter)}) != command_index length "
                f"({len(matrix.command_index)}). Regenere via "
                f"[DCP: Build Module Pipeline].",
                "warning",
            )
            return None

        # Soft warning: foundations-pure modules legitimamente tem
        # A-creation == 0 (sem loop A). Para todos os outros casos,
        # loop_multiplier["A-creation"] < 1 e sinal de drift.
        a_creation = matrix_module.loop_multiplier.get("A-creation", 0)
        is_foundations_pure = bool(getattr(matrix_module, "foundations_pure", False))
        if a_creation < 1 and not is_foundations_pure:
            signal_bus.toast_requested.emit(
                f"matrix modules[{ctx.cm_id}].loop_multiplier.A-creation"
                f"={a_creation} < 1 e modulo nao e foundations-pure "
                f"(warning soft)",
                "info",
            )

        commit_variant = getattr(config, "commit_type", "") or "simple"
        wbs_root = ctx.wbs_root

        try:
            queue = derive_queue_from_matrix(
                matrix,
                ctx.cm_id,
                wbs_root=wbs_root,
                config_path=getattr(config, "config_path", "") or "",
                commit_variant=commit_variant,
            )
        except Exception as exc:
            signal_bus.toast_requested.emit(
                f"Erro ao derivar fila in-memory: {exc}. "
                f"Caindo para SPECIFIC-FLOW.json.",
                "warning",
            )
            logger.warning(
                "[DCP] derive_queue_from_matrix falhou para %s: %s",
                ctx.cm_id, exc, exc_info=True,
            )
            return None

        if not queue:
            logger.warning(
                "[DCP] queue derivada vazia para modulo=%s — fallback para SPECIFIC-FLOW.json",
                ctx.cm_id,
            )
            return None

        is_last = (
            matrix.execution_order[-1] == ctx.cm_id
            if matrix.execution_order
            else False
        )
        try:
            trail_dict = build_load_queue_trail_entry(
                ctx.cm_id, len(queue), is_last,
            )
            entry = TrailEntry.model_validate(trail_dict)
            matrix.modules[ctx.cm_id].trail.append(entry)
        except Exception as exc:  # pragma: no cover — trail append is non-blocking
            logger.warning(
                "[DCP] trail load-queue append falhou (nao bloqueante): %s", exc,
            )

        return queue

    def _on_dcp_specific_flow_clicked(self) -> None:
        """Load SPECIFIC-FLOW.json for the active module into the command queue.

        Reads delivery.json to resolve `current_module`, then uses the
        DCP-9.2 cascade (artifacts.last_specific_flow -> custom_workflow_root)
        to locate the JSON and populate the queue via `pipeline_ready`.
        The user can then dispatch each item with [Rodar próximo].
        """
        from workflow_app.config.app_state import app_state

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um projeto antes de usar DCP: Specific-Flow.", "warning"
            )
            return

        config = app_state.config

        from workflow_app.dcp.specific_flow_handler import (
            _next_non_done_module_id,
            _resolve_wbs_root,
        )
        from workflow_app.services.delivery_reader import (
            DeliveryFound,
            DeliveryFutureVersion,
            DeliveryInvalid,
            DeliveryMissing,
            DeliveryReader,
            resolve_specific_flow,
        )

        wbs_root = _resolve_wbs_root(config)
        result = DeliveryReader().load(wbs_root)

        if isinstance(result, DeliveryMissing):
            signal_bus.toast_requested.emit(
                "delivery.json ausente. Rode /delivery:init primeiro.", "warning"
            )
            return
        if isinstance(result, DeliveryInvalid):
            signal_bus.toast_requested.emit(
                f"delivery.json invalido: {result.error}. Rode /delivery:validate.", "warning"
            )
            return
        if isinstance(result, DeliveryFutureVersion):
            signal_bus.toast_requested.emit(result.message, "warning")
            return

        assert isinstance(result, DeliveryFound)
        delivery = result.delivery
        cm_id = delivery.current_module

        # Auto-advance: se current_module aponta para um modulo done (situacao
        # comum ao retomar no dia seguinte), usa o proximo modulo nao-done.
        if not cm_id or (delivery.modules.get(cm_id) and delivery.modules[cm_id].state == "done"):
            cm_id = _next_non_done_module_id(delivery)

        if not cm_id:
            signal_bus.toast_requested.emit("Todos os modulos estao concluidos.", "warning")
            return

        module = delivery.modules.get(cm_id)
        if module is None:
            signal_bus.toast_requested.emit(
                f"Modulo {cm_id!r} nao existe no delivery.json. Rode /delivery:validate.", "warning"
            )
            return

        flow_path = resolve_specific_flow(
            delivery,
            cm_id,
            config.project_dir,
            custom_workflow_root=config.custom_workflow_root or None,
        )

        if flow_path is None or not flow_path.exists():
            dep_extra = ""
            if module is not None and module.state == "pending" and module.dependencies:
                unmet = [
                    dep_id for dep_id in module.dependencies
                    if dep_id not in delivery.modules
                    or delivery.modules[dep_id].state != "done"
                ]
                if unmet:
                    labels = [
                        f"{d}({delivery.modules[d].state})"
                        if d in delivery.modules else f"{d}(ausente)"
                        for d in unmet
                    ]
                    dep_extra = f" Deps bloqueantes: {', '.join(labels)}."
            signal_bus.toast_requested.emit(
                f"SPECIFIC-FLOW.json nao encontrado para {cm_id}. "
                f"Execute [DCP: Gerar Pipeline] primeiro.{dep_extra}",
                "warning",
            )
            return

        # M5 hibrida (TRILHA 3 — meta-loop estrategia-de-separacao):
        # carga delegada para helper privado reusavel por /dcp:build-and-load.
        self._enqueue_specific_flow(
            flow_path=flow_path,
            cm_id=cm_id,
            default_project_name=config.project_name,
            prefix_commands=None,
        )

    def _enqueue_specific_flow(
        self,
        flow_path: Path,
        cm_id: str,
        default_project_name: str,
        prefix_commands: list[dict] | None = None,
    ) -> bool:
        """Le SPECIFIC-FLOW.json e enfileira commands na fila do workflow-app.

        Helper privado extraido em 2026-05-13 (TRILHA 3 + POS-TRILHA do meta-loop
        estrategia-de-separacao, decisao M5 hibrida do usuario). Reusado por:
          - _on_dcp_specific_flow_clicked (caminho UX click-to-load)
          - /dcp:build-and-load (caminho programatico atomico build+validate+load)

        Args:
          flow_path: Path do SPECIFIC-FLOW.json a carregar.
          cm_id: module_id para label da fila.
          default_project_name: nome de projeto fallback quando SPECIFIC-FLOW.json
            nao declarar `project` field.
          prefix_commands: lista opcional de dicts com schema compativel
            (`{name, model, effort, phase, interaction}`) a prependar antes dos
            commands do flow. Usado por /dcp:build-and-load para injetar
            /dcp:congruence-check, /dcp:temporality-check, etc antes do flow.

        Returns:
          True se enqueue foi bem sucedido (`signal_bus.pipeline_ready` emitido).
          False quando flow_path invalido, JSON corrupto, ou specs vazias
          (toasts ja emitidos antes do return).
        """
        try:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            signal_bus.toast_requested.emit(f"Erro ao ler SPECIFIC-FLOW.json: {exc}", "error")
            return False

        if not isinstance(data, dict):
            signal_bus.toast_requested.emit(
                "SPECIFIC-FLOW.json invalido: root deve ser um objeto JSON.", "error"
            )
            return False

        # Identity guard: scope_module.module_id must match cm_id when present.
        # Without this, Level-2 fallback ({wbs_root}/workflow-app/SPECIFIC-FLOW.json)
        # could silently load a stale flow from a different module.
        scope_module = data.get("scope_module")
        if isinstance(scope_module, dict):
            flow_module_id = scope_module.get("module_id")
            if flow_module_id and flow_module_id != cm_id:
                signal_bus.toast_requested.emit(
                    f"SPECIFIC-FLOW.json pertence a '{flow_module_id}' mas o modulo "
                    f"ativo e '{cm_id}'. Regenere via [DCP: Build + Load].",
                    "warning",
                )
                logger.warning(
                    "[DCP] module_id mismatch: flow=%s, cm_id=%s — carga abortada",
                    flow_module_id, cm_id,
                )
                return False

        commands_raw = data.get("commands", [])
        if not isinstance(commands_raw, list):
            signal_bus.toast_requested.emit(
                "SPECIFIC-FLOW.json invalido: campo 'commands' deve ser uma lista.", "error"
            )
            return False

        # prefix_commands prependa antes do flow (uso programatico via /dcp:build-and-load)
        if prefix_commands:
            commands_raw = list(prefix_commands) + commands_raw

        # Onda 4: honor operator-persisted skip list. overrides.skipped[]
        # is a list of fully-rendered command name strings. Filter happens
        # before model/effort mapping so skipped commands never enter the queue.
        overrides = data.get("overrides") if isinstance(data.get("overrides"), dict) else {}
        skipped_raw = overrides.get("skipped") if isinstance(overrides, dict) else None
        skipped_set: set[str] = (
            {s for s in skipped_raw if isinstance(s, str) and s}
            if isinstance(skipped_raw, list) else set()
        )
        if skipped_set:
            before = len(commands_raw)
            commands_raw = [
                c for c in commands_raw
                if not (isinstance(c, dict) and c.get("name") in skipped_set)
            ]
            removed = before - len(commands_raw)
            if removed:
                logger.info(
                    "[DCP] overrides.skipped filtrou %d comandos (de %d para %d)",
                    removed, before, len(commands_raw),
                )

        _model_map = {
            "opus": ModelName.OPUS,
            "sonnet": ModelName.SONNET,
            "haiku": ModelName.HAIKU,
        }
        _effort_map = {
            "low": EffortLevel.LOW,
            "medium": EffortLevel.STANDARD,
            "standard": EffortLevel.STANDARD,
            "high": EffortLevel.HIGH,
            "max": EffortLevel.MAX,
        }
        specs: list[CommandSpec] = []
        for i, cmd in enumerate(commands_raw, start=1):
            if not isinstance(cmd, dict):
                continue
            name = cmd.get("name", "").strip()
            if not name:
                continue
            model = _model_map.get(str(cmd.get("model", "sonnet")).lower(), ModelName.SONNET)
            interaction = (
                InteractionType.INTERACTIVE
                if str(cmd.get("interaction", "auto")).lower() == "inter"
                else InteractionType.AUTO
            )
            effort = _effort_map.get(str(cmd.get("effort", "medium")).lower(), EffortLevel.STANDARD)
            phase = str(cmd.get("phase", "F?"))
            specs.append(
                CommandSpec(
                    name=name,
                    model=model,
                    interaction_type=interaction,
                    config_path="",
                    position=i,
                    effort=effort,
                    phase=phase,
                )
            )

        if not specs:
            signal_bus.toast_requested.emit("SPECIFIC-FLOW.json esta vazio.", "warning")
            return False

        project = data.get("project", default_project_name)
        logger.info("[DCP] loading pipeline from %s (%d commands, prefix=%d)",
                    flow_path, len(specs), len(prefix_commands or []))
        self._template_label.setText(f"  \U0001f4cb  DCP: {cm_id} — {project}")
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"DCP {cm_id}")
        signal_bus.pipeline_ready.emit(specs)
        # Onda 4: arm DCP context AFTER pipeline_ready. load_pipeline()
        # resets _current_dcp_flow_path to None at its start; we re-arm
        # here so subsequent _on_remove_requested calls persist to disk.
        # Order matters: emit is synchronous (Qt direct connection), so
        # load_pipeline runs to completion before this assignment.
        self._current_dcp_flow_path = flow_path
        return True

    def _on_cmd_single_clicked(self) -> None:
        """Reduced pipeline for a single command MD (no prep, no JSON).

        Steps:
          1. Open MD file dialog.
          2. Extract cmd_target_slash from heading or frontmatter.
          3. Decide create vs update via os.path.exists.
          4. Expand sub-sequence inline into queue-command-list.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar MD do comando",
            str(Path.cwd()),
            "Markdown Files (*.md);;All Files (*)",
        )
        if not path:
            return

        md_path = Path(path)
        try:
            content = md_path.read_text(encoding="utf-8")
        except Exception as exc:
            signal_bus.toast_requested.emit(
                f"Erro ao ler {md_path.name}: {exc}", "error"
            )
            return

        # Step 3: extract cmd_target_slash
        cmd_target_slash = ""
        fm_match = re.search(r"^cmd_target:\s*([^\r\n]+)", content, re.MULTILINE)
        if fm_match:
            cmd_target_slash = fm_match.group(1).strip()
        if not cmd_target_slash:
            heading_match = re.search(r"^#\s+(/[^\s\n]+)", content, re.MULTILINE)
            if heading_match:
                cmd_target_slash = heading_match.group(1).strip()

        if not cmd_target_slash:
            signal_bus.toast_requested.emit(
                f"MD {md_path.name} nao tem heading canonico (# /grupo:nome) "
                "nem cmd_target no header. Abortando.",
                "error",
            )
            return

        # Step 4: decide action
        target_disk = cmd_target_slash.lstrip("/").replace(":", "/")
        cmd_file_path = Path.cwd() / ".claude" / "commands" / f"{target_disk}.md"
        cmd_action = "update" if cmd_file_path.exists() else "create"

        # Build sub-sequence
        md_path_str = str(md_path.resolve())
        commands = [
            "/clear",
            "/model opus",
            "/effort high",
            f"/cmd:{cmd_action} {md_path_str}",
            f"/cmd:review {cmd_target_slash} {md_path_str}",
        ]
        commands.extend([
            "/clear",
            f"/cmd:kimi-pair-analyse --approved {md_path_str}",
            f"/cmd:kimi-pair-execute --approved {md_path_str}",
            "/clear",
            "/cmd:readme-upd",
        ])

        specs: list[CommandSpec] = []
        for i, cmd in enumerate(commands, start=1):
            specs.append(
                CommandSpec(
                    name=cmd,
                    model=ModelName.OPUS,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=EffortLevel.HIGH,
                    position=i,
                )
            )

        self._template_label.setText(
            f"  \U0001f4cb  Cmd Single: {cmd_target_slash} ({cmd_action})"
        )
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"Cmd Single {cmd_target_slash}")
        signal_bus.pipeline_ready.emit(specs)

        hint = ""
        if cmd_action == "create":
            hint = (
                " Comando novo detectado. Rode "
                "python3 ai-forge/scripts/generate-workflow-index.py "
                "para registrar no indice."
            )
        signal_bus.toast_requested.emit(
            f"Fila renderizada: {len(specs)} comandos.{hint}", "success"
        )

    def _expand_loop_json_specs(
        self, raw: dict, config_path: str
    ) -> list[CommandSpec]:
        """Expand a *-loop.json into a list of CommandSpec based on mode."""
        mode = raw.get("mode", "task")

        if mode == "task":
            return self._expand_loop_task_specs(raw, config_path)
        if mode == "cmd":
            return self._expand_loop_cmd_specs(raw, config_path)
        if mode == "both":
            return self._expand_loop_both_specs(raw, config_path)

        raise ValueError(f"Modo de loop nao reconhecido: {mode}")

    def _expand_loop_task_specs(
        self, raw: dict, config_path: str
    ) -> list[CommandSpec]:
        """Expand a task-mode *-loop.json (pre/exec/post)."""
        iteration_template = raw.get("iteration_template", {})
        items = raw.get("items", [])
        finalization = raw.get("finalization", {})
        loop_name = str(raw.get("name", "")) or "loop"

        return self._do_expand_loop_specs(
            iteration_template, items, finalization, loop_name, config_path
        )

    def _expand_loop_cmd_specs(
        self, raw: dict, config_path: str
    ) -> list[CommandSpec]:
        """Expand a cmd-mode *-loop.json (pre/exec_create/exec_update/kimi_eligible_wrapper)."""
        iteration_template = raw.get("iteration_template", {})
        items = raw.get("items", [])
        finalization = raw.get("finalization", {})
        loop_name = str(raw.get("name", "")) or "loop"

        specs: list[CommandSpec] = []
        current_model = ModelName.SONNET
        current_effort = EffortLevel.STANDARD
        pos = 1

        def _add_command(cmd: str, testid: str = "", kimi_eligible: bool = False) -> None:
            nonlocal current_model, current_effort, pos
            stripped = cmd.strip()
            if stripped.startswith("/model "):
                model_str = stripped.split(None, 1)[1].lower()
                current_model = _MODEL_MAP.get(model_str, current_model)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                        testid=testid,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return
            if stripped.startswith("/effort "):
                effort_str = stripped.split(None, 1)[1].lower()
                current_effort = _EFFORT_MAP.get(effort_str, current_effort)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=current_effort,
                        position=pos,
                        testid=testid,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return
            if stripped == "/clear":
                specs.append(
                    CommandSpec(
                        name="/clear",
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                        testid=testid,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return

            specs.append(
                CommandSpec(
                    name=stripped,
                    model=current_model,
                    interaction_type=InteractionType.AUTO,
                    config_path=config_path,
                    effort=current_effort,
                    position=pos,
                    testid=testid,
                    kimi_eligible=kimi_eligible,
                )
            )
            pos += 1

        for item in items:
            task_path = (
                str(item.get("task_path", ""))
                if isinstance(item, dict)
                else ""
            )
            cmd_action = (
                str(item.get("cmd_action", ""))
                if isinstance(item, dict)
                else ""
            )
            cmd_target_slash = (
                str(item.get("cmd_target_slash", ""))
                if isinstance(item, dict)
                else ""
            )
            kimi_eligible = (
                bool(item.get("kimi_eligible", False))
                if isinstance(item, dict)
                else False
            )

            for cmd in iteration_template.get("pre", []):
                resolved = (
                    cmd.replace("{task_path}", task_path)
                    .replace("{name}", loop_name)
                )
                _add_command(resolved, kimi_eligible=kimi_eligible)

            exec_key = "exec_create" if cmd_action == "create" else "exec_update"
            for cmd in iteration_template.get(exec_key, []):
                resolved = (
                    cmd.replace("{task_path}", task_path)
                    .replace("{cmd_target_slash}", cmd_target_slash)
                    .replace("{name}", loop_name)
                )
                _add_command(resolved, kimi_eligible=kimi_eligible)

            if (
                kimi_eligible
                and "kimi_eligible_wrapper" in iteration_template
                and self._use_kimi_chk.isChecked()
            ):
                for cmd in iteration_template.get("kimi_eligible_wrapper", []):
                    resolved = (
                        cmd.replace("{task_path}", task_path)
                        .replace("{name}", loop_name)
                    )
                    _add_command(resolved, kimi_eligible=kimi_eligible)

        for cmd in finalization.get("commands", []):
            resolved = cmd.replace("{name}", loop_name)
            _add_command(resolved)

        return specs

    def _expand_loop_both_specs(
        self, raw: dict, config_path: str
    ) -> list[CommandSpec]:
        """Expand a both-mode *-loop.json (task + cmd interleaved)."""
        iteration_template = raw.get("iteration_template", {})
        items = raw.get("items", [])
        finalization = raw.get("finalization", {})
        loop_name = str(raw.get("name", "")) or "loop"

        specs: list[CommandSpec] = []
        current_model = ModelName.SONNET
        current_effort = EffortLevel.STANDARD
        pos = 1

        def _add_command(cmd: str, testid: str = "") -> None:
            nonlocal current_model, current_effort, pos
            stripped = cmd.strip()
            if stripped.startswith("/model "):
                model_str = stripped.split(None, 1)[1].lower()
                current_model = _MODEL_MAP.get(model_str, current_model)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                    )
                )
                pos += 1
                return
            if stripped.startswith("/effort "):
                effort_str = stripped.split(None, 1)[1].lower()
                current_effort = _EFFORT_MAP.get(effort_str, current_effort)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=current_effort,
                        position=pos,
                    )
                )
                pos += 1
                return
            if stripped == "/clear":
                specs.append(
                    CommandSpec(
                        name="/clear",
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                    )
                )
                pos += 1
                return

            specs.append(
                CommandSpec(
                    name=stripped,
                    model=current_model,
                    interaction_type=InteractionType.AUTO,
                    config_path=config_path,
                    effort=current_effort,
                    position=pos,
                    testid=testid,
                )
            )
            pos += 1

        for item in items:
            if not isinstance(item, dict):
                continue

            task_type = str(item.get("task_type", ""))
            item_id = str(item.get("id", ""))

            if task_type == "ambiguous":
                specs.append(
                    CommandSpec(
                        name=f"[BLOQUEADO] Item {item_id} - task_type ambiguo",
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=current_effort,
                        position=pos,
                        blocked_reason="task_type ambiguo - resolva em /loop:mark-type",
                    )
                )
                pos += 1
                continue

            task_path = str(item.get("task_path", ""))

            if task_type == "task":
                task_template = iteration_template.get("task", {})
                kimi_eligible = bool(item.get("kimi_eligible", False))

                phases = ["pre", "exec", "post"]
                if kimi_eligible and "kimi_eligible_wrapper" in task_template:
                    phases = ["pre", "kimi_eligible_wrapper", "post"]

                for phase in phases:
                    for cmd in task_template.get(phase, []):
                        resolved = (
                            cmd.replace("{task_path}", task_path)
                            .replace("{name}", loop_name)
                        )
                        _add_command(resolved)

            elif task_type == "cmd":
                cmd_template = iteration_template.get("cmd", {})
                cmd_complexity = str(item.get("cmd_complexity", ""))
                cmd_action = str(item.get("cmd_action", ""))
                cmd_target_slash = str(item.get("cmd_target_slash", ""))
                kimi_eligible = bool(item.get("kimi_eligible", False))

                if cmd_complexity == "single":
                    expanded_commands = item.get("expanded_commands", [])
                    for cmd in expanded_commands:
                        resolved = (
                            cmd.replace("{task_path}", task_path)
                            .replace("{name}", loop_name)
                        )
                        _add_command(resolved, testid="queue-item-cmd-single")
                else:
                    for cmd in cmd_template.get("pre", []):
                        resolved = (
                            cmd.replace("{task_path}", task_path)
                            .replace("{name}", loop_name)
                        )
                        _add_command(resolved)

                    exec_key = "exec_create" if cmd_action == "create" else "exec_update"
                    for cmd in cmd_template.get(exec_key, []):
                        resolved = (
                            cmd.replace("{task_path}", task_path)
                            .replace("{cmd_target_slash}", cmd_target_slash)
                            .replace("{name}", loop_name)
                        )
                        _add_command(resolved)

                    if kimi_eligible and "kimi_eligible_wrapper" in cmd_template:
                        for cmd in cmd_template.get("kimi_eligible_wrapper", []):
                            resolved = (
                                cmd.replace("{task_path}", task_path)
                                .replace("{name}", loop_name)
                            )
                            _add_command(resolved)

        for cmd in finalization.get("commands", []):
            resolved = cmd.replace("{name}", loop_name)
            _add_command(resolved)

        return specs

    def _do_expand_loop_specs(
        self,
        iteration_template: dict,
        items: list,
        finalization: dict,
        loop_name: str,
        config_path: str,
    ) -> list[CommandSpec]:
        """Shared expansion logic for task-mode iteration_template."""
        specs: list[CommandSpec] = []
        current_model = ModelName.SONNET
        current_effort = EffortLevel.STANDARD
        pos = 1

        def _add_command(cmd: str, kimi_eligible: bool = False) -> None:
            nonlocal current_model, current_effort, pos
            stripped = cmd.strip()
            if stripped.startswith("/model "):
                model_str = stripped.split(None, 1)[1].lower()
                current_model = _MODEL_MAP.get(model_str, current_model)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return
            if stripped.startswith("/effort "):
                effort_str = stripped.split(None, 1)[1].lower()
                current_effort = _EFFORT_MAP.get(effort_str, current_effort)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=current_effort,
                        position=pos,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return
            if stripped == "/clear":
                specs.append(
                    CommandSpec(
                        name="/clear",
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return

            specs.append(
                CommandSpec(
                    name=stripped,
                    model=current_model,
                    interaction_type=InteractionType.AUTO,
                    config_path=config_path,
                    effort=current_effort,
                    position=pos,
                    kimi_eligible=kimi_eligible,
                )
            )
            pos += 1

        for item in items:
            task_path = (
                str(item.get("task_path", ""))
                if isinstance(item, dict)
                else ""
            )
            kimi_eligible = (
                bool(item.get("kimi_eligible", False))
                if isinstance(item, dict)
                else False
            )

            phases = ["pre", "exec", "post"]
            if (
                kimi_eligible
                and "kimi_eligible_wrapper" in iteration_template
                and self._use_kimi_chk.isChecked()
            ):
                phases = ["pre", "kimi_eligible_wrapper", "post"]

            for phase in phases:
                commands = iteration_template.get(phase, [])
                for cmd in commands:
                    resolved = cmd.replace("{task_path}", task_path).replace(
                        "{name}", loop_name
                    )
                    _add_command(resolved, kimi_eligible=kimi_eligible)

        for cmd in finalization.get("commands", []):
            resolved = cmd.replace("{name}", loop_name)
            _add_command(resolved)

        return specs

    def _on_daily_loop_clicked(self) -> None:
        """Expand a daily-loop _LOOP-CONFIG.json + PROGRESS.md into the queue.

        Requires the metrics-project-pill to point at blacksmith/loop-archives/{slug}/_LOOP-CONFIG.json
        (generated by /daily-loop:enumerate). One queue entry per pending item,
        with /clear at position 0 and /model/X /effort/Y emitted only when
        the bucket changes between consecutive items.

        Failed items ([!]) are NOT re-queued — fix them manually in PROGRESS.md
        or re-run /daily-loop:enumerate.

        Pre-flight: if `{loop_root}/.review-blocked` is present (dropped by
        /daily-loop:review-created when its 3-round self-healing loop exhausts
        with blockers remaining), a confirmation modal is shown before
        expanding the queue. Defense-in-depth alongside the terminal-side gate.
        """
        from PySide6.QtWidgets import QMessageBox

        from workflow_app.config.app_state import app_state
        from workflow_app.daily_loop import (
            DailyLoopConfigError,
            build_daily_loop_specs,
            read_review_blocked_sentinel,
        )

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um _LOOP-CONFIG.json em metrics-project-pill antes de usar Daily loop.",
                "warning",
            )
            return

        config = app_state.config
        raw = config.raw if isinstance(config.raw, dict) else {}

        if raw.get("kind") != "daily-loop" or "daily_loop" not in raw:
            signal_bus.toast_requested.emit(
                "Projeto carregado nao e um _LOOP-CONFIG.json. "
                "Rode /daily-loop no terminal e carregue o JSON gerado.",
                "warning",
            )
            return

        loop_root = Path(config.config_path).parent

        sentinel = read_review_blocked_sentinel(loop_root)
        if sentinel is not None:
            slug_for_modal = str(raw.get("daily_loop", {}).get("slug", "")) or "daily-loop"
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Daily Loop — Review BLOQUEADO")
            box.setText(
                f"O preparo do loop \"{slug_for_modal}\" foi REPROVADO por "
                "/daily-loop:review-created."
            )
            blocker_line = (
                f"\n\nBlockers remanescentes: {sentinel.blocker_count}"
                if sentinel.blocker_count
                else ""
            )
            box.setInformativeText(
                "Sentinel `.review-blocked` encontrado em:\n"
                f"{sentinel.path}\n\n"
                "Recomendado: Cancelar, ler _LOOP-CREATED-AUDIT.md, corrigir "
                "blockers e re-rodar /daily-loop:review-created."
                f"{blocker_line}\n\n"
                "Executar mesmo assim?"
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            yes_btn = box.button(QMessageBox.StandardButton.Yes)
            yes_btn.setText("Executar mesmo assim")
            cancel_btn = box.button(QMessageBox.StandardButton.Cancel)
            cancel_btn.setText("Cancelar")
            choice = box.exec()
            if choice != QMessageBox.StandardButton.Yes:
                logger.info(
                    "[daily-loop] %s execution cancelled (.review-blocked override declined)",
                    slug_for_modal,
                )
                signal_bus.toast_requested.emit(
                    "Execucao cancelada — .review-blocked ativo.",
                    "info",
                )
                return
            logger.warning(
                "[daily-loop] %s executing despite .review-blocked sentinel "
                "(blockers=%d, user override)",
                slug_for_modal,
                sentinel.blocker_count,
            )

        try:
            specs = build_daily_loop_specs(raw, loop_root)
        except DailyLoopConfigError as exc:
            signal_bus.toast_requested.emit(f"Daily loop invalido: {exc}", "error")
            return
        except OSError as exc:
            signal_bus.toast_requested.emit(f"Erro ao ler PROGRESS.md: {exc}", "error")
            return

        if not specs:
            signal_bus.toast_requested.emit(
                "PROGRESS.md sem itens pendentes — loop concluido. "
                "Rode /daily-loop:review --slug X para o veredito final.",
                "info",
            )
            return

        slug = str(raw.get("daily_loop", {}).get("slug", "")) or "daily-loop"
        item_count = sum(1 for s in specs if s.name.startswith("/daily-loop:do "))
        logger.info("[daily-loop] loading %s (%d items, %d specs)", slug, item_count, len(specs))

        self._template_label.setText(f"  \U0001f4cb  Daily loop: {slug} ({item_count} itens)")
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"Daily loop {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_loop_clicked(self) -> None:
        """Expand a /loop pipeline _LOOP-CONFIG.json + PROGRESS.md into the queue.

        Clone of `_on_daily_loop_clicked` adapted for the new `/loop`
        family (`/loop --task|--cmd|--cmd-single|--both`, created 2026-05-12).
        The only behavioural difference is the PROGRESS.md parser:
        `build_loop_specs` uses `parse_progress_items_loop` which is
        backtick-aware and tolerates literal `|` characters inside
        backtick-wrapped inline code in the Target column (e.g. mode
        flag enumerations like `--simple|--deep|--heavy`). The legacy
        button (`queue-btn-daily-loop`) keeps the original
        non-backtick-aware parser for byte-for-byte backwards
        compatibility with old archives.

        Requires the metrics-project-pill to point at the
        `_LOOP-CONFIG.json` of a `/loop`-flavoured pipeline (same V3 +
        kind: daily-loop schema as the legacy daily-loop).
        """
        from PySide6.QtWidgets import QMessageBox

        from workflow_app.config.app_state import app_state
        from workflow_app.daily_loop import (
            DailyLoopConfigError,
            build_loop_specs,
            read_review_blocked_sentinel,
        )

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um _LOOP-CONFIG.json em metrics-project-pill antes de usar Loop.",
                "warning",
            )
            return

        config = app_state.config
        raw = config.raw if isinstance(config.raw, dict) else {}

        if raw.get("kind") != "daily-loop" or "daily_loop" not in raw:
            signal_bus.toast_requested.emit(
                "Projeto carregado nao e um _LOOP-CONFIG.json. "
                "Rode /loop no terminal e carregue o JSON gerado.",
                "warning",
            )
            return

        loop_root = Path(config.config_path).parent

        sentinel = read_review_blocked_sentinel(loop_root)
        if sentinel is not None:
            slug_for_modal = str(raw.get("daily_loop", {}).get("slug", "")) or "loop"
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Loop — Review BLOQUEADO")
            box.setText(
                f"O preparo do loop \"{slug_for_modal}\" foi REPROVADO por "
                "/daily-loop:review-created."
            )
            blocker_line = (
                f"\n\nBlockers remanescentes: {sentinel.blocker_count}"
                if sentinel.blocker_count
                else ""
            )
            box.setInformativeText(
                "Sentinel `.review-blocked` encontrado em:\n"
                f"{sentinel.path}\n\n"
                "Recomendado: Cancelar, ler _LOOP-CREATED-AUDIT.md, corrigir "
                "blockers e re-rodar /daily-loop:review-created."
                f"{blocker_line}\n\n"
                "Executar mesmo assim?"
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            yes_btn = box.button(QMessageBox.StandardButton.Yes)
            yes_btn.setText("Executar mesmo assim")
            cancel_btn = box.button(QMessageBox.StandardButton.Cancel)
            cancel_btn.setText("Cancelar")
            choice = box.exec()
            if choice != QMessageBox.StandardButton.Yes:
                logger.info(
                    "[loop] %s execution cancelled (.review-blocked override declined)",
                    slug_for_modal,
                )
                signal_bus.toast_requested.emit(
                    "Execucao cancelada — .review-blocked ativo.",
                    "info",
                )
                return
            logger.warning(
                "[loop] %s executing despite .review-blocked sentinel "
                "(blockers=%d, user override)",
                slug_for_modal,
                sentinel.blocker_count,
            )

        try:
            specs = build_loop_specs(raw, loop_root)
        except DailyLoopConfigError as exc:
            signal_bus.toast_requested.emit(f"Loop invalido: {exc}", "error")
            return
        except OSError as exc:
            signal_bus.toast_requested.emit(f"Erro ao ler PROGRESS.md: {exc}", "error")
            return

        if not specs:
            signal_bus.toast_requested.emit(
                "PROGRESS.md sem itens pendentes — loop concluido. "
                "Rode /daily-loop:review --slug X para o veredito final.",
                "info",
            )
            return

        slug = str(raw.get("daily_loop", {}).get("slug", "")) or "loop"
        item_count = sum(1 for s in specs if s.name.startswith("/daily-loop:do "))
        logger.info("[loop] loading %s (%d items, %d specs)", slug, item_count, len(specs))

        self._template_label.setText(f"  \U0001f4cb  Loop: {slug} ({item_count} itens)")
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"Loop {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_rocksmash_clicked(self) -> None:
        """Expand the active _LOOP-CONFIG.json into the /loop-rocksmash:* queue.

        Requires the metrics-project-pill to point at a daily-loop
        _LOOP-CONFIG.json. Emits:
            1x /loop-rocksmash:prepare
            N pares /loop-rocksmash:do + /loop-rocksmash:review-done
                (apenas items com kind=iteration; preparo/finalizacao
                sao ignorados)
            1x /loop-rocksmash:rename

        Directives /clear, /model, /effort sao auto-injetadas conforme
        bucket boundaries (espelha build_loop_specs).
        """
        from workflow_app.command_queue.loop_rocksmash_expander import (
            build_loop_rocksmash_specs,
        )
        from workflow_app.config.app_state import app_state
        from workflow_app.daily_loop import DailyLoopConfigError

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Selecione um _LOOP-CONFIG.json na metrics-project-pill "
                "antes de usar rocksmash.",
                "warning",
            )
            return

        config = app_state.config
        raw = config.raw if isinstance(config.raw, dict) else {}

        if raw.get("kind") != "daily-loop" or "daily_loop" not in raw:
            signal_bus.toast_requested.emit(
                "Este botao opera apenas sobre _LOOP-CONFIG.json "
                "(kind=daily-loop). Carregue um gerado por /loop ou "
                "/daily-loop:enumerate.",
                "warning",
            )
            return

        loop_root = Path(config.config_path).parent

        try:
            specs = build_loop_rocksmash_specs(raw, loop_root)
        except DailyLoopConfigError as exc:
            signal_bus.toast_requested.emit(
                f"rocksmash invalido: {exc}", "error"
            )
            return

        slug = str(raw.get("daily_loop", {}).get("slug", "")) or "rocksmash"
        pair_count = sum(
            1 for s in specs if s.name.startswith("/loop-rocksmash:do ")
        )
        bucket_ids = sorted(
            {
                str(it.get("bucket", ""))
                for it in (raw.get("daily_loop", {}).get("items_index") or {}).values()
                if isinstance(it, dict) and str(it.get("kind", "iteration")) == "iteration"
            }
        )
        logger.info(
            "[rocksmash] loading %s (%d pares, %d specs, buckets=%s)",
            slug,
            pair_count,
            len(specs),
            ",".join(bucket_ids) or "-",
        )

        self._template_label.setText(
            f"  \U0001f4cb  rocksmash: {slug} ({pair_count} pares)"
        )
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"rocksmash {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_boilerplate_clicked(self) -> None:
        """Carrega o pipeline boilerplate (9 passos).

        Comportamento especial: NAO le metrics-project-pill (project.json).
        Abre BoilerplatePathDialog para o usuario colar o path do repo legado.
        Em seguida injeta config_path por-spec:
          - /boilerplate:scan → repo_path (caminho fornecido)
          - demais /boilerplate:* → staging_path = output/workspace/boilerplates/_staging/{basename(repo_path)}
          - /clear, /model X, /effort Y → "" (sem arg)

        O patch em main_window._on_pipeline_ready preserva esses config_path
        pre-setados (so escreve quando spec.config_path esta vazio).
        """
        from pathlib import Path

        from workflow_app.dialogs.boilerplate_path_dialog import BoilerplatePathDialog

        dlg = BoilerplatePathDialog(parent=self)
        if dlg.exec() != BoilerplatePathDialog.Accepted:
            return

        repo_path = dlg.repo_path
        if not repo_path:
            signal_bus.toast_requested.emit("Path vazio — boilerplate cancelado.", "warning")
            return

        # Basename normalizado: tira trailing slash e usa o ultimo segmento.
        # Bloqueia "." e ".." para preservar o isolamento do staging.
        basename = Path(repo_path).name
        if not basename or basename in {".", ".."}:
            signal_bus.toast_requested.emit(
                f"Basename invalido derivado de '{repo_path}'.", "error"
            )
            return

        staging_path = f"output/workspace/boilerplates/_staging/{basename}"

        raw = copy.deepcopy(TEMPLATE_BOILERPLATE)
        # Injeta config_path por spec. Headers (/clear, /model, /effort) ficam vazios.
        for spec in raw:
            if spec.name == "/clear" or spec.name.startswith("/model ") or spec.name.startswith("/effort "):
                spec.config_path = ""
                continue
            if spec.name == "/boilerplate:scan":
                spec.config_path = repo_path
            elif spec.name.startswith("/boilerplate:"):
                spec.config_path = staging_path
            else:
                spec.config_path = ""

        self._template_label.setText("  \U0001f4cb  Boilerplate")
        self._template_label.setVisible(True)
        # NOTA: pulamos _maybe_auto_save porque este fluxo nao depende de projeto carregado.

        # Reusa logica de _load_quick_template (injecao de /model rows e renumeracao).
        expanded: list[CommandSpec] = []
        current_model = None
        for spec in raw:
            if spec.name == "/clear":
                expanded.append(spec)
                continue
            if spec.name.startswith("/model "):
                current_model = spec.model
                expanded.append(spec)
                continue
            if spec.model != current_model:
                model_spec = CommandSpec(
                    name=f"/model {spec.model.value.lower()}",
                    model=spec.model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=0,
                )
                expanded.append(model_spec)
                current_model = spec.model
            expanded.append(spec)

        for i, spec in enumerate(expanded, start=1):
            spec.position = i

        signal_bus.pipeline_ready.emit(expanded)
        signal_bus.toast_requested.emit(
            f"Boilerplate carregado: 9 passos sobre {basename}", "success"
        )

    def _on_run_command(self, cmd_text: str) -> None:
        """Update last-command label and highlight the matching queue row."""
        parts = cmd_text.strip().split()
        self._last_cmd_label.setText("\n".join(parts))
        self._last_cmd_label.setVisible(True)
        self._highlight_current_command(cmd_text.strip())
        self._maybe_auto_save(cmd_text)

    def _highlight_current_command(self, cmd_text: str) -> None:
        """Highlight the queue row whose command matches cmd_text."""
        for item in self._items:
            item.set_highlighted(item.command_text() == cmd_text)

    def load_pipeline(self, specs: list[CommandSpec]) -> None:
        """Populate the queue with CommandSpec objects."""
        # Onda 4: clear DCP context — the new pipeline isn't (yet) backed by
        # a SPECIFIC-FLOW.json. The DCP handler will re-arm
        # _current_dcp_flow_path AFTER this signal returns, so DCP-sourced
        # loads end up with the path correctly set. Non-DCP sources stay None.
        self._current_dcp_flow_path = None

        # Clear existing
        for item in self._items:
            item.deleteLater()
        self._items.clear()

        # Remove stretch before inserting
        self._items_layout.takeAt(self._items_layout.count() - 1)

        for spec in specs:
            item = self._make_item(spec)
            self._items_layout.addWidget(item)
            self._items.append(item)

        # Re-add stretch at end
        self._items_layout.addStretch()

        self._empty_widget.setVisible(False)
        self._list_widget.setVisible(True)
        self._emit_progress_metrics()
        self._update_save_btn_state()

    def load_commands(self, commands: list[CommandSpec]) -> None:
        """Alias for load_pipeline() — called via signal pipeline_created."""
        self.load_pipeline(commands)

    def add_command(self, spec: CommandSpec) -> None:
        """Append a single CommandSpec to the existing queue.  # RESOLVED: G001"""
        # Remove stretch before inserting
        stretch_item = self._items_layout.takeAt(self._items_layout.count() - 1)

        item = self._make_item(spec)
        self._items_layout.addWidget(item)
        self._items.append(item)

        # Re-add stretch at end
        if stretch_item:
            self._items_layout.addStretch()

        self._empty_widget.setVisible(False)
        self._list_widget.setVisible(True)
        self._emit_progress_metrics()

    def _on_inline_add_clicked(self) -> None:
        """[+] Adicionar Comando — abre dialog com 3 inputs (1 obrigatorio +
        2 opcionais) + checkbox JSON por linha + radio de posicao (next/last)
        e injeta cada texto preenchido como item transiente, na ordem dos campos.

        Posicao next (default): o primeiro item entra entre a ultima linha
        "sent" e a primeira linha "pending"; os subsequentes empilham apos
        o ultimo injetado (preserva a ordem dos inputs).
        Posicao last: cada item entra no final da fila, na ordem dos inputs.
        Itens sao transientes — nao persistem em template/JSON/memoria;
        load_pipeline() / clear() os apagam.
        """
        from PySide6.QtWidgets import (
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QRadioButton,
            QVBoxLayout,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Adicionar Comando")
        dialog.setMinimumWidth(520)
        dialog.setMinimumHeight(360)
        dialog.setProperty("testid", "dialog-add-command")

        layout = QVBoxLayout(dialog)

        header_row = QHBoxLayout()
        lbl_cmd = QLabel("Comando")
        lbl_cmd.setStyleSheet("color: #A1A1AA; font-size: 11px; font-weight: 600;")
        lbl_json = QLabel("JSON")
        lbl_json.setStyleSheet("color: #FBBF24; font-size: 11px; font-weight: 600; padding-left: 4px;")
        lbl_json.setFixedWidth(40)
        header_row.addWidget(lbl_cmd)
        header_row.addWidget(lbl_json)
        layout.addLayout(header_row)

        inputs_and_checks = []
        for i, label_text in enumerate([
            "Comando a executar:",
            "Comando adicional (opcional):",
            "Comando adicional (opcional):",
        ]):
            layout.addWidget(QLabel(label_text))
            row = QHBoxLayout()
            inp = QLineEdit(dialog)
            inp.setProperty("testid", f"queue-add-input-{i + 1}")
            chk = QCheckBox(dialog)
            chk.setProperty("testid", f"queue-add-json-{i + 1}")
            chk.setToolTip("Anexar caminho do project.json ao comando")
            chk.setFixedWidth(40)
            chk.setStyleSheet("QCheckBox { color: #FBBF24; }")
            row.addWidget(inp)
            row.addWidget(chk)
            layout.addLayout(row)
            layout.addSpacing(4)
            inputs_and_checks.append((inp, chk))

        line_edit_1, chk_1 = inputs_and_checks[0]
        line_edit_2, chk_2 = inputs_and_checks[1]
        line_edit_3, chk_3 = inputs_and_checks[2]

        layout.addSpacing(8)
        layout.addWidget(QLabel("Posicao de insercao:"))
        radio_next = QRadioButton(
            "next — proximo (entre o ultimo enviado e o proximo pendente)",
            dialog,
        )
        radio_last = QRadioButton(
            "last — ultimo (apos todos os items da fila)",
            dialog,
        )
        radio_next.setChecked(True)
        layout.addWidget(radio_next)
        layout.addWidget(radio_last)

        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        line_edit_1.setFocus()

        if dialog.exec() != QDialog.Accepted:
            return

        from workflow_app.config.app_state import app_state as _app_state
        import os as _os
        json_path = ""
        if _app_state.has_config and _app_state.config:
            try:
                json_path = _os.path.relpath(
                    _app_state.config.config_path,
                    str(_app_state.config.project_dir),
                )
            except ValueError:
                json_path = str(_app_state.config.config_path)

        filled = []
        for line_edit, chk in [(line_edit_1, chk_1), (line_edit_2, chk_2), (line_edit_3, chk_3)]:
            text = line_edit.text().strip()
            if not text:
                continue
            if chk.isChecked() and json_path:
                text = f"{text} {json_path}"
            filled.append(text)

        if not filled:
            return
        position = "last" if radio_last.isChecked() else "next"
        for text in filled:
            self._inject_next_command(text, position=position)

    def _inject_next_command(self, text: str, position: str = "next") -> None:
        """Cria CommandSpec transiente e insere conforme a posicao.

        position="next" (default): apos sent/injected items (proximo a rodar).
        position="last": no final da fila (apos todos os items existentes).
        kimi_eligible=True forca a seta azul visivel independente do
        whitelist (ver CommandItemWidget._setup_ui).
        """
        spec = CommandSpec(
            name=text,
            model=ModelName.SONNET,
            interaction_type=InteractionType.AUTO,
            kimi_eligible=True,
        )
        item = self._make_item(spec)
        item._is_injected = True

        if position == "last":
            insert_idx = len(self._items)
        else:
            # Insertion index: depois do ultimo item sent OU injected.
            insert_idx = 0
            for i, existing in enumerate(self._items):
                if existing._is_sent or getattr(existing, "_is_injected", False):
                    insert_idx = i + 1

        # _items_layout = [items..., stretch]. insertWidget(K, w) coloca
        # w antes do K-esimo filho, entao insert_idx == len(self._items)
        # coloca w entre o ultimo item e o stretch.
        self._items_layout.insertWidget(insert_idx, item)
        self._items.insert(insert_idx, item)

        # Renumerar position 1-based para manter _item_at() coerente.
        for i, it in enumerate(self._items, start=1):
            it.get_spec().position = i

        self._empty_widget.setVisible(False)
        self._list_widget.setVisible(True)
        self._emit_progress_metrics()
        self._update_save_btn_state()

    def _update_save_btn_state(self) -> None:
        if hasattr(self, '_save_btn'):
            self._save_btn.setEnabled(len(self._items) > 0)

    def clear_queue(self) -> None:
        for item in self._items:
            item.deleteLater()
        self._items.clear()
        self._template_label.setVisible(False)
        self._last_cmd_label.setVisible(False)
        self._empty_widget.setVisible(True)
        self._list_widget.setVisible(False)
        self._emit_progress_metrics()
        self._update_save_btn_state()

    def _item_at(self, position: int) -> CommandItemWidget | None:
        for item in self._items:
            if item.get_spec().position == position:
                return item
        return None

    _DONE_STATUSES = (
        CommandStatus.CONCLUIDO,
        CommandStatus.ERRO,
        CommandStatus.PULADO,
    )

    def _emit_progress_metrics(self) -> None:
        """Emit metrics_updated(done, total) so queue-progress-ring reflects the queue.

        done = items that left the pending state by either:
          - being dispatched to a terminal (_is_sent True — the amber-dot UX,
            which is how live runs mark progress); or
          - reaching a terminal CommandStatus (CONCLUIDO/ERRO/PULADO — used by
            the resume path that hydrates state from DB).
        total = len(self._items). Failed/skipped count as done because they
        are no longer pending — the ring represents finished/total, not
        success/total.
        """
        total = len(self._items)
        done = sum(
            1
            for i in self._items
            if i._is_sent or i._status in self._DONE_STATUSES
        )
        signal_bus.metrics_updated.emit(done, total)

    def _make_item(self, spec: CommandSpec) -> CommandItemWidget:
        """Create a CommandItemWidget with can_reorder_fn injected."""
        item = CommandItemWidget(spec, can_reorder_fn=self._can_reorder, parent=self._items_container)
        item.remove_requested.connect(self._on_remove_requested)
        item.skip_requested.connect(self._on_skip_requested)
        item.retry_requested.connect(self._on_retry_requested)
        item.cancel_requested.connect(self._on_cancel_requested)
        # Per-item green arrow passa por _dispatch_green_arrow — handler
        # unico responsavel por (a) decidir o terminal de destino conforme
        # estado de --force Kimi, (b) chamar _on_run_command quando o
        # comando foi efetivamente despachado (label + highlight usam
        # SEMPRE a string original do item, nunca a transformada), e (c)
        # mirror de /clear para o workspace no fluxo Use Kimi legado.
        # Centralizar a logica num unico slot elimina inconsistencia entre
        # caminhos paralelos (issue HIGH 3 do review adversarial).
        item.run_in_terminal_requested.connect(self._dispatch_green_arrow)
        item.run_in_kimi_terminal_requested.connect(self._dispatch_blue_arrow)
        item.run_in_kimi_terminal_requested.connect(self._on_run_command)
        item.sent_state_changed.connect(self._on_item_sent_state_changed)
        # --force Kimi pode estar ativo no momento da criacao do item: aplica
        # imediatamente a regra de visibilidade da seta azul para o item novo.
        if getattr(self, "_force_kimi_chk", None) and self._force_kimi_chk.isChecked():
            btn = getattr(item, "_kimi_btn", None)
            if btn is not None:
                btn.setVisible(False)
        return item

    def _on_item_sent_state_changed(self, _is_sent: bool) -> None:
        """Item toggled the amber-dot (sent) state — refresh queue-progress-ring."""
        self._emit_progress_metrics()

    # Default delay between paste and Enter for the blue-arrow Kimi path.
    _KIMI_BLUE_ARROW_DEFAULT_DELAY_MS: int = 1_000
    # Extra delay added when the previous workspace dispatch was /clear:
    # Kimi takes longer to repaint the prompt after a full TUI clear.
    _KIMI_AFTER_CLEAR_EXTRA_DELAY_MS: int = 2_000

    def _dispatch_blue_arrow(self, kimi_prompt: str) -> None:
        """Forward a blue-arrow click to `kimi_blue_arrow_dispatched` with
        the right delay. If the previous workspace dispatch was /clear, add
        2s extra because Kimi's TUI repaint after a clear is slower than
        normal — without the extra delay, Enter lands before /skill: is
        composed and the command is silently dropped.
        """
        if self._last_workspace_dispatch_was_clear:
            delay = (
                self._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
                + self._KIMI_AFTER_CLEAR_EXTRA_DELAY_MS
            )
            self._last_workspace_dispatch_was_clear = False  # consumed
        else:
            delay = self._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
        signal_bus.kimi_blue_arrow_dispatched.emit(kimi_prompt, delay)

    def _on_force_kimi_toggled(self, checked: bool) -> None:
        """Quando --force Kimi liga: desliga Use Kimi e esconde a seta azul
        em todos os items. Quando desliga: re-habilita seta azul respeitando
        a regra original de visibilidade (whitelist OU spec.kimi_eligible)."""
        if checked and self._use_kimi_chk.isChecked():
            # Bloqueia o handler reverso temporariamente para evitar re-entrancy.
            self._use_kimi_chk.blockSignals(True)
            self._use_kimi_chk.setChecked(False)
            self._use_kimi_chk.blockSignals(False)
        self._use_kimi_chk.setEnabled(not checked)
        self._refresh_kimi_btn_visibility()

    def _on_use_kimi_toggled(self, checked: bool) -> None:
        """Quando Use Kimi liga e --force Kimi tambem esta marcado, desmarca
        este (modos mutuamente exclusivos). Sem efeito caso contrario."""
        if checked and self._force_kimi_chk.isChecked():
            self._force_kimi_chk.blockSignals(True)
            self._force_kimi_chk.setChecked(False)
            self._force_kimi_chk.blockSignals(False)
            self._use_kimi_chk.setEnabled(True)
            self._refresh_kimi_btn_visibility()

    def _refresh_kimi_btn_visibility(self) -> None:
        """Aplica regra de visibilidade das setas azuis per-item.

        Com --force Kimi marcado, esconde TODAS as setas azuis. Sem o force,
        repete a regra original aplicada em CommandItemWidget._setup_ui:
        visivel quando whitelist OR spec.kimi_eligible."""
        force_on = self._force_kimi_chk.isChecked()
        for item in self._items:
            btn = getattr(item, "_kimi_btn", None)
            if btn is None:
                continue
            if force_on:
                btn.setVisible(False)
                continue
            spec = item.get_spec()
            visible = is_kimi_compatible(spec.name) or spec.kimi_eligible
            btn.setVisible(visible)

    # Diretorios pesquisados para resolver existencia de uma skill quando
    # --force Kimi reescreve `/cmd` como `/skill:cmd`. Caches resolvidos uma
    # unica vez por instancia para evitar IO repetido no hot path.
    _SKILL_SEARCH_DIRS = (".claude/commands/skill", ".agents/skills")

    @classmethod
    def _resolve_skill_target(cls, slug: str) -> bool:
        """True quando existe arquivo `{slug}.md` em qualquer skill dir.

        slug = parte apos `/skill:` e antes do primeiro espaco/argumento.
        Idempotente para chamadas repetidas (filesystem check is cheap and
        already cached pelo SO; nao introduzimos cache em memoria para
        manter o sinal sempre fresco apos `git pull` durante a sessao)."""
        import os
        if not slug:
            return False
        # `slug` pode conter ":" para namespacing (ex: qa:trace) — quando
        # presente, o arquivo em disco vive em sub-diretorio: qa/trace.md.
        rel_path = slug.replace(":", "/") + ".md"
        for base in cls._SKILL_SEARCH_DIRS:
            if os.path.exists(os.path.join(base, rel_path)):
                return True
        return False

    @staticmethod
    def _inject_skill_prefix(cmd_text: str) -> str:
        """Insere 'skill:' apos a barra inicial do comando.

        /create-task -> /skill:create-task. Idempotente (`/skill:foo` permanece
        intacto) e preserva whitespace lider. Comandos sem `/` retornam
        inalterados — _dispatch_green_arrow os trata como prompt livre."""
        if not cmd_text:
            return cmd_text
        stripped = cmd_text.lstrip()
        if not stripped.startswith("/") or stripped.startswith("/skill:"):
            return cmd_text
        leading = cmd_text[: len(cmd_text) - len(stripped)]
        return f"{leading}/skill:{stripped[1:]}"

    def _dispatch_green_arrow(self, cmd_text: str) -> None:
        """Handler unico para `item.run_in_terminal_requested` (seta verde).

        Default path (force-kimi off): emite para terminal interactive e
        atualiza label/highlight com o cmd_text original. Mirror legado de
        `/clear`+Use Kimi tambem roda aqui (substitui o slot separado que
        existia antes do refactor).

        --force Kimi path: roteia para terminal workspace com prefixo /skill:;
        `/model` e `/effort` viram bolinha amarela SEM dispatch nem update de
        label/highlight (suprimidos pelo modo); `/clear` vai SO para workspace.
        Comandos sem skill wrapper existente disparam toast e abortam o
        dispatch (issue HIGH 2 do review adversarial)."""
        if not getattr(self, "_force_kimi_chk", None) or not self._force_kimi_chk.isChecked():
            # Legacy: dispatch + bookkeeping + mirror /clear quando Use Kimi.
            signal_bus.run_command_in_terminal.emit(cmd_text)
            self._on_run_command(cmd_text)
            self._mirror_clear_to_workspace_if_kimi_checked(cmd_text)
            return
        head = cmd_text.strip().split(None, 1)[0].lower() if cmd_text.strip() else ""
        if head.startswith("/model") or head.startswith("/effort"):
            # Bolinha amarela so — _on_run_clicked do item ja chama _mark_as_sent.
            # NAO atualizamos label/highlight pois o comando nao foi enviado.
            return
        if head == "/clear":
            signal_bus.run_command_in_workspace_terminal.emit(cmd_text)
            self._on_run_command(cmd_text)
            self._last_workspace_dispatch_was_clear = True
            return
        # Demais slash commands: injetar /skill: apos validar wrapper.
        if head.startswith("/"):
            slug = head[1:].split()[0] if head else ""
            if slug and not self._resolve_skill_target(slug):
                signal_bus.toast_requested.emit(
                    f"--force Kimi: skill '{slug}' nao encontrada em "
                    ".claude/commands/skill/ nem .agents/skills/ — dispatch abortado.",
                    "warn",
                )
                return
        transformed = self._inject_skill_prefix(cmd_text)
        signal_bus.run_command_in_workspace_terminal.emit(transformed)
        # IMPORTANTE: label/highlight usam SEMPRE a string ORIGINAL para que
        # _highlight_current_command consiga bater contra item.command_text().
        # Issue HIGH 3 do review adversarial (highlight quebrado no play-next).
        self._on_run_command(cmd_text)

    def _mirror_clear_to_workspace_if_kimi_checked(self, cmd_text: str) -> None:
        """When /clear is dispatched to interactive AND Use Kimi is checked,
        also emit it to the workspace terminal so both CLI sessions clear
        their context simultaneously, AND set the after-clear flag so the
        next blue-arrow Kimi dispatch uses the extended 3s delay (Kimi's
        TUI repaint after a clear is slower than normal).

        Connected to `item.run_in_terminal_requested` so it runs for every
        per-item green-button dispatch (the entry point most users actually
        click). The "Rodar próximo" path bypasses item signals and emits
        directly to the bus, so it has its own clear-both branch (which
        also sets the flag).
        """
        if not cmd_text or not cmd_text.strip():
            return
        # --force Kimi ja roteou /clear para o workspace via _dispatch_green_arrow.
        # Sem esta guarda haveria emissao dupla para o workspace terminal.
        if getattr(self, "_force_kimi_chk", None) and self._force_kimi_chk.isChecked():
            return
        head = cmd_text.strip().split(None, 1)[0].lower()
        if head == "/clear" and self._use_kimi_chk.isChecked():
            signal_bus.run_command_in_workspace_terminal.emit(cmd_text)
            self._last_workspace_dispatch_was_clear = True

    # ──────────────────────────────────────── Quick-save helpers ─────── #

    def _maybe_auto_save(self, changed_text: str) -> None:
        """Auto-trigger save_requested when label content changes,
        unless the content is /model or /clear."""
        if not changed_text:
            return
        first_line = changed_text.strip().split("\n")[0].strip().lower()
        _skip = ("/model", "/clear")
        if any(first_line.startswith(s) for s in _skip) or first_line == "/clear":
            return
        self.save_requested.emit()

    def get_template_label_text(self) -> str:
        """Return the current template label text (strip leading icon/space)."""
        text = self._template_label.text().strip()
        # Remove leading emoji + space (e.g. "  📋  Brief — Novo Projeto")
        for prefix in ("📋", "🔎"):
            if prefix in text:
                text = text.split(prefix, 1)[-1].strip()
        return text

    def get_last_command_text(self) -> str:
        """Return the current last-command label text."""
        return self._last_cmd_label.text().strip()

    def find_last_valid_command(self) -> str:
        """Walk the queue backwards from the last executed item to find
        a command that is not /model or /clear."""
        _skip = ("/model", "/clear")
        for item in reversed(self._items):
            if not item.is_pending_run():
                name = item.get_spec().name.strip()
                name_lower = name.lower()
                if not any(name_lower.startswith(s) for s in _skip):
                    return name
        return ""

    # ──────────────────────────────────────── Queue state persistence ─ #

    def get_queue_snapshot(self) -> list[dict]:
        """Return serializable snapshot of the current queue (commands + statuses)."""
        result = []
        for item in self._items:
            spec = item.get_spec()
            result.append({
                "name": spec.name,
                "model": spec.model.value,
                "interaction_type": spec.interaction_type.value,
                "position": spec.position,
                "is_optional": spec.is_optional,
                "config_path": spec.config_path,
                "phase": spec.phase,
                "status": item._status.value,
                "sent": not item.is_pending_run(),
            })
        return result

    def restore_queue_snapshot(self, state: list[dict]) -> None:
        """Restore queue from a saved state list, preserving statuses and sent flags."""
        from workflow_app.domain import CommandStatus, InteractionType, ModelName

        specs = []
        statuses: list[CommandStatus] = []
        sent_flags: list[bool] = []

        for entry in state:
            try:
                model = ModelName(entry.get("model", "Sonnet"))
            except ValueError:
                model = ModelName.SONNET
            try:
                interaction = InteractionType(entry.get("interaction_type", "auto"))
            except ValueError:
                interaction = InteractionType.AUTO

            spec = CommandSpec(
                name=entry["name"],
                model=model,
                interaction_type=interaction,
                position=entry.get("position", 0),
                is_optional=entry.get("is_optional", False),
                config_path=entry.get("config_path", ""),
                phase=entry.get("phase", "F?"),
            )
            specs.append(spec)

            try:
                status = CommandStatus(entry.get("status", "pendente"))
            except ValueError:
                status = CommandStatus.PENDENTE
            statuses.append(status)
            sent_flags.append(entry.get("sent", False))

        self.load_pipeline(specs)

        for item, status, sent in zip(self._items, statuses, sent_flags):
            if status != CommandStatus.PENDENTE:
                item.set_status(status)
            if sent:
                item._mark_as_sent()

    # ─────────────────────────────────────── Drag-and-drop: drop target ─ #

    def _can_reorder(self, position: int) -> bool:
        """Delegate to PipelineManager.can_reorder (converts 1-based → 0-based)."""
        if self._pipeline_manager is not None:
            return self._pipeline_manager.can_reorder(position - 1)
        return True

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._items_container:
            if event.type() == QEvent.Type.DragEnter:
                if event.mimeData().hasText():
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.DragMove:
                if event.mimeData().hasText():
                    self._update_drop_indicator(event.position().toPoint())
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.DragLeave:
                self._items_container.set_drop_indicator(None)
                return True
            elif event.type() == QEvent.Type.Drop:
                self._on_drop(event)
                return True
        return super().eventFilter(obj, event)

    def _update_drop_indicator(self, pos: QPoint) -> None:
        """Calculate drop index based on Y cursor position and update the visual indicator."""
        layout = self._items_layout
        count = layout.count()
        for i in range(count):
            layout_item = layout.itemAt(i)
            if layout_item and layout_item.widget():
                widget_rect = layout_item.widget().geometry()
                if pos.y() < widget_rect.center().y():
                    self._items_container.set_drop_indicator(i)
                    return
        self._items_container.set_drop_indicator(count)

    def _on_drop(self, event) -> None:
        """Process drop: emit reorder_requested if positions differ."""
        try:
            from_pos = int(event.mimeData().text())
        except (ValueError, AttributeError):
            return
        to_pos = self._items_container._drop_indicator_pos
        self._items_container.set_drop_indicator(None)
        if to_pos is None or from_pos == to_pos:
            event.ignore()
            return
        event.acceptProposedAction()
        self.reorder_requested.emit(from_pos, to_pos)

    # ─────────────────────────────────────────────────────── Slots ───── #

    def _on_command_started(self, index: int) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.EXECUTANDO)

    def _on_command_completed(self, index: int, success: bool = True) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.CONCLUIDO)
            self._emit_progress_metrics()

    def _on_command_failed(self, index: int, _msg: str) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.ERRO)
            self._emit_progress_metrics()

    def _on_command_skipped(self, index: int) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.PULADO)
            self._emit_progress_metrics()

    def _on_remove_requested(self, position: int) -> None:
        item = self._item_at(position)
        if item:
            removed_name = item.get_spec().name
            self._items_layout.removeWidget(item)
            item.deleteLater()
            self._items = [i for i in self._items if i.get_spec().position != position]
            if not self._items:
                self._empty_widget.setVisible(True)
                self._list_widget.setVisible(False)
            self._emit_progress_metrics()
            # Onda 4: when the queue is backed by a SPECIFIC-FLOW.json (DCP
            # context, set by _on_dcp_specific_flow_clicked), persist the
            # deletion to overrides.skipped[] so the next reload (or regen
            # without --reset-overrides) honors it. Without this, the user
            # has to re-delete the same broken commands every time they
            # click [DCP: Specific-Flow].
            self._persist_dcp_skip(removed_name)

    def _persist_dcp_skip(self, command_name: str) -> None:
        """Append `command_name` to overrides.skipped[] of the current DCP flow.

        No-op when the queue isn't sourced from a SPECIFIC-FLOW.json (legacy
        templates, ad-hoc pipelines). Failure to persist is surfaced as a
        warning toast but does NOT undo the in-memory deletion — the user
        already saw the item disappear from the queue, restoring it would
        be more confusing than a non-fatal warning.
        """
        flow_path = self._current_dcp_flow_path
        if flow_path is None or not command_name:
            return
        if not flow_path.exists():
            logger.warning(
                "[DCP] persist skip: flow path %s nao existe; override descartado",
                flow_path,
            )
            return
        try:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            signal_bus.toast_requested.emit(
                f"DCP: falha ao ler SPECIFIC-FLOW.json para persistir override: {exc}",
                "warning",
            )
            return
        if not isinstance(data, dict):
            return
        overrides = data.get("overrides")
        if not isinstance(overrides, dict):
            overrides = {}
            data["overrides"] = overrides
        skipped = overrides.get("skipped")
        if not isinstance(skipped, list):
            skipped = []
            overrides["skipped"] = skipped
        if command_name in skipped:
            return
        skipped.append(command_name)
        try:
            flow_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            logger.info(
                "[DCP] persisted skip %r in %s (total skipped=%d)",
                command_name, flow_path.name, len(skipped),
            )
        except OSError as exc:
            signal_bus.toast_requested.emit(
                f"DCP: falha ao gravar override em {flow_path.name}: {exc}",
                "warning",
            )

    def _on_skip_requested(self, position: int) -> None:
        item = self._item_at(position)
        if item:
            item.set_status(CommandStatus.PULADO)
            signal_bus.command_skipped.emit(position - 1)

    def _on_retry_requested(self, position: int) -> None:
        """Reset the failed item to PENDENTE and request pipeline retry."""
        item = self._item_at(position)
        if item:
            item.set_status(CommandStatus.PENDENTE)
        signal_bus.pipeline_retry_requested.emit(position - 1)

    def _on_cancel_requested(self) -> None:
        """Show confirmation dialog before cancelling the pipeline."""
        modal = ConfirmCancelModal(parent=self)
        if modal.exec() == ConfirmCancelModal.Accepted:
            signal_bus.pipeline_cancelled.emit()

    def _on_pipeline_error_with_message(self, _pipeline_id: int, message: str) -> None:
        """Mark the currently-executing item as failed with the error message."""
        for item in self._items:
            if item._status == CommandStatus.EXECUTANDO:
                item.set_status(CommandStatus.ERRO, error_message=message)
                break

    def _on_interactive_advance_ready(self, _command_exec_id: int) -> None:
        """Show and enable the 'Próximo' button when an interactive command awaits."""
        command_name = "Próximo"
        for item in self._items:
            if item._status == CommandStatus.EXECUTANDO:
                command_name = item.get_spec().name
                break
        self._next_bar.setVisible(True)
        self._btn_next.setVisible(True)
        self._btn_next.setEnabled(True)
        self._btn_next.setText(f"Continuar: {command_name}")

    def _on_btn_next_clicked(self) -> None:
        """Disable the button and ask PipelineManager to advance."""
        self._btn_next.setEnabled(False)
        self._next_bar.setVisible(False)
        self._btn_next.setVisible(False)
        self._btn_next.setText("Próximo →")
        signal_bus.interactive_advance_triggered.emit()

    # ───────────────────────────────────── Queue dispatch ──────────── #

    def _on_instance_selected(self, name: str) -> None:
        """Track the active CLI binary for downstream routing."""
        self._cli_binary = name

    def _find_next_pending(self) -> CommandItemWidget | None:
        """Find the first item not yet sent to terminal."""
        for item in self._items:
            if item.is_pending_run():
                return item
        return None

    def _on_step_btn_clicked(self) -> None:
        """Run the next pending item once and stop. Manual step-by-step.

        Dispatches EVERY pending item to the terminal — including queue
        helpers (/clear, /model X, /effort Y). The dispatcher uses
        run_command_in_terminal (Claude) or run_command_in_workspace_terminal
        (Kimi), pasting into the already-open CLI session. So /clear actually
        clears context and /model/effort actually switch the session's
        model/effort. Skipping helpers here would silently break model/effort
        transitions.
        """
        next_item = self._find_next_pending()
        if next_item is None:
            signal_bus.toast_requested.emit(
                "Fila vazia — nenhum item pendente para executar.",
                "info",
            )
            return

        spec = next_item.get_spec()

        # Dispatch via Kimi (blue arrow) or Claude (green arrow).
        # Routing rule:
        #   - checkbox checked AND command in kimi whitelist
        #     AND item's _kimi_btn is actually visible -> kimi click
        #   - otherwise -> claude (green) click
        # The triple condition guards against whitelist/visibility divergence
        # (real risk flagged by /skill:mcp-kimi senior-reviewer): if the
        # per-item _kimi_btn was hidden by some future spec mutation while
        # is_kimi_compatible still returns True, fall back to claude rather
        # than dispatch a kimi action with no visual feedback.
        #
        # Asymmetry note: kimi branch delegates to _on_kimi_clicked (which
        # internally does signal emit + _mark_as_sent). Claude branch
        # orchestrates manually. Contract: _on_kimi_clicked is the canonical
        # handler of the blue arrow — do not inline its body here, mirror its
        # invocation. If _on_kimi_clicked grows side effects, this routing
        # automatically inherits them (single source of truth).
        cmd_text = next_item.command_text()
        cmd_head = spec.name.strip().split(None, 1)[0].lower()
        use_kimi = (
            self._use_kimi_chk.isChecked()
            and is_kimi_compatible(spec.name)
            and getattr(next_item, "_kimi_btn", None) is not None
            and next_item._kimi_btn.isVisible()
        )

        # ALWAYS cancel any pending modal-confirmation Enter from a previous
        # dispatch. Otherwise a 1s-delayed Enter scheduled by a previous
        # /effort can fire into the next command's AskUserQuestion menu
        # and silently select the default option.
        self._cancel_pending_modal_enter()

        # --force Kimi: rota dedicada para o workspace terminal. /model e
        # /effort viram apenas bolinha amarela (sem dispatch). /clear vai
        # SO para o workspace. Demais comandos ganham prefixo /skill:. A
        # seta azul nao participa deste fluxo — checamos antes do branch
        # use_kimi para garantir precedencia.
        if self._force_kimi_chk.isChecked():
            if cmd_head.startswith("/model") or cmd_head.startswith("/effort"):
                # Bolinha amarela so — sem dispatch e sem update de label.
                next_item._mark_as_sent()
                return
            if cmd_head == "/clear":
                signal_bus.run_command_in_workspace_terminal.emit(cmd_text)
                self._on_run_command(cmd_text)
                next_item._mark_as_sent()
                self._last_workspace_dispatch_was_clear = True
                return
            # Validar skill wrapper antes de despachar (HIGH 2).
            slug = cmd_head[1:].split()[0] if cmd_head.startswith("/") else ""
            if slug and not self._resolve_skill_target(slug):
                signal_bus.toast_requested.emit(
                    f"--force Kimi: skill '{slug}' nao encontrada em "
                    ".claude/commands/skill/ nem .agents/skills/ — dispatch abortado.",
                    "warn",
                )
                return
            transformed = self._inject_skill_prefix(cmd_text)
            signal_bus.run_command_in_workspace_terminal.emit(transformed)
            # Bookkeeping com cmd_text ORIGINAL (nao transformado) para que
            # _highlight_current_command consiga bater contra item.command_text()
            # — issue HIGH 3 do review adversarial.
            self._on_run_command(cmd_text)
            next_item._mark_as_sent()
            return

        # Special case: /clear with Use Kimi checkbox active clears BOTH
        # CLI sessions (interactive + workspace). The two emits drive
        # MetricsBar's per-channel auto-idle independently, so each dot
        # turns green on its own 1s timer.
        clear_both = (
            cmd_head == "/clear" and self._use_kimi_chk.isChecked()
        )
        if clear_both:
            signal_bus.run_command_in_terminal.emit(cmd_text)
            signal_bus.run_command_in_workspace_terminal.emit(cmd_text)
            self._on_run_command(cmd_text)
            next_item._mark_as_sent()
            self._last_workspace_dispatch_was_clear = True
        elif use_kimi:
            next_item._on_kimi_clicked()
            self._last_workspace_dispatch_was_clear = False  # consumed by blue arrow
        else:
            signal_bus.run_command_in_terminal.emit(cmd_text)
            self._on_run_command(cmd_text)
            next_item._mark_as_sent()
            # Pure interactive dispatch does not affect the workspace flag.

        # /effort pede confirmação no Claude Code: agenda um Enter extra 1s
        # depois para aceitar o prompt automaticamente. O timer é cancelado
        # se um novo dispatch acontecer antes do Enter firar (proteção
        # contra firar dentro de AskUserQuestion do próximo comando).
        if spec.name.strip().lower().startswith("/effort"):
            self._arm_pending_modal_enter()

    def _arm_pending_modal_enter(self) -> None:
        """Schedule a 1s Enter to dismiss /effort's confirmation modal,
        cancellable by the next dispatch."""
        self._cancel_pending_modal_enter()
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(signal_bus.submit_enter_to_terminal.emit)
        t.start(1000)
        self._pending_modal_enter_timer = t

    def _cancel_pending_modal_enter(self) -> None:
        """Drop any pending modal-confirmation Enter. Called by every new
        dispatch so a stale Enter can never land in a future command's
        interactive prompt."""
        if self._pending_modal_enter_timer is not None:
            self._pending_modal_enter_timer.stop()
            self._pending_modal_enter_timer = None
