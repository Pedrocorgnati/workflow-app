"""Per-process identity for the workflow-app.

A single module-level constant (APP_SESSION_ID) is generated once at import
time. Every subsystem that needs to isolate per-instance state imports from
here. The value is also injected into PTY subprocesses via WF_APP_SESSION_ID
so that external scripts (notify-terminal-idle.py called by wf-notify.sh)
know which instance's IPC directory to write to.

Format: "session-<pid>" — human-readable, unique per OS process, and
naturally GC-able: a ~/.workflow-app/session-<pid>/ directory whose PID
no longer exists is an orphan left by a previous run and is safe to remove.

Why NOT uuid4?
  PID is zero-dependency (os.getpid() always available), self-documenting
  in directory listings, and its lifetime matches the process exactly.
  UUID would require cleanup heuristics (age-based); PID just needs a
  `psutil.pid_exists()` check — or a plain `/proc/<pid>` stat on Linux.

Isolation contract:
  - MetricsBar uses APP_SESSION_ID as the subdirectory inside
    ~/.workflow-app/ for the three IPC notify JSON files.
  - OutputPanel and XtermOutputPanel inject WF_APP_SESSION_ID=<id> into
    the PTY environment so every Bash subprocess the embedded CLI starts
    (Claude in T1, Kimi in T2, Codex in T3) writes the notify payload to
    the correct instance subdirectory.
  - notify-terminal-idle.py reads WF_APP_SESSION_ID from env and resolves
    the target directory; it falls back to "session-default" when the var
    is absent (headless CI / manual invocation outside a PTY).
  - logger.py uses the PID directly in the log filename so that multiple
    instances write to distinct log files rather than interleaving into
    a shared rotating file that RotatingFileHandler cannot safely share
    across OS processes.
"""
import os

APP_SESSION_ID: str = f"session-{os.getpid()}"
