"""Normalized breadth source adapters and deterministic acquisition policy."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo

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
from .fuyao.market import (
    FuyaoMarketConfigurationError,
    FuyaoMarketContractError,
    FuyaoMarketError,
    FuyaoMarketPermissionError,
    FuyaoMarketRateLimitError,
    FuyaoMarketResult,
    FuyaoMarketTransportError,
)
from .provenance import evidence_fingerprint, redact_provenance
from .shadow import compare_shadow
from .tdx.daily_package import TDXDailyPackageError, TDXStockUniverseError


FUYAO_BREADTH_SOURCE_ID = "breadth-fuyao"
TDX_BREADTH_SOURCE_ID = "breadth-tdx-daily-package"
EASTMONEY_BREADTH_SOURCE_ID = "breadth-eastmoney-clist-delay"

_BREADTH_FIELDS = (
    "advanceCount",
    "declineCount",
    "flatCount",
    "validCount",
    "advanceRatio",
    "medianReturn",
    "state",
)
_SUCCESS_STATUSES = frozenset({"ok", "fallback", "fallback-derived", "partial"})
_HISTORICAL_WARNING = "该数据源仅提供最新市场快照，历史日期不使用当前数据回填"
_UNSETTLED_WARNING = "最新市场快照尚未结算，不能作为盘后市场广度证据"
_SHANGHAI_ZONE = ZoneInfo("Asia/Shanghai")


class FuyaoBreadthClient(Protocol):
    def fetch_breadth(self, as_of: date) -> FuyaoMarketResult: ...


class LegacyBreadthProvider(Protocol):
    def _fetch_tdx_breadth(
        self,
        as_of: date,
        warnings: list[str],
    ) -> dict[str, Any]: ...

    def _fetch_eastmoney_breadth_fallback(
        self,
        as_of: date,
        primary_warning: str,
    ) -> dict[str, Any]: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _market_today() -> date:
    return datetime.now(_SHANGHAI_ZONE).date()


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
        message=message,
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
    if request.identity.dataset != "breadth":
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
    if capability.latest_only and request.current_market_date != request.identity.as_of:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.DATE_MISMATCH,
            _HISTORICAL_WARNING,
            provenance=RedactedProvenance(
                attributes={"dateEvidenceKind": "latest-only"}
            ),
        )
    if capability.latest_only and request.settled is not True:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.INSUFFICIENT,
            _UNSETTLED_WARNING,
            provenance=RedactedProvenance(
                attributes={"dateEvidenceKind": "latest-only"}
            ),
        )
    return None


def _quality_candidate(
    payload: Mapping[str, Any],
    request: SourceRequest,
    capability: SourceCapability,
    *,
    fetched_at: datetime,
    timings: AcquisitionTimings,
    provenance: RedactedProvenance,
) -> CollectionCandidate | AcquisitionFailure:
    copied_payload = copy.deepcopy(dict(payload))
    raw_quality = copied_payload.get("quality")
    if not isinstance(raw_quality, Mapping):
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONTRACT,
            f"{capability.source_id} breadth payload is missing quality",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )
    status = str(raw_quality.get("status") or "missing")
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
    source_revision = str(
        raw_quality.get("sourceRevision")
        or raw_quality.get("providerRevision")
        or capability.revision
    )
    if request.capability_revision is not None and source_revision != request.capability_revision:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONFIGURATION,
            f"{capability.source_id} returned capability revision {source_revision}",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )
    warnings = tuple(
        dict.fromkeys(
            str(value)
            for value in raw_quality.get("warnings") or ()
            if str(value)
        )
    )
    warning = str(raw_quality.get("warning")) if raw_quality.get("warning") else None
    observations = int(raw_quality.get("observations") or 0)
    source = str(raw_quality.get("source") or raw_quality.get("provider") or "none")
    provider = str(raw_quality.get("provider") or source)
    if status not in _SUCCESS_STATUSES:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.INSUFFICIENT,
            f"{capability.source_id} breadth quality is {status}",
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

    missing_fields = tuple(
        field_name
        for field_name in _BREADTH_FIELDS
        if copied_payload.get(field_name) is None
    )
    if missing_fields:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.INSUFFICIENT,
            f"{capability.source_id} breadth payload is missing required fields: "
            f"{', '.join(missing_fields)}",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )
    available_fields = tuple(
        field_name
        for field_name in _BREADTH_FIELDS
        if copied_payload.get(field_name) is not None
    )
    field_availability = FieldAvailability(
        available=available_fields,
        missing=missing_fields,
    )
    quality_extra = {
        str(key): copy.deepcopy(value)
        for key, value in raw_quality.items()
        if key
        not in {
            "dataset",
            "source",
            "provider",
            "status",
            "observations",
            "asOf",
            "warning",
            "warnings",
            "sourceRevision",
            "providerRevision",
        }
    }
    normalized_provenance = redact_provenance(provenance)
    fingerprint = evidence_fingerprint(
        {
            "dataset": request.identity.dataset,
            "requestedAsOf": request.identity.as_of.isoformat(),
            "actualAsOf": quality_as_of,
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
    quality = QualityMetadata(
        dataset=str(raw_quality.get("dataset") or "market-breadth"),
        source=source,
        provider=provider,
        status=status,
        observations=observations,
        as_of=request.identity.as_of,
        warning=warning,
        warnings=warnings,
        extra=quality_extra,
        source_revision=source_revision,
        fetched_at=fetched_at,
        field_availability=field_availability,
        timings=timings,
        evidence_fingerprint=fingerprint,
        provenance=normalized_provenance,
    )
    return CollectionCandidate(
        identity=request.identity,
        payload=copied_payload,
        source=source,
        status=status,
        observations=observations,
        warnings=warnings,
        settled=request.settled is True,
        actual_as_of=request.identity.as_of,
        quality=quality,
        source_revision=source_revision,
        fetched_at=fetched_at,
        field_availability=field_availability,
        timings=timings,
        evidence_fingerprint=fingerprint,
        provenance=normalized_provenance,
    )


def _normalize_payload(
    payload: Mapping[str, Any],
    request: SourceRequest,
    capability: SourceCapability,
    *,
    fetched_at: datetime,
    timings: AcquisitionTimings,
    provenance: RedactedProvenance,
) -> CollectionCandidate | AcquisitionFailure:
    try:
        return _quality_candidate(
            payload,
            request,
            capability,
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )
    except Exception as exc:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONTRACT,
            f"{capability.source_id} breadth normalization failed: {type(exc).__name__}",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )


@dataclass(frozen=True, slots=True)
class FuyaoBreadthSourceAdapter:
    client: FuyaoBreadthClient
    revision: str = "fuyao-market-v2"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=FUYAO_BREADTH_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            SourceCapability(
                source_id=self.source_id,
                provider="fuyao",
                revision=self.revision,
                supports_historical=False,
                latest_only=True,
                supported_fields=_BREADTH_FIELDS,
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        started = time.perf_counter()
        fetched_at = self.now()
        try:
            result = self.client.fetch_breadth(request.identity.as_of)
        except Exception as exc:
            timings = AcquisitionTimings(total_ms=_milliseconds(started))
            category, retryable = _classify_fuyao_error(exc)
            return _failure(
                request,
                self.capability,
                category,
                str(exc) or type(exc).__name__,
                retryable=retryable,
                fetched_at=fetched_at,
                timings=timings,
                provenance=RedactedProvenance(
                    endpoint="/api/a-share/prices/snapshot",
                    engine="requests",
                    attributes={"dateEvidenceKind": "latest-only"},
                ),
            )
        if not isinstance(result, FuyaoMarketResult):
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.CONTRACT,
                "Fuyao breadth adapter returned an invalid result",
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            )
        return _normalize_payload(
            result.as_dict(),
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=RedactedProvenance(
                endpoint=str(result.quality.get("endpoint") or "/api/a-share/prices/snapshot"),
                engine="requests",
                attributes={"dateEvidenceKind": "latest-only"},
            ),
        )


@dataclass(frozen=True, slots=True)
class TDXBreadthSourceAdapter:
    provider: LegacyBreadthProvider
    revision: str = "tdx-breadth-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=TDX_BREADTH_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            SourceCapability(
                source_id=self.source_id,
                provider="tdx",
                revision=self.revision,
                supports_historical=True,
                latest_only=False,
                supported_fields=_BREADTH_FIELDS,
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        started = time.perf_counter()
        fetched_at = self.now()
        try:
            payload = self.provider._fetch_tdx_breadth(request.identity.as_of, [])
        except TDXStockUniverseError as exc:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.INSUFFICIENT,
                f"通达信普通 A 股 universe 不足：{exc}",
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=RedactedProvenance(
                    engine="tdx-package",
                    attributes={"dateEvidenceKind": "package"},
                ),
            )
        except TDXDailyPackageError as exc:
            category = (
                AcquisitionFailureCategory.DATE_MISMATCH
                if "date" in str(exc).lower() or "日期" in str(exc)
                else AcquisitionFailureCategory.INSUFFICIENT
            )
            return _failure(
                request,
                self.capability,
                category,
                f"通达信盘后包不可用：{exc}",
                retryable=bool(getattr(exc, "retryable", False)),
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=RedactedProvenance(
                    engine="tdx-package",
                    attributes={"dateEvidenceKind": "package"},
                ),
            )
        except Exception as exc:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.INTERNAL,
                f"通达信盘后包不可用：{exc}",
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=RedactedProvenance(
                    engine="tdx-package",
                    attributes={"dateEvidenceKind": "package"},
                ),
            )
        return _normalize_payload(
            payload,
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=RedactedProvenance(
                engine="tdx-package",
                attributes={"dateEvidenceKind": "package"},
            ),
        )


@dataclass(frozen=True, slots=True)
class EastmoneyBreadthSourceAdapter:
    provider: LegacyBreadthProvider
    revision: str = "eastmoney-breadth-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=EASTMONEY_BREADTH_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            SourceCapability(
                source_id=self.source_id,
                provider="eastmoney",
                revision=self.revision,
                supports_historical=False,
                latest_only=True,
                supported_fields=_BREADTH_FIELDS,
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        primary_warning = str(request.params.get("primary_warning") or "")
        if not primary_warning:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.CONFIGURATION,
                "Eastmoney breadth fallback requires primary warning evidence",
            )
        started = time.perf_counter()
        fetched_at = self.now()
        try:
            payload = self.provider._fetch_eastmoney_breadth_fallback(
                request.identity.as_of,
                primary_warning,
            )
        except Exception as exc:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.NETWORK,
                f"东方财富市场广度不可用：{exc}",
                retryable=True,
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=RedactedProvenance(
                    endpoint="https://push2delay.eastmoney.com/api/qt/clist/get",
                    engine="requests",
                    attributes={"dateEvidenceKind": "latest-only"},
                ),
            )
        return _normalize_payload(
            payload,
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=RedactedProvenance(
                endpoint="https://push2delay.eastmoney.com/api/qt/clist/get",
                engine="requests",
                attributes={"dateEvidenceKind": "latest-only"},
            ),
        )


@dataclass(frozen=True, slots=True)
class BreadthAcquisitionPlan:
    """Preserve the approved Fuyao -> TDX -> Eastmoney breadth policy."""

    adapters: SourceAdapterRegistry
    fuyao_is_enabled: Callable[[str], bool]
    fuyao_shadow_enabled: Callable[[str], bool]
    fuyao_revision: Callable[[str], str]
    tdx_is_enabled: Callable[[], bool]
    market_today: Callable[[], date] = _market_today
    is_settled: Callable[[date], bool] = lambda _as_of: True
    dataset_id: str = field(init=False, default="breadth")
    plan_id: str = field(init=False, default="breadth-acquisition-v1")
    steps: tuple[AcquisitionPlanStep, ...] = field(init=False)

    def __post_init__(self) -> None:
        steps = (
            AcquisitionPlanStep(
                FUYAO_BREADTH_SOURCE_ID,
                role="formal",
                capability_revision=self.adapters.get(
                    FUYAO_BREADTH_SOURCE_ID
                ).capability.revision,
            ),
            AcquisitionPlanStep(
                TDX_BREADTH_SOURCE_ID,
                role="fallback",
                capability_revision=self.adapters.get(
                    TDX_BREADTH_SOURCE_ID
                ).capability.revision,
            ),
            AcquisitionPlanStep(
                EASTMONEY_BREADTH_SOURCE_ID,
                role="fallback",
                capability_revision=self.adapters.get(
                    EASTMONEY_BREADTH_SOURCE_ID
                ).capability.revision,
            ),
            AcquisitionPlanStep(
                FUYAO_BREADTH_SOURCE_ID,
                role="shadow",
                capability_revision=self.adapters.get(
                    FUYAO_BREADTH_SOURCE_ID
                ).capability.revision,
            ),
        )
        object.__setattr__(self, "steps", steps)
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

        current_market_date = self.market_today()
        settled = self.is_settled(identity.as_of)
        attempts: list[AttemptEvidence] = []
        formal_candidate: CollectionCandidate | None = None
        fuyao_warning: str | None = None
        tdx_failure: AcquisitionFailure | None = None
        terminal_failure: AcquisitionFailure | None = None

        if self.fuyao_is_enabled(self.dataset_id) and identity.as_of == current_market_date:
            result = self._attempt(
                identity,
                FUYAO_BREADTH_SOURCE_ID,
                role="formal",
                capability_revision=self.fuyao_revision(self.dataset_id),
                current_market_date=current_market_date,
                settled=settled,
                attempts=attempts,
            )
            if isinstance(result, CollectionCandidate):
                formal_candidate = result
            else:
                terminal_failure = result
                quality_status = result.provenance.attributes.get("qualityStatus")
                if quality_status:
                    fuyao_warning = (
                        f"扶摇采集质量为 {quality_status}，已回退现有 provider"
                    )
                else:
                    fuyao_warning = f"扶摇采集失败，已回退现有 provider：{result.message}"
                attempts[-1] = replace(attempts[-1], warning=fuyao_warning)

        if formal_candidate is None and self.tdx_is_enabled():
            result = self._attempt(
                identity,
                TDX_BREADTH_SOURCE_ID,
                role="fallback",
                current_market_date=current_market_date,
                settled=settled,
                attempts=attempts,
            )
            if isinstance(result, CollectionCandidate):
                formal_candidate = result
            else:
                tdx_failure = terminal_failure = result

        if formal_candidate is None and identity.as_of == current_market_date:
            primary_warning = (
                f"{tdx_failure.message}；已降级到东方财富市场广度涨跌幅排序分页统计"
                if tdx_failure is not None
                else "市场广度直接使用涨跌幅排序分页统计，未请求名义全 A 主快照"
            )
            result = self._attempt(
                identity,
                EASTMONEY_BREADTH_SOURCE_ID,
                role="fallback",
                current_market_date=current_market_date,
                settled=settled,
                params={"primary_warning": primary_warning},
                attempts=attempts,
            )
            if isinstance(result, CollectionCandidate):
                formal_candidate = result
            else:
                terminal_failure = result

        if formal_candidate is None:
            historical_warning = (
                _HISTORICAL_WARNING
                if identity.as_of != current_market_date
                else None
            )
            warning_parts = []
            if tdx_failure is not None:
                warning_parts.append(tdx_failure.message)
            if terminal_failure is not None and terminal_failure is not tdx_failure:
                warning_parts.append(terminal_failure.message)
            if historical_warning:
                warning_parts.append(historical_warning)
            warning = "；".join(dict.fromkeys(warning_parts))
            if fuyao_warning:
                warning = "; ".join(value for value in (warning, fuyao_warning) if value)
            failure = terminal_failure or AcquisitionFailure(
                AcquisitionFailureCategory.DATE_MISMATCH
                if historical_warning
                else AcquisitionFailureCategory.INSUFFICIENT,
                historical_warning or "breadth acquisition produced no candidate",
                requested_as_of=identity.as_of,
            )
            return CollectionOutcome(
                identity=identity,
                state=CollectionTaskState.FAILED_MISSING,
                warning=warning or failure.message,
                failure=failure,
                attempts=tuple(attempts),
            )

        warning = formal_candidate.quality.warning if formal_candidate.quality else None
        if fuyao_warning:
            warning = "; ".join(value for value in (warning, fuyao_warning) if value)

        if (
            not self.fuyao_is_enabled(self.dataset_id)
            and self.fuyao_shadow_enabled(self.dataset_id)
            and identity.as_of == current_market_date
        ):
            shadow = self._attempt(
                identity,
                FUYAO_BREADTH_SOURCE_ID,
                role="shadow",
                capability_revision=self.fuyao_revision(self.dataset_id),
                current_market_date=current_market_date,
                settled=settled,
                attempts=attempts,
            )
            if isinstance(shadow, CollectionCandidate):
                comparison = compare_shadow(
                    self.dataset_id,
                    formal_candidate.payload,
                    shadow.payload,
                    formal_revision=formal_candidate.source,
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
                        attributes={
                            **dict(attempts[-1].provenance.attributes),
                            "comparison": comparison,
                        },
                    ),
                )
                if comparison.get("status") not in {"match", "degraded"}:
                    warning = "; ".join(
                        value
                        for value in (
                            warning,
                            f"扶摇 shadow: {comparison.get('status')}",
                        )
                        if value
                    )
            else:
                shadow_warning = (
                    f"扶摇 shadow: {shadow.provenance.attributes.get('qualityStatus')}"
                    if shadow.provenance.attributes.get("qualityStatus")
                    else f"扶摇 shadow 不可用：{shadow.message}"
                )
                attempts[-1] = replace(attempts[-1], warning=shadow_warning)
                warning = "; ".join(
                    value for value in (warning, shadow_warning) if value
                )

        state = (
            CollectionTaskState.PARTIAL
            if formal_candidate.status in {"partial", "fallback-derived"}
            else CollectionTaskState.SUCCESS
        )
        return CollectionOutcome(
            identity=identity,
            state=state,
            candidate=formal_candidate,
            warning=warning,
            attempts=tuple(attempts),
        )

    def _attempt(
        self,
        identity: DatasetDate,
        source_id: str,
        *,
        role: str,
        current_market_date: date,
        settled: bool,
        attempts: list[AttemptEvidence],
        capability_revision: str | None = None,
        params: Mapping[str, object] | None = None,
    ) -> CollectionCandidate | AcquisitionFailure:
        adapter = self.adapters.get(source_id)
        result = adapter.acquire(
            SourceRequest(
                identity=identity,
                source_id=source_id,
                role=role,
                params=params or {},
                capability_revision=capability_revision
                or adapter.capability.revision,
                current_market_date=current_market_date,
                settled=settled,
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
                provider=(
                    result.quality.provider
                    if result.quality is not None
                    else adapter.capability.provider
                ),
                source=result.source,
                source_revision=result.source_revision
                or adapter.capability.revision,
                requested_as_of=identity.as_of,
                actual_as_of=result.actual_as_of,
                timings=result.timings,
                provenance=result.provenance,
                evidence_fingerprint=result.evidence_fingerprint,
            )
        )
        return result


def _classify_fuyao_error(
    exc: Exception,
) -> tuple[AcquisitionFailureCategory, bool]:
    if isinstance(exc, FuyaoMarketConfigurationError):
        return AcquisitionFailureCategory.CONFIGURATION, False
    if isinstance(exc, FuyaoMarketPermissionError):
        return AcquisitionFailureCategory.PERMISSION, False
    if isinstance(exc, FuyaoMarketRateLimitError):
        return AcquisitionFailureCategory.RATE_LIMIT, True
    if isinstance(exc, FuyaoMarketTransportError):
        return AcquisitionFailureCategory.NETWORK, True
    if isinstance(exc, FuyaoMarketContractError):
        return AcquisitionFailureCategory.CONTRACT, False
    if isinstance(exc, FuyaoMarketError):
        return AcquisitionFailureCategory.CONTRACT, False
    return AcquisitionFailureCategory.INTERNAL, False


def _milliseconds(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = [
    "BreadthAcquisitionPlan",
    "EASTMONEY_BREADTH_SOURCE_ID",
    "EastmoneyBreadthSourceAdapter",
    "FUYAO_BREADTH_SOURCE_ID",
    "FuyaoBreadthSourceAdapter",
    "TDX_BREADTH_SOURCE_ID",
    "TDXBreadthSourceAdapter",
]
