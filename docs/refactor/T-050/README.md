# T-050 — Workflow-app DCP cleanup

Refactor que adequa o workflow-app (PySide6) ao DCP, implementado por TASK-050
de `scheduled-updates/refactor-workflow-sytemforge/TASK-050-workflow-app-dcp-cleanup.md`.

## Resumo

- **Command Queue tab "workflow"** passa a expor 2 botoes DCP novos:
  - `[DCP: Build Module Pipeline]` — paste literal `/build-module-pipeline`
  - `[DCP: Specific-Flow]` — resolve `current_module` via T-035 reader e pasta
    `/build-module-pipeline {id}` ou `/build-module-pipeline --rehydrate {id}`
- Botoes legacy recebem sufixo `(legacy)` e prefixo `[legacy ...]` nos tooltips
  para isolar monolitos F1..F11 da entrada canonica DCP.
- **Template Builder catalog** passa a renderizar dois blocos sequenciais:
  1. `DCP Canonical Loop (per module)` — 12 fases A..I (catalogo canonico)
  2. `Legacy Monolithic (F1..F11) — Deprecated` — catalogo antigo preservado
- **Gate** de reader: quando `workflow_app.dcp.READER_AVAILABLE` e falso, o
  botao `[DCP: Specific-Flow]` fica desabilitado no init do widget com tooltip
  "Requer T-035 (reader)".

## Arquivos tocados

```
src/workflow_app/dcp/__init__.py                                  (novo)
src/workflow_app/dcp/specific_flow_handler.py                     (novo)
src/workflow_app/command_queue/command_queue_widget.py            (editado)
src/workflow_app/template_builder/template_builder_widget.py      (editado)
tests/test_dcp_specific_flow_handler.py                           (novo)
docs/refactor/T-050/README.md                                     (este arquivo)
README.md                                                         (secao DCP mode vs Legacy mode)
```

## Screenshots (pendente — manual)

A captura de tela das 3 abas (Daily, Workflow, Auxiliar) e do catalogo do
Template Builder com os banners DCP / Legacy deve ser anexada manualmente
apos a primeira execucao local do workflow-app pos T-050.

Colocar em:

```
docs/refactor/T-050/screenshots/
  workflow-tab-dcp-buttons.png
  workflow-tab-legacy-isolated.png
  template-builder-dcp-block.png
  template-builder-legacy-block.png
  dcp-specific-flow-disabled-when-reader-missing.png
```

## Fonte da verdade

- Spec: `../../../../scheduled-updates/refactor-workflow-sytemforge/TASK-050-workflow-app-dcp-cleanup.md`
- Canonical loop A..I: `../../../../WORKFLOW-DETAILED.md#2-arquitetura-dcp-canonical-loop-ai`
- Detailed §6.4: `../../../../scheduled-updates/refactor-workflow-sytemforge/detailed.md`
- Execution readiness: `../../../../scheduled-updates/refactor-workflow-sytemforge/EXECUTION-READINESS-T-050.md`
