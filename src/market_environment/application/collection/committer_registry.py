"""Fail-closed committer registry for the five stable datasets."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from types import MappingProxyType

from ...domain.models import DATASET_IDS
from ..ports.committers import (
    DatasetCommitEvidence,
    DatasetCommitRequest,
    DatasetCommitter,
)


class DatasetCommitterRegistry:
    """Resolve exactly one persistence strategy per stable dataset."""

    def __init__(self, committers: Iterable[DatasetCommitter] = ()) -> None:
        registered: dict[str, DatasetCommitter] = {}
        for committer in committers:
            dataset_id = committer.dataset_id
            if dataset_id not in DATASET_IDS:
                raise ValueError(f"unsupported dataset committer: {dataset_id}")
            if dataset_id in registered:
                raise ValueError(f"duplicate dataset committer: {dataset_id}")
            registered[dataset_id] = committer
        self._committers = MappingProxyType(registered)

    @classmethod
    def complete(
        cls,
        committers: Iterable[DatasetCommitter],
    ) -> "DatasetCommitterRegistry":
        registry = cls(committers)
        missing = tuple(
            dataset_id
            for dataset_id in DATASET_IDS
            if dataset_id not in registry._committers
        )
        if missing:
            raise ValueError(f"missing dataset committers: {', '.join(missing)}")
        return registry

    @property
    def dataset_ids(self) -> tuple[str, ...]:
        return tuple(
            dataset_id for dataset_id in DATASET_IDS if dataset_id in self._committers
        )

    def get(self, dataset_id: str) -> DatasetCommitter:
        committer = self._committers.get(dataset_id)
        if committer is None:
            raise ValueError(f"unknown dataset committer: {dataset_id}")
        return committer

    def commit(self, request: DatasetCommitRequest) -> DatasetCommitEvidence:
        return self.get(request.identity.dataset).commit(request)

    def __contains__(self, dataset_id: object) -> bool:
        return dataset_id in self._committers

    def __iter__(self) -> Iterator[DatasetCommitter]:
        return (self._committers[dataset_id] for dataset_id in self.dataset_ids)

    def __len__(self) -> int:
        return len(self._committers)


__all__ = ["DatasetCommitterRegistry"]
