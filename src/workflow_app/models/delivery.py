"""Pydantic v2 model of `delivery.json` v1 (DCP state plane).

Canonical source: `scheduled-updates/refactor-workflow-sytemforge/schemas/delivery.schema.json`
(T-001). This module replicates the schema structure exactly (D1-D9 resolutions
documented in EXECUTION-READINESS-T-035.md).

Schema structural violations (missing required fields, wrong types, invalid
enum values) raise `pydantic.ValidationError` via `Delivery.model_validate_json`.
Logical invariants I-01..I-12 (§5.2.5) are evaluated as **warnings** collected
in `Delivery._invariant_warnings` so the UI can display them without blocking
read-only access. Mutating operations (handled by T-002 `/delivery:validate` +
T-005 `DeliveryLock`) still fail hard on any invariant violation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

# ─── Type aliases ─────────────────────────────────────────────────────────── #

ModuleStateLiteral = Literal[
    "pending",
    "creation",
    "execution",
    "revision",
    "qa",
    "deploy",
    "done",
    "blocked",
    "rework",
]

StateIncludingV0 = Literal[
    "v0",
    "pending",
    "creation",
    "execution",
    "revision",
    "qa",
    "deploy",
    "done",
    "blocked",
    "rework",
]

StateExceptBlocked = Literal[
    "pending",
    "creation",
    "execution",
    "revision",
    "qa",
    "deploy",
    "done",
    "rework",
]

ModuleType = Literal[
    "foundations",
    "landing-page",
    "dashboard",
    "crud",
    "auth",
    "integration",
    "payment",
    "backoffice",
    "infra-only",
    "api-only",
]

Owner = Literal["pipeline", "human"]
ExecutionMode = Literal["sequential", "parallel-independent"]
ReworkPhase = Literal["creation", "execution", "revision", "qa", "deploy"]
Phase = ReworkPhase  # alias

ACTIVE_STATES: frozenset[str] = frozenset(
    {"creation", "execution", "revision", "qa", "deploy"}
)

_ISO8601_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_MODULE_KEY_RE = re.compile(r"^module-\d+-[a-z0-9-]+$")

Iso8601Utc = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"),
]
ModuleKey = Annotated[
    str, StringConstraints(pattern=r"^module-\d+-[a-z0-9-]+$")
]


# ─── Warning container ───────────────────────────────────────────────────── #


@dataclass(frozen=True)
class DeliveryInvariantWarning:
    """Non-fatal invariant violation detected during load.

    Surfaced through `Delivery.get_invariant_warnings()` so the workflow-app
    UI can render a modal list. Mutating flows MUST treat these as blockers
    by delegating to `/delivery:validate` (T-002), which fails with exit 1.
    """

    code: str  # e.g. "I-02"
    module: Optional[str]
    message: str


# ─── Sub-models ──────────────────────────────────────────────────────────── #


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    brief_root: str
    docs_root: str
    wbs_root: str
    workspace_root: str


class HistoryEntry(BaseModel):
    """Single transition record. `from` is a Python keyword, so we alias."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: StateIncludingV0 = Field(alias="from")
    to: ModuleStateLiteral
    at: Iso8601Utc
    by: str
    note: str


class ReworkTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Optional[ReworkPhase] = None
    module: Optional[str] = None


class ModuleFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    needs_rework: bool = False
    skeleton_outdated: bool = False
    rework_target: ReworkTarget = Field(default_factory=ReworkTarget)


class ModuleArtifacts(BaseModel):
    """Optional artifact pointers (all nullable per T-001 schema)."""

    model_config = ConfigDict(extra="forbid")

    module_meta_path: Optional[str] = None
    overview_path: Optional[str] = None
    last_specific_flow: Optional[str] = None
    last_review_report: Optional[str] = None
    last_commit_sha: Optional[str] = None
    last_deploy_url: Optional[str] = None
    git_tag: Optional[str] = None


class ModuleState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ModuleStateLiteral
    state_detail: Optional[str] = None
    module_type: ModuleType
    attempt: int = Field(ge=0)
    started_at: Optional[Iso8601Utc] = None
    last_transition: Iso8601Utc
    blocked: bool
    blocked_reason: Optional[str] = None
    blocked_prev_state: Optional[StateExceptBlocked] = None
    owner: Optional[Owner] = None
    flags: ModuleFlags
    skeleton_version: str
    rework_iterations: int = Field(ge=0)
    max_rework_iterations: int = Field(gt=0)
    history: List[HistoryEntry] = Field(default_factory=list)
    artifacts: ModuleArtifacts = Field(default_factory=ModuleArtifacts)
    dependencies: List[ModuleKey] = Field(default_factory=list)

    @model_validator(mode="after")
    def _per_module_invariants(self) -> "ModuleState":
        # Structural blocked/rework checks (also enforced by schema allOf,
        # re-checked here for defense in depth when model is built from dict).
        if self.state == "blocked":
            # I-11: blocked requires blocked_prev_state != null and != "blocked"
            if self.blocked_prev_state in (None, "blocked"):
                raise ValueError(
                    "I-11: state=blocked requires blocked_prev_state!=null and !=blocked"
                )
            if not self.blocked:
                raise ValueError("state=blocked requires blocked=true")
            if self.blocked_reason is None:
                raise ValueError("state=blocked requires blocked_reason!=null")
            if not self.history:
                raise ValueError("I-12: state=blocked requires non-empty history")
            if self.history[-1].to != "blocked":
                raise ValueError(
                    f"I-12: state=blocked requires history[-1].to=='blocked', got {self.history[-1].to!r}"
                )
        else:
            if self.blocked:
                raise ValueError(f"state={self.state!r} requires blocked=false")
            if self.blocked_reason is not None:
                raise ValueError(
                    f"state={self.state!r} requires blocked_reason=null"
                )

        if self.state == "rework":
            if not self.flags.needs_rework:
                raise ValueError(
                    "state=rework requires flags.needs_rework=true"
                )
            # I-08: rework_target phase+module both non-null
            if (
                self.flags.rework_target.phase is None
                or self.flags.rework_target.module is None
            ):
                raise ValueError(
                    "I-08: state=rework requires flags.rework_target.phase and .module to be non-null"
                )
        else:
            if self.flags.needs_rework:
                raise ValueError(
                    f"state={self.state!r} requires flags.needs_rework=false"
                )

        # I-06: attempt>=1 for active/done/rework states (and blocked when
        # blocked_prev_state != "pending").
        if self.state in ACTIVE_STATES or self.state in ("done", "rework"):
            if self.attempt < 1:
                raise ValueError(
                    f"I-06: state={self.state!r} requires attempt>=1, got {self.attempt}"
                )
        if self.state == "blocked" and self.blocked_prev_state not in (None, "pending"):
            if self.attempt < 1:
                raise ValueError(
                    "I-06: blocked with blocked_prev_state!=pending requires attempt>=1"
                )

        # I-09: max_rework_iterations > 0 (already enforced by Field(gt=0));
        # and rework_iterations <= max_rework_iterations.
        if self.rework_iterations > self.max_rework_iterations:
            raise ValueError(
                f"I-09: rework_iterations={self.rework_iterations} > max={self.max_rework_iterations}"
            )

        # I-07: last history entry must match current state (if history exists).
        if self.history and self.history[-1].to != self.state:
            raise ValueError(
                f"I-07: history[-1].to={self.history[-1].to!r} != state={self.state!r}"
            )

        return self


class Skeleton(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    sha256: str
    doc_path: str
    code_path: str
    last_updated: Iso8601Utc
    bumped_by: str


class Locks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holder: Optional[str] = None
    acquired_at: Optional[Iso8601Utc] = None
    expires_at: Optional[Iso8601Utc] = None
    ttl_seconds: int = Field(default=120, gt=0)

    @model_validator(mode="after")
    def _i04(self) -> "Locks":
        # I-04: holder and expires_at both null or both set.
        h, e, a = self.holder, self.expires_at, self.acquired_at
        if (h is None) != (e is None) or (h is None) != (a is None):
            raise ValueError(
                "I-04: locks.holder, locks.acquired_at and locks.expires_at "
                "must all be null or all be populated"
            )
        return self


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_sha256: str
    created_at: Iso8601Utc
    created_by: str
    last_modified_by: str


# ─── Top-level ───────────────────────────────────────────────────────────── #


class Delivery(BaseModel):
    """Top-level `delivery.json` v1 document.

    Loading via `Delivery.model_validate_json(content)` performs structural
    validation (fields, types, enums, per-module I-06..I-12 hard checks).
    Cross-module invariants I-01..I-03, I-10 are evaluated as warnings via
    `_collect_cross_invariants()` so the reader can present them as a UI
    warning list without blocking read-only access.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    project: Project
    current_module: Optional[ModuleKey] = None
    current_modules: List[ModuleKey] = Field(default_factory=list)
    execution_mode: ExecutionMode = "sequential"
    modules: Dict[ModuleKey, ModuleState]
    skeleton: Skeleton
    locks: Locks = Field(default_factory=Locks)
    metadata: Metadata

    # Private attribute to accumulate soft warnings (pydantic v2: prefix `_`).
    _invariant_warnings: List[DeliveryInvariantWarning] = []

    @model_validator(mode="after")
    def _collect_cross_invariants(self) -> "Delivery":
        # Reset in case a model is re-validated.
        warnings: List[DeliveryInvariantWarning] = []

        # I-01: execution_mode sequential requires current_module to exist in
        # modules. parallel-independent requires current_modules non-empty and
        # all keys exist. Structural presence is enforced by pydantic
        # (current_module has ModuleKey pattern); we only check referential
        # integrity here as a warning.
        if self.execution_mode == "sequential":
            if self.current_module is not None and self.current_module not in self.modules:
                warnings.append(
                    DeliveryInvariantWarning(
                        code="I-01",
                        module=self.current_module,
                        message=(
                            f"sequential mode: current_module={self.current_module!r} "
                            f"not found in modules"
                        ),
                    )
                )
            if self.current_module is None:
                warnings.append(
                    DeliveryInvariantWarning(
                        code="I-01",
                        module=None,
                        message="sequential mode requires current_module to be set",
                    )
                )
        else:  # parallel-independent
            if not self.current_modules:
                warnings.append(
                    DeliveryInvariantWarning(
                        code="I-01",
                        module=None,
                        message="parallel-independent mode requires non-empty current_modules",
                    )
                )
            missing = [m for m in self.current_modules if m not in self.modules]
            for m in missing:
                warnings.append(
                    DeliveryInvariantWarning(
                        code="I-01",
                        module=m,
                        message=f"current_modules entry {m!r} not found in modules",
                    )
                )

        # I-02: at most 1 active module in sequential mode; at most
        # len(current_modules) in parallel-independent.
        active = [
            mid for mid, st in self.modules.items() if st.state in ACTIVE_STATES
        ]
        if self.execution_mode == "sequential" and len(active) > 1:
            warnings.append(
                DeliveryInvariantWarning(
                    code="I-02",
                    module=None,
                    message=(
                        f"sequential mode has {len(active)} active modules "
                        f"({', '.join(active)}); expected at most 1"
                    ),
                )
            )
        elif self.execution_mode == "parallel-independent":
            cap = len(self.current_modules)
            if len(active) > cap:
                warnings.append(
                    DeliveryInvariantWarning(
                        code="I-02",
                        module=None,
                        message=(
                            f"parallel-independent mode has {len(active)} active modules "
                            f"(cap={cap})"
                        ),
                    )
                )

        # I-03: skeleton_version alignment.
        sk_version = self.skeleton.version
        for mid, st in self.modules.items():
            if st.skeleton_version != sk_version and not st.flags.skeleton_outdated:
                warnings.append(
                    DeliveryInvariantWarning(
                        code="I-03",
                        module=mid,
                        message=(
                            f"skeleton_version={st.skeleton_version!r} != skeleton.version={sk_version!r} "
                            f"and flags.skeleton_outdated is false"
                        ),
                    )
                )

        # I-10: dependencies of an active module must all be `done`.
        for mid, st in self.modules.items():
            if st.state not in ACTIVE_STATES:
                continue
            for dep in st.dependencies:
                dep_state = self.modules.get(dep)
                if dep_state is None:
                    warnings.append(
                        DeliveryInvariantWarning(
                            code="I-10",
                            module=mid,
                            message=(
                                f"dependency {dep!r} referenced by {mid!r} "
                                f"not found in modules"
                            ),
                        )
                    )
                    continue
                if dep_state.state != "done":
                    warnings.append(
                        DeliveryInvariantWarning(
                            code="I-10",
                            module=mid,
                            message=(
                                f"{mid!r} is in {st.state!r} but dependency {dep!r} "
                                f"is in {dep_state.state!r} (expected done)"
                            ),
                        )
                    )

        # Assign via __dict__ because private attributes in pydantic v2 need
        # explicit setattr; this is idiomatic per docs.
        object.__setattr__(self, "_invariant_warnings", warnings)
        return self

    def get_invariant_warnings(self) -> List[DeliveryInvariantWarning]:
        """Return the list of non-fatal invariant warnings collected on load."""
        return list(self._invariant_warnings)

    def has_invariant_warnings(self) -> bool:
        return bool(self._invariant_warnings)


__all__ = [
    "ACTIVE_STATES",
    "Delivery",
    "DeliveryInvariantWarning",
    "ExecutionMode",
    "HistoryEntry",
    "Iso8601Utc",
    "Locks",
    "Metadata",
    "ModuleArtifacts",
    "ModuleFlags",
    "ModuleKey",
    "ModuleState",
    "ModuleStateLiteral",
    "ModuleType",
    "Owner",
    "Project",
    "ReworkPhase",
    "ReworkTarget",
    "Skeleton",
    "StateExceptBlocked",
    "StateIncludingV0",
]
