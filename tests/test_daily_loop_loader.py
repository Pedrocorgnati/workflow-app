"""Regression tests for ``workflow_app.daily_loop.loader``.

Pinning for the silent fallback trap documented in
``blacksmith/loop-archives/05-13-micro-architecture-refactor/_HARDENING-REPORT.md``
(section 1 anatomy, section 3.1/3.3/3.4/3.5 fixes).

Quatro cenarios canonicos cobertos aqui (loop 05-13-hardening-cmd-flow, item 001):

  * ``test_fallback_when_items_str_with_populated_items_index_should_emit_warning``
    pinning do bug: ``buckets[*].items[*]`` como string + ``items_index[iid].commands``
    populado deveria emitir WARN em stderr. Marcado ``xfail(strict=True)`` ate o item
    005 do loop pousar o WARN no loader.
  * ``test_canonical_path_emits_literal_commands``
    happy path: ``buckets[*].items[*]`` como dict com ``commands`` -> cada comando
    vira um ``CommandSpec`` literal (sem wrapper ``/daily-loop:do``).
  * ``test_ambiguous_raises_dailyloopconfigerror``
    ``daily_loop.task_types[iid] == "ambiguous"`` levanta ``DailyLoopConfigError``
    com mensagem nomeando o iid, o caminho de correcao (``_LOOP-CONFIG.json``)
    e a razao registrada em ``items_index[iid].blocked_reason``. Pousou no item
    006 do loop 05-13-hardening-cmd-flow.
  * ``test_ambiguous_without_task_types_key_does_not_raise``
    retro-compat: ausencia da chave ``task_types`` mantem o caminho legacy
    intacto (nao levanta).
  * ``test_items_str_without_items_index_falls_back_silently``
    retro-compat: ``buckets[*].items[*]`` como string SEM ``items_index`` permanece
    no fallback ``/daily-loop:do --slug X --item NNN``, sem stderr.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from workflow_app.daily_loop.loader import (
    DailyLoopConfigError,
    build_daily_loop_specs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_progress(loop_root: Path, item_id: str = "001", bucket: str = "B") -> None:
    """Drop a minimal PROGRESS.md with a single pending item under loop_root."""
    progress = loop_root / "PROGRESS.md"
    progress.write_text(
        "# Progress\n"
        "\n"
        "| ID  | Status | Target          | Bucket | Updated |\n"
        "|-----|--------|-----------------|--------|---------|\n"
        f"| {item_id} | [ ]    | tasks/x.md      | {bucket}      | -       |\n",
        encoding="utf-8",
    )


def _base_config(
    *,
    items: list[Any],
    items_index: dict[str, Any] | None = None,
    task_types: dict[str, str] | None = None,
    bucket_id: str = "B",
    bucket_model: str = "opus",
    bucket_effort: str = "high",
) -> dict[str, Any]:
    """Build a minimal valid raw_config for build_daily_loop_specs.

    Only daily_loop is populated; basic_flow et al. are unused by the loader.
    """
    daily_loop: dict[str, Any] = {
        "slug": "test-loop",
        "buckets": [
            {
                "id": bucket_id,
                "model": bucket_model,
                "effort": bucket_effort,
                "items": items,
            }
        ],
    }
    if items_index is not None:
        daily_loop["items_index"] = items_index
    if task_types is not None:
        daily_loop["task_types"] = task_types
    return {"daily_loop": daily_loop}


# ---------------------------------------------------------------------------
# Cenario 1 — pinning do bug (xfail ate item 005 do loop pousar)
# ---------------------------------------------------------------------------


def test_fallback_when_items_str_with_populated_items_index_should_emit_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regressao do silent fallback trap.

    Anatomia (ver _HARDENING-REPORT.md §1.2):
      buckets[*].items[*] == ["001"]                             # string
      items_index["001"] == {"commands": ["/cmd:create foo.md"]} # populado
    -> loader cai no wrapper /daily-loop:do, sem emitir telemetria.
    Comportamento desejado (apos item 005): WARN nomeando o bug em stderr.
    """
    _write_progress(tmp_path)
    raw_config = _base_config(
        items=["001"],
        items_index={"001": {"commands": ["/cmd:create foo.md"]}},
    )

    build_daily_loop_specs(raw_config, tmp_path)

    captured = capsys.readouterr()
    assert "items_index" in captured.err.lower() or "fallback" in captured.err.lower(), (
        "Loader deveria emitir WARN explicito quando items_index tem commands "
        "mas buckets[*].items[*] esta como string; recebido stderr vazio. "
        f"stderr={captured.err!r}"
    )


def test_fallback_warning_message_exact_substrings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Casa substrings exatas do template literal do WARN (item 005).

    Garante que a redacao da telemetria nomeia: o iid, o do_command, o numero
    N de commands materializadas, o bug raiz (`buckets[*].items[*] esta como
    string`) e o caminho de correcao (`/loop:integration` ou promocao manual
    para dict). Mudancas na redacao quebram esse contrato — eh o pinning de
    UX da mensagem.
    """
    _write_progress(tmp_path)
    raw_config = _base_config(
        items=["001"],
        items_index={
            "001": {
                "commands": [
                    "/cmd:create foo.md",
                    "/cmd:review /micro:brief foo.md",
                ]
            }
        },
    )
    # Override do do_command para validar que ele aparece literal no WARN.
    raw_config["daily_loop"]["do_command"] = "/daily-loop:do"

    build_daily_loop_specs(raw_config, tmp_path)

    err = capsys.readouterr().err
    for needle in (
        "[daily-loop] WARN: item 001",
        "caiu no fallback /daily-loop:do",
        "items_index tem 2 commands materializadas",
        "daily_loop.buckets[*].items[*] esta como string",
        "Rodar /loop:integration novamente",
        '{"id":"001","commands":[...]}',
    ):
        assert needle in err, (
            f"Substring esperada ausente do WARN: {needle!r}. stderr={err!r}"
        )


# ---------------------------------------------------------------------------
# Cenario 2 — happy path (passa hoje)
# ---------------------------------------------------------------------------


def test_canonical_path_emits_literal_commands(tmp_path: Path) -> None:
    """Happy path canonico: dict com commands -> CommandSpec literal por entrada.

    Garante que o caminho preferencial (linhas 495-510 do loader) preserva os
    comandos exatos sem reescrever para wrapper /daily-loop:do.
    """
    _write_progress(tmp_path)
    canonical = [
        "/cmd:create blacksmith/x/task-001.md",
        "/cmd:review /micro:brief blacksmith/x/task-001.md",
    ]
    raw_config = _base_config(
        items=[{"id": "001", "commands": canonical}],
    )

    specs = build_daily_loop_specs(raw_config, tmp_path)
    names = [s.name for s in specs]

    for cmd in canonical:
        assert cmd in names, (
            f"Comando canonico {cmd!r} ausente dos specs emitidos. "
            f"Specs: {names}"
        )

    # Nenhum wrapper /daily-loop:do deveria aparecer para esse item.
    assert not any(n.startswith("/daily-loop:do") for n in names), (
        f"Wrapper /daily-loop:do nao deveria ser emitido no caminho canonico; "
        f"specs={names}"
    )


# ---------------------------------------------------------------------------
# Cenario 3 — ambiguous raises (pousou no item 006)
# ---------------------------------------------------------------------------


def test_ambiguous_raises_dailyloopconfigerror(tmp_path: Path) -> None:
    """Loader levanta DailyLoopConfigError em items ``task_type=ambiguous``.

    Spec do loop (item 006 do 05-13-hardening-cmd-flow) diz que workflow-app
    precisa bloquear esses items ate classificacao manual via /loop:mark-type.
    A excecao deve nomear o iid, o arquivo a ser editado e a razao registrada
    em ``items_index[iid].blocked_reason`` (mensagem acionavel).
    """
    _write_progress(tmp_path)
    raw_config = _base_config(
        items=[{"id": "001", "commands": ["/cmd:create foo.md"]}],
        task_types={"001": "ambiguous"},
        items_index={"001": {"blocked_reason": "missing classification"}},
    )

    with pytest.raises(DailyLoopConfigError) as excinfo:
        build_daily_loop_specs(raw_config, tmp_path)

    msg = str(excinfo.value)
    assert "task_type=ambiguous" in msg, (
        f"Mensagem deveria nomear o estado 'task_type=ambiguous'; recebido: {msg!r}"
    )
    assert "001" in msg, (
        f"Mensagem deveria nomear o iid '001'; recebido: {msg!r}"
    )
    assert "_LOOP-CONFIG.json" in msg, (
        f"Mensagem deveria apontar o arquivo a corrigir; recebido: {msg!r}"
    )
    assert "missing classification" in msg, (
        f"Mensagem deveria propagar blocked_reason; recebido: {msg!r}"
    )


def test_ambiguous_without_task_types_key_does_not_raise(tmp_path: Path) -> None:
    """Retro-compat: configs legacy sem ``task_types`` continuam funcionando.

    Antes do item 006 o loader nao olhava ``task_types``; configs gerados antes
    de ``/loop:mark-type`` nem sequer escrevem a chave. O guard deve ser noop
    nesse caminho.
    """
    _write_progress(tmp_path)
    raw_config = _base_config(
        items=[{"id": "001", "commands": ["/cmd:create foo.md"]}],
        # task_types ausente de proposito.
    )

    specs = build_daily_loop_specs(raw_config, tmp_path)
    assert specs, "Loader deveria emitir specs quando task_types esta ausente"


def test_ambiguous_with_blocked_reason_missing_uses_default_message(
    tmp_path: Path,
) -> None:
    """Quando ``items_index[iid].blocked_reason`` ausente, mensagem usa default.

    Garante que a ausencia do campo nao gera KeyError nem mensagem mal formada.
    """
    _write_progress(tmp_path)
    raw_config = _base_config(
        items=[{"id": "001", "commands": ["/cmd:create foo.md"]}],
        task_types={"001": "ambiguous"},
        # items_index ausente -> default "sem motivo registrado".
    )

    with pytest.raises(DailyLoopConfigError) as excinfo:
        build_daily_loop_specs(raw_config, tmp_path)

    assert "sem motivo registrado" in str(excinfo.value), (
        f"Mensagem deveria conter default quando blocked_reason ausente; "
        f"recebido: {excinfo.value!s}"
    )


# ---------------------------------------------------------------------------
# Cenario 4 — retro-compat (passa hoje)
# ---------------------------------------------------------------------------


def test_items_str_without_items_index_falls_back_silently(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Retro-compat: string items SEM items_index -> wrapper /daily-loop:do silencioso.

    Esse e o caminho legacy de ``/daily-loop`` puro (sem ``/loop:integration``
    materializando commands). Nao deve emitir WARN porque nao ha conflito —
    o fallback e a unica via.
    """
    _write_progress(tmp_path)
    raw_config = _base_config(items=["001"])
    # items_index ausente de proposito.

    specs = build_daily_loop_specs(raw_config, tmp_path)
    names = [s.name for s in specs]

    wrapper = "/daily-loop:do --slug test-loop --item 001"
    assert wrapper in names, (
        f"Wrapper {wrapper!r} ausente do fallback retro-compat; specs={names}"
    )

    captured = capsys.readouterr()
    # Filtra a coercao de floor do bucket (haiku/low) que tambem usa stderr — aqui
    # bucket eh opus/high, entao stderr deveria estar realmente vazio.
    assert captured.err.strip() == "", (
        "Fallback retro-compat (string sem items_index) deveria ser silencioso; "
        f"stderr={captured.err!r}"
    )
