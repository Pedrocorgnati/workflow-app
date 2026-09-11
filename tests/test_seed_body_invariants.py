"""As invariantes C1/C6 no texto que o modelo REALMENTE recebe.

Ate o cutover C2c, `ACTION_LITERALS` era o texto despachado e
`test_mcp_prompt_literals_snapshot.py` guardava as invariantes ali -- lugar
certo. Depois do C2c quem vence e o bloco `## Prompt canonico` do seed, e
aquelas invariantes ficaram guardando um dicionario que, para os 24 botoes da
grade, virou fallback: catalogo perfeito, producao errada, suite verde. Nove
seeds carregavam a redacao ANTERIOR as correcoes C1/C6 e nenhum teste ficou
vermelho por isso.

Este arquivo cobra as MESMAS invariantes do corpo dos seeds reais em disco. Ele
NAO substitui o snapshot: o catalogo continua sendo o texto de quem chama
`build_prompt` sem seed, e continua precisando das suas garantias. Os dois
arquivos vigiam as duas fontes, e e de proposito que digam quase a mesma coisa
-- foi a assimetria entre eles que deixou a regressao passar.

Por que texto e nao comportamento: o executor destes prompts e um LLM com
acesso de escrita ao repo. Nao da para assertar em teste que ele obedeceu; da
para assertar que a instrucao que ele recebeu carrega a fronteira, na forma em
que a fronteira foi decidida.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests._helpers import (
    assert_deriva_a_tabela_sem_copiar,
    assert_deriva_o_contrato_de_forma_sem_copiar,
    assert_tabela_handoff_canonica,
)
from workflow_app.agent_integration_specs import brainstorm_agent_specs
from workflow_app.brainstorm_seed_contract import (
    CANONICAL_SEED_COUNT,
    CANONICAL_SEED_FILENAMES,
    extract_action_literal,
    resolve_seed_dir,
    seed_prefix,
    validate_persona_action,
)
from workflow_app.widgets.mcp_prompt_actions import (
    _BRAINSTORM_TEMPLATE_PATH,
    _BRAINSTORM_VALIDATOR_PATH,
    _FILE_OPS_RULES_PATH,
    _PRECEDENCE_CLAUSE,
)

REPO_ROOT = Path(__file__).parents[3].resolve()
_FRONTMATTER_RX = re.compile(r"^\s*---\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.S)

#: Path do contrato da OUTRA lane. Um seed de brainstorm so pode nomea-lo para
#: dizer que ele nao vale aqui -- ver `test_nenhum_seed_manda_seguir_o_starter`.
_STARTER_PATH = "ai-forge/templates/mcp-flow/STARTER.md"

#: Forma com que um corpo declara a PROPRIA action. A variante com espaco
#: (``action `Criar tasks` ``) e referencia a action de OUTRO botao -- o seed 16
#: aponta o canal SIMPLES por nome -- e nao entra nesta regra.
_ACTION_AUTODECLARADA_RX = re.compile(r"action=`([^`]+)`")


def _corpos():
    """(nome, frontmatter, literal) de cada seed canonico, lido do disco."""
    seed_dir = resolve_seed_dir(REPO_ROOT)
    out = []
    for name in CANONICAL_SEED_FILENAMES:
        text = (seed_dir / name).read_text(encoding="utf-8")
        m = _FRONTMATTER_RX.match(text)
        assert m, f"{name}: frontmatter ausente"
        fm = yaml.safe_load(m.group(1)) or {}
        literal = extract_action_literal(text[m.end():])
        assert literal, f"{name}: bloco `## Prompt canonico` ausente ou vazio"
        out.append((name, fm, literal))
    return out


def _corpo_do_seed(nome: str) -> str:
    """O corpo de um seed endereçado por nome de arquivo."""
    achados = [lit for n, _fm, lit in _corpos() if n == nome]
    assert len(achados) == 1, f"{nome}: seed nao encontrado"
    return achados[0]


def _corpo_de(action: str) -> str:
    """O corpo do unico seed que declara `action` no frontmatter.

    Falha alto quando ha zero ou mais de um: um teste que aponta uma action e
    encontra duas nao sabe qual julgou, e um que nao encontra nenhuma passaria
    vazio se o `for` fosse silencioso.
    """
    achados = [lit for _, fm, lit in _corpos() if fm.get("action") == action]
    assert len(achados) == 1, f"{action}: {len(achados)} seeds (esperado 1)"
    return achados[0]


# ── 0. Nao-vacuidade ────────────────────────────────────────────────────────

def test_a_varredura_encontra_os_seeds_reais():
    """Sem isto, todo `for` abaixo passaria verde varrendo lista vazia."""
    corpos = _corpos()
    assert len(corpos) == CANONICAL_SEED_COUNT
    for nome, _fm, literal in corpos:
        assert literal.strip(), nome


# ── 1. Invariantes que valem para TODO seed ─────────────────────────────────

def test_todo_corpo_cita_o_file_ops_rules():
    """Toda action da grade mexe em arquivo, entao todo corpo abre citando.

    Varre a UNIAO (canonicos + suplementos): o corpo do suplemento tambem e
    despachado, e ate 2026-08-26 ele escapava de toda invariante global por
    elas iterarem `CANONICAL_SEED_FILENAMES`.

    Espelha `test_file_ops_rules_cited_by_every_literal` do snapshot. A action
    `Analisar complexidade` deixou de ser a excecao na C6/Task 22, quando ganhou
    escrita no frontmatter -- e o seed dela levou nove dias para acompanhar.
    """
    for nome, _fm, literal in _corpos_incluindo_suplementos():
        assert _FILE_OPS_RULES_PATH in literal, nome


def test_todo_corpo_cita_a_propria_persona():
    """O corpo e autonomo: quem o le precisa achar as regras da persona nele.

    O cabecalho montado pelo renderer ja imprime `agent_path`, mas ele e
    metadado do sistema. A ordem de LER o arquivo de regras tem de estar dentro
    do bloco do botao, senao um seed que perca a linha continua parecendo certo
    no preview do tooltip.
    """
    for nome, fm, literal in _corpos_incluindo_suplementos():
        assert fm["agent_path"] in literal, nome


def test_corpo_nunca_declara_action_diferente_da_do_frontmatter():
    """Gate G7 aplicado ao CORPO, e nao so ao par persona<->action.

    `validate_persona_action` compara `agent_path` com `action` do frontmatter e
    nunca abre o texto. Era por isso que o seed 19 passava verde anunciando
    ``action=`Otimizar` `` sob um botao cuja action e `Delegar`: as duas fontes
    que o gate compara estavam coerentes, e a terceira -- a unica que o modelo
    le -- dizia outra coisa. Divergencia aqui nao e cosmetica: o texto manda
    otimizar o arquivo, o botao roteia como delegacao.
    """
    divergentes = {}
    for nome, fm, literal in _corpos_incluindo_suplementos():
        for declarada in _ACTION_AUTODECLARADA_RX.findall(literal):
            if declarada != fm["action"]:
                divergentes[nome] = (declarada, fm["action"])
    assert not divergentes, (
        "corpo declara action diferente da do frontmatter "
        f"(nome: corpo vs frontmatter): {divergentes}"
    )


def test_nenhum_seed_manda_seguir_o_starter_como_contrato():
    """STARTER.md e o shape de `/mcp:research`, nao o desta lane.

    Cinco seeds mandavam "preservar a estrutura do STARTER.md" e um mandava
    escrever nas secoes 9/10/11 dele -- numeracao que nem no STARTER atual
    existe mais e que a lane brainstorm nunca teve. A unica mencao legitima ao
    STARTER dentro de um seed e a que CONTRASTA os dois contratos, e por isso a
    regra e sobre coocorrencia e nao sobre ausencia: proibir a palavra
    empurraria o seed a nao avisar que existe a outra lane.
    """
    for nome, _fm, literal in _corpos_incluindo_suplementos():
        if _STARTER_PATH in literal or "STARTER.md" in literal:
            assert "nao sao intercambiaveis" in literal, (
                f"{nome}: cita o STARTER sem dizer que ele nao e o contrato "
                "desta lane"
            )


# ── 2. Invariantes por action (as mesmas do snapshot do catalogo) ───────────

def test_criar_arquivo_cita_o_contrato_de_forma_e_o_validador():
    """C1: o corpo CITA o template; nao redeclara campo, secao nem enum.

    O seed 01 redeclarava a mao a convencao de nome, a regra de colisao e o
    status inicial, e apontava o template errado. Redeclarar e pior que apontar
    errado: quando o template mudar, a copia no seed nao muda junto e ninguem
    fica sabendo.

    A versao anterior deste teste so cobrava PRESENCA de dois paths e de uma
    frase, entao ela aprovava a ultima copia que tinha sobrado: a Regra 3
    inteira, parafraseada dentro do parenteses ("fica vazio enquanto o status e
    draft ... NAO preencha esse campo agora"). Presenca do template nao prova
    que o texto parou de redefini-lo -- prova so que ele o cita ANTES de
    redefinir.
    """
    literal = _corpo_de("Criar arquivo")
    assert_deriva_o_contrato_de_forma_sem_copiar(
        literal, "corpo do seed 01-criar-md.md"
    )
    assert _BRAINSTORM_VALIDATOR_PATH in literal, (
        "sem o validador o trabalho termina sem prova de que a forma bateu"
    )
    assert "exit code 0" in literal


def test_loop_prepare_deriva_a_tabela_em_vez_de_copiar():
    """C6/Task 21 + Codex F9 #1 + Codex R3 s3: o corpo CITA, nao redefine.

    Historico das duas falhas que este teste fecha, nesta ordem:

    1. O corpo copiava o mapa e a copia envelheceu: dizia `queue-btn-loop`
       para os cinco modos, mandando `--cmd-single` e `--rocksmash` para a
       fila errada, e prometia `_LOOP-CONFIG.json` novo nos cinco quando dois
       deles nunca produzem um.
    2. A correcao anterior manteve a copia e passou a conferi-la aqui. Isso
       institucionaliza a duplicacao que `BRAINSTORM.md:21` proibe: duas
       fontes escrevendo o mesmo mapa envelhecem de novo, so que agora com um
       teste verde por cima.

    Agora a tabela mora SO na persona (`assert_tabela_handoff_canonica` a
    julga) e o corpo do seed responde apenas por deriva-la.
    """
    literal = _corpo_de("Loop prepare")
    assert_deriva_a_tabela_sem_copiar(literal, "corpo do seed 09-loop-prepare.md")
    assert "loop-source" in literal, "a conversao de frontmatter tem perfil"


def test_analisar_complexidade_persiste_o_veredito_no_namespace():
    """C6/Task 22: a action deixou de ser read-only, mas nao virou escritora.

    O seed 16 mantinha a redacao read-only INTEIRA ("SOMENTE LEITURA", "nenhum
    arquivo e criado, editado ou anexado") enquanto o contrato ja exigia gravar
    `brainstorm_complexity`. Nao era instrucao incompleta: era a instrucao
    contraria, e o modelo obedeceria a ela.
    """
    literal = _corpo_de("Analisar complexidade")
    assert "brainstorm_complexity" in literal
    assert _BRAINSTORM_TEMPLATE_PATH in literal, "a forma do bloco mora no template"
    for campo in ("assessed_at", "verdict", "suggested_loop_mode"):
        assert campo in literal, campo

    linhas = [ln.strip().lstrip("- ").strip() for ln in literal.splitlines()]
    proibicao = [ln for ln in linhas if ln.startswith("Proibido: alterar qualquer coisa")]
    assert len(proibicao) == 1, f"proibicao nao esta em linha propria: {linhas}"
    for alvo in ("brainstorm_complexity", "frontmatter", "corpo", "arquivo"):
        assert alvo in proibicao[0], alvo

    assert "SOMENTE LEITURA" not in literal, (
        "ordem contraditoria: o corpo grava uma chave no frontmatter"
    )
    assert "nenhum arquivo e criado" not in literal


def test_delegar_deriva_os_dois_destinos_do_proprio_arquivo():
    """O payload do botao nao carrega tasklist alvo; o corpo resolve isso."""
    literal = _corpo_de("Delegar")
    assert "PROGRESS-" in literal
    assert "-tasks.md" in literal
    assert "nao carrega um path de tasklist separado" in literal


def test_atualizar_catalogos_restringe_destino_e_poupa_a_fonte():
    """A restricao e de DESTINO, e o `.md` aberto e fonte, nunca destino.

    O seed 22 fechava mandando "atualizar o arquivo selecionado in-place" -- o
    unico path que este botao nao pode tocar.
    """
    literal = _corpo_de("Atualizar scaffolds e blueprints")
    assert "ai-forge/scaffolds/" in literal
    assert "ai-forge/blueprints/" in literal
    assert "DESTINO e nao de volume" in literal
    assert "Proibido: reescrever este arquivo fonte" in literal


@pytest.mark.parametrize("secao", ["9 (Riscos", "10 (Criterios", "11 (Notas"])
def test_hardening_nao_importa_numeracao_de_secao_de_outro_template(secao):
    """Numeracao emprestada envelhece calada.

    O seed 08 mandava escrever nas secoes 9/10/11 "do STARTER.md". No STARTER
    atual essas secoes sao 11/12/13, e a lane brainstorm nao numera secao
    nenhuma (Regra 5). O endereco estava objetivamente errado nas duas leituras
    possiveis.
    """
    # Endereca pelo NOME do arquivo, e nao por `_corpo_de`: a action deste seed
    # e `Otimizar`, compartilhada por dez seeds, e a invariante e so deste.
    literal = _corpo_do_seed("08-hardening.md")
    assert secao not in literal


# ── 3. Fronteira entre o que o app decide e o que o modelo decide ───────────

#: Corpos fora da cardinalidade canonica. Entram nas invariantes de CORPO
#: porque o corpo deles tambem e despachado (`_read_action_literal` em
#: `main_window.py`), embora fiquem fora de toda varredura que itera
#: `CANONICAL_SEED_FILENAMES` -- que e exatamente por que regressao aqui
#: sobrevive mais tempo.
#:
#: DERIVADO do registro Python, nunca escrito a mao. A lista literal que estava
#: aqui era um SEGUNDO registro: registrar uma spec suplementar e um ato em
#: `agent_integration_specs._BRAINSTORM_AGENT_SPECS`, e nada obrigava quem
#: registra a lembrar deste arquivo. A spec nasceria com botao na grade e ZERO
#: invariante de corpo -- sem fronteira de escrita, sem checagem de path
#: citado, sem nada -- e a suite ficaria verde. E o mesmo buraco que
#: `test_a_descoberta_em_disco_nao_traz_corpo_fora_do_registro` fechou para os
#: seeds numerados em disco, do outro lado: la a descoberta e no filesystem,
#: aqui e em Python.
_SUPLEMENTOS = tuple(spec.prompt_path for spec in brainstorm_agent_specs())


def _corpos_incluindo_suplementos():
    """(nome, frontmatter, literal) de TODO corpo que producao despacha.

    Mesmo shape de `_corpos()` de proposito: as invariantes globais consomem
    esta, nao aquela. `_corpos()` sobrevive so para as invariantes que sao
    especificas de um seed canonico numerado.

    O nome do suplemento e o proprio `prompt_path` repo-relativo da spec, e a
    leitura sai de `REPO_ROOT` -- nao de `resolve_seed_dir()`. Uma spec pode
    apontar para fora de `seeds/`; ancorar em `seed_dir` faria ela sumir da
    varredura em silencio em vez de ser lida.
    """
    out = list(_corpos())
    for rel in _SUPLEMENTOS:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        m = _FRONTMATTER_RX.match(text)
        assert m, f"{rel}: frontmatter ausente"
        frontmatter = yaml.safe_load(m.group(1)) or {}
        literal = extract_action_literal(text[m.end():])
        assert literal, f"{rel}: bloco `## Prompt canonico` ausente ou vazio"
        out.append((rel, frontmatter, literal))
    return out


def test_todo_suplemento_registrado_entra_nas_invariantes_de_corpo():
    """A varredura global cobre EXATAMENTE o registro Python, sem sobra nem falta.

    `_SUPLEMENTOS` derivar do registro torna a igualdade trivial -- e esse e o
    ponto: o teste existe para que a derivacao nao possa ser desfeita em
    silencio. Quem trocar a expressao derivada por uma lista literal de novo
    fica vermelho aqui no primeiro registro que divergir.

    A parte NAO trivial e a segunda metade: cada `prompt_path` registrado tem
    de existir em disco e ter corpo extraivel. O registro valida a FORMA do
    path (`validate_repo_relative_md`), nunca a existencia -- o modulo nao toca
    filesystem de proposito. Sem esta checagem, uma spec apontando para um
    arquivo renomeado so falharia no clique do operador.
    """
    registrados = tuple(spec.prompt_path for spec in brainstorm_agent_specs())
    assert _SUPLEMENTOS == registrados, (
        "a varredura de suplementos divergiu do registro Python.\n"
        f"  varridos: {list(_SUPLEMENTOS)}\n"
        f"  registrados: {list(registrados)}"
    )

    canonicos = set(CANONICAL_SEED_FILENAMES)
    nomes = [n for n, _fm, _lit in _corpos_incluindo_suplementos()]
    assert [n for n in nomes if n not in canonicos] == list(registrados), (
        f"corpos suplementares lidos: {[n for n in nomes if n not in canonicos]}"
    )

    for rel in registrados:
        alvo = REPO_ROOT / rel
        assert alvo.is_file(), (
            f"spec suplementar registrada aponta para arquivo inexistente: "
            f"{rel} (o registro valida a forma do path, nunca a existencia)"
        )


def test_nenhum_corpo_manda_abortar_por_provider():
    """Roteamento de terminal e decisao do app, nunca do modelo.

    Cinco corpos mandavam: "Se radio=Codex e T3 ainda nao validado, abortar com
    mensagem explicita." Isso nao era so instrucao morta (o modelo nao observa
    nem o radio nem o T3) -- era o INVERSO do comportamento real. Os cinco sao
    `button_type: type-selector-radio-input`, e
    `widgets/mcp_prompt_button.py::MCPPromptButton._on_clicked` so bloqueia
    quando `self._button_type == "Codex"` (tipo FIXO); para radio-input a regra
    de 2026-05-23 e literal: "NAO bloquear quando Codex/T3 estiver
    indisponivel. O roteamento central em MainWindow faz fallback automatico
    T3->T2."

    Um modelo obediente abortaria justamente o caso que o app decidiu deixar
    passar -- e abortaria alegando um estado que nao tem como ter observado.
    """
    for nome, _fm, literal in _corpos_incluindo_suplementos():
        assert "radio=Codex" not in literal, (
            f"{nome}: corpo condiciona o trabalho ao provider; quem roteia e o "
            f"app no clique"
        )
        assert "T3 ainda nao validado" not in literal, nome


def test_a_clausula_de_precedencia_nao_diverge_da_persona():
    """Duas copias fisicas da MESMA ordem, obrigadas a concordar.

    `_PRECEDENCE_CLAUSE` (injetada nos templates) e o bloco "Contrato de uso"
    de `brainstorm-file-ops-rules.md` (lido pelo modelo em runtime) declaram a
    mesma precedencia. Nao da para deduplicar: uma e string Python, a outra e
    arquivo que a persona abre. Da para proibir que divirjam em silencio.
    """
    regras = (REPO_ROOT / _FILE_OPS_RULES_PATH).read_text(encoding="utf-8")
    ordem = ["operador", "sistema", "este arquivo", "comportamento do agente"]

    # A clausula da persona quebra em duas linhas de markdown. Achatar antes de
    # medir ordem: senao o teste depende de onde caiu o wrap, que nao e
    # contrato de nada.
    achatado = " ".join(regras.split())
    marca = "instrucoes do operador"
    inicio = achatado.find(marca)
    assert inicio >= 0, f"{_FILE_OPS_RULES_PATH}: clausula de precedencia sumiu"
    trecho = achatado[inicio : inicio + 200]
    posicoes = [trecho.find(t) for t in ordem]
    assert all(p >= 0 for p in posicoes), (trecho, posicoes)
    assert posicoes == sorted(posicoes), (
        f"{_FILE_OPS_RULES_PATH}: ordem de precedencia divergiu de "
        f"_PRECEDENCE_CLAUSE"
    )

    # No lado Python a mesma sequencia, com "este arquivo" escrito por path.
    # Medir a partir de "instrucoes do operador", e nao do inicio da string: o
    # preambulo da clausula ja cita `_FILE_OPS_RULES_PATH` uma vez ("identica a
    # declarada em ..."), e um `.find` ingenuo acharia essa mencao em vez do
    # elo da cadeia.
    achatado_py = " ".join(_PRECEDENCE_CLAUSE.split())
    inicio_py = achatado_py.find(marca)
    assert inicio_py >= 0, "_PRECEDENCE_CLAUSE: cadeia de precedencia sumiu"
    cadeia_py = achatado_py[inicio_py:]
    ordem_py = ["operador", "sistema", _FILE_OPS_RULES_PATH, "comportamento do agente"]
    pos_py = [cadeia_py.find(t) for t in ordem_py]
    assert all(p >= 0 for p in pos_py), (cadeia_py, pos_py)
    assert pos_py == sorted(pos_py), "_PRECEDENCE_CLAUSE fora de ordem"


def test_o_par_persona_action_do_suplemento_real_e_coerente():
    """G7 sobre os suplementos, cobrado aqui porque nao e cobrado em runtime.

    A grade aplica G6 (existencia da persona) a suplementos desde 2026-08-26,
    mas NAO G7 (coerencia do par persona-action) -- decisao registrada no
    docstring de `_check_supplemental_agent_path`: para os canonicos G7 existe
    porque o gear edita persona e action em campos separados do mesmo arquivo
    e nada impede salvar um par contraditorio; a spec suplementar nasce em
    Python e ligar G7 la tem blast radius proprio.

    Deixar de cobrar em runtime nao e deixar de cobrar. Aqui o par de CADA
    suplemento real e medido pelo mesmo validador dos canonicos, contra o
    disco.

    HONESTIDADE SOBRE O ALCANCE: hoje o unico suplemento aponta para
    `search-prod.md`, persona FORA de `PERSONA_ACTION_COHERENCE`, e o
    validador se abstem sobre persona desconhecida -- por design, documentado
    no proprio `validate_persona_action`. Para o registry corrente este laco
    portanto nao pode ficar vermelho. Ele e tripwire de suplemento FUTURO que
    aponte para persona conhecida, e por isso vem com controle positivo:
    sem ele, um dia em que G7 fosse neutralizado por inteiro passaria daqui
    sem ruido.
    """
    from workflow_app.agent_integration_specs import brainstorm_agent_specs

    specs = brainstorm_agent_specs()
    assert specs, "registry suplementar vazio: este teste virou no-op"

    for spec in specs:
        incoerencia = validate_persona_action(spec.agent_path, spec.action)
        assert incoerencia is None, f"{spec.slug}: G7 violado: {incoerencia}"

    # Controle positivo: o validador ainda REPROVA um par conhecido-incoerente.
    # Se isto virar None, o laco acima passou a ser decorativo.
    controle = validate_persona_action(
        "ai-forge/MCP/agents/hardening-engineer-rules.md", "Revisar"
    )
    assert controle is not None, (
        "validate_persona_action parou de reprovar par conhecido-incoerente: "
        "o laco de suplementos acima virou decorativo"
    )


def test_a_persona_de_cada_suplemento_real_existe_em_disco():
    """G6 medido contra o repo real, nao contra `tmp_path`.

    `test_suplemento_com_persona_inexistente_degrada` prova que o gate
    DEGRADA quando o arquivo falta. Este prova que hoje ele nao falta -- sem
    ele, apagar `search-prod.md` do repo sumiria com o botao em producao e a
    suite seguiria verde, porque degradacao limpa e justamente o que a outra
    suite espera ver.
    """
    from workflow_app.agent_integration_specs import brainstorm_agent_specs

    for spec in brainstorm_agent_specs():
        alvo = REPO_ROOT / spec.agent_path
        assert alvo.is_file(), f"{spec.slug}: agent_path inexistente: {alvo}"
        corpo = REPO_ROOT / spec.prompt_path
        assert corpo.is_file(), f"{spec.slug}: prompt_path inexistente: {corpo}"


#: H2 que o contrato de forma da lane declara para o CORPO de uma
#: `brainstorm-note` (`ai-forge/templates/mcp-flow/BRAINSTORM.md`, Regra 5).
#: Enumerado aqui por ser ASSERCAO de teste, nao instrucao de prompt: a
#: proibicao de redefinir secao (BRAINSTORM.md:21) fala de persona, literal e
#: validador -- os tres que o modelo le. Um teste que checa conformidade
#: precisa nomear o conjunto contra o qual checa.
_H2_DO_CORPO = (
    "## Objetivo",
    "## Escopo incluido",
    "## Escopo excluido",
    "## Hipoteses",
    "## Criterios de aceite",
    "## Notas",
)

#: Seeds cujo destino de escrita NAO e o corpo da brainstorm-note. Eles
#: nomeiam H2 de outro contrato legitimamente e ficam fora da regra acima:
#: 10..13 escrevem em `<stem>-tasks.md` (contrato da lane de tasks) e 16
#: IMPRIME `## Veredito de roteamento` no terminal, gravando so frontmatter.
_ESCREVEM_FORA_DO_CORPO = frozenset(
    {
        "10-criar-task.md",
        "11-revisar-task.md",
        "12-executar-task.md",
        "13-revisar-execucao.md",
        "16-analise-complexidade.md",
    }
)

_H2_CITADA_RX = re.compile(r"`(## [^`]+)`")


def test_nenhum_corpo_manda_criar_h2_fora_do_contrato_de_forma():
    """Regra 5 fixa o conjunto de H2; corpo que inventa secao invalida a nota.

    Catorze corpos mandavam criar H2 propria -- `## Evidencias locais`,
    `## Fontes externas`, `## Ativos do motor`, `## Revisao adversarial`,
    `## Diagnostico Debugger`, `## Ciclo PDCA` e assim por diante. Cada uma
    delas produz um arquivo que o validador da lane reprova, escrito por um
    modelo que obedeceu ao prompt: o defeito nao e do executor, e do texto.

    O seed 08 ja carregava a forma certa e serviu de molde: nomear o DESTINO
    do proprio output dentro do conjunto que o contrato declara, apontando a
    Regra 5, e deixar explicito que noutro shape valem as secoes daquele
    arquivo. Citar, nunca copiar o conjunto.
    """
    for nome, _fm, literal in _corpos_incluindo_suplementos():
        if nome in _ESCREVEM_FORA_DO_CORPO:
            continue
        for h2 in _H2_CITADA_RX.findall(literal):
            assert h2 in _H2_DO_CORPO, (
                f"{nome}: manda usar {h2}, fora das H2 que "
                f"{_BRAINSTORM_TEMPLATE_PATH} Regra 5 declara"
            )


def test_o_suplemento_nao_produz_segundo_arquivo_sob_action_de_arquivo():
    """`Otimizar` + target_path confina a escrita ao arquivo selecionado.

    O suplemento mandava registrar credencial ausente em
    `pending-actions/<slug>.md`. `pending-actions/{slug}.md` e convencao real
    do repo, mas quem a produz sao comandos de pipeline -- nao um botao cuja
    action promete "melhore este mesmo arquivo". Sob essa action o segundo
    arquivo e escrita fora do alvo declarado.
    """
    for nome, _fm, literal in _corpos_incluindo_suplementos():
        assert "pending-actions" not in literal, (
            f"{nome}: manda criar um segundo arquivo sob action que confina a "
            f"escrita ao arquivo selecionado"
        )


# ── 4. A persona citada pelo seed diz o MESMO que o seed ────────────────────
#
# Codex R2 #1: a tabela por modo entrou correta em `loop-preparer-rules.md`,
# mas treze regras ANTIGAS do mesmo arquivo continuavam mandando escrever
# `queue-btn-loop` e prometendo `_LOOP-CONFIG.json` sem condicionar ao modo.
# Persona e seed sao lidos pelo MESMO modelo na MESMA execucao: um arquivo
# coerente consigo mesmo e incoerente com o outro nao vale nada.

_PERSONA_LOOP = "ai-forge/MCP/agents/loop-preparer-rules.md"

#: Titulo da secao que e a fonte unica do botao de destino nessa persona.
_SECAO_HANDOFF = "Handoff condicional por modo"

#: Marcador do slot a preencher no preparo. Literal, porque e ele que o
#: preparador procura no template para saber que aquela celula e variavel.
_MARCADOR_SLOT = "{copiar aqui, literal, a terceira coluna"

_SECAO_RX = re.compile(
    r"^#+ *" + re.escape(_SECAO_HANDOFF) + r"\s*$(.*?)(?=^#+ |\Z)", re.S | re.M
)


def _persona_loop_texto() -> str:
    return (REPO_ROOT / _PERSONA_LOOP).read_text(encoding="utf-8")


def test_a_persona_do_loop_carrega_a_tabela_e_ela_fecha_o_contrato():
    """A secao de handoff da persona sustenta as MESMAS cinco linhas do seed.

    O seed e a persona chegam juntos ao modelo. Cobrar o contrato so no corpo
    do seed deixava a persona livre para dizer outra coisa -- e ela dizia.
    """
    texto = _persona_loop_texto()
    m = _SECAO_RX.search(texto)
    assert m, f"{_PERSONA_LOOP}: secao `{_SECAO_HANDOFF}` ausente"
    assert_tabela_handoff_canonica(
        texto, f"{_PERSONA_LOOP} secao `{_SECAO_HANDOFF}`"
    )
    assert m.group(1).strip(), "secao vazia"


def test_a_persona_nao_reenumera_os_modos_junto_com_o_json_fora_da_tabela():
    """A secao de handoff dizia ser fonte unica e nao era.

    A afirmacao valia para a coluna do BOTAO. A terceira coluna
    (`_LOOP-CONFIG.json`) estava reproduzida por extenso em outras cinco
    passagens da persona -- identidade, Passo 2, o template do intent lock, o
    bloco de handoff do documento produzido e o checklist de aceite. Cinco
    copias de uma regra de cinco linhas, cada uma envelhecendo por conta
    propria: mudar a celula de `--rocksmash` na tabela deixava as outras cinco
    prometendo o contrario, e nenhum teste ficava vermelho.

    A regra estrutural, e nao semantica: fora da secao da tabela, nenhum
    paragrafo pode enumerar tres ou mais dos cinco modos JUNTO com
    `_LOOP-CONFIG`. Citar um modo, ou listar os cinco sem falar do JSON
    (identidade faz isso, para dizer quais existem), continua livre -- o que a
    regra proibe e a forma da copia, que e a enumeracao por modo do valor que
    a tabela ja carrega.

    O paragrafo imediatamente abaixo da tabela e excecao deliberada: ele
    explica POR QUE a coluna existe, e fica dentro da propria secao, onde nao
    tem como divergir sem que quem edita veja as duas.
    """
    texto = _persona_loop_texto()
    i = texto.find(f"## {_SECAO_HANDOFF}")
    assert i >= 0, f"{_PERSONA_LOOP}: secao `{_SECAO_HANDOFF}` ausente"
    fim = texto.find("\n## ", i + 1)
    fora = texto[:i] + (texto[fim:] if fim > 0 else "")

    copias = []
    for par in fora.split("\n\n"):
        if "_LOOP-CONFIG" not in par:
            continue
        modos = [m for m in ("`--task`", "`--cmd`", "`--both`", "`--cmd-single`",
                             "`--rocksmash`") if m in par]
        if len(modos) >= 3:
            copias.append(f"  {modos} -> {' '.join(par.split())[:120]}")
    assert not copias, (
        f"{_PERSONA_LOOP}: paragrafo fora da secao `{_SECAO_HANDOFF}` reenumera "
        f"o handoff de JSON por modo, virando copia da terceira coluna:\n"
        + "\n".join(copias)
        + "\nAponte para a tabela (texto que instrui a persona) ou deixe um slot "
        "a preencher com a celula do modo escolhido (texto que vai para o "
        "documento produzido)."
    )


def test_o_template_copiado_nao_crava_produtor_de_loop_config():
    """Dentro do que e COPIADO para o documento, o produtor do JSON e slot.

    A tabela por modo resolveu o texto que INSTRUI a persona; ela nao alcanca
    o texto que a persona COPIA. Os blocos ```markdown desta persona sao o
    documento produzido, e la dentro estava escrito, em forma fixa,
    ``gera_loop_config_aqui: false  # o /loop gera ao ser rodado pelo
    operador`` -- verdade em `--task`, `--cmd` e `--both`, falsa nos outros
    dois, onde JSON novo nao nasce em fase nenhuma. O documento produzido
    viaja sozinho: quem o le depois nao tem a tabela na frente para descobrir
    que aquela linha nao valia para o modo dele.

    O gate anti-copia irmao (`test_a_persona_nao_reenumera_os_modos_junto_com_
    o_json_fora_da_tabela`) nao pega esta classe por construcao: ele exige
    tres modos nomeados no paragrafo, e a afirmacao universal nao nomeia
    nenhum. Copia parcial e copia; afirmacao universal e pior, porque nao tem
    nem a linha errada para consertar.

    Estrutural: dentro de fence, o BLOCO (trecho entre linhas em branco) que
    fala de `_LOOP-CONFIG` ou de `gera_loop_config_aqui` tem de carregar o
    marcador de slot. Nao ha julgamento de prosa aqui.

    Granularidade de bloco e nao de linha porque a afirmacao se quebra em duas
    linhas no blockquote do intent lock: uma diz que a persona nao gera, a
    seguinte abre o slot do produtor. Cobrar linha a linha reprovaria a metade
    que ja esta certa.
    """
    texto = _persona_loop_texto()
    dentro = False
    faltando: list[str] = []
    bloco: list[tuple[int, str]] = []

    def _fecha() -> None:
        if not bloco:
            return
        corpo = "\n".join(linha for _n, linha in bloco)
        if "_LOOP-CONFIG" in corpo or "gera_loop_config_aqui" in corpo:
            if _MARCADOR_SLOT not in corpo:
                faltando.append(
                    f"  linha {bloco[0][0]}: {' '.join(corpo.split())[:120]}"
                )
        bloco.clear()

    for n, linha in enumerate(texto.splitlines(), 1):
        if linha.startswith("```"):
            _fecha()
            dentro = not dentro
            continue
        if not dentro:
            continue
        if not linha.strip():
            _fecha()
            continue
        bloco.append((n, linha))
    _fecha()

    assert not faltando, (
        f"{_PERSONA_LOOP}: bloco copiado para o documento afirma produtor de "
        f"`_LOOP-CONFIG.json` em forma fixa, valida so em tres dos cinco "
        f"modos:\n" + "\n".join(faltando) + f"\nUse o slot {_MARCADOR_SLOT!r} "
        "para que a celula do modo escolhido seja copiada na hora do preparo."
    )


def test_a_persona_nao_crava_botao_fixo_fora_da_tabela():
    """Fora da tabela, nomear UM botao so vale citando a condicao de modo.

    Era o bug: `Voce nao e o executor do loop... clicar no botao
    queue-btn-loop`, `pronto para ser selecionado no queue-btn-loop`,
    `queue-btn-loop expande as fases` e mais dez linhas mandavam o preparo de
    um `--cmd-single` para a fila errada, contradizendo a tabela logo abaixo.
    """
    texto = _persona_loop_texto()
    m = _SECAO_RX.search(texto)
    assert m, f"{_PERSONA_LOOP}: secao `{_SECAO_HANDOFF}` ausente"
    secao = m.group(1)

    outros_botoes = ("queue-btn-cmd-single", "queue-btn-rocksmash")
    marcas_de_condicao = ("--cmd-single", "--rocksmash", _SECAO_HANDOFF, "condicional")

    infratoras = []
    for numero, linha in enumerate(texto.splitlines(), 1):
        if "queue-btn-loop" not in linha:
            continue
        if linha in secao:  # a tabela e o paragrafo que a explica
            continue
        if any(b in linha for b in outros_botoes):  # enumera os tres
            continue
        if any(marca in linha for marca in marcas_de_condicao):
            continue
        infratoras.append(f"{_PERSONA_LOOP}:{numero}: {linha.strip()[:110]}")

    assert not infratoras, (
        "linha nomeia `queue-btn-loop` como destino sem condicionar ao modo, "
        "contradizendo a tabela `" + _SECAO_HANDOFF + "`:\n  "
        + "\n  ".join(infratoras)
    )


#: Documentos que CITAM o preparador de loop sem serem donos do mapa
#: `modo -> botao -> _LOOP-CONFIG.json`. Todos os quatro ja afirmaram
#: `queue-btn-loop` como destino unico (Codex R1, 2026-08-26): o INDEX
#: descrevia a persona por esse botao, a MATRIX recortava o escopo dela por
#: ele, o CHANGELOG registrava a criacao com ele e o roteador de complexidade
#: mandava o documento para ele. A tabela mudou em C6/Task 21 e os quatro
#: ficaram para tras -- que e o modo de falhar de toda copia.
_LEITORES_DA_TABELA = (
    "ai-forge/MCP/agents/INDEX.md",
    "ai-forge/MCP/agents/CHANGELOG.md",
    "ai-forge/MCP/agents/compositions/MATRIX.md",
    "ai-forge/MCP/agents/complexity-router-rules.md",
)

#: Uma linha pode nomear `queue-btn-loop` desde que diga, na propria linha,
#: que o destino depende do modo. Nomear os outros dois botoes tambem vale:
#: quem enumera os tres nao esta afirmando um destino unico.
_MARCAS_DE_CONDICAO = (
    "--cmd-single",
    "--rocksmash",
    _SECAO_HANDOFF,
    "condicional",
    "CONDICIONAL",
    "queue-btn-cmd-single",
    "queue-btn-rocksmash",
)

#: Como um documento se refere ao preparador. Sem isto o teste reprovaria a
#: `ai-forge/rules/loop-rules.md` inteira, que fala do botao ENQUANTO botao
#: (`queue-btn-loop` expande a cadeia de fases) e nao como destino de persona.
_MENCOES_AO_PREPARADOR = ("loop-preparer", "loop-prepare", "Loop prepare")


def test_o_template_de_forma_nao_reproduz_a_tabela_de_handoff():
    """`BRAINSTORM.md` e dono da FORMA do artefato, nao do destino de fila.

    A Regra 4 item 5 dizia, por extenso, que `--task`/`--cmd`/`--both` geram
    JSON novo "pela pipeline de preparo disparada em `queue-btn-loop`" -- e na
    frase seguinte declarava que a tabela "nao e reproduzida aqui". Era
    reproduzida: faltava so a coluna do meio dos outros dois modos. O proprio
    `BRAINSTORM.md:21` diz que persona, literal e validador CITAM este arquivo
    e nenhum deles o redefine; a reciproca vale, e este teste e a reciproca.
    """
    alvo = REPO_ROOT / _BRAINSTORM_TEMPLATE_PATH
    assert alvo.exists(), f"{_BRAINSTORM_TEMPLATE_PATH} nao existe"
    assert_deriva_a_tabela_sem_copiar(
        alvo.read_text(encoding="utf-8"), _BRAINSTORM_TEMPLATE_PATH
    )


@pytest.mark.parametrize("rel", _LEITORES_DA_TABELA)
def test_catalogo_nao_crava_botao_fixo_para_o_preparador(rel: str):
    """Catalogo que cita o preparador nao pode cravar UM botao de destino.

    Diferente do `BRAINSTORM.md`, estes arquivos tem motivo legitimo para
    escrever `queue-btn-loop` (ele existe, e um botao real e aparece em
    contextos que nada tem a ver com a persona). O que nao podem e ligar o
    botao ao preparador sem dizer, na mesma linha, que o destino depende do
    modo -- foi assim que os quatro passaram a mandar `--cmd-single` e
    `--rocksmash` para a fila errada enquanto a persona ja dizia o contrario.
    """
    alvo = REPO_ROOT / rel
    assert alvo.exists(), f"{rel} nao existe"
    texto = alvo.read_text(encoding="utf-8")

    infratoras = [
        f"{rel}:{numero}: {linha.strip()[:110]}"
        for numero, linha in enumerate(texto.splitlines(), 1)
        if "queue-btn-loop" in linha
        and any(m in linha for m in _MENCOES_AO_PREPARADOR)
        and not any(m in linha for m in _MARCAS_DE_CONDICAO)
    ]

    assert not infratoras, (
        "linha liga `queue-btn-loop` ao preparador sem condicionar ao modo. "
        f"O mapa vive so em `{_PERSONA_LOOP}` secao `{_SECAO_HANDOFF}`; aqui, "
        "cite a condicao ou a secao:\n  " + "\n  ".join(infratoras)
    )



#: Todo path de repo que um corpo de seed cita entre crases, por seed.
#:
#: Este e o snapshot que o Codex pediu na R3 s4, mas NAO na forma que ele
#: prescreveu (`sha256` + tamanho do corpo). O motivo esta em disco:
#: `blacksmith/` inteiro e gitignored (`.gitignore:171`) e
#: `git ls-files blacksmith/brainstorm-mcp/` devolve zero, entao os 24 corpos
#: reais nao tem historico; e o modal da engrenagem
#: (`brainstorm_mcp_config_dialog.py`, campo `brainstorm-mcp-config-prompt`)
#: EDITA corpo, nao so frontmatter. Um snapshot de bytes ficaria vermelho a
#: cada edicao legitima do operador, sem um diff de VCS para explicar o que
#: mudou -- o teste viraria ruido e seria desligado, que e a pior forma de
#: fechar um buraco.
#:
#: O conjunto de paths citados nao tem esse problema: e independente de
#: redacao (reescrever a prosa nao o move) e e a superficie que importa em
#: seguranca, porque e a lista de arquivos que um modelo com acesso total ao
#: disco recebe ordem de abrir. As duas direcoes sao evento: um path a mais e
#: um arquivo novo que o modelo passa a ler; um path a menos e uma regra que
#: ele parou de ler. Nas duas o teste exige decisao explicita.
EXPECTED_SEED_PATH_CITATIONS: dict[str, tuple[str, ...]] = {
    "01-criar-md.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/criar-md-rules.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
        "ai-forge/templates/mcp-flow/STARTER.md",
    ),
    "02-pesquisar.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/search-in-rules.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "03-search-out.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/search-out-rules.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "04-search-forge.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/search-forge-rules.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "05-deep-detailer.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/deep-detailer.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "06-controversial.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/controversial-devils-advocate-rules.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "07-questioner.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/questioner-rules.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "08-hardening.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/hardening-engineer-rules.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "09-loop-prepare.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/loop-preparer-rules.md",
        "ai-forge/rules/loop-rules.md",
        "ai-forge/rules/workflow-app-command-lists.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "10-criar-task.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/criar-task-rules.md",
    ),
    "11-revisar-task.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/revisar-task-rules.md",
    ),
    "12-executar-task.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/executar-task-rules.md",
    ),
    "13-revisar-execucao.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/revisar-execucao-rules.md",
    ),
    "14-visual-design.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/specific-reviewer.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "15-layout-architect.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/layout-architect-rules.md",
        "ai-forge/component-kit/INDEX.md",
        "ai-forge/scaffolds/INDEX.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "16-analise-complexidade.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/complexity-router-rules.md",
        "ai-forge/MCP/agents/loop-preparer-rules.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "17-billing.md": (
        "ai-forge/MCP/agents/billing-scpecialist.md",
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "18-debugger.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/code-debugger.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "19-delegador.md": (
        "ai-forge/MCP/agents/analista-delegador-rules.md",
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
    ),
    "20-pdca.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/orquestrador-pdca-rules.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "21-soft-engen.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/soft-engineer.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "22-scaffolds-blueprints-updater.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/scaffolds-blueprints-updater.md",
    ),
    "23-ux-ui.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/ux-ui-specialist.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
    "24-performance-engineer.md": (
        "ai-forge/MCP/agents/brainstorm-file-ops-rules.md",
        "ai-forge/MCP/agents/performance-engineer.md",
        "ai-forge/templates/mcp-flow/BRAINSTORM.md",
    ),
}

#: Path de repo entre crases: comeca com nome de arquivo/pasta e tem ao menos
#: uma barra. Aceita `{...}` e `*` porque seeds citam alvos parametrizados.
_CITACAO_DE_PATH_RX = re.compile(
    r"`([A-Za-z0-9_][A-Za-z0-9_.\-]*(?:/[A-Za-z0-9_.\-{}*]+)+)`"
)


def _citacoes_de_path(literal: str) -> tuple[str, ...]:
    return tuple(sorted(set(_CITACAO_DE_PATH_RX.findall(literal))))


def test_o_snapshot_de_citacoes_cobre_os_24_seeds():
    """Guarda do proprio snapshot: seed sem entrada nao passa despercebido.

    Sem isto, um seed novo (ou renomeado) entraria com zero cobertura e o
    dicionario continuaria verde, porque a comparacao e por seed.
    """
    assert set(EXPECTED_SEED_PATH_CITATIONS) == set(CANONICAL_SEED_FILENAMES), (
        "EXPECTED_SEED_PATH_CITATIONS nao bate com CANONICAL_SEED_FILENAMES: "
        f"sobrando={sorted(set(EXPECTED_SEED_PATH_CITATIONS) - set(CANONICAL_SEED_FILENAMES))} "
        f"faltando={sorted(set(CANONICAL_SEED_FILENAMES) - set(EXPECTED_SEED_PATH_CITATIONS))}"
    )


@pytest.mark.parametrize("filename", CANONICAL_SEED_FILENAMES)
def test_os_paths_que_o_corpo_manda_ler_sao_os_declarados(filename: str):
    """O conjunto de arquivos que o seed manda abrir e congelado por seed."""
    seed_dir = resolve_seed_dir(REPO_ROOT)
    literal = extract_action_literal((seed_dir / filename).read_text(encoding="utf-8"))
    assert literal, f"{filename}: bloco `## Prompt canonico` ausente ou vazio"

    atual = _citacoes_de_path(literal)
    esperado = EXPECTED_SEED_PATH_CITATIONS[filename]
    if atual == esperado:
        return

    entraram = sorted(set(atual) - set(esperado))
    sairam = sorted(set(esperado) - set(atual))
    raise AssertionError(
        f"{filename}: os paths citados no corpo mudaram sem decisao registrada.\n"
        f"  entraram (arquivo novo que o modelo passa a abrir): {entraram or 'nenhum'}\n"
        f"  sairam (regra que o modelo parou de ler): {sairam or 'nenhum'}\n"
        "Se a mudanca e intencional, atualize EXPECTED_SEED_PATH_CITATIONS na "
        "mesma alteracao -- o snapshot existe para forcar esse ato, nao para "
        "impedir a edicao."
    )


@pytest.mark.parametrize("filename", CANONICAL_SEED_FILENAMES)
def test_todo_path_citado_pelo_corpo_existe_em_disco(filename: str):
    """Citar arquivo inexistente e mandar o modelo ler o vazio.

    O gate G6 ja cobre o `agent_path` do frontmatter. O corpo cita mais que
    isso -- template de forma, validador, regras de operacao de arquivo,
    INDEX de component-kit -- e nada cobria essas.
    """
    seed_dir = resolve_seed_dir(REPO_ROOT)
    literal = extract_action_literal((seed_dir / filename).read_text(encoding="utf-8"))
    assert literal, f"{filename}: bloco `## Prompt canonico` ausente ou vazio"

    ausentes = [
        p
        for p in _citacoes_de_path(literal)
        if "{" not in p and "*" not in p and not (REPO_ROOT / p).exists()
    ]
    assert not ausentes, (
        f"{filename}: o corpo manda ler path que nao existe: {ausentes}"
    )


# ── 4. Fronteira de escrita DECLARADA por corpo ─────────────────────────────

#: Marcadores ESTRUTURAIS do bloco `Restricoes:`. Sao prefixos fixos de bullet,
#: nao vocabulario a ser reconhecido em prosa: o gate acha os dois por posicao e
#: prefixo. Tentar deduzir destino ou proibicao lendo a prosa e a classe de
#: falha catalogada no topo de `tests/_helpers.py`, e ja custou duas
#: reescritas.
_MARCADOR_DESTINO = "- Destino de escrita: "
_MARCADOR_PROIBIDO = "- Proibido: "

#: Token de crase que serve de alvo: path, chave de frontmatter ou testid.
_ALVO_EM_CRASE_RX = re.compile(r"`([^`]+)`")

#: Formas de alvo que CONTAM como destino nomeado. A regra existe porque
#: "tem crase" nao e nomear: `` `.` `` e `` `o repositorio` `` passavam pelo
#: teste anterior e nao dizem onde a escrita cai. Cada forma abaixo aparece
#: hoje em pelo menos um dos 25 corpos -- a lista descreve o vocabulario real,
#: nao um ideal.
_FORMAS_DE_ALVO = (
    ("path", lambda s: "/" in s),
    ("arquivo .md", lambda s: s.endswith(".md")),
    ("secao", lambda s: s.lstrip().startswith("#")),
    ("campo de task", lambda s: s.startswith("**") and s.endswith(":**")),
    ("chave", lambda s: re.fullmatch(r"[a-z_][a-z0-9_]*", s) is not None),
    ("testid", lambda s: re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", s) is not None),
)

#: Linha que ANUNCIA restricoes, com ou sem prefixo de heading/citacao. Serve
#: so para contar: o bloco canonico e um so, e um `### Restricoes:` mais
#: abaixo era invisivel para o parser -- reabria escopo sem ficar vermelho.
_ANUNCIO_RESTRICOES_RX = re.compile(r"(?m)^[ \t]*[#>*\-]*[ \t]*Restricoes:[ \t]*$")

#: Abertura/fechamento de bloco cercado.
_FENCE_RX = re.compile(r"(?m)^[ \t]*```")


def _spans_de_fence(literal: str) -> tuple[tuple[int, int], ...]:
    """Intervalos [inicio, fim) cobertos por blocos cercados.

    Fence sem par fecha no fim do texto: o objetivo e nao considerar como
    instrucao viva um trecho que esta dentro de exemplo, e um bloco aberto e
    exatamente o caso em que tudo dali para baixo e exemplo.
    """
    marcas = [m.start() for m in _FENCE_RX.finditer(literal)]
    spans: list[tuple[int, int]] = []
    for i in range(0, len(marcas), 2):
        inicio = marcas[i]
        fim = marcas[i + 1] if i + 1 < len(marcas) else len(literal)
        spans.append((inicio, fim))
    return tuple(spans)


def _em_fence(pos: int, spans) -> bool:
    return any(a <= pos < b for a, b in spans)


def _anuncios_de_restricoes(literal: str) -> tuple[tuple[int, str], ...]:
    """(posicao, linha) de cada anuncio de restricoes FORA de bloco cercado."""
    spans = _spans_de_fence(literal)
    return tuple(
        (m.start(), m.group(0).strip())
        for m in _ANUNCIO_RESTRICOES_RX.finditer(literal)
        if not _em_fence(m.start(), spans)
    )


def _bullets_de_restricoes(literal: str) -> tuple[str, ...]:
    """Bullets do bloco `Restricoes:` do corpo, achatados, ou `()` se ausente.

    Parser POSICIONAL: bullet e linha que comeca com `- `; linha indentada
    pertence ao bullet anterior; linha vazia nao fecha o bloco; qualquer outra
    linha fecha. Nada aqui julga o texto do bullet.

    O marcador e procurado FORA de bloco cercado. Um corpo que mostrasse um
    exemplo de `Restricoes:` dentro de ``` teria a fronteira lida do exemplo,
    e o exemplo e o unico lugar do texto onde a fronteira nao vale.
    """
    marcador = "\nRestricoes:\n"
    spans = _spans_de_fence(literal)
    i = -1
    busca = literal.find(marcador)
    while busca >= 0:
        if not _em_fence(busca + 1, spans):
            i = busca
            break
        busca = literal.find(marcador, busca + 1)
    if i < 0:
        return ()
    bullets: list[str] = []
    for linha in literal[i + len(marcador):].splitlines():
        if linha.startswith("- "):
            bullets.append(linha)
        elif not linha.strip():
            continue
        elif bullets and linha[:1] in (" ", "\t"):
            bullets[-1] += " " + linha.strip()
        else:
            break
    return tuple(bullets)


#: Corpo sintetico com um bloco `Restricoes:` DENTRO de exemplo cercado, antes
#: do bloco vivo. E a forma que o parser antigo lia por primeiro.
_CORPO_COM_DECOY = """Tarefa:

1. Fazer algo.

```markdown
Restricoes:

- Destino de escrita: `exemplo/qualquer.md`, so ilustrativo.
- Proibido: nada, isto aqui e exemplo e nao instrucao.
```

Restricoes:

- Destino de escrita: o `.md` selecionado (target_path=true).
- Proibido: reescrever qualquer outro arquivo do repositorio.
"""


def test_o_parser_de_fronteira_ignora_exemplo_cercado():
    """A fronteira sai da instrucao viva, nunca do exemplo.

    Um corpo que ILUSTRA um bloco `Restricoes:` dentro de ``` tinha a
    fronteira lida do exemplo: `str.find` acha a primeira ocorrencia, e a
    primeira era a de mentira. O gate global cobraria o destino do exemplo e
    aprovaria um corpo cujo bloco vivo dissesse outra coisa -- ou nao
    existisse.
    """
    bullets = _bullets_de_restricoes(_CORPO_COM_DECOY)
    assert bullets, "parser nao achou o bloco vivo"
    assert "target_path=true" in bullets[0], (
        f"o parser leu o bloco do exemplo: {bullets[0]!r}"
    )
    assert len(_anuncios_de_restricoes(_CORPO_COM_DECOY)) == 1, (
        "o anuncio dentro do fence foi contado como bloco vivo"
    )


def test_o_parser_de_fronteira_enxerga_cabecalho_concorrente():
    """`### Restricoes:` e um segundo bloco, e tem de ser contado como tal.

    O marcador `\nRestricoes:\n` nao casa com uma linha de heading, entao um
    segundo bloco escrito assim ficava invisivel: o parser continuava lendo o
    primeiro e o gate de cardinalidade continuava vendo "exatamente um". Um
    corpo podia fechar o escopo em cima e reabri-lo embaixo sem nenhum teste
    ficar vermelho.
    """
    corpo = _CORPO_COM_DECOY + "\n### Restricoes:\n\n- Destino de escrita: qualquer lugar.\n"
    assert len(_anuncios_de_restricoes(corpo)) == 2, (
        "o segundo anuncio, escrito como heading, passou despercebido"
    )


def test_todo_corpo_despachado_declara_a_propria_fronteira_de_escrita():
    """Cada corpo diz, em forma fechada, ONDE pode escrever e o que nao pode.

    Antes disto nenhum teste do repositorio olhava para `Restricoes:` -- o
    bloco existia em 18 dos 24 seeds, faltava inteiro em seis (07, 18, 20, 21,
    23, 24) e ninguem percebia. O seed 24 chegava a mandar "propor ou APLICAR
    uma mudanca isolada" sem uma linha dizendo onde essa mudanca podia cair.

    Por que marcador estrutural e nao leitura de prosa: o inventario de paths
    (`EXPECTED_SEED_PATH_CITATIONS`) congela QUE arquivos o corpo cita, e um
    corpo pode inverter a acao -- trocar "ler" por "reescrever" -- mantendo o
    mesmo conjunto de paths e o snapshot verde. A fronteira precisa estar
    declarada num campo que so pode ser lido de um jeito.

    O que este gate NAO prova:

    - que o modelo obedeca. Isso nao e assertavel em teste; o que e assertavel
      e que a instrucao entregue carrega a fronteira;
    - que o destino declarado seja o destino CERTO. Isso e decisao de produto,
      e vive no proprio texto do bullet, revisado por humano;
    - que a proibicao cubra todo efeito colateral possivel. Ela cobre o que foi
      decidido; o gate garante que exista e nao possa sumir calada.
    """
    corpos = _corpos_incluindo_suplementos()
    assert len(corpos) == CANONICAL_SEED_COUNT + len(_SUPLEMENTOS), (
        f"varredura degenerada: {len(corpos)} corpos"
    )

    for nome, _fm, literal in corpos:
        # Conta ANUNCIOS, e nao a forma exata: `### Restricoes:` mais abaixo
        # nao casava com o marcador e reabria escopo em silencio -- dois
        # blocos, e o parser lia so o primeiro. Fora de fence, porque exemplo
        # cercado nao e instrucao.
        anuncios = _anuncios_de_restricoes(literal)
        assert len(anuncios) == 1, (
            f"{nome}: esperado exatamente um anuncio de `Restricoes:` fora de "
            f"bloco cercado, achado {len(anuncios)}: "
            f"{[linha for _pos, linha in anuncios]}"
        )
        assert anuncios[0][1] == "Restricoes:", (
            f"{nome}: o anuncio da fronteira tem de ser a linha nua "
            f"`Restricoes:`; achado {anuncios[0][1]!r}"
        )

        bullets = _bullets_de_restricoes(literal)
        assert len(bullets) >= 2, (
            f"{nome}: bloco `Restricoes:` com {len(bullets)} bullet(s); a "
            f"fronteira exige ao menos destino + proibicao"
        )

        assert bullets[0].startswith(_MARCADOR_DESTINO), (
            f"{nome}: o primeiro bullet de `Restricoes:` tem de ser o destino "
            f"de escrita e comecar com {_MARCADOR_DESTINO!r}; achado: "
            f"{bullets[0][:70]!r}"
        )
        assert literal.count(_MARCADOR_DESTINO) == 1, (
            f"{nome}: {literal.count(_MARCADOR_DESTINO)} marcadores de destino "
            f"no corpo; dois destinos declarados e nenhuma fronteira"
        )

        proibidos = [b for b in bullets if b.startswith(_MARCADOR_PROIBIDO)]
        assert len(proibidos) == 1, (
            f"{nome}: {len(proibidos)} bullets {_MARCADOR_PROIBIDO!r} "
            f"(esperado 1)"
        )

        destino = bullets[0][len(_MARCADOR_DESTINO):]
        tokens = _ALVO_EM_CRASE_RX.findall(destino)
        assert tokens, (
            f"{nome}: o destino declarado nao nomeia nenhum alvo entre crases "
            f"(path, chave de frontmatter ou testid): {destino[:90]!r}"
        )
        nomeados = [
            tok for tok in tokens
            if any(reconhece(tok.strip()) for _forma, reconhece in _FORMAS_DE_ALVO)
        ]
        assert nomeados, (
            f"{nome}: o destino poe crase em {tokens!r}, e nenhum desses tem "
            f"forma de alvo. Crase nao e endereco: `.` e `o repositorio` "
            f"passavam por este gate sem dizer onde a escrita cai. Formas "
            f"aceitas: {[f for f, _r in _FORMAS_DE_ALVO]}"
        )
        assert len(proibidos[0]) - len(_MARCADOR_PROIBIDO) >= 20, (
            f"{nome}: proibicao vazia de conteudo: {proibidos[0]!r}"
        )


def test_a_fronteira_declarada_nao_contradiz_o_target_path_do_frontmatter():
    """Frontmatter e corpo sao lidos por consumidores diferentes; nao podem brigar.

    `target_path` decide, no app, se o botao recebe o `.md` do picker
    (`main_window`/`mcp_prompt_actions`); o bullet de destino decide, no
    modelo, onde a escrita pode cair. Um corpo dizendo `target_path=true`
    debaixo de um frontmatter `false` manda o modelo editar um arquivo que o
    app nunca vai lhe entregar -- e o inverso faz ele recusar o arquivo que
    recebeu.

    O token `target_path=` e OBRIGATORIO no bullet, e nao opcional. Enquanto
    era opcional, a comparacao se abstinha: quatro dos vinte e cinco corpos
    (01, 12, 13, 22) simplesmente nao o escreviam, e para esses quatro o gate
    nao julgava nada -- justamente os tres em que `target_path: true` conVIVE
    com um destino que NAO e o arquivo do picker, que e a configuracao mais
    facil de o modelo confundir. Nao se infere valor a partir de prosa: o
    bullet declara, ou fica vermelho.
    """
    for nome, frontmatter, literal in _corpos_incluindo_suplementos():
        bullets = _bullets_de_restricoes(literal)
        assert bullets, f"{nome}: sem bloco `Restricoes:`"
        destino = bullets[0][len(_MARCADOR_DESTINO):]
        declarado = bool(frontmatter.get("target_path"))

        assert "target_path=true" in destino or "target_path=false" in destino, (
            f"{nome}: o bullet de destino nao declara `target_path=`; sem o "
            f"token a comparacao com o frontmatter se abstem e o corpo fica "
            f"livre para dizer o contrario dele: {destino[:110]!r}"
        )

        if "target_path=true" in destino:
            assert declarado, (
                f"{nome}: destino diz `target_path=true` e o frontmatter diz "
                f"false; o app nao entrega arquivo nenhum a este botao"
            )
        if "target_path=false" in destino or "`false`" in destino:
            assert not declarado, (
                f"{nome}: destino nega o target_path que o frontmatter afirma"
            )
        if not declarado:
            assert "in-place" not in destino, (
                f"{nome}: `target_path: false` nao tem arquivo-alvo para "
                f"editar in-place: {destino[:90]!r}"
            )


def test_a_descoberta_em_disco_nao_traz_corpo_fora_do_registro():
    """A grade descobre `NN-<slug>.md` ABERTO; as invariantes iteram uma tupla.

    `_load_brainstorm_seeds` (main_window) despacha qualquer arquivo com forma
    de seed que esteja em `seeds/` -- acrescentar `25-*.md` nao exige editar
    Python. Toda varredura deste arquivo, porem, itera
    `CANONICAL_SEED_FILENAMES`. Sem este gate, um seed 25 vira botao com ZERO
    invariante de corpo e a suite fica verde: sem fronteira de escrita, sem
    snapshot de paths, sem nada.

    O predicado de descoberta e reusado de `seed_prefix`, e nao reescrito
    aqui: duas implementacoes da mesma regra divergem em silencio, que e o
    motivo de a precedencia output-antes-de-seed morar num lugar so.
    """
    seed_dir = resolve_seed_dir(REPO_ROOT)
    descobertos = {
        p.name for p in seed_dir.glob("*.md") if seed_prefix(p.name) is not None
    }
    registro = set(CANONICAL_SEED_FILENAMES)
    assert descobertos == registro, (
        "o que a grade despacha divergiu do registro de identidade.\n"
        f"  em disco e fora do registro (vira botao sem invariante nenhuma): "
        f"{sorted(descobertos - registro) or 'nenhum'}\n"
        f"  no registro e ausente do disco: "
        f"{sorted(registro - descobertos) or 'nenhum'}\n"
        "Seed novo e bem-vindo: acrescente-o a CANONICAL_SEED_FILENAMES e aos "
        "snapshots por seed na mesma alteracao -- este gate existe para forcar "
        "esse ato, nao para impedir o seed."
    )
