"""
Tests for IPValidator — module-2/TASK-2.

Covers all 6 BDD scenarios:
- IPs within 100.64.0.0/10 → True
- IPs outside the range → False
- Malformed strings → False (no exception)
- IPv6 addresses → False (no exception)
"""

from __future__ import annotations

import pytest

from workflow_app.remote.ip_validator import IPValidator


@pytest.mark.parametrize(
    "ip, expected",
    [
        # ── True: within Tailscale CGNAT range 100.64.0.0/10 ──────────────────
        ("100.64.0.1", True),       # first usable address in the range
        ("100.100.10.5", True),     # typical Tailscale IP (BDD Cenário 5)
        ("100.127.255.254", True),  # last usable address in 100.64.0.0/10
        ("100.64.0.0", True),       # network address (included by ip_address check)
        # ── False: outside the range (BDD Cenário 6) ──────────────────────────
        ("192.168.1.100", False),   # private LAN
        ("10.0.0.1", False),        # private LAN
        ("172.16.0.1", False),      # private LAN
        ("8.8.8.8", False),         # public internet
        ("100.128.0.0", False),     # just outside 100.64.0.0/10 upper bound
        ("100.63.255.255", False),  # just below 100.64.0.0/10 lower bound
        # ── False: malformed / invalid ────────────────────────────────────────
        ("not-an-ip", False),
        ("300.0.0.1", False),       # octet out of range
        ("", False),                # empty string
        ("abc", False),
        ("1.2.3.4.5", False),       # too many octets
        # ── False: IPv6 (Tailscale uses IPv4 CGNAT only) ──────────────────────
        ("::1", False),             # loopback IPv6
        ("2001:db8::1", False),     # documentation IPv6
        ("fe80::1", False),         # link-local IPv6
    ],
)
def test_validate(ip, expected):
    """Parametrised test for all BDD scenarios."""
    assert IPValidator().validate(ip) is expected


def test_validate_never_raises():
    """validate() must not raise any exception for any input."""
    validator = IPValidator()
    evil_inputs = [None, 123, [], {}, "  ", "\x00", "100.64.0.0/10"]

    for inp in evil_inputs:
        try:
            result = validator.validate(inp)  # type: ignore[arg-type]
            assert isinstance(result, bool)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"validate({inp!r}) raised {type(exc).__name__}: {exc}")


def test_tailscale_network_instantiated_once(monkeypatch):
    """_TAILSCALE_NETWORK is a module-level constant (not recreated per call)."""
    import workflow_app.remote.ip_validator as mod

    network_id = id(mod._TAILSCALE_NETWORK)
    # Call validate multiple times
    v = IPValidator()
    for _ in range(5):
        v.validate("100.64.0.1")

    # The module-level constant must not be replaced
    assert id(mod._TAILSCALE_NETWORK) == network_id
