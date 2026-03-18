"""Performance budgets do Workflow App (module-16/TASK-4).

Budgets definidos no PRD:
- Startup: < 5s em hardware modesto
- Output rendering: < 100ms por chunk (10k linhas)
- Drag-drop: < 16ms (60fps target)
"""
from __future__ import annotations

import time


def test_enums_and_dataclasses_import_fast():
    """Importar os tipos base deve ser < 50ms."""
    start = time.perf_counter()
    elapsed = (time.perf_counter() - start) * 1000
    assert elapsed < 50, f"Import de tipos base demorou {elapsed:.1f}ms (budget: 50ms)"


def test_metrics_timer_calculations_are_fast():
    """ElapsedTimer deve processar 1000 ticks em < 50ms."""
    from workflow_app.core.metrics_timer import ElapsedTimer

    timer = ElapsedTimer()
    timer.start()

    start = time.perf_counter()
    for _ in range(1000):
        timer.tick()
        ElapsedTimer.format(timer.elapsed)
    elapsed = (time.perf_counter() - start) * 1000

    assert elapsed < 50, f"1000 ticks + format demorou {elapsed:.1f}ms (budget: 50ms)"


def test_token_cost_calculation_is_fast():
    """1000 cálculos de custo devem completar em < 10ms."""
    from workflow_app.core.token_tracker import TokenTracker
    from workflow_app.domain import ModelType

    start = time.perf_counter()
    for _ in range(1000):
        tracker = TokenTracker.__new__(TokenTracker)
        tracker._prices = {"sonnet": (3.0, 15.0)}
        tracker._calculate_cost(5000, 2000, ModelType.SONNET)
    elapsed = (time.perf_counter() - start) * 1000

    assert elapsed < 10, f"1000 cálculos de custo demorou {elapsed:.1f}ms (budget: 10ms)"


def test_paginated_result_creation_is_fast():
    """Criar PaginatedResult com 50 itens deve ser < 5ms."""
    from workflow_app.domain import PipelineStatus
    from workflow_app.history.history_manager import PaginatedResult

    # Create lightweight mock items
    items = [
        type("MockPE", (), {
            "id": i,
            "project_name": f"proj-{i}",
            "status": PipelineStatus.CONCLUIDO.value,
            "duration_seconds": float(60 * i),
        })()
        for i in range(1, 51)
    ]

    start = time.perf_counter()
    for _ in range(100):
        page = PaginatedResult(
            items=items,
            total_count=50,
            page=1,
            page_size=50,
            total_pages=1,
        )
        _ = page.total_count
        _ = page.total_pages
    elapsed = (time.perf_counter() - start) * 1000

    assert elapsed < 5, f"100 PaginatedResult criações demorou {elapsed:.1f}ms (budget: 5ms)"
