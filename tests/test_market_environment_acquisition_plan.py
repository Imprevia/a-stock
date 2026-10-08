from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

import pytest

from src.market_environment.application.collection import SourceAdapterRegistry
from src.market_environment.application.ports import (
    AcquisitionPlanStep,
    SourceCapability,
    SourceRequest,
)
from src.market_environment.domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    CollectionCandidate,
    CollectionTaskState,
    DatasetDate,
    RedactedProvenance,
)
from src.market_environment.infrastructure.providers.acquisition import (
    CompatibilitySourceAdapter,
    DeterministicAcquisitionPlan,
)
from src.market_environment.infrastructure.providers.provenance import (
    evidence_fingerprint,
    redact_mapping,
)


AS_OF = date(2026, 9, 30)
IDENTITY = DatasetDate("sectors", AS_OF)


@dataclass
class Adapter:
    source_id: str
    result: CollectionCandidate | AcquisitionFailure
    calls: list = field(default_factory=list)

    @property
    def capability(self):
        return SourceCapability(self.source_id, self.source_id.split("-")[0], "v1")

    def acquire(self, request):
        self.calls.append(request)
        return self.result


def candidate(source: str, payload: dict, *, status: str = "ok") -> CollectionCandidate:
    return CollectionCandidate(
        identity=IDENTITY,
        payload=payload,
        source=source,
        status=status,
        observations=1,
        warnings=(),
        settled=True,
        actual_as_of=AS_OF,
        source_revision="v1",
    )


def failure(source: str) -> AcquisitionFailure:
    return AcquisitionFailure(
        AcquisitionFailureCategory.NETWORK,
        f"{source} unavailable",
        source=source,
        source_revision="v1",
        requested_as_of=AS_OF,
    )


def test_compatibility_source_adapter_executes_one_provider_call_without_orchestration() -> None:
    calls = []
    raw = {"mainNet": 12}
    adapter = CompatibilitySourceAdapter(
        source_id="legacy-sectors",
        capability=SourceCapability("legacy-sectors", "legacy", "v1"),
        fetch=lambda request: calls.append(request) or raw,
        normalize=lambda value, _request: candidate("legacy-sectors", value),
    )

    result = adapter.acquire(
        SourceRequest(IDENTITY, "legacy-sectors", capability_revision="v1")
    )

    assert isinstance(result, CollectionCandidate)
    assert result.payload == raw
    assert len(calls) == 1
    assert not any(hasattr(adapter, name) for name in ("store", "coordinator", "lease", "rebuild"))


def test_plan_preserves_fallback_shadow_and_fill_only_enrichment_lineage() -> None:
    primary = Adapter("primary", failure("primary"))
    fallback = Adapter("fallback", candidate("fallback", {"value": 10, "filled": None}, status="fallback"))
    shadow = Adapter("shadow", candidate("shadow", {"value": 999, "filled": 999}))
    enrichment = Adapter("enrichment", candidate("enrichment", {"value": 777, "filled": 20, "blocked": 30}))
    registry = SourceAdapterRegistry((primary, fallback, shadow, enrichment))
    plan = DeterministicAcquisitionPlan(
        dataset_id="sectors",
        plan_id="sectors-v1",
        adapters=registry,
        steps=(
            AcquisitionPlanStep("primary", role="formal", capability_revision="v1"),
            AcquisitionPlanStep("fallback", role="fallback", capability_revision="v1"),
            AcquisitionPlanStep("shadow", role="shadow", capability_revision="v1"),
            AcquisitionPlanStep(
                "enrichment",
                role="enrichment",
                capability_revision="v1",
                approved_fields=("filled",),
            ),
        ),
    )

    outcome = plan.collect(IDENTITY)

    assert outcome.state is CollectionTaskState.PARTIAL
    assert outcome.candidate is not None
    assert outcome.candidate.source == "fallback"
    assert outcome.candidate.payload == {"value": 10, "filled": 20}
    assert [attempt.role for attempt in outcome.attempts] == [
        "formal",
        "fallback",
        "shadow",
        "enrichment",
    ]
    assert outcome.attempts[0].category is AcquisitionFailureCategory.NETWORK
    assert "primary unavailable" in outcome.candidate.warnings
    assert len(primary.calls) == len(fallback.calls) == len(shadow.calls) == len(enrichment.calls) == 1


def test_shadow_failure_never_downgrades_formal_candidate() -> None:
    formal = Adapter("formal", candidate("formal", {"value": 1}))
    shadow = Adapter("shadow", failure("shadow"))
    plan = DeterministicAcquisitionPlan(
        "sectors",
        "sectors-shadow-v1",
        (
            AcquisitionPlanStep("formal", capability_revision="v1"),
            AcquisitionPlanStep("shadow", role="shadow", capability_revision="v1"),
        ),
        SourceAdapterRegistry((formal, shadow)),
    )

    outcome = plan.collect(IDENTITY)

    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert outcome.candidate.source == "formal"
    assert outcome.candidate.payload == {"value": 1}
    assert outcome.candidate.warnings == ("shadow unavailable",)


def test_compatibility_adapter_enforces_latest_only_settlement_before_io() -> None:
    calls = []
    adapter = CompatibilitySourceAdapter(
        "latest",
        SourceCapability(
            "latest",
            "fixture",
            "v1",
            supports_historical=False,
            latest_only=True,
        ),
        fetch=lambda request: calls.append(request) or {},
        normalize=lambda _value, _request: candidate("latest", {"value": 1}),
    )

    historical = adapter.acquire(
        SourceRequest(
            IDENTITY,
            "latest",
            current_market_date=date(2026, 10, 1),
            settled=True,
        )
    )
    unsettled = adapter.acquire(
        SourceRequest(
            IDENTITY,
            "latest",
            current_market_date=AS_OF,
            settled=False,
        )
    )

    assert historical.category is AcquisitionFailureCategory.DATE_MISMATCH
    assert unsettled.category is AcquisitionFailureCategory.INSUFFICIENT
    assert calls == []


@pytest.mark.parametrize("evidence_kind", ["http-date", "page-time", "fetch-time", "latest-only"])
def test_historical_date_rejects_weak_evidence(evidence_kind: str) -> None:
    weak = replace(
        candidate("history", {"value": 1}),
        provenance=RedactedProvenance(attributes={"dateEvidenceKind": evidence_kind}),
    )
    adapter = CompatibilitySourceAdapter(
        "history",
        SourceCapability("history", "fixture", "v1"),
        fetch=lambda _request: weak,
        normalize=lambda value, _request: value,
    )
    request = SourceRequest(
        IDENTITY,
        "history",
        current_market_date=date(2026, 10, 1),
        settled=True,
    )

    result = adapter.acquire(request)

    assert result.category is AcquisitionFailureCategory.DATE_MISMATCH


def test_cross_date_cache_and_mismatched_package_cannot_prove_requested_date() -> None:
    cached = replace(
        candidate("history", {"value": 1}),
        provenance=RedactedProvenance(
            attributes={
                "dateEvidenceKind": "response",
                "cacheRequestedAsOf": "2026-09-29",
            }
        ),
    )
    other_identity = DatasetDate("sectors", date(2026, 9, 29))
    mismatched_package = CollectionCandidate(
        identity=other_identity,
        payload={"value": 1},
        source="history",
        status="ok",
        observations=1,
        warnings=(),
        settled=True,
        actual_as_of=other_identity.as_of,
        provenance=RedactedProvenance(attributes={"dateEvidenceKind": "package"}),
    )
    results = iter((cached, mismatched_package))
    adapter = CompatibilitySourceAdapter(
        "history",
        SourceCapability("history", "fixture", "v1"),
        fetch=lambda _request: next(results),
        normalize=lambda value, _request: value,
    )
    request = SourceRequest(
        IDENTITY,
        "history",
        current_market_date=date(2026, 10, 1),
        settled=True,
    )

    assert adapter.acquire(request).category is AcquisitionFailureCategory.DATE_MISMATCH
    assert adapter.acquire(request).category is AcquisitionFailureCategory.DATE_MISMATCH


def test_provenance_is_redacted_and_fingerprinted_before_return() -> None:
    secret = "super-secret-value"
    raw_candidate = replace(
        candidate("history", {"value": 1}),
        provenance=RedactedProvenance(
            endpoint=f"https://fixture.invalid/data?api_key={secret}&symbol=000001",
            engine="requests",
            attributes={
                "dateEvidenceKind": "response",
                "headers": {"Authorization": f"Bearer {secret}", "Cookie": secret},
                "proxy": f"http://user:{secret}@proxy.invalid",
                "challengeBody": f"captcha {secret}",
            },
        ),
    )
    adapter = CompatibilitySourceAdapter(
        "history",
        SourceCapability("history", "fixture", "v1"),
        fetch=lambda _request: raw_candidate,
        normalize=lambda value, _request: value,
    )

    result = adapter.acquire(
        SourceRequest(
            IDENTITY,
            "history",
            current_market_date=date(2026, 10, 1),
            settled=True,
        )
    )

    assert isinstance(result, CollectionCandidate)
    serialized = repr(result.provenance)
    assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert result.evidence_fingerprint is not None
    assert len(result.evidence_fingerprint) == 64

    first = evidence_fingerprint({"endpoint": f"https://x.invalid?a=1&token={secret}"})
    second = evidence_fingerprint({"endpoint": f"https://x.invalid?a=1&token={secret}"})
    assert first == second
    assert secret not in repr(redact_mapping({"rawBody": secret, "password": secret}))
