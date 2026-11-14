"""Fact skeleton for the QTS-04 STEP 2 theme layer."""

from __future__ import annotations

import itertools
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

DASH = "—"

STATUS_LABEL = {
    "ok": "数据完整",
    "degraded": "数据降级",
    "insufficient": "数据不足",
}
TIER_LABEL = {
    "core": "核心题材",
    "diffuse": "扩散题材",
    "event": "事件题材",
    "pseudo": "伪题材",
}
CATALYST_LABEL = {
    "confirmed": "已证实",
    "partial": "部分证实",
    "speculative": "市场推测",
    "unknown": "原因不明",
}
CONFIDENCE_LABEL = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "insufficient": "不足",
}


def label_map() -> dict[str, dict[str, str]]:
    return {"tier": dict(TIER_LABEL), "catalyst": dict(CATALYST_LABEL)}


def _num(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return DASH
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return DASH


def _pct(value: Any, digits: int = 1) -> str:
    if value is None or value == "":
        return DASH
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return DASH


def _text(value: Any) -> str:
    text = str(value or "").strip()
    return text or DASH


def render_markdown(result: Mapping[str, Any]) -> str:
    as_of = result.get("asOf") or DASH
    status = str(result.get("status") or DASH)
    themes = [row for row in result.get("themes") or [] if isinstance(row, Mapping)]
    quality = result.get("quality") or {}
    no_core = bool(result.get("noCoreTheme"))

    lines = [
        f"# 题材层事实骨架 · {as_of}",
        "",
        "> 这是事实骨架：agent 撰文的底稿与无模型兜底，不是对外主报告；对外文章必须通过 `theme_check_report.py` 校验。",
        "> 规则族 `QTS-04-02`（STEP 2 题材层）｜ 题材单元 = 概念成分股 ∩ 当日涨停池 ｜ 只做 `cn_concept` 标签",
        "> 数据源 {} ｜ 生成 {} ｜ 状态 **{}**（{}）".format(
            result.get("source") or DASH,
            str(result.get("generatedAt") or DASH)[:19].replace("T", " "),
            status,
            STATUS_LABEL.get(status, status),
        ),
        "> 契约 `{}` ｜ step `{}` ｜ reportId `{}`".format(
            result.get("schemaVersion") or DASH,
            result.get("step") or DASH,
            result.get("reportId") or DASH,
        ),
        "> 催化主源不可枚举：`confirmed` 在 v1 不可达；分级与 lift 均为 `needs-backtest`。",
        "",
    ]

    section = itertools.count(1)
    numerals = "一二三四五六七八九"

    def heading(title: str) -> str:
        index = next(section) - 1
        label = numerals[index] if index < len(numerals) else str(index + 1)
        return f"## {label}、{title}"

    lines += [heading("结论"), ""]
    if status == "insufficient":
        lines += ["本次**不产出题材**。", ""]
    elif no_core:
        lines += ["今日**没有核心题材**。", ""]
        reasons = list(result.get("noCoreReasons") or [])
        if reasons:
            lines += ["原因：", ""]
            lines += [f"- {reason}" for reason in reasons]
            lines.append("")
    else:
        lines += ["今日有核心题材；以下分级只描述当日证据强度，不是买点。", ""]

    if themes:
        lines += [
            "| 题材 | 分级 | 分数 | lift | 涨停成员 | 共享 token | 催化 |",
            "|---|---|---:|---:|---:|---|---|",
        ]
        for theme in themes:
            shared = theme.get("members", {}).get("sharedTokens") or []
            lines.append(
                "| {} | {} | {} | {} | {} | {} | {} |".format(
                    _text(theme.get("name")),
                    TIER_LABEL.get(str(theme.get("tier")), DASH),
                    _num(theme.get("score"), 1),
                    _num(theme.get("lift")),
                    _num(theme.get("observed"), 0),
                    _text(shared[0].get("token") if shared else None),
                    CATALYST_LABEL.get(
                        str((theme.get("catalyst") or {}).get("label")), DASH
                    ),
                )
            )
        lines.append("")

    if themes:
        lines += [heading("题材明细"), ""]
        for index, theme in enumerate(themes, 1):
            lines += _theme_section(index, theme, label_map())

    lines += [heading("数据质量"), ""]
    lines += [
        "| 项目 | 数值 |",
        "|---|---:|",
        f"| 概念目录 | {quality.get('conceptCatalogCount', DASH)} |",
        f"| 候选概念 | {quality.get('candidateConcepts', DASH)} |",
        f"| 当日涨停 | {quality.get('limitUpCount', DASH)} |",
        f"| 入选题材 | {len(themes)} |",
        f"| 已映射 token | {quality.get('mappedTokens', DASH)} |",
        f"| 未映射 token | {quality.get('unmappedTokens', DASH)} |",
        f"| point-in-time | {quality.get('pointInTime', DASH)} |",
        f"| 成分股口径 | {_text(quality.get('membershipBasis'))} |",
        f"| 回测等级 | {_text(quality.get('backtestGrade'))} |",
        "",
    ]
    gaps = [row for row in quality.get("membershipGap") or [] if isinstance(row, Mapping)]
    if gaps:
        lines += ["成员缺口（成分股当前快照 vs 当日有行情成员）：", ""]
        lines += [
            "| 题材 | 成员数 | 采样 | 有行情 | 缺口 | 口径 |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for row in gaps:
            lines.append(
                "| {} | {} | {} | {} | {} | {} |".format(
                    _text(row.get("name")),
                    row.get("memberCount", DASH),
                    row.get("sampled", DASH),
                    row.get("active", DASH),
                    row.get("value", DASH),
                    _text(row.get("basis")),
                )
            )
        lines.append("")
    warnings = list(quality.get("warnings") or [])
    if warnings:
        lines += ["告警：", ""]
        lines += [f"- {warning}" for warning in warnings]
        lines.append("")

    config = result.get("config") or {}
    tiers = config.get("tiers") or {}
    core = tiers.get("core") or {}
    diffuse = tiers.get("diffuse") or {}
    shared_min = config.get("sharedTokenMin", DASH)
    core_ladder = core.get("ladderDepth", DASH)
    core_observed = core.get("observedFloor", DASH)
    lines += [heading("口径与边界"), ""]
    lines += [
        "- 题材单元：概念当前成分股 ∩ 当日涨停池；单只概念成员不算题材。",
        f"- 共享 token 只在上述交集内部统计，`count ≥ {shared_min}` 才计入；停用词与跨概念属性词不产生催化。",
        "- `lift = 命中涨停成员数 / (成员数 × 全市场涨停率)`；全市场涨停率 = 当日涨停数 / 市场股票数。",
        "- 核心题材闸门：分数 ≥{}、lift ≥{}、共享 token ≥{}、最高连板 ≥{} 或涨停成员 ≥{}；任一不满足即降级。".format(
            core.get("totalScore", DASH),
            core.get("lift", DASH),
            core.get("sharedTokenMin", DASH),
            core_ladder,
            core_observed,
        ),
        "- 扩散题材闸门：分数 ≥{}、lift ≥{}、涨停成员 ≥{}；lift 低于 {} 记伪题材。".format(
            diffuse.get("totalScore", DASH),
            diffuse.get("lift", DASH),
            diffuse.get("observedFloor", DASH),
            diffuse.get("lift", DASH),
        ),
        "- 催化四档：`confirmed` / `partial` / `speculative` / `unknown`；主源不可枚举，`confirmed` 在 v1 不可达。",
        "- 成分股只有当前快照，历史日期无法还原当时成员；`backtestGrade` 因此为 D。",
        "- 涨停池约 1 年、异动解读约 2 年；缺失数据输出 `insufficient`，不借相邻日期。",
        "",
        f"**{result.get('disclaimer') or '以上为盘后题材观察与剧本，不是买点。'}**",
        "",
        f"`ruleVersion {result.get('ruleVersion') or DASH}` ｜ "
        f"`calibration {result.get('calibration') or 'needs-backtest'}` ｜ 未经回测，不构成投资建议。",
        "",
    ]
    return "\n".join(lines)


def _theme_section(index: int, theme: Mapping[str, Any], labels: Mapping[str, Mapping[str, str]]) -> list[str]:
    concept = theme.get("concept") or {}
    catalyst = theme.get("catalyst") or {}
    members = theme.get("members") or {}
    shared = [row for row in members.get("sharedTokens") or [] if isinstance(row, Mapping)]
    limit_up = [row for row in members.get("limitUp") or [] if isinstance(row, Mapping)]
    direction = theme.get("direction") or {}

    lines = [
        f"### {index}. {_text(theme.get('name'))}（{_text(concept.get('thscode'))}）",
        "",
        "- 分级：**{}** ｜ 分数：{} ｜ lift：{} ｜ 置信：{} ｜ 状态：{}".format(
            labels["tier"].get(str(theme.get("tier")), DASH),
            _num(theme.get("score"), 1),
            _num(theme.get("lift")),
            CONFIDENCE_LABEL.get(str(theme.get("confidence")), DASH),
            _text(theme.get("status")),
        ),
        "- 成员：{} 只 ｜ 涨停成员：{} 只 ｜ 期望命中：{} 只".format(
            concept.get("memberCount", DASH),
            theme.get("observed", DASH),
            _num(theme.get("expected")),
        ),
        "- 催化：**{}**（{}）".format(
            labels["catalyst"].get(str(catalyst.get("label")), DASH),
            _text(catalyst.get("reason")),
        ),
        "",
    ]
    if direction:
        lines += [
            "- 与 STEP 1 方向「{}」的成员 Jaccard：{}".format(
                _text(direction.get("name")),
                _num(direction.get("overlapJaccard"), 3),
            )
        ]
        lines.append("")

    metrics = [row for row in theme.get("metrics") or [] if isinstance(row, Mapping)]
    if metrics:
        lines += [
            "| 指标 | 数值 | 分数 | 权重 | 状态 |",
            "|---|---:|---:|---:|---|",
        ]
        for metric in metrics:
            lines.append(
                "| {} | {} | {} | {} | {} |".format(
                    _text(metric.get("name")),
                    _num(metric.get("value"), 4),
                    _num(metric.get("score"), 0),
                    _num(metric.get("weight"), 2),
                    _text(metric.get("status")),
                )
            )
        lines.append("")

    if shared:
        lines += ["共享 token：", ""]
        lines += [
            f"- `{_text(row.get('token'))}`：{row.get('count', DASH)} 只成员（{', '.join(row.get('holders') or [])}）"
            for row in shared
        ]
        lines.append("")

    if limit_up:
        lines += ["涨停成员：", ""]
        lines += [
            "- {} {}：{}（{} 连板）".format(
                _text(row.get("thscode")),
                _text(row.get("name")),
                _text(row.get("reason")),
                row.get("continueDay", DASH),
            )
            for row in limit_up
        ]
        lines.append("")

    sources = [row for row in catalyst.get("sources") or [] if isinstance(row, Mapping)]
    if sources:
        lines += ["催化来源：", ""]
        lines += [
            "- {} ｜ {} ｜ {}{}".format(
                _text(row.get("type")),
                _text(row.get("ref")),
                _text(row.get("token") or row.get("thscode")),
                f" ｜ {_text(row.get('tagName'))}" if row.get("tagName") else "",
            )
            for row in sources
        ]
        lines.append("")

    confirmation = theme.get("confirmation")
    invalidation = theme.get("invalidation")
    if confirmation or invalidation:
        lines += ["次日剧本：", ""]
        if confirmation:
            lines.append(f"- 确认：{_text(confirmation.get('text'))}")
        if invalidation:
            lines.append(f"- 失效：{_text(invalidation.get('text'))}")
        lines.append("")
    return lines


def render_fallback(result: Mapping[str, Any], issues: Sequence[Mapping[str, Any]] = ()) -> str:
    lines = ["> 文章未通过校验，以下为事实骨架", ""]
    if issues:
        lines.append("未通过项：")
        lines.append("")
        for issue in issues:
            detail = str(issue.get("detail") or "").strip()
            line = issue.get("line")
            column = issue.get("column")
            location = f"（第 {line} 行第 {column} 列）" if line and column else ""
            lines.append(f"- {detail}{location}")
        lines.append("")
    return "\n".join(lines) + "\n" + render_markdown(result)


def default_report_path(json_path: Path | None) -> Path | None:
    if json_path is None:
        return None
    return Path(json_path).with_suffix(".md")
