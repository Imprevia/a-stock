"""Complete registry construction for the market-environment composition root."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from typing import Any

from src.trading_system.data.provider_transport import (
    TransportEngineRegistry,
    TransportPolicyGateway,
)

from ..application.collection import (
    AcquisitionPlanRegistry,
    DatasetCollectorRegistry,
    DatasetCommitterRegistry,
    DatasetDetailProjectorRegistry,
    SourceAdapterRegistry,
)
from ..application.ports import AcquisitionPlanStep, SourceCapability, SourceRequest
from ..domain.models import AcquisitionFailure, AcquisitionFailureCategory, DATASET_IDS
from ..infrastructure.collection import (
    CoreDatasetCommitter,
    LimitsDatasetCommitter,
    StandardSnapshotCommitter,
)
from ..infrastructure.persistence.postgres import (
    MarketEnvironmentUnitOfWork,
    PostgresCollectionRunRepository,
    PostgresCollectionTaskRepository,
    PostgresConnectionFactory,
    PostgresCoreIndexResultRepository,
    PostgresLeaseRepository,
    PostgresLimitDetailRepository,
    PostgresMaterializedAggregateRepository,
    PostgresProviderCapabilityRepository,
    PostgresSnapshotRepository,
    PostgresTimezonePreferenceRepository,
    PostgresTradingSessionRepository,
)
from ..infrastructure.providers.acquisition import (
    CompatibilitySourceAdapter,
    DeterministicAcquisitionPlan,
)
from ..infrastructure.providers.active_direction_acquisition import (
    ActiveDirectionAcquisitionPlan,
    EastmoneyActiveDirectionDelayedAdapter,
    EastmoneyActiveDirectionPrimaryAdapter,
    TDXDerivedActiveDirectionAdapter,
)
from ..infrastructure.providers.breadth_acquisition import (
    BreadthAcquisitionPlan,
    EastmoneyBreadthSourceAdapter,
    FuyaoBreadthSourceAdapter,
    TDXBreadthSourceAdapter,
)
from ..infrastructure.providers.core_acquisition import (
    BaiduCoreHistorySourceAdapter,
    CoreAcquisitionPlan,
    EastmoneyCoreHistorySourceAdapter,
    FuyaoCoreHistorySourceAdapter,
    MootdxCoreHistorySourceAdapter,
    SinaCoreHistorySourceAdapter,
    TencentCoreHistorySourceAdapter,
    TencentCoreQuoteSourceAdapter,
)
from ..infrastructure.providers.core_contracts import INDEX_SPECS
from ..infrastructure.providers.limits_acquisition import (
    EastmoneyLimitsSourceAdapter,
    FuyaoLimitsSourceAdapter,
    LegacyLimitsSummarySourceAdapter,
    LimitsAcquisitionPlan,
)
from ..infrastructure.providers.sectors_acquisition import (
    EastmoneySectorDelayedAdapter,
    EastmoneySectorEnrichmentAdapter,
    EastmoneySectorPrimaryAdapter,
    FuyaoSectorSourceAdapter,
    SectorsAcquisitionPlan,
)


@dataclass(frozen=True, slots=True)
class RuntimeRegistries:
    """All fail-closed registries owned by one application composition root."""

    collectors: DatasetCollectorRegistry
    acquisition_plans: AcquisitionPlanRegistry
    source_adapters: SourceAdapterRegistry
    committers: DatasetCommitterRegistry
    detail_projectors: DatasetDetailProjectorRegistry
    transport_engines: TransportEngineRegistry
    transport_policy_gateway: TransportPolicyGateway


class _DeferredCompatibilitySource(RuntimeError):
    pass


def build_deferred_acquisition_registries(
) -> tuple[SourceAdapterRegistry, AcquisitionPlanRegistry]:
    """Register migration placeholders that fail before any provider I/O.

    Dataset-specific source adapters replace these entries during the staged
    5.x cutovers. Until then, the legacy collector registry remains the active
    runtime path and an accidental plan invocation fails as configuration.
    """

    adapters = tuple(_deferred_source_adapter(dataset_id) for dataset_id in DATASET_IDS)
    source_adapters = SourceAdapterRegistry(adapters)
    plans = AcquisitionPlanRegistry.complete(
        (
            DeterministicAcquisitionPlan(
                dataset_id=dataset_id,
                plan_id=f"{dataset_id}-compatibility-deferred-v1",
                steps=(
                    AcquisitionPlanStep(
                        adapter_id=_compatibility_source_id(dataset_id),
                        capability_revision="compatibility-deferred-v1",
                    ),
                ),
                adapters=source_adapters,
            )
            for dataset_id in DATASET_IDS
        ),
        source_adapters=source_adapters,
    )
    return source_adapters, plans


def build_runtime_acquisition_registries(
    *,
    provider: Any,
    fuyao_adapter: Any,
    fuyao_is_enabled: Callable[[str], bool],
    fuyao_gate_warning: Callable[[str], str],
    fuyao_shadow_enabled: Callable[[str], bool],
    fuyao_revision: Callable[[str], str],
    tdx_is_enabled: Callable[[], bool],
    tdx_active_direction_is_enabled: Callable[[], bool],
    sector_enrichment_enabled: Callable[[], bool],
    limits_v1_enabled: Callable[[], bool],
    limits_previous_session: Callable[[date], date | None],
    retained_core_indices: Callable[[Any], Any],
    market_today: Callable[[], date],
    is_settled: Callable[[date], bool],
) -> tuple[SourceAdapterRegistry, AcquisitionPlanRegistry]:
    """Build staged runtime registries for each migrated dataset."""

    core_sources = (
        TencentCoreQuoteSourceAdapter(provider),
        FuyaoCoreHistorySourceAdapter(fuyao_adapter),
        MootdxCoreHistorySourceAdapter(provider),
        BaiduCoreHistorySourceAdapter(provider),
        SinaCoreHistorySourceAdapter(provider),
        TencentCoreHistorySourceAdapter(provider),
        EastmoneyCoreHistorySourceAdapter(provider),
    )
    breadth_sources = (
        FuyaoBreadthSourceAdapter(
            fuyao_adapter,
            revision=fuyao_revision("breadth"),
        ),
        TDXBreadthSourceAdapter(provider),
        EastmoneyBreadthSourceAdapter(provider),
    )
    active_direction_sources = (
        EastmoneyActiveDirectionPrimaryAdapter(provider),
        EastmoneyActiveDirectionDelayedAdapter(provider),
        TDXDerivedActiveDirectionAdapter(provider),
    )
    sector_sources = (
        EastmoneySectorPrimaryAdapter(provider),
        EastmoneySectorDelayedAdapter(provider),
        FuyaoSectorSourceAdapter(
            fuyao_adapter,
            revision=fuyao_revision("sectors"),
        ),
        EastmoneySectorEnrichmentAdapter(
            provider,
            enabled=sector_enrichment_enabled,
        ),
    )
    limits_sources = (
        FuyaoLimitsSourceAdapter(provider),
        EastmoneyLimitsSourceAdapter(provider),
        LegacyLimitsSummarySourceAdapter(provider),
    )
    sources = []
    for dataset_id in DATASET_IDS:
        if dataset_id == "core":
            sources.extend(core_sources)
        elif dataset_id == "breadth":
            sources.extend(breadth_sources)
        elif dataset_id == "limits":
            sources.extend(limits_sources)
        elif dataset_id == "sectors":
            sources.extend(sector_sources)
        elif dataset_id == "activeDirection":
            sources.extend(active_direction_sources)
        else:
            sources.append(_deferred_source_adapter(dataset_id))
    source_adapters = SourceAdapterRegistry(sources)
    core_plan = CoreAcquisitionPlan(
        source_adapters,
        index_specs=tuple(INDEX_SPECS),
        fuyao_is_enabled=fuyao_is_enabled,
        fuyao_shadow_enabled=fuyao_shadow_enabled,
        fuyao_revision=fuyao_revision,
        retained_indices=retained_core_indices,
        market_today=market_today,
        is_settled=is_settled,
    )
    breadth_plan = BreadthAcquisitionPlan(
        source_adapters,
        fuyao_is_enabled=fuyao_is_enabled,
        fuyao_shadow_enabled=fuyao_shadow_enabled,
        fuyao_revision=fuyao_revision,
        tdx_is_enabled=tdx_is_enabled,
        market_today=market_today,
        is_settled=is_settled,
    )
    limits_plan = LimitsAcquisitionPlan(
        source_adapters,
        limits_v1_enabled=limits_v1_enabled,
        fuyao_is_enabled=fuyao_is_enabled,
        fuyao_shadow_enabled=fuyao_shadow_enabled,
        fuyao_revision=fuyao_revision,
        market_today=market_today,
        is_settled=is_settled,
        previous_session=limits_previous_session,
    )
    sectors_plan = SectorsAcquisitionPlan(
        source_adapters,
        fuyao_is_enabled=fuyao_is_enabled,
        fuyao_gate_warning=fuyao_gate_warning,
        fuyao_shadow_enabled=fuyao_shadow_enabled,
        fuyao_revision=fuyao_revision,
        market_today=market_today,
        is_settled=is_settled,
    )
    active_direction_plan = ActiveDirectionAcquisitionPlan(
        source_adapters,
        tdx_derived_is_enabled=tdx_active_direction_is_enabled,
        market_today=market_today,
        is_settled=is_settled,
    )
    plans = AcquisitionPlanRegistry.complete(
        (
            core_plan
            if dataset_id == "core"
            else (
                breadth_plan
                if dataset_id == "breadth"
                else (
                    limits_plan
                    if dataset_id == "limits"
                    else (
                        sectors_plan
                        if dataset_id == "sectors"
                        else (
                            active_direction_plan
                            if dataset_id == "activeDirection"
                            else _deferred_acquisition_plan(dataset_id, source_adapters)
                        )
                    )
                )
            )
            for dataset_id in DATASET_IDS
        ),
        source_adapters=source_adapters,
    )
    return source_adapters, plans


def build_committer_registry(
    unit_of_work_factory: Callable[[], Any],
) -> DatasetCommitterRegistry:
    """Build one committer for every stable dataset in canonical order."""

    committers = {
        "core": CoreDatasetCommitter(unit_of_work_factory),
        "breadth": StandardSnapshotCommitter("breadth", unit_of_work_factory),
        "limits": LimitsDatasetCommitter(unit_of_work_factory),
        "sectors": StandardSnapshotCommitter("sectors", unit_of_work_factory),
        "activeDirection": StandardSnapshotCommitter(
            "activeDirection",
            unit_of_work_factory,
        ),
    }
    return DatasetCommitterRegistry.complete(
        committers[dataset_id] for dataset_id in DATASET_IDS
    )


def build_unit_of_work_factory(repository: Any) -> Callable[[], Any]:
    """Reuse the runtime store engine without connecting during composition."""

    engine = getattr(repository, "engine", None)
    if engine is None:
        return _unavailable_unit_of_work
    connections = PostgresConnectionFactory(engine)

    def factory() -> MarketEnvironmentUnitOfWork:
        return MarketEnvironmentUnitOfWork(connections, _postgres_repository_bundle)

    return factory


def _deferred_source_adapter(dataset_id: str) -> CompatibilitySourceAdapter:
    source_id = _compatibility_source_id(dataset_id)
    revision = "compatibility-deferred-v1"

    def fetch(_request: SourceRequest) -> Any:
        raise _DeferredCompatibilitySource(
            f"{dataset_id} source adapter has not completed its dataset cutover"
        )

    def normalize(_raw: Any, _request: SourceRequest):
        raise AssertionError("deferred compatibility source cannot normalize a payload")

    def classify_error(_error: Exception) -> AcquisitionFailure:
        return AcquisitionFailure(
            AcquisitionFailureCategory.CONFIGURATION,
            f"{dataset_id} acquisition plan is deferred to its dataset cutover",
            source=source_id,
            source_revision=revision,
        )

    return CompatibilitySourceAdapter(
        source_id=source_id,
        capability=SourceCapability(
            source_id=source_id,
            provider="legacy-compatibility",
            revision=revision,
        ),
        fetch=fetch,
        normalize=normalize,
        classify_error=classify_error,
    )


def _deferred_acquisition_plan(
    dataset_id: str,
    source_adapters: SourceAdapterRegistry,
) -> DeterministicAcquisitionPlan:
    return DeterministicAcquisitionPlan(
        dataset_id=dataset_id,
        plan_id=f"{dataset_id}-compatibility-deferred-v1",
        steps=(
            AcquisitionPlanStep(
                adapter_id=_compatibility_source_id(dataset_id),
                capability_revision="compatibility-deferred-v1",
            ),
        ),
        adapters=source_adapters,
    )


def _compatibility_source_id(dataset_id: str) -> str:
    return f"legacy-compatibility-{dataset_id}"


def _unavailable_unit_of_work() -> Any:
    raise RuntimeError(
        "dataset committers require a PostgreSQL repository or an explicit "
        "unit-of-work factory"
    )


def _postgres_repository_bundle(connection: Any) -> SimpleNamespace:
    leases = PostgresLeaseRepository(connection)
    return SimpleNamespace(
        snapshots=PostgresSnapshotRepository(connection),
        collection_runs=PostgresCollectionRunRepository(connection),
        collection_tasks=PostgresCollectionTaskRepository(connection),
        core_index_results=PostgresCoreIndexResultRepository(connection),
        leases=leases,
        trading_sessions=PostgresTradingSessionRepository(connection),
        aggregates=PostgresMaterializedAggregateRepository(connection, leases=leases),
        provider_capabilities=PostgresProviderCapabilityRepository(connection),
        limit_details=PostgresLimitDetailRepository(connection),
        timezone_preferences=PostgresTimezonePreferenceRepository(connection),
    )


__all__ = [
    "RuntimeRegistries",
    "build_committer_registry",
    "build_deferred_acquisition_registries",
    "build_runtime_acquisition_registries",
    "build_unit_of_work_factory",
]
