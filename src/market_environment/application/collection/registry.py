"""Deterministic registry for the five stable market datasets."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from types import MappingProxyType

from ...domain.models import DATASET_IDS, CollectionOutcome, DatasetDate
from ..ports import DatasetCollector


class DatasetCollectorRegistry:
    """Resolve one collector per stable dataset identifier."""

    def __init__(self, collectors: Iterable[DatasetCollector] = ()) -> None:
        registered: dict[str, DatasetCollector] = {}
        for collector in collectors:
            dataset_id = collector.dataset_id
            if dataset_id not in DATASET_IDS:
                raise ValueError(f"unsupported dataset collector: {dataset_id}")
            if dataset_id in registered:
                raise ValueError(f"duplicate dataset collector: {dataset_id}")
            registered[dataset_id] = collector
        self._collectors = MappingProxyType(registered)

    @classmethod
    def complete(
        cls,
        collectors: Iterable[DatasetCollector],
    ) -> "DatasetCollectorRegistry":
        registry = cls(collectors)
        missing = tuple(
            dataset_id
            for dataset_id in DATASET_IDS
            if dataset_id not in registry._collectors
        )
        if missing:
            raise ValueError(f"missing dataset collectors: {', '.join(missing)}")
        return registry

    @property
    def dataset_ids(self) -> tuple[str, ...]:
        return tuple(
            dataset_id for dataset_id in DATASET_IDS if dataset_id in self._collectors
        )

    def get(self, dataset_id: str) -> DatasetCollector:
        collector = self._collectors.get(dataset_id)
        if collector is None:
            raise ValueError(f"unknown dataset collector: {dataset_id}")
        return collector

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        return self.get(identity.dataset).collect(identity)

    def __contains__(self, dataset_id: object) -> bool:
        return dataset_id in self._collectors

    def __iter__(self) -> Iterator[DatasetCollector]:
        return (self._collectors[dataset_id] for dataset_id in self.dataset_ids)

    def __len__(self) -> int:
        return len(self._collectors)


__all__ = ["DatasetCollectorRegistry"]
