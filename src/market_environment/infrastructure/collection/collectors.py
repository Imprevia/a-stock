"""Persistence-free collectors backed by registered acquisition plans."""

from __future__ import annotations

from dataclasses import dataclass

from ...application.collection import AcquisitionPlanRegistry, DatasetCollectorRegistry
from ...domain.models import (
    DATASET_IDS,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
)


@dataclass(frozen=True, slots=True)
class AcquisitionPlanCollector:
    dataset_id: str
    plans: AcquisitionPlanRegistry

    def __post_init__(self) -> None:
        if self.dataset_id not in DATASET_IDS:
            raise ValueError(f"unsupported acquisition collector: {self.dataset_id}")
        self.plans.get(self.dataset_id)

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        if identity.dataset != self.dataset_id:
            raise ValueError(
                f"collector {self.dataset_id} cannot collect {identity.dataset}"
            )
        outcome = self.plans.get(self.dataset_id).collect(identity)
        if outcome.identity != identity:
            raise ValueError("acquisition plan returned a mismatched outcome identity")
        if outcome.state in {CollectionTaskState.SUCCESS, CollectionTaskState.PARTIAL}:
            candidate = outcome.candidate
            if candidate is None or candidate.identity != identity:
                raise ValueError("acquisition plan returned a mismatched candidate identity")
        if outcome.state in {
            CollectionTaskState.FAILED_MISSING,
            CollectionTaskState.FAILED_RETAINED,
        } and outcome.failure is None and not outcome.warning:
            raise ValueError("acquisition plan returned an unclassified failure")
        return outcome


def build_plan_collector_registry(
    plans: AcquisitionPlanRegistry,
) -> DatasetCollectorRegistry:
    return DatasetCollectorRegistry.complete(
        AcquisitionPlanCollector(dataset_id, plans) for dataset_id in DATASET_IDS
    )


__all__ = ["AcquisitionPlanCollector", "build_plan_collector_registry"]
