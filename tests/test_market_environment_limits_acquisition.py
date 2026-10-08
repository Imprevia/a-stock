from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from src.market_environment.application.collection import SourceAdapterRegistry
from src.market_environment.application.ports import SourceCapability, SourceRequest
from src.market_environment.domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    CollectionCandidate,
    CollectionTaskState,
    DatasetDate,
    QualityMetadata,
)
from src.market_environment.infrastructure.legacy.providers import MarketDataProvider
from src.market_environment.infrastructure.providers.fuyao.limits_client import (
    FuyaoConfigurationError,
    FuyaoLimitDataset,
    FuyaoPoolResult,
)
from src.market_environment.infrastructure.providers.limits_acquisition import (
    EASTMONEY_LIMITS_SOURCE_ID,
    FUYAO_LIMITS_SOURCE_ID,
    LEGACY_LIMITS_SUMMARY_SOURCE_ID,
    EastmoneyLimitsSourceAdapter,
    FuyaoLimitsSourceAdapter,
    LegacyLimitsSummarySourceAdapter,
    LimitsAcquisitionPlan,
    LimitsCollectionCandidate,
)


AS_OF = date(2026, 9, 18)
PREVIOUS = date(2026, 9, 17)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)


def _summary_payload(*, source: str = "fixture-summary", limit_up: int = 2) -> dict:
    return {
        "limitUpCount": limit_up,
        "limitDownCount": 1,
        "failedLimitUpCount": 1,
        "failedLimitUpRatio": round(1 / (limit_up + 1), 4),
        "maxStreak": 2,
        "state": "已观测",
        "quality": {
            "dataset": "limit-pools",
            "source": source,
            "provider": source,
            "status": "ok",
            "observations": limit_up + 2,
            "asOf": AS_OF.isoformat(),
            "warning": None,
            "warnings": [],
        },
    }


class SummaryProvider:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = copy.deepcopy(payload or _summary_payload())
        self.calls: list[date] = []

    def fetch_chapter01_limits(self, as_of: date) -> dict:
        self.calls.append(as_of)
        return copy.deepcopy(self.payload)


class StubFuyao:
    configured = True

    def __init__(self, result: FuyaoLimitDataset | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def require_configured(self) -> None:
        if not self.configured:
            raise FuyaoConfigurationError("MARKET_ENVIRONMENT_FUYAO_API_KEY is required")

    def fetch_trading_days(self) -> tuple[date, ...]:
        self.calls.append("calendar")
        if self.error is not None:
            raise self.error
        return (PREVIOUS, AS_OF)

    def fetch_limit_dataset(self, as_of: date, *, trading_days=None) -> FuyaoLimitDataset:
        self.calls.append("dataset")
        if self.error is not None:
            raise self.error
        assert as_of == AS_OF
        assert trading_days == (PREVIOUS, AS_OF)
        assert self.result is not None
        return self.result


class MissingKeyFuyao(StubFuyao):
    configured = False


class DatasetFailureFuyao(StubFuyao):
    def fetch_limit_dataset(self, as_of: date, *, trading_days=None) -> FuyaoLimitDataset:
        self.calls.append("dataset")
        raise RuntimeError("dated pool unavailable")


def _fuyao_dataset(*, up_codes: tuple[str, ...] = ("600001",)) -> FuyaoLimitDataset:
    tickers = {
        f"{code}.SH": {
            "thscode": f"{code}.SH",
            "ticker": code,
            "name": f"样本{code}",
            "exchange": "SH",
            "list_date": "2020-01-02",
        }
        for code in up_codes
    }
    rows = tuple(
        {
            "thscode": f"{code}.SH",
            "ticker": code,
            "name": f"样本{code}",
            "is_st": False,
            "is_new": False,
            "last_price": 11,
            "price_change_ratio_pct": 10,
            "limit_up_time": "09:35",
            "limit_up_reason": "fixture",
            "continue_day_cnt": 2,
            "seal_money": 1_000_000,
            "max_seal_money": 2_000_000,
        }
        for code in up_codes
    )
    return FuyaoLimitDataset(
        as_of=AS_OF,
        pools={
            "limit_up": FuyaoPoolResult(rows, len(rows), 1),
            "failed_limit_up": FuyaoPoolResult((), 0, 0),
            "limit_down": FuyaoPoolResult((), 0, 0),
        },
        tickers=tickers,
    )


def _install_eastmoney_pools(provider: MarketDataProvider, *, up_codes=("600001",)) -> None:
    pools = {
        "getTopicZTPool": [
            {
                "m": "1",
                "c": code,
                "n": f"样本{code}",
                "board": "main",
                "is_st": False,
                "listing_days": 1000,
                "limit_regime": "pct:10",
                "close_price": 11,
                "previous_close": 10,
                "touched_limit_up": True,
                "closed_limit_up": True,
                "streak_days": 2,
            }
            for code in up_codes
        ],
        "getTopicZBPool": [],
        "getTopicDTPool": [],
    }
    provider.eastmoney.get_json = lambda url, _params, **_kwargs: {
        "data": {"pool": copy.deepcopy(pools[url.rsplit("/", 1)[-1]])}
    }


def _plan(
    provider: MarketDataProvider,
    *,
    detail_enabled: bool,
    shadow_enabled: bool = False,
    previous_session=None,
    summary_provider=None,
) -> LimitsAcquisitionPlan:
    adapters = SourceAdapterRegistry(
        (
            FuyaoLimitsSourceAdapter(provider, now=lambda: NOW),
            EastmoneyLimitsSourceAdapter(provider, now=lambda: NOW),
            LegacyLimitsSummarySourceAdapter(
                summary_provider or provider,
                now=lambda: NOW,
            ),
        )
    )
    return LimitsAcquisitionPlan(
        adapters,
        limits_v1_enabled=detail_enabled,
        fuyao_shadow_enabled=lambda _dataset: shadow_enabled,
        market_today=lambda: AS_OF,
        is_settled=lambda _as_of: True,
        previous_session=previous_session,
    )


def test_legacy_summary_candidate_matches_fixture_without_detail_fields() -> None:
    summary = SummaryProvider()
    provider = MarketDataProvider(fuyao=MissingKeyFuyao())

    outcome = _plan(
        provider,
        detail_enabled=False,
        summary_provider=summary,
    ).collect(DatasetDate("limits", AS_OF))

    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert outcome.candidate.payload == _summary_payload()
    assert outcome.candidate.source == "fixture-summary"
    assert summary.calls == [AS_OF]
    assert [(attempt.role, attempt.source) for attempt in outcome.attempts] == [
        ("formal", "fixture-summary")
    ]
    assert all(field not in outcome.candidate.payload for field in ("securityDetails", "poolQuality"))


def test_v1_plan_matches_legacy_fuyao_eastmoney_payload_and_normalization() -> None:
    baseline_provider = MarketDataProvider(fuyao=StubFuyao(_fuyao_dataset()))
    _install_eastmoney_pools(baseline_provider, up_codes=("600001", "600002"))
    baseline = baseline_provider.fetch_chapter01_limit_dataset_strict(AS_OF)

    provider = MarketDataProvider(fuyao=StubFuyao(_fuyao_dataset()))
    _install_eastmoney_pools(provider, up_codes=("600001", "600002"))
    outcome = _plan(
        provider,
        detail_enabled=True,
        previous_session=lambda _as_of: PREVIOUS,
    ).collect(DatasetDate("limits", AS_OF))

    assert outcome.candidate is not None
    assert isinstance(outcome.candidate, LimitsCollectionCandidate)
    assert outcome.candidate.payload == baseline.payload
    assert outcome.candidate.normalization is not None
    assert (
        outcome.candidate.normalization.dataset_checksum
        == baseline.normalization.dataset_checksum
    )
    def logical_rows(rows):
        result = []
        for row in rows:
            value = row.logical_dict()
            value.pop("fetched_at", None)
            result.append(value)
        return result

    assert logical_rows(outcome.candidate.normalization.rows) == logical_rows(
        baseline.normalization.rows
    )
    assert outcome.candidate.previous_as_of == PREVIOUS
    assert outcome.candidate.source == baseline.payload["quality"]["source"]
    assert [(attempt.role, attempt.source) for attempt in outcome.attempts] == [
        ("formal", "fuyao"),
        ("formal", "eastmoney-push2ex"),
    ]


def test_missing_fuyao_api_key_fails_closed_before_eastmoney() -> None:
    provider = MarketDataProvider(fuyao=MissingKeyFuyao(), require_fuyao_for_limits=True)
    eastmoney_calls: list[str] = []
    provider.eastmoney.get_json = (
        lambda url, _params, **_kwargs: eastmoney_calls.append(url)
    )

    outcome = _plan(provider, detail_enabled=True).collect(DatasetDate("limits", AS_OF))

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert outcome.failure is not None
    assert outcome.failure.category is AcquisitionFailureCategory.CONFIGURATION
    assert len(outcome.attempts) == 1
    assert eastmoney_calls == []


def test_v1_enabled_does_not_repeat_successful_fuyao_as_shadow() -> None:
    fuyao = StubFuyao(_fuyao_dataset())
    provider = MarketDataProvider(fuyao=fuyao)
    _install_eastmoney_pools(provider)

    outcome = _plan(
        provider,
        detail_enabled=True,
        shadow_enabled=True,
    ).collect(DatasetDate("limits", AS_OF))

    assert outcome.candidate is not None
    assert fuyao.calls == ["calendar", "dataset"]
    assert all(attempt.role != "shadow" for attempt in outcome.attempts)


def test_v1_fallback_does_not_retry_failed_fuyao_as_shadow() -> None:
    fuyao = DatasetFailureFuyao()
    provider = MarketDataProvider(fuyao=fuyao)
    _install_eastmoney_pools(provider)

    outcome = _plan(
        provider,
        detail_enabled=True,
        shadow_enabled=True,
    ).collect(DatasetDate("limits", AS_OF))

    assert outcome.candidate is not None
    assert outcome.candidate.source == "eastmoney-push2ex"
    assert fuyao.calls == ["calendar", "dataset"]
    assert all(attempt.role != "shadow" for attempt in outcome.attempts)


def test_calendar_failure_keeps_eastmoney_empty_pools_unconfirmed_like_legacy() -> None:
    baseline_provider = MarketDataProvider(fuyao=StubFuyao(error=RuntimeError("calendar unavailable")))
    _install_eastmoney_pools(baseline_provider, up_codes=())
    baseline = baseline_provider.fetch_chapter01_limit_dataset_strict(AS_OF)

    provider = MarketDataProvider(fuyao=StubFuyao(error=RuntimeError("calendar unavailable")))
    _install_eastmoney_pools(provider, up_codes=())
    outcome = _plan(provider, detail_enabled=True).collect(DatasetDate("limits", AS_OF))

    assert isinstance(outcome.candidate, LimitsCollectionCandidate)
    assert outcome.candidate.payload == baseline.payload
    assert outcome.candidate.normalization == baseline.normalization
    assert outcome.candidate.payload["limitUpCount"] is None
    assert outcome.candidate.payload["limitDownCount"] is None
    assert outcome.candidate.payload["failedLimitUpCount"] is None


def test_fallback_preserves_detail_field_exclusions_and_promotion_manifest() -> None:
    def install_excluded_pool(provider: MarketDataProvider) -> None:
        pools = {
            "getTopicZTPool": [
                {
                    "m": "1",
                    "c": "600001",
                    "n": "ST fixture",
                    "board": "main",
                    "is_st": True,
                    "listing_days": 1000,
                    "limit_regime": "pct:10",
                    "close_price": 11,
                    "previous_close": 10,
                    "touched_limit_up": True,
                    "closed_limit_up": True,
                    "streak_days": 2,
                }
            ],
            "getTopicZBPool": [],
            "getTopicDTPool": [],
        }
        provider.eastmoney.get_json = lambda url, _params, **_kwargs: {
            "data": {"pool": copy.deepcopy(pools[url.rsplit("/", 1)[-1]])}
        }

    baseline_provider = MarketDataProvider(fuyao=DatasetFailureFuyao())
    install_excluded_pool(baseline_provider)
    baseline = baseline_provider.fetch_chapter01_limit_dataset_strict(AS_OF)

    provider = MarketDataProvider(fuyao=DatasetFailureFuyao())
    install_excluded_pool(provider)
    outcome = _plan(provider, detail_enabled=True).collect(DatasetDate("limits", AS_OF))

    assert isinstance(outcome.candidate, LimitsCollectionCandidate)
    normalization = outcome.candidate.normalization
    assert normalization is not None
    assert normalization.dataset_checksum == baseline.normalization.dataset_checksum
    assert normalization.excluded == baseline.normalization.excluded == 1
    assert normalization.rule_version == baseline.normalization.rule_version == "limits-promotion-v2"
    assert normalization.membership_complete is baseline.normalization.membership_complete is True
    assert normalization.rows[0].invalid_reason == baseline.normalization.rows[0].invalid_reason == "st-security"


@dataclass(frozen=True, slots=True)
class FixedAdapter:
    source_id: str
    payload: dict
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            SourceCapability(self.source_id, self.source_id, "r1"),
        )

    def acquire(self, request: SourceRequest):
        quality_payload = self.payload["quality"]
        return CollectionCandidate(
            identity=request.identity,
            payload=copy.deepcopy(self.payload),
            source=str(quality_payload["source"]),
            status=str(quality_payload["status"]),
            observations=int(quality_payload["observations"]),
            warnings=tuple(quality_payload["warnings"]),
            settled=True,
            actual_as_of=request.identity.as_of,
            quality=QualityMetadata(
                dataset="limit-pools",
                source=str(quality_payload["source"]),
                provider=self.source_id,
                status=str(quality_payload["status"]),
                observations=int(quality_payload["observations"]),
                as_of=request.identity.as_of,
            ),
        )


@dataclass(frozen=True, slots=True)
class NeverAdapter:
    source_id: str
    capability: SourceCapability = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability", SourceCapability(self.source_id, "fixture", "r1"))

    def acquire(self, request: SourceRequest):
        return AcquisitionFailure(
            AcquisitionFailureCategory.INTERNAL,
            "unexpected fixture call",
            source=request.source_id,
        )


def test_shadow_evidence_never_replaces_legacy_formal_payload() -> None:
    formal_payload = _summary_payload(source="formal", limit_up=2)
    shadow_payload = _summary_payload(source="fuyao-shadow", limit_up=3)
    adapters = SourceAdapterRegistry(
        (
            FixedAdapter(FUYAO_LIMITS_SOURCE_ID, shadow_payload),
            NeverAdapter(EASTMONEY_LIMITS_SOURCE_ID),
            FixedAdapter(LEGACY_LIMITS_SUMMARY_SOURCE_ID, formal_payload),
        )
    )
    plan = LimitsAcquisitionPlan(
        adapters,
        limits_v1_enabled=False,
        fuyao_shadow_enabled=lambda _dataset: True,
        market_today=lambda: AS_OF,
        is_settled=lambda _as_of: True,
    )

    outcome = plan.collect(DatasetDate("limits", AS_OF))

    assert outcome.candidate is not None
    assert outcome.candidate.payload == formal_payload
    assert outcome.candidate.source == "formal"
    assert [attempt.role for attempt in outcome.attempts] == ["formal", "shadow"]
    assert "comparison" in outcome.attempts[-1].provenance.attributes
