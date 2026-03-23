"""
CommandQueueWidget — 280px right panel showing the command queue.

States:
  - Empty: "Nenhum pipeline configurado." + [Criar Pipeline] button
  - With commands: scrollable list of CommandItemWidget rows + [+] button at bottom

Width: fixed 280px (min 240px, max 360px)
"""

from __future__ import annotations

import copy
import json
import re

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from workflow_app.command_queue.command_item_widget import CommandItemWidget
from workflow_app.dialogs.confirm_cancel_modal import ConfirmCancelModal
from workflow_app.domain import CommandSpec, CommandStatus, InteractionType, ModelName
from workflow_app.signal_bus import signal_bus
from workflow_app.templates.quick_templates import (
    TEMPLATE_AUTO_IMPROOVE_LOOP,
    TEMPLATE_AUTOCAST_TEST,
    TEMPLATE_BRIEF_FEATURE,
    TEMPLATE_BRIEF_NEW,
    TEMPLATE_BUSINESS,
    TEMPLATE_DAILY,
    TEMPLATE_DEPLOY,
    TEMPLATE_JSON,
    TEMPLATE_MKT,
    TEMPLATE_MODULES,
)

_DROP_INDICATOR_COLOR = QColor("#F59E0B")  # Amber-400
_DROP_INDICATOR_WIDTH = 2

_SECTION_HEADER_STYLE = (
    "QPushButton { background-color: #1E1E21; color: #A1A1AA;"
    "  border: none; border-bottom: 1px solid #3F3F46;"
    "  border-radius: 0; text-align: left; padding: 3px 8px;"
    "  font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }"
    "QPushButton:hover { background-color: #2D2D30; color: #D4D4D8; }"
)

_SECTION_BTN_STYLE = (
    "QPushButton { background-color: #3F3F46; color: #D4D4D8;"
    "  border: 1px solid #52525B; border-radius: 4px;"
    "  font-size: 10px; font-weight: 600; padding: 2px 3px; }"
    "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
    "QPushButton:pressed { background-color: #FBBF24; color: #18181B; border-color: #FBBF24; }"
)

_TAB_ACTIVE_STYLE = (
    "QPushButton { background-color: #FBBF24; color: #18181B;"
    "  border: none; border-radius: 3px;"
    "  font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }"
)
_TAB_INACTIVE_STYLE = (
    "QPushButton { background-color: transparent; color: #A1A1AA;"
    "  border: none; border-radius: 3px;"
    "  font-size: 10px; font-weight: 600; letter-spacing: 0.5px; }"
    "QPushButton:hover { color: #D4D4D8; background-color: #2D2D30; }"
)


class _CollapsibleSection(QWidget):
    """Expandable/collapsible section with chevron header and 3-column button grid."""

    def __init__(
        self,
        title: str,
        expanded: bool = False,
        cols: int = 3,
        parent: QWidget | None = None,
        *,
        testid: str = "",
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._expanded = expanded
        self._cols = cols
        self._row = 0
        self._col = 0
        if testid:
            self.setProperty("testid", testid)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._toggle_btn = QPushButton(self._header_text())
        self._toggle_btn.setFixedHeight(24)
        self._toggle_btn.setStyleSheet(_SECTION_HEADER_STYLE)
        self._toggle_btn.clicked.connect(self._toggle)
        outer.addWidget(self._toggle_btn)

        self._content = QWidget()
        self._content.setStyleSheet("background-color: #27272A;")
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(5, 4, 5, 5)
        self._grid.setSpacing(3)
        self._content.setVisible(expanded)
        outer.addWidget(self._content)

    def _header_text(self) -> str:
        arrow = "▼" if self._expanded else "▶"
        return f"  {arrow}  {self._title.upper()}"

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._toggle_btn.setText(self._header_text())

    def add_button(self, label: str, tooltip: str, callback, *, testid: str = "") -> QPushButton:
        btn = QPushButton(label)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(_SECTION_BTN_STYLE)
        btn.clicked.connect(callback)
        self._grid.addWidget(btn, self._row, self._col)
        self._col += 1
        if self._col >= self._cols:
            self._col = 0
            self._row += 1
        return btn


class _DroppableContainer(QWidget):
    """QWidget subclass that paints a drop-position indicator line."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drop_indicator_pos: int | None = None

    def set_drop_indicator(self, pos: int | None) -> None:
        self._drop_indicator_pos = pos
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._drop_indicator_pos is None:
            return
        layout = self.layout()
        if layout is None:
            return
        count = layout.count()
        idx = self._drop_indicator_pos
        y: int
        if idx <= 0:
            y = 0
        elif idx >= count:
            last = layout.itemAt(count - 1)
            if last and last.widget():
                y = last.widget().geometry().bottom()
            else:
                y = self.height()
        else:
            item = layout.itemAt(idx)
            if item and item.widget():
                y = item.widget().geometry().top()
            else:
                y = 0
        painter = QPainter(self)
        pen = QPen(_DROP_INDICATOR_COLOR, _DROP_INDICATOR_WIDTH)
        painter.setPen(pen)
        painter.drawLine(4, y, self.width() - 4, y)
        painter.end()


class CommandQueueWidget(QWidget):
    """Right sidebar showing the pipeline command queue."""

    new_pipeline_requested = Signal()
    add_command_requested = Signal()
    reorder_requested = Signal(int, int)  # from_pos, to_pos (spec positions / indicator idx)
    save_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandQueueWidget")
        self.setMinimumWidth(200)
        self.setStyleSheet(
            "background-color: #18181B; border-left: 1px solid #3F3F46;"
        )

        self._items: list[CommandItemWidget] = []
        self._pipeline_manager = None
        self._autocast_active = False
        self._autocast_pending_advance = False  # Guard against duplicate advances
        self._loop_active = False  # Loop mode: restart queue when all commands finish
        self._cli_binary = "clauded"  # Active CLI instance (updated via instance_selected)
        self._autocast_workers: list = []  # Keep alive to prevent GC mid-run
        self._setup_ui()
        self._connect_signals()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header — tab row (Daily | Workflow | Auxiliar) + accordion content
        header = QWidget()
        header.setObjectName("CommandQueueHeader")
        header.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        # ── Tab bar (3 buttons in a row) ─────────────────────────────────
        tab_bar = QWidget()
        tab_bar.setFixedHeight(28)
        tab_bar.setStyleSheet("background-color: #1E1E21;")
        tab_bar_layout = QHBoxLayout(tab_bar)
        tab_bar_layout.setContentsMargins(4, 3, 4, 3)
        tab_bar_layout.setSpacing(3)

        self._sec_tabs: list[QPushButton] = []
        for i, label in enumerate(("Daily", "Workflow", "Auxiliar")):
            btn = QPushButton(label.upper())
            btn.setFixedHeight(22)
            btn.clicked.connect(lambda _ch=False, idx=i: self._switch_section(idx))
            tab_bar_layout.addWidget(btn, stretch=1)
            self._sec_tabs.append(btn)

        header_layout.addWidget(tab_bar)

        # ── Section contents (only one visible at a time) ────────────────
        self._sec_contents: list[QWidget] = []

        # Daily
        daily_content = self._build_section_grid([
            ("daily", "Daily tasks: scan → plan → do → validate → review",
             lambda: self._load_quick_template(TEMPLATE_DAILY, name="Daily"),
             "queue-btn-daily"),
            ("micro-json", "Configura project.json para micro-arquitetura",
             self._on_micro_json_clicked, "queue-btn-micro-json"),
            ("micro-arch", "Carrega pipeline de micro-arquitetura",
             self._on_micro_arch_clicked, "queue-btn-micro-arch"),
        ])
        header_layout.addWidget(daily_content)
        self._sec_contents.append(daily_content)

        # Workflow
        workflow_content = self._build_section_grid([
            ("json", "/project-json — Cria/atualiza project.json",
             lambda: self._load_quick_template(TEMPLATE_JSON, name="JSON"),
             "queue-btn-json"),
            ("brief new", "/first-brief-create → intake → PRD (novo projeto)",
             lambda: self._load_quick_template(TEMPLATE_BRIEF_NEW, name="Brief \u2014 Novo Projeto"),
             "queue-btn-brief-new"),
            ("brief feat", "/feature-brief-create → intake → PRD (nova feature)",
             lambda: self._load_quick_template(TEMPLATE_BRIEF_FEATURE, name="Brief \u2014 Feature"),
             "queue-btn-brief-feat"),
            ("modules", "Pipeline F4 de modules: core → blueprints → variants → structure",
             lambda: self._load_quick_template(TEMPLATE_MODULES, name="Modules"),
             "queue-btn-modules"),
            ("wbs", "WBS dinâmico — analisa modules existentes e gera tasks",
             self._on_wbs_clicked, "queue-btn-wbs"),
            ("qa", "QA + auditoria de stack (selecione a stack no modal)",
             self._on_qa_clicked, "queue-btn-qa"),
            ("deploy", "CI/CD, infra, pre-deploy, SLO, changelog",
             lambda: self._load_quick_template(TEMPLATE_DEPLOY, name="Deploy"),
             "queue-btn-deploy"),
        ])
        header_layout.addWidget(workflow_content)
        self._sec_contents.append(workflow_content)

        # Auxiliar
        auxiliar_content = self._build_section_grid([
            ("business", "Business: product-brief, SOW, budget, PDFs",
             lambda: self._load_quick_template(TEMPLATE_BUSINESS, name="Business"),
             "queue-btn-business"),
            ("mkt", "Marketing: portfolio, LinkedIn, Instagram",
             lambda: self._load_quick_template(TEMPLATE_MKT, name="Marketing"),
             "queue-btn-mkt"),
            ("auto-improove", "/model Opus + 5x /auto-improove:cmd (use com Loop)",
             lambda: self._load_quick_template(TEMPLATE_AUTO_IMPROOVE_LOOP, name="Auto-Improove Loop"),
             "queue-btn-auto-improove"),
            ("autocast-test", "Testa ciclo completo do autocast",
             lambda: self._load_quick_template(TEMPLATE_AUTOCAST_TEST, name="Autocast Test"),
             "queue-btn-autocast-test"),
            ("Sonnet", "Envia /model sonnet no terminal",
             lambda: signal_bus.run_command_in_terminal.emit("/model sonnet"),
             "queue-btn-model-sonnet"),
            ("Opus", "Envia /model opus no terminal",
             lambda: signal_bus.run_command_in_terminal.emit("/model opus"),
             "queue-btn-model-opus"),
        ])
        header_layout.addWidget(auxiliar_content)
        self._sec_contents.append(auxiliar_content)

        # Default: Workflow active (index 1)
        self._active_section = 1
        self._apply_section_styles()

        main_layout.addWidget(header)

        # Play bar — big play button
        play_bar = QWidget()
        play_bar.setStyleSheet(
            "background-color: #1C1C1F; border-bottom: 1px solid #3F3F46;"
        )
        play_bar.setFixedHeight(44)
        pl = QHBoxLayout(play_bar)
        pl.setContentsMargins(8, 5, 8, 5)

        self._play_btn = QPushButton("▶  Rodar próximo")
        self._play_btn.setFixedHeight(32)
        self._play_btn.setStyleSheet(
            "QPushButton { background-color: #16A34A; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 13px; font-weight: 700; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:pressed { background-color: #166534; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._play_btn.clicked.connect(self.run_next_pending)
        pl.addWidget(self._play_btn, stretch=7)

        # Autocast button — runs all AUTO commands sequentially, stops on INTERACTIVE
        self._autocast_btn = QPushButton("Autocast")
        self._autocast_btn.setFixedHeight(32)
        self._autocast_btn.setToolTip(
            "Executa comandos automáticos em sequência.\n"
            "Para ao chamar o primeiro comando interativo."
        )
        self._autocast_btn.setStyleSheet(
            "QPushButton { background-color: #7C3AED; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { background-color: #6D28D9; }"
            "QPushButton:pressed { background-color: #5B21B6; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._autocast_btn.clicked.connect(self._on_autocast_clicked)
        pl.addWidget(self._autocast_btn, stretch=2)

        # Loop button — runs autocast in a loop (restarts queue when finished)
        self._loop_btn = QPushButton("Loop")
        self._loop_btn.setFixedHeight(32)
        self._loop_btn.setToolTip(
            "Executa comandos em loop contínuo.\n"
            "Quando o último termina, reinicia pelo primeiro.\n"
            "Clique 'Parar' para interromper."
        )
        self._loop_btn.setStyleSheet(
            "QPushButton { background-color: #0891B2; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { background-color: #0E7490; }"
            "QPushButton:pressed { background-color: #155E75; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._loop_btn.clicked.connect(self._on_loop_clicked)
        pl.addWidget(self._loop_btn, stretch=2)

        # Botão JSON — copia path do project.json para o clipboard
        self._json_btn = QPushButton("JSON")
        self._json_btn.setFixedHeight(32)
        self._json_btn.setToolTip("Copia o caminho do project.json\ne digita no terminal automaticamente")
        self._json_btn.setStyleSheet(
            "QPushButton { background-color: #D97706; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 10px; font-weight: 700; }"
            "QPushButton:hover { background-color: #B45309; }"
            "QPushButton:pressed { background-color: #92400E; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._json_btn.clicked.connect(self._on_copy_json_path)
        pl.addWidget(self._json_btn, stretch=1)

        # Botão WS — copia workspace_root para o clipboard
        self._ws_btn = QPushButton("WS")
        self._ws_btn.setFixedHeight(32)
        self._ws_btn.setToolTip("Copia o workspace_root do projeto\ne digita no terminal automaticamente")
        self._ws_btn.setStyleSheet(
            "QPushButton { background-color: #059669; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 10px; font-weight: 700; }"
            "QPushButton:hover { background-color: #047857; }"
            "QPushButton:pressed { background-color: #065F46; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._ws_btn.clicked.connect(self._on_copy_ws_path)
        pl.addWidget(self._ws_btn, stretch=1)
        main_layout.addWidget(play_bar)

        # Template indicator label — shows which template/button was clicked
        self._template_label = QLabel("")
        self._template_label.setProperty("testid", "queue-template-label")
        self._template_label.setFixedHeight(28)
        self._template_label.setStyleSheet(
            "background-color: #1C1C1F; color: #A1A1AA;"
            " border-bottom: 1px solid #3F3F46;"
            " padding: 4px 10px; font-size: 11px;"
        )
        self._template_label.setVisible(False)
        main_layout.addWidget(self._template_label)

        # Last command played — shows the last ▶ command, one token per line
        self._last_cmd_label = QLabel("")
        self._last_cmd_label.setProperty("testid", "queue-last-command")
        self._last_cmd_label.setStyleSheet(
            "background-color: #1C1C1F; color: #D4D4D8;"
            " border-bottom: 1px solid #3F3F46;"
            " padding: 4px 10px; font-size: 11px; font-family: monospace;"
        )
        self._last_cmd_label.setWordWrap(True)
        self._last_cmd_label.setVisible(False)
        main_layout.addWidget(self._last_cmd_label)

        # Stacked content (empty state vs list)
        self._content_stack = QWidget()
        content_layout = QVBoxLayout(self._content_stack)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self._content_stack.setMinimumHeight(100)

        # ── Notepad ───────────────────────────────────────────────────────── #
        notepad_container = QWidget()
        notepad_container.setObjectName("NotepadContainer")
        notepad_container.setStyleSheet(
            "QWidget#NotepadContainer { background-color: #1C1C1F; border-top: 1px solid #3F3F46; }"
        )
        notepad_vl = QVBoxLayout(notepad_container)
        notepad_vl.setContentsMargins(0, 0, 0, 0)
        notepad_vl.setSpacing(0)

        notepad_header = QWidget()
        notepad_header.setFixedHeight(26)
        notepad_header.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )
        nh_layout = QHBoxLayout(notepad_header)
        nh_layout.setContentsMargins(8, 0, 6, 0)
        nh_layout.setSpacing(4)
        notepad_title = QLabel("📝 Bloco de Notas")
        notepad_title.setStyleSheet(
            "color: #A1A1AA; font-size: 10px; font-weight: 600; border: none;"
        )
        nh_layout.addWidget(notepad_title, stretch=1)
        clear_notepad_btn = QPushButton("Limpar")
        clear_notepad_btn.setFixedHeight(18)
        clear_notepad_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 3px;"
            "  font-size: 9px; padding: 1px 6px; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
        )
        nh_layout.addWidget(clear_notepad_btn)
        notepad_vl.addWidget(notepad_header)

        self._notepad_edit = QPlainTextEdit()
        self._notepad_edit.setProperty("testid", "queue-notepad")
        self._notepad_edit.setPlaceholderText("Escreva aqui e clique Enviar…")
        self._notepad_edit.setStyleSheet(
            "QPlainTextEdit {"
            "  background-color: #18181B; color: #FAFAFA;"
            "  border: none; font-size: 11px; padding: 4px 8px;"
            "  font-family: monospace; }"
        )
        notepad_vl.addWidget(self._notepad_edit)

        send_bar = QWidget()
        send_bar.setFixedHeight(38)
        send_bar.setStyleSheet(
            "background-color: #1C1C1F; border-top: 1px solid #3F3F46;"
        )
        send_bar_layout = QHBoxLayout(send_bar)
        send_bar_layout.setContentsMargins(4, 3, 8, 3)
        send_bar_layout.addStretch()

        notepad_send_btn = QPushButton("➤")
        notepad_send_btn.setFixedSize(32, 32)
        notepad_send_btn.setToolTip("Enviar")
        notepad_send_btn.setStyleSheet(
            "QPushButton { background-color: #2563EB; color: #FAFAFA;"
            "  border: none; border-radius: 16px;"
            "  font-size: 14px; font-weight: 700; }"
            "QPushButton:hover { background-color: #1D4ED8; }"
            "QPushButton:pressed { background-color: #1E40AF; }"
        )
        notepad_send_btn.clicked.connect(self._on_notepad_send)
        clear_notepad_btn.clicked.connect(self._notepad_edit.clear)
        send_bar_layout.addWidget(notepad_send_btn)
        notepad_vl.addWidget(send_bar)

        notepad_container.setMinimumHeight(80)

        # ── QSplitter: lista de comandos + notepad ───────────────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("CommandNoteSplitter")
        splitter.setHandleWidth(4)
        splitter.addWidget(self._content_stack)
        splitter.addWidget(notepad_container)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3F3F46; }"
            "QSplitter::handle:hover { background-color: #52525B; }"
            "QSplitter::handle:pressed { background-color: #71717A; }"
        )
        main_layout.addWidget(splitter, stretch=1)

        # Empty state
        self._empty_widget = QWidget()
        el = QVBoxLayout(self._empty_widget)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.setSpacing(12)
        empty_label = QLabel("Nenhum pipeline\nconfigurado.")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label.setStyleSheet("color: #71717A; font-size: 13px;")
        el.addWidget(empty_label)

        self._create_pipeline_btn = QPushButton("Criar Pipeline")
        self._create_pipeline_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #FBBF24;"
            "  border: 1px solid #FBBF24; border-radius: 4px;"
            "  padding: 6px 14px; font-weight: 600; }"
            "QPushButton:hover { background-color: #78350F; }"
        )
        self._create_pipeline_btn.clicked.connect(self.new_pipeline_requested)
        el.addWidget(self._create_pipeline_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # List view
        self._list_widget = QWidget()
        list_layout = QVBoxLayout(self._list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background-color: #18181B; }"
            " QScrollBar:horizontal { background: #1C1C1F; height: 8px; border: none; }"
            " QScrollBar::handle:horizontal { background: #52525B; border-radius: 4px; min-width: 30px; }"
            " QScrollBar::handle:horizontal:hover { background: #71717A; }"
            " QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }"
            " QScrollBar:vertical { background: #1C1C1F; width: 8px; border: none; }"
            " QScrollBar::handle:vertical { background: #52525B; border-radius: 4px; min-height: 30px; }"
            " QScrollBar::handle:vertical:hover { background: #71717A; }"
            " QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._items_container = _DroppableContainer()
        self._items_container.setStyleSheet("background-color: #18181B;")
        self._items_container.setAcceptDrops(True)
        self._items_container.installEventFilter(self)
        self._items_layout = QVBoxLayout(self._items_container)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(0)
        self._items_layout.addStretch()

        scroll.setWidget(self._items_container)
        list_layout.addWidget(scroll, stretch=1)

        # Add button footer
        add_bar = QWidget()
        add_bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        add_bar.setFixedHeight(36)
        al = QHBoxLayout(add_bar)
        al.setContentsMargins(8, 4, 8, 4)
        add_btn = QPushButton("[+] Adicionar Comando")
        add_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #FBBF24;"
            "  border: none; font-size: 12px; }"
            "QPushButton:hover { color: #FDE68A; }"
        )
        add_btn.clicked.connect(self.add_command_requested)
        al.addWidget(add_btn)

        save_btn = QPushButton("💾 Salvar")
        save_btn.setToolTip("Salvar fila no JSON do projeto (Ctrl+S)")
        save_btn.setFixedHeight(26)
        save_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 3px;"
            "  font-size: 11px; padding: 2px 8px; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; border-color: #FBBF24; }"
        )
        save_btn.clicked.connect(self.save_requested)
        al.addWidget(save_btn)

        list_layout.addWidget(add_bar)

        # "Próximo" button — shown only when an interactive command awaits advance
        next_bar = QWidget()
        next_bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        next_bar.setFixedHeight(40)
        nl = QHBoxLayout(next_bar)
        nl.setContentsMargins(8, 4, 8, 4)
        self._btn_next = QPushButton("Próximo →")
        self._btn_next.setFixedHeight(30)
        self._btn_next.setStyleSheet(
            "QPushButton { background-color: #16A34A; color: #FAFAF9;"
            "  border: none; border-radius: 4px; padding: 4px 16px;"
            "  font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._btn_next.setEnabled(False)
        self._btn_next.setVisible(False)
        nl.addWidget(self._btn_next, alignment=Qt.AlignmentFlag.AlignCenter)
        list_layout.addWidget(next_bar)
        self._next_bar = next_bar
        self._next_bar.setVisible(False)

        content_layout.addWidget(self._empty_widget)
        content_layout.addWidget(self._list_widget)
        self._list_widget.setVisible(False)

    def _connect_signals(self) -> None:
        signal_bus.pipeline_ready.connect(self.load_pipeline)
        signal_bus.command_started.connect(self._on_command_started)
        signal_bus.command_completed.connect(self._on_command_completed)
        signal_bus.command_failed.connect(self._on_command_failed)
        signal_bus.command_skipped.connect(self._on_command_skipped)
        signal_bus.pipeline_error_occurred.connect(self._on_pipeline_error_with_message)
        signal_bus.interactive_advance_ready.connect(self._on_interactive_advance_ready)
        signal_bus.autocast_command_done.connect(self._on_autocast_terminal_done)
        signal_bus.instance_selected.connect(self._on_instance_selected)
        self._btn_next.clicked.connect(self._on_btn_next_clicked)

    # ──────────────────────────────────── Section tabs (accordion) ─── #

    def _build_section_grid(
        self, buttons: list[tuple[str, str, object, str]], cols: int = 3
    ) -> QWidget:
        """Create a content widget with a 3-column grid of styled buttons."""
        content = QWidget()
        content.setStyleSheet("background-color: #27272A;")
        grid = QGridLayout(content)
        grid.setContentsMargins(5, 4, 5, 5)
        grid.setSpacing(3)
        for i, (label, tooltip, callback, testid) in enumerate(buttons):
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(_SECTION_BTN_STYLE)
            btn.clicked.connect(callback)
            grid.addWidget(btn, i // cols, i % cols)
        return content

    def _switch_section(self, index: int) -> None:
        """Switch to a section tab (accordion: only one open at a time)."""
        if index == self._active_section:
            return
        self._active_section = index
        self._apply_section_styles()

    def _apply_section_styles(self) -> None:
        """Update tab button styles and content visibility."""
        for i, (btn, content) in enumerate(zip(self._sec_tabs, self._sec_contents)):
            active = i == self._active_section
            btn.setStyleSheet(_TAB_ACTIVE_STYLE if active else _TAB_INACTIVE_STYLE)
            content.setVisible(active)

    # ──────────────────────────────────────────────────── Public API ─── #

    def set_pipeline_manager(self, pipeline_manager) -> None:
        """Inject the PipelineManager to enable can_reorder guards."""
        self._pipeline_manager = pipeline_manager

    def run_next_pending(self) -> None:
        """Find the first row not yet sent to terminal and trigger it."""
        for item in self._items:
            if item.is_pending_run():
                item._on_run_clicked()
                return

    def _on_copy_json_path(self) -> None:
        """Copia o caminho relativo do project.json para o clipboard."""
        import os

        from workflow_app.config.app_state import app_state

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit("Nenhum projeto carregado.", "warning")
            return

        abs_config = app_state.config.config_path
        project_dir = str(app_state.config.project_dir)
        try:
            rel = os.path.relpath(abs_config, project_dir)
        except ValueError:
            rel = abs_config
        QApplication.clipboard().setText(rel)
        signal_bus.paste_text_in_terminal.emit(rel)
        signal_bus.focus_interactive_terminal.emit()
        signal_bus.toast_requested.emit("Caminho JSON copiado e digitado no terminal.", "info")

    def _on_copy_ws_path(self) -> None:
        """Copia o workspace_root do projeto para o clipboard e digita no terminal."""
        from workflow_app.config.app_state import app_state

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit("Nenhum projeto carregado.", "warning")
            return

        ws = app_state.config.workspace_root
        QApplication.clipboard().setText(ws)
        signal_bus.paste_text_in_terminal.emit(ws)
        signal_bus.focus_interactive_terminal.emit()
        signal_bus.toast_requested.emit("workspace_root copiado e digitado no terminal.", "info")

    def _load_single_command(
        self,
        name: str,
        model: ModelName,
        interaction: InteractionType = InteractionType.INTERACTIVE,
    ) -> None:
        """Load a single command as a 1-item pipeline."""
        self._template_label.setText(f"  \U0001f4cb  {name}")
        self._template_label.setVisible(True)
        spec = CommandSpec(name=name, model=model, interaction_type=interaction, position=1)
        signal_bus.pipeline_ready.emit([spec])

    def _load_quick_template(self, template: list[CommandSpec], *, name: str = "") -> None:
        """Emit pipeline_ready with a fresh copy of a factory template.

        Inserts a '/model X' row before each command where the model changes,
        so the user only needs to switch models at transition points.
        The model rows carry no config_path.
        Skips /clear for model tracking — no /model haiku before /clear.
        """
        if name:
            self._template_label.setText(f"  \U0001f4cb  {name}")
            self._template_label.setVisible(True)

        raw = copy.deepcopy(template)

        expanded: list[CommandSpec] = []
        current_model = None
        for spec in raw:
            # Skip /clear for model tracking — it doesn't use a model
            if spec.name == "/clear":
                expanded.append(spec)
                continue  # Keep current_model — no /model needed if model didn't change
            if spec.model != current_model:
                model_spec = CommandSpec(
                    name=f"/model {spec.model.value.lower()}",
                    model=spec.model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",  # no json appended for model-switch rows
                    position=0,      # renumbered below
                )
                expanded.append(model_spec)
                current_model = spec.model
            expanded.append(spec)

        for i, spec in enumerate(expanded, start=1):
            spec.position = i

        signal_bus.pipeline_ready.emit(expanded)

    def _on_brief_clicked(self) -> None:
        """Open Brief modal with [New] and [Feature] options."""
        from workflow_app.dialogs.brief_template_dialog import BriefTemplateDialog

        dlg = BriefTemplateDialog(parent=self)
        if dlg.exec() == BriefTemplateDialog.Accepted:
            self._load_quick_template(dlg.selected_template)

    def _on_micro_json_clicked(self) -> None:
        """Show name dialog and patch project JSON for feature paths (micro-json config)."""
        from pathlib import Path

        from workflow_app.config.app_state import app_state
        from workflow_app.config.config_parser import parse_config
        from workflow_app.dialogs.micro_arch_name_dialog import MicroArchNameDialog

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um projeto antes de usar o Micro-JSON.", "warning"
            )
            return

        dlg = MicroArchNameDialog(parent=self)
        if dlg.exec() != MicroArchNameDialog.Accepted:
            return

        slug = dlg.slug
        config = app_state.config
        config_path = Path(config.config_path)

        # ── Read raw JSON ──────────────────────────────────────────────────
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            signal_bus.toast_requested.emit(f"Erro ao ler project.json: {exc}", "error")
            return

        # ── Derive base paths (strip /features/... if already set) ──────────
        base_brief = re.sub(r"/features(/.*)?$", "", config.brief_root)
        new_brief = f"{base_brief}/features/{slug}"
        base_docs = re.sub(r"/features(/.*)?$", "", config.docs_root)
        new_docs = f"{base_docs}/features/{slug}"
        base_wbs = re.sub(r"/features(/.*)?$", "", config.wbs_root)
        new_wbs = f"{base_wbs}/features/{slug}"

        # ── Patch paths based on JSON version ─────────────────────────────
        if "basic_flow" in raw:
            # V3
            raw["basic_flow"]["brief_root"] = new_brief
            raw["basic_flow"]["docs_root"] = new_docs
            raw["basic_flow"]["wbs_root"] = new_wbs
            pt = raw.get("project_type", {})
            if isinstance(pt, dict):
                if "new" in pt and isinstance(pt["new"], dict):
                    pt["new"]["enabled"] = False
                feature_entry = pt.get("feature", {})
                if isinstance(feature_entry, dict):
                    feature_entry["enabled"] = True
                    pt["feature"] = feature_entry
                else:
                    pt["feature"] = {"enabled": True}
                raw["project_type"] = pt
        elif "brief_root" in raw or "docs_root" in raw:
            # V2
            raw["brief_root"] = new_brief
            raw["docs_root"] = new_docs
            raw["wbs_root"] = new_wbs
            pt = raw.get("project_type", {})
            if isinstance(pt, dict):
                pt["new"] = False
                pt["feature"] = True
                raw["project_type"] = pt
            elif isinstance(pt, str):
                raw["project_type"] = "feature"
        else:
            # V1 — inject brief_root explicitly
            raw["brief_root"] = new_brief

        # ── Add feature entry to features list if present ─────────────────
        if "features" in raw and isinstance(raw["features"], list):
            existing = {f.get("slug") for f in raw["features"] if isinstance(f, dict)}
            if slug not in existing:
                raw["features"].append({
                    "slug": slug,
                    "name": slug.replace("-", " ").title(),
                })

        # ── Write back ────────────────────────────────────────────────────
        try:
            config_path.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            signal_bus.toast_requested.emit(f"Erro ao salvar project.json: {exc}", "error")
            return

        # ── Reload config in app_state ────────────────────────────────────
        try:
            new_config = parse_config(str(config_path))
            app_state.set_config(new_config)
            signal_bus.config_loaded.emit(str(config_path))
        except Exception as exc:
            signal_bus.toast_requested.emit(f"Erro ao recarregar config: {exc}", "error")
            return

        signal_bus.toast_requested.emit(
            f"Feature '{slug}' configurada. Paths: brief/docs/wbs → /features/{slug}", "success"
        )

    def _on_micro_arch_clicked(self) -> None:
        """Load micro-architecture template using current feature config."""
        from pathlib import Path

        from workflow_app.config.app_state import app_state
        from workflow_app.templates.quick_templates import _inject_clears

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um projeto antes de usar o Micro-Architecture.", "warning"
            )
            return

        config = app_state.config

        # Extract slug from wbs_root (expected: .../features/{slug})
        wbs_parts = config.wbs_root.rstrip("/").split("/")
        if len(wbs_parts) < 2 or wbs_parts[-2] != "features":
            signal_bus.toast_requested.emit(
                "Execute o Micro-JSON primeiro para configurar a feature.", "warning"
            )
            return

        slug = wbs_parts[-1]

        # ── Compute next sequential number for micro-architecture dir ────
        project_dir = Path(config.project_dir)
        micro_arch_base = project_dir / config.wbs_root / "micro-architecture"
        next_n = 1
        if micro_arch_base.is_dir():
            existing_nums: list[int] = []
            for child in micro_arch_base.iterdir():
                if child.is_dir():
                    match = re.match(r"^(\d+)-", child.name)
                    if match:
                        existing_nums.append(int(match.group(1)))
            if existing_nums:
                next_n = max(existing_nums) + 1

        micro_arch_path = f"{config.wbs_root}/micro-architecture/{next_n}-{slug}"

        # ── Build dynamic template ───────────────────────────────────────
        _O = ModelName.OPUS
        _S = ModelName.SONNET
        _I = InteractionType.INTERACTIVE
        _A = InteractionType.AUTO

        def _spec_local(
            name: str,
            model: ModelName,
            interaction: InteractionType,
            pos: int,
        ) -> CommandSpec:
            return CommandSpec(
                name=name,
                model=model,
                interaction_type=interaction,
                position=pos,
            )

        template = _inject_clears([
            _spec_local("/feature-brief-create",               _O, _I, 1),
            _spec_local("/intake:analyze",                     _S, _A, 2),
            _spec_local("/intake:enhance",                     _O, _I, 3),
            _spec_local("/micro-architecture",                 _S, _I, 4),
            _spec_local("/review-created-micro-architecture",  _O, _A, 5),
            _spec_local(f"/auto-flow execute {micro_arch_path}", _S, _A, 6),
            _spec_local(f"/review-executed-micro-architecture {micro_arch_path}", _O, _A, 7),
        ])

        signal_bus.toast_requested.emit(
            f"Micro-Architecture '{slug}': {next_n}-{slug}", "success"
        )
        self._load_quick_template(template, name="Micro-Architecture")

    def _on_wbs_clicked(self) -> None:
        """Build WBS template dynamically from existing modules."""
        from workflow_app.config.app_state import app_state
        from workflow_app.templates.quick_templates import _inject_clears
        from workflow_app.templates.wbs_template_builder import build_wbs_template

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um projeto antes de usar o WBS.", "warning"
            )
            return

        config = app_state.config
        template = build_wbs_template(
            wbs_root=config.wbs_root,
            project_dir=str(config.project_dir),
        )

        if not template:
            signal_bus.toast_requested.emit(
                "Nenhum module encontrado em modules/. Execute /auto-flow modules primeiro.",
                "warning",
            )
            return

        self._load_quick_template(_inject_clears(template), name="WBS")

    def _on_qa_clicked(self) -> None:
        """Open QA modal with stack options."""
        from workflow_app.dialogs.qa_stack_dialog import QAStackDialog

        dlg = QAStackDialog(parent=self)
        if dlg.exec() == QAStackDialog.Accepted:
            self._load_quick_template(dlg.selected_template, name="QA")

    def _on_run_command(self, cmd_text: str) -> None:
        """Update last-command label with the command that was just played."""
        parts = cmd_text.strip().split()
        self._last_cmd_label.setText("\n".join(parts))
        self._last_cmd_label.setVisible(True)

    def load_pipeline(self, specs: list[CommandSpec]) -> None:
        """Populate the queue with CommandSpec objects."""
        # Clear existing
        for item in self._items:
            item.deleteLater()
        self._items.clear()

        # Remove stretch before inserting
        self._items_layout.takeAt(self._items_layout.count() - 1)

        for spec in specs:
            item = self._make_item(spec)
            self._items_layout.addWidget(item)
            self._items.append(item)

        # Re-add stretch at end
        self._items_layout.addStretch()

        self._empty_widget.setVisible(False)
        self._list_widget.setVisible(True)

    def load_commands(self, commands: list[CommandSpec]) -> None:
        """Alias for load_pipeline() — called via signal pipeline_created."""
        self.load_pipeline(commands)

    def add_command(self, spec: CommandSpec) -> None:
        """Append a single CommandSpec to the existing queue.  # RESOLVED: G001"""
        # Remove stretch before inserting
        stretch_item = self._items_layout.takeAt(self._items_layout.count() - 1)

        item = self._make_item(spec)
        self._items_layout.addWidget(item)
        self._items.append(item)

        # Re-add stretch at end
        if stretch_item:
            self._items_layout.addStretch()

        self._empty_widget.setVisible(False)
        self._list_widget.setVisible(True)

    def clear_queue(self) -> None:
        for item in self._items:
            item.deleteLater()
        self._items.clear()
        self._template_label.setVisible(False)
        self._last_cmd_label.setVisible(False)
        self._empty_widget.setVisible(True)
        self._list_widget.setVisible(False)

    def _item_at(self, position: int) -> CommandItemWidget | None:
        for item in self._items:
            if item.get_spec().position == position:
                return item
        return None

    def _make_item(self, spec: CommandSpec) -> CommandItemWidget:
        """Create a CommandItemWidget with can_reorder_fn injected."""
        item = CommandItemWidget(spec, can_reorder_fn=self._can_reorder, parent=self._items_container)
        item.remove_requested.connect(self._on_remove_requested)
        item.skip_requested.connect(self._on_skip_requested)
        item.retry_requested.connect(self._on_retry_requested)
        item.cancel_requested.connect(self._on_cancel_requested)
        item.run_in_terminal_requested.connect(signal_bus.run_command_in_terminal)
        item.run_in_terminal_requested.connect(self._on_run_command)
        return item

    # ──────────────────────────────────────── Queue state persistence ─ #

    def get_queue_state(self) -> list[dict]:
        """Return serializable snapshot of the current queue (commands + statuses)."""
        result = []
        for item in self._items:
            spec = item.get_spec()
            result.append({
                "name": spec.name,
                "model": spec.model.value,
                "interaction_type": spec.interaction_type.value,
                "position": spec.position,
                "is_optional": spec.is_optional,
                "config_path": spec.config_path,
                "phase": spec.phase,
                "status": item._status.value,
                "sent": not item.is_pending_run(),
            })
        return result

    def restore_queue_state(self, state: list[dict]) -> None:
        """Restore queue from a saved state list, preserving statuses and sent flags."""
        from workflow_app.domain import CommandStatus, InteractionType, ModelName

        specs = []
        statuses: list[CommandStatus] = []
        sent_flags: list[bool] = []

        for entry in state:
            try:
                model = ModelName(entry.get("model", "Sonnet"))
            except ValueError:
                model = ModelName.SONNET
            try:
                interaction = InteractionType(entry.get("interaction_type", "auto"))
            except ValueError:
                interaction = InteractionType.AUTO

            spec = CommandSpec(
                name=entry["name"],
                model=model,
                interaction_type=interaction,
                position=entry.get("position", 0),
                is_optional=entry.get("is_optional", False),
                config_path=entry.get("config_path", ""),
                phase=entry.get("phase", "F?"),
            )
            specs.append(spec)

            try:
                status = CommandStatus(entry.get("status", "pendente"))
            except ValueError:
                status = CommandStatus.PENDENTE
            statuses.append(status)
            sent_flags.append(entry.get("sent", False))

        self.load_pipeline(specs)

        for item, status, sent in zip(self._items, statuses, sent_flags):
            if status != CommandStatus.PENDENTE:
                item.set_status(status)
            if sent:
                item._mark_as_sent()

    # ─────────────────────────────────────── Drag-and-drop: drop target ─ #

    def _can_reorder(self, position: int) -> bool:
        """Delegate to PipelineManager.can_reorder (converts 1-based → 0-based)."""
        if self._pipeline_manager is not None:
            return self._pipeline_manager.can_reorder(position - 1)
        return True

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._items_container:
            if event.type() == QEvent.Type.DragEnter:
                if event.mimeData().hasText():
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.DragMove:
                if event.mimeData().hasText():
                    self._update_drop_indicator(event.position().toPoint())
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.DragLeave:
                self._items_container.set_drop_indicator(None)
                return True
            elif event.type() == QEvent.Type.Drop:
                self._on_drop(event)
                return True
        return super().eventFilter(obj, event)

    def _update_drop_indicator(self, pos: QPoint) -> None:
        """Calculate drop index based on Y cursor position and update the visual indicator."""
        layout = self._items_layout
        count = layout.count()
        for i in range(count):
            layout_item = layout.itemAt(i)
            if layout_item and layout_item.widget():
                widget_rect = layout_item.widget().geometry()
                if pos.y() < widget_rect.center().y():
                    self._items_container.set_drop_indicator(i)
                    return
        self._items_container.set_drop_indicator(count)

    def _on_drop(self, event) -> None:
        """Process drop: emit reorder_requested if positions differ."""
        try:
            from_pos = int(event.mimeData().text())
        except (ValueError, AttributeError):
            return
        to_pos = self._items_container._drop_indicator_pos
        self._items_container.set_drop_indicator(None)
        if to_pos is None or from_pos == to_pos:
            event.ignore()
            return
        event.acceptProposedAction()
        self.reorder_requested.emit(from_pos, to_pos)

    # ─────────────────────────────────────────────────────── Slots ───── #

    def _on_command_started(self, index: int) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.EXECUTANDO)

    def _on_command_completed(self, index: int) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.CONCLUIDO)

    def _on_command_failed(self, index: int, _msg: str) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.ERRO)
        # Stop autocast/loop on failure
        if self._loop_active:
            self._stop_loop()
            signal_bus.toast_requested.emit("Loop: parado por erro", "warning")
        elif self._autocast_active:
            self._stop_autocast()
            signal_bus.toast_requested.emit("Autocast: parado por erro", "warning")

    def _on_command_skipped(self, index: int) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.PULADO)

    def _on_remove_requested(self, position: int) -> None:
        item = self._item_at(position)
        if item:
            self._items_layout.removeWidget(item)
            item.deleteLater()
            self._items = [i for i in self._items if i.get_spec().position != position]
            if not self._items:
                self._empty_widget.setVisible(True)
                self._list_widget.setVisible(False)

    def _on_skip_requested(self, position: int) -> None:
        item = self._item_at(position)
        if item:
            item.set_status(CommandStatus.PULADO)
            signal_bus.command_skipped.emit(position - 1)

    def _on_retry_requested(self, position: int) -> None:
        """Reset the failed item to PENDENTE and request pipeline retry."""
        item = self._item_at(position)
        if item:
            item.set_status(CommandStatus.PENDENTE)
        signal_bus.pipeline_retry_requested.emit(position - 1)

    def _on_cancel_requested(self) -> None:
        """Show confirmation dialog before cancelling the pipeline."""
        modal = ConfirmCancelModal(parent=self)
        if modal.exec() == ConfirmCancelModal.Accepted:
            signal_bus.pipeline_cancelled.emit()

    def _on_pipeline_error_with_message(self, _pipeline_id: int, message: str) -> None:
        """Mark the currently-executing item as failed with the error message."""
        for item in self._items:
            if item._status == CommandStatus.EXECUTANDO:
                item.set_status(CommandStatus.ERRO, error_message=message)
                break

    def _on_interactive_advance_ready(self, _command_exec_id: int) -> None:
        """Show and enable the 'Próximo' button when an interactive command awaits."""
        command_name = "Próximo"
        for item in self._items:
            if item._status == CommandStatus.EXECUTANDO:
                command_name = item.get_spec().name
                break
        self._next_bar.setVisible(True)
        self._btn_next.setVisible(True)
        self._btn_next.setEnabled(True)
        self._btn_next.setText(f"Continuar: {command_name}")

    def _on_btn_next_clicked(self) -> None:
        """Disable the button and ask PipelineManager to advance."""
        self._btn_next.setEnabled(False)
        self._next_bar.setVisible(False)
        self._btn_next.setVisible(False)
        self._btn_next.setText("Próximo →")
        signal_bus.interactive_advance_triggered.emit()

    def _on_notepad_send(self) -> None:
        """Send notepad text to terminal (no Enter, no clear), then focus terminal."""
        text = self._notepad_edit.toPlainText()
        if text:
            signal_bus.paste_text_in_terminal.emit(text)
            signal_bus.focus_interactive_terminal.emit()

    # ─────────────────────────────────────────────── Autocast ──────── #

    def _on_instance_selected(self, name: str) -> None:
        """Track the active CLI binary for autocast command building."""
        self._cli_binary = name

    def _on_autocast_terminal_done(self) -> None:
        """Called when ##SF_DONE## sentinel is detected in terminal output."""
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info("[Autocast] _on_autocast_terminal_done called. active=%s, pending=%s",
                     self._autocast_active, self._autocast_pending_advance)
        if self._autocast_active and not self._autocast_pending_advance:
            self._autocast_pending_advance = True
            from PySide6.QtCore import QTimer
            _logger.info("[Autocast] Scheduling _autocast_advance in 300ms")
            QTimer.singleShot(300, self._autocast_advance)
        else:
            _logger.info("[Autocast] SKIPPED advance (active=%s, pending=%s)",
                         self._autocast_active, self._autocast_pending_advance)

    def _on_autocast_clicked(self) -> None:
        """Toggle autocast mode on/off."""
        if self._autocast_active:
            self._stop_autocast()
        else:
            self._start_autocast()

    def _on_loop_clicked(self) -> None:
        """Toggle loop mode on/off."""
        if self._loop_active:
            self._stop_loop()
        else:
            self._start_loop()

    def _start_loop(self) -> None:
        """Activate loop mode and start autocast."""
        self._loop_active = True
        self._loop_btn.setText("Parar")
        self._loop_btn.setStyleSheet(
            "QPushButton { background-color: #DC2626; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { background-color: #B91C1C; }"
            "QPushButton:pressed { background-color: #991B1B; }"
        )
        signal_bus.toast_requested.emit("Loop ativado", "info")
        # Start autocast if not already running
        if not self._autocast_active:
            self._start_autocast()

    def _stop_loop(self) -> None:
        """Deactivate loop mode and stop autocast."""
        self._loop_active = False
        self._loop_btn.setText("Loop")
        self._loop_btn.setStyleSheet(
            "QPushButton { background-color: #0891B2; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { background-color: #0E7490; }"
            "QPushButton:pressed { background-color: #155E75; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        if self._autocast_active:
            self._stop_autocast()

    def _reset_all_items_to_pending(self) -> None:
        """Reset all items in the queue back to pending state for loop restart."""
        for item in self._items:
            item.reset_to_pending()

    def _start_autocast(self) -> None:
        """Activate autocast and trigger the first pending command."""
        import logging as _log
        _log.getLogger(__name__).info("[Autocast] _start_autocast called")
        self._autocast_active = True
        self._autocast_btn.setText("Parar")
        self._autocast_btn.setStyleSheet(
            "QPushButton { background-color: #DC2626; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { background-color: #B91C1C; }"
            "QPushButton:pressed { background-color: #991B1B; }"
        )
        signal_bus.toast_requested.emit("Autocast ativado", "info")
        # Use _autocast_advance instead of run_next_pending so /model and /clear
        # are handled with timed auto-advance from the very first command.
        self._autocast_advance()

    def _stop_autocast(self) -> None:
        """Deactivate autocast and restore button label."""
        import logging as _log
        import traceback
        _log.getLogger(__name__).info("[Autocast] _stop_autocast called from:\n%s", "".join(traceback.format_stack()[-4:-1]))
        self._autocast_active = False
        self._autocast_pending_advance = False
        self._autocast_btn.setText("Autocast")
        self._autocast_btn.setStyleSheet(
            "QPushButton { background-color: #7C3AED; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { background-color: #6D28D9; }"
            "QPushButton:pressed { background-color: #5B21B6; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )

    @staticmethod
    def _same_context_group(name_a: str, name_b: str) -> bool:
        """True if two commands belong to the same context group.

        Groups are sub-pipelines where each step benefits from shared
        conversation context (avoids re-reading the same files):
          - /qa:prep → /qa:trace → /qa:report
          - /backend:scan → /backend:audit → /backend:test-check → /backend:report
          - /frontend:scan → /frontend:audit → /frontend:assets-check → /frontend:report
          - /deep-research-1 → /deep-research-2
          - /c4-diagram-create → /mermaid-diagram-create
          - /daily:* (all daily steps share context)
        """
        a, b = name_a.lower(), name_b.lower()
        for prefix in ("/qa:", "/backend:", "/frontend:", "/daily:"):
            if a.startswith(prefix) and b.startswith(prefix):
                return True
        if a.startswith("/deep-research") and b.startswith("/deep-research"):
            return True
        if "diagram-create" in a and "diagram-create" in b:
            return True
        return False

    def _collect_context_group(self, start_item) -> list:
        """Collect consecutive AUTO items in the same context group.

        Starts from *start_item* and walks forward through pending items,
        skipping /model and /clear rows, collecting AUTO commands that
        belong to the same context group. Stops at the first INTERACTIVE
        command or a command outside the group.

        Returns a list of (item, spec) tuples.
        """
        group = [(start_item, start_item.get_spec())]
        start_name = start_item.get_spec().name.strip()

        # Walk remaining pending items after start_item
        found_start = False
        for item in self._items:
            if item is start_item:
                found_start = True
                continue
            if not found_start or not item.is_pending_run():
                continue

            spec = item.get_spec()
            name_lower = spec.name.strip().lower()

            # Skip /model and /clear — they're no-ops between group members
            if name_lower.startswith("/model") or name_lower == "/clear":
                group.append((item, spec))
                continue

            # Stop if INTERACTIVE or outside group
            if spec.interaction_type == InteractionType.INTERACTIVE:
                break
            if not self._same_context_group(start_name, spec.name.strip()):
                break

            group.append((item, spec))
        return group

    def _autocast_advance(self) -> None:
        """Called after a command completes while autocast is active.

        Handles three execution modes:
        - /model, /clear: skip (no-op, 300ms delay).
        - INTERACTIVE: run in terminal, stop autocast.
        - AUTO isolated: run via ``-p`` with sentinel.
        - AUTO context group: chain consecutive group members with ``&&``
          in a single ``-p`` call so they share conversation context.
        """
        import logging as _log
        _logger = _log.getLogger(__name__)

        if not self._autocast_active:
            _logger.info("[Autocast] _autocast_advance: NOT active, returning")
            return

        self._autocast_pending_advance = False  # Reset guard

        from PySide6.QtCore import QTimer

        next_item = self._find_next_pending()
        if next_item is None:
            if self._loop_active:
                _logger.info("[Autocast] _autocast_advance: loop restart — resetting all items")
                signal_bus.toast_requested.emit("Loop: reiniciando fila", "info")
                self._reset_all_items_to_pending()
                QTimer.singleShot(500, self._autocast_advance)
                return
            _logger.info("[Autocast] _autocast_advance: no more pending items")
            self._stop_autocast()
            signal_bus.toast_requested.emit("Autocast: fila concluída", "success")
            return

        spec = next_item.get_spec()
        name_lower = spec.name.strip().lower()
        cli = self._cli_binary
        _logger.info("[Autocast] _autocast_advance: next=%s interaction=%s model=%s",
                     spec.name, spec.interaction_type, spec.model)

        model_map = {"Opus": "opus", "Sonnet": "sonnet", "Haiku": "haiku"}

        def _build_p_cmd(s) -> str:
            """Build ``cli -p "prompt" --model X`` string."""
            prompt_parts = [s.name]
            if s.config_path:
                prompt_parts.append(s.config_path)
            prompt = " ".join(prompt_parts)
            escaped = prompt.replace('"', '\\"')
            model_flag = model_map.get(s.model.value, "sonnet")
            return f'{cli} -p "{escaped}" --model {model_flag}'

        def _build_interactive_cmd(s) -> str:
            """Build ``cli /cmd config --model X`` string (no -p)."""
            parts = [cli, s.name]
            if s.config_path:
                parts.append(s.config_path)
            model_flag = model_map.get(s.model.value, "sonnet")
            parts.extend(["--model", model_flag])
            return " ".join(parts)

        # /model and /clear are CLI built-ins — no-ops in autocast.
        if name_lower.startswith("/model") or name_lower == "/clear":
            next_item._mark_as_sent()
            QTimer.singleShot(300, self._autocast_advance)
            return

        is_interactive = spec.interaction_type == InteractionType.INTERACTIVE

        # Sentinel: use a subshell wrapper that traps EXIT to guarantee
        # the sentinel is always emitted, even if the command is killed.
        _SENTINEL_WRAPPER = (
            '(trap \'printf "\\043\\043SF_DONE\\043\\043\\n"\' EXIT; {cmd})'
        )

        if is_interactive:
            # Run interactive command in the interactive terminal (no -p)
            # with sentinel so autocast resumes automatically when it finishes.
            signal_bus.toast_requested.emit(
                f"Autocast: aguardando {spec.name} (interativo)", "info"
            )
            cmd = _build_interactive_cmd(spec)
            wrapped = _SENTINEL_WRAPPER.format(cmd=cmd)
            _logger.info("[Autocast] Sending INTERACTIVE to terminal: %s", wrapped)
            signal_bus.run_command_in_terminal.emit(wrapped)
            next_item._mark_as_sent()
            # Do NOT stop autocast — sentinel will trigger _autocast_advance
        else:
            # Check if this command starts a context group
            group = self._collect_context_group(next_item)
            # Filter out /model and /clear from the group for command building
            real_cmds = [(item, s) for item, s in group
                         if not s.name.strip().lower().startswith("/model")
                         and s.name.strip().lower() != "/clear"]

            if len(real_cmds) > 1:
                # Context group: chain with && in a single terminal command.
                cmd_parts = [_build_p_cmd(s) for _, s in real_cmds]
                chained = " && ".join(cmd_parts)
                names = [s.name for _, s in real_cmds]
                _logger.info("[Autocast] Context group (%d cmds): %s", len(real_cmds), names)
            else:
                chained = _build_p_cmd(spec)

            wrapped = _SENTINEL_WRAPPER.format(cmd=chained)
            _logger.info("[Autocast] Sending to autocast terminal: %s", wrapped)
            signal_bus.run_autocast_in_terminal.emit(wrapped)

            # Mark all items in the group as sent
            for item, _ in group:
                item._mark_as_sent()

    def _find_next_pending(self) -> CommandItemWidget | None:
        """Find the first item not yet sent to terminal."""
        for item in self._items:
            if item.is_pending_run():
                return item
        return None

    def _start_autocast_worker(self, spec) -> None:
        """Spawn an AutocastWorker subprocess for an AUTO command."""
        import pathlib

        from workflow_app.command_queue.autocast_worker import AutocastWorker

        # Resolve systemForge root as cwd (where .claude/commands live)
        cwd: str | None = None
        candidate = pathlib.Path(__file__).resolve().parent
        while candidate != candidate.parent:
            if (
                (candidate / ".claude" / "commands").is_dir()
                and (candidate / "CLAUDE.md").is_file()
            ):
                cwd = str(candidate)
                break
            candidate = candidate.parent

        worker = AutocastWorker(
            binary=self._cli_binary,
            command=spec.name,
            config_path=spec.config_path,
            cwd=cwd,
        )
        worker.output_chunk.connect(signal_bus.output_appended.emit)
        worker.finished.connect(self._on_autocast_worker_finished)
        # Clean up finished workers from the list
        worker.finished.connect(lambda _ok, w=worker: self._autocast_workers.remove(w))
        self._autocast_workers.append(worker)
        worker.start()

    def _on_autocast_worker_finished(self, success: bool) -> None:
        """Called when AutocastWorker subprocess exits."""
        if not success:
            signal_bus.toast_requested.emit("Autocast: comando retornou erro", "warning")
        if self._autocast_active and not self._autocast_pending_advance:
            self._autocast_pending_advance = True
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, self._autocast_advance)
