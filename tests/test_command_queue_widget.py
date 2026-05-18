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


class TestForceKimi:
    """Cobertura do modo `--force Kimi` (data-testid=queue-div-force-kimi).

    Quando ativo: a seta verde despacha para o terminal workspace com
    prefixo /skill:; /model e /effort viram bolinha amarela sem dispatch;
    /clear vai SO para workspace; seta azul fica oculta; Use Kimi e
    desabilitado (modos mutuamente exclusivos). Quando inativo: comportamento
    legado preservado."""

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
    def force_kimi_widget(self, widget, monkeypatch):
        """Widget com `_resolve_skill_target` monkeypatched para retornar True —
        evita dependencia em arquivos reais de skill dentro dos testes."""
        monkeypatch.setattr(
            type(widget), "_resolve_skill_target",
            classmethod(lambda cls, slug: True),
        )
        return widget

    # ---- UI checkbox -----------------------------------------------------

    def test_force_kimi_checkbox_exists_with_testid(self, widget):
        chk = widget._force_kimi_chk
        assert chk is not None
        assert chk.property("testid") == "queue-chk-force-kimi"
        assert chk.text() == "--force Kimi"

    def test_force_kimi_container_div_has_testid(self, widget):
        from PySide6.QtWidgets import QWidget
        # Procurar o QWidget container marcado com queue-div-force-kimi.
        found = [w for w in widget.findChildren(QWidget)
                 if w.property("testid") == "queue-div-force-kimi"]
        assert len(found) == 1, "queue-div-force-kimi container nao encontrado"

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

    # ---- Force-kimi ON: /skill: prefix + workspace ----------------------

    def test_force_on_per_item_injects_skill_prefix_to_workspace(
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
        assert emitted_interactive == [], "force-kimi NAO pode tocar interactive"
        assert emitted_workspace == ["/skill:create-task"]

    def test_force_on_step_btn_injects_skill_prefix_to_workspace(
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
        assert emitted_interactive == []
        assert emitted_workspace == ["/skill:create-task"]

    # ---- /model e /effort suprimidos -----------------------------------

    def test_force_on_model_effort_no_terminal_emit(
        self, force_kimi_widget, model_effort_specs
    ):
        """/model e /effort viram bolinha amarela SEM enviar para terminal,
        nem interactive nem workspace."""
        emitted_interactive: list[str] = []
        emitted_workspace: list[str] = []
        signal_bus.run_command_in_terminal.connect(emitted_interactive.append)
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
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
        assert emitted_interactive == []
        assert emitted_workspace == []
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

    # ---- /clear vai SO para workspace -----------------------------------

    def test_force_on_clear_per_item_goes_only_to_workspace(
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
        assert emitted_interactive == [], "/clear nao pode ir para interactive em force-kimi"
        assert emitted_workspace == ["/clear"]

    def test_force_on_clear_step_btn_goes_only_to_workspace(
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
        assert emitted_interactive == []
        assert emitted_workspace == ["/clear"]

    # ---- Skill existence validation -------------------------------------

    def test_force_on_unknown_skill_aborts_with_toast(self, widget, task_specs, monkeypatch):
        """Comando sem wrapper de skill (.claude/commands/skill ou .agents/skills)
        deve abortar dispatch com toast (review HIGH 2)."""
        monkeypatch.setattr(
            type(widget), "_resolve_skill_target",
            classmethod(lambda cls, slug: False),
        )
        emitted_workspace: list[str] = []
        toasts: list[tuple] = []
        signal_bus.run_command_in_workspace_terminal.connect(emitted_workspace.append)
        signal_bus.toast_requested.connect(lambda m, k: toasts.append((m, k)))
        try:
            widget._force_kimi_chk.setChecked(True)
            widget.load_pipeline(task_specs)
            widget._items[0]._on_run_clicked()
        finally:
            signal_bus.run_command_in_workspace_terminal.disconnect(emitted_workspace.append)
        assert emitted_workspace == [], "dispatch deve abortar quando skill nao existe"
        assert any("create-task" in m for m, _ in toasts), \
            "toast deve mencionar o slug ausente"

    # ---- /skill: prefix idempotente -------------------------------------

    def test_inject_skill_prefix_idempotent(self):
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        f = CommandQueueWidget._inject_skill_prefix
        assert f("/skill:create-task") == "/skill:create-task"
        assert f("/create-task") == "/skill:create-task"
        assert f("/create-task arg") == "/skill:create-task arg"
        assert f("") == ""
        assert f("prompt livre sem barra") == "prompt livre sem barra"

    # ---- Mutual exclusivity Use Kimi vs --force Kimi --------------------

    def test_force_kimi_disables_use_kimi(self, widget):
        widget._use_kimi_chk.setChecked(True)
        widget._force_kimi_chk.setChecked(True)
        assert widget._use_kimi_chk.isChecked() is False
        assert widget._use_kimi_chk.isEnabled() is False

    def test_unchecking_force_kimi_reenables_use_kimi(self, widget):
        widget._force_kimi_chk.setChecked(True)
        assert widget._use_kimi_chk.isEnabled() is False
        widget._force_kimi_chk.setChecked(False)
        assert widget._use_kimi_chk.isEnabled() is True

    def test_use_kimi_unchecks_force_kimi(self, widget):
        widget._force_kimi_chk.setChecked(True)
        # Apos force-kimi ligado, Use Kimi esta disabled — habilitar manualmente
        # para o teste simular o caso em que o usuario alterna entre modos.
        widget._use_kimi_chk.setEnabled(True)
        widget._use_kimi_chk.setChecked(True)
        assert widget._force_kimi_chk.isChecked() is False

    # ---- Seta azul oculta quando force-kimi ativo -----------------------

    def test_force_kimi_hides_blue_arrow_on_all_items(self, widget):
        kimi_specs = [
            CommandSpec("/qa:prep", ModelName.SONNET, position=1),
            CommandSpec("/create-task", ModelName.SONNET, position=2),
        ]
        widget.load_pipeline(kimi_specs)
        # Pre-condition: pelo menos um item tem seta azul visivel.
        any_visible_before = any(
            item._kimi_btn.isVisible() for item in widget._items
            if getattr(item, "_kimi_btn", None) is not None
        )
        widget._force_kimi_chk.setChecked(True)
        for item in widget._items:
            btn = getattr(item, "_kimi_btn", None)
            if btn is not None:
                assert btn.isVisible() is False, \
                    "seta azul deve ficar oculta com --force Kimi"
        widget._force_kimi_chk.setChecked(False)
        # Apos desligar: visibilidade restaurada pelo menos para um item
        # whitelisted (sanity — nao todos podem ser whitelisted).
        if any_visible_before:
            assert any(
                item._kimi_btn.isVisible() for item in widget._items
                if getattr(item, "_kimi_btn", None) is not None
            ), "seta azul deve ser restaurada apos desligar --force Kimi"

    def test_force_kimi_hides_blue_arrow_on_items_added_later(self, widget):
        widget._force_kimi_chk.setChecked(True)
        widget.load_pipeline([CommandSpec("/qa:prep", ModelName.SONNET, position=1)])
        item = widget._items[0]
        btn = getattr(item, "_kimi_btn", None)
        if btn is not None:
            assert btn.isVisible() is False

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
        # cmd_text original `/create-task`, NAO `/skill:create-task`.
        assert force_kimi_widget._items[0]._highlighted is True


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
    # Hardening per /skill:mcp-codex adversarial review 2026-05-14:
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
      - Cada fase precedida por bloco /clear + /model opus + /effort high.
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

    def test_each_phase_prefixed_by_clear_model_effort_block(self, widget):
        widget._on_study_command_ready('/study "duvida" --name foo')
        names = _spec_names(widget)
        # Bloco prep canonico: /clear + /model opus + /effort high antes de cada fase.
        # 7 fases => 7 blocos => total 7 fases + 7*3 = 28 itens.
        assert len(names) == 7 + 7 * 3
        for i in range(7):
            base = i * 4
            assert names[base] == "/clear"
            assert names[base + 1] == "/model opus"
            assert names[base + 2] == "/effort high"

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
      - botao existe em queue-tab-pipelines com testid esperado;
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
        assert btn is not None, "queue-btn-legacy-to-dcp ausente em queue-tab-pipelines"

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
