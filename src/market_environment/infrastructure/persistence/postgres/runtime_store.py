"""Explicit PostgreSQL runtime store adapter.

The public ``SnapshotStore`` module remains a migration/test compatibility
surface.  Normal application composition uses this PostgreSQL-only adapter so
the runtime cannot silently select a SQLite path.
"""

from __future__ import annotations

from ....snapshot_store import SnapshotStore


class PostgresRuntimeStore(SnapshotStore):
    def __init__(self, database_url: str) -> None:
        if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("PostgresRuntimeStore requires a PostgreSQL database URL")
        super().__init__(database_url=database_url, initialize_schema=False)


__all__ = ["PostgresRuntimeStore"]
