"""
TemplateBuilderWidget — 3-column layout inside the Templates tab.

┌──────────────────┬──────────────────┬──────────────────────────┐
│  CATÁLOGO        │  TEMPLATES SALVOS│  NOVO TEMPLATE           │
│  (todos comandos)│  (factory+custom)│  [Nome___] [Salvar][→]   │
│  /cmd  Sonnet [+]│  ▶ JSON      [→] │  /project-json  ↑ ↓ ✕   │
│  ...             │  ▶ Brief: New[→] │  /prd-create    ↑ ↓ ✕   │
│  ── Custom ────  │  ✏ Meu Template  │  ...                     │
│  [/cmd__] [Mod▼] │    [Editar]      │                          │
└──────────────────┴──────────────────┴──────────────────────────┘

[+] in column 1 → adds to the card in edit mode (col 2), or to
    the new template list (col 3) if no card is editing.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.signal_bus import signal_bus

# ─── Command catalog grouped by phase ───────────────────────────────────────── #

_O = ModelName.OPUS
_S = ModelName.SONNET
_H = ModelName.HAIKU
_I = InteractionType.INTERACTIVE
_A = InteractionType.AUTO

COMMAND_CATALOG: list[tuple[str, list[tuple[str, ModelName, InteractionType]]]] = [
    ("F1 — Brief", [
        ("/project-json",           _S, _I),
        ("/first-brief-create",     _O, _I),
        ("/feature-brief-create",   _O, _I),
        ("/intake:analyze",         _S, _A),
        ("/intake:enhance",         _O, _I),
        ("/tech-feasibility",       _O, _I),
        ("/break-intake",           _S, _A),
        ("/module-brief-create",    _O, _I),
    ]),
    ("F2 — PRD", [
        ("/prd-create",             _O, _I),
        ("/user-stories-create",    _S, _I),
        ("/hld-create",             _O, _I),
        ("/lld-create",             _O, _I),
        ("/fdd-create",             _O, _I),
        ("/adr-create",             _O, _I),
        ("/design-create",          _O, _I),
        ("/deep-research-1",        _O, _A),
        ("/deep-research-2",        _O, _A),
        ("/api-contract-create",    _O, _A),
        ("/threat-model-create",    _O, _A),
        ("/error-catalog-create",   _S, _A),
        ("/notification-spec-create", _S, _I),
        ("/analytics-spec-create",  _S, _I),
        ("/i18n-spec-create",       _S, _I),
        ("/review-prd-flow",        _O, _I),
    ]),
    ("F4 — WBS", [
        ("/auto-flow modules",      _O, _I),
        ("/modules:create",         _O, _I),
        ("/rollout-strategy-create",_S, _I),
    ]),
    ("F5 — WBS+", [
        ("/auto-flow create",       _S, _A),
        ("/validate-pipeline",      _S, _A),
        ("/create-task",            _S, _A),
        ("/create-overview",        _S, _A),
        ("/create-task-layout",     _S, _A),
        ("/review-created-task",    _S, _A),
    ]),
    ("F6 — Business", [
        ("/business:product-brief-create", _O, _A),
        ("/business:sow-create",    _O, _I),
        ("/business:create-budget", _S, _I),
        ("/business:generate-pdf-docs", _H, _A),
    ]),
    ("F7 — Execução", [
        ("/mobile-first-build",     _S, _A),
        ("/front-end-build",        _S, _A),
        ("/data-test-id",           _S, _A),
        ("/auto-flow execute",      _S, _A),
        ("/execute-task",           _S, _A),
        ("/review-executed-task",   _S, _A),
        ("/create-assets",          _H, _A),
        ("/create-mocks",           _S, _I),
        ("/github-linking",         _H, _A),
    ]),
    ("F8 — Complemento", [
        ("/env-creation",           _H, _I),
        ("/docker-create",          _S, _A),
        ("/seed-data-create",       _S, _A),
        ("/create-test-user",       _H, _A),
    ]),
    ("F9 — QA", [
        ("/qa:prep",                _S, _I),
        ("/qa:trace",               _O, _A),
        ("/qa:report",              _S, _A),
        ("/validate-backend",       _O, _A),
        ("/validate-front-end",     _O, _A),
        ("/qa-remediate",           _S, _I),
        ("/load-test-create",       _S, _I),
        ("/tech-debt-audit",        _S, _A),
    ]),
    ("F10 — Validação", [
        ("/validate-stack",         _H, _I),
        ("/review-language",        _H, _A),
        ("/final-review",           _S, _I),
    ]),
    ("F11 — Deploy", [
        ("/pre-deploy-testing",     _S, _I),
        ("/ci-cd-create",           _S, _I),
        ("/monitoring-setup",       _S, _I),
        ("/post-deploy-verify",     _S, _I),
        ("/changelog-create",       _H, _I),
        ("/deploy-flow",            _S, _I),
        ("/supabase-sql-editor",    _S, _A),
    ]),
]

_MODEL_COLOR = {
    ModelName.OPUS:   ("#7C3AED", "#FFFFFF"),
    ModelName.SONNET: ("#2563EB", "#FFFFFF"),
    ModelName.HAIKU:  ("#059669", "#FFFFFF"),
}


def _badge_style(model: ModelName) -> str:
    bg, fg = _MODEL_COLOR[model]
    return (
        f"background-color: {bg}; color: {fg};"
        "border-radius: 3px; padding: 1px 5px; font-size: 10px; font-weight: 600;"
    )


_INTERACTION_COLOR = {
    InteractionType.AUTO:        ("#1E3A5F", "#93C5FD"),   # blue — automático
    InteractionType.INTERACTIVE: ("#92400E", "#FDE68A"),   # amber — interativo
}
_INTERACTION_LABEL = {
    InteractionType.AUTO:        "Auto",
    InteractionType.INTERACTIVE: "Inter.",
}


def _interaction_badge_style(interaction: InteractionType) -> str:
    bg, fg = _INTERACTION_COLOR[interaction]
    return (
        f"background-color: {bg}; color: {fg};"
        "border-radius: 3px; padding: 1px 5px; font-size: 10px; font-weight: 600;"
    )


# ─── Selected command row (column 3) ─────────────────────────────────────────── #

class _SelectedRow(QWidget):
    move_up   = Signal(object)
    move_down = Signal(object)
    remove    = Signal(object)

    def __init__(self, spec: CommandSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(4)

        name = QLabel(self.spec.name)
        name.setStyleSheet("color: #FAFAFA; font-family: monospace; font-size: 12px;")
        layout.addWidget(name, stretch=1)

        badge = QLabel(self.spec.model.value)
        badge.setStyleSheet(_badge_style(self.spec.model))
        layout.addWidget(badge)

        for symbol, sig in [("↑", self.move_up), ("↓", self.move_down), ("✕", self.remove)]:
            btn = QPushButton(symbol)
            btn.setFixedSize(18, 18)
            color = "#EF4444" if symbol == "✕" else "#71717A"
            hover = "#FCA5A5" if symbol == "✕" else "#FAFAFA"
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none;"
                f"  color: {color}; font-size: 10px; }}"
                f"QPushButton:hover {{ color: {hover}; }}"
            )
            btn.clicked.connect(lambda _=False, s=sig: s.emit(self))
            layout.addWidget(btn)

        self.setStyleSheet(
            "QWidget { background-color: #27272A; border-bottom: 1px solid #3F3F46; }"
            "QWidget:hover { background-color: #3F3F46; }"
        )
        self.setFixedHeight(34)


# ─── Catalog command row (column 1) ──────────────────────────────────────────── #

class _CatalogRow(QWidget):
    """One row in the catalog list.

    View mode:  [name ─────] [Opus] [Auto] [✏] [+]
    Edit mode:  [name input] [Model▼] [Tipo▼] [✓] [✕]
    """

    add_requested = Signal(str, object, object)  # name, model, interaction_type

    def __init__(
        self,
        name: str,
        model: ModelName,
        interaction: InteractionType,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._model = model
        self._interaction = interaction
        self._build()

    # ── Build ── #

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        self._stack.addWidget(self._build_view_page())   # index 0
        self._stack.addWidget(self._build_edit_page())   # index 1
        self._stack.setCurrentIndex(0)

        self.setStyleSheet(
            "QWidget { background-color: #18181B; border-bottom: 1px solid #27272A; }"
            "QWidget:hover { background-color: #27272A; }"
        )
        self.setFixedHeight(32)

    def _build_view_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        self._view_name = QLabel(self._name)
        self._view_name.setStyleSheet(
            "color: #D4D4D8; font-family: monospace; font-size: 12px;"
        )
        layout.addWidget(self._view_name, stretch=1)

        self._view_model_badge = QLabel(self._model.value)
        self._view_model_badge.setStyleSheet(_badge_style(self._model))
        layout.addWidget(self._view_model_badge)

        self._view_interaction_badge = QLabel(_INTERACTION_LABEL[self._interaction])
        self._view_interaction_badge.setStyleSheet(
            _interaction_badge_style(self._interaction)
        )
        layout.addWidget(self._view_interaction_badge)

        edit_btn = QPushButton("✏")
        edit_btn.setFixedSize(20, 20)
        edit_btn.setToolTip("Editar comando")
        edit_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            "  color: #52525B; font-size: 11px; border-radius: 3px; }"
            "QPushButton:hover { color: #FBBF24; background: #27272A; }"
        )
        edit_btn.clicked.connect(self._enter_edit)
        layout.addWidget(edit_btn)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(20, 20)
        add_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #52525B;"
            "  color: #22C55E; border-radius: 3px; font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { background: #14532D; border-color: #22C55E; }"
        )
        add_btn.clicked.connect(
            lambda: self.add_requested.emit(self._name, self._model, self._interaction)
        )
        layout.addWidget(add_btn)

        return page

    def _build_edit_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        self._edit_name = QLineEdit(self._name)
        self._edit_name.setStyleSheet(
            "background: #3F3F46; color: #FAFAFA; border: 1px solid #FBBF24;"
            "border-radius: 3px; padding: 0 4px; font-size: 12px; font-family: monospace;"
        )
        self._edit_name.setFixedHeight(22)
        layout.addWidget(self._edit_name, stretch=1)

        self._edit_model = QComboBox()
        for m in ModelName:
            self._edit_model.addItem(m.value, m)
        self._edit_model.setCurrentText(self._model.value)
        self._edit_model.setFixedHeight(22)
        self._edit_model.setFixedWidth(68)
        self._edit_model.setStyleSheet(
            "QComboBox { background: #3F3F46; color: #FAFAFA; border: 1px solid #52525B;"
            "  border-radius: 3px; padding: 0 4px; font-size: 11px; }"
            "QComboBox QAbstractItemView { background: #27272A; color: #FAFAFA;"
            "  selection-background-color: #52525B; }"
        )
        layout.addWidget(self._edit_model)

        self._edit_interaction = QComboBox()
        self._edit_interaction.addItem("Auto",      InteractionType.AUTO)
        self._edit_interaction.addItem("Interativo", InteractionType.INTERACTIVE)
        current_idx = 0 if self._interaction == InteractionType.AUTO else 1
        self._edit_interaction.setCurrentIndex(current_idx)
        self._edit_interaction.setFixedHeight(22)
        self._edit_interaction.setFixedWidth(76)
        self._edit_interaction.setStyleSheet(
            "QComboBox { background: #3F3F46; color: #FAFAFA; border: 1px solid #52525B;"
            "  border-radius: 3px; padding: 0 4px; font-size: 11px; }"
            "QComboBox QAbstractItemView { background: #27272A; color: #FAFAFA;"
            "  selection-background-color: #52525B; }"
        )
        layout.addWidget(self._edit_interaction)

        confirm_btn = QPushButton("✓")
        confirm_btn.setFixedSize(20, 20)
        confirm_btn.setToolTip("Confirmar")
        confirm_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            "  color: #22C55E; font-size: 13px; font-weight: 700; border-radius: 3px; }"
            "QPushButton:hover { background: #14532D; }"
        )
        confirm_btn.clicked.connect(self._confirm_edit)
        layout.addWidget(confirm_btn)

        cancel_btn = QPushButton("✕")
        cancel_btn.setFixedSize(20, 20)
        cancel_btn.setToolTip("Cancelar")
        cancel_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            "  color: #71717A; font-size: 11px; border-radius: 3px; }"
            "QPushButton:hover { color: #EF4444; background: #27272A; }"
        )
        cancel_btn.clicked.connect(self._cancel_edit)
        layout.addWidget(cancel_btn)

        return page

    # ── Edit mode transitions ── #

    def _enter_edit(self) -> None:
        self._edit_name.setText(self._name)
        self._edit_model.setCurrentText(self._model.value)
        idx = 0 if self._interaction == InteractionType.AUTO else 1
        self._edit_interaction.setCurrentIndex(idx)
        self._stack.setCurrentIndex(1)
        self._edit_name.setFocus()
        self._edit_name.selectAll()

    def _confirm_edit(self) -> None:
        new_name = self._edit_name.text().strip()
        if new_name:
            self._name = new_name if new_name.startswith("/") else "/" + new_name
        self._model = self._edit_model.currentData()
        self._interaction = self._edit_interaction.currentData()
        # Refresh view labels
        self._view_name.setText(self._name)
        self._view_model_badge.setText(self._model.value)
        self._view_model_badge.setStyleSheet(_badge_style(self._model))
        self._view_interaction_badge.setText(_INTERACTION_LABEL[self._interaction])
        self._view_interaction_badge.setStyleSheet(
            _interaction_badge_style(self._interaction)
        )
        self._stack.setCurrentIndex(0)

    def _cancel_edit(self) -> None:
        self._stack.setCurrentIndex(0)


# ─── Main widget ─────────────────────────────────────────────────────────────── #

class TemplateBuilderWidget(QWidget):
    """Three-column layout: [Catalog | Saved Templates | New Template]."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("testid", "template-builder")
        self._selected: list[_SelectedRow] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        from workflow_app.template_builder.template_list_panel import TemplateListPanel

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3F3F46; }"
            "QSplitter::handle:hover { background-color: #FBBF24; }"
        )

        # ── Column 1: Command catalog ── #
        splitter.addWidget(self._build_catalog_panel())

        # ── Column 2: Saved templates ── #
        self._list_panel = TemplateListPanel()
        splitter.addWidget(self._list_panel)

        # ── Column 3: New template builder ── #
        splitter.addWidget(self._build_new_template_panel())

        splitter.setSizes([300, 380, 280])
        root.addWidget(splitter, stretch=1)

    # ── Column 1 ── #

    def _build_catalog_panel(self) -> QWidget:
        panel = QWidget()
        panel.setProperty("testid", "tpl-catalog-panel")
        panel.setStyleSheet("background-color: #18181B;")
        cl = QVBoxLayout(panel)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        hdr = QLabel("  CATÁLOGO DE COMANDOS")
        hdr.setProperty("testid", "tpl-catalog-header")
        hdr.setFixedHeight(28)
        hdr.setStyleSheet(
            "background-color: #27272A; color: #71717A; font-size: 11px;"
            "font-weight: 600; letter-spacing: 0.5px; border-bottom: 1px solid #3F3F46;"
        )
        cl.addWidget(hdr)

        # Search filter
        search_bar = QWidget()
        search_bar.setFixedHeight(34)
        search_bar.setStyleSheet("background-color: #1C1C1F; border-bottom: 1px solid #3F3F46;")
        sl = QHBoxLayout(search_bar)
        sl.setContentsMargins(8, 4, 8, 4)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filtrar...")
        self._search.setStyleSheet(
            "background-color: #3F3F46; color: #FAFAFA; border: none;"
            "border-radius: 3px; padding: 2px 8px; font-size: 12px;"
        )
        self._search.textChanged.connect(self._apply_filter)
        sl.addWidget(self._search)
        cl.addWidget(search_bar)

        catalog_scroll = QScrollArea()
        catalog_scroll.setWidgetResizable(True)
        catalog_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        catalog_scroll.setStyleSheet("border: none; background-color: #18181B;")

        self._catalog_container = QWidget()
        self._catalog_container.setProperty("testid", "tpl-catalog-list")
        self._catalog_container.setStyleSheet("background-color: #18181B;")
        self._catalog_layout = QVBoxLayout(self._catalog_container)
        self._catalog_layout.setContentsMargins(0, 0, 0, 0)
        self._catalog_layout.setSpacing(0)
        self._build_catalog()
        self._catalog_layout.addStretch()

        catalog_scroll.setWidget(self._catalog_container)
        cl.addWidget(catalog_scroll, stretch=1)

        # Custom command input
        custom_bar = QWidget()
        custom_bar.setFixedHeight(40)
        custom_bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        cbl = QHBoxLayout(custom_bar)
        cbl.setContentsMargins(8, 5, 8, 5)
        cbl.setSpacing(6)

        self._custom_input = QLineEdit()
        self._custom_input.setPlaceholderText("/meu-comando")
        self._custom_input.setStyleSheet(
            "background-color: #3F3F46; color: #FAFAFA; border: 1px solid #52525B;"
            "border-radius: 3px; padding: 2px 6px; font-size: 12px;"
        )
        self._custom_input.setFixedHeight(26)
        cbl.addWidget(self._custom_input, stretch=1)

        self._custom_model = QComboBox()
        for m in ModelName:
            self._custom_model.addItem(m.value, m)
        self._custom_model.setCurrentIndex(1)  # Sonnet default
        self._custom_model.setFixedHeight(26)
        self._custom_model.setStyleSheet(
            "QComboBox { background: #3F3F46; color: #FAFAFA; border: 1px solid #52525B;"
            "  border-radius: 3px; padding: 0 6px; font-size: 12px; }"
        )
        self._custom_model.setFixedWidth(72)
        cbl.addWidget(self._custom_model)

        add_custom = QPushButton("+")
        add_custom.setFixedSize(26, 26)
        add_custom.setStyleSheet(
            "QPushButton { background: #166534; color: #FAFAFA; border: none;"
            "  border-radius: 3px; font-size: 14px; font-weight: 700; }"
            "QPushButton:hover { background: #15803D; }"
        )
        add_custom.clicked.connect(self._on_add_custom)
        add_custom.setToolTip("Adicionar comando personalizado")
        cbl.addWidget(add_custom)

        cl.addWidget(custom_bar)
        return panel

    # ── Column 3 ── #

    def _build_new_template_panel(self) -> QWidget:
        panel = QWidget()
        panel.setProperty("testid", "tpl-new-panel")
        panel.setStyleSheet("background-color: #18181B;")
        rl = QVBoxLayout(panel)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        # Top bar: name + save + load
        top_bar = QWidget()
        top_bar.setFixedHeight(44)
        top_bar.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )
        tl = QHBoxLayout(top_bar)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(6)

        name_lbl = QLabel("Nome:")
        name_lbl.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        tl.addWidget(name_lbl)

        self._name_input = QLineEdit()
        self._name_input.setProperty("testid", "tpl-name-input")
        self._name_input.setPlaceholderText("Nome do template...")
        self._name_input.setStyleSheet(
            "background-color: #3F3F46; color: #FAFAFA; border: 1px solid #52525B;"
            "border-radius: 4px; padding: 2px 8px; font-size: 12px;"
        )
        self._name_input.setFixedHeight(28)
        tl.addWidget(self._name_input, stretch=1)

        self._save_btn = QPushButton("Salvar")
        self._save_btn.setProperty("testid", "tpl-btn-save")
        self._save_btn.setFixedHeight(28)
        self._save_btn.setStyleSheet(
            "QPushButton { background: #78350F; color: #FBBF24; border: 1px solid #FBBF24;"
            "  border-radius: 4px; font-size: 11px; padding: 0 8px; }"
            "QPushButton:hover { background: #92400E; }"
        )
        self._save_btn.clicked.connect(self._on_save)
        tl.addWidget(self._save_btn)

        self._load_btn = QPushButton("→ Fila")
        self._load_btn.setProperty("testid", "tpl-btn-load-queue")
        self._load_btn.setFixedHeight(28)
        self._load_btn.setStyleSheet(
            "QPushButton { background: #166534; color: #FAFAFA; border: none;"
            "  border-radius: 4px; font-size: 11px; font-weight: 700; padding: 0 8px; }"
            "QPushButton:hover { background: #15803D; }"
        )
        self._load_btn.clicked.connect(self._on_load)
        tl.addWidget(self._load_btn)

        rl.addWidget(top_bar)

        # Selected list header
        sel_header_row = QWidget()
        sel_header_row.setFixedHeight(28)
        sel_header_row.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )
        shl = QHBoxLayout(sel_header_row)
        shl.setContentsMargins(8, 0, 8, 0)
        sel_header = QLabel("SELECIONADOS")
        sel_header.setStyleSheet(
            "color: #71717A; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;"
        )
        shl.addWidget(sel_header, stretch=1)
        self._count_label = QLabel("0 comandos")
        self._count_label.setStyleSheet("color: #52525B; font-size: 11px;")
        shl.addWidget(self._count_label)
        rl.addWidget(sel_header_row)

        # Selected scroll area
        selected_scroll = QScrollArea()
        selected_scroll.setWidgetResizable(True)
        selected_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        selected_scroll.setStyleSheet("border: none; background-color: #18181B;")

        self._selected_container = QWidget()
        self._selected_container.setProperty("testid", "tpl-selected-list")
        self._selected_container.setStyleSheet("background-color: #18181B;")
        self._selected_layout = QVBoxLayout(self._selected_container)
        self._selected_layout.setContentsMargins(0, 0, 0, 0)
        self._selected_layout.setSpacing(0)
        self._selected_layout.addStretch()

        self._empty_label = QLabel("Clique + para adicionar comandos")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #52525B; font-size: 12px;")
        self._selected_layout.insertWidget(0, self._empty_label)

        selected_scroll.setWidget(self._selected_container)
        rl.addWidget(selected_scroll, stretch=1)

        # Footer: clear button
        clear_bar = QWidget()
        clear_bar.setFixedHeight(34)
        clear_bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        clrl = QHBoxLayout(clear_bar)
        clrl.setContentsMargins(8, 4, 8, 4)
        clear_btn = QPushButton("Limpar tudo")
        clear_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #71717A; border: none; font-size: 11px; }"
            "QPushButton:hover { color: #EF4444; }"
        )
        clear_btn.clicked.connect(self._clear_all)
        clrl.addWidget(clear_btn)
        clrl.addStretch()
        rl.addWidget(clear_bar)

        return panel

    # ── Catalog builder ── #

    def _build_catalog(self) -> None:
        self._all_rows: list[tuple[str, _CatalogRow]] = []
        self._phase_headers: list[tuple[str, QLabel]] = []

        for phase, cmds in COMMAND_CATALOG:
            hdr = QLabel(f"  {phase}")
            hdr.setFixedHeight(24)
            hdr.setStyleSheet(
                "background-color: #27272A; color: #A1A1AA; font-size: 11px;"
                "font-weight: 600; border-bottom: 1px solid #3F3F46;"
            )
            self._catalog_layout.addWidget(hdr)
            self._phase_headers.append((phase, hdr))

            for name, model, interaction in cmds:
                row = _CatalogRow(name, model, interaction)
                row.add_requested.connect(self._on_catalog_add)
                self._catalog_layout.addWidget(row)
                self._all_rows.append((phase, row))

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for _phase, row in self._all_rows:
            row.setVisible(not text or text in row._name.lower())
        for phase, hdr in self._phase_headers:
            visible = any(r.isVisible() for p, r in self._all_rows if p == phase)
            hdr.setVisible(visible)

    # ── Slots ── #

    def _on_catalog_add(self, name: str, model: ModelName, interaction: InteractionType) -> None:
        """Route [+]: editing card in col 2 → add there; else → add to col 3 selected list."""
        spec = CommandSpec(name=name, model=model, interaction_type=interaction)
        card = self._list_panel.get_editing_card()
        if card is not None:
            card.add_command_spec(spec)
        else:
            self._add_to_selected(spec)

    def _on_add_custom(self) -> None:
        name = self._custom_input.text().strip()
        if not name:
            return
        if not name.startswith("/"):
            name = "/" + name
        model: ModelName = self._custom_model.currentData()
        spec = CommandSpec(name=name, model=model)
        card = self._list_panel.get_editing_card()
        if card is not None:
            card.add_command_spec(spec)
        else:
            self._add_to_selected(spec)
        self._custom_input.clear()

    def _add_to_selected(self, spec: CommandSpec) -> None:
        row = _SelectedRow(spec)
        row.move_up.connect(self._move_up)
        row.move_down.connect(self._move_down)
        row.remove.connect(self._remove_row)
        idx = self._selected_layout.count() - 1
        self._selected_layout.insertWidget(idx, row)
        self._selected.append(row)
        self._empty_label.setVisible(False)
        self._update_count()

    def _move_up(self, row: _SelectedRow) -> None:
        idx = self._selected.index(row)
        if idx == 0:
            return
        self._selected.pop(idx)
        self._selected.insert(idx - 1, row)
        self._rebuild_selected_layout()

    def _move_down(self, row: _SelectedRow) -> None:
        idx = self._selected.index(row)
        if idx == len(self._selected) - 1:
            return
        self._selected.pop(idx)
        self._selected.insert(idx + 1, row)
        self._rebuild_selected_layout()

    def _remove_row(self, row: _SelectedRow) -> None:
        self._selected.remove(row)
        row.setParent(None)
        if not self._selected:
            self._empty_label.setVisible(True)
        self._update_count()

    def _rebuild_selected_layout(self) -> None:
        while self._selected_layout.count() > 1:
            item = self._selected_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for i, row in enumerate(self._selected):
            self._selected_layout.insertWidget(i, row)

    def _clear_all(self) -> None:
        for row in list(self._selected):
            row.setParent(None)
        self._selected.clear()
        self._empty_label.setVisible(True)
        self._update_count()

    def _update_count(self) -> None:
        n = len(self._selected)
        self._count_label.setText(f"{n} comando{'s' if n != 1 else ''}")

    def _build_specs(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name=row.spec.name,
                model=row.spec.model,
                interaction_type=row.spec.interaction_type,
                position=i + 1,
            )
            for i, row in enumerate(self._selected)
        ]

    def _on_load(self) -> None:
        if not self._selected:
            return
        signal_bus.pipeline_ready.emit(self._build_specs())

    def _on_save(self) -> None:
        name = self._name_input.text().strip()
        if not name or not self._selected:
            return
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.templates.template_manager import TemplateManager
            mgr = TemplateManager(db_manager)
            mgr.save_custom_template(name, "", self._build_specs())
            signal_bus.toast_requested.emit(f"Template '{name}' salvo.", "success")
            self._name_input.clear()
            self._list_panel.refresh()
        except Exception as exc:
            signal_bus.toast_requested.emit(str(exc), "error")
