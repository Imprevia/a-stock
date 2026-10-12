"""Immutable, provider-neutral models for Chapter 05 continuity analysis.

The models in this module intentionally contain no SQL, HTTP or provider
types.  They are suitable for fixture replay, PostgreSQL adapters and the
provider-free materialization/read paths.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Literal, Mapping, Sequence


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _checksum(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _finite(value: float | int | None, name: str) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


QualityStatus = Literal[
    "ok",
    "partial",
    "degraded",
    "reduced-confidence",
    "insufficient",
    "missing",
    "failed",
]
BackfillAttemptStatus = Literal[
    "success", "partial", "failed-retained", "failed-missing", "insufficient"
]
CandidateStage = Literal[
    "insufficient",
    "high-level-crowding",
    "mainline-confirmed",
    "mainline-candidate",
    "one-day-pulse",
    "rotation-or-ebb",
]


@dataclass(frozen=True, slots=True)
class Lineage:
    requested_as_of: date
    actual_as_of: date | None
    source: str
    source_revision: str
    schema_version: int
    checksum: str
    data_version: str | None = None
    classification_version: str | None = None
    membership_version: str | None = None
    universe_version: str | None = None
    adjustment_version: str | None = None
    benchmark_version: str | None = None
    calculation_version: str | None = None
    fetched_at: datetime | None = None
    warnings: tuple[str, ...] = ()
    quality_status: QualityStatus = "ok"
    observation_count: int = 0
    field_availability: Mapping[str, bool] = field(default_factory=dict)
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.source_revision.strip() or not self.checksum.strip():
            raise ValueError("lineage source, revision and checksum are required")
        if self.actual_as_of is not None and self.actual_as_of != self.requested_as_of:
            raise ValueError("actual_as_of must match requested_as_of")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if self.observation_count < 0:
            raise ValueError("observation_count must be non-negative")
        if self.quality_status == "ok" and self.actual_as_of is None:
            raise ValueError("ok lineage requires a proven actual_as_of")
        if self.quality_status == "ok" and any(
            available is False for available in self.field_availability.values()
        ):
            raise ValueError("ok lineage cannot report missing critical fields")


@dataclass(frozen=True, slots=True)
class TaxonomyRevision:
    taxonomy_version: str
    taxonomy_family: Literal["shenwan"]
    taxonomy_level: int
    source_revision: str
    effective_from: date
    effective_to: date | None
    checksum: str
    imported_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.taxonomy_family != "shenwan" or self.taxonomy_level != 1:
            raise ValueError("only Shenwan level 1 taxonomy is supported")
        if not self.taxonomy_version.strip() or not self.source_revision.strip() or not self.checksum.strip():
            raise ValueError("taxonomy version, source revision and checksum are required")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("taxonomy effective interval must be ordered")


@dataclass(frozen=True, slots=True)
class IndustryIdentity:
    industry_id: str
    display_name: str
    taxonomy: TaxonomyRevision

    def __post_init__(self) -> None:
        if not self.industry_id.strip() or not self.display_name.strip():
            raise ValueError("industry identity requires id and display name")


@dataclass(frozen=True, slots=True)
class MembershipInterval:
    security_id: str
    industry_id: str
    taxonomy_version: str
    valid_from: date
    valid_to: date | None
    source_revision: str
    evidence_checksum: str

    def __post_init__(self) -> None:
        if not self.security_id.strip() or not self.industry_id.strip():
            raise ValueError("membership requires security and industry IDs")
        if not self.taxonomy_version.strip() or not self.source_revision.strip() or not self.evidence_checksum.strip():
            raise ValueError("membership lineage is required")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("membership interval must be ordered")

    def covers(self, as_of: date) -> bool:
        return self.valid_from <= as_of and (self.valid_to is None or as_of < self.valid_to)


@dataclass(frozen=True, slots=True)
class SecurityDailyFact:
    security_id: str
    as_of: date
    market: Literal["sh", "sz", "bj"]
    original_close: float | None
    previous_close: float | None
    adjusted_close: float | None
    amount: float | None
    volume: int | None
    change_pct: float | None
    eligible: bool
    lineage: Lineage
    exclusion_reason: str | None = None
    original_open: float | None = None
    original_high: float | None = None
    original_low: float | None = None
    adjusted_previous_close: float | None = None

    def __post_init__(self) -> None:
        if self.lineage.requested_as_of != self.as_of:
            raise ValueError("fact lineage date mismatch")
        for name in (
            "original_open", "original_high", "original_low", "original_close",
            "previous_close", "adjusted_previous_close", "adjusted_close", "amount", "change_pct",
        ):
            _finite(getattr(self, name), name)
        if self.amount is not None and self.amount < 0:
            raise ValueError("amount must be non-negative")
        if self.volume is not None and self.volume < 0:
            raise ValueError("volume must be non-negative")
        if not self.eligible and not self.exclusion_reason:
            raise ValueError("ineligible facts require an exclusion reason")


@dataclass(frozen=True, slots=True)
class BenchmarkFact:
    benchmark_id: Literal["ordinary-a-share-equal-weight-v1"]
    as_of: date
    return_value: float | None
    eligible_count: int
    excluded_count: int
    session_dates: tuple[date, ...]
    lineage: Lineage

    def __post_init__(self) -> None:
        if self.benchmark_id != "ordinary-a-share-equal-weight-v1":
            raise ValueError("unsupported benchmark identity")
        if self.eligible_count < 0 or self.excluded_count < 0:
            raise ValueError("benchmark counts must be non-negative")
        _finite(self.return_value, "benchmark return")
        if self.lineage.requested_as_of != self.as_of:
            raise ValueError("benchmark lineage date mismatch")


@dataclass(frozen=True, slots=True)
class IndustryAggregate:
    industry_id: str
    as_of: date
    member_count: int
    eligible_return_count: int
    eligible_amount_count: int
    eligible_ma20_count: int
    industry_return: float | None
    original_amount: float | None
    breadth_ratio: float | None
    advance_count: int | None
    decline_count: int | None
    flat_count: int | None
    limit_up_count: int | None
    limit_down_count: int | None
    excluded_reasons: Mapping[str, int]
    lineage: Lineage
    input_checksum: str | None = None

    def __post_init__(self) -> None:
        for name in ("member_count", "eligible_return_count", "eligible_amount_count", "eligible_ma20_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        _finite(self.industry_return, "industry_return")
        _finite(self.original_amount, "original_amount")
        _finite(self.breadth_ratio, "breadth_ratio")
        if self.breadth_ratio is not None and not 0 <= self.breadth_ratio <= 1:
            raise ValueError("breadth_ratio must be within [0, 1]")
        if self.lineage.requested_as_of != self.as_of:
            raise ValueError("aggregate lineage date mismatch")


@dataclass(frozen=True, slots=True)
class MetricTrace:
    rule_id: str
    value: float | int | None
    percentile: float | None
    score: float | int | None
    status: QualityStatus
    weight: float
    original_weight: float
    normalized_weight: float | None
    observations: int
    required_observations: int = 60
    window_days: int = 250
    missing_reason: str | None = None
    sample_dates: tuple[date, ...] = ()
    actual_date_range: tuple[date, date] | None = None
    gaps: tuple[date, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or self.observations < 0 or self.required_observations < 0:
            raise ValueError("metric trace identity/counts are invalid")
        if self.weight < 0 or self.original_weight < 0:
            raise ValueError("metric weights must be non-negative")
        _finite(float(self.value) if isinstance(self.value, (float, int)) else None, "metric value")
        _finite(self.percentile, "metric percentile")
        if self.percentile is not None and not 0 <= self.percentile <= 1:
            raise ValueError("metric percentile must be within [0, 1]")
        if self.actual_date_range is not None and self.actual_date_range[1] < self.actual_date_range[0]:
            raise ValueError("metric actual date range must be ordered")


@dataclass(frozen=True, slots=True)
class InternalStructure:
    effective_member_count: int
    advancing_count: int | None
    declining_count: int | None
    flat_count: int | None
    limit_up_count: int | None
    limit_down_count: int | None
    top_by_turnover: tuple[Mapping[str, Any], ...] = ()
    top_by_return: tuple[Mapping[str, Any], ...] = ()
    top_security_turnover_contribution: float | None = None
    diffusion_ratio: float | None = None

    def __post_init__(self) -> None:
        if self.effective_member_count < 0:
            raise ValueError("effective member count must be non-negative")
        _finite(self.top_security_turnover_contribution, "top security turnover contribution")
        _finite(self.diffusion_ratio, "diffusion ratio")


@dataclass(frozen=True, slots=True)
class CandidateIndustry:
    industry_id: str
    display_name: str
    stage: CandidateStage
    total_score: float | None
    core_scores: Mapping[str, float | None]
    rule_traces: tuple[MetricTrace, ...]
    crowding_risk: bool | None
    vetoes: tuple[str, ...]
    internal_structure: InternalStructure | None
    confirmation_streak: int = 0

    def __post_init__(self) -> None:
        if not self.industry_id.strip() or not self.display_name.strip():
            raise ValueError("candidate identity is required")
        if self.confirmation_streak < 0:
            raise ValueError("confirmation streak must be non-negative")
        _finite(self.total_score, "candidate total score")


@dataclass(frozen=True, slots=True)
class UniqueValidation:
    candidate_industry: str | None
    candidate_name: str | None
    stage: CandidateStage
    persistence_evidence: str
    breadth_evidence: str
    turnover_evidence: str
    internal_structure: str
    target: str
    confirmation_condition: str
    invalidation_condition: str

    def render(self) -> str:
        return (
            f"候选板块：{self.candidate_name or '--'}；阶段：{self.stage}。\n"
            f"持续性证据：{self.persistence_evidence}；宽度证据：{self.breadth_evidence}；"
            f"成交证据：{self.turnover_evidence}；内部结构：{self.internal_structure}。\n"
            f"下一交易日只验证：{self.target}\n"
            f"确认条件：{self.confirmation_condition}；失效条件：{self.invalidation_condition}。"
        )

    def __post_init__(self) -> None:
        for name in (
            "persistence_evidence", "breadth_evidence", "turnover_evidence",
            "internal_structure", "target", "confirmation_condition", "invalidation_condition",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.candidate_industry is None and self.stage != "insufficient":
            raise ValueError("null candidate industry requires insufficient stage")


@dataclass(frozen=True, slots=True)
class SectorContinuityResult:
    as_of: date
    status: QualityStatus
    confidence: Literal["high", "medium", "low", "insufficient"]
    coverage: float | None
    metrics: tuple[MetricTrace, ...]
    candidates: tuple[CandidateIndustry, ...]
    validation: UniqueValidation
    lineage: Lineage
    missing_inputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.lineage.requested_as_of != self.as_of:
            raise ValueError("continuity lineage date mismatch")
        if len(self.candidates) > 3:
            raise ValueError("at most three candidates are supported")
        if self.validation.candidate_industry is not None:
            if not self.candidates or self.validation.candidate_industry != self.candidates[0].industry_id:
                raise ValueError("validation must target the first ranked candidate")
        if self.validation.candidate_industry is None and self.validation.stage != "insufficient":
            raise ValueError("no candidate requires insufficient validation stage")
        _finite(self.coverage, "continuity coverage")
        if self.coverage is not None and not 0 <= self.coverage <= 1:
            raise ValueError("continuity coverage must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class BackfillDateAttempt:
    run_id: str
    as_of: date
    status: BackfillAttemptStatus
    requested_at: datetime
    completed_at: datetime | None = None
    retry_eligible: bool = True
    warning: str | None = None
    compatible_result_checksum: str | None = None


@dataclass(frozen=True, slots=True)
class BackfillRun:
    run_id: str
    as_of: date
    session_dates: tuple[date, ...]
    source_revisions: Mapping[str, str]
    calculation_version: str
    status: Literal["queued", "running", "success", "partial", "failed"]
    attempts: tuple[BackfillDateAttempt, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.calculation_version.strip():
            raise ValueError("backfill run identity is required")
        if not self.session_dates or tuple(sorted(set(self.session_dates))) != self.session_dates:
            raise ValueError("backfill session dates must be non-empty, unique and ordered")
        if self.as_of != self.session_dates[-1]:
            raise ValueError("backfill as_of must be the last requested session")


__all__ = [
    "BackfillDateAttempt", "BackfillRun", "BenchmarkFact", "CandidateIndustry",
    "CandidateStage", "IndustryAggregate", "IndustryIdentity", "InternalStructure",
    "Lineage", "MembershipInterval", "MetricTrace", "QualityStatus", "SectorContinuityResult",
    "SecurityDailyFact", "TaxonomyRevision", "UniqueValidation",
]
