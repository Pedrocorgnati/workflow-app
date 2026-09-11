"""Testes do modal de configuracao gear (T4).

Cobre 3 cenarios do T4 (loop 05-21-implantation-tasklist-aba-brainstorm):
- test_gear_dialog_opens_with_seeds_loaded: dialog carrega 24 seeds com testid.
- test_gear_modal_persists_seed_edits_to_disk: save grava no .md (atomic write).
- test_gear_modal_revert_discards_edits: reject() preserva conteudo do .md.

Usa `tmp_path` para criar workspace temporario com 24 seeds canonicos.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(5)

pytest.importorskip("workflow_app.widgets.brainstorm_mcp_config_dialog")

from tests._helpers import real_seed_frontmatter
from workflow_app.brainstorm_seed_contract import (
    BRAINSTORM_SEEDS_RELDIR,
    CANONICAL_SEED_FILENAMES,
    resolve_seed_dir,
)
from workflow_app.main_window import MainWindow
from workflow_app.widgets.brainstorm_mcp_config_dialog import (
    BrainstormMcpConfigDialog,
    effective_label,
    load_seed,
    save_seed,
)
from workflow_app.widgets.mcp_prompt_button import VALID_BUTTON_TYPES

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


def _canonical_seed_specs() -> list[tuple[str, str, str, str, bool, str]]:
    """`(filename_sem_md, slug, button_type, action, target_path, terminal)`
    lido do frontmatter REAL dos 24 seeds em disco.

    Era uma lista hardcoded, e ela tinha derivado: dizia `Otimizar` para
    `19-delegador` e `22-scaffolds-blueprints-updater` e `Revisar` para
    `07-questioner` (os reais sao `Delegar`, `Atualizar scaffolds e blueprints`
    e `Questionar`), `button_type: Claude` nos 24 (21 sao
    `type-selector-radio-input`) e `terminal-interactive-output` nos 24 (20 sao
    o sentinel `depende-do-radio`). Uma fixture que afirma materializar "os 24
    seeds canonicos" e materializa outra coisa aprova o dialogo sobre um
    universo que nao existe -- e foi sobre `target_terminal` que o bug do
    sentinel nasceu.

    So `agent_path` continua sintetico: ele tem de existir DENTRO da `tmp_path`
    para satisfazer G6, e o path real aponta para fora dela.
    """
    return [
        (
            nome[: -len(".md")],
            str(fm["slug"]),
            str(fm["button_type"]),
            str(fm["action"]),
            bool(fm.get("target_path") or False),
            str(fm["target_terminal"]),
        )
        for nome, fm in real_seed_frontmatter().items()
    ]


def _materialize_seeds(repo_root: Path) -> tuple[Path, Path]:
    """Cria 24 seeds canonicos + diretorio de agentes. Retorna (seeds_dir, agents_dir)."""
    seeds_dir = repo_root / BRAINSTORM_SEEDS_RELDIR
    agents_dir = repo_root / "agents"
    seeds_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)
    specs = _canonical_seed_specs()
    # Guard de identidade: a fixture materializa os nomes REAIS do contrato
    # fechado, nunca nomes inventados. Sem isto a fixture volta a criar
    # intrusos que o loader por membership descarta em silencio.
    assert tuple(sorted(f"{s[0]}.md" for s in specs)) == CANONICAL_SEED_FILENAMES, (
        "specs divergiu de CANONICAL_SEED_FILENAMES"
    )
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
    sentinel_files = {"09-loop-prepare.md": "loop-prepare", "02-pesquisar.md": "pesquisar"}
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


def test_gear_nao_arrasta_button_type_da_linha_anterior(qtbot, tmp_path):
    """`button_type` invalido no disco nao pode virar o type da linha ANTERIOR.

    Terceira encarnacao do mesmo defeito de `_render_form_from`: condicionar o
    `setCurrentText` a pertinencia (`if valor in VALID_*`) deixa o widget
    exibindo o valor da linha anterior quando o da linha atual nao pertence, e
    `_capture_form_into` grava esse residuo por cima da seed atual. Ja custou
    `action` e `target_terminal` (os dois comentados no proprio metodo).

    Em `button_type` era PIOR que nos outros dois: o combo e fechado e so tem
    valores validos, entao o residuo arrastado tambem e valido -- passava na
    validacao e ia para o disco em silencio, trocando o type de uma seed pelo
    da seed que o operador tinha aberto antes.

    Contrato agora: valor de disco fora de `VALID_BUTTON_TYPES` esvazia a
    selecao (indice -1), o erro cita o valor DE DISCO (nao `''`), o save fica
    barrado, e trocar de linha nao apaga nem substitui o valor invalido - ele
    continua em memoria e em disco para o operador ver e corrigir.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir, _ = _materialize_seeds(repo_root)

    alvo = seeds_dir / "02-pesquisar.md"
    texto = alvo.read_text(encoding="utf-8")
    corrompido = re.sub(
        r"(?m)^button_type: .*$", "button_type: Sonnet", texto, count=1,
    )
    assert corrompido != texto, "fixture nao tem linha `button_type:` para corromper"
    assert "Sonnet" not in VALID_BUTTON_TYPES, "escolha outro valor invalido"
    alvo.write_text(corrompido, encoding="utf-8")

    dlg = BrainstormMcpConfigDialog(
        parent=None, repo_root=repo_root, seeds_dir=seeds_dir,
    )
    qtbot.addWidget(dlg)

    i_ok = _index_of(dlg, "01-criar-md.md")
    i_ruim = _index_of(dlg, "02-pesquisar.md")

    dlg._list_widget.setCurrentRow(i_ok)
    anterior = dlg._type_combo.currentText()
    assert anterior in VALID_BUTTON_TYPES, anterior

    dlg._list_widget.setCurrentRow(i_ruim)
    assert dlg._type_combo.currentIndex() == -1, (
        "combo manteve selecao com `button_type` invalido no disco; "
        f"exibindo {dlg._type_combo.currentText()!r}"
    )
    assert dlg._type_combo.currentText() != anterior, (
        "combo esta exibindo o `button_type` da linha ANTERIOR"
    )
    assert dlg._validate() is False
    assert "Sonnet" in dlg._error_label.text(), (
        f"erro nao cita o valor de disco: {dlg._error_label.text()!r}"
    )
    assert dlg._save_btn.isEnabled() is False

    # Sair da linha dispara `_capture_form_into` sobre ela: o valor invalido
    # tem de sobreviver, em memoria e em disco.
    dlg._list_widget.setCurrentRow(i_ok)
    assert dlg._seed_meta[i_ruim]["button_type"] == "Sonnet", (
        "trocar de linha sobrescreveu o `button_type` invalido com "
        f"{dlg._seed_meta[i_ruim]['button_type']!r}"
    )
    assert load_seed(alvo)[0]["button_type"] == "Sonnet"


@pytest.mark.parametrize(
    ("linha_yaml", "esperado"),
    [
        ("button_type:", None),
        ('button_type: ""', ""),
        ("button_type: false", False),
        ("button_type: 0", 0),
    ],
    ids=["ausente", "vazio", "false", "zero"],
)
def test_gear_nao_repara_button_type_falsy_para_claude(
    qtbot, tmp_path, linha_yaml, esperado,
):
    """Valor FALSY no disco nao pode virar "Claude" em silencio.

    Irmao do teste acima, e o furo que ele deixava: `Sonnet` e truthy, entao
    chegava ao teste de pertinencia e caia no caminho do indice -1. Os valores
    falsy nunca chegavam la -- `str(meta.get("button_type") or "Claude")`
    trocava cada um deles por "Claude" ANTES da checagem, e "Claude" pertence
    ao conjunto. O combo exibia um type que nao existe em disco, sair da linha
    gravava esse type na memoria por cima do defeito, e `_validate_record` --
    que le o meta cru e reprovaria `None`/`""`/`False`/`0` -- passava a
    aprovar. Um defeito de disco virava um palpite plausivel, salvavel.

    Os quatro casos sao grafias reais de YAML: chave sem valor, string vazia,
    booleano e inteiro.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seeds_dir, _ = _materialize_seeds(repo_root)

    alvo = seeds_dir / "02-pesquisar.md"
    texto = alvo.read_text(encoding="utf-8")
    corrompido = re.sub(r"(?m)^button_type: .*$", linha_yaml, texto, count=1)
    assert corrompido != texto, "fixture nao tem linha `button_type:` para corromper"
    alvo.write_text(corrompido, encoding="utf-8")
    assert load_seed(alvo)[0].get("button_type") == esperado, (
        "o parser nao produziu o valor falsy esperado; o teste estaria "
        "medindo outra coisa"
    )

    dlg = BrainstormMcpConfigDialog(
        parent=None, repo_root=repo_root, seeds_dir=seeds_dir,
    )
    qtbot.addWidget(dlg)

    i_ok = _index_of(dlg, "01-criar-md.md")
    i_ruim = _index_of(dlg, "02-pesquisar.md")

    dlg._list_widget.setCurrentRow(i_ok)
    dlg._list_widget.setCurrentRow(i_ruim)

    assert dlg._type_combo.currentIndex() == -1, (
        "combo exibindo um type valido para um `button_type` falsy em disco: "
        f"{dlg._type_combo.currentText()!r}"
    )
    assert dlg._validate() is False
    assert dlg._save_btn.isEnabled() is False

    # Sair da linha nao pode substituir o defeito por um palpite.
    dlg._list_widget.setCurrentRow(i_ok)
    assert dlg._seed_meta[i_ruim].get("button_type") == esperado, (
        "trocar de linha reparou o `button_type` invalido para "
        f"{dlg._seed_meta[i_ruim].get('button_type')!r}"
    )
    assert load_seed(alvo)[0].get("button_type") == esperado


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
        def __init__(self, root: Path) -> None:
            self._root = root

        def _systemforge_root(self) -> Path:
            return self._root

        def _brainstorm_seeds_dir(self) -> Path:
            return MainWindow._brainstorm_seeds_dir(self)  # type: ignore[arg-type]

        def _load_one_brainstorm_seed(self, path, root):
            return MainWindow._load_one_brainstorm_seed(  # type: ignore[arg-type]
                self, path, root
            )

        def _load_brainstorm_seeds(self):
            return MainWindow._load_brainstorm_seeds(self)  # type: ignore[arg-type]

    seeds, _issues = _Fake(repo_root)._load_brainstorm_seeds()
    ac = next(s for s in seeds if s["slug"] == "analise-complexidade")
    assert ac["label"] == "Complexidade"


def test_gear_default_seeds_dir_comes_from_the_contract(qtbot, tmp_path):
    """O default do dialog tem de ser o mesmo path que a grade resolve.

    Regressao de A1: o dialog carregava o literal `blacksmith/brainstorm-mcp`,
    que era o diretorio pai dos seeds depois da migracao da Task 08.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _materialize_seeds(repo_root)

    dlg = BrainstormMcpConfigDialog(parent=None, repo_root=repo_root)
    qtbot.addWidget(dlg)
    assert dlg.seeds_dir == resolve_seed_dir(repo_root)
    assert dlg.seeds_dir.name == "seeds"


def test_gear_opens_usable_through_the_production_wiring(qtbot, tmp_path):
    """`main_window` abre o gear sem `seeds_dir`. Este teste exerce esse caminho.

    Todo outro teste deste arquivo injeta `seeds_dir` -- correto para isolar
    comportamento, mas cega o gate exatamente onde o defeito morava. Aqui o
    dialog e construido como em producao: `repo_root` e nada mais. Se o default
    voltar a apontar para fora de `seeds/`, isto fica vermelho com o mesmo
    sintoma que o operador via na tela (lista vazia, save morto).
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _materialize_seeds(repo_root)

    dlg = BrainstormMcpConfigDialog(parent=None, repo_root=repo_root)
    qtbot.addWidget(dlg)
    assert dlg._error_label.text() == "", dlg._error_label.text()
    assert len(dlg._seed_paths) == len(CANONICAL_SEED_FILENAMES)
    assert dlg._list_widget.count() == len(CANONICAL_SEED_FILENAMES)
    assert dlg._save_btn.isEnabled()
