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
import direction
import fuyao_client
import history
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
    # Direction evidence.  ``market`` carries per-stock changes and volumes for
    # the whole market; ``board_changes`` carries one value per board.  Both
    # default to empty so a fixture without them still builds a valid document
    # with direction fields explicitly unavailable.
    market: fuyao_client.MarketSnapshot | None = None
    board_changes: dict[str, float | None] = field(default_factory=dict)


def _symbol_lookup(
    client: fuyao_client.FuyaoClient,
    quality: Quality,
) -> dict[str, fuyao_client.SymbolInfo]:
    """Listing dates keyed by thscode, or ``{}`` when filtering cannot run.

    Two distinct failures collapse to the same "do not filter" outcome:

    * the call failed, or returned nothing — nothing to filter on;
    * the call succeeded but *every* record lacks ``list_date``.  On 2026-11-20
      the upstream returned 5584 rows with ``list_date: null`` on all of them.
      Treating each as "missing" would empty the candidate pool and exit 2 for
      the whole Skill, so the capability is declared unavailable instead and
      the run continues with an explicit warning.  A *single* missing date
      still excludes just that stock; only a wholesale gap fails open.
    """

    try:
        rows = client.list_symbols()
    except fuyao_client.FuyaoError as error:
        quality.degrade(f"上市日期不可用，新股过滤降级为不过滤: {error}")
        return {}
    if not rows:
        quality.degrade("上市日期返回为空，新股过滤降级为不过滤")
        return {}

    dated = [row for row in rows if row.list_date is not None]
    if not dated:
        quality.degrade(
            f"上市日期字段整体缺失（{len(rows)} 条记录均无 list_date），"
            "本次未执行新股过滤"
        )
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
    market_median: float | None = None,
) -> list[dict[str, Any]]:
    """Render one ranking with its per-stock direction.

    Direction is appended, never used to reorder: the ranking still answers
    "who traded the most", and the direction column answers "and did they rise
    or fall".  Each row's own amount is used as the suspension hint: a row with
    zero traded value cannot have a real move, so it must not be counted flat.
    """

    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        verdict = direction.classify_direction(row.change_pct, volume=row.amount)
        out.append(
            {
                "rank": index,
                "code": row.thscode,
                "name": row.name,
                "amountYi": round(row.amount / 1e8, 2),
                "turnoverPct": round(row.turnover_pct, 4),
                "floatMvYi": round(row.float_mv_yi, 2),
                "changePct": round(row.change_pct, 2),
                "direction": verdict,
                "relativeToMarketPct": _round(
                    direction.relative_to_market(row.change_pct, market_median)
                ),
            }
        )
    return out


def _compute_intersection(
    amount_rows: Sequence[sina_client.RankRow],
    turnover_rows: Sequence[sina_client.RankRow],
    boards: Sequence[industry_map.IndustryBoard],
    market_median: float | None = None,
) -> list[dict[str, Any]]:
    """Stocks present on both rankings.

    Deliberately no threshold relaxation: when the two rankings do not
    overlap, the honest answer is an empty list.  Direction is appended for
    reading convenience; it never adds or removes a member.
    """

    amount_rank = {row.thscode: i for i, row in enumerate(amount_rows, start=1)}
    turnover_rank = {row.thscode: i for i, row in enumerate(turnover_rows, start=1)}
    shared = set(amount_rank) & set(turnover_rank)
    if not shared:
        return []

    change_by_code = {row.thscode: row.change_pct for row in amount_rows}
    amount_by_code = {row.thscode: row.amount for row in amount_rows}
    name_by_code = {row.thscode: row.name for row in amount_rows}
    board_names: dict[str, str] = {}
    index = industry_map.build_member_index(boards)
    for board in boards:
        board_names[board.thscode] = board.name

    records: list[dict[str, Any]] = []
    for code in sorted(shared, key=lambda c: amount_rank[c]):
        codes = index.get(code) or []
        change = change_by_code.get(code)
        records.append(
            {
                "code": code,
                "name": name_by_code.get(code, ""),
                "amountRank": amount_rank[code],
                "turnoverRank": turnover_rank[code],
                "industries": [board_names.get(c, c) for c in codes],
                "changePct": None if change is None else round(change, 2),
                "direction": direction.classify_direction(
                    change, volume=amount_by_code.get(code)
                ),
                "relativeToMarketPct": _round(
                    direction.relative_to_market(change, market_median)
                ),
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


def _market_baseline(
    market: fuyao_client.MarketSnapshot | None,
) -> dict[str, Any]:
    """Whole-market direction baseline, or an explicit unavailable block.

    This is the denominator every relative field is measured against, so it is
    published verbatim and labelled with its source.  When no market data was
    obtained the block says so instead of reporting a zero median.
    """

    if market is None or not market.changes:
        return {
            "status": "insufficient",
            "source": (market.source if market else "unavailable") or "unavailable",
            "universe": 0,
            "validCount": 0,
            "suspendedCount": 0,
            "upCount": 0,
            "downCount": 0,
            "flatCount": 0,
            "medianChangePct": None,
            "coverage": None,
            "reason": "全市场快照不可用，相对方向无法计算",
        }

    breadth = direction.aggregate_breadth(
        list(market.changes),
        market.changes,
        volumes=market.volumes,
        declared_count=market.total or None,
    )
    return {
        "status": breadth.status,
        "source": market.source,
        "universe": breadth.member_count,
        "validCount": breadth.valid_count,
        "suspendedCount": breadth.suspended_count,
        "upCount": breadth.up_count,
        "downCount": breadth.down_count,
        "flatCount": breadth.flat_count,
        "medianChangePct": _round(breadth.median_change_pct),
        "coverage": _round(breadth.coverage),
        "timestamp": market.timestamp,
    }


def _industry_direction(
    *,
    member_breadth: direction.Breadth,
    board_change: float | None,
    hit_counts: Mapping[str, int],
) -> tuple[str | None, str]:
    """Pick one direction for a board and say which evidence decided it.

    Priority is member median (equal weight, the same basis as the market
    benchmark), then the board index (capitalisation weighted), then the
    majority of ranking hits.  Recording the basis keeps a width-based verdict
    distinguishable from an index-based one instead of blending them into an
    unexplained label.
    """

    if member_breadth.median_change_pct is not None:
        return direction.classify_direction(member_breadth.median_change_pct), "member-median"
    if board_change is not None:
        return direction.classify_direction(board_change), "board-index"
    majority = direction.majority_direction(hit_counts)
    if majority is not None:
        return majority, "hit-majority"
    return None, "unavailable"


def _decorate_industries(
    industries: Sequence[dict[str, Any]],
    inputs: ScanInputs,
    amount_top: Sequence[sina_client.RankRow],
    turnover_top: Sequence[sina_client.RankRow],
    market_median: float | None,
) -> list[dict[str, Any]]:
    """Append the three direction evidence sets to every industry record.

    Only fields are added; the incoming list order — which encodes the
    activity ranking — is preserved exactly.
    """

    boards_by_code = {board.thscode: board for board in inputs.boards}
    # The ranking rows carry their own change, so hit direction never depends
    # on the market snapshot being available.  The market map is layered on top
    # to cover members outside the two rankings.
    changes: dict[str, float | None] = (
        dict(inputs.market.changes) if inputs.market else {}
    )
    volumes: dict[str, float | None] = (
        dict(inputs.market.volumes) if inputs.market else {}
    )
    for rows in (amount_top, turnover_top):
        for row in rows:
            changes[row.thscode] = row.change_pct
    member_index = industry_map.build_member_index(inputs.boards)

    # Union of both rankings per board, so a stock on both is counted once.
    hit_codes_by_board: dict[str, set[str]] = {}
    for rows in (amount_top, turnover_top):
        for row in rows:
            for board_code in member_index.get(row.thscode, ()):
                hit_codes_by_board.setdefault(board_code, set()).add(row.thscode)

    decorated: list[dict[str, Any]] = []
    for item in industries:
        board = boards_by_code.get(item["code"])
        hit_codes = sorted(hit_codes_by_board.get(item["code"], set()))
        hit_counts = direction.count_directions(hit_codes, changes, volumes=volumes)
        members = board.members if board is not None else ()
        member_breadth = direction.aggregate_breadth(members, changes, volumes=volumes)
        board_change = inputs.board_changes.get(item["code"])
        verdict, basis = _industry_direction(
            member_breadth=member_breadth,
            board_change=board_change,
            hit_counts=hit_counts,
        )

        record = dict(item)
        record.update(
            {
                "direction": verdict,
                "directionBasis": basis,
                "tag": direction.composite_tag(item["quadrant"], verdict),
                "boardChangePct": _round(board_change),
                "boardDirection": (
                    None if board_change is None
                    else direction.classify_direction(board_change)
                ),
                "hitUpCount": hit_counts["up"],
                "hitDownCount": hit_counts["down"],
                "hitFlatCount": hit_counts["flat"],
                "hitSuspendedCount": hit_counts["suspended"],
                "hitUnknownCount": hit_counts["unknown"],
                "hitCount": hit_counts["total"],
                "memberUpCount": member_breadth.up_count,
                "memberDownCount": member_breadth.down_count,
                "memberFlatCount": member_breadth.flat_count,
                "memberSuspendedCount": member_breadth.suspended_count,
                "memberUnknownCount": member_breadth.unknown_count,
                "memberMedianChangePct": _round(member_breadth.median_change_pct),
                "memberCoverage": _round(member_breadth.coverage),
                "memberBreadthStatus": member_breadth.status,
                # The official relative is equal-weight, matching the market
                # benchmark.  The weighted variant is published under its own
                # name so the two bases are never confused for one another.
                "relativeToMarketPct": _round(
                    direction.relative_to_market(
                        member_breadth.median_change_pct, market_median
                    )
                ),
                "boardRelativeToMarketPct": _round(
                    direction.relative_to_market(board_change, market_median)
                ),
            }
        )
        decorated.append(record)
    return decorated


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

    market_block = _market_baseline(inputs.market)
    market_median = market_block["medianChangePct"]

    amount_top = inputs.amount_rows[:top]
    turnover_top = inputs.turnover_rows[:top]

    industries: list[dict[str, Any]] = []
    levels = [1] if level == 1 else [2] if level == 2 else [1, 2]
    for one_level in levels:
        hits = industry_map.aggregate(
            inputs.boards, amount_top, turnover_top, level=one_level
        )
        industries.extend(hit.as_dict() for hit in hits[:top_sectors])

    # Direction is decorated after truncation so the activity ordering — and
    # therefore which industries appear at all — is untouched by direction.
    industries = _decorate_industries(
        industries, inputs, amount_top, turnover_top, market_median
    )

    intersection = _compute_intersection(
        amount_top, turnover_top, inputs.boards, market_median
    )

    percentiles = _percentile_block(
        turnover_top, inputs.history, settled=report.settled
    )

    candidate_codes = [
        item["code"] for item in industries if item["amountTopCount"] >= 2
    ]
    candidates = [
        {
            "thscode": item["code"],
            "name": item["name"],
            "tag": item["tag"],
            "direction": item["direction"],
        }
        for item in industries
        if item["amountTopCount"] >= 2
    ]

    amount_rows_out = _summarize_rows(
        amount_top, sina_client.RANK_BY_AMOUNT, market_median
    )
    turnover_rows_out = _summarize_rows(
        turnover_top, sina_client.RANK_BY_TURNOVER, market_median
    )

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
        "direction": {
            "basis": "changePct-vs-prev-close",
            "relativeBasis": "equal-weight-vs-market-median",
            "flatEpsilon": direction.FLAT_EPSILON,
            "minBreadthCoverage": direction.MIN_BREADTH_COVERAGE,
            "basisNote": _direction_basis_note(report),
            "market": market_block,
        },
        "directionSummary": {
            "byAmount": direction.summarize_direction(amount_rows_out),
            "byTurnover": direction.summarize_direction(turnover_rows_out),
        },
        "rankings": {
            "byAmount": amount_rows_out,
            "byTurnover": turnover_rows_out,
        },
        "industries": industries,
        "intersection": intersection,
        "percentile": percentiles,
        "handoff": {
            "target": "a-stock-qts04-sector-direction",
            "candidateThscodes": candidate_codes,
            "candidates": candidates,
            "note": (
                "本 Skill 只做发现层，不评分；候选行业需由下游按 QTS-04-01-01 至 -05 打分。"
                "方向仅作标注，不参与候选筛选。"
            ),
        },
        "quality": quality.as_dict(),
        "disclaimer": (
            "四象限描述资金分布、方向描述涨跌，两者都不是买卖信号；"
            "全部规则状态 needs-backtest。"
        ),
    }


def _direction_basis_note(report: session.SessionReport) -> str:
    """Explain what instant the direction fields describe.

    Before the open there is no session yet, so the only change available is
    the previous close against the one before it.  Saying so prevents a
    pre-open report from being read as a same-day direction.
    """

    if report.state == session.STATE_PREOPEN:
        return "开盘前：方向反映前一交易日收盘涨跌幅，不是当日方向"
    if report.state == session.STATE_CLOSED:
        return "已收盘：方向为当日收盘涨跌幅"
    return "盘中：方向为当前时点相对前一收盘价的涨跌幅"


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

    board_changes = _board_changes(fuyao, boards, quality)
    market = _market_snapshot(fuyao, quality)

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
        market=market,
        board_changes=board_changes,
    )


def _board_changes(
    client: fuyao_client.FuyaoClient,
    boards: Sequence[industry_map.IndustryBoard],
    quality: Quality,
) -> dict[str, float | None]:
    """One index-snapshot call covering every board of every loaded level."""

    if not boards:
        return {}
    try:
        changes = client.index_snapshot([board.thscode for board in boards])
    except fuyao_client.FuyaoError as error:
        quality.degrade(f"板块指数快照不可用，行业方向缺少板块涨跌: {error}")
        return {}
    if not changes:
        quality.degrade("板块指数快照返回为空，行业方向缺少板块涨跌")
    return changes


def _sina_market_fallback(quality: Quality) -> fuyao_client.MarketSnapshot:
    """Rebuild the whole-market map from the Sina full snapshot.

    Same instant, same per-stock change basis, so it is a genuine substitute
    rather than a different measure.  It is slower (~2.7s), which is why it is
    only used when the fuyao endpoint fails.
    """

    rows = sina_client.fetch_full_snapshot()
    changes = {row.thscode: row.change_pct for row in rows}
    # Sina exposes amount rather than volume; a zero amount means the stock did
    # not trade, which is the same suspension signal we need.
    volumes = {row.thscode: row.amount for row in rows}
    quality.degrade("全市场快照改用新浪全量快照兜底，相对方向仍可用")
    return fuyao_client.MarketSnapshot(
        changes=changes,
        volumes=volumes,
        source="sina-full-snapshot",
        timestamp=None,
        total=len(rows),
    )


def _market_snapshot(
    client: fuyao_client.FuyaoClient,
    quality: Quality,
) -> fuyao_client.MarketSnapshot:
    """Whole-market direction baseline, with an honest failure path."""

    def fallback() -> fuyao_client.MarketSnapshot:
        return _sina_market_fallback(quality)

    snapshot = fuyao_client.market_change_map(client, fallback=fallback)
    if snapshot.source == "unavailable":
        quality.degrade("全市场快照不可用，相对方向与宽度不可用")
    return snapshot


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

    board_changes: dict[str, float | None] = {}
    for code, value in (payload.get("boardChanges") or {}).items():
        board_changes[str(code)] = fuyao_client._optional_float(value)

    market_payload = payload.get("market")
    market: fuyao_client.MarketSnapshot | None = None
    if isinstance(market_payload, Mapping):
        changes = {
            str(code): fuyao_client._optional_float(value)
            for code, value in (market_payload.get("changes") or {}).items()
        }
        volumes = {
            str(code): fuyao_client._optional_float(value)
            for code, value in (market_payload.get("volumes") or {}).items()
        }
        market = fuyao_client.MarketSnapshot(
            changes=changes,
            volumes=volumes,
            source=str(market_payload.get("source") or "fixture"),
            timestamp=market_payload.get("timestamp"),
            total=fuyao_client._optional_int(market_payload.get("total")),
        )

    options = payload.get("options") or {}
    inputs = ScanInputs(
        as_of=today,
        now=now,
        amount_rows=rows("byAmount"),
        turnover_rows=rows("byTurnover"),
        boards=boards,
        history=history,
        market=market,
        board_changes=board_changes,
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
    parser.add_argument(
        "--answer",
        type=Path,
        default=None,
        help="会话回复文件：固定标题与五段结构，回复内容须逐字复制该文件",
    )
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=None,
        help="扫描轨迹记录目录；默认实时运行写到 Skill 缓存，fixture 模式不写",
    )
    parser.add_argument(
        "--no-history-store",
        action="store_true",
        help="本次不读写扫描轨迹（仍会渲染“首次记录”占位）",
    )
    parser.add_argument(
        "--import-history",
        type=Path,
        nargs="+",
        default=None,
        help="把既有 JSON 结果补录进扫描轨迹（同一 reportId 不重复）",
    )
    parser.add_argument("--fixture", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--no-bars", action="store_true")
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--now", type=str, default=None, help="覆盖当前时刻（测试用）")
    return parser.parse_args(argv)


def _history_root(args: argparse.Namespace) -> Path | None:
    """Where this run's trajectory rows live.

    Live runs default to the Skill cache.  Fixture runs stay out of it: a test
    replay must not become tomorrow's "previous scan".
    """

    if args.no_history_store:
        return None
    if args.history_dir is not None:
        return args.history_dir
    if args.fixture is not None:
        return None
    return CACHE_ROOT / history.HISTORY_SUBDIR


def _import_history(
    root: Path,
    paths: Sequence[Path],
    quality: "Quality",
) -> None:
    """Backfill the trajectory from result files that already exist.

    Only files produced by this Skill are accepted, and rows are deduplicated
    by ``reportId``, so importing the same file twice cannot inflate the
    timeline.  Nothing is recalculated: the projection is read from the file.
    """

    for path in paths:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            quality.warn(f"轨迹补录跳过 {path}: {error}")
            continue
        if not isinstance(payload, Mapping) or not payload.get("reportId"):
            quality.warn(f"轨迹补录跳过 {path}: 不是本 Skill 的结果文件")
            continue
        try:
            history.append_run(root, payload)
        except OSError as error:
            quality.warn(f"轨迹补录写入失败 {path}: {error}")


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

    history_root = _history_root(args)
    if history_root is not None and args.import_history:
        _import_history(history_root, args.import_history, quality)
    earlier: list[dict[str, Any]] = []
    if history_root is not None:
        try:
            earlier = history.load_recent(
                history_root,
                result.get("asOf") or "",
                exclude_report_id=str(result.get("reportId") or ""),
            )
        except OSError as error:  # pragma: no cover - unreadable cache
            quality.degrade(f"扫描轨迹历史不可读，本次按首次记录渲染: {error}")

    if args.markdown is not None or args.answer is not None:
        import report as report_module

    if args.markdown is not None:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(
            report_module.render(result, history=earlier), encoding="utf-8"
        )

    if args.answer is not None:
        artifacts: dict[str, str] = {}
        if args.output is not None:
            artifacts["JSON"] = str(args.output)
        if args.markdown is not None:
            artifacts["Markdown"] = str(args.markdown)
        args.answer.parent.mkdir(parents=True, exist_ok=True)
        args.answer.write_text(
            report_module.render_answer(result, artifacts=artifacts, history=earlier),
            encoding="utf-8",
        )

    if history_root is not None:
        try:
            history.append_run(history_root, result)
        except OSError as error:  # pragma: no cover - unwritable cache
            quality.degrade(f"扫描轨迹写入失败，下次扫描将缺少本次基线: {error}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())