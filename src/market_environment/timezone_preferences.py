"""User/workspace timezone preferences and their small SQLite audit trail.

The market-environment service deliberately has no dependency on a platform
identity provider.  This module keeps the storage and identity boundary small:
the API adapter supplies a stable user/workspace subject, while a later
platform-auth integration can replace that adapter without changing the
preference contract or historical snapshot values.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

TimezoneScope = Literal["personal", "workspace"]

DEFAULT_USER_ID = "anonymous"
DEFAULT_WORKSPACE_ID = "default"
_SUPPORTED_TIMEZONES = frozenset(available_timezones())


def validate_timezone(value: str | None) -> str | None:
    """Validate and normalize an optional IANA timezone identifier.

    ``None`` clears a preference.  Values are intentionally not converted to
    another spelling: the caller's selected IANA identifier is retained for
    display and audit.  The tzdata set check rejects path-like/unknown values
    while still allowing standard IANA links such as ``US/Eastern`` and
    ``UTC``.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("timezone must be an IANA timezone string or null")
    candidate = value.strip()
    if not candidate:
        raise ValueError("timezone must be an IANA timezone string or null")
    if "\x00" in candidate or candidate.startswith("/") or ".." in candidate:
        raise ValueError(f"unsupported IANA timezone: {candidate!r}")
    if _SUPPORTED_TIMEZONES and candidate not in _SUPPORTED_TIMEZONES:
        raise ValueError(f"unsupported IANA timezone: {candidate!r}")
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unsupported IANA timezone: {candidate!r}") from exc
    return candidate


def resolve_timezone(
    personal_timezone: str | None,
    workspace_timezone: str | None,
    browser_timezone: str | None,
) -> tuple[str, Literal["personal", "workspace", "browser", "utc-fallback"]]:
    """Resolve display timezone without ever fabricating an invalid value."""

    for value, source in (
        (personal_timezone, "personal"),
        (workspace_timezone, "workspace"),
        (browser_timezone, "browser"),
    ):
        if not value:
            continue
        try:
            valid = validate_timezone(value)
        except ValueError:
            # A corrupt persisted preference must fail closed.  Do not skip to
            # a lower-priority value because that would hide the bad setting;
            # the client receives UTC and can diagnose it from the warning.
            return "UTC", "utc-fallback"
        if valid is not None:
            return valid, source  # type: ignore[return-value]
    return "UTC", "utc-fallback"


@dataclass(frozen=True)
class TimezonePreference:
    scope: TimezoneScope
    subject_id: str
    workspace_id: str
    timezone: str | None
    updated_at: datetime | None


class TimezonePreferenceStore:
    """SQLite-backed, scope-isolated preference store.

    Personal preferences are keyed by user and workspace preferences by
    workspace.  Audit rows are append-only and contain only subject IDs and
    timezone values; no credentials or request payloads are persisted.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS timezone_preferences (
                    scope TEXT NOT NULL CHECK(scope IN ('personal', 'workspace')),
                    subject_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT '',
                    timezone TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (scope, subject_id, workspace_id)
                );
                CREATE TABLE IF NOT EXISTS timezone_preference_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL CHECK(scope IN ('personal', 'workspace')),
                    subject_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT '',
                    actor_id TEXT NOT NULL,
                    previous_timezone TEXT,
                    timezone TEXT,
                    changed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS timezone_preference_audit_lookup_idx
                    ON timezone_preference_audit(scope, subject_id, workspace_id, audit_id);
                """
            )

    @staticmethod
    def _timestamp(value: datetime | None = None) -> str:
        current = value or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _key(scope: TimezoneScope, subject_id: str, workspace_id: str) -> tuple[str, str, str]:
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
        with self._connect() as connection:
            row = connection.execute(
                "SELECT scope, subject_id, workspace_id, timezone, updated_at "
                "FROM timezone_preferences WHERE scope = ? AND subject_id = ? AND workspace_id = ?",
                key,
            ).fetchone()
        if row is None:
            return TimezonePreference(scope, key[1], key[2], None, None)
        return TimezonePreference(
            scope=row["scope"],
            subject_id=row["subject_id"],
            workspace_id=row["workspace_id"],
            timezone=row["timezone"],
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
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
        timestamp = self._timestamp(changed_at)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT timezone FROM timezone_preferences "
                "WHERE scope = ? AND subject_id = ? AND workspace_id = ?",
                key,
            ).fetchone()
            previous = row["timezone"] if row else None
            connection.execute(
                """
                INSERT INTO timezone_preferences(scope, subject_id, workspace_id, timezone, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope, subject_id, workspace_id) DO UPDATE SET
                    timezone = excluded.timezone,
                    updated_at = excluded.updated_at
                """,
                (*key, validated, timestamp),
            )
            if previous != validated:
                connection.execute(
                    """
                    INSERT INTO timezone_preference_audit(
                        scope, subject_id, workspace_id, actor_id,
                        previous_timezone, timezone, changed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*key, actor_id, previous, validated, timestamp),
                )
        return TimezonePreference(scope, key[1], key[2], validated, datetime.fromisoformat(timestamp))

    def audit_entries(self) -> tuple[sqlite3.Row, ...]:
        """Return audit rows for offline verification and diagnostics."""

        with self._connect() as connection:
            return tuple(
                connection.execute(
                    "SELECT * FROM timezone_preference_audit ORDER BY audit_id"
                ).fetchall()
            )
