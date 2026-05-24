---
description: "Adicionar setProperty testid ao grid_widget BrainstormGrid em main_window.py"
model: claude-sonnet-4-6
effort: low
scope: per_task
task_type: task
mode_support: auto
source_ref: "blacksmith/brainstorm-mcp/2026-05-23-workflow-app-layout.md#problema-2--adicionar-testid-ao-container-dos-9-botoes-brainstorm"
---

# Task 002 — Adicionar `testid` ao `BrainstormGrid`

## Acao

- Em `_build_brainstorm_page` (`main_window.py` ~linha 2277), imediatamente apos `grid_widget.setObjectName("BrainstormGrid")`, adicionar:
  ```python
  grid_widget.setProperty("testid", "brainstorm-buttons-grid")
  ```
- Verificar que `_rebuild_brainstorm_grid` tambem cobre o mesmo widget (o rebuild reutiliza `self._brainstorm_grid_widget`, entao o testid persiste automaticamente — confirmar que nao ha novo `QWidget()` criado no rebuild sem o testid).

## Saida esperada

- `ai-forge/workflow-app/src/workflow_app/main_window.py` — contem `setProperty("testid", "brainstorm-buttons-grid")` imediatamente apos `setObjectName("BrainstormGrid")`.

## Aceite

- `grep -n "brainstorm-buttons-grid" ai-forge/workflow-app/src/workflow_app/main_window.py` retorna exatamente 1 ocorrencia.
- Widget com `objectName="BrainstormGrid"` tambem tem `testid="brainstorm-buttons-grid"` inspecionado em runtime via `widget.property("testid")`.
- Suite pytest passa (`pytest ai-forge/workflow-app/tests/ -q`).
