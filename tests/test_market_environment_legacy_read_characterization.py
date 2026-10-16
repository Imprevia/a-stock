"""Compatibility characterization for the legacy market-environment reads.

These assertions intentionally preserve the current unversioned contracts while
the additive v2 resource API is introduced.  In particular, ``section`` on the
Chapter 01 route selects work but does not project siblings out of the response.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from src.market_environment.snapshot_store import SnapshotIntegrityError

from src.market_environment.service import MarketEnvironmentService
from tests.market_environment_api_support import build_test_app


AS_OF = date(2026, 10, 12)
GENERATED_AT = "2026-10-12T16:05:00+08:00"
CHAPTER_SECTIONS = ("breadth", "limits", "sectors", "activeDirection", "summary")
CHAPTER_SIBLINGS = {
    "breadth",
    "limits",
    "industryRanking",
    "sectorTurnover",
    "sectorBreadth",
    "sectorAnalysis",
    "activeDirection",
    "events",
    "combinationOverview",
    "assessment",
}


def _summary(marker: str) -> dict:
    return {
        "synchronization": marker,
        "dominantTrend": "数据不足",
        "warnings": [],
    }


def _chapter(as_of: date) -> dict:
    builder = MarketEnvironmentService(provider=object())
    core = {
        "asOf": as_of.isoformat(),
        "generatedAt": GENERATED_AT,
        "indices": [],
        "summary": _summary("chapter fixture"),
        "requestedAsOf": as_of,
        "effectiveDate": as_of,
    }
    missing = builder._missing_chapter_provider_data(
        as_of,
        "legacy characterization fixture",
        status="missing",
    )
    return builder._build_chapter01(core, missing)


class _LegacyMarketQueries:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.chapter = _chapter(AS_OF)

    def get(self, as_of: date) -> dict:
        self.calls.append(("aggregate", None))
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": GENERATED_AT,
            "indices": [],
            "summary": _summary("aggregate fixture"),
            "chapter01": self.chapter,
        }

    def get_core(self, as_of: date) -> dict:
        self.calls.append(("core", None))
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": GENERATED_AT,
            "indices": [],
            "summary": _summary("core fixture"),
        }

    def get_chapter01(self, as_of: date, section: str) -> dict:
        self.calls.append(("chapter01", section))
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": GENERATED_AT,
            "summary": _summary(f"{section} fixture"),
            "chapter01": self.chapter,
        }

    def get_next_session_comparison(self, as_of: date) -> dict:
        self.calls.append(("next-session", None))
        return {
            "status": "insufficient",
            "requestedAsOf": as_of.isoformat(),
            "currentAsOf": as_of.isoformat(),
            "nextAsOf": None,
            "current": None,
            "next": None,
            "deltas": {},
            "warnings": ["本地没有下一交易日证据"],
        }


class _LegacyThsQueries:
    provider_calls = 0

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def list_catalog(self, **kwargs) -> dict:
        self.calls.append(("catalog", kwargs))
        return {
            "revision": None,
            "items": [],
            "pagination": {"page": kwargs["page"], "pageSize": kwargs["page_size"], "total": 0},
        }

    def get_bars(self, thscode: str, **kwargs) -> dict:
        self.calls.append(("bars", (thscode, kwargs)))
        return {
            "thscode": "885001.TI",
            "requestedRange": {"start": "2026-10-01", "end": "2026-10-12"},
            "coverage": {
                "firstDate": None,
                "lastDate": None,
                "storedRows": 0,
                "gaps": [
                    {"kind": "leading", "start": "2026-10-01", "end": "2026-10-12"}
                ],
            },
            "items": [],
            "pagination": {"page": kwargs["page"], "pageSize": kwargs["page_size"], "total": 0},
        }

    def get_operation(self, run_id: str) -> dict:
        self.calls.append(("operation", run_id))
        return {
            "runId": run_id,
            "operation": "turnover-backfill",
            "status": "partial",
            "summary": {
                "completedItems": 1,
                "totalItems": 2,
                "failedItems": 1,
                "conflictItems": 0,
            },
            "warning": "one checkpoint failed",
            "checkpoints": [
                {
                    "thscode": "885001.TI",
                    "windowStart": "2026-10-01",
                    "windowEnd": "2026-10-12",
                    "status": "success",
                    "rowsWritten": 1,
                    "rowsSkipped": 0,
                    "conflicts": 0,
                    "warning": None,
                }
            ],
        }


def test_legacy_aggregate_and_core_paths_keep_their_existing_shapes() -> None:
    queries = _LegacyMarketQueries()
    client = TestClient(
        build_test_app(market_queries=queries, effective_date=AS_OF)
    )

    aggregate = client.get("/api/market-environment", params={"as_of": AS_OF.isoformat()})
    core = client.get("/api/market-environment/core", params={"as_of": AS_OF.isoformat()})

    assert aggregate.status_code == 200
    assert aggregate.json()["summary"]["synchronization"] == "aggregate fixture"
    assert CHAPTER_SIBLINGS <= aggregate.json()["chapter01"].keys()
    assert core.status_code == 200
    assert core.json()["summary"]["synchronization"] == "core fixture"
    assert core.json()["chapter01"] is None
    assert queries.calls == [("aggregate", None), ("core", None)]


def test_legacy_integrity_failure_is_a_safe_stable_503() -> None:
    class BrokenQueries(_LegacyMarketQueries):
        def get_core(self, as_of):
            raise SnapshotIntegrityError(
                "checksum=/secret/path sql=SELECT provider_payload=must-not-leak"
            )

    response = TestClient(
        build_test_app(market_queries=BrokenQueries(), effective_date=AS_OF)
    ).get(
        "/api/market-environment/core",
        params={"as_of": AS_OF.isoformat()},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "snapshot_integrity_error",
        "message": "本地市场数据完整性校验失败，请联系运维审计对应日期的数据。",
    }
    assert "must-not-leak" not in response.text


def test_legacy_chapter_section_still_returns_all_cumulative_siblings() -> None:
    queries = _LegacyMarketQueries()
    client = TestClient(
        build_test_app(market_queries=queries, effective_date=AS_OF)
    )

    payloads = []
    for section in CHAPTER_SECTIONS:
        response = client.get(
            "/api/market-environment/chapter-01",
            params={"as_of": AS_OF.isoformat(), "section": section},
        )
        assert response.status_code == 200
        payload = response.json()["chapter01"]
        assert CHAPTER_SIBLINGS <= payload.keys()
        payloads.append(payload)

    assert all(payload == payloads[0] for payload in payloads[1:])
    assert queries.calls == [("chapter01", section) for section in CHAPTER_SECTIONS]


def test_legacy_next_session_path_keeps_the_comparison_contract() -> None:
    queries = _LegacyMarketQueries()
    response = TestClient(
        build_test_app(market_queries=queries, effective_date=AS_OF)
    ).get(
        "/api/market-environment/next-session",
        params={"as_of": AS_OF.isoformat()},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "insufficient",
        "requestedAsOf": AS_OF.isoformat(),
        "currentAsOf": AS_OF.isoformat(),
        "nextAsOf": None,
        "current": None,
        "next": None,
        "deltas": {
            "directionPattern": None,
            "advancingIndexCount": None,
            "decliningIndexCount": None,
            "aboveMa20Count": None,
            "medianAmountRatio5": None,
            "volumeBackedAdvanceCount": None,
            "volumeBackedDeclineCount": None,
            "advanceRatio": None,
            "medianReturn": None,
        },
        "warnings": ["本地没有下一交易日证据"],
    }
    assert queries.calls == [("next-session", None)]


def test_legacy_ths_catalog_bars_and_operation_reads_keep_their_contracts() -> None:
    queries = _LegacyThsQueries()
    client = TestClient(build_test_app(ths_queries=queries, effective_date=AS_OF))

    catalog = client.get(
        "/api/market-environment/ths/catalog",
        params={"tag": "industry", "page": 2, "page_size": 25},
    )
    bars = client.get(
        "/api/market-environment/ths/sectors/885001.ti/bars",
        params={
            "start_date": "2026-10-01",
            "end_date": AS_OF.isoformat(),
            "page": 1,
            "page_size": 1000,
        },
    )
    operation = client.get("/api/market-environment/ths/operations/run-legacy")

    assert catalog.status_code == 200
    assert catalog.json() == {
        "revision": None,
        "items": [],
        "page": 2,
        "pageSize": 25,
        "total": 0,
    }
    assert bars.status_code == 200
    assert bars.json()["thscode"] == "885001.TI"
    assert bars.json()["coverage"] == {
        "firstDate": None,
        "lastDate": None,
        "storedRows": 0,
        "gaps": ["2026-10-01~2026-10-12"],
    }
    assert bars.json()["pageSize"] == 1000
    assert operation.status_code == 200
    assert operation.json()["progress"] == {
        "completed": 1,
        "total": 2,
        "failed": 1,
        "conflicts": 0,
    }
    assert len(operation.json()["checkpoints"]) == 1
    assert queries.provider_calls == 0
    assert [call[0] for call in queries.calls] == ["catalog", "bars", "operation"]
