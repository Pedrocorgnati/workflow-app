"""Sentinela: a suite NAO escreve na telemetria real de falhas (TASK 01).

Contexto (secao 10.1.5 de `blacksmith/brainstorm-mcp/08-24-systemforge-analise-
fluxo-loop.md`): 760 de 2.553 eventos do corte auditado de `.claude/wf-failures/`
sao ruido produzido por pytest, nao por producao. A correcao tem duas camadas:

1. `tests/conftest.py` arma `WF_BLOCK_REAL_FAILURE_TELEMETRY=1` no import;
2. `metrics_bar.real_failure_telemetry_blocked` recusa a raiz REAL do repo,
   resolvida a partir do modulo — monkeypatch de instancia nao a move.

Este arquivo e a prova: compara o conteudo do diretorio real antes e depois de
forcar uma falha de listener sem nenhum monkeypatch de caminho.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from workflow_app.metrics_bar import metrics_bar as mb_mod
from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.signal_bus import SignalBus


def _real_wf_failures_dir() -> Path | None:
    root = mb_mod._module_repo_root()
    if root is None:
        return None
    return root / ".claude" / "wf-failures"


def _snapshot(d: Path | None) -> dict[str, int]:
    """Nome -> tamanho de cada arquivo do diretorio (ausente = dict vazio)."""
    if d is None or not d.is_dir():
        return {}
    return {p.name: p.stat().st_size for p in sorted(d.iterdir()) if p.is_file()}


def test_guard_env_is_armed_by_conftest():
    assert os.environ.get(mb_mod.FAILURE_TELEMETRY_GUARD_ENV) == "1"


def test_real_root_is_refused_and_tmp_root_is_allowed(tmp_path):
    real = mb_mod._module_repo_root()
    assert real is not None, "raiz do repo nao resolvida a partir do modulo"
    assert mb_mod.real_failure_telemetry_blocked(real) is True
    assert mb_mod.real_failure_telemetry_blocked(tmp_path) is False
    assert mb_mod.real_failure_telemetry_blocked(None) is False


def test_forcing_failures_does_not_touch_real_wf_failures(qapp):
    """Sem monkeypatch nenhum: o diretorio real fica byte-a-byte igual."""
    d = _real_wf_failures_dir()
    before = _snapshot(d)

    bar = MetricsBar(SignalBus())
    for channel, reason in (
        ("interactive", "BLOCKED"),
        ("workspace", "EXIT_NONZERO"),
        ("worker", "RATE_LIMIT"),
    ):
        bar._append_failure_telemetry(channel, reason)

    after = _snapshot(d)
    assert after == before, (
        "a suite escreveu em .claude/wf-failures/ real; diferenca: "
        f"{set(after.items()) ^ set(before.items())}"
    )


def test_guard_disarmed_would_write_to_tmp(tmp_path, monkeypatch):
    """Prova que o guard nao e um no-op global: com raiz tmp, a linha e escrita."""
    bar = MetricsBar(SignalBus())
    monkeypatch.setattr(bar, "_repo_root_path", lambda: tmp_path)
    bar._append_failure_telemetry("interactive", "BLOCKED")
    files = list((tmp_path / ".claude" / "wf-failures").glob("*.jsonl"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8").strip() != ""


@pytest.mark.usefixtures("qapp")
def test_sentinel_detects_a_real_write_attempt(monkeypatch):
    """O sentinela falharia se alguem desarmasse a guarda: aqui a desarmamos de
    proposito e checamos que a funcao passa a AUTORIZAR a raiz real (sem, no
    entanto, escrever nada — so a decisao e exercitada)."""
    real = mb_mod._module_repo_root()
    monkeypatch.delenv(mb_mod.FAILURE_TELEMETRY_GUARD_ENV, raising=False)
    assert mb_mod.real_failure_telemetry_blocked(real) is False
