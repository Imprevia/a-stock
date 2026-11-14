"""Render the QTS-04 STEP 1 result as a human-readable Markdown report.

The JSON contract stays the machine interface; this module is a pure
presentation layer.  It never invents a value that the JSON does not carry:
missing scores render as an em dash, not as zero.
"""

from __future__ import annotations

import itertools
from datetime import datetime
from typing import Any, Mapping, Sequence

DASH = "—"

STATUS_LABEL = {
    "ok": "数据完整",
    "degraded": "数据降级，结论可用但有缺口",
    "insufficient": "数据不足，不给结论",
}

POOL_LABEL = {
    "focus": "重点池",
    "watch": "观察池",
    "excluded": "不参与",
    "insufficient": "数据不足",
}

CONFIDENCE_LABEL = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "insufficient": "不足",
}

METRIC_STATUS_LABEL = {
    "ok": "ok",
    "reduced-confidence": "短历史",
    "insufficient": "无分",
}

RULE_LABEL = {
    "QTS-04-01-01": ("5 日相对强度", "pct", 0.25, True),
    "QTS-04-01-02": ("20 日相对强度", "pct", 0.15, True),
    "QTS-04-01-03": ("成交额增量", "ratio", 0.20, False),
    "QTS-04-01-04": ("板块宽度", "pct-nosign", 0.20, False),
    "QTS-04-01-05": ("持续与恢复", "points", 0.20, False),
}

QUADRANT_ADVICE = {
    "真实流入": "量能、强度、覆盖三者一致，是四象限里最健康的一格。",
    "短线脉冲": "强度够但覆盖窄，容易一日游，需要次日量能确认。",
    "权重拉升": "普涨但缺量缺强度，多是权重或情绪带动，持续性偏弱。",
    "资金撤退": "强度与覆盖双弱，不参与。",
}


def _pct(value: Any, *, signed: bool = True, digits: int = 2) -> str:
    if value is None:
        return DASH
    try:
        number = float(value) * 100
    except (TypeError, ValueError):
        return DASH
    sign = "+" if signed and number > 0 else ""
    return f"{sign}{number:.{digits}f}%"


def _ratio(value: Any, digits: int = 2) -> str:
    if value is None:
        return DASH
    try:
        return f"{float(value):.{digits}f}×"
    except (TypeError, ValueError):
        return DASH


def _num(value: Any, digits: int = 1) -> str:
    if value is None:
        return DASH
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return DASH


def _int(value: Any) -> str:
    if value is None:
        return DASH
    try:
        return f"{int(round(float(value)))}"
    except (TypeError, ValueError):
        return DASH


def _money(value: Any) -> str:
    if value is None:
        return DASH
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DASH
    if abs(number) >= 1e8:
        return f"{number / 1e8:.2f} 亿"
    if abs(number) >= 1e4:
        return f"{number / 1e4:.2f} 万"
    return f"{number:.0f}"


def _metric_value(metric: Mapping[str, Any]) -> str:
    rule_id = str(metric.get("ruleId") or "")
    kind = RULE_LABEL.get(rule_id, ("", "raw", 0.0, False))[1]
    value = metric.get("value")
    if kind == "pct":
        return _pct(value, signed=True)
    if kind == "pct-nosign":
        return _pct(value, signed=False)
    if kind == "ratio":
        return _ratio(value)
    if kind == "points":
        return f"{_num(value, 1)} 分" if value is not None else DASH
    return _num(value)


def _quadrant_sentence(quadrant: Mapping[str, Any]) -> str:
    label = quadrant.get("label")
    if not label:
        reason = quadrant.get("reason")
        return f"无法判定四象限" + (f"（{reason}）" if reason else "") + "。"
    parts: list[str] = []
    strength = quadrant.get("strengthHigh")
    breadth = quadrant.get("breadthWide")
    parts.append("强度高" if strength else "强度低")
    parts.append("覆盖广" if breadth else "覆盖窄")
    detail = (
        f"量能 {_ratio(quadrant.get('turnoverRatio'))}、"
        f"5 日超额 {_pct(quadrant.get('relativeStrength5'))}、"
        f"当日上涨家数占比 {_pct(quadrant.get('advanceRatio'), signed=False)}"
    )
    advice = QUADRANT_ADVICE.get(str(label), "")
    return f"**{label}**（{'、'.join(parts)}）。{detail}。{advice}"


def _coinsurance(direction: Mapping[str, Any]) -> str:
    """Explain in one line why this sector made the list."""

    by_rule = {str(metric.get("ruleId")): metric for metric in direction.get("metrics") or []}
    bits: list[str] = []
    turnover = by_rule.get("QTS-04-01-03", {}).get("value")
    if turnover is not None:
        bits.append(f"量能放大到 {_ratio(turnover)}")
    rs5 = by_rule.get("QTS-04-01-01", {}).get("value")
    if rs5 is not None:
        bits.append(f"5 日超额 {_pct(rs5)}")
    breadth = by_rule.get("QTS-04-01-04", {}).get("value")
    if breadth is not None:
        bits.append(f"{_pct(breadth, signed=False, digits=0)} 成分股收于 MA20 上方")
    if not bits:
        return "指标不完整，仅凭剩余有效指标进入观察。"
    return "、".join(bits) + "。"


def _risk_line(direction: Mapping[str, Any]) -> str | None:
    metrics = list(direction.get("metrics") or [])
    reduced: list[Mapping[str, Any]] = []
    missing: list[Mapping[str, Any]] = []
    for metric in metrics:
        status = metric.get("status")
        if status == "insufficient":
            missing.append(metric)
        elif status == "reduced-confidence":
            reduced.append(metric)

    def name_of(metric: Mapping[str, Any]) -> str:
        return RULE_LABEL.get(str(metric.get("ruleId")), (str(metric.get("ruleId")),))[0]

    warnings: list[str] = []
    if missing:
        detail = "、".join(
            f"{name_of(metric)}（{metric.get('missingReason') or '无有效观测'}）" for metric in missing
        )
        warnings.append(f"未计分项：{detail}；总分按剩余权重归一")
    if reduced:
        observations = [metric.get("observations") for metric in reduced if metric.get("observations")]
        span = ""
        if observations:
            low, high = min(observations), max(observations)
            span = f"（观测 {low}）" if low == high else f"（观测 {low}—{high}）"
        if len(reduced) == len(metrics):
            warnings.append(f"全部 {len(metrics)} 项指标均为短历史{span}，置信度上限为中")
        else:
            warnings.append(
                f"{len(reduced)} 项指标为短历史{span}：{'、'.join(name_of(metric) for metric in reduced)}"
            )
    if direction.get("confidence") in {"low", "insufficient"}:
        warnings.append(f"整体置信度为{CONFIDENCE_LABEL.get(str(direction.get('confidence')), '未知')}")
    if not warnings:
        return None
    return "；".join(dict.fromkeys(warnings))


def _overview_table(directions: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = [
        "| # | 板块 | 代码 | 总分 | 置信 | 池位 | 四象限 | 5 日超额 | 20 日超额 | 量能 | 宽度 |",
        "|---:|---|---|---:|---|---|---|---:|---:|---:|---:|",
    ]
    for index, direction in enumerate(directions, 1):
        by_rule = {str(metric.get("ruleId")): metric for metric in direction.get("metrics") or []}
        quadrant = direction.get("quadrant") or {}
        lines.append(
            "| {idx} | {name} | `{code}` | {total} | {conf} | {pool} | {quad} | {rs5} | {rs20} | {turn} | {breadth} |".format(
                idx=index,
                name=direction.get("name") or DASH,
                code=direction.get("thscode") or DASH,
                total=_num(direction.get("totalScore")),
                conf=CONFIDENCE_LABEL.get(str(direction.get("confidence")), DASH),
                pool=POOL_LABEL.get(str(direction.get("pool")), DASH),
                quad=quadrant.get("label") or "未判定",
                rs5=_pct(by_rule.get("QTS-04-01-01", {}).get("value")),
                rs20=_pct(by_rule.get("QTS-04-01-02", {}).get("value")),
                turn=_ratio(by_rule.get("QTS-04-01-03", {}).get("value")),
                breadth=_pct(by_rule.get("QTS-04-01-04", {}).get("value"), signed=False),
            )
        )
    return lines


def _metric_table(direction: Mapping[str, Any]) -> list[str]:
    lines = [
        "| 规则 | 指标 | 数值 | 分位 | 得分 | 权重 | 观测 | 状态 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for metric in direction.get("metrics") or []:
        rule_id = str(metric.get("ruleId") or "")
        label = RULE_LABEL.get(rule_id, (metric.get("name") or rule_id, "raw", 0.0))[0]
        weight = metric.get("normalizedWeight")
        lines.append(
            "| `{rule}` | {label} | {value} | {pct} | {score} | {weight} | {obs} | {status} |".format(
                rule=rule_id,
                label=label,
                value=_metric_value(metric),
                pct=_pct(metric.get("percentile"), signed=False, digits=1),
                score=_int(metric.get("score")),
                weight=_pct(weight, signed=False, digits=0) if weight is not None else DASH,
                obs=metric.get("observations") or DASH,
                status=METRIC_STATUS_LABEL.get(str(metric.get("status")), str(metric.get("status"))),
            )
        )
    return lines


def _direction_section(index: int, direction: Mapping[str, Any]) -> list[str]:
    quadrant = direction.get("quadrant") or {}
    lines = [
        f"### {index}. {direction.get('name') or DASH}（`{direction.get('thscode')}`）",
        "",
        "总分 **{total}** ｜ 置信 **{conf}** ｜ 池位 **{pool}** ｜ 持续性 **{persistence}**".format(
            total=_num(direction.get("totalScore")),
            conf=CONFIDENCE_LABEL.get(str(direction.get("confidence")), DASH),
            pool=POOL_LABEL.get(str(direction.get("pool")), DASH),
            persistence=_int(direction.get("persistenceScore")),
        ),
        "",
        f"**四象限**：{_quadrant_sentence(quadrant)}",
        "",
        f"**入选理由**：{_coinsurance(direction)}",
        "",
        *_metric_table(direction),
        "",
        f"- **次日确认**：{direction.get('confirmation') or DASH}",
        f"- **次日失效**：{direction.get('invalidation') or DASH}",
    ]
    risk = _risk_line(direction)
    if risk:
        lines.append(f"- **注意**：{risk}")
    lines.append("")
    return lines


def render_markdown(result: Mapping[str, Any]) -> str:
    """Turn a pipeline result mapping into a Markdown report string."""

    as_of = result.get("asOf") or DASH
    status = str(result.get("status") or DASH)
    directions = list(result.get("directions") or [])
    quality = result.get("quality") or {}

    header = [
        f"# 板块层定向报告 · {as_of}",
        "",
        "> 规则族 `QTS-04-01`（STEP 1 板块层）｜ 基准 上证综指 `000001.SH` ｜ 只做 `industry` 标签",
        "> 数据源 {source} ｜ 生成 {generated} ｜ 状态 **{status}**（{label}）".format(
            source=result.get("source") or DASH,
            generated=str(result.get("generatedAt") or DASH)[:19].replace("T", " "),
            status=status,
            label=STATUS_LABEL.get(status, status),
        ),
    ]
    cache = result.get("cacheState")
    calls = result.get("providerCalls")
    if cache or calls is not None:
        header.append(
            "> 缓存 `{}` ｜ 接口调用 {} 次 ｜ 宽度范围 前 {} 个行业（实际 {}）".format(
                cache or DASH,
                calls if calls is not None else DASH,
                result.get("breadthUniverse", DASH),
                result.get("breadthUniverseUsed", DASH),
            )
        )
    lines = header + [""]

    section = itertools.count(1)
    numerals = "一二三四五六七八九"

    def heading(title: str) -> str:
        index = next(section) - 1
        label = numerals[index] if index < len(numerals) else str(index + 1)
        return f"## {label}、{title}"

    if status == "insufficient" or not directions:
        lines += [heading("结论"), "", "本次**不产出方向**。", ""]
        warnings = list(quality.get("warnings") or [])
        if warnings:
            lines += ["原因：", ""]
            lines += [f"- {item}" for item in warnings]
            lines.append("")
    else:
        lines += [heading("结论速览"), ""]
        lines += _overview_table(directions)
        lines.append("")
        lines += [heading("方向明细"), ""]
        for index, direction in enumerate(directions, 1):
            lines += _direction_section(index, direction)

    lines += [heading("数据质量"), ""]
    lines += [
        "| 项目 | 数值 |",
        "|---|---:|",
        f"| 行业目录总数 | {quality.get('industriesTotal', DASH)} |",
        f"| 当日有日线 | {quality.get('industriesUsable', DASH)} |",
        f"| 当日无日线 | {quality.get('industriesMissing', DASH)} |",
        f"| 宽度覆盖率不足淘汰 | {quality.get('excludedByCoverage', DASH)} |",
        f"| 总分低于 50 淘汰 | {quality.get('excludedByScore', DASH)} |",
        f"| 宽度覆盖率门槛 | {_pct(quality.get('minBreadthCoverage'), signed=False, digits=0)} |",
        "",
    ]
    warnings = list(quality.get("warnings") or [])
    if warnings:
        lines += ["告警：", ""]
        lines += [f"- {item}" for item in warnings]
        lines.append("")

    lines += [
        heading("口径与边界"),
        "",
        "- 分位窗口 250 个交易日；观测 <60 不给分，60—249 记「短历史」，≥250 记 `ok`。",
        "- 五档边界：≤P20=0、P20–P40=25、P40–P60=50、P60–P80=75、>P80=100。",
        "- 权重 25/15/20/20/20；指标缺失时按剩余有效权重归一，不补 0。",
        "- 成分股有效覆盖率 <70% 的行业不参与排名。",
        "- 重点池要求总分 ≥70 且持续性分 ≥60；观察池为总分 50—69。",
        "- 四象限只用原始值判定（强度：量能 ≥1.20 且 5 日超额 >0；覆盖：上涨比例 ≥50%）。",
        "",
        f"**{result.get('disclaimer') or '以上为观察候选与剧本，不是买点。'}**",
        "",
        f"`{result.get('ruleVersion') and 'ruleVersion ' + str(result.get('ruleVersion')) or ''}` ｜ "
        f"`calibration {result.get('calibration') or 'needs-backtest'}` ｜ 未经回测，不构成投资建议。",
        "",
    ]
    return "\n".join(lines)


def default_report_path(json_path) -> Any:
    """Sibling ``.md`` path for a JSON output path."""

    from pathlib import Path

    path = Path(json_path)
    return path.with_suffix(".md") if path.suffix else path.with_name(path.name + ".md")