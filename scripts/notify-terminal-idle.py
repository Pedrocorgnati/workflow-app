#!/usr/bin/env python3
"""Notify workflow-app that a terminal channel is now idle.

Call this at the end of a skill or command. The workflow-app reads the
file via QFileSystemWatcher and turns the channel's status dot green
immediately (authoritative idle path), holding it green via a per-channel
lock until the next command is dispatched or an external session starts.
A 30s safety-net TTL releases the lock if no other release event fires.

Usage:
    python3 notify-terminal-idle.py [interactive|workspace]

The channel defaults to "interactive" (Claude CLI terminal).

IPC mechanism: atomic file write via mkstemp + os.replace (never truncates
the live file mid-write, so QFileSystemWatcher always reads a complete JSON).
Separate files per channel eliminate cross-channel race conditions.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_DIR = Path.home() / ".workflow-app"
channel = sys.argv[1] if len(sys.argv) > 1 else "interactive"

if channel not in ("interactive", "workspace"):
    print(f"error: unknown channel {channel!r} — use 'interactive' or 'workspace'",
          file=sys.stderr)
    sys.exit(1)

# One file per channel — no cross-channel race condition.
NOTIFY_FILE = _DIR / f"terminal-notify-{channel}.json"

try:
    _DIR.mkdir(parents=True, exist_ok=True)
except OSError as exc:
    print(f"error: cannot create {_DIR}: {exc}", file=sys.stderr)
    sys.exit(1)

payload = json.dumps({
    "channel": channel,
    "state": "idle",
    "iat": time.time(),
    "exp": time.time() + 10.0,  # app must reject if now > exp (stale guard)
})

# Atomic write: mkstemp in same dir + os.replace (rename) so inotify only
# fires once the file is complete — never on a truncated intermediate state.
fd, tmp = tempfile.mkstemp(dir=_DIR, prefix=".tmp_notify_")
try:
    with os.fdopen(fd, "w") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, NOTIFY_FILE)
except Exception as exc:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    print(f"error: notify write failed: {exc}", file=sys.stderr)
    sys.exit(1)
