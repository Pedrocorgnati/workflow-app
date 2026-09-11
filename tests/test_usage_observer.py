"""Task 33: parse de usage sem inventar zero."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from workflow_app.core.token_tracker import calculate_cost
from workflow_app.domain import ModelType
from workflow_app.telemetry.usage_observer import (
    encode_claude_project_dirname,
    observe_usage,
    parse_usage_from_claude_jsonl,
    parse_usage_from_text,
)


def test_json_usage_object() -> None:
    texto = '{"usage": {"input_tokens": 12, "output_tokens": 34}}'
    visto = parse_usage_from_text(texto)
    assert visto is not None
    assert visto.tokens_in == 12
    assert visto.tokens_out == 34
    assert visto.usage_tokens == 46


def test_cache_nao_entra_no_input_cobrado() -> None:
    texto = (
        '{"usage": {"input_tokens": 2, "output_tokens": 10,'
        ' "cache_read_input_tokens": 5, "cache_creation_input_tokens": 100}}'
    )
    visto = parse_usage_from_text(texto)
    assert visto is not None
    assert visto.tokens_in == 2
    assert visto.tokens_out == 10


def test_silencio_nao_e_zero() -> None:
    assert parse_usage_from_text("") is None
    assert parse_usage_from_text("comando ok") is None
    assert parse_usage_from_text('{"usage": {"input_tokens": 0, "output_tokens": 0}}') is None


def test_par_rotulado() -> None:
    visto = parse_usage_from_text("input 1,200 output 80")
    assert visto is not None
    assert visto.tokens_in == 1200
    assert visto.tokens_out == 80


def test_observe_usage_nao_consulta_jsonl_automatico(tmp_path: Path) -> None:
    pasta = tmp_path / encode_claude_project_dirname(Path("/tmp/demo"))
    pasta.mkdir(parents=True)
    (pasta / "a.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2030-01-01T00:00:00Z",
                "message": {"usage": {"input_tokens": 99, "output_tokens": 1}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert (
        observe_usage(
            terminal_text="",
            provider="claude",
            cwd=Path("/tmp/demo"),
            since_ts=0,
            claude_projects_root=tmp_path,
        )
        is None
    )


def test_observe_prefere_terminal() -> None:
    visto = observe_usage(
        terminal_text='{"usage": {"input_tokens": 3, "output_tokens": 4}}',
        provider="claude",
        cwd=Path("/tmp"),
        since_ts=0,
    )
    assert visto is not None
    assert visto.source == "terminal"


def test_encode_claude_project_dirname() -> None:
    nome = encode_claude_project_dirname(Path("/tmp/cafés-demo"))
    assert nome.startswith("-tmp-caf")
    assert "s-demo" in nome
    assert "é" not in nome


def test_jsonl_respeita_since(tmp_path: Path) -> None:
    pasta = tmp_path / encode_claude_project_dirname(Path("/tmp/demo"))
    pasta.mkdir(parents=True)
    antigo = {
        "type": "assistant",
        "timestamp": "2020-01-01T00:00:00Z",
        "message": {"usage": {"input_tokens": 999, "output_tokens": 1}},
    }
    novo = {
        "type": "assistant",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": {"usage": {"input_tokens": 7, "output_tokens": 8}},
    }
    (pasta / "a.jsonl").write_text(
        json.dumps(antigo) + "\n" + json.dumps(novo) + "\n", encoding="utf-8"
    )
    corte = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    visto = parse_usage_from_claude_jsonl(
        cwd=Path("/tmp/demo"),
        since_ts=corte,
        claude_projects_root=tmp_path,
    )
    assert visto is not None
    assert visto.tokens_in == 7
    assert visto.tokens_out == 8
    assert visto.source == "claude_jsonl"


def test_calculate_cost_nao_precisa_de_banco() -> None:
    custo = calculate_cost(1_000_000, 0, ModelType.SONNET)
    assert custo == 3.0
