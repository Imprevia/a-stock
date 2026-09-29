from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from src.market_environment.fuyao_market import (
    FuyaoMarketAdapter,
    FuyaoMarketClient,
    FuyaoMarketConfigurationError,
    FuyaoMarketContractError,
    FuyaoMarketPermissionError,
    FuyaoMarketRateLimitError,
    FuyaoMarketTransportError,
)
from src.market_environment.fuyao_request_gate import FuyaoRequestGate


AS_OF = date(2026, 9, 18)
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/market-environment/fuyao-market-data.json").read_text(encoding="utf-8")
)


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def client(session, **kwargs):
    return FuyaoMarketClient("fixture-key", session=session, sleep=lambda _: None, **kwargs)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (Response({"code": 2001, "data": None}), FuyaoMarketPermissionError),
        (Response({"code": 4001, "data": {}}), FuyaoMarketTransportError),
        (Response({"code": 0, "data": None}), FuyaoMarketContractError),
        (Response(ValueError("bad json")), FuyaoMarketContractError),
    ],
)
def test_generic_envelope_classifies_errors_without_secret_echo(response, error):
    with pytest.raises(error):
        client(Session([response]), max_retries=0).request("/fixture")
    assert "fixture-key" not in str(response.payload)


def test_generic_layer_retries_429_and_stops_at_budget():
    session = Session([Response({}, 429), Response({}, 429), Response({}, 429)])
    with pytest.raises(FuyaoMarketRateLimitError):
        client(session, max_retries=2, request_budget=3).request("/fixture")
    assert len(session.calls) == 3


def test_missing_key_fails_closed_without_request():
    session = Session([])
    with pytest.raises(FuyaoMarketConfigurationError):
        FuyaoMarketClient(session=session).request("/fixture")
    assert session.calls == []


def test_market_clients_share_an_injected_request_gate():
    now = [0.0]
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    gate = FuyaoRequestGate(min_interval_seconds=0.5, sleep=sleep, monotonic=lambda: now[0])
    first = client(Session([Response({"code": 0, "data": {}})]), request_gate=gate)
    second = client(Session([Response({"code": 0, "data": {}})]), request_gate=gate)
    first.request("/fixture")
    second.request("/fixture")
    assert sleeps == pytest.approx([0.5])


def test_market_error_keeps_redacted_business_evidence():
    response = Response({"code": 5003, "message": "rate limited", "request_id": "req-123", "data": {}})
    with pytest.raises(FuyaoMarketTransportError, match=r"code=5003.*message=rate limited.*request_id=req-123"):
        client(Session([response]), max_retries=0).request("/fixture")


def test_core_normalization_keeps_bars_and_missing_date_insufficient():
    adapter = FuyaoMarketAdapter()
    result = adapter.normalize_core(FIXTURE["core"], AS_OF, min_bars=2)["sh000001"]
    assert result.status == "insufficient"  # fixture's last date intentionally differs from AS_OF
    assert result.payload["bars"][-1].amount == 120000000000
    assert result.quality["asOf"] == AS_OF.isoformat()


def test_core_accepts_exact_date_and_rejects_identity_mismatch():
    adapter = FuyaoMarketAdapter()
    rows = [dict(row, date="2026-09-18") for row in FIXTURE["core"]["sh000001"]]
    rows[-1]["thscode"] = "399001.SZ"
    result = adapter.normalize_core({"sh000001": rows}, AS_OF, min_bars=2)["sh000001"]
    assert result.status == "insufficient"
    assert any("identity mismatch" in item for item in result.warnings)


def test_breadth_requires_complete_stable_pagination_and_real_identities():
    adapter = FuyaoMarketAdapter()
    result = adapter.normalize_breadth(FIXTURE["breadth_pages"], AS_OF)
    assert result.status == "ok"
    assert result.payload["validCount"] == 4
    assert result.payload["advanceCount"] == 2

    changed = json.loads(json.dumps(FIXTURE["breadth_pages"]))
    changed[1]["pagination"]["total"] = 5
    rejected = adapter.normalize_breadth(changed, AS_OF)
    assert rejected.status == "insufficient"
    assert any("pagination total changed" in item for item in rejected.warnings)


def test_active_direction_requires_ordering_evidence_and_thirty_rows():
    adapter = FuyaoMarketAdapter()
    base = FIXTURE["active_direction_row"]
    rows = [dict(base, thscode=f"{600001 + i:06d}.SH", ticker=f"{600001 + i:06d}", amount=30000 - i, name=f"样本{i}") for i in range(30)]
    result = adapter.normalize_active_direction(rows, AS_OF, ordering_proven=True)
    assert result.status == "ok"
    assert len(result.payload["topStocks"]) == 30
    rejected = adapter.normalize_active_direction(rows, AS_OF)
    assert rejected.status == "ineligible"
    assert any("ordering" in item for item in rejected.warnings)


def test_sectors_reject_code_as_leader_and_missing_fields():
    adapter = FuyaoMarketAdapter()
    result = adapter.normalize_sectors(FIXTURE["sectors"], AS_OF)
    assert result.status == "ok"
    bad = [dict(FIXTURE["sectors"][0], leader="600001.SH", main_net=None)]
    rejected = adapter.normalize_sectors(bad, AS_OF)
    assert rejected.status in {"ineligible", "insufficient"}
    assert rejected.payload["rows"][0]["leader"] is None
    assert rejected.payload["rows"][0]["mainNet"] is None


def test_fixture_contains_no_credentials():
    serialized = json.dumps(FIXTURE, ensure_ascii=False).lower()
    assert "api-key" not in serialized
    assert "fixture-key" not in serialized
    assert "secret" not in serialized


def _ths_sources(count=320, *, snapshot_date=AS_OF, timestamp=None):
    shanghai = ZoneInfo("Asia/Shanghai")
    timestamp = timestamp or int(datetime.combine(snapshot_date, datetime.min.time(), tzinfo=shanghai).timestamp() * 1000)
    calendar = {
        "timestamp": timestamp,
        "item": [{"date": snapshot_date.strftime("%Y%m%d"), "date_ms": timestamp}],
    }
    catalog = {
        "timestamp": timestamp,
        "item": [{"thscode": f"{index:06d}.TI", "name": f"行业{index}"} for index in range(count)],
    }
    snapshots = {
        "timestamp": timestamp,
        "total": count,
        "item": [
            {
                "thscode": f"{index:06d}.TI",
                "price_change_ratio_pct": (index % 7) - 3,
                "turnover": 1000 + index,
            }
            for index in range(count)
        ],
    }
    return calendar, catalog, snapshots


def test_ths_sector_fetches_calendar_catalog_and_snapshot_with_stable_top_ten():
    calendar, catalog, snapshots = _ths_sources()
    session = Session(
        [
            Response({"code": 0, "data": calendar}),
            Response({"code": 0, "data": catalog}),
            Response({"code": 0, "data": snapshots}),
        ]
    )
    result = FuyaoMarketAdapter(client(session), source_revision="fuyao-sectors-r2").fetch_sectors(AS_OF, batch_size=320)
    assert result.status == "fallback"
    assert len(result.payload["rows"]) == 10
    assert result.quality["catalogCount"] == 320
    assert result.quality["snapshotCount"] == 320
    assert result.quality["snapshotCoverage"] == 1.0
    assert result.quality["fieldCoverage"]["changePct"] == 320
    assert result.quality["fieldCompleteness"]["requiredComplete"] is True
    assert result.quality["fieldCompleteness"]["unsupportedAreNull"] is True
    assert result.quality["permissionEvidence"] == {"configured": True}
    assert result.quality["rateLimitEvidence"]["requestsUsed"] == 3
    assert result.quality["providerRevision"] == "fuyao-sectors-r2"
    rows = result.payload["rows"]
    assert rows == sorted(rows, key=lambda row: (-row["changePct"], row["code"]))
    assert [row["code"] for row in rows[:3]] == ["000006.TI", "000013.TI", "000020.TI"]
    assert all(result.payload["rows"][0][field] is None for field in ("mainNet", "mainNetPct", "upCount", "downCount", "leader"))
    serialized = json.dumps(result.as_dict()).lower()
    assert "api_key" not in serialized
    assert "fixture-key" not in serialized
    assert [call[0].rsplit("/", 1)[-1] for call in session.calls] == [
        "trading-days",
        "ths-index-list",
        "snapshot",
    ]


def test_ths_sector_snapshot_coverage_and_date_mismatch_are_insufficient():
    calendar, catalog, snapshots = _ths_sources()
    snapshots["item"] = snapshots["item"][:-1]
    result = FuyaoMarketAdapter().normalize_sector_index_data(calendar, catalog, snapshots, AS_OF)
    assert result.status == "insufficient"
    assert any("coverage is incomplete" in warning for warning in result.warnings)

    _, _, mismatched = _ths_sources(snapshot_date=date(2026, 9, 19))
    mismatched_result = FuyaoMarketAdapter().normalize_sector_index_data(calendar, catalog, mismatched, AS_OF)
    assert mismatched_result.status == "insufficient"
    assert any("timestamp date mismatch" in warning for warning in mismatched_result.warnings)


def test_ths_sector_batches_accept_response_time_jitter_within_same_shanghai_date():
    calendar, catalog, snapshots = _ths_sources()
    second = dict(snapshots)
    second["timestamp"] = snapshots["timestamp"] + 1
    second["item"] = []
    result = FuyaoMarketAdapter().normalize_sector_index_data(calendar, catalog, (snapshots, second), AS_OF)
    assert result.status == "fallback"
    assert not any("different Shanghai dates" in warning for warning in result.warnings)
    assert result.quality["snapshotTimestampDateConsistent"] is True


def test_ths_sector_batches_reject_different_shanghai_dates_or_missing_timestamp():
    calendar, catalog, snapshots = _ths_sources()
    second = dict(snapshots)
    second["timestamp"] = snapshots["timestamp"] + 86_400_000
    second["item"] = snapshots["item"][:1]
    mismatched = FuyaoMarketAdapter().normalize_sector_index_data(calendar, catalog, (snapshots, second), AS_OF)
    assert mismatched.status == "insufficient"
    assert any("different Shanghai dates" in warning for warning in mismatched.warnings)

    missing = dict(snapshots)
    missing.pop("timestamp")
    missing_result = FuyaoMarketAdapter().normalize_sector_index_data(calendar, catalog, (snapshots, missing), AS_OF)
    assert missing_result.status == "insufficient"
    assert any("timestamp missing" in warning for warning in missing_result.warnings)


def _historical_index_payload(as_of: date, identity: str, count: int = 280) -> dict:
    rows = []
    for offset in range(count - 1, -1, -1):
        day = as_of - timedelta(days=offset)
        base = 3000.0 + (count - offset) / 10
        rows.append(
            {
                "date_ms": int(datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000),
                "open_price": base,
                "high_price": base + 10,
                "low_price": base - 10,
                "close_price": base + 2,
                "turnover": 1000000000 + offset,
            }
        )
    return {"timestamp": rows[-1]["date_ms"], "item": rows}


def test_v2_core_fetches_documented_endpoint_and_checks_all_five_indices():
    session = Session(
        [
            Response({"code": 0, "data": _historical_index_payload(AS_OF, identity)})
            for identity in ("000001.SH", "399001.SZ", "399006.SZ", "000300.SH", "000905.SH")
        ]
    )
    adapter = FuyaoMarketAdapter(client(session))
    result = adapter.fetch_core(AS_OF)
    assert set(result) == set(adapter.INDEX_CODES)
    assert all(item.status == "ok" and item.observations == 280 for item in result.values())
    assert all(item.quality["providerRevision"] == "fuyao-market-v2" for item in result.values())
    assert all(call[0].endswith("/api/a-share-index/prices/historical") for call in session.calls)
    assert all(call[1]["params"]["interval"] == "1d" for call in session.calls)
    assert all(set(call[1]["params"]) == {"thscode", "interval", "start", "end"} for call in session.calls)


def test_v2_core_requires_last_valid_bar_on_requested_shanghai_date():
    rows = _historical_index_payload(AS_OF, "000001.SH")["item"]
    rows[-1]["turnover"] = None
    result = FuyaoMarketAdapter().normalize_core({"sh000001": rows}, AS_OF, min_bars=1)["sh000001"]
    assert result.status == "insufficient"
    assert any("latest valid" in warning for warning in result.warnings)


def test_v2_core_derives_change_pct_from_date_local_closes():
    rows = [
        {
            "date": "2026-09-17",
            "open_price": 100,
            "high_price": 102,
            "low_price": 99,
            "close_price": 100,
            "turnover": 1000,
        },
        {
            "date": AS_OF.isoformat(),
            "open_price": 101,
            "high_price": 104,
            "low_price": 100,
            "close_price": 103,
            "turnover": 1100,
        },
    ]
    result = FuyaoMarketAdapter().normalize_core({"sh000001": rows}, AS_OF, min_bars=1)["sh000001"]

    assert result.status == "ok"
    assert result.payload["changePct"] == 3.0
    assert result.payload["amountEvidence"] == "direct-turnover"


def test_v2_breadth_accepts_page_timestamp_drift_with_stable_shanghai_date():
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    timestamp = int(datetime.combine(today, datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)
    pages = [
        {"timestamp": timestamp, "total": 3, "item": [
            {"thscode": "600001.SH", "price_change_ratio_pct": 1.0},
            {"thscode": "000001.SZ", "price_change_ratio_pct": -1.0},
        ]},
        {"timestamp": timestamp, "total": 3, "item": [
            {"thscode": "430001.BJ", "price_change_ratio_pct": 0.0},
        ]},
    ]
    session = Session([Response({"code": 0, "data": page}) for page in pages])
    result = FuyaoMarketAdapter(client(session)).fetch_breadth(today, page_size=2)
    assert result.status == "ok"
    assert result.payload["validCount"] == 3
    assert [call[1]["params"] for call in session.calls] == [
        {"limit": 2, "offset": 0},
        {"limit": 2, "offset": 2},
    ]
    changed = [dict(page) for page in pages]
    changed[1] = dict(changed[1], timestamp=timestamp + 2_000)
    accepted = FuyaoMarketAdapter().normalize_breadth(changed, today)
    assert accepted.status == "ok"
    assert accepted.quality["timestampExactStable"] is False
    assert accepted.quality["timestampDateStable"] is True
    assert accepted.quality["timestampDateConsistent"] is True
    assert accepted.quality["minTimestamp"] == timestamp
    assert accepted.quality["maxTimestamp"] == timestamp + 2_000
    assert accepted.quality["rawTimestamps"] == [timestamp, timestamp + 2_000]
    assert accepted.quality["timestampSpanMs"] == 2_000
    assert any("timestamps differ" in warning for warning in accepted.warnings)

    changed[1] = dict(changed[1], timestamp=timestamp + 86_400_000)
    rejected = FuyaoMarketAdapter().normalize_breadth(changed, today)
    assert rejected.status == "insufficient"
    assert any("snapshot date mismatch" in warning for warning in rejected.warnings)


def test_v2_breadth_retains_missing_change_ratio_as_partial_without_zero_fill():
    timestamp = int(datetime.combine(AS_OF, datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)
    pages = [
        {
            "timestamp": timestamp,
            "total": 2,
            "item": [
                {"thscode": "600001.SH", "price_change_ratio_pct": 1.0},
                {"thscode": "600002.SH", "price_change_ratio_pct": None},
            ],
        }
    ]
    result = FuyaoMarketAdapter().normalize_breadth(pages, AS_OF)
    assert result.status == "partial"
    assert result.payload["validCount"] == 1
    assert result.payload["flatCount"] == 0
    assert result.quality["fieldCoverage"] == {
        "rows": 2,
        "priceChangeRatioPct": 1,
        "missingPriceChangeRatioPct": 1,
    }
    assert any("missing valid price_change_ratio_pct" in warning for warning in result.warnings)


def test_v2_breadth_does_not_call_latest_only_endpoint_for_historical_date():
    session = Session([])
    historical = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    result = FuyaoMarketAdapter(client(session)).fetch_breadth(historical)
    assert result.status == "insufficient"
    assert session.calls == []
