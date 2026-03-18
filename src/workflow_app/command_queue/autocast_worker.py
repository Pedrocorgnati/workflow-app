"""
AutocastWorker — Subprocess runner for autocast AUTO commands.

Runs ``{binary} -p "{cmd} {config_path}"`` via the user's login shell so
shell aliases (e.g. ``clauded`` = ``claude --dangerously-skip-permissions``)
are resolved correctly.  Uses ``$SHELL -i -c`` so aliases defined in
``.zshrc``/``.bashrc`` are available without requiring a PATH binary.

Streams stdout to the output panel and emits ``finished`` when done.
"""
from __future__ import annotations

import logging
import os
import subprocess

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class AutocastWorker(QThread):
    """Runs a single AUTO command out-of-band and signals completion."""

    output_chunk = Signal(str)   # stdout line to display
    finished = Signal(bool)      # True = exit code 0, False = non-zero / error

    def __init__(
        self,
        binary: str,
        command: str,
        config_path: str,
        cwd: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._binary = binary
        self._command = command
        self._config_path = config_path
        self._cwd = cwd

    # ── QThread entry point ─────────────────────────────────────────── #

    def run(self) -> None:
        prompt_parts = [self._command]
        if self._config_path:
            prompt_parts.append(self._config_path)
        prompt = " ".join(prompt_parts)

        # Build the shell command string.  Escape any double-quotes inside
        # the prompt so the -p "..." argument is passed intact.
        escaped_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"')
        shell_cmd = f'{self._binary} -p "{escaped_prompt}"'

        # Run through the login shell so aliases (e.g. clauded) are resolved.
        shell = os.environ.get("SHELL", "/bin/bash")

        logger.info(
            "[AutocastWorker] %s -i -c %r (cwd=%s)", shell, shell_cmd, self._cwd
        )

        try:
            proc = subprocess.Popen(
                [shell, "-i", "-c", shell_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,   # never read from the user's terminal
                text=True,
                cwd=self._cwd,
            )
            # Stream output line by line
            for line in proc.stdout:  # type: ignore[union-attr]
                self.output_chunk.emit(line)
            proc.wait()
            success = proc.returncode == 0
            logger.info("[AutocastWorker] %r exited rc=%d", self._command, proc.returncode)
            self.finished.emit(success)
        except Exception as exc:  # noqa: BLE001
            msg = f"[Autocast] Erro ao executar '{self._command}': {exc}\n"
            logger.error("[AutocastWorker] %s", msg.strip())
            self.output_chunk.emit(msg)
            self.finished.emit(False)
