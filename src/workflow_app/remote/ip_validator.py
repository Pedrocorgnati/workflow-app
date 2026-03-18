"""
IPValidator — Validates peer IPs against the Tailscale CGNAT range.

Uses ipaddress.ip_network for precise subnet membership check.
The _TAILSCALE_NETWORK constant is instantiated once at module level for performance.

Security invariant: validate() NEVER raises an exception — returns False for any
invalid, malformed, or out-of-range input (including IPv6 addresses and empty strings).
"""

from __future__ import annotations

import ipaddress
import logging

logger = logging.getLogger(__name__)

# Tailscale CGNAT range — instantiated once at module level (not per call)
_TAILSCALE_NETWORK = ipaddress.ip_network("100.64.0.0/10")


class IPValidator:
    """Validates that a peer IP is within the Tailscale CGNAT range (100.64.0.0/10).

    Usage::

        if IPValidator().validate(peer_ip):
            accept_client()
        else:
            reject_with_1008()
    """

    def validate(self, ip: str) -> bool:
        """Return True if *ip* is within 100.64.0.0/10 (Tailscale CGNAT range).

        Returns False for:
        - IPs outside the range (e.g. 192.168.x.x, 10.x.x.x)
        - Malformed strings (e.g. "not-an-ip", "300.0.0.1")
        - Empty strings
        - IPv6 addresses (e.g. "::1") — Tailscale uses IPv4 CGNAT only

        Never raises ValueError or any other exception.
        """
        try:
            addr = ipaddress.ip_address(ip)
            result = addr in _TAILSCALE_NETWORK
            if not result:
                logger.warning(
                    "IPValidator: IP %s rejeitado (fora de 100.64.0.0/10)", ip
                )
            return result
        except ValueError:
            logger.warning("IPValidator: IP malformado '%s'", ip)
            return False
