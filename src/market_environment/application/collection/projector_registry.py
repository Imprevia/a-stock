"""Complete registry for provider-free dataset detail projectors."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Any

from ...domain.models import DATASET_IDS, CollectionCandidate, DatasetDate
from ..ports import DatasetDetailProjector


class DatasetDetailProjectorRegistry:
    def __init__(self, projectors: Iterable[DatasetDetailProjector] = ()) -> None:
        registered: dict[str, DatasetDetailProjector] = {}
        for projector in projectors:
            dataset_id = projector.dataset_id
            if dataset_id not in DATASET_IDS:
                raise ValueError(f"unsupported dataset detail projector: {dataset_id}")
            if dataset_id in registered:
                raise ValueError(f"duplicate dataset detail projector: {dataset_id}")
            registered[dataset_id] = projector
        self._projectors = MappingProxyType(registered)

    @classmethod
    def complete(
        cls,
        projectors: Iterable[DatasetDetailProjector],
    ) -> "DatasetDetailProjectorRegistry":
        registry = cls(projectors)
        missing = tuple(
            dataset_id for dataset_id in DATASET_IDS if dataset_id not in registry._projectors
        )
        if missing:
            raise ValueError(f"missing dataset detail projectors: {', '.join(missing)}")
        return registry

    @property
    def dataset_ids(self) -> tuple[str, ...]:
        return tuple(dataset_id for dataset_id in DATASET_IDS if dataset_id in self._projectors)

    def get(self, dataset_id: str) -> DatasetDetailProjector:
        projector = self._projectors.get(dataset_id)
        if projector is None:
            raise ValueError(f"unknown dataset detail projector: {dataset_id}")
        return projector

    def project(
        self,
        identity: DatasetDate,
        candidate: CollectionCandidate | None,
    ) -> Mapping[str, Any] | None:
        return self.get(identity.dataset).project(identity, candidate)

    def __iter__(self) -> Iterator[DatasetDetailProjector]:
        return (self._projectors[dataset_id] for dataset_id in self.dataset_ids)

    def __len__(self) -> int:
        return len(self._projectors)


__all__ = ["DatasetDetailProjectorRegistry"]
