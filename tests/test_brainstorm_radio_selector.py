"""Testes do radio selector (T3): default Claude + override do button_type.

Cobre 2 cenarios canonicos do T3 (loop 05-21-implantation-tasklist-aba-brainstorm):
- test_radio_selector_default_is_claude: provider runtime nasce em "Claude".
- test_type_selector_radio_overrides_button_type: button_type=
  type-selector-radio-input consulta `radio_state_getter` em vez de
  retornar literal fixo.

Testes operam diretamente em `MCPPromptButton._resolve_provider` sem
instanciar a MainWindow inteira (a logica do radio e roteamento e
testada via stub do getter).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.timeout(5)

from PySide6.QtCore import Qt


def test_radio_selector_default_is_claude(
    qtbot,
    mcp_prompt_button_factory,
    codex_alive_factory,
):
    """button_type=type-selector-radio-input sem getter resolve para 'Claude'.

    Spec §6.2: default seguro quando getter ausente OU getter levanta
    excecao OU getter retorna valor invalido fora do catalogo
    {Claude, Kimi, Codex}.
    """
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(
        button_type="type-selector-radio-input",
        action="Otimizar",
        target_path="terminal-interactive-output",
        radio_state_getter=None,
    )
    assert btn._resolve_provider() == "Claude"

    # Valor invalido fora do catalogo: default Claude.
    _, btn_bad = mcp_prompt_button_factory(
        button_type="type-selector-radio-input",
        action="Otimizar",
        target_path="terminal-interactive-output",
        radio_state_getter=lambda: "ProviderDesconhecido",
    )
    assert btn_bad._resolve_provider() == "Claude"


def test_type_selector_radio_overrides_button_type(
    qtbot,
    mcp_prompt_button_factory,
    codex_alive_factory,
):
    """O getter dinamicamente decide o provider (Claude/Kimi/Codex).

    Botoes fixos IGNORAM o radio (button_type "Claude" sempre = Claude).
    Botoes radio-driven consultam o getter a cada clique - permitindo
    alternar entre os 3 providers sem rebuild da grade.
    """
    codex_alive_factory(True)
    state = {"provider": "Kimi"}
    _, btn = mcp_prompt_button_factory(
        button_type="type-selector-radio-input",
        action="Otimizar",
        target_path="terminal-interactive-output",
        radio_state_getter=lambda: state["provider"],
    )
    assert btn._resolve_provider() == "Kimi"

    # Toggle do radio: novo clique resolve para o novo provider.
    state["provider"] = "Codex"
    assert btn._resolve_provider() == "Codex"
    state["provider"] = "Claude"
    assert btn._resolve_provider() == "Claude"

    # Sanity: botao fixo ignora o radio.
    _, btn_fixed = mcp_prompt_button_factory(
        button_type="Kimi",
        action="Otimizar",
        target_path="terminal-workspace-output",
        radio_state_getter=lambda: "Codex",  # ignorado
    )
    assert btn_fixed._resolve_provider() == "Kimi"
