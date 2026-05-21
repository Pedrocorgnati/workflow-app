"""Pydantic v2 model of `DCP-COMMAND-MATRIX.json` schema v1.

Canonical runtime authority (st-01 / source.md L46-92). The `.schema.json` on
disk is the external contract (CI / IDE / readers) generated via
`model_json_schema(schema_generator=WithDialect)` injecting
`$schema = https://json-schema.org/draft/2020-12/schema` and `$defs`.

SchemaVer (internal):
- ADDITION (1.0.x): add optional field, compatible with historical files.
- REVISION (1.x.0): remove optional field, rename key, restrict enum.
- MODEL    (x.0.0): remove required field, change type, break invariant.

Runtime validation is done via `DcpCommandMatrix.model_validate(raw)`, NOT via
the `jsonschema` library. The emitted `.schema.json` exists only for external
consumers; the active validator is Pydantic v2.12.5.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import GenerateJsonSchema

__all__ = [
    "PhaseLiteral",
    "BitLiteral",
    "ModelLiteral",
    "EffortLiteral",
    "InteractionLiteral",
    "TrailGateLiteral",
    "CommandIndexEntry",
    "CommandRef",
    "FilterTrailEntry",
    "TrailEntry",
    "TrailSnapshot",
    "DirectiveBoundary",
    "ArtifactsState",
    "ModuleEntry",
    "FoldInRules",
    "DcpCommandMatrix",
    "WithDialect",
]

PhaseLiteral = Literal[
    "A-creation",
    "B-tdd",
    "B-build",
    "B-dcp",
    "B3-execute",
    "C-linkage",
    "D-f8-micro",
    "D5-review",
    "E-qa-micro",
    "F-stack-plan",
    "F2-stack-check",
    "G-deploy",
    "H-commit",
    "I-human-signoff",
    "I-human-mkt",
]

BitLiteral = Literal[0, 1]

ModelLiteral = Literal["opus", "sonnet"]
EffortLiteral = Literal["low", "medium", "high", "max"]
InteractionLiteral = Literal["interactive", "headless", "manual", "auto", "inter"]


_BASE_CONFIG = ConfigDict(
    extra="forbid",
    frozen=False,
    validate_assignment=True,
    populate_by_name=True,
)


class CommandIndexEntry(BaseModel):
    model_config = _BASE_CONFIG

    name: str
    phase: PhaseLiteral
    model: ModelLiteral
    effort: EffortLiteral
    interaction: InteractionLiteral
    condition: Optional[str] = None
    per_task: bool = False
    per_stack: bool = False
    mandatory: bool = False
    source_ref: Optional[str] = None


class CommandRef(BaseModel):
    model_config = _BASE_CONFIG

    name: str
    phase: PhaseLiteral
    model: Optional[ModelLiteral] = None
    effort: Optional[EffortLiteral] = None
    interaction: Optional[InteractionLiteral] = None
    condition: Optional[str] = None
    mandatory: bool = False
    source_ref: Optional[str] = None


class FilterTrailEntry(BaseModel):
    model_config = _BASE_CONFIG

    at: datetime
    gate: str
    command_index: int
    from_bit: BitLiteral
    to_bit: BitLiteral
    reason: str


TrailGateLiteral = Literal[
    "congruence",
    "temporality",
    "meta-completeness",
    "directive-injector",
    "replicate",
    "load-queue",
    "filter-modules",
    "mark-loops",
]


class TrailEntry(BaseModel):
    """Granular trail entry. Two shapes coexist in this single model:

    - **Summary event** (1 per gate-run): ``bits_evaluated``, ``bits_flipped_*``,
      ``run_duration_ms``, ``input_sha256`` populated; flip fields ``None``.
    - **Flip event** (N per gate-run, N = real flips): ``command_index``,
      ``from_value`` (alias ``from``), ``to_value`` (alias ``to``), ``reason``,
      ``predicate`` populated; summary fields ``None``.

    Generic action events (replicate, mark-loops) use ``action``. The ``ts``
    field accepts the legacy alias ``at`` on read so in-flight matrices keep
    validating; new writers MUST emit ``ts``.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        validate_assignment=True,
        populate_by_name=True,
    )

    ts: datetime = Field(validation_alias=AliasChoices("ts", "at"))
    gate: TrailGateLiteral
    run_id: str

    bits_evaluated: Optional[int] = None
    bits_flipped_1_to_0: Optional[int] = None
    bits_flipped_0_to_1: Optional[int] = None
    run_duration_ms: Optional[int] = None
    input_sha256: Optional[str] = None

    command_index: Optional[int] = None
    from_value: Optional[BitLiteral] = Field(
        default=None,
        validation_alias=AliasChoices("from_value", "from"),
        serialization_alias="from",
    )
    to_value: Optional[BitLiteral] = Field(
        default=None,
        validation_alias=AliasChoices("to_value", "to"),
        serialization_alias="to",
    )
    reason: Optional[str] = None
    predicate: Optional[str] = None

    action: Optional[str] = None


class TrailSnapshot(BaseModel):
    model_config = _BASE_CONFIG

    archived_at: datetime
    entries: List[TrailEntry] = Field(default_factory=list)


class DirectiveBoundary(BaseModel):
    model_config = _BASE_CONFIG

    directive: Literal["/clear", "/model", "/effort"]
    at_command_index: int
    applied_at: datetime


class ArtifactsState(BaseModel):
    model_config = _BASE_CONFIG

    last_specific_flow: Optional[str] = None
    last_specific_flow_sha256: Optional[str] = None
    congruence_last_input_sha256: Optional[str] = None
    congruence_last_run_at: Optional[datetime] = None
    temporality_last_input_sha256: Optional[str] = None
    temporality_last_run_at: Optional[datetime] = None
    meta_completeness_last_input_sha256: Optional[str] = None
    meta_completeness_last_run_at: Optional[datetime] = None
    directive_injector_last_input_sha256: Optional[str] = None
    directive_injector_last_run_at: Optional[datetime] = None
    directive_injector_run_at: Optional[datetime] = None


class ModuleEntry(BaseModel):
    model_config = _BASE_CONFIG

    filter: List[BitLiteral]
    loop_multiplier: Dict[str, int]
    directive_boundaries: List[DirectiveBoundary] = Field(default_factory=list)
    trail: List[TrailEntry] = Field(default_factory=list)
    trail_archive: List[TrailSnapshot] = Field(default_factory=list)
    overrides_skipped: List[str] = Field(default_factory=list)
    artifacts: ArtifactsState = Field(default_factory=ArtifactsState)


class FoldInRules(BaseModel):
    model_config = _BASE_CONFIG

    H_commit: List[CommandRef] = Field(default_factory=list, alias="H-commit")
    I_human_signoff: List[CommandRef] = Field(default_factory=list, alias="I-human-signoff")
    G_deploy: List[CommandRef] = Field(default_factory=list, alias="G-deploy")
    I_human_mkt: List[CommandRef] = Field(default_factory=list, alias="I-human-mkt")


class DcpCommandMatrix(BaseModel):
    model_config = _BASE_CONFIG

    schema_version: Literal["1.0.1"] = Field(
        default="1.0.1",
        description="SchemaVer interno (ADDITION 1.0.x, REVISION 1.x.0, MODEL x.0.0).",
    )
    trail_max_entries: int = Field(
        default=200,
        ge=10,
        le=10000,
        description=(
            "Cap canonico do trail per modulo antes de archive. "
            "Mudancas exigem REVISION SchemaVer (acima de 10000 ou abaixo de 10 sao rejeitadas)."
        ),
    )
    command_index: List[CommandIndexEntry] = Field(default_factory=list)
    phase_buckets: Dict[str, List[int]] = Field(default_factory=dict)
    global_filter: List[BitLiteral] = Field(default_factory=list)
    global_filter_trail: List[FilterTrailEntry] = Field(default_factory=list)
    modules: Dict[str, ModuleEntry] = Field(default_factory=dict)
    fold_in_rules: FoldInRules = Field(default_factory=FoldInRules)
    current_module: Optional[str] = None
    execution_order: List[str] = Field(default_factory=list)
    created_at: datetime
    created_by: str
    last_mutated_at: datetime

    @model_validator(mode="after")
    def _check_invariants(self) -> "DcpCommandMatrix":
        n = len(self.command_index)
        if self.global_filter and len(self.global_filter) != n:
            raise ValueError(
                f"global_filter length ({len(self.global_filter)}) "
                f"must equal command_index length ({n})"
            )
        canonical_phases = {
            "A-creation",
            "B-tdd",
            "B-build",
            "B-dcp",
            "B3-execute",
            "C-linkage",
            "D-f8-micro",
            "D5-review",
            "E-qa-micro",
            "F-stack-plan",
            "F2-stack-check",
            "G-deploy",
            "H-commit",
            "I-human-signoff",
            "I-human-mkt",
        }
        for phase_key, indices in self.phase_buckets.items():
            if phase_key not in canonical_phases:
                raise ValueError(
                    f"phase_buckets contains non-canonical phase key: {phase_key!r}"
                )
            for idx in indices:
                if not (0 <= idx < n):
                    raise ValueError(
                        f"phase_buckets[{phase_key!r}] index {idx} out of range "
                        f"[0, {n})"
                    )
        for module_id, module in self.modules.items():
            if len(module.filter) != n:
                raise ValueError(
                    f"modules[{module_id!r}].filter length ({len(module.filter)}) "
                    f"must equal command_index length ({n})"
                )
            for phase_key in module.loop_multiplier:
                if phase_key not in canonical_phases:
                    raise ValueError(
                        f"modules[{module_id!r}].loop_multiplier contains "
                        f"non-canonical phase key: {phase_key!r}"
                    )
        return self


class WithDialect(GenerateJsonSchema):
    """Schema generator that injects `$schema = draft/2020-12` explicitly.

    Usage:
        DcpCommandMatrix.model_json_schema(schema_generator=WithDialect)
    """

    def generate(self, schema: Any, mode: str = "validation") -> Dict[str, Any]:
        js = super().generate(schema, mode=mode)
        js["$schema"] = self.schema_dialect
        return js
