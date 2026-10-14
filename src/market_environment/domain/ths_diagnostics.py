"""Provider-neutral values used by bounded THS collection diagnostics."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Sequence


THS_DIAGNOSTIC_SAMPLE_LIMIT = 20
THS_DIAGNOSTIC_BLOCKED_BY_LIMIT = 8

ThsReasonCode = Literal[
    "THS_LIVE_VALUES_MISSING",
    "THS_DAILY_SNAPSHOT_INSUFFICIENT",
    "THS_CATALOG_REVISION_COLLISION",
    "THS_DEPENDENCY_INSUFFICIENT",
    "THS_DEPENDENCY_REVISION_MISMATCH",
]
THS_REASON_CODES: frozenset[str] = frozenset(
    {
        "THS_LIVE_VALUES_MISSING",
        "THS_DAILY_SNAPSHOT_INSUFFICIENT",
        "THS_CATALOG_REVISION_COLLISION",
        "THS_DEPENDENCY_INSUFFICIENT",
        "THS_DEPENDENCY_REVISION_MISMATCH",
    }
)

_SAFE_CODE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_URL = re.compile(r"(?i)\b(?:https?|postgres(?:ql)?|mysql|redis)://[^\s]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?key|token|secret|password|authorization|"
    r"cookie|credential)\s*[:=]\s*[^\s,;]+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/=]{8,}")


def _bounded_text(value: object, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    normalized = " ".join(_CONTROL.sub(" ", value).split())
    normalized = _URL.sub("[redacted-url]", normalized)
    normalized = _SECRET_ASSIGNMENT.sub("[redacted]", normalized)
    normalized = _BEARER.sub("[redacted]", normalized)
    if len(normalized) > maximum:
        normalized = normalized[: maximum - 1].rstrip() + "…"
    return normalized


def _optional_safe_id(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    text = _bounded_text(value, field_name=field_name, maximum=256)
    if "://" in text or not _SAFE_CODE.fullmatch(text):
        raise ValueError(f"{field_name} must be an opaque identifier")
    return text


def _count(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _exact_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("exactDate must use YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("exactDate must use YYYY-MM-DD")
    return parsed


def _code_sample(values: Sequence[object], *, field_name: str) -> tuple[str, ...]:
    codes: list[str] = []
    for value in values:
        code = _optional_safe_id(value, field_name=field_name)
        if code is None:
            raise ValueError(f"{field_name} cannot contain null")
        codes.append(code)
    return tuple(sorted(set(codes))[:THS_DIAGNOSTIC_SAMPLE_LIMIT])


@dataclass(frozen=True, slots=True)
class ThsBlockedBy:
    dataset: str
    status: str
    reason_code: ThsReasonCode | None = None
    exact_date: date | None = None
    catalog_revision_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dataset",
            _bounded_text(self.dataset, field_name="blockedBy.dataset", maximum=64),
        )
        object.__setattr__(
            self,
            "status",
            _bounded_text(self.status, field_name="blockedBy.status", maximum=64),
        )
        if self.reason_code is not None and self.reason_code not in THS_REASON_CODES:
            raise ValueError("blockedBy.reasonCode is unsupported")
        if self.exact_date is not None:
            object.__setattr__(self, "exact_date", _exact_date(self.exact_date))
        object.__setattr__(
            self,
            "catalog_revision_id",
            _optional_safe_id(
                self.catalog_revision_id,
                field_name="blockedBy.catalogRevisionId",
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"dataset": self.dataset, "status": self.status}
        if self.reason_code is not None:
            result["reasonCode"] = self.reason_code
        if self.exact_date is not None:
            result["exactDate"] = self.exact_date.isoformat()
        if self.catalog_revision_id is not None:
            result["catalogRevisionId"] = self.catalog_revision_id
        return result


@dataclass(frozen=True, slots=True)
class ThsDiagnostic:
    reason_code: ThsReasonCode
    message: str
    failure_stage: str
    exact_date: date
    retryable: bool
    capability_revision: str | None = None
    catalog_revision_id: str | None = None
    expected_count: int | None = None
    observed_count: int | None = None
    usable_count: int | None = None
    rankable_count: int | None = None
    bar_count: int | None = None
    missing_live_count: int | None = None
    missing_live_codes: tuple[str, ...] = ()
    missing_ranking_count: int | None = None
    missing_ranking_codes: tuple[str, ...] = ()
    existing_checksum: str | None = None
    observed_checksum: str | None = None
    blocked_by: tuple[ThsBlockedBy, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.reason_code not in THS_REASON_CODES:
            raise ValueError("reason_code is unsupported")
        object.__setattr__(
            self,
            "message",
            _bounded_text(self.message, field_name="message", maximum=500),
        )
        object.__setattr__(
            self,
            "failure_stage",
            _bounded_text(
                self.failure_stage,
                field_name="failure_stage",
                maximum=64,
            ),
        )
        object.__setattr__(self, "exact_date", _exact_date(self.exact_date))
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be boolean")
        object.__setattr__(
            self,
            "capability_revision",
            _optional_safe_id(
                self.capability_revision,
                field_name="capability_revision",
            ),
        )
        object.__setattr__(
            self,
            "catalog_revision_id",
            _optional_safe_id(
                self.catalog_revision_id,
                field_name="catalog_revision_id",
            ),
        )
        for name in (
            "expected_count",
            "observed_count",
            "usable_count",
            "rankable_count",
            "bar_count",
            "missing_live_count",
            "missing_ranking_count",
        ):
            object.__setattr__(
                self,
                name,
                _count(getattr(self, name), field_name=name),
            )
        raw_missing_live_codes = tuple(self.missing_live_codes)
        raw_missing_ranking_codes = tuple(self.missing_ranking_codes)
        if self.missing_live_count is None and raw_missing_live_codes:
            object.__setattr__(
                self,
                "missing_live_count",
                len({str(code) for code in raw_missing_live_codes}),
            )
        if self.missing_ranking_count is None and raw_missing_ranking_codes:
            object.__setattr__(
                self,
                "missing_ranking_count",
                len({str(code) for code in raw_missing_ranking_codes}),
            )
        object.__setattr__(
            self,
            "missing_live_codes",
            _code_sample(raw_missing_live_codes, field_name="missing_live_codes"),
        )
        object.__setattr__(
            self,
            "missing_ranking_codes",
            _code_sample(
                raw_missing_ranking_codes,
                field_name="missing_ranking_codes",
            ),
        )
        if (
            self.missing_live_count is not None
            and self.missing_live_count < len(self.missing_live_codes)
        ):
            raise ValueError("missing_live_count cannot be smaller than its sample")
        if (
            self.missing_ranking_count is not None
            and self.missing_ranking_count < len(self.missing_ranking_codes)
        ):
            raise ValueError("missing_ranking_count cannot be smaller than its sample")
        for name in ("existing_checksum", "observed_checksum"):
            object.__setattr__(
                self,
                name,
                _optional_safe_id(getattr(self, name), field_name=name),
            )
        normalized_blocked_by: list[ThsBlockedBy] = []
        for item in self.blocked_by[:THS_DIAGNOSTIC_BLOCKED_BY_LIMIT]:
            if not isinstance(item, ThsBlockedBy):
                raise ValueError("blocked_by entries must be ThsBlockedBy values")
            normalized_blocked_by.append(item)
        object.__setattr__(self, "blocked_by", tuple(normalized_blocked_by))

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "reasonCode": self.reason_code,
            "message": self.message,
            "failureStage": self.failure_stage,
            "exactDate": self.exact_date.isoformat(),
            "retryable": self.retryable,
        }
        optional = {
            "capabilityRevision": self.capability_revision,
            "catalogRevisionId": self.catalog_revision_id,
            "expectedCount": self.expected_count,
            "observedCount": self.observed_count,
            "usableCount": self.usable_count,
            "rankableCount": self.rankable_count,
            "barCount": self.bar_count,
            "missingLiveCount": self.missing_live_count,
            "missingRankingCount": self.missing_ranking_count,
            "existingChecksum": self.existing_checksum,
            "observedChecksum": self.observed_checksum,
        }
        result.update({key: value for key, value in optional.items() if value is not None})
        if self.missing_live_codes:
            result["missingLiveCodes"] = list(self.missing_live_codes)
        if self.missing_ranking_codes:
            result["missingRankingCodes"] = list(self.missing_ranking_codes)
        if self.blocked_by:
            result["blockedBy"] = [item.as_dict() for item in self.blocked_by]
        return result


__all__ = [
    "THS_DIAGNOSTIC_BLOCKED_BY_LIMIT",
    "THS_DIAGNOSTIC_SAMPLE_LIMIT",
    "THS_REASON_CODES",
    "ThsBlockedBy",
    "ThsDiagnostic",
    "ThsReasonCode",
]
