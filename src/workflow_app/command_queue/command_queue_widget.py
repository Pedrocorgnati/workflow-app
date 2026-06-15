"""
CommandQueueWidget — 280px right panel showing the command queue.

States:
  - Empty: placeholder (vazio)
  - With commands: scrollable list of CommandItemWidget rows + [+] button at bottom

Width: fixed 280px (min 240px, max 360px)
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from workflow_app import dcp as dcp_pkg
from workflow_app.command_queue.command_item_widget import CommandItemWidget
from workflow_app.command_queue.codex_whitelist import is_image_generation_command
from workflow_app.command_queue.double_phase_button import DoublePhaseButton
from workflow_app.command_queue.kimi_whitelist import is_kimi_compatible
from workflow_app.command_queue.provider_router import (
    Provider,
    RoutingState,
    classify_provider,
)
from workflow_app.dialogs.confirm_cancel_modal import ConfirmCancelModal
from workflow_app.metrics_bar.recovery_prompt import RECOVERY_REASONS
from workflow_app.domain import (
    CommandSpec,
    CommandStatus,
    EffortLevel,
    FlagSpec,
    InteractionType,
    ModelName,
)
from workflow_app.services.delivery_invalid_formatter import (
    format_delivery_invalid_popup,
)
from workflow_app.services.matrix_invalid_formatter import (
    discover_latest_bak,
    extract_schema_version,
    format_matrix_invalid_popup,
)
from workflow_app.signal_bus import signal_bus
from workflow_app.templates.quick_templates import (
    COMMAND_FLAG_SPECS,
    TEMPLATE_BLOG,
    TEMPLATE_BLOG_STOCKPILE,
    TEMPLATE_BOILERPLATE,
    TEMPLATE_BRIEF_NEW,
    TEMPLATE_DAILY,
    TEMPLATE_HOSTGATOR,
    TEMPLATE_INTAKE_REVIEW,
    TEMPLATE_INTAKE_SEED,
    TEMPLATE_JSON,
    TEMPLATE_MICRO_ARCHITECTURE,
    TEMPLATE_MIGRATION,
    TEMPLATE_MKT,
    TEMPLATE_MODULES,
    TEMPLATE_STUDY,
)

_DROP_INDICATOR_COLOR = QColor("#F59E0B")  # Amber-400
_DROP_INDICATOR_WIDTH = 2

_WORKFLOW_APP_DIR = Path(__file__).resolve().parents[3]  # .../ai-forge/workflow-app


class ResponsiveButtonFlowLayout(QLayout):
    """Flow layout para botoes compactos das subtabs de insercoes.

    Quebra widgets em linhas conforme a largura disponivel. Quando a linha 5
    seria necessaria, reduz a largura alocada dos itens para manter no maximo
    `max_lines` linhas renderizadas.
    """

    _BUTTON_FLOOR_WIDTH = 44
    _ABSOLUTE_FLOOR_WIDTH = 8

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        spacing: int = 4,
        max_lines: int = 4,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self._max_lines = max(1, max_lines)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt API
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt API
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt API
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:  # noqa: N802 - Qt API
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt API
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt API
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt API
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(360, self.heightForWidth(360))

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt API
        left, top, right, bottom = self.getContentsMargins()
        min_height = 0
        min_width = self._BUTTON_FLOOR_WIDTH
        for item in self._visible_items():
            min_height = max(min_height, item.minimumSize().height(), item.sizeHint().height())
            min_width = max(min_width, min(item.minimumSize().width(), self._BUTTON_FLOOR_WIDTH))
        return QSize(min_width + left + right, min_height + top + bottom)

    def _visible_items(self) -> list[QLayoutItem]:
        visible: list[QLayoutItem] = []
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            visible.append(item)
        return visible

    def _base_width(self, item: QLayoutItem) -> int:
        return max(item.sizeHint().width(), item.minimumSize().width(), self._BUTTON_FLOOR_WIDTH)

    def _target_floor_width(self, items: list[QLayoutItem], width: int) -> int:
        if not items or width <= 0:
            return self._BUTTON_FLOOR_WIDTH
        items_per_line = max(1, (len(items) + self._max_lines - 1) // self._max_lines)
        fit_width = (width - self._spacing * (items_per_line - 1)) // items_per_line
        return max(self._ABSOLUTE_FLOOR_WIDTH, min(self._BUTTON_FLOOR_WIDTH, fit_width))

    def _floor_width(self, item: QLayoutItem, target_floor: int | None = None) -> int:
        # Permite compactar botoes alem do minimumWidth explicito quando a 5a
        # linha seria criada, mas preserva um alvo legivel.
        floor = self._BUTTON_FLOOR_WIDTH if target_floor is None else target_floor
        return min(self._base_width(item), floor)

    def _width_for_scale(
        self, item: QLayoutItem, scale: float, target_floor: int | None = None,
    ) -> int:
        base = self._base_width(item)
        floor = self._floor_width(item, target_floor)
        return max(floor, int(round(base * scale)))

    def _apply_compact_min_width(self, item: QLayoutItem, width: int) -> None:
        widget = item.widget()
        if widget is None:
            return
        original = widget.property("_responsive_flow_original_min_width")
        if not isinstance(original, int):
            original = widget.minimumWidth()
            widget.setProperty("_responsive_flow_original_min_width", original)
        target = min(original, width)
        if widget.minimumWidth() != target:
            widget.setMinimumWidth(target)

    def _line_count_for_scale(
        self,
        items: list[QLayoutItem],
        width: int,
        scale: float,
        target_floor: int | None = None,
    ) -> int:
        if not items:
            return 0
        if width <= 0:
            return len(items)
        lines = 1
        x = 0
        for item in items:
            item_width = self._width_for_scale(item, scale, target_floor)
            next_x = item_width if x == 0 else x + self._spacing + item_width
            if x > 0 and next_x > width:
                lines += 1
                x = item_width
            else:
                x = next_x
        return lines

    def _scale_and_floor_for_width(self, items: list[QLayoutItem], width: int) -> tuple[float, int]:
        target_floor = self._target_floor_width(items, width)
        if self._line_count_for_scale(items, width, 1.0, target_floor) <= self._max_lines:
            return 1.0, target_floor

        best = 0.0
        low, high = 0.0, 1.0
        for _ in range(14):
            mid = (low + high) / 2.0
            if self._line_count_for_scale(items, width, mid, target_floor) <= self._max_lines:
                best = mid
                low = mid
            else:
                high = mid
        return best, target_floor

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        items = self._visible_items()
        if not items:
            return top + bottom

        width = max(0, effective.width())
        scale, target_floor = self._scale_and_floor_for_width(items, width)
        y = effective.y()
        line_height = 0
        line_width = 0
        rendered_lines = 1

        for item in items:
            item_width = self._width_for_scale(item, scale, target_floor)
            item_height = item.sizeHint().height()
            next_line_width = (
                item_width if line_width == 0
                else line_width + self._spacing + item_width
            )

            if line_width > 0 and next_line_width > width and rendered_lines < self._max_lines:
                y += line_height + self._spacing
                line_height = 0
                line_width = 0
                rendered_lines += 1
                next_line_width = item_width

            if not test_only:
                item_x = effective.x() if line_width == 0 else effective.x() + line_width + self._spacing
                self._apply_compact_min_width(item, item_width)
                item.setGeometry(QRect(QPoint(item_x, y), QSize(item_width, item_height)))
            line_width = next_line_width
            line_height = max(line_height, item_height)

        return y + line_height - rect.y() + bottom


class _VisibilitySignalLabel(QLabel):
    """QLabel que emite `visibility_changed(bool)` em todo `setVisible`.

    Usado pelo `_template_label` para manter a `_template_row` sincronizada
    sem precisar trocar as ~20 chamadas existentes a
    `self._template_label.setVisible(True/False)` espalhadas pelo widget."""

    visibility_changed = Signal(bool)

    def setVisible(self, visible: bool) -> None:  # noqa: N802
        super().setVisible(visible)
        self.visibility_changed.emit(bool(visible))


class _ScheduleAutocastButton(QPushButton):
    """QPushButton de 2 modos:

    - compact (default): so o icone `⏱` centralizado. Usado em idle
      ("agendar") e fired ("disparado"); o botao fica 1:1.
    - expanded: renderiza `⏱ <texto>` para mostrar o cronometro durante
      a contagem. O caller deve relaxar largura (min/max) e adicionar
      stretch no layout para o botao crescer.

    `set_expanded(bool)` alterna o modo. `_base_text` sempre guarda o
    ultimo label recebido para tooltip/consumo externo.
    """

    _ICON = "⏱"

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(self._ICON, parent)
        self._base_text = text
        self._expanded = False

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._base_text = text
        self._refresh_display()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._refresh_display()

    def base_text(self) -> str:
        return self._base_text

    def _refresh_display(self) -> None:
        if self._expanded and self._base_text:
            super().setText(f"{self._ICON} {self._base_text}")
        else:
            super().setText(self._ICON)


class _TemplateLabel(_VisibilitySignalLabel):
    """Label do queue-template-label com prefixo fixo `Last template: `.

    Mudanca 2026-05-17: a label e sempre visivel e a parte variavel passa a
    ser o testid do ultimo botao clicado em pipelines/workflow/auxiliar (ver
    `_install_tab_click_tracker` no CommandQueueWidget). Chamadas legadas a
    `setText("  📋  X")` continuam funcionando (o texto vira valor da label
    ate o proximo click em tab tracker sobrescrever)."""

    _PREFIX = "Last template: "
    _PLACEHOLDER = "—"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self._PREFIX + self._PLACEHOLDER, parent)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        if text.startswith(self._PREFIX):
            super().setText(text)
            return
        cleaned = text.strip() or self._PLACEHOLDER
        super().setText(self._PREFIX + cleaned)

    def set_value(self, value: str) -> None:
        super().setText(self._PREFIX + (value.strip() or self._PLACEHOLDER))

    def setVisible(self, visible: bool) -> None:  # noqa: N802 - Qt API
        # Sempre visivel: ignora pedidos para esconder, mantem signal compat.
        super().setVisible(True)


def _load_tinted_svg_icon(path: Path, color_hex: str) -> QIcon | None:
    """Le um SVG com `currentColor` e renderiza em `color_hex`.

    Espelha `MainWindow._load_tinted_svg_icon` (main_window.py) para evitar
    dependencia circular ao reaproveitar o icone de `copy.svg` aqui.
    """
    if not path.is_file():
        return None
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    tinted = raw.replace("currentColor", color_hex)
    renderer = QSvgRenderer(QByteArray(tinted.encode("utf-8")))
    if not renderer.isValid():
        return None
    pixmap = QPixmap(QSize(32, 32))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return QIcon(pixmap)

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
    "  font-size: 10px; font-weight: 600; padding: 1px 3px; }"
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

logger = logging.getLogger(__name__)

_MODEL_MAP = {
    "opus": ModelName.OPUS,
    "sonnet": ModelName.SONNET,
}

_EFFORT_MAP = {
    "low": EffortLevel.LOW,
    "medium": EffortLevel.STANDARD,
    "high": EffortLevel.HIGH,
    "max": EffortLevel.MAX,
}

# GROUP_MAP — regras de injecao de /clear, /model, /effort por grupo de comando.
# Centralizado aqui para eliminar hardcode por botao (WORKFLOW-APP-RULES.md).
GROUP_MAP: dict[str, dict[str, Any]] = {
    "loop": {
        "model": ModelName.OPUS,
        "effort": EffortLevel.HIGH,
    },
    # Lane Kimi do /loop (queue-btn-kimi-loop): comandos /kimi-loop:* sao
    # QUICKSTART-mecanicos (ai-forge/rules/weak-llm-pipeline-rules.md), entao o
    # fallback Claude roda em sonnet/medium — espelha o precedente do blog
    # stockpile. Quando o seletor Kimi esta ativo, o roteamento via
    # kimi_whitelist.py ignora model/effort (Kimi CLI).
    "kimi_loop": {
        "model": ModelName.SONNET,
        "effort": EffortLevel.STANDARD,
    },
    "daily_loop": {
        "model": ModelName.SONNET,
        "effort": EffortLevel.STANDARD,
    },
    "daily": {
        "model": ModelName.SONNET,
        "effort": EffortLevel.STANDARD,  # first step (scan) is sonnet/standard
    },
    "cmd_single": {
        "model": ModelName.OPUS,
        "effort": EffortLevel.HIGH,
    },
    "study": {
        "model": ModelName.OPUS,
        "effort": EffortLevel.HIGH,
    },
    "legacy_to_dcp": {
        "model": ModelName.SONNET,
        "effort": EffortLevel.STANDARD,
    },
    "rocksmash_review": {
        "model": ModelName.OPUS,
        "effort": EffortLevel.HIGH,
    },
    # Pipeline multibackend (queue-btn-multibackend): vincula uma pagina
    # estatica HTML/CSS/JS ja hospedada (Hostinger) ao backend central
    # multi-tenant, adiciona login funcional (Zero Orfaos) e deixa em
    # producao. Os 6 subcomandos /multibackend:* sao todos opus/high (cada
    # um e um passo de pipeline que comunica via scan-report.json em disco,
    # nao via contexto de conversa), entao _inject_clears emite o triplet
    # completo so no primeiro e um /clear isolado antes dos demais.
    "multibackend": {
        "model": ModelName.OPUS,
        "effort": EffortLevel.HIGH,
    },
    # NOTA: o pipeline /book-legacy NAO entra no GROUP_MAP porque cada
    # subcomando tem model/effort proprio (3 tiers do Bloco I-34). GROUP_MAP
    # so expressa um par model/effort unico por grupo. O builder
    # _enqueue_book_legacy resolve os tiers per-subcomando internamente.
}


def _build_prep_specs(group: str, start_position: int = 1) -> list[CommandSpec]:
    """Retorna /clear, /model, /effort como CommandSpecs conforme GROUP_MAP."""
    cfg = GROUP_MAP.get(group, {})
    model = cfg.get("model", ModelName.OPUS)
    effort = cfg.get("effort", EffortLevel.HIGH)
    model_str = model.value.lower()
    effort_str = effort.value
    return [
        CommandSpec(name="/clear", model=model, interaction_type=InteractionType.AUTO, position=start_position),
        CommandSpec(name=f"/model {model_str}", model=model, interaction_type=InteractionType.AUTO, position=start_position + 1),
        CommandSpec(name=f"/effort {effort_str}", model=model, interaction_type=InteractionType.AUTO, position=start_position + 2),
    ]


@dataclass(frozen=True)
class DcpBuildContext:
    """Result of `_dcp_build_preflight` when all 6 gates pass.

    `delivery` is forward-referenced (file has `from __future__ import
    annotations`) to keep `workflow_app.models.delivery.Delivery` import
    lazy, matching how `_on_dcp_build_pipeline_clicked` resolves it.
    """

    cm_id: str
    module_state: str
    regenerate: bool
    wbs_root: Path
    delivery: "Delivery"  # noqa: F821 — resolved lazily via __future__ annotations


GOVERNANCE_COMMANDS: tuple[str, ...] = (
    "/pipeline:run-scorecard --cadence",
    "/pipeline:collect-lessons --cadence",
    "/memory:record-run",
    "/memory:retrieve-patterns",
    "/memory:decay-and-prune",
    "/meta:analyze-search-stall",
    "/meta:propose-mechanism",
    "/cmd:backlog-from-lessons",
    "/cmd:gap-to-task --from-backlog",
    "/cmd:tabu-guard",
    "/cmd:experiment",
    "/cmd:accept-or-revert",
    "/meta:inject-mechanism-sandbox",
    "/cmd:execute-gap-tasks",
    "/cmd:gap-review",
)

GOVERNANCE_WRITE_TARGETS: tuple[str, ...] = (
    "docs_root/_pipeline-research/",
    "scheduled-updates/governance-dry-run/",
    "scheduled-updates/BACKLOG-COMMAND-MUTATIONS.md",
    "scheduled-updates/TASK-INDEX.md",
    ".claude/commands/**/*.md",
    "ai-forge/templates/**/*.md",
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


@dataclass(frozen=True)
class RenderedInsertion:
    """Resultado PURO de `CommandQueueWidget.render_for_llm`.

    Contrato (ver blacksmith/brainstorm-mcp/06-15-insertions-subtab-llm-routing.md
    §6/§8.1 e ai-forge/rules/main-llm-publish.md):
    - `text` setado e `abort_reason is None`  -> publicar `text` (Enter conforme o caller).
    - `text is None` e `abort_reason` setado  -> caller emite toast e nao publica (Zero Silencio).
    - exclusividade: nunca `text` e `abort_reason` ambos setados; com payload nao-vazio
      nunca os dois `None`.
    - `helper_pulse` so e True em `mode="dispatch"` para `/model`//`/effort` (a fila pulsa o
      listener); em `mode="insert"` e SEMPRE False (insercao nao tem ciclo de listener).
    """

    text: str | None
    abort_reason: str | None = None
    helper_pulse: bool = False
    listener_channel: str | None = None


class CommandQueueWidget(QWidget):
    """Right sidebar showing the pipeline command queue."""

    add_command_requested = Signal()
    reorder_requested = Signal(int, int)  # from_pos, to_pos (spec positions / indicator idx)
    save_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandQueueWidget")
        self.setMinimumWidth(456)  # 2×listeners-frame(224) + DualStatusSection spacing(8)
        self.setStyleSheet(
            "background-color: #18181B; border-left: 1px solid #3F3F46;"
        )

        self._items: list[CommandItemWidget] = []
        self._pipeline_manager = None
        self._cli_binary = "clauded"  # Active CLI instance (updated via instance_selected)

        # Pending modal-confirmation Enter (currently used by /effort to
        # auto-dismiss Claude Code's confirmation prompt). Stored so the
        # next dispatch can cancel it — otherwise the late Enter fires
        # into AskUserQuestion menus or other interactive prompts of the
        # next command and selects the default option.
        self._pending_modal_enter_timer: QTimer | None = None

        # Provider derivado (router puro) do ultimo item avaliado no step path.
        # Computado por classify_provider em _on_step_btn_clicked APOS o Worker
        # axis (invariante 2). Defense-in-depth: fica disponivel internamente
        # para o botao unico (task 005) e o dispatch (task 006); nesta etapa
        # NAO governa roteamento nem UI (Zero Estados Indefinidos: inicia None).
        self._last_classified_provider: Provider | None = None

        # Tracks whether the LAST workspace dispatch was /clear. The next
        # blue-arrow Kimi dispatch reads this to add 2s extra delay before
        # Enter (Kimi takes longer to render its prompt right after a clear
        # because the whole TUI is being repainted from scratch).
        self._last_workspace_dispatch_was_clear: bool = False

        # task 006 — condicao de falha 4 (terminal alvo nao pronto -> abortar
        # com feedback visivel). Espelha a disponibilidade do T3 (terminal-
        # codex-output) emitida por main_window via codex_availability_changed.
        # Inicia True (otimista): o gate so aborta o dispatch Codex/T3 quando a
        # janela ja sinalizou explicitamente que o terminal Codex sumiu/nao esta
        # pronto, preservando o comportamento legado quando nenhum sinal chegou.
        self._codex_t3_available: bool = True

        # Onda 4: SPECIFIC-FLOW.json path of the currently-loaded DCP queue,
        # set by `_on_dcp_specific_flow_clicked` after a successful load.
        # When set, [Remove] persists the deleted command name to
        # overrides.skipped[] in this file so the next reload (or regen
        # without --reset-overrides) honors the deletion. Cleared by any
        # other pipeline_ready emission to avoid leaking DCP context into
        # legacy templates.
        self._current_dcp_flow_path: Path | None = None

        # DCP B-dcp pipeline context awaiting the final local-action
        # (`dcp-load-specific-flow`) at queue position 6. Armed by
        # `_on_dcp_build_pipeline_clicked` after preflight succeeds and the
        # 5-slash + 1-local-action specs are enqueued. Consumed by
        # `_handle_dcp_load_specific_flow` (Task 13) to locate the freshly
        # regenerated SPECIFIC-FLOW.json and emit it as the next pipeline.
        self._pending_dcp_load_ctx: Optional[DcpBuildContext] = None

        # task-019 (TASK-018): UI FAIL-CLOSED. Set to ctx.cm_id by
        # `_derive_queue_from_matrix_inmemory` when DCP-COMMAND-MATRIX.json
        # exists but fails strict validation. Both `_handle_dcp_load_specific_flow`
        # (DCP Execute) and `_on_dcp_specific_flow_clicked` (Specific Flow button)
        # check this attribute to abort instead of falling back to SPECIFIC-FLOW.json.
        # Cleared on any successful matrix derivation OR after the caller consumes
        # the abort signal (so a subsequent retry on a fixed matrix rearms cleanly).
        self._matrix_strict_failed_for_ctx: Optional[str] = None

        self._setup_ui()
        self._connect_signals()

        # Register the in-process local action consumed at queue position 6
        # of the B-dcp pipeline. The callable is the bound method
        # `_handle_dcp_load_specific_flow` (implemented by Task 13).
        # `register_local_action` overwrites any prior registration, so
        # re-instantiating the widget is safe.
        from workflow_app.command_queue.local_actions import register_local_action
        register_local_action(
            "dcp-load-specific-flow",
            self._handle_dcp_load_specific_flow,
        )

    # ─────────────────────────────────────────────── Attachment proxy ─── #

    class _AttachmentProxy:
        """Proxy que implementa a interface pill para DoublePhaseButton."""

        def __init__(self, widget, loader):
            self._widget = widget
            self._loader = loader

        def has_attachment(self):
            from workflow_app.config.app_state import app_state
            return app_state.has_config and app_state.config is not None

        def generate_from_attachment(self):
            self._loader()

    def _on_daily_command_ready(self, command_line: str) -> None:
        """Expand /daily <args> into individual sub-commands with model/effort transitions.

        Daily pipeline: no /clear between steps (context shared via _DAILY-*.md).
        Model/effort transitions emitted without /clear to preserve conversation context.

        Pipeline assignments:
          scan     — sonnet/standard  (mechanical data collection, 2-min target)
          plan     — opus/high        (judgment-intensive: scope, intent, acceptance criteria)
          do       — sonnet/high      (constrained implementation following the plan)
          validate — sonnet/standard  (mechanical: build/lint/test command execution)
          review   — sonnet/standard  (synthesis of existing artefacts, commit message)
        """
        prefix = "/daily"
        args = command_line[len(prefix):].strip() if command_line.startswith(prefix) else ""

        scan_name = f"/daily:scan {args}".rstrip() if args else "/daily:scan"
        plan_name = f"/daily:plan {args}".rstrip() if args else "/daily:plan"

        _AT = InteractionType.AUTO
        _S = ModelName.SONNET
        _O = ModelName.OPUS

        specs: list[CommandSpec] = [
            # header inicial — scan: sonnet/standard (Regra 3.4)
            CommandSpec(name="/clear",           model=_S, interaction_type=_AT, position=1),
            CommandSpec(name="/model sonnet",    model=_S, interaction_type=_AT, position=2),
            CommandSpec(name="/effort standard", model=_S, interaction_type=_AT, position=3),
            CommandSpec(scan_name, model=_S, interaction_type=_AT, effort=EffortLevel.STANDARD, position=4),
            # transicao sonnet/standard → opus/high (plan)
            CommandSpec(name="/model opus",      model=_O, interaction_type=_AT, position=5),
            CommandSpec(name="/effort high",     model=_O, interaction_type=_AT, position=6),
            CommandSpec(plan_name, model=_O, interaction_type=_AT, effort=EffortLevel.HIGH, position=7),
            # transicao opus/high → sonnet/high (do — so model muda, effort continua high)
            CommandSpec(name="/model sonnet",    model=_S, interaction_type=_AT, position=8),
            CommandSpec("/daily:do",       model=_S, interaction_type=_AT, effort=EffortLevel.HIGH,     position=9),
            # transicao sonnet/high → sonnet/standard (validate — so effort muda)
            CommandSpec(name="/effort standard", model=_S, interaction_type=_AT, position=10),
            CommandSpec("/daily:validate", model=_S, interaction_type=_AT, effort=EffortLevel.STANDARD, position=11),
            # sem transicao (review: sonnet/standard = mesmo que validate)
            CommandSpec("/daily:review",   model=_S, interaction_type=_AT, effort=EffortLevel.STANDARD, position=12),
        ]

        self._template_label.setText("  \U0001f4cb  Daily")
        self._template_label.setVisible(True)
        self._maybe_auto_save("Daily")
        signal_bus.pipeline_ready.emit(specs)

    def _on_daily_loop_command_ready(self, command_line: str) -> None:
        dl_cfg = GROUP_MAP.get("daily_loop", {})
        dl_model = dl_cfg.get("model", ModelName.SONNET)
        dl_effort = dl_cfg.get("effort", EffortLevel.STANDARD)
        specs = _build_prep_specs("daily_loop", start_position=1)
        specs.append(
            CommandSpec(
                name=command_line,
                model=dl_model,
                interaction_type=InteractionType.INTERACTIVE,
                config_path="",
                effort=dl_effort,
                position=len(specs) + 1,
            )
        )
        self.load_pipeline(specs)
        self._template_label.setText("  \U0001f4cb  Daily Loop")
        self._template_label.setVisible(True)
        self._maybe_auto_save("Daily Loop")

    def _candidate_md_roots(self, path_arg: str) -> list[Path]:
        """Candidatos de base_dir para resolver path_arg relativo de um .md.

        Ordem: project_dir carregado -> cwd -> raiz do SystemForge detectada
        a partir de __file__ (mesmo ancora usada pela terminal subprocess
        do output_panel, onde Claude Code de fato executa).
        Cobre o caso onde workflow-app foi lancado de /home/pedro mas o spec
        vive em /home/pedro/Repositorios/<repo>/blacksmith/...
        """
        from workflow_app.config.app_state import app_state

        p = Path(path_arg)
        if p.is_absolute():
            return [p]

        candidates: list[Path] = []
        seen: set[Path] = set()

        def add(base: Path | None) -> None:
            if base is None:
                return
            try:
                resolved = (base / p).resolve()
            except OSError:
                return
            if resolved not in seen:
                seen.add(resolved)
                candidates.append(resolved)

        if app_state.has_config and app_state.config is not None:
            add(app_state.config.project_dir)

        add(Path.cwd())

        sf_root = self._find_systemforge_root()
        add(sf_root)

        return candidates

    @staticmethod
    def _find_systemforge_root() -> Path | None:
        """Anda para cima a partir de __file__ ate achar marcador SystemForge
        (.claude/commands/ + ai-forge/ + CLAUDE.md). Mesma heuristica de
        output_panel._find_systemforge_root."""
        candidate = Path(__file__).resolve().parent
        while candidate != candidate.parent:
            if (
                (candidate / ".claude" / "commands").is_dir()
                and (candidate / "ai-forge").is_dir()
                and (candidate / "CLAUDE.md").is_file()
            ):
                return candidate
            candidate = candidate.parent
        return None

    def _resolve_relative_md(self, path_arg: str) -> Path | None:
        """Primeiro candidato existente em _candidate_md_roots; None se nenhum."""
        for c in self._candidate_md_roots(path_arg):
            if c.exists():
                return c
        return None

    @classmethod
    def _existing_loop_slug_from_path(cls, path_arg: str) -> str | None:
        """Detecta IDENTIDADE de loop ja persistido em disco.

        Delega para `ai-forge/scripts/normalize_loop_name.py` (single
        source of truth). Retorna o slug preservado quando o helper
        canonico classifica o path como re-entry; retorna None caso
        contrario.

        Usado pelo collision guard em `_on_loop_command_ready` ANTES de
        invocar o normalizador completo, para detectar conflito entre
        `--name` explicito do usuario e loop existente em disco.
        """
        try:
            result = cls._invoke_loop_normalizer(path=path_arg)
        except Exception:
            return None
        if result is None or not result.get("was_re_entry"):
            return None
        return result.get("slug")

    @classmethod
    def _derive_loop_slug_from_path(cls, path_arg: str) -> str:
        """Fallback determinista quando NAO ha `--name` explicito.

        Delega para `ai-forge/scripts/normalize_loop_name.py`, que
        implementa as 4 regras canonicas em sintonia com o markdown
        spec `/loop:create-structure`:
          1. Re-entry (source.md + _LOOP-CONFIG.json em disco): preserva
             slug do parent dir AS-IS (forward-only policy).
          2. Fresh path: aplica mm-dd + kebab + strip stopwords pt-BR
             + cap 46 chars conforme regex `^\\d{2}-\\d{2}-[a-z0-9]...$`.

        Single source of truth ELIMINA drift entre widget e markdown
        spec (per adversarial review com /mcp:codex 2026-05-14).

        Fallback de seguranca: se subprocess falhar (script ausente,
        erro inesperado), cai em `Path.stem` para evitar travamento da
        fila. Mesmo nesse caso pior, `/loop:create-structure` aplica sua
        propria normalizacao em runtime.
        """
        try:
            result = cls._invoke_loop_normalizer(path=path_arg)
        except Exception:
            return Path(path_arg).stem
        if result is None or "slug" not in result:
            return Path(path_arg).stem
        return result["slug"]

    @classmethod
    def _canonical_loop_slug(
        cls,
        name_arg: str | None,
        path_arg: str,
    ) -> str | None:
        """Computa slug FINAL canonico para enfileirar todas as fases do /loop.

        Garante que `/loop:create-structure`, `/loop:individual-analysis`,
        `/loop:integration`, `/loop:review`, `/loop:integrated-architecture`,
        `/loop:workflow-app` (e `/loop:mark-type`, `/loop:check-tasks-and-cmd`
        em --both) recebam EXATAMENTE o mesmo slug final que
        `/loop:create-structure` materializara em disco (via `--name` ou
        `--loop-slug`). Sem isso, fases 2..N apontariam para diretorio
        inexistente quando o helper normaliza `foo` -> `05-14-foo`.

        Retorna None se o helper falhar — caller deve abortar com toast.
        """
        try:
            result = cls._invoke_loop_normalizer(name=name_arg, path=path_arg)
        except Exception:
            return None
        if result is None or "slug" not in result:
            return None
        return result["slug"]

    @classmethod
    def _invoke_loop_normalizer(
        cls,
        name: str | None = None,
        path: str | None = None,
    ) -> dict | None:
        """Wrapper sobre `ai-forge/scripts/normalize_loop_name.py`.

        Subprocess intencional (em vez de import direto) por 3 razoes:
          - workflow-app vive em submodulo separado de ai-forge/scripts;
          - mantem interface uniforme entre widget (Python) e markdown
            spec (Bash) — ambos chamam via CLI;
          - latencia ~100ms aceitavel para flow de click no botao.

        Path resolution: paths relativos sao tentados primeiro contra
        candidate_md_roots (cwd, project_dir, repo root) do widget. Sem
        essa pre-resolucao, o helper enxergaria apenas cwd e poderia
        falhar em detectar re-entry/colisao quando o usuario digita
        path relativo a outro working dir (per codex review 2026-05-14).

        Retorna dict do JSON parseado em sucesso; None em qualquer falha
        (script ausente, exit non-zero, JSON mal-formado, timeout).
        """
        import json as _json
        import subprocess as _subprocess

        repo_root = cls._find_systemforge_root_for_class()
        if repo_root is None:
            return None
        script = repo_root / "ai-forge" / "scripts" / "normalize_loop_name.py"
        if not script.exists():
            return None

        resolved_path: str | None = path
        if path:
            try:
                p = Path(path).expanduser()
                if not p.is_absolute():
                    for candidate in cls._candidate_md_roots_static(path, repo_root):
                        if candidate.exists():
                            resolved_path = str(candidate)
                            break
            except (OSError, RuntimeError):
                resolved_path = path

        argv = [sys.executable, str(script), "--json"]
        if name:
            argv.extend(["--name", name])
        if resolved_path:
            argv.extend(["--path", resolved_path])

        try:
            proc = _subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
                cwd=str(repo_root),
            )
        except (OSError, _subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        try:
            return _json.loads(proc.stdout)
        except _json.JSONDecodeError:
            return None

    @staticmethod
    def _candidate_md_roots_static(path_arg: str, repo_root: Path) -> list[Path]:
        """Versao classmethod-friendly de `_candidate_md_roots`.

        Tenta resolver `path_arg` relativo contra: cwd, project_dir (se
        config carregada), e repo_root. Permite que `_invoke_loop_normalizer`
        funcione sem instancia de widget (chamada em classmethod).
        """
        try:
            from workflow_app.config.app_state import app_state
        except ImportError:
            app_state = None  # type: ignore[assignment]

        raw = Path(path_arg).expanduser()
        if raw.is_absolute():
            return [raw]

        roots: list[Path] = []
        try:
            roots.append(Path.cwd() / raw)
        except (OSError, RuntimeError):
            pass
        if app_state is not None and getattr(app_state, "has_config", False):
            cfg = getattr(app_state, "config", None)
            if cfg is not None and getattr(cfg, "project_dir", None):
                roots.append(Path(cfg.project_dir) / raw)
        roots.append(repo_root / raw)
        return roots

    @staticmethod
    def _find_systemforge_root_for_class() -> Path | None:
        """Versao class-level de _find_systemforge_root (sem self)."""
        candidate = Path(__file__).resolve().parent
        while candidate != candidate.parent:
            if (
                (candidate / ".claude" / "commands").is_dir()
                and (candidate / "ai-forge").is_dir()
                and (candidate / "CLAUDE.md").is_file()
            ):
                return candidate
            candidate = candidate.parent
        return None

    def _on_unified_command_ready(self, command_line: str) -> None:
        """Handler unico para queue-btn-loop, queue-btn-daily-loop e queue-btn-cmd-single.

        Delega para o processamento especifico de cada comando, garantindo
        que todos usem o mesmo DoublePhaseArgumentDialog refatorado.
        """
        tokens = command_line.strip().split()
        if not tokens:
            return

        base_cmd = tokens[0]
        if base_cmd == "/loop":
            self._on_loop_command_ready(command_line)
        elif base_cmd == "/kimi-loop":
            self._on_kimi_loop_command_ready(command_line)
        elif base_cmd == "/daily-loop":
            self._on_daily_loop_command_ready(command_line)
        else:
            # Fallback generico: adiciona como comando simples
            spec = CommandSpec(
                name=command_line,
                model=ModelName.OPUS,
                interaction_type=InteractionType.INTERACTIVE,
                position=len(self._items) + 1,
            )
            self.add_command(spec)
            self._template_label.setText(f"  \U0001f4cb  {base_cmd}")
            self._template_label.setVisible(True)
            self._maybe_auto_save(base_cmd)

    def _on_loop_command_ready(self, command_line: str) -> None:
        """Expand `/loop --{mode} <path.md> [--name <slug>]` into its
        canonical sub-command sequence per `.claude/commands/loop.md` FASE 2.

        Antes (legado): empilhava o comando centralizador como UMA entrada
        unica na fila — o que forcava o orquestrador `/loop` a sequenciar as
        sub-fases dentro de uma unica conversa, perdendo o pareamento canonico
        `/clear` + `/model` + `/effort` entre fases.

        Agora: faz o splice em runtime, materializando as 5 (--task/--cmd),
        7 (--both) ou sub-pipeline reduzida (--cmd-single) sub-fases como
        especs separadas, todas com OPUS/HIGH e `/clear` entre elas, conforme
        `ai-forge/workflow-rules/WORKFLOW-APP-RULES.md`.
        """
        tokens = command_line.strip().split()
        mode = None
        path_arg = ""
        name_arg = ""
        certain = False

        if len(tokens) >= 2 and tokens[0] == "/loop":
            i = 1
            while i < len(tokens):
                t = tokens[i]
                if t in ("--task", "--cmd", "--cmd-single", "--both"):
                    mode = t
                    if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                        path_arg = tokens[i + 1]
                        i += 2
                        continue
                elif t == "--name" and i + 1 < len(tokens):
                    name_arg = tokens[i + 1]
                    i += 2
                    continue
                elif t == "--certain":
                    # cmd-single "kimi certain": forca --force no par kimi-pair.
                    certain = True
                    i += 1
                    continue
                i += 1

        if mode is None or not path_arg:
            spec = CommandSpec(
                name=command_line,
                model=ModelName.OPUS,
                interaction_type=InteractionType.INTERACTIVE,
                position=len(self._items) + 1,
            )
            self.add_command(spec)
            self._template_label.setText("  \U0001f4cb  Loop")
            self._template_label.setVisible(True)
            self._maybe_auto_save("Loop")
            return

        # Collision guard (per codex adversarial review 2026-05-14):
        # quando o usuario fornece --name explicito MAS o path aponta para
        # um loop ja persistido em disco com slug DIFERENTE, abortar com
        # toast claro. Criar diretorio paralelo nessa situacao orfanaria
        # o loop existente silenciosamente.
        existing_slug = self._existing_loop_slug_from_path(path_arg)
        if name_arg and existing_slug and name_arg != existing_slug:
            signal_bus.toast_requested.emit(
                f"Conflito: --name '{name_arg}' divergente do loop existente "
                f"'{existing_slug}' em {path_arg}. Para reutilizar, omita "
                f"--name ou use --name {existing_slug}. Para criar loop "
                f"novo, aponte para um source.md fora desse diretorio.",
                "error",
            )
            return

        # Slug FINAL canonico (post-normalizacao mm-dd + kebab + stopwords).
        # Delega para ai-forge/scripts/normalize_loop_name.py — single source
        # of truth compartilhada com `/loop:create-structure` markdown spec.
        # Sem isso, fases 2..N enfileiradas com slug pre-normalizacao
        # apontariam para diretorio inexistente em runtime (bug e2e
        # identificado pelo codex review).
        slug = self._canonical_loop_slug(name_arg or None, path_arg)
        if slug is None:
            signal_bus.toast_requested.emit(
                f"Erro ao normalizar nome do loop. Verifique "
                f"ai-forge/scripts/normalize_loop_name.py e tente novamente "
                f"com --name explicito.",
                "error",
            )
            return

        loop_cfg = GROUP_MAP.get("loop", {})
        loop_model = loop_cfg.get("model", ModelName.OPUS)
        loop_effort = loop_cfg.get("effort", EffortLevel.HIGH)

        if mode == "--cmd-single":
            from workflow_app.config.app_state import app_state

            md_path = self._resolve_relative_md(path_arg)
            if md_path is None or not md_path.exists():
                tried = self._candidate_md_roots(path_arg)
                tried_str = "\n  - ".join(str(p) for p in tried) or path_arg
                signal_bus.toast_requested.emit(
                    f"Erro ao ler {path_arg}: arquivo nao encontrado em:\n  - {tried_str}",
                    "error",
                )
                return
            try:
                content = md_path.read_text(encoding="utf-8")
            except OSError as exc:
                signal_bus.toast_requested.emit(
                    f"Erro ao ler {md_path}: {exc}", "error"
                )
                return

            base_dir = md_path.parent
            for parent in (md_path.parent, *md_path.parent.parents):
                if (parent / ".claude").is_dir():
                    base_dir = parent
                    break
            if app_state.has_config and app_state.config is not None:
                base_dir = app_state.config.project_dir

            cmd_target_slash = ""
            fm_match = re.search(r"^cmd_target:\s*([^\r\n]+)", content, re.MULTILINE)
            if fm_match:
                cmd_target_slash = fm_match.group(1).strip()
            if not cmd_target_slash:
                heading_match = re.search(r"^#\s+(/[^\s\n]+)", content, re.MULTILINE)
                if heading_match:
                    cmd_target_slash = heading_match.group(1).strip()
            if not cmd_target_slash:
                signal_bus.toast_requested.emit(
                    f"MD {md_path.name} sem heading canonico (# /grupo:nome) "
                    "nem cmd_target no header. Abortando.",
                    "error",
                )
                return

            target_disk = cmd_target_slash.lstrip("/").replace(":", "/")
            cmd_file_path = base_dir / ".claude" / "commands" / f"{target_disk}.md"
            cmd_action = "update" if cmd_file_path.exists() else "create"

            md_path_str = str(md_path)
            kimi_slug = cmd_target_slash.lstrip("/")
            report_path = f"blacksmith/{kimi_slug}-kimi-pair-report.md"

            def _clear_spec(position: int) -> CommandSpec:
                # Boundary entre grupos independentes: apenas /clear. /model e
                # /effort sao suprimidos porque TODOS os grupos cmd_single
                # rodam em opus/high — re-emiti-los viola a anti-redundancia
                # (ai-forge/rules/workflow-app-command-lists.md §3.1).
                return CommandSpec(
                    name="/clear",
                    model=loop_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=loop_effort,
                    position=position,
                )

            def _cmd_spec(name: str) -> CommandSpec:
                return CommandSpec(
                    name=name,
                    model=loop_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=loop_effort,
                    position=len(specs) + 1,
                )

            # "kimi certain" forca --force nas duas pontas do par kimi-pair
            # (pula o gate macro de elegibilidade; PROIBIDA continua barrando
            # individualmente, ver FASE 0.3 de kimi-pair-analyse/execute).
            force = "--force " if certain else ""

            # Grupo 1: /clear /model opus /effort high (estado conhecido na
            # partida — §3.4). Grupos seguintes herdam model/effort e emitem
            # apenas /clear (§3.1).
            specs = _build_prep_specs("cmd_single", start_position=1)
            specs.append(_cmd_spec(f"/cmd:{cmd_action} {md_path_str}"))
            specs.append(_clear_spec(len(specs) + 1))
            specs.append(_cmd_spec(f"/cmd:review {cmd_target_slash} {md_path_str}"))
            specs.append(_clear_spec(len(specs) + 1))
            # Par kimi-pair compartilha contexto: execute consome o relatorio
            # produzido por analyse, entao NAO ha /clear entre eles (§3.2/§3.3).
            specs.append(_cmd_spec(f"/cmd:kimi-pair-analyse {force}{cmd_target_slash}"))
            specs.append(_cmd_spec(f"/cmd:kimi-pair-execute {force}{report_path}"))
            specs.append(_clear_spec(len(specs) + 1))
            specs.append(_cmd_spec("/cmd:readme-upd"))
            label = f"  \U0001f4cb  Loop --cmd-single: {cmd_target_slash} ({cmd_action})"
            auto_save_label = f"Loop --cmd-single {cmd_target_slash}"
        else:
            mode_flag = mode
            if mode == "--task":
                sub_names = [
                    f"/loop:create-structure {mode_flag} {path_arg} --name {slug}",
                    f"/loop:individual-analysis --name {slug}",
                    f"/loop:integration --name {slug}",
                    f"/loop:review --name {slug}",
                    f"/loop:integrated-architecture --loop-slug {slug}",
                    f"/loop:workflow-app --name {slug}",
                ]
            elif mode == "--cmd":
                sub_names = [
                    f"/loop:create-structure {mode_flag} {path_arg} --name {slug}",
                    f"/loop:individual-analysis {mode_flag} --name {slug}",
                    f"/loop:integration {mode_flag} --name {slug}",
                    f"/loop:review {mode_flag} --name {slug}",
                    f"/loop:integrated-architecture --loop-slug {slug}",
                    f"/loop:workflow-app {mode_flag} --name {slug}",
                ]
            else:  # --both
                sub_names = [
                    f"/loop:create-structure {mode_flag} {path_arg} --name {slug}",
                    f"/loop:individual-analysis {mode_flag} --name {slug}",
                    f"/loop:integration {mode_flag} --name {slug}",
                    f"/loop:review {mode_flag} --name {slug}",
                    f"/loop:integrated-architecture --loop-slug {slug}",
                    f"/loop:mark-type --name {slug}",
                    f"/loop:check-tasks-and-cmd --name {slug}",
                    f"/loop:workflow-app {mode_flag} --name {slug}",
                ]

            specs: list[CommandSpec] = []
            specs.extend(_build_prep_specs("loop", start_position=1))
            specs.append(
                CommandSpec(
                    name=sub_names[0],
                    model=loop_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=loop_effort,
                    position=len(specs) + 1,
                )
            )
            for sub in sub_names[1:]:
                # Boundary entre fases independentes: apenas /clear. /model e
                # /effort sao SUPRIMIDOS porque TODAS as fases do loop rodam em
                # opus/high (GROUP_MAP["loop"]) — re-emiti-los viola a politica
                # anti-redundancia (ai-forge/rules/workflow-app-command-lists.md
                # secao 3.1, REGRA INVIOLAVEL). Espelha o branch --cmd-single,
                # que ja faz isso certo via _clear_spec. O primeiro grupo (acima)
                # ja recebeu /clear /model /effort completo (secao 3.4).
                specs.append(
                    CommandSpec(
                        name="/clear",
                        model=loop_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=loop_effort,
                        position=len(specs) + 1,
                    )
                )
                specs.append(
                    CommandSpec(
                        name=sub,
                        model=loop_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=loop_effort,
                        position=len(specs) + 1,
                    )
                )

            label = f"  \U0001f4cb  Loop {mode}: {slug} ({len(sub_names)} fases)"
            auto_save_label = f"Loop {mode} {slug}"

        self._template_label.setText(label)
        self._template_label.setVisible(True)
        self._maybe_auto_save(auto_save_label)
        signal_bus.pipeline_ready.emit(specs)
        signal_bus.toast_requested.emit(
            f"Fila renderizada: {len(specs)} comandos.", "success"
        )

    def _on_kimi_loop_command_ready(self, command_line: str) -> None:
        """Expand `/kimi-loop --{mode} <path.md> [--name <slug>]` na lane Kimi.

        Gemeo de `_on_loop_command_ready` para a familia `/kimi-loop:*`
        (queue-btn-kimi-loop, 2026-06-09): mesmas regras de parse, collision
        guard e slug canonico, mas sub-fases /kimi-loop:* em
        GROUP_MAP["kimi_loop"] (sonnet/medium — weak-llm-pipeline-rules) e
        split init+enumerate (7 fases em --task/--cmd, 9 em --both). Design:
        blacksmith/09-06-llm-dumb-use/KIMI-LOOP-DESIGN.md (D1..D10).

        --cmd-single delega INTEGRAL ao branch /loop (mesma sub-pipeline
        /cmd:create|update -> /cmd:review -> kimi-pair -> readme-upd), que ja
        e a lane kimi-pair canonica. --rocksmash nao e suportado nesta lane
        (usar /loop --rocksmash).
        """
        tokens = command_line.strip().split()
        mode = None
        path_arg = ""
        name_arg = ""

        if len(tokens) >= 2 and tokens[0] == "/kimi-loop":
            i = 1
            while i < len(tokens):
                t = tokens[i]
                if t in ("--task", "--cmd", "--cmd-single", "--both"):
                    mode = t
                    if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                        path_arg = tokens[i + 1]
                        i += 2
                        continue
                elif t == "--name" and i + 1 < len(tokens):
                    name_arg = tokens[i + 1]
                    i += 2
                    continue
                i += 1

        if mode == "--cmd-single":
            # Delegacao integral: a sub-pipeline cmd-single e compartilhada
            # com /loop (ja e a lane kimi-pair). Reescreve apenas o head.
            self._on_loop_command_ready(
                command_line.replace("/kimi-loop", "/loop", 1)
            )
            return

        if mode is None or not path_arg:
            spec = CommandSpec(
                name=command_line,
                model=ModelName.SONNET,
                interaction_type=InteractionType.INTERACTIVE,
                position=len(self._items) + 1,
            )
            self.add_command(spec)
            self._template_label.setText("  \U0001f4cb  Kimi-Loop")
            self._template_label.setVisible(True)
            self._maybe_auto_save("Kimi-Loop")
            return

        # Collision guard + slug canonico: mesmos helpers do /loop (D1 do
        # design — as duas lanes compartilham blacksmith/loop-archives/).
        existing_slug = self._existing_loop_slug_from_path(path_arg)
        if name_arg and existing_slug and name_arg != existing_slug:
            signal_bus.toast_requested.emit(
                f"Conflito: --name '{name_arg}' divergente do loop existente "
                f"'{existing_slug}' em {path_arg}. Para reutilizar, omita "
                f"--name ou use --name {existing_slug}. Para criar loop "
                f"novo, aponte para um source.md fora desse diretorio.",
                "error",
            )
            return

        slug = self._canonical_loop_slug(name_arg or None, path_arg)
        if slug is None:
            signal_bus.toast_requested.emit(
                "Erro ao normalizar nome do loop. Verifique "
                "ai-forge/scripts/normalize_loop_name.py e tente novamente "
                "com --name explicito.",
                "error",
            )
            return

        kimi_cfg = GROUP_MAP.get("kimi_loop", {})
        kimi_model = kimi_cfg.get("model", ModelName.SONNET)
        kimi_effort = kimi_cfg.get("effort", EffortLevel.STANDARD)

        mode_flag = mode
        if mode == "--task":
            sub_names = [
                f"/kimi-loop:init {mode_flag} {path_arg} --name {slug}",
                f"/kimi-loop:enumerate --name {slug}",
                f"/kimi-loop:individual-analysis --name {slug}",
                f"/kimi-loop:integration --name {slug}",
                f"/kimi-loop:review --name {slug}",
                f"/kimi-loop:integrated-architecture --loop-slug {slug}",
                f"/kimi-loop:workflow-app --name {slug}",
            ]
        elif mode == "--cmd":
            sub_names = [
                f"/kimi-loop:init {mode_flag} {path_arg} --name {slug}",
                f"/kimi-loop:enumerate {mode_flag} --name {slug}",
                f"/kimi-loop:individual-analysis {mode_flag} --name {slug}",
                f"/kimi-loop:integration {mode_flag} --name {slug}",
                f"/kimi-loop:review {mode_flag} --name {slug}",
                f"/kimi-loop:integrated-architecture --loop-slug {slug}",
                f"/kimi-loop:workflow-app {mode_flag} --name {slug}",
            ]
        else:  # --both
            sub_names = [
                f"/kimi-loop:init {mode_flag} {path_arg} --name {slug}",
                f"/kimi-loop:enumerate {mode_flag} --name {slug}",
                f"/kimi-loop:individual-analysis {mode_flag} --name {slug}",
                f"/kimi-loop:integration {mode_flag} --name {slug}",
                f"/kimi-loop:review {mode_flag} --name {slug}",
                f"/kimi-loop:integrated-architecture --loop-slug {slug}",
                f"/kimi-loop:mark-type --name {slug}",
                f"/kimi-loop:check-tasks-and-cmd --name {slug}",
                f"/kimi-loop:workflow-app {mode_flag} --name {slug}",
            ]

        specs: list[CommandSpec] = []
        specs.extend(_build_prep_specs("kimi_loop", start_position=1))
        specs.append(
            CommandSpec(
                name=sub_names[0],
                model=kimi_model,
                interaction_type=InteractionType.AUTO,
                config_path="",
                effort=kimi_effort,
                position=len(specs) + 1,
            )
        )
        for sub in sub_names[1:]:
            # Boundary entre fases independentes: apenas /clear. /model e
            # /effort sao SUPRIMIDOS porque TODAS as fases rodam em
            # sonnet/medium (GROUP_MAP["kimi_loop"]) — anti-redundancia
            # (ai-forge/rules/workflow-app-command-lists.md secao 3.1).
            specs.append(
                CommandSpec(
                    name="/clear",
                    model=kimi_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=kimi_effort,
                    position=len(specs) + 1,
                )
            )
            specs.append(
                CommandSpec(
                    name=sub,
                    model=kimi_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=kimi_effort,
                    position=len(specs) + 1,
                )
            )

        label = f"  \U0001f4cb  Kimi-Loop {mode}: {slug} ({len(sub_names)} fases)"
        self._template_label.setText(label)
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"Kimi-Loop {mode} {slug}")
        signal_bus.pipeline_ready.emit(specs)
        signal_bus.toast_requested.emit(
            f"Fila renderizada: {len(specs)} comandos.", "success"
        )

    def _on_study_command_ready(self, command_line: str) -> None:
        """Expand `/study "<prompt>" [path.md] [--name <slug>] [--simple|--deep|--heavy] [--loop <path.md>]`
        em sua sequencia canonica de subcomandos por modo, conforme
        `.claude/commands/study.md` FASE 2 (7 fases em --simple, 9 em --deep/--heavy),
        com /clear + /model + /effort entre cada fase (GROUP_MAP["study"] = Opus/HIGH).

        Antes (legado): empilhava o orquestrador /study como UMA entrada unica,
        forcando-o a sequenciar fases dentro de uma unica conversa — sem pareamento
        canonico /clear + /model + /effort entre subcomandos.

        Agora: faz splice em runtime, materializando cada subcomando como spec
        separada na fila, alinhado a forma como queue-btn-loop ja opera.

        --loop <path.md>: preserva contrato Task-023 — anexa
        /tools:auq-interview --optimize <path> como ultimo item (com dedup vs spec
        anterior dentro do mesmo batch).
        """
        try:
            tokens = shlex.split(command_line)
        except ValueError:
            tokens = command_line.strip().split()

        if not tokens or tokens[0] != "/study":
            spec = CommandSpec(
                name=command_line,
                model=ModelName.OPUS,
                interaction_type=InteractionType.INTERACTIVE,
                position=len(self._items) + 1,
            )
            self.add_command(spec)
            self._template_label.setText("  \U0001f4cb  Study")
            self._template_label.setVisible(True)
            self._maybe_auto_save("Study")
            return

        mode = "--simple"
        name_arg = ""
        loop_path: str | None = None
        positional: list[str] = []
        i = 1
        while i < len(tokens):
            t = tokens[i]
            if t in ("--simple", "--deep", "--heavy"):
                mode = t
                i += 1
            elif t == "--name" and i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                name_arg = tokens[i + 1]
                i += 2
            elif t == "--loop" and i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                loop_path = tokens[i + 1]
                i += 2
            else:
                positional.append(t)
                i += 1

        # Fallback canonico (.claude/commands/study.md FASE 1, regra 44):
        # sem posicional + --loop <path> presente -> loop_path vira {input_path}
        # implicito da PRIMEIRA fase (/study:scope[/-decompose]), alem de seguir
        # como write-back destination em /study:publish. Sem isso, scope-decompose
        # roda cego e nao sabe o que estudar.
        if not positional and loop_path:
            positional = [loop_path]

        slug = name_arg
        if not slug:
            for p in positional:
                if p.endswith(".md"):
                    slug = Path(p).stem
                    break
        if not slug and positional:
            first = positional[0]
            slug = re.sub(r"[^a-z0-9]+", "-", first.lower()).strip("-")[:60] or "study"
        if not slug:
            slug = "study"

        positional_tail = " ".join(shlex.quote(p) for p in positional)
        scope_args = f"{positional_tail} --name {slug}".strip() if positional_tail else f"--name {slug}"
        publish_suffix = (
            f" --loop {shlex.quote(loop_path)}" if loop_path else ""
        )

        if mode == "--heavy":
            sub_names = [
                f"/study:scope-decompose {scope_args}",
                f"/study:enumerate --name {slug}",
                f"/study:loop-research --name {slug}",
                f"/study:loop-synth --name {slug}",
                f"/study:consolidate-user --name {slug}",
                f"/study:review-user --name {slug}",
                f"/study:consolidate-tech --name {slug}",
                f"/study:validate --name {slug}",
                f"/study:publish --name {slug}{publish_suffix}",
            ]
        elif mode == "--deep":
            sub_names = [
                f"/study:scope {scope_args}",
                f"/study:research --name {slug}",
                f"/study:triangulate --name {slug}",
                f"/study:write-user --name {slug}",
                f"/study:debate --name {slug}",
                f"/study:review-user --name {slug}",
                f"/study:write-tech --name {slug}",
                f"/study:validate --name {slug}",
                f"/study:publish --name {slug}{publish_suffix}",
            ]
        else:
            mode = "--simple"
            sub_names = [
                f"/study:scope {scope_args}",
                f"/study:research --name {slug}",
                f"/study:write-user --name {slug}",
                f"/study:review-user --name {slug}",
                f"/study:write-tech --name {slug}",
                f"/study:validate --name {slug}",
                f"/study:publish --name {slug}{publish_suffix}",
            ]

        # HARDENING --loop ativo (alinhamento com .claude/commands/study.md FASE 1.7
        # "Hardening contratual no encadeamento de subcomandos"): filtrar 5 subcomandos
        # SKIPADOS quando --loop. Drift entre este filtro e a spec eh BUG; reconciliar.
        # Resolve gap identificado em audit/loop-rocksmash-... (handler nao filtrava).
        if loop_path:
            _LOOP_SKIPPED_PREFIXES = (
                "/study:write-user",
                "/study:write-tech",
                "/study:review-user",
                "/study:consolidate-user",
                "/study:consolidate-tech",
            )
            sub_names = [
                s for s in sub_names
                if not any(s.startswith(p) for p in _LOOP_SKIPPED_PREFIXES)
            ]

        study_cfg = GROUP_MAP.get("study", {})
        study_model = study_cfg.get("model", ModelName.OPUS)
        study_effort = study_cfg.get("effort", EffortLevel.HIGH)

        specs: list[CommandSpec] = []
        specs.extend(_build_prep_specs("study", start_position=1))
        specs.append(
            CommandSpec(
                name=sub_names[0],
                model=study_model,
                interaction_type=InteractionType.AUTO,
                config_path="",
                effort=study_effort,
                position=len(specs) + 1,
            )
        )
        for sub in sub_names[1:]:
            # Boundary entre fases independentes: apenas /clear. /model e /effort
            # sao SUPRIMIDOS porque TODAS as fases do study rodam em opus/high
            # (GROUP_MAP["study"]) — re-emiti-los viola a anti-redundancia
            # (ai-forge/rules/workflow-app-command-lists.md secao 3.1, REGRA
            # INVIOLAVEL). O primeiro grupo ja recebeu prep completo (secao 3.4).
            specs.append(
                CommandSpec(
                    name="/clear",
                    model=study_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=study_effort,
                    position=len(specs) + 1,
                )
            )
            specs.append(
                CommandSpec(
                    name=sub,
                    model=study_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=study_effort,
                    position=len(specs) + 1,
                )
            )

        if loop_path:
            auq_name = f"/tools:auq-interview --optimize {loop_path}"
            if not specs or specs[-1].name != auq_name:
                # Salto LEGITIMO de model/effort (opus/high -> sonnet/standard):
                # aqui as diretivas DEVEM ser reemitidas (secao 4). Mantem o
                # prep completo, diferente do boundary opus/high acima.
                specs.extend(_build_prep_specs("study", start_position=len(specs) + 1))
                specs.append(
                    CommandSpec(
                        name=auq_name,
                        model=ModelName.SONNET,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=EffortLevel.STANDARD,
                        position=len(specs) + 1,
                    )
                )

        label = f"  \U0001f4cb  Study {mode}: {slug} ({len(sub_names)} fases)"
        self._template_label.setText(label)
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"Study {mode} {slug}")
        signal_bus.pipeline_ready.emit(specs)
        signal_bus.toast_requested.emit(
            f"Fila renderizada: {len(specs)} comandos.", "success"
        )

    @staticmethod
    def _extract_loop_path(command_line: str) -> str | None:
        """Extrai o valor de `--loop <path>` de um command_line shell-like.

        Suporta paths quoted (shlex). Retorna None se a flag estiver ausente,
        sem valor, ou se o proximo token for outra flag (`--xxx`).
        """
        try:
            tokens = shlex.split(command_line)
        except ValueError:
            return None
        for i, tok in enumerate(tokens):
            if tok == "--loop" and i + 1 < len(tokens):
                nxt = tokens[i + 1]
                if nxt and not nxt.startswith("--"):
                    return nxt
        return None

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        # Task 2 (loop 05-13-workflow-app-layout-2): margin-top 10 no container main-command-queue.
        main_layout.setContentsMargins(0, 10, 0, 0)
        main_layout.setSpacing(0)

        # Header — tab row (Daily | Workflow | Auxiliar) + accordion content
        header = QWidget()
        header.setObjectName("CommandQueueHeader")
        header.setProperty("testid", "output-toolbar-left")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setStyleSheet(
            "QWidget#CommandQueueHeader { background-color: #27272A;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        header_layout = QVBoxLayout(header)
        # Task 1 (loop 05-13-workflow-app-layout-2): margin-top 10 no container output-toolbar-left.
        header_layout.setContentsMargins(4, 14, 4, 4)
        header_layout.setSpacing(0)

        # ── Tab/action row ───────────────────────────────────────────────
        # Apenas abas primarias (Workflow, LOOPs, Auxiliar).
        # insertions_bar (Inserções + route-toggles + gear) migrou para
        # output-toolbar-center via MainWindow._setup_ui.
        tab_row = QWidget()
        tab_row.setFixedHeight(38)
        tab_row.setStyleSheet("background-color: #1E1E21;")
        tab_row_layout = QHBoxLayout(tab_row)
        tab_row_layout.setContentsMargins(4, 1, 4, 1)
        tab_row_layout.setSpacing(6)

        tab_bar = QWidget()
        tab_bar.setProperty("testid", "output-toolbar-left-primary-tabs")
        tab_bar.setStyleSheet("background-color: transparent;")
        tab_bar_layout = QHBoxLayout(tab_bar)
        tab_bar_layout.setContentsMargins(0, 0, 0, 0)
        tab_bar_layout.setSpacing(3)

        insertions_bar = QWidget()
        insertions_bar.setProperty("testid", "output-toolbar-left-insertions-controls")
        insertions_bar.setStyleSheet("background-color: transparent;")
        insertions_bar_layout = QHBoxLayout(insertions_bar)
        insertions_bar_layout.setContentsMargins(0, 0, 0, 0)
        insertions_bar_layout.setSpacing(3)

        self._sec_tabs: list[QPushButton] = []
        _tab_testids = (
            "queue-tab-workflow",
            "queue-tab-loops",
            "queue-tab-auxiliar",
            "queue-tab-terminal-insertions",
        )
        for i, label in enumerate(
            ("Workflow", "LOOPs", "Auxiliar", "Inserções")
        ):
            btn = QPushButton(label.upper())
            btn.setFixedHeight(22)
            btn.setProperty("testid", _tab_testids[i])
            btn.clicked.connect(lambda _ch=False, idx=i: self._switch_section(idx))
            if _tab_testids[i] != "queue-tab-terminal-insertions":
                tab_bar_layout.addWidget(btn, stretch=1)
            # insertions_btn: kept in _sec_tabs for index alignment (index 3)
            # but NOT added to any layout — content is always visible in
            # output-toolbar-center (skipped by _apply_section_styles).
            self._sec_tabs.append(btn)

        tab_row_layout.addWidget(tab_bar, stretch=1)
        # insertions_bar NAO entra no tab_row — MainWindow coloca em output-toolbar-center.

        # Exposed so MainWindow can:
        #   (a) append terminal-route-toggles + gear via attach_tab_bar_extras();
        #   (b) place insertions_bar + insertions_content in output-toolbar-center.
        self._tab_bar_layout = tab_bar_layout
        self._insertions_bar_layout = insertions_bar_layout
        self.insertions_bar = insertions_bar

        header_layout.addWidget(tab_row)

        # ── Section contents (only one visible at a time) ────────────────
        self._sec_contents: list[QWidget] = []

        # Pipelines
        daily_pill = self._AttachmentProxy(
            self, lambda: self._load_quick_template(TEMPLATE_DAILY, name="Daily")
        )
        daily_btn = DoublePhaseButton(
            label="daily",
            pipeline_name="/daily",
            argument_hint="[descricao da task] [config.json] [--tasklist <path.md>]",
            default_md_dir="blacksmith/daily/",
            radio_summaries={},
            pill=daily_pill,
            on_command_ready=self._on_daily_command_ready,
            parent=self,
        )
        daily_btn.setProperty("testid", "queue-btn-daily")
        daily_btn.setStyleSheet(_SECTION_BTN_STYLE)

        daily_loop_pill = self._AttachmentProxy(
            self, self._on_daily_loop_clicked
        )
        daily_loop_spec = COMMAND_FLAG_SPECS.get("/daily-loop")
        daily_loop_btn = DoublePhaseButton(
            label="daily-loop",
            pipeline_name="/daily-loop",
            argument_hint="[descricao da task] [config.json] [--tasklist <path.md>]",
            default_md_dir="blacksmith/daily-loop/",
            radio_summaries={},
            flags_boolean=daily_loop_spec.flags_boolean if daily_loop_spec else None,
            flags_with_value=daily_loop_spec.flags_with_value if daily_loop_spec else None,
            pill=daily_loop_pill,
            on_command_ready=self._on_unified_command_ready,
            parent=self,
        )
        daily_loop_btn.setProperty("testid", "queue-btn-daily-loop")
        daily_loop_btn.setToolTip(
            "Execute Daily Loop — expande a fila finita gerada por Create. "
            "Le _LOOP-CONFIG.json + PROGRESS.md do projeto carregado e cria "
            "para CADA item pendente: /daily-loop:do (bucket model/effort) + "
            "/daily-loop:review-done (Opus/standard, /mcp:dual Level 3 "
            "CROSS_ADVERSARIAL — analogo per-item de /review-executed-task, "
            "reverte+corrige+re-acceptance se achar regressao). Final: "
            "/daily-loop:review global em Opus/HIGH. /clear/model/effort "
            "dedupados entre buckets."
        )
        daily_loop_btn.setStyleSheet(_SECTION_BTN_STYLE)

        loop_pill = self._AttachmentProxy(
            self, self._on_loop_clicked
        )
        loop_spec = COMMAND_FLAG_SPECS.get("/loop")
        loop_btn = DoublePhaseButton(
            label="loop",
            pipeline_name="/loop",
            argument_hint="--task <path.md> [--name <slug>] | --cmd <path.md> [--name <slug>] | --cmd-single <path.md> | --both <path.md> [--name <slug>]",
            default_md_dir="blacksmith/loop/",
            radio_summaries={
                "--task": "para iterar execucao de tasks ja criadas em modulo ou micro-architecture",
                "--cmd": "para criar ou atualizar varios slash-commands do SystemForge em batch completo",
                "--cmd-single": "para criar ou atualizar um unico slash-command via sub-pipeline reduzida direta",
                "--both": "para fluxos que vao conter tasks variadas e criacao de comandos",
            },
            flags_boolean=loop_spec.flags_boolean if loop_spec else None,
            flags_with_value=loop_spec.flags_with_value if loop_spec else None,
            pill=loop_pill,
            on_command_ready=self._on_unified_command_ready,
            parent=self,
        )
        loop_btn.setProperty("testid", "queue-btn-loop")
        loop_btn.setToolTip(
            "Loop — expande fila finita gerada por /loop (--task|--cmd|--cmd-single|--both). "
            "Le _LOOP-CONFIG.json + PROGRESS.md do projeto carregado e cria "
            "para CADA item pendente: /daily-loop:do (bucket model/effort) + "
            "/daily-loop:review-done (Opus/standard, /mcp:dual Level 3 "
            "CROSS_ADVERSARIAL). Final: /daily-loop:review global em Opus/HIGH. "
            "/clear/model/effort dedupados entre buckets."
        )
        loop_btn.setStyleSheet(_SECTION_BTN_STYLE)

        # kimi-loop — gemeo do loop_btn na lane Kimi (/kimi-loop:*). Pill
        # REUSA _on_loop_clicked: o _LOOP-CONFIG.json e identico (D1/D2 do
        # design blacksmith/09-06-llm-dumb-use/KIMI-LOOP-DESIGN.md); a lane se
        # distingue pelos commands /kimi-loop:iteraction:* dentro do JSON.
        kimi_loop_pill = self._AttachmentProxy(
            self, self._on_loop_clicked
        )
        kimi_loop_spec = COMMAND_FLAG_SPECS.get("/kimi-loop")
        kimi_loop_btn = DoublePhaseButton(
            label="kimi-loop",
            pipeline_name="/kimi-loop",
            argument_hint="--task <path.md> [--name <slug>] | --cmd <path.md> [--name <slug>] | --cmd-single <path.md> | --both <path.md> [--name <slug>]",
            default_md_dir="blacksmith/loop/",
            radio_summaries={
                "--task": "para iterar execucao de tasks ja criadas, na lane Kimi (sonnet/medium)",
                "--cmd": "para criar ou atualizar varios slash-commands em batch, na lane Kimi",
                "--cmd-single": "para um unico slash-command (delega a sub-pipeline /loop --cmd-single)",
                "--both": "para fluxos com tasks variadas e criacao de comandos, na lane Kimi",
            },
            flags_boolean=kimi_loop_spec.flags_boolean if kimi_loop_spec else None,
            flags_with_value=kimi_loop_spec.flags_with_value if kimi_loop_spec else None,
            pill=kimi_loop_pill,
            on_command_ready=self._on_unified_command_ready,
            parent=self,
        )
        kimi_loop_btn.setProperty("testid", "queue-btn-kimi-loop")
        kimi_loop_btn.setToolTip(
            "Kimi-Loop — gemeo do Loop otimizado para LLM fraca "
            "(ai-forge/rules/weak-llm-pipeline-rules.md). Prep em 7 fases "
            "(--task/--cmd; split init+enumerate) ou 9 (--both), comandos "
            "/kimi-loop:* QUICKSTART-mecanicos, zero MCP, scripts "
            "deterministicos em kimi-loop/_scripts/. GROUP_MAP kimi_loop = "
            "sonnet/medium; todos os /kimi-loop:* sao Kimi-whitelisted "
            "(kimi_whitelist.py). Archives compartilham "
            "blacksmith/loop-archives/ — a pill carrega o mesmo "
            "_LOOP-CONFIG.json do Loop."
        )
        kimi_loop_btn.setStyleSheet(_SECTION_BTN_STYLE)

        study_pill = self._AttachmentProxy(
            self, lambda: self._load_quick_template(TEMPLATE_STUDY, name="Study")
        )
        study_btn = DoublePhaseButton(
            label="study",
            pipeline_name="/study",
            argument_hint='"<duvida>" [path.md] [--loop <path.md>] [--name <slug>] [--simple|--deep|--heavy]',
            default_md_dir="blacksmith/study/",
            radio_summaries={
                "--simple": "para estudo rapido com 1 fonte e output enxuto pra revisao imediata",
                "--deep": "para estudo intermediario com triangulacao de fontes e debate moderado de hipoteses",
                "--heavy": "para estudo denso com scope-decompose, loops de pesquisa e sintese profunda final",
            },
            pill=study_pill,
            on_command_ready=self._on_study_command_ready,
            parent=self,
        )
        study_btn.setProperty("testid", "queue-btn-study")
        study_btn.setToolTip(
            "Study — pesquisa estruturada com output dual (user-friendly + tecnico). "
            "3 modos: --simple (rapido, 1 fonte), --deep (triangulacao, debate), "
            "--heavy (scope-decompose, sintese profunda). Gera "
            "forged-goods/research/{name}.md."
        )
        study_btn.setStyleSheet(_SECTION_BTN_STYLE)

        # Botoes compartilhados construidos antes das secoes (usados em LOOPs
        # e Auxiliar). Cmd Single: modal simplificado com fixed_flag="cmd-single"
        # (apenas input de path; monta /loop --cmd-single <path.md>).
        _cmd_single_btn = DoublePhaseButton(
            label="Cmd Single",
            pipeline_name="/loop",
            argument_hint="",
            default_md_dir="blacksmith/loop/",
            radio_summaries={},
            flags_boolean=[],
            flags_with_value=[],
            fixed_flag="cmd-single",
            mode_radio=["kimi analyse", "kimi certain"],
            mode_radio_flags={"kimi analyse": "", "kimi certain": "--certain"},
            mode_radio_summaries={
                "kimi analyse": (
                    "kimi-pair-analyse roda o gate de elegibilidade antes de "
                    "adaptar (par analyse -> execute padrao)."
                ),
                "kimi certain": (
                    "kimi-pair-analyse --force + kimi-pair-execute --force: "
                    "pula o gate macro de elegibilidade (PROIBIDA continua "
                    "barrando individualmente)."
                ),
            },
            pill=None,
            on_command_ready=self._on_unified_command_ready,
            parent=self,
        )
        _cmd_single_btn.setProperty("testid", "queue-btn-cmd-single")
        _cmd_single_btn.setToolTip(
            "Cmd Single — pipeline reduzida para criar/atualizar UM comando "
            "avulso. Informe o path do .md da spec do comando."
        )
        _cmd_single_btn.setStyleSheet(_SECTION_BTN_STYLE)

        _maintenance_btn = QPushButton("maintenance")
        _maintenance_btn.setProperty("testid", "queue-btn-maintenance")
        _maintenance_btn.setToolTip("Maintenance — placeholder (acao a definir).")
        _maintenance_btn.setStyleSheet(_SECTION_BTN_STYLE)

        # ── Secao 0: Workflow ─────────────────────────────────────────────
        workflow_content = self._build_section_grid([
            ("json", "/project-json — Cria/atualiza project.json",
             lambda: self._load_quick_template(TEMPLATE_JSON, name="JSON"),
             "queue-btn-json"),
            ("brief new", "/first-brief-create → intake → PRD (novo projeto)",
             lambda: self._load_quick_template(TEMPLATE_BRIEF_NEW, name="Brief \u2014 Novo Projeto"),
             "queue-btn-brief-new"),
            ("micro-arch",
             "Pipeline DCP-lite /micro:* \u2014 5 comandos que produzem PRD + USER-STORIES + "
             "ARCHITECTURE + _micro-flow-hints + modules consumiveis diretamente por "
             "queue-btn-dcp-build (sem passo intermediario): "
             "/micro:brief \u2192 /micro:architecture \u2192 /micro:specific-flow-prep \u2192 "
             "/micro:modularize \u2192 /micro:review (com /clear + /model + /effort por boundary).",
             lambda: self._load_quick_template(TEMPLATE_MICRO_ARCHITECTURE, name="Micro-Arch"),
             "queue-btn-micro-arch"),
            ("Modules (Creation)", "Fase A do canonical loop — cria estrutura WBS, MODULE-META.json e delivery.json. Pre-requisito de [DCP: Build Module Pipeline].",
             self._on_modules_clicked,
             "queue-btn-modules"),
            ("DCP Build",
             "Enfileira pipeline B-dcp completo (5 cmds /dcp:* + carga local de SPECIFIC-FLOW) "
             "em queue-command-list para o modulo atual.\n"
             "Apos o pipeline rodar com sucesso, a fila e substituida pelos comandos do "
             "SPECIFIC-FLOW.json gerado. Compativel com producer canonico e producer micro.\n"
             "DESTRUTIVO quando SPECIFIC-FLOW.json ja existe (passa --regenerate, salva .bak-{ISO}). "
             "Modal de confirmacao antes da pipeline rodar.",
             self._on_dcp_build_pipeline_clicked, "queue-btn-dcp-build"),
            ("DCP Execute",
             "FALLBACK MANUAL: usar apenas quando o operador editou SPECIFIC-FLOW.json a mao "
             "apos um build anterior. O caminho default agora e [DCP Build] "
             "(queue-btn-dcp-build), que enfileira a pipeline B-dcp completa e ja carrega o "
             "flow gerado no 6o item.\n"
             "Le o SPECIFIC-FLOW.json do modulo atual e carrega os comandos na fila para "
             "execucao manual.\n"
             "ATENCAO: deletes/reorder na fila visual sao TRANSIENT — re-clicar este botao "
             "recarrega do disco e os itens removidos voltam. Para fix permanente, edite "
             "MODULE-META.json e regenere via [DCP Build].",
             self._on_dcp_specific_flow_clicked, "queue-btn-dcp-specific-flow"),
            ("governance",
             "Enfileira a cadeia governance expandida de /auto-flow: scorecard, lessons, "
             "memory, meta e cmd. Requer docs_root/_pipeline-research/PIPELINE-RUNS.tsv "
             "com pelo menos uma linha de dados; nunca enfileira /auto-flow governance "
             "como comando unico.",
             self._on_governance_clicked, "queue-btn-governance"),
        ])
        self._apply_dcp_reader_gating(workflow_content)
        self._refresh_governance_button_state(workflow_content)
        header_layout.addWidget(workflow_content)
        self._sec_contents.append(workflow_content)

        # ── Secao 1: LOOPs ────────────────────────────────────────────────
        loops_content = self._build_section_grid([
            daily_btn,
            daily_loop_btn,
            loop_btn,
            kimi_loop_btn,
            study_btn,
            ("rocksmash",
             "rocksmash — le metrics-project-pill (_LOOP-CONFIG.json kind=daily-loop), "
             "expande para fila /loop-rocksmash:prepare + N pares :do/:review-done + "
             "/loop-rocksmash:rename. Items kind=preparo/finalizacao sao ignorados; "
             "directives /clear, /model, /effort auto-injetadas por bucket boundary.",
             self._on_rocksmash_clicked,
             "queue-btn-rocksmash"),
            ("rocksmash review",
             "rocksmash review — injeta o template estatico de 12 itens "
             "(/clear /model opus /effort high + 5x /agents:troop-review {json} "
             "intercaladas por /clear). Le o JSON do projeto ativo da "
             "metrics-project-pill. Cada /agents:troop-review e uma rodada "
             "single-pass sobre o agent-progress-reviewer.md; as 5 invocacoes "
             "cobrem ate ~25 tasks por acionamento (re-clique para tasklists "
             "maiores). Requer /agents:troop-review criado. Bloqueia o clique "
             "se a pill nao apontar para um JSON valido em disco.",
             self._on_rocksmash_review_clicked,
             "queue-btn-rocksmash-review"),
            _cmd_single_btn,
        ])
        header_layout.addWidget(loops_content)
        self._sec_contents.append(loops_content)

        # ── Secao 2: Auxiliar ─────────────────────────────────────────────
        auxiliar_content = self._build_section_grid([
            ("legacy-to-dcp",
             "Legacy-to-DCP — adequa project.json legado (V3 canonico ou boilerplate convertido) ao canonical loop A..I. "
             "Pipeline: /legacy:detect (aborta V1/V2 com instrucao manual) -> /delivery:init|migrate -> "
             "/legacy:modules-from-features -> /dcp:meta-completeness (auto-fix P0, P1+ -> pending-actions) -> "
             "/legacy:enqueue-all-modules (expande /build-module-pipeline por modulo). "
             "Le project.json do metrics-project-pill. Idempotente: re-rodar nao quebra modulos ja convertidos. "
             "Para V1/V2: rodar /project-json manualmente para migrar para V3 antes de reenfileirar. "
             "Gaps P0 auto-fix, P1+ registrados em pending-actions/{slug}.md.",
             self._on_legacy_to_dcp_clicked,
             "queue-btn-legacy-to-dcp"),
            ("mkt", "Marketing: portfolio, LinkedIn, Instagram",
             lambda: self._load_quick_template(TEMPLATE_MKT, name="Marketing"),
             "queue-btn-mkt"),
            ("boilerplate", "Boilerplate: scan → convert-nextjs → cleanup → persona → mockify → persona-assets → enhance-fe → gen-sql → finalize. Abre modal para path do repo (NAO le project.json).",
             self._on_boilerplate_clicked, "queue-btn-boilerplate"),
            ("book-legacy", "Book Legacy: restauracao de livro escaneado. Abre modal de 5 campos "
             "(pasta de imagens, nome do livro, formato, fonte, glossario) e enfileira a cadeia "
             "expandida /book-legacy:* — preparo (:scan) + iteration per-pagina (:ocr, "
             ":apply-glossary, :diff-original) + finalizacao (:review-orthographic, :layout-plan, "
             ":compose-pages, :build-pdf, :validate). NUNCA enfileira o orquestrador como entrada "
             "unica. NAO le project.json.",
             self._on_book_legacy_clicked, "queue-btn-book-legacy"),
            ("intake-seed", "Intake Seed — prepara base maximamente expandida para o intake-review. Dupla função: (1) /intake:obvious melhora o INTAKE.md original; (2) /intake-review:seed gera INTAKE.seeded.md + MILESTONES.seeded.md consolidando features em docs_root/features/*. Passa project.json da pill.",
             lambda: self._load_quick_template(TEMPLATE_INTAKE_SEED, name="Intake Seed"),
             "queue-btn-intake-seed"),
            ("intake-review", "Intake Review (F9): create-checklist → list-improove → compare → create-gaplist → execute-gaplist-p0 → execute-gaplist-p1 → execute-gaplist-p2 → review-executed → clear",
             lambda: self._load_quick_template(TEMPLATE_INTAKE_REVIEW, name="Intake Review"),
             "queue-btn-intake-review"),
            ("blog stockpile",
             "Blog Stockpile — GERA ESTOQUE, NAO PUBLICA. "
             "Pipeline ATOMIZADA Kimi-friendly (Opcao D, D8 do DECISION-LOG): gera N=3 "
             "pacotes quad-locale (pt-BR/it-IT/en/es-ES) por clique e faz commit/push "
             "APENAS do estoque (em .claude/blog/data/stockpile/). O artigo NAO vai ao ar "
             "com este botao — a publicacao em content/{locale}/blog/ acontece via GitHub "
             "Actions cron 13h UTC (promote-from-stockpile.yml). Por design (T012), publicar "
             "e responsabilidade exclusiva do CI. "
             "Fase 1 (compartilhada): expand-keywords -> cluster -> prioritize -> deduplicate. "
             "Fase 2 (x3 pacotes, atomica): por pacote, generate-briefs (avanca wave + "
             "CURRENT-PACKAGE.json) -> write-articles --output-dir stockpile x4 locales -> "
             "review-seo --mode stockpile x4 locales -> quality-gate --mode stockpile x4 "
             "locales -> stockpile-finalize-package (Pass 2.4 atomico: monta package.json). "
             "Fase 3: stockpile-validate (npm run validate:stockpile) -> stockpile-push. "
             "Cada item da fila e um slash-command atomico ja Kimi-compat (ver kimi_whitelist.py), "
             "compativel com o seletor 'queue-div-main-llm' (Claude / Codex / Kimi). N editavel "
             "via _BLOG_STOCKPILE_PACKAGES_PER_CLICK em templates/quick_templates.py.",
             lambda: self._load_quick_template(
                 TEMPLATE_BLOG_STOCKPILE,
                 # T012: o nome vira o label persistente (_template_label) que
                 # fica VISIVEL na tela apos o clique — nao some como o tooltip.
                 name="Blog Stockpile (estoque, NAO publica)",
             ),
             "queue-btn-blog-stockpile"),
            ("Publish micro-site (multilingue br/it/es/us)",
             "Publish micro-site multilingue — para o slug selecionado via input, "
             "valida deploy-map.json (host nao-reservado), locales-map.json, "
             "site.json e REVIEW.md status:approved para os 4 locales "
             "(pt-BR/it-IT/es-ES/en-US) e entao enfileira 7 itens: "
             "/micro-sites-publish <host> --country br -> /clear -> "
             "/micro-sites-publish <host> --country it -> /clear -> "
             "/micro-sites-publish <host> --country es -> /clear -> "
             "/micro-sites-publish <host> --country us. "
             "Falha em qualquer validacao -> toast vermelho, nada enfileira. "
             "Cada invocacao do comando continua independente e idempotente; "
             "o autocast existente dispara o proximo apos cada termino "
             "(wf-notify.sh).",
             self._on_publish_micro_sites_multilingue_clicked,
             "queue-btn-publish-micro-sites-multilingue"),
            ("multibackend",
             "Multibackend — vincula uma pagina estatica HTML/CSS/JS ja "
             "hospedada (Hostinger) ao backend central multi-tenant do bloco "
             "06-03, injeta um botao de login OIDC funcional (Zero Orfaos) e "
             "deixa o site em PRODUCAO. Le o project.json do metrics-project-pill "
             "como $1. Pipeline (6 itens opus/high, cada um gate do seguinte via "
             "scan-report.json em disco): /multibackend:scan (resolve identidade/"
             "OIDC/arquitetura/deploy-dest) -> /multibackend:link-auth (injeta o "
             "elemento de login idempotente e RESPONSIVO (desktop + menu "
             "hamburguer mobile, R-26) com marker data-testid estavel) -> "
             "/multibackend:env-wire (audita valores OIDC, gera env-config sem "
             "secret em texto plano) -> /multibackend:build-verify (smoke local "
             "ramificando por arquitetura OIDC) -> /multibackend:deploy (rsync "
             "com snapshot + rollback verificado) -> /multibackend:verify-prod "
             "(HTTP 200, marker de login, login real via Playwright; veredito "
             "APROVADO/BLOQUEADO/AVISO). Sem project.json carregado -> toast "
             "verbose pt-BR, nada enfileira.",
             self._on_multibackend_clicked,
             "queue-btn-multibackend"),
            _maintenance_btn,
        ])
        header_layout.addWidget(auxiliar_content)
        self._sec_contents.append(auxiliar_content)

        # Terminal Insertions tab (refactor 2026-05-16): merge das antigas tabs
        # `queue-tab-prompts` e `queue-tab-actions` em uma so aba congruente
        # (itens digitados/inseridos no terminal). Layout em duas linhas:
        # - row top: prompts (MCP-test, Online Review, Progress, slot livre)
        # - row bottom: actions (JSON, WS, MCPs, Codex provider skills, asq-user)
        # Populadas via populate_prompts_tab() / populate_actions_tab() pelo
        # MainWindow (handlers dependem de estado vivo: signal_bus, _publish_to_terminal).
        terminal_insertions_content = QWidget()
        terminal_insertions_content.setStyleSheet("background-color: #27272A;")
        _ti_layout = QVBoxLayout(terminal_insertions_content)
        _ti_layout.setContentsMargins(5, 4, 5, 5)
        _ti_layout.setSpacing(4)

        # Refactor 2026-05-18: substituir as 3 rows estáticas
        # (terminal-insertions-row-prompts, -workflow-app, -actions) por um
        # QTabWidget com 4 sub-abas semânticas. Populadas via populate_*_subtab()
        # pelo MainWindow após build (handlers dependem de estado vivo).
        self._insertions_subtabs = QTabWidget()
        self._insertions_subtabs.setProperty("testid", "queue-subtabs-insertions")
        self._insertions_subtabs.setStyleSheet(
            "QTabWidget::pane { border: none; background: transparent; }"
            "QTabBar::tab { background: transparent; color: #A1A1AA;"
            "  border: none; border-radius: 3px;"
            "  padding: 6px 8px; font-size: 10px; font-weight: 700;"
            "  letter-spacing: 0.5px; margin-right: 3px; }"
            "QTabBar::tab:selected { background: #FBBF24; color: #18181B; }"
            "QTabBar::tab:hover { background: #2D2D30; color: #D4D4D8; }"
        )

        def _make_subtab(testid: str) -> tuple[QWidget, ResponsiveButtonFlowLayout]:
            w = QWidget()
            w.setProperty("testid", testid)
            lay = ResponsiveButtonFlowLayout(w, spacing=4, max_lines=4)
            lay.setContentsMargins(0, 2, 0, 2)
            return w, lay

        # paths & IDs agora usa o mesmo flow responsivo das demais subtabs.
        # `repo rules` entra no mesmo fluxo para o limite de 4 linhas valer
        # para a sub-aba inteira.
        _paths_tab = QWidget()
        _paths_tab.setProperty("testid", "queue-subtab-insertions-paths")
        self._subtab_paths_layout = ResponsiveButtonFlowLayout(
            _paths_tab, spacing=4, max_lines=4
        )
        self._subtab_paths_layout.setContentsMargins(0, 2, 0, 2)
        _prompts_tab, self._subtab_prompts_layout = _make_subtab("queue-subtab-insertions-prompts")
        _rules_tab, self._subtab_rules_layout = _make_subtab("queue-subtab-insertions-rules")
        _cmd_tab, self._subtab_cmd_layout = _make_subtab("queue-subtab-insertions-cmd")
        _auto_improove_tab, self._subtab_auto_improove_layout = _make_subtab("queue-subtab-insertions-auto-improove")
        _personal_tab, self._subtab_personal_layout = _make_subtab("queue-subtab-insertions-personal")
        _personas_tab, self._subtab_personas_layout = _make_subtab("queue-subtab-insertions-personas")

        self._insertions_subtabs.addTab(_paths_tab, "PATHS")
        self._insertions_subtabs.addTab(_prompts_tab, "PROMPTS")
        self._insertions_subtabs.addTab(_rules_tab, "RULES")
        self._insertions_subtabs.addTab(_cmd_tab, "CMD")
        self._insertions_subtabs.addTab(_auto_improove_tab, "AUTO IMPROOVE")
        self._insertions_subtabs.addTab(_personal_tab, "PERSONAL")
        self._insertions_subtabs.addTab(_personas_tab, "Agentes")

        # Restaurar sub-aba ativa da sessão anterior; persistir ao mudar.
        # Refactor 2026-05-19: sub-aba "cmd & mcp" deletada (botoes migraram para
        # output-toolbar-mcp). Indice antigo 1 (mcps) cai em prompts agora;
        # antigos 2/3 viram 1/2. Clamp para faixa nova [0,2].
        # 2026-06-02: 4a sub-aba "CMD" (comandos avulsos) re-adicionada apos RULES;
        # clamp passa a [0,3].
        # 2026-06-03: 5a sub-aba "PERSONAS" adicionada apos CMD; clamp passa a [0,4].
        # 2026-06-03: 6a sub-aba "AUTO IMPROOVE" e 7a "PERSONAL" adicionadas; clamp [0,6].
        _stg = QSettings("systemForge", "workflow-app")
        _active_subtab = int(_stg.value("insertions/active_subtab", 0))
        if not (0 <= _active_subtab < 7):
            _active_subtab = 0
        self._insertions_subtabs.setCurrentIndex(_active_subtab)
        self._insertions_subtabs.currentChanged.connect(
            lambda idx: QSettings("systemForge", "workflow-app").setValue(
                "insertions/active_subtab", idx
            )
        )

        _ti_layout.addWidget(self._insertions_subtabs)

        # terminal_insertions_content NAO entra no header_layout — MainWindow
        # coloca em output-toolbar-center. Permanece em _sec_contents para que
        # _switch_section controle a visibilidade normalmente.
        self._sec_contents.append(terminal_insertions_content)
        self.insertions_content = terminal_insertions_content

        # Default: Workflow active (index 0)
        self._active_section = 0
        self._apply_section_styles()

        # Exposed so MainWindow can place it as a sibling of output-toolbar.
        self.header_widget = header

        # Play bar — big play button
        play_bar = QWidget()
        play_bar.setStyleSheet(
            "background-color: #1C1C1F; border-bottom: 1px solid #3F3F46;"
        )
        play_bar.setFixedHeight(110)
        pl = QVBoxLayout(play_bar)
        pl.setContentsMargins(8, 5, 8, 5)
        pl.setSpacing(4)

        play_row_top = QHBoxLayout()
        play_row_top.setContentsMargins(0, 0, 0, 0)
        play_row_top.setSpacing(8)
        play_row_third = QHBoxLayout()
        play_row_third.setContentsMargins(0, 0, 0, 0)
        play_row_third.setSpacing(8)
        pl.addLayout(play_row_top)
        pl.addLayout(play_row_third)

        # "Rodar próximo" — botão dominante da play bar (primeira posição,
        # verde #16A34A, stretch=7). Executa o proximo item pendente da fila e
        # para. Funciona em qualquer item (auto ou interactive). Diferente do
        # _btn_next ("Continuar: X") que aparece SO em pause de interactive.
        self._play_btn = QPushButton("▶  Rodar próximo")
        self._play_btn.setProperty("testid", "queue-btn-play-next")
        self._play_btn.setFixedHeight(32)
        self._play_btn.setMinimumWidth(84)
        self._play_btn.setToolTip(
            "Executa o proximo item pendente da fila e para.\n"
            "Funciona com qualquer item — auto ou interactive."
        )
        self._play_btn.setStyleSheet(
            "QPushButton { background-color: #16A34A; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 13px; font-weight: 700; text-align: center; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:pressed { background-color: #166534; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._play_btn.clicked.connect(self._on_step_btn_clicked)

        # Container "div" envolvendo o queue-btn-play-next para alvo de testes
        # de UI (data-testid). Mantem o stretch=2 original do play_btn.
        self._play_btn_container = QWidget()
        self._play_btn_container.setProperty("testid", "queue-btn-play-next-container")
        _play_btn_container_layout = QHBoxLayout(self._play_btn_container)
        _play_btn_container_layout.setContentsMargins(0, 0, 0, 0)
        _play_btn_container_layout.setSpacing(0)
        _play_btn_container_layout.addWidget(self._play_btn)
        play_row_top.addWidget(self._play_btn_container, stretch=2)

        # Autocast (segunda posicao — invertido com schedule em Iter 12).
        # Width dobrada vs original (minimumWidth 140) e setinha dupla ▶▶.
        # Emite via signal_bus para a state machine em metrics_bar.
        self._btn_autocast = QPushButton("▶▶  autocast")
        self._btn_autocast.setProperty("testid", "autocast-btn")
        self._btn_autocast.setCheckable(True)
        self._btn_autocast.setFixedHeight(32)
        self._btn_autocast.setMinimumWidth(84)
        self._btn_autocast.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_autocast.setToolTip(
            "Autocast: dispara [Rodar proximo] em loop ate a fila esvaziar"
        )
        self._btn_autocast.setStyleSheet(
            "QPushButton { background-color: #1E3A8A; color: #FAFAFA;"
            "  border: 1px solid #3B82F6; border-radius: 5px;"
            "  font-size: 12px; font-weight: 700; padding: 0 10px; text-align: center; }"
            "QPushButton:hover { background-color: #1D4ED8; }"
            "QPushButton:checked { background-color: #DC2626; border-color: #EF4444; }"
            "QPushButton:checked:hover { background-color: #B91C1C; }"
        )

        def _on_autocast_play_toggled(checked: bool) -> None:
            self._btn_autocast.setText("▶▶  parar" if checked else "▶▶  autocast")
            signal_bus.autocast_toggle_requested.emit(bool(checked))

        def _on_autocast_state_synced(checked: bool) -> None:
            # Programmatic state change (e.g., arm timeout auto-stop). Update
            # the play bar button without re-emitting toggle_requested to
            # avoid recursive feedback into the state machine.
            if self._btn_autocast.isChecked() == bool(checked):
                return
            self._btn_autocast.blockSignals(True)
            self._btn_autocast.setChecked(bool(checked))
            self._btn_autocast.setText("▶▶  parar" if checked else "▶▶  autocast")
            self._btn_autocast.blockSignals(False)

        self._btn_autocast.toggled.connect(_on_autocast_play_toggled)
        signal_bus.autocast_state_changed.connect(_on_autocast_state_synced)
        # autocast + schedule dividem 60% da row (play_btn fica com 40%).
        # autocast min reduzido para 64 para conseguir encolher quando o
        # schedule cresce com o cronometro sem clipping de "▶▶  autocast".
        self._btn_autocast.setMinimumWidth(64)
        self._ac_sched_layout = QHBoxLayout()
        self._ac_sched_layout.setContentsMargins(0, 0, 0, 0)
        self._ac_sched_layout.setSpacing(8)
        self._ac_sched_layout.addWidget(self._btn_autocast, stretch=1)

        # Schedule-autocast (sobe para play_row_top em Iter 13). Dois modos:
        # idle/fired -> 1:1 (32x32), so icone. running -> expande, mostra
        # "⏱ MM:SS" e ocupa stretch=2 dentro do segmento de 60% — autocast
        # encolhe. Acabou o cronometro, autocast e disparado (via state machine
        # em metrics_bar._fire_schedule_autocast) e o schedule volta a 1:1.
        self._btn_schedule_autocast = _ScheduleAutocastButton("agendar")
        self._btn_schedule_autocast.setProperty("testid", "schedule-autocast-btn")
        self._btn_schedule_autocast.setFixedHeight(32)
        self._btn_schedule_autocast.setMinimumWidth(32)
        self._btn_schedule_autocast.setMaximumWidth(32)
        self._btn_schedule_autocast.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_schedule_autocast.setToolTip(
            "Agendar disparo automatico do autocast"
        )

        # 3 variantes compactas (idle/running/fired) — mantemos a paleta dos
        # stylesheets originais (#27272A / #F0B90B / #22C55E) mas com padding 0
        # e tamanho de fonte adequado ao icone centralizado em 32x32.
        _SCHED_BTN_IDLE_QSS = (
            "QPushButton { background-color: #27272A; color: #D4D4D8;"
            "  border: 1px solid #52525B; border-radius: 5px;"
            "  font-size: 16px; font-weight: 600; padding: 0;"
            "  text-align: center; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FAFAFA; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; }"
        )
        # Running usa padding lateral porque o texto "⏱ MM:SS" precisa de
        # respiro; font menor para caber em rows estreitas.
        _SCHED_BTN_RUNNING_QSS = (
            "QPushButton { background-color: #F0B90B; color: #18181B;"
            "  border: none; border-radius: 5px;"
            "  font-size: 13px; font-weight: 700; padding: 0 10px;"
            "  text-align: center; }"
            "QPushButton:hover { background-color: #D9A509; }"
        )
        _SCHED_BTN_FIRED_QSS = (
            "QPushButton { background-color: #22C55E; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 16px; font-weight: 700; padding: 0;"
            "  text-align: center; }"
        )
        _COMPACT_WIDTH = 32  # 1:1 com setFixedHeight(32)
        _EXPANDED_MIN_WIDTH = 72  # cabe "⏱ 00:23" sem clipping
        _QWIDGETSIZE_MAX = 16777215
        self._btn_schedule_autocast.setStyleSheet(_SCHED_BTN_IDLE_QSS)
        self._btn_schedule_autocast.clicked.connect(
            lambda: signal_bus.schedule_autocast_requested.emit()
        )

        def _set_schedule_compact() -> None:
            """idle/fired -> 1:1 (32x32), so o icone, sem stretch."""
            self._btn_schedule_autocast.set_expanded(False)
            self._btn_schedule_autocast.setMinimumWidth(_COMPACT_WIDTH)
            self._btn_schedule_autocast.setMaximumWidth(_COMPACT_WIDTH)
            # schedule sem stretch -> autocast (stretch=1) ocupa o restante.
            self._ac_sched_layout.setStretch(0, 1)
            self._ac_sched_layout.setStretch(1, 0)

        def _set_schedule_expanded() -> None:
            """running -> mostra '⏱ MM:SS' e cresce para autocast encolher."""
            self._btn_schedule_autocast.set_expanded(True)
            self._btn_schedule_autocast.setMinimumWidth(_EXPANDED_MIN_WIDTH)
            self._btn_schedule_autocast.setMaximumWidth(_QWIDGETSIZE_MAX)
            # autocast 1 : schedule 2 -> autocast diminui visivelmente.
            self._ac_sched_layout.setStretch(0, 1)
            self._ac_sched_layout.setStretch(1, 2)

        def _on_schedule_visual_changed(label: str, qss: str, tooltip: str) -> None:
            # Ignora qss recebido (formatos vinham com padding/font para o
            # antigo botao com texto); mapeia o estado pelo label.
            # "agendar" = idle (compact); "disparado" = fired (compact);
            # demais = running (expanded com cronometro).
            self._btn_schedule_autocast.setText(label)
            if label == "agendar":
                self._btn_schedule_autocast.setStyleSheet(_SCHED_BTN_IDLE_QSS)
                _set_schedule_compact()
            elif label == "disparado":
                self._btn_schedule_autocast.setStyleSheet(_SCHED_BTN_FIRED_QSS)
                _set_schedule_compact()
            else:
                self._btn_schedule_autocast.setStyleSheet(_SCHED_BTN_RUNNING_QSS)
                _set_schedule_expanded()
            self._btn_schedule_autocast.setToolTip(tooltip)

        signal_bus.schedule_autocast_visual_changed.connect(_on_schedule_visual_changed)
        self._ac_sched_layout.addWidget(self._btn_schedule_autocast, stretch=0)
        # play_btn (stretch=2) + ac_sched (stretch=3) -> 40/60 split na row.
        play_row_top.addLayout(self._ac_sched_layout, stretch=3)

        # LLM routing: one container with the main session selector and
        # optional worker preference toggles used by [Rodar proximo].
        _llm_box = QWidget()
        _llm_box.setProperty("testid", "queue-div-llm-routing")
        _llm_box.setFixedHeight(78)
        _llm_box.setStyleSheet(
            "QWidget { background-color: #1C1C1F; border: 1px solid #3F3F46;"
            "  border-radius: 5px; }"
        )
        _llm_layout = QVBoxLayout(_llm_box)
        _llm_layout.setContentsMargins(8, 4, 8, 4)
        _llm_layout.setSpacing(4)

        _control_qss = (
            "QRadioButton, QCheckBox { color: #FAFAFA; font-size: 10px;"
            "  font-weight: 600; background: transparent; border: none;"
            "  padding: 0; }"
            "QRadioButton::indicator, QCheckBox::indicator { width: 13px;"
            "  height: 13px; }"
            "QRadioButton::indicator:unchecked, QCheckBox::indicator:unchecked {"
            "  background-color: #3F3F46; border: 1px solid #52525B; }"
            "QRadioButton::indicator:unchecked { border-radius: 7px; }"
            "QCheckBox::indicator:unchecked { border-radius: 3px; }"
            "QRadioButton::indicator:checked, QCheckBox::indicator:checked {"
            "  background-color: #3B82F6; border: 1px solid #3B82F6; }"
            "QRadioButton::indicator:checked { border-radius: 7px; }"
            "QCheckBox::indicator:checked { border-radius: 3px; }"
            "QRadioButton::indicator:hover, QCheckBox::indicator:hover {"
            "  border-color: #93C5FD; }"
        )
        _section_label_qss = (
            "QLabel { color: #A1A1AA; font-size: 9px; font-weight: 700;"
            "  text-transform: uppercase; background: transparent; border: none; }"
        )

        _main_section = QWidget()
        _main_section.setProperty("testid", "queue-div-main-llm")
        _main_section.setStyleSheet("background: transparent; border: none;")
        _main_layout = QHBoxLayout(_main_section)
        _main_layout.setContentsMargins(0, 0, 0, 0)
        _main_layout.setSpacing(7)
        _main_label = QLabel("Main LLM:")
        _main_label.setStyleSheet(_section_label_qss)
        _main_options = QWidget()
        _main_options.setStyleSheet("background: transparent; border: none;")
        _main_options_layout = QHBoxLayout(_main_options)
        _main_options_layout.setContentsMargins(0, 0, 0, 0)
        _main_options_layout.setSpacing(7)
        self._main_claude_radio = QRadioButton("claude")
        self._main_claude_radio.setProperty("testid", "queue-radio-main-claude")
        self._main_claude_radio.setChecked(True)
        self._main_codex_radio = QRadioButton("codex")
        self._main_codex_radio.setProperty("testid", "queue-radio-main-codex")
        self._main_kimi_radio = QRadioButton("kimi")
        # Compatibility alias: this is the new Main LLM Kimi control.
        self._main_kimi_radio.setProperty("testid", "queue-chk-force-kimi")
        self._force_kimi_chk = self._main_kimi_radio
        self._main_llm_group = QButtonGroup(self)
        self._main_llm_group.setExclusive(True)
        for _btn in (
            self._main_claude_radio,
            self._main_codex_radio,
            self._main_kimi_radio,
        ):
            _btn.setStyleSheet(_control_qss)
            self._main_llm_group.addButton(_btn)
            _main_options_layout.addWidget(_btn)
        _main_layout.addWidget(_main_label)
        _main_layout.addWidget(_main_options, stretch=1)
        _llm_layout.addWidget(_main_section, stretch=1)

        _worker_section = QWidget()
        _worker_section.setProperty("testid", "queue-div-parallel-worker")
        _worker_section.setStyleSheet("background: transparent; border: none;")
        _worker_layout = QHBoxLayout(_worker_section)
        _worker_layout.setContentsMargins(0, 0, 0, 0)
        _worker_layout.setSpacing(7)
        _worker_label = QLabel("Parallel Worker:")
        _worker_label.setStyleSheet(_section_label_qss)
        _worker_options = QWidget()
        _worker_options.setStyleSheet("background: transparent; border: none;")
        _worker_options_layout = QHBoxLayout(_worker_options)
        _worker_options_layout.setContentsMargins(0, 0, 0, 0)
        _worker_options_layout.setSpacing(8)
        self._use_kimi_chk = QCheckBox("kimi")
        self._use_kimi_chk.setProperty("testid", "queue-chk-use-kimi")
        self._use_kimi_chk.setToolTip(
            "Quando marcado, [Rodar proximo] usa Kimi para items compativeis."
        )
        self._use_codex_chk = QCheckBox("codex")
        self._use_codex_chk.setProperty("testid", "queue-chk-use-codex")
        self._use_codex_chk.setToolTip(
            "Quando marcado, [Rodar proximo] envia ao T3 Codex apenas os itens com seta azul "
            "(worker-elegiveis). Itens so com seta verde seguem no T1."
        )
        for _btn in (self._use_kimi_chk, self._use_codex_chk):
            _btn.setStyleSheet(_control_qss)
            _worker_options_layout.addWidget(_btn)
        _worker_layout.addWidget(_worker_label)
        _worker_layout.addWidget(_worker_options, stretch=1)
        _llm_layout.addWidget(_worker_section, stretch=1)
        play_row_third.addWidget(_llm_box, stretch=1)

        # Botao de copiar todos os comandos renderizados em queue-command-list.
        # Posicionado em play_row_third apos --force Kimi.
        self._copy_commands_btn = QPushButton()
        self._copy_commands_btn.setProperty(
            "testid", "queue-btn-copy-commands"
        )
        _copy_icon = _load_tinted_svg_icon(
            _WORKFLOW_APP_DIR / "assets" / "copy.svg", "#FAFAFA"
        )
        if _copy_icon is not None:
            self._copy_commands_btn.setIcon(_copy_icon)
            self._copy_commands_btn.setIconSize(QSize(12, 12))
        else:
            self._copy_commands_btn.setText("⎘")
        self._copy_commands_btn.setFixedSize(22, 22)
        self._copy_commands_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_commands_btn.setToolTip(
            "Copiar todos os comandos renderizados, uma linha por comando"
        )
        self._copy_commands_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: 1px solid #52525B; border-radius: 3px; padding: 2px; }"
            "QPushButton:hover { background-color: #52525B; color: #FFFFFF; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B;"
            "  border-color: #FBBF24; }"
        )
        self._copy_commands_btn.clicked.connect(self._on_copy_rendered_commands)
        play_row_third.addWidget(
            self._copy_commands_btn, alignment=Qt.AlignmentFlag.AlignVCenter
        )

        # Main Kimi preserves the old slash-to-skill conversion and hides the
        # per-item blue arrows while active. Worker toggles keep the legacy
        # play-next preference path.
        self._force_kimi_chk.toggled.connect(self._on_force_kimi_toggled)
        self._use_kimi_chk.toggled.connect(self._on_use_kimi_toggled)
        self._main_codex_radio.toggled.connect(self._on_main_codex_toggled)
        self._main_claude_radio.toggled.connect(self._on_main_claude_toggled)
        self._use_codex_chk.toggled.connect(self._on_use_codex_toggled)

        main_layout.addWidget(play_bar)

        # Model/Effort row — above queue-template-label.
        # Espelha o comportamento visual de queue-template-label e
        # queue-last-command. Dois divs internos em row: esquerda renderiza
        # o ultimo `/model X` rodado em queue-command-list; direita renderiza
        # o ultimo `/effort X`. Atualizado em _on_run_command; resetado em
        # load_pipeline / clear_queue.
        self._model_effort_row = QWidget()
        self._model_effort_row.setProperty("testid", "queue-model-effort-row")
        self._model_effort_row.setFixedHeight(28)
        self._model_effort_row.setStyleSheet(
            "QWidget { background-color: #1C1C1F;"
            " border-bottom: 1px solid #3F3F46; }"
        )
        _mel = QHBoxLayout(self._model_effort_row)
        _mel.setContentsMargins(10, 4, 10, 4)
        _mel.setSpacing(6)

        _ME_LBL_BASE = (
            "background: transparent; border: none;"
            " color: #D4D4D8; font-size: 11px; font-family: monospace;"
        )

        self._last_model_div = QWidget()
        self._last_model_div.setProperty("testid", "queue-last-model")
        self._last_model_div.setStyleSheet("background: transparent;")
        _lmdl = QHBoxLayout(self._last_model_div)
        _lmdl.setContentsMargins(0, 0, 0, 0)
        _lmdl.setSpacing(4)
        self._last_model_label = QLabel("/model: —")
        self._last_model_label.setProperty("testid", "queue-last-model-value")
        self._last_model_label.setStyleSheet(_ME_LBL_BASE)
        _lmdl.addWidget(self._last_model_label)
        _lmdl.addStretch(1)
        _mel.addWidget(self._last_model_div, stretch=1)

        self._last_effort_div = QWidget()
        self._last_effort_div.setProperty("testid", "queue-last-effort")
        self._last_effort_div.setStyleSheet("background: transparent;")
        _ledl = QHBoxLayout(self._last_effort_div)
        _ledl.setContentsMargins(0, 0, 0, 0)
        _ledl.setSpacing(4)
        _ledl.addStretch(1)
        self._last_effort_label = QLabel("/effort: —")
        self._last_effort_label.setProperty("testid", "queue-last-effort-value")
        self._last_effort_label.setStyleSheet(_ME_LBL_BASE)
        _ledl.addWidget(self._last_effort_label)
        _mel.addWidget(self._last_effort_div, stretch=1)

        self._last_model_value: str = ""
        self._last_effort_value: str = ""

        main_layout.addWidget(self._model_effort_row)

        # Template indicator label — shows which template/button was clicked.
        self._template_row = QWidget()
        self._template_row.setFixedHeight(28)
        self._template_row.setStyleSheet(
            "QWidget { background-color: #1C1C1F;"
            " border-bottom: 1px solid #3F3F46; }"
        )
        _trl = QHBoxLayout(self._template_row)
        _trl.setContentsMargins(0, 0, 6, 0)
        _trl.setSpacing(4)

        self._template_label = _TemplateLabel()
        self._template_label.setProperty("testid", "queue-template-label")
        self._template_label.setStyleSheet(
            "background: transparent; color: #A1A1AA;"
            " border: none; padding: 4px 10px; font-size: 11px;"
        )
        _trl.addWidget(self._template_label, stretch=1)

        # Sempre visivel (mudanca 2026-05-17 P4) — row sincroniza via signal
        # mas _TemplateLabel.setVisible(False) e no-op, entao a row tambem.
        self._template_row.setVisible(True)
        self._template_label.visibility_changed.connect(
            self._template_row.setVisible
        )
        main_layout.addWidget(self._template_row)

        # Last command played — row horizontal (mudanca 2026-05-17 P1/P3):
        # 'Last command:' (sempre visivel) + nn/nn (count, reparenteado de
        # metrics_bar via attach_count_label) + comando-sem-args + eye-icon
        # (hover toast com comando completo).
        self._last_cmd_row = QWidget()
        self._last_cmd_row.setProperty("testid", "queue-last-command")
        self._last_cmd_row.setStyleSheet(
            "QWidget { background-color: #1C1C1F;"
            " border-bottom: 1px solid #3F3F46; }"
        )
        _lcl = QHBoxLayout(self._last_cmd_row)
        _lcl.setContentsMargins(10, 4, 10, 4)
        _lcl.setSpacing(6)

        _LBL_BASE = (
            "background: transparent; border: none;"
            " color: #D4D4D8; font-size: 11px; font-family: monospace;"
        )

        self._last_cmd_prefix_label = QLabel("Last command:")
        self._last_cmd_prefix_label.setStyleSheet(_LBL_BASE)
        _lcl.addWidget(self._last_cmd_prefix_label)

        # Placeholder slot pro count label (queue-count-label) — preenchido
        # via attach_count_label() chamado pelo main_window apos o assembly.
        self._last_cmd_count_slot = QWidget()
        self._last_cmd_count_slot.setStyleSheet("background: transparent;")
        _count_slot_layout = QHBoxLayout(self._last_cmd_count_slot)
        _count_slot_layout.setContentsMargins(0, 0, 0, 0)
        _count_slot_layout.setSpacing(0)
        self._last_cmd_count_slot_layout = _count_slot_layout
        _lcl.addWidget(self._last_cmd_count_slot)

        # Label com comando sem argumentos (ex: "/create-task").
        self._last_cmd_label = QLabel("")
        self._last_cmd_label.setProperty("testid", "queue-last-command-cmd")
        self._last_cmd_label.setStyleSheet(_LBL_BASE)
        _lcl.addWidget(self._last_cmd_label)

        # Eye-icon: QLabel clicavel/hover com QToolTip mostrando o comando
        # completo (com args). Usa caractere unicode pra evitar dependencia
        # de SVG aqui.
        self._last_cmd_eye = QLabel("\U0001F441")  # eye emoji
        self._last_cmd_eye.setProperty("testid", "queue-last-command-eye")
        self._last_cmd_eye.setStyleSheet(
            "background: transparent; border: none; color: #A1A1AA;"
            " font-size: 12px;"
        )
        self._last_cmd_eye.setToolTip("")
        _lcl.addWidget(self._last_cmd_eye)
        _lcl.addStretch(1)

        # Estado inicial (P3): so o prefixo visivel; count/cmd/eye hidden.
        self._last_cmd_count_slot.setVisible(False)
        self._last_cmd_label.setVisible(False)
        self._last_cmd_eye.setVisible(False)

        # Texto completo do ultimo comando (com args) — usado por
        # get_last_command_text() para restore_queue_snapshot.
        self._last_cmd_full: str = ""

        main_layout.addWidget(self._last_cmd_row)

        # Stacked content (empty state vs list)
        # Notepad foi removido em Iter 12 — _content_stack agora ocupa toda a
        # area abaixo da play_bar sem splitter intermediario.
        self._content_stack = QWidget()
        content_layout = QVBoxLayout(self._content_stack)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self._content_stack.setMinimumHeight(100)
        main_layout.addWidget(self._content_stack, stretch=1)

        # Empty state — placeholder vazio (texto e botao "Criar Pipeline"
        # removidos; criacao de pipeline acontece via outros fluxos).
        self._empty_widget = QWidget()
        el = QVBoxLayout(self._empty_widget)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.setSpacing(0)

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
        self._items_container.setProperty("testid", "queue-command-list")
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
        add_bar.setProperty("testid", "queue-add-bar")
        add_bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        add_bar.setFixedHeight(36)
        al = QHBoxLayout(add_bar)
        al.setContentsMargins(8, 4, 8, 4)
        add_btn = QPushButton("[+] Adicionar Comando")
        add_btn.setProperty("testid", "queue-btn-add-command")
        add_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #FBBF24;"
            "  border: none; font-size: 12px; }"
            "QPushButton:hover { color: #FDE68A; }"
        )
        add_btn.clicked.connect(self._on_inline_add_clicked)
        al.addWidget(add_btn)

        save_btn = QPushButton("💾 Salvar")
        save_btn.setProperty("testid", "queue-btn-save")
        save_btn.setToolTip("Salvar fila no JSON do projeto (Ctrl+S)")
        save_btn.setFixedHeight(26)
        save_btn.setEnabled(False)
        save_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 3px;"
            "  font-size: 11px; padding: 2px 8px; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; border-color: #FBBF24; }"
            "QPushButton:disabled { background-color: #27272A; color: #52525B; border-color: #3F3F46; }"
        )
        save_btn.clicked.connect(self.save_requested)
        al.addWidget(save_btn)
        self._save_btn = save_btn

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
        self._add_bar = add_bar
        content_layout.addWidget(self._add_bar)

    def _connect_signals(self) -> None:
        signal_bus.pipeline_ready.connect(self.load_pipeline)
        signal_bus.command_started.connect(self._on_command_started)
        signal_bus.command_completed.connect(self._on_command_completed)
        signal_bus.command_failed.connect(self._on_command_failed)
        signal_bus.command_skipped.connect(self._on_command_skipped)
        signal_bus.pipeline_error_occurred.connect(self._on_pipeline_error_with_message)
        signal_bus.interactive_advance_ready.connect(self._on_interactive_advance_ready)
        signal_bus.instance_selected.connect(self._on_instance_selected)
        signal_bus.autocast_step_requested.connect(self._on_autocast_step_requested)
        signal_bus.autocast_abort_requested.connect(self._on_autocast_abort_requested)
        signal_bus.interactive_input_requested.connect(self._cancel_pending_modal_enter)
        signal_bus.request_recovery_command.connect(self._on_request_recovery_command)
        signal_bus.codex_availability_changed.connect(
            self._on_codex_availability_changed
        )
        signal_bus.config_loaded.connect(self._on_config_loaded_for_governance)
        signal_bus.config_unloaded.connect(self._on_config_unloaded_for_governance)
        self._btn_next.clicked.connect(self._on_btn_next_clicked)

    def _on_config_loaded_for_governance(self, _path: str) -> None:
        self._refresh_governance_button_state()

    def _on_config_unloaded_for_governance(self) -> None:
        self._refresh_governance_button_state()

    def _on_codex_availability_changed(self, alive: bool) -> None:
        """Espelha a prontidao do T3 (terminal-codex-output) para o gate da
        condicao de falha 4 do botao unico (task 006).

        Emitido por main_window (`_codex_terminal_available`) sempre que o
        terminal Codex aparece/some. `_dispatch_codex_command(to_t1=False)` le
        este flag e aborta com toast quando o destino T3 nao esta pronto, em vez
        de publicar num terminal inexistente (Zero Silencio)."""
        self._codex_t3_available = bool(alive)

    def _on_autocast_abort_requested(self, cause: str, channel: str) -> None:
        """Desliga o botao autocast quando um listener entra em estado failed.

        Emitido por MetricsBar._on_terminal_force_failed apos receber
        terminal_force_failed (pattern matcher, exit-code watcher ou
        wf-notify.sh --status failure). Ver workflow-app-listeners.md §3.
        """
        if self._btn_autocast.isChecked():
            self._btn_autocast.setChecked(False)

    def _on_autocast_step_requested(self) -> None:
        """Programmatic click on `queue-btn-play-next` driven by the autocast loop.

        Emits no-op when the button is disabled (e.g. queue empty or already
        running) — the autocast state machine in MetricsBar interprets the
        absence of a busy transition as 'queue empty' and stops itself.
        """
        if self._play_btn.isEnabled():
            self._play_btn.click()

    # ──────────────────────────────────── Section tabs (accordion) ─── #

    def _build_section_grid(
        self, buttons: list[tuple[str, str, object, str] | QWidget], cols: int = 3
    ) -> QWidget:
        """Create a content widget with a 3-column grid of styled buttons."""
        content = QWidget()
        content.setStyleSheet("background-color: #27272A;")
        grid = QGridLayout(content)
        grid.setContentsMargins(5, 4, 5, 5)
        grid.setSpacing(3)
        for i, item in enumerate(buttons):
            if isinstance(item, QWidget):
                grid.addWidget(item, i // cols, i % cols)
            else:
                label, tooltip, callback, testid = item
                btn = QPushButton(label)
                btn.setToolTip(tooltip)
                btn.setStyleSheet(_SECTION_BTN_STYLE)
                if testid:
                    btn.setProperty("testid", testid)
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
            if i == 3:
                # insertions_content lives in output-toolbar-center — always visible.
                # insertions_btn is not in any layout. Skip both to avoid toggling.
                continue
            active = i == self._active_section
            btn.setStyleSheet(_TAB_ACTIVE_STYLE if active else _TAB_INACTIVE_STYLE)
            content.setVisible(active)

    # ──────────────────────────────────────────────────── Public API ─── #

    def set_pipeline_manager(self, pipeline_manager) -> None:
        """Inject the PipelineManager to enable can_reorder guards."""
        self._pipeline_manager = pipeline_manager

    # ── Sub-tab populate helpers (refactor 2026-05-18) ────────────────────── #
    # Os 3 métodos populate_*_tab foram substituídos por 4 métodos semânticos
    # que alimentam as sub-abas do QTabWidget queue-subtabs-insertions.
    # Cada um é idempotente: limpa o layout antes de inserir.

    def _populate_subtab(self, layout: QLayout, widgets: list[QWidget]) -> None:
        """Helper interno: limpa layout e insere widgets no flow responsivo."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for w in widgets:
            layout.addWidget(w)
        layout.invalidate()

    def populate_paths_subtab(
        self, widgets: list[QWidget], second_row: list[QWidget] | None = None,
    ) -> None:
        """Sub-aba 'Paths': JSON, WS, Workflow App + campos basic_flow.

        `second_row` (opcional) e anexado ao mesmo fluxo responsivo — usado
        pelo botao 'repo rules'. O limite de 4 linhas vale para a sub-aba toda.
        """
        self._populate_subtab(self._subtab_paths_layout, widgets + (second_row or []))

    def populate_prompts_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'prompts': botoes de prompt construídos a partir de arquivos .md."""
        self._populate_subtab(self._subtab_prompts_layout, widgets)

    def populate_rules_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'rules': dcp-list, cmd-list, terminal, listeners, indicators, add-rules."""
        self._populate_subtab(self._subtab_rules_layout, widgets)

    def populate_cmd_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'CMD': comandos avulsos que colam um slash-command no terminal."""
        self._populate_subtab(self._subtab_cmd_layout, widgets)

    def populate_auto_improove_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'AUTO IMPROOVE': comandos de melhoria continua de assets SystemForge."""
        self._populate_subtab(self._subtab_auto_improove_layout, widgets)

    def populate_personal_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'PERSONAL': comandos pessoais (curriculum, imbound, mkt)."""
        self._populate_subtab(self._subtab_personal_layout, widgets)

    def populate_personas_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'PERSONAS': botoes que colam o path de arquivos .md de personas."""
        self._populate_subtab(self._subtab_personas_layout, widgets)

    def add_persona_buttons(
        self, new_btns: list[QWidget], keep_last: QWidget | None = None,
    ) -> None:
        """Anexa botoes de persona ao flow da sub-aba PERSONAS ao vivo.

        Diferente de populate_personas_subtab (que limpa e repopula), este
        metodo PRESERVA os botoes existentes e apenas acrescenta os novos —
        usado pelo botao 'update' (queue-btn-personas-update).

        Se `keep_last` (o botao 'update' 1:1) for fornecido, ele e destacado
        da posicao atual e re-anexado ao final, garantindo que os novos botoes
        de persona entrem ANTES dele (update permanece sempre o ultimo widget).
        """
        layout = self._subtab_personas_layout
        if keep_last is not None:
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item is not None and item.widget() is keep_last:
                    layout.takeAt(i)
                    break
        for w in new_btns:
            layout.addWidget(w)
        if keep_last is not None:
            layout.addWidget(keep_last)
        layout.invalidate()

    def attach_tab_bar_extras(self, *extras: QWidget) -> None:
        """Anexa widgets ao bloco de inserções, apos a aba Inserções.

        Usado para terminal-route-toggles, que fica agrupado com
        queue-tab-terminal-insertions e nao disputa espaco com as abas
        primarias.
        """
        for w in extras:
            self._insertions_bar_layout.addWidget(w)

    def attach_subtab_corner_widget(self, widget: QWidget) -> None:
        """Posiciona um widget no canto direito da tab bar das sub-abas de
        inserções (PATHS/PROMPTS/RULES), na mesma row dos botoes de aba.

        Usado para o toolbar-prompts-config-gear, que passa a viver ao lado
        das abas em vez de no bloco insertions_bar.
        """
        self._insertions_subtabs.setCornerWidget(
            widget, Qt.Corner.TopRightCorner
        )

    def attach_count_label(self, count_label: QLabel) -> None:
        """Reparenteia o queue-count-label (owned por MetricsBar) para o
        slot dentro do queue-last-command. Idempotente.

        O label continua sendo atualizado por MetricsBar via signal
        `metrics_updated` -> `_on_metrics_updated_for_ring` (so muda o
        parent visual, nao o pipeline de signals).
        """
        count_label.setParent(self._last_cmd_count_slot)
        count_label.setStyleSheet(
            "background: transparent; border: none; color: #FBBF24;"
            " font-size: 11px; font-weight: 700; font-family: monospace;"
        )
        count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Limpa state legacy de embed_count_label.
        count_label.setFixedSize(0, 0)
        count_label.setMinimumSize(0, 0)
        count_label.setMaximumSize(16777215, 16777215)
        # Limpa o slot e adiciona o label.
        while self._last_cmd_count_slot_layout.count():
            self._last_cmd_count_slot_layout.takeAt(0)
        self._last_cmd_count_slot_layout.addWidget(count_label)
        # Garante visibilidade: a row-mae nao muda, mas o slot e mostrado/escondido
        # via _on_run_command/clear_queue (P3).

    def install_template_tracker(self) -> None:
        """Instala um event filter nas 3 tabs (pipelines/workflow/auxiliar)
        que captura clicks em QPushButton e atualiza queue-template-label
        com o testid do botao clicado.

        Chamado pelo main_window apos populate_* terminar. A tab
        terminal-insertions (indice 3) NAO e rastreada (regra P4).
        """
        if not hasattr(self, "_sec_contents"):
            return
        if not hasattr(self, "_tracked_section_indices"):
            self._tracked_section_indices = (0, 1, 2)
        tracked = self._tracked_section_indices
        for idx in tracked:
            if idx < len(self._sec_contents):
                self._sec_contents[idx].installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        # P4: detecta MouseButtonRelease em QPushButton dentro das 3 tabs
        # rastreadas, e atualiza queue-template-label com o testid do botao
        # via QTimer.singleShot(0, ...) — defer garante que executa apos os
        # slots `clicked` que esses botoes ja conectam (incluindo
        # _template_label.setText calls existentes).
        try:
            if event.type() == QEvent.Type.MouseButtonRelease:
                tracked = getattr(self, "_tracked_section_indices", ())
                if any(
                    idx < len(self._sec_contents) and obj is self._sec_contents[idx]
                    for idx in tracked
                ):
                    pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                    child = obj.childAt(pos)
                    while child is not None and not isinstance(child, QPushButton):
                        child = child.parentWidget()
                        if child is obj:
                            child = None
                            break
                    if isinstance(child, QPushButton):
                        testid = child.property("testid")
                        if isinstance(testid, str) and testid:
                            QTimer.singleShot(
                                0, lambda tid=testid: self._template_label.set_value(tid)
                            )
        except Exception:
            pass
        return super().eventFilter(obj, event)

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
        self._maybe_auto_save(name)

    def _load_quick_template(self, template: list[CommandSpec], *, name: str = "") -> None:
        """Emit pipeline_ready with a fresh copy of a factory template.

        Inserts a '/model X' row before each command where the model changes,
        so the user only needs to switch models at transition points.
        The model rows carry no config_path.
        Skips /clear for model tracking — no /model sonnet before /clear.
        """
        if name:
            self._template_label.setText(f"  \U0001f4cb  {name}")
            self._template_label.setVisible(True)
            self._maybe_auto_save(name)

        raw = copy.deepcopy(template)

        expanded: list[CommandSpec] = []
        current_model = None
        for spec in raw:
            # Skip /clear for model tracking — it doesn't use a model
            if spec.name == "/clear":
                expanded.append(spec)
                continue  # Keep current_model — no /model needed if model didn't change
            # Skip injection when spec is already a /model switch (template has it explicit)
            if spec.name.startswith("/model "):
                current_model = spec.model
                expanded.append(spec)
                continue
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

    # ────────────────────────────────────────────────────────── DCP ── #

    def _apply_dcp_reader_gating(self, workflow_content: QWidget) -> None:
        """Init-time gating for the workflow tab's DCP buttons.

        `[DCP: Specific-Flow]` is disabled when `workflow_app.dcp.READER_AVAILABLE`
        is false — it requires delivery_reader (T-035) to resolve the module and
        locate SPECIFIC-FLOW.json.

        Reading `dcp_pkg.READER_AVAILABLE` (instead of the imported symbol)
        lets pytest monkeypatch the flag without `importlib.reload`.
        """
        if dcp_pkg.READER_AVAILABLE:
            return
        logger.warning(
            "[DCP] reader ausente — DCP: Specific-Flow desabilitado"
        )
        for btn in workflow_content.findChildren(QPushButton):
            if btn.property("testid") == "queue-btn-dcp-specific-flow":
                btn.setEnabled(False)
                btn.setToolTip("Requer T-035 (reader)")
                break

    def _on_modules_clicked(self) -> None:
        """Carrega TEMPLATE_MODULES com fallback defensivo para ROCK-MAP.md.

        3 cenarios de fallback (conforme _DECISIONS-ITERS-9-11.md > Iter 9 > GAP 2.6
        e GAP 5.1):
          (a) ROCK-MAP.md ausente: toast info, log informativo.
          (b) ROCK-MAP.md malformado (parse error): toast warning, log com error_class.
          (c) ROCK-MAP.md com 0 rocks alem do skeleton: toast info "0 rocks, fila
              estatica (feature trivial)".

        Em todos os 3 cenarios, carrega TEMPLATE_MODULES estatico via
        `_load_quick_template` (alinhado com §21.4 v2). Expansao dinamica por
        N rocks fica para o module `modules-phase` (Sem 3).
        """
        import logging
        from pathlib import Path

        from workflow_app.config.app_state import app_state

        log = logging.getLogger(__name__)

        rock_map_path: Path | None = None
        fallback_reason = "missing"
        try:
            if app_state.has_config and app_state.config is not None:
                brief_root = getattr(app_state.config, "brief_root", None)
                project_dir = getattr(app_state.config, "project_dir", None)
                if brief_root and project_dir:
                    rock_map_path = Path(project_dir) / brief_root / "ROCK-MAP.md"
        except Exception as exc:  # noqa: BLE001 - defensivo, qualquer erro = fallback
            log.warning("[modules] erro ao resolver brief_root: %s: %s",
                        type(exc).__name__, exc)

        if rock_map_path is None or not rock_map_path.exists():
            log.info(
                "[modules] ROCK-MAP.md ausente (path=%s); usando TEMPLATE_MODULES "
                "estatico (operador nao rodou /break-intake ou projeto e single-rock).",
                rock_map_path,
            )
            signal_bus.toast_requested.emit("Sem ROCK-MAP, fila estatica", "info")
            return self._load_quick_template(TEMPLATE_MODULES, name="Modules")

        # ROCK-MAP.md existe; tentar parse defensivo
        try:
            content = rock_map_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning(
                "[modules] ROCK-MAP.md mal formado em %s (%s: %s); fallback para "
                "TEMPLATE_MODULES estatico. Re-rode /break-intake ou edite manualmente.",
                rock_map_path, type(exc).__name__, exc,
            )
            signal_bus.toast_requested.emit(
                "ROCK-MAP corrompido, fila estatica", "warning"
            )
            return self._load_quick_template(TEMPLATE_MODULES, name="Modules")

        # Conta rocks: linhas com pattern INTAKE-ROCK-{N}.md (exclui skeleton)
        import re

        try:
            rock_matches = re.findall(r"INTAKE-ROCK-(\d+)\.md", content)
            n_rocks = len(set(rock_matches))
        except Exception as exc:  # noqa: BLE001 - parse defensivo
            log.warning(
                "[modules] ROCK-MAP.md parse falhou em %s (%s: %s); fallback estatico.",
                rock_map_path, type(exc).__name__, exc,
            )
            signal_bus.toast_requested.emit(
                "ROCK-MAP corrompido, fila estatica", "warning"
            )
            return self._load_quick_template(TEMPLATE_MODULES, name="Modules")

        if n_rocks == 0:
            log.info(
                "[modules] ROCK-MAP.md tem 0 rocks alem do skeleton em %s; "
                "feature trivial, usando TEMPLATE_MODULES estatico "
                "(sem checklist-loop expansion).",
                rock_map_path,
            )
            signal_bus.toast_requested.emit(
                "0 rocks, fila estatica (feature trivial)", "info"
            )
            return self._load_quick_template(TEMPLATE_MODULES, name="Modules")

        # ROCK-MAP valido com N rocks - expansao dinamica fica para Sem 3 module.
        # Por enquanto carrega template base + log informativo.
        log.info(
            "[modules] ROCK-MAP.md OK em %s (%d rocks); carregando TEMPLATE_MODULES "
            "base (expansao dinamica pendente do module modules-phase).",
            rock_map_path, n_rocks,
        )
        return self._load_quick_template(TEMPLATE_MODULES, name="Modules")

    def _dcp_build_preflight(self) -> Optional[DcpBuildContext]:
        """Run the 6 MVP gates for `queue-btn-dcp-build` and return context.

        Gates (per Codex review T-013/T-052):
          1. has_config (project loaded)
          2. delivery.json exists + DeliveryFound (CLI requires it; no bootstrap)
          3. execution_mode != parallel-independent (or block ambiguous case)
          4. current_module exists, module exists, state != done
          5. MODULE-META.json exists, parses, has minimal canonical fields
          6. dependency readiness for pending → creation transitions

        On failure: emits the appropriate ``QMessageBox`` and returns ``None``
        (caller must abort). On success: returns ``DcpBuildContext`` with
        ``regenerate=True`` when module state is past pending so the
        SPECIFIC-FLOW is re-emitted without re-transitioning state.

        Reader-unavailable fallback (bare paste) is handled by the caller and
        is NOT a gate failure — preflight only runs when reader is available.
        """
        from PySide6.QtWidgets import QMessageBox

        from workflow_app.config.app_state import app_state

        # Gate 1 — project loaded
        if not app_state.has_config or app_state.config is None:
            logger.info("[DCP] build clicked without project — showing prompt")
            QMessageBox.information(
                self,
                "DCP",
                "Carregue um projeto (pill superior) antes de gerar pipeline DCP.",
            )
            return None
        config = app_state.config

        from workflow_app.dcp.specific_flow_handler import _resolve_wbs_root
        from workflow_app.services.delivery_reader import (
            DeliveryFound,
            DeliveryFutureVersion,
            DeliveryInvalid,
            DeliveryMissing,
            DeliveryReader,
        )

        wbs_root = _resolve_wbs_root(config)
        result = DeliveryReader().load(wbs_root)

        # Gate 2 — delivery.json present and structurally OK
        if isinstance(result, DeliveryMissing):
            QMessageBox.information(
                self, "DCP",
                "delivery.json ausente. Rode primeiro a Phase A:\n"
                "  1. Brief — Novo Projeto (queue-btn-brief-new), e\n"
                "  2. Modules (Creation) (queue-btn-modules)\n"
                "Depois volte ao DCP: Gerar Pipeline.",
            )
            return None
        if isinstance(result, DeliveryInvalid):
            body, clipboard_text = format_delivery_invalid_popup(
                result.path, result.error, result.details,
            )
            project_slug = (
                getattr(config, "project_name", None)
                or getattr(config, "name", None)
                or "(desconhecido)"
            )
            # Telemetry: count of distinct schema errors and project slug so
            # operators can correlate popups with logs without re-parsing JSON.
            try:
                _err_count = (
                    len(json.loads(result.details))
                    if result.details
                    else 0
                )
            except (json.JSONDecodeError, TypeError):
                _err_count = 0
            logger.info(
                "DCP preflight Gate 2 fail: %d errors in delivery.json (project=%s)",
                _err_count, project_slug,
            )
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("DCP build cancelado: delivery.json invalido")
            box.setText(body)
            box.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            copy_btn = box.addButton(
                "Copiar erros", QMessageBox.ButtonRole.ActionRole
            )
            close_btn = box.addButton(
                "Fechar", QMessageBox.ButtonRole.RejectRole
            )
            box.setDefaultButton(close_btn)
            box.exec()
            if box.clickedButton() is copy_btn:
                QApplication.clipboard().setText(clipboard_text)
                signal_bus.toast_requested.emit(
                    "Erros copiados para o clipboard.", "info"
                )
            return None
        if isinstance(result, DeliveryFutureVersion):
            QMessageBox.information(self, "DCP", result.message)
            return None

        assert isinstance(result, DeliveryFound)
        delivery = result.delivery

        # Gate 3 — parallel-independent requires explicit module selection
        if delivery.execution_mode == "parallel-independent":
            QMessageBox.information(
                self, "DCP",
                "execution_mode=parallel-independent requer selecao explicita "
                "do modulo. Use o botao DCP no card do modulo desejado.",
            )
            return None

        # Gate 4 — current_module is set, exists in modules, not done
        cm_id = delivery.current_module
        if not cm_id:
            QMessageBox.information(
                self, "DCP",
                "current_module nao definido em delivery.json. "
                "Rode /modules:create-structure ou /delivery:validate.",
            )
            return None
        if delivery.modules and all(
            m.state == "done" for m in delivery.modules.values()
        ):
            QMessageBox.information(
                self, "DCP", "Todos os modulos estao concluidos."
            )
            return None
        module = delivery.modules.get(cm_id)
        if module is None:
            QMessageBox.information(
                self, "DCP",
                f"current_module={cm_id!r} nao existe em modules. "
                "Rode /delivery:validate.",
            )
            return None
        if module.state == "done":
            # current_module aponta para um modulo `done` — o auto-advance
            # canonico nao rodou no ultimo /commit:* deste modulo (closer
            # pulado/legacy, ou um bug anterior do closer abortava antes de
            # escrever delivery.json). O owner UNICO do advance e o closer de
            # commit `dcp_closer.cmd_close` (/commit:*), NAO /delivery:sign-off
            # — a Opcao C (sign-off muta current_module) foi explicitamente
            # rejeitada em workflow-app-command-lists.md §9.
            #
            # Sugere o proximo modulo ELEGIVEL espelhando _next_eligible_module:
            # state==pending E todas as deps internas em `done` (I-10). O
            # dep-gating e obrigatorio — sem ele (bug antigo:
            # sorted-alphabetical puro) o primeiro pending alfabetico era
            # `module-10`, cujas deps (module-6/7/8) ainda estavam pending,
            # gerando uma sugestao impossivel. Hint NAO-autoritativo: quem muta
            # current_module continua sendo o closer.
            states = {mid: m.state for mid, m in delivery.modules.items()}
            next_eligible = next(
                (
                    mid
                    for mid in sorted(delivery.modules.keys())
                    if delivery.modules[mid].state == "pending"
                    and all(
                        states.get(dep) == "done"
                        for dep in delivery.modules[mid].dependencies
                        if dep in states  # external deps (not in set) = satisfied
                    )
                ),
                None,
            )
            logger.info(
                "DCP G4 fail: current_module=%s state=done; next_eligible=%s",
                cm_id, next_eligible,
            )
            if next_eligible:
                hint = (
                    f"\n\nProximo modulo elegivel: {next_eligible!r}.\n"
                    "Recuperacao one-shot (workaround §9): edite "
                    f"delivery.current_module = {next_eligible!r} e rode "
                    "/delivery:validate. Os proximos /commit:* avancam sozinhos."
                )
            else:
                hint = (
                    "\n\nNenhum modulo pending com dependencias resolvidas. "
                    "Se ainda ha modulos pending, suas deps internas nao estao "
                    "todas em `done` (verifique o DAG). Se nao ha mais nenhum, "
                    "o projeto esta completo — rode /delivery:sign-off."
                )
            QMessageBox.information(
                self, "DCP",
                f"Modulo {cm_id!r} ja concluido, mas current_module nao "
                "avancou. O avanco e responsabilidade do closer de /commit:* "
                "(dcp_closer), NAO de /delivery:sign-off (que nao muta "
                f"current_module).{hint}",
            )
            return None

        # Gate 5 — MODULE-META.json exists, parses, has minimal canonical fields
        meta_path = wbs_root / "modules" / cm_id / "MODULE-META.json"
        if not meta_path.exists():
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json ausente em {meta_path.name}. Phase A nao "
                "foi completada. Rode Modules (queue-btn-modules).",
            )
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json corrupto: {exc}. "
                "Re-rode Modules (queue-btn-modules).",
            )
            return None
        required_keys = {"module_id", "module_name", "module_type"}
        missing = required_keys - set(meta.keys())
        if missing:
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json incompleto. Faltam: {sorted(missing)}. "
                "Re-rode Modules (queue-btn-modules).",
            )
            return None
        # Identity check — meta.module_id MUST match delivery.json[modules] key,
        # otherwise we'd run pipeline against the wrong module's spec.
        if meta.get("module_id") != cm_id:
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json identifica module_id={meta.get('module_id')!r} "
                f"mas delivery.json aponta current_module={cm_id!r}. "
                "Resolva o desalinhamento antes de prosseguir.",
            )
            return None

        # Gate 6 — dependency readiness (mirrors CLI invariant I-10, step 11).
        # Only for pending → creation; modules past pending were already gated at
        # their own transition. Without this check the button pastes a command
        # destined to exit 1 with a cryptic CLI message.
        if module.state == "pending" and module.dependencies:
            blockers = [
                dep_id
                for dep_id in module.dependencies
                if dep_id not in delivery.modules
                or delivery.modules[dep_id].state != "done"
            ]
            if blockers:
                dep_lines = []
                for dep_id in blockers:
                    dep = delivery.modules.get(dep_id)
                    state_label = dep.state if dep else "ausente"
                    dep_lines.append(f"  • {dep_id} — {state_label}")
                QMessageBox.warning(
                    self,
                    "DCP — Dependências não concluídas",
                    f"Módulo {cm_id!r} não pode iniciar (pending → creation).\n\n"
                    "Dependências pendentes:\n" + "\n".join(dep_lines) + "\n\n"
                    "Complete o loop de cada dependência até state=done primeiro.",
                )
                return None

        # All gates passed — choose --regenerate when module is past pending
        regenerate = module.state != "pending"
        return DcpBuildContext(
            cm_id=cm_id,
            module_state=module.state,
            regenerate=regenerate,
            wbs_root=wbs_root,
            delivery=delivery,
        )

    @staticmethod
    def _read_flow_cmd_count(flow_path: Path) -> int | None:
        """Return the length of `commands[]` in SPECIFIC-FLOW.json, or None
        when the file cannot be parsed. Shared by the legacy paste handler
        and the new B-dcp pipeline handler so both surface the same
        metadata in the destructive-guard modal.
        """
        try:
            flow_data = json.loads(flow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(flow_data, dict):
            return None
        commands_raw = flow_data.get("commands")
        if not isinstance(commands_raw, list):
            return None
        return len(commands_raw)

    def _on_dcp_build_pipeline_clicked(self) -> None:
        """Enqueue the B-dcp pipeline with 6 visible items in queue-command-list.

        Pipeline shape (positions 1..6):
            1. /build-module-pipeline [--regenerate] --module {N}
               (config_path injetado por main_window._on_pipeline_ready)
            2. /dcp:congruence-check --module {N}
            3. /dcp:temporality-check --module {N}
            4. /dcp:meta-completeness --module {N}
            5. /dcp:directive-injector --module {N} --in-place
            6. (local-action) dcp-load-specific-flow

        Uses `_dcp_build_preflight` for gate evaluation, including the
        destructive guard (ConfirmRegenerateSpecificFlowModal) when
        `--regenerate` would overwrite an existing SPECIFIC-FLOW.json.

        Arms `self._pending_dcp_load_ctx` so the local action at position 6
        (`_handle_dcp_load_specific_flow`) can pick up the same module
        context after the 5 slash commands have regenerated the flow file.
        """
        from workflow_app.config.app_state import app_state

        ctx = self._dcp_build_preflight()
        if ctx is None:
            return

        # Defensive: preflight requires has_config==True, so config is non-None.
        config = app_state.config
        assert config is not None

        # Destructive guard — when --regenerate AND SPECIFIC-FLOW.json
        # already exists on disk, surface metadata + warn about manual-edit
        # loss before enqueueing. Mirrors the legacy paste handler.
        if ctx.regenerate:
            flow_path = ctx.wbs_root / "modules" / ctx.cm_id / "SPECIFIC-FLOW.json"
            if flow_path.exists():
                from workflow_app.dialogs.confirm_regenerate_specific_flow_modal import (
                    ConfirmRegenerateSpecificFlowModal,
                )
                command_count = self._read_flow_cmd_count(flow_path)
                modal = ConfirmRegenerateSpecificFlowModal(
                    flow_path=flow_path,
                    command_count=command_count,
                    cm_id=ctx.cm_id,
                    parent=self,
                )
                if modal.exec() != QDialog.DialogCode.Accepted:
                    logger.info(
                        "[DCP] pipeline regen cancelado pelo usuario "
                        "(modulo=%s, cmds=%s)",
                        ctx.cm_id, command_count,
                    )
                    return

        # Resolve helpers (kept lazy to avoid a heavy import at module load).
        from workflow_app.dcp.specific_flow_handler import _module_number

        module_num = _module_number(ctx.cm_id)
        regen_flag = " --regenerate" if ctx.regenerate else ""

        # NOTA: NAO concatenar {rel_cfg} no name aqui. main_window._on_pipeline_ready
        # injeta `spec.config_path = rel` (line ~2864) para specs sem prefixo
        # imune ([/boilerplate:, /auto-improove:, /blog:, /cmd:]), e o pty_runner.start()
        # faz append(config_path) ao argv. Se o name ja contiver o config, o resultado
        # final fica `/build-module-pipeline --module N <cfg> <cfg>` (config DUPLICADO),
        # argparse aborta com exit=2 silenciosamente e o gap de history vazio passa
        # batido pelo widget (bug capturado em 2026-05-18; post-check em
        # build_module_pipeline.py agora emite listener vermelho — ver
        # ai-forge/rules/workflow-app-listeners.md §2.2 VERIFY_FAILED).
        specs: list[CommandSpec] = [
            CommandSpec(
                name=f"/build-module-pipeline{regen_flag} --module {module_num}",
                model=ModelName.OPUS,
                interaction_type=InteractionType.AUTO,
                position=1,
                effort=EffortLevel.HIGH,
            ),
            CommandSpec(
                name=f"/dcp:congruence-check --module {module_num}",
                model=ModelName.SONNET,
                interaction_type=InteractionType.AUTO,
                position=2,
                effort=EffortLevel.HIGH,
            ),
            CommandSpec(
                name=f"/dcp:temporality-check --module {module_num}",
                model=ModelName.SONNET,
                interaction_type=InteractionType.AUTO,
                position=3,
                effort=EffortLevel.STANDARD,
            ),
            CommandSpec(
                name=f"/dcp:meta-completeness --module {module_num}",
                model=ModelName.SONNET,
                interaction_type=InteractionType.AUTO,
                position=4,
                effort=EffortLevel.STANDARD,
            ),
            CommandSpec(
                name=f"/dcp:directive-injector --module {module_num} --in-place",
                model=ModelName.SONNET,
                interaction_type=InteractionType.AUTO,
                position=5,
                effort=EffortLevel.STANDARD,
            ),
            CommandSpec(
                name="DCP: Carregar Specific-Flow",
                model=ModelName.SONNET,
                interaction_type=InteractionType.AUTO,
                position=6,
                effort=EffortLevel.LOW,
                kind="local-action",
                local_action_id="dcp-load-specific-flow",
            ),
        ]

        # Inject canonical /clear + /model + /effort block headers between
        # commands (same pattern as quick_templates). Without this the pipeline
        # is enqueued as a single sequential block without directives, which
        # contradicts WORKFLOW-APP-RULES GROUP_MAP for B-dcp items.
        from workflow_app.templates.quick_templates import _inject_clears
        expanded_specs = _inject_clears(specs)

        self._pending_dcp_load_ctx = ctx
        logger.info(
            "[DCP] enqueueing B-dcp pipeline (modulo=%s, regenerate=%s, items=%d, expanded=%d)",
            ctx.cm_id, ctx.regenerate, len(specs), len(expanded_specs),
        )
        signal_bus.pipeline_ready.emit(expanded_specs)

    def _find_governance_button(self, root: QWidget | None = None) -> QPushButton | None:
        search_root = root or getattr(self, "header_widget", None) or self
        for btn in search_root.findChildren(QPushButton):
            if btn.property("testid") == "queue-btn-governance":
                return btn
        return None

    @staticmethod
    def _resolve_config_path(config: object, path_value: object) -> Path | None:
        if not isinstance(path_value, str) or not path_value.strip():
            return None
        path = Path(path_value)
        if path.is_absolute():
            return path
        project_dir = getattr(config, "project_dir", None)
        if project_dir is None:
            return None
        return Path(project_dir) / path

    def _governance_ledger_path(self) -> Path | None:
        from workflow_app.config.app_state import app_state

        if not app_state.has_config or app_state.config is None:
            return None
        docs_root = self._resolve_config_path(
            app_state.config, getattr(app_state.config, "docs_root", None)
        )
        if docs_root is None:
            return None
        return docs_root / "_pipeline-research" / "PIPELINE-RUNS.tsv"

    @staticmethod
    def _governance_ledger_has_data(ledger_path: Path) -> bool:
        try:
            lines = ledger_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False
        data_lines = [line for line in lines[1:] if line.strip()]
        return bool(data_lines)

    def _governance_dryrun_dir(self) -> Path | None:
        from workflow_app.config.app_state import app_state

        if not app_state.has_config or app_state.config is None:
            return None
        project_dir = getattr(app_state.config, "project_dir", None)
        if project_dir is None:
            return None
        return Path(project_dir) / "scheduled-updates" / "governance-dry-run"

    def _latest_governance_dryrun_report(self) -> Path | None:
        dryrun_dir = self._governance_dryrun_dir()
        if dryrun_dir is None or not dryrun_dir.exists():
            return None
        reports = sorted(
            dryrun_dir.glob("GOVERNANCE-DRYRUN-*.md"),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
        return reports[0] if reports else None

    @staticmethod
    def _governance_dryrun_report_approved(report_path: Path) -> bool:
        try:
            text = report_path.read_text(encoding="utf-8")
        except OSError:
            return False
        if re.search(r"\b(abortado|aborted)\b", text, flags=re.IGNORECASE):
            return False
        return bool(
            re.search(
                r"(?im)^\s*forbidden_writes(?:\[\])?\s*:\s*(?:0|\[\s*\])\s*$",
                text,
            )
        )

    def _approved_governance_dryrun_report(self) -> Path | None:
        report_path = self._latest_governance_dryrun_report()
        if report_path is None:
            return None
        if not self._governance_dryrun_report_approved(report_path):
            return None
        return report_path

    def _governance_disabled_reason(self) -> str | None:
        ledger_path = self._governance_ledger_path()
        if ledger_path is None:
            return (
                "Carregue um project.json com docs_root antes de usar Governance."
            )
        if not ledger_path.exists():
            return f"Governance desabilitado: PIPELINE-RUNS.tsv ausente em {ledger_path}."
        if not self._governance_ledger_has_data(ledger_path):
            return (
                "Governance desabilitado: PIPELINE-RUNS.tsv existe, mas nao tem "
                "linhas de dados alem do cabecalho."
            )
        if self._approved_governance_dryrun_report() is None:
            dryrun_dir = self._governance_dryrun_dir()
            target = (
                str(dryrun_dir)
                if dryrun_dir is not None
                else "scheduled-updates/governance-dry-run"
            )
            return (
                "Governance desabilitado: rode /auto-flow governance --dry-run "
                f"e aprove um relatorio em {target} antes de aplicar."
            )
        return None

    def _refresh_governance_button_state(self, root: QWidget | None = None) -> None:
        btn = self._find_governance_button(root)
        if btn is None:
            return
        reason = self._governance_disabled_reason()
        if reason:
            btn.setEnabled(False)
            btn.setToolTip(reason)
            return
        btn.setEnabled(True)
        btn.setToolTip(
            "Enfileira a cadeia governance expandida de /auto-flow: "
            "scorecard, lessons, memory, meta e cmd. Nao usa /auto-flow governance "
            "como comando unico."
        )

    @staticmethod
    def _governance_specs() -> list[CommandSpec]:
        specs: list[CommandSpec] = []
        high_effort = {
            "/meta:propose-mechanism",
            "/cmd:experiment",
            "/cmd:accept-or-revert",
            "/meta:inject-mechanism-sandbox",
            "/cmd:execute-gap-tasks",
            "/cmd:gap-review",
        }
        for position, command in enumerate(GOVERNANCE_COMMANDS, start=1):
            effort = (
                EffortLevel.HIGH if command in high_effort else EffortLevel.STANDARD
            )
            model = (
                ModelName.OPUS
                if command in {"/meta:propose-mechanism", "/cmd:accept-or-revert"}
                else ModelName.SONNET
            )
            specs.append(
                CommandSpec(
                    name=command,
                    model=model,
                    interaction_type=InteractionType.AUTO,
                    position=position,
                    effort=effort,
                )
            )
        return specs

    def _confirm_governance_write_scope(self, ledger_path: Path) -> bool:
        from PySide6.QtWidgets import QMessageBox

        dryrun_report = self._approved_governance_dryrun_report()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Governance — confirmar escrita")
        box.setText(
            "A cadeia governance pode gravar artefatos de scorecard, lessons, "
            "memoria, backlog e experimentos de comando."
        )
        target_lines = "\n".join(f"  - {target}" for target in GOVERNANCE_WRITE_TARGETS)
        dryrun_line = f"\nDry-run aprovado: {dryrun_report}" if dryrun_report else ""
        box.setInformativeText(
            f"Preflight OK: {ledger_path}\n\n"
            f"{dryrun_line}\n\n"
            "Paths que podem ser mutados:\n"
            f"{target_lines}\n\n"
            "Enfileirar a cadeia governance agora?"
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        yes_btn = box.button(QMessageBox.StandardButton.Yes)
        if yes_btn is not None:
            yes_btn.setText("Enfileirar")
        cancel_btn = box.button(QMessageBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("Cancelar")
        return box.exec() == QMessageBox.StandardButton.Yes

    def _on_governance_clicked(self) -> None:
        self._refresh_governance_button_state()
        reason = self._governance_disabled_reason()
        if reason:
            signal_bus.toast_requested.emit(reason, "warning")
            return

        ledger_path = self._governance_ledger_path()
        assert ledger_path is not None
        if not self._confirm_governance_write_scope(ledger_path):
            signal_bus.toast_requested.emit("Governance cancelado.", "info")
            return

        from workflow_app.templates.quick_templates import _inject_clears

        specs = _inject_clears(self._governance_specs())
        self._template_label.setText("  \U0001f4cb  Governance")
        self._template_label.setVisible(True)
        self._maybe_auto_save("Governance")
        logger.info(
            "[governance] enqueueing expanded governance chain (commands=%d, specs=%d)",
            len(GOVERNANCE_COMMANDS), len(specs),
        )
        signal_bus.pipeline_ready.emit(specs)

    @staticmethod
    def _emit_dcp_meta_toast(module_dir: Path, *, verbose: bool = False) -> None:
        """Read ``meta-gaps-report.json`` from ``module_dir`` and emit a
        non-blocking toast via ``signal_bus.toast_requested``.

        Mapping (anti Zero Silencio):
          - ``total_gaps == 0`` AND ``verbose``  -> "success" (5s).
          - ``total_gaps == 0`` AND NOT verbose  -> suppressed (avoid noise).
          - ``total_gaps > 0`` AND any gap has ``confidence == "low"`` ->
            "warning" (6s) — pushes operator to act.
          - ``total_gaps > 0`` AND all gaps ``high``/``medium`` -> "info" (5s).

        The B-dcp gate 4 (``/dcp:meta-completeness``) is advisory: it
        writes ``meta-gaps-report.json`` with ``total_gaps`` and
        ``by_confidence`` aggregates. This handler runs at position 6 of
        the pipeline (after gate 4), reads the report and surfaces it as
        a toast so the operator never has to grep the audit dir.

        Silent no-op when the report is missing or malformed — gate 4
        may have skipped if MODULE-META was already validated within the
        300s idempotency TTL (and even in that case it does NOT bump
        the report). In NO_OP mode the report still exists; only true
        absence (gate 4 never ran for this module) yields silence here,
        which is acceptable because earlier validation gates already
        surfaced their own toasts.
        """
        report_path = module_dir / "meta-gaps-report.json"
        if not report_path.exists():
            return
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(report, dict):
            return

        total_gaps = report.get("total_gaps")
        if not isinstance(total_gaps, int):
            return
        by_confidence = report.get("by_confidence") or {}
        low_count = int(by_confidence.get("low", 0) or 0)

        if total_gaps == 0:
            if verbose:
                signal_bus.toast_requested.emit("Meta: completo (0 gaps)", "success")
            return

        if low_count > 0:
            signal_bus.toast_requested.emit(
                f"Meta: {total_gaps} gaps ({low_count} low confidence) "
                f"-- ver meta-gaps-report.json",
                "warning",
            )
        else:
            signal_bus.toast_requested.emit(
                f"Meta: {total_gaps} gaps (advisory) "
                f"-- ver meta-gaps-report.json",
                "info",
            )

    @staticmethod
    def _audit_display_dcp_reports(module_dir: Path, cm_id: str) -> None:
        """Surface congruence-report.json / temporality-report.json as a
        non-blocking informational toast.

        Replaces the legacy ``_check_dcp_validation_reports`` gate
        (task-028). Post-matrix architecture: the matrix already carries
        ``filter[]`` with bits flipped by the B-dcp gates, so the queue
        derived from it cannot contain commands that violated congruence
        or temporality. There is no "load anyway with violations" path
        because violations already zeroed the corresponding bits.

        The reports are kept as audit-only mirror: this method reads
        their flip counts and emits a single info toast so the operator
        has a one-glance summary without grepping the audit dir.

        Silent no-op when both reports are missing or unreadable
        (e.g. bare /dcp:specific-flow path without preflight).
        """
        flips_congruence = 0
        flips_temporality = 0
        for fname, count_key, target in (
            ("congruence-report.json", "incoherent_count", "congruence"),
            ("temporality-report.json", "violations_count", "temporality"),
        ):
            report_path = module_dir / fname
            if not report_path.exists():
                continue
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(report, dict):
                continue
            if report.get("module_id") and report["module_id"] != cm_id:
                continue
            count = report.get(count_key, 0)
            if isinstance(count, int) and count > 0:
                if target == "congruence":
                    flips_congruence = count
                else:
                    flips_temporality = count

        if flips_congruence == 0 and flips_temporality == 0:
            return

        signal_bus.toast_requested.emit(
            f"DCP: congruence flippou {flips_congruence} bits, "
            f"temporality {flips_temporality} bits",
            "info",
        )

    def _handle_dcp_load_specific_flow(self, spec: CommandSpec) -> bool:
        """Local-action callable invoked at queue position 6 of the B-dcp
        pipeline. Consumes `self._pending_dcp_load_ctx` to locate the
        freshly regenerated SPECIFIC-FLOW.json and emit it via
        `_enqueue_specific_flow`.

        Steps:
          1. Pop `_pending_dcp_load_ctx`; refuse with a toast if absent.
          2. Re-read delivery.json (mutated by the 5 previous pipeline steps).
          3. Try DCP-COMMAND-MATRIX.json first and emit the derived queue.
          4. Fallback to SPECIFIC-FLOW.json legacy cascade only when matrix is
             absent or invalid.

        Returns True only when the enqueue succeeds; False on any guard
        miss (no context, delivery indisponivel, flow ausente, enqueue
        rejeitado). Always clears `_pending_dcp_load_ctx` before returning
        so a subsequent click rearms cleanly.
        """
        from workflow_app.config.app_state import app_state
        from workflow_app.services.delivery_reader import (
            DeliveryFound,
            DeliveryReader,
            resolve_specific_flow,
        )

        ctx = self._pending_dcp_load_ctx
        if ctx is None:
            signal_bus.toast_requested.emit(
                "DCP load chamado sem contexto pending. "
                "Re-clique [DCP: Build Module Pipeline].",
                "error",
            )
            logger.warning(
                "[DCP] dcp-load-specific-flow disparado sem contexto pendente "
                "(spec=%s); ignorando.", spec.name,
            )
            return False

        self._pending_dcp_load_ctx = None

        result = DeliveryReader().load(ctx.wbs_root)
        if not isinstance(result, DeliveryFound):
            signal_bus.toast_requested.emit(
                f"delivery.json indisponivel apos pipeline DCP: "
                f"{type(result).__name__}",
                "error",
            )
            return False

        config = app_state.config
        if config is None:
            signal_bus.toast_requested.emit(
                "Projeto descarregado entre build e load. "
                "Recarregue o projeto e re-clique [DCP: Build Module Pipeline].",
                "error",
            )
            return False

        module_dir = ctx.wbs_root / "modules" / ctx.cm_id

        # Surface advisory output of gate 4 (/dcp:meta-completeness) as a
        # non-blocking toast. Does not block the load — meta-completeness is
        # advisory by contract (NUNCA flippa filter[], NUNCA bloqueia paste).
        self._emit_dcp_meta_toast(module_dir, verbose=False)

        # task-028 (st-05): congruence/temporality reports are audit-only
        # now. Violations have already flipped filter[] bits in the matrix;
        # the queue derived from it cannot contain commands tied to flipped
        # bits, so there is no "load anyway" path. We surface flip counts
        # as a single info toast for operator awareness.
        self._audit_display_dcp_reports(module_dir, ctx.cm_id)

        # task-027 (st-05): matrix-driven in-memory derivation is the canonical
        # source for the DCP Execute queue. SPECIFIC-FLOW.json is read only as
        # a transitional path for projects whose matrix has not yet been
        # generated (FileNotFoundError). task-019 (TASK-018) made this path
        # FAIL-CLOSED: when the matrix exists but fails strict validation,
        # `_matrix_strict_failed_for_ctx` is armed and DCP Execute aborts
        # without falling back.
        matrix_queue = self._derive_queue_from_matrix_inmemory(ctx, config)
        if matrix_queue is not None:
            # task-019 (TASK-018): defense-in-depth guard before emit.
            # Reject bare slash-names (e.g. `/create-task` without args)
            # that may have slipped past the matrix validator.
            if not self._validate_no_bare_names(matrix_queue, ctx.cm_id):
                return False
            self._template_label.setText(f"  \U0001f4cb  DCP Matrix: {ctx.cm_id}")
            self._template_label.setVisible(True)
            self._maybe_auto_save(f"DCP Matrix {ctx.cm_id}")
            signal_bus.pipeline_ready.emit(matrix_queue)
            logger.info(
                "[DCP] queue derivada in-memory (matrix) | modulo=%s count=%d",
                ctx.cm_id, len(matrix_queue),
            )
            return True

        # task-019 (TASK-018): UI FAIL-CLOSED. When matrix exists but failed
        # strict validation, abort DCP Execute without reading SPECIFIC-FLOW.json.
        # The MATRIX_INVALID popup was already shown by the helper.
        if self._matrix_strict_failed_for_ctx == ctx.cm_id:
            self._matrix_strict_failed_for_ctx = None
            return False

        flow_path = resolve_specific_flow(
            result.delivery,
            ctx.cm_id,
            config.project_dir,
            custom_workflow_root=config.custom_workflow_root or None,
        )
        if flow_path is None or not flow_path.exists():
            signal_bus.toast_requested.emit(
                f"Matrix ausente e SPECIFIC-FLOW.json nao apareceu "
                f"para {ctx.cm_id}. Regenere via "
                f"[DCP: Build Module Pipeline].",
                "warning",
            )
            return False

        return self._enqueue_specific_flow(
            flow_path=flow_path,
            cm_id=ctx.cm_id,
            default_project_name=config.project_name,
            prefix_commands=None,
            project_dir=config.project_dir,
        )

    def _load_condition_context(
        self,
        ctx: "DcpBuildContext",
        config: "PipelineConfig",
    ) -> "tuple[Optional[dict], Optional[dict]]":
        """Load (enriched MODULE-META, project.json) for consumer defense-in-depth.

        Best-effort: returns (None, project) — or (None, None) — on any failure
        so `derive_queue_from_matrix` falls back to filter-bits-only (the exact
        pre-change behavior). When it succeeds, the MODULE-META is enriched with
        the same delivery runtime snapshot the producer uses, so the consumer's
        condition re-evaluation never diverges from the materialized filter.
        """
        project = getattr(config, "raw", None)
        meta: Optional[dict] = None
        try:
            import json as _json
            meta_path = ctx.wbs_root / "modules" / ctx.cm_id / "MODULE-META.json"
            if meta_path.exists() and project is not None:
                meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                try:
                    import sys as _sys
                    from pathlib import Path as _P
                    _lib = _P(__file__).resolve().parents[5] / ".claude" / "commands" / "_lib"
                    if str(_lib) not in _sys.path:
                        _sys.path.insert(0, str(_lib))
                    from specific_flow.generator import _enrich_meta_with_delivery_state
                    delivery = getattr(ctx, "delivery", None)
                    delivery_dict = (
                        delivery.model_dump(by_alias=True)
                        if hasattr(delivery, "model_dump") else delivery
                    )
                    meta = _enrich_meta_with_delivery_state(meta, delivery_dict, ctx.cm_id)
                except Exception as exc:  # enrichment optional; raw meta covers static predicates
                    logger.debug("[dcp] meta enrichment skipped (%s); using raw meta.", exc)
        except Exception as exc:
            logger.debug("[dcp] condition context unavailable (%s); filter-bits only.", exc)
            meta = None
        return meta, project

    def _derive_queue_from_matrix_inmemory(
        self,
        ctx: "DcpBuildContext",
        config: "PipelineConfig",
    ) -> Optional[list[CommandSpec]]:
        """Try to derive the queue in-memory from DCP-COMMAND-MATRIX.json.

        Returns the rendered `list[CommandSpec]` when the matrix is present
        and validates against the Pydantic model (task-027 / st-05 algorithm
        9-17). Returns None when the matrix is absent OR cannot be validated;
        the caller falls back to the legacy SPECIFIC-FLOW.json read path.

        Side effects on success:
          - Appends and persists a `load-queue` entry to the matrix module
            trail so the operator-visible load is auditable.
        """
        from workflow_app.dcp.queue_derivation import (
            build_load_queue_trail_entry,
            derive_queue_from_matrix,
            load_matrix,
        )
        from workflow_app.models.dcp_command_matrix import TrailEntry

        # task-019 (TASK-018): clear stale fail-closed flag at entry so each
        # call reflects only the current attempt. The flag is re-armed below
        # only when matrix exists AND fails strict validation.
        self._matrix_strict_failed_for_ctx = None

        dcp_root_raw = getattr(config, "dcp_root", "") or ""
        if not dcp_root_raw:
            return None
        dcp_root = Path(dcp_root_raw)
        if not dcp_root.is_absolute():
            dcp_root = (Path(config.project_dir) / dcp_root_raw).resolve()

        try:
            matrix = load_matrix(dcp_root)
        except FileNotFoundError:
            # Matrix absent: legitimate scenario for projects not yet migrated.
            # Flag stays cleared (set at entry), so the caller may fall back
            # to SPECIFIC-FLOW.json without abort.
            return None
        except Exception as exc:  # ValidationError + JSON errors
            # task-019 (TASK-018): red MATRIX_INVALID popup, FAIL-CLOSED.
            # Matrix exists but fails strict validation: arm the fail-closed
            # flag so the caller aborts DCP Execute without falling back to
            # SPECIFIC-FLOW.json. The popup is critical (red) and offers only
            # detail-copy + close — no "continuar com fallback" button.
            self._matrix_strict_failed_for_ctx = ctx.cm_id
            matrix_path = dcp_root / "DCP-COMMAND-MATRIX.json"
            schema_version_attempted = extract_schema_version(matrix_path)
            latest_bak = discover_latest_bak(matrix_path)
            body, clipboard_text = format_matrix_invalid_popup(
                matrix_path,
                type(exc).__name__,
                str(exc),
                schema_version_attempted=schema_version_attempted,
                latest_bak=latest_bak,
            )
            logger.error(
                "[DCP] matrix invalida em %s (schema_version=%s, latest_bak=%s): "
                "%s -> DCP Execute ABORTADO (sem fallback)",
                matrix_path, schema_version_attempted, latest_bak, exc,
            )
            try:
                from PySide6.QtWidgets import QMessageBox

                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Critical)
                box.setWindowTitle("MATRIX_INVALID: DCP-COMMAND-MATRIX.json invalido")
                box.setText(body)
                box.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard
                )
                copy_btn = box.addButton(
                    "Copiar detalhes", QMessageBox.ButtonRole.ActionRole
                )
                close_btn = box.addButton(
                    "Fechar", QMessageBox.ButtonRole.RejectRole
                )
                box.setDefaultButton(close_btn)
                box.exec()
                if box.clickedButton() is copy_btn:
                    QApplication.clipboard().setText(clipboard_text)
                    signal_bus.toast_requested.emit(
                        "Detalhes do MATRIX_INVALID copiados.", "info"
                    )
            except Exception as ui_exc:  # popup failed (headless/test) — keep toast
                logger.warning(
                    "[DCP] MATRIX_INVALID popup falhou (%s); emitindo toast critico",
                    ui_exc,
                )
                signal_bus.toast_requested.emit(
                    f"DCP-COMMAND-MATRIX.json invalido ({type(exc).__name__}): "
                    f"DCP Execute ABORTADO (sem fallback).",
                    "error",
                )
            return None

        # task-028 (st-05): matrix-driven identity guard.
        # Replaces the legacy scope_module check (still kept in
        # _enqueue_specific_flow for the transitional SPECIFIC-FLOW.json read
        # path used by projects not yet migrated to the matrix contract).
        # When the operator-active module is absent from the matrix, we
        # cannot safely derive a queue in-memory — return None with an
        # explicit operator toast pointing at the regeneration entrypoint.
        matrix_module = matrix.modules.get(ctx.cm_id)
        if matrix_module is None:
            signal_bus.toast_requested.emit(
                f"modulo {ctx.cm_id} ausente da matrix - "
                f"regenerar via [DCP: Build Module Pipeline]",
                "warning",
            )
            logger.warning(
                "[DCP] cm_id=%s ausente em matrix.modules — fallback para SPECIFIC-FLOW.json",
                ctx.cm_id,
            )
            return None

        # Soft warning: current_module pode estar stale entre build-matrix
        # e load (sequencial da pipeline e quem garante coerencia). Nao
        # bloqueia, apenas sinaliza.
        if matrix.current_module and matrix.current_module != ctx.cm_id:
            signal_bus.toast_requested.emit(
                f"matrix.current_module={matrix.current_module} difere do "
                f"modulo ativo {ctx.cm_id} (warning soft)",
                "info",
            )
            logger.info(
                "[DCP] current_module stale: matrix=%s ativo=%s",
                matrix.current_module, ctx.cm_id,
            )

        # Defense-in-depth: schema_version range + filter length cross-check.
        # Pydantic ja valida ambos via Literal["1.0.1"] e validators internos,
        # mas mantemos a checagem explicita para detectar drift caso o
        # contrato relaxe no futuro.
        supported_schemas = {"1.0.1"}
        if matrix.schema_version not in supported_schemas:
            signal_bus.toast_requested.emit(
                f"matrix.schema_version={matrix.schema_version} fora da "
                f"faixa suportada ({sorted(supported_schemas)}). "
                f"Caindo para SPECIFIC-FLOW.json.",
                "warning",
            )
            return None
        if len(matrix_module.filter) != len(matrix.command_index):
            signal_bus.toast_requested.emit(
                f"matrix modules[{ctx.cm_id}].filter length "
                f"({len(matrix_module.filter)}) != command_index length "
                f"({len(matrix.command_index)}). Regenere via "
                f"[DCP: Build Module Pipeline].",
                "warning",
            )
            return None

        # Soft warning: foundations-pure modules legitimamente tem
        # A-creation == 0 (sem loop A). Para todos os outros casos,
        # loop_multiplier["A-creation"] < 1 e sinal de drift.
        a_creation = matrix_module.loop_multiplier.get("A-creation", 0)
        is_foundations_pure = bool(getattr(matrix_module, "foundations_pure", False))
        if a_creation < 1 and not is_foundations_pure:
            signal_bus.toast_requested.emit(
                f"matrix modules[{ctx.cm_id}].loop_multiplier.A-creation"
                f"={a_creation} < 1 e modulo nao e foundations-pure "
                f"(warning soft)",
                "info",
            )

        commit_variant = getattr(config, "commit_type", "") or "simple"
        wbs_root = ctx.wbs_root

        # Defense-in-depth context: pass enriched MODULE-META + project.json so
        # the consumer can drop any command whose canonical condition resolves
        # False, even if a stale matrix left its filter bit at 1. Enrichment
        # mirrors the producer (generator._enrich_meta_with_delivery_state) so
        # runtime-state predicates (tdd.gate_ready, review.*, module.state.*)
        # never diverge between producer and consumer. Strictly best-effort: on
        # ANY failure meta stays None and the consumer trusts the
        # (producer-materialized) filter bits — exact pre-change behavior.
        cond_meta, cond_project = self._load_condition_context(ctx, config)

        try:
            queue = derive_queue_from_matrix(
                matrix,
                ctx.cm_id,
                wbs_root=wbs_root,
                config_path=getattr(config, "config_path", "") or "",
                commit_variant=commit_variant,
                include_directives=True,
                meta=cond_meta,
                project=cond_project,
            )
        except Exception as exc:
            signal_bus.toast_requested.emit(
                f"Erro ao derivar fila in-memory: {exc}. "
                f"Caindo para SPECIFIC-FLOW.json.",
                "warning",
            )
            logger.warning(
                "[DCP] derive_queue_from_matrix falhou para %s: %s",
                ctx.cm_id, exc, exc_info=True,
            )
            return None

        if not queue:
            logger.warning(
                "[DCP] queue derivada vazia para modulo=%s — fallback para SPECIFIC-FLOW.json",
                ctx.cm_id,
            )
            return None

        is_last = (
            matrix.execution_order[-1] == ctx.cm_id
            if matrix.execution_order
            else False
        )
        try:
            trail_dict = build_load_queue_trail_entry(
                ctx.cm_id, len(queue), is_last,
            )
            entry = TrailEntry.model_validate(trail_dict)
            matrix.modules[ctx.cm_id].trail.append(entry)
            matrix_path = dcp_root / "DCP-COMMAND-MATRIX.json"
            tmp_path = matrix_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                matrix.model_dump_json(by_alias=True, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp_path.replace(matrix_path)
        except Exception as exc:  # pragma: no cover — trail append is non-blocking
            logger.warning(
                "[DCP] trail load-queue persist falhou (nao bloqueante): %s", exc,
            )

        return queue

    # task-019 (TASK-018): defense-in-depth bare-slash check.
    # Mirrors `ai-forge/scripts/_dcp_canonical.py:115-125` so the widget can
    # reject bare names without importing from ai-forge/scripts (not on the
    # workflow-app sys.path). Kept in sync via tests/test_dcp_fail_closed_bare_name.py.
    #
    # A bare rendered name is ILLEGITIMATE only when the command's canonical
    # template REQUIRES a placeholder (e.g. /create-task {task} collapsed to
    # /create-task — the loop 05-27 regression). Commands that are CANONICALLY
    # bare by design (e.g. /create-task-layout, /data-test-id, every /nextjs:*
    # review) are legitimate and MUST pass — this matches the validator, which
    # only flags BARE_NON_EXECUTABLE_NAME when the canonical template has "{".
    # The authoritative allowlist is derived live from profiles.FULL_PROFILE
    # (queue_derivation.canonical_bare_command_names); the static snapshot below
    # is the fail-safe used only when that import is unavailable. The two are
    # locked in sync by tests/test_dcp_canonical_bare_snapshot.py.
    _BARE_SLASH_NAME_RE = re.compile(r"^/[a-z][a-z0-9-]*(:[a-z0-9-]+)*$")
    # Directives injected at consumption time (not in FULL_PROFILE): always bare-OK.
    _BARE_DIRECTIVE_ALLOWLIST = frozenset({"/clear", "/model {tier}", "/effort {level}"})
    # Static fail-safe snapshot of profiles.FULL_PROFILE canonically-bare slash
    # commands (template carries NO placeholder). Regenerate + verify drift via
    # tests/test_dcp_canonical_bare_snapshot.py.
    _CANONICAL_BARE_FALLBACK = frozenset({
        "/android:accessibility", "/android:architecture", "/android:compose",
        "/android:configuration", "/android:data-layer", "/android:di",
        "/android:hardcodes", "/android:kotlin", "/android:lifecycle",
        "/android:navigation", "/android:performance", "/android:resources",
        "/android:scalability", "/android:security", "/android:testing",
        "/assets:create", "/brief-vs-frontend-review", "/build-verify",
        "/ci-cd-create", "/compliance-check", "/create-task-layout",
        "/create-test-user", "/data-test-id", "/db-migration-create",
        "/delivery:sync-progress", "/dependency-audit", "/deploy-checklist",
        "/dev-bootstrap-create", "/docker-create", "/env-creation",
        "/gate:frontend-runtime", "/hostinger:update-bd", "/infra-create",
        "/infra-smoke-check", "/integration-test-create", "/load-test-create",
        "/marketing-readiness-check", "/mobile-first-build", "/monitoring-setup",
        "/next-modules-skeleton-update", "/nextjs:accessibility",
        "/nextjs:anti-hacking-review", "/nextjs:anti-loop", "/nextjs:architecture",
        "/nextjs:boundaries", "/nextjs:configuration", "/nextjs:data-fetching",
        "/nextjs:error-handling", "/nextjs:forms", "/nextjs:hardcodes",
        "/nextjs:nextjs-components", "/nextjs:performance", "/nextjs:scalability",
        "/nextjs:security", "/nextjs:seo", "/nextjs:server-actions",
        "/nextjs:styling", "/nextjs:typescript", "/npm-run", "/pending-actions-mcp",
        "/post-deploy-verify", "/pre-deploy-testing", "/python:api",
        "/python:architecture", "/python:async", "/python:ci-cd",
        "/python:configuration", "/python:data-handling", "/python:dependencies",
        "/python:error-handling", "/python:hardcodes", "/python:packaging",
        "/python:performance", "/python:scalability", "/python:security",
        "/python:testing", "/python:typing", "/python:web-framework",
        "/reactnative:accessibility", "/reactnative:architecture",
        "/reactnative:ci-cd", "/reactnative:configuration",
        "/reactnative:data-fetching", "/reactnative:error-handling",
        "/reactnative:hardcodes", "/reactnative:navigation",
        "/reactnative:performance", "/reactnative:scalability",
        "/reactnative:security", "/reactnative:state-management",
        "/reactnative:styling", "/reactnative:testing", "/reactnative:typescript",
        "/review-language", "/secrets-scan", "/seed-data-create", "/slo-create",
        "/staging-validate", "/supabase-sql-editor", "/sync:github", "/sync:mcp",
        "/tech-debt-audit", "/typescript:accessibility", "/typescript:architecture",
        "/typescript:configuration", "/typescript:data-fetching",
        "/typescript:dom-components", "/typescript:error-handling",
        "/typescript:forms", "/typescript:hardcodes", "/typescript:performance",
        "/typescript:scalability", "/typescript:security", "/typescript:seo",
        "/typescript:styling", "/typescript:typescript", "/validation-remediate",
    })
    _bare_allowlist_cache: Optional[frozenset] = None

    @classmethod
    def _bare_allowlist(cls) -> frozenset:
        """Names that are legitimately bare: directives + canonically-bare cmds.

        Authoritative source is profiles.FULL_PROFILE (live, single source of
        truth shared with the validator). Falls back to the static snapshot with
        a WARN (Zero Silencio) if profiles cannot be imported — never silently
        fail-open, so a genuine bare-name regression is still caught even in a
        degraded environment.
        """
        if cls._bare_allowlist_cache is not None:
            return cls._bare_allowlist_cache
        canonical: Optional[frozenset] = None
        try:
            from workflow_app.dcp.queue_derivation import canonical_bare_command_names
            canonical = canonical_bare_command_names()
        except Exception as exc:  # pragma: no cover - import guard
            logger.warning(
                "[DCP] canonical_bare_command_names indisponivel (%s); usando "
                "snapshot estatico.", exc,
            )
            canonical = None
        if canonical is None:
            logger.warning(
                "[DCP] canonical-bare set vindo do snapshot estatico de fallback "
                "(profiles.FULL_PROFILE nao importavel)."
            )
            canonical = cls._CANONICAL_BARE_FALLBACK
        cls._bare_allowlist_cache = cls._BARE_DIRECTIVE_ALLOWLIST | canonical
        return cls._bare_allowlist_cache

    @classmethod
    def _is_bare_slash_name(cls, name: str) -> bool:
        """True when `name` is a slash bare ILEGITIMO (placeholder lost).

        Canonically-bare commands (in the FULL_PROFILE allowlist) and directives
        return False — a bare render of them is correct.
        """
        normalized = re.sub(r"\s+", " ", name or "").strip()
        if normalized in cls._bare_allowlist():
            return False
        return bool(cls._BARE_SLASH_NAME_RE.match(normalized))

    def _validate_no_bare_names(
        self,
        specs: list[CommandSpec],
        cm_id: str,
    ) -> bool:
        """Reject the emit when any CommandSpec carries a bare slash-name.

        Second-layer guard to prevent regression of the bare-name bug
        (loop 05-27-dcp-flow-structured-fix). Returns True when all spec
        names pass; False after surfacing a red MATRIX_INVALID-style popup
        and a toast. The popup body identifies the offender(s) so the
        operator can correlate with `DCP-COMMAND-MATRIX.json`.
        """
        offenders: list[str] = []
        for spec in specs:
            # Validate the RENDERED command name on its own. config_path is NOT
            # concatenated here: a placeholder-loss bug (e.g. /create-task without
            # its {task} arg) must be caught even when config_path is set, and
            # appending config_path would MASK it — "/create-task .claude/projects/
            # foo.json" looks non-bare but the {task} arg is still gone, and the
            # executor would feed the project json where the TASK path belongs.
            # Legitimately-bare commands pass via the canonical-bare allowlist
            # (_is_bare_slash_name), not via a config_path side-channel.
            if self._is_bare_slash_name(spec.name):
                offenders.append(spec.name)
        if not offenders:
            return True

        joined = ", ".join(offenders[:5])
        suffix = f" (+{len(offenders) - 5} mais)" if len(offenders) > 5 else ""
        body = (
            "Matriz derivada contem name bare (sem args/placeholders).\n\n"
            f"Modulo:    {cm_id}\n"
            f"Offenders: {joined}{suffix}\n\n"
            "DCP Execute ABORTADO (sem fallback). Regere a matrix via\n"
            "[DCP: Build Module Pipeline] e revalide com\n"
            "  python3 ai-forge/scripts/validate-dcp-matrix-canonical.py "
            "--matrix <DCP-COMMAND-MATRIX.json>"
        )
        logger.error(
            "[DCP] guard pre-emit rejeitou matrix com %d name bare para modulo=%s: %s",
            len(offenders), cm_id, joined,
        )
        try:
            from PySide6.QtWidgets import QMessageBox

            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("MATRIX_INVALID: name bare na fila derivada")
            box.setText(body)
            box.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            box.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
            box.exec()
        except Exception as ui_exc:  # popup failed (headless/test) — keep toast
            logger.warning(
                "[DCP] MATRIX_INVALID (bare guard) popup falhou (%s); emitindo toast",
                ui_exc,
            )
            signal_bus.toast_requested.emit(
                f"Matriz {cm_id} contem name bare ({joined}). "
                f"DCP Execute ABORTADO.",
                "error",
            )
        return False

    def _on_dcp_specific_flow_clicked(self) -> None:
        """Load SPECIFIC-FLOW.json for the active module into the command queue.

        Reads delivery.json to resolve `current_module`, then uses the
        DCP-9.2 cascade (artifacts.last_specific_flow -> custom_workflow_root)
        to locate the JSON and populate the queue via `pipeline_ready`.
        The user can then dispatch each item with [Rodar próximo].
        """
        from workflow_app.config.app_state import app_state

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um projeto antes de usar DCP: Specific-Flow.", "warning"
            )
            return

        config = app_state.config

        from workflow_app.dcp.specific_flow_handler import (
            _next_non_done_module_id,
            _resolve_wbs_root,
        )
        from workflow_app.services.delivery_reader import (
            DeliveryFound,
            DeliveryFutureVersion,
            DeliveryInvalid,
            DeliveryMissing,
            DeliveryReader,
            resolve_specific_flow,
        )

        wbs_root = _resolve_wbs_root(config)
        result = DeliveryReader().load(wbs_root)

        if isinstance(result, DeliveryMissing):
            signal_bus.toast_requested.emit(
                "delivery.json ausente. Rode /delivery:init primeiro.", "warning"
            )
            return
        if isinstance(result, DeliveryInvalid):
            signal_bus.toast_requested.emit(
                f"delivery.json invalido: {result.error}. Rode /delivery:validate.", "warning"
            )
            return
        if isinstance(result, DeliveryFutureVersion):
            signal_bus.toast_requested.emit(result.message, "warning")
            return

        assert isinstance(result, DeliveryFound)
        delivery = result.delivery
        cm_id = delivery.current_module

        # Auto-advance: se current_module aponta para um modulo done (situacao
        # comum ao retomar no dia seguinte), usa o proximo modulo nao-done.
        if not cm_id or (delivery.modules.get(cm_id) and delivery.modules[cm_id].state == "done"):
            cm_id = _next_non_done_module_id(delivery)

        if not cm_id:
            signal_bus.toast_requested.emit("Todos os modulos estao concluidos.", "warning")
            return

        module = delivery.modules.get(cm_id)
        if module is None:
            signal_bus.toast_requested.emit(
                f"Modulo {cm_id!r} nao existe no delivery.json. Rode /delivery:validate.", "warning"
            )
            return

        # Canonical path: the Specific Flow button renders the sequence from
        # DCP-COMMAND-MATRIX.json. SPECIFIC-FLOW.json is read only as a
        # transitional path for projects whose matrix has not yet been
        # generated. task-019 (TASK-018) made this path FAIL-CLOSED: when the
        # matrix exists but fails strict validation, the button aborts without
        # falling back to SPECIFIC-FLOW.json.
        matrix_ctx = DcpBuildContext(
            cm_id=cm_id,
            module_state=module.state,
            regenerate=False,
            wbs_root=wbs_root,
            delivery=delivery,
        )
        matrix_queue = self._derive_queue_from_matrix_inmemory(matrix_ctx, config)
        if matrix_queue is not None:
            # task-019 (TASK-018): defense-in-depth guard before emit.
            if not self._validate_no_bare_names(matrix_queue, cm_id):
                return
            self._template_label.setText(f"  \U0001f4cb  DCP Matrix: {cm_id}")
            self._template_label.setVisible(True)
            self._maybe_auto_save(f"DCP Matrix {cm_id}")
            signal_bus.pipeline_ready.emit(matrix_queue)
            logger.info(
                "[DCP] Specific-Flow button carregou matrix | modulo=%s count=%d",
                cm_id, len(matrix_queue),
            )
            return

        # task-019 (TASK-018): UI FAIL-CLOSED. Matrix existed but failed strict;
        # abort without reading SPECIFIC-FLOW.json. Popup ja foi mostrado.
        if self._matrix_strict_failed_for_ctx == cm_id:
            self._matrix_strict_failed_for_ctx = None
            return

        flow_path = resolve_specific_flow(
            delivery,
            cm_id,
            config.project_dir,
            custom_workflow_root=config.custom_workflow_root or None,
        )

        if flow_path is None or not flow_path.exists():
            dep_extra = ""
            if module is not None and module.state == "pending" and module.dependencies:
                unmet = [
                    dep_id for dep_id in module.dependencies
                    if dep_id not in delivery.modules
                    or delivery.modules[dep_id].state != "done"
                ]
                if unmet:
                    labels = [
                        f"{d}({delivery.modules[d].state})"
                        if d in delivery.modules else f"{d}(ausente)"
                        for d in unmet
                    ]
                    dep_extra = f" Deps bloqueantes: {', '.join(labels)}."
            signal_bus.toast_requested.emit(
                f"Matrix ausente/invalida e SPECIFIC-FLOW.json nao encontrado "
                f"para {cm_id}. Execute [DCP: Gerar Pipeline] "
                f"primeiro.{dep_extra}",
                "warning",
            )
            return

        # M5 hibrida (TRILHA 3 — meta-loop estrategia-de-separacao):
        # carga delegada para helper privado reusavel por /dcp:build-and-load.
        self._enqueue_specific_flow(
            flow_path=flow_path,
            cm_id=cm_id,
            default_project_name=config.project_name,
            prefix_commands=None,
            project_dir=config.project_dir,
        )

    def _enqueue_specific_flow(
        self,
        flow_path: Path,
        cm_id: str,
        default_project_name: str,
        prefix_commands: list[dict] | None = None,
        project_dir: Path | None = None,
    ) -> bool:
        """Le SPECIFIC-FLOW.json e enfileira commands na fila do workflow-app.

        Helper privado extraido em 2026-05-13 (TRILHA 3 + POS-TRILHA do meta-loop
        estrategia-de-separacao, decisao M5 hibrida do usuario). Reusado por:
          - _on_dcp_specific_flow_clicked (caminho UX click-to-load)
          - /dcp:build-and-load (caminho programatico atomico build+validate+load)

        Args:
          flow_path: Path do SPECIFIC-FLOW.json a carregar.
          cm_id: module_id para label da fila.
          default_project_name: nome de projeto fallback quando SPECIFIC-FLOW.json
            nao declarar `project` field.
          prefix_commands: lista opcional de dicts com schema compativel
            (`{name, model, effort, phase, interaction}`) a prependar antes dos
            commands do flow. Usado por /dcp:build-and-load para injetar
            /dcp:congruence-check, /dcp:temporality-check, etc antes do flow.
          project_dir: raiz do projeto usada para resolver paths relativos de
            TASK-*.md na validacao de existencia (loop 06-09). Opcional —
            quando ausente a validacao degrada para fail-open nos paths
            relativos (so paths absolutos e basenames canonicos sao checados).

        Returns:
          True se enqueue foi bem sucedido (`signal_bus.pipeline_ready` emitido).
          False quando flow_path invalido, JSON corrupto, ou specs vazias
          (toasts ja emitidos antes do return).
        """
        try:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            signal_bus.toast_requested.emit(f"Erro ao ler SPECIFIC-FLOW.json: {exc}", "error")
            return False

        if not isinstance(data, dict):
            signal_bus.toast_requested.emit(
                "SPECIFIC-FLOW.json invalido: root deve ser um objeto JSON.", "error"
            )
            return False

        # Identity guard: scope_module.module_id must match cm_id when present.
        # Without this, Level-2 fallback ({wbs_root}/workflow-app/SPECIFIC-FLOW.json)
        # could silently load a stale flow from a different module.
        scope_module = data.get("scope_module")
        if isinstance(scope_module, dict):
            flow_module_id = scope_module.get("module_id")
            if flow_module_id and flow_module_id != cm_id:
                signal_bus.toast_requested.emit(
                    f"SPECIFIC-FLOW.json pertence a '{flow_module_id}' mas o modulo "
                    f"ativo e '{cm_id}'. Regenere via [DCP: Build + Load].",
                    "warning",
                )
                logger.warning(
                    "[DCP] module_id mismatch: flow=%s, cm_id=%s — carga abortada",
                    flow_module_id, cm_id,
                )
                return False

        commands_raw = data.get("commands", [])
        if not isinstance(commands_raw, list):
            signal_bus.toast_requested.emit(
                "SPECIFIC-FLOW.json invalido: campo 'commands' deve ser uma lista.", "error"
            )
            return False

        # prefix_commands prependa antes do flow (uso programatico via /dcp:build-and-load)
        if prefix_commands:
            commands_raw = list(prefix_commands) + commands_raw

        # Onda 4: honor operator-persisted skip list. overrides.skipped[]
        # is a list of fully-rendered command name strings. Filter happens
        # before model/effort mapping so skipped commands never enter the queue.
        overrides = data.get("overrides") if isinstance(data.get("overrides"), dict) else {}
        skipped_raw = overrides.get("skipped") if isinstance(overrides, dict) else None
        skipped_set: set[str] = (
            {s for s in skipped_raw if isinstance(s, str) and s}
            if isinstance(skipped_raw, list) else set()
        )
        if skipped_set:
            before = len(commands_raw)
            commands_raw = [
                c for c in commands_raw
                if not (isinstance(c, dict) and c.get("name") in skipped_set)
            ]
            removed = before - len(commands_raw)
            if removed:
                logger.info(
                    "[DCP] overrides.skipped filtrou %d comandos (de %d para %d)",
                    removed, before, len(commands_raw),
                )

        # Loop 06-09: valida cada entry contra o disco ANTES do enqueue.
        # SPECIFIC-FLOW.json stale (per-task sintetizado por contagem, pre-fix
        # 06-08) ou stub do gerador com placeholder literal (`TASK-{k}`)
        # produzia comandos para tasks inexistentes ("task N nao existe") que
        # so estouravam em runtime do slash command. Drops sao SEMPRE visiveis
        # (Zero Silencio): toast resumido + reason completo no log.
        from workflow_app.dcp.flow_validation import validate_flow_commands

        vres = validate_flow_commands(
            commands_raw,
            cm_id=cm_id,
            project_dir=project_dir,
            flow_path=flow_path,
        )
        if vres.dropped:
            for d in vres.dropped:
                logger.warning(
                    "[DCP] comando descartado no load de %s: %r — %s",
                    flow_path, d.name, d.reason,
                )
            shown = "; ".join(d.name for d in vres.dropped[:5])
            extra = (
                f" (+{len(vres.dropped) - 5} no log)"
                if len(vres.dropped) > 5 else ""
            )
            signal_bus.toast_requested.emit(
                f"SPECIFIC-FLOW.json: {len(vres.dropped)} comando(s) "
                f"invalido(s) descartado(s) no load — {shown}{extra}. "
                f"Motivos no log. Flow provavelmente stale: regenere via "
                f"[DCP: Build Module Pipeline].",
                "warning",
            )
        commands_raw = vres.valid

        _model_map = {
            "opus": ModelName.OPUS,
            "sonnet": ModelName.SONNET,
        }
        _effort_map = {
            "low": EffortLevel.LOW,
            "medium": EffortLevel.STANDARD,
            "standard": EffortLevel.STANDARD,
            "high": EffortLevel.HIGH,
            "max": EffortLevel.MAX,
        }
        specs: list[CommandSpec] = []
        for i, cmd in enumerate(commands_raw, start=1):
            if not isinstance(cmd, dict):
                continue
            name = cmd.get("name", "").strip()
            if not name:
                continue
            model = _model_map.get(str(cmd.get("model", "sonnet")).lower(), ModelName.SONNET)
            interaction = (
                InteractionType.INTERACTIVE
                if str(cmd.get("interaction", "auto")).lower() == "inter"
                else InteractionType.AUTO
            )
            effort = _effort_map.get(str(cmd.get("effort", "medium")).lower(), EffortLevel.STANDARD)
            phase = str(cmd.get("phase", "F?"))
            specs.append(
                CommandSpec(
                    name=name,
                    model=model,
                    interaction_type=interaction,
                    config_path="",
                    position=i,
                    effort=effort,
                    phase=phase,
                )
            )

        if not specs:
            signal_bus.toast_requested.emit("SPECIFIC-FLOW.json esta vazio.", "warning")
            return False

        project = data.get("project", default_project_name)
        logger.info("[DCP] loading pipeline from %s (%d commands, prefix=%d)",
                    flow_path, len(specs), len(prefix_commands or []))
        self._template_label.setText(f"  \U0001f4cb  DCP: {cm_id} — {project}")
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"DCP {cm_id}")
        signal_bus.pipeline_ready.emit(specs)
        # Onda 4: arm DCP context AFTER pipeline_ready. load_pipeline()
        # resets _current_dcp_flow_path to None at its start; we re-arm
        # here so subsequent _on_remove_requested calls persist to disk.
        # Order matters: emit is synchronous (Qt direct connection), so
        # load_pipeline runs to completion before this assignment.
        self._current_dcp_flow_path = flow_path
        return True

    def _on_cmd_single_clicked(self) -> None:
        """Reduced pipeline for a single command MD (no prep, no JSON).

        Steps:
          1. Open MD file dialog.
          2. Extract cmd_target_slash from heading or frontmatter.
          3. Decide create vs update via os.path.exists.
          4. Expand sub-sequence inline into queue-command-list.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar MD do comando",
            str(Path.cwd()),
            "Markdown Files (*.md);;All Files (*)",
        )
        if not path:
            return

        md_path = Path(path)
        try:
            content = md_path.read_text(encoding="utf-8")
        except Exception as exc:
            signal_bus.toast_requested.emit(
                f"Erro ao ler {md_path.name}: {exc}", "error"
            )
            return

        # Step 3: extract cmd_target_slash
        cmd_target_slash = ""
        fm_match = re.search(r"^cmd_target:\s*([^\r\n]+)", content, re.MULTILINE)
        if fm_match:
            cmd_target_slash = fm_match.group(1).strip()
        if not cmd_target_slash:
            heading_match = re.search(r"^#\s+(/[^\s\n]+)", content, re.MULTILINE)
            if heading_match:
                cmd_target_slash = heading_match.group(1).strip()

        if not cmd_target_slash:
            signal_bus.toast_requested.emit(
                f"MD {md_path.name} nao tem heading canonico (# /grupo:nome) "
                "nem cmd_target no header. Abortando.",
                "error",
            )
            return

        # Step 4: decide action
        target_disk = cmd_target_slash.lstrip("/").replace(":", "/")
        cmd_file_path = Path.cwd() / ".claude" / "commands" / f"{target_disk}.md"
        cmd_action = "update" if cmd_file_path.exists() else "create"

        # Build sub-sequence
        md_path_str = str(md_path.resolve())
        commands = [
            "/clear",
            "/model opus",
            "/effort high",
            f"/cmd:{cmd_action} {md_path_str}",
            f"/cmd:review {cmd_target_slash} {md_path_str}",
        ]
        commands.extend([
            "/clear",
            f"/cmd:kimi-pair-analyse --approved {md_path_str}",
            f"/cmd:kimi-pair-execute --approved {md_path_str}",
            "/clear",
            "/cmd:readme-upd",
        ])

        specs: list[CommandSpec] = []
        for i, cmd in enumerate(commands, start=1):
            specs.append(
                CommandSpec(
                    name=cmd,
                    model=ModelName.OPUS,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=EffortLevel.HIGH,
                    position=i,
                )
            )

        self._template_label.setText(
            f"  \U0001f4cb  Cmd Single: {cmd_target_slash} ({cmd_action})"
        )
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"Cmd Single {cmd_target_slash}")
        signal_bus.pipeline_ready.emit(specs)

        hint = ""
        if cmd_action == "create":
            hint = (
                " Comando novo detectado. Rode "
                "python3 ai-forge/scripts/generate-workflow-index.py "
                "para registrar no indice."
            )
        signal_bus.toast_requested.emit(
            f"Fila renderizada: {len(specs)} comandos.{hint}", "success"
        )

    def _expand_loop_json_specs(
        self, raw: dict, config_path: str
    ) -> list[CommandSpec]:
        """Expand a *-loop.json into a list of CommandSpec based on mode."""
        mode = raw.get("mode", "task")

        if mode == "task":
            return self._expand_loop_task_specs(raw, config_path)
        if mode == "cmd":
            return self._expand_loop_cmd_specs(raw, config_path)
        if mode == "both":
            return self._expand_loop_both_specs(raw, config_path)

        raise ValueError(f"Modo de loop nao reconhecido: {mode}")

    def _expand_loop_task_specs(
        self, raw: dict, config_path: str
    ) -> list[CommandSpec]:
        """Expand a task-mode *-loop.json (pre/exec/post)."""
        iteration_template = raw.get("iteration_template", {})
        items = raw.get("items", [])
        finalization = raw.get("finalization", {})
        loop_name = str(raw.get("name", "")) or "loop"

        return self._do_expand_loop_specs(
            iteration_template, items, finalization, loop_name, config_path
        )

    def _expand_loop_cmd_specs(
        self, raw: dict, config_path: str
    ) -> list[CommandSpec]:
        """Expand a cmd-mode *-loop.json (pre/exec_create/exec_update/kimi_eligible_wrapper)."""
        iteration_template = raw.get("iteration_template", {})
        items = raw.get("items", [])
        finalization = raw.get("finalization", {})
        loop_name = str(raw.get("name", "")) or "loop"

        specs: list[CommandSpec] = []
        current_model = ModelName.SONNET
        current_effort = EffortLevel.STANDARD
        pos = 1

        def _add_command(cmd: str, testid: str = "", kimi_eligible: bool = False) -> None:
            nonlocal current_model, current_effort, pos
            stripped = cmd.strip()
            if stripped.startswith("/model "):
                model_str = stripped.split(None, 1)[1].lower()
                current_model = _MODEL_MAP.get(model_str, current_model)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                        testid=testid,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return
            if stripped.startswith("/effort "):
                effort_str = stripped.split(None, 1)[1].lower()
                current_effort = _EFFORT_MAP.get(effort_str, current_effort)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=current_effort,
                        position=pos,
                        testid=testid,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return
            if stripped == "/clear":
                specs.append(
                    CommandSpec(
                        name="/clear",
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                        testid=testid,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return

            specs.append(
                CommandSpec(
                    name=stripped,
                    model=current_model,
                    interaction_type=InteractionType.AUTO,
                    config_path=config_path,
                    effort=current_effort,
                    position=pos,
                    testid=testid,
                    kimi_eligible=kimi_eligible,
                )
            )
            pos += 1

        for item in items:
            task_path = (
                str(item.get("task_path", ""))
                if isinstance(item, dict)
                else ""
            )
            cmd_action = (
                str(item.get("cmd_action", ""))
                if isinstance(item, dict)
                else ""
            )
            cmd_target_slash = (
                str(item.get("cmd_target_slash", ""))
                if isinstance(item, dict)
                else ""
            )
            kimi_eligible = (
                bool(item.get("kimi_eligible", False))
                if isinstance(item, dict)
                else False
            )

            for cmd in iteration_template.get("pre", []):
                resolved = (
                    cmd.replace("{task_path}", task_path)
                    .replace("{name}", loop_name)
                )
                _add_command(resolved, kimi_eligible=kimi_eligible)

            exec_key = "exec_create" if cmd_action == "create" else "exec_update"
            for cmd in iteration_template.get(exec_key, []):
                resolved = (
                    cmd.replace("{task_path}", task_path)
                    .replace("{cmd_target_slash}", cmd_target_slash)
                    .replace("{name}", loop_name)
                )
                _add_command(resolved, kimi_eligible=kimi_eligible)

            if (
                kimi_eligible
                and "kimi_eligible_wrapper" in iteration_template
                and self._use_kimi_chk.isChecked()
            ):
                for cmd in iteration_template.get("kimi_eligible_wrapper", []):
                    resolved = (
                        cmd.replace("{task_path}", task_path)
                        .replace("{name}", loop_name)
                    )
                    _add_command(resolved, kimi_eligible=kimi_eligible)

        for cmd in finalization.get("commands", []):
            resolved = cmd.replace("{name}", loop_name)
            _add_command(resolved)

        return specs

    def _expand_loop_both_specs(
        self, raw: dict, config_path: str
    ) -> list[CommandSpec]:
        """Expand a both-mode *-loop.json (task + cmd interleaved)."""
        iteration_template = raw.get("iteration_template", {})
        items = raw.get("items", [])
        finalization = raw.get("finalization", {})
        loop_name = str(raw.get("name", "")) or "loop"

        specs: list[CommandSpec] = []
        current_model = ModelName.SONNET
        current_effort = EffortLevel.STANDARD
        pos = 1

        def _add_command(cmd: str, testid: str = "") -> None:
            nonlocal current_model, current_effort, pos
            stripped = cmd.strip()
            if stripped.startswith("/model "):
                model_str = stripped.split(None, 1)[1].lower()
                current_model = _MODEL_MAP.get(model_str, current_model)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                    )
                )
                pos += 1
                return
            if stripped.startswith("/effort "):
                effort_str = stripped.split(None, 1)[1].lower()
                current_effort = _EFFORT_MAP.get(effort_str, current_effort)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=current_effort,
                        position=pos,
                    )
                )
                pos += 1
                return
            if stripped == "/clear":
                specs.append(
                    CommandSpec(
                        name="/clear",
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                    )
                )
                pos += 1
                return

            specs.append(
                CommandSpec(
                    name=stripped,
                    model=current_model,
                    interaction_type=InteractionType.AUTO,
                    config_path=config_path,
                    effort=current_effort,
                    position=pos,
                    testid=testid,
                )
            )
            pos += 1

        for item in items:
            if not isinstance(item, dict):
                continue

            task_type = str(item.get("task_type", ""))
            item_id = str(item.get("id", ""))

            if task_type == "ambiguous":
                specs.append(
                    CommandSpec(
                        name=f"[BLOQUEADO] Item {item_id} - task_type ambiguo",
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=current_effort,
                        position=pos,
                        blocked_reason="task_type ambiguo - resolva em /loop:mark-type",
                    )
                )
                pos += 1
                continue

            task_path = str(item.get("task_path", ""))

            if task_type == "task":
                task_template = iteration_template.get("task", {})
                kimi_eligible = bool(item.get("kimi_eligible", False))

                phases = ["pre", "exec", "post"]
                if kimi_eligible and "kimi_eligible_wrapper" in task_template:
                    phases = ["pre", "kimi_eligible_wrapper", "post"]

                for phase in phases:
                    for cmd in task_template.get(phase, []):
                        resolved = (
                            cmd.replace("{task_path}", task_path)
                            .replace("{name}", loop_name)
                        )
                        _add_command(resolved)

            elif task_type == "cmd":
                cmd_template = iteration_template.get("cmd", {})
                cmd_complexity = str(item.get("cmd_complexity", ""))
                cmd_action = str(item.get("cmd_action", ""))
                cmd_target_slash = str(item.get("cmd_target_slash", ""))
                kimi_eligible = bool(item.get("kimi_eligible", False))

                if cmd_complexity == "single":
                    expanded_commands = item.get("expanded_commands", [])
                    for cmd in expanded_commands:
                        resolved = (
                            cmd.replace("{task_path}", task_path)
                            .replace("{name}", loop_name)
                        )
                        _add_command(resolved, testid="queue-item-cmd-single")
                else:
                    for cmd in cmd_template.get("pre", []):
                        resolved = (
                            cmd.replace("{task_path}", task_path)
                            .replace("{name}", loop_name)
                        )
                        _add_command(resolved)

                    exec_key = "exec_create" if cmd_action == "create" else "exec_update"
                    for cmd in cmd_template.get(exec_key, []):
                        resolved = (
                            cmd.replace("{task_path}", task_path)
                            .replace("{cmd_target_slash}", cmd_target_slash)
                            .replace("{name}", loop_name)
                        )
                        _add_command(resolved)

                    if kimi_eligible and "kimi_eligible_wrapper" in cmd_template:
                        for cmd in cmd_template.get("kimi_eligible_wrapper", []):
                            resolved = (
                                cmd.replace("{task_path}", task_path)
                                .replace("{name}", loop_name)
                            )
                            _add_command(resolved)

        for cmd in finalization.get("commands", []):
            resolved = cmd.replace("{name}", loop_name)
            _add_command(resolved)

        return specs

    def _do_expand_loop_specs(
        self,
        iteration_template: dict,
        items: list,
        finalization: dict,
        loop_name: str,
        config_path: str,
    ) -> list[CommandSpec]:
        """Shared expansion logic for task-mode iteration_template."""
        specs: list[CommandSpec] = []
        current_model = ModelName.SONNET
        current_effort = EffortLevel.STANDARD
        pos = 1

        def _add_command(cmd: str, kimi_eligible: bool = False) -> None:
            nonlocal current_model, current_effort, pos
            stripped = cmd.strip()
            if stripped.startswith("/model "):
                model_str = stripped.split(None, 1)[1].lower()
                current_model = _MODEL_MAP.get(model_str, current_model)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return
            if stripped.startswith("/effort "):
                effort_str = stripped.split(None, 1)[1].lower()
                current_effort = _EFFORT_MAP.get(effort_str, current_effort)
                specs.append(
                    CommandSpec(
                        name=stripped,
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        effort=current_effort,
                        position=pos,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return
            if stripped == "/clear":
                specs.append(
                    CommandSpec(
                        name="/clear",
                        model=current_model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                        kimi_eligible=kimi_eligible,
                    )
                )
                pos += 1
                return

            specs.append(
                CommandSpec(
                    name=stripped,
                    model=current_model,
                    interaction_type=InteractionType.AUTO,
                    config_path=config_path,
                    effort=current_effort,
                    position=pos,
                    kimi_eligible=kimi_eligible,
                )
            )
            pos += 1

        for item in items:
            task_path = (
                str(item.get("task_path", ""))
                if isinstance(item, dict)
                else ""
            )

            # Task-mode loops nunca injetam kimi-pair: /cmd:kimi-pair-* opera
            # sobre arquivos de slash-command (.claude/commands/*.md) apos
            # /cmd:create ou /cmd:update — task descriptors nao sao alvo
            # valido. Wrapper kimi continua disponivel apenas em --cmd e no
            # bloco cmd de --both.
            for phase in ("pre", "exec", "post"):
                commands = iteration_template.get(phase, [])
                for cmd in commands:
                    resolved = cmd.replace("{task_path}", task_path).replace(
                        "{name}", loop_name
                    )
                    _add_command(resolved)

        for cmd in finalization.get("commands", []):
            resolved = cmd.replace("{name}", loop_name)
            _add_command(resolved)

        return specs

    def _on_daily_loop_clicked(self) -> None:
        """Expand a daily-loop _LOOP-CONFIG.json + PROGRESS.md into the queue.

        Requires the metrics-project-pill to point at blacksmith/loop-archives/{slug}/_LOOP-CONFIG.json
        (generated by /daily-loop:enumerate). One queue entry per pending item,
        with /clear at position 0 and /model/X /effort/Y emitted only when
        the bucket changes between consecutive items.

        Failed items ([!]) are NOT re-queued — fix them manually in PROGRESS.md
        or re-run /daily-loop:enumerate.

        Pre-flight: if `{loop_root}/.review-blocked` is present (dropped by
        /daily-loop:review-created when its 3-round self-healing loop exhausts
        with blockers remaining), a confirmation modal is shown before
        expanding the queue. Defense-in-depth alongside the terminal-side gate.
        """
        from PySide6.QtWidgets import QMessageBox

        from workflow_app.config.app_state import app_state
        from workflow_app.daily_loop import (
            DailyLoopConfigError,
            build_daily_loop_specs,
            read_review_blocked_sentinel,
        )

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um _LOOP-CONFIG.json em metrics-project-pill antes de usar Daily loop.",
                "warning",
            )
            return

        config = app_state.config
        raw = config.raw if isinstance(config.raw, dict) else {}

        if raw.get("kind") != "daily-loop" or "daily_loop" not in raw:
            signal_bus.toast_requested.emit(
                "Projeto carregado nao e um _LOOP-CONFIG.json. "
                "Rode /daily-loop no terminal e carregue o JSON gerado.",
                "warning",
            )
            return

        loop_root = Path(config.config_path).parent

        sentinel = read_review_blocked_sentinel(loop_root)
        if sentinel is not None:
            slug_for_modal = str(raw.get("daily_loop", {}).get("slug", "")) or "daily-loop"
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Daily Loop — Review BLOQUEADO")
            box.setText(
                f"O preparo do loop \"{slug_for_modal}\" foi REPROVADO por "
                "/daily-loop:review-created."
            )
            blocker_line = (
                f"\n\nBlockers remanescentes: {sentinel.blocker_count}"
                if sentinel.blocker_count
                else ""
            )
            box.setInformativeText(
                "Sentinel `.review-blocked` encontrado em:\n"
                f"{sentinel.path}\n\n"
                "Recomendado: Cancelar, ler _LOOP-CREATED-AUDIT.md, corrigir "
                "blockers e re-rodar /daily-loop:review-created."
                f"{blocker_line}\n\n"
                "Executar mesmo assim?"
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            yes_btn = box.button(QMessageBox.StandardButton.Yes)
            yes_btn.setText("Executar mesmo assim")
            cancel_btn = box.button(QMessageBox.StandardButton.Cancel)
            cancel_btn.setText("Cancelar")
            choice = box.exec()
            if choice != QMessageBox.StandardButton.Yes:
                logger.info(
                    "[daily-loop] %s execution cancelled (.review-blocked override declined)",
                    slug_for_modal,
                )
                signal_bus.toast_requested.emit(
                    "Execucao cancelada — .review-blocked ativo.",
                    "info",
                )
                return
            logger.warning(
                "[daily-loop] %s executing despite .review-blocked sentinel "
                "(blockers=%d, user override)",
                slug_for_modal,
                sentinel.blocker_count,
            )

        try:
            specs = build_daily_loop_specs(raw, loop_root)
        except DailyLoopConfigError as exc:
            signal_bus.toast_requested.emit(f"Daily loop invalido: {exc}", "error")
            return
        except OSError as exc:
            signal_bus.toast_requested.emit(f"Erro ao ler PROGRESS.md: {exc}", "error")
            return

        if not specs:
            signal_bus.toast_requested.emit(
                "PROGRESS.md sem itens pendentes — loop concluido. "
                "Rode /daily-loop:review --slug X para o veredito final.",
                "info",
            )
            return

        slug = str(raw.get("daily_loop", {}).get("slug", "")) or "daily-loop"
        # Count real items from buckets[*].items[*] — the legacy heuristic
        # `name.startswith("/daily-loop:do ")` only matched the fallback wrapper
        # shape and silently reported 0 for canonical post-/loop:integration
        # configs where commands are materialized inline.
        item_count = sum(
            len(b.get("items", []))
            for b in raw.get("daily_loop", {}).get("buckets", [])
        )
        logger.info("[daily-loop] loading %s (%d items, %d specs)", slug, item_count, len(specs))

        self._template_label.setText(f"  \U0001f4cb  Daily loop: {slug} ({item_count} itens)")
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"Daily loop {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_loop_clicked(self) -> None:
        """Expand a /loop pipeline _LOOP-CONFIG.json + PROGRESS.md into the queue.

        Clone of `_on_daily_loop_clicked` adapted for the new `/loop`
        family (`/loop --task|--cmd|--cmd-single|--both`, created 2026-05-12).
        The only behavioural difference is the PROGRESS.md parser:
        `build_loop_specs` uses `parse_progress_items_loop` which is
        backtick-aware and tolerates literal `|` characters inside
        backtick-wrapped inline code in the Target column (e.g. mode
        flag enumerations like `--simple|--deep|--heavy`). The legacy
        button (`queue-btn-daily-loop`) keeps the original
        non-backtick-aware parser for byte-for-byte backwards
        compatibility with old archives.

        Requires the metrics-project-pill to point at the
        `_LOOP-CONFIG.json` of a `/loop`-flavoured pipeline (same V3 +
        kind: daily-loop schema as the legacy daily-loop).
        """
        from PySide6.QtWidgets import QMessageBox

        from workflow_app.config.app_state import app_state
        from workflow_app.daily_loop import (
            DailyLoopConfigError,
            build_loop_specs,
            read_review_blocked_sentinel,
        )

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um _LOOP-CONFIG.json em metrics-project-pill antes de usar Loop.",
                "warning",
            )
            return

        config = app_state.config
        raw = config.raw if isinstance(config.raw, dict) else {}

        if raw.get("kind") != "daily-loop" or "daily_loop" not in raw:
            signal_bus.toast_requested.emit(
                "Projeto carregado nao e um _LOOP-CONFIG.json. "
                "Rode /loop no terminal e carregue o JSON gerado.",
                "warning",
            )
            return

        loop_root = Path(config.config_path).parent

        sentinel = read_review_blocked_sentinel(loop_root)
        if sentinel is not None:
            slug_for_modal = str(raw.get("daily_loop", {}).get("slug", "")) or "loop"
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Loop — Review BLOQUEADO")
            box.setText(
                f"O preparo do loop \"{slug_for_modal}\" foi REPROVADO por "
                "/daily-loop:review-created."
            )
            blocker_line = (
                f"\n\nBlockers remanescentes: {sentinel.blocker_count}"
                if sentinel.blocker_count
                else ""
            )
            box.setInformativeText(
                "Sentinel `.review-blocked` encontrado em:\n"
                f"{sentinel.path}\n\n"
                "Recomendado: Cancelar, ler _LOOP-CREATED-AUDIT.md, corrigir "
                "blockers e re-rodar /daily-loop:review-created."
                f"{blocker_line}\n\n"
                "Executar mesmo assim?"
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            yes_btn = box.button(QMessageBox.StandardButton.Yes)
            yes_btn.setText("Executar mesmo assim")
            cancel_btn = box.button(QMessageBox.StandardButton.Cancel)
            cancel_btn.setText("Cancelar")
            choice = box.exec()
            if choice != QMessageBox.StandardButton.Yes:
                logger.info(
                    "[loop] %s execution cancelled (.review-blocked override declined)",
                    slug_for_modal,
                )
                signal_bus.toast_requested.emit(
                    "Execucao cancelada — .review-blocked ativo.",
                    "info",
                )
                return
            logger.warning(
                "[loop] %s executing despite .review-blocked sentinel "
                "(blockers=%d, user override)",
                slug_for_modal,
                sentinel.blocker_count,
            )

        try:
            specs = build_loop_specs(raw, loop_root)
        except DailyLoopConfigError as exc:
            signal_bus.toast_requested.emit(f"Loop invalido: {exc}", "error")
            return
        except OSError as exc:
            signal_bus.toast_requested.emit(f"Erro ao ler PROGRESS.md: {exc}", "error")
            return

        if not specs:
            signal_bus.toast_requested.emit(
                "PROGRESS.md sem itens pendentes — loop concluido. "
                "Rode /daily-loop:review --slug X para o veredito final.",
                "info",
            )
            return

        slug = str(raw.get("daily_loop", {}).get("slug", "")) or "loop"
        # Count real items from buckets[*].items[*] — the legacy heuristic
        # `name.startswith("/daily-loop:do ")` only matched the fallback wrapper
        # shape and silently reported 0 for canonical post-/loop:integration
        # configs where commands are materialized inline.
        item_count = sum(
            len(b.get("items", []))
            for b in raw.get("daily_loop", {}).get("buckets", [])
        )
        logger.info("[loop] loading %s (%d items, %d specs)", slug, item_count, len(specs))

        self._template_label.setText(f"  \U0001f4cb  Loop: {slug} ({item_count} itens)")
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"Loop {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_rocksmash_clicked(self) -> None:
        """Expand the active _LOOP-CONFIG.json into the /loop-rocksmash:* queue.

        Requires the metrics-project-pill to point at a daily-loop
        _LOOP-CONFIG.json. Emits:
            1x /loop-rocksmash:prepare
            N pares /loop-rocksmash:do + /loop-rocksmash:review-done
                (apenas items com kind=iteration; preparo/finalizacao
                sao ignorados)
            1x /loop-rocksmash:rename

        Directives /clear, /model, /effort sao auto-injetadas conforme
        bucket boundaries (espelha build_loop_specs).
        """
        from workflow_app.command_queue.loop_rocksmash_expander import (
            build_loop_rocksmash_specs,
        )
        from workflow_app.config.app_state import app_state
        from workflow_app.daily_loop import DailyLoopConfigError

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Selecione um _LOOP-CONFIG.json na metrics-project-pill "
                "antes de usar rocksmash.",
                "warning",
            )
            return

        config = app_state.config
        raw = config.raw if isinstance(config.raw, dict) else {}

        if raw.get("kind") != "daily-loop" or "daily_loop" not in raw:
            signal_bus.toast_requested.emit(
                "Este botao opera apenas sobre _LOOP-CONFIG.json "
                "(kind=daily-loop). Carregue um gerado por /loop ou "
                "/daily-loop:enumerate.",
                "warning",
            )
            return

        loop_root = Path(config.config_path).parent

        try:
            specs = build_loop_rocksmash_specs(raw, loop_root)
        except DailyLoopConfigError as exc:
            signal_bus.toast_requested.emit(
                f"rocksmash invalido: {exc}", "error"
            )
            return

        slug = str(raw.get("daily_loop", {}).get("slug", "")) or "rocksmash"
        pair_count = sum(
            1 for s in specs if s.name.startswith("/loop-rocksmash:do ")
        )
        bucket_ids = sorted(
            {
                str(it.get("bucket", ""))
                for it in (raw.get("daily_loop", {}).get("items_index") or {}).values()
                if isinstance(it, dict) and str(it.get("kind", "iteration")) == "iteration"
            }
        )
        logger.info(
            "[rocksmash] loading %s (%d pares, %d specs, buckets=%s)",
            slug,
            pair_count,
            len(specs),
            ",".join(bucket_ids) or "-",
        )

        self._template_label.setText(
            f"  \U0001f4cb  rocksmash: {slug} ({pair_count} pares)"
        )
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"rocksmash {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_rocksmash_review_clicked(self) -> None:
        """Enfileira o template estatico do botao `rocksmash review`.

        Le o JSON do projeto ativo (metrics-project-pill) e injeta o
        template estatico de 12 itens da Secao 4 do
        task-004-botao-workflow-app.md (loop 05-21-rocksmash-review-base):

            /clear /model opus /effort high
            /agents:troop-review {json}
            /clear  /agents:troop-review {json}   (x4)

        Sao 5 invocacoes single-pass de /agents:troop-review. A primeira
        herda o /clear do bloco prep; as outras 4 recebem /clear proprio.
        /model e /effort aparecem uma unica vez (WORKFLOW-APP-RULES.md
        secao 3 — politica anti-redundancia).

        Guardrails da Secao 4.0:
          a/b. valida que a pill aponta para um JSON suportado; bloqueia
               o clique com toast acionavel quando ausente/invalido;
          c.   desabilita o botao por uma janela curta (anti duplo-disparo);
          d.   registra no log timestamp (formatter), json e contagem.

        Dependencia de runtime: /agents:troop-review precisa existir
        (criado pela Task 3 do mesmo loop). Este botao apenas enfileira
        a string do comando — nao cria/atualiza o slash-command.
        """
        from workflow_app.config.app_state import app_state

        # ── Guardrail 4.0 a/b: JSON suportado na metrics-project-pill ──
        if not app_state.has_config or app_state.config is None:
            signal_bus.toast_requested.emit(
                "rocksmash review requer um JSON carregado na "
                "metrics-project-pill. Use o botao [json] (queue-btn-json) "
                "para carregar ou criar um project.json antes de acionar "
                "este botao.",
                "warning",
            )
            return

        config = app_state.config
        json_path = str(config.config_path or "")
        if not json_path or not Path(json_path).is_file():
            signal_bus.toast_requested.emit(
                "O JSON da metrics-project-pill nao foi localizado em disco "
                f"({json_path or 'caminho vazio'}). Recarregue o projeto via "
                "botao [json] (queue-btn-json) e tente novamente.",
                "error",
            )
            return

        # ── Guardrail 4.0 c: anti duplo-disparo — desabilita o botao ──
        btn = next(
            (
                b for b in self.findChildren(QPushButton)
                if b.property("testid") == "queue-btn-rocksmash-review"
            ),
            None,
        )
        if btn is not None:
            btn.setEnabled(False)
            QTimer.singleShot(800, lambda b=btn: b.setEnabled(True))

        # ── Monta o template estatico de 12 itens (Secao 4 da task-004) ──
        cfg = GROUP_MAP["rocksmash_review"]
        model = cfg["model"]
        effort = cfg["effort"]
        troop_rounds = 5

        specs: list[CommandSpec] = list(_build_prep_specs("rocksmash_review"))
        pos = len(specs) + 1
        for round_idx in range(troop_rounds):
            # A 1a invocacao herda o /clear do bloco prep; as demais
            # recebem /clear proprio. /model e /effort ja vigentes —
            # nao reemitir (anti-redundancia).
            if round_idx > 0:
                specs.append(
                    CommandSpec(
                        name="/clear", model=model,
                        interaction_type=InteractionType.AUTO, position=pos,
                    )
                )
                pos += 1
            specs.append(
                CommandSpec(
                    name=f"/agents:troop-review {json_path}",
                    model=model, effort=effort,
                    interaction_type=InteractionType.AUTO, position=pos,
                )
            )
            pos += 1

        # ── Guardrail 4.0 d: log da UI (timestamp via formatter) ──
        logger.info(
            "[rocksmash-review] json=%s | %d comandos injetados na fila "
            "(%d rodadas /agents:troop-review)",
            json_path, len(specs), troop_rounds,
        )
        self._template_label.setText(
            f"  \U0001f4cb  rocksmash review "
            f"({troop_rounds}x /agents:troop-review)"
        )
        self._template_label.setVisible(True)
        self._maybe_auto_save("rocksmash review")
        signal_bus.pipeline_ready.emit(specs)

    def _on_legacy_to_dcp_clicked(self) -> None:
        """Enfileira pipeline legacy-to-dcp para o project.json carregado.

        Le `metrics-project-pill` (project.json, qualquer schema V1/V2/V3).
        Gate 2 verboso pt-BR quando `has_config` ausente: sugere botao
        `queue-btn-json` (/project-json) para carregar/criar project.json.

        Sequencia enfileirada (source.md, pos-codex-review 2026-05-17):
          1. /clear + /model sonnet + /effort medium
          2. /legacy:detect <path>
             (gate: V1/V2 nao migram automaticamente — /legacy:detect
              classifica e materializa MODULES-INDEX.json. Quando schema!=V3,
              o proprio /legacy:detect imprime FALHA com instrucao para
              executar migracao manual via /project-json antes de reenfileirar
              esta pipeline. Decisao codex/2026-05-17: opcao B — handler nao
              tenta migrar schema, pois /project-json nao implementa branch
              --migrate-v3 e seria violacao Zero Silencio chamar cmd inexistente)
          3. /clear + /model sonnet + /effort medium
          4. /delivery:init <path> --from-modules-index (skip if v1 existe)
          5. /clear + /model sonnet + /effort medium
          6. /legacy:modules-from-features <path>
          7. /clear + /model sonnet + /effort medium
          8. /dcp:meta-completeness --all --auto-fix-p0 <path>
          9. /clear + /model sonnet + /effort high
          10. /legacy:enqueue-all-modules <path>

        O ultimo item expande dinamicamente em runtime para uma sequencia
        /build-module-pipeline --module {id} por modulo detectado
        (analogo ao /loop-rocksmash:prepare expandir do rocksmash).
        Idempotente: re-rodar nao quebra modulos ja convertidos.
        """
        from workflow_app.config.app_state import app_state

        # Gate 1: has_config — verbose pt-BR (feedback_workflow_app_gate_verbose)
        if not app_state.has_config or app_state.config is None:
            signal_bus.toast_requested.emit(
                "legacy-to-dcp requer project.json carregado na pill superior. "
                "Use o botao [json] (queue-btn-json) para criar ou carregar um "
                "project.json antes de rodar este pipeline.",
                "warning",
            )
            return

        config = app_state.config
        path = str(config.config_path)
        if not path:
            signal_bus.toast_requested.emit(
                "project.json carregado nao expoe config_path. Recarregue o "
                "projeto via botao [json] (queue-btn-json) e tente novamente.",
                "error",
            )
            return

        group = "legacy_to_dcp"
        cfg = GROUP_MAP[group]
        model = cfg["model"]
        effort_standard = cfg["effort"]

        def _cmd(name: str, start: int, effort: EffortLevel = effort_standard) -> CommandSpec:
            return CommandSpec(
                name=name, model=model, effort=effort,
                interaction_type=InteractionType.AUTO, position=start,
            )

        # Constroi APENAS os comandos reais; a injecao de /clear /model /effort
        # com anti-redundancia (ai-forge/rules/workflow-app-command-lists.md
        # secao 3.1 + 3.4) e delegada a _inject_clears — mesmo helper canonico
        # usado por queue-btn-dcp-build. O _prep() unconditional anterior
        # reemitia /model sonnet /effort medium antes de CADA step (steps 1-4
        # identicos), violando a secao 3.1. _inject_clears emite o triplet
        # completo so no primeiro comando e, no salto de effort medium->high do
        # step final, reemite SO /effort high (model sonnet inalterado, suprimido).
        from workflow_app.templates.quick_templates import _inject_clears

        real_specs: list[CommandSpec] = [
            # Step 1: detect (aborta V1/V2 com instrucao manual; ver docstring)
            _cmd(f"/legacy:detect {path}", 1),
            # Step 2: delivery init/migrate (idempotente)
            _cmd(f"/delivery:init --if-missing {path}", 2),
            # Step 3: modules-from-features
            _cmd(f"/legacy:modules-from-features {path}", 3),
            # Step 4: meta-completeness com auto-fix-p0 em todos modulos
            _cmd(f"/dcp:meta-completeness --all --auto-fix-p0 {path}", 4),
            # Step 5: enqueue-all-modules (expande dinamicamente em runtime; high)
            _cmd(f"/legacy:enqueue-all-modules {path}", 5, EffortLevel.HIGH),
        ]
        specs = _inject_clears(real_specs)

        slug = Path(path).stem
        logger.info(
            "[legacy-to-dcp] enqueued %d specs for project=%s",
            len(specs), slug,
        )
        self._template_label.setText(
            f"  \U0001f4cb  legacy-to-dcp: {slug} ({len(specs)} specs)"
        )
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"legacy-to-dcp {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_multibackend_clicked(self) -> None:
        """Enfileira a pipeline multibackend para o project.json carregado.

        Le `metrics-project-pill` (project.json, qualquer schema V1/V2/V3) e
        passa `config.config_path` como `$1` aos 6 subcomandos. Vincula uma
        pagina estatica HTML/CSS/JS ja hospedada na Hostinger ao backend
        central multi-tenant (bloco 06-03), injeta login OIDC funcional e
        deixa o site em producao.

        Gate 1 (has_config): toast verboso pt-BR quando ausente, sugere o
        botao `queue-btn-json` (/project-json). Gate 2 (config_path): toast
        verboso pt-BR quando o config carregado nao expoe config_path.

        Sequencia enfileirada (todos opus/high, GROUP_MAP["multibackend"]):
          1. /multibackend:scan <path>        (resolve identidade/OIDC/arq)
          2. /multibackend:link-auth <path>   (injeta login idempotente)
          3. /multibackend:env-wire <path>    (audita OIDC, gera env-config)
          4. /multibackend:build-verify <path>(smoke local por arquitetura)
          5. /multibackend:deploy <path>      (rsync + snapshot + rollback)
          6. /multibackend:verify-prod <path> (verifica producao, veredito)

        Cada subcomando comunica com o anterior via scan-report.json em
        disco (nao via contexto de conversa), por isso _inject_clears poe um
        /clear entre cada um. Idempotente: re-rodar nao quebra o que ja foi
        aplicado (cada /multibackend:* e idempotente por sentinela/snapshot).
        """
        from workflow_app.config.app_state import app_state

        # Gate 1: has_config — verbose pt-BR (feedback_workflow_app_gate_verbose)
        if not app_state.has_config or app_state.config is None:
            signal_bus.toast_requested.emit(
                "multibackend requer project.json carregado na pill superior. "
                "Use o botao [json] (queue-btn-json) para criar ou carregar um "
                "project.json antes de rodar este pipeline.",
                "warning",
            )
            return

        config = app_state.config
        path = str(config.config_path)
        if not path:
            signal_bus.toast_requested.emit(
                "project.json carregado nao expoe config_path. Recarregue o "
                "projeto via botao [json] (queue-btn-json) e tente novamente.",
                "error",
            )
            return

        group = "multibackend"
        cfg = GROUP_MAP[group]
        model = cfg["model"]
        effort = cfg["effort"]

        def _cmd(name: str, start: int) -> CommandSpec:
            return CommandSpec(
                name=name, model=model, effort=effort,
                interaction_type=InteractionType.AUTO, position=start,
            )

        # Constroi APENAS os comandos reais; a injecao de /clear /model /effort
        # com anti-redundancia e delegada a _inject_clears (mesmo helper canonico
        # usado por queue-btn-legacy-to-dcp e queue-btn-dcp-build).
        from workflow_app.templates.quick_templates import _inject_clears

        real_specs: list[CommandSpec] = [
            _cmd(f"/multibackend:scan {path}", 1),
            _cmd(f"/multibackend:link-auth {path}", 2),
            _cmd(f"/multibackend:env-wire {path}", 3),
            _cmd(f"/multibackend:build-verify {path}", 4),
            _cmd(f"/multibackend:deploy {path}", 5),
            _cmd(f"/multibackend:verify-prod {path}", 6),
        ]
        specs = _inject_clears(real_specs)

        slug = Path(path).stem
        logger.info(
            "[multibackend] enqueued %d specs for project=%s",
            len(specs), slug,
        )
        self._template_label.setText(
            f"  \U0001f50c  multibackend: {slug} ({len(specs)} specs)"
        )
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"multibackend {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_boilerplate_clicked(self) -> None:
        """Carrega o pipeline boilerplate (9 passos).

        Comportamento especial: NAO le metrics-project-pill (project.json).
        Abre BoilerplatePathDialog para o usuario colar o path do repo legado.
        Em seguida injeta config_path por-spec:
          - /boilerplate:scan → repo_path (caminho fornecido)
          - demais /boilerplate:* → staging_path = output/workspace/boilerplates/_staging/{basename(repo_path)}
          - /clear, /model X, /effort Y → "" (sem arg)

        O patch em main_window._on_pipeline_ready preserva esses config_path
        pre-setados (so escreve quando spec.config_path esta vazio).
        """
        from pathlib import Path

        from workflow_app.dialogs.boilerplate_path_dialog import BoilerplatePathDialog

        dlg = BoilerplatePathDialog(parent=self)
        if dlg.exec() != BoilerplatePathDialog.Accepted:
            return

        repo_path = dlg.repo_path
        if not repo_path:
            signal_bus.toast_requested.emit("Path vazio — boilerplate cancelado.", "warning")
            return

        # Basename normalizado: tira trailing slash e usa o ultimo segmento.
        # Bloqueia "." e ".." para preservar o isolamento do staging.
        basename = Path(repo_path).name
        if not basename or basename in {".", ".."}:
            signal_bus.toast_requested.emit(
                f"Basename invalido derivado de '{repo_path}'.", "error"
            )
            return

        staging_path = f"output/workspace/boilerplates/_staging/{basename}"

        raw = copy.deepcopy(TEMPLATE_BOILERPLATE)
        # Injeta config_path por spec. Headers (/clear, /model, /effort) ficam vazios.
        for spec in raw:
            if spec.name == "/clear" or spec.name.startswith("/model ") or spec.name.startswith("/effort "):
                spec.config_path = ""
                continue
            if spec.name == "/boilerplate:scan":
                spec.config_path = repo_path
            elif spec.name.startswith("/boilerplate:"):
                spec.config_path = staging_path
            else:
                spec.config_path = ""

        self._template_label.setText("  \U0001f4cb  Boilerplate")
        self._template_label.setVisible(True)
        # NOTA: pulamos _maybe_auto_save porque este fluxo nao depende de projeto carregado.

        # Reusa logica de _load_quick_template (injecao de /model rows e renumeracao).
        expanded: list[CommandSpec] = []
        current_model = None
        for spec in raw:
            if spec.name == "/clear":
                expanded.append(spec)
                continue
            if spec.name.startswith("/model "):
                current_model = spec.model
                expanded.append(spec)
                continue
            if spec.model != current_model:
                model_spec = CommandSpec(
                    name=f"/model {spec.model.value.lower()}",
                    model=spec.model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=0,
                )
                expanded.append(model_spec)
                current_model = spec.model
            expanded.append(spec)

        for i, spec in enumerate(expanded, start=1):
            spec.position = i

        signal_bus.pipeline_ready.emit(expanded)
        signal_bus.toast_requested.emit(
            f"Boilerplate carregado: 9 passos sobre {basename}", "success"
        )

    def _on_book_legacy_clicked(self) -> None:
        """Abre o modal de 5 campos do pipeline /book-legacy e enfileira a cadeia.

        Comportamento especial (espelha _on_boilerplate_clicked): NAO le
        metrics-project-pill (project.json). Abre BookLegacyDialog para o
        operador informar os 5 inputs (pasta de imagens, nome do livro,
        formato, fonte, glossario).

        Ao confirmar, o dict book_legacy_inputs alimenta o builder
        _enqueue_book_legacy, que expande a cadeia de subcomandos
        /book-legacy:* como itens proprios da fila. O orquestrador
        /book-legacy NUNCA e enfileirado como entrada unica
        (workflow-app-command-lists.md secao 8).
        """
        from workflow_app.dialogs.book_legacy_dialog import BookLegacyDialog

        dlg = BookLegacyDialog(parent=self)
        if dlg.exec() != BookLegacyDialog.Accepted:
            return

        book_legacy_inputs = dlg.book_legacy_inputs
        if not book_legacy_inputs.get("images_path") or not book_legacy_inputs.get(
            "book_name"
        ):
            signal_bus.toast_requested.emit(
                "Inputs incompletos — book-legacy cancelado.", "warning"
            )
            return

        specs = self._enqueue_book_legacy(book_legacy_inputs)

        book_name = book_legacy_inputs["book_name"]
        logger.info(
            "[book-legacy] enqueued %d specs for book=%s",
            len(specs),
            book_name,
        )
        self._template_label.setText(
            f"  \U0001f4d6  Book Legacy: {book_name} ({len(specs)} specs)"
        )
        self._template_label.setVisible(True)
        # NOTA: pulamos _maybe_auto_save porque este fluxo nao depende de
        # projeto carregado (espelha _on_boilerplate_clicked).
        signal_bus.pipeline_ready.emit(specs)
        signal_bus.toast_requested.emit(
            f"Book Legacy carregado: cadeia /book-legacy:* sobre '{book_name}'",
            "success",
        )

    def _enqueue_book_legacy(
        self, book_legacy_inputs: dict[str, str]
    ) -> list[CommandSpec]:
        """Expande o pipeline /book-legacy na cadeia de subcomandos /book-legacy:*.

        Mapeamento canonico (source.md Parte 12, daily_loop.buckets[*].items[*]):
          - preparo:      /book-legacy:scan
          - iteration:    /book-legacy:ocr, :apply-glossary, :diff-original
          - finalizacao:  /book-legacy:review-orthographic, :layout-plan,
                          :compose-pages, :build-pdf, :validate

        Regra INVIOLAVEL (workflow-app-command-lists.md secao 8): o orquestrador
        /book-legacy NUNCA entra como entrada unica. Este builder sempre expande
        os 9 subcomandos como itens proprios.

        model/effort por subcomando segue os 3 tiers do Bloco I-34:
          - Tier mecanico (sonnet/low): scan, ocr, apply-glossary, build-pdf,
                                        validate
          - Tier texto    (sonnet/medium): diff-original, layout-plan,
                                           compose-pages
          - Tier juizo    (opus/high):  review-orthographic

        NOTA sobre o tier mecanico: o frontmatter v2 dos subcomandos declara
        `model: sonnet`; a diretiva textual `/model sonnet` na fila e o campo
        CommandSpec.model (usado para o badge da UI) ficam ambos alinhados ao
        enum ModelName do workflow-app.

        /clear, /model e /effort sao injetados no boundary de cada subcomando
        para isolar o contexto (analogo a build_loop_specs / boilerplate).
        """
        # Tiers do Bloco I-34: (token textual do /model, enum representavel,
        # token textual do /effort, enum de effort).
        _MECHANICAL = ("sonnet", ModelName.SONNET, "low", EffortLevel.LOW)
        _TEXT = ("sonnet", ModelName.SONNET, "medium", EffortLevel.STANDARD)
        _JUDGMENT = ("opus", ModelName.OPUS, "high", EffortLevel.HIGH)

        images_path = book_legacy_inputs["images_path"]
        book_name = book_legacy_inputs["book_name"]
        page_format = book_legacy_inputs.get("page_format", "14x21cm")
        font = book_legacy_inputs.get("font", "EB Garamond")
        glossary = book_legacy_inputs.get("glossary", "glossario-base.json")

        # Argumentos comuns repassados a cada subcomando. shlex.quote protege
        # nome de livro e fonte que podem conter espacos.
        common_args = (
            f"{shlex.quote(images_path)}"
            f" --book {shlex.quote(book_name)}"
            f" --format {shlex.quote(page_format)}"
            f" --font {shlex.quote(font)}"
            f" --glossary {shlex.quote(glossary)}"
        )

        # Cada tupla: (slash-command, tier). A ordem reflete o canonical loop
        # do pipeline (preparo -> iteration -> finalizacao). O orquestrador
        # /book-legacy NAO aparece — apenas os 9 subcomandos expandidos.
        chain: list[tuple[str, tuple]] = [
            # preparo
            ("/book-legacy:scan", _MECHANICAL),
            # iteration (per-pagina)
            ("/book-legacy:ocr", _MECHANICAL),
            ("/book-legacy:apply-glossary", _MECHANICAL),
            ("/book-legacy:diff-original", _TEXT),
            # finalizacao
            ("/book-legacy:review-orthographic", _JUDGMENT),
            ("/book-legacy:layout-plan", _TEXT),
            ("/book-legacy:compose-pages", _TEXT),
            ("/book-legacy:build-pdf", _MECHANICAL),
            ("/book-legacy:validate", _MECHANICAL),
        ]

        specs: list[CommandSpec] = []
        pos = 0
        current_model_token: str | None = None
        current_effort_token: str | None = None

        for cmd_name, tier in chain:
            model_token, model_enum, effort_token, effort_enum = tier
            # Boundary directives: /clear sempre, /model e /effort apenas quando
            # o token muda em relacao ao subcomando anterior (evita ruido).
            pos += 1
            specs.append(
                CommandSpec(
                    name="/clear",
                    model=model_enum,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=pos,
                )
            )
            if model_token != current_model_token:
                pos += 1
                specs.append(
                    CommandSpec(
                        name=f"/model {model_token}",
                        model=model_enum,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                    )
                )
                current_model_token = model_token
            if effort_token != current_effort_token:
                pos += 1
                specs.append(
                    CommandSpec(
                        name=f"/effort {effort_token}",
                        model=model_enum,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=pos,
                    )
                )
                current_effort_token = effort_token
            pos += 1
            specs.append(
                CommandSpec(
                    name=f"{cmd_name} {common_args}",
                    model=model_enum,
                    effort=effort_enum,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=pos,
                )
            )

        return specs

    def _on_publish_micro_sites_multilingue_clicked(self) -> None:
        """Validate and enqueue the multilingue publish chain for a slug.

        Opens a small QInputDialog asking for the micro-site slug. On confirm,
        delegates to ``micro_sites_multilingue_expander.validate_and_build_specs``
        which runs the 4 validation gates (deploy-map, locales-map, site.json
        per-locale, REVIEW.md status:approved). Any failure -> red toast and
        nothing is enqueued. On success, emits the 7 specs via
        ``signal_bus.pipeline_ready``.

        Espelha o padrao de ``_on_book_legacy_clicked``: nao depende de
        metrics-project-pill; abre dialog proprio; emite specs e toast.
        """
        from PySide6.QtWidgets import QInputDialog
        from workflow_app.command_queue.micro_sites_multilingue_expander import (
            MicroSitesMultilingueError,
            validate_and_build_specs,
        )

        slug, ok = QInputDialog.getText(
            self,
            "Publish micro-site multilingue",
            "Slug do micro-site (ex.: a01):",
        )
        if not ok:
            return
        slug = slug.strip()
        if not slug:
            signal_bus.toast_requested.emit(
                "Slug vazio — publicacao multilingue cancelada.", "warning"
            )
            return

        try:
            result = validate_and_build_specs(slug, Path.cwd())
        except MicroSitesMultilingueError as exc:
            signal_bus.toast_requested.emit(
                f"Publish multilingue bloqueado: {exc}", "error"
            )
            return

        logger.info(
            "[publish-micro-sites-multilingue] slug=%s host=%s specs=%d",
            result.slug,
            result.host,
            len(result.specs),
        )
        self._template_label.setText(
            f"  \U0001f310  publish multilingue: {result.slug} "
            f"({result.host}, {len(result.specs)} specs)"
        )
        self._template_label.setVisible(True)
        signal_bus.pipeline_ready.emit(result.specs)
        signal_bus.toast_requested.emit(
            f"Publish multilingue carregado: {result.slug} -> 4 locales (br/it/es/us)",
            "success",
        )

    def _on_run_command(self, cmd_text: str) -> None:
        """Update last-command row e highlight a queue row correspondente.

        A row do queue-last-command renderiza: prefixo (sempre) + count
        (queue-count-label, vive sincronizado via metrics_updated) + comando
        sem args + eye-icon com hover-tooltip do comando completo.
        """
        cleaned = cmd_text.strip()
        self._last_cmd_full = cleaned
        parts = cleaned.split()
        cmd_token = parts[0] if parts else ""
        self._last_cmd_label.setText(cmd_token)
        self._last_cmd_label.setVisible(True)
        self._last_cmd_count_slot.setVisible(True)
        self._last_cmd_eye.setVisible(True)
        self._last_cmd_eye.setToolTip(cleaned)
        # queue-model-effort-row: captura o ultimo /model e /effort rodados
        # a partir de queue-command-list. Atualiza so o lado correspondente.
        if cmd_token == "/model" and len(parts) > 1:
            self._last_model_value = parts[1]
            self._last_model_label.setText(f"/model: {self._last_model_value}")
        elif cmd_token == "/effort" and len(parts) > 1:
            self._last_effort_value = parts[1]
            self._last_effort_label.setText(f"/effort: {self._last_effort_value}")
        self._highlight_current_command(cleaned)
        self._maybe_auto_save(cmd_text)

    def _highlight_current_command(self, cmd_text: str) -> None:
        """Highlight the queue row whose command matches cmd_text."""
        for item in self._items:
            item.set_highlighted(item.command_text() == cmd_text)

    def load_pipeline(self, specs: list[CommandSpec]) -> None:
        """Populate the queue with CommandSpec objects."""
        # Onda 4: clear DCP context — the new pipeline isn't (yet) backed by
        # a SPECIFIC-FLOW.json. The DCP handler will re-arm
        # _current_dcp_flow_path AFTER this signal returns, so DCP-sourced
        # loads end up with the path correctly set. Non-DCP sources stay None.
        self._current_dcp_flow_path = None

        # Reset queue-model-effort-row: nova pipeline reseta o ultimo /model
        # e /effort rodados (escopados a queue-command-list atual).
        self._reset_model_effort_row()

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

        # Garantir positions 1-based únicas — specs carregados em lote
        # (ex.: rocksmash expander) chegam com position=0; sem renumeração,
        # _on_remove_requested filtra todos os itens ao deletar qualquer um.
        for i, it in enumerate(self._items, start=1):
            it.get_spec().position = i

        # Re-add stretch at end
        self._items_layout.addStretch()

        self._empty_widget.setVisible(False)
        self._list_widget.setVisible(True)
        self._emit_progress_metrics()
        self._update_save_btn_state()

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

        # Assign unique 1-based position so _on_remove_requested filter is correct.
        item.get_spec().position = len(self._items)

        # Re-add stretch at end
        if stretch_item:
            self._items_layout.addStretch()

        self._empty_widget.setVisible(False)
        self._list_widget.setVisible(True)
        self._emit_progress_metrics()

    def _on_inline_add_clicked(self) -> None:
        """[+] Adicionar Comando — abre dialog com 3 inputs (1 obrigatorio +
        2 opcionais) + checkbox JSON por linha + radio de posicao (next/last)
        e injeta cada texto preenchido como item transiente, na ordem dos campos.

        Posicao next (default): o primeiro item entra entre a ultima linha
        "sent" e a primeira linha "pending"; os subsequentes empilham apos
        o ultimo injetado (preserva a ordem dos inputs).
        Posicao last: cada item entra no final da fila, na ordem dos inputs.
        Itens sao transientes — nao persistem em template/JSON/memoria;
        load_pipeline() / clear() os apagam.
        """
        from PySide6.QtWidgets import (
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QRadioButton,
            QVBoxLayout,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Adicionar Comando")
        dialog.setMinimumWidth(520)
        dialog.setMinimumHeight(360)
        dialog.setProperty("testid", "dialog-add-command")

        layout = QVBoxLayout(dialog)

        header_row = QHBoxLayout()
        lbl_cmd = QLabel("Comando")
        lbl_cmd.setStyleSheet("color: #A1A1AA; font-size: 11px; font-weight: 600;")
        lbl_json = QLabel("JSON")
        lbl_json.setStyleSheet("color: #FBBF24; font-size: 11px; font-weight: 600; padding-left: 4px;")
        lbl_json.setFixedWidth(40)
        header_row.addWidget(lbl_cmd)
        header_row.addWidget(lbl_json)
        layout.addLayout(header_row)

        inputs_and_checks = []
        for i, label_text in enumerate([
            "Comando a executar:",
            "Comando adicional (opcional):",
            "Comando adicional (opcional):",
        ]):
            layout.addWidget(QLabel(label_text))
            row = QHBoxLayout()
            inp = QLineEdit(dialog)
            inp.setProperty("testid", f"queue-add-input-{i + 1}")
            chk = QCheckBox(dialog)
            chk.setProperty("testid", f"queue-add-json-{i + 1}")
            chk.setToolTip("Anexar caminho do project.json ao comando")
            chk.setFixedWidth(40)
            chk.setStyleSheet("QCheckBox { color: #FBBF24; }")
            row.addWidget(inp)
            row.addWidget(chk)
            layout.addLayout(row)
            layout.addSpacing(4)
            inputs_and_checks.append((inp, chk))

        line_edit_1, chk_1 = inputs_and_checks[0]
        line_edit_2, chk_2 = inputs_and_checks[1]
        line_edit_3, chk_3 = inputs_and_checks[2]

        layout.addSpacing(8)
        layout.addWidget(QLabel("Posicao de insercao:"))
        radio_next = QRadioButton(
            "next — proximo (entre o ultimo enviado e o proximo pendente)",
            dialog,
        )
        radio_last = QRadioButton(
            "last — ultimo (apos todos os items da fila)",
            dialog,
        )
        radio_next.setChecked(True)
        layout.addWidget(radio_next)
        layout.addWidget(radio_last)

        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        line_edit_1.setFocus()

        if dialog.exec() != QDialog.Accepted:
            return

        import os as _os

        from workflow_app.config.app_state import app_state as _app_state
        json_path = ""
        if _app_state.has_config and _app_state.config:
            try:
                json_path = _os.path.relpath(
                    _app_state.config.config_path,
                    str(_app_state.config.project_dir),
                )
            except ValueError:
                json_path = str(_app_state.config.config_path)

        filled = []
        for line_edit, chk in [(line_edit_1, chk_1), (line_edit_2, chk_2), (line_edit_3, chk_3)]:
            text = line_edit.text().strip()
            if not text:
                continue
            if chk.isChecked() and json_path:
                text = f"{text} {json_path}"
            filled.append(text)

        if not filled:
            return
        position = "last" if radio_last.isChecked() else "next"
        for text in filled:
            self._inject_next_command(text, position=position)

    def _inject_next_command(self, text: str, position: str = "next") -> None:
        """Cria CommandSpec transiente e insere conforme a posicao.

        position="next" (default): apos sent/injected items (proximo a rodar).
        position="last": no final da fila (apos todos os items existentes).
        kimi_eligible=True forca a seta azul visivel independente do
        whitelist (ver CommandItemWidget._setup_ui).
        """
        spec = CommandSpec(
            name=text,
            model=ModelName.SONNET,
            interaction_type=InteractionType.AUTO,
            kimi_eligible=True,
        )
        item = self._make_item(spec)
        item._is_injected = True

        if position == "last":
            insert_idx = len(self._items)
        else:
            # Insertion index: depois do ultimo item sent OU injected.
            insert_idx = 0
            for i, existing in enumerate(self._items):
                if existing._is_sent or getattr(existing, "_is_injected", False):
                    insert_idx = i + 1

        # _items_layout = [items..., stretch]. insertWidget(K, w) coloca
        # w antes do K-esimo filho, entao insert_idx == len(self._items)
        # coloca w entre o ultimo item e o stretch.
        self._items_layout.insertWidget(insert_idx, item)
        self._items.insert(insert_idx, item)

        # Renumerar position 1-based para manter _item_at() coerente.
        for i, it in enumerate(self._items, start=1):
            it.get_spec().position = i

        self._empty_widget.setVisible(False)
        self._list_widget.setVisible(True)
        self._emit_progress_metrics()
        self._update_save_btn_state()

    def _update_save_btn_state(self) -> None:
        if hasattr(self, '_save_btn'):
            self._save_btn.setEnabled(len(self._items) > 0)

    def clear_queue(self) -> None:
        for item in self._items:
            item.deleteLater()
        self._items.clear()
        # P3 (2026-05-17): a row do queue-last-command nao some mais — so o
        # prefixo "Last command:" permanece visivel; count/cmd/eye recolhem.
        self._last_cmd_label.setVisible(False)
        self._last_cmd_count_slot.setVisible(False)
        self._last_cmd_eye.setVisible(False)
        self._last_cmd_eye.setToolTip("")
        self._last_cmd_full = ""
        self._reset_model_effort_row()
        # P4: queue-template-label e sempre visivel; nao escondemos mais.
        self._empty_widget.setVisible(True)
        self._list_widget.setVisible(False)
        self._emit_progress_metrics()
        self._update_save_btn_state()

    def _reset_model_effort_row(self) -> None:
        self._last_model_value = ""
        self._last_effort_value = ""
        self._last_model_label.setText("/model: —")
        self._last_effort_label.setText("/effort: —")

    def _item_at(self, position: int) -> CommandItemWidget | None:
        for item in self._items:
            if item.get_spec().position == position:
                return item
        return None

    _DONE_STATUSES = (
        CommandStatus.CONCLUIDO,
        CommandStatus.ERRO,
        CommandStatus.PULADO,
    )

    def _emit_progress_metrics(self) -> None:
        """Emit metrics_updated(done, total) so queue-progress-ring reflects the queue.

        done = items that left the pending state by either:
          - being dispatched to a terminal (_is_sent True — the amber-dot UX,
            which is how live runs mark progress); or
          - reaching a terminal CommandStatus (CONCLUIDO/ERRO/PULADO — used by
            the resume path that hydrates state from DB).
        total = len(self._items). Failed/skipped count as done because they
        are no longer pending — the ring represents finished/total, not
        success/total.
        """
        total = len(self._items)
        done = sum(
            1
            for i in self._items
            if i._is_sent or i._status in self._DONE_STATUSES
        )
        signal_bus.metrics_updated.emit(done, total)

    def _resolve_item_provider(self, spec: CommandSpec) -> Provider:
        """Resolver injetado em cada CommandItemWidget para colorir o botao unico.

        Classifica o provider efetivo do item via o modulo PURO
        provider_router.classify_provider, montando o RoutingState SOMENTE com
        estado de worker (checkboxes T2/T3) + Main LLM ativo (invariantes 2 e 5:
        eixo Worker antes do Main-LLM, nunca os terminal-route-toggles). Reusa a
        mesma construcao do step path (_on_step_btn_clicked)."""
        routing_state = RoutingState(
            kimi_worker_enabled=bool(
                getattr(self, "_use_kimi_chk", None) is not None
                and self._use_kimi_chk.isChecked()
            ),
            codex_worker_enabled=bool(
                getattr(self, "_use_codex_chk", None) is not None
                and self._use_codex_chk.isChecked()
            ),
            main_llm=self._resolve_interactive_main_llm(),
        )
        return classify_provider(spec, routing_state)

    def _make_item(self, spec: CommandSpec) -> CommandItemWidget:
        """Create a CommandItemWidget with can_reorder_fn injected."""
        item = CommandItemWidget(
            spec,
            can_reorder_fn=self._can_reorder,
            parent=self._items_container,
            provider_resolver=self._resolve_item_provider,
        )
        item.remove_requested.connect(self._on_remove_requested)
        item.skip_requested.connect(self._on_skip_requested)
        item.retry_requested.connect(self._on_retry_requested)
        item.cancel_requested.connect(self._on_cancel_requested)
        # Per-item green arrow passa por _dispatch_green_arrow — handler
        # unico responsavel por (a) decidir o terminal de destino conforme
        # estado de --force Kimi, (b) chamar _on_run_command quando o
        # comando foi efetivamente despachado (label + highlight usam
        # SEMPRE a string original do item, nunca a transformada), e (c)
        # mirror de /clear para o workspace no fluxo Use Kimi legado.
        # Centralizar a logica num unico slot elimina inconsistencia entre
        # caminhos paralelos (issue HIGH 3 do review adversarial).
        # Fix D-1: a seta verde (Claude/T1) passa por um slot que so marca
        # enviado quando `_dispatch_green_arrow` publica de fato (retorna True).
        # Espelha `_on_single_button_codex_dispatch`: sob Main Codex/Kimi o
        # dispatch pode abortar (`.md`/skill ausente) e o item NAO deve virar
        # ambar. O `_on_run_clicked` do item nao marca mais enviado.
        item.run_in_terminal_requested.connect(
            lambda cmd, it=item: self._on_single_button_green_dispatch(it, cmd)
        )
        item.run_in_kimi_terminal_requested.connect(self._dispatch_blue_arrow)
        item.run_in_kimi_terminal_requested.connect(self._on_run_command)
        # Fix D-5: local-action roda in-process; o queue widget e dono do
        # dispatch + toast (nunca cola `spec.name` no T1 — invariante 8).
        item.run_local_action_requested.connect(
            lambda spec, it=item: self._on_single_button_local_action_dispatch(it, spec)
        )
        # Fix D-6: adaptacao Kimi falhou (ValueError) -> toast visivel.
        item.kimi_adaptation_failed.connect(self._on_kimi_adaptation_failed)
        # Botao unico roxo (Codex/T3): reusa o dispatcher Codex existente
        # (to_t1=False => T3 xterm). Sem terminal novo (criterio de rejeicao 1).
        # O wiring fino de falhas Codex e detalhado na task 006.
        # Gate de mark-as-sent: o item so vira ambar quando o dispatcher publica
        # de fato (mesma logica do step path em _on_step_btn_clicked). Um abort
        # do dispatcher (comando inexistente / T3 nao pronto / adaptacao vazia)
        # deixa o item pendente; o toast do dispatcher e o feedback visivel
        # (review-executed task 006, finding F2).
        item.run_in_codex_terminal_requested.connect(
            lambda cmd, it=item: self._on_single_button_codex_dispatch(it, cmd)
        )
        item.sent_state_changed.connect(self._on_item_sent_state_changed)
        # --force Kimi pode estar ativo no momento da criacao do item: aplica
        # imediatamente a regra de visibilidade da seta de worker para o item
        # novo (migrado de _kimi_btn.setVisible para o botao unico adaptavel).
        # Fix D-3 (Position A): Main Kimi oculta as setas worker SOMENTE quando
        # o Worker Kimi esta desligado. Com Main Kimi + Worker Kimi ativos, a
        # seta permanece visivel para que o roteamento ao T2 (invariante 2:
        # worker antes do Main LLM) tenha feedback visual — clique e step
        # concordam em T2.
        _main_kimi = getattr(self, "_force_kimi_chk", None) and self._force_kimi_chk.isChecked()
        _worker_kimi = getattr(self, "_use_kimi_chk", None) and self._use_kimi_chk.isChecked()
        if _main_kimi and not _worker_kimi:
            item.set_worker_arrow_visible(False)
        return item

    def _on_single_button_codex_dispatch(
        self, item: CommandItemWidget, cmd_text: str
    ) -> None:
        """Slot do botao unico (roxo) para o worker Codex/T3.

        So marca o item como enviado quando `_dispatch_codex_command` publica de
        fato (retorna True). Em qualquer abort do dispatcher (comando inexistente
        em .claude/commands/, terminal T3 nao pronto, ou adaptacao vazia) o item
        permanece pendente e o toast emitido pelo dispatcher e o feedback visivel
        (Zero Silencio). Espelha o gate do step path (`_on_step_btn_clicked`:
        `if self._dispatch_codex_command(cmd): next_item._mark_as_sent()`),
        eliminando a assimetria do finding F2 do review-executed da task 006."""
        if self._dispatch_codex_command(cmd_text):
            item._mark_as_sent()

    def _on_item_sent_state_changed(self, _is_sent: bool) -> None:
        """Item toggled the amber-dot (sent) state — refresh queue-progress-ring."""
        self._emit_progress_metrics()

    # Default delay between paste and Enter for the blue-arrow Kimi path.
    _KIMI_BLUE_ARROW_DEFAULT_DELAY_MS: int = 1_000
    # Extra delay added when the previous workspace dispatch was /clear:
    # Kimi takes longer to repaint the prompt after a full TUI clear.
    _KIMI_AFTER_CLEAR_EXTRA_DELAY_MS: int = 2_000

    def _dispatch_blue_arrow(self, kimi_prompt: str) -> None:
        """Forward a blue-arrow click to `kimi_blue_arrow_dispatched` with
        the right delay. If the previous workspace dispatch was /clear, add
        2s extra because Kimi's TUI repaint after a clear is slower than
        normal — without the extra delay, Enter lands before /skill: is
        composed and the command is silently dropped.

        task 006 — condicao de falha 3 (adaptacao Kimi retorna texto vazio ->
        abortar). `adapt_to_kimi` levanta ValueError em vez de devolver vazio,
        entao na pratica o `_on_kimi_clicked` ja nem emite; este guard e
        defense-in-depth no proprio dispatcher (deliverable da task) para
        garantir que nenhum payload vazio chegue ao T2 sem feedback visivel.
        """
        if not kimi_prompt or not kimi_prompt.strip():
            signal_bus.toast_requested.emit(
                "Worker Kimi: adaptacao retornou texto vazio — dispatch abortado.",
                "warning",
            )
            return
        if self._last_workspace_dispatch_was_clear:
            delay = (
                self._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
                + self._KIMI_AFTER_CLEAR_EXTRA_DELAY_MS
            )
            self._last_workspace_dispatch_was_clear = False  # consumed
        else:
            delay = self._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
        signal_bus.kimi_blue_arrow_dispatched.emit(kimi_prompt, delay)

    # ───────────────────── Listener recovery dispatch ───────────────────── #
    # Loop 06-01-listener-recovery-command, TASK 08. A command queue vira a dona
    # do roteamento do payload de recuperacao: o builder PURO
    # (recovery_prompt.build_recovery_prompt) deixa de embutir
    # `/tools:listener-recovery`; em vez disso o MetricsBar (TASK 07) emite o
    # sinal semantico `request_recovery_command(channel, reason, context_file)`
    # e este handler monta+valida+roteia o comando real por canal/LLM antes de
    # qualquer paste. Fonte: ai-forge/rules/workflow-app-listeners.md.
    _RECOVERY_VALID_CHANNELS = ("interactive", "workspace", "workspace_xterm")

    def _resolve_interactive_main_llm(self) -> str:
        """Qual LLM ocupa o terminal interactive (T1) AGORA.

        Espelha a precedencia de `_dispatch_green_arrow`/`_on_btn_next_clicked`:
        radio Main Codex > checkbox Main Kimi (--force) > Claude (default)."""
        if getattr(self, "_main_codex_radio", None) and self._main_codex_radio.isChecked():
            return "codex"
        if getattr(self, "_force_kimi_chk", None) and self._force_kimi_chk.isChecked():
            return "kimi"
        return "claude"

    def current_main_llm(self) -> str:
        """Acessor publico read-only do Main LLM efetivo do T1 (`claude|codex|kimi`).

        Superficie UNICA para o `main_window` (insercoes LLM-aware) ler o Main LLM
        sem instanciar radio proprio nem ler o cache `MetricsBar._main_llm`. Encapsula
        `_resolve_interactive_main_llm()` (precedencia canonica codex > kimi > claude).
        Ver blacksmith/brainstorm-mcp/06-15-insertions-subtab-llm-routing.md §11.1/D1.
        """
        return self._resolve_interactive_main_llm()

    @staticmethod
    def _build_recovery_base_command(
        channel: str, reason: str, context_file: str
    ) -> str:
        """Monta o comando-cru de recuperacao (slash + args), sem roteamento.

        O roteamento por LLM/canal acontece DEPOIS, no handler. Manter o slash
        cru aqui (e nunca no builder puro) e o contrato do aceite da TASK 08."""
        return (
            f"/tools:listener-recovery --channel {channel} "
            f"--reason {reason} --context-file {context_file}"
        )

    def _reject_recovery_command(
        self, channel: str | None, message: str
    ) -> None:
        """Contrato de violacao: toast warning + failure/BLOCKED no canal.

        Zero Silencio / Zero Estados Indefinidos: nunca cola um comando
        malformado; sempre sinaliza o porque. Quando o canal e invalido nao ha
        dot para falhar, entao apenas o toast e emitido."""
        signal_bus.toast_requested.emit(message, "warning")
        if channel in self._RECOVERY_VALID_CHANNELS:
            signal_bus.terminal_force_failed.emit(channel, "BLOCKED")

    def _on_request_recovery_command(
        self, channel: str, reason: str, context_file: str
    ) -> None:
        """Handler do sinal semantico de recuperacao do red-listener (TASK 08).

        Valida o contrato de `request_recovery_command`, monta o comando
        `/tools:listener-recovery ...` e o roteia por canal/LLM:
          - interactive + Claude -> slash cru (run_command_in_terminal);
          - interactive + Codex  -> _build_codex_slash_executor_prompt(interactive);
          - interactive + Kimi   -> /skill:slash-executor + slash cru;
          - workspace            -> Kimi blue-arrow (kimi_blue_arrow_dispatched, T2);
          - workspace_xterm      -> _build_codex_slash_executor_prompt(workspace_xterm).

        O canal e marcado busy pelo CAMINHO EXISTENTE: o MetricsBar ja conecta
        run_command_in_terminal / run_command_in_workspace_xterm /
        kimi_blue_arrow_dispatched aos seus `_on_command_dispatched_*`, que
        chamam dot.set_busy(True) (failed->busy = "novo dispatch explicito" de
        §1.2). Por isso este handler NAO chama `_on_run_command` nem
        `_mark_as_sent`: recovery sintetico NAO e item de fila."""
        # --- Contrato (espelha o docstring de request_recovery_command) --- #
        if channel not in self._RECOVERY_VALID_CHANNELS:
            self._reject_recovery_command(
                None,
                f"Auto-recuperacao abortada: canal invalido ({channel}).",
            )
            return
        if reason not in RECOVERY_REASONS:
            self._reject_recovery_command(
                channel,
                f"Auto-recuperacao abortada: motivo invalido ({reason}) "
                f"fora de RECOVERY_REASONS.",
            )
            return
        if not context_file or not context_file.endswith(".md") or not os.path.exists(
            context_file
        ):
            self._reject_recovery_command(
                channel,
                f"Auto-recuperacao abortada: context-file invalido "
                f"({context_file}) — esperado .md existente em disco.",
            )
            return

        base = self._build_recovery_base_command(channel, reason, context_file)

        # --- Roteamento por canal/LLM --- #
        # recovery_mode=True em TODOS os caminhos nao-Claude: o executor recebe a
        # excecao de recovery EXPLICITA (igual ao Claude cru), nunca por
        # auto-deteccao fragil. Ver ai-forge/rules/listener-vermelho.md.
        if channel == "workspace":
            # T2 Parallel Worker Kimi: o paste real e a seta azul (TASK 09),
            # via kimi_blue_arrow_dispatched. O payload usa o executor universal.
            payload = self._build_kimi_slash_executor_invocation(
                base, recovery_mode=True
            )
            self._dispatch_blue_arrow(payload)
        elif channel == "workspace_xterm":
            # T3 Parallel Worker Codex.
            payload = self._build_codex_slash_executor_prompt(
                base, listener_channel="workspace_xterm", recovery_mode=True
            )
            if payload is None:
                self._reject_recovery_command(
                    channel,
                    "Auto-recuperacao abortada: comando Claude "
                    "/tools:listener-recovery nao encontrado em "
                    ".claude/commands/ para o canal Codex.",
                )
                return
            signal_bus.run_command_in_workspace_xterm.emit(payload)
        else:  # channel == "interactive" — roteia pelo Main LLM (T1)
            llm = self._resolve_interactive_main_llm()
            if llm == "codex":
                payload = self._build_codex_slash_executor_prompt(
                    base, listener_channel="interactive", recovery_mode=True
                )
                if payload is None:
                    self._reject_recovery_command(
                        channel,
                        "Auto-recuperacao abortada: comando Claude "
                        "/tools:listener-recovery nao encontrado em "
                        ".claude/commands/ para o Main LLM Codex.",
                    )
                    return
            elif llm == "kimi":
                payload = self._build_kimi_slash_executor_invocation(
                    base, recovery_mode=True
                )
            else:  # claude — slash cru, sem transformacao
                payload = base
            signal_bus.run_command_in_terminal.emit(payload)

        label_map = {
            "interactive": "Terminal 1",
            "workspace": "Terminal 2",
            "workspace_xterm": "Terminal 3",
        }
        signal_bus.toast_requested.emit(
            f"AUTO-RECUPERACAO: comando colado em "
            f"{label_map.get(channel, channel)} (motivo {reason}, "
            f"snapshot {os.path.basename(context_file)}).",
            "info",
        )

    def _on_force_kimi_toggled(self, checked: bool) -> None:
        """Main LLM Kimi preserves the old force-Kimi routing behavior."""
        self._refresh_kimi_btn_visibility()
        if checked:
            signal_bus.main_llm_changed.emit("kimi")

    def _on_use_kimi_toggled(self, checked: bool) -> None:
        """Parallel Worker Kimi keeps the legacy play-next preference toggle."""
        self._refresh_kimi_btn_visibility()

    def _on_main_codex_toggled(self, checked: bool) -> None:
        """Hook kept explicit for symmetry with Main Kimi."""
        self._refresh_kimi_btn_visibility()
        if checked:
            signal_bus.main_llm_changed.emit("codex")

    def _on_main_claude_toggled(self, checked: bool) -> None:
        """Main LLM Claude is the default raw-dispatch path (T1 interactive).

        Emits main_llm_changed so MetricsBar can phrase the red-listener
        auto-recovery prompt for Claude (uses /skill:auq-interview on the
        ask path). See ai-forge/rules/llm-routing-div.md."""
        if checked:
            signal_bus.main_llm_changed.emit("claude")

    def _on_use_codex_toggled(self, checked: bool) -> None:
        """Parallel Worker Codex: recolore o botao unico (roxo/T3) sem reload.

        Nao altera a visibilidade da seta worker (eixo Kimi), mas o provider
        efetivo de itens Codex-elegiveis muda, entao recalcula a cor de todos
        os itens (requisito visual 3)."""
        self._refresh_kimi_btn_visibility()

    def _refresh_kimi_btn_visibility(self) -> None:
        """Aplica regra de visibilidade da seta de worker per-item + recolore.

        Com Main LLM Kimi marcado, oculta o marcador worker de TODOS os itens
        (set_worker_arrow_visible(False)). Sem isso, repete a regra original:
        visivel quando whitelist Kimi OR spec.kimi_eligible. Em qualquer caso,
        set_worker_arrow_visible recolore o botao unico conforme o provider
        efetivo (resolver), refletindo tambem o toggle de Worker Codex."""
        # Fix D-3 (Position A, honra invariante 2): Main Kimi oculta as setas
        # worker SOMENTE quando o Worker Kimi esta desligado. Com Main Kimi +
        # Worker Kimi ativos, o eixo Worker e independente do Main LLM, entao a
        # seta permanece visivel e o comando kimi-elegivel roteia ao T2 (worker)
        # tanto no clique quanto no step — sem divergencia.
        force_main_kimi = self._force_kimi_chk.isChecked()
        worker_kimi_on = bool(
            getattr(self, "_use_kimi_chk", None) is not None
            and self._use_kimi_chk.isChecked()
        )
        suppress = force_main_kimi and not worker_kimi_on
        for item in self._items:
            if suppress:
                item.set_worker_arrow_visible(False)
                continue
            spec = item.get_spec()
            visible = is_kimi_compatible(spec.name) or spec.kimi_eligible
            item.set_worker_arrow_visible(visible)

    # Diretorios pesquisados para resolver existencia de uma skill quando
    # --force Kimi reescreve `/cmd` como `/skill:cmd`. Caches resolvidos uma
    # unica vez por instancia para evitar IO repetido no hot path.
    _SKILL_SEARCH_DIRS = (".claude/commands/skill", ".agents/skills")
    _CLAUDE_COMMAND_SEARCH_DIRS = (".claude/commands",)
    _CODEX_EXECUTOR_AGENT_PATH = (
        "ai-forge/MCP/agents/executor-de-slash-commands-rules.md"
    )
    _LISTENER_RULES_PATH = "ai-forge/rules/workflow-app-listeners.md"
    _KIMI_SLASH_EXECUTOR_SKILL = "slash-executor"
    # Slug normalizado (namespace, com `:`) do comando de auto-recuperacao do
    # red-listener. O dispatch de recuperacao (`_on_request_recovery_command`)
    # sinaliza recovery_mode EXPLICITAMENTE aos executores Codex/Kimi para este
    # slug — sem depender de auto-deteccao fragil pelo agente. Ver
    # ai-forge/rules/listener-vermelho.md e llm-routing-div.md §7.
    _RECOVERY_SLUG = "tools:listener-recovery"
    # Custom-prompt directives: pseudo-slash prefixes que o profile DCP injeta
    # mas que NAO sao slash-commands registrados em `.claude/commands/`. O corpo
    # do comando ja e uma instrucao em linguagem natural que nomeia um prompt em
    # `ai-forge/custom-prompts/`. Sob Main Claude o texto vai raw ao PTY; sob
    # Codex/Kimi precisamos (a) NAO abortar como comando desconhecido e (b)
    # resolver o arquivo do prompt + envolve-lo no contrato de finalizacao do
    # listener. Mapa slug -> arquivo do custom-prompt (fonte da verdade unica).
    # Ex.: `/goal rode o prompt em ai-forge/custom-prompts/goal-review-prompt.md
    # para auditar a implantacao do module {N} usando {project_json}.`
    _CUSTOM_PROMPT_DIRECTIVES = {
        "goal": "ai-forge/custom-prompts/goal-review-prompt.md",
    }
    _KIMI_WRAPPER_ONLY_MARKERS = (
        "daily-loop-autocast",
        "WF_CHANNEL_OVERRIDE=workspace",
        "After executing the bash block from the command file",
        "NUNCA processe mais de 1 item",
        "NUNCA execute o bloco bash mais de UMA vez",
    )

    @classmethod
    def _candidate_search_roots(cls) -> list[Path]:
        """Repo-root candidates independent of the process cwd."""
        roots: list[Path] = []
        seen: set[str] = set()

        def _push_root(p: Path) -> None:
            key = str(p)
            if key not in seen:
                seen.add(key)
                roots.append(p)

        for anchor in (Path.cwd(), _WORKFLOW_APP_DIR):
            resolved = anchor.resolve()
            _push_root(resolved)
            for parent in resolved.parents:
                _push_root(parent)
        return roots

    @classmethod
    def _resolve_skill_file(cls, slug: str) -> Path | None:
        """Return `{slug}.md` from any Kimi skill dir, when present.

        slug = parte apos `/skill:` e antes do primeiro espaco/argumento.
        Suporta dois formatos de disco:
          - subdir:     qa/trace.md            (.claude/commands/skill/ usa subdiretorios)
          - colon-flat: blog:competitor-spy.md  (.agents/skills/ usa ":" no nome do arquivo)
        """
        if not slug:
            return None
        rel_subdir = slug.replace(":", "/") + ".md"  # qa/trace.md
        rel_flat   = slug + ".md"                    # blog:competitor-spy.md
        for root in cls._candidate_search_roots():
            for base in cls._SKILL_SEARCH_DIRS:
                subdir_path = root / base / rel_subdir
                if os.path.exists(subdir_path):
                    return subdir_path
                if rel_flat != rel_subdir:
                    flat_path = root / base / rel_flat
                    if os.path.exists(flat_path):
                        return flat_path
        return None

    @classmethod
    def _resolve_skill_target(cls, slug: str) -> bool:
        """True quando existe arquivo `{slug}.md` em qualquer skill dir."""
        return cls._resolve_skill_file(slug) is not None

    @classmethod
    def _kimi_requires_specific_wrapper(cls, slug: str) -> bool:
        """Preserve Kimi wrappers that carry command-specific runtime behavior.

        The universal slash executor fixes false failure finalization for generic
        wrappers, but a few wrappers intentionally add channel binding, dedupe,
        or standalone autocast scripts. Those must keep the old `/skill:<slug>`
        route or the Kimi path bypasses their extra contract.
        """
        skill_file = cls._resolve_skill_file(slug)
        if skill_file is None:
            return False
        try:
            text = skill_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return any(marker in text for marker in cls._KIMI_WRAPPER_ONLY_MARKERS)

    @classmethod
    def _resolve_claude_command_file(cls, slug: str) -> Path | None:
        """Return the backing .claude command markdown for a slash slug."""
        if not slug:
            return None
        rel_subdir = slug.replace(":", "/") + ".md"
        rel_flat = slug + ".md"
        for root in cls._candidate_search_roots():
            for base in cls._CLAUDE_COMMAND_SEARCH_DIRS:
                subdir_path = root / base / rel_subdir
                if subdir_path.exists():
                    return subdir_path
                if rel_flat != rel_subdir:
                    flat_path = root / base / rel_flat
                    if flat_path.exists():
                        return flat_path
        return None

    @classmethod
    def _resolve_custom_prompt_file(cls, slug: str) -> Path | None:
        """Return the `ai-forge/custom-prompts/` file backing a custom-prompt
        directive slug (e.g. `goal`), or None when the slug is not a known
        directive / the file is missing on disk."""
        rel = cls._CUSTOM_PROMPT_DIRECTIVES.get(slug)
        if not rel:
            return None
        for root in cls._candidate_search_roots():
            candidate = root / rel
            if candidate.exists():
                return candidate
        return None

    @classmethod
    def _resolve_codex_executor_agent_file(cls) -> Path | None:
        for root in cls._candidate_search_roots():
            candidate = root / cls._CODEX_EXECUTOR_AGENT_PATH
            if candidate.exists():
                return candidate
        return None

    @classmethod
    def _resolve_listener_rules_file(cls) -> Path | None:
        for root in cls._candidate_search_roots():
            candidate = root / cls._LISTENER_RULES_PATH
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _inject_skill_prefix(cmd_text: str) -> str:
        """Insere 'skill:' apos a barra inicial do comando.

        /create-task -> /skill:create-task. Idempotente (`/skill:foo` permanece
        intacto) e preserva whitespace lider. Comandos sem `/` retornam
        inalterados — _dispatch_green_arrow os trata como prompt livre."""
        if not cmd_text:
            return cmd_text
        stripped = cmd_text.lstrip()
        if not stripped.startswith("/") or stripped.startswith("/skill:"):
            return cmd_text
        leading = cmd_text[: len(cmd_text) - len(stripped)]
        return f"{leading}/skill:{stripped[1:]}"

    @classmethod
    def _build_kimi_slash_executor_invocation(
        cls, cmd_text: str, *, recovery_mode: bool = False
    ) -> str:
        """Route Main Kimi slash commands through one hardened executor skill.

        The older path rewrote `/foo` to `/skill:foo`, which delegated to
        hundreds of generated wrappers. Some wrappers let Kimi run the literal
        Claude final block (`__exit_code=$?`), so a nonzero helper/search shell
        command could emit a false `wf-notify --status failure` before the
        eventual success. The universal executor keeps Kimi on the skill path
        while centralizing the listener finalization contract in one file.

        `recovery_mode=True` (dispatch de auto-recuperacao do red-listener para
        `/tools:listener-recovery`) injeta o flag de executor `--recovery-mode`
        ANTES do slash alvo. A skill `slash-executor` consome+strip esse flag e
        ativa o recovery_mode (rodar a FASE FINAL/`wf_verdict` do alvo) de forma
        EXPLICITA, sem depender de auto-deteccao por slug. So vale para
        `_RECOVERY_SLUG` (defesa: ignorado para qualquer outro alvo)."""
        stripped = cmd_text.lstrip()
        if not stripped.startswith("/") or stripped.startswith("/skill:"):
            return cmd_text
        leading = cmd_text[: len(cmd_text) - len(stripped)]
        flag = ""
        if recovery_mode and cls._normalized_slash_slug(stripped) == cls._RECOVERY_SLUG:
            flag = "--recovery-mode "
        return f"{leading}/skill:{cls._KIMI_SLASH_EXECUTOR_SKILL} {flag}{stripped}"

    @staticmethod
    def _command_head(cmd_text: str) -> str:
        return cmd_text.strip().split(None, 1)[0].lower() if cmd_text.strip() else ""

    @classmethod
    def _normalized_slash_slug(cls, cmd_text: str) -> str:
        """Slug normalizado (namespace) do primeiro token slash de `cmd_text`.

        `/tools:listener-recovery --x` -> `tools:listener-recovery`. A forma de
        disco com barra inicial `/tools/listener-recovery` tambem normaliza para
        `:`. A entrada DEVE comecar com `/`; caso contrario retorna "" (a forma
        de disco crua `tools/listener-recovery`, sem `/`, retorna "" — fail-safe:
        sem ativacao falsa de recovery). Usado para reconhecer o slug exato do
        recovery (defesa: recovery_mode so vale para `_RECOVERY_SLUG`)."""
        head = cls._command_head(cmd_text)
        if not head.startswith("/"):
            return ""
        return head[1:].replace("/", ":")

    # Contrato de finalizacao do listener — comum a TODO dispatch Codex
    # (slash-command executor + custom-prompt directive). Extraido para uma
    # constante unica para que ambos os builders emitam exatamente as mesmas
    # regras semanticas de wf-notify (Zero Silencio, sem dupla-fonte).
    _CODEX_LISTENER_FINALIZATION_CONTRACT = (
        "Listener finalization contract:\n"
        "- Emit exactly one final listener status for this command.\n"
        "- Decide that status from the command-level outcome, not from an "
        "incidental shell `$?` left by the last exploratory/read/check command.\n"
        "- Treat `BLOCKED`, `RESSALVAS`, rejected/reproved verdicts, missing "
        "required inputs, and failed required verification/install/action as "
        "semantic failure. These outcomes MUST notify failure/red, even when "
        "the last shell command exited 0.\n"
        "- Success is allowed only when the final report is not blocked and "
        "contains no unresolved blocker. If your final answer says `BLOCKED`, "
        "`RESSALVAS`, or equivalent, the listener status must be failure, not "
        "success.\n"
        "- On command success, notify only success. Do not run or preserve a "
        "failure path first, and do not let a previous nonzero helper command "
        "produce `wf-notify --status failure`.\n"
        "- Emit failure only for a real blocker: missing required input, "
        "BLOCKED/RESSALVAS verdict, failed verification, failed required "
        "install/action, or another command-level failure that must stop the "
        "queue.\n"
        "- Use the canonical failure reason: `BLOCKED` for blocked gates or "
        "missing required capability after execution has started, `MISSING_ARG` "
        "for missing required arguments, `RESSALVAS` for human-decision "
        "reviews, `VERIFY_FAILED` for failed/reproved verification, and "
        "`EXIT_NONZERO` for other terminal command failures.\n"
        "- If the markdown final block captures `__exit_code=$?`, treat it as "
        "a Claude-shell implementation detail. For Codex execution, run the "
        "semantically equivalent `wf-notify.sh --status success --exit-code 0` "
        "after success, or the matching failure notify after a real blocker. "
        "Never run the success branch of that block after a semantic blocker.\n\n"
    )

    # Contrato de finalizacao ESPECIFICO de recovery — substitui o generico
    # SOMENTE no dispatch de `/tools:listener-recovery` (recovery_mode). Diferente
    # do generico, aqui a `## FASE FINAL` do comando alvo (com `wf_verdict`) NAO e
    # ignorada: ela E o handshake semantico da recuperacao. Espelha o contrato do
    # comando (.claude/commands/tools/listener-recovery.md) + listener-vermelho.md.
    _CODEX_RECOVERY_FINALIZATION_CONTRACT = (
        "Recovery finalization contract (overrides the generic contract for "
        "this slug):\n"
        "- Goal: LEAVE the red listener ONLY on a real recovery. Emit exactly "
        "ONE final listener status (success XOR failure); `awaiting_user` is "
        "interim, never final.\n"
        "- RESOLVER (root cause fixed AND validated) -> success.\n"
        "- RELATORIO (report written, no fix applied) -> failure/BLOCKED. "
        "Writing a report is NOT success.\n"
        "- Verification of the applied fix failed (REPROVADO) -> "
        "failure/VERIFY_FAILED.\n"
        "- Absent required FLAG (--channel / --reason / --context-file missing) "
        "or a --channel/--reason value out of enum -> failure/MISSING_ARG.\n"
        "- A PRESENT but empty / nonexistent / non-`.md` --context-file, a reason "
        "out of RECOVERY_REASONS, or an infra/auth/rate-limit cause -> "
        "failure/BLOCKED (blind recovery forbidden / not recoverable here).\n"
        "- PERGUNTAR: emit the blue `awaiting_user` signal ONCE, immediately "
        "followed by a real, specific question; await the answer; then emit "
        "exactly one final success/failure. With no human present (afk/yolo), "
        "degrade to RELATORIO -> failure/BLOCKED, never success.\n"
        "- Failure wins: a later success cannot erase a real failure for the "
        "same run.\n"
        "- Run the command's `## FASE FINAL` block (it reads `wf_verdict`) or "
        "the semantically equivalent wf-notify for the verdict you reached. "
        "Never emit success when the verdict is BLOCKED/RESSALVAS/REPROVADO/"
        "MISSING_ARG.\n\n"
    )

    @classmethod
    def _build_codex_custom_prompt_prompt(
        cls,
        cmd_text: str,
        *,
        listener_channel: str | None = None,
    ) -> str | None:
        """Build the Codex prompt for a custom-prompt directive (e.g. `/goal`).

        Diferente de `_build_codex_slash_executor_prompt`, NAO resolve um
        markdown em `.claude/commands/` — o corpo do comando ja e a instrucao em
        linguagem natural e nomeia um arquivo em `ai-forge/custom-prompts/`. O
        Codex le esse arquivo, segue o roteiro e finaliza o listener pelo MESMO
        contrato dos demais dispatches. Retorna None quando o slug nao e uma
        diretiva conhecida ou o arquivo do prompt nao existe (Zero Silencio: o
        caller aborta com toast)."""
        stripped = cmd_text.strip()
        if not stripped or not stripped.startswith("/"):
            return cmd_text
        head, _, instruction = stripped.partition(" ")
        slug = head[1:]
        prompt_file = cls._resolve_custom_prompt_file(slug)
        if prompt_file is None:
            return None
        agent_file = cls._resolve_codex_executor_agent_file()
        agent_ref = (
            str(agent_file)
            if agent_file is not None
            else cls._CODEX_EXECUTOR_AGENT_PATH
        )
        listener_file = cls._resolve_listener_rules_file()
        listener_ref = (
            str(listener_file)
            if listener_file is not None
            else cls._LISTENER_RULES_PATH
        )
        channel = listener_channel or "interactive"
        return (
            "Execute the SystemForge custom-prompt directive below with maximum "
            "fidelity. This is NOT a registered slash command — it is a "
            "pseudo-slash prefix whose body is a natural-language instruction "
            "that names the prompt file to follow.\n\n"
            f"Executor rules: {agent_ref}\n"
            f"Listener rules: {listener_ref}\n"
            f"Expected listener channel: {channel}\n"
            f"Instruction: {instruction.strip() or '(none)'}\n"
            f"Custom prompt file: {prompt_file}\n\n"
            + cls._CODEX_LISTENER_FINALIZATION_CONTRACT
            + "Protocol:\n"
            "1. Read the executor rules file first.\n"
            "2. Read the listener rules file before running any finalization "
            "block.\n"
            "3. Read the custom prompt file exactly as the source of truth and "
            "follow its roteiro de execucao step by step.\n"
            "4. The custom prompt expects template literals (e.g. `{module}` and "
            "`{project_json}`) — resolve them from the Instruction above (it "
            "already carries the rendered module id and project json path).\n"
            "5. Resolve project variables from .claude/project.json and "
            ".codex/codex-project.json when present.\n"
            "6. The custom prompt has no `## FASE FINAL`/wf-notify block of its "
            f"own — emit the single final listener status for channel `{channel}` "
            "per the contract above. Do not prefix the pasted text with "
            "WF_CHANNEL_OVERRIDE and do not hardcode a different channel.\n"
            "7. If a required variable, file, or capability is missing, emit "
            "exactly one failure notify (reason BLOCKED or MISSING_ARG) before "
            "the final response, then stop with BLOCKED and list the missing "
            "inputs. Do not emit success for this case.\n"
            "8. Do the work; do not summarize the prompt instead of executing it."
        )

    @classmethod
    def _build_codex_slash_executor_prompt(
        cls,
        cmd_text: str,
        *,
        listener_channel: str | None = None,
        recovery_mode: bool = False,
    ) -> str | None:
        """Build the prompt that asks Codex to execute a Claude slash command.

        `recovery_mode=True` (set pelo dispatch de auto-recuperacao do
        red-listener para `/tools:listener-recovery`) troca o contrato de
        finalizacao GENERICO pelo ESPECIFICO de recovery e injeta um protocolo
        explicito: a regra generica "ignore a `## FASE FINAL` do alvo" e
        SUSPENSA para este slug; o agente roda a state machine de recuperacao
        (RESOLVER/RELATORIO/PERGUNTAR) e o `wf_verdict` da FASE FINAL. Assim o
        Codex tem o MESMO equivalente do Claude (que roda o comando cru), sem
        depender de auto-deteccao fragil pelas regras. Ver
        ai-forge/rules/listener-vermelho.md."""
        stripped = cmd_text.strip()
        if not stripped or not stripped.startswith("/"):
            return cmd_text
        head, _, args = stripped.partition(" ")
        slug = head[1:]
        command_file = cls._resolve_claude_command_file(slug)
        if command_file is None:
            return None
        agent_file = cls._resolve_codex_executor_agent_file()
        agent_ref = (
            str(agent_file)
            if agent_file is not None
            else cls._CODEX_EXECUTOR_AGENT_PATH
        )
        listener_file = cls._resolve_listener_rules_file()
        listener_ref = (
            str(listener_file)
            if listener_file is not None
            else cls._LISTENER_RULES_PATH
        )
        channel = listener_channel or "interactive"
        # recovery_mode so vale para o slug EXATO (defesa: nunca ativa a excecao
        # de executor para outro comando alvo). Usa o MESMO normalizador do
        # builder Kimi (`_normalized_slash_slug`: case-insensitive + tolerante a
        # whitespace) para que Codex e Kimi tenham defesa identica — sem
        # divergencia latente (ex.: `/Tools:Listener-Recovery`).
        is_recovery = (
            recovery_mode
            and cls._normalized_slash_slug(stripped) == cls._RECOVERY_SLUG
        )
        if is_recovery:
            return (
                "Use the SystemForge slash-command executor rules and execute "
                "the Claude command below in RECOVERY MODE (the strict executor "
                "exception for `tools:listener-recovery`, Passo 3.5).\n\n"
                f"Executor rules: {agent_ref}\n"
                f"Listener rules: {listener_ref}\n"
                f"Expected listener channel: {channel}\n"
                "Recovery mode: enabled by caller\n"
                f"Command: {stripped}\n"
                f"Command markdown: {command_file}\n"
                f"Arguments: {args.strip() or '(none)'}\n\n"
                + cls._CODEX_RECOVERY_FINALIZATION_CONTRACT
                + "Protocol:\n"
                "1. Read the executor rules file first (note Passo 3.5 "
                "recovery_mode — the strict exception for this slug).\n"
                "2. Read the listener rules file before running any finalization "
                "block.\n"
                "3. Read the command markdown file exactly as the source of "
                "truth and follow its FASE 1..FASE FINAL recovery state machine.\n"
                "4. Read `--context-file` FIRST: it is a Markdown (.md) "
                "diagnostic snapshot, NOT JSON; never parse it as JSON nor "
                "require JSON fields. Failure mapping matches the command (FASE "
                "1): if the `--context-file` FLAG is absent -> failure/MISSING_ARG; "
                "if the flag is present but the file is empty, nonexistent, or "
                "does not end in `.md` -> failure/BLOCKED (blind recovery is "
                "forbidden). Then stop.\n"
                "5. Resolve project variables from .claude/project.json and "
                ".codex/codex-project.json when present.\n"
                "6. RECOVERY EXCEPTION: the generic 'ignore the target "
                "`## FASE FINAL` / wf-notify block' rule is SUSPENDED for this "
                "command. You MUST run this command's recovery state machine and "
                f"emit the single final listener status for channel `{channel}` "
                "per its `wf_verdict` mapping. The channel comes from the PTY env "
                "(WF_CHANNEL_OVERRIDE); do not paste/prefix it and do not hardcode "
                "a different channel.\n"
                "7. Do the work; do not summarize the command instead of "
                "executing it."
            )
        return (
            "Use the SystemForge slash-command executor rules and execute the "
            "Claude command below with maximum fidelity.\n\n"
            f"Executor rules: {agent_ref}\n"
            f"Listener rules: {listener_ref}\n"
            f"Expected listener channel: {channel}\n"
            f"Command: {stripped}\n"
            f"Command markdown: {command_file}\n"
            f"Arguments: {args.strip() or '(none)'}\n\n"
            + cls._CODEX_LISTENER_FINALIZATION_CONTRACT
            + "Protocol:\n"
            "1. Read the executor rules file first.\n"
            "2. Read the listener rules file before running any finalization block.\n"
            "3. Read the command markdown file exactly as the source of truth.\n"
            "4. Parse frontmatter as execution metadata, then execute the markdown body.\n"
            "5. Resolve project variables from .claude/project.json and "
            ".codex/codex-project.json when present.\n"
            "6. Respect the listener contract: if the command has a "
            "`## FASE FINAL`, autocast, or wf-notify block, execute/preserve it "
            f"so it notifies channel `{channel}` via the PTY environment. Do not "
            "prefix the pasted command with WF_CHANNEL_OVERRIDE and do not hardcode "
            "a different channel.\n"
            "7. If a required variable, file, or MCP-only capability is missing, "
            "emit exactly one failure notify with reason BLOCKED or MISSING_ARG "
            "before the final response, then stop with BLOCKED and list the missing "
            "inputs. Do not emit success for this case.\n"
            "8. Before your final response, verify the invariant: a response that "
            "contains BLOCKED/RESSALVAS/reproved/failure has already emitted "
            "failure/red, and a response that emitted success contains no blocker.\n"
            "9. Do the work; do not summarize the command instead of executing it."
        )

    @classmethod
    def render_for_llm(
        cls,
        text: str,
        llm: str,
        *,
        listener_channel: str = "interactive",
        mode: str = "insert",
    ) -> RenderedInsertion:
        """Renderiza um payload para o LLM de destino, SEM efeito colateral.

        Funcao PURA: nao chama `_on_run_command`, `_dispatch_*`, `emit` de PTY nem
        toast; so retorna `RenderedInsertion`. Levanta a arvore de decisao dos
        dispatchers de fila (`_dispatch_kimi_main_command`/`_dispatch_codex_command`)
        para que insercoes (paste/no-Enter no `main_window`) compartilhem a MESMA
        adaptacao de publicacao por Main LLM. Contrato/invariantes:
        blacksmith/brainstorm-mcp/06-15-insertions-subtab-llm-routing.md §6/§8.1.

        `llm`: "claude" | "codex" | "kimi" (LLM efetivo do terminal de destino).
        `mode`: "insert" (insercao, nunca pulsa) | "dispatch" (fila, pode pulsar).
        """
        head = cls._command_head(text)

        # /model, /effort: diretivas Claude-only (D8).
        if head.startswith("/model") or head.startswith("/effort"):
            if llm == "claude":
                return RenderedInsertion(text=text, listener_channel=listener_channel)
            if mode == "dispatch":
                # A fila pulsa o listener (amarelo->verde) sem escrever no PTY.
                return RenderedInsertion(
                    text=None, helper_pulse=True, listener_channel=listener_channel
                )
            # Insercao: sem ciclo de listener para pulsar -> abort (Zero Silencio).
            return RenderedInsertion(
                text=None,
                abort_reason=(
                    "diretiva /model//effort nao e insercao valida fora de Claude"
                ),
                listener_channel=listener_channel,
            )

        # /clear: raw para os tres LLM (todos entendem).
        if head == "/clear":
            return RenderedInsertion(text=text, listener_channel=listener_channel)

        # Claude: publica o comando raw sempre (o REPL resolve). Sem checagem de existencia.
        if llm == "claude":
            return RenderedInsertion(text=text, listener_channel=listener_channel)

        # Texto livre / path / persona (nao-slash): passthrough para qualquer LLM.
        if not head.startswith("/"):
            return RenderedInsertion(text=text, listener_channel=listener_channel)

        slug = head[1:]

        if llm == "kimi":
            if head.startswith("/skill:"):
                # Kimi entende /skill: nativamente -> raw.
                return RenderedInsertion(text=text, listener_channel=listener_channel)
            if slug in cls._CUSTOM_PROMPT_DIRECTIVES:
                if cls._resolve_custom_prompt_file(slug) is None:
                    return RenderedInsertion(
                        text=None,
                        abort_reason=(
                            f"custom-prompt '{slug}' nao encontrado em "
                            "ai-forge/custom-prompts/"
                        ),
                    )
                return RenderedInsertion(
                    text=cls._build_kimi_slash_executor_invocation(text),
                    listener_channel=listener_channel,
                )
            has_command = cls._resolve_claude_command_file(slug) is not None
            has_skill = cls._resolve_skill_target(slug)
            if slug and not has_command and not has_skill:
                return RenderedInsertion(
                    text=None,
                    abort_reason=(
                        f"comando/skill '{slug}' nao encontrado em "
                        ".claude/commands/ ou .agents/skills/"
                    ),
                )
            if slug and (not has_command or cls._kimi_requires_specific_wrapper(slug)):
                return RenderedInsertion(
                    text=cls._inject_skill_prefix(text),
                    listener_channel=listener_channel,
                )
            return RenderedInsertion(
                text=cls._build_kimi_slash_executor_invocation(
                    text,
                    recovery_mode=(
                        cls._normalized_slash_slug(text) == cls._RECOVERY_SLUG
                    ),
                ),
                listener_channel=listener_channel,
            )

        if llm == "codex":
            if head.startswith("/skill:"):
                # D7: sem fonte canonica para adaptar /skill: ao Codex -> abort.
                return RenderedInsertion(
                    text=None,
                    abort_reason="/skill: nao tem fonte para adaptar ao Codex",
                )
            if slug in cls._CUSTOM_PROMPT_DIRECTIVES:
                transformed = cls._build_codex_custom_prompt_prompt(
                    text, listener_channel=listener_channel
                )
                if transformed is None:
                    return RenderedInsertion(
                        text=None,
                        abort_reason=(
                            f"custom-prompt '{slug}' nao encontrado em "
                            "ai-forge/custom-prompts/"
                        ),
                    )
                return RenderedInsertion(
                    text=transformed, listener_channel=listener_channel
                )
            transformed = cls._build_codex_slash_executor_prompt(
                text,
                listener_channel=listener_channel,
                recovery_mode=(
                    cls._normalized_slash_slug(text) == cls._RECOVERY_SLUG
                ),
            )
            if transformed is None:
                return RenderedInsertion(
                    text=None,
                    abort_reason=(
                        f"comando Claude '{slug}' nao encontrado em .claude/commands/"
                    ),
                )
            return RenderedInsertion(text=transformed, listener_channel=listener_channel)

        # LLM desconhecido: defensivo -> raw (igual Claude).
        return RenderedInsertion(text=text, listener_channel=listener_channel)

    def _dispatch_codex_command(self, cmd_text: str, *, to_t1: bool = False) -> bool:
        """Dispatch a command to Codex. Returns False when validation aborts."""
        emit = (
            signal_bus.run_command_in_terminal.emit
            if to_t1
            else signal_bus.run_command_in_workspace_xterm.emit
        )
        head = self._command_head(cmd_text)
        if head.startswith("/model") or head.startswith("/effort"):
            # Claude-specific directives: NOT sent to Codex (would error), but
            # the listener still pulses yellow→green so the autocast loop
            # advances exactly as it does under Claude. Channel matches the
            # terminal Codex actually runs in (T1 when to_t1, else T3 xterm).
            signal_bus.listener_helper_pulse.emit(
                "interactive" if to_t1 else "workspace_xterm"
            )
            return True
        # task 006 — condicao de falha 4 (terminal alvo nao pronto -> abortar
        # com feedback visivel). Vale apenas para o destino Worker Codex (T3,
        # to_t1=False); o caminho Main Codex (to_t1=True) publica no T1
        # interactive, que existe sempre. Diretivas /model|/effort retornam
        # acima (so pulsam o listener, nao publicam), logo nao passam por aqui.
        if not to_t1 and not self._codex_t3_available:
            signal_bus.toast_requested.emit(
                "Worker Codex (T3): terminal-codex-output nao esta pronto — "
                "dispatch abortado.",
                "warning",
            )
            return False
        if head == "/clear":
            emit(cmd_text)
            self._on_run_command(cmd_text)
            return True
        channel = "interactive" if to_t1 else "workspace_xterm"
        slug = head[1:]
        if slug in self._CUSTOM_PROMPT_DIRECTIVES:
            # Custom-prompt directive (ex.: /goal): nao existe em
            # .claude/commands/. Resolve o arquivo do custom-prompt e envolve a
            # instrucao no contrato de listener. NAO tratar como slash-command.
            transformed = self._build_codex_custom_prompt_prompt(
                cmd_text, listener_channel=channel
            )
            if transformed is None:
                signal_bus.toast_requested.emit(
                    f"Main LLM Codex: custom-prompt '{slug}' nao encontrado em "
                    "ai-forge/custom-prompts/ — dispatch abortado.",
                    "warning",
                )
                return False
        elif head.startswith("/"):
            # Defesa-em-profundidade: se o slug de recovery chegar como item
            # NORMAL de fila (nao o dispatch sintetico de `_on_request_recovery_
            # command`), ele tambem ganha recovery_mode=True — nunca o contrato
            # generico (que conflita com a FASE FINAL/`wf_verdict` do recovery).
            transformed = self._build_codex_slash_executor_prompt(
                cmd_text,
                listener_channel=channel,
                recovery_mode=(
                    self._normalized_slash_slug(cmd_text) == self._RECOVERY_SLUG
                ),
            )
            if transformed is None:
                signal_bus.toast_requested.emit(
                    f"Main LLM Codex: comando Claude '{slug}' nao encontrado em "
                    ".claude/commands/ — dispatch abortado.",
                    "warning",
                )
                return False
        else:
            transformed = cmd_text
        # task 006 — condicao de falha 3 (adaptacao Codex retorna texto vazio ->
        # abortar). `_build_codex_slash_executor_prompt` nunca devolve vazio para
        # um slash resolvivel (None quando o comando some), mas este guard fecha
        # o invariante 10 (falha nunca publica texto parcial) tambem para o
        # caminho non-slash, garantindo Zero Silencio antes de qualquer emit.
        if not transformed or not transformed.strip():
            signal_bus.toast_requested.emit(
                "Worker Codex: adaptacao retornou texto vazio — dispatch abortado.",
                "warning",
            )
            return False
        emit(transformed)
        self._on_run_command(cmd_text)
        return True

    def _dispatch_kimi_main_command(self, cmd_text: str) -> bool:
        """Dispatch through the Main LLM Kimi path. Returns False on abort."""
        head = self._command_head(cmd_text)
        if head.startswith("/model") or head.startswith("/effort"):
            # Claude-specific directives: NOT sent to Kimi (would error), but
            # the listener still pulses yellow→green so the autocast loop
            # advances exactly as it does under Claude. Main Kimi runs in T1.
            signal_bus.listener_helper_pulse.emit("interactive")
            return True
        if head == "/clear":
            signal_bus.run_command_in_terminal.emit(cmd_text)
            self._on_run_command(cmd_text)
            return True
        if head.startswith("/skill:"):
            signal_bus.run_command_in_terminal.emit(cmd_text)
            self._on_run_command(cmd_text)
            return True
        if head.startswith("/"):
            slug = head[1:].split()[0] if head else ""
            if slug in self._CUSTOM_PROMPT_DIRECTIVES:
                # Custom-prompt directive (ex.: /goal): nao existe em
                # .claude/commands/ nem como skill. Roteia pelo executor
                # universal (`/skill:slash-executor /goal ...`), que resolve o
                # arquivo em ai-forge/custom-prompts/ e preserva o contrato de
                # listener. Nunca abortar como comando desconhecido.
                if self._resolve_custom_prompt_file(slug) is None:
                    signal_bus.toast_requested.emit(
                        f"Main LLM Kimi: custom-prompt '{slug}' nao encontrado "
                        "em ai-forge/custom-prompts/ — dispatch abortado.",
                        "warning",
                    )
                    return False
                transformed = self._build_kimi_slash_executor_invocation(cmd_text)
            else:
                has_command = self._resolve_claude_command_file(slug) is not None
                has_skill = self._resolve_skill_target(slug)
                if slug and not has_command and not has_skill:
                    signal_bus.toast_requested.emit(
                        f"Main LLM Kimi: comando/skill '{slug}' nao encontrado em "
                        ".claude/commands/ ou .agents/skills/ — dispatch abortado.",
                        "warning",
                    )
                    return False
                if slug and (
                    not has_command or self._kimi_requires_specific_wrapper(slug)
                ):
                    transformed = self._inject_skill_prefix(cmd_text)
                else:
                    # Defesa-em-profundidade: o slug de recovery como item NORMAL
                    # de fila tambem recebe recovery_mode (flag --recovery-mode),
                    # nunca o wrapper generico que conflita com sua FASE FINAL.
                    transformed = self._build_kimi_slash_executor_invocation(
                        cmd_text,
                        recovery_mode=(
                            self._normalized_slash_slug(cmd_text)
                            == self._RECOVERY_SLUG
                        ),
                    )
        else:
            transformed = cmd_text
        signal_bus.run_command_in_terminal.emit(transformed)
        self._on_run_command(cmd_text)
        return True

    def _dispatch_green_arrow(self, cmd_text: str) -> bool:
        """Handler unico para `item.run_in_terminal_requested` (provider efetivo
        Claude/T1). Retorna True quando publicou de fato (fix D-1: o slot
        `_on_single_button_green_dispatch` so marca enviado em True).

        `/clear` (fix D-2): tratado PRIMEIRO, independente do Main LLM — vai raw
        para o T1 (Claude, Codex e Kimi entendem `/clear` inalterado) e espelha
        para os workers ativos com o gate de prontidao do T3 (via
        `_mirror_clear_to_workspace_if_kimi_checked`, fix D-7). Antes, sob Main
        Codex, `/clear` era embrulhado por `_dispatch_codex_command` e nunca
        espelhava aos workers.

        Default path (force-kimi off): emite para terminal interactive e
        atualiza label/highlight com o cmd_text original.

        Main LLM Codex/Kimi: roteia para `_dispatch_codex_command(to_t1=True)` /
        `_dispatch_kimi_main_command`; comandos sem `.md`/skill existente
        disparam toast e abortam (retornam False) — o item permanece pendente."""
        head = ""
        if cmd_text and cmd_text.strip():
            head = cmd_text.strip().split(None, 1)[0].lower()

        # Regra de capacidade exclusiva (image-gen): o caminho verde e Claude/T1.
        # Um comando que CRIA imagem NUNCA pode rodar fora do Worker Codex — so o
        # Codex gera pixel. Recusa aqui (Zero Silencio) em vez de colar no Claude.
        if is_image_generation_command(cmd_text):
            signal_bus.toast_requested.emit(
                f"{head}: geracao de imagem so roda no Worker Codex (T3) — so o"
                " Codex gera imagem. Ative o Worker Codex e tente de novo.",
                "warning",
            )
            return False

        # Fix D-2: /clear primeiro, antes de qualquer branch de Main LLM.
        if head == "/clear":
            signal_bus.run_command_in_terminal.emit(cmd_text)
            self._on_run_command(cmd_text)
            self._mirror_clear_to_workspace_if_kimi_checked(cmd_text)
            return True

        if getattr(self, "_main_codex_radio", None) and self._main_codex_radio.isChecked():
            return self._dispatch_codex_command(cmd_text, to_t1=True)

        if not getattr(self, "_force_kimi_chk", None) or not self._force_kimi_chk.isChecked():
            signal_bus.run_command_in_terminal.emit(cmd_text)
            self._on_run_command(cmd_text)
            return True
        return self._dispatch_kimi_main_command(cmd_text)

    def _on_single_button_green_dispatch(
        self, item: CommandItemWidget, cmd_text: str
    ) -> None:
        """Slot do botao unico (verde/Claude-T1). Marca enviado SO quando
        `_dispatch_green_arrow` publica de fato (fix D-1). Espelha
        `_on_single_button_codex_dispatch`: sob Main Codex/Kimi o dispatch pode
        abortar (`.md`/skill ausente) — nesse caso o item fica pendente e o toast
        do dispatcher e o feedback (Zero Silencio)."""
        if self._dispatch_green_arrow(cmd_text):
            item._mark_as_sent()

    def _on_single_button_local_action_dispatch(
        self, item: CommandItemWidget, spec: "CommandSpec"
    ) -> None:
        """Slot do botao unico para um item `kind=="local-action"` (fix D-5).

        Roda a action registrada in-process (mesma `dispatch_local_action` do
        `pipeline_manager`), NUNCA cola no T1 (invariante 8). Marca enviado em
        sucesso; em id ausente/desconhecido emite toast e mantem pendente."""
        from workflow_app.command_queue.local_actions import (
            dispatch_local_action,
            get_local_action,
        )

        action_id = getattr(spec, "local_action_id", None)
        if not action_id or get_local_action(action_id) is None:
            signal_bus.toast_requested.emit(
                f"local-action desconhecida ou sem id: {action_id!r} — nada executado.",
                "warning",
            )
            return
        if dispatch_local_action(action_id, spec):
            item._mark_as_sent()
        else:
            signal_bus.toast_requested.emit(
                f"local-action {action_id!r} falhou (retornou False).",
                "warning",
            )

    def _on_kimi_adaptation_failed(self, cmd_text: str) -> None:
        """Slot do `item.kimi_adaptation_failed` (fix D-6): toast visivel quando
        `adapt_to_kimi` levanta ValueError. Sem isto, o clique Kimi falhava em
        silencio e o item ficava pendente sem feedback (Zero Silencio)."""
        signal_bus.toast_requested.emit(
            f"Adaptacao Kimi falhou para '{cmd_text}' — comando nao despachado.",
            "warning",
        )

    def _mirror_clear_to_workspace_if_kimi_checked(self, cmd_text: str) -> None:
        """When /clear is dispatched to interactive AND a worker is checked,
        also emit it to the worker terminal so both CLI sessions clear their
        context simultaneously, AND set the after-clear flag so the next
        blue-arrow Kimi dispatch uses the extended 3s delay (Kimi's TUI repaint
        after a clear is slower than normal).

        Chamado pela branch `/clear`-first de `_dispatch_green_arrow` (fix D-2),
        para TODO Main LLM. O "Rodar próximo" (step) tem seu proprio `clear_both`
        equivalente. **Sem guarda de Main LLM** (fix da ressalva D-2/D-7): o
        espelhamento ao worker e independente do Main LLM (invariante 2) — sob
        Main Kimi com Worker Kimi/Codex ativo, `/clear` deve espelhar ao T2/T3
        igual ao step. O T1 ja recebeu `/clear` raw na branch chamadora.
        """
        if not cmd_text or not cmd_text.strip():
            return
        head = cmd_text.strip().split(None, 1)[0].lower()
        if head == "/clear" and self._use_kimi_chk.isChecked():
            signal_bus.run_command_in_workspace_terminal.emit(cmd_text)
            self._last_workspace_dispatch_was_clear = True
        if head == "/clear" and getattr(self, "_use_codex_chk", None) and self._use_codex_chk.isChecked():
            # Fix D-7: mesmo gate de prontidao do T3 que o step path
            # (`clear_both`) — sem ele, o /clear ia para um xterm Codex
            # possivelmente inexistente em silencio. T3 indisponivel -> toast.
            if self._codex_t3_available:
                signal_bus.run_command_in_workspace_xterm.emit(cmd_text)
            else:
                signal_bus.toast_requested.emit(
                    "Worker Codex (T3): terminal-codex-output nao esta pronto"
                    " — /clear nao espelhado.",
                    "warning",
                )

    # ──────────────────────────────────────── Quick-save helpers ─────── #

    def _maybe_auto_save(self, changed_text: str) -> None:
        """Auto-trigger save_requested when label content changes,
        unless the content is /model or /clear."""
        if not changed_text:
            return
        first_line = changed_text.strip().split("\n")[0].strip().lower()
        _skip = ("/model", "/clear")
        if any(first_line.startswith(s) for s in _skip) or first_line == "/clear":
            return
        self.save_requested.emit()

    def get_template_label_text(self) -> str:
        """Return the current template label value (strip 'Last template: '
        prefix + leading icon/space). Devolve string vazia quando o valor
        e o placeholder '—'."""
        text = self._template_label.text().strip()
        if text.startswith(_TemplateLabel._PREFIX):
            text = text[len(_TemplateLabel._PREFIX):].strip()
        if text == _TemplateLabel._PLACEHOLDER:
            return ""
        for prefix in ("📋", "🔎"):
            if prefix in text:
                text = text.split(prefix, 1)[-1].strip()
        return text

    def get_last_command_text(self) -> str:
        """Return the current last-command full text (cmd + args)."""
        return self._last_cmd_full.strip()

    def _on_copy_rendered_commands(self) -> None:
        """Copia todos os comandos renderizados em queue-command-list para o
        clipboard, um por linha, na ordem visual atual (inclui /clear, /model,
        /effort e demais directivas — reflete exatamente o que esta na tela)."""
        lines: list[str] = []
        for item in self._items:
            spec = item.get_spec()
            name = (spec.name or "").strip()
            if name:
                lines.append(name)
        QApplication.clipboard().setText("\n".join(lines))

    def find_last_valid_command(self) -> str:
        """Walk the queue backwards from the last executed item to find
        a command that is not /model or /clear."""
        _skip = ("/model", "/clear")
        for item in reversed(self._items):
            if not item.is_pending_run():
                name = item.get_spec().name.strip()
                name_lower = name.lower()
                if not any(name_lower.startswith(s) for s in _skip):
                    return name
        return ""

    # ──────────────────────────────────────── Queue state persistence ─ #

    def get_queue_snapshot(self) -> list[dict]:
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

    def restore_queue_snapshot(self, state: list[dict]) -> None:
        """Restore queue from a saved state list, preserving statuses and sent flags.

        Loop 06-09 (brecha 3 — filas auto-salvas pre-fix): snapshots gravados
        antes do fix 06-08 carregam comandos per-task sintetizados por contagem
        (tasks fantasma, ex. `TASK-4.md` inexistente) ou placeholder literal
        `TASK-{k}` nunca renderizado. Entradas ainda PENDENTES (nao enviadas)
        passam pela mesma validacao pura de `flow_validation` usada no load do
        SPECIFIC-FLOW.json antes de voltar a fila; entradas ja executadas sao
        historico e restauram verbatim. Drops sao SEMPRE visiveis (Zero
        Silencio): toast resumido + reason completo no log. `load_pipeline`
        renumera positions 1-based, entao dropar nao quebra a remocao por
        position.
        """
        from workflow_app.dcp.flow_validation import validate_flow_commands
        from workflow_app.domain import CommandStatus, InteractionType, ModelName

        project_dir = None
        try:
            from workflow_app.config.app_state import app_state

            if app_state.has_config and app_state.config is not None:
                project_dir = getattr(app_state.config, "project_dir", None)
        except Exception:  # noqa: BLE001 - contexto opcional; sem ele a
            project_dir = None  # validacao fica fail-open p/ refs relativas

        specs = []
        statuses: list[CommandStatus] = []
        sent_flags: list[bool] = []
        dropped: list = []

        for entry in state:
            try:
                model = ModelName(entry.get("model", "Sonnet"))
            except ValueError:
                model = ModelName.SONNET
            try:
                interaction = InteractionType(entry.get("interaction_type", "auto"))
            except ValueError:
                interaction = InteractionType.AUTO
            try:
                status = CommandStatus(entry.get("status", "pendente"))
            except ValueError:
                status = CommandStatus.PENDENTE
            sent = bool(entry.get("sent", False))

            # So valida o que ainda VAI rodar; um item executado com ref hoje
            # ausente e registro historico, nao um dispatch futuro. Modo
            # task-only: snapshots cobrem filas arbitrarias onde `{slug}` em
            # texto-livre e legitimo (resolvido pelo LLM receptor) — so a
            # assinatura `TASK-{k}` do stub do gerador derruba.
            if status == CommandStatus.PENDENTE and not sent:
                vres = validate_flow_commands(
                    [{"name": entry.get("name", "")}],
                    cm_id="",
                    project_dir=project_dir,
                    placeholder_mode="task-only",
                )
                if vres.dropped:
                    dropped.extend(vres.dropped)
                    continue

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
            statuses.append(status)
            sent_flags.append(sent)

        if dropped:
            for d in dropped:
                logger.warning(
                    "[restore] comando descartado no snapshot restaurado: %r — %s",
                    d.name, d.reason,
                )
            shown = "; ".join(d.name for d in dropped[:5])
            extra = (
                f" (+{len(dropped) - 5} no log)" if len(dropped) > 5 else ""
            )
            signal_bus.toast_requested.emit(
                f"Snapshot restaurado: {len(dropped)} comando(s) pendente(s) "
                f"invalido(s) descartado(s) — {shown}{extra}. Motivos no log. "
                f"Fila salva pre-fix 06-08: regenere via "
                f"[DCP: Build Module Pipeline].",
                "warning",
            )

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

    def _on_command_completed(self, index: int, success: bool = True) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.CONCLUIDO)
            self._emit_progress_metrics()

    def _on_command_failed(self, index: int, _msg: str) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.ERRO)
            self._emit_progress_metrics()

    def _on_command_skipped(self, index: int) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.PULADO)
            self._emit_progress_metrics()

    def _on_remove_requested(self, position: int) -> None:
        item = self._item_at(position)
        if item:
            removed_name = item.get_spec().name
            self._items_layout.removeWidget(item)
            item.deleteLater()
            self._items = [i for i in self._items if i.get_spec().position != position]
            if not self._items:
                self._empty_widget.setVisible(True)
                self._list_widget.setVisible(False)
            self._emit_progress_metrics()
            # Onda 4: when the queue is backed by a SPECIFIC-FLOW.json (DCP
            # context, set by _on_dcp_specific_flow_clicked), persist the
            # deletion to overrides.skipped[] so the next reload (or regen
            # without --reset-overrides) honors it. Without this, the user
            # has to re-delete the same broken commands every time they
            # click [DCP: Specific-Flow].
            self._persist_dcp_skip(removed_name)

    def _persist_dcp_skip(self, command_name: str) -> None:
        """Append `command_name` to overrides.skipped[] of the current DCP flow.

        No-op when the queue isn't sourced from a SPECIFIC-FLOW.json (legacy
        templates, ad-hoc pipelines). Failure to persist is surfaced as a
        warning toast but does NOT undo the in-memory deletion — the user
        already saw the item disappear from the queue, restoring it would
        be more confusing than a non-fatal warning.
        """
        flow_path = self._current_dcp_flow_path
        if flow_path is None or not command_name:
            return
        if not flow_path.exists():
            logger.warning(
                "[DCP] persist skip: flow path %s nao existe; override descartado",
                flow_path,
            )
            return
        try:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            signal_bus.toast_requested.emit(
                f"DCP: falha ao ler SPECIFIC-FLOW.json para persistir override: {exc}",
                "warning",
            )
            return
        if not isinstance(data, dict):
            return
        overrides = data.get("overrides")
        if not isinstance(overrides, dict):
            overrides = {}
            data["overrides"] = overrides
        skipped = overrides.get("skipped")
        if not isinstance(skipped, list):
            skipped = []
            overrides["skipped"] = skipped
        if command_name in skipped:
            return
        skipped.append(command_name)
        try:
            flow_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            logger.info(
                "[DCP] persisted skip %r in %s (total skipped=%d)",
                command_name, flow_path.name, len(skipped),
            )
        except OSError as exc:
            signal_bus.toast_requested.emit(
                f"DCP: falha ao gravar override em {flow_path.name}: {exc}",
                "warning",
            )

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

    # ───────────────────────────────────── Queue dispatch ──────────── #

    def _on_instance_selected(self, name: str) -> None:
        """Track the active CLI binary for downstream routing."""
        self._cli_binary = name

    def _find_next_pending(self) -> CommandItemWidget | None:
        """Find the first item not yet sent to terminal."""
        for item in self._items:
            if item.is_pending_run():
                return item
        return None

    def _on_step_btn_clicked(self) -> None:
        """Run the next pending item once and stop. Manual step-by-step.

        Dispatches EVERY pending item to the terminal — including queue
        helpers (/clear, /model X, /effort Y). The dispatcher uses
        run_command_in_terminal (Claude) or run_command_in_workspace_terminal
        (Kimi), pasting into the already-open CLI session. So /clear actually
        clears context and /model/effort actually switch the session's
        model/effort. Skipping helpers here would silently break model/effort
        transitions.
        """
        next_item = self._find_next_pending()
        if next_item is None:
            signal_bus.toast_requested.emit(
                "Fila vazia — nenhum item pendente para executar.",
                "info",
            )
            return

        spec = next_item.get_spec()

        # Fix D-5: local-action NUNCA vai a um terminal (invariante 8). No step
        # manual roda in-process (mesma semantica do autocast/pipeline_manager),
        # via o slot dono do dispatch + toast. Paridade com o clique.
        if getattr(spec, "kind", "slash") == "local-action":
            self._on_single_button_local_action_dispatch(next_item, spec)
            return

        # Routing has TWO orthogonal axes (worker axis is the fix of
        # 2026-05-30):
        #   (1) Worker axis — does a Parallel Worker claim this command? A
        #       blue-arrow (worker-eligible) command goes to the worker
        #       terminal (T2 Kimi / T3 Codex) whenever the matching worker
        #       checkbox is active. Evaluated FIRST and fully INDEPENDENT of
        #       which Main LLM is selected.
        #   (2) Main-LLM axis — everything the worker did NOT claim goes to
        #       T1 in the Main LLM's own format (Claude raw / Codex executor
        #       prompt / Kimi skill).
        # Before this fix, Main Codex/Kimi short-circuited to T1 for EVERY
        # command, so blue-arrow commands that belonged to the worker were
        # silently pasted into T1 in the main format (the reported bug). The
        # Claude-main path already routed workers correctly, so the fix is to
        # make that same worker routing apply under any Main LLM.
        #
        cmd_text = next_item.command_text()
        cmd_head = spec.name.strip().split(None, 1)[0].lower()

        # ── Provider router (autoridade do worker axis, source.md §12) ─────── #
        # classify_provider (modulo PURO, task 003) e computado PRIMEIRO e e a
        # AUTORIDADE do dispatch dos DOIS eixos worker (Kimi/T2 e Codex/T3) no
        # step/autocast — paridade com o clique direto (command_item_widget, que
        # ja consumia o router). Decide o provider efetivo do item avaliando o
        # eixo Worker antes do Main-LLM (invariante 2) e a precedencia Kimi>Codex
        # (regra 6). RoutingState recebe SOMENTE estado da queue (checkboxes de
        # worker T2/T3 + Main LLM do T1), NUNCA os terminal-route-toggles
        # (invariante 5). Recovery do loop 06-02-seta-unica (decisao do operador:
        # modelo router/whitelist) + fix F-2 (06-02): step e clique agora
        # concordam para Kimi E Codex (antes so o Codex consumia o router; o gate
        # Kimi legado usava is_kimi_compatible isolado e divergia do clique para
        # itens kimi_eligible-only).
        routing_state = RoutingState(
            kimi_worker_enabled=self._use_kimi_chk.isChecked(),
            codex_worker_enabled=bool(
                getattr(self, "_use_codex_chk", None) is not None
                and self._use_codex_chk.isChecked()
            ),
            main_llm=self._resolve_interactive_main_llm(),
        )
        self._last_classified_provider = classify_provider(spec, routing_state)

        # ── Regra de capacidade exclusiva: GERACAO DE IMAGEM ──────────────── #
        # Enforce mecanico (progress.md "Capacidade exclusiva"): so o Codex gera
        # imagem. Um comando de image-gen roteado a provider != Codex e RECUSADO
        # aqui — nunca despachado ao Claude/Kimi (que falhariam ou, pior,
        # produziriam algo falso). Ative o Worker Codex para roda-lo no T3.
        if (
            is_image_generation_command(spec.name)
            and self._last_classified_provider is not Provider.CODEX
        ):
            signal_bus.toast_requested.emit(
                f"{cmd_head}: geracao de imagem so roda no Worker Codex (T3) —"
                " so o Codex gera imagem. Ative o Worker Codex e tente de novo.",
                "warning",
            )
            return

        # use_kimi e governado pelo router: Provider.KIMI significa worker Kimi
        # ativo E (is_kimi_compatible OU spec.kimi_eligible) E Codex nao venceu
        # (regra 6, Kimi precede). O guard is_worker_arrow_visible() e mantido
        # contra divergencia de whitelist/visibilidade (risco sinalizado por
        # /mcp:kimi senior-reviewer): se a seta worker per-item foi escondida por
        # mutacao futura do spec, cai no fallback em vez de despachar uma acao
        # Kimi sem feedback visual. _on_kimi_clicked e o handler canonico da seta
        # azul (faz signal emit + _mark_as_sent) — nao inlinar o corpo aqui,
        # espelhar a invocacao (fonte unica da verdade).
        use_kimi = (
            self._last_classified_provider is Provider.KIMI
            and next_item.is_worker_arrow_visible()
        )

        # use_codex e governado SO pelo router: Provider.CODEX significa worker
        # Codex ativo E comando na whitelist Codex (is_codex_compatible) E Kimi
        # nao venceu. Substitui o gate legado `codex_blue_eligible` (que reusava
        # a elegibilidade Kimi). Fix D-4: removido o conjunto
        # `_resolve_claude_command_file(...) is not None` (shadow-router que
        # divergia do clique): TODAS as condicoes de falha — incluindo comando
        # sem `.md` — vivem em `_dispatch_codex_command` (toast + retorna False;
        # o gate `if self._dispatch_codex_command(): _mark_as_sent()` mantem o
        # item pendente no abort). Assim step == clique para Codex. /clear|/model
        # /effort e local-action resolvem para CLAUDE no router, nunca chegam como
        # CODEX; is_codex_compatible so casa `/`-commands, entao CODEX => slash.
        use_codex = self._last_classified_provider is Provider.CODEX

        # ALWAYS cancel any pending modal-confirmation Enter from a previous
        # dispatch. Otherwise a 1s-delayed Enter scheduled by a previous
        # /effort can fire into the next command's AskUserQuestion menu
        # and silently select the default option.
        self._cancel_pending_modal_enter()

        # ── Worker axis (FIRST, independent of Main LLM) ──────────────── #
        # Special case: /clear with a Parallel Worker active clears BOTH CLI
        # sessions. T1 always receives /clear raw (Claude, Codex and Kimi all
        # understand /clear unchanged); the active worker terminal mirrors it
        # so both contexts reset together.
        clear_both = (
            cmd_head == "/clear"
            and (self._use_kimi_chk.isChecked() or self._use_codex_chk.isChecked())
        )
        if clear_both:
            signal_bus.run_command_in_terminal.emit(cmd_text)
            if self._use_kimi_chk.isChecked():
                signal_bus.run_command_in_workspace_terminal.emit(cmd_text)
                self._last_workspace_dispatch_was_clear = True
            if self._use_codex_chk.isChecked():
                # task 006 finding F3 — mesmo gate de terminal alvo nao pronto
                # (condicao de falha 4) que ja vale em _dispatch_codex_command:
                # so espelha /clear para o T3 quando o terminal-codex-output
                # esta pronto. Sem o gate, o /clear ia para um xterm inexistente
                # silenciosamente. O T1 ja recebeu /clear raw acima; quando o T3
                # esta indisponivel emitimos toast (Zero Silencio) em vez de
                # publicar no vazio.
                if self._codex_t3_available:
                    signal_bus.run_command_in_workspace_xterm.emit(cmd_text)
                else:
                    signal_bus.toast_requested.emit(
                        "Worker Codex (T3): terminal-codex-output nao esta pronto"
                        " — /clear nao espelhado.",
                        "warning",
                    )
            self._on_run_command(cmd_text)
            next_item._mark_as_sent()
            return

        # Blue-arrow (worker-eligible) command + matching worker checkbox →
        # worker terminal. Kimi takes precedence over Codex when both workers
        # are checked (legacy order preserved). This runs regardless of the
        # Main LLM, so Main Codex/Kimi no longer swallow worker-bound commands.
        if use_kimi:
            next_item._on_kimi_clicked()
            self._last_workspace_dispatch_was_clear = False  # consumed by blue arrow
            return
        if use_codex:
            if self._dispatch_codex_command(cmd_text):  # to_t1=False → T3 xterm
                next_item._mark_as_sent()
            return

        # ── Main-LLM axis ─────────────────────────────────────────────── #
        # No worker claimed this command → dispatch to T1 in the Main LLM's
        # own format.
        if getattr(self, "_main_codex_radio", None) and self._main_codex_radio.isChecked():
            if self._dispatch_codex_command(cmd_text, to_t1=True):
                next_item._mark_as_sent()
            return
        if self._force_kimi_chk.isChecked():
            if self._dispatch_kimi_main_command(cmd_text):
                next_item._mark_as_sent()
            return

        # Claude main (default): raw dispatch to T1 interactive.
        signal_bus.run_command_in_terminal.emit(cmd_text)
        self._on_run_command(cmd_text)
        next_item._mark_as_sent()
        # Pure interactive dispatch does not affect the workspace flag.

        # /effort pede confirmação no Claude Code: agenda um Enter extra 1s
        # depois para aceitar o prompt automaticamente. O timer é cancelado
        # se um novo dispatch acontecer antes do Enter firar (proteção
        # contra firar dentro de AskUserQuestion do próximo comando). Só o
        # caminho Claude main mostra esse modal (Codex/Kimi main suprimem
        # /effort com pulse, sem dispatch — nada para confirmar).
        if spec.name.strip().lower().startswith("/effort"):
            self._arm_pending_modal_enter()

    def _arm_pending_modal_enter(self) -> None:
        """Schedule a 1s Enter to dismiss /effort's confirmation modal,
        cancellable by the next dispatch."""
        self._cancel_pending_modal_enter()
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(signal_bus.submit_enter_to_terminal.emit)
        t.start(1000)
        self._pending_modal_enter_timer = t

    def _cancel_pending_modal_enter(self) -> None:
        """Drop any pending modal-confirmation Enter. Called by every new
        dispatch so a stale Enter can never land in a future command's
        interactive prompt."""
        if self._pending_modal_enter_timer is not None:
            self._pending_modal_enter_timer.stop()
            self._pending_modal_enter_timer = None
