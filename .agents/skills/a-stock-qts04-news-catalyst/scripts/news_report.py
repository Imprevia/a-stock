"""Deterministic fact sheet for QTS-04 STEP 2.5.

The markdown produced here is a skeleton: it only restates JSON fields and is
also the fallback when an agent-written report fails validation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import news

STATUS_LABELS = {
    "ok": "正常",
    "degraded": "降级",
    "insufficient": "数据不足",
    "empty": "空结果",
    "unavailable": "不可用",
    "disabled": "未启用",
}
SOURCE_LABELS = {
    "anomalyAnalysis": "异动解读",
    "limitUpReason": "涨停原因",
    "stockTimeline": "个股新闻",
}


def _label_polarity(polarity: Mapping[str, Any] | None) -> str:
    payload = polarity or {}
    label = str(payload.get("label") or news.POLARITY_UNKNOWN)
    return news.POLARITY_LABELS.get(label, label)


def _label_risk(level: Any) -> str:
    key = str(level or news.RISK_UNCOVERED)
    return news.RISK_LABELS.get(key, key)


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "-"


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _unit_events(unit: Mapping[str, Any], limit: int = 2) -> str:
    rows = []
    for event in (unit.get("events") or [])[:limit]:
        rows.append(f"{event.get('eventType')}（{event.get('severity')}）")
    return "；".join(rows) if rows else "-"


def _stock_events(stock: Mapping[str, Any], limit: int = 2) -> str:
    rows = []
    for flag in (stock.get("flags") or [])[:limit]:
        rows.append(f"{flag.get('eventType')}（{flag.get('severity')}）")
    return "；".join(rows) if rows else "-"


def _source_line(name: str, payload: Mapping[str, Any]) -> str:
    status = str(payload.get("status") or "unknown")
    label = STATUS_LABELS.get(status, status)
    parts = [f"`{name}` {label}"]
    if payload.get("count") is not None:
        parts.append(f"{payload.get('count')} 条")
    if payload.get("reason"):
        parts.append(re.sub(r"\d+", "*", str(payload.get("reason"))).replace("\n", " "))
    if payload.get("probed"):
        parts.append(f"探测 {len(payload.get('probed'))} 只")
    return "，".join(parts)


def render_markdown(result: Mapping[str, Any]) -> str:
    as_of = result.get("asOf")
    status = str(result.get("status") or "unknown")
    quality = result.get("quality") or {}
    sources = quality.get("sources") or {}
    coverage = quality.get("coverage") or {}
    config = result.get("config") or {}
    lexicon = result.get("lexicon") or {}
    units = result.get("units") or []
    stocks = result.get("stocks") or []
    evidence = result.get("evidence") or []

    lines: list[str] = []
    lines.append(f"# QTS-04 消息面极性报告（{as_of}）")
    lines.append("")
    lines.append(
        f"> 报告 ID `{result.get('reportId')}`｜规则 `{result.get('ruleVersion')}`｜"
        f"状态 **{STATUS_LABELS.get(status, status)}（{status}）**｜校准 `{result.get('calibration')}`"
    )
    lines.append(
        f"> 词表 v{lexicon.get('version') or '未知'}｜回看 {config.get('lookbackDays') or '-'} 自然日｜"
        f"交易日历 {coverage.get('calendar') or '-'}"
    )
    lines.append("")

    lines.append("## 一、数据状态")
    lines.append("")
    lines.append("| 来源 | 状态 |")
    lines.append("|---|---|")
    for key, payload in sources.items():
        lines.append(f"| {SOURCE_LABELS.get(key, key)} | {_source_line(key, payload or {})} |")
    lines.append("")
    lines.append(
        f"- 证据 {coverage.get('evidenceItems', 0)} 条，去重 {coverage.get('duplicates', 0)} 条，"
        f"无法归属 {coverage.get('unattributed', 0)} 条。"
    )
    lines.append(f"- 主源不可用：{result.get('primarySourceReason')}")
    if status == "insufficient":
        reason = (quality.get("warnings") or [result.get("primarySourceReason")])[0]
        lines.append(f"- 数据不足，本次不产出结论。原因：{reason}")
    if quality.get("warnings"):
        lines.append("- 取数告警：")
        for warning in quality.get("warnings") or []:
            safe_warning = re.sub(r"\d+", "*", str(warning)).replace("\n", " ")
            safe_warning = safe_warning.split("{", 1)[0].strip()
            lines.append(f"  - {safe_warning[:200]}")
    lines.append("")

    lines.append("## 二、单元极性")
    lines.append("")
    if not units:
        lines.append("本轮没有可分析的板块/题材单元。")
    else:
        lines.append("| 单元 | 类型 | 极性 | 置信度 | 证据 | 成员覆盖 | 主要事件 |")
        lines.append("|---|---|---|---|---|---|---|")
        for unit in units:
            polarity = unit.get("polarity") or {}
            label = _label_polarity(polarity)
            if polarity.get("label") == news.POLARITY_UNKNOWN and polarity.get("missingReason"):
                label = f"{label}（{polarity.get('missingReason')}）"
            members = unit.get("members") or {}
            coverage_text = f"{unit.get('coveredMembers', 0)}/{members.get('count', 0)}"
            lines.append(
                f"| {_cell(unit.get('name') or unit.get('unitId'))} | {unit.get('unitType')} | "
                f"{label} | {polarity.get('confidence', '-')} | {unit.get('evidenceCount', 0)} | "
                f"{coverage_text} | {_cell(_unit_events(unit))} |"
            )
    lines.append("")

    lines.append("## 三、个股风险")
    lines.append("")
    if not stocks:
        lines.append("本轮没有个股单元。")
    else:
        lines.append("| 代码 | 名称 | 风险 | 极性 | 证据 | 主要事项 |")
        lines.append("|---|---|---|---|---|---|")
        for stock in stocks:
            risk = str(stock.get("riskLevel") or news.RISK_UNCOVERED)
            risk_text = _label_risk(risk)
            if risk == news.RISK_UNCOVERED:
                risk_text = "未覆盖（不代表没有利空）"
            if risk == news.RISK_BLOCK:
                risk_text = f"{risk_text}（仅提示，不自动排除）"
            lines.append(
                f"| {stock.get('thscode')} | {_cell(stock.get('name') or '-')} | {risk_text} | "
                f"{_label_polarity(stock.get('polarity'))} | {stock.get('evidenceCount', 0)} | "
                f"{_cell(_stock_events(stock))} |"
            )
    lines.append("")

    lines.append("## 四、证据摘要")
    lines.append("")
    if not evidence:
        lines.append("窗口内没有归属证据；所有单元与个股只能标记为无法判定或未覆盖。")
    else:
        ranked = sorted(
            evidence,
            key=lambda item: (str(item.get("date")), str(item.get("thscode"))),
            reverse=True,
        )[:12]
        for item in ranked:
            events = [
                str(event.get("eventType"))
                for event in (item.get("events") or [])
                if event.get("active", True)
            ][:3]
            suffix = f"事件：{'、'.join(events)}" if events else "无结构化事件"
            lines.append(
                f"- {item.get('date')} · `{item.get('thscode')}` · {item.get('source')}｜{suffix}"
            )
    lines.append("")

    lines.append("## 五、边界")
    lines.append("")
    lines.append("- 极性只表示文本方向，不预测收益，也不构成投资建议。")
    lines.append("- `无法判定` 与 `未覆盖` 都不是 `中性` 或 `未见利空`；它们表示证据不足。")
    lines.append("- 硬否决只是提示，规则状态为 `needs-backtest`，未通过校准前不自动排除。")
    lines.append(f"- {result.get('disclaimer')}")
    return "\n".join(lines) + "\n"


def render_fallback(result: Mapping[str, Any]) -> str:
    """Plain fact skeleton used when an agent-written report fails validation."""

    body = render_markdown(result)
    note = "> 自动降级：以下仅列事实骨架，未通过人工报告校验。\n\n"
    return note + body


def default_report_path(output: Path | None) -> Path | None:
    if output is None:
        return None
    return Path(output).with_suffix(".md")
