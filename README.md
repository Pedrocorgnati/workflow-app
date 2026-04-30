# Workflow App

Desktop app for managing Claude Code pipeline workflows (PySide6 + SQLite).

## Requirements

- Python 3.10+
- Linux with Qt6 libraries installed
- PySide6 6.7.x

## Installation

```bash
git clone <repo-url>
cd workflow-app
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running

```bash
make run
# or
python -m workflow_app.main
```

## Testing

```bash
make test
# or
python3 -m pytest tests/ -v --timeout=10 --ignore=tests/test_vault.py
```

## Lint

```bash
make lint
```

## Configuration

Place your `.claude/project.json` in the workspace directory selected via the app's config bar (Ctrl+O).

## Architecture

```
src/workflow_app/
├── main.py               # Entry point
├── main_window.py        # MainWindow (root widget)
├── signal_bus.py         # Global SignalBus singleton
├── domain.py             # Enums, dataclasses (CommandSpec, FilterSpec, TemplateDTO…)
├── tokens.py             # Design tokens (COLORS, TYPOGRAPHY, SPACING)
├── theme.py              # QSS stylesheet
├── config/               # AppState, ConfigParser
├── core/                 # Metrics, notifications, git, token tracking
├── db/                   # SQLAlchemy models + DatabaseManager
├── pipeline/             # PipelineManager, CommandStateMachine, SDKWorker
├── templates/            # TemplateManager (factory + custom templates)
├── history/              # HistoryManager (paginated history queries)
├── command_queue/        # CommandQueueWidget
├── metrics_bar/          # MetricsBar (top toolbar)
├── output_panel/         # OutputPanel (streaming terminal output)
├── dialogs/              # PreferencesDialog, ResumeDialog, etc.
├── interview/            # InterviewEngine (SYSTEM-PROGRESS.md)
└── sdk/                  # SDKAdapter (Claude Code CLI)
```

## Modules

16 modules implemented (84 tasks). See `output/wbs/workflow-app/modules/MODULES-PROGRESS.md`.

## DCP mode vs Legacy mode

A partir de T-050 o workflow-app separa a entrada **DCP canonical loop A..I
per module** da entrada legacy monolitica F1..F11. Ambas convivem para nao
quebrar templates existentes; novos pipelines devem usar apenas DCP.

| Aspecto | DCP (novo, canonico) | Legacy (F1..F11, deprecated) |
|---|---|---|
| Escopo de execucao | Por module (state-machine em `delivery.json`) | Projeto inteiro em fases monoliticas |
| Entry point UI — Command Queue | Botoes `[DCP: Build Module Pipeline]` e `[DCP: Specific-Flow]` na aba *workflow* | Botoes `modules (legacy)`, `specific-flow (legacy)`, `wbs`, `create`, `execute`, `qa`, `deploy` (tooltips marcados `[legacy ...]`) |
| Entry point CLI | `/build-module-pipeline` (paste literal) ou `/build-module-pipeline {id}` / `--rehydrate {id}` (resolvido via `delivery.json`) | `/auto-flow {indicator}` / `/front-end-build` / `/back-end-build` etc. |
| Catalogo — Template Builder | Bloco `DCP Canonical Loop (per module)` com 12 fases A, B, B.2, C, D, D.5, E, F, G, F.2, H, I | Bloco `Legacy Monolithic (F1..F11) — Deprecated` preservado como referencia |
| Fonte de verdade | `delivery.json` v1 (T-035 `DeliveryReader`) | Ausente — pipelines legacy nao tem state-machine |
| Dependencia para habilitar | T-035 (`workflow_app.services.delivery_reader`). O botao `[DCP: Specific-Flow]` fica desabilitado com tooltip `"Requer T-035 (reader)"` se a importacao falhar | Sempre disponivel (nao requer reader) |
| Mensagens de bloqueio | `QMessageBox.information` com texto literal da spec (`"Carregue um projeto (pill superior) antes de gerar pipeline DCP."`, `"Nenhum modulo ativo. Use [DCP: Build Module Pipeline] primeiro"`, `"delivery.json ausente — rode /delivery:init..."`, etc.) | Sem gates explicitos |
| Uso recomendado | Novos projetos e modules novos | Manter apenas para projetos que nao foram migrados para `delivery.json` |

### Quadro resumo (spec T-050)

| Fluxo | Botao | Estado |
|-------|-------|--------|
| Creation (Fase A) | Modules (Creation) | cria WBS + MODULE-META + delivery.json |
| DCP (Fase A→B) | DCP: Build Module Pipeline + DCP: Specific-Flow | gera SPECIFIC-FLOW.json e transita pending → creation |

Para detalhes do refactor T-050 veja `docs/refactor/T-050/README.md`.
