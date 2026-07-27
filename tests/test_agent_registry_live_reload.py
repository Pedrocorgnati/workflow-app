"""Testes do refresh em runtime do registry de specs (finding 010 E-3).

`/mcp:create-agent` reescreve `agent_integration_specs.py` com o workflow-app
aberto. Antes de `MainWindow._load_agent_registry`, os consumidores faziam
`from workflow_app.agent_integration_specs import ...` dentro da funcao, o que
resolve `sys.modules` e devolve as tuplas do PRIMEIRO import: a spec recem
criada so aparecia depois de reiniciar o app, contrariando o que
`ai-forge/rules/workflow-app-agent-creation.md` promete.

O que estes testes provam:
- edicao PERSISTIDA em disco entra no build seguinte, sem restart (E-3);
- o modulo cacheado em `sys.modules` continua intacto (W-3): a carga vai para um
  modulo anonimo, entao um registry malformado nao muta o objeto bom;
- registry quebrado degrada visivelmente para o ultimo valido (Zero Silencio);
- registry sem `brainstorm_button_kwargs` degrada para zero suplementos em vez
  de derrubar a grade inteira por ImportError (W-1).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QObject

from workflow_app import agent_integration_specs as specs_mod
from workflow_app import main_window as mw
from workflow_app.main_window import MainWindow

_MODULE_NAME = "workflow_app.agent_integration_specs"

_BRAINSTORM_ENTRY = """_BRAINSTORM_AGENT_SPECS: Final[tuple[BrainstormAgentSpec, ...]] = (
    BrainstormAgentSpec(
        slug="hardening-engineer",
        label="hardening",
        button_type="type-selector-radio-input",
        action="Otimizar",
        agent_name="hardening engineer",
        agent_path="ai-forge/MCP/agents/hardening-engineer-rules.md",
        prompt_path="blacksmith/brainstorm-mcp/07-24-criacao-de-agentes.md",
    ),
)"""

_MCP_ENTRY = """_MCP_AGENT_SPECS: Final[tuple[McpAgentSpec, ...]] = (
    McpAgentSpec(
        slug="hardening-engineer",
        label="hardening",
        directive=(
            "no papel de hardening engineer, conforme regras em "
            "ai-forge/MCP/agents/hardening-engineer-rules.md"
        ),
    ),
)"""


def _write_registry(tmp_path: Path, *, mcp: str = "", brainstorm: str = "") -> Path:
    """Materializa em disco uma copia do registry real com specs registradas.

    Reusa o codigo-fonte de producao de proposito: e exatamente o que
    `/mcp:create-agent` faz (substituir o literal vazio pelo literal populado),
    entao o teste exercita a forma real do arquivo, nao uma miniatura.
    """
    # `__spec__.origin`, nao `__file__`: `_point_registry_at` redireciona
    # `__file__`, e um segundo `_write_registry` no mesmo teste passaria a ler
    # o registry ja populado em vez do original.
    source = Path(specs_mod.__spec__.origin).read_text(encoding="utf-8")
    if mcp:
        old = "_MCP_AGENT_SPECS: Final[tuple[McpAgentSpec, ...]] = ()"
        assert old in source
        source = source.replace(old, mcp)
    if brainstorm:
        old = "_BRAINSTORM_AGENT_SPECS: Final[tuple[BrainstormAgentSpec, ...]] = ()"
        assert old in source
        source = source.replace(old, brainstorm)
    target = tmp_path / "agent_integration_specs.py"
    target.write_text(source, encoding="utf-8")
    return target


@pytest.fixture
def toasts(monkeypatch) -> list[tuple[str, str]]:
    """Captura os toasts de degradacao sem depender do signal_bus real."""
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mw,
        "signal_bus",
        type(
            "SB",
            (),
            {
                "toast_requested": type(
                    "S", (), {"emit": staticmethod(lambda m, k: captured.append((m, k)))}
                )()
            },
        )(),
    )
    return captured


@pytest.fixture(autouse=True)
def registry_servido_limpo(monkeypatch):
    """Zera o registry servido antes de cada teste deste modulo.

    `MainWindow._agent_registry_served` e estado de CLASSE (os dois coletores
    precisam do mesmo objeto). Sem este reset, o modulo sintetico carregado por
    um teste continuaria servido no teste seguinte — e, pior, vazaria para as
    suites de integracao que injetam specs por `monkeypatch` no modulo cacheado.
    `monkeypatch.setattr` restaura o valor anterior no teardown.
    """
    monkeypatch.setattr(MainWindow, "_agent_registry_served", None)


def _point_registry_at(monkeypatch, path: Path) -> None:
    """Faz `_load_agent_registry` ler `path` em vez do arquivo instalado."""
    monkeypatch.setattr(specs_mod, "__file__", str(path))


# ── E-3: edicao persistida entra sem restart ─────────────────────────────────


def test_edicao_persistida_aparece_sem_restart(tmp_path, monkeypatch, toasts):
    """Spec gravada em disco e visivel na carga seguinte (sem reiniciar o app)."""
    _point_registry_at(monkeypatch, _write_registry(tmp_path, brainstorm=_BRAINSTORM_ENTRY))

    registry = MainWindow._load_agent_registry("brainstorm-buttons-grid")

    specs = registry.brainstorm_agent_specs()
    assert len(specs) == 1
    assert specs[0].slug == "hardening-engineer"
    assert specs[0].testid == specs_mod.BRAINSTORM_TESTID_PREFIX + "hardening-engineer"
    assert toasts == []


def test_edicao_persistida_aparece_para_a_coluna_mcp(tmp_path, monkeypatch, toasts):
    """Mesmo contrato na superficie MCP da output-toolbar."""
    _point_registry_at(monkeypatch, _write_registry(tmp_path, mcp=_MCP_ENTRY))

    registry = MainWindow._load_agent_registry("output-toolbar-mcp")

    specs = registry.mcp_agent_specs()
    assert len(specs) == 1
    assert specs[0].slug == "hardening-engineer"
    assert toasts == []


# ── W-3: o modulo cacheado nunca e mutado ────────────────────────────────────


def test_modulo_cacheado_permanece_intacto(tmp_path, monkeypatch, toasts):
    """A carga vai para um modulo ANONIMO; `sys.modules` nao e trocado.

    E a diferenca material para `importlib.reload`, que re-executaria o modulo
    dentro do namespace existente e propagaria a edicao (inclusive uma edicao
    quebrada) para todo mundo que ja segurava o objeto.
    """
    _point_registry_at(monkeypatch, _write_registry(tmp_path, brainstorm=_BRAINSTORM_ENTRY))

    registry = MainWindow._load_agent_registry("brainstorm-buttons-grid")

    assert registry is not specs_mod
    assert sys.modules[_MODULE_NAME] is specs_mod
    assert specs_mod.brainstorm_agent_specs() == ()
    assert len(registry.brainstorm_agent_specs()) == 1


def test_registry_quebrado_cai_no_ultimo_valido_com_aviso(tmp_path, monkeypatch, toasts):
    """Registry invalido nao derruba nada e nao passa silenciosamente."""
    broken = tmp_path / "agent_integration_specs.py"
    broken.write_text("this is not valid python(\n", encoding="utf-8")
    _point_registry_at(monkeypatch, broken)

    registry = MainWindow._load_agent_registry("brainstorm-buttons-grid")

    # Ultimo registry valido continua servivel.
    assert registry is specs_mod
    assert registry.brainstorm_agent_specs() == ()
    # Zero Silencio: o operador precisa saber que a spec nova nao entrou.
    assert len(toasts) == 1
    assert toasts[0][1] == "warning"
    assert "brainstorm-buttons-grid" in toasts[0][0]


def test_registry_com_spec_invalida_degrada_sem_derrubar(tmp_path, monkeypatch, toasts):
    """Spec que viola o contrato levanta na execucao do modulo, e isso degrada."""
    invalid = _BRAINSTORM_ENTRY.replace('action="Otimizar"', 'action="Acao Inexistente"')
    _point_registry_at(monkeypatch, _write_registry(tmp_path, brainstorm=invalid))

    registry = MainWindow._load_agent_registry("brainstorm-buttons-grid")

    assert registry is specs_mod
    assert len(toasts) == 1
    assert toasts[0][1] == "warning"


def test_arquivo_sumido_cai_no_ultimo_valido(tmp_path, monkeypatch, toasts):
    """`__file__` apontando para path inexistente nao explode o build."""
    _point_registry_at(monkeypatch, tmp_path / "nao-existe.py")

    registry = MainWindow._load_agent_registry("output-toolbar-mcp")

    assert registry is specs_mod
    assert len(toasts) == 1
    assert toasts[0][1] == "warning"


# ── Gatilho: recarrega quando o arquivo muda, e SO quando ele muda ───────────


def test_arquivo_inalterado_devolve_o_mesmo_objeto(tmp_path, monkeypatch, toasts):
    """Sem edicao em disco, builds sucessivos servem o MESMO modulo.

    Nao e microotimizacao: se cada build recarregasse, as dataclasses seriam
    classes novas toda vez e dois objetos criados em builds diferentes deixariam
    de casar em `isinstance` — exatamente o defeito que o fix de 010 E-3 evita
    ao manter specs, validadores e builders vindos de uma unica origem.
    """
    _point_registry_at(monkeypatch, _write_registry(tmp_path, mcp=_MCP_ENTRY))

    primeiro = MainWindow._load_agent_registry("output-toolbar-mcp")
    segundo = MainWindow._load_agent_registry("output-toolbar-mcp")

    assert primeiro is segundo
    assert toasts == []


def test_edicao_posterior_dispara_nova_leitura(tmp_path, monkeypatch, toasts):
    """Reescrever o arquivo entre dois builds troca o registry servido."""
    alvo = _write_registry(tmp_path, mcp=_MCP_ENTRY)
    _point_registry_at(monkeypatch, alvo)

    antes = MainWindow._load_agent_registry("output-toolbar-mcp")
    assert len(antes.mcp_agent_specs()) == 1

    # `/mcp:create-agent` gravando a segunda persona no mesmo arquivo.
    _write_registry(tmp_path, mcp=_MCP_ENTRY.replace("hardening-engineer", "ux-writer"))

    depois = MainWindow._load_agent_registry("output-toolbar-mcp")

    assert depois is not antes
    assert [s.slug for s in depois.mcp_agent_specs()] == ["ux-writer"]
    assert toasts == []


def test_modulo_instalado_intocado_serve_o_cacheado(monkeypatch, toasts):
    """Com o arquivo canonico intacto, a primeira carga nao reexecuta nada.

    Este e o caminho de 100% dos testes de integracao que injetam specs por
    `monkeypatch` no modulo cacheado: se o loader recarregasse aqui, o patch
    deles apontaria para um objeto que a producao nao usa mais.
    """
    assert MainWindow._load_agent_registry("output-toolbar-mcp") is specs_mod
    assert MainWindow._load_agent_registry("brainstorm-buttons-grid") is specs_mod
    assert toasts == []


# ── Integracao com os coletores (identidade de dataclass) ────────────────────


class _CollectorStub(QObject):
    """Stub minimo para exercitar os coletores reais de `MainWindow`.

    Mesmo idioma dos demais stubs da suite: reusa o codigo de producao via
    `MainWindow.<metodo>(self, ...)` em vez de instanciar a QMainWindow.
    """

    def __init__(self, repo_root: Path) -> None:
        super().__init__()
        self._fake_root = repo_root

    def _systemforge_root(self) -> Path:
        return self._fake_root

    def collect_brainstorm(self, seed_slugs=(), existing_testids=()):
        return MainWindow._collect_brainstorm_agent_specs(
            self, list(seed_slugs), list(existing_testids)
        )

    def collect_mcp(self, existing_testids=()):
        return MainWindow._collect_mcp_agent_specs(self, list(existing_testids))


def test_coletor_brainstorm_usa_o_registry_relido(tmp_path, monkeypatch, toasts):
    """O coletor devolve a spec nova e guarda o MODULO de onde ela saiu.

    Guardar o modulo e o que mantem `isinstance(spec, BrainstormAgentSpec)`
    valido em `brainstorm_button_kwargs`: as dataclasses do modulo relido sao
    classes distintas das cacheadas, entao specs e builder tem que vir da mesma
    origem.
    """
    _point_registry_at(monkeypatch, _write_registry(tmp_path, brainstorm=_BRAINSTORM_ENTRY))
    stub = _CollectorStub(tmp_path)

    specs = stub.collect_brainstorm()

    assert len(specs) == 1
    registry = stub._brainstorm_agent_registry
    assert registry is not None
    assert isinstance(specs[0], registry.BrainstormAgentSpec)
    assert not isinstance(specs[0], specs_mod.BrainstormAgentSpec)
    kwargs = registry.brainstorm_button_kwargs(specs[0], repo_root=tmp_path)
    assert kwargs["testid_slug"] == "hardening-engineer"
    assert toasts == []


def test_coletor_brainstorm_respeita_colisao_de_seed(tmp_path, monkeypatch, toasts):
    """Colisao de slug com um seed canonico degrada para zero suplementos."""
    _point_registry_at(monkeypatch, _write_registry(tmp_path, brainstorm=_BRAINSTORM_ENTRY))
    stub = _CollectorStub(tmp_path)

    specs = stub.collect_brainstorm(seed_slugs=["hardening-engineer"])

    assert specs == ()
    assert stub._brainstorm_agent_registry is None
    assert len(toasts) == 1
    assert toasts[0][1] == "warning"


def test_coletor_mcp_usa_o_registry_relido(tmp_path, monkeypatch, toasts):
    _point_registry_at(monkeypatch, _write_registry(tmp_path, mcp=_MCP_ENTRY))
    stub = _CollectorStub(tmp_path)

    specs = stub.collect_mcp()

    assert len(specs) == 1
    assert specs[0].testid == "output-mcp-agent-hardening-engineer"
    assert toasts == []


def test_coletor_mcp_respeita_colisao_de_testid(tmp_path, monkeypatch, toasts):
    _point_registry_at(monkeypatch, _write_registry(tmp_path, mcp=_MCP_ENTRY))
    stub = _CollectorStub(tmp_path)

    specs = stub.collect_mcp(
        existing_testids=["output-mcp-agent-hardening-engineer"]
    )

    assert specs == ()
    assert len(toasts) == 1


# ── W-1: builder ausente degrada, nao derruba a grade ────────────────────────


def test_builder_ausente_preserva_os_seeds(tmp_path, monkeypatch, toasts):
    """Registry sem `brainstorm_button_kwargs` devolve os seeds, sem excecao.

    Antes do finding 010 W-1, o import do builder ficava FORA de qualquer guard,
    logo depois do coletor: um registry sem esse simbolo levantava ImportError e
    matava a grade inteira, inclusive os 24 seeds canonicos.
    """
    source = _write_registry(tmp_path, brainstorm=_BRAINSTORM_ENTRY)
    text = source.read_text(encoding="utf-8")
    text = text.replace("def brainstorm_button_kwargs(", "def _removido_do_registry(")
    text = text.replace('"brainstorm_button_kwargs",', "")
    source.write_text(text, encoding="utf-8")
    _point_registry_at(monkeypatch, source)

    class _GridStub(_CollectorStub):
        def _collect_brainstorm_agent_specs(self, seed_slugs, existing_testids):
            return MainWindow._collect_brainstorm_agent_specs(
                self, seed_slugs, existing_testids
            )

        def _make_brainstorm_prompt_button(self, **kwargs):  # pragma: no cover
            raise AssertionError("nao deveria montar botao sem builder")

    stub = _GridStub(tmp_path)
    seed_buttons, agent_buttons = MainWindow._build_brainstorm_grid_buttons(stub, [])

    assert seed_buttons == []
    assert agent_buttons == []
    assert len(toasts) == 1
    assert toasts[0][1] == "warning"
