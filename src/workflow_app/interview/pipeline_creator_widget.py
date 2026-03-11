"""
PipelineCreatorWidget — 3-page dialog for creating a command pipeline.

Pages (QStackedWidget):
  PAGE_CHOICE (0)   — Choose creation method (Interview or Template)
  PAGE_INTERVIEW (1) — InterviewWidget embedded
  PAGE_REVIEW (2)   — Review & confirm command list

Signals:
  pipeline_ready(list[CommandSpec])          — User confirmed the queue
  save_as_template_requested(list[CommandSpec]) — User clicked "Salvar como Template"

Min size: 580×520px
Header height: 56px (#27272A, border-bottom #3F3F46)
Footer height: 56px (#27272A, border-top #3F3F46)
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.widgets.model_badge import ModelBadge
from workflow_app.widgets.notification_banner import NotificationBanner

PAGE_CHOICE = 0
PAGE_INTERVIEW = 1
PAGE_REVIEW = 2


class PipelineCreatorWidget(QDialog):
    """Dialog for creating a new command pipeline via interview or template."""

    pipeline_ready = Signal(list)                  # list[CommandSpec]
    save_as_template_requested = Signal(list)       # list[CommandSpec]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Criar Nova Fila de Comandos")
        self.setMinimumSize(580, 520)
        self.setModal(True)
        self.setStyleSheet("background-color: #18181B;")

        self._generated_commands: list[CommandSpec] = []
        self._removed_positions: set[int] = set()

        self._setup_ui()
        self._update_footer(PAGE_CHOICE)

    # ─────────────────────────────────────────────────────────── UI ──── #

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

        self._stack.addWidget(self._build_choice_page())   # 0
        self._stack.addWidget(self._build_interview_page())  # 1
        self._stack.addWidget(self._build_review_page())   # 2

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

    # ── Page builders ──────────────────────────────────────────────── #

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
        interview_card.mousePressEvent = lambda _: self._go_to_interview()

        template_card = self._build_choice_card(
            icon="📋",
            title="Usar Template",
            description="Escolha um dos 4 templates pré-definidos ou um template salvo.",
        )
        template_card.mousePressEvent = lambda _: self._go_to_template()

        cl.addWidget(interview_card)
        cl.addWidget(template_card)
        layout.addWidget(cards_row)

        return page

    def _build_choice_card(self, icon: str, title: str, description: str) -> QWidget:
        card = QWidget()
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
        """Page 1: Interview widget (stub — real implementation in module-04/TASK-2)."""
        page = QWidget()
        page.setStyleSheet("background-color: #18181B;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(16)

        # Error banner (hidden by default)
        self._error_banner = NotificationBanner(page)
        layout.addWidget(self._error_banner)

        # Question area (placeholder — InterviewWidget will replace this)
        question_label = QLabel("Tipo de projeto:")
        question_label.setStyleSheet("color: #FAFAFA; font-size: 14px; font-weight: 600;")
        layout.addWidget(question_label)

        options_widget = QWidget()
        options_widget.setStyleSheet(
            "background-color: #27272A; border: 1px solid #3F3F46;"
            " border-radius: 6px; padding: 12px;"
        )
        ol = QVBoxLayout(options_widget)
        ol.setSpacing(8)
        options = [
            "Projeto Novo (F1-F12 completo)",
            "Feature Grande (PRD + LLD + WBS + execução)",
            "Feature Pequena (intake rápido + FDD + execute)",
            "Refactor",
        ]
        for opt in options:
            rb = QLabel(f"○  {opt}")
            rb.setStyleSheet("color: #FAFAFA; font-size: 13px;")
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            ol.addWidget(rb)
        layout.addWidget(options_widget)

        layout.addStretch()

        # Progress bar
        progress_row = QWidget()
        pl = QHBoxLayout(progress_row)
        pl.setContentsMargins(0, 0, 0, 0)
        progress_label = QLabel("Pergunta 1 de 4")
        progress_label.setStyleSheet("color: #A1A1AA; font-size: 12px;")
        pl.addWidget(progress_label)
        pl.addStretch()
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(25)
        self._progress_bar.setFixedSize(120, 8)
        self._progress_bar.setTextVisible(False)
        pl.addWidget(self._progress_bar)
        progress_pct = QLabel("25%")
        progress_pct.setStyleSheet("color: #A1A1AA; font-size: 12px;")
        pl.addWidget(progress_pct)
        layout.addWidget(progress_row)

        # "Generate" button (stub — triggers fake pipeline for demo)
        gen_btn = QPushButton("Gerar Fila →")
        gen_btn.setStyleSheet(
            "QPushButton { background-color: #FBBF24; color: #18181B;"
            "  font-weight: 700; border: none; border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #FDE68A; }"
        )
        gen_btn.clicked.connect(self._on_interview_completed_stub)
        layout.addWidget(gen_btn, alignment=Qt.AlignmentFlag.AlignRight)

        return page

    def _build_review_page(self) -> QWidget:
        """Page 2: Review & confirm command list."""
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
        hint = QLabel("Comandos opcionais podem ser removidos da fila.")
        hint.setStyleSheet("color: #71717A; font-size: 12px; font-style: italic;")
        hl.addWidget(hint)
        layout.addWidget(header_row)

        # Scrollable review list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "background-color: #18181B; border: 1px solid #3F3F46; border-radius: 8px;"
        )

        self._review_container = QWidget()
        self._review_container.setStyleSheet("background-color: #18181B;")
        self._review_layout = QVBoxLayout(self._review_container)
        self._review_layout.setContentsMargins(0, 0, 0, 0)
        self._review_layout.setSpacing(0)
        self._review_layout.addStretch()
        scroll.setWidget(self._review_container)
        layout.addWidget(scroll, stretch=1)

        return page

    # ─────────────────────────────────────────────────────── Navigation ─ #

    def _go_to_interview(self) -> None:
        self._stack.setCurrentIndex(PAGE_INTERVIEW)
        self._update_footer(PAGE_INTERVIEW)

    def _go_to_template(self) -> None:
        # TODO: Open TemplateListWidget sub-dialog — stub
        from workflow_app.widgets.notification_banner import NotificationBanner
        from workflow_app.interview.interview_engine import InterviewEngine
        # Stub: load a demo template
        engine = InterviewEngine()
        specs = engine.get_stub_template()
        self._load_review_page(specs)

    def _go_back(self) -> None:
        current = self._stack.currentIndex()
        if current == PAGE_INTERVIEW:
            self._stack.setCurrentIndex(PAGE_CHOICE)
            self._update_footer(PAGE_CHOICE)
        elif current == PAGE_REVIEW:
            self._stack.setCurrentIndex(PAGE_CHOICE)
            self._update_footer(PAGE_CHOICE)

    def _load_review_page(self, commands: list[CommandSpec]) -> None:
        self._generated_commands = commands
        self._removed_positions.clear()
        self._populate_review_list(commands)
        self._stack.setCurrentIndex(PAGE_REVIEW)
        self._update_footer(PAGE_REVIEW)

    def _update_footer(self, page: int) -> None:
        self._back_btn.setVisible(page != PAGE_CHOICE)
        self._save_template_btn.setVisible(page == PAGE_REVIEW)
        self._confirm_btn.setVisible(page == PAGE_REVIEW)

        if page == PAGE_REVIEW:
            count = len([c for c in self._generated_commands
                         if c.position not in self._removed_positions])
            self._confirm_btn.setEnabled(count > 0)

    def _populate_review_list(self, commands: list[CommandSpec]) -> None:
        # Clear existing items
        while self._review_layout.count() > 1:
            item = self._review_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        for spec in commands:
            row = ReviewItemRow(spec, parent=self._review_container)
            row.remove_toggled.connect(self._on_remove_toggled)
            self._review_layout.insertWidget(self._review_layout.count() - 1, row)

        self._update_counter()

    def _update_counter(self) -> None:
        count = len([c for c in self._generated_commands
                     if c.position not in self._removed_positions])
        self._counter_label.setText(f"{count} comando{'s' if count != 1 else ''} na fila")
        self._confirm_btn.setEnabled(count > 0)

    # ─────────────────────────────────────────────────────────── Slots ── #

    def _on_interview_completed_stub(self) -> None:
        """Stub: generate a demo pipeline for testing the review page."""
        from workflow_app.interview.interview_engine import InterviewEngine
        engine = InterviewEngine()
        try:
            specs = engine.get_stub_template()
            self._load_review_page(specs)
        except ValueError as exc:
            self._error_banner.show_error(str(exc))

    def _on_remove_toggled(self, position: int, removed: bool) -> None:
        if removed:
            self._removed_positions.add(position)
        else:
            self._removed_positions.discard(position)
        self._update_counter()

    def _on_save_template(self) -> None:
        active = [c for c in self._generated_commands
                  if c.position not in self._removed_positions]
        self.save_as_template_requested.emit(active)

    def _on_confirm(self) -> None:
        active = [c for c in self._generated_commands
                  if c.position not in self._removed_positions]
        if not active:
            return
        self.pipeline_ready.emit(active)
        self.accept()


# ─────────────────────────────────────────────────────── Review item ─── #


class ReviewItemRow(QWidget):
    """Single row in the review list (page 2)."""

    remove_toggled = Signal(int, bool)  # position, is_removed

    def __init__(self, spec: CommandSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.setFixedHeight(40)
        self.setStyleSheet(
            "background-color: #18181B; border-bottom: 1px solid #3F3F46;"
        )
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        # Position number
        pos_label = QLabel(f"#{self._spec.position:02d}")
        pos_label.setFixedWidth(32)
        pos_label.setStyleSheet("color: #71717A; font-size: 12px; font-weight: 600;")
        layout.addWidget(pos_label)

        # Command name
        self._name_label = QLabel(self._spec.name)
        self._name_label.setStyleSheet(
            "color: #FAFAFA; font-family: monospace; font-size: 13px;"
        )
        layout.addWidget(self._name_label, stretch=1)

        # Model badge
        model_badge = ModelBadge(self._spec.model, short=False, parent=self)
        layout.addWidget(model_badge)

        # Interaction badge
        inter_text = "→ auto" if self._spec.interaction_type == InteractionType.AUTO else "↔ inter"
        inter_style = (
            "background-color: #1E3A5F; color: #93C5FD;"
            if self._spec.interaction_type == InteractionType.AUTO
            else "background-color: #92400E; color: #FDE68A;"
        )
        inter_badge = QLabel(inter_text)
        inter_badge.setStyleSheet(
            f"{inter_style} border-radius: 4px; padding: 2px 6px;"
            " font-size: 11px;"
        )
        layout.addWidget(inter_badge)

        # Optional checkbox
        if self._spec.is_optional:
            self._checkbox = QCheckBox("remover")
            self._checkbox.setStyleSheet("color: #A1A1AA; font-size: 12px;")
            self._checkbox.toggled.connect(self._on_toggled)
            layout.addWidget(self._checkbox)

    def _on_toggled(self, checked: bool) -> None:
        if checked:
            self._name_label.setStyleSheet(
                "color: #71717A; font-family: monospace; font-size: 13px;"
                " text-decoration: line-through;"
            )
        else:
            self._name_label.setStyleSheet(
                "color: #FAFAFA; font-family: monospace; font-size: 13px;"
            )
        self.remove_toggled.emit(self._spec.position, checked)
