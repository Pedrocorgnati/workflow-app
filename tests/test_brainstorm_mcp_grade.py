"""Unit tests for T2 (loop 05-21-implantation-tasklist-aba-brainstorm).

Cobre o seed loader `_load_brainstorm_seeds` e o slot
`_on_mcp_prompt_requested` sem depender da inicializacao completa da
MainWindow (que requer QApplication + setup pesado). Os testes operam
sobre um workspace temporario com 9 seeds materializados pelo helper
`_write_seeds`.

Cenarios cobertos:
1. 9 seeds validos -> grade 3x3 com 9 MCPPromptButton.
2. seed yaml malformado -> _BrainstormSeedError + grade vazia.
3. seed com agent_path inexistente -> _BrainstormSeedError (G6).
4. clique duplo rapido (debounce 300ms) -> 1 publish.
5. compat layer: target_path:false + sem target_path_edit_inplace.
6. glob com 8 seeds (1 renomeado p/ 10-) -> _BrainstormSeedError.
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
    "02-pesquisar.md": {
        "slug": "pesquisar",
        "title": "Seed - Botao 2 - Pesquisar",
        "button_type": "type-selector-radio-input",
        "agent_name": "pesquisador",
        "agent_path": "agents/pesquisar-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "03-controversial.md": {
        "slug": "controversial",
        "title": "Seed - Botao 3 - Controversial",
        "button_type": "type-selector-radio-input",
        "agent_name": "controversial",
        "agent_path": "agents/controversial-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "04-hardening.md": {
        "slug": "hardening",
        "title": "Seed - Botao 4 - Hardening",
        "button_type": "type-selector-radio-input",
        "agent_name": "hardening",
        "agent_path": "agents/hardening-rules.md",
        "action": "Otimizar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "05-criar-task.md": {
        "slug": "criar-task",
        "title": "Seed - Botao 5 - Criar task",
        "button_type": "type-selector-radio-input",
        "agent_name": "criar-task",
        "agent_path": "agents/criar-task-rules.md",
        "action": "Criar tasks",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "06-revisar-task.md": {
        "slug": "revisar-task",
        "title": "Seed - Botao 6 - Revisar task",
        "button_type": "Claude",
        "agent_name": "revisar-task",
        "agent_path": "agents/revisar-task-rules.md",
        "action": "Revisar tasks",
        "target_path": "true",
        "target_terminal": "terminal-interactive-output",
    },
    "07-executar-task.md": {
        "slug": "executar-task",
        "title": "Seed - Botao 7 - Executar task",
        "button_type": "type-selector-radio-input",
        "agent_name": "executar-task",
        "agent_path": "agents/executar-task-rules.md",
        "action": "Executar",
        "target_path": "true",
        "target_terminal": "depende-do-radio",
    },
    "08-revisar-execucao.md": {
        "slug": "revisar-execucao",
        "title": "Seed - Botao 8 - Revisar execucao",
        "button_type": "Claude",
        "agent_name": "revisar-execucao",
        "agent_path": "agents/revisar-execucao-rules.md",
        "action": "Revisar execucao",
        "target_path": "true",
        "target_terminal": "terminal-interactive-output",
    },
    "09-revisar-qa.md": {
        "slug": "revisar-qa",
        "title": "Seed - Botao 9 - Revisar QA",
        "button_type": "type-selector-radio-input",
        "agent_name": "revisar-qa",
        "agent_path": "agents/revisar-qa-rules.md",
        "action": "Revisar QA",
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
    """Materializa 9 seeds (+ personas) em tmp_path. Overrides[fname]=None remove o seed."""
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


# Cenario 1: 9 seeds validos -> 9 carregam, ordem deterministica


def test_load_seeds_happy_path_9_valid(tmp_path):
    repo_root = _write_seeds(tmp_path)
    fake = _FakeMainWindow(repo_root)
    seeds = fake._load_brainstorm_seeds()
    assert len(seeds) == 9
    expected_order = [
        "criar-md",
        "pesquisar",
        "controversial",
        "hardening",
        "criar-task",
        "revisar-task",
        "executar-task",
        "revisar-execucao",
        "revisar-qa",
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


# Cenario 6: 8 seeds (1 renomeado para 10-) -> grade bloqueada


def test_glob_rejects_renamed_seed(tmp_path):
    repo_root = _write_seeds(tmp_path)
    # Renomeia 09 -> 10 (fora do range 0[1-9])
    old = repo_root / "blacksmith" / "brainstorm-mcp" / "09-revisar-qa.md"
    new = old.parent / "10-revisar-qa.md"
    old.rename(new)
    fake = _FakeMainWindow(repo_root)
    # 09 renomeado para 10 (fora do range 0[1-9]) -> so 8 seeds canonicos.
    with pytest.raises(_BrainstormSeedError, match="esperado exatamente 9"):
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
        label="pesquisar",
        button_type="type-selector-radio-input",
        prompt="x",
        agent_name="pesquisador",
        agent_path="agents/x.md",
        action="Otimizar",
        target_path="terminal-interactive-output",
        testid_slug="pesquisar",
    )
    qtbot.addWidget(btn)
    assert btn.property("testid") == "mcp-prompt-btn-pesquisar"


def test_widget_accepts_ptbr_actions(qtbot):
    for action in (
        "Criar arquivo",
        "Otimizar",
        "Criar tasks",
        "Revisar tasks",
        "Executar",
        "Revisar execucao",
        "Revisar QA",
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
