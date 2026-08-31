from __future__ import annotations

import copy
import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml
from jsonschema import ValidationError

from src.trading_system.backtest.runner import run_backtest, validate_validation_evidence
from src.trading_system.cli import run
from src.trading_system.data.canonical import canonical_json_bytes, load_snapshot, sha256_value, validate_event
from src.trading_system.data.providers import FallbackChain, ProviderFailure, SerialRateLimiter, create_after_market_snapshot
from src.trading_system.evaluation.engine import evaluate_rule_set
from src.trading_system.evidence.bundle import create_evidence_bundle, verify_evidence_bundle
from src.trading_system.rules.coverage import scan_documented_rules, validate_coverage
from src.trading_system.rules.models import RuleValidationError
from src.trading_system.rules.registry import load_rule_sets, validate_registry

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "trading-system"


def complete_snapshot() -> dict:
    return json.loads((FIXTURE_DIR / "market-environment-complete.json").read_text(encoding="utf-8"))


def market_rule_set():
    return load_rule_sets(ROOT)["market-environment"]


def copy_registry(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "trading-rules", tmp_path / "trading-rules")
    return tmp_path


def test_registry_and_document_coverage_are_complete() -> None:
    assert validate_registry(ROOT) == {"ruleSets": 1, "rules": 46}
    assert validate_coverage(ROOT) == {"documentedRules": 327, "executableRules": 46}


def test_document_scanner_allows_same_file_references_but_rejects_cross_file_duplicates(tmp_path: Path) -> None:
    docs = tmp_path / "搭建交易系统-量化版"
    docs.mkdir()
    (docs / "first.md").write_text("QTS-01-01-01\n再次引用 QTS-01-01-01\n", encoding="utf-8")
    assert scan_documented_rules(tmp_path) == {"QTS-01-01-01": "搭建交易系统-量化版/first.md"}
    (docs / "second.md").write_text("QTS-01-01-01\n", encoding="utf-8")
    with pytest.raises(RuleValidationError, match="appears in both"):
        scan_documented_rules(tmp_path)


def test_fixed_snapshot_matches_golden_and_is_deterministic() -> None:
    snapshot = complete_snapshot()
    first = evaluate_rule_set(market_rule_set(), snapshot)
    second = evaluate_rule_set(market_rule_set(), copy.deepcopy(snapshot))
    golden = (FIXTURE_DIR / "market-environment-golden.json").read_bytes()

    assert canonical_json_bytes(first) == canonical_json_bytes(second) == golden
    assert len(first["traces"]) == 46
    assert len({trace["ruleId"] for trace in first["traces"]}) == 46
    assert first["score"] == 100
    assert first["state"] == "trend"
    assert first["confidence"] == "high"


def test_missing_inputs_never_become_zero_or_high_confidence() -> None:
    snapshot = complete_snapshot()
    snapshot["metrics"] = {"index.bullish_ratio": 1.0}
    result = evaluate_rule_set(market_rule_set(), snapshot)

    assert result["confidence"] == "insufficient"
    assert result["state"] == "insufficient"
    assert result["coverage"] < 0.5
    assert "index.ma20_slope_percentile" in result["missingInputs"]


def test_hard_veto_overrides_high_score() -> None:
    snapshot = complete_snapshot()
    snapshot["metrics"]["risk.systemic"] = True
    result = evaluate_rule_set(market_rule_set(), snapshot)

    assert result["score"] == 100
    assert result["state"] == "retreat"
    assert any("系统性风险" in item for item in result["vetoes"])


@pytest.mark.parametrize("mutation", ["unknown-evaluator", "duplicate-id", "validated-without-evidence", "unknown-field"])
def test_registry_rejects_invalid_rules(tmp_path: Path, mutation: str) -> None:
    root = copy_registry(tmp_path)
    path = root / "trading-rules" / "rule-sets" / "market-environment.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if mutation == "unknown-evaluator":
        payload["rules"][0]["evaluator"] = "arbitrary.eval"
    elif mutation == "duplicate-id":
        payload["rules"].append(copy.deepcopy(payload["rules"][0]))
    elif mutation == "validated-without-evidence":
        payload["rules"][0]["status"] = "validated"
        payload["rules"][0]["thresholds"]["provenance"] = "validated"
    else:
        payload["rules"][0]["unexpected"] = True
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(RuleValidationError):
        load_rule_sets(root)


def test_structured_event_requires_source_expiry_and_invalidation() -> None:
    event = complete_snapshot()["events"][0]
    validate_event(event, ROOT)
    event.pop("invalidation")
    with pytest.raises(ValidationError):
        validate_event(event, ROOT)


def test_canonical_hash_is_key_order_independent_and_rejects_nan() -> None:
    assert sha256_value({"b": 2, "a": 1}) == sha256_value({"a": 1, "b": 2})
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": float("nan")})


def test_serial_limiter_waits_at_least_one_second() -> None:
    current = [0.0]
    sleeps: list[float] = []

    def clock() -> float:
        return current[0]

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        current[0] += seconds

    limiter = SerialRateLimiter(clock=clock, sleeper=sleeper, random_uniform=lambda _low, _high: 0.1)
    limiter.acquire()
    limiter.acquire()

    assert sleeps == pytest.approx([1.1])


def test_fallback_chain_records_403_without_retrying_same_provider() -> None:
    calls: list[str] = []

    def blocked():
        calls.append("eastmoney")
        raise ProviderFailure("HTTP 403", status_code=403, retryable=False)

    def fallback():
        calls.append("tencent")
        return [1, 2, 3]

    value, quality = FallbackChain((("eastmoney", blocked), ("tencent", fallback))).fetch("breadth")

    assert value == [1, 2, 3]
    assert calls == ["eastmoney", "tencent"]
    assert quality.status == "fallback"
    assert "HTTP 403" in quality.warnings[0]


def test_after_market_provider_failure_emits_insufficient_snapshot() -> None:
    class FailingService:
        def get(self, as_of):
            raise RuntimeError(f"unavailable on {as_of}")

    snapshot = create_after_market_snapshot(date(2026, 8, 28), FailingService())

    assert snapshot["status"] == "insufficient"
    assert snapshot["providerQuality"][0]["status"] == "failed"
    assert snapshot["metrics"] == {}


def test_evidence_bundle_detects_tampering(tmp_path: Path) -> None:
    snapshot = complete_snapshot()
    rule_set = market_rule_set()
    result = evaluate_rule_set(rule_set, snapshot)
    create_evidence_bundle(
        tmp_path,
        snapshot,
        result,
        rule_set,
        root=ROOT,
        created_at="2026-08-28T16:31:00+08:00",
        git_sha="test-sha",
    )

    assert verify_evidence_bundle(tmp_path, ROOT)["files"] == 3
    (tmp_path / "snapshot.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuleValidationError, match="hash mismatch"):
        verify_evidence_bundle(tmp_path, ROOT)


def test_backtest_records_coverage_gap_costs_and_partitions(tmp_path: Path) -> None:
    for index, day in enumerate((26, 27, 28)):
        snapshot = complete_snapshot()
        snapshot["asOf"] = f"2026-08-{day}"
        snapshot["metrics"]["backtest.forward_return"] = 0.01 + index * 0.001
        (tmp_path / f"{day}.json").write_bytes(canonical_json_bytes(snapshot))

    result = run_backtest(sorted(tmp_path.glob("*.json")), market_rule_set(), transaction_cost_bps=10)

    assert result["availableTradingDays"] == 3
    assert result["coverageGap"] == 497
    assert result["validationEligible"] is False
    assert result["runs"][0]["netForwardReturn"] == pytest.approx(0.009)
    assert result["inSample"]["observations"] > 0
    assert result["outOfSample"]["observations"] > 0


def test_validation_promotion_requires_complete_500_day_evidence() -> None:
    with pytest.raises(RuleValidationError, match="missing"):
        validate_validation_evidence({"availableTradingDays": 750})

    evidence = {
        "availableTradingDays": 499,
        "transactionCostBps": 10,
        "inSample": {"observations": 300, "confidenceInterval95": [0.0, 0.1]},
        "outOfSample": {"observations": 199, "confidenceInterval95": [0.0, 0.1]},
        "ruleSetVersion": 1,
        "backtestHash": "hash",
        "rollbackCriteria": "out-of-sample lower bound below zero",
    }
    with pytest.raises(RuleValidationError, match="500"):
        validate_validation_evidence(evidence)


def test_cli_validates_and_replays_fixture(tmp_path: Path) -> None:
    assert run(["rules", "validate"]) == 0
    assert run(["rules", "coverage"]) == 0
    assert run(["docs", "sync-check"]) == 0
    assert run(
        [
            "evaluate",
            "--rule-set",
            "market-environment",
            "--snapshot",
            str(FIXTURE_DIR / "market-environment-complete.json"),
            "--output",
            str(tmp_path / "evidence"),
        ]
    ) == 0
    assert run(["evidence", "verify", str(tmp_path / "evidence")]) == 0


def test_workflows_separate_offline_pr_and_after_market_paths() -> None:
    pr_workflow = (ROOT / ".github" / "workflows" / "trading-rules-pr.yml").read_text(encoding="utf-8")
    scheduled_workflow = (ROOT / ".github" / "workflows" / "trading-rules-after-market.yml").read_text(encoding="utf-8")

    assert 'TRADING_RULES_OFFLINE: "1"' in pr_workflow
    assert "snapshot create" not in pr_workflow
    assert "schedule:" in scheduled_workflow
    assert "snapshot create" in scheduled_workflow
    assert "if: always()" in scheduled_workflow
