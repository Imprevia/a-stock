"""Orchestration for the active-industry scan Skill.

This module owns I/O and sequencing; every calculation it calls is a pure
function from ``quadrant``, ``percentile`` or ``industry_map``.

Degradation policy: each data source has an independent failure path, and no
single failure aborts the run.  Only "both rankings unavailable" is fatal,
because there is nothing left to report.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import contract
import fuyao_client
import industry_map
import percentile
import quadrant
import session
import sina_client
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

DEFAULT_TOP = 50
DEFAULT_CANDIDATE_POOL = 400
DEFAULT_MIN_LISTING_DAYS = 250
DEFAULT_LEVEL = 1
DEFAULT_TOP_SECTORS = 10
DEFAULT_BOARD_LIST_API = "881"

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_INSUFFICIENT = "insufficient"

PERCENTILE_DEFERRED_REASON = "当日累计量与历史全天分布不可比"

# THS board catalogue: level-1 codes start with 881, level-2 with 884.
LEVEL_PREFIX = {1: "881", 2: "884"}

CACHE_ROOT = Path(__file__).resolve().parent.parent / ".cache" / "active-industry-scan"


@dataclass
class Quality:
    """Tracks every degradation so the caller can see what was lost."""

    status: str = STATUS_OK
    degradations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def degrade(self, message: str) -> None:
        self.degradations.append(message)
        if self.status == STATUS_OK:
            self.status = STATUS_DEGRADED

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def insufficient(self, message: str) -> None:
        self.degradations.append(message)
        self.status = STATUS_INSUFFICIENT

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "degradations": list(self.degradations),
            "warnings": list(self.warnings),
        }


@dataclass
class ScanInputs:
    """Everything the pipeline needs, before any calculation."""

    as_of: date
    now: datetime
    amount_rows: list[sina_client.RankRow]
    turnover_rows: list[sina_client.RankRow]
    boards: list[industry_map.IndustryBoard] = field(default_factory=list)
    membership_date: date | None = None
    bars: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    missing_bars: list[str] = field(default_factory=list)
    history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    excluded_by_amount: list[dict[str, Any]] = field(default_factory=list)
    excluded_by_turnover: list[dict[str, Any]] = field(default_factory=list)
    missing_list_date: list[str] = field(default_factory=list)


def _symbol_lookup(
    client: fuyao_client.FuyaoClient,
    quality: Quality,
) -> dict[str, fuyao_client.SymbolInfo]:
    try:
        rows = client.list_symbols()
    except fuyao_client.FuyaoError as error:
        quality.degrade(f"上市日期不可用，新股过滤降级为不过滤: {error}")
        return {}
    if not rows:
        quality.degrade("上市日期返回为空，新股过滤降级为不过滤")
        return {}
    return {row.thscode: row for row in rows}


def _filtered_ranking(
    rows: Sequence[sina_client.RankRow],
    symbols: Mapping[str, fuyao_client.SymbolInfo],
    today: date,
    *,
    min_listing_days: int,
    top: int,
    sort_key: str,
    quality: Quality,
    label: str,
) -> tuple[list[sina_client.RankRow], list[dict[str, Any]], list[str]]:
    """Filter one candidate pool then truncate to ``top``.

    Filtering happens before truncation so the ranking stays at full size
    even when several high-turnover stocks are recent listings.
    """

    if not symbols:
        ranked = sina_client.rank(rows, sort_key, top=top)
        return ranked, [], []

    kept, excluded, missing = fuyao_client.filter_by_listing_age(
        rows, symbols, today, min_listing_days=min_listing_days
    )
    ranked = sina_client.rank(kept, sort_key, top=top)
    if len(ranked) < top:
        quality.degrade(
            f"{label}候选池过滤后仅 {len(ranked)} 只，不足 {top} 只"
        )
    if missing:
        quality.warn(f"{label}有 {len(missing)} 只缺少上市日期，已排除")
    return ranked, excluded, missing


def _summarize_rows(
    rows: Sequence[sina_client.RankRow],
    sort_key: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        out.append(
            {
                "rank": index,
                "code": row.thscode,
                "name": row.name,
                "amountYi": round(row.amount / 1e8, 2),
                "turnoverPct": round(row.turnover_pct, 4),
                "floatMvYi": round(row.float_mv_yi, 2),
                "changePct": round(row.change_pct, 2),
            }
        )
    return out


def _compute_intersection(
    amount_rows: Sequence[sina_client.RankRow],
    turnover_rows: Sequence[sina_client.RankRow],
    boards: Sequence[industry_map.IndustryBoard],
) -> list[dict[str, Any]]:
    """Stocks present on both rankings.

    Deliberately no threshold relaxation: when the two rankings do not
    overlap, the honest answer is an empty list.
    """

    amount_rank = {row.thscode: i for i, row in enumerate(amount_rows, start=1)}
    turnover_rank = {row.thscode: i for i, row in enumerate(turnover_rows, start=1)}
    shared = set(amount_rank) & set(turnover_rank)
    if not shared:
        return []

    name_by_code = {row.thscode: row.name for row in amount_rows}
    board_names: dict[str, str] = {}
    index = industry_map.build_member_index(boards)
    for board in boards:
        board_names[board.thscode] = board.name

    records: list[dict[str, Any]] = []
    for code in sorted(shared, key=lambda c: amount_rank[c]):
        codes = index.get(code) or []
        records.append(
            {
                "code": code,
                "name": name_by_code.get(code, ""),
                "amountRank": amount_rank[code],
                "turnoverRank": turnover_rank[code],
                "industries": [board_names.get(c, c) for c in codes],
            }
        )
    return records


def _percentile_block(
    rows: Sequence[sina_client.RankRow],
    history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    settled: bool,
) -> dict[str, Any]:
    """Relative-turnover block, or a deferred marker before settlement."""

    if not settled:
        return percentile.deferred(
            PERCENTILE_DEFERRED_REASON, _settlement_label()
        )
    per_code: dict[str, Any] = {}
    for row in rows:
        bars = history.get(row.thscode) or []
        series = [float(b.get("volume") or 0) for b in bars]
        result = percentile.evaluate(series)
        per_code[row.thscode] = {
            "status": result.status,
            "windowBars": result.window_bars,
            # Shares, not a percentage: history carries volume only.  The
            # amplification ratio is unit-free and stays valid.
            "baselineVolumeShares": _round(result.average_turnover),
            "amplification": _round(result.amplification),
            "percentile": _round(result.percentile),
        }
    return {"status": "computed", "byCode": per_code}


def _settlement_label() -> str:
    return session.settlement_time().strftime("%H:%M")


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def build_result(
    inputs: ScanInputs,
    *,
    top: int,
    candidate_pool: int,
    min_listing_days: int,
    level: int,
    top_sectors: int,
    quality: Quality,
    nonce: str = "",
) -> dict[str, Any]:
    """Assemble the full result document from prepared inputs."""

    identity = contract.build_contract(inputs.now, nonce=nonce)
    report = session.describe(inputs.now)

    amount_top = inputs.amount_rows[:top]
    turnover_top = inputs.turnover_rows[:top]

    industries: list[dict[str, Any]] = []
    levels = [1] if level == 1 else [2] if level == 2 else [1, 2]
    for one_level in levels:
        hits = industry_map.aggregate(
            inputs.boards, amount_top, turnover_top, level=one_level
        )
        industries.extend(hit.as_dict() for hit in hits[:top_sectors])

    intersection = _compute_intersection(amount_top, turnover_top, inputs.boards)

    percentiles = _percentile_block(
        turnover_top, inputs.history, settled=report.settled
    )

    candidate_codes = [
        item["code"] for item in industries if item["amountTopCount"] >= 2
    ]

    if report.early_snapshot:
        quality.warn(session.early_snapshot_warning())
    if report.state in {session.STATE_PREOPEN, session.STATE_LUNCH}:
        quality.warn(f"当前处于 {report.state}，行情已静止，榜单反映最近一个成交时刻")

    return {
        **identity.as_dict(),
        "asOf": inputs.now.isoformat(timespec="seconds"),
        **report.as_dict(),
        "turnoverBasis": "float-share",
        "filter": {
            "minListingDays": min_listing_days,
            "candidatePool": candidate_pool,
            "top": top,
        },
        "rankings": {
            "byAmount": _summarize_rows(amount_top, sina_client.RANK_BY_AMOUNT),
            "byTurnover": _summarize_rows(
                turnover_top, sina_client.RANK_BY_TURNOVER
            ),
        },
        "industries": industries,
        "intersection": intersection,
        "percentile": percentiles,
        "handoff": {
            "target": "a-stock-qts04-sector-direction",
            "candidateThscodes": candidate_codes,
            "note": "本 Skill 只做发现层，不评分；候选行业需由下游按 QTS-04-01-01 至 -05 打分",
        },
        "quality": quality.as_dict(),
        "disclaimer": (
            "四象限描述资金分布，不是买卖信号；全部规则状态 needs-backtest。"
        ),
    }


# --------------------------------------------------------------------------
# live collection
# --------------------------------------------------------------------------


def collect_live(
    *,
    now: datetime,
    candidate_pool: int,
    min_listing_days: int,
    level: int,
    top: int,
    quality: Quality,
    cache_root: Path | None = None,
    enable_bars: bool = True,
    enable_history: bool = True,
    client: fuyao_client.FuyaoClient | None = None,
) -> ScanInputs:
    """Fetch everything from the live providers, degrading where needed."""

    today = now.astimezone(SHANGHAI).date()
    fuyao = client or fuyao_client.FuyaoClient(cache_dir=cache_root)

    symbols = _symbol_lookup(fuyao, quality)

    amount_rows: list[sina_client.RankRow] = []
    turnover_rows: list[sina_client.RankRow] = []
    try:
        amount_rows = sina_client.fetch_sorted_pool(
            sina_client.RANK_BY_AMOUNT, pool_size=candidate_pool
        )
    except sina_client.SinaError as error:
        quality.degrade(f"成交额榜排序接口失败: {error}")
    try:
        turnover_rows = sina_client.fetch_sorted_pool(
            sina_client.RANK_BY_TURNOVER, pool_size=candidate_pool
        )
    except sina_client.SinaError as error:
        quality.degrade(f"换手率榜排序接口失败: {error}")

    if not amount_rows and not turnover_rows:
        quality.degrade("两个榜的排序接口均失败，改用全量快照本地重排")
        try:
            full = sina_client.fetch_full_snapshot()
        except sina_client.SinaError as error:
            quality.insufficient(f"全量快照也失败，无法产出榜单: {error}")
            return ScanInputs(today, now, [], [])
        amount_rows = sina_client.rank(full, sina_client.RANK_BY_AMOUNT, top=candidate_pool)
        turnover_rows = sina_client.rank(
            full, sina_client.RANK_BY_TURNOVER, top=candidate_pool
        )

    amount_kept, amount_excluded, amount_missing = _filtered_ranking(
        amount_rows, symbols, today,
        min_listing_days=min_listing_days, top=top,
        sort_key=sina_client.RANK_BY_AMOUNT, quality=quality, label="成交额榜",
    )
    turnover_kept, turnover_excluded, turnover_missing = _filtered_ranking(
        turnover_rows, symbols, today,
        min_listing_days=min_listing_days, top=top,
        sort_key=sina_client.RANK_BY_TURNOVER, quality=quality, label="换手率榜",
    )

    boards: list[industry_map.IndustryBoard] = []
    membership_date: date | None = None
    if level in (1, 2, "both"):
        boards, membership_date = _load_boards(
            fuyao, today, level, quality, cache_root
        )

    bars: dict[str, list[dict[str, Any]]] = {}
    missing_bars: list[str] = []
    if enable_bars:
        wanted = list({row.symbol for row in amount_kept + turnover_kept})
        bars, missing_bars = sina_client.fetch_klines(wanted)
        if missing_bars:
            quality.degrade(
                f"分时 K 线缺失 {len(missing_bars)}/{len(wanted)} 只，量能段不完整"
            )

    history: dict[str, list[dict[str, Any]]] = {}
    if enable_history and session.describe(now).settled:
        codes = [row.thscode for row in turnover_kept]
        try:
            history = fuyao.stock_history(
                codes, _history_start(today), today
            )
        except fuyao_client.FuyaoError as error:
            quality.degrade(f"历史日线不可用，分位段缺失: {error}")
    elif enable_history and not session.describe(now).settled:
        # Percentile is intentionally withheld intraday; not a degradation.
        pass

    return ScanInputs(
        as_of=today,
        now=now,
        amount_rows=amount_kept,
        turnover_rows=turnover_kept,
        boards=boards,
        membership_date=membership_date,
        bars=bars,
        missing_bars=missing_bars,
        history=history,
        excluded_by_amount=amount_excluded,
        excluded_by_turnover=turnover_excluded,
        missing_list_date=sorted(set(amount_missing) | set(turnover_missing)),
    )


def _history_start(today: date) -> date:
    return date(today.year - 1, today.month, today.day)


def _load_boards(
    client: fuyao_client.FuyaoClient,
    as_of: date,
    level: int | str,
    quality: Quality,
    cache_root: Path | None,
) -> tuple[list[industry_map.IndustryBoard], date | None]:
    root = cache_root or CACHE_ROOT
    levels = [1] if level == 1 else [2] if level == 2 else [1, 2]
    collected: list[industry_map.IndustryBoard] = []
    effective: date | None = None
    for one in levels:
        cached = industry_map.load_boards(root, as_of, one)
        if cached is not None:
            boards, cache_date = cached
            collected.extend(boards)
            effective = cache_date if effective is None else min(effective, cache_date)
            if cache_date != as_of:
                quality.degrade(
                    f"行业成分股使用 {cache_date.isoformat()} 缓存，非当日"
                )
            continue
        try:
            boards = _fetch_boards(client, one)
        except fuyao_client.FuyaoError as error:
            quality.insufficient(f"行业成分股不可用且无缓存（level {one}）: {error}")
            continue
        if not boards:
            quality.insufficient(f"行业成分股为空（level {one}）")
            continue
        industry_map.save_boards(root, as_of, one, boards)
        collected.extend(boards)
    return collected, effective


def _fetch_boards(
    client: fuyao_client.FuyaoClient,
    level: int,
) -> list[industry_map.IndustryBoard]:
    """Fetch a board catalogue and its membership.

    The catalogue itself comes from ``index list``; membership needs one call
    per board, so this is the expensive path that the cache exists to avoid.
    """

    data = client.call(
        ["index", "catalog", "--tag", "industry", "--format", "json"]
    )
    items = data.get("item")
    if not isinstance(items, list):
        return []
    prefix = LEVEL_PREFIX.get(level, "881")
    boards: list[industry_map.IndustryBoard] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("thscode") or "").strip()
        if not code.startswith(prefix):
            continue
        try:
            members = client.index_constituents(code)
        except fuyao_client.FuyaoError:
            members = []
        boards.append(
            industry_map.IndustryBoard(
                thscode=code,
                name=str(item.get("name") or "").strip(),
                level=level,
                members=tuple(members),
            )
        )
    return boards


# --------------------------------------------------------------------------
# fixture path
# --------------------------------------------------------------------------


def load_fixture(path: Path) -> tuple[ScanInputs, dict[str, Any]]:
    """Build inputs from a JSON fixture, with no network access at all."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("fixture 必须是 JSON 对象")

    raw_now = payload.get("now") or payload.get("asOf") or "2026-11-19T10:30:00+08:00"
    now = datetime.fromisoformat(str(raw_now))
    if now.tzinfo is None:
        now = now.replace(tzinfo=SHANGHAI)
    today = now.astimezone(SHANGHAI).date()

    def rows(key: str) -> list[sina_client.RankRow]:
        out: list[sina_client.RankRow] = []
        for item in payload.get(key) or []:
            if not isinstance(item, Mapping):
                continue
            parsed = sina_client.parse_row(item)
            if parsed is not None:
                out.append(parsed)
        return out

    boards: list[industry_map.IndustryBoard] = []
    for item in payload.get("boards") or []:
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("thscode") or "").strip()
        if not code:
            continue
        boards.append(
            industry_map.IndustryBoard(
                thscode=code,
                name=str(item.get("name") or "").strip(),
                level=int(item.get("level") or 1),
                members=tuple(item.get("members") or ()),
            )
        )

    history: dict[str, list[dict[str, Any]]] = {}
    for code, bars in (payload.get("history") or {}).items():
        if isinstance(bars, list):
            history[str(code)] = [b for b in bars if isinstance(b, Mapping)]

    options = payload.get("options") or {}
    inputs = ScanInputs(
        as_of=today,
        now=now,
        amount_rows=rows("byAmount"),
        turnover_rows=rows("byTurnover"),
        boards=boards,
        history=history,
    )
    return inputs, dict(options) if isinstance(options, Mapping) else {}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A 股盘中活跃行业扫描：双榜 + 行业聚合 + 四象限 + 交集"
    )
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    parser.add_argument(
        "--candidate-pool", type=int, default=DEFAULT_CANDIDATE_POOL
    )
    parser.add_argument(
        "--min-listing-days", type=int, default=DEFAULT_MIN_LISTING_DAYS
    )
    parser.add_argument(
        "--level", choices=("1", "2", "both"), default=str(DEFAULT_LEVEL)
    )
    parser.add_argument("--top-sectors", type=int, default=DEFAULT_TOP_SECTORS)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    parser.add_argument("--fixture", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--no-bars", action="store_true")
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--now", type=str, default=None, help="覆盖当前时刻（测试用）")
    return parser.parse_args(argv)


def _level_value(raw: str) -> int | str:
    return "both" if raw == "both" else int(raw)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    quality = Quality()

    wall_clock = datetime.now(tz=SHANGHAI)
    if args.now:
        now = datetime.fromisoformat(args.now)
        if now.tzinfo is None:
            now = now.replace(tzinfo=SHANGHAI)
        # `--now` moves the label, never the data: the provider only returns
        # a snapshot of *its* call moment.  Say so instead of implying replay.
        drift = abs((wall_clock - now).total_seconds())
        if drift > 60:
            quality.warn(
                f"--now 指定 {now.strftime('%H:%M')}，但实际调用时刻为 "
                f"{wall_clock.strftime('%H:%M')}；榜单数据取自实际调用时刻，"
                "本参数只改变时点标签，不能回溯历史快照"
            )
    else:
        now = wall_clock

    level = _level_value(args.level)

    if args.fixture is not None:
        inputs, options = load_fixture(args.fixture)
        top = int(options.get("top", args.top))
        pool = int(options.get("candidatePool", args.candidate_pool))
        min_days = int(options.get("minListingDays", args.min_listing_days))
        top_sectors = int(options.get("topSectors", args.top_sectors))
        forced = options.get("qualityStatus")
        if forced:
            quality.status = str(forced)
        for message in options.get("degradations") or []:
            quality.degrade(str(message))
    else:
        inputs = collect_live(
            now=now,
            candidate_pool=args.candidate_pool,
            min_listing_days=args.min_listing_days,
            level=level,
            top=args.top,
            quality=quality,
            cache_root=args.cache_dir,
            enable_bars=not args.no_bars,
            enable_history=not args.no_history,
        )
        top = args.top
        pool = args.candidate_pool
        min_days = args.min_listing_days
        top_sectors = args.top_sectors

    if not inputs.amount_rows and not inputs.turnover_rows:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "两个榜均无数据，无法产出结果",
                    "quality": quality.as_dict(),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    result = build_result(
        inputs,
        top=top,
        candidate_pool=pool,
        min_listing_days=min_days,
        level=level if isinstance(level, int) else 0,
        top_sectors=top_sectors,
        quality=quality,
    )

    result["excluded"] = {
        "byTurnover": list(inputs.excluded_by_turnover),
        "byAmount": list(inputs.excluded_by_amount),
        "missingListDate": inputs.missing_list_date,
    }
    if inputs.membership_date is not None:
        result["industryMembershipDate"] = inputs.membership_date.isoformat()

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)

    if args.markdown is not None:
        import report as report_module

        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(report_module.render(result), encoding="utf-8")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())