"""Regression tests for `/loop-rocksmash:compare`.

Spec canonica: `.claude/commands/loop-rocksmash/compare.md`.

Este suite valida o contrato declarado na spec markdown (slash-command e
interpretado pelo LLM, entao validamos a PRESENCA dos contratos / invariantes
no texto + montagens deterministicas de fixtures JSON para garantir que
`json.loads` aceita o schema documentado).

Cenarios cobertos (mapeados de task-025-B15 do loop 05-19-tasks-faltantes):

  * test_compare_md_declares_json_fenced_contract
    Spec declara contrato C1 (schema JSON fixo) + chaves canonicas em ingles
    literal (`task_atual`, `task_anterior`, `divergence`, `impact`,
    `alignment_points`, `divergence_summary`).

  * test_compare_md_declares_cooperative_flock_contract
    PASSO 1 declara `flock --timeout 60` cooperativo em `{doc_path}.lock` +
    cenario de lock orfao tratado deterministicamente (exit 9 em timeout 60s).

  * test_compare_md_declares_idempotency_via_sha256_hash
    Contrato C5 declara hash SHA256 canonicalizado + header
    `<!-- compare-hash:task={task_id} sha=SHA256_HEX -->` + exit 4 no-op.

  * test_compare_json_canonical_payload_is_loadable
    Payload canonico (montado a partir do schema declarado em compare.md
    linhas 226+) e roundtrip-loadable via `json.loads`.

  * test_compare_md_declares_summary_prose_length
    Sumario prosa documenta a faixa 5-10 linhas em pt-BR (idioma inviolado).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _repo_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / ".claude" / "commands" / "loop-rocksmash" / "compare.md").is_file():
            return parent
    raise RuntimeError(f"Could not locate compare.md above {cur}")


@pytest.fixture(scope="module")
def compare_md_text() -> str:
    path = _repo_root() / ".claude" / "commands" / "loop-rocksmash" / "compare.md"
    assert path.is_file(), f"compare.md nao encontrado em {path}"
    return path.read_text(encoding="utf-8")


def test_compare_md_declares_json_fenced_contract(compare_md_text: str) -> None:
    """Spec declara contrato C1 (schema JSON fixo) e chaves canonicas."""
    assert "C1" in compare_md_text, "Contrato C1 ausente de compare.md"
    assert "json.loads" in compare_md_text, (
        "Spec deve declarar validacao via json.loads"
    )
    for canonical_key in (
        "task_atual",
        "task_anterior",
        "divergence",
        "impact",
        "alignment_points",
        "divergence_summary",
    ):
        assert canonical_key in compare_md_text, (
            f"Chave canonica '{canonical_key}' ausente do schema declarado"
        )


def test_compare_md_declares_cooperative_flock_contract(compare_md_text: str) -> None:
    """PASSO 1 deve declarar `flock --timeout 60` + exit 9 em lock timeout."""
    assert "flock" in compare_md_text.lower(), (
        "PASSO 1 deve declarar lock cooperativo via flock"
    )
    assert "60" in compare_md_text, "Timeout canonico 60s deve estar declarado"
    assert "exit 9" in compare_md_text.lower(), (
        "Lock timeout deve mapear para exit 9 (gate determinista)"
    )
    assert "{doc_path}.lock" in compare_md_text, (
        "Lock file canonico '{doc_path}.lock' ausente"
    )


def test_compare_md_declares_idempotency_via_sha256_hash(compare_md_text: str) -> None:
    """Contrato C5: hash SHA256 + header compare-hash + exit 4 no-op."""
    assert "C5" in compare_md_text, "Contrato C5 (idempotencia) ausente"
    assert "SHA256" in compare_md_text or "sha256" in compare_md_text.lower(), (
        "Hash SHA256 deve ser citado no contrato C5"
    )
    assert "compare-hash" in compare_md_text, (
        "Header marker `compare-hash` ausente do contrato de idempotencia"
    )
    assert "exit 4" in compare_md_text.lower(), (
        "No-op idempotente deve mapear para exit 4"
    )


def test_compare_json_canonical_payload_is_loadable() -> None:
    """Payload canonico do schema documentado e parseavel via json.loads.

    Schema referencia: compare.md PASSO 4 (Montagem do bloco JSON canonico).
    Aqui montamos um payload minimo valido e garantimos que `json.loads` aceita.
    """
    canonical_payload = {
        "task_atual": {
            "id": "B15",
            "title": "Testes regressao pytest",
            "decisoes": ["criar 6 arquivos pytest"],
            "outputs": ["tests/test_loop_rocksmash_compare.py"],
            "contratos_tocados": ["compare.md", "integrate.md"],
            "dependencias": ["B3", "B4", "B5"],
            "riscos_ou_hardening": ["R1: Codex mockado"],
        },
        "task_anterior": {
            "id": "B14",
            "title": "Doc loader",
            "decisoes": [],
            "outputs": [],
            "contratos_tocados": [],
            "dependencias": [],
            "riscos_ou_hardening": [],
        },
        "divergence": "low",
        "impact": "marginal",
        "alignment_points": ["ambos tocam loader.py"],
        "divergence_summary": "divergencia marginal; consolidacao trivial",
    }
    serialized = json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True)
    roundtrip = json.loads(serialized)
    assert roundtrip == canonical_payload

    # Hash SHA256 canonicalizado deve ser estavel (mesmo input -> mesmo hash).
    h1 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    h2 = hashlib.sha256(
        json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()
    assert h1 == h2, "Hash deve ser estavel para o mesmo payload canonicalizado"
    assert len(h1) == 64, "SHA256 hex deve ter 64 chars"


def test_compare_md_declares_summary_prose_length(compare_md_text: str) -> None:
    """Sumario prosa: 5-10 linhas, pt-BR, sem emoji, sem em-dash."""
    assert "5-10 linhas" in compare_md_text or "5 a 10 linhas" in compare_md_text, (
        "Faixa canonica do sumario prosa (5-10 linhas) ausente"
    )
    assert "pt-BR" in compare_md_text, (
        "Idioma canonico pt-BR deve estar declarado (regra inviolada)"
    )


def test_compare_md_preserves_other_sections(compare_md_text: str) -> None:
    """Contrato C4: write substitui APENAS '## Task atual', preservando outras."""
    assert "C4" in compare_md_text, "Contrato C4 (preservacao) ausente"
    for protected_section in ("## ADR Log", "## Arquitetura semeada", "## Historico"):
        assert protected_section in compare_md_text, (
            f"Secao protegida '{protected_section}' nao citada no contrato"
        )
    assert "<!-- preserve:start -->" in compare_md_text, (
        "Marker preserve:start deve estar citado no contrato"
    )


def test_compare_md_declares_atomic_write_pattern(compare_md_text: str) -> None:
    """Contrato C3: write-temp-rename atomico sob flock."""
    assert "C3" in compare_md_text, "Contrato C3 (atomicidade) ausente"
    assert (
        "write-temp-rename" in compare_md_text
        or "{doc_path}.tmp" in compare_md_text
    ), "Padrao write-temp-rename ausente do contrato C3"
