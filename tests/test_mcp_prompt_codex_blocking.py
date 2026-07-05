"""Codex blocking + T7 hardening (12 testes #1..#12).

Mapeamento 1:1 dos 12 itens de hardening do T7 (task-008 do loop
05-21-implantation-tasklist-aba-brainstorm). Cada teste valida 1
invariante endurecida em MCPPromptButton:

#1  _CODEX_TARGET_TESTID + _CODEX_TOAST_CANONICAL canonicos.
#2  Cache `_codex_alive_cache` evita findChildren repetido.
#3  `radio_state_getter_ref` armazenado como WeakMethod quando bound.
#4  `setEnabled(alive)` no __init__ para button_type=Codex fixo.
#5  `_codex_target_alive` exige QPlainTextEdit/QTextEdit + isVisibleTo
    (QLabel com testid correto NAO passa o gate).
#6  `recheck_codex_availability` emite codex_availability_changed.
#7  `_resolve_provider` faz snapshot atomico (race radio vs click).
#8  Clique em radio-Codex sem T3 emite toast canonico.
#9  `_on_clicked` segue ordem canonica (gate T7 antes de emit).
#10 `eventFilter` dispara feedback toast em clique em Codex disabled.
#11 caplog valida estrutura do log `codex_blocked` (extras canonicos).
#12 caplog valida AUSENCIA de PII (agent_path, prompt) nos extras.
"""

from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.timeout(5)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from workflow_app.signal_bus import signal_bus
from workflow_app.widgets.mcp_prompt_button import (
    MCPPromptButton,
    _CODEX_TARGET_TESTID,
    _CODEX_TOAST_CANONICAL,
    _CODEX_TOAST_SHORT,
)


class _ToastSpy:
    """Captura emissoes de `signal_bus.toast_requested` (msg, level)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        signal_bus.toast_requested.connect(self._on_toast)

    def _on_toast(self, msg: str, level: str) -> None:
        self.events.append((msg, level))

    def count(self) -> int:
        return len(self.events)

    def at(self, idx: int) -> tuple[str, str]:
        return self.events[idx]

    def disconnect(self) -> None:
        try:
            signal_bus.toast_requested.disconnect(self._on_toast)
        except (RuntimeError, TypeError):
            pass


@pytest.fixture
def toast_spy():
    spy = _ToastSpy()
    yield spy
    spy.disconnect()


# #1 - constantes canonicas existem e tem texto literal estavel.
def test_codex_constants_are_canonical():
    """Auditoria depende do texto literal byte-a-byte (mcp-flow §10.5)."""
    assert _CODEX_TARGET_TESTID == "terminal-codex-output"
    assert "Codex indisponivel" in _CODEX_TOAST_CANONICAL
    assert "terminal-codex-output" in _CODEX_TOAST_CANONICAL
    assert "Nao havera fallback automatico" in _CODEX_TOAST_CANONICAL
    assert _CODEX_TOAST_SHORT == "Codex bloqueado: T3 ausente."


# #2 - cache evita re-busca em cada clique.
def test_codex_alive_cache_avoids_repeat_findchildren(
    qtbot, mcp_prompt_button_factory, monkeypatch,
):
    """Apos a primeira leitura, cache nao re-executa `_codex_target_alive`."""
    call_count = {"n": 0}

    def _fake_alive(self):
        call_count["n"] += 1
        return True

    monkeypatch.setattr(MCPPromptButton, "_codex_target_alive", _fake_alive)
    _, btn = mcp_prompt_button_factory(button_type="Codex", action="send")
    assert call_count["n"] >= 1
    base = call_count["n"]
    for _ in range(5):
        btn._is_codex_alive_cached()
    assert call_count["n"] == base


# #3 - radio_state_getter armazenado como WeakMethod quando bound.
def test_radio_state_getter_stored_as_weakmethod_when_bound(
    qtbot, mcp_prompt_button_factory,
):
    """Bound method -> WeakMethod; lambda -> ref direta."""
    from weakref import WeakMethod

    class _Holder:
        def get_provider(self) -> str:
            return "Claude"

    holder = _Holder()
    _, btn = mcp_prompt_button_factory(
        button_type="type-selector-radio-input",
        action="send",
        radio_state_getter=holder.get_provider,
    )
    assert isinstance(btn._radio_state_getter_ref, WeakMethod)
    _, btn2 = mcp_prompt_button_factory(
        button_type="type-selector-radio-input",
        action="send",
        radio_state_getter=lambda: "Kimi",
    )
    assert not isinstance(btn2._radio_state_getter_ref, WeakMethod)
    assert btn2._resolve_provider() == "Kimi"


# #4 - setEnabled(alive) no __init__ para Codex fixo.
def test_codex_fixed_button_disabled_when_t3_missing(
    qtbot, mcp_prompt_button_factory, codex_alive_factory,
):
    """Codex fixo nasce disabled quando T3 ausente + tooltip curto."""
    codex_alive_factory(False)
    _, btn = mcp_prompt_button_factory(
        button_type="Codex", action="send",
        target_path="terminal-codex-output",
    )
    assert btn.isEnabled() is False
    assert btn.toolTip() == _CODEX_TOAST_SHORT


# #5 - _codex_target_alive endurecido (QLabel com testid NAO passa).
def test_codex_target_alive_rejects_qlabel_placeholder(qtbot):
    """QLabel com testid `terminal-codex-output` NAO satisfaz o gate."""
    from PySide6.QtWidgets import QHBoxLayout, QWidget

    root = QWidget()
    layout = QHBoxLayout(root)
    fake_term = QLabel(root)
    fake_term.setProperty("testid", "terminal-codex-output")
    btn = MCPPromptButton(
        label="probe", button_type="Claude", prompt="x",
        action="send", target_path="terminal-interactive-output",
        parent=root, testid_slug="probe",
    )
    layout.addWidget(btn)
    qtbot.addWidget(root)
    root.show()
    qtbot.waitExposed(root)
    assert btn._codex_target_alive() is False


# #6 - recheck_codex_availability emite signal global.
def test_recheck_codex_availability_emits_signal(
    qtbot, mcp_prompt_button_factory, codex_alive_factory,
):
    """`recheck_codex_availability` emite `codex_availability_changed`."""
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(button_type="Claude", action="send")
    with qtbot.waitSignal(
        signal_bus.codex_availability_changed, timeout=1000,
    ) as blocker:
        btn.recheck_codex_availability()
    assert blocker.args == [True]


# #7 - _resolve_provider snapshot atomico.
def test_resolve_provider_snapshot_atomic(
    qtbot, mcp_prompt_button_factory,
):
    """Cada chamada resolve UMA vez; getter falho cai em default Claude."""
    state = {"provider": "Claude"}
    _, btn = mcp_prompt_button_factory(
        button_type="type-selector-radio-input", action="send",
        radio_state_getter=lambda: state["provider"],
    )
    assert btn._resolve_provider() == "Claude"
    state["provider"] = "Kimi"
    assert btn._resolve_provider() == "Kimi"

    def _bad_getter() -> str:
        raise RuntimeError("bad")

    _, btn2 = mcp_prompt_button_factory(
        button_type="type-selector-radio-input", action="send",
        radio_state_getter=_bad_getter,
    )
    assert btn2._resolve_provider() == "Claude"


# #8 - _block_codex_unavailable emite toast canonico.
def test_block_codex_unavailable_emits_canonical_toast(
    qtbot, mcp_prompt_button_factory, codex_alive_factory, toast_spy,
):
    """_block_codex_unavailable emite o toast canonico (sem fallback).

    Contrato 2026-05-23: radio-input Codex NAO bloqueia no clique (fallback
    central T3->T2 no MainWindow), entao o clique nao produz o toast canonico.
    O emissor de bloqueio canonico permanece e e exercitado diretamente.
    """
    codex_alive_factory(False)
    _, btn = mcp_prompt_button_factory(
        button_type="type-selector-radio-input", action="send",
        radio_state_getter=lambda: "Codex",
    )
    # Clique em radio-input faz fallback: nenhum toast canonico.
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert all(msg != _CODEX_TOAST_CANONICAL for msg, _ in toast_spy.events)
    # O emissor canonico, chamado diretamente, emite o toast canonico.
    btn._block_codex_unavailable(reason="t3_missing")
    canonical_count = sum(
        1 for msg, level in toast_spy.events
        if msg == _CODEX_TOAST_CANONICAL and level == "warning"
    )
    assert canonical_count >= 1


# #9 - radio-input Codex faz fallback (nao bloqueia no clique).
def test_radio_input_codex_falls_back_instead_of_blocking(
    qtbot, mcp_prompt_button_factory, codex_alive_factory,
):
    """Contrato 2026-05-23: radio-input Codex sem T3 NAO bloqueia — emite
    prompt_requested (o fallback central T3->T2 acontece no MainWindow). O
    gate de bloqueio canonico fica restrito ao button_type fixo "Codex".
    """
    codex_alive_factory(False)
    _, btn = mcp_prompt_button_factory(
        button_type="type-selector-radio-input", action="Executar",
        radio_state_getter=lambda: "Codex",
    )
    received: list[dict] = []
    btn.prompt_requested.connect(lambda p: received.append(p))
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert len(received) == 1


# #10 - eventFilter dispara feedback em clique em Codex disabled.
def test_event_filter_feedback_on_disabled_codex_click(
    qtbot, mcp_prompt_button_factory, codex_alive_factory, toast_spy,
):
    """Clicar em botao Codex disabled emite toast curto."""
    codex_alive_factory(False)
    _, btn = mcp_prompt_button_factory(
        button_type="Codex", action="send",
        target_path="terminal-codex-output",
    )
    assert btn.isEnabled() is False
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    short_count = sum(
        1 for msg, level in toast_spy.events
        if msg == _CODEX_TOAST_SHORT and level == "warning"
    )
    assert short_count >= 1


# #11 - caplog valida extras estruturados em codex_blocked.
def test_codex_blocked_logs_structured(
    qtbot, mcp_prompt_button_factory, codex_alive_factory, caplog,
):
    """Campos canonicos: button_id, seed_slug, provider, reason, ts_ns."""
    codex_alive_factory(False)
    _, btn = mcp_prompt_button_factory(
        button_type="type-selector-radio-input", action="send",
        radio_state_getter=lambda: "Codex", testid_slug="hard-11",
    )
    # radio-input nao bloqueia no clique (contrato 2026-05-23); o log
    # estruturado e emitido pelo bloqueio canonico, exercitado diretamente.
    with caplog.at_level(
        logging.WARNING, logger="workflow_app.widgets.mcp_prompt_button",
    ):
        btn._block_codex_unavailable(reason="t3_missing")
    blocked = [r for r in caplog.records if r.getMessage() == "codex_blocked"]
    assert blocked
    rec = blocked[0]
    assert getattr(rec, "button_id", "") != ""
    assert isinstance(getattr(rec, "seed_slug", None), str)
    assert getattr(rec, "provider", None) == "Codex"
    assert getattr(rec, "reason", None) == "t3_missing"
    assert isinstance(getattr(rec, "ts_ns", None), int)


# #12 - caplog valida AUSENCIA de PII (agent_path, prompt).
def test_codex_blocked_log_has_no_pii(
    qtbot, mcp_prompt_button_factory, codex_alive_factory, caplog,
):
    """Campos PROIBIDOS: agent_path, prompt vazariam PII em logs."""
    codex_alive_factory(False)
    _, btn = mcp_prompt_button_factory(
        button_type="type-selector-radio-input", action="send",
        radio_state_getter=lambda: "Codex", testid_slug="hard-12",
    )
    # Bloqueio canonico exercitado diretamente (radio-input faz fallback).
    with caplog.at_level(
        logging.WARNING, logger="workflow_app.widgets.mcp_prompt_button",
    ):
        btn._block_codex_unavailable(reason="t3_missing")
    blocked = [r for r in caplog.records if r.getMessage() == "codex_blocked"]
    assert blocked
    rec = blocked[0]
    assert not hasattr(rec, "agent_path"), "PII proibida no log"
    assert not hasattr(rec, "prompt"), "PII proibida no log"
