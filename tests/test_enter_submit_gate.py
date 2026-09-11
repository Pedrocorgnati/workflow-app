"""Gate de eco do Enter submissor (T1/T2) — anti command-stacking.

Contexto do bug que estes testes travam: o Enter submissor viajava como um
`singleShot` fixo de 250ms depois do bracketed paste, sem prova nenhuma de
que a TUI do outro lado tinha renderizado o texto. Node so le o stdin quando
o event loop dele esta livre; durante o repaint completo que vem depois de um
`/clear`, o paste e o `\r` sao drenados no MESMO tick e o handler do submit
resolve o buffer contra o closure PRE-paste. O submit some em silencio, o
`/clear` fica na linha e o item seguinte cola em cima:

    /clear /skill:slash-executor /loop ...   <- comando inexistente

Cobertura:
  - piso do Enter por Main LLM (claude curto, kimi/qwen longo, +extra
    depois de `/clear`), e canal workspace intocado;
  - gate: sem eco na tela o `\r` NAO sai; com eco sai; estourou o teto sai
    do mesmo jeito (nunca um item mudo);
  - epoch: gate de um dispatch velho nao cospe `\r` em cima do novo;
  - reenvio: comando ainda na linha do cursor => `\r` de novo, ate o cap;
  - compensacao de `/clear` no listener do T1 quando o Main nao e Claude.
"""
from __future__ import annotations

import time

import pytest

from workflow_app.output_panel.output_panel import OutputPanel


class FakeShell:
    """Substitui o PersistentShell: so registra os writes."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def send_raw(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def resize(self, cols: int, rows: int) -> None:  # PTY SIGWINCH — no-op
        pass

    def start(self) -> None:
        pass

    @property
    def enters(self) -> int:
        return self.writes.count(b"\r")


@pytest.fixture()
def panel(qapp, qtbot):
    p = OutputPanel()
    qtbot.addWidget(p)
    p._shell = FakeShell()
    return p


@pytest.fixture()
def workspace_panel(qapp, qtbot):
    p = OutputPanel(workspace_mode=True)
    qtbot.addWidget(p)
    p._shell = FakeShell()
    return p


def _paint(panel: OutputPanel, text: str) -> None:
    """Renderiza `text` na tela do pyte como a TUI faria."""
    panel._stream.feed(text.encode("utf-8"))


class TestEnterFloorPerMainLLM:
    """Fix 3 — o piso do Enter no T1 passa a seguir o Main LLM."""

    def test_claude_keeps_the_short_floor(self, panel):
        panel._main_llm = "claude"
        assert panel._enter_submit_delay_ms("/loop --task x") == 250

    def test_gemini_cli_forks_get_the_long_floor(self, panel):
        for llm in ("kimi", "qwen", "grok", "codex"):
            panel._main_llm = llm
            assert panel._enter_submit_delay_ms("/loop") == 1_000, llm

    def test_first_command_after_clear_gets_the_extra(self, panel):
        panel._main_llm = "kimi"
        panel._last_dispatch_head = "/clear"
        assert panel._enter_submit_delay_ms("/skill:slash-executor /loop") == 3_000

    def test_after_clear_extra_does_not_apply_to_claude(self, panel):
        panel._main_llm = "claude"
        panel._last_dispatch_head = "/clear"
        assert panel._enter_submit_delay_ms("/loop") == 250

    def test_workspace_channel_is_untouched(self, workspace_panel):
        """O T2 ja tinha piso proprio (blue arrow, `delay_ms` do caller);
        o eixo Main nao pode vazar para la."""
        workspace_panel._main_llm = "kimi"
        workspace_panel._last_dispatch_head = "/clear"
        assert workspace_panel._enter_submit_delay_ms("/clear") == 250

    def test_main_llm_signal_updates_the_cache(self, panel):
        panel._on_main_llm_changed("qwen")
        assert panel._main_llm == "qwen"
        panel._on_main_llm_changed("")  # emissao vazia nao apaga o cache
        assert panel._main_llm == "qwen"


class TestSubmitGateNeedle:
    def test_clear_is_long_enough_to_gate(self):
        """`/clear` (6 chars) fica ABAIXO do minimo da telemetria de eco (8)
        e e justamente o comando do bug — o gate usa um minimo mais frouxo."""
        assert OutputPanel._submit_gate_needle("/clear") == "/clear"
        assert OutputPanel._echo_needle("/clear") is None

    def test_needle_is_the_tail_of_the_token_under_the_cursor(self):
        """Bug do `/slash-executor` duplicado: o autocomplete da TUI casa
        por subsequencia enquanto o token esta pela metade na tela. Olhar o
        FIM do ultimo token prova que ele chegou inteiro ao render."""
        needle = OutputPanel._submit_gate_needle(
            "/slash-executor /corgly:questions-rebase"
        )
        assert needle == "tions-rebase"
        assert len(needle) == OutputPanel._SUBMIT_GATE_MAX_CHARS

    def test_short_last_token_falls_back_to_the_longest(self):
        needle = OutputPanel._submit_gate_needle("/skill:slash-executor -x")
        assert needle == "lash-executor"[-OutputPanel._SUBMIT_GATE_MAX_CHARS :]

    def test_short_or_empty_command_has_no_needle(self):
        assert OutputPanel._submit_gate_needle("cd") is None
        assert OutputPanel._submit_gate_needle("   ") is None


class TestGateHoldsEnterUntilEcho:
    """Fix 1 — o `\r` so sai depois que a tela mostra o paste."""

    def test_enter_is_withheld_while_the_screen_has_not_rendered(self, panel):
        far = time.monotonic() + 60
        panel._poll_submit_gate("/clear", 0, far, panel._submit_epoch)
        assert panel._shell.enters == 0, (
            "Enter saiu antes de a TUI ecoar o paste — e exatamente assim "
            "que o submit do /clear era descartado."
        )

    def test_enter_fires_once_the_paste_shows_up(self, panel):
        far = time.monotonic() + 60
        _paint(panel, "> /clear")
        panel._poll_submit_gate("/clear", 0, far, panel._submit_epoch)
        assert panel._shell.enters == 1

    def test_stale_echo_on_screen_does_not_release_the_gate(self, panel):
        """Baseline: exigimos que a contagem AUMENTE. Um `/clear` que sobrou
        do ciclo anterior nao pode liberar o Enter do ciclo atual."""
        _paint(panel, "> /clear\r\n")
        baseline = panel._screen_needle_count("/clear")
        assert baseline == 1
        panel._poll_submit_gate("/clear", baseline, time.monotonic() + 60,
                                panel._submit_epoch)
        assert panel._shell.enters == 0
        _paint(panel, "> /clear")
        panel._poll_submit_gate("/clear", baseline, time.monotonic() + 60,
                                panel._submit_epoch)
        assert panel._shell.enters == 1

    def test_timeout_sends_the_enter_anyway(self, panel):
        """Teto estourado manda o `\r` do mesmo jeito: pior caso e o
        comportamento antigo, nunca um item que fica mudo na fila."""
        panel._poll_submit_gate("/clear", 0, time.monotonic() - 1,
                                panel._submit_epoch)
        assert panel._shell.enters == 1

    def test_command_without_needle_falls_back_to_the_floor(self, panel):
        panel._poll_submit_gate(None, None, time.monotonic() + 60,
                                panel._submit_epoch)
        assert panel._shell.enters == 1

    def test_stale_epoch_never_writes(self, panel):
        panel._poll_submit_gate("/clear", 0, time.monotonic() - 1,
                                panel._submit_epoch - 1)
        assert panel._shell.enters == 0


class TestResendWhenSubmitDidNotTake:
    """Fix 2 — comando ainda na linha do prompt significa submit engolido."""

    def test_resends_while_the_command_sits_at_the_cursor(self, panel):
        _paint(panel, "> /clear")
        panel._verify_submitted("/clear", panel._submit_epoch, 1)
        assert panel._shell.enters == 1

    def test_no_resend_once_the_line_is_gone(self, panel):
        """Depois do submit real o `/clear` limpa a tela; nada a reenviar."""
        _paint(panel, "> /clear")
        _paint(panel, "\x1b[2J\x1b[H")
        panel._verify_submitted("/clear", panel._submit_epoch, 1)
        assert panel._shell.enters == 0

    def test_transcript_above_the_input_box_does_not_trigger_a_resend(self, panel):
        """O comando submetido continua visivel no transcript. So a
        vizinhanca do cursor conta, senao reenviariamos para sempre."""
        _paint(panel, "> /skill:slash-executor /loop\r\n")
        for _ in range(8):
            _paint(panel, "saida do agente\r\n")
        panel._verify_submitted("/skill:slas", panel._submit_epoch, 1)
        assert panel._shell.enters == 0

    def test_resend_is_capped(self, panel):
        _paint(panel, "> /clear")
        panel._verify_submitted("/clear", panel._submit_epoch,
                                panel._ENTER_MAX_RESENDS)
        assert panel._shell.enters == 1  # ultimo permitido, sem reagendar

    def test_stale_epoch_never_resends(self, panel):
        _paint(panel, "> /clear")
        panel._verify_submitted("/clear", panel._submit_epoch - 1, 1)
        assert panel._shell.enters == 0


class TestRunShellCommandWiring:
    def test_dispatch_does_not_write_enter_synchronously(self, panel):
        panel._main_llm = "kimi"
        panel._run_shell_command("/clear")
        assert panel._shell.enters == 0
        assert panel._last_dispatch_head == "/clear"

    def test_each_dispatch_invalidates_the_previous_gate(self, panel):
        first = panel._submit_epoch
        panel._run_shell_command("/clear")
        panel._run_shell_command("/skill:slash-executor /loop")
        assert panel._submit_epoch > first + 1
        # o gate do /clear nao pode mais cuspir \r em cima do comando novo
        panel._poll_submit_gate("/clear", 0, time.monotonic() - 1, first)
        assert panel._shell.enters == 0


class TestListenerClearCompensationOnT1:
    """Fix 3 (lado do listener) — o extra de `/clear` valia so no T2."""

    @pytest.fixture()
    def bar(self, qapp):
        from workflow_app.metrics_bar.metrics_bar import MetricsBar
        from workflow_app.signal_bus import SignalBus
        return MetricsBar(SignalBus())

    def test_claude_on_t1_keeps_the_plain_hold(self, bar):
        bar._main_llm = "claude"
        assert bar._helper_auto_idle_delay_ms("interactive", "/clear") == (
            bar._HELPER_AUTO_IDLE_INTERACTIVE_MS
        )

    def test_kimi_on_t1_gets_the_clear_extra(self, bar):
        bar._main_llm = "kimi"
        assert bar._helper_auto_idle_delay_ms("interactive", "/clear") == (
            bar._HELPER_AUTO_IDLE_INTERACTIVE_MS + bar._CLEAR_WORKSPACE_EXTRA_MS
        )

    def test_workspace_clear_extra_is_preserved(self, bar):
        assert bar._helper_auto_idle_delay_ms("workspace", "/clear") == (
            bar._HELPER_AUTO_IDLE_MS + bar._CLEAR_WORKSPACE_EXTRA_MS
        )

    def test_non_clear_helper_is_untouched(self, bar):
        bar._main_llm = "qwen"
        assert bar._helper_auto_idle_delay_ms("interactive", "/model") == (
            bar._HELPER_AUTO_IDLE_INTERACTIVE_MS
        )


class TestGateEndToEndOnTheEventLoop:
    """Percorre a cadeia real de QTimer: dispatch -> gate -> Enter."""

    def test_enter_lands_after_the_terminal_echoes(self, panel, qtbot):
        panel._main_llm = "claude"
        panel._run_shell_command("/skill:slash-executor /loop --task x")
        assert panel._shell.enters == 0
        _paint(panel, "> /skill:slash-executor /loop --task x")
        qtbot.waitUntil(lambda: panel._shell.enters >= 1, timeout=3_000)
        # o paste continua sendo o primeiro write; o \r vem separado depois
        assert panel._shell.writes[0] != b"\r"

    def test_no_enter_while_the_screen_stays_blank(self, panel, qtbot):
        """Enquanto a TUI nao renderiza, seguramos — e o que impede o `\r`
        de ser resolvido contra o buffer PRE-paste."""
        panel._main_llm = "claude"
        panel._run_shell_command("/skill:slash-executor /loop --task x")
        qtbot.wait(900)
        assert panel._shell.enters == 0


class TestGateSkipsPastesTheTuiDoesNotEcho:
    """Paste multi-linha/longo vira `[Pasted text #1 +N lines]` na TUI: nao
    ha eco para esperar, entao o gate se desliga e o Enter sai no piso."""

    def test_multiline_prompt_has_no_needle(self):
        assert OutputPanel._submit_gate_needle(
            "Analise o repositorio\ne devolva um relatorio"
        ) is None

    def test_long_prompt_has_no_needle(self):
        assert OutputPanel._submit_gate_needle("/x " + "a" * 500) is None

    def test_single_line_slash_command_still_gates(self):
        assert OutputPanel._submit_gate_needle(
            "/slash-executor /corgly:questions-rebase"
        ) is not None
