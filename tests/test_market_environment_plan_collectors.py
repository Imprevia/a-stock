from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from src.market_environment.application.collection import AcquisitionPlanRegistry, SourceAdapterRegistry
from src.market_environment.application.ports import AcquisitionPlanStep, DatasetCollector
from src.market_environment.domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DATASET_IDS,
    DatasetDate,
)
from src.market_environment.infrastructure.collection.collectors import (
    AcquisitionPlanCollector,
    build_plan_collector_registry,
)


AS_OF = date(2026, 9, 14)


@dataclass
class Plan:
    dataset_id: str
    result: CollectionOutcome
    plan_id: str = "fixture-v1"
    steps: tuple[AcquisitionPlanStep, ...] = (AcquisitionPlanStep("fixture"),)

    def collect(self, identity):
        return self.result


@dataclass(frozen=True)
class Adapter:
    source_id: str = "fixture"

    @property
    def capability(self):
        from src.market_environment.application.ports import SourceCapability

        return SourceCapability("fixture", "fixture", "v1")

    def acquire(self, request):
        raise AssertionError("fixture plan does not call its adapter")


def outcome(dataset: str, state: CollectionTaskState) -> CollectionOutcome:
    identity = DatasetDate(dataset, AS_OF)
    if state in {CollectionTaskState.SUCCESS, CollectionTaskState.PARTIAL}:
        candidate = CollectionCandidate(
            identity=identity,
            payload={"asOf": AS_OF.isoformat()},
            source="fixture",
            status="partial" if state is CollectionTaskState.PARTIAL else "ok",
            observations=1,
            warnings=(),
            settled=True,
            actual_as_of=AS_OF,
        )
        return CollectionOutcome(identity, state, candidate=candidate)
    failure = AcquisitionFailure(
        AcquisitionFailureCategory.NETWORK,
        "fixture unavailable",
        requested_as_of=AS_OF,
    )
    return CollectionOutcome(
        identity,
        state,
        warning=failure.message,
        retained=state is CollectionTaskState.FAILED_RETAINED,
        failure=failure,
    )


def registry_for(state: CollectionTaskState):
    sources = SourceAdapterRegistry((Adapter(),))
    plans = AcquisitionPlanRegistry.complete(
        (Plan(dataset_id, outcome(dataset_id, state)) for dataset_id in DATASET_IDS),
        source_adapters=sources,
    )
    return build_plan_collector_registry(plans)


@pytest.mark.parametrize(
    "state",
    (
        CollectionTaskState.SUCCESS,
        CollectionTaskState.PARTIAL,
        CollectionTaskState.FAILED_MISSING,
        CollectionTaskState.FAILED_RETAINED,
    ),
)
def test_plan_collectors_return_normalized_outcomes_without_persistence(state) -> None:
    registry = registry_for(state)
    identity = DatasetDate("breadth", AS_OF)

    result = registry.collect(identity)

    assert result.state is state
    assert registry.dataset_ids == DATASET_IDS
    assert all(isinstance(collector, DatasetCollector) for collector in registry)
    assert all(
        not hasattr(collector, attribute)
        for collector in registry
        for attribute in ("store", "lease", "coordinator", "rebuild_aggregate", "collect_task")
    )


def test_plan_collector_rejects_mismatched_outcome_before_commit() -> None:
    sources = SourceAdapterRegistry((Adapter(),))
    wrong = outcome("sectors", CollectionTaskState.SUCCESS)
    plans = AcquisitionPlanRegistry(
        (Plan("breadth", wrong),),
        source_adapters=sources,
    )
    collector = AcquisitionPlanCollector("breadth", plans)

    with pytest.raises(ValueError, match="mismatched outcome identity"):
        collector.collect(DatasetDate("breadth", AS_OF))
