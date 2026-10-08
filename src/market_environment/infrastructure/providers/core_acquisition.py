"""Normalized core-index source adapters and five isolated acquisition subplans."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from ...application.collection import SourceAdapterRegistry
from ...application.ports import AcquisitionPlanStep, SourceCapability, SourceRequest
from ...domain.analysis import analyze_index, build_collected_core_summary
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
from .core_contracts import INDEX_SPECS, IndexSpec as CoreIndexSpecValue
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


TENCENT_CORE_QUOTE_SOURCE_ID = "core-tencent-realtime-quote"
FUYAO_CORE_HISTORY_SOURCE_ID = "core-fuyao-history"
MOOTDX_CORE_HISTORY_SOURCE_ID = "core-mootdx-history"
BAIDU_CORE_HISTORY_SOURCE_ID = "core-baidu-history"
SINA_CORE_HISTORY_SOURCE_ID = "core-sina-history"
TENCENT_CORE_HISTORY_SOURCE_ID = "core-tencent-history"
EASTMONEY_CORE_HISTORY_SOURCE_ID = "core-eastmoney-history"

CORE_HISTORY_SOURCE_ORDER = (
    FUYAO_CORE_HISTORY_SOURCE_ID,
    MOOTDX_CORE_HISTORY_SOURCE_ID,
    BAIDU_CORE_HISTORY_SOURCE_ID,
    SINA_CORE_HISTORY_SOURCE_ID,
    TENCENT_CORE_HISTORY_SOURCE_ID,
    EASTMONEY_CORE_HISTORY_SOURCE_ID,
)

_PRICE_GUARDED_CODES = frozenset({"sh000001", "sh000905"})
_INDEX_FIELDS = (
    "code",
    "name",
    "representative",
    "changePct",
    "close",
    "movingAverages",
    "history",
    "dataQuality",
)
_SHANGHAI_ZONE = ZoneInfo("Asia/Shanghai")


class CoreIndexSpec(Protocol):
    code: str
    digits: str
    name: str
    representative: str


class LegacyCoreProvider(Protocol):
    def fetch_quotes(
        self,
        specs: tuple[CoreIndexSpec, ...],
    ) -> dict[str, dict[str, Any]]: ...

    def _fetch_mootdx(self, spec: CoreIndexSpec, limit: int) -> list[Any]: ...

    def _fetch_baidu_kline(self, spec: CoreIndexSpec, limit: int) -> list[Any]: ...

    def _fetch_sina_kline(
        self,
        spec: CoreIndexSpec,
        limit: int,
        quote: dict[str, Any],
    ) -> list[Any]: ...

    def _fetch_tencent_kline(self, spec: CoreIndexSpec, limit: int) -> list[Any]: ...

    def _fetch_eastmoney_kline(self, spec: CoreIndexSpec, limit: int) -> list[Any]: ...


class FuyaoCoreClient(Protocol):
    def fetch_core(
        self,
        as_of: date,
        *,
        codes: Sequence[str] | None = None,
        limit: int = 280,
        quotes_by_code: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, FuyaoMarketResult]: ...


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
    if request.identity.dataset != "core":
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
            f"latest-only source {capability.source_id} cannot prove historical date",
            provenance=RedactedProvenance(
                attributes={"dateEvidenceKind": "latest-only"}
            ),
        )
    return None


def _index_spec(
    request: SourceRequest,
    capability: SourceCapability,
) -> CoreIndexSpec | AcquisitionFailure:
    spec = request.params.get("spec")
    if spec is None or not all(
        str(getattr(spec, name, "") or "").strip()
        for name in ("code", "digits", "name", "representative")
    ):
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONFIGURATION,
            f"{capability.source_id} requires a valid core index spec",
        )
    return spec  # type: ignore[return-value]


def _quote(request: SourceRequest) -> dict[str, Any]:
    raw = request.params.get("quote")
    return copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else {}


def _price_matches(bars: Sequence[Any], expected_price: Any) -> bool:
    if expected_price in (None, 0, "") or not bars:
        return True
    try:
        expected = float(expected_price)
        close = float(getattr(bars[-1], "close"))
    except (TypeError, ValueError, AttributeError):
        return False
    return expected != 0 and abs(close - expected) / abs(expected) <= 0.2


def _history_candidate(
    raw_bars: Sequence[Any],
    request: SourceRequest,
    capability: SourceCapability,
    *,
    spec: CoreIndexSpec,
    source: str,
    provider: str,
    warning: str | None,
    status: str,
    fetched_at: datetime,
    timings: AcquisitionTimings,
    provenance: RedactedProvenance,
    minimum_bars: int = 60,
    guarded_price: bool = False,
    source_revision: str | None = None,
) -> CollectionCandidate | AcquisitionFailure:
    bars = list(raw_bars)
    quote = _quote(request)
    expected_price = quote.get("price")
    if len(bars) < minimum_bars:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.INSUFFICIENT,
            f"{source} returned {len(bars)} bars; {minimum_bars} required",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )
    if guarded_price and spec.code in _PRICE_GUARDED_CODES and expected_price in (
        None,
        0,
        "",
    ):
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.INSUFFICIENT,
            f"{source} requires an independent Tencent quote for {spec.code}",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )
    if not _price_matches(bars, expected_price):
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONTRACT,
            f"{source} history does not match the independent Tencent quote",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )

    try:
        filtered = sorted(
            (bar for bar in bars if getattr(bar, "date") <= request.identity.as_of),
            key=lambda bar: getattr(bar, "date"),
        )
    except (TypeError, AttributeError) as exc:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONTRACT,
            f"{source} returned malformed index history: {type(exc).__name__}",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )
    if not filtered:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.DATE_MISMATCH,
            "所选日期前无历史数据",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )

    result = SimpleNamespace(bars=filtered, source=source, warning=warning)
    try:
        analysis = analyze_index(spec, filtered, result, quote)
    except Exception as exc:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.CONTRACT,
            f"{source} core normalization failed: {type(exc).__name__}",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
        )
    selected_warning = warning or analysis["dataQuality"].get("warning")
    warnings = (str(selected_warning),) if selected_warning else ()
    effective_as_of = getattr(filtered[-1], "date")
    normalized_provenance = redact_provenance(
        replace(
            provenance,
            attributes={
                **dict(provenance.attributes),
                "dateEvidenceKind": "history-bar",
                "indexCode": spec.code,
                "effectiveAsOf": effective_as_of.isoformat(),
            },
        )
    )
    revision = source_revision or capability.revision
    fingerprint = evidence_fingerprint(
        {
            "dataset": "core",
            "requestedAsOf": request.identity.as_of.isoformat(),
            "effectiveAsOf": effective_as_of.isoformat(),
            "indexCode": spec.code,
            "source": source,
            "sourceRevision": revision,
            "observations": len(filtered),
            "provenance": {
                "endpoint": normalized_provenance.endpoint,
                "engine": normalized_provenance.engine,
                **dict(normalized_provenance.attributes),
            },
        }
    )
    availability = FieldAvailability(available=_INDEX_FIELDS)
    quality = QualityMetadata(
        dataset="core-index-history",
        source=source,
        provider=provider,
        status=status,
        observations=len(filtered),
        as_of=request.identity.as_of,
        warning=selected_warning,
        warnings=warnings,
        extra={"indexCode": spec.code, "effectiveAsOf": effective_as_of.isoformat()},
        source_revision=revision,
        fetched_at=fetched_at,
        field_availability=availability,
        timings=timings,
        evidence_fingerprint=fingerprint,
        provenance=normalized_provenance,
    )
    return CollectionCandidate(
        identity=request.identity,
        payload=analysis,
        source=source,
        status=status,
        observations=len(filtered),
        warnings=warnings,
        settled=request.settled is True,
        actual_as_of=request.identity.as_of,
        quality=quality,
        source_revision=revision,
        fetched_at=fetched_at,
        field_availability=availability,
        timings=timings,
        evidence_fingerprint=fingerprint,
        provenance=normalized_provenance,
    )


@dataclass(frozen=True, slots=True)
class TencentCoreQuoteSourceAdapter:
    provider: LegacyCoreProvider
    revision: str = "tencent-core-quote-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=TENCENT_CORE_QUOTE_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            SourceCapability(
                source_id=self.source_id,
                provider="tencent",
                revision=self.revision,
                supports_historical=False,
                latest_only=True,
                supported_fields=(
                    "name",
                    "price",
                    "last_close",
                    "change_pct",
                    "amount",
                    "volume",
                    "is_stale",
                ),
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        specs = request.params.get("specs")
        if not isinstance(specs, tuple) or not specs:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.CONFIGURATION,
                "Tencent core quote adapter requires index specs",
            )
        started = time.perf_counter()
        fetched_at = self.now()
        provenance = RedactedProvenance(
            endpoint="https://qt.gtimg.cn/q=<indices>",
            engine="requests",
            attributes={"dateEvidenceKind": "latest-only"},
        )
        try:
            quotes = self.provider.fetch_quotes(specs)
        except Exception as exc:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.NETWORK,
                str(exc) or type(exc).__name__,
                retryable=True,
                fetched_at=fetched_at,
                timings=AcquisitionTimings(total_ms=_milliseconds(started)),
                provenance=provenance,
            )
        normalized = {
            str(code): copy.deepcopy(dict(value))
            for code, value in quotes.items()
            if isinstance(value, Mapping)
        }
        timings = AcquisitionTimings(total_ms=_milliseconds(started))
        normalized_provenance = redact_provenance(provenance)
        fingerprint = evidence_fingerprint(
            {
                "dataset": "core",
                "requestedAsOf": request.identity.as_of.isoformat(),
                "source": "tencent-realtime-quote",
                "sourceRevision": self.revision,
                "indexCodes": sorted(normalized),
            }
        )
        return CollectionCandidate(
            identity=request.identity,
            payload={"quotes": normalized},
            source="tencent-realtime-quote",
            status="ok" if len(normalized) == len(specs) else "partial",
            observations=len(normalized),
            warnings=(),
            settled=request.settled is True,
            actual_as_of=request.identity.as_of,
            quality=QualityMetadata(
                dataset="core-index-quotes",
                source="tencent-realtime-quote",
                provider="tencent",
                status="ok" if len(normalized) == len(specs) else "partial",
                observations=len(normalized),
                as_of=request.identity.as_of,
                source_revision=self.revision,
                fetched_at=fetched_at,
                timings=timings,
                evidence_fingerprint=fingerprint,
                provenance=normalized_provenance,
            ),
            source_revision=self.revision,
            fetched_at=fetched_at,
            timings=timings,
            evidence_fingerprint=fingerprint,
            provenance=normalized_provenance,
        )


@dataclass(frozen=True, slots=True)
class FuyaoCoreHistorySourceAdapter:
    client: FuyaoCoreClient
    revision: str = "fuyao-market-v2"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=FUYAO_CORE_HISTORY_SOURCE_ID)
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
                supported_fields=_INDEX_FIELDS,
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        invalid = _validate_request(request, self.capability)
        if invalid is not None:
            return invalid
        spec = _index_spec(request, self.capability)
        if isinstance(spec, AcquisitionFailure):
            return spec
        quote = _quote(request)
        if (
            request.current_market_date == request.identity.as_of
            and quote.get("price") in (None, "")
        ):
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.INSUFFICIENT,
                "当前日期缺少独立腾讯报价校验",
                provenance=RedactedProvenance(
                    endpoint="/api/a-share-index/prices/historical",
                    engine="requests",
                    attributes={"dateEvidenceKind": "history-bar"},
                ),
            )
        started = time.perf_counter()
        fetched_at = self.now()
        provenance = RedactedProvenance(
            endpoint="/api/a-share-index/prices/historical",
            engine="requests",
            attributes={"dateEvidenceKind": "history-bar"},
        )
        try:
            results = self.client.fetch_core(
                request.identity.as_of,
                codes=(spec.code,),
                limit=280,
                quotes_by_code={spec.code: quote} if quote else {},
            )
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
                provenance=provenance,
            )
        result = results.get(spec.code)
        timings = AcquisitionTimings(total_ms=_milliseconds(started))
        if not isinstance(result, FuyaoMarketResult):
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.CONTRACT,
                f"Fuyao core response omitted {spec.code}",
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )
        if result.status != "ok":
            message = "；".join(result.warnings) or "扶摇核心指数契约校验失败"
            return _failure(
                request,
                self.capability,
                (
                    AcquisitionFailureCategory.DATE_MISMATCH
                    if "date" in message.lower() or "日期" in message
                    else AcquisitionFailureCategory.INSUFFICIENT
                ),
                message,
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )
        revision = str(
            result.quality.get("providerRevision")
            or result.quality.get("sourceRevision")
            or self.revision
        )
        if revision != self.capability.revision:
            return _failure(
                request,
                self.capability,
                AcquisitionFailureCategory.CONFIGURATION,
                f"Fuyao core returned capability revision {revision}",
                fetched_at=fetched_at,
                timings=timings,
                provenance=provenance,
            )
        return _history_candidate(
            list(result.payload.get("bars") or ()),
            request,
            self.capability,
            spec=spec,
            source="fuyao",
            provider="fuyao",
            warning="；".join(result.warnings) or None,
            status="ok",
            fetched_at=fetched_at,
            timings=timings,
            provenance=provenance,
            minimum_bars=280,
            source_revision=revision,
        )


@dataclass(frozen=True, slots=True)
class MootdxCoreHistorySourceAdapter:
    provider: LegacyCoreProvider
    revision: str = "mootdx-core-history-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=MOOTDX_CORE_HISTORY_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            _history_capability(
                self.source_id,
                "mootdx",
                self.revision,
                methods=("TCP",),
            ),
        )

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        return _legacy_history_attempt(
            request,
            self.capability,
            fetch=lambda spec, _quote_value: self.provider._fetch_mootdx(spec, 280),
            source="mootdx",
            provider="mootdx",
            warning=None,
            status="ok",
            engine="mootdx-tcp",
            endpoint=None,
            guarded_price=True,
            now=self.now,
        )


@dataclass(frozen=True, slots=True)
class BaiduCoreHistorySourceAdapter:
    provider: LegacyCoreProvider
    revision: str = "baidu-core-history-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=BAIDU_CORE_HISTORY_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability", _history_capability(self.source_id, "baidu", self.revision))

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        return _legacy_history_attempt(
            request,
            self.capability,
            fetch=lambda spec, _quote_value: self.provider._fetch_baidu_kline(spec, 280),
            source="baidu-kline",
            provider="baidu",
            warning="通达信不可用，已降级到百度历史 K 线",
            status="fallback",
            engine="requests",
            endpoint="https://finance.pae.baidu.com/selfselect/getstockquotation",
            guarded_price=True,
            now=self.now,
        )


@dataclass(frozen=True, slots=True)
class SinaCoreHistorySourceAdapter:
    provider: LegacyCoreProvider
    revision: str = "sina-core-history-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=SINA_CORE_HISTORY_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability", _history_capability(self.source_id, "sina", self.revision))

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        return _legacy_history_attempt(
            request,
            self.capability,
            fetch=lambda spec, quote_value: self.provider._fetch_sina_kline(spec, 280, quote_value),
            source="sina-kline",
            provider="sina",
            warning="通达信和百度不可用，已降级到新浪指数 K 线；成交额按腾讯实时成交额校准估算",
            status="fallback",
            engine="requests",
            endpoint="https://quotes.sina.cn/cn/api/jsonp_v2.php/<index>/CN_MarketData.getKLineData",
            guarded_price=False,
            now=self.now,
        )


@dataclass(frozen=True, slots=True)
class TencentCoreHistorySourceAdapter:
    provider: LegacyCoreProvider
    revision: str = "tencent-core-history-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=TENCENT_CORE_HISTORY_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability", _history_capability(self.source_id, "tencent", self.revision))

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        return _legacy_history_attempt(
            request,
            self.capability,
            fetch=lambda spec, _quote_value: self.provider._fetch_tencent_kline(spec, 280),
            source="tencent-kline",
            provider="tencent",
            warning="通达信、百度和新浪不可用，已降级到腾讯历史 K 线；历史成交额可能不可用",
            status="fallback",
            engine="requests",
            endpoint="https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            guarded_price=False,
            now=self.now,
        )


@dataclass(frozen=True, slots=True)
class EastmoneyCoreHistorySourceAdapter:
    provider: LegacyCoreProvider
    revision: str = "eastmoney-core-history-v1"
    now: Callable[[], datetime] = _utc_now
    source_id: str = field(init=False, default=EASTMONEY_CORE_HISTORY_SOURCE_ID)
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability", _history_capability(self.source_id, "eastmoney", self.revision))

    def acquire(self, request: SourceRequest) -> CollectionCandidate | AcquisitionFailure:
        return _legacy_history_attempt(
            request,
            self.capability,
            fetch=lambda spec, _quote_value: self.provider._fetch_eastmoney_kline(spec, 280),
            source="eastmoney-kline",
            provider="eastmoney",
            warning="通达信、百度、新浪和腾讯不可用，已降级到东方财富历史 K 线",
            status="fallback",
            engine="requests",
            endpoint="https://push2his.eastmoney.com/api/qt/stock/kline/get",
            guarded_price=False,
            now=self.now,
        )


def _history_capability(
    source_id: str,
    provider: str,
    revision: str,
    *,
    methods: tuple[str, ...] = ("GET",),
) -> SourceCapability:
    return SourceCapability(
        source_id=source_id,
        provider=provider,
        revision=revision,
        supports_historical=True,
        supported_fields=_INDEX_FIELDS,
        methods=methods,
    )


def _legacy_history_attempt(
    request: SourceRequest,
    capability: SourceCapability,
    *,
    fetch: Callable[[CoreIndexSpec, dict[str, Any]], Sequence[Any]],
    source: str,
    provider: str,
    warning: str | None,
    status: str,
    engine: str,
    endpoint: str | None,
    guarded_price: bool,
    now: Callable[[], datetime],
) -> CollectionCandidate | AcquisitionFailure:
    invalid = _validate_request(request, capability)
    if invalid is not None:
        return invalid
    spec = _index_spec(request, capability)
    if isinstance(spec, AcquisitionFailure):
        return spec
    started = time.perf_counter()
    fetched_at = now()
    provenance = RedactedProvenance(
        endpoint=endpoint,
        engine=engine,
        attributes={"dateEvidenceKind": "history-bar", "indexCode": spec.code},
    )
    try:
        bars = fetch(spec, _quote(request))
    except Exception as exc:
        return _failure(
            request,
            capability,
            AcquisitionFailureCategory.NETWORK,
            f"{source}: {exc}",
            retryable=engine == "requests",
            fetched_at=fetched_at,
            timings=AcquisitionTimings(total_ms=_milliseconds(started)),
            provenance=provenance,
        )
    return _history_candidate(
        bars,
        request,
        capability,
        spec=spec,
        source=source,
        provider=provider,
        warning=warning,
        status=status,
        fetched_at=fetched_at,
        timings=AcquisitionTimings(total_ms=_milliseconds(started)),
        provenance=provenance,
        guarded_price=guarded_price,
    )


@dataclass(frozen=True, slots=True)
class CoreIndexAcquisitionResult:
    code: str
    candidate: CollectionCandidate | None
    failure: AcquisitionFailure | None
    attempts: tuple[AttemptEvidence, ...]
    fuyao_degraded: bool = False


@dataclass(frozen=True, slots=True)
class CoreIndexAcquisitionSubplan:
    """Acquire one index independently so sibling failures cannot abort it."""

    index_spec: CoreIndexSpec
    adapters: SourceAdapterRegistry
    plan_id: str = field(init=False)
    steps: tuple[AcquisitionPlanStep, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", f"core-index-{self.index_spec.code}-v1")
        object.__setattr__(
            self,
            "steps",
            tuple(
                AcquisitionPlanStep(
                    source_id,
                    role="formal" if index == 0 else "fallback",
                    capability_revision=self.adapters.get(source_id).capability.revision,
                )
                for index, source_id in enumerate(CORE_HISTORY_SOURCE_ORDER)
            ),
        )

    def collect(
        self,
        identity: DatasetDate,
        *,
        quote: Mapping[str, Any],
        fuyao_enabled: bool,
        fuyao_revision: str,
        current_market_date: date,
        settled: bool,
    ) -> CoreIndexAcquisitionResult:
        attempts: list[AttemptEvidence] = []
        source_ids = (
            CORE_HISTORY_SOURCE_ORDER
            if fuyao_enabled
            else CORE_HISTORY_SOURCE_ORDER[1:]
        )
        failures: list[AcquisitionFailure] = []
        for index, source_id in enumerate(source_ids):
            result = _attempt_source(
                self.adapters,
                identity,
                source_id,
                role="formal" if index == 0 else "fallback",
                current_market_date=current_market_date,
                settled=settled,
                params={"spec": self.index_spec, "quote": dict(quote)},
                attempts=attempts,
                capability_revision=(
                    fuyao_revision
                    if source_id == FUYAO_CORE_HISTORY_SOURCE_ID
                    else None
                ),
            )
            if isinstance(result, CollectionCandidate):
                if fuyao_enabled and source_id != FUYAO_CORE_HISTORY_SOURCE_ID:
                    fuyao_failure = failures[0] if failures else None
                    if fuyao_failure is not None:
                        fallback_warning = f"扶摇失败并回退：{fuyao_failure.message}"
                        analysis = copy.deepcopy(dict(result.payload))
                        quality = dict(analysis.get("dataQuality") or {})
                        quality["warning"] = "；".join(
                            value
                            for value in (
                                quality.get("warning"),
                                fallback_warning,
                            )
                            if value
                        )
                        analysis["dataQuality"] = quality
                        combined_warning = str(quality["warning"])
                        result = replace(
                            result,
                            payload=analysis,
                            warnings=(combined_warning,),
                            quality=(
                                replace(
                                    result.quality,
                                    warning=combined_warning,
                                    warnings=(combined_warning,),
                                )
                                if result.quality is not None
                                else None
                            ),
                        )
                return CoreIndexAcquisitionResult(
                    code=self.index_spec.code,
                    candidate=result,
                    failure=None,
                    attempts=tuple(attempts),
                    fuyao_degraded=fuyao_enabled
                    and source_id != FUYAO_CORE_HISTORY_SOURCE_ID,
                )
            failures.append(result)
        terminal = failures[-1]
        combined = "；".join(
            dict.fromkeys(failure.message for failure in failures)
        )
        return CoreIndexAcquisitionResult(
            code=self.index_spec.code,
            candidate=None,
            failure=replace(terminal, message=combined),
            attempts=tuple(attempts),
            fuyao_degraded=fuyao_enabled and bool(failures),
        )

    def shadow(
        self,
        identity: DatasetDate,
        *,
        quote: Mapping[str, Any],
        fuyao_revision: str,
        current_market_date: date,
        settled: bool,
    ) -> CoreIndexAcquisitionResult:
        attempts: list[AttemptEvidence] = []
        result = _attempt_source(
            self.adapters,
            identity,
            FUYAO_CORE_HISTORY_SOURCE_ID,
            role="shadow",
            current_market_date=current_market_date,
            settled=settled,
            params={"spec": self.index_spec, "quote": dict(quote)},
            attempts=attempts,
            capability_revision=fuyao_revision,
        )
        if isinstance(result, CollectionCandidate):
            return CoreIndexAcquisitionResult(
                self.index_spec.code,
                result,
                None,
                tuple(attempts),
            )
        return CoreIndexAcquisitionResult(
            self.index_spec.code,
            None,
            result,
            tuple(attempts),
        )


@dataclass(frozen=True, slots=True)
class CoreAcquisitionPlan:
    """Preserve quote cross-checks and five independently isolated indices."""

    adapters: SourceAdapterRegistry
    index_specs: tuple[CoreIndexSpec, ...]
    fuyao_is_enabled: Callable[[str], bool]
    fuyao_shadow_enabled: Callable[[str], bool]
    fuyao_revision: Callable[[str], str]
    retained_indices: Callable[[DatasetDate], Mapping[str, Mapping[str, Any]]] = (
        lambda _identity: {}
    )
    market_today: Callable[[], date] = _market_today
    is_settled: Callable[[date], bool] = lambda _as_of: True
    now: Callable[[], datetime] = _utc_now
    dataset_id: str = field(init=False, default="core")
    plan_id: str = field(init=False, default="core-acquisition-v1")
    steps: tuple[AcquisitionPlanStep, ...] = field(init=False)
    subplans: tuple[CoreIndexAcquisitionSubplan, ...] = field(init=False)

    def __post_init__(self) -> None:
        codes = tuple(spec.code for spec in self.index_specs)
        if len(codes) != 5 or len(set(codes)) != 5:
            raise ValueError("core acquisition requires five unique index specs")
        steps = (
            AcquisitionPlanStep(
                TENCENT_CORE_QUOTE_SOURCE_ID,
                role="enrichment",
                capability_revision=self.adapters.get(
                    TENCENT_CORE_QUOTE_SOURCE_ID
                ).capability.revision,
                approved_fields=("quote",),
            ),
            *tuple(
                AcquisitionPlanStep(
                    source_id,
                    role="formal" if index == 0 else "fallback",
                    capability_revision=self.adapters.get(source_id).capability.revision,
                )
                for index, source_id in enumerate(CORE_HISTORY_SOURCE_ORDER)
            ),
        )
        object.__setattr__(self, "steps", steps)
        object.__setattr__(
            self,
            "subplans",
            tuple(
                CoreIndexAcquisitionSubplan(spec, self.adapters)
                for spec in self.index_specs
            ),
        )
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
        warnings: list[str] = []
        quotes: dict[str, Any] = {}
        if identity.as_of == current_market_date:
            quote_result = _attempt_source(
                self.adapters,
                identity,
                TENCENT_CORE_QUOTE_SOURCE_ID,
                role="enrichment",
                current_market_date=current_market_date,
                settled=settled,
                params={"specs": self.index_specs},
                attempts=attempts,
            )
            if isinstance(quote_result, CollectionCandidate):
                raw_quotes = quote_result.payload.get("quotes")
                if isinstance(raw_quotes, Mapping):
                    quotes = {
                        str(code): copy.deepcopy(dict(value))
                        for code, value in raw_quotes.items()
                        if isinstance(value, Mapping)
                    }
            else:
                warnings.append(f"腾讯实时报价不可用：{quote_result.message}")

        retained_by_code = {
            str(code): copy.deepcopy(dict(value))
            for code, value in self.retained_indices(identity).items()
            if isinstance(value, Mapping)
        }
        analyses: list[dict[str, Any]] = []
        index_evidence: list[dict[str, Any]] = []
        index_sources: list[str] = []
        retained_sources: list[str] = []
        effective_dates: list[date] = []
        failures: list[AcquisitionFailure] = []
        current_successes = 0
        fuyao_degraded = False
        fuyao_enabled = self.fuyao_is_enabled(self.dataset_id)
        approved_revision = self.fuyao_revision(self.dataset_id)

        for subplan in self.subplans:
            started = time.perf_counter()
            spec = subplan.index_spec
            result = subplan.collect(
                identity,
                quote=quotes.get(spec.code, {}),
                fuyao_enabled=fuyao_enabled,
                fuyao_revision=approved_revision,
                current_market_date=current_market_date,
                settled=settled,
            )
            attempts.extend(result.attempts)
            fuyao_degraded = fuyao_degraded or result.fuyao_degraded
            if result.candidate is not None:
                analysis = copy.deepcopy(dict(result.candidate.payload))
                analyses.append(analysis)
                current_successes += 1
                index_sources.append(result.candidate.source)
                effective_date = _analysis_effective_date(analysis)
                if effective_date is not None:
                    effective_dates.append(effective_date)
                warning = (
                    result.candidate.warnings[0]
                    if result.candidate.warnings
                    else None
                )
                if warning:
                    warnings.append(f"{spec.name}：{warning}")
                index_evidence.append(
                    {
                        "code": spec.code,
                        "name": spec.name,
                        "status": CollectionTaskState.SUCCESS.value,
                        "source": result.candidate.source,
                        "observations": result.candidate.observations,
                        "warning": warning,
                        "durationMs": _milliseconds(started),
                        "retained": False,
                    }
                )
                continue

            failure = result.failure or AcquisitionFailure(
                AcquisitionFailureCategory.INTERNAL,
                f"{spec.code} acquisition failed without evidence",
                requested_as_of=identity.as_of,
            )
            failures.append(failure)
            retained = retained_by_code.get(spec.code)
            if retained is not None:
                analyses.append(retained)
                effective_date = _analysis_effective_date(retained)
                if effective_date is not None:
                    effective_dates.append(effective_date)
                source = str(
                    (retained.get("dataQuality") or {}).get("source") or "none"
                )
                retained_sources.append(source)
                state = CollectionTaskState.FAILED_RETAINED
                observations = len(retained.get("history") or ())
            else:
                source = "none"
                state = CollectionTaskState.FAILED_MISSING
                observations = 0
            warnings.append(f"{spec.name}：{failure.message}")
            index_evidence.append(
                {
                    "code": spec.code,
                    "name": spec.name,
                    "status": state.value,
                    "source": source,
                    "observations": observations,
                    "warning": failure.message,
                    "durationMs": _milliseconds(started),
                    "retained": retained is not None,
                }
            )

        if not analyses:
            failure = AcquisitionFailure(
                AcquisitionFailureCategory.INSUFFICIENT,
                "全部指数数据源不可用且没有同日期可保留结果",
                requested_as_of=identity.as_of,
            )
            return CollectionOutcome(
                identity=identity,
                state=CollectionTaskState.FAILED_MISSING,
                warning="；".join(warnings) or failure.message,
                failure=failure,
                attempts=tuple(attempts),
            )

        effective_date = min(effective_dates) if effective_dates else identity.as_of
        core_payload = {
            "asOf": effective_date.isoformat(),
            "generatedAt": self.now().isoformat(),
            "indices": analyses,
            "summary": build_collected_core_summary(analyses, warnings),
        }
        session, session_warning = _trading_session_evidence(
            identity.as_of,
            analyses,
            index_sources or retained_sources,
            self.now(),
        )
        if session_warning:
            warnings.append(session_warning)

        shadow_report = None
        if not fuyao_enabled and self.fuyao_shadow_enabled(self.dataset_id):
            shadow_indices: list[dict[str, Any]] = []
            shadow_failures: list[str] = []
            for subplan in self.subplans:
                shadow = subplan.shadow(
                    identity,
                    quote=quotes.get(subplan.index_spec.code, {}),
                    fuyao_revision=approved_revision,
                    current_market_date=current_market_date,
                    settled=settled,
                )
                attempts.extend(shadow.attempts)
                if shadow.candidate is not None:
                    shadow_indices.append(dict(shadow.candidate.payload))
                elif shadow.failure is not None:
                    shadow_failures.append(
                        f"{subplan.index_spec.name}：{shadow.failure.message}"
                    )
            shadow_payload = {
                "asOf": identity.as_of.isoformat(),
                "indices": shadow_indices,
                "quality": {
                    "status": "ok" if len(shadow_indices) == len(self.subplans) else "insufficient",
                    "source": "fuyao",
                    "providerRevision": approved_revision,
                    "observations": len(shadow_indices),
                    "asOf": identity.as_of.isoformat(),
                    "warnings": shadow_failures,
                },
            }
            shadow_report = compare_shadow(
                "core",
                core_payload,
                shadow_payload,
                formal_revision=",".join(sorted(set(index_sources))) or "retained",
                shadow_revision=approved_revision,
                as_of=identity.as_of,
            )
            if shadow_report.get("status") != "match":
                warnings.append(f"扶摇 shadow: {shadow_report.get('status')}")

        source = ",".join(sorted(set(index_sources)))
        if not source:
            source = ",".join(sorted(set(retained_sources))) or "retained"
        terminal_failure = failures[-1] if failures else None
        if current_successes == 0:
            state = CollectionTaskState.FAILED_RETAINED
            candidate_status = "partial"
        elif current_successes < len(self.index_specs) or fuyao_degraded:
            state = CollectionTaskState.PARTIAL
            candidate_status = "partial"
        else:
            state = CollectionTaskState.SUCCESS
            candidate_status = "ok"

        fetched_at = self.now()
        availability = FieldAvailability(
            available=("asOf", "generatedAt", "indices", "summary"),
            missing=tuple(
                evidence["code"]
                for evidence in index_evidence
                if evidence["status"] == CollectionTaskState.FAILED_MISSING.value
            ),
        )
        quality_extra: dict[str, Any] = {
            "indexResults": tuple(index_evidence),
            "tradingSession": session,
            "sessionWarning": session_warning,
            "effectiveAsOf": effective_date.isoformat(),
        }
        if shadow_report is not None:
            quality_extra["shadow"] = shadow_report
        provenance = redact_provenance(
            RedactedProvenance(
                attributes={
                    "dateEvidenceKind": "per-index-history",
                    "effectiveAsOf": effective_date.isoformat(),
                    "indexCount": len(analyses),
                }
            )
        )
        fingerprint = evidence_fingerprint(
            {
                "dataset": "core",
                "requestedAsOf": identity.as_of.isoformat(),
                "effectiveAsOf": effective_date.isoformat(),
                "source": source,
                "indexResults": index_evidence,
                "tradingSession": session,
            }
        )
        warning_text = "；".join(warnings) if warnings else None
        quality = QualityMetadata(
            dataset="core-indices",
            source=source,
            provider=source,
            status=candidate_status,
            observations=len(analyses),
            as_of=identity.as_of,
            warning=warning_text,
            warnings=tuple(warnings),
            extra=quality_extra,
            source_revision=self.plan_id,
            fetched_at=fetched_at,
            field_availability=availability,
            evidence_fingerprint=fingerprint,
            provenance=provenance,
        )
        candidate = CollectionCandidate(
            identity=identity,
            payload=core_payload,
            source=source,
            status=candidate_status,
            observations=len(analyses),
            warnings=tuple(warnings),
            settled=settled,
            actual_as_of=identity.as_of,
            quality=quality,
            source_revision=self.plan_id,
            fetched_at=fetched_at,
            field_availability=availability,
            evidence_fingerprint=fingerprint,
            provenance=provenance,
        )
        return CollectionOutcome(
            identity=identity,
            state=state,
            candidate=candidate,
            warning=warning_text,
            retained=state is CollectionTaskState.FAILED_RETAINED,
            failure=terminal_failure
            if state is CollectionTaskState.FAILED_RETAINED
            else None,
            attempts=tuple(attempts),
        )


def _attempt_source(
    adapters: SourceAdapterRegistry,
    identity: DatasetDate,
    source_id: str,
    *,
    role: str,
    current_market_date: date,
    settled: bool,
    params: Mapping[str, object],
    attempts: list[AttemptEvidence],
    capability_revision: str | None = None,
) -> CollectionCandidate | AcquisitionFailure:
    adapter = adapters.get(source_id)
    result = adapter.acquire(
        SourceRequest(
            identity=identity,
            source_id=source_id,
            role=role,
            params=params,
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
                engine=result.provenance.engine,
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
            source_revision=result.source_revision or adapter.capability.revision,
            engine=result.provenance.engine,
            requested_as_of=identity.as_of,
            actual_as_of=result.actual_as_of,
            timings=result.timings,
            provenance=result.provenance,
            evidence_fingerprint=result.evidence_fingerprint,
        )
    )
    return result


def _analysis_effective_date(analysis: Mapping[str, Any]) -> date | None:
    history = analysis.get("history")
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)) or not history:
        return None
    latest = history[-1]
    if not isinstance(latest, Mapping):
        return None
    try:
        return date.fromisoformat(str(latest.get("date") or ""))
    except ValueError:
        return None


def _trading_session_evidence(
    as_of: date,
    analyses: Sequence[Mapping[str, Any]],
    sources: Sequence[str],
    fetched_at: datetime,
) -> tuple[dict[str, Any] | None, str | None]:
    histories: list[list[date]] = []
    for analysis in analyses:
        parsed: list[date] = []
        history = analysis.get("history")
        if isinstance(history, Sequence) and not isinstance(history, (str, bytes)):
            for point in history:
                if not isinstance(point, Mapping) or not point.get("date"):
                    continue
                try:
                    parsed.append(date.fromisoformat(str(point["date"])))
                except ValueError:
                    continue
        if len(parsed) < 2 or parsed[-1] != as_of:
            return None, "core index history could not prove the requested session"
        histories.append(parsed)
    if not histories:
        return None, "core index history did not contain session evidence"
    previous_dates = {history[-2] for history in histories}
    if len(previous_dates) != 1:
        return None, "core indices did not agree on the previous trading session"
    previous_as_of = next(iter(previous_dates))
    return (
        {
            "asOf": as_of.isoformat(),
            "previousAsOf": previous_as_of.isoformat(),
            "isSession": True,
            "source": "core-index-history:"
            + ",".join(sorted(set(sources or ("retained",)))),
            "actualAsOf": as_of.isoformat(),
            "fetchedAt": fetched_at.isoformat(),
            "warnings": (),
        },
        None,
    )


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
    "BAIDU_CORE_HISTORY_SOURCE_ID",
    "CORE_HISTORY_SOURCE_ORDER",
    "EASTMONEY_CORE_HISTORY_SOURCE_ID",
    "FUYAO_CORE_HISTORY_SOURCE_ID",
    "MOOTDX_CORE_HISTORY_SOURCE_ID",
    "SINA_CORE_HISTORY_SOURCE_ID",
    "TENCENT_CORE_HISTORY_SOURCE_ID",
    "TENCENT_CORE_QUOTE_SOURCE_ID",
    "BaiduCoreHistorySourceAdapter",
    "CoreAcquisitionPlan",
    "CoreIndexSpecValue",
    "CoreIndexAcquisitionResult",
    "CoreIndexAcquisitionSubplan",
    "EastmoneyCoreHistorySourceAdapter",
    "FuyaoCoreHistorySourceAdapter",
    "MootdxCoreHistorySourceAdapter",
    "SinaCoreHistorySourceAdapter",
    "TencentCoreHistorySourceAdapter",
    "TencentCoreQuoteSourceAdapter",
    "INDEX_SPECS",
]
