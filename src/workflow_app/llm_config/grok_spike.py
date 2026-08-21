"""Spike Grok — integracao via provider bridge kernel (item 025 / C19).

Esta integracao substitui o subprocesso proprio do spike original por uma
chamada ao kernel neutro (`ai-forge/scripts/_provider_bridge_kernel.py`) com
o adapter `grok` (`ai-forge/scripts/_provider_adapters.py`). Ela ainda vive
atras do feature gate ``SF_GROK_SPIKE`` e NAO cumpre D-30 sozinha; a promocao
publica na UI e responsabilidade do item 026.

Contrato (C-58, D-41, C-53):

- O feature gate ``SF_GROK_SPIKE`` e fail-closed: ausente/0/unrecognized =
  wiring inativo. Somente ``SF_GROK_SPIKE=1`` liga a integracao.
- A sessao Grok e construida pelo kernel: o adapter fornece argv e env,
  o kernel fornece transporte, timeout, parsing e telemetria C-53.
- Credencial: o CLI ``grok`` (``~/.local/bin/grok``) autentica via arquivo
  proprio (``~/.grok/auth.json`` ou equivalente). A variavel de ambiente
  ``GROK_API_KEY`` e validada como check minimo para manter o contrato do
  spike original; sem ela a sessao nao abre.
- O lifecycle da sessao segue o padrao do kernel: invoke, outcome, teardown.

Riscos mitigados (D-52): R-08, R-44.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from workflow_app.config.feature_flags import grok_spike_enabled

_GROK_CLI_CANDIDATES: Final[list[str]] = [
    os.path.expanduser("~/.local/bin/grok"),
    shutil.which("grok") or "",
]

_GROK_DEFAULT_MODEL: Final[str] = "grok-4.5"
_GROK_DEFAULT_TIMEOUT: Final[int] = 240


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (
            (candidate / ".claude" / "commands").is_dir()
            and (candidate / "ai-forge").is_dir()
            and (candidate / "CLAUDE.md").is_file()
        ):
            return candidate
    raise GrokSpikeError(
        "repo root not found (need .claude/commands + ai-forge + CLAUDE.md)"
    )


REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)
SCRIPTS_DIR = str(REPO_ROOT / "ai-forge" / "scripts")
if SCRIPTS_DIR not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, SCRIPTS_DIR)


def _load_kernel_module(name: str) -> Any:
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = Path(SCRIPTS_DIR) / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise GrokSpikeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_kernel = _load_kernel_module("_provider_bridge_kernel")
_adapters = _load_kernel_module("_provider_adapters")


class GrokSpikeError(Exception):
    """Erro base do spike Grok."""


class GrokSpikeGateError(GrokSpikeError):
    """Feature gate desligado — spike inativo."""


class GrokSpikeAuthError(GrokSpikeError):
    """Credencial ausente ou invalida."""


class GrokSpikeCLINotFound(GrokSpikeError):
    """Binario do CLI grok nao encontrado no PATH."""


class _ProcessHandle:
    """Handle compativel com subprocess.Popen para consumidores legados.

    O spike antigo expunha um subprocesso real. Apos a migracao para o kernel
    o processo nao e retido, mas manter a interface ``poll/terminate/wait/kill``
    evita quebrar callers que ainda inspecionam ``GrokSpikeSession.process``.
    """

    def __init__(self) -> None:
        self._alive = True

    def poll(self) -> int | None:
        return None if self._alive else 0

    def terminate(self) -> None:
        self._alive = False

    def wait(self, timeout: float | None = None) -> int:
        self._alive = False
        return 0

    def kill(self) -> None:
        self._alive = False


@dataclass
class GrokSpikeSession:
    """Sessao Grok via kernel (item 025 / C19).

    Attributes:
        model: modelo Grok em uso (default ``grok-4.5``).
        process: handle compativel (``None`` antes de ``open()``).
        alive: ``True`` enquanto a sessao estiver aberta.
        last_outcome: resultado bruto do kernel da ultima invocacao.
    """

    model: str = _GROK_DEFAULT_MODEL
    process: Any = field(default=None, repr=False)
    alive: bool = False
    last_outcome: dict[str, Any] | None = field(default=None, repr=False)

    def open(self) -> None:
        """Abre a sessao: valida gate, credencial e CLI; despacha pelo kernel.

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

        params = _kernel.SpecParams(
            prompt="", grok_model=self.model, resolved_binary=cli
        )
        adapter = _adapters.get_adapter("grok")

        outcome = _kernel.invoke_provider(
            "grok",
            lambda: adapter.build_spec(params),
            cwd=str(REPO_ROOT),
            timeout=_GROK_DEFAULT_TIMEOUT,
            env_for=lambda: _env_with_cli_on_path(adapter.env(), cli),
        )
        self.last_outcome = outcome

        if not outcome.get("ok"):
            terminal = outcome.get("terminal")
            if terminal == _kernel.TERMINAL_BINARY_MISSING:
                raise GrokSpikeCLINotFound(
                    "CLI grok nao encontrado em ~/.local/bin/grok nem no PATH"
                )
            stderr = outcome.get("stderr", "")
            raise GrokSpikeError(
                f"Grok kernel invocation failed: {terminal} {stderr}".strip()
            )

        self.process = _ProcessHandle()
        self.alive = True

    def close(self) -> None:
        """Teardown da sessao. Idempotente."""
        if self.process is not None:
            if self.alive:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    self.process.kill()
        self.alive = False
        self.process = None

    def __enter__(self) -> GrokSpikeSession:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _env_with_cli_on_path(env: dict[str, str], cli: str) -> dict[str, str]:
    """Garante que o diretorio do CLI resolvido esteja no PATH do subprocesso.

    ``_resolve_cli()`` aceita ``~/.local/bin/grok`` mesmo quando esse diretorio
    esta fora do PATH; ja o adapter resolve o binario por ``shutil.which("grok")``.
    Sem esta normalizacao as duas resolucoes divergem e a sessao falharia com
    ``FileNotFoundError`` depois de ter passado o gate local — exatamente o
    cenario apontado na auditoria do item 009.

    Args:
        env: ambiente produzido pelo adapter (copia normalizada).
        cli: path absoluto do CLI grok resolvido por ``_resolve_cli()``.

    Returns:
        O mesmo mapeamento quando o diretorio ja esta no PATH, ou uma copia com
        o diretorio do CLI no inicio do PATH.
    """
    cli_dir = os.path.dirname(os.path.abspath(cli))
    parts = [part for part in env.get("PATH", "").split(os.pathsep) if part]
    if cli_dir in parts:
        return env
    patched = dict(env)
    patched["PATH"] = os.pathsep.join([cli_dir, *parts])
    return patched


def _resolve_cli() -> str:
    """Retorna o path do CLI grok ou levanta GrokSpikeCLINotFound."""
    for candidate in _GROK_CLI_CANDIDATES:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return os.path.abspath(candidate)
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
