"""
TailscaleDetector — Discovers the local Tailscale IP via subprocess.

Runs 'tailscale ip -4' with a 5s timeout.
Returns a TailscaleResult dataclass with success status, IP, or error message.

Platform support:
- Windows: tries 'tailscale.exe' first, then 'tailscale'
- Linux / macOS: tries 'tailscale'
"""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TailscaleResult:
    """Result of a Tailscale IP detection attempt.

    Fields:
        success: True when a valid Tailscale IP was found.
        ip:      Tailscale IPv4 address (e.g. "100.100.10.5") when success=True; "" otherwise.
        error:   Human-readable error message in Portuguese when success=False; "" otherwise.
    """

    success: bool
    ip: str
    error: str


class TailscaleDetector:
    """Detects the local Tailscale IP address via the 'tailscale ip -4' command.

    Usage::

        result = TailscaleDetector().detect()
        if result.success:
            print(result.ip)    # "100.x.x.x"
        else:
            print(result.error) # human-readable error in Portuguese

    Invariant: detect() NEVER raises an exception — all errors are wrapped in TailscaleResult.
    """

    def detect(self) -> TailscaleResult:
        """Run 'tailscale ip -4' and return the detected IP or a structured error."""
        for binary in self._get_candidates():
            try:
                result = subprocess.run(
                    [binary, "ip", "-4"],
                    timeout=5,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                continue  # try next candidate
            except subprocess.TimeoutExpired:
                return self._timeout_error()

            if result.returncode != 0:
                return self._inactive_error()

            ip = result.stdout.strip()
            logger.debug("TailscaleDetector: IP detectado = %s", ip)
            return TailscaleResult(success=True, ip=ip, error="")

        return self._not_found_error()

    def _get_candidates(self) -> list[str]:
        """Return binary names to try, ordered by platform preference."""
        if platform.system() == "Windows":
            return ["tailscale.exe", "tailscale"]
        return ["tailscale"]

    def _not_found_error(self) -> TailscaleResult:
        msg = "Tailscale não encontrado. Instale em https://tailscale.com"
        logger.error("TailscaleDetector: %s", msg)
        return TailscaleResult(success=False, ip="", error=msg)

    def _inactive_error(self) -> TailscaleResult:
        msg = "Tailscale não está conectado. Execute 'tailscale up'"
        logger.error("TailscaleDetector: %s", msg)
        return TailscaleResult(success=False, ip="", error=msg)

    def _timeout_error(self) -> TailscaleResult:
        msg = "Timeout ao detectar IP Tailscale (5s). Verifique o serviço."
        logger.error("TailscaleDetector: %s", msg)
        return TailscaleResult(success=False, ip="", error=msg)
