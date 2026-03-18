"""
Tests for CommandItemWidget (module-10/TASK-3).

Covers:
  - Default status PENDENTE
  - Command name displayed in label
  - ModelBadge displays correct model
  - set_status(PULADO) applies line-through styling
  - set_status(EXECUTANDO) starts StatusDot pulse
  - set_status(CONCLUIDO) stops pulse and changes appearance
  - set_model() updates the model badge
  - remove_requested, skip_requested, edit_model_requested signals exist
  - original_position maps to spec.position
"""
from __future__ import annotations

import pytest

from workflow_app.command_queue.command_item_widget import CommandItemWidget
from workflow_app.domain import (
    CommandSpec,
    CommandStatus,
    ModelName,
)


@pytest.fixture()
def spec() -> CommandSpec:
    return CommandSpec(
        name="/prd-create",
        model=ModelName.SONNET,
        position=0,
    )


@pytest.fixture()
def item(spec, qtbot):
    w = CommandItemWidget(spec)
    qtbot.addWidget(w)
    w.show()
    return w


class TestCommandItemWidgetInitialState:
    def test_default_status_pendente(self, item):
        """Initial status is PENDENTE."""
        assert item._status == CommandStatus.PENDENTE

    def test_command_name_displayed(self, item):
        """Command name appears in the name label."""
        assert item._name_label.text() == "/prd-create"

    def test_model_badge_shows_sonnet(self, item):
        """ModelBadge shows 'Son' (short) for SONNET."""
        assert item._model_badge.text() in ("Son", "Sonnet")

    def test_actions_button_exists(self, item):
        """Run button (▶) is present and visible."""
        assert item._run_btn is not None
        assert item._run_btn.isVisible()

    def test_spec_position_accessible(self, item):
        """spec.position is accessible via get_spec()."""
        assert item.get_spec().position == 0


class TestCommandItemWidgetSetStatus:
    def test_set_status_concluido(self, item):
        """CONCLUIDO changes status attribute."""
        item.set_status(CommandStatus.CONCLUIDO)
        assert item._status == CommandStatus.CONCLUIDO

    def test_set_status_erro(self, item):
        """ERRO changes status attribute."""
        item.set_status(CommandStatus.ERRO)
        assert item._status == CommandStatus.ERRO

    def test_set_status_incerto(self, item):
        """INCERTO changes status attribute."""
        item.set_status(CommandStatus.INCERTO)
        assert item._status == CommandStatus.INCERTO

    def test_set_status_pulado_applies_strikethrough(self, item):
        """PULADO applies text-decoration: line-through in name label stylesheet."""
        item.set_status(CommandStatus.PULADO)
        assert "line-through" in item._name_label.styleSheet()

    def test_set_status_non_pulado_removes_strikethrough(self, item):
        """Non-PULADO status removes strikethrough from name label."""
        item.set_status(CommandStatus.PULADO)
        item.set_status(CommandStatus.PENDENTE)
        assert "line-through" not in item._name_label.styleSheet()

    def test_set_status_executando_shows_border(self, item):
        """EXECUTANDO applies a blue left-border highlight to the widget."""
        item.set_status(CommandStatus.EXECUTANDO)
        assert "border-left" in item.styleSheet()

    def test_set_status_concluido_removes_border(self, item):
        """CONCLUIDO after EXECUTANDO removes the border highlight."""
        item.set_status(CommandStatus.EXECUTANDO)
        item.set_status(CommandStatus.CONCLUIDO)
        assert "border-left" not in item.styleSheet()


class TestCommandItemWidgetSetModel:
    def test_set_model_opus(self, item):
        """set_model(OPUS) updates badge to 'Opus' short name."""
        item.set_model(ModelName.OPUS)
        assert item._model_badge.text() in ("Opus",)

    def test_set_model_updates_spec(self, item):
        """set_model updates the internal spec model."""
        item.set_model(ModelName.HAIKU)
        assert item.get_spec().model == ModelName.HAIKU


class TestCommandItemWidgetSignals:
    def test_skip_requested_signal_exists(self, item):
        """skip_requested signal is defined."""
        assert hasattr(item, "skip_requested")

    def test_remove_requested_signal_exists(self, item):
        """remove_requested signal is defined."""
        assert hasattr(item, "remove_requested")

    def test_edit_model_requested_signal_exists(self, item):
        """edit_model_requested signal is defined."""
        assert hasattr(item, "edit_model_requested")


# ───────────────────────── INCERTO state (GAP-012 fix) ──────── #

class TestCommandItemWidgetIncertoState:
    """INCERTO state must not show error row (only ERRO does)."""

    def test_incerto_hides_error_row(self, item):
        """set_status(INCERTO) must keep error row hidden."""
        item.set_status(CommandStatus.INCERTO)
        assert not item._error_row.isVisible(), (
            "Error row must be hidden for INCERTO status"
        )

    def test_erro_shows_error_row(self, item):
        """set_status(ERRO) must make error row visible (sanity check)."""
        item.set_status(CommandStatus.ERRO)
        assert item._error_row.isVisible(), (
            "Error row must be visible for ERRO status"
        )

    def test_incerto_after_erro_hides_row(self, item):
        """After ERRO, switching to INCERTO hides the error row."""
        item.set_status(CommandStatus.ERRO)
        assert item._error_row.isVisible()
        item.set_status(CommandStatus.INCERTO)
        assert not item._error_row.isVisible()
