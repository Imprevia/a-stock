"""Provider quality, fallback, and after-market snapshot boundaries."""

from __future__ import annotations

import random
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

import requests

from .provider_http import HostPolicy, ProviderHttpClient, ProviderHttpError

_GLOBAL_EASTMONEY_LIMITER: "SerialRateLimiter | None" = None

_SECTOR_RULE_TO_METRIC = {
    "QTS-01-05-01": "sector.relative_strength_percentile",
    "QTS-01-05-02": "sector.top_turnover_days",
    "QTS-01-05-03": "sector.above_ma20_ratio_percentile",
    "QTS-01-05-04": "sector.disagreement_recovery_percentile",
    "QTS-01-05-05": "sector.top5_turnover_concentration_percentile",
}


@dataclass(frozen=True)
class ProviderQuality:
    dataset: str
    provider: str
    status: str
    observations: int
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["warnings"] = list(self.warnings)
        return value


class ProviderFailure(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class SerialRateLimiter:
    """Shared serial limiter with injectable timing for deterministic tests."""

    def __init__(
        self,
        minimum_interval: float = 1.0,
        jitter: tuple[float, float] = (0.05, 0.25),
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if minimum_interval < 1.0:
            raise ValueError("Eastmoney minimum interval must be at least 1 second")
        self.minimum_interval = minimum_interval
        self.jitter = jitter
        self.clock = clock
        self.sleeper = sleeper
        self.random_uniform = random_uniform
        self._last_request_at: float | None = None
        self._request_lock = threading.Lock()

    def acquire(self) -> None:
        with self._request_lock:
            self._acquire_unlocked()

    def run(self, operation: Callable[[], Any]) -> Any:
        """Serialize the complete provider request, including rate-limit waiting."""
        with self._request_lock:
            self._acquire_unlocked()
            return operation()

    def _acquire_unlocked(self) -> None:
        now = self.clock()
        if self._last_request_at is not None:
            required = self.minimum_interval + self.random_uniform(*self.jitter)
            remaining = required - (now - self._last_request_at)
            if remaining > 0:
                self.sleeper(remaining)
                now = self.clock()
        self._last_request_at = now


class EastmoneyClient:
    """Rate-limited shared Eastmoney session; HTTP 403 is never retried blindly."""

    def __init__(
        self,
        timeout: float = 8.0,
        limiter: SerialRateLimiter | None = None,
        session: requests.Session | None = None,
        retry_total: int = 2,
        retry_backoff: float = 0.6,
        transport: ProviderHttpClient | None = None,
    ) -> None:
        global _GLOBAL_EASTMONEY_LIMITER
        self.timeout = timeout
        if _GLOBAL_EASTMONEY_LIMITER is None:
            _GLOBAL_EASTMONEY_LIMITER = SerialRateLimiter()
        self.limiter = limiter or _GLOBAL_EASTMONEY_LIMITER
        self.session = session or requests.Session()
        self.transport = transport or ProviderHttpClient(
            session=self.session,
            default_policy=HostPolicy(
                minimum_interval=0.0,
                jitter=(0.0, 0.0),
                timeout=timeout,
                max_retries=retry_total,
                retry_backoff=retry_backoff,
                cache_ttl_seconds=0.0,
            ),
        )
        self._requested_date: ContextVar[str | None] = ContextVar(
            f"eastmoney-requested-date-{id(self)}",
            default=None,
        )
        self._source_id: ContextVar[str | None] = ContextVar(
            f"eastmoney-source-id-{id(self)}",
            default=None,
        )

    @contextmanager
    def request_identity(
        self,
        *,
        requested_date: str | None = None,
        source_id: str | None = None,
    ):
        """Bind transport identity without changing the legacy two-arg API."""

        date_token = self._requested_date.set(requested_date)
        source_token = self._source_id.set(source_id)
        try:
            yield
        finally:
            self._source_id.reset(source_token)
            self._requested_date.reset(date_token)

    def get_json(
        self,
        url: str,
        params: dict[str, Any],
        *,
        requested_date: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.transport.get(
                url,
                params=params,
                timeout=self.timeout,
                cache_ttl=0.0,
                requested_date=requested_date or self._requested_date.get(),
                source_id=source_id or self._source_id.get(),
                gate=self.limiter.run,
            )
        except ProviderHttpError as exc:
            raise ProviderFailure(
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        return response.json()


class FallbackChain:
    """Run providers serially and retain an auditable degradation record."""

    def __init__(self, providers: Iterable[tuple[str, Callable[[], Any]]]) -> None:
        self.providers = tuple(providers)

    def fetch(self, dataset: str) -> tuple[Any | None, ProviderQuality]:
        warnings: list[str] = []
        for index, (name, provider) in enumerate(self.providers):
            try:
                value = provider()
                status = "ok" if index == 0 else "fallback"
                return value, ProviderQuality(dataset, name, status, _observation_count(value), tuple(warnings))
            except ProviderFailure as exc:
                warnings.append(f"{name}: {exc}")
            except Exception as exc:  # provider boundary must preserve later fallbacks
                warnings.append(f"{name}: {exc}")
        return None, ProviderQuality(dataset, "none", "failed", 0, tuple(warnings))


def _observation_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, dict, set)):
        return len(value)
    return 1


def _sector_analysis(payload: dict[str, Any], as_of: date) -> dict[str, Any] | None:
    analysis = (payload.get("chapter01") or {}).get("sectorAnalysis")
    if not isinstance(analysis, dict) or analysis.get("asOf") != as_of.isoformat():
        return None
    return analysis


def _provenance_entry(analysis: dict[str, Any], trace: dict[str, Any], as_of: date) -> dict[str, Any] | None:
    quality = analysis.get("quality") if isinstance(analysis.get("quality"), dict) else {}
    lineage = analysis.get("lineage") if isinstance(analysis.get("lineage"), dict) else {}
    history = analysis.get("history") if isinstance(analysis.get("history"), dict) else {}
    versions = lineage.get("versions") if isinstance(lineage.get("versions"), dict) else lineage
    analysis_quality = trace.get("status") or quality.get("status") or analysis.get("status")
    if analysis_quality not in {"ok", "partial", "degraded", "reduced-confidence"}:
        return None
    history_coverage = history.get("coverage", quality.get("coverage", analysis.get("coverage")))
    constituent_coverage = trace.get("raw", {}).get("constituentCoverage", quality.get("constituentCoverage", analysis.get("coverage")))
    version_keys = {
        "dataVersion": ("dataVersion", "marketDataVersion"),
        "classificationVersion": ("classificationVersion", "taxonomyVersion"),
        "membershipVersion": ("membershipVersion",),
        "universeVersion": ("universeVersion",),
        "adjustmentVersion": ("adjustmentVersion",),
        "benchmarkVersion": ("benchmarkVersion",),
        "calculationVersion": ("calculationVersion",),
    }
    result: dict[str, Any] = {
        "sourceDataset": "sector-continuity-analysis",
        "actualDate": analysis.get("asOf"),
        "analysisQuality": analysis_quality,
        "historyCoverage": history_coverage,
        "constituentCoverage": constituent_coverage,
        "evidenceReferences": sorted(set(lineage.get("evidenceReferences") or trace.get("evidenceReferences") or [])),
        "upstreamEvidenceChecksums": sorted(set(lineage.get("evidenceChecksums") or lineage.get("upstreamEvidenceChecksums") or [])),
    }
    for target, candidates in version_keys.items():
        result[target] = next((versions.get(key) for key in candidates if versions.get(key)), None)
    required = (
        "actualDate", "historyCoverage", "constituentCoverage", "dataVersion",
        "classificationVersion", "membershipVersion", "universeVersion",
        "adjustmentVersion", "benchmarkVersion", "calculationVersion",
    )
    if any(result.get(key) is None for key in required):
        return None
    try:
        result["historyCoverage"] = float(result["historyCoverage"])
        result["constituentCoverage"] = float(result["constituentCoverage"])
    except (TypeError, ValueError):
        return None
    if result["actualDate"] != as_of.isoformat():
        return None
    return result


def _bridge_sector_metrics(payload: dict[str, Any], as_of: date) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    analysis = _sector_analysis(payload, as_of)
    if analysis is None:
        return {}, {}, ["same-date sector continuity analysis is unavailable"]
    candidates = analysis.get("candidates") if isinstance(analysis.get("candidates"), list) else []
    first = candidates[0] if candidates and isinstance(candidates[0], dict) else None
    candidate_traces = first.get("ruleTraces", []) if first else []
    market_traces = analysis.get("metricTraces") if isinstance(analysis.get("metricTraces"), list) else []
    traces: dict[str, dict[str, Any]] = {}
    for trace in [*candidate_traces, *market_traces]:
        if isinstance(trace, dict) and trace.get("ruleId") in _SECTOR_RULE_TO_METRIC:
            traces[str(trace["ruleId"])] = trace
    metrics: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    warnings: list[str] = []
    for rule_id, metric_name in _SECTOR_RULE_TO_METRIC.items():
        if rule_id != "QTS-01-05-05" and first is None:
            continue
        trace = traces.get(rule_id)
        if not trace:
            continue
        value = trace.get("value")
        if rule_id != "QTS-01-05-02":
            value = trace.get("percentile")
        entry = _provenance_entry(analysis, trace, as_of)
        if value is None or entry is None:
            warnings.append(f"{metric_name} omitted because value or provenance is incomplete")
            continue
        metrics[metric_name] = value
        provenance[metric_name] = entry
    return metrics, provenance, warnings


def create_after_market_snapshot(as_of: date, service: Any | None = None) -> dict[str, Any]:
    """Create a real-data partial snapshot without inventing unavailable breadth data.

    The existing market-environment service supplies the index slice. Chapter 01
    needs several additional datasets, so this first-stage provider deliberately
    marks the snapshot insufficient until those inputs are connected.
    """

    from src.market_environment.service import MarketEnvironmentService

    market_service = service or MarketEnvironmentService()
    created_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    try:
        payload = market_service.get(as_of)
    except Exception as exc:
        return {
            "schemaVersion": 2,
            "asOf": as_of.isoformat(),
            "createdAt": created_at,
            "status": "insufficient",
            "providerQuality": [ProviderQuality("index-daily", "fallback-chain", "failed", 0, (str(exc),)).to_dict()],
            "metrics": {},
            "metricProvenance": {},
            "events": [],
            "warnings": [f"index provider failed: {exc}", "chapter 01 requires breadth, limit, sector, active-security, and event datasets"],
        }

    indices = payload.get("indices", [])
    valid_ma = [
        item
        for item in indices
        if all(item.get("movingAverages", {}).get(key) is not None for key in ("ma5", "ma10", "ma20"))
    ]
    bullish = [
        item
        for item in valid_ma
        if item["close"] > item["movingAverages"]["ma5"] > item["movingAverages"]["ma10"] > item["movingAverages"]["ma20"]
    ]
    positions = [item.get("rangePosition60") for item in indices if item.get("rangePosition60") is not None]
    turnover = [item.get("amountRatio20") for item in indices if item.get("amountRatio20") is not None]
    warnings = list(payload.get("summary", {}).get("warnings", []))
    sector_metrics, metric_provenance, sector_warnings = _bridge_sector_metrics(payload, as_of)
    warnings.extend(sector_warnings)
    warnings.append("chapter 01 breadth, limit, tier-risk, active-security, and event datasets are not yet fully connected")
    sources = sorted({item.get("dataQuality", {}).get("source", "unknown") for item in indices})
    status = "fallback" if warnings else "ok"
    return {
        "schemaVersion": 2,
        "asOf": payload.get("asOf", as_of.isoformat()),
        "createdAt": payload.get("generatedAt", created_at),
        "status": "insufficient",
        "providerQuality": [
            ProviderQuality("index-daily", "+".join(sources), status, len(indices), tuple(warnings[:-1])).to_dict(),
            ProviderQuality("chapter-01-extended", "not-connected", "missing", 0, (warnings[-1],)).to_dict(),
        ],
        "metrics": {
            "index.bullish_ratio": len(bullish) / len(valid_ma) if valid_ma else None,
            "index.range_position_60": sum(positions) / len(positions) if positions else None,
            "market.turnover_ratio_20": sum(turnover) / len(turnover) if turnover else None,
            **sector_metrics,
        },
        "metricProvenance": metric_provenance,
        "events": [],
        "warnings": warnings,
    }
