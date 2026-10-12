"""Provider-neutral contracts for Fuyao THS sector datasets.

The models deliberately keep THS observations separate from the canonical
Shenwan continuity domain.  They contain no HTTP, SQLAlchemy, FastAPI or
provider response types and can therefore be replayed from fixed fixtures.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Mapping


THS_TAGS = ("industry", "cn_concept", "region", "tszs")
THS_DATASETS = ("industry-ranking", "sector-turnover", "sector-breadth")
THS_CODE_PATTERN = re.compile(r"^\d{6}\.TI$")

ThsTag = Literal["industry", "cn_concept", "region", "tszs"]
ThsQuality = Literal["ok", "partial", "degraded", "insufficient", "missing", "failed"]
OperationStatus = Literal[
    "queued",
    "running",
    "success",
    "partial",
    "failed",
    "conflict",
]
OperationKind = Literal["catalog-sync", "turnover-backfill", "member-import"]


def _required_text(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _finite(value: float | int | None, field_name: str) -> float | None:
    if value is None:
        return None
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _non_negative(value: float | int | None, field_name: str) -> float | None:
    normalized = _finite(value, field_name)
    if normalized is not None and normalized < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return normalized


def normalize_thscode(value: str) -> str:
    normalized = _required_text(value, "thscode").upper()
    if not THS_CODE_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid THS code: {value}")
    return normalized


@dataclass(frozen=True, slots=True)
class ThsCatalogRevision:
    revision_id: str
    capability_revision: str
    provider_timestamp: datetime
    fetched_at: datetime
    tag_counts: Mapping[str, int]
    checksum: str
    source: str = "fuyao"

    def __post_init__(self) -> None:
        _required_text(self.revision_id, "revision_id")
        _required_text(self.capability_revision, "capability_revision")
        _required_text(self.checksum, "checksum")
        _required_text(self.source, "source")
        if set(self.tag_counts) != set(THS_TAGS):
            raise ValueError("catalog revision must include exactly the four supported THS tags")
        if any(not isinstance(count, int) or count <= 0 for count in self.tag_counts.values()):
            raise ValueError("catalog tag counts must be positive integers")
        if self.provider_timestamp.tzinfo is None or self.fetched_at.tzinfo is None:
            raise ValueError("catalog timestamps must be timezone-aware")

    @property
    def row_count(self) -> int:
        return sum(self.tag_counts.values())


@dataclass(frozen=True, slots=True)
class ThsCatalogRelation:
    revision_id: str
    tag: ThsTag
    thscode: str
    name: str

    def __post_init__(self) -> None:
        _required_text(self.revision_id, "revision_id")
        if self.tag not in THS_TAGS:
            raise ValueError(f"unsupported THS tag: {self.tag}")
        object.__setattr__(self, "thscode", normalize_thscode(self.thscode))
        _required_text(self.name, "name")


@dataclass(frozen=True, slots=True)
class ThsSnapshotFact:
    thscode: str
    name: str
    as_of: date
    provider_timestamp: datetime
    change_pct: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    turnover: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "thscode", normalize_thscode(self.thscode))
        _required_text(self.name, "name")
        if self.provider_timestamp.tzinfo is None:
            raise ValueError("snapshot provider_timestamp must be timezone-aware")
        _finite(self.change_pct, "change_pct")
        for field_name in ("open", "high", "low", "close", "volume", "turnover"):
            _non_negative(getattr(self, field_name), field_name)
        prices = (self.open, self.high, self.low, self.close)
        if self.high is not None and any(
            value is not None and self.high < value for value in (self.open, self.low, self.close)
        ):
            raise ValueError("high must not be below another OHLC value")
        if self.low is not None and any(
            value is not None and self.low > value for value in (self.open, self.high, self.close)
        ):
            raise ValueError("low must not be above another OHLC value")
        if all(value is None for value in prices) and self.volume is None and self.turnover is None:
            raise ValueError("snapshot fact requires at least one market value")


@dataclass(frozen=True, slots=True)
class ThsRankingRow:
    tag: ThsTag
    rank: int
    thscode: str
    name: str
    change_pct: float
    volume: float | None
    turnover: float | None
    catalog_revision: str
    as_of: date

    def __post_init__(self) -> None:
        if self.tag not in THS_TAGS:
            raise ValueError(f"unsupported THS tag: {self.tag}")
        if self.rank <= 0:
            raise ValueError("rank must be positive")
        object.__setattr__(self, "thscode", normalize_thscode(self.thscode))
        _required_text(self.name, "name")
        _required_text(self.catalog_revision, "catalog_revision")
        _finite(self.change_pct, "change_pct")
        _non_negative(self.volume, "volume")
        _non_negative(self.turnover, "turnover")


@dataclass(frozen=True, slots=True)
class ThsSectorBar:
    thscode: str
    trading_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    turnover: float | None
    source: str
    source_revision: str
    checksum: str
    fetched_at: datetime
    quality: ThsQuality = "ok"
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "thscode", normalize_thscode(self.thscode))
        for field_name in ("open", "high", "low", "close", "volume", "turnover"):
            _non_negative(getattr(self, field_name), field_name)
        if all(getattr(self, field_name) is None for field_name in ("open", "high", "low", "close", "volume", "turnover")):
            raise ValueError("sector bar cannot be entirely empty")
        if self.high is not None and any(
            value is not None and self.high < value for value in (self.open, self.low, self.close)
        ):
            raise ValueError("high must not be below another OHLC value")
        if self.low is not None and any(
            value is not None and self.low > value for value in (self.open, self.high, self.close)
        ):
            raise ValueError("low must not be above another OHLC value")
        _required_text(self.source, "source")
        _required_text(self.source_revision, "source_revision")
        _required_text(self.checksum, "checksum")
        if self.fetched_at.tzinfo is None:
            raise ValueError("bar fetched_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ThsBackfillRun:
    run_id: str
    thscodes: tuple[str, ...]
    start_date: date
    end_date: date
    capability_revision: str
    request_budget: int
    status: OperationStatus = "queued"
    requests_used: int = 0
    warning: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.run_id, "run_id")
        _required_text(self.capability_revision, "capability_revision")
        normalized = tuple(sorted({normalize_thscode(code) for code in self.thscodes}))
        if not normalized:
            raise ValueError("backfill run requires at least one THS code")
        if len(normalized) > 60:
            raise ValueError("backfill run accepts at most 60 THS codes")
        object.__setattr__(self, "thscodes", normalized)
        if self.start_date > self.end_date:
            raise ValueError("backfill date range must be ordered")
        if (self.end_date - self.start_date).days > 366 * 5 + 2:
            raise ValueError("backfill date range cannot exceed five years")
        if self.request_budget <= 0:
            raise ValueError("request_budget must be positive")
        if self.requests_used < 0 or self.requests_used > self.request_budget:
            raise ValueError("requests_used must be within request_budget")


@dataclass(frozen=True, slots=True)
class ThsBackfillCheckpoint:
    run_id: str
    thscode: str
    window_start: date
    window_end: date
    status: OperationStatus
    source_revision: str
    rows_written: int = 0
    rows_skipped: int = 0
    conflicts: int = 0
    warning: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.run_id, "run_id")
        object.__setattr__(self, "thscode", normalize_thscode(self.thscode))
        _required_text(self.source_revision, "source_revision")
        if self.window_start > self.window_end:
            raise ValueError("checkpoint window must be ordered")
        if any(value < 0 for value in (self.rows_written, self.rows_skipped, self.conflicts)):
            raise ValueError("checkpoint counts must be non-negative")


@dataclass(frozen=True, slots=True)
class ThsOperation:
    run_id: str
    kind: OperationKind
    status: OperationStatus
    capability_revision: str
    request_checksum: str
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    request_metadata: Mapping[str, Any] = field(default_factory=dict)
    progress: Mapping[str, Any] = field(default_factory=dict)
    result: Mapping[str, Any] = field(default_factory=dict)
    total_items: int = 0
    completed_items: int = 0
    failed_items: int = 0
    conflict_items: int = 0
    request_budget: int | None = None
    requests_used: int = 0
    warning: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.run_id, "run_id")
        if self.kind not in {"catalog-sync", "turnover-backfill", "member-import"}:
            raise ValueError(f"unsupported THS operation kind: {self.kind}")
        _required_text(self.capability_revision, "capability_revision")
        _required_text(self.request_checksum, "request_checksum")
        for field_name in ("requested_at", "started_at", "completed_at"):
            value = getattr(self, field_name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        counts = (
            self.total_items,
            self.completed_items,
            self.failed_items,
            self.conflict_items,
            self.requests_used,
        )
        if any(value < 0 for value in counts):
            raise ValueError("operation counts must be non-negative")
        if self.completed_items + self.failed_items + self.conflict_items > self.total_items:
            raise ValueError("completed, failed, and conflict items cannot exceed total_items")
        if self.request_budget is not None:
            if self.request_budget <= 0:
                raise ValueError("request_budget must be positive")
            if self.requests_used > self.request_budget:
                raise ValueError("requests_used must be within request_budget")
        _validate_redacted_metadata(self.request_metadata)


def _validate_redacted_metadata(value: Any) -> None:
    forbidden_keys = {
        "api_key",
        "apikey",
        "authorization",
        "headers",
        "password",
        "presigned_url",
        "raw_payload",
        "raw_response",
        "secret",
        "signed_url",
        "token",
        "url",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in forbidden_keys:
                raise ValueError(f"operation request metadata contains sensitive key: {key}")
            _validate_redacted_metadata(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _validate_redacted_metadata(item)
    elif isinstance(value, str) and "://" in value:
        raise ValueError("operation request metadata cannot contain a URL")


@dataclass(frozen=True, slots=True)
class ThsMemberObservation:
    security_id: str
    change_pct: float | None
    close: float | None
    adjusted_closes: tuple[float, ...]
    turnover: float | None
    limit_up: bool | None = None
    limit_down: bool | None = None
    lineage: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required_text(self.security_id, "security_id")
        _finite(self.change_pct, "change_pct")
        _non_negative(self.close, "close")
        _non_negative(self.turnover, "turnover")
        if any(_non_negative(value, "adjusted_close") is None for value in self.adjusted_closes):
            raise ValueError("adjusted close history cannot contain null values")
        if self.limit_up is True and self.limit_down is True:
            raise ValueError("a member cannot be both limit-up and limit-down")


@dataclass(frozen=True, slots=True)
class ThsMemberDailyFact:
    security_id: str
    trading_date: date
    original_open: float | None
    original_high: float | None
    original_low: float | None
    original_close: float | None
    adjusted_close: float | None
    adjustment_factor: float | None
    volume: float | None
    turnover: float | None
    quality: ThsQuality
    source_revision: str
    checksum: str
    field_lineage: Mapping[str, str]
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required_text(self.security_id, "security_id")
        _required_text(self.source_revision, "source_revision")
        _required_text(self.checksum, "checksum")
        for field_name in (
            "original_open",
            "original_high",
            "original_low",
            "original_close",
            "adjusted_close",
            "adjustment_factor",
            "volume",
            "turnover",
        ):
            _non_negative(getattr(self, field_name), field_name)
        if self.adjusted_close is not None and self.adjustment_factor is None:
            raise ValueError("adjusted_close requires an adjustment_factor")
        if not self.field_lineage:
            raise ValueError("member fact requires field lineage")


@dataclass(frozen=True, slots=True)
class ThsSectorMembership:
    thscode: str
    member_security_id: str
    member_name: str
    as_of: date
    provider_timestamp: datetime
    fetched_at: datetime
    source_revision: str
    checksum: str
    quality: ThsQuality = "ok"
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "thscode", normalize_thscode(self.thscode))
        _required_text(self.member_security_id, "member_security_id")
        _required_text(self.member_name, "member_name")
        _required_text(self.source_revision, "source_revision")
        _required_text(self.checksum, "checksum")
        if self.provider_timestamp.tzinfo is None or self.fetched_at.tzinfo is None:
            raise ValueError("membership timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ThsMemberRanking:
    security_id: str
    value: float

    def __post_init__(self) -> None:
        _required_text(self.security_id, "security_id")
        _finite(self.value, "ranking value")


@dataclass(frozen=True, slots=True)
class ThsSectorBreadth:
    thscode: str
    as_of: date
    selection_reasons: tuple[str, ...]
    member_count: int
    valid_direction_count: int
    advance_count: int
    decline_count: int
    flat_count: int
    advance_ratio: float | None
    advance_decline_spread_ratio: float | None
    median_change_pct: float | None
    valid_ma20_count: int
    close_above_ma20_count: int
    ma20_breadth: float | None
    limit_up_count: int | None
    limit_down_count: int | None
    top_by_turnover: tuple[ThsMemberRanking, ...]
    top_by_gain: tuple[ThsMemberRanking, ...]
    max_member_turnover_contribution: float | None
    diffusion_rate: float | None
    quality: ThsQuality
    warnings: tuple[str, ...] = ()
    lineage: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "thscode", normalize_thscode(self.thscode))
        if not self.selection_reasons:
            raise ValueError("sector breadth requires a selection reason")
        counts = (
            self.member_count,
            self.valid_direction_count,
            self.advance_count,
            self.decline_count,
            self.flat_count,
            self.valid_ma20_count,
            self.close_above_ma20_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("breadth counts must be non-negative")
        if self.advance_count + self.decline_count + self.flat_count != self.valid_direction_count:
            raise ValueError("direction counts must reconcile")
        if self.valid_direction_count > self.member_count or self.valid_ma20_count > self.member_count:
            raise ValueError("eligible counts cannot exceed member_count")
        if self.close_above_ma20_count > self.valid_ma20_count:
            raise ValueError("close_above_ma20_count cannot exceed valid_ma20_count")
        for field_name in (
            "advance_ratio",
            "ma20_breadth",
            "max_member_turnover_contribution",
            "diffusion_rate",
        ):
            value = _finite(getattr(self, field_name), field_name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field_name} must be within [0, 1]")
        spread = _finite(self.advance_decline_spread_ratio, "advance_decline_spread_ratio")
        if spread is not None and not -1 <= spread <= 1:
            raise ValueError("advance_decline_spread_ratio must be within [-1, 1]")
        _finite(self.median_change_pct, "median_change_pct")


__all__ = [
    "OperationStatus",
    "OperationKind",
    "THS_CODE_PATTERN",
    "THS_DATASETS",
    "THS_TAGS",
    "ThsBackfillCheckpoint",
    "ThsBackfillRun",
    "ThsCatalogRelation",
    "ThsCatalogRevision",
    "ThsMemberObservation",
    "ThsMemberDailyFact",
    "ThsMemberRanking",
    "ThsOperation",
    "ThsSectorMembership",
    "ThsQuality",
    "ThsRankingRow",
    "ThsSectorBar",
    "ThsSectorBreadth",
    "ThsSnapshotFact",
    "ThsTag",
    "normalize_thscode",
]
