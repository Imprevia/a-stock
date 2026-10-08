"""Normalized limits source adapters and the staged limits acquisition plan.

This module deliberately stops at the acquisition boundary.  It does not
acquire a lease, write a snapshot, prepare a previous-session store bundle,
or invoke a coordinator.  The existing provider implementation remains the
source of truth for row mapping and summary payload construction while the
adapters expose one vendor-neutral candidate/failure contract.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Protocol

from ...application.collection import SourceAdapterRegistry
from ...application.ports import AcquisitionPlanStep, SourceCapability, SourceRequest
from ...domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    AcquisitionTimings,
    AttemptEvidence,
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
    FieldAvailability,
    QualityMetadata,
    RedactedProvenance,
)
from ...domain.policies.limit_facts import LimitNormalizationResult, normalize_limit_pools
from ...limit_promotion import limit_v1_enabled
from .fuyao.limits_client import (
    FuyaoConfigurationError,
    FuyaoContractError,
    FuyaoError,
    FuyaoNonTradingDayError,
    FuyaoPermissionError,
    FuyaoTransportError,
)
from .provenance import evidence_fingerprint, redact_provenance
from .shadow import compare_shadow


LIMITS_FUYAO_SOURCE_ID = "limits-fuyao"
LIMITS_EASTMONEY_SOURCE_ID = "limits-eastmoney"
LIMITS_LEGACY_SUMMARY_SOURCE_ID = "limits-legacy-summary"

# Descriptive aliases make the source ordering explicit to callers and tests.
FUYAO_LIMITS_SOURCE_ID = LIMITS_FUYAO_SOURCE_ID
EASTMONEY_LIMITS_SOURCE_ID = LIMITS_EASTMONEY_SOURCE_ID
LEGACY_LIMITS_SUMMARY_SOURCE_ID = LIMITS_LEGACY_SUMMARY_SOURCE_ID

LIMITS_SOURCE_REVISION = "fuyao-limit-pools-v1"
EASTMONEY_LIMITS_SOURCE_REVISION = "eastmoney-limit-pools-v1"
LEGACY_LIMITS_SOURCE_REVISION = "limits-summary-v1"
LIMITS_RULE_VERSION = "limits-promotion-v2"

_SUCCESS_STATUSES = frozenset({"ok", "partial", "fallback", "fallback-derived", "degraded"})
_LIMIT_FIELDS = (
    "limitUpCount",
    "limitDownCount",
    "failedLimitUpCount",
    "failedLimitUpRatio",
    "maxStreak",
    "state",
)
_DETAIL_FIELDS = (
    "securityDetails",
    "membershipQuality",
    "streakQuality",
    "poolQuality",
)
_AUDIT_WARNING = (
    "Fuyao pool response omits the session date; the calendar-confirmed request date "
    "is used as evidence"
)


class LegacyLimitsProvider(Protocol):
    """Minimal provider surface used by Eastmoney/summary adapters."""

    def _fetch_eastmoney_limit_dataset(
        self,
        as_of: date,
        *,
        strict: bool,
        on_pool: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> Any: ...

    def fetch_chapter01_limits(self, as_of: date) -> Mapping[str, Any]: ...


class FuyaoLimitsProvider(LegacyLimitsProvider, Protocol):
    fuyao: Any

    def _map_fuyao_limit_dataset(self, dataset: Any) -> dict[str, list[dict[str, Any]]]: ...

    def _merge_limit_sources(
        self,
        fuyao: Any,
        eastmoney: Any | None,
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], list[str]]: ...

    def _limit_payload(
        self,
        as_of: date,
        pools: Mapping[str, list[Any]],
        warnings: list[str],
        *,
        source: str,
        provider_status: str,
    ) -> dict[str, Any]: ...

    @staticmethod
    def _append_limit_warning(
        payload: dict[str, Any],
        warning: str,
        *,
        status: str | None = None,
    ) -> dict[str, Any]: ...

    @staticmethod
    def normalize_limit_pools(
        pools: dict[str, list[Any] | None],
        as_of: date,
        *,
        actual_as_of: date | None = None,
        source: str = "provider",
        source_revision: str | None = None,
        rule_version: str | None = None,
        membership_complete: bool | None = None,
        streak_complete: bool | None = None,
        pool_quality: Mapping[str, Any] | None = None,
    ) -> LimitNormalizationResult: ...


class _PoolRows(list):
    """List-compatible Fuyao rows carrying the date evidence used by payloads."""

    def __init__(self, rows: list[Any], *, as_of: date, source: str) -> None:
        super().__init__(rows)
        self.actual_as_of = as_of
        self.date_evidence = "request-parameter"
        self.source = source


@dataclass(frozen=True, slots=True)
class LimitsCollectionCandidate(CollectionCandidate):
    """Limits candidate retaining typed detail evidence outside the API payload."""

    normalization: LimitNormalizationResult | None = None
    previous_as_of: date | None = None

    def __post_init__(self) -> None:
        super(LimitsCollectionCandidate, self).__post_init__()
        if self.normalization is not None and (
            self.normalization.as_of != self.identity.as_of
            or self.normalization.actual_as_of != self.identity.as_of
        ):
            raise ValueError("limits candidate normalization date mismatch")
        if self.previous_as_of is not None and self.previous_as_of >= self.identity.as_of:
            raise ValueError("limits previous session must precede the requested date")


@dataclass(frozen=True, slots=True)
class _LimitsSourceResult:
    payload: dict[str, Any]
    normalization: LimitNormalizationResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _milliseconds(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _failure(
    request: SourceRequest,
    capability: SourceCapability,
    category: AcquisitionFailureCategory,
    message: str,
    *,
    retryable: bool = False,
    fetched_at: datetime | None = None,
    timings: AcquisitionTimings | None = None,
    provenance: RedactedProvenance | None = None,
) -> AcquisitionFailure:
    return AcquisitionFailure(
        category=category,
        message=str(message) or f"{capability.source_id} acquisition failed",
        retryable=retryable,
        source=capability.source_id,
        source_revision=capability.revision,
        requested_as_of=request.identity.as_of,
        fetched_at=fetched_at,
        timings=timings or AcquisitionTimings(),
        provenance=redact_provenance(provenance or RedactedProvenance()),
    )


def _validate_request(
    request: SourceRequest,
    capability: SourceCapability,
) -> AcquisitionFailure | None:
    if request.identity.dataset != "limits":
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONFIGURATION,
            f"{capability.source_id} cannot collect {request.identity.dataset}",
        )
    if request.source_id != capability.source_id:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONFIGURATION,
            f"source request {request.source_id} does not match adapter {capability.source_id}",
        )
    if request.capability_revision not in {None, capability.revision}:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONFIGURATION,
            f"source capability revision mismatch for {capability.source_id}",
        )
    return None


def _classify_fuyao_error(exc: Exception) -> tuple[AcquisitionFailureCategory, bool]:
    if isinstance(exc, FuyaoConfigurationError):
        return AcquisitionFailureCategory.CONFIGURATION, False
    if isinstance(exc, FuyaoPermissionError):
        return AcquisitionFailureCategory.PERMISSION, False
    if isinstance(exc, FuyaoNonTradingDayError):
        return AcquisitionFailureCategory.DATE_MISMATCH, False
    if isinstance(exc, FuyaoTransportError):
        return AcquisitionFailureCategory.NETWORK, True
    if isinstance(exc, FuyaoContractError):
        return AcquisitionFailureCategory.CONTRACT, False
    if isinstance(exc, FuyaoError):
        return AcquisitionFailureCategory.CONTRACT, False
    return AcquisitionFailureCategory.INTERNAL, False


def _result_parts(result: Any) -> tuple[dict[str, Any], LimitNormalizationResult | None]:
    payload = getattr(result, "payload", None)
    normalization = getattr(result, "normalization", None)
    if payload is None and isinstance(result, Mapping):
        if isinstance(result.get("payload"), Mapping):
            payload = result["payload"]
            normalization = result.get("normalization")
        else:
            payload = result
    if not isinstance(payload, Mapping):
        raise ValueError("limits source returned a non-object payload")
    if normalization is not None and not isinstance(normalization, LimitNormalizationResult):
        # Legacy fixtures use a duck-typed normalization result.  It is still
        # validated below and accepted by the typed committer during cutover.
        if not all(hasattr(normalization, name) for name in ("as_of", "actual_as_of", "rows")):
            raise ValueError("limits source returned invalid normalization evidence")
    return copy.deepcopy(dict(payload)), normalization


def _candidate_from_result(
    result: Any,
    request: SourceRequest,
    capability: SourceCapability,
    *,
    fetched_at: datetime,
    timings: AcquisitionTimings,
    provenance: RedactedProvenance,
    source_override: str | None = None,
    revision_override: str | None = None,
) -> CollectionCandidate | AcquisitionFailure:
    try:
        payload, normalization = _result_parts(result)
        raw_quality = payload.get("quality")
        if not isinstance(raw_quality, Mapping):
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.CONTRACT,
                f"{capability.source_id} payload is missing quality",
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )
        quality_as_of = str(raw_quality.get("asOf") or "")
        if quality_as_of != request.identity.as_of.isoformat():
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.DATE_MISMATCH,
                f"{capability.source_id} returned mismatched asOf {quality_as_of or 'missing'}",
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )
        actual_as_of = getattr(normalization, "actual_as_of", None) or request.identity.as_of
        if actual_as_of != request.identity.as_of:
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.DATE_MISMATCH,
                f"{capability.source_id} returned mismatched actual date {actual_as_of}",
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )
        status = str(raw_quality.get("status") or "missing")
        warnings = tuple(dict.fromkeys(str(value) for value in raw_quality.get("warnings") or () if str(value)))
        source = source_override or str(raw_quality.get("source") or raw_quality.get("provider") or capability.source_id)
        source_revision = revision_override or str(
            getattr(normalization, "source_revision", None)
            or raw_quality.get("sourceRevision")
            or raw_quality.get("providerRevision")
            or capability.revision
        )
        observations = int(raw_quality.get("observations") or 0)
        if status not in _SUCCESS_STATUSES:
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.INSUFFICIENT,
                str(raw_quality.get("warning") or f"{capability.source_id} quality is {status}"),
                fetched_at=fetched_at,
                timings=timings,
                provenance=replace(
                    provenance,
                    attributes={
                        **dict(provenance.attributes),
                        "qualityStatus": status,
                        "qualityWarnings": warnings,
                    },
                ),
            )
        available = tuple(
            field_name
            for field_name in (*_LIMIT_FIELDS, *_DETAIL_FIELDS)
            if payload.get(field_name) is not None
        )
        missing = tuple(field_name for field_name in capability.supported_fields if field_name not in available)
        field_availability = FieldAvailability(available=available, missing=missing)
        normalized_provenance = redact_provenance(
            replace(
                provenance,
                attributes={
                    **dict(provenance.attributes),
                    "dateEvidence": raw_quality.get("dateEvidence"),
                    "membershipComplete": getattr(normalization, "membership_complete", None),
                    "streakComplete": getattr(normalization, "streak_complete", None),
                    "excluded": getattr(normalization, "excluded", None),
                    "ruleVersion": getattr(normalization, "rule_version", None),
                    "datasetChecksum": getattr(normalization, "dataset_checksum", None),
                },
            )
        )
        fingerprint = evidence_fingerprint(
            {
                "dataset": request.identity.dataset,
                "requestedAsOf": request.identity.as_of.isoformat(),
                "actualAsOf": actual_as_of.isoformat(),
                "source": source,
                "sourceRevision": source_revision,
                "observations": observations,
                "provenance": {
                    "endpoint": normalized_provenance.endpoint,
                    "engine": normalized_provenance.engine,
                    **dict(normalized_provenance.attributes),
                },
            }
        )
        quality_extra = {
            str(key): copy.deepcopy(value)
            for key, value in raw_quality.items()
            if key
            not in {
                "dataset", "source", "provider", "status", "observations", "asOf",
                "warning", "warnings", "sourceRevision", "providerRevision",
            }
        }
        provider = str(raw_quality.get("provider") or source)
        quality = QualityMetadata(
            dataset=str(raw_quality.get("dataset") or "limit-pools"),
            source=source,
            provider=provider,
            status=status,
            observations=observations,
            as_of=request.identity.as_of,
            warning=str(raw_quality.get("warning")) if raw_quality.get("warning") else None,
            warnings=warnings,
            extra=quality_extra,
            source_revision=source_revision,
            fetched_at=fetched_at,
            field_availability=field_availability,
            timings=timings,
            evidence_fingerprint=fingerprint,
            provenance=normalized_provenance,
        )
        candidate_type = LimitsCollectionCandidate if normalization is not None else CollectionCandidate
        candidate_kwargs: dict[str, Any] = {}
        if normalization is not None:
            candidate_kwargs["normalization"] = normalization
        return candidate_type(
            identity=request.identity,
            payload=payload,
            source=source,
            status=status,
            observations=observations,
            warnings=warnings,
            settled=request.settled is not False,
            actual_as_of=actual_as_of,
            quality=quality,
            source_revision=source_revision,
            fetched_at=fetched_at,
            field_availability=field_availability,
            timings=timings,
            evidence_fingerprint=fingerprint,
            provenance=normalized_provenance,
            **candidate_kwargs,
        )
    except Exception as exc:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONTRACT,
            f"{capability.source_id} normalization failed: {type(exc).__name__}",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )


@dataclass(frozen=True, slots=True)
class EastmoneyLimitsSourceAdapter:
    """Adapter over the existing per-pool Eastmoney primary/delayed chain."""

    provider: LegacyLimitsProvider
    revision: str = EASTMONEY_LIMITS_SOURCE_REVISION
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=LIMITS_EASTMONEY_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            SourceCapability(
                source_id=self.source_id,
                provider="eastmoney",
                revision=self.revision,
                supports_historical=True,
                supported_fields=(*_LIMIT_FIELDS, *_DETAIL_FIELDS),
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        started = time.perf_counter()
        fetched_at = self.now()
        try:
            result = self.provider._fetch_eastmoney_limit_dataset(
                request.identity.as_of,
                strict=True,
            )
        except Exception as exc:
            category = (
                AcquisitionFailureCategory.DATE_MISMATCH
                if "date" in str(exc).lower()
                else AcquisitionFailureCategory.NETWORK
            )
            return _failure(
                request,
                self.capability,
                category,
                str(exc) or type(exc).__name__,
                retryable=category is AcquisitionFailureCategory.NETWORK,
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=RedactedProvenance(
                    endpoint="https://push2ex.eastmoney.com",
                    engine="requests",
                    attributes={"dateEvidenceKind": "response-or-request-parameter"},
                ),
            )
        return _candidate_from_result(
            result,
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=RedactedProvenance(
                endpoint="https://push2ex.eastmoney.com",
                engine="requests",
                attributes={"dateEvidenceKind": "response-or-request-parameter"},
            ),
        )


@dataclass(frozen=True, slots=True)
class LegacyLimitsSummarySourceAdapter:
    """Adapter for the pre-V1 aggregate summary path."""

    provider: LegacyLimitsProvider
    revision: str = LEGACY_LIMITS_SOURCE_REVISION
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=LIMITS_LEGACY_SUMMARY_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            SourceCapability(
                source_id=self.source_id,
                provider="legacy-limits",
                revision=self.revision,
                supports_historical=True,
                supported_fields=_LIMIT_FIELDS,
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        started = time.perf_counter()
        fetched_at = self.now()
        try:
            payload = self.provider.fetch_chapter01_limits(request.identity.as_of)
        except Exception as exc:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.NETWORK,
                str(exc) or type(exc).__name__,
                retryable=True,
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=RedactedProvenance(
                    endpoint="legacy-limits-summary",
                    engine="requests",
                    attributes={"dateEvidenceKind": "provider-payload"},
                ),
            )
        raw_quality = payload.get("quality") if isinstance(payload, Mapping) else None
        if not isinstance(raw_quality, Mapping):
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.CONTRACT,
                f"{self.source_id} payload is missing quality",
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            )
        source = str(
            raw_quality.get("source")
            or raw_quality.get("provider")
            or self.source_id
        )
        normalization = normalize_limit_pools(
            {
                "limit_up": None,
                "failed_limit_up": None,
                "limit_down": None,
            },
            as_of=request.identity.as_of,
            actual_as_of=request.identity.as_of,
            source=source,
            source_revision=self.revision,
            rule_version=LIMITS_RULE_VERSION,
            membership_complete=False,
            streak_complete=False,
        )
        return _candidate_from_result(
            _LimitsSourceResult(copy.deepcopy(dict(payload)), normalization),
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=RedactedProvenance(
                endpoint="legacy-limits-summary",
                engine="requests",
                attributes={"dateEvidenceKind": "provider-payload"},
            ),
        )


@dataclass(frozen=True, slots=True)
class FuyaoLimitsSourceAdapter:
    """Strict Fuyao dated-pool adapter with calendar and API-key gates."""

    provider: FuyaoLimitsProvider
    revision: str = LIMITS_SOURCE_REVISION
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=LIMITS_FUYAO_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            SourceCapability(
                source_id=self.source_id,
                provider="fuyao",
                revision=self.revision,
                supports_historical=True,
                supported_fields=(*_LIMIT_FIELDS, *_DETAIL_FIELDS),
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        started = time.perf_counter()
        fetched_at = self.now()
        provenance = RedactedProvenance(
            endpoint="https://fuyao.aicubes.cn/api/a-share/special-data/limit-up-pool",
            engine="requests",
            attributes={"dateEvidenceKind": "provider-calendar-and-request-parameter"},
        )
        calendar_confirmed = False
        try:
            client = self.provider.fuyao
            client.require_configured()
            trading_days = tuple(client.fetch_trading_days())
            calendar_confirmed = True
            if request.identity.as_of not in trading_days:
                raise FuyaoNonTradingDayError(
                    f"{request.identity.as_of.isoformat()} is not present in the Fuyao trading calendar"
                )
            dataset = client.fetch_limit_dataset(
                request.identity.as_of,
                trading_days=trading_days,
            )
            mapped = self.provider._map_fuyao_limit_dataset(dataset)
            fuyao_normalization = self.provider.normalize_limit_pools(
                mapped,
                request.identity.as_of,
                actual_as_of=request.identity.as_of,
                source="fuyao",
                source_revision=self.revision,
                rule_version=LIMITS_RULE_VERSION,
                membership_complete=True,
                streak_complete=all(
                    row.get("streak_days") is not None for row in mapped["limit_up"]
                ),
            )
            merged_pools, pool_quality, merge_warnings = self.provider._merge_limit_sources(
                fuyao_normalization,
                None,
            )
            wrapped_pools = {
                pool_name: _PoolRows(rows, as_of=request.identity.as_of, source="fuyao")
                for pool_name, rows in merged_pools.items()
            }
            membership_complete = all(
                quality.get("membershipComplete") is True
                for quality in pool_quality.values()
            )
            streak_complete = membership_complete and all(
                row.get("streak_days") is not None for row in merged_pools["limit_up"]
            )
            normalization = self.provider.normalize_limit_pools(
                wrapped_pools,
                request.identity.as_of,
                actual_as_of=request.identity.as_of,
                source="fuyao",
                source_revision=self.revision,
                rule_version=LIMITS_RULE_VERSION,
                membership_complete=membership_complete,
                streak_complete=streak_complete,
                pool_quality=pool_quality,
            )
            warnings = [_AUDIT_WARNING, *getattr(dataset, "warnings", ()), *merge_warnings]
            warnings = list(dict.fromkeys(str(value) for value in warnings if str(value)))
            payload = self.provider._limit_payload(
                request.identity.as_of,
                wrapped_pools,
                [],
                source="fuyao",
                provider_status="partial" if merge_warnings else "ok",
            )
            payload["quality"]["dateEvidence"] = "request-parameter"
            for warning in warnings:
                payload = self.provider._append_limit_warning(payload, warning)
            normalization = replace(
                normalization,
                warnings=tuple(dict.fromkeys((*normalization.warnings, *warnings))),
                dataset_checksum="",
            ).normalized()
            result = _LimitsSourceResult(payload, normalization)
        except Exception as exc:
            category, retryable = _classify_fuyao_error(exc)
            return _failure(
                request,
                self.capability,
                category,
                str(exc) or type(exc).__name__,
                retryable=retryable,
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=replace(
                    provenance,
                    attributes={
                        **dict(provenance.attributes),
                        "calendarConfirmed": calendar_confirmed,
                    },
                ),
            )
        return _candidate_from_result(
            result,
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=provenance,
            source_override=str(payload["quality"].get("source") or "fuyao"),
            revision_override=self.revision,
        )


@dataclass(frozen=True, slots=True)
class LimitsAcquisitionPlan:
    """Preserve limits formal/fallback/shadow ordering and feature gates."""

    adapters: SourceAdapterRegistry
    limits_v1_enabled: bool | Callable[[], bool] | None = None
    fuyao_is_enabled: Callable[[str], bool] = lambda _dataset: False
    fuyao_shadow_enabled: Callable[[str], bool] = lambda _dataset: False
    fuyao_revision: Callable[[str], str] = lambda _dataset: LIMITS_SOURCE_REVISION
    market_today: Callable[[], date] = lambda: datetime.now().date()
    is_settled: Callable[[date], bool] = lambda _as_of: True
    previous_session: Callable[[date], date | None] | None = None
    dataset_id: str = field(init=False, default="limits")
    plan_id: str = field(init=False, default="limits-acquisition-v1")
    steps: tuple[AcquisitionPlanStep, ...] = field(init=False)

    def __post_init__(self) -> None:
        referenced = [LIMITS_LEGACY_SUMMARY_SOURCE_ID, LIMITS_EASTMONEY_SOURCE_ID, LIMITS_FUYAO_SOURCE_ID]
        steps = tuple(
            AcquisitionPlanStep(
                source_id,
                role=role,
                capability_revision=self.adapters.get(source_id).capability.revision,
            )
            for source_id, role in (
                (LIMITS_FUYAO_SOURCE_ID, "formal"),
                (LIMITS_EASTMONEY_SOURCE_ID, "fallback"),
                (LIMITS_LEGACY_SUMMARY_SOURCE_ID, "formal"),
            )
            if source_id in self.adapters
        )
        if not steps or not all(source_id in self.adapters for source_id in referenced):
            missing = tuple(source_id for source_id in referenced if source_id not in self.adapters)
            raise ValueError(f"limits acquisition plan references missing adapters: {', '.join(missing)}")
        object.__setattr__(self, "steps", steps)
        self.adapters.validate_references((self,))

    def _detail_enabled(self) -> bool:
        value = limit_v1_enabled() if self.limits_v1_enabled is None else self.limits_v1_enabled
        return bool(value() if callable(value) else value)

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        if identity.dataset != self.dataset_id:
            failure = AcquisitionFailure(
                AcquisitionFailureCategory.CONFIGURATION,
                f"plan {self.plan_id} cannot collect {identity.dataset}",
                requested_as_of=identity.as_of,
            )
            return CollectionOutcome(identity=identity, state=CollectionTaskState.FAILED_MISSING, warning=failure.message, failure=failure)

        detail_enabled = self._detail_enabled()
        attempts: list[AttemptEvidence] = []
        warnings: list[str] = []
        formal: CollectionCandidate | None = None
        terminal: AcquisitionFailure | None = None

        ordered = (
            (LIMITS_FUYAO_SOURCE_ID, "formal"),
            (LIMITS_EASTMONEY_SOURCE_ID, "fallback"),
        ) if detail_enabled else ((LIMITS_LEGACY_SUMMARY_SOURCE_ID, "formal"),)

        for source_id, role in ordered:
            result = self._attempt(identity, source_id, role=role, attempts=attempts)
            if isinstance(result, AcquisitionFailure):
                terminal = result
                warnings.append(result.message)
                # Missing Fuyao credentials are a deliberate gate and must not
                # be silently turned into an Eastmoney success.
                if source_id == LIMITS_FUYAO_SOURCE_ID and result.category in {
                    AcquisitionFailureCategory.CONFIGURATION,
                    AcquisitionFailureCategory.DATE_MISMATCH,
                }:
                    break
                continue
            formal = result
            break

        if formal is None:
            failure = terminal or AcquisitionFailure(
                AcquisitionFailureCategory.INSUFFICIENT,
                "limits acquisition produced no candidate",
                requested_as_of=identity.as_of,
            )
            return CollectionOutcome(
                identity=identity,
                state=CollectionTaskState.FAILED_MISSING,
                warning="; ".join(dict.fromkeys(warnings)) or failure.message,
                failure=failure,
                attempts=tuple(attempts),
            )

        if detail_enabled and formal.source.startswith("fuyao"):
            cross_check = self._attempt(
                identity,
                LIMITS_EASTMONEY_SOURCE_ID,
                role="formal",
                attempts=attempts,
            )
            if isinstance(cross_check, AcquisitionFailure):
                warning = f"Eastmoney cross-check unavailable: {cross_check.message}"
                attempts[-1] = replace(attempts[-1], warning=warning)
                warnings.append(warning)
                formal = self._with_warning(formal, warning, status="partial")
            else:
                formal = self._merge_detail_candidates(formal, cross_check)

        if detail_enabled and formal.source.startswith("eastmoney") and warnings:
            primary_warning = (
                "Fuyao primary source unavailable; using Eastmoney fallback: "
                f"{warnings[0]}"
            )
            warnings[0] = primary_warning
            attempts[0] = replace(attempts[0], warning=primary_warning)
            formal = self._eastmoney_fallback_candidate(
                formal,
                primary_warning,
                calendar_confirmed=bool(
                    attempts[0].provenance.attributes.get("calendarConfirmed")
                ),
            )

        if (
            not detail_enabled
            and self.fuyao_shadow_enabled(self.dataset_id)
            and not self.fuyao_is_enabled(self.dataset_id)
            and identity.as_of == self.market_today()
            and self.is_settled(identity.as_of)
        ):
            shadow = self._attempt(identity, LIMITS_FUYAO_SOURCE_ID, role="shadow", attempts=attempts)
            if isinstance(shadow, CollectionCandidate):
                comparison = compare_shadow(
                    self.dataset_id,
                    formal.payload,
                    shadow.payload,
                    formal_revision=formal.source_revision or formal.source,
                    shadow_revision=self.fuyao_revision(self.dataset_id),
                    as_of=identity.as_of,
                )
                attempts[-1] = replace(
                    attempts[-1],
                    warning=(
                        f"扶摇 shadow: {comparison.get('status')}"
                        if comparison.get("status") not in {"match", "degraded"}
                        else None
                    ),
                    provenance=replace(
                        attempts[-1].provenance,
                        attributes={**dict(attempts[-1].provenance.attributes), "comparison": comparison},
                    ),
                )
                if comparison.get("status") not in {"match", "degraded"}:
                    warnings.append(f"扶摇 shadow: {comparison.get('status')}")
            else:
                attempts[-1] = replace(attempts[-1], warning=f"扶摇 shadow 不可用：{shadow.message}")
                warnings.append(f"扶摇 shadow 不可用：{shadow.message}")

        if isinstance(formal, LimitsCollectionCandidate) and self.previous_session is not None:
            formal = replace(formal, previous_as_of=self.previous_session(identity.as_of))
        combined_warnings = tuple(dict.fromkeys((*formal.warnings, *warnings)))
        formal = replace(formal, warnings=combined_warnings)
        state = CollectionTaskState.PARTIAL if formal.status in {"partial", "fallback", "fallback-derived", "degraded"} or warnings else CollectionTaskState.SUCCESS
        return CollectionOutcome(
            identity=identity,
            state=state,
            candidate=formal,
            warning="; ".join(combined_warnings) or None,
            attempts=tuple(attempts),
        )

    def _merge_detail_candidates(
        self,
        fuyao: CollectionCandidate,
        eastmoney: CollectionCandidate,
    ) -> LimitsCollectionCandidate:
        if not isinstance(fuyao, LimitsCollectionCandidate) or fuyao.normalization is None:
            raise ValueError("Fuyao limits candidate is missing normalization")
        if not isinstance(eastmoney, LimitsCollectionCandidate) or eastmoney.normalization is None:
            raise ValueError("Eastmoney limits candidate is missing normalization")
        provider = self.adapters.get(LIMITS_FUYAO_SOURCE_ID).provider
        merged_pools, pool_quality, merge_warnings = provider._merge_limit_sources(
            fuyao.normalization,
            eastmoney.normalization,
        )
        source = (
            "fuyao+eastmoney"
            if any(item.get("source") == "fuyao+eastmoney" for item in pool_quality.values())
            else "fuyao"
        )
        wrapped_pools = {
            pool_name: _PoolRows(rows, as_of=fuyao.identity.as_of, source=source)
            for pool_name, rows in merged_pools.items()
        }
        membership_complete = all(
            item.get("membershipComplete") is True for item in pool_quality.values()
        )
        streak_complete = membership_complete and all(
            row.get("streak_days") is not None for row in merged_pools["limit_up"]
        )
        normalization = normalize_limit_pools(
            wrapped_pools,
            as_of=fuyao.identity.as_of,
            actual_as_of=fuyao.identity.as_of,
            source=source,
            source_revision="fuyao-eastmoney-union-v1",
            rule_version=LIMITS_RULE_VERSION,
            membership_complete=membership_complete,
            streak_complete=streak_complete,
            pool_quality=pool_quality,
        )
        audit_warnings = tuple(
            warning for warning in fuyao.warnings if warning != "Eastmoney cross-check unavailable"
        )
        all_warnings = tuple(dict.fromkeys((*audit_warnings, *merge_warnings)))
        normalization = replace(
            normalization,
            warnings=tuple(dict.fromkeys((*normalization.warnings, *all_warnings))),
            dataset_checksum="",
        ).normalized()
        payload = provider._limit_payload(
            fuyao.identity.as_of,
            wrapped_pools,
            list(merge_warnings),
            source=source,
            provider_status="partial" if merge_warnings else "ok",
        )
        payload["quality"]["dateEvidence"] = "request-parameter"
        for warning in audit_warnings:
            payload = provider._append_limit_warning(payload, warning)
        result = _candidate_from_result(
            _LimitsSourceResult(payload, normalization),
            SourceRequest(
                identity=fuyao.identity,
                source_id=LIMITS_FUYAO_SOURCE_ID,
                capability_revision=self.adapters.get(LIMITS_FUYAO_SOURCE_ID).capability.revision,
                current_market_date=self.market_today(),
                settled=self.is_settled(fuyao.identity.as_of),
            ),
            self.adapters.get(LIMITS_FUYAO_SOURCE_ID).capability,
            fetched_at=fuyao.fetched_at or _utc_now(),
            timings=AcquisitionTimings(
                total_ms=sum(
                    value for value in (fuyao.timings.total_ms, eastmoney.timings.total_ms) if value is not None
                )
            ),
            provenance=replace(
                fuyao.provenance,
                attributes={
                    **dict(fuyao.provenance.attributes),
                    "crossCheckSource": eastmoney.source,
                    "crossCheckFingerprint": eastmoney.evidence_fingerprint,
                },
            ),
            source_override=source,
            revision_override="fuyao-eastmoney-union-v1",
        )
        if not isinstance(result, LimitsCollectionCandidate):
            raise ValueError("merged limits evidence did not produce a typed candidate")
        return result

    @staticmethod
    def _with_warning(
        candidate: CollectionCandidate,
        warning: str,
        *,
        status: str,
    ) -> CollectionCandidate:
        payload = copy.deepcopy(dict(candidate.payload))
        quality_payload = payload.get("quality")
        if not isinstance(quality_payload, dict):
            raise ValueError("limits payload is missing quality")
        quality_warnings = list(
            dict.fromkeys([*(quality_payload.get("warnings") or []), warning])
        )
        quality_payload["warnings"] = quality_warnings
        quality_payload["warning"] = "; ".join(quality_warnings)
        quality_payload["status"] = status
        quality = candidate.quality
        if quality is not None:
            quality = replace(
                quality,
                status=status,
                warning=quality_payload["warning"],
                warnings=tuple(quality_warnings),
            )
        return replace(
            candidate,
            payload=payload,
            status=status,
            warnings=tuple(quality_warnings),
            quality=quality,
        )

    def _eastmoney_fallback_candidate(
        self,
        candidate: CollectionCandidate,
        warning: str,
        *,
        calendar_confirmed: bool,
    ) -> CollectionCandidate:
        if not isinstance(candidate, LimitsCollectionCandidate) or candidate.normalization is None:
            raise ValueError("Eastmoney fallback is missing normalization")
        payload = copy.deepcopy(dict(candidate.payload))
        count_fields = {
            "limit_up": "limitUpCount",
            "failed_limit_up": "failedLimitUpCount",
            "limit_down": "limitDownCount",
        }
        unconfirmed_empty = {
            pool_name
            for pool_name, field_name in count_fields.items()
            if not calendar_confirmed and payload.get(field_name) == 0
        }
        calendar_warning = (
            "Fuyao trading calendar was unavailable; Eastmoney empty pools remain unconfirmed"
            if unconfirmed_empty
            else None
        )
        for pool_name in unconfirmed_empty:
            payload[count_fields[pool_name]] = None
        if {"limit_up", "failed_limit_up"} & unconfirmed_empty:
            payload["failedLimitUpRatio"] = None
        if unconfirmed_empty:
            payload["state"] = "insufficient"
        status = "partial" if unconfirmed_empty else "fallback"
        provider = self.adapters.get(LIMITS_FUYAO_SOURCE_ID).provider
        payload = provider._append_limit_warning(payload, warning, status=status)
        if calendar_warning:
            payload = provider._append_limit_warning(payload, calendar_warning)
        pool_quality = {
            pool_name: {
                **dict(item),
                "status": "insufficient" if pool_name in unconfirmed_empty else "fallback",
                "membershipComplete": False if pool_name in unconfirmed_empty else item.get("membershipComplete"),
                "warnings": list(dict.fromkeys([*(item.get("warnings") or []), warning, *([calendar_warning] if calendar_warning else [])])),
            }
            for pool_name, item in dict(candidate.normalization.pool_quality or {}).items()
        }
        normalization = replace(
            candidate.normalization,
            warnings=tuple(dict.fromkeys((*candidate.normalization.warnings, warning, *([calendar_warning] if calendar_warning else [])))),
            membership_complete=all(item.get("membershipComplete") is True for item in pool_quality.values()),
            pool_quality=pool_quality,
            dataset_checksum="",
        ).normalized()
        raw_quality = payload["quality"]
        warnings = tuple(str(value) for value in raw_quality.get("warnings") or ())
        quality = replace(
            candidate.quality,
            status=status,
            warning=str(raw_quality.get("warning")) if raw_quality.get("warning") else None,
            warnings=warnings,
            source_revision=normalization.source_revision,
        ) if candidate.quality is not None else None
        return replace(
            candidate,
            payload=payload,
            status=status,
            warnings=warnings,
            quality=quality,
            normalization=normalization,
        )

    def _attempt(
        self,
        identity: DatasetDate,
        source_id: str,
        *,
        role: str,
        attempts: list[AttemptEvidence],
    ) -> CollectionCandidate | AcquisitionFailure:
        adapter = self.adapters.get(source_id)
        result = adapter.acquire(
            SourceRequest(
                identity=identity,
                source_id=source_id,
                role=role,
                capability_revision=adapter.capability.revision,
                current_market_date=self.market_today(),
                settled=self.is_settled(identity.as_of),
            )
        )
        if isinstance(result, AcquisitionFailure):
            attempts.append(
                AttemptEvidence(
                    role=role,
                    provider=adapter.capability.provider,
                    source=source_id,
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
                role=role,
                provider=result.quality.provider if result.quality else adapter.capability.provider,
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


__all__ = [
    "EASTMONEY_LIMITS_SOURCE_ID",
    "EASTMONEY_LIMITS_SOURCE_REVISION",
    "FUYAO_LIMITS_SOURCE_ID",
    "LEGACY_LIMITS_SUMMARY_SOURCE_ID",
    "LEGACY_LIMITS_SOURCE_REVISION",
    "LIMITS_EASTMONEY_SOURCE_ID",
    "LIMITS_FUYAO_SOURCE_ID",
    "LIMITS_LEGACY_SUMMARY_SOURCE_ID",
    "LIMITS_RULE_VERSION",
    "LimitsCollectionCandidate",
    "LimitsAcquisitionPlan",
    "EastmoneyLimitsSourceAdapter",
    "FuyaoLimitsSourceAdapter",
    "LegacyLimitsSummarySourceAdapter",
]
