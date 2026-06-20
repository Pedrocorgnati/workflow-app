"""Tests for the LLM-aware insertion routing feature.

Source of truth:
  - blacksmith/brainstorm-mcp/06-15-insertions-subtab-llm-routing.md
  - blacksmith/brainstorm-mcp/06-15-insertions-subtab-llm-routing-tasks.md

Covers:
  - Task 09: render_for_llm renderer (all first-token classes x claude/kimi/codex).
  - Task 01: characterization — render_for_llm is pure (no toast); insertion never
    emits run_command_* (paste/no-Enter); renderer matches the queue dispatchers
    (mode="dispatch") for the non-divergent cases (parity golden for the gated Task 11).
  - Task 10: transporter _publish_insertion_llm_aware (T1 render, Phase-1 fan-out
    guard, Notes D6, abort-with-toast, no-destination no-op).

Uses real on-disk commands for determinism:
  - /cmd:whitelist  -> .claude/commands/cmd/whitelist.md (exists)
  - /goal           -> ai-forge/custom-prompts/goal-review-prompt.md (exists)
  - /cmd:zzz-nonexistent-xyz -> absent (abort path)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.signal_bus import signal_bus

R = CommandQueueWidget.render_for_llm

REAL_CMD = "/cmd:whitelist"
MISSING_CMD = "/cmd:zzz-nonexistent-xyz"
GOAL = "/goal rode o prompt em ai-forge/custom-prompts/goal-review-prompt.md"


# ──────────────────────────────────────────────────────────────────────────────
# Task 09 — renderer branches
# ──────────────────────────────────────────────────────────────────────────────
class TestRenderForLlm:
    def test_claude_slash_is_raw(self):
        r = R(REAL_CMD, "claude")
        assert r.text == REAL_CMD
        assert r.abort_reason is None

    def test_claude_missing_command_still_raw(self):
        # Claude REPL is the resolver; never aborts.
        r = R(MISSING_CMD, "claude")
        assert r.text == MISSING_CMD
        assert r.abort_reason is None

    def test_kimi_real_command_is_skill_adaptation(self):
        r = R(REAL_CMD, "kimi")
        assert r.abort_reason is None
        assert r.text is not None and r.text.startswith("/skill:")
        assert "cmd:whitelist" in r.text

    def test_codex_real_command_builds_simulated_prompt(self):
        r = R(REAL_CMD, "codex")
        assert r.abort_reason is None
        assert r.text is not None
        assert r.text != REAL_CMD
        assert "whitelist" in r.text.lower()

    def test_kimi_missing_command_aborts(self):
        r = R(MISSING_CMD, "kimi")
        assert r.text is None
        assert r.abort_reason and "nao encontrado" in r.abort_reason

    def test_codex_missing_command_aborts(self):
        r = R(MISSING_CMD, "codex")
        assert r.text is None
        assert r.abort_reason and "nao encontrado" in r.abort_reason

    def test_goal_custom_prompt_claude_raw(self):
        r = R(GOAL, "claude")
        assert r.text == GOAL

    def test_goal_custom_prompt_kimi_slash_executor(self):
        r = R(GOAL, "kimi")
        assert r.abort_reason is None
        assert r.text is not None and r.text.startswith("/skill:slash-executor /goal")

    def test_goal_custom_prompt_codex_builds_prompt(self):
        r = R(GOAL, "codex")
        assert r.abort_reason is None
        assert r.text is not None and "goal-review-prompt.md" in r.text

    def test_skill_codex_aborts_d7(self):
        r = R("/skill:slash-executor /goal x", "codex")
        assert r.text is None
        assert r.abort_reason and "/skill:" in r.abort_reason

    def test_skill_kimi_raw(self):
        r = R("/skill:dual", "kimi")
        assert r.text == "/skill:dual"
        assert r.abort_reason is None

    def test_skill_claude_raw(self):
        r = R("/skill:dual", "claude")
        assert r.text == "/skill:dual"

    @pytest.mark.parametrize("llm", ["claude", "kimi", "codex"])
    def test_clear_raw_all_llms(self, llm):
        r = R("/clear", llm)
        assert r.text == "/clear"
        assert r.abort_reason is None

    def test_model_effort_claude_raw(self):
        assert R("/model opus", "claude").text == "/model opus"
        assert R("/effort high", "claude").text == "/effort high"

    @pytest.mark.parametrize("llm", ["kimi", "codex"])
    def test_model_effort_insert_mode_aborts_non_claude_d8(self, llm):
        r = R("/model opus", llm, mode="insert")
        assert r.text is None
        assert r.helper_pulse is False
        assert r.abort_reason

    @pytest.mark.parametrize("llm", ["kimi", "codex"])
    def test_model_effort_dispatch_mode_pulses_non_claude_d8(self, llm):
        r = R("/effort high", llm, mode="dispatch")
        assert r.text is None
        assert r.helper_pulse is True
        assert r.abort_reason is None

    @pytest.mark.parametrize("llm", ["claude", "kimi", "codex"])
    def test_path_passthrough(self, llm):
        r = R("ai-forge/MCP/agents/x.md", llm)
        assert r.text == "ai-forge/MCP/agents/x.md"
        assert r.abort_reason is None

    @pytest.mark.parametrize("llm", ["claude", "kimi", "codex"])
    def test_free_text_passthrough(self, llm):
        r = R("Leia o arquivo e implemente", llm)
        assert r.text == "Leia o arquivo e implemente"
        assert r.abort_reason is None

    def test_idempotent_same_inputs(self):
        # frozen dataclass -> value equality
        assert R(REAL_CMD, "kimi") == R(REAL_CMD, "kimi")

    @pytest.mark.parametrize("cmd", [REAL_CMD, GOAL])
    @pytest.mark.parametrize("llm", ["kimi", "codex"])
    def test_no_wf_channel_override_assignment_in_text(self, cmd, llm):
        # Invariant (§8.1): never PREFIX/INJECT a channel-override ASSIGNMENT
        # (WF_CHANNEL_OVERRIDE=<value>) into the pasted text. The Codex simulated
        # prompt may MENTION the env var name in its instructions (canonical
        # builder behavior) — that is not the anti-pattern.
        r = R(cmd, llm)
        if r.text:
            assert "WF_CHANNEL_OVERRIDE=" not in r.text

    @pytest.mark.parametrize(
        "cmd",
        [REAL_CMD, MISSING_CMD, GOAL, "/skill:dual", "/clear", "path/x", "free text"],
    )
    @pytest.mark.parametrize("llm", ["claude", "kimi", "codex"])
    def test_invariant_exclusivity_of_return(self, cmd, llm):
        r = R(cmd, llm)
        # never both set
        assert not (r.text is not None and r.abort_reason is not None)
        # with a real payload, never both None (except /model//effort pulse cases,
        # not exercised here)
        assert not (r.text is None and r.abort_reason is None)


# ──────────────────────────────────────────────────────────────────────────────
# Task 01 — characterization / purity / parity golden
# ──────────────────────────────────────────────────────────────────────────────
class TestCharacterization:
    def test_render_for_llm_is_pure_no_toast(self):
        captured: list = []
        signal_bus.toast_requested.connect(lambda *a: captured.append(a))
        R(MISSING_CMD, "codex")  # an abort path: must NOT toast (caller does)
        R(REAL_CMD, "kimi")
        assert captured == []

    @pytest.mark.parametrize("cmd", [REAL_CMD, GOAL, "/clear", "texto livre"])
    def test_renderer_matches_kimi_dispatcher(self, qapp, qtbot, cmd):
        """Parity golden: render_for_llm(mode=dispatch) == _dispatch_kimi_main_command
        emit, for the non-divergent first-token classes (gate for the gated Task 11)."""
        cq = CommandQueueWidget()
        qtbot.addWidget(cq)
        emitted: list = []
        signal_bus.run_command_in_terminal.connect(lambda t: emitted.append(t))
        cq._dispatch_kimi_main_command(cmd)
        rendered = CommandQueueWidget.render_for_llm(cmd, "kimi", mode="dispatch")
        assert rendered.text is not None
        assert emitted and emitted[-1] == rendered.text

    @pytest.mark.parametrize("cmd", [REAL_CMD, GOAL, "/clear", "texto livre"])
    def test_renderer_matches_codex_dispatcher_t1(self, qapp, qtbot, cmd):
        cq = CommandQueueWidget()
        qtbot.addWidget(cq)
        emitted: list = []
        signal_bus.run_command_in_terminal.connect(lambda t: emitted.append(t))
        cq._dispatch_codex_command(cmd, to_t1=True)
        rendered = CommandQueueWidget.render_for_llm(cmd, "codex", mode="dispatch")
        assert rendered.text is not None
        assert emitted and emitted[-1] == rendered.text


# ──────────────────────────────────────────────────────────────────────────────
# Task 10 — transporter
# ──────────────────────────────────────────────────────────────────────────────
def _new_window(qtbot):
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _set_route(win, *, t1, t2, t3):
    win._chk_route_t1.setChecked(t1)
    win._chk_route_t2.setChecked(t2)
    win._chk_route_t3.setChecked(t3)


def _capture(signal):
    out: list = []
    signal.connect(lambda *a: out.append(a))
    return out


def _button_by_testid(win, testid: str):
    from PySide6.QtWidgets import QPushButton

    for btn in win.findChildren(QPushButton):
        if btn.property("testid") == testid:
            return btn
    raise AssertionError(f"button not found: {testid}")


class TestPublishInsertionLlmAware:
    def test_neutral_path_passthrough(self, qapp, qtbot):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        ok = win._publish_insertion_llm_aware("ai-forge/MCP/agents/x.md")
        assert ok is True
        assert pastes and pastes[-1][0] == "ai-forge/MCP/agents/x.md"

    def test_slash_t1_claude_pastes_raw(self, qapp, qtbot):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_claude_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        ok = win._publish_insertion_llm_aware(REAL_CMD)
        assert ok is True
        assert pastes[-1][0] == REAL_CMD

    def test_slash_t1_kimi_pastes_adaptation(self, qapp, qtbot):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._force_kimi_chk.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        ok = win._publish_insertion_llm_aware(REAL_CMD)
        assert ok is True
        assert pastes[-1][0].startswith("/skill:")

    def test_slash_t1_codex_pastes_prompt(self, qapp, qtbot):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_codex_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        ok = win._publish_insertion_llm_aware(REAL_CMD)
        assert ok is True
        assert pastes[-1][0] != REAL_CMD and "whitelist" in pastes[-1][0].lower()

    def test_fanout_guard_aborts_with_toast(self, qapp, qtbot):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=True, t3=False)
        win._command_queue._main_claude_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        toasts = _capture(signal_bus.toast_requested)
        ok = win._publish_insertion_llm_aware(REAL_CMD)
        assert ok is False
        assert not pastes
        assert toasts and "Fan-out" in toasts[-1][0]

    def test_missing_command_under_codex_aborts_with_toast(self, qapp, qtbot):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_codex_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        toasts = _capture(signal_bus.toast_requested)
        ok = win._publish_insertion_llm_aware(MISSING_CMD)
        assert ok is False
        assert not pastes
        assert toasts and "abortada" in toasts[-1][0].lower()

    def test_notes_t1_copies_rendered_to_clipboard(self, qapp, qtbot):
        from PySide6.QtWidgets import QApplication

        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._chk_notes_t1.setChecked(True)
        win._command_queue._force_kimi_chk.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        ok = win._publish_insertion_llm_aware(REAL_CMD)
        assert ok is True
        assert not pastes  # Notes diverts to clipboard, no terminal paste
        assert QApplication.clipboard().text().startswith("/skill:")

    def test_no_destination_is_noop(self, qapp, qtbot):
        win = _new_window(qtbot)
        _set_route(win, t1=False, t2=False, t3=False)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        ok = win._publish_insertion_llm_aware(REAL_CMD)
        assert ok is False
        assert not pastes

    def test_insertion_never_emits_run_command(self, qapp, qtbot):
        """paste/no-Enter semantics: an insertion never uses run_command_* (Enter)."""
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_claude_radio.setChecked(True)
        runs = _capture(signal_bus.run_command_in_terminal)
        win._publish_insertion_llm_aware(REAL_CMD)
        assert not runs

    def test_cmd_subtab_listener_debug_button_uses_codex_renderer(self, qapp, qtbot):
        """CMD subtab buttons must not paste raw Claude slash under Main Codex."""
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_codex_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)

        try:
            _button_by_testid(win, "queue-btn-cmd-debug-green").click()
        finally:
            Path("blacksmith/listeners/.debug-counter").unlink(missing_ok=True)
            for path in (Path("blacksmith/listeners"), Path("blacksmith")):
                try:
                    path.rmdir()
                except OSError:
                    pass

        assert pastes
        payload = pastes[-1][0]
        assert payload != "/listener:analyse --green"
        assert "Command: /listener:analyse --green" in payload

    def test_personal_subtab_button_uses_codex_renderer(self, qapp, qtbot):
        """PERSONAL subtab buttons share the same Codex insertion path."""
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_codex_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)

        _button_by_testid(win, "queue-btn-personal-cv-create").click()

        assert pastes
        payload = pastes[-1][0]
        assert payload != "/curriculum:create"
        assert "Command: /curriculum:create" in payload
