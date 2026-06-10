"""
CommandItemWidget — Single row in the command queue.

Visual states per DESIGN.md 2.3:
  Pendente   ○ gray   /cmd-name  [Model]
  Executando ⊙ blue   /cmd-name  [Model] ●●● (pulsing)
  Concluido  ✓ green  /cmd-name  [Model]
  Erro       ✕ red    /cmd-name  [Model]
  Pulado     ─ muted  /cmd-name (strikethrough) [Model]
  Incerto    ? amber  /cmd-name  [Model]
"""

from __future__ import annotations

import shlex
from collections.abc import Callable

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workflow_app.command_queue.kimi_whitelist import adapt_to_kimi, is_kimi_compatible
from workflow_app.command_queue.provider_router import Provider
from workflow_app.domain import CommandSpec, CommandStatus, InteractionType, ModelName
from workflow_app.widgets.model_badge import ModelBadge

# Error state colours (Graphite Amber theme)
_COLOR_ERROR_BG = "#3F1010"
_COLOR_ERROR_BORDER = "#7F1D1D"
_COLOR_ERROR_TEXT = "#FCA5A5"

_STATUS_SYMBOL: dict[CommandStatus, str] = {
    CommandStatus.PENDENTE:   "○",
    CommandStatus.EXECUTANDO: "⊙",
    CommandStatus.CONCLUIDO:  "✓",
    CommandStatus.ERRO:       "✕",
    CommandStatus.PULADO:     "─",
    CommandStatus.INCERTO:    "?",
}

# Botao unico adaptavel (source.md secao 9): cor/tooltip/destino derivam do
# provider efetivo. Pares (cor, cor_hover) por provider.
_PROVIDER_BTN_STYLE: dict[Provider, tuple[str, str]] = {
    Provider.CLAUDE: ("#22C55E", "#86EFAC"),  # verde  -> T1
    Provider.KIMI:   ("#3B82F6", "#93C5FD"),  # azul   -> T2
    Provider.CODEX:  ("#A855F7", "#D8B4FE"),  # roxo   -> T3
}
_PROVIDER_LABEL: dict[Provider, str] = {
    Provider.CLAUDE: "Claude",
    Provider.KIMI:   "Kimi worker",
    Provider.CODEX:  "Codex worker",
}
_PROVIDER_DEST: dict[Provider, str] = {
    Provider.CLAUDE: "T1 terminal-interactive",
    Provider.KIMI:   "T2 terminal-workspace",
    Provider.CODEX:  "T3 terminal-codex-output",
}
# Cinza do estado Desabilitado (item nao executavel / recalculo falhou).
_PROVIDER_DISABLED_COLOR = "#52525B"


def _format_command_label(name: str, config_path: str, *, max_lines: int = 3) -> str:
    """Render a command + args as at most `max_lines` visual rows.

    Strategy:
      - line 1 is always the command name (untouched).
      - remaining tokens are grouped into `--flag value` pairs when possible,
        then evenly distributed across the remaining `max_lines - 1` rows.
        Trailing rows absorb leftovers so flag/value pairs stay together
        unless the row count forces a split.

    Examples (max_lines=3):
      "/prd-create"                                 -> "/prd-create"
      "/foo .claude/projects/x.json"                -> "/foo\\n.claude/projects/x.json"
      "/cmd --slug s --item 5 path/cfg"             -> "/cmd\\n--slug s --item 5\\npath/cfg"
    """
    raw = f"{name} {config_path}".strip()
    if not raw:
        return ""
    parts = raw.split()
    if len(parts) <= 1:
        return raw

    head = parts[0]
    rest = parts[1:]

    # Group --flag/-f value pairs so the row split keeps them together when possible.
    groups: list[str] = []
    i = 0
    while i < len(rest):
        tok = rest[i]
        nxt = rest[i + 1] if i + 1 < len(rest) else None
        is_flag = tok.startswith("-")
        next_is_value = nxt is not None and not nxt.startswith("-")
        if is_flag and next_is_value:
            groups.append(f"{tok} {nxt}")
            i += 2
        else:
            groups.append(tok)
            i += 1

    remaining = max_lines - 1  # rows available for arguments
    if remaining <= 0:
        return head

    if len(groups) <= remaining:
        return "\n".join([head, *groups])

    # Distribute groups across the remaining rows, front-loading the extras
    # (so the last row is short — easier to read in a 280px panel).
    n = len(groups)
    base, extra = divmod(n, remaining)
    lines = [head]
    idx = 0
    for row in range(remaining):
        count = base + (1 if row < extra else 0)
        lines.append(" ".join(groups[idx:idx + count]))
        idx += count
    return "\n".join(lines)


class CommandItemWidget(QWidget):
    """One command row in the queue list."""

    # Signals
    remove_requested = Signal(int)          # position
    skip_requested = Signal(int)            # position
    edit_model_requested = Signal(int)      # position
    retry_requested = Signal(int)           # position (module-12/TASK-3)
    cancel_requested = Signal()             # no arg — cancel whole pipeline
    run_in_terminal_requested = Signal(str) # command name (Claude — interactive terminal)
    run_in_kimi_terminal_requested = Signal(str)  # Kimi-adapted prompt (workspace terminal)
    run_in_codex_terminal_requested = Signal(str)  # Codex prompt (T3 codex-output terminal)
    run_local_action_requested = Signal(object)    # CommandSpec — in-process local-action (kind=="local-action"); queue widget owns dispatch
    kimi_adaptation_failed = Signal(str)    # command_text whose adapt_to_kimi raised ValueError (queue widget toasts — Zero Silencio)
    sent_state_changed = Signal(bool)       # _is_sent toggled (drives queue-progress-ring)

    # Minimum Manhattan distance before drag begins (px)
    _DRAG_THRESHOLD = 10

    def __init__(
        self,
        spec: CommandSpec,
        can_reorder_fn: Callable[[int], bool] | None = None,
        parent: QWidget | None = None,
        *,
        provider_resolver: Callable[[CommandSpec], Provider] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CommandItemWidget")
        self._spec = spec
        self._status = CommandStatus.PENDENTE
        self._is_sent: bool = False
        self._highlighted: bool = False
        self._can_reorder_fn: Callable[[int], bool] = can_reorder_fn or (lambda _pos: True)
        self._drag_start_pos: QPoint | None = None
        # Resolver injetado pelo queue widget: classifica o provider efetivo do
        # item (Claude/Kimi/Codex) a partir do estado de worker + Main LLM. None
        # => sempre Claude (verde/T1), preservando o comportamento legado e o
        # criterio de aceite 3 (sem workers ativos, equivale ao verde atual).
        self._provider_resolver: Callable[[CommandSpec], Provider] | None = (
            provider_resolver
        )
        self._current_provider: Provider | None = Provider.CLAUDE
        self.setMinimumHeight(53)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._setup_ui()
        if spec.testid:
            self.setProperty("testid", spec.testid)
        elif spec.kimi_eligible:
            self.setProperty("testid", "queue-item-kimi-run")
        if spec.blocked_reason:
            self.set_status(CommandStatus.ERRO, spec.blocked_reason)

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Main row
        main_row_widget = QWidget()
        layout = QHBoxLayout(main_row_widget)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        # Single adaptive execution button (substitui o par verde+azul legado).
        # Cor/tooltip/destino derivam do provider efetivo (provider_router),
        # recalculados no clique e quando os workers mudam. Criterio de aceite 1
        # (um unico botao por item) + criterio de rejeicao 5 (nao deixar dois
        # botoes de execucao). objectName "IconButton" preserva o padding 4px do
        # tema (sem ele o glifo ▶ e clipado no botao 16x16).
        _is_local_action = getattr(self._spec, "kind", "slash") == "local-action"
        self._exec_btn = QPushButton("▶")
        self._exec_btn.setObjectName("IconButton")
        self._exec_btn.setProperty("testid", "queue-item-exec-run")
        self._exec_btn.setFixedSize(16, 16)
        self._exec_btn.clicked.connect(self._on_exec_clicked)
        layout.addWidget(self._exec_btn)
        # Alias retrocompativel: a logica de estado "enviado" (● ambar) e os
        # handlers _on_run_clicked/reset_to_pending continuam operando sobre o
        # MESMO QPushButton — nao existe um segundo botao de execucao.
        self._run_btn = self._exec_btn
        # Elegibilidade worker (eixo estatico identico a regra legada do
        # _kimi_btn): whitelist Kimi OR spec.kimi_eligible, exceto local-action.
        # Consumido pelo gate de play-next do queue widget via
        # is_worker_arrow_visible(); o queue widget pode ocultar (Main Kimi) via
        # set_worker_arrow_visible(False). Distinto da COR do botao, que segue o
        # provider efetivo (resolver).
        self._worker_arrow_visible = (
            not _is_local_action
            and (is_kimi_compatible(self._spec.name) or self._spec.kimi_eligible)
        )

        # Copy button (blue clipboard icon) — copies the full command line
        self._copy_btn = QPushButton("\u29C9")
        self._copy_btn.setObjectName("IconButton")
        self._copy_btn.setFixedSize(16, 16)
        self._copy_btn.setToolTip("Copiar comando")
        self._copy_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  color: #38BDF8; font-size: 12px; }"
            "QPushButton:hover { color: #7DD3FC; }"
        )
        self._copy_btn.clicked.connect(self._on_copy_clicked)
        # local-action items have no slash payload to paste, so the copy
        # button is hidden — the action runs in-process when the queue
        # reaches the item.
        if _is_local_action:
            self._copy_btn.setVisible(False)
        layout.addWidget(self._copy_btn)

        # Quick-delete button (red ✕) — next to copy button on the left side
        self._delete_btn = QPushButton("✕")
        self._delete_btn.setObjectName("IconButton")
        self._delete_btn.setFixedSize(18, 18)
        self._delete_btn.setToolTip("Remover da fila")
        self._delete_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  color: #EF4444; font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { color: #FCA5A5; }"
            "QPushButton:pressed { color: #DC2626; }"
        )
        self._delete_btn.clicked.connect(
            lambda: self.remove_requested.emit(self._spec.position)
        )
        layout.addWidget(self._delete_btn)

        # Command name (+ optional config path) — capped at 3 visual rows.
        # Tokens beyond the cap are merged into existing rows so very long
        # commands (eg. /daily-loop:review-done --slug X --item N path/cfg)
        # continue legible inside the 280px panel without scrolling vertically.
        label_text = _format_command_label(
            self._spec.name, self._spec.config_path, max_lines=3
        )
        if _is_local_action:
            # Make it visually distinct from a slash-command paste; the user
            # should immediately see this is an in-process action.
            label_text = f"⚙ {label_text}"
        self._name_label = QLabel(label_text)
        self._name_label.setStyleSheet(
            "color: #FAFAFA; font-family: monospace; font-size: 11px;"
        )
        layout.addWidget(self._name_label, stretch=1)

        # Interaction type badge (auto / inter)
        interaction_text = self._spec.interaction_badge_text()
        self._interaction_badge = QLabel(interaction_text)
        _is_auto = self._spec.interaction_type == InteractionType.AUTO
        _inter_color = "#22C55E" if _is_auto else "#FBBF24"
        self._interaction_badge.setStyleSheet(
            f"color: {_inter_color}; font-size: 9px; font-weight: 600;"
            " font-family: monospace; padding: 1px 4px;"
            f" border: 1px solid {_inter_color}; border-radius: 3px;"
        )
        self._interaction_badge.setFixedHeight(18)

        # Model badge — construido para preservar API publica (ex.:
        # set_model, testes que leem _model_badge.text()), mas nao
        # renderizado: as badges de model/auto foram removidas dos itens
        # da queue-command-list a pedido do usuario.
        self._model_badge = ModelBadge(self._spec.model, short=True, parent=self)
        self._model_badge.setVisible(False)
        self._interaction_badge.setVisible(False)
        root.addWidget(main_row_widget)

        # Dashed separator line
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet(
            "border: none; border-top: 1px dashed #3F3F46; background: transparent;"
        )
        root.addWidget(separator)

        # Error row (hidden by default — shown only when status == ERRO)
        self._error_row = QWidget()
        self._error_row.setObjectName("ErrorRow")
        er_layout = QHBoxLayout(self._error_row)
        er_layout.setContentsMargins(10, 2, 10, 6)
        er_layout.setSpacing(6)

        self._error_label = QLabel()
        self._error_label.setStyleSheet(f"color: {_COLOR_ERROR_TEXT}; font-size: 11px;")
        self._error_label.setWordWrap(True)
        er_layout.addWidget(self._error_label, stretch=1)

        self._btn_retry = QPushButton("Retentar")
        self._btn_retry.setFixedWidth(72)
        self._btn_retry.setStyleSheet(
            "QPushButton { background-color: #7F1D1D; color: #FCA5A5;"
            "  border: 1px solid #991B1B; border-radius: 3px; font-size: 11px; padding: 2px 6px; }"
            "QPushButton:hover { background-color: #991B1B; }"
        )
        self._btn_retry.clicked.connect(
            lambda: self.retry_requested.emit(self._spec.position)
        )
        er_layout.addWidget(self._btn_retry)

        self._btn_skip_err = QPushButton("Pular")
        self._btn_skip_err.setFixedWidth(52)
        self._btn_skip_err.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 3px; font-size: 11px; padding: 2px 6px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        self._btn_skip_err.clicked.connect(
            lambda: self.skip_requested.emit(self._spec.position)
        )
        er_layout.addWidget(self._btn_skip_err)

        self._btn_cancel_pipeline = QPushButton("Cancelar")
        self._btn_cancel_pipeline.setFixedWidth(64)
        self._btn_cancel_pipeline.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 3px; font-size: 11px; padding: 2px 6px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        self._btn_cancel_pipeline.clicked.connect(self.cancel_requested)
        er_layout.addWidget(self._btn_cancel_pipeline)

        self._error_row.setVisible(False)
        root.addWidget(self._error_row)

        # Pinta o botao unico conforme o provider efetivo inicial (verde/Claude
        # por default; azul/roxo se um worker ja estiver ativo no resolver).
        self.refresh_provider()
        self._update_appearance()

    # ──────────────────────────────────────────────────── Public API ─── #

    def set_status(self, status: CommandStatus, error_message: str = "") -> None:
        self._status = status
        # Show error row only for ERRO state
        is_error = status == CommandStatus.ERRO
        self._error_row.setVisible(is_error)
        if is_error and error_message:
            self._error_label.setText(error_message)
        elif not is_error:
            self._error_label.clear()
        self._update_appearance()

    def get_spec(self) -> CommandSpec:
        return self._spec

    def command_text(self) -> str:
        """Return the full command text (name + config_path), shell-quoted when needed.

        config_path pode conter caminhos arbitrarios (ex.: boilerplate aceita repo
        path do usuario). shlex.quote nao adiciona aspas para paths sem caracteres
        especiais, entao templates legados (ex.: ".claude/projects/foo.json") ficam
        intocados.
        """
        if not self._spec.config_path:
            return self._spec.name
        return f"{self._spec.name} {shlex.quote(self._spec.config_path)}"

    def set_highlighted(self, highlighted: bool) -> None:
        """Mark this item as the 'current' command (matches queue-last-command)."""
        if self._highlighted == highlighted:
            return
        self._highlighted = highlighted
        self._update_appearance()

    def set_model(self, model: ModelName) -> None:
        self._spec = CommandSpec(
            name=self._spec.name,
            model=model,
            interaction_type=self._spec.interaction_type,
            position=self._spec.position,
            is_optional=self._spec.is_optional,
        )
        self._model_badge.deleteLater()
        self._model_badge = ModelBadge(model, short=True, parent=self)
        # Badge nunca eh renderizada (vide __init__): mantida apenas para
        # preservar API publica/testes que leem _model_badge.text().
        self._model_badge.setVisible(False)

    def _on_copy_clicked(self) -> None:
        """Copy the full command line to the clipboard."""
        text = self.command_text()
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    def _on_run_clicked(self) -> None:
        """Toggle sent state: play → request dispatch; amber dot → reset to pending.

        NÃO marca enviado aqui (fix D-1, 2026-06-02). O `_mark_as_sent` e
        responsabilidade do slot do queue widget `_on_single_button_green_dispatch`,
        que so marca quando `_dispatch_green_arrow` publica de fato (retorna True).
        Sob Main Codex/Kimi o dispatch pode abortar (`.md`/skill ausente); marcar
        aqui de forma incondicional deixaria o item ambar sem ter despachado —
        mesma assimetria ja corrigida no caminho Codex (`_on_codex_clicked`)."""
        if self._is_sent:
            self.reset_to_pending()
            return
        self.run_in_terminal_requested.emit(self.command_text())

    def _on_kimi_clicked(self) -> None:
        """Send Kimi-adapted prompt to the workspace terminal and mark as sent.

        Does NOT trigger the Claude (interactive) terminal — the green arrow
        becomes amber as if it had been run, so play-next skips it.
        """
        if self._is_sent:
            return
        try:
            kimi_prompt = adapt_to_kimi(self.command_text())
        except ValueError:
            # Fix D-6: nao engolir em silencio (Zero Silencio). O queue widget
            # emite um toast de warning; o item permanece pendente.
            self.kimi_adaptation_failed.emit(self.command_text())
            return
        self.run_in_kimi_terminal_requested.emit(kimi_prompt)
        self._mark_as_sent()

    def _on_codex_clicked(self) -> None:
        """Despacha o item ao worker Codex (T3). NAO marca enviado aqui.

        Espelha _on_kimi_clicked: emite o sinal dedicado consumido pelo queue
        widget. A adaptacao Codex/dispatcher e o tratamento de falhas sao
        responsabilidade do handler do queue widget (wiring de dispatch +
        failure handling detalhados na task 006); aqui so emitimos o slash cru.

        Diferente das setas Claude/Kimi, TODAS as condicoes de falha do Codex
        (comando inexistente, T3 nao pronto, adaptacao vazia) vivem no
        dispatcher do queue widget. Por isso o `_mark_as_sent()` e responsabi-
        lidade do slot conectado (`_on_single_button_codex_dispatch`), que so
        marca enviado quando `_dispatch_codex_command` publica de fato. Marcar
        aqui de forma incondicional deixaria o item ambar mesmo num abort
        (review-executed task 006, finding F2): o item ficaria 'enviado' e o
        play-next o pularia apesar de nada ter sido despachado.
        """
        if self._is_sent:
            return
        self.run_in_codex_terminal_requested.emit(self.command_text())

    # ─────────────────────────── Provider (botao unico) ──────────────────── #

    def effective_provider(self) -> Provider | None:
        """Provider efetivo deste item, recalculado on-demand (criterio 8).

        Sem resolver injetado -> Provider.CLAUDE (verde/T1 legado, criterio de
        aceite 3). Resolver que levanta excecao -> None == estado Desabilitado
        (sad path do requisito visual 5: nunca crashar nem despachar provider
        stale; o botao fica cinza e inerte).
        """
        if self._provider_resolver is None:
            return Provider.CLAUDE
        try:
            prov = self._provider_resolver(self._spec)
        except Exception:
            return None
        return prov if isinstance(prov, Provider) else Provider.CLAUDE

    def _apply_exec_style(self, color: str, hover: str) -> None:
        """Aplica cor/hover no botao unico e forca re-polish do stylesheet.

        Sem o unpolish/polish a regra global QPushButton#IconButton do theme.py
        mantem a cor anterior em cache (mesmo motivo de _mark_as_sent)."""
        self._exec_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            f"  color: {color}; font-size: 10px; }}"
            f"QPushButton:hover {{ color: {hover}; }}"
            f"QPushButton:disabled {{ color: {_PROVIDER_DISABLED_COLOR}; }}"
        )
        style = self._exec_btn.style()
        if style is not None:
            style.unpolish(self._exec_btn)
            style.polish(self._exec_btn)
        self._exec_btn.update()

    def refresh_provider(self) -> None:
        """Recolore o botao unico conforme o provider efetivo + tooltip/destino.

        No-op visual enquanto o item esta 'enviado' (o indicador ambar vence,
        vide tabela secao 9 linha 'Enviado'). Conectado ao toggle de workers no
        queue widget para recalcular sem reload manual (requisito visual 3)."""
        self._current_provider = self.effective_provider()
        if self._is_sent:
            return
        self._exec_btn.setText("▶")
        prov = self._current_provider
        if prov is None:
            # Desabilitado: cinza, inerte, sem dispatch.
            self._exec_btn.setEnabled(False)
            self._exec_btn.setToolTip(
                "Item nao executavel no estado atual (provider indefinido)"
            )
            self._apply_exec_style(
                _PROVIDER_DISABLED_COLOR, _PROVIDER_DISABLED_COLOR
            )
            return
        self._exec_btn.setEnabled(True)
        base, hover = _PROVIDER_BTN_STYLE[prov]
        self._exec_btn.setToolTip(
            f"Enviar para {_PROVIDER_LABEL[prov]} ({_PROVIDER_DEST[prov]})"
        )
        self._apply_exec_style(base, hover)

    def is_worker_arrow_visible(self) -> bool:
        """Item esta apresentando seta de worker (azul/roxo).

        Substitui o legado `_kimi_btn.isVisible()` como marcador 'item worker-
        bound' consumido pelo gate de play-next (llm-routing-div.md §3.1)."""
        return self._worker_arrow_visible

    def set_worker_arrow_visible(self, visible: bool) -> None:
        """Liga/desliga o marcador worker-bound (ex.: Main Kimi oculta todos).

        Migra o legado `_kimi_btn.setVisible()`; recolore o botao unico para
        refletir o provider efetivo apos a mudanca de estado de worker."""
        self._worker_arrow_visible = bool(visible)
        self.refresh_provider()

    def _on_exec_clicked(self) -> None:
        """Clique no botao unico: recalcula o provider AGORA (criterio de
        rejeicao 8) e roteia ao handler do provider efetivo.

        Sent -> toggle reset (paridade com a seta verde legada). Provider None
        (Desabilitado) -> nao despacha; apenas reafirma o estado cinza."""
        if self._is_sent:
            self.reset_to_pending()
            return
        # Fix D-5: local-action NUNCA vai a um terminal (invariante 8). Roda
        # in-process; o queue widget e dono do dispatch (dispatch_local_action)
        # e do toast. O item so encaminha o spec, sem importar a logica de
        # local-action nem colar `spec.name` no T1.
        if getattr(self._spec, "kind", "slash") == "local-action":
            self.run_local_action_requested.emit(self._spec)
            return
        prov = self.effective_provider()
        self._current_provider = prov
        if prov is None:
            self.refresh_provider()  # garante cinza/disabled + tooltip
            return
        if prov is Provider.KIMI:
            self._on_kimi_clicked()
        elif prov is Provider.CODEX:
            self._on_codex_clicked()
        else:
            self._on_run_clicked()

    def _mark_as_sent(self) -> None:
        """Visually mark this row as already sent to terminal."""
        was_sent = self._is_sent
        self._is_sent = True
        self._run_btn.setText("●")
        self._run_btn.setToolTip("Resetar para pendente")
        self._run_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  color: #FBBF24; font-size: 11px; }"
            "QPushButton:hover { color: #FDE68A; }"
        )
        # Force Qt to re-evaluate stylesheet cascade — without this, the global
        # QPushButton#IconButton rule from theme.py can keep the previous color
        # cached and the ● glyph stays green visually.
        style = self._run_btn.style()
        if style is not None:
            style.unpolish(self._run_btn)
            style.polish(self._run_btn)
        self._run_btn.update()
        if not was_sent:
            self.sent_state_changed.emit(True)

    def is_pending_run(self) -> bool:
        """True if this row has not yet been sent to the terminal."""
        return not self._is_sent

    def reset_to_pending(self) -> None:
        """Reset this row back to pending state (for loop restart)."""
        was_sent = self._is_sent
        self._is_sent = False
        self._run_btn.setText("▶")
        self._run_btn.setEnabled(True)
        # Recolore conforme o provider efetivo (verde Claude por default; azul
        # Kimi / roxo Codex se um worker estiver ativo). refresh_provider ja faz
        # o unpolish/polish, espelhando o que _mark_as_sent fazia para o ambar.
        self.refresh_provider()
        self.set_status(CommandStatus.PENDENTE)
        if was_sent:
            self.sent_state_changed.emit(False)

    # ─────────────────────────────────────────── Drag-and-drop source ─── #

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._drag_start_pos is None:
            return
        delta = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
        if delta < self._DRAG_THRESHOLD:
            return
        if not self._can_reorder_fn(self._spec.position):
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self._spec.position))
        drag.setMimeData(mime)
        # Renderiza o widget em um pixmap base
        base = QPixmap(self.size())
        base.fill(Qt.GlobalColor.transparent)
        self.render(base)
        # Aplica opacidade em um segundo pixmap
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setOpacity(0.7)
        painter.drawPixmap(0, 0, base)
        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(self._drag_start_pos)
        drag.exec(Qt.DropAction.MoveAction)
        self._drag_start_pos = None

    # ─────────────────────────────────────────────────────── Helpers ─── #

    def _update_appearance(self) -> None:
        # Highlight border for the row matching the last-played command
        _hl = (
            " border-top: 2px solid #E4E4E7; border-bottom: 2px solid #E4E4E7;"
            if self._highlighted else ""
        )

        if self._status == CommandStatus.PULADO:
            self._name_label.setStyleSheet(
                "color: #52525B; font-family: monospace; font-size: 11px;"
                " text-decoration: line-through;"
            )
            self.setStyleSheet(
                f"QWidget#CommandItemWidget {{ background-color: #27272A;{_hl} }}"
            )
        elif self._status == CommandStatus.EXECUTANDO:
            self._name_label.setStyleSheet(
                "color: #FAFAFA; font-family: monospace; font-size: 11px;"
            )
            self.setStyleSheet(
                f"QWidget#CommandItemWidget {{ background-color: #27272A;"
                f" border-left: 2px solid #38BDF8;{_hl} }}"
            )
        elif self._status == CommandStatus.CONCLUIDO:
            self._name_label.setStyleSheet(
                "color: #A1A1AA; font-family: monospace; font-size: 11px;"
            )
            self.setStyleSheet(
                f"QWidget#CommandItemWidget {{ background-color: #27272A;{_hl} }}"
            )
        elif self._status == CommandStatus.ERRO:
            self._name_label.setStyleSheet(
                "color: #FB7185; font-family: monospace; font-size: 11px;"
            )
            if self._highlighted:
                self.setStyleSheet(
                    f"QWidget#CommandItemWidget {{ background-color: {_COLOR_ERROR_BG};"
                    f" border: 1px solid {_COLOR_ERROR_BORDER}; border-radius: 2px;"
                    f" border-top: 2px solid #E4E4E7; border-bottom: 2px solid #E4E4E7; }}"
                )
            else:
                self.setStyleSheet(
                    f"QWidget#CommandItemWidget {{ background-color: {_COLOR_ERROR_BG};"
                    f" border: 1px solid {_COLOR_ERROR_BORDER}; border-radius: 2px; }}"
                )
        else:
            self._name_label.setStyleSheet(
                "color: #FAFAFA; font-family: monospace; font-size: 11px;"
            )
            self.setStyleSheet(
                f"QWidget#CommandItemWidget {{ background-color: #27272A;{_hl} }}"
                "QWidget#CommandItemWidget:hover { background-color: #3F3F46; }"
            )

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #27272A; border: 1px solid #3F3F46;"
            "  color: #FAFAFA; padding: 4px; }"
            "QMenu::item { padding: 6px 16px; border-radius: 4px; }"
            "QMenu::item:selected { background-color: #3F3F46; }"
            "QMenu::separator { background-color: #3F3F46; height: 1px; }"
        )
        edit_action = menu.addAction("✏ Editar Modelo")
        skip_action = menu.addAction("⏭ Marcar Pular")
        menu.addSeparator()
        remove_action = menu.addAction("🗑 Remover")
        remove_action.setData("danger")

        action = menu.exec(self.mapToGlobal(pos))
        if action == edit_action:
            self.edit_model_requested.emit(self._spec.position)
        elif action == skip_action:
            self.skip_requested.emit(self._spec.position)
        elif action == remove_action:
            self.remove_requested.emit(self._spec.position)
