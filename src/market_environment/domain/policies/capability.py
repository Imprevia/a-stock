"""Fail-closed evidence policies for capability report promotion."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

from ..models.capability import THS_CAPABILITY_REVISIONS, ProviderCapabilityReport


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
_THS_ENDPOINTS = {
    "industry-ranking": "/api/a-share-index/prices/snapshot",
    "sector-membership": "/api/a-share-index/constituents/ths-stock-list",
    "sector-turnover-history": "/api/a-share-index/prices/historical",
    "sector-member-daily-dump": "/api/dump/market-dumps/daily-k/download-url",
    "sector-member-incremental-dump": "/api/dump/market-dumps/daily-k-10d/download-url",
    "sector-member-adjustment-dump": "/api/dump/market-dumps/adjustment-factors/download-url",
}
_THS_DUMP_REQUIRED_COLUMNS = {
    "sector-member-daily-dump": {
        "thscode",
        "date_ms",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
        "currency",
        "interval",
        "adjusted",
    },
    "sector-member-incremental-dump": {
        "thscode",
        "date_ms",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
        "currency",
        "interval",
        "adjusted",
    },
    "sector-member-adjustment-dump": {
        "thscode",
        "ticker",
        "ex_date_ms",
        "dividend_per_share",
        "per_share_bonus",
        "allotment_ratio",
        "allotment_price",
        "currency",
    },
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CapabilityEvidenceError(ValueError):
    """Raised when a report cannot prove its frozen provider contract."""


def capability_evidence_policies() -> Mapping[
    CapabilityEvidencePolicyKey, CapabilityEvidencePolicy
]:
    policies: dict[CapabilityEvidencePolicyKey, CapabilityEvidencePolicy] = {
        FUYAO_SECTORS_V2: validate_fuyao_sectors_v2
    }
    for dataset, revision in THS_CAPABILITY_REVISIONS.items():
        policies[("fuyao", dataset, revision)] = validate_fuyao_ths_operation
    return policies


def validate_fuyao_ths_operation(
    report: ProviderCapabilityReport,
    envelope_as_of: date,
) -> None:
    revision = THS_CAPABILITY_REVISIONS.get(report.dataset)
    if revision is None or (report.provider, report.revision) != ("fuyao", revision):
        raise CapabilityEvidenceError("THS capability evidence policy identity mismatch")
    if report.endpoint != _THS_ENDPOINTS[report.dataset]:
        raise CapabilityEvidenceError("THS capability endpoint evidence is incomplete")
    if report.sample_count < 1:
        raise CapabilityEvidenceError("THS capability sample evidence is incomplete")
    if (
        report.permission_evidence.get("configured") is not True
        or report.permission_evidence.get("approved") is not True
        or report.permission_evidence.get("mode") != "explicit-real-probe"
    ):
        raise CapabilityEvidenceError("THS capability permission evidence is incomplete")
    budget = _integer(report.rate_limit_evidence.get("requestBudget"))
    used = _integer(report.rate_limit_evidence.get("requestsUsed"))
    if budget is None or used is None or budget < 1 or used < 1 or used > budget:
        raise CapabilityEvidenceError("THS capability rate-limit evidence is invalid")
    if (
        report.date_evidence.get("requested") != envelope_as_of.isoformat()
        or report.date_evidence.get("exact") is not True
    ):
        raise CapabilityEvidenceError("THS capability exact-date evidence is inconsistent")

    if report.dataset == "industry-ranking":
        _validate_ths_catalog(report)
    elif report.dataset == "sector-membership":
        _validate_ths_membership(report)
    elif report.dataset == "sector-turnover-history":
        _validate_ths_history(report)
    else:
        _validate_ths_dump(report)


def _validate_ths_catalog(report: ProviderCapabilityReport) -> None:
    fields = report.field_coverage
    dates = report.date_evidence
    endpoints = _mapping(fields.get("endpoints"), "endpoint")
    if endpoints != {
        "catalog": "/api/a-share-index/catalog/ths-index-list",
        "snapshot": "/api/a-share-index/prices/snapshot",
    }:
        raise CapabilityEvidenceError("THS catalog endpoint evidence is incomplete")
    if set(fields.get("tags", ())) != {"industry", "cn_concept", "region", "tszs"}:
        raise CapabilityEvidenceError("THS catalog tag coverage is incomplete")
    tag_counts = _mapping(fields.get("tagCounts"), "tag count")
    if set(tag_counts) != {"industry", "cn_concept", "region", "tszs"} or any(
        (_integer(value) or 0) < 1 for value in tag_counts.values()
    ):
        raise CapabilityEvidenceError("THS catalog tag counts are incomplete")
    unique_codes = _integer(fields.get("uniqueCodes"))
    snapshot_rows = _integer(fields.get("snapshotRows"))
    catalog_timestamps = dates.get("catalogTimestamps")
    snapshot_timestamps = dates.get("snapshotTimestamps")
    snapshot_batch_count = _integer(
        report.pagination_evidence.get("snapshotBatchCount")
    )
    if (
        unique_codes is None
        or unique_codes < 1
        or snapshot_rows != unique_codes
        or fields.get("requiredFieldsComplete") is not True
        or fields.get("ohlcPresent") is not True
        or fields.get("volumePresent") is not True
        or fields.get("turnoverPresent") is not True
        or report.pagination_evidence.get("catalogIdentityUnique") is not True
        or report.pagination_evidence.get("snapshotIdentityUnique") is not True
        or _number(report.pagination_evidence.get("snapshotCoverage")) != 1.0
        or not isinstance(catalog_timestamps, Sequence)
        or isinstance(catalog_timestamps, (str, bytes))
        or len(catalog_timestamps) != 4
        or any(_iso_timestamp_date(value) != date.fromisoformat(str(dates["requested"])) for value in catalog_timestamps)
        or not isinstance(snapshot_timestamps, Sequence)
        or isinstance(snapshot_timestamps, (str, bytes))
        or not snapshot_timestamps
        or snapshot_batch_count != len(snapshot_timestamps)
        or _integer(report.pagination_evidence.get("snapshotTimestampCount"))
        != snapshot_batch_count
        or report.pagination_evidence.get("snapshotTimestampDateConsistent") is not True
        or any(_iso_timestamp_date(value) != date.fromisoformat(str(dates["requested"])) for value in snapshot_timestamps)
        or _iso_timestamp_date(dates.get("providerTimestamp"))
        != date.fromisoformat(str(dates["requested"]))
    ):
        raise CapabilityEvidenceError("THS catalog/snapshot coverage is incomplete")


def _validate_ths_membership(report: ProviderCapabilityReport) -> None:
    fields = report.field_coverage
    if (
        not re.fullmatch(r"\d{6}\.TI", str(fields.get("thscode", "")))
        or fields.get("memberIdentity") is not True
        or fields.get("memberName") is not True
        or fields.get("identityUnique") is not True
        or _integer(report.pagination_evidence.get("memberCount")) != report.sample_count
    ):
        raise CapabilityEvidenceError("THS membership coverage is incomplete")


def _validate_ths_history(report: ProviderCapabilityReport) -> None:
    fields = report.field_coverage
    history = report.history_window
    try:
        start = date.fromisoformat(str(history["requestedStart"]))
        end = date.fromisoformat(str(history["requestedEnd"]))
        observed_start = date.fromisoformat(str(history["observedStart"]))
        observed_end = date.fromisoformat(str(history["observedEnd"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CapabilityEvidenceError("THS history window evidence is incomplete") from exc
    if (
        not re.fullmatch(r"\d{6}\.TI", str(fields.get("thscode", "")))
        or fields.get("ohlcComplete") is not True
        or fields.get("volumeComplete") is not True
        or fields.get("turnoverComplete") is not True
        or fields.get("dateUnique") is not True
        or history.get("withinFiveYears") is not True
        or not start <= observed_start <= observed_end <= end
        or observed_end != end
    ):
        raise CapabilityEvidenceError("THS history field or window evidence is incomplete")


def _validate_ths_dump(report: ProviderCapabilityReport) -> None:
    fields = report.field_coverage
    if set(fields.get("columns", ())) < _THS_DUMP_REQUIRED_COLUMNS[report.dataset]:
        raise CapabilityEvidenceError("THS dump schema evidence is incomplete")
    if (
        fields.get("requiredColumnsPresent") is not True
        or fields.get("checksumMatchesMetadata") is not True
        or fields.get("temporaryFile") is not True
        or fields.get("temporaryFileRemovedAfterProbe") is not True
        or fields.get("presignedUrlPersisted") is not False
        or fields.get("rawResponsePersisted") is not False
        or fields.get("primaryKeyUnique") is not True
        or not _SHA256.fullmatch(str(fields.get("sha256", "")))
        or (_integer(fields.get("sizeBytes")) or 0) < 1
        or report.pagination_evidence.get("downloadComplete") is not True
        or report.pagination_evidence.get("schemaInspected") is not True
    ):
        raise CapabilityEvidenceError("THS dump checksum or redaction evidence is incomplete")
    expected_dump_ids = {
        "sector-member-daily-dump": "a_share_daily_k_1d_none_10y",
        "sector-member-incremental-dump": "a_share_daily_k_1d_none_10d",
        "sector-member-adjustment-dump": "a_share_adjustment_factors_event_none_all",
    }
    if fields.get("dumpId") != expected_dump_ids[report.dataset]:
        raise CapabilityEvidenceError("THS dump identity evidence is incomplete")
    if report.dataset != "sector-member-adjustment-dump" and (
        fields.get("interval") != "1d"
        or fields.get("adjusted") != "none"
        or fields.get("intervalDaily") is not True
        or fields.get("adjustedNone") is not True
        or fields.get("currencyCny") is not True
    ):
        raise CapabilityEvidenceError("THS daily dump interval, adjustment or currency evidence is incomplete")
    if report.dataset == "sector-member-adjustment-dump" and fields.get("currencyCny") is not True:
        raise CapabilityEvidenceError("THS adjustment dump currency evidence is incomplete")
    if report.dataset == "sector-member-adjustment-dump" and (
        fields.get("adjustmentFactorDerived") is not True
        or fields.get("previousCloseEvidence") is not True
    ):
        raise CapabilityEvidenceError(
            "THS adjustment-factor formula and previous-close evidence are incomplete"
        )


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


def _iso_timestamp_date(value: Any) -> date | None:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(_SHANGHAI).date()
    except (TypeError, ValueError):
        return None


__all__ = [
    "CapabilityEvidenceError",
    "CapabilityEvidencePolicy",
    "CapabilityEvidencePolicyKey",
    "FUYAO_SECTORS_V2",
    "capability_evidence_policies",
    "validate_fuyao_sectors_v2",
]
