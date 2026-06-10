from __future__ import annotations

from pathlib import Path

from workflow_app.pipeline.phase_trigger_engine import PhaseTriggerEngine

# Checkpoints whose phase_triggers foram depreciados no item 004 (1.7.0-pre.2).
# Governanca migrada para dcp_closer._fire_governance_ledger; o engine puro NAO
# deve mais injetar comandos avulsos na fila para nenhum destes.
_DEPRECATED_CHECKPOINTS = [
    "/review-prd-flow",
    "/validate-pipeline",
    "/build-verify",
    "/brief-vs-frontend-review",
    "/post-deploy-verify",
    "/delivery:sign-off",
]

# Comandos de dcp_triggers[].after — o engine NUNCA leu dcp_triggers (apenas
# phase_triggers), entao nenhum destes deve disparar dispatch automatico.
# Excluido `/post-deploy-verify` da lista por ser tambem um checkpoint de
# phase_triggers (f11, agora depreciado) — overlap coberto pelo teste anterior.
_DCP_TRIGGER_AFTERS = [
    "/commit:simple",
    "/commit:static",
    "/build-module-pipeline",
    "/delivery:unblock",
]


def _real_contract_path() -> Path:
    # tests/ -> workflow-app/ ; contrato real consumido pelo engine em runtime.
    root = Path(__file__).resolve().parents[1]
    return root / "ai-forge" / "pipeline-contracts" / "PHASE-CONTRACTS.json"


def test_deprecated_phase_triggers_emit_no_standalone_commands():
    """Item 004 (Contrato C2): nenhum comando avulso entra na fila.

    Apos a depreciacao (auto_actions=[]), tanto o caminho runtime
    (check_and_expand) quanto o compile-time (inject_phase_actions_into_queue)
    devem produzir ZERO specs novos para cada checkpoint depreciado, sem
    qualquer alteracao no engine.
    """
    engine = PhaseTriggerEngine(_real_contract_path())

    from workflow_app.domain import CommandSpec

    for checkpoint in _DEPRECATED_CHECKPOINTS:
        _trigger_id, specs = engine.check_and_expand(
            checkpoint,
            existing_commands=[],
            fired_triggers=set(),
            config_path=".claude/projects/demo.json",
        )
        assert specs == [], (
            f"checkpoint depreciado {checkpoint} ainda injetou comandos avulsos: "
            f"{[s.name for s in specs]}"
        )

    queue = [CommandSpec(name=c) for c in _DEPRECATED_CHECKPOINTS]
    out = engine.inject_phase_actions_into_queue(queue)
    assert [c.name for c in out] == _DEPRECATED_CHECKPOINTS, (
        "inject_phase_actions_into_queue inseriu comandos avulsos a partir de "
        f"phase_triggers depreciados: {[c.name for c in out]}"
    )


def test_engine_has_no_dcp_triggers_dispatcher():
    """Item 004 (Aceite): dcp_triggers segue sem dispatcher automatico.

    O PhaseTriggerEngine le apenas `phase_triggers`. Disparar qualquer comando
    listado em `dcp_triggers[].after` (ex.: /commit:*) NAO pode expandir a fila.
    """
    engine = PhaseTriggerEngine(_real_contract_path())

    for after in _DCP_TRIGGER_AFTERS:
        trigger_id, specs = engine.check_and_expand(
            after,
            existing_commands=[],
            fired_triggers=set(),
            config_path="",
        )
        assert specs == [], (
            f"engine despachou dcp_trigger para {after}: {[s.name for s in specs]}"
        )
        assert trigger_id is None, (
            f"engine casou um phase_trigger para o comando dcp {after}: {trigger_id}"
        )


def _write_contract(path):
    path.write_text(
        """
{
  "phase_triggers": {
    "f2_post_review": {
      "on_command_success": "/review-prd-flow",
      "auto_actions": [
        "/pipeline:run-scorecard --phase f2",
        "/cmd:backlog-from-lessons --phase f2"
      ]
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_benchmark(path):
    path.write_text('{"version":"test"}\n', encoding="utf-8")


def test_trigger_expands_actions(tmp_path):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    _write_benchmark(tmp_path / "BENCHMARK-CONTRACTS.json")
    engine = PhaseTriggerEngine(contract)

    trigger_id, specs = engine.check_and_expand(
        "/review-prd-flow",
        existing_commands=[],
        fired_triggers=set(),
        config_path=".claude/projects/demo.json",
    )

    assert trigger_id == "f2_post_review"
    assert [s.name for s in specs] == [
        "/pipeline:run-scorecard --phase f2",
        "/cmd:backlog-from-lessons --phase f2",
    ]
    assert all(s.config_path == ".claude/projects/demo.json" for s in specs)


def test_trigger_respects_fired_triggers(tmp_path):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    _write_benchmark(tmp_path / "BENCHMARK-CONTRACTS.json")
    engine = PhaseTriggerEngine(contract)

    trigger_id, specs = engine.check_and_expand(
        "/review-prd-flow",
        existing_commands=[],
        fired_triggers={"f2_post_review"},
        config_path="",
    )

    assert trigger_id is None
    assert specs == []


def test_trigger_dedupes_existing_actions(tmp_path):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    _write_benchmark(tmp_path / "BENCHMARK-CONTRACTS.json")
    engine = PhaseTriggerEngine(contract)

    trigger_id, specs = engine.check_and_expand(
        "/review-prd-flow",
        existing_commands=["/pipeline:run-scorecard --phase f2"],
        fired_triggers=set(),
        config_path="",
    )

    assert trigger_id == "f2_post_review"
    assert [s.name for s in specs] == ["/cmd:backlog-from-lessons --phase f2"]


def test_compile_time_injection_inserts_after_checkpoint(tmp_path):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    _write_benchmark(tmp_path / "BENCHMARK-CONTRACTS.json")
    engine = PhaseTriggerEngine(contract)

    from workflow_app.domain import CommandSpec

    queue = [
        CommandSpec(name="/project-json"),
        CommandSpec(name="/review-prd-flow"),
        CommandSpec(name="/auto-flow modules"),
    ]

    out = engine.inject_phase_actions_into_queue(queue)
    names = [c.name for c in out]
    idx = names.index("/review-prd-flow")
    assert names[idx + 1] == "/pipeline:run-scorecard --phase f2"
    assert names[idx + 2] == "/cmd:backlog-from-lessons --phase f2"


def test_missing_benchmark_suppresses_injection_and_writes_pending(tmp_path, caplog):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    engine = PhaseTriggerEngine(contract)

    trigger_id, specs = engine.check_and_expand(
        "/review-prd-flow",
        existing_commands=[],
        fired_triggers=set(),
        config_path=".claude/projects/demo.json",
    )

    assert trigger_id == "f2_post_review"
    assert specs == []
    pending = tmp_path / "_pipeline-research" / "_PENDING.md"
    content = pending.read_text(encoding="utf-8")
    assert "trigger_id: `f2_post_review`" in content
    assert "missing_artifact:" in content
    assert "config_path: `.claude/projects/demo.json`" in content
    assert "bootstrap guard absent" in caplog.text


def test_missing_benchmark_pending_is_idempotent(tmp_path):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    engine = PhaseTriggerEngine(contract)

    for _ in range(2):
        engine.check_and_expand(
            "/review-prd-flow",
            existing_commands=[],
            fired_triggers=set(),
            config_path="",
        )

    pending = tmp_path / "_pipeline-research" / "_PENDING.md"
    content = pending.read_text(encoding="utf-8")
    assert content.count("<!-- phase-trigger-pending:") == 1
    assert content.count("## Pending phase trigger - f2_post_review") == 1


def test_pending_write_failure_is_visible_and_still_suppresses_injection(tmp_path, caplog):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    (tmp_path / "_pipeline-research").write_text("not a directory\n", encoding="utf-8")
    engine = PhaseTriggerEngine(contract)

    trigger_id, specs = engine.check_and_expand(
        "/review-prd-flow",
        existing_commands=[],
        fired_triggers=set(),
        config_path="",
    )

    assert trigger_id == "f2_post_review"
    assert specs == []
    assert engine.last_pending_notice is not None
    assert "pending_error" in engine.last_pending_notice
    assert "pending write failed" in caplog.text
    assert "bootstrap guard pending marker unavailable" in caplog.text


def test_pending_entry_is_removed_when_benchmark_returns(tmp_path):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    engine = PhaseTriggerEngine(contract)

    engine.check_and_expand(
        "/review-prd-flow",
        existing_commands=[],
        fired_triggers=set(),
        config_path="",
    )
    pending = tmp_path / "_pipeline-research" / "_PENDING.md"
    assert "f2_post_review" in pending.read_text(encoding="utf-8")

    _write_benchmark(tmp_path / "BENCHMARK-CONTRACTS.json")
    trigger_id, specs = engine.check_and_expand(
        "/review-prd-flow",
        existing_commands=[],
        fired_triggers=set(),
        config_path="",
    )

    assert trigger_id == "f2_post_review"
    assert [s.name for s in specs] == [
        "/pipeline:run-scorecard --phase f2",
        "/cmd:backlog-from-lessons --phase f2",
    ]
    assert "f2_post_review" not in pending.read_text(encoding="utf-8")
