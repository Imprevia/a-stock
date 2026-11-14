"""QTS-04 STEP 1 sector-direction pipeline.

Orchestrates: industry catalog -> industry bars -> benchmark bars -> four
metrics -> provisional ranking -> breadth for the top N -> full scoring ->
quadrant -> directions with confirmation and invalidation levels.

Every failure path downgrades instead of inventing data.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from sector_contract import attach_interface  # noqa: E402
from predicate import build_confirmation, build_invalidation  # noqa: E402
from cache import (  # noqa: E402
    CACHE_STATE_COLD,
    KIND_INDUSTRY,
    KIND_STOCK,
    BarCache,
    default_cache_dir,
)
from fuyao_client import (  # noqa: E402
    FuyaoClient,
    FuyaoDegraded,
    FuyaoError,
    FuyaoInsufficient,
)
from scoring import (  # noqa: E402
    MIN_BREADTH_COVERAGE,
    RULE_WEIGHTS,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    Bar,
    Metric,
    advance_ratio,
    build_metrics,
    has_session,
    member_ma20,
    confidence_from_metrics,
    normalize_weights,
    persistence_metric,
    pool_state,
    quadrant,
    relative_strength,
    slice_until,
    total_score,
    turnover_ratio,
)
from report import default_report_path, render_markdown  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")

BENCHMARK_CODE = "000001.SH"
DEFAULT_BREADTH_UNIVERSE = 30
HISTORY_SESSIONS = 300
HISTORY_CALENDAR_DAYS = 450
SETTLEMENT = clock_time(15, 10)
RULE_VERSION = "0.1"
DISCLAIMER = "以上为观察候选与剧本，不是买点；不构成买卖建议。所有阈值状态为 needs-backtest。"


def today_shanghai() -> date:
    return datetime.now(SHANGHAI).date()


def now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


def resolve_as_of(raw: str | None, *, now: datetime | None = None) -> tuple[date, list[str]]:
    """Resolve a target session and refuse dates that cannot be complete."""

    current = now or now_shanghai()
    warnings: list[str] = []
    if raw:
        try:
            target = date.fromisoformat(raw)
        except ValueError as error:
            raise FuyaoInsufficient(f"--as-of 不是合法日期：{raw}") from error
    else:
        target = current.date()
        if current.time() < SETTLEMENT:
            target = target - timedelta(days=1)
            warnings.append("未到 15:10 结算时间，已回退到上一自然日；请在休市确认后指定 --as-of")
    if target > current.date():
        raise FuyaoInsufficient(f"目标日期 {target} 晚于今天 {current.date()}，无法取数")
    if target == current.date() and current.time() < SETTLEMENT:
        raise FuyaoInsufficient(f"目标日期 {target} 尚未收盘结算（15:10 之前）")
    return target, warnings


@dataclass
class IndustryInputs:
    thscode: str
    name: str
    bars: list[Bar] = field(default_factory=list)
    members: dict[str, list[Bar]] = field(default_factory=dict)


def _load_fixture(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise FuyaoInsufficient(f"无法读取 fixture：{error}") from error
    except json.JSONDecodeError as error:
        raise FuyaoInsufficient(f"fixture 不是合法 JSON：{error}") from error
    if not isinstance(payload, Mapping):
        raise FuyaoInsufficient("fixture 顶层必须是对象")
    return dict(payload)


def _bars_from_fixture(rows: Sequence[Mapping[str, Any]]) -> list[Bar]:
    from scoring import normalize_bars

    normalized: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if "date_ms" in row:
            normalized.append(row)
            continue
        raw_date = row.get("date")
        if not isinstance(raw_date, str):
            continue
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError:
            continue
        millis = int(datetime(parsed.year, parsed.month, parsed.day, tzinfo=SHANGHAI).timestamp() * 1000)
        normalized.append(
            {
                "date_ms": millis,
                "open_price": row.get("open"),
                "high_price": row.get("high"),
                "low_price": row.get("low"),
                "close_price": row.get("close"),
                "turnover": row.get("turnover"),
                "volume": row.get("volume"),
            }
        )
    return normalize_bars(normalized)


def _fetch_industries(client: FuyaoClient, cache: BarCache, target: date) -> list[IndustryInputs]:
    catalog = client.list_industries()
    start = target - timedelta(days=HISTORY_CALENDAR_DAYS)
    codes = [row["thscode"] for row in catalog]
    fetched = client.industry_history_batch(codes, start, target)
    for code, bars in fetched.items():
        cache.save(KIND_INDUSTRY, code, bars)
    result: list[IndustryInputs] = []
    for row in catalog:
        bars = cache.load(KIND_INDUSTRY, row["thscode"])
        result.append(IndustryInputs(thscode=row["thscode"], name=row["name"], bars=slice_until(bars, target)))
    return result


def _fetch_benchmark(client: FuyaoClient, cache: BarCache, target: date) -> list[Bar]:
    start = target - timedelta(days=HISTORY_CALENDAR_DAYS)
    cached = cache.load(KIND_INDUSTRY, BENCHMARK_CODE)
    if not has_session(cached, target):
        fetched = client.industry_history_batch([BENCHMARK_CODE], start, target)
        if BENCHMARK_CODE in fetched:
            cache.save(KIND_INDUSTRY, BENCHMARK_CODE, fetched[BENCHMARK_CODE])
    return slice_until(cache.load(KIND_INDUSTRY, BENCHMARK_CODE), target)


def _provisional_score(bars: Sequence[Bar], benchmark: Sequence[Bar], target: date) -> float | None:
    """Rank industries before breadth using the three bar-only metrics."""

    from scoring import percentile_score, rolling_midrank

    scores: list[tuple[float, int | None]] = []
    weight_sum = 0.0
    for rule_id, window in (("QTS-04-01-01", 5), ("QTS-04-01-02", 20)):
        current, history = relative_strength(bars, benchmark, window)
        percentile, _, _ = rolling_midrank(current, history)
        weight = dict((rule, item) for rule, _, item in RULE_WEIGHTS)[rule_id]
        score = percentile_score(percentile)
        if score is not None:
            scores.append((weight, score))
            weight_sum += weight
    current, history = turnover_ratio(bars, 20)
    percentile, _, _ = rolling_midrank(current, history)
    score = percentile_score(percentile)
    if score is not None:
        scores.append((0.20, score))
        weight_sum += 0.20
    value, _, status, _ = persistence_metric(bars, benchmark)
    if status != STATUS_INSUFFICIENT and value is not None:
        scores.append((0.20, int(round(value))))
        weight_sum += 0.20
    if not scores or weight_sum <= 0:
        return None
    return sum(weight * score for weight, score in scores) / weight_sum


def _build_direction(
    industry: IndustryInputs,
    benchmark: Sequence[Bar],
    target: date,
) -> dict[str, Any]:
    metrics = build_metrics(
        sector=industry.bars,
        benchmark=benchmark,
        member_bars=industry.members or None,
        as_of=target,
    )
    normalize_weights(metrics)
    total = total_score(metrics)
    confidence = confidence_from_metrics(metrics)
    by_name = {metric.name: metric for metric in metrics}
    persistence_score = by_name["persistence"].score
    rs5 = by_name["relative_strength_5"].value
    turnover_value = by_name["turnover_ratio"].value
    advance = advance_ratio(industry.members, target) if industry.members else None
    quadrant_value = quadrant(
        turnover_ratio_value=turnover_value,
        relative_strength_5=rs5,
        advance=advance,
    )
    close = industry.bars[-1].close if industry.bars else None
    turnovers = [bar.turnover for bar in industry.bars[-21:-1]]
    turnover_mean = (
        sum(value for value in turnovers if value is not None) / len([v for v in turnovers if v is not None])
        if any(value is not None for value in turnovers)
        else None
    )
    # Prose and predicate come from one call so they cannot drift apart.
    confirmation = build_confirmation(close, turnover_mean)
    invalidation = build_invalidation(close, turnover_mean)
    return {
        "thscode": industry.thscode,
        "name": industry.name,
        "asOf": target.isoformat(),
        "totalScore": None if total is None else round(total, 2),
        "confidence": confidence,
        "persistenceScore": persistence_score,
        "pool": pool_state(total, persistence_score),
        "quadrant": quadrant_value,
        "metrics": [metric.to_dict() for metric in metrics],
        "confirmation": confirmation,
        "invalidation": invalidation,
        "ruleVersion": RULE_VERSION,
        "calibration": "needs-backtest",
    }


def run_pipeline(
    *,
    as_of: date,
    breadth_universe: int = DEFAULT_BREADTH_UNIVERSE,
    cache_dir: Path | None = None,
    fixture: Path | None = None,
    client: FuyaoClient | None = None,
    env_file: Path | None = None,
    max_directions: int = 3,
) -> dict[str, Any]:
    """Execute the pipeline and return a structured, JSON-serializable result."""

    cache = BarCache(cache_dir or default_cache_dir())
    warnings: list[str] = []
    source = "fuyao"
    cache_state = CACHE_STATE_COLD
    worker: FuyaoClient | None = None

    if fixture is not None:
        payload = _load_fixture(fixture)
        source = "fixture"
        target = date.fromisoformat(str(payload.get("asOf") or as_of.isoformat()))
        industries_raw = payload.get("industries") or []
        industry_bars_raw = payload.get("industryBars") or {}
        benchmark_bars = _bars_from_fixture(payload.get("benchmarkBars") or [])
        constituents_raw = payload.get("constituents") or {}
        stock_bars_raw = payload.get("stockBars") or {}
        industries: list[IndustryInputs] = []
        for row in industries_raw:
            if not isinstance(row, Mapping):
                continue
            code = str(row.get("thscode") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            if not code:
                continue
            bars = _bars_from_fixture(industry_bars_raw.get(code) or [])
            members: dict[str, list[Bar]] = {}
            for member in constituents_raw.get(code) or []:
                member_code = str(member).strip().upper()
                if not member_code:
                    continue
                members[member_code] = _bars_from_fixture(stock_bars_raw.get(member_code) or [])
            industries.append(
                IndustryInputs(
                    thscode=code,
                    name=name or code,
                    bars=slice_until(bars, target),
                    members={key: slice_until(value, target) for key, value in members.items()},
                )
            )
        cache_state = "fixture"
        as_of = target
    else:
        worker = client or FuyaoClient(env_file=env_file)
        try:
            worker.check_prerequisites()
        except FuyaoInsufficient as error:
            return _insufficient(as_of, str(error), warnings, source, breadth_universe)
        benchmark_bars = _fetch_benchmark(worker, cache, as_of)
        if not has_session(benchmark_bars, as_of):
            return _insufficient(
                as_of,
                f"基准 {BENCHMARK_CODE} 在 {as_of} 没有日线，无法计算相对强度",
                warnings,
                source,
                breadth_universe,
            )
        try:
            industries = _fetch_industries(worker, cache, as_of)
        except FuyaoError as error:
            return _insufficient(as_of, str(error), warnings, source, breadth_universe)
        cache_state = cache.cache_state(KIND_INDUSTRY, [item.thscode for item in industries], as_of)

    if not industries:
        return _insufficient(as_of, "目标日期没有可用的行业板块", warnings, source, breadth_universe)
    if not has_session(benchmark_bars, as_of):
        return _insufficient(as_of, f"基准 {BENCHMARK_CODE} 在 {as_of} 没有日线", warnings, source, breadth_universe)

    usable = [item for item in industries if has_session(item.bars, as_of)]
    missing = len(industries) - len(usable)
    if missing:
        warnings.append(f"{missing} 个行业在目标日期没有日线，已排除")
    if not usable:
        return _insufficient(as_of, f"没有任何行业在 {as_of} 有日线", warnings, source, breadth_universe)

    ranked = sorted(
        ((item, _provisional_score(item.bars, benchmark_bars, as_of)) for item in usable),
        key=lambda pair: (-(pair[1] if pair[1] is not None else -1), pair[0].thscode),
    )
    selected = [item for item, score in ranked[: max(0, breadth_universe)] if score is not None]
    if fixture is None:
        _attach_breadth(selected, worker or FuyaoClient(), cache, as_of, warnings)

    directions: list[dict[str, Any]] = []
    excluded_by_coverage = 0
    excluded_by_score = 0
    for industry in chosen_with_breadth(selected):
        direction = _build_direction(industry, benchmark_bars, as_of)
        breadth_metric = next(
            (metric for metric in direction["metrics"] if metric["ruleId"] == "QTS-04-01-04"), None
        )
        if breadth_metric and breadth_metric["missingReason"] == "constituent-coverage-below-70%":
            excluded_by_coverage += 1
            continue
        if direction["totalScore"] is None or direction["totalScore"] < 50:
            excluded_by_score += 1
            continue
        directions.append(direction)

    directions.sort(key=lambda item: (-(item["totalScore"] or 0), item["thscode"]))
    directions = directions[:max_directions]

    status = _overall_status(directions, warnings)
    result = {
        "asOf": as_of.isoformat(),
        "generatedAt": now_shanghai().isoformat(),
        "status": status,
        "source": source,
        "benchmark": BENCHMARK_CODE,
        "breadthUniverse": breadth_universe,
        "breadthUniverseUsed": len(selected),
        "cacheState": cache_state,
        "credentialSource": worker.credential_source if worker is not None else "fixture",
        "quality": {
            "status": status,
            "industriesTotal": len(industries),
            "industriesUsable": len(usable),
            "industriesMissing": missing,
            "excludedByCoverage": excluded_by_coverage,
            "excludedByScore": excluded_by_score,
            "minBreadthCoverage": MIN_BREADTH_COVERAGE,
            "warnings": warnings,
        },
        "directions": directions,
        "ruleVersion": RULE_VERSION,
        "calibration": "needs-backtest",
        "disclaimer": DISCLAIMER,
        "providerCalls": len(worker.calls) if worker is not None else 0,
    }
    return attach_interface(result, breadth_universe)


def chosen_with_breadth(selected: Sequence[IndustryInputs]) -> list[IndustryInputs]:
    return list(selected)


def _attach_breadth(
    selected: Sequence[IndustryInputs],
    client: FuyaoClient,
    cache: BarCache,
    target: date,
    warnings: list[str],
) -> None:
    start = target - timedelta(days=HISTORY_CALENDAR_DAYS)
    for industry in selected:
        try:
            members = client.constituents(industry.thscode)
        except FuyaoError as error:
            warnings.append(f"{industry.thscode} 成分股取数失败，宽度记为不足：{error}")
            continue
        if not members:
            warnings.append(f"{industry.thscode} 没有成分股，宽度记为不足")
            continue
        codes = [row["thscode"] for row in members]
        missing = [code for code in codes if not has_session(cache.load(KIND_STOCK, code), target)]
        if missing:
            try:
                fetched = client.stock_history_batch(missing, start, target)
            except FuyaoError as error:
                warnings.append(f"{industry.thscode} 成分股日线取数失败：{error}")
                fetched = {}
            for code, bars in fetched.items():
                cache.save(KIND_STOCK, code, bars)
        industry.members = {code: slice_until(cache.load(KIND_STOCK, code), target) for code in codes}


def _overall_status(directions: Sequence[Mapping[str, Any]], warnings: Sequence[str]) -> str:
    if not directions:
        return STATUS_INSUFFICIENT
    if warnings:
        return "degraded"
    for direction in directions:
        for metric in direction.get("metrics", []):
            if metric.get("status") == STATUS_INSUFFICIENT:
                return "degraded"
    return STATUS_OK


def _insufficient(
    as_of: date,
    reason: str,
    warnings: Sequence[str],
    source: str,
    breadth_universe: int = DEFAULT_BREADTH_UNIVERSE,
) -> dict[str, Any]:
    return attach_interface({
        "asOf": as_of.isoformat(),
        "generatedAt": now_shanghai().isoformat(),
        "status": STATUS_INSUFFICIENT,
        "source": source,
        "benchmark": BENCHMARK_CODE,
        "directions": [],
        "quality": {
            "status": STATUS_INSUFFICIENT,
            "warnings": list(warnings) + [reason],
        },
        "ruleVersion": RULE_VERSION,
        "calibration": "needs-backtest",
        "disclaimer": DISCLAIMER,
    }, breadth_universe)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QTS-04 STEP 1 板块层定向")
    parser.add_argument("--as-of", dest="as_of", default=None, help="目标交易日 YYYY-MM-DD")
    parser.add_argument(
        "--breadth-universe",
        dest="breadth_universe",
        type=int,
        default=DEFAULT_BREADTH_UNIVERSE,
        help=f"计算宽度的行业数量上限（默认 {DEFAULT_BREADTH_UNIVERSE}）",
    )
    parser.add_argument("--cache-dir", dest="cache_dir", type=Path, default=None)
    parser.add_argument(
        "--env-file",
        dest="env_file",
        type=Path,
        default=None,
        help="fuyao 凭据文件（默认自动查找 deploy/truenas/deploy.env 中的 FUYAO_API_KEY）",
    )
    parser.add_argument("--fixture", type=Path, default=None, help="离线 fixture JSON")
    parser.add_argument("--output", type=Path, default=None, help="JSON 结果写入路径（唯一事实源）")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="事实骨架 Markdown 写入路径（agent 撰文底稿/无模型兜底，非对外主报告；给 --output 时默认写到同名 .md）",
    )
    parser.add_argument(
        "--format",
        dest="format",
        choices=("json", "markdown", "both"),
        default="json",
        help="stdout 输出格式（默认 json；markdown 打印事实骨架，仅作底稿或兜底）",
    )
    args = parser.parse_args(argv)

    try:
        target, warnings = resolve_as_of(args.as_of)
        result = run_pipeline(
            as_of=target,
            breadth_universe=args.breadth_universe,
            cache_dir=args.cache_dir,
            fixture=args.fixture,
            env_file=args.env_file,
        )
        result["quality"].setdefault("warnings", [])
        result["quality"]["warnings"] = list(warnings) + list(result["quality"]["warnings"])
    except FuyaoError as error:
        result = {
            "asOf": args.as_of,
            "status": error.status,
            "directions": [],
            "quality": {"status": error.status, "warnings": [str(error)]},
            "calibration": "needs-backtest",
        }
        attach_interface(result, args.breadth_universe)

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    markdown = render_markdown(result)

    written: dict[str, Any] = {"status": result.get("status")}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        written["output"] = str(args.output)
    report_path = args.report or (default_report_path(args.output) if args.output else None)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(markdown if markdown.endswith("\n") else markdown + "\n", encoding="utf-8")
        written["report"] = str(report_path)

    if args.format == "json":
        print(json.dumps(written, ensure_ascii=False, sort_keys=True) if args.output else text)
    elif args.format == "markdown":
        print(markdown)
    else:
        print(text)
        print()
        print(markdown)
    return 0 if result.get("status") in {STATUS_OK, "degraded"} else 1


if __name__ == "__main__":
    raise SystemExit(main())