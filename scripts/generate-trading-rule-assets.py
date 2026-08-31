"""Generate the chapter 01 YAML registry and full documentation coverage index."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.trading_system.rules.coverage import write_coverage

CHAPTER_ROOT = ROOT / "搭建交易系统-量化版" / "01-如何判断市场环境"
RULE_PATTERN = re.compile(r"^\| `(QTS-[0-9]{2}-[0-9]{2}-[0-9]{2})` \| ([^|]+) \|")


def positive_percentile() -> list[dict[str, Any]]:
    return [
        {"lte": 0.2, "score": 0},
        {"lte": 0.4, "score": 25},
        {"lte": 0.6, "score": 50},
        {"lte": 0.8, "score": 75},
        {"gt": 0.8, "score": 100},
    ]


def negative_percentile() -> list[dict[str, Any]]:
    return [
        {"lte": 0.2, "score": 100},
        {"lte": 0.4, "score": 75},
        {"lte": 0.6, "score": 50},
        {"lte": 0.8, "score": 25},
        {"gt": 0.8, "score": 0},
    ]


def score_bands() -> list[dict[str, Any]]:
    return [
        {"lte": 20, "score": 0},
        {"lte": 40, "score": 25},
        {"lte": 60, "score": 50},
        {"lte": 80, "score": 75},
        {"gt": 80, "score": 100},
    ]


def ratio_bands() -> list[dict[str, Any]]:
    return positive_percentile()


def documented_rules() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for path in sorted(CHAPTER_ROOT.glob("*.md")):
        document_ref = path.relative_to(ROOT).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            match = RULE_PATTERN.match(line)
            if match:
                result[match.group(1)] = {"title": match.group(2).strip(), "documentRef": document_ref}
    if len(result) != 46:
        raise RuntimeError(f"expected 46 chapter 01 rules, found {len(result)}")
    return result


def base_specs() -> dict[str, dict[str, Any]]:
    positive = positive_percentile()
    negative = negative_percentile()
    ratio = ratio_bands()
    specs: dict[str, dict[str, Any]] = {
        "QTS-01-01-01": {"metric": "index.bullish_ratio", "windows": [20], "weight": 0.25, "bands": ratio},
        "QTS-01-01-02": {"metric": "index.ma20_slope_percentile", "windows": [5, 20, 250], "weight": 0.20, "bands": positive},
        "QTS-01-01-03": {"metric": "index.range_position_60", "windows": [60], "weight": 0.15, "bands": ratio, "provenance": "fixed"},
        "QTS-01-01-04": {"metric": "market.turnover_ratio_20", "windows": [20], "weight": 0.20, "bands": [{"lte": 0.8, "score": 25}, {"lte": 1.0, "score": 50}, {"lte": 1.2, "score": 75}, {"gt": 1.2, "score": 100}]},
        "QTS-01-01-05": {"metric": "index.volume_price_efficiency_percentile", "windows": [20, 250], "weight": 0.20, "bands": positive, "vetoes": [("risk.volume_breakdown_unrecovered", "truthy", True, "放量跌破 MA20 且次日未收回")]},
        "QTS-01-02-01": {"metric": "breadth.advance_ratio_percentile", "windows": [250], "weight": 0.30, "bands": positive},
        "QTS-01-02-02": {"metric": "breadth.advance_decline_spread_percentile", "windows": [250], "weight": 0.20, "bands": positive},
        "QTS-01-02-03": {"metric": "breadth.median_return_percentile", "windows": [250], "weight": 0.30, "bands": positive},
        "QTS-01-02-04": {"metric": "breadth.momentum_percentile", "windows": [6, 250], "weight": 0.10, "bands": positive},
        "QTS-01-02-05": {"metric": "breadth.index_consistent", "windows": [1], "weight": 0.10, "bands": [{"equals": False, "score": 0}, {"equals": True, "score": 100}], "evaluator": "metric.boolean", "provenance": "fixed"},
        "QTS-01-03-01": {"metric": "limits.limit_up_count_percentile", "windows": [250], "weight": 0.20, "bands": positive},
        "QTS-01-03-02": {"metric": "limits.limit_down_count_percentile", "windows": [250], "weight": 0.25, "bands": negative, "direction": "negative", "vetoes": [("risk.limit_down_extreme_two_days", "truthy", True, "跌停家数高于 P80 且连续两日")]},
        "QTS-01-03-03": {"metric": "limits.failed_limit_up_ratio_percentile", "windows": [250], "weight": 0.20, "bands": negative, "direction": "negative"},
        "QTS-01-03-04": {"metric": "limits.promotion_ratio_percentile", "windows": [250], "weight": 0.25, "bands": positive},
        "QTS-01-03-05": {"metric": "limits.max_streak_percentile", "windows": [250], "weight": 0.10, "bands": positive},
        "QTS-01-04-01": {"metric": "risk.high_tier_loss_percentile", "windows": [250], "weight": 0.40, "bands": positive, "vetoes": [("risk.high_tier_batch_limit_down", "truthy", True, "高位核心批量跌停")]},
        "QTS-01-04-02": {"metric": "risk.middle_tier_loss_percentile", "windows": [250], "weight": 0.35, "bands": positive},
        "QTS-01-04-03": {"metric": "risk.low_tier_feedback_percentile", "windows": [250], "weight": 0.15, "bands": positive},
        "QTS-01-04-04": {"metric": "risk.failure_repair_ratio_percentile", "windows": [250], "weight": 0.10, "bands": negative, "direction": "negative"},
        "QTS-01-05-01": {"metric": "sector.relative_strength_percentile", "windows": [5, 20, 250], "weight": 0.25, "bands": positive},
        "QTS-01-05-02": {"metric": "sector.top_turnover_days", "windows": [5], "weight": 0.20, "bands": [{"equals": 0, "score": 0}, {"equals": 1, "score": 25}, {"equals": 2, "score": 50}, {"equals": 3, "score": 75}, {"gte": 4, "score": 100}]},
        "QTS-01-05-03": {"metric": "sector.above_ma20_ratio_percentile", "windows": [250], "weight": 0.20, "bands": positive},
        "QTS-01-05-04": {"metric": "sector.disagreement_recovery_percentile", "windows": [20, 250], "weight": 0.20, "bands": positive},
        "QTS-01-05-05": {"metric": "sector.top5_turnover_concentration_percentile", "windows": [250], "weight": 0.15, "bands": positive, "vetoes": [("risk.sector_crowding_without_breadth", "truthy", True, "成交集中但板块宽度不足，标记抱团风险")]},
        "QTS-01-06-01": {"metric": "active.direction_cluster_percentile", "windows": [250], "weight": 0.25, "bands": positive},
        "QTS-01-06-02": {"metric": "active.turnover_expansion_percentile", "windows": [20, 250], "weight": 0.20, "bands": positive},
        "QTS-01-06-03": {"metric": "active.excess_return_percentile", "windows": [250], "weight": 0.20, "bands": positive},
        "QTS-01-06-04": {"metric": "active.close_position", "windows": [1], "weight": 0.15, "bands": ratio, "provenance": "fixed"},
        "QTS-01-06-05": {"metric": "active.sector_sync_percentile", "windows": [250], "weight": 0.20, "bands": positive, "vetoes": [("risk.active_stall_breakdown", "truthy", True, "容量股巨量滞涨且次日跌破")]},
        "QTS-01-07-01": {"metric": "event.source_reliability", "windows": [0], "weight": 0.30, "bands": [{"equals": 0, "score": 0}, {"equals": 1, "score": 25}, {"equals": 2, "score": 50}, {"equals": 3, "score": 75}, {"gte": 4, "score": 100}], "provenance": "fixed", "scope": "event"},
        "QTS-01-07-02": {"metric": "event.age_hours", "windows": [0], "weight": 0.15, "bands": [{"lte": 24, "score": 100}, {"lte": 72, "score": 75}, {"lte": 120, "score": 50}, {"lte": 480, "score": 25}, {"gt": 480, "score": 0}], "scope": "event"},
        "QTS-01-07-03": {"metric": "event.price_turnover_confirmation", "windows": [5], "weight": 0.30, "bands": score_bands(), "scope": "event"},
        "QTS-01-07-04": {"metric": "event.sector_diffusion_confirmation", "windows": [5], "weight": 0.15, "bands": score_bands(), "scope": "event"},
        "QTS-01-07-05": {"metric": "event.next_day_acceptance_percentile", "windows": [1, 250], "weight": 0.10, "bands": positive, "scope": "event", "vetoes": [("event.source_reliability", "eq", 0, "来源可靠性为 0，事件方向不得加分")]},
        "QTS-01-08-02": {"metric": "environment.evidence_consistency_count", "windows": [1], "weight": 0.20, "bands": [{"equals": 0, "score": 0}, {"equals": 1, "score": 25}, {"equals": 2, "score": 75}, {"gte": 3, "score": 100}], "provenance": "fixed"},
        "QTS-01-08-03": {"metric": "environment.classification_streak", "windows": [3], "weight": 0.10, "bands": [{"lte": 0, "score": 0}, {"equals": 1, "score": 25}, {"equals": 2, "score": 75}, {"gte": 3, "score": 100}], "vetoes": [("risk.systemic", "truthy", True, "系统性风险否决环境分类")]},
        "QTS-01-09-04": {"metric": "review.completeness_ratio", "windows": [1], "weight": 0.0, "bands": [{"lt": 0.5, "score": 0}, {"lt": 0.7, "score": 25}, {"lt": 0.9, "score": 50}, {"lt": 1.0, "score": 75}, {"gte": 1.0, "score": 100}], "provenance": "fixed", "scope": "review"},
    }
    return specs


def aggregate_specs() -> dict[str, dict[str, Any]]:
    return {
        "QTS-01-00-01": {"members": [f"QTS-01-01-{index:02d}" for index in range(1, 6)], "weight": 0.30},
        "QTS-01-00-02": {"members": [f"QTS-01-02-{index:02d}" for index in range(1, 6)], "weight": 0.25},
        "QTS-01-00-03": {"members": [f"QTS-01-03-{index:02d}" for index in range(1, 6)], "weight": 0.20},
        "QTS-01-00-04": {"members": [f"QTS-01-04-{index:02d}" for index in range(1, 5)], "weight": 0.15, "invert": True, "vetoes": [("risk.all_tiers_deteriorating", "truthy", True, "高、中、低位样本同时恶化")]},
        "QTS-01-00-05": {"members": [*[f"QTS-01-05-{index:02d}" for index in range(1, 6)], *[f"QTS-01-06-{index:02d}" for index in range(1, 6)]], "weight": 0.10},
        "QTS-01-08-01": {"members": [f"QTS-01-00-{index:02d}" for index in range(1, 6)], "memberWeights": {"QTS-01-00-01": 0.30, "QTS-01-00-02": 0.25, "QTS-01-00-03": 0.20, "QTS-01-00-04": 0.15, "QTS-01-00-05": 0.10}, "weight": 0.70},
        "QTS-01-09-01": {"members": ["QTS-01-00-01", "QTS-01-00-02"], "weight": 0.35},
        "QTS-01-09-02": {"members": ["QTS-01-00-03", "QTS-01-00-04"], "weight": 0.35, "vetoes": [("risk.emotion_chain", "truthy", True, "情绪风险链触发否决")]},
        "QTS-01-09-03": {"members": ["QTS-01-00-05"], "weight": 0.30},
    }


def make_rule(rule_id: str, documented: dict[str, dict[str, str]], spec: dict[str, Any], aggregate: bool) -> dict[str, Any]:
    metadata = documented[rule_id]
    vetoes = [
        {"input": item[0], "operator": item[1], "value": item[2], "reason": item[3]}
        for item in spec.get("vetoes", [])
    ]
    parameters: dict[str, Any] = {}
    inputs: list[str] = []
    evaluator = spec.get("evaluator", "aggregate.rules" if aggregate else "metric.band")
    if aggregate:
        parameters = {key: value for key, value in spec.items() if key in {"members", "memberWeights", "invert"}}
    else:
        inputs = [spec["metric"]]
        parameters = {"formulaSource": metadata["documentRef"]}
    return {
        "ruleId": rule_id,
        "version": 1,
        "title": metadata["title"],
        "status": "defined",
        "scope": spec.get("scope", "market"),
        "evaluator": evaluator,
        "inputs": inputs,
        "windows": spec.get("windows", [1]),
        "parameters": parameters,
        "thresholds": {"provenance": spec.get("provenance", "empirical-initial"), "bands": spec.get("bands", score_bands())},
        "scoring": {"weight": spec["weight"], "direction": spec.get("direction", "positive")},
        "vetoes": vetoes,
        "missingData": "insufficient" if aggregate else "reduce-confidence",
        "outputs": ["score", "trace"],
        "documentRefs": [metadata["documentRef"]],
        "evidenceRefs": [],
    }


def main() -> None:
    documented = documented_rules()
    base = base_specs()
    aggregates = aggregate_specs()
    if set(documented) != set(base) | set(aggregates):
        missing = sorted(set(documented) - set(base) - set(aggregates))
        extra = sorted((set(base) | set(aggregates)) - set(documented))
        raise RuntimeError(f"rule mapping mismatch; missing={missing}, extra={extra}")
    rules = [
        make_rule(rule_id, documented, aggregates.get(rule_id, base.get(rule_id, {})), rule_id in aggregates)
        for rule_id in sorted(documented)
    ]
    output = ROOT / "trading-rules" / "rule-sets" / "market-environment.yaml"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump({"ruleSet": "market-environment", "version": 1, "rules": rules}, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    write_coverage(ROOT)
    print(f"generated {len(rules)} executable rules and trading-rules/coverage.yaml")


if __name__ == "__main__":
    main()
