"""Narrow persistence protocols owned by application use cases."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any, Protocol, runtime_checkable

from ...domain.models import (
    CollectionCandidate,
    DatasetDate,
    MaterializationRevision,
)


@runtime_checkable
class SnapshotReader(Protocol):
    def get(self, identity: DatasetDate) -> CollectionCandidate | None: ...

    def list_dates(self, dataset: str) -> Sequence[date]: ...


@runtime_checkable
class SnapshotRepository(SnapshotReader, Protocol):
    def put(self, candidate: CollectionCandidate) -> CollectionCandidate: ...


@runtime_checkable
class CollectionRunRepository(Protocol):
    def get_run(self, run_id: str) -> object | None: ...

    def save_run(self, run: object) -> object: ...


@runtime_checkable
class CollectionTaskRepository(Protocol):
    def get_task(self, task_id: str) -> object | None: ...

    def list_tasks(self, run_id: str) -> Sequence[object]: ...

    def save_task(self, task: object) -> object: ...


@runtime_checkable
class CoreIndexResultRepository(Protocol):
    def list_results(self, task_id: str) -> Sequence[object]: ...

    def put_result(self, result: object) -> object: ...


@runtime_checkable
class CollectionStatusReader(Protocol):
    def collection_status(self, as_of: date) -> Mapping[str, Any]: ...

    def get_run(self, run_id: str) -> object | None: ...


@runtime_checkable
class LeaseRepository(Protocol):
    def acquire(self, identity: DatasetDate, owner: str, *, lease_seconds: float) -> object | None: ...

    def renew(self, lease: object, *, lease_seconds: float) -> object | None: ...

    def release(self, lease: object) -> bool: ...

    def execute_fenced(
        self,
        lease: object,
        operation: str,
        writer: object,
        *,
        expected_identity: DatasetDate | None = None,
    ) -> object: ...

    def list_fence_events(
        self,
        *,
        identity: DatasetDate | None = None,
    ) -> Sequence[Mapping[str, Any]]: ...


@runtime_checkable
class TradingSessionReader(Protocol):
    def get_session(self, as_of: date) -> object | None: ...

    def list_sessions(self, *, after: date | None = None) -> Sequence[object]: ...


@runtime_checkable
class TradingSessionRepository(TradingSessionReader, Protocol):
    def put_session(self, session: object) -> object: ...


@runtime_checkable
class MaterializedAggregateReader(Protocol):
    def get_aggregate(self, as_of: date) -> Mapping[str, Any] | None: ...


@runtime_checkable
class MaterializedAggregateRepository(MaterializedAggregateReader, Protocol):
    def revision(self, as_of: date) -> MaterializationRevision: ...

    def compare_and_swap(
        self,
        as_of: date,
        expected: MaterializationRevision,
        payload: Mapping[str, Any],
    ) -> MaterializationRevision: ...


@runtime_checkable
class ProviderCapabilityRepository(Protocol):
    def get_capability(
        self,
        provider: str,
        dataset: str,
        revision: str,
    ) -> Mapping[str, Any] | None: ...

    def put_capability(self, report: Mapping[str, Any]) -> None: ...

    def list_capabilities(
        self,
        *,
        provider: str | None = None,
        dataset: str | None = None,
        status: str | None = None,
    ) -> Sequence[Mapping[str, Any]]: ...


@runtime_checkable
class LimitDetailRepository(Protocol):
    def get_limit_detail(self, as_of: date) -> Mapping[str, Any] | None: ...

    def put_limit_detail(
        self,
        as_of: date,
        manifest: Mapping[str, Any],
        facts: Iterable[object],
    ) -> None: ...


@runtime_checkable
class TimezonePreferenceReader(Protocol):
    def get(
        self,
        scope: str,
        *,
        subject_id: str,
        workspace_id: str,
    ) -> object: ...


@runtime_checkable
class TimezonePreferenceWriter(Protocol):
    def set(
        self,
        scope: str,
        *,
        subject_id: str,
        workspace_id: str,
        timezone_value: str | None,
        actor_id: str,
    ) -> object: ...


@runtime_checkable
class TimezonePreferenceRepository(
    TimezonePreferenceReader,
    TimezonePreferenceWriter,
    Protocol,
):
    pass


__all__ = [
    "CollectionRunRepository",
    "CollectionStatusReader",
    "CollectionTaskRepository",
    "CoreIndexResultRepository",
    "LeaseRepository",
    "LimitDetailRepository",
    "MaterializedAggregateReader",
    "MaterializedAggregateRepository",
    "ProviderCapabilityRepository",
    "SnapshotReader",
    "SnapshotRepository",
    "TimezonePreferenceReader",
    "TimezonePreferenceRepository",
    "TimezonePreferenceWriter",
    "TradingSessionReader",
    "TradingSessionRepository",
]
