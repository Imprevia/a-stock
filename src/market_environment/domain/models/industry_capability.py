"""Capability contracts for the point-in-time industry data path.

The existing :class:`ProviderCapabilityReport` is kept for the five normal
collection datasets.  This module is deliberately separate because industry
analysis approves a dataset/source/revision tuple, not a provider globally,
and needs explicit coverage, rights and negative-case evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Literal, Mapping


IndustryCapabilityStatus = Literal["eligible", "ineligible", "unverified"]
INDUSTRY_CAPABILITY_DATASETS = (
    "shenwan-taxonomy",
    "shenwan-point-in-time-membership",
    "stock-adjusted-price",
    "tdx-original-daily-facts",
    "benchmark-history",
)
INDUSTRY_CAPABILITY_SCHEMA_VERSION = 1

_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?key|token|secret|password|authorization|cookie|credential)",
    re.I,
)
_SECRET_VALUE = re.compile(r"bearer\s+[A-Za-z0-9_\-]{12,}", re.I)


class IndustryCapabilityError(ValueError):
    """Raised when an industry capability report cannot be trusted."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _checksum(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _redacted(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(k): _redacted(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redacted(v, key=key) for v in value]
    if isinstance(value, str) and _SECRET_VALUE.fullmatch(value.strip()):
        return "[redacted]"
    return value


def _contains_sensitive(value: Any, *, key: str = "") -> bool:
    if _SECRET_KEY.search(key):
        return True
    if isinstance(value, Mapping):
        return any(_contains_sensitive(v, key=str(k)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive(v, key=key) for v in value)
    return isinstance(value, str) and bool(_SECRET_VALUE.fullmatch(value.strip()))


@dataclass(frozen=True, slots=True)
class IndustryCapabilityReport:
    """One reviewed capability for one dataset, source and revision."""

    dataset: str
    source: str
    revision: str
    status: IndustryCapabilityStatus
    requested_dates: tuple[date, ...] = ()
    actual_dates: tuple[date, ...] = ()
    market_coverage: Mapping[str, Any] = field(default_factory=dict)
    field_semantics: Mapping[str, Any] = field(default_factory=dict)
    pagination: Mapping[str, Any] = field(default_factory=dict)
    permission: Mapping[str, Any] = field(default_factory=dict)
    rate_limit: Mapping[str, Any] = field(default_factory=dict)
    data_rights: Mapping[str, Any] = field(default_factory=dict)
    negative_cases: tuple[str, ...] = ()
    sample_count: int = 0
    warnings: tuple[str, ...] = ()
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: int = INDUSTRY_CAPABILITY_SCHEMA_VERSION
    checksum: str = ""

    def __post_init__(self) -> None:
        if self.dataset not in INDUSTRY_CAPABILITY_DATASETS:
            raise IndustryCapabilityError(f"unsupported industry capability dataset: {self.dataset}")
        if not self.source.strip() or not self.revision.strip():
            raise IndustryCapabilityError("capability source and revision are required")
        if self.status not in {"eligible", "ineligible", "unverified"}:
            raise IndustryCapabilityError(f"unsupported capability status: {self.status}")
        if self.sample_count < 0:
            raise IndustryCapabilityError("sample_count must be non-negative")
        if self.schema_version != INDUSTRY_CAPABILITY_SCHEMA_VERSION:
            raise IndustryCapabilityError(f"unsupported capability schema version: {self.schema_version}")
        if any(not isinstance(value, date) for value in (*self.requested_dates, *self.actual_dates)):
            raise IndustryCapabilityError("capability dates must be date values")
        if self.status == "eligible":
            self._validate_eligible()

    def _validate_eligible(self) -> None:
        if not self.requested_dates or not self.actual_dates:
            raise IndustryCapabilityError("eligible capability requires requested and actual dates")
        if tuple(self.requested_dates) != tuple(self.actual_dates):
            raise IndustryCapabilityError("eligible capability date evidence must match exactly")
        if not self.market_coverage or not self.field_semantics:
            raise IndustryCapabilityError("eligible capability requires market and field coverage")
        if not self.pagination or self.pagination.get("complete") is not True:
            raise IndustryCapabilityError("eligible capability requires complete pagination evidence")
        if self.permission.get("approved") is not True:
            raise IndustryCapabilityError("eligible capability requires approved permission evidence")
        if self.rate_limit.get("bounded") is not True:
            raise IndustryCapabilityError("eligible capability requires bounded rate-limit evidence")
        if self.data_rights.get("reviewed") is not True:
            raise IndustryCapabilityError("eligible capability requires reviewed data-rights evidence")
        if not self.negative_cases:
            raise IndustryCapabilityError("eligible capability requires negative-case evidence")
        if self.sample_count < 1:
            raise IndustryCapabilityError("eligible capability requires observations")

    def logical_dict(self) -> dict[str, Any]:
        checked_at = self.checked_at.astimezone(timezone.utc) if self.checked_at.tzinfo else self.checked_at.replace(tzinfo=timezone.utc)
        return {
            "dataset": self.dataset,
            "source": self.source,
            "revision": self.revision,
            "status": self.status,
            "requested_dates": [value.isoformat() for value in self.requested_dates],
            "actual_dates": [value.isoformat() for value in self.actual_dates],
            "market_coverage": dict(self.market_coverage),
            "field_semantics": dict(self.field_semantics),
            "pagination": dict(self.pagination),
            "permission": dict(self.permission),
            "rate_limit": dict(self.rate_limit),
            "data_rights": dict(self.data_rights),
            "negative_cases": list(self.negative_cases),
            "sample_count": int(self.sample_count),
            "warnings": list(self.warnings),
            "checked_at": checked_at.isoformat(),
            "schema_version": self.schema_version,
        }

    def normalized(self) -> "IndustryCapabilityReport":
        value = replace(self, checked_at=self.checked_at.astimezone(timezone.utc) if self.checked_at.tzinfo else self.checked_at.replace(tzinfo=timezone.utc))
        return replace(value, checksum=value.checksum or _checksum(value.logical_dict()))

    def to_dict(self, *, redacted: bool = False) -> dict[str, Any]:
        value = self.normalized()
        result = {**value.logical_dict(), "checksum": value.checksum}
        return _redacted(result) if redacted else result

    def redacted_dict(self) -> dict[str, Any]:
        return self.to_dict(redacted=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IndustryCapabilityReport":
        if _contains_sensitive(value):
            raise IndustryCapabilityError("capability report contains sensitive material")
        supplied_checksum = str(value.get("checksum", ""))
        try:
            checked_at = datetime.fromisoformat(str(value.get("checked_at")))
            report = cls(
                dataset=str(value.get("dataset", "")),
                source=str(value.get("source", "")),
                revision=str(value.get("revision", "")),
                status=value.get("status", "unverified"),  # type: ignore[arg-type]
                requested_dates=tuple(date.fromisoformat(str(item)) for item in value.get("requested_dates", ())),
                actual_dates=tuple(date.fromisoformat(str(item)) for item in value.get("actual_dates", ())),
                market_coverage=dict(value.get("market_coverage") or {}),
                field_semantics=dict(value.get("field_semantics") or {}),
                pagination=dict(value.get("pagination") or {}),
                permission=dict(value.get("permission") or {}),
                rate_limit=dict(value.get("rate_limit") or {}),
                data_rights=dict(value.get("data_rights") or {}),
                negative_cases=tuple(str(item) for item in value.get("negative_cases", ())),
                sample_count=int(value.get("sample_count", 0)),
                warnings=tuple(str(item) for item in value.get("warnings", ())),
                checked_at=checked_at,
                schema_version=int(value.get("schema_version", INDUSTRY_CAPABILITY_SCHEMA_VERSION)),
            ).normalized()
        except (TypeError, ValueError) as exc:
            raise IndustryCapabilityError("capability report structure is invalid") from exc
        if supplied_checksum and report.checksum != supplied_checksum:
            raise IndustryCapabilityError("capability report checksum mismatch")
        return report


CapabilityContract = IndustryCapabilityReport
SourceCapabilityReport = IndustryCapabilityReport


__all__ = [
    "CapabilityContract",
    "INDUSTRY_CAPABILITY_DATASETS",
    "INDUSTRY_CAPABILITY_SCHEMA_VERSION",
    "IndustryCapabilityError",
    "IndustryCapabilityReport",
    "IndustryCapabilityStatus",
    "SourceCapabilityReport",
]
