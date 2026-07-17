"""Unit tests for T2 (loop 05-21-implantation-tasklist-aba-brainstorm).

Cobre o seed loader `_load_brainstorm_seeds` e o slot
`_on_mcp_prompt_requested` sem depender da inicializacao completa da
MainWindow (que requer QApplication + setup pesado). Os testes operam
sobre um workspace temporario com 24 seeds materializados pelo helper
`_write_seeds`.

Cenarios cobertos:
1. 24 seeds validos -> grade com 24 MCPPromptButton.
2. seed yaml malformado -> _BrainstormSeedError + grade vazia.
3. seed com agent_path inexistente -> _BrainstormSeedError (G6).
4. clique duplo rapido (debounce 300ms) -> 1 publish.
5. compat layer: target_path:false + sem target_path_edit_inplace.
6. glob com seed faltante -> _BrainstormSeedError.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from workflow_app.main_window import MainWindow, _BrainstormSeedError
from workflow_app.widgets.mcp_prompt_button import MCPPromptButton


# Helpers


_SEED_TEMPLATES = {
    "01-criar-md.md": {
        "slug": "criar-md",
        "title": "Seed - Botao 1 - Criar md",
        "button_type": "Claude",
        "agent_name": "estruturador de ideias",
        "agent_path": "agents/criar-md-rules.md",
        "action": "Criar arquivo",
        "target_path": "false",
        "target_terminal": "terminal-interactive-output",
    },
    "02-search-in.md": {
        "slug": "search-in",
        "title": "Seed - Botao 2 - search-in",
        "button_type": "type-selector-radio-input",
        "agent_name": "search-in",
        "agent_path": "agents/search-in-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    # search-out vem logo apos search-in na grade (prefixo 03-). O numero
    # "Botao N" no title e a identidade historica do seed (ver source_ref do
    # arquivo real), independente da posicao na grade.
    "03-search-out.md": {
        "slug": "search-out",
        "title": "Seed - Botao 10 - search-out",
        "button_type": "type-selector-radio-input",
        "agent_name": "search-out",
        "agent_path": "agents/search-out-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    # search-forge entra na 4a posicao da grade (prefixo 04-), logo apos a
    # familia de pesquisa search-in/search-out.
    "04-search-forge.md": {
        "slug": "search-forge",
        "title": "Seed - Botao 14 - search-forge",
        "button_type": "type-selector-radio-input",
        "agent_name": "search-forge",
        "agent_path": "agents/search-forge-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    # deep-detailer entra na 5a posicao da grade (prefixo 05-), logo apos
    # search-forge. Empurra controversial..analise para 06..15.
    "05-deep-detailer.md": {
        "slug": "deep-detailer",
        "title": "Seed - Botao 15 - Deep Detailer",
        "button_type": "type-selector-radio-input",
        "agent_name": "deep-detailer",
        "agent_path": "agents/deep-detailer.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "06-controversial.md": {
        "slug": "controversial",
        "title": "Seed - Botao 3 - Controversial",
        "button_type": "type-selector-radio-input",
        "agent_name": "controversial",
        "agent_path": "agents/controversial-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "07-hardening.md": {
        "slug": "hardening",
        "title": "Seed - Botao 4 - Hardening",
        "button_type": "type-selector-radio-input",
        "agent_name": "hardening",
        "agent_path": "agents/hardening-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "08-loop-prepare.md": {
        "slug": "loop-prepare",
        "title": "Seed - Botao 5 - Loop prepare",
        "button_type": "type-selector-radio-input",
        "agent_name": "loop-prepare",
        "agent_path": "agents/loop-prepare-rules.md",
        "action": "Loop prepare",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "09-criar-task.md": {
        "slug": "criar-task",
        "title": "Seed - Botao 6 - Criar task",
        "button_type": "type-selector-radio-input",
        "agent_name": "criar-task",
        "agent_path": "agents/criar-task-rules.md",
        "action": "Criar tasks",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "10-revisar-task.md": {
        "slug": "revisar-task",
        "title": "Seed - Botao 7 - Revisar task",
        "button_type": "Claude",
        "agent_name": "revisar-task",
        "agent_path": "agents/revisar-task-rules.md",
        "action": "Revisar tasks",
        "target_path": "true",
        "target_terminal": "terminal-interactive-output",
    },
    "11-executar-task.md": {
        "slug": "executar-task",
        "title": "Seed - Botao 8 - Executar task",
        "button_type": "type-selector-radio-input",
        "agent_name": "executar-task",
        "agent_path": "agents/executar-task-rules.md",
        "action": "Executar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "12-revisar-execucao.md": {
        "slug": "revisar-execucao",
        "title": "Seed - Botao 9 - Revisar execucao",
        "button_type": "Claude",
        "agent_name": "revisar-execucao",
        "agent_path": "agents/revisar-execucao-rules.md",
        "action": "Revisar execucao",
        "target_path": "true",
        "target_terminal": "terminal-interactive-output",
    },
    "13-visual-design.md": {
        "slug": "repo-ruler",
        "title": "Seed - Botao 13 - Repo ruler",
        "button_type": "type-selector-radio-input",
        "agent_name": "repo-ruler",
        "agent_path": "agents/specific-reviewer.md",
        "action": "Revisar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "14-layout-architect.md": {
        "slug": "layout-architect",
        "title": "Seed - Botao 12 - Layout",
        "button_type": "type-selector-radio-input",
        "agent_name": "layout-architect",
        "agent_path": "agents/layout-architect-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "15-analise-complexidade.md": {
        "slug": "analise-complexidade",
        "title": "Seed - Botao 13 - Analise de complexidade",
        "button_type": "type-selector-radio-input",
        "agent_name": "analise-complexidade",
        "agent_path": "agents/complexity-router-rules.md",
        "action": "Analisar complexidade",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "16-billing.md": {
        "slug": "billing",
        "title": "Seed - Botao 16 - Billing",
        "button_type": "type-selector-radio-input",
        "agent_name": "billing",
        "agent_path": "agents/billing-scpecialist.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "17-debugger.md": {
        "slug": "debugger",
        "title": "Seed - Botao 17 - Debugger",
        "button_type": "type-selector-radio-input",
        "agent_name": "debugger",
        "agent_path": "agents/code-debugger.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "18-delegador.md": {
        "slug": "delegador",
        "title": "Seed - Botao 18 - Delegador",
        "button_type": "type-selector-radio-input",
        "agent_name": "delegador",
        "agent_path": "agents/analista-delegador-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "19-pdca.md": {
        "slug": "pdca",
        "title": "Seed - Botao 19 - PDCA",
        "button_type": "type-selector-radio-input",
        "agent_name": "pdca",
        "agent_path": "agents/orquestrador-pdca-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "20-soft-engen.md": {
        "slug": "soft-engen",
        "title": "Seed - Botao 20 - soft Engen",
        "button_type": "type-selector-radio-input",
        "agent_name": "soft-engineer",
        "agent_path": "agents/soft-engineer.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "21-scaffolds-blueprints-updater.md": {
        "slug": "scaffolds-blueprints-updater",
        "title": "Seed - Botao 21 - Scaffold Update",
        "button_type": "type-selector-radio-input",
        "agent_name": "scaffolds-blueprints-updater",
        "agent_path": "agents/scaffolds-blueprints-updater.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "22-questioner.md": {
        "slug": "questioner",
        "title": "Seed - Botao 22 - Questionador",
        "button_type": "type-selector-radio-input",
        "agent_name": "questioner",
        "agent_path": "agents/questioner-rules.md",
        "action": "Revisar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "23-ux-ui.md": {
        "slug": "ux-ui",
        "title": "Seed - Botao 23 - UX/UI",
        "button_type": "type-selector-radio-input",
        "agent_name": "ux-ui",
        "agent_path": "agents/ux-ui-specialist.md",
        "action": "Revisar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "24-performance-engineer.md": {
        "slug": "performance-engineer",
        "title": "Seed - Botao 24 - Performance",
        "button_type": "type-selector-radio-input",
        "agent_name": "performance-engineer",
        "agent_path": "agents/performance-engineer.md",
        "action": "Revisar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
}


def _frontmatter(d: dict) -> str:
    lines = ["---"]
    for k, v in d.items():
        if isinstance(v, str) and v in ("true", "false"):
            lines.append(f"{k}: {v}")
        else:
            lines.append(f'{k}: "{v}"')
    lines.append("---\n\n# body\n")
    return "\n".join(lines)


def _write_seeds(tmp_path: Path, overrides: dict[str, dict | None] | None = None) -> Path:
    """Materializa 24 seeds (+ personas) em tmp_path. Overrides[fname]=None remove o seed."""
    overrides = overrides or {}
    repo_root = tmp_path / "repo"
    seeds_dir = repo_root / "blacksmith" / "brainstorm-mcp"
    agents_dir = repo_root / "agents"
    seeds_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)
    for fname, base in _SEED_TEMPLATES.items():
        if fname in overrides and overrides[fname] is None:
            continue
        spec = {**base, **(overrides.get(fname) or {})}
        # Create persona file pointed by agent_path (unless overridden to missing)
        agent_path_rel = spec["agent_path"]
        agent_abs = repo_root / agent_path_rel
        agent_abs.parent.mkdir(parents=True, exist_ok=True)
        if not agent_abs.exists():
            agent_abs.write_text("# persona stub\n", encoding="utf-8")
        # Allow raw_body override for malformed yaml
        raw_body = spec.pop("__raw_body__", None)
        if raw_body is not None:
            (seeds_dir / fname).write_text(raw_body, encoding="utf-8")
        else:
            (seeds_dir / fname).write_text(_frontmatter(spec), encoding="utf-8")
    return repo_root


class _FakeMainWindow:
    """Stub minimo de MainWindow para testar _load_brainstorm_seeds isoladamente.

    Reusa o codigo real via .__func__() — evita instanciar MainWindow inteira
    (PySide6 QMainWindow + setup pesado).
    """

    _BRAINSTORM_SEEDS_RELDIR = "blacksmith/brainstorm-mcp"

    def __init__(self, repo_root: Path) -> None:
        self._fake_root = repo_root

    def _systemforge_root(self) -> Path:
        return self._fake_root

    def _brainstorm_seeds_dir(self) -> Path:
        return MainWindow._brainstorm_seeds_dir(self)  # type: ignore[arg-type]

    def _load_brainstorm_seeds(self):
        return MainWindow._load_brainstorm_seeds(self)  # type: ignore[arg-type]


# Cenario 1: 24 seeds validos -> 24 carregam, ordem deterministica


def test_load_seeds_happy_path_24_valid(tmp_path):
    repo_root = _write_seeds(tmp_path)
    fake = _FakeMainWindow(repo_root)
    seeds = fake._load_brainstorm_seeds()
    assert len(seeds) == 24
    expected_order = [
        "criar-md",
        "search-in",
        "search-out",
        "search-forge",
        "deep-detailer",
        "controversial",
        "hardening",
        "loop-prepare",
        "criar-task",
        "revisar-task",
        "executar-task",
        "revisar-execucao",
        "repo-ruler",
        "layout-architect",
        "analise-complexidade",
        "billing",
        "debugger",
        "delegador",
        "pdca",
        "soft-engen",
        "scaffolds-blueprints-updater",
        "questioner",
        "ux-ui",
        "performance-engineer",
    ]
    assert [s["slug"] for s in seeds] == expected_order
    # Cada seed tem campos canonicos
    for s in seeds:
        assert s["button_type"] in {
            "Claude",
            "Codex",
            "Kimi",
            "type-selector-radio-input",
        }
        assert s["agent_path"].startswith("agents/")
        assert "seed_path" in s


def test_brainstorm_grid_contract_is_4x6():
    assert MainWindow._BRAINSTORM_SEED_COUNT == 24
    assert MainWindow._BRAINSTORM_GRID_COLUMNS == 4


# Cenario 2: yaml malformado -> erro fail-fast


def test_load_seeds_malformed_yaml_raises(tmp_path):
    bad_body = (
        "---\n"
        "slug: criar-md\n"
        "\t button_type: Claude\n"  # tab no inicio = yaml invalido
        "---\n"
    )
    repo_root = _write_seeds(
        tmp_path,
        overrides={"01-criar-md.md": {"__raw_body__": bad_body}},
    )
    fake = _FakeMainWindow(repo_root)
    with pytest.raises(_BrainstormSeedError, match="01-criar-md"):
        fake._load_brainstorm_seeds()


# Cenario 3: agent_path inexistente -> G6 fail


def test_load_seeds_missing_agent_path_g6(tmp_path):
    repo_root = _write_seeds(tmp_path)
    # Remove o arquivo de persona apos materializar os seeds
    (repo_root / "agents" / "criar-md-rules.md").unlink()
    fake = _FakeMainWindow(repo_root)
    with pytest.raises(_BrainstormSeedError, match="G6"):
        fake._load_brainstorm_seeds()


# Cenario 4: debounce 300ms -> click duplo rapido emite 1 publish


def test_debounce_double_click_publishes_once(monkeypatch, tmp_path):
    """Slot _on_mcp_prompt_requested respeita _prompt_in_flight.

    Stub completo apos T020 BLOCKER 1 (loop 05-21-implantation-tasklist-
    aba-brainstorm): contrato real exige `_systemforge_root`, retorno bool
    de `_publish_to_specific_terminal` (True=ok, False=aborta com toast T3)
    e signal_bus com `dispatch_result`.
    """

    class _Stub:
        _brainstorm_runtime_type = "Claude"
        _prompt_in_flight = False
        _brainstorm_md_path = "/repo/some.md"

        def __init__(self, repo_root: Path) -> None:
            self._fake_root = repo_root
            self.publish_calls: list = []

        def _systemforge_root(self) -> Path:
            return self._fake_root

        def _rel_to_root(self, p: str) -> str:
            return "some.md"

        def _codex_terminal_available(self) -> bool:
            # Test exercises button_type=Claude → resolved_slug != "codex",
            # gate at main_window.py:2503 nao dispara, mas mantemos defensivo.
            return False

        def _publish_to_specific_terminal(self, text, terminal):
            # T020 BLOCKER 1 contract: deve retornar True quando publicacao
            # foi confirmada (caller propaga dispatch_result e aborta com
            # toast canonico T3 quando False). Stub T1 (terminal=1) sempre
            # confirma, alinhado a semantica fire-and-forget do real.
            self.publish_calls.append((text, terminal))
            return True

    stub = _Stub(tmp_path)
    # Mock QTimer.singleShot para nao limpar _prompt_in_flight automaticamente.
    import workflow_app.main_window as mw

    monkeypatch.setattr(mw, "QTimer", type("QT", (), {"singleShot": staticmethod(lambda ms, fn: None)}))
    # Mock signal_bus para nao depender do bus real. Inclui dispatch_result
    # (T020 BLOCKER 1: caller emite sucesso/falha do publish para sinalizar
    # checkbox do botao via signal_bus, antes silencioso).
    monkeypatch.setattr(mw, "signal_bus", type("SB", (), {
        "toast_requested": type("T", (), {"emit": staticmethod(lambda *a, **k: None)})(),
        "dispatch_result": type("D", (), {"emit": staticmethod(lambda *a, **k: None)})(),
    })())
    # Mock build_prompt para nao depender de seed_meta real / file IO.
    monkeypatch.setattr(mw, "build_prompt", lambda meta, md_ref, root: "PROMPT FINAL")

    payload = {
        "label": "criar-md",
        "action": "Criar arquivo",
        "agent_name": "x",
        "agent_path": "agents/x.md",
        "button_type": "Claude",
        "target_path": "terminal-interactive-output",
        "target_path_edit_inplace": False,
    }
    MainWindow._on_mcp_prompt_requested(stub, payload)  # type: ignore[arg-type]
    MainWindow._on_mcp_prompt_requested(stub, payload)  # type: ignore[arg-type]
    assert len(stub.publish_calls) == 1


def test_criar_md_ignores_selected_brainstorm_md(monkeypatch, tmp_path):
    """Botao 1 cria arquivo novo e nunca anexa o .md selecionado no picker."""

    class _Stub:
        _brainstorm_runtime_type = "Claude"
        _prompt_in_flight = False
        _brainstorm_md_path = "/repo/blacksmith/brainstorm-mcp/anexado.md"

        def __init__(self, repo_root: Path) -> None:
            self._fake_root = repo_root
            self.publish_calls: list = []

        def _systemforge_root(self) -> Path:
            return self._fake_root

        def _rel_to_root(self, p: str) -> str:
            return "blacksmith/brainstorm-mcp/anexado.md"

        def _codex_terminal_available(self) -> bool:
            return False

        def _publish_to_specific_terminal(self, text, terminal):
            self.publish_calls.append((text, terminal))
            return True

    stub = _Stub(tmp_path)
    captured: dict[str, object] = {}

    import workflow_app.main_window as mw

    monkeypatch.setattr(mw, "QTimer", type("QT", (), {"singleShot": staticmethod(lambda ms, fn: None)}))
    monkeypatch.setattr(mw, "signal_bus", type("SB", (), {
        "toast_requested": type("T", (), {"emit": staticmethod(lambda *a, **k: None)})(),
        "dispatch_result": type("D", (), {"emit": staticmethod(lambda *a, **k: None)})(),
    })())

    def _capture_build_prompt(meta, md_ref, root):
        captured["meta"] = meta
        captured["md_ref"] = md_ref
        return "PROMPT CRIAR MD"

    monkeypatch.setattr(mw, "build_prompt", _capture_build_prompt)

    payload = {
        "label": "Criar md",
        "action": "Criar arquivo",
        "agent_name": "estruturador",
        "agent_path": "agents/criar-md-rules.md",
        "button_type": "Claude",
        "target_path": "terminal-interactive-output",
        "target_path_edit_inplace": False,
    }
    MainWindow._on_mcp_prompt_requested(stub, payload)  # type: ignore[arg-type]
    assert captured["md_ref"] is None
    assert captured["meta"]["target_path"] is False
    assert stub.publish_calls == [("PROMPT CRIAR MD", 1)]


# Cenario 5: compat layer (target_path:false, sem target_path_edit_inplace)


def test_compat_layer_target_path_boolean(tmp_path):
    repo_root = _write_seeds(
        tmp_path,
        overrides={
            "01-criar-md.md": {
                "target_path": "false",
                # target_terminal explicito mantido
            }
        },
    )
    fake = _FakeMainWindow(repo_root)
    seeds = fake._load_brainstorm_seeds()
    s01 = next(s for s in seeds if s["slug"] == "criar-md")
    assert s01["target_path_edit_inplace"] is False
    assert s01["target_terminal"] == "terminal-interactive-output"


# Cenario 6: seed faltante -> grade bloqueada


def test_glob_rejects_renamed_seed(tmp_path):
    repo_root = _write_seeds(tmp_path)
    # Renomeia 24 -> 25, quebrando a sequencia canonica de prefixos (01..24).
    old = repo_root / "blacksmith" / "brainstorm-mcp" / "24-performance-engineer.md"
    new = old.parent / "25-performance-engineer.md"
    old.rename(new)
    fake = _FakeMainWindow(repo_root)
    with pytest.raises(_BrainstormSeedError, match="esperado exatamente 24"):
        fake._load_brainstorm_seeds()


# Cenario extra: testid_slug do widget gera brainstorm-mcp-btn-{slug}


def test_widget_testid_slug_brainstorm_format(qtbot):
    btn = MCPPromptButton(
        label="criar-md",
        button_type="Claude",
        prompt="x",
        agent_name="estruturador",
        agent_path="agents/criar-md-rules.md",
        action="Criar arquivo",
        target_path="terminal-interactive-output",
        testid_slug="criar-md",
    )
    qtbot.addWidget(btn)
    assert btn.property("testid") == "mcp-prompt-btn-criar-md"


def test_widget_accepts_radio_button_type(qtbot):
    btn = MCPPromptButton(
        label="search-in",
        button_type="type-selector-radio-input",
        prompt="x",
        agent_name="search-in",
        agent_path="agents/x.md",
        action="Otimizar",
        target_path="terminal-interactive-output",
        testid_slug="search-in",
    )
    qtbot.addWidget(btn)
    assert btn.property("testid") == "mcp-prompt-btn-search-in"


def test_widget_accepts_ptbr_actions(qtbot):
    for action in (
        "Criar arquivo",
        "Otimizar",
        "Criar tasks",
        "Revisar tasks",
        "Executar",
        "Revisar execucao",
        "Loop prepare",
    ):
        btn = MCPPromptButton(
            label=action,
            button_type="Claude",
            prompt="x",
            action=action,  # type: ignore[arg-type]
            target_path="terminal-interactive-output",
        )
        qtbot.addWidget(btn)
        assert btn.payload()["action"] == action
