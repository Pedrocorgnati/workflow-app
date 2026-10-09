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

    def test_kimi_real_command_is_skill_slash_executor(self):
        r = R(REAL_CMD, "kimi")
        assert r.abort_reason is None
        assert r.text == f"/skill:slash-executor {REAL_CMD}"

    def test_qwen_real_command_is_native_slash_executor(self):
        r = R(REAL_CMD, "qwen")
        assert r.abort_reason is None
        assert r.text == f"/slash-executor {REAL_CMD}"

    def test_grok_real_command_is_native_slash_executor_with_runtime(self):
        r = R(REAL_CMD, "grok")
        assert r.abort_reason is None
        assert r.text == (
            f"/slash-executor --delegation-runtime=grok {REAL_CMD}"
        )
        assert r.text != REAL_CMD

    def test_codex_real_command_builds_simulated_prompt(self):
        r = R(REAL_CMD, "codex")
        assert r.abort_reason is None
        assert r.text is not None
        assert r.text != REAL_CMD
        assert "whitelist" in r.text.lower()

    @pytest.mark.parametrize("llm", ["kimi", "qwen", "grok"])
    def test_skill_runtime_missing_command_aborts(self, llm):
        r = R(MISSING_CMD, llm)
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

    def test_goal_custom_prompt_qwen_slash_executor(self):
        r = R(GOAL, "qwen")
        assert r.abort_reason is None
        assert r.text is not None and r.text.startswith("/slash-executor /goal")

    def test_goal_custom_prompt_grok_slash_executor(self):
        r = R(GOAL, "grok")
        assert r.abort_reason is None
        assert r.text is not None and r.text.startswith(
            "/slash-executor --delegation-runtime=grok /goal"
        )

    def test_goal_custom_prompt_codex_builds_prompt(self):
        r = R(GOAL, "codex")
        assert r.abort_reason is None
        assert r.text is not None and "goal-review-prompt.md" in r.text

    def test_skill_codex_aborts_d7(self):
        r = R("/skill:slash-executor /goal x", "codex")
        assert r.text is None
        assert r.abort_reason and "/skill:" in r.abort_reason

    @pytest.mark.parametrize("llm", ["kimi", "qwen"])
    def test_skill_runtime_raw(self, llm):
        r = R("/skill:dual", llm)
        assert r.text == "/skill:dual"
        assert r.abort_reason is None

    def test_skill_claude_raw(self):
        r = R("/skill:dual", "claude")
        assert r.text == "/skill:dual"

    def test_skill_leftover_rewritten_for_grok(self):
        r = R("/skill:slash-executor /cmd:whitelist", "grok")
        assert r.abort_reason is None
        assert r.text == (
            "/slash-executor --delegation-runtime=grok /cmd:whitelist"
        )
        assert "/skill:" not in (r.text or "")

    @pytest.mark.parametrize("llm", ["claude", "kimi", "codex", "qwen", "grok"])
    def test_clear_raw_all_llms(self, llm):
        r = R("/clear", llm)
        assert r.text == "/clear"
        assert r.abort_reason is None

    def test_model_effort_claude_raw(self):
        assert R("/model opus", "claude").text == "/model opus"
        assert R("/effort high", "claude").text == "/effort high"

    @pytest.mark.parametrize("llm", ["kimi", "codex", "qwen", "grok"])
    def test_model_effort_insert_mode_aborts_non_claude_d8(self, llm):
        r = R("/model opus", llm, mode="insert")
        assert r.text is None
        assert r.helper_pulse is False
        assert r.abort_reason

    @pytest.mark.parametrize("llm", ["kimi", "codex", "qwen", "grok"])
    def test_model_effort_dispatch_mode_pulses_non_claude_d8(self, llm):
        r = R("/effort high", llm, mode="dispatch")
        assert r.text is None
        assert r.helper_pulse is True
        assert r.abort_reason is None

    @pytest.mark.parametrize("llm", ["claude", "kimi", "codex", "qwen", "grok"])
    def test_path_passthrough(self, llm):
        r = R("ai-forge/MCP/agents/x.md", llm)
        assert r.text == "ai-forge/MCP/agents/x.md"
        assert r.abort_reason is None

    @pytest.mark.parametrize("llm", ["claude", "kimi", "codex", "qwen", "grok"])
    def test_free_text_passthrough(self, llm):
        r = R("Leia o arquivo e implemente", llm)
        assert r.text == "Leia o arquivo e implemente"
        assert r.abort_reason is None

    def test_idempotent_same_inputs(self):
        # frozen dataclass -> value equality
        assert R(REAL_CMD, "kimi") == R(REAL_CMD, "kimi")
        assert R(REAL_CMD, "qwen") == R(REAL_CMD, "qwen")
        assert R(REAL_CMD, "grok") == R(REAL_CMD, "grok")

    def test_qwen_slash_uses_native_slash_executor(self):
        rendered = R("/corgly:class-review", "qwen", mode="insert")
        kimi = R("/corgly:class-review", "kimi", mode="insert")
        assert rendered.abort_reason is None
        assert rendered.text == "/slash-executor /corgly:class-review"
        assert kimi.text == "/skill:slash-executor /corgly:class-review"

    def test_grok_slash_uses_native_slash_executor_with_runtime(self):
        rendered = R("/corgly:class-review", "grok", mode="insert")
        kimi = R("/corgly:class-review", "kimi", mode="insert")
        qwen = R("/corgly:class-review", "qwen", mode="insert")
        assert rendered.abort_reason is None
        assert rendered.text == (
            "/slash-executor --delegation-runtime=grok /corgly:class-review"
        )
        assert kimi.text == "/skill:slash-executor /corgly:class-review"
        assert qwen.text == "/slash-executor /corgly:class-review"

    @pytest.mark.parametrize("cmd", [REAL_CMD, GOAL])
    @pytest.mark.parametrize("llm", ["kimi", "codex", "qwen", "grok"])
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
    @pytest.mark.parametrize("llm", ["claude", "kimi", "codex", "qwen", "grok"])
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
    @pytest.mark.parametrize(
        "llm,dispatch",
        [
            ("kimi", "_dispatch_kimi_main_command"),
            ("qwen", "_dispatch_qwen_main_command"),
            ("grok", "_dispatch_grok_main_command"),
        ],
    )
    def test_renderer_matches_skill_runtime_dispatcher(self, qapp, qtbot, cmd, llm, dispatch):
        """Parity golden: render_for_llm(mode=dispatch) == skill-runtime dispatcher
        emit (Kimi uses /skill:slash-executor; Qwen uses /slash-executor;
        Grok uses /slash-executor --delegation-runtime=grok)."""
        cq = CommandQueueWidget()
        qtbot.addWidget(cq)
        emitted: list = []
        signal_bus.run_command_in_terminal.connect(lambda t: emitted.append(t))
        getattr(cq, dispatch)(cmd)
        rendered = CommandQueueWidget.render_for_llm(cmd, llm, mode="dispatch")
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
    radios = (win._chk_route_t1, win._chk_route_t2, win._chk_route_t3)
    states = (t1, t2, t3)
    if sum(states) == 1:
        radios[states.index(True)].setChecked(True)
        return
    win._terminal_route_group.setExclusive(False)
    for radio, checked in zip(radios, states, strict=True):
        radio.setChecked(checked)
    win._terminal_route_group.setExclusive(True)


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

    def test_fanout_renders_one_variant_per_destination(self, qapp, qtbot, monkeypatch):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=True, t3=True)
        win._command_queue._main_claude_radio.setChecked(True)
        sent_t1 = _capture(signal_bus.paste_text_in_terminal)
        sent_t2 = _capture(signal_bus.paste_text_in_workspace_terminal)
        sent_t3: list[tuple[str, bool]] = []
        monkeypatch.setattr(
            win,
            "_xterm_inject_text",
            lambda payload, with_enter=False: sent_t3.append(
                (payload, with_enter)
            ) or True,
        )
        report = win._publish_insertion_llm_aware_report("/corgly:class-review")
        assert report.accepted == ("T1", "T2", "T3")
        assert sent_t1 == [("/corgly:class-review",)]
        assert sent_t2[0][0].startswith(
            "/skill:slash-executor /corgly:class-review"
        )
        assert "Command: /corgly:class-review" in sent_t3[0][0]
        assert sent_t3[0][1] is False

    def test_qwen_t1_pastes_slash_executor_like_kimi(self, qapp, qtbot):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_qwen_radio.setVisible(True)
        win._command_queue._main_qwen_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        try:
            ok = win._publish_insertion_llm_aware(REAL_CMD)
            assert ok is True
            assert pastes[-1][0] == f"/slash-executor {REAL_CMD}"
        finally:
            win._modal_check_timer.stop()

    def test_grok_t1_pastes_slash_executor_with_runtime(self, qapp, qtbot):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_grok_radio.setVisible(True)
        win._command_queue._main_grok_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        try:
            ok = win._publish_insertion_llm_aware(REAL_CMD)
            assert ok is True
            assert pastes[-1][0] == (
                f"/slash-executor --delegation-runtime=grok {REAL_CMD}"
            )
        finally:
            win._modal_check_timer.stop()

    def test_sink_failure_isolated_after_successful_render(self, qapp, qtbot, monkeypatch):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=True, t3=True)
        win._command_queue._main_claude_radio.setChecked(True)
        sent_t1 = _capture(signal_bus.paste_text_in_terminal)
        sent_t2 = _capture(signal_bus.paste_text_in_workspace_terminal)
        monkeypatch.setattr(win, "_xterm_inject_text", lambda *_a, **_kw: False)

        report = win._publish_insertion_llm_aware_report("/corgly:class-review")

        assert sent_t1 and sent_t2
        assert report.accepted == ("T1", "T2")
        assert report.failed == ("T3",)
        assert report.errors == ("T3: sink_unavailable",)

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

    def test_corgly_button_is_insertion_only(self, qapp, qtbot):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_claude_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        runs = _capture(signal_bus.run_command_in_terminal)

        _button_by_testid(win, "output-btn-corgly-class-review").click()

        assert pastes == [("/corgly:class-review",)]
        assert runs == []

    def test_corgly_class_select_is_used_only_by_compatible_commands(
        self, qapp, qtbot
    ):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_claude_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)

        filename = "5 - Eu, minha família e minha rotina.docx"
        index = win._corgly_class_select.findText(filename)
        assert index > 0
        win._corgly_class_select.setCurrentIndex(index)

        _button_by_testid(win, "output-btn-corgly-class-review").click()
        _button_by_testid(win, "output-btn-corgly-vocab-text-review").click()
        _button_by_testid(win, "output-btn-corgly-class-create").click()

        assert pastes == [
            (f'/corgly:class-review "{filename}"',),
            (f'/corgly:vocab-text-review "{filename}"',),
            ("/corgly:class-create",),
        ]

    def test_corgly_command_tab_buttons_insert_like_class_create(
        self, qapp, qtbot
    ):
        """Botoes das abas Corgly: paste sem Enter, combo so se o hint aceitar .docx.

        A sub-aba `corgly` hospeda o curso legado e a `corgly2` os comandos
        `corgly2-*`; o comportamento de insercao e o mesmo nas duas.
        """
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_claude_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        runs = _capture(signal_bus.run_command_in_terminal)

        filename = "5 - Eu, minha família e minha rotina.docx"
        index = win._corgly_class_select.findText(filename)
        assert index > 0
        win._corgly_class_select.setCurrentIndex(index)

        class_create = _button_by_testid(win, "output-btn-corgly-class-create")
        flow_host = class_create.parentWidget()
        assert flow_host is not None
        assert flow_host.property("testid") == "output-toolbar-corgly-flow"

        for testid, host_testid in (
            ("output-btn-corgly-change-vocabulary-order", "output-toolbar-corgly-flow"),
            ("output-btn-corgly-enrich-vocabulary", "output-toolbar-corgly-flow"),
            ("output-btn-corgly-clean-progress", "output-toolbar-corgly-flow"),
            ("output-btn-corgly-create-homework", "output-toolbar-corgly-flow"),
            ("output-btn-corgly-picture-parts", "output-toolbar-corgly-flow"),
            (
                "output-btn-corgly-corgly2-divide-vocabulary",
                "output-toolbar-corgly2-flow",
            ),
            (
                "output-btn-corgly-corgly2-look4translation",
                "output-toolbar-corgly2-flow",
            ),
            (
                "output-btn-corgly-corgly2-optimize-phrases",
                "output-toolbar-corgly2-flow",
            ),
            (
                "output-btn-corgly-corgly2-put-false-friends",
                "output-toolbar-corgly2-flow",
            ),
            (
                "output-btn-corgly-desktop-1-subastantives-next-word",
                "output-toolbar-corgly-desktop-flow",
            ),
            (
                "output-btn-corgly-desktop-2-subastantives-identify",
                "output-toolbar-corgly-desktop-flow",
            ),
            (
                "output-btn-corgly-desktop-3-substantive-base",
                "output-toolbar-corgly-desktop-flow",
            ),
            (
                "output-btn-corgly-desktop-4-substantive-polissemia",
                "output-toolbar-corgly-desktop-flow",
            ),
            (
                "output-btn-corgly-desktop-5-substantives-examples",
                "output-toolbar-corgly-desktop-flow",
            ),
            (
                "output-btn-corgly-desktop-6-substantives-translation",
                "output-toolbar-corgly-desktop-flow",
            ),
            (
                "output-btn-corgly-desktop-7-substantives-checkboxes",
                "output-toolbar-corgly-desktop-flow",
            ),
            (
                "output-btn-corgly-desktop-8-substantives-finalize",
                "output-toolbar-corgly-desktop-flow",
            ),
            (
                "output-btn-corgly-desktop-adjectives-next",
                "output-toolbar-corgly-desktop-flow",
            ),
            (
                "output-btn-corgly-desktop-next-verb-phase",
                "output-toolbar-corgly-desktop-flow",
            ),
            ("output-btn-corgly-class-create", "output-toolbar-corgly-flow"),
        ):
            btn = _button_by_testid(win, testid)
            assert btn.parentWidget().property("testid") == host_testid
            btn.click()

        assert pastes == [
            (f'/corgly:change-vocabulary-order "{filename}"',),
            (f'/corgly:enrich-vocabulary "{filename}"',),
            ("/corgly:clean-progress",),
            (f'/corgly:create-homework "{filename}"',),
            (f'/corgly:picture-parts "{filename}"',),
            ("/corgly:corgly2-divide-vocabulary",),
            ("/corgly:corgly2-look4translation",),
            ("/corgly:corgly2-optimize-phrases",),
            ("/corgly:corgly2-put-false-friends",),
            ("/corgly-desktop:1-subastantives-next-word",),
            ("/corgly-desktop:2-subastantives-identify",),
            ("/corgly-desktop:3-substantive-base",),
            ("/corgly-desktop:4-substantive-polissemia",),
            ("/corgly-desktop:5-substantives-examples",),
            ("/corgly-desktop:6-substantives-translation",),
            ("/corgly-desktop:7-substantives-checkboxes",),
            ("/corgly-desktop:8-substantives-finalize",),
            ("/corgly-desktop:adjectives-next",),
            ("/corgly-desktop:next-verb-phase",),
            ("/corgly:class-create",),
        ]
        assert runs == []

    def test_corgly2_all_enqueues_queue_and_does_not_insert(
        self, qapp, qtbot, tmp_path
    ):
        from workflow_app.db.database_manager import db_manager

        db_manager.setup(db_path=str(tmp_path / "test_workflow.db"))
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_claude_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        runs = _capture(signal_bus.run_command_in_terminal)

        _button_by_testid(win, "output-btn-corgly-corgly2-all").click()

        assert pastes == []
        assert runs == []
        assert [item.command_text() for item in win._command_queue._items] == [
            "/corgly:corgly2-divide-vocabulary",
            "/clear",
            "/corgly:corgly2-put-false-friends",
            "/clear",
            "/corgly:corgly2-optimize-phrases",
            "/clear",
        ]

    def test_substantives_enqueues_queue_and_does_not_insert(
        self, qapp, qtbot, tmp_path
    ):
        from workflow_app.db.database_manager import db_manager

        db_manager.setup(db_path=str(tmp_path / "test_workflow.db"))
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_claude_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        runs = _capture(signal_bus.run_command_in_terminal)

        _button_by_testid(win, "output-btn-corgly-substantives").click()

        assert pastes == []
        assert runs == []
        assert [item.command_text() for item in win._command_queue._items] == list(
            win._SUBSTANTIVES_ALL_QUEUE
        )

    def test_empty_corgly_class_selection_keeps_command_without_argument(
        self, qapp, qtbot
    ):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        win._command_queue._main_claude_radio.setChecked(True)
        pastes = _capture(signal_bus.paste_text_in_terminal)

        assert win._corgly_class_select.currentIndex() == 0
        assert win._corgly_class_select.currentText() == ""
        _button_by_testid(win, "output-btn-corgly-class-update").click()

        assert pastes == [("/corgly:class-update",)]

    def test_corgly_strategy_and_rule_buttons_insert_paths_without_enter(
        self, qapp, qtbot
    ):
        win = _new_window(qtbot)
        _set_route(win, t1=True, t2=False, t3=False)
        pastes = _capture(signal_bus.paste_text_in_terminal)
        runs = _capture(signal_bus.run_command_in_terminal)

        strategy = win._corgly_strategy_buttons[0]
        rule = win._corgly_rule_buttons[0]
        strategy.click()
        rule.click()

        assert pastes == [
            (str(strategy.property("corgly_path")),),
            (str(rule.property("corgly_path")),),
        ]
        assert qapp.clipboard().text() == str(rule.property("corgly_path"))
        assert runs == []

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
