from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from src.market_environment import api
from src.market_environment.schemas import (
    EvidenceQuality,
    LimitEvidence,
    PROMOTION_RULE_VERSION,
    PROMOTION_SAMPLE_RULE,
)
from src.market_environment.service import MarketEnvironmentService


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "market-environment"
    / "limit-evidence-contract.json"
)
CONTRACT = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = CONTRACT["cases"]
NEW_FIELDS = set(CONTRACT["newFields"])
LEGACY_FIELDS = {
    "limitUpCount",
    "limitDownCount",
    "failedLimitUpCount",
    "failedLimitUpRatio",
    "maxStreak",
    "state",
    "quality",
}


class LegacyLimitEvidence(BaseModel):
    limitUpCount: int | None
    limitDownCount: int | None
    failedLimitUpCount: int | None
    failedLimitUpRatio: float | None
    maxStreak: int | None
    state: str
    quality: EvidenceQuality


class ContractService:
    def __init__(self, limits: dict[str, Any]) -> None:
        self.limits = deepcopy(limits)
        for field in CONTRACT["outOfScope"]["absentFields"]:
            if field not in LimitEvidence.model_fields:
                self.limits[field] = "must-be-filtered"

    def get_chapter01(self, as_of: date, section: str) -> dict[str, Any]:
        assert section == "limits"
        builder = MarketEnvironmentService(provider=object(), persistent_cache=False)
        core = {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-09-04T15:35:00+08:00",
            "indices": [],
            "summary": {
                "synchronization": "no-data",
                "dominantTrend": "insufficient",
                "warnings": [],
            },
            "requestedAsOf": as_of,
            "effectiveDate": as_of,
        }
        provider_data = builder._missing_chapter_provider_data(
            as_of,
            "fixture only",
            status="missing",
        )
        provider_data["limits"] = self.limits
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": core["generatedAt"],
            "chapter01": builder._build_chapter01(core, provider_data),
        }


def test_contract_constants_and_fields_are_frozen() -> None:
    assert PROMOTION_SAMPLE_RULE == CONTRACT["sampleRule"]
    assert PROMOTION_RULE_VERSION == CONTRACT["contractVersion"]
    assert LEGACY_FIELDS | NEW_FIELDS <= set(LimitEvidence.model_fields)
    unsupported = set(CONTRACT["outOfScope"]["absentFields"]) - set(LimitEvidence.model_fields)
    assert not unsupported & set(LimitEvidence.model_fields)
    assert CONTRACT["outOfScope"]["continuousStrengthExtension"]["status"] == "insufficient"


@pytest.mark.parametrize("case_name", CASES)
def test_fixed_cases_round_trip_through_pydantic(case_name: str) -> None:
    payload = CASES[case_name]

    model = LimitEvidence.model_validate(payload)

    assert model.model_dump(mode="json", exclude_unset=True) == payload
    unsupported = set(CONTRACT["outOfScope"]["absentFields"]) - set(LimitEvidence.model_fields)
    assert not unsupported & set(payload)


def test_legacy_omission_and_explicit_null_remain_distinct() -> None:
    legacy = LimitEvidence.model_validate(CASES["legacyOmitted"])
    explicit_null = LimitEvidence.model_validate(CASES["explicitNull"])

    legacy_compatible = legacy.model_dump(mode="json", exclude_unset=True)
    explicit_null_dump = explicit_null.model_dump(mode="json", exclude_unset=True)
    normal_response_dump = legacy.model_dump(mode="json")

    assert not NEW_FIELDS & set(legacy_compatible)
    assert NEW_FIELDS <= set(explicit_null_dump)
    assert all(explicit_null_dump[field] is None for field in NEW_FIELDS)
    assert all(normal_response_dump[field] is None for field in NEW_FIELDS)


def test_valid_and_zero_denominator_promotion_semantics() -> None:
    valid = LimitEvidence.model_validate(CASES["promotion20Of8"])
    zero = LimitEvidence.model_validate(CASES["zeroDenominator"])

    assert valid.yesterdayLimitUpEligible == 20
    assert valid.todayPromoted == 8
    assert valid.promotionRatio == 0.4
    assert valid.promotionSampleRule == PROMOTION_SAMPLE_RULE
    assert valid.promotionRuleVersion == PROMOTION_RULE_VERSION
    assert valid.promotionQuality is not None
    assert valid.promotionQuality.status == "ok"

    assert zero.yesterdayLimitUpEligible == 0
    assert zero.todayPromoted == 0
    assert zero.promotionRatio is None
    assert zero.quality.status == "ok"
    assert zero.promotionQuality is not None
    assert zero.promotionQuality.status == "insufficient"
    assert zero.promotionQuality.reason == "zero-denominator"
    assert zero.fieldQuality is not None
    assert zero.fieldQuality["promotionRatio"].status == "insufficient"


def test_field_dataset_and_cache_quality_domains_remain_separate() -> None:
    dataset_statuses = {payload["quality"]["status"] for payload in CASES.values()}
    cache_states = {
        payload["quality"]["cacheState"]
        for payload in CASES.values()
        if "cacheState" in payload["quality"]
    }
    field_statuses = {
        quality["status"]
        for payload in CASES.values()
        for quality in [
            *([payload["promotionQuality"]] if payload.get("promotionQuality") else []),
            *((payload.get("fieldQuality") or {}).values()),
        ]
    }

    assert dataset_statuses == set(CONTRACT["qualityDomains"]["dataset"])
    assert cache_states == set(CONTRACT["qualityDomains"]["cache"])
    assert field_statuses == set(CONTRACT["qualityDomains"]["field"])

    assert CASES["datasetFallback"]["quality"]["status"] == "fallback"
    assert CASES["datasetFallback"]["quality"]["cacheState"] == "fresh"
    assert CASES["datasetFallback"]["promotionQuality"]["status"] == "degraded"
    assert CASES["datasetDegraded"]["quality"]["cacheState"] == "stale"
    assert CASES["datasetPartial"]["promotionQuality"]["status"] == "insufficient"


def test_old_client_ignores_additive_fields_and_preserves_legacy_facts() -> None:
    payload = CASES["promotion20Of8"]

    parsed = LegacyLimitEvidence.model_validate(payload).model_dump(mode="json")

    assert set(parsed) == LEGACY_FIELDS
    for field in LEGACY_FIELDS - {"quality"}:
        assert parsed[field] == payload[field]


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    [
        (("quality", "status"), "stale"),
        (("quality", "cacheState"), "fallback"),
        (("promotionQuality", "status"), "partial"),
        (("promotionQuality", "asOf"), "not-a-date"),
        (("promotionQuality", "source"), None),
        (("promotionSampleAsOf",), "2099-99-99"),
        (("promotionRuleVersion",), "limits-promotion-v2"),
        (("fieldQuality", "ladder"), CASES["promotion20Of8"]["promotionQuality"]),
        (("fieldQuality", "promotionRatio", "observations"), 19),
        (("fieldQuality", "promotionRatio", "source"), None),
    ],
)
def test_contract_rejects_crossed_quality_or_scope_values(
    path: tuple[str, ...],
    invalid_value: Any,
) -> None:
    payload = deepcopy(CASES["promotion20Of8"])
    target: dict[str, Any] = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = invalid_value

    with pytest.raises(ValidationError):
        LimitEvidence.model_validate(payload)


@pytest.mark.parametrize(
    "updates",
    [
        {"todayPromoted": 21},
        {"promotionRatio": 0.99},
        {"yesterdayLimitUpEligible": 0},
        {"promotionPreviousAsOf": "2026-09-05"},
        {"promotionQuality": {"status": "insufficient"}},
        {"fieldQuality": None},
    ],
)
def test_contract_rejects_inconsistent_promotion_evidence(
    updates: dict[str, Any],
) -> None:
    payload = deepcopy(CASES["promotion20Of8"])
    for field, value in updates.items():
        if field == "promotionQuality" and isinstance(value, dict):
            payload[field].update(value)
        else:
            payload[field] = value

    with pytest.raises(ValidationError):
        LimitEvidence.model_validate(payload)


@pytest.mark.parametrize("case_name", CASES)
def test_fixed_cases_pass_production_fastapi_response_model(
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
) -> None:
    source = CASES[case_name]
    monkeypatch.setattr(api, "service", ContractService(source))

    response = TestClient(api.app).get(
        "/api/market-environment/chapter-01?as_of=2026-09-04&section=limits"
    )

    assert response.status_code == 200
    serialized = response.json()["chapter01"]["limits"]
    for field in LEGACY_FIELDS - {"quality"}:
        assert serialized[field] == source[field]
    for field, value in source["quality"].items():
        assert serialized["quality"][field] == value
    for field in NEW_FIELDS:
        assert serialized[field] == source.get(field)
    unsupported = set(CONTRACT["outOfScope"]["absentFields"]) - set(LimitEvidence.model_fields)
    assert not unsupported & set(serialized)
