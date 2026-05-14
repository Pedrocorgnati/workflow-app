"""Unit tests for the Gate 2 verbose error formatter
(`format_delivery_invalid_popup` in
`workflow_app.services.delivery_invalid_formatter`).

Loop 05-14-fix-dcp-build-button-pipeline-tasklist Task 004 (= source TASK-3) —
covers AC-004.1 (todos os erros), AC-004.2 (pt-BR), AC-004.3 (sugestao).

Tests target the pure formatter helper so the Qt event loop is not required.
Cenario 1 exercises a synthetic `ValidationError.errors()` JSON with 3 issues;
Cenario 2 covers the degraded path where `details` is missing (still anti
Zero Silencio).
"""

from __future__ import annotations

import json

from workflow_app.services.delivery_invalid_formatter import (
    format_delivery_invalid_popup,
    translate_pydantic_msg,
)


# ─── Cenario 1: 3 erros pydantic ──────────────────────────────────────────── #


def test_gate2_verbose_three_errors() -> None:
    """Popup body enumerates ALL pydantic errors + fix suggestion (AC-004.1, 3)."""
    details = json.dumps(
        [
            {
                "type": "literal_error",
                "loc": ["modules", "module-1-x", "module_type"],
                "msg": "Input should be 'crud', 'feature' or 'foundations'",
                "input": "feature",
            },
            {
                "type": "missing",
                "loc": ["skeleton", "sha256"],
                "msg": "Field required",
                "input": None,
            },
            {
                "type": "string_type",
                "loc": ["metadata", "schema_sha256"],
                "msg": "Input should be a valid string",
                "input": None,
            },
        ]
    )

    body, clipboard = format_delivery_invalid_popup(
        path="/tmp/wbs/delivery.json",
        error="schema validation failed (3 errors)",
        details=details,
    )

    # AC-004.1: all 3 errors shown (not truncated to the short summary).
    assert "Encontrados 3 erros" in body
    assert "modules.module-1-x.module_type" in body
    assert "skeleton.sha256" in body
    assert "metadata.schema_sha256" in body

    # AC-004.2: pt-BR translations applied; no emojis or em-dash.
    assert "campo obrigatorio" in body.lower()
    assert "string" in body.lower()
    assert "—" not in body  # em-dash forbidden in prose
    for ch in body:
        assert not (0x1F300 <= ord(ch) <= 0x1FAFF), f"emoji {ch!r} detected"

    # AC-004.3: fix suggestion always present.
    assert "/delivery:migrate" in body

    # Clipboard payload carries raw English msg + raw loc for bug reports.
    assert "Copiar erros" in clipboard
    assert "Input should be 'crud'" in clipboard
    assert "/delivery:migrate" in clipboard


# ─── Cenario 2: details ausentes (caminho degradado) ──────────────────────── #


def test_gate2_verbose_degraded_when_details_missing() -> None:
    """Without parsed details, body still carries error summary + fix (no Zero Silencio)."""
    body, clipboard = format_delivery_invalid_popup(
        path="/tmp/wbs/delivery.json",
        error="io error reading delivery.json: permission denied",
        details=None,
    )

    assert "permission denied" in body
    assert "/delivery:migrate" in body
    assert "/tmp/wbs/delivery.json" in body
    assert "indisponivel" in clipboard.lower()


# ─── Translation helper ──────────────────────────────────────────────────── #


def test_translate_pydantic_msg_known_phrases() -> None:
    assert translate_pydantic_msg("Field required") == "campo obrigatorio"
    assert "string" in translate_pydantic_msg("Input should be a valid string")
    assert "schema" in translate_pydantic_msg("Extra inputs are not permitted")
    # Unknown messages fall through verbatim.
    assert translate_pydantic_msg("Some new message") == "Some new message"
