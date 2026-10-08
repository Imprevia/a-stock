"""Normalized sector source adapters and deterministic acquisition policy."""

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
from .sector_enrichment import (
    ENRICHMENT_MAPPING_REVISION,
    ENRICHMENT_MATCH_METHOD,
    SUPPLEMENTAL_FIELDS,
)
from .shadow import compare_shadow


EASTMONEY_SECTOR_PRIMARY_SOURCE_ID = "sectors-eastmoney-clist"
EASTMONEY_SECTOR_DELAYED_SOURCE_ID = "sectors-eastmoney-clist-delay"
FUYAO_SECTOR_SOURCE_ID = "sectors-fuyao"
EASTMONEY_SECTOR_ENRICHMENT_SOURCE_ID = "sectors-eastmoney-dataapi-enrichment"

_EASTMONEY_PRIMARY_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_EASTMONEY_DELAYED_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
_EASTMONEY_DATAAPI_URL = "https://data.eastmoney.com/dataapi/bkzj/getbkzj"
_DATAAPI_REQUEST_FIELDS = ("f3", "f6", "f62", "f104", "f105", "f128", "f184")
_SECTOR_ROW_FIELDS = (
    "rank",
    "code",
    "name",
    "changePct",
    "amount",
    "mainNet",
    "mainNetPct",
    "upCount",
    "downCount",
    "leader",
)
_FUYAO_FIELDS = ("rank", "code", "name", "changePct", "amount")
_SUCCESS_STATUSES = frozenset({"ok", "partial", "fallback", "fallback-derived"})
_HISTORICAL_WARNING = "该数据源仅提供最新市场快照，历史日期不使用当前数据回填"
_ENRICHMENT_GATE_WARNING = "东方财富 dataapi 行业字段补充仅允许当前上海交易日且结算后调用"
_SHANGHAI_ZONE = ZoneInfo("Asia/Shanghai")


class LegacySectorProvider(Protocol):
    def _fetch_eastmoney_industries_from(self, url: str) -> list[dict[str, Any]]: ...

    def _build_sectors(
        self,
        rows: list[dict[str, Any]],
        as_of: date,
        *,
        source: str,
        status: str,
        warnings: list[str],
    ) -> dict[str, Any]: ...

    def enrich_fuyao_sectors(
        self,
        payload: Mapping[str, Any],
        as_of: date,
        *,
        eligible: bool,
    ) -> dict[str, Any]: ...


class FuyaoSectorClient(Protocol):
    def fetch_sectors(self, as_of: date) -> FuyaoMarketResult: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _market_today() -> date:
    return datetime.now(_SHANGHAI_ZONE).date()


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
    *,
    require_settled: bool = False,
) -> AcquisitionFailure | None:
    if request.identity.dataset != "sectors":
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
    if require_settled and request.settled is not True:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.INSUFFICIENT,
            _ENRICHMENT_GATE_WARNING,
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
    source_override: str | None = None,
    provider_override: str | None = None,
    revision_override: str | None = None,
) -> CollectionCandidate | AcquisitionFailure:
    copied_payload = copy.deepcopy(dict(payload))
    raw_quality = copied_payload.get("quality")
    if not isinstance(raw_quality, Mapping):
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONTRACT,
            f"{capability.source_id} sector payload is missing quality",
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
    status = str(raw_quality.get("status") or "missing")
    if status not in _SUCCESS_STATUSES:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.INSUFFICIENT,
            str(raw_quality.get("warning") or f"{capability.source_id} sector quality is {status}"),
            fetched_at=fetched_at,
            timings=timings,
            provenance=replace(
                provenance,
                attributes={
                    **dict(provenance.attributes),
                    "qualityStatus": status,
                    "qualityWarnings": tuple(raw_quality.get("warnings") or ()),
                },
            ),
        )
    rows = copied_payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.INSUFFICIENT,
            f"{capability.source_id} sector payload has no rows",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.CONTRACT,
                f"{capability.source_id} sector row {index} is not an object",
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )
        if not str(row.get("code") or "").strip() or not str(row.get("name") or "").strip():
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.CONTRACT,
                f"{capability.source_id} sector row {index} lacks code or name",
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )
        try:
            float(row.get("changePct"))
        except (TypeError, ValueError):
            return _failure(
                request,
                capability,
                AcquisitionFailureCategory.CONTRACT,
                f"{capability.source_id} sector row {index} lacks changePct",
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )

    raw_revision = raw_quality.get("sourceRevision") or raw_quality.get("providerRevision")
    source_revision = str(revision_override or raw_revision or capability.revision)
    if (
        revision_override is None
        and request.capability_revision is not None
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
    warnings = tuple(
        dict.fromkeys(
            str(value) for value in raw_quality.get("warnings") or () if str(value)
        )
    )
    source = source_override or str(
        raw_quality.get("source") or raw_quality.get("provider") or "none"
    )
    provider = provider_override or str(raw_quality.get("provider") or source)
    observations = int(raw_quality.get("observations") or len(rows))
    available = tuple(
        name
        for name in _SECTOR_ROW_FIELDS
        if all(row.get(name) is not None for row in rows)
    )
    missing = tuple(
        name
        for name in capability.supported_fields
        if name not in available
    )
    unsupported = tuple(
        name for name in _SECTOR_ROW_FIELDS if name not in capability.supported_fields
    )
    field_availability = FieldAvailability(
        available=available,
        missing=missing,
        unsupported=unsupported,
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
        dataset=str(raw_quality.get("dataset") or "industry-ranking"),
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
    source_override: str | None = None,
    provider_override: str | None = None,
    revision_override: str | None = None,
) -> CollectionCandidate | AcquisitionFailure:
    try:
        return _quality_candidate(
            payload,
            request,
            capability,
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
            source_override=source_override,
            provider_override=provider_override,
            revision_override=revision_override,
        )
    except Exception as exc:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONTRACT,
            f"{capability.source_id} sector normalization failed: {type(exc).__name__}",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )


@dataclass(frozen=True, slots=True)
class EastmoneySectorPrimaryAdapter:
    provider: LegacySectorProvider
    revision: str = "eastmoney-sectors-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=EASTMONEY_SECTOR_PRIMARY_SOURCE_ID)
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
                supported_fields=_SECTOR_ROW_FIELDS,
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        started = time.perf_counter()
        fetched_at = self.now()
        try:
            rows = self.provider._fetch_eastmoney_industries_from(_EASTMONEY_PRIMARY_URL)
            payload = self.provider._build_sectors(
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
                    endpoint=_EASTMONEY_PRIMARY_URL,
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
                endpoint=_EASTMONEY_PRIMARY_URL,
                engine="requests",
                attributes={"dateEvidenceKind": "latest-only"},
            ),
        )


@dataclass(frozen=True, slots=True)
class EastmoneySectorDelayedAdapter:
    provider: LegacySectorProvider
    revision: str = "eastmoney-sectors-delay-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=EASTMONEY_SECTOR_DELAYED_SOURCE_ID)
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
                supported_fields=_SECTOR_ROW_FIELDS,
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
                "Eastmoney delayed sectors requires primary failure evidence",
            )
        started = time.perf_counter()
        fetched_at = self.now()
        try:
            rows = self.provider._fetch_eastmoney_industries_from(_EASTMONEY_DELAYED_URL)
            payload = self.provider._build_sectors(
                rows,
                request.identity.as_of,
                source="eastmoney-clist-delay",
                status="fallback",
                warnings=[
                    f"东方财富行业主域不可用：{primary_error}",
                    "已降级到东方财富延迟行业排名",
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
                    endpoint=_EASTMONEY_DELAYED_URL,
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
                endpoint=_EASTMONEY_DELAYED_URL,
                engine="requests",
                attributes={"dateEvidenceKind": "latest-only"},
            ),
        )


@dataclass(frozen=True, slots=True)
class FuyaoSectorSourceAdapter:
    client: FuyaoSectorClient
    revision: str = "fuyao-market-v2"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=FUYAO_SECTOR_SOURCE_ID)
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
                supported_fields=_FUYAO_FIELDS,
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        started = time.perf_counter()
        fetched_at = self.now()
        try:
            result = self.client.fetch_sectors(request.identity.as_of)
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
                provenance=RedactedProvenance(
                    endpoint="/api/a-share/ths-index/snapshot",
                    engine="requests",
                    attributes={"dateEvidenceKind": "provider-calendar-and-timestamp"},
                ),
            )
        if not isinstance(result, FuyaoMarketResult):
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.CONTRACT,
                "Fuyao sector adapter returned an invalid result",
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
                endpoint=str(
                    result.quality.get("endpoint") or "/api/a-share/ths-index/snapshot"
                ),
                engine="requests",
                attributes={"dateEvidenceKind": "provider-calendar-and-timestamp"},
            ),
        )


@dataclass(frozen=True, slots=True)
class EastmoneySectorEnrichmentAdapter:
    provider: LegacySectorProvider
    enabled: Callable[[], bool] = lambda: False
    revision: str = ENRICHMENT_MAPPING_REVISION
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(
        init=False,
        default=EASTMONEY_SECTOR_ENRICHMENT_SOURCE_ID,
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
                supported_fields=SUPPLEMENTAL_FIELDS,
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability, require_settled=True)
        if invalid is not None:
            return invalid
        base_payload = request.params.get("base_payload")
        if not isinstance(base_payload, Mapping):
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.CONFIGURATION,
                "sector enrichment requires an accepted Fuyao base payload",
            )
        started = time.perf_counter()
        fetched_at = self.now()
        provenance = RedactedProvenance(
            endpoint=_EASTMONEY_DATAAPI_URL,
            engine="requests",
            attributes={
                "dateEvidenceKind": "latest-only",
                "sameVendor": True,
                "mappingRevision": ENRICHMENT_MAPPING_REVISION,
            },
        )
        if not self.enabled():
            payload = _with_enrichment_metadata(
                base_payload,
                _enrichment_metadata(
                    "disabled",
                    request.identity.as_of,
                    base_payload,
                    reason="feature-disabled",
                ),
            )
        else:
            try:
                payload = self.provider.enrich_fuyao_sectors(
                    copy.deepcopy(dict(base_payload)),
                    request.identity.as_of,
                    eligible=True,
                )
            except Exception as exc:
                metadata = _enrichment_metadata(
                    "failed",
                    request.identity.as_of,
                    base_payload,
                    current=request.current_market_date,
                    settled=request.settled is True,
                    eligible=True,
                    reason="request-attempted",
                    warning=(
                        "东方财富 dataapi 行业字段补充失败"
                        f"（{request.identity.as_of.isoformat()}）：{exc}"
                    ),
                )
                return _failure(
                    request,
                    self.capability,
                    AcquisitionFailureCategory.NETWORK,
                    metadata["warnings"][0],
                    retryable=True,
                    fetched_at=fetched_at,
                    timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                    provenance=replace(
                        provenance,
                        attributes={
                            **dict(provenance.attributes),
                            "sectorEnrichment": metadata,
                        },
                    ),
                )
        if not isinstance(payload, Mapping):
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.CONTRACT,
                "sector enrichment returned a non-object payload",
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=provenance,
            )
        metadata = (payload.get("quality") or {}).get("sectorEnrichment")
        if isinstance(metadata, Mapping) and str(metadata.get("status")) == "failed":
            warnings = [str(value) for value in metadata.get("warnings") or () if str(value)]
            message = warnings[0] if warnings else "东方财富 dataapi 行业字段补充失败"
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.INSUFFICIENT,
                message,
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=replace(
                    provenance,
                    attributes={
                        **dict(provenance.attributes),
                        "sectorEnrichment": copy.deepcopy(dict(metadata)),
                    },
                ),
            )
        return _normalize_payload(
            payload,
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=provenance,
            source_override="eastmoney-dataapi",
            provider_override="eastmoney",
            revision_override=self.capability.revision,
        )


@dataclass(frozen=True, slots=True)
class SectorsAcquisitionPlan:
    """Preserve Eastmoney -> approved Fuyao -> fill-only dataapi policy."""

    adapters: SourceAdapterRegistry
    fuyao_is_enabled: Callable[[str], bool] = lambda _dataset: False
    fuyao_gate_warning: Callable[[str], str] = (
        lambda _dataset: "扶摇 sectors provider 未启用或缺少批准 capability"
    )
    fuyao_shadow_enabled: Callable[[str], bool] = lambda _dataset: False
    fuyao_revision: Callable[[str], str] = lambda _dataset: "fuyao-market-v2"
    market_today: Callable[[], date] = _market_today
    is_settled: Callable[[date], bool] = lambda _as_of: True
    dataset_id: str = field(init=False, default="sectors")
    plan_id: str = field(init=False, default="sectors-acquisition-v1")
    steps: tuple[AcquisitionPlanStep, ...] = field(init=False)

    def __post_init__(self) -> None:
        steps = (
            self._step(EASTMONEY_SECTOR_PRIMARY_SOURCE_ID, "formal"),
            self._step(EASTMONEY_SECTOR_DELAYED_SOURCE_ID, "fallback"),
            self._step(FUYAO_SECTOR_SOURCE_ID, "fallback"),
            AcquisitionPlanStep(
                EASTMONEY_SECTOR_ENRICHMENT_SOURCE_ID,
                role="enrichment",
                capability_revision=self.adapters.get(
                    EASTMONEY_SECTOR_ENRICHMENT_SOURCE_ID
                ).capability.revision,
                approved_fields=SUPPLEMENTAL_FIELDS,
            ),
            self._step(FUYAO_SECTOR_SOURCE_ID, "shadow"),
        )
        object.__setattr__(self, "steps", steps)
        self.adapters.validate_references((self,))

    def _step(self, source_id: str, role: str) -> AcquisitionPlanStep:
        return AcquisitionPlanStep(
            source_id,
            role=role,
            capability_revision=self.adapters.get(source_id).capability.revision,
        )

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

        settled = self.is_settled(identity.as_of)
        attempts: list[AttemptEvidence] = []
        primary = self._attempt(
            identity,
            EASTMONEY_SECTOR_PRIMARY_SOURCE_ID,
            role="formal",
            current_market_date=current_market_date,
            settled=settled,
            attempts=attempts,
        )
        formal_candidate: CollectionCandidate | None = None
        eastmoney_failure: AcquisitionFailure | None = None
        if isinstance(primary, CollectionCandidate):
            formal_candidate = primary
        else:
            attempts[-1] = replace(
                attempts[-1],
                warning=f"东方财富行业主域不可用：{primary.message}",
            )
            delayed = self._attempt(
                identity,
                EASTMONEY_SECTOR_DELAYED_SOURCE_ID,
                role="fallback",
                current_market_date=current_market_date,
                settled=settled,
                attempts=attempts,
                params={"primary_error": primary.message},
            )
            if isinstance(delayed, CollectionCandidate):
                formal_candidate = delayed
            else:
                eastmoney_failure = replace(
                    delayed,
                    message=f"东方财富行业排名不可用：{delayed.message}",
                )
                attempts[-1] = replace(
                    attempts[-1], warning=eastmoney_failure.message
                )

        if formal_candidate is None:
            if not self.fuyao_is_enabled(self.dataset_id):
                assert eastmoney_failure is not None
                warning = (
                    f"{eastmoney_failure.message}；"
                    f"{self.fuyao_gate_warning(self.dataset_id)}"
                )
                return CollectionOutcome(
                    identity=identity,
                    state=CollectionTaskState.FAILED_MISSING,
                    warning=warning,
                    failure=replace(eastmoney_failure, message=warning),
                    attempts=tuple(attempts),
                )
            fuyao = self._attempt(
                identity,
                FUYAO_SECTOR_SOURCE_ID,
                role="fallback",
                capability_revision=self.fuyao_revision(self.dataset_id),
                current_market_date=current_market_date,
                settled=settled,
                attempts=attempts,
            )
            if isinstance(fuyao, AcquisitionFailure):
                assert eastmoney_failure is not None
                warning = (
                    f"{eastmoney_failure.message}；"
                    f"扶摇行业 fallback 不可用：{fuyao.message}"
                )
                return CollectionOutcome(
                    identity=identity,
                    state=CollectionTaskState.FAILED_MISSING,
                    warning=warning,
                    failure=replace(fuyao, message=warning),
                    attempts=tuple(attempts),
                )
            assert eastmoney_failure is not None
            formal_candidate = _append_candidate_warnings(
                fuyao,
                (
                    eastmoney_failure.message,
                    f"扶摇 capability revision: {self.fuyao_revision(self.dataset_id)}",
                ),
            )
            formal_candidate = self._enrich(
                identity,
                formal_candidate,
                current_market_date=current_market_date,
                settled=settled,
                attempts=attempts,
            )
        elif (
            self.fuyao_shadow_enabled(self.dataset_id)
            and self.fuyao_is_enabled(self.dataset_id)
        ):
            formal_candidate = self._shadow(
                identity,
                formal_candidate,
                current_market_date=current_market_date,
                settled=settled,
                attempts=attempts,
            )

        state = (
            CollectionTaskState.PARTIAL
            if formal_candidate.status in {"partial", "fallback", "fallback-derived"}
            else CollectionTaskState.SUCCESS
        )
        warning = formal_candidate.quality.warning if formal_candidate.quality else None
        return CollectionOutcome(
            identity=identity,
            state=state,
            candidate=formal_candidate,
            warning=warning,
            attempts=tuple(attempts),
        )

    def _enrich(
        self,
        identity: DatasetDate,
        candidate: CollectionCandidate,
        *,
        current_market_date: date,
        settled: bool,
        attempts: list[AttemptEvidence],
    ) -> CollectionCandidate:
        if identity.as_of != current_market_date or not settled:
            metadata = _enrichment_metadata(
                "skipped",
                identity.as_of,
                candidate.payload,
                current=current_market_date,
                settled=False,
                eligible=False,
                reason=_ENRICHMENT_GATE_WARNING,
                warning=_ENRICHMENT_GATE_WARNING,
                include_mapping=False,
            )
            return _candidate_with_enrichment(candidate, metadata)
        result = self._attempt(
            identity,
            EASTMONEY_SECTOR_ENRICHMENT_SOURCE_ID,
            role="enrichment",
            current_market_date=current_market_date,
            settled=settled,
            attempts=attempts,
            params={"base_payload": copy.deepcopy(dict(candidate.payload))},
        )
        if isinstance(result, AcquisitionFailure):
            raw_metadata = result.provenance.attributes.get("sectorEnrichment")
            metadata = (
                copy.deepcopy(dict(raw_metadata))
                if isinstance(raw_metadata, Mapping)
                else _enrichment_metadata(
                    "failed",
                    identity.as_of,
                    candidate.payload,
                    current=current_market_date,
                    settled=settled,
                    eligible=True,
                    reason="request-attempted",
                    warning=result.message,
                )
            )
            return _candidate_with_enrichment(candidate, metadata)
        try:
            return _fill_only_enrichment(candidate, result.payload)
        except ValueError as exc:
            warning = f"东方财富 dataapi 行业字段补充失败：{exc}"
            attempts[-1] = replace(
                attempts[-1],
                category=AcquisitionFailureCategory.CONTRACT,
                warning=warning,
            )
            return _candidate_with_enrichment(
                candidate,
                _enrichment_metadata(
                    "failed",
                    identity.as_of,
                    candidate.payload,
                    current=current_market_date,
                    settled=settled,
                    eligible=True,
                    reason="request-attempted",
                    warning=warning,
                ),
            )

    def _shadow(
        self,
        identity: DatasetDate,
        candidate: CollectionCandidate,
        *,
        current_market_date: date,
        settled: bool,
        attempts: list[AttemptEvidence],
    ) -> CollectionCandidate:
        shadow = self._attempt(
            identity,
            FUYAO_SECTOR_SOURCE_ID,
            role="shadow",
            capability_revision=self.fuyao_revision(self.dataset_id),
            current_market_date=current_market_date,
            settled=settled,
            attempts=attempts,
        )
        if isinstance(shadow, AcquisitionFailure):
            warning = f"扶摇 shadow 不可用：{shadow.message}"
            attempts[-1] = replace(attempts[-1], warning=warning)
            return _append_candidate_warnings(candidate, (warning,), quality_payload=False)
        comparison = compare_shadow(
            self.dataset_id,
            candidate.payload,
            shadow.payload,
            formal_revision=candidate.source_revision or candidate.source,
            shadow_revision=self.fuyao_revision(self.dataset_id),
            as_of=identity.as_of,
        )
        warning = (
            f"扶摇 shadow: {comparison.get('status')}"
            if comparison.get("status") not in {"match", "degraded"}
            else None
        )
        attempts[-1] = replace(
            attempts[-1],
            warning=warning,
            provenance=replace(
                attempts[-1].provenance,
                attributes={
                    **dict(attempts[-1].provenance.attributes),
                    "comparison": comparison,
                },
            ),
        )
        return (
            _append_candidate_warnings(candidate, (warning,), quality_payload=False)
            if warning
            else candidate
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
                capability_revision=capability_revision or adapter.capability.revision,
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
                provider=adapter.capability.provider,
                source=(source_id if role == "enrichment" else result.source),
                source_revision=(
                    adapter.capability.revision
                    if role == "enrichment"
                    else result.source_revision or adapter.capability.revision
                ),
                requested_as_of=identity.as_of,
                actual_as_of=result.actual_as_of,
                warning=(
                    _enrichment_attempt_warning(result.payload)
                    if role == "enrichment"
                    else None
                ),
                timings=result.timings,
                provenance=result.provenance,
                evidence_fingerprint=result.evidence_fingerprint,
            )
        )
        return result


def _append_candidate_warnings(
    candidate: CollectionCandidate,
    added: tuple[str | None, ...],
    *,
    quality_payload: bool = True,
) -> CollectionCandidate:
    merged = tuple(
        dict.fromkeys(
            [*candidate.warnings, *(value for value in added if value)]
        )
    )
    payload = copy.deepcopy(dict(candidate.payload))
    if quality_payload:
        raw_quality = dict(payload.get("quality") or {})
        raw_quality["warnings"] = list(merged)
        raw_quality["warning"] = "; ".join(merged) if merged else None
        payload["quality"] = raw_quality
    quality = candidate.quality
    if quality is not None:
        quality = replace(
            quality,
            warnings=merged,
            warning="; ".join(merged) if merged else None,
        )
    return replace(candidate, payload=payload, warnings=merged, quality=quality)


def _enrichment_metadata(
    status: str,
    as_of: date,
    base_payload: Mapping[str, Any],
    *,
    current: date | None = None,
    settled: bool = False,
    eligible: bool = False,
    reason: str = "not-evaluated",
    warning: str | None = None,
    include_mapping: bool = True,
) -> dict[str, Any]:
    rows = base_payload.get("rows")
    base_rows = len(rows) if isinstance(rows, list) else 0
    metadata: dict[str, Any] = {
        "status": status,
        "source": "eastmoney-dataapi",
        "provider": "eastmoney",
        "sameVendor": True,
        "endpoint": _EASTMONEY_DATAAPI_URL,
        "requestedFields": list(_DATAAPI_REQUEST_FIELDS),
        "mappingRevision": ENRICHMENT_MAPPING_REVISION if include_mapping else None,
        "matchMethod": ENRICHMENT_MATCH_METHOD if include_mapping else None,
        "sourceRows": 0,
        "baseRows": base_rows,
        "matchedRows": 0,
        "unmatchedRows": base_rows,
        "identityCoverage": 0.0 if base_rows else None,
        "fieldCoverage": (
            {field_name: 0.0 for field_name in SUPPLEMENTAL_FIELDS}
            if include_mapping
            else {}
        ),
        "dateEvidence": {
            "requested": as_of.isoformat(),
            "current": current.isoformat() if current is not None else None,
            "eligible": eligible,
            "settled": settled,
            "reason": reason,
        },
        "warnings": [warning] if warning else [],
    }
    if include_mapping:
        metadata["fieldMatched"] = {
            field_name: 0 for field_name in SUPPLEMENTAL_FIELDS
        }
    return metadata


def _with_enrichment_metadata(
    payload: Mapping[str, Any], metadata: Mapping[str, Any]
) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    quality = dict(result.get("quality") or {})
    quality["sectorEnrichment"] = copy.deepcopy(dict(metadata))
    result["quality"] = quality
    return result


def _candidate_with_enrichment(
    candidate: CollectionCandidate,
    metadata: Mapping[str, Any],
) -> CollectionCandidate:
    payload = _with_enrichment_metadata(candidate.payload, metadata)
    quality_payload = dict(payload.get("quality") or {})
    warnings = tuple(
        dict.fromkeys(
            [
                *candidate.warnings,
                *(str(value) for value in metadata.get("warnings") or () if str(value)),
            ]
        )
    )
    quality_payload["warnings"] = list(warnings)
    quality_payload["warning"] = "；".join(warnings) if warnings else None
    payload["quality"] = quality_payload
    quality = candidate.quality
    if quality is not None:
        quality = replace(
            quality,
            warnings=warnings,
            warning=quality_payload["warning"],
            extra={
                **dict(quality.extra),
                "sectorEnrichment": copy.deepcopy(dict(metadata)),
            },
        )
    return replace(candidate, payload=payload, warnings=warnings, quality=quality)


def _fill_only_enrichment(
    base: CollectionCandidate,
    enriched_payload: Mapping[str, Any],
) -> CollectionCandidate:
    base_payload = copy.deepcopy(dict(base.payload))
    base_rows = base_payload.get("rows")
    enriched_rows = enriched_payload.get("rows")
    if not isinstance(base_rows, list) or not isinstance(enriched_rows, list):
        raise ValueError("enrichment rows are missing")
    if len(base_rows) != len(enriched_rows):
        raise ValueError("enrichment changed sector row count")
    merged_rows: list[dict[str, Any]] = []
    for index, (base_row, enriched_row) in enumerate(zip(base_rows, enriched_rows)):
        if not isinstance(base_row, Mapping) or not isinstance(enriched_row, Mapping):
            raise ValueError(f"enrichment row {index} is not an object")
        for identity_field in ("code", "name"):
            if base_row.get(identity_field) != enriched_row.get(identity_field):
                raise ValueError(f"enrichment changed sector {identity_field}")
        merged = copy.deepcopy(dict(base_row))
        for field_name in SUPPLEMENTAL_FIELDS:
            if merged.get(field_name) is None and enriched_row.get(field_name) is not None:
                merged[field_name] = copy.deepcopy(enriched_row[field_name])
        merged_rows.append(merged)
    raw_quality = enriched_payload.get("quality")
    metadata = (
        raw_quality.get("sectorEnrichment")
        if isinstance(raw_quality, Mapping)
        else None
    )
    if not isinstance(metadata, Mapping):
        raise ValueError("enrichment metadata is missing")
    base_payload["rows"] = merged_rows
    merged_candidate = _candidate_with_enrichment(base, metadata)
    return replace(
        merged_candidate,
        payload={**dict(merged_candidate.payload), "rows": merged_rows},
    )


def _enrichment_attempt_warning(payload: Mapping[str, Any]) -> str | None:
    quality = payload.get("quality")
    metadata = quality.get("sectorEnrichment") if isinstance(quality, Mapping) else None
    if not isinstance(metadata, Mapping):
        return None
    status = str(metadata.get("status") or "")
    warnings = [str(value) for value in metadata.get("warnings") or () if str(value)]
    if warnings:
        return "; ".join(warnings)
    if status in {"disabled", "skipped"}:
        return f"sector enrichment {status}"
    return None


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


__all__ = [
    "EASTMONEY_SECTOR_DELAYED_SOURCE_ID",
    "EASTMONEY_SECTOR_ENRICHMENT_SOURCE_ID",
    "EASTMONEY_SECTOR_PRIMARY_SOURCE_ID",
    "EastmoneySectorDelayedAdapter",
    "EastmoneySectorEnrichmentAdapter",
    "EastmoneySectorPrimaryAdapter",
    "FUYAO_SECTOR_SOURCE_ID",
    "FuyaoSectorSourceAdapter",
    "SectorsAcquisitionPlan",
]
