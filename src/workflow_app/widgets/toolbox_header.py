"""
ToolboxHeader — Compact strip above the terminal with Skills, Tools, and Meta buttons.

Buttons paste their command name as inline text in the terminal (no Enter).
Three sections in a row: SKILLS | TOOLS | META.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from workflow_app.signal_bus import signal_bus

# ─── Data ─────────────────────────────────────────────────────────────────── #

SKILLS_DATA: list[tuple[str, str, str]] = [
    ("mcp-codex",    "/skill:mcp-codex",                    "Pair programming com Codex MCP (4 níveis)"),
    ("resolve-gaps", "/skill:resolve-gaps",                  "Resolução interativa de gaps"),
    ("resume-flow",  "/skill:resume-flow",                   "Retomada inteligente após limite de contexto"),
    ("budget-al",    "/skill:budget-alignment",              "Alinhamento de orçamento"),
    ("compliance",   "/skill:compliance-traceability",       "Rastreabilidade de compliance"),
    ("ctx-anchor",   "/skill:context-anchor",                "Ancoragem de contexto pré-execução"),
    ("data-compl",   "/skill:data-compliance-context",       "Contexto LGPD/GDPR"),
    ("data-impact",  "/skill:data-impact-decision",          "Decisão de impacto em dados"),
    ("data-integ",   "/skill:data-integrity-guard",          "Guarda de integridade de dados"),
    ("deploy-res",   "/skill:deploy-resilience-planner",     "Planejamento de resiliência para deploy"),
    ("docs-cnfl",    "/skill:docs-conflict-mediator",        "Mediação de conflitos entre docs"),
    ("exec-ready",   "/skill:execution-readiness-verifier",  "Verificação de readiness"),
    ("handoff",      "/skill:handoff-alignment",             "Alinhamento de handoff"),
    ("integ-bnd",    "/skill:integration-boundary-decision", "Decisão de boundary de integração"),
    ("metric-pr",    "/skill:metric-priority-arbiter",       "Arbitragem: SLO vs deadline vs custo"),
    ("observab",     "/skill:observability-decision",        "Decisão de observabilidade"),
    ("proc-pause",   "/skill:process-pause-signal",          "Sinal de pausa em loops 2+"),
    ("qa-sev",       "/skill:qa-severity-decider",           "Classificação de severidade QA"),
    ("sec-gate",     "/skill:security-review-gate",          "Gate de revisão de segurança"),
    ("test-fail",    "/skill:test-failure-decision",         "Decisão para falhas de teste persistentes"),
    ("ux-spec",      "/skill:ux-spec-decision",              "Specs UX/UI ambíguas"),
]

TOOLS_DATA: list[tuple[str, str, str]] = [
    ("init-ctx",  "/tools:init-context",          "Carrega contexto sem modificar nada"),
    ("nuclear",   "/tools:nuclear-debug",          "Debug nuclear para bugs persistentes"),
    ("next-feat", "/tools:next-feature-research",  "Analisa gap INTAKE vs workspace"),
    ("lay-rfct",  "/tools:layout-full-refactor",   "Refatora visual do front-end"),
    ("lay-upd",   "/tools:layout-upd",             "Atualiza tema light/dark a partir de preset"),
    ("clr-wf",    "/tools:clear-workflow",         "Arquiva conteúdo atual em old/{N}/"),
    ("clr-old",   "/tools:clear-old-docs",         "Deleta pastas old/ (irreversível)"),
    ("saas-sug",  "/tools:saas-suggestion",        "6 sugestões de SaaS"),
    ("saas-crd",  "/tools:saas-to-crowd",          "Dossier SaaS → JSON de crowdfunding"),
    ("sync-tok",  "/tools:sync-showroom-tokens",   "Converte preset JSON em globals.css"),
    ("sys-sug",   "/tools:system-suggestion",      "Melhorias via pair programming com Codex"),
]

META_DATA: list[tuple[str, str, str]] = [
    ("create",       "/cmd:create",              "Cria novo comando via entrevista"),
    ("update",       "/cmd:update",              "Atualiza comando existente"),
    ("readme-upd",   "/cmd:readme-upd",          "Sincroniza README.md"),
    ("scaffolds",    "/cmd:scaffolds-upd",       "Atualiza scaffolds com código real"),
    ("find-gaps",    "/cmd:find-gaps",           "Auditoria do pipeline para gaps"),
    ("gap-to-task",  "/cmd:gap-to-task",         "GAP-ANALYSIS → tasks sequenciais"),
    ("exec-gaps",    "/cmd:execute-gap-tasks",   "Executa tasks de gaps e sincroniza"),
    ("global-mgmt",  "/cmd:global-management",   "Gestão global do fluxo SystemForge"),
    ("flow-rsch",    "/cmd:flow-research",       "Atualiza FLOW.md com os 3 fluxos"),
    ("flow-upd",     "/cmd:flow-update",         "Atualiza sugestões de próximo passo"),
    ("asq-user",     "/cmd:asq-user-question",   "Audita comandos contra boas práticas"),
]

# ─── Styles ───────────────────────────────────────────────────────────────── #

_BTN_STYLE = (
    "QPushButton { background-color: #3F3F46; color: #D4D4D8;"
    "  border: 1px solid #52525B; border-radius: 3px;"
    "  font-size: 9px; font-weight: 600; padding: 2px 4px; }"
    "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
    "QPushButton:pressed { background-color: #FBBF24; color: #18181B; border-color: #FBBF24; }"
)

_TITLE_STYLE = (
    "color: #A1A1AA; font-size: 9px; font-weight: 700;"
    " letter-spacing: 0.5px; padding: 0 4px;"
)


# ─── ToolboxHeader ────────────────────────────────────────────────────────── #

class ToolboxHeader(QWidget):
    """Compact header with Skills, Tools, and Meta buttons above the terminal."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ToolboxHeader")
        self.setStyleSheet(
            "QWidget#ToolboxHeader { background-color: #1C1C1F;"
            " border-bottom: 1px solid #3F3F46; }"
        )
        self._setup_ui()

    def _setup_ui(self) -> None:
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        main.addWidget(self._build_section("SKILLS", SKILLS_DATA, cols=7), stretch=7)
        main.addWidget(self._build_separator())
        main.addWidget(self._build_section("TOOLS", TOOLS_DATA, cols=4), stretch=4)
        main.addWidget(self._build_separator())
        main.addWidget(self._build_section("META", META_DATA, cols=4), stretch=4)

    def _build_separator(self) -> QWidget:
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #3F3F46;")
        return sep

    def _build_section(
        self, title: str, data: list[tuple[str, str, str]], *, cols: int = 7
    ) -> QWidget:
        section = QWidget()
        section.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)

        label = QLabel(title)
        label.setStyleSheet(_TITLE_STYLE)
        label.setFixedHeight(14)
        layout.addWidget(label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            " QScrollBar:vertical { background: #1C1C1F; width: 5px; border: none; }"
            " QScrollBar::handle:vertical { background: #52525B; border-radius: 2px; }"
            " QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)

        for i, (label_text, cmd, tip) in enumerate(data):
            btn = QPushButton(label_text)
            btn.setToolTip(f"{cmd} — {tip}")
            btn.setStyleSheet(_BTN_STYLE)
            btn.setFixedHeight(20)
            btn.clicked.connect(lambda _checked=False, c=cmd: signal_bus.paste_text_in_terminal.emit(c))
            grid.addWidget(btn, i // cols, i % cols)

        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        return section


# ─── ToolboxTab ───────────────────────────────────────────────────────────── #

class ToolboxTab(QWidget):
    """Full-size tab for browsing Skills, Tools, and Meta commands with descriptions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ToolboxTab")
        self.setStyleSheet("background-color: #18181B;")
        self._setup_ui()

    def _setup_ui(self) -> None:
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        main.addWidget(self._build_column("SKILLS", SKILLS_DATA, "#7C3AED"), stretch=1)
        main.addWidget(self._build_col_separator())
        main.addWidget(self._build_column("TOOLS", TOOLS_DATA, "#2563EB"), stretch=1)
        main.addWidget(self._build_col_separator())
        main.addWidget(self._build_column("META", META_DATA, "#F59E0B"), stretch=1)

    def _build_col_separator(self) -> QWidget:
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #3F3F46;")
        return sep

    def _build_column(
        self, title: str, data: list[tuple[str, str, str]], accent: str
    ) -> QWidget:
        col = QWidget()
        col.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QLabel(f"  {title}")
        header.setFixedHeight(32)
        header.setStyleSheet(
            f"background-color: #27272A; color: {accent};"
            "  font-size: 12px; font-weight: 700; letter-spacing: 1px;"
            "  border-bottom: 1px solid #3F3F46; padding: 6px 8px;"
        )
        layout.addWidget(header)

        # Scrollable list of rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: #18181B; }"
            " QScrollBar:vertical { background: #1C1C1F; width: 6px; border: none; }"
            " QScrollBar::handle:vertical { background: #52525B; border-radius: 3px; }"
            " QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        rows_layout = QVBoxLayout(container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(0)

        for label_text, cmd, tip in data:
            row = self._build_row(label_text, cmd, tip, accent)
            rows_layout.addWidget(row)

        rows_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        return col

    def _build_row(
        self, label_text: str, cmd: str, description: str, accent: str
    ) -> QWidget:
        row = QWidget()
        row.setFixedHeight(44)
        row.setStyleSheet(
            "QWidget { background-color: transparent;"
            "  border-bottom: 1px solid #3F3F46; }"
            "QWidget:hover { background-color: #27272A; }"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        # Paste button
        paste_btn = QPushButton("▸")
        paste_btn.setFixedSize(24, 24)
        paste_btn.setToolTip(f"Colar {cmd} no terminal")
        paste_btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent; border: 1px solid {accent};"
            f"  color: {accent}; border-radius: 4px; font-size: 11px; font-weight: 700; }}"
            f"QPushButton:hover {{ background-color: {accent}; color: #18181B; }}"
        )
        paste_btn.clicked.connect(
            lambda _checked=False, c=cmd: signal_bus.paste_text_in_terminal.emit(c)
        )
        layout.addWidget(paste_btn)

        # Info column
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(1)

        name_label = QLabel(cmd)
        name_label.setStyleSheet(
            "color: #FAFAFA; font-family: monospace; font-size: 12px;"
            " border: none;"
        )
        info.addWidget(name_label)

        desc_label = QLabel(description)
        desc_label.setStyleSheet(
            "color: #71717A; font-size: 10px; border: none;"
        )
        info.addWidget(desc_label)

        layout.addLayout(info, stretch=1)

        return row
