"""FlagsPanel — painel de flags MCP na aba LLM Routing (item 021).

Checkboxes (um por literal canonico), com logica de disable/tooltip
quando a flag e incompativel com o Main corrente (C-57, C-43 e MiMo > Kimi;
tabela `_AUTOPROXY_FLAGS_BY_MAIN`). Desabilitada e fora do payload sao a
MESMA regra (`inactive_flags_for_main`): `checked_flags` nunca devolve flag
cinza, mesmo marcada antes da troca de Main.

Layout: duas colunas rotuladas — thinking (raciocinio mais poderoso) e
execution (runtime de terminal). A capacidade NAO vive em
`queue-div-main-llm`.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from workflow_app.config.llm_flags import (
    _AUTOPROXY_FLAGS_BY_MAIN,
    _EXECUTION_FLAG_ORDER,
    _FLAG_CANONICAL_ORDER,
    _FLAG_LITERAL_TO_MAIN,
    _FLAGS_BY_TERMINAL,
    _MIMO_SUPERSEDES,
    _REDUNDANT_FLAG_MAINS,
    _THINKING_FLAG_ORDER,
)

# Ordem estavel dos checkboxes na UI (canonica).
_FLAG_ORDER: list[str] = list(_FLAG_CANONICAL_ORDER)

_COLUMN_LABEL_QSS = (
    "QLabel { color: #A1A1AA; font-size: 11px; font-weight: 700;"
    "  background: transparent; border: none; }"
)

# Tooltip default para flags habilitadas.
_DEFAULT_TOOLTIP = (
    "Quando marcado, anexa {flag} ao label dos itens T1 (Claude). "
    "Nunca afeta /clear, /model, /effort, local-action nem itens worker."
)


def autoproxy_tooltip(flag: str, main: str) -> str:
    """Tooltip de uma flag desabilitada por auto-proxy sob o Main ``main``.

    A tabela de quem desabilita o que e `_AUTOPROXY_FLAGS_BY_MAIN`
    (`config/llm_flags.py`); aqui vive so o texto, um por Main. Publica
    porque o loop legado de checkboxes do `CommandQueueWidget` mostra o
    mesmo texto (Zero Silencio: o operador sabe por que a flag apagou).

    - kimi (C-43 / R-40): as skills de provider do lado Kimi
      (`.kimi/skills/codex`) sao auto-proxies do proprio Kimi; honrar a flag
      do Codex sob Main Kimi produziria registro falso de segunda opiniao.
    - mimo (MiMo > Kimi, 2026-10-02): com a MiMo no T1 nenhum caminho
      escolhe o Kimi.
    """
    if main == "kimi":
        return (
            f"{flag} desabilitado sob Main Kimi: as skills de provider do lado Kimi "
            "sao auto-proxy, entao a flag viraria auto-consulta silenciosa em vez de "
            "segunda opiniao explicita. Para pedir Codex de forma explicita, troque "
            "o Main."
        )
    if main == "mimo":
        return (
            f"{flag} desabilitado sob Main MiMo: MiMo > Kimi (2026-10-02). Com a "
            "MiMo no T1 nenhum caminho escolhe o Kimi, e o parser v2 mandaria a "
            "flag para a propria MiMo (auto-consulta). Para pedir Kimi de forma "
            "explicita, troque o Main."
        )
    return f"{flag} desabilitado sob Main {main}."


_KILL_SWITCH_TOOLTIP = (
    "Paridade de flags desabilitada pelo kill-switch "
    "SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0."
)


def _main_slug(main: str | None) -> str:
    """Slug normalizado do Main (vazio/None cai no default ``claude``)."""
    return main.strip().lower() if main else "claude"


def _kill_switch_blocks(slug: str) -> bool:
    """True quando o kill-switch de paridade derruba as flags sob ``slug``.

    Escopo do switch: so Main nao-Claude (source.md:444). Sob Main Claude
    nao existe delegacao non-Claude a frear.
    """
    from workflow_app.config import delegation_flags_nonclaude_enabled

    return slug != "claude" and not delegation_flags_nonclaude_enabled()


def inactive_flags_for_main(main: str | None) -> frozenset[str]:
    """Flags do regime vigente que NAO valem sob o Main ``main``.

    Fonte unica de duas coisas que nao podem divergir: o checkbox cinza no
    `FlagsPanel` e a ausencia da flag no payload T1 (`checked_flags`). Flag
    desabilitada que seguisse no sufixo era o defeito: um `--kimi` marcado
    sob Main Claude continuava no payload depois do Main virar MiMo,
    reabrindo o caminho para o Kimi que o auto-proxy MiMo > Kimi fecha.

    Uniao, na precedencia do painel:
      - kill-switch ``SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0`` sob Main
        nao-Claude: todas as flags do regime vigente;
      - auto-proxy do Main (`_AUTOPROXY_FLAGS_BY_MAIN`);
      - flags redundantes com o Main (`_REDUNDANT_FLAG_MAINS`).

    Publica porque o caminho legado de checkboxes do `CommandQueueWidget`
    (sem `FlagsPanel` embutido) precisa do mesmo filtro.
    """
    slug = _main_slug(main)
    if _kill_switch_blocks(slug):
        return frozenset(_FLAG_ORDER)
    redundant = frozenset(
        flag for flag, owner in _REDUNDANT_FLAG_MAINS.items() if owner == slug
    )
    return _AUTOPROXY_FLAGS_BY_MAIN.get(slug, frozenset()) | redundant


def _terminals_for_flag(flag: str) -> str:
    """Terminais que aceitam a flag, na ordem T1 > T2 > T3.

    Consome `_FLAGS_BY_TERMINAL` (constante que ate 2026-08-17 nascia morta,
    gap ST003 do item 021): o operador precisa ver, sem clicar, onde a flag
    tem efeito.
    """
    return ", ".join(
        term for term in ("T1", "T2", "T3")
        if flag in _FLAGS_BY_TERMINAL.get(term, frozenset())
    )


class FlagsPanel(QWidget):
    """Painel de flags MCP na aba LLM Config (thinking / execution).

    Sinal ``flags_changed`` e emitido quando qualquer checkbox muda de estado.
    """

    flags_changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        main_llm_resolver: Callable[[], str] | None = None,
        show_label: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        self._main_llm_resolver = main_llm_resolver
        self._checkboxes: dict[str, QCheckBox] = {}
        # Flags fora do payload sob o ultimo Main aplicado. Vazio ate o
        # primeiro `set_main_llm` (Main Claude sem kill-switch: nada cai).
        self._inactive: frozenset[str] = frozenset()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self._label: QLabel | None = None
        if show_label:
            self._label = QLabel("Flag")
            self._label.setStyleSheet(
                "QLabel { color: #A1A1AA; font-size: 11px; font-weight: 700;"
                "  background: transparent; border: none; }"
            )
            outer.addWidget(self._label)

        grid_host = QWidget()
        grid_host.setStyleSheet("background: transparent; border: none;")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)

        thinking_lbl = QLabel("Thinking")
        thinking_lbl.setProperty("testid", "queue-div-flag-thinking")
        thinking_lbl.setStyleSheet(_COLUMN_LABEL_QSS)
        execution_lbl = QLabel("Execution")
        execution_lbl.setProperty("testid", "queue-div-flag-execution")
        execution_lbl.setStyleSheet(_COLUMN_LABEL_QSS)
        grid.addWidget(thinking_lbl, 0, 0)
        grid.addWidget(execution_lbl, 0, 1)

        thinking_flags = [f for f in _THINKING_FLAG_ORDER if f in _FLAG_ORDER]
        execution_flags = [f for f in _EXECUTION_FLAG_ORDER if f in _FLAG_ORDER]

        def _add_flag_checkbox(flag: str, row: int, column: int) -> None:
            chk = QCheckBox(flag)
            testid = f"queue-chk-flag-{flag.lstrip('-')}"
            chk.setProperty("testid", testid)
            chk.setToolTip(_DEFAULT_TOOLTIP.format(flag=flag))
            chk.toggled.connect(self._on_checkbox_toggled)
            grid.addWidget(chk, row, column)
            self._checkboxes[flag] = chk

        for idx, flag in enumerate(thinking_flags):
            _add_flag_checkbox(flag, idx + 1, 0)
        for idx, flag in enumerate(execution_flags):
            _add_flag_checkbox(flag, idx + 1, 1)

        outer.addWidget(grid_host)
        outer.addStretch(1)

        # Estado inicial coerente com o Main persistido e com o kill-switch:
        # sem esta chamada o painel nascia com todas habilitadas ate o operador
        # girar o radio de Main pela primeira vez (gap A4 do item 021).
        if main_llm_resolver is not None:
            self.refresh()

    # ── Estado ────────────────────────────────────────────────────────────── #

    def _on_checkbox_toggled(self, checked: bool) -> None:
        _ = checked
        self.flags_changed.emit()

    def checkbox(self, flag: str) -> QCheckBox | None:
        """Acessor do QCheckBox de uma flag (None quando o literal e invalido).

        Usado pelo `CommandQueueWidget` para expor os checkboxes do painel como
        `_flag_<slug>_chk`, mantendo UM unico controle por literal (e portanto
        um unico `queue-chk-flag-*` por testid).
        """
        return self._checkboxes.get(flag)

    def checked_flags(self) -> list[str]:
        """Flags marcadas QUE VALEM sob o Main corrente, na ordem estavel.

        E a fonte do sufixo T1 (`CommandQueueWidget._active_mcp_flags`).
        Flag desabilitada (auto-proxy, redundante ou kill-switch) fica fora
        mesmo marcada: sem isso um `--kimi` marcado antes da troca para Main
        MiMo seguia no payload (MiMo > Kimi). O metodo nunca desmarca: a
        selecao do operador volta ao payload quando o Main volta a aceitar
        a flag.
        """
        return [
            f for f in _FLAG_ORDER
            if f not in self._inactive and self._checkboxes[f].isChecked()
        ]

    def inactive_flags(self) -> frozenset[str]:
        """Flags fora do payload sob o ultimo Main aplicado (`set_main_llm`)."""
        return self._inactive

    def refresh(self) -> None:
        """Reaplica enabled/tooltip lendo o Main do resolver injetado."""
        if self._main_llm_resolver is None:
            return
        try:
            self.set_main_llm(self._main_llm_resolver())
        except Exception:  # noqa: BLE001 - painel nunca derruba a janela
            self.set_main_llm("claude")

    def set_main_llm(self, main: str) -> None:
        """Atualiza enabled/disabled e tooltip de cada checkbox.

        Regras:
          - Kill-switch SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0: disabled
            apenas sob Main **nao-Claude** (source.md:444). Sob Main Claude o
            kill-switch nao tem efeito: nao existe delegacao non-Claude a
            frear quando o proprio Main ja e Claude.
          - Main claude: todas habilitadas (variantes de raciocinio nao
            redundam o CLI do T1).
          - Main kimi: --kimi e --kimi-k3 disabled (redundantes); --codex e
            --codex-ultra disabled por auto-proxy (C-43/R-40).
          - Main mimo: --mimo e --mimo-pro disabled (redundantes); --kimi e
            --kimi-k3 disabled (MiMo > Kimi).
          - Main codex: --codex e --codex-ultra disabled (redundantes).
          - Main qwen: --qwen disabled (redundante).
          - Main grok: --grok e --grok-xhigh disabled (redundantes).
        O auto-proxy vem da tabela `_AUTOPROXY_FLAGS_BY_MAIN` do regime
        vigente e tem precedencia sobre a regra de redundancia.

        O conjunto desabilitado vem de `inactive_flags_for_main` e e o MESMO
        que `checked_flags` tira do payload. Nenhum checkbox e desmarcado:
        a marcacao sobrevive a troca de Main e volta a valer quando o Main
        volta a aceitar a flag.
        """
        slug = _main_slug(main)
        inactive = inactive_flags_for_main(slug)
        self._inactive = inactive

        if _kill_switch_blocks(slug):
            for chk in self._checkboxes.values():
                chk.setEnabled(False)
                chk.setToolTip(_KILL_SWITCH_TOOLTIP)
            return

        autoproxy = _AUTOPROXY_FLAGS_BY_MAIN.get(slug, frozenset())
        for flag, chk in self._checkboxes.items():
            disabled = flag in inactive
            chk.setEnabled(not disabled)
            if flag in autoproxy:
                chk.setToolTip(autoproxy_tooltip(flag, slug))
            else:
                chk.setToolTip(self._tooltip_for_flag(flag, slug, disabled=disabled))

    def set_flag_states_from_mirror(self, flags: list[str]) -> None:
        """Sincroniza os checkboxes a partir de uma lista de flags ativas.

        Usado pelo espelho do command_queue para manter paridade bidirecional.
        Nao emite ``flags_changed`` para evitar loop de feedback.
        """
        for flag, chk in self._checkboxes.items():
            should_check = flag in flags
            if chk.isChecked() != should_check:
                chk.blockSignals(True)
                chk.setChecked(should_check)
                chk.blockSignals(False)

    def _tooltip_for_flag(
        self, flag: str, main: str, *, disabled: bool
    ) -> str:
        """Tooltip contextual para uma flag sob um Main especifico."""
        if disabled:
            redundant_main = _REDUNDANT_FLAG_MAINS.get(flag)
            if redundant_main and main == redundant_main:
                return f"Flag {flag} redundante sob Main {main}."
            return _KILL_SWITCH_TOOLTIP
        target = _FLAG_LITERAL_TO_MAIN.get(flag, "")
        terminals = _terminals_for_flag(flag)
        suffix = ""
        if target and terminals:
            suffix = f"\nDelega para {target}. Aceita em: {terminals}."
        # Precedencia MiMo > Kimi (2026-10-02), pareada por coluna: com as
        # duas do par marcadas a do Kimi sai do payload; o tooltip avisa
        # (Zero Silencio). Pares do regime vigente em `_MIMO_SUPERSEDES`.
        superseded = _MIMO_SUPERSEDES.get(flag)
        if superseded:
            suffix += (
                "\nVence o " + " e o ".join(sorted(superseded))
                + " quando os dois estao marcados."
            )
        for mimo_flag, losers in _MIMO_SUPERSEDES.items():
            if flag in losers:
                suffix += (
                    f"\nSe {mimo_flag} tambem estiver marcado, a MiMo vence e o "
                    f"{flag} sai do payload (MiMo > Kimi)."
                )
        return _DEFAULT_TOOLTIP.format(flag=flag) + suffix
