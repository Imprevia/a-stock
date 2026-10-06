"""PostgreSQL lease, fencing-token, and fence-audit repository."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Connection, text

from ....domain.models import DatasetDate
from ....snapshot_store import (
    LeaseFenceError,
    LeaseToken,
    lease_token_fingerprint,
)
from .repositories import _as_date, _as_datetime


class PostgresLeaseRepository:
    def __init__(
        self,
        connection: Connection,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.connection = connection
        self.now = now or (lambda: datetime.now(timezone.utc))

    def acquire(
        self,
        identity: DatasetDate,
        owner: str,
        *,
        lease_seconds: float,
    ) -> LeaseToken | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = self._utc(self.now())
        expires_at = current + timedelta(seconds=lease_seconds)
        if self.connection.dialect.name == "postgresql":
            self.connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lease_key))"),
                {
                    "lease_key": (
                        f"market-lease:{identity.dataset}:{identity.as_of.isoformat()}"
                    )
                },
            )
        suffix = " FOR UPDATE" if self.connection.dialect.name == "postgresql" else ""
        row = self.connection.execute(
            text(
                "SELECT owner, expires_at, generation, token FROM refresh_leases "
                "WHERE dataset = :dataset AND as_of = :as_of" + suffix
            ),
            {"dataset": identity.dataset, "as_of": identity.as_of},
        ).mappings().first()
        if row is not None and _as_datetime(row["expires_at"]) > current:
            return None
        ledger = self.connection.execute(
            text(
                "SELECT generation FROM refresh_lease_fences "
                "WHERE dataset = :dataset AND as_of = :as_of"
            ),
            {"dataset": identity.dataset, "as_of": identity.as_of},
        ).scalar_one_or_none()
        prior_generation = int(ledger or 0)
        if row is not None:
            prior_generation = max(prior_generation, int(row["generation"]))
        generation = prior_generation + 1
        token_value = f"{generation}-{uuid.uuid4().hex}"
        lease = LeaseToken(
            identity.dataset,
            identity.as_of,
            owner,
            generation,
            token_value,
            expires_at,
        )
        self.connection.execute(
            text(
                """
                INSERT INTO refresh_lease_fences(
                    dataset, as_of, generation, token, updated_at
                ) VALUES (
                    :dataset, :as_of, :generation, :token, :updated_at
                )
                ON CONFLICT(dataset, as_of) DO UPDATE SET
                    generation = excluded.generation,
                    token = excluded.token,
                    updated_at = excluded.updated_at
                """
            ),
            {
                "dataset": identity.dataset,
                "as_of": identity.as_of,
                "generation": generation,
                "token": "[redacted]",
                "updated_at": current.isoformat(),
            },
        )
        self.connection.execute(
            text(
                """
                INSERT INTO refresh_leases(
                    dataset, as_of, owner, acquired_at, expires_at, generation, token
                ) VALUES (
                    :dataset, :as_of, :owner, :acquired_at, :expires_at,
                    :generation, :token
                )
                ON CONFLICT(dataset, as_of) DO UPDATE SET
                    owner = excluded.owner,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at,
                    generation = excluded.generation,
                    token = excluded.token
                """
            ),
            {
                "dataset": identity.dataset,
                "as_of": identity.as_of,
                "owner": owner,
                "acquired_at": current.isoformat(),
                "expires_at": expires_at.isoformat(),
                "generation": generation,
                "token": token_value,
            },
        )
        return lease

    def get(
        self,
        identity: DatasetDate,
        *,
        owner: str | None = None,
    ) -> LeaseToken | None:
        owner_clause = " AND owner = :owner" if owner is not None else ""
        parameters: dict[str, Any] = {
            "dataset": identity.dataset,
            "as_of": identity.as_of,
        }
        if owner is not None:
            parameters["owner"] = owner
        row = self.connection.execute(
            text(
                "SELECT owner, generation, token, expires_at FROM refresh_leases "
                "WHERE dataset = :dataset AND as_of = :as_of" + owner_clause
            ),
            parameters,
        ).mappings().first()
        if row is None:
            return None
        return LeaseToken(
            identity.dataset,
            identity.as_of,
            str(row["owner"]),
            int(row["generation"]),
            str(row["token"]),
            _as_datetime(row["expires_at"]),
        )

    def renew(
        self,
        lease: object,
        *,
        lease_seconds: float,
    ) -> LeaseToken | None:
        if not isinstance(lease, LeaseToken):
            raise TypeError("lease repository requires LeaseToken")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = self._utc(self.now())
        expires_at = current + timedelta(seconds=lease_seconds)
        result = self.connection.execute(
            text(
                """
                UPDATE refresh_leases
                SET acquired_at = :acquired_at, expires_at = :expires_at
                WHERE dataset = :dataset AND as_of = :as_of AND owner = :owner
                  AND generation = :generation AND token = :token
                  AND expires_at > :current
                """
            ),
            {
                "acquired_at": current.isoformat(),
                "expires_at": expires_at.isoformat(),
                "dataset": lease.dataset,
                "as_of": lease.as_of,
                "owner": lease.owner,
                "generation": lease.generation,
                "token": lease.token,
                "current": current.isoformat(),
            },
        )
        if result.rowcount == 0:
            return None
        return LeaseToken(
            lease.dataset,
            lease.as_of,
            lease.owner,
            lease.generation,
            lease.token,
            expires_at,
        )

    def release(self, lease: object) -> bool:
        if not isinstance(lease, LeaseToken):
            return False
        result = self.connection.execute(
            text(
                """
                DELETE FROM refresh_leases
                WHERE dataset = :dataset AND as_of = :as_of AND owner = :owner
                  AND generation = :generation AND token = :token
                """
            ),
            {
                "dataset": lease.dataset,
                "as_of": lease.as_of,
                "owner": lease.owner,
                "generation": lease.generation,
                "token": lease.token,
            },
        )
        return result.rowcount > 0

    def assert_valid(
        self,
        lease: LeaseToken,
        operation: str,
        *,
        expected_identity: DatasetDate | None = None,
    ) -> None:
        current = self._utc(self.now())
        if expected_identity is not None and (
            lease.dataset != expected_identity.dataset
            or lease.as_of != expected_identity.as_of
        ):
            raise LeaseFenceError(
                "lease fenced: credential dataset/date does not match the write",
                lease=lease,
                operation=operation,
            )
        row = self.connection.execute(
            text(
                "SELECT owner, generation, token, expires_at FROM refresh_leases "
                "WHERE dataset = :dataset AND as_of = :as_of"
            ),
            {"dataset": lease.dataset, "as_of": lease.as_of},
        ).mappings().first()
        if (
            row is None
            or row["owner"] != lease.owner
            or int(row["generation"]) != lease.generation
            or row["token"] != lease.token
            or _as_datetime(row["expires_at"]) <= current
        ):
            raise LeaseFenceError(
                "lease fenced: owner/token differs or lease has expired",
                lease=lease,
                operation=operation,
            )

    def execute_fenced(
        self,
        lease: object,
        operation: str,
        writer: object,
        *,
        expected_identity: DatasetDate | None = None,
    ) -> object:
        if not isinstance(lease, LeaseToken):
            raise TypeError("fenced write requires LeaseToken")
        if not callable(writer):
            raise TypeError("fenced write requires a callable writer")
        try:
            self.assert_valid(
                lease,
                operation,
                expected_identity=expected_identity,
            )
        except LeaseFenceError as error:
            self.record_fence_event(error)
            raise
        return writer(self.connection)

    def record_fence_event(
        self,
        error: LeaseFenceError,
        *,
        created_at: datetime | None = None,
    ) -> None:
        lease = error.lease
        self.connection.execute(
            text(
                """
                INSERT INTO lease_fence_events(
                    dataset, as_of, owner, generation, token, operation,
                    reason, created_at
                ) VALUES (
                    :dataset, :as_of, :owner, :generation, :token, :operation,
                    :reason, :created_at
                )
                """
            ),
            {
                "dataset": lease.dataset,
                "as_of": lease.as_of,
                "owner": lease.owner,
                "generation": lease.generation,
                "token": lease_token_fingerprint(lease.token),
                "operation": error.operation,
                "reason": str(error),
                "created_at": self._utc(created_at or self.now()).isoformat(),
            },
        )

    def list_fence_events(
        self,
        *,
        identity: DatasetDate | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        where = (
            "WHERE dataset = :dataset AND as_of = :as_of"
            if identity is not None
            else ""
        )
        parameters = (
            {"dataset": identity.dataset, "as_of": identity.as_of}
            if identity is not None
            else {}
        )
        rows = self.connection.execute(
            text(f"SELECT * FROM lease_fence_events {where} ORDER BY event_id"),
            parameters,
        ).mappings()
        return tuple(
            {
                **dict(row),
                "as_of": _as_date(row["as_of"]),
                "created_at": _as_datetime(row["created_at"]),
                "token_fingerprint": row["token"],
            }
            for row in rows
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


__all__ = ["PostgresLeaseRepository"]
