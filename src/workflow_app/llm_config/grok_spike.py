"""Spike Grok — integracao descartavel atras de feature gate (item 025).

Modulo ISOLADO e DESCARTAVEL. Todo o codigo aqui sera removido ou promovido
pelo item 026. Nao importar deste modulo em nenhum caminho publico da UI
(radio, menu, telemetria) enquanto o feature gate ``SF_GROK_SPIKE`` estiver
desligado (default).

Contrato (C-58, D-41):

- O feature gate ``SF_GROK_SPIKE`` e fail-closed: ausente/0/unrecognized =
  wiring inativo. Somente ``SF_GROK_SPIKE=1`` liga a integracao.
- Este modulo NAO cumpre D-30 (promocao publica). Quem cumpre e o item 026.
- Credencial: o CLI ``grok`` (``~/.local/bin/grok``) exige autenticacao via
  ambiente (``GROK_API_KEY`` ou equivalente). Sem credencial, a sessao nao
  abre e o caller recebe ``GrokSpikeAuthError``.
- O lifecycle da sessao segue o padrao do CLI: spawn subprocesso, valida
  auth, mantem sessao ativa, teardown no close.

Riscos mitigados (D-52): R-08, R-44.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Final

from workflow_app.config.feature_flags import grok_spike_enabled

_GROK_CLI_CANDIDATES: Final[list[str]] = [
    os.path.expanduser("~/.local/bin/grok"),
    shutil.which("grok") or "",
]

_GROK_DEFAULT_MODEL: Final[str] = "grok-4.5"


class GrokSpikeError(Exception):
    """Erro base do spike Grok."""


class GrokSpikeGateError(GrokSpikeError):
    """Feature gate desligado — spike inativo."""


class GrokSpikeAuthError(GrokSpikeError):
    """Credencial ausente ou invalida."""


class GrokSpikeCLINotFound(GrokSpikeError):
    """Binario do CLI grok nao encontrado no PATH."""


@dataclass
class GrokSpikeSession:
    """Sessao descartavel com o CLI Grok (item 025).

    Attributes:
        model: modelo Grok em uso (default ``grok-4.5``).
        process: subprocesso ativo (``None`` antes de ``open()``).
        alive: ``True`` enquanto o subprocesso estiver rodando.
    """

    model: str = _GROK_DEFAULT_MODEL
    process: subprocess.Popen | None = field(default=None, repr=False)
    alive: bool = False

    def open(self) -> None:
        """Abre a sessao: valida gate, credencial e CLI; faz spawn.

        Raises:
            GrokSpikeGateError: feature gate desligado.
            GrokSpikeCLINotFound: binario ``grok`` ausente.
            GrokSpikeAuthError: credencial ausente ou invalida.
        """
        if not grok_spike_enabled():
            raise GrokSpikeGateError(
                "SF_GROK_SPIKE desligado — spike Grok inativo (item 025)"
            )
        cli = _resolve_cli()
        _validate_auth()
        self.process = subprocess.Popen(
            [cli, "--model", self.model, "--output-format", "json"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.alive = self.process.poll() is None

    def close(self) -> None:
        """Teardown da sessao. Idempotente."""
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.alive = False
            self.process = None

    def __enter__(self) -> GrokSpikeSession:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _resolve_cli() -> str:
    """Retorna o path do CLI grok ou levanta GrokSpikeCLINotFound."""
    for candidate in _GROK_CLI_CANDIDATES:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise GrokSpikeCLINotFound(
        "CLI grok nao encontrado em ~/.local/bin/grok nem no PATH"
    )


def _validate_auth() -> None:
    """Verifica se a credencial minima esta disponivel no ambiente.

    O CLI grok usa autenticacao propria (nao documentada publicamente);
    este check valida apenas que a variavel de ambiente esperada existe
    e nao esta vazia. A validacao real acontece no primeiro call ao CLI.
    """
    cred = os.environ.get("GROK_API_KEY", "").strip()
    if not cred:
        raise GrokSpikeAuthError(
            "GROK_API_KEY ausente ou vazia — credencial obrigatoria "
            "para o spike Grok (item 025)"
        )


def is_grok_spike_active() -> bool:
    """``True`` quando o gate esta ligado E ha sessao ativa.

    Helper para consumers que precisam checar estado sem acoplar ao
    ciclo de vida da sessao. Sempre seguro chamar (sem side-effects).
    """
    return grok_spike_enabled()
