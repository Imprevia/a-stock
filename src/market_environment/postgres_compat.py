"""Small DB-API compatibility layer for the existing SnapshotStore SQL.

The domain store historically used sqlite3's qmark placeholders and row
objects.  This adapter keeps that internal contract while routing execution
through a SQLAlchemy PostgreSQL connection during the migration.  It is an
implementation seam, not a second storage backend.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import Connection, text


class PostgresRow:
    def __init__(self, row: Any, keys: tuple[str, ...]) -> None:
        self._mapping = dict(zip(keys, row, strict=False))
        for key, value in list(self._mapping.items()):
            if key.endswith("_json") and value is not None and not isinstance(value, str):
                self._mapping[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            elif isinstance(value, (date, datetime)):
                self._mapping[key] = value.isoformat()

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return tuple(self._mapping.values())[key]
        return self._mapping[key]

    def keys(self):
        return self._mapping.keys()

    def __iter__(self):
        return iter(self._mapping.values())


class PostgresResult:
    def __init__(self, result: Any) -> None:
        self.rowcount = getattr(result, "rowcount", -1)
        if getattr(result, "returns_rows", True):
            self._keys = tuple(result.keys())
            self._rows = [PostgresRow(row, self._keys) for row in result.fetchall()]
        else:
            self._keys = ()
            self._rows = []
        self._index = 0

    def fetchone(self) -> PostgresRow | None:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self) -> list[PostgresRow]:
        rows = self._rows[self._index :]
        self._index = len(self._rows)
        return rows


_QMARK = re.compile(r"\?")


def _translate_sql(sql: str) -> str | None:
    stripped = sql.strip()
    upper = stripped.upper()
    if upper.startswith("PRAGMA ") or upper in {"BEGIN", "BEGIN IMMEDIATE", "COMMIT"}:
        return None
    had_ignore = bool(re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", sql, flags=re.I))
    had_replace = bool(re.search(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", sql, flags=re.I))
    sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, flags=re.I)
    sql = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "INSERT INTO", sql, flags=re.I)
    sql = re.sub(r"\bSELECT\s+rowid\s*,", "SELECT id AS rowid,", sql, flags=re.I)
    sql = _QMARK.sub("%s", sql)
    # SQLite INSERT OR IGNORE is used only for idempotent migration/fence rows.
    if had_ignore:
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    elif had_replace and re.search(r"\brefresh_runs\b", sql, flags=re.I):
        sql = sql.rstrip().rstrip(";") + (
            " ON CONFLICT (run_id, dataset) DO UPDATE SET "
            "as_of = EXCLUDED.as_of, result_json = EXCLUDED.result_json, created_at = EXCLUDED.created_at"
        )
    return sql


class PostgresConnection:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def __enter__(self) -> "PostgresConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> PostgresResult:
        translated = _translate_sql(sql)
        if translated is None:
            class Empty:
                def keys(self): return ()
                def fetchall(self): return []
            return PostgresResult(Empty())
        values = tuple(params or ())
        result = self.connection.exec_driver_sql(translated, values)
        return PostgresResult(result)

    def close(self) -> None:
        self.connection.close()

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()
