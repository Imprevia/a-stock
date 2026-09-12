from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from src.market_environment import api
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.limit_facts import normalize_limit_pools
from src.market_environment.limit_promotion import limit_v1_enabled
from src.market_environment.providers import LimitProviderDatasetResult, MarketDataProvider
from src.market_environment.schemas import MarketEnvironmentResponse
from src.market_environment.service import MARKET_TIME_ZONE, MarketEnvironmentService
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore, TradingSessionRecord
from tests.test_market_environment_service import SectionProvider, make_bars


CURRENT = make_bars()[-1].date
PREVIOUS = make_bars()[-2].date
MARKET_NOW = datetime.combine(CURRENT, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
LIMIT_PROVIDER_FIXTURE = Path(__file__).parent / "fixtures/market-environment/limit-provider-date-evidence.json"


def limit_row(code: str, *, streak: int = 2) -> dict:
    return {
        "m": "1",
        "c": code,
        "n": f"样本{code}",
        "board": "main",
        "is_st": False,
        "listing_days": 1000,
        "limit_regime": "pct:10",
        "close_price": 11.0,
        "previous_close": 10.0,
        "touched_limit_up": True,
        "closed_limit_up": True,
        "streak_days": streak,
    }


def limit_result(as_of: date, codes: list[str], *, extra_rows: list[dict] | None = None):
    up_rows = [limit_row(code, streak=index % 5 + 1) for index, code in enumerate(codes)]
    up_rows.extend(extra_rows or [])
    failed = [{**limit_row("601000"), "closed_limit_up": False, "streak_days": None}]
    down = [{**limit_row("601001"), "touched_limit_up": False, "closed_limit_up": None, "streak_days": None}]
    pools = {"limit_up": up_rows, "failed_limit_up": failed, "limit_down": down}
    normalization = normalize_limit_pools(
        pools,
        as_of=as_of,
        actual_as_of=as_of,
        source="fixture-adjacent-sessions",
        source_revision="fixture-limits-v1",
        rule_version="limits-promotion-v1",
        fetched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    failed_ratio = round(1 / (len(up_rows) + 1), 4)
    payload = {
        "limitUpCount": len(up_rows),
        "limitDownCount": 1,
        "failedLimitUpCount": 1,
        "failedLimitUpRatio": failed_ratio,
        "maxStreak": max((row.get("streak_days") or 0 for row in up_rows), default=0) or None,
        "state": "observed",
        "quality": {
            "dataset": "limit-pools",
            "source": "fixture-adjacent-sessions",
            "provider": "fixture-adjacent-sessions",
            "status": "ok",
            "observations": len(up_rows) + 2,
            "asOf": as_of.isoformat(),
            "warning": None,
            "warnings": [],
        },
    }
    return LimitProviderDatasetResult(payload, normalization)


def malformed_limit_result(case_name: str, as_of: date = CURRENT) -> LimitProviderDatasetResult:
    fixture = json.loads(LIMIT_PROVIDER_FIXTURE.read_text(encoding="utf-8"))
    case = fixture[case_name]
    by_endpoint = {
        "getTopicZTPool": "limit_up",
        "getTopicZBPool": "failed_limit_up",
        "getTopicDTPool": "limit_down",
    }
    provider = MarketDataProvider()

    def fake_get_json(url, _params):
        endpoint = url.rsplit("/", 1)[-1]
        return {"data": {"date": as_of.strftime("%Y%m%d"), "pool": case["pools"][by_endpoint[endpoint]]}}

    provider.eastmoney.get_json = fake_get_json
    return provider.fetch_chapter01_limit_dataset(as_of)


class DetailedLimitProvider:
    def __init__(self, results: dict[date, LimitProviderDatasetResult], *, fail_on: set[date] | None = None):
        self.results = results
        self.fail_on = fail_on or set()
        self.calls: list[date] = []

    def fetch_chapter01_limit_dataset(self, as_of: date):
        self.calls.append(as_of)
        if as_of in self.fail_on:
            raise RuntimeError("fixture limit detail failure")
        return self.results[as_of]

    def fetch_chapter01_limits(self, as_of: date):
        self.calls.append(as_of)
        if as_of in self.fail_on:
            raise RuntimeError("fixture limit detail failure")
        return self.results[as_of].payload


def seed_store(tmp_path) -> tuple[SnapshotStore, MarketEnvironmentService]:
    store = SnapshotStore(tmp_path / "limits.sqlite3")
    core_service = MarketEnvironmentService(provider=SectionProvider(), persistent_cache=False)
    core = core_service._get_core(CURRENT)
    store.put(
        SnapshotRecord(
            "core",
            CURRENT,
            core_service._core_payload(core),
            "fixture",
            "ok",
            5,
            (),
            MARKET_NOW,
            True,
        )
    )
    store.put_trading_session(
        TradingSessionRecord(PREVIOUS, None, True, "fixture", actual_as_of=PREVIOUS, fetched_at=MARKET_NOW)
    )
    store.put_trading_session(
        TradingSessionRecord(CURRENT, PREVIOUS, True, "fixture", actual_as_of=CURRENT, fetched_at=MARKET_NOW)
    )
    service = MarketEnvironmentService(
        provider=DetailedLimitProvider({}),
        snapshot_store=store,
        persistent_cache=True,
        local_reads_only=True,
        now=lambda: MARKET_NOW,
    )
    return store, service


def test_default_flag_is_off(monkeypatch) -> None:
    monkeypatch.delenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", raising=False)
    assert limit_v1_enabled() is False


def test_paired_collection_materializes_strict_20_of_8_and_rolls_back_non_destructively(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    previous_codes = [f"600{index:03d}" for index in range(20)]
    current_codes = previous_codes[:8] + ["600100"]  # current-only first board
    previous_result = limit_result(PREVIOUS, previous_codes)
    current_result = limit_result(CURRENT, current_codes)
    current_result.payload["continuousStrength"] = {
        "status": "insufficient",
        "count": 999,
        "ruleVersion": "unapproved-fixture",
    }
    provider = DetailedLimitProvider({PREVIOUS: previous_result, CURRENT: current_result})
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    )

    result = coordinator.collect(CURRENT, ["limits"])
    payload = service.get(CURRENT)
    limits = payload["chapter01"]["limits"]

    assert result.run.status == "success"
    assert {
        "leaseWaitMs",
        "previousLeaseWaitMs",
        "previousProviderCollectionMs",
        "providerCollectionMs",
        "storeWriteMs",
        "aggregateRebuildMs",
    } <= set(result.tasks[0].timings)
    assert provider.calls == [PREVIOUS, CURRENT]
    assert limits["yesterdayLimitUpEligible"] == 20
    assert limits["todayPromoted"] == 8
    assert limits["promotionRatio"] == 0.4
    assert limits["promotionPreviousAsOf"] == PREVIOUS.isoformat()
    assert limits["promotionSampleAsOf"] == CURRENT.isoformat()
    assert limits["promotionQuality"]["status"] == "ok"
    assert set(limits["fieldQuality"]) == {
        "todayPromoted",
        "yesterdayLimitUpEligible",
        "promotionRatio",
    }
    assert "ladder" in limits
    assert limits["ladder"]
    assert "continuousStrength" not in limits
    assert {fact.streak_days for fact in store.get_limit_security_facts(CURRENT) if fact.pool_type == "limit_up"} >= {
        1,
        2,
        3,
        4,
    }
    MarketEnvironmentResponse.model_validate(payload)

    first_checksum = store.get_limit_security_dataset(CURRENT)["dataset_checksum"]
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute(
            "SELECT count(*) FROM schema_migrations WHERE version IN (1, 2)"
        ).fetchone()[0] == 2
    repeated = coordinator.collect(CURRENT, ["limits"])
    assert repeated.run.status == "success"
    assert provider.calls == [PREVIOUS, CURRENT, CURRENT]
    assert store.get_limit_security_dataset(CURRENT)["dataset_checksum"] == first_checksum

    calls_before_get = list(provider.calls)
    assert service.get(CURRENT)["chapter01"]["limits"]["promotionRatio"] == 0.4
    assert provider.calls == calls_before_get

    monkeypatch.setattr(api, "service", service)
    response = TestClient(api.app).get(
        "/api/market-environment/chapter-01",
        params={"as_of": CURRENT.isoformat(), "section": "limits"},
    )
    assert response.status_code == 200
    assert response.json()["chapter01"]["limits"]["promotionRatio"] == 0.4
    assert provider.calls == calls_before_get

    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "0")
    rolled_back = service.get(CURRENT)["chapter01"]["limits"]
    assert "promotionRatio" not in rolled_back
    assert rolled_back["limitUpCount"] == len(current_codes)
    assert rolled_back["limitDownCount"] == 1
    assert rolled_back["failedLimitUpCount"] == 1
    assert rolled_back["failedLimitUpRatio"] == round(1 / (len(current_codes) + 1), 4)
    assert rolled_back["maxStreak"] is not None
    assert store.get_limit_security_dataset(CURRENT)["dataset_checksum"] == first_checksum
    assert len(store.get_limit_security_facts(CURRENT)) > 0

    response = TestClient(api.app).get(
        "/api/market-environment/chapter-01",
        params={"as_of": CURRENT.isoformat(), "section": "limits"},
    )
    assert response.status_code == 200
    assert response.json()["chapter01"]["limits"]["promotionRatio"] is None

    detail_checksum = store.get_limit_security_dataset(CURRENT)["dataset_checksum"]
    disabled_provider = DetailedLimitProvider({CURRENT: limit_result(CURRENT, ["600999"])})
    disabled = CollectionCoordinator(
        disabled_provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=False,
    ).collect(CURRENT, ["limits"])
    assert disabled.run.status == "success"
    assert store.get_limit_security_dataset(CURRENT)["dataset_checksum"] == detail_checksum

    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    rebound_required = service.get(CURRENT)["chapter01"]["limits"]
    assert rebound_required["limitUpCount"] == 1
    assert rebound_required["promotionRatio"] is None
    assert rebound_required["promotionQuality"]["status"] == "insufficient"
    assert rebound_required["promotionQuality"]["reason"] == "unbound-limit-aggregate"


def test_zero_denominator_and_missing_or_incomplete_dependencies_are_insufficient(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    provider = DetailedLimitProvider(
        {PREVIOUS: limit_result(PREVIOUS, []), CURRENT: limit_result(CURRENT, ["600100"])}
    )
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    )
    coordinator.collect(CURRENT, ["limits"])
    limits = service.get(CURRENT)["chapter01"]["limits"]
    assert (limits["todayPromoted"], limits["yesterdayLimitUpEligible"], limits["promotionRatio"]) == (0, 0, None)
    assert limits["quality"]["status"] == "ok"
    assert limits["promotionQuality"]["status"] == "insufficient"
    assert limits["promotionQuality"]["reason"] == "zero-denominator"

    other_store, other_service = seed_store(tmp_path / "other")
    malformed = limit_result(CURRENT, [], extra_rows=[{"c": "bad"}])
    other_provider = DetailedLimitProvider({PREVIOUS: limit_result(PREVIOUS, ["600000"]), CURRENT: malformed})
    result = CollectionCoordinator(
        other_provider,
        other_store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=other_service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    ).collect(CURRENT, ["limits"])
    incomplete = other_service.get(CURRENT)["chapter01"]["limits"]
    assert result.run.status == "partial"
    assert incomplete["promotionRatio"] is None
    assert incomplete["promotionQuality"]["status"] == "insufficient"
    assert incomplete["promotionQuality"]["reason"] == "incomplete-adjacent-session-sample"
    manifest = other_store.get_limit_security_dataset(CURRENT)
    assert manifest is not None and manifest["complete"] is False
    assert any(fact.invalid_reason == "malformed-identity" for fact in other_store.get_limit_security_facts(CURRENT))

    other_provider.results[CURRENT] = limit_result(CURRENT, ["600000"])
    recovered = CollectionCoordinator(
        other_provider,
        other_store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=other_service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    ).collect(CURRENT, ["limits"])
    recovered_limits = other_service.get(CURRENT)["chapter01"]["limits"]
    assert recovered.run.status == "success"
    assert other_store.get_limit_security_dataset(CURRENT)["complete"] is True
    assert all(fact.invalid_reason != "malformed-identity" for fact in other_store.get_limit_security_facts(CURRENT))
    assert recovered_limits["promotionRatio"] == 1.0


def test_malformed_limit_rows_persist_partial_bundle_and_api_is_insufficient(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    malformed = malformed_limit_result("nonMappingPartial")
    provider = DetailedLimitProvider({PREVIOUS: limit_result(PREVIOUS, ["600000"]), CURRENT: malformed})
    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    ).collect(CURRENT, ["limits"])

    assert result.run.status == "partial"
    assert result.tasks[0].status == "partial"
    manifest = store.get_limit_security_dataset(CURRENT)
    snapshot = store.get("limits", CURRENT)
    facts = store.get_limit_security_facts(CURRENT)
    assert manifest is not None and manifest["complete"] is False
    assert manifest["dataset_checksum"] == malformed.normalization.dataset_checksum
    assert snapshot is not None
    assert snapshot.payload["quality"]["_detailDatasetChecksum"] == manifest["dataset_checksum"]
    assert len(facts) == 1
    assert facts[0].invalid_reason == "malformed-row"
    assert facts[0].row_checksum == malformed.normalization.rows[0].row_checksum

    monkeypatch.setattr(api, "service", service)
    response = TestClient(api.app).get(
        "/api/market-environment/chapter-01",
        params={"as_of": CURRENT.isoformat(), "section": "limits"},
    )
    assert response.status_code == 200
    limits = response.json()["chapter01"]["limits"]
    assert (
        limits["limitUpCount"],
        limits["failedLimitUpCount"],
        limits["limitDownCount"],
        limits["failedLimitUpRatio"],
    ) == (None, 0, 0, None)
    assert limits["quality"]["status"] == "partial"
    assert limits["quality"]["observations"] == 0
    assert "malformed-row" in limits["quality"]["warning"]
    assert (
        limits["todayPromoted"],
        limits["yesterdayLimitUpEligible"],
        limits["promotionRatio"],
    ) == (None, None, None)
    assert limits["promotionQuality"]["status"] == "insufficient"
    assert limits["promotionQuality"]["reason"] == "incomplete-adjacent-session-sample"
    assert {quality["status"] for quality in limits["fieldQuality"].values()} == {"insufficient"}


def test_malformed_refresh_retains_same_date_complete_bundle_and_degrades_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    previous_codes = ["600000", "600001"]
    current_codes = ["600000"]
    good_provider = DetailedLimitProvider(
        {PREVIOUS: limit_result(PREVIOUS, previous_codes), CURRENT: limit_result(CURRENT, current_codes)}
    )
    good_coordinator = CollectionCoordinator(
        good_provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    )
    assert good_coordinator.collect(CURRENT, ["limits"]).run.status == "success"
    original_snapshot = store.get("limits", CURRENT)
    original_manifest = store.get_limit_security_dataset(CURRENT)
    original_fact_checksums = tuple(fact.row_checksum for fact in store.get_limit_security_facts(CURRENT))
    assert original_snapshot is not None and original_manifest is not None

    malformed_provider = DetailedLimitProvider({CURRENT: malformed_limit_result("nonMappingAllFail")})
    failed = CollectionCoordinator(
        malformed_provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    ).collect(CURRENT, ["limits"])

    retained_snapshot = store.get("limits", CURRENT)
    retained_manifest = store.get_limit_security_dataset(CURRENT)
    retained_fact_checksums = tuple(fact.row_checksum for fact in store.get_limit_security_facts(CURRENT))
    assert failed.tasks[0].status == "failed-retained"
    assert retained_snapshot is not None and retained_manifest is not None
    assert retained_snapshot.checksum == original_snapshot.checksum
    assert retained_manifest["dataset_checksum"] == original_manifest["dataset_checksum"]
    assert retained_fact_checksums == original_fact_checksums
    assert "malformed-row" in (retained_snapshot.refresh_warning or "")

    monkeypatch.setattr(api, "service", service)
    response = TestClient(api.app).get(
        "/api/market-environment/chapter-01",
        params={"as_of": CURRENT.isoformat(), "section": "limits"},
    )
    assert response.status_code == 200
    limits = response.json()["chapter01"]["limits"]
    assert (
        limits["limitUpCount"],
        limits["limitDownCount"],
        limits["failedLimitUpCount"],
        limits["failedLimitUpRatio"],
        limits["maxStreak"],
    ) == (1, 1, 1, 0.5, 1)
    assert limits["quality"]["status"] == "degraded"
    assert "malformed-row" in limits["quality"]["refreshWarning"]
    assert limits["promotionRatio"] == 0.5
    assert limits["promotionQuality"]["status"] == "degraded"
    assert malformed_provider.calls == [CURRENT]


def test_st_regime_identity_conflict_invalidates_v1_without_changing_legacy_fields(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    conflict = {
        **limit_row("600003"),
        "is_st": False,
        "limit_regime": "st",
        "close_price": 10.5,
    }
    previous = limit_result(PREVIOUS, ["600000"], extra_rows=[conflict])
    repeated = limit_result(PREVIOUS, ["600000"], extra_rows=[conflict])
    current = limit_result(CURRENT, ["600000", "600003"])
    provider = DetailedLimitProvider({PREVIOUS: previous, CURRENT: current})
    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    ).collect(CURRENT, ["limits"])

    manifest = store.get_limit_security_dataset(PREVIOUS)
    facts = {fact.code: fact for fact in store.get_limit_security_facts(PREVIOUS)}
    previous_snapshot = store.get("limits", PREVIOUS)
    limits = service.get(CURRENT)["chapter01"]["limits"]

    assert result.run.status == "partial"
    assert manifest is not None
    assert manifest["complete"] is False
    assert manifest["dataset_checksum"] == previous.normalization.dataset_checksum
    assert previous.normalization.dataset_checksum == repeated.normalization.dataset_checksum
    assert (facts["600003"].is_st, facts["600003"].limit_regime) == (False, "st")
    assert facts["600003"].eligible is False
    assert facts["600003"].invalid_reason == "st-regime-identity-mismatch"
    assert (limits["todayPromoted"], limits["yesterdayLimitUpEligible"], limits["promotionRatio"]) == (
        None,
        None,
        None,
    )
    assert limits["quality"]["status"] == "ok"
    assert limits["promotionQuality"]["status"] == "insufficient"
    assert limits["promotionQuality"]["reason"] == "incomplete-adjacent-session-sample"
    assert {quality["status"] for quality in limits["fieldQuality"].values()} == {"insufficient"}
    assert previous_snapshot is not None
    assert previous_snapshot.payload["limitUpCount"] == 2
    assert previous_snapshot.payload["limitDownCount"] == 1
    assert previous_snapshot.payload["failedLimitUpCount"] == 1
    assert previous_snapshot.payload["failedLimitUpRatio"] == round(1 / 3, 4)
    assert limits["limitUpCount"] == 2
    assert limits["limitDownCount"] == 1
    assert limits["failedLimitUpCount"] == 1
    assert limits["failedLimitUpRatio"] == round(1 / 3, 4)

    provider.results[PREVIOUS] = limit_result(PREVIOUS, ["600000", "600003"])
    recovered = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    ).collect(CURRENT, ["limits"])
    recovered_manifest = store.get_limit_security_dataset(PREVIOUS)
    recovered_limits = service.get(CURRENT)["chapter01"]["limits"]

    assert recovered.run.status == "success"
    assert recovered_manifest is not None and recovered_manifest["complete"] is True
    assert recovered_manifest["dataset_checksum"] != manifest["dataset_checksum"]
    assert (
        recovered_limits["todayPromoted"],
        recovered_limits["yesterdayLimitUpEligible"],
        recovered_limits["promotionRatio"],
    ) == (2, 2, 1.0)
    assert recovered_limits["promotionQuality"]["status"] == "ok"
    assert {quality["status"] for quality in recovered_limits["fieldQuality"].values()} == {"ok"}
    assert recovered_limits["limitUpCount"] == 2
    assert recovered_limits["limitDownCount"] == 1
    assert recovered_limits["failedLimitUpCount"] == 1
    assert recovered_limits["failedLimitUpRatio"] == round(1 / 3, 4)


def test_failed_refresh_retains_same_date_bundle_and_marks_promotion_degraded(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    previous_codes = [f"600{index:03d}" for index in range(3)]
    results = {PREVIOUS: limit_result(PREVIOUS, previous_codes), CURRENT: limit_result(CURRENT, previous_codes[:2])}
    provider = DetailedLimitProvider(results)
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    )
    coordinator.collect(CURRENT, ["limits"])
    checksum = store.get_limit_security_dataset(CURRENT)["dataset_checksum"]

    provider.fail_on.add(CURRENT)
    failed = coordinator.collect(CURRENT, ["limits"])
    limits = service.get(CURRENT)["chapter01"]["limits"]

    assert failed.tasks[0].status == "failed-retained"
    assert store.get_limit_security_dataset(CURRENT)["dataset_checksum"] == checksum
    assert limits["promotionRatio"] == round(2 / 3, 4)
    assert limits["promotionQuality"]["status"] == "degraded"
    assert "fixture limit detail failure" in limits["quality"]["refreshWarning"]

    def fail_rebuild(_as_of, **_kwargs):
        raise RuntimeError("fixture retained rebuild failure")

    coordinator.rebuild_aggregate = fail_rebuild
    retained = coordinator.collect(CURRENT, ["limits"])
    assert retained.run.status == "failed"
    assert retained.tasks[0].status == "failed-retained"
    assert "fixture limit detail failure" in retained.tasks[0].warning
    assert "aggregate rebuild failed: fixture retained rebuild failure" in retained.tasks[0].warning


def test_missing_previous_detail_keeps_current_bundle_but_promotion_is_insufficient(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    provider = DetailedLimitProvider(
        {CURRENT: limit_result(CURRENT, ["600000"])},
        fail_on={PREVIOUS},
    )
    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    ).collect(CURRENT, ["limits"])

    assert result.run.status == "partial"
    assert provider.calls == [PREVIOUS, CURRENT]
    assert store.get_limit_security_dataset(PREVIOUS) is None
    assert store.get_limit_security_dataset(CURRENT) is not None
    limits = service.get(CURRENT)["chapter01"]["limits"]
    assert limits["todayPromoted"] is None
    assert limits["yesterdayLimitUpEligible"] is None
    assert limits["promotionRatio"] is None
    assert limits["promotionQuality"]["status"] == "insufficient"
    assert limits["promotionQuality"]["reason"] == "missing-limit-security-dataset"


def test_current_provider_date_mismatch_does_not_persist_requested_date(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    previous_result = limit_result(PREVIOUS, ["600000"])
    current_result = limit_result(CURRENT, ["600000"])
    mismatched = LimitProviderDatasetResult(
        current_result.payload,
        replace(current_result.normalization, actual_as_of=PREVIOUS),
    )
    provider = DetailedLimitProvider({PREVIOUS: previous_result, CURRENT: mismatched})
    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    ).collect(CURRENT, ["limits"])

    assert result.tasks[0].status == "failed-missing"
    assert "limits provider date mismatch" in result.tasks[0].warning
    assert store.get("limits", CURRENT) is None
    assert store.get_limit_security_dataset(CURRENT) is None
    assert store.get_limit_security_facts(CURRENT) == ()
    limits = service.get(CURRENT)["chapter01"]["limits"]
    assert limits["limitUpCount"] is None
    assert limits["promotionRatio"] is None
    assert limits["promotionQuality"]["status"] == "insufficient"


def test_atomic_bundle_rolls_back_snapshot_when_fact_write_fails(tmp_path, monkeypatch) -> None:
    store = SnapshotStore(tmp_path / "atomic.sqlite3")
    result = limit_result(CURRENT, ["600000"])
    snapshot = SnapshotRecord(
        "limits",
        CURRENT,
        result.payload,
        "fixture-adjacent-sessions",
        "ok",
        3,
        (),
        MARKET_NOW,
        True,
    )

    stored_snapshot, stored_checksum = store.put_limit_collection(snapshot, result.normalization)
    stored_facts = store.get_limit_security_facts(CURRENT)
    with sqlite3.connect(store.path) as connection:
        connection.executescript(
            """
            CREATE TRIGGER fail_limit_fact_write
            BEFORE INSERT ON limit_security_facts
            WHEN NEW.code = '601001'
            BEGIN
                SELECT RAISE(ABORT, 'fixture fact write failure');
            END;
            """
        )

    retry_snapshot = replace(snapshot, fetched_at=MARKET_NOW + timedelta(minutes=1))
    try:
        store.put_limit_collection(retry_snapshot, result.normalization)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("fault injection should abort the atomic bundle")

    assert store.get("limits", CURRENT) == stored_snapshot
    assert store.get_limit_security_dataset(CURRENT)["dataset_checksum"] == stored_checksum
    assert store.get_limit_security_facts(CURRENT) == stored_facts


def test_previous_retained_snapshot_degrades_promotion_quality(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    codes = ["600000", "600001"]
    provider = DetailedLimitProvider(
        {PREVIOUS: limit_result(PREVIOUS, codes), CURRENT: limit_result(CURRENT, codes[:1])}
    )
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    )
    coordinator.collect(CURRENT, ["limits"])
    store.set_refresh_warning("limits", PREVIOUS, "previous session refresh failed")

    limits = service.get(CURRENT)["chapter01"]["limits"]
    assert limits["promotionRatio"] == 0.5
    assert limits["quality"]["status"] == "degraded"
    assert limits["promotionQuality"]["status"] == "degraded"
    assert any("previous session refresh failed" in warning for warning in limits["promotionQuality"]["warnings"])
    assert {quality["status"] for quality in limits["fieldQuality"].values()} == {"degraded"}


def test_rebuild_failure_cannot_mix_old_materialized_limits_with_new_bundle(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    old_payload = service.rebuild_materialized_aggregate(CURRENT)
    assert old_payload["chapter01"]["limits"]["limitUpCount"] is None
    provider = DetailedLimitProvider(
        {
            PREVIOUS: limit_result(PREVIOUS, ["600000", "600001"]),
            CURRENT: limit_result(CURRENT, ["600000"]),
        }
    )

    def fail_rebuild(_as_of, **_kwargs):
        raise RuntimeError("fixture aggregate rebuild failure")

    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=fail_rebuild,
        limits_v1_enabled=True,
    ).collect(CURRENT, ["limits"])
    assert result.tasks[0].status == "partial"
    assert "aggregate rebuild failed" in result.tasks[0].warning

    limits = service.get(CURRENT)["chapter01"]["limits"]
    assert limits["limitUpCount"] == 1
    assert limits["yesterdayLimitUpEligible"] == 2
    assert limits["todayPromoted"] == 1
    assert limits["promotionRatio"] == 0.5


def test_enabled_concurrent_cold_start_runs_only_one_paired_provider_chain(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    codes = ["600000"]
    provider = DetailedLimitProvider({PREVIOUS: limit_result(PREVIOUS, codes), CURRENT: limit_result(CURRENT, codes)})
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    )

    first = coordinator.start_run(CURRENT, ["limits"])
    second = coordinator.start_run(CURRENT, ["limits"])
    coordinator.execute_run(second.run.run_id)
    assert provider.calls == []
    coordinator.execute_run(first.run.run_id)

    assert provider.calls == [PREVIOUS, CURRENT]
    assert second.tasks[0].status == "busy"


def test_disabled_collection_does_not_write_or_replace_normalized_details(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "0")
    store, service = seed_store(tmp_path)
    provider = DetailedLimitProvider({CURRENT: limit_result(CURRENT, ["600000"])})
    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=False,
    ).collect(CURRENT, ["limits"])

    assert result.run.status == "success"
    assert provider.calls == [CURRENT]
    assert store.get("limits", CURRENT) is not None
    assert store.get_limit_security_dataset(CURRENT) is None
    assert store.get_limit_security_facts(CURRENT) == ()


def test_collection_status_limits_detail_is_provider_free_and_contract_complete(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    provider = DetailedLimitProvider(
        {PREVIOUS: limit_result(PREVIOUS, ["600000", "600001"]), CURRENT: limit_result(CURRENT, ["600000"])}
    )
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: MARKET_NOW,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    )
    coordinator.collect(CURRENT, ["limits"])
    provider.calls.clear()
    monkeypatch.setattr(api, "collection_coordinator", coordinator)

    response = TestClient(api.app).get(
        "/api/market-environment/data-collection",
        params={"as_of": CURRENT.isoformat()},
    )

    assert response.status_code == 200
    limits = next(item for item in response.json()["datasets"] if item["dataset"] == "limits")
    detail = limits["detail"]
    assert detail["sampleAsOf"] == CURRENT.isoformat()
    assert detail["previousAsOf"] == PREVIOUS.isoformat()
    assert detail["excludedCount"] is not None
    assert detail["promotionDependency"]
    assert limits["latestAttempt"]["promotionDependency"] == detail["promotionDependency"]
    assert provider.calls == []
