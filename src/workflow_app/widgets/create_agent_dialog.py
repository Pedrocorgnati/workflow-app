"""CreateAgentDialog — modal de criação guiada de agentes (AGENT-TASK-003).

QDialog ApplicationModal com:
- nome (QLineEdit) e descrição (QPlainTextEdit) obrigatórios;
- checkboxes MCP e Brainstorm opcionais e independentes;
- validação reativa via ``workflow_app.create_agent_prompt``;
- estados locais OPEN_IDLE / INVALID / DISPATCHING / ACCEPTED / PARTIAL /
  FAILED / CANCELLED (sem state machine externa);
- submit único (guarda in-flight); Escape fecha só fora de DISPATCHING;
- Enter na descrição multiline NÃO submete;
- feedback nunca afirma "Agente criado" — apenas publicação de prompt.

O dialog NÃO despacha para terminais: emite ``submit_requested(CreateAgentRequest)``
e o host (MainWindow) chama ``report_dispatch_result`` / ``report_builder_failure``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Final

from PySide6.QtCore import QMetaMethod, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workflow_app.create_agent_prompt import (
    DESCRIPTION_MAX_CHARS,
    NAME_MAX_CHARS,
    CreateAgentPromptError,
    build_create_agent_prompt,
    redact_secrets,
    validate_description,
    validate_name,
)

# ── Public types ─────────────────────────────────────────────────────────────


class DialogState(str, Enum):
    """Estados mínimos do modal (matriz de estados do descritivo)."""

    OPEN_IDLE = "OPEN_IDLE"
    INVALID = "INVALID"
    DISPATCHING = "DISPATCHING"
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class CreateAgentRequest:
    """Snapshot imutável emitido no submit — sem widgets, pronto para o builder host."""

    name: str
    description: str
    include_mcp: bool
    include_brainstorm: bool
    prompt: str


@dataclass(frozen=True)
class DispatchReport:
    """Resultado do dispatch reportado pelo host após ``submit_requested``."""

    accepted: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    notes_copied: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def has_any_accepted(self) -> bool:
        return bool(self.accepted)

    @property
    def is_full_success(self) -> bool:
        return bool(self.accepted) and not self.failed

    @property
    def is_partial(self) -> bool:
        return bool(self.accepted) and bool(self.failed)

    @property
    def is_total_failure(self) -> bool:
        return not self.accepted


# Feedback copy — never claim the agent was created.
_MSG_ACCEPTED_PREFIX: Final[str] = "Prompt de criacao publicado em "
_MSG_PARTIAL_PREFIX: Final[str] = "Publicacao parcial. Aceitos: "
_MSG_FAILED_GENERIC: Final[str] = "Falha ao publicar o prompt de criacao."
_MSG_PROGRESS: Final[str] = "Publicando prompt de criacao..."
_FORBIDDEN_SUCCESS_PHRASE: Final[str] = "Agente criado"
# Matches every casing of the forbidden claim, with any run of whitespace
# between the words (a wrapped label still reads as the claim) and with the
# "foi/foram" variants. The lookbehind spares the NEGATED form: "nenhum agente
# foi criado" is the copy we WANT, and rewriting it would invert its meaning.
_FORBIDDEN_SUCCESS_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!nenhum\s)agentes?\s+(?:foi\s+|foram\s+)?criad[oa]s?", re.IGNORECASE
)


# Any trace of the prompt envelope in a host error means the payload leaked
# into the message — replace the whole line by the generic copy.
_PROMPT_ECHO_RE: Final[re.Pattern[str]] = re.compile(
    r"</?agent-request-json>|\"destinations\"\s*:", re.IGNORECASE
)


# Separators that render as nothing but split a phrase for a regex engine.
# Cf is covered by category; these are listed because they are the ones an
# attacker reaches for first, and because U+2028/U+2029 are Zl/Zp, not Cf.
_INVISIBLE_EXTRA: Final[frozenset[str]] = frozenset(
    {
        "\u200b",  # ZERO WIDTH SPACE
        "\ufeff",  # BOM / ZERO WIDTH NO-BREAK SPACE
        "\u2028",  # LINE SEPARATOR (Zl)
        "\u2029",  # PARAGRAPH SEPARATOR (Zp)
    }
)


def _strip_invisible(text: str) -> str:
    """Drop invisible codepoints so they cannot split a guarded phrase.

    ``_FORBIDDEN_SUCCESS_RE`` matches on visible words; a zero-width character
    wedged between them ("Agente\\u200b criado") would defeat the guard while
    reading as the forbidden claim on screen. Normalizing to NFC first keeps
    the comparison stable for composed/decomposed input.
    """
    return "".join(
        ch
        for ch in unicodedata.normalize("NFC", text)
        if unicodedata.category(ch) != "Cf" and ch not in _INVISIBLE_EXTRA
    )


def _rewrite_forbidden_phrase(match: re.Match[str]) -> str:
    """Replace the claim, mirroring the casing of the matched text."""
    original = match.group(0)
    if original.isupper():
        return "PROMPT PUBLICADO"
    if original[:1].isupper():
        return "Prompt publicado"
    return "prompt publicado"

_INPUT_STYLE: Final[str] = (
    "QLineEdit, QPlainTextEdit {"
    "  background-color: #27272A; color: #FAFAFA;"
    "  border: 1px solid #3F3F46; border-radius: 4px; padding: 6px 8px;"
    "}"
    "QLineEdit:disabled, QPlainTextEdit:disabled {"
    "  color: #71717A; background-color: #1F1F23;"
    "}"
)
_LABEL_STYLE: Final[str] = "color: #FAFAFA; font-size: 13px; font-weight: 600;"
_ERROR_STYLE: Final[str] = (
    "color: #F87171; font-size: 12px; background: transparent; padding: 2px 0;"
)
_PROGRESS_STYLE: Final[str] = (
    "color: #A1A1AA; font-size: 12px; background: transparent; padding: 2px 0;"
)
_CHECK_STYLE: Final[str] = "color: #FAFAFA; font-size: 13px;"


class CreateAgentDialog(QDialog):
    """Modal de criação guiada de agentes (testid ``create-agent-dialog``)."""

    submit_requested = Signal(object)  # CreateAgentRequest
    state_changed = Signal(str)  # DialogState value

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Criar agente")
        self.setProperty("testid", "create-agent-dialog")
        self.setMinimumSize(480, 420)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet("background-color: #18181B;")

        self._state: DialogState = DialogState.OPEN_IDLE
        self._in_flight: bool = False
        self._last_request: CreateAgentRequest | None = None
        self._last_feedback: str = ""
        self._escape_blocked: bool = False
        self._torn_down: bool = False
        self._emitting_submit: bool = False

        self._build_ui()
        self._wire_validation()
        self._apply_state(DialogState.OPEN_IDLE)
        self._refresh_submit_enabled()

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def state(self) -> DialogState:
        return self._state

    @property
    def last_feedback(self) -> str:
        return self._last_feedback

    @property
    def last_request(self) -> CreateAgentRequest | None:
        return self._last_request

    @property
    def in_flight(self) -> bool:
        return self._in_flight

    @property
    def torn_down(self) -> bool:
        """True after the teardown ran (close by success, partial or cancel)."""
        return self._torn_down

    def has_sensitive_data(self) -> bool:
        """True while name/description/request/prompt still live in memory.

        Used by the host and by focal tests to prove the teardown contract
        (AGENT-TASK-009): nothing typed by the operator survives the close.
        """
        return bool(
            self._name_input.text()
            or self._description_input.toPlainText()
            or self._last_request is not None
        )

    def name_text(self) -> str:
        return self._name_input.text()

    def description_text(self) -> str:
        return self._description_input.toPlainText()

    def include_mcp(self) -> bool:
        return self._mcp_checkbox.isChecked()

    def include_brainstorm(self) -> bool:
        return self._brainstorm_checkbox.isChecked()

    def set_fields(
        self,
        *,
        name: str = "",
        description: str = "",
        include_mcp: bool = False,
        include_brainstorm: bool = False,
    ) -> None:
        """Populate fields (tests / re-open helpers). No-op while DISPATCHING."""
        if self._state == DialogState.DISPATCHING:
            return
        self._name_input.setText(name)
        self._description_input.setPlainText(description)
        self._mcp_checkbox.setChecked(include_mcp)
        self._brainstorm_checkbox.setChecked(include_brainstorm)
        self._refresh_submit_enabled()

    def focus_name(self) -> None:
        self._name_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def report_dispatch_result(self, report: DispatchReport) -> None:
        """Host reports terminal/clipboard dispatch outcomes.

        ACCEPTED / PARTIAL close the dialog. FAILED restores controls and
        keeps the modal open for retry.
        """
        if self._state != DialogState.DISPATCHING:
            return

        if report.is_full_success:
            dests = ", ".join(report.accepted) if report.accepted else "destino"
            msg = f"{_MSG_ACCEPTED_PREFIX}{dests}."
            if report.notes_copied:
                notes = ", ".join(report.notes_copied)
                msg += f" Notes copiado: {notes}."
            self._set_feedback(msg, kind="success")
            self._apply_state(DialogState.ACCEPTED)
            self._finish_close()
            return

        if report.is_partial:
            accepted = ", ".join(report.accepted) or "-"
            failed = ", ".join(report.failed) or "-"
            msg = f"{_MSG_PARTIAL_PREFIX}{accepted}. Falhos: {failed}."
            self._set_feedback(msg, kind="warning")
            self._apply_state(DialogState.PARTIAL)
            self._finish_close()
            return

        # Total failure — stay open, restore controls, sanitized error.
        err = report.errors[0] if report.errors else _MSG_FAILED_GENERIC
        self._set_feedback(self._sanitize_error(err), kind="error")
        self._in_flight = False
        self._apply_state(DialogState.FAILED)
        self._restore_controls()
        # FAILED is recoverable: treat as OPEN_IDLE for further edits.
        self._apply_state(DialogState.OPEN_IDLE)

    def report_builder_failure(self, message: str = _MSG_FAILED_GENERIC) -> None:
        """Host reports builder/transport failure before any destination accepted."""
        if self._state != DialogState.DISPATCHING:
            return
        self._set_feedback(self._sanitize_error(message), kind="error")
        self._in_flight = False
        self._apply_state(DialogState.FAILED)
        self._restore_controls()
        self._apply_state(DialogState.OPEN_IDLE)

    # ── UI build ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QWidget()
        header.setObjectName("CreateAgentDialogHeader")
        header.setFixedHeight(52)
        header.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        title = QLabel("Criar agente")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #FAFAFA;")
        hl.addWidget(title)
        hl.addStretch()
        self._window_close_btn = QPushButton("✕")
        self._window_close_btn.setFixedSize(28, 28)
        self._window_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._window_close_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; color: #A1A1AA; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FAFAFA; }"
            "QPushButton:disabled { color: #52525B; }"
        )
        self._window_close_btn.clicked.connect(self._on_cancel)
        hl.addWidget(self._window_close_btn)
        root.addWidget(header)

        # Body
        body = QWidget()
        body.setStyleSheet("background-color: #18181B;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 18, 24, 12)
        bl.setSpacing(12)

        # Name
        self._name_label = QLabel("Nome")
        self._name_label.setStyleSheet(_LABEL_STYLE)
        self._name_input = QLineEdit()
        self._name_input.setProperty("testid", "create-agent-name-input")
        self._name_input.setPlaceholderText("Nome humano do agente")
        self._name_input.setMaxLength(NAME_MAX_CHARS + 32)  # soft cap; hard via validator
        self._name_input.setStyleSheet(_INPUT_STYLE)
        self._name_input.setAccessibleName("Nome do agente")
        self._name_label.setBuddy(self._name_input)
        bl.addWidget(self._name_label)
        bl.addWidget(self._name_input)

        # Description
        self._description_label = QLabel("Descricao")
        self._description_label.setStyleSheet(_LABEL_STYLE)
        self._description_input = QPlainTextEdit()
        self._description_input.setProperty("testid", "create-agent-description-input")
        self._description_input.setPlaceholderText(
            "Proposito e escopo do agente (obrigatorio)"
        )
        self._description_input.setMinimumHeight(120)
        self._description_input.setTabChangesFocus(True)
        self._description_input.setStyleSheet(_INPUT_STYLE)
        self._description_input.setAccessibleName("Descricao do agente")
        self._description_label.setBuddy(self._description_input)
        bl.addWidget(self._description_label)
        bl.addWidget(self._description_input, stretch=1)

        # Optional destinations
        opts = QHBoxLayout()
        opts.setSpacing(16)
        self._mcp_checkbox = QCheckBox("Integrar no setor MCP")
        self._mcp_checkbox.setProperty("testid", "create-agent-target-mcp-checkbox")
        self._mcp_checkbox.setStyleSheet(_CHECK_STYLE)
        self._mcp_checkbox.setAccessibleName("Integrar no setor MCP")
        self._mcp_checkbox.setChecked(False)
        opts.addWidget(self._mcp_checkbox)

        self._brainstorm_checkbox = QCheckBox("Integrar no Brainstorm")
        self._brainstorm_checkbox.setProperty(
            "testid", "create-agent-target-brainstorm-checkbox"
        )
        self._brainstorm_checkbox.setStyleSheet(_CHECK_STYLE)
        self._brainstorm_checkbox.setAccessibleName("Integrar no Brainstorm")
        self._brainstorm_checkbox.setChecked(False)
        opts.addWidget(self._brainstorm_checkbox)
        opts.addStretch()
        bl.addLayout(opts)

        # Validation / progress feedback
        self._error_label = QLabel("")
        self._error_label.setProperty("testid", "create-agent-validation-error")
        self._error_label.setStyleSheet(_ERROR_STYLE)
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        self._error_label.setAccessibleName("Erro de validacao")
        bl.addWidget(self._error_label)

        self._progress_label = QLabel("")
        self._progress_label.setProperty("testid", "create-agent-progress")
        self._progress_label.setStyleSheet(_PROGRESS_STYLE)
        self._progress_label.setWordWrap(True)
        self._progress_label.setVisible(False)
        bl.addWidget(self._progress_label)

        root.addWidget(body, stretch=1)

        # Footer buttons
        footer = QWidget()
        footer.setObjectName("CreateAgentDialogFooter")
        footer.setFixedHeight(56)
        footer.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 0, 24, 0)
        fl.setSpacing(8)
        fl.addStretch()

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("testid", "create-agent-cancel")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.setAutoDefault(False)
        self._cancel_btn.setDefault(False)
        self._cancel_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: none; border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #52525B; }"
            "QPushButton:disabled { color: #71717A; background-color: #27272A; }"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        fl.addWidget(self._cancel_btn)

        self._submit_btn = QPushButton("Criar agente")
        self._submit_btn.setProperty("testid", "create-agent-submit")
        self._submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._submit_btn.setAutoDefault(False)
        self._submit_btn.setDefault(False)
        self._submit_btn.setObjectName("PrimaryButton")
        self._submit_btn.setStyleSheet(
            "QPushButton { background-color: #16A34A; color: #FAFAFA;"
            "  font-weight: 700; border: none; border-radius: 4px; padding: 8px 20px; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._submit_btn.clicked.connect(self._on_submit)
        fl.addWidget(self._submit_btn)

        root.addWidget(footer)

        # QDialogButtonBox not used as container so we keep exact labels/testids;
        # reject() still wired for Escape via keyPressEvent / reject override.

    def _wire_validation(self) -> None:
        self._name_input.textChanged.connect(self._on_fields_changed)
        self._description_input.textChanged.connect(self._on_fields_changed)

    # ── Validation / submit ──────────────────────────────────────────────────

    def _on_fields_changed(self, *_args: object) -> None:
        if self._state == DialogState.DISPATCHING:
            return
        # Clear stale error while typing after INVALID/FAILED.
        if self._state in (DialogState.INVALID, DialogState.OPEN_IDLE, DialogState.FAILED):
            if self._state == DialogState.INVALID:
                # The message explains what is wrong with the input, so it only
                # goes away once both fields look fillable again.
                if (
                    self._name_input.text().strip()
                    and self._description_input.toPlainText().strip()
                ):
                    self._clear_error()
                    self._apply_state(DialogState.OPEN_IDLE)
            elif self._error_label.isVisible():
                # Transport error from a previous FAILED attempt. FAILED is
                # transient and lands back on OPEN_IDLE, so without this the
                # message stayed on screen forever, describing an attempt the
                # operator has already moved past.
                self._clear_error()
        self._refresh_submit_enabled()

    def _refresh_submit_enabled(self) -> None:
        if self._state == DialogState.DISPATCHING or self._in_flight:
            self._submit_btn.setEnabled(False)
            return
        name_ok = bool(self._name_input.text().strip())
        desc_ok = bool(self._description_input.toPlainText().strip())
        self._submit_btn.setEnabled(name_ok and desc_ok)

    def _on_submit(self) -> None:
        if self._in_flight or self._state == DialogState.DISPATCHING:
            return

        name_raw = self._name_input.text()
        desc_raw = self._description_input.toPlainText()
        include_mcp = self._mcp_checkbox.isChecked()
        include_brainstorm = self._brainstorm_checkbox.isChecked()

        # Full validation via pure builder helpers (G5-prompt).
        try:
            name = validate_name(name_raw)
        except CreateAgentPromptError as exc:
            self._enter_invalid(str(exc), focus=self._name_input)
            return

        try:
            description = validate_description(desc_raw)
        except CreateAgentPromptError as exc:
            self._enter_invalid(str(exc), focus=self._description_input)
            return

        try:
            prompt = build_create_agent_prompt(
                name, description, include_mcp, include_brainstorm
            )
        except CreateAgentPromptError as exc:
            focus_widget = (
                self._name_input
                if exc.field == "name"
                else self._description_input
            )
            self._enter_invalid(str(exc), focus=focus_widget)
            return

        request = CreateAgentRequest(
            name=name,
            description=description,
            include_mcp=bool(include_mcp),
            include_brainstorm=bool(include_brainstorm),
            prompt=prompt,
        )
        self._last_request = request
        self._in_flight = True
        self._clear_error()
        self._set_feedback(_MSG_PROGRESS, kind="progress")
        self._apply_state(DialogState.DISPATCHING)
        self._lock_controls()
        self._emitting_submit = True
        try:
            self.submit_requested.emit(request)
        finally:
            self._emitting_submit = False

    def _enter_invalid(self, message: str, *, focus: QWidget) -> None:
        self._set_feedback(self._sanitize_error(message), kind="error")
        self._apply_state(DialogState.INVALID)
        focus.setFocus(Qt.FocusReason.OtherFocusReason)
        self._refresh_submit_enabled()

    def _on_cancel(self) -> None:
        if self._state == DialogState.DISPATCHING or self._in_flight:
            return
        self._apply_state(DialogState.CANCELLED)
        self._last_request = None
        self.reject()

    # ── State / controls ─────────────────────────────────────────────────────

    def _apply_state(self, new_state: DialogState) -> None:
        self._state = new_state
        self._escape_blocked = new_state == DialogState.DISPATCHING
        self.state_changed.emit(new_state.value)

    def _lock_controls(self) -> None:
        self._name_input.setEnabled(False)
        self._description_input.setEnabled(False)
        self._mcp_checkbox.setEnabled(False)
        self._brainstorm_checkbox.setEnabled(False)
        self._submit_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._window_close_btn.setEnabled(False)
        self.setCursor(Qt.CursorShape.BusyCursor)

    def _restore_controls(self) -> None:
        self._name_input.setEnabled(True)
        self._description_input.setEnabled(True)
        self._mcp_checkbox.setEnabled(True)
        self._brainstorm_checkbox.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        self._window_close_btn.setEnabled(True)
        self.unsetCursor()
        self._progress_label.setVisible(False)
        self._progress_label.clear()
        self._refresh_submit_enabled()

    def _finish_close(self) -> None:
        self._in_flight = False
        self.accept()

    # ── Teardown ─────────────────────────────────────────────────────────────

    def done(self, result: int) -> None:  # noqa: D102 - Qt override
        # Single close funnel: accept(), reject() and closeEvent() all land here.
        super().done(result)
        self._teardown()

    def _teardown(self) -> None:
        """Clear operator data, prompt and connections once the modal closes.

        Idempotent. Runs on ACCEPTED, PARTIAL and CANCELLED — never on FAILED,
        because a total failure keeps the modal open for retry with the fields
        intact. The sanitized ``last_feedback`` survives so the host can report
        the outcome after the widget is gone.
        """
        if self._torn_down:
            return
        self._torn_down = True
        self._in_flight = False
        self._escape_blocked = False

        # Drop the prompt/request snapshot first: it carries the full payload.
        self._last_request = None

        # Wipe the fields without re-entering validation (widgets may already
        # be scheduled for deletion by WA_DeleteOnClose).
        for widget in (self._name_input, self._description_input):
            try:
                blocked = widget.signalsBlocked()
                widget.blockSignals(True)
                widget.clear()
                widget.blockSignals(blocked)
            except RuntimeError:  # pragma: no cover - C++ side already gone
                pass
        for check in (self._mcp_checkbox, self._brainstorm_checkbox):
            try:
                blocked = check.signalsBlocked()
                check.blockSignals(True)
                check.setChecked(False)
                check.blockSignals(blocked)
            except RuntimeError:  # pragma: no cover
                pass

        # Release host connections so a stale instance can never publish again.
        # While ``submit_requested`` is still being emitted (ACCEPTED/PARTIAL
        # close synchronously from the host slot), cutting the connections now
        # would silence the remaining slots of that same emission — defer.
        if self._emitting_submit:
            # `self` as context: Qt drops the call if the dialog dies first
            # (WA_DeleteOnClose).
            QTimer.singleShot(0, self, self._disconnect_public_signals)
        else:
            self._disconnect_public_signals()

    def _disconnect_public_signals(self) -> None:
        try:
            signals = (self.submit_requested, self.state_changed)
        except RuntimeError:  # pragma: no cover - C++ side already gone
            return
        for signal in signals:
            try:
                if not self.isSignalConnected(QMetaMethod.fromSignal(signal)):
                    continue
                signal.disconnect()
            except (RuntimeError, TypeError):  # pragma: no cover - already gone
                pass

    # ── Feedback ─────────────────────────────────────────────────────────────

    def _set_feedback(self, message: str, *, kind: str) -> None:
        safe = self._sanitize_error(message)
        # Hard invariant: never claim the agent was created. Case-insensitive
        # on BOTH sides — a mixed-case variant ("AGENTE CRIADO", "Agente Criado")
        # used to pass the guard and reach the label untouched. Invisible
        # codepoints are dropped first: a zero-width character between the
        # words used to split the phrase for the regex while still reading as
        # the claim on screen.
        safe = _FORBIDDEN_SUCCESS_RE.sub(_rewrite_forbidden_phrase, _strip_invisible(safe))
        self._last_feedback = safe
        if kind == "progress":
            self._error_label.setVisible(False)
            self._error_label.clear()
            self._progress_label.setText(safe)
            self._progress_label.setVisible(True)
        elif kind in ("error", "warning"):
            self._progress_label.setVisible(False)
            self._progress_label.clear()
            self._error_label.setText(safe)
            self._error_label.setVisible(True)
            self._error_label.setStyleSheet(
                _ERROR_STYLE
                if kind == "error"
                else "color: #FBBF24; font-size: 12px; background: transparent; padding: 2px 0;"
            )
            self.setAccessibleDescription(safe)
        else:  # success (brief, then close)
            self._progress_label.setText(safe)
            self._progress_label.setVisible(True)
            self._error_label.setVisible(False)

    def _clear_error(self) -> None:
        self._error_label.clear()
        self._error_label.setVisible(False)
        self.setAccessibleDescription("")

    @staticmethod
    def _sanitize_error(message: str) -> str:
        """Keep feedback free of exception repr / prompt body / secrets.

        Order is load-bearing:
        1. drop everything after the first line (kills multi-line dumps);
        2. bail out on traceback markers;
        3. drop anything that looks like the prompt envelope — a host error
           that echoes the payload must never repaint it on screen;
        4. redact high-confidence secrets BEFORE truncating, so a token cut
           in half by the 200-char cap cannot survive as a partial value;
        5. truncate last.
        """
        text = (message or "").strip()
        if not text:
            return _MSG_FAILED_GENERIC
        # Never echo multi-line exception dumps.
        first_line = text.splitlines()[0].strip()
        if first_line.startswith("Traceback") or "File \"" in first_line:
            return _MSG_FAILED_GENERIC
        # Never echo the prompt envelope or its JSON payload back to the UI.
        if _PROMPT_ECHO_RE.search(first_line):
            return _MSG_FAILED_GENERIC
        first_line = redact_secrets(first_line)
        if len(first_line) > 200:
            first_line = first_line[:197] + "..."
        return first_line

    # ── Keyboard / close guards ──────────────────────────────────────────────

    def reject(self) -> None:
        if self._state == DialogState.DISPATCHING or self._in_flight:
            return
        if self._state != DialogState.CANCELLED:
            self._apply_state(DialogState.CANCELLED)
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._state == DialogState.DISPATCHING or self._in_flight:
            event.ignore()
            return
        if self._state not in (
            DialogState.ACCEPTED,
            DialogState.PARTIAL,
            DialogState.CANCELLED,
        ):
            self._apply_state(DialogState.CANCELLED)
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            if self._escape_blocked or self._in_flight:
                event.ignore()
                return
            self._on_cancel()
            event.accept()
            return
        # Enter in QPlainTextEdit inserts newline (default). Do not accept dialog
        # on Enter from description; autoDefault is already False on buttons.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focus = self.focusWidget()
            if focus is self._description_input:
                # Let QPlainTextEdit handle newline; never submit.
                super().keyPressEvent(event)
                return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # Initial focus on name (contract 10.3).
        self.focus_name()


__all__ = [
    "CreateAgentDialog",
    "CreateAgentRequest",
    "DialogState",
    "DispatchReport",
    "DESCRIPTION_MAX_CHARS",
    "NAME_MAX_CHARS",
]
