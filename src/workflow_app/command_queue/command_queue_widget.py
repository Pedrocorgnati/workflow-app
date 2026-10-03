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
import time
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
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from workflow_app import dcp as dcp_pkg
from workflow_app import dispatch_telemetry
from workflow_app.command_queue.codex_whitelist import is_image_generation_command
from workflow_app.command_queue.command_item_widget import (
    CommandItemWidget,
    command_text_with_flags,
    render_with_mcp_flags,
)
from workflow_app.command_queue.double_phase_button import DoublePhaseButton
from workflow_app.command_queue.kimi_whitelist import is_t2_eligible
from workflow_app.command_queue.loop_phase_manifest import (
    LoopPhaseManifestError,
    build_sub_names,
)
from workflow_app.command_queue.model_effort_equivalence import (
    adapt_specs_to_main,
    is_directive_line,
    is_foreign_directive,
    is_suppressed_directive,
)
from workflow_app.command_queue.provider_router import (
    Provider,
    RoutingState,
    classify_provider,
)
from workflow_app.command_queue.rocksmash_cursor import (
    RocksmashRuntimeCursor,
    scoped_subphase,
)
from workflow_app.delivery.lock_bridge import (
    _find_systemforge_root as _find_delivery_systemforge_root,
)
from workflow_app.dialogs.confirm_cancel_modal import ConfirmCancelModal
from workflow_app.domain import (
    CommandSpec,
    CommandStatus,
    EffortLevel,
    FlagSpec,
    InteractionType,
    ModelName,
)
from workflow_app.metrics_bar.recovery_prompt import RECOVERY_REASONS
from workflow_app.provider_capability_loader import get_loader as get_capability_loader
from workflow_app.runtime_paths import workflow_app_assets_dir
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

_WORKFLOW_APP_DIR = _find_delivery_systemforge_root() / "ai-forge" / "workflow-app"
_ASSETS_DIR = workflow_app_assets_dir()

# ── Filtro por categoria da sub-aba 'Agentes' (insertions personas) ─────────── #
# A sub-aba 'Agentes' expoe uma barra de filtros (QTabBar) acima do flow unico
# de botoes de persona. A 1a aba e SEMPRE "All" (renderiza todos); as demais
# filtram os botoes pela property `persona_category`. A atribuicao slug ->
# categoria vive em MainWindow (_persona_category), que importa estas constantes
# para validar/normalizar. Manter esta lista como fonte unica da ORDEM das abas.
PERSONA_FILTER_ALL_LABEL = "All"
PERSONA_FILTER_CATEGORIES: tuple[str, ...] = (
    "Plan",
    "Research",
    "Design",
    "Build",
    "Review",
    "specialists",
)
# Categoria default para personas auto-descobertas que nao casam nenhuma regra.
PERSONA_FILTER_DEFAULT = "Build"

# ── Filtro por tipo da sub-aba 'PROMPTS' ──────────────────────────────────── #
PROMPT_FILTER_ALL_LABEL = "All"
PROMPT_FILTER_CATEGORIES: tuple[str, ...] = (
    "Plan",
    "Review",
    "Build",
    "Ops",
    "Study",
    "commit",
)
PROMPT_FILTER_DEFAULT = "Ops"


# `QWIDGETSIZE_MAX` do Qt (nao exposto pelo PySide6): valor de "sem teto" que
# `QWidget.setMaximumHeight` reconhece. Espelha a constante homonima de
# `main_window.py` (duplicada de proposito: importar de la seria circular).
_QT_WIDGET_SIZE_MAX = 16777215


def enable_height_for_width(widget: QWidget) -> None:
    """Faz um container de `ResponsiveButtonFlowLayout` reportar altura real.

    `QWidgetItem.hasHeightForWidth()` consulta a size policy do WIDGET, nao o
    layout interno. Sem esta marca, o layout pai dimensiona o container pelo
    `sizeHint()` do flow — calculado numa largura de referencia fixa de 360px —
    e nao pela altura verdadeira na largura efetiva, entregando uma faixa vazia
    (ou cortando linhas, quando a coluna e mais estreita que a referencia).

    Gemeo de `main_window._enable_height_for_width` (que delega para ca): a
    funcao vive junto do flow porque quem monta as sub-abas e as secoes do
    header e este modulo.
    """
    policy = widget.sizePolicy()
    policy.setHeightForWidth(True)
    widget.setSizePolicy(policy)


class ResponsiveButtonFlowLayout(QLayout):
    """Flow layout para botoes compactos das subtabs de insercoes.

    Quebra widgets em linhas conforme a largura disponivel.

    Dois regimes, escolhidos por `max_lines`:

    - `max_lines=int` (legado): quando a linha `max_lines + 1` seria
      necessaria, reduz a largura alocada dos itens para manter no maximo
      `max_lines` linhas renderizadas.
    - `max_lines=None` (responsivo canonico): numero de linhas livre. Cada
      botao fica com a largura natural do proprio label e a quantidade de
      botoes por linha acompanha a largura da janela — janela maior, mais
      botoes por linha; janela menor, menos.

    `v_spacing` controla o gap vertical entre linhas de forma independente do
    gap horizontal (`spacing`). Default: mesmo valor de `spacing`.
    """

    _BUTTON_FLOOR_WIDTH = 44
    _ABSOLUTE_FLOOR_WIDTH = 8

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        spacing: int = 4,
        v_spacing: int | None = None,
        max_lines: int | None = 4,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self._v_spacing = spacing if v_spacing is None else max(0, v_spacing)
        self._max_lines = None if max_lines is None else max(1, max_lines)
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
        natural = max(item.sizeHint().width(), item.minimumSize().width())
        if self._max_lines is None:
            # Regime responsivo: largura congruente com o proprio label, sem
            # piso artificial (o piso so existe para o regime compactado).
            return natural
        return max(natural, self._BUTTON_FLOOR_WIDTH)

    def _target_floor_width(self, items: list[QLayoutItem], width: int) -> int:
        if self._max_lines is None or not items or width <= 0:
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
        if self._max_lines is None:
            # Sem compactacao no regime responsivo: o minimumWidth do botao
            # nunca e mutado, entao o label permanece integro.
            return
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
        if self._max_lines is None:
            return 1.0, target_floor
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
            if self._max_lines is None and width > 0:
                # Botao mais largo que a area disponivel nunca vaza para fora
                # do container — ele ocupa a linha inteira.
                item_width = min(item_width, width)
            item_height = item.sizeHint().height()
            next_line_width = (
                item_width if line_width == 0
                else line_width + self._spacing + item_width
            )

            can_break = self._max_lines is None or rendered_lines < self._max_lines
            if line_width > 0 and next_line_width > width and can_break:
                y += line_height + self._v_spacing
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


_TEMPLATE_ICON_CHIP_STYLE = (
    "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
    "  border: 1px solid #52525B; border-radius: 3px; padding: 2px; }"
    "QPushButton:hover { background-color: #52525B; color: #FFFFFF; }"
    "QPushButton:pressed { background-color: #FBBF24; color: #18181B;"
    "  border-color: #FBBF24; }"
)


def _apply_template_icon_chip(
    button: QPushButton, icon: QIcon | None, fallback_text: str
) -> None:
    """Aplica o chrome 22x22 dos chips da row queue-template-label."""
    if icon is not None:
        button.setIcon(icon)
        button.setIconSize(QSize(12, 12))
        button.setText("")
    else:
        button.setText(fallback_text)
    button.setFixedSize(22, 22)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(_TEMPLATE_ICON_CHIP_STYLE)


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
    "  font-size: 10px; font-weight: 600; padding: 3px 8px; }"
    "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
    "QPushButton:pressed { background-color: #FBBF24; color: #18181B; border-color: #FBBF24; }"
    "QPushButton:focus { border-color: #FBBF24; }"
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
# NOTA (item 004, D-004-A): `_MODEL_MAP` mapeia o texto de uma diretiva
# `/model X` do CLI Claude para `ModelName`, que tem exatamente dois membros
# (`domain.py`: OPUS, SONNET). `kimi-k3` NAO entra aqui: exigiria ou um membro
# novo no enum — que deixa de ser Claude-only e afeta 5 modulos fora do widget
# — ou um mapa paralelo. Decisao humana pendente; ver `## Decisoes abertas`
# da task 004 do loop 08-17-systemforge-multillm-gaps-refactor.

# Item 004 (C6/C13): lista canonica de slugs do eixo Main LLM com semantica
# family+variant. `opus` e `(claude, opus)`, NAO um provider novo — MF-01
# (source.md:1198) proibe inflar `provider_router.Provider` com variante.
# Este mapa vive no widget de proposito: `provider_router.py` esta em
# "proibido editar" pela clausula de Dependencias do item 004, e o eixo de
# variante nao atravessa o router.
# `claude` (sem variante) permanece fora da lista canonica como default do
# regime legado — e a family nua, nao mais uma opcao de variante.
# `mimo` (2026-10-02, D5) e family nova sem variante: `mimo-pro` existe so
# como literal de flag (`--mimo-pro`), nunca como slug do eixo Main.
_MAIN_LLM_VARIANTS: dict[str, tuple[str, str | None]] = {
    "opus": ("claude", "opus"),
    "sonnet": ("claude", "sonnet"),
    "codex": ("codex", None),
    "kimi": ("kimi", None),
    "kimi-k3": ("kimi", "k3"),
    "qwen": ("qwen", None),
    "mimo": ("mimo", None),
    "grok": ("grok", None),
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
    # Lane /mkt-assets (queue-btn-mkt-assets, 2026-06-18): familia gemea de
    # /loop voltada a gerar 30 posts de feed Instagram a partir do project.json.
    # Todos os subcomandos /mkt-assets:* rodam em sonnet/standard (a cadeia
    # comunica via artefatos em output/mkt-assets/{slug}/runs/, nao via contexto
    # de conversa), entao _build_prep_specs emite o triplet /clear+/model+/effort
    # so na 1a fase e /clear isolado entre as demais (anti-redundancia
    # ai-forge/rules/workflow-app-command-lists.md secao 3.1).
    "mkt_assets": {
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
    # estatica HTML/CSS/JS ja hospedada (Hostinger) ao backend OIDC central
    # systemforge-dashboard (systemforgedashboard.com), adiciona login
    # funcional (Zero Orfaos) e deixa em
    # producao. Os 6 subcomandos /multibackend:* sao todos opus/high (cada
    # um e um passo de pipeline que comunica via scan-report.json em disco,
    # nao via contexto de conversa), entao _inject_clears emite o triplet
    # completo so no primeiro e um /clear isolado antes dos demais.
    "multibackend": {
        "model": ModelName.OPUS,
        "effort": EffortLevel.HIGH,
    },
    # Familia Usabilidade do cliente final (queue-btn-usabilidade-visual +
    # queue-btn-usabilidade-ia): refactor do loop 06-23 apos o revert 06-22
    # (reuso de comandos scope=module em pipeline project-level = orfaos). Os
    # DOIS botoes compartilham este unico par opus/high. Cada handler expande
    # UMA cadeia estatica e completa, sem branch A/B em runtime: a trilha visual
    # e 100% project (zero module-bound); a trilha IA so toca comandos
    # module-bound depois do bootstrap micro:* que cria o modulo e grava o
    # module_id num lock (resolvido em runtime pelos proprios comandos, nunca
    # como placeholder {N} literal na expansao do clique).
    "usabilidade": {
        "model": ModelName.OPUS,
        "effort": EffortLevel.HIGH,
    },
    # NOTA: o pipeline /book-legacy NAO entra no GROUP_MAP porque cada
    # subcomando tem model/effort proprio (3 tiers do Bloco I-34). GROUP_MAP
    # so expressa um par model/effort unico por grupo. O builder
    # _enqueue_book_legacy resolve os tiers per-subcomando internamente.
}


def _realign_after_translation(
    source: list[CommandSpec],
    survivors: list[CommandSpec],
    statuses: list[CommandStatus],
    sent_flags: list[bool],
) -> tuple[list[CommandStatus], list[bool]]:
    """Remapeia status/sent quando a adequacao C27 muda o tamanho da fila.

    A adequacao so mexe em linha de diretiva: sob qualquer Main nao-Claude o
    run inteiro de `/model`+`/effort` e REMOVIDO. Toda linha nao-diretiva
    sobrevive 1:1 e em ordem, entao da para reconstruir a correspondencia
    caminhando as duas listas em paralelo, sem pedir proveniencia.

    O branch de diretiva sobrevivente ficou defensivo (hoje nenhuma adequacao
    preserva diretiva) e existe para nao corromper o alinhamento se uma versao
    futura voltar a transformar em vez de remover: a diretiva herda o estado da
    PRIMEIRA linha do run que a originou.
    """
    out_status: list[CommandStatus] = []
    out_sent: list[bool] = []
    s = 0
    for spec in survivors:
        if is_directive_line(spec.name):
            start = s
            while s < len(source) and is_directive_line(source[s].name):
                s += 1
            if s == start:  # defensivo: diretiva sem ancestral no source
                out_status.append(CommandStatus.PENDENTE)
                out_sent.append(False)
                continue
            out_status.append(statuses[start])
            out_sent.append(sent_flags[start])
            continue
        # Linha comum: pula qualquer run de diretiva descartado antes dela.
        while s < len(source) and is_directive_line(source[s].name):
            s += 1
        if s >= len(source):
            out_status.append(CommandStatus.PENDENTE)
            out_sent.append(False)
            continue
        out_status.append(statuses[s])
        out_sent.append(sent_flags[s])
        s += 1
    return out_status, out_sent


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
        # Telemetria de dispatch: ultimo head publicado por canal. O incidente
        # 2026-08-24 mostrou que as duas ocorrencias de comando engolido foram
        # o PRIMEIRO comando logo depois de um `/clear` — condicao necessaria,
        # nao suficiente (outros pos-/clear rodaram bem). Registrar o flag em
        # cada dispatch e o que permite testar essa correlacao com dados em vez
        # de com memoria de duas amostras.
        self._last_dispatch_head: dict[str, str] = {}
        # Auto-loop (main-command-queue-auto-loop-btn, main_window): quando
        # ligado, o verde autoritativo do T1 rearma a fila — toda seta unica
        # ambar (item enviado) volta a verde/pendente. Só dispara com a fila
        # ESGOTADA (zero pendentes): rearmar no meio faria `_find_next_pending`
        # devolver sempre o item 1 e o autocast repetiria o primeiro item para
        # sempre, sem nunca alcançar o item 2 (starvation).
        self._auto_loop_enabled: bool = False
        # Batching do queue-progress-ring durante o rearme em massa: cada
        # `reset_to_pending()` emitiria um metrics_updated via
        # `_on_item_sent_state_changed`. Suprime durante o loop e emite UMA vez.
        self._suspend_progress_metrics: bool = False

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
        # Task 15: ultimo contexto de loop despachado e o evento de lifecycle
        # montado a partir dele. O atributo continua sendo o espelho do ULTIMO
        # evento (util a teste e a inspecao); a persistencia do corpus e feita
        # em paralelo por `_persist_lifecycle`, que anexa cada evento ao
        # sidecar JSONL. Antes disso o evento morria aqui, sobrescrito pelo
        # proximo, e o corpus de lifecycle nascia vazio.
        self._last_loop_context = None
        self._last_lifecycle_event: dict | None = None
        # Task 24: eventos de FILA (canceled/closed) e o par provider/instante
        # do ultimo despacho, necessarios para `item_completed`/`item_failed`.
        # `None` aqui e "nao observado nesta sessao", nunca zero.
        self._last_queue_lifecycle_event: dict | None = None
        self._last_dispatch_provider: str | None = None
        self._last_dispatch_started_at: float | None = None
        # Task 24(a): registro do despacho AINDA SEM DESFECHO. E o que permite
        # `item_completed`/`item_failed` existirem: os dois eventos estavam
        # instrumentados e mudos porque seus unicos gatilhos eram
        # `signal_bus.command_completed`/`command_failed`, que nao tem UM
        # `.emit()` em `src/`. O desfecho real vem dos dois sinais autoritativos
        # que o app de fato emite — `listener_authoritative_idle` (verde
        # pos-fence) e `autocast_abort_requested` (falha de listener).
        # `None` = "nenhum despacho em voo", nunca "concluido".
        self._pending_item_outcome: dict | None = None
        # Task 33: totais da sessao viva (caminho do terminal, nao PipelineManager).
        # Acumulados so quando observe_usage devolve numero > 0.
        self._usage_session_in: int = 0
        self._usage_session_out: int = 0
        self._usage_session_cost: float = 0.0
        # Tasks 19/20: binding vivo com o `_ROCKSMASH-STATE.json` da fila
        # rocksmash corrente. `None` em qualquer outra fila — e a maioria delas.
        self._rocksmash_cursor: RocksmashRuntimeCursor | None = None
        # Task 16: ultima tentativa de retomada do botao Loop. `None` significa
        # "nunca clicado" — nao "retomada vazia"; sao estados diferentes e
        # confundi-los faria o funil contar clique que nao houve.
        self._last_resume_record: dict | None = None
        self._last_resume_event: dict | None = None
        # Task 24 (call sites): travas de idempotencia dos eventos de FILA.
        # `queue_started` sai uma vez por `queue_id` (a identidade da fila, nao
        # do dispatch). Pausa/retomada usam uma MAQUINA DE ESTADO por `queue_id`
        # em vez de um booleano: o booleano desduplicava a emissao dupla
        # conhecida (module_detail emite e `PipelineManager.pause()` reemite),
        # mas engolia a retomada de uma pausa gravada em OUTRA sessao do app, e
        # ai o loop ficava `paused` para sempre no corpus. `app_closed` tem dois
        # ancoradouros (closeEvent + aboutToQuit) porque o proprio repositorio
        # documenta que widget-filho nao recebe closeEvent de forma confiavel.
        self._queue_started_emitted: set[str] = set()
        self._queue_pause_state: dict[str, str] = {}
        self._app_closed_emitted: bool = False

        # Tracks whether the LAST workspace dispatch was /clear. The next
        # blue-arrow Kimi dispatch reads this to add 2s extra delay before
        # Enter (Kimi takes longer to render its prompt right after a clear
        # because the whole TUI is being repainted from scratch).
        self._last_workspace_dispatch_was_clear: bool = False
        # Seq do `/clear` adiado no T1 sob Main Kimi. Incrementa em todo
        # publish interactive: um dispatch novo cancela o `/clear` pendente.
        self._pending_kimi_clear_seq: int = 0

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

    @staticmethod
    def _is_loop_attachment_config(config: object | None) -> bool:
        """Retorna True somente quando o config tem shape de _LOOP-CONFIG.json."""
        if config is None:
            return False
        raw = getattr(config, "raw", None)
        return (
            isinstance(raw, dict)
            and raw.get("kind") == "daily-loop"
            and "daily_loop" in raw
        )

    @classmethod
    def _resolve_loop_attachment_config(cls):
        """Resolve o anexo loop sem consultar project.json por engano.

        Fonte primaria: ``app_state.loop_config`` (metrics-loop-pill).
        Compatibilidade: aceita ``app_state.config`` apenas quando o proprio
        payload legado tem shape de _LOOP-CONFIG.json.
        """
        from workflow_app.config.app_state import app_state

        if app_state.loop_config is not None:
            return app_state.loop_config
        legacy_config = app_state.config
        if cls._is_loop_attachment_config(legacy_config):
            return legacy_config
        return None

    class _AttachmentProxy:
        """Proxy que implementa a interface pill para DoublePhaseButton."""

        def __init__(self, widget, loader, attachment_kind: str = "project"):
            self._widget = widget
            self._loader = loader
            self._attachment_kind = attachment_kind

        def has_attachment(self):
            from workflow_app.config.app_state import app_state
            if self._attachment_kind == "loop":
                return (
                    app_state.loop_config is not None
                    or self._widget._is_loop_attachment_config(app_state.config)
                )
            return app_state.has_project and app_state.project_config is not None

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
        elif base_cmd == "/mkt-assets":
            self._on_mkt_assets_command_ready(command_line)
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

    def _selected_brainstorm_md_path(self) -> str:
        """Retorna o .md selecionado no picker da aba brainstorm, se existir."""
        win = self.window()
        return str(getattr(win, "_brainstorm_md_path", "") or "").strip()

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
            # Espelha a sanitizacao do produtor /cmd:kimi-pair-analyse (Passo 5.1:
            # slug_sanitized = cmd_slash.lstrip('/').replace(':','_')). Sem o
            # replace(':','_') o report_path diverge para alvos com namespace
            # (ex: /mkt-assets:workflow-app -> mkt-assets:workflow-app-... em vez
            # de mkt-assets_workflow-app-...), e o execute recebe path inexistente.
            kimi_slug = cmd_target_slash.lstrip("/").replace(":", "_")
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
            # Ultima etapa: implanta as flags multi-LLM (--kimi/--codex) no
            # comando recem criado/atualizado. Guard de existencia: so enfileira
            # /auto-improove:mcp-flags se o proprio comando existir em disco;
            # caso contrario emite toast warning e segue sem o passo, nunca
            # enfileirando comando inexistente (task-006 do loop de flags).
            mcp_flags_cmd_path = (
                base_dir / ".claude" / "commands" / "auto-improove" / "mcp-flags.md"
            )
            if mcp_flags_cmd_path.exists():
                specs.append(
                    _cmd_spec(f"/auto-improove:mcp-flags --target {cmd_target_slash}")
                )
            else:
                signal_bus.toast_requested.emit(
                    "comando /auto-improove:mcp-flags ausente; "
                    "passo mcp-flags omitido da fila --cmd-single",
                    "warning",
                )
            label = f"  \U0001f4cb  Loop --cmd-single: {cmd_target_slash} ({cmd_action})"
            auto_save_label = f"Loop --cmd-single {cmd_target_slash}"
        else:
            # Anatomia (nome, ordem, args) vem do manifesto canonico
            # ai-forge/rules/loop-phase-manifest.json — nao de listas literais
            # aqui. Contagem vigente: 8 fases em --task, 7 em --cmd, 10 em
            # --both (feature-design entrou em --task/--both na Task 27 do
            # estudo 08-24; fica fora de --cmd porque o modo --cmd cria
            # slash-commands, nao feature de produto).
            try:
                sub_names = build_sub_names(
                    "loop", mode, path_arg=path_arg, slug=slug
                )
            except LoopPhaseManifestError as exc:
                signal_bus.toast_requested.emit(
                    f"Manifesto de fases do loop indisponivel: {exc}", "error"
                )
                return

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

        # Mesma fonte da lane /loop: ai-forge/rules/loop-phase-manifest.json.
        # A lane kimi divide create-structure em init + enumerate e nao tem
        # friendly-resume, mas a contagem coincide: 7/7/9.
        try:
            sub_names = build_sub_names(
                "kimi_loop", mode, path_arg=path_arg, slug=slug
            )
        except LoopPhaseManifestError as exc:
            signal_bus.toast_requested.emit(
                f"Manifesto de fases do loop indisponivel: {exc}", "error"
            )
            return

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

    def _on_mkt_assets_command_ready(self, command_line: str) -> None:
        """Expand `/mkt-assets <project.json>` na cadeia canonica da familia.

        Gemeo de `_on_kimi_loop_command_ready` para a familia `/mkt-assets:*`
        (queue-btn-mkt-assets, 2026-06-18). Diferente de /loop e /kimi-loop, a
        familia NAO tem modos (--task/--cmd/--both) nem normalizacao de slug: o
        argumento unico canonico de TODOS os subcomandos e o path do
        `project.json` (argument-hint `<project.json>` em cada
        .claude/commands/mkt-assets/*.md). Expande a forma secao 8 (sem
        centralizador) na ordem canonica scan -> research -> plan -> generate ->
        review -> workflow-app, todas em GROUP_MAP["mkt_assets"]
        (sonnet/standard). Os comandos /mkt-assets:iteraction:* NAO entram na
        fila: sao dirigidos por /mkt-assets:generate em runtime (1 iteration por
        post). Anti-redundancia (secao 3.1): _build_prep_specs emite o triplet
        completo so na 1a fase; /clear isolado entre as demais (todas no mesmo
        grupo, model/effort inalterados).
        """
        tokens = command_line.strip().split()
        project_arg = ""
        if tokens and tokens[0] == "/mkt-assets":
            # Argumento unico = primeiro token nao-flag. Cobre os dois caminhos:
            # `/mkt-assets <path>` (positional emitido pelo pill) e
            # `/mkt-assets --project <path>` (dialog) — em ambos o <path> e o
            # primeiro token que nao comeca por "--".
            for t in tokens[1:]:
                if not t.startswith("--"):
                    project_arg = t
                    break

        if not project_arg:
            spec = CommandSpec(
                name=command_line,
                model=ModelName.SONNET,
                interaction_type=InteractionType.INTERACTIVE,
                position=len(self._items) + 1,
            )
            self.add_command(spec)
            self._template_label.setText("  \U0001f4cb  Mkt-Assets")
            self._template_label.setVisible(True)
            self._maybe_auto_save("Mkt-Assets")
            return

        mkt_cfg = GROUP_MAP.get("mkt_assets", {})
        mkt_model = mkt_cfg.get("model", ModelName.SONNET)
        mkt_effort = mkt_cfg.get("effort", EffortLevel.STANDARD)

        # Cadeia canonica da familia (W6 de /mkt-assets:workflow-app + secao 8):
        # cada subcomando e linha propria, na ordem da spec; NUNCA o
        # centralizador `/mkt-assets <subindicador>`.
        # /mkt-assets:generate cria o esqueleto ASSETS-TO-CREATE.md +
        # _GENERATE-CHECKPOINT.json (necessario para os pares iteraction).
        # O botao expande esta fase em 30 pares (generate-post + review-post)
        # conforme documentado em /mkt-assets:generate (secao Nota de
        # Configuracao). generate-post e idempotente (dedupe na reentrada);
        # review-post e o QA por bloco que estava ausente neste botao.
        # /mkt-assets:workflow-app e o fechador (handoff p/ /pictures-create).
        slug = Path(project_arg).stem
        _iteraction_pairs: list[str] = []
        for _i in range(1, 31):
            _post_id = f"post-{_i:02d}"
            _iteraction_pairs.append(
                f"/mkt-assets:iteraction:generate-post --slug {slug} --post {_post_id} --config {project_arg}"
            )
            _iteraction_pairs.append(
                f"/mkt-assets:iteraction:review-post --slug {slug} --post {_post_id} --config {project_arg}"
            )
        sub_names = [
            f"/mkt-assets:scan {project_arg}",
            f"/mkt-assets:research {project_arg}",
            f"/mkt-assets:plan {project_arg}",
            f"/mkt-assets:generate {project_arg}",
            *_iteraction_pairs,
            f"/mkt-assets:review {project_arg}",
            f"/mkt-assets:workflow-app {project_arg}",
        ]

        specs: list[CommandSpec] = []
        specs.extend(_build_prep_specs("mkt_assets", start_position=1))
        specs.append(
            CommandSpec(
                name=sub_names[0],
                model=mkt_model,
                interaction_type=InteractionType.AUTO,
                config_path="",
                effort=mkt_effort,
                position=len(specs) + 1,
            )
        )
        for sub in sub_names[1:]:
            # Boundary entre fases independentes: apenas /clear. /model e
            # /effort sao SUPRIMIDOS porque TODAS as fases rodam em
            # sonnet/standard (GROUP_MAP["mkt_assets"]) — anti-redundancia
            # (ai-forge/rules/workflow-app-command-lists.md secao 3.1).
            specs.append(
                CommandSpec(
                    name="/clear",
                    model=mkt_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=mkt_effort,
                    position=len(specs) + 1,
                )
            )
            specs.append(
                CommandSpec(
                    name=sub,
                    model=mkt_model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    effort=mkt_effort,
                    position=len(specs) + 1,
                )
            )

        label = f"  \U0001f4cb  Mkt-Assets: {len(sub_names)} itens (4+60+2)"
        self._template_label.setText(label)
        self._template_label.setVisible(True)
        self._maybe_auto_save("Mkt-Assets")
        signal_bus.pipeline_ready.emit(specs)
        signal_bus.toast_requested.emit(
            f"Fila renderizada: {len(specs)} comandos.", "success"
        )

    def _on_mkt_assets_clicked(self) -> None:
        """Pill loader do queue-btn-mkt-assets: resolve o project.json ativo.

        Le o project.json carregado na metrics-project-pill (app_state) e roteia
        para `_on_mkt_assets_command_ready` com o path positional. Gate verboso
        pt-BR quando nenhum projeto esta carregado (mirror rocksmash): sugere o
        botao [json] (queue-btn-json). O `_AttachmentProxy.has_attachment` ja
        exige has_config, mas a validacao de existencia em disco e repetida aqui
        (defesa em profundidade, igual aos demais botoes project-scoped).
        """
        from workflow_app.config.app_state import app_state

        if not app_state.has_config or app_state.config is None:
            signal_bus.toast_requested.emit(
                "mkt-assets requer um project.json carregado na "
                "metrics-project-pill. Use o botao [json] (queue-btn-json) "
                "para carregar ou criar um project.json antes de acionar "
                "este botao.",
                "warning",
            )
            return

        json_path = str(app_state.config.config_path or "")
        if not json_path or not Path(json_path).is_file():
            signal_bus.toast_requested.emit(
                "O project.json da metrics-project-pill nao foi localizado em "
                f"disco ({json_path or 'caminho vazio'}). Recarregue o projeto "
                "via botao [json] (queue-btn-json) e tente novamente.",
                "error",
            )
            return

        self._on_mkt_assets_command_ready(f"/mkt-assets {json_path}")

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
        # Moldura identica a output-toolbar-center: fundo #1E1E21, borda
        # 1px #3F3F46, radius 6px, padding uniforme 4px. As abas primarias
        # ficam a esquerda em tamanho natural (sem barra interna de 38px
        # nem stretch full-width), no mesmo papel do QTabBar de
        # queue-subtabs-insertions.
        header.setStyleSheet(
            "QWidget#CommandQueueHeader { background-color: #1E1E21;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(4, 4, 4, 4)
        header_layout.setSpacing(0)

        # ── Tab/action row ───────────────────────────────────────────────
        # Apenas abas primarias (LOOPs, Workflow, Auxiliar).
        # insertions_bar (Inserções + route-toggles + gear) migrou para
        # output-toolbar-center via MainWindow._setup_ui.
        tab_row = QWidget()
        tab_row.setStyleSheet("background: transparent; border: none;")
        tab_row_layout = QHBoxLayout(tab_row)
        tab_row_layout.setContentsMargins(0, 0, 0, 4)
        tab_row_layout.setSpacing(6)

        tab_bar = QWidget()
        tab_bar.setProperty("testid", "output-toolbar-left-primary-tabs")
        tab_bar.setStyleSheet("background: transparent; border: none;")
        tab_bar_layout = QHBoxLayout(tab_bar)
        tab_bar_layout.setContentsMargins(0, 0, 0, 0)
        tab_bar_layout.setSpacing(3)

        insertions_bar = QWidget()
        insertions_bar.setProperty("testid", "output-toolbar-left-insertions-controls")
        # `border: none` e obrigatorio desde 2026-07-20: a barra passou a viver
        # dentro do queue-div-llm-routing, cujo QSS nao-escopado (`QWidget { ...
        # border: 1px solid #3F3F46 }`) cascatearia uma borda espuria aqui.
        insertions_bar.setStyleSheet("background: transparent; border: none;")
        insertions_bar_layout = QHBoxLayout(insertions_bar)
        insertions_bar_layout.setContentsMargins(0, 0, 0, 0)
        insertions_bar_layout.setSpacing(3)

        self._sec_tabs: list[QPushButton] = []
        # A 4a aba (`queue-tab-terminal-insertions`) foi removida em
        # 07-27-workflow-app-header-toggles-llm-unico (I3.3): nunca entrava em
        # layout e passou a duplicar o botao "TERMINAL INSERTIONS" do
        # `output-toolbar-section-selector`. `insertions_content` continua
        # exposto como atributo publico (pagina 1 do stack do header).
        _tab_testids = (
            "queue-tab-workflow",
            "queue-tab-loops",
            "queue-tab-auxiliar",
        )
        for i, label in enumerate(("Workflow", "LOOPs", "Auxiliar")):
            btn = QPushButton(label.upper())
            btn.setFixedHeight(22)
            btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("testid", _tab_testids[i])
            btn.clicked.connect(lambda _ch=False, idx=i: self._switch_section(idx))
            self._sec_tabs.append(btn)
        # Ordem visual: LOOPs | WORKFLOW | AUXILIAR. `_sec_tabs` e
        # `_sec_contents` seguem o indice logico (0=Workflow, 1=LOOPs).
        tab_bar_layout.addWidget(self._sec_tabs[1])
        tab_bar_layout.addWidget(self._sec_tabs[0])
        tab_bar_layout.addWidget(self._sec_tabs[2])

        tab_row_layout.addWidget(tab_bar)
        tab_row_layout.addStretch(1)
        # insertions_bar NAO entra no tab_row — MainWindow coloca em output-toolbar-center.

        # Exposed so MainWindow can:
        #   (a) append extras (ex-terminal-route-toggles, hoje sem chamador)
        #       via attach_tab_bar_extras();
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
            self, self._on_daily_loop_clicked, attachment_kind="loop"
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
            "Le _LOOP-CONFIG.json + PROGRESS.md do anexo loop e cria "
            "para CADA item pendente: /daily-loop:do (bucket model/effort) + "
            "/daily-loop:review-done (Opus/standard, /mcp:dual Level 3 "
            "CROSS_ADVERSARIAL — analogo per-item de /review-executed-task, "
            "reverte+corrige+re-acceptance se achar regressao). Final: "
            "/daily-loop:review global em Opus/HIGH. /clear/model/effort "
            "dedupados entre buckets."
        )
        daily_loop_btn.setStyleSheet(_SECTION_BTN_STYLE)

        loop_pill = self._AttachmentProxy(
            self, self._on_loop_clicked, attachment_kind="loop"
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
            selected_md_path_getter=self._selected_brainstorm_md_path,
            pill=loop_pill,
            on_command_ready=self._on_unified_command_ready,
            parent=self,
        )
        loop_btn.setProperty("testid", "queue-btn-loop")
        loop_btn.setToolTip(
            "Loop — expande fila finita gerada por /loop (--task|--cmd|--cmd-single|--both). "
            "Le _LOOP-CONFIG.json + PROGRESS.md do anexo loop e cria "
            "para CADA item pendente: /daily-loop:do (bucket model/effort) + "
            "/daily-loop:review-done (Opus/standard, /mcp:dual Level 3 "
            "CROSS_ADVERSARIAL). Final: /daily-loop:review global em Opus/HIGH. "
            "/clear/model/effort dedupados entre buckets."
        )
        loop_btn.setStyleSheet(_SECTION_BTN_STYLE)

        # simple loop — gemeo economico do loop_btn (queue-btn-loop-simple,
        # 2026-09-17). Mesmo anexo/JSON/PROGRESS.md do loop normal; a unica
        # diferenca e que build_loop_specs(..., simple=True) reduz o bloco
        # per-item para /loop:iteraction:create-task +
        # /loop:iteraction:execute-task --simple-loop + /clear (badge em
        # .claude/commands/loop/iteraction/execute-task.md absorve o trabalho
        # de review-executed-task; review-created-task e apenas descartado).
        # Alternar entre este botao e o loop_btn no meio de uma execucao e
        # seguro: o estado persistido (_LOOP-CONFIG.json + progress.md) e
        # identico.
        loop_simple_pill = self._AttachmentProxy(
            self, lambda: self._on_loop_clicked(simple=True), attachment_kind="loop"
        )
        loop_simple_btn = DoublePhaseButton(
            label="simple loop",
            pipeline_name="/loop",
            argument_hint="--task <path.md> [--name <slug>] | --cmd <path.md> [--name <slug>] | --cmd-single <path.md> | --both <path.md> [--name <slug>]",
            default_md_dir="blacksmith/loop/",
            radio_summaries={
                "--task": "para iterar execucao de tasks ja criadas em modulo ou micro-architecture (modo economico)",
                "--cmd": "para criar ou atualizar varios slash-commands do SystemForge em batch completo (modo economico)",
                "--cmd-single": "para criar ou atualizar um unico slash-command via sub-pipeline reduzida direta",
                "--both": "para fluxos que vao conter tasks variadas e criacao de comandos (modo economico)",
            },
            flags_boolean=loop_spec.flags_boolean if loop_spec else None,
            flags_with_value=loop_spec.flags_with_value if loop_spec else None,
            selected_md_path_getter=self._selected_brainstorm_md_path,
            pill=loop_simple_pill,
            on_command_ready=self._on_unified_command_ready,
            parent=self,
        )
        loop_simple_btn.setProperty("testid", "queue-btn-loop-simple")
        loop_simple_btn.setToolTip(
            "Simple Loop — versao economica do Loop. Por item, roda apenas "
            "/loop:iteraction:create-task + "
            "/loop:iteraction:execute-task --simple-loop + /clear (pula "
            "review-created-task e review-executed-task; o trabalho do "
            "segundo e absorvido inline pela badge --simple-loop do "
            "execute-task mantido). "
            "Finaliza igual ao Loop normal (/loop:reconcile-check + "
            "/loop:iteraction:review-executed-loop). Mesmo _LOOP-CONFIG.json e "
            "progress.md do Loop — da para alternar entre os dois botoes no "
            "meio de uma execucao sem perder progresso."
        )
        loop_simple_btn.setStyleSheet(_SECTION_BTN_STYLE)

        # kimi-loop — gemeo do loop_btn na lane Kimi (/kimi-loop:*). Pill
        # REUSA _on_loop_clicked: o _LOOP-CONFIG.json e identico (D1/D2 do
        # design blacksmith/09-06-llm-dumb-use/KIMI-LOOP-DESIGN.md); a lane se
        # distingue pelos commands /kimi-loop:iteraction:* dentro do JSON.
        kimi_loop_pill = self._AttachmentProxy(
            self, self._on_loop_clicked, attachment_kind="loop"
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

        # mkt-assets — familia gemea de /loop (lane mode: mkt_assets) voltada a
        # gerar 30 posts de feed Instagram a partir do project.json
        # (queue-btn-mkt-assets, 2026-06-18). Pill reusa o padrao project-scoped:
        # _on_mkt_assets_clicked le o project.json ativo da metrics-project-pill;
        # sem projeto carregado, o dialog coleta o path e roteia pelo
        # _on_unified_command_ready (-> _on_mkt_assets_command_ready).
        mkt_assets_pill = self._AttachmentProxy(
            self, self._on_mkt_assets_clicked
        )
        mkt_assets_spec = COMMAND_FLAG_SPECS.get("/mkt-assets")
        mkt_assets_btn = DoublePhaseButton(
            label="mkt-assets",
            pipeline_name="/mkt-assets",
            argument_hint="<project.json>",
            default_md_dir=".claude/projects/",
            radio_summaries={},
            flags_boolean=mkt_assets_spec.flags_boolean if mkt_assets_spec else None,
            flags_with_value=mkt_assets_spec.flags_with_value if mkt_assets_spec else None,
            pill=mkt_assets_pill,
            on_command_ready=self._on_unified_command_ready,
            parent=self,
        )
        mkt_assets_btn.setProperty("testid", "queue-btn-mkt-assets")
        mkt_assets_btn.setToolTip(
            "Mkt-Assets — familia gemea de /loop (lane mode: mkt_assets) que "
            "recebe o project.json, analisa o repositorio em workspace_root, "
            "pesquisa tendencias, planeja 30 dias de feed Instagram e entrega "
            "30 prompts de arte em ASSETS-TO-CREATE.md + CAPTIONS-30D.md. "
            "Expande a cadeia (forma secao 8, sem centralizador): /mkt-assets:scan "
            "-> research -> plan -> generate (+iteraction:* em runtime) -> review "
            "-> workflow-app. GROUP_MAP mkt_assets = sonnet/standard; /clear "
            "dedupado entre fases. Handoff final para /pictures-create."
        )
        mkt_assets_btn.setStyleSheet(_SECTION_BTN_STYLE)

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
            ("Modules (Creation)",
             "Fase A do canonical loop — cria estrutura WBS, MODULE-META.json, "
             "as TASK-<n>.md por module e delivery.json.\n"
             "Pre-requisito de [DCP Build] e TAMBEM de [Build+Exec (modules)] / "
             "[Create+Exec All (modules)] — esses dois derivam a fila das "
             "TASK-*.md em disco, entao precisam que este passo tenha rodado, "
             "mas NAO precisam de [DCP Build].",
             self._on_modules_clicked,
             "queue-btn-modules"),
            ("Build+Exec (modules)",
             "Enfileira Build+Exec (5 comandos nucleares por task real, mais UM "
             "/review-executed-module --auto-close por module com task) para TODOS "
             "os modules encontrados em disco sob {wbs_root}/modules/.\n"
             "Com veredito APROVADO o review da baixa no module (done) e avanca "
             "current_module automaticamente.\n"
             "Modules sem task executavel sao pulados e logados; nenhum "
             "/review-executed-module orfao e emitido para eles.\n"
             "NAO requer [DCP Build]: a fila e derivada 100% do disco "
             "({wbs_root}/modules/ + TASK-*.md), sem ler DCP-COMMAND-MATRIX.json "
             "nem SPECIFIC-FLOW.json. Unico pre-requisito de estrutura e "
             "[Modules (Creation)], que materializa as TASK-*.md.\n"
             "Habilitado quando ha projeto carregado; nao depende do reader de "
             "SPECIFIC-FLOW.json (disk-only, fora do gating de "
             "_apply_dcp_reader_gating).",
             self._on_build_execute_modules_clicked,
             "queue-btn-build-execute-modules"),
            ("Create+Exec All (modules)",
             "Versao reduzida de [Build+Exec (modules)]: enfileira apenas "
             "/create-task e /execute-task por task real (sem "
             "/review-created-task nem /review-executed-task), mais UM "
             "/review-executed-module --auto-close por module com task, "
             "para TODOS os modules encontrados em disco sob "
             "{wbs_root}/modules/.\n"
             "Mesmas pre-condicoes e mesmo comportamento de skip de modules "
             "sem task executavel do [Build+Exec (modules)], incluindo a "
             "independencia de [DCP Build]: fila 100% derivada do disco.",
             self._on_create_execute_all_modules_clicked,
             "queue-btn-create-execute-all-modules"),
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
            loop_simple_btn,
            kimi_loop_btn,
            mkt_assets_btn,
            study_btn,
            ("rocksmash",
             "rocksmash — le anexo loop (_LOOP-CONFIG.json kind=daily-loop), "
             "expande para fila /loop-rocksmash:prepare + N quadruplas "
             ":do/:review-done/:compare/:integrate + "
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
             "hospedada (Hostinger) ao backend OIDC central systemforge-dashboard "
             "(systemforgedashboard.com) (loop de origem 06-03), injeta um botao "
             "de login OIDC funcional (Zero Orfaos) e "
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
             "verbose pt-BR, nada enfileira. As origens vinculadas por esta "
             "pipeline aparecem inventariadas e com diagnostico de paridade na "
             "aba admin Integracoes do backend central (systemforge-dashboard).",
             self._on_multibackend_clicked,
             "queue-btn-multibackend"),
            ("usabilidade visual",
             "Usabilidade (visual/responsivo) — trilha 100% project, zero "
             "module-bound (licao do revert 06-22). Le o project.json do "
             "metrics-project-pill como $1. Cadeia A estatica (12 comandos "
             "opus/high, sem branch em runtime): IDENTIFICAR via "
             "/usabilidade:detect + /frontend:scan + /frontend:audit + "
             "/frontend:mobile-check + /frontend:assets-check + /frontend:report "
             "-> IMPLANTAR via /tools:layout-full-refactor + /tools:mobile-analysis "
             "+ /tools:mobile-update -> REVISAR (delta gate) re-rodando "
             "/usabilidade:detect + /frontend:report -> MANUAL via "
             "/instruction-manual (recebe o workspace_root derivado do config, "
             "nao o placeholder literal). Nenhum --module, nenhum "
             "build-module-pipeline, nenhum review-executed-module, nenhuma "
             "entrevista. Sem project.json carregado -> toast verbose pt-BR, "
             "nada enfileira.",
             self._on_usabilidade_visual_clicked,
             "queue-btn-usabilidade-visual"),
            ("usabilidade IA",
             "Usabilidade (IA/findability) — trilha que cria um modulo real via "
             "micro-architecture ANTES de qualquer comando module-bound; o "
             "numero do modulo nunca aparece como placeholder {N}. Le o "
             "project.json do metrics-project-pill como $1. Cadeia B estatica "
             "(13 comandos opus/high, sem branch em runtime): IDENTIFICAR via "
             "/usabilidade:detect + /frontend:scan + /frontend:audit + "
             "/frontend:report -> BOOTSTRAP DCP-lite /micro:brief -> "
             "/micro:architecture -> /micro:specific-flow-prep -> "
             "/micro:modularize (CRIA o modulo e grava o module_id no lock/"
             "delivery.json) -> /micro:review -> BUILD via /build-module-pipeline "
             "(resolve o modulo ativo lendo o lock, fail-closed se ausente) -> "
             "REVISAR via /review-executed-module (mesmo lock) + /front-end-review "
             "-> MANUAL via /instruction-manual (workspace_root derivado do "
             "config). Os comandos module-bound rodam sempre depois do bootstrap "
             "que cria o modulo; nenhum {N} literal na fila. Sem project.json "
             "carregado -> toast verbose pt-BR, nada enfileira.",
             self._on_usabilidade_ia_clicked,
             "queue-btn-usabilidade-ia"),
            ("Credentials",
             "Credentials — gera e executa credenciais para o projeto carregado.\n"
             "Cadeia enfileirada (3 comandos com tiers proprios):\n"
             "  1. /credentials:env-creation {config_path} (sonnet/low)\n"
             "  2. /credentials:create {config_path} (opus/high)\n"
             "  3. /credentials:execute {config_path} (sonnet/high)\n"
             "Le o project.json da metrics-project-pill como $1. Cada comando "
             "comunica com o anterior via .claude/projects/{slug}.credentials-state.json "
             "em disco, por isso um /clear e injetado entre eles. Roteado "
             "exclusivamente para Claude (nao entra em whitelist Kimi/Codex). "
             "Sem project.json carregado -> toast verbose pt-BR, nada enfileira. "
             "Use o botao [json] (queue-btn-json) para criar ou carregar um "
             "project.json antes de rodar este pipeline.",
             self._on_credentials_clicked,
             "queue-btn-credentials"),
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
            lay = ResponsiveButtonFlowLayout(w, spacing=4, v_spacing=1, max_lines=None)
            lay.setContentsMargins(0, 2, 0, 2)
            # Sem esta marca a sub-aba e medida pelo sizeHint de referencia
            # (360px) do flow, e nao pela altura real na largura do header.
            enable_height_for_width(w)
            return w, lay

        # paths & IDs agora usa o mesmo flow responsivo das demais subtabs.
        # `repo rules` entra no mesmo fluxo para a quebra por largura valer
        # para a sub-aba inteira (linhas livres, gap vertical de 1px).
        _paths_tab = QWidget()
        _paths_tab.setProperty("testid", "queue-subtab-insertions-paths")
        self._subtab_paths_layout = ResponsiveButtonFlowLayout(
            _paths_tab, spacing=4, v_spacing=1, max_lines=None
        )
        self._subtab_paths_layout.setContentsMargins(0, 2, 0, 2)
        enable_height_for_width(_paths_tab)
        _prompts_tab = QWidget()
        _prompts_tab.setProperty("testid", "queue-subtab-insertions-prompts")
        _prompts_row = QHBoxLayout(_prompts_tab)
        _prompts_row.setContentsMargins(0, 0, 0, 0)
        _prompts_row.setSpacing(6)

        _prompts_main = QWidget()
        _prompts_outer = QVBoxLayout(_prompts_main)
        _prompts_outer.setContentsMargins(0, 0, 0, 0)
        _prompts_outer.setSpacing(3)

        self._prompts_filter_bar = QTabBar()
        self._prompts_filter_bar.setProperty("testid", "queue-prompts-filter-bar")
        self._prompts_filter_bar.setExpanding(False)
        self._prompts_filter_bar.setDrawBase(False)
        self._prompts_filter_bar.setUsesScrollButtons(True)
        self._prompts_filter_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._prompts_filter_bar.setStyleSheet(
            "QTabBar { background: transparent; }"
            "QTabBar::tab { background: #27272A; color: #A1A1AA;"
            "  border: none; border-radius: 3px;"
            "  padding: 3px 9px; font-size: 9px; font-weight: 700;"
            "  letter-spacing: 0.4px; margin-right: 3px; }"
            "QTabBar::tab:selected { background: #0D9488; color: #FAFAFA; }"
            "QTabBar::tab:hover:!selected { background: #3F3F46; color: #D4D4D8; }"
        )
        self._prompts_filter_bar.addTab(PROMPT_FILTER_ALL_LABEL)
        for _cat in PROMPT_FILTER_CATEGORIES:
            self._prompts_filter_bar.addTab(_cat)
        _prompts_outer.addWidget(self._prompts_filter_bar)

        _prompts_flow_host = QWidget()
        self._subtab_prompts_layout = ResponsiveButtonFlowLayout(
            _prompts_flow_host, spacing=4, v_spacing=1, max_lines=None
        )
        self._subtab_prompts_layout.setContentsMargins(0, 2, 0, 2)
        # heightForWidth precisa subir host -> _prompts_main -> _prompts_tab
        # para a sub-aba ser medida pela altura real (o QVBoxLayout so propaga
        # se o item filho anunciar hfw na size policy).
        enable_height_for_width(_prompts_flow_host)
        enable_height_for_width(_prompts_main)
        enable_height_for_width(_prompts_tab)
        _prompts_outer.addWidget(_prompts_flow_host, stretch=1)

        # Div utils (mesmo padrao de `queue-subtab-insertions-personas-utils`
        # e `queue-subtab-insertions-brainstorm-utils`): o gear de config sai
        # do flow e fica no canto direito, pequeno e discreto.
        _prompts_utils = QWidget()
        _prompts_utils.setObjectName("PromptsUtilsColumn")
        _prompts_utils.setProperty("testid", "queue-subtab-insertions-prompts-utils")
        _prompts_utils.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _prompts_utils.setStyleSheet(
            "QWidget#PromptsUtilsColumn { background-color: #1E1E21;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        _prompts_utils.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._subtab_prompts_utils_layout = QVBoxLayout(_prompts_utils)
        self._subtab_prompts_utils_layout.setContentsMargins(4, 4, 4, 4)
        self._subtab_prompts_utils_layout.setSpacing(4)
        self._subtab_prompts_utils_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetFixedSize
        )
        self._prompts_utils_div = _prompts_utils
        self.prompts_utils_div = _prompts_utils

        _prompts_row.addWidget(_prompts_main, stretch=1)
        _prompts_row.addWidget(
            _prompts_utils,
            alignment=(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
            ),
        )

        _prf = QSettings("systemForge", "workflow-app")
        _active_prompt_filter = int(_prf.value("prompts/active_filter", 0))
        if not (0 <= _active_prompt_filter <= len(PROMPT_FILTER_CATEGORIES)):
            _active_prompt_filter = 0
        self._prompts_filter_bar.setCurrentIndex(_active_prompt_filter)
        self._prompts_filter_bar.currentChanged.connect(
            self._on_prompts_filter_changed
        )
        _rules_tab, self._subtab_rules_layout = _make_subtab("queue-subtab-insertions-rules")
        _cmd_tab, self._subtab_cmd_layout = _make_subtab("queue-subtab-insertions-cmd")
        _new_cmd_tab, self._subtab_new_cmd_layout = _make_subtab("queue-subtab-insertions-new-cmd")
        _auto_improove_tab, self._subtab_auto_improove_layout = _make_subtab("queue-subtab-insertions-auto-improove")
        _personal_tab, self._subtab_personal_layout = _make_subtab("queue-subtab-insertions-personal")

        # Aba 'Agentes' (personas): estrutura especial. Em vez de um flow
        # nu, ela tem uma barra de filtros por categoria (QTabBar) acima de um
        # flow unico de botoes. A 1a aba ("All") mostra todos; as demais filtram
        # por `persona_category`. O flow continua sendo _subtab_personas_layout
        # e so hospeda botoes de persona; os tres utilitarios (+ / gear / update)
        # vivem na div `queue-subtab-insertions-personas-utils` (coluna direita da
        # row `output-toolbar-agentes`) e
        # nunca sao filtrados. Ver _on_personas_filter_changed.
        #
        # 2026-07-27: deixou de ser sub-aba do `queue-subtabs-insertions` e
        # virou a QUARTA pagina do `output-toolbar-section-stack` (botao
        # `output-toolbar-section-agentes` do seletor). O testid do widget nao
        # muda com a promocao (regra D1) — so muda quem e o pai, e o MainWindow
        # o consome via o atributo publico `personas_content`.
        _personas_tab = QWidget()
        _personas_tab.setProperty("testid", "queue-subtab-insertions-personas")
        _personas_outer = QVBoxLayout(_personas_tab)
        _personas_outer.setContentsMargins(0, 0, 0, 0)
        _personas_outer.setSpacing(3)

        self._personas_filter_bar = QTabBar()
        self._personas_filter_bar.setProperty("testid", "queue-personas-filter-bar")
        self._personas_filter_bar.setExpanding(False)
        self._personas_filter_bar.setDrawBase(False)
        self._personas_filter_bar.setUsesScrollButtons(True)
        self._personas_filter_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._personas_filter_bar.setStyleSheet(
            "QTabBar { background: transparent; }"
            "QTabBar::tab { background: #27272A; color: #A1A1AA;"
            "  border: none; border-radius: 3px;"
            "  padding: 3px 9px; font-size: 9px; font-weight: 700;"
            "  letter-spacing: 0.4px; margin-right: 3px; }"
            "QTabBar::tab:selected { background: #8B5CF6; color: #FAFAFA; }"
            "QTabBar::tab:hover:!selected { background: #3F3F46; color: #D4D4D8; }"
        )
        self._personas_filter_bar.addTab(PERSONA_FILTER_ALL_LABEL)
        for _cat in PERSONA_FILTER_CATEGORIES:
            self._personas_filter_bar.addTab(_cat)
        _personas_outer.addWidget(self._personas_filter_bar)

        _personas_flow_host = QWidget()
        self._subtab_personas_layout = ResponsiveButtonFlowLayout(
            _personas_flow_host, spacing=4, v_spacing=1, max_lines=None
        )
        self._subtab_personas_layout.setContentsMargins(0, 2, 0, 2)
        # Mesma cadeia do PROMPTS: sem hfw, `output-toolbar-agentes` e medida
        # pelo sizeHint de 360px do flow de personas.
        enable_height_for_width(_personas_flow_host)
        enable_height_for_width(_personas_tab)
        _personas_outer.addWidget(_personas_flow_host, stretch=1)

        # Div dos utilitarios (2026-07-27): os tres botoes 1:1 que nao sao
        # personas (`+` create, gear de config e update) saem do flow e passam a
        # viver AQUI, numa div propria. Coluna vertical com size policy Fixed nos
        # dois eixos: a div ocupa exatamente a largura de um botao (mais as
        # margens) e a altura dos tres empilhados, nunca a faixa inteira da aba.
        #
        # 2026-07-27 (2a rodada): deixou de ser o ultimo item EMPILHADO dentro de
        # `queue-subtab-insertions-personas` e passou a ser a coluna DIREITA da
        # row `output-toolbar-agentes`, montada pelo MainWindow. Aqui a div nasce
        # sem parent (mesmo precedente de `insertions_bar`) e e exposta via o
        # atributo publico `personas_utils_div`; o testid nao muda com a mudanca
        # de pai (regra D1).
        _personas_utils = QWidget()
        _personas_utils.setObjectName("PersonasUtilsColumn")
        _personas_utils.setProperty("testid", "queue-subtab-insertions-personas-utils")
        _personas_utils.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _personas_utils.setStyleSheet(
            "QWidget#PersonasUtilsColumn { background-color: #1E1E21;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        _personas_utils.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._subtab_personas_utils_layout = QVBoxLayout(_personas_utils)
        self._subtab_personas_utils_layout.setContentsMargins(4, 4, 4, 4)
        self._subtab_personas_utils_layout.setSpacing(4)
        self._subtab_personas_utils_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetFixedSize
        )
        # O divisor horizontal que separava a div do flow saiu junto: em row a
        # separacao e espacial (colunas distintas), nao precisa de linha.
        self._personas_utils_div = _personas_utils
        #: Consumido pelo MainWindow como a coluna direita de
        #: `output-toolbar-agentes` (nasce sem parent, como `insertions_bar`).
        self.personas_utils_div = _personas_utils

        # Restaura o filtro ativo da sessao anterior; persiste ao trocar. O
        # filtro real so tem efeito apos o MainWindow popular os botoes — por
        # isso populate_personas_subtab/add_persona_buttons re-aplicam o filtro.
        _pf = QSettings("systemForge", "workflow-app")
        _active_filter = int(_pf.value("personas/active_filter", 0))
        if not (0 <= _active_filter <= len(PERSONA_FILTER_CATEGORIES)):
            _active_filter = 0
        self._personas_filter_bar.setCurrentIndex(_active_filter)
        self._personas_filter_bar.currentChanged.connect(
            self._on_personas_filter_changed
        )

        self._insertions_subtabs.addTab(_paths_tab, "PATHS")
        self._insertions_subtabs.addTab(_prompts_tab, "PROMPTS")
        self._insertions_subtabs.addTab(_rules_tab, "RULES")
        self._insertions_subtabs.addTab(_cmd_tab, "CMD")
        self._insertions_subtabs.addTab(_new_cmd_tab, "NEW CMD")
        self._insertions_subtabs.addTab(_auto_improove_tab, "AUTO IMPROOVE")
        self._insertions_subtabs.addTab(_personal_tab, "PERSONAL")
        # 'Agentes' NAO e mais sub-aba daqui: virou pagina 3 do
        # `output-toolbar-section-stack` (ver personas_content abaixo).

        # Restaurar sub-aba ativa da sessão anterior; persistir ao mudar.
        # Refactor 2026-05-19: sub-aba "cmd & mcp" deletada (botoes migraram para
        # output-toolbar-mcp). Indice antigo 1 (mcps) cai em prompts agora;
        # antigos 2/3 viram 1/2. Clamp para faixa nova [0,2].
        # 2026-06-02: 4a sub-aba "CMD" (comandos avulsos) re-adicionada apos RULES;
        # clamp passa a [0,3].
        # 2026-06-03: 5a sub-aba "PERSONAS" adicionada apos CMD; clamp passa a [0,4].
        # 2026-06-03: 6a sub-aba "AUTO IMPROOVE" e 7a "PERSONAL" adicionadas; clamp [0,6].
        # 2026-07-27: 'Agentes' promovida a secao do header; restavam 6 sub-abas
        # (PATHS..PERSONAL) e o clamp voltava para [0,5]. Um indice 6 persistido
        # por sessao antiga caia em PATHS.
        # 2026-08-20: 7a sub-aba "NEW CMD" adicionada ao lado de CMD; clamp
        # passa a [0,6]. Se o indice persistido vier sem essa aba (>=4),
        # desloca uma posicao para preservar PATHS/PROMPTS/RULES/CMD.
        _stg = QSettings("systemForge", "workflow-app")
        _active_subtab = int(_stg.value("insertions/active_subtab", 0))
        if _active_subtab >= 4:
            _active_subtab += 1
        if not (0 <= _active_subtab < 7):
            _active_subtab = 0
        self._insertions_subtabs.setCurrentIndex(_active_subtab)
        self._insertions_subtabs.currentChanged.connect(
            lambda idx: QSettings("systemForge", "workflow-app").setValue(
                "insertions/active_subtab", idx
            )
        )
        # O QStackedLayout interno do QTabWidget dimensiona pelo MAXIMO entre as
        # 7 sub-abas: PATHS (1 linha) herdava a altura de PROMPTS (5 linhas) e o
        # pane sobrava vazio. `_sync_insertions_subtabs_height` poe um teto na
        # altura real da sub-aba ATIVA. Resize/LayoutRequest (populate, filtro,
        # resize da janela) chegam pelo eventFilter.
        self._insertions_subtabs.currentChanged.connect(
            lambda _idx: self._sync_insertions_subtabs_height()
        )
        self._insertions_subtabs.installEventFilter(self)

        _ti_layout.addWidget(self._insertions_subtabs)

        # terminal_insertions_content NAO entra no header_layout — MainWindow
        # coloca em output-toolbar-center, hoje pagina 1 do stack do header.
        # Fora de `_sec_contents` desde I3.3: o acordeao das tres secoes nao
        # controla mais a visibilidade dele, quem controla e o
        # `output-toolbar-section-selector`.
        self.insertions_content = terminal_insertions_content

        # personas_content (2026-07-27): a aba 'Agentes' segue o mesmo contrato
        # de insertions_content — construida aqui, posicionada pelo MainWindow
        # como pagina 3 do `output-toolbar-section-stack`, fora de
        # `_sec_contents` (quem controla a visibilidade e o seletor de secoes).
        self.personas_content = _personas_tab

        # Default: LOOPs active (index 1)
        self._active_section = 1
        self._apply_section_styles()

        # Exposed so MainWindow can place it as a sibling of output-toolbar.
        self.header_widget = header

        # Play bar — big play button
        _PLAY_ROW_TOP_HEIGHT = 32
        _ACTIONS_ROW_HEIGHT = 28
        _PLAY_ROW_BOTTOM_HEIGHT = 32
        # queue-div-llm-routing (_llm_box) deixou de morar na play bar: passou a
        # ser reparenteado para a linha 1 da OutputToolbar do MainWindow (slot
        # antes ocupado por output-toolbar-progress-boxes). As secoes agora sao
        # verticais (Main LLM / Parallel Worker / MCP Flags / MCP / brainstorm),
        # empilhadas uma sobre a outra; dentro de cada secao label e inputs ficam
        # em row.
        _PLAY_BAR_VERTICAL_MARGINS = 10
        _PLAY_BAR_SPACING = 4
        _PLAY_BAR_HEIGHT = (
            _PLAY_ROW_TOP_HEIGHT
            + _PLAY_ROW_BOTTOM_HEIGHT
            + _ACTIONS_ROW_HEIGHT
            + _PLAY_BAR_VERTICAL_MARGINS
            + (_PLAY_BAR_SPACING * 2)
        )
        self._play_bar = QWidget()
        self._play_bar.setStyleSheet(
            "background-color: #1C1C1F; border-bottom: 1px solid #3F3F46;"
        )
        self._play_bar.setFixedHeight(_PLAY_BAR_HEIGHT)
        pl = QVBoxLayout(self._play_bar)
        pl.setContentsMargins(8, 5, 8, 5)
        pl.setSpacing(4)

        play_row_top = QHBoxLayout()
        play_row_top.setContentsMargins(0, 0, 0, 0)
        play_row_top.setSpacing(8)
        pl.addLayout(play_row_top)

        # "Rodar próximo" — botão dominante da play bar (primeira posição,
        # verde #16A34A, stretch=7). Executa o proximo item pendente da fila e
        # para. Funciona em qualquer item (auto ou interactive). Diferente do
        # _btn_next ("Continuar: X") que aparece SO em pause de interactive.
        self._play_btn = QPushButton("▶  Rodar próximo")
        self._play_btn.setProperty("testid", "queue-btn-play-next")
        self._play_btn.setFixedHeight(_PLAY_ROW_TOP_HEIGHT)
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
        # de UI (data-testid). Duas linhas:
        #   Linha 1: apenas queue-btn-play-next
        #   Linha 2: autocast-btn + schedule-autocast-btn + main-command-queue-auto-loop-btn
        self._play_btn_container = QWidget()
        self._play_btn_container.setProperty("testid", "queue-btn-play-next-container")
        _play_btn_container_layout = QVBoxLayout(self._play_btn_container)
        _play_btn_container_layout.setContentsMargins(0, 0, 0, 0)
        _play_btn_container_layout.setSpacing(4)
        _play_btn_container_layout.addWidget(self._play_btn)

        # Linha 2: autocast + schedule + auto-loop
        self._play_row_bottom = QHBoxLayout()
        self._play_row_bottom.setContentsMargins(0, 0, 0, 0)
        self._play_row_bottom.setSpacing(4)
        _play_btn_container_layout.addLayout(self._play_row_bottom)

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
        # Linha 2 do queue-btn-play-next-container: autocast + schedule + auto-loop
        self._play_row_bottom.addLayout(self._ac_sched_layout, stretch=1)

        # LLM routing: one container with the main session selector and
        # optional worker preference toggles used by [Rodar proximo].
        # Reparenteado pelo MainWindow para a linha 1 da OutputToolbar (layout
        # legado) ou para a aba LLM Config (SF_LLM_CONFIG_V2="1"); por isso e
        # exposto como self._llm_box.
        #
        # A orientacao depende do kill-switch (item 017, C-04):
        # - flag OFF: coluna. As tres secoes (Main LLM | Parallel Worker | Flag)
        #   ficam empilhadas, separadas por divisores HLine. A div mora na
        #   top-row, ao lado do selector, onde so ha largura para uma coluna.
        # - flag ON: linha. Instance, Main, Parallel e Flag ficam lado a lado,
        #   separadas por divisores VLine. A div mora dentro da aba LLM Routing,
        #   que tem a largura inteira do header e um teto de altura (R-18).
        # Em ambos os casos, nas duas primeiras secoes o label fica em cima dos
        # inputs; em Flag o label divide a linha com os checkboxes.
        from workflow_app.config import llm_config_v2_enabled as _llm_v2_on
        from workflow_app.config.feature_flags import (
            instance_group_route_aware_enabled as _instance_group_in_routing,
        )

        _llm_box_horizontal = _llm_v2_on()
        _llm_box = QWidget()
        self._llm_box = _llm_box
        _llm_box.setProperty("testid", "queue-div-llm-routing")
        _llm_box.setStyleSheet(
            "QWidget { background-color: #1C1C1F; border: 1px solid #3F3F46;"
            "  border-radius: 5px; }"
        )
        # spacing 6 entre secoes (o de dentro de cada secao e 2), para o par
        # label+controles ler como um bloco so.
        _llm_layout = (
            QHBoxLayout(_llm_box) if _llm_box_horizontal else QVBoxLayout(_llm_box)
        )
        _llm_layout.setContentsMargins(8, 4, 8, 4)
        _llm_layout.setSpacing(6)
        self._llm_layout = _llm_layout

        # Mesma aparencia dos inputs de output-mcp-provider-radio-input e
        # type-selector-radio-input: fonte 11px/700, indicador 12px, unchecked
        # #18181B com borda #52525B, checked ambar #FBBF24, hover #FDE68A.
        # Radios ficam circulares (radius 6px); checkboxes mantem o quadrado
        # (radius 3px) com o mesmo esquema de cor.
        _control_qss = (
            "QRadioButton, QCheckBox { color: #FAFAFA; font-size: 11px;"
            "  font-weight: 700; background: transparent; border: none;"
            "  padding: 0; }"
            "QRadioButton::indicator, QCheckBox::indicator { width: 12px;"
            "  height: 12px; }"
            "QRadioButton::indicator:unchecked, QCheckBox::indicator:unchecked {"
            "  background-color: #18181B; border: 1px solid #52525B; }"
            "QRadioButton::indicator:unchecked { border-radius: 6px; }"
            "QCheckBox::indicator:unchecked { border-radius: 3px; }"
            "QRadioButton::indicator:checked, QCheckBox::indicator:checked {"
            "  background-color: #FBBF24; border: 1px solid #FBBF24; }"
            "QRadioButton::indicator:checked { border-radius: 6px; }"
            "QCheckBox::indicator:checked { border-radius: 3px; }"
            "QRadioButton::indicator:hover, QCheckBox::indicator:hover {"
            "  border-color: #FDE68A; }"
        )
        # 11px iguala os controles (_control_qss): com o label em cima e os
        # inputs embaixo, 9px lia como legenda solta. A distincao entre label e
        # controle passa a ser so de cor (#A1A1AA vs #FAFAFA).
        # `text-transform` saiu daqui: Qt Style Sheets nao implementa a
        # propriedade, entao ela nunca teve efeito. Quem quiser caixa-alta tem
        # de escrever a string do QLabel ja em caixa-alta.
        _section_label_qss = (
            "QLabel { color: #A1A1AA; font-size: 11px; font-weight: 700;"
            "  background: transparent; border: none; }"
        )
        def _make_llm_divider() -> QFrame:
            """Divisor fino entre secoes do _llm_box.

            Segue a orientacao do `_llm_layout`: HLine de 1px de altura na
            coluna legada, VLine de 1px de largura na linha da aba LLM Config.
            """
            line = QFrame()
            line.setFrameShadow(QFrame.Shadow.Plain)
            line.setStyleSheet("color: #3F3F46; background: #3F3F46; border: none;")
            if _llm_box_horizontal:
                line.setFrameShape(QFrame.Shape.VLine)
                line.setFixedWidth(1)
            else:
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFixedHeight(1)
            return line

        self._make_llm_divider = _make_llm_divider

        # Na aba expandida, os aliases formam a primeira coluna independente.
        # O widget real pertence ao MetricsBar e e reparenteado pelo MainWindow
        # depois que ambos os componentes existem. No modo legado, o destino
        # historico continua sendo queue-div-main-llm.
        self.instance_buttons_section = None
        if _llm_box_horizontal and _instance_group_in_routing():
            _instance_section = QWidget()
            _instance_section.setProperty("testid", "queue-div-instance-buttons")
            _instance_section.setStyleSheet("background: transparent; border: none;")
            _instance_section.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Preferred,
            )
            _instance_layout = QVBoxLayout(_instance_section)
            _instance_layout.setContentsMargins(0, 0, 0, 0)
            _instance_layout.setSpacing(0)
            self.instance_buttons_section = _instance_section
            _llm_layout.addWidget(_instance_section)
            _llm_layout.addWidget(_make_llm_divider())

        _main_section = QWidget()
        # Exposto para preservar o destino route-aware do modo legado. Na aba
        # expandida, instance-group vive na coluna dedicada criada acima.
        self.main_llm_section = _main_section
        _main_section.setProperty("testid", "queue-div-main-llm")
        _main_section.setStyleSheet("background: transparent; border: none;")
        if _llm_box_horizontal:
            _main_section.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Preferred,
            )
        # Layout em coluna: label em cima, inputs (radios) embaixo. spacing 2
        # deixa o gap label-controle menor que o gap entre secoes (_llm_layout
        # usa 6), agrupando cada par visualmente.
        _main_layout = QVBoxLayout(_main_section)
        _main_layout.setContentsMargins(0, 0, 0, 0)
        _main_layout.setSpacing(2)
        _main_label = QLabel("Main LLM:")
        _main_label.setStyleSheet(_section_label_qss)
        _main_options = QWidget()
        _main_options.setStyleSheet("background: transparent; border: none;")
        _main_options_layout = (
            QGridLayout(_main_options)
            if _llm_box_horizontal
            else QHBoxLayout(_main_options)
        )
        _main_options_layout.setContentsMargins(0, 0, 0, 0)
        if _llm_box_horizontal:
            _main_options_layout.setHorizontalSpacing(7)
            _main_options_layout.setVerticalSpacing(2)
        else:
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
        self._main_qwen_radio = QRadioButton("qwen")
        self._main_qwen_radio.setProperty("testid", "queue-radio-main-qwen")
        self._main_mimo_radio = QRadioButton("mimo")
        self._main_mimo_radio.setProperty("testid", "queue-radio-main-mimo")
        self._main_grok_radio = QRadioButton("grok")
        self._main_grok_radio.setProperty("testid", "queue-radio-main-grok")
        # Radios de VARIANTE (opus/sonnet/kimi-k3) NAO entram em
        # `queue-div-main-llm`: esta div escolhe o CLI do terminal, nao a
        # capacidade de raciocinio. As variantes vivem em `queue-div-flag`.
        # Os widgets continuam existindo (testids C6) mas ficam ocultos e
        # fora do layout, para persistencia antiga cair na family.
        self._main_opus_radio = QRadioButton("opus")
        self._main_opus_radio.setProperty("testid", "queue-radio-main-opus")
        self._main_sonnet_radio = QRadioButton("sonnet")
        self._main_sonnet_radio.setProperty("testid", "queue-radio-main-sonnet")
        self._main_kimi_k3_radio = QRadioButton("kimi-k3")
        self._main_kimi_k3_radio.setProperty("testid", "queue-radio-main-kimi-k3")
        self._main_llm_group = QButtonGroup(self)
        self._main_llm_group.setExclusive(True)
        # Layout expandido: CLIs de terminal em duas colunas.
        # Fora da aba, o layout legado continua horizontal.
        _main_grid_positions = {
            self._main_claude_radio: (0, 0),
            self._main_codex_radio: (0, 1),
            self._main_kimi_radio: (1, 0),
            self._main_grok_radio: (1, 1),
            self._main_qwen_radio: (2, 0),
            self._main_mimo_radio: (2, 1),
        }
        for _btn in (
            self._main_claude_radio,
            self._main_codex_radio,
            self._main_kimi_radio,
            self._main_qwen_radio,
            self._main_mimo_radio,
            self._main_grok_radio,
        ):
            _btn.setStyleSheet(_control_qss)
            self._main_llm_group.addButton(_btn)
            if _llm_box_horizontal:
                _row, _column = _main_grid_positions[_btn]
                _main_options_layout.addWidget(_btn, _row, _column)
            else:
                _main_options_layout.addWidget(_btn)
        for _variant_btn in (
            self._main_opus_radio,
            self._main_sonnet_radio,
            self._main_kimi_k3_radio,
        ):
            _variant_btn.setStyleSheet(_control_qss)
            self._main_llm_group.addButton(_variant_btn)
            _variant_btn.setVisible(False)
        # ST006: kill-switch — qwen radio visivel somente quando llm_config_v2
        # esta ligado. Ausente ou off = oculto.
        # Item 026: kill-switch — grok radio visivel somente quando
        # SF_GROK_SPIKE esta ligado (D-41/C-58: nada de Grok publico antes do
        # spike). Ausente ou off = oculto.
        # MiMo (2026-10-02, D3): radio Main e worker T2 ficam sob o switch
        # proprio do roster MiMo, lido pelo atributo do modulo
        # (`_feature_flags.mimo_v1_enabled()`), ponto unico de monkeypatch.
        from workflow_app.config import feature_flags as _feature_flags
        from workflow_app.config.feature_flags import (
            grok_spike_enabled,
            main_providers_v2_enabled,
            parallel_workers_v2_enabled,
        )

        # Intencao de visibilidade por slug. `isVisible()` NAO serve como
        # oraculo aqui: durante o __init__ nenhum widget foi mostrado ainda,
        # entao ele retorna False ate para os radios habilitados — era isso que
        # tornava a restauracao do Main persistido (abaixo) inalcancavel.
        # Item 004 (C6): os 3 radios de variante passaram a ser gated.
        # Item 005 (C26): o gate foi MOVIDO do global `SF_LLM_CONFIG_V2` para o
        # kill-switch dedicado `SF_MAIN_PROVIDERS_V2`, que decide o roster de
        # radios Main. Regime legado (flag ausente) = os 3 radios de variante
        # (`opus`, `sonnet`, `kimi-k3`) mais o provider adicional `qwen` ficam
        # ocultos, e o eixo Main volta a ser exatamente `claude`/`codex`/`kimi`.
        # `grok` NAO entra neste switch: continua exclusivamente sob
        # `SF_GROK_SPIKE`, para nao criar conjuncao de dois switches (C7).
        # `mimo` fica sob o switch proprio do roster MiMo, sem conjuncao com
        # `SF_MAIN_PROVIDERS_V2` (C7): opt-in, congelado no boot, fail-closed.
        _main_radio_visible = {
            "claude": True,
            "codex": True,
            "kimi": True,
            "qwen": main_providers_v2_enabled(),
            "grok": grok_spike_enabled(),
            "mimo": _feature_flags.mimo_v1_enabled(),
            # Variantes de raciocinio sairam do Main LLM (sempre ocultas).
            "opus": False,
            "sonnet": False,
            "kimi-k3": False,
        }
        if not _main_radio_visible["qwen"]:
            self._main_qwen_radio.setVisible(False)
        if not _main_radio_visible["grok"]:
            self._main_grok_radio.setVisible(False)
        if not _main_radio_visible["mimo"]:
            self._main_mimo_radio.setVisible(False)
        # Intencao de boot por slug, lida depois do __init__: `isVisible()`
        # nao serve (ver acima) e um radio oculto continua marcavel por codigo.
        # Consumida pela guarda do mimo no resolver e no handler do radio.
        self._main_radio_visible = _main_radio_visible
        self._main_opus_radio.setVisible(False)
        self._main_sonnet_radio.setVisible(False)
        self._main_kimi_k3_radio.setVisible(False)
        # Item 018: persistencia do radio Main LLM via QSettings.
        # Restaura a selecao da sessao anterior (default: claude).
        _main_stg = QSettings("systemForge", "workflow-app")
        _saved_main = _main_stg.value("main_llm/selected", "claude")
        _main_radio_map = {
            "claude": self._main_claude_radio,
            "codex": self._main_codex_radio,
            "kimi": self._main_kimi_radio,
            "qwen": self._main_qwen_radio,
            "mimo": self._main_mimo_radio,
            "grok": self._main_grok_radio,
            "opus": self._main_opus_radio,
            "sonnet": self._main_sonnet_radio,
            "kimi-k3": self._main_kimi_k3_radio,
        }
        self._main_radio_map = _main_radio_map
        _saved_slug = str(_saved_main or "claude").strip().lower()
        if _saved_slug not in _main_radio_map:
            _saved_slug = "claude"
        # Variantes de raciocinio persistidas (opus/sonnet/kimi-k3) caem na
        # family: o Main LLM agora e so o CLI do terminal.
        _saved_slug = {
            "opus": "claude",
            "sonnet": "claude",
            "kimi-k3": "kimi",
        }.get(_saved_slug, _saved_slug)
        # Slug persistido cujo radio esta oculto por kill-switch (ex.: sessao
        # anterior rodou com SF_GROK_SPIKE=1 e esta nao) volta para claude em
        # vez de marcar um radio invisivel — Main marcado tem que ser Main que
        # o operador consegue ver e trocar.
        if not _main_radio_visible.get(_saved_slug, False):
            _saved_slug = "claude"
        _main_radio_map[_saved_slug].setChecked(True)
        self._main_llm_group.buttonClicked.connect(
            lambda btn: self._persist_main_llm_selection()
        )
        # O stretch horizontal permanece apenas no modo legado. Na aba, a
        # grade tem exatamente duas colunas de controles.
        if not _llm_box_horizontal:
            _main_options_layout.addStretch(1)
        _main_layout.addWidget(_main_label)
        _main_layout.addWidget(_main_options)
        _llm_layout.addWidget(_main_section)

        _worker_section = QWidget()
        _worker_section.setProperty("testid", "queue-div-parallel-worker")
        _worker_section.setStyleSheet("background: transparent; border: none;")
        if _llm_box_horizontal:
            _worker_section.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Preferred,
            )
        # Layout em coluna: label em cima, inputs (checkboxes) embaixo.
        _worker_layout = QVBoxLayout(_worker_section)
        _worker_layout.setContentsMargins(0, 0, 0, 0)
        _worker_layout.setSpacing(2)
        _worker_label = QLabel("Parallel Worker:")
        _worker_label.setStyleSheet(_section_label_qss)
        _worker_options = QWidget()
        _worker_options.setStyleSheet("background: transparent; border: none;")
        _worker_options_layout = QHBoxLayout(_worker_options)
        _worker_options_layout.setContentsMargins(0, 0, 0, 0)
        _worker_options_layout.setSpacing(12 if _llm_box_horizontal else 8)
        self._use_kimi_chk = QCheckBox("kimi")
        self._use_kimi_chk.setProperty("testid", "queue-chk-use-kimi")
        self._use_kimi_chk.setToolTip(
            "Quando marcado, [Rodar proximo] usa Kimi para items compativeis."
        )
        self._use_qwen_chk = QCheckBox("qwen")
        self._use_qwen_chk.setProperty("testid", "queue-chk-use-qwen")
        self._use_qwen_chk.setToolTip(
            "Quando marcado, [Rodar proximo] usa Qwen para items compativeis."
        )
        self._use_mimo_chk = QCheckBox("mimo")
        self._use_mimo_chk.setProperty("testid", "queue-chk-use-mimo")
        self._use_mimo_chk.setToolTip(
            "Quando marcado, [Rodar proximo] usa MiMo para items compativeis "
            "(T2; exclusivo com kimi e qwen, PW-01; MiMo vence Kimi)."
        )
        self._use_codex_chk = QCheckBox("codex")
        self._use_codex_chk.setProperty("testid", "queue-chk-use-codex")
        self._use_codex_chk.setToolTip(
            "Quando marcado, [Rodar proximo] envia ao T3 Codex apenas os itens com seta azul "
            "(worker-elegiveis). Itens so com seta verde seguem no T1."
        )
        self._use_grok_chk = QCheckBox("grok")
        self._use_grok_chk.setProperty("testid", "queue-chk-use-grok")
        self._use_grok_chk.setToolTip(
            "Quando marcado, [Rodar proximo] usa Grok para items compativeis."
        )
        for _btn in (
            self._use_kimi_chk,
            self._use_qwen_chk,
            self._use_mimo_chk,
            self._use_codex_chk,
            self._use_grok_chk,
        ):
            _btn.setStyleSheet(_control_qss)
        # Item 005 (C26): roster de workers paralelos sob kill-switch dedicado
        # `SF_PARALLEL_WORKERS_V2` (boot-frozen, fail-closed). Ausente/off = o
        # roster legado de 2 workers (`kimi` no T2, `codex` no T3); "1" expoe os
        # 4 em dois pares exclusivos. Este switch decide QUEM aparece — a
        # exclusividade PW-01 (um worker por terminal) continua enforced nos
        # handlers `_on_use_*_toggled` e nao e duplicada aqui.
        # Os checkboxes ocultos sao desmarcados explicitamente: todos os
        # consumidores a jusante leem `isChecked()` sem consultar visibilidade,
        # entao worker invisivel marcado vazaria para a resolucao de terminal.
        # `_worker_visible` guarda a intencao de boot por worker (isVisible()
        # nao serve no __init__); restore, ocupacao e o handler do mimo leem
        # daqui, entao um worker oculto nunca volta marcado por codigo.
        self._worker_visible = {
            "kimi": True,
            "qwen": parallel_workers_v2_enabled(),
            "mimo": _feature_flags.mimo_v1_enabled(),
            "codex": True,
            "grok": parallel_workers_v2_enabled(),
        }
        if not parallel_workers_v2_enabled():
            for _hidden_worker in (self._use_qwen_chk, self._use_grok_chk):
                _hidden_worker.setChecked(False)
                _hidden_worker.setVisible(False)
        # `mimo` tem switch proprio do roster MiMo (C7): nao depende de
        # `SF_PARALLEL_WORKERS_V2`, entao o hide+uncheck fica fora do laco acima.
        if not self._worker_visible["mimo"]:
            self._use_mimo_chk.setChecked(False)
            self._use_mimo_chk.setVisible(False)
        # Split visual T2/T3 (source.md:1191 + §10.2): na aba, cada terminal e
        # uma coluna interna com seus workers empilhados, repetindo a
        # leitura em grade do Main LLM. O modo legado preserva a linha unica.
        _sub_label_qss = (
            "QLabel { color: #71717A; font-size: 10px; font-weight: 700;"
            "  background: transparent; border: none; }"
        )
        for _sub_testid, _sub_text, _sub_btns in (
            (
                "queue-div-parallel-t2",
                "T2:",
                (self._use_kimi_chk, self._use_qwen_chk, self._use_mimo_chk),
            ),
            ("queue-div-parallel-t3", "T3:", (self._use_codex_chk, self._use_grok_chk)),
        ):
            _sub = QWidget()
            _sub.setProperty("testid", _sub_testid)
            _sub.setStyleSheet("background: transparent; border: none;")
            _sub_layout = (
                QVBoxLayout(_sub)
                if _llm_box_horizontal
                else QHBoxLayout(_sub)
            )
            _sub_layout.setContentsMargins(0, 0, 0, 0)
            _sub_layout.setSpacing(2 if _llm_box_horizontal else 6)
            _sub_lbl = QLabel(_sub_text)
            _sub_lbl.setStyleSheet(_sub_label_qss)
            _sub_layout.addWidget(_sub_lbl)
            for _btn in _sub_btns:
                _sub_layout.addWidget(_btn)
            # Os dois sub-grupos sobrevivem ao regime legado: cada terminal
            # mantem ao menos um worker visivel (T2 kimi, T3 codex), entao os
            # rotulos continuam verdadeiros e os testids
            # `queue-div-parallel-t2`/`-t3` permanecem estaveis nos dois regimes.
            _worker_options_layout.addWidget(_sub)
        _worker_options_layout.addStretch(1)
        _worker_layout.addWidget(_worker_label)
        _worker_layout.addWidget(_worker_options)
        _llm_layout.addWidget(_make_llm_divider())
        _llm_layout.addWidget(_worker_section)

        # Terceira secao (item 004): flags MCP intra-comando (--kimi/--codex)
        # anexadas ao label dos itens T1 (Claude). Espelha o padrao do worker;
        # eixo-flag distinto do eixo-worker (queue-chk-use-*). Estado inicial
        # desmarcado (nenhum sufixo por default). As exclusoes I2 (/clear,
        # /model, /effort, local-action) e o strip a worker/Desabilitado (I3)
        # vivem no helper puro render_with_mcp_flags; o handler apenas le os
        # checkboxes e re-renderiza os labels afetados.
        _flag_section = QWidget()
        _flag_section.setProperty("testid", "queue-div-flag")
        _flag_section.setStyleSheet("background: transparent; border: none;")
        # Na aba, Flag segue o mesmo formato das demais colunas: titulo em cima
        # e controles abaixo. O modo legado continua horizontal.
        _flag_layout = (
            QVBoxLayout(_flag_section)
            if _llm_box_horizontal
            else QHBoxLayout(_flag_section)
        )
        _flag_layout.setContentsMargins(0, 0, 0, 0)
        _flag_layout.setSpacing(2 if _llm_box_horizontal else 8)
        # Item 021: sob a flag, quem preenche `queue-div-flag` e o FlagsPanel
        # (thinking/execution). Aliasando os checkboxes do painel como
        # `_flag_<slug>_chk`, o plumbing (`_refresh_flag_checkboxes_state`,
        # `_active_mcp_flags_from_local`, C-43/C-57) vale para todos os
        # literais sem duplicar controle.
        self._flags_panel = None
        if _llm_box_horizontal:
            from workflow_app.config.llm_flags import _FLAG_CANONICAL_ORDER
            from workflow_app.llm_config.flags_panel import FlagsPanel

            _panel = FlagsPanel(
                main_llm_resolver=self._resolve_interactive_main_llm,
                show_label=False,
            )
            self._flags_panel = _panel
            for _flag in _FLAG_CANONICAL_ORDER:
                _chk = _panel.checkbox(_flag)
                if _chk is None:
                    continue
                _chk.setStyleSheet(_control_qss)
                setattr(
                    self,
                    f"_flag_{_flag.lstrip('-').replace('-', '_')}_chk",
                    _chk,
                )
            _panel.flags_changed.connect(self._on_flags_panel_changed)
            # Titulos de coluna (thinking / execution) vivem no FlagsPanel;
            # o label unico "Flag" sobraria como terceira faixa.
            _flag_layout.addWidget(_panel)
        else:
            _flag_label = QLabel("Flag")
            _flag_label.setStyleSheet(_section_label_qss)
            _flag_options = QWidget()
            _flag_options.setStyleSheet("background: transparent; border: none;")
            _flag_options_layout = QHBoxLayout(_flag_options)
            _flag_options_layout.setContentsMargins(0, 0, 0, 0)
            _flag_options_layout.setSpacing(8)
            self._flag_mimo_chk = QCheckBox("--mimo")
            self._flag_mimo_chk.setProperty("testid", "queue-chk-flag-mimo")
            self._flag_mimo_chk.setToolTip(
                "Quando marcado, anexa --mimo ao label dos itens T1 (Claude). "
                "Lane T2: vence o --kimi quando os dois estao marcados. "
                "Nunca afeta /clear, /model, /effort, local-action nem itens worker."
            )
            self._flag_kimi_chk = QCheckBox("--kimi")
            self._flag_kimi_chk.setProperty("testid", "queue-chk-flag-kimi")
            self._flag_kimi_chk.setToolTip(
                "Quando marcado, anexa --kimi ao label dos itens T1 (Claude). "
                "Lane T2: se --mimo tambem estiver marcado, a MiMo vence e o "
                "--kimi sai do payload. "
                "Nunca afeta /clear, /model, /effort, local-action nem itens worker."
            )
            self._flag_codex_chk = QCheckBox("--codex")
            self._flag_codex_chk.setProperty("testid", "queue-chk-flag-codex")
            self._flag_codex_chk.setToolTip(
                "Quando marcado, anexa --codex ao label dos itens T1 (Claude). "
                "Nunca afeta /clear, /model, /effort, local-action nem itens worker."
            )
            for _btn in (
                self._flag_mimo_chk,
                self._flag_kimi_chk,
                self._flag_codex_chk,
            ):
                _btn.setStyleSheet(_control_qss)
                _btn.toggled.connect(self._on_flag_toggled)
                _flag_options_layout.addWidget(_btn)
            _flag_options_layout.addStretch(1)
            _flag_layout.addWidget(_flag_label)
            _flag_layout.addWidget(_flag_options)
        _llm_layout.addWidget(_make_llm_divider())
        _llm_layout.addWidget(_flag_section)
        # _llm_box NAO entra na play bar: o MainWindow o reparenteia para a
        # aba LLM Routing. O MainWindow anexa somente o instance-group na
        # primeira coluna reservada.

        # Chip 22x22 da row queue-template-label (copy + clear). Estilo unico
        # para os dois: 1:1, so o icone muda.
        self._copy_commands_btn = QPushButton()
        self._copy_commands_btn.setProperty(
            "testid", "queue-btn-copy-commands"
        )
        _copy_icon = _load_tinted_svg_icon(
            _ASSETS_DIR / "copy.svg", "#FAFAFA"
        )
        _apply_template_icon_chip(self._copy_commands_btn, _copy_icon, "⎘")
        self._copy_commands_btn.setToolTip(
            "Copiar todos os comandos renderizados, uma linha por comando"
        )
        self._copy_commands_btn.clicked.connect(self._on_copy_rendered_commands)

        # Main Kimi preserves the old slash-to-skill conversion and hides the
        # per-item blue arrows while active. Worker toggles keep the legacy
        # play-next preference path.
        self._force_kimi_chk.toggled.connect(self._on_force_kimi_toggled)
        self._use_kimi_chk.toggled.connect(self._on_use_kimi_toggled)
        self._use_qwen_chk.toggled.connect(self._on_use_qwen_toggled)
        self._use_mimo_chk.toggled.connect(self._on_use_mimo_toggled)
        self._main_codex_radio.toggled.connect(self._on_main_codex_toggled)
        self._main_claude_radio.toggled.connect(self._on_main_claude_toggled)
        self._main_qwen_radio.toggled.connect(self._on_main_qwen_toggled)
        self._main_grok_radio.toggled.connect(self._on_main_grok_toggled)
        self._main_mimo_radio.toggled.connect(self._on_main_mimo_toggled)
        # Item 004 (C6): radios de variante. Emitem a FAMILY no
        # `main_llm_changed` — ver `_on_main_variant_toggled` (decisao ST006).
        self._main_opus_radio.toggled.connect(self._on_main_opus_toggled)
        self._main_sonnet_radio.toggled.connect(self._on_main_sonnet_toggled)
        self._main_kimi_k3_radio.toggled.connect(self._on_main_kimi_k3_toggled)
        self._use_codex_chk.toggled.connect(self._on_use_codex_toggled)
        self._use_grok_chk.toggled.connect(self._on_use_grok_toggled)

        # Item 020: restaurar selecao de worker da sessao anterior.
        self._restore_worker_selection()
        # ST003.3 (C24, belt-and-suspenders): hoje a MetricsBar e construida
        # ANTES do CommandQueueWidget (main_window.py), entao o emit do restore
        # acima chega. O singleShot(0) - idioma ja usado neste arquivo - garante
        # que uma reordenacao futura da construcao nao volte a deixar a
        # MetricsBar cega EM SILENCIO. Emissao dupla e inofensiva.
        QTimer.singleShot(0, self._emit_worker_occupancy)
        # Mesma armadilha, agora no eixo Main: o restore do radio (QSettings)
        # roda ANTES dos `toggled.connect` logo acima, entao ele NAO emite
        # `main_llm_changed`. Sem este emit de boot, um Main Kimi/Qwen
        # restaurado ficava invisivel para a MetricsBar (prompt de
        # auto-recuperacao com a persona errada) e para as OutputPanels
        # (piso do Enter submissor curto demais para a TUI do gemini-cli).
        QTimer.singleShot(0, self._emit_main_llm_boot)

        main_layout.addWidget(self._play_bar)

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
        # Label ocupa o restante da largura; copy/clear entram no canto
        # direito (Clear e reparentado pelo MainWindow apos a criacao).
        _trl.addWidget(self._template_label, stretch=1)
        _trl.addWidget(
            self._copy_commands_btn, 0, Qt.AlignmentFlag.AlignVCenter
        )

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
        signal_bus.listener_authoritative_idle.connect(
            self._on_listener_authoritative_idle
        )
        signal_bus.terminal_output_observed.connect(
            self._on_terminal_output_observed
        )
        # Task 24: pausa/retomada da fila viram evento. Os dois sinais ja
        # existiam e nao tinham consumidor de telemetria — a fila parava e o
        # corpus nao registrava nada, entao `paused` era indistinguivel de
        # abandono na classificacao historica.
        signal_bus.pipeline_paused.connect(self._on_queue_paused_observed)
        signal_bus.pipeline_resumed.connect(self._on_queue_resumed_observed)
        self._btn_next.clicked.connect(self._on_btn_next_clicked)

    # ─────────────────────────────────────────────── Auto-loop (fila) ── #

    #: Canal do listener que rearma o auto-loop (T1 = terminal interactive).
    _AUTO_LOOP_CHANNEL: str = "interactive"

    def set_auto_loop_enabled(self, enabled: bool) -> None:
        """Liga/desliga o auto-loop da fila (dono do estado: o botao do
        main_window, que chama este setter no `toggled`)."""
        self._auto_loop_enabled = bool(enabled)

    def is_auto_loop_enabled(self) -> bool:
        return self._auto_loop_enabled

    def _on_listener_authoritative_idle(self, channel: str) -> None:
        """T1 chegou ao verde autoritativo — rearma a fila se o auto-loop
        estiver ligado.

        Só o canal `interactive` conta PARA O REARME: os workers (T2/T3) ficam
        verdes em cadencia propria e rearmar por eles reabriria a fila no meio
        de um dispatch Claude ainda em voo.

        Task 24(a): o DESFECHO, ao contrario do rearme, vale para os tres
        canais e nao depende do auto-loop estar ligado. Um item despachado ao
        Worker Codex (T3) conclui quando o T3 fica verde, e o operador que roda
        a fila no passo a passo produz exatamente o mesmo fato que o autocast
        produz. Amarrar a telemetria ao toggle faria o corpus mudar de forma
        conforme um botao de UI — e todo run manual apareceria como abandono.
        Por isso o fechamento vem ANTES das duas guardas."""
        self._close_pending_item_outcome(failed=False, channel=channel)
        if not self._auto_loop_enabled:
            return
        if channel != self._AUTO_LOOP_CHANNEL:
            return
        self.rearm_sent_items()

    def rearm_sent_items(self) -> bool:
        """Volta TODA seta unica ambar (item enviado) para verde/pendente.

        Gate de ciclo completo: no-op enquanto existir qualquer item pendente.
        Sem esse gate, o rearme dispararia ao fim de CADA item e o
        `_find_next_pending` do autocast voltaria eternamente ao item 1
        (starvation do resto da fila). Com ele, a fila roda 1..N e so recomeca
        do 1 quando o ultimo item termina.

        Retorna True quando rearmou de fato (usado pelos testes)."""
        if not self._items:
            return False
        if any(item.is_pending_run() for item in self._items):
            return False
        self._suspend_progress_metrics = True
        try:
            for item in self._items:
                # is_pending_run() == `not _is_sent`: aqui todos estao enviados.
                item.reset_to_pending()
        finally:
            self._suspend_progress_metrics = False
        self._emit_progress_metrics()
        signal_bus.toast_requested.emit(
            f"auto-loop: fila rearmada ({len(self._items)} itens de volta a pendente).",
            "info",
        )
        return True

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

    # Painel canonico do T2 e o OutputPanel `terminal-workspace` (main_window):
    # so ele tem `_shell` (PTY). O testid `terminal-workspace-output` e do
    # TerminalCanvas interno, que nao tem `_shell` — a sonda devolveria None
    # sempre (item 007).
    _T2_OUTPUT_TESTID = "terminal-workspace"
    _T3_OUTPUT_TESTID = "terminal-codex-output"
    _GROK_CLI_BASENAME = "grok"

    def _find_t2_output_panel(self) -> QWidget | None:
        """Locate the canonical T2 widget (`terminal-workspace`).

        Returns None when this queue is not embedded in MainWindow (unit
        tests) or when T2 has not been built yet.
        """
        win = self.window()
        if win is None:
            return None
        for child in win.findChildren(QWidget):
            if child.property("testid") == self._T2_OUTPUT_TESTID:
                return child
        return None

    def _t2_pty_hosts_cli(self, cli: str) -> bool | None:
        """Whether the T2 PTY session currently hosts ``cli``.

        Returns:
          - True when a descendant process of the T2 PTY matches ``cli``
          - False when the PTY is inspectable but ``cli`` is not running
            (zsh idle, outro binario)
          - None when there is no PTY to inspect (headless / unit tests).
            Chamadores decidem o que fazer com None: o guard MiMo bloqueia
            (fail-closed, item 007); o guard Grok libera (fail-open legado).
        """
        panel = self._find_t2_output_panel()
        if panel is None:
            return None
        shell = getattr(panel, "_shell", None)
        if shell is None:
            return None
        pid_fn = getattr(shell, "pid", None)
        pid = pid_fn() if callable(pid_fn) else None
        if pid is None:
            return None
        hosts_fn = getattr(shell, "hosts_cli", None)
        if not callable(hosts_fn):
            return None
        try:
            return bool(hosts_fn(cli))
        except OSError:
            return None

    def _find_t3_output_panel(self) -> QWidget | None:
        """Locate the canonical T3 widget (`terminal-codex-output`).

        Returns None when this queue is not embedded in MainWindow (unit
        tests) or when T3 has not been built yet.
        """
        win = self.window()
        if win is None:
            return None
        for child in win.findChildren(QWidget):
            if child.property("testid") == self._T3_OUTPUT_TESTID:
                return child
        return None

    def _t3_pty_hosts_cli(self, cli: str) -> bool | None:
        """Whether the T3 PTY session currently hosts ``cli``.

        Returns:
          - True when a descendant process of the T3 PTY matches ``cli``
          - False when the PTY is inspectable but ``cli`` is not running
            (zsh idle, leftover Codex REPL, other binary)
          - None when there is no PTY to inspect (headless / unit tests).
            Callers then fall back to occupancy; occupancy alone is NOT
            enough in production.
        """
        panel = self._find_t3_output_panel()
        if panel is None:
            return None
        shell = getattr(panel, "_shell", None)
        if shell is None:
            return None
        pid_fn = getattr(shell, "pid", None)
        pid = pid_fn() if callable(pid_fn) else None
        if pid is None:
            return None
        hosts_fn = getattr(shell, "hosts_cli", None)
        if not callable(hosts_fn):
            return None
        try:
            return bool(hosts_fn(cli))
        except OSError:
            return None

    def _ensure_t2_mimo_host(self) -> bool:
        """Gate Worker T2 MiMo: ocupacao viva + processo `mimo` no PTY do T2.

        FAIL-CLOSED (item 007): diferente do guard Grok
        (`_ensure_t3_grok_host`, que libera quando o PTY nao e inspecionavel),
        so libera o envio quando a ocupacao viva do T2 e `mimo` E o PTY do T2
        hospeda de fato um processo `mimo` (`PersistentShell.hosts_cli('mimo')`).
        Qualquer outro estado (ocupacao diferente, processo ausente, PTY nao
        inspecionavel, headless) bloqueia com toast de `warning` e devolve False
        (Zero Silencio). NUNCA ha `return True` no ramo None da sonda.
        """
        if self._resolve_worker_occupancy()[0] != "mimo":
            signal_bus.toast_requested.emit(
                "Worker MiMo (T2): o T2 nao esta ocupado pela MiMo - envio bloqueado.",
                "warning",
            )
            return False
        hosted = self._t2_pty_hosts_cli("mimo")
        if hosted is False:
            signal_bus.toast_requested.emit(
                "Worker MiMo (T2): processo mimo ausente no terminal T2 (rode mimod no T2) - envio bloqueado.",
                "warning",
            )
            return False
        if hosted is None:
            # Fail-closed: PTY nao inspecionavel NUNCA libera envio.
            signal_bus.toast_requested.emit(
                "Worker MiMo (T2): terminal T2 nao inspecionavel (sem PTY) - envio bloqueado.",
                "warning",
            )
            return False
        return True

    def _ensure_t3_grok_host(self) -> bool:
        """Gate Worker T3 Grok: widget + occupancy + PTY process.

        Toasts the specific reason and returns False on abort (Zero Silencio).
        """
        if not self._codex_t3_available:
            signal_bus.toast_requested.emit(
                "Worker Grok (T3): terminal-codex-output nao esta pronto — "
                "dispatch abortado.",
                "warning",
            )
            return False
        _t2, t3 = self._resolve_worker_occupancy()
        if t3 != "grok":
            signal_bus.toast_requested.emit(
                "Worker Grok (T3): o xterm nao hospeda o CLI grok "
                "(queue-chk-use-grok desmarcado) — dispatch abortado.",
                "warning",
            )
            return False
        hosted = self._t3_pty_hosts_cli(self._GROK_CLI_BASENAME)
        if hosted is False:
            signal_bus.toast_requested.emit(
                "Worker Grok (T3): o PTY nao hospeda o processo grok "
                "(ocupacao marcada, CLI ausente) — dispatch abortado.",
                "warning",
            )
            return False
        return True

    def _on_autocast_abort_requested(self, cause: str, channel: str) -> None:
        """Desliga o botao autocast quando um listener entra em estado failed.

        Emitido por MetricsBar._on_terminal_force_failed apos receber
        terminal_force_failed (pattern matcher, exit-code watcher ou
        wf-notify.sh --status failure). Ver workflow-app-listeners.md §3.

        Task 24: desligar o autocast por falha de listener PARA a fila — nada
        mais avanca sozinho. Sem marcar isso, o loop ficaria com pendentes e
        zero evento, que e exatamente a assinatura de abandono. A trava de
        `_on_queue_paused_observed` cuida do caso em que um `pipeline_paused`
        chega logo em seguida pelo mesmo incidente.

        Task 24(a): este e o unico desfecho NEGATIVO autoritativo do app. O
        item em voo no canal que falhou termina em `item_failed`, e o evento
        sai ANTES do `queue_paused` para que a ordem no corpus conte a historia
        na ordem em que ela aconteceu: o item falhou, e por isso a fila parou.
        Invertido, a pausa pareceria decisao do operador.
        """
        self._close_pending_item_outcome(failed=True, channel=channel, cause=cause)
        if self._btn_autocast.isChecked():
            self._btn_autocast.setChecked(False)
            self._on_queue_paused_observed()

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
        """Create a content widget with a responsive flow of styled buttons.

        Refactor 07-27: o QGridLayout de `cols` colunas fixas foi substituido
        pelo `ResponsiveButtonFlowLayout` em regime livre (`max_lines=None`).
        Cada botao fica com a largura do proprio label e a quantidade por
        linha acompanha a largura da janela. `cols` e mantido apenas por
        compatibilidade de assinatura (ignorado).
        """
        content = QWidget()
        content.setStyleSheet("background-color: #27272A;")
        flow = ResponsiveButtonFlowLayout(
            content, spacing=3, v_spacing=1, max_lines=None
        )
        flow.setContentsMargins(5, 4, 5, 5)
        # Sem hfw o `output-toolbar-left` mede esta secao pelo sizeHint de
        # referencia (360px) do flow: varias linhas a mais do que a largura
        # real do header exige, tudo virando faixa vazia sob os botoes.
        enable_height_for_width(content)
        for item in buttons:
            if isinstance(item, QWidget):
                flow.addWidget(item)
            else:
                label, tooltip, callback, testid = item
                btn = QPushButton(label)
                btn.setToolTip(tooltip)
                btn.setStyleSheet(_SECTION_BTN_STYLE)
                if testid:
                    btn.setProperty("testid", testid)
                btn.clicked.connect(callback)
                flow.addWidget(btn)
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

    #: testid do utilitario da aba PROMPTS. Nao e um prompt filtravel e vive
    #: na div `queue-subtab-insertions-prompts-utils`, em coluna, encostada no
    #: canto direito da sub-aba.
    _PROMPTS_UTIL_TESTIDS = (
        "toolbar-prompts-config-gear",
    )

    def populate_prompts_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'prompts': botoes de prompt construídos a partir de arquivos .md.

        O gear `toolbar-prompts-config-gear` sai do flow e vai para a div
        `queue-subtab-insertions-prompts-utils` no canto direito.
        """
        prompts = [w for w in widgets if not self._is_prompts_util(w)]
        utils = [w for w in widgets if self._is_prompts_util(w)]
        self._populate_subtab(self._subtab_prompts_layout, prompts)
        self._populate_prompts_utils(utils)
        self._apply_prompt_filter()

    def _is_prompts_util(self, widget: QWidget) -> bool:
        """True para o gear de config da aba PROMPTS."""
        tid = widget.property("testid")
        return isinstance(tid, str) and tid in self._PROMPTS_UTIL_TESTIDS

    def _populate_prompts_utils(self, widgets: list[QWidget]) -> None:
        """Reconstroi a coluna de utilitarios (gear) da aba PROMPTS."""
        layout = self._subtab_prompts_utils_layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for w in widgets:
            layout.addWidget(w, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.invalidate()

    def populate_rules_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'rules': dcp-list, cmd-list, terminal, listeners, indicators, add-rules."""
        self._populate_subtab(self._subtab_rules_layout, widgets)

    def populate_cmd_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'CMD': comandos avulsos que colam um slash-command no terminal."""
        self._populate_subtab(self._subtab_cmd_layout, widgets)

    def populate_new_cmd_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'NEW CMD': comandos de modernizacao e atualizacao de templates."""
        self._populate_subtab(self._subtab_new_cmd_layout, widgets)

    def populate_auto_improove_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'AUTO IMPROOVE': comandos de melhoria continua de assets SystemForge."""
        self._populate_subtab(self._subtab_auto_improove_layout, widgets)

    def populate_personal_subtab(self, widgets: list[QWidget]) -> None:
        """Sub-aba 'PERSONAL': comandos pessoais (curriculum, imbound, mkt)."""
        self._populate_subtab(self._subtab_personal_layout, widgets)

    # ── Filtro por tipo da sub-aba 'PROMPTS' ───────────────────────────────── #

    def _prompt_filter_category(self) -> str:
        """Tipo selecionado na barra de filtros de prompts (ou 'All')."""
        bar = getattr(self, "_prompts_filter_bar", None)
        if bar is None:
            return PROMPT_FILTER_ALL_LABEL
        idx = bar.currentIndex()
        if 1 <= idx <= len(PROMPT_FILTER_CATEGORIES):
            return PROMPT_FILTER_CATEGORIES[idx - 1]
        return PROMPT_FILTER_ALL_LABEL

    def _apply_prompt_filter(self) -> None:
        """Mostra prompts do tipo selecionado e preserva utilitarios visiveis."""
        layout = getattr(self, "_subtab_prompts_layout", None)
        if layout is None:
            return
        category = self._prompt_filter_category()
        show_all = category == PROMPT_FILTER_ALL_LABEL
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is None:
                continue
            cat = widget.property("prompt_category")
            if not isinstance(cat, str) or not cat:
                widget.setVisible(True)
                continue
            widget.setVisible(show_all or cat == category)
        layout.invalidate()

    def _on_prompts_filter_changed(self, index: int) -> None:
        """Persiste o filtro ativo da sub-aba PROMPTS e re-filtra o flow."""
        QSettings("systemForge", "workflow-app").setValue(
            "prompts/active_filter", int(index)
        )
        self._apply_prompt_filter()

    #: testids dos tres botoes utilitarios da aba 'Agentes'. Nao sao personas
    #: (prefixo plural `personas`), nunca entram no flow filtravel e vivem na
    #: div `queue-subtab-insertions-personas-utils`, em coluna, encostada no
    #: canto direito da row `output-toolbar-agentes`.
    _PERSONAS_UTIL_TESTIDS = (
        "queue-btn-personas-create",
        "queue-btn-personas-config",
        "queue-btn-personas-update",
    )

    def populate_personas_subtab(self, widgets: list[QWidget]) -> None:
        """Aba 'Agentes': botoes que colam o path de arquivos .md de personas.

        `widgets` chega do MainWindow como uma lista unica (create + personas +
        gear + update, nessa ordem). O particionamento acontece AQUI: os tres
        utilitarios vao para a div em coluna da direita da row 'Agentes' e o resto para o
        flow responsivo filtravel.

        Re-aplica o filtro de categoria ativo apos popular (os botoes recem
        criados respeitam a aba de filtro selecionada).
        """
        personas = [w for w in widgets if not self._is_personas_util(w)]
        utils = [w for w in widgets if self._is_personas_util(w)]
        self._populate_subtab(self._subtab_personas_layout, personas)
        self._populate_personas_utils(utils)
        self._apply_persona_filter()

    def _is_personas_util(self, widget: QWidget) -> bool:
        """True para os tres botoes utilitarios da aba 'Agentes'."""
        tid = widget.property("testid")
        return isinstance(tid, str) and tid in self._PERSONAS_UTIL_TESTIDS

    def _populate_personas_utils(self, widgets: list[QWidget]) -> None:
        """Reconstroi a coluna de utilitarios (+, gear, update) da aba 'Agentes'.

        Idempotente: limpa a div antes de reanexar, entao repopular a aba (ex.
        apos o modal de configuracao, que recria os botoes) nunca duplica
        widget nem deixa orfao na coluna.
        """
        layout = self._subtab_personas_utils_layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for w in widgets:
            layout.addWidget(w)
        layout.invalidate()

    # ── Filtro por categoria da sub-aba 'Agentes' ────────────────────────────── #

    def _persona_filter_category(self) -> str:
        """Categoria selecionada na barra de filtros (ou 'All' no indice 0)."""
        bar = getattr(self, "_personas_filter_bar", None)
        if bar is None:
            return PERSONA_FILTER_ALL_LABEL
        idx = bar.currentIndex()
        if 1 <= idx <= len(PERSONA_FILTER_CATEGORIES):
            return PERSONA_FILTER_CATEGORIES[idx - 1]
        return PERSONA_FILTER_ALL_LABEL

    def _apply_persona_filter(self) -> None:
        """Mostra apenas os botoes de persona da categoria selecionada.

        'All' (indice 0) mostra todos. Os botoes utilitarios (create, config
        gear e update — testids `queue-btn-personas-*`, sem o sufixo de slug)
        NUNCA sao filtrados: desde 2026-07-27 nem sequer moram neste flow, e
        sim na div `queue-subtab-insertions-personas-utils`. O guard por testid
        continua aqui como rede para qualquer utilitario que volte ao flow. O
        flow responsivo ja ignora widgets ocultos (_visible_items), entao a
        relayout acontece sozinha.
        """
        layout = getattr(self, "_subtab_personas_layout", None)
        if layout is None:
            return
        category = self._persona_filter_category()
        show_all = category == PERSONA_FILTER_ALL_LABEL
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is None:
                continue
            tid = widget.property("testid")
            # So botoes de persona (queue-btn-persona-<slug>) sao filtraveis. Os
            # utilitarios sao `queue-btn-personas-create/config/update`
            # (char 18 == 's', nao casa o prefixo com hifen) e ficam sempre visiveis.
            is_persona = isinstance(tid, str) and tid.startswith("queue-btn-persona-")
            if not is_persona:
                widget.setVisible(True)
                continue
            cat = widget.property("persona_category")
            widget.setVisible(show_all or cat == category)
        layout.invalidate()

    def _on_personas_filter_changed(self, index: int) -> None:
        """Slot da barra de filtros: persiste a aba ativa e re-filtra o flow."""
        QSettings("systemForge", "workflow-app").setValue(
            "personas/active_filter", int(index)
        )
        self._apply_persona_filter()

    def add_persona_buttons(
        self, new_btns: list[QWidget], keep_last: QWidget | None = None,
    ) -> None:
        """Anexa botoes de persona ao flow da aba 'Agentes' ao vivo.

        Diferente de populate_personas_subtab (que limpa e repopula), este
        metodo PRESERVA os botoes existentes e apenas acrescenta os novos —
        usado pelo botao 'update' (queue-btn-personas-update).

        `keep_last` (o botao 'update' 1:1) e legado: desde 2026-07-27 os tres
        utilitarios vivem fora do flow, na div
        `queue-subtab-insertions-personas-utils`, entao nao ha o que destacar
        e reanexar — as personas novas ja entram no fim do flow. O parametro
        continua aceito (e o destaque continua defensivo) para o caso de um
        utilitario reaparecer no flow.
        """
        layout = self._subtab_personas_layout
        # Destaca config+update (utilitarios finais) para reanexar apos as
        # personas novas, preservando ordem relativa config < update e o
        # create no indice 0.
        trailing: list[QWidget] = []
        if keep_last is not None:
            # Coleta utilitarios finais (config gear, se presente, e update)
            # de tras para frente ate o primeiro persona/create.
            for i in range(layout.count() - 1, -1, -1):
                item = layout.itemAt(i)
                w = item.widget() if item is not None else None
                if w is None:
                    continue
                tid = w.property("testid")
                if w is keep_last or (
                    isinstance(tid, str)
                    and tid in {"queue-btn-personas-update", "queue-btn-personas-config"}
                ):
                    layout.takeAt(i)
                    trailing.insert(0, w)
                else:
                    break
        for w in new_btns:
            layout.addWidget(w)
        for w in trailing:
            layout.addWidget(w)
        layout.invalidate()
        # Personas recem-adicionadas pelo botao 'update' respeitam o filtro ativo.
        self._apply_persona_filter()

    def attach_tab_bar_extras(self, *extras: QWidget) -> None:
        """Anexa widgets ao bloco de inserções, apos a aba Inserções.

        API generica sem chamador ativo desde
        07-27-workflow-app-header-toggles-llm-unico (I1.1/I1.2): o unico
        consumidor era o bloco `terminal-route-toggles`, dissolvido quando
        cada checkbox de rota migrou para o header do seu terminal
        (`terminal-route-t1/t2/t3`). Mantida porque nao guarda estado e
        continua sendo o ponto de extensao do `insertions_bar`.
        """
        for w in extras:
            self._insertions_bar_layout.addWidget(w)

    def attach_subtab_corner_widget(self, widget: QWidget) -> None:
        """Posiciona um widget no canto direito da tab bar das sub-abas de
        inserções (PATHS/PROMPTS/RULES), na mesma row dos botoes de aba.

        Sem chamador ativo: o `toolbar-prompts-config-gear` vive na div
        `queue-subtab-insertions-prompts-utils` (canto da sub-aba PROMPTS).
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

        Chamado pelo main_window apos populate_* terminar. O conteudo de
        inserções (`insertions_content`) NAO e rastreado (regra P4); desde
        I3.3 ele nem faz parte de `_sec_contents`.
        """
        if not hasattr(self, "_sec_contents"):
            return
        if not hasattr(self, "_tracked_section_indices"):
            self._tracked_section_indices = (0, 1, 2)
        tracked = self._tracked_section_indices
        for idx in tracked:
            if idx < len(self._sec_contents):
                self._sec_contents[idx].installEventFilter(self)

    def _sync_insertions_subtabs_height(self) -> None:
        """Encolhe `queue-subtabs-insertions` ate a altura real da sub-aba ATIVA.

        Motivacao (2026-07-27): o `QStackedLayout` interno de um QTabWidget
        dimensiona pelo maximo entre TODAS as paginas. Com PROMPTS (5 linhas de
        botoes) no mesmo stack, PATHS e PERSONAL (1 linha) recebiam ~83px a mais
        do que precisam e o pane ficava vazio abaixo dos botoes.

        A altura verdadeira vem do `heightForWidth` do flow da sub-aba ativa
        (exato na largura efetiva, ao contrario do `sizeHint()`, que usa uma
        largura de referencia fixa de 360px) e vira `maximumHeight` do
        QTabWidget. `QWidgetItem` respeita `maximumHeight` tanto em
        `heightForWidth` quanto em `sizeHint`, entao o teto propaga sozinho
        para `output-toolbar-center` e para o stack do header.

        Nunca corta abaixo do `minimumSizeHint` da pagina, e libera o teto
        quando nao ha `heightForWidth` utilizavel (pagina ainda sem geometria).
        """
        tabs = getattr(self, "_insertions_subtabs", None)
        if tabs is None:
            return
        page = tabs.currentWidget()
        if page is None:
            return

        def _apply(limit: int) -> None:
            if tabs.maximumHeight() == limit:
                return
            tabs.setMaximumHeight(limit)
            # Na troca de sub-aba a pagina recem-exposta ainda carrega a
            # geometria antiga, entao esta medida pode estar um ciclo atras.
            # Re-mede no proximo turno do event loop; a guarda de igualdade
            # acima encerra a cadeia assim que o valor estabiliza.
            QTimer.singleShot(0, self._sync_insertions_subtabs_height)

        page_layout = page.layout()
        width = page.width() or tabs.width()
        content = -1
        if page_layout is not None and width > 0 and page_layout.hasHeightForWidth():
            content = page_layout.heightForWidth(width)
        if content <= 0:
            _apply(_QT_WIDGET_SIZE_MAX)
            return
        content = max(content, page.minimumSizeHint().height())

        # Cromo = tab bar + moldura do pane. Medido pela geometria viva (exato,
        # e estavel quando o teto ja foi aplicado, porque encolhe os dois
        # juntos); o sizeHint da tab bar cobre o boot, antes do 1o layout.
        chrome = tabs.height() - page.height()
        if chrome <= 0:
            chrome = tabs.tabBar().sizeHint().height()
        _apply(chrome + content)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        # NOTA (2026-07-27): este metodo esta SOMBREADO — a classe redefine
        # `eventFilter` mais abaixo (drag-and-drop do items_container) e a
        # ultima definicao vence. O rastreio P4 abaixo nunca roda. Bug
        # pre-existente, deixado como esta para nao mudar comportamento fora do
        # escopo desta correcao de layout; o hook de altura das sub-abas foi
        # instalado na definicao viva.
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
        "/credentials:create", "/credentials:env-creation",
        "/credentials:execute --mode write", "/credentials:test-user",
        "/credentials:verify", "/data-test-id",
        "/db-migration-create",
        "/delivery:sync-progress", "/dependency-audit", "/deploy-checklist",
        "/dev-bootstrap-create", "/docker-create",
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
        *,
        source: str = "matrix",
    ) -> bool:
        """Reject the emit when any CommandSpec carries a bare slash-name.

        Second-layer guard to prevent regression of the bare-name bug
        (loop 05-27-dcp-flow-structured-fix). Returns True when all spec
        names pass; False after surfacing a red popup and a toast. The popup
        body identifies the offender(s) so the operator can correlate with the
        producer of the queue.

        `source` seleciona a remediacao mostrada ao operador, porque os dois
        produtores de fila que passam por este guard NAO tem a mesma cura:

        - `"matrix"` (default): fila derivada de `DCP-COMMAND-MATRIX.json` /
          `SPECIFIC-FLOW.json`. A cura e regerar a matrix via [DCP Build].
        - `"disk"`: fila derivada direto do filesystem (`{wbs_root}/modules/`
          + `TASK-*.md`), como em [Build+Exec (modules)] e
          [Create+Exec All (modules)]. Esses botoes nao leem matrix nenhuma;
          mandar o operador rodar [DCP Build] aqui seria mandar reconstruir um
          artefato que nao participa da falha. A cura real e o proprio disco.
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
        if source == "disk":
            headline = (
                "Fila derivada do disco contem name bare (sem args/placeholders)."
            )
            window_title = "QUEUE_INVALID: name bare na fila derivada do disco"
            remediation = (
                "Emit ABORTADO (sem fallback). Esta fila NAO vem de\n"
                "DCP-COMMAND-MATRIX.json nem de SPECIFIC-FLOW.json. Rodar\n"
                "[DCP Build] nao corrige nada aqui. Confira o disco:\n"
                "  1. {wbs_root}/modules/ tem o module esperado?\n"
                "  2. O module tem TASK-<n>.md executavel (sem sufixo alfabetico)?\n"
                "  3. Rode [Modules (Creation)] se as TASK-*.md ainda nao existem."
            )
            log_prefix = "[build-execute-modules]"
            log_msg = (
                "%s guard pre-emit rejeitou fila de disco com %d name bare "
                "para modulo=%s: %s"
            )
        else:
            headline = "Matriz derivada contem name bare (sem args/placeholders)."
            window_title = "MATRIX_INVALID: name bare na fila derivada"
            remediation = (
                "DCP Execute ABORTADO (sem fallback). Regere a matrix via\n"
                "[DCP: Build Module Pipeline] e revalide com\n"
                "  python3 ai-forge/scripts/validate-dcp-matrix-canonical.py "
                "--matrix <DCP-COMMAND-MATRIX.json>"
            )
            log_prefix = "[DCP]"
            log_msg = (
                "%s guard pre-emit rejeitou matrix com %d name bare "
                "para modulo=%s: %s"
            )
        body = (
            f"{headline}\n\n"
            f"Modulo:    {cm_id}\n"
            f"Offenders: {joined}{suffix}\n\n"
            f"{remediation}"
        )
        logger.error(log_msg, log_prefix, len(offenders), cm_id, joined)
        try:
            from PySide6.QtWidgets import QMessageBox

            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(window_title)
            box.setText(body)
            box.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            box.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
            box.exec()
        except Exception as ui_exc:  # popup failed (headless/test) — keep toast
            logger.warning(
                "%s popup do guard de name bare falhou (%s); emitindo toast",
                log_prefix, ui_exc,
            )
            if source == "disk":
                toast = (
                    f"Fila de disco do module {cm_id} contem name bare "
                    f"({joined}). Emit ABORTADO."
                )
            else:
                toast = (
                    f"Matriz {cm_id} contem name bare ({joined}). "
                    f"DCP Execute ABORTADO."
                )
            signal_bus.toast_requested.emit(toast, "error")
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
        # Contrato do par kimi-pair: analyse recebe o COMANDO-ALVO (slash slug);
        # execute recebe o PATH DO RELATORIO em blacksmith/, nomeado pelo alvo
        # sanitizado (espelha slug_sanitized do produtor, ':' -> '_'). Passar o
        # spec (.md) para os dois e bug: analyse analisaria o arquivo errado e
        # execute consumiria um spec em vez do report. cmd_target_slash e
        # garantido nao-vazio pelo abort acima.
        kimi_report_path = (
            f"blacksmith/{cmd_target_slash.lstrip('/').replace(':', '_')}"
            "-kimi-pair-report.md"
        )
        commands.extend([
            "/clear",
            f"/cmd:kimi-pair-analyse --approved {cmd_target_slash}",
            f"/cmd:kimi-pair-execute --approved {kimi_report_path}",
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

        Requires the loop attachment to point at blacksmith/loop-archives/{slug}/_LOOP-CONFIG.json
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

        config = self._resolve_loop_attachment_config()
        if config is None:
            signal_bus.toast_requested.emit(
                "Nenhum loop anexado para daily-loop. Carregue um _LOOP-CONFIG.json "
                "no anexo loop (metrics-loop-pill) ou use o fallback de "
                "compatibilidade legado.",
                "warning",
            )
            return

        raw = config.raw if isinstance(config.raw, dict) else {}

        if raw.get("kind") != "daily-loop" or "daily_loop" not in raw:
            signal_bus.toast_requested.emit(
                "Anexo loop carregado nao e um _LOOP-CONFIG.json. "
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

        # Hint (nao autoridade): o workspace do project.json anexado so importa
        # quando o proprio loop declara workspace_drift_policy. O default do
        # loader e loop_wins — um project anexado NUNCA bloqueia a expansao da
        # fila (regressao 2026-07-27: default `block` travava o botao Loop
        # sempre que havia project em attachments-project-row).
        project_workspace_root: Path | None = None
        project_cfg = app_state.project_config
        if (
            project_cfg is not None
            and not (
                isinstance(project_cfg.raw, dict)
                and project_cfg.raw.get("kind") == "daily-loop"
            )
        ):
            workspace_raw = str(project_cfg.workspace_root or "").strip()
            if workspace_raw:
                workspace_path = Path(workspace_raw)
                project_workspace_root = (
                    workspace_path
                    if workspace_path.is_absolute()
                    else project_cfg.project_dir / workspace_path
                )

        try:
            specs = build_daily_loop_specs(
                raw,
                loop_root,
                project_workspace_root=project_workspace_root,
            )
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

    def _on_loop_clicked(self, simple: bool = False) -> None:
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

        Requires the loop attachment to point at the
        `_LOOP-CONFIG.json` of a `/loop`-flavoured pipeline (same V3 +
        kind: daily-loop schema as the legacy daily-loop).

        `simple` (2026-09-17, `queue-btn-loop-simple`): passthrough to
        `build_loop_specs(..., simple=True)`, which reduces each item's
        canonical block to `/loop:iteraction:create-task` +
        `/loop:iteraction:execute-task --simple-loop` + `/clear`. Same
        `_LOOP-CONFIG.json`/`progress.md` as the normal button — only the
        dispatched command strings differ — so this and `queue-btn-loop`
        can be alternated freely mid-loop (see the badge in
        `.claude/commands/loop/iteraction/execute-task.md`).
        """
        from PySide6.QtWidgets import QMessageBox

        from workflow_app.config.app_state import app_state
        from workflow_app.daily_loop import (
            DailyLoopConfigError,
            build_loop_specs,
            read_loop_resume_preview,
            read_review_blocked_sentinel,
        )

        config = self._resolve_loop_attachment_config()
        if config is None:
            signal_bus.toast_requested.emit(
                "Nenhum loop anexado para o botão Loop. Carregue um _LOOP-CONFIG.json "
                "no anexo loop (metrics-loop-pill) ou use o fallback de "
                "compatibilidade legado.",
                "warning",
            )
            return

        raw = config.raw if isinstance(config.raw, dict) else {}

        if raw.get("kind") != "daily-loop" or "daily_loop" not in raw:
            signal_bus.toast_requested.emit(
                "Anexo loop carregado nao e um _LOOP-CONFIG.json. "
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

        # Hint (nao autoridade): o workspace do project.json anexado so importa
        # quando o proprio loop declara workspace_drift_policy. O default do
        # loader e loop_wins — um project anexado NUNCA bloqueia a expansao da
        # fila (regressao 2026-07-27: default `block` travava o botao Loop
        # sempre que havia project em attachments-project-row).
        project_workspace_root: Path | None = None
        project_cfg = app_state.project_config
        if (
            project_cfg is not None
            and not (
                isinstance(project_cfg.raw, dict)
                and project_cfg.raw.get("kind") == "daily-loop"
            )
        ):
            workspace_raw = str(project_cfg.workspace_root or "").strip()
            if workspace_raw:
                workspace_path = Path(workspace_raw)
                project_workspace_root = (
                    workspace_path
                    if workspace_path.is_absolute()
                    else project_cfg.project_dir / workspace_path
                )

        slug = str(raw.get("daily_loop", {}).get("slug", "")) or "loop"

        # Task 16 (estudo 08-24): preview de retomada NO PROPRIO botao Loop.
        # Nenhum botao novo, nenhum `/loop:resume`: o mesmo clique que ja
        # retomava agora diz o que vai retomar ANTES de enfileirar. O preview
        # nao elege nada — PROGRESS.md continua a autoridade, lido aqui e
        # relido pelo loader na materializacao.
        preview = None
        try:
            preview = read_loop_resume_preview(raw, loop_root)
        except OSError as exc:
            self._record_loop_resume(slug, None, "read_error")
            signal_bus.toast_requested.emit(
                f"Erro ao ler PROGRESS.md: {exc}", "error"
            )
            return

        if preview is not None and preview.blocked:
            # Marcador fora de `[x] [ ] [!]`: aborta antes de montar fila. O
            # loader levantaria o mesmo erro adiante, mas sem os IDs — e o ID
            # e a unica parte acionavel da mensagem.
            self._record_loop_resume(slug, preview, "blocked_invalid_marker")
            signal_bus.toast_requested.emit(
                f"Loop {slug}: PROGRESS.md com marcador invalido — nada "
                f"enfileirado. {preview.invalid_detail()}. Marcadores "
                "canonicos: [x] done, [ ] pending, [!] failed.",
                "error",
            )
            return

        if preview is not None:
            logger.info(
                "[loop] resume preview %s: %s | %s",
                slug,
                preview.summary_line(),
                preview.ids_line(),
            )

        try:
            specs = build_loop_specs(
                raw,
                loop_root,
                project_workspace_root=project_workspace_root,
                simple=simple,
            )
        except DailyLoopConfigError as exc:
            self._record_loop_resume(slug, preview, "config_error")
            signal_bus.toast_requested.emit(f"Loop invalido: {exc}", "error")
            return
        except OSError as exc:
            self._record_loop_resume(slug, preview, "read_error")
            signal_bus.toast_requested.emit(f"Erro ao ler PROGRESS.md: {exc}", "error")
            return

        if not specs:
            self._record_loop_resume(slug, preview, "empty")
            concluido = (
                f" Estado: {preview.summary_line()}." if preview is not None else ""
            )
            signal_bus.toast_requested.emit(
                "PROGRESS.md sem itens pendentes — loop concluido."
                f"{concluido} "
                "Rode /daily-loop:review --slug X para o veredito final.",
                "info",
            )
            return
        # Count real items from buckets[*].items[*] — the legacy heuristic
        # `name.startswith("/daily-loop:do ")` only matched the fallback wrapper
        # shape and silently reported 0 for canonical post-/loop:integration
        # configs where commands are materialized inline.
        item_count = sum(
            len(b.get("items", []))
            for b in raw.get("daily_loop", {}).get("buckets", [])
        )
        logger.info("[loop] loading %s (%d items, %d specs)", slug, item_count, len(specs))

        if preview is not None:
            resumo = f"{preview.summary_line()} de {preview.total_count}"
        else:
            resumo = f"{item_count} itens"
        label_prefix = "Simple Loop" if simple else "Loop"
        self._template_label.setText(f"  \U0001f4cb  {label_prefix}: {slug} ({resumo})")
        self._template_label.setVisible(True)
        self._record_loop_resume(slug, preview, "materialized", specs=specs)
        self._maybe_auto_save(f"{label_prefix} {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_rocksmash_clicked(self) -> None:
        """Expand the active _LOOP-CONFIG.json into the /loop-rocksmash:* queue.

        Requires the loop attachment to point at a daily-loop
        _LOOP-CONFIG.json. Emits:
            1x /loop-rocksmash:prepare
            N quadruplas /loop-rocksmash:do + :review-done + :compare
                + :integrate (shape canonico B6; apenas items com
                kind=iteration, preparo/finalizacao sao ignorados)
            1x /loop-rocksmash:rename

        A iteracao e QUADRUPLA, nao par: `build_loop_rocksmash_specs` emite
        os quatro verbos por item e `assert_rocksmash_iteration_shape` os
        exige no config. O shape de 2 comandos so sobrevive atras do opt-in
        legado `daily_loop.rocksmash_legacy_two_step`. Snapshot da fila real:
        tests/snapshots/loop_anatomy/rocksmash_quadrupla.json.

        Directives /clear, /model, /effort sao auto-injetadas conforme
        bucket boundaries (espelha build_loop_specs).
        """
        from workflow_app.command_queue.loop_rocksmash_expander import (
            build_loop_rocksmash_specs,
        )
        from workflow_app.daily_loop import DailyLoopConfigError

        config = self._resolve_loop_attachment_config()
        if config is None:
            signal_bus.toast_requested.emit(
                "Nenhum loop anexado para Rocksmash. Carregue o _LOOP-CONFIG.json "
                "no anexo loop (metrics-loop-pill).",
                "warning",
            )
            return

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
        # Uma iteracao = uma quadrupla; contar os `:do` continua sendo a
        # forma certa de contar iteracoes, so o nome estava errado.
        iteration_count = sum(
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
            "[rocksmash] loading %s (%d iteracoes, %d specs, buckets=%s)",
            slug,
            iteration_count,
            len(specs),
            ",".join(bucket_ids) or "-",
        )

        self._template_label.setText(
            f"  \U0001f4cb  rocksmash: {slug} ({iteration_count} iteracoes)"
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
        pagina estatica HTML/CSS/JS ja hospedada na Hostinger ao backend OIDC
        central systemforge-dashboard / systemforgedashboard.com (loop de
        origem 06-03), injeta login OIDC funcional e deixa o site em producao.

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

    def _on_credentials_clicked(self) -> None:
        """Enfileira a pipeline de credenciais para o project.json carregado.

        Le `metrics-project-pill` (project.json) e passa `config.config_path`
        como `$1` aos 3 subcomandos. Gera e executa credenciais via
        /credentials:env-creation -> /credentials:create -> /credentials:execute,
        comunicando entre si por `.claude/projects/{slug}.credentials-state.json`
        em disco (nao via contexto de conversa), por isso `_inject_clears` poe um
        `/clear` entre cada um.

        Gate 1 (has_config): toast verboso pt-BR quando ausente, sugere o
        botao `queue-btn-json` (/project-json). Gate 2 (config_path): toast
        verboso pt-BR quando o config carregado nao expoe config_path.

        Sequencia enfileirada (tiens heterogeneos, sem GROUP_MAP):
          1. /credentials:env-creation <path>  (sonnet/low)
          2. /credentials:create <path>        (opus/high)
          3. /credentials:execute <path>       (sonnet/high)

        Todos os comandos sao roteados exclusivamente para Claude; nao ha
        entradas correspondentes em kimi_whitelist.py nem codex_whitelist.py.
        """
        from workflow_app.config.app_state import app_state
        from workflow_app.templates.quick_templates import _inject_clears

        # Gate 1: has_config — verbose pt-BR (feedback_workflow_app_gate_verbose)
        if not app_state.has_config or app_state.config is None:
            signal_bus.toast_requested.emit(
                "credentials requer project.json carregado na pill superior. "
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

        real_specs: list[CommandSpec] = [
            CommandSpec(
                name=f"/credentials:env-creation {path}",
                model=ModelName.SONNET,
                effort=EffortLevel.LOW,
                interaction_type=InteractionType.AUTO,
                position=1,
            ),
            CommandSpec(
                name=f"/credentials:create {path}",
                model=ModelName.OPUS,
                effort=EffortLevel.HIGH,
                interaction_type=InteractionType.AUTO,
                position=2,
            ),
            CommandSpec(
                name=f"/credentials:execute {path}",
                model=ModelName.SONNET,
                effort=EffortLevel.HIGH,
                interaction_type=InteractionType.AUTO,
                position=3,
            ),
        ]
        specs = _inject_clears(real_specs)

        slug = Path(path).stem
        logger.info(
            "[credentials] enqueued %d specs for project=%s",
            len(specs), slug,
        )
        self._template_label.setText(
            f"  \U0001f510  credentials: {slug} ({len(specs)} specs)"
        )
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"credentials {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_build_execute_modules_clicked(self) -> None:
        """Enfileira Build+Exec (5 comandos nucleares por task real, mais UM
        `/review-executed-module` por module com task) para TODOS os modules
        encontrados em disco sob `{wbs_root}/modules/`.

        Pre-condicoes (falha -> toast `warning` + return, nunca emit parcial):
        1. Projeto carregado (`app_state.has_config and app_state.config`).
        2. `wbs_root` resolvido via `_resolve_wbs_root(config)` existe em disco.
        3. `wbs_root/modules/` existe.

        Modules sem task executavel (`enumerate_module_tasks(...) == []`) sao
        pulados e logados; nenhum `/review-executed-module` orfao e emitido para
        eles. `_resolve_task_substitution` nunca recebe task vazia/None neste
        fluxo, pois o loop de tasks so roda apos o guard de lista vazia.
        """
        self._build_execute_modules(reduced=False)

    def _on_create_execute_all_modules_clicked(self) -> None:
        """Versao reduzida de Build+Exec: por task real, apenas `/create-task`
        e `/execute-task` (sem `/review-created-task` nem
        `/review-executed-task`), mais UM `/review-executed-module` por module
        com task, para TODOS os modules encontrados em disco sob
        `{wbs_root}/modules/`. Mesmas pre-condicoes de
        `_on_build_execute_modules_clicked`.
        """
        self._build_execute_modules(reduced=True)

    def _build_execute_modules(self, *, reduced: bool) -> None:
        from workflow_app.config.app_state import app_state

        if not (app_state.has_config and app_state.config):
            signal_bus.toast_requested.emit(
                "Carregue um projeto antes de usar Build+Exec.", "warning"
            )
            return

        config = app_state.config

        from workflow_app.dcp.specific_flow_handler import _resolve_wbs_root

        wbs_root = _resolve_wbs_root(config)
        if not Path(wbs_root).exists():
            signal_bus.toast_requested.emit(
                f"wbs_root nao encontrado: {wbs_root}.", "warning"
            )
            return

        modules_dir = Path(wbs_root) / "modules"
        if not modules_dir.is_dir():
            signal_bus.toast_requested.emit(
                f"Nenhum diretorio modules/ em {wbs_root}. Rode Modules primeiro.",
                "warning",
            )
            return

        from workflow_app.dcp.queue_derivation import (
            _module_path,
            _resolve_task_substitution,
            enumerate_modules_on_disk,
        )
        from workflow_app.dcp.task_enum import enumerate_module_tasks
        from workflow_app.templates.quick_templates import _inject_clears

        module_ids = enumerate_modules_on_disk(wbs_root)

        real_specs: list[CommandSpec] = []
        pos = 1
        cm_id: str | None = None

        for module_id in module_ids:
            module_dir = modules_dir / module_id
            task_names = enumerate_module_tasks(module_dir)
            if not task_names:
                logger.info(
                    "[build-execute-modules] module %s sem task executavel; pulado.",
                    module_id,
                )
                continue

            if cm_id is None:
                cm_id = module_id

            module_path = _module_path(module_id, Path(wbs_root))
            for task_name in task_names:
                task_arg = _resolve_task_substitution(task_name, module_path)
                real_specs.append(CommandSpec(
                    name=f"/create-task {task_arg}",
                    model=ModelName.OPUS,
                    effort=EffortLevel.HIGH,
                    interaction_type=InteractionType.AUTO,
                    position=pos,
                ))
                pos += 1
                if not reduced:
                    real_specs.append(CommandSpec(
                        name=f"/review-created-task {task_arg}",
                        model=ModelName.SONNET,
                        effort=EffortLevel.STANDARD,
                        interaction_type=InteractionType.AUTO,
                        position=pos,
                    ))
                    pos += 1
                real_specs.append(CommandSpec(
                    name=f"/execute-task {task_arg}",
                    model=ModelName.SONNET,
                    effort=EffortLevel.STANDARD,
                    interaction_type=InteractionType.AUTO,
                    position=pos,
                ))
                pos += 1
                if not reduced:
                    real_specs.append(CommandSpec(
                        name=f"/review-executed-task {task_arg}",
                        model=ModelName.SONNET,
                        effort=EffortLevel.STANDARD,
                        interaction_type=InteractionType.AUTO,
                        position=pos,
                    ))
                    pos += 1

            # --auto-close: com veredito APROVADO o review da baixa no module
            # (qa -> done) e avanca current_module, sem acao manual entre modules.
            real_specs.append(CommandSpec(
                name=f"/review-executed-module {module_path} --auto-close",
                model=ModelName.OPUS,
                effort=EffortLevel.HIGH,
                interaction_type=InteractionType.AUTO,
                position=pos,
            ))
            pos += 1

        if not real_specs:
            signal_bus.toast_requested.emit(
                "Nenhuma task executavel encontrada em nenhum module de "
                f"{wbs_root}/modules/. Nada para enfileirar.",
                "warning",
            )
            return

        specs = _inject_clears(real_specs)

        if not self._validate_no_bare_names(
            specs, cm_id or module_ids[0], source="disk"
        ):
            return

        tag = "create-execute-all" if reduced else "build-execute-modules"
        logger.info(
            "[%s] enqueued %d specs across %d module(s)",
            tag, len(specs), len(module_ids),
        )
        label = (
            "create+execute all modules"
            if reduced
            else "build+exec modules"
        )
        self._template_label.setText(
            f"  \U0001f4e6  {label}: ({len(specs)} specs)"
        )
        self._template_label.setVisible(True)
        self._maybe_auto_save(
            "Create+Execute All Modules" if reduced else "Build+Exec Modules"
        )
        signal_bus.pipeline_ready.emit(specs)

    def _usabilidade_gate_and_path(self) -> tuple[str, str] | None:
        """Gate compartilhado pelos dois handlers de Usabilidade.

        Retorna `(config_path, workspace_root)` quando ha project.json valido
        carregado na metrics-project-pill; emite o toast verbose pt-BR e retorna
        None quando o gate falha (sem project.json OU sem config_path). O
        `workspace_root` e DERIVADO do config (campo `workspace_root` resolvido
        pelo parser, com fallback para o diretorio do config); nunca o
        placeholder literal `{workspace_root}`.
        """
        from workflow_app.config.app_state import app_state

        # Gate 1: has_config — verbose pt-BR (feedback_workflow_app_gate_verbose)
        if not app_state.has_config or app_state.config is None:
            signal_bus.toast_requested.emit(
                "usabilidade requer project.json carregado na pill superior. "
                "Use o botao [json] (queue-btn-json) para criar ou carregar um "
                "project.json antes de rodar esta trilha.",
                "warning",
            )
            return None

        config = app_state.config
        path = str(config.config_path)
        if not path:
            signal_bus.toast_requested.emit(
                "project.json carregado nao expoe config_path. Recarregue o "
                "projeto via botao [json] (queue-btn-json) e tente novamente.",
                "error",
            )
            return None

        # workspace_root derivado do config (Zero Assumido: nunca placeholder).
        workspace_root = config.workspace_root or str(Path(path).parent)
        return path, workspace_root

    def _emit_usabilidade_pipeline(
        self, trilha: str, real_specs: list[CommandSpec], slug: str
    ) -> None:
        """Injeta /clear/model/effort com anti-redundancia e emite a fila.

        Mesmo helper canonico (_inject_clears) usado por queue-btn-multibackend,
        queue-btn-legacy-to-dcp e queue-btn-dcp-build.
        """
        from workflow_app.templates.quick_templates import _inject_clears

        specs = _inject_clears(real_specs)
        logger.info(
            "[usabilidade:%s] enqueued %d specs for project=%s",
            trilha, len(specs), slug,
        )
        self._template_label.setText(
            f"  \U0001f9ed  usabilidade {trilha}: {slug} ({len(specs)} specs)"
        )
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"usabilidade {trilha} {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_usabilidade_visual_clicked(self) -> None:
        """Enfileira a trilha VISUAL de Usabilidade (Cadeia A, 100% project).

        Le `metrics-project-pill` (project.json) e passa `config.config_path`
        como `$1` a cada subcomando. Cadeia estatica e completa (sem branch A/B
        em runtime, sem entrevista), alinhada a licao do revert 06-22: NENHUM
        comando scope=module. Ordem canonica (WORKFLOW.md), 12 specs opus/high
        (GROUP_MAP["usabilidade"]):

          IDENTIFICAR
            1. /usabilidade:detect <path>     (project/check)
            2. /frontend:scan <path>
            3. /frontend:audit <path>
            4. /frontend:mobile-check <path>
            5. /frontend:assets-check <path>
            6. /frontend:report <path>
          IMPLANTAR
            7. /tools:layout-full-refactor <path>
            8. /tools:mobile-analysis <path>
            9. /tools:mobile-update <path>
          REVISAR (delta gate)
            10. /usabilidade:detect <path>    (re-run)
            11. /frontend:report <path>       (re-run)
          MANUAL
            12. /instruction-manual <workspace_root>

        `/instruction-manual` recebe o `workspace_root` DERIVADO do config
        (nao o placeholder literal). _inject_clears poe /clear entre os passos
        (cada subcomando comunica via artefato em disco, nao via conversa).
        """
        gate = self._usabilidade_gate_and_path()
        if gate is None:
            return
        path, workspace_root = gate

        cfg = GROUP_MAP["usabilidade"]
        model = cfg["model"]
        effort = cfg["effort"]

        def _cmd(name: str, start: int) -> CommandSpec:
            return CommandSpec(
                name=name, model=model, effort=effort,
                interaction_type=InteractionType.AUTO, position=start,
            )

        real_specs: list[CommandSpec] = [
            # IDENTIFICAR
            _cmd(f"/usabilidade:detect {path}", 1),
            _cmd(f"/frontend:scan {path}", 2),
            _cmd(f"/frontend:audit {path}", 3),
            _cmd(f"/frontend:mobile-check {path}", 4),
            _cmd(f"/frontend:assets-check {path}", 5),
            _cmd(f"/frontend:report {path}", 6),
            # IMPLANTAR
            _cmd(f"/tools:layout-full-refactor {path}", 7),
            _cmd(f"/tools:mobile-analysis {path}", 8),
            _cmd(f"/tools:mobile-update {path}", 9),
            # REVISAR (delta gate)
            _cmd(f"/usabilidade:detect {path}", 10),
            _cmd(f"/frontend:report {path}", 11),
            # MANUAL (workspace_root derivado do config, nunca placeholder)
            _cmd(f"/instruction-manual {workspace_root}", 12),
        ]
        self._emit_usabilidade_pipeline("visual", real_specs, Path(path).stem)

    def _on_usabilidade_ia_clicked(self) -> None:
        """Enfileira a trilha IA/findability de Usabilidade (Cadeia B).

        Le `metrics-project-pill` (project.json) e passa `config.config_path`
        como `$1` a cada subcomando. Cadeia estatica e completa (sem branch A/B
        em runtime, sem entrevista). Cria um MODULO REAL via micro-architecture
        ANTES de qualquer comando module-bound; o module_id nunca aparece como
        placeholder {N} na expansao do clique — os comandos module-bound
        resolvem o modulo ativo lendo o lock/delivery.json que `/micro:modularize`
        grava antes nesta mesma fila. Ordem canonica, 13 specs opus/high
        (GROUP_MAP["usabilidade"]):

          IDENTIFICAR
            1. /usabilidade:detect <path>     (project/check)
            2. /frontend:scan <path>
            3. /frontend:audit <path>
            4. /frontend:report <path>
          BOOTSTRAP do modulo (DCP-lite)
            5. /micro:brief <path>
            6. /micro:architecture <path>
            7. /micro:specific-flow-prep <path>
            8. /micro:modularize <path>        (CRIA o modulo + grava module_id)
            9. /micro:review <path>
          BUILD (module-bound, resolve modulo via lock)
            10. /build-module-pipeline <path>
          REVISAR (module-bound, mesmo lock)
            11. /review-executed-module <path>
            12. /front-end-review <path>
          MANUAL
            13. /instruction-manual <workspace_root>

        Contrato anti-{N}: o module_id sai unicamente do lock gravado por
        `/micro:modularize` (posicao 8), que roda antes de
        `/build-module-pipeline` (10) e `/review-executed-module` (11). A
        garantia e a ordem estatica da fila; o fail-closed (abortar se o lock
        estiver ausente) e responsabilidade dos proprios comandos module-bound.
        """
        gate = self._usabilidade_gate_and_path()
        if gate is None:
            return
        path, workspace_root = gate

        cfg = GROUP_MAP["usabilidade"]
        model = cfg["model"]
        effort = cfg["effort"]

        def _cmd(name: str, start: int) -> CommandSpec:
            return CommandSpec(
                name=name, model=model, effort=effort,
                interaction_type=InteractionType.AUTO, position=start,
            )

        real_specs: list[CommandSpec] = [
            # IDENTIFICAR
            _cmd(f"/usabilidade:detect {path}", 1),
            _cmd(f"/frontend:scan {path}", 2),
            _cmd(f"/frontend:audit {path}", 3),
            _cmd(f"/frontend:report {path}", 4),
            # BOOTSTRAP do modulo (DCP-lite) — cria o modulo + grava module_id
            _cmd(f"/micro:brief {path}", 5),
            _cmd(f"/micro:architecture {path}", 6),
            _cmd(f"/micro:specific-flow-prep {path}", 7),
            _cmd(f"/micro:modularize {path}", 8),
            _cmd(f"/micro:review {path}", 9),
            # BUILD (module-bound; resolve modulo ativo via lock, nunca {N})
            _cmd(f"/build-module-pipeline {path}", 10),
            # REVISAR (module-bound; mesmo lock)
            _cmd(f"/review-executed-module {path}", 11),
            _cmd(f"/front-end-review {path}", 12),
            # MANUAL (workspace_root derivado do config, nunca placeholder)
            _cmd(f"/instruction-manual {workspace_root}", 13),
        ]
        self._emit_usabilidade_pipeline("ia", real_specs, Path(path).stem)

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
        self._highlight_current_command(cleaned)
        self._maybe_auto_save(cmd_text)

    def _highlight_current_command(self, cmd_text: str) -> None:
        """Highlight the queue row whose command matches cmd_text."""
        for item in self._items:
            item.set_highlighted(item.command_text() == cmd_text)

    def load_pipeline(self, specs: list[CommandSpec]) -> None:
        """Popula a fila com `CommandSpec` — funil unico de enfileiramento.

        (a) A funcao e `-> None` e **destroi a fila existente** (`self._items`)
        antes de remontar; nenhum dos 4 callsites trata retorno
        (`main_window.py:8859` em `_on_pipeline_ready`, `main_window.py:9465` em
        `_refresh_queue_ui`, `command_queue_widget.py:1112` na pipeline Daily
        Loop, e `restore_queue_snapshot` aqui mesmo).

        (b) Os dois preflights do topo (credencial ORCH do Main e capability por
        comando) sao **informativos por decisao explicita (D4)**: emitem toast
        `warning` e seguem. Rodam ANTES da destruicao da fila e ANTES de
        `adapt_specs_to_main` justamente para que o operador possa trocar o Main
        sem ter uma fila a meio caminho, e para que o aviso descreva a fila que
        ele pediu — sob Main nao-Claude a traducao remove as linhas
        `/model`/`/effort` e muda o tamanho da lista.

        (c) O fail-closed real NAO esta aqui: e o guard de dispatch em
        `_on_step_btn_clicked`, que faz `return` e avalia o Main VIVO
        (`_resolve_interactive_main_llm()`). Item 012 (D5) revogou o
        congelamento do item 019: nao existe mais contrato de enqueue, e o
        radio corrente e a unica autoridade do dispatch.

        (d) Callsite perigoso documentado: `restore_queue_snapshot` (`:11054`,
        chamada em `:11167`) tambem passa por aqui, entao restaurar um snapshot
        dispara os mesmos avisos.
        """
        # Item 011 (C12): preflight no TOPO, acima de `self._items.clear()` e de
        # `adapt_specs_to_main`. Ele **avisa e nao barra** — D4 decidiu manter o
        # preflight informativo, porque `load_pipeline` e `-> None` e destroi a
        # fila antes de qualquer validacao: um `return` precoce ainda deixaria
        # `_on_pipeline_ready` emitindo `pipeline_created` e o toast de sucesso
        # "Pipeline carregado: N comandos" sobre uma fila que nao existe.
        # Quem de fato barra e o guard de dispatch em `_on_step_btn_clicked`,
        # que avalia o Main vivo (item 012 / D5).
        # Fila vazia nao avisa (comportamento preservado).
        if specs:
            _orch_err = self._orch_preflight_main_credential()
            if _orch_err is not None:
                signal_bus.toast_requested.emit(_orch_err, "warning")
            _cap_err = self._capability_preflight_specs(specs)
            if _cap_err is not None:
                signal_bus.toast_requested.emit(_cap_err, "warning")

        # Task 24: a trava de `queue_started` NAO cai aqui. Snapshot/restore
        # preserva `loop_context` (e com ele o `queue_id`), entao limpar o set
        # faria a MESMA fila largar duas vezes no corpus depois de um restore.
        # Fila de verdade nova traz `queue_id` novo e emite sozinha; e a
        # identidade da fila que manda, nao o ciclo de carregamento.

        # Onda 4: clear DCP context — the new pipeline isn't (yet) backed by
        # a SPECIFIC-FLOW.json. The DCP handler will re-arm
        # _current_dcp_flow_path AFTER this signal returns, so DCP-sourced
        # loads end up with the path correctly set. Non-DCP sources stay None.
        self._current_dcp_flow_path = None

        # Clear existing
        for item in self._items:
            item.deleteLater()
        self._items.clear()

        # Remove stretch before inserting
        self._items_layout.takeAt(self._items_layout.count() - 1)

        # Adequacao model/effort ao Main LLM corrente (`queue-div-main-llm`).
        # Sob Main `claude` isto e identidade byte-a-byte; sob qualquer outro as
        # linhas `/model`/`/effort` somem, porque nenhum dos CLIs nao-Claude tem
        # diretiva textual equivalente (C27, evidencia em
        # `model_effort_equivalence`). A leitura acontece AQUI, no enqueue, e
        # nao no dispatch: `adapt_specs_to_main` REMOVE linhas (D-C27-2, item
        # 002), e remocao nao e reversivel por re-render. Item 012 (D5) tornou o
        # estado vivo o regime unico do DISPATCH, mas a composicao da LISTA
        # continua sendo decidida no enqueue — trocar o Main depois de carregar
        # nao ressuscita linha removida nem apaga linha ja materializada. O que
        # o item 012 re-renderiza retroativamente e o sufixo de flags, o
        # `dispatch_text` e o badge de dialeto (ver `_refresh_items_live_state`),
        # nunca a composicao da fila.
        specs = adapt_specs_to_main(specs, self._resolve_interactive_main_llm())

        # Tasks 19/20: (re)ligar o cursor de rocksmash. Fazer o bind AQUI, no
        # funil unico de enfileiramento, e nao no handler do botao, cobre de
        # graca o caminho de snapshot/restore: uma fila rocksmash restaurada
        # volta gravando progresso, em vez de rodar subfases mudas e te-las
        # reenfileiradas na proxima expansao. Fila que nao e rocksmash zera o
        # cursor — deixar o anterior pendurado marcaria subfase de OUTRO loop.
        self._rocksmash_cursor = RocksmashRuntimeCursor.from_specs(specs)
        # Fila nova destroi a anterior: um despacho da fila antiga que ainda
        # nao teve desfecho nunca sera observado. Descartar e a leitura honesta;
        # emitir `item_completed` aqui inventaria uma conclusao.
        self._pending_item_outcome = None

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
        # Estado vivo no ENQUEUE (item 012, finding F1 do review-executed):
        # `_refresh_items_live_state` e o unico sitio que chama
        # `set_dialect_badge`. Sem esta chamada, uma fila carregada ou
        # RESTAURADA ja contendo residuo em dialeto estrangeiro (`/model sol
        # high`, `/reasoning yes`) nasce com o badge apagado, e a mitigacao de
        # R-J5 so acende se o operador por acaso trocar um radio de Main
        # depois — exatamente o cenario que o badge existe para cobrir.
        # O metodo recomputa do zero (idempotente), entao a chamada e segura.
        self._refresh_items_live_state()
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
        # Estado vivo no ENQUEUE (item 012, finding F1). `add_command` NAO passa
        # por `adapt_specs_to_main`, entao e o caminho onde uma diretiva
        # suprimida sob Main nao-Claude chega inteira na fila: sem o re-render
        # o item nasce sem badge.
        self._refresh_items_live_state()
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
        lbl_main_llm = QLabel("Main llm")
        lbl_main_llm.setStyleSheet("color: #22C55E; font-size: 11px; font-weight: 600; padding-left: 4px;")
        lbl_main_llm.setFixedWidth(70)
        lbl_prompt = QLabel("prompt")
        lbl_prompt.setStyleSheet("color: #A78BFA; font-size: 11px; font-weight: 600; padding-left: 4px;")
        lbl_prompt.setFixedWidth(60)
        header_row.addWidget(lbl_cmd)
        header_row.addWidget(lbl_json)
        header_row.addWidget(lbl_main_llm)
        header_row.addWidget(lbl_prompt)
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
            chk_main_llm = QCheckBox(dialog)
            chk_main_llm.setProperty("testid", f"queue-add-main-llm-{i + 1}")
            chk_main_llm.setToolTip("Forçar Main LLM (seta verde) ou permitir Parallel LLM (seta azul)")
            chk_main_llm.setFixedWidth(70)
            chk_main_llm.setChecked(True)  # Default: checked
            chk_main_llm.setStyleSheet("QCheckBox { color: #22C55E; }")
            chk_prompt = QCheckBox(dialog)
            chk_prompt.setProperty("testid", f"queue-add-prompt-{i + 1}")
            chk_prompt.setToolTip("Enviar como prompt simples (texto raw sem transformações)")
            chk_prompt.setFixedWidth(60)
            chk_prompt.setChecked(True)  # Default: checked
            chk_prompt.setStyleSheet("QCheckBox { color: #A78BFA; }")
            row.addWidget(inp)
            row.addWidget(chk)
            row.addWidget(chk_main_llm)
            row.addWidget(chk_prompt)
            layout.addLayout(row)
            layout.addSpacing(4)
            inputs_and_checks.append((inp, chk, chk_main_llm, chk_prompt))

        line_edit_1, chk_1, chk_main_llm_1, chk_prompt_1 = inputs_and_checks[0]
        line_edit_2, chk_2, chk_main_llm_2, chk_prompt_2 = inputs_and_checks[1]
        line_edit_3, chk_3, chk_main_llm_3, chk_prompt_3 = inputs_and_checks[2]

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
        for line_edit, chk, chk_main_llm, chk_prompt in [(line_edit_1, chk_1, chk_main_llm_1, chk_prompt_1), (line_edit_2, chk_2, chk_main_llm_2, chk_prompt_2), (line_edit_3, chk_3, chk_main_llm_3, chk_prompt_3)]:
            text = line_edit.text().strip()
            if not text:
                continue
            if chk.isChecked() and json_path:
                text = f"{text} {json_path}"
            force_main = chk_main_llm.isChecked()
            is_prompt = chk_prompt.isChecked()
            filled.append((text, force_main, is_prompt))

        if not filled:
            return
        position = "last" if radio_last.isChecked() else "next"
        for text, force_main, is_prompt in filled:
            self._inject_next_command(text, position=position, force_main_llm=force_main, is_prompt=is_prompt)

    def _inject_next_command(self, text: str, position: str = "next", force_main_llm: bool = True, is_prompt: bool = True) -> None:
        """Cria CommandSpec transiente e insere conforme a posicao.

        position="next" (default): apos sent/injected items (proximo a rodar).
        position="last": no final da fila (apos todos os items existentes).
        force_main_llm: Se True, forca CLAUDE (verde/T1); se False, permite workers (azul/T2/T3).
        is_prompt: Se True, envia texto raw sem transformacoes (sem /slash-executor, /skill:, etc.).
        kimi_eligible=True forca a seta azul visivel independente do
        whitelist (ver CommandItemWidget._setup_ui).
        """
        spec = CommandSpec(
            name=text,
            model=ModelName.SONNET,
            interaction_type=InteractionType.AUTO,
            kimi_eligible=True,
            force_main_llm=force_main_llm,
            is_prompt=is_prompt,
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
        # P4: queue-template-label e sempre visivel; nao escondemos mais.
        self._empty_widget.setVisible(True)
        self._list_widget.setVisible(False)
        self._emit_progress_metrics()
        self._update_save_btn_state()

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
        if self._suspend_progress_metrics:
            # Rearme em massa do auto-loop em curso: o emit final sai uma unica
            # vez em `rearm_sent_items` (evita N ticks intermediarios do ring).
            return
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
        estado de worker (checkboxes de worker: kimi, qwen e mimo no T2,
        codex e grok no T3) + Main LLM ativo (invariantes 2 e 5: eixo Worker
        antes do Main-LLM, nunca os checkboxes de rota de terminal
        `terminal-route-t1/t2/t3`, que desde 07-27 vivem no header de cada
        terminal). Reusa a mesma construcao do step path
        (_on_step_btn_clicked).

        `mimo_worker_enabled` vem de `_is_mimo_worker_live()`, nao do
        `isChecked()` cru: worker MiMo oculto pelo switch do roster nunca
        chega ao router, mesmo marcado por codigo."""
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
            qwen_worker_enabled=bool(
                getattr(self, "_use_qwen_chk", None) is not None
                and self._use_qwen_chk.isChecked()
            ),
            grok_worker_enabled=bool(
                getattr(self, "_use_grok_chk", None) is not None
                and self._use_grok_chk.isChecked()
            ),
            mimo_worker_enabled=self._is_mimo_worker_live(),
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
        # Rota propria da MiMo (T2, item 007): mark-as-sent fica no slot,
        # depois do envio confirmado pelo host guard fail-closed. Nao passa
        # pelo `_dispatch_blue_arrow` do Kimi/Qwen (caminho antigo preservado).
        item.run_in_mimo_terminal_requested.connect(
            lambda cmd, it=item: self._on_single_button_mimo_dispatch(it, cmd)
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
        # Eixo-flag (F1 do review-executed-loop 07-09-flags): um item criado com
        # --kimi/--codex JA marcada precisa nascer com o label em paridade com
        # copy/dispatch, que computam o sufixo live. Espelha o read-at-create do
        # eixo-worker logo acima: le os checkboxes queue-chk-flag-* e aplica o
        # sufixo via o helper puro. No-op quando nenhuma flag marcada (guard
        # active_flags) ou item inelegivel (I2/I3 resolvidas no helper => sufixo
        # vazio => set_flag_suffix restaura a base). Cobre load_pipeline E
        # add_command (ambos passam por _make_item), fechando o gap de todos os
        # add-paths com uma unica mudanca.
        _active_flags = self._active_mcp_flags()
        if _active_flags:
            _provider = self._resolve_item_provider(spec)
            _rendered = render_with_mcp_flags(
                spec,
                for_dispatch=False,
                provider=_provider,
                active_flags=_active_flags,
            )
            item.set_flag_suffix(_rendered[len(spec.name):].strip())
            # Item 012: seta tambem o dispatch text inicial (com config_path).
            _full_dispatch = command_text_with_flags(
                spec,
                provider=_provider,
                active_flags=_active_flags,
            )
            item.set_dispatch_text(_full_dispatch)
        # Item 012 (D5, revoga o item 019): NAO existe mais contrato congelado a
        # capturar aqui. O dispatch (step, clique per-item e seta verde) le o
        # estado vivo da UI no momento do clique. Como nao ha cache indexado por
        # `id(item)`, o vazamento por reuso de endereco do CPython (item morto ->
        # `deleteLater()` sem `del` no dicionario -> item novo herdando o
        # contrato do morto) morre POR CONSTRUCAO: `load_pipeline`, `clear_queue`
        # e `_on_remove_requested` nao tem mais estado paralelo a purgar.
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

    def _on_single_button_mimo_dispatch(
        self, item: CommandItemWidget, cmd_text: str
    ) -> None:
        """Slot do botao unico (azul) para a MiMo/T2 (rota propria, item 007).

        So marca o item como enviado quando `_dispatch_mimo_blue_arrow` devolve
        True (host guard fail-closed passou E o payload foi emitido ao T2). Em
        qualquer abort (ocupacao errada, processo mimo ausente, PTY nao
        inspecionavel, payload com "!`") o item permanece pendente e o toast do
        dispatcher e o feedback visivel (Zero Silencio). Espelha
        `_on_single_button_codex_dispatch`; label e highlight usam o texto
        original do item (`cmd_text`), como a seta verde."""
        if self._dispatch_mimo_blue_arrow(cmd_text):
            self._on_run_command(cmd_text)
            item._mark_as_sent()

    def _on_item_sent_state_changed(self, _is_sent: bool) -> None:
        """Item toggled the amber-dot (sent) state — refresh queue-progress-ring."""
        self._emit_progress_metrics()

    # Default delay between paste and Enter for the blue-arrow Kimi path.
    _KIMI_BLUE_ARROW_DEFAULT_DELAY_MS: int = 1_000
    # Extra delay added when the previous workspace dispatch was /clear:
    # Kimi takes longer to repaint the prompt after a full TUI clear.
    _KIMI_AFTER_CLEAR_EXTRA_DELAY_MS: int = 2_000

    def _dispatch_mimo_blue_arrow(self, cmd_text: str) -> bool:
        """Despacha a seta azul da MiMo ao T2; True so quando publicou o payload.

        Caminho PROPRIO da MiMo (item 007): nao passa por `_dispatch_blue_arrow`
        (Kimi/Qwen) nem por `_route_blue_arrow_through_universal` — o builder
        `_build_mimo_slash_executor_invocation` ja produz o executor nativo
        `/slash-executor --delegation-runtime=mimo`. Gates nesta ordem:

          1. texto vazio/so espacos -> toast `warning` + False;
          2. `_ensure_t2_mimo_host()` (fail-closed) -> False ja com toast;
          3. builder (recusa de "!`" -> ValueError) -> toast `warning` + False.

        Delay igual ao do `_dispatch_blue_arrow`: `_KIMI_BLUE_ARROW_DEFAULT_DELAY_MS`,
        mais `_KIMI_AFTER_CLEAR_EXTRA_DELAY_MS` quando a ultima dispatch do
        workspace foi /clear (flag consumida aqui para False). O retorno bool e a
        definicao de "envio confirmado" usada pelo slot
        `_on_single_button_mimo_dispatch` (mark-as-sent gated, mesma semantica de
        `_dispatch_codex_command`)."""
        if not cmd_text or not cmd_text.strip():
            signal_bus.toast_requested.emit(
                "Worker MiMo: comando vazio - dispatch abortado.",
                "warning",
            )
            return False
        if not self._ensure_t2_mimo_host():
            return False
        try:
            payload = self._build_mimo_slash_executor_invocation(cmd_text)
        except ValueError as exc:
            signal_bus.toast_requested.emit(
                f"Worker MiMo: {exc} - dispatch abortado.",
                "warning",
            )
            return False
        if self._last_workspace_dispatch_was_clear:
            delay = (
                self._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
                + self._KIMI_AFTER_CLEAR_EXTRA_DELAY_MS
            )
            self._last_workspace_dispatch_was_clear = False  # consumed
        else:
            delay = self._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
        dispatch_telemetry.open_dispatch(
            route="blue-arrow",
            channel="workspace",
            command=payload,
            position=self._dispatch_position(),
            after_clear=self._last_dispatch_head.get("workspace") == "/clear",
        )
        self._last_dispatch_head["workspace"] = self._command_head(payload)
        signal_bus.kimi_blue_arrow_dispatched.emit(payload, delay)
        return True

    def _dispatch_blue_arrow(self, kimi_prompt: str) -> None:
        """Forward a blue-arrow click to `kimi_blue_arrow_dispatched` with
        the right delay. Handler do par T2 inteiro (Worker Kimi e Worker
        Qwen): o clique per-item e o step convergem aqui via
        `_on_kimi_clicked`. Se a ocupacao do T2 e `qwen`, reescreve
        `/skill:slash-executor` para o slash nativo `/slash-executor`.

        If the previous workspace dispatch was /clear, add 2s extra because
        Kimi's TUI repaint after a clear is slower than normal — without the
        extra delay, Enter lands before /skill: is composed and the command
        is silently dropped. O mesmo delay vale para Qwen (Rich prompt).

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
        # FIX-011 Opt 1: roteia o worker pelo executor universal (contrato de
        # finalizacao do listener) quando aplicavel — fecha o stuck-yellow do
        # caso 011 sem tocar `adapt_to_kimi`. Idempotente para o payload de
        # recovery (ja `/skill:slash-executor ...`).
        kimi_prompt = self._route_blue_arrow_through_universal(kimi_prompt)
        t2, _ = self._resolve_worker_occupancy()
        if t2 == "qwen":
            kimi_prompt = self._build_qwen_slash_executor_invocation(kimi_prompt)
        if self._last_workspace_dispatch_was_clear:
            delay = (
                self._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
                + self._KIMI_AFTER_CLEAR_EXTRA_DELAY_MS
            )
            self._last_workspace_dispatch_was_clear = False  # consumed
        else:
            delay = self._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
        dispatch_telemetry.open_dispatch(
            route="blue-arrow",
            channel="workspace",
            command=kimi_prompt,
            position=self._dispatch_position(),
            after_clear=self._last_dispatch_head.get("workspace") == "/clear",
        )
        self._last_dispatch_head["workspace"] = self._command_head(kimi_prompt)
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

    #: Item 004 (C13): ordem de leitura do eixo Main LLM. Estende a precedencia
    #: legada (codex > qwen > grok > mimo > kimi > claude) com os slugs de
    #: variante. `mimo` vem antes de todo slug kimi (regra MiMo > Kimi,
    #: 2026-10-02); os slugs legados mantem a posicao relativa.
    #: O `_main_llm_group` e exclusivo, entao no maximo um radio esta marcado e
    #: a ordem so importa como desempate defensivo; ela mantem os slugs legados
    #: na mesma ordem relativa para que o regime legado (variantes e mimo
    #: ocultos e nunca marcados) resolva byte a byte como antes.
    _MAIN_LLM_PRECEDENCE = (
        "codex",
        "qwen",
        "grok",
        "mimo",
        "kimi-k3",
        "opus",
        "sonnet",
        "kimi",
    )

    def _resolve_interactive_main_llm_slug(self) -> str:
        """Slug CRU do radio Main marcado AGORA.

        Retorna um slug canonico de `_MAIN_LLM_VARIANTS` (C13) ou `claude`
        — a family nua, default do regime legado. E a unica leitura que
        preserva a variante; `_resolve_interactive_main_llm()` colapsa para
        family de proposito (ver docstring de lá).

        Guarda de visibilidade (D-005-4) SO para `mimo`: com o roster MiMo
        desligado, um radio mimo marcado por codigo nao vira Main (fail-closed
        quando `_main_radio_visible` falta). Os demais slugs seguem resolvidos
        sem olhar visibilidade, como D-005-4 decidiu.
        """
        _map = getattr(self, "_main_radio_map", None) or {}
        _visible = getattr(self, "_main_radio_visible", None) or {}
        for slug in self._MAIN_LLM_PRECEDENCE:
            if slug == "mimo" and not _visible.get("mimo", False):
                continue
            radio = _map.get(slug)
            if radio is not None and radio.isChecked():
                return slug
        return "claude"

    def _resolve_interactive_main_llm_pair(self) -> tuple[str, str | None]:
        """Item 004 (C6/C13): `(family, variant)` do Main LLM marcado AGORA.

        `variant` e `None` para os slugs que sao family nua
        (`claude|codex|kimi|qwen|mimo|grok`) e carrega a variante de modelo
        para os slugs de variante: `opus`/`sonnet` -> family `claude`,
        `kimi-k3` -> family `kimi`. MF-01: variante NAO vira membro de
        `provider_router.Provider`.
        """
        return _MAIN_LLM_VARIANTS.get(
            self._resolve_interactive_main_llm_slug(), ("claude", None)
        )

    def _resolve_interactive_main_llm(self) -> str:
        """Qual LLM ocupa o terminal interactive (T1) AGORA — FAMILY apenas.

        Espelha a precedencia de `_dispatch_green_arrow`/`_on_btn_next_clicked`:
        radio Main Codex > radio Main Qwen > radio Main Grok > radio Main MiMo > checkbox Main Kimi (--force) > Claude (default).

        Item 004 (ST004/ST006): com os radios de variante ligados, este acessor
        continua devolvendo `claude|codex|kimi|qwen|mimo|grok`. Isso e um ADAPTADOR
        explicito, nao coercao silenciosa: os 14 call sites (routing, roster do
        `main_window`, `MetricsBar`, recovery prompt/context, `FlagsPanel`)
        raciocinam em provider, e `opus`/`sonnet`/`kimi-k3` nao sao providers.
        Quem precisa da variante chama `_resolve_interactive_main_llm_pair()`;
        quem precisa do slug cru (persistencia) chama
        `_resolve_interactive_main_llm_slug()`.
        """
        return self._resolve_interactive_main_llm_pair()[0]

    def current_main_llm(self) -> str:
        """Acessor publico read-only do Main LLM (`claude|codex|kimi|qwen|mimo|grok`).

        Superficie UNICA para o `main_window` (insercoes LLM-aware) ler o Main LLM
        sem instanciar radio proprio nem ler o cache `MetricsBar._main_llm`. Encapsula
        `_resolve_interactive_main_llm()` (precedencia codex > qwen > grok > mimo > kimi > claude).
        Ver blacksmith/brainstorm-mcp/06-15-insertions-subtab-llm-routing.md §11.1/D1.
        """
        return self._resolve_interactive_main_llm()

    def _emit_main_llm_boot(self) -> None:
        """Publica o Main LLM restaurado do QSettings uma vez, no boot.

        Os handlers dos radios so existem depois do restore, entao sem este
        emit os consumidores de `main_llm_changed` nasciam presos no default
        `claude` ate o operador clicar em algum radio.
        """
        signal_bus.main_llm_changed.emit(self._resolve_interactive_main_llm())

    def _persist_main_llm_selection(self) -> None:
        """Item 018: salva o radio Main LLM selecionado no QSettings.

        Chamado pelo signal ``buttonClicked`` do ``_main_llm_group``.
        Persiste o slug (``claude|codex|kimi|qwen|mimo|grok`` + os de variante
        do item 004: ``opus|sonnet|kimi-k3``) em ``main_llm/selected`` para
        restaurar na proxima inicializacao do widget. A restauracao rejeita
        slug cujo radio esteja oculto por kill-switch e cai em ``claude``.

        Item 004: grava o slug CRU. Persistir a family colapsada faria a
        sessao seguinte reabrir em ``claude`` depois do operador ter escolhido
        ``opus`` — perda silenciosa da selecao.
        """
        slug = self._resolve_interactive_main_llm_slug()
        QSettings("systemForge", "workflow-app").setValue(
            "main_llm/selected", slug
        )

    def _capability_preflight_specs(self, specs: list[CommandSpec]) -> str | None:
        """Item 011 (C11/C12): capability por comando sob o Main corrente.

        AVISA, nao barra (decisao humana D4). Retorna `None` quando nao ha nada
        a dizer, ou UMA mensagem agregada — nunca uma por comando: aviso
        repetido 40 vezes e ruido, e ruido esconde sinal.

        Puro em relacao a fila: nao le nem escreve `self._items`. Recebe as
        specs na forma **recebida** (dialeto Claude, ANTES de
        `adapt_specs_to_main`), porque sob Main nao-Claude a traducao remove as
        linhas `/model`/`/effort` e muda o tamanho da lista — avisar depois
        descreveria uma fila que o operador nunca montou.

        Silencioso para comando fora do snapshot: `None` de
        `get_mapped_capabilities` significa "nao mapeado", nao "indisponivel".

        Fail-open explicito: comando que o snapshot mapeia para OUTRO Main mas
        nao para o Main corrente (family nova ainda sem linhas no snapshot,
        como a `mimo` antes de ganhar cobertura) entra na fila sem checagem de
        capability, e o aviso diz isso com todas as letras em vez de calar.
        """
        family = self._resolve_interactive_main_llm()
        loader = get_capability_loader()

        if loader.get_failure_reason() == "snapshot_ausente":
            return "Capability preflight indisponivel: snapshot_ausente (aviso, nao barra)."

        _known = {fam for fam, _ in _MAIN_LLM_VARIANTS.values()} | {"claude"}
        missing: list[tuple[str, str]] = []
        uncovered: list[str] = []
        for spec in specs:
            name = getattr(spec, "name", "") or ""
            if getattr(spec, "kind", "slash") == "local-action":
                continue
            if is_directive_line(name):
                continue
            slug = self._command_head(name)
            if not slug or slug == "/clear":
                continue
            mapped = loader.get_mapped_capabilities(slug, family, "main")
            if mapped is None:
                if slug not in uncovered and any(
                    loader.get_mapped_capabilities(slug, other, "main") is not None
                    for other in _known - {family}
                ):
                    uncovered.append(slug)
                continue
            for capability, status in mapped.items():
                if status != "disponivel":
                    missing.append((slug, capability))

        if not missing and not uncovered:
            return None

        message = ""
        if missing:
            examples = ", ".join(f"{slug}:{cap}" for slug, cap in missing[:3])
            overflow = len(missing) - 3
            suffix = f" (+{overflow})" if overflow > 0 else ""
            message = (
                f"Capability preflight (aviso, nao barra): {len(missing)} item(ns) "
                f"sem capability sob Main '{family}': {examples}{suffix}"
            )
        if uncovered:
            ex = ", ".join(uncovered[:3])
            overflow_u = len(uncovered) - 3
            suffix_u = f" (+{overflow_u})" if overflow_u > 0 else ""
            clause = (
                f"Capability preflight (aviso, nao barra): Main '{family}' sem "
                f"cobertura no snapshot para {len(uncovered)} item(ns) mapeado(s) "
                f"em outros Mains: {ex}{suffix_u}; fila aceita sem checagem de "
                f"capability (fail-open)."
            )
            message = f"{message}; {clause}" if message else clause
        return message

    def _orch_preflight_main_credential(self, main_llm: str | None = None) -> str | None:
        """Item 018: preflight de credencial do Main LLM antes do enqueue.

        Verifica se a credencial basica do provider selecionado como Main
        esta disponivel no ambiente. Retorna ``None`` quando OK, ou uma
        mensagem de erro quando a credencial esta ausente.

        ``main_llm`` permite avaliar um Main **explicito** em vez de reler a UI
        aqui dentro. Item 012 (D5, revoga o item 019): o dispatch passa o Main
        **VIVO** (`_resolve_interactive_main_llm()`), porque e contra essa conta
        que o comando vai de fato rodar — girar o radio para Codex depois de
        enfileirar muda o destino real do item, entao checar a credencial de um
        Main congelado avisaria sobre a conta errada. O parametro permanece
        explicito (em vez de o metodo reler a UI sozinho) para manter uma unica
        fonte do Main por dispatch: quem decide o roteamento e quem decide o
        preflight leem o mesmo valor, no mesmo instante.

        **Fontes de verdade (PF-01, source.md §10.13).** Credencial de provider
        e **ORCH**: quem le e o agente/CLI, nao a aplicacao entregue. Por isso
        ela vive em ``.claude/projects/{slug}.json > credentials.mcp_servers.
        <provider>.*`` e **nunca** no ``.env``. O preflight resolve, nesta ordem:

        1. **CLI resolvivel** — binario do provider no ``PATH`` ou em
           ``~/.local/bin``. "Provider sem CLI resolvivel" e a primeira metade
           do fail-closed de PF-01 (source.md:1415).
        2. **Credencial ORCH** — segunda metade. Aceita, nesta ordem:
           ``credentials.mcp_servers.<provider>.*`` no project.json detectado;
           config local do proprio CLI (``~/.codex/auth.json``,
           ``~/.kimi/config.toml``, ``~/.qwen/settings.json``,
           ``~/.grok/auth.json``, ``~/.local/share/mimocode/auth.json``,
           ``~/.claude.json``); variavel de ambiente,
           apenas como ultimo sinal e nunca como fonte canonica.

        A config local do CLI conta como credencial porque e assim que os CLIs
        deste host de fato autenticam. Exigir a env var reprovaria provider
        perfeitamente autenticado, que e falso-negativo, nao fail-closed. Ja
        um provider sem CLI e sem nenhuma das tres fontes reprova de verdade.

        Retorna ``None`` quando aprovado, ou a mensagem de bloqueio (com motivo
        e provider afetado) que o chamador emite como toast. **Proibido fallback
        silencioso para outro provider** (PF-01, Zero Silencio).
        """
        import os

        if main_llm is None:
            main_llm = self._resolve_interactive_main_llm()

        entry = self._ORCH_PROVIDER_SOURCES.get(main_llm)
        if entry is None:
            return None
        binaries, cred_key, config_paths, env_keys = entry

        if not self._orch_cli_resolvable(binaries):
            return (
                f"CLI do Main LLM '{main_llm}' nao resolvivel: nenhum de "
                f"{', '.join(binaries)} encontrado no PATH ou em ~/.local/bin."
            )

        if self._orch_credential_in_project_json(cred_key):
            return None
        for rel in config_paths:
            if os.path.exists(os.path.expanduser(rel)):
                return None
        for key in env_keys:
            if os.environ.get(key, "").strip():
                return None

        return (
            f"Credencial ORCH do Main LLM '{main_llm}' ausente: nada em "
            f"credentials.mcp_servers.{cred_key} do project.json, nenhuma config "
            f"local ({', '.join(config_paths)}) e nenhuma de {', '.join(env_keys)}."
        )

    # provider -> (binarios aceitos, chave ORCH, configs locais do CLI, envs de fallback)
    _ORCH_PROVIDER_SOURCES: dict[
        str, tuple[tuple[str, ...], str, tuple[str, ...], tuple[str, ...]]
    ] = {
        "claude": (
            ("claude", "clauded"),
            "claude",
            ("~/.claude.json", "~/.claude/settings.json"),
            ("ANTHROPIC_API_KEY",),
        ),
        "kimi": (
            ("kimi", "kimid"),
            "kimi",
            ("~/.kimi/config.toml",),
            ("KIMI_API_KEY", "MOONSHOT_API_KEY"),
        ),
        "codex": (
            ("codex", "codex-high"),
            "codex",
            ("~/.codex/auth.json", "~/.codex/config.toml"),
            ("OPENAI_API_KEY",),
        ),
        "qwen": (
            ("qwen", "qwen-high"),
            "qwen",
            ("~/.qwen/settings.json",),
            ("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
        ),
        "grok": (
            ("grok",),
            "grok",
            ("~/.grok/auth.json", "~/.grok/config.toml"),
            ("GROK_API_KEY", "XAI_API_KEY"),
        ),
        # MiMo (D5): so o launcher `mimod`. O `mimo` do zsh do operador e
        # funcao de shell (abre o dialogo de bypass do TUI) e o binario real
        # (`~/.mimocode/bin/mimo`) nao fica no PATH nem em ~/.local/bin; o
        # preflight so faz sentido para o launcher que o app de fato digita.
        # Auth do CLI: `XIAOMI_API_KEY` (alias `MIMO_API_KEY`, mesmo segredo
        # do Token Plan) ou o auth.json do mimocode, conferido so por
        # existencia (nunca lido).
        "mimo": (
            ("mimod",),
            "mimo",
            ("~/.local/share/mimocode/auth.json",),
            ("XIAOMI_API_KEY", "MIMO_API_KEY"),
        ),
    }

    @staticmethod
    def _orch_cli_resolvable(binaries: tuple[str, ...]) -> bool:
        """PF-01, metade 1: algum binario do provider existe e e executavel."""
        import os
        import shutil

        for name in binaries:
            if shutil.which(name):
                return True
            local = os.path.expanduser(f"~/.local/bin/{name}")
            if os.path.isfile(local) and os.access(local, os.X_OK):
                return True
        return False

    @staticmethod
    def _orch_credential_in_project_json(provider_key: str) -> bool:
        """PF-01, metade 2: credencial ORCH declarada no project.json detectado.

        Le ``credentials.mcp_servers.<provider_key>`` e aceita qualquer valor
        escalar nao vazio (``api_key``, ``access_token``, ``binary``, ``enabled``
        ...). Nao loga o valor: o preflight so precisa saber se existe.
        """
        import json

        from workflow_app.config.config_parser import detect_config

        try:
            path = detect_config()
            if not path:
                return False
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return False

        node = data.get("credentials", {}).get("mcp_servers", {}).get(provider_key)
        if not isinstance(node, dict):
            return bool(node)
        return any(
            isinstance(v, (str, bool, int, float)) and str(v).strip() not in ("", "False")
            for v in node.values()
        )

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
          - interactive + Qwen   -> /slash-executor + slash cru;
          - interactive + Grok   -> /slash-executor --delegation-runtime=grok + slash;
          - workspace            -> Kimi/Qwen blue-arrow (kimi_blue_arrow_dispatched, T2);
          - workspace_xterm      -> Codex envelope OU Grok `/slash-executor` nativo.

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
            # T2 Parallel Worker: seta azul (TASK 09). Qwen no T2 usa o
            # slash nativo `/slash-executor`; Kimi permanece `/skill:`.
            t2, _ = self._resolve_worker_occupancy()
            builder = (
                self._build_qwen_slash_executor_invocation
                if t2 == "qwen"
                else self._build_kimi_slash_executor_invocation
            )
            payload = builder(base, recovery_mode=True)
            self._dispatch_blue_arrow(payload)
        elif channel == "workspace_xterm":
            # T3 Parallel Worker: Codex envelope por default; Grok usa o
            # mesmo builder nativo do Main (`/slash-executor`), nunca o
            # envelope "Use the SystemForge slash-command executor rules".
            _t2, t3 = self._resolve_worker_occupancy()
            if t3 == "grok":
                hosted = self._t3_pty_hosts_cli(self._GROK_CLI_BASENAME)
                if hosted is False:
                    self._reject_recovery_command(
                        channel,
                        "Auto-recuperacao abortada: T3 PTY nao hospeda o "
                        "processo grok (queue-chk-use-grok marcado, CLI "
                        "ausente).",
                    )
                    return
                payload = self._build_grok_slash_executor_invocation(
                    base, recovery_mode=True
                )
            else:
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
            self._publish_to_terminal("workspace_xterm", route="listener-recovery", text=payload)
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
            elif llm == "qwen":
                payload = self._build_qwen_slash_executor_invocation(
                    base, recovery_mode=True
                )
            elif llm == "grok":
                payload = self._build_grok_slash_executor_invocation(
                    base, recovery_mode=True
                )
            elif llm == "mimo":
                try:
                    payload = self._build_mimo_slash_executor_invocation(
                        base, recovery_mode=True
                    )
                except ValueError as exc:
                    self._reject_recovery_command(
                        channel, f"Auto-recuperacao abortada: {exc}"
                    )
                    return
            elif llm == "kimi":
                payload = self._build_kimi_slash_executor_invocation(
                    base, recovery_mode=True
                )
            else:  # claude — slash cru, sem transformacao
                payload = base
            self._publish_to_terminal("interactive", route="listener-recovery", text=payload)

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
        """Main LLM Kimi preserves the old force-Kimi routing behavior.

        Item 012, finding F2: este e o handler do radio Main Kimi
        (`_force_kimi_chk` e alias de `_main_kimi_radio`) e era o UNICO do eixo
        Main sem o ponto unico de re-render. A omissao ficava mascarada porque
        desmarcar o radio anterior dispara o handler daquele radio, que
        re-renderiza — a mesma forma da omissao em `_on_main_claude_toggled`
        que este item corrigiu.
        """
        self._refresh_kimi_btn_visibility()
        self._refresh_flag_checkboxes_state()
        self._refresh_items_live_state()
        if checked:
            signal_bus.main_llm_changed.emit("kimi")

    def _on_use_kimi_toggled(self, checked: bool) -> None:
        """Parallel Worker Kimi (T2). PW-01: exclusividade com qwen e mimo."""
        if checked:
            if self._use_qwen_chk.isChecked():
                self._use_qwen_chk.blockSignals(True)
                self._use_qwen_chk.setChecked(False)
                self._use_qwen_chk.blockSignals(False)
                signal_bus.toast_requested.emit(
                    "Kimi substituiu Qwen no worker T2 (exclusividade PW-01)",
                    "info",
                )
            if self._use_mimo_chk.isChecked():
                self._use_mimo_chk.blockSignals(True)
                self._use_mimo_chk.setChecked(False)
                self._use_mimo_chk.blockSignals(False)
                signal_bus.toast_requested.emit(
                    "Kimi substituiu MiMo no worker T2 (exclusividade PW-01)",
                    "info",
                )
            self._warn_main_worker_collision("kimi")
        self._refresh_kimi_btn_visibility()
        self._persist_worker_selection()

    def _on_use_qwen_toggled(self, checked: bool) -> None:
        """Parallel Worker Qwen (T2). PW-01: exclusividade com kimi e mimo."""
        if checked:
            if self._use_kimi_chk.isChecked():
                self._use_kimi_chk.blockSignals(True)
                self._use_kimi_chk.setChecked(False)
                self._use_kimi_chk.blockSignals(False)
                signal_bus.toast_requested.emit(
                    "Qwen substituiu Kimi no worker T2 (exclusividade PW-01)",
                    "info",
                )
            if self._use_mimo_chk.isChecked():
                self._use_mimo_chk.blockSignals(True)
                self._use_mimo_chk.setChecked(False)
                self._use_mimo_chk.blockSignals(False)
                signal_bus.toast_requested.emit(
                    "Qwen substituiu MiMo no worker T2 (exclusividade PW-01)",
                    "info",
                )
            self._warn_main_worker_collision("qwen")
        self._refresh_kimi_btn_visibility()
        self._persist_worker_selection()

    def _on_use_mimo_toggled(self, checked: bool) -> None:
        """Parallel Worker MiMo (T2). PW-01: exclusividade com kimi e qwen.

        Worker oculto pelo kill-switch do roster MiMo e inerte: sem persistir,
        sem toast, sem desmarcar irmaos.
        """
        if checked and not (getattr(self, "_worker_visible", None) or {}).get(
            "mimo", False
        ):
            self._use_mimo_chk.blockSignals(True)
            self._use_mimo_chk.setChecked(False)
            self._use_mimo_chk.blockSignals(False)
            logger.debug("worker mimo oculto: marcacao programatica ignorada")
            return
        if checked:
            for sibling, label in (
                (self._use_kimi_chk, "Kimi"),
                (self._use_qwen_chk, "Qwen"),
            ):
                if sibling.isChecked():
                    sibling.blockSignals(True)
                    sibling.setChecked(False)
                    sibling.blockSignals(False)
                    signal_bus.toast_requested.emit(
                        f"MiMo substituiu {label} no worker T2 (exclusividade PW-01)",
                        "info",
                    )
            self._warn_main_worker_collision("mimo")
        self._refresh_kimi_btn_visibility()
        self._persist_worker_selection()

    def _on_main_codex_toggled(self, checked: bool) -> None:
        """Hook kept explicit for symmetry with Main Kimi.

        Item 012 (D5): re-renderiza os itens ja enfileirados. Trocar o Main muda
        o provider efetivo, logo muda o sufixo de flags, o `dispatch_text` e o
        badge de dialeto que o dispatch vivo vai consumir.
        """
        self._refresh_kimi_btn_visibility()
        self._refresh_flag_checkboxes_state()
        self._refresh_items_live_state()
        if checked:
            signal_bus.main_llm_changed.emit("codex")

    def _on_main_claude_toggled(self, checked: bool) -> None:
        """Main LLM Claude is the default raw-dispatch path (T1 interactive).

        Emits main_llm_changed so MetricsBar can phrase the red-listener
        auto-recovery prompt for Claude (uses /tools:auq-interview on the
        ask path). See ai-forge/rules/llm-routing-div.md.

        Item 012 (D5): passa a chamar `_refresh_kimi_btn_visibility()` — que os
        outros tres handlers do eixo Main ja chamavam e este NAO chamava — e o
        ponto unico de re-render. Sob o regime congelado a omissao era inocua
        (o step lia o contrato); sob o regime vivo era divergencia real.
        """
        self._refresh_kimi_btn_visibility()
        self._refresh_flag_checkboxes_state()
        self._refresh_items_live_state()
        if checked:
            signal_bus.main_llm_changed.emit("claude")

    def _on_main_qwen_toggled(self, checked: bool) -> None:
        """Main LLM Qwen: mesmo payload de terminal que Kimi (slash-executor).

        Item 012 (D5): re-renderiza os itens ja enfileirados (sufixo, dispatch
        text e badge de dialeto seguem o Main vivo).
        """
        self._refresh_kimi_btn_visibility()
        self._refresh_flag_checkboxes_state()
        self._refresh_items_live_state()
        if checked:
            signal_bus.main_llm_changed.emit("qwen")

    def _on_main_grok_toggled(self, checked: bool) -> None:
        """Main LLM Grok: dispatch via provider bridge (D-30, item 026).

        Item 012 (D5): re-renderiza os itens ja enfileirados (sufixo, dispatch
        text e badge de dialeto seguem o Main vivo).
        """
        self._refresh_kimi_btn_visibility()
        self._refresh_flag_checkboxes_state()
        self._refresh_items_live_state()
        if checked:
            signal_bus.main_llm_changed.emit("grok")

    def _on_main_mimo_toggled(self, checked: bool) -> None:
        """Main LLM MiMo (CLI mimocode no T1): emite a family `mimo`.

        Guarda D-005-4 so para mimo: radio oculto pelo kill-switch do roster
        MiMo e inerte; marcacao programatica volta para claude.
        """
        if checked and not (getattr(self, "_main_radio_visible", None) or {}).get(
            "mimo", False
        ):
            self._main_mimo_radio.blockSignals(True)
            self._main_claude_radio.setChecked(True)
            self._main_mimo_radio.blockSignals(False)
            logger.debug(
                "radio Main mimo oculto: marcacao programatica revertida para claude"
            )
            return
        self._refresh_kimi_btn_visibility()
        self._refresh_flag_checkboxes_state()
        self._refresh_items_live_state()
        if checked:
            signal_bus.main_llm_changed.emit("mimo")

    def _on_main_variant_toggled(self, slug: str, checked: bool) -> None:
        """Item 004 (C6/ST006): handler comum dos 3 radios de variante.

        DECISAO ST006 (registrada aqui de proposito — Zero Silencio): o sinal
        `main_llm_changed` carrega a FAMILY, nunca o slug de variante. Os 4
        rosters externos do eixo Main sao fechados nos slugs de provider do
        roster:

          - `main_window._MAIN_LLM_SLUGS` (clampa desconhecido para `claude`);
          - `metrics_bar._MAIN_LLM_SLUGS` (IGNORA desconhecido em silencio, o
            que deixaria o cache preso no Main ANTERIOR — pior falha das 4);
          - `metrics_bar/recovery_prompt.py` e `recovery_context.py` (tupla
            hardcoded + fallback `claude`).

        Emitir `opus` para eles seria descartar a selecao em silencio em 3 dos
        4 e travar o cache no 4o. Emitir a family mantem os 4 corretos: quem
        roteia por provider recebe provider. A variante nao vaza para roster
        nenhum — desde o item 012 (D5) ela vive SOMENTE em
        `_resolve_interactive_main_llm_pair()`, leitor canonico sobrevivente
        (o contrato congelado do item 019, que a espelhava, foi removido).
        Inflar os 4 rosters com os slugs de variante e trabalho de outro item
        (C13 fecha a lista de radios; o roster externo permanece o eixo
        provider).

        Item 012 (D5): re-renderiza os itens ja enfileirados, como os demais
        handlers do eixo Main.
        """
        self._refresh_kimi_btn_visibility()
        self._refresh_flag_checkboxes_state()
        self._refresh_items_live_state()
        if checked:
            family, _variant = _MAIN_LLM_VARIANTS.get(slug, ("claude", None))
            signal_bus.main_llm_changed.emit(family)

    def _on_main_opus_toggled(self, checked: bool) -> None:
        """Main LLM `opus`: family `claude`, variante de modelo `opus`."""
        self._on_main_variant_toggled("opus", checked)

    def _on_main_sonnet_toggled(self, checked: bool) -> None:
        """Main LLM `sonnet`: family `claude`, variante de modelo `sonnet`."""
        self._on_main_variant_toggled("sonnet", checked)

    def _on_main_kimi_k3_toggled(self, checked: bool) -> None:
        """Main LLM `kimi-k3`: family `kimi`, variante de modelo `k3`.

        D-004-B: sob Main nao-Claude, `/model` e `/effort` sao REMOVIDOS no
        enqueue (llm-routing-div.md §14) e nao existe dialeto textual de
        modelo para o Kimi hoje (gap R-J3 aberto). Ou seja: a variante `k3` e
        carregada no contrato mas ainda nao tem tradutor de diretiva — decisao
        humana pendente, ver `## Decisoes abertas` da task 004.
        """
        self._on_main_variant_toggled("kimi-k3", checked)

    def _on_use_codex_toggled(self, checked: bool) -> None:
        """Parallel Worker Codex (T3). PW-01: exclusividade com grok."""
        if checked:
            if self._use_grok_chk.isChecked():
                self._use_grok_chk.blockSignals(True)
                self._use_grok_chk.setChecked(False)
                self._use_grok_chk.blockSignals(False)
                signal_bus.toast_requested.emit(
                    "Codex substituiu Grok no worker T3 (exclusividade PW-01)",
                    "info",
                )
            self._warn_main_worker_collision("codex")
        self._refresh_kimi_btn_visibility()
        self._persist_worker_selection()

    def _on_use_grok_toggled(self, checked: bool) -> None:
        """Parallel Worker Grok (T3). PW-01: exclusividade com codex."""
        if checked:
            if self._use_codex_chk.isChecked():
                self._use_codex_chk.blockSignals(True)
                self._use_codex_chk.setChecked(False)
                self._use_codex_chk.blockSignals(False)
                signal_bus.toast_requested.emit(
                    "Grok substituiu Codex no worker T3 (exclusividade PW-01)",
                    "info",
                )
            self._warn_main_worker_collision("grok")
        self._refresh_kimi_btn_visibility()
        self._persist_worker_selection()

    def _warn_main_worker_collision(self, worker_provider: str) -> None:
        """Item 020: toast de aviso quando Main e worker ocupam o mesmo provider.

        Nao bloqueia — apenas alerta sobre custo/rate-limit duplicado.
        """
        main_llm = self._resolve_interactive_main_llm()
        if main_llm == worker_provider:
            signal_bus.toast_requested.emit(
                f"Provider {worker_provider} ocupa Main (T1) e worker"
                " simultaneamente (custo/rate-limit)",
                "warning",
            )

    def _is_mimo_worker_live(self) -> bool:
        """Worker MiMo marcado E visivel por intencao de boot (fail-closed)."""
        chk = getattr(self, "_use_mimo_chk", None)
        visible = (getattr(self, "_worker_visible", None) or {}).get("mimo", False)
        return bool(chk is not None and visible and chk.isChecked())

    def current_worker_occupancy(self) -> tuple[str, str]:
        """Leitura publica da ocupacao viva dos pares de worker: ``(t2, t3)``.

        Delegador fino de `_resolve_worker_occupancy` (mesma precedencia, mesmo
        ``""`` para par vazio), para consumidores fora do eixo de checkboxes
        nao reimplementarem a resolucao.
        """
        return self._resolve_worker_occupancy()

    def _resolve_worker_occupancy(self) -> tuple[str, str]:
        """Resolve a ocupacao real dos pares de worker: ``(t2, t3)``.

        Precedencia por par (D1 no T2, a mesma do persist no T3):
        ``mimo`` senao ``kimi`` senao ``qwen`` senao ``""`` no T2 (``mimo``
        so quando `_is_mimo_worker_live()`: worker oculto nunca ocupa);
        ``codex`` senao ``grok`` senao ``""`` no T3. ``""`` significa PAR
        VAZIO (nenhum worker marcado), estado legitimo e distinto de
        "desconhecido". PW-01 ja deixa um so marcado por par; a precedencia
        e o desempate defensivo para estado programatico, legado ou de
        restore corrompido.

        Ponto UNICO de leitura dos checkboxes de worker para fins de ocupacao.
        Duas resolucoes lado a lado divergem com o tempo, e este metodo existe
        justamente porque uma copia divergiu: os modulos de recuperacao
        carregavam um mapa constante `workspace=kimi`/`workspace_xterm=codex`
        que passou a mentir quando o roster expandido expos qwen/grok
        (gap C24). `_persist_worker_selection` e `_emit_worker_occupancy` sao
        os dois consumidores.
        """
        def _on(name: str) -> bool:
            chk = getattr(self, name, None)
            return bool(chk is not None and chk.isChecked())

        if self._is_mimo_worker_live():
            t2 = "mimo"
        elif _on("_use_kimi_chk"):
            t2 = "kimi"
        elif _on("_use_qwen_chk"):
            t2 = "qwen"
        else:
            t2 = ""
        if _on("_use_codex_chk"):
            t3 = "codex"
        elif _on("_use_grok_chk"):
            t3 = "grok"
        else:
            t3 = ""
        return t2, t3

    def _emit_worker_occupancy(self) -> None:
        """Publica a ocupacao dos pares no `signal_bus` (emissor UNICO).

        Consumido por `MetricsBar._on_worker_occupancy_changed`, que a usa
        para nomear o LLM certo no snapshot diagnostico e no toast da
        auto-recuperacao. Emissao repetida e inofensiva: o consumidor apenas
        escreve cache.
        """
        t2, t3 = self._resolve_worker_occupancy()
        signal_bus.worker_occupancy_changed.emit(t2, t3)

    def _persist_worker_selection(self) -> None:
        """Item 020: salva selecao de worker no QSettings.

        Persiste qual provider esta marcado em cada terminal (T2/T3).
        Chave: ``worker/t2_selected`` e ``worker/t3_selected``.

        Item 013 (C24): a resolucao saiu daqui para `_resolve_worker_occupancy`
        e a mesma ocupacao persistida e emitida no `signal_bus` - persistir sem
        emitir deixaria o MetricsBar com a ocupacao anterior ate o proximo
        boot.
        """
        stg = QSettings("systemForge", "workflow-app")
        t2, t3 = self._resolve_worker_occupancy()
        stg.setValue("worker/t2_selected", t2)
        stg.setValue("worker/t3_selected", t3)
        # ST003.1 (toggle): os handlers `_on_use_*_toggled` ja chamam este
        # metodo, entao um emit aqui cobre todos sem uma edicao por handler.
        # A troca PW-01 tambem fica coberta: o handler do checkbox recem-marcado
        # roda DEPOIS da desmarcacao do par (que usa blockSignals), entao o
        # consumidor observa o estado final, nunca um `("", "")` intermediario.
        self._emit_worker_occupancy()

    def _restore_worker_selection(self) -> None:
        """Item 020: restaura selecao de worker do QSettings.

        blockSignals para nao disparar PW-01 durante restore.

        Worker oculto por kill-switch (intencao de boot em `_worker_visible`)
        nunca volta marcado: o QSettings de uma sessao com o roster ligado nao
        pode vazar worker invisivel para a ocupacao. O QSettings NAO e
        regravado aqui, entao a selecao reaparece quando o switch religar.
        """
        stg = QSettings("systemForge", "workflow-app")
        t2 = stg.value("worker/t2_selected", "")
        t3 = stg.value("worker/t3_selected", "")
        _visible = getattr(self, "_worker_visible", None) or {
            "kimi": True,
            "codex": True,
        }

        for chk, name in (
            (self._use_kimi_chk, "kimi"),
            (self._use_qwen_chk, "qwen"),
            (self._use_mimo_chk, "mimo"),
        ):
            chk.blockSignals(True)
            chk.setChecked(t2 == name and _visible.get(name, False))
            chk.blockSignals(False)

        for chk, name in (
            (self._use_codex_chk, "codex"),
            (self._use_grok_chk, "grok"),
        ):
            chk.blockSignals(True)
            chk.setChecked(t3 == name and _visible.get(name, False))
            chk.blockSignals(False)

        # ST003.2 (C24): emitir FORA do blockSignals. `blockSignals` silencia
        # os sinais dos QCheckBox, entao os handlers `_on_use_*_toggled` NAO
        # rodam no restore - um emit pendurado so neles deixaria o MetricsBar
        # com ocupacao desconhecida ate o primeiro clique, isto e, exatamente
        # na sessao recem-aberta, que e quando a auto-recuperacao mais dispara.
        self._emit_worker_occupancy()

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
            # Mesma elegibilidade T2 do router (`is_t2_eligible`): comando de
            # imagem nunca ganha seta worker, nem com `kimi_eligible`.
            visible = is_t2_eligible(spec.name, kimi_eligible=spec.kimi_eligible)
            item.set_worker_arrow_visible(visible)

    def _on_flag_toggled(self, checked: bool) -> None:
        """Eixo-flag (item 004): marcar/desmarcar --kimi/--codex re-renderiza os
        labels dos itens T1 imediatamente, sem toast, sem reiniciar a fila e sem
        tocar o estado de execucao.

        Idempotente: o sufixo e sempre recomputado do zero a partir de spec.name
        via render_with_mcp_flags, entao toggles repetidos nunca acumulam nem
        duplicam flags. Espelha os handlers _on_use_*_toggled do eixo-worker.

        Item 012 (D5) — CONTRATO AFIRMADO, nao efeito colateral tolerado: o
        re-render RETROATIVO do label e do `dispatch_text` de itens JA
        enfileirados e o comportamento DESEJADO. Ate o item 011 ele era gap
        (C15) porque convivia com o contrato congelado do item 019, e as duas
        metades diziam coisas diferentes: o label mostrava a flag nova e o step
        despachava a flag velha. Removido o congelamento, o step passou a ler
        `_active_mcp_flags()` vivo — label e dispatch voltaram a concordar, e
        C15 fechou por INVERSAO DE SINAL. Este handler NAO foi revogado nem
        alterado: so o contrato que ele cumpre mudou de "tolerado" para
        "afirmado e testado" (`test_flag_toggle_is_retroactive`).

        Item 021: tambem espelha o estado no FlagsPanel (aba LLM Config).
        """
        _ = checked
        self._sync_flags_panel_to_mirror()
        self._refresh_flag_suffix()

    def _on_flags_panel_changed(self) -> None:
        """Slot de ``FlagsPanel.flags_changed`` (painel embutido em queue-div-flag).

        Quando o painel e a fonte unica (flag ON), nao ha espelho a sincronizar:
        os checkboxes do painel JA sao `self._flag_*_chk`. Basta re-renderizar
        o sufixo dos labels. Ate 2026-08-17 o sinal nem existia — o handler
        fazia `if hasattr(self, "flags_changed")`, sempre False, e as 7
        checkboxes eram controles mortos (Zero Silencio violado).
        """
        self._refresh_flag_suffix()

    def _active_mcp_flags(self) -> list[str]:
        """Le o estado das flags MCP ativas.

        Item 021: le do FlagsPanel (aba LLM Config) quando disponivel; fallback
        para os checkboxes locais queue-chk-flag-* (retrocompat).
        Ordem de entrada preservada (dedupe/ordenacao final ficam no helper puro
        render_with_mcp_flags)."""
        # Item 021: FlagsPanel como fonte canonica quando disponivel.
        flags_panel = self._get_flags_panel()
        if flags_panel is not None:
            try:
                return flags_panel.checked_flags()
            except RuntimeError:
                pass
        # Fallback: checkboxes locais do command_queue. Flag inativa sob o
        # Main resolvido (auto-proxy, redundante ou kill-switch) fica fora do
        # sufixo, pela MESMA regra de `FlagsPanel.checked_flags` (achado
        # F2-corretude-1): sem o filtro um `--kimi` marcado antes da troca
        # para Main MiMo seguia no payload, cinza mas `isChecked()`, e o
        # `--codex` vazava do mesmo jeito sob Main Kimi (C-43/R-40). O
        # checkbox nunca e desmarcado: a escolha do operador volta a valer
        # quando o Main volta a aceitar a flag.
        from workflow_app.llm_config.flags_panel import inactive_flags_for_main

        inactive = inactive_flags_for_main(self._resolve_interactive_main_llm())
        flags: list[str] = []
        for flag, attr in (
            ("--mimo", "_flag_mimo_chk"),
            ("--kimi", "_flag_kimi_chk"),
            ("--codex", "_flag_codex_chk"),
        ):
            chk = getattr(self, attr, None)
            if chk is not None and chk.isChecked() and flag not in inactive:
                flags.append(flag)
        return flags

    def _get_flags_panel(self):
        """Acessa o FlagsPanel de `queue-div-flag` (item 021).

        Prioriza o painel EMBUTIDO na propria div; o lookup pelo MainWindow
        continua como fallback para o periodo em que o painel morava num
        container irmao. Retorna None quando a aba esta desabilitada
        (kill-switch) ou o widget ainda nao foi construido.
        """
        panel = getattr(self, "_flags_panel", None)
        if panel is not None:
            return panel
        try:
            main_win = self.window()
            return getattr(main_win, "_llm_config_flags_panel", None)
        except Exception:  # noqa: BLE001
            return None

    def _sync_flags_panel_to_mirror(self) -> None:
        """Espelha o estado do FlagsPanel nos checkboxes locais (item 021).

        Bidirecional: quando o FlagsPanel muda, os checkboxes locais refletem;
        quando os checkboxes locais mudam, o FlagsPanel reflete. Usa
        blockSignals para evitar loop de feedback.
        """
        flags_panel = self._get_flags_panel()
        if flags_panel is None:
            return
        # Painel EMBUTIDO: os checkboxes locais SAO os do painel. Espelhar aqui
        # reescreveria o painel a partir de uma leitura parcial dele mesmo e
        # apagaria silenciosamente as flags sem alias legado.
        if flags_panel is getattr(self, "_flags_panel", None):
            return
        try:
            active = self._active_mcp_flags_from_local()
            flags_panel.set_flag_states_from_mirror(active)
        except RuntimeError:
            pass

    def _active_mcp_flags_from_local(self) -> list[str]:
        """Le checkboxes locais queue-chk-flag-* (sem passar pelo FlagsPanel).

        Percorre os literais canonicos vigentes, e nao so os legados: sob a
        flag ON, `_flag_<slug>_chk` existe para todos eles (aliases dos
        checkboxes do painel embutido). Sob a flag OFF so os checkboxes
        legados existem e o resultado e identico ao de antes.

        Sem o filtro de flags inativas de `_active_mcp_flags` de proposito:
        esta leitura so alimenta `set_flag_states_from_mirror` do painel
        externo, e filtrar aqui DESMARCARIA no painel a flag inativa
        (a escolha do operador sumiria em vez de voltar com o Main). O
        sufixo do painel ja sai filtrado por `FlagsPanel.checked_flags`.
        """
        from workflow_app.config.llm_flags import _FLAG_CANONICAL_ORDER

        flags: list[str] = []
        for flag in _FLAG_CANONICAL_ORDER:
            chk = getattr(
                self, f"_flag_{flag.lstrip('-').replace('-', '_')}_chk", None
            )
            if chk is not None and chk.isChecked():
                flags.append(flag)
        return flags

    def _refresh_flag_suffix(self) -> None:
        """Recomputa e aplica o sufixo de flags MCP no label de cada item da fila.

        Contraparte do eixo-flag ao _refresh_kimi_btn_visibility (eixo-worker).
        Fila vazia (self._items sem itens) = no-op. Para cada item delega a
        decisao ao helper puro render_with_mcp_flags: I2 (/clear, /model,
        /effort, local-action) saem limpos; I3 (itens roteados a worker T2/T3 ou
        Desabilitado) saem sem flags; so T1 Claude recebe o sufixo. O sufixo
        passado a set_flag_suffix e a diferenca entre o render e spec.name (o
        render sempre comeca por spec.name), entao itens inelegiveis recebem "" e
        ficam inalterados. O recompute-do-zero garante idempotencia (I1: spec.name
        nunca e mutado).

        Item 012: tambem chama set_dispatch_text com o texto completo (nome +
        flags + config_path) via command_text_with_flags. Isso garante que os
        caminhos per-item run e per-item copy (que leem dispatch_text()) produzem
        a mesma string que mass copy e autocast (paridade dos quatro caminhos).
        """
        active_flags = self._active_mcp_flags()
        for item in self._items:
            spec = item.get_spec()
            provider = self._resolve_item_provider(spec)
            rendered = render_with_mcp_flags(
                spec,
                for_dispatch=False,
                provider=provider,
                active_flags=active_flags,
            )
            suffix = rendered[len(spec.name):].strip()
            item.set_flag_suffix(suffix)
            # Item 012: seta o texto completo de dispatch (com flags + config_path)
            # no widget, para que per-item run/copy usem o produtor unico.
            full_dispatch = command_text_with_flags(
                spec,
                provider=provider,
                active_flags=active_flags,
            )
            item.set_dispatch_text(full_dispatch)

    def _refresh_items_live_state(self) -> None:
        """Ponto UNICO de re-render dos itens ja enfileirados (item 012 / D5).

        Sob o regime de estado vivo, tudo que a UI mostra num item enfileirado
        tem que ser funcao do estado corrente — nao do estado do enqueue. Este
        metodo e o unico lugar que reafirma isso, e ele delega:

          - sufixo de flags + `dispatch_text` -> `_refresh_flag_suffix()`
            (chamado, NAO duplicado: o objetivo e UM ponto de re-render, nao
            dois lacos que divergem na proxima mudanca);
          - badge de dialeto -> `is_suppressed_directive` (predicado PURO, o
            mesmo que espelha os cinco dispatchers).

        Idempotente: `_refresh_flag_suffix` recomputa o sufixo do zero a partir
        de `spec.name` (I1 — `spec.name` nunca e mutado), e o badge e um
        `setVisible` booleano. Toggles repetidos nao acumulam.

        Fila vazia = no-op (o laco nao itera).
        """
        self._refresh_flag_suffix()
        main_llm = self._resolve_interactive_main_llm()
        for item in self._items:
            spec = item.get_spec()
            suppressed = is_suppressed_directive(spec.name, main_llm)
            tooltip = (
                f"Diretiva nao suportada pelo Main {main_llm}: sera suprimida "
                "no dispatch (pulso de listener), nada chega ao terminal."
                if suppressed
                else ""
            )
            item.set_dialect_badge(suppressed, tooltip)

    def _refresh_flag_checkboxes_state(self) -> None:
        """Atualiza enabled/tooltip das checkboxes de flag (item 021).

        Regras:
          - Kill-switch SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0: todas
            desabilitadas **sob Main nao-Claude** (source.md:444). Sob Main
            Claude o kill-switch nao tem efeito — o nome diz o escopo: ele
            freia a paridade de delegacao *non-Claude*, e nao existe delegacao
            non-Claude a frear quando o proprio Main ja e Claude.
          - Main == Claude: todas habilitadas.
          - Main != Claude: flag cujo provider bate com o Main -> disabled
            (redundante, tabela `_REDUNDANT_FLAG_MAINS`); demais habilitadas.
          - **C-43 (R-40): Main == Kimi -> `--codex` e `--codex-ultra`
            (tabela `_AUTOPROXY_FLAGS_BY_MAIN`) disabled com tooltip citando
            auto-proxy.** As skills de provider do lado Kimi
            (`.kimi/skills/codex`) sao auto-proxies: marcar `--codex` sob Main
            Kimi seria intencao explicita aceita e silenciosamente convertida
            em auto-consulta. Desabilitar com motivo visivel e a resolucao
            honesta (source.md §10.15, ponto 1) — Zero Silencio.
          - **Main == MiMo -> `--mimo`/`--mimo-pro` disabled (redundantes) e
            `--kimi`/`--kimi-k3` disabled por auto-proxy (MiMo > Kimi,
            2026-10-02)**, pela mesma tabela `_AUTOPROXY_FLAGS_BY_MAIN`: com a
            MiMo no T1 nenhum caminho escolhe o Kimi.

        O conjunto desabilitado aqui e o mesmo que `_active_mcp_flags` tira do
        payload (`inactive_flags_for_main`): flag cinza nunca vai no sufixo.

        Sob v2 os checkboxes SAO os do `FlagsPanel` embutido em
        `queue-div-flag`; delegamos para `FlagsPanel.set_main_llm`, que
        implementa exatamente estas regras. Manter duas implementacoes das
        mesmas regras sobre os mesmos widgets e a armadilha DUP-01: a proxima
        flag entraria numa so das duas. Por isso o loop legado abaixo le as
        MESMAS tabelas do painel (`_AUTOPROXY_FLAGS_BY_MAIN`,
        `_REDUNDANT_FLAG_MAINS`, `_MIMO_SUPERSEDES`) e o mesmo texto de
        auto-proxy (`autoproxy_tooltip`).
        """
        from workflow_app.config import delegation_flags_nonclaude_enabled
        from workflow_app.config.llm_flags import (
            _AUTOPROXY_FLAGS_BY_MAIN,
            _MIMO_SUPERSEDES,
            _REDUNDANT_FLAG_MAINS,
            _SUPPORTED_MCP_FLAGS,
        )
        from workflow_app.llm_config.flags_panel import autoproxy_tooltip

        main_llm = self._resolve_interactive_main_llm()

        def _t1_tooltip(flag: str) -> str:
            # Precedencia MiMo > Kimi (2026-10-02) lida de `_MIMO_SUPERSEDES`
            # do regime vigente, a mesma tabela do FlagsPanel e de
            # `render_with_mcp_flags`: a chave avisa que vence o par, o par
            # avisa que sai do payload. Sem isso o refresh apagava a
            # explicacao que o checkbox mostra desde a construcao.
            precedence = ""
            losers = _MIMO_SUPERSEDES.get(flag)
            if losers:
                precedence = (
                    "Lane T2: vence o " + " e o ".join(sorted(losers))
                    + " quando os dois estao marcados. "
                )
            else:
                for winner, superseded in _MIMO_SUPERSEDES.items():
                    if flag in superseded:
                        precedence = (
                            "Lane T2: se " + winner + " tambem estiver "
                            "marcado, a MiMo vence e o " + flag
                            + " sai do payload. "
                        )
                        break
            return (
                "Quando marcado, anexa " + flag + " ao label dos itens T1 (Claude). "
                + precedence
                + "Nunca afeta /clear, /model, /effort, local-action nem itens worker."
            )

        panel = getattr(self, "_flags_panel", None)
        if panel is not None:
            try:
                panel.set_main_llm(main_llm)
                return
            except RuntimeError:
                # painel ja destruido em rebuild: cai no caminho legado
                pass

        ks_enabled = delegation_flags_nonclaude_enabled()

        for flag in _SUPPORTED_MCP_FLAGS:
            chk = getattr(self, f"_flag_{flag.lstrip('-').replace('-', '_')}_chk", None)
            if chk is None:
                continue
            if not ks_enabled and main_llm != "claude":
                chk.setEnabled(False)
                chk.setToolTip(
                    "Paridade de flags desabilitada pelo kill-switch "
                    "SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0."
                )
                continue
            if main_llm == "claude":
                chk.setEnabled(True)
                chk.setToolTip(_t1_tooltip(flag))
                continue
            if flag in _AUTOPROXY_FLAGS_BY_MAIN.get(main_llm, frozenset()):
                # Auto-proxy: C-43 / R-40 sob Main kimi, MiMo > Kimi sob Main
                # mimo. Precede a regra de redundancia, como no painel.
                chk.setEnabled(False)
                chk.setToolTip(autoproxy_tooltip(flag, main_llm))
            elif _REDUNDANT_FLAG_MAINS.get(flag) == main_llm:
                chk.setEnabled(False)
                chk.setToolTip(flag + " redundante sob Main " + main_llm + ".")
            else:
                chk.setEnabled(True)
                chk.setToolTip(_t1_tooltip(flag))

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
    _QWEN_SLASH_EXECUTOR_INVOCATION = "/slash-executor"
    _GROK_SLASH_EXECUTOR_INVOCATION = "/slash-executor"
    _GROK_DELEGATION_RUNTIME_FLAG = "--delegation-runtime=grok"
    # Main MiMo (T1): executor nativo `.mimocode/commands/slash-executor.md`.
    # Contrato do payload em ai-forge/rules/mimo-code-cli-contract.md.
    _MIMO_DELEGATION_RUNTIME_FLAG = "--delegation-runtime=mimo"
    # O loader do CLI mimocode expande shell no host ao carregar o template de
    # comando customizado (contrato, secao 7): payload slash com este token e
    # recusado no builder, antes de qualquer transformacao.
    _MIMO_SHELL_EXPANSION_TOKEN = "!`"
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

    @classmethod
    def _kimi_executor_prefix(cls) -> str:
        return f"/skill:{cls._KIMI_SLASH_EXECUTOR_SKILL}"

    @classmethod
    def _starts_with_invocation(cls, stripped: str, invocation: str) -> bool:
        return stripped == invocation or stripped.startswith(invocation + " ")

    @classmethod
    def _build_qwen_slash_executor_invocation(
        cls, cmd_text: str, *, recovery_mode: bool = False
    ) -> str:
        """Route Main Qwen slash commands through the native `/slash-executor`.

        Qwen TUI resolves `/slash-executor` (skill name, no `/skill:` prefix).
        Leftover Kimi dialect `/skill:slash-executor ...` is rewritten to the
        native form so old queue snapshots still run. Other `/skill:` wrappers
        stay intact. Recovery injects `--recovery-mode` the same way as Kimi.
        """
        stripped = cmd_text.lstrip()
        if not stripped.startswith("/"):
            return cmd_text
        leading = cmd_text[: len(cmd_text) - len(stripped)]
        native = cls._QWEN_SLASH_EXECUTOR_INVOCATION
        if cls._starts_with_invocation(stripped, native):
            return cmd_text
        kimi_prefix = cls._kimi_executor_prefix()
        if cls._starts_with_invocation(stripped, kimi_prefix):
            return f"{leading}{native}{stripped[len(kimi_prefix):]}"
        if stripped.startswith("/skill:"):
            return cmd_text
        flag = ""
        if recovery_mode and cls._normalized_slash_slug(stripped) == cls._RECOVERY_SLUG:
            flag = "--recovery-mode "
        return f"{leading}{native} {flag}{stripped}"

    @classmethod
    def _build_grok_slash_executor_invocation(
        cls,
        cmd_text: str,
        *,
        recovery_mode: bool = False,
        runtime_flag: str | None = None,
    ) -> str:
        """Route Grok slash commands through native `/slash-executor`.

        Grok TUI resolves `/slash-executor` (command in `.grok/commands/`).
        Fresh wraps always inject `--delegation-runtime=grok`. Leftover Kimi
        dialect `/skill:slash-executor ...` is rewritten to the native form.
        Other `/skill:<slug>` wrappers are rewritten to `/<slug>` then wrapped
        — Grok TUI does not speak `/skill:`. Already-native `/slash-executor
        ...` is returned unchanged (no double-wrap). Recovery injects
        `--recovery-mode` after the delegation flag, before the target slash.
        PromptCompiler and Codex envelope stay out of this builder.
        """
        stripped = cmd_text.lstrip()
        if not stripped.startswith("/"):
            return cmd_text
        leading = cmd_text[: len(cmd_text) - len(stripped)]
        native = cls._GROK_SLASH_EXECUTOR_INVOCATION
        if cls._starts_with_invocation(stripped, native):
            return cmd_text
        kimi_prefix = cls._kimi_executor_prefix()
        if cls._starts_with_invocation(stripped, kimi_prefix):
            remainder = stripped[len(kimi_prefix):].lstrip()
            if remainder.startswith("/"):
                return cls._build_grok_slash_executor_invocation(
                    f"{leading}{remainder}",
                    recovery_mode=recovery_mode,
                    runtime_flag=runtime_flag,
                )
            return cls._wrap_grok_slash_executor(
                leading,
                remainder,
                recovery_mode=recovery_mode,
                runtime_flag=runtime_flag,
            )
        if stripped.startswith("/skill:"):
            rest = stripped[len("/skill:"):]
            if not rest:
                return cmd_text
            rewritten = f"/{rest}"
            return cls._build_grok_slash_executor_invocation(
                f"{leading}{rewritten}",
                recovery_mode=recovery_mode,
                runtime_flag=runtime_flag,
            )
        return cls._wrap_grok_slash_executor(
            leading, stripped, recovery_mode=recovery_mode, runtime_flag=runtime_flag
        )

    @classmethod
    def _build_mimo_slash_executor_invocation(
        cls, cmd_text: str, *, recovery_mode: bool = False
    ) -> str:
        """Route Main MiMo slash commands through native `/slash-executor`.

        Mesmo dialeto do Grok (`.mimocode/commands/slash-executor.md`), com
        `--delegation-runtime=mimo`. Contrato do CLI
        (ai-forge/rules/mimo-code-cli-contract.md): o payload termina com
        exatamente UM espaco, que fecha o popup de autocomplete do TUI e
        preserva o texto, e nenhum no inicio; o Enter vai num write separado
        (output_panel). Texto que nao e slash volta inalterado.

        Levanta ValueError quando o texto slash contem "!`": o CLI expande
        shell no host ao carregar o template (contrato, secao 7).
        """
        if (
            cmd_text.lstrip().startswith("/")
            and cls._MIMO_SHELL_EXPANSION_TOKEN in cmd_text
        ):
            raise ValueError(
                f'payload slash com "{cls._MIMO_SHELL_EXPANSION_TOKEN}" recusado: '
                "o CLI mimocode expande shell no host ao carregar o template do "
                "comando (ver ai-forge/rules/mimo-code-cli-contract.md)."
            )
        wrapped = cls._build_grok_slash_executor_invocation(
            cmd_text,
            recovery_mode=recovery_mode,
            runtime_flag=cls._MIMO_DELEGATION_RUNTIME_FLAG,
        )
        if not wrapped.lstrip().startswith("/"):
            return wrapped
        return wrapped.strip() + " "

    @classmethod
    def _wrap_grok_slash_executor(
        cls,
        leading: str,
        target: str,
        *,
        recovery_mode: bool,
        runtime_flag: str | None = None,
    ) -> str:
        """Compose `/slash-executor --delegation-runtime=grok [--recovery-mode] <slash>`.

        Flag order matches the Task 02/06 aceite: delegation runtime first,
        then recovery, then the target slash. `_split_executor_flags` strips
        leftover executor flags from snapshots so they are not double-copied
        into the target command.
        """
        native = cls._GROK_SLASH_EXECUTOR_INVOCATION
        clean, _runtime, recovery_from_text = cls._split_executor_flags(target)
        body = clean.lstrip()
        slug_src = body if body.startswith("/") else (f"/{body}" if body else "")
        flags = [runtime_flag or cls._GROK_DELEGATION_RUNTIME_FLAG]
        if (recovery_mode or recovery_from_text) and (
            cls._normalized_slash_slug(slug_src) == cls._RECOVERY_SLUG
        ):
            flags.append("--recovery-mode")
        flag_str = " ".join(flags)
        if not body:
            return f"{leading}{native} {flag_str}"
        if not body.startswith("/"):
            body = f"/{body}"
        return f"{leading}{native} {flag_str} {body}"

    @classmethod
    def _route_blue_arrow_through_universal(cls, kimi_prompt: str) -> str:
        """FIX-011 Opt 1 — aplica ao dispatch blue-arrow (worker Kimi T2) a MESMA
        decisao de roteamento do caminho de insercao interativo (`_render_*`,
        L7702-7742): comandos reais passam pelo executor universal
        (`/skill:slash-executor`, que carrega o `<LISTENER_FINALIZATION_CONTRACT>`),
        em vez do wrapper BARE (`/skill:<slug>` produzido por `adapt_to_kimi`),
        que NAO roda a FASE FINAL -> stuck-yellow (caso 011, debug.md).

        Espelha EXATAMENTE as excecoes do roteamento canonico (L7729), para
        nao romper contratos especificos de wrapper:
          - `/skill:slash-executor ...` (recovery/programatico) -> intacto (idempotente);
          - alvo sem `.claude/command` (skill-only) -> permanece BARE;
          - `_kimi_requires_specific_wrapper(slug)` (channel-binding / dedupe /
            autocast standalone) -> permanece BARE.
        NAO toca `adapt_to_kimi` (funcao pura com testes de igualdade exata).
        Canal do worker = `workspace` (injetado no PTY por output_panel.py)."""
        stripped = kimi_prompt.lstrip()
        if not stripped.startswith("/skill:"):
            return kimi_prompt
        leading = kimi_prompt[: len(kimi_prompt) - len(stripped)]
        rest = stripped[len("/skill:"):]
        parts = rest.split(None, 1)
        head = parts[0] if parts else ""
        if head == cls._KIMI_SLASH_EXECUTOR_SKILL:
            return kimi_prompt  # ja universal -> intacto (nao re-envelopa)
        slug = head  # adapt_to_kimi: `/<slug>` -> `/skill:<slug>`, logo head == slug
        if (
            not slug
            or cls._resolve_claude_command_file(slug) is None
            or cls._kimi_requires_specific_wrapper(slug)
        ):
            return kimi_prompt  # mantem BARE (identico a L7729)
        raw = f"{leading}/{rest}"  # inverso exato do adapt_to_kimi
        return cls._build_kimi_slash_executor_invocation(raw)

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

    # Runtimes de delegacao autorizados pelo executor universal (C8/C9).
    # Nao existe runtime default: ausencia significa que o caller nao declarou
    # identidade e o executor assume o proprio runtime.
    _DELEGATION_RUNTIMES: tuple[str, ...] = ("kimi", "codex", "grok", "qwen", "mimo")

    @classmethod
    def _split_executor_flags(
        cls,
        cmd_text: str,
        *,
        default_runtime: str | None = None,
    ) -> tuple[str, str | None, bool]:
        """Separa flags de executor (`--recovery-mode`, `--delegation-runtime=`)
        do texto do comando alvo.

        Retorna uma tripla `(clean_text, runtime, recovery)` onde:
          - `clean_text` e o comando original SEM as flags de executor.
          - `runtime` e o valor de `--delegation-runtime=` quando presente e
            valido, senao `default_runtime` (por default `None`, que significa
            "o caller NAO declarou runtime"). Nao inventamos `kimi` aqui: o
            envelope omite `Executing runtime identity:` quando o runtime e
            desconhecido, e o executor assume a identidade do proprio runtime
            (contrato de `executor-de-slash-commands-rules.md`, L30/L32/L33).
          - `recovery` indica se `--recovery-mode` estava presente.

        Regras (alinhadas a `<RESOLVE_COMMAND>` de slash-executor):
          - Apenas tokens no inicio do comando (antes do slash alvo) sao
            consumidos como flags de executor.
          - `--recovery-mode` e reconhecido como flag booleano.
          - `--delegation-runtime=<id>` exige `<id>` em `_DELEGATION_RUNTIMES`;
            valor vazio/invalido deixa `runtime` como `default_runtime` e NAO
            remove o token (o executor la embaixo decidira o bloqueio).
          - Flags do eixo intra-comando (`--kimi`, `--codex`, etc.) NAO sao
            removidas; elas viajam como argumentos do comando alvo.
          - Preserva whitespace leading/trailing e a ordem canonica:
            `--recovery-mode` primeiro, depois `--delegation-runtime=`, depois
            o comando alvo e seus argumentos.
        """
        leading_len = len(cmd_text) - len(cmd_text.lstrip())
        leading = cmd_text[:leading_len]
        recovery = False
        runtime: str | None = None
        cursor = leading_len
        consumed = False

        # Escaneia somente o prefixo de flags do executor. Usar split/join aqui
        # alterava tabs, espacos repetidos e whitespace terminal mesmo quando
        # nenhuma flag era consumida, violando a identidade C-35.
        while cursor < len(cmd_text):
            token_match = re.match(r"\S+", cmd_text[cursor:])
            if token_match is None:
                break
            tok = token_match.group(0)
            if tok == "--recovery-mode":
                recovery = True
            elif tok.startswith("--delegation-runtime="):
                value = tok.split("=", 1)[1]
                # So consome o token quando o valor e valido. Valor invalido
                # deixa o token no comando alvo, para que o executor la embaixo
                # bloqueie com reason BLOCKED (fail-closed no ponto mais cedo).
                if value in cls._DELEGATION_RUNTIMES:
                    runtime = value
                else:
                    break
            else:
                break

            consumed = True
            cursor += token_match.end()
            while cursor < len(cmd_text) and cmd_text[cursor].isspace():
                cursor += 1

        # Fast path deliberado: sem flag consumida, devolve o mesmo objeto de
        # texto byte a byte, inclusive whitespace nao canonico.
        if not consumed:
            return cmd_text, default_runtime, False

        clean = f"{leading}{cmd_text[cursor:]}"
        # Preserva o fail-closed legado para uma entrada composta apenas pelas
        # flags do executor: sem comando alvo, nao fabrica payload vazio.
        if not clean.strip():
            clean = cmd_text.lstrip()
        return (
            clean,
            runtime if runtime is not None else default_runtime,
            recovery,
        )

    @classmethod
    def _intra_command_flag_literals(cls) -> tuple[str, ...]:
        """Literais de flag intra-comando reconhecidas no envelope (C8).

        DERIVADO de `llm_flags._FLAG_CANONICAL_ORDER`, a fonte canonica unica
        do conjunto fechado (boot-frozen pelo kill-switch dedicado que o
        proprio `llm_flags` consulta uma unica vez):
        regime legado = roster C26 mais `--mimo` (`_LEGACY_FLAG_ORDER`);
        regime v2 = `_FULL_FLAG_CANONICAL_ORDER`. NAO reescrever a
        lista aqui: uma copia local diverge do conjunto vigente e volta a
        deixar flags armadas invisiveis no envelope de delegacao.
        """
        from workflow_app.config.llm_flags import _FLAG_CANONICAL_ORDER

        return tuple(_FLAG_CANONICAL_ORDER)

    @classmethod
    def _intra_command_flags(cls, cmd_text: str) -> list[str]:
        """Retorna as flags intra-comando presentes em `cmd_text`, em ordem.

        Apenas literais de `_intra_command_flag_literals()` sao reconhecidas;
        nao remove nada do texto original. O resultado e usado para preencher a
        linha `Delegation flags:` do envelope sem duplicar ou reordenar.
        """
        supported = cls._intra_command_flag_literals()
        seen: set[str] = set()
        result: list[str] = []
        for tok in cmd_text.split():
            if tok in supported and tok not in seen:
                seen.add(tok)
                result.append(tok)
        return result

    @classmethod
    def _delegation_envelope_block(
        cls, cmd_text: str, runtime: str | None
    ) -> str:
        """Bloco OPCIONAL do envelope de delegacao (C8).

        As duas linhas sao emitidas SOMENTE quando ha o que declarar:
          - `Delegation flags:` so aparece quando existe flag intra-comando
            armada no comando alvo;
          - `Executing runtime identity:` so aparece quando o caller declarou o
            runtime via `--delegation-runtime=<id>`.

        Sem nenhuma das duas condicoes o bloco e vazio e o payload volta a ser
        byte-identico ao envelope pre-C8 (criterio C-35 do item 010). Emitir
        `(none)` ou um `kimi` inventado violava esse criterio e ainda mentia
        sobre a identidade do runtime quando o Codex era quem executava. A
        ausencia das linhas ja tem semantica definida no contrato do executor:
        "Ausente = assuma a identidade do proprio runtime".

        O retorno ja inclui o `\n` terminal de cada linha emitida, para que o
        callsite possa concatenar sem produzir linha em branco no caso vazio.
        """
        lines: list[str] = []
        flags = cls._intra_command_flags(cmd_text)
        if flags:
            lines.append(f"Delegation flags: {' '.join(flags)}")
        if runtime:
            lines.append(f"Executing runtime identity: {runtime}")
        return "".join(f"{line}\n" for line in lines)

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
        "- For normal slash commands, never execute the target markdown's "
        "literal `## FASE FINAL`, autocast, or `wf-notify` shell block. That "
        "block reads the last helper shell `$?` and can emit false failure/red "
        "after a successful Codex execution. Treat it as transport reference "
        "only; emit the single semantic final notify yourself at the real end. "
        "The only exception is the dedicated recovery-mode dispatch for "
        "`tools:listener-recovery`.\n\n"
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
        # C8: separa flags de executor ANTES de resolver o slug. Um token
        # `--delegation-runtime=codex` no inicio faria `stripped` comecar por
        # `-` e a diretiva devolveria o texto cru sem envelope nenhum (mesmo
        # cuidado ja tomado em `_build_codex_slash_executor_prompt`).
        clean_text, runtime, _recovery = cls._split_executor_flags(cmd_text)
        stripped = clean_text.strip()
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
            f"{cls._delegation_envelope_block(clean_text, runtime)}"
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
        # C8: separa flags de executor (`--recovery-mode`, `--delegation-runtime=`)
        # do texto que vira Command/Arguments. Fazemos isso ANTES de resolver o
        # comando, senao um token `--delegation-runtime=codex` no inicio faria o
        # slug resolver para um valor invalido e retornaria None.
        clean_text, runtime, recovery_from_text = cls._split_executor_flags(cmd_text)
        stripped = clean_text.strip()
        clean_stripped = stripped
        _, _, clean_args = clean_stripped.partition(" ")
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
            (recovery_mode or recovery_from_text)
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
                f"{cls._delegation_envelope_block(clean_text, runtime)}"
                "Recovery mode: enabled by caller\n"
                f"Command: {clean_stripped}\n"
                f"Command markdown: {command_file}\n"
                f"Arguments: {clean_args.strip() or '(none)'}\n\n"
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
            f"{cls._delegation_envelope_block(clean_text, runtime)}"
            f"Command: {clean_stripped}\n"
            f"Command markdown: {command_file}\n"
            f"Arguments: {clean_args.strip() or '(none)'}\n\n"
            + cls._CODEX_LISTENER_FINALIZATION_CONTRACT
            + "Protocol:\n"
            "1. Read the executor rules file first.\n"
            "2. Read the listener rules file before running any finalization block.\n"
            "3. Read the command markdown file exactly as the source of truth.\n"
            "4. Parse frontmatter as execution metadata, then execute the markdown body.\n"
            "5. Resolve project variables from .claude/project.json and "
            ".codex/codex-project.json when present.\n"
            "6. Respect the listener contract: if the command has a "
            "`## FASE FINAL`, autocast, or wf-notify block, DO NOT execute that "
            "literal target block in normal Codex mode. It is a Claude-shell "
            "`$?` transport reference and can turn an incidental nonzero helper "
            "command into false failure/red. Instead, emit exactly one "
            f"semantic final notify for channel `{channel}` at the real end. "
            "Do not prefix the pasted command with WF_CHANNEL_OVERRIDE and do "
            "not hardcode a different channel.\n"
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

        `llm`: "claude" | "codex" | "kimi" | "qwen" | "grok".
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

        # /clear: raw para os LLM (todos entendem).
        if head == "/clear":
            return RenderedInsertion(text=text, listener_channel=listener_channel)

        # Claude: publica o comando raw sempre (o REPL resolve). Sem checagem de existencia.
        if llm == "claude":
            return RenderedInsertion(text=text, listener_channel=listener_channel)

        # Texto livre / path / persona (nao-slash): passthrough para qualquer LLM.
        if not head.startswith("/"):
            return RenderedInsertion(text=text, listener_channel=listener_channel)

        slug = head[1:]

        if llm in ("kimi", "qwen"):
            build_executor = (
                cls._build_qwen_slash_executor_invocation
                if llm == "qwen"
                else cls._build_kimi_slash_executor_invocation
            )
            if llm == "qwen" and cls._starts_with_invocation(
                head, cls._QWEN_SLASH_EXECUTOR_INVOCATION
            ):
                return RenderedInsertion(text=text, listener_channel=listener_channel)
            if head.startswith("/skill:"):
                if llm == "qwen" and cls._starts_with_invocation(
                    text.lstrip(), cls._kimi_executor_prefix()
                ):
                    return RenderedInsertion(
                        text=build_executor(text),
                        listener_channel=listener_channel,
                    )
                # Kimi (e wrappers Qwen /skill:<slug>) entendem /skill: nativamente.
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
                    text=build_executor(text),
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
                text=build_executor(
                    text,
                    recovery_mode=(
                        cls._normalized_slash_slug(text) == cls._RECOVERY_SLUG
                    ),
                ),
                listener_channel=listener_channel,
            )

        if llm == "grok":
            build_executor = cls._build_grok_slash_executor_invocation
            if cls._starts_with_invocation(
                head, cls._GROK_SLASH_EXECUTOR_INVOCATION
            ):
                return RenderedInsertion(
                    text=text, listener_channel=listener_channel
                )
            if head.startswith("/skill:"):
                rewritten = build_executor(text)
                if rewritten.lstrip().startswith("/skill:"):
                    return RenderedInsertion(
                        text=None,
                        abort_reason=(
                            "/skill: nao e dialeto do TUI Grok — "
                            "reescreva como /slash-executor"
                        ),
                    )
                return RenderedInsertion(
                    text=rewritten, listener_channel=listener_channel
                )
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
                    text=build_executor(text),
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
            return RenderedInsertion(
                text=build_executor(
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

    # ──────────────────── Publicacao instrumentada no terminal ───────── #
    # Ponto unico por onde a fila publica texto em um PTY. Antes do incidente
    # 2026-08-24 cada dispatcher chamava `signal_bus.run_command_in_*.emit`
    # direto; como `Signal(str)` nao devolve valor, `_dispatch_green_arrow`
    # retornava True (e `_mark_as_sent()` rodava) sem que NENHUMA camada
    # soubesse se os bytes chegaram ao terminal. Duas vezes a fila afirmou ter
    # despachado um comando que nunca executou, e o log do app nao tinha uma
    # linha sequer sobre o envio.
    #
    # O funil nao muda o roteamento: quem decide canal, formato e ordem
    # continua sendo cada dispatcher. O que ele acrescenta e o registro do
    # `emit` — rota, canal, canal-alvo, tamanho, posicao na fila e se o
    # dispatch anterior no mesmo canal foi um `/clear`. O `output_panel`
    # completa o par com os bytes efetivamente escritos no PTY e com o eco do
    # lado do terminal (ver `workflow_app.dispatch_telemetry`).

    _CHANNEL_SIGNALS = {
        "interactive": "run_command_in_terminal",
        "workspace": "run_command_in_workspace_terminal",
        "workspace_xterm": "run_command_in_workspace_xterm",
    }
    # Main Kimi (`queue-div-main-llm`): o `/clear` da fila so e colado no
    # T1 depois deste hold. O listener fica amarelo na hora (`listener_hold`)
    # para o autocast nao pular o item; o verde volta a ser o auto-idle
    # vigente, disparado so quando o paste acontece. Claude/Codex/Qwen/Grok
    # e T2/T3 nao esperam.
    _CLEAR_KIMI_MAIN_SEND_DELAY_MS: int = 5_000

    def _persist_lifecycle(self, evento) -> None:
        """Anexa `evento` ao sidecar de lifecycle. Nunca levanta.

        Ate a Task 24 os quatro emissores abaixo montavam envelopes validos e
        os deixavam em `self._last_*_event`, que NENHUM ponto de `src/` lia:
        cada evento sobrescrevia o anterior e morria com o processo. Guardar o
        ultimo evento continua util para teste e diagnostico, mas so o sidecar
        transforma eventos soltos em corpus — e sem corpus `classify_loop_state`
        nao consegue separar loop `paused` de `canceled` de `stale`.

        `None` entra e sai em silencio: comando fora de loop nao gera evento, e
        isso e o caminho normal.
        """
        try:
            from workflow_app.telemetry import lifecycle_sink

            lifecycle_sink.record_event(evento)
        except Exception:  # noqa: BLE001 - telemetria nunca derruba a fila
            logger.debug("[loop] persistencia de lifecycle falhou", exc_info=True)

    def _record_loop_resume(
        self,
        loop_id: str,
        preview,
        result: str,
        *,
        specs: "list[CommandSpec] | None" = None,
    ) -> None:
        """Registra `resume_attempted` e o desfecho da materializacao (Task 16).

        Registra a TENTATIVA mesmo quando ela falha — e sobretudo quando falha.
        Um funil que so conta retomada bem-sucedida esconde exatamente o que
        precisa ser medido: quantas vezes o operador clicou e nao saiu fila.

        `queue_id` so existe quando houve fila, e vem do `LoopExecutionContext`
        do primeiro spec que o carrega (Task 15) — nunca de um uuid novo, que
        seria uma correlacao que nao correlaciona com nada.
        """
        try:
            queue_id = None
            for spec in specs or []:
                ctx = getattr(spec, "loop_context", None)
                if ctx is not None and getattr(ctx, "queue_id", ""):
                    queue_id = ctx.queue_id
                    break

            registro: dict = {
                "resume_attempted": True,
                "loop_id": loop_id,
                "queue_id": queue_id,
                "result": result,
                "spec_count": len(specs) if specs is not None else 0,
            }
            registro.update(
                preview.to_dict()
                if preview is not None
                else {"preview_available": False}
            )
            self._last_resume_record = registro
            logger.info("[loop] resume_attempted %s -> %s", loop_id, result)

            if queue_id is None:
                # Sem fila nao ha `queue_id`, e `build_lifecycle_event` recusa o
                # evento sem ele. Recusa correta: o registro acima ja preserva a
                # tentativa; inventar um id so para satisfazer o schema criaria
                # um run fantasma no corpus.
                self._last_resume_event = None
                return

            from workflow_app.telemetry.loop_lifecycle_event import (
                build_lifecycle_event,
            )

            self._last_resume_event = build_lifecycle_event(
                event_type="queue_resumed",
                loop_id=loop_id,
                queue_id=queue_id,
                result="started",
            )
            self._persist_lifecycle(self._last_resume_event)
        except Exception:  # pragma: no cover - telemetria nunca derruba a fila
            self._last_resume_event = None

    def _record_loop_dispatch(self, spec, provider) -> None:
        """Fecha a travessia do `LoopExecutionContext` no dispatcher (Task 15).

        Aqui — e so aqui — os valores EFETIVOS existem: o provider saiu do
        router, o model e o effort sao os do spec que esta indo para o terminal.
        Antes do despacho ha intencao; depois dele ha fato.

        Guarda o ultimo contexto e o ultimo evento montado E anexa o evento ao
        sidecar de lifecycle via `_persist_lifecycle`. O guard de teste
        (`WF_BLOCK_REAL_LIFECYCLE_TELEMETRY`, armado no conftest) impede que a
        suite despeje dispatch sintetico no corpus real. O `item_id` vem SEMPRE
        do contexto — nunca do texto de `spec.name`.

        Aqui tambem nasce `queue_started`: nao existe um handler unico de
        "comecou a fila" (ha tres caminhos de entrada e o `PipelineManager.start`
        nao tem chamador ligado), entao o primeiro despacho de cada `queue_id` E
        o inicio observavel da fila. A trava e por `queue_id` para o rearme do
        auto-loop nao contar uma segunda largada da mesma fila.
        """
        try:
            from workflow_app.telemetry.loop_lifecycle_event import (
                build_lifecycle_event,
            )

            ctx = getattr(spec, "loop_context", None)
            self._last_loop_context = ctx
            if ctx is None or not ctx.is_item_scoped():
                # Comando fora de loop (ou diretiva `/clear`, `/model`,
                # `/effort`): nao ha item para correlacionar. Zerar o evento
                # evita que um dispatch avulso herde o item anterior.
                self._last_lifecycle_event = None
                return
            self._record_queue_started(ctx)
            nome_provider = getattr(provider, "value", None) or str(provider)
            # Task 24: o desfecho (`item_completed`/`item_failed`) precisa do
            # MESMO provider efetivo do despacho e do instante inicial para
            # `duration`. Guardar aqui evita reconstruir o efetivo depois do
            # fato - reconstrucao que erraria em todo override manual.
            self._last_dispatch_provider = nome_provider
            self._last_dispatch_started_at = time.time()
            # Task 24(a): abre o registro que o retorno autoritativo vai fechar.
            # Sobrescrever um pendente anterior e deliberado e nao emite nada:
            # significa que o despacho anterior nunca chegou ao terminal (gate
            # de dispatch abortou depois deste ponto) ou que seu canal nunca
            # ficou verde. Um desfecho que ninguem observou nao vira evento.
            self._pending_item_outcome = {
                "spec": spec,
                "ctx": ctx,
                "provider": nome_provider,
                "started_at": self._last_dispatch_started_at,
                "channel": None,
                "output_buf": [],
            }
            self._last_lifecycle_event = build_lifecycle_event(
                event_type="item_dispatched",
                loop_id=ctx.loop_id,
                queue_id=ctx.queue_id,
                context=ctx,
                provider_effective=nome_provider,
                model_effective=spec.model.value,
                effort_effective=spec.effort.value,
            )
            self._persist_lifecycle(self._last_lifecycle_event)
        except Exception:  # noqa: BLE001 — telemetria nunca derruba dispatch
            self._last_lifecycle_event = None

    def _on_terminal_output_observed(self, channel: str, chunk: str) -> None:
        """Acumula PTY do canal do despacho em voo. Sem canal ainda, ignora."""
        pendente = self._pending_item_outcome
        if pendente is None or not chunk:
            return
        canal = pendente.get("channel")
        if canal is not None and canal != channel:
            return
        buf = pendente.setdefault("output_buf", [])
        buf.append(chunk)

    def _observe_pending_usage(self, pendente: dict):
        """Task 33: so devolve ObservedUsage com numero > 0."""
        try:
            from pathlib import Path

            from workflow_app.telemetry.usage_observer import observe_usage
        except Exception:  # noqa: BLE001
            return None
        texto = "".join(pendente.get("output_buf") or [])
        return observe_usage(
            terminal_text=texto,
            provider=pendente.get("provider"),
            cwd=Path.cwd(),
            since_ts=pendente.get("started_at"),
        )

    def _close_pending_item_outcome(
        self,
        *,
        failed: bool,
        channel: str | None = None,
        cause: str | None = None,
    ) -> bool:
        """Fecha o despacho em voo: emite o desfecho e marca a subfase.

        Este e o produtor runtime que faltava para `item_completed` e
        `item_failed`. Ate 2026-08-24 os dois eventos existiam no schema, no
        envelope e nos alias — e nao tinham gatilho: os handlers ligados a eles
        pendiam de `signal_bus.command_completed`/`command_failed`, sinais sem
        UM `.emit()` em `src/`. O corpus registrava saida (`item_dispatched`) e
        nunca chegada, e a razao "concluiu/abandonou" era estruturalmente
        incalculavel.

        Chamado dos DOIS unicos desfechos autoritativos do app:
        `listener_authoritative_idle` (verde pos-fence do canal) e
        `autocast_abort_requested` (listener declarado failed). Colar texto no
        terminal NAO e desfecho — ver Regra L14.7 de
        `ai-forge/rules/loop-rules.md`: "despachado" e "concluido" sao fatos
        diferentes, e emitir conclusao no `_mark_as_sent` transformaria toda
        falha silenciosa em sucesso registrado.

        `channel=None` significa "sem restricao de canal" (usado pelo caminho
        indexado). Com canal, so fecha o despacho que saiu por ele: o T1 ficar
        verde enquanto um item roda no T3 nao conclui o item do T3.

        Returns:
            True quando havia despacho em voo e ele foi fechado.
        """
        pendente = self._pending_item_outcome
        if pendente is None:
            return False
        canal_despacho = pendente.get("channel")
        if channel is not None and canal_despacho is not None and canal_despacho != channel:
            return False
        # Consumo one-shot: limpar ANTES de emitir garante que uma reentrada
        # (verde duplo, ou abort seguido de verde) nao conte o mesmo item duas
        # vezes, mesmo que a emissao levante.
        self._pending_item_outcome = None

        ctx = pendente.get("ctx")
        spec = pendente.get("spec")

        # Sidecar ANTES da telemetria (R20). Observer de custo e opcional e
        # nao pode impedir o desfecho da subfase.
        self._finish_rocksmash_subphase(ctx, failed=failed, cause=cause)

        usage_tokens = None
        cost = None
        try:
            visto = self._observe_pending_usage(pendente)
            if visto is not None:
                usage_tokens = visto.usage_tokens
                provider = str(pendente.get("provider") or "").lower()
                # Preco Anthropic so vale para Claude. Outro provider: conta
                # tokens e deixa cost nulo (nao observado), nunca tarifa errada.
                if provider == "claude":
                    from workflow_app.core.token_tracker import calculate_cost

                    modelo = getattr(spec, "model", None)
                    modelo_key = getattr(modelo, "value", None) or str(modelo or "sonnet")
                    cost = calculate_cost(visto.tokens_in, visto.tokens_out, modelo_key)
                    self._usage_session_cost += cost
                self._usage_session_in += visto.tokens_in
                self._usage_session_out += visto.tokens_out
                signal_bus.token_update.emit(
                    self._usage_session_in,
                    self._usage_session_out,
                    self._usage_session_cost,
                )
        except Exception:  # noqa: BLE001 - telemetria nunca aborta o sidecar
            logger.exception("[loop] observer de usage falhou apos desfecho")

        try:
            from workflow_app.telemetry.loop_lifecycle_event import (
                build_lifecycle_event,
            )

            if spec is None or ctx is None or not ctx.is_item_scoped():
                self._last_lifecycle_event = None
                return True
            inicio = pendente.get("started_at")
            duracao = (time.time() - inicio) if inicio else None
            provider = pendente.get("provider")
            if provider is None:
                # Sem despacho observado nao ha "efetivo"; o envelope recusaria
                # o evento e a recusa esta certa.
                self._last_lifecycle_event = None
                return True
            self._last_lifecycle_event = build_lifecycle_event(
                event_type="item_failed" if failed else "item_completed",
                loop_id=ctx.loop_id,
                queue_id=ctx.queue_id,
                context=ctx,
                provider_effective=provider,
                model_effective=spec.model.value,
                effort_effective=spec.effort.value,
                duration=duracao,
                usage_tokens=usage_tokens,
                cost=cost,
            )
            self._persist_lifecycle(self._last_lifecycle_event)
        except Exception:  # noqa: BLE001 - telemetria nunca derruba a fila
            self._last_lifecycle_event = None
        return True

    # ───────────────────────────────── cursor de subfase (rocksmash) ── #

    def _begin_rocksmash_subphase(self, spec) -> bool:
        """Marca `in_flight` no sidecar ANTES do dispatch (Tasks 19/20).

        Diferente da telemetria, este gate PODE abortar o dispatch: a recusa de
        `begin_subphase` significa "esta subfase ja esta em voo num processo
        vivo", e despachar por cima e exatamente o efeito duplicado que a
        autoridade de maquina existe para impedir. Chamado ANTES de
        `_record_loop_dispatch` para que uma recusa nao deixe um
        `item_dispatched` de um item que nunca saiu.

        Cursor ausente NAO e sinonimo de "pode despachar". Fila que nao e
        rocksmash nao tem subfase para marcar e passa direto; mas uma spec que
        E subfase rocksmash com cursor desligado (config ilegivel no bind) tem
        que ser RECUSADA. Deixar passar nao produziria sequer um `in_flight`
        orfao para a reabertura converter em `unknown`: a subfase rodaria sem
        registro nenhum e voltaria `pending` na proxima expansao, repetindo o
        efeito. Isso e exatamente o que a autoridade de maquina existe para
        impedir, entao aqui o default e fail-closed.

        Returns:
            True quando pode despachar. False quando a subfase ja esta em voo
            num processo vivo, ou quando o comando e subfase rocksmash e nao ha
            cursor para registrar o checkpoint.
        """
        cursor = self._rocksmash_cursor
        ctx = getattr(spec, "loop_context", None)
        if cursor is None:
            escopo = scoped_subphase(ctx)
            if escopo is None:
                return True
            item_id, subfase = escopo
            signal_bus.toast_requested.emit(
                f"Rocksmash {item_id}/{subfase}: dispatch abortado — sem cursor "
                "de estado para esta fila (config do loop ilegivel no bind). "
                "Reabra a fila com o _LOOP-CONFIG.json legivel; despachar agora "
                "rodaria a subfase sem checkpoint e ela voltaria a fila.",
                "warning",
            )
            return False
        resultado = cursor.begin(ctx)
        if resultado.error:
            signal_bus.toast_requested.emit(
                f"Rocksmash {resultado.item_id}/{resultado.subphase}: "
                f"dispatch abortado — {resultado.error}",
                "warning",
            )
            return False
        return True

    def _finish_rocksmash_subphase(
        self, ctx, *, failed: bool, cause: str | None = None
    ) -> None:
        """Grava o desfecho da subfase apos retorno autoritativo.

        Falha de escrita aqui NAO aborta nada: o efeito ja aconteceu. Vira
        toast porque a subfase fica presa em `in_flight` — e `in_flight` cujo
        processo morreu vira `unknown` na reabertura, que BLOQUEIA a retomada
        automatica do loop inteiro ate reconciliacao. O operador precisa saber
        disso antes de fechar o app, senao descobre na proxima expansao, em
        forma de fila que recusa abrir. Zero Silencio.
        """
        cursor = self._rocksmash_cursor
        if cursor is None:
            return
        resultado = cursor.finish(ctx, failed=failed, note=cause)
        if resultado.error:
            signal_bus.toast_requested.emit(
                f"Rocksmash {resultado.item_id}/{resultado.subphase}: desfecho NAO "
                f"gravado em _ROCKSMASH-STATE.json — {resultado.error}. "
                "A subfase segue `in_flight` e virara `unknown` na reabertura, "
                "que bloqueia a retomada automatica ate reconciliacao manual.",
                "warning",
            )

    def _record_loop_item_outcome(self, index: int, *, failed: bool) -> None:
        """Desfecho pelo caminho INDEXADO (`command_completed`/`command_failed`).

        Delega ao mesmo fechador do caminho autoritativo, de proposito. Ate
        2026-08-24 este era o unico produtor de `item_completed`/`item_failed`
        — e um produtor morto: os dois sinais que o alimentam nao tem UM
        `.emit()` em `src/` (os sinais homonimos dos runners sao outros, e so
        chegam ao `PipelineManager`, cujo `start()` nao tem chamador ligado).
        Manter a funcao com corpo proprio criaria dois produtores do MESMO
        evento; delegar deixa o registro one-shot: quem fechar primeiro
        consome o pendente, e o segundo vira no-op em vez de contar o item
        duas vezes.

        `index` sobrevive na assinatura porque os dois slots o passam; o
        desfecho, porem, sai do registro do despacho, nao da posicao na lista.
        Sem despacho observado nesta sessao nao ha evento: atribuir custo a um
        tier adivinhado e pior que nao atribuir.
        """
        self._close_pending_item_outcome(failed=failed)

    def _record_queue_lifecycle(self, event_type: str, ctx: object = None) -> None:
        """Emite um evento puramente de fila (`queue_canceled`, `app_closed`).

        `item_id` e `phase` ficam nulos por contrato: a fila nao esta "num
        item" quando e cancelada. O `queue_id`/`loop_id` saem de `ctx` quando o
        chamador tem um contexto mais fresco na mao, e do ultimo contexto de
        loop visto quando nao tem; sem nenhum dos dois nao ha evento, porque um
        evento de fila sem fila nao correlaciona com nada.
        """
        try:
            from workflow_app.telemetry.loop_lifecycle_event import (
                build_lifecycle_event,
            )

            if ctx is None:
                ctx = getattr(self, "_last_loop_context", None)
            if ctx is None or not getattr(ctx, "queue_id", ""):
                self._last_queue_lifecycle_event = None
                return
            self._last_queue_lifecycle_event = build_lifecycle_event(
                event_type=event_type,
                loop_id=ctx.loop_id,
                queue_id=ctx.queue_id,
            )
            self._persist_lifecycle(self._last_queue_lifecycle_event)
        except Exception:  # noqa: BLE001 - telemetria nunca derruba a fila
            self._last_queue_lifecycle_event = None

    def _record_queue_started(self, ctx: object) -> None:
        """Emite `queue_started` uma unica vez por `queue_id`.

        Nao ha, no app, um ponto unico onde "a fila comecou": ha tres caminhos
        de entrada (play, step manual e autocast) e o `PipelineManager.start()`
        — que seria o candidato natural — tem seu unico chamador desconectado.
        Inventar um handler novo so para a telemetria criaria um segundo lugar
        onde a fila comeca, e os dois divergiriam na primeira mudanca de UI.
        O primeiro despacho de um `queue_id` E o inicio observavel da fila.

        A trava e por `queue_id`, nao por sessao nem por carregamento: o rearme
        do auto-loop e o restore de snapshot seguem despachando itens da MESMA
        fila e nenhum dos dois pode contar uma segunda largada. Fila nova traz
        `queue_id` novo e larga sozinha.
        """
        try:
            queue_id = getattr(ctx, "queue_id", "") or ""
            if not queue_id or queue_id in self._queue_started_emitted:
                return
            self._queue_started_emitted.add(queue_id)
            self._record_queue_lifecycle("queue_started", ctx)
        except Exception:  # noqa: BLE001 - telemetria nunca derruba dispatch
            logger.debug("[loop] queue_started falhou", exc_info=True)

    def _registrar_transicao_de_fila(self, event_type: str) -> None:
        """Emite pausa/retomada apenas quando o estado da fila MUDA.

        Duas armadilhas moram aqui e elas puxam para lados opostos.

        A primeira: `pipeline_paused` chega em duplicata pelo desenho atual
        (module_detail emite o sinal e `PipelineManager.pause()` reemite). Sem
        desduplicacao um clique viraria duas pausas e a razao pausa/retomada —
        que e justamente o que `classify_loop_state` le — sairia errada.

        A segunda: a pausa pode ter sido gravada por OUTRA sessao do app. Uma
        trava booleana por sessao suprimiria a retomada correspondente e
        deixaria o loop `paused` para sempre no corpus. Isso e pior que uma
        retomada sobrando: `classify_loop_state` procura pausa SEM retomada
        posterior, entao retomada sem pausa nao apaga nada, enquanto pausa sem
        retomada mente sobre o estado final.

        A trava, portanto, e uma maquina de estado por `queue_id` que comeca
        indefinida: a primeira transicao observada sempre passa, e so a
        repeticao do MESMO estado e engolida.
        """
        try:
            ctx = getattr(self, "_last_loop_context", None)
            queue_id = getattr(ctx, "queue_id", "") or ""
            if not queue_id:
                # Fora de loop nao ha fila a que correlacionar; o envelope
                # recusaria o evento e a recusa esta certa.
                return
            estado = "paused" if event_type == "queue_paused" else "resumed"
            if self._queue_pause_state.get(queue_id) == estado:
                return
            self._queue_pause_state[queue_id] = estado
            self._record_queue_lifecycle(event_type, ctx)
        except Exception:  # noqa: BLE001 - telemetria nunca derruba a fila
            logger.debug("[loop] %s falhou", event_type, exc_info=True)

    def _on_queue_paused_observed(self) -> None:
        """Slot de `pipeline_paused`. Ver `_registrar_transicao_de_fila`."""
        self._registrar_transicao_de_fila("queue_paused")

    def _on_queue_resumed_observed(self) -> None:
        """Slot de `pipeline_resumed`. Ver `_registrar_transicao_de_fila`."""
        self._registrar_transicao_de_fila("queue_resumed")

    def note_app_closing(self) -> None:
        """Emite `app_closed` uma vez por processo. Chamado pela MainWindow.

        Publico de proposito: os dois ancoradouros vivem em `main_window.py`
        (`closeEvent` e o `aboutToQuit`), porque o proprio repositorio ja
        registra que "widgets-filho nao recebem closeEvent confiavelmente". Com
        dois ancoradouros a trava e obrigatoria, senao o fechamento normal
        gravaria dois `app_closed` e a contagem de sessoes encerradas dobraria.

        Sem `app_closed` o fechamento e indistinguivel de abandono: os dois
        deixam a fila com pendentes e nenhuma marca. Essa e a confusao que o
        criterio 12.2.18 proibe publicar como metrica.
        """
        try:
            if self._app_closed_emitted:
                return
            self._app_closed_emitted = True
            self._record_queue_lifecycle("app_closed")
        except Exception:  # noqa: BLE001 - telemetria nunca derruba o shutdown
            logger.debug("[loop] app_closed falhou", exc_info=True)

    def _record_provider_blocked(
        self, item: object, *, provider: object = None
    ) -> None:
        """Emite `provider_blocked` quando uma barreira recusa o despacho.

        Contextual por contrato: o bloqueio pode pegar a fila parada (credencial
        ORCH ausente, antes de qualquer item sair) ou um item em voo (capacidade
        exclusiva de imagem). Por isso `item_id`/`phase` sao opcionais aqui e o
        contexto vem do PROPRIO item barrado — nunca de `self._last_loop_context`,
        que guarda o ultimo item DESPACHADO e apontaria para o item anterior.

        `provider_effective` e o provider que seria usado (Main vivo ou o
        classificado pelo router). Nao ha promocao a "efetivo" de verdade porque
        nada executou; o campo diz contra qual tier o bloqueio aconteceu, que e
        a pergunta que o corpus precisa responder.
        """
        try:
            from workflow_app.telemetry.loop_lifecycle_event import (
                build_lifecycle_event,
            )

            spec = item.get_spec() if item is not None else None
            ctx = getattr(spec, "loop_context", None)
            if ctx is None or not getattr(ctx, "queue_id", ""):
                # Comando fora de loop: bloqueio real, mas sem fila a que
                # correlacionar. O envelope recusaria, e a recusa esta certa.
                return
            nome_provider = getattr(provider, "value", None)
            if nome_provider is None and provider is not None:
                nome_provider = str(provider)
            self._last_lifecycle_event = build_lifecycle_event(
                event_type="provider_blocked",
                loop_id=ctx.loop_id,
                queue_id=ctx.queue_id,
                context=ctx,
                provider_effective=nome_provider,
                model_effective=getattr(getattr(spec, "model", None), "value", None),
                effort_effective=getattr(getattr(spec, "effort", None), "value", None),
            )
            self._persist_lifecycle(self._last_lifecycle_event)
        except Exception:  # noqa: BLE001 - telemetria nunca derruba a fila
            logger.debug("[loop] provider_blocked falhou", exc_info=True)

    def _dispatch_position(self) -> int | None:
        """Indice do item que esta sendo despachado (itens ja enviados).

        Barato e suficiente para alinhar uma linha de telemetria com a
        `_QUEUE-STATE.json` depois do fato — foi exatamente o cruzamento que
        faltou para posicionar as duas ocorrencias do incidente.
        """
        try:
            return sum(1 for item in self._items if not item.is_pending_run())
        except Exception:  # noqa: BLE001 — telemetria nunca derruba dispatch
            return None

    def _publish_to_terminal(self, channel: str, *, route: str, text: str) -> None:
        """Registra e publica `text` no canal indicado."""
        if channel == "interactive":
            self._pending_kimi_clear_seq += 1
        if self._should_delay_kimi_main_clear(channel, text):
            seq = self._pending_kimi_clear_seq
            self._bind_pending_item_channel(channel)
            signal_bus.listener_hold.emit(channel)
            QTimer.singleShot(
                self._CLEAR_KIMI_MAIN_SEND_DELAY_MS,
                self,
                lambda ch=channel, rt=route, tx=text, token=seq: (
                    self._flush_delayed_kimi_clear(ch, rt, tx, token)
                ),
            )
            return
        self._emit_to_terminal(channel, route=route, text=text)

    def _should_delay_kimi_main_clear(self, channel: str, text: str) -> bool:
        return (
            channel == "interactive"
            and self._command_head(text) == "/clear"
            and self.current_main_llm() == "kimi"
        )

    def _flush_delayed_kimi_clear(
        self, channel: str, route: str, text: str, seq: int
    ) -> None:
        if seq != self._pending_kimi_clear_seq:
            return
        self._emit_to_terminal(channel, route=route, text=text)

    def _bind_pending_item_channel(self, channel: str) -> None:
        # Task 24(a): o canal so e conhecido AQUI. `_record_loop_dispatch` roda
        # antes das ramificacoes de worker e nao sabe se o item vai para T1, T2
        # ou T3. Sem amarrar, o verde autoritativo do T1 fecharia um item que
        # esta rodando no T3 — desfecho atribuido ao terminal errado. So a
        # PRIMEIRA publicacao amarra: um dispatch Codex publica preambulo alem
        # do comando, e todos vao para o mesmo canal.
        pendente = self._pending_item_outcome
        if pendente is not None and pendente.get("channel") is None:
            pendente["channel"] = channel

    def _emit_to_terminal(self, channel: str, *, route: str, text: str) -> None:
        dispatch_telemetry.open_dispatch(
            route=route,
            channel=channel,
            command=text,
            position=self._dispatch_position(),
            after_clear=self._last_dispatch_head.get(channel) == "/clear",
        )
        self._last_dispatch_head[channel] = self._command_head(text)
        self._bind_pending_item_channel(channel)
        getattr(signal_bus, self._CHANNEL_SIGNALS[channel]).emit(text)

    def _terminal_emitter(self, channel: str, *, route: str):
        """Callable de 1 argumento equivalente a `signal_bus.<sinal>.emit`.

        Os dispatchers Codex e Grok escolhem o sinal uma vez e o chamam de
        varios ramos; devolver um emissor preserva esse desenho em vez de
        espalhar `if to_t1` por cada ramo.
        """
        def _emit(text: str) -> None:
            self._publish_to_terminal(channel, route=route, text=text)

        return _emit

    def _dispatch_codex_command(self, cmd_text: str, *, to_t1: bool = False, is_prompt: bool = False) -> bool:
        """Dispatch a command to Codex. Returns False when validation aborts."""
        # Prompt simples: envia texto raw sem transformacoes
        if is_prompt:
            channel = "interactive" if to_t1 else "workspace_xterm"
            emit = self._terminal_emitter(channel, route="codex-main-prompt")
            emit(cmd_text)
            self._on_run_command(cmd_text)
            return True

        channel = "interactive" if to_t1 else "workspace_xterm"
        emit = self._terminal_emitter(channel, route="codex-main")
        head = self._command_head(cmd_text)
        if is_directive_line(cmd_text):
            # O Codex CLI nao tem diretiva TEXTUAL de modelo/effort: `/model` e
            # picker de duas etapas que ignora argumento, e `/effort` nao
            # existe (C27, evidencia em `model_effort_equivalence`). Qualquer
            # diretiva que chegue aqui e residuo — fila enfileirada sob Claude
            # com o Main trocado depois, ou snapshot antigo. Suprime e pulsa o
            # listener yellow→green para o autocast avancar como avanca sob
            # Claude. Canal = terminal onde o Codex roda de fato (T1 quando
            # to_t1, senao T3 xterm).
            signal_bus.listener_helper_pulse.emit(
                "interactive" if to_t1 else "workspace_xterm"
            )
            return True
        # task 006 — condicao de falha 4 (terminal alvo nao pronto -> abortar
        # com feedback visivel). Vale apenas para o destino Worker Codex (T3,
        # to_t1=False); o caminho Main Codex (to_t1=True) publica no T1
        # interactive, que existe sempre. Fica DEPOIS do branch de diretiva de
        # proposito: diretiva nunca publica no PTY (so pulsa), entao nao precisa
        # de T3 pronto.
        if not to_t1 and not self._codex_t3_available:
            signal_bus.toast_requested.emit(
                "Worker Codex (T3): terminal-codex-output nao esta pronto — "
                "dispatch abortado.",
                "warning",
            )
            return False
        if head == "/clear":
            # Raw, sem wrapper de slash-executor: `/clear` e comando do proprio
            # CLI Codex.
            emit(cmd_text)
            self._on_run_command(cmd_text)
            return True
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

    def _dispatch_kimi_main_command(
        self, cmd_text: str, *, llm_label: str = "Kimi", dialect: str = "kimi", is_prompt: bool = False
    ) -> bool:
        """Dispatch through the skill-runtime Main LLM path (Kimi / Qwen).

        Kimi publishes `/skill:slash-executor /<claude-command>` (or
        `/skill:<slug>` for skill-only / wrapper-specific cases). Qwen
        (`dialect="qwen"`) publishes native `/slash-executor /<claude-command>`.
        `llm_label` appears only in abort toasts. Returns False on abort.
        """
        # Prompt simples: envia texto raw sem transformacoes
        if is_prompt:
            self._publish_to_terminal("interactive", route="kimi-main-prompt", text=cmd_text)
            self._on_run_command(cmd_text)
            return True

        build_executor = (
            self._build_qwen_slash_executor_invocation
            if dialect == "qwen"
            else self._build_kimi_slash_executor_invocation
        )
        head = self._command_head(cmd_text)
        if is_directive_line(cmd_text):
            # O Kimi CLI nao tem diretiva TEXTUAL de modelo/reasoning: o
            # `/model` descarta o argumento e abre picker bloqueante (que ainda
            # engoliria a proxima linha colada, corrompendo a fila) e
            # `/reasoning` nao existe (C27, evidencia em
            # `model_effort_equivalence`). Suprime e pulsa (ver Codex acima).
            # Precisa vir ANTES do branch generico de slash — la `/reasoning`
            # resolveria slug inexistente e abortaria com toast.
            signal_bus.listener_helper_pulse.emit("interactive")
            return True
        if head == "/clear":
            self._publish_to_terminal("interactive", route="kimi-main/clear", text=cmd_text)
            self._on_run_command(cmd_text)
            return True
        if dialect == "qwen" and self._starts_with_invocation(
            head, self._QWEN_SLASH_EXECUTOR_INVOCATION
        ):
            self._publish_to_terminal("interactive", route="kimi-main/passthrough", text=cmd_text)
            self._on_run_command(cmd_text)
            return True
        if head.startswith("/skill:"):
            if dialect == "qwen" and self._starts_with_invocation(
                cmd_text.lstrip(), self._kimi_executor_prefix()
            ):
                transformed = build_executor(cmd_text)
                self._publish_to_terminal("interactive", route="kimi-main/skill-executor", text=transformed)
                self._on_run_command(cmd_text)
                return True
            self._publish_to_terminal("interactive", route="kimi-main/skill", text=cmd_text)
            self._on_run_command(cmd_text)
            return True
        if head.startswith("/"):
            slug = head[1:].split()[0] if head else ""
            if slug in self._CUSTOM_PROMPT_DIRECTIVES:
                # Custom-prompt directive (ex.: /goal): nao existe em
                # .claude/commands/ nem como skill. Roteia pelo executor
                # universal, que resolve o arquivo em ai-forge/custom-prompts/
                # e preserva o contrato de listener. Nunca abortar como
                # comando desconhecido.
                if self._resolve_custom_prompt_file(slug) is None:
                    signal_bus.toast_requested.emit(
                        f"Main LLM {llm_label}: custom-prompt '{slug}' nao encontrado "
                        "em ai-forge/custom-prompts/ — dispatch abortado.",
                        "warning",
                    )
                    return False
                transformed = build_executor(cmd_text)
            else:
                has_command = self._resolve_claude_command_file(slug) is not None
                has_skill = self._resolve_skill_target(slug)
                if slug and not has_command and not has_skill:
                    signal_bus.toast_requested.emit(
                        f"Main LLM {llm_label}: comando/skill '{slug}' nao encontrado em "
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
                    transformed = build_executor(
                        cmd_text,
                        recovery_mode=(
                            self._normalized_slash_slug(cmd_text)
                            == self._RECOVERY_SLUG
                        ),
                    )
        else:
            transformed = cmd_text
        self._publish_to_terminal("interactive", route="qwen-main", text=transformed)
        self._on_run_command(cmd_text)
        return True

    def _dispatch_qwen_main_command(self, cmd_text: str, *, is_prompt: bool = False) -> bool:
        """Dispatch through the Main LLM Qwen path.

        Qwen TUI resolves `/slash-executor` natively (no `/skill:` prefix).
        The compiled PromptCompiler envelope is not used here.
        Returns False on abort (runtime unavailable or unknown slash).
        """
        # Prompt simples: envia texto raw sem transformacoes
        if is_prompt:
            self._publish_to_terminal("interactive", route="qwen-main-prompt", text=cmd_text)
            self._on_run_command(cmd_text)
            return True

        head = self._command_head(cmd_text)
        # Diretivas e /clear nao dependem do daemon: pulsam / vao raw como Kimi.
        if not is_directive_line(cmd_text) and head != "/clear":
            # ST005: dynamic unavailability check — if Qwen runtime is unhealthy,
            # block dispatch with actionable reason.
            if not self._qwen_runtime_available():
                signal_bus.toast_requested.emit(
                    "Main LLM Qwen: processo Qwen indisponivel no momento. "
                    "Verifique se o daemon Qwen esta rodando e a porta esta escutando.",
                    "warning",
                )
                return False
        return self._dispatch_kimi_main_command(
            cmd_text, llm_label="Qwen", dialect="qwen"
        )

    def _qwen_runtime_available(self) -> bool:
        """ST005: placeholder de health check do runtime Qwen no dispatch.

        Item 011: a docstring anterior afirmava consumir `ProviderCapabilityLoader`
        para um check estatico. O corpo sempre foi `return True` e o loader nunca
        foi importado aqui — a afirmacao era falsa. Isto e, hoje, um placeholder
        que sempre autoriza: nao ha check estatico nem probe de daemon. Mudar o
        corpo altera comportamento de dispatch Qwen e esta fora do escopo do item
        011 (que so avisa); quem consome capability e o preflight informativo de
        `load_pipeline`.
        """
        return True

    def _dispatch_mimo_main_command(self, cmd_text: str, *, is_prompt: bool = False) -> bool:
        """Dispatch through the Main LLM MiMo path (CLI mimocode no T1).

        Payload: `/slash-executor --delegation-runtime=mimo /<comando> <args> `
        (um espaco no fim, Enter em write separado). `/clear` vai cru e sem
        espaco (com espaco o TUI nao limpa). Diretivas `/model`/`/effort` nao
        existem no TUI da MiMo: pulsam o listener, como no Grok. Retorna False
        no abort (comando/skill inexistente ou payload com "!`" recusado pelo
        builder), mantendo o item pendente.
        """
        channel = "interactive"
        if is_prompt:
            self._publish_to_terminal(channel, route="mimo-main-prompt", text=cmd_text)
            self._on_run_command(cmd_text)
            return True

        head = self._command_head(cmd_text)
        if is_directive_line(cmd_text):
            signal_bus.listener_helper_pulse.emit(channel)
            return True
        if head == "/clear":
            self._publish_to_terminal(channel, route="mimo-main", text=cmd_text.strip())
            self._on_run_command(cmd_text)
            return True

        stripped = cmd_text.lstrip()
        if stripped.startswith("/") and not self._starts_with_invocation(
            head, self._GROK_SLASH_EXECUTOR_INVOCATION
        ) and not self._starts_with_invocation(head, self._kimi_executor_prefix()):
            slug = head[1:]
            if slug.startswith("skill:"):
                slug = slug[len("skill:"):]
            if slug in self._CUSTOM_PROMPT_DIRECTIVES:
                if self._resolve_custom_prompt_file(slug) is None:
                    signal_bus.toast_requested.emit(
                        f"Main LLM MiMo: custom-prompt '{slug}' nao encontrado "
                        "em ai-forge/custom-prompts/ — dispatch abortado.",
                        "warning",
                    )
                    return False
            elif slug and (
                self._resolve_claude_command_file(slug) is None
                and not self._resolve_skill_target(slug)
            ):
                signal_bus.toast_requested.emit(
                    f"Main LLM MiMo: comando/skill '{slug}' nao encontrado em "
                    ".claude/commands/ ou .agents/skills/ — dispatch abortado.",
                    "warning",
                )
                return False

        try:
            transformed = self._build_mimo_slash_executor_invocation(
                cmd_text,
                recovery_mode=(
                    self._normalized_slash_slug(cmd_text) == self._RECOVERY_SLUG
                ),
            )
        except ValueError as exc:
            signal_bus.toast_requested.emit(
                f"Main LLM MiMo: {exc} - dispatch abortado.", "warning"
            )
            return False
        if not transformed or not transformed.strip():
            signal_bus.toast_requested.emit(
                "Main LLM MiMo: adaptacao retornou texto vazio — dispatch abortado.",
                "warning",
            )
            return False
        self._publish_to_terminal(channel, route="mimo-main", text=transformed)
        self._on_run_command(cmd_text)
        return True

    def _dispatch_grok_main_command(self, cmd_text: str, *, to_t1: bool = True, is_prompt: bool = False) -> bool:
        """Dispatch through the Grok native `/slash-executor` (Main T1 or Worker T3).

        Payload: `/slash-executor --delegation-runtime=grok /<comando> <args>`.
        Never `/skill:slash-executor`. PromptCompiler and Codex envelope stay
        out. C19 / grok_spike / provider bridge kernel stay out: this method
        only changes the TEXT pasted into the already-open PTY.

        `to_t1=True` -> T1 interactive (Main Grok). `to_t1=False` -> T3
        workspace_xterm (worker Grok). Returns False on abort.
        """
        # Prompt simples: envia texto raw sem transformacoes
        if is_prompt:
            channel = "interactive" if to_t1 else "workspace_xterm"
            emit = self._terminal_emitter(channel, route="grok-main-prompt")
            emit(cmd_text)
            self._on_run_command(cmd_text)
            return True

        channel = "interactive" if to_t1 else "workspace_xterm"
        emit = self._terminal_emitter(channel, route="grok-main")
        llm_label = "Grok" if to_t1 else "Worker Grok (T3)"
        head = self._command_head(cmd_text)
        if is_directive_line(cmd_text):
            signal_bus.listener_helper_pulse.emit(channel)
            return True
        if head == "/clear":
            emit(cmd_text)
            self._on_run_command(cmd_text)
            return True
        if not to_t1:
            if not self._ensure_t3_grok_host():
                return False
        if self._starts_with_invocation(
            head, self._GROK_SLASH_EXECUTOR_INVOCATION
        ):
            emit(cmd_text)
            self._on_run_command(cmd_text)
            return True
        if head.startswith("/skill:"):
            transformed = self._build_grok_slash_executor_invocation(cmd_text)
            if transformed.lstrip().startswith("/skill:"):
                signal_bus.toast_requested.emit(
                    f"Main LLM {llm_label}: dialeto /skill: nao e valido no "
                    "TUI Grok — dispatch abortado.",
                    "warning",
                )
                return False
            emit(transformed)
            self._on_run_command(cmd_text)
            return True
        if head.startswith("/"):
            slug = head[1:].split()[0] if head else ""
            if slug in self._CUSTOM_PROMPT_DIRECTIVES:
                if self._resolve_custom_prompt_file(slug) is None:
                    signal_bus.toast_requested.emit(
                        f"Main LLM {llm_label}: custom-prompt '{slug}' nao "
                        "encontrado em ai-forge/custom-prompts/ — dispatch "
                        "abortado.",
                        "warning",
                    )
                    return False
                transformed = self._build_grok_slash_executor_invocation(
                    cmd_text
                )
            else:
                has_command = self._resolve_claude_command_file(slug) is not None
                has_skill = self._resolve_skill_target(slug)
                if slug and not has_command and not has_skill:
                    signal_bus.toast_requested.emit(
                        f"Main LLM {llm_label}: comando/skill '{slug}' nao "
                        "encontrado em .claude/commands/ ou .agents/skills/ "
                        "— dispatch abortado.",
                        "warning",
                    )
                    return False
                transformed = self._build_grok_slash_executor_invocation(
                    cmd_text,
                    recovery_mode=(
                        self._normalized_slash_slug(cmd_text)
                        == self._RECOVERY_SLUG
                    ),
                )
        else:
            transformed = cmd_text
        if not transformed or not transformed.strip():
            signal_bus.toast_requested.emit(
                f"Main LLM {llm_label}: adaptacao retornou texto vazio — "
                "dispatch abortado.",
                "warning",
            )
            return False
        emit(transformed)
        self._on_run_command(cmd_text)
        return True

    def _dispatch_green_arrow(self, cmd_text: str, *, is_prompt: bool = False) -> bool:
        """Handler unico para `item.run_in_terminal_requested` (provider efetivo
        Claude/T1). Retorna True quando publicou de fato (fix D-1: o slot
        `_on_single_button_green_dispatch` so marca enviado em True).

        `is_prompt` (D-8): repassado aos dispatchers de Main exatamente como o
        step repassa `spec.is_prompt`. Item de pipeline chega com False (default
        de `CommandSpec`) e recebe a adaptacao do Main; so o item marcado como
        prompt no dialogo "Adicionar comando" vai raw — nos tres caminhos.

        Item 012 (D5): este caminho DEIXOU DE SER o unico caminho vivo. Ele
        sempre leu `_main_*_radio.isChecked()` no momento do dispatch; desde o
        item 012 o botao de step (`_on_step_btn_clicked`) faz o mesmo, e o
        contrato congelado do item 019 foi removido. A paridade entre os tres
        caminhos (clique per-item, step, seta verde) passou a ser por
        construcao, nao por coincidencia de implementacao.

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
            self._publish_to_terminal("interactive", route="green-arrow/clear", text=cmd_text)
            self._on_run_command(cmd_text)
            self._mirror_clear_to_workspace_if_kimi_checked(cmd_text)
            return True

        if getattr(self, "_main_codex_radio", None) and self._main_codex_radio.isChecked():
            return self._dispatch_codex_command(cmd_text, to_t1=True, is_prompt=is_prompt)

        if getattr(self, "_main_qwen_radio", None) and self._main_qwen_radio.isChecked():
            return self._dispatch_qwen_main_command(cmd_text, is_prompt=is_prompt)

        if getattr(self, "_main_grok_radio", None) and self._main_grok_radio.isChecked():
            return self._dispatch_grok_main_command(cmd_text, is_prompt=is_prompt)

        if self._resolve_interactive_main_llm() == "mimo":
            return self._dispatch_mimo_main_command(cmd_text, is_prompt=is_prompt)

        if not getattr(self, "_force_kimi_chk", None) or not self._force_kimi_chk.isChecked():
            # Main Claude com diretiva em dialeto estrangeiro (C27): um snapshot
            # salvo antes de 2026-08-17 pode trazer `/model sol high`,
            # `/model k3` ou `/reasoning yes` — residuo da traducao revogada,
            # que o Claude Code tambem nao entende. Suprime e pulsa, simetrico
            # ao que os dispatchers Codex/Kimi/Qwen/Grok ja fazem. Fail-open:
            # `/model haiku` e qualquer diretiva legitima segue raw.
            if is_foreign_directive(cmd_text):
                signal_bus.listener_helper_pulse.emit("interactive")
                return True
            self._publish_to_terminal("interactive", route="green-arrow/claude", text=cmd_text)
            self._on_run_command(cmd_text)
            return True
        return self._dispatch_kimi_main_command(cmd_text, is_prompt=is_prompt)

    def _on_single_button_green_dispatch(
        self, item: CommandItemWidget, cmd_text: str
    ) -> None:
        """Slot do botao unico (verde/Claude-T1). Marca enviado SO quando
        `_dispatch_green_arrow` publica de fato (fix D-1). Espelha
        `_on_single_button_codex_dispatch`: sob Main Codex/Kimi o dispatch pode
        abortar (`.md`/skill ausente) — nesse caso o item fica pendente e o toast
        do dispatcher e o feedback (Zero Silencio).

        D-8: repassa o `is_prompt` do spec, o mesmo valor que o step entrega aos
        dispatchers de Main, para clique e step concordarem."""
        if self._dispatch_green_arrow(cmd_text, is_prompt=item.get_spec().is_prompt):
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
        # Item 020: T2 family = kimi OR qwen; T3 family = codex OR grok.
        _t2_active = (
            self._use_kimi_chk.isChecked()
            or (getattr(self, "_use_qwen_chk", None) is not None
                and self._use_qwen_chk.isChecked())
        )
        _t3_active = (
            (getattr(self, "_use_codex_chk", None) is not None
             and self._use_codex_chk.isChecked())
            or (getattr(self, "_use_grok_chk", None) is not None
                and self._use_grok_chk.isChecked())
        )
        if head == "/clear" and _t2_active:
            self._publish_to_terminal("workspace", route="mirror-clear/t2", text=cmd_text)
            self._last_workspace_dispatch_was_clear = True
        if head == "/clear" and _t3_active:
            # Fix D-7: mesmo gate de prontidao do T3 que o step path
            # (`clear_both`) — sem ele, o /clear ia para um xterm Codex
            # possivelmente inexistente em silencio. T3 indisponivel -> toast.
            if self._codex_t3_available:
                self._publish_to_terminal("workspace_xterm", route="mirror-clear/t3", text=cmd_text)
            else:
                signal_bus.toast_requested.emit(
                    "Worker (T3): terminal-codex-output nao esta pronto"
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
        /effort e demais directivas — reflete exatamente o que esta na tela).

        Item 012: usa command_text_with_flags (produtor unico), que combina
        render_with_mcp_flags (sufixo de flags) + config_path (shell-quoted).
        Paridade byte-a-byte com per-item run/copy e autocast/step. O provider
        efetivo vem de _resolve_item_provider; so T1 Claude recebe sufixo;
        itens roteados a worker sao stripados (I3)."""
        active_flags = self._active_mcp_flags()
        lines: list[str] = []
        for item in self._items:
            spec = item.get_spec()
            provider = self._resolve_item_provider(spec)
            # Item 012: usa command_text_with_flags (produtor unico) em vez
            # de render_with_mcp_flags isolado. Resolve R-28: mass copy agora
            # inclui config_path + flags em paridade com per-item run/copy.
            rendered = command_text_with_flags(
                spec,
                provider=provider,
                active_flags=active_flags,
            )
            name = (rendered or "").strip()
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

    def rendered_specs(self) -> list[CommandSpec]:
        """Specs REALMENTE na fila, pos-traducao C27 e pos-renumeracao 1-based.

        `load_pipeline` recebe a lista em dialeto Claude e a transforma: sob
        Main Codex um par `/model`+`/effort` vira UMA linha, sob Qwen/Grok as
        duas somem. Quem guardar a lista de ENTRADA fica com indices que nao
        batem com a tela — e `PipelineManager.reorder_command` indexa a fila
        dele com a `position` que o item arrastado carrega, que e a da tela.
        Resultado: o operador arrasta uma linha e outra se move.
        """
        return [item.get_spec() for item in self._items]

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
                # C27: sem `effort`, `restore_queue_snapshot` reconstroi o spec
                # com o default do dataclass (`EffortLevel.STANDARD`) — o item
                # volta da fila salva afirmando um effort que nao e o que foi
                # enfileirado. `kimi_eligible` some pelo mesmo caminho e muda
                # roteamento de worker, entao vai junto.
                "effort": spec.effort.value,
                "kimi_eligible": spec.kimi_eligible,
                "status": item._status.value,
                "sent": not item.is_pending_run(),
                # Task 15: a correlacao de loop tem que sobreviver a
                # snapshot/restore. Sem isto, retomar uma fila salva perderia
                # `item_id` e a unica alternativa seria re-inferi-lo do texto do
                # comando — precisamente o que 12.2.5 proibe. Ausente (None) em
                # todo comando fora de loop, e a chave nem e escrita.
                **(
                    {"loop_context": spec.loop_context.to_dict()}
                    if spec.loop_context is not None
                    else {}
                ),
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
        from workflow_app.domain import (
            CommandStatus,
            InteractionType,
            LoopExecutionContext,
            ModelName,
        )

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
            try:
                # Snapshot pre-C27 nao tem a chave: cai no mesmo default do
                # dataclass, que e o comportamento antigo — nao regride.
                effort = EffortLevel(entry.get("effort", EffortLevel.STANDARD.value))
            except ValueError:
                effort = EffortLevel.STANDARD
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
                effort=effort,
                kimi_eligible=bool(entry.get("kimi_eligible", False)),
                # Snapshot antigo nao tem a chave: `from_dict` devolve None e o
                # item volta sem correlacao, como antes — nunca estoura.
                loop_context=LoopExecutionContext.from_dict(
                    entry.get("loop_context")
                ),
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

        # A adequacao C27 REMOVE as linhas de diretiva sob qualquer Main
        # nao-Claude. `zip` posicional aplicaria entao o status da linha N a um
        # item que veio da linha N+k, e truncaria a cauda. Adequa AQUI para
        # realinhar; `load_pipeline` adequa de novo, mas `adapt_specs_to_main`
        # e idempotente, entao vira no-op.
        survivors = adapt_specs_to_main(specs, self._resolve_interactive_main_llm())
        if len(survivors) != len(specs):
            statuses, sent_flags = _realign_after_translation(
                specs, survivors, statuses, sent_flags
            )
            specs = survivors

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
        # Teto por sub-aba ativa de `queue-subtabs-insertions`: Resize cobre o
        # resize da janela (muda quantas linhas o flow usa) e LayoutRequest
        # cobre populate_*_subtab e a troca de filtro (PROMPTS/AGENTES).
        # getattr: o filtro e instalado durante `_setup_ui`, antes de varios
        # atributos existirem (inclusive `_items_container`, logo abaixo).
        if obj is getattr(self, "_insertions_subtabs", None) and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.LayoutRequest,
        ):
            self._sync_insertions_subtabs_height()

        if obj is getattr(self, "_items_container", None):
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
            self._record_loop_item_outcome(index, failed=not success)
            self._emit_progress_metrics()

    def _on_command_failed(self, index: int, _msg: str) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.ERRO)
            self._record_loop_item_outcome(index, failed=True)
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
            # Task 24: `canceled` exige evento explicito. Sem esta linha o
            # cancelamento seria indistinguivel de abandono na classificacao
            # historica - o loop ficaria com pendentes e nenhuma marca.
            self._record_queue_lifecycle("queue_canceled")
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

        ESTADO VIVO, REGIME UNICO (item 012 / D5). Este caminho le a UI no
        momento do clique, identico ao clique per-item
        (`CommandItemWidget._on_exec_clicked`, criterio de rejeicao 8 de
        `single-arrow-multifunction.md`, que e o contrato canonico dos dois) e a
        seta verde (`_dispatch_green_arrow`). Os cinco pontos que ate o item 011
        consumiam o contrato congelado do item 019 passaram a ler vivo:

          1. preflight ORCH   -> `_resolve_interactive_main_llm()`
          2. RoutingState     -> `_resolve_item_provider(spec)` (mesmo resolver
                                 injetado no clique per-item)
          3. espelho /clear   -> os quatro checkboxes de worker
          4. eixo Main-LLM    -> `_resolve_interactive_main_llm()`
          5. `active_flags`   -> `_active_mcp_flags()`

        C16 FECHADO POR REMOCAO DO MECANISMO, nao por implantacao de switch: nao
        existe congelamento a gatear, entao o gate do roster Main NAO ganha
        essa responsabilidade e nenhum kill-switch novo foi criado. O
        dicionario `id(item) -> contrato` foi removido junto, e com ele o
        vazamento por reuso de endereco do CPython (ver comentario no final de
        `_make_item`).

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

        # Item 018: preflight ORCH — barra se a credencial do Main LLM estiver
        # ausente. Item 012 (D5, revoga o item 019): a credencial checada e a do
        # Main VIVO, porque e contra ela que o dispatch vai rodar. Trocar de Main
        # depois de enfileirar muda o destino real do item ja enfileirado, entao
        # checar a credencial do Main congelado avisaria sobre a conta errada.
        _main_vivo = self._resolve_interactive_main_llm()
        _orch_err = self._orch_preflight_main_credential(_main_vivo)
        if _orch_err is not None:
            # Task 24: este e o fail-closed real do dispatch. Sem evento, um
            # loop barrado por credencial ausente fica identico a um loop
            # abandonado — pendentes na lista e nenhuma marca de que alguem
            # tentou. O contexto vem do item barrado, nao do ultimo despachado.
            self._record_provider_blocked(next_item, provider=_main_vivo)
            signal_bus.toast_requested.emit(_orch_err, "warning")
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
        # `dispatch_text` e o produtor renderizado vivo compartilhado com o
        # clique per-item. `command_text` ignora o sufixo de flags e fazia o
        # step perder Delegation flags sob Main Codex/Kimi/Qwen/Grok.
        cmd_text = next_item.dispatch_text()
        cmd_head = spec.name.strip().split(None, 1)[0].lower()

        # ── Provider router (autoridade do worker axis, source.md §12) ─────── #
        # classify_provider (modulo PURO, task 003) e computado PRIMEIRO e e a
        # AUTORIDADE do dispatch dos DOIS eixos worker (Kimi/T2 e Codex/T3) no
        # step/autocast — paridade com o clique direto (command_item_widget, que
        # ja consumia o router). Decide o provider efetivo do item avaliando o
        # eixo Worker antes do Main-LLM (invariante 2) e a precedencia Kimi>Codex
        # (regra 6). RoutingState recebe SOMENTE estado da queue (checkboxes de
        # worker T2/T3 + Main LLM do T1), NUNCA os checkboxes de rota de
        # terminal `terminal-route-t1/t2/t3` (invariante 5; desde 07-27 eles
        # vivem no header de cada terminal, nao mais num bloco unico). Recovery do loop 06-02-seta-unica (decisao do operador:
        # modelo router/whitelist) + fix F-2 (06-02): step e clique agora
        # concordam para Kimi E Codex (antes so o Codex consumia o router; o gate
        # Kimi legado usava is_kimi_compatible isolado e divergia do clique para
        # itens kimi_eligible-only).
        #
        # Item 012 (D5, revoga o item 019): o step deriva o provider do MESMO
        # resolver que o clique per-item usa (`_resolve_item_provider`, injetado
        # em cada CommandItemWidget como `provider_resolver`). Paridade step ==
        # clique por CONSTRUCAO, nao por coincidencia: uma unica funcao monta o
        # RoutingState a partir dos quatro checkboxes de worker vivos + Main vivo
        # e invoca `classify_provider` (no mesmo modulo, entao o patch dos testes
        # continua pegando). Nao ha mais contrato congelado a consultar.
        self._last_classified_provider = self._resolve_item_provider(spec)

        # ── Regra de capacidade exclusiva: GERACAO DE IMAGEM ──────────────── #
        # Enforce mecanico (progress.md "Capacidade exclusiva"): so o Codex gera
        # imagem. Um comando de image-gen roteado a provider != Codex e RECUSADO
        # aqui — nunca despachado ao Claude/Kimi (que falhariam ou, pior,
        # produziriam algo falso). Ative o Worker Codex para roda-lo no T3.
        if (
            is_image_generation_command(spec.name)
            and self._last_classified_provider is not Provider.CODEX
        ):
            # Task 24: bloqueio por capacidade tambem e `provider_blocked`. O
            # provider aqui e o CLASSIFICADO (contra quem a barreira bateu),
            # nao o Codex que deveria ter recebido o item.
            self._record_provider_blocked(
                next_item, provider=self._last_classified_provider
            )
            signal_bus.toast_requested.emit(
                f"{cmd_head}: geracao de imagem so roda no Worker Codex (T3) —"
                " so o Codex gera imagem. Ative o Worker Codex e tente de novo.",
                "warning",
            )
            return

        # Tasks 19/20: marcar a subfase rocksmash como `in_flight` e o ULTIMO
        # gate que pode recusar o item — e por isso vem antes do registro de
        # despacho. Recusa aqui significa "a mesma subfase ja esta em voo num
        # processo vivo"; deixar passar aplicaria o efeito duas vezes.
        if not self._begin_rocksmash_subphase(spec):
            return

        # Task 24: `item_dispatched` so nasce DEPOIS de todo gate que pode
        # recusar o item. Registrar antes fazia o item barrado por capacidade
        # aparecer no corpus como despachado e logo em seguida como bloqueado —
        # um item que nunca saiu contando como saida.
        self._record_loop_dispatch(spec, self._last_classified_provider)

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
        use_qwen = (
            self._last_classified_provider is Provider.QWEN
            and next_item.is_worker_arrow_visible()
        )
        use_mimo = (
            self._last_classified_provider is Provider.MIMO
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
        use_grok = self._last_classified_provider is Provider.GROK

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
        # Item 012 (D5, revoga o item 019): o espelho le os workers VIVOS. Ligar
        # um worker depois de enfileirar um /clear passa a espelhar o /clear —
        # sob o contrato congelado nao espelhava.
        # Item 020: estendido para qwen (T2) e grok (T3).
        _kimi_on = self._use_kimi_chk.isChecked()
        _codex_on = self._use_codex_chk.isChecked()
        _qwen_on = bool(
            getattr(self, "_use_qwen_chk", None) is not None
            and self._use_qwen_chk.isChecked()
        )
        _grok_on = bool(
            getattr(self, "_use_grok_chk", None) is not None
            and self._use_grok_chk.isChecked()
        )
        _t2_active = _kimi_on or _qwen_on
        _t3_active = _codex_on or _grok_on
        clear_both = (
            cmd_head == "/clear"
            and (_t2_active or _t3_active)
        )
        if clear_both:
            self._publish_to_terminal("interactive", route="step/clear-both", text=cmd_text)
            if _t2_active:
                self._publish_to_terminal("workspace", route="step/clear-both", text=cmd_text)
                self._last_workspace_dispatch_was_clear = True
            if _t3_active:
                # task 006 finding F3 — mesmo gate de terminal alvo nao pronto
                # (condicao de falha 4) que ja vale em _dispatch_codex_command:
                # so espelha /clear para o T3 quando o terminal-codex-output
                # esta pronto. Sem o gate, o /clear ia para um xterm inexistente
                # silenciosamente. O T1 ja recebeu /clear raw acima; quando o T3
                # esta indisponivel emitimos toast (Zero Silencio) em vez de
                # publicar no vazio.
                if self._codex_t3_available:
                    self._publish_to_terminal("workspace_xterm", route="step/clear-both", text=cmd_text)
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
        if use_qwen:
            # Seta azul T2: o clique per-item (`_on_exec_clicked` com
            # Provider.QWEN) e o step compartilham `_on_kimi_clicked` ->
            # `_dispatch_blue_arrow`. Occupacao qwen reescreve o payload
            # para `/slash-executor` nativo.
            next_item._on_kimi_clicked()
            self._last_workspace_dispatch_was_clear = False
            return
        if use_mimo:
            # Seta azul T2 com rota propria MiMo (item 007): o clique
            # per-item (`_on_exec_clicked` com Provider.MIMO) e o step
            # compartilham `_on_mimo_clicked` -> `_dispatch_mimo_blue_arrow`.
            # O mark-as-sent fica no slot, depois do envio confirmado; o
            # `_last_workspace_dispatch_was_clear` e consumido no dispatcher.
            next_item._on_mimo_clicked()
            return
        if use_codex:
            if self._dispatch_codex_command(cmd_text, to_t1=False, is_prompt=spec.is_prompt):  # to_t1=False → T3 xterm
                next_item._mark_as_sent()
            return
        if use_grok:
            # Worker T3 Grok uses the same native `/slash-executor` builder
            # as Main Grok. Envelope Codex fica so no worker Codex.
            if self._dispatch_grok_main_command(cmd_text, to_t1=False, is_prompt=spec.is_prompt):
                next_item._mark_as_sent()
            return

        # ── Main-LLM axis ─────────────────────────────────────────────── #
        # No worker claimed this command → dispatch to T1 in the Main LLM's
        # own format.
        # Item 012 (D5, revoga o item 019): le o radio VIVO. A troca de Main LLM
        # entre enqueue e dispatch ALTERA, por decisao humana explicita, o
        # formato de dispatch do item ja enfileirado — o estado vivo da UI e a
        # unica fonte do dispatch. Esta e a linha que faz o step convergir com
        # `_dispatch_green_arrow`, que ja lia `_main_*_radio.isChecked()`.
        _main = self._resolve_interactive_main_llm()
        if _main == "codex":
            if self._dispatch_codex_command(cmd_text, to_t1=True, is_prompt=spec.is_prompt):
                next_item._mark_as_sent()
            return
        if _main == "kimi":
            if self._dispatch_kimi_main_command(cmd_text, is_prompt=spec.is_prompt):
                next_item._mark_as_sent()
            return
        if _main == "qwen":
            if self._dispatch_qwen_main_command(cmd_text, is_prompt=spec.is_prompt):
                next_item._mark_as_sent()
            return
        if _main == "mimo":
            # Sem esta branch, Main=MiMo caia no dispatch raw de Claude e o
            # TUI da MiMo recebia o slash cru, sem o executor nativo.
            if self._dispatch_mimo_main_command(cmd_text, is_prompt=spec.is_prompt):
                next_item._mark_as_sent()
            return
        if _main == "grok":
            # Sem esta branch, Main=Grok caia no dispatch raw de Claude logo
            # abaixo: o comando ia para T1 no formato do Claude enquanto o
            # radio marcado dizia Grok. `_dispatch_green_arrow` ja roteava
            # certo — era so o "Rodar proximo" que divergia.
            if self._dispatch_grok_main_command(cmd_text, is_prompt=spec.is_prompt):
                next_item._mark_as_sent()
            return

        # Claude main (default): raw dispatch to T1 interactive.
        # Item 012: usa command_text_with_flags (produtor unico) em vez da
        # computacao duplicada de flag_suffix. Paridade byte-a-byte com
        # per-item run/copy e mass copy (caminho 4). classify_provider ja
        # rodou e _last_classified_provider e CLAUDE neste ramo — o worker
        # axis e as esteiras Main Codex/Kimi retornaram ANTES.
        # Item 012 (D5, revoga o item 019): le as flags VIVAS. O sufixo que o
        # step despacha passa a ser o mesmo que o label do item mostra depois de
        # um toggle — sob o contrato congelado os dois divergiam.
        active_flags = self._active_mcp_flags()
        cmd_text_t1 = command_text_with_flags(
            spec,
            provider=self._last_classified_provider,
            active_flags=active_flags,
        )
        self._publish_to_terminal("interactive", route="step/claude-main", text=cmd_text_t1)
        self._on_run_command(cmd_text_t1)
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
