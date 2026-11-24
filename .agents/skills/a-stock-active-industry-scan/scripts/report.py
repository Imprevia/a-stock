"""Markdown renderer for the active-industry scan Skill.

Renders a result document that was already computed elsewhere.  No metric is
recalculated here: every number printed is read straight out of the JSON, so
the two artifacts cannot disagree.  A missing value renders as ``—`` rather
than ``0`` so an absent measurement stays visibly absent.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import direction
import history as history_module

MISSING = "—"

#: The user-facing answer has a fixed identity: the heading below and the
#: bullet block produced by ``render_highlight``.  Sessions are required to
#: paste ``--answer`` verbatim, so any change here is a format change for every
#: conversation that uses the Skill.
ANSWER_HEADING = "# 最活跃的行业"
ANSWER_HIGHLIGHT_BULLETS = 5

#: Direction groups are a complete partition of the industry table, which is
#: already capped by ``--top-sectors``.  An extra cap here would silently drop
#: the most active falling industry (observed 2026-11-20: 半导体 is 7th by
#: relative excess but the day's headline), so no second limit is applied.
DIRECTION_GROUP_LIMIT = None


def _text(value: Any) -> str:
    if value is None or value == "":
        return MISSING
    return str(value)


def _num(value: Any, digits: int = 2) -> str:
    if value is None:
        return MISSING
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return MISSING


def _pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return MISSING
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return MISSING


def _signed_pct(value: Any, digits: int = 2) -> str:
    """A change expressed with an explicit sign.

    Direction values must never be read as unsigned magnitudes: a session that
    renders ``1.23%`` and another that renders ``+1.23%`` look like different
    measurements.  Rates (turnover, hit rate) keep ``_pct`` because they carry
    no sign.
    """

    if value is None:
        return MISSING
    try:
        return f"{float(value):+.{digits}f}%"
    except (TypeError, ValueError):
        return MISSING


def _rate(value: Any) -> str:
    if value is None:
        return MISSING
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return MISSING


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    if not rows:
        return [f"（无{headers[0]}数据）"]
    head = "| " + " | ".join(headers) + " |"
    rule = "|" + "|".join("---" for _ in headers) + "|"
    body = ["| " + " | ".join(cells) + " |" for cells in rows]
    return [head, rule, *body]


def render(
    document: Mapping[str, Any],
    *,
    history: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Produce the Markdown report for one result document."""

    lines: list[str] = ["# A 股活跃行业扫描", ""]
    lines.extend(_render_header(document))
    if document.get("earlySnapshot"):
        lines.append("> **早期快照**：首根 5 分钟 bar 含集合竞价，占比可达 47%，榜单波动剧烈。")
        lines.append("")
    lines.extend(_render_body(document, history=history))
    return "\n".join(lines).rstrip() + "\n"


def render_answer(
    document: Mapping[str, Any],
    *,
    artifacts: Mapping[str, str] | None = None,
    history: Sequence[Mapping[str, Any]] = (),
) -> str:
    """The canonical session answer for one result document.

    Identical input renders identical text, so two sessions handed the same
    JSON cannot disagree about the title, the section names or the table
    columns.  ``artifacts`` adds the saved file paths to the footer.
    """

    lines: list[str] = [ANSWER_HEADING, ""]
    lines.extend(_render_highlight(document))
    if document.get("earlySnapshot"):
        lines.append("")
        lines.append("> **早期快照**：首根 5 分钟 bar 含集合竞价，占比可达 47%，榜单波动剧烈。")
    lines.append("")
    lines.extend(_render_body(document, history=history))
    if artifacts:
        for label, path in artifacts.items():
            if path:
                lines.append(f"- {label}：{path}")
    return "\n".join(lines).rstrip() + "\n"


def _render_header(document: Mapping[str, Any]) -> list[str]:
    state = _text(document.get("sessionState"))
    quality = document.get("quality") or {}
    return [
        f"- 运行时刻：{_text(document.get('asOf'))}（{state}）",
        f"- 数据截止：{_text(document.get('dataCutoff'))}",
        f"- 已过 bar 数：{_text(document.get('elapsedBars'))}"
        f"　换手率口径：{_text(document.get('turnoverBasis'))}",
        f"- 质量状态：{_text(quality.get('status'))}",
        "",
    ]


CN_NUMERALS = "一二三四五六七八九十"


def _section_heading(index: int, title: str) -> str:
    mark = CN_NUMERALS[index - 1] if index <= len(CN_NUMERALS) else str(index)
    return f"## {mark}、{title}"


def _render_body(
    document: Mapping[str, Any],
    *,
    history: Sequence[Mapping[str, Any]] = (),
) -> list[str]:
    """Every section, numbered contiguously.

    Numbering is assigned here rather than hardcoded per section: an optional
    section (被剔除) would otherwise leave a gap, and two answers from the same
    Skill would carry different section numbers.
    """

    sections: list[tuple[str, list[str]]] = [
        ("行业活跃度与方向", _render_industries(document)),
        ("方向分组", _render_direction_groups(document)),
        ("双榜交集", _render_intersection(document)),
        ("扫描变化轨迹", _render_trajectory(document, history)),
        ("双榜明细", _render_rankings(document)),
    ]
    excluded = _render_excluded(document)
    if excluded:
        sections.append(("被剔除的股票", excluded))
    sections.append(("数据质量", _render_quality(document.get("quality") or {})))

    lines: list[str] = []
    for index, (title, block) in enumerate(sections, 1):
        lines.append(_section_heading(index, title))
        lines.append("")
        lines.extend(block)
    lines.extend(_render_footer(document))
    return lines


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _top_industries(
    document: Mapping[str, Any], count: int = 3
) -> list[Mapping[str, Any]]:
    """Rank by double-board hits, independent of the table's own ordering.

    The headline must not inherit the upstream sort, otherwise a sorting change
    would silently rewrite the opening sentence of every session answer.  Ties
    break on amount hits, then turnover hits, then code, which is stable.
    """

    industries = [i for i in document.get("industries") or [] if isinstance(i, Mapping)]
    return sorted(
        industries,
        key=lambda i: (
            -_int(i.get("hitCount")),
            -_int(i.get("amountTopCount")),
            -_int(i.get("turnoverTopCount")),
            str(i.get("code")),
        ),
    )[:count]


def _industry_phrase(item: Mapping[str, Any]) -> str:
    return (
        f"{_text(item.get('name'))}（成交额榜 {_text(item.get('amountTopCount'))}"
        f"、换手榜 {_text(item.get('turnoverTopCount'))}"
        f"，{_text(item.get('tag'))}"
        f"，板块 {_signed_pct(item.get('boardChangePct'))}"
        f"，相对市场 {_signed_pct(item.get('relativeToMarketPct'))}）"
    )


def _render_highlight(document: Mapping[str, Any]) -> list[str]:
    """The fixed five-bullet conclusion block that opens every answer."""

    quality = document.get("quality") or {}
    market = (document.get("direction") or {}).get("market") or {}
    top = [_industry_phrase(item) for item in _top_industries(document)]
    groups = direction.group_by_direction(document.get("industries") or [])
    intersection = document.get("intersection") or []
    names = [str(item.get("name")) for item in intersection if item.get("name")]
    handoff = document.get("handoff") or {}
    codes = handoff.get("candidateThscodes") or []
    membership = document.get("industryMembershipDate")

    lines = [
        f"- 时点：{_text(document.get('asOf'))}（{_text(document.get('sessionState'))}）"
        f"　数据截止 {_text(document.get('dataCutoff'))}"
        f"　已过 bar 数 {_text(document.get('elapsedBars'))}"
        f"　质量 {_text(quality.get('status'))}",
        f"- 全市场：中位 {_signed_pct(market.get('medianChangePct'))}"
        f"　涨 {_text(market.get('upCount'))} / 跌 {_text(market.get('downCount'))}"
        f" / 平 {_text(market.get('flatCount'))}"
        f" / 停牌 {_text(market.get('suspendedCount'))}",
        f"- 最活跃行业：{'；'.join(top) if top else MISSING}",
        f"- 方向：活跃上涨 {len(groups.get('up') or [])} 个"
        f"、活跃下跌 {len(groups.get('down') or [])} 个",
        f"- 双榜交集：{len(intersection)} 只"
        f"（{'、'.join(names)}）　候选行业 {len(codes)} 个",
    ]
    if membership:
        lines[0] += f"　行业成分股 {_text(membership)}"
    return lines


def _render_industries(document: Mapping[str, Any]) -> list[str]:
    industries = document.get("industries") or []
    lines: list[str] = []
    rows = []
    for item in industries:
        rows.append(
            [
                _text(item.get("name")),
                _text(item.get("level")),
                _text(item.get("amountTopCount")),
                _text(item.get("turnoverTopCount")),
                _text(item.get("memberCount")),
                _rate(item.get("hitRateAmount")),
                _text(item.get("quadrant")),
                _signed_pct(item.get("boardChangePct")),
                _hit_direction_cell(item),
                _signed_pct(item.get("relativeToMarketPct")),
                _text(item.get("tag")),
            ]
        )
    lines.extend(
        _table(
            [
                "行业", "层级", "成交额榜", "换手榜", "成分股", "成交额命中率",
                "四象限", "板块涨跌", "上榜涨跌", "相对市场", "方向标签",
            ],
            rows,
        )
    )
    lines.append("")
    lines.append("四象限：真实活跃（双榜均命中）、权重拉升（仅成交额榜）、"
                 "小盘情绪（仅换手榜）、冷门（均未达阈值）。")
    lines.append("")
    return lines


def _hit_direction_cell(item: Mapping[str, Any]) -> str:
    """Render the hit split as ``涨N/跌M``, or a dash when nothing is known."""

    up = item.get("hitUpCount")
    down = item.get("hitDownCount")
    if up is None and down is None:
        return MISSING
    total = item.get("hitCount")
    if not total:
        return MISSING
    return f"涨{_text(up)}/跌{_text(down)}"


def _render_direction_groups(document: Mapping[str, Any]) -> list[str]:
    """The up/down split, rendered straight from the JSON industry list."""

    industries = document.get("industries") or []
    groups = direction.group_by_direction(
        industries, limit=DIRECTION_GROUP_LIMIT, order_by_relative=True
    )
    lines: list[str] = []

    market = (document.get("direction") or {}).get("market") or {}
    lines.append(
        f"- 全市场基准：中位涨跌幅 {_signed_pct(market.get('medianChangePct'))}"
        f"，涨 {_text(market.get('upCount'))} / 跌 {_text(market.get('downCount'))}"
        f" / 平 {_text(market.get('flatCount'))}"
        f" / 停牌 {_text(market.get('suspendedCount'))}"
        f"（有效 {_text(market.get('validCount'))} / {_text(market.get('universe'))}）"
    )
    lines.append(f"- 相对基准：{_text((document.get('direction') or {}).get('relativeBasis'))}")
    lines.append(f"- 口径：{_text((document.get('direction') or {}).get('basisNote'))}")
    lines.append("")

    for key, title in (("up", "活跃上涨"), ("down", "活跃下跌")):
        members = groups.get(key) or []
        lines.append(f"### {title}（{len(members)} 个）")
        lines.append("")
        if not members:
            lines.append("本次该分组为空：没有行业方向落在这一侧，未放宽判定阈值。")
            lines.append("")
            continue
        rows = [
            [
                _text(item.get("name")),
                _text(item.get("tag")),
                _signed_pct(item.get("boardChangePct")),
                _hit_direction_cell(item),
                _signed_pct(item.get("relativeToMarketPct")),
            ]
            for item in members
        ]
        lines.extend(
            _table(["行业", "方向标签", "板块涨跌", "上榜涨跌", "相对市场"], rows)
        )
        lines.append("")

    summary = document.get("directionSummary") or {}
    for key, label in (("byAmount", "成交额榜"), ("byTurnover", "换手率榜")):
        block = summary.get(key) or {}
        if not block:
            continue
        lines.append(
            f"- {label}：涨 {_text(block.get('up'))} / 跌 {_text(block.get('down'))}"
            f" / 平 {_text(block.get('flat'))}"
            f"，上涨股成交额占比 {_rate(block.get('upAmountShare'))}"
        )
    lines.append("")
    return lines


def _render_intersection(document: Mapping[str, Any]) -> list[str]:
    items = document.get("intersection") or []
    lines: list[str] = []
    rows = []
    for item in items:
        industries = item.get("industries") or []
        rows.append(
            [
                _text(item.get("name")),
                _text(item.get("code")),
                _text(item.get("amountRank")),
                _text(item.get("turnoverRank")),
                " / ".join(str(i) for i in industries) if industries else MISSING,
                _signed_pct(item.get("changePct")),
                _text(direction.DIRECTION_LABELS.get(item.get("direction"))),
                _signed_pct(item.get("relativeToMarketPct")),
            ]
        )
    lines.extend(
        _table(
            ["名称", "代码", "成交额排名", "换手排名", "行业", "涨跌幅", "方向", "相对市场"],
            rows,
        )
    )
    if not items:
        lines.append("本次无交集：两个榜的 Top N 没有共同股票。未放宽阈值。")
    else:
        groups = direction.group_by_direction(items)
        lines.append("")
        lines.append(
            f"交集方向：上涨 {len(groups.get('up') or [])} 只、"
            f"下跌 {len(groups.get('down') or [])} 只（其余为平盘或停牌）。"
        )
    lines.append("")
    return lines


def _trajectory_row(row: Mapping[str, Any], top_codes: Sequence[str]) -> list[str]:
    market = row.get("market") or {}
    by_turnover = row.get("byTurnover") or {}
    intersection = row.get("intersection") or {}
    index = {
        str(item.get("code")): item
        for item in row.get("industries") or []
        if isinstance(item, Mapping)
    }
    hits = []
    for code in top_codes:
        item = index.get(code)
        hits.append(f"{_text(item.get('name'))} {_text(item.get('amountTopCount'))}" if item else "—")
    stamp = _text(row.get("asOf"))
    if stamp != MISSING and len(stamp) >= 19:
        # Seconds, not minutes: two scans a minute apart are separate rows and
        # must not render as the same timestamp.
        stamp = stamp[11:19]
    return [
        stamp,
        _text(row.get("elapsedBars")),
        _signed_pct(market.get("medianChangePct")),
        f"{_text(market.get('upCount'))}/{_text(market.get('downCount'))}",
        "；".join(hits) if hits else "—",
        _signed_pct((index.get(top_codes[0]) or {}).get("boardChangePct")) if top_codes else "—",
        f"{_text(by_turnover.get('up'))}/{_text(by_turnover.get('down'))}",
        _text(intersection.get("count")),
        _text(len(row.get("candidates") or [])),
    ]


def _render_trajectory(
    document: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]] = (),
) -> list[str]:
    """How the scan moved across the runs of the same trading day.

    Data comes from the per-day history store, never from a second network
    call: the trajectory must describe runs that actually happened, and a
    replay of an old JSON must reproduce the same table.
    """

    current = history_module.snapshot(document)
    top_codes = [str(item.get("code")) for item in _top_industries(document)]
    earlier = [row for row in history if isinstance(row, Mapping)]
    # Chronological: imported runs can be older than rows already stored, and a
    # trajectory out of time order would compare the wrong pair.
    ordered = sorted(
        [*earlier, current], key=lambda row: str(row.get("asOf") or "")
    )

    lines: list[str] = []
    rows = ordered
    if len(rows) == 1:
        lines.append(
            "本次为当日首次记录：暂无对比基线。再次扫描同一交易日会填充本表。"
        )
        lines.append("")
        return lines

    table_rows = [_trajectory_row(row, top_codes) for row in rows]
    lines.extend(
        _table(
            [
                "时刻", "bar", "全市场中位", "涨/跌", f"Top3 成交额榜（{_top_label(document)}）",
                "首位行业板块", "换手榜涨/跌", "交集", "候选",
            ],
            table_rows,
        )
    )
    lines.append("")

    position = rows.index(current)
    previous = rows[position - 1] if position > 0 else None
    baseline = rows[0] if len(rows) > 1 else None

    threshold_note = (
        f"（中位 ±{history_module.MEDIAN_EPSILON:.2f}pp、"
        f"上涨家数 ±{history_module.COUNT_RATIO_EPSILON * 100:.0f}%、"
        f"行业命中 ±{history_module.HIT_EPSILON}、交集增删、候选增删）"
    )

    def block(title: str, other: Mapping[str, Any] | None) -> None:
        if other is None:
            return
        changes = history_module.highlight_changes(
            current, other, top_codes=top_codes
        )
        lines.append(title)
        lines.append("")
        if changes:
            for item in changes:
                lines.append(f"- {item}")
        else:
            lines.append(f"- 未触发任何阈值{threshold_note}")
        lines.append("")

    block("关键变化（相对上一次扫描）：", previous)
    if baseline is not None and baseline is not previous:
        stamp = _text(baseline.get("asOf"))
        if stamp != MISSING and len(stamp) >= 19:
            stamp = stamp[11:19]
        block(f"关键变化（相对当日首次 {stamp}）：", baseline)
    lines.append(
        f"轨迹取自本地 `{history_module.HISTORY_SUBDIR}/` 当日记录（最多 "
        f"{history_module.MAX_SNAPSHOTS} 次），不是历史行情回放。"
    )
    lines.append("")
    return lines


def _top_label(document: Mapping[str, Any]) -> str:
    names = [str(item.get("name")) for item in _top_industries(document)]
    return "、".join(names) if names else MISSING


def _render_rankings(document: Mapping[str, Any]) -> list[str]:
    rankings = document.get("rankings") or {}
    lines: list[str] = []
    for label, key in (("成交额榜", "byAmount"), ("换手率榜", "byTurnover")):
        rows = []
        for item in (rankings.get(key) or [])[:15]:
            rows.append(
                [
                    _text(item.get("rank")),
                    _text(item.get("name")),
                    _text(item.get("code")),
                    _num(item.get("amountYi")),
                    _pct(item.get("turnoverPct")),
                    _num(item.get("floatMvYi")),
                    _signed_pct(item.get("changePct")),
                    _text(direction.DIRECTION_LABELS.get(item.get("direction"))),
                    _signed_pct(item.get("relativeToMarketPct")),
                ]
            )
        lines.append(f"### {label}（前 15）")
        lines.append("")
        lines.extend(
            _table(
                [
                    "#", "名称", "代码", "成交额(亿)", "换手率", "流通市值(亿)",
                    "涨跌幅", "方向", "相对市场",
                ],
                rows,
            )
        )
        lines.append("")
    return lines


def _render_excluded(document: Mapping[str, Any]) -> list[str]:
    excluded = document.get("excluded") or {}
    turnover = excluded.get("byTurnover") or []
    amount = excluded.get("byAmount") or []
    missing = excluded.get("missingListDate") or []
    if not turnover and not amount and not missing:
        return []

    lines: list[str] = []
    if turnover:
        rows = [
            [
                _text(item.get("name")),
                _text(item.get("code")),
                _text(item.get("listDate")),
                _text(item.get("listingDays")),
                _text(item.get("rankIfUnfiltered")),
            ]
            for item in turnover
        ]
        lines.append("### 换手率榜剔除")
        lines.append("")
        lines.extend(
            _table(["名称", "代码", "上市日期", "上市天数", "原排名"], rows)
        )
        lines.append("")
    if amount:
        rows = [
            [
                _text(item.get("name")),
                _text(item.get("code")),
                _text(item.get("listDate")),
                _text(item.get("listingDays")),
                _text(item.get("rankIfUnfiltered")),
            ]
            for item in amount
        ]
        lines.append("### 成交额榜剔除")
        lines.append("")
        lines.extend(
            _table(["名称", "代码", "上市日期", "上市天数", "原排名"], rows)
        )
        lines.append("")
    if missing:
        lines.append(f"缺少上市日期而排除：{len(missing)} 只")
        lines.append("")
    return lines


def _render_quality(quality: Mapping[str, Any]) -> list[str]:
    """Always present, even when clean.

    A section that disappears on good days would move every later section up
    and make two answers from the same Skill structurally different.
    """

    degradations = quality.get("degradations") or []
    warnings = quality.get("warnings") or []
    lines: list[str] = []
    if not degradations and not warnings:
        lines.append("- 本次无降级、无提示。")
    for item in degradations:
        lines.append(f"- 降级：{item}")
    for item in warnings:
        lines.append(f"- 提示：{item}")
    lines.append("")
    return lines


def _render_footer(document: Mapping[str, Any]) -> list[str]:
    lines = ["---", ""]
    percentile_block = document.get("percentile") or {}
    if percentile_block.get("status") == "deferred":
        lines.append(
            f"- 换手率历史分位：本次不可用（{_text(percentile_block.get('reason'))}），"
            f"{_text(percentile_block.get('availableAfter'))} 后可补算。"
        )
    handoff = document.get("handoff") or {}
    codes = handoff.get("candidateThscodes") or []
    lines.append(
        f"- 候选行业（交下游打分）：{len(codes)} 个"
        f"{'：' + '、'.join(codes[:10]) if codes else ''}"
    )
    lines.append(f"- {_text(document.get('disclaimer'))}")
    lines.append(
        "- 方向口径：平盘阈值 "
        f"±{_text((document.get('direction') or {}).get('flatEpsilon'))}%，"
        f"宽度覆盖率门槛 {_rate((document.get('direction') or {}).get('minBreadthCoverage'))}；"
        "停牌与无昨收样本剔出分母，不记为平盘。"
    )
    lines.append(
        "- 方向与四象限都是描述层，同为 `needs-backtest`；"
        "方向不参与排序、不筛选候选、不构成买卖信号。"
    )
    lines.append(
        f"- 报告标识：{_text(document.get('reportId'))}　"
        f"规则版本：{_text(document.get('ruleVersion'))}"
    )
    return lines