"""
MCPPromptButton — Botao canonico para disparo de prompts MCP.

Aceita button_type Claude/Codex/Kimi (legacy) + type-selector-radio-input
(seed-driven brainstorm; T2 loop 05-21-implantation-tasklist-aba-brainstorm).
Aceita action legacy send/queue/config + 7 literals pt-BR canonicos.

Uso seed-driven (brainstorm grade):
    btn = MCPPromptButton(
        label="Criar md",
        button_type="Claude",
        prompt=Path("blacksmith/brainstorm-mcp/01-criar-md.md"),
        agent_name="estruturador de ideias",
        agent_path="ai-forge/MCP/agents/criar-md-rules.md",
        action="Criar arquivo",
        target_path="terminal-interactive-output",
        testid_slug="criar-md",
    )

Comportamento:
- Left-click: emite `prompt_requested(dict)` com label/type/prompt/action/target_path/agent.
- Right-click: abre `MCPPromptConfigModal` (edicao inline da config).
- Cor de fundo varia por type dentro da identidade Graphite/Amber do app
  (tons escuros/saturados, nunca pastel).
- Validacao no __init__: type="Codex" exige target_path="terminal-codex-output".
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Literal
from weakref import WeakMethod

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

from workflow_app.signal_bus import signal_bus

logger = logging.getLogger(__name__)

ButtonType = Literal["Claude", "Codex", "Kimi", "type-selector-radio-input"]
ActionType = Literal[
    "send",
    "queue",
    "config",
    "Criar arquivo",
    "Otimizar",
    "Criar tasks",
    "Revisar tasks",
    "Revisar",
    "Executar",
    "Revisar execucao",
    "Loop prepare",
]

# Catalogos canonicos compartilhados (widget + loader em main_window).
VALID_BUTTON_TYPES: set[str] = {
    "Claude",
    "Codex",
    "Kimi",
    "type-selector-radio-input",
}
VALID_ACTIONS_LEGACY: set[str] = {"send", "queue", "config"}
VALID_ACTIONS_PTBR: set[str] = {
    "Criar arquivo",
    "Otimizar",
    "Criar tasks",
    "Revisar tasks",
    "Revisar",
    "Executar",
    "Revisar execucao",
    "Loop prepare",
    "Analisar complexidade",
}
VALID_ACTIONS: set[str] = VALID_ACTIONS_LEGACY | VALID_ACTIONS_PTBR

VALID_TERMINALS: set[str] = {
    "terminal-interactive-output",
    "terminal-workspace-output",
    "terminal-codex-output",
}
# Alias publico para compat com leitores externos do widget.
_VALID_TARGETS: set[str] = VALID_TERMINALS

# Cores canonicas conforme mcp-flow-implantation-base-archive.md §4:
# Claude=laranja, Codex=roxo, Kimi=azul, type-selector-radio-input=verde.
# Fix T021 loop 05-21-implantation-tasklist-aba-brainstorm.
_TYPE_BG: dict[str, str] = {
    "Claude": "#C2410C",  # laranja escuro (Tailwind orange-700)
    "Codex":  "#6D28D9",  # roxo (Tailwind violet-700)
    "Kimi":   "#1D4ED8",  # azul (Tailwind blue-700)
    "type-selector-radio-input": "#15803D",  # verde (Tailwind green-700)
}
_TYPE_FG: dict[str, str] = {
    "Claude": "#FAFAFA",
    "Codex":  "#FAFAFA",
    "Kimi":   "#FAFAFA",
    "type-selector-radio-input": "#FAFAFA",
}
_TYPE_BORDER: dict[str, str] = {
    "Claude": "#EA580C",  # orange-600
    "Codex":  "#7C3AED",  # violet-600
    "Kimi":   "#2563EB",  # blue-600
    "type-selector-radio-input": "#16A34A",  # green-600
}

# Hardening T7 (loop 05-21-implantation-tasklist-aba-brainstorm).
# Debounce per-botao em nanossegundos (monotonic_ns evita regressao de wall-clock).
# Aplicado APENAS as actions guarded — clique fora dessas dispara direto.
_DEBOUNCE_NS = 800_000_000  # 800 ms
_GUARDED_ACTIONS: frozenset[str] = frozenset({"Executar", "Revisar execucao"})

# Gate T7 (task-008 loop 05-21-implantation-tasklist-aba-brainstorm).
# Testid canonico do terminal Codex (T3). Quando ausente da arvore Qt, botoes
# Codex (fixos OU radio-driven com radio=Codex) NAO publicam: fixos ficam
# disabled, radio-driven bloqueiam no clique. Sem fallback silencioso para
# Claude/Kimi (§6.3:669 + §10.5:7 do mcp-flow-implantation.md).
_CODEX_TARGET_TESTID = "terminal-codex-output"
_CODEX_TOAST_CANONICAL = (
    "Codex indisponivel: terminal T3 (testid: terminal-codex-output) "
    "nao encontrado no workflow-app. Publicacao bloqueada para preservar "
    "auditoria de provider. Nao havera fallback automatico para Claude/Kimi."
)
_CODEX_TOAST_SHORT = "Codex bloqueado: T3 ausente."

# Estado checkbox/debounce e per-widget-instance; rebuild da grade (T4) ou
# restart do QApplication resetam tudo — alinhado a "sem memoria, nao persiste
# apos restart" (base-archive 230-236).


def _ellipsize_middle(text: str, max_len: int = 80) -> str:
    """Encurta `text` para `max_len` chars preservando inicio e fim com '...' no meio."""
    if len(text) <= max_len:
        return text
    keep = (max_len - 3) // 2
    return f"{text[:keep]}...{text[-keep:]}"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lighten(hex_color: str, factor: float) -> str:
    """Clareia `hex_color` por `factor` (0..1)."""
    r, g, b = _hex_to_rgb(hex_color)
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))
    return f"#{r:02X}{g:02X}{b:02X}"


def _darken(hex_color: str, factor: float) -> str:
    """Escurece `hex_color` por `factor` (0..1)."""
    r, g, b = _hex_to_rgb(hex_color)
    r = max(0, int(r * (1.0 - factor)))
    g = max(0, int(g * (1.0 - factor)))
    b = max(0, int(b * (1.0 - factor)))
    return f"#{r:02X}{g:02X}{b:02X}"


class _InlineCheckBox(QCheckBox):
    """QCheckBox embutido em QPushButton com stop propagation forte.

    `event.accept()` em mousePress/Release/keyPress IMPEDE o evento de subir
    para o QPushButton pai — clique direto no checkbox NUNCA dispara o
    handler do botao. `NoFocus` evita roubar tab order/Space do botao pai
    (assim Space ativa o botao mesmo com checkbox interno).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setText("")  # sem label proprio (spec base-archive 230-236)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Indicador compacto para caber no botao 22px (default ~16px).
        self.setStyleSheet(
            "QCheckBox { background: transparent; border: none; padding: 0; }"
            "QCheckBox::indicator { width: 12px; height: 12px; }"
            "QCheckBox::indicator:unchecked { background-color: #18181B;"
            "  border: 1px solid #52525B; border-radius: 3px; }"
            "QCheckBox::indicator:checked { background-color: #FBBF24;"
            "  border: 1px solid #FBBF24; border-radius: 3px; }"
            "QCheckBox::indicator:hover { border-color: #FDE68A; }"
        )

    def mousePressEvent(self, event):  # noqa: N802
        event.accept()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        event.accept()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        event.accept()
        super().keyPressEvent(event)


class MCPPromptConfigModal(QDialog):
    """Modal de edicao da config do botao MCP (right-click)."""

    def __init__(
        self,
        parent: QPushButton | None = None,
        *,
        label: str = "",
        prompt: str = "",
        agent_name: str | None = None,
        agent_path: str | None = None,
        target_path: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurar MCP Prompt Button")
        self.setProperty("testid", "mcp-prompt-config-modal")

        form = QFormLayout(self)
        self._label_edit = QLineEdit(label, self)
        self._prompt_edit = QPlainTextEdit(prompt, self)
        self._prompt_edit.setMinimumHeight(120)
        self._agent_name_edit = QLineEdit(agent_name or "", self)
        self._agent_path_edit = QLineEdit(agent_path or "", self)
        self._target_edit = QLineEdit(target_path or "", self)

        form.addRow("Label:", self._label_edit)
        form.addRow("Prompt:", self._prompt_edit)
        form.addRow("Agent name:", self._agent_name_edit)
        form.addRow("Agent path:", self._agent_path_edit)
        form.addRow("Target terminal:", self._target_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict[str, str]:
        return {
            "label": self._label_edit.text(),
            "prompt": self._prompt_edit.toPlainText(),
            "agent_name": self._agent_name_edit.text() or "",
            "agent_path": self._agent_path_edit.text() or "",
            "target_path": self._target_edit.text() or "",
        }


class MCPPromptButton(QPushButton):
    """Botao canonico para disparo de prompts MCP.

    Hardening T7 (loop 05-21-implantation-tasklist-aba-brainstorm):
    - Checkbox embutido `_InlineCheckBox` a esquerda do label (sem label
      proprio, stop propagation, NoFocus).
    - Debounce 800ms per-botao via `time.monotonic_ns()` para actions em
      `_GUARDED_ACTIONS` ({Executar, Revisar execucao}).
    - Confirmacao `QMessageBox.question` no re-clique quando checkbox ja
      marcado.
    - Estado (checkbox/debounce) e per-widget-instance; rebuild da grade
      via `_brainstorm_grid_invalidated` OU restart do QApplication
      resetam tudo (sem memoria, nao persiste apos restart).
    - Checkbox marca APENAS via `mark_dispatch_result(True)` disparado por
      `signal_bus.dispatch_result` apos sucesso real do disparo no
      terminal. Falha desmarca e zera debounce (libera retry imediato).
    """

    prompt_requested = Signal(dict)

    def __init__(
        self,
        label: str,
        button_type: ButtonType,
        prompt: str | Path,
        agent_name: str | None = None,
        agent_path: str | None = None,
        action: ActionType = "send",
        target_path: str | None = None,
        *,
        testid_slug: str | None = None,
        target_path_edit_inplace: bool = False,
        radio_state_getter: Callable[[], str] | None = None,
        parent=None,
    ) -> None:
        # Texto vazio no QPushButton — label visivel vai como QLabel filho
        # (necessario para conviver com QHBoxLayout interno; Qt sobrepoe texto
        # nativo com widgets filhos).
        super().__init__("", parent)

        # Validacao
        if button_type not in VALID_BUTTON_TYPES:
            raise ValueError(
                f"button_type invalido: {button_type!r} "
                f"(esperado: {sorted(VALID_BUTTON_TYPES)})"
            )
        if action not in VALID_ACTIONS:
            raise ValueError(
                f"action invalida: {action!r} (esperado: {sorted(VALID_ACTIONS)})"
            )
        if target_path is not None and target_path not in VALID_TERMINALS:
            raise ValueError(
                f"target_path invalido: {target_path!r}. "
                f"Esperado: {sorted(VALID_TERMINALS)}"
            )
        if button_type == "Codex" and target_path != "terminal-codex-output":
            raise ValueError(
                "button_type='Codex' exige target_path='terminal-codex-output' "
                f"(recebido: {target_path!r})"
            )

        self._label = label
        self._button_type: ButtonType = button_type
        self._prompt: str | Path = prompt
        self._agent_name = agent_name
        self._agent_path = agent_path
        self._action: ActionType = action
        self._target_path = target_path
        self._testid_slug = testid_slug
        self._target_path_edit_inplace = bool(target_path_edit_inplace)

        # Hardening T7: estado intra-sessao (per-widget-instance; rebuild da
        # grade ou restart do QApplication reseta tudo - aceitavel).
        self._checkbox_state: bool = False
        self._last_dispatch_ns: int = 0

        # Gate T7 (task-008): cache de disponibilidade do terminal Codex.
        # `None` = ainda nao avaliado (avalia preguicosamente no primeiro
        # uso). Invalidado por `signal_bus.codex_availability_changed` ou
        # `recheck_codex_availability()`.
        self._codex_alive_cache: bool | None = None
        # Marca pedido de recheck quando o widget ainda nao tem parent
        # (self.window() retorna None no __init__). showEvent consome.
        self._recheck_pending: bool = False

        # Radio state getter (T7): callable opcional que retorna o provider
        # ativo ("Claude"/"Kimi"/"Codex") quando button_type=
        # type-selector-radio-input. Armazenado como WeakMethod quando e
        # bound method (evita ciclo MainWindow <-> button). Fallback direto
        # quando e funcao livre ou lambda (impossivel weakref).
        self._radio_state_getter_ref: WeakMethod | Callable[[], str] | None
        if radio_state_getter is None:
            self._radio_state_getter_ref = None
        else:
            try:
                self._radio_state_getter_ref = WeakMethod(radio_state_getter)
            except TypeError:
                # Funcao livre/lambda: armazena diretamente (sem weakref).
                self._radio_state_getter_ref = radio_state_getter

        # button_id estavel para filtrar signal_bus.dispatch_result. Quando
        # testid_slug ausente, deriva de id(self) para nao colidir entre
        # instancias anonimas.
        slug_fallback = testid_slug or f"anon-{button_type.lower()}-{id(self):x}"
        self._button_id = f"mcp-prompt-btn-{slug_fallback}"
        self.setObjectName(self._button_id)
        self.setProperty("testid", self._button_id)
        self.setAccessibleName(f"{label} - botao MCP")

        # Checkbox embutido + label como child widget. Layout horizontal
        # gerencia spacing; label transparente para mouse propaga clique no
        # texto ao QPushButton pai.
        self._checkbox = _InlineCheckBox(self)
        self._checkbox.setObjectName(f"{self._button_id}-checkbox")
        self._checkbox.setProperty("testid", f"{self._button_id}-checkbox")
        self._checkbox.setAccessibleName("Marcar disparo concluido")
        self._checkbox.setToolTip("Marcado apos disparo bem-sucedido")

        self._label_widget = QLabel(label, self)
        self._label_widget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._label_widget.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 8, 0)
        row.setSpacing(4)
        row.addWidget(self._checkbox, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._label_widget, 1, Qt.AlignmentFlag.AlignVCenter)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_visual_state()

        # Tooltip: primeiras 80 chars do prompt
        prompt_preview = self._resolve_prompt_text()[:80]
        self.setToolTip(
            f"[{button_type}] {label}\n"
            f"action={action} target={target_path or '-'}\n"
            f"prompt: {prompt_preview}{'...' if len(self._resolve_prompt_text()) > 80 else ''}"
        )

        self.clicked.connect(self._on_clicked)
        # Filtra dispatch_result por button_id em _on_dispatch_result.
        signal_bus.dispatch_result.connect(self._on_dispatch_result)
        # Auto-cura: cache invalidado quando T3 muda em runtime.
        signal_bus.codex_availability_changed.connect(
            self._on_codex_availability_changed
        )
        # Event filter captura clique mesmo em estado disabled para feedback
        # canonico (QPushButton.disabled ignora cliques nativamente).
        self.installEventFilter(self)

        # Aplica setEnabled inicial para button_type=Codex fixo: se T3 nao
        # estiver visivel, botao nasce disabled com tooltip da variante curta.
        # Em button_type=type-selector-radio-input o botao SEMPRE nasce
        # habilitado (radio pode mover para Claude/Kimi) e o gate roda no
        # clique.
        if self._button_type == "Codex":
            alive = self._is_codex_alive_cached()
            super().setEnabled(alive)
            self._sync_visual_state()
            if not alive:
                self.setToolTip(_CODEX_TOAST_SHORT)

    # API

    def payload(self) -> dict:
        """Payload canonico emitido em `prompt_requested`.

        `button_id` propaga o objectName para que o handler externo
        possa direcionar `signal_bus.dispatch_result` ao widget de origem.
        """
        return {
            "label": self._label,
            "button_type": self._button_type,
            "prompt": str(self._prompt),
            "prompt_text": self._resolve_prompt_text(),
            "agent_name": self._agent_name,
            "agent_path": self._agent_path,
            "action": self._action,
            "target_path": self._target_path,
            "target_path_edit_inplace": self._target_path_edit_inplace,
            "testid_slug": self._testid_slug,
            "button_id": self._button_id,
        }

    def mark_dispatch_result(self, success: bool) -> None:
        """Atualiza estado do checkbox conforme resultado real do disparo.

        Sucesso: marca checkbox + atualiza last_dispatch_ns (debounce ativo).
        Falha: desmarca checkbox + zera last_dispatch_ns (libera retry imediato).
        Spec: §7.3 mcp-flow-implantation.md (falha NAO marca como sucesso).
        """
        if success:
            self._checkbox_state = True
            with QSignalBlocker(self._checkbox):
                self._checkbox.setChecked(True)
            self._last_dispatch_ns = time.monotonic_ns()
        else:
            self._checkbox_state = False
            with QSignalBlocker(self._checkbox):
                self._checkbox.setChecked(False)
            self._last_dispatch_ns = 0
        self._sync_visual_state()

    # Helpers

    def _resolve_prompt_text(self) -> str:
        """Le prompt se for Path .md, senao retorna a string literal."""
        if isinstance(self._prompt, Path):
            try:
                return self._prompt.read_text(encoding="utf-8")
            except OSError:
                return f"[erro lendo {self._prompt}]"
        return str(self._prompt)

    def _is_debounced(self) -> bool:
        """True quando clique cai dentro da janela de debounce per-botao.

        Aplica APENAS para actions em `_GUARDED_ACTIONS`. Cliques bloqueados
        sao IGNORADOS (nao enfileirados). Per-botao explicito - debounce de
        outros widgets nao afeta este.
        """
        if self._action not in _GUARDED_ACTIONS:
            return False
        now = time.monotonic_ns()
        if self._last_dispatch_ns and (now - self._last_dispatch_ns) < _DEBOUNCE_NS:
            logger.debug(
                "MCPPromptButton debounce ignored: action=%s button_id=%s",
                self._action,
                self._button_id,
            )
            return True
        return False

    def _needs_confirmation(self) -> bool:
        """True quando re-clique de action guarded com checkbox ja marcado."""
        return self._action in _GUARDED_ACTIONS and self._checkbox_state

    def _confirm_redispatch(self, md_path: str | None) -> bool:
        """Modal de confirmacao com texto literal da spec.

        Parent `self.window()` (top-level) evita dangling pointer caso a
        grade seja reconstruida (`_brainstorm_grid_invalidated`) durante o
        dialogo. Default `No` previne click-through. `target-path`
        ellipsizado para max 80 chars.
        """
        if not self._needs_confirmation():
            return True
        target = _ellipsize_middle(str(md_path or ""))
        parent_win = self.window() if self.window() is not None else self
        reply = QMessageBox.question(
            parent_win,
            "Confirmar",
            f"Disparar novamente em {target}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_dispatch_result(self, button_id: str, success: bool) -> None:
        """Slot filtrado por button_id; ignora resultados de outros botoes."""
        if button_id == self._button_id:
            self.mark_dispatch_result(success)

    # Gate T7 (task-008 loop 05-21-implantation-tasklist-aba-brainstorm)

    def _codex_target_alive(self) -> bool:
        """T3 funcional = widget com testid `terminal-codex-output`
        presente, valido (shiboken), aceito por duck-type (QPlainTextEdit
        /QTextEdit legacy OU XtermOutputPanel via `_shell.send_raw`) e
        visivel para a janela raiz.

        Definicao operacional endurecida (§T7 task-008 +
        analise-de-destino-T7 Bloco 4 + BLOCKER 2-bis 2026-05-22 do loop
        05-21-implantation-tasklist-aba-brainstorm): NAO basta
        property("testid") bater - placeholder QLabel com testid correto
        enganaria o gate. O widget precisa ser:

        - instancia de QPlainTextEdit/QTextEdit (terminais legacy pyte), OU
        - duck-type xterm: ter atributo `_shell` com metodo `send_raw`
          callable (XtermOutputPanel canonico, QWebEngineView-backed).

        Sem o caminho xterm, o T3 real (XtermOutputPanel) seria rejeitado
        aqui mesmo o testid casando, e o radio Codex habilitaria pela
        janela (`_codex_terminal_available` em main_window.py:1985-1987 ja
        aceita qualquer QWidget) enquanto o clique do botao bloqueava -
        inconsistencia que defeitava o fix BLOCKER 2 do T020.

        `shiboken6.isValid` evita dangling pointer pos-deleteLater. Retorna
        False quando o widget ainda nao tem parent (self.window() is None).
        """
        try:
            import shiboken6  # type: ignore[import-untyped]
        except ImportError:
            shiboken6 = None

        root = self.window()
        if root is None:
            return False
        for w in root.findChildren(QObject):
            testid = str(w.property("testid") or "")
            if testid != _CODEX_TARGET_TESTID:
                continue
            if shiboken6 is not None and not shiboken6.isValid(w):
                continue
            is_legacy_edit = isinstance(w, (QPlainTextEdit, QTextEdit))
            shell = getattr(w, "_shell", None)
            is_xterm_duck = shell is not None and callable(getattr(shell, "send_raw", None))
            if not (is_legacy_edit or is_xterm_duck):
                continue
            if not isinstance(w, QWidget) or not w.isVisibleTo(root):
                continue
            return True
        return False

    def _is_codex_alive_cached(self) -> bool:
        """Le cache; popula com `_codex_target_alive` na primeira chamada.

        Cache evita O(N) `findChildren` a cada clique em botao radio-Codex.
        Invalidado por `signal_bus.codex_availability_changed` (auto-cura
        ativa) ou `recheck_codex_availability()` (sondagem defensiva).
        """
        if self._codex_alive_cache is None:
            self._codex_alive_cache = self._codex_target_alive()
        return self._codex_alive_cache

    def recheck_codex_availability(self) -> None:
        """Forca recheck de T3 e emite signal global.

        Antes de o widget ter parent (`self.window() is None`), marca
        pendente e replaya no proximo showEvent. Idempotente: emite signal
        sempre que avalia, deixando demais consumidores reagirem.
        """
        if self.window() is None or self.parentWidget() is None:
            self._recheck_pending = True
            return
        alive = self._codex_target_alive()
        self._codex_alive_cache = alive
        if self._button_type == "Codex":
            super().setEnabled(alive)
            self._sync_visual_state()
            if alive:
                # Restaura tooltip canonico de preview (sobrescreve o short).
                prompt_preview = self._resolve_prompt_text()[:80]
                self.setToolTip(
                    f"[{self._button_type}] {self._label}\n"
                    f"action={self._action} target={self._target_path or '-'}\n"
                    f"prompt: {prompt_preview}"
                    f"{'...' if len(self._resolve_prompt_text()) > 80 else ''}"
                )
            else:
                self.setToolTip(_CODEX_TOAST_SHORT)
        signal_bus.codex_availability_changed.emit(alive)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._recheck_pending:
            self._recheck_pending = False
            self.recheck_codex_availability()

    def _on_codex_availability_changed(self, alive: bool) -> None:
        """Reage ao signal global: atualiza cache e re-aplica setEnabled.

        Para `button_type=Codex` fixo, ativa/desativa o botao conforme
        novo estado. Para `button_type=type-selector-radio-input`, apenas
        atualiza o cache (gate no clique consome o valor novo).
        """
        self._codex_alive_cache = alive
        if self._button_type == "Codex":
            super().setEnabled(alive)
            self._sync_visual_state()
            if alive:
                prompt_preview = self._resolve_prompt_text()[:80]
                self.setToolTip(
                    f"[{self._button_type}] {self._label}\n"
                    f"action={self._action} target={self._target_path or '-'}\n"
                    f"prompt: {prompt_preview}"
                    f"{'...' if len(self._resolve_prompt_text()) > 80 else ''}"
                )
            else:
                self.setToolTip(_CODEX_TOAST_SHORT)

    def _resolve_provider(self) -> str:
        """Snapshot atomico do provider efetivo no inicio do slot.

        Resolve UMA vez por clique: evita race radio-toggled vs button-
        clicked na fila de eventos Qt (sem garantia de ordem). Fixo:
        retorna button_type direto. Radio: chama o getter (resolve
        WeakMethod) ou default "Claude" quando getter ausente/invalido.
        """
        if self._button_type in ("Claude", "Kimi", "Codex"):
            return self._button_type
        if self._button_type == "type-selector-radio-input":
            ref = self._radio_state_getter_ref
            fn: Callable[[], str] | None
            if isinstance(ref, WeakMethod):
                fn = ref()  # resolve weak ref (None se ja coletado)
            else:
                fn = ref  # funcao livre/lambda guardada direta
            if fn is None:
                return "Claude"
            try:
                value = fn()
            except Exception:  # noqa: BLE001 - getter falho cai no default seguro
                return "Claude"
            value_norm = str(value or "").strip().capitalize()
            if value_norm in ("Claude", "Kimi", "Codex"):
                return value_norm
            return "Claude"
        return "Claude"

    def _block_codex_unavailable(self, reason: str = "t3_missing") -> str:
        """Emite toast canonico + telemetria forense (sem PII).

        Texto literal canonico (NAO encurtar - auditoria depende dele).
        Telemetria inclui button_id, slug e ts; nunca prompt/agent_path/
        target_path.
        """
        signal_bus.toast_requested.emit(_CODEX_TOAST_CANONICAL, "warning")
        seed_slug = ""
        if isinstance(self._prompt, Path):
            seed_slug = self._prompt.stem
        elif self._testid_slug:
            seed_slug = self._testid_slug
        logger.warning(
            "codex_blocked",
            extra={
                "button_id": self._button_id,
                "seed_slug": seed_slug,
                "provider": "Codex",
                "reason": reason,
                "ts_ns": time.time_ns(),
            },
        )
        return _CODEX_TOAST_CANONICAL

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """Feedback no clique em Codex disabled (QPushButton ignora nativamente).

        Captura MouseButtonPress no proprio botao quando disabled e dispara
        a variante curta do toast - usuario que clica num botao cinza recebe
        sinal explicito alem do tooltip estatico.
        """
        if (
            obj is self
            and not self.isEnabled()
            and event.type() == QEvent.Type.MouseButtonPress
            and self._button_type == "Codex"
        ):
            signal_bus.toast_requested.emit(_CODEX_TOAST_SHORT, "warning")
            return True
        return super().eventFilter(obj, event)

    def _sync_visual_state(self) -> None:
        """Aplica stylesheet conforme checkbox state.

        Checked -> cinza (#A1A1AA / fg escuro); unchecked -> cor de
        `button_type`. Hover/pressed/disabled derivados do bg corrente
        para evitar conflito cromatico quando checked.
        """
        if not self.isEnabled():
            bg = "#27272A"
            fg = "#71717A"
            border = "#3F3F46"
        elif self._checkbox_state:
            bg = "#27272A"
            fg = "#A1A1AA"
            border = "#52525B"
        else:
            bg = _TYPE_BG[self._button_type]
            fg = _TYPE_FG[self._button_type]
            border = _TYPE_BORDER[self._button_type]
        hover_bg = _lighten(bg, 0.1)
        pressed_bg = _darken(bg, 0.1)
        self.setStyleSheet(
            f"QPushButton {{ background-color: {bg}; color: {fg};"
            f"  border: 1px solid {border}; border-radius: 5px;"
            "  font-weight: 700; }"
            f"QPushButton:hover {{ background-color: {hover_bg}; border-color: #71717A; }}"
            f"QPushButton:pressed {{ background-color: {pressed_bg}; color: {fg}; }}"
            "QPushButton:disabled { background-color: #27272A; color: #71717A;"
            "  border-color: #3F3F46; }"
        )
        if getattr(self, "_label_widget", None) is not None:
            self._label_widget.setStyleSheet(
                f"color: {fg}; font-size: 10px; font-weight: 600; background: transparent;"
            )

    def _set_label_text(self, text: str) -> None:
        """Atualiza label visivel (QLabel filho) sem tocar texto nativo do QPushButton."""
        self._label = text
        if getattr(self, "_label_widget", None) is not None:
            self._label_widget.setText(text)

    def _on_clicked(self) -> None:
        """Ordem canonica: T7 (Codex gate) -> debounce -> confirmacao
        -> update ts -> emit.

        T7 antecede T6 (debounce/confirmacao): nao faz sentido gastar
        janela de debounce em provider invalido, e re-clique em radio-
        Codex sem T3 nao deve disparar a confirmacao "Disparar
        novamente?" porque NAO houve disparo previo bem-sucedido (o gate
        antecede toda a cadeia).

        O checkbox NAO e marcado aqui — apenas via `mark_dispatch_result`
        disparado externamente por `signal_bus.dispatch_result` apos o
        resultado real do disparo (spec §7.3 + base-archive 230-236).
        Bloqueio por debounce/confirmacao NAO atualiza ts nem checkbox.
        """
        # Gate T7 (Codex availability) — snapshot atomico do provider.
        # Regra de fallback (2026-05-23): para botoes
        # type-selector-radio-input, NAO bloquear quando Codex/T3 estiver
        # indisponivel. O roteamento central em MainWindow faz fallback
        # automatico T3->T2. Mantemos bloqueio apenas para button_type
        # fixo "Codex".
        provider = self._resolve_provider()
        if (
            provider == "Codex"
            and self._button_type == "Codex"
            and not self._is_codex_alive_cached()
        ):
            self._block_codex_unavailable(reason="t3_missing")
            return
        # Gate T6: debounce
        if self._is_debounced():
            return
        # Gate T6: confirmacao re-clique
        md_path = getattr(self.window(), "_brainstorm_md_path", None)
        if not self._confirm_redispatch(md_path):
            return
        # atomic-ish: janela de debounce comeca aqui, antes do emit, para
        # fechar re-entrancia caso slots conectados a prompt_requested
        # disparem _on_clicked de novo no mesmo callstack.
        self._last_dispatch_ns = time.monotonic_ns()
        self.prompt_requested.emit(self.payload())

    # Right-click → modal

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        modal = MCPPromptConfigModal(
            parent=self,
            label=self._label,
            prompt=self._resolve_prompt_text(),
            agent_name=self._agent_name,
            agent_path=self._agent_path,
            target_path=self._target_path,
        )
        self._last_modal = modal  # mantem ref para inspecao em testes
        if modal.exec() == QDialog.DialogCode.Accepted:
            values = modal.values()
            new_label = values["label"] or self._label
            self._set_label_text(new_label)
            self._prompt = values["prompt"]
            self._agent_name = values["agent_name"] or None
            self._agent_path = values["agent_path"] or None
            new_target = values["target_path"] or None
            if new_target and new_target in VALID_TERMINALS:
                if self._button_type == "Codex" and new_target != "terminal-codex-output":
                    # mantem o atual; nao quebra o widget
                    pass
                else:
                    self._target_path = new_target
        event.accept()


# Standalone test runner

if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

    app = QApplication(sys.argv)
    root = QWidget()
    root.setWindowTitle("MCPPromptButton — standalone preview")
    layout = QHBoxLayout(root)

    b1 = MCPPromptButton(
        label="Claude · Criar arquivo",
        button_type="Claude",
        prompt="Resuma o diff atual em 3 bullets.",
        action="Criar arquivo",
        target_path="terminal-interactive-output",
    )
    b2 = MCPPromptButton(
        label="Codex · Otimizar",
        button_type="Codex",
        prompt="Adversarial review da PR atual.",
        action="Otimizar",
        target_path="terminal-codex-output",
    )
    b3 = MCPPromptButton(
        label="Kimi · Executar",
        button_type="Kimi",
        prompt="Pair analyse no comando ativo.",
        action="Executar",
        target_path="terminal-workspace-output",
    )
    for b in (b1, b2, b3):
        b.prompt_requested.connect(lambda p: print("emitted:", p))
        layout.addWidget(b)

    root.show()
    sys.exit(app.exec())
