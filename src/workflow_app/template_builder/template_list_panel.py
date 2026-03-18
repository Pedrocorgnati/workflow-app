"""
TemplateListPanel — Scrollable list of all saved templates as collapsible editable cards.

Each card shows:
  Normal mode : [command name] [model badge]  (no action button)
  Edit mode   : [≡] [command name] [model badge] [−]  (drag to reorder, − removes)
  Card header : [▼ Name] [→ Carregar] [+ (edit)] [Editar / Salvar]  (factory: no edit)

WorkflowCatalogColumn — Left-panel listing all commands from WORKFLOW.md.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.signal_bus import signal_bus

# ─── Palette ──────────────────────────────────────────────────────────────── #

_DARK    = "#18181B"
_SURFACE = "#27272A"
_BORDER  = "#3F3F46"
_MUTED   = "#71717A"
_DROP_COLOR = QColor("#F59E0B")

_MODEL_COLOR: dict[ModelName, tuple[str, str]] = {
    ModelName.OPUS:   ("#7C3AED", "#FFFFFF"),
    ModelName.SONNET: ("#2563EB", "#FFFFFF"),
    ModelName.HAIKU:  ("#059669", "#FFFFFF"),
}

_MODEL_OPTIONS: list[tuple[str, ModelName | None]] = [
    ("— Sem modelo —", None),
    ("Opus",           ModelName.OPUS),
    ("Sonnet",         ModelName.SONNET),
    ("Haiku",          ModelName.HAIKU),
]


def _badge_style(model: ModelName) -> str:
    bg, fg = _MODEL_COLOR[model]
    return (
        f"background-color: {bg}; color: {fg}; border-radius: 3px;"
        "padding: 1px 5px; font-size: 10px; font-weight: 600;"
    )


# ─── WORKFLOW.md parsing ──────────────────────────────────────────────────── #

_WORKFLOW_ENTRY_RE = re.compile(r"^\s*\(([hos])\)\s+(/\S+)")
_SECTION_HEADER_RE = re.compile(r"^##\s+(.+)")
_MODEL_MAP_WF: dict[str, ModelName] = {
    "h": ModelName.HAIKU,
    "s": ModelName.SONNET,
    "o": ModelName.OPUS,
}
_INTERACTIVE_CMDS = frozenset({
    # F1 — Brief (genuine interviews)
    "/project-json", "/create-flow", "/first-brief-create",
    "/feature-brief-create", "/module-brief-create", "/intake:enhance",
    "/tech-feasibility",
    # F2 — PRD (genuine interviews)
    "/prd-create", "/user-stories-create", "/hld-create", "/lld-create",
    "/fdd-create", "/adr-create", "/design-create", "/review-prd-flow",
    "/notification-spec-create", "/analytics-spec-create", "/i18n-spec-create",
    "/privacy-assessment-create",
    # F3 — Optimization (selection interviews)
    "/create-scaffolds", "/create-blueprints", "/create-guardrails",
    "/create-integrations",
    # F4 — WBS (genuine interviews)
    "/modules:create-core", "/modules:create-variants",
    "/rollout-strategy-create",
    # F4b — Micro
    "/micro-architecture", "/micro:plan", "/micro:setup",
    # F5 — WBS+
    "/reforge-pipeline",
    # F6 — Business (genuine interviews)
    "/business:sow-create", "/business:create-budget",
    "/business:simple-budget",
    # F7 — Execução
    "/create-mocks",
    # F8 — Complemento
    "/env-creation",
    # F9 — QA (genuine interviews)
    "/qa:prep", "/qa-remediate", "/load-test-create",
    # F10 — Validação
    "/validate-stack", "/final-review",
    # F11 — Deploy (genuine interviews)
    "/pre-deploy-testing", "/ci-cd-create", "/monitoring-setup",
    "/post-deploy-verify", "/changelog-create", "/deploy-flow",
    "/infra-create", "/slo-create", "/staging-validate",
    # F12 — Marketing
    "/docs-create",
    # Daily
    "/daily", "/daily:plan",
})


def _find_workflow_md() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "WORKFLOW.md"
        if candidate.exists():
            return candidate
    return None


def _parse_workflow_md() -> list[tuple[str, str, ModelName, bool]]:
    """Parse WORKFLOW.md. Returns list of (section, name, model, is_interactive)."""
    path = _find_workflow_md()
    if path is None:
        return []
    entries: list[tuple[str, str, ModelName, bool]] = []
    seen: set[str] = set()
    current_section = "Geral"
    for line in path.read_text(encoding="utf-8").splitlines():
        sec_m = _SECTION_HEADER_RE.match(line)
        if sec_m:
            current_section = sec_m.group(1).strip()
            continue
        cmd_m = _WORKFLOW_ENTRY_RE.match(line)
        if cmd_m:
            model_key = cmd_m.group(1)
            name = cmd_m.group(2)
            if name not in seen:
                seen.add(name)
                entries.append((
                    current_section,
                    name,
                    _MODEL_MAP_WF[model_key],
                    name in _INTERACTIVE_CMDS,
                ))
    return entries


# ─── Workflow Command Row ─────────────────────────────────────────────────── #

class _WorkflowCmdRow(QWidget):
    """One row in the workflow catalog column: name + interactivity + model + [+]."""

    add_requested = Signal(object)  # CommandSpec

    def __init__(
        self,
        name: str,
        model: ModelName,
        is_interactive: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._model = model
        self._is_interactive = is_interactive
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 4, 2)
        layout.setSpacing(4)

        lbl = QLabel(self._name)
        lbl.setStyleSheet(
            "color: #D4D4D8; font-family: monospace; font-size: 11px;"
        )
        layout.addWidget(lbl, stretch=1)

        if self._is_interactive:
            i_lbl = QLabel("I")
            i_lbl.setToolTip("Interativo — requer entrada do usuário")
            i_lbl.setStyleSheet(
                "background: #78350F; color: #FBBF24; border-radius: 3px;"
                "padding: 0px 4px; font-size: 9px; font-weight: 700;"
            )
            i_lbl.setFixedWidth(14)
            i_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(i_lbl)

        badge = QLabel(self._model.value)
        badge.setStyleSheet(_badge_style(self._model))
        layout.addWidget(badge)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(20, 20)
        add_btn.setToolTip("Adicionar ao template em edição (ou à fila)")
        add_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #52525B;"
            "  color: #22C55E; border-radius: 3px; font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { background: #14532D; border-color: #22C55E; }"
        )
        add_btn.clicked.connect(self._on_add)
        layout.addWidget(add_btn)

        self.setFixedHeight(28)
        self.setStyleSheet(
            f"QWidget {{ background-color: {_DARK}; border-bottom: 1px solid {_SURFACE}; }}"
            f"QWidget:hover {{ background-color: {_SURFACE}; }}"
        )

    def _on_add(self) -> None:
        spec = CommandSpec(
            name=self._name,
            model=self._model,
            interaction_type=InteractionType.INTERACTIVE if self._is_interactive else InteractionType.AUTO,
        )
        self.add_requested.emit(spec)

    def matches_filter(self, text: str) -> bool:
        return not text or text in self._name.lower()


# ─── Workflow Catalog Column ──────────────────────────────────────────────── #

class WorkflowCatalogColumn(QWidget):
    """
    Left column in the Templates tab: lists all commands from WORKFLOW.md.
    [+] on a row emits add_command_requested(CommandSpec).
    """

    add_command_requested = Signal(object)  # CommandSpec

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, _WorkflowCmdRow]] = []  # (section, row)
        self._section_headers: list[tuple[str, QLabel]] = []
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QLabel("  WORKFLOW.MD")
        hdr.setFixedHeight(28)
        hdr.setStyleSheet(
            f"background-color: {_SURFACE}; color: {_MUTED}; font-size: 11px;"
            "font-weight: 600; letter-spacing: 0.5px; border-bottom: 1px solid #3F3F46;"
        )
        root.addWidget(hdr)

        # Search bar
        search_bar = QWidget()
        search_bar.setFixedHeight(32)
        search_bar.setStyleSheet(f"background: #1C1C1F; border-bottom: 1px solid {_BORDER};")
        sl = QHBoxLayout(search_bar)
        sl.setContentsMargins(6, 4, 6, 4)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filtrar...")
        self._search.setStyleSheet(
            f"background: {_BORDER}; color: #FAFAFA; border: none;"
            "border-radius: 3px; padding: 1px 6px; font-size: 11px;"
        )
        self._search.textChanged.connect(self._apply_filter)
        sl.addWidget(self._search)
        root.addWidget(search_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"border: none; background-color: {_DARK};")

        self._container = QWidget()
        self._container.setStyleSheet(f"background-color: {_DARK};")
        self._vbox = QVBoxLayout(self._container)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(0)

        self._populate()
        self._vbox.addStretch()

        scroll.setWidget(self._container)
        root.addWidget(scroll, stretch=1)

    def _populate(self) -> None:
        entries = _parse_workflow_md()
        current_section: str | None = None

        for section, name, model, is_interactive in entries:
            if section != current_section:
                current_section = section
                sec_lbl = QLabel(f"  {section}")
                sec_lbl.setFixedHeight(22)
                sec_lbl.setStyleSheet(
                    f"background: {_SURFACE}; color: #A1A1AA; font-size: 10px;"
                    f"font-weight: 600; border-bottom: 1px solid {_BORDER};"
                )
                self._vbox.addWidget(sec_lbl)
                self._section_headers.append((section, sec_lbl))

            row = _WorkflowCmdRow(name, model, is_interactive, parent=self._container)
            row.add_requested.connect(self.add_command_requested)
            self._vbox.addWidget(row)
            self._rows.append((section, row))

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for section, row in self._rows:
            row.setVisible(row.matches_filter(text))
        for section, hdr in self._section_headers:
            visible = any(
                r.isVisible() for s, r in self._rows if s == section
            )
            hdr.setVisible(visible)


# ─── Add Command Dialog ───────────────────────────────────────────────────── #

class _AddCommandDialog(QDialog):
    """Small modal: command name + {json} checkbox + model select."""

    def __init__(
        self,
        parent: QWidget | None = None,
        initial_name: str = "",
        initial_model: ModelName | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar Comando" if initial_name else "Adicionar Comando")
        self.setModal(True)
        self.setFixedSize(400, 210)
        self.setStyleSheet(
            f"background-color: {_SURFACE}; color: #FAFAFA;"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 12)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Command input
        self._cmd_input = QLineEdit()
        self._cmd_input.setPlaceholderText("/meu-comando")
        if initial_name:
            self._cmd_input.setText(initial_name)
        self._cmd_input.setStyleSheet(
            f"background: #3F3F46; color: #FAFAFA; border: 1px solid {_BORDER};"
            "border-radius: 3px; padding: 2px 8px; font-size: 12px; font-family: monospace;"
        )
        self._cmd_input.setFixedHeight(28)
        form.addRow("Comando:", self._cmd_input)

        # {json} checkbox
        self._json_cb = QCheckBox("Importar {json}  — acrescenta o caminho do projeto.json")
        self._json_cb.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        form.addRow("", self._json_cb)

        # Model select
        self._model_combo = QComboBox()
        for label, value in _MODEL_OPTIONS:
            self._model_combo.addItem(label, value)
        if initial_model is not None:
            for i, (_, v) in enumerate(_MODEL_OPTIONS):
                if v == initial_model:
                    self._model_combo.setCurrentIndex(i)
                    break
        else:
            self._model_combo.setCurrentIndex(2)  # Sonnet default
        self._model_combo.setFixedHeight(28)
        self._model_combo.setStyleSheet(
            f"QComboBox {{ background: #3F3F46; color: #FAFAFA; border: 1px solid {_BORDER};"
            "  border-radius: 3px; padding: 0 6px; font-size: 12px; }}"
            "QComboBox QAbstractItemView { background: #3F3F46; color: #FAFAFA; }"
        )
        form.addRow("Modelo:", self._model_combo)

        layout.addLayout(form)
        layout.addStretch()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Salvar" if initial_name else "Adicionar")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        btns.setStyleSheet(
            f"QPushButton {{ background: #3F3F46; color: #FAFAFA; border: 1px solid {_BORDER};"
            "  border-radius: 3px; padding: 4px 14px; font-size: 12px; }}"
            "QPushButton:hover { background: #52525B; }"
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    @property
    def command_name(self) -> str:
        name = self._cmd_input.text().strip()
        if name and not name.startswith("/"):
            name = "/" + name
        if self._json_cb.isChecked():
            name += " {json}"
        return name

    @property
    def model(self) -> ModelName | None:
        return self._model_combo.currentData()


# ─── Droppable container ──────────────────────────────────────────────────── #

class _DroppableCommandsContainer(QWidget):
    """Paints a drop indicator line for D&D reordering."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._indicator: int | None = None

    def set_indicator(self, pos: int | None) -> None:
        self._indicator = pos
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._indicator is None:
            return
        layout = self.layout()
        if layout is None:
            return
        count = layout.count()
        idx = self._indicator
        if idx <= 0:
            y = 0
        elif idx >= count:
            last = layout.itemAt(count - 1)
            y = last.widget().geometry().bottom() if (last and last.widget()) else self.height()
        else:
            item = layout.itemAt(idx)
            y = item.widget().geometry().top() if (item and item.widget()) else 0
        painter = QPainter(self)
        painter.setPen(QPen(_DROP_COLOR, 2))
        painter.drawLine(4, y, self.width() - 4, y)
        painter.end()


# ─── Template Command Row ─────────────────────────────────────────────────── #

class _TemplateCommandRow(QWidget):
    """One command row in a template card. Switches between normal/edit mode."""

    remove_self = Signal(object)   # self
    edit_requested = Signal(object)  # self

    _DRAG_THRESHOLD = 8

    def __init__(
        self,
        spec: CommandSpec,
        show_model: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.spec = spec
        self._show_model = show_model
        self._editing = False
        self._drag_start: QPoint | None = None
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        # Drag handle (edit mode only)
        self._handle = QLabel("≡")
        self._handle.setFixedWidth(14)
        self._handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._handle.setStyleSheet(f"color: {_MUTED}; font-size: 14px;")
        self._handle.setCursor(Qt.CursorShape.SizeVerCursor)
        self._handle.setVisible(False)
        layout.addWidget(self._handle)

        # Command name
        display = self.spec.name
        if self.spec.config_path:
            display += f" {self.spec.config_path}"
        self._name_lbl = QLabel(display)
        self._name_lbl.setStyleSheet("color: #D4D4D8; font-family: monospace; font-size: 12px;")
        layout.addWidget(self._name_lbl, stretch=1)

        # Model badge
        self._badge = QLabel("")
        if self._show_model:
            self._badge.setText(self.spec.model.value)
            self._badge.setStyleSheet(_badge_style(self.spec.model))
        layout.addWidget(self._badge)

        # Edit button (always visible)
        self._edit_btn = QPushButton("✏")
        self._edit_btn.setFixedSize(20, 20)
        self._edit_btn.setToolTip("Editar comando")
        self._edit_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #52525B;"
            "  color: #A1A1AA; border-radius: 3px; font-size: 11px; }"
            "QPushButton:hover { background: #3F3F46; color: #FAFAFA; }"
        )
        self._edit_btn.clicked.connect(lambda: self.edit_requested.emit(self))
        layout.addWidget(self._edit_btn)

        # Remove button (always visible)
        self._remove_btn = QPushButton("✕")
        self._remove_btn.setFixedSize(20, 20)
        self._remove_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #7F1D1D;"
            "  color: #EF4444; border-radius: 3px; font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { background: #450a0a; border-color: #EF4444; }"
        )
        self._remove_btn.clicked.connect(lambda: self.remove_self.emit(self))
        layout.addWidget(self._remove_btn)

        self.setFixedHeight(30)
        self.setStyleSheet(
            f"QWidget {{ background-color: {_DARK}; border-bottom: 1px solid {_SURFACE}; }}"
            f"QWidget:hover {{ background-color: {_SURFACE}; }}"
        )

    def set_editing(self, editing: bool) -> None:
        self._editing = editing
        self._handle.setVisible(editing)

    def is_model_cmd(self) -> bool:
        return self.spec.name.lower().startswith("/model")

    def is_clear_cmd(self) -> bool:
        n = self.spec.name.strip().lower()
        return n == "/clear" or n.startswith("/clear ")

    def apply_cmd_filter(self, show_model: bool, show_clear: bool) -> None:
        if self.is_model_cmd():
            self.setVisible(show_model)
        elif self.is_clear_cmd():
            self.setVisible(show_clear)
        else:
            self.setVisible(True)

    def refresh_display(self) -> None:
        """Re-render name label and badge after spec update."""
        display = self.spec.name
        if self.spec.config_path:
            display += f" {self.spec.config_path}"
        self._name_lbl.setText(display)
        show_model = not self.spec.name.lower().startswith("/model")
        if show_model and self._show_model:
            self._badge.setText(self.spec.model.value)
            self._badge.setStyleSheet(_badge_style(self.spec.model))
        else:
            self._badge.setText("")

    # ── Drag source ── #

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._editing:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._drag_start is None or not self._editing:
            return
        delta = (event.position().toPoint() - self._drag_start).manhattanLength()
        if delta < self._DRAG_THRESHOLD:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText("tcr_drag")
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)
        self._drag_start = None

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_start = None
        super().mouseReleaseEvent(event)


# ─── Template Card ────────────────────────────────────────────────────────── #

class _TemplateCard(QWidget):
    """Collapsible card for one template."""

    def __init__(
        self,
        template_id: int | None,
        name: str,
        is_factory: bool,
        commands: list[CommandSpec],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._template_id = template_id
        self._name = name
        self._is_factory = is_factory
        self._rows: list[_TemplateCommandRow] = []
        self._editing = False
        self._expanded = False
        self._build(commands)

    def _build(self, commands: list[CommandSpec]) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ── #
        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 0, 6, 0)
        hl.setSpacing(4)

        self._chevron_btn = QPushButton(self._header_text())
        self._chevron_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #FAFAFA;"
            "  font-size: 12px; font-weight: 600; text-align: left; padding: 0; }"
            "QPushButton:hover { color: #FBBF24; }"
        )
        self._chevron_btn.clicked.connect(self._toggle_expand)
        hl.addWidget(self._chevron_btn, stretch=1)

        # Command count badge
        n = len(commands)
        count_lbl = QLabel(f"{n}")
        count_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px; padding: 0 4px;"
        )
        hl.addWidget(count_lbl)

        # Load all to queue
        load_btn = QPushButton("→ Carregar")
        load_btn.setFixedHeight(22)
        load_btn.setStyleSheet(
            "QPushButton { background: #166534; color: #FAFAFA; border: none;"
            "  border-radius: 3px; font-size: 10px; padding: 0 8px; }"
            "QPushButton:hover { background: #15803D; }"
        )
        load_btn.clicked.connect(self._load_to_queue)
        hl.addWidget(load_btn)

        # Add command button (edit mode only)
        self._add_cmd_btn = QPushButton("+")
        self._add_cmd_btn.setFixedSize(24, 22)
        self._add_cmd_btn.setToolTip("Adicionar comando")
        self._add_cmd_btn.setStyleSheet(
            "QPushButton { background: #1D4ED8; color: #FAFAFA; border: none;"
            "  border-radius: 3px; font-size: 14px; font-weight: 700; }"
            "QPushButton:hover { background: #1E40AF; }"
        )
        self._add_cmd_btn.setVisible(False)
        self._add_cmd_btn.clicked.connect(self._on_add_command)
        hl.addWidget(self._add_cmd_btn)

        # Edit / Save button (custom templates only)
        if not self._is_factory:
            self._edit_btn = QPushButton("Editar")
            self._edit_btn.setFixedHeight(22)
            self._apply_edit_btn_normal_style()
            self._edit_btn.clicked.connect(self._toggle_edit)
            hl.addWidget(self._edit_btn)

        outer.addWidget(header)

        # ── Commands container ── #
        self._cmd_widget = _DroppableCommandsContainer()
        self._cmd_widget.setAcceptDrops(True)
        self._cmd_widget.installEventFilter(self)
        self._cmd_layout = QVBoxLayout(self._cmd_widget)
        self._cmd_layout.setContentsMargins(0, 0, 0, 0)
        self._cmd_layout.setSpacing(0)
        self._cmd_widget.setVisible(False)
        self._populate_rows(commands)
        outer.addWidget(self._cmd_widget)

        self.setStyleSheet(
            f"background-color: {_DARK}; border-bottom: 2px solid {_BORDER};"
        )

    # ── Helpers ── #

    def _header_text(self) -> str:
        arrow = "▼" if self._expanded else "▶"
        prefix = "🏭 " if self._is_factory else "✏ "
        return f"{arrow}  {prefix}{self._name}"

    def _apply_edit_btn_normal_style(self) -> None:
        self._edit_btn.setText("Editar")
        self._edit_btn.setStyleSheet(
            f"QPushButton {{ background: #3F3F46; color: #A1A1AA; border: 1px solid {_BORDER};"
            "  border-radius: 3px; font-size: 10px; padding: 0 8px; }}"
            "QPushButton:hover { background: #52525B; color: #FAFAFA; }"
        )

    def _apply_edit_btn_save_style(self) -> None:
        self._edit_btn.setText("Salvar")
        self._edit_btn.setStyleSheet(
            "QPushButton { background: #78350F; color: #FBBF24; border: 1px solid #FBBF24;"
            "  border-radius: 3px; font-size: 10px; padding: 0 8px; }"
            "QPushButton:hover { background: #92400E; }"
        )

    def _populate_rows(self, commands: list[CommandSpec]) -> None:
        for r in self._rows:
            r.setParent(None)
        self._rows.clear()

        # Inject synthetic /model rows where the model changes,
        # so the "model" checkbox has rows to show/hide.
        expanded: list[CommandSpec] = []
        current_model = None
        for spec in commands:
            if spec.name.lower().startswith("/model"):
                # Already has an explicit /model row — keep as-is
                expanded.append(spec)
                current_model = spec.model
                continue
            if spec.name == "/clear":
                expanded.append(spec)
                current_model = None  # force model row after clear
                continue
            if spec.model != current_model:
                expanded.append(CommandSpec(
                    name=f"/model {spec.model.value.lower()}",
                    model=spec.model,
                    interaction_type=InteractionType.AUTO,
                    position=0,
                ))
                current_model = spec.model
            expanded.append(spec)

        for spec in expanded:
            show_model = not spec.name.lower().startswith("/model")
            row = _TemplateCommandRow(spec, show_model=show_model, parent=self._cmd_widget)
            row.remove_self.connect(self._remove_row)
            row.edit_requested.connect(self._on_edit_row)
            self._cmd_layout.addWidget(row)
            self._rows.append(row)

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self._cmd_widget.setVisible(self._expanded)
        self._chevron_btn.setText(self._header_text())

    def _toggle_edit(self) -> None:
        if self._editing:
            self._save_edit()
        else:
            self._start_edit()

    def _start_edit(self) -> None:
        self._editing = True
        self._apply_edit_btn_save_style()
        self._add_cmd_btn.setVisible(True)
        if not self._expanded:
            self._toggle_expand()
        for row in self._rows:
            row.set_editing(True)

    def _save_edit(self) -> None:
        self._editing = False
        self._apply_edit_btn_normal_style()
        self._add_cmd_btn.setVisible(False)
        for row in self._rows:
            row.set_editing(False)
        self._persist()

    def _persist(self) -> None:
        if self._template_id is None:
            return
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.templates.template_manager import TemplateManager
            # Filter out synthetic /model rows — they are display-only
            specs = [
                CommandSpec(
                    name=r.spec.name,
                    model=r.spec.model,
                    interaction_type=r.spec.interaction_type,
                    position=i + 1,
                    is_optional=r.spec.is_optional,
                    config_path=r.spec.config_path,
                )
                for i, r in enumerate(
                    r for r in self._rows if not r.is_model_cmd()
                )
            ]
            mgr = TemplateManager(db_manager)
            mgr.update_custom_template(self._template_id, specs)
            signal_bus.toast_requested.emit(f"Template '{self._name}' atualizado.", "success")
        except Exception as exc:
            signal_bus.toast_requested.emit(str(exc), "error")

    def _remove_row(self, row: _TemplateCommandRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
        row.setParent(None)
        if not self._editing:
            self._persist()

    def _on_edit_row(self, row: _TemplateCommandRow) -> None:
        dlg = _AddCommandDialog(
            parent=self,
            initial_name=row.spec.name,
            initial_model=row.spec.model,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = dlg.command_name
        if not name:
            return
        model = dlg.model or ModelName.SONNET
        row.spec = CommandSpec(
            name=name,
            model=model,
            interaction_type=row.spec.interaction_type,
            position=row.spec.position,
            is_optional=row.spec.is_optional,
            config_path=row.spec.config_path,
        )
        row.refresh_display()
        if not self._editing:
            self._persist()

    def apply_cmd_filter(self, show_model: bool, show_clear: bool) -> None:
        for row in self._rows:
            row.apply_cmd_filter(show_model, show_clear)
        # Force layout recalculation after visibility changes
        if self._cmd_layout is not None:
            self._cmd_layout.invalidate()
        self._cmd_widget.updateGeometry()
        self._cmd_widget.update()

    def _on_add_command(self) -> None:
        dlg = _AddCommandDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = dlg.command_name
        if not name:
            return
        model = dlg.model or ModelName.SONNET
        show_model = dlg.model is not None
        spec = CommandSpec(
            name=name,
            model=model,
            interaction_type=InteractionType.AUTO,
        )
        self._add_spec_as_row(spec, show_model)

    def add_command_spec(self, spec: CommandSpec) -> None:
        """Add a CommandSpec to this card (called from catalog column [+])."""
        if not self._editing:
            return
        show_model = not spec.name.lower().startswith("/model")
        self._add_spec_as_row(spec, show_model)

    def _add_spec_as_row(self, spec: CommandSpec, show_model: bool = True) -> None:
        row = _TemplateCommandRow(spec, show_model=show_model, parent=self._cmd_widget)
        row.set_editing(True)
        row.remove_self.connect(self._remove_row)
        row.edit_requested.connect(self._on_edit_row)
        self._cmd_layout.addWidget(row)
        self._rows.append(row)

    def _load_to_queue(self) -> None:
        """Load all commands to queue, inserting /model switcher rows."""
        # Skip synthetic /model rows — they'll be re-injected below
        raw = [
            CommandSpec(
                name=r.spec.name,
                model=r.spec.model,
                interaction_type=r.spec.interaction_type,
                position=0,
                is_optional=r.spec.is_optional,
                config_path=r.spec.config_path,
            )
            for r in self._rows
            if not r.is_model_cmd()
        ]
        expanded: list[CommandSpec] = []
        current_model = None
        for spec in raw:
            if not spec.name.lower().startswith("/model"):
                if spec.model != current_model:
                    expanded.append(CommandSpec(
                        name=f"/model {spec.model.value.lower()}",
                        model=spec.model,
                        interaction_type=InteractionType.AUTO,
                        position=0,
                    ))
                    current_model = spec.model
            expanded.append(spec)
        for i, spec in enumerate(expanded, start=1):
            spec.position = i
        signal_bus.pipeline_ready.emit(expanded)

    # ── D&D event filter on _cmd_widget ── #

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._cmd_widget and self._editing:
            t = event.type()
            if t == QEvent.Type.DragEnter:
                if event.mimeData().hasText():
                    event.acceptProposedAction()
                    return True
            elif t == QEvent.Type.DragMove:
                if event.mimeData().hasText():
                    self._update_indicator(event.position().toPoint())
                    event.acceptProposedAction()
                    return True
            elif t == QEvent.Type.DragLeave:
                self._cmd_widget.set_indicator(None)
                return True
            elif t == QEvent.Type.Drop:
                self._on_drop(event)
                return True
        return super().eventFilter(obj, event)

    def _update_indicator(self, pos: QPoint) -> None:
        layout = self._cmd_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                if pos.y() < item.widget().geometry().center().y():
                    self._cmd_widget.set_indicator(i)
                    return
        self._cmd_widget.set_indicator(layout.count())

    def _on_drop(self, event) -> None:
        source = event.source()
        to_idx = self._cmd_widget._indicator
        self._cmd_widget.set_indicator(None)
        if source not in self._rows or to_idx is None:
            event.ignore()
            return
        from_idx = self._rows.index(source)
        adj = to_idx - (1 if to_idx > from_idx else 0)
        if from_idx == adj:
            event.ignore()
            return
        event.acceptProposedAction()
        self._rows.pop(from_idx)
        self._rows.insert(adj, source)
        self._rebuild_layout()

    def _rebuild_layout(self) -> None:
        while self._cmd_layout.count():
            item = self._cmd_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for row in self._rows:
            row.setParent(self._cmd_widget)
            self._cmd_layout.addWidget(row)


# ─── WBS Dynamic Card ─────────────────────────────────────────────────────── #

class _WbsDynamicCard(QWidget):
    """Card especial para o template WBS dinâmico (não armazenado no DB)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 0, 6, 0)
        hl.setSpacing(4)

        title_btn = QPushButton("▶  🏭 WBS")
        title_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #FAFAFA;"
            "  font-size: 12px; font-weight: 600; text-align: left; padding: 0; }"
            "QPushButton:hover { color: #FBBF24; }"
        )
        hl.addWidget(title_btn, stretch=1)

        dyn_lbl = QLabel("dinâmico")
        dyn_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px; padding: 0 4px;"
        )
        hl.addWidget(dyn_lbl)

        load_btn = QPushButton("→ Carregar")
        load_btn.setFixedHeight(22)
        load_btn.setStyleSheet(
            "QPushButton { background: #166534; color: #FAFAFA; border: none;"
            "  border-radius: 3px; font-size: 10px; padding: 0 8px; }"
            "QPushButton:hover { background: #15803D; }"
        )
        load_btn.clicked.connect(self._load_wbs)
        hl.addWidget(load_btn)

        outer.addWidget(header)
        self.setStyleSheet(
            f"background-color: {_DARK}; border-bottom: 2px solid {_BORDER};"
        )

    def _load_wbs(self) -> None:
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

        expanded = _inject_clears(template)
        signal_bus.pipeline_ready.emit(expanded)


# ─── Template List Panel ──────────────────────────────────────────────────── #

class TemplateListPanel(QWidget):
    """Scrollable list of all templates (factory + custom) as editable cards."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[_TemplateCard] = []
        self._show_model = False
        self._show_clear = False
        self._build()
        self._load_templates()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QLabel("  TEMPLATES SALVOS")
        hdr.setFixedHeight(28)
        hdr.setStyleSheet(
            f"background-color: {_SURFACE}; color: {_MUTED}; font-size: 11px;"
            "font-weight: 600; letter-spacing: 0.5px; border-bottom: 1px solid #3F3F46;"
        )
        root.addWidget(hdr)

        # Filter navbar
        navbar = QWidget()
        navbar.setFixedHeight(28)
        navbar.setStyleSheet(
            f"background-color: #1C1C1F; border-bottom: 1px solid {_BORDER};"
        )
        nl = QHBoxLayout(navbar)
        nl.setContentsMargins(8, 0, 8, 0)
        nl.setSpacing(12)

        filter_lbl = QLabel("Mostrar:")
        filter_lbl.setStyleSheet(f"color: {_MUTED}; font-size: 10px; border: none;")
        nl.addWidget(filter_lbl)

        self._cb_model = QCheckBox("model")
        self._cb_model.setStyleSheet(
            f"QCheckBox {{ color: #A1A1AA; font-size: 10px; border: none; }}"
            "QCheckBox::indicator { width: 12px; height: 12px; }"
            f"QCheckBox::indicator:unchecked {{ border: 1px solid {_BORDER}; border-radius: 2px; background: {_DARK}; }}"
            "QCheckBox::indicator:checked { border: 1px solid #7C3AED; border-radius: 2px; background: #7C3AED; }"
        )
        self._cb_model.setToolTip("Exibir comandos /model no fluxo")
        self._cb_model.stateChanged.connect(self._on_filter_changed)
        nl.addWidget(self._cb_model)

        self._cb_clear = QCheckBox("clear")
        self._cb_clear.setStyleSheet(
            f"QCheckBox {{ color: #A1A1AA; font-size: 10px; border: none; }}"
            "QCheckBox::indicator { width: 12px; height: 12px; }"
            f"QCheckBox::indicator:unchecked {{ border: 1px solid {_BORDER}; border-radius: 2px; background: {_DARK}; }}"
            "QCheckBox::indicator:checked { border: 1px solid #F59E0B; border-radius: 2px; background: #F59E0B; }"
        )
        self._cb_clear.setToolTip("Exibir comandos /clear no fluxo")
        self._cb_clear.stateChanged.connect(self._on_filter_changed)
        nl.addWidget(self._cb_clear)

        nl.addStretch()
        root.addWidget(navbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"border: none; background-color: {_DARK};")

        self._container = QWidget()
        self._container.setStyleSheet(f"background-color: {_DARK};")
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()

        scroll.setWidget(self._container)
        root.addWidget(scroll, stretch=1)

    def _load_templates(self) -> None:
        # Add WBS dynamic card at the top
        wbs_card = _WbsDynamicCard()
        idx = self._list_layout.count() - 1
        self._list_layout.insertWidget(idx, wbs_card)

        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.templates.template_manager import TemplateManager
            mgr = TemplateManager(db_manager)
            templates = mgr.list_templates()
        except Exception:
            return

        for tmpl in templates:
            try:
                full = mgr.load_template(tmpl.id)
                card = _TemplateCard(
                    template_id=full.id,
                    name=full.name,
                    is_factory=full.is_factory,
                    commands=full.commands,
                )
                idx = self._list_layout.count() - 1  # before stretch
                self._list_layout.insertWidget(idx, card)
                self._cards.append(card)
                card.apply_cmd_filter(self._show_model, self._show_clear)
            except Exception:
                continue

    def _on_filter_changed(self) -> None:
        self._show_model = self._cb_model.isChecked()
        self._show_clear = self._cb_clear.isChecked()
        for card in self._cards:
            card.apply_cmd_filter(self._show_model, self._show_clear)
        # Force the scroll area container to recalculate layout
        self._container.updateGeometry()
        self._container.update()

    def get_editing_card(self) -> _TemplateCard | None:
        """Return the card currently in edit mode, or None."""
        for card in self._cards:
            if card._editing:
                return card
        return None

    def refresh(self) -> None:
        """Reload all templates from DB."""
        # Remove all children except the stretch item
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._cards.clear()
        self._load_templates()
