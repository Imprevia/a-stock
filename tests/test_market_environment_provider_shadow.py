from copy import deepcopy
from datetime import date, datetime, timezone
import json

from src.market_environment.provider_shadow import compare_shadow
from src.market_environment.snapshot_store import SnapshotRecord, payload_checksum


AS_OF = date(2026, 9, 18)


def quality(status="ok", source="eastmoney-fixture", observations=3):
    return {
        "status": status,
        "source": source,
        "providerRevision": f"{source}-v1",
        "observations": observations,
        "asOf": AS_OF.isoformat(),
        "warnings": [],
    }


def test_core_compares_index_identity_and_numeric_tolerance_without_mutating_inputs():
    formal = {
        "asOf": AS_OF.isoformat(),
        "indices": [
            {
                "code": "sh000001",
                "changePct": 1.2,
                "history": [{"date": AS_OF.isoformat(), "open": 3_900, "close": 3_950, "high": 3_970, "low": 3_880, "amount": 100_000}],
            },
            {
                "code": "sz399001",
                "changePct": -0.2,
                "history": [{"date": AS_OF.isoformat(), "open": 12_000, "close": 12_010, "high": 12_100, "low": 11_950, "amount": 200_000}],
            },
        ],
        "quality": quality(observations=2),
    }
    shadow = deepcopy(formal)
    shadow["quality"]["source"] = "fuyao"
    shadow["quality"]["providerRevision"] = "fuyao-v3"
    shadow["indices"][0]["history"][0]["close"] += 0.005
    before_formal, before_shadow = deepcopy(formal), deepcopy(shadow)

    result = compare_shadow("core", formal, shadow, formal_revision="eastmoney-v1", shadow_revision="fuyao-v3", as_of=AS_OF)

    assert result["status"] == "match"
    assert result["match"] is True
    assert result["comparedCount"] == 2
    assert result["formalProviderRevision"] == "eastmoney-v1"
    assert result["shadowProviderRevision"] == "fuyao-v3"
    assert formal == before_formal
    assert shadow == before_shadow
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_breadth_reports_count_and_median_mismatch():
    formal = {
        "advanceCount": 8,
        "declineCount": 2,
        "flatCount": 1,
        "validCount": 11,
        "advanceRatio": 8 / 11,
        "medianReturn": 1.2,
        "quality": quality(observations=11),
    }
    shadow = {**formal, "declineCount": 3, "validCount": 12, "advanceRatio": 8 / 12, "quality": quality(source="fuyao", observations=12)}

    result = compare_shadow("breadth", formal, shadow)

    assert result["status"] == "mismatch"
    assert result["match"] is False
    assert result["formalCount"] == 11
    assert result["shadowCount"] == 12
    assert {item["field"] for item in result["differences"]} >= {"declineCount", "validCount"}


def test_active_direction_detects_missing_identity_and_ordering_change():
    def row(code, amount):
        return {"code": code, "name": f"股票{code}", "amount": amount, "changePct": 1.0, "closePosition": 0.5}

    formal = {"topStocks": [row("000001", 300), row("000002", 200), row("000003", 100)], "quality": quality(observations=3)}
    shadow = {"topStocks": [row("000002", 200), row("000001", 300), row("600000", 90)], "quality": quality(source="fuyao", observations=3)}

    result = compare_shadow("activeDirection", formal, shadow)

    assert result["status"] == "mismatch"
    assert result["identityMissing"] == {"formal": ["600000"], "shadow": ["000003"]}
    assert result["orderingDifferences"]
    assert result["comparedCount"] == 2


def test_sectors_match_uses_canonical_security_identity_and_ignores_rank_field():
    formal = {
        "rows": [{"rank": 1, "code": "BK001", "name": "电子", "changePct": 2.0, "amount": 1000, "mainNet": 12, "mainNetPct": 1.2, "upCount": 20, "downCount": 5, "leader": "样本股"}],
        "quality": quality(observations=1),
    }
    shadow = {
        "rows": [{"rank": 9, "code": "BK001", "name": "电子", "changePct": 2.004, "amount": 1000.4, "mainNet": 12.2, "mainNetPct": 1.204, "upCount": 20, "downCount": 5, "leader": "样本股"}],
        "quality": quality(source="fuyao", observations=1),
    }

    result = compare_shadow("sectors", formal, shadow)

    assert result["status"] == "match"
    assert result["comparedCount"] == 1
    assert result["orderingDifferences"] == []


def test_quality_failure_is_insufficient_and_does_not_expose_payload():
    formal = {"advanceCount": 2, "declineCount": 1, "flatCount": 0, "validCount": 3, "quality": quality()}
    shadow = {"advanceCount": None, "declineCount": None, "flatCount": None, "validCount": None, "secret": "should-not-be-copied", "quality": quality(status="failed", source="fuyao")}

    result = compare_shadow("breadth", formal, shadow)

    assert result["status"] == "insufficient"
    assert result["match"] is None
    assert "secret" not in json.dumps(result)
    assert "should-not-be-copied" not in json.dumps(result)


def test_different_provider_dates_are_mismatch_even_when_metrics_match():
    formal = {"advanceCount": 2, "declineCount": 1, "flatCount": 0, "validCount": 3, "quality": quality()}
    shadow_quality = quality(source="fuyao")
    shadow_quality["asOf"] = "2026-09-17"
    shadow = {"advanceCount": 2, "declineCount": 1, "flatCount": 0, "validCount": 3, "quality": shadow_quality}

    result = compare_shadow("breadth", formal, shadow)

    assert result["status"] == "mismatch"
    assert any(item["field"] == "asOf" for item in result["differences"])


def test_partial_quality_is_degraded_not_match():
    formal = {"advanceCount": 2, "declineCount": 1, "flatCount": 0, "validCount": 3, "quality": quality()}
    shadow = {**formal, "quality": quality(status="partial", source="fuyao")}

    result = compare_shadow("breadth", formal, shadow)

    assert result["status"] == "degraded"
    assert result["match"] is False


def test_shadow_mismatch_does_not_change_formal_snapshot_source_or_checksum():
    formal_payload = {
        "advanceCount": 2,
        "declineCount": 1,
        "flatCount": 0,
        "validCount": 3,
        "quality": quality(source="formal-provider"),
    }
    record = SnapshotRecord(
        dataset="breadth",
        as_of=AS_OF,
        payload=formal_payload,
        source="formal-provider",
        status="ok",
        observations=3,
        warnings=(),
        fetched_at=datetime.now(timezone.utc),
    ).normalized()
    original_payload = deepcopy(record.payload)
    original_source = record.source
    original_checksum = record.checksum
    shadow_payload = {**formal_payload, "advanceCount": 1, "quality": quality(source="fuyao")}

    report = compare_shadow("breadth", record.payload, shadow_payload)

    assert report["status"] == "mismatch"
    assert record.payload == original_payload
    assert record.source == original_source
    assert record.checksum == original_checksum == payload_checksum(original_payload)


def test_core_adapter_mapping_shape_is_supported():
    class Result:
        def __init__(self):
            self.payload = {
                "code": "sh000001",
                "identity": "000001.SH",
                "bars": [{"date": AS_OF.isoformat(), "open": 3900, "close": 3950, "high": 3970, "low": 3880, "amount": 100000}],
            }
            self.quality = quality(source="fuyao")

        def as_dict(self):
            return {**self.payload, "quality": self.quality}

    formal = {"indices": [{"code": "sh000001", "history": [{"date": AS_OF.isoformat(), "open": 3900, "close": 3950, "high": 3970, "low": 3880, "amount": 100000}]}], "quality": quality(observations=1)}
    shadow = {"sh000001": Result()}
    result = compare_shadow("core", formal, shadow)
    assert result["status"] == "match"
    assert result["comparedCount"] == 1
