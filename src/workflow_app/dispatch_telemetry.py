"""
Telemetria de dispatch — torna `sent=True` observavel em vez de otimista.

Motivacao (incidente 2026-08-24, `blacksmith/recovery/incidents/
20260824-pty-dispatch-swallowed-item-006/INCIDENT.md` §5). A fila marca um
item como `sent=True` assim que `_dispatch_green_arrow` retorna True, e esse
retorno acontece logo apos `signal_bus.run_command_in_terminal.emit(...)`.
`run_command_in_terminal` e um `Signal(str)`: nao carrega valor de retorno.
Nenhuma camada confirmava que os bytes chegaram ao PTY. Resultado pratico:
duas ocorrencias em que a fila afirmava ter despachado um comando que o
terminal nunca executou, e o log do app nao tinha UMA linha sobre o envio.

Este modulo fecha esse ponto cego registrando tres eventos correlacionados
por um `seq` monotonico:

1. `emit`      — a fila publicou o texto no sinal (quem, para qual canal).
2. `pty_write` — o `output_panel` escreveu no PTY (bytes pedidos x escritos).
3. `echo`      — o terminal ecoou o comando (confirmacao do lado de la).

Cada evento vai para o logger normal do app E para um sidecar JSONL
(`~/.workflow-app/logs/dispatch-telemetry-{pid}.jsonl`), porque o log
principal e um RotatingFileHandler de 5 MB x 5 e uma investigacao forense
nao pode depender de a evidencia nao ter rotacionado.

Nada aqui pode derrubar um dispatch: toda funcao e best-effort e engole as
proprias excecoes. Telemetria que quebra o caminho quente e pior que
telemetria ausente.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOG_DIR = Path.home() / ".workflow-app" / "logs"
_JSONL_PATH = _LOG_DIR / f"dispatch-telemetry-{os.getpid()}.jsonl"

# Texto de comando entra em log: mascarar por FORMATO (nunca por nome de
# chave). Mesmas classes que `pretool-bash-secrets.sh` bloqueia no Bash.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)

# Quanto do comando entra no registro. Suficiente para casar com a fila e com
# `_QUEUE-STATE.json`; curto o bastante para nao inchar o sidecar.
_MAX_COMMAND_CHARS = 240

_lock = threading.Lock()
_seq = 0

# Ultimo `emit` publicado por canal, aguardando o `pty_write` correspondente.
# A entrega de sinal Qt em conexao direta e sincrona e na mesma thread, entao
# o `pty_write` do texto X chega DENTRO do `emit` de X: um slot por canal
# basta, e a correlacao ainda e checada pelo texto.
_pending: dict[str, dict[str, Any]] = {}


def mask(text: str) -> str:
    """Mascara segredos por formato antes de qualquer persistencia."""
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("***", out)
    return out


def _short(command: str) -> str:
    masked = mask(command)
    if len(masked) <= _MAX_COMMAND_CHARS:
        return masked
    return masked[:_MAX_COMMAND_CHARS] + f"...(+{len(masked) - _MAX_COMMAND_CHARS})"


def command_head(command: str) -> str:
    """Primeiro token do comando (`/clear`, `/loop:iteraction:execute-task`)."""
    stripped = command.strip()
    if not stripped:
        return ""
    return mask(stripped.split(None, 1)[0])[:80]


def _write_jsonl(record: dict[str, Any]) -> None:
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _JSONL_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Sidecar indisponivel nao pode derrubar dispatch nem poluir o app.
        pass


def _emit_record(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = {
        "ts": time.time(),
        "monotonic": time.monotonic(),
        "pid": os.getpid(),
        "event": event,
        **payload,
    }
    _write_jsonl(record)
    return record


def open_dispatch(
    *,
    route: str,
    channel: str,
    command: str,
    position: int | None = None,
    after_clear: bool | None = None,
) -> int:
    """Registra a publicacao do comando no sinal. Retorna o `seq` do dispatch.

    Chamado pela command queue no instante em que ela publica — antes de o
    `output_panel` ver qualquer byte. E o evento que dava `sent=True` sem
    nenhuma prova.
    """
    global _seq
    try:
        with _lock:
            _seq += 1
            seq = _seq
            _pending[channel] = {
                "seq": seq,
                "command": command,
                "route": route,
                "opened_at": time.monotonic(),
            }
        head = command_head(command)
        logger.info(
            "[dispatch#%d] emit route=%s channel=%s head=%s chars=%d "
            "position=%s after_clear=%s cmd=%r",
            seq, route, channel, head, len(command), position, after_clear,
            _short(command),
        )
        _emit_record("emit", {
            "seq": seq,
            "route": route,
            "channel": channel,
            "head": head,
            "chars": len(command),
            "position": position,
            "after_clear": after_clear,
            "command": _short(command),
        })
        return seq
    except Exception:  # noqa: BLE001 — telemetria nunca derruba dispatch
        logger.debug("[dispatch] open_dispatch falhou", exc_info=True)
        return -1


def record_pty_write(
    *,
    channel: str,
    command: str,
    requested: int,
    written: int | None,
    bracketed: bool,
) -> int:
    """Registra a escrita real no PTY. Retorna o `seq` correlacionado (ou -1).

    `written` vem de `PersistentShell.send_raw`, que passou a devolver o
    total de bytes aceitos por `os.write`. O fd do master e O_NONBLOCK:
    escrita parcial e EAGAIN sao possiveis e ate hoje eram descartados em
    silencio. `written != requested` e exatamente a forma que um comando
    engolido teria no log.
    """
    try:
        with _lock:
            entry = _pending.get(channel)
            if entry is not None and entry.get("command") == command:
                seq = int(entry["seq"])
                route = entry.get("route", "?")
                _pending.pop(channel, None)
            else:
                # Escrita sem `emit` correspondente: rota imperativa
                # (inject no xterm, blue arrow, digitacao do operador).
                seq = -1
                route = "unattributed"
        head = command_head(command)
        short = written is not None and written != requested
        level = logging.WARNING if short else logging.INFO
        logger.log(
            level,
            "[dispatch#%s] pty_write channel=%s route=%s head=%s requested=%d "
            "written=%s bracketed=%s%s",
            seq, channel, route, head, requested, written, bracketed,
            "  << ESCRITA CURTA/FALHA NO PTY" if short else "",
        )
        _emit_record("pty_write", {
            "seq": seq,
            "channel": channel,
            "route": route,
            "head": head,
            "requested": requested,
            "written": written,
            "bracketed": bracketed,
            "short_write": short,
        })
        return seq
    except Exception:  # noqa: BLE001
        logger.debug("[dispatch] record_pty_write falhou", exc_info=True)
        return -1


def record_enter(
    *, channel: str, written: int | None, reason: str = "direct"
) -> None:
    """Registra o Enter submissor, que viaja como write separado.

    `reason` diz por que este `\r` saiu — `gated` (a tela ecoou o paste,
    caminho normal), `gate-timeout` (o eco nao apareceu dentro do teto e
    mandamos assim mesmo), `resend-N` (o comando continuava na linha de
    prompt depois do Enter anterior) ou `signal` (Enter avulso, pelos
    sinais `submit_enter_to_*`). Um `resend-*` recorrente e a assinatura
    de uma TUI engolindo submit — e o que o incidente do `/clear` colado
    junto do proximo item produzia em silencio.
    """
    try:
        logger.info(
            "[dispatch] enter channel=%s written=%s reason=%s",
            channel, written, reason,
        )
        _emit_record(
            "enter",
            {"channel": channel, "written": written, "reason": reason},
        )
    except Exception:  # noqa: BLE001
        logger.debug("[dispatch] record_enter falhou", exc_info=True)


def record_echo(
    *,
    seq: int,
    channel: str,
    command: str,
    echoed: bool | None,
    bytes_seen: int,
    elapsed_ms: int,
    helper: bool,
) -> None:
    """Registra a confirmacao do lado do terminal.

    `echoed=True` significa que um trecho distintivo do comando foi
    encontrado no buffer da tela depois do write. `False` significa que o
    terminal nao mostra o comando E nao produziu bytes — a assinatura do
    comando engolido. `None` significa que o comando nao tem token
    distintivo o bastante para decidir (`/clear`, `/model haiku`): registra
    sem acusar.
    """
    try:
        verdict = {True: "OK", False: "MISSING", None: "UNKNOWN"}[echoed]
        level = (
            logging.WARNING
            if (echoed is False and not helper and bytes_seen == 0)
            else logging.INFO
        )
        logger.log(
            level,
            "[dispatch#%s] echo=%s channel=%s head=%s bytes_seen=%d "
            "after_ms=%d helper=%s%s",
            seq, verdict, channel, command_head(command), bytes_seen,
            elapsed_ms, helper,
            "  << COMANDO ENGOLIDO: nada na tela e zero bytes do PTY"
            if (echoed is False and not helper and bytes_seen == 0) else "",
        )
        _emit_record("echo", {
            "seq": seq,
            "channel": channel,
            "head": command_head(command),
            "echo": verdict,
            "bytes_seen": bytes_seen,
            "elapsed_ms": elapsed_ms,
            "helper": helper,
        })
    except Exception:  # noqa: BLE001
        logger.debug("[dispatch] record_echo falhou", exc_info=True)


def jsonl_path() -> Path:
    """Path do sidecar desta instancia (usado em diagnostico e testes)."""
    return _JSONL_PATH


def _reset_for_tests() -> None:
    """Zera contador e pendencias. Uso exclusivo de teste."""
    global _seq
    with _lock:
        _seq = 0
        _pending.clear()
