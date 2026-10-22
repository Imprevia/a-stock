"""Resource isolation, parity and bounded pagination for the v2 HTTP API."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from src.market_environment.application.queries import V2MarketDataQueries
from src.market_environment.infrastructure.v2_market_data_compat import (
    CompatibilityV2MarketDataReadAdapter,
)
from tests.market_environment_api_support import build_test_app


AS_OF = date(2026, 10, 15)
ROOT = f"/api/v2/market-environment/{AS_OF.isoformat()}"


class _GuardedCompatibilityAdapter(CompatibilityV2MarketDataReadAdapter):
    def __init__(self, aggregates):
        super().__init__(aggregates)
        self.provider_calls = 0
        self.write_calls = 0
        self.history_calls: list[tuple[str, object]] = []

    def breadth_history(self, as_of, **kwargs):
        self.history_calls.append(("breadth", kwargs.get("after")))
        return super().breadth_history(as_of, **kwargs)

    def limits_history(self, as_of, **kwargs):
        self.history_calls.append(("limits", kwargs.get("after")))
        return super().limits_history(as_of, **kwargs)


def _quality(status: str = "ok") -> dict:
    return {
        "dataset": "fixture",
        "source": "local-fixture",
        "provider": "local",
        "status": status,
        "observations": 3,
        "asOf": AS_OF.isoformat(),
        "warnings": [],
    }


def _aggregate() -> dict:
    history = [
        {"date": f"2026-10-{day:02d}", "close": float(day)}
        for day in (13, 14, 15)
    ]
    breadth_history = [
        {"asOf": f"2026-10-{day:02d}", "advanceCount": day, "quality": _quality()}
        for day in (13, 14, 15)
    ]
    limit_history = [
        {"asOf": f"2026-10-{day:02d}", "limitUpCount": day, "quality": _quality()}
        for day in (13, 14, 15)
    ]
    pools = {
        key: {
            "total": 3,
            "quality": {"status": "ok", "asOf": AS_OF.isoformat(), "warnings": []},
            "rows": [
                {
                    "securityId": f"SH:60000{index}",
                    "code": f"60000{index}",
                    "exchange": "SH",
                    "name": f"证券{index}",
                    "poolType": "limit_up" if key == "promoted" else key,
                    "source": "local-fixture",
                    "warnings": [],
                }
                for index in range(1, 4)
            ],
        }
        for key in ("limitUp", "limitDown", "failedLimitUp", "promoted")
    }
    sector_rows = [
        {"tag": "industry", "rank": index, "thscode": f"88500{index}.TI", "name": f"板块{index}"}
        for index in range(1, 4)
    ]
    return {
        "asOf": AS_OF.isoformat(),
        "generatedAt": "2026-10-15T16:30:00+08:00",
        "summary": {"synchronization": "同步", "dominantTrend": "震荡", "warnings": []},
        "indices": [
            {
                "code": "000001.SH",
                "name": "上证指数",
                "close": 3210.0,
                "changePct": 0.5,
                "history": history,
                "dataQuality": _quality(),
            }
        ],
        "chapter01": {
            "status": "ok",
            "coverage": 1.0,
            "summarySentence": "fixture conclusion",
            "marketEvidence": {"directionPattern": "synchronized_rally"},
            "breadth": {
                "advanceCount": 3000,
                "declineCount": 1500,
                "quality": _quality(),
                "history": {"points": breadth_history},
            },
            "limits": {
                "limitUpCount": 55,
                "limitDownCount": 4,
                "quality": _quality(),
                "securityDetails": pools,
                "history": {"points": limit_history},
                "ruleEvidence": [{"ruleId": "QTS-01-03-01", "status": "ok"}],
                "riskEvidence": [{"code": "failure-repair", "status": "ok"}],
            },
            "industryRanking": {"quality": _quality(), "rows": sector_rows},
            "sectorTurnover": {"quality": _quality(), "rows": sector_rows},
            "sectorBreadth": {"quality": _quality(), "rows": sector_rows},
            "sectorAnalysis": {"quality": _quality(), "candidates": [{"industryId": "801010"}]},
            "activeDirection": {
                "state": "ok",
                "quality": _quality(),
                "topStocks": [
                    {"code": f"00000{index}", "name": f"活跃{index}", "amount": index * 100.0}
                    for index in range(1, 4)
                ],
            },
            "events": {
                "state": "ok",
                "quality": _quality(),
                "items": [{"id": f"event-{index}", "title": f"事件{index}"} for index in range(1, 4)],
            },
            "assessment": {
                "state": "ok",
                "confidence": "medium",
                "evidence": ["fixture"],
                "risks": [],
                "nextConfirmation": "observe",
                "invalidation": "none",
            },
        },
        "_componentRevision": {"private": "must-not-leak"},
    }


def _client() -> TestClient:
    operations = {
        "run-1": {
            "runId": "run-1",
            "kind": "turnover-backfill",
            "status": "partial",
            "progress": {"completed": 2, "total": 3, "failed": 1, "conflicts": 0},
            "requestedAt": "2026-10-15T16:00:00+08:00",
            "completedAt": "2026-10-15T16:30:00+08:00",
            "checkpoints": [
                {
                    "thscode": f"88500{index}.TI",
                    "windowStart": "2026-10-01",
                    "windowEnd": AS_OF.isoformat(),
                    "status": "success" if index < 3 else "failed",
                }
                for index in range(1, 4)
            ],
        }
    }
    reads = CompatibilityV2MarketDataReadAdapter({AS_OF: _aggregate()}, operations=operations)
    return TestClient(
        build_test_app(
            v2_queries=V2MarketDataQueries(reads),
            effective_date=AS_OF,
        )
    )


def _all_pages(client: TestClient, path: str, *, limit: int = 2) -> list[dict]:
    items: list[dict] = []
    cursor = None
    revision = None
    while True:
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if revision:
            params["revision"] = revision
        response = client.get(path, params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        revision = body["snapshotRevision"]
        items.extend(body["data"]["items"])
        cursor = body["pagination"]["nextCursor"]
        if cursor is None:
            return items


def test_overview_indices_and_single_index_are_compact_and_same_revision() -> None:
    client = _client()
    overview = client.get(f"{ROOT}/overview").json()
    indices = client.get(f"{ROOT}/indices", params={"revision": overview["snapshotRevision"]}).json()
    detail = client.get(f"{ROOT}/indices/000001.SH", params={"revision": overview["snapshotRevision"]}).json()

    assert overview["data"]["summary"]["synchronization"] == "同步"
    assert "chapter01" not in overview["data"]
    assert indices["data"]["items"][0]["close"] == detail["data"]["close"] == 3210.0
    assert "history" not in indices["data"]["items"][0]
    assert "history" not in detail["data"]
    assert {overview["snapshotRevision"], indices["snapshotRevision"], detail["snapshotRevision"]} == {overview["snapshotRevision"]}
    assert "must-not-leak" not in str(overview)


def test_index_breadth_and_limits_history_paginate_every_point_once() -> None:
    client = _client()
    for path in (
        f"{ROOT}/indices/000001.SH/history",
        f"{ROOT}/breadth/history",
        f"{ROOT}/limits/history",
    ):
        rows = _all_pages(client, path)
        identity = [row.get("date") or row.get("asOf") for row in rows]
        assert identity == ["2026-10-13", "2026-10-14", "2026-10-15"]
        assert len(identity) == len(set(identity))


def test_breadth_and_limits_http_history_pages_are_revision_pinned_and_read_only() -> None:
    reads = _GuardedCompatibilityAdapter({AS_OF: _aggregate()})
    client = TestClient(
        build_test_app(
            v2_queries=V2MarketDataQueries(reads),
            effective_date=AS_OF,
        )
    )

    for resource in ("breadth", "limits"):
        first = client.get(f"{ROOT}/{resource}/history", params={"limit": 2})
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert first_body["pagination"]["returned"] == 2
        assert first_body["pagination"]["hasMore"] is True
        second = client.get(
            f"{ROOT}/{resource}/history",
            params={
                "limit": 2,
                "cursor": first_body["pagination"]["nextCursor"],
                "revision": first_body["snapshotRevision"],
            },
        )
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert second_body["snapshotRevision"] == first_body["snapshotRevision"]
        assert second_body["pagination"]["returned"] == 1

    assert reads.history_calls == [
        ("breadth", None),
        ("breadth", ("2026-10-14",)),
        ("limits", None),
        ("limits", ("2026-10-14",)),
    ]
    assert reads.provider_calls == 0
    assert reads.write_calls == 0


def test_history_cursor_rejects_stale_revision_changed_filters_and_cross_resource_use() -> None:
    reads = _GuardedCompatibilityAdapter({AS_OF: _aggregate()})
    client = TestClient(
        build_test_app(
            v2_queries=V2MarketDataQueries(reads),
            effective_date=AS_OF,
        )
    )
    first = client.get(f"{ROOT}/breadth/history", params={"limit": 2})
    assert first.status_code == 200
    body = first.json()
    cursor = body["pagination"]["nextCursor"]

    stale = client.get(
        f"{ROOT}/breadth/history",
        params={"limit": 2, "cursor": cursor, "revision": "sr1_stale"},
    )
    changed_filter = client.get(
        f"{ROOT}/breadth/history",
        params={"limit": 2, "cursor": cursor, "start_date": "2026-10-14"},
    )
    cross_resource = client.get(
        f"{ROOT}/limits/history",
        params={"limit": 2, "cursor": cursor},
    )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "snapshot_revision_conflict"
    assert changed_filter.status_code == 422
    assert cross_resource.status_code == 422
    assert reads.provider_calls == 0
    assert reads.write_calls == 0


def test_limits_summary_evidence_and_each_pool_are_independent() -> None:
    client = _client()
    summary = client.get(f"{ROOT}/limits").json()["data"]
    evidence = client.get(f"{ROOT}/limits/evidence").json()["data"]

    assert summary["limitUpCount"] == 55
    assert not {"securityDetails", "history", "ruleEvidence", "riskEvidence"} & summary.keys()
    assert set(evidence) == {"ruleEvidence", "riskEvidence"}
    for pool_type in ("limit_up", "limit_down", "failed_limit_up", "promoted"):
        rows = _all_pages(client, f"{ROOT}/limits/pools/{pool_type}")
        assert len(rows) == 3
        assert len({row["securityId"] for row in rows}) == 3


def test_limits_pool_exposes_pool_specific_quality_and_retained_warning() -> None:
    aggregate = _aggregate()
    limits = aggregate["chapter01"]["limits"]
    limits["quality"] = {
        **_quality("failed-retained"),
        "refreshWarning": "保留同日旧数据",
    }
    limits["securityDetails"]["limitUp"]["quality"] = _quality("ok")
    reads = CompatibilityV2MarketDataReadAdapter({AS_OF: aggregate})
    client = TestClient(
        build_test_app(
            v2_queries=V2MarketDataQueries(reads),
            effective_date=AS_OF,
        )
    )

    body = client.get(f"{ROOT}/limits/pools/limit_up").json()

    assert body["quality"]["status"] == "failed-retained"
    assert body["quality"]["warnings"] == ["保留同日旧数据"]


def test_sector_resources_are_isolated_bounded_and_link_existing_ths_reads() -> None:
    client = _client()
    for name in ("rankings", "turnover", "breadth"):
        response = client.get(f"{ROOT}/sectors/{name}", params={"limit": 2})
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]["items"]) == 2
        assert body["pagination"]["hasMore"] is True
        hrefs = {link["href"] for link in body["links"]}
        assert "/api/market-environment/ths/catalog" in hrefs
        assert "/api/market-environment/ths/sectors/{thscode}/bars" in hrefs
        encoded = response.text
        assert "activeDirection" not in encoded
        assert "securityDetails" not in encoded
    analysis = client.get(f"{ROOT}/sectors/analysis").json()["data"]
    assert analysis["candidates"][0]["industryId"] == "801010"


def test_active_direction_events_and_assessment_preserve_missing_semantics_and_bounds() -> None:
    client = _client()
    active = _all_pages(client, f"{ROOT}/active-direction")
    events = _all_pages(client, f"{ROOT}/events")
    assessment = client.get(f"{ROOT}/assessment").json()

    assert len(active) == len(events) == 3
    assert assessment["data"]["confidence"] == "medium"
    assert assessment["quality"]["status"] in {"missing", "insufficient"}


def test_operation_summary_excludes_checkpoints_and_checkpoint_pages_preserve_counts() -> None:
    client = _client()
    summary = client.get("/api/v2/market-environment/operations/run-1")
    rows = _all_pages(client, "/api/v2/market-environment/operations/run-1/checkpoints")

    assert summary.status_code == 200
    assert "checkpoints" not in summary.json()["data"]
    assert summary.json()["data"]["progress"] == {"completed": 2, "total": 3, "failed": 1, "conflicts": 0}
    assert len(rows) == 3


def test_etag_304_and_stale_cursor_conflict_do_not_read_another_date() -> None:
    client = _client()
    first = client.get(f"{ROOT}/overview")
    unchanged = client.get(f"{ROOT}/overview", headers={"If-None-Match": first.headers["etag"]})
    first_page = client.get(f"{ROOT}/limits/pools/limit_up", params={"limit": 2}).json()
    stale = client.get(
        f"{ROOT}/limits/pools/limit_up",
        params={"limit": 2, "cursor": first_page["pagination"]["nextCursor"], "revision": "sr1_stale"},
    )

    assert unchanged.status_code == 304
    assert unchanged.content == b""
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "snapshot_revision_conflict"
