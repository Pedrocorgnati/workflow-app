"""Testes do modal de configuracao gear (T4).

Cobre 3 cenarios do T4 (loop 05-21-implantation-tasklist-aba-brainstorm):
- test_gear_dialog_opens_with_seeds_loaded: dialog carrega 9 seeds com testid.
- test_gear_modal_persists_seed_edits_to_disk: save grava no .md (atomic write).
- test_gear_modal_revert_discards_edits: reject() preserva conteudo do .md.

Usa `tmp_path` para criar workspace temporario com 9 seeds canonicos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(5)

pytest.importorskip("workflow_app.widgets.brainstorm_mcp_config_dialog")

from workflow_app.widgets.brainstorm_mcp_config_dialog import (
    BrainstormMcpConfigDialog,
    load_seed,
    save_seed,
)


_SEED_TEMPLATE = """---
schema_version: "1.0"
slug: {slug}
label: {label}
button_type: {button_type}
agent_name: {agent_name}
agent_path: {agent_path}
action: {action}
target_path: {target_path}
target_terminal: {target_terminal}
---

# {slug}

## Prompt canonico

{prompt_body}

"""


def _materialize_seeds(repo_root: Path) -> tuple[Path, Path]:
    """Cria 9 seeds canonicos + diretorio de agentes. Retorna (seeds_dir, agents_dir)."""
    seeds_dir = repo_root / "blacksmith" / "brainstorm-mcp"
    agents_dir = repo_root / "agents"
    seeds_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)
    specs = [
        ("01-criar-md", "criar-md", "Claude", "Criar arquivo", False, "terminal-interactive-output"),
        ("02-pesquisar", "pesquisar", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("03-controversial", "controversial", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("04-hardening", "hardening", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("05-criar-task", "criar-task", "Claude", "Criar tasks", True, "terminal-interactive-output"),
        ("06-revisar-task", "revisar-task", "Claude", "Revisar tasks", True, "terminal-interactive-output"),
        ("07-executar-task", "executar-task", "Claude", "Executar", True, "terminal-interactive-output"),
        ("08-revisar-execucao", "revisar-execucao", "Claude", "Revisar execucao", True, "terminal-interactive-output"),
        ("09-revisar-qa", "revisar-qa", "Claude", "Revisar QA", True, "terminal-interactive-output"),
    ]
    for fname, slug, btype, action, tp, tt in specs:
        agent_path = f"agents/{slug}-rules.md"
        (repo_root / agent_path).write_text("# persona stub\n", encoding="utf-8")
        body = _SEED_TEMPLATE.format(
            slug=slug,
            label=slug,
            button_type=btype,
            agent_name=f"agent-{slug}",
            agent_path=agent_path,
            action=action,
            target_path=str(tp).lower(),
            target_terminal=tt,
            prompt_body=f"prompt body for {slug}",
        )
        (seeds_dir / f"{fname}.md").write_text(body, encoding="utf-8")
    return seeds_dir, agents_dir


def test_gear_dialog_opens_with_seeds_loaded(qtbot, tmp_path):
    """Dialog inicializa com 9 seeds carregados na lista lateral."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir, _ = _materialize_seeds(repo_root)

    dlg = BrainstormMcpConfigDialog(
        parent=None, repo_root=repo_root, seeds_dir=seeds_dir,
    )
    qtbot.addWidget(dlg)
    assert dlg.property("testid") == "brainstorm-mcp-config-dialog"
    # Lista lateral tem 9 itens (1 por seed).
    assert dlg._list_widget.count() == 9
    # Os 9 paths foram registrados internamente.
    assert len(dlg._seed_paths) == 9


def test_gear_modal_persists_seed_edits_to_disk(qtbot, tmp_path):
    """save_seed (helper modular) grava label/action/prompt no .md atomicamente.

    Valida o contrato de I/O do dialogo sem depender da UI: chama o helper
    diretamente e re-le o arquivo. Os caminhos via UI sao testados em E2E
    do main_window; aqui validamos a primitiva.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir, _ = _materialize_seeds(repo_root)
    seed_path = seeds_dir / "01-criar-md.md"
    original_meta, _ = load_seed(seed_path)

    patch = {
        "label": "novo-label",
        "button_type": "Kimi",
        "agent_name": "novo agent",
        "agent_path": "agents/criar-md-rules.md",
        "action": "Revisar QA",
        "target_path": True,
        "target_terminal": "terminal-workspace-output",
        "schema_version": original_meta.get("schema_version", "1.0"),
    }
    save_seed(seed_path, patch, prompt_body="novo prompt body")

    meta_after, body_after = load_seed(seed_path)
    assert meta_after["label"] == "novo-label"
    assert meta_after["button_type"] == "Kimi"
    assert meta_after["action"] == "Revisar QA"
    assert meta_after["target_path"] is True
    assert "novo prompt body" in body_after


def test_gear_modal_revert_discards_edits(qtbot, tmp_path):
    """Reject (cancel) NAO altera conteudo do .md.

    Cria dialogo, marca dirty via edit programatico, fecha sem save.
    `load_seed` apos o reject deve retornar meta original.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir, _ = _materialize_seeds(repo_root)
    seed_path = seeds_dir / "01-criar-md.md"
    meta_before, body_before = load_seed(seed_path)

    dlg = BrainstormMcpConfigDialog(
        parent=None, repo_root=repo_root, seeds_dir=seeds_dir,
    )
    qtbot.addWidget(dlg)
    # Seleciona row 0 e simula edicao do label sem salvar.
    dlg._list_widget.setCurrentRow(0)
    dlg._label_edit.setText("rascunho-temporario")
    dlg._mark_dirty()
    dlg.reject()

    meta_after, body_after = load_seed(seed_path)
    assert meta_after.get("label") == meta_before.get("label")
    assert body_after == body_before
