from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.market_environment.providers import MarketDataProvider
from src.market_environment.sector_enrichment import (
    ENRICHMENT_MAPPING_REVISION,
    SectorIdentityMatcher,
    normalize_sector_name,
)


AS_OF = date(2026, 9, 30)
AFTER_SETTLEMENT = datetime(2026, 9, 30, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
FIXTURE_PATH = Path(__file__).parent / "fixtures/market-environment/eastmoney-sector-dataapi.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def base_payload(*, second: bool = True) -> dict:
    rows = [
        {
            "rank": 1,
            "code": "885001.TI",
            "name": "电子",
            "changePct": 2.35,
            "amount": 1_000_000_000,
            "mainNet": 999,
            "mainNetPct": None,
            "upCount": None,
            "downCount": None,
            "leader": None,
        }
    ]
    if second:
        rows.append(
            {
                "rank": 2,
                "code": "885002.TI",
                "name": "医药",
                "changePct": 1.2,
                "amount": 800_000_000,
                "mainNet": None,
                "mainNetPct": None,
                "upCount": None,
                "downCount": None,
                "leader": None,
            }
        )
    return {
        "rows": rows,
        "state": "当日排名已观测",
        "quality": {
            "dataset": "industry-ranking",
            "source": "fuyao",
            "provider": "fuyao",
            "status": "fallback",
            "observations": len(rows),
            "asOf": AS_OF.isoformat(),
            "warning": "sector provider fields unavailable",
            "warnings": ["sector provider fields unavailable"],
        },
    }


def provider(*, enabled: bool = True, now: datetime = AFTER_SETTLEMENT, mapping=None) -> MarketDataProvider:
    return MarketDataProvider(
        sector_enrichment_enabled=enabled,
        sector_enrichment_now=lambda: now,
        sector_identity_mapping=mapping,
    )


def test_offline_fixture_is_redacted_and_defines_all_contract_cases():
    text = FIXTURE_PATH.read_text(encoding="utf-8").lower()

    assert FIXTURE["partial128"]["rowCount"] == 128
    assert {
        "complete",
        "partial128",
        "malformedValues",
        "ambiguousPercentageScale",
        "duplicateNames",
        "missingLeader",
    } <= set(FIXTURE)
    assert "token" not in text
    assert "cookie" not in text
    assert "set-cookie" not in text
    assert "authorization" not in text


def test_identity_matcher_is_exact_versioned_and_collision_safe():
    matcher = SectorIdentityMatcher()
    base = [
        {"code": "885001.TI", "name": "电子（行业）", "changePct": 2.35, "amount": 1000},
        {"code": "885002.TI", "name": "未匹配", "changePct": 1.0, "amount": 1000},
    ]
    source = [
        {"f12": "BK001", "f14": "电子(行业)", "f3": 235, "f6": 1000},
        {"f12": "BK002", "f14": "其他", "f3": 100, "f6": 1000},
    ]

    result = matcher.match(base, source)

    assert normalize_sector_name("电子（行业）") == normalize_sector_name("电子(行业)")
    assert result.mapping_revision == ENRICHMENT_MAPPING_REVISION
    assert result.matched_rows == 1
    assert result.matches[0].method == "normalized-name"
    assert result.unmatched_base == (1,)


def test_identity_matcher_rejects_duplicate_names_and_taxonomy_conflicts():
    duplicate = SectorIdentityMatcher().match(
        [{"code": "885001.TI", "name": "电子", "changePct": 2.35, "amount": 1000}],
        [
            {"f12": "BK001", "f14": "电子", "f3": 235, "f6": 1000},
            {"f12": "BK999", "f14": "电子", "f3": 235, "f6": 1000},
        ],
    )
    taxonomy = SectorIdentityMatcher({"885001.TI": "BK001"}).match(
        [{"code": "885001.TI", "name": "电子", "changePct": 2.35, "amount": 1000}],
        [{"f12": "BK001", "f14": "煤炭", "f3": 235, "f6": 1000}],
    )

    assert duplicate.matches == ()
    assert any("candidates" in conflict for conflict in duplicate.conflicts)
    assert taxonomy.matches == ()
    assert any("taxonomy" in conflict for conflict in taxonomy.conflicts)


def test_disabled_historical_and_pre_settlement_paths_make_zero_requests(monkeypatch):
    calls = []

    disabled = provider(enabled=False)
    monkeypatch.setattr(disabled.http, "get_json", lambda *_args, **_kwargs: calls.append("disabled"))
    disabled_result = disabled.enrich_fuyao_sectors(base_payload(), AS_OF, eligible=True)

    historical = provider(now=AFTER_SETTLEMENT)
    monkeypatch.setattr(historical.http, "get_json", lambda *_args, **_kwargs: calls.append("historical"))
    historical_result = historical.enrich_fuyao_sectors(base_payload(), date(2026, 9, 29), eligible=True)

    pre_settlement = provider(now=datetime(2026, 9, 30, 14, 59, tzinfo=ZoneInfo("Asia/Shanghai")))
    monkeypatch.setattr(pre_settlement.http, "get_json", lambda *_args, **_kwargs: calls.append("pre"))
    pre_result = pre_settlement.enrich_fuyao_sectors(base_payload(), AS_OF, eligible=True)

    ineligible = provider()
    monkeypatch.setattr(ineligible.http, "get_json", lambda *_args, **_kwargs: calls.append("ineligible"))
    ineligible_result = ineligible.enrich_fuyao_sectors(base_payload(), AS_OF, eligible=False)

    assert calls == []
    assert disabled_result["quality"]["sectorEnrichment"]["status"] == "disabled"
    assert historical_result["quality"]["sectorEnrichment"]["dateEvidence"]["reason"] == "not-current-shanghai-date"
    assert pre_result["quality"]["sectorEnrichment"]["dateEvidence"]["reason"] == "before-settlement"
    assert ineligible_result["quality"]["sectorEnrichment"]["dateEvidence"]["reason"] == "caller-not-eligible"


def test_fixed_dataapi_request_uses_shared_host_policy_and_date_cache_key(monkeypatch):
    client = provider()
    captured = {}

    def fake_get_json(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FIXTURE["complete"]

    monkeypatch.setattr(client.http, "get_json", fake_get_json)
    rows = client._fetch_sector_dataapi_rows(AS_OF)
    policy = client.http._policy("data.eastmoney.com")

    assert len(rows) == 2
    assert captured["url"] == client._SECTOR_DATAAPI_URL
    assert captured["params"]["key"] == "f3,f6,f62,f104,f105,f128,f184"
    assert captured["params"]["code"] == "m:90+s:4"
    assert captured["requested_date"] == AS_OF.isoformat()
    assert captured["cache_ttl"] == 10.0
    assert policy.max_retries == 2
    assert policy.failure_threshold == 3
    assert policy.cooldown_seconds == 30.0


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"data": None}, {"data": {}}, {"data": {"diff": []}}, {"data": {"rows": []}}],
)
def test_dataapi_rejects_malformed_envelopes_and_unsupported_shapes(monkeypatch, payload):
    client = provider()
    monkeypatch.setattr(client.http, "get_json", lambda *_args, **_kwargs: payload)

    with pytest.raises(ValueError):
        client._fetch_sector_dataapi_rows(AS_OF)


def test_fill_only_merge_normalizes_integerized_percentages_and_preserves_fuyao(monkeypatch):
    client = provider()
    monkeypatch.setattr(client.http, "get_json", lambda *_args, **_kwargs: FIXTURE["complete"])
    before = base_payload()

    result = client.enrich_fuyao_sectors(before, AS_OF, eligible=True)

    first, second = result["rows"]
    assert (first["code"], first["name"], first["changePct"], first["amount"]) == (
        "885001.TI",
        "电子",
        2.35,
        1_000_000_000,
    )
    assert first["mainNet"] == 999
    assert first["mainNetPct"] == 3.15
    assert first["leader"] == "领涨样本"
    assert second["mainNet"] == -25_000_000
    assert second["mainNetPct"] == -0.85
    enrichment = result["quality"]["sectorEnrichment"]
    assert enrichment["status"] == "enriched"
    assert enrichment["percentageScale"] == 0.01
    assert enrichment["identityCoverage"] == 1.0
    assert enrichment["fieldCoverage"]["mainNet"] == 1.0
    assert enrichment["fieldFilled"]["mainNet"] == 1
    assert result["quality"]["source"] == "fuyao"
    assert result["quality"]["status"] == "fallback"
    assert before["rows"][0]["mainNetPct"] is None


def test_partial_128_row_coverage_preserves_unmatched_fuyao_fields(monkeypatch):
    partial = FIXTURE["partial128"]
    rows = list(partial["matchedRows"])
    template = partial["unmatchedTemplate"]
    for index in range(1, partial["rowCount"]):
        rows.append(
            {
                key: value.format(index=index) if isinstance(value, str) else value
                for key, value in template.items()
            }
        )
    client = provider()
    monkeypatch.setattr(client.http, "get_json", lambda *_args, **_kwargs: {"data": {"diff": rows}})

    result = client.enrich_fuyao_sectors(base_payload(), AS_OF, eligible=True)

    enrichment = result["quality"]["sectorEnrichment"]
    assert enrichment["sourceRows"] == 128
    assert enrichment["matchedRows"] == 1
    assert enrichment["unmatchedRows"] == 1
    assert enrichment["identityCoverage"] == 0.5
    assert enrichment["status"] == "partial"
    assert result["rows"][1]["mainNet"] is None
    assert result["quality"]["status"] == "fallback"


@pytest.mark.parametrize("fixture_name", ["malformedValues", "ambiguousPercentageScale"])
def test_invalid_numeric_or_ambiguous_scale_preserves_base_payload(monkeypatch, fixture_name):
    client = provider()
    monkeypatch.setattr(client.http, "get_json", lambda *_args, **_kwargs: FIXTURE[fixture_name])
    base = base_payload(second=False)

    result = client.enrich_fuyao_sectors(base, AS_OF, eligible=True)

    assert result["rows"] == base["rows"]
    assert result["quality"]["status"] == "fallback"
    assert result["quality"]["sectorEnrichment"]["status"] == "failed"
    assert "dataapi" in result["quality"]["warning"]


def test_duplicate_name_and_missing_leader_remain_unfilled(monkeypatch):
    duplicate = provider()
    monkeypatch.setattr(duplicate.http, "get_json", lambda *_args, **_kwargs: FIXTURE["duplicateNames"])
    duplicate_result = duplicate.enrich_fuyao_sectors(base_payload(second=False), AS_OF, eligible=True)

    missing_leader = provider()
    monkeypatch.setattr(missing_leader.http, "get_json", lambda *_args, **_kwargs: FIXTURE["missingLeader"])
    leader_result = missing_leader.enrich_fuyao_sectors(base_payload(second=False), AS_OF, eligible=True)

    assert duplicate_result["rows"][0]["mainNet"] == 999
    assert duplicate_result["rows"][0]["mainNetPct"] is None
    assert duplicate_result["quality"]["sectorEnrichment"]["matchedRows"] == 0
    assert duplicate_result["quality"]["sectorEnrichment"]["status"] == "partial"
    assert leader_result["rows"][0]["leader"] is None
    assert leader_result["rows"][0]["mainNetPct"] == 0.1


def test_supplemental_failure_retains_base_and_records_source_date_warning(monkeypatch):
    client = provider()
    monkeypatch.setattr(
        client.http,
        "get_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fixture unavailable")),
    )
    base = base_payload()

    result = client.enrich_fuyao_sectors(base, AS_OF, eligible=True)

    assert result["rows"] == base["rows"]
    assert result["quality"]["source"] == "fuyao"
    assert result["quality"]["status"] == "fallback"
    assert result["quality"]["sectorEnrichment"]["status"] == "failed"
    assert "2026-09-30" in result["quality"]["warning"]
    assert "东方财富 dataapi" in result["quality"]["warning"]
