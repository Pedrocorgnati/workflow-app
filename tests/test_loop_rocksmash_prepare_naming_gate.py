"""Regression tests for gate RP-NAMING-01 in /loop-rocksmash:prepare.

O gate vive em `.claude/commands/loop-rocksmash/prepare.md` PASSO 1 (gate 8).
Como o slash-command e markdown interpretado pelo LLM, este suite valida a
PRESENCA do gate na spec via regex/substring checks. Garante que edits futuros
nao removam acidentalmente o gate.

Cenarios cobertos (mapeados de task-006 do loop
05-16-loop-rocksmash-prepare-accepts-incompatible):

  * test_prepare_md_declares_rp_naming_gate
    A spec declara o id `RP-NAMING-01` e a regex canonica
    `^task-\\d+(?:\\.\\d+)*-[a-z0-9-]+\\.md$`.

  * test_prepare_md_lists_naming_error_in_header
    O bloco "Casos de erro deterministas" enumera o caso de basename incompativel
    com exit 1.

  * test_prepare_md_excludes_archived_items_from_gate
    A spec menciona explicitamente que items com `archived: true` sao ignorados
    pelo gate (consistente com pseudo-codigo de task-004 fix-proposto).

  * test_prepare_md_references_precedent_loop
    A mensagem do gate cita o loop precedente que motivou o fix
    (05-16-loop-rocksmash-prepare-accepts-incompatible) para rastreabilidade.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _repo_root() -> Path:
    """Walk up ate achar a raiz do SystemForge (contem .claude/commands/loop-rocksmash/).

    Workflow-app e submodule e tem seu proprio .claude/ vazio; precisamos do
    repo pai onde os slash-commands canonicos do SystemForge vivem.
    """
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / ".claude" / "commands" / "loop-rocksmash" / "prepare.md").is_file():
            return parent
    raise RuntimeError(
        f"Could not locate .claude/commands/loop-rocksmash/prepare.md above {cur}"
    )


@pytest.fixture(scope="module")
def prepare_md_text() -> str:
    path = _repo_root() / ".claude" / "commands" / "loop-rocksmash" / "prepare.md"
    assert path.is_file(), f"prepare.md nao encontrado em {path}"
    return path.read_text(encoding="utf-8")


def test_prepare_md_declares_rp_naming_gate(prepare_md_text: str) -> None:
    """Gate id e regex canonica devem estar na spec."""
    assert "RP-NAMING-01" in prepare_md_text, (
        "Gate id 'RP-NAMING-01' ausente de prepare.md — regressao do fix de "
        "2026-05-17. Restaurar gate 8 do PASSO 1 conforme task-004 do loop "
        "05-16-loop-rocksmash-prepare-accepts-incompatible."
    )
    # Regex canonica do basename (pode aparecer escapada ou nao).
    canonical_regex_variants = [
        r"^task-\d+(?:\.\d+)*-[a-z0-9-]+\.md$",
        r"task-\\d+(?:\\.\\d+)*-[a-z0-9-]+\\.md",
    ]
    assert any(v in prepare_md_text for v in canonical_regex_variants), (
        "Regex canonica do basename ausente de prepare.md; esperado uma das: "
        f"{canonical_regex_variants}"
    )


def test_prepare_md_lists_naming_error_in_header(prepare_md_text: str) -> None:
    """Bloco 'Casos de erro deterministas' deve enumerar o caso do basename."""
    # O bloco header de erros deve conter o caso basename invalido.
    assert "Casos de erro deterministas" in prepare_md_text, (
        "Bloco 'Casos de erro deterministas' ausente — spec corrompida"
    )
    assert "basename" in prepare_md_text.lower(), (
        "Spec nao menciona 'basename' no contexto do gate naming"
    )
    # Exit code 1 declarado para esse caso.
    naming_section_start = prepare_md_text.find("RP-NAMING-01")
    naming_section = prepare_md_text[naming_section_start : naming_section_start + 1200]
    assert "exit 1" in naming_section.lower() or "Exit 1" in naming_section, (
        f"Gate RP-NAMING-01 deve declarar exit 1; trecho:\n{naming_section[:400]}"
    )


def test_prepare_md_excludes_archived_items_from_gate(prepare_md_text: str) -> None:
    """Items com archived: true devem ser IGNORADOS pelo gate naming.

    Pseudo-codigo de task-004 tem `if item.get('archived'): continue`. Sem este
    skip, loops parcialmente arquivados com naming legacy quebrariam.
    """
    naming_section_start = prepare_md_text.find("RP-NAMING-01")
    assert naming_section_start != -1, "RP-NAMING-01 ausente"
    naming_section = prepare_md_text[naming_section_start : naming_section_start + 1500]
    assert "archived" in naming_section.lower(), (
        "Gate RP-NAMING-01 deve mencionar tratamento de items archived "
        "(skip semantico); trecho:\n" + naming_section[:600]
    )


def test_prepare_md_references_precedent_loop(prepare_md_text: str) -> None:
    """Mensagem do gate cita loop precedente para rastreabilidade do fix."""
    # Precedente: loop 05-16-loop-rocksmash-prepare-accepts-incompatible.
    # Pode aparecer em qualquer trecho do PASSO 1 gate 8 (nao apenas no header).
    assert "05-16-loop-rocksmash-prepare-accepts-incompatible" in prepare_md_text, (
        "Gate deve citar loop precedente que motivou o fix para audit trail"
    )
