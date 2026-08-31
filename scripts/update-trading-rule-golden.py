"""Regenerate the committed deterministic market-environment golden result."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.trading_system.data.canonical import canonical_json_bytes, load_snapshot
from src.trading_system.evaluation.engine import evaluate_rule_set
from src.trading_system.rules.registry import load_rule_sets


def main() -> None:
    fixture_dir = ROOT / "tests" / "fixtures" / "trading-system"
    snapshot = load_snapshot(fixture_dir / "market-environment-complete.json", ROOT)
    rule_set = load_rule_sets(ROOT)["market-environment"]
    result = evaluate_rule_set(rule_set, snapshot)
    output = fixture_dir / "market-environment-golden.json"
    output.write_bytes(canonical_json_bytes(result))
    print(f"wrote {output.relative_to(ROOT)} with {len(result['traces'])} traces")


if __name__ == "__main__":
    main()
