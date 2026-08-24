"""Marcador de status desconhecido em PROGRESS.md bloqueia, nao some.

Contrato (fonte: 10.1.2, 10.2 I5 e 12.2.3 do estudo 08-24):
  - conjunto canonico FECHADO: `[x]` done, `[ ]` pending, `[!]` failed;
  - qualquer outro glifo vira `InvalidMarker` e levanta `InvalidMarkerError`;
  - o glifo desconhecido NUNCA e convertido para status canonico;
  - o caso real observado no corpus e `[~]` (uma ocorrencia).
"""

from __future__ import annotations

import pytest

from workflow_app.daily_loop.loader import (
    DailyLoopConfigError,
    InvalidMarkerError,
    parse_progress_items,
    parse_progress_items_loop,
    scan_progress_invalid_markers,
    scan_progress_invalid_markers_loop,
)

# Tres status canonicos + um invalid_marker (13.1, linha Corpus).
PROGRESS_TRES_STATUS_MAIS_INVALIDO = """# Progress: fixture-invalid-marker
Modo: --task
Total: 4 items | Done: 1 | Pending: 1 | Failed: 1

## Items

| ID  | Status | Target | Bucket | Updated |
|-----|--------|--------|--------|---------|
| 001 | [x]    | tasks/items/task-001.md | T-opus-high | 2026-08-01T00:00:00Z |
| 002 | [ ]    | tasks/items/task-002.md | T-opus-high | -       |
| 003 | [!]    | tasks/items/task-003.md | T-opus-high | 2026-08-01T01:00:00Z |
| 004 | [~]    | tasks/items/task-004.md | T-opus-high | -       |
"""

PROGRESS_SO_CANONICOS = """| ID  | Status | Target | Bucket | Updated |
|-----|--------|--------|--------|---------|
| 001 | [x]    | a.md | T-opus-high | - |
| 002 | [ ]    | b.md | T-opus-high | - |
| 003 | [!]    | c.md | T-opus-high | - |
"""

PARSERS = [
    pytest.param(parse_progress_items, scan_progress_invalid_markers, id="daily"),
    pytest.param(
        parse_progress_items_loop, scan_progress_invalid_markers_loop, id="loop"
    ),
]


@pytest.mark.parametrize("parse, scan", PARSERS)
def test_marcador_desconhecido_levanta_erro_explicito(parse, scan):
    with pytest.raises(InvalidMarkerError) as exc:
        parse(PROGRESS_TRES_STATUS_MAIS_INVALIDO)
    markers = exc.value.markers
    assert [m.item_id for m in markers] == ["004"]
    assert [m.glyph for m in markers] == ["~"]
    assert markers[0].line_no == 12
    assert "[~]" in markers[0].raw_line


@pytest.mark.parametrize("parse, scan", PARSERS)
def test_erro_e_subclasse_do_erro_de_config(parse, scan):
    # Callers antigos capturam DailyLoopConfigError; o bloqueio novo cai la.
    with pytest.raises(DailyLoopConfigError):
        parse(PROGRESS_TRES_STATUS_MAIS_INVALIDO)


@pytest.mark.parametrize("parse, scan", PARSERS)
def test_status_canonicos_continuam_aceitos(parse, scan):
    items = parse(PROGRESS_SO_CANONICOS)
    assert [i.status for i in items] == ["done", "pending", "failed"]
    assert scan(PROGRESS_SO_CANONICOS) == []


@pytest.mark.parametrize("parse, scan", PARSERS)
def test_invalido_nao_vira_status_canonico(parse, scan):
    # strict=False e a porta do auditor/preview: o item some da fila, mas a
    # trilha continua disponivel. Em nenhum dos dois caminhos ele vira pending.
    items = parse(PROGRESS_TRES_STATUS_MAIS_INVALIDO, strict=False)
    assert [i.item_id for i in items] == ["001", "002", "003"]
    assert "004" not in {i.item_id for i in items}
    assert [i.status for i in items] == ["done", "pending", "failed"]
    trail = scan(PROGRESS_TRES_STATUS_MAIS_INVALIDO)
    assert [(m.item_id, m.glyph) for m in trail] == [("004", "~")]


@pytest.mark.parametrize("parse, scan", PARSERS)
def test_prosa_e_cabecalho_continuam_ignorados(parse, scan):
    ruido = (
        "# Progress\n"
        "Modo: --task\n"
        "| ID | Status | Target | Bucket |\n"
        "|---|---|---|---|\n"
        "texto livre com [x] no meio\n"
        "| nota | sem forma de item |\n"
    )
    assert scan(ruido) == []
    assert parse(ruido) == []


@pytest.mark.parametrize("parse, scan", PARSERS)
def test_multiplos_invalidos_sao_todos_reportados(parse, scan):
    txt = (
        "| ID  | Status | Target | Bucket |\n"
        "|-----|--------|--------|--------|\n"
        "| 001 | [?]    | a.md | T-opus-high |\n"
        "| 002 | [x]    | b.md | T-opus-high |\n"
        "| 003 | [~]    | c.md | T-opus-high |\n"
    )
    with pytest.raises(InvalidMarkerError) as exc:
        parse(txt)
    assert [(m.item_id, m.glyph) for m in exc.value.markers] == [
        ("001", "?"),
        ("003", "~"),
    ]
    assert "Marcadores canonicos" in str(exc.value)
