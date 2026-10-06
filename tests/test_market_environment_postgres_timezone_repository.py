from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.market_environment.application.ports import TimezonePreferenceRepository
from src.market_environment.infrastructure.persistence.postgres import (
    PostgresTimezonePreferenceRepository,
)
from src.market_environment.interfaces.http.dependencies import (
    get_timezone_commands,
    get_timezone_queries,
)
from src.market_environment.interfaces.http.routers.timezone_preferences import router


NOW = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


@pytest.fixture
def timezone_connection():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    connection = engine.connect()
    connection.exec_driver_sql(
        """
        CREATE TABLE timezone_preferences (
            scope TEXT NOT NULL, subject_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL DEFAULT '', timezone TEXT,
            updated_at TEXT,
            PRIMARY KEY(scope, subject_id, workspace_id)
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE timezone_preference_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL, subject_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL DEFAULT '', actor_id TEXT NOT NULL,
            previous_timezone TEXT, timezone TEXT, changed_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()
        engine.dispose()


def test_timezone_repository_preserves_scope_keys_fallback_and_audit(
    timezone_connection,
) -> None:
    repository = PostgresTimezonePreferenceRepository(
        timezone_connection,
        now=lambda: NOW,
    )

    assert isinstance(repository, TimezonePreferenceRepository)
    assert repository.get(
        "personal", subject_id="user-a", workspace_id="workspace-a"
    ).timezone is None
    repository.set(
        "workspace",
        subject_id="user-a",
        workspace_id="workspace-a",
        timezone_value="Asia/Shanghai",
        actor_id="owner-a",
    )
    repository.set(
        "personal",
        subject_id="user-a",
        workspace_id="workspace-a",
        timezone_value="America/New_York",
        actor_id="user-a",
    )
    repository.set(
        "personal",
        subject_id="user-a",
        workspace_id="workspace-a",
        timezone_value="America/New_York",
        actor_id="user-a",
    )

    personal = repository.get(
        "personal", subject_id="user-a", workspace_id="workspace-b"
    )
    workspace = repository.get(
        "workspace", subject_id="another-user", workspace_id="workspace-a"
    )
    assert (personal.subject_id, personal.workspace_id, personal.timezone) == (
        "user-a",
        "",
        "America/New_York",
    )
    assert (workspace.subject_id, workspace.workspace_id, workspace.timezone) == (
        "workspace-a",
        "workspace-a",
        "Asia/Shanghai",
    )
    assert [entry["timezone"] for entry in repository.list_audit_entries()] == [
        "Asia/Shanghai",
        "America/New_York",
    ]


def test_timezone_repository_participates_in_caller_transaction(
    timezone_connection,
) -> None:
    repository = PostgresTimezonePreferenceRepository(
        timezone_connection,
        now=lambda: NOW,
    )
    with pytest.raises(RuntimeError, match="rollback"):
        with timezone_connection.begin():
            repository.set(
                "personal",
                subject_id="user-a",
                workspace_id="workspace-a",
                timezone_value="UTC",
                actor_id="user-a",
            )
            raise RuntimeError("rollback")

    assert repository.get(
        "personal", subject_id="user-a", workspace_id="workspace-a"
    ).timezone is None
    assert repository.list_audit_entries() == ()


def test_timezone_route_keeps_workspace_authorization_and_fallback(
    timezone_connection,
) -> None:
    repository = PostgresTimezonePreferenceRepository(
        timezone_connection,
        now=lambda: NOW,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_timezone_queries] = lambda: repository
    app.dependency_overrides[get_timezone_commands] = lambda: repository

    with TestClient(app) as client:
        forbidden = client.put(
            "/api/preferences/timezone",
            headers={"x-user-id": "user-a", "x-workspace-id": "workspace-a"},
            json={"scope": "workspace", "timezone": "Asia/Shanghai"},
        )
        assert forbidden.status_code == 403

        updated = client.put(
            "/api/preferences/timezone",
            headers={
                "x-user-id": "owner-a",
                "x-workspace-id": "workspace-a",
                "x-workspace-role": "owner",
            },
            json={"scope": "workspace", "timezone": "Asia/Shanghai"},
        )
        assert updated.status_code == 200
        assert updated.json()["effectiveSource"] == "workspace"

        browser = client.get(
            "/api/preferences/timezone",
            headers={
                "x-user-id": "user-b",
                "x-workspace-id": "workspace-b",
                "x-browser-timezone": "UTC",
            },
        )
        assert browser.json()["effectiveSource"] == "browser"


class _Result:
    def __init__(self, row=None) -> None:
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _RecordingPostgresConnection:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        return _Result(None)


def test_postgres_timezone_write_serializes_first_write_and_row_update() -> None:
    connection = _RecordingPostgresConnection()
    repository = PostgresTimezonePreferenceRepository(connection, now=lambda: NOW)

    repository.set(
        "workspace",
        subject_id="owner-a",
        workspace_id="workspace-a",
        timezone_value="UTC",
        actor_id="owner-a",
    )

    statements = [sql for sql, _ in connection.calls]
    assert "pg_advisory_xact_lock" in statements[0]
    assert "FOR UPDATE" in statements[1]
    assert "INSERT INTO timezone_preferences" in statements[2]
    assert "INSERT INTO timezone_preference_audit" in statements[3]
