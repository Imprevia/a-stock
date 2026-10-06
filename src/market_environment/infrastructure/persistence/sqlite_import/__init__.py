"""Explicit SQLite fixture and stopped-migration input adapters."""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "LegacySqliteSnapshotStore":
        from .store import LegacySqliteSnapshotStore

        return LegacySqliteSnapshotStore
    raise AttributeError(name)


__all__ = ["LegacySqliteSnapshotStore"]
