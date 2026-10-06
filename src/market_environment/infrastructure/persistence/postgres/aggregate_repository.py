"""PostgreSQL materialized aggregate repository with revision CAS."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text

from ....domain.models import MaterializationRevision
from ....snapshot_store import (
    MATERIALIZED_COMPONENT_REVISION_KEY,
    MaterializedAggregateConflict,
    SnapshotIntegrityError,
    payload_checksum,
)
from .lease_repository import PostgresLeaseRepository
from .repositories import _as_datetime, _canonical_json, _json_load


class PostgresMaterializedAggregateRepository:
    def __init__(
        self,
        connection: Connection,
        *,
        leases: PostgresLeaseRepository | None = None,
    ) -> None:
        self.connection = connection
        self.leases = leases

    def get_aggregate(self, as_of: date) -> Mapping[str, Any] | None:
        row = self.connection.execute(
            text(
                "SELECT * FROM materialized_market_environment "
                "WHERE as_of = :as_of"
            ),
            {"as_of": as_of},
        ).mappings().first()
        if row is None:
            return None
        payload = dict(_json_load(row["payload_json"], {}))
        if payload_checksum(payload) != row["checksum"]:
            raise SnapshotIntegrityError(
                f"materialized aggregate checksum mismatch: {as_of.isoformat()}"
            )
        if payload.get("asOf") not in (None, as_of.isoformat()):
            raise SnapshotIntegrityError(
                f"materialized aggregate exact-date mismatch: {as_of.isoformat()}"
            )
        return payload

    def revision(self, as_of: date) -> MaterializationRevision:
        state = {
            "snapshots": self._rows(
                """
                SELECT dataset, as_of, source, status, observations, warnings_json,
                       fetched_at, settled, schema_version, checksum, refresh_warning
                FROM snapshot_entries
                WHERE as_of = :as_of
                   OR (dataset = 'breadth' AND as_of < :as_of)
                   OR (
                       dataset = 'limits'
                       AND as_of = (
                           SELECT previous_as_of FROM trading_sessions WHERE as_of = :as_of
                       )
                   )
                ORDER BY dataset, as_of
                """,
                as_of,
            ),
            "tradingSessions": self._rows(
                """
                SELECT as_of, previous_as_of, actual_as_of, is_session, source,
                       schema_version, checksum, warnings_json
                FROM trading_sessions
                WHERE as_of = :as_of
                   OR as_of = (
                       SELECT previous_as_of FROM trading_sessions WHERE as_of = :as_of
                   )
                ORDER BY as_of
                """,
                as_of,
            ),
            "limitDatasets": self._rows(
                """
                SELECT as_of, actual_as_of, source, source_revision, rule_version,
                       schema_version, complete, excluded, warnings_json, dataset_checksum
                FROM limit_security_datasets
                WHERE as_of = :as_of
                   OR as_of = (
                       SELECT previous_as_of FROM trading_sessions WHERE as_of = :as_of
                   )
                ORDER BY as_of
                """,
                as_of,
            ),
            "componentVersions": self._rows(
                """
                SELECT component_kind, dataset, as_of, revision
                FROM materialization_component_versions
                WHERE (
                        component_kind = 'snapshot'
                        AND (
                            as_of = :as_of
                            OR (dataset = 'breadth' AND as_of < :as_of)
                            OR (
                                dataset = 'limits'
                                AND as_of = (
                                    SELECT previous_as_of FROM trading_sessions
                                    WHERE as_of = :as_of
                                )
                            )
                        )
                      )
                   OR (
                        component_kind = 'trading_session'
                        AND (
                            as_of = :as_of
                            OR as_of = (
                                SELECT previous_as_of FROM trading_sessions
                                WHERE as_of = :as_of
                            )
                        )
                      )
                   OR (
                        component_kind IN ('limit_dataset', 'limit_facts')
                        AND (
                            as_of = :as_of
                            OR as_of = (
                                SELECT previous_as_of FROM trading_sessions
                                WHERE as_of = :as_of
                            )
                        )
                      )
                ORDER BY component_kind, dataset, as_of
                """,
                as_of,
            ),
        }
        return MaterializationRevision(payload_checksum(state))

    def compare_and_swap(
        self,
        as_of: date,
        expected: MaterializationRevision,
        payload: Mapping[str, Any],
        *,
        lease: object | None = None,
    ) -> MaterializationRevision:
        if lease is not None:
            if self.leases is None:
                raise ValueError("fenced aggregate write requires a lease repository")
            return self.leases.execute_fenced(
                lease,
                "materialized_aggregate",
                lambda _connection: self._compare_and_swap(as_of, expected, payload),
            )  # type: ignore[return-value]
        return self._compare_and_swap(as_of, expected, payload)

    def _compare_and_swap(
        self,
        as_of: date,
        expected: MaterializationRevision,
        payload: Mapping[str, Any],
    ) -> MaterializationRevision:
        try:
            if self.connection.dialect.name == "postgresql":
                self.connection.execute(
                    text(
                        "LOCK TABLE materialization_component_versions IN SHARE MODE"
                    )
                )
            current = self.revision(as_of)
            if current != expected:
                raise MaterializedAggregateConflict(
                    "materialized aggregate inputs changed before commit"
                )
            value = dict(payload)
            if value.get("asOf") not in (None, as_of.isoformat()):
                raise ValueError("materialized aggregate payload date does not match key")
            if value.get(MATERIALIZED_COMPONENT_REVISION_KEY) != expected.value:
                raise ValueError(
                    "materialized aggregate payload revision does not match its inputs"
                )
            checksum = payload_checksum(value)
            generated_at = value.get("generatedAt")
            generated = (
                _as_datetime(generated_at)
                if generated_at is not None
                else datetime.now().astimezone()
            )
            self.connection.execute(
                text(
                    """
                    INSERT INTO materialized_market_environment(
                        as_of, payload_json, generated_at, checksum
                    ) VALUES (
                        :as_of, :payload_json, :generated_at, :checksum
                    )
                    ON CONFLICT(as_of) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        generated_at = excluded.generated_at,
                        checksum = excluded.checksum
                    """
                ),
                {
                    "as_of": as_of,
                    "payload_json": _canonical_json(value),
                    "generated_at": generated,
                    "checksum": checksum,
                },
            )
            return current
        except MaterializedAggregateConflict:
            raise
        except Exception as error:
            message = str(error).lower()
            if "could not serialize" in message or "serializationfailure" in message:
                raise MaterializedAggregateConflict(
                    "materialized aggregate inputs changed before commit"
                ) from error
            raise

    def _rows(self, statement: str, as_of: date) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(statement),
            {"as_of": as_of},
        ).mappings()
        return [self._normalized_row(row) for row in rows]

    @staticmethod
    def _normalized_row(row: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (date, datetime)):
                result[key] = value.isoformat()
            elif key.endswith("_json") and value is not None and not isinstance(value, str):
                result[key] = _canonical_json(value)
            else:
                result[key] = value
        return result


__all__ = ["PostgresMaterializedAggregateRepository"]
