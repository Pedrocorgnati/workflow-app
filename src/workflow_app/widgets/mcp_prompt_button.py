"""
MCPPromptButton — Botao canonico para disparo de prompts MCP.

Aceita button_type Claude/Codex/Kimi (legacy) + type-selector-radio-input
(seed-driven brainstorm; T2 loop 05-21-implantation-tasklist-aba-brainstorm).
Aceita action legacy send/queue/config + 7 literals pt-BR canonicos.

Uso seed-driven (brainstorm grade):
    btn = MCPPromptButton(
        label="Criar md",
        button_type="Claude",
        prompt=Path("blacksmith/brainstorm-mcp/seeds/01-criar-md.md"),
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

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, QSize, Qt, Signal
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

from workflow_app import brainstorm_telemetry
from workflow_app.signal_bus import signal_bus

logger = logging.getLogger(__name__)

ButtonType = Literal["Claude", "Codex", "Kimi", "type-selector-radio-input"]
#: Vocabulario de action: ABERTO desde a Task 29.
#:
#: Era um `Literal[...]` de 15 membros -- a QUARTA copia da lista de actions,
#: depois de `ACTION_LITERALS`, `ACTION_COHERENCE` e `VALID_ACTIONS_PTBR`, e a
#: unica que nenhum teste conseguia consertar sozinha porque um `Literal` so
#: existe para o type checker. Fechar o tipo tambem significava que ganhar uma
#: action nova exigia editar Python, exatamente o que a Task 29 removeu do
#: caminho do operador.
#:
#: O que continua fechado, e por que basta: o par persona-action
#: (`brainstorm_seed_contract.validate_persona_action`) segue reprovando
#: action incoerente em persona CONHECIDA, e `mcp_prompt_actions.build_prompt`
#: segue exigindo a action no catalogo quando o seed nao traz o proprio bloco
#: `## Prompt canonico`. O gate mudou de lugar; nao evaporou.
ActionType = str

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
    "Questionar",
    "Delegar",
    "Atualizar scaffolds e blueprints",
}
VALID_ACTIONS: set[str] = VALID_ACTIONS_LEGACY | VALID_ACTIONS_PTBR

VALID_TERMINALS: set[str] = {
    "terminal-interactive-output",
    "terminal-workspace-output",
    "terminal-codex-output",
}
# Alias publico para compat com leitores externos do widget.
_VALID_TARGETS: set[str] = VALID_TERMINALS

#: Valor de `target_terminal` que adia a escolha do terminal para o runtime:
#: quem decide e o radio T1/T2/T3 no momento do clique, nao o seed. Fica FORA
#: de `VALID_TERMINALS` de proposito (nao e um terminal, e a ausencia de um),
#: mas e um valor de dominio legitimo do frontmatter -- 20 dos 24 seeds usam.
#: Definido aqui, junto do catalogo, para que main_window e o dialogo de
#: configuracao leiam a mesma constante em vez de repetir o literal.
SEED_TARGET_TERMINAL_RUNTIME_SENTINEL: str = "depende-do-radio"

#: Padding vertical (px, por lado) dos botoes da grade `brainstorm-buttons-grid`.
#: Unico knob de altura: o botao mede `conteudo + 2 * BUTTON_V_PADDING_PX`. Era 1px
#: sobre um piso de estilo de 19px (folga real de 2.5px/lado); com o piso
#: removido do `sizeHint`, este 1px passou a valer e o botao caiu para 16px —
#: a "metade do padding" pedida em 2026-07-27.
BUTTON_V_PADDING_PX = 1

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


def _acao_guardada(action: str) -> bool:
    """True quando esta action merece debounce e confirmacao de re-disparo.

    Duas fontes, nao uma:

    - `_GUARDED_ACTIONS` -- as duas actions CONHECIDAMENTE destrutivas, que
      mandam o modelo executar uma task ou revisar uma execucao. Sempre
      guardadas, como desde o hardening T7.
    - tudo que esta FORA de `VALID_ACTIONS` -- action que ninguem mediu.

    O segundo ramo nasceu com a Task 29. Enquanto o gate de action era um
    enum fechado, "action fora do catalogo" nao existia e a whitelist exata
    era completa por construcao. Abrindo o combo do gear, um rotulo novo
    ("Executar tudo", "Deploy") passa a ser digitavel -- e caia direto no
    ramo sem guarda nenhuma: sem debounce contra duplo-clique e sem
    confirmacao ao re-disparar. Quanto MENOS se sabe sobre a action, MENOS
    protecao ela tinha.

    As 12 actions conhecidas e nao destrutivas seguem disparando direto: elas
    estao em `VALID_ACTIONS` e fora de `_GUARDED_ACTIONS`. O custo do
    default seguro recai so sobre rotulo novo, e e 800 ms mais um "confirma?"
    no segundo clique.
    """
    return action in _GUARDED_ACTIONS or action not in VALID_ACTIONS

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

#: Quantas chars do prompt entram no tooltip de preview. Constante e nao
#: literal porque o valor aparecia em SEIS lugares (tres cortes e tres
#: comparacoes de comprimento) nos tres construtores duplicados que a
#: Task 30 fundiu.
_TOOLTIP_PREVIEW_LEN = 80

#: Texto da UI que diz de onde vem a previa do prompt e onde se edita. Sem
#: ele o campo travado parece defeito, e o operador procura o bug em vez do
#: gear (Task 31, D15).
_PROMPT_PREVIEW_HINT = (
    "Somente leitura. Este texto e o bloco `## Prompt canonico` do seed. "
    "Para edita-lo, use a engrenagem da aba Brainstorm "
    "(Configurar seeds brainstorm-mcp)."
)

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
    """Modal de config do botao MCP (right-click). Prompt e PREVIA, nao campo.

    D15 -- escritor unico, leitor derivado (Task 31).

    Ate aqui este modal tinha um `QPlainTextEdit` editavel com o prompt, e
    aceitar o dialogo fazia `self._prompt = values["prompt"]` no botao. Isso
    criava uma SEGUNDA superficie de escrita sobre o mesmo campo que o gear
    (`brainstorm_mcp_config_dialog`) grava no bloco `## Prompt canonico` do
    seed. Duas superficies de escrita sobre o mesmo dado nao "competem": elas
    produzem last-write-wins silencioso, e neste caso o silencio era pior que
    o normal, porque a escrita do modal nao ia para o disco. Quando o botao
    nasce de um seed, `_prompt` e um `Path`; aceitar o modal trocava esse
    `Path` por uma STRING com o conteudo lido. O botao passava a despachar o
    texto congelado no momento em que alguem abriu o modal, o seed no disco
    seguia com o texto verdadeiro, o gear continuava mostrando o do disco, e
    nada na tela dizia que os dois tinham divergido.

    A saida nao e remover o campo das duas superficies: quem abre o modal
    precisa ver QUE prompt aquele botao dispara. Entao o campo fica, como
    previa somente-leitura da mesma fonte, e a UI diz de onde o texto vem e
    onde se edita. Escritor unico: o gear. Leitor derivado: este modal.
    """

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
        # Previa: somente-leitura DE FATO (`setReadOnly`), nao apenas
        # visualmente. Sem isto o operador digita, o dialogo aceita e a
        # edicao evapora no `values()` -- pior que um campo travado, porque
        # parece ter funcionado.
        self._prompt_edit = QPlainTextEdit(prompt, self)
        self._prompt_edit.setReadOnly(True)
        self._prompt_edit.setMinimumHeight(120)
        self._prompt_edit.setProperty("testid", "mcp-prompt-config-preview")
        self._prompt_edit.setToolTip(_PROMPT_PREVIEW_HINT)
        self._prompt_hint = QLabel(_PROMPT_PREVIEW_HINT, self)
        self._prompt_hint.setWordWrap(True)
        self._prompt_hint.setProperty("testid", "mcp-prompt-config-preview-hint")
        self._agent_name_edit = QLineEdit(agent_name or "", self)
        self._agent_path_edit = QLineEdit(agent_path or "", self)
        self._target_edit = QLineEdit(target_path or "", self)

        form.addRow("Label:", self._label_edit)
        form.addRow("Prompt (previa):", self._prompt_edit)
        form.addRow("", self._prompt_hint)
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
        """Campos EDITAVEIS do modal. `prompt` saiu de proposito (D15).

        A chave nao esta ausente por esquecimento: enquanto ela existir,
        existe um caminho de persistencia saindo daqui, e o proximo caller a
        escrever `self._prompt = values["prompt"]` recria a divergencia que a
        Task 31 fechou. Para LER a previa existe `prompt_preview()`.
        """
        return {
            "label": self._label_edit.text(),
            "agent_name": self._agent_name_edit.text() or "",
            "agent_path": self._agent_path_edit.text() or "",
            "target_path": self._target_edit.text() or "",
        }

    def prompt_preview(self) -> str:
        """Texto exibido na previa. Leitura; nao ha contraparte de escrita."""
        return self._prompt_edit.toPlainText()


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
        action_literal: str | None = None,
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
        # Task 29 abriu `ActionType` para `str`; este gate de pertinencia era
        # o que ainda desfazia a abertura na pratica. Com ele, o operador
        # digitava uma action nova no combo editavel do gear, o save dizia OK
        # e o proximo rebuild da grade perdia o botao -- caminho de escrita e
        # caminho de leitura discordando em silencio, que e exatamente a
        # classe de defeito que esta C2 existe para fechar.
        #
        # O que substituiu o gate, e por que basta: o par persona-action
        # (`brainstorm_seed_contract.validate_persona_action`) segue reprovando
        # action incoerente em persona conhecida, e `build_prompt` segue
        # exigindo o bloco `## Prompt canonico` no seed quando a action esta
        # fora de `ACTION_LITERALS`. `VALID_ACTIONS` continua fechado onde
        # deve: a superficie PROGRAMATICA de agentes
        # (`agent_integration_specs.SUPPORTED_ACTIONS`) o consome como antes.
        if not isinstance(action, str) or not action.strip():
            raise ValueError(
                f"action invalida: {action!r} (esperado: str nao vazia)"
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
        # `None` = este botao nao veio de seed (suplemento / caller
        # programatico) e `build_prompt` deve usar `ACTION_LITERALS`.
        # Qualquer str, inclusive vazia, e literal vindo do seed.
        if action_literal is not None and not isinstance(action_literal, str):
            raise TypeError("action_literal deve ser str ou None")
        self._action_literal = action_literal

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
        # Padding vertical: sem altura fixa, a altura do botao e o conteudo
        # mais a margem de cima/baixo declarada AQUI — este layout e o unico
        # knob de padding vertical da grade `brainstorm-buttons-grid`.
        #
        # 07-27 (2a rodada): o pedido de "metade do padding" so teve efeito
        # depois que `sizeHint()` parou de herdar o piso vertical do
        # QPushButton (ver `_CONTENT_DRIVEN_HEIGHT` abaixo): com o piso, o
        # botao media 19px independente da margem (2.5px de folga por lado).
        # Sem ele, a margem de 1px vale de verdade e o botao mede 16px.
        row.setContentsMargins(6, BUTTON_V_PADDING_PX, 8, BUTTON_V_PADDING_PX)
        row.setSpacing(4)
        row.addWidget(self._checkbox, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._label_widget, 1, Qt.AlignmentFlag.AlignVCenter)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_visual_state()

        # Tooltip: primeiras chars do prompt (builder unico, Task 30).
        self.setToolTip(self._build_tooltip())

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

    # Geometria

    def _layout_size(self, *, minimum: bool) -> QSize | None:
        layout = self.layout()
        if layout is None:
            return None
        return layout.totalMinimumSize() if minimum else layout.totalSizeHint()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """Largura suficiente para o label inteiro (checkbox + texto + margens).

        `QPushButton.sizeHint()` deriva do texto NATIVO do botao, que aqui e
        vazio de proposito (o label visivel e um QLabel filho). Sem este
        override o hint fica em ~34px e o `ResponsiveButtonFlowLayout`, que
        dimensiona cada item pelo proprio hint, corta o label. Mesclar com o
        `totalSizeHint()` do QHBoxLayout interno devolve a largura real do
        conteudo.

        ALTURA (07-27): vem SO do layout interno, nunca do piso do QPushButton.
        O piso do estilo (19px, insensivel a QSS `min-height` e a margem do
        layout) congelava a altura e fazia qualquer ajuste de padding vertical
        virar no-op. Largura continua sendo o maximo entre os dois.
        """
        base = super().sizeHint()
        content = self._layout_size(minimum=False)
        if content is None:
            return base
        return QSize(max(base.width(), content.width()), content.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """Piso de largura tambem ancorado no conteudo real do botao.

        Altura pelo mesmo criterio do `sizeHint` (conteudo, sem o piso do
        estilo) — do contrario o minimo reintroduziria os 19px.
        """
        base = super().minimumSizeHint()
        content = self._layout_size(minimum=True)
        if content is None:
            return base
        return QSize(max(base.width(), content.width()), content.height())

    # API

    def payload(self) -> dict:
        """Payload canonico emitido em `prompt_requested`.

        `button_id` propaga o objectName para que o handler externo
        possa direcionar `signal_bus.dispatch_result` ao widget de origem.
        """
        payload = {
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
        # `None` significa ausencia NO TRANSPORTE (botao suplementar, caller
        # programatico); `""` seria presenca vazia. Emitir a chave sempre
        # faria o suplemento nunca alcancar o fallback `ACTION_LITERALS`.
        if self._action_literal is not None:
            payload["action_literal"] = self._action_literal
        return payload

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
        """Devolve o texto que a UI mostra como previa do prompt.

        O literal congelado no build VENCE a leitura do arquivo. As duas
        superficies de previa (tooltip e modal de right-click) existem para
        responder UMA pergunta -- "o que este botao vai mandar?" -- e a
        resposta e `self._action_literal`, que e o que `payload()` emite e o
        que `build_prompt` injeta em `{action}`.

        Antes disto elas liam o `.md` INTEIRO, e cada divergencia era
        visivel:

        - o corte de 80 chars do tooltip caia dentro do frontmatter, entao a
          previa era `---\nslug: criar-md\ntitle: ...` -- YAML, nunca o
          prompt;
        - o modal mostrava frontmatter, `## Objetivo` e `## Notas` embaixo do
          rotulo que afirma, em `_PROMPT_PREVIEW_HINT`, ser "o bloco
          `## Prompt canonico` do seed";
        - editar o seed em disco POR FORA da engrenagem trocava a previa e
          nao trocava o despacho, porque o botao ja carregava o snapshot: o
          operador lia B e o modelo recebia A.

        A leitura do arquivo sobrevive para quem nao tem literal -- caller
        programatico e `prompt` que ja e string literal. Ai o arquivo e, de
        fato, a unica fonte disponivel.
        """
        if self._action_literal is not None:
            return self._action_literal
        if isinstance(self._prompt, Path):
            try:
                return self._prompt.read_text(encoding="utf-8")
            except OSError:
                return f"[erro lendo {self._prompt}]"
        return str(self._prompt)

    def _build_tooltip(self) -> str:
        """Monta o tooltip canonico de preview. Fonte UNICA dos tres caminhos.

        Ate a Task 30 este texto era remontado a mao em tres lugares -- o
        `__init__`, o `recheck_codex_availability` e o
        `_on_codex_availability_changed`. Tres copias do mesmo f-string
        significam que mudar a FONTE do literal (foi o que a C2 fez, tirando
        o prompt do frontmatter e passando para o bloco `## Prompt canonico`)
        conserta um caminho e deixa dois exibindo o texto velho, sem que
        nenhum teste perceba: os tres produziam strings diferentes so quando
        a fonte divergia, que e exatamente o momento em que ninguem esta
        olhando.

        Efeito colateral desejado: `_resolve_prompt_text()` e chamado UMA vez
        por tooltip. As tres copias chamavam duas vezes cada (uma para cortar,
        outra para medir o comprimento), o que em seed com `prompt` do tipo
        `Path` era uma segunda leitura de disco por tooltip montado.
        """
        prompt = self._resolve_prompt_text()
        reticencias = "..." if len(prompt) > _TOOLTIP_PREVIEW_LEN else ""
        return (
            f"[{self._button_type}] {self._label}\n"
            f"action={self._action} target={self._target_path or '-'}\n"
            f"prompt: {prompt[:_TOOLTIP_PREVIEW_LEN]}{reticencias}"
        )

    def _is_debounced(self) -> bool:
        """True quando clique cai dentro da janela de debounce per-botao.

        Aplica APENAS para actions em `_GUARDED_ACTIONS`. Cliques bloqueados
        sao IGNORADOS (nao enfileirados). Per-botao explicito - debounce de
        outros widgets nao afeta este.
        """
        if not _acao_guardada(self._action):
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
        return _acao_guardada(self._action) and self._checkbox_state

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
                self.setToolTip(self._build_tooltip())
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
                self.setToolTip(self._build_tooltip())
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
            # Este -- e nao o gate de `_on_clicked` -- e o caminho DOMINANTE
            # de `codex_unavailable` em producao: quando o T3 ja esta morto
            # na construcao, o botao nasce `disabled`, `clicked` nunca chega
            # ao slot e o clique morre aqui. Instrumentar so o slot media a
            # janela rara (cache envenenado entre o enable e o clique) e
            # deixava o caso comum contando como "botao nunca clicado" --
            # exatamente a ambiguidade que os WIDGET_REASONS existem para
            # desfazer, e com o sinal invertido: um botao que o operador
            # tenta usar e nao consegue apareceria como candidato a
            # aposentadoria.
            self._registrar_bloqueio("codex_unavailable")
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

    def _registrar_bloqueio(self, reason: str) -> None:
        """Um clique que morreu antes do `emit`.

        Sem estes tres eventos, "zero uso" e ambiguo: o botao nunca clicado e
        o botao clicado e barrado no gate produzem o mesmo silencio, e o
        segundo e o oposto de um candidato a aposentadoria.

        A raiz do repo vem da janela quando a janela e a MainWindow. Em teste
        de widget isolado ela nao e, e ai `source_kind` fica `unknown` -- que
        e a resposta honesta, nao um defeito a contornar.
        """
        raiz = None
        obter_raiz = getattr(self.window(), "_systemforge_root", None)
        if callable(obter_raiz):
            try:
                raiz = obter_raiz()
            except Exception:  # noqa: BLE001
                raiz = None
        brainstorm_telemetry.record_click_blocked(
            reason=reason,
            button_id=self._button_id,
            testid_slug=self._testid_slug,
            action=self._action,
            requested_provider=self._button_type,
            source_kind=brainstorm_telemetry.source_kind_for(self._prompt, raiz),
        )

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
            self._registrar_bloqueio("codex_unavailable")
            return
        # Gate T6: debounce
        if self._is_debounced():
            self._registrar_bloqueio("debounced")
            return
        # Gate T6: confirmacao re-clique
        md_path = getattr(self.window(), "_brainstorm_md_path", None)
        if not self._confirm_redispatch(md_path):
            self._registrar_bloqueio("redispatch_declined")
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
            # `self._prompt` NAO e reatribuido aqui (D15, Task 31). Quando o
            # botao vem de um seed, `_prompt` e o `Path` do arquivo, e a
            # linha que existia neste ponto o trocava por uma string com o
            # conteudo lido: dali em diante o botao despachava um texto
            # congelado e deixava de acompanhar o seed no disco.
            self._agent_name = values["agent_name"] or None
            self._agent_path = values["agent_path"] or None
            new_target = values["target_path"] or None
            if new_target and new_target in VALID_TERMINALS:
                if self._button_type == "Codex" and new_target != "terminal-codex-output":
                    # mantem o atual; nao quebra o widget
                    pass
                else:
                    self._target_path = new_target
            self._refresh_tooltip()
        event.accept()

    def _refresh_tooltip(self) -> None:
        """Re-monta o tooltip depois de uma mutacao de estado exibido.

        O tooltip e a UNICA superficie que mostra `label`, `action` e
        `target` juntos. O modal do right-click reescreve tres desses
        campos e, ate aqui, nao remontava nada: o operador trocava o
        destino de `terminal-interactive-output` para `terminal-codex-
        output`, aceitava, passava o mouse por cima e lia o destino
        VELHO. A unica confirmacao visual que ele tem de que a edicao
        pegou afirmava que nao pegou -- e o clique seguinte ia para o
        destino novo. Errar dos dois lados: quem confia no tooltip
        re-edita o que ja estava certo; quem nao confia perde o
        tooltip como fonte.

        Nao sobrescreve o aviso de Codex indisponivel (`_CODEX_TOAST_
        SHORT`): naquele estado o botao esta desabilitado e o texto de
        preview seria uma promessa falsa de que o clique despacha.
        """
        if self._button_type == "Codex" and not self._is_codex_alive_cached():
            return
        self.setToolTip(self._build_tooltip())


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
