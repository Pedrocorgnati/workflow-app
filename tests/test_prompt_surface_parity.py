"""Task 31 (D15) -- escritor unico, leitor derivado, sobre o corpo do prompt.

Duas telas mostram o corpo do prompt de um seed: a engrenagem da aba
Brainstorm (`BrainstormMcpConfigDialog`) e o modal de right-click do botao
(`MCPPromptConfigModal`). Ate a Task 31 as DUAS escreviam, e a segunda
escrevia pior: aceitar o modal fazia `botao._prompt = values["prompt"]`, e
quando o botao nasce de um seed `_prompt` e o `Path` do arquivo. A aceitacao
trocava o `Path` por uma string congelada, o seed no disco seguia com o texto
verdadeiro, e nada na tela dizia que os dois tinham divergido.

O arranjo travado aqui: a engrenagem grava; o modal so LE, da mesma fonte.

Os testes cobrem os quatro aceites da task:
1. Paridade  -- as duas superficies exibem texto identico para o mesmo seed.
2. Direcao   -- editar pela engrenagem propaga; nao existe caminho de volta.
3. Ausencia de escrita -- provada por AST sobre o modulo do modal, nao por
   leitura visual nem por grep (o comentario que explica a decisao cita os
   simbolos removidos de proposito, e um grep cru o acusaria).
4. UI honesta -- a previa e read-only DE FATO e diz de onde vem o texto.
"""

from __future__ import annotations

import ast
from pathlib import Path
from textwrap import dedent

import pytest

from workflow_app.brainstorm_seed_contract import extract_action_literal
from workflow_app.widgets import mcp_prompt_button as mpb
from workflow_app.widgets.brainstorm_mcp_config_dialog import (
    BrainstormMcpConfigDialog,
)
from workflow_app.widgets.mcp_prompt_button import (
    MCPPromptButton,
    MCPPromptConfigModal,
)

pytestmark = pytest.mark.timeout(15)


_CORPO_ORIGINAL = "Corpo canonico original, reconhecivel byte a byte."

_SEED = dedent(
    """\
    ---
    schema_version: 1
    slug: "paridade"
    label: "paridade"
    title: "Seed - paridade"
    button_type: "Claude"
    agent_name: "agente-paridade"
    agent_path: "agents/paridade-rules.md"
    action: "Otimizar"
    target_path: "false"
    target_terminal: "terminal-interactive-output"
    ---

    # body

    ## Prompt canonico

    {corpo}
    """
)


@pytest.fixture
def seed_repo(tmp_path):
    """Repo minimo com UM seed, servindo as duas superficies."""
    repo_root = tmp_path / "repo"
    seeds_dir = repo_root / "blacksmith" / "brainstorm-mcp" / "seeds"
    seeds_dir.mkdir(parents=True)
    (repo_root / "agents").mkdir()
    (repo_root / "agents" / "paridade-rules.md").write_text(
        "# persona stub\n", encoding="utf-8"
    )
    seed = seeds_dir / "01-paridade.md"
    seed.write_text(_SEED.format(corpo=_CORPO_ORIGINAL), encoding="utf-8")
    return repo_root, seeds_dir, seed


def _abre_gear(qtbot, repo_root, seeds_dir):
    dlg = BrainstormMcpConfigDialog(None, repo_root, seeds_dir=seeds_dir)
    qtbot.addWidget(dlg)
    return dlg


def _abre_modal(qtbot, seed: Path, monkeypatch):
    """Abre o modal pelo caminho REAL (contextMenuEvent), sem exec bloqueante."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QApplication, QDialog

    btn = MCPPromptButton(
        label="paridade",
        button_type="Claude",
        prompt=seed,
        agent_name="agente-paridade",
        agent_path="agents/paridade-rules.md",
        action="Otimizar",
        target_path="terminal-interactive-output",
        testid_slug="paridade",
    )
    qtbot.addWidget(btn)

    abertos: list[MCPPromptConfigModal] = []

    def _fake_exec(self) -> int:
        abertos.append(self)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(MCPPromptConfigModal, "exec", _fake_exec)
    pos = QPoint(max(btn.width() // 2, 1), max(btn.height() // 2, 1))
    QApplication.sendEvent(
        btn,
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, btn.mapToGlobal(pos)),
    )
    assert len(abertos) == 1
    return btn, abertos[0]


# ── 1. Paridade ───────────────────────────────────────────────────────────


def test_as_duas_superficies_mostram_o_mesmo_corpo(qtbot, seed_repo, monkeypatch):
    """Engrenagem e modal, mesmo seed, mesmo texto."""
    repo_root, seeds_dir, seed = seed_repo

    dlg = _abre_gear(qtbot, repo_root, seeds_dir)
    do_gear = dlg._prompt_edit.toPlainText()

    _btn, modal = _abre_modal(qtbot, seed, monkeypatch)
    do_modal = modal.prompt_preview()

    assert do_gear.strip() == _CORPO_ORIGINAL
    # O modal exibe o ARQUIVO inteiro (e o que o botao despacha); o corpo
    # canonico dentro dele tem de ser o mesmo que a engrenagem edita.
    assert extract_action_literal(do_modal).strip() == do_gear.strip()


# ── 2. Direcao ────────────────────────────────────────────────────────────


def test_editar_pela_engrenagem_aparece_no_modal(qtbot, seed_repo, monkeypatch):
    """A propagacao existe e tem UM sentido: gear -> disco -> modal.

    A edicao passa pelo caminho de PRODUCAO do gear (digitar na caixa e
    clicar em salvar), nao por uma chamada direta a `save_seed` -- senao o
    teste provaria que o modulo de persistencia funciona, e nao que a
    engrenagem e mesmo a escritora.
    """
    repo_root, seeds_dir, seed = seed_repo
    novo = "Corpo REESCRITO pela engrenagem em 2026-08-26."

    dlg = _abre_gear(qtbot, repo_root, seeds_dir)
    dlg._prompt_edit.setPlainText(novo)
    dlg._on_save_clicked()
    assert dlg._error_label.text() == ""
    assert extract_action_literal(seed.read_text(encoding="utf-8")).strip() == novo

    _btn, modal = _abre_modal(qtbot, seed, monkeypatch)
    assert extract_action_literal(modal.prompt_preview()).strip() == novo


def test_aceitar_o_modal_nao_reverte_nem_congela_o_seed(
    qtbot, seed_repo, monkeypatch,
):
    """Aceitar o modal (Accepted) nao pode tocar no corpo nem no vinculo.

    Este e o caso concreto que a task descreve: `_prompt` continua sendo o
    `Path` do seed depois do aceite. Se voltasse a virar string, o botao
    pararia de acompanhar o arquivo e nenhuma edicao posterior da engrenagem
    chegaria nele.
    """
    _repo_root, _seeds_dir, seed = seed_repo
    antes = seed.read_bytes()

    btn, modal = _abre_modal(qtbot, seed, monkeypatch)
    # A previa esta travada: mesmo forcando texto no widget, nada persiste.
    modal._prompt_edit.setPlainText("TENTATIVA DE SOBRESCRITA")

    assert seed.read_bytes() == antes
    assert isinstance(btn._prompt, Path)
    assert btn._prompt == seed
    assert "prompt" not in modal.values()


# ── 3. Ausencia de caminho de escrita (AST) ───────────────────────────────


def _modulo_do_modal() -> ast.Module:
    return ast.parse(Path(mpb.__file__).read_text(encoding="utf-8"))


def _classe(arvore: ast.Module, nome: str) -> ast.ClassDef:
    (cls,) = [
        n for n in arvore.body if isinstance(n, ast.ClassDef) and n.name == nome
    ]
    return cls


def test_values_do_modal_nao_carrega_o_prompt():
    """A chave `prompt` ERA o caminho de escrita; some do dicionario."""
    modal = _classe(_modulo_do_modal(), "MCPPromptConfigModal")
    (values,) = [
        n for n in modal.body
        if isinstance(n, ast.FunctionDef) and n.name == "values"
    ]
    chaves = {
        k.value
        for d in ast.walk(values)
        if isinstance(d, ast.Dict)
        for k in d.keys
        if isinstance(k, ast.Constant)
    }
    assert "prompt" not in chaves
    assert {"label", "agent_name", "agent_path", "target_path"} <= chaves


def test_nenhum_caminho_do_modal_reatribui_o_prompt_do_botao():
    """Nada no modulo escreve `self._prompt` fora do `__init__` do botao."""
    arvore = _modulo_do_modal()
    botao = _classe(arvore, "MCPPromptButton")
    for metodo in botao.body:
        if not isinstance(metodo, ast.FunctionDef) or metodo.name == "__init__":
            continue
        for no in ast.walk(metodo):
            alvos = (
                no.targets if isinstance(no, ast.Assign)
                else [no.target] if isinstance(no, (ast.AugAssign, ast.AnnAssign))
                else []
            )
            for alvo in alvos:
                assert not (
                    isinstance(alvo, ast.Attribute)
                    and alvo.attr == "_prompt"
                    and isinstance(alvo.value, ast.Name)
                    and alvo.value.id == "self"
                ), f"{metodo.name} reatribui self._prompt"


def test_o_modal_nao_chama_nenhuma_rotina_de_persistencia():
    """Nem escrita direta, nem `save_seed`/`render_seed` importados de fora."""
    modal = _classe(_modulo_do_modal(), "MCPPromptConfigModal")
    proibidos = {
        "write_text", "open", "save_seed", "save_seeds_transactional",
        "render_seed", "replace_action_literal", "_atomic_write",
    }
    for no in ast.walk(modal):
        if isinstance(no, ast.Call):
            nome = (
                no.func.attr if isinstance(no.func, ast.Attribute)
                else no.func.id if isinstance(no.func, ast.Name)
                else ""
            )
            assert nome not in proibidos, f"modal chama {nome}"


# ── 4. UI honesta ─────────────────────────────────────────────────────────


def test_a_previa_e_read_only_de_fato_e_diz_de_onde_vem(qtbot, seed_repo, monkeypatch):
    """Travado no widget (`isReadOnly`) e explicado na tela, nao so no codigo."""
    _repo_root, _seeds_dir, seed = seed_repo
    _btn, modal = _abre_modal(qtbot, seed, monkeypatch)

    assert modal._prompt_edit.isReadOnly() is True
    assert modal._prompt_edit.property("testid") == "mcp-prompt-config-preview"

    dica = modal._prompt_hint.text()
    assert "Somente leitura" in dica
    assert "engrenagem" in dica
    assert "## Prompt canonico" in dica
    assert modal._prompt_edit.toolTip() == dica


# ── 5. Task 32: o texto editado chega ao MODELO, nao so a outra tela ───────


def test_editar_pela_engrenagem_muda_o_prompt_despachado(qtbot, seed_repo):
    """A cadeia inteira: engrenagem -> disco -> loader -> payload -> prompt.

    Os outros testes deste arquivo param na SEGUNDA TELA. Se o loader
    congelasse o literal, ou o payload deixasse de transportar a chave, ou
    `build_prompt` voltasse a preferir `ACTION_LITERALS`, todos eles
    continuariam verdes e o operador continuaria editando um texto que o
    modelo nunca recebe -- que e exatamente o defeito que C2 fechou.
    """
    from workflow_app.main_window import MainWindow
    from workflow_app.widgets.mcp_prompt_actions import (
        ACTION_LITERALS,
        build_prompt,
    )

    repo_root, seeds_dir, seed = seed_repo
    novo = "Corpo despachado ao modelo, escrito pela engrenagem."

    dlg = _abre_gear(qtbot, repo_root, seeds_dir)
    dlg._prompt_edit.setPlainText(novo)
    dlg._on_save_clicked()
    assert dlg._error_label.text() == ""

    # Releitura pelo loader de PRODUCAO, sem subir a MainWindow inteira.
    class _Stub:
        def _systemforge_root(self):
            return repo_root

    dados = MainWindow._load_one_brainstorm_seed(_Stub(), seed, repo_root)

    btn = MCPPromptButton(
        label=dados["label"],
        button_type=dados["button_type"],
        prompt=dados["seed_path"],
        agent_name=dados["agent_name"],
        agent_path=dados["agent_path"],
        action=dados["action"],
        target_path=dados["target_terminal"],
        testid_slug=dados["slug"],
        action_literal=dados["action_literal"],
    )
    qtbot.addWidget(btn)

    # `seed_meta` montado como o handler de producao monta (main_window
    # `_on_brainstorm_btn_clicked`): `target_path` e o BOOL de edicao
    # in-place, nao o testid de terminal que o payload carrega com o mesmo
    # nome. `action_literal` entra por PRESENCA da chave.
    payload = btn.payload()
    seed_meta = {
        "agent_name": payload["agent_name"],
        "agent_path": payload["agent_path"],
        "action": payload["action"],
        "target_path": payload["target_path_edit_inplace"],
    }
    assert "action_literal" in payload, "o payload perdeu o transporte do corpo"
    seed_meta["action_literal"] = payload["action_literal"]

    prompt = build_prompt(seed_meta, None, repo_root)
    assert novo in prompt
    assert ACTION_LITERALS["Otimizar"] not in prompt


# ── 5. A previa mostra o que sera DESPACHADO ────────────────────────────────
#
# As fixtures acima constroem o botao SEM `action_literal`, que e o caminho de
# caller programatico. Producao nao passa por ali: o loader extrai o bloco e o
# builder o entrega ao botao. Os testes abaixo usam o shape de producao.


def _botao_de_producao(qtbot, seed: Path, literal: str) -> MCPPromptButton:
    btn = MCPPromptButton(
        label="paridade",
        button_type="Claude",
        prompt=seed,
        agent_name="agente-paridade",
        agent_path="agents/paridade-rules.md",
        action="Otimizar",
        target_path="terminal-interactive-output",
        testid_slug="paridade",
        action_literal=literal,
    )
    qtbot.addWidget(btn)
    return btn


def test_previa_mostra_o_literal_e_nao_o_arquivo_inteiro(qtbot, seed_repo):
    """`_PROMPT_PREVIEW_HINT` afirma mostrar o bloco; agora e verdade.

    A previa lia o `.md` inteiro. Como o corte do tooltip sao 80 chars e o
    arquivo comeca pelo frontmatter, o que o operador via era YAML --
    `---`, `schema_version`, `slug` -- e nunca uma linha do prompt.
    """
    _repo, _seeds_dir, seed = seed_repo
    btn = _botao_de_producao(qtbot, seed, _CORPO_ORIGINAL)

    assert btn._resolve_prompt_text() == _CORPO_ORIGINAL

    tooltip = btn.toolTip()
    assert _CORPO_ORIGINAL[:40] in tooltip
    for marca in ("schema_version", "target_terminal", "## Prompt canonico"):
        assert marca not in tooltip, f"tooltip ainda expoe {marca!r}"


def test_previa_e_despacho_nao_divergem_quando_o_disco_muda_por_fora(
    qtbot, seed_repo
):
    """O botao carrega um snapshot; a previa tem de mostrar ESSE snapshot.

    Nao ha watcher dos seeds -- so o save da engrenagem reconstroi a grade.
    Enquanto a previa relia o arquivo e o payload emitia o snapshot, uma
    edicao feita por fora (editor de texto, git checkout, outro loop) fazia a
    tela mostrar B e o modelo receber A, sem sinal nenhum de que os dois
    tinham divergido.

    O contrato nao e "a previa esta sempre fresca": e "a previa e o despacho
    nunca discordam".
    """
    _repo, _seeds_dir, seed = seed_repo
    btn = _botao_de_producao(qtbot, seed, _CORPO_ORIGINAL)

    seed.write_text(
        _SEED.format(corpo="TEXTO NOVO ESCRITO POR FORA DA ENGRENAGEM"),
        encoding="utf-8",
    )

    assert btn._resolve_prompt_text() == btn.payload()["action_literal"]
    assert "POR FORA" not in btn._resolve_prompt_text()


def test_sem_literal_a_previa_continua_lendo_o_arquivo(qtbot, seed_repo):
    """O caminho sem seed nao regride: ali o arquivo e a unica fonte."""
    _repo, _seeds_dir, seed = seed_repo
    btn = MCPPromptButton(
        label="paridade",
        button_type="Claude",
        prompt=seed,
        agent_name="agente-paridade",
        agent_path="agents/paridade-rules.md",
        action="Otimizar",
        target_path="terminal-interactive-output",
        testid_slug="paridade",
    )
    qtbot.addWidget(btn)

    texto = btn._resolve_prompt_text()
    assert texto == seed.read_text(encoding="utf-8")
    assert "action_literal" not in btn.payload()
