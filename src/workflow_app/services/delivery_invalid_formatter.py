"""Verbose formatter for `DeliveryInvalid` results surfaced by Gate 2 of
the DCP build pipeline.

Anti Zero Silencio (CLAUDE.md Tier 2): when `delivery.json` fails Pydantic
validation the operator must see ALL errors with pt-BR translations and a
fix suggestion. This module is pure (no Qt imports) so it can be unit
tested without an event loop.

Loop 05-14-fix-dcp-build-button-pipeline-tasklist item 004 (= source TASK-3).
"""

from __future__ import annotations

import json
from typing import Any

# Translation of recurring Pydantic v2 error messages to pt-BR. Keys are
# lowercase substrings matched against `err["msg"]`; the first hit wins so
# more specific entries come first. Unknown messages fall through verbatim
# (still pt-BR enough for the operator: pydantic uses short imperative
# English already). Keep this tuple short — it is a UX aid, not full i18n.
_PYDANTIC_MSG_PT_BR: tuple[tuple[str, str], ...] = (
    ("field required", "campo obrigatorio"),
    ("input should be a valid string", "valor deve ser string"),
    ("input should be a valid integer", "valor deve ser inteiro"),
    ("input should be a valid number", "valor deve ser numero"),
    ("input should be a valid boolean", "valor deve ser booleano"),
    ("input should be a valid datetime", "valor deve ser datetime ISO 8601"),
    ("extra inputs are not permitted", "campo nao reconhecido pelo schema"),
    ("input should be", "valor invalido"),  # generic Literal/Enum fallback
    ("value error", "erro de validacao"),
)

_FIX_FOOTER = (
    "Fix sugerido: rode `/delivery:migrate` no projeto "
    "(consulte `ai-forge/workflow-app/src/workflow_app/models/delivery.py` "
    "para o schema canonico) OU edite manualmente."
)


def translate_pydantic_msg(msg: str) -> str:
    """Best-effort pt-BR translation for a Pydantic error message."""
    if not msg:
        return ""
    lowered = msg.lower()
    for needle, translated in _PYDANTIC_MSG_PT_BR:
        if needle in lowered:
            tail = msg[lowered.find(needle) + len(needle):].strip()
            return f"{translated}{(': ' + tail) if tail else ''}"
    return msg


def format_delivery_invalid_popup(
    path: Any,
    error: str,
    details: str | None,
) -> tuple[str, str]:
    """Format the verbose Gate 2 popup body for a DeliveryInvalid result.

    Returns (display_text, clipboard_text):

    - display_text: human-readable pt-BR body to render in the QMessageBox.
      Enumerates each pydantic error with `loc` + translated `msg` + input
      preview (when input is a string shorter than 80 chars), followed by
      a fix suggestion footer.
    - clipboard_text: same content prefixed with a canonical header,
      suitable for pasting into a bug report. Keeps raw English msg + raw
      loc so the operator can diff against the schema definition.

    When `details` is missing or unparseable the body still carries the
    short error and the fix footer (never the legacy one-line message —
    that violates Zero Silencio).
    """
    path_str = str(path)

    errors: list[dict[str, Any]] = []
    if details:
        try:
            parsed = json.loads(details)
            if isinstance(parsed, list):
                errors = [e for e in parsed if isinstance(e, dict)]
        except (json.JSONDecodeError, TypeError):
            errors = []

    if not errors:
        body = (
            f"delivery.json invalido em:\n  {path_str}\n\n"
            f"Resumo: {error}\n\n"
            f"{_FIX_FOOTER}"
        )
        clipboard = (
            "Copiar erros - delivery.json invalido\n"
            f"Path: {path_str}\n"
            f"Resumo: {error}\n"
            f"Detalhes: (indisponivel)\n"
        )
        return body, clipboard

    lines: list[str] = [
        f"Encontrados {len(errors)} erros de schema em:",
        f"  {path_str}",
        "",
    ]
    clipboard_lines: list[str] = [
        "Copiar erros - delivery.json invalido",
        f"Path: {path_str}",
        f"Total: {len(errors)} erros",
        "",
    ]
    for idx, err in enumerate(errors, start=1):
        loc = err.get("loc") or []
        if isinstance(loc, (list, tuple)):
            loc_str = ".".join(str(seg) for seg in loc) if loc else "(raiz)"
        else:
            loc_str = str(loc)
        raw_msg = err.get("msg") or ""
        msg = translate_pydantic_msg(raw_msg)
        input_val = err.get("input")
        input_preview = ""
        if isinstance(input_val, str) and 0 < len(input_val) < 80:
            input_preview = f" (recebido: {input_val!r})"
        lines.append(f"{idx}. {loc_str} - {msg}{input_preview}")
        clipboard_lines.append(
            f"{idx}. loc={loc_str} | msg={raw_msg} | input={input_val!r}"
        )

    lines.extend(["", _FIX_FOOTER])
    clipboard_lines.extend(["", _FIX_FOOTER])
    return "\n".join(lines), "\n".join(clipboard_lines)


__all__ = [
    "format_delivery_invalid_popup",
    "translate_pydantic_msg",
]
