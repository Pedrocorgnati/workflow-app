"""Feature flags do workflow-app, resolvidas no boot do processo.

Ponto UNICO de leitura do kill-switch global da expansao multi-LLM (loop
`08-11-llm-config-multillm-expansion`, item 002). O nome da env var vive uma
unica vez neste arquivo, em `_LLM_CONFIG_V2_FLAG`; nenhum outro modulo de `src/`
consulta o ambiente para essa decisao.

Contrato:

- A variavel e lida UMA vez, em tempo de import (boot), e congelada em constante
  de modulo. As funcoes publicas respondem a partir dessa captura e nunca voltam
  ao ambiente. Espalhar `os.environ.get` por chamada e exatamente o anti-pattern
  que este modulo existe para impedir.
- Consequencia operacional (gate G2 do loop): trocar a variavel no meio de um
  processo ja iniciado nao muda a resposta. Todo teste de estado de flag exige
  processo novo por estado. Nao existe hook de reset: um reset em runtime abriria
  um segundo caminho de resolucao e violaria o proprio contrato de ponto unico.
- Fail-closed: somente o valor `"1"` liga o caminho novo. Ausente, `"0"` e
  qualquer outro valor caem no caminho legado, que e byte-a-byte o comportamento
  descrito no Bloco 3 do `BASELINE.md` do loop. A comparacao e literal: sem
  `strip`, sem `casefold`, sem coercao. Toda normalizacao de entrada alarga o
  conjunto de valores que LIGAM o caminho novo, que e exatamente o oposto de
  fail-closed; `" 1 "`, `"1\n"`, `"TRUE"` e `"01"` sao valores nao reconhecidos
  e caem no legado.
- KS-02 / G3: desligar a flag desliga comportamento; nao reverte escrita ja feita
  em disco.

Consumidores previstos: itens 003 e 009 do loop. O item 002 entrega apenas o
helper; nenhum caminho de UI o consome ainda.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

# ══════════════════════════════════════════════════════════════════════ #
# SECAO: familias de kill-switch e inventario KS-01 (item 005)          #
# ══════════════════════════════════════════════════════════════════════ #
#
# (a) CRITERIO DE CLASSIFICACAO — invariante
#
#     A familia de um kill-switch e definida por QUANDO o gate e consultado,
#     nunca pela pureza do codigo gateado. Se o valor e lido no import do
#     modulo ou na construcao do widget, o switch e BOOT-FROZEN, ainda que o
#     codigo por tras do gate seja puro e testavel em isolamento. Inversamente,
#     codigo impuro consultado a cada chamada seria hot-read. Classificar pela
#     pureza do alvo — e nao pelo momento da leitura — foi o erro que este
#     criterio existe para impedir.
#
# (b) INVENTARIO KS-01 — todos os switches deste modulo, nos DOIS prefixos
#
#     Polaridade:
#       opt-in  = ausente cai no legado; so `"1"` liga o caminho novo.
#       opt-out = ausente JA e o caminho novo; `"0"` restaura o legado.
#
#     | # | Nome                                     | Polaridade | Familia     | Estado legado restaurado                                          |
#     |---|------------------------------------------|------------|-------------|-------------------------------------------------------------------|
#     | 1 | SF_LLM_CONFIG_V2                         | opt-in     | boot-frozen | Bloco 3 do BASELINE.md do loop 08-11 (UI multi-LLM inteira off)   |
#     | 2 | SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE   | opt-out    | boot-frozen | `"0"` suprime flags de delegacao para terminais nao-Claude        |
#     | 3 | SF_LLM_FLAGS_RULES_V2                    | opt-in     | boot-frozen | regras de flag anteriores ao pacote de rules                      |
#     | 4 | SF_INSTANCE_GROUP_ROUTE_AWARE            | opt-in     | boot-frozen | agrupamento de instancia sem consciencia de rota                  |
#     | 5 | SF_GROK_SPIKE                            | opt-in     | boot-frozen | roster sem `grok` (radio Main e worker paralelo ocultos)          |
#     | 6 | SF_MAIN_PROVIDERS_V2                     | opt-in     | boot-frozen | radios Main = `claude`, `codex`, `kimi` (sem qwen/opus/sonnet/k3) |
#     | 7 | SF_PARALLEL_WORKERS_V2                   | opt-in     | boot-frozen | workers = `kimi` (T2) e `codex` (T3), 2 no total                  |
#     | 8 | SF_LLM_FLAGS_V2                          | opt-in     | boot-frozen | conjunto fechado de 2 literais: `--codex` e `--kimi`              |
#     | 9 | SF_MCP_THINK_EXEC_V2                     | opt-in     | boot-frozen | action row legada Main MCP / Parallel / Dual (sem TE-01)          |
#     |10 | SF_MCP_WRAPPERS_V2                       | (n/a)      | (n/a)       | NAO CRIADO — ver nota abaixo                                      |
#
#     Contagem MEDIDA nesta tabela (item 006 do loop
#     08-17-systemforge-multillm-gaps-refactor, gap C7): 10 linhas numeradas e
#     9 switches VIVOS. A diferenca e a linha 10, que registra um switch NAO
#     CRIADO (ver nota abaixo). A linha do switch proprio do Router V2 (item
#     010) foi RETIRADA — nao marcada como legada — junto com a remocao daquele
#     regime em `command_queue/provider_router.py`, e as linhas seguintes foram
#     renumeradas sem deixar lacuna. O nome da variavel morta nao e repetido
#     aqui de proposito: ele so sobrevive no guard de remocao em
#     `tests/test_provider_router.py`, para que uma busca por ocorrencia viva no
#     `src/` volte vazia.
#
#     Linha 10 (`SF_MCP_WRAPPERS_V2`): o switch NAO existe neste modulo e nao
#     foi criado pelo item 005. Nao ha, em `src/`, camada de wrappers que ele
#     possa gatear (A005-8), e a decisao D-005-2 — onde exatamente o gate
#     entraria — segue sem resposta. Criar a constante sem comportamento
#     gateado produziria um switch inerte, que e exatamente o defeito R-H1 que
#     o item 005 existe para nao cometer. A linha fica no inventario como
#     registro do que falta, nunca como declaracao de que o switch existe.
#
#     `SF_MODEL_EFFORT_EQUIV` NAO consta nesta tabela: foi removido pelo item
#     002 (D-C27-2) e nao e membro vivo de familia nenhuma.
#
# (c) `SF_FLAG_PARITY_V2` — NAO EXISTE E NAO DEVE SER CRIADO
#
#     O comportamento de paridade de flags ja tem freio funcional proprio:
#     `SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE` (`:98-133` na numeracao anterior
#     a esta secao; ver o bloco daquele switch abaixo), default LIGADO e
#     fail-open deliberado. Dois freios para o mesmo comportamento e defeito
#     pior que o gap que eles tentariam fechar (`source.md:1256`). Qualquer
#     proposta futura de `SF_FLAG_PARITY_V2` deve ser recusada apontando para
#     este paragrafo e para o switch que ja cobre o caso.
#
# (d) REVOGACAO DA CLAUSULA GLOBAL DO DOCSTRING DE MODULO — PENDENTE
#
#     Bloqueada pela decisao D-005-1 (sem resposta). O docstring de modulo
#     declara contrato boot-frozen para o modulo INTEIRO e trata leitura
#     per-call como anti-pattern. Revogar essa clausula so faz sentido se a
#     familia hot-read tiver ao menos um membro declarado — e hoje ela tem
#     zero, porque seu unico candidato historico (`SF_MODEL_EFFORT_EQUIV`) foi
#     removido pelo item 002. As alternativas em aberto (lista de admissao
#     vazia, familia hot-read registrada como historico revogado, ou
#     reclassificacao de um switch existente) sao decisao, nao inferencia.
#     Ate D-005-1 ser respondida, o docstring de modulo permanece intocado e
#     valido: os 9 switches vivos da tabela acima sao, sem excecao,
#     boot-frozen, entao a clausula global descreve corretamente o estado atual
#     do modulo. Esta alinea NAO afrouxa nada de forma generica.
#
#
# (e) DECISOES ABERTAS RESTANTES — o que ficou fora e por que
#
#     D-005-3 (`grok` entra em `SF_MAIN_PROVIDERS_V2`?) — SEM RESPOSTA. Acao
#     nula tomada: o radio `grok` continua exclusivamente sob `SF_GROK_SPIKE`
#     (linha 6 da tabela) e NAO foi adicionado ao roster de
#     `SF_MAIN_PROVIDERS_V2` (linha 7). Amarrar o mesmo radio a dois switches e
#     o defeito C7 (`command_queue/provider_router.py:228`); enquanto a decisao
#     nao vier, um switch por radio e a unica configuracao que nao inventa
#     semantica para a rodada "todos ligados" do KS-01.
#
#     D-005-4 (profundidade do gate da precedencia) — SEM RESPOSTA, DIVIDA
#     REGISTRADA. `_resolve_interactive_main_llm_slug` percorre
#     `_MAIN_LLM_PRECEDENCE` lendo `isChecked()` sem consultar visibilidade.
#     Com `SF_MAIN_PROVIDERS_V2` ausente os 4 radios novos ficam ocultos e o
#     slug persistido que apontasse para um deles cai de volta para `claude`;
#     como o `_main_llm_group` e exclusivo, marcar `claude` desmarca os demais,
#     entao o caminho legado e correto na UI. Um `setChecked` PROGRAMATICO
#     sobre um radio oculto, porem, ainda faria a precedencia devolver um slug
#     nao legado. Filtrar a iteracao pelo switch mudaria o
#     comportamento observavel de testes que marcam radios direto, e essa
#     troca e decisao, nao inferencia.
#
#     D-005-5 (`tests/test_llm_config_tab.py:511-522`) — SEM RESPOSTA, DIVIDA
#     REGISTRADA. `TestFlagsPanelSupportedFlags::test_supported_flags_count_is_seven`
#     e `::test_supported_flags_literals` fixam 7 literais e passam a falhar sob
#     o regime ausente de `SF_LLM_FLAGS_V2`. O arquivo esta declaradamente fora
#     da suite executada (cerca de 16 min, `source.md:1339`), entao consertar os
#     asserts aqui produziria correcao nao demonstravel. Nao foram tocados.
#
# ══════════════════════════════════════════════════════════════════════ #

# Unica ocorrencia literal do nome da env var em `src/`. Todo o resto do codigo
# se refere a ela por esta constante (criterio de aceite A1 do item 002).
_LLM_CONFIG_V2_FLAG: Final[str] = "SF_LLM_CONFIG_V2"

#: Variavel nao definida no ambiente do processo. Caminho legado.
STATE_ABSENT: Final[str] = "absent"
#: Definida como `"0"`. Kill-switch explicitamente desligado. Caminho legado.
STATE_OFF: Final[str] = "off"
#: Definida como `"1"`. Unico estado que liga o caminho novo.
STATE_ON: Final[str] = "on"
#: Definida com qualquer outro valor. Fail-closed no caminho legado.
STATE_UNRECOGNIZED: Final[str] = "unrecognized"


def _resolve_llm_config_v2_state(env: Mapping[str, str]) -> str:
    """Classifica o estado da flag a partir de um mapping de ambiente (funcao pura).

    Recebe o mapping por parametro para permanecer testavel sem tocar o processo
    corrente. O unico callsite de producao e a resolucao de boot logo abaixo.
    """
    if _LLM_CONFIG_V2_FLAG not in env:
        return STATE_ABSENT
    # Comparacao literal, deliberadamente sem `strip()`/`casefold()`: qualquer
    # normalizacao aqui aumentaria o conjunto de valores capazes de LIGAR o
    # caminho novo, invertendo o contrato fail-closed declarado no docstring do
    # modulo e no ST001 do item 002.
    raw = env[_LLM_CONFIG_V2_FLAG]
    if raw == "1":
        return STATE_ON
    if raw == "0":
        return STATE_OFF
    return STATE_UNRECOGNIZED


# Resolucao de boot: acontece uma vez, no import do modulo.
_LLM_CONFIG_V2_STATE: Final[str] = _resolve_llm_config_v2_state(os.environ)
_LLM_CONFIG_V2_ENABLED: Final[bool] = _LLM_CONFIG_V2_STATE == STATE_ON


def llm_config_v2_flag_name() -> str:
    """Nome da env var do kill-switch, para mensagens de diagnostico e telemetria."""
    return _LLM_CONFIG_V2_FLAG


def llm_config_v2_state() -> str:
    """Estado congelado no boot: `absent`, `off`, `on` ou `unrecognized`."""
    return _LLM_CONFIG_V2_STATE


def llm_config_v2_enabled() -> bool:
    """`True` somente quando a flag foi lida como `"1"` no boot deste processo."""
    return _LLM_CONFIG_V2_ENABLED


# ── Kill-switch: delegacao de flags para Main nao-Claude ────────────── #
# Item 012 do loop 08-11-llm-config-multillm-expansion. Segundo kill-switch
# do modulo, mesmo padrao boot-frozen do item 002. Diferente do global
# (`_LLM_CONFIG_V2_FLAG`, fail-closed com default legado), este tem default
# LIGADO: a paridade de sufixo e o comportamento correto; o valor "0"
# desliga (freio imediato em producao se a paridade regridir).
_DELEGATION_FLAGS_NONCLAUDE_FLAG: Final[str] = "SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE"


def _resolve_delegation_flags_nonclaude(env: Mapping[str, str]) -> bool:
    """Classifica o estado da flag de delegacao non-Claude (funcao pura).

    Default operacional: LIGADO (True). A paridade de sufixo nos quatro
    caminhos e o comportamento desejado; o kill-switch so freia em producao
    se a paridade regridir. Somente o valor literal "0" desliga.
    Fail-closed para o lado seguro: paridade ativa.
    """
    if _DELEGATION_FLAGS_NONCLAUDE_FLAG not in env:
        return True  # default ligado
    raw = env[_DELEGATION_FLAGS_NONCLAUDE_FLAG]
    if raw == "0":
        return False
    return True  # qualquer outro valor = paridade ativa


_DELEGATION_FLAGS_NONCLAUDE_ENABLED: Final[bool] = _resolve_delegation_flags_nonclaude(
    os.environ
)


def delegation_flags_nonclaude_enabled() -> bool:
    """`True` quando a paridade de flags para Main nao-Claude esta ativa.

    Default True (paridade ligada). Somente ``SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0``
    desliga. Congelado no boot (mesmo contrato do item 002).
    """
    return _DELEGATION_FLAGS_NONCLAUDE_ENABLED


def delegation_flags_nonclaude_flag_name() -> str:
    """Nome da env var do kill-switch de delegacao non-Claude."""
    return _DELEGATION_FLAGS_NONCLAUDE_FLAG


# ── Kill-switch: atalho da rule de flags multi-LLM ─────────────────── #
# Item 016 do loop 08-11-llm-config-multillm-expansion. Mesmo contrato
# fail-closed e boot-frozen do item 002: somente o literal "1" registra o
# atalho novo na sub-aba RULES; qualquer outro estado preserva o layout legado.
_LLM_FLAGS_RULES_V2_FLAG: Final[str] = "SF_LLM_FLAGS_RULES_V2"


def _resolve_llm_flags_rules_v2_state(env: Mapping[str, str]) -> str:
    """Classifica o estado do kill-switch do atalho da rule (funcao pura)."""
    if _LLM_FLAGS_RULES_V2_FLAG not in env:
        return STATE_ABSENT
    raw = env[_LLM_FLAGS_RULES_V2_FLAG]
    if raw == "1":
        return STATE_ON
    if raw == "0":
        return STATE_OFF
    return STATE_UNRECOGNIZED


_LLM_FLAGS_RULES_V2_STATE: Final[str] = _resolve_llm_flags_rules_v2_state(os.environ)
_LLM_FLAGS_RULES_V2_ENABLED: Final[bool] = _LLM_FLAGS_RULES_V2_STATE == STATE_ON


def llm_flags_rules_v2_flag_name() -> str:
    """Nome da env var do atalho da rule de flags multi-LLM."""
    return _LLM_FLAGS_RULES_V2_FLAG


def llm_flags_rules_v2_state() -> str:
    """Estado congelado no boot: `absent`, `off`, `on` ou `unrecognized`."""
    return _LLM_FLAGS_RULES_V2_STATE


def llm_flags_rules_v2_enabled() -> bool:
    """`True` somente quando o kill-switch foi lido como `"1"` no boot."""
    return _LLM_FLAGS_RULES_V2_ENABLED


# ── Kill-switch: instance-group route-aware (P9 / item 024) ───────── #
# Quarto kill-switch do modulo, mesmo padrao boot-frozen fail-closed do
# item 002: ausente = instance-group legado (rotas fixas: codex→xterm,
# kimid→workspace, resto→interactive). Somente "1" liga o comportamento
# route-aware (snapshot de terminal-route-t1/t2/t3) e a migracao de
# QSettings para schema v2. KS-01 do source.md.
_INSTANCE_GROUP_ROUTE_AWARE_FLAG: Final[str] = "SF_INSTANCE_GROUP_ROUTE_AWARE"


def _resolve_instance_group_route_aware_state(env: Mapping[str, str]) -> str:
    """Classifica o estado do kill-switch do instance-group route-aware (funcao pura)."""
    if _INSTANCE_GROUP_ROUTE_AWARE_FLAG not in env:
        return STATE_ABSENT
    raw = env[_INSTANCE_GROUP_ROUTE_AWARE_FLAG]
    if raw == "1":
        return STATE_ON
    if raw == "0":
        return STATE_OFF
    return STATE_UNRECOGNIZED


_INSTANCE_GROUP_ROUTE_AWARE_STATE: Final[str] = _resolve_instance_group_route_aware_state(
    os.environ
)
_INSTANCE_GROUP_ROUTE_AWARE_ENABLED: Final[bool] = (
    _INSTANCE_GROUP_ROUTE_AWARE_STATE == STATE_ON
)


def instance_group_route_aware_flag_name() -> str:
    """Nome da env var do kill-switch do instance-group route-aware."""
    return _INSTANCE_GROUP_ROUTE_AWARE_FLAG


def instance_group_route_aware_state() -> str:
    """Estado congelado no boot: `absent`, `off`, `on` ou `unrecognized`."""
    return _INSTANCE_GROUP_ROUTE_AWARE_STATE


def instance_group_route_aware_enabled() -> bool:
    """`True` somente quando a env var foi lida como `"1"` no boot."""
    return _INSTANCE_GROUP_ROUTE_AWARE_ENABLED


# ── Kill-switch: spike Grok integracao (item 025) ──────────────────── #
# Quinto kill-switch do modulo, mesmo padrao boot-frozen fail-closed do
# item 002: ausente = spike desligado (wiring descartavel isolado).
# Somente "1" liga a integracao Grok real (autenticacao + lifecycle da
# sessao). O spike NAO cumpre D-30; a promocao publica e o item 026.
# C-58: com o gate desligado, nenhuma entrada Grok spike em radio, menu
# ou telemetria publica.
_GROK_SPIKE_FLAG: Final[str] = "SF_GROK_SPIKE"


def _resolve_grok_spike_state(env: Mapping[str, str]) -> str:
    """Classifica o estado do kill-switch do spike Grok (funcao pura)."""
    if _GROK_SPIKE_FLAG not in env:
        return STATE_ABSENT
    raw = env[_GROK_SPIKE_FLAG]
    if raw == "1":
        return STATE_ON
    if raw == "0":
        return STATE_OFF
    return STATE_UNRECOGNIZED


_GROK_SPIKE_STATE: Final[str] = _resolve_grok_spike_state(os.environ)
_GROK_SPIKE_ENABLED: Final[bool] = _GROK_SPIKE_STATE == STATE_ON


def grok_spike_flag_name() -> str:
    """Nome da env var do kill-switch do spike Grok."""
    return _GROK_SPIKE_FLAG


def grok_spike_state() -> str:
    """Estado congelado no boot: `absent`, `off`, `on` ou `unrecognized`."""
    return _GROK_SPIKE_STATE


def grok_spike_enabled() -> bool:
    """`True` somente quando a env var foi lida como `"1"` no boot."""
    return _GROK_SPIKE_ENABLED


# ── Kill-switch: roster de radios Main (C26 / item 005) ───────────── #
# Item 005 do loop 08-17-systemforge-multillm-gaps-refactor. Mesmo padrao
# boot-frozen fail-closed do item 002: ausente = 3 Mains legados
# (`claude`, `codex`, `kimi`). Somente "1" liga os radios de variante e de
# provider adicional (`qwen`, `opus`, `sonnet`, `kimi-k3`). O radio `grok`
# NAO entra aqui: continua exclusivamente sob `SF_GROK_SPIKE`, para nao
# reproduzir a conjuncao de dois switches que C7 aponta como defeito.
_MAIN_PROVIDERS_V2_FLAG: Final[str] = "SF_MAIN_PROVIDERS_V2"


def _resolve_main_providers_v2_state(env: Mapping[str, str]) -> str:
    """Classifica o estado do kill-switch do roster de radios Main (funcao pura)."""
    if _MAIN_PROVIDERS_V2_FLAG not in env:
        return STATE_ABSENT
    raw = env[_MAIN_PROVIDERS_V2_FLAG]
    if raw == "1":
        return STATE_ON
    if raw == "0":
        return STATE_OFF
    return STATE_UNRECOGNIZED


_MAIN_PROVIDERS_V2_STATE: Final[str] = _resolve_main_providers_v2_state(os.environ)
_MAIN_PROVIDERS_V2_ENABLED: Final[bool] = _MAIN_PROVIDERS_V2_STATE == STATE_ON


def main_providers_v2_flag_name() -> str:
    """Nome da env var do kill-switch do roster de radios Main."""
    return _MAIN_PROVIDERS_V2_FLAG


def main_providers_v2_state() -> str:
    """Estado congelado no boot: `absent`, `off`, `on` ou `unrecognized`."""
    return _MAIN_PROVIDERS_V2_STATE


def main_providers_v2_enabled() -> bool:
    """`True` somente quando a env var foi lida como `"1"` no boot."""
    return _MAIN_PROVIDERS_V2_ENABLED


# ── Kill-switch: roster de workers paralelos (C26 / item 005) ─────── #
# Item 005 do mesmo loop. Ausente = roster legado de 2 workers
# (`use-kimi` no T2, `use-codex` no T3). Somente "1" expoe os 4 workers
# em dois pares exclusivos (T2: kimi|qwen, T3: codex|grok). A
# exclusividade PW-01 continua enforced nos handlers `_on_use_*_toggled`;
# este switch decide QUEM aparece, nunca quantos ficam marcados.
_PARALLEL_WORKERS_V2_FLAG: Final[str] = "SF_PARALLEL_WORKERS_V2"


def _resolve_parallel_workers_v2_state(env: Mapping[str, str]) -> str:
    """Classifica o estado do kill-switch do roster de workers (funcao pura)."""
    if _PARALLEL_WORKERS_V2_FLAG not in env:
        return STATE_ABSENT
    raw = env[_PARALLEL_WORKERS_V2_FLAG]
    if raw == "1":
        return STATE_ON
    if raw == "0":
        return STATE_OFF
    return STATE_UNRECOGNIZED


_PARALLEL_WORKERS_V2_STATE: Final[str] = _resolve_parallel_workers_v2_state(os.environ)
_PARALLEL_WORKERS_V2_ENABLED: Final[bool] = _PARALLEL_WORKERS_V2_STATE == STATE_ON


def parallel_workers_v2_flag_name() -> str:
    """Nome da env var do kill-switch do roster de workers paralelos."""
    return _PARALLEL_WORKERS_V2_FLAG


def parallel_workers_v2_state() -> str:
    """Estado congelado no boot: `absent`, `off`, `on` ou `unrecognized`."""
    return _PARALLEL_WORKERS_V2_STATE


def parallel_workers_v2_enabled() -> bool:
    """`True` somente quando a env var foi lida como `"1"` no boot."""
    return _PARALLEL_WORKERS_V2_ENABLED


# ── Kill-switch: conjunto fechado de literais de flag (C26 / item 005) ── #
# Item 005 do mesmo loop. Ausente = 2 literais legados (`--kimi`,
# `--codex`, tabela C26 em source.md:1251). Somente "1" liga os 7
# literais canonicos. Consumido por `workflow_app.config.llm_flags`, que e
# um modulo puro (sem Qt) — o import de `feature_flags` a partir dele e
# legitimo porque `config/__init__.py` e Qt-free por PEP 562.
#
# Familia: BOOT-FROZEN. Linha de consulta real: a expressao ternaria que
# define `_SUPPORTED_MCP_FLAGS` em `config/llm_flags.py`, avaliada UMA vez no
# import daquele modulo. As 5 estruturas restantes de `llm_flags` sao
# derivadas dessa e congelam junto.
#
# Pontos de congelamento por import (quem materializa o conjunto vigente em
# estado de modulo, tornando-o imune a mutacao posterior de `os.environ`):
#   - `llm_config/flags_panel.py:24-28` — importa `_FLAG_CANONICAL_ORDER`,
#     `_FLAG_LITERAL_TO_MAIN`, `_FLAGS_BY_TERMINAL`, `_REDUNDANT_FLAG_MAINS` e
#     congela a ordem da UI em `_FLAG_ORDER` (`:32`).
#   - `command_queue/command_item_widget.py:143` — importa
#     `_SUPPORTED_MCP_FLAGS`, usado por `render_with_mcp_flags`.
# Os demais consumidores (`command_queue_widget.py:3592`, `:9585`, `:9661`)
# importam DENTRO de funcao, entao leem o estado ja congelado; nao sao pontos
# de congelamento proprios.
#
# NAO usar as ancoras `command_queue/terminal_helpers.py:29-35` nem
# `main_window.py:6664` (A005-3, A005-4): estao erradas e citar qualquer uma
# delas reintroduziria a premissa que a preparacao do item 005 ja refutou.
_LLM_FLAGS_V2_FLAG: Final[str] = "SF_LLM_FLAGS_V2"


def _resolve_llm_flags_v2_state(env: Mapping[str, str]) -> str:
    """Classifica o estado do kill-switch do conjunto de literais (funcao pura)."""
    if _LLM_FLAGS_V2_FLAG not in env:
        return STATE_ABSENT
    raw = env[_LLM_FLAGS_V2_FLAG]
    if raw == "1":
        return STATE_ON
    if raw == "0":
        return STATE_OFF
    return STATE_UNRECOGNIZED


_LLM_FLAGS_V2_STATE: Final[str] = _resolve_llm_flags_v2_state(os.environ)
_LLM_FLAGS_V2_ENABLED: Final[bool] = _LLM_FLAGS_V2_STATE == STATE_ON


def llm_flags_v2_flag_name() -> str:
    """Nome da env var do kill-switch do conjunto fechado de literais de flag."""
    return _LLM_FLAGS_V2_FLAG


def llm_flags_v2_state() -> str:
    """Estado congelado no boot: `absent`, `off`, `on` ou `unrecognized`."""
    return _LLM_FLAGS_V2_STATE


def llm_flags_v2_enabled() -> bool:
    """`True` somente quando a env var foi lida como `"1"` no boot."""
    return _LLM_FLAGS_V2_ENABLED


# ── Kill-switch: par Thinking/Execution do dispatch MCP (C26 / item 005) ── #
# Item 005 do mesmo loop. Ausente = caminho unico legado
# (action row Main MCP / Parallel / Dual). Somente "1" liga a matriz
# `_TE_COMMANDS` com 3 pastilhas Thinking e 5 Execution (TE-01).
# Antes do item 005 esse bloco estava gateado pelo global
# `SF_LLM_CONFIG_V2`; o gate foi MOVIDO para ca, nao duplicado.
_MCP_THINK_EXEC_V2_FLAG: Final[str] = "SF_MCP_THINK_EXEC_V2"


def _resolve_mcp_think_exec_v2_state(env: Mapping[str, str]) -> str:
    """Classifica o estado do kill-switch do par think/exec (funcao pura)."""
    if _MCP_THINK_EXEC_V2_FLAG not in env:
        return STATE_ABSENT
    raw = env[_MCP_THINK_EXEC_V2_FLAG]
    if raw == "1":
        return STATE_ON
    if raw == "0":
        return STATE_OFF
    return STATE_UNRECOGNIZED


_MCP_THINK_EXEC_V2_STATE: Final[str] = _resolve_mcp_think_exec_v2_state(os.environ)
_MCP_THINK_EXEC_V2_ENABLED: Final[bool] = _MCP_THINK_EXEC_V2_STATE == STATE_ON


def mcp_think_exec_v2_flag_name() -> str:
    """Nome da env var do kill-switch do par Thinking/Execution."""
    return _MCP_THINK_EXEC_V2_FLAG


def mcp_think_exec_v2_state() -> str:
    """Estado congelado no boot: `absent`, `off`, `on` ou `unrecognized`."""
    return _MCP_THINK_EXEC_V2_STATE


def mcp_think_exec_v2_enabled() -> bool:
    """`True` somente quando a env var foi lida como `"1"` no boot."""
    return _MCP_THINK_EXEC_V2_ENABLED


__all__ = [
    "STATE_ABSENT",
    "STATE_OFF",
    "STATE_ON",
    "STATE_UNRECOGNIZED",
    "delegation_flags_nonclaude_enabled",
    "delegation_flags_nonclaude_flag_name",
    "grok_spike_enabled",
    "grok_spike_flag_name",
    "grok_spike_state",
    "instance_group_route_aware_enabled",
    "instance_group_route_aware_flag_name",
    "instance_group_route_aware_state",
    "llm_config_v2_enabled",
    "llm_config_v2_flag_name",
    "llm_config_v2_state",
    "llm_flags_rules_v2_enabled",
    "llm_flags_rules_v2_flag_name",
    "llm_flags_rules_v2_state",
    "llm_flags_v2_enabled",
    "llm_flags_v2_flag_name",
    "llm_flags_v2_state",
    "main_providers_v2_enabled",
    "main_providers_v2_flag_name",
    "main_providers_v2_state",
    "mcp_think_exec_v2_enabled",
    "mcp_think_exec_v2_flag_name",
    "mcp_think_exec_v2_state",
    "parallel_workers_v2_enabled",
    "parallel_workers_v2_flag_name",
    "parallel_workers_v2_state",
]
