"""Explicit, redacted capability probe for Fuyao THS operations."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import sqlite3
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from src.trading_system.data.provider_http import build_requests_compatibility_session

from ....domain.models.capability import (
    THS_CAPABILITY_REVISIONS,
    ProviderCapabilityReport,
)
from ....domain.models.ths_sector import normalize_thscode
from .market import FuyaoMarketClient
from .ths_sector import FuyaoThsSectorAdapter


DUMP_METADATA_ENDPOINTS: Mapping[str, str] = {
    "sector-member-daily-dump": "/api/dump/market-dumps/daily-k/download-url",
    "sector-member-incremental-dump": "/api/dump/market-dumps/daily-k-10d/download-url",
    "sector-member-adjustment-dump": "/api/dump/market-dumps/adjustment-factors/download-url",
}

_DUMP_KINDS: Mapping[str, str] = {
    "sector-member-daily-dump": "daily",
    "sector-member-incremental-dump": "incremental",
    "sector-member-adjustment-dump": "adjustment",
}
_URL_KEYS = ("download_url", "downloadUrl", "presigned_url", "presignedUrl", "url")
_CHECKSUM_KEYS = ("sha256", "checksum", "file_checksum", "fileChecksum")
_DUMP_ID_KEYS = ("dump_id", "dumpId", "file_name", "fileName", "filename")
_INTERVAL_KEYS = ("interval", "frequency")
_ADJUSTED_KEYS = ("adjusted", "adjustment", "adjustment_type", "adjustmentType")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_EXPECTED_DUMP_IDS = {
    "daily": "a_share_daily_k_1d_none_10y",
    "incremental": "a_share_daily_k_1d_none_10d",
    "adjustment": "a_share_adjustment_factors_event_none_all",
}
_SECURITY_ID = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
_OFFICIAL_DUMP_SCHEMAS: Mapping[str, frozenset[str]] = {
    "daily": frozenset(
        {
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
        }
    ),
    "incremental": frozenset(
        {
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
        }
    ),
    "adjustment": frozenset(
        {
            "thscode",
            "ticker",
            "ex_date_ms",
            "dividend_per_share",
            "per_share_bonus",
            "allotment_ratio",
            "allotment_price",
            "currency",
        }
    ),
}


class FuyaoThsProbeError(RuntimeError):
    """Probe failure whose message cannot contain provider payloads or URLs."""


@dataclass(frozen=True, slots=True)
class DumpDownloadEvidence:
    checksum: str
    size_bytes: int


class FuyaoThsDumpDownloader:
    """Stream a short-lived signed download to an operator-scoped temp file."""

    def __init__(self, *, session: Any | None = None, timeout: float = 120.0) -> None:
        self._session = session or build_requests_compatibility_session()
        self._timeout = max(1.0, float(timeout))

    def download(
        self,
        signed_url: str,
        destination: Path,
        *,
        max_bytes: int,
    ) -> DumpDownloadEvidence:
        parsed = urlsplit(signed_url)
        if not _is_safe_download_target(parsed):
            raise FuyaoThsProbeError("Fuyao dump metadata returned an invalid download target")
        try:
            response = self._session.get(
                signed_url,
                stream=True,
                timeout=self._timeout,
                allow_redirects=False,
            )
        except Exception as exc:  # noqa: BLE001 - URL must never escape through an error
            raise FuyaoThsProbeError("Fuyao dump download failed") from exc
        try:
            status = int(getattr(response, "status_code", 0) or 0)
            if status < 200 or status >= 300:
                raise FuyaoThsProbeError(
                    f"Fuyao dump download returned HTTP {status or 'unknown'}"
                )
            headers = getattr(response, "headers", {}) or {}
            raw_length = next(
                (
                    value
                    for key, value in headers.items()
                    if str(key).strip().lower() == "content-length"
                ),
                None,
            )
            if raw_length is not None:
                try:
                    declared_length = int(raw_length)
                except (TypeError, ValueError) as exc:
                    raise FuyaoThsProbeError(
                        "Fuyao dump download has an invalid content length"
                    ) from exc
                if declared_length > max_bytes:
                    raise FuyaoThsProbeError(
                        "Fuyao dump download exceeds the configured size bound"
                    )
            digest = hashlib.sha256()
            observed = 0
            with destination.open("xb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    value = bytes(chunk)
                    observed += len(value)
                    if observed > max_bytes:
                        raise FuyaoThsProbeError(
                            "Fuyao dump download exceeds the configured size bound"
                        )
                    digest.update(value)
                    stream.write(value)
            if observed < 1:
                raise FuyaoThsProbeError("Fuyao dump download is empty")
            return DumpDownloadEvidence(digest.hexdigest(), observed)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()


def run_fuyao_ths_capability_probe(
    *,
    as_of: date,
    thscode: str,
    history_start: date,
    max_dump_bytes: int,
    client: FuyaoMarketClient | Any | None = None,
    downloader: FuyaoThsDumpDownloader | Any | None = None,
    revisions: Mapping[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Probe six independent THS capabilities without writing formal facts."""

    if history_start > as_of:
        raise ValueError("THS history probe range must be ordered")
    if (as_of - history_start).days > 366 * 5 + 2:
        raise ValueError("THS history probe range cannot exceed five years")
    if max_dump_bytes < 1:
        raise ValueError("THS dump size bound must be positive")
    selected_revisions = dict(THS_CAPABILITY_REVISIONS)
    selected_revisions.update(revisions or {})
    if set(selected_revisions) != set(THS_CAPABILITY_REVISIONS):
        raise ValueError("THS capability probe requires exactly six revisions")

    active_client = client or FuyaoMarketClient()
    active_downloader = downloader or FuyaoThsDumpDownloader()
    clock = now or (lambda: datetime.now(timezone.utc))
    adapter = FuyaoThsSectorAdapter(
        active_client,
        catalog_revision=selected_revisions["industry-ranking"],
        membership_revision=selected_revisions["sector-membership"],
        history_revision=selected_revisions["sector-turnover-history"],
        now=clock,
    )
    reports: list[ProviderCapabilityReport] = []
    reports.append(
        _capture_report(
            "industry-ranking",
            selected_revisions["industry-ranking"],
            as_of,
            active_client,
            clock,
            lambda: _probe_catalog(adapter, active_client, as_of, clock),
        )
    )
    reports.append(
        _capture_report(
            "sector-membership",
            selected_revisions["sector-membership"],
            as_of,
            active_client,
            clock,
            lambda: _probe_membership(adapter, active_client, thscode, as_of, clock),
        )
    )
    reports.append(
        _capture_report(
            "sector-turnover-history",
            selected_revisions["sector-turnover-history"],
            as_of,
            active_client,
            clock,
            lambda: _probe_history(
                adapter,
                active_client,
                thscode,
                history_start,
                as_of,
                clock,
            ),
        )
    )
    with tempfile.TemporaryDirectory(prefix="fuyao-ths-probe-") as temp_dir:
        for dataset, endpoint in DUMP_METADATA_ENDPOINTS.items():
            reports.append(
                _capture_report(
                    dataset,
                    selected_revisions[dataset],
                    as_of,
                    active_client,
                    clock,
                    lambda dataset=dataset, endpoint=endpoint: _probe_dump(
                        client=active_client,
                        downloader=active_downloader,
                        dataset=dataset,
                        endpoint=endpoint,
                        as_of=as_of,
                        destination=Path(temp_dir) / f"{_DUMP_KINDS[dataset]}.parquet",
                        max_dump_bytes=max_dump_bytes,
                        clock=clock,
                        revision=selected_revisions[dataset],
                    ),
                )
            )
    return {
        "provider": "fuyao",
        "asOf": as_of.isoformat(),
        "promotionStatus": "not-promoted",
        "reports": [report.redacted_dict() for report in reports],
    }


def _missing_change_pct_tags(
    bundle: Any,
    *,
    allowed_tags: frozenset[str] = frozenset({"industry", "cn_concept", "region", "tszs"}),
) -> tuple[str, ...]:
    """Return the subset of the four THS tags whose every snapshot row lacks change_pct.

    The capability promotion policy reads this field to refuse any tag whose coverage
    collapsed to zero, so a single provider gap cannot leave a per-tag ranking without
    at least one leader carrying a non-null change_pct.
    """
    relations = getattr(bundle, "relations", ())
    snapshots = tuple(getattr(bundle, "snapshots", ()))
    if not relations or not snapshots:
        return ()
    coverage: dict[str, list[bool]] = {tag: [] for tag in allowed_tags}
    snapshot_by_code = {
        normalize_thscode(getattr(snapshot, "thscode", "")): snapshot
        for snapshot in snapshots
    }
    for relation in relations:
        snapshot = snapshot_by_code.get(
            normalize_thscode(getattr(relation, "thscode", ""))
        )
        if snapshot is None:
            continue
        coverage.setdefault(relation.tag, []).append(
            getattr(snapshot, "change_pct", None) is not None
        )
    return tuple(
        sorted(tag for tag, values in coverage.items() if values and not any(values))
    )


def _capture_report(
    dataset: str,
    revision: str,
    as_of: date,
    client: Any,
    clock: Callable[[], datetime],
    operation: Callable[[], ProviderCapabilityReport],
) -> ProviderCapabilityReport:
    before = int(getattr(client, "request_count", 0) or 0)
    try:
        return operation()
    except Exception as exc:  # noqa: BLE001 - every operation must leave reviewable evidence
        used = max(0, int(getattr(client, "request_count", before) or 0) - before)
        return _report(
            dataset=dataset,
            revision=revision,
            status="ineligible",
            endpoint=_endpoint_for(dataset),
            as_of=as_of,
            client=client,
            clock=clock,
            sample_count=0,
            field_coverage={"complete": False},
            date_evidence={"requested": as_of.isoformat(), "exact": False},
            pagination_evidence={"proven": False},
            requests_used=used,
            warnings=(_safe_failure(dataset, exc),),
            missing_evidence=("operation contract was not proven",),
        )


def _probe_catalog(
    adapter: FuyaoThsSectorAdapter,
    client: Any,
    as_of: date,
    clock: Callable[[], datetime],
) -> ProviderCapabilityReport:
    before = int(getattr(client, "request_count", 0) or 0)
    bundle = adapter.fetch_catalog_snapshot(as_of)
    used = int(getattr(client, "request_count", before) or 0) - before
    unique_codes = {row.thscode for row in bundle.relations}
    return _report(
        dataset="industry-ranking",
        revision=adapter.catalog_revision,
        status="eligible",
        endpoint=adapter.SNAPSHOT_ENDPOINT,
        as_of=as_of,
        client=client,
        clock=clock,
        sample_count=len(bundle.snapshots),
        field_coverage={
            "endpoints": {
                "catalog": adapter.CATALOG_ENDPOINT,
                "snapshot": adapter.SNAPSHOT_ENDPOINT,
            },
            "tags": sorted(bundle.revision.tag_counts),
            "tagCounts": dict(bundle.revision.tag_counts),
            "catalogRows": len(bundle.relations),
            "uniqueCodes": len(unique_codes),
            "snapshotRows": len(bundle.snapshots),
            "requiredFieldsComplete": all(
                row.close is not None for row in bundle.snapshots
            ),
            "changePctCoverage": (
                sum(1 for row in bundle.snapshots if row.change_pct is not None)
                / max(1, len(bundle.snapshots))
            ),
            "changePctCoverageThreshold": 0.99,
            "changePctMissingCodes": sorted(
                row.thscode for row in bundle.snapshots if row.change_pct is None
            ),
            "changePctMissingTags": _missing_change_pct_tags(bundle),
            "ohlcPresent": all(
                None not in {row.open, row.high, row.low, row.close}
                for row in bundle.snapshots
            ),
            "volumePresent": all(row.volume is not None for row in bundle.snapshots),
            "turnoverPresent": all(row.turnover is not None for row in bundle.snapshots),
        },
        date_evidence={
            "requested": as_of.isoformat(),
            "exact": True,
            "providerTimestamp": bundle.revision.provider_timestamp.isoformat(),
            "catalogTimestamps": [
                value.isoformat() for value in bundle.catalog_timestamps
            ],
            "snapshotTimestamps": [
                value.isoformat() for value in bundle.snapshot_timestamps
            ],
        },
        pagination_evidence={
            "catalogIdentityUnique": True,
            "snapshotIdentityUnique": True,
            "snapshotCoverage": len(bundle.snapshots) / len(unique_codes),
            "snapshotBatchCount": max(
                1,
                (len(unique_codes) + adapter.SNAPSHOT_BATCH_SIZE - 1)
                // adapter.SNAPSHOT_BATCH_SIZE,
            ),
            "snapshotTimestampCount": len(bundle.snapshot_timestamps),
            "snapshotTimestampDateConsistent": bool(bundle.snapshot_timestamps)
            and all(
                value.astimezone(_SHANGHAI).date() == as_of
                for value in bundle.snapshot_timestamps
            ),
        },
        requests_used=used,
        warnings=bundle.warnings,
    )


def _probe_membership(
    adapter: FuyaoThsSectorAdapter,
    client: Any,
    thscode: str,
    as_of: date,
    clock: Callable[[], datetime],
) -> ProviderCapabilityReport:
    before = int(getattr(client, "request_count", 0) or 0)
    rows = adapter.fetch_memberships(thscode, as_of=as_of)
    used = int(getattr(client, "request_count", before) or 0) - before
    return _report(
        dataset="sector-membership",
        revision=adapter.membership_revision,
        status="eligible",
        endpoint=adapter.MEMBERSHIP_ENDPOINT,
        as_of=as_of,
        client=client,
        clock=clock,
        sample_count=len(rows),
        field_coverage={
            "thscode": rows[0].thscode,
            "memberIdentity": all(bool(row.member_security_id) for row in rows),
            "memberName": all(bool(row.member_name) for row in rows),
            "identityUnique": len({row.member_security_id for row in rows}) == len(rows),
        },
        date_evidence={
            "requested": as_of.isoformat(),
            "exact": {row.as_of.isoformat() for row in rows} == {as_of.isoformat()},
            "providerTimestamps": sorted(
                {row.provider_timestamp.isoformat() for row in rows}
            ),
        },
        pagination_evidence={"proven": True, "memberCount": len(rows)},
        requests_used=used,
    )


def _probe_history(
    adapter: FuyaoThsSectorAdapter,
    client: Any,
    thscode: str,
    start_date: date,
    end_date: date,
    clock: Callable[[], datetime],
) -> ProviderCapabilityReport:
    before = int(getattr(client, "request_count", 0) or 0)
    rows = adapter.fetch_history(thscode, start_date=start_date, end_date=end_date)
    if not rows:
        raise FuyaoThsProbeError("Fuyao THS history probe returned no rows")
    observed_start = min(row.trading_date for row in rows)
    observed_end = max(row.trading_date for row in rows)
    exact = (
        observed_end == end_date
        and all(start_date <= row.trading_date <= end_date for row in rows)
    )
    used = int(getattr(client, "request_count", before) or 0) - before
    return _report(
        dataset="sector-turnover-history",
        revision=adapter.history_revision,
        status=(
            "eligible"
            if exact and all(row.quality == "ok" for row in rows)
            else "ineligible"
        ),
        endpoint=adapter.HISTORY_ENDPOINT,
        as_of=end_date,
        client=client,
        clock=clock,
        sample_count=len(rows),
        field_coverage={
            "thscode": rows[0].thscode,
            "ohlcComplete": all(
                None not in {row.open, row.high, row.low, row.close} for row in rows
            ),
            "volumeComplete": all(row.volume is not None for row in rows),
            "turnoverComplete": all(row.turnover is not None for row in rows),
            "dateUnique": len({row.trading_date for row in rows}) == len(rows),
        },
        date_evidence={
            "requested": end_date.isoformat(),
            "exact": exact,
        },
        history_window={
            "requestedStart": start_date.isoformat(),
            "requestedEnd": end_date.isoformat(),
            "observedStart": observed_start.isoformat(),
            "observedEnd": observed_end.isoformat(),
            "withinFiveYears": (end_date - start_date).days <= 366 * 5 + 2,
        },
        pagination_evidence={"proven": True, "rowCount": len(rows)},
        requests_used=used,
        warnings=tuple(warning for row in rows for warning in row.warnings),
        missing_evidence=tuple(
            item
            for item, missing in (
                (
                    "history volume/turnover coverage is incomplete",
                    not all(row.quality == "ok" for row in rows),
                ),
                (
                    "history latest row does not cover requested as_of",
                    not exact,
                ),
            )
            if missing
        ),
    )


def _probe_dump(
    *,
    client: Any,
    downloader: Any,
    dataset: str,
    endpoint: str,
    as_of: date,
    destination: Path,
    max_dump_bytes: int,
    clock: Callable[[], datetime],
    revision: str,
) -> ProviderCapabilityReport:
    before = int(getattr(client, "request_count", 0) or 0)
    metadata = client.request(endpoint, requested_date=as_of).data
    signed_url = _metadata_value(metadata, _URL_KEYS)
    if not isinstance(signed_url, str) or not signed_url.strip():
        raise FuyaoThsProbeError("Fuyao dump metadata lacks a download target")
    expected_checksum = _normalized_checksum(_metadata_value(metadata, _CHECKSUM_KEYS))
    if expected_checksum is None:
        raise FuyaoThsProbeError("Fuyao dump metadata lacks a SHA-256 checksum")
    dump_id = _metadata_value(metadata, _DUMP_ID_KEYS)
    kind = _DUMP_KINDS[dataset]
    if str(dump_id or "").strip() != _EXPECTED_DUMP_IDS[kind]:
        raise FuyaoThsProbeError("Fuyao dump metadata has an unexpected dump_id")
    interval = str(_metadata_value(metadata, _INTERVAL_KEYS) or "").strip().lower()
    adjusted = str(_metadata_value(metadata, _ADJUSTED_KEYS) or "").strip().lower()
    if kind != "adjustment" and (interval != "1d" or adjusted != "none"):
        raise FuyaoThsProbeError(
            "Fuyao dump metadata does not prove interval=1d and adjusted=none"
        )
    evidence = downloader.download(
        signed_url,
        destination,
        max_bytes=max_dump_bytes,
    )
    if evidence.checksum != expected_checksum:
        raise FuyaoThsProbeError("Fuyao dump checksum does not match metadata")
    schema = _inspect_parquet(destination, kind)
    destination.unlink(missing_ok=True)
    used = int(getattr(client, "request_count", before) or 0) - before
    fresh = schema["endDate"] == as_of.isoformat()
    adjustment_ready = kind != "adjustment"
    warnings = (
        ()
        if adjustment_ready
        else (
            "Fuyao adjustment dump exposes corporate-action terms rather than an adjustment factor; formula and previous-close evidence are not implemented",
        )
    )
    return _report(
        dataset=dataset,
        revision=revision,
        status="eligible" if adjustment_ready and fresh else "ineligible",
        endpoint=endpoint,
        as_of=as_of,
        client=client,
        clock=clock,
        sample_count=schema["rowCount"],
        field_coverage={
            "dumpId": str(dump_id or dataset),
            "interval": interval if kind != "adjustment" else "not-applicable",
            "adjusted": adjusted if kind != "adjustment" else "not-applicable",
            "columns": schema["columns"],
            "requiredColumns": schema["requiredColumns"],
            "requiredColumnsPresent": True,
            "sha256": evidence.checksum,
            "sizeBytes": evidence.size_bytes,
            "checksumMatchesMetadata": True,
            "temporaryFile": True,
            "temporaryFileRemovedAfterProbe": True,
            "presignedUrlPersisted": False,
            "rawResponsePersisted": False,
            "primaryKeyUnique": schema["primaryKeyUnique"],
            "currencyCny": schema["currencyCny"],
            "intervalDaily": schema["intervalDaily"],
            "adjustedNone": schema["adjustedNone"],
            "adjustmentFactorDerived": False if kind == "adjustment" else None,
            "previousCloseEvidence": False if kind == "adjustment" else None,
        },
        date_evidence={
            "requested": as_of.isoformat(),
            "exact": fresh if kind != "adjustment" else schema["endDate"] <= as_of.isoformat(),
            "observedStart": schema["startDate"],
            "observedEnd": schema["endDate"],
        },
        history_window={
            "observedStart": schema["startDate"],
            "observedEnd": schema["endDate"],
            "rowCount": schema["rowCount"],
        },
        pagination_evidence={"downloadComplete": True, "schemaInspected": True},
        requests_used=used,
        warnings=warnings,
        missing_evidence=tuple(
            [
                *(
                    ()
                    if adjustment_ready
                    else (
                        "adjustment-factor formula is not frozen",
                        "previous-close evidence is unavailable",
                    )
                ),
                *(
                    ()
                    if fresh or kind == "adjustment"
                    else ("dump latest row does not cover requested as_of",)
                ),
            ]
        ),
    )


def _inspect_parquet(path: Path, kind: str) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(path)
        columns = [str(name) for name in parquet.schema_arrow.names]
        required = sorted(_OFFICIAL_DUMP_SCHEMAS[kind])
        missing = sorted(set(required) - set(columns))
        if missing:
            raise FuyaoThsProbeError(
                "Fuyao dump schema is missing required columns: " + ", ".join(missing)
            )
        date_column = "ex_date_ms" if kind == "adjustment" else "date_ms"
        key_database = path.with_suffix(".keys.sqlite3")
        connection = sqlite3.connect(key_database)
        connection.execute(
            "CREATE TABLE observed_keys (thscode TEXT NOT NULL, date_ms INTEGER NOT NULL, PRIMARY KEY(thscode,date_ms))"
        )
        observed_start: date | None = None
        observed_end: date | None = None
        currencies: set[str] = set()
        intervals: set[str] = set()
        adjusted_values: set[str] = set()
        observed_rows = 0
        columns_to_read = ["thscode", date_column]
        columns_to_read.append("currency")
        if kind != "adjustment":
            columns_to_read.extend(("interval", "adjusted"))
        try:
            for batch in parquet.iter_batches(columns=columns_to_read, batch_size=65536):
                code_values = batch.column(0).to_pylist()
                date_values = batch.column(1).to_pylist()
                currency_values = batch.column(2).to_pylist()
                interval_values = (
                    batch.column(3).to_pylist()
                    if kind != "adjustment"
                    else [None] * len(code_values)
                )
                adjusted_rows = (
                    batch.column(4).to_pylist()
                    if kind != "adjustment"
                    else [None] * len(code_values)
                )
                keys: list[tuple[str, int]] = []
                for raw_code, raw_date, raw_currency, raw_interval, raw_adjusted in zip(
                    code_values,
                    date_values,
                    currency_values,
                    interval_values,
                    adjusted_rows,
                    strict=True,
                ):
                    code = str(raw_code or "").strip().upper()
                    if not _SECURITY_ID.fullmatch(code):
                        raise FuyaoThsProbeError(
                            "Fuyao dump contains an invalid thscode"
                        )
                    date_number = _millisecond_value(raw_date)
                    observed = _millisecond_date(date_number)
                    observed_start = observed if observed_start is None else min(observed_start, observed)
                    observed_end = observed if observed_end is None else max(observed_end, observed)
                    keys.append((code, date_number))
                    observed_rows += 1
                    currencies.add(str(raw_currency or "").strip().upper())
                    if kind != "adjustment":
                        intervals.add(str(raw_interval or "").strip().lower())
                        adjusted_values.add(str(raw_adjusted or "").strip().lower())
                try:
                    connection.executemany(
                        "INSERT INTO observed_keys(thscode,date_ms) VALUES (?,?)",
                        keys,
                    )
                    connection.commit()
                except sqlite3.IntegrityError as exc:
                    raise FuyaoThsProbeError(
                        "Fuyao dump contains duplicate business keys"
                    ) from exc
        finally:
            connection.close()
            key_database.unlink(missing_ok=True)
        if observed_start is None or observed_end is None:
            raise FuyaoThsProbeError("Fuyao dump contains no dated rows")
        if observed_rows != int(parquet.metadata.num_rows):
            raise FuyaoThsProbeError("Fuyao dump row count evidence is inconsistent")
        if currencies != {"CNY"}:
            raise FuyaoThsProbeError("Fuyao dump currency is not uniformly CNY")
        if kind != "adjustment" and intervals != {"1d"}:
            raise FuyaoThsProbeError("Fuyao daily dump interval is not uniformly 1d")
        if kind != "adjustment" and adjusted_values != {"none"}:
            raise FuyaoThsProbeError("Fuyao daily dump adjusted mode is not uniformly none")
        return {
            "columns": sorted(columns),
            "requiredColumns": required,
            "rowCount": int(parquet.metadata.num_rows),
            "startDate": observed_start.isoformat(),
            "endDate": observed_end.isoformat(),
            "primaryKeyUnique": True,
            "currencyCny": currencies == {"CNY"},
            "intervalDaily": intervals == {"1d"} if kind != "adjustment" else None,
            "adjustedNone": adjusted_values == {"none"} if kind != "adjustment" else None,
        }
    except FuyaoThsProbeError:
        raise
    except Exception as exc:  # noqa: BLE001 - do not expose file metadata
        raise FuyaoThsProbeError("Fuyao dump Parquet schema cannot be inspected") from exc


def _report(
    *,
    dataset: str,
    revision: str,
    status: str,
    endpoint: str,
    as_of: date,
    client: Any,
    clock: Callable[[], datetime],
    sample_count: int,
    field_coverage: Mapping[str, Any],
    date_evidence: Mapping[str, Any],
    pagination_evidence: Mapping[str, Any],
    requests_used: int,
    history_window: Mapping[str, Any] | None = None,
    warnings: tuple[str, ...] = (),
    missing_evidence: tuple[str, ...] = (),
) -> ProviderCapabilityReport:
    checked_at = clock()
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    return ProviderCapabilityReport(
        provider="fuyao",
        dataset=dataset,
        revision=revision,
        status=status,
        endpoint=endpoint,
        field_coverage=dict(field_coverage),
        date_evidence=dict(date_evidence),
        history_window=dict(history_window or {}),
        pagination_evidence=dict(pagination_evidence),
        permission_evidence={
            "configured": bool(getattr(client, "configured", True)),
            "approved": True,
            "mode": "explicit-real-probe",
        },
        rate_limit_evidence={
            "requestBudget": int(getattr(client, "request_budget", 0) or 0),
            "requestsUsed": max(0, int(requests_used)),
        },
        sample_count=max(0, int(sample_count)),
        warnings=tuple(dict.fromkeys(str(item) for item in warnings if str(item))),
        missing_evidence=tuple(
            dict.fromkeys(str(item) for item in missing_evidence if str(item))
        ),
        checked_at=checked_at,
    ).normalized()


def _metadata_value(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, Mapping):
        for key in keys:
            if value.get(key) not in (None, ""):
                return value[key]
        for nested in value.values():
            candidate = _metadata_value(nested, keys)
            if candidate not in (None, ""):
                return candidate
    elif isinstance(value, (list, tuple)):
        for nested in value:
            candidate = _metadata_value(nested, keys)
            if candidate not in (None, ""):
                return candidate
    return None


def _is_safe_download_target(parsed: Any) -> bool:
    """Reject non-HTTPS and obvious local/private targets before any request."""

    try:
        scheme = str(parsed.scheme or "").lower()
        hostname = str(parsed.hostname or "").strip().lower().rstrip(".")
        username = parsed.username
    except (AttributeError, ValueError):
        return False
    if scheme != "https" or not hostname or username:
        return False
    if hostname in {"localhost", "localhost.localdomain", "metadata.google.internal"}:
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    )


def _normalized_checksum(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.split(":", 1)[1]
    return text if len(text) == 64 and all(char in "0123456789abcdef" for char in text) else None


def _millisecond_date(value: Any) -> date:
    number = _millisecond_value(value)
    try:
        return datetime.fromtimestamp(number / 1000, _SHANGHAI).date()
    except (OSError, OverflowError, ValueError) as exc:
        raise FuyaoThsProbeError("Fuyao dump contains an invalid millisecond date") from exc


def _millisecond_value(value: Any) -> int:
    try:
        number = float(value)
        if not number.is_integer() or abs(number) < 10_000_000_000:
            raise ValueError
        return int(number)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FuyaoThsProbeError("Fuyao dump contains an invalid millisecond date") from exc


def _endpoint_for(dataset: str) -> str:
    return {
        "industry-ranking": FuyaoThsSectorAdapter.SNAPSHOT_ENDPOINT,
        "sector-membership": FuyaoThsSectorAdapter.MEMBERSHIP_ENDPOINT,
        "sector-turnover-history": FuyaoThsSectorAdapter.HISTORY_ENDPOINT,
        **DUMP_METADATA_ENDPOINTS,
    }[dataset]


def _safe_failure(dataset: str, exc: Exception) -> str:
    if isinstance(exc, FuyaoThsProbeError):
        return str(exc)
    return f"{dataset} capability probe failed ({type(exc).__name__})"


__all__ = [
    "DUMP_METADATA_ENDPOINTS",
    "DumpDownloadEvidence",
    "FuyaoThsDumpDownloader",
    "FuyaoThsProbeError",
    "run_fuyao_ths_capability_probe",
]
