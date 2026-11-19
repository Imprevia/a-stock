"""Offline tests for the QTS-04 STEP 2 theme-layer skill."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / ".agents" / "skills" / "a-stock-qts04-theme-layer"
CORE = REPO / ".agents" / "skills" / "qts04-core" / "scripts"
FIXTURES = Path(__file__).parent / "fixtures" / "a_stock_qts04_theme_layer"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(SKILL / "scripts"))

import theme_check_report as check_report  # noqa: E402
import theme_report as report  # noqa: E402
import theming  # noqa: E402
import theme_pipeline  # noqa: E402
from qts04 import check as core_check  # noqa: E402
from qts04.predicate import evaluate  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 11, 13, 16, 0, tzinfo=SHANGHAI)
AS_OF = date(2026, 11, 13)


def run(fixture: str = "strong.json", **kwargs):
    return theme_pipeline.run_pipeline(
        as_of=AS_OF,
        fixture=FIXTURES / fixture,
        now=NOW,
        use_cache=kwargs.pop("use_cache", False),
        **kwargs,
    )


def test_token_split_handles_fullwidth_plus_and_dedupes() -> None:
    assert theming.split_reason("短剧游戏＋文化传媒+短剧游戏") == ["短剧游戏", "文化传媒"]
    assert theming.split_reason("AI短剧（试点）+影视院线") == ["AI短剧", "影视院线"]
    assert theming.split_reason("") == []


def test_shared_tokens_count_only_inside_members() -> None:
    rows = [
        {"thscode": "000001.SZ", "reason": "短剧游戏+文化传媒"},
        {"thscode": "000002.SZ", "reason": "短剧游戏"},
    ]
    shared = theming.build_shared_tokens(rows)
    assert shared[0] == {"token": "短剧游戏", "holders": ["000001.SZ", "000002.SZ"], "count": 2}
    assert all(item["token"] != "文化传媒" for item in shared)


def test_single_holder_never_becomes_shared() -> None:
    rows = [{"thscode": "000001.SZ", "reason": "独家题材"}]
    assert theming.build_shared_tokens(rows) == []


def test_stop_tokens_and_attribute_tokens_are_excluded() -> None:
    rows = [
        {"thscode": "000001.SZ", "reason": "年报增长+股份回购+短剧游戏"},
        {"thscode": "000002.SZ", "reason": "年报增长+股份回购+短剧游戏"},
    ]
    assert [item["token"] for item in theming.build_shared_tokens(rows)] == ["短剧游戏"]
    assert theming.is_stop_token("股份回购")
    assert theming.detect_attribute_tokens({"跨概念": {"a", "b", "c", "d"}}) == {"跨概念"}


def test_lift_formula_matches_measured_2026_11_13() -> None:
    value = theming.compute_lift(7, 100, 38, 5400)
    assert value == pytest.approx(9.947368, rel=1e-5)
    assert theming.compute_lift(3, 189, 38, 5400) == pytest.approx(2.2556, rel=1e-3)
    assert theming.compute_lift(10, 1068, 38, 5400) == pytest.approx(1.3306, rel=1e-3)
    assert theming.compute_lift(0, 100, 38, 5400) == 0.0


def test_tier_gates_reproduce_the_measured_table() -> None:
    assert theming.classify_tier(score=52.5, lift=9.9474, shared_count=3, ladder_depth=1, observed=7)[0] == "core"
    assert theming.classify_tier(score=37.5, lift=2.2556, shared_count=3, ladder_depth=2, observed=3)[0] == "diffuse"
    assert theming.classify_tier(score=46.9, lift=10.3, shared_count=0, ladder_depth=1, observed=4)[0] == "event"
    assert theming.classify_tier(score=38.8, lift=1.3306, shared_count=1, ladder_depth=3, observed=10)[0] == "pseudo"
    assert theming.classify_tier(score=52.5, lift=0.8, shared_count=3, ladder_depth=3, observed=10)[0] == "pseudo"


def test_strong_fixture_outputs_core_and_contract_fields() -> None:
    result = run()
    assert result["schemaVersion"] == "1.0"
    assert result["step"] == "STEP 2"
    assert result["asOf"] == "2026-11-13"
    assert result["status"] == "ok"
    assert result["noCoreTheme"] is False
    assert result["themes"][0]["name"] == "短剧游戏"
    assert result["themes"][0]["tier"] == "core"
    assert result["themes"][0]["lift"] == pytest.approx(9.9474, rel=1e-3)
    assert result["themes"][0]["catalyst"]["label"] == "partial"
    assert result["catalystPolicy"]["confirmedAvailable"] is False
    assert result["quality"]["pointInTime"] is False
    assert result["quality"]["backtestGrade"] == "D"
    assert result["quality"]["limitUpCrossCheck"]["consistent"] is True
    assert result["config"]["lift"]["coreThreshold"] == 3.0
    assert result["disclaimer"]


def test_theme_includes_metrics_members_and_predicates() -> None:
    theme = run()["themes"][0]
    assert len(theme["metrics"]) == 6
    assert theme["members"]["membershipGap"]["basis"] in {"exact", "estimated-from-sample"}
    assert -1.0 <= theme["members"]["medianChange"] <= 1.0
    assert 0.0 <= theme["members"]["advanceRatio"] <= 1.0
    assert theme["members"]["sharedTokens"][0]["token"] == "短剧游戏"
    assert theme["confirmation"]["all"]
    assert theme["invalidation"]["all"]
    assert theme["concept"]["barsObservations"] >= 30


def test_weak_fixture_outputs_no_core_theme() -> None:
    result = run("weak.json")
    assert result["noCoreTheme"] is True
    assert all(theme["tier"] != "core" for theme in result["themes"])
    assert result["noCoreReasons"]
    assert [theme["tier"] for theme in result["themes"]] == ["diffuse", "event", "pseudo"]


def test_missing_members_are_skipped_not_fabricated() -> None:
    result = run("missing-members.json")
    assert all(theme["name"] != "空成员概念" for theme in result["themes"])


def test_missing_benchmark_is_insufficient() -> None:
    result = run("missing-benchmark.json")
    assert result["status"] == "insufficient"


def test_no_core_reasons_empty_when_core_exists() -> None:
    assert run()["noCoreReasons"] == []


def test_catalyst_four_levels_and_confirmed_unreachable() -> None:
    shared = [{"token": "短剧游戏", "holders": ["000001.SZ", "000002.SZ"], "count": 2}]
    unknown = theming.build_catalyst(
        shared_tokens=[], anomalies=[], member_codes=[], as_of=AS_OF
    )
    speculative = theming.build_catalyst(
        shared_tokens=shared, anomalies=[], member_codes=["000001.SZ", "000002.SZ"], as_of=AS_OF
    )
    partial = theming.build_catalyst(
        shared_tokens=shared,
        anomalies=[
            {"thscode": "000001", "content": "短剧游戏异动", "keyWords": ["短剧游戏"]},
        ],
        member_codes=["000001.SZ", "000002.SZ"],
        as_of=AS_OF,
    )
    assert unknown["label"] == "unknown"
    assert speculative["label"] == "speculative"
    assert partial["label"] == "partial"
    assert theming.confirmed_policy()["confirmedAvailable"] is False


def test_predicate_evaluates_next_session_or_unknown() -> None:
    theme = run()["themes"][0]
    confirmation = theme["confirmation"]
    threshold = confirmation["all"][0]["value"]
    turnover = confirmation["all"][1]["value"]
    met = evaluate(
        confirmation,
        [{"date_ms": 1763049600000, "close_price": threshold + 1, "turnover": turnover + 1}],
    )
    unmet = evaluate(
        confirmation,
        [{"date_ms": 1763049600000, "close_price": threshold - 1, "turnover": turnover + 1}],
    )
    assert met == "met"
    assert unmet == "unmet"
    assert evaluate(confirmation, []) == "unknown"


def test_report_id_is_stable_and_config_sensitive(monkeypatch) -> None:
    first = run()
    second = run()
    assert first["reportId"] == second["reportId"]
    assert first["themes"] == second["themes"]

    monkeypatch.setattr(theme_pipeline, "CORE_LIFT", 3.1)
    monkeypatch.setattr(theming, "CORE_LIFT", 3.1)
    changed = run()
    assert changed["reportId"] != first["reportId"]


def test_step1_consumption_attaches_direction_overlap() -> None:
    result = run(step1=FIXTURES / "step1.json")
    assert result["input"]["step1ReportId"] == "abc123def4567890"
    assert result["input"]["step1"]["reportId"] == "abc123def4567890"
    directed = [theme for theme in result["themes"] if theme["direction"]]
    assert directed
    assert 0.0 < directed[0]["direction"]["overlapJaccard"] <= 1.0


def test_step1_missing_schema_is_rejected() -> None:
    with pytest.raises(ValueError, match="schemaVersion"):
        run(step1=FIXTURES / "step1-missing-schema.json")


def test_standalone_and_chained_results_are_structurally_equivalent() -> None:
    standalone = run()
    chained = run(step1=FIXTURES / "step1.json")
    stripped = [{key: value for key, value in theme.items() if key != "direction"} for theme in chained["themes"]]
    standalone_stripped = [
        {key: value for key, value in theme.items() if key != "direction"}
        for theme in standalone["themes"]
    ]
    assert standalone_stripped == stripped
    assert standalone["config"] == chained["config"]
    assert standalone["noCoreTheme"] == chained["noCoreTheme"]


def test_skeleton_passes_checker_and_tampered_tier_fails() -> None:
    result = run()
    article = report.render_markdown(result)
    verdict = check_report.validate(result, article)
    assert verdict["status"] == "PASS", verdict["issues"]

    tampered = article.replace("| 固态电池 | 伪题材 |", "| 固态电池 | 核心题材 |")
    bad = check_report.validate(result, tampered)
    assert bad["status"] == "FAIL"
    assert any(issue["check"] == "labelProvenance" for issue in bad["issues"])


def test_weak_skeleton_passes_and_no_core_claim_fails() -> None:
    result = run("weak.json")
    article = report.render_markdown(result)
    assert check_report.validate(result, article)["status"] == "PASS"
    tampered = article.replace("今日**没有核心题材**", "今日**核心题材**：算力租赁")
    bad = check_report.validate(result, tampered)
    assert bad["status"] == "FAIL"
    assert any(issue["check"] == "labelProvenance" for issue in bad["issues"])


def test_label_check_is_optional_for_step1_compatibility() -> None:
    result = run()
    article = report.render_markdown(result).replace("| 固态电池 | 伪题材 |", "| 固态电池 | 核心题材 |")
    assert core_check.validate(result, article)["status"] == "PASS"
    assert check_report.validate(result, article)["status"] == "FAIL"


def test_skeleton_has_no_forbidden_wording() -> None:
    article = report.render_markdown(run())
    for word in core_check.FORBIDDEN_WORDS:
        assert word not in article


def test_date_validation_rejects_future_and_pre_settlement() -> None:
    with pytest.raises(theme_pipeline.FuyaoInsufficient):
        theme_pipeline.resolve_as_of("2026-11-14", now=NOW)
    with pytest.raises(theme_pipeline.FuyaoInsufficient):
        theme_pipeline.resolve_as_of(
            "2026-11-13", now=datetime(2026, 11, 13, 14, 0, tzinfo=SHANGHAI)
        )


def test_non_trading_fixture_is_rejected() -> None:
    with pytest.raises(theme_pipeline.FuyaoInsufficient, match="交易日"):
        run("non-trading.json")


def test_fixture_run_never_needs_credentials(monkeypatch) -> None:
    monkeypatch.delenv("FUYAO_API_KEY", raising=False)
    monkeypatch.delenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", raising=False)
    result = run()
    assert result["source"] == "fixture"
    assert result["status"] == "ok"


def test_point_in_time_snapshot_is_deterministic(tmp_path: Path) -> None:
    first = theme_pipeline.run_pipeline(
        as_of=AS_OF,
        fixture=FIXTURES / "strong.json",
        cache_dir=tmp_path,
        now=NOW,
        use_cache=True,
    )
    path = tmp_path / "point-in-time" / "2026-11-13.json"
    assert path.exists()
    before = path.read_text(encoding="utf-8")
    second = theme_pipeline.run_pipeline(
        as_of=AS_OF,
        fixture=FIXTURES / "strong.json",
        cache_dir=tmp_path,
        now=NOW,
        use_cache=True,
    )
    assert first["reportId"] == second["reportId"]
    assert path.read_text(encoding="utf-8") == before
    payload = json.loads(before)
    assert payload["asOf"] == "2026-11-13"
    assert payload["themes"][0]["tokens"]


def test_unmapped_tokens_are_reported() -> None:
    result = run()
    assert result["unmappedTokens"]
    assert all(row["occurrences"] >= 1 for row in result["unmappedTokens"])


class FakeClient:
    """Minimal in-process client proving the live path and cache behavior."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.credential_source = "fake"
        self.members = [f"{100 + i:06d}.SZ" for i in range(1, 101)]
        self.rows = [
            {
                "thscode": self.members[i],
                "name": "标的",
                "reason": "短剧游戏+文化传媒" if i < 5 else "短剧游戏",
                "continueDay": 3 if i == 0 else 1,
            }
            for i in range(7)
        ]
        self.rows += [
            {"thscode": f"9{i:05d}.SZ", "name": "其他标的", "reason": "年报增长+股份回购", "continueDay": 1}
            for i in range(31)
        ]

    def check_prerequisites(self):
        return {"ready": True}

    def market_calendar(self):
        return ["20261113"]

    def list_concepts(self):
        self.calls.append("catalog")
        return [{"thscode": "886060.TI", "name": "短剧游戏"}]

    def index_snapshot(self, codes):
        self.calls.append("snapshot")
        return [{"thscode": "886060.TI", "priceChangePct": 3.0, "turnover": 2e9}]

    def limit_up_pool(self, as_of):
        self.calls.append("pool")
        return self.rows

    def limit_up_statistics(self, as_of):
        self.calls.append("stats")
        return {"tradeDate": "2026-11-13", "limitUpStockCount": 38, "boards": []}

    def anomaly_analysis(self, as_of):
        self.calls.append("anomaly")
        return [
            {
                "thscode": self.members[0],
                "tagName": "短剧游戏",
                "keyWords": ["短剧游戏"],
                "content": "短剧游戏活跃",
                "url": "",
            }
        ]

    def index_history_batch(self, codes, start, end):
        self.calls.append("index")
        from qts04.model import Bar
        from datetime import timedelta

        days = []
        cursor = end
        while len(days) < 40:
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor -= timedelta(days=1)
        days.reverse()
        return {
            code: [Bar(d, 1000 + i * 5 if code != "000001.SH" else 4000 + i) for i, d in enumerate(days)]
            for code in codes
        }

    def constituents(self, code):
        self.calls.append("constituents")
        return [{"thscode": member, "name": "标的"} for member in self.members]

    def stock_history_batch(self, codes, start, end):
        self.calls.append("stock")
        from qts04.model import Bar
        from datetime import timedelta

        return {
            code: [
                Bar(end - timedelta(days=1), 10.0, 1e6),
                Bar(end, 10.3, 1e6),
            ]
            for code in codes
        }


def test_live_path_uses_snapshot_and_reuses_cache(tmp_path: Path) -> None:
    client = FakeClient()
    first = theme_pipeline.run_pipeline(
        as_of=AS_OF,
        client=client,
        cache_dir=tmp_path,
        now=NOW,
        use_cache=True,
    )
    assert first["input"]["candidateBasis"] == "reason-token+snapshot"
    assert first["quality"]["providerCalls"] > 0
    assert first["themes"][0]["name"] == "短剧游戏"
    calls_after_first = len(client.calls)

    second = theme_pipeline.run_pipeline(
        as_of=AS_OF,
        client=client,
        cache_dir=tmp_path,
        now=NOW,
        use_cache=True,
    )
    assert len(client.calls) == calls_after_first
    assert second["reportId"] == first["reportId"]
    assert second["quality"]["providerCalls"] == 0


def test_wide_concept_is_pseudo_despite_many_limit_ups() -> None:
    result = run("wide-pseudo.json")
    theme = result["themes"][0]
    assert theme["name"] == "新能源汽车"
    assert theme["observed"] == 10
    assert theme["lift"] == pytest.approx(1.3306, rel=1e-3)
    assert theme["tier"] == "pseudo"
    assert result["noCoreTheme"] is True


class MissingSnapshotClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.catalog = [
            {"thscode": f"8860{i:02d}.TI", "name": f"概念{i}"}
            for i in range(10)
        ]

    def list_concepts(self):
        self.calls.append("catalog")
        return self.catalog

    def index_snapshot(self, codes):
        self.calls.append("snapshot")
        return []


def test_snapshot_missing_rows_make_result_insufficient(tmp_path: Path) -> None:
    result = theme_pipeline.run_pipeline(
        as_of=AS_OF,
        client=MissingSnapshotClient(),
        cache_dir=tmp_path,
        now=NOW,
        use_cache=True,
    )
    assert result["status"] == "insufficient"
    assert any("概念快照缺行" in warning for warning in result["quality"]["warnings"])


def test_missing_all_price_bars_yields_null_score_and_insufficient() -> None:
    result = run("missing-bars.json")
    assert result["status"] == "insufficient"
    assert result["themes"]
    assert all(theme["score"] is None for theme in result["themes"])
    assert all(theme["status"] == "insufficient" for theme in result["themes"])


def test_concept_name_token_is_never_treated_as_attribute() -> None:
    """A token equal to the concept name defines the theme, not an attribute.

    Regression: on 2026-11-18 ``算力租赁`` appeared in 4+ concepts' limit-up
    members, so the global attribute detector blocked it and the pipeline
    reported a false ``noCoreTheme``.
    """

    from datetime import date as _date

    concept = {
        "thscode": "886050.TI",
        "name": "算力租赁",
        "members": [f"00010{i}.SZ" for i in range(1, 6)],
        "bars": [],
    }
    limit_ups = [
        {"thscode": f"00010{i}.SZ", "reason": "算力租赁+推理算力", "continueDay": 2}
        for i in range(1, 4)
    ]
    theme = theming.build_theme(
        as_of=_date(2026, 11, 18),
        concept=concept,
        limit_ups=limit_ups,
        limit_up_tokens=theming.tokenize_limit_ups(limit_ups),
        benchmark_bars=[],
        member_changes={},
        anomalies=[],
        limit_up_count=len(limit_ups),
        universe=5400,
        attribute_tokens={"算力租赁", "推理算力", "数据中心"},
    )
    assert [item["token"] for item in theme["members"]["sharedTokens"]] == ["算力租赁"]
    # The genuinely cross-concept token stays blocked.
    assert all(item["token"] != "推理算力" for item in theme["members"]["sharedTokens"])
