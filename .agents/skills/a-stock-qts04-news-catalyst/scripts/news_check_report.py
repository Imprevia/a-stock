"""Deterministic gate for a QTS-04 STEP 2.5 human-readable report.

Two layers:

1. Reuse ``qts04.check.validate`` for number provenance, forbidden trading
   wording, disclaimer / ``needs-backtest`` / data status.
2. Add news-specific checks: labels must be renderings of the JSON, an
   ``unknown`` unit must be written as 无法判定, an ``uncovered`` stock must be
   written as 未覆盖, and a missing primary source forbids 已证实/确认利好.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

SKILL_DIR = Path(__file__).resolve().parent.parent
_CORE = SKILL_DIR.parent / "qts04-core" / "scripts"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))
if str(SKILL_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))

from qts04.check import validate as validate_base  # noqa: E402

import news  # noqa: E402

POLARITY_LABELS = dict(news.POLARITY_LABELS)
RISK_LABELS = dict(news.RISK_LABELS)
DEFINITION_WORDS = ("规则", "定义", "口径", "分级", "阈值", "标签", "并非", "不是", "不等于")
PRIMARY_FORBIDDEN = ("已证实", "确认利好", "确认利空")
_REPORT_ID = re.compile(r"^[0-9a-f]{16}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _issue(check: str, detail: str, line: int | None = None) -> dict[str, Any]:
    return {"check": check, "detail": detail, "line": line, "column": None}


def _is_definition(line: str) -> bool:
    return any(word in line for word in DEFINITION_WORDS)


def _first_label(line: str, mapping: Mapping[str, str]) -> str | None:
    for label in sorted(set(mapping.values()), key=len, reverse=True):
        if label and label in line:
            return label
    return None


def check_result_contract(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if str(result.get("schemaVersion")) != news.SCHEMA_VERSION:
        issues.append(_issue("resultContract", f"schemaVersion 应为 {news.SCHEMA_VERSION}"))
    if str(result.get("step")) != news.STEP:
        issues.append(_issue("resultContract", f"step 应为 {news.STEP}"))
    if str(result.get("ruleVersion")) != news.RULE_VERSION:
        issues.append(_issue("resultContract", f"ruleVersion 应为 {news.RULE_VERSION}"))
    if not _REPORT_ID.match(str(result.get("reportId") or "")):
        issues.append(_issue("resultContract", "reportId 不是 16 位十六进制"))
    lexicon = result.get("lexicon") or {}
    if not _SHA256.match(str(lexicon.get("sha256") or "")):
        issues.append(_issue("resultContract", "lexicon.sha256 不是 64 位十六进制"))
    if result.get("primarySourceAvailable") is not False:
        issues.append(_issue("resultContract", "primarySourceAvailable 必须为 false"))
    if str(result.get("calibration")) != "needs-backtest":
        issues.append(_issue("resultContract", "calibration 必须为 needs-backtest"))

    for unit in result.get("units") or []:
        polarity = unit.get("polarity") or {}
        label = str(polarity.get("label") or "")
        if label not in POLARITY_LABELS:
            issues.append(_issue("resultContract", f"{unit.get('unitId')} 的极性标签非法：{label}"))
        if label == news.POLARITY_UNKNOWN and not polarity.get("missingReason"):
            issues.append(_issue("resultContract", f"{unit.get('unitId')} 为 unknown 但缺少 missingReason"))
    for stock in result.get("stocks") or []:
        risk = str(stock.get("riskLevel") or "")
        if risk not in RISK_LABELS:
            issues.append(_issue("resultContract", f"{stock.get('thscode')} 的风险标签非法：{risk}"))
        if risk == news.RISK_UNCOVERED and not stock.get("missingReason"):
            issues.append(_issue("resultContract", f"{stock.get('thscode')} 为 uncovered 但缺少 missingReason"))
    return issues


def check_coverage_wording(article: str, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    units = [unit for unit in result.get("units") or [] if isinstance(unit, Mapping)]
    stocks = [stock for stock in result.get("stocks") or [] if isinstance(stock, Mapping)]
    lines = article.splitlines()

    if any((unit.get("polarity") or {}).get("label") == news.POLARITY_UNKNOWN for unit in units):
        if "无法判定" not in article:
            issues.append(_issue("coverageWording", "存在无法判定的单元，正文缺少「无法判定」"))

    uncovered = [str(stock.get("thscode")) for stock in stocks if stock.get("riskLevel") == news.RISK_UNCOVERED]
    if uncovered:
        if "未覆盖" not in article:
            issues.append(_issue("coverageWording", "存在未覆盖个股，正文缺少「未覆盖」"))
        for index, line in enumerate(lines, 1):
            if any(code in line for code in uncovered) and "未覆盖" not in line:
                issues.append(
                    _issue("coverageWording", "未覆盖个股所在行必须写明「未覆盖」", index)
                )

    if uncovered:
        for index, line in enumerate(lines, 1):
            for match in re.finditer("无利空", line):
                window = line[max(0, match.start() - 6) : match.start()]
                if any(word in window for word in ("不等于", "并非", "不是", "不代表")):
                    continue
                issues.append(
                    _issue("coverageWording", "存在未覆盖个股时不得写「无利空」", index)
                )
                break
    return issues


def check_label_provenance(article: str, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    lines = article.splitlines()
    for unit in result.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        name = str(unit.get("name") or "").strip()
        expected = POLARITY_LABELS.get(str((unit.get("polarity") or {}).get("label") or ""))
        if not name or not expected:
            continue
        for index, line in enumerate(lines, 1):
            if name not in line or _is_definition(line):
                continue
            found = _first_label(line, POLARITY_LABELS)
            if found and found != expected:
                issues.append(
                    _issue("labelProvenance", f"{name} 的极性写作「{found}」，JSON 为「{expected}」", index)
                )
    for stock in result.get("stocks") or []:
        if not isinstance(stock, Mapping):
            continue
        code = str(stock.get("thscode") or "").strip()
        expected = RISK_LABELS.get(str(stock.get("riskLevel") or ""))
        if not code or not expected:
            continue
        for index, line in enumerate(lines, 1):
            if code not in line or _is_definition(line):
                continue
            found = _first_label(line, RISK_LABELS)
            if found and found != expected:
                issues.append(
                    _issue("labelProvenance", f"{code} 的风险写作「{found}」，JSON 为「{expected}」", index)
                )
    return issues


def check_primary_source(article: str, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if result.get("primarySourceAvailable") is False:
        for word in PRIMARY_FORBIDDEN:
            if word in article:
                issues.append(
                    _issue("primarySourceWording", f"主源不可用，正文不得出现「{word}」")
                )
    return issues


def check_required_news_conclusion(article: str, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    status = str(result.get("status") or "")
    if status == news.STATUS_INSUFFICIENT:
        if "数据不足" not in article:
            issues.append(_issue("requiredNewsConclusion", "数据不足时正文必须写明「数据不足」"))
        if not any(word in article for word in ("不产出结论", "无法给出结论", "没有可分析", "不产出方向")):
            issues.append(
                _issue("requiredNewsConclusion", "数据不足时须写明本次不产出结论")
            )
        if not any(word in article for word in ("原因", "因为", "由于", "缺少", "没有")):
            issues.append(_issue("requiredNewsConclusion", "数据不足时须说明原因"))
    elif result.get("units") and "置信" not in article:
        issues.append(_issue("requiredNewsConclusion", "正文缺少置信度说明"))
    return issues


def validate_report(result: Mapping[str, Any], article: str) -> dict[str, Any]:
    base = validate_base(result, article)
    # STEP 2.5 has no direction payload; the generic "不产出方向" requirement
    # is replaced by the news-specific conclusion check below.
    base_issues = [
        issue
        for issue in base.get("issues") or []
        if issue.get("check") != "requiredNoDirectionReason"
    ]
    checks: list[dict[str, Any]] = []
    for check in base.get("checks") or []:
        name = str(check.get("name"))
        matched = [
            issue
            for issue in base_issues
            if issue.get("check") == name
            or (name == "requiredItems" and str(issue.get("check")).startswith("required"))
        ]
        checks.append({"name": name, "status": "fail" if matched else "pass", "issues": len(matched)})
    issues: list[dict[str, Any]] = list(base_issues)
    news_checks = {
        "resultContract": check_result_contract(result),
        "coverageWording": check_coverage_wording(article, result),
        "labelProvenance": check_label_provenance(article, result),
        "primarySourceWording": check_primary_source(article, result),
        "requiredNewsConclusion": check_required_news_conclusion(article, result),
    }
    for name, found in news_checks.items():
        checks.append({"name": name, "status": "fail" if found else "pass", "issues": len(found)})
        issues.extend(found)
    issues.sort(
        key=lambda item: (
            item.get("line") or 0,
            item.get("check") or "",
            item.get("detail") or "",
        )
    )
    return {
        "status": "pass" if not issues else "fail",
        "checks": checks,
        "issues": issues,
        "resultStatus": result.get("status"),
        "reportId": result.get("reportId"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 QTS-04 STEP 2.5 消息面报告")
    parser.add_argument("--result", type=Path, required=True, help="JSON 结果")
    parser.add_argument("--article", type=Path, required=True, help="人读报告 markdown")
    parser.add_argument("--json", action="store_true", help="输出机器可读判定")
    args = parser.parse_args(argv)

    try:
        result = json.loads(args.result.read_text(encoding="utf-8"))
        article = args.article.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as error:
        print(f"输入不可读：{error}", file=sys.stderr)
        return 2
    if not isinstance(result, Mapping):
        print("JSON 顶层必须是对象", file=sys.stderr)
        return 2

    verdict = validate_report(result, article)
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"判定：{verdict['status']}")
        for check in verdict["checks"]:
            print(f"- {check['name']}: {check['status']}（{check['issues']}）")
        for issue in verdict["issues"]:
            location = f"第 {issue['line']} 行" if issue.get("line") else "全局"
            print(f"  · {location} [{issue['check']}] {issue['detail']}")
    return 0 if verdict["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
