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
import logging
from pathlib import Path
import os
import re

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
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

from workflow_app import dcp as dcp_pkg
from workflow_app.command_queue.command_item_widget import CommandItemWidget
from workflow_app.command_queue.kimi_whitelist import is_kimi_compatible
from workflow_app.dcp.specific_flow_handler import build_paste_command_only
from workflow_app.dialogs.confirm_cancel_modal import ConfirmCancelModal
from workflow_app.domain import CommandSpec, CommandStatus, EffortLevel, InteractionType, ModelName
from workflow_app.signal_bus import signal_bus
from workflow_app.templates.quick_templates import (
    TEMPLATE_AUTO_IMPROOVE,
    TEMPLATE_BLOG,
    TEMPLATE_BOILERPLATE,
    TEMPLATE_BRIEF_FEATURE,
    TEMPLATE_BRIEF_NEW,
    TEMPLATE_BUSINESS,
    TEMPLATE_CREATE_DAILY_LOOP,
    TEMPLATE_DAILY,
    TEMPLATE_DEPLOY,
    TEMPLATE_HOSTGATOR,
    TEMPLATE_INTAKE_REVIEW,
    TEMPLATE_INTAKE_SEED,
    TEMPLATE_JSON,
    TEMPLATE_LISTENER_TEST,
    TEMPLATE_MIGRATION,
    TEMPLATE_MKT,
    TEMPLATE_MODULES,
    TEMPLATE_PYTHON_IMPROOVE,
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

logger = logging.getLogger(__name__)

_MODEL_MAP = {
    "opus": ModelName.OPUS,
    "sonnet": ModelName.SONNET,
    "haiku": ModelName.HAIKU,
}

_EFFORT_MAP = {
    "low": EffortLevel.LOW,
    "medium": EffortLevel.STANDARD,
    "high": EffortLevel.HIGH,
    "max": EffortLevel.MAX,
}


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
        self._cli_binary = "clauded"  # Active CLI instance (updated via instance_selected)

        # Pending modal-confirmation Enter (currently used by /effort to
        # auto-dismiss Claude Code's confirmation prompt). Stored so the
        # next dispatch can cancel it — otherwise the late Enter fires
        # into AskUserQuestion menus or other interactive prompts of the
        # next command and selects the default option.
        self._pending_modal_enter_timer: QTimer | None = None

        # Tracks whether the LAST workspace dispatch was /clear. The next
        # blue-arrow Kimi dispatch reads this to add 2s extra delay before
        # Enter (Kimi takes longer to render its prompt right after a clear
        # because the whole TUI is being repainted from scratch).
        self._last_workspace_dispatch_was_clear: bool = False

        # Onda 4: SPECIFIC-FLOW.json path of the currently-loaded DCP queue,
        # set by `_on_dcp_specific_flow_clicked` after a successful load.
        # When set, [Remove] persists the deleted command name to
        # overrides.skipped[] in this file so the next reload (or regen
        # without --reset-overrides) honors the deletion. Cleared by any
        # other pipeline_ready emission to avoid leaking DCP context into
        # legacy templates.
        self._current_dcp_flow_path: Path | None = None

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
        _tab_testids = ("queue-tab-daily", "queue-tab-workflow", "queue-tab-auxiliar")
        for i, label in enumerate(("Daily", "Workflow", "Auxiliar")):
            btn = QPushButton(label.upper())
            btn.setFixedHeight(22)
            btn.setProperty("testid", _tab_testids[i])
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
            ("Create daily loop",
             "Create Daily Loop — roda /daily-loop no terminal (Opus/HIGH). "
             "Pipeline interativo: scan -> plan -> enumerate. Gera "
             "blacksmith/loop-archives/{slug}/ com PROGRESS.md, tasks/T-{model}-{effort}.md "
             "e _LOOP-CONFIG.json. Depois carregue o _LOOP-CONFIG.json em "
             "metrics-project-pill e clique [Execute daily loop].",
             self._on_create_daily_loop_clicked,
             "queue-btn-create-daily-loop"),
            ("Cmd Single",
             "Cmd Single — pipeline reduzida para criar/atualizar UM comando "
             "avulso sem preparo terminal. Selecione um .md com heading canonico "
             "(# /grupo:nome) e o workflow-app expande a sub-sequencia inline.",
             self._on_cmd_single_clicked,
             "queue-btn-cmd-single"),
            ("Execute daily loop",
             "Execute Daily Loop — expande a fila finita gerada por Create. "
             "Le _LOOP-CONFIG.json + PROGRESS.md do projeto carregado e cria "
             "para CADA item pendente: /daily-loop:do (bucket model/effort) + "
             "/daily-loop:review-done (Opus/standard, /skill:double-mcp Level 3 "
             "CROSS_ADVERSARIAL — analogo per-item de /review-executed-task, "
             "reverte+corrige+re-acceptance se achar regressao). Final: "
             "/daily-loop:review global em Opus/HIGH. /clear/model/effort "
             "dedupados entre buckets.",
             self._on_daily_loop_clicked, "queue-btn-execute-daily-loop"),
            ("intake-seed", "Intake Seed — prepara base maximamente expandida para o intake-review. Dupla função: (1) /intake:obvious melhora o INTAKE.md original; (2) /intake-review:seed gera INTAKE.seeded.md + MILESTONES.seeded.md consolidando features em docs_root/features/*. Passa project.json da pill.",
             lambda: self._load_quick_template(TEMPLATE_INTAKE_SEED, name="Intake Seed"),
             "queue-btn-intake-seed"),
            ("intake-review", "Intake Review (F9): create-checklist → list-improove → compare → create-gaplist → execute-gaplist-p0 → execute-gaplist-p1 → execute-gaplist-p2 → review-executed → clear",
             lambda: self._load_quick_template(TEMPLATE_INTAKE_REVIEW, name="Intake Review"),
             "queue-btn-intake-review"),
            ("delivery plan", "Planejamento: analyse → identify → create-tasks",
             self._on_delivery_plan_clicked, "queue-btn-delivery-plan"),
            ("delivery qa", "Validacao: qa-gate → mcp-review → sign-off",
             self._on_delivery_qa_clicked, "queue-btn-delivery-qa"),
            ("blog", "Blog SEO: estratégia → keywords → clusters → artigos → deploy",
             lambda: self._load_quick_template(TEMPLATE_BLOG, name="Blog SEO"),
             "queue-btn-blog"),
            ("auto-improove", "Melhoria contínua do SystemForge — 1 iteração (~10% por rodada, use Loop ×10). Sem vínculo com projeto.",
             self._on_auto_improove_balanced_clicked,
             "queue-btn-auto-improove-balanced"),
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
            ("Modules (Creation)", "Fase A do canonical loop — cria estrutura WBS, MODULE-META.json e delivery.json. Pre-requisito de [DCP: Build Module Pipeline].",
             lambda: self._load_quick_template(TEMPLATE_MODULES, name="Modules"),
             "queue-btn-modules"),
            ("DCP: Gerar Pipeline (regen)",
             "DESTRUTIVO quando SPECIFIC-FLOW.json ja existe.\n"
             "Cola /build-module-pipeline no terminal — decide automaticamente entre novo "
             "pipeline (state=pending) ou --regenerate (sobrescreve, salva .bak-{ISO}). "
             "Edicoes manuais no SPECIFIC-FLOW.json sao perdidas. "
             "Modal de confirmacao aparece antes do paste quando o arquivo ja existe.",
             self._on_dcp_build_clicked, "queue-btn-dcp-build"),
            ("DCP: Specific-Flow (load)",
             "Le o SPECIFIC-FLOW.json do modulo atual e carrega os comandos na fila para "
             "execucao manual.\n"
             "ATENCAO: deletes/reorder na fila visual sao TRANSIENT — re-clicar este botao "
             "recarrega do disco e os itens removidos voltam. Para fix permanente, edite "
             "MODULE-META.json e regenere via [DCP: Gerar Pipeline].",
             self._on_dcp_specific_flow_clicked, "queue-btn-dcp-specific-flow"),
            ("specific-flow (legacy)", "[legacy custom-template] — use DCP: Specific-Flow",
             self._on_specific_flow_clicked, "queue-btn-specific-flow"),
            ("qa", "[legacy F9] QA + auditoria de stack (selecione a stack no modal)",
             self._on_qa_clicked, "queue-btn-qa"),
            ("deploy", "[legacy F11] CI/CD, infra, pre-deploy, SLO, changelog",
             lambda: self._load_quick_template(TEMPLATE_DEPLOY, name="Deploy"),
             "queue-btn-deploy"),

        ])
        self._apply_dcp_reader_gating(workflow_content)
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
            ("boilerplate", "Boilerplate: scan → convert-nextjs → cleanup → persona → mockify → persona-assets → enhance-fe → gen-sql → finalize. Abre modal para path do repo (NAO le project.json).",
             self._on_boilerplate_clicked, "queue-btn-boilerplate"),
            ("micro-arch", "Carrega pipeline de micro-arquitetura",
             self._on_micro_arch_clicked, "queue-btn-micro-arch"),
            ("listener-test", "Testa o ciclo do listener-workspace dot. Carrega /test-autoflow-auto (compativel Kimi via /skill:test-autoflow-auto).",
             lambda: self._load_quick_template(TEMPLATE_LISTENER_TEST, name="Listener Test"),
             "queue-btn-listener-test"),
            ("python-improove", "Auto-Improove Python — /model opus + /effort high + 20× (/clear + /auto-improove:python). Delega trechos deterministicos dos comandos para scripts Python co-localizados. Sem vinculo com projeto.",
             self._on_python_improove_clicked,
             "queue-btn-python-improove"),
            ("micro-json", "Configura project.json para micro-arquitetura",
             self._on_micro_json_clicked, "queue-btn-micro-json"),
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

        # "Rodar próximo" — botão dominante da play bar (primeira posição,
        # verde #16A34A, stretch=7). Executa o proximo item pendente da fila e
        # para. Funciona em qualquer item (auto ou interactive). Diferente do
        # _btn_next ("Continuar: X") que aparece SO em pause de interactive.
        self._play_btn = QPushButton("▶  Rodar próximo")
        self._play_btn.setProperty("testid", "queue-btn-play-next")
        self._play_btn.setFixedHeight(32)
        self._play_btn.setToolTip(
            "Executa o proximo item pendente da fila e para.\n"
            "Funciona com qualquer item — auto ou interactive."
        )
        self._play_btn.setStyleSheet(
            "QPushButton { background-color: #16A34A; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 13px; font-weight: 700; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:pressed { background-color: #166534; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        self._play_btn.clicked.connect(self._on_step_btn_clicked)
        pl.addWidget(self._play_btn, stretch=7)

        # Use Kimi checkbox — quando marcado, [Rodar próximo] (queue-btn-play-next)
        # clica na seta AZUL (kimi) ao inves da VERDE (claude) para items que
        # estao na whitelist Kimi (kimi_whitelist.is_kimi_compatible). Items
        # fora da whitelist seguem rodando no Claude independente do estado do
        # checkbox. Ocupa o slot que antes era do botão Autocast (removido).
        _kimi_box = QWidget()
        _kimi_box.setProperty("testid", "queue-div-use-kimi")
        _kimi_box.setFixedHeight(32)
        _kimi_box.setStyleSheet(
            "QWidget { background-color: #1C1C1F; border: 1px solid #3F3F46;"
            "  border-radius: 5px; }"
        )
        _kbl = QHBoxLayout(_kimi_box)
        _kbl.setContentsMargins(10, 0, 10, 0)
        _kbl.setSpacing(8)
        self._use_kimi_chk = QCheckBox("Use Kimi")
        self._use_kimi_chk.setProperty("testid", "queue-chk-use-kimi")
        self._use_kimi_chk.setToolTip(
            "Quando marcado, [Rodar próximo] dispara via Kimi (seta azul) para\n"
            "items kimi-compatible. Items fora da whitelist seguem rodando no\n"
            "Claude (seta verde) — checkbox e ignorado nesse caso."
        )
        self._use_kimi_chk.setStyleSheet(
            "QCheckBox { color: #FAFAFA; font-size: 11px; font-weight: 600;"
            "  background: transparent; border: none; padding: 0; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
            "QCheckBox::indicator:unchecked { background-color: #3F3F46;"
            "  border: 1px solid #52525B; border-radius: 3px; }"
            "QCheckBox::indicator:checked { background-color: #3B82F6;"
            "  border: 1px solid #3B82F6; border-radius: 3px; }"
            "QCheckBox::indicator:hover { border-color: #93C5FD; }"
        )
        _kbl.addWidget(self._use_kimi_chk)
        pl.addWidget(_kimi_box, stretch=2)

        # Botão JSON — copia path do project.json para o clipboard
        self._json_btn = QPushButton("JSON")
        self._json_btn.setProperty("testid", "queue-btn-json-path")
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
        self._ws_btn.setProperty("testid", "queue-btn-ws-path")
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
        self._notepad_edit.setAttribute(
            Qt.WidgetAttribute.WA_InputMethodEnabled, True,
        )
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
        self._items_container.setProperty("testid", "queue-command-list")
        self._items_container.setStyleSheet("background-color: #18181B;")
        self._items_container.setAcceptDrops(True)
        self._items_container.installEventFilter(self)
        self._notepad_edit.installEventFilter(self)
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
        save_btn.setProperty("testid", "queue-btn-save")
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
        signal_bus.instance_selected.connect(self._on_instance_selected)
        signal_bus.autocast_step_requested.connect(self._on_autocast_step_requested)
        self._btn_next.clicked.connect(self._on_btn_next_clicked)

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
            active = i == self._active_section
            btn.setStyleSheet(_TAB_ACTIVE_STYLE if active else _TAB_INACTIVE_STYLE)
            content.setVisible(active)

    # ──────────────────────────────────────────────────── Public API ─── #

    def set_pipeline_manager(self, pipeline_manager) -> None:
        """Inject the PipelineManager to enable can_reorder guards."""
        self._pipeline_manager = pipeline_manager

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
        self._maybe_auto_save(name)

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

    def _on_specific_flow_clicked(self) -> None:
        """Load SPECIFIC-FLOW.json generated by /workflow-custom-template.

        Reads the pre-generated JSON directly — does NOT call _load_quick_template
        because the JSON already contains /model and /clear commands.
        config_path is left empty; main_window._on_pipeline_ready sets it on load.
        """
        from workflow_app.config.app_state import app_state

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um projeto antes de usar o Specific Flow.", "warning"
            )
            return

        config = app_state.config
        custom_root = config.custom_workflow_root or f"{config.wbs_root}/specific-flow"
        flow_path = Path(config.project_dir) / custom_root / "SPECIFIC-FLOW.json"

        if not flow_path.exists():
            signal_bus.toast_requested.emit(
                f"SPECIFIC-FLOW.json não encontrado em {custom_root}/. "
                "Execute /workflow-custom-template primeiro.",
                "warning",
            )
            return

        try:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            signal_bus.toast_requested.emit(
                f"Erro ao ler SPECIFIC-FLOW.json: {exc}", "error"
            )
            return

        _model_map = {
            "opus": ModelName.OPUS,
            "sonnet": ModelName.SONNET,
            "haiku": ModelName.HAIKU,
        }
        specs: list[CommandSpec] = []
        for i, cmd in enumerate(data.get("commands", []), start=1):
            name = cmd.get("name", "")
            model = _model_map.get(str(cmd.get("model", "sonnet")).lower(), ModelName.SONNET)
            interaction = (
                InteractionType.INTERACTIVE
                if str(cmd.get("interaction", "auto")).lower() == "inter"
                else InteractionType.AUTO
            )
            specs.append(
                CommandSpec(
                    name=name,
                    model=model,
                    interaction_type=interaction,
                    config_path="",
                    position=i,
                )
            )

        if not specs:
            signal_bus.toast_requested.emit("SPECIFIC-FLOW.json está vazio.", "warning")
            return

        project = data.get("project", config.project_name)
        self._template_label.setText(f"  \U0001f4cb  Specific Flow — {project}")
        self._template_label.setVisible(True)
        self._maybe_auto_save("Specific Flow")
        signal_bus.pipeline_ready.emit(specs)

    def _on_qa_clicked(self) -> None:
        """Open QA modal with stack options."""
        from workflow_app.dialogs.qa_stack_dialog import QAStackDialog

        dlg = QAStackDialog(parent=self)
        if dlg.exec() == QAStackDialog.Accepted:
            self._load_quick_template(dlg.selected_template, name="QA")

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

    def _on_dcp_build_clicked(self) -> None:
        """Paste canonical `/build-module-pipeline` command — Phase A pre-req gate.

        MVP gate (per Codex review T-013/T-052):
          1. has_config (project loaded)
          2. delivery.json exists + DeliveryFound (CLI requires it; no bootstrap)
          3. execution_mode != parallel-independent (or block ambiguous case)
          4. current_module exists, module exists, state != done
          5. MODULE-META.json exists, parses, has minimal canonical fields

        Choses ``--regenerate`` when module is past pending (state in
        creation/execution/etc) so the SPECIFIC-FLOW is re-emitted without
        re-transitioning state. Falls back to bare command only when the reader
        is genuinely unavailable.
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
            return
        config = app_state.config

        # Reader unavailable — emit bare command and let CLI surface errors
        if not dcp_pkg.READER_AVAILABLE:
            cmd = build_paste_command_only(config=config)
            logger.warning("[DCP] reader ausente — colando comando bare")
            signal_bus.paste_text_in_terminal.emit(cmd)
            signal_bus.focus_interactive_terminal.emit()
            return

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
            return
        if isinstance(result, DeliveryInvalid):
            QMessageBox.information(
                self, "DCP",
                f"delivery.json invalido: {result.error}. Rode /delivery:validate.",
            )
            return
        if isinstance(result, DeliveryFutureVersion):
            QMessageBox.information(self, "DCP", result.message)
            return

        assert isinstance(result, DeliveryFound)
        delivery = result.delivery

        # Gate 3 — parallel-independent requires explicit module selection
        if delivery.execution_mode == "parallel-independent":
            QMessageBox.information(
                self, "DCP",
                "execution_mode=parallel-independent requer selecao explicita "
                "do modulo. Use o botao DCP no card do modulo desejado.",
            )
            return

        # Gate 4 — current_module is set, exists in modules, not done
        cm_id = delivery.current_module
        if not cm_id:
            QMessageBox.information(
                self, "DCP",
                "current_module nao definido em delivery.json. "
                "Rode /modules:create-structure ou /delivery:validate.",
            )
            return
        if delivery.modules and all(
            m.state == "done" for m in delivery.modules.values()
        ):
            QMessageBox.information(
                self, "DCP", "Todos os modulos estao concluidos."
            )
            return
        module = delivery.modules.get(cm_id)
        if module is None:
            QMessageBox.information(
                self, "DCP",
                f"current_module={cm_id!r} nao existe em modules. "
                "Rode /delivery:validate.",
            )
            return
        if module.state == "done":
            QMessageBox.information(
                self, "DCP",
                f"Modulo {cm_id!r} ja concluido. "
                "Use /delivery:sign-off ou inicie o proximo modulo.",
            )
            return

        # Gate 5 — MODULE-META.json exists, parses, has minimal canonical fields
        meta_path = wbs_root / "modules" / cm_id / "MODULE-META.json"
        if not meta_path.exists():
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json ausente em {meta_path.name}. Phase A nao "
                "foi completada. Rode Modules (queue-btn-modules).",
            )
            return
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json corrupto: {exc}. "
                "Re-rode Modules (queue-btn-modules).",
            )
            return
        required_keys = {"module_id", "module_name", "module_type"}
        missing = required_keys - set(meta.keys())
        if missing:
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json incompleto. Faltam: {sorted(missing)}. "
                "Re-rode Modules (queue-btn-modules).",
            )
            return
        # Identity check — meta.module_id MUST match delivery.json[modules] key,
        # otherwise we'd run pipeline against the wrong module's spec.
        if meta.get("module_id") != cm_id:
            QMessageBox.information(
                self, "DCP",
                f"MODULE-META.json identifica module_id={meta.get('module_id')!r} "
                f"mas delivery.json aponta current_module={cm_id!r}. "
                "Resolva o desalinhamento antes de prosseguir.",
            )
            return

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
                return

        # All gates passed — choose --regenerate when module is past pending
        regenerate = module.state != "pending"

        # Destructive guard — when --regenerate AND SPECIFIC-FLOW.json already
        # exists on disk, surface metadata + warn about manual-edit loss before
        # pasting. CLI still backs up to .bak-{ISO_UTC} but the queue UI will
        # re-mirror the regenerated file, so any manual deletes are wiped.
        if regenerate:
            flow_path = wbs_root / "modules" / cm_id / "SPECIFIC-FLOW.json"
            if flow_path.exists():
                command_count: int | None = None
                try:
                    flow_data = json.loads(flow_path.read_text(encoding="utf-8"))
                    if isinstance(flow_data, dict):
                        commands_raw = flow_data.get("commands")
                        if isinstance(commands_raw, list):
                            command_count = len(commands_raw)
                except (json.JSONDecodeError, OSError):
                    command_count = None

                from workflow_app.dialogs.confirm_regenerate_specific_flow_modal import (
                    ConfirmRegenerateSpecificFlowModal,
                )

                modal = ConfirmRegenerateSpecificFlowModal(
                    flow_path=flow_path,
                    command_count=command_count,
                    cm_id=cm_id,
                    parent=self,
                )
                if modal.exec() != QDialog.DialogCode.Accepted:
                    logger.info(
                        "[DCP] regen cancelado pelo usuario (modulo=%s, cmds=%s)",
                        cm_id, command_count,
                    )
                    return

        cmd = build_paste_command_only(
            config=config, current_module=cm_id, regenerate=regenerate,
        )
        logger.info("[DCP] pasting %r (regenerate=%s)", cmd, regenerate)
        signal_bus.paste_text_in_terminal.emit(cmd)
        signal_bus.focus_interactive_terminal.emit()

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
                f"SPECIFIC-FLOW.json nao encontrado para {cm_id}. "
                f"Execute [DCP: Gerar Pipeline] primeiro.{dep_extra}",
                "warning",
            )
            return

        try:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            signal_bus.toast_requested.emit(f"Erro ao ler SPECIFIC-FLOW.json: {exc}", "error")
            return

        if not isinstance(data, dict):
            signal_bus.toast_requested.emit(
                "SPECIFIC-FLOW.json invalido: root deve ser um objeto JSON.", "error"
            )
            return

        commands_raw = data.get("commands", [])
        if not isinstance(commands_raw, list):
            signal_bus.toast_requested.emit(
                "SPECIFIC-FLOW.json invalido: campo 'commands' deve ser uma lista.", "error"
            )
            return

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

        _model_map = {
            "opus": ModelName.OPUS,
            "sonnet": ModelName.SONNET,
            "haiku": ModelName.HAIKU,
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
            return

        project = data.get("project", config.project_name)
        logger.info("[DCP] loading pipeline from %s (%d commands)", flow_path, len(specs))
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
        if self._use_kimi_chk.isChecked():
            commands.extend([
                "/clear",
                f"/cmd:kimi-pair-analyse --approved {md_path_str}",
                f"/kimi:pair-execute --approved {md_path_str}",
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

    def _on_create_daily_loop_clicked(self) -> None:
        """Unified loop runner: detects JSON format and expands queue.

        - *-loop.json  -> expand iteration_template per item + finalization
        - _LOOP-CONFIG.json (daily-loop) -> delegate to legacy _on_daily_loop_clicked
        """
        from workflow_app.config.app_state import app_state

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um loop JSON em metrics-project-pill antes de executar.",
                "warning",
            )
            return

        config = app_state.config
        raw = config.raw if isinstance(config.raw, dict) else {}

        # Discriminate by schema
        if raw.get("kind") == "daily-loop" and "daily_loop" in raw:
            self._on_daily_loop_clicked()
            return

        if "iteration_template" in raw and "items" in raw and "finalization" in raw:
            try:
                specs = self._expand_loop_json_specs(raw, str(config.config_path))
            except Exception as exc:
                signal_bus.toast_requested.emit(
                    f"Erro ao expandir loop JSON: {exc}", "error"
                )
                return

            if not specs:
                signal_bus.toast_requested.emit(
                    "Loop JSON sem comandos para executar.", "info"
                )
                return

            slug = str(raw.get("name", "")) or "loop"
            item_count = sum(
                1
                for s in specs
                if not s.name.startswith(("/model ", "/effort ", "/clear"))
            )
            self._template_label.setText(
                f"  \U0001f4cb  Loop: {slug} ({item_count} comandos)"
            )
            self._template_label.setVisible(True)
            self._maybe_auto_save(f"Loop {slug}")
            signal_bus.pipeline_ready.emit(specs)
            return

        signal_bus.toast_requested.emit(
            "Projeto carregado nao e um loop valido. "
            "Carregue um _LOOP-CONFIG.json ou um *-loop.json.",
            "warning",
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
            kimi_eligible = (
                bool(item.get("kimi_eligible", False))
                if isinstance(item, dict)
                else False
            )

            phases = ["pre", "exec", "post"]
            if (
                kimi_eligible
                and "kimi_eligible_wrapper" in iteration_template
                and self._use_kimi_chk.isChecked()
            ):
                phases = ["pre", "kimi_eligible_wrapper", "post"]

            for phase in phases:
                commands = iteration_template.get(phase, [])
                for cmd in commands:
                    resolved = cmd.replace("{task_path}", task_path).replace(
                        "{name}", loop_name
                    )
                    _add_command(resolved, kimi_eligible=kimi_eligible)

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
        item_count = sum(1 for s in specs if s.name.startswith("/daily-loop:do "))
        logger.info("[daily-loop] loading %s (%d items, %d specs)", slug, item_count, len(specs))

        self._template_label.setText(f"  \U0001f4cb  Daily loop: {slug} ({item_count} itens)")
        self._template_label.setVisible(True)
        self._maybe_auto_save(f"Daily loop {slug}")
        signal_bus.pipeline_ready.emit(specs)

    def _on_auto_improove_balanced_clicked(self) -> None:
        """Load the auto-improove balanced flow (Daily tab).

        Comportamento especial: NÃO requer projeto carregado e NÃO anexa
        config_path a nenhum comando. Este template opera sobre o próprio
        SystemForge (.claude/commands/, ai-forge/), sem vínculo com projeto.

        Para recalcular as quantidades: /auto-improove:update-workflow-template
        """
        raw = copy.deepcopy(TEMPLATE_AUTO_IMPROOVE)
        for spec in raw:
            spec.config_path = ""  # Sem project.json — opera sobre o SystemForge

        self._template_label.setText("  \U0001f4cb  Auto-Improove")
        self._template_label.setVisible(True)
        self._maybe_auto_save("Auto-Improove")

        expanded: list[CommandSpec] = []
        current_model = None
        for spec in raw:
            if spec.name == "/clear":
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
            "Auto-Improove carregado — sem projeto. Use Loop ×10 para completar tudo.", "info"
        )

    def _on_python_improove_clicked(self) -> None:
        """Load the python-improove flow (Auxiliar tab).

        Comportamento especial: NAO requer projeto carregado e NAO anexa
        config_path a nenhum comando. Opera sobre o proprio SystemForge
        (.claude/commands/), igual ao auto-improove balanced.
        """
        raw = copy.deepcopy(TEMPLATE_PYTHON_IMPROOVE)
        for spec in raw:
            spec.config_path = ""

        self._template_label.setText("  \U0001f4cb  Python Improove")
        self._template_label.setVisible(True)
        self._maybe_auto_save("Python Improove")

        for i, spec in enumerate(raw, start=1):
            spec.position = i

        signal_bus.pipeline_ready.emit(raw)
        signal_bus.toast_requested.emit(
            "Python Improove carregado — sem projeto. 20 iteracoes.", "info"
        )

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

    def _on_delivery_plan_clicked(self) -> None:
        """Build Delivery PLAN template (before code — analyse/identify/create-tasks)."""
        from workflow_app.config.app_state import app_state
        from workflow_app.templates.quick_templates import _inject_clears
        from workflow_app.templates.delivery_template_builder import build_delivery_plan_template

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um projeto antes de usar o Delivery.", "warning"
            )
            return

        config = app_state.config
        template = build_delivery_plan_template(
            docs_root=config.docs_root,
            project_dir=str(config.project_dir),
            wbs_root=config.wbs_root,
        )

        if not template:
            signal_bus.toast_requested.emit(
                "Nenhuma milestone encontrada em MILESTONES.md (nem MILESTONES.seeded.md). Execute /modules:build-milestones ou /intake-review:seed primeiro.",
                "warning",
            )
            return

        self._load_quick_template(_inject_clears(template), name="Delivery Plan")

    def _on_delivery_qa_clicked(self) -> None:
        """Build Delivery QA template (after code — qa-gate/mcp-review/sign-off)."""
        from workflow_app.config.app_state import app_state
        from workflow_app.templates.quick_templates import _inject_clears
        from workflow_app.templates.delivery_template_builder import build_delivery_qa_template

        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "Carregue um projeto antes de usar o Delivery.", "warning"
            )
            return

        config = app_state.config
        template = build_delivery_qa_template(
            docs_root=config.docs_root,
            project_dir=str(config.project_dir),
            wbs_root=config.wbs_root,
        )

        if not template:
            signal_bus.toast_requested.emit(
                "Nenhuma milestone encontrada em MILESTONES.md (nem MILESTONES.seeded.md). Execute /modules:build-milestones ou /intake-review:seed primeiro.",
                "warning",
            )
            return

        self._load_quick_template(_inject_clears(template), name="Delivery QA")

    def _on_run_command(self, cmd_text: str) -> None:
        """Update last-command label and highlight the matching queue row."""
        parts = cmd_text.strip().split()
        self._last_cmd_label.setText("\n".join(parts))
        self._last_cmd_label.setVisible(True)
        self._highlight_current_command(cmd_text.strip())
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
        # Mirror /clear to workspace when Use Kimi is checked. This fires on
        # ANY path that emits run_in_terminal_requested (per-item green play,
        # autocast clicks via play_btn, etc.) so the duplicate dispatch is
        # not coupled to a single entry point in this widget.
        item.run_in_terminal_requested.connect(self._mirror_clear_to_workspace_if_kimi_checked)
        item.run_in_kimi_terminal_requested.connect(self._dispatch_blue_arrow)
        item.run_in_kimi_terminal_requested.connect(self._on_run_command)
        return item

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
        """
        if self._last_workspace_dispatch_was_clear:
            delay = (
                self._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
                + self._KIMI_AFTER_CLEAR_EXTRA_DELAY_MS
            )
            self._last_workspace_dispatch_was_clear = False  # consumed
        else:
            delay = self._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
        signal_bus.kimi_blue_arrow_dispatched.emit(kimi_prompt, delay)

    def _mirror_clear_to_workspace_if_kimi_checked(self, cmd_text: str) -> None:
        """When /clear is dispatched to interactive AND Use Kimi is checked,
        also emit it to the workspace terminal so both CLI sessions clear
        their context simultaneously, AND set the after-clear flag so the
        next blue-arrow Kimi dispatch uses the extended 3s delay (Kimi's
        TUI repaint after a clear is slower than normal).

        Connected to `item.run_in_terminal_requested` so it runs for every
        per-item green-button dispatch (the entry point most users actually
        click). The "Rodar próximo" path bypasses item signals and emits
        directly to the bus, so it has its own clear-both branch (which
        also sets the flag).
        """
        if not cmd_text or not cmd_text.strip():
            return
        head = cmd_text.strip().split(None, 1)[0].lower()
        if head == "/clear" and self._use_kimi_chk.isChecked():
            signal_bus.run_command_in_workspace_terminal.emit(cmd_text)
            self._last_workspace_dispatch_was_clear = True

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
        """Return the current template label text (strip leading icon/space)."""
        text = self._template_label.text().strip()
        # Remove leading emoji + space (e.g. "  📋  Brief — Novo Projeto")
        for prefix in ("📋", "🔎"):
            if prefix in text:
                text = text.split(prefix, 1)[-1].strip()
        return text

    def get_last_command_text(self) -> str:
        """Return the current last-command label text."""
        return self._last_cmd_label.text().strip()

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
        # Reset input method on notepad focus to prevent rare IME freeze
        if obj is self._notepad_edit and event.type() == QEvent.Type.FocusIn:
            im = QApplication.inputMethod()
            if im is not None:
                im.reset()
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

    def _on_command_skipped(self, index: int) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.PULADO)

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

    def _on_notepad_send(self) -> None:
        """Send notepad text to terminal (no Enter, no clear), then focus terminal."""
        text = self._notepad_edit.toPlainText()
        if text:
            signal_bus.paste_text_in_terminal.emit(text)
            signal_bus.focus_interactive_terminal.emit()

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

        # Dispatch via Kimi (blue arrow) or Claude (green arrow).
        # Routing rule:
        #   - checkbox checked AND command in kimi whitelist
        #     AND item's _kimi_btn is actually visible -> kimi click
        #   - otherwise -> claude (green) click
        # The triple condition guards against whitelist/visibility divergence
        # (real risk flagged by /skill:mcp-kimi senior-reviewer): if the
        # per-item _kimi_btn was hidden by some future spec mutation while
        # is_kimi_compatible still returns True, fall back to claude rather
        # than dispatch a kimi action with no visual feedback.
        #
        # Asymmetry note: kimi branch delegates to _on_kimi_clicked (which
        # internally does signal emit + _mark_as_sent). Claude branch
        # orchestrates manually. Contract: _on_kimi_clicked is the canonical
        # handler of the blue arrow — do not inline its body here, mirror its
        # invocation. If _on_kimi_clicked grows side effects, this routing
        # automatically inherits them (single source of truth).
        cmd_text = next_item.command_text()
        cmd_head = spec.name.strip().split(None, 1)[0].lower()
        use_kimi = (
            self._use_kimi_chk.isChecked()
            and is_kimi_compatible(spec.name)
            and getattr(next_item, "_kimi_btn", None) is not None
            and next_item._kimi_btn.isVisible()
        )

        # ALWAYS cancel any pending modal-confirmation Enter from a previous
        # dispatch. Otherwise a 1s-delayed Enter scheduled by a previous
        # /effort can fire into the next command's AskUserQuestion menu
        # and silently select the default option.
        self._cancel_pending_modal_enter()

        # Special case: /clear with Use Kimi checkbox active clears BOTH
        # CLI sessions (interactive + workspace). The two emits drive
        # MetricsBar's per-channel auto-idle independently, so each dot
        # turns green on its own 1s timer.
        clear_both = (
            cmd_head == "/clear" and self._use_kimi_chk.isChecked()
        )
        if clear_both:
            signal_bus.run_command_in_terminal.emit(cmd_text)
            signal_bus.run_command_in_workspace_terminal.emit(cmd_text)
            self._on_run_command(cmd_text)
            next_item._mark_as_sent()
            self._last_workspace_dispatch_was_clear = True
        elif use_kimi:
            next_item._on_kimi_clicked()
            self._last_workspace_dispatch_was_clear = False  # consumed by blue arrow
        else:
            signal_bus.run_command_in_terminal.emit(cmd_text)
            self._on_run_command(cmd_text)
            next_item._mark_as_sent()
            # Pure interactive dispatch does not affect the workspace flag.

        # /effort pede confirmação no Claude Code: agenda um Enter extra 1s
        # depois para aceitar o prompt automaticamente. O timer é cancelado
        # se um novo dispatch acontecer antes do Enter firar (proteção
        # contra firar dentro de AskUserQuestion do próximo comando).
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
