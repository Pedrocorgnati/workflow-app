#!/usr/bin/env python3
"""Notify workflow-app of a terminal channel finalization event.

v2 contract (ai-forge/rules/workflow-app-listeners.md §2.3 + §9):

  - Aceita um payload completo via flags nomeadas:
      --channel  interactive | workspace | workspace_xterm
      --status   success | failure | awaiting_user
      --reason   (canonical enum quando status=failure; vazio caso contrario)
      --exit-code  int (default: 0 em success / awaiting_user, 1 em failure)
      --run-id     string opaca (default: ISO-8601 + pid)

  - Retrocompat v1: invocacao `notify-terminal-idle.py [channel]` continua
    valida e e tratada como `--status success` (legacy success path).

IPC: atomic file write via mkstemp + os.replace na pasta `~/.workflow-app/`.
Um arquivo por canal (`terminal-notify-{channel}.json`) elimina race entre
canais. O app le via QFileSystemWatcher; o `mkstemp+os.replace` garante que
o watcher so dispare quando o arquivo esta completo.

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

Consumers v1 que so leem `state` continuam funcionando (success/v1 = idle).

Exit codes:
    0  payload escrito
    1  args invalidos (channel/status desconhecido) ou erro de IO
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_DIR = Path.home() / ".workflow-app"

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
    """Parse v2 flags; fall back to v1 positional channel when no flags given.

    v1 form (still accepted): `notify-terminal-idle.py interactive`
    """
    # v1 compat shortcut: exactly one positional, no flags.
    if len(argv) == 1 and not argv[0].startswith("-"):
        return argparse.Namespace(
            channel=argv[0],
            status="success",
            reason="",
            exit_code=0,
            run_id=f"v1-{int(time.time())}-{os.getpid()}",
        )

    parser = argparse.ArgumentParser(
        description="Notify workflow-app of a terminal channel event (v2).",
        add_help=True,
    )
    parser.add_argument("--channel", required=True, choices=_VALID_CHANNELS)
    parser.add_argument("--status", default="success", choices=_VALID_STATUS)
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


def _atomic_write(path: Path, payload: str) -> None:
    """mkstemp + os.replace na mesma pasta — inotify so dispara quando completo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_notify_")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 1)

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
        _atomic_write(target, payload)
    except OSError as exc:
        print(f"error: notify write failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
