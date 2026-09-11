"""Testes de debounce 800ms + confirmacao re-clique para actions guarded (T6).

Cobre 4 cenarios do T6 (loop 05-21-implantation-tasklist-aba-brainstorm):
- test_debounce_blocks_rapid_clicks: 800ms via `frozen_clock` (sem sleep real).
- test_executar_requires_confirmation_on_re_click: QMessageBox.question.
- test_state_clears_on_grid_restart: mark_dispatch_result(False) reseta tudo.
- test_propagation_on_inline_checkbox_click: _InlineCheckBox NAO dispara
  prompt_requested (stop propagation).

Hardening T9 §5 + §6: `frozen_clock` fixture evita sleep real; `qsettings_
isolated` autouse impede contaminacao do `~/.config/`.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.timeout(5)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


def test_debounce_blocks_rapid_clicks(
    qtbot,
    mcp_prompt_button_factory,
    codex_alive_factory,
    frozen_clock,
):
    """Clique repetido em <800ms NAO emite prompt_requested (debounce).

    Action `Executar` esta em `_GUARDED_ACTIONS` -> debounce ativo.
    Apos avancar 900ms via `frozen_clock`, novo clique passa.
    """
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(
        button_type="Claude",
        action="Executar",
        target_path="terminal-interactive-output",
    )
    received: list[dict] = []
    btn.prompt_requested.connect(lambda p: received.append(p))

    # 1o clique: passa (sem debounce previo).
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert len(received) == 1

    # 2o clique imediato: bloqueado por debounce.
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert len(received) == 1, "2o clique deveria estar bloqueado"

    # Avanca 900ms: debounce libera.
    frozen_clock(900)
    # Mas re-clique exige confirmacao se checkbox foi marcado externamente.
    # Como `mark_dispatch_result` nao foi chamado, checkbox=False - passa.
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert len(received) == 2


def test_executar_requires_confirmation_on_re_click(
    qtbot,
    mcp_prompt_button_factory,
    codex_alive_factory,
    monkeypatch,
    frozen_clock,
):
    """Re-clique em action guarded com checkbox marcado abre QMessageBox.

    `_confirm_redispatch` invoca `QMessageBox.question` com default `No`.
    Mockamos para retornar `No` -> emit NAO acontece.
    """
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(
        button_type="Claude",
        action="Executar",
        target_path="terminal-interactive-output",
    )
    received: list[dict] = []
    btn.prompt_requested.connect(lambda p: received.append(p))

    # Simula sucesso previo: checkbox=marcado + last_dispatch_ns setado.
    btn.mark_dispatch_result(True)
    assert btn._checkbox_state is True

    # Avanca para sair da janela de debounce mas mantem checkbox.
    frozen_clock(900)

    # Mock do dialogo: usuario clica em "No".
    question_calls: list[tuple] = []

    def _fake_question(parent, title, text, *args, **kwargs):
        question_calls.append((title, text))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_fake_question))

    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert len(question_calls) == 1, (
        "esperado abrir QMessageBox.question exatamente uma vez"
    )
    assert received == [], "usuario disse 'No' -> nao deve emitir"


def test_state_clears_on_grid_restart(
    qtbot,
    mcp_prompt_button_factory,
    codex_alive_factory,
):
    """Falha do dispatch desmarca checkbox e zera debounce (libera retry).

    Spec §7.3: `mark_dispatch_result(False)` desmarca checkbox + zera
    last_dispatch_ns para liberar retry imediato. Simula o efeito de
    rebuild da grade ou restart do QApplication (estado intra-sessao
    nao persiste).
    """
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(
        button_type="Claude",
        action="Executar",
        target_path="terminal-interactive-output",
    )
    btn.mark_dispatch_result(True)
    assert btn._checkbox_state is True
    assert btn._last_dispatch_ns != 0
    # Falha (e.g. terminal nao publicou):
    btn.mark_dispatch_result(False)
    assert btn._checkbox_state is False
    assert btn._last_dispatch_ns == 0


def test_propagation_on_inline_checkbox_click(
    qtbot,
    mcp_prompt_button_factory,
    codex_alive_factory,
):
    """Clique direto no `_InlineCheckBox` NAO dispara prompt_requested.

    Stop propagation forte via `event.accept()` em mousePressEvent +
    mouseReleaseEvent. Spec base-archive 230-236.
    """
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(
        button_type="Claude",
        action="Executar",
        target_path="terminal-interactive-output",
    )
    received: list[dict] = []
    btn.prompt_requested.connect(lambda p: received.append(p))

    cb = btn._checkbox
    # Clica diretamente no checkbox embutido. Como o stop-propagation
    # acontece via event.accept(), o botao pai NAO recebe o clique.
    qtbot.mouseClick(cb, Qt.MouseButton.LeftButton)
    assert received == [], (
        "clique no checkbox embutido NAO deveria emitir prompt_requested"
    )


# ---------------------------------------------------------------------------
# Action fora do catalogo: fail-safe (Task 29 abriu o vocabulario)
# ---------------------------------------------------------------------------


def test_action_desconhecida_e_guardada_por_debounce(
    qtbot,
    mcp_prompt_button_factory,
    codex_alive_factory,
    frozen_clock,
):
    """Rotulo novo digitado no gear NAO burla o debounce.

    Enquanto o gate de action era enum fechado, `_GUARDED_ACTIONS` como
    whitelist exata era completa: so existiam as 12 actions do catalogo.
    A Task 29 abriu o gate (qualquer string nao-vazia passa) e a whitelist
    ficou para tras -- entao "Deploy", "Executar tudo" ou qualquer rotulo
    que o operador inventasse na engrenagem caia no ramo SEM debounce.
    Quanto menos se sabe sobre a action, menos protecao ela tinha.
    """
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(
        button_type="Claude",
        action="Deploy",
        target_path="terminal-interactive-output",
    )
    recebidos: list[dict] = []
    btn.prompt_requested.connect(lambda p: recebidos.append(p))

    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert len(recebidos) == 1

    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert len(recebidos) == 1, "action desconhecida deveria ter debounce"

    frozen_clock(900)
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert len(recebidos) == 2


def test_action_desconhecida_exige_confirmacao_no_re_disparo(
    qtbot,
    monkeypatch,
    mcp_prompt_button_factory,
    codex_alive_factory,
    frozen_clock,
):
    """Re-disparo de action desconhecida com checkbox marcado pergunta antes."""
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(
        button_type="Claude",
        action="Deploy",
        target_path="terminal-interactive-output",
    )
    recebidos: list[dict] = []
    btn.prompt_requested.connect(lambda p: recebidos.append(p))

    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert len(recebidos) == 1
    btn.mark_dispatch_result(True)
    frozen_clock(900)

    perguntas: list[str] = []

    def _recusa(*args, **kwargs):
        perguntas.append("perguntou")
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", _recusa)
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert perguntas == ["perguntou"]
    assert len(recebidos) == 1, "recusa na confirmacao nao deveria despachar"


def test_actions_conhecidas_e_nao_destrutivas_seguem_sem_guarda(
    qtbot,
    mcp_prompt_button_factory,
    codex_alive_factory,
):
    """O default seguro nao pode pedagiar as 12 actions do catalogo.

    Se `_acao_guardada` fosse "guarda tudo", cada clique em `Criar arquivo`
    ou `Questionar` passaria a custar 800ms e um dialogo -- o oposto do
    fluxo de brainstorm, que e clicar varios botoes em sequencia.
    """
    from workflow_app.widgets.mcp_prompt_button import (
        VALID_ACTIONS_PTBR,
        _acao_guardada,
    )

    codex_alive_factory(True)
    livres = sorted(VALID_ACTIONS_PTBR - {"Executar", "Revisar execucao"})
    assert len(livres) == 10
    assert [a for a in livres if _acao_guardada(a)] == []

    _, btn = mcp_prompt_button_factory(
        button_type="Claude",
        action="Questionar",
        target_path="terminal-interactive-output",
    )
    recebidos: list[dict] = []
    btn.prompt_requested.connect(lambda p: recebidos.append(p))
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert len(recebidos) == 2, "action livre nao deveria sofrer debounce"
