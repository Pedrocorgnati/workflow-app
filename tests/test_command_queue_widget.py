"""
Tests for CommandQueueWidget (module-10/TASK-2).

Covers:
  - Initial state shows empty widget (Nenhum pipeline configurado)
  - load_pipeline() populates list and hides empty widget
  - clear_queue() returns to empty state
  - Signal slots update item statuses (command_started, completed, failed, skipped)
  - remove_requested removes the item from the list
  - skip_requested marks item as PULADO
  - Width is within min/max bounds (200–360px)
"""
from __future__ import annotations

import json

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.domain import (
    CommandSpec,
    CommandStatus,
    EffortLevel,
    ModelName,
)
from workflow_app.signal_bus import signal_bus


@pytest.fixture()
def specs() -> list[CommandSpec]:
    return [
        CommandSpec("/prd-create", ModelName.OPUS, position=1),
        CommandSpec("/hld-create", ModelName.SONNET, position=2),
        CommandSpec("/lld-create", ModelName.SONNET, position=3),
    ]


@pytest.fixture()
def widget(qapp, qtbot) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    w.show()
    return w


class TestCommandQueueWidgetInitialState:
    def test_width_within_bounds(self, widget):
        """Widget width is within min/max bounds (200–460px).

        Upper bound raised from 360→400 by TASK-050: the new DCP buttons
        (`DCP: Build Module Pipeline` / `DCP: Specific-Flow`) have spec-
        mandated literal labels wider than the previous legacy buttons.
        Raised 400→440 by TASK-1 layout refactor (2026-05-12): autocast e
        schedule-autocast btns migraram do metrics_bar para a play bar.
        Raised 440→460 (2026-05-12): wrapper QWidget `_play_btn_container`
        em volta de `queue-btn-play-next` adiciona overhead minimo de
        layout (~7px) somado ao minimo intrinseco do botao.
        """
        assert 200 <= widget.width() <= 460

    def test_empty_widget_visible(self, widget):
        """Empty state widget is visible initially."""
        assert widget._empty_widget.isVisible()

    def test_list_widget_hidden(self, widget):
        """List widget is hidden initially."""
        assert not widget._list_widget.isVisible()

    def test_no_items_initially(self, widget):
        """No CommandItemWidget items initially."""
        assert len(widget._items) == 0


class TestCommandQueueWidgetLoadPipeline:
    def test_load_shows_list(self, widget, specs):
        """load_pipeline shows list widget and hides empty state."""
        widget.load_pipeline(specs)
        assert widget._list_widget.isVisible()
        assert not widget._empty_widget.isVisible()

    def test_load_creates_items(self, widget, specs):
        """load_pipeline creates one CommandItemWidget per spec."""
        widget.load_pipeline(specs)
        assert len(widget._items) == 3

    def test_load_items_have_correct_names(self, widget, specs):
        """Each loaded item displays the correct command name."""
        widget.load_pipeline(specs)
        names = [item._name_label.text() for item in widget._items]
        assert "/prd-create" in names
        assert "/hld-create" in names
        assert "/lld-create" in names

    def test_reload_replaces_existing_items(self, widget, specs):
        """Calling load_pipeline again replaces all items."""
        widget.load_pipeline(specs)
        widget.load_pipeline(specs[:1])
        assert len(widget._items) == 1


class TestCommandQueueWidgetClear:
    def test_clear_queue_returns_to_empty(self, widget, specs):
        """clear_queue() makes empty widget visible and hides list."""
        widget.load_pipeline(specs)
        widget.clear_queue()
        assert widget._empty_widget.isVisible()
        assert not widget._list_widget.isVisible()

    def test_clear_queue_removes_items(self, widget, specs):
        """clear_queue() empties the _items list."""
        widget.load_pipeline(specs)
        widget.clear_queue()
        assert len(widget._items) == 0


class TestCommandQueueWidgetStatusUpdates:
    def test_command_started_sets_executando(self, widget, specs):
        """command_started signal sets item status to EXECUTANDO."""
        widget.load_pipeline(specs)
        widget._on_command_started(0)  # index 0 → position 1
        assert widget._items[0]._status == CommandStatus.EXECUTANDO

    def test_command_completed_sets_concluido(self, widget, specs):
        """command_completed signal sets item status to CONCLUIDO."""
        widget.load_pipeline(specs)
        widget._on_command_completed(1)  # index 1 → position 2
        assert widget._items[1]._status == CommandStatus.CONCLUIDO

    def test_command_failed_sets_erro(self, widget, specs):
        """command_failed signal sets item status to ERRO."""
        widget.load_pipeline(specs)
        widget._on_command_failed(2, "timeout")  # index 2 → position 3
        assert widget._items[2]._status == CommandStatus.ERRO

    def test_command_skipped_sets_pulado(self, widget, specs):
        """command_skipped signal sets item status to PULADO."""
        widget.load_pipeline(specs)
        widget._on_command_skipped(0)  # index 0 → position 1
        assert widget._items[0]._status == CommandStatus.PULADO


class TestCommandQueueWidgetRemove:
    def test_remove_requested_removes_item(self, widget, specs):
        """_on_remove_requested removes item from list."""
        widget.load_pipeline(specs)
        widget._on_remove_requested(1)  # position 1
        assert len(widget._items) == 2

    def test_remove_last_item_shows_empty(self, widget):
        """Removing the last item returns to empty state."""
        single_spec = [CommandSpec("/cmd", ModelName.OPUS, position=1)]
        widget.load_pipeline(single_spec)
        widget._on_remove_requested(1)
        assert widget._empty_widget.isVisible()


# ────────────────────────────────────── Error flow (GAP-011) ─── #

class TestCommandQueueWidgetErrorFlow:
    """Error row signals are connected and cancel shows ConfirmCancelModal (GAP-011 fix)."""

    def test_retry_requested_resets_item_to_pendente(self, widget, specs):
        """retry_requested resets the failed item status to PENDENTE."""
        widget.load_pipeline(specs)
        # Manually set item to ERRO first
        item = widget._items[0]
        item.set_status(CommandStatus.ERRO)

        widget._on_retry_requested(1)  # position 1

        assert item._status == CommandStatus.PENDENTE

    def test_cancel_requested_shows_confirm_modal(self, widget, specs, monkeypatch):
        """_on_cancel_requested shows ConfirmCancelModal before cancelling."""
        from unittest.mock import MagicMock, patch
        widget.load_pipeline(specs)

        with patch(
            "workflow_app.command_queue.command_queue_widget.ConfirmCancelModal"
        ) as MockModal:
            mock_instance = MagicMock()
            mock_instance.exec.return_value = MockModal.Accepted
            MockModal.return_value = mock_instance

            widget._on_cancel_requested()

            MockModal.assert_called_once()
            mock_instance.exec.assert_called_once()

    def test_pipeline_error_with_message_marks_executing_item(self, widget, specs):
        """_on_pipeline_error_with_message sets EXECUTANDO item to ERRO with message."""
        widget.load_pipeline(specs)
        item = widget._items[1]  # position 2
        item.set_status(CommandStatus.EXECUTANDO)

        widget._on_pipeline_error_with_message(0, "Command timed out")

        assert item._status == CommandStatus.ERRO

    def test_error_row_signals_exist_on_item(self, widget):
        """After load_pipeline(), item has retry_requested and cancel_requested signals."""
        single_spec = [CommandSpec("/cmd", ModelName.OPUS, position=1)]
        widget.load_pipeline(single_spec)
        item = widget._items[0]

        assert hasattr(item, "retry_requested")
        assert hasattr(item, "cancel_requested")


# ─── Step button (queue-btn-play-next) — helpers go to terminal ─────────── #

class TestStepBtnDispatchesHelpersToTerminal:
    """Regression guard: queue-btn-play-next MUST send /clear, /model X, /effort Y
    to the terminal — they are NOT queue helpers in the manual path.

    Why this exists: the manual path uses
    `signal_bus.run_command_in_terminal.emit(text)` which sends text to the
    already-open Claude Code session — `/clear` is the ONLY way to clear that
    session's context, and `/model X` / `/effort Y` are the ONLY way to switch
    the session's model/effort. Skipping them silently breaks the canonical use
    case (manual stepping through bucketed loops).
    """

    @pytest.fixture()
    def helper_specs(self) -> list[CommandSpec]:
        return [
            CommandSpec("/clear", ModelName.SONNET, position=1),
            CommandSpec("/model opus", ModelName.OPUS, position=2),
            CommandSpec("/effort high", ModelName.OPUS, EffortLevel.HIGH, position=3),
            CommandSpec("/prd-create", ModelName.OPUS, EffortLevel.HIGH, position=4),
        ]

    def _captured_emissions(self, widget, helper_specs):
        """Click play-next once per item; return the texts emitted to terminal."""
        emitted: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted.append)
        try:
            widget.load_pipeline(helper_specs)
            for _ in helper_specs:
                widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted.append)
        return emitted

    def test_clear_is_dispatched_to_terminal(self, widget, helper_specs):
        emitted = self._captured_emissions(widget, helper_specs)
        assert "/clear" in emitted, (
            "/clear must be sent to terminal — it's the only way to clear context "
            "in the manual play-next path. Do not skip it."
        )

    def test_model_helper_is_dispatched_to_terminal(self, widget, helper_specs):
        emitted = self._captured_emissions(widget, helper_specs)
        assert any(t.startswith("/model opus") for t in emitted), (
            "/model X must be sent to terminal in the manual path — it's the only "
            "way to switch the session's model."
        )

    def test_effort_helper_is_dispatched_to_terminal(self, widget, helper_specs):
        emitted = self._captured_emissions(widget, helper_specs)
        assert any(t.startswith("/effort high") for t in emitted), (
            "/effort Y must be sent to terminal in the manual path — it's the only "
            "way to switch the session's effort."
        )

    def test_real_command_still_dispatched_after_helpers(self, widget, helper_specs):
        emitted = self._captured_emissions(widget, helper_specs)
        assert any(t.startswith("/prd-create") for t in emitted), (
            "Real command must also be dispatched after helpers."
        )

    def test_each_click_advances_exactly_one_item(self, widget, helper_specs):
        """Manual path is step-by-step: 4 items require 4 clicks, not 1.

        Checks `is_pending_run()` (the canonical queue check), not `_status`.
        Status only transitions when a real subprocess fires lifecycle callbacks;
        in the manual path there is no subprocess, so status stays PENDENTE — but
        `_is_sent=True` removes the item from the pending queue.
        """
        widget.load_pipeline(helper_specs)
        pending_after_each_click = []
        for _ in helper_specs:
            widget._on_step_btn_clicked()
            pending_after_each_click.append(
                [item.is_pending_run() for item in widget._items]
            )

        # After click N, items 0..N-1 must NOT be pending; item N..end must be pending.
        for click_idx, pendings in enumerate(pending_after_each_click):
            for i, is_pending in enumerate(pendings):
                if i <= click_idx:
                    assert not is_pending, (
                        f"After click {click_idx + 1}, item {i} should have left the "
                        f"pending queue. Skip-helpers regression suspected."
                    )
                else:
                    assert is_pending, (
                        f"After click {click_idx + 1}, item {i} should still be pending. "
                        f"Step button advanced more than one item."
                    )

    def test_helper_marks_item_as_sent(self, widget, helper_specs):
        """After a /clear click, the /clear item must leave the pending queue.

        Otherwise next click re-fires the same item infinitely — the bug this
        whole regression suite guards against would manifest as a different
        symptom (terminal flooded with /clear).
        """
        widget.load_pipeline(helper_specs)
        widget._on_step_btn_clicked()
        assert not widget._items[0].is_pending_run(), (
            "/clear item must leave pending queue after dispatch — "
            "otherwise next click re-fires the same item infinitely."
        )


class TestClearMirrorToWorkspace:
    """When Use Kimi checkbox is active, /clear must reach BOTH terminals
    via every dispatch route (per-item green button, "Rodar próximo",
    autocast). Bug repro: previously only the step_btn path was wired."""

    @pytest.fixture()
    def clear_specs(self) -> list[CommandSpec]:
        return [CommandSpec("/clear", ModelName.SONNET, position=1)]

    def test_step_btn_clear_with_kimi_checked_emits_to_both(self, widget, clear_specs):
        """The "Rodar próximo" button path."""
        emitted_interactive: list[str] = []
        emitted_workspace: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        try:
            widget._use_kimi_chk.setChecked(True)
            widget.load_pipeline(clear_specs)
            widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert "/clear" in emitted_interactive
        assert "/clear" in emitted_workspace

    def test_per_item_green_button_clear_with_kimi_checked_emits_to_both(
        self, widget, clear_specs
    ):
        """The per-item green ▶ play button path — bug repro path. Without
        the mirror connection in `_make_item`, /clear here only reaches the
        interactive terminal regardless of the checkbox state."""
        emitted_interactive: list[str] = []
        emitted_workspace: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        try:
            widget._use_kimi_chk.setChecked(True)
            widget.load_pipeline(clear_specs)
            # Simulate the per-item green button click (NOT step_btn)
            widget._items[0]._on_run_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert "/clear" in emitted_interactive
        assert "/clear" in emitted_workspace, (
            "/clear via per-item button must mirror to workspace when Use Kimi "
            "is active. Repro: previously only step_btn path had this branch."
        )

    def test_per_item_clear_without_kimi_checked_does_not_mirror(
        self, widget, clear_specs
    ):
        """Sanity: when checkbox is OFF, /clear must NOT reach workspace."""
        emitted_workspace: list[str] = []
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        try:
            widget._use_kimi_chk.setChecked(False)
            widget.load_pipeline(clear_specs)
            widget._items[0]._on_run_clicked()
        finally:
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert emitted_workspace == [], (
            "/clear must not mirror to workspace when checkbox is off."
        )

    def test_per_item_non_clear_does_not_mirror_even_with_kimi_checked(
        self, widget, qapp
    ):
        """Sanity: only /clear mirrors. Other commands route via the
        kimi-button (blue) when applicable, never via the mirror."""
        non_clear_specs = [CommandSpec("/prd-create", ModelName.OPUS, position=1)]
        emitted_workspace: list[str] = []
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        try:
            widget._use_kimi_chk.setChecked(True)
            widget.load_pipeline(non_clear_specs)
            widget._items[0]._on_run_clicked()
        finally:
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert emitted_workspace == [], (
            "Non-/clear commands must not mirror via the run_in_terminal signal."
        )


class TestKimiBlueArrowDelay:
    """Blue-arrow Kimi dispatch must use the dedicated signal so MetricsBar
    can track it as a command dispatch (bumps workspace epoch + releases
    idle lock). Without this, helper auto-idle scheduled before the blue
    arrow click would fire mid-command and lock the dot green prematurely.
    """

    @pytest.fixture()
    def kimi_specs(self) -> list[CommandSpec]:
        return [CommandSpec("/qa:prep", ModelName.SONNET, position=1)]

    def test_blue_arrow_emits_kimi_dispatched_signal(self, widget, qapp, kimi_specs):
        """Click on blue arrow → fires kimi_blue_arrow_dispatched with the
        adapted prompt + delay. Default delay is 1000ms; bumped to 3000ms
        when the previous workspace dispatch was /clear.
        """
        emissions: list[tuple[str, int]] = []

        def capture(prompt: str, delay: int) -> None:
            emissions.append((prompt, delay))

        signal_bus.kimi_blue_arrow_dispatched.connect(capture)
        try:
            widget.load_pipeline(kimi_specs)
            item = widget._items[0]
            assert item.is_worker_arrow_visible()
            item._on_kimi_clicked()
            assert len(emissions) == 1
            prompt, delay = emissions[0]
            assert prompt.startswith("/skill:")
            assert delay == 1000  # default — no /clear preceded
        finally:
            signal_bus.kimi_blue_arrow_dispatched.disconnect(capture)

    def test_blue_arrow_after_clear_uses_extra_delay(self, widget, qapp):
        """After /clear (with Use Kimi mirror), the next blue-arrow click
        must use 3000ms delay (1000 default + 2000 extra) so Kimi has
        time to repaint its prompt before Enter."""
        specs = [
            CommandSpec("/clear", ModelName.SONNET, position=1),
            CommandSpec("/qa:prep", ModelName.SONNET, position=2),
        ]
        emissions: list[tuple[str, int]] = []

        def capture(prompt: str, delay: int) -> None:
            emissions.append((prompt, delay))

        signal_bus.kimi_blue_arrow_dispatched.connect(capture)
        try:
            widget._use_kimi_chk.setChecked(True)
            widget.load_pipeline(specs)
            # Step 1: click /clear via "Rodar próximo" (mirrors to workspace)
            widget._on_step_btn_clicked()
            assert widget._last_workspace_dispatch_was_clear is True
            # Step 2: click blue arrow on /qa:prep
            widget._items[1]._on_kimi_clicked()
            assert len(emissions) == 1
            _, delay = emissions[0]
            assert delay == 3000, (
                f"After /clear the blue-arrow delay must be 3000ms, got {delay}"
            )
            # Flag must be consumed
            assert widget._last_workspace_dispatch_was_clear is False
        finally:
            signal_bus.kimi_blue_arrow_dispatched.disconnect(capture)

    def test_pending_effort_enter_is_cancelled_by_next_dispatch(self, widget, qapp):
        """Bug repro: /effort schedules a 1s Enter to dismiss its modal.
        If the next dispatch (e.g. /skill with AskUserQuestion) lands
        before the timer fires, the late Enter must be CANCELLED — else
        it lands inside AskUserQuestion and selects the default option.
        """
        specs = [
            CommandSpec("/effort medium", ModelName.OPUS, EffortLevel.STANDARD, position=1),
            CommandSpec("/skill:test-autoflow-interactive", ModelName.OPUS, position=2),
        ]
        widget.load_pipeline(specs)
        # Step 1: /effort dispatched → modal-Enter timer armed
        widget._on_step_btn_clicked()
        assert widget._pending_modal_enter_timer is not None
        assert widget._pending_modal_enter_timer.isActive()
        # Step 2: next dispatch must cancel the pending timer
        widget._on_step_btn_clicked()
        assert widget._pending_modal_enter_timer is None, (
            "Pending /effort Enter must be cancelled by the next dispatch — "
            "otherwise it fires into the next command's interactive prompt."
        )

    def test_blue_arrow_consecutive_uses_default_delay(self, widget, qapp):
        """Two blue-arrow dispatches in a row (no /clear between) → both
        use the default 1000ms delay, not the after-clear 3000ms."""
        specs = [
            CommandSpec("/qa:prep", ModelName.SONNET, position=1),
            CommandSpec("/qa:report", ModelName.SONNET, position=2),
        ]
        emissions: list[tuple[str, int]] = []

        def capture(prompt: str, delay: int) -> None:
            emissions.append((prompt, delay))

        signal_bus.kimi_blue_arrow_dispatched.connect(capture)
        try:
            widget.load_pipeline(specs)
            widget._items[0]._on_kimi_clicked()
            widget._items[1]._on_kimi_clicked()
            assert len(emissions) == 2
            assert emissions[0][1] == 1000
            assert emissions[1][1] == 1000
        finally:
            signal_bus.kimi_blue_arrow_dispatched.disconnect(capture)

    def test_blue_arrow_does_not_emit_legacy_run_command_signal(
        self, widget, qapp, kimi_specs
    ):
        """Regression guard: the blue-arrow path must NOT emit
        run_command_in_workspace_terminal (the legacy 80ms path), or the
        500ms gate is bypassed."""
        legacy: list[str] = []
        signal_bus.run_command_in_workspace_terminal.connect(legacy.append)
        try:
            widget.load_pipeline(kimi_specs)
            widget._items[0]._on_kimi_clicked()
            assert legacy == [], (
                "Blue arrow must NOT emit run_command_in_workspace_terminal — "
                "only kimi_blue_arrow_dispatched."
            )
        finally:
            signal_bus.run_command_in_workspace_terminal.disconnect(legacy.append)


class TestForceKimi:
    """Cobertura do modo Main LLM Kimi (testid legado queue-chk-force-kimi).

    Quando ativo: a seta verde despacha para o terminal interactive via
    /skill:slash-executor; /model e /effort viram bolinha amarela sem dispatch;
    /clear vai SO para interactive; seta azul fica oculta. Quando Main LLM
    Claude esta ativo, comportamento legado preservado."""

    @pytest.fixture()
    def task_specs(self) -> list[CommandSpec]:
        return [CommandSpec("/create-task", ModelName.SONNET, position=1)]

    @pytest.fixture()
    def model_effort_specs(self) -> list[CommandSpec]:
        return [
            CommandSpec("/model opus", ModelName.OPUS, position=1),
            CommandSpec("/effort high", ModelName.OPUS, position=2),
        ]

    @pytest.fixture()
    def clear_specs(self) -> list[CommandSpec]:
        return [CommandSpec("/clear", ModelName.SONNET, position=1)]

    @pytest.fixture()
    def force_kimi_widget(self, widget, monkeypatch, tmp_path):
        """Widget com `_resolve_claude_command_file` monkeypatched para retornar
        um markdown real fake — evita dependencia em arquivos do repo."""
        command_file = tmp_path / ".claude" / "commands" / "create-task.md"
        command_file.parent.mkdir(parents=True)
        command_file.write_text("# create task", encoding="utf-8")
        monkeypatch.setattr(
            type(widget), "_resolve_skill_target",
            classmethod(lambda cls, slug: True),
        )
        monkeypatch.setattr(
            type(widget),
            "_resolve_claude_command_file",
            classmethod(lambda cls, slug: command_file),
        )
        return widget

    # ---- UI checkbox -----------------------------------------------------

    def test_main_llm_kimi_radio_keeps_force_kimi_testid(self, widget):
        chk = widget._force_kimi_chk
        assert chk is not None
        assert chk.property("testid") == "queue-chk-force-kimi"
        assert chk.text() == "kimi"

    def test_single_llm_routing_container_has_two_sections(self, widget):
        from PySide6.QtWidgets import QWidget
        found = [
            w for w in widget.findChildren(QWidget)
            if w.property("testid") == "queue-div-llm-routing"
        ]
        assert len(found) == 1, "queue-div-llm-routing container nao encontrado"
        assert widget._main_claude_radio.isChecked() is True
        assert widget._main_codex_radio.text() == "codex"
        assert widget._use_codex_chk.property("testid") == "queue-chk-use-codex"

    # ---- Legacy path (force-kimi OFF) -----------------------------------

    def test_force_off_per_item_routes_to_interactive(self, widget, task_specs):
        """Sem --force Kimi, comportamento legado: emite interactive."""
        emitted_interactive: list[str] = []
        emitted_workspace: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        try:
            widget._force_kimi_chk.setChecked(False)
            widget.load_pipeline(task_specs)
            widget._items[0]._on_run_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert emitted_interactive == ["/create-task"]
        assert emitted_workspace == []

    # ---- Main Kimi ON: /skill: prefix + interactive ---------------------

    def test_force_on_per_item_injects_skill_prefix_to_interactive(
        self, force_kimi_widget, task_specs
    ):
        emitted_interactive: list[str] = []
        emitted_workspace: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        try:
            force_kimi_widget._force_kimi_chk.setChecked(True)
            force_kimi_widget.load_pipeline(task_specs)
            force_kimi_widget._items[0]._on_run_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert emitted_interactive == ["/skill:slash-executor /create-task"]
        assert emitted_workspace == [], "Main LLM Kimi nao deve tocar T2"

    def test_force_on_step_btn_injects_skill_prefix_to_interactive(
        self, force_kimi_widget, task_specs
    ):
        emitted_interactive: list[str] = []
        emitted_workspace: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        try:
            force_kimi_widget._force_kimi_chk.setChecked(True)
            force_kimi_widget.load_pipeline(task_specs)
            force_kimi_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert emitted_interactive == ["/skill:slash-executor /create-task"]
        assert emitted_workspace == []

    def test_force_on_keeps_colon_namespace_when_injecting_skill_prefix(
        self, force_kimi_widget
    ):
        emitted_interactive: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        try:
            force_kimi_widget._force_kimi_chk.setChecked(True)
            force_kimi_widget.load_pipeline([
                CommandSpec("/blog:init-strategy", ModelName.SONNET, position=1)
            ])
            force_kimi_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
        assert emitted_interactive == ["/skill:slash-executor /blog:init-strategy"]

    def test_force_on_direct_skill_command_passes_through(self, force_kimi_widget):
        emitted_interactive: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        try:
            force_kimi_widget._force_kimi_chk.setChecked(True)
            force_kimi_widget.load_pipeline([
                CommandSpec("/skill:daily --check", ModelName.SONNET, position=1)
            ])
            force_kimi_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
        assert emitted_interactive == ["/skill:daily --check"]

    def test_force_on_skill_only_command_keeps_legacy_skill_route(
        self, widget, monkeypatch
    ):
        emitted_interactive: list[str] = []
        monkeypatch.setattr(
            type(widget),
            "_resolve_claude_command_file",
            classmethod(lambda cls, slug: None),
        )
        monkeypatch.setattr(
            type(widget),
            "_resolve_skill_target",
            classmethod(lambda cls, slug: slug == "prompt-to-md"),
        )
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        try:
            widget._force_kimi_chk.setChecked(True)
            widget.load_pipeline([
                CommandSpec("/prompt-to-md --name demo", ModelName.SONNET, position=1)
            ])
            widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
        assert emitted_interactive == ["/skill:prompt-to-md --name demo"]

    def test_force_on_preserves_special_kimi_wrapper(
        self, force_kimi_widget, monkeypatch
    ):
        emitted_interactive: list[str] = []
        monkeypatch.setattr(
            type(force_kimi_widget),
            "_kimi_requires_specific_wrapper",
            classmethod(lambda cls, slug: slug == "daily-loop:do"),
        )
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        try:
            force_kimi_widget._force_kimi_chk.setChecked(True)
            force_kimi_widget.load_pipeline([
                CommandSpec(
                    "/daily-loop:do --slug inbox --item 001",
                    ModelName.SONNET,
                    position=1,
                )
            ])
            force_kimi_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
        assert emitted_interactive == [
            "/skill:daily-loop:do --slug inbox --item 001"
        ]

    # ---- /model e /effort suprimidos -----------------------------------

    def test_force_on_model_effort_no_terminal_emit(
        self, force_kimi_widget, model_effort_specs
    ):
        """/model e /effort viram bolinha amarela SEM enviar para terminal,
        nem interactive nem workspace."""
        emitted_interactive: list[str] = []
        emitted_workspace: list[str] = []
        pulses: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        signal_bus.listener_helper_pulse.connect(pulses.append)
        try:
            force_kimi_widget._force_kimi_chk.setChecked(True)
            force_kimi_widget.load_pipeline(model_effort_specs)
            # Per-item green em /model
            force_kimi_widget._items[0]._on_run_clicked()
            # Per-item green em /effort
            force_kimi_widget._items[1]._on_run_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
            signal_bus.listener_helper_pulse.disconnect(pulses.append)
        assert emitted_interactive == []
        assert emitted_workspace == []
        # NAO enviado ao terminal, MAS o listener pulsa verde para o autocast
        # avancar — kimi main roda em T1 (interactive).
        assert pulses == ["interactive", "interactive"]
        # Bolinha amarela: items marcados como sent
        assert force_kimi_widget._items[0].is_pending_run() is False
        assert force_kimi_widget._items[1].is_pending_run() is False

    def test_force_on_model_effort_does_not_update_last_command_label(
        self, force_kimi_widget, model_effort_specs
    ):
        """/model e /effort suprimidos NAO devem aparecer como ultimo comando
        executado (review MEDIUM 4)."""
        force_kimi_widget._force_kimi_chk.setChecked(True)
        force_kimi_widget.load_pipeline(model_effort_specs)
        # Estado inicial: label invisivel / vazio
        force_kimi_widget._items[0]._on_run_clicked()
        # Last command label deve permanecer vazio/invisivel
        assert not force_kimi_widget._last_cmd_label.isVisible() or \
            force_kimi_widget._last_cmd_label.text().strip() == ""

    # ---- /clear vai SO para interactive ---------------------------------

    def test_force_on_clear_per_item_goes_only_to_interactive(
        self, force_kimi_widget, clear_specs
    ):
        emitted_interactive: list[str] = []
        emitted_workspace: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        try:
            force_kimi_widget._force_kimi_chk.setChecked(True)
            force_kimi_widget.load_pipeline(clear_specs)
            force_kimi_widget._items[0]._on_run_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert emitted_interactive == ["/clear"]
        assert emitted_workspace == [], "/clear nao pode ir para T2 em Main LLM Kimi"

    def test_force_on_clear_step_btn_goes_only_to_interactive(
        self, force_kimi_widget, clear_specs
    ):
        emitted_interactive: list[str] = []
        emitted_workspace: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        try:
            force_kimi_widget._force_kimi_chk.setChecked(True)
            force_kimi_widget.load_pipeline(clear_specs)
            force_kimi_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert emitted_interactive == ["/clear"]
        assert emitted_workspace == []

    # ---- Skill existence validation -------------------------------------

    def test_force_on_unknown_skill_aborts_with_toast(self, widget, task_specs, monkeypatch):
        """Comando sem markdown em .claude/commands
        deve abortar dispatch com toast (review HIGH 2)."""
        monkeypatch.setattr(
            type(widget), "_resolve_skill_target",
            classmethod(lambda cls, slug: False),
        )
        monkeypatch.setattr(
            type(widget),
            "_resolve_claude_command_file",
            classmethod(lambda cls, slug: None),
        )
        emitted_interactive: list[str] = []
        emitted_workspace: list[str] = []
        toasts: list[tuple] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        try:
            widget._force_kimi_chk.setChecked(True)
            widget.load_pipeline(task_specs)
            widget._items[0]._on_run_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_interactive.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert emitted_interactive == [], "dispatch deve abortar quando skill nao existe"
        assert emitted_workspace == [], "dispatch deve abortar quando skill nao existe"
        assert any("create-task" in m for m, _ in toasts), \
            "toast deve mencionar o slug ausente"

    def test_resolve_skill_target_works_when_cwd_is_nested(self, tmp_path, monkeypatch):
        """Regression: resolver deve achar skill no parent mesmo com cwd aninhado."""
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

        repo_root = tmp_path / "repo"
        nested_cwd = repo_root / "ai-forge" / "workflow-app"
        nested_cwd.mkdir(parents=True)
        skills_dir = repo_root / ".agents" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "blog:init-strategy.md").write_text("# skill", encoding="utf-8")

        monkeypatch.chdir(nested_cwd)
        monkeypatch.setattr(
            CommandQueueWidget,
            "_SKILL_SEARCH_DIRS",
            (".agents/skills",),
            raising=False,
        )
        assert CommandQueueWidget._resolve_skill_target("blog:init-strategy") is True

    def test_kimi_requires_specific_wrapper_detects_runtime_contract(
        self, tmp_path, monkeypatch
    ):
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

        repo_root = tmp_path / "repo"
        nested_cwd = repo_root / "ai-forge" / "workflow-app"
        nested_cwd.mkdir(parents=True)
        skills_dir = repo_root / ".agents" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "daily-loop:do.md").write_text(
            "Run daily-loop-autocast with WF_CHANNEL_OVERRIDE=workspace",
            encoding="utf-8",
        )
        (skills_dir / "create-task.md").write_text(
            "Read .claude/commands/create-task.md",
            encoding="utf-8",
        )

        monkeypatch.chdir(nested_cwd)
        monkeypatch.setattr(
            CommandQueueWidget,
            "_SKILL_SEARCH_DIRS",
            (".agents/skills",),
            raising=False,
        )

        assert CommandQueueWidget._kimi_requires_specific_wrapper("daily-loop:do") is True
        assert CommandQueueWidget._kimi_requires_specific_wrapper("create-task") is False

    # ---- /skill: prefix idempotente -------------------------------------

    def test_inject_skill_prefix_idempotent(self):
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        f = CommandQueueWidget._inject_skill_prefix
        assert f("/skill:create-task") == "/skill:create-task"
        assert f("/create-task") == "/skill:create-task"
        assert f("/create-task arg") == "/skill:create-task arg"
        assert f("") == ""
        assert f("prompt livre sem barra") == "prompt livre sem barra"

    def test_kimi_slash_executor_invocation_preserves_original_command(self):
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        f = CommandQueueWidget._build_kimi_slash_executor_invocation
        assert f("/skill:create-task") == "/skill:create-task"
        assert f("/create-task") == "/skill:slash-executor /create-task"
        assert f("/blog:init-strategy --x y") == (
            "/skill:slash-executor /blog:init-strategy --x y"
        )
        assert f("") == ""
        assert f("prompt livre sem barra") == "prompt livre sem barra"

    # ---- Main LLM radio exclusivity ------------------------------------

    def test_main_llm_kimi_does_not_disable_parallel_kimi(self, widget):
        widget._use_kimi_chk.setChecked(True)
        widget._force_kimi_chk.setChecked(True)
        assert widget._use_kimi_chk.isChecked() is True
        assert widget._use_kimi_chk.isEnabled() is True

    def test_selecting_claude_unchecks_main_kimi(self, widget):
        widget._force_kimi_chk.setChecked(True)
        widget._main_claude_radio.setChecked(True)
        assert widget._force_kimi_chk.isChecked() is False

    # ---- Seta azul oculta quando force-kimi ativo -----------------------

    def test_force_kimi_hides_blue_arrow_on_all_items(self, widget):
        kimi_specs = [
            CommandSpec("/qa:prep", ModelName.SONNET, position=1),
            CommandSpec("/create-task", ModelName.SONNET, position=2),
        ]
        widget.load_pipeline(kimi_specs)
        # Pre-condition: pelo menos um item tem seta de worker visivel.
        any_visible_before = any(
            item.is_worker_arrow_visible() for item in widget._items
        )
        widget._force_kimi_chk.setChecked(True)
        for item in widget._items:
            assert item.is_worker_arrow_visible() is False, \
                "seta de worker deve ficar oculta com --force Kimi"
        widget._main_claude_radio.setChecked(True)
        # Apos desligar: visibilidade restaurada pelo menos para um item
        # whitelisted (sanity — nao todos podem ser whitelisted).
        if any_visible_before:
            assert any(
                item.is_worker_arrow_visible() for item in widget._items
            ), "seta de worker deve ser restaurada apos desligar --force Kimi"

    def test_force_kimi_hides_blue_arrow_on_items_added_later(self, widget):
        widget._force_kimi_chk.setChecked(True)
        widget.load_pipeline([CommandSpec("/qa:prep", ModelName.SONNET, position=1)])
        item = widget._items[0]
        assert item.is_worker_arrow_visible() is False

    # ---- Highlight usa cmd_text original, nao transformado --------------

    def test_force_on_step_btn_highlight_uses_original_cmd_text(
        self, force_kimi_widget, task_specs
    ):
        """Review HIGH 3: highlight quebrava no play-next porque _on_run_command
        recebia o cmd_text transformado e nao batia com item.command_text()."""
        force_kimi_widget._force_kimi_chk.setChecked(True)
        force_kimi_widget.load_pipeline(task_specs)
        force_kimi_widget._on_step_btn_clicked()
        # Item deve estar destacado (highlighted) — comparacao internal usa
        # cmd_text original `/create-task`, NAO `/skill:slash-executor /create-task`.
        assert force_kimi_widget._items[0]._highlighted is True


class TestCodexLlmRouting:
    """Main Codex routes to T1; worker Codex routes to Terminal 3."""

    @pytest.fixture()
    def codex_widget(self, widget, tmp_path, monkeypatch):
        command_file = tmp_path / ".claude" / "commands" / "blog" / "init-strategy.md"
        command_file.parent.mkdir(parents=True)
        command_file.write_text("# init strategy", encoding="utf-8")
        # /cmd:review e codex-compatible (whitelist Codex) mas NAO kimi-compatible:
        # usado pelos testes de roteamento Codex/T3 sob o modelo router/whitelist.
        review_file = tmp_path / ".claude" / "commands" / "cmd" / "review.md"
        review_file.parent.mkdir(parents=True)
        review_file.write_text("# review", encoding="utf-8")
        agent_file = tmp_path / "ai-forge" / "MCP" / "agents" / "executor.md"
        agent_file.parent.mkdir(parents=True)
        agent_file.write_text("# executor", encoding="utf-8")
        listener_file = tmp_path / "ai-forge" / "rules" / "workflow-app-listeners.md"
        listener_file.parent.mkdir(parents=True)
        listener_file.write_text("# listeners", encoding="utf-8")
        _codex_files = {"blog:init-strategy": command_file, "cmd:review": review_file}
        monkeypatch.setattr(
            type(widget),
            "_resolve_claude_command_file",
            classmethod(lambda cls, slug: _codex_files.get(slug)),
        )
        monkeypatch.setattr(
            type(widget),
            "_resolve_codex_executor_agent_file",
            classmethod(lambda cls: agent_file),
        )
        monkeypatch.setattr(
            type(widget),
            "_resolve_listener_rules_file",
            classmethod(lambda cls: listener_file),
        )
        return widget

    def test_main_codex_step_sends_executor_prompt_to_t1(self, codex_widget):
        emitted_t1: list[str] = []
        emitted_t2: list[str] = []
        emitted_t3: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_t1.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_t2.append)
        signal_bus.run_command_in_workspace_xterm.connect(emitted_t3.append)
        try:
            codex_widget._main_codex_radio.setChecked(True)
            codex_widget.load_pipeline([
                CommandSpec("/blog:init-strategy", ModelName.SONNET, position=1)
            ])
            codex_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_t1.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_t2.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(emitted_t3.append)

        assert len(emitted_t1) == 1
        assert emitted_t2 == []
        assert emitted_t3 == []
        assert "Command: /blog:init-strategy" in emitted_t1[0]
        assert "Command markdown:" in emitted_t1[0]
        assert "Listener rules:" in emitted_t1[0]
        assert "Expected listener channel: interactive" in emitted_t1[0]
        assert "execute/preserve it so it notifies channel `interactive`" in emitted_t1[0]
        assert "Emit exactly one final listener status" in emitted_t1[0]
        assert "not from an incidental shell `$?`" in emitted_t1[0]
        assert "On command success, notify only success" in emitted_t1[0]
        assert "These outcomes MUST notify failure/red" in emitted_t1[0]
        assert "If your final answer says `BLOCKED`" in emitted_t1[0]
        assert "Do not emit success for this case" in emitted_t1[0]

    def test_main_codex_model_effort_are_suppressed(self, codex_widget):
        emitted_t1: list[str] = []
        emitted_t3: list[str] = []
        pulses: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(emitted_t3.append)
        signal_bus.listener_helper_pulse.connect(pulses.append)
        try:
            codex_widget._main_codex_radio.setChecked(True)
            codex_widget.load_pipeline([
                CommandSpec("/model opus", ModelName.OPUS, position=1),
                CommandSpec("/effort medium", ModelName.OPUS, position=2),
            ])
            codex_widget._on_step_btn_clicked()
            codex_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(emitted_t3.append)
            signal_bus.listener_helper_pulse.disconnect(pulses.append)

        assert emitted_t1 == []
        assert emitted_t3 == []
        # NAO enviado ao terminal, MAS o listener pulsa verde para o autocast
        # avancar — codex main roda em T1 (interactive).
        assert pulses == ["interactive", "interactive"]
        assert codex_widget._items[0].is_pending_run() is False
        assert codex_widget._items[1].is_pending_run() is False

    def test_parallel_codex_worker_routes_next_eligible_command_to_t3(
        self, codex_widget
    ):
        emitted_t1: list[str] = []
        emitted_t3: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(emitted_t3.append)
        try:
            codex_widget._main_claude_radio.setChecked(True)
            codex_widget._use_codex_chk.setChecked(True)
            # /cmd:review e codex-compatible (whitelist Codex); o router o
            # classifica como Provider.CODEX -> worker Codex/T3.
            codex_widget.load_pipeline([
                CommandSpec("/cmd:review", ModelName.SONNET, position=1)
            ])
            codex_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(emitted_t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(emitted_t3.append)

        assert emitted_t1 == []
        assert len(emitted_t3) == 1
        assert "Command: /cmd:review" in emitted_t3[0]
        assert "Listener rules:" in emitted_t3[0]
        assert "Expected listener channel: workspace_xterm" in emitted_t3[0]
        assert "execute/preserve it so it notifies channel `workspace_xterm`" in emitted_t3[0]
        assert "Emit exactly one final listener status" in emitted_t3[0]
        assert "not from an incidental shell `$?`" in emitted_t3[0]
        assert "These outcomes MUST notify failure/red" in emitted_t3[0]
        assert "Never run the success branch" in emitted_t3[0]


class TestWorkerRoutingExpandedToAllMainLlms:
    """Fix 2026-05-30 — blue-arrow (worker-bound) commands route to the worker
    terminal (T2 Kimi / T3 Codex) under ANY Main LLM, not only Claude.

    Bug before the fix: when Main LLM was Codex (or Kimi), `_on_step_btn_clicked`
    short-circuited EVERY command to T1 in the main format, silently swallowing
    blue-arrow commands that belonged to the Parallel Worker. The Claude-main
    worker routing was correct; this expands the SAME behavior to all main LLMs.

    Goal contract:
      - No Parallel Worker checked → all commands go to T1 in the Main LLM
        format (even commands that COULD run on a worker).
      - A Parallel Worker checked → blue-arrow commands go to the worker
        terminal in the worker's format; green-arrow commands stay on T1.
    """

    @pytest.fixture()
    def routed_widget(self, widget, tmp_path, monkeypatch):
        """widget with claude command files resolvable for the slugs used
        below, so the Codex executor-prompt builder succeeds."""
        files: dict[str, object] = {}
        # commit:simple is resolvable but NOT kimi-compatible (no blue arrow):
        # used by the green-arrow-only regression test below.
        # cmd:review is codex-compatible (Codex whitelist) but NOT kimi-compatible:
        # used by the Codex/T3 routing tests under the router/whitelist model.
        for slug in ("blog:init-strategy", "qa:prep", "commit:simple", "cmd:review"):
            f = tmp_path / ".claude" / "commands" / (slug.replace(":", "/") + ".md")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("# cmd", encoding="utf-8")
            files[slug] = f
        agent_file = tmp_path / "executor.md"
        agent_file.write_text("# executor", encoding="utf-8")
        listener_file = tmp_path / "listeners.md"
        listener_file.write_text("# listeners", encoding="utf-8")
        monkeypatch.setattr(
            type(widget),
            "_resolve_claude_command_file",
            classmethod(lambda cls, slug: files.get(slug)),
        )
        monkeypatch.setattr(
            type(widget),
            "_resolve_codex_executor_agent_file",
            classmethod(lambda cls: agent_file),
        )
        monkeypatch.setattr(
            type(widget),
            "_resolve_listener_rules_file",
            classmethod(lambda cls: listener_file),
        )
        return widget

    def test_main_codex_worker_kimi_routes_blue_arrow_to_t2(self, routed_widget):
        """Main Codex + Worker Kimi: a Kimi-compatible (blue-arrow) command
        goes to T2 Kimi (kimi_blue_arrow_dispatched), NOT to T1 Codex."""
        t1: list[str] = []
        t3: list[str] = []
        blue: list[str] = []

        def _blue(prompt: str, delay: int) -> None:
            blue.append(prompt)

        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        signal_bus.kimi_blue_arrow_dispatched.connect(_blue)
        try:
            routed_widget._main_codex_radio.setChecked(True)
            routed_widget._use_kimi_chk.setChecked(True)
            routed_widget.load_pipeline(
                [CommandSpec("/qa:prep", ModelName.SONNET, position=1)]
            )
            assert routed_widget._items[0].is_worker_arrow_visible()
            routed_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)
            signal_bus.kimi_blue_arrow_dispatched.disconnect(_blue)

        assert t1 == [], "blue-arrow command must NOT leak into T1 under Main Codex"
        assert t3 == []
        assert len(blue) == 1
        assert blue[0].startswith("/skill:")
        assert routed_widget._items[0].is_pending_run() is False

    def test_main_codex_worker_codex_routes_blue_arrow_to_t3(self, routed_widget):
        """Main Codex + Worker Codex: a codex-compatible command (/cmd:review)
        goes to T3 Codex worker (channel workspace_xterm), NOT to T1.

        Modelo router/whitelist (decisao do operador 06-02): a elegibilidade do
        worker Codex vem da whitelist Codex (is_codex_compatible), nao da
        elegibilidade Kimi blue-arrow."""
        t1: list[str] = []
        t3: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            routed_widget._main_codex_radio.setChecked(True)
            routed_widget._use_codex_chk.setChecked(True)
            routed_widget.load_pipeline(
                [CommandSpec("/cmd:review", ModelName.SONNET, position=1)]
            )
            routed_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert t1 == [], "codex command must NOT leak into T1 under Main Codex"
        assert len(t3) == 1
        assert "Command: /cmd:review" in t3[0]
        assert "Expected listener channel: workspace_xterm" in t3[0]

    def test_main_kimi_worker_codex_routes_blue_arrow_to_t3(self, routed_widget):
        """Main Kimi + Worker Codex: a codex-compatible command (/cmd:review)
        goes to T3 Codex worker, NOT to T1 Kimi.

        Modelo router/whitelist (decisao do operador 06-02): worker Codex
        reivindica comandos da whitelist Codex, independente do Main LLM."""
        t1: list[str] = []
        t3: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            routed_widget._main_kimi_radio.setChecked(True)  # alias _force_kimi_chk
            routed_widget._use_codex_chk.setChecked(True)
            routed_widget.load_pipeline(
                [CommandSpec("/cmd:review", ModelName.SONNET, position=1)]
            )
            routed_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert t1 == [], "codex command must NOT leak into T1 under Main Kimi"
        assert len(t3) == 1
        assert "Command: /cmd:review" in t3[0]
        assert "Expected listener channel: workspace_xterm" in t3[0]

    def test_main_codex_no_worker_keeps_blue_arrow_on_t1(self, routed_widget):
        """Goal rule #1 — Main Codex + NO worker: even a Kimi-eligible
        (blue-arrow) command goes to T1 in the Codex executor format, with
        nothing leaking to the worker terminals."""
        t1: list[str] = []
        t3: list[str] = []
        blue: list[str] = []

        def _blue(prompt: str, delay: int) -> None:
            blue.append(prompt)

        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        signal_bus.kimi_blue_arrow_dispatched.connect(_blue)
        try:
            routed_widget._main_codex_radio.setChecked(True)
            routed_widget._use_kimi_chk.setChecked(False)
            routed_widget._use_codex_chk.setChecked(False)
            routed_widget.load_pipeline(
                [CommandSpec("/qa:prep", ModelName.SONNET, position=1)]
            )
            routed_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)
            signal_bus.kimi_blue_arrow_dispatched.disconnect(_blue)

        assert len(t1) == 1
        assert "Command: /qa:prep" in t1[0]
        assert "Expected listener channel: interactive" in t1[0]
        assert t3 == []
        assert blue == []

    def test_main_claude_worker_codex_green_arrow_only_stays_on_t1(self, routed_widget):
        """Reported bug 2026-06-01 — Main Claude + Worker Codex: a command that
        is NOT blue-arrow eligible (green-arrow only, e.g. /commit:simple, not in
        the kimi whitelist) must stay on T1 raw, NOT be swallowed by T3 Codex.

        Before the fix, use_codex routed EVERY resolvable slash command to T3,
        ignoring the blue/green distinction."""
        t1: list[str] = []
        t3: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            routed_widget._main_claude_radio.setChecked(True)
            routed_widget._use_codex_chk.setChecked(True)
            routed_widget.load_pipeline(
                [CommandSpec("/commit:simple", ModelName.SONNET, position=1)]
            )
            # No blue arrow on a non-whitelisted command.
            assert routed_widget._items[0].is_worker_arrow_visible() is False
            routed_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert t3 == [], "green-arrow-only command must NOT be routed to T3 Codex"
        assert t1 == ["/commit:simple"], "green-arrow-only command stays raw on T1"

    def test_main_claude_worker_codex_blue_arrow_goes_to_t3(self, routed_widget):
        """Companion to the green-arrow regression: under the SAME Main Claude +
        Worker Codex, a codex-compatible command (/cmd:review) DOES go to T3
        Codex. Together the two tests pin the codex-whitelist/green split.

        Modelo router/whitelist (decisao do operador 06-02): o item codex-only
        nao tem a seta azul Kimi; o provider efetivo (botao unico) e CODEX."""
        from workflow_app.command_queue.provider_router import Provider

        t1: list[str] = []
        t3: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            routed_widget._main_claude_radio.setChecked(True)
            routed_widget._use_codex_chk.setChecked(True)
            routed_widget.load_pipeline(
                [CommandSpec("/cmd:review", ModelName.SONNET, position=1)]
            )
            assert routed_widget._items[0].effective_provider() is Provider.CODEX
            routed_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert t1 == [], "codex command must NOT leak into T1"
        assert len(t3) == 1
        assert "Command: /cmd:review" in t3[0]
        assert "Expected listener channel: workspace_xterm" in t3[0]

    def test_kimi_eligible_non_codex_command_not_claimed_by_codex_worker(
        self, routed_widget
    ):
        """Decisao do operador 06-02 (modelo router/whitelist): com SOMENTE o
        worker Codex ligado, um comando kimi-elegivel mas NAO codex-compativel
        (/blog:init-strategy) NAO e reivindicado pelo worker Codex — vai para T1
        raw, nao para T3. Trava a mudanca de comportamento vs o gate legado
        codex_blue_eligible (que mandava todo blue-arrow para o worker ativo).

        Fecha a divergencia step-vs-clique que reprovou o loop
        06-02-seta-unica-multi-llm-queue: agora o step concorda com o clique
        direto (ambos usam a whitelist Codex via provider_router)."""
        t1: list[str] = []
        t3: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            routed_widget._main_claude_radio.setChecked(True)
            routed_widget._use_kimi_chk.setChecked(False)
            routed_widget._use_codex_chk.setChecked(True)
            routed_widget.load_pipeline(
                [CommandSpec("/blog:init-strategy", ModelName.SONNET, position=1)]
            )
            routed_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert t3 == [], (
            "comando kimi-elegivel-nao-codex NAO pode ir para o worker Codex/T3"
        )
        assert t1 == ["/blog:init-strategy"], (
            "comando nao reivindicado por worker cai em Claude/T1 raw"
        )

    def test_kimi_eligible_only_command_routes_to_t2_in_step(self, routed_widget):
        """Fix F-2 (recovery 06-02): paridade step-vs-clique do eixo Kimi. Um
        item `kimi_eligible=True` que NAO esta na whitelist Kimi (ex.:
        /execute-task vindo de um loop kimi_eligible) e classificado KIMI pelo
        provider_router (regra 4: kimi_worker ativo E kimi_eligible). O step
        agora consome o veredito do router para use_kimi (antes gateava so por
        is_kimi_compatible e mandava o item para T1, divergindo do clique
        direto). Com Worker Kimi ligado, o step deve despachar para T2 (seta
        azul), NAO para T1.

        Pre-F-2 este teste falharia: o item iria raw para T1 (use_kimi era False
        porque is_kimi_compatible('/execute-task') e False)."""
        from workflow_app.command_queue.provider_router import Provider

        t1: list[str] = []
        t3: list[str] = []
        blue: list[str] = []

        def _blue(prompt: str, delay: int) -> None:
            blue.append(prompt)

        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        signal_bus.kimi_blue_arrow_dispatched.connect(_blue)
        try:
            routed_widget._main_claude_radio.setChecked(True)
            routed_widget._use_kimi_chk.setChecked(True)
            routed_widget._use_codex_chk.setChecked(False)
            routed_widget.load_pipeline(
                [CommandSpec(
                    "/execute-task", ModelName.SONNET, position=1,
                    kimi_eligible=True,
                )]
            )
            assert routed_widget._items[0].is_worker_arrow_visible(), (
                "item kimi_eligible deve mostrar a seta worker"
            )
            assert (
                routed_widget._items[0].effective_provider() is Provider.KIMI
            ), "clique direto ja classifica KIMI; o step deve concordar"
            routed_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)
            signal_bus.kimi_blue_arrow_dispatched.disconnect(_blue)

        assert t1 == [], (
            "item kimi_eligible NAO pode vazar para T1 no step (divergencia F-2)"
        )
        assert t3 == [], "worker Kimi vai para T2, nunca T3"
        assert len(blue) == 1, "item kimi_eligible deve despachar a seta azul (T2)"


# ---------------------------------------------------------------------------
# Item 001 — Unificar entrypoint dos 3 botoes (daily-loop, loop, cmd-single)
# ---------------------------------------------------------------------------

class TestUnifiedEntrypointThreeButtons:
    """Valida que queue-btn-daily-loop, queue-btn-loop e queue-btn-cmd-single
    abrem a mesma classe DoublePhaseArgumentDialog e que a lista renderizada
    apos accept() traz /clear, /model, /effort conforme GROUP_MAP.
    """

    def _find_button_by_testid(self, widget: CommandQueueWidget, testid: str):
        from PySide6.QtWidgets import QPushButton
        # Buttons live inside header_widget (sibling of CommandQueueWidget in MainWindow)
        header = getattr(widget, "header_widget", None)
        search_root = header if header is not None else widget
        for btn in search_root.findChildren(QPushButton):
            if btn.property("testid") == testid:
                return btn
        return None

    def test_daily_loop_button_is_double_phase_button(self, widget):
        btn = self._find_button_by_testid(widget, "queue-btn-daily-loop")
        assert btn is not None
        from workflow_app.command_queue.double_phase_button import DoublePhaseButton
        assert isinstance(btn, DoublePhaseButton)

    def test_loop_button_is_double_phase_button(self, widget):
        btn = self._find_button_by_testid(widget, "queue-btn-loop")
        assert btn is not None
        from workflow_app.command_queue.double_phase_button import DoublePhaseButton
        assert isinstance(btn, DoublePhaseButton)

    def test_cmd_single_button_is_double_phase_button(self, widget):
        btn = self._find_button_by_testid(widget, "queue-btn-cmd-single")
        assert btn is not None
        from workflow_app.command_queue.double_phase_button import DoublePhaseButton
        assert isinstance(btn, DoublePhaseButton)

    def test_all_three_buttons_open_same_dialog_class(self, widget, qapp, qtbot, monkeypatch):
        from workflow_app.command_queue.double_phase_button import DoublePhaseButton
        from workflow_app.command_queue.double_phase_dialog import DoublePhaseArgumentDialog

        opened: list[DoublePhaseArgumentDialog] = []

        def fake_exec(self):
            opened.append(self)
            return 1  # QDialog.Accepted

        monkeypatch.setattr(DoublePhaseArgumentDialog, "exec", fake_exec)

        for testid in ("queue-btn-daily-loop", "queue-btn-loop", "queue-btn-cmd-single"):
            opened.clear()
            btn = self._find_button_by_testid(widget, testid)
            assert btn is not None, f"botao {testid} nao encontrado"
            from PySide6.QtCore import Qt
            qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
            assert len(opened) == 1, f"{testid}: esperado 1 dialog, aberto {len(opened)}"
            dlg = opened[0]
            assert isinstance(dlg, DoublePhaseArgumentDialog)
            assert dlg.objectName() == "DoublePhaseArgumentDialog"
            assert dlg.property("data-testid") in (None, "")

    def test_loop_command_ready_injects_prep_per_group_map(self, widget):
        from workflow_app.command_queue.command_queue_widget import GROUP_MAP
        widget.clear_queue()
        widget._on_loop_command_ready("/loop --task blacksmith/loop/test.md --name test-slug")
        names = [item.get_spec().name for item in widget._items]
        assert names[0] == "/clear"
        assert names[1].startswith("/model ")
        assert names[2].startswith("/effort ")
        loop_cfg = GROUP_MAP.get("loop", {})
        expected_model = loop_cfg.get("model", ModelName.OPUS).value.lower()
        expected_effort = loop_cfg.get("effort", EffortLevel.HIGH).value
        assert names[1] == f"/model {expected_model}"
        assert names[2] == f"/effort {expected_effort}"

    def test_daily_loop_command_ready_injects_prep_per_group_map(self, widget):
        from workflow_app.command_queue.command_queue_widget import GROUP_MAP
        widget.clear_queue()
        widget._on_daily_loop_command_ready("/daily-loop --tasklist path.md")
        names = [item.get_spec().name for item in widget._items]
        assert names[0] == "/clear"
        assert names[1].startswith("/model ")
        assert names[2].startswith("/effort ")
        dl_cfg = GROUP_MAP.get("daily_loop", {})
        expected_model = dl_cfg.get("model", ModelName.SONNET).value.lower()
        expected_effort = dl_cfg.get("effort", EffortLevel.STANDARD).value
        assert names[1] == f"/model {expected_model}"
        assert names[2] == f"/effort {expected_effort}"

    def test_cmd_single_command_ready_injects_prep_per_group_map(self, widget, tmp_path):
        from workflow_app.command_queue.command_queue_widget import GROUP_MAP
        md = tmp_path / "cmd.md"
        md.write_text("# /test:cmd\ncmd_target: /test:cmd\n", encoding="utf-8")
        widget.clear_queue()
        widget._on_loop_command_ready(f"/loop --cmd-single {md} --name test-cmd")
        names = [item.get_spec().name for item in widget._items]
        assert names[0] == "/clear"
        assert names[1].startswith("/model ")
        assert names[2].startswith("/effort ")
        cs_cfg = GROUP_MAP.get("cmd_single", {})
        expected_model = cs_cfg.get("model", ModelName.OPUS).value.lower()
        expected_effort = cs_cfg.get("effort", EffortLevel.HIGH).value
        assert names[1] == f"/model {expected_model}"
        assert names[2] == f"/effort {expected_effort}"


# ---------------------------------------------------------------------------
# Item 002 — Corrigir bug do literal <slug> no runtime
# ---------------------------------------------------------------------------

class TestBugLiteralSlugRegression:
    """Valida que o dialog estruturado nunca emite <slug> ou <path> literais
    no comando final e que o handler de loop processa o valor real corretamente.
    """

    def test_double_phase_dialog_emits_real_slug_not_placeholder(self, qapp):
        """Marcar --name e digitar meu-slug produz '--name meu-slug', nunca '--name <slug>'."""
        from PySide6.QtTest import QSignalSpy
        from workflow_app.command_queue.double_phase_dialog import DoublePhaseArgumentDialog
        from workflow_app.domain import FlagSpec

        dlg = DoublePhaseArgumentDialog(
            pipeline_name="/loop",
            flags_with_value=[FlagSpec(name="name", label="Nome", placeholder="slug")],
        )
        spy = QSignalSpy(dlg.submitted)

        # Marcar checkbox --name
        chk = dlg._flag_checkboxes["name"]
        chk.setChecked(True)

        # Digitar valor real
        container, edit = dlg._flag_inputs["name"]
        edit.setText("meu-slug")

        # Confirmar
        dlg._on_confirm()

        assert spy.count() == 1
        command_line = spy.at(0)[0]
        assert "--name meu-slug" in command_line
        assert "<slug>" not in command_line
        dlg.deleteLater()

    def test_loop_command_ready_processes_real_slug(self, widget):
        """_on_loop_command_ready recebe '--name meu-slug' e propaga slug canonico.

        Apos integracao com normalize_loop_name.py (single source of truth,
        2026-05-14), `--name meu-slug` sem prefixo mm-dd e normalizado para
        `{mm}-{dd}-meu-slug`. Todos os sub-comandos da fila recebem o slug
        canonico FINAL, garantindo que fases 2..N nao apontem para diretorio
        inexistente.
        """
        import re as _re
        widget.clear_queue()
        widget._on_loop_command_ready("/loop --task blacksmith/loop/test.md --name meu-slug")
        names = [item.get_spec().name for item in widget._items]
        # Slug deve ser canonical-form: ^\d{2}-\d{2}-meu-slug$
        canonical_re = _re.compile(r"--name (\d{2}-\d{2}-meu-slug)\b")
        canonical_matches = [canonical_re.search(n) for n in names]
        assert any(canonical_matches), (
            f"nenhum comando continha slug canonico mm-dd-meu-slug: {names}"
        )
        assert all("<slug>" not in n for n in names), f"placeholder <slug> encontrado: {names}"
        # Todos os sub-comandos devem ter o MESMO slug final
        slugs_found = {m.group(1) for m in canonical_matches if m}
        assert len(slugs_found) == 1, (
            f"sub-comandos divergiram em slug: {slugs_found} - quebraria cadeia"
        )

    # ─── Regression: slug derivation from source.md path ────────────────────
    # Bug 2026-05-14: `slug = Path(path_arg).stem` retornava "source" quando
    # o source.md vivia em blacksmith/loop-archives/{loop_name}/source.md.
    # Hardening per /mcp:codex adversarial review 2026-05-14:
    # widget faz APENAS identity lookup (re-entry detection via JSON canonico);
    # canonicalizacao (mm-dd prefix, kebab, stopwords) e autoridade exclusiva
    # do /loop:create-structure markdown spec.

    def test_existing_loop_slug_detects_re_entry(self, tmp_path):
        """Quando _LOOP-CONFIG.json existe no parent, retorna nome do parent dir."""
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        loop_dir = tmp_path / "blog-stockpile-publish-overhaul"
        loop_dir.mkdir()
        (loop_dir / "_LOOP-CONFIG.json").write_text("{}", encoding="utf-8")
        source = loop_dir / "source.md"
        source.write_text("# source", encoding="utf-8")
        result = CommandQueueWidget._existing_loop_slug_from_path(str(source))
        assert result == "blog-stockpile-publish-overhaul"

    def test_existing_loop_slug_returns_none_without_json(self, tmp_path):
        """Sem _LOOP-CONFIG.json, retorna None (fresh source, nao re-entry)."""
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        loop_dir = tmp_path / "new-loop"
        loop_dir.mkdir()
        source = loop_dir / "source.md"
        source.write_text("# fresh", encoding="utf-8")
        result = CommandQueueWidget._existing_loop_slug_from_path(str(source))
        assert result is None

    def test_existing_loop_slug_returns_none_for_named_source(self, tmp_path):
        """Source com nome != source.md nunca eh tratado como re-entry."""
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        (tmp_path / "_LOOP-CONFIG.json").write_text("{}", encoding="utf-8")
        named = tmp_path / "refactor-auth.md"
        named.write_text("# named", encoding="utf-8")
        result = CommandQueueWidget._existing_loop_slug_from_path(str(named))
        assert result is None

    def test_existing_loop_slug_handles_dotdot_path(self, tmp_path):
        """Path com ../ eh resolvido antes de checar ancestrais."""
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        loop_dir = tmp_path / "my-loop"
        loop_dir.mkdir()
        (loop_dir / "_LOOP-CONFIG.json").write_text("{}", encoding="utf-8")
        (loop_dir / "source.md").write_text("# x", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        traversal_path = str(sub / ".." / "my-loop" / "source.md")
        result = CommandQueueWidget._existing_loop_slug_from_path(traversal_path)
        assert result == "my-loop"

    def test_derive_slug_applies_mm_dd_for_fresh_source(self, tmp_path):
        """Fresh source (sem _LOOP-CONFIG.json) recebe slug canonical com
        prefixo mm-dd via shared helper normalize_loop_name.py (single
        source of truth, 2026-05-14)."""
        import re as _re
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        source = tmp_path / "refactor-auth.md"
        source.write_text("# x", encoding="utf-8")
        result = CommandQueueWidget._derive_loop_slug_from_path(str(source))
        assert _re.match(r"^\d{2}-\d{2}-refactor-auth$", result), (
            f"esperado mm-dd-refactor-auth, obtido {result!r}"
        )

    def test_derive_slug_preserves_legacy_loop_without_mm_dd(self, tmp_path):
        """Loop legado sem prefixo mm-dd e preservado as-is (forward-only policy)."""
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        loop_dir = tmp_path / "blog-stockpile-publish-overhaul"
        loop_dir.mkdir()
        (loop_dir / "_LOOP-CONFIG.json").write_text("{}", encoding="utf-8")
        (loop_dir / "source.md").write_text("# x", encoding="utf-8")
        result = CommandQueueWidget._derive_loop_slug_from_path(
            str(loop_dir / "source.md")
        )
        # Codex review 2026-05-14: legado sem mm-dd e preservado, nao renomeado.
        assert result == "blog-stockpile-publish-overhaul"
        assert not result.startswith("05-")  # zero normalizacao no widget

    def test_loop_command_ready_uses_parent_dir_when_source_md(
        self, widget, tmp_path, monkeypatch
    ):
        """E2E: /loop --both .../{loop}/source.md SEM --name -> usa parent dir."""
        loop_dir = tmp_path / "blog-stockpile-publish-overhaul"
        loop_dir.mkdir()
        (loop_dir / "_LOOP-CONFIG.json").write_text("{}", encoding="utf-8")
        source = loop_dir / "source.md"
        source.write_text("# x", encoding="utf-8")
        widget.clear_queue()
        widget._on_loop_command_ready(f"/loop --both {source}")
        names = [item.get_spec().name for item in widget._items]
        assert any(
            "--name blog-stockpile-publish-overhaul" in n for n in names
        ), f"fila: {names}"
        assert not any(
            n.endswith(" --name source") or " --name source " in n for n in names
        ), f"slug bugado 'source': {names}"

    def test_invoke_loop_normalizer_resolves_relative_path(self, tmp_path, monkeypatch):
        """Path relativo eh resolvido via candidate_md_roots antes de chamar helper.

        Regression per codex review 2026-05-14: sem isso, paths relativos
        que so existem fora do cwd do widget escapariam da deteccao de
        re-entry/colisao.
        """
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

        # Cria estrutura fake de loop sob tmp_path
        loop_dir = tmp_path / "fake-loop-relative"
        loop_dir.mkdir()
        (loop_dir / "_LOOP-CONFIG.json").write_text("{}", encoding="utf-8")
        (loop_dir / "source.md").write_text("# x", encoding="utf-8")

        # Muda cwd para parent de tmp_path; path relativo "fake-loop-relative/source.md"
        # so existe se candidate_md_roots tentar tmp_path.
        monkeypatch.chdir(tmp_path)
        result = CommandQueueWidget._invoke_loop_normalizer(
            path="fake-loop-relative/source.md"
        )
        assert result is not None, "helper deveria detectar re-entry com path relativo"
        assert result["was_re_entry"] is True
        assert result["slug"] == "fake-loop-relative"

    def test_loop_command_ready_blocks_on_slug_collision(
        self, widget, tmp_path
    ):
        """Collision guard: --name X divergente de loop existente -> aborta com toast."""
        from PySide6.QtCore import QObject

        loop_dir = tmp_path / "real-loop"
        loop_dir.mkdir()
        (loop_dir / "_LOOP-CONFIG.json").write_text("{}", encoding="utf-8")
        source = loop_dir / "source.md"
        source.write_text("# x", encoding="utf-8")

        toasts: list[tuple[str, str]] = []
        from workflow_app.signal_bus import signal_bus

        class _Sink(QObject):
            def __init__(self):
                super().__init__()
                signal_bus.toast_requested.connect(self._on_toast)

            def _on_toast(self, msg, level):
                toasts.append((msg, level))

        sink = _Sink()
        widget.clear_queue()
        widget._on_loop_command_ready(f"/loop --both {source} --name wrong-name")
        names = [item.get_spec().name for item in widget._items]
        assert names == [], f"fila deveria estar vazia, contem: {names}"
        assert any(
            "Conflito" in m and "wrong-name" in m and "real-loop" in m
            for m, _ in toasts
        ), f"toast esperado, obtido: {toasts}"
        # silenciar warning de unused
        del sink

    def test_grep_gate_zero_slug_or_path_in_output_paths(self):
        """Gate de grep: zero ocorrencias de <slug> ou <path> em caminhos de saida ativos.

        Hardening (review-done Item 002, finding #1 Codex senior-adversarial):
        filtros de palavra-chave (placeholder/label/argument_hint/replace/in inner)
        sao validos apenas na porcao de CODIGO da linha (antes do `#`). Isso impede
        bypass como `parts.append("--name <slug>")  # label`.

        Hardening (finding #2): deteccao de docstring agora conta ocorrencias de
        `\"\"\"` por linha (par mantem estado, impar inverte) — lida com aspas
        triplas que abrem e fecham na mesma linha.
        """
        import re
        from pathlib import Path

        repo_root = Path("/home/pedro/Repositórios/systemForge")
        targets = [
            repo_root / "ai-forge/workflow-app/src/workflow_app/command_queue/command_queue_widget.py",
            repo_root / "ai-forge/workflow-app/src/workflow_app/command_queue/double_phase_dialog.py",
            repo_root / "ai-forge/workflow-app/src/workflow_app/templates/quick_templates.py",
        ]

        suspicious: list[str] = []
        for p in targets:
            if not p.exists():
                continue
            content = p.read_text(encoding="utf-8")
            file_lines = content.split("\n")
            # Primeira passagem: marcar linhas dentro de docstrings (hardened)
            in_docstring = False
            docstring_lines: set[int] = set()
            for idx, raw in enumerate(file_lines, start=1):
                triple_count = raw.count('"""')
                if in_docstring:
                    docstring_lines.add(idx)
                if triple_count % 2 == 1:
                    in_docstring = not in_docstring
                    docstring_lines.add(idx)
            # Segunda passagem: verificar placeholders apenas na porcao de codigo
            for idx, raw in enumerate(file_lines, start=1):
                stripped = raw.strip()
                if "<slug>" not in raw and "<path>" not in raw:
                    continue
                if stripped.startswith("#"):
                    continue
                if idx in docstring_lines:
                    continue
                # Separar codigo de comentario inline (heuristica conservadora:
                # corta no primeiro `#` que nao esta dentro de string literal).
                code_part = raw
                in_single = False
                in_double = False
                cut_at: int | None = None
                for i, ch in enumerate(raw):
                    if ch == "'" and not in_double:
                        in_single = not in_single
                    elif ch == '"' and not in_single:
                        in_double = not in_double
                    elif ch == "#" and not in_single and not in_double:
                        cut_at = i
                        break
                if cut_at is not None:
                    code_part = raw[:cut_at]
                # Placeholder no comentario inline e ignorado (nao chega ao output).
                if "<slug>" not in code_part and "<path>" not in code_part:
                    continue
                # Filtros de contexto valem apenas na porcao de codigo.
                allow_tokens = ("placeholder", "label", "argument_hint", "replace(", "in inner")
                if any(tok in code_part for tok in allow_tokens):
                    continue
                suspicious.append(f"{p.name}:{idx}: {raw.strip()}")

        assert len(suspicious) == 0, f"Linhas suspeitas de output ativo com placeholder: {suspicious}"


# ─── queue-btn-study: expansao canonica por --simple/--deep/--heavy ───────── #


def _spec_names(widget) -> list[str]:
    return [item.get_spec().name for item in widget._items]


class TestStudyButtonExpandsByMode:
    """`_on_study_command_ready` materializa a sequencia canonica de subcomandos
    `/study:*` conforme `.claude/commands/study.md` FASE 2, com /clear + /model +
    /effort entre cada fase (GROUP_MAP["study"] = Opus/HIGH).

    Contratos verificados:
      - --simple (default): 7 fases (scope, research, write-user, review-user,
        write-tech, validate, publish).
      - --deep: 9 fases (+triangulate, +debate).
      - --heavy: 9 fases (scope-decompose, enumerate, loop-research, loop-synth,
        consolidate-user, review-user, consolidate-tech, validate, publish).
      - Primeira fase recebe bloco /clear + /model opus + /effort high (secao
        3.4); demais fases recebem APENAS /clear (anti-redundancia secao 3.1,
        pois todas rodam opus/high). Salto para sonnet/standard no --loop
        reemite o bloco (secao 4).
      - --loop <path>: /study:publish recebe `--loop <path>` E auq-interview
        e anexado como ultimo item (Task-023 preservado).
      - --name explicito vence; senao deriva do path.md, senao slugifica prompt.
    """

    def _phase_indices(self, names: list[str]) -> list[int]:
        return [i for i, n in enumerate(names) if n.startswith("/study:") or n.startswith("/tools:auq-interview")]

    def test_simple_mode_default_renders_seven_phases(self, widget):
        widget._on_study_command_ready('/study "duvida" --name foo')
        names = _spec_names(widget)
        study_phases = [n for n in names if n.startswith("/study:")]
        assert len(study_phases) == 7
        assert study_phases[0].startswith("/study:scope ")
        assert "--name foo" in study_phases[0]
        assert study_phases[1] == "/study:research --name foo"
        assert study_phases[2] == "/study:write-user --name foo"
        assert study_phases[3] == "/study:review-user --name foo"
        assert study_phases[4] == "/study:write-tech --name foo"
        assert study_phases[5] == "/study:validate --name foo"
        assert study_phases[6] == "/study:publish --name foo"

    def test_deep_mode_renders_nine_phases_with_triangulate_and_debate(self, widget):
        widget._on_study_command_ready('/study "duvida" --name foo --deep')
        names = _spec_names(widget)
        study_phases = [n for n in names if n.startswith("/study:")]
        assert len(study_phases) == 9
        assert study_phases[2] == "/study:triangulate --name foo"
        assert study_phases[4] == "/study:debate --name foo"
        assert study_phases[-1] == "/study:publish --name foo"

    def test_heavy_mode_renders_nine_phases_with_decompose_and_consolidate(self, widget):
        widget._on_study_command_ready('/study "duvida" --name foo --heavy')
        names = _spec_names(widget)
        study_phases = [n for n in names if n.startswith("/study:")]
        assert len(study_phases) == 9
        assert study_phases[0].startswith("/study:scope-decompose ")
        assert study_phases[1] == "/study:enumerate --name foo"
        assert study_phases[2] == "/study:loop-research --name foo"
        assert study_phases[3] == "/study:loop-synth --name foo"
        assert study_phases[4] == "/study:consolidate-user --name foo"
        assert study_phases[5] == "/study:review-user --name foo"
        assert study_phases[6] == "/study:consolidate-tech --name foo"
        assert study_phases[7] == "/study:validate --name foo"
        assert study_phases[8] == "/study:publish --name foo"

    def test_first_phase_full_block_rest_clear_only(self, widget):
        widget._on_study_command_ready('/study "duvida" --name foo')
        names = _spec_names(widget)
        # Anti-redundancia (ai-forge/rules/workflow-app-command-lists.md secao
        # 3.1, REGRA INVIOLAVEL): todas as 7 fases rodam opus/high, entao /model
        # e /effort sao emitidos UMA vez (primeira fase, secao 3.4); as demais
        # recebem APENAS /clear. Total = 3 (prep) + 7 fases + 6 /clear = 16.
        assert len(names) == 16
        # Primeira fase: bloco completo.
        assert names[0] == "/clear"
        assert names[1] == "/model opus"
        assert names[2] == "/effort high"
        assert names[3].startswith("/study:scope ")
        # secao 3.1: /model e /effort emitidos exatamente uma vez no total.
        assert sum(1 for n in names if n.startswith("/model ")) == 1
        assert sum(1 for n in names if n.startswith("/effort ")) == 1
        # Cada fase real (7) precedida por exatamente um /clear (7 no total).
        reals = [n for n in names if n.startswith("/study:")]
        assert len(reals) == 7
        assert sum(1 for n in names if n == "/clear") == 7

    def test_loop_propagates_to_publish_and_appends_auq_interview(self, widget):
        widget._on_study_command_ready('/study "duvida" --name foo --loop bar.md')
        names = _spec_names(widget)
        publish = [n for n in names if n.startswith("/study:publish")][0]
        assert publish == "/study:publish --name foo --loop bar.md"
        assert names[-1] == "/tools:auq-interview --optimize bar.md"

    def test_loop_quoted_path_with_spaces_is_preserved_in_publish(self, widget):
        widget._on_study_command_ready(
            '/study "duvida" --name foo --loop "blacksmith/loop/05-15 study/source.md"'
        )
        names = _spec_names(widget)
        publish = [n for n in names if n.startswith("/study:publish")][0]
        # shlex.quote encapsula o path com espaco em aspas simples.
        assert "blacksmith/loop/05-15 study/source.md" in publish
        assert names[-1] == "/tools:auq-interview --optimize blacksmith/loop/05-15 study/source.md"

    def test_no_loop_keeps_publish_without_loop_and_no_auq(self, widget):
        widget._on_study_command_ready('/study "duvida" --name foo --deep')
        names = _spec_names(widget)
        publish = [n for n in names if n.startswith("/study:publish")][0]
        assert publish == "/study:publish --name foo"
        assert all("auq-interview" not in n for n in names)

    def test_loop_flag_without_value_does_not_append_auq(self, widget):
        widget._on_study_command_ready('/study "duvida" --name foo --loop')
        names = _spec_names(widget)
        assert all("auq-interview" not in n for n in names)

    def test_loop_flag_followed_by_other_flag_does_not_append_auq(self, widget):
        widget._on_study_command_ready('/study "duvida" --loop --name foo')
        names = _spec_names(widget)
        assert all("auq-interview" not in n for n in names)

    def test_loop_without_positional_injects_loop_path_as_scope_input(self, widget):
        """Fallback canonico (study.md FASE 1 regra 44): sem posicional + --loop
        presente -> a PRIMEIRA fase recebe loop_path como input_path para que
        scope-decompose/scope saiba o que estudar. Antes do fix o handler
        empilhava `/study:scope-decompose --name <slug>` cego.
        """
        widget._on_study_command_ready(
            '/study --loop blacksmith/loop/05-15-dcp-pipeline-perfect-flow-final.md --heavy --name study'
        )
        names = _spec_names(widget)
        first_phase = [n for n in names if n.startswith("/study:")][0]
        assert first_phase.startswith("/study:scope-decompose ")
        assert "blacksmith/loop/05-15-dcp-pipeline-perfect-flow-final.md" in first_phase
        assert "--name study" in first_phase
        # Write-back continua propagando para /study:publish.
        publish = [n for n in names if n.startswith("/study:publish")][0]
        assert "--loop blacksmith/loop/05-15-dcp-pipeline-perfect-flow-final.md" in publish

    def test_loop_without_positional_simple_mode_uses_scope(self, widget):
        widget._on_study_command_ready(
            '/study --loop blacksmith/loop/topic.md --simple'
        )
        names = _spec_names(widget)
        first_phase = [n for n in names if n.startswith("/study:")][0]
        assert first_phase.startswith("/study:scope ")
        assert "blacksmith/loop/topic.md" in first_phase
        # Slug deriva do stem do loop_path quando --name ausente.
        assert "--name topic" in first_phase

    def test_loop_with_positional_keeps_positional_does_not_duplicate(self, widget):
        """Quando user fornece posicional E --loop, posicional vence (sem dup)."""
        widget._on_study_command_ready(
            '/study briefings/topic.md --loop blacksmith/loop/dest.md --simple --name foo'
        )
        names = _spec_names(widget)
        first_phase = [n for n in names if n.startswith("/study:")][0]
        assert "briefings/topic.md" in first_phase
        assert "blacksmith/loop/dest.md" not in first_phase
        publish = [n for n in names if n.startswith("/study:publish")][0]
        assert "--loop blacksmith/loop/dest.md" in publish

    def test_resubmit_replaces_queue_not_appends(self, widget):
        widget._on_study_command_ready('/study "a" --name foo --loop bar.md')
        first_len = len(widget._items)
        widget._on_study_command_ready('/study "a" --name foo --loop bar.md')
        # pipeline_ready substitui (clear + load), nao acumula.
        assert len(widget._items) == first_len

    def test_name_derived_from_path_md_when_not_explicit(self, widget):
        widget._on_study_command_ready('/study briefings/topic.md --simple')
        names = _spec_names(widget)
        study_phases = [n for n in names if n.startswith("/study:")]
        # Slug derivado do stem "topic".
        assert all("--name topic" in n for n in study_phases[1:])

    def test_name_slugified_from_prompt_when_no_path(self, widget):
        widget._on_study_command_ready('/study "investigar Server Actions"')
        names = _spec_names(widget)
        # slugify("investigar Server Actions") -> "investigar-server-actions"
        assert any("--name investigar-server-actions" in n for n in names)


class TestLegacyToDcpButton:
    """Cobertura do botao `queue-btn-legacy-to-dcp` (pipeline legacy-to-dcp).

    Garante:
      - botao existe em queue-tab-auxiliar com testid esperado;
      - sem project.json carregado (Gate 1) emite toast pt-BR e nao enfileira;
      - com project.json valido enfileira a sequencia canonica de 12 specs
        (4 blocos de directives prep + 1 cmd cada, mais bloco final high).
    """

    def _find_button_by_testid(self, widget: CommandQueueWidget, testid: str):
        from PySide6.QtWidgets import QPushButton
        header = getattr(widget, "header_widget", None)
        search_root = header if header is not None else widget
        for btn in search_root.findChildren(QPushButton):
            if btn.property("testid") == testid:
                return btn
        return None

    def test_button_exists_with_testid(self, widget):
        btn = self._find_button_by_testid(widget, "queue-btn-legacy-to-dcp")
        assert btn is not None, "queue-btn-legacy-to-dcp ausente em queue-tab-auxiliar"

    def test_button_tooltip_mentions_canonical_loop(self, widget):
        btn = self._find_button_by_testid(widget, "queue-btn-legacy-to-dcp")
        assert btn is not None
        tip = btn.toolTip()
        assert "Legacy-to-DCP" in tip
        assert "canonical loop A..I" in tip
        assert "/legacy:detect" in tip
        assert "metrics-project-pill" in tip

    def test_click_without_config_emits_verbose_pt_br_toast(self, widget, qtbot):
        from PySide6.QtCore import Qt

        from workflow_app.config.app_state import app_state

        toasts: list[tuple[str, str]] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        pipelines: list[list] = []
        signal_bus.pipeline_ready.connect(lambda specs: pipelines.append(list(specs)))

        # Force has_config False (no project loaded).
        app_state.clear_config()
        assert not app_state.has_config

        btn = self._find_button_by_testid(widget, "queue-btn-legacy-to-dcp")
        assert btn is not None
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

        assert pipelines == [], "nao deve enfileirar quando sem config"
        assert toasts, "esperado toast verboso quando sem config"
        msg, kind = toasts[-1]
        assert "project.json" in msg
        assert "queue-btn-json" in msg
        assert kind == "warning"

    def test_click_with_config_enqueues_canonical_sequence(
        self, widget, qtbot, tmp_path,
    ):
        from PySide6.QtCore import Qt

        from workflow_app.command_queue.command_queue_widget import GROUP_MAP
        from workflow_app.config.app_state import app_state

        project_json = tmp_path / "test-project.json"
        project_json.write_text(
            '{"name":"test-project","basic_flow":{"wbs_root":"wbs"}}',
            encoding="utf-8",
        )
        # Use the real loader path (app_state.load_config(path) expects a
        # readable ProjectConfig). We bypass strict validation by setting
        # attributes directly to keep this test surgical.
        from types import SimpleNamespace

        fake_cfg = SimpleNamespace(
            config_path=str(project_json),
            raw={"name": "test-project"},
            project_name="test-project",
        )
        app_state.clear_config()
        app_state.set_config(fake_cfg)  # type: ignore[arg-type]
        assert app_state.has_config

        pipelines: list[list] = []
        signal_bus.pipeline_ready.connect(lambda specs: pipelines.append(list(specs)))

        btn = self._find_button_by_testid(widget, "queue-btn-legacy-to-dcp")
        assert btn is not None
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

        assert pipelines, "esperado pipeline_ready emitido"
        specs = pipelines[-1]
        names = [s.name for s in specs]
        # Pos-codex-review 2026-05-17: pipeline reduzida para 5 cmds reais
        # (sem etapa /project-json --migrate-v3, que nao existe como branch).
        # /legacy:detect agora aborta V1/V2 com exit 2 + gap em pending-actions.
        # 5 blocos de prep (3 specs cada) + 5 cmds = 20 specs.
        prep_count = sum(1 for n in names if n in ("/clear",))
        assert prep_count == 5, f"esperado 5 /clear (1 por bloco), achei {prep_count}"
        assert any(n.startswith("/legacy:detect ") for n in names)
        # NAO deve existir /project-json --migrate-v3 (cmd inexistente):
        assert not any("--migrate-v3" in n for n in names), (
            "Regressao: handler legacy-to-dcp nao deve enfileirar "
            "/project-json --migrate-v3 (branch nao existe no /project-json)"
        )
        assert any(n.startswith("/delivery:init --if-missing ") for n in names)
        assert any(n.startswith("/legacy:modules-from-features ") for n in names)
        assert any(n.startswith("/dcp:meta-completeness --all --auto-fix-p0 ") for n in names)
        assert any(n.startswith("/legacy:enqueue-all-modules ") for n in names)
        # Project path injetado em cada cmd real (5).
        path_str = str(project_json)
        cmd_with_path = [n for n in names if path_str in n]
        assert len(cmd_with_path) == 5
        # GROUP_MAP usa sonnet/medium nos 4 primeiros blocos; ultimo bloco usa high.
        group = GROUP_MAP["legacy_to_dcp"]
        assert group["model"] == ModelName.SONNET
        assert group["effort"] == EffortLevel.STANDARD
        # Confirma directive final high
        effort_high_idx = [i for i, n in enumerate(names) if n == "/effort high"]
        assert effort_high_idx, "esperado pelo menos um /effort high para enqueue-all-modules"


# ---------------------------------------------------------------------------
# Multibackend — botao queue-btn-multibackend
# ---------------------------------------------------------------------------


class TestMultibackendButton:
    """Cobertura do botao `queue-btn-multibackend` (pipeline multibackend).

    Garante:
      - botao existe em queue-tab-auxiliar com testid esperado;
      - sem project.json carregado (Gate 1) emite toast pt-BR e nao enfileira;
      - com project.json valido enfileira os 6 subcomandos /multibackend:* na
        ordem canonica (scan -> link-auth -> env-wire -> build-verify ->
        deploy -> verify-prod), cada um com config_path como $1, todos
        opus/high (GROUP_MAP["multibackend"]).
    """

    def _find_button_by_testid(self, widget: CommandQueueWidget, testid: str):
        from PySide6.QtWidgets import QPushButton
        header = getattr(widget, "header_widget", None)
        search_root = header if header is not None else widget
        for btn in search_root.findChildren(QPushButton):
            if btn.property("testid") == testid:
                return btn
        return None

    def test_button_exists_with_testid(self, widget):
        btn = self._find_button_by_testid(widget, "queue-btn-multibackend")
        assert btn is not None, "queue-btn-multibackend ausente em queue-tab-auxiliar"

    def test_button_tooltip_mentions_pipeline(self, widget):
        btn = self._find_button_by_testid(widget, "queue-btn-multibackend")
        assert btn is not None
        tip = btn.toolTip()
        assert "Multibackend" in tip
        assert "/multibackend:scan" in tip
        assert "/multibackend:verify-prod" in tip
        assert "metrics-project-pill" in tip

    def test_group_map_multibackend_is_opus_high(self):
        from workflow_app.command_queue.command_queue_widget import GROUP_MAP

        group = GROUP_MAP["multibackend"]
        assert group["model"] == ModelName.OPUS
        assert group["effort"] == EffortLevel.HIGH

    def test_click_without_config_emits_verbose_pt_br_toast(self, widget, qtbot):
        from PySide6.QtCore import Qt

        from workflow_app.config.app_state import app_state

        toasts: list[tuple[str, str]] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        pipelines: list[list] = []
        signal_bus.pipeline_ready.connect(lambda specs: pipelines.append(list(specs)))

        # Force has_config False (no project loaded).
        app_state.clear_config()
        assert not app_state.has_config

        btn = self._find_button_by_testid(widget, "queue-btn-multibackend")
        assert btn is not None
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

        assert pipelines == [], "nao deve enfileirar quando sem config"
        assert toasts, "esperado toast verboso quando sem config"
        msg, kind = toasts[-1]
        assert "project.json" in msg
        assert "queue-btn-json" in msg
        assert kind == "warning"

    def test_click_with_config_enqueues_six_subcommands_with_path(
        self, widget, qtbot, tmp_path,
    ):
        from PySide6.QtCore import Qt

        from workflow_app.command_queue.command_queue_widget import GROUP_MAP
        from workflow_app.config.app_state import app_state

        project_json = tmp_path / "test-project.json"
        project_json.write_text(
            '{"name":"test-project","basic_flow":{"wbs_root":"wbs"}}',
            encoding="utf-8",
        )
        from types import SimpleNamespace

        fake_cfg = SimpleNamespace(
            config_path=str(project_json),
            raw={"name": "test-project"},
            project_name="test-project",
        )
        app_state.clear_config()
        app_state.set_config(fake_cfg)  # type: ignore[arg-type]
        assert app_state.has_config

        pipelines: list[list] = []
        signal_bus.pipeline_ready.connect(lambda specs: pipelines.append(list(specs)))

        btn = self._find_button_by_testid(widget, "queue-btn-multibackend")
        assert btn is not None
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

        assert pipelines, "esperado pipeline_ready emitido"
        specs = pipelines[-1]
        names = [s.name for s in specs]
        path_str = str(project_json)

        # Os 6 subcomandos reais na ordem canonica, cada um com $1 = config_path.
        expected_subcmds = [
            f"/multibackend:scan {path_str}",
            f"/multibackend:link-auth {path_str}",
            f"/multibackend:env-wire {path_str}",
            f"/multibackend:build-verify {path_str}",
            f"/multibackend:deploy {path_str}",
            f"/multibackend:verify-prod {path_str}",
        ]
        real = [n for n in names if n.startswith("/multibackend:")]
        assert real == expected_subcmds, (
            f"ordem/contrato dos subcomandos incorreto: {real}"
        )
        # Cada subcomando carrega o path do project.json como $1.
        assert all(path_str in n for n in real)
        assert len(real) == 6

        # Todos os specs reais sao opus/high (GROUP_MAP["multibackend"]).
        real_specs = [s for s in specs if s.name.startswith("/multibackend:")]
        group = GROUP_MAP["multibackend"]
        assert group["model"] == ModelName.OPUS
        assert group["effort"] == EffortLevel.HIGH
        for s in real_specs:
            assert s.model == ModelName.OPUS
            assert s.effort == EffortLevel.HIGH

        # _inject_clears poe um /clear antes de cada subcomando (6 ao todo) +
        # o triplet model/effort uma unica vez (grupo unico opus/high).
        assert names.count("/clear") == 6, (
            f"esperado 6 /clear (1 por subcomando), achei {names.count('/clear')}"
        )
        assert names.count("/model opus") == 1
        assert names.count("/effort high") == 1


# ---------------------------------------------------------------------------
# Governance — botao queue-btn-governance
# ---------------------------------------------------------------------------


class TestGovernanceButton:
    def _find_button_by_testid(self, widget: CommandQueueWidget, testid: str):
        from PySide6.QtWidgets import QPushButton

        header = getattr(widget, "header_widget", None)
        search_root = header if header is not None else widget
        for btn in search_root.findChildren(QPushButton):
            if btn.property("testid") == testid:
                return btn
        return None

    @pytest.fixture(autouse=True)
    def _isolate_app_state(self):
        from workflow_app.config.app_state import app_state

        app_state.clear_config()
        yield
        app_state.clear_config()

    def _set_config(self, tmp_path, *, docs_root: str = "docs"):
        from types import SimpleNamespace

        from workflow_app.config.app_state import app_state

        cfg = SimpleNamespace(
            config_path=str(tmp_path / ".claude" / "project.json"),
            project_dir=tmp_path,
            docs_root=docs_root,
            raw={"name": "governance-test"},
            project_name="governance-test",
        )
        app_state.set_config(cfg)  # type: ignore[arg-type]
        return cfg

    def _ledger(self, tmp_path):
        ledger = tmp_path / "docs" / "_pipeline-research" / "PIPELINE-RUNS.tsv"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        return ledger

    def _approved_dryrun(self, tmp_path):
        report = (
            tmp_path
            / "scheduled-updates"
            / "governance-dry-run"
            / "GOVERNANCE-DRYRUN-20260604T000000Z.md"
        )
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "# Governance dry-run\n\nforbidden_writes: 0\n",
            encoding="utf-8",
        )
        return report

    def test_button_exists_with_testid(self, widget):
        btn = self._find_button_by_testid(widget, "queue-btn-governance")
        assert btn is not None

    def test_absent_ledger_disables_button_with_tooltip(self, widget, tmp_path):
        self._set_config(tmp_path)
        widget._refresh_governance_button_state()

        btn = self._find_button_by_testid(widget, "queue-btn-governance")
        assert btn is not None
        assert not btn.isEnabled()
        assert "PIPELINE-RUNS.tsv ausente" in btn.toolTip()

    def test_header_only_ledger_disables_button_with_tooltip(self, widget, tmp_path):
        self._set_config(tmp_path)
        self._ledger(tmp_path).write_text("started_at\tstatus\n", encoding="utf-8")
        widget._refresh_governance_button_state()

        btn = self._find_button_by_testid(widget, "queue-btn-governance")
        assert btn is not None
        assert not btn.isEnabled()
        assert "nao tem linhas de dados" in btn.toolTip()

    def test_ledger_with_data_without_approved_dryrun_disables_button(
        self, widget, tmp_path,
    ):
        self._set_config(tmp_path)
        self._ledger(tmp_path).write_text(
            "started_at\tstatus\n2026-06-03T00:00:00Z\tok\n",
            encoding="utf-8",
        )
        widget._refresh_governance_button_state()

        btn = self._find_button_by_testid(widget, "queue-btn-governance")
        assert btn is not None
        assert not btn.isEnabled()
        assert "dry-run" in btn.toolTip()
        assert "antes de aplicar" in btn.toolTip()

    def test_ledger_with_data_and_approved_dryrun_enables_button(
        self, widget, tmp_path,
    ):
        self._set_config(tmp_path)
        self._ledger(tmp_path).write_text(
            "started_at\tstatus\n2026-06-03T00:00:00Z\tok\n",
            encoding="utf-8",
        )
        self._approved_dryrun(tmp_path)
        widget._refresh_governance_button_state()

        btn = self._find_button_by_testid(widget, "queue-btn-governance")
        assert btn is not None
        assert btn.isEnabled()

    def test_aborted_dryrun_keeps_button_disabled(self, widget, tmp_path):
        self._set_config(tmp_path)
        self._ledger(tmp_path).write_text(
            "started_at\tstatus\n2026-06-03T00:00:00Z\tok\n",
            encoding="utf-8",
        )
        report = self._approved_dryrun(tmp_path)
        report.write_text(
            "# Governance dry-run\n\nforbidden_writes: 0\nABORTADO\n",
            encoding="utf-8",
        )
        widget._refresh_governance_button_state()

        btn = self._find_button_by_testid(widget, "queue-btn-governance")
        assert btn is not None
        assert not btn.isEnabled()

    def test_config_loaded_signal_refreshes_governance_button(self, widget, tmp_path):
        self._set_config(tmp_path)
        self._ledger(tmp_path).write_text(
            "started_at\tstatus\n2026-06-03T00:00:00Z\tok\n",
            encoding="utf-8",
        )
        self._approved_dryrun(tmp_path)

        btn = self._find_button_by_testid(widget, "queue-btn-governance")
        assert btn is not None
        assert not btn.isEnabled()

        signal_bus.config_loaded.emit(str(tmp_path / ".claude" / "project.json"))

        assert btn.isEnabled()

    def test_config_unloaded_signal_disables_governance_button(self, widget, tmp_path):
        from workflow_app.config.app_state import app_state

        self._set_config(tmp_path)
        self._ledger(tmp_path).write_text(
            "started_at\tstatus\n2026-06-03T00:00:00Z\tok\n",
            encoding="utf-8",
        )
        self._approved_dryrun(tmp_path)
        widget._refresh_governance_button_state()

        btn = self._find_button_by_testid(widget, "queue-btn-governance")
        assert btn is not None
        assert btn.isEnabled()

        app_state.clear_config()
        signal_bus.config_unloaded.emit()

        assert not btn.isEnabled()
        assert "project.json" in btn.toolTip()

    def test_click_confirms_paths_and_enqueues_expanded_governance_chain(
        self, widget, qtbot, tmp_path, monkeypatch,
    ):
        from PySide6.QtCore import Qt

        from workflow_app.command_queue.command_queue_widget import (
            GOVERNANCE_COMMANDS,
            GOVERNANCE_WRITE_TARGETS,
        )

        self._set_config(tmp_path)
        ledger = self._ledger(tmp_path)
        ledger.write_text(
            "started_at\tstatus\n2026-06-03T00:00:00Z\tok\n",
            encoding="utf-8",
        )
        self._approved_dryrun(tmp_path)
        widget._refresh_governance_button_state()

        confirmed: list[str] = []

        def _confirm(path):
            assert path == ledger
            confirmed.extend(GOVERNANCE_WRITE_TARGETS)
            return True

        monkeypatch.setattr(widget, "_confirm_governance_write_scope", _confirm)

        pipelines: list[list] = []
        signal_bus.pipeline_ready.connect(lambda specs: pipelines.append(list(specs)))

        btn = self._find_button_by_testid(widget, "queue-btn-governance")
        assert btn is not None
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

        assert confirmed
        assert "docs_root/_pipeline-research/" in confirmed
        assert pipelines, "esperado pipeline_ready emitido"
        names = [spec.name for spec in pipelines[-1]]
        for command in GOVERNANCE_COMMANDS:
            assert command in names
        assert "/auto-flow governance" not in names


# ---------------------------------------------------------------------------
# Cmd Single — radio "kimi analyse" | "kimi certain" + anti-redundancia §3.1
# (ai-forge/rules/workflow-app-command-lists.md)
# ---------------------------------------------------------------------------


class TestCmdSingleKimiModes:
    """Valida as duas variantes do cmd-single e a conformidade com §3.1
    (model/effort emitidos uma unica vez; /clear entre grupos independentes).
    """

    @pytest.fixture(autouse=True)
    def _isolate_app_state(self):
        # Outro teste deste arquivo (test_handler_uses_app_state_config_dir)
        # deixa um SimpleNamespace sem project_dir em app_state.config. Sem
        # config, o cmd-single resolve base_dir pelo walk-up do .md (caminho
        # real testado aqui). Limpa antes e depois para nao vazar nem herdar.
        from workflow_app.config.app_state import app_state
        app_state.clear_config()
        yield
        app_state.clear_config()

    def _md(self, tmp_path):
        md = tmp_path / "cmd.md"
        md.write_text("# /test:cmd\ncmd_target: /test:cmd\n", encoding="utf-8")
        return md

    def test_kimi_analyse_pair_has_no_force(self, widget, tmp_path):
        md = self._md(tmp_path)
        widget.clear_queue()
        widget._on_loop_command_ready(f"/loop --cmd-single {md} --name test-cmd")
        names = [item.get_spec().name for item in widget._items]
        analyse = [n for n in names if n.startswith("/cmd:kimi-pair-analyse")]
        execute = [n for n in names if n.startswith("/cmd:kimi-pair-execute")]
        assert analyse == ["/cmd:kimi-pair-analyse /test:cmd"]
        assert execute == [
            "/cmd:kimi-pair-execute blacksmith/test:cmd-kimi-pair-report.md"
        ]
        assert not any("--force" in n for n in names)

    def test_kimi_certain_forces_both_pair_steps(self, widget, tmp_path):
        md = self._md(tmp_path)
        widget.clear_queue()
        widget._on_loop_command_ready(
            f"/loop --cmd-single {md} --name test-cmd --certain"
        )
        names = [item.get_spec().name for item in widget._items]
        assert "/cmd:kimi-pair-analyse --force /test:cmd" in names
        assert (
            "/cmd:kimi-pair-execute --force blacksmith/test:cmd-kimi-pair-report.md"
            in names
        )

    def test_cmd_single_anti_redundancy_single_model_effort(self, widget, tmp_path):
        """§3.1: model/effort sao emitidos UMA vez; grupos seguintes so /clear."""
        md = self._md(tmp_path)
        widget.clear_queue()
        widget._on_loop_command_ready(f"/loop --cmd-single {md} --name test-cmd")
        names = [item.get_spec().name for item in widget._items]
        assert sum(1 for n in names if n.startswith("/model ")) == 1
        assert sum(1 for n in names if n.startswith("/effort ")) == 1
        # 4 grupos (create | review | kimi-pair | readme) => 4 /clear boundaries.
        assert names.count("/clear") == 4
        # Real commands na ordem canonica, par kimi-pair adjacente (sem /clear).
        reais = [n for n in names if not n.startswith(("/clear", "/model", "/effort"))]
        assert reais == [
            f"/cmd:create {md}",
            "/cmd:review /test:cmd " + str(md),
            "/cmd:kimi-pair-analyse /test:cmd",
            "/cmd:kimi-pair-execute blacksmith/test:cmd-kimi-pair-report.md",
            "/cmd:readme-upd",
        ]

    def test_cmd_single_first_group_has_full_prep(self, widget, tmp_path):
        """§3.4: primeiro grupo sempre /clear /model /effort na partida."""
        md = self._md(tmp_path)
        widget.clear_queue()
        widget._on_loop_command_ready(f"/loop --cmd-single {md} --name test-cmd")
        names = [item.get_spec().name for item in widget._items]
        assert names[0] == "/clear"
        assert names[1].startswith("/model ")
        assert names[2].startswith("/effort ")


class TestStepPathInvokesProviderRouter:
    """Task 004 (06-02-seta-unica-multi-llm-queue): o step path consome o router
    PURO provider_router.classify_provider, montando o RoutingState a partir do
    estado da queue (checkboxes de worker + Main LLM) e APOS o Worker axis
    (invariante 2). Nesta task o resultado fica em _last_classified_provider e
    NAO altera roteamento/UI; estes testes apenas garantem a integracao."""

    @pytest.fixture()
    def real_spec(self) -> list[CommandSpec]:
        return [CommandSpec("/prd-create", ModelName.OPUS, EffortLevel.HIGH, position=1)]

    def test_classify_provider_called_with_routing_state(self, widget, real_spec):
        """O step path chama classify_provider com um RoutingState montado a
        partir dos checkboxes de worker e do Main LLM (nunca route-toggles)."""
        from unittest.mock import patch

        from workflow_app.command_queue.provider_router import Provider, RoutingState

        widget.load_pipeline(real_spec)
        widget._use_kimi_chk.setChecked(True)
        if getattr(widget, "_use_codex_chk", None) is not None:
            widget._use_codex_chk.setChecked(False)

        with patch(
            "workflow_app.command_queue.command_queue_widget.classify_provider",
            return_value=Provider.KIMI,
        ) as mock_classify:
            widget._on_step_btn_clicked()

        assert mock_classify.called, (
            "_on_step_btn_clicked deve invocar classify_provider no step path."
        )
        called_spec, called_state = mock_classify.call_args.args
        assert called_spec is widget._items[0].get_spec() or \
            called_spec.name == "/prd-create"
        assert isinstance(called_state, RoutingState)
        assert called_state.kimi_worker_enabled is True
        assert called_state.codex_worker_enabled is False
        assert called_state.main_llm == "claude"
        assert widget._last_classified_provider == Provider.KIMI

    def test_routing_state_reflects_codex_worker_and_main_llm(self, widget, real_spec):
        """codex_worker_enabled e main_llm refletem o estado vivo da queue."""
        from unittest.mock import patch

        from workflow_app.command_queue.provider_router import Provider, RoutingState

        if getattr(widget, "_use_codex_chk", None) is None or \
                getattr(widget, "_force_kimi_chk", None) is None:
            pytest.skip("widget sem checkboxes de worker codex / main kimi")

        widget.load_pipeline(real_spec)
        widget._use_kimi_chk.setChecked(False)
        widget._use_codex_chk.setChecked(True)
        widget._force_kimi_chk.setChecked(True)  # Main LLM = kimi

        captured: dict[str, RoutingState] = {}

        def _capture(spec, state):
            captured["state"] = state
            return Provider.CODEX

        with patch(
            "workflow_app.command_queue.command_queue_widget.classify_provider",
            side_effect=_capture,
        ):
            widget._on_step_btn_clicked()

        state = captured["state"]
        assert state.kimi_worker_enabled is False
        assert state.codex_worker_enabled is True
        assert state.main_llm == "kimi"

    def test_classify_runs_for_helper_items_too(self, widget):
        """O router e avaliado para todo item do step path, inclusive helpers
        (/clear, /model, /effort) — nenhum item escapa da classificacao."""
        from unittest.mock import patch

        from workflow_app.command_queue.provider_router import Provider

        helpers = [
            CommandSpec("/clear", ModelName.SONNET, position=1),
            CommandSpec("/model opus", ModelName.OPUS, position=2),
        ]
        widget.load_pipeline(helpers)

        with patch(
            "workflow_app.command_queue.command_queue_widget.classify_provider",
            return_value=Provider.CLAUDE,
        ) as mock_classify:
            widget._on_step_btn_clicked()
            widget._on_step_btn_clicked()

        assert mock_classify.call_count == 2, (
            "classify_provider deve rodar uma vez por item do step path."
        )


# ---------------------------------------------------------------------------
# Item 006 — Dispatch Codex/T3 + condicoes de falha obrigatorias
# (source.md secao 10 + casos 5, 6, 9, 10 da secao 14)
# ---------------------------------------------------------------------------

class TestSingleButtonDispatchFailureConditions:
    """Botao unico (task 005) + dispatchers EXISTENTES (task 006).

    Cobre as 4 condicoes de falha obrigatorias (source.md secao 10) e os casos
    5, 6, 9, 10 da secao 14:
      - C2/caso 5: worker desligado pos-render -> clique recalcula provider e
        nao usa destino stale.
      - caso 6: local-action nunca publica em worker (invariante 8).
      - C1/caso 9: comando inexistente aborta com toast e nao publica texto
        parcial (invariante 10).
      - caso 10: Main LLM Kimi + worker Codex produz par emergente Kimi/T1 +
        Codex/T3.
      - C3: adaptacao Kimi/Codex vazia aborta.
      - C4: terminal alvo Codex/T3 nao pronto aborta com feedback visivel.
    """

    @pytest.fixture()
    def disp_widget(self, widget, tmp_path, monkeypatch):
        """widget com command files resolviveis para os slugs usados aqui,
        de modo que o builder do executor Codex e o gate de lookup tenham
        comandos reais para encontrar."""
        files: dict[str, object] = {}
        # qa:prep / blog:init-strategy sao kimi-compatible (blue-arrow);
        # commit:simple resolve mas NAO e kimi-compatible (green-arrow only);
        # cmd:review e codex-compatible (Codex whitelist) mas NAO kimi-compatible.
        for slug in ("qa:prep", "blog:init-strategy", "commit:simple", "cmd:review"):
            f = tmp_path / ".claude" / "commands" / (slug.replace(":", "/") + ".md")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("# cmd", encoding="utf-8")
            files[slug] = f
        agent_file = tmp_path / "executor.md"
        agent_file.write_text("# executor", encoding="utf-8")
        listener_file = tmp_path / "listeners.md"
        listener_file.write_text("# listeners", encoding="utf-8")
        monkeypatch.setattr(
            type(widget),
            "_resolve_claude_command_file",
            classmethod(lambda cls, slug: files.get(slug)),
        )
        monkeypatch.setattr(
            type(widget),
            "_resolve_codex_executor_agent_file",
            classmethod(lambda cls: agent_file),
        )
        monkeypatch.setattr(
            type(widget),
            "_resolve_listener_rules_file",
            classmethod(lambda cls: listener_file),
        )
        return widget

    # ---- caso 5 — worker desligado pos-render --------------------------- #
    def test_worker_off_after_render_recalculates_on_click(self, disp_widget):
        """Caso 5: item renderizado com worker Kimi ON fica azul/T2; se o
        worker e desligado ENTRE render e clique, o clique do botao unico
        recalcula o provider AGORA e cai no destino correto (Claude/T1), nunca
        no destino stale (Kimi/T2)."""
        from workflow_app.command_queue.provider_router import Provider

        disp_widget._main_claude_radio.setChecked(True)
        disp_widget._use_kimi_chk.setChecked(True)
        disp_widget.load_pipeline(
            [CommandSpec("/qa:prep", ModelName.SONNET, position=1)]
        )
        item = disp_widget._items[0]
        # Renderizado azul/T2 enquanto o worker Kimi estava ativo.
        assert item.effective_provider() is Provider.KIMI

        # Worker desligado depois do render.
        disp_widget._use_kimi_chk.setChecked(False)

        t1: list[str] = []
        blue: list[str] = []

        def _blue(prompt: str, delay: int) -> None:
            blue.append(prompt)

        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.kimi_blue_arrow_dispatched.connect(_blue)
        try:
            # Clique no botao unico recalcula o provider no momento do clique.
            item._on_exec_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.kimi_blue_arrow_dispatched.disconnect(_blue)

        assert blue == [], "destino stale Kimi/T2 NAO pode ser usado apos worker off"
        assert t1 == ["/qa:prep"], "clique recalculado cai em Claude/T1 (raw)"

    # ---- caso 6 — local-action nunca publica em worker ------------------ #
    def test_local_action_never_routes_to_worker(self, disp_widget):
        """Caso 6 (invariante 8): um item local-action permanece Claude mesmo
        com AMBOS os workers ativos — nunca azul/T2 nem roxo/T3."""
        from workflow_app.command_queue.provider_router import Provider

        disp_widget._main_claude_radio.setChecked(True)
        disp_widget._use_kimi_chk.setChecked(True)
        disp_widget._use_codex_chk.setChecked(True)
        disp_widget.load_pipeline(
            [
                CommandSpec(
                    "dcp-load-specific-flow",
                    ModelName.SONNET,
                    position=1,
                    kind="local-action",
                    local_action_id="dcp-load-specific-flow",
                )
            ]
        )
        item = disp_widget._items[0]
        assert item.effective_provider() is Provider.CLAUDE

    # ---- caso 9 — comando inexistente aborta com toast ------------------ #
    def test_nonexistent_command_codex_aborts_with_toast(self, disp_widget):
        """Caso 9 (invariante 10): um slash Claude que NAO existe em
        .claude/commands/ aborta o dispatch Codex/T3 com toast e nao publica
        texto parcial no terminal."""
        toasts: list[tuple[str, str]] = []
        t3: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            result = disp_widget._dispatch_codex_command("/comando-que-nao-existe-xyz")
        finally:
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert result is False
        assert t3 == [], "comando inexistente nao pode publicar texto parcial em T3"
        assert any("nao encontrado" in m for m, _ in toasts)

    # ---- custom-prompt directive (/goal) sob Codex/Kimi ----------------- #
    _GOAL_CMD = (
        "/goal rode o prompt em ai-forge/custom-prompts/goal-review-prompt.md "
        "para auditar a implantacao do module 8 usando "
        ".claude/projects/foo.json."
    )

    @pytest.fixture()
    def goal_widget(self, disp_widget, tmp_path, monkeypatch):
        """disp_widget com `_resolve_custom_prompt_file` resolvendo `goal`."""
        prompt_file = tmp_path / "ai-forge" / "custom-prompts" / "goal-review-prompt.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("# goal-review-prompt", encoding="utf-8")
        monkeypatch.setattr(
            type(disp_widget),
            "_resolve_custom_prompt_file",
            classmethod(
                lambda cls, slug: prompt_file if slug == "goal" else None
            ),
        )
        return disp_widget

    def test_goal_directive_main_codex_t1_builds_custom_prompt(self, goal_widget):
        """Main Codex: `/goal ...` NAO aborta como comando inexistente — vira
        prompt de custom-prompt apontando ao arquivo em ai-forge/custom-prompts/
        com o canal interactive (T1)."""
        t1: list[str] = []
        toasts: list[tuple[str, str]] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        try:
            result = goal_widget._dispatch_codex_command(self._GOAL_CMD, to_t1=True)
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)

        assert result is True
        assert len(t1) == 1
        payload = t1[0]
        assert "Custom prompt file:" in payload
        assert "goal-review-prompt.md" in payload
        assert "Expected listener channel: interactive" in payload
        # nunca tenta resolver /goal como slash-command de .claude/commands/
        assert "nao encontrado" not in " ".join(m for m, _ in toasts)

    def test_goal_directive_worker_codex_t3_channel(self, goal_widget):
        """Worker Codex (to_t1=False): `/goal ...` vai ao T3 com canal
        workspace_xterm."""
        t3: list[str] = []
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            result = goal_widget._dispatch_codex_command(self._GOAL_CMD)
        finally:
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert result is True
        assert len(t3) == 1
        assert "Expected listener channel: workspace_xterm" in t3[0]
        assert "Custom prompt file:" in t3[0]

    def test_goal_directive_codex_missing_prompt_file_aborts(
        self, disp_widget, monkeypatch
    ):
        """Codex: se o arquivo do custom-prompt nao existe, aborta com toast
        que cita ai-forge/custom-prompts/ (Zero Silencio com a mensagem certa,
        nao a de .claude/commands/)."""
        toasts: list[tuple[str, str]] = []
        t1: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_terminal.connect(t1.append)
        try:
            # Resolver no nivel da classe (o builder usa cls._resolve...): o
            # arquivo do custom-prompt "some" (o resolver real acharia o
            # goal-review-prompt.md do repo).
            monkeypatch.setattr(
                type(disp_widget),
                "_resolve_custom_prompt_file",
                classmethod(lambda cls, slug: None),
            )
            result = disp_widget._dispatch_codex_command(self._GOAL_CMD, to_t1=True)
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)

        assert result is False
        assert t1 == []
        assert any("ai-forge/custom-prompts/" in m for m, _ in toasts)

    def test_goal_directive_main_kimi_routes_through_executor_skill(self, goal_widget):
        """Main Kimi: `/goal ...` NAO aborta — roteia pelo executor universal
        `/skill:slash-executor /goal ...` (a skill resolve o custom-prompt)."""
        t1: list[str] = []
        toasts: list[tuple[str, str]] = []
        goal_widget._main_kimi_radio.setChecked(True)  # alias _force_kimi_chk
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        try:
            result = goal_widget._dispatch_kimi_main_command(self._GOAL_CMD)
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)

        assert result is True
        assert len(t1) == 1
        assert t1[0].startswith("/skill:slash-executor /goal ")
        assert "nao encontrado" not in " ".join(m for m, _ in toasts)

    def test_goal_directive_main_kimi_missing_prompt_file_aborts(
        self, disp_widget, monkeypatch
    ):
        """Main Kimi: arquivo do custom-prompt ausente aborta com toast que cita
        ai-forge/custom-prompts/."""
        toasts: list[tuple[str, str]] = []
        t1: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_terminal.connect(t1.append)
        try:
            monkeypatch.setattr(
                type(disp_widget),
                "_resolve_custom_prompt_file",
                classmethod(lambda cls, slug: None),
            )
            disp_widget._main_kimi_radio.setChecked(True)
            result = disp_widget._dispatch_kimi_main_command(self._GOAL_CMD)
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)

        assert result is False
        assert t1 == []
        assert any("ai-forge/custom-prompts/" in m for m, _ in toasts)

    # ---- caso 10 — Main Kimi + worker Codex (par emergente) ------------- #
    def test_main_kimi_worker_codex_emergent_pair(self, disp_widget):
        """Caso 10: com Main LLM Kimi + worker Codex ativo, um comando
        green-arrow-only (commit:simple) vai para Kimi/T1 e um comando
        codex-compatible (cmd:review) vai para Codex/T3 — o par emergente
        Kimi/T1 + Codex/T3 na mesma fila.

        Modelo router/whitelist (decisao do operador 06-02): o item de T3 e um
        comando da whitelist Codex (is_codex_compatible), nao um blue-arrow
        Kimi."""
        t1: list[str] = []
        t3: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            disp_widget._main_kimi_radio.setChecked(True)  # alias _force_kimi_chk
            disp_widget._use_codex_chk.setChecked(True)
            disp_widget.load_pipeline([
                CommandSpec("/commit:simple", ModelName.SONNET, position=1),
                CommandSpec("/cmd:review", ModelName.SONNET, position=2),
            ])
            disp_widget._on_step_btn_clicked()  # commit:simple -> Kimi/T1
            disp_widget._on_step_btn_clicked()  # cmd:review -> Codex/T3
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert len(t1) == 1, "green-arrow-only deve ir para Main Kimi/T1"
        assert t1[0].startswith("/skill:"), "Main Kimi publica em formato skill"
        assert len(t3) == 1, "codex command deve ir para worker Codex/T3"
        assert "Command: /cmd:review" in t3[0]
        assert "Expected listener channel: workspace_xterm" in t3[0]

    # ---- C3 — adaptacao vazia aborta ------------------------------------ #
    def test_blue_arrow_empty_adaptation_aborts(self, disp_widget):
        """C3: payload Kimi vazio/whitespace aborta com toast e nao emite
        kimi_blue_arrow_dispatched (defense-in-depth no dispatcher)."""
        toasts: list[tuple[str, str]] = []
        blue: list[str] = []

        def _blue(prompt: str, delay: int) -> None:
            blue.append(prompt)

        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.kimi_blue_arrow_dispatched.connect(_blue)
        try:
            disp_widget._dispatch_blue_arrow("   ")
        finally:
            signal_bus.kimi_blue_arrow_dispatched.disconnect(_blue)

        assert blue == []
        assert any("texto vazio" in m for m, _ in toasts)

    def test_codex_empty_transform_aborts(self, disp_widget):
        """C3: texto vazio no dispatch Codex aborta com toast antes de qualquer
        emit (invariante 10: nunca publica texto parcial)."""
        toasts: list[tuple[str, str]] = []
        t3: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            result = disp_widget._dispatch_codex_command("")
        finally:
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert result is False
        assert t3 == []
        assert any("texto vazio" in m for m, _ in toasts)

    # ---- C4 — terminal alvo Codex/T3 nao pronto ------------------------- #
    def test_codex_t3_not_ready_aborts_with_toast(self, disp_widget):
        """C4: quando o T3 (terminal-codex-output) sinaliza indisponivel via
        codex_availability_changed(False), o dispatch Worker Codex aborta com
        toast visivel e nao publica no terminal inexistente."""
        disp_widget._on_codex_availability_changed(False)
        toasts: list[tuple[str, str]] = []
        t3: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            result = disp_widget._dispatch_codex_command("/blog:init-strategy")
        finally:
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert result is False
        assert t3 == [], "dispatch para T3 nao pronto nao pode publicar"
        assert any("nao esta pronto" in m for m, _ in toasts)

    def test_codex_t3_ready_again_allows_dispatch(self, disp_widget):
        """C4 (recuperacao): apos codex_availability_changed(True) o dispatch
        Worker Codex volta a publicar normalmente em T3 (Zero Estados
        Indefinidos: o gate nao trava para sempre)."""
        disp_widget._on_codex_availability_changed(False)
        disp_widget._on_codex_availability_changed(True)
        t3: list[str] = []
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            result = disp_widget._dispatch_codex_command("/blog:init-strategy")
        finally:
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert result is True
        assert len(t3) == 1
        assert "Command: /blog:init-strategy" in t3[0]

    def test_main_codex_t1_unaffected_by_t3_readiness(self, disp_widget):
        """C4 escopo: o gate de prontidao do T3 NAO afeta o caminho Main Codex
        (to_t1=True), que publica no T1 interactive — sempre presente."""
        disp_widget._on_codex_availability_changed(False)
        t1: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        try:
            result = disp_widget._dispatch_codex_command(
                "/blog:init-strategy", to_t1=True
            )
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)

        assert result is True
        assert len(t1) == 1
        assert "Command: /blog:init-strategy" in t1[0]
        assert "Expected listener channel: interactive" in t1[0]

    # ---- F2 — botao unico nao marca enviado quando o dispatch aborta ----- #
    def test_single_button_codex_abort_keeps_item_pending(self, disp_widget):
        """F2 (review-executed task 006): clicar o botao unico roxo num item
        Codex quando o T3 nao esta pronto deve ABORTAR o dispatch (toast) e
        deixar o item PENDENTE — nunca ambar. Antes do fix, _on_codex_clicked
        marcava enviado incondicionalmente, e o play-next pulava um item que
        nada despachou (assimetria vs o gate do step path)."""
        disp_widget._on_codex_availability_changed(False)
        disp_widget.load_pipeline(
            [CommandSpec("/blog:init-strategy", ModelName.SONNET, position=1)]
        )
        item = disp_widget._items[0]
        toasts: list[tuple[str, str]] = []
        t3: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            # Emite o sinal do botao unico -> slot _on_single_button_codex_dispatch.
            item._on_codex_clicked()
        finally:
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert item._is_sent is False, (
            "item deve permanecer pendente quando o dispatch Codex aborta"
        )
        assert t3 == [], "abort nao pode publicar texto parcial em T3"
        assert any("nao esta pronto" in m for m, _ in toasts)

    def test_single_button_codex_success_marks_item_sent(self, disp_widget):
        """F2 (caminho feliz): com T3 pronto, o clique no botao unico publica em
        T3 e SO ENTAO marca o item como enviado (gate via retorno do dispatcher,
        espelhando o step path)."""
        disp_widget._on_codex_availability_changed(True)
        disp_widget.load_pipeline(
            [CommandSpec("/blog:init-strategy", ModelName.SONNET, position=1)]
        )
        item = disp_widget._items[0]
        t3: list[str] = []
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            item._on_codex_clicked()
        finally:
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert item._is_sent is True, "publicacao bem-sucedida deve marcar enviado"
        assert len(t3) == 1
        assert "Command: /blog:init-strategy" in t3[0]

    # ---- F3 — /clear worker Codex respeita o gate de T3 pronto ----------- #
    def test_clear_both_codex_t3_not_ready_skips_mirror(self, disp_widget):
        """F3 (review-executed task 006): /clear com worker Codex ativo NAO
        espelha para o T3 quando o terminal-codex-output nao esta pronto; emite
        toast (Zero Silencio) em vez de publicar num xterm inexistente. O T1
        ainda recebe /clear raw."""
        disp_widget._on_codex_availability_changed(False)
        disp_widget._use_kimi_chk.setChecked(False)
        disp_widget._use_codex_chk.setChecked(True)
        disp_widget.load_pipeline(
            [CommandSpec("/clear", ModelName.SONNET, position=1)]
        )
        toasts: list[tuple[str, str]] = []
        t1: list[str] = []
        t3: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            disp_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert t3 == [], "/clear nao pode ir para um T3 nao pronto"
        assert "/clear" in t1, "T1 (Claude) sempre recebe /clear raw"
        assert any("nao esta pronto" in m for m, _ in toasts)

    def test_clear_both_codex_t3_ready_mirrors(self, disp_widget):
        """F3 (caminho feliz): com T3 pronto, /clear com worker Codex ativo
        espelha para o workspace_xterm normalmente."""
        disp_widget._on_codex_availability_changed(True)
        disp_widget._use_kimi_chk.setChecked(False)
        disp_widget._use_codex_chk.setChecked(True)
        disp_widget.load_pipeline(
            [CommandSpec("/clear", ModelName.SONNET, position=1)]
        )
        t3: list[str] = []
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            disp_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)

        assert t3 == ["/clear"], "/clear deve espelhar para o T3 quando pronto"

    # ===================================================================== #
    # Divergencias D-1..D-7 (revisao /mcp:codex 2026-06-02) — paridade
    # clique vs step vs autocast. Decisao: o provider_router e a fonte unica;
    # cada caminho converge nele preservando Zero Silencio + invariante 2.
    # ===================================================================== #

    def test_d1_green_click_abort_under_main_codex_keeps_item_pending(self, disp_widget):
        """D-1: clique CLAUDE/T1 sob Main Codex cujo `.md` nao existe -> o
        dispatch Codex(to_t1=True) aborta com toast e o item PERMANECE pendente
        (nao vira ambar). Antes, `_on_run_clicked` marcava enviado antes do
        dispatch. Agora so o slot `_on_single_button_green_dispatch` marca, e so
        em sucesso."""
        toasts: list[tuple[str, str]] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        disp_widget._main_codex_radio.setChecked(True)
        disp_widget._use_kimi_chk.setChecked(False)
        disp_widget._use_codex_chk.setChecked(False)
        disp_widget.load_pipeline(
            [CommandSpec("/nao-existe-xyz", ModelName.SONNET, position=1)]
        )
        item = disp_widget._items[0]
        item._on_exec_clicked()  # provider CLAUDE (sem worker) -> green dispatch

        assert item.is_pending_run() is True, (
            "abort do dispatch nao pode marcar o item como enviado (D-1)"
        )
        assert any("nao encontrado" in m for m, _ in toasts)

    def test_d1_green_click_success_marks_sent(self, disp_widget):
        """D-1 companion: Main Claude raw (sempre publica) -> o item vira ambar
        via o slot, preservando o comportamento de sucesso."""
        disp_widget._main_claude_radio.setChecked(True)
        disp_widget._use_kimi_chk.setChecked(False)
        disp_widget._use_codex_chk.setChecked(False)
        disp_widget.load_pipeline(
            [CommandSpec("/qa:prep", ModelName.SONNET, position=1)]
        )
        item = disp_widget._items[0]
        t1: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        try:
            item._on_exec_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
        assert t1 == ["/qa:prep"]
        assert item.is_pending_run() is False, "dispatch ok deve marcar enviado"

    def test_d2_clear_under_main_codex_goes_raw_and_mirrors(self, disp_widget):
        """D-2: `/clear` no clique sob Main Codex vai RAW ao T1 (nao embrulhado
        por _dispatch_codex_command) e espelha para o worker Kimi/T2."""
        disp_widget._main_codex_radio.setChecked(True)
        disp_widget._use_kimi_chk.setChecked(True)
        t1: list[str] = []
        t2: list[str] = []
        t3: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_terminal.connect(t2.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            ok = disp_widget._dispatch_green_arrow("/clear")
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(t2.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)
        assert ok is True
        assert t1 == ["/clear"], "/clear raw ao T1 sob Main Codex (nao codex-wrapped)"
        assert t2 == ["/clear"], "/clear espelhado ao worker Kimi/T2"
        assert all("Command:" not in x for x in t1), "nao pode virar prompt executor Codex"

    def test_d3_main_kimi_plus_worker_kimi_routes_to_t2(self, disp_widget):
        """D-3 (Position A, invariante 2): Main Kimi + Worker Kimi -> a seta
        worker NAO e escondida e um comando kimi-elegivel roteia ao T2 no step
        (clique e step concordam), nao cai em T1 Kimi."""
        disp_widget._main_kimi_radio.setChecked(True)  # alias _force_kimi_chk
        disp_widget._use_kimi_chk.setChecked(True)
        disp_widget.load_pipeline(
            [CommandSpec("/qa:prep", ModelName.SONNET, position=1)]
        )
        item = disp_widget._items[0]
        assert item.is_worker_arrow_visible() is True, (
            "Main Kimi + Worker Kimi nao deve esconder a seta worker (D-3)"
        )
        t1: list[str] = []
        blue: list[str] = []

        def _blue(prompt: str, delay: int) -> None:
            blue.append(prompt)

        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.kimi_blue_arrow_dispatched.connect(_blue)
        try:
            disp_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.kimi_blue_arrow_dispatched.disconnect(_blue)
        assert len(blue) == 1, "comando kimi-elegivel deve ir ao worker Kimi/T2"
        assert t1 == [], "nao pode cair em T1 Kimi (divergencia D-3)"

    def test_d3_main_kimi_alone_still_hides_worker_arrow(self, disp_widget):
        """D-3 guard: Main Kimi SOZINHO (Worker Kimi off) continua escondendo a
        seta worker — tudo vai a T1 Kimi (comportamento legado preservado)."""
        disp_widget._main_kimi_radio.setChecked(True)
        disp_widget._use_kimi_chk.setChecked(False)
        disp_widget.load_pipeline(
            [CommandSpec("/qa:prep", ModelName.SONNET, position=1)]
        )
        assert disp_widget._items[0].is_worker_arrow_visible() is False

    def test_d4_codex_missing_md_in_step_aborts_not_fallthrough(self, disp_widget):
        """D-4: comando codex-compativel sem `.md` (/python:py-review nao esta no
        fixture) no step com Worker Codex -> `_dispatch_codex_command` aborta com
        toast; NAO cai no Main-LLM axis colando raw em T1. step == clique."""
        toasts: list[tuple[str, str]] = []
        t1: list[str] = []
        t3: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        disp_widget._main_claude_radio.setChecked(True)
        disp_widget._use_codex_chk.setChecked(True)
        disp_widget.load_pipeline(
            [CommandSpec("/python:py-review", ModelName.SONNET, position=1)]
        )
        try:
            disp_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)
        assert t1 == [], "codex sem .md NAO pode cair raw em T1 (D-4)"
        assert t3 == [], "nada publicado em T3 no abort"
        assert any("nao encontrado" in m for m, _ in toasts)
        assert disp_widget._items[0].is_pending_run() is True

    def test_d5_local_action_click_runs_in_process_not_t1(self, disp_widget):
        """D-5: clique no botao unico de um local-action roda a action in-process
        (dispatch_local_action) e NUNCA cola o nome em T1 (invariante 8)."""
        from workflow_app.command_queue.local_actions import (
            register_local_action,
            unregister_local_action,
        )

        called: list[str] = []
        register_local_action("test-d5-action", lambda spec: called.append(spec.name) or True)
        t1: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        try:
            disp_widget.load_pipeline([
                CommandSpec(
                    "test-d5-action", ModelName.SONNET, position=1,
                    kind="local-action", local_action_id="test-d5-action",
                )
            ])
            item = disp_widget._items[0]
            item._on_exec_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            unregister_local_action("test-d5-action")
        assert called == ["test-d5-action"], "local-action deve rodar in-process"
        assert t1 == [], "local-action NUNCA cola em T1 (invariante 8)"
        assert disp_widget._items[0].is_pending_run() is False

    def test_d5_local_action_step_runs_in_process(self, disp_widget):
        """D-5: o step manual sobre um local-action tambem roda in-process,
        nao cola em T1."""
        from workflow_app.command_queue.local_actions import (
            register_local_action,
            unregister_local_action,
        )

        called: list[str] = []
        register_local_action("test-d5-step", lambda spec: called.append(spec.name) or True)
        t1: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        try:
            disp_widget.load_pipeline([
                CommandSpec(
                    "test-d5-step", ModelName.SONNET, position=1,
                    kind="local-action", local_action_id="test-d5-step",
                )
            ])
            disp_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            unregister_local_action("test-d5-step")
        assert called == ["test-d5-step"]
        assert t1 == []

    def test_d6_kimi_adaptation_failure_emits_toast(self, disp_widget, monkeypatch):
        """D-6: quando adapt_to_kimi levanta ValueError, o item emite
        `kimi_adaptation_failed` e o queue widget toasta (Zero Silencio); o item
        NAO e marcado enviado."""
        import workflow_app.command_queue.command_item_widget as ciw

        def _boom(_cmd):
            raise ValueError("malformed")

        monkeypatch.setattr(ciw, "adapt_to_kimi", _boom)
        toasts: list[tuple[str, str]] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        disp_widget._main_claude_radio.setChecked(True)
        disp_widget._use_kimi_chk.setChecked(True)
        disp_widget.load_pipeline(
            [CommandSpec("/qa:prep", ModelName.SONNET, position=1)]
        )
        item = disp_widget._items[0]
        item._on_kimi_clicked()
        assert any("Adaptacao Kimi falhou" in m for m, _ in toasts)
        assert item.is_pending_run() is True

    def test_d7_clear_mirror_t3_gated_when_unavailable(self, disp_widget):
        """D-7: mirror de `/clear` ao T3 respeita `_codex_t3_available`; quando o
        T3 nao esta pronto, emite toast e NAO publica no xterm inexistente."""
        disp_widget._on_codex_availability_changed(False)
        disp_widget._use_kimi_chk.setChecked(False)
        disp_widget._use_codex_chk.setChecked(True)
        toasts: list[tuple[str, str]] = []
        t3: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_workspace_xterm.connect(t3.append)
        try:
            disp_widget._mirror_clear_to_workspace_if_kimi_checked("/clear")
        finally:
            signal_bus.run_command_in_workspace_xterm.disconnect(t3.append)
        assert t3 == [], "T3 indisponivel: /clear nao espelhado (D-7)"
        assert any("nao esta pronto" in m for m, _ in toasts)

    def test_d2_clear_mirrors_to_worker_under_main_kimi(self, disp_widget):
        """D-2/D-7 ressalva (close-out): `/clear` sob Main Kimi + Worker Kimi
        deve espelhar ao T2 (paridade com o step `clear_both`). Antes, o
        early-return de Main Kimi em `_mirror_clear_to_workspace_if_kimi_checked`
        pulava o espelhamento e divergia do step."""
        disp_widget._main_kimi_radio.setChecked(True)  # alias _force_kimi_chk
        disp_widget._use_kimi_chk.setChecked(True)
        t1: list[str] = []
        t2: list[str] = []
        signal_bus.run_command_in_terminal.connect(t1.append)
        signal_bus.run_command_in_workspace_terminal.connect(t2.append)
        try:
            ok = disp_widget._dispatch_green_arrow("/clear")
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
            signal_bus.run_command_in_workspace_terminal.disconnect(t2.append)
        assert ok is True
        assert t1 == ["/clear"], "/clear raw ao T1 (Kimi main entende /clear)"
        assert t2 == ["/clear"], "/clear espelhado ao Worker Kimi/T2 sob Main Kimi"

    # ---- Regra capacidade exclusiva (image-gen) — enforce mecanico ---------- #
    def test_image_gen_command_refused_in_step_without_codex_worker(self, disp_widget):
        """So o Codex gera imagem: um comando de image-gen (/pictures-create)
        roteado a provider != Codex (aqui Main Claude, sem Worker Codex) e
        RECUSADO no step — nada vai ao T1, item permanece pendente, toast emitido."""
        toasts: list[tuple[str, str]] = []
        t1: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_terminal.connect(t1.append)
        disp_widget._main_claude_radio.setChecked(True)
        disp_widget._use_kimi_chk.setChecked(False)
        disp_widget._use_codex_chk.setChecked(False)
        disp_widget.load_pipeline(
            [CommandSpec("/pictures-create", ModelName.SONNET, position=1)]
        )
        try:
            disp_widget._on_step_btn_clicked()
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
        assert t1 == [], "image-gen NAO pode ir ao Claude/T1 (so o Codex gera imagem)"
        assert disp_widget._items[0].is_pending_run() is True
        assert any("Worker Codex" in m for m, _ in toasts)

    def test_image_gen_green_dispatch_refused(self, disp_widget):
        """O caminho verde (Claude/T1) recusa um comando de image-gen e retorna
        False (Zero Silencio: toast em vez de colar no Claude)."""
        toasts: list[tuple[str, str]] = []
        t1: list[str] = []
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        signal_bus.run_command_in_terminal.connect(t1.append)
        try:
            ok = disp_widget._dispatch_green_arrow("/pictures-create")
        finally:
            signal_bus.run_command_in_terminal.disconnect(t1.append)
        assert ok is False
        assert t1 == []
        assert any("Worker Codex" in m for m, _ in toasts)


class TestRestoreSnapshotValidation:
    """Loop 06-09 (brecha 3): snapshots auto-salvos pre-fix 06-08 carregam
    comandos per-task sintetizados por contagem (tasks fantasma) ou placeholder
    literal. `restore_queue_snapshot` valida entradas PENDENTES contra o disco
    (mesma passada de flow_validation do load do SPECIFIC-FLOW.json); entradas
    ja enviadas sao historico e restauram verbatim. Drops geram toast."""

    @staticmethod
    def _entry(name: str, *, status: str = "pendente", sent: bool = False) -> dict:
        return {
            "name": name,
            "model": "Sonnet",
            "interaction_type": "auto",
            "position": 1,
            "is_optional": False,
            "config_path": "",
            "phase": "B.3",
            "status": status,
            "sent": sent,
        }

    def test_pending_phantom_task_dropped_with_toast(self, widget, tmp_path):
        module_dir = tmp_path / "modules" / "module-7-auth"
        module_dir.mkdir(parents=True)
        (module_dir / "TASK-1.md").write_text("# t1", encoding="utf-8")
        real = f"/execute-task --module 7 --task {module_dir / 'TASK-1.md'}"
        phantom = f"/execute-task --module 7 --task {module_dir / 'TASK-4.md'}"

        toasts: list[tuple[str, str]] = []
        handler = lambda m, k: toasts.append((m, k))  # noqa: E731
        signal_bus.toast_requested.connect(handler)
        try:
            widget.restore_queue_snapshot(
                [self._entry(real), self._entry(phantom)]
            )
        finally:
            signal_bus.toast_requested.disconnect(handler)

        names = [it.get_spec().name for it in widget._items]
        assert names == [real], "fantasma pendente deve ser dropado no restore"
        assert any("descartado" in m for m, _ in toasts), (
            "drop deve ser visivel via toast (Zero Silencio)"
        )

    def test_sent_phantom_kept_as_history(self, widget, tmp_path):
        phantom = f"/execute-task --module 7 --task {tmp_path / 'TASK-99.md'}"
        widget.restore_queue_snapshot(
            [self._entry(phantom, status="concluido", sent=True)]
        )
        names = [it.get_spec().name for it in widget._items]
        assert names == [phantom], (
            "entrada ja executada e registro historico — restaura verbatim"
        )

    def test_pending_literal_placeholder_dropped(self, widget):
        widget.restore_queue_snapshot(
            [
                self._entry("/execute-task --module 7 --task TASK-{k}"),
                self._entry("/qa:prep --module 7"),
            ]
        )
        names = [it.get_spec().name for it in widget._items]
        assert names == ["/qa:prep --module 7"], (
            "placeholder literal pendente nao pode voltar para a fila"
        )

    def test_relative_ref_without_project_dir_fails_open(self, widget, monkeypatch):
        from workflow_app.config.app_state import app_state

        monkeypatch.setattr(app_state, "_config", None)
        rel = "/execute-task --module 7 --task wbs/modules/m7/TASK-9.md"
        widget.restore_queue_snapshot([self._entry(rel)])
        names = [it.get_spec().name for it in widget._items]
        assert names == [rel], (
            "ref relativa sem contexto de resolucao e inverificavel — manter "
            "(fail-open evita falso drop)"
        )

    def test_statuses_and_sent_flags_stay_aligned_after_drop(self, widget, tmp_path):
        module_dir = tmp_path / "modules" / "module-2-core"
        module_dir.mkdir(parents=True)
        (module_dir / "TASK-1.md").write_text("# t1", encoding="utf-8")
        done = f"/execute-task --module 2 --task {module_dir / 'TASK-1.md'}"
        phantom = f"/execute-task --module 2 --task {module_dir / 'TASK-3.md'}"
        pending = "/qa:prep --module 2"

        widget.restore_queue_snapshot(
            [
                self._entry(done, status="concluido", sent=True),
                self._entry(phantom),
                self._entry(pending),
            ]
        )

        from workflow_app.domain import CommandStatus

        assert [it.get_spec().name for it in widget._items] == [done, pending]
        assert widget._items[0]._status == CommandStatus.CONCLUIDO
        assert widget._items[0].is_pending_run() is False, "sent preservado"
        assert widget._items[1]._status == CommandStatus.PENDENTE
        assert widget._items[1].is_pending_run() is True, (
            "flags nao podem desalinhar apos drop no meio do snapshot"
        )

    def test_freetext_placeholder_survives_restore_task_only_mode(self, widget):
        """Caso real (pipeline-position/site-barato.json): prompt /mcp:codex
        pendente com `{slug}` em texto livre e legitimo — o LLM receptor
        resolve contextualmente. So a assinatura `TASK-{k}` do stub derruba."""
        freetext = (
            "/mcp:codex revisar a gaplist gerada por "
            "/intake-review:create-gaplist (output/wbs/{slug}/intake-review/)"
        )
        widget.restore_queue_snapshot([self._entry(freetext)])
        names = [it.get_spec().name for it in widget._items]
        assert names == [freetext], (
            "placeholder de texto-livre nao pode ser dropado no restore "
            "(falso positivo observado em snapshot real)"
        )


class TestEnqueueSpecificFlowValidationIntegration:
    """Loop 06-09 (P2 do critic): exercita o _enqueue_specific_flow REAL contra
    um SPECIFIC-FLOW.json fantasma em disco — glue load -> validate -> drop ->
    toast -> enqueue dos validos (as outras suites mockam o helper)."""

    def test_phantom_and_placeholder_dropped_valid_enqueued(self, widget, tmp_path):
        module_dir = tmp_path / "wbs" / "modules" / "module-7-auth"
        module_dir.mkdir(parents=True)
        (module_dir / "TASK-1.md").write_text("# t1", encoding="utf-8")

        valid = f"/execute-task --module 7 --task {module_dir / 'TASK-1.md'}"
        phantom = f"/execute-task --module 7 --task {module_dir / 'TASK-4.md'}"
        stub = "/execute-task --module 7 --task TASK-{k}"
        flow_path = module_dir / "SPECIFIC-FLOW.json"
        flow_path.write_text(json.dumps({
            "project": "proj-x",
            "commands": [
                {"name": valid, "model": "sonnet", "effort": "medium",
                 "phase": "B.3", "interaction": "auto"},
                {"name": phantom, "model": "sonnet", "effort": "medium",
                 "phase": "B.3", "interaction": "auto"},
                {"name": stub, "model": "sonnet", "effort": "medium",
                 "phase": "B.3", "interaction": "auto"},
            ],
        }), encoding="utf-8")

        toasts: list[tuple[str, str]] = []
        handler = lambda m, k: toasts.append((m, k))  # noqa: E731
        signal_bus.toast_requested.connect(handler)
        try:
            ok = widget._enqueue_specific_flow(
                flow_path,
                cm_id="module-7-auth",
                default_project_name="proj-x",
                project_dir=tmp_path,
            )
        finally:
            signal_bus.toast_requested.disconnect(handler)

        assert ok is True
        names = [it.get_spec().name for it in widget._items]
        assert valid in names
        assert phantom not in names, "TASK fantasma nao pode ser enfileirada"
        assert stub not in names, "placeholder do stub nao pode ser enfileirado"
        assert any("descartado" in m for m, _ in toasts), (
            "drop deve ser visivel via toast (Zero Silencio)"
        )

    def test_all_phantom_flow_returns_false_with_empty_toast(self, widget, tmp_path):
        module_dir = tmp_path / "wbs" / "modules" / "module-7-auth"
        module_dir.mkdir(parents=True)
        flow_path = module_dir / "SPECIFIC-FLOW.json"
        flow_path.write_text(json.dumps({
            "commands": [
                {"name": f"/execute-task --module 7 --task {module_dir / 'TASK-9.md'}",
                 "model": "sonnet", "effort": "medium",
                 "phase": "B.3", "interaction": "auto"},
            ],
        }), encoding="utf-8")

        toasts: list[tuple[str, str]] = []
        handler = lambda m, k: toasts.append((m, k))  # noqa: E731
        signal_bus.toast_requested.connect(handler)
        try:
            ok = widget._enqueue_specific_flow(
                flow_path,
                cm_id="module-7-auth",
                default_project_name="proj-x",
                project_dir=tmp_path,
            )
        finally:
            signal_bus.toast_requested.disconnect(handler)

        assert ok is False, "flow 100%% fantasma nao pode enfileirar nada"
        assert widget._items == []
