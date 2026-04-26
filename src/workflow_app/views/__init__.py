"""Top-level workflow-app views.

Each view is a ``QWidget`` that renders one full page of the application.
Pages are registered in ``main_window.MainWindow._setup_ui`` under
``_view_stack`` and switched by the ``MetricsBar`` navigation buttons.
"""

from workflow_app.views.kanban import KanbanView
from workflow_app.views.module_detail import ModuleDetailView

__all__ = ["KanbanView", "ModuleDetailView"]
