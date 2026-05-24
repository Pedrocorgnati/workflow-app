---
description: "Corrigir font-size do _label_widget em MCPPromptButton de 13px herdado para 10px explicito"
model: claude-sonnet-4-6
effort: low
scope: per_task
task_type: task
mode_support: auto
source_ref: "blacksmith/brainstorm-mcp/2026-05-23-workflow-app-layout.md#problema-3--tipografia-dos-9-botoes-brainstorm-fora-do-padrao"
---

# Task 003 — Corrigir tipografia dos 9 botoes brainstorm

## Acao

- Em `mcp_prompt_button.py`, metodo `_sync_visual_state` (~linha 748), localizar o `setStyleSheet` do `_label_widget`:
  ```python
  self._label_widget.setStyleSheet(
      f"color: {fg}; font-weight: 600; background: transparent;"
  )
  ```
- Substituir por:
  ```python
  self._label_widget.setStyleSheet(
      f"color: {fg}; font-size: 10px; font-weight: 600; background: transparent;"
  )
  ```
- Inspecionar visualmente os contextos de uso do `MCPPromptButton` alem da grade brainstorm (MCP column em `_build_mcp_column`) para confirmar que 10px nao trunca labels nessas instancias. O botao tem `setFixedHeight(22)` em ambos os contextos — compativel com 10px.

## Saida esperada

- `ai-forge/workflow-app/src/workflow_app/widgets/mcp_prompt_button.py` — `_sync_visual_state` contem `font-size: 10px` no stylesheet do `_label_widget`.

## Aceite

- `grep -n "font-size: 10px" ai-forge/workflow-app/src/workflow_app/widgets/mcp_prompt_button.py` retorna pelo menos 1 ocorrencia dentro de `_sync_visual_state`.
- Inspecao visual: os 9 botoes da grade brainstorm exibem texto com tamanho equivalente aos botoes `_SECTION_BTN_STYLE` (referencia: `command_queue_widget.py` linha 203).
- Nenhum label da MCP column fica truncado visivelmente.
- Suite pytest passa (`pytest ai-forge/workflow-app/tests/ -q`).
