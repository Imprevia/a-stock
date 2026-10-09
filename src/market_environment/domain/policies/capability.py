"""Fail-closed evidence policies for capability report promotion."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..models.capability import ProviderCapabilityReport


CapabilityEvidencePolicy = Callable[[ProviderCapabilityReport, date], None]
CapabilityEvidencePolicyKey = tuple[str, str, str]

FUYAO_SECTORS_V2 = ("fuyao", "sectors", "fuyao-market-v2")
_FUYAO_SECTOR_ENDPOINTS = {
    "calendar": "/api/a-share/calendar/trading-days",
    "catalog": "/api/a-share-index/catalog/ths-index-list",
    "snapshot": "/api/a-share-index/prices/snapshot",
}
_FUYAO_SECTOR_FIELDS = ("code", "name", "changePct", "amount")
_FUYAO_UNSUPPORTED_FIELDS = (
    "mainNet",
    "mainNetPct",
    "upCount",
    "downCount",
    "leader",
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class CapabilityEvidenceError(ValueError):
    """Raised when a report cannot prove its frozen provider contract."""


def capability_evidence_policies() -> Mapping[
    CapabilityEvidencePolicyKey, CapabilityEvidencePolicy
]:
    return {FUYAO_SECTORS_V2: validate_fuyao_sectors_v2}


def validate_fuyao_sectors_v2(
    report: ProviderCapabilityReport,
    envelope_as_of: date,
) -> None:
    if (report.provider, report.dataset, report.revision) != FUYAO_SECTORS_V2:
        raise CapabilityEvidenceError("capability evidence policy identity mismatch")
    if report.endpoint != _FUYAO_SECTOR_ENDPOINTS["snapshot"]:
        raise CapabilityEvidenceError("capability endpoint evidence is incomplete")

    endpoints = _mapping(report.field_coverage.get("endpoints"), "endpoint")
    if any(
        endpoints.get(name) != endpoint
        for name, endpoint in _FUYAO_SECTOR_ENDPOINTS.items()
    ):
        raise CapabilityEvidenceError("capability endpoint evidence is incomplete")

    expected_date = envelope_as_of.isoformat()
    dates = report.date_evidence
    if dates.get("requested") != expected_date or dates.get("calendar") != expected_date:
        raise CapabilityEvidenceError("capability exact-date evidence is inconsistent")
    snapshot_dates = dates.get("snapshot")
    if (
        not isinstance(snapshot_dates, Sequence)
        or isinstance(snapshot_dates, (str, bytes))
        or not snapshot_dates
        or {str(value) for value in snapshot_dates} != {expected_date}
    ):
        raise CapabilityEvidenceError("capability exact-date evidence is inconsistent")

    pagination = report.pagination_evidence
    if (
        _integer(pagination.get("catalogCount")) != 320
        or _integer(pagination.get("snapshotCount")) != 320
        or pagination.get("catalogIdentityUnique") is not True
        or pagination.get("snapshotIdentityUnique") is not True
        or _number(pagination.get("snapshotCoverage")) != 1.0
    ):
        raise CapabilityEvidenceError(
            "capability catalog or snapshot coverage is incomplete"
        )

    batch_count = _integer(pagination.get("snapshotBatchCount"))
    timestamp_count = _integer(pagination.get("snapshotTimestampCount"))
    timestamps = pagination.get("snapshotTimestamps")
    if (
        batch_count is None
        or batch_count < 1
        or timestamp_count != batch_count
        or pagination.get("snapshotTimestampDateConsistent") is not True
        or not isinstance(timestamps, Sequence)
        or isinstance(timestamps, (str, bytes))
        or not timestamps
        or any(_timestamp_date(value) != envelope_as_of for value in timestamps)
    ):
        raise CapabilityEvidenceError(
            "capability snapshot batch date evidence is incomplete"
        )

    fields = report.field_coverage
    if any(_integer(fields.get(name)) != 320 for name in _FUYAO_SECTOR_FIELDS):
        raise CapabilityEvidenceError(
            "capability supported-field coverage is incomplete"
        )
    if any(
        _integer(fields.get(name)) != 0 for name in _FUYAO_UNSUPPORTED_FIELDS
    ):
        raise CapabilityEvidenceError(
            "capability unsupported-field evidence is invalid"
        )
    if set(report.missing_evidence) != set(_FUYAO_UNSUPPORTED_FIELDS):
        raise CapabilityEvidenceError(
            "capability unsupported-field absence is incomplete"
        )

    if report.permission_evidence.get("configured") is not True:
        raise CapabilityEvidenceError("capability permission evidence is incomplete")
    budget = _integer(report.rate_limit_evidence.get("requestBudget"))
    used = _integer(report.rate_limit_evidence.get("requestsUsed"))
    if budget is None or used is None or budget < 1 or used < 1 or used > budget:
        raise CapabilityEvidenceError("capability rate-limit evidence is invalid")


def _mapping(value: Any, evidence_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise CapabilityEvidenceError(
            f"capability {evidence_name} evidence is incomplete"
        )
    return value


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        converted = int(value)
    except (TypeError, ValueError):
        return None
    return converted if converted == value else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp_date(value: Any) -> date | None:
    try:
        number = float(value)
        if abs(number) > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, _SHANGHAI).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


__all__ = [
    "CapabilityEvidenceError",
    "CapabilityEvidencePolicy",
    "CapabilityEvidencePolicyKey",
    "FUYAO_SECTORS_V2",
    "capability_evidence_policies",
    "validate_fuyao_sectors_v2",
]
