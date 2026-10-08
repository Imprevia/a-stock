"""Normalized active-direction adapters and deterministic fallback policy."""

from __future__ import annotations

import copy
import math
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
from .provenance import evidence_fingerprint, redact_provenance
from .tdx.daily_package import (
    TDX_UPSTREAM_REVISION,
    TDXDailyPackageError,
    TDXStockUniverseError,
)


EASTMONEY_ACTIVE_DIRECTION_PRIMARY_SOURCE_ID = "active-direction-eastmoney-primary"
EASTMONEY_ACTIVE_DIRECTION_DELAYED_SOURCE_ID = "active-direction-eastmoney-delayed"
TDX_ACTIVE_DIRECTION_SOURCE_ID = "active-direction-tdx-derived"

_ACTIVE_DIRECTION_FIELDS = ("state", "summary", "topStocks")
_SUCCESS_STATUSES = frozenset({"ok", "partial", "fallback", "fallback-derived"})
_HISTORICAL_WARNING = "该数据源仅提供最新市场快照，历史日期不使用当前数据回填"
_MINIMUM_OBSERVATIONS = 30
_TOP_SIZE = 10
_SHANGHAI_ZONE = ZoneInfo("Asia/Shanghai")


class LegacyActiveDirectionProvider(Protocol):
    _STOCK_SNAPSHOT_URL: str
    _ACTIVE_DIRECTION_FALLBACK_URL: str

    def _fetch_eastmoney_active_direction_rows(
        self,
        url: str,
    ) -> list[dict[str, Any]]: ...

    def _fetch_tdx_active_direction_rows(
        self,
        as_of: date,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]: ...

    def _build_active_direction(
        self,
        rows: list[dict[str, Any]],
        as_of: date,
        *,
        source: str,
        status: str,
        warnings: list[str],
        preserve_order: bool = False,
        quality_metadata: Mapping[str, Any] | None = None,
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
    if request.identity.dataset != "activeDirection":
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
    if request.current_market_date != request.identity.as_of:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.DATE_MISMATCH,
            _HISTORICAL_WARNING,
            provenance=RedactedProvenance(
                attributes={"dateEvidenceKind": "latest-only"}
            ),
        )
    return None


def _candidate_from_payload(
    payload: Mapping[str, Any],
    request: SourceRequest,
    capability: SourceCapability,
    *,
    fetched_at: datetime,
    timings: AcquisitionTimings,
    provenance: RedactedProvenance,
) -> CollectionCandidate | AcquisitionFailure:
    try:
        copied_payload = copy.deepcopy(dict(payload))
        raw_quality = copied_payload.get("quality")
        if not isinstance(raw_quality, Mapping):
            raise ValueError("payload is missing quality")
        status = str(raw_quality.get("status") or "missing")
        quality_as_of = str(raw_quality.get("asOf") or "")
        if quality_as_of != request.identity.as_of.isoformat():
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.DATE_MISMATCH,
                f"{capability.source_id} returned mismatched asOf "
                f"{quality_as_of or 'missing'}",
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )
        warnings_value = raw_quality.get("warnings") or ()
        if not isinstance(warnings_value, (list, tuple)):
            raise ValueError("quality warnings must be a sequence")
        warnings = tuple(
            dict.fromkeys(str(value) for value in warnings_value if str(value))
        )
        warning = (
            str(raw_quality.get("warning"))
            if raw_quality.get("warning")
            else None
        )
        observations = int(raw_quality.get("observations") or 0)
        source = str(
            raw_quality.get("source") or raw_quality.get("provider") or "none"
        )
        provider = str(raw_quality.get("provider") or source)
        source_revision = str(
            raw_quality.get("sourceRevision")
            or raw_quality.get("providerRevision")
            or capability.revision
        )
        if (
            request.capability_revision is not None
            and source_revision != request.capability_revision
        ):
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.CONFIGURATION,
                f"{capability.source_id} returned capability revision {source_revision}",
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )
        if status not in _SUCCESS_STATUSES:
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.INSUFFICIENT,
                f"{capability.source_id} active-direction quality is {status}",
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
        validation_error = _validate_top_rows(copied_payload, observations)
        if validation_error is not None:
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.INSUFFICIENT,
                validation_error,
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )

        missing_fields = tuple(
            name
            for name in _ACTIVE_DIRECTION_FIELDS
            if copied_payload.get(name) is None
        )
        field_availability = FieldAvailability(
            available=tuple(
                name
                for name in _ACTIVE_DIRECTION_FIELDS
                if copied_payload.get(name) is not None
            ),
            missing=missing_fields,
        )
        extra = {
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
            dataset=str(raw_quality.get("dataset") or "active-direction"),
            source=source,
            provider=provider,
            status=status,
            observations=observations,
            as_of=request.identity.as_of,
            warning=warning,
            warnings=warnings,
            extra=extra,
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
    except Exception as exc:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONTRACT,
            f"{capability.source_id} active-direction normalization failed: "
            f"{type(exc).__name__}",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )


def _validate_top_rows(payload: Mapping[str, Any], observations: int) -> str | None:
    if observations < _MINIMUM_OBSERVATIONS:
        return (
            f"active-direction requires at least {_MINIMUM_OBSERVATIONS} observations; "
            f"received {observations}"
        )
    rows = payload.get("topStocks")
    if not isinstance(rows, list) or len(rows) != _TOP_SIZE:
        observed = len(rows) if isinstance(rows, list) else 0
        return f"active-direction requires {_TOP_SIZE} ranked rows; received {observed}"
    identities: set[str] = set()
    amounts: list[float] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            return f"active-direction row {index} is not an object"
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        try:
            amount = float(row.get("amount"))
        except (TypeError, ValueError):
            amount = math.nan
        if not code or not name or not math.isfinite(amount):
            return f"active-direction row {index} lacks code, name or amount"
        if code in identities:
            return f"active-direction rows contain duplicate code {code}"
        identities.add(code)
        amounts.append(amount)
    if any(left < right for left, right in zip(amounts, amounts[1:])):
        return "active-direction rows are not ordered by descending amount"
    return None


@dataclass(frozen=True, slots=True)
class EastmoneyActiveDirectionPrimaryAdapter:
    provider: LegacyActiveDirectionProvider
    revision: str = "eastmoney-active-direction-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(
        init=False,
        default=EASTMONEY_ACTIVE_DIRECTION_PRIMARY_SOURCE_ID,
    )
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
                supported_fields=_ACTIVE_DIRECTION_FIELDS,
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        started = time.perf_counter()
        fetched_at = self.now()
        try:
            rows = self.provider._fetch_eastmoney_active_direction_rows(
                self.provider._STOCK_SNAPSHOT_URL
            )
            payload = self.provider._build_active_direction(
                rows,
                request.identity.as_of,
                source="eastmoney-clist",
                status="partial",
                warnings=[],
            )
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
                    endpoint=self.provider._STOCK_SNAPSHOT_URL,
                    engine="requests",
                    attributes={"dateEvidenceKind": "latest-only"},
                ),
            )
        return _candidate_from_payload(
            payload,
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=RedactedProvenance(
                endpoint=self.provider._STOCK_SNAPSHOT_URL,
                engine="requests",
                attributes={"dateEvidenceKind": "latest-only"},
            ),
        )


@dataclass(frozen=True, slots=True)
class EastmoneyActiveDirectionDelayedAdapter:
    provider: LegacyActiveDirectionProvider
    revision: str = "eastmoney-active-direction-delay-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(
        init=False,
        default=EASTMONEY_ACTIVE_DIRECTION_DELAYED_SOURCE_ID,
    )
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
                supported_fields=_ACTIVE_DIRECTION_FIELDS,
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        primary_error = str(request.params.get("primary_error") or "")
        if not primary_error:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.CONFIGURATION,
                "Eastmoney delayed active-direction requires primary failure evidence",
            )
        started = time.perf_counter()
        fetched_at = self.now()
        try:
            rows = self.provider._fetch_eastmoney_active_direction_rows(
                self.provider._ACTIVE_DIRECTION_FALLBACK_URL
            )
            payload = self.provider._build_active_direction(
                rows,
                request.identity.as_of,
                source="eastmoney-clist-delay",
                status="fallback",
                warnings=[
                    f"东方财富容量方向主域不可用：{primary_error}",
                    "已降级到东方财富延迟容量方向",
                ],
            )
        except Exception as exc:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.NETWORK,
                f"主域失败：{primary_error}；延迟域失败：{exc}",
                retryable=True,
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=RedactedProvenance(
                    endpoint=self.provider._ACTIVE_DIRECTION_FALLBACK_URL,
                    engine="requests",
                    attributes={"dateEvidenceKind": "latest-only"},
                ),
            )
        normalized = _candidate_from_payload(
            payload,
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=RedactedProvenance(
                endpoint=self.provider._ACTIVE_DIRECTION_FALLBACK_URL,
                engine="requests",
                attributes={"dateEvidenceKind": "latest-only"},
            ),
        )
        if isinstance(normalized, AcquisitionFailure):
            return replace(
                normalized,
                message=(
                    f"主域失败：{primary_error}；延迟域失败：{normalized.message}"
                ),
            )
        return normalized


@dataclass(frozen=True, slots=True)
class TDXDerivedActiveDirectionAdapter:
    provider: LegacyActiveDirectionProvider
    revision: str = TDX_UPSTREAM_REVISION
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=TDX_ACTIVE_DIRECTION_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            SourceCapability(
                source_id=self.source_id,
                provider="tdx",
                revision=self.revision,
                supports_historical=False,
                latest_only=True,
                supported_fields=_ACTIVE_DIRECTION_FIELDS,
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
                "TDX-derived active-direction requires Eastmoney failure evidence",
            )
        started = time.perf_counter()
        fetched_at = self.now()
        provenance = RedactedProvenance(
            engine="tdx-package",
            attributes={
                "dateEvidenceKind": "package",
                "productDateCapability": "current-only",
            },
        )
        try:
            rows, metadata = self.provider._fetch_tdx_active_direction_rows(
                request.identity.as_of
            )
            payload = self.provider._build_active_direction(
                rows,
                request.identity.as_of,
                source="tdx-daily-package-derived",
                status="fallback-derived",
                warnings=[
                    primary_warning,
                    "已降级到通达信盘后包并进行本地成交额排序",
                ],
                preserve_order=True,
                quality_metadata=metadata,
            )
        except TDXStockUniverseError as exc:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.INSUFFICIENT,
                f"{primary_warning}；通达信普通 A 股 universe 不足：{exc}",
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=replace(
                    provenance,
                    attributes={
                        **dict(provenance.attributes),
                        **exc.classification.metadata(),
                    },
                ),
            )
        except TDXDailyPackageError as exc:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.INSUFFICIENT,
                f"{primary_warning}；通达信盘后包不可用：{exc}",
                retryable=bool(getattr(exc, "retryable", False)),
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=provenance,
            )
        except Exception as exc:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.INTERNAL,
                f"{primary_warning}；通达信盘后包不可用：{exc}",
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=provenance,
            )
        normalized = _candidate_from_payload(
            payload,
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=provenance,
        )
        if isinstance(normalized, AcquisitionFailure):
            return replace(
                normalized,
                message=f"{primary_warning}；通达信盘后包不可用：{normalized.message}",
            )
        return normalized


@dataclass(frozen=True, slots=True)
class ActiveDirectionAcquisitionPlan:
    """Preserve Eastmoney primary/delayed ordering and optional TDX derivation."""

    adapters: SourceAdapterRegistry
    tdx_derived_is_enabled: Callable[[], bool]
    market_today: Callable[[], date] = _market_today
    is_settled: Callable[[date], bool] = lambda _as_of: True
    dataset_id: str = field(init=False, default="activeDirection")
    plan_id: str = field(init=False, default="active-direction-acquisition-v1")
    steps: tuple[AcquisitionPlanStep, ...] = field(init=False)

    def __post_init__(self) -> None:
        steps = tuple(
            AcquisitionPlanStep(
                source_id,
                role=role,
                capability_revision=self.adapters.get(
                    source_id
                ).capability.revision,
            )
            for source_id, role in (
                (EASTMONEY_ACTIVE_DIRECTION_PRIMARY_SOURCE_ID, "formal"),
                (EASTMONEY_ACTIVE_DIRECTION_DELAYED_SOURCE_ID, "fallback"),
                (TDX_ACTIVE_DIRECTION_SOURCE_ID, "fallback"),
            )
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
        if identity.as_of != current_market_date:
            failure = AcquisitionFailure(
                AcquisitionFailureCategory.DATE_MISMATCH,
                _HISTORICAL_WARNING,
                requested_as_of=identity.as_of,
            )
            return CollectionOutcome(
                identity=identity,
                state=CollectionTaskState.FAILED_MISSING,
                warning=failure.message,
                failure=failure,
            )

        attempts: list[AttemptEvidence] = []
        settled = self.is_settled(identity.as_of)
        primary = self._attempt(
            identity,
            EASTMONEY_ACTIVE_DIRECTION_PRIMARY_SOURCE_ID,
            role="formal",
            current_market_date=current_market_date,
            settled=settled,
            attempts=attempts,
        )
        if isinstance(primary, CollectionCandidate):
            return self._success(identity, primary, attempts)

        primary_warning = f"东方财富容量方向主域不可用：{primary.message}"
        attempts[-1] = replace(attempts[-1], warning=primary_warning)
        delayed = self._attempt(
            identity,
            EASTMONEY_ACTIVE_DIRECTION_DELAYED_SOURCE_ID,
            role="fallback",
            current_market_date=current_market_date,
            settled=settled,
            attempts=attempts,
            params={"primary_error": primary.message},
        )
        if isinstance(delayed, CollectionCandidate):
            return self._success(identity, delayed, attempts)

        eastmoney_warning = f"东方财富容量方向不可用：{delayed.message}"
        attempts[-1] = replace(attempts[-1], warning=eastmoney_warning)
        if not self.tdx_derived_is_enabled():
            failure = replace(delayed, message=eastmoney_warning)
            return CollectionOutcome(
                identity=identity,
                state=CollectionTaskState.FAILED_MISSING,
                warning=eastmoney_warning,
                failure=failure,
                attempts=tuple(attempts),
            )

        tdx = self._attempt(
            identity,
            TDX_ACTIVE_DIRECTION_SOURCE_ID,
            role="fallback",
            current_market_date=current_market_date,
            settled=settled,
            attempts=attempts,
            params={"primary_warning": eastmoney_warning},
        )
        if isinstance(tdx, CollectionCandidate):
            return self._success(identity, tdx, attempts)
        return CollectionOutcome(
            identity=identity,
            state=CollectionTaskState.FAILED_MISSING,
            warning=tdx.message,
            failure=tdx,
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
        params: Mapping[str, object] | None = None,
    ) -> CollectionCandidate | AcquisitionFailure:
        adapter = self.adapters.get(source_id)
        result = adapter.acquire(
            SourceRequest(
                identity=identity,
                source_id=source_id,
                role=role,
                params=params or {},
                capability_revision=adapter.capability.revision,
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

    @staticmethod
    def _success(
        identity: DatasetDate,
        candidate: CollectionCandidate,
        attempts: list[AttemptEvidence],
    ) -> CollectionOutcome:
        state = (
            CollectionTaskState.PARTIAL
            if candidate.status in {"partial", "fallback-derived"}
            else CollectionTaskState.SUCCESS
        )
        return CollectionOutcome(
            identity=identity,
            state=state,
            candidate=candidate,
            warning=candidate.quality.warning if candidate.quality else None,
            attempts=tuple(attempts),
        )


def _milliseconds(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = [
    "ActiveDirectionAcquisitionPlan",
    "EASTMONEY_ACTIVE_DIRECTION_DELAYED_SOURCE_ID",
    "EASTMONEY_ACTIVE_DIRECTION_PRIMARY_SOURCE_ID",
    "EastmoneyActiveDirectionDelayedAdapter",
    "EastmoneyActiveDirectionPrimaryAdapter",
    "TDX_ACTIVE_DIRECTION_SOURCE_ID",
    "TDXDerivedActiveDirectionAdapter",
]
