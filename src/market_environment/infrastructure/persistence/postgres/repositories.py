"""PostgreSQL repositories for exact-date snapshots and reference evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy import Connection, text

from ....application.mappers import candidate_to_snapshot_fields, snapshot_to_candidate
from ....domain.models import CollectionCandidate, DatasetDate
from ...providers.capability import ProviderCapabilityReport
from ....snapshot_store import (
    SNAPSHOT_SCHEMA_VERSION,
    TRADING_SESSION_SCHEMA_VERSION,
    SnapshotIntegrityError,
    SnapshotRecord,
    TradingSessionRecord,
    payload_checksum,
)


def _json_load(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _as_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _as_datetime(value: datetime | str) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _allows_legacy_core_effective_date(
    identity: DatasetDate,
    payload: Mapping[str, Any],
) -> bool:
    """Accept legacy core effective dates without relabeling snapshot identity."""

    if identity.dataset != "core":
        return False
    try:
        effective_as_of = date.fromisoformat(str(payload.get("asOf") or ""))
    except ValueError:
        return False
    if effective_as_of >= identity.as_of:
        return False
    quality = payload.get("quality")
    if isinstance(quality, Mapping) and quality.get("asOf") not in (
        None,
        identity.as_of.isoformat(),
    ):
        return False
    indices = payload.get("indices")
    if not isinstance(indices, Sequence) or isinstance(indices, (str, bytes)) or not indices:
        return False
    latest_dates: list[date] = []
    for value in indices:
        if not isinstance(value, Mapping):
            return False
        history = value.get("history")
        if not isinstance(history, Sequence) or isinstance(history, (str, bytes)) or not history:
            return False
        latest = history[-1]
        if not isinstance(latest, Mapping):
            return False
        try:
            latest_date = date.fromisoformat(str(latest.get("date") or ""))
        except ValueError:
            return False
        if latest_date > identity.as_of:
            return False
        latest_dates.append(latest_date)
    return min(latest_dates) == effective_as_of


def _snapshot_dates_are_compatible(
    identity: DatasetDate,
    payload: Mapping[str, Any],
    actual_as_of: date | None,
) -> bool:
    if actual_as_of not in (None, identity.as_of):
        return False
    expected_as_of = identity.as_of.isoformat()
    quality = payload.get("quality")
    quality_as_of = quality.get("asOf") if isinstance(quality, Mapping) else None
    if payload.get("asOf") in (None, expected_as_of) and quality_as_of in (
        None,
        expected_as_of,
    ):
        return True
    return _allows_legacy_core_effective_date(identity, payload)


class PostgresSnapshotRepository:
    def __init__(
        self,
        connection: Connection,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.connection = connection
        self.now = now or (lambda: datetime.now(timezone.utc))

    def get(self, identity: DatasetDate) -> CollectionCandidate | None:
        row = self.connection.execute(
            text(
                "SELECT * FROM snapshot_entries "
                "WHERE dataset = :dataset AND as_of = :as_of"
            ),
            {"dataset": identity.dataset, "as_of": identity.as_of},
        ).mappings().first()
        if row is None:
            return None
        payload = dict(_json_load(row["payload_json"], {}))
        if payload_checksum(payload) != row["checksum"]:
            raise SnapshotIntegrityError(
                f"snapshot checksum mismatch: {identity.dataset}/{identity.as_of.isoformat()}"
            )
        record = SnapshotRecord(
            dataset=str(row["dataset"]),
            as_of=_as_date(row["as_of"]),  # type: ignore[arg-type]
            payload=payload,
            source=str(row["source"]),
            status=str(row["status"]),
            observations=int(row["observations"]),
            warnings=tuple(str(value) for value in _json_load(row["warnings_json"], [])),
            fetched_at=_as_datetime(row["fetched_at"]),
            settled=bool(row["settled"]),
            schema_version=int(row["schema_version"]),
            checksum=str(row["checksum"]),
            refresh_warning=row["refresh_warning"],
        )
        if record.schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise SnapshotIntegrityError(
                f"unsupported snapshot schema version: {record.schema_version}"
            )
        candidate = snapshot_to_candidate(record)
        if candidate.identity != identity or not _snapshot_dates_are_compatible(
            identity,
            payload,
            candidate.actual_as_of,
        ):
            raise SnapshotIntegrityError(
                f"snapshot exact-date mismatch: {identity.dataset}/{identity.as_of.isoformat()}"
            )
        return candidate

    def put(self, candidate: CollectionCandidate) -> CollectionCandidate:
        fields = candidate_to_snapshot_fields(candidate, fetched_at=self.now())
        payload = dict(fields["payload"])
        expected_as_of = candidate.identity.as_of.isoformat()
        if not _snapshot_dates_are_compatible(
            candidate.identity,
            payload,
            candidate.actual_as_of,
        ):
            raise SnapshotIntegrityError(
                "snapshot exact-date mismatch: "
                f"{candidate.identity.dataset}/{expected_as_of}"
            )
        checksum = payload_checksum(payload)
        self.connection.execute(
            text(
                """
                INSERT INTO snapshot_entries(
                    dataset, as_of, payload_json, source, status, observations,
                    warnings_json, fetched_at, settled, schema_version, checksum,
                    refresh_warning
                ) VALUES (
                    :dataset, :as_of, :payload_json, :source, :status, :observations,
                    :warnings_json, :fetched_at, :settled, :schema_version, :checksum,
                    :refresh_warning
                )
                ON CONFLICT(dataset, as_of) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    source = excluded.source,
                    status = excluded.status,
                    observations = excluded.observations,
                    warnings_json = excluded.warnings_json,
                    fetched_at = excluded.fetched_at,
                    settled = excluded.settled,
                    schema_version = excluded.schema_version,
                    checksum = excluded.checksum,
                    refresh_warning = excluded.refresh_warning
                """
            ),
            {
                **fields,
                "payload_json": _canonical_json(payload),
                "warnings_json": _canonical_json(list(fields["warnings"])),
                "settled": int(bool(fields["settled"])),
                "checksum": checksum,
            },
        )
        stored = self.get(candidate.identity)
        assert stored is not None
        return stored

    def list_dates(self, dataset: str) -> Sequence[date]:
        return tuple(
            _as_date(value)
            for value in self.connection.execute(
                text(
                    "SELECT as_of FROM snapshot_entries "
                    "WHERE dataset = :dataset ORDER BY as_of DESC"
                ),
                {"dataset": dataset},
            ).scalars()
            if value is not None
        )  # type: ignore[return-value]


class PostgresTradingSessionRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def get_session(self, as_of: date) -> TradingSessionRecord | None:
        row = self.connection.execute(
            text("SELECT * FROM trading_sessions WHERE as_of = :as_of"),
            {"as_of": as_of},
        ).mappings().first()
        return self._from_row(row, expected_as_of=as_of) if row is not None else None

    def list_sessions(self, *, after: date | None = None) -> Sequence[TradingSessionRecord]:
        where = "WHERE as_of > :after" if after is not None else ""
        rows = self.connection.execute(
            text(f"SELECT * FROM trading_sessions {where} ORDER BY as_of"),
            {"after": after} if after is not None else {},
        ).mappings()
        return tuple(self._from_row(row) for row in rows)

    def put_session(self, session: object) -> TradingSessionRecord:
        if not isinstance(session, TradingSessionRecord):
            raise TypeError("trading session repository requires TradingSessionRecord")
        value = session.normalized()
        if value.schema_version != TRADING_SESSION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported trading session schema version: {value.schema_version}"
            )
        if value.actual_as_of not in (None, value.as_of):
            raise ValueError("trading session actual_as_of must match as_of")
        self.connection.execute(
            text(
                """
                INSERT INTO trading_sessions(
                    as_of, previous_as_of, actual_as_of, is_session, source,
                    schema_version, checksum, fetched_at, warnings_json
                ) VALUES (
                    :as_of, :previous_as_of, :actual_as_of, :is_session, :source,
                    :schema_version, :checksum, :fetched_at, :warnings_json
                )
                ON CONFLICT(as_of) DO UPDATE SET
                    previous_as_of = excluded.previous_as_of,
                    actual_as_of = excluded.actual_as_of,
                    is_session = excluded.is_session,
                    source = excluded.source,
                    schema_version = excluded.schema_version,
                    checksum = excluded.checksum,
                    fetched_at = excluded.fetched_at,
                    warnings_json = excluded.warnings_json
                """
            ),
            {
                "as_of": value.as_of,
                "previous_as_of": value.previous_as_of,
                "actual_as_of": value.actual_as_of,
                "is_session": int(value.is_session),
                "source": value.source,
                "schema_version": value.schema_version,
                "checksum": value.checksum,
                "fetched_at": value.fetched_at,
                "warnings_json": _canonical_json(list(value.warnings)),
            },
        )
        return value

    def put_session_if_absent(self, session: object) -> TradingSessionRecord:
        """Seed derived prior-session evidence without overwriting its owner."""

        if not isinstance(session, TradingSessionRecord):
            raise TypeError("trading session repository requires TradingSessionRecord")
        value = session.normalized()
        if value.schema_version != TRADING_SESSION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported trading session schema version: {value.schema_version}"
            )
        if value.actual_as_of not in (None, value.as_of):
            raise ValueError("trading session actual_as_of must match as_of")
        self.connection.execute(
            text(
                """
                INSERT INTO trading_sessions(
                    as_of, previous_as_of, actual_as_of, is_session, source,
                    schema_version, checksum, fetched_at, warnings_json
                ) VALUES (
                    :as_of, :previous_as_of, :actual_as_of, :is_session, :source,
                    :schema_version, :checksum, :fetched_at, :warnings_json
                )
                ON CONFLICT(as_of) DO NOTHING
                """
            ),
            {
                "as_of": value.as_of,
                "previous_as_of": value.previous_as_of,
                "actual_as_of": value.actual_as_of,
                "is_session": int(value.is_session),
                "source": value.source,
                "schema_version": value.schema_version,
                "checksum": value.checksum,
                "fetched_at": value.fetched_at,
                "warnings_json": _canonical_json(list(value.warnings)),
            },
        )
        stored = self.get_session(value.as_of)
        assert stored is not None
        return stored

    @staticmethod
    def _from_row(
        row: Mapping[str, Any],
        *,
        expected_as_of: date | None = None,
    ) -> TradingSessionRecord:
        value = TradingSessionRecord(
            as_of=_as_date(row["as_of"]),  # type: ignore[arg-type]
            previous_as_of=_as_date(row["previous_as_of"]),
            actual_as_of=_as_date(row["actual_as_of"]),
            is_session=bool(row["is_session"]),
            source=str(row["source"]),
            schema_version=int(row["schema_version"]),
            checksum=str(row["checksum"]),
            fetched_at=_as_datetime(row["fetched_at"]),
            warnings=tuple(str(item) for item in _json_load(row["warnings_json"], [])),
        )
        if expected_as_of is not None and value.as_of != expected_as_of:
            raise SnapshotIntegrityError(
                f"trading session exact-date mismatch: {expected_as_of.isoformat()}"
            )
        if value.schema_version != TRADING_SESSION_SCHEMA_VERSION:
            raise SnapshotIntegrityError(
                f"unsupported trading session schema version: {value.as_of.isoformat()}"
            )
        if payload_checksum(value.logical_dict()) != value.checksum:
            raise SnapshotIntegrityError(
                f"trading session checksum mismatch: {value.as_of.isoformat()}"
            )
        return value


class PostgresProviderCapabilityRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def get_capability(
        self,
        provider: str,
        dataset: str,
        revision: str,
    ) -> Mapping[str, Any] | None:
        row = self.connection.execute(
            text(
                "SELECT * FROM provider_capability_reports "
                "WHERE provider = :provider AND dataset = :dataset "
                "AND revision = :revision"
            ),
            {"provider": provider, "dataset": dataset, "revision": revision},
        ).mappings().first()
        return self._from_row(row).to_dict() if row is not None else None

    def put_capability(self, report: Mapping[str, Any]) -> None:
        value = ProviderCapabilityReport.from_dict(report).normalized()
        existing = self.connection.execute(
            text(
                "SELECT checksum FROM provider_capability_reports "
                "WHERE provider = :provider AND dataset = :dataset "
                "AND revision = :revision"
            ),
            {
                "provider": value.provider,
                "dataset": value.dataset,
                "revision": value.revision,
            },
        ).scalar_one_or_none()
        if existing is not None and str(existing) != value.checksum:
            raise ValueError(
                "capability revision already exists with a different checksum: "
                f"{value.provider}/{value.dataset}/{value.revision}"
            )
        payload = value.to_dict()
        self.connection.execute(
            text(
                """
                INSERT INTO provider_capability_reports(
                    provider, dataset, revision, status, endpoint,
                    field_coverage_json, date_evidence_json, history_window_json,
                    pagination_evidence_json, permission_evidence_json,
                    rate_limit_evidence_json, sample_count, warnings_json,
                    missing_evidence_json, checked_at, schema_version, checksum
                ) VALUES (
                    :provider, :dataset, :revision, :status, :endpoint,
                    :field_coverage_json, :date_evidence_json, :history_window_json,
                    :pagination_evidence_json, :permission_evidence_json,
                    :rate_limit_evidence_json, :sample_count, :warnings_json,
                    :missing_evidence_json, :checked_at, :schema_version, :checksum
                )
                ON CONFLICT(provider, dataset, revision) DO UPDATE SET
                    status = excluded.status,
                    endpoint = excluded.endpoint,
                    field_coverage_json = excluded.field_coverage_json,
                    date_evidence_json = excluded.date_evidence_json,
                    history_window_json = excluded.history_window_json,
                    pagination_evidence_json = excluded.pagination_evidence_json,
                    permission_evidence_json = excluded.permission_evidence_json,
                    rate_limit_evidence_json = excluded.rate_limit_evidence_json,
                    sample_count = excluded.sample_count,
                    warnings_json = excluded.warnings_json,
                    missing_evidence_json = excluded.missing_evidence_json,
                    checked_at = excluded.checked_at,
                    schema_version = excluded.schema_version,
                    checksum = excluded.checksum
                """
            ),
            {
                **payload,
                "field_coverage_json": _canonical_json(payload["field_coverage"]),
                "date_evidence_json": _canonical_json(payload["date_evidence"]),
                "history_window_json": _canonical_json(payload["history_window"]),
                "pagination_evidence_json": _canonical_json(payload["pagination_evidence"]),
                "permission_evidence_json": _canonical_json(payload["permission_evidence"]),
                "rate_limit_evidence_json": _canonical_json(payload["rate_limit_evidence"]),
                "warnings_json": _canonical_json(payload["warnings"]),
                "missing_evidence_json": _canonical_json(payload["missing_evidence"]),
            },
        )

    def list_capabilities(
        self,
        *,
        provider: str | None = None,
        dataset: str | None = None,
        status: str | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        clauses = []
        parameters: dict[str, Any] = {}
        for field, value in (
            ("provider", provider),
            ("dataset", dataset),
            ("status", status),
        ):
            if value is not None:
                clauses.append(f"{field} = :{field}")
                parameters[field] = value
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            text(
                "SELECT * FROM provider_capability_reports "
                f"{where} ORDER BY checked_at DESC, revision DESC"
            ),
            parameters,
        ).mappings()
        return tuple(self._from_row(row).to_dict() for row in rows)

    @staticmethod
    def _from_row(row: Mapping[str, Any]) -> ProviderCapabilityReport:
        return ProviderCapabilityReport.from_dict(
            {
                "provider": row["provider"],
                "dataset": row["dataset"],
                "revision": row["revision"],
                "status": row["status"],
                "endpoint": row["endpoint"],
                "field_coverage": _json_load(row["field_coverage_json"], {}),
                "date_evidence": _json_load(row["date_evidence_json"], {}),
                "history_window": _json_load(row["history_window_json"], {}),
                "pagination_evidence": _json_load(row["pagination_evidence_json"], {}),
                "permission_evidence": _json_load(row["permission_evidence_json"], {}),
                "rate_limit_evidence": _json_load(row["rate_limit_evidence_json"], {}),
                "sample_count": row["sample_count"],
                "warnings": _json_load(row["warnings_json"], []),
                "missing_evidence": _json_load(row["missing_evidence_json"], []),
                "checked_at": _as_datetime(row["checked_at"]).isoformat(),
                "schema_version": row["schema_version"],
                "checksum": row["checksum"],
            }
        )


__all__ = [
    "PostgresProviderCapabilityRepository",
    "PostgresSnapshotRepository",
    "PostgresTradingSessionRepository",
]
