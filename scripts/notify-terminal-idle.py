#!/usr/bin/env python3
"""Notify workflow-app of a terminal channel finalization event.

v2 contract (ai-forge/rules/workflow-app-listeners.md §2.3 + §9):

  - Aceita um payload completo via flags nomeadas:
      --channel  interactive | workspace | workspace_xterm
      --status   success | failure | awaiting_user
      --reason   (canonical enum quando status=failure; vazio caso contrario)
      --exit-code  int (default: 0 em success / awaiting_user, 1 em failure)
      --run-id     string opaca (default: ISO-8601 + pid)

  - `--status` e obrigatorio. O antigo atalho v1
    `notify-terminal-idle.py [channel]` foi desativado para impedir falso
    verde por fallback legado.

IPC: escrita IN-PLACE no mesmo inode (write-from-0 + ftruncate + fsync) em
`~/.workflow-app/<session>/terminal-notify-{channel}.json`. O subdiretorio
`<session>` e resolvido a partir de WF_APP_SESSION_ID (injetado no PTY pelo
app via PersistentShell.extra_env). Quando ausente (CI headless, invocacao
manual) usa "session-default". Um arquivo por canal por instancia — elimina
cross-instance contamination (bug: multiplas instancias abertas em paralelo
observando o mesmo arquivo e recebendo o recovery prompt umas das outras).
O app le via QFileSystemWatcher; a escrita in-place mantem o inode estavel
para que o inotify entregue IN_MODIFY de forma deterministica (mkstemp+
os.replace trocava o inode e o fileChanged era frequentemente engolido ->
dot preso amarelo; ver §15.6 de ai-forge/rules/workflow-app-listeners.md).
Leitura parcial e tratada no consumidor (try/except + dedup por run_id).

Payload escrito (v2):
    {
      "channel": "interactive",
      "state": "idle" | "failed" | "awaiting_user",
      "status": "success" | "failure" | "awaiting_user",
      "reason": "VERIFY_FAILED" | "" | ...,
      "exit_code": 0,
      "run_id": "2026-05-18T19-30-00Z-12345",
      "iat": 1734542400.0,
      "exp": 1734542410.0,
      "schema": 2
    }

Mapping `status -> state` (consumido por TerminalStatusDot):
    success         -> "idle"            (dot verde)
    failure         -> "failed"          (dot vermelho)
    awaiting_user   -> "awaiting_user"   (dot azul)

Consumers que leem apenas `state` continuam funcionando, desde que o emissor
use o contrato v2 explicito.

Exit codes:
    0  payload escrito
    1  args invalidos (channel/status desconhecido) ou erro de IO
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_SESSION_ID: str = os.environ.get("WF_APP_SESSION_ID", "session-default")
_DIR = Path.home() / ".workflow-app" / _SESSION_ID

_VALID_CHANNELS = ("interactive", "workspace", "workspace_xterm")
_VALID_STATUS = ("success", "failure", "awaiting_user")
_VALID_REASONS = (
    "VERIFY_FAILED", "BLOCKED", "RESSALVAS",
    "TIMEOUT", "EXIT_NONZERO", "MISSING_ARG",
)
_STATUS_TO_STATE = {
    "success": "idle",
    "failure": "failed",
    "awaiting_user": "awaiting_user",
}


def _notify_file_name(channel: str) -> str:
    """Return the IPC filename suffix used by MetricsBar watchers."""
    return channel.replace("_", "-")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse v2 flags. Status is required so success/failure is explicit."""
    parser = argparse.ArgumentParser(
        description="Notify workflow-app of a terminal channel event (v2).",
        add_help=True,
    )
    parser.add_argument("--channel", required=True, choices=_VALID_CHANNELS)
    parser.add_argument("--status", required=True, choices=_VALID_STATUS)
    parser.add_argument("--reason", default="")
    parser.add_argument("--exit-code", dest="exit_code", type=int, default=None)
    parser.add_argument("--run-id", dest="run_id", default="")
    args = parser.parse_args(argv)

    if args.status == "failure":
        if not args.reason:
            parser.error("--reason e obrigatorio quando --status=failure")
        if args.reason not in _VALID_REASONS:
            parser.error(
                f"--reason invalido '{args.reason}' "
                f"(esperado: {'|'.join(_VALID_REASONS)})"
            )
    else:
        # Em success/awaiting_user, reason fica vazio mesmo se passado.
        args.reason = ""

    if args.exit_code is None:
        args.exit_code = 1 if args.status == "failure" else 0

    if not args.run_id:
        args.run_id = (
            time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
            + f"-{os.getpid()}"
        )

    return args


def _inplace_write(path: Path, payload: str) -> None:
    """Escrita IN-PLACE no MESMO inode (write-from-0 + ftruncate + fsync).

    Antes usava mkstemp + os.replace (rename atomico). O rename TROCA o inode,
    e o QFileSystemWatcher (inotify) do app frequentemente ENGOLE o fileChanged
    resultante — surgindo so como directoryChanged, que tambem nao e 100%
    confiavel — deixando o dot do listener preso AMARELO apesar do payload
    correto em disco (ver ai-forge/rules/workflow-app-listeners.md §15.6;
    confirmado empiricamente em 2026-05-31: write os.replace nao verdejava o
    dot, write in-place no mesmo inode verdejava todas as vezes).

    Escrever in-place mantem o inode estavel, entao o inotify entrega IN_MODIFY
    no path observado de forma deterministica (caminho first-hand). A
    seguranca contra leitura parcial e garantida no consumidor (json.loads em
    try/except + dedup por run_id + reprocess por directoryChanged como
    backstop) e a janela e minima: um unico write() do payload pequeno, seguido
    de ftruncate para o tamanho exato (sem janela de tamanho-zero).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload.encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        written = 0
        while written < len(data):
            written += os.write(fd, data[written:])
        os.ftruncate(fd, len(data))  # remove cauda de um payload anterior maior
        os.fsync(fd)
    finally:
        os.close(fd)


def main(argv: list[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 1)

    # Correção defensiva: PTY é fonte de verdade do canal real
    pty_channel = os.environ.get("WF_CHANNEL_OVERRIDE", "")
    if pty_channel and pty_channel != args.channel:
        print(
            f"notify-terminal-idle: WARNING: canal divergente — "
            f"comando enviou '{args.channel}' mas PTY declara '{pty_channel}'. "
            f"Usando PTY.",
            file=sys.stderr,
        )
        args.channel = pty_channel

    now = time.time()
    state = _STATUS_TO_STATE[args.status]
    payload_dict = {
        "channel": args.channel,
        "state": state,
        "status": args.status,
        "reason": args.reason,
        "exit_code": args.exit_code,
        "run_id": args.run_id,
        "iat": now,
        "exp": now + 10.0,
        "schema": 2,
    }
    payload = json.dumps(payload_dict)

    target = _DIR / f"terminal-notify-{_notify_file_name(args.channel)}.json"
    try:
        _inplace_write(target, payload)
    except OSError as exc:
        print(f"error: notify write failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
