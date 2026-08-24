"""Envelope versionado de FailureEvent (Task 14 do estudo 08-24).

Contexto do defeito que este modulo corrige. No corte auditado havia 61 JSONL e
2.553 eventos validos, e **todos** tinham `command`, `exit_code` e
`duration_seconds` nulos; em 966 deles `run_id` tambem estava ausente. O funil
bruto, portanto, nao mede producao: ele registra que algo falhou, sem dizer o
que, por quanto tempo, nem em qual run.

O que este envelope muda:

1. **Versao.** `schema_version` permite evoluir o corpus sem adivinhar formato.
2. **Identidade.** `event_id` unico por evento; `run_id` presente quando ha run.
3. **Origem e classe.** `source` diz QUEM observou; `failure_class` diz QUE TIPO
   de falha e. Os dois eixos sao ortogonais - um `EXIT_NONZERO` observado pelo
   listener e um observado por um gate sao a mesma classe, origens distintas.
4. **Comando sem vazamento.** `command_name` guarda o slash-command ou o
   primeiro token sanitizado. Nunca linha completa, args, heredoc ou path.
5. **`notify` deixa de ser categoria.** Payload sem reason vira `UNSPECIFIED`
   com classe `unknown`. Tratar `notify` como reason semantico inflava a
   estatistica com uma categoria que nunca descreveu falha alguma.

Nulabilidade e deliberada: `exit_code` e `duration_seconds` so aparecem quando
foram **observados**. Falha sem processo observado nao tem exit code legitimo, e
inventar zero seria pior que admitir o desconhecido (Zero Assumido).

Este modulo e puro: sem Qt, sem I/O, sem relogio proprio alem de `time.time()`.
Quem persiste e o chamador.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Final

SCHEMA_VERSION: Final[str] = "1.0.0"

# QUEM observou a falha.
SOURCES: Final[frozenset[str]] = frozenset(
    {"listener", "recovery", "provider", "subprocess", "gate", "test"}
)

# QUE TIPO de falha e. Ortogonal a `source`.
FAILURE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "semantic",
        "infrastructure",
        "auth",
        "quota",
        "process",
        "recovery",
        "unknown",
    }
)

CHANNELS: Final[frozenset[str]] = frozenset(
    {"interactive", "workspace", "workspace_xterm"}
)

# Sentinela para payload que chegou SEM reason. Nao e uma categoria semantica:
# e a admissao explicita de que o emissor nao informou o motivo.
REASON_UNSPECIFIED: Final[str] = "UNSPECIFIED"

# Enum estavel de reason. Os seis primeiros sao os RECOVERY_REASONS do
# `recovery_prompt.py`; NO_VERDICT e deliberadamente nao-recuperavel; EARLY_EXIT
# vem do scanner de chunk fatal.
REASONS: Final[frozenset[str]] = frozenset(
    {
        "BLOCKED",
        "RESSALVAS",
        "VERIFY_FAILED",
        "EXIT_NONZERO",
        "MISSING_ARG",
        "TIMEOUT",
        "NO_VERDICT",
        "EARLY_EXIT",
        REASON_UNSPECIFIED,
    }
)

# Valores historicos que NUNCA foram reason semantico. `notify` era o default do
# payload do listener quando o campo vinha vazio (ver 10.1.5 do estudo).
_REASON_ALIASES_VAZIOS: Final[frozenset[str]] = frozenset({"notify", "", "none", "null"})

_CLASSE_POR_REASON: Final[dict[str, str]] = {
    "BLOCKED": "semantic",
    "RESSALVAS": "semantic",
    "VERIFY_FAILED": "semantic",
    "NO_VERDICT": "semantic",
    "MISSING_ARG": "semantic",
    "EXIT_NONZERO": "process",
    "EARLY_EXIT": "process",
    "TIMEOUT": "infrastructure",
    REASON_UNSPECIFIED: "unknown",
}

# Slash-command canonico: uma barra so, sem path, sem args.
_SLASH_CMD = re.compile(r"^/[A-Za-z0-9][A-Za-z0-9:_-]{0,63}$")
# Token nu aceitavel (nome de binario). Sem barra, sem '=', sem '~', sem aspas.
_TOKEN_NU = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class FailureEventError(ValueError):
    """Envelope invalido. Erro do emissor, nao do corpus."""


def normalize_reason(raw: Any) -> str:
    """Mapeia o reason bruto para o enum estavel.

    `notify`, vazio e nulo colapsam em `UNSPECIFIED`: sao a mesma coisa - o
    emissor nao disse o motivo. Reason desconhecido tambem vira `UNSPECIFIED`,
    porque um enum que aceita qualquer string nao e enum.
    """
    if raw is None:
        return REASON_UNSPECIFIED
    texto = str(raw).strip()
    if texto.lower() in _REASON_ALIASES_VAZIOS:
        return REASON_UNSPECIFIED
    if texto in REASONS:
        return texto
    return REASON_UNSPECIFIED


def classify(reason: str, source: str) -> str:
    """Deriva `failure_class` do par (reason, source).

    A falha de uma tentativa de recuperacao e classe `recovery`, qualquer que
    seja o reason: o que interessa medir ali e que o remendo automatico nao
    pegou, nao o sintoma original.
    """
    if source == "recovery":
        return "recovery"
    return _CLASSE_POR_REASON.get(reason, "unknown")


def sanitize_command_name(raw: Any) -> str | None:
    """Extrai o nome canonico do comando. Devolve None quando nao da para
    extrair NADA seguro.

    Regra: slash-command inteiro, ou o primeiro token nu. Nunca mais que isso.
    Um path como `/home/pedro/deploy.sh` casa "comeca com barra" mas tem duas
    barras: e recusado, porque path e dado sensivel e porque `/home` nao e nome
    de comando. Devolver None e melhor que devolver um fragmento errado: campo
    vazio e honesto, campo com lixo contamina a agregacao.
    """
    if raw is None:
        return None
    texto = str(raw).strip()
    if not texto:
        return None
    primeira = texto.splitlines()[0].strip()
    if not primeira:
        return None
    head = primeira.split()[0]
    # `--flag` colado ao inicio, redirecionamento, env inline: nada disso e nome.
    if head.startswith(("-", "~", "$", "<", ">", "|")):
        return None
    if "=" in head or '"' in head or "'" in head or "\\" in head:
        return None
    if head.startswith("/"):
        if head.count("/") > 1:
            return None  # path, nao slash-command
        return head if _SLASH_CMD.match(head) else None
    return head if _TOKEN_NU.match(head) else None


def _nullable_str(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _nullable_int(valor: Any) -> int | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _nullable_float(valor: Any) -> float | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        convertido = float(valor)
    except (TypeError, ValueError):
        return None
    return convertido if convertido >= 0 else None


def build_failure_event(
    *,
    channel: str,
    reason: Any,
    source: str = "listener",
    failure_class: str | None = None,
    run_id: Any = None,
    item_id: Any = None,
    raw_command: Any = None,
    exit_code: Any = None,
    duration_seconds: Any = None,
    ts: float | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Monta o envelope. Levanta `FailureEventError` em channel/source/classe
    fora do enum - erro de emissor precisa aparecer, nao virar linha torta no
    corpus."""
    if channel not in CHANNELS:
        raise FailureEventError(f"channel fora do enum: {channel!r}")
    if source not in SOURCES:
        raise FailureEventError(f"source fora do enum: {source!r}")

    reason_norm = normalize_reason(reason)
    classe = failure_class or classify(reason_norm, source)
    if classe not in FAILURE_CLASSES:
        raise FailureEventError(f"failure_class fora do enum: {classe!r}")

    momento = time.time() if ts is None else float(ts)
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id or uuid.uuid4().hex,
        # `ts` continua epoch UTC: o classificador de contaminacao
        # (ai-forge/scripts/classify-wf-failures-contamination.py) rejeita
        # registro com ts nao numerico, e quebrar o consumidor para ganhar
        # legibilidade seria trocar dado por estetica. `ts_iso` acompanha.
        "ts": momento,
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(momento)),
        "source": source,
        "failure_class": classe,
        "reason": reason_norm,
        "channel": channel,
        "command_name": sanitize_command_name(raw_command),
        "run_id": _nullable_str(run_id),
        "item_id": _nullable_str(item_id),
        "exit_code": _nullable_int(exit_code),
        "duration_seconds": _nullable_float(duration_seconds),
    }


#: Campos que TODO evento carrega preenchidos (nunca None).
CAMPOS_OBRIGATORIOS: Final[tuple[str, ...]] = (
    "schema_version",
    "event_id",
    "ts",
    "source",
    "failure_class",
    "reason",
    "channel",
)

#: Campos deliberadamente nullable: so aparecem quando observados.
CAMPOS_NULLABLE: Final[tuple[str, ...]] = (
    "command_name",
    "run_id",
    "item_id",
    "exit_code",
    "duration_seconds",
)
