---
description: "Remover QLabel brainstorm-provider-label redundante do radio_row em main_window.py"
model: claude-sonnet-4-6
effort: low
scope: per_task
task_type: task
mode_support: auto
source_ref: "blacksmith/brainstorm-mcp/2026-05-23-workflow-app-layout.md#problema-1--remover-brainstorm-provider-label-redundante"
---

# Task 001 — Remover `brainstorm-provider-label`

## Acao

- Remover a linha que instancia `self._brainstorm_provider_label = QLabel("Provider: Claude")` em `_build_brainstorm_page` (~linha 2248 de `main_window.py`).
- Remover a linha `radio_row_layout.addWidget(self._brainstorm_provider_label)` na mesma funcao.
- Em `_on_brainstorm_type_changed`, remover a linha `self._brainstorm_provider_label.setText(...)` (~linha 2270) e qualquer outro acesso ao atributo `_brainstorm_provider_label`.
- Verificar com `grep -rn "brainstorm_provider_label\|brainstorm-provider-label"` que nao restam referencias orfas em `main_window.py`.
- Confirmar com o mesmo grep nos arquivos de testes (`ai-forge/workflow-app/tests/`) que nenhum teste referencia o testid `brainstorm-provider-label`.

## Saida esperada

- `ai-forge/workflow-app/src/workflow_app/main_window.py` — sem nenhuma ocorrencia de `brainstorm_provider_label` ou `brainstorm-provider-label`.

## Aceite

- `grep -rn "brainstorm_provider_label" ai-forge/workflow-app/src/` retorna vazio.
- `grep -rn "brainstorm-provider-label" ai-forge/workflow-app/` retorna vazio.
- App inicia sem `AttributeError` ao trocar o radio de provider.
- Suite pytest passa (`pytest ai-forge/workflow-app/tests/ -q`).
