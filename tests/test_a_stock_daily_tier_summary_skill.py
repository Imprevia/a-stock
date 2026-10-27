"""Offline behavioral coverage for the daily tier summary Skill."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents/skills/a-stock-daily-tier-summary/scripts/analyze_tier_summary.py"
FIXTURES = ROOT / "tests/fixtures/a_stock_daily_tier_summary"
SPEC = importlib.util.spec_from_file_location("a_stock_daily_tier_summary", SCRIPT)
assert SPEC and SPEC.loader
summary = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = summary
SPEC.loader.exec_module(summary)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _empty_pools() -> dict:
    return {
        "limit_up": {"rows": [], "quality": {"status": "ok"}},
        "failed_limit_up": {"rows": [], "quality": {"status": "ok"}},
        "limit_down": {"rows": [], "quality": {"status": "ok"}},
    }


def _session(
    as_of: str,
    *,
    previous: str | None = None,
    pools: dict | None = None,
    quality="ok",
    revision: str | None = None,
):
    return summary.session_from_dict(
        {
            "requestedDate": as_of,
            "actualDate": as_of,
            "previousSession": previous,
            "source": "synthetic-fixture",
            "revision": revision,
            "quality": {"status": quality},
            "pools": pools or _empty_pools(),
        }
    )


def test_normalization_deduplicates_exchange_identity_and_rejects_conflicts() -> None:
    edge = _fixture("edge-cases.json")
    pool = summary.normalize_pool("limit_up", edge["duplicateRows"], source_kind="local")

    assert len(pool.members) == 1
    assert pool.members[0].identity.security_id == "SH:600101"
    assert pool.quality.status == "degraded"
    assert "counted once" in pool.quality.warnings[0]

    with pytest.raises(summary.ConflictingRowsError, match="SH:600102"):
        summary.normalize_pool("limit_up", edge["conflictingRows"], source_kind="local")


def test_eastmoney_lbc_wins_and_pattern_days_never_set_the_tier() -> None:
    rows = _fixture("edge-cases.json")["eastmoneyPrecedence"]
    pool = summary.normalize_pool("limit_up", rows, source_kind="eastmoney")

    member = pool.members[0]
    assert member.streak_days == 2
    assert member.pattern_days == 8
    assert summary.tier_for_streak(member.streak_days) == "middle"

    local_pool = summary.normalize_pool("limit_up", rows, source_kind="local")
    assert local_pool.members[0].streak_days is None
    assert summary._tier_members(local_pool) == {"high": set(), "middle": set(), "low": set()}


def test_missing_streak_preserves_pool_member_but_degrades_tier_coverage() -> None:
    rows = _fixture("edge-cases.json")["partialTierRows"]
    pool = summary.normalize_pool("limit_up", rows, source_kind="local")

    assert len(pool.members) == 1
    assert pool.quality.status == "degraded"
    assert all(not members for members in summary._tier_members(pool).values())


def test_explicit_date_mismatch_fails_closed_and_closed_date_resolves() -> None:
    edge = _fixture("edge-cases.json")
    mismatch = {
        **edge["dateMismatch"],
        "source": "synthetic-fixture",
        "pools": _empty_pools(),
    }
    with pytest.raises(summary.DateEvidenceError, match="contradiction"):
        summary.session_from_dict(mismatch)

    request = edge["closedDateRequest"]
    resolved = summary.resolve_relative_session(
        request["relative"],
        now=datetime.fromisoformat(request["now"]),
        trading_sessions=[date.fromisoformat(item) for item in request["tradingSessions"]],
    )
    assert resolved.literal_date == date(2026, 10, 25)
    assert resolved.session_date == date(2026, 10, 23)
    assert resolved.literal_date_closed is True
    assert "休市" in resolved.note


def test_zero_failed_sample_denominator_is_nullable_not_zero_percent() -> None:
    pools = _fixture("edge-cases.json")["zeroDenominatorPools"]
    previous = _session("2026-10-22", pools=pools)
    current = _session("2026-10-23", previous="2026-10-22", pools=pools)

    result = summary.analyze_sessions(previous, current)

    assert result["failedSampleRepair"] == {
        "numerator": 0,
        "denominator": 0,
        "ratio": None,
        "status": "insufficient",
        "warning": "previous failed-limit-up sample is empty",
    }
    rendered = summary.render_summary(result)
    assert "0%" not in rendered
    assert "高位样本0只，数据不足" in rendered


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("confirmed", "confirmed"),
        ("invalidated", "invalidated"),
        ("inconclusive", "inconclusive"),
        ("conflicting", "conflicting"),
    ],
)
def test_previous_plan_states_preserve_original_conditions(name: str, expected: str) -> None:
    plan = _fixture("edge-cases.json")["planStates"][name]
    result = summary.evaluate_previous_plan(plan, {"x": 2, "y": 0})

    assert result["status"] == expected
    conditions = [*result["confirmation"], *result["invalidation"]]
    assert all(condition["text"] for condition in conditions)
    assert all("observed" in condition and "expected" in condition for condition in conditions)


def test_previous_plan_unavailable_is_explicit() -> None:
    plan = _fixture("edge-cases.json")["planStates"]["unavailable"]
    result = summary.evaluate_previous_plan(plan, {})

    assert result["status"] == "unavailable"
    assert "未找到" in result["summary"]


def test_any_invalidation_condition_triggers_without_rewriting_thresholds() -> None:
    plan = {
        "confirmation": [
            {"metric": "continued", "operator": ">=", "value": 2, "text": "至少2只继续涨停"}
        ],
        "invalidation": [
            {"metric": "failed", "operator": ">=", "value": 2, "text": "至少2只炸板"},
            {"metric": "down", "operator": ">=", "value": 1, "text": "至少1只跌停"},
        ],
    }

    result = summary.evaluate_previous_plan(
        plan, {"continued": 1, "failed": 0, "down": 1}
    )

    assert result["status"] == "invalidated"
    assert result["invalidation"][0]["passed"] is False
    assert result["invalidation"][1]["passed"] is True


class LocalV2Transport:
    def __init__(self, *, revision_mismatch: bool = False):
        self.calls: list[tuple[str, float, dict]] = []
        self.revision_mismatch = revision_mismatch

    def get_json(self, url: str, *, timeout: float, headers=None):
        self.calls.append((url, timeout, dict(headers or {})))
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("/limits"):
            return {
                "asOf": "2026-10-23",
                "snapshotRevision": "rev-23",
                "quality": {"status": "ok"},
                "data": {"previousSession": "2026-10-22"},
            }
        pool_type = parsed.path.rsplit("/", 1)[-1]
        cursor = query.get("cursor", [None])[0]
        if pool_type == "limit_up" and cursor is None:
            items = [{"exchange": "SH", "code": "600001", "streak_days": 2}]
            pagination = {"hasMore": True, "nextCursor": "next-1"}
        elif pool_type == "limit_up":
            items = [{"exchange": "SZ", "code": "000001", "streak_days": 1}]
            pagination = {"hasMore": False, "nextCursor": None}
        else:
            items = []
            pagination = {"hasMore": False, "nextCursor": None}
        return {
            "asOf": "2026-10-23",
            "snapshotRevision": "changed" if self.revision_mismatch else "rev-23",
            "quality": {"status": "ok"},
            "data": {"items": items},
            "pagination": pagination,
        }


class CurrentReviewTransport:
    def __init__(
        self,
        *,
        revision_mismatch: bool = False,
        date_mismatch: bool = False,
        missing_index: bool = False,
        conflicting_pattern: bool = False,
    ):
        self.calls: list[tuple[str, float, dict]] = []
        self.revision_mismatch = revision_mismatch
        self.date_mismatch = date_mismatch
        environment = _fixture("e2e.json")["marketEnvironment"]
        self.summary = json.loads(json.dumps(environment["summary"]))
        self.indices = json.loads(json.dumps(environment["indices"]))
        self.breadth = json.loads(json.dumps(environment["breadth"]))
        if missing_index:
            self.indices.pop()
        if conflicting_pattern:
            self.summary["marketEvidence"]["directionPattern"] = "broad_weakness"

    def get_json(self, url: str, *, timeout: float, headers=None):
        self.calls.append((url, timeout, dict(headers or {})))
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        resource = parsed.path.rsplit("/", 1)[-1]
        as_of = "2026-10-22" if self.date_mismatch and resource == "breadth" else "2026-10-23"
        revision = "changed" if self.revision_mismatch and resource == "breadth" else "rev-23"
        envelope = {
            "asOf": as_of,
            "snapshotRevision": revision,
            "quality": {"status": "ok"},
        }
        if resource == "overview":
            return {**envelope, "data": {"summary": self.summary}}
        if resource == "indices":
            return {**envelope, "data": {"items": self.indices}}
        if resource == "breadth":
            return {**envelope, "data": self.breadth}
        if resource == "limits":
            return {**envelope, "data": {"previousSession": "2026-10-22"}}
        pool_type = resource
        cursor = query.get("cursor", [None])[0]
        if pool_type == "limit_up" and cursor is None:
            items = [{"exchange": "SH", "code": "600001", "streak_days": 2}]
            pagination = {"hasMore": True, "nextCursor": "next-1"}
        elif pool_type == "limit_up":
            items = [{"exchange": "SZ", "code": "000001", "streak_days": 1}]
            pagination = {"hasMore": False, "nextCursor": None}
        else:
            items = []
            pagination = {"hasMore": False, "nextCursor": None}
        return {**envelope, "data": {"items": items}, "pagination": pagination}


def test_local_v2_reads_all_pages_with_one_revision_and_only_read_paths() -> None:
    transport = LocalV2Transport()
    session = summary.fetch_local_session(
        "http://local.test",
        date(2026, 10, 23),
        previous_session=date(2026, 10, 22),
        transport=transport,
    )

    assert len(session.pools["limit_up"].members) == 2
    assert len(transport.calls) == 5
    for url, timeout, headers in transport.calls:
        parsed = urlparse(url)
        assert parsed.path.startswith("/api/v2/market-environment/2026-10-23/limits")
        assert not any(word in parsed.path for word in ("collect", "refresh", "backfill", "operation"))
        assert timeout == 5.0
        assert headers["Accept"] == "application/json"
    pool_queries = [parse_qs(urlparse(url).query) for url, _, _ in transport.calls[1:]]
    assert all(query["revision"] == ["rev-23"] for query in pool_queries)
    assert pool_queries[1]["cursor"] == ["next-1"]


def test_local_v2_revision_change_fails_closed() -> None:
    with pytest.raises(summary.ReadError, match="changed snapshotRevision"):
        summary.fetch_local_session(
            "http://local.test",
            date(2026, 10, 23),
            previous_session=date(2026, 10, 22),
            transport=LocalV2Transport(revision_mismatch=True),
        )


def test_current_v2_review_pins_overview_revision_across_all_resources() -> None:
    transport = CurrentReviewTransport()

    session, environment = summary.fetch_local_current_review(
        "http://local.test",
        date(2026, 10, 23),
        previous_session=date(2026, 10, 22),
        transport=transport,
    )

    assert session.date_evidence.revision == environment.revision == "rev-23"
    assert len(session.pools["limit_up"].members) == 2
    assert len(transport.calls) == 8
    first_path = urlparse(transport.calls[0][0]).path
    assert first_path.endswith("/overview")
    assert not parse_qs(urlparse(transport.calls[0][0]).query)
    for url, timeout, headers in transport.calls[1:]:
        parsed = urlparse(url)
        assert parsed.path.startswith("/api/v2/market-environment/2026-10-23/")
        assert not any(word in parsed.path for word in ("collect", "refresh", "backfill", "operation"))
        assert parse_qs(parsed.query)["revision"] == ["rev-23"]
        assert timeout == 5.0
        assert headers["Accept"] == "application/json"


@pytest.mark.parametrize(
    ("transport", "error", "message"),
    [
        (CurrentReviewTransport(revision_mismatch=True), summary.ReadError, "changed snapshotRevision"),
        (CurrentReviewTransport(date_mismatch=True), summary.DateEvidenceError, "date mismatch"),
        (CurrentReviewTransport(missing_index=True), summary.ReadError, "missing expected index"),
        (CurrentReviewTransport(conflicting_pattern=True), summary.ReadError, "conflicting canonical"),
    ],
)
def test_current_v2_review_fails_closed_on_mixed_or_conflicting_evidence(
    transport, error, message
) -> None:
    with pytest.raises(error, match=message):
        summary.fetch_local_current_review(
            "http://local.test",
            date(2026, 10, 23),
            previous_session=date(2026, 10, 22),
            transport=transport,
        )


class EastmoneyTransport:
    def __init__(self, qdate: str | None):
        self.qdate = qdate
        self.calls: list[tuple[str, float, dict]] = []

    def get_json(self, url: str, *, timeout: float, headers=None):
        self.calls.append((url, timeout, dict(headers or {})))
        data = {"pool": [], "tc": 0}
        if self.qdate is not None:
            data["qdate"] = self.qdate
        return {"data": data}


def test_eastmoney_request_date_only_is_degraded_and_timeout_is_bounded() -> None:
    transport = EastmoneyTransport(None)
    session = summary.fetch_eastmoney_session(
        date(2026, 10, 23), previous_session=date(2026, 10, 22), transport=transport
    )

    assert session.quality.status == "degraded"
    assert session.date_evidence.actual_date is None
    assert len(transport.calls) == 3
    assert all(call[1] == 8.0 for call in transport.calls)
    assert all("date=20261023" in call[0] for call in transport.calls)


def test_eastmoney_explicit_qdate_contradiction_is_insufficient() -> None:
    with pytest.raises(summary.DateEvidenceError, match="date contradiction"):
        summary.fetch_eastmoney_session(
            date(2026, 10, 23),
            previous_session=date(2026, 10, 22),
            transport=EastmoneyTransport("20261022"),
        )


def test_fixture_end_to_end_arithmetic_quality_and_full_card() -> None:
    result = summary.analyze_fixture(_fixture("e2e.json"))

    assert result["dates"] == {
        "previousSession": "2026-10-22",
        "currentSession": "2026-10-23",
    }
    assert result["tierOutcomes"]["high"]["sampleSize"] == 2
    assert result["tierOutcomes"]["high"]["continuedLimitUp"] == 1
    assert result["tierOutcomes"]["middle"]["limitDown"] == 1
    assert result["tierOutcomes"]["low"]["outsideObservedPools"] == 1
    assert result["failedSampleRepair"]["numerator"] == 1
    assert result["failedSampleRepair"]["denominator"] == 2
    assert result["failedSampleRepair"]["ratio"] == 0.5
    assert result["previousVerification"]["status"] == "invalidated"
    assert result["currentTiers"]["low"]["count"] > result["tierOutcomes"]["low"]["sampleSize"]
    assert result["structure"]["label"] in {"扩散", "抱团", "低位试错", "修复", "混合"}
    assert result["structure"]["status"] == "needs-backtest"
    assert result["nextSessionVerification"]["layer"] == "middle"
    environment = result["marketEnvironment"]
    assert environment["date"] == "2026-10-23"
    assert environment["revision"] == "fixture-current"
    assert environment["directionGroups"] == {
        "rising": ["上证指数"],
        "falling": ["深证成指", "创业板指", "沪深300", "中证500"],
        "flat": [],
        "insufficient": [],
    }
    assert environment["ma20Groups"]["below"] == list(summary.INDEX_NAMES)
    assert environment["breadthIndexRelation"]["state"] == "consistent"
    assert environment["conclusion"]["category"] == "弱势分化、保持观察"
    assert environment["confidence"] == "low"
    assert environment["nextSessionVerification"]["concept"] == "breadth"

    rendered = summary.render_summary(result)
    lines = rendered.splitlines()
    assert lines[0] == "上证指数上涨；深证成指、创业板指、沪深300、中证500下跌"
    assert lines[1] == "MA20下方：上证指数、深证成指、创业板指、沪深300、中证500"
    assert lines[2] == "上涨占比40.4%"
    assert lines[3] == "全A涨跌幅中位数-0.46%"
    assert lines[4] == "五指数5日成交额比值中位数1.03"
    assert lines[5] == "放量上涨/下跌为0/0"
    assert lines[6] == "今日宽度标签：同向走弱。"
    assert lines[7] == "核心证据：与指数一致。"
    assert lines[8].startswith("昨日验证结果：")
    assert lines[9].startswith("今日分层结论：")
    assert lines[10].startswith("风险主要位于")
    assert "涨停6→6只、跌停1→1只、炸板2→2只" in lines[10]
    assert lines[11].startswith("下一交易日只验证中位层：")
    assert lines[12] == "因此今天属于弱势分化、保持观察。"
    assert lines[13] == "置信度低。"
    assert lines[14] == (
        "下一交易日只验证：上涨占比是否继续 ≤45% 且全 A 中位涨幅 <0；"
        "若持续，则弱势得到进一步确认。"
    )
    assert "___" not in rendered


def test_quality_propagates_and_serialization_excludes_raw_payloads_or_credentials() -> None:
    payload = _fixture("e2e.json")
    payload["sessions"]["2026-10-23"]["quality"] = {
        "status": "degraded",
        "warnings": ["synthetic quality warning"],
    }
    result = summary.analyze_fixture(payload)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)

    assert result["quality"]["status"] == "degraded"
    assert "synthetic quality warning" in result["quality"]["warnings"]
    assert "rawResponse" not in encoded
    assert "runtimeSnapshot" not in encoded
    assert "credential" not in encoded.lower()
    assert "fixture-current" in encoded


def test_limits_only_fixture_keeps_tiers_and_marks_environment_insufficient() -> None:
    payload = _fixture("e2e.json")
    payload.pop("marketEnvironment")

    result = summary.analyze_fixture(payload)

    assert result["structure"]["status"] == "needs-backtest"
    assert result["marketEnvironment"]["conclusion"]["category"] == "数据不足"
    assert result["marketEnvironment"]["nextSessionVerification"]["concept"] == "data-recovery"
    assert "市场环境输入是否恢复" in summary.render_summary(result)


def test_named_groups_handle_flat_ma20_equality_and_missing_values() -> None:
    payload = _fixture("e2e.json")
    environment = payload["marketEnvironment"]
    environment["summary"]["marketEvidence"] = None
    environment["indices"][0]["changePct"] = 0
    environment["indices"][0]["close"] = environment["indices"][0]["movingAverages"]["ma20"]
    environment["indices"][1]["changePct"] = None
    environment["indices"][1]["movingAverages"]["ma20"] = None
    environment["breadth"]["indexConsistent"] = None

    result = summary.analyze_fixture(payload)["marketEnvironment"]

    assert result["directionGroups"]["flat"] == ["上证指数"]
    assert result["directionGroups"]["insufficient"] == ["深证成指"]
    assert result["ma20Groups"]["above"] == ["上证指数"]
    assert result["ma20Groups"]["insufficient"] == ["深证成指"]
    assert result["confidence"] == "insufficient"


def test_breadth_relation_derives_consistency_and_divergence_only_without_canonical() -> None:
    consistent = _fixture("e2e.json")
    consistent["marketEnvironment"]["breadth"]["indexConsistent"] = None
    consistent_result = summary.analyze_fixture(consistent)["marketEnvironment"]
    assert consistent_result["breadthIndexRelation"] == {"state": "consistent", "source": "derived"}

    divergent = _fixture("e2e.json")
    for row in divergent["marketEnvironment"]["indices"]:
        row["changePct"] = 0.2
    divergent["marketEnvironment"]["summary"]["marketEvidence"] = None
    divergent["marketEnvironment"]["breadth"]["indexConsistent"] = None
    divergent_result = summary.analyze_fixture(divergent)["marketEnvironment"]
    assert divergent_result["breadthIndexRelation"]["state"] == "divergent"
    assert divergent_result["conclusion"]["category"] == "指数与个股分化"


def test_insufficient_required_pool_does_not_emit_a_stronger_structure_label() -> None:
    payload = _fixture("e2e.json")
    payload["sessions"]["2026-10-23"]["pools"]["limit_down"]["quality"] = {
        "status": "insufficient",
        "warnings": ["synthetic missing pool evidence"],
    }

    result = summary.analyze_fixture(payload)

    assert result["quality"]["status"] == "insufficient"
    assert result["structure"]["label"] == "数据不足"
    assert result["structure"]["status"] == "insufficient"


class PoolRouterTransport:
    """Exercise the real HTTP mapper in memory, with small pages for consumers."""

    def __init__(self, client):
        self.client = client
        self.calls = []

    def get_json(self, url: str, *, timeout: float, headers=None):
        parsed = urlparse(url)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        if "/pools/" in parsed.path:
            params["limit"] = "2"
        self.calls.append((parsed.path, dict(params), timeout))
        response = self.client.get(parsed.path, params=params, headers=headers or {})
        assert response.status_code == 200, response.text
        return response.json()


def _assert_restored_http_tier_samples(adapter, evidence, *, missing_streak):
    from contextlib import closing
    from tests.test_market_environment_v2_postgres_pools import pool_http_client

    with closing(pool_http_client(adapter)) as client:
        transport = PoolRouterTransport(client)
        previous = summary.fetch_local_session(
            "http://synthetic.test", evidence.previous,
            previous_session=None, transport=transport,
        )
        current = summary.fetch_local_session(
            "http://synthetic.test", evidence.current,
            previous_session=evidence.previous, transport=transport,
        )
    result = summary.analyze_sessions(previous, current)
    for tier in ("high", "middle", "low"):
        outcome = result["tierOutcomes"][tier]
        assert outcome["sampleSize"] == 4
        categories = ("continuedLimitUp", "failedLimitUp", "limitDown", "outsideObservedPools")
        assert [outcome[key] for key in categories] == [1, 1, 1, 1]
        assert sum(outcome[key] for key in categories) == outcome["sampleSize"]
        assert outcome["continuedRatio"] == 0.25
    repair = result["failedSampleRepair"]
    assert (repair["numerator"], repair["denominator"], repair["ratio"]) == (1, 2, 0.5)
    assert all(not fact.eligible for facts in evidence.facts_by_date.values() for fact in facts)
    assert len(previous.pools["limit_up"].members) == 12 + int(missing_streak)
    assert sum(outcome["sampleSize"] for outcome in result["tierOutcomes"].values()) == 12
    assert result["quality"]["status"] == "degraded"
    if missing_streak:
        missing = [member for member in previous.pools["limit_up"].members if member.identity.code == "609999"]
        assert len(missing) == 1 and missing[0].streak_days is None
        assert any("lack a valid consecutive-board field" in warning for warning in previous.pools["limit_up"].quality.warnings)
        aggregate_count = evidence.aggregates[evidence.previous]["chapter01"]["limits"]["limitUpCount"]
        assert aggregate_count == 13
    assert any(params.get("cursor") for _, params, _ in transport.calls)
    assert all(timeout == 5.0 for _, _, timeout in transport.calls)
    assert all("/limits" in path and "collection" not in path for path, _, _ in transport.calls)
    assert all("revision" in params for path, params, _ in transport.calls if "/pools/" in path)


@pytest.fixture
def restored_pool_provider_guard(monkeypatch):
    from tests.test_market_environment_v2_postgres_pools import forbid_pool_provider_access

    yield from forbid_pool_provider_access.__wrapped__(monkeypatch)


@pytest.mark.parametrize("missing_streak", (False, True))
def test_restored_pool_http_evidence_reaches_daily_tier_arithmetic(
    restored_pool_provider_guard, missing_streak,
):
    from src.market_environment.infrastructure.v2_market_data_compat import CompatibilityV2MarketDataReadAdapter
    from tests.test_market_environment_v2_postgres_pools import build_pool_evidence

    evidence = build_pool_evidence(missing_streak=missing_streak)
    _assert_restored_http_tier_samples(
        CompatibilityV2MarketDataReadAdapter(evidence.aggregates), evidence,
        missing_streak=missing_streak,
    )


@pytest.fixture
def restored_pool_postgres_connection():
    from tests.test_market_environment_v2_postgres_pools import postgres_pool_connection

    yield from postgres_pool_connection.__wrapped__()


@pytest.mark.integration
@pytest.mark.parametrize("missing_streak", (False, True))
def test_restored_postgres_http_evidence_reaches_daily_tier_arithmetic(
    restored_pool_postgres_connection, restored_pool_provider_guard, monkeypatch, missing_streak,
):
    from tests.test_market_environment_v2_postgres_pools import (
        build_pool_evidence, pool_reads_only, seed_postgres_pool_evidence,
    )

    evidence = build_pool_evidence(missing_streak=missing_streak)
    adapter = seed_postgres_pool_evidence(restored_pool_postgres_connection, evidence)
    with pool_reads_only(restored_pool_postgres_connection, monkeypatch):
        _assert_restored_http_tier_samples(adapter, evidence, missing_streak=missing_streak)
