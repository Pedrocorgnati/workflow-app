"""Contrato canonico de identidade dos seeds do brainstorm MCP.

Este modulo e o DONO UNICO da cardinalidade e da identidade dos seeds
brainstorm. A cardinalidade (``CANONICAL_SEED_COUNT``) e a tupla fechada
``CANONICAL_SEED_FILENAMES`` sao derivadas diretamente dos arquivos reais
lidos do disco no momento da construcao do modulo.

``C2`` estendeu-o com o parsing e a validacao do bloco
``## Prompt canonico`` -- o texto do corpo do seed que e despachado ao modelo.
NAO ha campo ``action_literal`` no frontmatter nem bump de schema: o corpo e a
unica fonte persistida, e duplicar o texto criaria uma segunda copia que o gear
teria de manter sincronizada (D15). E PROIBIDO criar um segundo modulo com a
mesma responsabilidade (10.6 conflito 1).

``C6`` estendeu-o com ``PERSONA_ACTION_COHERENCE`` e
``validate_persona_action``: identidade de seed nao e so o nome do arquivo,
e tambem o par persona-action que aquele botao dispara. O modulo continua
PURO -- sem Qt, sem I/O -- porque o gate G7 roda tanto no loader da grade
quanto no submit do gear, e um dos dois nao pode depender do outro.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

#: Diretorio relativo (a partir da raiz do repo SystemForge) onde residem
#: os 24 seeds canonicos do brainstorm MCP. Os seeds foram migrados do
#: diretorio pai para `seeds/` na Task 08 do loop
#: 08-25-systemforge-analise-fluxo-brainstorm.
BRAINSTORM_SEEDS_RELDIR: str = "blacksmith/brainstorm-mcp/seeds"

#: Diretorio relativo (a partir da raiz do repo SystemForge) onde residem
#: seeds suplementares (fora da cardinalidade canonica).
#: Migracao futura (C3) mova os suplementos para este path.
SUPPLEMENTAL_SEEDS_RELDIR: str = "blacksmith/brainstorm-mcp/seeds/supplemental"

#: Tupla fechada com os 24 nomes de arquivo seed reais lidos do disco.
#: A ordem e lexicografica (01..24).
CANONICAL_SEED_FILENAMES: tuple[str, ...] = (
    "01-criar-md.md",
    "02-pesquisar.md",
    "03-search-out.md",
    "04-search-forge.md",
    "05-deep-detailer.md",
    "06-controversial.md",
    "07-questioner.md",
    "08-hardening.md",
    "09-loop-prepare.md",
    "10-criar-task.md",
    "11-revisar-task.md",
    "12-executar-task.md",
    "13-revisar-execucao.md",
    "14-visual-design.md",
    "15-layout-architect.md",
    "16-analise-complexidade.md",
    "17-billing.md",
    "18-debugger.md",
    "19-delegador.md",
    "20-pdca.md",
    "21-soft-engen.md",
    "22-scaffolds-blueprints-updater.md",
    "23-ux-ui.md",
    "24-performance-engineer.md",
)

#: Cardinalidade canonica: sempre igual a len(CANONICAL_SEED_FILENAMES).
CANONICAL_SEED_COUNT: int = len(CANONICAL_SEED_FILENAMES)


def resolve_seed_dir(root: str | Path) -> Path:
    """Resolve o diretorio absoluto dos seeds a partir de uma raiz qualquer.

    Args:
        root: Raiz do repositorio SystemForge (ou path equivalente).

    Returns:
        Path absoluto do diretorio que contem os 24 seeds canonicos.
    """
    return Path(root).expanduser().resolve() / BRAINSTORM_SEEDS_RELDIR


# ---------------------------------------------------------------------------
# Coerencia persona <-> action (gate G7, bloco C6)
# ---------------------------------------------------------------------------

#: Categorias de persona. A categoria e o que torna a troca de persona
#: detectavel: um seed que troca `criar-task-rules` por `code-debugger` muda
#: de categoria e o par deixa de fechar, mesmo que o `action` nao mude.
PERSONA_CATEGORY_ACTIONS: Mapping[str, frozenset[str]] = MappingProxyType({
    "creator": frozenset({"Criar arquivo"}),
    "researcher": frozenset({"Otimizar"}),
    "enricher": frozenset({"Otimizar"}),
    "critic": frozenset({"Otimizar"}),
    "interrogator": frozenset({"Questionar"}),
    "preparer": frozenset({"Loop prepare"}),
    "task_author": frozenset({"Criar tasks"}),
    "task_reviewer": frozenset({"Revisar tasks"}),
    "executor": frozenset({"Executar"}),
    "execution_reviewer": frozenset({"Revisar execucao"}),
    "reviewer": frozenset({"Revisar"}),
    "router": frozenset({"Analisar complexidade"}),
    "delegator": frozenset({"Delegar"}),
    "catalog_updater": frozenset({"Atualizar scaffolds e blueprints"}),
})

#: Persona -> categoria, com o PATH CANONICO COMPLETO como chave.
#:
#: A chave nao e o slug e nao e derivada do nome do seed, de proposito. Os
#: seeds `19-delegador.md` e `22-scaffolds-blueprints-updater.md` mostram os
#: dois modos de errar isso: o primeiro tem nome de seed que nao lembra o da
#: persona, o segundo tem nome identico ao dela. Chave por slug faria a
#: fixture sintetica de `test_brainstorm_tab_loading.py` passar por acidente.
PERSONA_CATEGORIES: Mapping[str, str] = MappingProxyType({
    "ai-forge/MCP/agents/criar-md-rules.md": "creator",
    "ai-forge/MCP/agents/search-in-rules.md": "researcher",
    "ai-forge/MCP/agents/search-out-rules.md": "researcher",
    "ai-forge/MCP/agents/search-forge-rules.md": "researcher",
    "ai-forge/MCP/agents/deep-detailer.md": "enricher",
    "ai-forge/MCP/agents/controversial-devils-advocate-rules.md": "critic",
    "ai-forge/MCP/agents/questioner-rules.md": "interrogator",
    "ai-forge/MCP/agents/hardening-engineer-rules.md": "enricher",
    "ai-forge/MCP/agents/loop-preparer-rules.md": "preparer",
    "ai-forge/MCP/agents/criar-task-rules.md": "task_author",
    "ai-forge/MCP/agents/revisar-task-rules.md": "task_reviewer",
    "ai-forge/MCP/agents/executar-task-rules.md": "executor",
    "ai-forge/MCP/agents/revisar-execucao-rules.md": "execution_reviewer",
    "ai-forge/MCP/agents/specific-reviewer.md": "reviewer",
    "ai-forge/MCP/agents/layout-architect-rules.md": "enricher",
    "ai-forge/MCP/agents/complexity-router-rules.md": "router",
    "ai-forge/MCP/agents/billing-scpecialist.md": "enricher",
    "ai-forge/MCP/agents/code-debugger.md": "enricher",
    "ai-forge/MCP/agents/analista-delegador-rules.md": "delegator",
    "ai-forge/MCP/agents/orquestrador-pdca-rules.md": "enricher",
    "ai-forge/MCP/agents/soft-engineer.md": "enricher",
    "ai-forge/MCP/agents/scaffolds-blueprints-updater.md": "catalog_updater",
    "ai-forge/MCP/agents/ux-ui-specialist.md": "reviewer",
    "ai-forge/MCP/agents/performance-engineer.md": "reviewer",
})

#: Nuances medidas em A7, uma frase por persona, citando a linha que as
#: sustenta. Elas existem para que a reprovacao explique O QUE na persona
#: contradiz a action, em vez de dizer apenas "incoerente".
#:
#: As tres sao especificas e NAO foram generalizadas: o delegador proibe
#: producao propria, o questioner condiciona a escrita a confirmacao previa,
#: e o updater de catalogos restringe o DESTINO e nao a mutacao. Sao limites
#: diferentes; achatar os tres em "nao escreve" seria exagerar o veredito.
PERSONA_ACTION_NUANCES: Mapping[str, str] = MappingProxyType({
    "ai-forge/MCP/agents/analista-delegador-rules.md": (
        "analista-delegador-rules.md:23 atribui toda producao tecnica aos "
        "agentes delegados e reserva a escrita a um PROGRESS proprio e a uma "
        "tasklist alvo; uma action que reescreve o proprio alvo contradiz isso"
    ),
    "ai-forge/MCP/agents/questioner-rules.md": (
        "questioner-rules.md:19 define persistencia padrao como sintese final "
        "e so admite escrita incremental por pedido explicito, sobre decisao "
        "ja confirmada; uma action de escrita incondicional contradiz isso"
    ),
    "ai-forge/MCP/agents/scaffolds-blueprints-updater.md": (
        "scaffolds-blueprints-updater.md:16 restringe os alvos a "
        "`ai-forge/scaffolds/`, `ai-forge/blueprints/` e seus indices; a "
        "restricao e de DESTINO, nao de mutacao, entao a action precisa ser a "
        "que escreve nesses catalogos"
    ),
})

#: Projecao final consumida pelo gate: persona -> actions aceitas.
PERSONA_ACTION_COHERENCE: Mapping[str, frozenset[str]] = MappingProxyType({
    path: PERSONA_CATEGORY_ACTIONS[category]
    for path, category in PERSONA_CATEGORIES.items()
})

#: Paths de persona que este contrato conhece. Exposto porque
#: `validate_persona_action` se ABSTEM sobre persona desconhecida, e quem
#: chama precisa poder distinguir "aprovado" de "nao julgado".
KNOWN_PERSONA_PATHS: frozenset[str] = frozenset(PERSONA_CATEGORIES)

#: Actions que este contrato JA MEDIU, em qualquer categoria. Existe pelo
#: mesmo motivo de `KNOWN_PERSONA_PATHS`: `validate_persona_action` se abstem
#: sobre o que nunca mediu, e a abstencao tem de ser simetrica nos dois eixos.
#:
#: Sem isto o gate G7 anulava a Task 29 na pratica. Cada categoria aceita
#: exatamente UMA action, entao qualquer action nova sobre uma persona
#: CONHECIDA -- que e o caso dos 24 seeds reais -- era reprovada por
#: "incoerencia", quando o que de fato acontecia era o contrato nunca ter
#: visto aquele rotulo. A action nova so passava sobre persona desconhecida,
#: unico ramo onde o gate ja se abstinha.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    a for acoes in PERSONA_CATEGORY_ACTIONS.values() for a in acoes
)


def _normalize_agent_path(agent_path: str) -> str:
    """Normaliza a chave: separador posix e sem `./` na frente."""
    return str(agent_path).strip().replace("\\", "/").lstrip("./")


def validate_persona_action(agent_path: str, action: str) -> str | None:
    """Julga o par persona-action de um seed. Funcao pura.

    Args:
        agent_path: Path canonico da persona, como aparece em `agent_path`.
        action: Rotulo da action, como aparece em `action`.

    Returns:
        `None` quando o par e coerente, quando a persona e desconhecida
        deste contrato, OU quando a action nunca foi medida por ele
        (`KNOWN_ACTIONS`); caso contrario, a razao da incoerencia.

    A abstencao sobre persona desconhecida e deliberada. O gear deixa o
    operador apontar `agent_path` para uma persona nova, e inventar um
    veredito para quem nunca foi medido transformaria o gate em bloqueio de
    trabalho legitimo. Quem precisa da distincao consulta
    `KNOWN_PERSONA_PATHS` e decide o proprio aviso -- o que o gate nao pode
    fazer e afirmar coerencia que nao verificou.
    """
    key = _normalize_agent_path(agent_path)
    allowed = PERSONA_ACTION_COHERENCE.get(key)
    if allowed is None:
        return None
    action = str(action).strip()
    if action in allowed:
        return None
    # Abstencao simetrica a de persona desconhecida: uma action que este
    # contrato nunca mediu nao e evidencia de INCOERENCIA, e evidencia de
    # rotulo novo. Reprovar aqui devolveria o vocabulario fechado que a
    # Task 29 abriu -- toda action nascida no combo do gear morreria no
    # rebuild seguinte, porque os 24 seeds reais tem persona conhecida.
    #
    # O que continua reprovado, e e o defeito que G7 existe para pegar: uma
    # action CONHECIDA sobre uma persona que nao a sustenta (`criar-md-rules`
    # com `Questionar`), que denuncia seed que trocou de persona sem trocar
    # de action.
    if action not in KNOWN_ACTIONS:
        return None
    esperado = ", ".join(sorted(allowed))
    razao = PERSONA_ACTION_NUANCES.get(key)
    base = (
        f"persona `{key}` (categoria `{PERSONA_CATEGORIES[key]}`) nao "
        f"sustenta a action `{action}`; aceita: {esperado}"
    )
    return f"{base}. {razao}" if razao else base



# ---------------------------------------------------------------------------
# C2 - o corpo do seed E o literal despachado
# ---------------------------------------------------------------------------
#
# O bloco `## Prompt canonico` do corpo do seed e o texto que substitui
# `{action}` no template do prompt. Ele NAO tem copia no frontmatter: copia
# seria segunda fonte persistida do mesmo dado, e o gear passaria a ter de
# gravar as duas (D15 -- escritor unico, leitor derivado).
#
# Este bloco e o dono UNICO do parsing e da validacao desse texto. O loader da
# grade (`main_window._load_one_brainstorm_seed`) e o gear
# (`brainstorm_mcp_config_dialog`) importam daqui; a regex NAO e duplicada nos
# dois. O modulo continua puro -- sem Qt, sem I/O -- porque os dois chamadores
# precisam do mesmo veredito e nenhum pode depender do outro.

#: Heading que abre o bloco canonico, e a regex que o delimita. O terminador
#: `(?=^## |\Z)` e o que torna um `## ` digitado DENTRO do editor capaz de
#: truncar o bloco em silencio -- por isso `validate_action_literal` recusa
#: heading H2 interno ANTES da gravacao (o texto ja truncado, lido de volta do
#: disco, nao teria como acusar nada).
#: Forma de nome de um seed: `NN-<slug>.md`, prefixo com DOIS OU MAIS digitos.
#:
#: A abertura para `\d{2,}` (Task 29) e deliberada: a regex de exatamente dois
#: digitos impunha um teto de 99 seeds sem que nada no produto dissesse isso.
#: `01..N` contiguo passou a ser a regra de cardinalidade, entao o teto tinha
#: de sair junto -- senao o seed 100 seria classificado como intruso e sumiria
#: da grade em silencio, que e o modo de falha que C2 existe para fechar.
#:
#: ROTEADOR, NAO VALIDADOR. Decide QUEM e candidato a seed pela forma do nome.
#: Frontmatter, schema e coerencia persona-action continuam sendo julgados
#: pelo loader e pelo validador -- um nome bem formado com corpo podre vira
#: `issue` visivel, nunca seed silencioso.
SEED_FILENAME_RX = re.compile(r"^(\d{2,})-([a-z][a-z0-9-]*)\.md$")

#: Forma de um OUTPUT (`MM-DD-slug.md`). Testada ANTES de `SEED_FILENAME_RX`.
#:
#: As duas formas colidem: `05-24-foot-stock-bugfix.md` casa como seed de
#: prefixo `05` (colisao medida em disco em 2026-05-24, quando dois outputs
#: salvos no diretorio errado apagaram seeds da grade). A precedencia e o que
#: separa as duas, nao a regex.
SEED_OUTPUT_RX = re.compile(r"^\d{2}-\d{2}-.+\.md$")


def seed_prefix(name: str) -> int | None:
    """Prefixo numerico de um nome com forma de seed, ou None.

    `MM-DD-slug.md` devolve None mesmo casando com a forma de seed: a
    precedencia de output vive AQUI, num lugar so, para os tres consumidores
    (loader da grade, engrenagem, classificador) nao a reimplementarem cada
    um com uma ordem diferente.
    """
    if SEED_OUTPUT_RX.match(name):
        return None
    m = SEED_FILENAME_RX.match(name)
    return int(m.group(1)) if m else None


_PROMPT_SECTION_HEADING: str = "## Prompt canonico"

#: Delimitadores do bloco que o renderer usa para embrulhar o corpo do seed
#: no prompt final (contrato `standalone`). Moram AQUI, e nao no renderer,
#: porque `validate_action_literal` precisa recusar corpo que os contenha:
#: um corpo que escreva a linha de fim por conta propria fecharia o bloco
#: mais cedo e tudo depois dela leria como instrucao do sistema. Duas copias
#: da string -- uma no renderer, outra no validador -- divergiriam calado e
#: reabririam exatamente essa brecha.
SEED_PROMPT_BEGIN: str = "--- PROMPT DO BOTAO ---"
SEED_PROMPT_END: str = "--- FIM DO PROMPT DO BOTAO ---"

_PROMPT_SECTION_RX: "re.Pattern[str]" = re.compile(
    r"(^## Prompt canonico[ \t]*$\n?)(.*?)(?=^## |\Z)", re.M | re.S
)

#: Detecta heading H2 interno. `## foo` trunca de fato; `##` sozinho nao
#: trunca, mas e ambiguo o bastante para ser recusado junto.
_H2_INSIDE_RX: "re.Pattern[str]" = re.compile(r"^##(?:[ \t]|$)", re.M)

#: Teto do literal, identico ao `MAX_FIELD_LEN['prompt']` que o gear ja aplica.
MAX_ACTION_LITERAL_LEN: int = 32768

#: Tokens que `mcp_prompt_actions._fill_template` substitui no template. Eles
#: sao RESERVADOS: um literal que os contenha nao sofre substituicao hoje
#: (`{action}` e o ultimo da ordem e `str.replace()` nao reprocessa o texto
#: inserido -- anti-interpolacao documentada em `mcp_prompt_actions.py:20-21`),
#: mas sobrevive cru ate o modelo e viraria substituicao de verdade se alguem
#: reordenasse a tupla. `_PLACEHOLDERS` DERIVA desta constante.
RESERVED_RENDER_TOKENS: tuple[str, ...] = (
    "target-path",
    "agent-name",
    "agent-path",
    "action",
)


def extract_action_literal(body: str) -> str | None:
    """Extrai o bloco `## Prompt canonico` do corpo do seed.

    Devolve `None` quando o bloco NAO existe e `str` quando existe -- inclusive
    string vazia, quando existe e esta vazio. A distincao e o contrato inteiro:
    ausencia vira `issue` do item no loader, presenca vazia e um literal vazio
    legitimo que o transporte carrega ate `build_prompt`.

    `extract_prompt_body` do gear colapsava os dois casos em `""` e por isso nao
    podia ser reusada aqui.

    Raise `ValueError` quando ha mais de um bloco: qual deles vale seria uma
    escolha arbitraria, e escolher em silencio e pior do que recusar.
    """
    if not isinstance(body, str):
        raise TypeError("body deve ser str")
    matches = list(_PROMPT_SECTION_RX.finditer(body))
    if len(matches) > 1:
        raise ValueError(
            f"mais de um bloco `{_PROMPT_SECTION_HEADING}` "
            f"({len(matches)} encontrados)"
        )
    if not matches:
        return None
    return matches[0].group(2).rstrip()


def replace_action_literal(body: str, novo: str) -> str:
    """Devolve `body` com o bloco `## Prompt canonico` trocado por `novo`.

    Funcao pura, sem I/O. Existe aqui, e nao no gear, para que a LEITURA
    (`extract_action_literal`) e a ESCRITA do mesmo bloco compartilhem a
    unica regex. O gear tinha a sua propria copia (`_PROMPT_RX`), e duas
    regexes do mesmo bloco e como o produto ganha um caso em que ler e
    escrever discordam sem ninguem notar.

    Raises:
        ValueError: quando o bloco nao existe. Substituir em silencio
            devolveria o corpo intacto e o save reportaria sucesso sem ter
            gravado a edicao do operador.
    """
    if not _PROMPT_SECTION_RX.search(body):
        raise ValueError("bloco `## Prompt canonico` ausente")
    return _PROMPT_SECTION_RX.sub(
        lambda m: f"{m.group(1)}{novo.rstrip()}\n\n", body, count=1
    )


def validate_action_literal(literal: object) -> str | None:
    """Julga um literal de action. Devolve o motivo da recusa, ou `None`.

    Devolve motivo (str) em vez de levantar porque os dois chamadores fazem
    coisas diferentes com a falha: o loader vira `issue` daquele item e degrada
    so ele, o gear bloqueia o Save mostrando a mesma frase.

    Chamado pelo gear sobre o BUFFER DO EDITOR, antes de gravar -- e esse o
    unico momento em que o heading H2 interno ainda e detectavel.
    """
    if not isinstance(literal, str):
        return "literal de action deve ser str"
    if "\x00" in literal:
        return "literal de action contem NUL"
    ctrl = sorted(
        {
            ch
            for ch in literal
            if ch not in ("\n", "\t") and unicodedata.category(ch)[0] == "C"
        }
    )
    if ctrl:
        nomes = ", ".join(repr(c) for c in ctrl[:5])
        return f"literal de action contem control chars: {nomes}"
    if not literal.strip():
        return (
            f"bloco `{_PROMPT_SECTION_HEADING}` vazio; ele e o texto "
            "despachado ao modelo e nao pode ser branco"
        )
    if len(literal) > MAX_ACTION_LITERAL_LEN:
        return (
            f"literal de action excede {MAX_ACTION_LITERAL_LEN} chars "
            f"(tem {len(literal)})"
        )
    if _H2_INSIDE_RX.search(literal):
        return (
            f"literal de action contem heading `##`, que encerraria o bloco "
            f"`{_PROMPT_SECTION_HEADING}` e truncaria o texto na releitura"
        )
    forjados = [
        d for d in (SEED_PROMPT_BEGIN, SEED_PROMPT_END) if d in literal
    ]
    if forjados:
        nomes = ", ".join(repr(d) for d in forjados)
        return (
            f"literal de action contem delimitador do bloco de prompt: {nomes}; "
            "escrever essa linha no corpo fecharia o bloco mais cedo e o resto "
            "do texto seria lido como instrucao do sistema"
        )
    achados = [t for t in RESERVED_RENDER_TOKENS if "{" + t + "}" in literal]
    if achados:
        nomes = ", ".join("{" + t + "}" for t in achados)
        return (
            f"literal de action contem token reservado do renderer: {nomes}"
        )
    return None


__all__ = [
    "BRAINSTORM_SEEDS_RELDIR",
    "SUPPLEMENTAL_SEEDS_RELDIR",
    "CANONICAL_SEED_FILENAMES",
    "CANONICAL_SEED_COUNT",
    "resolve_seed_dir",
    "PERSONA_CATEGORY_ACTIONS",
    "PERSONA_CATEGORIES",
    "PERSONA_ACTION_NUANCES",
    "PERSONA_ACTION_COHERENCE",
    "KNOWN_PERSONA_PATHS",
    "KNOWN_ACTIONS",
    "validate_persona_action",
    "SEED_FILENAME_RX",
    "SEED_OUTPUT_RX",
    "seed_prefix",
    "MAX_ACTION_LITERAL_LEN",
    "SEED_PROMPT_BEGIN",
    "SEED_PROMPT_END",
    "RESERVED_RENDER_TOKENS",
    "extract_action_literal",
    "replace_action_literal",
    "validate_action_literal",
]
