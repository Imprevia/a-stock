"""Atomic persistence boundary for market-environment commands."""

from __future__ import annotations

from typing import Protocol, Self, runtime_checkable

from .repositories import (
    CollectionIdempotencyRepository,
    CollectionRunRepository,
    CollectionTaskRepository,
    CoreIndexResultRepository,
    LeaseRepository,
    LimitDetailRepository,
    MaterializedAggregateRepository,
    ProviderCapabilityRepository,
    SectorContinuityRepository,
    SnapshotRepository,
    ThsSectorRepository,
    TimezonePreferenceRepository,
    TradingSessionRepository,
)


@runtime_checkable
class MarketEnvironmentUnitOfWork(Protocol):
    snapshots: SnapshotRepository
    collection_runs: CollectionRunRepository
    collection_tasks: CollectionTaskRepository
    collection_idempotency: CollectionIdempotencyRepository
    core_index_results: CoreIndexResultRepository
    leases: LeaseRepository
    trading_sessions: TradingSessionRepository
    aggregates: MaterializedAggregateRepository
    provider_capabilities: ProviderCapabilityRepository
    limit_details: LimitDetailRepository
    timezone_preferences: TimezonePreferenceRepository
    sector_continuity: SectorContinuityRepository
    # Explicit aliases keep the six logical evidence families discoverable
    # while the adapter remains one transaction-scoped repository.
    sector_taxonomy: SectorContinuityRepository
    sector_memberships: SectorContinuityRepository
    sector_security_facts: SectorContinuityRepository
    sector_benchmarks: SectorContinuityRepository
    sector_industry_aggregates: SectorContinuityRepository
    sector_results: SectorContinuityRepository
    sector_backfill: SectorContinuityRepository
    ths_sectors: ThsSectorRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type, exc, traceback) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


__all__ = ["MarketEnvironmentUnitOfWork"]
