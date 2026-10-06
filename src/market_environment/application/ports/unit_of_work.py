"""Atomic persistence boundary for market-environment commands."""

from __future__ import annotations

from typing import Protocol, Self, runtime_checkable

from .repositories import (
    CollectionRunRepository,
    CollectionTaskRepository,
    LeaseRepository,
    LimitDetailRepository,
    MaterializedAggregateRepository,
    ProviderCapabilityRepository,
    SnapshotRepository,
    TimezonePreferenceRepository,
    TradingSessionRepository,
)


@runtime_checkable
class MarketEnvironmentUnitOfWork(Protocol):
    snapshots: SnapshotRepository
    collection_runs: CollectionRunRepository
    collection_tasks: CollectionTaskRepository
    leases: LeaseRepository
    trading_sessions: TradingSessionRepository
    aggregates: MaterializedAggregateRepository
    provider_capabilities: ProviderCapabilityRepository
    limit_details: LimitDetailRepository
    timezone_preferences: TimezonePreferenceRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type, exc, traceback) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


__all__ = ["MarketEnvironmentUnitOfWork"]
