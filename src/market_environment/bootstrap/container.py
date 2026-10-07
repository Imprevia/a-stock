"""Explicit composition container for legacy-backed application seams."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic
from typing import Any

from ..application.ports import (
    CollectionCommandPort,
    CollectionQueryPort,
    MarketEnvironmentQueryPort,
)
from ..infrastructure.collection import CollectionCoordinator
from ..infrastructure.providers.fuyao.market import FuyaoMarketAdapter
from ..infrastructure.collection.refresh import MARKET_TIME_ZONE
from ..infrastructure.materialized_aggregate_factory import build_composer, build_rebuilder
from ..infrastructure.materialization_support import MaterializationSupport
from ..timezone_preferences import TimezonePreferenceStore
from ..infrastructure.compatibility import (
    CoordinatorCollectionCommandAdapter,
    CoordinatorCollectionQueryAdapter,
    RebuilderAggregateCommandAdapter,
    RepositoryMarketEnvironmentQueryAdapter,
    TimezoneCommandAdapter,
    TimezoneQueryAdapter,
)
from ..infrastructure.execution import BoundedTaskExecutor
from ..infrastructure.persistence.postgres.runtime_store import PostgresRuntimeStore
from ..infrastructure.providers.runtime import CollectorProviderRuntime
from .settings import MarketEnvironmentSettings, SettingsConfigurationError


@dataclass(frozen=True, slots=True)
class ReadDependencies:
    market_environment: MarketEnvironmentQueryPort
    collection: CollectionQueryPort
    timezone_preferences: TimezoneQueryAdapter
    clock: Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CommandDependencies:
    collection: CollectionCommandPort
    aggregate: RebuilderAggregateCommandAdapter
    timezone_preferences: TimezoneCommandAdapter


@dataclass(frozen=True, slots=True)
class ContainerAdapters:
    """Injectable composition seams for offline tests and local commands."""

    repository: Any | None = None
    collector: Any | None = None
    clock: Callable[[], datetime] | None = None
    monotonic_clock: Callable[[], float] = monotonic
    task_executor: Any | None = None
    refresh_executor: Any | None = None
    timezone_repository: Any | None = None
    fuyao_adapter: Any | None = None


@dataclass(slots=True)
class ApplicationContainer:
    settings: MarketEnvironmentSettings
    reads: ReadDependencies
    commands: CommandDependencies
    resources: tuple[Any, ...] = field(default_factory=tuple, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        seen: set[int] = set()
        for resource in reversed(self.resources):
            identity = id(resource)
            if identity in seen:
                continue
            seen.add(identity)
            _close_resource(resource)
        self._closed = True


def build_container(
    settings: MarketEnvironmentSettings | None = None,
    *,
    adapters: ContainerAdapters | None = None,
) -> ApplicationContainer:
    """Build the modular-monolith container at an explicit runtime boundary."""

    adapters = adapters or ContainerAdapters()
    settings = settings or MarketEnvironmentSettings.from_environment(
        require_database=adapters.repository is None
    )
    if adapters.repository is None and settings.database is None:
        raise SettingsConfigurationError(
            "normal market-environment runtime requires "
            "MARKET_ENVIRONMENT_DATABASE_URL"
        )
    clock = adapters.clock or (lambda: datetime.now(MARKET_TIME_ZONE))

    repository = adapters.repository or _build_repository(settings)
    collector = adapters.collector or _build_collector(settings)
    refresh_executor = adapters.refresh_executor or ThreadPoolExecutor(
        max_workers=settings.collection_workers,
        thread_name_prefix="market-snapshot",
    )
    materialization_support = MaterializationSupport(
        repository,
        now=clock,
        snapshot_ttl_seconds=30,
    )
    composer = build_composer(
        support=materialization_support,
        repository=repository,
        market_now_callable=materialization_support.market_now,
        snapshot_ttl_seconds=materialization_support.snapshot_ttl_seconds,
    )
    rebuilder = build_rebuilder(
        repository=repository,
        composer=composer,
        market_now_callable=materialization_support.market_now,
    )
    fuyao_adapter = adapters.fuyao_adapter or FuyaoMarketAdapter()
    coordinator = CollectionCoordinator(
        collector,
        repository,
        now=clock,
        rebuild_aggregate=rebuilder.rebuild,
        limits_v1_enabled=settings.limits_v1_enabled,
        fuyao_config=settings.fuyao,
        fuyao_adapter=fuyao_adapter,
    )
    task_executor = adapters.task_executor or BoundedTaskExecutor(
        max_workers=settings.collection_workers,
        thread_name_prefix="market-collection",
    )
    timezone_repository = adapters.timezone_repository or _build_timezone_repository(
        settings,
        repository,
    )

    reads = ReadDependencies(
        market_environment=RepositoryMarketEnvironmentQueryAdapter(repository),
        collection=CoordinatorCollectionQueryAdapter(coordinator),
        timezone_preferences=TimezoneQueryAdapter(timezone_repository),
        clock=clock,
    )
    commands = CommandDependencies(
        collection=CoordinatorCollectionCommandAdapter(coordinator, task_executor),
        aggregate=RebuilderAggregateCommandAdapter(rebuilder),
        timezone_preferences=TimezoneCommandAdapter(timezone_repository),
    )
    return ApplicationContainer(
        settings=settings,
        reads=reads,
        commands=commands,
        resources=(
            repository,
            timezone_repository,
            collector,
            fuyao_adapter,
            refresh_executor,
            task_executor,
        ),
    )


def _build_repository(settings: MarketEnvironmentSettings) -> PostgresRuntimeStore:
    if settings.database is None:
        raise SettingsConfigurationError(
            "normal market-environment runtime requires "
            "MARKET_ENVIRONMENT_DATABASE_URL"
        )
    return PostgresRuntimeStore(settings.database.url)


def _build_collector(settings: MarketEnvironmentSettings) -> CollectorProviderRuntime:
    return CollectorProviderRuntime(
        require_fuyao_for_limits=settings.limits_v1_enabled,
        tdx_fallback_enabled=settings.tdx.fallback_enabled,
        tdx_active_direction_derived_enabled=(
            settings.tdx.derived_active_direction_enabled
        ),
        sector_enrichment_enabled=settings.sector_enrichment_enabled,
    )


def _build_timezone_repository(
    settings: MarketEnvironmentSettings,
    repository: Any,
) -> TimezonePreferenceStore:
    if settings.database is not None:
        return TimezonePreferenceStore(database_url=settings.database.url)
    return TimezonePreferenceStore(repository.path)


def _close_resource(resource: Any) -> None:
    shutdown = getattr(resource, "shutdown", None)
    if callable(shutdown):
        try:
            shutdown(wait=True, cancel_futures=True)
        except TypeError:
            shutdown(wait=True)
        return
    close = getattr(resource, "close", None)
    if callable(close):
        close()
        return
    engine = getattr(resource, "engine", None)
    dispose = getattr(engine, "dispose", None)
    if callable(dispose):
        dispose()


__all__ = [
    "ApplicationContainer",
    "CommandDependencies",
    "ContainerAdapters",
    "ReadDependencies",
    "build_container",
]
