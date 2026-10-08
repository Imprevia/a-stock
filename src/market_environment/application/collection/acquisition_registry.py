"""Fail-closed registries for source adapters and dataset acquisition plans."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from types import MappingProxyType

from ...domain.models import DATASET_IDS
from ..ports.acquisition import AcquisitionPlan, SourceAdapter


class SourceAdapterRegistry:
    def __init__(self, adapters: Iterable[SourceAdapter] = ()) -> None:
        registered: dict[str, SourceAdapter] = {}
        for adapter in adapters:
            source_id = adapter.source_id
            if not source_id.strip():
                raise ValueError("source adapter id must not be empty")
            if source_id in registered:
                raise ValueError(f"duplicate source adapter: {source_id}")
            if adapter.capability.source_id != source_id:
                raise ValueError(f"source capability id mismatch: {source_id}")
            if adapter.capability.revision != adapter.capability.revision.strip():
                raise ValueError(f"invalid source capability revision: {source_id}")
            registered[source_id] = adapter
        self._adapters = MappingProxyType(registered)

    def get(self, source_id: str) -> SourceAdapter:
        adapter = self._adapters.get(source_id)
        if adapter is None:
            raise ValueError(f"unknown source adapter: {source_id}")
        return adapter

    def validate_references(self, plans: Iterable[AcquisitionPlan]) -> None:
        for plan in plans:
            if plan.dataset_id not in DATASET_IDS:
                raise ValueError(f"unsupported acquisition plan dataset: {plan.dataset_id}")
            if not plan.plan_id.strip():
                raise ValueError(f"acquisition plan for {plan.dataset_id} has no id")
            if not plan.steps:
                raise ValueError(f"acquisition plan has no steps: {plan.dataset_id}")
            for step in plan.steps:
                adapter = self.get(step.adapter_id)
                if not adapter.capability.available:
                    raise ValueError(f"unavailable source adapter: {step.adapter_id}")
                if step.capability_revision is not None and step.capability_revision != adapter.capability.revision:
                    raise ValueError(
                        f"capability revision mismatch for {step.adapter_id}: "
                        f"expected {step.capability_revision}, registered {adapter.capability.revision}"
                    )

    def __contains__(self, source_id: object) -> bool:
        return source_id in self._adapters

    def __iter__(self) -> Iterator[SourceAdapter]:
        return iter(self._adapters.values())

    def __len__(self) -> int:
        return len(self._adapters)


class AcquisitionPlanRegistry:
    def __init__(
        self,
        plans: Iterable[AcquisitionPlan] = (),
        *,
        source_adapters: SourceAdapterRegistry | None = None,
    ) -> None:
        registered: dict[str, AcquisitionPlan] = {}
        for plan in plans:
            if plan.dataset_id not in DATASET_IDS:
                raise ValueError(f"unsupported acquisition plan dataset: {plan.dataset_id}")
            if plan.dataset_id in registered:
                raise ValueError(f"duplicate acquisition plan: {plan.dataset_id}")
            registered[plan.dataset_id] = plan
        self._plans = MappingProxyType(registered)
        if source_adapters is not None:
            source_adapters.validate_references(self._plans.values())

    @classmethod
    def complete(
        cls,
        plans: Iterable[AcquisitionPlan],
        *,
        source_adapters: SourceAdapterRegistry,
    ) -> "AcquisitionPlanRegistry":
        registry = cls(plans, source_adapters=source_adapters)
        missing = tuple(dataset for dataset in DATASET_IDS if dataset not in registry._plans)
        if missing:
            raise ValueError(f"missing acquisition plans: {', '.join(missing)}")
        return registry

    @property
    def dataset_ids(self) -> tuple[str, ...]:
        return tuple(dataset for dataset in DATASET_IDS if dataset in self._plans)

    def get(self, dataset_id: str) -> AcquisitionPlan:
        plan = self._plans.get(dataset_id)
        if plan is None:
            raise ValueError(f"unknown acquisition plan: {dataset_id}")
        return plan

    def __contains__(self, dataset_id: object) -> bool:
        return dataset_id in self._plans

    def __iter__(self) -> Iterator[AcquisitionPlan]:
        return (self._plans[dataset] for dataset in self.dataset_ids)

    def __len__(self) -> int:
        return len(self._plans)


__all__ = ["AcquisitionPlanRegistry", "SourceAdapterRegistry"]
