"""
MainWindow — Workflow App shell (module-01/TASK-3 + module-14/TASK-4).

Layout:
  ┌─────────────────────────────────────────────────────────────┐
  │ MetricsBar (48px)                                           │
  │ ConfigBar (48px)  [⬡ project]  [Workflow][Comandos]         │
  ├─────────────────────────────────────────────────────────────┤
  │ ViewStack (QStackedWidget):                                 │
  │   Page 0 — Workflow:                                        │
  │     QSplitter: CommandQueueWidget(280px) | LeftTabWidget    │
  │       Tab 0: (toolbox header removido) + OutputPanel        │
  │       Tab 1: History (FilterPanel + list + detail)          │
  │   Page 1 — Comandos:                                        │
  │     TemplateBuilderWidget (full width)                      │
  │   Page 2 — Kanban:                                          │
  │     KanbanView (full width)                                 │
  │   Page 3 — Module Detail:                                   │
  │     ModuleDetailView (full width)                           │
  └─────────────────────────────────────────────────────────────┘

Window: resize(1280, 720), setMinimumSize(1024, 600)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from workflow_app.command_queue.add_command_dialog import AddCommandDialog
from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.config.app_state import app_state
from workflow_app.config.config_bar import ConfigBar
from workflow_app.config.config_parser import detect_config, parse_config
from workflow_app.domain import CommandSpec
from workflow_app.errors import ConfigError
from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.output_panel.output_panel import OutputPanel
from workflow_app.services.delivery_reader import DeliveryReader
from workflow_app.services.lock_service import LockService
from workflow_app.signal_bus import signal_bus
from workflow_app.template_builder.template_builder_widget import TemplateBuilderWidget
from workflow_app.views.kanban import KanbanView
from workflow_app.views.module_detail import ModuleDetailView
from workflow_app.widgets.execution_detail_panel import ExecutionDetailPanel
from workflow_app.widgets.execution_history_widget import ExecutionHistoryWidget
from workflow_app.widgets.filter_panel import FilterPanel
from workflow_app.widgets.toast_notifier import ToastNotifier
from workflow_app.widgets.version_update_banner import VersionUpdateBanner

logger = logging.getLogger(__name__)

# ── Directory shortcuts for the Workspace terminal label bar ─────────────── #
# main_window.py lives at: .../systemForge/ai-forge/workflow-app/src/workflow_app/
_WORKFLOW_APP_DIR = str(Path(__file__).resolve().parents[2])  # .../ai-forge/workflow-app
_SYSTEMFORGE_DIR  = str(Path(__file__).resolve().parents[4])  # .../systemForge

# Task 7 (loop 05-13-workflow-app-layout-2): prompt longo literal embutido,
# preservado byte-a-byte (sha256 d70879ea1e07618ae5ad26f024558c232dde70e5f587c5f8416a3064ab90787e)
# das linhas 97-319 de blacksmith/loop-archives/05-13-workflow-app-layout-2/source.md.
# Tratado como literal — nao parsear, nao interpolar, nao executar.
PROGRESS_PROMPT = """\
Sistema de Execucao Adversarial com Double-MCP + Codex Review
Objetivo
Analise profundamente o problema informado utilizando /skill:double-mcp, defina a melhor solucao tecnica, proponha uma arquitetura adequada e gere uma sequencia de tasks tecnicas executaveis.
Apos gerar as tasks:
Execute-as sequencialmente.
Faca revisao adversarial obrigatoria via /skill:mcp-codex em cada task.
Faca uma revisao holistica final do conjunto completo.
Mantenha rastreabilidade continua em PROGRESS.md.

FASE 1 — DISCUSSAO E PLANEJAMENTO
1. Debate tecnico inicial
Utilize /skill:double-mcp para:
Identificar a causa raiz do problema.
Debater alternativas de solucao.
Avaliar tradeoffs tecnicos.
Identificar riscos arquiteturais.
Definir a solucao mais robusta e sustentavel.
Definir arquitetura final da implementacao.
O debate deve produzir:
Diagnostico do problema.
Estrategia escolhida.
Arquitetura proposta.
Dependencias afetadas.
Riscos conhecidos.
Criterios de aceite globais.

2. Geracao das tasks
Com base na arquitetura definida:
Crie uma lista de tasks:
Sequenciais.
Atomicas.
Executaveis.
Testaveis.
Sem sobreposicao.
Ordenadas logicamente.
Com criterios de aceite explicitos.
Cada task deve conter:
Objetivo.
Escopo.
Criterios de aceite.
Arquivos potencialmente afetados.
Dependencias de outras tasks.
IMPORTANTE:
Nao criar tasks vagas.
Nao criar tasks excessivamente grandes.
Nao misturar refactor amplo com correcao funcional.
Nao introduzir escopo novo sem justificativa explicita.

3. Revisao previa das tasks
Antes de executar qualquer task:
Utilize /skill:mcp-codex para revisar toda a lista de tasks em modo adversarial.
O review deve validar:
Ordem logica.
Cobertura completa do problema.
Ausencia de gaps.
Ausencia de redundancias.
Riscos de regressao.
Clareza dos criterios de aceite.
Coerencia arquitetural.
Somente apos aprovacao iniciar execucao.

FASE 2 — SETUP OBRIGATORIO
1. Criar PROGRESS.md
Criar PROGRESS.md na raiz do projeto contendo:
Cabecalho
Objetivo.
Data.
Escopo.
Fonte/origem das tasks.
Arquitetura definida.
Regras operacionais.

Tabela de rastreabilidade
#
Task
Status
Codex Verdict
Evidencia
Notas

Status validos:
pending
in-progress
review
done
blocked
Inicialmente:
Todas as tasks devem comecar como pending.

2. Regras de integridade
Nao e permitido:
Reordenar tasks arbitrariamente.
Criar tasks extras sem justificativa.
Alterar escopo silenciosamente.
Pular revisao adversarial.
Toda mudanca estrutural deve ser registrada em Notas.

FASE 3 — LOOP OPERACIONAL POR TASK
Para cada task k = 1..N:

Etapa 1 — Inicio
Atualizar imediatamente o PROGRESS.md:
Status -> in-progress

Etapa 2 — Implementacao
Implementar a task:
Da forma mais minima possivel.
Sem refactors fora do escopo.
Sem mudancas especulativas.
Sem antecipar tasks futuras.
Priorizar:
Clareza.
Determinismo.
Isolamento.
Baixo risco de regressao.

Etapa 3 — Review adversarial obrigatorio
Atualizar status:
review
Invocar /skill:mcp-codex em modo adversarial review passando:
Descricao completa da task.
Criterios de aceite.
Diff gerado.
Arquivos alterados.
Contexto arquitetural relevante.
O review deve validar:
Se a implementacao realmente resolve a task.
Se houve regressao.
Se existe codigo orfao.
Se existem estados indefinidos.
Se ha inconsistencias arquiteturais.
Se o codigo segue CLAUDE.md.

Etapa 4 — Interpretacao do veredito
Se APROVADO
Marcar task como done.
Registrar:
Veredito.
Evidencias.
Arquivos alterados.
Paths relevantes.
Linhas-chave.
Observacoes relevantes.

Se RESSALVAS
Corrigir problemas.
Reexecutar /skill:mcp-codex.
Maximo de 3 rodadas.
Se exceder 3 rodadas:
Marcar como blocked.
Registrar motivo detalhado.
Continuar somente se o bloqueio nao inviabilizar tasks dependentes.

Se REPROVADO
Corrigir obrigatoriamente antes de avancar.
Reexecutar review.
Maximo de 3 rodadas.
Persistindo falha:
Marcar blocked.
Registrar justificativa tecnica completa.
Solicitar intervencao do usuario se necessario.

Etapa 5 — Gate obrigatorio
Nunca avancar para k+1 enquanto k nao estiver:
done
OU
blocked com justificativa explicita registrada.

FASE 4 — REVISAO HOLISTICA FINAL
Apos todas as tasks:
Executar /skill:mcp-codex novamente em modo adversarial holistico.
O review final deve validar:
Cobertura
Alguma task original ficou parcialmente implementada?
Alguma implementacao ficou incompleta?
Coerencia
Contradicoes entre tasks.
Regressoes.
Codigo morto.
Codigo orfao.
Duplicacoes.
Integracao
Compatibilidade entre mudancas.
Fluxos quebrados.
Acoplamentos perigosos.
Gaps entre tasks.
Qualidade transversal
Validar regras invioalveis do projeto:
Zero Orfaos
Zero Silencio
Zero Estados Indefinidos
ECU
Demais regras descritas em CLAUDE.md

FASE 5 — REGISTRO FINAL
Adicionar ao PROGRESS.md:
Revisao Final
Conteudo obrigatorio:
Veredito final.
Gaps encontrados.
Correcoes aplicadas.
Riscos remanescentes.
Limitacoes conhecidas.
Observacoes arquiteturais.
Estado final do sistema.

REGRAS GERAIS (INVIOLAVEIS)
Atualizar PROGRESS.md imediatamente apos cada transicao de status.
Nunca atualizar status em batch.
Nunca pular o gate do /skill:mcp-codex.
Nunca ocultar falhas.
Nunca assumir comportamento implicito sem validacao.
Em caso de bloqueio critico insoluvel:
Parar.
Explicar claramente.
Solicitar direcionamento do usuario.

RELATORIO FINAL OBRIGATORIO
Ao final da execucao, reportar:
Quantidade de tasks done
Quantidade de tasks blocked
Resumo executivo da implementacao
Principais riscos remanescentes
"""


class MainWindow(QMainWindow):
    """Main application window."""

    _SETTINGS_GEOMETRY = "MainWindow/geometry"
    _SETTINGS_SPLITTER = "MainWindow/splitterSizes"
    _SETTINGS_LAST_CONFIG = "Project/lastConfigPath"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SystemForge Desktop")
        self.setMinimumSize(640, 480)
        self.resize(1280, 720)
        self.setObjectName("MainWindow")

        # Pipeline execution state (RF03)
        self._pipeline_manager = None
        self._testid_overlays: list = []
        self._datatest_active = False
        # Task 3 (loop 05-13-workflow-app-layout-2): modo do test-mode column.
        # "off" preserva o default original (overlay desligado na inicializacao).
        self._datatest_mode = "off"

        self._settings = QSettings("SystemForge", "WorkflowApp")
        self._setup_ui()
        self._setup_shortcuts()
        self._connect_signals()
        self._restore_state()
        self._attempt_startup_detection()
        # Modo Remoto removido 2026-05-12 — RemoteServer nao e mais
        # instanciado; signais remote_* permanecem definidos mas sem produtor.

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        central = QWidget()
        central.setObjectName("CentralWidget")
        central.setStyleSheet("background-color: #18181B;")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # VersionUpdateBanner (hidden by default, shown when templates are outdated)
        self._version_banner = VersionUpdateBanner(parent=central)
        self._version_banner.update_requested.connect(self._on_version_update_requested)
        root_layout.addWidget(self._version_banner)

        # MetricsBar — hidden; owns state machine (dots, timers, signals).
        # Visible children are reparented out before hide() is called.
        self._metrics_bar = MetricsBar(parent=self)
        root_layout.addWidget(self._metrics_bar)

        # ConfigBar (hidden — project selector moved into MetricsBar)
        self._config_bar = ConfigBar(parent=self)
        self._config_bar.hide()
        self._metrics_bar.config_change_requested.connect(self._on_config_change_requested)
        self._metrics_bar.config_unload_requested.connect(self._unload_config)

        # ── ViewStack: 3 pages switched by ConfigBar nav buttons ─────── #
        self._view_stack = QStackedWidget()
        self._view_stack.setObjectName("ViewStack")

        # ── Page 0: Workflow (splitter: CommandQueue + LeftTabWidget) ── #
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("MainSplitter")
        self._splitter.setHandleWidth(5)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3F3F46; }"
            "QSplitter::handle:hover { background-color: #FBBF24; }"
        )

        self._command_queue = CommandQueueWidget(parent=self)
        self._command_queue.setProperty("testid", "main-command-queue")

        # Pill row — project pill + selectors as first div inside command queue.
        # Widgets are reparented from MetricsBar (state machine stays in MetricsBar).
        _pill_row = QWidget()
        _pill_row.setObjectName("CommandQueuePillRow")
        _pill_row.setProperty("testid", "main-command-queue-pill-row")
        _pill_row_layout = QHBoxLayout(_pill_row)
        # Task 1 (loop 05-13-workflow-app-layout-2): margin-top 10 no container que envolve metrics-project-pill.
        _pill_row_layout.setContentsMargins(8, 10, 8, 6)
        _pill_row_layout.setSpacing(5)
        for _w in (
            self._metrics_bar._project_pill,
            self._metrics_bar._feature_name_input,
            self._metrics_bar._proj_open_btn,
            self._metrics_bar._proj_select_btn,
            self._metrics_bar._loop_select_btn,
        ):
            _pill_row_layout.addWidget(_w)
        # Park hidden nav buttons here so MetricsBar is fully decoupled
        for _btn in (self._metrics_bar._btn_workflow, self._metrics_bar._btn_comandos):
            _pill_row_layout.addWidget(_btn)
            _btn.hide()
        _pill_row_layout.addStretch(1)
        self._command_queue.layout().insertWidget(0, _pill_row)

        # Window label — etiqueta livre para identificar visualmente esta
        # janela quando varias instancias do workflow-app rodam em paralelo.
        # Click + digite. Texto verde, fonte 35, sem persistencia.
        self._window_label = QLineEdit()
        self._window_label.setObjectName("WindowLabelInput")
        self._window_label.setProperty("testid", "main-window-label")
        self._window_label.setPlaceholderText("/")
        self._window_label.setStyleSheet(
            "QLineEdit {"
            " color: #22C55E;"
            " background-color: transparent;"
            " border: none;"
            " font-size: 35px;"
            " font-weight: 600;"
            " padding: 4px 8px;"
            "}"
        )
        self._command_queue.layout().insertWidget(0, self._window_label)

        # MetricsBar no longer has visible children — hide it.
        self._metrics_bar.hide()

        # Output container (refactor 2026-05-12): QTabWidget e a aba
        # "Historico" foram removidos; signal_bus.history_panel_toggled
        # virou no-op via _switch_to_history_tab e _build_history_panel
        # nao e mais invocado em runtime.
        output_container = QWidget()
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(5)
        # ToolboxHeader removido em 2026-05-12 — substituido pelos quick btns
        # da play bar do CommandQueueWidget (ver AC-1.1 do TASK-1 layout refactor).

        # OutputToolbar (refactor 2026-05-12): faixa unica acima do
        # terminal_splitter. listeners-frame (reparenteado do MetricsBar)
        # na esquerda + os 2 botoes de controle dos terminais (alternar
        # layout + colapsar workspace) na direita. Os botoes
        # JSON/WS/mcp-*/asq-user foram migrados para a 4a div do
        # MetricsBar via _populate_header_actions().
        self._terminal_is_vertical = False
        self._workspace_collapsed = False

        # Row: [queue-header (left)] [actions+controls (center)] [listeners (right)] [test-mode (4o, width=conteudo)]
        _toolbar_bar, _toolbar_center, _toolbar_left_top = self._build_output_toolbar()
        _toolbar_row = QWidget()
        _toolbar_row_layout = QHBoxLayout(_toolbar_row)
        _toolbar_row_layout.setContentsMargins(0, 10, 0, 0)
        _toolbar_row_layout.setSpacing(10)

        # Refactor 2026-05-14 layout-3: coluna esquerda passa a ser um container
        # vertical com left_top (testid output-toolbar-left-top) acima do
        # CommandQueue header_widget (testid output-toolbar-left). A altura
        # total da coluna acompanha output-toolbar-right (134); header_widget
        # absorve o que sobra apos left_top, equivalente ao output-toolbar-center.
        from PySide6.QtWidgets import QVBoxLayout as _LeftVBox
        _toolbar_left_container = QWidget()
        _toolbar_left_layout = _LeftVBox(_toolbar_left_container)
        _toolbar_left_layout.setContentsMargins(0, 0, 0, 0)
        _toolbar_left_layout.setSpacing(0)
        _toolbar_left_layout.addWidget(_toolbar_left_top)
        _toolbar_left_layout.addWidget(self._command_queue.header_widget, stretch=1)

        _toolbar_row_layout.addWidget(_toolbar_left_container, stretch=1)            # left
        _toolbar_row_layout.addWidget(_toolbar_center, stretch=1)                    # center
        _toolbar_row_layout.addWidget(_toolbar_bar, stretch=1)                       # right
        # Task 3 (loop 05-13-workflow-app-layout-2): 4o sibling com width=conteudo (stretch=0)
        _test_mode_column = self._build_test_mode_column()
        _toolbar_row_layout.addWidget(_test_mode_column)                             # test-mode
        output_layout.addWidget(_toolbar_row)

        # Dual terminal: splitter with interactive (top/left) + workspace (bottom/right)
        self._terminal_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._terminal_splitter.setHandleWidth(4)
        self._terminal_splitter.setChildrenCollapsible(False)
        self._terminal_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3F3F46; }"
            "QSplitter::handle:hover { background-color: #FBBF24; }"
        )

        from PySide6.QtWidgets import QLabel

        # Top/Left: Interactive terminal (user types here)
        self._interactive_wrapper = QWidget()
        interactive_layout = QVBoxLayout(self._interactive_wrapper)
        interactive_layout.setContentsMargins(0, 0, 0, 0)
        interactive_layout.setSpacing(0)
        interactive_label = QLabel(" INTERACTIVE")
        interactive_label.setFixedHeight(20)
        interactive_label.setStyleSheet(
            "QLabel { background-color: #1A2E05; color: #84CC16;"
            "  font-size: 10px; font-weight: 700; padding-left: 6px; }"
        )
        interactive_layout.addWidget(interactive_label)
        self._output_panel = OutputPanel(parent=self._interactive_wrapper)
        self._output_panel.setProperty("testid", "terminal-interactive")
        interactive_layout.addWidget(self._output_panel, stretch=1)
        interactive_layout.addWidget(
            self._build_terminal_notes_footer("terminal-interactive-notes")
        )
        self._terminal_splitter.addWidget(self._interactive_wrapper)

        # Bottom/Right: Workspace terminal (Kimi / paste target for blue ▶)
        self._workspace_wrapper = QWidget()
        workspace_layout = QVBoxLayout(self._workspace_wrapper)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._build_workspace_label_bar())
        self._workspace_panel = OutputPanel(parent=self._workspace_wrapper, workspace_mode=True)
        self._workspace_panel.setProperty("testid", "terminal-workspace")
        workspace_layout.addWidget(self._workspace_panel, stretch=1)
        workspace_layout.addWidget(
            self._build_terminal_notes_footer("terminal-workspace-notes")
        )
        self._terminal_splitter.addWidget(self._workspace_wrapper)

        self._terminal_splitter.setSizes([350, 350])
        output_layout.addWidget(self._terminal_splitter, stretch=1)

        self._splitter.addWidget(self._command_queue)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.addWidget(output_container)
        self._splitter.setStretchFactor(1, 2)

        self._view_stack.addWidget(self._splitter)  # index 0

        # ── Page 1: Comandos (TemplateBuilderWidget, full width) ──────── #
        self._template_builder = TemplateBuilderWidget(parent=self)
        self._template_builder.setProperty("testid", "page-comandos")
        self._view_stack.addWidget(self._template_builder)  # index 1

        # ── Cooperative lock service (T-037) ─────────────────────────── #
        # Instantiated BEFORE the per-module detail view so it can be
        # injected as a constructor arg. API-only for now: no acquire on
        # startup. T-038 drives try_acquire/release from the detail view.
        self._lock_service = LockService(parent=self)
        self._lock_service.lock_lost.connect(self._on_lock_lost)

        # Shared DeliveryReader used by both Kanban and ModuleDetailView.
        self._kanban_reader = DeliveryReader()

        # ── Page 2: Kanban (9 colunas por estado DCP, T-036) ──────────── #
        self._kanban_view = KanbanView(reader=self._kanban_reader, parent=self)
        self._kanban_view.setProperty("testid", "page-kanban")
        self._kanban_view.module_clicked.connect(self._on_kanban_module_clicked)
        self._view_stack.addWidget(self._kanban_view)  # index 2

        # ── Page 3: Module Detail (per-modulo view, T-038) ───────────── #
        self._module_detail_view = ModuleDetailView(
            reader=self._kanban_reader,
            lock_service=self._lock_service,
            parent=self,
        )
        self._module_detail_view.setProperty("testid", "page-module-detail")
        self._module_detail_view.back_requested.connect(
            lambda: self._view_stack.setCurrentIndex(2)
        )
        self._view_stack.addWidget(self._module_detail_view)  # index 3

        root_layout.addWidget(self._view_stack, stretch=1)

        # Toast notification (floating, stacked, level-dependent duration)
        self._toast_notifier = ToastNotifier(central)

    def _build_output_toolbar(self) -> tuple[QWidget, QWidget, QWidget]:
        """Single horizontal toolbar acima do dual-terminal splitter.

        Left side: reparenteia `MetricsBar._listeners_frame` (testid=
        listeners-frame), preservando ownership pelo MetricsBar para que a
        state machine continue alimentando os dots e o queue-progress-ring
        via signal_bus.

        Right side: container vertical com duas linhas. Linha de cima:
        os 6 botoes de acao rapida (JSON, WS, mcp-codex, mcp-kimi,
        double-mcp, asq-user) populados via `_populate_header_actions()`.
        Linha de baixo: alternador de layout (vertical/horizontal) e
        chevron de colapso do terminal-workspace.
        """
        from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

        bar = QWidget()
        bar.setObjectName("OutputToolbar")
        bar.setProperty("testid", "output-toolbar-right")
        # Task 1 (loop 05-13-workflow-app-layout-2): +10 para acomodar margin-top dos containers internos.
        bar.setFixedHeight(134)
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setStyleSheet(
            "QWidget#OutputToolbar { background-color: #1C1C1F;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        lay = QHBoxLayout(bar)
        # Task 1 (loop 05-13-workflow-app-layout-2): margin-top 10 no container output-toolbar-right.
        lay.setContentsMargins(8, 18, 8, 8)
        lay.setSpacing(8)

        # Left — reparent listeners-frame (owned by MetricsBar). Qt reparents
        # automatically when addWidget() is called on a different layout.
        lay.addWidget(self._metrics_bar._listeners_frame)
        lay.addStretch(1)

        # Refactor 2026-05-14 layout-3: output-toolbar-center-top movido para
        # output-toolbar-left-top (coluna esquerda). output-toolbar-center-bottom
        # renomeado para output-toolbar-center e ocupa toda a altura do row.
        # right_container = wrapper da coluna CENTER (mantido como retorno
        # para preservar a assinatura consumida por _setup_ui).
        right_container = QWidget()
        right_container.setObjectName("OutputToolbarRight")
        right_col = QVBoxLayout(right_container)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(0)

        # left_top: reparenteia instance-group para a coluna esquerda.
        # Posicionado pelo _setup_ui acima de output-toolbar-left.
        left_top = QWidget()
        left_top.setObjectName("OutputToolbarLeftTop")
        left_top.setProperty("testid", "output-toolbar-left-top")
        left_top.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        left_top.setStyleSheet(
            "QWidget#OutputToolbarLeftTop { border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        left_top_layout = QVBoxLayout(left_top)
        left_top_layout.setContentsMargins(6, 6, 6, 6)
        left_top_layout.setSpacing(0)
        left_top_layout.addWidget(self._metrics_bar._instance_group)

        center_bottom = QWidget()
        center_bottom.setObjectName("OutputToolbarCenter")
        center_bottom.setProperty("testid", "output-toolbar-center")
        center_bottom.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        center_bottom.setStyleSheet(
            "QWidget#OutputToolbarCenter { border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        center_bottom_layout = QVBoxLayout(center_bottom)
        center_bottom_layout.setContentsMargins(6, 6, 6, 6)
        center_bottom_layout.setSpacing(6)

        actions_row = QWidget()
        actions_row.setProperty("testid", "output-toolbar-actions-row")
        actions_layout = QHBoxLayout(actions_row)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)

        controls_row = QWidget()
        controls_row.setProperty("testid", "output-toolbar-controls-row")
        controls_layout = QHBoxLayout(controls_row)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        controls_layout.addStretch(1)

        # Refactor 2026-05-14 layout-3: nova fileira entre controls_row e
        # actions_row com botoes que publicam os principais testids para o
        # terminal (roteamento T1/T2 via terminal-route-toggles).
        datatest_row = QWidget()
        datatest_row.setProperty("testid", "output-toolbar-datatest-row")
        datatest_layout = QHBoxLayout(datatest_row)
        datatest_layout.setContentsMargins(0, 0, 0, 0)
        datatest_layout.setSpacing(6)

        # Task 6 (loop 05-13-workflow-app-layout-2): div T1/T2 ocupa o lugar
        # fisico liberado pela Task 5. Roteamento ESTRITO: aplica-se apenas
        # aos botoes das rows output-toolbar-actions-row e
        # output-toolbar-controls-row via self._publish_to_terminal(). Estilo
        # espelha queue-div-use-kimi (background, border, radius, indicator).
        _TERMINAL_ROUTE_CHK_STYLE = (
            "QCheckBox { color: #FAFAFA; font-size: 11px; font-weight: 600;"
            "  background: transparent; border: none; padding: 0; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
            "QCheckBox::indicator:unchecked { background-color: #3F3F46;"
            "  border: 1px solid #52525B; border-radius: 3px; }"
            "QCheckBox::indicator:checked { background-color: #3B82F6;"
            "  border: 1px solid #3B82F6; border-radius: 3px; }"
            "QCheckBox::indicator:hover { border-color: #93C5FD; }"
        )
        self._chk_route_t1 = QCheckBox("T1")
        self._chk_route_t1.setProperty("testid", "terminal-route-t1")
        self._chk_route_t1.setChecked(True)
        self._chk_route_t1.setToolTip(
            "T1: publicar em terminal-interactive-output.\n"
            "T1+T2 publica em ambos. Nenhum = no-op silencioso."
        )
        self._chk_route_t1.setStyleSheet(_TERMINAL_ROUTE_CHK_STYLE)

        self._chk_route_t2 = QCheckBox("T2")
        self._chk_route_t2.setProperty("testid", "terminal-route-t2")
        self._chk_route_t2.setChecked(False)
        self._chk_route_t2.setToolTip(
            "T2: publicar em terminal-workspace-output.\n"
            "T1+T2 publica em ambos. Nenhum = no-op silencioso."
        )
        self._chk_route_t2.setStyleSheet(_TERMINAL_ROUTE_CHK_STYLE)

        _terminal_route_box = QWidget()
        _terminal_route_box.setProperty("testid", "terminal-route-toggles")
        _terminal_route_box.setFixedHeight(32)
        _terminal_route_box.setStyleSheet(
            "QWidget { background-color: #1C1C1F; border: 1px solid #3F3F46;"
            "  border-radius: 5px; }"
        )
        _trbl = QHBoxLayout(_terminal_route_box)
        _trbl.setContentsMargins(10, 0, 10, 0)
        _trbl.setSpacing(8)
        _trbl.addWidget(self._chk_route_t1)
        _trbl.addWidget(self._chk_route_t2)
        controls_layout.addWidget(_terminal_route_box)

        _TOGGLE_BTN_STYLE = (
            "QPushButton { background-color: #27272A; color: #D4D4D8;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  font-size: 15px; padding: 2px 0; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FAFAFA;"
            "  border-color: #71717A; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B;"
            "  border-color: #FBBF24; }"
        )

        # Task 5 (loop 05-13-workflow-app-layout-2): toggles movidos de
        # controls_row (output-toolbar-center) para queue_count_toggles_row
        # (output-toolbar-right, abaixo de queue-count-label). Largura
        # reduzida 44->42 para que 42 + 4 (spacing) + 42 = 88 = largura
        # de queue-count-label. O espaco vacado em controls_row sera
        # consumido pela Task 6 (checkbox T1/T2).
        from PySide6.QtCore import QSize as _QSize
        self._layout_icon_stacked = QIcon(
            str(Path(_WORKFLOW_APP_DIR) / "assets" / "layout-stacked.svg")
        )
        self._layout_icon_side = QIcon(
            str(Path(_WORKFLOW_APP_DIR) / "assets" / "layout-side-by-side.svg")
        )
        self._layout_toggle_btn = QPushButton()
        self._layout_toggle_btn.setProperty("testid", "terminal-layout-toggle")
        self._layout_toggle_btn.setToolTip("Layout: lado a lado. Clique para empilhar")
        self._layout_toggle_btn.setFixedSize(42, 34)
        self._layout_toggle_btn.setIconSize(_QSize(22, 22))
        # Estado inicial: lado a lado -> clique vai empilhar -> mostra icone "stacked".
        self._layout_toggle_btn.setIcon(self._layout_icon_stacked)
        self._layout_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._layout_toggle_btn.setStyleSheet(_TOGGLE_BTN_STYLE)
        self._layout_toggle_btn.clicked.connect(self._toggle_terminal_layout)
        self._metrics_bar._queue_count_toggles_layout.addWidget(
            self._layout_toggle_btn
        )

        self._collapse_chevron = QPushButton("\u25BC")
        self._collapse_chevron.setProperty("testid", "terminal-workspace-collapse")
        self._collapse_chevron.setToolTip("Colapsar terminal Workspace")
        self._collapse_chevron.setFixedSize(42, 34)
        self._collapse_chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_chevron.setStyleSheet(
            "QPushButton { background-color: #27272A; color: #C4B5FD;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  font-size: 15px; padding: 2px 0; }"
            "QPushButton:hover { background-color: #3F3F46; color: #E9DDFF;"
            "  border-color: #71717A; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B;"
            "  border-color: #FBBF24; }"
        )
        self._collapse_chevron.clicked.connect(self._toggle_workspace_collapse)
        self._metrics_bar._queue_count_toggles_layout.addWidget(
            self._collapse_chevron
        )
        # Task 3 (loop 05-13-workflow-app-layout-2): _btn_datatest movido para a nova
        # coluna `output-toolbar-test-mode` (4o sibling de _toolbar_row).

        # Refactor 2026-05-14 layout-3: 3 fileiras dentro de output-toolbar-center
        # (controls_row, datatest_row, actions_row, nesta ordem).
        center_bottom_layout.addWidget(controls_row)
        center_bottom_layout.addWidget(datatest_row)
        center_bottom_layout.addWidget(actions_row)

        right_col.addWidget(center_bottom)
        # right_container NOT added to bar — returned separately so _setup_ui
        # can place it as a sibling (center) in _toolbar_row.

        self._populate_header_actions(
            target=actions_layout,
            controls_left_target=controls_layout,
            datatest_row_target=datatest_layout,
        )

        return bar, right_container, left_top

    # Task 3 (loop 05-13-workflow-app-layout-2): nova coluna test-mode com toggle radio-like.
    _TEST_MODE_BTN_STYLE = (
        "QPushButton { background-color: transparent; color: #A1A1AA;"
        "  border: 1px solid #52525B; border-radius: 6px;"
        "  font-size: 11px; font-weight: 600; padding: 0 6px; }"
        "QPushButton:hover { color: #FAFAFA; background-color: #3F3F46;"
        "  border-color: #71717A; }"
        "QPushButton:checked { background-color: #DC2626; color: #FAFAFA;"
        "  border-color: #DC2626; font-weight: 700; }"
    )
    _TEST_MODE_BTN_STYLE_BODY = (
        "QPushButton { background-color: transparent; color: #60A5FA;"
        "  border: 1px solid #2563EB; border-radius: 6px;"
        "  font-size: 11px; font-weight: 600; padding: 0 6px; }"
        "QPushButton:hover { color: #FAFAFA; background-color: #1E3A8A;"
        "  border-color: #3B82F6; }"
        "QPushButton:checked { background-color: #2563EB; color: #FAFAFA;"
        "  border-color: #2563EB; font-weight: 700; }"
    )
    _TEST_MODE_BTN_STYLE_BTN = (
        "QPushButton { background-color: transparent; color: #FACC15;"
        "  border: 1px solid #EAB308; border-radius: 6px;"
        "  font-size: 11px; font-weight: 600; padding: 0 6px; }"
        "QPushButton:hover { color: #18181B; background-color: #CA8A04;"
        "  border-color: #FACC15; }"
        "QPushButton:checked { background-color: #EAB308; color: #18181B;"
        "  border-color: #EAB308; font-weight: 700; }"
    )

    def _build_test_mode_column(self) -> QWidget:
        """4a div irma de _toolbar_row com 3 botoes test-mode (DataTest/BodyTest/BtnTest).

        Comportamento radio-like via QButtonGroup.ExclusionPolicy.ExclusiveOptional:
        zero ou um botao checado. Click no checado desliga (-> modo "off"). Click em
        outro reseta o anterior automaticamente (Qt). Estado inicial: nenhum checado
        (preserva default original do `_btn_datatest`).
        """
        from PySide6.QtWidgets import (
            QHBoxLayout,  # noqa: F401 — referenced only in _build_output_toolbar
            QVBoxLayout,
            QButtonGroup,
        )

        column = QWidget()
        column.setObjectName("OutputToolbarTestMode")
        column.setProperty("testid", "output-toolbar-test-mode")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setStyleSheet(
            "QWidget#OutputToolbarTestMode { background-color: #1C1C1F;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(6, 16, 6, 6)
        col_layout.setSpacing(6)

        # DataTest: reusa o botao ja criado pelo MetricsBar. Reparent automatico
        # ao adicionar em outro layout.
        btn_data = self._metrics_bar._btn_datatest
        # BodyTest e BtnTest: mesmo perfil do DataTest (size, checkable); cores distintas.
        from PySide6.QtWidgets import QPushButton

        btn_body = QPushButton("BodyTest")
        btn_body.setFixedSize(68, 32)
        btn_body.setCheckable(True)
        btn_body.setToolTip("Exibir testids EXCETO em botoes")
        btn_body.setStyleSheet(self._TEST_MODE_BTN_STYLE_BODY)
        btn_body.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_btn = QPushButton("BtnTest")
        btn_btn.setFixedSize(68, 32)
        btn_btn.setCheckable(True)
        btn_btn.setToolTip("Exibir testids APENAS em botoes")
        btn_btn.setStyleSheet(self._TEST_MODE_BTN_STYLE_BTN)
        btn_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        col_layout.addWidget(btn_data)
        col_layout.addWidget(btn_body)
        col_layout.addWidget(btn_btn)
        col_layout.addStretch(1)

        # Toggle radio-like: zero ou um selecionado. PySide6 6.7 nao expoe
        # `setExclusionPolicy`, entao usamos `exclusive=False` + logica manual
        # no handler para desligar os outros dois quando um eh ativado.
        # Re-click no botao ativo o desliga (comportamento padrao de checkable=True
        # com exclusive=False).
        self._test_mode_group = QButtonGroup(self)
        self._test_mode_group.setExclusive(False)
        self._test_mode_group.addButton(btn_data)
        self._test_mode_group.addButton(btn_body)
        self._test_mode_group.addButton(btn_btn)

        # Estado inicial: nenhum checado (preserva default `DataTest off` original).
        self._test_mode_buttons = {
            "all": btn_data,
            "body": btn_body,
            "buttons": btn_btn,
        }
        # Flag reentrancia para evitar loop em setChecked(False) cascata.
        self._test_mode_syncing = False
        for b in self._test_mode_buttons.values():
            b.toggled.connect(self._on_test_mode_button_toggled)

        return column

    def _on_test_mode_button_toggled(self, checked: bool) -> None:
        """Resolve o modo ativo, mantem exclusividade manual (no max 1 checado)
        e emite `datatest_mode_changed`.

        Comportamento radio-like:
        - Ativar um botao desliga os outros dois.
        - Re-click no checado desliga (modo "off").
        """
        if self._test_mode_syncing:
            return
        sender = self.sender()
        self._test_mode_syncing = True
        try:
            if checked:
                # Desligar os outros dois.
                for btn in self._test_mode_buttons.values():
                    if btn is not sender and btn.isChecked():
                        btn.setChecked(False)
        finally:
            self._test_mode_syncing = False

        mode = "off"
        for key, btn in self._test_mode_buttons.items():
            if btn.isChecked():
                mode = key
                break
        signal_bus.datatest_mode_changed.emit(mode)

    def _publish_to_terminal(self, text: str) -> None:
        """Task 6 (loop 05-13-workflow-app-layout-2): roteia `text` para
        terminal(es) conforme estado dos checkboxes T1/T2.

        Escopo ESTRITO: chamada exclusivamente pelos handlers dos botoes das
        rows output-toolbar-actions-row e output-toolbar-controls-row. Demais
        emissores de paste_text_in_terminal / paste_text_in_workspace_terminal
        permanecem intactos.

        Matriz 4 estados (Zero Estados Indefinidos: nenhum cai em no-op
        explicito, nao em silencio acidental):
        - T1 only: paste em terminal-interactive-output + focus interactive.
        - T2 only: paste em terminal-workspace-output + focus workspace.
        - T1 + T2: paste em ambos + focus interactive (preferencia padrao).
        - Nenhum: retorno silencioso sem traceback.
        """
        t1 = bool(self._chk_route_t1.isChecked()) if hasattr(self, "_chk_route_t1") else True
        t2 = bool(self._chk_route_t2.isChecked()) if hasattr(self, "_chk_route_t2") else False
        if not t1 and not t2:
            return
        if t1:
            signal_bus.paste_text_in_terminal.emit(text)
        if t2:
            signal_bus.paste_text_in_workspace_terminal.emit(text)
        if t1:
            signal_bus.focus_interactive_terminal.emit()
        elif t2:
            try:
                self._workspace_panel._terminal.setFocus()
            except AttributeError:
                pass

    def _populate_header_actions(self, target=None, controls_left_target=None, datatest_row_target=None) -> None:
        """Add JSON/WS/mcp-codex/mcp-kimi/double-mcp/asq-user buttons.

        Quando `target` (QHBoxLayout) e fornecido, popula nesse layout —
        usado pelo `_build_output_toolbar` para colocar os botoes na
        linha superior do container direito (acima dos controles de
        terminal). Quando ausente, fallback para o slot legado da 4a div
        do MetricsBar.

        Idempotente: limpa o layout antes de inserir, em caso de re-build.
        Os handlers replicam o comportamento original do output-toolbar:
        JSON/WS resolvem via `app_state.config`; demais emitem o comando
        cru via `signal_bus.paste_text_in_terminal` + focus.
        """
        from PySide6.QtWidgets import QHBoxLayout  # noqa: F401 — referenced in type only

        slot = target if target is not None else getattr(
            self._metrics_bar, "_header_actions_layout", None,
        )
        if slot is None:
            return

        # Idempotency: drop any previously-added widgets.
        while slot.count():
            item = slot.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        def _make_action_btn(
            label: str, testid: str, bg: str, hover: str, pressed: str, tooltip: str,
        ) -> QPushButton:
            btn = QPushButton(label)
            btn.setProperty("testid", testid)
            btn.setFixedHeight(28)
            btn.setMinimumWidth(64)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: #FAFAFA;"
                "  border: none; border-radius: 5px;"
                "  font-size: 10px; font-weight: 700; padding: 0 8px; }"
                f"QPushButton:hover {{ background-color: {hover}; }}"
                f"QPushButton:pressed {{ background-color: {pressed}; }}"
                "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
            )
            return btn

        def _on_json_path() -> None:
            import os
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
            # Task 6 (loop 05-13-workflow-app-layout-2): roteamento T1/T2.
            self._publish_to_terminal(rel)
            signal_bus.toast_requested.emit(
                "Caminho JSON copiado e digitado no terminal.", "info",
            )

        def _on_ws_path() -> None:
            if not app_state.has_config or not app_state.config:
                signal_bus.toast_requested.emit("Nenhum projeto carregado.", "warning")
                return
            ws = app_state.config.workspace_root
            QApplication.clipboard().setText(ws)
            # Task 6 (loop 05-13-workflow-app-layout-2): roteamento T1/T2.
            self._publish_to_terminal(ws)
            signal_bus.toast_requested.emit(
                "workspace_root copiado e digitado no terminal.", "info",
            )

        # Task 4c (loop 05-13-workflow-app-layout-2): Brief/Docs espelham WS,
        # porem com basic_flow.brief_root / basic_flow.docs_root.
        def _on_brief_path() -> None:
            if not app_state.has_config or not app_state.config:
                signal_bus.toast_requested.emit("Nenhum projeto carregado.", "warning")
                return
            brief = app_state.config.brief_root
            QApplication.clipboard().setText(brief)
            # Task 6 (loop 05-13-workflow-app-layout-2): roteamento T1/T2.
            self._publish_to_terminal(brief)
            signal_bus.toast_requested.emit(
                "brief_root copiado e digitado no terminal.", "info",
            )

        def _on_docs_path() -> None:
            if not app_state.has_config or not app_state.config:
                signal_bus.toast_requested.emit("Nenhum projeto carregado.", "warning")
                return
            docs = app_state.config.docs_root
            QApplication.clipboard().setText(docs)
            # Task 6 (loop 05-13-workflow-app-layout-2): roteamento T1/T2.
            self._publish_to_terminal(docs)
            signal_bus.toast_requested.emit(
                "docs_root copiado e digitado no terminal.", "info",
            )

        # Task 6 (loop 05-13-workflow-app-layout-2): roteamento T1/T2 nos
        # botoes mcp-codex / mcp-kimi / double-mcp / asq-user (actions_row).
        def _paste_cmd(cmd: str):
            def _h() -> None:
                self._publish_to_terminal(cmd)
            return _h

        json_btn = _make_action_btn(
            "JSON", "queue-btn-json-path",
            "#D97706", "#B45309", "#92400E",
            "Copia o caminho do project.json\ne digita no terminal automaticamente",
        )
        json_btn.clicked.connect(_on_json_path)

        ws_btn = _make_action_btn(
            "WS", "queue-btn-ws-path",
            "#059669", "#047857", "#065F46",
            "Copia o workspace_root do projeto\ne digita no terminal automaticamente",
        )
        ws_btn.clicked.connect(_on_ws_path)

        # Task 4c (loop 05-13-workflow-app-layout-2): Brief/Docs apos json/ws.
        brief_btn = _make_action_btn(
            "Brief", "queue-btn-brief-path",
            "#0EA5E9", "#0284C7", "#0369A1",
            "Copia o brief_root do projeto\ne digita no terminal automaticamente",
        )
        brief_btn.clicked.connect(_on_brief_path)

        docs_btn = _make_action_btn(
            "Docs", "queue-btn-docs-path",
            "#9333EA", "#7E22CE", "#6B21A8",
            "Copia o docs_root do projeto\ne digita no terminal automaticamente",
        )
        docs_btn.clicked.connect(_on_docs_path)

        # JSON/WS/Brief/Docs vao para o lado esquerdo da linha de controles
        # quando o target dedicado for fornecido (space-between com toggle/chevron).
        # Fallback: anexar ao slot principal junto aos demais botoes.
        if controls_left_target is not None:
            controls_left_target.insertWidget(0, json_btn)
            controls_left_target.insertWidget(1, ws_btn)
            controls_left_target.insertWidget(2, brief_btn)
            controls_left_target.insertWidget(3, docs_btn)
        else:
            slot.addWidget(json_btn)
            slot.addWidget(ws_btn)
            slot.addWidget(brief_btn)
            slot.addWidget(docs_btn)

        mcp_codex_btn = _make_action_btn(
            "mcp-codex", "output-btn-mcp-codex",
            "#7C3AED", "#6D28D9", "#5B21B6",
            "/skill:mcp-codex \u2014 Pair programming com Codex MCP",
        )
        mcp_codex_btn.clicked.connect(_paste_cmd("/skill:mcp-codex"))
        slot.addWidget(mcp_codex_btn)

        mcp_kimi_btn = _make_action_btn(
            "mcp-kimi", "output-btn-mcp-kimi",
            "#2563EB", "#1D4ED8", "#1E40AF",
            "/skill:mcp-kimi \u2014 Persona-aware Kimi orchestrator",
        )
        mcp_kimi_btn.clicked.connect(_paste_cmd("/skill:mcp-kimi"))
        slot.addWidget(mcp_kimi_btn)

        double_mcp_btn = _make_action_btn(
            "double-mcp", "output-btn-double-mcp",
            "#DC2626", "#B91C1C", "#991B1B",
            "/skill:double-mcp \u2014 Co-execucao paralela Codex+Kimi",
        )
        double_mcp_btn.clicked.connect(_paste_cmd("/skill:double-mcp"))
        slot.addWidget(double_mcp_btn)

        asq_user_btn = _make_action_btn(
            "asq-user", "output-btn-asq-user",
            "#F59E0B", "#D97706", "#B45309",
            "/skill:auq-interview \u2014 Entrevista AUQ guiada",
        )
        asq_user_btn.clicked.connect(_paste_cmd("/skill:auq-interview"))
        slot.addWidget(asq_user_btn)

        # Task 7 (loop 05-13-workflow-app-layout-2): botao Progress como
        # ULTIMO widget de output-toolbar-actions-row. Click publica
        # PROGRESS_PROMPT (constante module-level, ver topo deste arquivo)
        # via self._publish_to_terminal() — reusa publish unico da Task 6.
        progress_btn = _make_action_btn(
            "Progress", "output-btn-progress",
            "#10B981", "#059669", "#047857",
            "Progress \u2014 publica prompt longo de execucao adversarial\n"
            "(double-mcp + codex review) no terminal alvo (T1/T2).",
        )
        progress_btn.clicked.connect(lambda: self._publish_to_terminal(PROGRESS_PROMPT))
        slot.addWidget(progress_btn)

        # Refactor 2026-05-14 layout-3: 5 botoes "nav" na output-toolbar-datatest-row.
        # Cada botao publica seu testid alvo via _publish_to_terminal (rota T1/T2),
        # exatamente como os demais botoes da output-toolbar-center.
        if datatest_row_target is not None:
            _NAV_BUTTONS = [
                ("div-play", "queue-btn-play-next-container"),
                ("cmd-list", "queue-command-list"),
                ("nav-left", "output-toolbar-left"),
                ("nav-center", "output-toolbar-center"),
                ("nav-right", "output-toolbar-right"),
            ]
            for label, target_testid in _NAV_BUTTONS:
                nav_btn = _make_action_btn(
                    label, f"output-btn-nav-{target_testid}",
                    "#475569", "#334155", "#1E293B",
                    f"Publica `{target_testid}` no terminal alvo (T1/T2).",
                )
                nav_btn.clicked.connect(_paste_cmd(target_testid))
                datatest_row_target.addWidget(nav_btn)
            datatest_row_target.addStretch(1)

    def _build_terminal_notes_footer(self, testid: str) -> QWidget:
        """Footer de anotacoes livre por terminal — sem comunicacao com o resto
        do app.

        Mesma altura do `queue-add-bar` (36px) para casar visualmente quando os
        terminais ficam lado a lado com a queue. Aparencia neutra (letra
        normal, fundo escuro padrao), distinto do `main-window-label` que e
        outdoor verde grande.

        Acoes a direita do input:
          1. Botao seta para cima — cola o texto do input no terminal
             correspondente ao testid (interactive vs workspace).
          2. Botao copiar (icone de duas folhas sobrepostas) — joga o texto
             na clipboard.

        Os icones SVG sao renderizados em branco via QSvgRenderer + QPainter
        porque os assets usam `stroke="currentColor"` e QIcon nao herda cor
        do QSS.
        """
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QApplication, QHBoxLayout

        bar = QWidget()
        bar.setProperty("testid", testid)
        bar.setFixedHeight(36)
        bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        notes_input = QLineEdit()
        notes_input.setPlaceholderText("anotacoes")
        notes_input.setStyleSheet(
            "QLineEdit {"
            "  color: #E4E4E7;"
            "  background-color: #18181B;"
            "  border: 1px solid #3F3F46;"
            "  border-radius: 3px;"
            "  font-size: 12px;"
            "  padding: 2px 6px;"
            "}"
            "QLineEdit:focus { border-color: #52525B; }"
        )
        lay.addWidget(notes_input, stretch=1)

        btn_style = (
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: 1px solid #52525B; border-radius: 3px; padding: 2px; }"
            "QPushButton:hover { background-color: #52525B; color: #FFFFFF; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B;"
            "  border-color: #FBBF24; }"
        )

        paste_btn = QPushButton()
        arrow_icon_path = Path(_WORKFLOW_APP_DIR) / "assets" / "arrow-up.svg"
        arrow_icon = self._load_tinted_svg_icon(arrow_icon_path, "#FAFAFA")
        if arrow_icon is not None:
            paste_btn.setIcon(arrow_icon)
            paste_btn.setIconSize(QSize(14, 14))
        else:
            paste_btn.setText("↑")
        paste_btn.setFixedSize(26, 26)
        paste_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        paste_btn.setToolTip("Colar anotacao no terminal")
        paste_btn.setStyleSheet(btn_style)

        is_workspace = testid == "terminal-workspace-notes"

        def _paste_to_terminal() -> None:
            text = notes_input.text()
            if not text:
                return
            if is_workspace:
                signal_bus.paste_text_in_workspace_terminal.emit(text)
                try:
                    self._workspace_panel._terminal.setFocus()
                except AttributeError:
                    pass
            else:
                signal_bus.paste_text_in_terminal.emit(text)
                signal_bus.focus_interactive_terminal.emit()

        paste_btn.clicked.connect(_paste_to_terminal)
        lay.addWidget(paste_btn)

        clear_btn = QPushButton()
        broom_icon_path = Path(_WORKFLOW_APP_DIR) / "assets" / "broom.svg"
        broom_icon = self._load_tinted_svg_icon(broom_icon_path, "#FAFAFA")
        if broom_icon is not None:
            clear_btn.setIcon(broom_icon)
            clear_btn.setIconSize(QSize(14, 14))
        else:
            clear_btn.setText("🧹")
        clear_btn.setFixedSize(26, 26)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setToolTip("Limpar anotacao")
        clear_btn.setStyleSheet(btn_style)
        clear_btn.clicked.connect(notes_input.clear)
        lay.addWidget(clear_btn)

        copy_btn = QPushButton()
        copy_icon_path = Path(_WORKFLOW_APP_DIR) / "assets" / "copy.svg"
        copy_icon = self._load_tinted_svg_icon(copy_icon_path, "#FAFAFA")
        if copy_icon is not None:
            copy_btn.setIcon(copy_icon)
            copy_btn.setIconSize(QSize(14, 14))
        else:
            copy_btn.setText("⎘")
        copy_btn.setFixedSize(26, 26)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setToolTip("Copiar anotacao para a area de transferencia")
        copy_btn.setStyleSheet(btn_style)
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(notes_input.text())
        )
        lay.addWidget(copy_btn)

        return bar

    def _load_tinted_svg_icon(self, path: Path, color_hex: str) -> QIcon | None:
        """Le um SVG com `stroke/fill="currentColor"` e renderiza em `color_hex`,
        retornando um QIcon. Devolve None se o arquivo nao existir ou o
        modulo QtSvg nao estiver disponivel — caller cuida do fallback texto.
        """
        if not path.is_file():
            return None
        try:
            from PySide6.QtCore import QByteArray, QSize as _QSize
            from PySide6.QtGui import QPainter, QPixmap
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
        pixmap = QPixmap(_QSize(32, 32))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            renderer.render(painter)
        finally:
            painter.end()
        return QIcon(pixmap)

    def _build_workspace_label_bar(self) -> QWidget:
        """20px label bar for the Workspace terminal with four shortcut buttons.

        Buttons: WORKSPACE (purple) · SystemForge (blue) · cd Workflow-app (teal)
        · mention Workflow-app (teal). The three leftmost send a `cd <absolute>`
        + Enter; the rightmost pastes the relative path `ai-forge/workflow-app`
        without Enter.
        """
        from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

        bar = QWidget()
        bar.setFixedHeight(20)
        bar.setStyleSheet("background-color: #1E1B4B;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 0, 4, 0)
        lay.setSpacing(0)

        def _btn(label: str, color: str) -> QPushButton:
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; color: {color};"
                f"  font-size: 10px; font-weight: 700; padding: 0 3px; }}"
                f"QPushButton:hover {{ color: #FFFFFF; background: transparent; }}"
            )
            return b

        # ── WORKSPACE — cd to project workspace_root ──────────────────── #
        btn_ws = _btn("WORKSPACE", "#A78BFA")
        btn_ws.setToolTip("cd → workspace do projeto carregado")

        def _on_workspace() -> None:
            if not app_state.has_config or not app_state.config:
                signal_bus.toast_requested.emit("Nenhum projeto carregado.", "warning")
                return
            path = str(app_state.config.project_dir / app_state.config.workspace_root)
            signal_bus.run_command_in_workspace_terminal.emit(f"cd {path}")
            self._workspace_panel._terminal.setFocus()

        btn_ws.clicked.connect(_on_workspace)

        # ── SystemForge — cd to monorepo root ─────────────────────────── #
        btn_sf = _btn("SystemForge", "#60A5FA")
        btn_sf.setToolTip(f"cd → {_SYSTEMFORGE_DIR}")
        btn_sf.clicked.connect(
            lambda: (
                signal_bus.run_command_in_workspace_terminal.emit(f"cd {_SYSTEMFORGE_DIR}"),
                self._workspace_panel._terminal.setFocus(),
            )
        )

        # ── cd Workflow-app — cd to ai-forge/workflow-app ─────────────── #
        btn_wa = _btn("cd Workflow-app", "#2DD4BF")
        btn_wa.setToolTip(f"cd → {_WORKFLOW_APP_DIR}")
        btn_wa.clicked.connect(
            lambda: (
                signal_bus.run_command_in_workspace_terminal.emit(f"cd {_WORKFLOW_APP_DIR}"),
                self._workspace_panel._terminal.setFocus(),
            )
        )

        # ── mention Workflow-app — paste relative path without Enter ──── #
        btn_wa_mention = _btn("mention Workflow-app", "#2DD4BF")
        btn_wa_mention.setToolTip("Cola 'ai-forge/workflow-app' no terminal (sem Enter)")
        btn_wa_mention.clicked.connect(
            lambda: (
                signal_bus.paste_text_in_workspace_terminal.emit("ai-forge/workflow-app"),
                self._workspace_panel._terminal.setFocus(),
            )
        )

        lay.addWidget(btn_ws)
        lay.addSpacing(6)
        lay.addWidget(btn_sf)
        lay.addSpacing(6)
        lay.addWidget(btn_wa)
        lay.addSpacing(6)
        lay.addWidget(btn_wa_mention)
        lay.addStretch()
        return bar

    def _build_history_panel(self) -> QWidget:
        """Cria o painel de histórico: FilterPanel + lista + detalhe.

        Se o DatabaseManager ainda não foi inicializado (ex: em testes),
        retorna um placeholder vazio sem levantar exceção.
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.history.history_manager import HistoryManager

            history_mgr = HistoryManager(db_manager.session_factory)

            self._filter_panel = FilterPanel(parent=container)
            layout.addWidget(self._filter_panel)

            content_splitter = QSplitter(Qt.Orientation.Vertical)
            content_splitter.setChildrenCollapsible(False)

            self._history_list = ExecutionHistoryWidget(history_mgr, parent=container)
            content_splitter.addWidget(self._history_list)

            self._history_detail = ExecutionDetailPanel(history_mgr, parent=container)
            content_splitter.addWidget(self._history_detail)

            content_splitter.setSizes([300, 200])
            layout.addWidget(content_splitter, stretch=1)

            # Wire signals
            self._filter_panel.filter_changed.connect(self._history_list.apply_filter)
            self._history_list.execution_selected.connect(
                self._history_detail.load_execution
            )

        except RuntimeError:
            # db_manager not yet initialized (e.g. during tests without setup())
            from PySide6.QtWidgets import QLabel
            placeholder = QLabel("Histórico disponível após inicialização do banco.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(placeholder)

        return container

    def _setup_shortcuts(self) -> None:
        save_queue = QAction("Salvar Fila", self)
        save_queue.setShortcut(QKeySequence("Ctrl+S"))
        save_queue.triggered.connect(self._on_save_queue)
        self.addAction(save_queue)

    def _toggle_terminal_layout(self) -> None:
        """Toggle terminal splitter between vertical (column) and horizontal (row)."""
        if self._terminal_is_vertical:
            self._terminal_splitter.setOrientation(Qt.Orientation.Horizontal)
            self._layout_toggle_btn.setIcon(self._layout_icon_stacked)
            self._layout_toggle_btn.setToolTip("Layout: lado a lado. Clique para empilhar")
            self._terminal_is_vertical = False
        else:
            self._terminal_splitter.setOrientation(Qt.Orientation.Vertical)
            self._layout_toggle_btn.setIcon(self._layout_icon_side)
            self._layout_toggle_btn.setToolTip("Layout: empilhado. Clique para lado a lado")
            self._terminal_is_vertical = True
        self._update_collapse_chevron()

    def _toggle_workspace_collapse(self) -> None:
        """Toggle collapse/expand of the workspace terminal."""
        if self._workspace_collapsed:
            self._workspace_wrapper.show()
            if hasattr(self, "_saved_splitter_sizes"):
                self._terminal_splitter.setSizes(self._saved_splitter_sizes)
            else:
                self._terminal_splitter.setSizes([350, 350])
            self._workspace_collapsed = False
            self._collapse_chevron.setToolTip("Colapsar terminal Workspace")
        else:
            self._saved_splitter_sizes = self._terminal_splitter.sizes()
            self._workspace_wrapper.hide()
            self._workspace_collapsed = True
            self._collapse_chevron.setToolTip("Expandir terminal Workspace")
        self._update_collapse_chevron()

    def _update_collapse_chevron(self) -> None:
        """Update chevron icon based on collapsed state."""
        if self._workspace_collapsed:
            self._collapse_chevron.setText("\u25B6")  # ▶ collapsed
        else:
            self._collapse_chevron.setText("\u25BC")  # ▼ expanded

    def _connect_signals(self) -> None:
        self._command_queue.add_command_requested.connect(self._open_add_command)
        self._command_queue.reorder_requested.connect(self._on_queue_reorder_requested)
        self._command_queue.save_requested.connect(self._on_save_queue)
        self._metrics_bar.view_changed.connect(self._on_view_changed)
        signal_bus.toast_requested.connect(self._show_toast)
        signal_bus.pipeline_ready.connect(self._on_pipeline_ready)
        signal_bus.history_panel_toggled.connect(self._switch_to_history_tab)
        signal_bus.pipeline_started.connect(self._switch_to_output_tab)
        # Task 3 (loop 05-13-workflow-app-layout-2): migrado para signal granular
        # com modos `off`/`all`/`body`/`buttons`. `datatest_toggled` mantido em
        # signal_bus por compat mas nao mais emitido pela UI.
        signal_bus.datatest_mode_changed.connect(self._on_datatest_mode_changed)
        signal_bus.focus_interactive_terminal.connect(self._on_focus_interactive_terminal)
        signal_bus.pipeline_completed.connect(self._refresh_history_list)
        signal_bus.permission_request_received.connect(self._on_permission_request)
        # _btn_new removed — pipeline creator accessible via command queue or Ctrl+N
        # RF10: Dry Run handler
        signal_bus.dry_run_requested.connect(self._on_dry_run)
        # RF03: Pipeline execution control (guarded to prevent signal recursion)
        signal_bus.pipeline_paused.connect(self._on_pipeline_paused_for_pm)
        signal_bus.pipeline_resumed.connect(self._on_pipeline_resumed_for_pm)
        signal_bus.pipeline_retry_requested.connect(self._on_pipeline_retry_requested)
        signal_bus.pipeline_cancelled.connect(self._on_pipeline_cancel_for_pm)

    # ─────────────────────────────────────────────────────── State ───── #

    def _save_state(self) -> None:
        self._settings.setValue(self._SETTINGS_GEOMETRY, self.saveGeometry())
        self._settings.setValue(self._SETTINGS_SPLITTER, self._splitter.sizes())

    def _restore_state(self) -> None:
        geometry = self._settings.value(self._SETTINGS_GEOMETRY)
        if geometry:
            self.restoreGeometry(geometry)
        splitter_sizes = self._settings.value(self._SETTINGS_SPLITTER)
        if splitter_sizes:
            try:
                self._splitter.setSizes([int(s) for s in splitter_sizes])
            except (ValueError, TypeError):
                pass

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._settings.value(self._SETTINGS_SPLITTER):
            total = self._splitter.width()
            if total > 0:
                self._splitter.setSizes([total // 3, total * 2 // 3])

    def closeEvent(self, event) -> None:  # noqa: N802
        # T-037: release the cooperative lock BEFORE saving state so the
        # filesystem lock is relinquished even if persistence blows up.
        # release_and_stop() is idempotent and never raises, but we wrap
        # it defensively so a regression cannot prevent app shutdown.
        try:
            self._lock_service.release_and_stop()
        except Exception:  # noqa: BLE001
            logger.exception("closeEvent: failed to release cooperative lock")
        self._save_state()
        super().closeEvent(event)

    def _on_lock_lost(self, reason: str) -> None:
        """Slot for LockService.lock_lost — surface a toast to the user.

        T-037: in API-only mode, no flow actively holds the lock, so this
        slot is mostly a safety net for future T-038 edit flows. We keep
        the wiring now so the contract is stable from day one.
        """
        logger.warning("MainWindow: cooperative lock lost: %s", reason)
        signal_bus.toast_requested.emit(
            "Lock cooperativo perdido — outra instancia assumiu delivery.json",
            "error",
        )

    # ─────────────────────────────────────────────────────── Slots ───── #

    def _open_add_command(self) -> None:
        next_pos = len(self._command_queue._items) + 1
        dialog = AddCommandDialog(next_position=next_pos, parent=self)
        dialog.command_added.connect(self._on_command_added)
        dialog.exec()

    def _on_pipeline_ready(self, commands: list[CommandSpec]) -> None:
        # Annotate each spec with the relative config path when a project is loaded.
        # Comandos /boilerplate:* recebem config_path pre-setado pelo handler
        # (repo_path no scan, staging_path nos demais) e NAO devem ser sobrescritos
        # pelo project.json. Para os demais comandos mantemos o comportamento legado
        # (anotar com a config relativa) para nao regredir templates customizados.
        if app_state.has_config and app_state.config:
            import os
            abs_config = app_state.config.config_path
            project_dir = str(app_state.config.project_dir)
            try:
                rel = os.path.relpath(abs_config, project_dir)
            except ValueError:
                rel = abs_config
            for spec in commands:
                if spec.name.startswith("/model ") or spec.name.startswith("/effort ") or spec.name == "/clear":
                    continue  # model-switch, /effort and /clear rows must never carry a config path
                if spec.name.startswith("/boilerplate:"):
                    continue  # respeita config_path pre-setado por _on_boilerplate_clicked
                if spec.name.startswith("/auto-improove:"):
                    continue  # auto-improove opera sobre o proprio SystemForge, sem project.json
                if spec.name.startswith("/blog:"):
                    continue  # blog opera sobre o proprio SystemForge, sem project.json
                if spec.name.startswith("/cmd:"):
                    continue  # /cmd:* sao META commands do SystemForge, nao dependem de project.json
                spec.config_path = rel

        self._command_queue.load_pipeline(commands)
        # NOTE: do NOT emit signal_bus.pipeline_ready here — it is connected back
        # to this slot and would cause infinite recursion.
        signal_bus.pipeline_created.emit(commands)

        # RF03: Instantiate PipelineManager for this pipeline session.
        from workflow_app.db.database_manager import db_manager
        from workflow_app.pipeline.pipeline_manager import PipelineManager
        from workflow_app.sdk.sdk_adapter import SDKAdapter

        adapter = SDKAdapter()
        # cwd = raiz da systemForge (onde está .claude/commands/) para que os
        # slash commands sejam encontrados pelo claude-agent-sdk
        if app_state.has_config:
            workspace = str(app_state.config.project_dir)
        else:
            # Detect systemForge root by walking up from cwd looking for .claude/commands/
            from pathlib import Path
            _cwd = Path.cwd()
            workspace = str(_cwd)
            for p in [_cwd, *_cwd.parents]:
                if (p / ".claude" / "commands").is_dir() and (p / "CLAUDE.md").is_file():
                    workspace = str(p)
                    break
        self._pipeline_manager = PipelineManager(
            signal_bus=signal_bus,
            sdk_adapter=adapter,
            session_factory=db_manager.session_factory,
            workspace_dir=workspace,
        )
        self._pipeline_manager.set_queue(commands)
        self._command_queue.set_pipeline_manager(self._pipeline_manager)

        self._show_toast(
            f"Pipeline carregado: {len(commands)} comandos", "success"
        )

    def _on_command_added(self, spec: CommandSpec) -> None:
        # RESOLVED: G001 — append to existing queue
        self._command_queue.add_command(spec)
        self._show_toast(f"Comando adicionado: {spec.name}", "success")

    def _on_config_change_requested(self, path: str) -> None:
        """Trata solicitação de troca de config vinda da ConfigBar."""
        self._load_config(path)
        if app_state.has_config and app_state.config and app_state.config.config_path == path:
            signal_bus.toast_requested.emit(
                f"Projeto carregado: {app_state.project_name}", "success"
            )

    def _on_view_changed(self, index: int) -> None:
        """Switch the main view stack (0=Workflow, 2=Kanban, 3=ModuleDetail).

        Index 1 (Comandos) is blocked — nav buttons are hidden and the
        workflow view is permanently active.
        """
        if index == 1:
            return
        self._view_stack.setCurrentIndex(index)
        if self._datatest_active:
            self._show_testid_overlays()

    def _switch_to_output_tab(self) -> None:
        """Switch to Workflow view (output container is the only left pane)."""
        self._view_stack.setCurrentIndex(0)
        self._metrics_bar.set_active_view(0)

    def _switch_to_history_tab(self) -> None:
        """No-op since the Histórico tab was eliminated (refactor 2026-05-12).

        Kept as a stub because signal_bus.history_panel_toggled still exists
        and may be wired by remote/legacy code paths.
        """
        self._view_stack.setCurrentIndex(0)
        self._metrics_bar.set_active_view(0)

    def _refresh_history_list(self) -> None:
        """No-op stub; the history panel is no longer mounted in the UI."""
        return

    def _show_toast(self, message: str, msg_type: str = "info") -> None:
        self._toast_notifier.show(message, msg_type)

    # ─────────────────────────────────── DataTest overlay & terminal focus ─ #

    def _on_focus_interactive_terminal(self) -> None:
        """Switch to output tab and focus the interactive terminal."""
        self._switch_to_output_tab()
        self._output_panel._terminal.setFocus()

    def _on_datatest_toggled(self, enabled: bool) -> None:
        """Compat legado: roteia para o novo handler de modo.

        Mantido caso codigo externo ainda emita `signal_bus.datatest_toggled`.
        """
        self._on_datatest_mode_changed("all" if enabled else "off")

    def _on_datatest_mode_changed(self, mode: str) -> None:
        """Task 3 (loop 05-13-workflow-app-layout-2): handler de modo test-mode.

        Modos validos: `off`, `all`, `body` (tudo MENOS QAbstractButton),
        `buttons` (APENAS QAbstractButton).
        """
        if mode not in ("off", "all", "body", "buttons"):
            mode = "off"
        self._datatest_mode = mode
        self._datatest_active = mode != "off"
        if mode == "off":
            self._hide_testid_overlays()
        else:
            self._show_testid_overlays()

    def _show_testid_overlays(self) -> None:
        """Walk child widgets of the active tab and show floating red testid overlay labels.

        Only scans widgets within the currently selected view tab
        (0=Workflow, 1=Comandos, 2=Kanban, 3=ModuleDetail) plus the shared MetricsBar.
        Overlays are parented to the central widget so they float beyond
        their target widget bounds. Click an overlay to copy its text.
        """
        self._hide_testid_overlays()
        from PySide6.QtCore import QPoint, QTimer
        from PySide6.QtWidgets import QApplication as _QApp, QLabel as _Lbl

        central = self.centralWidget()
        used_positions: list[tuple[int, int, int, int]] = []  # x, y, w, h

        _STYLE_NORMAL = (
            "background-color: rgba(220, 38, 38, 0.9); color: white;"
            " font-size: 11px; font-weight: 700; padding: 3px 6px;"
            " border-radius: 3px; border: none;"
        )
        _STYLE_COPIED = (
            "background-color: rgba(34, 197, 94, 0.9); color: white;"
            " font-size: 11px; font-weight: 700; padding: 3px 6px;"
            " border-radius: 3px; border: none;"
        )

        # Only scan the active view's widget + metrics bar
        active_page = self._view_stack.currentWidget()
        scan_roots = [active_page, self._metrics_bar]
        scan_widgets: list[QWidget] = []
        for root in scan_roots:
            if root:
                scan_widgets.append(root)
                scan_widgets.extend(root.findChildren(QWidget))

        # Task 3 (loop 05-13-workflow-app-layout-2): filtragem por modo test-mode.
        from PySide6.QtWidgets import QAbstractButton as _AbsBtn

        _mode = getattr(self, "_datatest_mode", "all")
        for widget in scan_widgets:
            testid = widget.property("testid")
            if not testid or widget.property("_is_testid_overlay"):
                continue
            _is_btn = isinstance(widget, _AbsBtn)
            if _mode == "body" and _is_btn:
                continue
            if _mode == "buttons" and not _is_btn:
                continue
            if testid and not widget.property("_is_testid_overlay"):
                # Skip widgets that aren't visible on screen
                if not widget.isVisible() or not widget.isVisibleTo(central):
                    continue
                testid_str = str(testid)

                # Map widget position to central widget coordinates
                # Offset badges slightly above the target widget
                try:
                    pos = widget.mapTo(central, QPoint(0, 0))
                except RuntimeError:
                    continue
                x, y = pos.x(), pos.y() - 14

                # Offset if overlapping with existing overlay
                for ux, uy, uw, uh in used_positions:
                    if abs(x - ux) < max(uw, 30) and abs(y - uy) < max(uh, 18):
                        y = uy + uh + 2

                overlay = _Lbl(testid_str, central)
                overlay.setStyleSheet(_STYLE_NORMAL)
                overlay.setProperty("_is_testid_overlay", True)
                overlay.setCursor(Qt.CursorShape.PointingHandCursor)
                overlay.setToolTip(f"Clique para copiar: {testid_str}")

                # Click to copy to clipboard with visual feedback
                def _make_click(lbl, text):
                    def _handler(_event):
                        _QApp.clipboard().setText(f'data-testid="{text}"')
                        lbl.setStyleSheet(_STYLE_COPIED)
                        QTimer.singleShot(600, lambda: lbl.setStyleSheet(_STYLE_NORMAL))
                    return _handler

                overlay.mousePressEvent = _make_click(overlay, testid_str)

                overlay.adjustSize()
                overlay.move(x, y)
                overlay.show()
                overlay.raise_()
                used_positions.append((x, y, overlay.width(), overlay.height()))
                self._testid_overlays.append(overlay)

    def _hide_testid_overlays(self) -> None:
        """Remove all testid overlay labels."""
        for overlay in self._testid_overlays:
            overlay.hide()
            overlay.deleteLater()
        self._testid_overlays.clear()

    def _on_permission_request(self, request_data: dict) -> None:
        """Show PermissionRequestDialog when the SDK needs user approval."""
        from workflow_app.dialogs.permission_request_dialog import (
            PermissionRequestDialog,
        )
        from workflow_app.sdk.sdk_adapter import SDKAdapter

        dlg = PermissionRequestDialog(parent=self, request_data=request_data)

        # Route permission response to the active PipelineManager's SDKAdapter.
        sdk_adapter: SDKAdapter | None = None
        if self._pipeline_manager is not None:
            sdk_adapter = self._pipeline_manager._sdk_adapter

        def _on_granted() -> None:
            if sdk_adapter is not None:
                sdk_adapter.respond_to_permission(True)

        def _on_rejected() -> None:
            if sdk_adapter is not None:
                sdk_adapter.respond_to_permission(False)
            self._show_toast("Permissão rejeitada.", "warning")

        dlg.permission_granted.connect(_on_granted)
        dlg.permission_rejected.connect(_on_rejected)
        dlg.exec()

    # ──────────────────────────────────────────── Config detection ──── #

    def _attempt_startup_detection(self) -> None:
        """Tenta detectar e carregar project.json automaticamente ao iniciar.

        Prioridade:
        1. Último config salvo no QSettings (persistência entre sessões)
        2. Auto-detecção via detect_config() (fallback)
        """
        from pathlib import Path

        last_path = self._settings.value(self._SETTINGS_LAST_CONFIG)
        if last_path and Path(last_path).exists():
            logger.info("Restaurando último config do QSettings: %s", last_path)
            self._load_config(last_path)
            return

        config_path = detect_config()
        if config_path:
            logger.info("Config detectado no startup: %s", config_path)
            self._load_config(config_path)
        else:
            logger.info("Nenhum config detectado no cwd. Modo sem projeto.")
            self._update_title(project_name=None)

    def _load_config(self, path: str) -> None:
        """Carrega um project.json e atualiza o estado da aplicação.

        Emite signal_bus.config_loaded em caso de sucesso.
        Exibe toast de erro em caso de falha.
        """
        try:
            config = parse_config(path)
        except (ConfigError, FileNotFoundError) as exc:
            logger.error("Falha ao carregar config '%s': %s", path, exc)
            signal_bus.toast_requested.emit(
                f"Falha ao carregar config: {exc.message if isinstance(exc, ConfigError) else str(exc)}",
                "error",
            )
            return

        app_state.set_config(config)
        self._update_title(project_name=config.project_name)
        self._settings.setValue(self._SETTINGS_LAST_CONFIG, path)
        signal_bus.config_loaded.emit(path)
        logger.info("Config carregado: projeto=%s", config.project_name)
        self._check_template_versions()  # RESOLVED: G002
        self._restore_queue_from_storage(path)
        self._load_kanban_from_config(config)

    def _check_template_versions(self) -> None:
        """Check if factory templates are aligned with the current CLAUDE.md.  # RESOLVED: G002"""
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.templates.template_manager import TemplateManager
            from workflow_app.templates.version_checker import VersionChecker

            self._version_checker_mgr = TemplateManager(db_manager)
            self._version_checker = VersionChecker(self._version_checker_mgr)
            result = self._version_checker.check_factory_templates()
            if result.is_outdated:
                self._version_banner.set_outdated_names(result.outdated_names)
                self._version_banner.setVisible(True)
        except Exception:
            pass  # version check is non-critical

    def _on_version_update_requested(self) -> None:
        """Refresh factory templates with the current CLAUDE.md hash."""
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.templates.claude_md_hasher import compute_hash, find_claude_md
            from workflow_app.templates.factory_templates import refresh_factory_templates

            path = find_claude_md()
            new_hash = compute_hash(path) if path else None
            if new_hash:
                refresh_factory_templates(db_manager, new_hash)
                self._show_toast("Templates de fábrica atualizados.", "success")
            else:
                self._show_toast("CLAUDE.md não encontrado. Atualização cancelada.", "warning")
        except Exception as exc:
            logger.error("Erro ao atualizar templates de fábrica: %s", exc)
            self._show_toast("Falha ao atualizar templates.", "error")

    # ─────────────────────────────────── RF03: Pipeline execution control ─── #

    def _on_run_requested(self) -> None:
        """Called when ▶ is clicked — starts the active PipelineManager."""
        if self._pipeline_manager is not None:
            self._pipeline_manager.start()

    def _on_pipeline_paused_for_pm(self) -> None:
        """Guard-wrapped pause: prevents signal recursion (pm.pause() re-emits pipeline_paused)."""
        pm = self._pipeline_manager
        if pm is not None and not pm._paused:
            pm.pause()

    def _on_pipeline_resumed_for_pm(self) -> None:
        """Guard-wrapped resume: prevents signal recursion (pm.resume() re-emits pipeline_resumed)."""
        pm = self._pipeline_manager
        if pm is not None and pm._paused:
            pm.resume()

    def _on_pipeline_retry_requested(self, _index: int) -> None:
        """Retry the current ERRO command via PipelineManager."""
        if self._pipeline_manager is not None:
            self._pipeline_manager.retry_current()

    def _on_pipeline_cancel_for_pm(self) -> None:
        """Cancel the active pipeline, then clear the manager reference."""
        pm = self._pipeline_manager
        if pm is not None and pm._pipeline_exec_id is not None:
            self._pipeline_manager = None  # clear first to prevent re-entry
            pm.cancel()

    def _on_queue_reorder_requested(self, from_pos: int, to_pos: int) -> None:
        """Handle drag-and-drop reorder from CommandQueueWidget."""
        if self._pipeline_manager is None:
            return
        success = self._pipeline_manager.reorder_command(from_pos, to_pos)
        if success:
            self._refresh_queue_ui()

    def _refresh_queue_ui(self) -> None:
        """Reload the queue display from the pipeline manager's current queue."""
        if self._pipeline_manager is None:
            return
        self._command_queue.load_pipeline(self._pipeline_manager._queue)

    # ──────────────────────────────────────── RF10: Dry Run handler ─────── #

    def _on_dry_run(self) -> None:
        """Validate the current command queue offline via DryRunValidator."""
        from workflow_app.dry_run import DryRunValidator

        commands = [item.get_spec() for item in self._command_queue._items]
        if not commands:
            self._show_toast("Nenhum comando na fila para validar.", "warning")
            return

        report = DryRunValidator().validate(commands)
        if report.is_valid:
            warnings = len(report.warnings)
            msg = f"Dry Run: OK — {len(commands)} comando(s) válido(s)."
            if warnings:
                msg += f" {warnings} aviso(s)."
            self._show_toast(msg, "success")
        else:
            errors = len(report.errors)
            self._show_toast(
                f"Dry Run: {errors} erro(s) encontrado(s). Verifique a fila.", "warning"
            )

    # ──────────────────────────────────── RF11: Resume interrupted pipeline ─ #

    def _check_for_interrupted_pipeline(self) -> None:
        """After loading config, offer to resume an interrupted pipeline (RF11)."""
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.db.models import CommandExecution, PipelineExecution
            from workflow_app.dialogs.resume_dialog import ResumeDialog, ResumeInfo
            from workflow_app.domain import CommandStatus
            from workflow_app.pipeline.pipeline_manager import PipelineManager
            from workflow_app.sdk.sdk_adapter import SDKAdapter

            adapter = SDKAdapter()
            pm = PipelineManager(
                signal_bus=signal_bus,
                sdk_adapter=adapter,
                session_factory=db_manager.session_factory,
            )
            interrupted_id = pm.check_resume()
            if interrupted_id is None:
                return

            with db_manager.session_factory() as session:
                pipeline = session.get(PipelineExecution, interrupted_id)
                if pipeline is None:
                    return

                cmds = (
                    session.query(CommandExecution)
                    .filter_by(pipeline_id=interrupted_id)
                    .order_by(CommandExecution.position)
                    .all()
                )
                completed = [c for c in cmds if c.status == CommandStatus.CONCLUIDO.value]
                uncertain = next(
                    (c for c in cmds if c.status == CommandStatus.INCERTO.value), None
                )
                pending = [c for c in cmds if c.status == CommandStatus.PENDENTE.value]

                info = ResumeInfo(
                    pipeline_exec_id=interrupted_id,
                    last_completed_command=completed[-1].command_name if completed else None,
                    uncertain_command=uncertain.command_name if uncertain else None,
                    pending_count=len(pending),
                    total_count=len(cmds),
                    completed_count=len(completed),
                    interrupted_at=pipeline.started_at or pipeline.created_at,
                )

            dlg = ResumeDialog(info, parent=self)
            result = dlg.exec()
            choice = dlg.user_choice()

            if result == ResumeDialog.RESULT_REEXECUTE:
                self._show_toast("Selecione o pipeline para retomar a execução.", "info")
            elif choice == ResumeDialog.RESULT_SKIP:
                self._show_toast("Pipeline interrompido ignorado.", "info")
            # RESULT_CANCEL: do nothing

        except Exception:
            pass  # resume check is non-critical; never block startup

    def _on_save_queue(self) -> None:
        """Salva snapshot da fila + metadados no storage dedicado queue_root.

        Grava em `output/wbs/pipeline-position/{slug}.json` via
        `write_queue_root` (atomic: tmp + os.replace). Consumido por
        `_restore_queue_from_storage` no startup.

        Para `last_command`, se o valor for `/model` ou `/clear`, anda para
        tras na fila buscando o ultimo comando real.
        """
        from datetime import datetime
        from pathlib import Path

        from workflow_app.services.queue_storage import write_queue_root

        if not app_state.has_config or not app_state.config:
            self._show_toast("Nenhum projeto carregado.", "warning")
            return

        commands = self._command_queue.get_queue_snapshot()
        template_label = self._command_queue.get_template_label_text()
        last_command = self._command_queue.get_last_command_text()

        if not commands and not template_label and not last_command:
            self._show_toast("Nada a salvar (fila vazia).", "warning")
            return

        # If last_command is /model or /clear, find the previous valid command
        _skip = ("/model", "/clear")
        if last_command:
            cmd_lower = last_command.strip().split("\n")[0].strip().lower()
            if any(cmd_lower.startswith(s) for s in _skip) or cmd_lower == "/clear":
                last_command = self._command_queue.find_last_valid_command()

        queue_root_path = Path(app_state.config.project_dir) / app_state.config.queue_root
        data = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "template_label": template_label,
            "last_command": last_command,
            "commands": commands,
        }

        try:
            write_queue_root(queue_root_path, data)
            self._show_toast(
                f"Fila salva: {len(commands)} comandos"
                + (f" — {template_label}" if template_label else ""),
                "success",
            )
        except Exception as exc:
            self._show_toast(f"Erro ao salvar fila: {exc}", "error")

    def _restore_queue_from_storage(self, config_path: str) -> None:
        """Restaura fila do storage dedicado queue_root, se existir."""
        from pathlib import Path

        from workflow_app.services.queue_storage import read_queue_root

        if not app_state.has_config or not app_state.config:
            return

        queue_root_path = Path(app_state.config.project_dir) / app_state.config.queue_root
        queue_data = read_queue_root(queue_root_path)

        commands = queue_data.get("commands")
        if not commands:
            return

        self._command_queue.restore_queue_snapshot(commands)

        saved_at = queue_data.get("saved_at", "")[:16].replace("T", " ")
        self._show_toast(
            f"Fila restaurada: {len(commands)} comandos (salva {saved_at})", "info"
        )

    def _unload_config(self) -> None:
        """Desvincula o projeto atual."""
        app_state.clear_config()
        self._settings.remove(self._SETTINGS_LAST_CONFIG)
        self._update_title(project_name=None)
        self._kanban_view.clear()
        self._module_detail_view.clear()
        signal_bus.config_unloaded.emit()
        signal_bus.toast_requested.emit("Projeto desvinculado", "info")

    # ─────────────────────────────────────────────── Kanban (T-036) ──── #

    def _load_kanban_from_config(self, config) -> None:
        """Populate the Kanban view with modules from the loaded project.

        Resolves ``{project_dir}/{wbs_root}`` and delegates to
        ``KanbanView.load``. Failures are logged; the kanban header surfaces
        the user-visible message itself.
        """
        try:
            wbs_abs = config.project_dir / config.wbs_root
        except (AttributeError, TypeError) as exc:
            logger.warning("Kanban: cannot resolve wbs_root: %s", exc)
            return
        self._kanban_view.load(wbs_abs)
        self._module_detail_view.set_wbs_root(wbs_abs)

    def _on_kanban_module_clicked(self, module_id: str) -> None:
        """Open the per-module detail view (T-038).

        Resolves ``module_id`` via ``ModuleDetailView.show_for`` and switches
        ``_view_stack`` to page 4. Failures surface via ``signal_bus`` toast.
        """
        try:
            self._module_detail_view.show_for(module_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("ModuleDetail: show_for(%s) failed", module_id)
            signal_bus.toast_requested.emit(
                f"Falha ao abrir módulo: {exc}", "error"
            )
            return
        self._view_stack.setCurrentIndex(3)

    def _update_title(self, project_name: str | None) -> None:
        """Atualiza a barra de título da janela.

        Com projeto: "{project_name} — SystemForge Desktop"
        Sem projeto: "SystemForge Desktop — Sem Projeto"
        """
        if project_name:
            self.setWindowTitle(f"{project_name} — SystemForge Desktop")
        else:
            self.setWindowTitle("SystemForge Desktop — Sem Projeto")


# ──────────────────────────────────────────────────────── Entry point ─── #


def main() -> None:
    from workflow_app.core.sentry_config import init_sentry
    from workflow_app.logger import setup_logging

    setup_logging()
    init_sentry()

    app = QApplication(sys.argv)
    app.setApplicationName("SystemForge Desktop")
    app.setOrganizationName("SystemForge")

    # Apply D19 Graphite Amber theme
    from workflow_app.theme import apply_theme
    apply_theme(app)

    # Load --wf-* design tokens (centralized colors/spacing/radius/typography).
    # Appended after apply_theme so theme defaults remain, with token overrides
    # for widgets that opt-in via objectName/property selectors.
    try:
        _tokens_path = Path(__file__).resolve().parent / "styles" / "tokens.qss"
        if _tokens_path.exists():
            _existing = app.styleSheet() or ""
            app.setStyleSheet(_existing + "\n" + _tokens_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - estilos nao podem quebrar boot
        logger.warning("Falha ao carregar styles/tokens.qss: %s", exc)

    # Window icon
    from pathlib import Path
    icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Initialize database (seeds factory templates on first run)
    from workflow_app.db.database_manager import db_manager
    db_manager.setup()

    # Verify SDK availability and authentication before opening main window
    from workflow_app.dialogs.critical_error_modal import CriticalErrorModal
    from workflow_app.errors import SDKNotAuthenticatedError, SDKNotAvailableError
    from workflow_app.sdk.sdk_adapter import SDKAdapter

    adapter = SDKAdapter()
    try:
        adapter.ensure_sdk_ready()
    except (SDKNotAvailableError, SDKNotAuthenticatedError) as exc:
        CriticalErrorModal.show_and_exit(exc)
        return  # sys.exit already called, prevents further execution

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
