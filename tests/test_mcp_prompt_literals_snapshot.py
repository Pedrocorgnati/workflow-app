"""Snapshot dos literais de action dos botoes `mcp-prompt-btn` (Task 16, C1).

Nao existia suite golden a preservar: ate 2026-08-25 o texto dos literais podia
mudar sem nenhum teste ficar vermelho, e foi assim que o literal `Criar arquivo`
seguiu apontando `STARTER.md` depois que a lane brainstorm ja tinha outro
contrato. Este arquivo fecha esse buraco.

CONTRATO DESTE TESTE. Ele fica vermelho a QUALQUER mudanca de texto de literal,
por desenho. Isso nao e fragilidade: os literais sao o prompt que vai para um
LLM com acesso de escrita ao repo, entao mudanca de uma palavra e mudanca de
comportamento e merece revisao explicita. O procedimento para uma mudanca
legitima e:

1. mudar o literal em `mcp_prompt_actions.py`;
2. bumpar `PROMPT_TEMPLATE_VERSION` (um bump por PR, nunca um por literal);
3. atualizar o hash aqui, na mesma mudanca.

Pular o passo 3 e o unico jeito de este teste falhar sem que haja bug. Pular o
passo 2 e o bug que ele existe para pegar.

A cardinalidade do conjunto e `len(EXPECTED_LITERALS)`, nunca um numero escrito
em prosa: C6 entrou com tres actions novas e provou que o numero escrito na
docstring envelhece sozinho.
"""

from __future__ import annotations

import hashlib

from tests._helpers import (
    assert_deriva_a_tabela_sem_copiar,
    assert_deriva_o_contrato_de_forma_sem_copiar,
)
from workflow_app.widgets.mcp_prompt_actions import (
    _BRAINSTORM_TEMPLATE_PATH,
    _BRAINSTORM_VALIDATOR_PATH,
    _FILE_OPS_RULES_PATH,
    _PRECEDENCE_CLAUSE,
    ACTION_LITERALS,
    PROMPT_TEMPLATE_VERSION,
)

#: Versao do conjunto. Muda junto com qualquer hash abaixo.
#: v14 = Codex R3 s3 (segunda lane): o literal `Criar arquivo` repetia a
#: Regra 3 de `BRAINSTORM.md` dentro do parenteses e prescrevia o conteudo de
#: `related-paths`/`agent-paths`, que e a tabela da Regra 1. Os dois agora
#: citam a regra pelo numero e param ai. A palavra `draft` sai do literal por
#: consequencia -- e o teste que EXIGIA `draft` aqui era o que teria ficado
#: vermelho na correcao certa.
#: v13 = Codex R3 s3: o literal `Loop prepare` repetia enum de modos, mapa
#: de botoes e veredito de `_LOOP-CONFIG.json` por modo. Os tres sao a
#: tabela `Handoff condicional por modo` de `loop-preparer-rules.md`, e
#: `BRAINSTORM.md:21` manda citar, nao redefinir. Foi essa copia que
#: envelheceu afirmando `queue-btn-loop` nos cinco modos. O literal agora
#: cita a tabela e manda aplica-la ao modo escolhido.
#: v12 = Codex F9 #1: o literal `Loop prepare` dizia que o produtor do
#: `_LOOP-CONFIG.json` era "exclusivamente a pipeline /loop" nos CINCO modos.
#: `--cmd-single` nao gera JSON em fase nenhuma e `--rocksmash` consome o de um
#: loop ja materializado, entao o texto prometia, em dois dos cinco, um handoff
#: que nunca acontece.
#: v11 = C2c (Task 26): o bloco `## Prompt canonico` do seed venceu
#: `ACTION_LITERALS` na montagem do prompt. Os literais em si NAO mudaram
#: -- por isso os sha256 abaixo seguem iguais; o que mudou foi quem tem
#: precedencia sobre eles.
EXPECTED_TEMPLATE_VERSION = "2026-08-26-v14"

#: `nome -> (sha256 do literal, comprimento em caracteres)`.
EXPECTED_LITERALS: dict[str, tuple[str, int]] = {
    "Otimizar": (
        "7d62723a1127763501dc0864dd94d011f68c7a336432d4de27b5cc2cb8b78b08", 149
    ),
    "Criar tasks": (
        "61bd250bc492a06f522c5d3ef8a7a202940e7eaa339000679691c6848acb41a0", 686
    ),
    "Revisar tasks": (
        "bff85dc34d19d56c15051064157f0074ab2e6782100cb896cbe5c506d8eb24a3", 518
    ),
    "Revisar": (
        "d75bbcb11d35063973766a9777575980cdd1e4243c51ca80d573cf3ebe9609e1", 280
    ),
    "Executar": (
        "b8d5e5aac091e52042de2b971de3ac25d18cad56d76882cd70476ff16f3be645", 506
    ),
    "Revisar execucao": (
        "8d39f46d194adb49645b87b306b540c0ebf85137e9c7a80146286283e6d09d23", 614
    ),
    "Criar arquivo": (
        "21a9c40b76d1bb98857920d6ab78470091742b6c988e8d55e3c8a80bfe6ebe60", 989
    ),
    "Loop prepare": (
        "cad73b7795dcf104683d78b47681aeec3f2f575378a5a915110822da819fc63e",
        1263,
    ),
    "Questionar": (
        "12eb0aa4d0637ff8687c2a3021f9fa430f881848f0c34c15e0c9fd679c2a7f48", 636
    ),
    "Delegar": (
        "54fa3b66a864593cbfc998c73c2886d2a108e0cc581deea68b0966456dfdca36", 891
    ),
    "Atualizar scaffolds e blueprints": (
        "80b0ce1f04095d0e20f4297871a97dd53fb2f23566bd4080f9994a7d2d280532", 716
    ),
    "Analisar complexidade": (
        "99c10bf7c87f16a2cafd3814a3c6affd96fe3324179c635e3af01bf9f58cf756", 1621
    ),
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_literal_set_is_exactly_the_expected_set():
    """Literal novo ou removido exige decisao explicita, nao passa de carona."""
    assert set(ACTION_LITERALS) == set(EXPECTED_LITERALS)
    assert len(ACTION_LITERALS) == len(EXPECTED_LITERALS)


def test_literal_order_is_stable():
    """A ordem e a ordem dos botoes na grade; embaralhar muda a UI."""
    assert list(ACTION_LITERALS) == list(EXPECTED_LITERALS)


def test_template_version_matches_snapshot():
    assert PROMPT_TEMPLATE_VERSION == EXPECTED_TEMPLATE_VERSION


def test_every_literal_matches_its_snapshot():
    divergent = {
        name: (_sha(text), len(text))
        for name, text in ACTION_LITERALS.items()
        if (_sha(text), len(text)) != EXPECTED_LITERALS[name]
    }
    assert not divergent, (
        "literal mudou sem atualizar o snapshot. Se a mudanca e intencional, "
        f"bumpe PROMPT_TEMPLATE_VERSION e grave os valores novos: {divergent}"
    )


def test_no_literal_is_empty_or_padded():
    for name, text in ACTION_LITERALS.items():
        assert text.strip() == text, f"{name}: literal com espaco nas bordas"
        assert text, f"{name}: literal vazio"


# --------------------------------------------------------------------------
# Invariantes de conteudo que sobrevivem a um rewrite de texto
# --------------------------------------------------------------------------


def test_file_ops_rules_cited_by_every_literal():
    """Toda action mexe em arquivo, entao toda action abre citando file-ops.

    Ate C6 havia uma excecao (`Analisar complexidade` nao escrevia nada) e a
    lista de excecoes vivia hardcoded aqui. A Task 22 deu escrita aquela action
    e a excecao acabou: a lista some, e o teste passa a varrer o conjunto
    inteiro. Uma action futura que nao escreva precisa mudar este teste de
    proposito, e nao herdar silenciosamente a dispensa.
    """
    for name, literal in ACTION_LITERALS.items():
        assert _FILE_OPS_RULES_PATH in literal, name


def test_analisar_complexidade_escreve_so_o_namespace():
    """C6/Task 22: a action deixou de ser read-only, mas nao virou escritora.

    O gate aqui e textual porque o escritor e o LLM, nao o app: o que da para
    verificar em teste e que a instrucao carrega a fronteira, com a proibicao
    em LINHA PROPRIA e nao diluida no meio da prosa.
    """
    literal = ACTION_LITERALS["Analisar complexidade"]
    assert "brainstorm_complexity" in literal
    assert _BRAINSTORM_TEMPLATE_PATH in literal, "a forma do bloco mora no template"

    linhas = [ln.strip() for ln in literal.splitlines()]
    proibicao = [ln for ln in linhas if ln.startswith("PROIBIDO alterar qualquer coisa")]
    assert len(proibicao) == 1, f"proibicao nao esta em linha propria: {linhas}"
    assert "brainstorm_complexity" in proibicao[0]
    for alvo in ("frontmatter", "corpo", "arquivo"):
        assert alvo in proibicao[0], alvo

    # A proibicao anterior era absoluta ("nao escreva nada"); manter o texto
    # velho junto com a instrucao nova daria uma ordem contraditoria ao LLM.
    assert "NAO crie, escreva, anexe" not in literal
    assert "APENAS no terminal" not in literal


def test_actions_de_c6_citam_a_persona_que_as_sustenta():
    """As tres actions novas nascem de nuance de persona; o literal cita a fonte."""
    esperado = {
        "Questionar": "questioner-rules.md",
        "Delegar": "analista-delegador-rules.md",
        "Atualizar scaffolds e blueprints": "scaffolds-blueprints-updater.md",
    }
    for action, persona in esperado.items():
        assert persona in ACTION_LITERALS[action], action


def test_delegar_deriva_os_dois_destinos_do_proprio_arquivo():
    """O payload do botao nao carrega tasklist alvo; o literal resolve isso."""
    literal = ACTION_LITERALS["Delegar"]
    assert "PROGRESS-" in literal
    assert "-tasks.md" in literal
    assert "nao carrega um path de tasklist separado" in literal


def test_atualizar_catalogos_restringe_destino_e_nao_volume():
    literal = ACTION_LITERALS["Atualizar scaffolds e blueprints"]
    assert "ai-forge/scaffolds/" in literal
    assert "ai-forge/blueprints/" in literal


def test_questionar_persiste_so_a_sintese_final():
    literal = ACTION_LITERALS["Questionar"]
    assert "sintese final" in literal
    assert "uma pergunta por vez" in literal


def test_loop_prepare_deriva_a_tabela_em_vez_de_copiar():
    """C6/Task 21 + Codex F9 #1 + Codex R3 s3: o literal CITA, nao redefine.

    Mesma correcao aplicada ao corpo do seed 09, pela mesma razao: o catalogo
    repetia enum de modos, mapa de botoes e veredito de JSON por modo, todos
    declarados na tabela `Handoff condicional por modo` da persona. Duas
    fontes escrevendo o mesmo mapa e como a divergencia comecou.
    """
    literal = ACTION_LITERALS["Loop prepare"]
    assert_deriva_a_tabela_sem_copiar(literal, "ACTION_LITERALS['Loop prepare']")
    # A proibicao universal continua NOMEANDO o artefato: ela vale nos cinco
    # modos, entao nao e veredito por modo e nao e copia da terceira coluna.
    assert "_LOOP-CONFIG.json" in literal
    assert "NAO cria" in literal


def test_criar_arquivo_cites_the_single_form_contract():
    """C1 + Codex R3 s3: o literal CITA o template; nao redeclara nada dele.

    A versao anterior terminava em `assert "draft" in literal`, com o
    comentario de que o literal "so declara o efeito no instante da criacao".
    Declarar o efeito E redeclarar a regra: o efeito no instante da criacao e
    literalmente o item 1 da Regra 3. Aquela linha nao era uma garantia frouxa,
    era uma garantia INVERTIDA -- ela reprovaria a deduplicacao correta e
    aprovaria a copia que a lane tinha.
    """
    literal = ACTION_LITERALS["Criar arquivo"]
    assert_deriva_o_contrato_de_forma_sem_copiar(
        literal, "ACTION_LITERALS['Criar arquivo']"
    )
    assert _BRAINSTORM_VALIDATOR_PATH in literal
    assert "STARTER.md" not in literal, (
        "STARTER.md e o contrato da lane /mcp:research, nao da brainstorm"
    )


def test_precedence_clause_is_defined_once_and_shared():
    """D15/C1: uma clausula de precedencia, nao uma copia por template."""
    assert _PRECEDENCE_CLAUSE.strip()
    assert _FILE_OPS_RULES_PATH in _PRECEDENCE_CLAUSE
    assert "operador" in _PRECEDENCE_CLAUSE
