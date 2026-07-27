"""Integracao das specs suplementares na grade Brainstorm (AGENT-TASK-008).

Cobre o contrato de `brainstorm-buttons-grid` quando o registry de
`agent_integration_specs` tem entradas Brainstorm: botao `MCPPromptButton`
suplementar materializado DEPOIS dos 24 seeds canonicos, pelo MESMO builder no
build inicial e no rebuild pos-save do gear.

Invariantes provadas aqui:

- cardinalidade: `_load_brainstorm_seeds()` continua devolvendo exatamente 24
  seeds e `_brainstorm_mcp_btns` continua tendo exatamente 24 botoes, com ou sem
  suplementos (os suplementos vivem em `_brainstorm_agent_btns`);
- loader canonico intocado: nenhuma spec suplementar vira 25o arquivo `NN-*.md`
  nem aparece na lista devolvida pelo loader;
- action: so e aceita a action presente nos DOIS registries
  (`VALID_ACTIONS` do widget E `ACTION_LITERALS` do builder de prompt) — uma
  action legada como `send`, valida para o widget mas sem literal, e recusada;
- persistencia visual: salvar o gear (rebuild) nao remove nem duplica o
  suplemento, porque ele e relido do registry e nao de estado de widget;
- fail-safe: registry invalido, colisao com seed ou colisao de testid degradam
  para zero suplementos sem derrubar os 24 seeds.

Os testes NAO instanciam a MainWindow inteira: exercitam os metodos reais
(`_build_brainstorm_grid_buttons`, `_collect_brainstorm_agent_specs`,
`_rebuild_brainstorm_grid`) via `_GridStub`, no mesmo idioma de
`_FakeMainWindow` em test_brainstorm_mcp_grade.py. O registry canonico e vazio
por design (as specs sao acrescentadas por `/mcp:create-agent`), entao cada
teste injeta as suas via monkeypatch de
`workflow_app.agent_integration_specs.brainstorm_agent_specs`.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from PySide6.QtWidgets import QGridLayout, QWidget

from workflow_app import agent_integration_specs as specs_mod
from workflow_app.agent_integration_specs import (
    AgentIntegrationSpecError,
    BrainstormAgentSpec,
)
from workflow_app.main_window import MainWindow, _BrainstormSeedError
from workflow_app.widgets.mcp_prompt_actions import ACTION_LITERALS
from workflow_app.widgets.mcp_prompt_button import VALID_ACTIONS, MCPPromptButton

SEED_COUNT = 24
COLUMNS = 4


# ── Helpers ──────────────────────────────────────────────────────────────────


def _seed(index: int, **over) -> dict:
    """Seed no shape exato devolvido por `_load_brainstorm_seeds()`."""
    seed = {
        "slug": f"seed-{index:02d}",
        "label": f"Seed {index:02d}",
        "button_type": "Claude",
        "action": "Revisar",
        "agent_name": f"agente-{index:02d}",
        "agent_path": f"agents/agente-{index:02d}.md",
        "target_terminal": "terminal-interactive-output",
        "target_path_edit_inplace": False,
        "seed_path": Path(f"blacksmith/brainstorm-mcp/{index:02d}-seed.md"),
    }
    seed.update(over)
    return seed


def _seeds(count: int = SEED_COUNT) -> list[dict]:
    return [_seed(i) for i in range(1, count + 1)]


def _spec(slug: str = "hardening-suplementar", **over) -> BrainstormAgentSpec:
    kwargs = {
        "slug": slug,
        "label": "hardening+",
        "button_type": "Claude",
        "action": "Revisar",
        "agent_name": "hardening engineer",
        "agent_path": "ai-forge/MCP/agents/hardening-engineer-rules.md",
        "prompt_path": "blacksmith/brainstorm-mcp/hardening-suplementar.md",
    }
    kwargs.update(over)
    return BrainstormAgentSpec(**kwargs)


class _GridStub:
    """Stub minimo de MainWindow para exercitar os metodos reais da grade.

    Reusa o codigo de producao via `MainWindow.<metodo>(self, ...)` — evita
    instanciar a MainWindow inteira (QMainWindow + setup pesado), mantendo os
    caminhos de build/rebuild os MESMOS que rodam em producao.
    """

    _BRAINSTORM_GRID_COLUMNS = COLUMNS
    _BRAINSTORM_SEED_COUNT = SEED_COUNT

    def __init__(self, repo_root: Path, seeds: list[dict]) -> None:
        self._fake_root = repo_root
        self._seeds = seeds
        self._seed_error: str | None = None
        self._brainstorm_mcp_btns: list[MCPPromptButton] = []
        self._brainstorm_agent_btns: list[MCPPromptButton] = []
        self.published: list[dict] = []
        self.grid_widget = QWidget()
        self._brainstorm_grid_layout = QGridLayout(self.grid_widget)

    # deps reais consumidas pelos metodos sob teste
    def _systemforge_root(self) -> Path:
        return self._fake_root

    def _current_llm_provider(self) -> str:
        # I2.1: substitui o antigo `_brainstorm_runtime_type`; o provider
        # runtime vem do Main LLM (queue-div-main-llm).
        return "claude"

    def _get_brainstorm_runtime_provider(self) -> str:
        return "Claude"

    def _on_mcp_prompt_requested(self, payload: dict) -> None:
        self.published.append(payload)

    def _codex_terminal_available(self) -> bool:
        return False

    def _load_brainstorm_seeds(self) -> list[dict]:
        if self._seed_error is not None:
            raise _BrainstormSeedError(self._seed_error)
        return self._seeds

    # metodos de producao sob teste
    def _collect_brainstorm_agent_specs(self, seed_slugs, existing_testids):
        return MainWindow._collect_brainstorm_agent_specs(
            self, seed_slugs, existing_testids
        )

    def _make_brainstorm_prompt_button(self, **kwargs):
        return MainWindow._make_brainstorm_prompt_button(self, **kwargs)

    def _build_brainstorm_grid_buttons(self, seeds):
        return MainWindow._build_brainstorm_grid_buttons(self, seeds)

    def _place_brainstorm_buttons(self, layout, buttons) -> None:
        MainWindow._place_brainstorm_buttons(self, layout, buttons)

    def _rebuild_brainstorm_grid(self) -> None:
        MainWindow._rebuild_brainstorm_grid(self)

    # helpers de leitura da grade materializada
    def grid_testids(self) -> list[str]:
        layout = self._brainstorm_grid_layout
        out = []
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if widget is not None:
                out.append(str(widget.property("testid")))
        return out

    def position_of(self, testid: str) -> tuple[int, int]:
        layout = self._brainstorm_grid_layout
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if widget is not None and str(widget.property("testid")) == testid:
                row, col, _rs, _cs = layout.getItemPosition(i)
                return row, col
        raise AssertionError(f"testid ausente na grade: {testid}")


@pytest.fixture
def stub(qapp, tmp_path):
    """Stub com os 24 seeds canonicos e uma grade real vazia."""
    return _GridStub(tmp_path, _seeds())


@pytest.fixture
def registry(monkeypatch):
    """Injeta specs Brainstorm no registry (canonicamente vazio)."""

    def _set(*specs: BrainstormAgentSpec) -> None:
        monkeypatch.setattr(
            specs_mod, "brainstorm_agent_specs", lambda: tuple(specs)
        )

    return _set


# ── Cardinalidade: os 24 seeds continuam sendo 24 ────────────────────────────


def test_registry_vazio_nao_muda_a_grade(stub):
    """Contrato de zero-impacto: sem specs, nada de novo aparece."""
    seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)

    assert len(seed_btns) == SEED_COUNT
    assert agent_btns == []


def test_suplementos_nao_entram_na_lista_de_seeds(stub, registry):
    """`_brainstorm_mcp_btns` continua sendo exatamente os 24 canonicos."""
    registry(_spec(), _spec(slug="ux-suplementar", label="ux+"))

    seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)

    assert len(seed_btns) == SEED_COUNT
    assert len(agent_btns) == 2
    seed_slugs = {s["slug"] for s in stub._seeds}
    for btn in agent_btns:
        assert str(btn.property("testid")).removeprefix("mcp-prompt-btn-") not in (
            seed_slugs
        )


def test_suplemento_nao_entra_no_loader_canonico(stub, registry, tmp_path):
    """Uma spec nunca vira 25o arquivo `NN-*.md` nem aparece no loader."""
    registry(_spec())

    loaded = stub._load_brainstorm_seeds()

    assert len(loaded) == SEED_COUNT
    assert "hardening-suplementar" not in {s["slug"] for s in loaded}


# ── Ordenacao: suplementos DEPOIS dos 24 seeds ───────────────────────────────


def test_suplementos_vem_depois_dos_seeds_na_ordem_do_registry(stub, registry):
    registry(
        _spec(slug="primeiro", label="1o"),
        _spec(slug="segundo", label="2o"),
    )

    seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)
    ordered = [str(b.property("testid")) for b in seed_btns + agent_btns]

    assert ordered[SEED_COUNT:] == [
        "mcp-prompt-btn-primeiro",
        "mcp-prompt-btn-segundo",
    ]


def test_posicao_no_grid_segue_row_major_apos_o_24o_seed(stub, registry):
    """24 seeds ocupam as linhas 0..5 (4 colunas); o 25o cai em (6, 0)."""
    registry(_spec(slug="primeiro"), _spec(slug="segundo"))
    _materialize(stub)

    assert stub.position_of("mcp-prompt-btn-primeiro") == (SEED_COUNT // COLUMNS, 0)
    assert stub.position_of("mcp-prompt-btn-segundo") == (SEED_COUNT // COLUMNS, 1)


# ── Action: aceita nos DOIS registries ───────────────────────────────────────


def test_action_precisa_existir_nos_dois_registries():
    """`send` e valida para o widget mas nao tem literal: spec recusada."""
    legacy_only = sorted(set(VALID_ACTIONS) - set(ACTION_LITERALS))
    assert legacy_only, "cenario exige ao menos uma action sem literal"

    with pytest.raises(AgentIntegrationSpecError) as exc:
        _spec(action=legacy_only[0])

    assert exc.value.field == "action"


def test_action_da_spec_chega_intacta_no_botao(stub, registry):
    registry(_spec(action="Criar tasks"))

    _seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)

    assert agent_btns[0].payload()["action"] == "Criar tasks"
    assert "Criar tasks" in VALID_ACTIONS
    assert "Criar tasks" in ACTION_LITERALS


def test_codex_resolve_terminal_t3_no_botao(stub, registry):
    registry(_spec(slug="codex-suplementar", button_type="Codex"))

    _seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)

    assert agent_btns[0].payload()["target_path"] == "terminal-codex-output"


def test_prompt_path_resolve_contra_o_repo_root(stub, registry, tmp_path):
    registry(_spec())

    _seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)

    assert agent_btns[0].payload()["prompt"] == str(
        tmp_path / "blacksmith/brainstorm-mcp/hardening-suplementar.md"
    )


def test_botao_suplementar_tem_a_mesma_decoracao_do_seed(stub, registry):
    """Altura, largura minima e signal conectado sao os do builder comum."""
    registry(_spec())

    seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)
    supplement = agent_btns[0]

    assert supplement.height() == seed_btns[0].height()
    assert supplement.minimumWidth() == seed_btns[0].minimumWidth()
    supplement.prompt_requested.emit({"button_id": "mcp-prompt-btn-x"})
    assert stub.published == [{"button_id": "mcp-prompt-btn-x"}]


# ── Fail-safe: suplemento ruim nunca derruba os 24 seeds ─────────────────────


def test_colisao_de_slug_com_seed_descarta_suplementos(stub, registry, caplog):
    registry(_spec(slug="seed-01"))

    seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)

    assert len(seed_btns) == SEED_COUNT
    assert agent_btns == []
    assert "seed-01" in caplog.text


def test_colisao_de_testid_com_seed_descarta_suplementos(stub, registry, caplog):
    """Testid do suplemento igual ao de um seed ja montado."""
    stub._seeds = [_seed(1, slug="hardening-suplementar")] + _seeds()[1:]
    # slug do seed difere do da spec so no registro; o testid colide.
    registry(_spec(slug="hardening-suplementar"))

    seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)

    assert len(seed_btns) == SEED_COUNT
    assert agent_btns == []
    assert caplog.text


def test_registry_que_levanta_degrada_para_zero_suplementos(
    stub, monkeypatch, caplog
):
    def _boom():
        raise AgentIntegrationSpecError("registry corrompido", field="slug")

    monkeypatch.setattr(specs_mod, "brainstorm_agent_specs", _boom)

    seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)

    assert len(seed_btns) == SEED_COUNT
    assert agent_btns == []
    assert "registry corrompido" in caplog.text


def test_falha_ao_materializar_suplemento_preserva_os_seeds(
    stub, registry, monkeypatch, caplog
):
    """Kwargs invalidos (widget recusa) degradam sem matar a grade."""
    registry(_spec())
    monkeypatch.setattr(
        specs_mod,
        "brainstorm_button_kwargs",
        lambda spec, **_kw: {
            "label": spec.label,
            "button_type": spec.button_type,
            "prompt": "x.md",
            "action": "action-inexistente",
        },
    )

    seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)

    assert len(seed_btns) == SEED_COUNT
    assert agent_btns == []
    assert "ignorada" in caplog.text


def test_falha_em_seed_continua_atomica_e_re_raise(stub, registry):
    """Politica all-or-nothing dos seeds nao mudou com o builder comum."""
    registry(_spec())
    stub._seeds = [_seed(1, action="action-inexistente")] + _seeds()[1:]

    with pytest.raises(ValueError):
        stub._build_brainstorm_grid_buttons(stub._seeds)


# ── Persistencia visual: salvar o gear nao remove nem duplica ────────────────


def _materialize(stub) -> None:
    """Materializa a grade no layout como faz `_build_brainstorm_page`."""
    seed_btns, agent_btns = stub._build_brainstorm_grid_buttons(stub._seeds)
    for i, btn in enumerate(seed_btns + agent_btns):
        stub._brainstorm_grid_layout.addWidget(btn, i // COLUMNS, i % COLUMNS)
    stub._brainstorm_mcp_btns = seed_btns
    stub._brainstorm_agent_btns = agent_btns


def test_rebuild_preserva_o_suplemento(stub, registry, qapp):
    registry(_spec())
    _materialize(stub)
    assert "mcp-prompt-btn-hardening-suplementar" in stub.grid_testids()

    stub._rebuild_brainstorm_grid()
    qapp.processEvents()

    assert len(stub._brainstorm_mcp_btns) == SEED_COUNT
    assert len(stub._brainstorm_agent_btns) == 1
    assert "mcp-prompt-btn-hardening-suplementar" in stub.grid_testids()


def test_rebuilds_sucessivos_nao_acumulam_widgets(stub, registry, qapp):
    registry(_spec(), _spec(slug="ux-suplementar"))
    _materialize(stub)
    baseline = stub.grid_testids()

    for _ in range(3):
        stub._rebuild_brainstorm_grid()
        qapp.processEvents()

    testids = stub.grid_testids()
    assert testids == baseline
    assert len(testids) == len(set(testids)) == SEED_COUNT + 2


def test_rebuild_destroi_os_botoes_antigos(stub, registry, qapp):
    """Seeds E suplementos antigos morrem: nenhum sobrevive como duplicata.

    `deleteLater()` so materializa a destruicao quando o evento
    `DeferredDelete` e drenado — `processEvents()` sozinho nao o entrega.
    """
    import shiboken6
    from PySide6.QtCore import QEvent

    registry(_spec())
    _materialize(stub)
    antigos = list(stub._brainstorm_mcp_btns) + list(stub._brainstorm_agent_btns)
    assert len(antigos) == SEED_COUNT + 1

    stub._rebuild_brainstorm_grid()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert not any(shiboken6.isValid(btn) for btn in antigos)


def test_spec_registrada_depois_do_build_aparece_no_rebuild(
    stub, registry, qapp
):
    """Gear salvo apos `/mcp:create-agent` materializa o botao novo."""
    _materialize(stub)
    assert stub._brainstorm_agent_btns == []

    registry(_spec(slug="novo-agente"))
    stub._rebuild_brainstorm_grid()
    qapp.processEvents()

    assert "mcp-prompt-btn-novo-agente" in stub.grid_testids()
    assert len(stub._brainstorm_mcp_btns) == SEED_COUNT


def test_spec_removida_some_no_rebuild(stub, registry, monkeypatch, qapp):
    registry(_spec(slug="temporario"))
    _materialize(stub)
    assert "mcp-prompt-btn-temporario" in stub.grid_testids()

    monkeypatch.setattr(specs_mod, "brainstorm_agent_specs", tuple)
    stub._rebuild_brainstorm_grid()
    qapp.processEvents()

    assert "mcp-prompt-btn-temporario" not in stub.grid_testids()
    assert stub._brainstorm_agent_btns == []


def test_rebuild_com_seed_quebrado_zera_as_duas_listas(stub, registry, qapp):
    registry(_spec())
    _materialize(stub)
    stub._seed_error = "seed 07 sumiu"

    stub._rebuild_brainstorm_grid()
    qapp.processEvents()

    assert stub._brainstorm_mcp_btns == []
    assert stub._brainstorm_agent_btns == []
    assert stub.grid_testids() == []


def test_ordem_no_grid_e_identica_entre_build_e_rebuild(stub, registry, qapp):
    registry(_spec(slug="primeiro"), _spec(slug="segundo"))
    _materialize(stub)
    antes = stub.grid_testids()

    stub._rebuild_brainstorm_grid()
    qapp.processEvents()

    assert stub.grid_testids() == antes


# ── Fonte unica: build e rebuild consomem o MESMO builder ────────────────────


@pytest.mark.parametrize(
    "func", [MainWindow._build_brainstorm_page, MainWindow._rebuild_brainstorm_grid]
)
def test_ambos_os_caminhos_delegam_ao_builder_comum(func):
    """Nenhum dos dois instancia MCPPromptButton por conta propria."""
    source = inspect.getsource(func)

    assert source.count("_build_brainstorm_grid_buttons(seeds)") == 1
    assert "MCPPromptButton(" not in source
