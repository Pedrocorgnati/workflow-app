"""Regressao: botoes da sub-aba PROMPTS (queue-subtab-insertions-prompts) devem
renderizar para TODOS os .md de ai-forge/custom-prompts/prompts-subtab/,
independentemente do cwd com que o app foi lancado.

Bug historico (2026-06-24): o carregamento/reconciliacao e o QFileSystemWatcher
da sub-aba resolviam o diretorio via os.getcwd(). O app roda com cwd =
ai-forge/workflow-app (Makefile `uv run python -m workflow_app.main`), nunca a
raiz do repo, entao o path resolvido (ai-forge/workflow-app/ai-forge/custom-
prompts/...) nao existia -> watcher observava nada, reconciliacao nao achava o
dir e NENHUM botao de prompt era criado. Fix: usar _systemforge_root()
(cwd-independente, parents[4]), o mesmo resolver que a sub-aba de personas usa.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QPushButton


def _new_window(qtbot):
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _subtab_widgets(win):
    layout = win._command_queue._subtab_prompts_layout
    return [
        layout.itemAt(i).widget()
        for i in range(layout.count())
        if layout.itemAt(i).widget() is not None
    ]


def _button_by_testid(win, testid: str) -> QPushButton:
    for widget in _subtab_widgets(win):
        if widget.property("testid") == testid:
            assert isinstance(widget, QPushButton)
            return widget
    raise AssertionError(f"botao {testid} nao encontrado")


def _set_prompt_filter(win, category: str) -> int:
    from workflow_app.command_queue.command_queue_widget import (
        PROMPT_FILTER_ALL_LABEL,
        PROMPT_FILTER_CATEGORIES,
    )

    bar = win._command_queue._prompts_filter_bar
    if category == PROMPT_FILTER_ALL_LABEL:
        idx = 0
    else:
        idx = 1 + list(PROMPT_FILTER_CATEGORIES).index(category)
    bar.setCurrentIndex(idx)
    return idx


def _prompt_md_basenames() -> set[str]:
    from workflow_app.main_window import MainWindow

    root = MainWindow._systemforge_root()
    d = root / "ai-forge" / "custom-prompts" / "prompts-subtab"
    return {
        p.name for p in d.glob("*.md") if p.name != "README.md"
    }


def test_prompts_subtab_renders_all_md_regardless_of_cwd(qtbot, tmp_path):
    """Lancado de um cwd != raiz do repo, a sub-aba ainda cria um botao por
    .md real (reconciliacao de boot cwd-independente)."""
    _prev = Path.cwd()
    os.chdir(tmp_path)  # cwd deliberadamente != raiz do repo
    try:
        win = _new_window(qtbot)
        entry_basenames = {
            os.path.basename(e["path"]) for e in win._prompt_entries
        }
    finally:
        os.chdir(_prev)

    on_disk = _prompt_md_basenames()
    assert on_disk, "esperava ao menos 1 .md em prompts-subtab/"
    missing = on_disk - entry_basenames
    assert not missing, (
        f"botoes de prompt nao renderizados para .md existentes: {sorted(missing)}"
    )


def test_prompts_watcher_points_to_repo_root_abs_dir(qtbot, tmp_path):
    """O QFileSystemWatcher observa o dir absoluto via _systemforge_root, nunca
    um path cwd-relativo (que duplicaria ai-forge/workflow-app/ai-forge/...)."""
    from workflow_app.main_window import MainWindow

    expected = str(
        MainWindow._systemforge_root() / "ai-forge/custom-prompts/prompts-subtab"
    )
    _prev = Path.cwd()
    os.chdir(tmp_path)
    try:
        win = _new_window(qtbot)
        dirs = win._prompts_file_watcher.directories()
    finally:
        os.chdir(_prev)

    assert expected in dirs, f"watcher deveria observar {expected}, observa {dirs}"
    assert not any(
        "workflow-app/ai-forge/custom-prompts" in d for d in dirs
    ), f"watcher observando path cwd-relativo duplicado: {dirs}"


def test_prompts_subtab_has_a_button_per_entry(qtbot):
    """Cada entry de prompt vira um QPushButton com testid output-btn-prompt-*
    na sub-aba queue-subtab-insertions-prompts."""
    win = _new_window(qtbot)
    layout = win._command_queue._subtab_prompts_layout
    rendered = {
        layout.itemAt(i).widget().property("testid")
        for i in range(layout.count())
        if isinstance(layout.itemAt(i).widget(), QPushButton)
    }
    for entry in win._prompt_entries:
        assert entry["testid"] in rendered, (
            f"entry {entry['label']} sem botao renderizado ({entry['testid']})"
        )


def test_prompts_filter_bar_has_all_first_then_categories(qtbot):
    from workflow_app.command_queue.command_queue_widget import (
        PROMPT_FILTER_ALL_LABEL,
        PROMPT_FILTER_CATEGORIES,
    )

    win = _new_window(qtbot)
    bar = win._command_queue._prompts_filter_bar

    assert bar.property("testid") == "queue-prompts-filter-bar"
    labels = [bar.tabText(i) for i in range(bar.count())]
    assert labels[0] == PROMPT_FILTER_ALL_LABEL == "All"
    assert tuple(labels[1:]) == PROMPT_FILTER_CATEGORIES


def test_every_prompt_button_has_valid_category_and_tooltip(qtbot):
    from workflow_app.command_queue.command_queue_widget import PROMPT_FILTER_CATEGORIES

    win = _new_window(qtbot)

    prompt_buttons = [
        widget for widget in _subtab_widgets(win)
        if isinstance(widget, QPushButton)
        and (
            str(widget.property("testid")).startswith("output-btn-prompt-")
            or widget.property("testid") == "queue-btn-executar-tasks"
        )
    ]
    assert prompt_buttons, "esperava botoes de prompt renderizados"
    for btn in prompt_buttons:
        category = btn.property("prompt_category")
        description = btn.property("prompt_description")
        assert category in PROMPT_FILTER_CATEGORIES, btn.property("testid")
        assert isinstance(description, str) and description.strip(), btn.property("testid")
        assert btn.toolTip().strip(), btn.property("testid")


def test_create_agent_prompt_button_is_registered(qtbot):
    win = _new_window(qtbot)

    btn = _button_by_testid(win, "output-btn-prompt-create-agent")

    assert btn.property("prompt_category") == "Build"
    assert "persona MCP" in btn.property("prompt_description")
    assert any(
        entry["label"] == "create-agent"
        and entry["path"] == "ai-forge/custom-prompts/prompts-subtab/create-agent.md"
        for entry in win._prompt_entries
    )


def test_create_agent_prompt_keeps_frontmatter_label_when_qsettings_is_old(qtbot):
    QSettings("systemForge", "workflow-app").setValue(
        "prompts_row/entries",
        json.dumps([
            {
                "label": "MCP-test",
                "path": "ai-forge/custom-prompts/prompts-subtab/mcp-test.md",
                "description": "legacy settings without create-agent",
            }
        ]),
    )

    win = _new_window(qtbot)

    assert any(
        entry["label"] == "create-agent"
        and entry["path"] == "ai-forge/custom-prompts/prompts-subtab/create-agent.md"
        for entry in win._prompt_entries
    )


def test_prompt_filter_hides_non_matching_prompts_keeps_utilities(qtbot):
    win = _new_window(qtbot)
    try:
        _set_prompt_filter(win, "Review")

        for widget in _subtab_widgets(win):
            if not isinstance(widget, QPushButton):
                continue
            category = widget.property("prompt_category")
            if isinstance(category, str) and category:
                if category == "Review":
                    assert not widget.isHidden(), widget.property("testid")
                else:
                    assert widget.isHidden(), widget.property("testid")

        assert not _button_by_testid(win, "queue-btn-add-prompt").isHidden()
        assert not _button_by_testid(win, "toolbar-prompts-config-gear").isHidden()
    finally:
        from workflow_app.command_queue.command_queue_widget import PROMPT_FILTER_ALL_LABEL

        _set_prompt_filter(win, PROMPT_FILTER_ALL_LABEL)
        QSettings("systemForge", "workflow-app").setValue("prompts/active_filter", 0)
