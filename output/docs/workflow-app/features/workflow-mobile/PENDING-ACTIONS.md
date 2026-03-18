# PENDING-ACTIONS — Workflow Mobile Remote

<!-- Gerado por: /tech-debt-audit em 2026-03-16 -->
<!-- Total BLOQUEADORES: 0 | ALTOS: 6 -->
## Tech Debt Audit

Itens a resolver antes do deploy:

- [ ] [ALTO] Complexidade em `src/workflow_app/template_builder/template_list_panel.py`:1069 — extrair `TemplateFilterModel` e `TemplateCardWidget`
- [ ] [ALTO] Complexidade em `src/workflow_app/command_queue/command_queue_widget.py`:817 — extrair `CommandRowDelegate` e `CommandQueueModel`
- [ ] [ALTO] Complexidade em `src/workflow_app/template_builder/template_builder_widget.py`:784 — extrair `TemplateFormValidator` e `TemplatePreviewPanel`
- [ ] [ALTO] Complexidade em `src/workflow_app/main_window.py`:777 — extrair `MenuController` e `PanelRegistry`
- [ ] [ALTO] Complexidade em `src/workflow_app/pipeline/pipeline_manager.py`:711 — separar `PipelineExecutor` da persistência
- [ ] [ALTO] Dependência PySide6 6.7.2 → 6.10.2 (MINOR ×3) — atualizar com cuidado, validar testes após

<!-- /end:tech-debt-audit -->
