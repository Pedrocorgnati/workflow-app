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
