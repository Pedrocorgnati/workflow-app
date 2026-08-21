"""Testes de integracao do spike Grok (item 025).

Marker ``grok_live``: estes testes exigem credencial real (``GROK_API_KEY``)
e o CLI ``grok`` instalado. Sem credencial, o teste falha com ``BLOCKED``
explicito — skip NAO conta como aprovacao (C-58, G6).

Aceite:
    cd ai-forge/workflow-app && QT_QPA_PLATFORM=offscreen python -m pytest \\
      tests/integration/test_grok_spike.py -m grok_live --no-cov -q
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import workflow_app.llm_config.grok_spike as grok_spike
from workflow_app.config.feature_flags import grok_spike_enabled
from workflow_app.llm_config.grok_spike import (
    GrokSpikeAuthError,
    GrokSpikeCLINotFound,
    GrokSpikeGateError,
    GrokSpikeSession,
    _env_with_cli_on_path,
    _resolve_cli,
    _validate_auth,
)


def _has_grok_credentials() -> bool:
    return bool(os.environ.get("GROK_API_KEY", "").strip())


def _has_grok_cli() -> bool:
    for candidate in [os.path.expanduser("~/.local/bin/grok"), shutil.which("grok") or ""]:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return True
    return False


# ── Auth e credential checks ─────────────────────────────────────────────────


class TestGrokSpikeAuth:
    """Validacao de autenticacao e credencial do spike Grok."""

    def test_auth_raises_without_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sem GROK_API_KEY, _validate_auth levanta GrokSpikeAuthError."""
        monkeypatch.delenv("GROK_API_KEY", raising=False)
        with pytest.raises(GrokSpikeAuthError, match="GROK_API_KEY ausente"):
            _validate_auth()

    def test_auth_raises_with_empty_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GROK_API_KEY vazia conta como ausente."""
        monkeypatch.setenv("GROK_API_KEY", "   ")
        with pytest.raises(GrokSpikeAuthError, match="GROK_API_KEY ausente"):
            _validate_auth()

    def test_auth_passes_with_valid_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GROK_API_KEY presente e nao-vazia nao levanta."""
        monkeypatch.setenv("GROK_API_KEY", "test-key-spike-025")
        _validate_auth()  # nao levanta


# ── Feature gate checks ──────────────────────────────────────────────────────


class TestGrokSpikeGate:
    """Feature gate SF_GROK_SPIKE controla o spike."""

    def test_gate_disabled_blocks_session_open(self) -> None:
        """Com gate desligado (default), open() levanta GrokSpikeGateError."""
        if grok_spike_enabled():
            pytest.skip("SF_GROK_SPIKE=1 no ambiente — gate ligado")
        session = GrokSpikeSession()
        with pytest.raises(GrokSpikeGateError, match="SF_GROK_SPIKE desligado"):
            session.open()

    def test_is_grok_spike_active_reflects_gate(self) -> None:
        """is_grok_spike_active() espelha o estado do gate."""
        from workflow_app.llm_config.grok_spike import is_grok_spike_active

        assert is_grok_spike_active() == grok_spike_enabled()


# ── CLI resolution ───────────────────────────────────────────────────────────


class TestGrokSpikeCLI:
    """Resolucao do binario do CLI grok."""

    def test_cli_not_found_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sem binario no PATH nem em ~/.local/bin, levanta GrokSpikeCLINotFound."""
        monkeypatch.setattr(
            "workflow_app.llm_config.grok_spike._GROK_CLI_CANDIDATES", []
        )
        with pytest.raises(GrokSpikeCLINotFound, match="nao encontrado"):
            _resolve_cli()

    def test_resolved_cli_dir_is_prepended_to_path(self) -> None:
        """CLI fora do PATH: o diretorio resolvido entra no PATH do subprocesso.

        Regressao do finding do item 009: ``_resolve_cli()`` aceita
        ``~/.local/bin/grok`` mesmo fora do PATH, enquanto o adapter resolve por
        ``shutil.which("grok")``. Sem a normalizacao as duas resolucoes divergem.
        """
        env = {"PATH": "/usr/bin:/bin"}
        patched = _env_with_cli_on_path(env, "/home/someone/.local/bin/grok")
        assert patched["PATH"].split(os.pathsep)[0] == "/home/someone/.local/bin"
        assert "/usr/bin" in patched["PATH"].split(os.pathsep)
        assert env["PATH"] == "/usr/bin:/bin", "env de entrada nao pode ser mutado"

    def test_path_untouched_when_cli_dir_already_present(self) -> None:
        """CLI ja no PATH: nenhuma copia nem reordenacao do PATH."""
        env = {"PATH": "/usr/local/bin:/usr/bin"}
        patched = _env_with_cli_on_path(env, "/usr/local/bin/grok")
        assert patched is env
        assert patched["PATH"] == "/usr/local/bin:/usr/bin"

    def test_session_and_adapter_use_same_cli_when_local_bin_is_outside_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Spike, adapter e runner convergem para o executavel ja validado."""
        local_bin = tmp_path / ".local" / "bin"
        local_bin.mkdir(parents=True)
        fake_cli = local_bin / "grok"
        fake_cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_cli.chmod(0o755)

        empty_path = tmp_path / "empty-path"
        empty_path.mkdir()
        monkeypatch.setenv("PATH", str(empty_path))
        monkeypatch.setenv("GROK_API_KEY", "test-key-boundary")
        monkeypatch.setattr(grok_spike, "_GROK_CLI_CANDIDATES", [str(fake_cli)])
        monkeypatch.setattr(grok_spike, "grok_spike_enabled", lambda: True)

        captured: dict[str, object] = {}

        def capture_transport(spec, *, cwd, timeout, env, runner=None):
            captured.update(spec=spec, cwd=cwd, timeout=timeout, env=dict(env))
            return {"ok": True, "terminal": "ok"}

        monkeypatch.setattr(grok_spike._kernel, "run_provider", capture_transport)

        resolved = _resolve_cli()
        session = GrokSpikeSession()
        session.open()
        try:
            spec = captured["spec"]
            runner_env = captured["env"]
            assert resolved == str(fake_cli)
            assert spec.command[0] == resolved
            assert str(local_bin) not in str(empty_path).split(os.pathsep)
            assert runner_env["PATH"].split(os.pathsep).count(str(local_bin)) == 1
            assert shutil.which("grok", path=runner_env["PATH"]) == resolved
            assert os.environ["PATH"] == str(empty_path)
        finally:
            session.close()


# ── Live integration (exige credencial) ──────────────────────────────────────


@pytest.mark.grok_live
class TestGrokSpikeLive:
    """Testes que exigem credencial real e CLI instalado.

    Pre-requisito ausente produz BLOCKED explicito (nunca skip como aprovacao).
    """

    def test_live_auth_and_session_lifecycle(self) -> None:
        """Autenticacao + lifecycle da sessao com credencial real.

        BLOCKED se GROK_API_KEY ausente ou CLI grok nao instalado.
        """
        if not _has_grok_credentials():
            pytest.fail(
                "BLOCKED: GROK_API_KEY ausente — credencial obrigatoria "
                "para teste grok_live (item 025). Skip nao conta como aprovacao."
            )
        if not _has_grok_cli():
            pytest.fail(
                "BLOCKED: CLI grok nao encontrado — instale em "
                "~/.local/bin/grok ou adicione ao PATH (item 025)."
            )
        if not grok_spike_enabled():
            pytest.fail(
                "BLOCKED: SF_GROK_SPIKE desligado — exporte "
                "SF_GROK_SPIKE=1 para ativar o spike (item 025)."
            )
        session = GrokSpikeSession()
        try:
            session.open()
            assert session.alive is True
            assert session.process is not None
            assert session.process.poll() is None
        finally:
            session.close()
        assert session.alive is False
        assert session.process is None

    def test_live_session_context_manager(self) -> None:
        """Context manager abre e fecha a sessao corretamente."""
        if not _has_grok_credentials():
            pytest.fail("BLOCKED: GROK_API_KEY ausente (item 025)")
        if not _has_grok_cli():
            pytest.fail("BLOCKED: CLI grok nao encontrado (item 025)")
        if not grok_spike_enabled():
            pytest.fail("BLOCKED: SF_GROK_SPIKE desligado (item 025)")
        with GrokSpikeSession() as session:
            assert session.alive is True
        assert session.alive is False
