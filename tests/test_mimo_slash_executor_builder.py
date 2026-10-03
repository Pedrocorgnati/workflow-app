"""Builder da seta azul MiMo (`_build_mimo_slash_executor_invocation`).

Trava o contrato do payload descrito em ai-forge/rules/mimo-code-cli-contract.md:
`/slash-executor --delegation-runtime=mimo /<ns:cmd> <args> ` (sem espaco no
inicio, exatamente um no fim), idempotente, com reescrita das formas
`/skill:`, e recusa explicita de payload slash com "!`" (o CLI mimocode expande
shell no host ao carregar o template do comando). Item 006 do loop
10-03-systemforge-mimo-llm-paralela.
"""
from __future__ import annotations

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.signal_bus import signal_bus

_PREFIX = "/slash-executor --delegation-runtime=mimo "


@pytest.fixture()
def widget(qapp, qtbot, monkeypatch) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    w.show()
    # O radio mimo fica atras do switch do roster MiMo; o teste liga direto.
    w._main_radio_visible["mimo"] = True
    w._main_mimo_radio.setChecked(True)
    # O preflight de CLI/credencial depende do host; nao e o alvo aqui.
    monkeypatch.setattr(w, "_orch_preflight_main_credential", lambda *_a, **_k: None)
    return w


def _builder():
    return CommandQueueWidget._build_mimo_slash_executor_invocation


@pytest.mark.parametrize(
    ("cmd_text", "recovery_mode"),
    [
        ("/qa:trace --module 3", False),
        ("/skill:qa:trace --module 3", False),
        ("/skill:slash-executor /daily", False),
        ("/tools:listener-recovery --channel interactive", True),
    ],
)
def test_builder_is_idempotent(cmd_text, recovery_mode):
    b = _builder()
    once = b(cmd_text, recovery_mode=recovery_mode)
    assert b(once, recovery_mode=recovery_mode) == once


def test_builder_rewrites_skill_forms():
    b = _builder()
    assert b("/skill:qa:trace --module 3") == f"{_PREFIX}/qa:trace --module 3 "
    assert b("/skill:slash-executor /daily") == f"{_PREFIX}/daily "


@pytest.mark.parametrize("cmd_text", ["  /prd-create", "/prd-create   "])
def test_builder_no_leading_space_and_single_trailing_space(cmd_text):
    assert _builder()(cmd_text) == f"{_PREFIX}/prd-create "


def test_builder_refuses_shell_expansion_token():
    with pytest.raises(ValueError) as exc:
        _builder()("/qa:trace !`printf X`")
    msg = str(exc.value)
    assert "!`" in msg
    assert "mimo-code-cli-contract.md" in msg


def test_builder_leaves_free_text_unchanged():
    assert _builder()("texto livre") == "texto livre"


def test_mimo_is_a_delegation_runtime():
    assert "mimo" in CommandQueueWidget._DELEGATION_RUNTIMES


def test_dispatch_refuses_shell_expansion_token(widget):
    emitted: list[str] = []
    toasts: list[tuple[str, str]] = []
    handler = lambda m, k: toasts.append((m, k))  # noqa: E731
    signal_bus.run_command_in_terminal.connect(emitted.append)
    signal_bus.toast_requested.connect(handler)
    try:
        ok = widget._dispatch_mimo_main_command("/qa:trace !`printf X`")
    finally:
        signal_bus.run_command_in_terminal.disconnect(emitted.append)
        signal_bus.toast_requested.disconnect(handler)
    assert ok is False
    assert emitted == []
    assert len(toasts) == 1
    message, kind = toasts[0]
    assert kind == "warning"
    assert "!`" in message
