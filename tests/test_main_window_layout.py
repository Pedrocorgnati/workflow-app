"""TASK-1 layout refactor regression tests.

Cobre AC-1.1, AC-1.3, AC-1.4: ToolboxHeader removido, queue-progress-ring
presente em listeners-frame, autocast e schedule-autocast btns expostos na
play bar do CommandQueueWidget.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from workflow_app.command_queue.command_queue_widget import (
    CommandQueueWidget,
    ResponsiveButtonFlowLayout,
)
from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.signal_bus import signal_bus
from workflow_app.widgets.queue_progress_ring import QueueProgressRing


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _find_by_testid(parent, testid: str):
    for w in parent.findChildren(QPushButton):
        if w.property("testid") == testid:
            return w
    return None


def _find_widget_by_testid(parent, testid: str):
    from PySide6.QtWidgets import QWidget

    for w in [parent, *parent.findChildren(QWidget)]:
        if w.property("testid") == testid:
            return w
    return None


def test_main_window_no_toolbox_header_attr(app):
    """AC-1.1: MainWindow nao deve mais ter _toolbox_header."""
    from workflow_app.main_window import MainWindow
    win = MainWindow()
    assert not hasattr(win, "_toolbox_header"), "ToolboxHeader nao foi removido"


def test_metrics_bar_has_queue_progress_ring(app):
    """Refactor 2026-05-17 power-bi-section: o ring continua owned por
    MetricsBar (signal pipelines preservados), mas nao e mais filho do
    listeners-frame — virou IRMAO dentro do power-bi-section montado em
    MainWindow._build_output_toolbar. Aqui (sem MainWindow), o ring fica
    sem parent ate ser reparenteado pelo PowerBiSection.
    """
    mb = MetricsBar()
    assert hasattr(mb, "_queue_progress_ring")
    assert isinstance(mb._queue_progress_ring, QueueProgressRing)
    assert mb._queue_progress_ring.parent() is None


def test_command_queue_has_autocast_buttons(app):
    """AC-1.4: autocast e schedule-autocast vivem agora na play bar."""
    cq = CommandQueueWidget()
    assert _find_by_testid(cq, "autocast-btn") is not None
    assert _find_by_testid(cq, "schedule-autocast-btn") is not None


def test_output_toolbar_left_splits_insertions_controls(app):
    """Refactor output-toolbar-left/center: as abas primarias (Workflow/LOOPs/
    Auxiliar) ficam no header output-toolbar-left; o bloco insertions-controls
    saiu do header (command_queue_widget.py: "insertions_bar NAO entra no
    tab_row").

    2026-07-20 ele passou a ser anexado como ULTIMA secao do
    queue-div-llm-routing; 2026-07-27 saiu tambem de la, porque o
    insertions_bar esta vazio e a secao entregava um label sobre nada, mais um
    divisor HLine orfao. Hoje o widget continua vivo como atributo publico,
    SEM parent, tanto em standalone quanto com a MainWindow completa.
    A aba Inserchoes (queue-tab-terminal-insertions) deixou de ser botao de aba
    (conteudo sempre visivel no center), entao nao e mais procurada aqui.
    """
    from workflow_app.main_window import MainWindow

    win = MainWindow()

    # Abas primarias permanecem no header output-toolbar-left.
    primary = win._command_queue._tab_bar_layout.parentWidget()
    assert primary is not None
    assert primary.property("testid") == "output-toolbar-left-primary-tabs"
    for tab in win._command_queue._sec_tabs[:3]:
        assert tab.parentWidget() is primary

    # insertions-controls NAO vive mais dentro do queue-div-llm-routing.
    insertions = win._command_queue.insertions_bar
    assert insertions is not None
    assert insertions.property("testid") == "output-toolbar-left-insertions-controls"
    assert insertions.parentWidget() is None, (
        "insertions_bar voltou a ser anexado a algum container"
    )
    llm_box = win._command_queue._llm_box
    assert llm_box.property("testid") == "queue-div-llm-routing"
    assert _find_widget_by_testid(
        llm_box, "output-toolbar-left-insertions-controls"
    ) is None
    # A coluna fecha nas tres secoes proprias: nada de divisor HLine orfao no
    # fim, que era o rastro visual da secao removida.
    layout = llm_box.layout()
    last = layout.itemAt(layout.count() - 1).widget()
    assert not isinstance(last, QFrame), "coluna termina em divisor orfao"
    assert last.property("testid") == "queue-div-flag"

    # output-toolbar-center guarda somente o conteudo da aba Inserchoes.
    content = win._command_queue.insertions_content
    center = content.parentWidget()
    assert center is not None
    assert center.property("testid") == "output-toolbar-center"
    center_layout = center.layout()
    assert center_layout.count() == 1
    assert center_layout.itemAt(0).widget() is content


def test_llm_routing_sections_are_vertical_label_over_controls(app):
    """queue-div-llm-routing: TRES secoes, label sempre no indice 0.

    Layout 2026-07-27: label no indice 0, bloco de controles no indice 1, e os
    controles seguem lado a lado ENTRE SI (QHBoxLayout interno). As duas
    primeiras secoes ficam em coluna (label EM CIMA dos controles); falha se
    qualquer uma delas voltar ao layout horizontal, que e o estado anterior.
    `queue-div-flag` e a excecao deliberada: label "Flag" na MESMA linha dos
    checkboxes (QHBoxLayout na secao).
    """
    cq = CommandQueueWidget()
    llm_box = cq._llm_box

    # (testid, texto do label, layout esperado da secao)
    sections = [
        ("queue-div-main-llm", "Main LLM:", QVBoxLayout),
        ("queue-div-parallel-worker", "Parallel Worker:", QVBoxLayout),
        ("queue-div-flag", "Flag", QHBoxLayout),
    ]

    # Exatamente tres secoes na coluna, na ordem declarada, com HLine entre
    # elas e nenhum divisor sobrando na ponta.
    layout = llm_box.layout()
    assert isinstance(layout, QVBoxLayout)
    found = [
        layout.itemAt(i).widget().property("testid")
        for i in range(layout.count())
        if not isinstance(layout.itemAt(i).widget(), QFrame)
    ]
    assert found == [testid for testid, _, _ in sections]

    for testid, label_text, expected_layout in sections:
        section = _find_widget_by_testid(llm_box, testid)
        assert section is not None, f"secao {testid} sumiu"
        section_layout = section.layout()
        assert isinstance(section_layout, expected_layout), (
            f"{testid} mudou de orientacao de layout"
        )
        assert section_layout.count() == 2, f"{testid} nao e label + controles"

        label = section_layout.itemAt(0).widget()
        assert isinstance(label, QLabel), f"{testid} nao tem label no indice 0"
        assert label.text() == label_text

        options = section_layout.itemAt(1).widget()
        assert options is not None, f"{testid} nao tem bloco de controles"
        assert isinstance(options.layout(), QHBoxLayout), (
            f"controles de {testid} deixaram de ficar lado a lado"
        )
        assert options.layout().count() >= 2


def test_output_toolbar_header_is_single_row_with_section_selector(app):
    """I3.1/I3.2: o header virou UMA linha + um stack de secoes.

    Linha unica: queue-div-llm-routing | output-toolbar-section-selector |
    output-toolbar-datatest-queue-stack. As tres divs que antes disputavam
    espaco em duas linhas viraram paginas de `output-toolbar-section-stack`,
    e nenhuma delas troca de testid (D1). Em 2026-07-27 entrou a QUARTA
    pagina (AGENTES), promovida de sub-aba do `queue-subtabs-insertions`, e
    logo depois a secao unica `MCP & BRAINSTORM` foi dissolvida: suas duas
    sub-abas internas subiram para as duas ULTIMAS posicoes do seletor (MCPs
    e BRAINSTORM), totalizando CINCO secoes.

    O stack e filho do proprio seletor (logo abaixo da fileira de botoes), nao
    um irmao full-width por baixo dos tres blocos da linha.
    """
    from workflow_app.main_window import MainWindow

    win = MainWindow()

    llm_box = win._command_queue._llm_box
    top_row = llm_box.parentWidget()
    assert top_row is not None
    top_layout = top_row.layout()
    assert top_layout.count() == 3, "a linha do header tem exatamente 3 blocos"
    assert top_layout.itemAt(0).widget() is llm_box

    selector = top_layout.itemAt(1).widget()
    assert selector.property("testid") == "output-toolbar-section-selector"
    assert (
        top_layout.itemAt(2).widget().property("testid")
        == "output-toolbar-datatest-queue-stack"
    )

    # Cinco botoes de select, na ordem e com os rotulos decididos (D14).
    expected = [
        ("output-toolbar-section-command-sequence", "COMMAND SEQUENCE"),
        ("output-toolbar-section-terminal-insertions", "TERMINAL INSERTIONS"),
        ("output-toolbar-section-agentes", "AGENTES"),
        ("output-toolbar-section-mcps", "MCPs"),
        ("output-toolbar-section-brainstorm", "BRAINSTORM"),
    ]
    btns = win._toolbar_section_btns
    assert [(b.property("testid"), b.text()) for b in btns] == expected
    for btn in btns:
        assert _find_by_testid(selector, btn.property("testid")) is btn

    stack = win._toolbar_section_stack
    assert stack.property("testid") == "output-toolbar-section-stack"
    # O stack mora DENTRO do seletor, imediatamente abaixo da fileira de
    # botoes — nao pendurado no container da linha.
    assert stack.parentWidget() is selector
    selector_layout = selector.layout()
    assert selector_layout.count() == 2, "fileira de botoes + stack"
    assert selector_layout.itemAt(1).widget() is stack
    assert stack.count() == 5
    assert stack.widget(0) is win._command_queue.header_widget
    assert stack.widget(0).property("testid") == "output-toolbar-left"
    assert stack.widget(1).property("testid") == "output-toolbar-center"
    assert stack.widget(2).property("testid") == "output-toolbar-agentes"
    assert stack.widget(3).property("testid") == "output-toolbar-mcp"
    assert stack.widget(4).property("testid") == "output-toolbar-brainstorm"
    # A pagina 2 hospeda a aba 'Agentes' com o testid original preservado (D1).
    personas = win._command_queue.personas_content
    assert personas.property("testid") == "queue-subtab-insertions-personas"
    assert personas.parentWidget() is stack.widget(2)

    # Boot fixo em COMMAND SEQUENCE (D14) e troca de pagina pelo clique.
    assert stack.currentIndex() == 0
    for i in range(1, 5):
        btns[i].click()
        assert stack.currentIndex() == i
    btns[0].click()
    assert stack.currentIndex() == 0


def test_mcps_e_brainstorm_sao_secoes_de_primeiro_nivel(app):
    """A secao unica `MCP & BRAINSTORM` foi dissolvida (2026-07-27).

    Suas duas sub-abas internas viraram as duas ULTIMAS secoes do seletor, com
    o MESMO conteudo de antes: MCPs renderiza as personas/acoes MCP, BRAINSTORM
    renderiza `brainstorm-buttons-grid`. A tab bar interna que fazia o segundo
    nivel (`output-progress-tabbar` + `output-mcp-tab-*`) nao existe mais.
    """
    from workflow_app.main_window import MainWindow

    win = MainWindow()

    # O botao e a secao dissolvida sumiram por completo do seletor.
    selector = win._toolbar_section_selector
    assert _find_by_testid(selector, "output-toolbar-section-mcp-brainstorm") is None
    for testid in ("output-mcp-tab-mcps", "output-mcp-tab-brainstorm"):
        assert _find_by_testid(win, testid) is None
    assert _find_widget_by_testid(selector, "output-progress-tabbar") is None

    stack = win._toolbar_section_stack
    mcps_btn = _find_by_testid(selector, "output-toolbar-section-mcps")
    brainstorm_btn = _find_by_testid(selector, "output-toolbar-section-brainstorm")

    # Cada botao mostra a moldura da sua secao, e o conteudo herdado esta la.
    mcps_btn.click()
    mcps_column = stack.currentWidget()
    assert mcps_column.property("testid") == "output-toolbar-mcp"
    for action_id in ("main", "parallel", "dual"):
        assert _find_by_testid(mcps_column, f"output-mcp-action-{action_id}")
    assert _find_widget_by_testid(mcps_column, "output-mcp-persona-checkboxes")

    brainstorm_btn.click()
    brainstorm_column = stack.currentWidget()
    assert brainstorm_column.property("testid") == "output-toolbar-brainstorm"
    assert _find_widget_by_testid(brainstorm_column, "brainstorm-buttons-grid")

    # As duas molduras sao irmas no stack: nenhuma vive dentro da outra.
    assert _find_widget_by_testid(mcps_column, "output-toolbar-brainstorm") is None
    assert _find_widget_by_testid(brainstorm_column, "output-toolbar-mcp") is None


def test_output_toolbar_left_subtabs_use_responsive_flow(app):
    """Subtabs internas quebram linha e compactam sem renderizar mais de 4 linhas."""
    from PySide6.QtWidgets import QWidget

    cq = CommandQueueWidget()
    assert isinstance(cq._subtab_paths_layout, ResponsiveButtonFlowLayout)
    assert isinstance(cq._subtab_prompts_layout, ResponsiveButtonFlowLayout)
    assert isinstance(cq._subtab_rules_layout, ResponsiveButtonFlowLayout)

    path_buttons = [QPushButton("path-a"), QPushButton("path-b")]
    second_row_buttons = [QPushButton("repo rules")]
    cq.populate_paths_subtab(path_buttons, second_row_buttons)
    assert cq._subtab_paths_layout.count() == 3

    parent = QWidget()
    layout = ResponsiveButtonFlowLayout(parent, spacing=4, max_lines=4)
    for i in range(18):
        btn = QPushButton(f"btn-{i}")
        btn.setFixedHeight(28)
        btn.setMinimumWidth(64)
        layout.addWidget(btn)

    layout.setGeometry(QRect(0, 0, 180, 200))
    y_positions = {
        layout.itemAt(i).widget().geometry().y()
        for i in range(layout.count())
    }
    widths = [
        layout.itemAt(i).widget().geometry().width()
        for i in range(layout.count())
    ]
    max_right = max(
        layout.itemAt(i).widget().geometry().right()
        for i in range(layout.count())
    )

    assert len(y_positions) <= 4
    assert min(widths) < 64
    assert max_right < 180


def test_personas_flow_ajusta_botoes_por_linha_conforme_largura(app):
    """34 personas: largura do label e quebra responsiva.

    O contrato antigo era teto de 4 linhas com compactacao dos botoes. Agora o
    flow roda sem teto: cada botao fica com a largura do proprio label e a
    quantidade por linha acompanha a largura disponivel — janela maior, mais
    botoes por linha.

    Desde 2026-07-27 os tres utilitarios (`+`, gear, update) sairam do flow e
    vivem na coluna `queue-subtab-insertions-personas-utils` no fim da aba, so
    personas continuam aqui.
    """
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    layout = win._command_queue._subtab_personas_layout
    win._command_queue._personas_filter_bar.setCurrentIndex(0)
    win._command_queue._apply_persona_filter()

    # 34 personas (utilitarios ficam fora do flow)
    assert layout.count() == 34
    assert win._command_queue._subtab_personas_utils_layout.count() == 3
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert all(widget is not None for widget in widgets)

    def render(width: int) -> list[int]:
        layout.setGeometry(QRect(0, 0, width, layout.heightForWidth(width)))
        assert max(widget.geometry().right() for widget in widgets) < width
        return sorted({widget.geometry().y() for widget in widgets})

    narrow_lines = render(480)
    medium_lines = render(640)
    wide_lines = render(1200)

    assert len(wide_lines) < len(medium_lines) < len(narrow_lines)

    persona_widgets = [
        widget for widget in widgets
        if str(widget.property("testid")).startswith("queue-btn-persona-")
        and not str(widget.property("testid")).startswith("queue-btn-personas-")
    ]
    assert len(persona_widgets) == 34
    assert all(widget.accessibleName() for widget in persona_widgets)

    # 2026-07-27: a largura deixou de acompanhar o label e passou a ser
    # padronizada em `_PERSONA_BTN_WIDTH` para TODOS os botoes da aba. O flow
    # continua responsivo (quantos cabem por linha varia com a largura), so o
    # item virou uniforme.
    from workflow_app.main_window import _PERSONA_BTN_WIDTH

    assert {widget.geometry().width() for widget in persona_widgets} == {
        _PERSONA_BTN_WIDTH
    }

    # Gap vertical de 1px entre linhas (altura da linha = maior botao dela).
    line_height = max(widget.geometry().height() for widget in widgets)
    assert wide_lines[1] - wide_lines[0] == line_height + 1


def test_attachment_row_keeps_visible_controls_non_overlapping(app):
    """Project/loop/brainstorm attachments stay split and non-overlapping."""
    from workflow_app.config.app_state import app_state
    from workflow_app.main_window import MainWindow

    app_state.clear_all()
    win = MainWindow()
    project_name = "project-with-a-very-long-name-for-small-viewports"
    loop_name = "loop-with-a-very-long-name-for-small-viewports"
    win._metrics_bar._apply_project_loaded(project_name)
    win._metrics_bar._apply_loop_loaded(loop_name)
    win.resize(640, 480)
    win.show()
    app.processEvents()

    assert win._metrics_bar._project_name_lbl.toolTip() == project_name
    assert win._metrics_bar._loop_name_lbl.toolTip() == loop_name
    assert win._metrics_bar._project_name_lbl.maximumWidth() <= 180
    assert win._metrics_bar._loop_name_lbl.maximumWidth() <= 180

    attachments_block = win._attachments_block
    project_row = win._attachments_project_row
    loop_row = win._attachments_loop_row
    brainstorm_row = win._attachments_brainstorm_row
    actions_row = win._clear_queue_btn.parentWidget()

    assert attachments_block is not None
    assert project_row is not None
    assert loop_row is not None
    assert brainstorm_row is not None
    assert actions_row is not None
    assert project_row.parentWidget() is attachments_block
    assert loop_row.parentWidget() is attachments_block
    assert brainstorm_row.parentWidget() is attachments_block
    assert actions_row.parentWidget() is not attachments_block

    row_tops = {project_row.geometry().top(), loop_row.geometry().top(), brainstorm_row.geometry().top()}
    assert len(row_tops) == 3, "anexos devem ocupar linhas semanticas separadas"

    for row in (project_row, loop_row, brainstorm_row):
        visible_items = []
        layout = row.layout()
        for idx in range(layout.count()):
            item = layout.itemAt(idx)
            widget = item.widget()
            if widget is not None and widget.isVisible():
                visible_items.append(widget)

        previous_right = -1
        for widget in visible_items:
            geom = widget.geometry()
            assert geom.left() > previous_right
            previous_right = geom.right()


def test_autocast_toggle_signal_proxied(app):
    """AC-1.4: clicar autocast na play bar emite autocast_toggle_requested."""
    cq = CommandQueueWidget()
    received: list[bool] = []
    signal_bus.autocast_toggle_requested.connect(received.append)
    btn = _find_by_testid(cq, "autocast-btn")
    btn.setChecked(True)
    btn.setChecked(False)
    assert received[-2:] == [True, False]


def test_schedule_autocast_signal_proxied(app):
    """AC-1.4: clicar agendar emite schedule_autocast_requested."""
    cq = CommandQueueWidget()
    received: list[int] = []
    signal_bus.schedule_autocast_requested.connect(lambda: received.append(1))
    btn = _find_by_testid(cq, "schedule-autocast-btn")
    btn.click()
    assert received[-1] == 1
