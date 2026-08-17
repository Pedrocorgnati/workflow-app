"""Loader do snapshot de capacidades provider (D-37, D-38).

Le **exclusivamente** o snapshot JSON (C-03), nunca os arquivos autorais
(C-01, provider-capabilities.yaml) em tempo de execucao.

Paths congelados no BASELINE.md Bloco 4:
  C-01: ai-forge/rules/provider-capabilities.yaml  (NUNCA aberto aqui)
  C-02: ai-forge/scripts/gen-provider-capability-matrix.py
  C-03: ai-forge/schemas/provider-capability-matrix.json

Contratos:
  - Cache por processo (singleton, lazy load).
  - Fail-closed: snapshot ausente ou dado nao mapeado = "indisponivel".
  - Motivo acionavel via get_failure_reason().
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DEFAULT_SNAPSHOT_PATH = REPO_ROOT / "ai-forge" / "schemas" / "provider-capability-matrix.json"
AUTHORIAL_PATH = REPO_ROOT / "ai-forge" / "rules" / "provider-capabilities.yaml"

_STATUS_DISPONIVEL = "disponivel"
_STATUS_INDISPONIVEL = "indisponivel"

_REASON_NONE = None
_REASON_SNAPSHOT_AUSENTE = "snapshot_ausente"
_REASON_NAO_MAPEADO = "nao_mapeado"


class ProviderCapabilityLoader:
    """Le snapshot de capacidades com cache por processo.

    NUNCA abre o arquivo autoral (C-01). Toda consulta nao mapeada
    retorna "indisponivel" (fail-closed).
    """

    def __init__(self, snapshot_path: Path | str | None = None) -> None:
        self._snapshot_path = Path(snapshot_path) if snapshot_path else DEFAULT_SNAPSHOT_PATH
        self._data: dict[str, Any] | None = None
        self._failure_reason: str | None = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        """Carrega o snapshot do disco. Thread-safe, chamado uma unica vez."""
        with self._lock:
            if self._data is not None:
                return
            try:
                raw = self._snapshot_path.read_text(encoding="utf-8")
                self._data = json.loads(raw)
                self._failure_reason = _REASON_NONE
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                self._data = {}
                self._failure_reason = _REASON_SNAPSHOT_AUSENTE

    def reload(self) -> None:
        """Forca recarregamento do snapshot (para testes ou apos atualizacao)."""
        with self._lock:
            self._data = None
            self._failure_reason = None
        self._load()

    def get_capability(
        self,
        command: str,
        provider: str,
        role: str,
        capability: str,
    ) -> str:
        """Retorna 'disponivel' ou 'indisponivel' para a consulta.

        Fail-closed: qualquer dado ausente ou snapshot indisponivel
        retorna _STATUS_INDISPONIVEL.
        """
        self._load()
        assert self._data is not None

        if self._failure_reason is not None:
            return _STATUS_INDISPONIVEL

        matrix = self._data.get("matrix")
        if not matrix:
            self._failure_reason = _REASON_SNAPSHOT_AUSENTE
            return _STATUS_INDISPONIVEL

        cmd_data = matrix.get(command)
        if cmd_data is None:
            self._failure_reason = _REASON_NAO_MAPEADO
            return _STATUS_INDISPONIVEL

        provider_data = cmd_data.get(provider)
        if provider_data is None:
            self._failure_reason = _REASON_NAO_MAPEADO
            return _STATUS_INDISPONIVEL

        role_data = provider_data.get(role)
        if role_data is None:
            self._failure_reason = _REASON_NAO_MAPEADO
            return _STATUS_INDISPONIVEL

        status = role_data.get(capability)
        if status is None:
            self._failure_reason = _REASON_NAO_MAPEADO
            return _STATUS_INDISPONIVEL

        if status == _STATUS_DISPONIVEL:
            self._failure_reason = _REASON_NONE
            return _STATUS_DISPONIVEL

        self._failure_reason = _REASON_NAO_MAPEADO
        return _STATUS_INDISPONIVEL

    def is_available(
        self,
        command: str,
        provider: str,
        role: str,
        capability: str,
    ) -> bool:
        """True somente quando get_capability retorna 'disponivel'.

        False em qualquer outro caso (fail-closed).
        """
        return self.get_capability(command, provider, role, capability) == _STATUS_DISPONIVEL

    def get_failure_reason(self) -> str | None:
        """Motivo do fail-closed quando aplicavel.

        None quando o snapshot esta carregado e a ultima consulta foi saudavel.
        """
        self._load()
        return self._failure_reason


_instance: ProviderCapabilityLoader | None = None
_instance_lock = threading.Lock()


def get_loader(snapshot_path: Path | str | None = None) -> ProviderCapabilityLoader:
    """Retorna o singleton do loader (cache por processo)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ProviderCapabilityLoader(snapshot_path)
    return _instance


def reset_singleton() -> None:
    """Reseta o singleton (apenas para testes)."""
    global _instance
    with _instance_lock:
        _instance = None
