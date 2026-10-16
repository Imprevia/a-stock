"""Explicit composition container for legacy-backed application seams."""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from time import monotonic
from typing import Any

from src.trading_system.data.provider_transport import (
    HostPolicy,
    RequestsTransportEngine,
    TransportEngineRegistry,
    TransportPolicyGateway,
    get_process_transport_gateway,
)
from src.trading_system.data.provider_scrapling import ScraplingStaticHttpEngine

from ..application.collection import DatasetCollectorRegistry
from ..application.commands import ThsOperationGates
from ..application.ports import (
    CollectionCommandPort,
    CollectionQueryPort,
    MarketEnvironmentQueryPort,
)
from ..application.queries import V2MarketDataQueries
from ..domain.models import DATASET_IDS
from ..infrastructure.collection import (
    AcquisitionPlanCollector,
    CollectionCoordinator,
    CoreCommitRequestFactory,
    CoreRetainedIndexReader,
    LimitsCommitRequestFactory,
    LimitsPreviousSessionCommitPreparer,
    LimitsPreviousSessionEvidenceReader,
    ProviderLimitHistoryPreparer,
    ThsIndustryRankingCollector,
    ThsSectorBreadthCollector,
    ThsSectorTurnoverCollector,
)
from ..infrastructure.providers.fuyao.market import (
    FuyaoMarketAdapter,
    FuyaoMarketClient,
)
from ..infrastructure.providers.fuyao.ths_dump import (
    FuyaoThsDumpReader,
    merge_member_facts,
)
from ..infrastructure.providers.fuyao.ths_sector import (
    FuyaoThsCapabilityPolicy,
    FuyaoThsSectorAdapter,
)
from ..infrastructure.collection.refresh import MARKET_TIME_ZONE, effective_market_date
from ..infrastructure.materialized_aggregate_factory import build_composer, build_rebuilder
from ..infrastructure.materialization_support import MaterializationSupport
from ..timezone_preferences import TimezonePreferenceStore
from ..infrastructure.compatibility import (
    CoordinatorCollectionCommandAdapter,
    CoordinatorCollectionQueryAdapter,
    RebuilderAggregateCommandAdapter,
    RepositoryMarketEnvironmentQueryAdapter,
    ThsSectorCommandAdapter,
    ThsSectorQueryAdapter,
    TimezoneCommandAdapter,
    TimezoneQueryAdapter,
)
from ..infrastructure.execution import BoundedTaskExecutor
from ..infrastructure.persistence.postgres.runtime_store import PostgresRuntimeStore
from ..infrastructure.persistence.postgres import PostgresV2MarketDataReadService
from ..infrastructure.v2_market_data_compat import CompatibilityV2MarketDataReadAdapter
from ..infrastructure.providers import (
    ActiveDirectionCollector,
    BreadthCollector,
    CoreCollector,
    FuyaoCollectionPolicy,
    LimitsCollector,
)
from ..infrastructure.providers.runtime import CollectorProviderRuntime
from .registries import (
    RuntimeRegistries,
    build_committer_registry,
    build_detail_projector_registry,
    build_runtime_acquisition_registries,
    build_unit_of_work_factory,
)
from .settings import MarketEnvironmentSettings, SettingsConfigurationError


@dataclass(frozen=True, slots=True)
class ReadDependencies:
    market_environment: MarketEnvironmentQueryPort
    v2_market_environment: Any
    collection: CollectionQueryPort
    timezone_preferences: TimezoneQueryAdapter
    ths_sectors: Any
    clock: Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CommandDependencies:
    collection: CollectionCommandPort
    aggregate: RebuilderAggregateCommandAdapter
    timezone_preferences: TimezoneCommandAdapter
    ths_sectors: Any


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
    collector_registry: Any | None = None
    acquisition_plan_registry: Any | None = None
    source_adapter_registry: Any | None = None
    committer_registry: Any | None = None
    detail_projector_registry: Any | None = None
    transport_engine_registry: TransportEngineRegistry | None = None
    transport_policy_gateway: TransportPolicyGateway | None = None
    unit_of_work_factory: Callable[[], Any] | None = None
    limit_history_preparer: Any | None = None
    commit_request_factories: dict[str, Callable[..., Any]] | None = None
    commit_preparers: dict[str, Any] | None = None
    typed_cutover_datasets: tuple[str, ...] | None = None
    ths_queries: Any | None = None
    ths_commands: Any | None = None
    v2_queries: Any | None = None


@dataclass(slots=True)
class ApplicationContainer:
    settings: MarketEnvironmentSettings
    reads: ReadDependencies
    commands: CommandDependencies
    registries: RuntimeRegistries
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
    transport_gateway, transport_engines = _build_transport(
        settings,
        adapters.transport_policy_gateway,
        adapters.transport_engine_registry,
    )
    collector = adapters.collector or _build_collector(settings, transport_gateway)
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
    fuyao_adapter = adapters.fuyao_adapter or FuyaoMarketAdapter(
        FuyaoMarketClient(transport_gateway=transport_gateway)
    )
    fuyao_policy = FuyaoCollectionPolicy(settings.fuyao, repository)
    unit_of_work_factory = (
        adapters.unit_of_work_factory or build_unit_of_work_factory(repository)
    )
    ths_capability_policy = _build_ths_capability_policy(repository)

    def ths_adapter_factory(
        capability_revision: str,
        history_revision: str | None,
        membership_revision: str | None = None,
    ) -> FuyaoThsSectorAdapter:
        return FuyaoThsSectorAdapter(
            FuyaoMarketClient(transport_gateway=transport_gateway),
            capability_revision=capability_revision,
            history_revision=history_revision or capability_revision,
            membership_revision=membership_revision or capability_revision,
            now=lambda: _market_now(clock).astimezone(timezone.utc),
        )

    def load_ths_catalog_bundle(as_of: date) -> Any:
        revision = (
            os.getenv("MARKET_ENVIRONMENT_FUYAO_THS_CATALOG_REVISION") or ""
        ).strip()
        if not revision:
            raise RuntimeError("Fuyao THS catalog capability revision is not configured")
        report = ths_capability_policy.require("industry-ranking", revision)
        adapter = ths_adapter_factory(revision, revision)
        before = int(adapter.client.request_count)
        bundle = adapter.fetch_catalog_snapshot(as_of)
        requests_used = int(adapter.client.request_count) - before
        authorized_budget = int(report.rate_limit_evidence["requestBudget"])
        if requests_used > authorized_budget:
            raise RuntimeError("Fuyao THS catalog request budget was exhausted")
        return bundle

    def current_completed_session() -> date | None:
        current = _market_now(clock).date()
        return (
            current
            if _is_settled(
                current,
                clock=clock,
                settlement_boundary=settings.settlement_time,
            )
            else None
        )

    ths_collectors = (
        ThsIndustryRankingCollector(
            load_ths_catalog_bundle,
            current_completed_session,
        ),
        ThsSectorTurnoverCollector(
            unit_of_work_factory,
            current_completed_session,
        ),
        ThsSectorBreadthCollector(
            unit_of_work_factory,
            current_completed_session,
        ),
    )
    limits_previous_sessions = LimitsPreviousSessionEvidenceReader(repository)
    uses_default_collectors = adapters.collector_registry is None
    typed_cutover_datasets = adapters.typed_cutover_datasets
    if typed_cutover_datasets is None:
        typed_cutover_datasets = DATASET_IDS if uses_default_collectors else ()
    source_adapters, acquisition_plans = _build_acquisition_registries(
        adapters,
        provider=collector,
        fuyao_adapter=fuyao_adapter,
        fuyao_policy=fuyao_policy,
        tdx_is_enabled=lambda: settings.tdx.fallback_enabled,
        tdx_active_direction_is_enabled=(
            lambda: settings.tdx.derived_active_direction_enabled
        ),
        sector_enrichment_enabled=lambda: settings.sector_enrichment_enabled,
        limits_v1_enabled=lambda: settings.limits_v1_enabled,
        limits_previous_session=limits_previous_sessions.previous_as_of,
        retained_core_indices=CoreRetainedIndexReader(repository),
        market_today=lambda: _market_now(clock).date(),
        is_settled=lambda as_of: _is_settled(
            as_of,
            clock=clock,
            settlement_boundary=settings.settlement_time,
        ),
        crawl_fallback_is_enabled=settings.crawl_fallback.is_host_enabled,
    )
    collector_registry = adapters.collector_registry
    if collector_registry is None:
        collector_registry = _build_runtime_collector_registry(
            collector,
            repository,
            acquisition_plans,
            typed_cutover_datasets=typed_cutover_datasets,
            clock=clock,
            settlement_boundary=settings.settlement_time,
            limits_v1_enabled=settings.limits_v1_enabled,
            fuyao_adapter=fuyao_adapter,
            fuyao_policy=fuyao_policy,
            ths_collectors=ths_collectors,
        )
    committer_registry = adapters.committer_registry or build_committer_registry(
        unit_of_work_factory
    )
    detail_projectors = (
        adapters.detail_projector_registry
        or build_detail_projector_registry(
            repository,
            limits_enabled=settings.limits_v1_enabled,
        )
    )
    registries = RuntimeRegistries(
        collectors=collector_registry,
        acquisition_plans=acquisition_plans,
        source_adapters=source_adapters,
        committers=committer_registry,
        detail_projectors=detail_projectors,
        transport_engines=transport_engines,
        transport_policy_gateway=transport_gateway,
    )
    limits_collector = (
        collector_registry.get("limits")
        if uses_default_collectors and "limits" not in typed_cutover_datasets
        else None
    )
    limit_history_preparer = adapters.limit_history_preparer
    if limit_history_preparer is None and "limits" in typed_cutover_datasets:
        limit_history_preparer = ProviderLimitHistoryPreparer(
            collector,
            repository,
            now=lambda: _market_now(clock),
        )
    coordinator = CollectionCoordinator(
        collector,
        repository,
        now=clock,
        rebuild_aggregate=rebuilder.rebuild,
        limits_v1_enabled=settings.limits_v1_enabled,
        fuyao_config=settings.fuyao,
        fuyao_adapter=fuyao_adapter,
        fuyao_policy=fuyao_policy,
        collector_registry=collector_registry,
        committer_registry=committer_registry,
        commit_request_factories={
            "core": CoreCommitRequestFactory(lambda: _market_now(clock)),
            "limits": LimitsCommitRequestFactory(limits_previous_sessions),
            **dict(adapters.commit_request_factories or {}),
        },
        commit_preparers={
            "limits": LimitsPreviousSessionCommitPreparer(
                repository,
                acquisition_plans.get("limits"),
                limits_previous_sessions,
                enabled=lambda: settings.limits_v1_enabled,
                now=lambda: _market_now(clock).astimezone(timezone.utc),
            ),
            **dict(adapters.commit_preparers or {}),
        },
        detail_projector_registry=detail_projectors,
        limits_collector=limits_collector,
        limit_history_preparer=limit_history_preparer,
        typed_cutover_datasets=typed_cutover_datasets,
    )
    task_executor = adapters.task_executor or BoundedTaskExecutor(
        max_workers=settings.collection_workers,
        thread_name_prefix="market-collection",
    )
    timezone_repository = adapters.timezone_repository or _build_timezone_repository(
        settings,
        repository,
    )
    ths_gates = ThsOperationGates(
        manual_write_enabled=lambda: settings.manual_refresh_enabled,
        authorized=lambda: _environment_enabled(
            "MARKET_ENVIRONMENT_THS_WRITES_AUTHORIZED"
        ),
        after_market=lambda as_of: _is_settled(
            as_of,
            clock=clock,
            settlement_boundary=settings.settlement_time,
        ),
    )
    ths_queries = adapters.ths_queries or ThsSectorQueryAdapter(unit_of_work_factory)
    ths_commands = adapters.ths_commands or ThsSectorCommandAdapter(
        unit_of_work_factory=unit_of_work_factory,
        executor=task_executor,
        adapter_factory=ths_adapter_factory,
        dump_reader=FuyaoThsDumpReader(),
        fact_merger=merge_member_facts,
        capability_policy=ths_capability_policy,
        gates=ths_gates,
        default_revisions={
            "industry-ranking": os.getenv(
                "MARKET_ENVIRONMENT_FUYAO_THS_CATALOG_REVISION"
            ),
            "sector-membership": os.getenv(
                "MARKET_ENVIRONMENT_FUYAO_THS_MEMBERSHIP_REVISION"
            ),
            "sector-turnover-history": os.getenv(
                "MARKET_ENVIRONMENT_FUYAO_THS_HISTORY_REVISION"
            ),
        },
        clock=lambda: _market_now(clock).astimezone(timezone.utc),
        effective_date=lambda: effective_market_date(_market_now(clock)),
    )

    v2_queries = adapters.v2_queries
    if v2_queries is None:
        engine = getattr(repository, "engine", None)
        connect = getattr(engine, "connect", None)
        v2_reads = (
            PostgresV2MarketDataReadService(connect)
            if callable(connect)
            else CompatibilityV2MarketDataReadAdapter(repository)
        )
        v2_queries = V2MarketDataQueries(v2_reads)
    reads = ReadDependencies(
        market_environment=RepositoryMarketEnvironmentQueryAdapter(repository),
        v2_market_environment=v2_queries,
        collection=CoordinatorCollectionQueryAdapter(coordinator),
        timezone_preferences=TimezoneQueryAdapter(timezone_repository),
        ths_sectors=ths_queries,
        clock=clock,
    )
    commands = CommandDependencies(
        collection=CoordinatorCollectionCommandAdapter(coordinator, task_executor),
        aggregate=RebuilderAggregateCommandAdapter(rebuilder),
        timezone_preferences=TimezoneCommandAdapter(timezone_repository),
        ths_sectors=ths_commands,
    )
    return ApplicationContainer(
        settings=settings,
        reads=reads,
        commands=commands,
        registries=registries,
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


def _build_collector(
    settings: MarketEnvironmentSettings,
    transport_gateway: TransportPolicyGateway,
) -> CollectorProviderRuntime:
    return CollectorProviderRuntime(
        require_fuyao_for_limits=settings.limits_v1_enabled,
        tdx_fallback_enabled=settings.tdx.fallback_enabled,
        tdx_active_direction_derived_enabled=(
            settings.tdx.derived_active_direction_enabled
        ),
        sector_enrichment_enabled=settings.sector_enrichment_enabled,
        transport_gateway=transport_gateway,
    )


def _build_transport(
    settings: MarketEnvironmentSettings,
    gateway: TransportPolicyGateway | None,
    engines: TransportEngineRegistry | None,
) -> tuple[TransportPolicyGateway, TransportEngineRegistry]:
    if gateway is not None:
        gateway_engines = gateway.engine_registry
        if engines is not None and engines is not gateway_engines:
            raise ValueError(
                "transport engine registry must be owned by the injected policy gateway"
            )
        return gateway, gateway_engines
    if engines is not None:
        gateway = TransportPolicyGateway(engines)
        return gateway, engines
    configured_engines: tuple[Any, ...] = (RequestsTransportEngine(),)
    if settings.scrapling.enabled:
        configured_engines += (ScraplingStaticHttpEngine(settings.scrapling),)
    desired_registry = TransportEngineRegistry(configured_engines)
    try:
        gateway = get_process_transport_gateway(
            engine_registry=desired_registry,
            default_policy=HostPolicy(
                timeout=8.0,
                max_retries=2,
                retry_backoff=0.5,
                cache_ttl_seconds=10.0,
            ),
            policies={
                "www.tdx.com.cn": HostPolicy(
                    minimum_interval=1.0,
                    jitter=(0.05, 0.25),
                    timeout=(10.0, 30.0),
                    max_retries=2,
                    retry_backoff=1.0,
                    request_budget=20,
                    cache_ttl_seconds=0.0,
                ),
                "data.eastmoney.com": HostPolicy(
                    minimum_interval=1.0,
                    jitter=(0.05, 0.25),
                    timeout=(8.0, 15.0),
                    max_retries=2,
                    retry_backoff=0.8,
                    request_budget=20,
                    cache_ttl_seconds=10.0,
                ),
                "fuyao.aicubes.cn": HostPolicy(
                    minimum_interval=0.5,
                    jitter=(0.0, 0.0),
                    timeout=8.0,
                    max_retries=2,
                    retry_backoff=0.2,
                    request_budget=120,
                    cache_ttl_seconds=0.0,
                ),
            },
        )
    except RuntimeError:
        gateway = get_process_transport_gateway()
        if gateway.engine_registry.names != desired_registry.names:
            raise SettingsConfigurationError(
                "process transport engines do not match the configured Scrapling profile"
            ) from None
        if settings.scrapling.enabled:
            active = gateway.engine_registry.resolve("scrapling")
            if getattr(active, "config", None) != settings.scrapling:
                raise SettingsConfigurationError(
                    "process Scrapling allowlist does not match runtime settings"
                ) from None
    return gateway, gateway.engine_registry


def _build_acquisition_registries(
    adapters: ContainerAdapters,
    *,
    provider: Any,
    fuyao_adapter: Any,
    fuyao_policy: FuyaoCollectionPolicy,
    tdx_is_enabled: Callable[[], bool],
    tdx_active_direction_is_enabled: Callable[[], bool],
    sector_enrichment_enabled: Callable[[], bool],
    limits_v1_enabled: Callable[[], bool],
    limits_previous_session: Callable[[date], date | None],
    retained_core_indices: Callable[[Any], Any],
    market_today: Callable[[], date],
    is_settled: Callable[[date], bool],
    crawl_fallback_is_enabled: Callable[[str], bool] = lambda _host: False,
):
    plans = adapters.acquisition_plan_registry
    sources = adapters.source_adapter_registry
    if (plans is None) != (sources is None):
        raise ValueError(
            "acquisition plan and source adapter registries must be injected together"
        )
    if plans is None:
        return build_runtime_acquisition_registries(
            provider=provider,
            fuyao_adapter=fuyao_adapter,
            fuyao_is_enabled=fuyao_policy.is_enabled,
            fuyao_gate_warning=fuyao_policy.gate_warning,
            fuyao_shadow_enabled=fuyao_policy.shadow_enabled,
            fuyao_revision=fuyao_policy.revision,
            tdx_is_enabled=tdx_is_enabled,
            tdx_active_direction_is_enabled=tdx_active_direction_is_enabled,
            sector_enrichment_enabled=sector_enrichment_enabled,
            limits_v1_enabled=limits_v1_enabled,
            limits_previous_session=limits_previous_session,
            retained_core_indices=retained_core_indices,
            market_today=market_today,
            is_settled=is_settled,
            crawl_fallback_is_enabled=crawl_fallback_is_enabled,
        )
    return sources, plans


def _build_runtime_collector_registry(
    provider: Any,
    repository: Any,
    acquisition_plans: Any,
    *,
    typed_cutover_datasets: tuple[str, ...],
    clock: Callable[[], datetime],
    settlement_boundary: Any,
    limits_v1_enabled: bool,
    fuyao_adapter: Any,
    fuyao_policy: FuyaoCollectionPolicy,
    ths_collectors: tuple[Any, Any, Any],
    lease_seconds: float = 600.0,
) -> DatasetCollectorRegistry:
    typed = frozenset(typed_cutover_datasets)

    def market_now() -> datetime:
        return _market_now(clock)

    def is_settled(as_of: date) -> bool:
        current = market_now()
        return as_of < current.date() or (
            as_of == current.date()
            and current.time().replace(tzinfo=None) >= settlement_boundary
        )

    collectors = [
        AcquisitionPlanCollector("core", acquisition_plans)
        if "core" in typed
        else (
            CoreCollector(
                provider,
                repository,
                market_now=market_now,
                is_settled=is_settled,
                fuyao_adapter=fuyao_adapter,
                fuyao_is_enabled=fuyao_policy.is_enabled,
                fuyao_shadow_enabled=fuyao_policy.shadow_enabled,
                fuyao_revision=fuyao_policy.revision,
                lease_seconds=lease_seconds,
            )
        ),
        AcquisitionPlanCollector("breadth", acquisition_plans)
        if "breadth" in typed
        else (
            BreadthCollector(
                provider,
                repository,
                market_now=market_now,
                is_settled=is_settled,
                fuyao_adapter=fuyao_adapter,
                fuyao_is_enabled=fuyao_policy.is_enabled,
                fuyao_shadow_enabled=fuyao_policy.shadow_enabled,
                fuyao_revision=fuyao_policy.revision,
            )
        ),
        AcquisitionPlanCollector("limits", acquisition_plans)
        if "limits" in typed
        else (
            LimitsCollector(
                provider,
                repository,
                market_now=market_now,
                is_settled=is_settled,
                lease_seconds=lease_seconds,
                limits_v1_enabled_override=limits_v1_enabled,
                fuyao_is_enabled=fuyao_policy.is_enabled,
                fuyao_shadow_enabled=fuyao_policy.shadow_enabled,
                fuyao_revision=fuyao_policy.revision,
            )
        ),
        *ths_collectors,
        AcquisitionPlanCollector("activeDirection", acquisition_plans)
        if "activeDirection" in typed
        else (
            ActiveDirectionCollector(
                provider,
                repository,
                market_now=market_now,
                is_settled=is_settled,
            )
        ),
    ]
    return DatasetCollectorRegistry.complete(collectors)


def _market_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None:
        return value.replace(tzinfo=MARKET_TIME_ZONE)
    return value.astimezone(MARKET_TIME_ZONE)


def _is_settled(
    as_of: date,
    *,
    clock: Callable[[], datetime],
    settlement_boundary: Any,
) -> bool:
    current = _market_now(clock)
    return as_of < current.date() or (
        as_of == current.date()
        and current.time().replace(tzinfo=None) >= settlement_boundary
    )


def _environment_enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _build_ths_capability_policy(repository: Any) -> FuyaoThsCapabilityPolicy:
    return FuyaoThsCapabilityPolicy(
        repository,
        enabled={
            "industry-ranking": _environment_enabled(
                "MARKET_ENVIRONMENT_FUYAO_THS_CATALOG_ENABLED"
            ),
            "sector-membership": _environment_enabled(
                "MARKET_ENVIRONMENT_FUYAO_THS_MEMBERSHIP_ENABLED"
            ),
            "sector-turnover-history": _environment_enabled(
                "MARKET_ENVIRONMENT_FUYAO_THS_HISTORY_ENABLED"
            ),
            "sector-member-daily-dump": _environment_enabled(
                "MARKET_ENVIRONMENT_FUYAO_THS_DAILY_DUMP_ENABLED"
            ),
            "sector-member-incremental-dump": _environment_enabled(
                "MARKET_ENVIRONMENT_FUYAO_THS_INCREMENTAL_DUMP_ENABLED"
            ),
            "sector-member-adjustment-dump": _environment_enabled(
                "MARKET_ENVIRONMENT_FUYAO_THS_ADJUSTMENT_DUMP_ENABLED"
            ),
        },
    )


def _build_timezone_repository(
    settings: MarketEnvironmentSettings,
    repository: Any,
) -> TimezonePreferenceStore:
    if settings.database is not None:
        return TimezonePreferenceStore(
            database_url=settings.database.url,
            initialize_schema=False,
        )
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
    "RuntimeRegistries",
    "build_container",
]
