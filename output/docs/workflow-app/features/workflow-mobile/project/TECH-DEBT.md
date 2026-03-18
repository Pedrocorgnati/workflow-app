---
Auditoria: 2026-03-16
---

# Auditoria de Dívida Técnica — Workflow Mobile Remote

**Gerado em:** 2026-03-16 14:00
**Workspace:** ai-forge/workflow-app
**Stack:** Python/PySide6 (desktop) + Android/Kotlin (Jetpack Compose)

## Resumo Executivo

| Categoria | BLOQUEADOR | ALTO | MÉDIO | BAIXO | Total |
|-----------|-----------|------|-------|-------|-------|
| Marcações (TODO/FIXME/HACK) | 0 | 0 | 4 | 0 | 4 |
| Complexidade Excessiva | 0 | 5 | 2 | 0 | 7 |
| Código Morto (vulture) | 0 | 0 | 0 | 0 | 0 |
| Dependências Desatualizadas | 0 | 1 | 1 | 2 | 4 |
| **TOTAL** | **0** | **6** | **7** | **2** | **15** |

Nenhum item BLOQUEADOR identificado.

---

## Itens ALTO

### [DEBT-001] Complexidade: `template_list_panel.py` — 1069 linhas

- **Arquivo:** `src/workflow_app/template_builder/template_list_panel.py`
- **Linhas:** 1069 (limite BLOQUEADOR: >800)
- **Impacto:** Widget PySide6 monolítico; dificulta manutenção e testes isolados.
- **Ação:** Extrair lógica de busca/filtro em `TemplateFilterModel`, separar `TemplateCardWidget` como componente autônomo.

### [DEBT-002] Complexidade: `command_queue_widget.py` — 817 linhas

- **Arquivo:** `src/workflow_app/command_queue/command_queue_widget.py`
- **Linhas:** 817 (limite BLOQUEADOR: >800)
- **Impacto:** Widget de fila de comandos com responsabilidades mistas; difícil de testar.
- **Ação:** Extrair `CommandRowDelegate` e `CommandQueueModel` (QAbstractTableModel) para separar dados de apresentação.

### [DEBT-003] Complexidade: `template_builder_widget.py` — 784 linhas

- **Arquivo:** `src/workflow_app/template_builder/template_builder_widget.py`
- **Linhas:** 784
- **Impacto:** Widget principal do template builder com lógica de UI, validação e persistência misturadas.
- **Ação:** Extrair `TemplateFormValidator` e `TemplatePreviewPanel`.

### [DEBT-004] Complexidade: `main_window.py` — 777 linhas

- **Arquivo:** `src/workflow_app/main_window.py`
- **Linhas:** 777
- **Impacto:** Janela principal concentra roteamento de eventos, menu e inicialização de painéis.
- **Ação:** Extrair `MenuController` e inicialização de painéis para `PanelRegistry`.

### [DEBT-005] Complexidade: `pipeline_manager.py` — 711 linhas

- **Arquivo:** `src/workflow_app/pipeline/pipeline_manager.py`
- **Linhas:** 711
- **Impacto:** Manager de pipeline com lógica de estado, execução e persistência acopladas.
- **Ação:** Separar `PipelineExecutor` da lógica de persistência de estado.

### [DEBT-006] Dependência: PySide6 3 versões MINOR desatualizada

- **Pacote:** PySide6 (+ PySide6_Addons, PySide6_Essentials, shiboken6)
- **Versão atual:** 6.7.2 | **Última:** 6.10.2
- **Impacto:** 3 versões MINOR atrás — potenciais melhorias de performance Qt, correções de bugs, novas APIs Compose-friendly.
- **Ação:** Atualizar com cuidado: `pip install PySide6==6.10.2` — validar testes após atualização.

---

## Itens MÉDIO

### [DEBT-007] TODO: Expandir testes de `WorkflowScreenTest`

- **Arquivo:** `android/app/src/androidTest/java/com/workflowapp/remote/ui/WorkflowScreenTest.kt:14`
- **Conteúdo:** `TODO: Expand after /auto-flow execute populates ViewModel with real logic.`
- **Ação:** Expandir com testes reais de ViewModel após execução do module-8.

### [DEBT-008] TODO: Tokens de cor em `ConnectionStatus.kt`

- **Arquivo:** `android/app/src/main/java/com/workflowapp/remote/model/ConnectionStatus.kt:43`
- **Conteúdo:** `TODO module-8: Replace hardcoded colors with MaterialTheme.colorScheme tokens.`
- **Ação:** Substituir cores hardcoded por `MaterialTheme.colorScheme.*` ao executar module-8.

### [DEBT-009] TODO: Tokens de cor em `PipelineViewState.kt` (×2)

- **Arquivo:** `android/app/src/main/java/com/workflowapp/remote/model/PipelineViewState.kt:13,52`
- **Conteúdo:** `TODO module-8: Replace hardcoded colors with MaterialTheme.colorScheme tokens.`
- **Ação:** Substituir cores hardcoded por `MaterialTheme.colorScheme.*` ao executar module-8.

### [DEBT-010] Complexidade: `interview/pipeline_creator_widget.py` — 693 linhas

- **Arquivo:** `src/workflow_app/interview/pipeline_creator_widget.py`
- **Linhas:** 693
- **Ação:** Extrair cada etapa do wizard em `StepWidget` independente.

### [DEBT-011] Complexidade: `output_panel/output_panel.py` — 587 linhas

- **Arquivo:** `src/workflow_app/output_panel/output_panel.py`
- **Linhas:** 587
- **Ação:** Separar renderizadores de tipo de saída em strategy classes.

### [DEBT-012] Complexidade: `sdk/sdk_adapter.py` — 571 linhas

- **Arquivo:** `src/workflow_app/sdk/sdk_adapter.py`
- **Linhas:** 571
- **Ação:** Extrair handlers de resposta por tipo de mensagem.

### [DEBT-013] Dependência: `anthropic` 1 versão MINOR desatualizada

- **Pacote:** anthropic
- **Versão atual:** 0.75.0 | **Última:** 0.85.0
- **Ação:** Avaliar changelog antes de atualizar — pode conter mudanças de API.

---

## Itens BAIXO

### [DEBT-014] Dependência: SQLAlchemy — atualização PATCH disponível

- **Pacote:** SQLAlchemy 2.0.46 → 2.0.48
- **Ação:** `pip install SQLAlchemy==2.0.48` — update seguro.

### [DEBT-015] Dependência: python-dotenv — atualização PATCH disponível

- **Pacote:** python-dotenv 1.2.1 → 1.2.2
- **Ação:** `pip install python-dotenv==1.2.2` — update seguro.

---

## Complexidade Excessiva — Tabela Completa

### Arquivos Grandes (> 500 linhas, excluindo testes)

| Arquivo | Linhas | Severidade | Sugestão |
|---------|--------|-----------|---------|
| `src/workflow_app/template_builder/template_list_panel.py` | 1069 | ALTO | Extrair `TemplateFilterModel`, `TemplateCardWidget` |
| `src/workflow_app/command_queue/command_queue_widget.py` | 817 | ALTO | Extrair `CommandRowDelegate`, `CommandQueueModel` |
| `src/workflow_app/template_builder/template_builder_widget.py` | 784 | ALTO | Extrair `TemplateFormValidator`, `TemplatePreviewPanel` |
| `src/workflow_app/main_window.py` | 777 | ALTO | Extrair `MenuController`, `PanelRegistry` |
| `src/workflow_app/pipeline/pipeline_manager.py` | 711 | ALTO | Separar `PipelineExecutor` da persistência |
| `src/workflow_app/interview/pipeline_creator_widget.py` | 693 | MÉDIO | Extrair `StepWidget` por etapa do wizard |
| `src/workflow_app/output_panel/output_panel.py` | 587 | MÉDIO | Strategy classes por tipo de saída |
| `src/workflow_app/sdk/sdk_adapter.py` | 571 | MÉDIO | Handlers por tipo de mensagem |

---

## Código Morto Identificado (via vulture)

Nenhum item detectado com `--min-confidence 80`. Base de código limpa.

---

## Dependências Desatualizadas

| Pacote | Atual | Última | Tipo | Recomendação |
|--------|-------|--------|------|-------------|
| PySide6 | 6.7.2 | 6.10.2 | MINOR (×3) | UPDATE_COM_CUIDADO — validar testes |
| PySide6_Addons | 6.7.2 | 6.10.2 | MINOR (×3) | UPDATE_COM_CUIDADO (junto com PySide6) |
| PySide6_Essentials | 6.7.2 | 6.10.2 | MINOR (×3) | UPDATE_COM_CUIDADO (junto com PySide6) |
| shiboken6 | 6.7.2 | 6.10.2 | MINOR (×3) | UPDATE_COM_CUIDADO (junto com PySide6) |
| anthropic | 0.75.0 | 0.85.0 | MINOR | AVALIAR changelog antes de atualizar |
| SQLAlchemy | 2.0.46 | 2.0.48 | PATCH | UPDATE_SEGURO |
| python-dotenv | 1.2.1 | 1.2.2 | PATCH | UPDATE_SEGURO |
| cryptography | 3.4.8 | 46.0.5 | MAJOR (sistema) | N/A — dependência do sistema, não direta |

---

## Plano de Correção

1. **Imediato (pré-deploy):** nenhum item BLOQUEADOR — pipeline desbloqueado.
2. **Próxima sprint (ALTOS):**
   - Atualizar PySide6 para 6.10.2 (validar suite de testes após)
   - Refatorar `template_list_panel.py` e `command_queue_widget.py` (>800 linhas)
3. **Backlog (MÉDIOS/BAIXOS):**
   - TODOs de tokens de cor Kotlin → cobertos pelo module-8
   - Refatorar arquivos 500–800 linhas em sprints de manutenção
   - Atualizar SQLAlchemy, python-dotenv (PATCH — sem risco)
