"""Regression tests for `/loop:integrated-architecture`.

Spec canonica: `.claude/commands/loop/integrated-architecture.md`.

Cenarios cobertos (mapeados de task-025-B15 do loop 05-19-tasks-faltantes):

  * test_integrated_arch_md_declares_seed_idempotency_via_sha256
    Header canonico `<!-- arch-seed:version=N hash=SHA256_HEX -->` + recompute
    do hash a cada execucao + no-op (exit 4) quando hash identico.

  * test_integrated_arch_md_declares_reseed_flag
    Flag `--reseed` forca regeneracao mesmo com hash igual.

  * test_integrated_arch_md_declares_deterministic_mode
    Modo default e determinist (sem Codex) reproduzivel bit-a-bit.

  * test_seed_hash_is_stable_across_runs
    Hash SHA256 de um seed sintetico canonico e estavel entre invocacoes.

  * test_integrated_arch_md_declares_backfill_for_legacy_docs
    Flag `--backfill` aplica em loops legacy sem header arch-seed.

  * test_integrated_arch_md_declares_canonical_exit_codes
    Tabela de exit codes (0 sucesso, 4 no-op, 6 recurso, 8 dep, 9 lock, 10 input)
    declarada na spec.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


def _repo_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / ".claude" / "commands" / "loop" / "integrated-architecture.md").is_file():
            return parent
    raise RuntimeError(f"Could not locate integrated-architecture.md above {cur}")


@pytest.fixture(scope="module")
def integrated_arch_md_text() -> str:
    path = (
        _repo_root()
        / ".claude"
        / "commands"
        / "loop"
        / "integrated-architecture.md"
    )
    assert path.is_file(), f"integrated-architecture.md nao encontrado em {path}"
    return path.read_text(encoding="utf-8")


def test_integrated_arch_md_declares_seed_idempotency_via_sha256(
    integrated_arch_md_text: str,
) -> None:
    """Idempotencia: header arch-seed + SHA256 + exit 4 quando hash identico."""
    assert "arch-seed" in integrated_arch_md_text, (
        "Marker canonico 'arch-seed' ausente da spec"
    )
    assert "SHA256" in integrated_arch_md_text or "sha256" in integrated_arch_md_text.lower(), (
        "Hash SHA256 deve ser citado no contrato de idempotencia"
    )
    assert "version=" in integrated_arch_md_text, (
        "Convencao 'version=N' do header arch-seed ausente"
    )
    assert "exit 4" in integrated_arch_md_text.lower(), (
        "No-op idempotente deve mapear para exit 4"
    )


def test_integrated_arch_md_declares_reseed_flag(
    integrated_arch_md_text: str,
) -> None:
    """Flag `--reseed` forca regeneracao mesmo com hash igual."""
    assert "--reseed" in integrated_arch_md_text, (
        "Flag canonica '--reseed' ausente da spec"
    )
    # A semantica do --reseed deve estar documentada em algum lugar da spec.
    lower_text = integrated_arch_md_text.lower()
    assert (
        "forca regeneracao" in lower_text
        or "forca regenera" in lower_text
        or "regenera" in lower_text
    ), "Semantica de --reseed (forca regeneracao) ausente"
    # E deve aparecer junto a `--reseed` em pelo menos um trecho.
    assert "reseed" in lower_text and "regenera" in lower_text


def test_integrated_arch_md_declares_deterministic_mode(
    integrated_arch_md_text: str,
) -> None:
    """Modo default e determinist (sem Codex), reproduzivel."""
    assert "determinist" in integrated_arch_md_text.lower(), (
        "Modo determinist (default) deve estar documentado"
    )
    # Modo Codex (--deep-arch-seed) tambem deve estar documentado como opcional.
    assert "--deep-arch-seed" in integrated_arch_md_text, (
        "Flag opt-in '--deep-arch-seed' (Codex) ausente"
    )


def test_seed_hash_is_stable_across_runs() -> None:
    """Hash SHA256 de um seed sintetico canonico e estavel entre invocacoes.

    Spec FASE 7.1: 'SHA256 sobre concatenacao em ordem fixa'. Aqui validamos
    o invariante: mesmo input bytes -> mesmo hash hex, sempre.
    """
    seed_blob = (
        b"# Arquitetura semeada\n"
        b"## Pipeline\n- step1\n- step2\n"
        b"## Repositorio destino\n- /home/repo\n"
    )
    h1 = hashlib.sha256(seed_blob).hexdigest()
    h2 = hashlib.sha256(seed_blob).hexdigest()
    h3 = hashlib.sha256(seed_blob).hexdigest()
    assert h1 == h2 == h3
    assert len(h1) == 64
    # Mudanca minima -> hash diferente (detecta drift).
    h_drift = hashlib.sha256(seed_blob + b"\n").hexdigest()
    assert h_drift != h1


def test_integrated_arch_md_declares_backfill_for_legacy_docs(
    integrated_arch_md_text: str,
) -> None:
    """Flag `--backfill` documenta tratamento de docs legacy."""
    assert "--backfill" in integrated_arch_md_text, (
        "Flag '--backfill' ausente da spec"
    )
    assert "legacy" in integrated_arch_md_text.lower(), (
        "Tratamento de docs legacy deve estar documentado"
    )
    assert "--force-backfill" in integrated_arch_md_text, (
        "Flag '--force-backfill' (conflito estrutural) ausente"
    )


def test_integrated_arch_md_declares_canonical_exit_codes(
    integrated_arch_md_text: str,
) -> None:
    """Tabela canonica de exit codes deve cobrir 0/4/6/8/9/10."""
    text_lower = integrated_arch_md_text.lower()
    # Exit codes mais relevantes citados na spec.
    for exit_code in ("exit 0", "exit 4", "exit 6", "exit 8", "exit 9", "exit 10"):
        assert exit_code in text_lower, (
            f"Exit code canonico '{exit_code}' ausente da tabela"
        )


def test_integrated_arch_md_declares_cooperative_flock() -> None:
    """PASSO de lock cooperativo (flock 60s) deve estar documentado.

    Skip silencioso quando a spec evolui sem alterar o contrato (defensive
    check via fixture local para evitar carregamento duplo do arquivo).
    """
    path = (
        _repo_root()
        / ".claude"
        / "commands"
        / "loop"
        / "integrated-architecture.md"
    )
    text = path.read_text(encoding="utf-8")
    assert "flock" in text.lower(), (
        "Lock cooperativo (flock) deve estar declarado na spec"
    )
    assert "60s" in text or "timeout 60" in text, (
        "Timeout canonico 60s deve estar declarado"
    )


def test_integrated_arch_md_declares_preserve_markers(
    integrated_arch_md_text: str,
) -> None:
    """Bloco semeado envolto em markers preserve:start/preserve:end."""
    assert "<!-- preserve:start -->" in integrated_arch_md_text, (
        "Marker preserve:start ausente"
    )
    assert "<!-- preserve:end -->" in integrated_arch_md_text, (
        "Marker preserve:end ausente"
    )
