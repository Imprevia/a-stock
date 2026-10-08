"""Compatibility adapters and deterministic dataset acquisition plans."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from ...application.collection import SourceAdapterRegistry
from ...application.ports import AcquisitionPlanStep, SourceCapability, SourceRequest
from ...domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    AttemptEvidence,
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
)
from .provenance import evidence_fingerprint, redact_provenance


@dataclass(frozen=True, slots=True)
class CompatibilitySourceAdapter:
    """Translate one legacy provider call without orchestration side effects."""

    source_id: str
    capability: SourceCapability
    fetch: Callable[[SourceRequest], Any]
    normalize: Callable[[Any, SourceRequest], CollectionCandidate]
    classify_error: Callable[[Exception], AcquisitionFailure] | None = None

    def __post_init__(self) -> None:
        if self.source_id != self.capability.source_id:
            raise ValueError("compatibility adapter source and capability must match")

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        if request.source_id != self.source_id:
            return AcquisitionFailure(
                AcquisitionFailureCategory.CONFIGURATION,
                f"source request {request.source_id} does not match adapter {self.source_id}",
                source=self.source_id,
                source_revision=self.capability.revision,
                requested_as_of=request.identity.as_of,
            )
        if request.capability_revision not in {None, self.capability.revision}:
            return AcquisitionFailure(
                AcquisitionFailureCategory.CONFIGURATION,
                f"source capability revision mismatch for {self.source_id}",
                source=self.source_id,
                source_revision=self.capability.revision,
                requested_as_of=request.identity.as_of,
            )
        if self.capability.latest_only and request.current_market_date != request.identity.as_of:
            return AcquisitionFailure(
                AcquisitionFailureCategory.DATE_MISMATCH,
                f"latest-only source {self.source_id} cannot prove historical date",
                source=self.source_id,
                source_revision=self.capability.revision,
                requested_as_of=request.identity.as_of,
            )
        if self.capability.latest_only and request.settled is not True:
            return AcquisitionFailure(
                AcquisitionFailureCategory.INSUFFICIENT,
                f"latest-only source {self.source_id} requires settlement evidence",
                source=self.source_id,
                source_revision=self.capability.revision,
                requested_as_of=request.identity.as_of,
            )
        try:
            raw = self.fetch(request)
            candidate = self.normalize(raw, request)
        except Exception as exc:
            if self.classify_error is not None:
                return self.classify_error(exc)
            return AcquisitionFailure(
                AcquisitionFailureCategory.CONTRACT,
                f"{self.source_id} compatibility source failed: {type(exc).__name__}",
                source=self.source_id,
                source_revision=self.capability.revision,
                requested_as_of=request.identity.as_of,
                fetched_at=datetime.now(timezone.utc),
            )
        if candidate.identity != request.identity:
            return AcquisitionFailure(
                AcquisitionFailureCategory.DATE_MISMATCH,
                f"{self.source_id} returned another dataset or date",
                source=self.source_id,
                source_revision=self.capability.revision,
                requested_as_of=request.identity.as_of,
                fetched_at=candidate.fetched_at,
            )
        if candidate.actual_as_of is None:
            return AcquisitionFailure(
                AcquisitionFailureCategory.DATE_MISMATCH,
                f"{self.source_id} did not prove an actual market date",
                source=self.source_id,
                source_revision=self.capability.revision,
                requested_as_of=request.identity.as_of,
                fetched_at=candidate.fetched_at,
            )
        provenance = redact_provenance(candidate.provenance)
        date_kind = str(provenance.attributes.get("dateEvidenceKind") or "")
        cached_date = provenance.attributes.get("cacheRequestedAsOf")
        historical = (
            request.current_market_date is not None
            and request.identity.as_of != request.current_market_date
        )
        if historical and date_kind in {"", "http-date", "page-time", "fetch-time", "cache", "latest-only"}:
            return AcquisitionFailure(
                AcquisitionFailureCategory.DATE_MISMATCH,
                f"{self.source_id} date evidence cannot prove historical data",
                source=self.source_id,
                source_revision=self.capability.revision,
                requested_as_of=request.identity.as_of,
                fetched_at=candidate.fetched_at,
                provenance=provenance,
            )
        if cached_date is not None and str(cached_date) != request.identity.as_of.isoformat():
            return AcquisitionFailure(
                AcquisitionFailureCategory.DATE_MISMATCH,
                f"{self.source_id} cached evidence belongs to another requested date",
                source=self.source_id,
                source_revision=self.capability.revision,
                requested_as_of=request.identity.as_of,
                fetched_at=candidate.fetched_at,
                provenance=provenance,
            )
        fingerprint = candidate.evidence_fingerprint or evidence_fingerprint(
            {
                "dataset": candidate.identity.dataset,
                "requestedAsOf": candidate.identity.as_of.isoformat(),
                "actualAsOf": candidate.actual_as_of.isoformat(),
                "source": candidate.source,
                "sourceRevision": candidate.source_revision or self.capability.revision,
                "provenance": {
                    "endpoint": provenance.endpoint,
                    "engine": provenance.engine,
                    **dict(provenance.attributes),
                },
            }
        )
        return replace(candidate, provenance=provenance, evidence_fingerprint=fingerprint)


@dataclass(frozen=True, slots=True)
class DeterministicAcquisitionPlan:
    dataset_id: str
    plan_id: str
    steps: tuple[AcquisitionPlanStep, ...]
    adapters: SourceAdapterRegistry

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError("acquisition plan id must not be empty")
        self.adapters.validate_references((self,))

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        if identity.dataset != self.dataset_id:
            failure = AcquisitionFailure(
                AcquisitionFailureCategory.CONFIGURATION,
                f"plan {self.plan_id} cannot collect {identity.dataset}",
                requested_as_of=identity.as_of,
            )
            return CollectionOutcome(
                identity=identity,
                state=CollectionTaskState.FAILED_MISSING,
                warning=failure.message,
                failure=failure,
            )

        attempts: list[AttemptEvidence] = []
        warnings: list[str] = []
        candidate: CollectionCandidate | None = None
        last_failure: AcquisitionFailure | None = None

        for step in self.steps:
            if not step.enabled or step.role in {"shadow", "enrichment"}:
                continue
            if candidate is not None:
                break
            result = self._attempt(identity, step, attempts)
            if isinstance(result, AcquisitionFailure):
                last_failure = result
                warnings.append(result.message)
            else:
                candidate = result

        if candidate is None:
            failure = last_failure or AcquisitionFailure(
                AcquisitionFailureCategory.INSUFFICIENT,
                f"acquisition plan {self.plan_id} produced no candidate",
                requested_as_of=identity.as_of,
            )
            return CollectionOutcome(
                identity=identity,
                state=CollectionTaskState.FAILED_MISSING,
                warning="; ".join(warnings) or failure.message,
                failure=failure,
                attempts=tuple(attempts),
            )

        formal = candidate
        for step in self.steps:
            if not step.enabled or step.role not in {"shadow", "enrichment"}:
                continue
            result = self._attempt(identity, step, attempts)
            if isinstance(result, AcquisitionFailure):
                warnings.append(result.message)
                continue
            if step.role == "enrichment":
                formal = self._fill_approved_fields(formal, result, step.approved_fields)

        combined_warnings = tuple(dict.fromkeys((*formal.warnings, *warnings)))
        formal = replace(formal, warnings=combined_warnings)
        state = (
            CollectionTaskState.PARTIAL
            if formal.status in {"partial", "fallback", "fallback-derived", "degraded"}
            else CollectionTaskState.SUCCESS
        )
        return CollectionOutcome(
            identity=identity,
            state=state,
            candidate=formal,
            warning="; ".join(combined_warnings) or None,
            attempts=tuple(attempts),
        )

    def _attempt(
        self,
        identity: DatasetDate,
        step: AcquisitionPlanStep,
        attempts: list[AttemptEvidence],
    ) -> CollectionCandidate | AcquisitionFailure:
        adapter = self.adapters.get(step.adapter_id)
        result = adapter.acquire(
            SourceRequest(
                identity=identity,
                source_id=step.adapter_id,
                role=step.role,
                capability_revision=step.capability_revision,
            )
        )
        if isinstance(result, AcquisitionFailure):
            attempts.append(
                AttemptEvidence(
                    role=step.role,
                    provider=adapter.capability.provider,
                    source=step.adapter_id,
                    source_revision=adapter.capability.revision,
                    requested_as_of=identity.as_of,
                    category=result.category,
                    warning=result.message,
                    timings=result.timings,
                    provenance=result.provenance,
                    evidence_fingerprint=result.evidence_fingerprint,
                )
            )
            return result
        attempts.append(
            AttemptEvidence(
                role=step.role,
                provider=(result.quality.provider if result.quality is not None else adapter.capability.provider),
                source=result.source,
                source_revision=result.source_revision or adapter.capability.revision,
                requested_as_of=identity.as_of,
                actual_as_of=result.actual_as_of,
                timings=result.timings,
                provenance=result.provenance,
                evidence_fingerprint=result.evidence_fingerprint,
            )
        )
        return result

    @staticmethod
    def _fill_approved_fields(
        base: CollectionCandidate,
        enrichment: CollectionCandidate,
        approved_fields: tuple[str, ...],
    ) -> CollectionCandidate:
        payload = copy.deepcopy(dict(base.payload))
        supplemental = enrichment.payload
        for field_name in approved_fields:
            if payload.get(field_name) is None and supplemental.get(field_name) is not None:
                payload[field_name] = copy.deepcopy(supplemental[field_name])
        return replace(base, payload=payload)


__all__ = ["CompatibilitySourceAdapter", "DeterministicAcquisitionPlan"]
