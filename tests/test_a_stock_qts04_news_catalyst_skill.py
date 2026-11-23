"""Offline tests for the QTS-04 STEP 2.5 news-catalyst skill."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / ".agents" / "skills" / "a-stock-qts04-news-catalyst"
CORE = REPO / ".agents" / "skills" / "qts04-core" / "scripts"
FIXTURES = Path(__file__).parent / "fixtures" / "a_stock_qts04_news_catalyst"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(SKILL / "scripts"))

from qts04.client import FuyaoClient, FuyaoInsufficient  # noqa: E402

import news  # noqa: E402


@pytest.fixture(autouse=True)
def _credential(monkeypatch):
    monkeypatch.setenv("FUYAO_API_KEY", "test-key")
    monkeypatch.delenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", raising=False)


def _completed(args, payload, code=0):
    return subprocess.CompletedProcess(args, code, stdout=json.dumps(payload), stderr="")


def _client(runner):
    return FuyaoClient(runner=runner, env_file=False)


def test_anomaly_range_passes_begin_and_end_dates():
    seen: list[list[str]] = []

    def runner(args, **kwargs):
        seen.append(list(args))
        return _completed(args, {"ok": True, "data": {"items": []}})

    assert _client(runner).anomaly_analysis_range(date(2026, 11, 9), date(2026, 11, 13)) == []
    assert len(seen) == 1
    assert "--begin-date" in seen[0] and "2026-11-09" in seen[0]
    assert "--end-date" in seen[0] and "2026-11-13" in seen[0]


def test_single_day_anomaly_delegates_once():
    seen: list[list[str]] = []

    def runner(args, **kwargs):
        seen.append(list(args))
        return _completed(args, {"ok": True, "data": {"items": []}})

    _client(runner).anomaly_analysis(date(2026, 11, 13))
    assert len(seen) == 1
    assert seen[0].count("2026-11-13") == 2


def test_anomaly_parses_code_from_link():
    payload = {
        "ok": True,
        "data": {
            "items": [
                {
                    "tag_code": "LIMIT_UP",
                    "tag_name": "涨停",
                    "key_word_list": ["业绩预增"],
                    "analysis_content": "样本",
                    "link_url": "https://x/?marketId=33&thsHqCode=002115.SZ&date=2026-11-13",
                }
            ]
        },
    }
    client = _client(lambda args, **kwargs: _completed(args, payload))
    items = client.anomaly_analysis(date(2026, 11, 13))
    assert items[0]["thscode"] == "002115.SZ"
    assert items[0]["keyWords"] == ["业绩预增"]


def test_stock_timeline_pages_and_dedupes():
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        if "--offset" in args and args[args.index("--offset") + 1] == "first":
            return _completed(
                args,
                {
                    "ok": True,
                    "data": {
                        "item": [
                            {"title": "a", "content": "same", "url": "u1", "seq": "1"},
                            {"title": "b", "content": "other", "url": "u2", "seq": "2"},
                        ],
                        "offset": "next",
                        "has_more": True,
                    },
                },
            )
        return _completed(
            args,
            {
                "ok": True,
                "data": {
                    "item": [{"title": "c", "content": "same", "url": "u1", "seq": "3"}],
                    "has_more": False,
                },
            },
        )

    rows = _client(runner).stock_timeline("300001.SZ", size=2, max_pages=3)
    assert len(rows) == 2
    assert len(calls) == 2
    assert rows[0]["seq"] == "1"
    assert rows[1]["title"] == "b"


def test_stock_timeline_maps_unavailable_to_insufficient():
    payload = {"ok": False, "error": {"code": "FUYAO_5003", "message": "Data source unavailable"}}

    client = _client(lambda args, **kwargs: _completed(args, payload))
    with pytest.raises(FuyaoInsufficient) as error:
        client.stock_timeline("300001.SZ")
    assert error.value.code == "FUYAO_5003"


def test_stock_timeline_keeps_unknown_fields_under_raw():
    payload = {
        "ok": True,
        "data": {"item": [{"content": "x", "brand_new_field": "keep-me"}], "has_more": False},
    }
    rows = _client(lambda args, **kwargs: _completed(args, payload)).stock_timeline("300001.SZ")
    assert rows[0]["raw"]["brand_new_field"] == "keep-me"


def test_notice_detail_is_not_part_of_v1_call_path():
    blobs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [SKILL / "SKILL.md", SKILL / "scripts" / "news.py", SKILL / "scripts" / "news_pipeline.py"]
        if path.exists()
    )
    assert "notice-detail" not in blobs
    assert "notice_detail" not in blobs


def _lexicon():
    import news

    return news.load_lexicon()


def _score_text(text: str, keywords=()):
    import news

    lex = _lexicon()
    keyword_hits = news.classify_keywords(keywords, lex)
    events = news.merge_events(keyword_hits["events"], news.match_text(text, lex))
    for event in events:
        event["contribution"] = news.event_contribution(event, 1.0)
    return events


def _polarity(events, unit=False, evidence_count=1, covered=1, members=1):
    import news

    return news.aggregate_polarity(
        events,
        evidence_count=evidence_count,
        covered_members=covered,
        member_count=members,
        unit=unit,
    )


def test_lexicon_validation_and_stable_hash():
    import news

    lex = _lexicon()
    assert lex.version == "1.0"
    assert len(lex.sha256) == 64
    assert len(lex.of_class("event")) >= 80
    again = news.load_lexicon()
    assert again.sha256 == lex.sha256


def test_lexicon_rejects_unknown_rule_id(tmp_path):
    import news

    payload = {
        "version": "1.0",
        "rules": [
            {
                "id": "x",
                "ruleId": "QTS-99-99-99",
                "class": "event",
                "eventType": "x",
                "polarity": "positive",
                "severity": "weak",
                "weight": 1,
                "patterns": ["x"],
            }
        ],
    }
    path = tmp_path / "lexicon.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(news.LexiconError):
        news.load_lexicon(path)


def test_negation_drops_planned_negative_events():
    events = _score_text("公司终止减持计划，未实施减持")
    assert [event for event in events if event["active"]] == []


def test_uncertainty_downgrades_planned_reduction():
    events = _score_text("股东拟减持不超过2%股份")
    active = [event for event in events if event["active"]]
    assert active and active[0]["eventType"] == "股东减持"
    assert active[0]["severity"] == "weak"
    assert active[0]["certainty"] == "speculative"
    assert _polarity(active)["label"] == "negative"
    import news

    assert news.stock_risk(active, 1) == "watch"


def test_negation_does_not_cross_sentence_boundary():
    events = _score_text("公司不存在退市风险。公司股东减持")
    active = [event for event in events if event["active"]]
    assert any(event["eventType"] == "股东减持" for event in active)


def test_hard_negative_wins_over_positive():
    events = _score_text("公司收到退市风险警示，同时发布业绩预增公告")
    import news

    assert news.stock_risk(events, 1) == "block"
    assert _polarity(events)["label"] in {"negative", "mixed"}


def test_positive_and_reduction_is_mixed_and_downgrade():
    events = _score_text("公司业绩预增，股东减持")
    polarity = _polarity(events)
    assert polarity["label"] == "mixed"
    import news

    assert news.stock_risk(events, 1) == "downgrade"


def test_neutral_when_only_clarification_text():
    events = _score_text("公司发布澄清公告，股票交易正常")
    polarity = _polarity(events)
    assert polarity["label"] == "neutral"


def test_unknown_when_no_evidence():
    polarity = _polarity([], evidence_count=0)
    assert polarity["label"] == "unknown"
    assert polarity["missingReason"]


def test_unit_gate_requires_two_evidence_and_two_members():
    events = _score_text("公司业绩预增")
    polarity = _polarity(events, unit=True, evidence_count=1, covered=1, members=10)
    assert polarity["label"] == "unknown"
    assert polarity["confidence"] == "insufficient"
    assert polarity["missingReason"]


def test_uncovered_is_not_none():
    import news

    assert news.stock_risk([], 0) == "uncovered"
    assert news.stock_risk([], 1) == "none"


def test_keyword_classes_route_correctly():
    import news

    lex = _lexicon()
    routed = news.classify_keywords(["业绩预亏", "存储芯片", "板块回调", "未知新词"], lex)

    assert [event["eventType"] for event in routed["events"]] == ["业绩预亏"]
    assert routed["topics"] == ["存储芯片"]
    assert routed["contexts"] == ["板块回调"]
    assert routed["unmatched"] == ["未知新词"]


def test_date_and_code_helpers():
    import news

    assert news.parse_date_from_url("https://x/?a=1&date=2026-11-13") == date(2026, 11, 13)
    assert news.parse_date_from_url("https://x/") is None
    assert news.normalize_code("002115") == "002115.SZ"
    assert news.normalize_code("600000") == "600000.SH"
    assert news.normalize_code("430047") == "430047.BJ"
    assert news.normalize_code("600000.SH") == "600000.SH"


def test_recency_decay_half_life():
    import news

    assert news.recency_decay(0) == 1.0
    assert news.recency_decay(3) == pytest.approx(0.5)
    assert news.recency_decay(None) == 1.0


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------


def _fixture(name: str) -> Path:
    return FIXTURES / f"{name}.json"


def _run(name: str, **kwargs):
    import news_pipeline as pipeline

    fixture = json.loads(_fixture(name).read_text(encoding="utf-8"))
    return pipeline.run_pipeline(as_of=date(2026, 11, 13), fixture=fixture, **kwargs)


def test_mixed_fixture_end_to_end():
    result = _run("news-mixed")
    assert result["schemaVersion"] == "1.0"
    assert result["step"] == "STEP 2.5"
    assert result["ruleVersion"] == "QTS-04-09"
    assert result["status"] == "degraded"
    assert result["primarySourceAvailable"] is False
    assert result["calibration"] == "needs-backtest"
    assert len(result["lexicon"]["sha256"]) == 64
    assert result["quality"]["coverage"]["duplicates"] == 1
    assert result["quality"]["coverage"]["unattributed"] == 1

    units = {unit["unitId"]: unit for unit in result["units"]}
    assert units["theme:T1"]["polarity"]["label"] == "mixed"
    assert units["theme:T1"]["coveredMembers"] == 4
    assert units["theme:T1"]["polarity"]["confidence"] in {"medium", "high"}
    assert units["theme:T2"]["polarity"]["label"] == "unknown"
    assert units["theme:T2"]["polarity"]["missingReason"]
    assert units["sector:881101.TI"]["polarity"]["label"] == "mixed"

    stocks = {stock["thscode"]: stock for stock in result["stocks"]}
    assert stocks["002115.SZ"]["riskLevel"] == "block"
    assert stocks["300001.SZ"]["riskLevel"] == "none"
    assert stocks["600000.SH"]["polarity"]["label"] == "neutral"
    assert stocks["000001.SZ"]["riskLevel"] == "none"
    assert len(result["evidence"]) == result["quality"]["coverage"]["evidenceItems"]


def test_attribution_is_by_thscode_and_duplicates_drop():
    payload = {
        "asOf": "2026-11-13",
        "tradingDays": ["2026-11-13"],
        "anomalies": [
            {"thscode": "A", "keyWords": [], "content": "同一段文本", "url": "u1"},
            {"thscode": "A", "keyWords": [], "content": "同一段文本", "url": "u2"},
            {"thscode": "B", "keyWords": [], "content": "同一段文本", "url": "u3"},
            {"thscode": "", "keyWords": [], "content": "无代码文本", "url": "u4"},
        ],
        "limitUps": [],
        "timelines": {},
        "constituents": {},
    }
    import news_pipeline as pipeline

    result = pipeline.run_pipeline(as_of=date(2026, 11, 13), fixture=payload, codes=["A", "B"])
    assert result["quality"]["coverage"]["duplicates"] == 1
    assert result["quality"]["coverage"]["unattributed"] == 1
    assert result["quality"]["coverage"]["evidenceItems"] == 2
    assert {stock["thscode"] for stock in result["stocks"]} == {"A", "B"}


def test_status_degraded_when_timeline_unavailable():
    result = _run("news-timeline-unavailable")
    assert result["status"] == "degraded"
    assert result["quality"]["sources"]["stockTimeline"]["status"] == "unavailable"
    assert result["quality"]["sources"]["stockTimeline"]["reason"]


def test_status_insufficient_when_no_source():
    result = _run("news-insufficient")
    assert result["status"] == "insufficient"
    assert result["units"][0]["polarity"]["label"] == "unknown"
    assert result["stocks"] == []


def test_upstream_v2_is_rejected_as_insufficient():
    import news_pipeline as pipeline

    fixture = json.loads(_fixture("news-upstream-v2").read_text(encoding="utf-8"))
    with pytest.raises(pipeline.FuyaoInsufficient, match="schemaVersion"):
        pipeline.run_pipeline(as_of=date(2026, 11, 13), fixture=fixture)


def test_negation_fixture_with_codes():
    result = _run("news-negation", codes=["600519.SH", "600520.SH", "999999.SZ"])
    stocks = {stock["thscode"]: stock for stock in result["stocks"]}
    assert stocks["600519.SH"]["riskLevel"] == "none"
    assert stocks["600519.SH"]["polarity"]["label"] == "neutral"
    assert stocks["600520.SH"]["riskLevel"] == "watch"
    assert stocks["999999.SZ"]["riskLevel"] == "uncovered"
    assert stocks["999999.SZ"]["missingReason"]


def test_fixture_never_touches_network(monkeypatch):
    import news_pipeline as pipeline

    def explode(*args, **kwargs):
        raise AssertionError("fixture mode must not construct a client")

    monkeypatch.setattr(pipeline, "FuyaoClient", explode)
    result = _run("news-mixed")
    assert result["status"] == "degraded"


def test_date_validation_rejects_future_and_pre_close():
    import news_pipeline as pipeline
    from datetime import datetime

    with pytest.raises(pipeline.FuyaoInsufficient, match="未来"):
        pipeline.resolve_as_of("2026-11-24", now=datetime(2026, 11, 23, 16, 0, tzinfo=pipeline.SHANGHAI))
    with pytest.raises(pipeline.FuyaoInsufficient, match="15:10"):
        pipeline.resolve_as_of("2026-11-23", now=datetime(2026, 11, 23, 14, 0, tzinfo=pipeline.SHANGHAI))
    assert pipeline.resolve_as_of(
        "2026-11-23", now=datetime(2026, 11, 23, 16, 0, tzinfo=pipeline.SHANGHAI)
    ) == date(2026, 11, 23)


def test_non_trading_day_is_rejected():
    import news_pipeline as pipeline

    fixture = {
        "asOf": "2026-11-14",
        "tradingDays": ["2026-11-13"],
        "anomalies": [],
        "limitUps": [],
        "timelines": {},
        "constituents": {},
    }
    with pytest.raises(pipeline.FuyaoInsufficient, match="交易日历"):
        pipeline.run_pipeline(as_of=date(2026, 11, 14), fixture=fixture, codes=["600000.SH"])


def test_report_id_is_stable_and_changes_with_lexicon(monkeypatch):
    import news

    first = _run("news-mixed")
    second = _run("news-mixed")
    assert first["reportId"] == second["reportId"]

    payload = json.loads((SKILL / "references" / "lexicon.v1.json").read_text(encoding="utf-8"))
    payload["version"] = "1.1"
    changed = news.load_lexicon(_write_temp_lexicon(payload))
    monkeypatch.setattr(news, "load_lexicon", lambda path=None: changed)
    third = _run("news-mixed")
    assert third["reportId"] != first["reportId"]


def _write_temp_lexicon(payload):
    import tempfile

    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle, ensure_ascii=False)
    handle.close()
    return Path(handle.name)


def test_cache_avoids_repeat_calls_and_refresh_forces_them():
    import news_pipeline as pipeline

    class FakeClient:
        calls = 0

        def check_prerequisites(self):
            return {"ready": True}

        def market_calendar(self):
            return ["2026-11-13"]

        def anomaly_analysis_range(self, start, end):
            FakeClient.calls += 1
            return [
                {
                    "thscode": "600000.SH",
                    "tagName": "公告",
                    "keyWords": ["业绩预增"],
                    "content": "业绩预增",
                    "url": "https://x/?date=2026-11-13",
                }
            ]

        def limit_up_pool(self, as_of):
            FakeClient.calls += 1
            return []

        def stock_timeline(self, code, **kwargs):
            FakeClient.calls += 1
            return []

        def constituents(self, code):
            return []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pipeline, "FuyaoClient", FakeClient)
    try:
        tmp = Path(tempfile.mkdtemp())
        first = pipeline.run_pipeline(
            as_of=date(2026, 11, 13), codes=["600000.SH"], cache_dir=tmp, use_cache=True
        )
        calls_after_first = FakeClient.calls
        second = pipeline.run_pipeline(
            as_of=date(2026, 11, 13), codes=["600000.SH"], cache_dir=tmp, use_cache=True
        )
        assert FakeClient.calls == calls_after_first
        assert first["reportId"] == second["reportId"]
        pipeline.run_pipeline(
            as_of=date(2026, 11, 13), codes=["600000.SH"], cache_dir=tmp, use_cache=False
        )
        assert FakeClient.calls > calls_after_first
    finally:
        monkeypatch.undo()


def test_cli_writes_json_and_report(tmp_path):
    import news_pipeline as pipeline

    output = tmp_path / "news.json"
    code = pipeline.main(
        [
            "--as-of",
            "2026-11-13",
            "--fixture",
            str(_fixture("news-mixed")),
            "--output",
            str(output),
            "--format",
            "json",
        ]
    )
    assert code == 0
    assert output.exists()
    assert output.with_suffix(".md").exists()
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "degraded"


def test_fallback_reports_pass_checker_for_all_statuses(tmp_path):
    import news_check_report as checker
    import news_pipeline as pipeline
    from news_report import render_fallback

    cases = {
        "news-mixed": [],
        "news-timeline-unavailable": [],
        "news-insufficient": [],
        "news-negation": ["600519.SH", "600520.SH", "999999.SZ"],
    }
    for name, codes in cases.items():
        result = _run(name, codes=codes)
        verdict = checker.validate_report(result, render_fallback(result))
        assert verdict["status"] == "pass", (name, verdict["issues"])


def test_checker_rejects_uncovered_as_no_bad_news():
    import news_check_report as checker
    from news_report import render_fallback

    result = _run("news-negation", codes=["600519.SH", "999999.SZ"])
    article = render_fallback(result)
    article = article.replace("未覆盖（不代表没有利空）", "未见利空")
    verdict = checker.validate_report(result, article)
    assert verdict["status"] == "fail"
    assert any(issue["check"] == "coverageWording" for issue in verdict["issues"])


def test_checker_rejects_unknown_as_neutral():
    import news_check_report as checker
    from news_report import render_fallback

    result = _run("news-mixed")
    article = render_fallback(result).replace("无法判定", "中性")
    verdict = checker.validate_report(result, article)
    assert verdict["status"] == "fail"
    assert any(issue["check"] == "coverageWording" for issue in verdict["issues"])


def test_checker_rejects_confirmed_claim_and_wrong_label():
    import news_check_report as checker
    from news_report import render_fallback

    result = _run("news-mixed")
    article = render_fallback(result)
    confirmed = article + "\n该利好已证实。\n"
    verdict = checker.validate_report(result, confirmed)
    assert verdict["status"] == "fail"
    assert any(issue["check"] == "primarySourceWording" for issue in verdict["issues"])

    wrong = article.replace("多空交织", "利好", 1)
    verdict = checker.validate_report(result, wrong)
    assert verdict["status"] == "fail"
    assert any(issue["check"] == "labelProvenance" for issue in verdict["issues"])


def test_checker_rejects_missing_disclaimer_and_backtest_marker():
    import news_check_report as checker
    from news_report import render_fallback

    result = _run("news-mixed")
    article = render_fallback(result)
    article = article.replace("needs-backtest", "已验证")
    verdict = checker.validate_report(result, article)
    assert verdict["status"] == "fail"
    assert any(issue["check"].startswith("required") for issue in verdict["issues"])


def test_fixture_count_and_lexicon_size():
    assert len(list(FIXTURES.glob("*.json"))) == 7
    payload = json.loads((SKILL / "references" / "lexicon.v1.json").read_text(encoding="utf-8"))
    event_rules = [rule for rule in payload["rules"] if rule["class"] == "event"]
    assert len(event_rules) >= 80
    assert all(rule["ruleId"] in news.RULE_IDS for rule in payload["rules"])


def test_cli_step_paths_codes_cache_and_refresh(tmp_path):
    import news_pipeline as pipeline

    output = tmp_path / "news.json"
    cache = tmp_path / "cache"
    code = pipeline.main(
        [
            "--as-of",
            "2026-11-13",
            "--fixture",
            str(_fixture("news-mixed")),
            "--step1",
            str(_fixture("step1-basic")),
            "--step2",
            str(_fixture("step2-basic")),
            "--codes",
            "002115.SZ",
            "--cache-dir",
            str(cache),
            "--refresh",
            "--output",
            str(output),
            "--format",
            "json",
        ]
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert {unit["unitType"] for unit in payload["units"]} == {"sector", "theme"}
    codes = {stock["thscode"] for stock in payload["stocks"]}
    assert "002115.SZ" in codes
    assert codes == {"002115.SZ", "300001.SZ", "600000.SH", "000001.SZ"}


def test_cli_exit_codes(tmp_path):
    import news_pipeline as pipeline

    mixed = tmp_path / "mixed.json"
    assert pipeline.main(
        ["--as-of", "2026-11-13", "--fixture", str(_fixture("news-mixed")), "--output", str(mixed), "--format", "json"]
    ) == 0

    bad = tmp_path / "bad.json"
    assert pipeline.main(
        ["--as-of", "2026-11-13", "--fixture", str(_fixture("news-upstream-v2")), "--output", str(bad), "--format", "json"]
    ) == 1
    assert json.loads(bad.read_text(encoding="utf-8"))["status"] == "insufficient"

    with pytest.raises(SystemExit) as error:
        pipeline.main(["--as-of"])
    assert error.value.code == 2


def test_documented_keys_match_output():
    result = _run("news-mixed")
    documented = {
        "schemaVersion",
        "step",
        "ruleVersion",
        "reportId",
        "asOf",
        "config",
        "input",
        "status",
        "quality",
        "primarySourceAvailable",
        "primarySourceReason",
        "units",
        "stocks",
        "evidence",
        "lexicon",
        "unmatchedKeywords",
        "disclaimer",
        "calibration",
    }
    assert documented <= set(result)
    contract = (SKILL / "references" / "data-contract.md").read_text(encoding="utf-8")
    for key in documented:
        assert key in contract, key


def test_checker_rejects_buy_wording():
    import news_check_report as checker
    from news_report import render_fallback

    result = _run("news-mixed")
    article = render_fallback(result) + "\n建议买入。\n"
    verdict = checker.validate_report(result, article)
    assert verdict["status"] == "fail"
    assert any(issue["check"] == "forbiddenWording" for issue in verdict["issues"])


def test_calendar_dates_are_normalized_from_compact_form():
    import news_pipeline as pipeline

    assert pipeline._normalize_calendar(["20261120", "2026-11-23", ""]) == [
        "2026-11-20",
        "2026-11-23",
    ]


def test_anomaly_unavailable_but_limit_up_ok_is_degraded():
    import news_pipeline as pipeline
    from qts04.client import FuyaoDegraded

    class FakeClient:
        def check_prerequisites(self):
            return {"ready": True}

        def market_calendar(self):
            return ["20261120"]

        def anomaly_analysis_range(self, start, end):
            raise FuyaoDegraded("data source unavailable", code="FUYAO_5003")

        def limit_up_pool(self, as_of):
            return [{"thscode": "002115.SZ", "name": "样本", "reason": "商业航天+存储芯片"}]

        def stock_timeline(self, code, **kwargs):
            return []

        def constituents(self, code):
            return []

    original = pipeline.FuyaoClient
    pipeline.FuyaoClient = FakeClient
    try:
        result = pipeline.run_pipeline(as_of=date(2026, 11, 20), codes=["002115.SZ"], use_cache=False)
    finally:
        pipeline.FuyaoClient = original
    assert result["status"] == "degraded"
    assert result["quality"]["sources"]["anomalyAnalysis"]["status"] == "unavailable"
    assert result["quality"]["sources"]["limitUpReason"]["status"] == "ok"
    assert result["quality"]["coverage"]["calendar"] == "ok"
    assert result["stocks"][0]["thscode"] == "002115.SZ"


def test_cli_invalid_fixture_returns_2(tmp_path):
    import news_pipeline as pipeline

    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert pipeline.main(["--as-of", "2026-11-13", "--fixture", str(bad)]) == 2


def test_checker_unreadable_input_returns_2(tmp_path, capsys):
    import news_check_report as checker

    assert checker.main(["--result", str(tmp_path / "missing.json"), "--article", str(tmp_path / "missing.md")]) == 2


def test_weekend_is_rejected_when_calendar_is_unavailable():
    import news_pipeline as pipeline

    fixture = {
        "asOf": "2026-11-14",
        "tradingDays": [],
        "anomalies": [],
        "limitUps": [],
        "timelines": {},
        "constituents": {},
    }
    with pytest.raises(pipeline.FuyaoInsufficient, match="周末"):
        pipeline.run_pipeline(as_of=date(2026, 11, 14), fixture=fixture, codes=["600000.SH"])
