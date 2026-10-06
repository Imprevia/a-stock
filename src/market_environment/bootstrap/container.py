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
from ..collection import CollectionCoordinator
from ..fuyao_market import FuyaoMarketAdapter
from ..providers import MarketDataProvider
from ..refresh import MARKET_TIME_ZONE
from ..service import MarketEnvironmentService
from ..snapshot_store import SnapshotStore
from ..timezone_preferences import TimezonePreferenceStore
from ..infrastructure.compatibility import (
    LegacyAggregateCommandAdapter,
    LegacyCollectionCommandAdapter,
    LegacyCollectionQueryAdapter,
    LegacyMarketEnvironmentQueryAdapter,
    LegacyTimezoneCommandAdapter,
    LegacyTimezoneQueryAdapter,
)
from ..infrastructure.execution import BoundedTaskExecutor
from .settings import MarketEnvironmentSettings, SettingsConfigurationError


@dataclass(frozen=True, slots=True)
class ReadDependencies:
    market_environment: MarketEnvironmentQueryPort
    collection: CollectionQueryPort
    timezone_preferences: LegacyTimezoneQueryAdapter
    clock: Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CommandDependencies:
    collection: CollectionCommandPort
    aggregate: LegacyAggregateCommandAdapter
    timezone_preferences: LegacyTimezoneCommandAdapter


@dataclass(frozen=True, slots=True)
class LegacyContainerAdapters:
    """Injectable seams used while concrete application ports are introduced."""

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
    adapters: LegacyContainerAdapters | None = None,
) -> ApplicationContainer:
    """Build the modular-monolith container at an explicit runtime boundary."""

    adapters = adapters or LegacyContainerAdapters()
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
    service = MarketEnvironmentService(
        provider=collector,
        clock=adapters.monotonic_clock,
        snapshot_store=repository,
        persistent_cache=settings.persistent_cache_enabled,
        local_reads_only=settings.persistent_cache_enabled,
        now=clock,
        refresh_executor=refresh_executor,
    )
    fuyao_adapter = adapters.fuyao_adapter or FuyaoMarketAdapter()
    coordinator = CollectionCoordinator(
        collector,
        repository,
        now=clock,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=settings.limits_v1_enabled,
        fuyao_config=settings.fuyao,
        fuyao_adapter=fuyao_adapter,
        analysis_service=service,
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
        market_environment=LegacyMarketEnvironmentQueryAdapter(service),
        collection=LegacyCollectionQueryAdapter(coordinator),
        timezone_preferences=LegacyTimezoneQueryAdapter(timezone_repository),
        clock=clock,
    )
    commands = CommandDependencies(
        collection=LegacyCollectionCommandAdapter(coordinator, task_executor),
        aggregate=LegacyAggregateCommandAdapter(service),
        timezone_preferences=LegacyTimezoneCommandAdapter(timezone_repository),
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
            service,
            task_executor,
        ),
    )


def _build_repository(settings: MarketEnvironmentSettings) -> SnapshotStore:
    if settings.database is None:
        raise SettingsConfigurationError(
            "normal market-environment runtime requires "
            "MARKET_ENVIRONMENT_DATABASE_URL"
        )
    return SnapshotStore(database_url=settings.database.url)


def _build_collector(settings: MarketEnvironmentSettings) -> MarketDataProvider:
    return MarketDataProvider(
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
    "LegacyContainerAdapters",
    "ReadDependencies",
    "build_container",
]
