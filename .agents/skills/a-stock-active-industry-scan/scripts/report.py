"""Markdown renderer for the active-industry scan Skill.

Renders a result document that was already computed elsewhere.  No metric is
recalculated here: every number printed is read straight out of the JSON, so
the two artifacts cannot disagree.  A missing value renders as ``—`` rather
than ``0`` so an absent measurement stays visibly absent.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

MISSING = "—"


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


def render(document: Mapping[str, Any]) -> str:
    """Produce the Markdown report for one result document."""

    lines: list[str] = []
    lines.append("# A 股活跃行业扫描")
    lines.append("")

    state = _text(document.get("sessionState"))
    lines.append(
        f"- 运行时刻：{_text(document.get('asOf'))}（{state}）"
    )
    lines.append(f"- 数据截止：{_text(document.get('dataCutoff'))}")
    lines.append(
        f"- 已过 bar 数：{_text(document.get('elapsedBars'))}"
        f"　换手率口径：{_text(document.get('turnoverBasis'))}"
    )
    quality = document.get("quality") or {}
    lines.append(f"- 质量状态：{_text(quality.get('status'))}")
    lines.append("")

    if document.get("earlySnapshot"):
        lines.append("> **早期快照**：首根 5 分钟 bar 含集合竞价，占比可达 47%，榜单波动剧烈。")
        lines.append("")

    lines.extend(_render_industries(document))
    lines.extend(_render_intersection(document))
    lines.extend(_render_rankings(document))
    lines.extend(_render_excluded(document))
    lines.extend(_render_quality(quality))
    lines.extend(_render_footer(document))
    return "\n".join(lines).rstrip() + "\n"


def _render_industries(document: Mapping[str, Any]) -> list[str]:
    industries = document.get("industries") or []
    lines = ["## 一、行业活跃度", ""]
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
            ]
        )
    lines.extend(
        _table(
            ["行业", "层级", "成交额榜", "换手榜", "成分股", "成交额命中率", "四象限"],
            rows,
        )
    )
    lines.append("")
    lines.append("四象限：真实活跃（双榜均命中）、权重拉升（仅成交额榜）、"
                 "小盘情绪（仅换手榜）、冷门（均未达阈值）。")
    lines.append("")
    return lines


def _render_intersection(document: Mapping[str, Any]) -> list[str]:
    items = document.get("intersection") or []
    lines = ["## 二、双榜交集", ""]
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
            ]
        )
    lines.extend(_table(["名称", "代码", "成交额排名", "换手排名", "行业"], rows))
    if not items:
        lines.append("本次无交集：两个榜的 Top N 没有共同股票。未放宽阈值。")
    lines.append("")
    return lines


def _render_rankings(document: Mapping[str, Any]) -> list[str]:
    rankings = document.get("rankings") or {}
    lines = ["## 三、双榜明细", ""]
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
                    _pct(item.get("changePct")),
                ]
            )
        lines.append(f"### {label}（前 15）")
        lines.append("")
        lines.extend(
            _table(
                ["#", "名称", "代码", "成交额(亿)", "换手率", "流通市值(亿)", "涨跌幅"],
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

    lines = ["## 四、被剔除的股票", ""]
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
    degradations = quality.get("degradations") or []
    warnings = quality.get("warnings") or []
    if not degradations and not warnings:
        return []
    lines = ["## 五、数据质量", ""]
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
        f"- 报告标识：{_text(document.get('reportId'))}　"
        f"规则版本：{_text(document.get('ruleVersion'))}"
    )
    return lines