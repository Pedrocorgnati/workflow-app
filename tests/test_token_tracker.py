"""Tests for TokenTracker (module-15/TASK-1)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from workflow_app.core.token_tracker import _DEFAULT_PRICES, TokenTracker
from workflow_app.domain import ModelType


@pytest.fixture()
def mock_db():
    """DatabaseManager com CommandExecution mock."""
    mock_cmd = MagicMock()
    mock_cmd.tokens_input = 0
    mock_cmd.tokens_output = 0
    mock_cmd.cost_usd = 0.0

    mock_session = MagicMock()
    mock_session.get.return_value = mock_cmd
    mock_session.__enter__ = lambda s: mock_session
    mock_session.__exit__ = MagicMock(return_value=False)

    db = MagicMock()
    db.get_session.return_value = mock_session
    return db, mock_cmd


def test_record_calculates_sonnet_cost(mock_db):
    db, cmd = mock_db
    tracker = TokenTracker(db)
    cost = tracker.record(1, tokens_in=5000, tokens_out=2000, model=ModelType.SONNET)
    # (5000 * 3 + 2000 * 15) / 1_000_000 = 0.015 + 0.030 = 0.045
    assert cost == pytest.approx(0.045, rel=1e-4)


def test_record_calculates_opus_cost(mock_db):
    db, cmd = mock_db
    tracker = TokenTracker(db)
    cost = tracker.record(1, tokens_in=1000, tokens_out=1000, model=ModelType.OPUS)
    # (1000 * 15 + 1000 * 75) / 1_000_000 = 0.090
    assert cost == pytest.approx(0.090, rel=1e-4)


def test_record_updates_command_fields(mock_db):
    db, cmd = mock_db
    tracker = TokenTracker(db)
    cost = tracker.record(1, tokens_in=100, tokens_out=50, model=ModelType.HAIKU)
    assert cmd.tokens_input == 100
    assert cmd.tokens_output == 50
    assert cost > 0  # cost_usd lives on PipelineExecution, not CommandExecution


def test_custom_prices_override_defaults(mock_db):
    db, _ = mock_db
    custom = {ModelType.SONNET.value: (10.0, 30.0)}
    tracker = TokenTracker(db, custom_prices=custom)
    cost = tracker._calculate_cost(1_000_000, 0, ModelType.SONNET)
    assert cost == pytest.approx(10.0, rel=1e-4)


def test_format_cost_small():
    assert TokenTracker.format_cost(0.000045) == "$0.0000"
    assert TokenTracker.format_cost(0.0001) == "$0.0001"


def test_format_cost_normal():
    assert TokenTracker.format_cost(1.5) == "$1.50"


def test_get_session_total_sums_all_commands():
    """Testa que get_session_total soma corretamente vários comandos."""
    mock_cmd1 = MagicMock()
    mock_cmd1.tokens_input = 1000
    mock_cmd1.tokens_output = 500
    mock_cmd1.cost_usd = 0.01

    mock_cmd2 = MagicMock()
    mock_cmd2.tokens_input = 2000
    mock_cmd2.tokens_output = 1000
    mock_cmd2.cost_usd = 0.02

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.all.return_value = [
        mock_cmd1, mock_cmd2
    ]
    mock_session.__enter__ = lambda s: mock_session
    mock_session.__exit__ = MagicMock(return_value=False)

    db = MagicMock()
    db.get_session.return_value = mock_session

    tracker = TokenTracker(db)
    total_in, total_out, cost = tracker.get_session_total(pipeline_id=1)

    assert total_in == 3000
    assert total_out == 1500
    assert cost == pytest.approx(0.03, rel=1e-4)


def test_zero_tokens_no_error(mock_db):
    """tokens_in=0 e tokens_out=0 devem persistir sem erro."""
    db, cmd = mock_db
    tracker = TokenTracker(db)
    cost = tracker.record(1, tokens_in=0, tokens_out=0, model=ModelType.SONNET)
    assert cost == 0.0


def test_default_prices_contain_all_models():
    assert ModelType.OPUS.value in _DEFAULT_PRICES
    assert ModelType.SONNET.value in _DEFAULT_PRICES
    assert ModelType.HAIKU.value in _DEFAULT_PRICES


def test_update_prices_changes_calculation(mock_db):
    """update_prices() deve alterar o cálculo de custo em runtime."""
    db, _ = mock_db
    tracker = TokenTracker(db)
    # Before: Sonnet = (3.0, 15.0)
    cost_before = tracker._calculate_cost(1_000_000, 0, ModelType.SONNET)
    assert cost_before == pytest.approx(3.0)
    # After: custom price
    tracker.update_prices({ModelType.SONNET.value: (20.0, 50.0)})
    cost_after = tracker._calculate_cost(1_000_000, 0, ModelType.SONNET)
    assert cost_after == pytest.approx(20.0)


def test_persist_pipeline_totals():
    """persist_pipeline_totals() acumula tokens e custo no PipelineExecution."""
    mock_cmd1 = MagicMock()
    mock_cmd1.tokens_input = 1000
    mock_cmd1.tokens_output = 500
    mock_cmd1.cost_usd = 0.0  # not used for sum; uses formula

    mock_pe = MagicMock()
    mock_pe.tokens_input = 0
    mock_pe.tokens_output = 0
    mock_pe.cost_usd = 0.0

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.all.return_value = [mock_cmd1]
    mock_session.get.return_value = mock_pe
    mock_session.__enter__ = lambda s: mock_session
    mock_session.__exit__ = MagicMock(return_value=False)

    db = MagicMock()
    db.get_session.return_value = mock_session

    tracker = TokenTracker(db)
    tracker.persist_pipeline_totals(pipeline_id=1)

    assert mock_pe.tokens_input == 1000
    assert mock_pe.tokens_output == 500
