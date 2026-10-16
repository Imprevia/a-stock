from __future__ import annotations

import json

from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from src.market_environment.infrastructure.persistence.postgres.integrity_audit import (
    audit_core_date_integrity,
)


def test_integrity_audit_is_read_only_and_reports_bounded_date_references() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.strip().upper())

    event.listen(engine, "before_cursor_execute", capture)
    payload = {
        "asOf": "2026-10-15",
        "quality": {"asOf": "2026-10-16", "effectiveAsOf": "2026-10-15"},
        "indices": [
            {
                "code": "sh000001",
                "history": [{"date": "2026-10-15", "close": 3200}],
            }
        ],
    }
    aggregate = {
        "asOf": "2026-10-15",
        "indices": payload["indices"],
        "_componentRevision": "revision-reference",
    }
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE snapshot_entries(dataset TEXT, as_of TEXT, payload_json TEXT, checksum TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE materialized_market_environment(as_of TEXT, payload_json TEXT, checksum TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO snapshot_entries VALUES (?, ?, ?, ?)",
            ("core", "2026-10-16", json.dumps(payload), "snapshot-checksum"),
        )
        connection.exec_driver_sql(
            "INSERT INTO materialized_market_environment VALUES (?, ?, ?)",
            ("2026-10-16", json.dumps(aggregate), "aggregate-checksum"),
        )
    statements.clear()

    with engine.connect() as connection:
        before = connection.exec_driver_sql(
            "SELECT (SELECT COUNT(*) FROM snapshot_entries), "
            "(SELECT COUNT(*) FROM materialized_market_environment)"
        ).one()
        statements.clear()
        findings = audit_core_date_integrity(connection)
        audit_statements = tuple(statements)
        after = connection.exec_driver_sql(
            "SELECT (SELECT COUNT(*) FROM snapshot_entries), "
            "(SELECT COUNT(*) FROM materialized_market_environment)"
        ).one()

    assert before == after == (1, 1)
    assert audit_statements and all(statement.startswith("SELECT") for statement in audit_statements)
    assert findings[0] == {
        "kind": "snapshot",
        "dataset": "core",
        "keyAsOf": "2026-10-16",
        "payloadAsOf": "2026-10-15",
        "qualityAsOf": "2026-10-16",
        "effectiveAsOf": "2026-10-15",
        "checksum": "snapshot-checksum",
        "componentRevision": None,
        "indices": ({"code": "sh000001", "historyTail": "2026-10-15"},),
    }
    assert findings[1]["componentRevision"] == "revision-reference"
    assert "close" not in str(findings)
    engine.dispose()
