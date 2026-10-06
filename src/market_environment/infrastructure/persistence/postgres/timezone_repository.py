"""PostgreSQL timezone preference repository over a shared transaction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import Connection, text

from ....timezone_preferences import (
    TimezonePreference,
    TimezoneScope,
    validate_timezone,
)
from .repositories import _as_datetime


class PostgresTimezonePreferenceRepository:
    """Persist scope-isolated preferences and append-only audit entries."""

    def __init__(
        self,
        connection: Connection,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.connection = connection
        self.now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _key(
        scope: TimezoneScope,
        subject_id: str,
        workspace_id: str,
    ) -> tuple[str, str, str]:
        if scope == "personal":
            return scope, subject_id, ""
        return scope, workspace_id, workspace_id

    def get(
        self,
        scope: TimezoneScope,
        *,
        subject_id: str,
        workspace_id: str,
    ) -> TimezonePreference:
        key = self._key(scope, subject_id, workspace_id)
        row = self.connection.execute(
            text(
                "SELECT scope, subject_id, workspace_id, timezone, updated_at "
                "FROM timezone_preferences WHERE scope = :scope "
                "AND subject_id = :subject_id AND workspace_id = :workspace_id"
            ),
            self._parameters(key),
        ).mappings().first()
        if row is None:
            return TimezonePreference(scope, key[1], key[2], None, None)
        return TimezonePreference(
            scope=row["scope"],
            subject_id=row["subject_id"],
            workspace_id=row["workspace_id"],
            timezone=row["timezone"],
            updated_at=(
                _as_datetime(row["updated_at"])
                if row["updated_at"] is not None
                else None
            ),
        )

    def set(
        self,
        scope: TimezoneScope,
        *,
        subject_id: str,
        workspace_id: str,
        timezone_value: str | None,
        actor_id: str,
        changed_at: datetime | None = None,
    ) -> TimezonePreference:
        validated = validate_timezone(timezone_value)
        key = self._key(scope, subject_id, workspace_id)
        timestamp = self._utc(changed_at or self.now())
        parameters = self._parameters(key)
        if self.connection.dialect.name == "postgresql":
            self.connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"market-timezone:{key[0]}:{key[1]}:{key[2]}"},
            )
        lock_clause = (
            " FOR UPDATE" if self.connection.dialect.name == "postgresql" else ""
        )
        row = self.connection.execute(
            text(
                "SELECT timezone FROM timezone_preferences "
                "WHERE scope = :scope AND subject_id = :subject_id "
                f"AND workspace_id = :workspace_id{lock_clause}"
            ),
            parameters,
        ).mappings().first()
        previous = row["timezone"] if row is not None else None
        self.connection.execute(
            text(
                """
                INSERT INTO timezone_preferences(
                    scope, subject_id, workspace_id, timezone, updated_at
                ) VALUES (
                    :scope, :subject_id, :workspace_id, :timezone, :updated_at
                )
                ON CONFLICT(scope, subject_id, workspace_id) DO UPDATE SET
                    timezone = excluded.timezone,
                    updated_at = excluded.updated_at
                """
            ),
            {
                **parameters,
                "timezone": validated,
                "updated_at": timestamp,
            },
        )
        if previous != validated:
            self.connection.execute(
                text(
                    """
                    INSERT INTO timezone_preference_audit(
                        scope, subject_id, workspace_id, actor_id,
                        previous_timezone, timezone, changed_at
                    ) VALUES (
                        :scope, :subject_id, :workspace_id, :actor_id,
                        :previous_timezone, :timezone, :changed_at
                    )
                    """
                ),
                {
                    **parameters,
                    "actor_id": actor_id,
                    "previous_timezone": previous,
                    "timezone": validated,
                    "changed_at": timestamp,
                },
            )
        return TimezonePreference(scope, key[1], key[2], validated, timestamp)

    def list_audit_entries(self) -> Sequence[Mapping[str, Any]]:
        return tuple(
            dict(row)
            for row in self.connection.execute(
                text("SELECT * FROM timezone_preference_audit ORDER BY audit_id")
            ).mappings()
        )

    @staticmethod
    def _parameters(key: tuple[str, str, str]) -> dict[str, str]:
        return {
            "scope": key[0],
            "subject_id": key[1],
            "workspace_id": key[2],
        }

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


__all__ = ["PostgresTimezonePreferenceRepository"]
