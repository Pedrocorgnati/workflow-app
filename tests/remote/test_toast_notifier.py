"""Tests for ToastNotifier (module-5/TASK-1 — widgets/toast_notifier.py)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

from workflow_app.widgets.toast_notifier import MAX_ACTIVE_TOASTS, ToastNotifier


@pytest.fixture
def parent_window(qapp):
    w = QWidget()
    w.resize(800, 600)
    w.show()
    return w


@pytest.fixture
def notifier(parent_window):
    return ToastNotifier(parent_window)


def test_show_creates_active_toast(notifier):
    notifier.show("Mensagem de teste", "info")
    assert len(notifier._active) == 1


def test_show_multiple_toasts_stacked(notifier):
    notifier.show("Toast 1", "info")
    notifier.show("Toast 2", "error")
    assert len(notifier._active) == 2


def test_dismiss_removes_toast(notifier):
    notifier.show("Para remover", "warning")
    assert len(notifier._active) == 1
    toast = notifier._active[0]
    notifier._remove_toast(toast)
    assert len(notifier._active) == 0


def test_max_active_toasts_guard(notifier):
    """Garante que flooding é bloqueado após MAX_ACTIVE_TOASTS."""
    for i in range(MAX_ACTIVE_TOASTS + 3):
        notifier.show(f"Toast {i}", "info")
    assert len(notifier._active) <= MAX_ACTIVE_TOASTS


def test_show_all_levels_no_exception(notifier):
    """Todos os níveis válidos devem exibir sem erro."""
    for level in ("info", "success", "warning", "error"):
        notifier.show(f"Nível {level}", level)


def test_unknown_level_falls_back_to_info(notifier):
    """Nível desconhecido não deve gerar exceção (fallback para info)."""
    notifier.show("Nível inválido", "unknown_level")
    assert len(notifier._active) >= 1
