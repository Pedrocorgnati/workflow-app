"""Dialog de configuracao dos 9 seeds `blacksmith/brainstorm-mcp/0[1-9]-*.md`.

Materializa T4 do loop 05-21-implantation-tasklist-aba-brainstorm (gear
`brainstorm-mcp-config-gear`). Read+Update apenas (sem Create/Delete).
8 campos editaveis por seed: label, type, prompt, agent_name, agent_path,
action, target_path (bool), target_terminal.

Persistencia per-seed:
- yaml frontmatter preservado opacamente (sort_keys=False, chaves
  desconhecidas mantidas);
- body markdown preservado integralmente, exceto bloco `## Prompt canonico`;
- atomic write (tmpfile + fsync + os.replace + fsync do diretorio);
- file lock cooperativo `flock(LOCK_EX|LOCK_NB)` durante save.

Validacao bloqueante (Save desabilitado e label vermelho com motivo):
- label vazio;
- type fora de VALID_BUTTON_TYPES;
- action fora de VALID_ACTIONS_PTBR (7 literais T5);
- agent_path fora do repo_root OU inexistente quando != "TODO";
- (target_path, target_terminal) fora da tabela ACTION_COHERENCE;
- qualquer campo excedendo MAX_FIELD_LEN.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

# Catalogos reutilizados do widget MCPPromptButton.
from workflow_app.widgets.mcp_prompt_button import (
    VALID_ACTIONS_PTBR,
    VALID_BUTTON_TYPES,
    VALID_TERMINALS,
)


class SeedError(Exception):
    """Falha de parsing/escrita de seed `.md`."""


# Limites per-campo (anti YAML bomb + casa com gate st_size>64KB do loader T2).
MAX_FIELD_LEN: dict[str, int] = {
    "label": 80,
    "agent_name": 120,
    "agent_path": 260,
    "prompt": 32768,
}

# Tabela canonica de coerencia (action -> {target_path}, {target_terminal}).
ACTION_COHERENCE: dict[str, dict[str, set]] = {
    "Criar arquivo":    {"target_path": {False}, "target_terminal": {"terminal-interactive-output"}},
    "Otimizar":         {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    "Criar tasks":      {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    "Revisar tasks":    {"target_path": {True},  "target_terminal": {"terminal-interactive-output"}},
    "Executar":         {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    "Revisar execucao": {"target_path": {True},  "target_terminal": {"terminal-interactive-output"}},
    "Loop prepare":     {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
}

CURRENT_SCHEMA_VERSION = 1

_PROMPT_RX = re.compile(r"(^## Prompt canonico\s*$\n?)(.*?)(?=^## |\Z)", re.M | re.S)
_FRONTMATTER_RX = re.compile(r"^---\n(.*?)\n---\n?(.*)\Z", re.S)


def _sanitize(value: str, key: str) -> str:
    """Remove BOM/null + strip + cap por MAX_FIELD_LEN."""
    s = value.replace("﻿", "").replace("\x00", "").strip()
    cap = MAX_FIELD_LEN.get(key, 1024)
    if len(s) > cap:
        raise ValueError(f"Campo '{key}' excede {cap} chars (tem {len(s)})")
    return s


def load_seed(path: Path) -> tuple[dict[str, Any], str]:
    """Le `path`, retorna `(meta_dict, body_str)`.

    Tolera BOM utf-8. Falha em frontmatter ausente, root nao-mapping ou
    yaml malformado.
    """
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SeedError(f"{path.name}: erro de leitura: {exc}") from exc
    m = _FRONTMATTER_RX.match(raw)
    if not m:
        raise SeedError(f"{path.name}: frontmatter ausente")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SeedError(f"{path.name}: yaml malformado: {exc}") from exc
    if not isinstance(meta, dict):
        raise SeedError(f"{path.name}: root frontmatter nao e mapping")
    return meta, m.group(2)


def extract_prompt_body(body: str) -> str:
    """Retorna o conteudo do bloco `## Prompt canonico` (sem o heading)."""
    m = _PROMPT_RX.search(body)
    if not m:
        return ""
    return m.group(2).rstrip()


def save_seed(path: Path, patch: dict[str, Any], prompt_body: str) -> None:
    """Aplica `patch` ao frontmatter e substitui o bloco `## Prompt canonico`.

    Atomic write robusto: tmpfile -> fsync -> os.replace -> fsync diretorio.
    File lock cooperativo `flock(LOCK_EX|LOCK_NB)` adquirido durante a operacao.
    Linux: usa fcntl; Windows: pula lock com WARN (app primario e Linux).
    """
    lock_fd = _acquire_lock(path, exclusive=True)
    try:
        meta, body = load_seed(path)
        meta.update(patch)
        if not _PROMPT_RX.search(body):
            raise SeedError(f"{path.name}: bloco '## Prompt canonico' ausente")
        new_body = _PROMPT_RX.sub(
            lambda m: f"{m.group(1)}{prompt_body.rstrip()}\n\n",
            body,
            count=1,
        )
        meta_dump = yaml.safe_dump(meta, sort_keys=False, allow_unicode=False).strip()
        out = f"---\n{meta_dump}\n---\n{new_body}"

        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp",
        )
        tmp_path = Path(tmp)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(out)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            try:
                dfd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass  # fsync de diretorio nao suportado em alguns FS (tmpfs etc).
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
    finally:
        _release_lock(lock_fd)


def _acquire_lock(path: Path, exclusive: bool) -> int | None:
    """Adquire flock cooperativo nao-bloqueante. Retorna fd ou None (Windows)."""
    if sys.platform.startswith("win"):
        return None  # Windows: skip lock com WARN silencioso.
    import fcntl
    fd = os.open(str(path), os.O_RDONLY)
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    try:
        fcntl.flock(fd, mode | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as exc:
        os.close(fd)
        raise SeedError(f"{path.name}: seed em uso (lock indisponivel): {exc}") from exc
    return fd


def _release_lock(fd: int | None) -> None:
    if fd is None:
        return
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class BrainstormMcpConfigDialog(QDialog):
    """Modal application-wide para editar os 9 seeds brainstorm-mcp."""

    saved = Signal()  # Emitido apos save bem-sucedido (rebuild da grade).

    def __init__(
        self,
        parent: QWidget | None,
        repo_root: Path,
        seeds_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("testid", "brainstorm-mcp-config-dialog")
        self.setWindowTitle("Configurar 9 seeds brainstorm-mcp")
        self.setMinimumSize(900, 560)

        self.repo_root: Path = repo_root.resolve()
        self.seeds_dir: Path = (
            seeds_dir.resolve() if seeds_dir
            else (self.repo_root / "blacksmith" / "brainstorm-mcp").resolve()
        )

        # Estado per-seed: lista paralela aos itens da lista lateral.
        self._seed_paths: list[Path] = []
        self._seed_meta: list[dict[str, Any]] = []
        self._seed_prompt: list[str] = []
        self._current_index: int = -1
        self._dirty: bool = False

        self._build_ui()
        self._load_seeds()

    # ---- UI build ----------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # ---- Coluna esquerda: lista dos seeds ----
        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(4)
        list_title = QLabel("Seeds (9)")
        list_title.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        list_layout.addWidget(list_title)
        self._list_widget = QListWidget()
        self._list_widget.setProperty("testid", "brainstorm-mcp-config-list")
        self._list_widget.currentRowChanged.connect(self._on_row_changed)
        list_layout.addWidget(self._list_widget, stretch=1)
        splitter.addWidget(list_panel)

        # ---- Coluna direita: formulario dos 8 campos ----
        form_panel = QWidget()
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(6)

        self._slug_label = QLabel("slug: -")
        self._slug_label.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        form_layout.addWidget(self._slug_label)

        self._label_edit = self._mk_lineedit("brainstorm-mcp-config-label")
        form_layout.addLayout(self._row("Label", self._label_edit))

        self._type_combo = QComboBox()
        self._type_combo.setProperty("testid", "brainstorm-mcp-config-type")
        for t in sorted(VALID_BUTTON_TYPES):
            self._type_combo.addItem(t)
        self._type_combo.currentTextChanged.connect(self._mark_dirty)
        form_layout.addLayout(self._row("Type", self._type_combo))

        self._agent_name_edit = self._mk_lineedit("brainstorm-mcp-config-agent-name")
        form_layout.addLayout(self._row("Agent name", self._agent_name_edit))

        self._agent_path_edit = self._mk_lineedit("brainstorm-mcp-config-agent-path")
        form_layout.addLayout(self._row("Agent path", self._agent_path_edit))

        self._action_combo = QComboBox()
        self._action_combo.setProperty("testid", "brainstorm-mcp-config-action")
        for a in sorted(VALID_ACTIONS_PTBR):
            self._action_combo.addItem(a)
        self._action_combo.currentTextChanged.connect(self._mark_dirty)
        form_layout.addLayout(self._row("Action", self._action_combo))

        target_row = QHBoxLayout()
        target_row.setContentsMargins(0, 0, 0, 0)
        target_row.setSpacing(8)
        target_row.addWidget(QLabel("target_path:"))
        self._target_path_chk = QCheckBox()
        self._target_path_chk.setProperty(
            "testid", "brainstorm-mcp-config-target-path",
        )
        self._target_path_chk.toggled.connect(self._mark_dirty)
        target_row.addWidget(self._target_path_chk)
        target_row.addSpacing(12)
        target_row.addWidget(QLabel("target_terminal:"))
        self._target_terminal_combo = QComboBox()
        self._target_terminal_combo.setProperty(
            "testid", "brainstorm-mcp-config-target-terminal",
        )
        for t in sorted(VALID_TERMINALS):
            self._target_terminal_combo.addItem(t)
        self._target_terminal_combo.currentTextChanged.connect(self._mark_dirty)
        target_row.addWidget(self._target_terminal_combo, stretch=1)
        form_layout.addLayout(target_row)

        form_layout.addWidget(QLabel("Prompt canonico:"))
        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setProperty("testid", "brainstorm-mcp-config-prompt")
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._prompt_edit.setFont(mono)
        self._prompt_edit.textChanged.connect(self._mark_dirty)
        form_layout.addWidget(self._prompt_edit, stretch=1)

        self._error_label = QLabel("")
        self._error_label.setProperty("testid", "brainstorm-mcp-config-error")
        self._error_label.setStyleSheet(
            "color: #F87171; font-size: 11px; background: transparent;",
        )
        self._error_label.setWordWrap(True)
        form_layout.addWidget(self._error_label)

        splitter.addWidget(form_panel)
        splitter.setSizes([220, 680])

        # ---- Botoes Save/Cancel ----
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._save_btn = btn_box.button(QDialogButtonBox.StandardButton.Save)
        self._save_btn.setProperty("testid", "brainstorm-mcp-config-save")
        cancel_btn = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setProperty("testid", "brainstorm-mcp-config-cancel")
        btn_box.accepted.connect(self._on_save_clicked)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

    def _row(self, title: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        lbl = QLabel(f"{title}:")
        lbl.setMinimumWidth(96)
        row.addWidget(lbl)
        row.addWidget(widget, stretch=1)
        return row

    def _mk_lineedit(self, testid: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setProperty("testid", testid)
        edit.textChanged.connect(self._mark_dirty)
        return edit

    # ---- Data load ---------------------------------------------------------

    def _load_seeds(self) -> None:
        if not self.seeds_dir.is_dir():
            self._error_label.setText(
                f"Diretorio inexistente: {self.seeds_dir}",
            )
            self._save_btn.setEnabled(False)
            return

        paths = sorted(self.seeds_dir.glob("0[1-9]-*.md"))
        if len(paths) != 9:
            self._error_label.setText(
                f"Esperados 9 seeds 0[1-9]-*.md; encontrados {len(paths)}",
            )
            self._save_btn.setEnabled(False)
            return

        self._seed_paths = []
        self._seed_meta = []
        self._seed_prompt = []
        for p in paths:
            try:
                meta, body = load_seed(p)
            except SeedError as exc:
                self._error_label.setText(str(exc))
                self._save_btn.setEnabled(False)
                return
            schema_v = meta.get("schema_version", CURRENT_SCHEMA_VERSION)
            if schema_v != CURRENT_SCHEMA_VERSION:
                self._error_label.setText(
                    f"{p.name} schema_version={schema_v!r} incompativel "
                    f"(esperado {CURRENT_SCHEMA_VERSION})",
                )
                self._save_btn.setEnabled(False)
                return
            self._seed_paths.append(p)
            self._seed_meta.append(dict(meta))
            self._seed_prompt.append(extract_prompt_body(body))

            slug = str(meta.get("slug") or p.stem)
            label = str(meta.get("label") or meta.get("title") or slug)
            item = QListWidgetItem(f"{p.name}  -  {label}")
            item.setData(Qt.ItemDataRole.UserRole, slug)
            item.setData(Qt.ItemDataRole.UserRole + 1, f"brainstorm-mcp-config-row-{slug}")
            self._list_widget.addItem(item)

        self._list_widget.setCurrentRow(0)

    # ---- Row swap ----------------------------------------------------------

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._seed_paths):
            return
        # Persistir edits do row anterior em memoria.
        if self._current_index >= 0:
            self._capture_form_into(self._current_index)
        self._current_index = row
        self._render_form_from(row)
        self._dirty = False  # carregar nao conta como dirty.
        self._validate()

    def _render_form_from(self, idx: int) -> None:
        meta = self._seed_meta[idx]
        prompt = self._seed_prompt[idx]
        self._slug_label.setText(f"slug: {meta.get('slug', '-')}")
        # Bloqueia signals durante repopulacao para nao marcar dirty.
        for w in (
            self._label_edit, self._type_combo, self._agent_name_edit,
            self._agent_path_edit, self._action_combo,
            self._target_path_chk, self._target_terminal_combo,
            self._prompt_edit,
        ):
            w.blockSignals(True)

        self._label_edit.setText(str(meta.get("label") or meta.get("title") or ""))
        button_type = str(meta.get("button_type") or "Claude")
        if button_type in VALID_BUTTON_TYPES:
            self._type_combo.setCurrentText(button_type)
        self._agent_name_edit.setText(str(meta.get("agent_name") or ""))
        self._agent_path_edit.setText(str(meta.get("agent_path") or ""))
        action = str(meta.get("action") or "")
        if action in VALID_ACTIONS_PTBR:
            self._action_combo.setCurrentText(action)
        self._target_path_chk.setChecked(bool(meta.get("target_path") or False))
        tt = str(meta.get("target_terminal") or "terminal-interactive-output")
        if tt in VALID_TERMINALS:
            self._target_terminal_combo.setCurrentText(tt)
        self._prompt_edit.setPlainText(prompt)

        for w in (
            self._label_edit, self._type_combo, self._agent_name_edit,
            self._agent_path_edit, self._action_combo,
            self._target_path_chk, self._target_terminal_combo,
            self._prompt_edit,
        ):
            w.blockSignals(False)

    def _capture_form_into(self, idx: int) -> None:
        """Copia valores atuais do form para `self._seed_meta[idx]` e `_seed_prompt[idx]`."""
        meta = self._seed_meta[idx]
        meta["label"] = self._label_edit.text()
        meta["button_type"] = self._type_combo.currentText()
        meta["agent_name"] = self._agent_name_edit.text()
        meta["agent_path"] = self._agent_path_edit.text()
        meta["action"] = self._action_combo.currentText()
        meta["target_path"] = bool(self._target_path_chk.isChecked())
        meta["target_terminal"] = self._target_terminal_combo.currentText()
        meta.setdefault("schema_version", CURRENT_SCHEMA_VERSION)
        self._seed_prompt[idx] = self._prompt_edit.toPlainText()

    # ---- Validation --------------------------------------------------------

    def _mark_dirty(self, *_args: Any) -> None:
        self._dirty = True
        self._validate()

    def _validate(self) -> bool:
        """Valida o estado atual do form. Atualiza error label + save enabled."""
        try:
            label = _sanitize(self._label_edit.text(), "label")
            if not label:
                raise ValueError("Label obrigatorio")

            btn_type = self._type_combo.currentText()
            if btn_type not in VALID_BUTTON_TYPES:
                raise ValueError(f"Type invalido: {btn_type!r}")

            agent_name = _sanitize(self._agent_name_edit.text(), "agent_name")
            agent_path = _sanitize(self._agent_path_edit.text(), "agent_path")
            self._validate_agent_path(agent_path)

            action = self._action_combo.currentText()
            if action not in VALID_ACTIONS_PTBR:
                raise ValueError(f"Action invalida: {action!r}")

            target_path = bool(self._target_path_chk.isChecked())
            target_terminal = self._target_terminal_combo.currentText()
            if target_terminal not in VALID_TERMINALS:
                raise ValueError(f"target_terminal invalido: {target_terminal!r}")
            coh = ACTION_COHERENCE.get(action)
            if coh is None:
                raise ValueError(f"Action sem coerencia mapeada: {action!r}")
            if target_path not in coh["target_path"]:
                raise ValueError(
                    f"Combinacao invalida: action={action!r} requer "
                    f"target_path in {sorted(coh['target_path'])}",
                )
            if target_terminal not in coh["target_terminal"]:
                raise ValueError(
                    f"Combinacao invalida: action={action!r} requer "
                    f"target_terminal in {sorted(coh['target_terminal'])}",
                )

            prompt_text = self._prompt_edit.toPlainText()
            _sanitize(prompt_text, "prompt")
            for line in prompt_text.splitlines():
                stripped = line.lstrip()
                if stripped[:1] in ("{", "["):
                    raise ValueError(
                        "Prompt nao pode comecar linha com yaml flow style (`{`/`[`)",
                    )

        except ValueError as exc:
            self._error_label.setText(str(exc))
            self._save_btn.setEnabled(False)
            return False

        self._error_label.setText("")
        self._save_btn.setEnabled(True)
        return True

    def _validate_agent_path(self, agent_path: str) -> None:
        if not agent_path:
            raise ValueError("agent_path obrigatorio")
        if agent_path == "TODO":
            return  # placeholder permitido em refactor.
        ap = (self.repo_root / agent_path).resolve()
        try:
            ap.relative_to(self.repo_root)
        except ValueError as exc:
            raise ValueError(f"agent_path fora do repo: {agent_path}") from exc
        if not ap.is_file():
            raise ValueError(f"agent_path inexistente: {agent_path}")

    # ---- Save --------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        # Captura o row atual antes de validar.
        if self._current_index >= 0:
            self._capture_form_into(self._current_index)

        if not self._validate():
            return

        # Persiste todos os 9 seeds (idempotente quando nao houve dirty per-seed,
        # mas re-grava igual mesmo assim - simplificacao defensiva).
        try:
            for i, p in enumerate(self._seed_paths):
                meta = self._seed_meta[i]
                prompt = self._seed_prompt[i]
                patch = {
                    "label": meta.get("label", ""),
                    "button_type": meta.get("button_type", "Claude"),
                    "agent_name": meta.get("agent_name", ""),
                    "agent_path": meta.get("agent_path", ""),
                    "action": meta.get("action", ""),
                    "target_path": bool(meta.get("target_path", False)),
                    "target_terminal": meta.get("target_terminal", ""),
                    "schema_version": meta.get(
                        "schema_version", CURRENT_SCHEMA_VERSION,
                    ),
                }
                save_seed(p, patch, prompt)
        except SeedError as exc:
            self._error_label.setText(f"Falha de save: {exc}")
            self._save_btn.setEnabled(True)
            return
        except OSError as exc:
            self._error_label.setText(f"Falha de IO: {exc}")
            self._save_btn.setEnabled(True)
            return

        self.saved.emit()
        self.accept()
