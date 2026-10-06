"""Dataset-oriented collection port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ...domain.models import CollectionOutcome, DatasetDate


@runtime_checkable
class DatasetCollector(Protocol):
    dataset_id: str

    def collect(self, identity: DatasetDate) -> CollectionOutcome: ...


__all__ = ["DatasetCollector"]
