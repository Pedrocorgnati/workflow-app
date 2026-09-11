"""C2c -- o corpo do seed E o texto despachado ao modelo.

Antes deste cluster existiam DUAS fontes para o mesmo prompt: o dicionario
`ACTION_LITERALS`, que era o que o modelo de fato recebia, e o bloco
`## Prompt canonico` de cada seed, que era o que o operador lia e editava pela
engrenagem. Editar o seed nao mudava nada do que era despachado -- a
engrenagem gravava com sucesso num texto inerte.

Estes testes travam a nova regra: o corpo vence, `ACTION_LITERALS` sobra como
fallback de quem nao tem seed, e a preferencia e por PRESENCA da chave.
"""

import re
from pathlib import Path

import pytest

import yaml

from workflow_app.brainstorm_seed_contract import (
    CANONICAL_SEED_FILENAMES,
    SEED_PROMPT_BEGIN,
    SEED_PROMPT_END,
    extract_action_literal,
    resolve_seed_dir,
    validate_action_literal,
)
from workflow_app.widgets.mcp_prompt_actions import (
    ACTION_LITERALS,
    build_prompt,
)

REPO_ROOT = Path(__file__).parents[3].resolve()
_FRONTMATTER_RX = re.compile(r"^\s*---\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.S)


def _base_meta(**over):
    meta = {
        "target_path": False,
        "action": "Otimizar",
        "agent_name": "agente-x",
        "agent_path": "ai-forge/MCP/agents/criar-md-rules.md",
    }
    meta.update(over)
    return meta


# ── 1. Preferencia ──────────────────────────────────────────────────────────

def test_corpo_do_seed_vence_action_literals():
    corpo = "TEXTO QUE VEIO DO SEED, unico e reconhecivel."
    p = build_prompt(_base_meta(action_literal=corpo), None, REPO_ROOT)
    assert corpo in p
    assert ACTION_LITERALS["Otimizar"] not in p


def test_sem_a_chave_o_fallback_continua_valendo():
    """`ACTION_LITERALS` nao virou codigo morto: e o caminho sem seed."""
    p = build_prompt(_base_meta(), None, REPO_ROOT)
    assert ACTION_LITERALS["Otimizar"] in p


def test_preferencia_e_por_presenca_nao_por_truthiness():
    """String vazia e um valor, nao 'ausente' -- e o validador a recusa."""
    with pytest.raises(ValueError, match="action_literal invalido"):
        build_prompt(_base_meta(action_literal=""), None, REPO_ROOT)


def test_action_nova_passa_quando_o_seed_traz_o_proprio_corpo():
    """Task 29: com vocabulario aberto, o catalogo nao pode barrar a action.

    Antes desta task o gate de pertinencia a `ACTION_LITERALS` rodava antes de
    olhar o corpo, entao uma action digitada no combo aberto do gear virava um
    botao que levantava `ValueError` na montagem do prompt -- o combo abria e o
    produto quebrava dois passos depois.
    """
    out = build_prompt(
        _base_meta(action="NaoExiste", action_literal="corpo proprio"),
        None,
        REPO_ROOT,
    )
    assert "corpo proprio" in out


def test_sem_corpo_a_action_continua_presa_ao_catalogo():
    """O gate mudou de lugar, nao evaporou.

    Sem bloco `## Prompt canonico` o catalogo e a UNICA fonte do texto: aceitar
    uma action fora dele seria despachar prompt sem literal nenhum.
    """
    with pytest.raises(ValueError, match="action invalida"):
        build_prompt(_base_meta(action="NaoExiste"), None, REPO_ROOT)


# ── 2. Blindagem de quem chama sem passar pelo loader ───────────────────────

@pytest.mark.parametrize(
    "ruim, motivo",
    [
        ("usa {action} aqui", "token reservado"),
        ("usa {target-path} aqui", "token reservado"),
        ("corpo\n## Sub\nmais", "heading"),
        ("com\x00nul", "NUL"),
        (123, "str"),
    ],
)
def test_build_prompt_revalida_literal_de_caller_direto(ruim, motivo):
    """`build_prompt` nao confia que o caller passou pelo loader."""
    with pytest.raises(ValueError, match="action_literal invalido"):
        build_prompt(_base_meta(action_literal=ruim), None, REPO_ROOT)


def test_corpo_com_chaves_nao_sofre_interpolacao_recursiva():
    """Anti-injection: `.replace()` nao reprocessa o texto inserido.

    `{action}` e substituido por ULTIMO e `str.replace` nao varre o resultado,
    entao notacao de Classe A dentro do corpo (`{slug}`, `{MM-DD}`) chega
    literal ao modelo -- que e exatamente o que os seeds precisam.
    """
    corpo = "grave em MM-DD-{repositorio}-{slug-simples}.md"
    p = build_prompt(_base_meta(action_literal=corpo), None, REPO_ROOT)
    assert "{repositorio}" in p and "{slug-simples}" in p


# ── 3. Paridade contra os seeds REAIS em disco ──────────────────────────────

def _literais_reais():
    seed_dir = resolve_seed_dir(REPO_ROOT)
    out = []
    for name in CANONICAL_SEED_FILENAMES:
        text = (seed_dir / name).read_text(encoding="utf-8")
        m = _FRONTMATTER_RX.match(text)
        assert m, f"{name}: frontmatter ausente"
        out.append((name, extract_action_literal(text[m.end():])))
    return out


def test_todos_os_seeds_reais_tem_bloco_valido():
    for name, lit in _literais_reais():
        assert lit is not None, f"{name}: bloco `## Prompt canonico` ausente"
        assert validate_action_literal(lit) is None, f"{name} recusado"


def _seeds_reais():
    """(nome, frontmatter, literal) de cada seed canonico, do disco.

    `_literais_reais` devolve so o corpo, e por isso todo teste que o usava
    montava um `_base_meta` artificial com `target_path=False` fixo. Os 23
    seeds que declaram `target_path: true` renderizam por OUTRO template --
    exatamente o que nunca era exercitado contra o arquivo real.
    """
    seed_dir = resolve_seed_dir(REPO_ROOT)
    out = []
    for name in CANONICAL_SEED_FILENAMES:
        text = (seed_dir / name).read_text(encoding="utf-8")
        m = _FRONTMATTER_RX.match(text)
        assert m, f"{name}: frontmatter ausente"
        fm = yaml.safe_load(m.group(1)) or {}
        out.append((name, fm, extract_action_literal(text[m.end():])))
    return out


def _meta_do_seed(fm, literal):
    return {
        "target_path": bool(fm.get("target_path")),
        "action": fm["action"],
        "agent_name": fm["agent_name"],
        "agent_path": fm["agent_path"],
        "action_literal": literal,
    }


def test_o_corpo_chega_inteiro_e_delimitado_em_cada_seed_real():
    """O corpo inteiro atravessa o render, uma vez so, dentro do bloco.

    O teste antigo comparava apenas a PRIMEIRA LINHA do corpo com o prompt
    final -- e a primeira linha e justamente a que sobrevive a qualquer
    truncamento. Ele passou verde durante todo o periodo em que o cutover
    C2c emendava o corpo no meio da frase de `TEMPLATE_SHORT`, produzindo
    "...neste tipo de tarefa\ne\nVoce e o agente ..." e um ".." final.
    Primeira linha presente, prompt quebrado, suite verde.

    O que se trava aqui e o CONTRATO DE COMPOSICAO, nao a prosa: o bloco
    abre e fecha uma vez, e o que esta entre os delimitadores e byte a byte
    o que `extract_action_literal` devolveu. Reescrever um seed inteiro nao
    reprova aqui; emendar, truncar ou duplicar o corpo reprova.

    Roda com o `target_path` REAL de cada seed, entao cobre os dois
    templates standalone.
    """
    for name, fm, lit in _seeds_reais():
        alvo = "blacksmith/brainstorm-mcp/alvo.md" if fm.get("target_path") else None
        p = build_prompt(_meta_do_seed(fm, lit), alvo, REPO_ROOT)

        assert p.count(SEED_PROMPT_BEGIN) == 1, f"{name}: abertura duplicada"
        assert p.count(SEED_PROMPT_END) == 1, f"{name}: fechamento duplicado"
        bloco = p.split(SEED_PROMPT_BEGIN, 1)[1].split(SEED_PROMPT_END, 1)[0]
        assert bloco.strip("\n") == lit.strip(), f"{name}: corpo alterado no render"


def test_nada_do_template_e_emendado_no_corpo_do_seed():
    """Nenhuma frase do contrato de fragmento sobra depois do corpo.

    Os quatro sintomas do splice, travados um a um:
    (a) a frase "e {action}." de `TEMPLATE_SHORT` nao envolve mais o corpo;
    (b) "o conteudo deste arquivo <alvo>." de `TEMPLATE_HARDENED` nao fica
        pendurado DEPOIS da ultima restricao do operador;
    (c) o template nao declara persona em prosa competindo com a do corpo;
    (d) o corpo termina onde terminava, sem ganhar um segundo ponto final.
    """
    for name, fm, lit in _seeds_reais():
        alvo = "blacksmith/brainstorm-mcp/alvo.md" if fm.get("target_path") else None
        p = build_prompt(_meta_do_seed(fm, lit), alvo, REPO_ROOT)
        assert SEED_PROMPT_END in p, f"{name}: corpo nao foi embrulhado"
        depois = p.split(SEED_PROMPT_END, 1)[1]

        assert "faria neste tipo" not in p, f"{name}: frase de fragmento no render"
        assert "o conteudo deste arquivo" not in p, f"{name}: cauda do hardened"
        assert "Atue como um" not in p, f"{name}: persona em prosa no template"
        assert ".." not in p.split(SEED_PROMPT_BEGIN, 1)[0], f"{name}: '..' no cabecalho"
        assert depois.strip() == "", f"{name}: sobrou texto apos o bloco: {depois!r}"


def test_o_catalogo_continua_no_contrato_de_fragmento():
    """Sem seed, o render historico sobrevive intacto -- e a outra metade.

    Se a escolha de template deixasse de olhar a proveniencia e passasse a
    embrulhar tudo, os literais do catalogo -- que sao fragmentos escritos
    para COMPLETAR a frase -- virariam blocos soltos comecando em minuscula.
    """
    p = build_prompt(_base_meta(), None, REPO_ROOT)
    assert SEED_PROMPT_BEGIN not in p
    assert "faria neste tipo de tarefa" in p
    assert ACTION_LITERALS["Otimizar"] in p


def test_nenhum_seed_real_reintroduz_token_de_manutencao():
    """Gate do C2b travado em teste: `{type}` e `§N.N` nao voltam."""
    sujos = []
    for name, lit in _literais_reais():
        if "{type}" in lit:
            sujos.append(f"{name}: {{type}}")
        if re.search(r"§\d", lit):
            sujos.append(f"{name}: referencia §N.N")
    assert not sujos, sujos


# ── 4. Task 32: fallback exaustivo ──────────────────────────────────────────

@pytest.mark.parametrize("nome", sorted(ACTION_LITERALS))
def test_toda_action_do_catalogo_resolve_sem_seed(nome):
    """O fallback vale para o catalogo INTEIRO, nao so para `Otimizar`.

    O teste antigo cobria uma action. Bastava o gate de C2c ficar sensivel ao
    nome da action -- um `if base["action"] == "Otimizar"` defensivo, um
    catalogo dividido em dois dicts -- para 11 dos 12 caminhos quebrarem com a
    suite verde.
    """
    p = build_prompt(_base_meta(action=nome), None, REPO_ROOT)
    assert ACTION_LITERALS[nome] in p


# ── 5. Task 32: nenhum placeholder morto sobrevive no render ────────────────

#: Retrato A13 (medido em 2026-08-24, limpo pela Task 26): tokens que os
#: corpos dos seeds usavam como se fossem interpolados e que `_fill_template`
#: nunca substituiu. Nao estao em `_PLACEHOLDERS` -- chegavam ao modelo com as
#: chaves, pedindo que ELE preenchesse um valor que ninguem lhe deu.
_TOKENS_MORTOS_A13 = (
    "{type}",
    "{workspace_root}",
    "{slug-simples}",
    "{repositorio}",
    "{MM-DD}",
    "{slug}",
    "{name}",
)

_TOKEN_RX = re.compile(r"\{[^{}\n]{1,40}\}")


def test_nenhum_token_morto_de_a13_volta_aos_corpos_reais():
    """Guarda a limpeza da Task 26 pelo NOME de cada token."""
    sujos = [
        f"{name}: {tok}"
        for name, lit in _literais_reais()
        for tok in _TOKENS_MORTOS_A13
        if tok in lit
    ]
    assert not sujos, sujos


@pytest.mark.parametrize("alvo", [False, True])
def test_prompt_renderizado_nao_tem_nenhuma_chave_sobrevivente(alvo):
    """Mais forte que a lista: ZERO `{...}` no texto que sai para o modelo.

    A lista nomeada acima envelhece -- um token morto NOVO, inventado amanha
    num corpo de seed, passaria por ela. Esta versao nao tem nome para
    envelhecer: depois de `_fill_template` rodar, todo placeholder real ja
    virou valor, entao qualquer chave remanescente e, por definicao, uma
    chave que ninguem substitui.

    Roda nas duas formas de template, porque so `TEMPLATE_HARDENED` carrega
    `{target-path}` e so ele poderia deixar a chave para tras quando o valor
    e vazio.
    """
    sobreviventes = {}
    for name, lit in _literais_reais():
        p = build_prompt(
            _base_meta(target_path=alvo, action_literal=lit),
            "blacksmith/brainstorm-mcp/alvo.md" if alvo else None,
            REPO_ROOT,
        )
        achados = sorted(set(_TOKEN_RX.findall(p)))
        if achados:
            sobreviventes[name] = achados
    assert not sobreviventes, sobreviventes


def test_o_suplemento_tambem_esta_limpo():
    """`search-prod.md` e despachado como os outros e some das varreduras.

    Ele nao esta em `CANONICAL_SEED_FILENAMES` (vive em `seeds/supplemental/`)
    -- entao toda checagem que itera a tupla canonica o ignora em silencio.
    Era o unico corpo que ainda afirmava, por escrito, que `{type}` seria
    "substituido em runtime".
    """
    caminho = resolve_seed_dir(REPO_ROOT) / "supplemental" / "search-prod.md"
    texto = caminho.read_text(encoding="utf-8")
    m = _FRONTMATTER_RX.match(texto)
    assert m, "suplemento sem frontmatter"
    lit = extract_action_literal(texto[m.end():])
    assert lit is not None, "suplemento sem bloco `## Prompt canonico`"
    assert validate_action_literal(lit) is None
    assert not _TOKEN_RX.findall(lit), _TOKEN_RX.findall(lit)

    p = build_prompt(_base_meta(action_literal=lit), None, REPO_ROOT)
    assert not _TOKEN_RX.findall(p)
