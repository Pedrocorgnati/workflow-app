"""Testes do modal de configuracao gear (T4).

Cobre 3 cenarios do T4 (loop 05-21-implantation-tasklist-aba-brainstorm):
- test_gear_dialog_opens_with_seeds_loaded: dialog carrega 24 seeds com testid.
- test_gear_modal_persists_seed_edits_to_disk: save grava no .md (atomic write).
- test_gear_modal_revert_discards_edits: reject() preserva conteudo do .md.

Usa `tmp_path` para criar workspace temporario com 24 seeds canonicos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(5)

pytest.importorskip("workflow_app.widgets.brainstorm_mcp_config_dialog")

from workflow_app.main_window import MainWindow
from workflow_app.widgets.brainstorm_mcp_config_dialog import (
    BrainstormMcpConfigDialog,
    effective_label,
    load_seed,
    save_seed,
)


#: Literal do sentinel de terminal-em-runtime, deliberadamente NAO importado de
#: `mcp_prompt_button`: o valor viaja no frontmatter dos seeds em disco, entao o
#: teste tem que travar a string do contrato. Renomear a constante no codigo sem
#: migrar os 20 seeds que a usam deve ficar vermelho aqui.
SEED_TARGET_TERMINAL_RUNTIME_SENTINEL = "depende-do-radio"

_SEED_TEMPLATE = """---
schema_version: 1
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
    """Cria 24 seeds canonicos + diretorio de agentes. Retorna (seeds_dir, agents_dir)."""
    seeds_dir = repo_root / "blacksmith" / "brainstorm-mcp"
    agents_dir = repo_root / "agents"
    seeds_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)
    specs = [
        ("01-criar-md", "criar-md", "Claude", "Criar arquivo", False, "terminal-interactive-output"),
        ("02-search-in", "search-in", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("03-search-out", "search-out", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("04-search-forge", "search-forge", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("05-deep-detailer", "deep-detailer", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("06-controversial", "controversial", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("08-hardening", "hardening", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("09-loop-prepare", "loop-prepare", "Claude", "Loop prepare", True, "terminal-interactive-output"),
        ("10-criar-task", "criar-task", "Claude", "Criar tasks", True, "terminal-interactive-output"),
        ("11-revisar-task", "revisar-task", "Claude", "Revisar tasks", True, "terminal-interactive-output"),
        ("12-executar-task", "executar-task", "Claude", "Executar", True, "terminal-interactive-output"),
        ("13-revisar-execucao", "revisar-execucao", "Claude", "Revisar execucao", True, "terminal-interactive-output"),
        ("14-visual-design", "repo-ruler", "Claude", "Revisar", True, "terminal-interactive-output"),
        ("15-layout-architect", "layout-architect", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("16-analise-complexidade", "analise-complexidade", "Claude", "Analisar complexidade", True, "terminal-interactive-output"),
        ("17-billing", "billing", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("18-debugger", "debugger", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("19-delegador", "delegador", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("20-pdca", "pdca", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("21-soft-engen", "soft-engen", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("22-scaffolds-blueprints-updater", "scaffolds-blueprints-updater", "Claude", "Otimizar", True, "terminal-interactive-output"),
        ("07-questioner", "questioner", "Claude", "Revisar", True, "terminal-interactive-output"),
        ("23-ux-ui", "ux-ui", "Claude", "Revisar", True, "terminal-interactive-output"),
        ("24-performance-engineer", "performance-engineer", "Claude", "Revisar", True, "terminal-interactive-output"),
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
    """Dialog inicializa com 24 seeds carregados na lista lateral."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir, _ = _materialize_seeds(repo_root)

    dlg = BrainstormMcpConfigDialog(
        parent=None, repo_root=repo_root, seeds_dir=seeds_dir,
    )
    qtbot.addWidget(dlg)
    assert dlg.property("testid") == "brainstorm-mcp-config-dialog"
    # Lista lateral tem 24 itens (1 por seed).
    assert dlg._list_widget.count() == 24
    # Os 24 paths foram registrados internamente.
    assert len(dlg._seed_paths) == 24


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
        "action": "Loop prepare",
        "target_path": True,
        "target_terminal": "terminal-workspace-output",
        "schema_version": original_meta.get("schema_version", "1.0"),
    }
    save_seed(seed_path, patch, prompt_body="novo prompt body")

    meta_after, body_after = load_seed(seed_path)
    assert meta_after["label"] == "novo-label"
    assert meta_after["button_type"] == "Kimi"
    assert meta_after["action"] == "Loop prepare"
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


# Regressao: campo Label do gear reflete no label do botao da grade.


# PR1(c): o sentinel `depende-do-radio` e valor de dominio, nao lixo.


def _index_of(dlg, filename: str) -> int:
    """Row do seed cujo arquivo e `filename` (a ordem da lista nao e garantida)."""
    for i, p in enumerate(dlg._seed_paths):
        if Path(p).name == filename:
            return i
    raise AssertionError(f"seed {filename} nao carregado no dialogo")


def test_gear_save_preserves_runtime_terminal_sentinel(qtbot, tmp_path):
    """Abrir-editar-salvar NAO troca `depende-do-radio` por um terminal fixo.

    Era o bug: o sentinel nao estava em `VALID_TERMINALS`, entao o combo nunca
    o assumia e `_capture_form_into` gravava o texto residual do combo. Como
    `_on_save_clicked` re-grava os 24 seeds, um unico save destruia o sentinel
    de TODOS eles - inclusive os que o operador nem abriu.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir, _ = _materialize_seeds(repo_root)

    # Dois seeds com action terminal-agnostica passam a diferir o terminal.
    sentinel_files = {"09-loop-prepare.md": "loop-prepare", "02-search-in.md": "search-in"}
    for fname, slug in sentinel_files.items():
        p = seeds_dir / fname
        save_seed(
            p,
            {"target_terminal": SEED_TARGET_TERMINAL_RUNTIME_SENTINEL},
            f"prompt body for {slug}",
        )
        assert load_seed(p)[0]["target_terminal"] == SEED_TARGET_TERMINAL_RUNTIME_SENTINEL

    dlg = BrainstormMcpConfigDialog(
        parent=None, repo_root=repo_root, seeds_dir=seeds_dir,
    )
    qtbot.addWidget(dlg)

    # Seed com sentinel: o combo exibe o proprio sentinel e o form valida.
    idx = _index_of(dlg, "09-loop-prepare.md")
    dlg._list_widget.setCurrentRow(idx)
    assert dlg._target_terminal_combo.currentText() == SEED_TARGET_TERMINAL_RUNTIME_SENTINEL
    assert dlg._validate() is True

    # Editar OUTRO campo e salvar nao pode arrastar o terminal junto.
    dlg._label_edit.setText("loop-prepare-editado")
    dlg._mark_dirty()
    dlg._on_save_clicked()

    for fname in sentinel_files:
        meta_after, _ = load_seed(seeds_dir / fname)
        assert meta_after["target_terminal"] == SEED_TARGET_TERMINAL_RUNTIME_SENTINEL, (
            f"{fname}: sentinel sobrescrito pelo save do gear"
        )
    assert load_seed(seeds_dir / "09-loop-prepare.md")[0]["label"] == "loop-prepare-editado"
    # Seeds de terminal fixo continuam intactos.
    assert (
        load_seed(seeds_dir / "01-criar-md.md")[0]["target_terminal"]
        == "terminal-interactive-output"
    )


def test_gear_rejects_sentinel_when_action_pins_the_terminal(qtbot, tmp_path):
    """`Criar arquivo` crava o terminal, entao adiar para o radio e incoerente."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir, _ = _materialize_seeds(repo_root)

    dlg = BrainstormMcpConfigDialog(
        parent=None, repo_root=repo_root, seeds_dir=seeds_dir,
    )
    qtbot.addWidget(dlg)

    dlg._list_widget.setCurrentRow(_index_of(dlg, "01-criar-md.md"))
    assert dlg._validate() is True
    dlg._target_terminal_combo.setCurrentText(SEED_TARGET_TERMINAL_RUNTIME_SENTINEL)

    assert dlg._validate() is False
    assert SEED_TARGET_TERMINAL_RUNTIME_SENTINEL in dlg._error_label.text()
    assert dlg._save_btn.isEnabled() is False


def test_effective_label_strips_legacy_title_in_label():
    """Label legado que guardou o `title` inteiro nunca vaza para o botao."""
    legacy = {
        "label": "Seed - Botao 13 - Analise de Complexidade",
        "title": "Seed - Botao 13 - Analise de complexidade",
        "slug": "analise-complexidade",
    }
    assert effective_label(legacy) == "Analise de Complexidade"
    # Label explicito limpo vence o title.
    assert effective_label({"label": "Complexidade", "title": "Seed - Botao 13 - X"}) == "Complexidade"
    # Sem label: deriva do title (sem prefixo).
    assert effective_label({"title": "Seed - Botao 2 - search-in", "slug": "search-in"}) == "search-in"
    # Sem label nem title: fallback slug.
    assert effective_label({"slug": "x"}) == "x"


def test_gear_label_edit_reflects_on_grid_button_label(tmp_path):
    """Editar o campo Label e salvar muda o label que o loader entrega ao botao.

    Era o bug: o loader derivava o label so do `title` e ignorava o `label`
    gravado pelo gear -> editar o campo nao mudava nada no botao.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir, _ = _materialize_seeds(repo_root)
    seed_path = seeds_dir / "16-analise-complexidade.md"

    # Simula o save do gear: grava `label` novo no frontmatter.
    save_seed(seed_path, {"label": "Complexidade"}, "prompt body for analise-complexidade")

    class _Fake:
        _BRAINSTORM_SEEDS_RELDIR = "blacksmith/brainstorm-mcp"
        _BRAINSTORM_SEED_COUNT = 24

        def __init__(self, root: Path) -> None:
            self._root = root

        def _systemforge_root(self) -> Path:
            return self._root

        def _brainstorm_seeds_dir(self) -> Path:
            return MainWindow._brainstorm_seeds_dir(self)  # type: ignore[arg-type]

        def _load_brainstorm_seeds(self):
            return MainWindow._load_brainstorm_seeds(self)  # type: ignore[arg-type]

    seeds = _Fake(repo_root)._load_brainstorm_seeds()
    ac = next(s for s in seeds if s["slug"] == "analise-complexidade")
    assert ac["label"] == "Complexidade"
