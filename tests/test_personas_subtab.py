"""Regression tests for the PERSONAS insertions sub-aba in MainWindow.

Cobre: (1) um botao por persona REAL de ai-forge/MCP/agents/ que cola o path
no terminal; (2) o botao 'update' 1:1 (queue-btn-personas-update) que re-varre
a pasta e cria botao para personas novas ao vivo, sem reiniciar o app;
(3) o botao create 1:1 (queue-btn-personas-create) verde com '+' sempre
na primeira posicao e fora do prefixo filtravel queue-btn-persona-.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPushButton

from workflow_app.command_queue.command_queue_widget import (
    PERSONA_FILTER_ALL_LABEL,
    PERSONA_FILTER_CATEGORIES,
    PERSONA_FILTER_DEFAULT,
)
from workflow_app.main_window import (
    _PERSONA_BTN_WIDTH,
    _PERSONAS_UTIL_BTN_SIZE,
)
from workflow_app.signal_bus import signal_bus


def _new_window(qtbot):
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _buttons_by_testid_prefix(win, prefix: str) -> dict[str, QPushButton]:
    out: dict[str, QPushButton] = {}
    for btn in win.findChildren(QPushButton):
        tid = btn.property("testid")
        if isinstance(tid, str) and tid.startswith(prefix):
            out[tid] = btn
    return out


def _button_by_testid(win, testid: str) -> QPushButton:
    for btn in win.findChildren(QPushButton):
        if btn.property("testid") == testid:
            return btn
    raise AssertionError(f"botao nao encontrado: {testid}")


def test_personas_subtab_has_one_button_per_real_persona(qtbot):
    win = _new_window(qtbot)

    expected = {slug for slug, _ in win._scan_persona_files()}
    assert expected, "esperava ao menos uma persona real em ai-forge/MCP/agents/"

    persona_btns = _buttons_by_testid_prefix(win, "queue-btn-persona-")
    rendered = {tid[len("queue-btn-persona-"):] for tid in persona_btns}

    assert rendered == expected


def test_personas_is_a_header_section_not_an_insertions_subtab(qtbot):
    """2026-07-27: 'Agentes' saiu do queue-subtabs-insertions e virou a 4a
    secao do output-toolbar-section-selector."""
    win = _new_window(qtbot)

    tabs = win._command_queue._insertions_subtabs
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert "Agentes" not in labels
    assert "PERSONAS" not in labels

    btn = _button_by_testid(win, "output-toolbar-section-agentes")
    assert btn.text() == "AGENTES"
    stack = win._toolbar_section_stack
    btn.click()
    assert stack.currentWidget().property("testid") == "output-toolbar-agentes"


def test_persona_buttons_use_user_friendly_labels(qtbot):
    win = _new_window(qtbot)

    expected = {
        "queue-btn-persona-analista-delegador-rules": "Delegador",
        "queue-btn-persona-controversial-devils-advocate-rules": "Controversial",
        "queue-btn-persona-executar-task-rules": "Executor",
        "queue-btn-persona-code-debugger": "Debugger",
        "queue-btn-persona-scaffolds-blueprints-updater": "Scaffold Update",
        "queue-btn-persona-questioner-rules": "Questionador",
        "queue-btn-persona-ux-ui-specialist": "UX/UI",
        "queue-btn-persona-performance-engineer": "Performance",
    }
    for testid, label in expected.items():
        btn = _button_by_testid(win, testid)
        assert btn.text() == label
        assert "-rules" not in btn.text()


def test_persona_buttons_share_one_fixed_width(qtbot):
    """2026-07-27: todos os botoes de `queue-subtab-insertions-personas` medem
    o mesmo (120px), independente do tamanho do label."""
    win = _new_window(qtbot)

    btns = _buttons_by_testid_prefix(win, "queue-btn-persona-")
    assert btns, "a aba precisa ter personas para o contrato valer"
    assert {b.width() for b in btns.values()} == {_PERSONA_BTN_WIDTH}


def test_persona_button_pastes_relative_path(qtbot, monkeypatch):
    win = _new_window(qtbot)

    captured: list[str] = []
    monkeypatch.setattr(win, "_publish_to_terminal", lambda text: captured.append(text))

    slug, rel_path = win._scan_persona_files()[0]
    btn = _button_by_testid(win, f"queue-btn-persona-{slug}")
    btn.click()

    assert captured == [rel_path]
    assert rel_path == str(Path("ai-forge/MCP/agents") / f"{slug}.md")


def test_four_new_persona_shortcuts_publish_exact_paths(qtbot, monkeypatch):
    win = _new_window(qtbot)
    captured: list[str] = []
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(win, "_publish_to_terminal", lambda text: captured.append(text))

    def _capture_toast(message: str, level: str) -> None:
        toasts.append((message, level))

    slugs = (
        "scaffolds-blueprints-updater",
        "questioner-rules",
        "ux-ui-specialist",
        "performance-engineer",
    )
    signal_bus.toast_requested.connect(_capture_toast)
    try:
        for slug in slugs:
            btn = _button_by_testid(win, f"queue-btn-persona-{slug}")
            assert btn.accessibleName()
            btn.click()
    finally:
        signal_bus.toast_requested.disconnect(_capture_toast)

    assert captured == [f"ai-forge/MCP/agents/{slug}.md" for slug in slugs]
    assert toasts == [
        (
            "Persona copiada e colada no terminal: "
            f"ai-forge/MCP/agents/{slug}.md",
            "info",
        )
        for slug in slugs
    ]


def test_personas_create_button_is_green_square_with_plus(qtbot):
    win = _new_window(qtbot)

    btn = _button_by_testid(win, "queue-btn-personas-create")
    # 1:1 no lado canonico dos utilitarios (34 -> 24, -30% em 2026-07-27).
    assert btn.width() == _PERSONAS_UTIL_BTN_SIZE
    assert btn.height() == _PERSONAS_UTIL_BTN_SIZE
    assert "#16A34A" in btn.styleSheet()  # verde
    assert btn.text() == "+"
    assert btn.accessibleName() == "Criar agente"
    assert "primeira posicao" in btn.toolTip()


def test_personas_create_button_is_first_widget_in_utils_div(qtbot):
    win = _new_window(qtbot)

    layout = win._command_queue._subtab_personas_utils_layout
    first = layout.itemAt(0).widget()
    assert first is not None
    assert first.property("testid") == "queue-btn-personas-create"
    # Unico no flow (e no MainWindow via findChildren helper).
    create_btns = [
        b for b in win.findChildren(QPushButton)
        if b.property("testid") == "queue-btn-personas-create"
    ]
    assert len(create_btns) == 1


def test_personas_create_is_not_a_persona_button(qtbot):
    """queue-btn-personas-create NAO usa o prefixo filtravel queue-btn-persona-."""
    win = _new_window(qtbot)
    persona_btns = _buttons_by_testid_prefix(win, "queue-btn-persona-")
    assert "queue-btn-personas-create" not in persona_btns
    # startswith("queue-btn-persona-") casa com "queue-btn-persona-" (singular)
    # mas NAO com "queue-btn-personas-create" porque apos "persona" vem "s".
    # Garante o contrato: create e utilitario plural, fora da contagem de personas.
    for tid in persona_btns:
        assert tid.startswith("queue-btn-persona-")
        assert not tid.startswith("queue-btn-personas-")


def test_personas_update_button_is_green_square_with_icon(qtbot):
    win = _new_window(qtbot)

    btn = _button_by_testid(win, "queue-btn-personas-update")
    assert btn.width() == _PERSONAS_UTIL_BTN_SIZE
    assert btn.height() == _PERSONAS_UTIL_BTN_SIZE
    assert "#16A34A" in btn.styleSheet()  # verde
    assert btn.accessibleName() == "Recarregar personas"
    assert "mantem este botao sempre no final" in btn.toolTip()
    # Icone (refresh.svg) ou fallback textual de refresh.
    assert (not btn.icon().isNull()) or btn.text() == "⟳"


def test_personas_update_button_is_last_widget_in_utils_div(qtbot):
    win = _new_window(qtbot)

    layout = win._command_queue._subtab_personas_utils_layout
    last = layout.itemAt(layout.count() - 1).widget()
    assert last.property("testid") == "queue-btn-personas-update"


def test_personas_utils_div_is_the_right_column_of_the_agentes_row(qtbot):
    """A div dos 3 utilitarios e a coluna DIREITA da row `output-toolbar-agentes`,
    fora do grupo de botoes, empilhada em coluna e ocupando so o espaco necessario."""
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

    win = _new_window(qtbot)
    cq = win._command_queue

    div = cq._personas_utils_div
    assert div is cq.personas_utils_div
    assert div.property("testid") == "queue-subtab-insertions-personas-utils"
    assert isinstance(div.layout(), QVBoxLayout), "os 3 botoes ficam em coluna"

    # Exatamente os 3 utilitarios, nenhuma persona.
    tids = [
        div.layout().itemAt(i).widget().property("testid")
        for i in range(div.layout().count())
    ]
    assert tids == [
        "queue-btn-personas-create",
        "queue-btn-personas-config",
        "queue-btn-personas-update",
    ]

    # Row (nao coluna) com o conteudo da aba a esquerda e a div encostada a
    # direita: ela e o ULTIMO item de `output-toolbar-agentes`, alinhada a
    # direita e sem stretch (todo o stretch e do conteudo).
    from PySide6.QtWidgets import QSizePolicy

    from PySide6.QtCore import Qt

    agentes = div.parentWidget()
    assert agentes.property("testid") == "output-toolbar-agentes"
    row = agentes.layout()
    assert isinstance(row, QHBoxLayout), "agentes e uma row"
    assert row.itemAt(0).widget() is cq.personas_content
    assert row.itemAt(row.count() - 1).widget() is div
    assert row.stretch(0) == 1
    assert row.stretch(row.count() - 1) == 0
    assert row.itemAt(row.count() - 1).alignment() & Qt.AlignmentFlag.AlignRight

    # A div saiu de dentro da aba: nem ela nem o divisor antigo continuam la.
    outer = cq.personas_content.layout()
    assert all(
        outer.itemAt(i).widget() is not div for i in range(outer.count())
    )

    # So o espaco necessario: uma coluna de um botao de largura, nunca a faixa
    # inteira da row.
    assert div.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed
    assert div.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert div.sizeHint().width() < 60
    assert div.sizeHint().height() > div.sizeHint().width()  # coluna, nao row

    # Nenhum utilitario sobrou no flow filtravel.
    flow_tids = {
        cq._subtab_personas_layout.itemAt(i).widget().property("testid")
        for i in range(cq._subtab_personas_layout.count())
        if cq._subtab_personas_layout.itemAt(i).widget() is not None
    }
    assert not flow_tids & set(tids)


def test_personas_update_adds_button_for_new_persona(qtbot, tmp_path, monkeypatch):
    win = _new_window(qtbot)

    before = set(_buttons_by_testid_prefix(win, "queue-btn-persona-"))

    # Aponta o scan para um diretorio temporario contendo as personas reais
    # ja renderizadas + uma persona nova. _build_persona_buttons pula as ja
    # presentes (set de slugs), entao apenas a nova deve virar botao.
    fake_dir = tmp_path / "agents"
    fake_dir.mkdir()
    new_slug = "zz-new-test-persona"
    (fake_dir / f"{new_slug}.md").write_text(
        "---\n"
        f"slug: {new_slug}\n"
        "name: Persona de Teste\n"
        "status: active\n"
        "provider_support: [claude, codex, kimi]\n"
        f"agent_path: {fake_dir}/{new_slug}.md\n"
        "---\n\n# corpo\n",
        encoding="utf-8",
    )

    def _fake_scan():
        return [(new_slug, str(fake_dir / f"{new_slug}.md"))]

    monkeypatch.setattr(win, "_scan_persona_files", _fake_scan)

    win._on_personas_update_clicked()

    after = set(_buttons_by_testid_prefix(win, "queue-btn-persona-"))
    added = after - before
    assert added == {f"queue-btn-persona-{new_slug}"}

    # A persona nova entra no flow; os utilitarios seguem na div em coluna.
    flow = win._command_queue._subtab_personas_layout
    flow_last = flow.itemAt(flow.count() - 1).widget()
    assert flow_last.property("testid") == f"queue-btn-persona-{new_slug}"
    utils = win._command_queue._subtab_personas_utils_layout
    assert utils.itemAt(0).widget().property("testid") == "queue-btn-personas-create"
    assert (
        utils.itemAt(utils.count() - 1).widget().property("testid")
        == "queue-btn-personas-update"
    )


def test_personas_update_is_idempotent_when_nothing_new(qtbot, monkeypatch):
    win = _new_window(qtbot)

    before = set(_buttons_by_testid_prefix(win, "queue-btn-persona-"))
    # scan retorna as mesmas personas ja renderizadas -> nenhum botao novo.
    win._on_personas_update_clicked()
    after = set(_buttons_by_testid_prefix(win, "queue-btn-persona-"))

    assert after == before


# ── Gear de configuracao dos agentes (sub-aba 'Agentes') ──────────────────── #


def test_personas_subtab_has_config_gear_before_update(qtbot):
    win = _new_window(qtbot)

    layout = win._command_queue._subtab_personas_utils_layout
    tids = [
        layout.itemAt(i).widget().property("testid")
        for i in range(layout.count())
        if layout.itemAt(i).widget() is not None
    ]
    assert tids[0] == "queue-btn-personas-create", "create deve ser o primeiro"
    assert "queue-btn-personas-config" in tids, "gear de agentes ausente na aba"
    # update permanece o ultimo widget da coluna; o gear vem antes dele.
    assert tids[-1] == "queue-btn-personas-update"
    assert tids.index("queue-btn-personas-create") < tids.index(
        "queue-btn-personas-config"
    )
    assert tids.index("queue-btn-personas-config") < tids.index(
        "queue-btn-personas-update"
    )


def test_personas_config_gear_is_not_a_persona_button(qtbot):
    # Os testids utilitarios plurais NAO contaminam a contagem de personas
    # (prefixo queue-btn-persona- singular).
    win = _new_window(qtbot)
    persona_btns = _buttons_by_testid_prefix(win, "queue-btn-persona-")
    assert "queue-btn-personas-create" not in persona_btns
    assert "queue-btn-personas-config" not in persona_btns
    assert "queue-btn-personas-update" not in persona_btns


def test_personas_config_dialog_lists_all_current_agents(qtbot):
    from workflow_app.main_window import PersonasConfigDialog

    win = _new_window(qtbot)
    entries = [
        {
            "slug": slug,
            "rel_path": rel,
            "label": win._persona_button_label(slug, rel),
            "default_label": win._persona_button_label(
                slug, rel, ignore_overrides=True
            ),
        }
        for slug, rel in win._scan_persona_files()
    ]
    dlg = PersonasConfigDialog(entries, win)
    qtbot.addWidget(dlg)

    listed = {slug for slug, _default, _le in dlg._rows}
    assert listed == {slug for slug, _ in win._scan_persona_files()}
    # Sem edicao, collect() nao produz override.
    assert dlg.collect() == {}


def test_personas_config_label_override_applies_to_button(qtbot, monkeypatch):
    from PySide6.QtCore import QSettings

    # QSettings persiste em disco — preserva e restaura o valor previo para
    # nao vazar o override entre runs (o 1o agente alfabetico e checado por
    # test_persona_buttons_use_user_friendly_labels).
    _settings = QSettings("systemForge", "workflow-app")
    _prev = _settings.value("personas/label_overrides", None)
    try:
        win = _new_window(qtbot)
        slug, rel = win._scan_persona_files()[0]

        # Simula o modal: usuario renomeia o primeiro agente.
        monkeypatch.setattr(
            "workflow_app.main_window.PersonasConfigDialog.exec",
            lambda self: 1,  # QDialog.DialogCode.Accepted
        )
        monkeypatch.setattr(
            "workflow_app.main_window.PersonasConfigDialog.collect",
            lambda self: {slug: "Renomeado X"},
        )

        win._open_personas_config_dialog()

        btn = _button_by_testid(win, f"queue-btn-persona-{slug}")
        assert btn.text() == "Renomeado X"
        assert win._persona_label_overrides.get(slug) == "Renomeado X"
    finally:
        if _prev is None:
            _settings.remove("personas/label_overrides")
        else:
            _settings.setValue("personas/label_overrides", _prev)


def test_prompts_gear_lives_in_prompts_subtab_not_corner(qtbot):
    win = _new_window(qtbot)

    # Nao e mais cornerWidget compartilhado das sub-abas.
    assert win._command_queue._insertions_subtabs.cornerWidget() is None

    # Vive como widget do flow da sub-aba PROMPTS.
    layout = win._command_queue._subtab_prompts_layout
    tids = [
        layout.itemAt(i).widget().property("testid")
        for i in range(layout.count())
        if layout.itemAt(i).widget() is not None
    ]
    assert "toolbar-prompts-config-gear" in tids


def _subtab_testids(win, attr: str) -> list[str]:
    layout = getattr(win._command_queue, attr)
    return [
        layout.itemAt(i).widget().property("testid")
        for i in range(layout.count())
        if layout.itemAt(i).widget() is not None
    ]


def test_asq_user_button_lives_in_cmd_subtab_not_prompts(qtbot):
    win = _new_window(qtbot)

    cmd_tids = _subtab_testids(win, "_subtab_cmd_layout")
    prompts_tids = _subtab_testids(win, "_subtab_prompts_layout")

    # Migrou de PROMPTS para CMD (2026-06-22).
    assert "output-btn-asq-user" in cmd_tids
    assert "output-btn-asq-user" not in prompts_tids


# ── Barra de filtros por categoria da sub-aba 'Agentes' ───────────────────── #


def _persona_filter_bar(win):
    return win._command_queue._personas_filter_bar


def _set_persona_filter(win, category: str) -> int:
    """Seleciona a aba de filtro `category` (ou 'All') e retorna o indice."""
    bar = _persona_filter_bar(win)
    if category == PERSONA_FILTER_ALL_LABEL:
        idx = 0
    else:
        idx = 1 + list(PERSONA_FILTER_CATEGORIES).index(category)
    bar.setCurrentIndex(idx)
    return idx


def test_personas_filter_bar_has_all_first_then_categories(qtbot):
    win = _new_window(qtbot)
    bar = _persona_filter_bar(win)

    assert bar.property("testid") == "queue-personas-filter-bar"
    labels = [bar.tabText(i) for i in range(bar.count())]
    # "All" sempre na primeira posicao, seguido das categorias na ordem canonica.
    assert labels[0] == PERSONA_FILTER_ALL_LABEL == "All"
    assert tuple(labels[1:]) == PERSONA_FILTER_CATEGORIES


def test_every_persona_button_has_valid_category(qtbot):
    win = _new_window(qtbot)

    persona_btns = _buttons_by_testid_prefix(win, "queue-btn-persona-")
    assert persona_btns, "esperava ao menos um botao de persona"
    for tid, btn in persona_btns.items():
        cat = btn.property("persona_category")
        assert cat in PERSONA_FILTER_CATEGORIES, f"{tid} -> categoria invalida {cat!r}"


def test_persona_category_known_mappings(qtbot):
    win = _new_window(qtbot)

    expected = {
        "queue-btn-persona-search-in-rules": "Research",
        "queue-btn-persona-search-out-rules": "Research",
        "queue-btn-persona-search-forge-rules": "Research",
        "queue-btn-persona-study-researcher-rules": "Research",
        "queue-btn-persona-visual-designer-rules": "Design",
        "queue-btn-persona-layout-architect-rules": "Design",
        "queue-btn-persona-seo-specialist": "Design",
        "queue-btn-persona-criar-task-rules": "Build",
        "queue-btn-persona-executar-task-rules": "Build",
        "queue-btn-persona-revisar-qa-rules": "Review",
        "queue-btn-persona-code-debugger": "Review",
        "queue-btn-persona-hardening-engineer-rules": "Review",
        "queue-btn-persona-orquestrador-pdca-rules": "Plan",
        "queue-btn-persona-analista-delegador-rules": "Plan",
        "queue-btn-persona-billing-scpecialist": "specialists",
        "queue-btn-persona-auth-security-specialist": "specialists",
        "queue-btn-persona-deployment-reliability-specialist": "specialists",
        "queue-btn-persona-soft-engineer": "specialists",
        "queue-btn-persona-engenheiro-solucionador": "specialists",
        "queue-btn-persona-scaffolds-blueprints-updater": "Build",
        "queue-btn-persona-questioner-rules": "Review",
        "queue-btn-persona-ux-ui-specialist": "Design",
        "queue-btn-persona-performance-engineer": "specialists",
    }
    for tid, cat in expected.items():
        btn = _button_by_testid(win, tid)
        assert btn.property("persona_category") == cat, tid


def test_four_new_personas_follow_their_exact_filters(qtbot):
    win = _new_window(qtbot)
    expected = {
        "queue-btn-persona-scaffolds-blueprints-updater": "Build",
        "queue-btn-persona-questioner-rules": "Review",
        "queue-btn-persona-ux-ui-specialist": "Design",
        "queue-btn-persona-performance-engineer": "specialists",
    }
    try:
        for active_category in expected.values():
            _set_persona_filter(win, active_category)
            for testid, category in expected.items():
                button = _button_by_testid(win, testid)
                assert button.isHidden() is (category != active_category), testid

            assert not _button_by_testid(win, "queue-btn-personas-create").isHidden()
            assert not _button_by_testid(win, "queue-btn-personas-config").isHidden()
            assert not _button_by_testid(win, "queue-btn-personas-update").isHidden()
    finally:
        _set_persona_filter(win, PERSONA_FILTER_ALL_LABEL)


def test_filter_hides_non_matching_personas_keeps_utilities(qtbot):
    win = _new_window(qtbot)
    try:
        _set_persona_filter(win, "Research")

        persona_btns = _buttons_by_testid_prefix(win, "queue-btn-persona-")
        for tid, btn in persona_btns.items():
            cat = btn.property("persona_category")
            if cat == "Research":
                assert not btn.isHidden(), f"{tid} deveria estar visivel"
            else:
                assert btn.isHidden(), f"{tid} deveria estar oculto sob filtro Research"

        # Create, gear de config e botao update nunca sao filtrados.
        assert not _button_by_testid(win, "queue-btn-personas-create").isHidden()
        assert not _button_by_testid(win, "queue-btn-personas-config").isHidden()
        assert not _button_by_testid(win, "queue-btn-personas-update").isHidden()
        # create permanece o primeiro widget da coluna de utilitarios.
        layout = win._command_queue._subtab_personas_utils_layout
        first = layout.itemAt(0).widget()
        assert first.property("testid") == "queue-btn-personas-create"
    finally:
        _set_persona_filter(win, PERSONA_FILTER_ALL_LABEL)


def test_all_filter_shows_every_persona(qtbot):
    win = _new_window(qtbot)
    # Filtra e depois volta para 'All' — todos os botoes devem reaparecer.
    _set_persona_filter(win, "Review")
    _set_persona_filter(win, PERSONA_FILTER_ALL_LABEL)

    for tid, btn in _buttons_by_testid_prefix(win, "queue-btn-persona-").items():
        assert not btn.isHidden(), f"{tid} deveria estar visivel em 'All'"


def test_unknown_persona_falls_back_to_default_category(qtbot):
    win = _new_window(qtbot)
    assert win._infer_persona_category("zz-totally-unknown") == PERSONA_FILTER_DEFAULT
    assert win._persona_category("zz-totally-unknown", "x.md") == PERSONA_FILTER_DEFAULT
    # Inferencia por palavra-chave para personas fora do mapa explicito.
    assert win._infer_persona_category("zz-search-probe") == "Research"
    assert win._infer_persona_category("zz-layout-probe") == "Design"
    assert win._infer_persona_category("zz-audit-probe") == "Review"
    assert win._infer_persona_category("zz-orquestrador-probe") == "Plan"
    assert win._infer_persona_category("zz-billing-specialist") == "specialists"
    assert win._infer_persona_category("zz-deploy-specialist") == "specialists"
    assert win._infer_persona_category("zz-engenheiro-probe") == "specialists"


def test_specialists_filter_shows_new_specialist_agents(qtbot):
    win = _new_window(qtbot)
    try:
        _set_persona_filter(win, "specialists")

        expected_visible = {
            "queue-btn-persona-billing-scpecialist",
            "queue-btn-persona-auth-security-specialist",
            "queue-btn-persona-deployment-reliability-specialist",
            "queue-btn-persona-soft-engineer",
            "queue-btn-persona-engenheiro-solucionador",
            "queue-btn-persona-performance-engineer",
        }
        for tid, btn in _buttons_by_testid_prefix(win, "queue-btn-persona-").items():
            if tid in expected_visible:
                assert not btn.isHidden(), f"{tid} deveria estar visivel"
            elif btn.property("persona_category") == "specialists":
                assert not btn.isHidden(), f"{tid} deveria estar visivel"
            else:
                assert btn.isHidden(), f"{tid} deveria estar oculto sob filtro specialists"
    finally:
        _set_persona_filter(win, PERSONA_FILTER_ALL_LABEL)


def test_new_persona_via_update_respects_active_filter(qtbot, tmp_path, monkeypatch):
    win = _new_window(qtbot)
    try:
        _set_persona_filter(win, "Research")

        fake_dir = tmp_path / "agents"
        fake_dir.mkdir()
        research_slug = "zz-search-probe-rules"
        review_slug = "zz-audit-probe-rules"
        for sl in (research_slug, review_slug):
            (fake_dir / f"{sl}.md").write_text(
                "---\n"
                f"slug: {sl}\n"
                "name: Probe\n"
                "provider_support: [claude]\n"
                f"agent_path: {fake_dir}/{sl}.md\n"
                "---\n\n# corpo\n",
                encoding="utf-8",
            )

        monkeypatch.setattr(
            win,
            "_scan_persona_files",
            lambda: [
                (research_slug, str(fake_dir / f"{research_slug}.md")),
                (review_slug, str(fake_dir / f"{review_slug}.md")),
            ],
        )
        win._on_personas_update_clicked()

        research_btn = _button_by_testid(win, f"queue-btn-persona-{research_slug}")
        review_btn = _button_by_testid(win, f"queue-btn-persona-{review_slug}")
        assert research_btn.property("persona_category") == "Research"
        assert review_btn.property("persona_category") == "Review"
        # A persona nova respeita o filtro ativo no momento do update.
        assert not research_btn.isHidden()
        assert review_btn.isHidden()
    finally:
        _set_persona_filter(win, PERSONA_FILTER_ALL_LABEL)
