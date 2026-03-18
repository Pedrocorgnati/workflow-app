"""
Tests for TailscaleDetector — module-2/TASK-2.

All tests mock subprocess.run to avoid requiring Tailscale installed.
Covers all 4 BDD scenarios: active, not found, inactive, timeout.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from workflow_app.remote.tailscale import TailscaleDetector, TailscaleResult

# ── Cenário 1: Tailscale ativo ─────────────────────────────────────────────────


def test_detect_tailscale_ativo():
    """BDD: Dado que Tailscale está instalado e ativo → retorna IP."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "100.100.10.5\n"

    with patch("subprocess.run", return_value=mock_result):
        result = TailscaleDetector().detect()

    assert result == TailscaleResult(success=True, ip="100.100.10.5", error="")


def test_detect_strips_whitespace():
    """IP com espaços/newlines é retornado sem eles."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "  100.64.0.1  \n"

    with patch("subprocess.run", return_value=mock_result):
        result = TailscaleDetector().detect()

    assert result.success is True
    assert result.ip == "100.64.0.1"


# ── Cenário 2: Tailscale não instalado ────────────────────────────────────────


def test_detect_nao_instalado():
    """BDD: Dado que 'tailscale' não existe no PATH → retorna erro com URL de instalação."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = TailscaleDetector().detect()

    assert result.success is False
    assert result.ip == ""
    assert "https://tailscale.com" in result.error


# ── Cenário 3: Tailscale inativo ─────────────────────────────────────────────


def test_detect_inativo():
    """BDD: Dado que Tailscale está instalado mas não conectado → retorna erro com instrução."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch("subprocess.run", return_value=mock_result):
        result = TailscaleDetector().detect()

    assert result.success is False
    assert result.ip == ""
    assert "tailscale up" in result.error


# ── Cenário 4: Timeout ────────────────────────────────────────────────────────


def test_detect_timeout():
    """BDD: Dado que o comando trava → retorna erro de timeout."""
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="tailscale", timeout=5),
    ):
        result = TailscaleDetector().detect()

    assert result.success is False
    assert result.ip == ""
    assert "Timeout" in result.error or "timeout" in result.error.lower()


# ── Cross-platform ────────────────────────────────────────────────────────────


def test_get_candidates_windows():
    """Em Windows, a lista inclui tailscale.exe antes de tailscale."""
    with patch("platform.system", return_value="Windows"):
        candidates = TailscaleDetector()._get_candidates()

    assert candidates[0] == "tailscale.exe"
    assert "tailscale" in candidates


def test_get_candidates_linux():
    """Em Linux, a lista contém apenas 'tailscale'."""
    with patch("platform.system", return_value="Linux"):
        candidates = TailscaleDetector()._get_candidates()

    assert candidates == ["tailscale"]


def test_detect_windows_fallback_to_tailscale():
    """Em Windows, se tailscale.exe falha com FileNotFoundError, tenta tailscale."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "100.64.0.2\n"

    call_count = 0

    def side_effect(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        if "tailscale.exe" in cmd[0]:
            raise FileNotFoundError
        return mock_result

    with patch("platform.system", return_value="Windows"), patch(
        "subprocess.run", side_effect=side_effect
    ):
        result = TailscaleDetector().detect()

    assert result.success is True
    assert result.ip == "100.64.0.2"


# ── Error messages are in Portuguese ─────────────────────────────────────────


def test_error_messages_not_empty():
    """Todos os cenários de erro retornam mensagem não-vazia."""
    detector = TailscaleDetector()
    for error_fn in [
        detector._not_found_error,
        detector._inactive_error,
        detector._timeout_error,
    ]:
        result = error_fn()
        assert result.success is False
        assert result.ip == ""
        assert len(result.error) > 0
