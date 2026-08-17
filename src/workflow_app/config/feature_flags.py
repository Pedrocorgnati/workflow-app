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


# ── Kill-switch: router por familia e variante (P2 / item 010) ──────── #
# Terceiro kill-switch do modulo, mesmo padrao boot-frozen do item 002 e
# mesmo contrato fail-closed: ausente = router legado (CLAUDE/KIMI/CODEX,
# `main_llm` ignorado na decisao). Somente "1" liga a regra nova em que a
# familia do Main participa do roteamento. Fonte: source.md do loop
# 08-11-llm-config-multillm-expansion (tabela P2, "ausente = legado").
_PROVIDER_ROUTER_V2_FLAG: Final[str] = "SF_PROVIDER_ROUTER_V2"


def _resolve_provider_router_v2_state(env: Mapping[str, str]) -> str:
    """Classifica o estado do kill-switch do router (funcao pura).

    Mesma comparacao literal do item 002 (sem `strip`/`casefold`): normalizar
    a entrada alargaria o conjunto de valores capazes de LIGAR o caminho novo,
    que e o oposto de fail-closed.
    """
    if _PROVIDER_ROUTER_V2_FLAG not in env:
        return STATE_ABSENT
    raw = env[_PROVIDER_ROUTER_V2_FLAG]
    if raw == "1":
        return STATE_ON
    if raw == "0":
        return STATE_OFF
    return STATE_UNRECOGNIZED


_PROVIDER_ROUTER_V2_STATE: Final[str] = _resolve_provider_router_v2_state(os.environ)
_PROVIDER_ROUTER_V2_ENABLED: Final[bool] = _PROVIDER_ROUTER_V2_STATE == STATE_ON


def provider_router_v2_flag_name() -> str:
    """Nome da env var do kill-switch do router por familia e variante."""
    return _PROVIDER_ROUTER_V2_FLAG


def provider_router_v2_state() -> str:
    """Estado congelado no boot: `absent`, `off`, `on` ou `unrecognized`."""
    return _PROVIDER_ROUTER_V2_STATE


def provider_router_v2_enabled() -> bool:
    """`True` somente quando a env var (`_PROVIDER_ROUTER_V2_FLAG`) foi lida como `"1"` no boot.

    O router so consulta o Main na decisao quando este helper E
    :func:`llm_config_v2_enabled` respondem `True` (o global do item 002 e o
    kill-switch especifico do item 010 valem em conjuncao).
    """
    return _PROVIDER_ROUTER_V2_ENABLED


# ── Kill-switch: instance-group route-aware (P9 / item 024) ───────── #
# Quinto kill-switch do modulo, mesmo padrao boot-frozen fail-closed do
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
# Sexto kill-switch do modulo, mesmo padrao boot-frozen fail-closed do
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
    "provider_router_v2_enabled",
    "provider_router_v2_flag_name",
    "provider_router_v2_state",
]
