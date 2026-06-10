"""Regression: `/build-module-pipeline` matrix contract.

Loop 05-27-dcp-flow-structured-fix - TASK-021 (item 022). Locks the
end-to-end behavior delivered by Onda 3 (TASK-014 strict default + TASK-015
guard-duplo + TASK-016 EXIT_BUSINESS=1) when `build_module_pipeline()` runs
against a real on-disk fixture:

  Case A (happy path): a freshly migrated DCP-COMMAND-MATRIX.json passes the
                       strict validator inside the pipeline; exit 0; delivery.json
                       transitions module-1-foundations pending -> creation.

  Case B (matrix corrompida): a bare placeholder name is injected into the
                              already-migrated command_index, bypassing the
                              migrator. The pipeline must exit non-zero
                              (EXIT_BUSINESS=1) and delivery.json must remain
                              byte-equal to the pre-run snapshot.

Why this test:

- TASK-015 introduced Guard 1 (_strict_validate_matrix_in_memory after the
  load+pydantic step) so the strict validator runs on the in-memory dict
  BEFORE delivery.json is mutated downstream. A regression that removed this
  guard would let a corrupt matrix slip through up to the lock-acquisition
  point.
- TASK-016 locked the contract that matrix-invalid emits EXIT_BUSINESS=1 with
  delivery.json INTOCADO. This test asserts both axes (exit code + byte-equal
  delivery.json) so a regression that mutates delivery before the guard fires
  fails loud.

Pattern: subprocess invocation of `build_module_pipeline()` via a Python -c
shim. Subprocess is required because the function caches the strict validator
module under `_STRICT_VALIDATOR_MOD` and registers synthetic packages in
`sys.modules`; sharing those across test cases inside the same pytest process
risks cross-contamination with neighbour tests that import the same code via
different paths (e.g. test_dcp_pipeline_e2e_task_manager.py).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest


# Layout: ai-forge/workflow-app/tests/this_file.py -> parents[3] = REPO_ROOT
REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATOR = REPO_ROOT / "ai-forge" / "scripts" / "migrate-dcp-matrix-canonical.py"
VALIDATOR = REPO_ROOT / "ai-forge" / "scripts" / "validate-dcp-matrix-canonical.py"
PROFILES = REPO_ROOT / ".claude" / "commands" / "_lib" / "specific_flow" / "profiles.py"
BUILD_PIPELINE_LIB = REPO_ROOT / ".claude" / "commands" / "_lib"

CM_ID = "module-1-foundations"
FOLD_IN_KEYS = ("G-deploy", "H-commit", "I-human-signoff", "I-human-mkt")


# --- Fixture builders ------------------------------------------------------ #


def _legacy_skeleton() -> Dict[str, Any]:
    """Pre-migrator matrix skeleton (copied from test_dcp_matrix_canonical)."""
    return {
        "schema_version": "1.0.1",
        "trail_max_entries": 200,
        "command_index": [],
        "phase_buckets": {},
        "global_filter": [],
        "global_filter_trail": [],
        "modules": {
            CM_ID: {
                "filter": [],
                "loop_multiplier": {},
                "directive_boundaries": [],
                "trail": [],
                "trail_archive": [],
                "overrides_skipped": [],
                "artifacts": {"last_specific_flow": None},
            }
        },
        "fold_in_rules": {k: [] for k in FOLD_IN_KEYS},
        "current_module": CM_ID,
        "execution_order": [CM_ID],
        "created_at": "2026-05-27T00:00:00Z",
        "created_by": "test:build-module-pipeline-matrix-contract",
        "last_mutated_at": "2026-05-27T00:00:00Z",
    }


def _materialize_canonical_matrix(matrix_path: Path) -> None:
    """Write a legacy skeleton then run the real migrator on it.

    The real migrator (TASK-007/TASK-008) emits the 171-entry canonical
    command_index in dual-field (name + template) shape. The output is a
    matrix that passes the strict validator out-of-the-box.
    """
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_path.write_text(
        json.dumps(_legacy_skeleton(), indent=2), encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(MIGRATOR),
            "--matrix",
            str(matrix_path),
            "--profiles",
            str(PROFILES),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"migrator failed (exit {result.returncode}): "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def _write_project_json(config_path: Path, *, wbs_root: Path, dcp_root: Path) -> None:
    """V3 project.json with explicit dcp_root so the pipeline finds the matrix."""
    payload = {
        "name": "bmp-matrix-contract",
        "basic_flow": {
            "brief_root": str(wbs_root / "brief"),
            "docs_root": str(wbs_root / "docs"),
            "wbs_root": str(wbs_root),
            "workspace_root": str(wbs_root / "workspace"),
            "dcp_root": str(dcp_root),
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_delivery_json(wbs_root: Path) -> Path:
    """delivery.json v2 with module-1-foundations in pending state.

    `build_module_pipeline` requires:
      - execution_mode == sequential (I-02 precheck path)
      - modules[CM_ID].state == "pending" (transitions to creation)
      - skeleton.version matches MODULE-META.skeleton_version_required
    """
    payload = {
        "version": 2,
        "project": {
            "name": "bmp-matrix-contract",
            "brief_root": str(wbs_root / "brief"),
            "docs_root": str(wbs_root / "docs"),
            "wbs_root": str(wbs_root),
            "workspace_root": str(wbs_root / "workspace"),
        },
        "current_module": CM_ID,
        "current_modules": [],
        "execution_mode": "sequential",
        "modules": {
            CM_ID: {
                "state": "pending",
                "state_detail": "pending-detail",
                "module_type": "foundations",
                "attempt": 0,
                "started_at": "2026-05-27T12:00:00Z",
                "last_transition": "2026-05-27T12:00:00Z",
                "blocked": False,
                "blocked_reason": None,
                "blocked_prev_state": None,
                "owner": "pipeline",
                "flags": {
                    "needs_rework": False,
                    "skeleton_outdated": False,
                    "rework_target": {"phase": None, "module": None},
                },
                "skeleton_version": "skeleton-v1",
                "rework_iterations": 0,
                "max_rework_iterations": 2,
                "history": [],
                "artifacts": {
                    "module_meta_path": None,
                    "overview_path": None,
                    "last_review_report": None,
                    "last_commit_sha": None,
                    "last_deploy_url": None,
                    "git_tag": None,
                },
                "dependencies": [],
            }
        },
        "skeleton": {
            "version": "skeleton-v1",
            "sha256": "deadbeef",
            "doc_path": "output/_SHARED-SKELETON.md",
            "code_path": "output/shared/contracts",
            "last_updated": "2026-05-27T08:00:00Z",
            "bumped_by": "modules:create-structure",
        },
        "locks": {
            "holder": None,
            "acquired_at": None,
            "expires_at": None,
            "ttl_seconds": 120,
        },
        "metadata": {
            "schema_sha256": "schema-v1",
            "created_at": "2026-05-27T15:00:00Z",
            "created_by": "/delivery:init",
            "last_modified_by": "build-module-pipeline",
        },
    }
    path = wbs_root / "delivery.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_module_meta(wbs_root: Path) -> Path:
    """Minimal-but-complete MODULE-META.json that satisfies the canonical schema."""
    meta_dir = wbs_root / "modules" / CM_ID
    meta_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "module_id": CM_ID,
        "module_name": "Foundations",
        "module_type": "foundations",
        "natures": ["shared-primitives", "plumbing"],
        "criticality": "high",
        "scope_override": None,
        "presence": {
            "frontend": False,
            "backend": False,
            "database": False,
            "mobile": False,
            "static": False,
        },
        "dependencies": {
            "modules": [],
            "contracts": [],
            "external_services": [],
            "env_vars_required": [],
        },
        "allow_older_skeleton": False,
        "reviews": {
            "stack_review_profile": "foundations-lean",
            "required_checks": [
                "architecture",
                "configuration",
                "typescript",
                "boundaries",
            ],
            "skipped_checks": [
                "seo",
                "accessibility",
                "styling",
                "performance",
                "data-fetching",
                "server-actions",
                "forms",
            ],
            "require_mobile_check": False,
        },
        "deploy": {
            "target": "none",
            "requires_migrations": False,
            "requires_seed": False,
            "rollback_strategy": "git-revert-tag",
        },
        "qa": {
            "requires_roles_validation": False,
            "requires_billing_validation": False,
            "intake_review_required": False,
            "security_review_required": True,
        },
        "skeleton_version_required": "skeleton-v1",
        "estimated_effort_hours": 4,
        "commit_type": "simple",
        "flags": {"skeleton_outdated": False},
        "module": {"requires_container": False},
        "mcp": {"module_additions": []},
        "env": {"module_additions": []},
        "tdd": {
            "required": False,
            "required_suites": [],
            "coverage_target": 0,
            "mutation_target": 0,
            "locked": False,
            "lock_sha256": None,
        },
    }
    path = meta_dir / "MODULE-META.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _build_fixture(tmp_path: Path) -> Dict[str, Path]:
    """Assemble the full on-disk fixture and return canonical paths."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    dcp_root = tmp_path / "dcp"
    dcp_root.mkdir()
    config_path = tmp_path / ".claude" / "project.json"

    _write_project_json(config_path, wbs_root=wbs_root, dcp_root=dcp_root)
    delivery_path = _write_delivery_json(wbs_root)
    meta_path = _write_module_meta(wbs_root)
    matrix_path = dcp_root / "DCP-COMMAND-MATRIX.json"
    _materialize_canonical_matrix(matrix_path)

    return {
        "config_path": config_path,
        "wbs_root": wbs_root,
        "dcp_root": dcp_root,
        "delivery_path": delivery_path,
        "meta_path": meta_path,
        "matrix_path": matrix_path,
    }


# --- Subprocess shim ------------------------------------------------------- #


def _run_build_module_pipeline(
    config_path: Path, *, module: str, cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Invoke `build_module_pipeline()` in a clean subprocess.

    Isolation is required because the lib registers synthetic packages
    (`_sf_delivery_lib`, `_sf_modules_lib`, `_sf_build_lib`) in sys.modules at
    import time and caches the strict validator under `_STRICT_VALIDATOR_MOD`.
    Re-importing inside the test process would clobber neighbour tests.
    """
    shim = (
        "import sys; "
        f"sys.path.insert(0, {str(BUILD_PIPELINE_LIB)!r}); "
        "from build_module_pipeline import build_module_pipeline; "
        f"rc = build_module_pipeline({str(config_path)!r}, module={module!r}); "
        "sys.exit(rc)"
    )
    env = os.environ.copy()
    # Force unbuffered stderr so error messages survive on failure.
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.run(
        [sys.executable, "-c", shim],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def _validate_matrix_strict(matrix_path: Path) -> subprocess.CompletedProcess[str]:
    """Run the canonical strict validator out-of-band against an on-disk matrix."""
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--matrix",
            str(matrix_path),
            "--profiles",
            str(PROFILES),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


# --- Skip guard ------------------------------------------------------------ #


_REQUIRED_PATHS = (MIGRATOR, VALIDATOR, PROFILES, BUILD_PIPELINE_LIB / "build_module_pipeline.py")


_SKIP_REASON = next(
    (f"missing required path: {p}" for p in _REQUIRED_PATHS if not p.exists()),
    None,
)

pytestmark = pytest.mark.skipif(
    _SKIP_REASON is not None,
    reason=_SKIP_REASON or "",
)


# --- Case A: healthy fixture ---------------------------------------------- #


def test_build_module_pipeline_healthy_matrix_passes_strict_validator(
    tmp_path: Path,
) -> None:
    """Case A: matrix gerada via migrador canonico passa validator strict
    dentro do pipeline; exit == EXIT_OK=0; matrix on-disk continua valida
    apos a mutacao (current_module + last_mutated_at)."""
    paths = _build_fixture(tmp_path)

    # Pre-flight: matrix on disk passes strict validator before the run.
    pre_strict = _validate_matrix_strict(paths["matrix_path"])
    assert pre_strict.returncode == 0, (
        f"baseline strict validation failed (rc={pre_strict.returncode}): "
        f"{pre_strict.stderr!r} / {pre_strict.stdout!r}"
    )

    result = _run_build_module_pipeline(
        paths["config_path"], module=CM_ID, cwd=tmp_path
    )

    assert result.returncode == 0, (
        f"build_module_pipeline must return EXIT_OK=0 on healthy fixture; "
        f"got rc={result.returncode}, "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )

    # Post-run: matrix STILL passes strict validation. The pipeline mutated
    # current_module + last_mutated_at and atomically rewrote the file; a
    # regression that bypasses Guard 2 (post-mutation pre-write) would leak
    # an off-canonical reference here.
    post_strict = _validate_matrix_strict(paths["matrix_path"])
    assert post_strict.returncode == 0, (
        f"post-mutation strict validation failed (rc={post_strict.returncode}): "
        f"{post_strict.stderr!r}"
    )

    # Delivery.json transitioned: state -> creation, attempt -> 1.
    doc = json.loads(paths["delivery_path"].read_text(encoding="utf-8"))
    module_state = doc["modules"][CM_ID]
    assert module_state["state"] == "creation", (
        f"expected state=creation after happy path; got {module_state['state']!r}"
    )
    assert module_state["attempt"] == 1, (
        f"expected attempt=1 after first run; got {module_state['attempt']}"
    )


# --- Case B: corrupted matrix --------------------------------------------- #


def test_build_module_pipeline_corrupted_matrix_exits_nonzero_and_preserves_delivery(
    tmp_path: Path,
) -> None:
    """Case B: bare placeholder name injetado em command_index[0]; o pipeline
    deve abortar com exit nao-zero (EXIT_BUSINESS=1) e delivery.json deve ficar
    byte-equal ao snapshot pre-run.

    Cobre TASK-015 (Guard 1) + TASK-016 (EXIT_BUSINESS=1) + zero side-effects
    em delivery.json.
    """
    paths = _build_fixture(tmp_path)

    # Snapshot delivery.json bytes before the run.
    delivery_bytes_before = paths["delivery_path"].read_bytes()

    # Corrupt the matrix: strip the {task} placeholder from entry 0's `name`
    # and `template`. The canonical template for `/create-task` carries
    # `{task}`, so a bare `/create-task` is BARE_NON_EXECUTABLE_NAME under the
    # strict validator (TASK-005/TASK-014 contract).
    matrix_raw = json.loads(paths["matrix_path"].read_text(encoding="utf-8"))
    assert matrix_raw["command_index"], "fixture must have a non-empty command_index"
    target_entry = matrix_raw["command_index"][0]
    assert target_entry["name"].startswith("/create-task"), (
        f"fixture invariant: entry 0 name starts with /create-task; "
        f"got {target_entry['name']!r}"
    )
    # Drop args from both name and template -> bare token whose canonical
    # template requires placeholder.
    target_entry["name"] = "/create-task"
    target_entry["template"] = "/create-task"
    paths["matrix_path"].write_text(
        json.dumps(matrix_raw, indent=2), encoding="utf-8"
    )

    # Sanity: the corrupted matrix now fails the strict validator at the
    # script boundary too.
    corrupt_strict = _validate_matrix_strict(paths["matrix_path"])
    assert corrupt_strict.returncode != 0, (
        "fixture invariant: corrupted matrix must fail strict validator "
        f"out-of-band (got rc={corrupt_strict.returncode})"
    )

    result = _run_build_module_pipeline(
        paths["config_path"], module=CM_ID, cwd=tmp_path
    )

    assert result.returncode != 0, (
        "build_module_pipeline must NOT return EXIT_OK on a corrupted matrix; "
        f"got rc=0, stdout={result.stdout!r}"
    )
    # EXIT_BUSINESS=1 per the demoted contract (TASK-016).
    assert result.returncode == 1, (
        f"corrupted matrix must collapse to EXIT_BUSINESS=1; "
        f"got rc={result.returncode}, stderr={result.stderr!r}"
    )

    # Delivery.json INTOCADO (TASK-015 + TASK-016 fail-closed contract).
    delivery_bytes_after = paths["delivery_path"].read_bytes()
    assert delivery_bytes_after == delivery_bytes_before, (
        "delivery.json must be byte-equal after corrupted-matrix run; "
        "Guard 1 fired AFTER an unsafe mutation"
    )


# --- Loop 06-09: cross-check loop_multiplier vs TASK-*.md reais ------------- #

_CROSSCHECK_SHIM = r"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, sys.argv[1])  # .claude/commands/_lib
import build_module_pipeline as bmp

cm_id = sys.argv[2]
wbs_root = Path(sys.argv[3])
baked = int(sys.argv[4])

entry = SimpleNamespace(
    filter=[1, 1],
    loop_multiplier={"A-creation": baked, "B3-execute": baked},
)
matrix = SimpleNamespace(command_index=[None, None], modules={cm_id: entry})
bmp._validate_matrix_module(
    matrix, cm_id, {"module_type": "feature"}, wbs_root=wbs_root
)
print("validate-ok")
"""


def _run_crosscheck_shim(wbs_root: Path, cm_id: str, baked: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _CROSSCHECK_SHIM,
         str(BUILD_PIPELINE_LIB), cm_id, str(wbs_root), str(baked)],
        capture_output=True, text=True, timeout=60,
    )


def _make_module_dir(wbs_root: Path, cm_id: str) -> Path:
    """3 tasks executaveis (TASK-0/1/2) + 2 companions que NAO contam."""
    d = wbs_root / "modules" / cm_id
    d.mkdir(parents=True)
    for name in ("TASK-0.md", "TASK-1.md", "TASK-2.md",
                 "TASK-1-REVIEW.md", "TASK-0-CHECKLIST.md"):
        (d / name).write_text("# t", encoding="utf-8")
    return d


def test_multiplier_drift_emits_warn_with_real_count(tmp_path):
    """baked=5 vs 3 executaveis reais (companions excluidos) -> WARN por fase
    com a contagem canonica e remediacao /dcp:matrix-mark-loops; advisory
    (exit 0, validacao passa)."""
    _make_module_dir(tmp_path, "module-9-feature")
    proc = _run_crosscheck_shim(tmp_path, "module-9-feature", baked=5)
    assert proc.returncode == 0, proc.stderr
    assert "validate-ok" in proc.stdout
    warns = [l for l in proc.stderr.splitlines() if "difere de 3 TASK-*.md" in l]
    assert len(warns) == 2, f"esperava WARN p/ A-creation e B3-execute: {proc.stderr}"
    assert "/dcp:matrix-mark-loops" in proc.stderr


def test_multiplier_parity_emits_no_warn(tmp_path):
    """baked == contagem real -> silencio (sem ruido no caminho saudavel)."""
    _make_module_dir(tmp_path, "module-9-feature")
    proc = _run_crosscheck_shim(tmp_path, "module-9-feature", baked=3)
    assert proc.returncode == 0, proc.stderr
    assert "difere de" not in proc.stderr
    assert "pulado" not in proc.stderr


def test_module_dir_missing_emits_skip_warn(tmp_path):
    """wbs_root dado mas diretorio do modulo ausente -> WARN explicito de
    cross-check pulado (Zero Silencio; simetrico ao fail-loud do consumer),
    sem abortar (advisory)."""
    (tmp_path / "modules").mkdir()
    proc = _run_crosscheck_shim(tmp_path, "module-9-feature", baked=3)
    assert proc.returncode == 0, proc.stderr
    assert "cross-check de loop_multiplier pulado" in proc.stderr
    assert "module-9-feature" in proc.stderr
