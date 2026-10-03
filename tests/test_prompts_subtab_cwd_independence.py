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
    for btn in win.findChildren(QPushButton):
        if btn.property("testid") == testid:
            return btn
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


def test_systemforge_prompts_delegate_to_exact_canonical_invocations():
    from workflow_app.main_window import MainWindow

    prompts_dir = (
        MainWindow._systemforge_root()
        / "ai-forge/custom-prompts/prompts-subtab"
    )
    expected = {
        "systemforge-db-update.md": (
            "title: SF DB",
            "/hostinger:update-bd systemforge-dashboard",
            ".claude/commands/hostinger/update-bd.md",
        ),
        "systemforge-hostinger-deploy.md": (
            "title: SF Deploy",
            "/commit:nextjs-hostinger systemforge-dashboard",
            ".claude/commands/commit/nextjs-hostinger.md",
        ),
        "systemforge-fix-503.md": (
            "title: SF 503",
            "/hostinger:fix-503 .claude/projects/systemforge-dashboard.json",
            ".claude/commands/hostinger/fix-503.md",
        ),
        "corgly-db-update.md": (
            "title: Corgly DB",
            "/hostinger:update-bd corgly-app",
            ".claude/commands/hostinger/update-bd.md",
        ),
        "corgly-hostinger-deploy.md": (
            "title: Corgly Deploy",
            "/commit:nextjs-hostinger corgly-app",
            ".claude/commands/commit/nextjs-hostinger.md",
        ),
    }
    for filename, required_tokens in expected.items():
        prompt_path = prompts_dir / filename
        text = prompt_path.read_text(encoding="utf-8")
        assert len(prompt_path.stem) <= 32
        assert "category: commit" in text
        assert ".claude/project.json" in text
        slug = "corgly" if filename.startswith("corgly-") else "systemforge-dashboard"
        assert f"pending-actions/{slug}.md" in text
        if slug == "corgly":
            assert ".claude/commands/hostinger/_shared/corgly-app.md" in text
            assert "corgly-app.json" not in text
        assert text.count("Pare quando ") == 1
        for token in required_tokens:
            assert token in text


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
    assert labels[-1] == "commit"


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


def test_estrategista_delegador_prompt_button_is_registered(qtbot):
    win = _new_window(qtbot)

    btn = _button_by_testid(win, "output-btn-prompt-delegador-mcp")

    assert btn.property("prompt_category") == "Build"
    description = btn.property("prompt_description")
    for token in ("Codex", "Kimi", "Qwen"):
        assert token in description, description
    assert any(
        entry["path"]
        == "ai-forge/custom-prompts/prompts-subtab/estrategista-delegador.md"
        for entry in win._prompt_entries
    )


def test_estrategista_delegador_label_survives_old_qsettings(qtbot):
    """QSettings antigo sem a entry nova: a reconciliacao de boot descobre o .md
    e respeita o `title` do frontmatter (label 'Delegador MCP', nao o
    Title-Case do nome do arquivo)."""
    QSettings("systemForge", "workflow-app").setValue(
        "prompts_row/entries",
        json.dumps([
            {
                "label": "MCP-test",
                "path": "ai-forge/custom-prompts/prompts-subtab/mcp-test.md",
                "description": "legacy settings without estrategista-delegador",
            }
        ]),
    )

    win = _new_window(qtbot)

    assert any(
        entry["label"] == "Delegador MCP"
        and entry["path"]
        == "ai-forge/custom-prompts/prompts-subtab/estrategista-delegador.md"
        for entry in win._prompt_entries
    )


def test_systemforge_commit_prompts_are_registered_and_filtered(qtbot, monkeypatch):
    win = _new_window(qtbot)
    published = []
    monkeypatch.setattr(win, "_publish_to_terminal", published.append)
    try:
        expected = {
            "output-btn-prompt-sf-db": (
                "SF DB",
                "ai-forge/custom-prompts/prompts-subtab/systemforge-db-update.md",
            ),
            "output-btn-prompt-sf-deploy": (
                "SF Deploy",
                "ai-forge/custom-prompts/prompts-subtab/systemforge-hostinger-deploy.md",
            ),
            "output-btn-prompt-sf-503": (
                "SF 503",
                "ai-forge/custom-prompts/prompts-subtab/systemforge-fix-503.md",
            ),
            "output-btn-prompt-corgly-db": (
                "Corgly DB",
                "ai-forge/custom-prompts/prompts-subtab/corgly-db-update.md",
            ),
            "output-btn-prompt-corgly-deploy": (
                "Corgly Deploy",
                "ai-forge/custom-prompts/prompts-subtab/corgly-hostinger-deploy.md",
            ),
            "output-btn-prompt-only-commit": (
                "only commit",
                "ai-forge/custom-prompts/prompts-subtab/only-commit.md",
            ),
            "output-btn-prompt-only-push": (
                "only push",
                "ai-forge/custom-prompts/prompts-subtab/only-push.md",
            ),
            "output-btn-prompt-full-deploy": (
                "full deploy",
                "ai-forge/custom-prompts/prompts-subtab/full-deploy.md",
            ),
            "output-btn-prompt-commit-push": (
                "commit & push",
                "ai-forge/custom-prompts/prompts-subtab/commit-push.md",
            ),
        }
        for testid, (label, path) in expected.items():
            btn = _button_by_testid(win, testid)
            assert btn.text() == label
            assert btn.property("prompt_category") == "commit"
            assert btn.toolTip().strip()
            assert any(
                entry["label"] == label and entry["path"] == path
                for entry in win._prompt_entries
            )
            if label.startswith("Corgly"):
                published.clear()
                btn.click()
                assert published == [f"{win._prompt_base} {path}"]

        _set_prompt_filter(win, "commit")
        assert not _button_by_testid(win, "output-btn-prompt-sf-db").isHidden()
        assert not _button_by_testid(win, "output-btn-prompt-sf-deploy").isHidden()
        assert not _button_by_testid(win, "output-btn-prompt-sf-503").isHidden()
        assert not _button_by_testid(win, "output-btn-prompt-corgly-db").isHidden()
        assert not _button_by_testid(win, "output-btn-prompt-corgly-deploy").isHidden()
        assert not _button_by_testid(win, "output-btn-prompt-only-commit").isHidden()
        assert not _button_by_testid(win, "output-btn-prompt-only-push").isHidden()
        assert not _button_by_testid(win, "output-btn-prompt-full-deploy").isHidden()
        assert not _button_by_testid(win, "output-btn-prompt-commit-push").isHidden()
        assert _button_by_testid(win, "output-btn-prompt-mcp-test").isHidden()
    finally:
        from workflow_app.command_queue.command_queue_widget import PROMPT_FILTER_ALL_LABEL

        _set_prompt_filter(win, PROMPT_FILTER_ALL_LABEL)
        QSettings("systemForge", "workflow-app").setValue("prompts/active_filter", 0)


def test_systemforge_commit_labels_survive_old_qsettings(qtbot):
    QSettings("systemForge", "workflow-app").setValue(
        "prompts_row/entries",
        json.dumps([
            {
                "label": "MCP-test",
                "path": "ai-forge/custom-prompts/prompts-subtab/mcp-test.md",
                "description": "legacy settings without systemforge prompts",
            }
        ]),
    )

    win = _new_window(qtbot)

    labels_by_path = {
        entry["path"]: entry["label"] for entry in win._prompt_entries
    }
    assert labels_by_path[
        "ai-forge/custom-prompts/prompts-subtab/systemforge-db-update.md"
    ] == "SF DB"
    assert labels_by_path[
        "ai-forge/custom-prompts/prompts-subtab/systemforge-hostinger-deploy.md"
    ] == "SF Deploy"
    assert labels_by_path[
        "ai-forge/custom-prompts/prompts-subtab/systemforge-fix-503.md"
    ] == "SF 503"
    assert labels_by_path[
        "ai-forge/custom-prompts/prompts-subtab/corgly-db-update.md"
    ] == "Corgly DB"
    assert labels_by_path[
        "ai-forge/custom-prompts/prompts-subtab/corgly-hostinger-deploy.md"
    ] == "Corgly Deploy"
    assert labels_by_path[
        "ai-forge/custom-prompts/prompts-subtab/only-commit.md"
    ] == "only commit"
    assert labels_by_path[
        "ai-forge/custom-prompts/prompts-subtab/only-push.md"
    ] == "only push"
    assert labels_by_path[
        "ai-forge/custom-prompts/prompts-subtab/full-deploy.md"
    ] == "full deploy"
    assert labels_by_path[
        "ai-forge/custom-prompts/prompts-subtab/commit-push.md"
    ] == "commit & push"


def test_systemforge_503_is_third_systemforge_prompt(qtbot):
    win = _new_window(qtbot)

    paths = [entry["path"] for entry in win._prompt_entries]
    sf_block = [
        "ai-forge/custom-prompts/prompts-subtab/systemforge-db-update.md",
        "ai-forge/custom-prompts/prompts-subtab/systemforge-hostinger-deploy.md",
        "ai-forge/custom-prompts/prompts-subtab/systemforge-fix-503.md",
    ]
    start = paths.index(sf_block[0])

    assert paths[start:start + 3] == sf_block
    assert _button_by_testid(win, "output-btn-prompt-sf-503").text() == "SF 503"


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
