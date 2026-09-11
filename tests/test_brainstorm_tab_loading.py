"""Testes da aba brainstorm: carga dos 24 seeds + picker md + dispatch_result.

Cobre 4 cenarios canonicos do T2/T1 (loop 05-21-implantation-tasklist-aba-brainstorm):
- test_brainstorm_tab_loads_24_seeds_as_mcp_prompt_buttons: 24 botoes na grade.
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

from workflow_app.brainstorm_seed_contract import (
    BRAINSTORM_SEEDS_RELDIR,
    CANONICAL_SEED_COUNT,
    CANONICAL_SEED_FILENAMES,
    KNOWN_ACTIONS,
    KNOWN_PERSONA_PATHS,
    validate_persona_action,
)
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

    ## Prompt canonico

    Corpo canonico sintetico do seed {slug}.
    """
)


def _slug_of(filename: str) -> str:
    """Slug canonico de um seed: `NN-<slug>.md` -> `<slug>`."""
    return filename[3:-3]


#: Slugs na ordem exata declarada pelo contrato.
CANONICAL_SLUGS = [_slug_of(n) for n in CANONICAL_SEED_FILENAMES]


def _materialize_24_seeds(repo_root: Path) -> Path:
    """Materializa a grade canonica DERIVANDO os nomes do contrato.

    A lista de slugs era digitada a mao aqui e havia divergido da tupla real:
    `02-search-in.md` onde o canonico e `02-pesquisar.md`, `13-repo-ruler.md`
    onde e `13-revisar-execucao.md`, `22-questioner.md` onde e
    `22-scaffolds-blueprints-updater.md`. Uma fixture que inventa identidade
    so consegue provar descoberta por PREFIXO, que e exatamente o criterio que
    a Task 10 removeu: o teste passava com 24 seeds enquanto um loader por
    membership apontaria varios canonicos ausentes.

    Derivando de `CANONICAL_SEED_FILENAMES`, a fixture falha no instante em
    que o loader deixa de honrar a tupla fechada.
    """
    seeds_dir = repo_root / BRAINSTORM_SEEDS_RELDIR
    agents_dir = repo_root / "agents"
    seeds_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)
    for filename in CANONICAL_SEED_FILENAMES:
        slug = _slug_of(filename)
        (agents_dir / f"{slug}-rules.md").write_text(
            "# persona stub\n", encoding="utf-8"
        )
        (seeds_dir / filename).write_text(
            _SEED_BODY.format(slug=slug), encoding="utf-8"
        )
    return seeds_dir


class _FakeMainWindow:
    """Stub minimo para reusar `_load_brainstorm_seeds` sem subir MainWindow."""

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


def test_brainstorm_tab_loads_24_seeds_as_mcp_prompt_buttons(tmp_path):
    """`_load_brainstorm_seeds` retorna 24 dicts ordenados por filename.

    Cobertura: contrato do loader que alimenta `_build_brainstorm_page`
    com `MCPPromptButton(label=slug, button_type=..., prompt=seed_path,
    ...)`. Cada seed precisa carregar campos canonicos do widget.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _materialize_24_seeds(repo_root)
    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()
    assert issues == []
    assert len(seeds) == CANONICAL_SEED_COUNT
    assert [s["slug"] for s in seeds] == CANONICAL_SLUGS
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
    retornar exatamente os 24 seeds canonicos. Regressao das duas sumiços de hoje.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)
    # Simula as duas saidas reais que quebraram a grade em 2026-05-24.
    (seeds_dir / "05-24-foot-stock-ciclo-assinatura-planos.md").write_text(
        "# output do brainstorm\n", encoding="utf-8"
    )
    (seeds_dir / "05-24-foot-stock-bugfix-tasks.md").write_text(
        "# output do brainstorm\n", encoding="utf-8"
    )
    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()
    # Os irmaos com prefixo de data viram UMA issue agregada e a grade
    # canonica continua completa (C3 Task 10: degradacao, nunca grade zerada).
    assert len(issues) == 1
    assert "05-24-foot-stock" in issues[0]["filename"]
    assert len(seeds) == CANONICAL_SEED_COUNT
    assert [s["slug"] for s in seeds] == CANONICAL_SLUGS


def test_seed_loader_still_reports_when_a_real_seed_is_missing(tmp_path):
    """O filtro nao pode mascarar a ausencia de um seed canonico real.

    Pos-C3 (Task 10) a ausencia deixou de zerar a grade: ela vira `issue`
    identificando o arquivo e os 23 restantes continuam de pe.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)
    (seeds_dir / "13-revisar-execucao.md").unlink()
    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()
    assert len(seeds) == CANONICAL_SEED_COUNT - 1
    assert [i["filename"] for i in issues] == ["13-revisar-execucao.md"]
    assert "ausente" in issues[0]["reason"]
    assert "revisar-execucao" not in [s["slug"] for s in seeds]


def test_seeds_dir_helper_points_to_canonical_reldir(tmp_path):
    """Contrato de path do helper `_brainstorm_seeds_dir`.

    Este teste NAO exerce o picker, apesar do nome que carregava antes: ele
    afirma apenas que o helper resolve `{repo}/BRAINSTORM_SEEDS_RELDIR`. Quem
    observa o diretorio realmente entregue a `QFileDialog.getOpenFileName` e
    `tests/test_brainstorm_md_picker.py`; manter o nome antigo aqui vendia
    uma cobertura de picker que nunca existiu.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _materialize_24_seeds(repo_root)
    fake = _FakeMainWindow(repo_root)
    seeds_dir = fake._brainstorm_seeds_dir()
    assert seeds_dir == (repo_root.resolve() / BRAINSTORM_SEEDS_RELDIR)
    assert seeds_dir.is_dir()


def test_picker_fallback_to_blacksmith_when_brainstorm_mcp_absent(tmp_path):
    """Cenario §7.5: brainstorm-mcp inexistente -> fallback para blacksmith/.

    O loader reporta a issue "diretorio inexistente" (sem excecao, pos-C3
    Task 10) e o caller no main_window cai para `blacksmith/`.
    """
    repo_root = tmp_path / "repo"
    (repo_root / "blacksmith").mkdir(parents=True)
    fake = _FakeMainWindow(repo_root)
    # Diretorio canonico ausente: zero seeds e UMA issue, sem excecao.
    seeds, issues = fake._load_brainstorm_seeds()
    assert seeds == []
    assert len(issues) == 1
    assert "diretorio inexistente" in issues[0]["reason"]
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


def test_same_prefix_impostor_does_not_pass_as_canonical_seed(tmp_path):
    """Renomear um seed canonico mantendo o prefixo NAO pode passar batido.

    Este e o buraco que a descoberta por prefixo deixava aberto: com o
    criterio antigo (regex `NN-<slug-alpha>.md` + contiguidade de prefixo),
    `14-visual-design.md` renomeado para `14-outra-coisa.md` mantinha o
    prefixo `14` presente, produzia 24 botoes e ZERO issues — um seed
    canonico desaparecia em silencio absoluto.

    Depois da Task 29 a cardinalidade voltou a ser aberta, mas a deteccao
    NAO voltou a depender de prefixo: quem acusa a ausencia e a tupla
    canonica, agora no papel de registro de identidade.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)
    (seeds_dir / "14-visual-design.md").rename(seeds_dir / "14-outra-coisa.md")

    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()

    # Task 29 abriu a cardinalidade: `14-outra-coisa.md` tem forma valida de
    # seed, entao CARREGA como seed nao-canonico (a grade nao encolhe). O que
    # nao pode acontecer -- e e o ponto deste teste -- e o desaparecimento de
    # `14-visual-design.md` passar em silencio.
    carregados = [s["seed_path"].name for s in seeds]
    assert "14-visual-design.md" not in carregados
    assert "14-outra-coisa.md" in carregados
    ausentes = [i for i in issues if "ausente" in i["reason"]]
    assert [i["filename"] for i in ausentes] == ["14-visual-design.md"], (
        "renomear seed canonico mantendo o prefixo tem de doer"
    )


def test_seed_novo_fora_da_tupla_vira_botao(tmp_path):
    """Task 29: acrescentar um seed nao exige editar Python em lugar nenhum.

    Antes, a tupla canonica era a lista de ALVOS e um `25-*.md` valido era
    descartado como intruso -- para ganhar um botao era preciso editar o
    contrato no repo aninhado E o classificador na raiz. Agora `seeds/` e a
    fonte, e a tupla so responde por identidade (deteccao de remocao).
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)
    (seeds_dir / "25-inventado.md").write_text(
        _SEED_BODY.format(slug="inventado"), encoding="utf-8"
    )
    (repo_root / "agents" / "inventado-rules.md").write_text("# x\n", encoding="utf-8")

    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()

    assert len(seeds) == CANONICAL_SEED_COUNT + 1
    assert "inventado" in [s["slug"] for s in seeds]
    assert issues == []
    # Ordem: os canonicos primeiro, na ordem do contrato; extras no fim.
    assert seeds[-1]["seed_path"].name == "25-inventado.md"


def test_action_nova_atravessa_loader_e_botao(tmp_path, qtbot):
    """Task 29: action nova salva pelo gear tem de CHEGAR na grade.

    Abrir so o combo do gear teria produzido o pior arranjo possivel: o
    operador digita `action: Acao Inventada`, o save diz OK, e o proximo
    rebuild da grade perde o botao porque o loader (e o `__init__` do widget)
    ainda exigiam pertinencia a `VALID_ACTIONS`. Caminho de escrita e caminho
    de leitura discordando em silencio -- a classe de defeito que esta C2
    existe para fechar. Este teste percorre os dois.

    ATENCAO ao ler este teste: a persona da fixture (`agents/<slug>-rules.md`)
    e DESCONHECIDA do contrato, e o gate G7 se abstem sobre persona que nunca
    mediu. Ou seja, este teste sozinho NAO prova a Task 29 -- ele percorre o
    unico ramo onde o gate ja era permissivo. Quem prova o caso real, com
    persona CONHECIDA (que e o caso dos 24 seeds de producao), e
    `test_action_nova_sobre_persona_CONHECIDA_atravessa`, logo abaixo. Os dois
    ficam: este cobre a persona nova, aquele cobre a persona existente.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)
    corpo = _SEED_BODY.format(slug="inventado").replace(
        'action: "Otimizar"', 'action: "Acao Inventada"'
    )
    (seeds_dir / "25-inventado.md").write_text(corpo, encoding="utf-8")
    (repo_root / "agents" / "inventado-rules.md").write_text("# x\n", encoding="utf-8")

    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()

    assert issues == []
    novo_seed = [s for s in seeds if s["slug"] == "inventado"]
    assert len(novo_seed) == 1
    assert novo_seed[0]["action"] == "Acao Inventada"

    # E o widget aceita a mesma action: sem isto, o loader entregaria um dict
    # que a grade nao consegue instanciar.
    btn = MCPPromptButton(
        label="inventado",
        button_type="Claude",
        prompt=novo_seed[0]["seed_path"],
        agent_name="agent-inventado",
        agent_path="agents/inventado-rules.md",
        action="Acao Inventada",
        target_path="terminal-interactive-output",
        testid_slug="action-nova",
    )
    qtbot.addWidget(btn)
    assert btn.payload()["action"] == "Acao Inventada"


def test_action_nova_sobre_persona_CONHECIDA_atravessa(tmp_path, qtbot):
    """Task 29 no caminho REAL: os 24 seeds tem persona conhecida do contrato.

    Este e o teste que faltava, e a ausencia dele escondeu que a Task 29 nao
    estava entregue. `PERSONA_CATEGORY_ACTIONS` da a cada categoria um
    frozenset de UMA action; `validate_persona_action` reprovava qualquer
    action fora dele. Como todo seed de producao aponta para uma persona
    canonica, o gate G7 anulava na pratica a abertura do vocabulario: o
    operador digitava a action nova, o gear salvava, e o rebuild seguinte
    reprovava o seed inteiro -- de novo escrita e leitura discordando.

    O contrato agora se abstem sobre action que nunca mediu, do mesmo jeito
    que ja se abstinha sobre persona que nunca mediu.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)

    persona = "ai-forge/MCP/agents/criar-md-rules.md"
    assert persona in KNOWN_PERSONA_PATHS, "fixture precisa de persona CONHECIDA"
    persona_abs = repo_root / persona
    persona_abs.parent.mkdir(parents=True, exist_ok=True)
    persona_abs.write_text("# persona canonica stub\n", encoding="utf-8")

    corpo = (
        _SEED_BODY.format(slug="inventado")
        .replace('action: "Otimizar"', 'action: "Acao Inventada"')
        .replace('agent_path: "agents/inventado-rules.md"', f'agent_path: "{persona}"')
    )
    (seeds_dir / "25-inventado.md").write_text(corpo, encoding="utf-8")

    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()

    assert issues == [], f"persona conhecida + action nova foi reprovada: {issues}"
    novo = [s for s in seeds if s["slug"] == "inventado"]
    assert len(novo) == 1
    assert novo[0]["action"] == "Acao Inventada"

    btn = MCPPromptButton(
        label="inventado",
        button_type="Claude",
        prompt=novo[0]["seed_path"],
        agent_name="agent-inventado",
        agent_path=persona,
        action="Acao Inventada",
        target_path="terminal-interactive-output",
        testid_slug="action-nova-persona-conhecida",
    )
    qtbot.addWidget(btn)
    assert btn.payload()["action"] == "Acao Inventada"


def test_g7_ainda_pega_action_CONHECIDA_na_persona_errada(tmp_path):
    """Contra-teste da abstencao: G7 nao pode ter virado carimbo.

    A abstencao acima e sobre action NUNCA MEDIDA. Uma action que o contrato
    conhece, posta numa persona que nao a sustenta, continua sendo o defeito
    que G7 existe para pegar -- seed que trocou de persona e esqueceu de
    trocar a action. Sem este teste, alguem poderia "consertar" o gate
    devolvendo `None` sempre e a suite ficaria verde.
    """
    razao = validate_persona_action(
        "ai-forge/MCP/agents/criar-md-rules.md", "Questionar"
    )
    assert razao is not None, "G7 deixou passar action conhecida em persona errada"
    assert "nao sustenta" in razao

    assert "Questionar" in KNOWN_ACTIONS
    assert (
        validate_persona_action(
            "ai-forge/MCP/agents/criar-md-rules.md", "Acao Que Ninguem Mediu"
        )
        is None
    )


def test_action_vazia_continua_recusada(tmp_path):
    """A abertura e de VOCABULARIO, nao de forma: action vazia nunca passa."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)
    alvo = seeds_dir / CANONICAL_SEED_FILENAMES[0]
    alvo.write_text(
        alvo.read_text(encoding="utf-8").replace(
            'action: "Otimizar"', 'action: "   "'
        ),
        encoding="utf-8",
    )

    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()

    assert len(seeds) == CANONICAL_SEED_COUNT - 1
    assert any("action vazia" in i["reason"] for i in issues)

    with pytest.raises(ValueError, match="action invalida"):
        MCPPromptButton(
            label="x", button_type="Claude", prompt="x",
            action="  ", target_path="terminal-interactive-output",
            testid_slug="action-vazia",
        )


def test_nome_sem_forma_de_seed_nunca_vira_botao(tmp_path):
    """A abertura e de CARDINALIDADE, nao de forma: nome torto continua fora."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)
    for torto in ("inventado.md", "9-curto.md", "25-Maiuscula.md"):
        (seeds_dir / torto).write_text(
            _SEED_BODY.format(slug="inventado"), encoding="utf-8"
        )

    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()

    assert len(seeds) == CANONICAL_SEED_COUNT
    intrusos = [i for i in issues if "forma de seed" in i["reason"]]
    assert len(intrusos) == 1
    for torto in ("inventado.md", "9-curto.md", "25-Maiuscula.md"):
        assert torto in intrusos[0]["filename"]


def test_sequencia_com_buraco_vira_issue(tmp_path):
    """`01..N` contiguo: buraco e sinal de remocao, nao de numeracao esparsa."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)
    (seeds_dir / "30-longe.md").write_text(
        _SEED_BODY.format(slug="longe"), encoding="utf-8"
    )
    (repo_root / "agents" / "longe-rules.md").write_text("# x\n", encoding="utf-8")

    fake = _FakeMainWindow(repo_root)
    _, issues = fake._load_brainstorm_seeds()

    buracos = [i for i in issues if "buraco" in i["reason"]]
    assert len(buracos) == 1
    for ausente in ("25", "26", "27", "28", "29"):
        assert ausente in buracos[0]["reason"]


def test_seed_without_frontmatter_delimiters_is_rejected(tmp_path):
    """Frontmatter e obrigatorio de verdade, nao decorativo.

    O parser antigo caia para `raw = text` quando os delimitadores `---`
    faltavam: o documento INTEIRO ia para o YAML e um arquivo sem frontmatter,
    mas com as chaves certas, era aceito como seed valido.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)
    corpo = _SEED_BODY.format(slug="criar-md")
    sem_delim = corpo.replace("---\n", "", 2)
    assert "schema_version" in sem_delim, "a fixture ainda precisa ter as chaves"
    (seeds_dir / "01-criar-md.md").write_text(sem_delim, encoding="utf-8")

    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()

    assert len(seeds) == CANONICAL_SEED_COUNT - 1
    assert "criar-md" not in [s["slug"] for s in seeds]
    alvo = [i for i in issues if i["filename"] == "01-criar-md.md"]
    assert len(alvo) == 1
    assert "frontmatter ausente" in alvo[0]["reason"]


def test_missing_seeds_dir_is_a_global_scope_issue(tmp_path):
    """Fonte inviavel e `scope: global`; falha de item e `scope: item`.

    O caller usa essa distincao para decidir entre reconstruir a grade
    degradada e preservar a grade anterior: uma leitura vazia por diretorio
    ausente nao pode ser confundida com "a grade agora e vazia".
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()
    assert seeds == []
    assert [i.get("scope") for i in issues] == ["global"]


def test_item_failures_are_never_global_scope(tmp_path):
    """Seed corrompido degrada o item; jamais marca a fonte como inviavel."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir = _materialize_24_seeds(repo_root)
    (seeds_dir / "07-questioner.md").write_text(
        "---\nslug: [\n---\n", encoding="utf-8"
    )
    fake = _FakeMainWindow(repo_root)
    seeds, issues = fake._load_brainstorm_seeds()
    assert len(seeds) == CANONICAL_SEED_COUNT - 1
    assert issues, "a falha precisa ser reportada"
    assert all(i.get("scope") == "item" for i in issues)
