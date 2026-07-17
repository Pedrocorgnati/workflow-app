"""TASK-1 layout refactor regression tests.

Cobre AC-1.1, AC-1.3, AC-1.4: ToolboxHeader removido, queue-progress-ring
presente em listeners-frame, autocast e schedule-autocast btns expostos na
play bar do CommandQueueWidget.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QPushButton

from workflow_app.command_queue.command_queue_widget import (
    CommandQueueWidget,
    ResponsiveButtonFlowLayout,
)
from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.signal_bus import signal_bus
from workflow_app.widgets.queue_progress_ring import QueueProgressRing


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _find_by_testid(parent, testid: str):
    for w in parent.findChildren(QPushButton):
        if w.property("testid") == testid:
            return w
    return None


def _find_widget_by_testid(parent, testid: str):
    from PySide6.QtWidgets import QWidget

    for w in [parent, *parent.findChildren(QWidget)]:
        if w.property("testid") == testid:
            return w
    return None


def test_main_window_no_toolbox_header_attr(app):
    """AC-1.1: MainWindow nao deve mais ter _toolbox_header."""
    from workflow_app.main_window import MainWindow
    win = MainWindow()
    assert not hasattr(win, "_toolbox_header"), "ToolboxHeader nao foi removido"


def test_metrics_bar_has_queue_progress_ring(app):
    """Refactor 2026-05-17 power-bi-section: o ring continua owned por
    MetricsBar (signal pipelines preservados), mas nao e mais filho do
    listeners-frame — virou IRMAO dentro do power-bi-section montado em
    MainWindow._build_output_toolbar. Aqui (sem MainWindow), o ring fica
    sem parent ate ser reparenteado pelo PowerBiSection.
    """
    mb = MetricsBar()
    assert hasattr(mb, "_queue_progress_ring")
    assert isinstance(mb._queue_progress_ring, QueueProgressRing)
    assert mb._queue_progress_ring.parent() is None


def test_command_queue_has_autocast_buttons(app):
    """AC-1.4: autocast e schedule-autocast vivem agora na play bar."""
    cq = CommandQueueWidget()
    assert _find_by_testid(cq, "autocast-btn") is not None
    assert _find_by_testid(cq, "schedule-autocast-btn") is not None


def test_output_toolbar_left_splits_insertions_controls(app):
    """Refactor output-toolbar-left/center: as abas primarias (Workflow/LOOPs/
    Auxiliar) ficam no header output-toolbar-left; o bloco insertions-controls
    migrou para output-toolbar-center, reparenteado por MainWindow._setup_ui
    (command_queue_widget.py: "insertions_bar NAO entra no tab_row" +
    main_window.py: _center_layout.addWidget(insertions_bar)). Em standalone o
    insertions_bar fica sem parent; so a MainWindow completa o ancora no center.
    A aba Inserchoes (queue-tab-terminal-insertions) deixou de ser botao de aba
    (conteudo sempre visivel no center), entao nao e mais procurada aqui.
    """
    from workflow_app.main_window import MainWindow

    win = MainWindow()

    # Abas primarias permanecem no header output-toolbar-left.
    primary = win._command_queue._tab_bar_layout.parentWidget()
    assert primary is not None
    assert primary.property("testid") == "output-toolbar-left-primary-tabs"
    for tab in win._command_queue._sec_tabs[:3]:
        assert tab.parentWidget() is primary

    # insertions-controls migrou para output-toolbar-center (fora do header).
    insertions = win._command_queue.insertions_bar
    center = insertions.parentWidget()
    assert insertions is not None
    assert center is not None
    assert insertions.property("testid") == "output-toolbar-left-insertions-controls"
    assert center.property("testid") == "output-toolbar-center"
    assert insertions.parentWidget() is center


def test_output_toolbar_left_subtabs_use_responsive_flow(app):
    """Subtabs internas quebram linha e compactam sem renderizar mais de 4 linhas."""
    from PySide6.QtWidgets import QWidget

    cq = CommandQueueWidget()
    assert isinstance(cq._subtab_paths_layout, ResponsiveButtonFlowLayout)
    assert isinstance(cq._subtab_prompts_layout, ResponsiveButtonFlowLayout)
    assert isinstance(cq._subtab_rules_layout, ResponsiveButtonFlowLayout)

    path_buttons = [QPushButton("path-a"), QPushButton("path-b")]
    second_row_buttons = [QPushButton("repo rules")]
    cq.populate_paths_subtab(path_buttons, second_row_buttons)
    assert cq._subtab_paths_layout.count() == 3

    parent = QWidget()
    layout = ResponsiveButtonFlowLayout(parent, spacing=4, max_lines=4)
    for i in range(18):
        btn = QPushButton(f"btn-{i}")
        btn.setFixedHeight(28)
        btn.setMinimumWidth(64)
        layout.addWidget(btn)

    layout.setGeometry(QRect(0, 0, 180, 200))
    y_positions = {
        layout.itemAt(i).widget().geometry().y()
        for i in range(layout.count())
    }
    widths = [
        layout.itemAt(i).widget().geometry().width()
        for i in range(layout.count())
    ]
    max_right = max(
        layout.itemAt(i).widget().geometry().right()
        for i in range(layout.count())
    )

    assert len(y_positions) <= 4
    assert min(widths) < 64
    assert max_right < 180


def test_personas_flow_keeps_34_agents_and_utilities_within_four_lines(app):
    """34 personas + gear/update continuam acionaveis em quatro linhas."""
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    layout = win._command_queue._subtab_personas_layout
    win._command_queue._personas_filter_bar.setCurrentIndex(0)
    win._command_queue._apply_persona_filter()

    assert layout.count() == 36
    layout.setGeometry(QRect(0, 0, 640, 220))
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert all(widget is not None for widget in widgets)
    assert len({widget.geometry().y() for widget in widgets}) <= 4
    assert max(widget.geometry().right() for widget in widgets) < 640

    persona_widgets = [
        widget for widget in widgets
        if str(widget.property("testid")).startswith("queue-btn-persona-")
    ]
    assert len(persona_widgets) == 34
    assert all(widget.accessibleName() for widget in persona_widgets)


def test_attachment_row_keeps_visible_controls_non_overlapping(app):
    """Project/loop/brainstorm attachments stay split and non-overlapping."""
    from workflow_app.config.app_state import app_state
    from workflow_app.main_window import MainWindow

    app_state.clear_all()
    win = MainWindow()
    project_name = "project-with-a-very-long-name-for-small-viewports"
    loop_name = "loop-with-a-very-long-name-for-small-viewports"
    win._metrics_bar._apply_project_loaded(project_name)
    win._metrics_bar._apply_loop_loaded(loop_name)
    win.resize(640, 480)
    win.show()
    app.processEvents()

    assert win._metrics_bar._project_name_lbl.toolTip() == project_name
    assert win._metrics_bar._loop_name_lbl.toolTip() == loop_name
    assert win._metrics_bar._project_name_lbl.maximumWidth() <= 180
    assert win._metrics_bar._loop_name_lbl.maximumWidth() <= 180

    attachments_block = win._attachments_block
    project_row = win._attachments_project_row
    loop_row = win._attachments_loop_row
    brainstorm_row = win._attachments_brainstorm_row
    actions_row = win._clear_queue_btn.parentWidget()

    assert attachments_block is not None
    assert project_row is not None
    assert loop_row is not None
    assert brainstorm_row is not None
    assert actions_row is not None
    assert project_row.parentWidget() is attachments_block
    assert loop_row.parentWidget() is attachments_block
    assert brainstorm_row.parentWidget() is attachments_block
    assert actions_row.parentWidget() is not attachments_block

    row_tops = {project_row.geometry().top(), loop_row.geometry().top(), brainstorm_row.geometry().top()}
    assert len(row_tops) == 3, "anexos devem ocupar linhas semanticas separadas"

    for row in (project_row, loop_row, brainstorm_row):
        visible_items = []
        layout = row.layout()
        for idx in range(layout.count()):
            item = layout.itemAt(idx)
            widget = item.widget()
            if widget is not None and widget.isVisible():
                visible_items.append(widget)

        previous_right = -1
        for widget in visible_items:
            geom = widget.geometry()
            assert geom.left() > previous_right
            previous_right = geom.right()


def test_autocast_toggle_signal_proxied(app):
    """AC-1.4: clicar autocast na play bar emite autocast_toggle_requested."""
    cq = CommandQueueWidget()
    received: list[bool] = []
    signal_bus.autocast_toggle_requested.connect(received.append)
    btn = _find_by_testid(cq, "autocast-btn")
    btn.setChecked(True)
    btn.setChecked(False)
    assert received[-2:] == [True, False]


def test_schedule_autocast_signal_proxied(app):
    """AC-1.4: clicar agendar emite schedule_autocast_requested."""
    cq = CommandQueueWidget()
    received: list[int] = []
    signal_bus.schedule_autocast_requested.connect(lambda: received.append(1))
    btn = _find_by_testid(cq, "schedule-autocast-btn")
    btn.click()
    assert received[-1] == 1
