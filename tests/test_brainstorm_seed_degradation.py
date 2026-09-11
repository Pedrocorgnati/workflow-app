"""C3 - carga degradavel por item da grade brainstorm (Task 10 e 11).

Loop de origem: `08-25-systemforge-analise-fluxo-brainstorm`, bloco C3
(resiliencia). Antes desta mudanca `_load_brainstorm_seeds` era fail-fast
all-or-nothing: UM seed corrompido em disco zerava a grade inteira (A3 / G5).

Cobertura:

1. degradacao: um seed invalido produz `N-1` botoes canonicos mais o
   suplemento e UMA `issue`, sem `_BrainstormSeedError` propagada.
2. identidade: nenhum arquivo do diretorio PAI (output `MM-DD-*.md`,
   companion `*-tasks.md`, `INDEX.md`) e classificado como seed.
3. ordem de insercao da grade nos DOIS ramos (flow de producao e
   fallback de grade), sem assertar linhas nem colunas.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from workflow_app.brainstorm_seed_contract import (
    BRAINSTORM_SEEDS_RELDIR,
    CANONICAL_SEED_COUNT,
    CANONICAL_SEED_FILENAMES,
)
from workflow_app.main_window import MainWindow, _BrainstormSeedError

_AGENT_REL = "agents/persona-stub.md"


def _seed_text(slug: str) -> str:
    return (
        "---\n"
        f'slug: "{slug}"\n'
        f'title: "Seed - Botao X - {slug}"\n'
        'button_type: "Claude"\n'
        f'agent_name: "agent-{slug}"\n'
        f'agent_path: "{_AGENT_REL}"\n'
        'action: "Otimizar"\n'
        "target_path: true\n"
        'target_terminal: "terminal-interactive-output"\n'
        "---\n\n# body\n\n"
        "## Prompt canonico\n\n"
        f"Corpo canonico sintetico do seed {slug}.\n"
    )


def _slug_of(filename: str) -> str:
    """Slug canonico de um seed: `NN-<slug>.md` -> `<slug>`."""
    return filename[3:-3]


#: Vitimas dos cenarios de corrupcao, escolhidas por POSICAO na tupla canonica.
#: Indices, nao literais: assim o teste sobrevive a um rename de seed sem virar
#: fixture-que-inventa-identidade de novo.
_VICTIM_5 = CANONICAL_SEED_FILENAMES[4]
_VICTIM_3 = CANONICAL_SEED_FILENAMES[2]
_VICTIM_11 = CANONICAL_SEED_FILENAMES[10]
_VICTIM_7 = CANONICAL_SEED_FILENAMES[6]


def _materialize(tmp_path: Path) -> Path:
    """Cria um repo sintetico com os N seeds canonicos e a persona alvo.

    Os nomes sao DERIVADOS de `CANONICAL_SEED_FILENAMES`, nunca inventados.
    A versao anterior gerava `01-seed-01.md .. 24-seed-24.md`, o que so fazia
    sentido contra um loader que descobria por PREFIXO. Depois que a Task 10
    trocou a descoberta por membership na tupla fechada, essa fixture passou a
    materializar 24 intrusos e zero seeds: os cenarios de degradacao mediam um
    repo sem nenhum seed canonico, nao um seed corrompido no meio de N sadios.
    """
    repo_root = tmp_path / "repo"
    seeds_dir = repo_root / BRAINSTORM_SEEDS_RELDIR
    seeds_dir.mkdir(parents=True)
    agent_abs = repo_root / _AGENT_REL
    agent_abs.parent.mkdir(parents=True, exist_ok=True)
    agent_abs.write_text("# persona stub\n", encoding="utf-8")
    for filename in CANONICAL_SEED_FILENAMES:
        (seeds_dir / filename).write_text(
            _seed_text(_slug_of(filename)), encoding="utf-8"
        )
    return repo_root


class _LoaderStub:
    """Stub minimo que reusa o loader real sem subir a MainWindow."""

    def __init__(self, repo_root: Path) -> None:
        self._fake_root = repo_root

    def _systemforge_root(self) -> Path:
        return self._fake_root

    def _brainstorm_seeds_dir(self) -> Path:
        return MainWindow._brainstorm_seeds_dir(self)  # type: ignore[arg-type]

    def _load_one_brainstorm_seed(self, path, root):
        return MainWindow._load_one_brainstorm_seed(  # type: ignore[arg-type]
            self, path, root
        )

    def _load_brainstorm_seeds(self):
        return MainWindow._load_brainstorm_seeds(self)  # type: ignore[arg-type]


# ── 1. Degradacao ───────────────────────────────────────────────────────────


def test_corrupted_seed_degrades_instead_of_zeroing_grid(tmp_path):
    """Seed corrompido: N-1 seeds sobem e a falha vira `issue` identificada."""
    repo_root = _materialize(tmp_path)
    victim = repo_root / BRAINSTORM_SEEDS_RELDIR / _VICTIM_5
    victim.write_text(
        f"---\nslug: {_slug_of(_VICTIM_5)}\n\t button_type: Claude\n---\n",
        encoding="utf-8",
    )
    stub = _LoaderStub(repo_root)

    seeds, issues = stub._load_brainstorm_seeds()

    assert len(seeds) == CANONICAL_SEED_COUNT - 1
    assert all(s["slug"] != _slug_of(_VICTIM_5) for s in seeds)
    assert [i["filename"] for i in issues] == [_VICTIM_5]
    assert "yaml malformado" in issues[0]["reason"]


def test_corrupted_seed_never_raises(tmp_path):
    """Nenhum caminho da carga degradavel propaga `_BrainstormSeedError`."""
    repo_root = _materialize(tmp_path)
    for name in (_VICTIM_3, _VICTIM_11):
        (repo_root / BRAINSTORM_SEEDS_RELDIR / name).write_text(
            "---\nnao_e_seed: 1\n---\n", encoding="utf-8"
        )
    stub = _LoaderStub(repo_root)

    try:
        seeds, issues = stub._load_brainstorm_seeds()
    except _BrainstormSeedError as exc:  # pragma: no cover - regressao C3
        pytest.fail(f"carga degradavel nao pode propagar excecao: {exc}")

    assert len(seeds) == CANONICAL_SEED_COUNT - 2
    assert len(issues) == 2


def test_single_seed_failure_keeps_remaining_seeds_loadable(tmp_path):
    """Seed incompleto: os N-1 restantes continuam CARREGAVEIS.

    Escopo deliberado: LOADER. O nome anterior
    (`..._keeps_button_grid_populated`) prometia grade, mas o corpo nunca
    construia botao, suplemento nem superficie de issue — um builder que
    devolvesse zero widgets passaria aqui. A grade real (N-1 botoes canonicos
    + suplemento + issues publicadas) e provada em
    `tests/test_brainstorm_agent_specs_integration.py::
    test_rebuild_com_seed_quebrado_degrada_por_item`.
    """
    repo_root = _materialize(tmp_path)
    (repo_root / BRAINSTORM_SEEDS_RELDIR / _VICTIM_7).write_text(
        f"---\nslug: {_slug_of(_VICTIM_7)}\n---\n", encoding="utf-8"
    )
    stub = _LoaderStub(repo_root)
    seeds, issues = stub._load_brainstorm_seeds()

    assert len(issues) == 1
    assert issues[0]["filename"] == _VICTIM_7
    assert len(seeds) == CANONICAL_SEED_COUNT - 1
    assert _slug_of(_VICTIM_7) not in [s["slug"] for s in seeds]


# ── 2. Identidade: o diretorio PAI nao contem seeds ─────────────────────────


_CLASSIFY_PATH = (
    Path(__file__).resolve().parents[3] / "ai-forge" / "scripts" / "_brainstorm_classify.py"
)

#: O repo aninhado pode ser clonado standalone; nesse caso o modulo da raiz
#: nao existe e os testes de identidade sao pulados em vez de quebrarem.
_requires_classify = pytest.mark.skipif(
    not _CLASSIFY_PATH.is_file(),
    reason=f"modulo de classificacao da raiz ausente: {_CLASSIFY_PATH}",
)


def _classify_module():
    """Carrega `_brainstorm_classify` por path, sem tocar em `sys.path`.

    D14 fecha os CONSUMIDORES de producao do modulo em exatamente dois
    (`validate-brainstorm-md.py` e `brainstorm-mcp-observability.py`). Um
    teste que ASSERTA o contrato do modulo nao e um terceiro consumidor:
    ele nao adiciona dependencia em runtime, e a Task 11 exige o teste de
    identidade explicitamente.
    """
    spec = importlib.util.spec_from_file_location(
        "_brainstorm_classify_undertest", _CLASSIFY_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@_requires_classify
@pytest.mark.parametrize(
    "name",
    [
        "INDEX.md",
        "08-24-systemforge-analise-fluxo-brainstorm.md",
        "08-24-systemforge-analise-fluxo-brainstorm-tasks.md",
        "PROGRESS-05-24.md",
        "task-001-preparo.md",
    ],
)
def test_parent_dir_artifacts_are_never_classified_as_seed(name):
    """Output, companion e legado do diretorio pai nunca viram `seed`."""
    classify = _classify_module()
    assert classify.classify(name) != "seed"


@_requires_classify
def test_classifier_parses_exactly_the_canonical_tuple():
    """O parser da raiz enxerga a MESMA tupla fechada que o app importa.

    Derivar o esperado de `load_canonical_seed_filenames()` — a propria
    funcao sob teste — tornava o caso tautologico: um parser que devolvesse
    tupla vazia fazia o laco passar sem executar UMA assercao sequer, e uma
    divergencia entre a tupla da raiz e a do app passava despercebida.
    """
    classify = _classify_module()
    assert tuple(classify.load_canonical_seed_filenames()) == CANONICAL_SEED_FILENAMES


@_requires_classify
@pytest.mark.parametrize("fname", CANONICAL_SEED_FILENAMES)
def test_canonical_names_are_classified_as_seed(fname):
    """Cada nome da tupla fechada e classificado como `seed`.

    Parametrizado pela tupla IMPORTADA do contrato, nao pela leitura que o
    modulo sob teste faz dela.
    """
    assert _classify_module().classify(fname) == "seed"


@_requires_classify
@pytest.mark.parametrize(
    "impostor",
    [
        "14-outra-coisa.md",
        f"25-{_slug_of(CANONICAL_SEED_FILENAMES[-1])}.md",
        "07-impostor.md",
    ],
)
def test_same_prefix_impostor_is_not_a_seed(impostor):
    """Prefixo NAO e identidade: nome fora da tupla nunca e `seed`."""
    assert impostor not in CANONICAL_SEED_FILENAMES
    assert _classify_module().classify(impostor) != "seed"


@_requires_classify
def test_supplemental_is_not_a_canonical_seed():
    classify = _classify_module()
    assert classify.classify("search-prod.md") == "supplemental"


# ── 3. Ordem row-major, sem geometria ──────────────────────────────────────


class _OrderStub:
    _BRAINSTORM_GRID_COLUMNS = 4


class _RecordingLayout:
    """Layout falso que registra a ORDEM de insercao, nunca a geometria."""

    def __init__(self) -> None:
        self.order: list[object] = []

    def addWidget(self, widget, *_args) -> None:  # noqa: N802 - API Qt
        self.order.append(widget)


def test_place_buttons_preserves_order_in_fallback_grid():
    """Ramo FALLBACK (`QGridLayout`): insere na ordem da lista recebida.

    O criterio e a ORDEM, nao `4x6`: a geometria de grade pertence ao
    fallback e o aceite proibiu depender de linhas e colunas.
    """
    buttons = [f"btn-{i:02d}" for i in range(CANONICAL_SEED_COUNT)]
    layout = _RecordingLayout()

    MainWindow._place_brainstorm_buttons(  # type: ignore[arg-type]
        _OrderStub(), layout, buttons
    )

    assert layout.order == buttons


def test_place_buttons_preserves_order_in_production_flow_layout(qapp):
    """Ramo de PRODUCAO (`ResponsiveButtonFlowLayout`): mesma ordem.

    `_RecordingLayout` so percorre o fallback — inverter APENAS o ramo de
    producao passaria batido por ele. Aqui o layout real e exercitado, e a
    assercao continua sendo a sequencia de insercao, nunca a geometria.

    `ResponsiveButtonFlowLayout` mora em `command_queue/`, caminho protegido
    pela premissa 4.1 do loop: importado somente para LEITURA.
    """
    from PySide6.QtWidgets import QPushButton, QWidget

    from workflow_app.command_queue.command_queue_widget import (
        ResponsiveButtonFlowLayout,
    )

    host = QWidget()
    layout = ResponsiveButtonFlowLayout(host)
    buttons = [QPushButton(f"btn-{i:02d}", host) for i in range(CANONICAL_SEED_COUNT)]

    MainWindow._place_brainstorm_buttons(  # type: ignore[arg-type]
        _OrderStub(), layout, buttons
    )

    inseridos = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert inseridos == buttons
