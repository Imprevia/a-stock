from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from src.market_environment.application.commands import ThsOperationGateError
from tests.market_environment_api_support import build_test_app


AS_OF = date(2026, 10, 12)


class LocalQueries:
    provider_calls = 0

    def __init__(self) -> None:
        self.catalog_args = None
        self.bar_args = None

    def list_catalog(self, **kwargs):
        self.catalog_args = kwargs
        return {
            "revision": {
                "id": "catalog-r1",
                "capabilityRevision": "cap-r1",
                "providerTimestamp": "2026-10-12T16:00:00+08:00",
                "fetchedAt": "2026-10-12T08:01:00+00:00",
                "checksum": "checksum-r1",
                "rowCount": 1,
                "tagCounts": {
                    "industry": 1,
                    "cn_concept": 0,
                    "region": 0,
                    "tszs": 0,
                },
            },
            "filters": {},
            "items": [
                {
                    "tag": "industry",
                    "thscode": "885001.TI",
                    "name": "合成行业",
                    "revisionId": "catalog-r1",
                }
            ],
            "pagination": {"page": 2, "pageSize": 1, "total": 3},
        }

    def get_bars(self, thscode, **kwargs):
        self.bar_args = (thscode, kwargs)
        return {
            "thscode": "885001.TI",
            "requestedRange": {"start": "2026-10-08", "end": "2026-10-12"},
            "coverage": {
                "firstDate": "2026-10-09",
                "lastDate": "2026-10-10",
                "storedRows": 2,
                "okRows": 2,
                "gaps": [
                    {"kind": "leading", "start": "2026-10-08", "end": "2026-10-08"},
                    {"kind": "trailing", "start": "2026-10-11", "end": "2026-10-12"},
                ],
                "complete": False,
            },
            "items": [
                {
                    "tradingDate": "2026-10-09",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 100.0,
                    "turnover": 200.0,
                    "source": "fuyao",
                    "sourceRevision": "history-r1",
                    "checksum": "bar-r1",
                    "fetchedAt": "2026-10-12T08:00:00+00:00",
                    "quality": "ok",
                    "warnings": [],
                }
            ],
            "pagination": {"page": 1, "pageSize": 20, "total": 2},
        }

    def get_operation(self, run_id):
        if run_id == "missing":
            raise LookupError("sensitive internal lookup")
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
                    "windowStart": "2026-10-08",
                    "windowEnd": "2026-10-09",
                    "status": "success",
                    "rowsWritten": 2,
                    "rowsSkipped": 0,
                    "conflicts": 0,
                    "warning": None,
                }
            ],
        }


class QueuedCommands:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = []
        self.error = error

    def _result(self, kind, payload):
        self.calls.append((kind, payload))
        if self.error:
            raise self.error
        return {"runId": f"{kind}-run", "status": "queued"}

    def start_catalog_sync(self, **kwargs):
        return self._result("catalog", kwargs)

    def start_turnover_backfill(self, **kwargs):
        return self._result("backfill", kwargs)

    def start_member_import(self, **kwargs):
        return self._result("import", kwargs)


def test_ths_get_routes_are_local_and_map_frozen_contract() -> None:
    queries = LocalQueries()
    client = TestClient(build_test_app(ths_queries=queries, effective_date=AS_OF))

    catalog = client.get(
        "/api/market-environment/ths/catalog",
        params={"tag": "industry", "search": "合成", "revision": "catalog-r1", "page": 2, "page_size": 1},
    )
    assert catalog.status_code == 200
    assert catalog.json() == {
        "revision": {
            "revisionId": "catalog-r1",
            "capabilityRevision": "cap-r1",
            "providerTimestamp": "2026-10-12T16:00:00+08:00",
            "fetchedAt": "2026-10-12T08:01:00Z",
            "tagCounts": {"industry": 1, "cn_concept": 0, "region": 0, "tszs": 0},
            "checksum": "checksum-r1",
        },
        "items": [{"tag": "industry", "thscode": "885001.TI", "name": "合成行业"}],
        "page": 2,
        "pageSize": 1,
        "total": 3,
    }
    assert queries.catalog_args == {
        "tag": "industry",
        "search": "合成",
        "revision_id": "catalog-r1",
        "page": 2,
        "page_size": 1,
    }

    bars = client.get(
        "/api/market-environment/ths/sectors/885001.ti/bars",
        params={"start_date": "2026-10-08", "end_date": "2026-10-12", "page_size": 20},
    )
    assert bars.status_code == 200
    assert bars.json()["requestedStart"] == "2026-10-08"
    assert bars.json()["coverage"] == {
        "firstDate": "2026-10-09",
        "lastDate": "2026-10-10",
        "storedRows": 2,
        "gaps": ["2026-10-08~2026-10-08", "2026-10-11~2026-10-12"],
    }
    assert bars.json()["items"][0]["volume"] == 100.0
    assert bars.json()["items"][0]["turnover"] == 200.0

    operation = client.get("/api/market-environment/ths/operations/run-1")
    assert operation.status_code == 200
    assert operation.json()["progress"] == {
        "completed": 1,
        "total": 2,
        "failed": 1,
        "conflicts": 0,
    }
    assert queries.provider_calls == 0
    assert client.get("/api/market-environment/ths/operations/missing").status_code == 404


def test_ths_posts_return_queued_ids_and_do_not_echo_import_paths(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1")
    commands = QueuedCommands()
    client = TestClient(
        build_test_app(ths_commands=commands, ths_queries=LocalQueries(), effective_date=AS_OF)
    )

    catalog = client.post(
        "/api/market-environment/ths/catalog/sync",
        json={"capabilityRevision": "catalog-r1", "requestBudget": 5},
    )
    assert catalog.status_code == 202
    assert catalog.json() == {"runId": "catalog-run", "status": "queued"}

    backfill = client.post(
        "/api/market-environment/ths/turnover/backfills",
        json={
            "thscodes": ["885001.TI"],
            "startDate": "2026-10-01",
            "endDate": "2026-10-12",
            "capabilityRevision": "history-r1",
            "requestBudget": 1,
        },
    )
    assert backfill.status_code == 202
    assert backfill.json() == {"runId": "backfill-run", "status": "queued"}

    manifest = {
        "path": "/private/operator/dump.parquet",
        "dumpId": "dump-1",
        "schemaRevision": "schema-r1",
        "capabilityRevision": "dump-r1",
        "checksum": "fixture-checksum",
        "startDate": "2026-10-12",
        "endDate": "2026-10-12",
    }
    imported = client.post(
        "/api/market-environment/ths/member-facts/imports",
        json={
            "asOf": "2026-10-12",
            "sourceRevision": "member-r1",
            "requestBudget": 1,
            "daily": manifest,
            "adjustment": {**manifest, "dumpId": "adjustment-1"},
        },
    )
    assert imported.status_code == 202
    assert imported.json() == {"runId": "import-run", "status": "queued"}
    assert "/private" not in imported.text


def test_ths_write_gates_fail_without_dispatch_or_secret_echo(monkeypatch) -> None:
    commands = QueuedCommands()
    client = TestClient(build_test_app(ths_commands=commands, effective_date=AS_OF))
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "0")

    response = client.post("/api/market-environment/ths/catalog/sync")
    assert response.status_code == 403
    assert commands.calls == []

    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1")
    failing = QueuedCommands(
        RuntimeError("https://signed.example/private?api_key=super-secret")
    )
    client = TestClient(build_test_app(ths_commands=failing, effective_date=AS_OF))
    response = client.post(
        "/api/market-environment/ths/turnover/backfills",
        json={
            "thscodes": ["885001.TI"],
            "startDate": "2026-10-01",
            "endDate": "2026-10-12",
        },
    )
    assert response.status_code == 403
    assert "signed.example" not in response.text
    assert "super-secret" not in response.text


def test_ths_gate_errors_are_structured_without_provider_dispatch(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1")
    commands = QueuedCommands(ThsOperationGateError("THS write permission is not authorized"))
    client = TestClient(build_test_app(ths_commands=commands, effective_date=AS_OF))

    response = client.post("/api/market-environment/ths/catalog/sync")
    assert response.status_code == 403
    assert response.json()["detail"] == "THS write permission is not authorized"
    assert len(commands.calls) == 1
