"""Helpers compartilhados entre suites pytest-qt.

Hardening T9 §6 do loop 05-21-implantation-tasklist-aba-brainstorm.
Centraliza a assertion canonica de "Codex blocking sem fallback silencioso"
para reuso em test_mcp_prompt_codex_blocking.py e variantes T7.
"""

from __future__ import annotations

from typing import Any


def assert_no_silent_fallback(
    mock_t1: Any,
    mock_t2: Any,
    toast_spy: Any,
    expected_toast_text: str,
) -> None:
    """Garante que Codex bloqueado nao caiu em fallback para Claude/Kimi.

    Validacoes:
    - `mock_t1.publish` (terminal Claude T1) NAO foi chamado.
    - `mock_t2.publish` (terminal Kimi T2) NAO foi chamado.
    - `toast_spy` (QSignalSpy ou similar com .count()/.at(idx)) recebeu pelo
      menos 1 emissao com o texto canonico esperado e nivel `"warning"`.

    O texto literal canonico vem de `_CODEX_TOAST_CANONICAL` no widget
    (§6.3:669 + §10.5:7 do mcp-flow-implantation.md). Validacao byte-a-byte
    impede regressao silenciosa do toast (tolerar mudanca textual via
    `in` mascara perda de auditoria).
    """
    mock_t1.publish.assert_not_called()
    mock_t2.publish.assert_not_called()
    assert toast_spy.count() >= 1, (
        "esperado pelo menos 1 emissao em toast_requested"
    )
    first = toast_spy.at(0)
    toast_text = first[0]
    toast_level = first[1]
    assert toast_text == expected_toast_text, (
        f"toast literal mismatch: {toast_text!r}"
    )
    assert toast_level == "warning", (
        f"toast level deveria ser 'warning', recebido {toast_level!r}"
    )
