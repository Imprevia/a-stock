"""Offline behavioral coverage for the QTS-04 sector-direction Skill."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/a-stock-qts04-sector-direction"
SCRIPTS = SKILL / "scripts"
FIXTURES = ROOT / "tests/fixtures/a_stock_qts04_sector_direction"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cache as cache_module  # noqa: E402
import check_report  # noqa: E402
import sector_contract as contract  # noqa: E402
import fuyao_client  # noqa: E402
import predicate  # noqa: E402
import scoring  # noqa: E402
import report  # noqa: E402
import sector_pipeline  # noqa: E402


@dataclass
class Completed:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _bars(rows: list[dict]) -> list[scoring.Bar]:
    return sector_pipeline._bars_from_fixture(rows)


def _trend(start: float, days: int, step: float) -> list[scoring.Bar]:
    bars = []
    value = start
    for index in range(days):
        value *= 1 + step
        bars.append(
            scoring.Bar(
                trading_date=date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + index),
                close=value,
                turnover=1e9,
            )
        )
    return bars


# ---------------------------------------------------------------- scoring


def test_percentile_tiers_match_documented_boundaries() -> None:
    assert [scoring.percentile_score(value) for value in (0.10, 0.21, 0.39, 0.41, 0.59, 0.61, 0.79, 0.81)] == [
        0,
        25,
        25,
        50,
        50,
        75,
        75,
        100,
    ]
    assert scoring.percentile_score(0.20) == 0
    assert scoring.percentile_score(0.40) == 25
    assert scoring.percentile_score(0.60) == 50
    assert scoring.percentile_score(0.80) == 75
    assert scoring.percentile_score(None) is None


def test_observation_threshold_is_strictly_sixty() -> None:
    fifty_nine, count_59, status_59 = scoring.rolling_midrank(1.0, [float(i) for i in range(58)])
    assert (fifty_nine, count_59, status_59) == (None, 59, scoring.STATUS_INSUFFICIENT)

    value_60, count_60, status_60 = scoring.rolling_midrank(1.0, [float(i) for i in range(59)])
    assert count_60 == 60
    assert status_60 == scoring.STATUS_REDUCED
    assert value_60 is not None

    _, count_250, status_250 = scoring.rolling_midrank(1.0, [float(i) for i in range(249)])
    assert count_250 == 250
    assert status_250 == scoring.STATUS_OK


def test_midrank_percentile_is_deterministic_and_symmetric_on_ties() -> None:
    assert scoring.midrank_percentile(2, [1, 2, 3]) == pytest.approx(0.5)
    assert scoring.midrank_percentile(2, [2, 2, 2]) == pytest.approx(0.5)
    assert scoring.midrank_percentile(3, [1, 2, 3]) == pytest.approx(5 / 6)
    assert scoring.midrank_percentile(None, [1, 2]) is None
    assert scoring.midrank_percentile(1, []) is None


def test_turnover_ratio_excludes_today_and_rejects_zero_mean() -> None:
    days = [date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + i) for i in range(22)]
    bars = [scoring.Bar(trading_date=day, close=10.0, turnover=100.0) for day in days[:-1]]
    bars.append(scoring.Bar(trading_date=days[-1], close=10.0, turnover=200.0))
    value, history = scoring.turnover_ratio(bars, 20)
    assert value == pytest.approx(2.0)
    assert len(history) == 2

    zero_bars = [scoring.Bar(trading_date=day, close=10.0, turnover=0.0) for day in days]
    zero_value, _ = scoring.turnover_ratio(zero_bars, 20)
    assert zero_value is None


def test_turnover_ratio_returns_none_when_window_is_short() -> None:
    days = [date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + i) for i in range(5)]
    bars = [scoring.Bar(trading_date=day, close=10.0, turnover=1e9) for day in days]
    assert scoring.turnover_ratio(bars, 20) == (None, [])


def test_relative_strength_needs_aligned_sessions() -> None:
    sector = _trend(1000.0, 30, 0.01)
    benchmark = _trend(3000.0, 30, 0.001)
    value, history = scoring.relative_strength(sector, benchmark, 5)
    assert value is not None and value > 0
    assert history
    short_value, short_history = scoring.relative_strength(sector, benchmark, 40)
    assert short_value is None
    assert short_history == []


def test_breadth_coverage_gate_blocks_ranking() -> None:
    as_of = date(2026, 11, 13)
    fixture = _fixture("short-history.json")
    members = {
        code: _bars(rows) for code, rows in fixture["stockBars"].items()
    }
    ratio, coverage, valid, total = scoring.member_ma20(members, as_of)
    assert total == 5
    assert valid == 2
    assert coverage == pytest.approx(0.4)
    assert ratio is not None


def test_member_ma20_returns_none_for_zero_members() -> None:
    ratio, coverage, valid, total = scoring.member_ma20({}, date(2026, 11, 13))
    assert (ratio, coverage, valid, total) == (None, 0.0, 0, 0)


def test_persistence_metric_reports_insufficient_without_windows() -> None:
    sector = _trend(1000.0, 3, 0.01)
    benchmark = _trend(3000.0, 3, 0.001)
    value, _, status, _ = scoring.persistence_metric(sector, benchmark)
    assert value is None
    assert status == scoring.STATUS_INSUFFICIENT


def test_quadrant_uses_raw_values_only() -> None:
    strong_broad = scoring.quadrant(turnover_ratio_value=1.5, relative_strength_5=0.05, advance=0.7)
    assert strong_broad["label"] == "真实流入"
    strong_narrow = scoring.quadrant(turnover_ratio_value=1.5, relative_strength_5=0.05, advance=0.3)
    assert strong_narrow["label"] == "短线脉冲"
    weak_broad = scoring.quadrant(turnover_ratio_value=0.9, relative_strength_5=-0.01, advance=0.7)
    assert weak_broad["label"] == "权重拉升"
    weak_narrow = scoring.quadrant(turnover_ratio_value=0.9, relative_strength_5=-0.01, advance=0.3)
    assert weak_narrow["label"] == "资金撤退"
    assert scoring.quadrant(turnover_ratio_value=None, relative_strength_5=0.05, advance=0.7)["label"] is None


def test_normalized_weights_renormalize_over_scored_metrics() -> None:
    metrics = [
        scoring.Metric("A", "a", 1.0, 0.5, 50, scoring.STATUS_OK, 0.25),
        scoring.Metric("B", "b", None, None, None, scoring.STATUS_INSUFFICIENT, 0.15),
        scoring.Metric("C", "c", 1.0, 0.5, 50, scoring.STATUS_OK, 0.20),
        scoring.Metric("D", "d", 1.0, 0.5, 50, scoring.STATUS_OK, 0.20),
        scoring.Metric("E", "e", 1.0, 0.5, 50, scoring.STATUS_OK, 0.20),
    ]
    scoring.normalize_weights(metrics)
    assert metrics[1].normalized_weight is None
    total = sum(metric.normalized_weight or 0 for metric in metrics)
    assert total == pytest.approx(1.0)
    assert scoring.total_score(metrics) == pytest.approx(50.0)


def test_confidence_caps_at_medium_for_reduced_windows() -> None:
    ok_metrics = [
        scoring.Metric(str(i), str(i), 1.0, 0.5, 50, scoring.STATUS_OK, 0.2) for i in range(5)
    ]
    assert scoring.confidence_from_metrics(ok_metrics) == "high"
    reduced = [
        scoring.Metric(str(i), str(i), 1.0, 0.5, 50, scoring.STATUS_REDUCED, 0.2) for i in range(5)
    ]
    assert scoring.confidence_from_metrics(reduced) == "medium"
    partial = [
        scoring.Metric("0", "0", 1.0, 0.5, 50, scoring.STATUS_OK, 0.2),
        scoring.Metric("1", "1", 1.0, 0.5, 50, scoring.STATUS_OK, 0.2),
        scoring.Metric("2", "2", 1.0, 0.5, 50, scoring.STATUS_OK, 0.2),
        scoring.Metric("3", "3", None, None, None, scoring.STATUS_INSUFFICIENT, 0.2),
        scoring.Metric("4", "4", None, None, None, scoring.STATUS_INSUFFICIENT, 0.2),
    ]
    assert scoring.confidence_from_metrics(partial) == "low"


def test_pool_state_thresholds_require_persistence_companion() -> None:
    assert scoring.pool_state(75, 65) == "focus"
    assert scoring.pool_state(75, 40) == "watch"
    assert scoring.pool_state(60, 100) == "watch"
    assert scoring.pool_state(49, 100) == "excluded"
    assert scoring.pool_state(None, 100) == "insufficient"


# ---------------------------------------------------------------- client


def test_client_rejects_missing_credential_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(fuyao_client.API_KEY_ENV, raising=False)
    monkeypatch.delenv(fuyao_client.LEGACY_API_KEY_ENV, raising=False)
    client = fuyao_client.FuyaoClient(
        api_key="",
        runner=lambda *a, **kw: pytest.fail("must not run"),
    )
    with pytest.raises(fuyao_client.FuyaoInsufficient):
        client.require_key()
    assert client.calls == []


def test_env_file_parsing_handles_dotenv_syntax(tmp_path: Path) -> None:
    env = tmp_path / "deploy.env"
    env.write_text(
        "# comment line\n"
        "\n"
        "NAMESPACE=a-stock\n"
        "export FUYAO_API_KEY='quoted-value-123'\n"
        "TUSHARE_TOKEN=should-never-be-read\n",
        encoding="utf-8",
    )
    assert fuyao_client.parse_env_file(env, "FUYAO_API_KEY") == "quoted-value-123"
    assert fuyao_client.parse_env_file(env, "NAMESPACE") == "a-stock"
    assert fuyao_client.parse_env_file(env, "MISSING") is None
    assert fuyao_client.parse_env_file(tmp_path / "absent.env", "FUYAO_API_KEY") is None


def test_env_file_parsing_strips_double_quotes_and_inline_comment(tmp_path: Path) -> None:
    env = tmp_path / "deploy.env"
    env.write_text(
        'A="double-quoted"\n'
        "B=plain-value # trailing comment\n"
        "C=\n",
        encoding="utf-8",
    )
    assert fuyao_client.parse_env_file(env, "A") == "double-quoted"
    assert fuyao_client.parse_env_file(env, "B") == "plain-value"
    assert fuyao_client.parse_env_file(env, "C") is None


def test_credential_falls_back_to_deploy_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(fuyao_client.API_KEY_ENV, raising=False)
    monkeypatch.delenv(fuyao_client.LEGACY_API_KEY_ENV, raising=False)
    env = tmp_path / "deploy.env"
    env.write_text("FUYAO_API_KEY=from-file-key\nTUSHARE_TOKEN=other-secret\n", encoding="utf-8")

    key, source = fuyao_client.resolve_credential(env_file=env)
    assert key == "from-file-key"
    assert source == "file:FUYAO_API_KEY@deploy.env"

    client = fuyao_client.FuyaoClient(env_file=env)
    assert client.require_key() == "from-file-key"
    assert client.credential_source == source


def test_credential_prefers_process_env_over_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / "deploy.env"
    env.write_text("FUYAO_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv(fuyao_client.API_KEY_ENV, "from-process-env")

    key, source = fuyao_client.resolve_credential(env_file=env)
    assert key == "from-process-env"
    assert source == f"env:{fuyao_client.API_KEY_ENV}"


def test_credential_accepts_legacy_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(fuyao_client.API_KEY_ENV, raising=False)
    monkeypatch.setenv(fuyao_client.LEGACY_API_KEY_ENV, "legacy-key")
    env = tmp_path / "deploy.env"
    env.write_text("FUYAO_API_KEY=from-file\n", encoding="utf-8")

    key, source = fuyao_client.resolve_credential(env_file=env)
    assert key == "legacy-key"
    assert source == f"env:{fuyao_client.LEGACY_API_KEY_ENV}"


def test_credential_reports_none_when_nothing_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(fuyao_client.API_KEY_ENV, raising=False)
    monkeypatch.delenv(fuyao_client.LEGACY_API_KEY_ENV, raising=False)
    key, source = fuyao_client.resolve_credential(env_file=tmp_path / "absent.env")
    assert key is None
    assert source == "none"


def test_repo_env_file_is_found_and_git_ignored() -> None:
    env = fuyao_client.find_env_file(SKILL / "scripts" / "fuyao_client.py")
    assert env is not None, "deploy/truenas/deploy.env should be discoverable from the skill"
    assert env.name == "deploy.env"
    assert env.parent.name == "truenas"
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(env)],
        cwd=str(ROOT),
        check=False,
    )
    assert result.returncode == 0, "credential file must stay git-ignored"


def test_credential_source_never_contains_the_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(fuyao_client.API_KEY_ENV, raising=False)
    monkeypatch.delenv(fuyao_client.LEGACY_API_KEY_ENV, raising=False)
    secret = "sk-file-secret-must-not-leak-0001"
    env = tmp_path / "deploy.env"
    env.write_text(f"FUYAO_API_KEY={secret}\n", encoding="utf-8")
    client = fuyao_client.FuyaoClient(env_file=env)
    assert client.require_key() == secret
    assert secret not in client.credential_source
    assert secret not in json.dumps({"source": client.credential_source}, ensure_ascii=False)


def test_client_reports_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fuyao_client.shutil, "which", lambda _: None)
    client = fuyao_client.FuyaoClient(api_key="x" * 20, runner=lambda *a, **kw: pytest.fail("must not run"))
    with pytest.raises(fuyao_client.FuyaoInsufficient) as error:
        client.check_prerequisites()
    assert "hithink-finance" in str(error.value)


def test_client_parses_success_envelope() -> None:
    client = fuyao_client.FuyaoClient(
        api_key="k" * 24,
        runner=lambda *a, **kw: Completed(
            stdout='{"ok": true, "data": {"item": [{"thscode": "881101.TI", "name": "种植业"}]}}'
        ),
    )
    assert client.list_industries() == [{"thscode": "881101.TI", "name": "种植业"}]


def test_client_retries_rate_limit_then_succeeds() -> None:
    responses = [
        Completed(stdout='{"ok": false, "error": {"code": 4001, "message": "rate"}}'),
        Completed(stdout='{"ok": false, "error": {"code": 4001, "message": "rate"}}'),
        Completed(stdout='{"ok": true, "data": {"item": [{"thscode": "X.TI", "name": "n"}]}}'),
    ]
    delays: list[float] = []
    client = fuyao_client.FuyaoClient(
        api_key="k" * 24,
        max_retries=3,
        sleeper=delays.append,
        runner=lambda *a, **kw: responses.pop(0),
    )
    assert client.list_industries() == [{"thscode": "X.TI", "name": "n"}]
    assert len(delays) == 2
    assert delays == [1.0, 2.0]
    assert client.calls[-1].attempts == 3


def test_client_backoff_is_bounded() -> None:
    responses = [Completed(stdout='{"ok": false, "error": {"code": 4001, "message": "rate"}}') for _ in range(6)]
    delays: list[float] = []
    client = fuyao_client.FuyaoClient(
        api_key="k" * 24,
        max_retries=2,
        sleeper=delays.append,
        runner=lambda *a, **kw: responses.pop(0),
    )
    with pytest.raises(fuyao_client.FuyaoDegraded):
        client.list_industries()
    assert all(delay <= fuyao_client.MAX_BACKOFF_SECONDS for delay in delays)
    assert len(delays) == 2


def test_client_batches_history_calls_at_ten_codes() -> None:
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        codes = argv[argv.index("--thscodes") + 1].split(",")
        payload = {"ok": True, "data": {"item": [{"thscode": code, "item": []} for code in codes]}}
        return Completed(stdout=json.dumps(payload))

    client = fuyao_client.FuyaoClient(api_key="k" * 24, runner=runner)
    codes = [f"{880000 + index}.TI" for index in range(23)]
    client.industry_history_batch(codes, date(2026, 10, 1), date(2026, 11, 13))
    assert len(calls) == 3
    assert [len(call[call.index("--thscodes") + 1].split(",")) for call in calls] == [10, 10, 3]


def test_client_redacts_credential_from_errors() -> None:
    secret = "sk-fuyao-supersecret-value-123"
    client = fuyao_client.FuyaoClient(
        api_key=secret,
        runner=lambda *a, **kw: Completed(returncode=2, stdout="", stderr=f"boom {secret}"),
    )
    with pytest.raises(fuyao_client.FuyaoDegraded) as error:
        client.list_industries()
    assert secret not in str(error.value)
    assert "***" in str(error.value)


def test_client_credential_never_enters_argv() -> None:
    seen: dict[str, list[str]] = {}

    def runner(argv, **kwargs):
        seen["argv"] = list(argv)
        seen["env"] = kwargs.get("env") or {}
        return Completed(stdout='{"ok": true, "data": {"item": [{"thscode": "X.TI", "name": "n"}]}}')

    secret = "sk-fuyao-never-in-argv-9876"
    client = fuyao_client.FuyaoClient(api_key=secret, runner=runner)
    client.list_industries()
    assert all(secret not in token for token in seen["argv"])
    assert seen["env"][fuyao_client.CLI_KEY_ENV] == secret


# ---------------------------------------------------------------- cache


def test_cache_roundtrip_and_states(tmp_path: Path) -> None:
    store = cache_module.BarCache(tmp_path)
    as_of = date(2026, 11, 13)
    bar = scoring.Bar(trading_date=as_of, close=10.0, turnover=1e9)
    store.save(cache_module.KIND_INDUSTRY, "881101.TI", [bar])
    assert store.load(cache_module.KIND_INDUSTRY, "881101.TI")[0].close == 10.0
    assert store.cache_state(cache_module.KIND_INDUSTRY, ["881101.TI"], as_of) == cache_module.CACHE_STATE_WARM
    assert store.cache_state(cache_module.KIND_INDUSTRY, ["884001.TI"], as_of) == cache_module.CACHE_STATE_COLD
    assert (
        store.cache_state(cache_module.KIND_INDUSTRY, ["881101.TI", "884001.TI"], as_of)
        == cache_module.CACHE_STATE_PARTIAL
    )


def test_cache_merges_without_dropping_earlier_sessions(tmp_path: Path) -> None:
    store = cache_module.BarCache(tmp_path)
    day1 = date(2026, 11, 12)
    day2 = date(2026, 11, 13)
    store.save(cache_module.KIND_INDUSTRY, "X.TI", [scoring.Bar(day1, 10.0, 1e9)])
    store.save(cache_module.KIND_INDUSTRY, "X.TI", [scoring.Bar(day2, 11.0, 1e9)])
    bars = store.load(cache_module.KIND_INDUSTRY, "X.TI")
    assert [bar.trading_date for bar in bars] == [day1, day2]


def test_cache_missing_window_only_requests_the_gap(tmp_path: Path) -> None:
    store = cache_module.BarCache(tmp_path)
    start = date(2026, 1, 1)
    end = date(2026, 3, 1)
    store.save(cache_module.KIND_INDUSTRY, "X.TI", [scoring.Bar(date(2026, 2, 1), 10.0, 1e9)])
    gap = store.missing_window(cache_module.KIND_INDUSTRY, "X.TI", start, end)
    assert gap is not None
    assert gap[0] < end


def test_cache_is_git_ignored() -> None:
    target = SKILL / ".cache"
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(target / "qts04" / "industry" / "x.json")],
        cwd=str(ROOT),
        check=False,
    )
    assert result.returncode == 0, "skill cache directory must stay untracked"


# ---------------------------------------------------------------- pipeline


def test_pipeline_e2e_from_fixture_produces_bounded_directions() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        breadth_universe=4,
        fixture=FIXTURES / "e2e.json",
    )
    assert result["source"] == "fixture"
    assert result["benchmark"] == "000001.SH"
    assert len(result["directions"]) <= 3
    assert result["directions"], "fixture should yield at least one direction"
    for direction in result["directions"]:
        assert direction["calibration"] == "needs-backtest"
        assert direction["confirmation"]["all"] and direction["invalidation"]["all"]
        assert direction["confirmation"]["text"] and direction["invalidation"]["text"]
        assert len(direction["metrics"]) == 5
        assert {metric["ruleId"] for metric in direction["metrics"]} == {
            "QTS-04-01-01",
            "QTS-04-01-02",
            "QTS-04-01-03",
            "QTS-04-01-04",
            "QTS-04-01-05",
        }
        assert 0 <= direction["totalScore"] <= 100


def test_pipeline_excludes_industry_below_coverage_gate() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        breadth_universe=4,
        fixture=FIXTURES / "e2e.json",
    )
    assert result["quality"]["excludedByCoverage"] == 1
    codes = {direction["thscode"] for direction in result["directions"]}
    assert "884001.TI" not in codes


def test_pipeline_short_history_yields_insufficient() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        fixture=FIXTURES / "short-history.json",
    )
    assert result["status"] == "insufficient"
    assert result["directions"] == []


def test_pipeline_missing_benchmark_is_insufficient() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        fixture=FIXTURES / "missing-benchmark.json",
    )
    assert result["status"] == "insufficient"
    assert any("基准" in warning for warning in result["quality"]["warnings"])


def test_pipeline_empty_catalog_is_insufficient() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        fixture=FIXTURES / "empty.json",
    )
    assert result["status"] == "insufficient"
    assert result["directions"] == []


def test_pipeline_output_never_claims_validation_or_advice() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        breadth_universe=4,
        fixture=FIXTURES / "e2e.json",
    )
    text = json.dumps(result, ensure_ascii=False)
    assert "validated" not in text
    assert result["calibration"] == "needs-backtest"
    assert "不是买点" in result["disclaimer"]


def test_pipeline_never_calls_real_cli_in_fixture_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("fixture mode must not spawn hithink-finance")

    monkeypatch.setattr(subprocess, "run", explode)
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        breadth_universe=4,
        fixture=FIXTURES / "e2e.json",
    )
    assert result["directions"]


def test_resolve_as_of_refuses_future_dates() -> None:
    now = datetime(2026, 11, 14, 10, 0)
    with pytest.raises(fuyao_client.FuyaoInsufficient):
        sector_pipeline.resolve_as_of("2026-12-01", now=now)


def test_resolve_as_of_refuses_unsettled_same_day() -> None:
    now = datetime(2026, 11, 14, 10, 0)
    with pytest.raises(fuyao_client.FuyaoInsufficient):
        sector_pipeline.resolve_as_of("2026-11-14", now=now)


def test_resolve_as_of_accepts_settled_session() -> None:
    now = datetime(2026, 11, 14, 16, 0)
    target, warnings = sector_pipeline.resolve_as_of("2026-11-13", now=now)
    assert target == date(2026, 11, 13)
    assert warnings == []


def test_cli_writes_output_file(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    exit_code = sector_pipeline.main(
        [
            "--as-of",
            "2026-11-13",
            "--breadth-universe",
            "4",
            "--fixture",
            str(FIXTURES / "e2e.json"),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["directions"]


def test_fixtures_contain_no_real_market_payload() -> None:
    for path in FIXTURES.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "synthetic fixture" in text
        assert "api_key" not in text.lower()


# ---------------------------------------------------------------- report


def _e2e_result() -> dict:
    return sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        breadth_universe=4,
        fixture=FIXTURES / "e2e.json",
    )


def test_report_has_title_and_all_sections() -> None:
    text = report.render_markdown(_e2e_result())
    assert text.startswith("# 板块层定向事实骨架 · 2026-11-13")
    for heading in ("## 一、结论速览", "## 二、方向明细", "## 三、数据质量", "## 四、口径与边界"):
        assert heading in text


def test_report_lists_every_direction_with_both_levels() -> None:
    result = _e2e_result()
    text = report.render_markdown(result)
    for direction in result["directions"]:
        assert direction["thscode"] in text
        assert direction["name"] in text
        assert direction["confirmation"]["text"] in text
        assert direction["invalidation"]["text"] in text


def test_report_tables_cover_all_five_rules_per_direction() -> None:
    text = report.render_markdown(_e2e_result())
    for rule_id in ("QTS-04-01-01", "QTS-04-01-02", "QTS-04-01-03", "QTS-04-01-04", "QTS-04-01-05"):
        assert text.count(f"`{rule_id}`") >= 2  # overview row + metric table row


def test_report_renders_missing_scores_as_dash_not_zero() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        breadth_universe=4,
        fixture=FIXTURES / "e2e.json",
    )
    weak = next(direction for direction in result["directions"] if direction["thscode"] == "881103.TI")
    breadth = next(metric for metric in weak["metrics"] if metric["ruleId"] == "QTS-04-01-04")
    assert breadth["score"] is None
    text = report.render_markdown(result)
    row = next(line for line in text.splitlines() if "`QTS-04-01-04`" in line and "板块宽度" in line and "无分" in line)
    assert "—" in row
    assert "| 0 |" not in row


def test_report_normalized_weights_never_exceed_one_hundred_percent() -> None:
    result = _e2e_result()
    text = report.render_markdown(result)
    for direction in result["directions"]:
        total = 0.0
        for metric in direction["metrics"]:
            weight = metric["normalizedWeight"]
            if weight is not None:
                total += weight
        assert total <= 1.0 + 1e-9
    assert "120%" not in text


def test_report_insufficient_result_says_no_directions() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        fixture=FIXTURES / "missing-benchmark.json",
    )
    text = report.render_markdown(result)
    assert "## 一、结论" in text
    assert "本次**不产出方向**" in text
    assert "基准 000001.SH 在 2026-11-13 没有日线" in text
    assert "## 二、数据质量" in text


def test_report_never_claims_validation_or_advice() -> None:
    text = report.render_markdown(_e2e_result())
    assert "validated" not in text
    assert "needs-backtest" in text
    assert "不是买点" in text


def test_cli_writes_markdown_report_next_to_json(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "result.json"
    exit_code = sector_pipeline.main(
        [
            "--as-of",
            "2026-11-13",
            "--breadth-universe",
            "4",
            "--fixture",
            str(FIXTURES / "e2e.json"),
            "--output",
            str(output),
            "--format",
            "json",
        ]
    )
    assert exit_code == 0
    report_path = output.with_suffix(".md")
    assert report_path.is_file()
    text = report_path.read_text(encoding="utf-8")
    assert text.startswith("# 板块层定向事实骨架")


def test_cli_explicit_report_path_wins(tmp_path: Path) -> None:
    output = tmp_path / "r.json"
    explicit = tmp_path / "custom" / "report.md"
    sector_pipeline.main(
        [
            "--as-of", "2026-11-13",
            "--breadth-universe", "4",
            "--fixture", str(FIXTURES / "e2e.json"),
            "--output", str(output),
            "--report", str(explicit),
        ]
    )
    assert explicit.is_file()
    assert not output.with_suffix(".md").exists()


def test_cli_markdown_format_prints_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sector_pipeline.main(
        [
            "--as-of", "2026-11-13",
            "--breadth-universe", "4",
            "--fixture", str(FIXTURES / "e2e.json"),
            "--format", "markdown",
        ]
    )
    captured = capsys.readouterr().out
    assert captured.startswith("# 板块层定向事实骨架")
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured)


def test_cli_json_format_stays_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    sector_pipeline.main(
        [
            "--as-of", "2026-11-13",
            "--breadth-universe", "4",
            "--fixture", str(FIXTURES / "e2e.json"),
            "--format", "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["directions"]


def test_default_report_path_replaces_suffix() -> None:
    assert str(report.default_report_path("a/b/result.json")) == "a/b/result.md"
    assert str(report.default_report_path("result")) == "result.md"

# ---------------------------------------------------------------- contract


def test_pipeline_declares_schema_version_and_frozen_config() -> None:
    result = _e2e_result()
    assert result["schemaVersion"] == contract.SCHEMA_VERSION == "1.0"
    config = result["config"]
    assert config["breadthUniverse"] == 4
    assert config["weights"] == {
        "QTS-04-01-01": 0.25,
        "QTS-04-01-02": 0.15,
        "QTS-04-01-03": 0.20,
        "QTS-04-01-04": 0.20,
        "QTS-04-01-05": 0.20,
    }
    assert config["percentileTiers"]["boundaries"] == [0.2, 0.4, 0.6, 0.8]
    assert config["percentileTiers"]["scores"] == [0, 25, 50, 75, 100]
    assert config["minObservations"] == 60
    assert config["fullWindow"] == 250
    assert config["minBreadthCoverage"] == 0.70
    assert config["confirmation"]["closeMultiplier"] == 1.005
    assert config["confirmation"]["closeChange"] == 0.005
    assert config["invalidation"]["closeMultiplier"] == 0.97
    assert config["invalidation"]["closeChange"] == -0.03
    assert config["invalidation"]["turnoverMultiplier"] == 0.8


def test_config_breadth_universe_follows_the_flag() -> None:
    narrow = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        breadth_universe=2,
        fixture=FIXTURES / "e2e.json",
    )
    wide = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        breadth_universe=4,
        fixture=FIXTURES / "e2e.json",
    )
    assert narrow["config"]["breadthUniverse"] == 2
    assert wide["config"]["breadthUniverse"] == 4
    assert narrow["reportId"] != wide["reportId"]


def test_report_id_is_stable_across_identical_runs() -> None:
    first = _e2e_result()
    second = _e2e_result()
    assert first["reportId"] == second["reportId"]
    assert len(first["reportId"]) == 16


def test_report_id_ignores_volatile_fields() -> None:
    result = _e2e_result()
    identity = result["reportId"]
    result["generatedAt"] = "2030-01-01T00:00:00+08:00"
    result["providerCalls"] = 999
    result["cacheState"] = "warm"
    result["credentialSource"] = "env:OTHER"
    assert contract.compute_report_id(result) == identity


def test_report_id_changes_when_thresholds_change() -> None:
    result = _e2e_result()
    identity = result["reportId"]
    result["config"]["minBreadthCoverage"] = 0.75
    assert contract.compute_report_id(result) != identity


def test_insufficient_result_carries_interface_fields() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        fixture=FIXTURES / "missing-benchmark.json",
    )
    assert result["status"] == "insufficient"
    assert result["schemaVersion"] == "1.0"
    assert result["config"]["breadthUniverse"] == sector_pipeline.DEFAULT_BREADTH_UNIVERSE
    assert len(result["reportId"]) == 16
    assert result["directions"] == []


def test_require_schema_version_refuses_old_payloads() -> None:
    with pytest.raises(ValueError, match="schemaVersion"):
        contract.require_schema_version({"asOf": "2026-11-13"})
    with pytest.raises(ValueError, match="不支持"):
        contract.require_schema_version({"schemaVersion": "0.9"})
    assert contract.require_schema_version({"schemaVersion": "1.0"}) == "1.0"


# ---------------------------------------------------------------- predicate


def test_confirmation_builder_shares_numbers_with_prose() -> None:
    built = predicate.build_confirmation(100.0, 2_000_000_000)
    assert built is not None
    assert built["horizonDays"] == 1
    assert [clause["field"] for clause in built["all"]] == ["close", "turnover"]
    assert built["all"][0]["value"] == 100.50
    assert built["all"][0]["op"] == ">="
    assert built["all"][1]["value"] == 2_000_000_000.0
    assert f"{built['all'][0]['value']:.2f}" in built["text"]
    assert f"{built['all'][1]['value']:.0f}" in built["text"]
    assert "+0.5%" in built["text"]
    assert all(clause["basis"] for clause in built["all"])


def test_invalidation_builder_shares_numbers_with_prose() -> None:
    built = predicate.build_invalidation(100.0, 2_000_000_000)
    assert built is not None
    assert built["all"][0] == {
        "field": "close",
        "op": "<",
        "value": 97.0,
        "basis": "referenceClose*0.97",
    }
    assert built["all"][1]["value"] == 1_600_000_000.0
    assert f"{built['all'][0]['value']:.2f}" in built["text"]
    assert f"{built['all'][1]['value']:.0f}" in built["text"]
    assert "-3%" in built["text"]


def test_predicate_builders_drop_turnover_clause_without_mean() -> None:
    assert len(predicate.build_confirmation(100.0, None)["all"]) == 1
    assert len(predicate.build_invalidation(100.0, 0)["all"]) == 1
    assert predicate.build_confirmation(None, 1e9) is None
    assert predicate.build_invalidation(None, 1e9) is None


def test_evaluate_returns_met_unmet_unknown() -> None:
    built = predicate.build_confirmation(100.0, 1_000_000_000)
    met = [{"date": "2026-11-16", "close": 101.0, "turnover": 1_100_000_000}]
    assert predicate.evaluate(built, met) == "met"
    weak_close = [{"date": "2026-11-16", "close": 99.0, "turnover": 1_100_000_000}]
    assert predicate.evaluate(built, weak_close) == "unmet"
    weak_turnover = [{"date": "2026-11-16", "close": 101.0, "turnover": 900_000_000}]
    assert predicate.evaluate(built, weak_turnover) == "unmet"
    missing_turnover = [{"date": "2026-11-16", "close": 101.0}]
    assert predicate.evaluate(built, missing_turnover) == "unknown"


def test_evaluate_missing_target_session_is_unknown_not_error() -> None:
    built = predicate.build_confirmation(100.0, 1_000_000_000)
    assert predicate.evaluate(built, []) == "unknown"
    assert predicate.evaluate(built, None) == "unknown"
    assert predicate.evaluate(None, []) == "unknown"
    delayed = {
        "text": "two sessions later",
        "horizonDays": 2,
        "all": [{"field": "close", "op": ">=", "value": 100.0, "basis": "test"}],
    }
    assert predicate.evaluate(delayed, [{"date": "2026-11-16", "close": 200.0}]) == "unknown"
    assert predicate.evaluate(delayed, [{"date": "2026-11-16", "close": 1.0}, {"date": "2026-11-17", "close": 200.0}]) == "met"


def test_evaluate_supports_pct_change_against_previous_bar() -> None:
    built = {
        "text": "pct",
        "horizonDays": 2,
        "all": [{"field": "pctChange", "op": ">=", "value": 0.01, "basis": "test"}],
    }
    bars = [{"date": "2026-11-16", "close": 100.0}, {"date": "2026-11-17", "close": 102.0}]
    assert predicate.evaluate(built, bars) == "met"
    assert predicate.evaluate(built, bars[:1]) == "unknown"
    assert predicate.evaluate(built, [{"date": "2026-11-16"}, {"date": "2026-11-17", "close": 102.0}]) == "unknown"


# ---------------------------------------------------------------- checker


def _compliant_article(result: dict) -> str:
    labels = {"high": "高", "medium": "中", "low": "低", "insufficient": "不足"}
    lines = [
        f"# {result['asOf']} 板块层定向",
        "",
        f"数据状态 {result['status']}。本次共 {len(result['directions'])} 个方向。",
        "",
    ]
    for index, direction in enumerate(result["directions"], 1):
        lines += [
            f"## {index}. {direction['name']} {direction['thscode']}",
            "",
            f"总分 {direction['totalScore']:.1f} ｜ 置信 {labels[direction['confidence']]} ｜ {direction['pool']}。",
            f"确认：{direction['confirmation']['text']}",
            f"失效：{direction['invalidation']['text']}",
            "",
        ]
    lines.append("> 数据来源 fuyao，不是买点，不构成买卖建议；所有阈值 needs-backtest。")
    return "\n".join(lines)


def _insufficient_article(result: dict) -> str:
    return "\n".join(
        [
            f"# {result['asOf']} 板块层定向",
            "",
            "数据状态 insufficient（数据不足）。本次不产出方向。",
            "原因：基准 000001.SH 当日没有日线，无法计算相对强度。",
            "",
            "> 不构成投资建议；所有阈值 needs-backtest。",
        ]
    )


def test_checker_passes_a_compliant_article() -> None:
    result = _e2e_result()
    verdict = check_report.validate(result, _compliant_article(result))
    assert verdict["status"] == "PASS", verdict["issues"]
    assert all(check["status"] == "pass" for check in verdict["checks"])


def test_checker_rejects_numbers_without_json_provenance() -> None:
    result = _e2e_result()
    article = _compliant_article(result) + "\n宽度 73.21%，量能 2.34×，成交额 1.23 亿。\n"
    verdict = check_report.validate(result, article)
    assert verdict["status"] == "FAIL"
    details = " ".join(issue["detail"] for issue in verdict["issues"])
    for token in ("73.21", "2.34", "1.23"):
        assert token in details
    assert all(issue["line"] for issue in verdict["issues"])


def test_checker_whitelists_small_integers() -> None:
    result = _e2e_result()
    article = _compliant_article(result).replace(
        "本次共",
        "按 3 个方向口径核对，观测 5 项指标；本次共",
    )
    verdict = check_report.validate(result, article)
    assert verdict["status"] == "PASS", verdict["issues"]


@pytest.mark.parametrize("word", ["买入", "加仓", "仓位", "必涨", "已验证", "目标价"])
def test_checker_rejects_each_forbidden_word(word: str) -> None:
    result = _e2e_result()
    verdict = check_report.validate(result, _compliant_article(result) + f"\n{word}\n")
    assert verdict["status"] == "FAIL"
    hits = [issue for issue in verdict["issues"] if issue["check"] == "forbiddenWording"]
    assert hits and word in hits[0]["detail"]
    assert hits[0]["line"] is not None and hits[0]["column"] is not None


def test_checker_requires_disclaimer() -> None:
    result = _e2e_result()
    article = _compliant_article(result).replace(
        "> 数据来源 fuyao，不是买点，不构成买卖建议；所有阈值 needs-backtest。",
        "> 数据来源 fuyao；所有阈值 needs-backtest。",
    )
    verdict = check_report.validate(result, article)
    assert verdict["status"] == "FAIL"
    assert any(issue["check"] == "requiredDisclaimer" for issue in verdict["issues"])


def test_checker_requires_backtest_marker() -> None:
    result = _e2e_result()
    article = _compliant_article(result).replace("needs-backtest", "待回测")
    verdict = check_report.validate(result, article)
    assert any(issue["detail"].startswith("缺少 needs-backtest") for issue in verdict["issues"])


def test_checker_requires_data_status() -> None:
    result = _e2e_result()
    article = _compliant_article(result).replace("数据状态 degraded", "数据状态正常")
    verdict = check_report.validate(result, article)
    assert any(issue["check"] == "requiredDataStatus" for issue in verdict["issues"])


def test_checker_requires_each_direction_confidence() -> None:
    result = _e2e_result()
    article = _compliant_article(result).replace("置信 中", "置信 高")
    verdict = check_report.validate(result, article)
    assert any(issue["check"] == "requiredConfidence" for issue in verdict["issues"])


def test_checker_insufficient_does_not_require_directions() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        fixture=FIXTURES / "missing-benchmark.json",
    )
    verdict = check_report.validate(result, _insufficient_article(result))
    assert verdict["status"] == "PASS", verdict["issues"]


def test_checker_insufficient_requires_reason() -> None:
    result = sector_pipeline.run_pipeline(
        as_of=date(2026, 11, 13),
        fixture=FIXTURES / "missing-benchmark.json",
    )
    article = _insufficient_article(result).replace("原因：基准 000001.SH 当日没有日线，无法计算相对强度。", "")
    verdict = check_report.validate(result, article)
    assert verdict["status"] == "FAIL"
    assert any(issue["check"] == "requiredNoDirectionReason" for issue in verdict["issues"])


def test_checker_rejects_result_without_schema_version() -> None:
    result = _e2e_result()
    result.pop("schemaVersion")
    verdict = check_report.validate(result, _compliant_article(result))
    assert verdict["status"] == "FAIL"
    assert any(issue["check"] == "schemaVersion" for issue in verdict["issues"])


def test_checker_is_deterministic_and_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def explode(*args, **kwargs):
        raise AssertionError("checker must not touch the network")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    result = _e2e_result()
    article = _compliant_article(result)
    first = check_report.validate(result, article)
    second = check_report.validate(result, article)
    assert first == second


def test_checker_cli_exit_codes(tmp_path: Path) -> None:
    result = _e2e_result()
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    article_path = tmp_path / "article.md"
    article_path.write_text(_compliant_article(result), encoding="utf-8")
    assert check_report.main(["--result", str(result_path), "--article", str(article_path)]) == 0

    article_path.write_text(_compliant_article(result) + "\n宽度 73.21%。\n", encoding="utf-8")
    assert check_report.main(["--result", str(result_path), "--article", str(article_path)]) == 1

    assert check_report.main(["--result", str(tmp_path / "missing.json"), "--article", str(article_path)]) == 2


def test_report_is_positioned_as_fact_skeleton() -> None:
    text = report.render_markdown(_e2e_result())
    assert "事实骨架" in text
    assert "不是对外主报告" in text
    assert "reportId" in text


def test_report_fallback_triggers_on_failed_article() -> None:
    result = _e2e_result()
    article = _compliant_article(result) + "\n宽度 73.21%。\n"
    verdict = check_report.validate(result, article)
    assert verdict["status"] == "FAIL"
    fallback = report.render_fallback(result, verdict["issues"])
    assert fallback.startswith("> 文章未通过校验，以下为事实骨架")
    assert "# 板块层定向事实骨架" in fallback
    assert "73.21" in fallback
