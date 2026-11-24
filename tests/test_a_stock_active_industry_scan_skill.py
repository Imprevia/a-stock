"""Offline coverage for the active-industry-scan Skill.

Every case runs without network access and without real credentials.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/a-stock-active-industry-scan"
SCRIPTS = SKILL / "scripts"
FIXTURES = ROOT / "tests/fixtures/active_industry_scan"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import contract  # noqa: E402
import direction  # noqa: E402
import percentile  # noqa: E402
import fuyao_client  # noqa: E402
import industry_map  # noqa: E402
import sina_client  # noqa: E402
import history  # noqa: E402
import report  # noqa: E402
import scan_pipeline  # noqa: E402
import quadrant  # noqa: E402
import session  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")


# --------------------------------------------------------------------------
# quadrant.py
# --------------------------------------------------------------------------


def test_quadrant_classifies_active_when_both_rankings_hit():
    thresholds = quadrant.QuadrantThresholds(amount=2, turnover=2)
    verdict = quadrant.classify(
        quadrant.QuadrantInput(amount_top_count=14, turnover_top_count=3),
        thresholds,
    )
    assert verdict == quadrant.QUADRANT_ACTIVE


def test_quadrant_classifies_weight_when_only_amount_hits():
    thresholds = quadrant.QuadrantThresholds(amount=2, turnover=2)
    verdict = quadrant.classify(
        quadrant.QuadrantInput(amount_top_count=5, turnover_top_count=0),
        thresholds,
    )
    assert verdict == quadrant.QUADRANT_WEIGHT


def test_quadrant_classifies_retail_when_only_turnover_hits():
    thresholds = quadrant.QuadrantThresholds(amount=2, turnover=2)
    verdict = quadrant.classify(
        quadrant.QuadrantInput(amount_top_count=0, turnover_top_count=4),
        thresholds,
    )
    assert verdict == quadrant.QUADRANT_RETAIL


def test_quadrant_classifies_cold_when_neither_hits():
    thresholds = quadrant.QuadrantThresholds(amount=2, turnover=2)
    verdict = quadrant.classify(
        quadrant.QuadrantInput(amount_top_count=1, turnover_top_count=1),
        thresholds,
    )
    assert verdict == quadrant.QUADRANT_COLD


def test_quadrant_covers_union_of_both_rankings():
    summary = quadrant.summarize(
        {"881121.TI": 4},
        {"881181.TI": 3},
        quadrant.QuadrantThresholds(),
    )
    assert set(summary) == {"881121.TI", "881181.TI"}
    assert summary["881121.TI"] == quadrant.QUADRANT_WEIGHT
    assert summary["881181.TI"] == quadrant.QUADRANT_RETAIL


def test_quadrant_ignores_member_count_and_history():
    """Classification must not change when membership data is absent."""

    thresholds = quadrant.QuadrantThresholds(amount=2, turnover=2)
    evidence = quadrant.QuadrantInput(amount_top_count=3, turnover_top_count=3)
    assert quadrant.classify(evidence, thresholds) == quadrant.QUADRANT_ACTIVE
    # The input type has no membership field at all, so history cannot leak in.


def test_hit_rate_returns_none_for_unusable_denominator():
    assert quadrant.hit_rate(3, 0) is None
    assert quadrant.hit_rate(3, None) is None
    assert quadrant.hit_rate(3, 30) == pytest.approx(0.1)


def test_rank_key_prefers_presence_on_both_rankings():
    thresholds = quadrant.QuadrantThresholds(amount=2, turnover=2)
    both = quadrant.rank_key(2, 2, thresholds)
    amount_only = quadrant.rank_key(5, 0, thresholds)
    turnover_only = quadrant.rank_key(0, 6, thresholds)
    # Both-rankings industry sorts ahead of a one-sided industry with more raw
    # hits, because presence on both is stronger evidence than volume on one.
    assert sorted([amount_only, both, turnover_only])[0] == both


def test_rank_key_orders_one_sided_industries_by_total_hits():
    thresholds = quadrant.QuadrantThresholds()
    heavy = quadrant.rank_key(9, 0, thresholds)
    light = quadrant.rank_key(3, 0, thresholds)
    assert sorted([heavy, light])[0] == heavy


def test_quadrant_thresholds_reject_zero():
    with pytest.raises(ValueError):
        quadrant.QuadrantThresholds(amount=0)


# --------------------------------------------------------------------------
# direction.py
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "volume", "expected"),
    [
        (-17.26, 1e6, direction.DIRECTION_DOWN),
        (-0.004, 1e6, direction.DIRECTION_FLAT),
        (0.0, 1e6, direction.DIRECTION_FLAT),
        (0.004, 1e6, direction.DIRECTION_FLAT),
        (10.0, 1e6, direction.DIRECTION_UP),
        (-0.006, 1e6, direction.DIRECTION_DOWN),
        (0.006, 1e6, direction.DIRECTION_UP),
        (None, 1e6, direction.DIRECTION_SUSPENDED),
        (0.0, 0, direction.DIRECTION_SUSPENDED),
    ],
)
def test_classify_direction_covers_every_branch(change, volume, expected):
    assert direction.classify_direction(change, volume=volume) == expected


def test_classify_direction_absent_change_is_suspended_not_flat():
    """A missing previous close is an absent measurement, never "unchanged"."""

    assert direction.classify_direction(None) == direction.DIRECTION_SUSPENDED
    assert direction.classify_direction(None) != direction.DIRECTION_FLAT


def test_classify_direction_volume_zero_overrides_stale_zero_change():
    """A suspended stock can carry a stale 0.0 change; volume disambiguates."""

    assert direction.classify_direction(0.0, volume=0) == direction.DIRECTION_SUSPENDED


def test_market_median_ignores_none_and_orders_by_value():
    assert direction.market_median([3.0, None, -1.0, 1.0]) == 1.0


def test_market_median_is_none_when_nothing_usable():
    assert direction.market_median([]) is None
    assert direction.market_median([None, None]) is None


def test_market_median_of_single_sample_is_that_sample():
    assert direction.market_median([-5.08]) == -5.08


def test_relative_to_market_subtracts_and_propagates_none():
    assert direction.relative_to_market(-6.85, -5.08) == pytest.approx(-1.77)
    assert direction.relative_to_market(0.22, -5.08) == pytest.approx(5.30)
    assert direction.relative_to_market(None, -5.08) is None
    assert direction.relative_to_market(1.0, None) is None


def test_breadth_counts_directions_and_excludes_suspended_from_denominator():
    members = ["A", "B", "C", "D"]
    changes = {"A": 2.0, "B": -3.0, "C": 0.0, "D": None}
    breadth = direction.aggregate_breadth(members, changes)
    assert breadth.up_count == 1
    assert breadth.down_count == 1
    assert breadth.flat_count == 1
    assert breadth.suspended_count == 1
    # The suspended member is excluded from the usable count, not counted flat.
    assert breadth.valid_count == 3
    assert breadth.valid_count == breadth.up_count + breadth.down_count + breadth.flat_count


def test_breadth_median_uses_only_usable_members():
    """A suspended member must not drag the median toward zero."""

    members = ["A", "B", "C", "D"]
    changes = {"A": 1.0, "B": 3.0, "C": 5.0, "D": None}
    breadth = direction.aggregate_breadth(members, changes)
    assert breadth.status == direction.BREADTH_OK
    # Treating D as 0.0 would give 2.0 instead of 3.0.
    assert breadth.median_change_pct == pytest.approx(3.0)


def test_breadth_denominator_is_declared_members_not_fetched_rows():
    """Missing member data must reduce coverage, not fake a full board."""

    members = ["A", "B", "C", "D", "E"]
    breadth = direction.aggregate_breadth(members, {"A": 1.0})
    assert breadth.member_count == 5
    assert breadth.valid_count == 1
    assert breadth.coverage == pytest.approx(0.2)


def test_breadth_status_threshold_boundaries():
    assert direction.breadth_status(0.699) == direction.BREADTH_INSUFFICIENT
    assert direction.breadth_status(0.70) == direction.BREADTH_OK
    assert direction.breadth_status(0.95) == direction.BREADTH_OK
    assert direction.breadth_status(None) == direction.BREADTH_INSUFFICIENT


def test_breadth_withholding_median_when_coverage_insufficient():
    members = [f"M{i}" for i in range(10)]
    changes = {"M0": 1.0, "M1": 2.0, "M2": 3.0}
    breadth = direction.aggregate_breadth(members, changes)
    assert breadth.status == direction.BREADTH_INSUFFICIENT
    assert breadth.median_change_pct is None
    # Counts stay visible even when the median is withheld.
    assert breadth.up_count == 3
    assert breadth.member_count == 10


def test_breadth_uses_volumes_to_spot_suspended_members():
    members = ["A", "B"]
    breadth = direction.aggregate_breadth(
        members, {"A": 1.0, "B": 0.0}, volumes={"A": 1e6, "B": 0}
    )
    assert breadth.up_count == 1
    assert breadth.suspended_count == 1
    assert breadth.flat_count == 0


@pytest.mark.parametrize(
    "quadrant_label",
    [quadrant.QUADRANT_ACTIVE, quadrant.QUADRANT_WEIGHT,
     quadrant.QUADRANT_RETAIL, quadrant.QUADRANT_COLD],
)
def test_composite_tag_appends_direction_to_every_quadrant(quadrant_label):
    assert direction.composite_tag(quadrant_label, direction.DIRECTION_UP) == f"{quadrant_label}·上涨"
    assert direction.composite_tag(quadrant_label, direction.DIRECTION_DOWN) == f"{quadrant_label}·下跌"


def test_composite_tag_leaves_quadrant_alone_without_direction():
    assert direction.composite_tag(quadrant.QUADRANT_ACTIVE, None) == quadrant.QUADRANT_ACTIVE
    assert direction.composite_tag(quadrant.QUADRANT_ACTIVE, direction.DIRECTION_FLAT) == quadrant.QUADRANT_ACTIVE
    assert direction.composite_tag(quadrant.QUADRANT_ACTIVE, direction.DIRECTION_SUSPENDED) == quadrant.QUADRANT_ACTIVE


def test_summarize_direction_counts_and_up_amount_share():
    rows = [
        {"direction": "up", "amountYi": 30.0},
        {"direction": "down", "amountYi": 70.0},
        {"direction": "flat", "amountYi": 0.0},
    ]
    summary = direction.summarize_direction(rows)
    assert summary["up"] == 1
    assert summary["down"] == 1
    assert summary["flat"] == 1
    assert summary["up"] + summary["down"] + summary["flat"] == summary["total"]
    assert summary["upAmountShare"] == pytest.approx(0.30)


def test_summarize_direction_share_is_none_without_turnover():
    assert direction.summarize_direction([])["upAmountShare"] is None


def test_group_by_direction_keeps_only_up_and_down():
    items = [
        {"name": "a", "direction": "up"},
        {"name": "b", "direction": "down"},
        {"name": "c", "direction": "flat"},
        {"name": "d", "direction": "suspended"},
    ]
    groups = direction.group_by_direction(items)
    assert [i["name"] for i in groups["up"]] == ["a"]
    assert [i["name"] for i in groups["down"]] == ["b"]
    assert sum(len(v) for v in groups.values()) == 2


def test_group_by_direction_never_pads_an_empty_group():
    groups = direction.group_by_direction([{"name": "a", "direction": "up"}])
    assert groups["down"] == []
    assert groups["up"]


# --------------------------------------------------------------------------
# percentile.py
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bar_count", "expected_status"),
    [
        (3, percentile.STATUS_INSUFFICIENT),
        (59, percentile.STATUS_INSUFFICIENT),
        (60, percentile.STATUS_OK),
        (239, percentile.STATUS_OK),
        (272, percentile.STATUS_OK),
    ],
)
def test_percentile_bar_boundaries(bar_count, expected_status):
    series = [10.0] * (bar_count - 1) + [20.0]
    result = percentile.evaluate(series, min_bars=60)
    assert result.status == expected_status
    assert result.window_bars == bar_count


def test_percentile_below_minimum_returns_none_not_zero():
    result = percentile.evaluate([1.0, 2.0, 3.0], min_bars=60)
    assert result.percentile is None
    assert result.average_turnover is None
    assert result.amplification is None
    assert not result.usable


def test_percentile_of_volume_matches_percentile_of_turnover():
    """A constant float-share count makes the two percentiles identical."""

    volumes = [120.0, 98.0, 150.0, 91.0, 200.0, 175.0, 130.0] * 10
    float_shares = 8_000_000.0
    turnovers = [v / float_shares * 100 for v in volumes]

    from_volume = percentile.evaluate(volumes, min_bars=60)
    from_turnover = percentile.evaluate(turnovers, min_bars=60)

    assert from_volume.percentile == pytest.approx(from_turnover.percentile)
    assert from_volume.amplification == pytest.approx(from_turnover.amplification)


def test_percentile_amplification_uses_history_excluding_current():
    history = [10.0] * 60
    series = history + [30.0]
    result = percentile.evaluate(series, min_bars=60, avg_window=20)
    assert result.average_turnover == pytest.approx(10.0)
    assert result.amplification == pytest.approx(3.0)


def test_percentile_maximum_scores_one():
    series = [5.0] * 70 + [99.0]
    result = percentile.evaluate(series, min_bars=60)
    assert result.percentile == pytest.approx(1.0)


def test_percentile_rejects_non_finite_values():
    series = [10.0] * 60 + [float("inf")]
    result = percentile.evaluate(series, min_bars=60)
    # Infinity is filtered out, leaving 60 usable bars; no crash, no infinity.
    assert result.status in {percentile.STATUS_OK, percentile.STATUS_INSUFFICIENT}
    if result.usable:
        assert result.percentile is not None


def test_deferred_reports_reason_and_availability():
    payload = percentile.deferred("累计量与全天分布不可比", "15:10")
    assert payload["status"] == "deferred"
    assert payload["reason"]
    assert payload["availableAfter"] == "15:10"


# --------------------------------------------------------------------------
# contract.py
# --------------------------------------------------------------------------


def test_report_id_is_stable_within_a_run():
    moment = datetime(2026, 11, 19, 10, 30, 12, tzinfo=SHANGHAI)
    first = contract.build_contract(moment)
    second = contract.build_contract(moment)
    assert first.report_id == second.report_id


def test_report_id_differs_across_runs():
    early = contract.build_contract(datetime(2026, 11, 19, 10, 30, tzinfo=SHANGHAI))
    late = contract.build_contract(datetime(2026, 11, 19, 10, 31, tzinfo=SHANGHAI))
    assert early.report_id != late.report_id


def test_contract_versions_are_fixed():
    built = contract.build_contract(datetime(2026, 11, 19, 10, 30, tzinfo=SHANGHAI))
    assert built.rule_version == "active-industry-scan-v2"
    assert built.schema_version == "1.1"
    # The constants and the built identity must never drift apart.
    assert built.rule_version == contract.RULE_VERSION
    assert built.schema_version == contract.SCHEMA_VERSION


def test_contract_normalizes_naive_datetime_to_shanghai():
    built = contract.build_contract(datetime(2026, 11, 19, 10, 30))
    assert built.generated_at.startswith("2026-11-19T10:30:00")
    assert "+08:00" in built.generated_at


def test_contract_dict_has_required_keys():
    payload = contract.build_contract(datetime(2026, 11, 19, 10, 30, tzinfo=SHANGHAI)).as_dict()
    assert set(payload) == {"schemaVersion", "ruleVersion", "reportId", "generatedAt"}

# --------------------------------------------------------------------------
# sina_client.py
# --------------------------------------------------------------------------


def test_to_thscode_maps_all_three_exchanges():
    assert sina_client.to_thscode("sh600000") == "600000.SH"
    assert sina_client.to_thscode("sz000001") == "000001.SZ"
    assert sina_client.to_thscode("bj920309") == "920309.BJ"


def test_parse_row_extracts_ranking_fields():
    row = sina_client.parse_row(
        {
            "code": "600000",
            "symbol": "sh600000",
            "name": "样本",
            "amount": "1234567890",
            "turnoverratio": "3.5",
            "trade": "10.5",
            "nmc": "200000",
            "changepercent": "1.2",
        }
    )
    assert row is not None
    assert row.amount == pytest.approx(1234567890.0)
    assert row.turnover_pct == pytest.approx(3.5)
    assert row.float_mv_yi == pytest.approx(20.0)
    assert row.thscode == "600000.SH"


def test_parse_row_rejects_row_without_symbol_or_code():
    assert sina_client.parse_row({"code": "", "symbol": "sh600000"}) is None
    assert sina_client.parse_row({"code": "600000", "symbol": ""}) is None


def test_parse_row_tolerates_garbage_numbers():
    row = sina_client.parse_row(
        {"code": "600000", "symbol": "sh600000", "amount": "n/a", "turnoverratio": None}
    )
    assert row is not None
    assert row.amount == 0.0
    assert row.turnover_pct == 0.0


def test_rank_sorts_by_requested_key():
    rows = [
        sina_client.RankRow("1", "sh600001", "a", amount=10.0, turnover_pct=99.0,
                            price=1.0, float_mv_yi=1.0, change_pct=0.0),
        sina_client.RankRow("2", "sh600002", "b", amount=90.0, turnover_pct=1.0,
                            price=1.0, float_mv_yi=1.0, change_pct=0.0),
    ]
    assert [r.code for r in sina_client.rank(rows, "amount", top=1)] == ["2"]
    assert [r.code for r in sina_client.rank(rows, "turnoverratio", top=1)] == ["1"]


def test_rank_rejects_unknown_key():
    with pytest.raises(ValueError):
        sina_client.rank([], "nonsense", top=5)


def test_bars_up_to_filters_by_end_stamp():
    bars = [{"day": f"2026-11-19 09:{m:02d}:00", "volume": 1} for m in (35, 40, 45)]
    kept = sina_client.bars_up_to(bars, "09:40")
    assert len(kept) == 2
    assert kept[-1]["day"].endswith("09:40:00")


def test_bars_up_to_ignores_malformed_timestamps():
    bars = [{"day": "garbage"}, {"day": "2026-11-19 09:35:00", "volume": 5}]
    assert len(sina_client.bars_up_to(bars, "10:30")) == 1


def test_cumulative_volume_and_amount_skip_bad_values():
    bars = [{"volume": "100", "amount": "1.5"}, {"volume": None, "amount": "x"}]
    assert sina_client.cumulative_volume(bars) == 100
    assert sina_client.cumulative_amount(bars) == pytest.approx(1.5)


def test_fetch_sorted_pool_rejects_unknown_sort_key():
    with pytest.raises(ValueError):
        sina_client.fetch_sorted_pool("nonsense")


def test_fetch_klines_reports_missing_symbols(monkeypatch):
    def fake(symbol, **kwargs):
        return [{"day": "2026-11-19 09:35:00", "volume": 1}] if symbol == "sh600000" else []

    monkeypatch.setattr(sina_client, "fetch_kline", fake)
    bars, missing = sina_client.fetch_klines(["sh600000", "sh600001"])
    assert set(bars) == {"sh600000"}
    assert missing == ["sh600001"]


# --------------------------------------------------------------------------
# fuyao_client.py
# --------------------------------------------------------------------------


def _symbols_payload(rows):
    return json.dumps({"ok": True, "data": {"item": rows}})


def test_parse_env_file_reads_only_requested_key(tmp_path):
    env = tmp_path / "deploy.env"
    env.write_text(
        "# comment\nTUSHARE_TOKEN=secret-other\nFUYAO_API_KEY=wanted\n",
        encoding="utf-8",
    )
    assert fuyao_client.parse_env_file(env, "FUYAO_API_KEY") == "wanted"
    assert fuyao_client.parse_env_file(env, "MISSING") is None


def test_parse_env_file_handles_quotes_and_comments(tmp_path):
    env = tmp_path / "deploy.env"
    env.write_text('export FUYAO_API_KEY="quoted" # trailing\n', encoding="utf-8")
    assert fuyao_client.parse_env_file(env, "FUYAO_API_KEY") == "quoted"


def test_resolve_credential_prefers_explicit_argument(monkeypatch):
    monkeypatch.setenv("FUYAO_API_KEY", "from-env")
    key, label = fuyao_client.resolve_credential(explicit_key="explicit")
    assert key == "explicit"
    assert label == "argument"


def test_resolve_credential_falls_back_through_env_order(monkeypatch):
    monkeypatch.delenv("FUYAO_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", "legacy")
    key, label = fuyao_client.resolve_credential(search_env_file=False)
    assert key == "legacy"
    assert label == "env:MARKET_ENVIRONMENT_FUYAO_API_KEY"


def test_resolve_credential_reports_none_when_absent(monkeypatch):
    monkeypatch.delenv("FUYAO_API_KEY", raising=False)
    monkeypatch.delenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", raising=False)
    key, label = fuyao_client.resolve_credential(search_env_file=False)
    assert key is None
    assert label == "none"


def test_credential_value_never_enters_cache_or_output(tmp_path, monkeypatch):
    """The key must not appear in any serialized artifact."""

    monkeypatch.setenv("FUYAO_API_KEY", "super-secret-value")
    client = fuyao_client.FuyaoClient(cache_dir=tmp_path)
    assert client.credential_source == "env:FUYAO_API_KEY"
    blob = json.dumps(client.credential_source)
    assert "super-secret-value" not in blob


def test_list_symbols_parses_listing_dates():
    def runner(args):
        return 0, _symbols_payload([
            {"thscode": "600000.SH", "name": "样本", "list_date": "2020-01-01"},
            {"thscode": "920309.BJ", "name": "次新", "list_date": "2026-11-17"},
            {"thscode": "688845.SH", "name": "缺日期", "list_date": None},
        ]), ""

    client = fuyao_client.FuyaoClient(runner=runner)
    symbols = client.list_symbols()
    assert len(symbols) == 3
    assert symbols[0].list_date.isoformat() == "2020-01-01"
    assert symbols[2].list_date is None


def test_list_symbols_skips_rows_without_thscode():
    def runner(args):
        return 0, _symbols_payload([{"name": "无代码"}, {"thscode": "600000.SH", "name": "ok"}]), ""

    assert len(fuyao_client.FuyaoClient(runner=runner).list_symbols()) == 1


def test_client_raises_on_nonzero_exit():
    client = fuyao_client.FuyaoClient(runner=lambda args: (1, "", "boom"))
    with pytest.raises(fuyao_client.FuyaoError):
        client.list_symbols()


def test_client_raises_on_ok_false():
    payload = json.dumps({"ok": False, "error": {"message": "限流"}})
    client = fuyao_client.FuyaoClient(runner=lambda args: (0, payload, ""))
    with pytest.raises(fuyao_client.FuyaoError, match="限流"):
        client.list_symbols()


def test_stock_history_chunks_by_ten_codes():
    calls = []

    def runner(args):
        codes = args[args.index("--thscodes") + 1]
        calls.append(len(codes.split(",")))
        items = [{"thscode": c, "item": [{"date_ms": 1, "volume": 1}]} for c in codes.split(",")]
        return 0, json.dumps({"ok": True, "data": {"item": items}}), ""

    client = fuyao_client.FuyaoClient(runner=runner)
    result = client.stock_history(
        [f"6000{i:02d}.SH" for i in range(23)],
        date(2025, 1, 1),
        date(2026, 1, 1),
    )
    assert calls == [10, 10, 3]
    assert len(result) == 23


def test_listing_days_computes_from_list_date():
    info = fuyao_client.SymbolInfo("920309.BJ", "次新", date(2026, 11, 17))
    assert info.listing_days(date(2026, 11, 19)) == 2


def test_filter_by_listing_age_excludes_young_and_missing():
    rows = [
        sina_client.RankRow("600000", "sh600000", "老股", 1.0, 1.0, 1.0, 1.0, 0.0),
        sina_client.RankRow("920309", "bj920309", "次新", 1.0, 1.0, 1.0, 1.0, 0.0),
        sina_client.RankRow("688845", "sh688845", "缺日期", 1.0, 1.0, 1.0, 1.0, 0.0),
    ]
    symbols = {
        "600000.SH": fuyao_client.SymbolInfo("600000.SH", "老股", date(2020, 1, 1)),
        "920309.BJ": fuyao_client.SymbolInfo("920309.BJ", "次新", date(2026, 11, 17)),
        "688845.SH": fuyao_client.SymbolInfo("688845.SH", "缺日期", None),
    }
    kept, excluded, missing = fuyao_client.filter_by_listing_age(
        rows, symbols, date(2026, 11, 19), min_listing_days=250
    )
    assert [r.thscode for r in kept] == ["600000.SH"]
    assert [e["code"] for e in excluded] == ["920309.BJ"]
    assert excluded[0]["listingDays"] == 2
    assert missing == ["688845.SH"]


def test_filter_by_listing_age_keeps_all_when_pool_is_old():
    rows = [sina_client.RankRow(f"60000{i}", f"sh60000{i}", "老股", 1.0, 1.0, 1.0, 1.0, 0.0)
            for i in range(5)]
    symbols = {r.thscode: fuyao_client.SymbolInfo(r.thscode, "老股", date(2015, 1, 1)) for r in rows}
    kept, excluded, missing = fuyao_client.filter_by_listing_age(
        rows, symbols, date(2026, 11, 19), min_listing_days=250
    )
    assert len(kept) == 5
    assert excluded == []
    assert missing == []


def test_index_snapshot_parses_board_changes_and_keeps_missing_as_none():
    def runner(args):
        assert args[:2] == ["index", "snapshot"]
        codes = args[args.index("--thscodes") + 1]
        assert len(codes.split(",")) == 90
        return 0, json.dumps({"ok": True, "data": {"item": [
            {"thscode": "881121.TI", "price_change_ratio_pct": -6.847481},
            {"thscode": "881101.TI", "price_change_ratio_pct": None},
            {"name": "无代码"},
        ]}}), ""

    changes = fuyao_client.FuyaoClient(runner=runner).index_snapshot(
        [f"8811{i:02d}.TI" for i in range(90)]
    )
    assert changes["881121.TI"] == pytest.approx(-6.847481)
    assert changes["881101.TI"] is None
    assert len(changes) == 2


def test_index_snapshot_supports_a_full_level_two_catalogue():
    def runner(args):
        codes = args[args.index("--thscodes") + 1]
        assert len(codes.split(",")) == 230
        return 0, json.dumps({"ok": True, "data": {"item": [
            {"thscode": "884101.TI", "price_change_ratio_pct": -2.699863},
        ]}}), ""

    changes = fuyao_client.FuyaoClient(runner=runner).index_snapshot(
        [f"8841{i:02d}.TI" for i in range(230)]
    )
    assert changes == {"884101.TI": pytest.approx(-2.699863)}


def test_index_snapshot_empty_input_makes_no_call():
    def runner(args):  # pragma: no cover - must not be reached
        raise AssertionError("should not call the CLI for an empty list")

    assert fuyao_client.FuyaoClient(runner=runner).index_snapshot([]) == {}


def test_index_snapshot_failure_raises_for_caller_to_degrade():
    def runner(args):
        return 1, "", "boom"

    with pytest.raises(fuyao_client.FuyaoError):
        fuyao_client.FuyaoClient(runner=runner).index_snapshot(["881121.TI"])


def test_market_snapshot_pages_concurrently_and_dedupes_by_thscode():
    calls: list[int] = []

    def runner(args):
        assert args[:2] == ["market", "snapshot"]
        offset = int(args[args.index("--offset") + 1])
        calls.append(offset)
        # Page 0 and page 1 overlap on 000002.SZ on purpose.
        if offset == 0:
            rows = [
                {"thscode": "000001.SZ", "price_change_ratio_pct": 1.495017, "volume": 2.1e8},
                {"thscode": "000002.SZ", "price_change_ratio_pct": -3.424658, "volume": 1.5e8},
            ]
        elif offset == 1000:
            rows = [
                {"thscode": "000002.SZ", "price_change_ratio_pct": -3.5, "volume": 1.5e8},
                {"thscode": "000006.SZ", "price_change_ratio_pct": None, "volume": 0},
            ]
        else:
            rows = []
        return 0, json.dumps({"ok": True, "data": {"item": rows}}), ""

    snapshot = fuyao_client.FuyaoClient(runner=runner).market_snapshot(max_pages=3)
    assert len(calls) == 3
    assert set(snapshot.changes) == {"000001.SZ", "000002.SZ", "000006.SZ"}
    # The later page wins on overlap, and keeps the last observed value.
    assert snapshot.changes["000002.SZ"] == pytest.approx(-3.5)
    # A missing change stays None; the volume hint is preserved.
    assert snapshot.changes["000006.SZ"] is None
    assert snapshot.volumes["000006.SZ"] == 0
    assert snapshot.source == "fuyao-market-snapshot"


def test_market_change_map_uses_primary_path_without_touching_fallback():
    def fallback():  # pragma: no cover - must not be reached
        raise AssertionError("fallback must not run when the primary succeeds")

    client = fuyao_client.FuyaoClient(
        runner=lambda args: (0, json.dumps({"ok": True, "data": {"item": [
            {"thscode": "600000.SH", "price_change_ratio_pct": 1.5, "volume": 1e6},
        ]}}), "")
    )
    snapshot = fuyao_client.market_change_map(client, fallback=fallback)
    assert snapshot.source == "fuyao-market-snapshot"
    assert snapshot.changes == {"600000.SH": 1.5}


def test_market_change_map_falls_back_when_primary_fails():
    client = fuyao_client.FuyaoClient(runner=lambda args: (1, "", "boom"))
    recovered = fuyao_client.MarketSnapshot(
        changes={"600000.SH": 2.0}, volumes={"600000.SH": 1e6},
        source="sina-full-snapshot",
    )
    snapshot = fuyao_client.market_change_map(client, fallback=lambda: recovered)
    assert snapshot.source == "sina-full-snapshot"
    assert snapshot.changes == {"600000.SH": 2.0}


def test_market_change_map_returns_empty_snapshot_when_everything_fails():
    """Losing the benchmark degrades the run; it must not raise."""

    client = fuyao_client.FuyaoClient(runner=lambda args: (1, "", "boom"))

    def fallback():
        raise fuyao_client.FuyaoError("fallback down")

    snapshot = fuyao_client.market_change_map(client, fallback=fallback)
    assert snapshot.changes == {}
    assert snapshot.source == "unavailable"
    assert not snapshot


# --------------------------------------------------------------------------
# industry_map.py
# --------------------------------------------------------------------------


def _board(code, name, level, members):
    return industry_map.IndustryBoard(code, name, level, tuple(members))


def _row(code):
    suffix = "SH" if code.startswith("6") else "SZ"
    return sina_client.RankRow(code, f"sh{code}", f"样本{code}", 1.0, 1.0, 1.0, 1.0, 0.0)


def test_aggregate_counts_both_rankings_per_board():
    boards = [
        _board("881101.TI", "半导体", 1, ["600001.SH", "600002.SH", "600003.SH"]),
        _board("881102.TI", "元件", 1, ["600004.SH", "600005.SH"]),
    ]
    amount = [_row("600001"), _row("600002"), _row("600004")]
    turnover = [_row("600001"), _row("600005")]
    hits = {h.thscode: h for h in industry_map.aggregate(boards, amount, turnover, level=1)}
    assert hits["881101.TI"].amount_top_count == 2
    assert hits["881101.TI"].turnover_top_count == 1
    assert hits["881102.TI"].amount_top_count == 1
    assert hits["881102.TI"].turnover_top_count == 1


def test_aggregate_omits_boards_with_no_hits():
    boards = [_board("881101.TI", "半导体", 1, ["600001.SH"])]
    hits = industry_map.aggregate(boards, [], [], level=1)
    assert hits == []


def test_aggregate_filters_by_level():
    boards = [
        _board("881101.TI", "一级", 1, ["600001.SH"]),
        _board("884101.TI", "二级", 2, ["600001.SH"]),
    ]
    level_one = industry_map.aggregate(boards, [_row("600001")], [], level=1)
    level_two = industry_map.aggregate(boards, [_row("600001")], [], level=2)
    assert [h.thscode for h in level_one] == ["881101.TI"]
    assert [h.thscode for h in level_two] == ["884101.TI"]


def test_both_levels_are_counted_independently():
    """A stock in both levels contributes to each level's own count."""

    boards = [
        _board("881101.TI", "一级", 1, ["600001.SH"]),
        _board("884101.TI", "二级", 2, ["600001.SH"]),
    ]
    amount = [_row("600001")]
    one = industry_map.aggregate(boards, amount, [], level=1)
    two = industry_map.aggregate(boards, amount, [], level=2)
    assert one[0].amount_top_count == 1
    assert two[0].amount_top_count == 1


def test_hit_rate_is_none_for_empty_board():
    boards = [_board("881104.TI", "空行业", 1, [])]
    hits = industry_map.aggregate(boards, [], [], level=1)
    # No hits at all, so the board is omitted; assert the helper directly.
    assert quadrant.hit_rate(0, 0) is None
    assert hits == []


def test_hit_rate_none_survives_into_output_shape(monkeypatch):
    """An empty membership must surface as null, not 0."""

    boards = [_board("881104.TI", "空行业", 1, ["600001.SH"])]
    # Force a zero denominator by making the board appear with no members but
    # still counted, via a direct IndustryHit construction path.
    hit = industry_map.IndustryHit(
        thscode="881104.TI",
        name="空行业",
        level=1,
        amount_top_count=0,
        turnover_top_count=0,
        member_count=0,
        quadrant=quadrant.QUADRANT_COLD,
        hit_rate_amount=quadrant.hit_rate(0, 0),
        hit_rate_turnover=quadrant.hit_rate(0, 0),
    )
    payload = hit.as_dict()
    assert payload["hitRateAmount"] is None
    assert payload["hitRateTurnover"] is None
    json.dumps(payload)  # must serialize


def test_aggregate_output_is_json_serializable():
    boards = [_board("881101.TI", "半导体", 1, ["600001.SH"])]
    hits = industry_map.aggregate(boards, [_row("600001")], [_row("600001")], level=1)
    json.dumps([h.as_dict() for h in hits], ensure_ascii=False)


def test_board_level_infers_from_prefix():
    assert industry_map.board_level("881121.TI") == 1
    assert industry_map.board_level("884021.TI") == 2


def test_cache_round_trip(tmp_path):
    boards = [_board("881101.TI", "半导体", 1, ["600001.SH", "600002.SH"])]
    industry_map.save_boards(tmp_path, date(2026, 11, 19), 1, boards)
    loaded = industry_map.load_boards(tmp_path, date(2026, 11, 19), 1)
    assert loaded is not None
    restored, effective = loaded
    assert effective == date(2026, 11, 19)
    assert restored[0].members == ("600001.SH", "600002.SH")


def test_cache_falls_back_to_older_file(tmp_path):
    boards = [_board("881101.TI", "半导体", 1, ["600001.SH"])]
    industry_map.save_boards(tmp_path, date(2026, 11, 18), 1, boards)
    loaded = industry_map.load_boards(tmp_path, date(2026, 11, 19), 1)
    assert loaded is not None
    _, effective = loaded
    assert effective == date(2026, 11, 18)


def test_cache_returns_none_when_absent(tmp_path):
    assert industry_map.load_boards(tmp_path, date(2026, 11, 19), 1) is None


def test_cache_ignores_newer_files(tmp_path):
    boards = [_board("881101.TI", "半导体", 1, ["600001.SH"])]
    industry_map.save_boards(tmp_path, date(2026, 11, 20), 1, boards)
    assert industry_map.load_boards(tmp_path, date(2026, 11, 19), 1) is None


def test_pool_filter_fills_ranking_to_full_size():
    """Filtering must happen before truncation so Top-N stays complete."""

    rows = []
    for i in range(60):
        rows.append(sina_client.RankRow(f"9200{i:02d}", f"bj9200{i:02d}", f"次新{i}", 1.0,
                                        50.0 - i, 1.0, 1.0, 0.0))
    for i in range(60):
        rows.append(sina_client.RankRow(f"6000{i:02d}", f"sh6000{i:02d}", f"老股{i}", 1.0,
                                        30.0 - i, 1.0, 1.0, 0.0))
    symbols = {}
    for row in rows[:60]:
        symbols[row.thscode] = fuyao_client.SymbolInfo(row.thscode, row.name, date(2026, 11, 1))
    for row in rows[60:]:
        symbols[row.thscode] = fuyao_client.SymbolInfo(row.thscode, row.name, date(2015, 1, 1))

    kept, excluded, missing = fuyao_client.filter_by_listing_age(
        rows, symbols, date(2026, 11, 19), min_listing_days=250
    )
    assert len(excluded) == 60
    assert missing == []
    assert len(kept) == 60
    ranked = sina_client.rank(kept, "turnoverratio", top=50)
    assert len(ranked) == 50
    # Every surviving stock is an established listing.
    assert all(r.code.startswith("6000") for r in ranked)


def test_excluded_entries_carry_original_rank():
    rows = [
        sina_client.RankRow("600000", "sh600000", "老股", 1.0, 30.0, 1.0, 1.0, 0.0),
        sina_client.RankRow("920309", "bj920309", "次新", 1.0, 46.36, 1.0, 1.0, 0.0),
    ]
    symbols = {
        "600000.SH": fuyao_client.SymbolInfo("600000.SH", "老股", date(2015, 1, 1)),
        "920309.BJ": fuyao_client.SymbolInfo("920309.BJ", "次新", date(2026, 11, 17)),
    }
    _, excluded, _ = fuyao_client.filter_by_listing_age(
        rows, symbols, date(2026, 11, 19), min_listing_days=250
    )
    assert excluded[0]["name"] == "次新"
    assert excluded[0]["listingDays"] == 2
    assert excluded[0]["listDate"] == "2026-11-17"


def test_missing_list_date_is_reported_separately():
    rows = [sina_client.RankRow("688845", "sh688845", "缺日期", 1.0, 30.0, 1.0, 1.0, 0.0)]
    symbols = {"688845.SH": fuyao_client.SymbolInfo("688845.SH", "缺日期", None)}
    kept, excluded, missing = fuyao_client.filter_by_listing_age(
        rows, symbols, date(2026, 11, 19), min_listing_days=250
    )
    assert kept == []
    assert excluded == []
    assert missing == ["688845.SH"]


# --------------------------------------------------------------------------
# session.py
# --------------------------------------------------------------------------


def _at(hhmm: str, day: int = 19):
    hour, minute = (int(p) for p in hhmm.split(":"))
    return datetime(2026, 11, day, hour, minute, tzinfo=SHANGHAI)


@pytest.mark.parametrize(
    ("hhmm", "expected"),
    [
        ("09:29", session.STATE_PREOPEN),
        ("09:31", session.STATE_INTRADAY),
        ("11:29", session.STATE_INTRADAY),
        ("11:31", session.STATE_LUNCH),
        ("12:59", session.STATE_LUNCH),
        ("13:01", session.STATE_INTRADAY),
        ("14:59", session.STATE_INTRADAY),
        ("15:05", session.STATE_SETTLING),
        ("15:11", session.STATE_CLOSED),
    ],
)
def test_session_state_across_the_day(hhmm, expected):
    assert session.session_state(_at(hhmm)) == expected


def test_elapsed_bars_before_open_is_zero():
    assert session.elapsed_bars(_at("09:29")) == 0


def test_elapsed_bars_at_1030_is_twelve():
    """09:35 through 10:30 inclusive is twelve completed bars."""

    assert session.elapsed_bars(_at("10:30")) == 12


def test_elapsed_bars_freeze_during_lunch():
    assert session.elapsed_bars(_at("11:31")) == 24
    assert session.elapsed_bars(_at("12:59")) == 24


def test_elapsed_bars_full_session_is_48():
    assert session.elapsed_bars(_at("15:00")) == 48
    assert session.elapsed_bars(_at("15:11")) == 48


def test_data_cutoff_matches_last_completed_bar():
    assert session.data_cutoff(_at("10:30")).endswith("10:30:00+08:00")
    assert session.data_cutoff(_at("11:31")).endswith("11:30:00+08:00")
    assert session.data_cutoff(_at("13:01")).endswith("11:30:00+08:00")


def test_data_cutoff_empty_before_open():
    assert session.data_cutoff(_at("09:29")) == ""


def test_data_cutoff_snaps_to_close_after_settlement():
    assert session.data_cutoff(_at("15:11")).endswith("15:00:00+08:00")


def test_early_snapshot_flag_only_for_first_three_bars():
    assert session.describe(_at("09:35")).early_snapshot is True
    assert session.describe(_at("09:40")).early_snapshot is True
    assert session.describe(_at("09:50")).early_snapshot is False
    assert session.describe(_at("10:30")).early_snapshot is False


def test_settled_only_after_settlement_time():
    assert session.describe(_at("15:05")).settled is False
    assert session.describe(_at("15:11")).settled is True


def test_settlement_time_honours_environment(monkeypatch):
    monkeypatch.setenv(session.SETTLEMENT_ENV, "15:30")
    assert session.session_state(_at("15:20")) == session.STATE_SETTLING
    assert session.session_state(_at("15:31")) == session.STATE_CLOSED
    monkeypatch.delenv(session.SETTLEMENT_ENV)


def test_open_time_honours_environment(monkeypatch):
    monkeypatch.setenv(session.OPEN_ENV, "09:45")
    assert session.session_state(_at("09:40")) == session.STATE_PREOPEN
    monkeypatch.delenv(session.OPEN_ENV)


def test_early_snapshot_warning_mentions_auction():
    text = session.early_snapshot_warning()
    assert "集合竞价" in text
    assert "15.9" in text or "47.3" in text


def test_session_report_serializes():
    payload = session.describe(_at("10:30")).as_dict()
    assert payload["sessionState"] == "intraday"
    assert payload["elapsedBars"] == 12
    assert set(payload) == {
        "sessionState", "elapsedBars", "dataCutoff", "earlySnapshot", "settled"
    }
    json.dumps(payload)


# --------------------------------------------------------------------------
# deferred percentile
# --------------------------------------------------------------------------


def test_intraday_percentile_is_deferred_not_scaled():
    """No state may synthesize a percentile from a partial session."""

    payload = percentile.deferred(
        "当日累计量与历史全天分布不可比", "15:10"
    )
    assert payload["status"] == "deferred"
    assert "availableAfter" in payload
    for forbidden in ("estimate", "scaled", "extrapolated"):
        assert forbidden not in json.dumps(payload)


def test_settled_state_permits_percentile():
    assert session.is_settled(session.STATE_CLOSED) is True
    for state in (
        session.STATE_PREOPEN,
        session.STATE_INTRADAY,
        session.STATE_LUNCH,
        session.STATE_SETTLING,
    ):
        assert session.is_settled(state) is False


# --------------------------------------------------------------------------
# scan_pipeline.py + report.py
# --------------------------------------------------------------------------


def _fixture(name: str = "scan.json") -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "scan_pipeline.py"), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_fixture_run_produces_all_four_quadrants(tmp_path):
    out = tmp_path / "out.json"
    completed = _run_cli("--fixture", str(FIXTURES / "scan.json"), "--output", str(out))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    quadrants = {i["name"]: i["quadrant"] for i in result["industries"]}
    assert quadrants["半导体"] == "真实活跃"
    assert quadrants["元件"] == "权重拉升"
    assert quadrants["环保设备"] == "小盘情绪"


def test_fixture_run_reports_intraday_state_and_deferred_percentile(tmp_path):
    out = tmp_path / "out.json"
    _run_cli("--fixture", str(FIXTURES / "scan.json"), "--output", str(out))
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["sessionState"] == "intraday"
    assert result["percentile"]["status"] == "deferred"
    assert result["percentile"]["availableAfter"] == "15:10"


def test_fixture_intersection_is_not_relaxed_when_disjoint(tmp_path):
    payload = {
        "now": "2026-11-19T10:30:00+08:00",
        "byAmount": [_row("600000").__dict__ | {"amount": 9e9}],
        "byTurnover": [_row("600100").__dict__ | {"turnoverratio": 40.0}],
        "boards": [],
    }
    fixture = tmp_path / "disjoint.json"
    fixture.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.json"
    completed = _run_cli("--fixture", str(fixture), "--output", str(out))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["intersection"] == []
    assert result["quality"]["status"] == "ok"


def test_fixture_excludes_无数据时返回非零(tmp_path):
    payload = {"now": "2026-11-19T10:30:00+08:00", "byAmount": [], "byTurnover": [], "boards": []}
    fixture = tmp_path / "empty.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    completed = _run_cli("--fixture", str(fixture))
    assert completed.returncode == 2
    assert "无法产出结果" in completed.stderr


def test_handoff_lists_candidate_codes_and_disclaims_scoring(tmp_path):
    out = tmp_path / "out.json"
    _run_cli("--fixture", str(FIXTURES / "scan.json"), "--output", str(out))
    result = json.loads(out.read_text(encoding="utf-8"))
    handoff = result["handoff"]
    assert handoff["target"] == "a-stock-qts04-sector-direction"
    assert handoff["candidateThscodes"]
    assert "不评分" in handoff["note"]


def test_handoff_candidates_are_usable_thscodes(tmp_path):
    out = tmp_path / "out.json"
    _run_cli("--fixture", str(FIXTURES / "scan.json"), "--output", str(out))
    result = json.loads(out.read_text(encoding="utf-8"))
    for code in result["handoff"]["candidateThscodes"]:
        assert code.startswith("881") or code.startswith("884")
        assert code.endswith(".TI")


# --------------------------------------------------------------------------
# direction layer through the full pipeline (fixture direction.json)
# --------------------------------------------------------------------------


def _direction_result(tmp_path, fixture="direction.json", *extra):
    out = tmp_path / "out.json"
    completed = _run_cli("--fixture", str(FIXTURES / fixture), "--output", str(out), *extra)
    assert completed.returncode == 0, completed.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def _industry(result, name):
    return next(item for item in result["industries"] if item["name"] == name)


def test_market_baseline_is_published_and_recomputable(tmp_path):
    result = _direction_result(tmp_path)
    market = result["direction"]["market"]
    assert market["status"] == "ok"
    assert market["medianChangePct"] == pytest.approx(-2.2)
    assert market["upCount"] + market["downCount"] + market["flatCount"] == market["validCount"]
    assert market["validCount"] + market["suspendedCount"] == market["universe"]
    assert result["direction"]["relativeBasis"] == "equal-weight-vs-market-median"


def test_industry_directions_differ_while_quadrant_stays_active(tmp_path):
    """The whole point: heavy trading is not the same as rising."""

    result = _direction_result(tmp_path)
    semis = _industry(result, "半导体")
    bank = _industry(result, "银行")

    assert semis["quadrant"] == "真实活跃"
    assert semis["direction"] == "down"
    assert semis["tag"] == "真实活跃·下跌"

    assert bank["direction"] == "up"
    assert bank["tag"] == "权重拉升·上涨"

    # Opposite directions, opposite relative excess.
    assert semis["relativeToMarketPct"] < 0 < bank["relativeToMarketPct"]


def test_industry_reports_all_three_evidence_sets(tmp_path):
    result = _direction_result(tmp_path)
    semis = _industry(result, "半导体")
    # board index, ranking hits, member breadth — all present at once.
    assert semis["boardChangePct"] == pytest.approx(-6.8475)
    assert semis["hitDownCount"] == 4 and semis["hitUpCount"] == 0
    assert semis["memberDownCount"] == 4 and semis["memberUpCount"] == 0
    assert semis["directionBasis"] == "member-median"


def test_low_coverage_withholds_breadth_but_keeps_other_evidence(tmp_path):
    result = _direction_result(tmp_path)
    thin = _industry(result, "低覆盖行业")
    assert thin["memberBreadthStatus"] == "insufficient"
    assert thin["memberMedianChangePct"] is None
    assert thin["relativeToMarketPct"] is None
    # Board index and hit counts survive, and the basis says which one decided.
    assert thin["boardChangePct"] == pytest.approx(-3.1)
    assert thin["hitUpCount"] == 4 and thin["hitDownCount"] == 4
    assert thin["directionBasis"] == "board-index"


def test_suspended_members_are_excluded_not_counted_flat(tmp_path):
    result = _direction_result(tmp_path)
    semis = _industry(result, "半导体")
    # 600099.SH has no measurement at all; that is "unknown", not "flat".
    assert semis["memberUnknownCount"] == 1
    assert semis["memberFlatCount"] == 0
    assert semis["memberCoverage"] == pytest.approx(0.8)


def test_direction_summary_counts_match_ranking_rows(tmp_path):
    result = _direction_result(tmp_path)
    for key in ("byAmount", "byTurnover"):
        rows = result["rankings"][key]
        summary = result["directionSummary"][key]
        assert summary["up"] == sum(1 for r in rows if r["direction"] == "up")
        assert summary["down"] == sum(1 for r in rows if r["direction"] == "down")
        assert summary["suspended"] == sum(
            1 for r in rows if r["direction"] == "suspended"
        )
        assert (summary["up"] + summary["down"] + summary["flat"]
                + summary["suspended"] == summary["total"])
        amount_total = sum(r["amountYi"] for r in rows)
        if amount_total:
            expected = sum(r["amountYi"] for r in rows if r["direction"] == "up") / amount_total
            assert summary["upAmountShare"] == pytest.approx(expected, abs=1e-4)


def test_ranking_rows_carry_direction_and_relative(tmp_path):
    result = _direction_result(tmp_path)
    market = result["direction"]["market"]["medianChangePct"]
    seen = set()
    for row in result["rankings"]["byAmount"]:
        seen.add(row["direction"])
        if row["relativeToMarketPct"] is not None:
            assert row["relativeToMarketPct"] == pytest.approx(
                row["changePct"] - market, abs=1e-2
            )
    assert "up" in seen and "down" in seen


def test_intersection_groups_by_direction_without_losing_members(tmp_path):
    result = _direction_result(tmp_path)
    items = result["intersection"]
    groups = direction.group_by_direction(items)
    assert len(groups["up"]) == 1
    assert len(groups["down"]) == 2
    # Grouping is a view: nobody is dropped.
    assert len(groups["up"]) + len(groups["down"]) == len(items)
    assert {i["direction"] for i in items} == {"up", "down"}


def test_handoff_list_is_unaffected_by_direction(tmp_path):
    """Candidates are chosen by activity; direction only annotates them."""

    result = _direction_result(tmp_path)
    candidates = result["handoff"]["candidateThscodes"]
    assert len(candidates) == len(result["handoff"]["candidates"])
    tags = {c["thscode"]: c["tag"] for c in result["handoff"]["candidates"]}
    # A falling industry stays in the list, carrying its direction.
    assert "881121.TI" in candidates
    assert tags["881121.TI"] == "真实活跃·下跌"


def test_direction_does_not_reorder_industries(tmp_path):
    """Decorating must not disturb the activity ordering."""

    result = _direction_result(tmp_path)
    flags = [
        int(i["amountTopCount"] >= 2 and i["turnoverTopCount"] >= 2)
        for i in result["industries"]
    ]
    # Two-ranking industries still come before every one-sided one.
    assert flags == sorted(flags, reverse=True)


def test_preopen_labels_direction_as_previous_session(tmp_path):
    payload = _fixture("direction.json")
    payload["now"] = "2026-11-20T09:00:00+08:00"
    fixture = tmp_path / "preopen.json"
    fixture.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.json"
    completed = _run_cli("--fixture", str(fixture), "--output", str(out))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["sessionState"] == "preopen"
    assert "前一交易日" in result["direction"]["basisNote"]


def test_absence_of_market_data_nulls_relatives_without_guessing(tmp_path):
    """scan.json has no market block: absolute direction still works."""

    result = _direction_result(tmp_path, "scan.json")
    market = result["direction"]["market"]
    assert market["status"] == "insufficient"
    assert market["medianChangePct"] is None
    assert market["upCount"] == 0
    for item in result["industries"]:
        assert item["relativeToMarketPct"] is None
        assert item["boardRelativeToMarketPct"] is None
    # Absolute direction is still derived from each stock's own change.
    assert {r["direction"] for r in result["rankings"]["byAmount"]} == {"up"}


def test_fixture_without_direction_keys_defaults_to_none_not_zero():
    """A fixture lacking direction evidence must not imply a zero move."""

    inputs, _ = scan_pipeline.load_fixture(FIXTURES / "scan.json")
    assert inputs.market is None
    assert inputs.board_changes == {}


def test_build_result_survives_missing_direction_inputs():
    inputs, options = scan_pipeline.load_fixture(FIXTURES / "scan.json")
    result = scan_pipeline.build_result(
        inputs, top=8, candidate_pool=50, min_listing_days=250,
        level=1, top_sectors=6, quality=scan_pipeline.Quality(),
    )
    assert result["direction"]["market"]["medianChangePct"] is None
    assert result["directionSummary"]["byAmount"]["total"] == 8
    assert all(i["direction"] in {None, "up", "down", "flat", "suspended"}
               for i in result["industries"])


def test_zero_amount_ranking_row_is_suspended_not_flat(tmp_path):
    """A row with no traded value cannot have a real move, so it is not flat."""

    result = _direction_result(tmp_path)
    rows = {r["name"]: r for r in result["rankings"]["byTurnover"]}
    assert rows["停牌股"]["direction"] == "suspended"
    assert rows["平盘股"]["direction"] == "flat"
    summary = result["directionSummary"]["byTurnover"]
    assert summary["suspended"] == 1
    assert summary["flat"] == 1


def test_level_both_annotates_second_level_boards(tmp_path):
    payload = _fixture("direction.json")
    payload["boards"].append(
        {"thscode": "884001.TI", "name": "半导体(二级)", "level": 2,
         "members": ["600001.SH", "600002.SH", "600003.SH", "600004.SH"]}
    )
    payload["boardChanges"]["884001.TI"] = -7.4
    payload["options"] = {"top": 8, "topSectors": 6, "level": "both"}
    fixture = tmp_path / "both.json"
    fixture.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.json"
    completed = _run_cli("--fixture", str(fixture), "--level", "both",
                         "--output", str(out))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    second = next(i for i in result["industries"] if i["level"] == 2)
    assert second["boardChangePct"] == pytest.approx(-7.4)
    assert second["direction"] == "down"
    assert second["tag"].endswith("下跌")


def test_empty_intersection_still_carries_direction_blocks(tmp_path):
    payload = _fixture("direction.json")
    # Make the two rankings disjoint.
    payload["byTurnover"] = [
        dict(row, code=f"6011{i:02d}", symbol=f"sh6011{i:02d}")
        for i, row in enumerate(payload["byTurnover"])
    ]
    fixture = tmp_path / "disjoint.json"
    fixture.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out, md = tmp_path / "out.json", tmp_path / "out.md"
    completed = _run_cli("--fixture", str(fixture),
                         "--output", str(out), "--markdown", str(md))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["intersection"] == []
    # Direction sections are unaffected by an empty intersection.
    assert result["direction"]["market"]["status"] == "ok"
    assert result["directionSummary"]["byAmount"]["total"] > 0
    text = md.read_text(encoding="utf-8")
    assert "本次无交集" in text
    assert "活跃下跌" in text


def test_markdown_numbers_match_json(tmp_path):
    out = tmp_path / "out.json"
    md = tmp_path / "out.md"
    _run_cli("--fixture", str(FIXTURES / "scan.json"),
             "--output", str(out), "--markdown", str(md))
    result = json.loads(out.read_text(encoding="utf-8"))
    text = md.read_text(encoding="utf-8")
    for item in result["industries"]:
        assert item["name"] in text
        assert str(item["amountTopCount"]) in text
        assert str(item["turnoverTopCount"]) in text
    assert result["reportId"] in text
    assert result["ruleVersion"] in text


def _direction_markdown(tmp_path):
    out = tmp_path / "out.json"
    md = tmp_path / "out.md"
    completed = _run_cli("--fixture", str(FIXTURES / "direction.json"),
                         "--output", str(out), "--markdown", str(md))
    assert completed.returncode == 0, completed.stderr
    return json.loads(out.read_text(encoding="utf-8")), md.read_text(encoding="utf-8")


def test_markdown_industry_table_carries_direction_columns(tmp_path):
    result, text = _direction_markdown(tmp_path)
    header = next(line for line in text.splitlines() if line.startswith("| 行业 |"))
    for column in ("板块涨跌", "上榜涨跌", "相对市场", "方向标签"):
        assert column in header
    # A withheld value renders as a dash, never as 0.
    thin = _industry(result, "低覆盖行业")
    assert thin["relativeToMarketPct"] is None
    row = next(line for line in text.splitlines() if line.startswith("| 低覆盖行业 |"))
    assert "—" in row


def test_markdown_direction_groups_match_json_membership(tmp_path):
    """Group membership and labels must be a pure render of the JSON."""

    result, text = _direction_markdown(tmp_path)
    groups = direction.group_by_direction(result["industries"])
    up_block = text.split("### 活跃上涨")[1].split("### ")[0]
    down_block = text.split("### 活跃下跌")[1].split("\n- ")[0]

    assert f"（{len(groups['up'])} 个）" in text
    assert f"（{len(groups['down'])} 个）" in text
    for item in groups["up"]:
        assert item["name"] in up_block
        assert item["tag"] in up_block
    for item in groups["down"]:
        assert item["name"] in down_block
    # The rising and falling blocks never swap members.
    for item in groups["down"]:
        assert item["name"] not in up_block


def test_markdown_group_lists_strongest_relative_first(tmp_path):
    result, text = _direction_markdown(tmp_path)
    down_block = text.split("### 活跃下跌")[1].split("\n- ")[0]
    names = [i["name"] for i in direction.group_by_direction(
        result["industries"], order_by_relative=True)["down"]]
    positions = [down_block.index(n) for n in names]
    assert positions == sorted(positions)


def test_direction_groups_partition_the_industry_table(tmp_path):
    """No industry may vanish from the grouping: it is a full split, not a top-N."""

    result, text = _direction_markdown(tmp_path)
    grouped = direction.group_by_direction(result["industries"])
    directional = [i for i in result["industries"] if i["direction"] in {"up", "down"}]
    assert len(grouped["up"]) + len(grouped["down"]) == len(directional)
    for item in directional:
        assert item["name"] in text.split("## 三")[0]

    # The limit constant must not quietly recut the already-capped table.
    assert report.DIRECTION_GROUP_LIMIT is None


def test_markdown_states_empty_group_explicitly(tmp_path):
    """An all-one-way day must say so rather than padding the empty side."""

    payload = _fixture("direction.json")
    for board in payload["boards"]:
        board["members"] = [m for m in board["members"] if m.startswith("60000")
                            and m in {"600001.SH", "600002.SH", "600003.SH", "600004.SH"}]
    payload["boards"] = [b for b in payload["boards"] if b["members"]]
    payload["byTurnover"] = [r for r in payload["byTurnover"] if r["changepercent"] < 0]
    fixture = tmp_path / "oneway.json"
    fixture.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out, md = tmp_path / "out.json", tmp_path / "out.md"
    completed = _run_cli("--fixture", str(fixture), "--output", str(out), "--markdown", str(md))
    assert completed.returncode == 0, completed.stderr
    text = md.read_text(encoding="utf-8")
    assert "活跃上涨（0 个）" in text
    assert "本次该分组为空" in text


def test_markdown_direction_footer_declares_thresholds_and_disclaimer(tmp_path):
    _, text = _direction_markdown(tmp_path)
    assert "needs-backtest" in text
    assert "不构成买卖信号" in text
    assert "停牌与无昨收样本剔出分母" in text


def test_markdown_direction_section_reports_market_baseline(tmp_path):
    result, text = _direction_markdown(tmp_path)
    market = result["direction"]["market"]
    assert f"{market['medianChangePct']:.2f}%" in text
    assert f"涨 {market['upCount']} / 跌 {market['downCount']}" in text


def test_markdown_rendering_is_deterministic_with_direction(tmp_path):
    _, first = _direction_markdown(tmp_path)
    _, second = _direction_markdown(tmp_path)
    assert first == second


def test_markdown_contains_intersection_and_excluded_sections(tmp_path):
    out = tmp_path / "out.json"
    md = tmp_path / "out.md"
    _run_cli("--fixture", str(FIXTURES / "scan.json"),
             "--output", str(out), "--markdown", str(md))
    text = md.read_text(encoding="utf-8")
    assert "双榜交集" in text
    result = json.loads(out.read_text(encoding="utf-8"))
    for item in result["intersection"][:3]:
        assert item["name"] in text


def test_report_renders_missing_values_as_dash():
    document = {
        "industries": [
            {
                "code": "881101.TI", "name": "空行业", "level": 1,
                "amountTopCount": 0, "turnoverTopCount": 0,
                "memberCount": 0, "hitRateAmount": None, "hitRateTurnover": None,
                "quadrant": "冷门",
            }
        ],
        "intersection": [],
        "rankings": {},
        "quality": {"status": "ok", "degradations": [], "warnings": []},
    }
    text = report.render(document)
    assert "—" in text
    assert "本次无交集" in text


def test_report_is_pure_render_of_json(tmp_path):
    """Rendering the same document twice yields identical text."""

    out = tmp_path / "out.json"
    _run_cli("--fixture", str(FIXTURES / "scan.json"), "--output", str(out))
    document = json.loads(out.read_text(encoding="utf-8"))
    assert report.render(document) == report.render(document)


def test_level_both_outputs_two_levels(tmp_path):
    out = tmp_path / "out.json"
    _run_cli("--fixture", str(FIXTURES / "scan.json"), "--level", "both",
             "--output", str(out))
    result = json.loads(out.read_text(encoding="utf-8"))
    levels = {i["level"] for i in result["industries"]}
    assert 1 in levels


def test_fixture_mode_makes_no_network_calls(monkeypatch, tmp_path):
    """The fixture path must not touch urllib or the CLI.

    Runs in-process so the patched functions are the ones the pipeline would
    actually reach; a subprocess would inherit an unpatched interpreter.
    """

    def explode(*args, **kwargs):
        raise AssertionError("fixture 模式不应发起网络请求")

    monkeypatch.setattr(sina_client.urllib.request, "urlopen", explode)
    monkeypatch.setattr(fuyao_client.subprocess, "run", explode)
    out = tmp_path / "out.json"
    code = scan_pipeline.main(
        ["--fixture", str(FIXTURES / "scan.json"), "--output", str(out)]
    )
    assert code == 0
    assert out.is_file()


def test_quality_helpers_track_status():
    quality = scan_pipeline.Quality()
    assert quality.status == "ok"
    quality.degrade("某源失败")
    assert quality.status == "degraded"
    quality.insufficient("整段缺失")
    assert quality.status == "insufficient"
    payload = quality.as_dict()
    assert len(payload["degradations"]) == 2


def test_quality_warnings_do_not_change_status():
    quality = scan_pipeline.Quality()
    quality.warn("提示")
    assert quality.status == "ok"
    assert quality.as_dict()["warnings"] == ["提示"]


def test_original_rank_is_recorded_when_filtering():
    """rankIfUnfiltered must be the pre-filter position, not null."""

    rows = [_row("600000"), _row("920309"), _row("600002")]
    symbols = {
        "600000.SH": fuyao_client.SymbolInfo("600000.SH", "老股", date(2015, 1, 1)),
        "920309.SH": fuyao_client.SymbolInfo("920309.SH", "次新", date(2026, 11, 17)),
        "600002.SH": fuyao_client.SymbolInfo("600002.SH", "老股", date(2015, 1, 1)),
    }
    kept, excluded, _ = fuyao_client.filter_by_listing_age(
        rows, symbols, date(2026, 11, 19), min_listing_days=250
    )
    assert [r.thscode for r in kept] == ["600000.SH", "600002.SH"]
    assert excluded[0]["rankIfUnfiltered"] == 2


# --------------------------------------------------------------------------
# degradation matrix
# --------------------------------------------------------------------------


def _live_inputs(monkeypatch, *, amount_fail=False, turnover_fail=False,
                 full_fail=False, symbols_fail=False, symbols_undated=False,
                 bars_missing=0,
                 boards_cached=None, boards_ok=True,
                 board_snapshot_fail=False, market_snapshot_fail=False,
                 now="2026-11-19T10:30:00+08:00"):
    """Drive collect_live with every external call stubbed."""

    quality = scan_pipeline.Quality()
    rows = [
        sina_client.RankRow(f"6000{i:02d}", f"sh6000{i:02d}", f"样本{i}", 1e9, 20.0 - i, 10.0, 100.0, 1.0)
        for i in range(10)
    ]

    def fake_pool(key, pool_size=400, **kwargs):
        fail = amount_fail if key == sina_client.RANK_BY_AMOUNT else turnover_fail
        if fail:
            raise sina_client.SinaError("stub failure")
        return list(rows)

    def fake_full(**kwargs):
        if full_fail:
            raise sina_client.SinaError("stub full failure")
        return list(rows)

    def fake_symbols(self):
        if symbols_fail:
            raise fuyao_client.FuyaoError("stub symbols failure")
        if symbols_undated:
            # 2026-11-20 upstream regression: rows present, list_date absent.
            return [fuyao_client.SymbolInfo(r.thscode, r.name, None) for r in rows]
        return [fuyao_client.SymbolInfo(r.thscode, r.name, date(2015, 1, 1)) for r in rows]

    def fake_klines(symbols, **kwargs):
        missing = list(symbols)[:bars_missing]
        return {s: [{"day": "2026-11-19 09:35:00", "volume": 1}] for s in symbols if s not in missing}, missing

    monkeypatch.setattr(sina_client, "fetch_sorted_pool", fake_pool)
    monkeypatch.setattr(sina_client, "fetch_full_snapshot", fake_full)
    monkeypatch.setattr(sina_client, "fetch_klines", fake_klines)
    monkeypatch.setattr(fuyao_client.FuyaoClient, "list_symbols", fake_symbols)

    def fake_index_snapshot(self, codes):
        if board_snapshot_fail:
            raise fuyao_client.FuyaoError("stub board snapshot failure")
        return {code: -6.85 for code in codes}

    def fake_market_snapshot(self, **kwargs):
        if market_snapshot_fail:
            raise fuyao_client.FuyaoError("stub market snapshot failure")
        changes = {r.thscode: r.change_pct for r in rows}
        return fuyao_client.MarketSnapshot(
            changes=changes,
            volumes={r.thscode: r.amount for r in rows},
            source="fuyao-market-snapshot",
            total=len(rows),
        )

    monkeypatch.setattr(fuyao_client.FuyaoClient, "index_snapshot", fake_index_snapshot)
    monkeypatch.setattr(fuyao_client.FuyaoClient, "market_snapshot", fake_market_snapshot)

    if boards_cached is not None:
        monkeypatch.setattr(industry_map, "load_boards", lambda *a, **k: boards_cached)
    elif boards_ok:
        healthy = ([industry_map.IndustryBoard("881101.TI", "半导体", 1, ("600000.SH",))],
                   date(2026, 11, 19))
        monkeypatch.setattr(industry_map, "load_boards", lambda *a, **k: healthy)
    else:
        monkeypatch.setattr(industry_map, "load_boards", lambda *a, **k: None)
        monkeypatch.setattr(scan_pipeline, "_fetch_boards", lambda *a, **k: [])

    fixed = datetime.fromisoformat(now)
    inputs = scan_pipeline.collect_live(
        now=fixed,
        candidate_pool=50,
        min_listing_days=250,
        level=1,
        top=5,
        quality=quality,
        cache_root=None,
        enable_bars=True,
        enable_history=False,
    )
    return inputs, quality


def test_degradation_single_ranking_failure(monkeypatch):
    inputs, quality = _live_inputs(monkeypatch, turnover_fail=True)
    assert quality.status == "degraded"
    assert any("换手率榜排序接口失败" in d for d in quality.degradations)
    assert inputs.amount_rows, "成交额榜应仍然完整"


def test_degradation_both_rankings_fall_back_to_full_snapshot(monkeypatch):
    inputs, quality = _live_inputs(monkeypatch, amount_fail=True, turnover_fail=True)
    assert quality.status == "degraded"
    assert any("全量快照" in d for d in quality.degradations)
    assert inputs.amount_rows and inputs.turnover_rows


def test_degradation_full_snapshot_failure_is_insufficient(monkeypatch):
    inputs, quality = _live_inputs(
        monkeypatch, amount_fail=True, turnover_fail=True, full_fail=True,
        boards_ok=False,
    )
    assert quality.status == "insufficient"
    assert inputs.amount_rows == []


def test_board_index_failure_keeps_hit_and_breadth_evidence(monkeypatch):
    inputs, quality = _live_inputs(monkeypatch, board_snapshot_fail=True)
    assert quality.status == "degraded"
    assert any("板块指数快照不可用" in d for d in quality.degradations)
    assert inputs.board_changes == {}
    # The market map still arrived, so width and relative stay available.
    assert inputs.market and inputs.market.changes

    result = scan_pipeline.build_result(
        inputs, top=5, candidate_pool=50, min_listing_days=250,
        level=1, top_sectors=5, quality=quality,
    )
    for item in result["industries"]:
        assert item["boardChangePct"] is None
        assert item["boardDirection"] is None
        assert item["hitCount"] >= 0
        assert item["memberBreadthStatus"] in {"ok", "insufficient"}


def test_market_failure_falls_back_to_sina_snapshot(monkeypatch):
    inputs, quality = _live_inputs(monkeypatch, market_snapshot_fail=True)
    assert inputs.market is not None
    assert inputs.market.source == "sina-full-snapshot"
    assert inputs.market.changes
    assert any("新浪全量快照兜底" in d for d in quality.degradations)


def test_both_direction_sources_failing_degrades_without_aborting(monkeypatch):
    """Losing every direction source must still yield a complete scan."""

    inputs, quality = _live_inputs(
        monkeypatch, board_snapshot_fail=True, market_snapshot_fail=True,
        full_fail=True,
    )
    assert quality.status in {"degraded", "insufficient"}
    # Rankings still arrive from the sorted-pool path.
    assert inputs.amount_rows and inputs.turnover_rows
    assert inputs.market is not None
    assert inputs.market.source == "unavailable"

    result = scan_pipeline.build_result(
        inputs, top=5, candidate_pool=50, min_listing_days=250,
        level=1, top_sectors=5, quality=quality,
    )
    assert result["direction"]["market"]["status"] == "insufficient"
    assert result["direction"]["market"]["medianChangePct"] is None
    # Absolute direction survives; nothing pretends to know the benchmark.
    assert result["rankings"]["byAmount"]
    for item in result["industries"]:
        assert item["relativeToMarketPct"] is None
        assert item["boardRelativeToMarketPct"] is None


def test_direction_degrades_independently_of_ranking_failures(monkeypatch):
    """A direction failure must not be reported as a ranking failure."""

    inputs, quality = _live_inputs(monkeypatch, board_snapshot_fail=True)
    assert not any("排序接口失败" in d for d in quality.degradations)


def test_degradation_symbols_failure_skips_filtering(monkeypatch):
    inputs, quality = _live_inputs(monkeypatch, symbols_fail=True)
    assert quality.status == "degraded"
    assert any("新股过滤降级" in d for d in quality.degradations)
    assert inputs.amount_rows, "上市日期缺失时不应让榜单为空"


def test_undated_symbol_field_wholesale_gap_fails_open(monkeypatch):
    """2026-11-20: every row had list_date null; that must not empty the run."""

    inputs, quality = _live_inputs(monkeypatch, symbols_undated=True)
    assert quality.status == "degraded"
    assert any("整体缺失" in d and "未执行新股过滤" in d for d in quality.degradations)
    assert inputs.amount_rows, "整体缺上市日期时榜单不得为空"
    assert inputs.turnover_rows, "换手率榜同样不得为空"
    # Nothing was excluded on age grounds, because age could not be measured.
    assert inputs.excluded_by_amount == []
    assert inputs.excluded_by_turnover == []


def test_undated_symbols_still_produce_a_full_result_document(monkeypatch):
    inputs, quality = _live_inputs(monkeypatch, symbols_undated=True)
    result = scan_pipeline.build_result(
        inputs, top=5, candidate_pool=50, min_listing_days=250,
        level=1, top_sectors=5, quality=quality,
    )
    assert result["quality"]["status"] == "degraded"
    assert result["rankings"]["byAmount"]
    assert any("整体缺失" in d for d in result["quality"]["degradations"])


def test_symbol_lookup_fails_open_only_when_every_date_is_absent():
    """A single undated stock keeps the old exclude-that-stock behaviour."""

    class PartiallyDated:
        def list_symbols(self):
            return [
                fuyao_client.SymbolInfo("600000.SH", "老股", date(2015, 1, 1)),
                fuyao_client.SymbolInfo("688845.SH", "缺日期", None),
            ]

    quality = scan_pipeline.Quality()
    symbols = scan_pipeline._symbol_lookup(PartiallyDated(), quality)
    assert set(symbols) == {"600000.SH", "688845.SH"}
    assert quality.status == "ok"
    assert quality.degradations == []


def test_symbol_lookup_fails_open_when_all_dates_absent():
    class WhollyUndated:
        def list_symbols(self):
            return [fuyao_client.SymbolInfo("600000.SH", "老股", None)]

    quality = scan_pipeline.Quality()
    assert scan_pipeline._symbol_lookup(WhollyUndated(), quality) == {}
    assert quality.status == "degraded"
    assert any("整体缺失" in d for d in quality.degradations)


def test_degradation_missing_bars_is_recorded(monkeypatch):
    inputs, quality = _live_inputs(monkeypatch, bars_missing=3)
    assert quality.status == "degraded"
    assert any("分时 K 线缺失" in d for d in quality.degradations)


def test_degradation_boards_unavailable_without_cache(monkeypatch):
    inputs, quality = _live_inputs(monkeypatch, boards_ok=False)
    assert quality.status == "insufficient"
    assert inputs.boards == []
    assert inputs.amount_rows, "行业段缺失不应清空榜单"


def test_degradation_boards_from_stale_cache_is_degraded(monkeypatch):
    boards = [industry_map.IndustryBoard("881101.TI", "半导体", 1, ("600000.SH",))]
    inputs, quality = _live_inputs(
        monkeypatch, boards_cached=(boards, date(2026, 11, 18))
    )
    assert quality.status == "degraded"
    assert any("缓存" in d for d in quality.degradations)
    assert inputs.boards, "有旧缓存时应继续产出行业段"


def test_degradation_matrix_preserves_other_sections(monkeypatch, tmp_path):
    """A single failing source must not blank the rest of the document."""

    inputs, quality = _live_inputs(monkeypatch, bars_missing=2)
    inputs.excluded_by_amount = []
    inputs.excluded_by_turnover = []
    result = scan_pipeline.build_result(
        inputs, top=5, candidate_pool=50, min_listing_days=250,
        level=1, top_sectors=5, quality=quality,
    )
    assert result["rankings"]["byAmount"]
    assert result["rankings"]["byTurnover"]
    assert result["quality"]["status"] == "degraded"
    json.dumps(result, ensure_ascii=False)


def test_all_sources_failing_exits_nonzero(tmp_path, monkeypatch):
    payload = {"now": "2026-11-19T10:30:00+08:00", "byAmount": [], "byTurnover": [], "boards": []}
    fixture = tmp_path / "empty.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    code = scan_pipeline.main(["--fixture", str(fixture)])
    assert code == 2


def test_settled_run_computes_percentile(tmp_path):
    fixture_payload = _fixture()
    fixture_payload["now"] = "2026-11-19T15:30:00+08:00"
    fixture_payload["history"] = {
        "600000.SH": [{"volume": 1000 + i} for i in range(80)]
    }
    fixture = tmp_path / "settled.json"
    fixture.write_text(json.dumps(fixture_payload, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.json"
    _run_cli("--fixture", str(fixture), "--output", str(out))
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["sessionState"] == "closed"
    assert result["percentile"]["status"] == "computed"


# --------------------------------------------------------------------------
# CLI contract for the board catalogue
# --------------------------------------------------------------------------


def test_fetch_boards_uses_index_catalog_command():
    """The catalogue subcommand is `index catalog`, not `index list`.

    A wrong name fails at runtime with CLI_UNKNOWN_COMMAND, which no pure
    function test catches; assert the exact argv here.
    """

    seen: list[list[str]] = []

    def runner(args):
        seen.append(list(args))
        if args[:2] == ["index", "catalog"]:
            payload = {"ok": True, "data": {"item": [
                {"thscode": "881101.TI", "name": "半导体"},
                {"thscode": "884101.TI", "name": "半导体二级"},
            ]}}
            return 0, json.dumps(payload), ""
        if args[:2] == ["index", "constituents"]:
            payload = {"ok": True, "data": {"item": [{"thscode": "600000.SH"}]}}
            return 0, json.dumps(payload), ""
        return 1, "", "unexpected"

    client = fuyao_client.FuyaoClient(runner=runner)
    boards = scan_pipeline._fetch_boards(client, 1)
    assert seen[0][:2] == ["index", "catalog"]
    assert [b.thscode for b in boards] == ["881101.TI"]
    assert boards[0].members == ("600000.SH",)


def test_fetch_boards_filters_by_level_prefix():
    def runner(args):
        if args[:2] == ["index", "catalog"]:
            payload = {"ok": True, "data": {"item": [
                {"thscode": "881101.TI", "name": "一级"},
                {"thscode": "884101.TI", "name": "二级"},
            ]}}
            return 0, json.dumps(payload), ""
        payload = {"ok": True, "data": {"item": []}}
        return 0, json.dumps(payload), ""

    client = fuyao_client.FuyaoClient(runner=runner)
    assert [b.thscode for b in scan_pipeline._fetch_boards(client, 1)] == ["881101.TI"]
    assert [b.thscode for b in scan_pipeline._fetch_boards(client, 2)] == ["884101.TI"]


def test_now_argument_warns_about_snapshot_freshness(monkeypatch, tmp_path):
    """`--now` labels the run; it cannot rewind the provider snapshot."""

    def fake_pool(key, pool_size=400, **kwargs):
        return [_row("600000")]

    def fake_symbols(self):
        return [fuyao_client.SymbolInfo("600000.SH", "样本", date(2015, 1, 1))]

    monkeypatch.setattr(sina_client, "fetch_sorted_pool", fake_pool)
    monkeypatch.setattr(sina_client, "fetch_klines", lambda s, **k: ({}, []))
    monkeypatch.setattr(fuyao_client.FuyaoClient, "list_symbols", fake_symbols)
    monkeypatch.setattr(industry_map, "load_boards", lambda *a, **k: (
        [industry_map.IndustryBoard("881101.TI", "半导体", 1, ("600000.SH",))],
        date(2026, 11, 19),
    ))

    out = tmp_path / "out.json"
    code = scan_pipeline.main(["--now", "2026-11-19T10:30:00+08:00", "--output", str(out)])
    assert code == 0
    warnings = json.loads(out.read_text(encoding="utf-8"))["quality"]["warnings"]
    assert any("不能回溯历史快照" in w for w in warnings)


def test_percentile_field_is_volume_not_percentage(tmp_path):
    """History carries volume only; the baseline must not claim to be a pct."""

    payload = _fixture()
    payload["now"] = "2026-11-19T15:30:00+08:00"
    payload["history"] = {"600000.SH": [{"volume": 4_000_000 + i * 1000} for i in range(80)]}
    fixture = tmp_path / "vol.json"
    fixture.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.json"
    _run_cli("--fixture", str(fixture), "--output", str(out))
    block = json.loads(out.read_text(encoding="utf-8"))["percentile"]
    entry = block["byCode"]["600000.SH"]
    assert "averageTurnoverPct" not in entry
    assert entry["baselineVolumeShares"] > 1000
    assert "amplification" in entry


def test_documented_keys_match_output(tmp_path):
    """Guard against SKILL.md drifting from the real JSON shape."""

    out = tmp_path / "out.json"
    _run_cli("--fixture", str(FIXTURES / "scan.json"), "--output", str(out))
    result = json.loads(out.read_text(encoding="utf-8"))
    for key in (
        "schemaVersion", "ruleVersion", "reportId", "generatedAt", "asOf",
        "sessionState", "elapsedBars", "dataCutoff", "earlySnapshot", "settled",
        "turnoverBasis", "filter", "rankings", "industries", "intersection",
        "percentile", "handoff", "quality", "disclaimer", "excluded",
        "direction", "directionSummary",
    ):
        assert key in result, f"输出缺字段 {key}"
    assert set(result["intersection"][0]) == {
        "code", "name", "amountRank", "turnoverRank", "industries",
        "changePct", "direction", "relativeToMarketPct",
    }
    assert set(result["industries"][0]) == {
        "code", "name", "level", "amountTopCount", "turnoverTopCount",
        "memberCount", "hitRateAmount", "hitRateTurnover", "quadrant",
        # direction layer (schemaVersion 1.1)
        "direction", "directionBasis", "tag", "boardChangePct", "boardDirection",
        "hitUpCount", "hitDownCount", "hitFlatCount", "hitSuspendedCount",
        "hitUnknownCount", "hitCount",
        "memberUpCount", "memberDownCount", "memberFlatCount",
        "memberSuspendedCount", "memberUnknownCount",
        "memberMedianChangePct", "memberCoverage",
        "memberBreadthStatus", "relativeToMarketPct", "boardRelativeToMarketPct",
    }
    assert set(result["direction"]["market"]) >= {
        "status", "source", "universe", "validCount", "suspendedCount",
        "upCount", "downCount", "flatCount", "medianChangePct",
    }
    assert set(result["rankings"]["byAmount"][0]) >= {
        "rank", "code", "name", "amountYi", "turnoverPct", "floatMvYi",
        "changePct", "direction", "relativeToMarketPct",
    }


# --------------------------------------------------------------------------
# report.render_answer (fixed session answer format)
# --------------------------------------------------------------------------


def _answer_markdown(tmp_path):
    out = tmp_path / "out.json"
    md = tmp_path / "out.md"
    answer = tmp_path / "answer.md"
    completed = _run_cli(
        "--fixture", str(FIXTURES / "direction.json"),
        "--output", str(out), "--markdown", str(md), "--answer", str(answer),
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(out.read_text(encoding="utf-8")), answer.read_text(encoding="utf-8")


def test_answer_heading_and_highlight_are_fixed(tmp_path):
    """The opening block is exactly one heading plus five bullets."""

    result, text = _answer_markdown(tmp_path)
    lines = text.splitlines()
    assert lines[0] == report.ANSWER_HEADING == "# 最活跃的行业"
    assert lines[1] == ""
    bullets = [line for line in lines[2:8] if line.startswith("- ")]
    assert len(bullets) == report.ANSWER_HIGHLIGHT_BULLETS
    for prefix in ("- 时点：", "- 全市场：", "- 最活跃行业：", "- 方向：", "- 双榜交集："):
        assert any(line.startswith(prefix) for line in bullets), prefix
    # The two dashboards are distinct objects: the answer is not the report.
    assert "# A 股活跃行业扫描" not in text
    assert result["reportId"] in text


def test_answer_sections_have_fixed_names_and_order(tmp_path):
    """Sections never get renamed, duplicated or reordered."""

    _, text = _answer_markdown(tmp_path)
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == [
        "## 一、行业活跃度与方向",
        "## 二、方向分组",
        "## 三、双榜交集",
        "## 四、扫描变化轨迹",
        "## 五、双榜明细",
        "## 六、数据质量",
    ]


def test_answer_is_deterministic_and_matches_cli(tmp_path):
    """Same JSON renders the same text; the file is the renderer's output."""

    result, text = _answer_markdown(tmp_path)
    assert report.render_answer(result) == report.render_answer(result)
    again = tmp_path / "again.md"
    again.write_text(report.render_answer(result), encoding="utf-8")
    body = text.split("\n- JSON：")[0]
    assert body == again.read_text(encoding="utf-8").rstrip()


def test_answer_uses_signed_change_percent():
    """A change always carries its sign; a rate never does."""

    document = {
        "industries": [
            {
                "code": "881121.TI", "name": "半导体", "level": 1,
                "amountTopCount": 4, "turnoverTopCount": 2, "memberCount": 5,
                "hitRateAmount": 0.8, "hitRateTurnover": 0.4, "quadrant": "真实活跃",
                "hitCount": 6, "hitUpCount": 1, "hitDownCount": 5,
                "boardChangePct": 1.2, "relativeToMarketPct": -2.5,
                "direction": "down", "tag": "真实活跃·上涨",
            }
        ],
        "rankings": {
            "byAmount": [
                {"rank": 1, "name": "A", "code": "600001.SH", "amountYi": 10.0,
                 "turnoverPct": 8.0, "floatMvYi": 10.0, "changePct": 1.5,
                 "direction": "up", "relativeToMarketPct": 2.5},
            ],
        },
        "intersection": [],
        "direction": {
            "market": {"medianChangePct": 1.92, "upCount": 4, "downCount": 1,
                       "flatCount": 0, "suspendedCount": 0},
            "flatEpsilon": 0.005, "minBreadthCoverage": 0.7,
            "basisNote": "已收盘",
        },
        "handoff": {"candidateThscodes": ["881121.TI"]},
        "quality": {"status": "ok", "degradations": [], "warnings": []},
    }
    text = report.render_answer(document)
    assert "+1.20%" in text      # board change keeps its plus
    assert "-2.50%" in text      # relative change keeps its minus
    assert "+1.92%" in text      # market median keeps its plus
    assert "8.00%" in text       # turnover is a rate: no sign
    assert "+8.00%" not in text


def test_skill_md_requires_verbatim_answer():
    """Guard the hard rule: sessions paste the file, they do not re-typeset."""

    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    section = text.split("## 回复格式（硬要求）", 1)[1].split("\n## ", 1)[0]
    assert "--answer" in section
    assert "逐字复制" in section
    assert "# 最活跃的行业" in section
    assert "## 备注" in section


# --------------------------------------------------------------------------
# history.py + 扫描变化轨迹
# --------------------------------------------------------------------------


def _doc(at: str, median: float, up: int, down: int, *, hits=4, board=-6.85):
    return {
        "reportId": f"ais-{at.replace(':', '').replace('-', '')}-00000000",
        "asOf": f"2026-11-24T{at}:00+08:00",
        "dataCutoff": f"2026-11-24T{at}:00+08:00",
        "sessionState": "intraday",
        "elapsedBars": 8,
        "quality": {"status": "ok", "degradations": [], "warnings": []},
        "direction": {
            "market": {"medianChangePct": median, "upCount": up, "downCount": down,
                       "flatCount": 0, "suspendedCount": 0},
        },
        "directionSummary": {
            "byAmount": {"up": 45, "down": 5},
            "byTurnover": {"up": 40, "down": 10},
        },
        "industries": [
            {"code": "881121.TI", "name": "半导体", "level": 1,
             "amountTopCount": hits, "turnoverTopCount": 4, "hitCount": hits + 4,
             "boardChangePct": board, "relativeToMarketPct": 2.0,
             "direction": "up", "tag": "真实活跃·上涨"},
        ],
        "intersection": [
            {"code": "688836.SH", "name": "宇树科技", "amountRank": 1,
             "turnoverRank": 2, "industries": ["自动化设备"], "changePct": 4.0,
             "direction": "up", "relativeToMarketPct": 2.0},
        ],
        "handoff": {"candidateThscodes": ["881121.TI"]},
        "rankings": {},
    }


def test_history_snapshot_keeps_only_what_a_trajectory_needs():
    row = history.snapshot(_doc("10:00", 1.5, 4000, 900))
    assert row["market"]["medianChangePct"] == 1.5
    assert row["industries"][0]["amountTopCount"] == 4
    assert row["intersection"]["count"] == 1
    assert "rankings" not in row


def test_history_append_is_idempotent_per_report_id(tmp_path):
    first = _doc("10:00", 1.5, 4000, 900)
    history.append_run(tmp_path, first)
    history.append_run(tmp_path, first)
    rows = history.load_recent(tmp_path, first["asOf"])
    assert len(rows) == 1


def test_history_load_recent_excludes_the_current_run(tmp_path):
    first = _doc("10:00", 1.5, 4000, 900)
    second = _doc("10:30", 1.2, 3900, 1000)
    history.append_run(tmp_path, first)
    history.append_run(tmp_path, second)
    rows = history.load_recent(tmp_path, second["asOf"],
                               exclude_report_id=second["reportId"])
    assert [row["reportId"] for row in rows] == [first["reportId"]]


def test_history_highlight_reports_only_moves_above_threshold():
    before = history.snapshot(_doc("10:00", 1.5, 4000, 900))
    same = history.snapshot(_doc("10:30", 1.6, 4020, 900))
    moved = history.snapshot(_doc("11:00", 0.4, 3000, 1800, hits=6, board=-3.0))
    assert history.highlight_changes(same, before, top_codes=["881121.TI"]) == []
    changes = history.highlight_changes(moved, before, top_codes=["881121.TI"])
    text = "\n".join(changes)
    assert "全市场中位" in text
    assert "上涨家数" in text
    assert "半导体 成交额榜命中" in text
    assert "半导体 板块" in text


def test_history_highlight_names_intersection_changes():
    before = history.snapshot(_doc("10:00", 1.5, 4000, 900))
    after_doc = _doc("10:30", 1.5, 4000, 900)
    after_doc["intersection"] = []
    after = history.snapshot(after_doc)
    text = "\n".join(history.highlight_changes(after, before))
    assert "双榜交集 1 → 0 只" in text
    assert "掉出 宇树科技" in text


def test_trajectory_section_renders_first_run_placeholder():
    text = report.render_answer(_doc("10:00", 1.5, 4000, 900))
    assert "## 四、扫描变化轨迹" in text
    assert "本次为当日首次记录" in text


def test_trajectory_section_renders_row_per_run(tmp_path):
    first = _doc("10:00", 1.5, 4000, 900)
    second = _doc("10:30", 0.6, 3200, 1500, hits=6, board=-4.0)
    history.append_run(tmp_path, first)
    earlier = history.load_recent(tmp_path, second["asOf"])
    text = report.render_answer(second, history=earlier)
    block = text.split("## 四、扫描变化轨迹")[1].split("## 五、")[0]
    assert "| 时刻 | bar |" in block
    assert "10:00" in block and "10:30" in block
    assert "关键变化（相对上一次扫描）" in block
    assert "全市场中位 +1.50% → +0.60%" in block


def test_cli_history_dir_accumulates_and_is_isolated_from_cache(tmp_path):
    history_dir = tmp_path / "hist"
    first = tmp_path / "first.json"
    payload = _fixture("direction.json")
    first.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    answer_one = tmp_path / "a1.md"
    completed = _run_cli("--fixture", str(first), "--history-dir", str(history_dir),
                         "--output", str(tmp_path / "o1.json"), "--answer", str(answer_one))
    assert completed.returncode == 0, completed.stderr
    assert "本次为当日首次记录" in answer_one.read_text(encoding="utf-8")

    payload["now"] = "2026-11-20T16:00:00+08:00"
    payload["boardChanges"]["881121.TI"] = -3.0
    second = tmp_path / "second.json"
    second.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    answer_two = tmp_path / "a2.md"
    completed = _run_cli("--fixture", str(second), "--history-dir", str(history_dir),
                         "--output", str(tmp_path / "o2.json"), "--answer", str(answer_two))
    assert completed.returncode == 0, completed.stderr
    text = answer_two.read_text(encoding="utf-8")
    assert "本次为当日首次记录" not in text
    assert "关键变化（相对上一次扫描）" in text
    assert sorted(p.name for p in history_dir.iterdir()) == ["2026-11-20.jsonl"]


def test_history_store_is_off_for_fixtures_and_on_for_live_runs():
    """A replay must not become the next live run's baseline."""

    fixture = scan_pipeline.parse_args(["--fixture", "x.json"])
    assert scan_pipeline._history_root(fixture) is None

    live = scan_pipeline.parse_args([])
    assert scan_pipeline._history_root(live) == scan_pipeline.CACHE_ROOT / "history"

    explicit = scan_pipeline.parse_args(["--fixture", "x.json", "--history-dir", "/tmp/h"])
    assert str(scan_pipeline._history_root(explicit)) == "/tmp/h"

    disabled = scan_pipeline.parse_args(["--no-history-store"])
    assert scan_pipeline._history_root(disabled) is None
