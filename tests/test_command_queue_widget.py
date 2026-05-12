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
        CommandSpec("/lld-create", ModelName.HAIKU, position=3),
    ]


@pytest.fixture()
def widget(qapp, qtbot) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    w.show()
    return w


class TestCommandQueueWidgetInitialState:
    def test_width_within_bounds(self, widget):
        """Widget width is within min/max bounds (200–400px).

        Upper bound raised from 360→400 by TASK-050: the new DCP buttons
        (`DCP: Build Module Pipeline` / `DCP: Specific-Flow`) have spec-
        mandated literal labels wider than the previous legacy buttons.
        """
        assert 200 <= widget.width() <= 400

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
            assert item._kimi_btn.isVisible()
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
