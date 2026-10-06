"""Explicit legacy SQLite adapter; never selected by normal runtime wiring."""

from __future__ import annotations

from pathlib import Path

from ....snapshot_store import LegacySnapshotStoreAdapter, SnapshotStore


class LegacySqliteSnapshotStore(SnapshotStore):
    """Open an explicitly named SQLite test or stopped-migration database."""

    def __init__(self, path: Path | str) -> None:
        super().__init__(backend=LegacySnapshotStoreAdapter(path))


__all__ = ["LegacySqliteSnapshotStore"]
