from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "tests" / "fixtures" / "market-environment" / "limit-ecosystem-matrix.json"
RULES_PATH = ROOT / "trading-rules" / "rule-sets" / "market-environment.yaml"
DOC_PATH = ROOT / "搭建交易系统-量化版" / "01-如何判断市场环境" / "03.涨停、跌停、炸板和连板晋级.md"


def test_limit_ecosystem_matrix_matches_rule_registry_and_document() -> None:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    registry = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    rules = {rule["ruleId"]: rule for rule in registry["rules"]}
    expected_ids = [item["ruleId"] for item in matrix["rules"]]

    assert expected_ids == [f"QTS-01-03-0{i}" for i in range(1, 6)]
    assert len(expected_ids) == len(set(expected_ids))
    assert sum(item["weight"] for item in matrix["rules"]) == 1
    assert matrix["defaultWindow"] == 250
    assert matrix["minimumValidObservations"] == 60

    for item in matrix["rules"]:
        rule = rules[item["ruleId"]]
        assert rule["title"] == item["title"]
        assert rule["scoring"]["weight"] == item["weight"]
        assert rule["scoring"]["direction"] == item["direction"]
        assert rule["windows"] == [matrix["defaultWindow"]]
        assert rule["status"] == "defined"
        assert rule["parameters"]["formulaSource"] == matrix["document"]

    frontmatter = DOC_PATH.read_text(encoding="utf-8").split("---", 2)[1]
    metadata = yaml.safe_load(frontmatter)
    assert metadata["quantVersion"] == matrix["quantVersion"]
    assert metadata["ruleStatus"] == matrix["ruleStatus"]
    assert re.search(r"250\s*个交易日", DOC_PATH.read_text(encoding="utf-8"))
    assert re.search(r"60\s*个有效观测", DOC_PATH.read_text(encoding="utf-8"))


def test_limit_ecosystem_fixture_covers_missing_data_paths() -> None:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    assert {"complete-adjacent-sessions", "zero-denominator", "date-mismatch"}.issubset(
        matrix["fixtureCases"]
    )
    assert "insufficient" in matrix["qualityStates"]
    assert "failed" in matrix["qualityStates"]
