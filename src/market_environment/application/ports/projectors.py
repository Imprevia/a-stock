"""Provider-free local dataset detail projection port."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from ...domain.models import CollectionCandidate, DatasetDate


@runtime_checkable
class DatasetDetailProjector(Protocol):
    dataset_id: str

    def project(
        self,
        identity: DatasetDate,
        candidate: CollectionCandidate | None,
    ) -> Mapping[str, Any] | None: ...


__all__ = ["DatasetDetailProjector"]
