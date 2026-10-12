from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.trading_system.data.canonical import (
    canonical_json_bytes,
    load_snapshot,
    sha256_value,
)
from src.trading_system.evaluation.engine import evaluate_rule_set
from src.trading_system.evidence.bundle import (
    create_evidence_bundle,
    verify_evidence_bundle,
)
from src.trading_system.rules.registry import load_rule_sets


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "trading-system"
GOLDEN = json.loads(
    (FIXTURE_DIR / "market-environment-v2-golden.json").read_text(encoding="utf-8")
)


def _sector_trace_summary(result: dict) -> list[dict]:
    keys = ("ruleId", "status", "value", "score", "missingInputs")
    return [
        {key: trace[key] for key in keys}
        for trace in result["traces"]
        if trace["ruleId"].startswith("QTS-01-05-")
    ]


def _bundle_bytes(path: Path) -> dict[str, bytes]:
    return {item.name: item.read_bytes() for item in sorted(path.iterdir())}


@pytest.mark.parametrize("case", sorted(GOLDEN))
def test_v2_golden_replay_and_evidence_bundle_are_byte_deterministic(
    case: str,
    tmp_path: Path,
) -> None:
    expected = GOLDEN[case]
    snapshot = load_snapshot(FIXTURE_DIR / expected["snapshotFile"], ROOT)
    rule_set = load_rule_sets(ROOT)["market-environment"]

    first = evaluate_rule_set(rule_set, snapshot)
    second = evaluate_rule_set(rule_set, copy.deepcopy(snapshot))
    first_bytes = canonical_json_bytes(first)
    second_bytes = canonical_json_bytes(second)

    assert first_bytes == second_bytes
    assert first["snapshotHash"] == second["snapshotHash"] == sha256_value(snapshot)
    assert first["snapshotHash"] == expected["snapshotHash"]
    assert first["resultHash"] == second["resultHash"] == expected["resultHash"]
    assert hashlib.sha256(first_bytes).hexdigest() == expected["resultBytesSha256"]
    assert canonical_json_bytes(first["traces"]) == canonical_json_bytes(second["traces"])
    assert (
        hashlib.sha256(canonical_json_bytes(first["traces"])).hexdigest()
        == expected["tracesSha256"]
    )
    assert _sector_trace_summary(first) == expected["sectorTraces"]

    bundle_runs: list[dict[str, bytes]] = []
    for replay, result in (("first", first), ("second", second)):
        bundle_dir = tmp_path / replay
        create_evidence_bundle(
            bundle_dir,
            snapshot,
            result,
            rule_set,
            root=ROOT,
            created_at="2026-08-28T16:31:00+08:00",
            git_sha="fixture-golden-sha",
        )
        verification = verify_evidence_bundle(bundle_dir, ROOT)
        assert verification["evidenceId"] == expected["evidenceId"]
        bundle_runs.append(_bundle_bytes(bundle_dir))

    assert bundle_runs[0] == bundle_runs[1]
    assert {
        name: hashlib.sha256(content).hexdigest()
        for name, content in bundle_runs[0].items()
    } == expected["bundleFiles"]
