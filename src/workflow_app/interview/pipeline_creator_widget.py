"""
PipelineCreatorWidget — 3-page dialog for creating a command pipeline.

Pages (QStackedWidget):
  PAGE_CHOICE (0)   — Choose creation method (Interview or Template)
  PAGE_INTERVIEW (1) — Multi-question interview via InterviewEngine
  PAGE_REVIEW (2)   — Review & confirm command list (drag-and-drop)

Signals:
  pipeline_ready(list[CommandSpec])          — User confirmed the queue
  save_as_template_requested(list[CommandSpec]) — User clicked "Salvar como Template"

Min size: 580×520px
Header height: 56px (#27272A, border-bottom #3F3F46)
Footer height: 56px (#27272A, border-top #3F3F46)
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from workflow_app.domain import CommandSpec, InteractionType
from workflow_app.widgets.model_badge import ModelBadge
from workflow_app.widgets.notification_banner import NotificationBanner

PAGE_CHOICE = 0
PAGE_INTERVIEW = 1
PAGE_REVIEW = 2


class _ClickableCard(QWidget):
    """QWidget subclass with a proper clicked signal (PySide6-safe)."""

    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PipelineCreatorWidget(QDialog):
    """Dialog for creating a new command pipeline via interview or template."""

    pipeline_ready = Signal(list)                   # list[CommandSpec]
    save_as_template_requested = Signal(list)        # list[CommandSpec]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Criar Nova Fila de Comandos")
        self.setMinimumSize(580, 520)
        self.setModal(True)
        self.setStyleSheet("background-color: #18181B;")

        self._generated_commands: list[CommandSpec] = []
        self._removed_names: set[str] = set()

        # Interview state (populated in _go_to_interview)
        self._interview_questions: list = []
        self._current_question_index: int = 0
        self._interview_answers: dict = {}
        self._current_answer_group: QButtonGroup | None = None
        self._current_check_boxes: list[QCheckBox] = []

        self._setup_ui()
        self._update_footer(PAGE_CHOICE)

    # ──────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────── #
        header = QWidget()
        header.setObjectName("DialogHeader")
        header.setFixedHeight(56)
        header.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        self._title_label = QLabel("Criar Nova Fila de Comandos")
        self._title_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #FAFAFA;")
        hl.addWidget(self._title_label)
        hl.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; color: #A1A1AA; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FAFAFA; }"
        )
        close_btn.clicked.connect(self.reject)
        hl.addWidget(close_btn)
        root.addWidget(header)

        # ── Stacked pages ─────────────────────────────────────────────── #
        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._build_choice_page())    # 0
        self._stack.addWidget(self._build_interview_page()) # 1
        self._stack.addWidget(self._build_review_page())    # 2

        # ── Footer ────────────────────────────────────────────────────── #
        footer = QWidget()
        footer.setObjectName("DialogFooter")
        footer.setFixedHeight(56)
        footer.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 0, 24, 0)
        fl.setSpacing(8)

        self._back_btn = QPushButton("← Voltar")
        self._back_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: none; border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        self._back_btn.clicked.connect(self._go_back)
        fl.addWidget(self._back_btn)

        fl.addStretch()

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: none; border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        self._cancel_btn.clicked.connect(self.reject)
        fl.addWidget(self._cancel_btn)

        self._save_template_btn = QPushButton("Salvar como Template")
        self._save_template_btn.setStyleSheet(
            "QPushButton { background-color: #27272A; color: #FAFAFA;"
            "  border: 1px solid #3F3F46; border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #3F3F46; }"
        )
        self._save_template_btn.clicked.connect(self._on_save_template)
        fl.addWidget(self._save_template_btn)

        self._confirm_btn = QPushButton("Confirmar Fila ✓")
        self._confirm_btn.setObjectName("PrimaryButton")
        self._confirm_btn.setStyleSheet(
            "QPushButton { background-color: #FBBF24; color: #18181B;"
            "  font-weight: 700; border: none; border-radius: 6px; padding: 8px 20px; }"
            "QPushButton:hover { background-color: #FDE68A; }"
            "QPushButton:disabled { background-color: #78350F; color: #92400E; }"
        )
        self._confirm_btn.setToolTip("Adicione ao menos um comando")
        self._confirm_btn.clicked.connect(self._on_confirm)
        fl.addWidget(self._confirm_btn)

        root.addWidget(footer)
        self._stack.setCurrentIndex(PAGE_CHOICE)

    # ── Page builders ───────────────────────────────────────────────── #

    def _build_choice_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background-color: #18181B;")
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(24)
        layout.setContentsMargins(40, 40, 40, 40)

        title = QLabel("Como deseja criar a fila de comandos?")
        title.setStyleSheet("color: #FAFAFA; font-size: 15px; font-weight: 600;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        cards_row = QWidget()
        cl = QHBoxLayout(cards_row)
        cl.setSpacing(16)

        interview_card = self._build_choice_card(
            icon="🎯",
            title="Entrevista Guiada",
            description="Responda perguntas sobre o projeto e receba a fila ideal automaticamente.",
        )
        interview_card.clicked.connect(self._go_to_interview)

        template_card = self._build_choice_card(
            icon="📋",
            title="Usar Template",
            description="Escolha um dos 4 templates pré-definidos ou um template salvo.",
        )
        template_card.clicked.connect(self._go_to_template)

        cl.addWidget(interview_card)
        cl.addWidget(template_card)
        layout.addWidget(cards_row)

        return page

    def _build_choice_card(self, icon: str, title: str, description: str) -> _ClickableCard:
        card = _ClickableCard()
        card.setObjectName("ChoiceCard")
        card.setFixedSize(200, 180)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet(
            "QWidget#ChoiceCard { background-color: #27272A; border: 2px solid #3F3F46;"
            "  border-radius: 12px; padding: 16px; }"
            "QWidget#ChoiceCard:hover { border-color: #FBBF24; }"
        )
        cl = QVBoxLayout(card)
        cl.setAlignment(Qt.AlignmentFlag.AlignTop)
        cl.setSpacing(8)

        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 32px; background: transparent;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            "color: #FAFAFA; font-size: 15px; font-weight: 700; background: transparent;"
        )
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setStyleSheet("color: #A1A1AA; font-size: 13px; background: transparent;")
        desc_label.setWordWrap(True)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(desc_label)

        return card

    def _build_interview_page(self) -> QWidget:
        """Page 1: Multi-question interview wired to InterviewEngine."""
        page = QWidget()
        page.setStyleSheet("background-color: #18181B;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(16)

        # Error banner (hidden by default)
        self._error_banner = NotificationBanner(page)
        layout.addWidget(self._error_banner)

        # Question text (updated per question)
        self._question_label = QLabel()
        self._question_label.setStyleSheet(
            "color: #FAFAFA; font-size: 14px; font-weight: 600;"
        )
        self._question_label.setWordWrap(True)
        layout.addWidget(self._question_label)

        # Options container (cleared and rebuilt per question)
        self._options_container = QWidget()
        self._options_container.setStyleSheet(
            "background-color: #27272A; border: 1px solid #3F3F46;"
            " border-radius: 6px; padding: 12px;"
        )
        self._options_layout = QVBoxLayout(self._options_container)
        self._options_layout.setSpacing(8)
        layout.addWidget(self._options_container)

        # Hint label (shown only when question has a hint)
        self._hint_label = QLabel()
        self._hint_label.setStyleSheet(
            "color: #71717A; font-size: 12px; font-style: italic;"
        )
        self._hint_label.setWordWrap(True)
        self._hint_label.setVisible(False)
        layout.addWidget(self._hint_label)

        layout.addStretch()

        # Progress row
        progress_row = QWidget()
        pl = QHBoxLayout(progress_row)
        pl.setContentsMargins(0, 0, 0, 0)
        self._progress_label = QLabel("Pergunta 1 de 1")
        self._progress_label.setStyleSheet("color: #A1A1AA; font-size: 12px;")
        pl.addWidget(self._progress_label)
        pl.addStretch()
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedSize(120, 8)
        self._progress_bar.setTextVisible(False)
        pl.addWidget(self._progress_bar)
        self._progress_pct = QLabel("0%")
        self._progress_pct.setStyleSheet("color: #A1A1AA; font-size: 12px;")
        pl.addWidget(self._progress_pct)
        layout.addWidget(progress_row)

        # Next / Finish button
        self._next_btn = QPushButton("Próximo →")
        self._next_btn.setStyleSheet(
            "QPushButton { background-color: #FBBF24; color: #18181B;"
            "  font-weight: 700; border: none; border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #FDE68A; }"
        )
        self._next_btn.clicked.connect(self._on_interview_next)
        layout.addWidget(self._next_btn, alignment=Qt.AlignmentFlag.AlignRight)

        return page

    def _build_review_page(self) -> QWidget:
        """Page 2: Review & confirm command list with drag-and-drop reordering."""
        page = QWidget()
        page.setStyleSheet("background-color: #18181B;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(12)

        # Header info
        header_row = QWidget()
        hl = QVBoxLayout(header_row)
        hl.setSpacing(2)
        title = QLabel("Revise os comandos da fila")
        title.setStyleSheet("color: #FAFAFA; font-size: 15px; font-weight: 600;")
        hl.addWidget(title)
        self._counter_label = QLabel("0 comandos na fila")
        self._counter_label.setStyleSheet(
            "color: #FBBF24; font-size: 13px; font-weight: 600;"
        )
        hl.addWidget(self._counter_label)
        hint = QLabel(
            "Arraste para reordenar. Clique com botão direito para mais opções."
        )
        hint.setStyleSheet("color: #71717A; font-size: 12px; font-style: italic;")
        hl.addWidget(hint)
        layout.addWidget(header_row)

        # Toolbar: "Adicionar Comando" button
        toolbar = QWidget()
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addStretch()
        self._add_btn = QPushButton("+ Adicionar Comando")
        self._add_btn.setStyleSheet(
            "QPushButton { background-color: #27272A; color: #FAFAFA;"
            "  border: 1px solid #3F3F46; border-radius: 4px;"
            "  padding: 6px 12px; font-size: 13px; }"
            "QPushButton:hover { background-color: #3F3F46; }"
        )
        self._add_btn.clicked.connect(self._on_add_command)
        tl.addWidget(self._add_btn)
        layout.addWidget(toolbar)

        # QListWidget with drag-and-drop reordering (ST002)
        self._review_list = QListWidget()
        self._review_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._review_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._review_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._review_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._review_list.customContextMenuRequested.connect(self._show_context_menu)
        self._review_list.setStyleSheet(
            "QListWidget { background-color: #18181B;"
            "  border: 1px solid #3F3F46; border-radius: 8px; }"
            "QListWidget::item { background-color: #18181B;"
            "  border-bottom: 1px solid #3F3F46; padding: 0px; }"
            "QListWidget::item:selected { background-color: #27272A; }"
            "QListWidget::item:hover { background-color: #27272A; }"
        )
        layout.addWidget(self._review_list, stretch=1)

        return page

    # ──────────────────────────────────────────────────── Navigation ─── #

    def _go_to_interview(self) -> None:
        from workflow_app.interview.interview_engine import InterviewEngine
        engine = InterviewEngine()
        self._interview_questions = engine.start_interview()
        self._interview_answers = {}
        self._current_question_index = 0
        self._render_question(0)
        self._stack.setCurrentIndex(PAGE_INTERVIEW)
        self._update_footer(PAGE_INTERVIEW)

    def _go_to_template(self) -> None:
        # RESOLVED: opens TemplatePickerDialog for template selection
        from workflow_app.dialogs.template_picker_dialog import TemplatePickerDialog

        dlg = TemplatePickerDialog(parent=self)
        if dlg.exec() == TemplatePickerDialog.DialogCode.Accepted and dlg.commands:
            self._load_review_page(dlg.commands)

    def _go_back(self) -> None:
        current = self._stack.currentIndex()
        if current in (PAGE_INTERVIEW, PAGE_REVIEW):
            self._stack.setCurrentIndex(PAGE_CHOICE)
            self._update_footer(PAGE_CHOICE)

    def _load_review_page(self, commands: list[CommandSpec]) -> None:
        self._generated_commands = list(commands)
        self._removed_names.clear()
        self._populate_review_list(commands)
        self._stack.setCurrentIndex(PAGE_REVIEW)
        self._update_footer(PAGE_REVIEW)

    def _update_footer(self, page: int) -> None:
        self._back_btn.setVisible(page != PAGE_CHOICE)
        self._save_template_btn.setVisible(page == PAGE_REVIEW)
        self._confirm_btn.setVisible(page == PAGE_REVIEW)

        if page == PAGE_REVIEW:
            count = self._review_list.count()
            self._confirm_btn.setEnabled(count > 0)

    def _populate_review_list(self, commands: list[CommandSpec]) -> None:
        self._review_list.clear()
        for spec in commands:
            self._add_list_item(spec)
        self._update_counter()

    def _add_list_item(self, spec: CommandSpec) -> QListWidgetItem:
        """Add a CommandSpec as a styled QListWidgetItem."""
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, spec)
        item.setSizeHint(QSize(0, 44))
        self._review_list.addItem(item)
        self._review_list.setItemWidget(item, self._build_item_widget(spec))
        return item

    def _build_item_widget(self, spec: CommandSpec) -> QWidget:
        """Build the display widget for a single CommandSpec row."""
        row = QWidget()
        row.setStyleSheet("background-color: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Drag handle indicator
        handle = QLabel("⠿")
        handle.setStyleSheet("color: #52525B; font-size: 16px;")
        handle.setFixedWidth(20)
        layout.addWidget(handle)

        # Command name
        name_lbl = QLabel(spec.name)
        name_lbl.setStyleSheet(
            "color: #FAFAFA; font-family: monospace; font-size: 13px;"
        )
        layout.addWidget(name_lbl, stretch=1)

        # Model badge
        model_badge = ModelBadge(spec.model, short=False, parent=row)
        layout.addWidget(model_badge)

        # Interaction type badge
        inter_text = "→ auto" if spec.interaction_type == InteractionType.AUTO else "↔ inter"
        inter_style = (
            "background-color: #1E3A5F; color: #93C5FD;"
            if spec.interaction_type == InteractionType.AUTO
            else "background-color: #92400E; color: #FDE68A;"
        )
        inter_badge = QLabel(inter_text)
        inter_badge.setStyleSheet(
            f"{inter_style} border-radius: 4px; padding: 2px 6px; font-size: 11px;"
        )
        layout.addWidget(inter_badge)

        return row

    def _update_counter(self) -> None:
        count = self._review_list.count()
        self._counter_label.setText(f"{count} comando{'s' if count != 1 else ''} na fila")
        self._confirm_btn.setEnabled(count > 0)

    # ─────────────────────────────── Interview helpers ─────────────────── #

    def _is_question_visible(self, idx: int) -> bool:
        """Return True if question at idx should be shown given current answers."""
        q = self._interview_questions[idx]
        if not q.depends_on:
            return True
        for field, required_value in q.depends_on.items():
            if self._interview_answers.get(field) != required_value:
                return False
        return True

    def _get_visible_question_indices(self) -> list[int]:
        """Return ordered list of question indices visible given current answers."""
        return [
            i for i in range(len(self._interview_questions))
            if self._is_question_visible(i)
        ]

    def _render_question(self, idx: int) -> None:
        """Render the question at index idx into the interview page."""
        self._current_question_index = idx
        q = self._interview_questions[idx]

        # Update question text
        self._question_label.setText(q.question)

        # Update hint
        if q.hint:
            self._hint_label.setText(q.hint)
            self._hint_label.setVisible(True)
        else:
            self._hint_label.setVisible(False)

        # Clear options layout
        while self._options_layout.count():
            child = self._options_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        radio_style = (
            "QRadioButton { color: #FAFAFA; font-size: 13px; background: transparent; }"
            "QRadioButton::indicator { width: 14px; height: 14px; }"
            "QRadioButton::indicator:checked { background-color: #FBBF24;"
            "  border: 2px solid #FBBF24; border-radius: 7px; }"
            "QRadioButton::indicator:unchecked { border: 2px solid #71717A;"
            "  border-radius: 7px; background-color: transparent; }"
        )
        check_style = (
            "QCheckBox { color: #FAFAFA; font-size: 13px; background: transparent; }"
            "QCheckBox::indicator { width: 14px; height: 14px; border-radius: 2px; }"
            "QCheckBox::indicator:checked { background-color: #FBBF24;"
            "  border: 2px solid #FBBF24; }"
            "QCheckBox::indicator:unchecked { border: 2px solid #71717A;"
            "  background-color: transparent; }"
        )

        if q.multi_select:
            self._current_answer_group = None
            self._current_check_boxes = []
            for opt in q.options:
                cb = QCheckBox(opt)
                cb.setStyleSheet(check_style)
                self._options_layout.addWidget(cb)
                self._current_check_boxes.append(cb)
        else:
            self._current_check_boxes = []
            self._current_answer_group = QButtonGroup()
            for i, opt in enumerate(q.options):
                rb = QRadioButton(opt)
                rb.setStyleSheet(radio_style)
                if i == 0:
                    rb.setChecked(True)
                self._current_answer_group.addButton(rb, i)
                self._options_layout.addWidget(rb)

        # Update progress indicator
        visible_indices = self._get_visible_question_indices()
        current_pos = (visible_indices.index(idx) + 1) if idx in visible_indices else 1
        total_visible = len(visible_indices)
        pct = int(current_pos / max(total_visible, 1) * 100)
        self._progress_label.setText(f"Pergunta {current_pos} de {total_visible}")
        self._progress_bar.setValue(pct)
        self._progress_pct.setText(f"{pct}%")

        # Update button label
        future_visible = [i for i in visible_indices if i > idx]
        self._next_btn.setText("Próximo →" if future_visible else "Gerar Fila →")

    def _collect_current_answer(self) -> None:
        """Save the current question's selected answer into _interview_answers."""
        q = self._interview_questions[self._current_question_index]
        if q.multi_select:
            selected = [cb.text() for cb in self._current_check_boxes if cb.isChecked()]
            self._interview_answers[q.field_name] = selected
        elif self._current_answer_group is not None:
            btn = self._current_answer_group.checkedButton()
            if btn is not None:
                self._interview_answers[q.field_name] = btn.text()

    # ─────────────────────────────────────────────────────────── Slots ── #

    def _on_interview_next(self) -> None:
        """Advance to the next visible question or finish the interview."""
        self._collect_current_answer()

        visible_indices = self._get_visible_question_indices()
        future_visible = [i for i in visible_indices if i > self._current_question_index]

        if future_visible:
            self._render_question(future_visible[0])
        else:
            self._finish_interview()

    def _finish_interview(self) -> None:
        from workflow_app.interview.interview_engine import InterviewEngine
        engine = InterviewEngine()
        try:
            specs = engine.generate_command_list(self._interview_answers)
            self._load_review_page(specs)
        except (ValueError, KeyError) as exc:
            self._error_banner.show_error(str(exc))

    def _show_context_menu(self, pos) -> None:
        """Show right-click context menu on a review list item (ST003)."""
        item = self._review_list.itemAt(pos)
        if item is None:
            return
        spec: CommandSpec | None = item.data(Qt.ItemDataRole.UserRole)
        if spec is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #27272A; color: #FAFAFA;"
            "  border: 1px solid #3F3F46; }"
            "QMenu::item { padding: 6px 16px; }"
            "QMenu::item:selected { background-color: #3F3F46; }"
        )

        edit_action = menu.addAction("Editar Tipo...")
        edit_action.triggered.connect(lambda: self._on_edit_command_type(item, spec))

        if spec.is_optional:
            menu.addSeparator()
            remove_action = menu.addAction("Remover da fila")
            remove_action.triggered.connect(lambda: self._on_remove_item(item))

        menu.exec(self._review_list.viewport().mapToGlobal(pos))

    def _on_edit_command_type(self, item: QListWidgetItem, spec: CommandSpec) -> None:
        """Open EditCommandTypeDialog and apply the result to the list item."""
        from workflow_app.dialogs.edit_command_type_dialog import EditCommandTypeDialog
        dlg = EditCommandTypeDialog(spec, parent=self)
        dlg.command_updated.connect(
            lambda updated: self._apply_command_update(item, updated)
        )
        dlg.exec()

    def _apply_command_update(self, item: QListWidgetItem, updated: CommandSpec) -> None:
        """Refresh a list item after its CommandSpec was edited."""
        item.setData(Qt.ItemDataRole.UserRole, updated)
        self._review_list.setItemWidget(item, self._build_item_widget(updated))
        # Keep _generated_commands in sync
        for i, spec in enumerate(self._generated_commands):
            if spec.name == updated.name:
                self._generated_commands[i] = updated
                break

    def _on_remove_item(self, item: QListWidgetItem) -> None:
        """Remove an optional command from the review list."""
        self._review_list.takeItem(self._review_list.row(item))
        self._update_counter()

    def _on_add_command(self) -> None:
        """Open AddCommandDialog to append a new command to the queue."""
        from workflow_app.command_queue.add_command_dialog import AddCommandDialog
        next_pos = self._review_list.count() + 1
        dlg = AddCommandDialog(next_position=next_pos, parent=self)
        dlg.command_added.connect(self._on_command_from_dialog)
        dlg.exec()

    def _on_command_from_dialog(self, spec: CommandSpec) -> None:
        """Handle a new CommandSpec emitted by AddCommandDialog."""
        self._generated_commands.append(spec)
        self._add_list_item(spec)
        self._update_counter()

    def _on_save_template(self) -> None:
        self.save_as_template_requested.emit(self._get_current_specs())

    def _on_confirm(self) -> None:
        specs = self._get_current_specs()
        if not specs:
            return
        self.pipeline_ready.emit(specs)
        self.accept()

    def _get_current_specs(self) -> list[CommandSpec]:
        """Return CommandSpecs from the list in current display order."""
        specs = []
        for i in range(self._review_list.count()):
            spec = self._review_list.item(i).data(Qt.ItemDataRole.UserRole)
            if spec is not None:
                specs.append(spec)
        return specs
