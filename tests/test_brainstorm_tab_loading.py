"""Testes da aba brainstorm: carga dos 9 seeds + picker md + dispatch_result.

Cobre 4 cenarios canonicos do T2/T1 (loop 05-21-implantation-tasklist-aba-brainstorm):
- test_brainstorm_tab_loads_9_seeds_as_mcp_prompt_buttons: 9 botoes na grade.
- test_picker_md_opens_brainstorm_mcp_dir: picker abre em blacksmith/brainstorm-mcp/.
- test_picker_fallback_to_blacksmith_when_brainstorm_mcp_absent: fallback §7.5.
- test_dispatch_result_signal_marks_button_checkbox: signal_bus.dispatch_result
  marca/desmarca o checkbox do botao de origem (filtrado por button_id).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

pytestmark = pytest.mark.timeout(5)

from workflow_app.main_window import (
    MainWindow,
    _BrainstormSeedError,
)
from workflow_app.signal_bus import signal_bus
from workflow_app.widgets.mcp_prompt_button import MCPPromptButton


_SEED_BODY = dedent(
    """\
    ---
    schema_version: "1.0"
    slug: "{slug}"
    label: "{slug}"
    title: "Seed - {slug}"
    button_type: "Claude"
    agent_name: "agent-{slug}"
    agent_path: "agents/{slug}-rules.md"
    action: "Otimizar"
    target_path: "false"
    target_terminal: "terminal-interactive-output"
    ---

    # body
    """
)


def _materialize_9_seeds(repo_root: Path) -> Path:
    seeds_dir = repo_root / "blacksmith" / "brainstorm-mcp"
    agents_dir = repo_root / "agents"
    seeds_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)
    slugs = [
        ("01", "criar-md"),
        ("02", "pesquisar"),
        ("03", "controversial"),
        ("04", "hardening"),
        ("05", "criar-task"),
        ("06", "revisar-task"),
        ("07", "executar-task"),
        ("08", "revisar-execucao"),
        ("09", "revisar-qa"),
    ]
    for prefix, slug in slugs:
        (agents_dir / f"{slug}-rules.md").write_text(
            "# persona stub\n", encoding="utf-8"
        )
        (seeds_dir / f"{prefix}-{slug}.md").write_text(
            _SEED_BODY.format(slug=slug), encoding="utf-8"
        )
    return seeds_dir


class _FakeMainWindow:
    """Stub minimo para reusar `_load_brainstorm_seeds` sem subir MainWindow."""

    _BRAINSTORM_SEEDS_RELDIR = "blacksmith/brainstorm-mcp"

    def __init__(self, repo_root: Path) -> None:
        self._fake_root = repo_root

    def _systemforge_root(self) -> Path:
        return self._fake_root

    def _brainstorm_seeds_dir(self) -> Path:
        return MainWindow._brainstorm_seeds_dir(self)  # type: ignore[arg-type]

    def _load_brainstorm_seeds(self):
        return MainWindow._load_brainstorm_seeds(self)  # type: ignore[arg-type]


def test_brainstorm_tab_loads_9_seeds_as_mcp_prompt_buttons(tmp_path):
    """`_load_brainstorm_seeds` retorna 9 dicts ordenados por filename.

    Cobertura: contrato do loader que alimenta `_build_brainstorm_page`
    com `MCPPromptButton(label=slug, button_type=..., prompt=seed_path,
    ...)`. Cada seed precisa carregar campos canonicos do widget.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _materialize_9_seeds(repo_root)
    fake = _FakeMainWindow(repo_root)
    seeds = fake._load_brainstorm_seeds()
    assert len(seeds) == 9
    slugs = [s["slug"] for s in seeds]
    assert slugs == [
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
    for s in seeds:
        # Campos canonicos do widget.
        assert s["button_type"] in {
            "Claude",
            "Codex",
            "Kimi",
            "type-selector-radio-input",
        }
        assert isinstance(s["seed_path"], Path)
        assert s["agent_name"].startswith("agent-")
        assert s["agent_path"].startswith("agents/")


def test_seed_loader_ignores_date_prefixed_output_siblings(tmp_path):
    """Hardening 2026-05-24: outputs da acao 'Criar arquivo' (ex:
    05-24-foot-stock-....md) vivem na mesma pasta dos seeds. O prefixo de data
    MM- casa o glob 0[1-9]-*.md e fazia len(paths) > 9 -> grade inteira sumia.

    O loader deve filtrar esses irmaos (slug nao-alfabetico apos 0N-) e ainda
    retornar exatamente os 9 seeds canonicos. Regressao das duas sumiços de hoje.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_9_seeds(repo_root)
    # Simula as duas saidas reais que quebraram a grade em 2026-05-24.
    (seeds_dir / "05-24-foot-stock-ciclo-assinatura-planos.md").write_text(
        "# output do brainstorm\n", encoding="utf-8"
    )
    (seeds_dir / "05-24-foot-stock-bugfix-tasks.md").write_text(
        "# output do brainstorm\n", encoding="utf-8"
    )
    fake = _FakeMainWindow(repo_root)
    seeds = fake._load_brainstorm_seeds()
    assert len(seeds) == 9
    assert [s["slug"] for s in seeds] == [
        "criar-md", "pesquisar", "controversial", "hardening", "criar-task",
        "revisar-task", "executar-task", "revisar-execucao", "revisar-qa",
    ]


def test_seed_loader_still_fails_when_a_real_seed_is_missing(tmp_path):
    """O filtro nao pode mascarar a ausencia de um seed canonico real."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_9_seeds(repo_root)
    (seeds_dir / "09-revisar-qa.md").unlink()
    fake = _FakeMainWindow(repo_root)
    with pytest.raises(_BrainstormSeedError, match="esperado exatamente 9"):
        fake._load_brainstorm_seeds()


def test_picker_md_opens_brainstorm_mcp_dir(tmp_path):
    """Diretorio canonico `blacksmith/brainstorm-mcp/` resolvido pelo helper.

    Validamos o contrato do path canonico (sem instanciar QFileDialog real):
    `_brainstorm_seeds_dir` deve apontar para `{repo}/blacksmith/brainstorm-mcp`.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _materialize_9_seeds(repo_root)
    fake = _FakeMainWindow(repo_root)
    seeds_dir = fake._brainstorm_seeds_dir()
    assert seeds_dir.name == "brainstorm-mcp"
    assert seeds_dir.parent.name == "blacksmith"
    assert seeds_dir.is_dir()


def test_picker_fallback_to_blacksmith_when_brainstorm_mcp_absent(tmp_path):
    """Cenario §7.5: brainstorm-mcp inexistente -> fallback para blacksmith/.

    O loader original retorna `_BrainstormSeedError` ("diretorio inexistente")
    e o caller no main_window cai para `blacksmith/`. Validamos o branch
    do loader (fail-fast quando o canonico nao existe).
    """
    repo_root = tmp_path / "repo"
    (repo_root / "blacksmith").mkdir(parents=True)
    fake = _FakeMainWindow(repo_root)
    # Diretorio canonico ausente: o loader falha rapido.
    with pytest.raises(_BrainstormSeedError, match="diretorio inexistente"):
        fake._load_brainstorm_seeds()
    # Mas o fallback path (blacksmith/) existe e seria usado pelo picker.
    assert (repo_root / "blacksmith").is_dir()


def test_dispatch_result_signal_marks_button_checkbox(
    qtbot,
    mcp_prompt_button_factory,
    codex_alive_factory,
):
    """`signal_bus.dispatch_result.emit(button_id, True)` marca checkbox.

    Filtro por button_id: emit com outro button_id NAO afeta o botao.
    Emit com False desmarca + zera debounce.
    """
    codex_alive_factory(True)
    _, btn = mcp_prompt_button_factory(
        button_type="Claude",
        action="Executar",
        target_path="terminal-interactive-output",
        testid_slug="alvo",
    )
    assert btn._checkbox_state is False
    expected_button_id = btn._button_id

    # Emit com outro button_id: NAO deve marcar.
    signal_bus.dispatch_result.emit("mcp-prompt-btn-outro", True)
    qtbot.wait(10)
    assert btn._checkbox_state is False

    # Emit com button_id correto + sucesso: marca.
    signal_bus.dispatch_result.emit(expected_button_id, True)
    qtbot.wait(10)
    assert btn._checkbox_state is True

    # Emit com button_id correto + falha: desmarca.
    signal_bus.dispatch_result.emit(expected_button_id, False)
    qtbot.wait(10)
    assert btn._checkbox_state is False
    assert btn._last_dispatch_ns == 0
