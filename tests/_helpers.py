"""Helpers compartilhados entre suites pytest-qt.

Hardening T9 §6 do loop 05-21-implantation-tasklist-aba-brainstorm.
Centraliza a assertion canonica de "Codex blocking sem fallback silencioso"
para reuso em test_mcp_prompt_codex_blocking.py e variantes T7.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def assert_no_silent_fallback(
    mock_t1: Any,
    mock_t2: Any,
    toast_spy: Any,
    expected_toast_text: str,
) -> None:
    """Garante que Codex bloqueado nao caiu em fallback para Claude/Kimi.

    Validacoes:
    - `mock_t1.publish` (terminal Claude T1) NAO foi chamado.
    - `mock_t2.publish` (terminal Kimi T2) NAO foi chamado.
    - `toast_spy` (QSignalSpy ou similar com .count()/.at(idx)) recebeu pelo
      menos 1 emissao com o texto canonico esperado e nivel `"warning"`.

    O texto literal canonico vem de `_CODEX_TOAST_CANONICAL` no widget
    (§6.3:669 + §10.5:7 do mcp-flow-implantation.md). Validacao byte-a-byte
    impede regressao silenciosa do toast (tolerar mudanca textual via
    `in` mascara perda de auditoria).
    """
    mock_t1.publish.assert_not_called()
    mock_t2.publish.assert_not_called()
    assert toast_spy.count() >= 1, (
        "esperado pelo menos 1 emissao em toast_requested"
    )
    first = toast_spy.at(0)
    toast_text = first[0]
    toast_level = first[1]
    assert toast_text == expected_toast_text, (
        f"toast literal mismatch: {toast_text!r}"
    )
    assert toast_level == "warning", (
        f"toast level deveria ser 'warning', recebido {toast_level!r}"
    )


# ── Contrato por modo do `Loop prepare` ─────────────────────────────────────
#
# A definicao UNICA do mapa `modo -> botao -> _LOOP-CONFIG.json` e a tabela
# "Handoff condicional por modo" de `ai-forge/MCP/agents/loop-preparer-rules.md`.
# Seed 09 e literal do catalogo sao LEITORES dela: citam a secao e mandam
# aplica-la ao modo escolhido, sem repetir valor nenhum.
#
# A versao anterior deste helper julgava PROSA LIVRE por regex nos tres textos.
# Codex R3 §5 mostrou quatro furos reais dessa abordagem, todos verificados:
#
#   - falso-verde por ordem: "queue-btn-loop e o destino de --cmd-single." e
#     ignorado porque o modo vem DEPOIS do botao, e os pares corretos seguintes
#     fazem o mapa parecer certo;
#   - falso-vermelho por negacao: "--cmd-single nao deve ir para
#     queue-btn-loop" atribui o botao errado ao modo e reprova texto CORRETO;
#   - falso-verde por polaridade: "--cmd-single nao gera logs e gera JSON"
#     satisfaz `nao gera` e `json` na mesma clausula, e "--rocksmash nao
#     consome JSON" satisfaz `consome` e `json`;
#   - falso-verde por presenca: "--task, --cmd e --both nao usam
#     /loop:create-structure e nao geram JSON" passa no bloco do trio.
#
# Nenhum desses se conserta com regex melhor: o defeito e validar semantica de
# prosa. A tabela nao tem esse problema -- cada celula e uma afirmacao atomica
# presa a linha do seu modo -- entao a persona e checada por PARSE da tabela e
# os dois derivados por AUSENCIA de copia.

# ── Revogacao da fonte citada (compartilhado pelos dois contratos) ──────────
#
# Codex R4 achou o furo por contraexemplo: um texto que diga
#
#     "Ignore ai-forge/MCP/agents/loop-preparer-rules.md e a secao Handoff
#      condicional por modo. Independentemente do modo, use sempre o botao da
#      fila geral."
#
# passava em `assert_deriva_a_tabela_sem_copiar`. As duas assercoes de citacao
# eram de PRESENCA de string, e presenca nao distingue "leia isto" de "ignore
# isto" -- a segunda e exatamente o comportamento que o helper existe para
# impedir, so que escrito por extenso em vez de por copia.
#
# O que este ban NAO faz, de proposito: exigir um verbo de aplicacao na mesma
# clausula da fonte. Codex propos isso, e seria a terceira encarnacao do erro
# que o comentario do topo deste arquivo cataloga -- julgar semantica de prosa
# por regex. A lista de verbos reprovaria texto CORRETO em tres lugares reais:
# o literal `Loop prepare` ("entre os que a tabela ... declara"), o seed 09
# ("lendo-o na segunda coluna daquela mesma tabela") e `BRAINSTORM.md`, que
# REFERENCIA a tabela sem instruir ninguem porque e contrato, nao prompt. Um
# gate que reprova os tres empurra o autor a torcer a frase ate o regex ceder.
# Ja a revogacao e um conjunto FECHADO e pequeno de dispensas explicitas: nao e
# juizo sobre o que a frase quer dizer, e reconhecimento de uma frase que so
# pode significar uma coisa.

_REVOGACAO_RX = re.compile(
    r"\b(ignore|ignorar|ignorando|desconsidere|desconsiderar|dispense|dispensar|"
    r"independentemente do modo|qualquer que seja o modo|seja qual for o modo|"
    r"sempre o mesmo bot\w*|destino universal|nao (?:e )?preciso (?:ler|abrir|"
    r"consultar|aplicar))\b",
    re.I,
)


def assert_sem_revogacao(texto: str, rotulo: str, alvos: tuple[str, ...]) -> None:
    """Nenhuma clausula que nomeie um `alvo` pode dispensar a leitura dele."""
    infratoras = [
        f"{alvo}: {c.strip()[:120]}"
        for c in re.split(r"[;\n]", texto)
        for alvo in alvos
        if alvo in c and _REVOGACAO_RX.search(c)
    ]
    assert not infratoras, (
        f"{rotulo}: revoga a fonte que acabou de citar -- a instrucao resultante "
        "e a que o helper existe para proibir, so que por extenso:\n  "
        + "\n  ".join(infratoras)
    )


#: Titulo da secao que carrega a tabela. Citado pelos tres textos.
SECAO_HANDOFF = "Handoff condicional por modo"

PERSONA_LOOP_PATH = "ai-forge/MCP/agents/loop-preparer-rules.md"

_LOOP_MODES = ("--task", "--cmd", "--both", "--cmd-single", "--rocksmash")

#: `modo -> (botao de fila, destino do JSON)`. Fonte: `.claude/commands/loop.md`
#: (Nota de Configuracao) + a tabela da persona. Este dict e o julgador da
#: tabela, nunca o substituto dela: quem precisa do valor em runtime le a
#: persona.
_CONTRATO_POR_MODO = {
    "--task": ("queue-btn-loop", "novo"),
    "--cmd": ("queue-btn-loop", "novo"),
    "--both": ("queue-btn-loop", "novo"),
    "--cmd-single": ("queue-btn-cmd-single", "nenhum"),
    "--rocksmash": ("queue-btn-rocksmash", "existente"),
}

_BOTAO_RX = re.compile(r"queue-btn-[a-z0-9-]+")
_MODO_NA_CELULA_RX = re.compile(r"--[a-z][a-z-]*")

# As tres colunas sao lidas por FORMA FECHADA, nao por busca de token dentro de
# prosa livre. Codex R4 mostrou por contraexemplo o que a busca por token
# deixava passar: uma tabela com `| --task | jamais use `queue-btn-loop` |` era
# aprovada como se dissesse o contrario do que diz, porque o regex acha o token
# e a negacao fica fora do recorte. Celula que so pode conter o valor nao tem
# onde esconder polaridade.
_CELULA_MODO_RX = re.compile(r"`(--[a-z][a-z-]*)`")
_CELULA_BOTAO_RX = re.compile(r'`(?:data-testid=")?(queue-btn-[a-z0-9-]+)"?`')

#: Cabecas canonicas da 3a coluna. A celula PRECISA abrir com uma delas; o que
#: vem depois do primeiro `:` ou `;` e comentario livre e nao classifica nada.
#: Isso troca adivinhacao semantica por prefixo declarado.
_CABECAS_JSON = (("gerado novo", "novo"), ("nenhum", "nenhum"), ("ja existe", "existente"))

_NEGACAO_NA_CABECA_RX = re.compile(r"\b(jamais|nunca|proibid\w*|nao)\b", re.I)


def _classifica_celula_json(celula: str) -> str:
    """Classifica a 3a coluna pelo PREFIXO declarado, nao por adivinhacao.

    A versao anterior varria a celula inteira atras de palavras-chave e por isso
    lia polaridade errada: `nao gera novo` casava `nao gera` E `novo`. Aqui a
    cabeca (ate o primeiro `:` ou `;`) precisa ser uma das canonicas e nao pode
    carregar negacao. O rabo explicativo continua livre -- e la que mora, por
    exemplo, "a sub-pipeline nao gera JSON", que e a razao da cabeca `nenhum` e
    nao uma contradicao dela.
    """
    cabeca = re.split(r"[:;]", celula.strip(), maxsplit=1)[0].strip().strip("`").lower()
    assert not _NEGACAO_NA_CABECA_RX.search(cabeca), (
        f"cabeca da coluna `_LOOP-CONFIG.json` carrega negacao, e a coluna "
        f"declara o que ACONTECE, nao o que nao acontece: {celula!r}"
    )
    for prefixo, classe in _CABECAS_JSON:
        if cabeca.startswith(prefixo):
            return classe
    raise AssertionError(
        "cabeca da coluna `_LOOP-CONFIG.json` nao abre com nenhuma das "
        f"canonicas {[h for h, _ in _CABECAS_JSON]}: {celula!r}"
    )


def _secao(texto: str, titulo: str) -> str | None:
    m = re.search(
        r"^#+ *" + re.escape(titulo) + r"\s*$(.*?)(?=^#+ |\Z)", texto, re.S | re.M
    )
    return m.group(1) if m else None


def parse_tabela_handoff(texto: str) -> dict[str, tuple[str, str]]:
    """`modo -> (botao, classe do JSON)` lido da TABELA, nao da prosa.

    Levanta `AssertionError` quando a secao nao existe, quando uma linha nao
    tem exatamente tres colunas, quando uma celula de modo ou de botao nao
    contem exatamente um token, ou quando um modo aparece duas vezes.
    """
    secao = _secao(texto, SECAO_HANDOFF)
    assert secao is not None, f"secao `{SECAO_HANDOFF}` ausente"

    linhas = [ln.strip() for ln in secao.splitlines() if ln.strip().startswith("|")]
    linhas = [ln for ln in linhas if not re.fullmatch(r"\|[\s|:-]+\|", ln)]
    assert linhas, f"secao `{SECAO_HANDOFF}` sem tabela"

    out: dict[str, tuple[str, str]] = {}
    for ln in linhas[1:]:  # linha 0 e o cabecalho
        celulas = [c.strip() for c in ln.strip("|").split("|")]
        assert len(celulas) == 3, f"linha com {len(celulas)} colunas (esperado 3): {ln!r}"
        m_modo = _CELULA_MODO_RX.fullmatch(celulas[0].strip())
        assert m_modo, (
            f"celula de modo nao e so o modo entre crases (prosa esconde "
            f"polaridade): {celulas[0]!r}"
        )
        m_botao = _CELULA_BOTAO_RX.fullmatch(celulas[1].strip())
        assert m_botao, (
            f"celula de botao nao e so o testid entre crases (prosa esconde "
            f"polaridade): {celulas[1]!r}"
        )
        modo = m_modo.group(1)
        botoes = [m_botao.group(1)]
        assert modo not in out, f"modo {modo} aparece em duas linhas"
        out[modo] = (botoes[0], _classifica_celula_json(celulas[2]))
    return out


def assert_tabela_handoff_canonica(texto: str, rotulo: str) -> None:
    """Trava a TABELA da persona contra `_CONTRATO_POR_MODO`.

    Cobre as duas regressoes que ja aconteceram de verdade: mandar
    `--cmd-single` para `queue-btn-loop` (operador cai na fila errada) e
    prometer `_LOOP-CONFIG.json` novo nos cinco modos (o proximo leitor espera
    arquivo que, em dois deles, nunca chega).
    """
    tabela = parse_tabela_handoff(texto)
    faltando = sorted(set(_CONTRATO_POR_MODO) - set(tabela))
    sobrando = sorted(set(tabela) - set(_CONTRATO_POR_MODO))
    assert not faltando, f"{rotulo}: tabela nao cobre {faltando}"
    assert not sobrando, f"{rotulo}: tabela inventa modo {sobrando}"
    divergentes = [
        f"  {modo}: tabela={tabela[modo]} contrato={esperado}"
        for modo, esperado in _CONTRATO_POR_MODO.items()
        if tabela[modo] != esperado
    ]
    assert not divergentes, (
        f"{rotulo}: tabela diverge do contrato por modo:\n" + "\n".join(divergentes)
    )


def assert_deriva_a_tabela_sem_copiar(texto: str, rotulo: str) -> None:
    """Trava um LEITOR da tabela (seed 09, literal do catalogo).

    Exige a citacao (persona + nome da secao) e proibe as duas formas de copia
    que ja envelheceram no repo:

    - qualquer `queue-btn-*` no texto -- valor que so a tabela declara;
    - `_LOOP-CONFIG.json` na mesma clausula que um modo -- veredito por modo,
      que e exatamente a terceira coluna.

    A proibicao universal ("voce NAO cria esse JSON") continua permitida: ela
    nao nomeia modo nenhum, porque vale para os cinco.
    """
    assert PERSONA_LOOP_PATH in texto, f"{rotulo}: nao cita `{PERSONA_LOOP_PATH}`"
    assert SECAO_HANDOFF in texto, f"{rotulo}: nao cita a secao `{SECAO_HANDOFF}`"
    assert_sem_revogacao(texto, rotulo, (PERSONA_LOOP_PATH, SECAO_HANDOFF))

    copiados = sorted(set(_BOTAO_RX.findall(texto)))
    assert not copiados, (
        f"{rotulo}: copia valor da tabela em vez de cita-la -- {copiados}. "
        f"O botao de destino e declarado SO na secao `{SECAO_HANDOFF}` de "
        f"`{PERSONA_LOOP_PATH}`; aqui, mande aplicar a tabela ao modo escolhido."
    )

    infratoras = [
        c.strip()[:120]
        for c in re.split(r"[;\n]", texto)
        if "_LOOP-CONFIG" in c and _MODO_NA_CELULA_RX.search(c)
    ]
    assert not infratoras, (
        f"{rotulo}: repete o veredito de `_LOOP-CONFIG.json` por modo, que e a "
        f"terceira coluna da tabela:\n  " + "\n  ".join(infratoras)
    )


# ── Contrato de forma (`BRAINSTORM.md`) vs seus LEITORES ────────────────────
#
# `BRAINSTORM.md:21`: "Esta e a UNICA definicao de forma do artefato. Persona,
# literal de action e validador CITAM este arquivo; nenhum deles redefine
# campo, secao, enum ou regra de preenchimento." A Regra 3 fecha com a ordem
# operacional correspondente: "Persona e literal passam a citar esta regra em
# vez de redeclarar a sua."
#
# O seed 01 e o literal `Criar arquivo` desobedeciam essa ordem exatamente como
# o seed 09 desobedecia a da tabela de handoff: carregavam uma COPIA da Regra 3
# ("fica vazio enquanto o status e draft ... NAO preencha esse campo agora"). A
# copia nao estava errada no dia em que foi escrita -- e esse e o ponto. A
# fronteira da Regra 3 e a saida de `draft`, e ela ja mudou uma vez: foi o
# conflito de duas pontas entre `preencher quando aplicavel` (literal antigo) e
# `sempre vazio` (persona antiga) que obrigou a escrever a Regra 3. Manter duas
# fontes reabre esse mesmo conflito na proxima mudanca.
#
# `criar-md-rules.md` ja fazia certo (cita "**Regra 3**, item 1" em quatro
# pontos e nao repete valor nenhum); este helper cobra o mesmo dos outros dois.

CONTRATO_DE_FORMA_PATH = "ai-forge/templates/mcp-flow/BRAINSTORM.md"

#: Campos cuja regra de preenchimento e declarada por `BRAINSTORM.md`. NOMEAR
#: o campo e citacao legitima -- e assim que um leitor diz de que campo esta
#: falando. Prescrever o VALOR dele e que e redefinicao.
_CAMPOS_DO_CONTRATO_DE_FORMA = (
    "implantation-destiny-path",
    "related-paths",
    "agent-paths",
    "artifact_kind",
    "template_path",
)

#: Vocabulario de VALOR, deliberadamente sem verbo de acao. "preencha X como a
#: Regra 1 declara" e citacao e nao pode ficar vermelho, entao `preench` fica
#: FORA. O que caracteriza copia e afirmar QUAL valor o campo recebe, ou sob
#: QUAL status ele o recebe.
_PRESCRICAO_DE_VALOR_RX = re.compile(
    r"vazi[oa]|obrigatori|\bdraft\b|\bready\b|\[\]|kebab-case|semver|"
    r"brainstorm-note|\bISO\b",
    re.I,
)


def assert_deriva_o_contrato_de_forma_sem_copiar(texto: str, rotulo: str) -> None:
    """Trava um LEITOR do contrato de forma (seed 01, literal `Criar arquivo`).

    Exige a citacao (path do template + o numero da regra) e proibe a unica
    forma de copia que ja envelheceu nesta lane: uma clausula que junte o nome
    de um campo do contrato com a prescricao do valor dele.

    Nao proibe nomear o campo, nao proibe o verbo `preencher` e nao proibe
    falar de `status` em geral: proibir isso empurraria o texto a nao dizer de
    que campo esta tratando, que e o oposto de citar.
    """
    assert CONTRATO_DE_FORMA_PATH in texto, (
        f"{rotulo}: nao cita `{CONTRATO_DE_FORMA_PATH}`"
    )
    assert "Regra 3" in texto, (
        f"{rotulo}: nao nomeia a Regra 3, entao nao ha o que o leitor abra"
    )
    assert_sem_revogacao(texto, rotulo, (CONTRATO_DE_FORMA_PATH, "Regra 3"))

    infratoras = []
    for clausula in re.split(r"[;\n]", texto):
        campos = [c for c in _CAMPOS_DO_CONTRATO_DE_FORMA if c in clausula]
        if not campos:
            continue
        valores = sorted(set(_PRESCRICAO_DE_VALOR_RX.findall(clausula)))
        if valores:
            infratoras.append(f"{campos} <- {valores}: {clausula.strip()[:120]}")
    assert not infratoras, (
        f"{rotulo}: prescreve o valor de um campo cuja regra vive so em "
        f"`{CONTRATO_DE_FORMA_PATH}`. Cite a regra pelo numero e pare ai; a "
        "copia envelhece com a regra e a citacao nao:\n  "
        + "\n  ".join(infratoras)
    )


# ── Frontmatter REAL dos 24 seeds canonicos ─────────────────────────────────
#
# Codex R2 #2: DUAS fixtures diferentes afirmavam materializar "os 24 seeds
# canonicos" e as duas tinham derivado do disco -- uma em tres `action`, em
# `button_type` (24 de 24) e em `target_terminal` (20 de 24); a outra em tres
# `action` e um `target_terminal`. Fixture que descreve um universo que nao
# existe aprova o widget sobre esse universo. Este e o leitor UNICO do
# frontmatter real; quem precisa comparar ou derivar, chama aqui.

_FRONTMATTER_RX = re.compile(r"^\s*---\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.S)

#: Raiz do repo REAL (nao a `tmp_path` de nenhum teste).
REPO_ROOT_REAL = Path(__file__).parents[3].resolve()


def real_seed_frontmatter() -> dict[str, dict[str, Any]]:
    """`{nome_do_arquivo: frontmatter}` dos 24 seeds canonicos em disco."""
    from workflow_app.brainstorm_seed_contract import (
        CANONICAL_SEED_FILENAMES,
        resolve_seed_dir,
    )

    seed_dir = resolve_seed_dir(REPO_ROOT_REAL)
    out: dict[str, dict[str, Any]] = {}
    for nome in CANONICAL_SEED_FILENAMES:
        texto = (seed_dir / nome).read_text(encoding="utf-8")
        m = _FRONTMATTER_RX.match(texto)
        assert m, f"{nome}: frontmatter ausente"
        out[nome] = yaml.safe_load(m.group(1)) or {}
    return out


def assert_fixture_bate_com_os_seeds_reais(
    fixture: dict[str, dict[str, Any]],
    rotulo: str,
    campos: tuple[str, ...] = ("slug", "button_type", "action", "target_terminal"),
) -> None:
    """Reprova quando a fixture diverge do frontmatter real em `campos`.

    `target_path` e comparado a parte porque as fixtures o escrevem como
    string ("true"/"false") para interpolar direto no YAML.
    """
    reais = real_seed_frontmatter()
    assert set(fixture) == set(reais), (
        f"{rotulo}: conjunto de arquivos diverge dos 24 canonicos"
    )
    divergencias = []
    for nome in sorted(fixture):
        real, falso = reais[nome], fixture[nome]
        for campo in campos:
            a, b = str(falso.get(campo)), str(real.get(campo))
            if a != b:
                divergencias.append(f"{nome} {campo}: fixture={a!r} real={b!r}")
        if "target_path" in falso:
            a = str(falso["target_path"]).lower()
            b = str(real.get("target_path")).lower()
            if a != b:
                divergencias.append(f"{nome} target_path: fixture={a!r} real={b!r}")
    assert not divergencias, (
        f"{rotulo} nao descreve os seeds reais:\n  " + "\n  ".join(divergencias)
    )
