"""Regression tests for the PERSONAS insertions sub-aba in MainWindow.

Cobre: (1) um botao por persona REAL de ai-forge/MCP/agents/ que cola o path
no terminal; (2) o botao 'update' 1:1 (queue-btn-personas-update) que re-varre
a pasta e cria botao para personas novas ao vivo, sem reiniciar o app.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPushButton


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


def test_personas_subtab_uses_user_friendly_tab_label(qtbot):
    win = _new_window(qtbot)

    tabs = win._command_queue._insertions_subtabs
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert "Agentes" in labels
    assert "PERSONAS" not in labels


def test_persona_buttons_use_user_friendly_labels(qtbot):
    win = _new_window(qtbot)

    expected = {
        "queue-btn-persona-analista-delegador-rules": "Delegador",
        "queue-btn-persona-controversial-devils-advocate-rules": "Controversial",
        "queue-btn-persona-executar-task-rules": "Executor",
        "queue-btn-persona-code-debugger": "Debugger",
    }
    for testid, label in expected.items():
        btn = _button_by_testid(win, testid)
        assert btn.text() == label
        assert "-rules" not in btn.text()


def test_persona_button_pastes_relative_path(qtbot, monkeypatch):
    win = _new_window(qtbot)

    captured: list[str] = []
    monkeypatch.setattr(win, "_publish_to_terminal", lambda text: captured.append(text))

    slug, rel_path = win._scan_persona_files()[0]
    btn = _button_by_testid(win, f"queue-btn-persona-{slug}")
    btn.click()

    assert captured == [rel_path]
    assert rel_path == str(Path("ai-forge/MCP/agents") / f"{slug}.md")


def test_personas_update_button_is_green_square_with_icon(qtbot):
    win = _new_window(qtbot)

    btn = _button_by_testid(win, "queue-btn-personas-update")
    assert btn.width() == 34 and btn.height() == 34  # 1:1
    assert "#16A34A" in btn.styleSheet()  # verde
    assert btn.accessibleName() == "Recarregar personas"
    assert "mantem este botao sempre no final" in btn.toolTip()
    # Icone (refresh.svg) ou fallback textual de refresh.
    assert (not btn.icon().isNull()) or btn.text() == "⟳"


def test_personas_update_button_is_last_widget_in_flow(qtbot):
    win = _new_window(qtbot)

    layout = win._command_queue._subtab_personas_layout
    last = layout.itemAt(layout.count() - 1).widget()
    assert last.property("testid") == "queue-btn-personas-update"


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

    # update permanece o ultimo widget do flow.
    layout = win._command_queue._subtab_personas_layout
    last = layout.itemAt(layout.count() - 1).widget()
    assert last.property("testid") == "queue-btn-personas-update"


def test_personas_update_is_idempotent_when_nothing_new(qtbot, monkeypatch):
    win = _new_window(qtbot)

    before = set(_buttons_by_testid_prefix(win, "queue-btn-persona-"))
    # scan retorna as mesmas personas ja renderizadas -> nenhum botao novo.
    win._on_personas_update_clicked()
    after = set(_buttons_by_testid_prefix(win, "queue-btn-persona-"))

    assert after == before
