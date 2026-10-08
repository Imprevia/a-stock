from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.market_environment.application.collection import (
    AcquisitionPlanRegistry,
    SourceAdapterRegistry,
)
from src.market_environment.application.ports import (
    AcquisitionPlanStep,
    SourceCapability,
    SourceRequest,
)
from src.market_environment.domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    CollectionOutcome,
    CollectionTaskState,
    DATASET_IDS,
    DatasetDate,
)


@dataclass
class Adapter:
    source_id: str
    capability: SourceCapability

    def acquire(self, request: SourceRequest):
        return AcquisitionFailure(
            AcquisitionFailureCategory.INSUFFICIENT,
            f"fixture {request.source_id}",
        )


@dataclass
class Plan:
    dataset_id: str
    plan_id: str
    steps: tuple[AcquisitionPlanStep, ...]

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        return CollectionOutcome(
            identity=identity,
            state=CollectionTaskState.FAILED_MISSING,
            warning="fixture",
        )


def adapter(source_id: str, revision: str = "v1", *, available: bool = True) -> Adapter:
    return Adapter(
        source_id,
        SourceCapability(source_id, "fixture", revision, available=available),
    )


def complete_plans() -> tuple[Plan, ...]:
    return tuple(
        Plan(dataset, f"{dataset}-plan", (AcquisitionPlanStep("fixture"),))
        for dataset in DATASET_IDS
    )


def test_complete_acquisition_registries_validate_stable_datasets_and_revisions() -> None:
    sources = SourceAdapterRegistry((adapter("fixture"),))
    plans = AcquisitionPlanRegistry.complete(complete_plans(), source_adapters=sources)

    assert plans.dataset_ids == DATASET_IDS
    assert sources.get("fixture").capability.revision == "v1"


def test_acquisition_registries_fail_closed_before_external_io() -> None:
    sources = SourceAdapterRegistry((adapter("fixture"),))

    with pytest.raises(ValueError, match="duplicate source adapter"):
        SourceAdapterRegistry((adapter("fixture"), adapter("fixture")))

    with pytest.raises(ValueError, match="unknown source adapter"):
        AcquisitionPlanRegistry(
            (Plan("core", "core-plan", (AcquisitionPlanStep("missing"),)),),
            source_adapters=sources,
        )

    with pytest.raises(ValueError, match="capability revision mismatch"):
        AcquisitionPlanRegistry(
            (Plan("core", "core-plan", (AcquisitionPlanStep("fixture", capability_revision="v2"),)),),
            source_adapters=sources,
        )

    with pytest.raises(ValueError, match="missing acquisition plans"):
        AcquisitionPlanRegistry.complete(
            complete_plans()[:-1],
            source_adapters=sources,
        )


def test_registry_validates_fallback_shadow_enrichment_and_availability() -> None:
    roles = ("formal", "fallback", "shadow", "enrichment")
    steps = tuple(
        AcquisitionPlanStep(role, role=role, capability_revision="v1")
        for role in roles
    )
    sources = SourceAdapterRegistry(tuple(adapter(role) for role in roles))
    registry = AcquisitionPlanRegistry(
        (Plan("sectors", "sectors-plan", steps),),
        source_adapters=sources,
    )
    assert registry.get("sectors").steps == steps

    unavailable = SourceAdapterRegistry((adapter("formal", available=False),))
    with pytest.raises(ValueError, match="unavailable source adapter"):
        AcquisitionPlanRegistry(
            (Plan("core", "core-plan", (AcquisitionPlanStep("formal"),)),),
            source_adapters=unavailable,
        )
