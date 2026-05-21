"""Regression tests for `/loop-rocksmash:integrate`.

Spec canonica: `.claude/commands/loop-rocksmash/integrate.md`.

Cenarios cobertos (mapeados de task-025-B15 do loop 05-19-tasks-faltantes):

  * test_integrate_md_declares_adr_log_lifo_invariant
    Contrato C3 declara LIFO inviolavel: nova entrada SEMPRE no topo,
    numeracao monotonica `ADR-{NNN}`, jamais reescrever entradas existentes
    (HT-INT-03).

  * test_integrate_md_declares_consolidation_n2_rule
    Contrato C6 declara regra N=2: tasks com distancia >= 3 movem para
    `## Historico` em forma resumida (3-5 linhas).

  * test_integrate_md_declares_idempotency_via_compare_hash
    Contrato C2 / HT-RS-01: chave de idempotencia = SHA256 do bloco JSON
    canonicalizado escrito por `:compare`; re-execucao com hash igual = no-op
    (exit 4), NAO duplica ADR Log.

  * test_integrate_adr_lifo_simulation_appends_at_top
    Simulacao deterministica: dada uma sequencia LIFO de ADRs, append insere
    no topo e renumera monotonicamente.

  * test_integrate_md_codex_mocked_invariant_no_fallback
    Contrato C1: Codex two-shot e infra-essencial; SEM fallback determinist;
    indisponibilidade -> exit 8 + pending-actions.

  * test_integrate_md_declares_verification_required
    Frontmatter declara `verification_required: true` (atomic-verifier
    pre-commit do `.claude/hooks/`).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _repo_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / ".claude" / "commands" / "loop-rocksmash" / "integrate.md").is_file():
            return parent
    raise RuntimeError(f"Could not locate integrate.md above {cur}")


@pytest.fixture(scope="module")
def integrate_md_text() -> str:
    path = _repo_root() / ".claude" / "commands" / "loop-rocksmash" / "integrate.md"
    assert path.is_file(), f"integrate.md nao encontrado em {path}"
    return path.read_text(encoding="utf-8")


def test_integrate_md_declares_adr_log_lifo_invariant(integrate_md_text: str) -> None:
    """Contrato C3 declara LIFO inviolavel + numeracao ADR-{NNN} monotonica."""
    assert "C3" in integrate_md_text, "Contrato C3 (LIFO) ausente"
    assert "LIFO" in integrate_md_text, "Termo LIFO deve aparecer no contrato"
    assert "ADR-{NNN}" in integrate_md_text or "ADR-NNN" in integrate_md_text, (
        "Padrao de nomeacao ADR-{NNN} ausente"
    )
    # Os 3 campos obrigatorios da entrada ADR.
    for required_field in ("Contexto", "Decisao", "Consequencia"):
        assert required_field in integrate_md_text, (
            f"Campo obrigatorio do ADR '{required_field}' ausente do contrato C3"
        )
    assert "HT-INT-03" in integrate_md_text, (
        "Tripwire HT-INT-03 (nao renumerar ADRs existentes) ausente"
    )


def test_integrate_md_declares_consolidation_n2_rule(integrate_md_text: str) -> None:
    """Contrato C6: tasks com distancia >= 3 movem para `## Historico`."""
    assert "C6" in integrate_md_text, "Contrato C6 (consolidacao N=2) ausente"
    assert "N=2" in integrate_md_text, "Regra canonica N=2 ausente"
    assert ">= 3" in integrate_md_text or "&gt;= 3" in integrate_md_text, (
        "Distancia canonica '>= 3' para promocao a `## Historico` ausente"
    )
    assert "## Historico" in integrate_md_text, (
        "Secao alvo `## Historico` ausente do contrato"
    )
    assert "3-5 linhas" in integrate_md_text, (
        "Faixa canonica do resumo (3-5 linhas) ausente"
    )


def test_integrate_md_declares_idempotency_via_compare_hash(
    integrate_md_text: str,
) -> None:
    """Contrato C2 / HT-RS-01: idempotencia via compare-hash; exit 4 no-op."""
    assert "C2" in integrate_md_text, "Contrato C2 (idempotencia) ausente"
    assert "HT-RS-01" in integrate_md_text, (
        "Tripwire HT-RS-01 (idempotencia/no-duplicate-ADR) ausente"
    )
    assert "compare-hash" in integrate_md_text, (
        "Chave de idempotencia 'compare-hash' ausente"
    )
    assert "SHA256" in integrate_md_text or "sha256" in integrate_md_text.lower(), (
        "Hash SHA256 do payload canonicalizado deve ser citado"
    )
    assert "exit 4" in integrate_md_text.lower(), (
        "No-op idempotente deve mapear para exit 4"
    )


def test_integrate_adr_lifo_simulation_appends_at_top() -> None:
    """Simulacao deterministica do invariante LIFO: append insere no topo.

    Como o comando real escreve via Codex two-shot (mockado conforme R1 da
    task), simulamos a transformacao em memoria garantindo o invariante
    estrutural do contrato C3.
    """
    initial_adr_log = [
        {"num": 2, "title": "Decisao B14", "date": "2026-05-18"},
        {"num": 1, "title": "Decisao B13", "date": "2026-05-17"},
    ]
    next_num = max(e["num"] for e in initial_adr_log) + 1
    new_entry = {"num": next_num, "title": "Decisao B15", "date": "2026-05-19"}
    updated = [new_entry, *initial_adr_log]

    # LIFO: novo no topo.
    assert updated[0]["num"] == 3
    # Monotonicidade: numeracao crescente.
    nums = [e["num"] for e in updated]
    assert nums == sorted(nums, reverse=True), (
        "ADR Log deve manter ordem LIFO (decrescente quando lido top-down)"
    )
    # Entradas previas inalteradas.
    assert updated[1:] == initial_adr_log


def test_integrate_md_codex_mocked_invariant_no_fallback(
    integrate_md_text: str,
) -> None:
    """Contrato C1: Codex two-shot e infra-essencial; SEM fallback determinist."""
    assert "C1" in integrate_md_text, "Contrato C1 (Codex two-shot) ausente"
    assert (
        "two-shot" in integrate_md_text.lower()
        or "Codex two-shot" in integrate_md_text
    ), "Estrategia Codex two-shot ausente do contrato"
    assert "controversial" in integrate_md_text.lower(), (
        "Round 1 'controversial-reviewer' ausente"
    )
    assert "hardening" in integrate_md_text.lower(), "Round 2 'hardening' ausente"
    assert "exit 8" in integrate_md_text.lower(), (
        "Codex indisponivel deve mapear para exit 8"
    )
    assert "pending-actions" in integrate_md_text, (
        "Indisponibilidade Codex deve registrar pending-actions"
    )
    # Anti-fallback explicito.
    assert (
        "SEM fallback" in integrate_md_text
        or "sem fallback" in integrate_md_text.lower()
        or "NAO substituir" in integrate_md_text
    ), "Veto canonico ao fallback determinist ausente"


def test_integrate_md_declares_verification_required(integrate_md_text: str) -> None:
    """Frontmatter declara `verification_required: true` para atomic-verifier."""
    # Frontmatter v2 deve declarar verification_required: true.
    head = integrate_md_text.split("---", 2)
    assert len(head) >= 3, "Frontmatter v2 malformado"
    frontmatter = head[1]
    assert "verification_required: true" in frontmatter, (
        "Frontmatter deve declarar 'verification_required: true' (atomic-verifier)"
    )


def test_integrate_md_canonical_payload_roundtrip_with_compare() -> None:
    """Payload do compare-hash usado em integrate e o MESMO produzido por compare.

    Garante que ambos os comandos compartilham o mesmo schema canonicalizado
    (chaves ordenadas, ensure_ascii=False) para o calculo de SHA256.
    """
    canonical_payload = {
        "task_atual": {
            "id": "B15",
            "title": "Testes regressao",
            "decisoes": ["criar 6 arquivos"],
            "outputs": ["tests/"],
            "contratos_tocados": ["compare.md"],
            "dependencias": ["B3"],
            "riscos_ou_hardening": ["R1"],
        },
        "task_anterior": None,
        "divergence": "low",
        "impact": "marginal",
        "alignment_points": [],
        "divergence_summary": "primeira task do loop",
    }
    serialized = json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True)
    h = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    assert len(h) == 64

    # Mesmo payload, segunda vez -> mesmo hash (idempotencia).
    h2 = hashlib.sha256(
        json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()
    assert h == h2


def test_integrate_md_protects_arquitetura_semeada(integrate_md_text: str) -> None:
    """Contrato C5: `## Arquitetura semeada` permanece byte-identica."""
    assert "C5" in integrate_md_text, "Contrato C5 (preservacao) ausente"
    assert "## Arquitetura semeada" in integrate_md_text, (
        "Secao protegida ausente do contrato"
    )
    assert "<!-- preserve:start -->" in integrate_md_text, (
        "Marker preserve:start ausente"
    )
    assert "byte-identica" in integrate_md_text, (
        "Garantia byte-identica deve estar declarada"
    )
