"""Golden API contracts captured before the market-environment refactor."""

from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from src.market_environment.collection import CollectionCoordinator
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.service import MarketEnvironmentService
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore
from tests.market_environment_api_support import (
    FakeCollectionCommands,
    build_test_app,
)
from tests.test_market_environment_collection import AS_OF, CollectionProvider


class _ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)


class _ContractService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    def get(self, as_of: date) -> dict:
        if self.error is not None:
            raise self.error
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-08-29T15:05:00+08:00",
            "indices": [],
            "summary": {
                "synchronization": "无可用数据",
                "dominantTrend": "数据不足",
                "warnings": ["characterization fixture"],
            },
        }

    def get_chapter01(self, as_of: date, section: str) -> dict:
        builder = MarketEnvironmentService(provider=object())
        core = {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-08-29T15:05:00+08:00",
            "indices": [],
            "summary": {
                "synchronization": "无可用数据",
                "dominantTrend": "数据不足",
                "warnings": [],
            },
            "requestedAsOf": as_of,
            "effectiveDate": as_of,
        }
        provider_data = builder._missing_chapter_provider_data(
            as_of,
            "characterization missing fixture",
            status="missing",
        )
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": core["generatedAt"],
            "chapter01": builder._build_chapter01(core, provider_data),
        }


def _coordinator(tmp_path, provider=None) -> CollectionCoordinator:
    market_now = datetime.combine(
        AS_OF,
        datetime.min.time(),
        tzinfo=MARKET_TIME_ZONE,
    ).replace(hour=16)
    return CollectionCoordinator(
        provider or CollectionProvider(),
        SnapshotStore(tmp_path / "characterization.sqlite3"),
        now=lambda: market_now,
    )


def _dataset(response, dataset: str) -> dict:
    return next(item for item in response.json()["datasets"] if item["dataset"] == dataset)


def test_characterizes_success_route_alias_and_status_code(monkeypatch) -> None:
    response = TestClient(
        build_test_app(
            market_queries=_ContractService(),
            effective_date=date(2026, 9, 3),
        )
    ).get(
        "/api/market-environment",
        params={"as_of": "2026-08-28"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "asOf": "2026-08-28",
        "generatedAt": "2026-08-29T15:05:00+08:00",
        "indices": [],
        "summary": {
            "synchronization": "无可用数据",
            "dominantTrend": "数据不足",
            "warnings": ["characterization fixture"],
            "syncPattern": None,
            "synchronizationAssessment": None,
            "bullishAlignmentRatio": None,
            "marketEvidence": None,
            "reviewSentence": None,
            "dataGaps": [],
        },
        "chapter01": None,
    }


def test_characterizes_missing_chapter_quality_and_exact_date(monkeypatch) -> None:
    response = TestClient(
        build_test_app(
            market_queries=_ContractService(),
            effective_date=date(2026, 9, 3),
        )
    ).get(
        "/api/market-environment/chapter-01",
        params={"as_of": "2026-08-28", "section": "breadth"},
    )

    assert response.status_code == 200
    assert response.json()["asOf"] == "2026-08-28"
    quality = response.json()["chapter01"]["breadth"]["quality"]
    assert quality == {
        "dataset": "market-breadth",
        "source": "none",
        "provider": "none",
        "status": "missing",
        "observations": 0,
        "asOf": "2026-08-28",
        "warning": "characterization missing fixture",
        "warnings": ["characterization missing fixture"],
        "cacheState": None,
        "snapshotFetchedAt": None,
        "refreshing": None,
        "refreshWarning": None,
        "derived": None,
        "rankingMethod": None,
        "sourceRevision": None,
        "industryMappingRevision": None,
        "industryMappingCoverage": None,
        "industryMappingCovered": None,
        "industryMappingTotal": None,
        "stockUniversePolicyVersion": None,
        "stockUniverseRawCount": None,
        "stockUniverseRetainedCount": None,
        "stockUniverseExcludedCount": None,
        "stockUniverseUnclassifiedCount": None,
        "stockUniverseRetainedByMarket": None,
        "stockUniverseExcludedByReason": None,
        "stockUniverseUnclassifiedByReason": None,
        "sectorEnrichment": None,
    }


def test_characterizes_partial_run_and_sibling_success(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1")
    coordinator = _coordinator(
        tmp_path,
        CollectionProvider(failing_datasets={"sectors"}),
    )
    client = TestClient(
        build_test_app(
            collection_queries=coordinator,
            collection_commands=FakeCollectionCommands(
                coordinator,
                _ImmediateExecutor(),
            ),
            effective_date=AS_OF,
        )
    )

    started = client.post(
        "/api/market-environment/collection-runs",
        json={"asOf": AS_OF.isoformat()},
    )
    polled = client.get(
        f"/api/market-environment/collection-runs/{started.json()['runId']}"
    )

    assert started.status_code == 202
    assert polled.status_code == 200
    assert polled.json()["asOf"] == AS_OF.isoformat()
    assert polled.json()["status"] == "partial"
    tasks = {item["dataset"]: item for item in polled.json()["tasks"]}
    assert tasks["breadth"]["status"] == "success"
    assert tasks["breadth"]["source"] == "fixture"
    assert tasks["breadth"]["observations"] == 3
    assert tasks["sectors"]["status"] == "failed-missing"
    assert tasks["sectors"]["source"] == "none"
    assert "sectors unavailable" in tasks["sectors"]["warning"]


def test_characterizes_degraded_local_status_without_provider_call(monkeypatch, tmp_path) -> None:
    provider = CollectionProvider()
    coordinator = _coordinator(tmp_path, provider)
    coordinator.store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=AS_OF,
            payload={
                "quality": {
                    "dataset": "market-breadth",
                    "source": "fixture-degraded",
                    "provider": "fixture",
                    "status": "degraded",
                    "observations": 2,
                    "asOf": AS_OF.isoformat(),
                    "warning": "characterization degraded fixture",
                    "warnings": ["characterization degraded fixture"],
                }
            },
            source="fixture-degraded",
            status="degraded",
            observations=2,
            warnings=("characterization degraded fixture",),
            fetched_at=datetime(2026, 9, 3, 16, tzinfo=MARKET_TIME_ZONE),
            settled=True,
            refresh_warning="retained degraded evidence",
        )
    )
    provider.calls.clear()

    response = TestClient(
        build_test_app(
            collection_queries=coordinator,
            effective_date=AS_OF,
        )
    ).get(
        "/api/market-environment/data-collection",
        params={"as_of": AS_OF.isoformat()},
    )

    assert response.status_code == 200
    assert response.json()["asOf"] == AS_OF.isoformat()
    breadth = _dataset(response, "breadth")
    assert breadth["available"] is True
    assert breadth["source"] == "fixture-degraded"
    assert breadth["observations"] == 2
    assert breadth["refreshWarning"] == "retained degraded evidence"
    assert breadth["quality"] == {
        "dataset": "market-breadth",
        "source": "fixture-degraded",
        "provider": "fixture",
        "status": "degraded",
        "observations": 2,
        "asOf": AS_OF.isoformat(),
        "warning": "characterization degraded fixture",
        "warnings": ["characterization degraded fixture"],
    }
    assert provider.calls == []


def test_characterizes_failed_retained_attempt_and_snapshot(monkeypatch, tmp_path) -> None:
    provider = CollectionProvider()
    current = [datetime(2026, 9, 3, 16, tzinfo=MARKET_TIME_ZONE)]
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "characterization.sqlite3"),
        now=lambda: current[0],
    )
    first = coordinator.collect(AS_OF, ["sectors"])
    assert first.tasks[0].status == "success"
    current[0] += timedelta(minutes=1)
    provider.failing_datasets.add("sectors")
    failed = coordinator.collect(AS_OF, ["sectors"])
    assert failed.tasks[0].status == "failed-retained"
    provider.calls.clear()

    response = TestClient(
        build_test_app(
            collection_queries=coordinator,
            effective_date=AS_OF,
        )
    ).get(
        "/api/market-environment/data-collection",
        params={"as_of": AS_OF.isoformat()},
    )

    assert response.status_code == 200
    sectors = _dataset(response, "sectors")
    assert sectors["available"] is True
    assert sectors["source"] == "fixture"
    assert sectors["observations"] == 3
    assert sectors["quality"]["status"] == "ok"
    assert sectors["quality"]["asOf"] == AS_OF.isoformat()
    assert "sectors unavailable" in sectors["refreshWarning"]
    assert sectors["latestAttempt"]["status"] == "failed-retained"
    assert "sectors unavailable" in sectors["latestAttempt"]["warning"]
    assert provider.calls == []


def test_characterizes_503_and_validation_error_statuses(monkeypatch) -> None:
    client = TestClient(
        build_test_app(
            market_queries=_ContractService(
                error=RuntimeError("characterization provider failure")
            ),
            effective_date=date(2026, 9, 3),
        )
    )

    provider_failure = client.get(
        "/api/market-environment",
        params={"as_of": "2026-08-28"},
    )
    invalid_section = client.get(
        "/api/market-environment/chapter-01",
        params={"as_of": "2026-08-28", "section": "unknown"},
    )
    invalid_date = client.get(
        "/api/market-environment",
        params={"as_of": "not-a-date"},
    )

    assert provider_failure.status_code == 503
    assert provider_failure.json() == {"detail": "characterization provider failure"}
    assert invalid_section.status_code == 422
    assert invalid_date.status_code == 422
