from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from src.market_environment.bootstrap.app import create_app
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.domain.models import DATASET_IDS
from src.market_environment.application.ths_diagnostics import (
    ThsDiagnostic,
    encode_ths_diagnostic,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.service import MarketEnvironmentService
from src.market_environment.schemas import CollectionTaskResponse, EvidenceQuality
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore
from tests.market_environment_api_support import (
    FakeCollectionCommands,
    build_test_app,
)
from tests.test_market_environment_collection import AS_OF, CollectionProvider


class StubService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str | None]] = []

    def get(self, as_of: date):
        self.calls.append(("aggregate", None))
        if self.error:
            raise self.error
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-08-29T15:05:00+08:00",
            "indices": [],
            "summary": {"synchronization": "无可用数据", "dominantTrend": "数据不足", "warnings": []},
        }

    def get_core(self, as_of: date):
        self.calls.append(("core", None))
        if self.error:
            raise self.error
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-08-29T15:05:00+08:00",
            "indices": [],
            "summary": {"synchronization": "无可用数据", "dominantTrend": "数据不足", "warnings": []},
        }

    def get_chapter01(self, as_of: date, section: str):
        self.calls.append(("chapter01", section))
        if self.error:
            raise self.error
        builder = MarketEnvironmentService(provider=object())
        core = {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-08-29T15:05:00+08:00",
            "indices": [],
            "summary": {"synchronization": "无可用数据", "dominantTrend": "数据不足", "warnings": []},
            "requestedAsOf": as_of,
            "effectiveDate": as_of,
        }
        provider_data = builder._missing_chapter_provider_data(as_of, "fixture", status="missing")
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": core["generatedAt"],
            "chapter01": builder._build_chapter01(core, provider_data),
        }

    def get_next_session_comparison(self, as_of: date):
        self.calls.append(("next-session", None))
        return {
            "status": "insufficient",
            "requestedAsOf": as_of.isoformat(),
            "currentAsOf": None,
            "nextAsOf": None,
            "current": None,
            "next": None,
            "deltas": {},
            "warnings": ["fixture no next session"],
        }


def test_api_route_methods_models_and_success_statuses_are_stable() -> None:
    schema = create_app().openapi()["paths"]
    expected = {
        ("/api/health", "get"): ("200", None),
        ("/api/market-environment", "get"): ("200", "MarketEnvironmentResponse"),
        ("/api/market-environment/core", "get"): ("200", "MarketEnvironmentResponse"),
        ("/api/market-environment/next-session", "get"): (
            "200",
            "NextSessionComparisonResponse",
        ),
        ("/api/market-environment/chapter-01", "get"): ("200", "Chapter01Response"),
        ("/api/market-environment/data-collection", "get"): (
            "200",
            "CollectionStatusResponse",
        ),
        ("/api/market-environment/collection-runs", "post"): (
            "202",
            "CollectionRunResponse",
        ),
        ("/api/market-environment/collection-runs/{run_id}", "get"): (
            "200",
            "CollectionRunResponse",
        ),
        ("/api/market-environment/ths/catalog", "get"): (
            "200",
            "ThsCatalogResponse",
        ),
        ("/api/market-environment/ths/sectors/{thscode}/bars", "get"): (
            "200",
            "ThsSectorBarsResponse",
        ),
        ("/api/market-environment/ths/operations/{run_id}", "get"): (
            "200",
            "ThsOperationResponse",
        ),
        ("/api/market-environment/ths/catalog/sync", "post"): (
            "202",
            "QueuedThsOperationResponse",
        ),
        ("/api/market-environment/ths/turnover/backfills", "post"): (
            "202",
            "QueuedThsOperationResponse",
        ),
        ("/api/market-environment/ths/member-facts/imports", "post"): (
            "202",
            "QueuedThsOperationResponse",
        ),
        ("/api/preferences/timezone", "get"): ("200", "TimezonePreferencesResponse"),
        ("/api/preferences/timezone", "put"): ("200", "TimezonePreferencesResponse"),
        ("/api/v2/market-environment/operations/{run_id}", "get"): ("200", "V2Envelope_dict_str__Any__"),
        ("/api/v2/market-environment/operations/{run_id}/checkpoints", "get"): ("200", "V2PaginatedEnvelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/overview", "get"): ("200", "V2Envelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/indices", "get"): ("200", "V2Envelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/indices/{code}", "get"): ("200", "V2Envelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/indices/{code}/history", "get"): ("200", "V2PaginatedEnvelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/breadth", "get"): ("200", "V2Envelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/breadth/history", "get"): ("200", "V2PaginatedEnvelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/limits", "get"): ("200", "V2Envelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/limits/pools/{pool_type}", "get"): ("200", "V2PaginatedEnvelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/limits/history", "get"): ("200", "V2PaginatedEnvelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/limits/evidence", "get"): ("200", "V2Envelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/sectors/rankings", "get"): ("200", "V2PaginatedEnvelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/sectors/turnover", "get"): ("200", "V2PaginatedEnvelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/sectors/breadth", "get"): ("200", "V2PaginatedEnvelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/sectors/analysis", "get"): ("200", "V2Envelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/active-direction", "get"): ("200", "V2PaginatedEnvelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/events", "get"): ("200", "V2PaginatedEnvelope_dict_str__Any__"),
        ("/api/v2/market-environment/{as_of}/assessment", "get"): ("200", "V2Envelope_dict_str__Any__"),
    }

    assert {
        (path, method)
        for path, methods in schema.items()
        for method in methods
        if path.startswith("/api/")
    } == set(expected)
    for (path, method), (status_code, model) in expected.items():
        operation = schema[path][method]
        assert status_code in operation["responses"]
        response_schema = operation["responses"][status_code].get("content", {}).get(
            "application/json", {}
        ).get("schema", {})
        if model is not None:
            assert response_schema["$ref"] == f"#/components/schemas/{model}"


def test_api_entrypoint_has_no_mutable_runtime_singletons() -> None:
    from src.market_environment import api

    assert api.app is not None
    assert not hasattr(api, "service")
    assert not hasattr(api, "collection_coordinator")
    assert not hasattr(api, "collection_executor")
    assert not hasattr(api, "timezone_preference_store")


def test_api_rejects_invalid_and_future_dates() -> None:
    client = TestClient(
        build_test_app(
            market_queries=StubService(),
            effective_date=date.today(),
        )
    )
    assert client.get("/api/market-environment?as_of=not-a-date").status_code == 422
    future = date.today().replace(year=date.today().year + 1).isoformat()
    assert client.get(f"/api/market-environment?as_of={future}").status_code == 422


def test_api_returns_503_for_provider_failure(monkeypatch) -> None:
    response = TestClient(
        build_test_app(
            market_queries=StubService(RuntimeError("全部指数数据源不可用")),
            effective_date=date(2026, 9, 14),
        )
    ).get("/api/market-environment?as_of=2026-08-28")
    assert response.status_code == 503
    assert "全部指数数据源不可用" in response.json()["detail"]


def test_api_returns_schema_payload(monkeypatch) -> None:
    response = TestClient(
        build_test_app(
            market_queries=StubService(),
            effective_date=date(2026, 9, 14),
        )
    ).get("/api/market-environment?as_of=2026-08-28")
    assert response.status_code == 200
    assert response.json()["asOf"] == "2026-08-28"


def test_api_omitted_date_is_resolved_at_request_time(monkeypatch) -> None:
    """The default date must follow the Shanghai pre-open effective day."""

    response = TestClient(
        build_test_app(
            market_queries=StubService(),
            effective_date=date(2026, 9, 14),
        )
    ).get("/api/market-environment")

    assert response.status_code == 200
    assert response.json()["asOf"] == "2026-09-14"


def test_api_exposes_core_and_section_endpoints(monkeypatch) -> None:
    service = StubService()
    client = TestClient(
        build_test_app(
            market_queries=service,
            effective_date=date(2026, 9, 14),
        )
    )

    core = client.get("/api/market-environment/core?as_of=2026-08-28")
    chapter = client.get("/api/market-environment/chapter-01?as_of=2026-08-28&section=breadth")

    assert core.status_code == 200
    assert chapter.status_code == 200
    assert chapter.json()["chapter01"]["breadth"]["quality"]["status"] == "missing"
    assert service.calls == [("core", None), ("chapter01", "breadth")]


def test_chapter_api_normalizes_ths_revision_and_typed_diagnostics_locally() -> None:
    class DiagnosticChapterService(StubService):
        def get_chapter01(self, as_of: date, section: str):
            payload = super().get_chapter01(as_of, section)
            diagnostic = encode_ths_diagnostic(
                ThsDiagnostic(
                    reason_code="THS_LIVE_VALUES_MISSING",
                    message="一个目录编号缺少当日行情",
                    failure_stage="snapshot-value-classification",
                    exact_date=as_of,
                    retryable=True,
                    catalog_revision_id="catalog-r8",
                    expected_count=2,
                    rankable_count=1,
                    missing_live_count=1,
                    missing_live_codes=("883422.TI",),
                )
            )
            ranking = payload["chapter01"]["industryRanking"]
            ranking.update(
                {
                    "state": "partial",
                    "catalogRevision": "catalog-r8",
                    "rows": [
                        {
                            "tag": "industry",
                            "rank": 2,
                            "thscode": "883422.TI",
                            "name": "空行情样本",
                            "changePct": None,
                            "volume": None,
                            "turnover": None,
                            "catalogRevision": "catalog-r8",
                            "asOf": as_of.isoformat(),
                            "quality": "insufficient",
                            "warnings": ["当日市场字段全部缺失"],
                        }
                    ],
                }
            )
            ranking["quality"].update(
                {
                    "status": "partial",
                    "observations": 2,
                    "warning": diagnostic,
                    "warnings": [diagnostic],
                    "catalogRevision": "catalog-r8",
                    "expectedCodes": 2,
                    "rankableCount": 1,
                    "missingLiveCount": 1,
                    "missingLiveCodes": ["883422.TI"],
                }
            )
            return payload

    service = DiagnosticChapterService()
    response = TestClient(
        build_test_app(
            market_queries=service,
            effective_date=date(2026, 9, 14),
        )
    ).get("/api/market-environment/chapter-01?as_of=2026-08-28&section=sectors")

    assert response.status_code == 200
    ranking = response.json()["chapter01"]["industryRanking"]
    assert ranking["catalogRevisionId"] == "catalog-r8"
    assert "catalogRevision" not in ranking
    assert ranking["quality"]["catalogRevisionId"] == "catalog-r8"
    assert ranking["quality"]["expectedCount"] == 2
    assert ranking["quality"]["warning"] == "一个目录编号缺少当日行情"
    assert ranking["diagnostics"]["reasonCode"] == "THS_LIVE_VALUES_MISSING"
    assert ranking["rows"][0]["catalogRevisionId"] == "catalog-r8"
    assert "catalogRevision" not in ranking["rows"][0]
    assert service.calls == [("chapter01", "sectors")]


def test_api_exposes_provider_free_next_session_endpoint(monkeypatch) -> None:
    service = StubService()
    response = TestClient(
        build_test_app(
            market_queries=service,
            effective_date=date(2026, 9, 14),
        )
    ).get("/api/market-environment/next-session?as_of=2026-08-28")

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient"
    assert response.json()["nextAsOf"] is None
    assert service.calls == [("next-session", None)]


def test_api_rejects_unknown_chapter_section(monkeypatch) -> None:
    service = StubService()
    response = TestClient(
        build_test_app(
            market_queries=service,
            effective_date=date(2026, 9, 14),
        )
    ).get(
        "/api/market-environment/chapter-01?as_of=2026-08-28&section=unknown"
    )

    assert response.status_code == 422
    assert service.calls == []


class ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)


class NoopExecutor:
    def submit(self, function, *args):
        return None


def collection_coordinator(tmp_path, provider=None) -> CollectionCoordinator:
    market_now = datetime.combine(AS_OF, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
    return CollectionCoordinator(
        provider or CollectionProvider(),
        SnapshotStore(tmp_path / "snapshots.sqlite3"),
        now=lambda: market_now,
    )


def test_collection_post_can_be_explicitly_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "0")
    coordinator = collection_coordinator(tmp_path)

    response = TestClient(
        build_test_app(
            collection_queries=coordinator,
            collection_commands=FakeCollectionCommands(coordinator, NoopExecutor()),
            effective_date=AS_OF,
        )
    ).post(
        "/api/market-environment/collection-runs",
        json={"asOf": AS_OF.isoformat(), "datasets": ["breadth"]},
    )

    assert response.status_code == 403


def test_collection_status_is_provider_free_and_reports_exact_date(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", raising=False)
    provider = CollectionProvider()
    coordinator = collection_coordinator(tmp_path, provider)
    coordinator.collect(AS_OF, ["breadth"])
    provider.calls.clear()

    response = TestClient(
        build_test_app(
            collection_queries=coordinator,
            effective_date=AS_OF,
        )
    ).get(
        f"/api/market-environment/data-collection?as_of={AS_OF.isoformat()}"
    )

    assert response.status_code == 200
    assert response.json()["manualRefreshEnabled"] is True
    assert provider.calls == []
    rows = {item["dataset"]: item for item in response.json()["datasets"]}
    assert rows["breadth"]["available"] is True
    assert rows["core"]["available"] is False


def test_collection_status_does_not_project_legacy_sectors_evidence(monkeypatch, tmp_path) -> None:
    provider = CollectionProvider()
    coordinator = collection_coordinator(tmp_path, provider)
    enrichment = {
        "status": "partial",
        "source": "eastmoney-dataapi",
        "provider": "eastmoney",
        "sameVendor": True,
        "matchedRows": 1,
        "unmatchedRows": 2,
        "identityCoverage": 0.3333,
        "warnings": ["fixture supplemental lineage"],
    }
    coordinator.store.put(
        SnapshotRecord(
            dataset="sectors",
            as_of=AS_OF,
            payload={
                "rows": [],
                "state": "当日排名已观测",
                "quality": {
                    "dataset": "industry-ranking",
                    "source": "fuyao",
                    "provider": "fuyao",
                    "status": "fallback",
                    "observations": 0,
                    "asOf": AS_OF.isoformat(),
                    "warnings": [],
                    "sectorEnrichment": enrichment,
                },
            },
            source="fuyao",
            status="fallback",
            observations=0,
            warnings=(),
            fetched_at=datetime(2026, 9, 3, 16, tzinfo=MARKET_TIME_ZONE),
            settled=True,
        )
    )
    response = TestClient(
        build_test_app(
            collection_queries=coordinator,
            effective_date=AS_OF,
        )
    ).get(
        f"/api/market-environment/data-collection?as_of={AS_OF.isoformat()}"
    )

    assert response.status_code == 200
    rows = {item["dataset"]: item for item in response.json()["datasets"]}
    assert tuple(rows) == DATASET_IDS
    assert "sectors" not in rows
    assert all(
        rows[dataset]["available"] is False
        for dataset in ("industry-ranking", "sector-turnover", "sector-breadth")
    )
    legacy = coordinator.store.get("sectors", AS_OF)
    assert legacy is not None
    assert legacy.payload["quality"]["sectorEnrichment"] == enrichment
    assert provider.calls == []


def test_collection_status_exposes_attempt_timings(monkeypatch, tmp_path) -> None:
    coordinator = collection_coordinator(tmp_path)
    result = coordinator.collect(AS_OF, ["breadth"])
    task = result.tasks[0]
    coordinator.store.transition_collection_task(
        task.task_id,
        task.status,
        expected_statuses=(task.status,),
        timings={"shadow": {"status": "match"}, "providerCollectionMs": 1.25},
    )
    response = TestClient(
        build_test_app(
            collection_queries=coordinator,
            effective_date=AS_OF,
        )
    ).get(
        f"/api/market-environment/data-collection?as_of={AS_OF.isoformat()}"
    )

    assert response.status_code == 200
    breadth = next(item for item in response.json()["datasets"] if item["dataset"] == "breadth")
    assert breadth["latestAttempt"]["timings"] == {
        "shadow": {"status": "match"},
        "providerCollectionMs": 1.25,
    }


def test_collection_status_decodes_local_ths_diagnostic_without_provider_call(
    monkeypatch, tmp_path
) -> None:
    provider = CollectionProvider()
    coordinator = collection_coordinator(tmp_path, provider)
    result = coordinator.collect(AS_OF, ["industry-ranking"])
    task = result.tasks[0]
    warning = encode_ths_diagnostic(
        ThsDiagnostic(
            reason_code="THS_LIVE_VALUES_MISSING",
            message="2 个目录编号缺少当日行情",
            failure_stage="snapshot-value-classification",
            exact_date=AS_OF,
            retryable=True,
            catalog_revision_id="catalog-r8",
            expected_count=846,
            rankable_count=844,
            missing_live_count=2,
            missing_live_codes=("883999.TI", "883422.TI"),
        )
    )
    coordinator.store.transition_collection_task(
        task.task_id,
        task.status,
        expected_statuses=(task.status,),
        warning=warning,
        timings={"catalogRevision": "catalog-r8"},
    )
    provider.calls.clear()

    response = TestClient(
        build_test_app(collection_queries=coordinator, effective_date=AS_OF)
    ).get(f"/api/market-environment/data-collection?as_of={AS_OF.isoformat()}")

    assert response.status_code == 200
    row = next(
        item
        for item in response.json()["datasets"]
        if item["dataset"] == "industry-ranking"
    )
    attempt = row["latestAttempt"]
    assert attempt["warning"] == "2 个目录编号缺少当日行情"
    assert attempt["catalogRevisionId"] == "catalog-r8"
    assert attempt["timings"]["catalogRevisionId"] == "catalog-r8"
    assert "catalogRevision" not in attempt["timings"]
    assert attempt["diagnostics"]["reasonCode"] == "THS_LIVE_VALUES_MISSING"
    assert attempt["diagnostics"]["missingLiveCodes"] == [
        "883422.TI",
        "883999.TI",
    ]
    assert provider.calls == []


def test_collection_status_exposes_derived_quality_from_local_snapshot(monkeypatch, tmp_path) -> None:
    coordinator = collection_coordinator(tmp_path)
    coordinator.store.put(
        SnapshotRecord(
            dataset="activeDirection",
            as_of=AS_OF,
            payload={
                "state": "unverified",
                "summary": "derived fixture",
                "topStocks": [],
                "quality": {
                    "source": "tdx-daily-package-derived",
                    "status": "fallback-derived",
                    "rankingMethod": "local-turnover-desc-identity-asc",
                    "industryMappingCoverage": 0.5,
                },
            },
            source="tdx-daily-package-derived",
            status="fallback-derived",
            observations=30,
            warnings=("fixture warning",),
            fetched_at=datetime(2026, 9, 3, 16, tzinfo=MARKET_TIME_ZONE),
            settled=True,
        )
    )
    response = TestClient(
        build_test_app(
            collection_queries=coordinator,
            effective_date=AS_OF,
        )
    ).get(
        f"/api/market-environment/data-collection?as_of={AS_OF.isoformat()}"
    )

    assert response.status_code == 200
    active = next(item for item in response.json()["datasets"] if item["dataset"] == "activeDirection")
    assert active["source"] == "tdx-daily-package-derived"
    assert active["quality"]["rankingMethod"] == "local-turnover-desc-identity-asc"
    assert active["quality"]["industryMappingCoverage"] == 0.5


def test_collection_single_run_is_enabled_by_default_and_can_be_polled(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", raising=False)
    coordinator = collection_coordinator(tmp_path)
    client = TestClient(
        build_test_app(
            collection_queries=coordinator,
            collection_commands=FakeCollectionCommands(coordinator, ImmediateExecutor()),
            effective_date=AS_OF,
        )
    )

    started = client.post(
        "/api/market-environment/collection-runs",
        json={"asOf": AS_OF.isoformat(), "datasets": ["breadth"]},
    )
    polled = client.get(
        f"/api/market-environment/collection-runs/{started.json()['runId']}"
    )

    assert started.status_code == 202
    assert started.json()["requestedDatasets"] == ["breadth"]
    assert polled.status_code == 200
    assert polled.json()["status"] == "success"
    assert polled.json()["completedTasks"] == 1


def test_collection_task_timings_accept_ths_revision_metadata() -> None:
    response = CollectionTaskResponse(
        taskId="task-1",
        dataset="industry-ranking",
        asOf=AS_OF,
        status="partial",
        source="fuyao-ths",
        observations=10,
        warning="snapshot coverage incomplete",
        timings={
            "providerCollectionMs": 12.5,
            "sourceRevision": "fuyao-ths-catalog-v1",
            "capabilityRevision": "fuyao-ths-catalog-v1",
            "catalogRevision": "catalog-fixture-r1",
            "requestBudget": 12,
        },
        queuedAt=None,
        startedAt=None,
        completedAt=None,
        durationMs=12.5,
        settled=False,
    )

    assert response.timings["providerCollectionMs"] == 12.5
    assert response.timings["sourceRevision"] == "fuyao-ths-catalog-v1"
    assert response.timings["catalogRevision"] == "catalog-fixture-r1"
    assert response.timings["requestBudget"] == 12


def test_ths_quality_bounds_missing_samples_without_truncating_total_count() -> None:
    codes = [f"{index:06d}.TI" for index in range(25)]

    quality = EvidenceQuality.model_validate(
        {
            "dataset": "industry-ranking",
            "source": "fuyao-ths",
            "provider": "fuyao",
            "status": "partial",
            "observations": 25,
            "warnings": [],
            "catalogRevision": "catalog-r8",
            "expectedCodes": 846,
            "observedCodes": 846,
            "rankableCodes": 821,
            "barCodes": 821,
            "missingLiveCodes": list(reversed(codes)),
        }
    ).model_dump()

    assert quality["catalogRevisionId"] == "catalog-r8"
    assert quality["expectedCount"] == 846
    assert quality["observedCount"] == 846
    assert quality["rankableCount"] == 821
    assert quality["barCount"] == 821
    assert quality["missingLiveCount"] == 25
    assert quality["missingLiveCodes"] == codes[:20]


def test_collection_full_run_reports_partial_and_keeps_successes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "true")
    coordinator = collection_coordinator(tmp_path)
    client = TestClient(
        build_test_app(
            collection_queries=coordinator,
            collection_commands=FakeCollectionCommands(coordinator, ImmediateExecutor()),
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

    tasks = {item["dataset"]: item for item in polled.json()["tasks"]}
    assert polled.json()["status"] == "partial"
    assert set(tasks) == set(DATASET_IDS)
    assert "sectors" not in tasks
    assert tasks["industry-ranking"]["status"] == "failed-missing"
    assert tasks["sector-turnover"]["status"] == "blocked"
    assert tasks["sector-breadth"]["status"] == "blocked"
    assert tasks["breadth"]["status"] == "success"


def test_collection_duplicate_post_reports_busy_without_provider_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1")
    provider = CollectionProvider()
    coordinator = collection_coordinator(tmp_path, provider)
    client = TestClient(
        build_test_app(
            collection_queries=coordinator,
            collection_commands=FakeCollectionCommands(coordinator, NoopExecutor()),
            effective_date=AS_OF,
        )
    )
    request = {"asOf": AS_OF.isoformat(), "datasets": ["breadth"]}

    first = client.post("/api/market-environment/collection-runs", json=request)
    second = client.post("/api/market-environment/collection-runs", json=request)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["tasks"][0]["status"] == "busy"
    assert provider.calls == []


def test_collection_rejects_historical_latest_only_dataset(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1")
    coordinator = collection_coordinator(tmp_path)

    response = TestClient(
        build_test_app(
            collection_queries=coordinator,
            collection_commands=FakeCollectionCommands(coordinator, NoopExecutor()),
            effective_date=AS_OF,
        )
    ).post(
        "/api/market-environment/collection-runs",
        json={
            "asOf": (AS_OF - timedelta(days=1)).isoformat(),
            "datasets": ["breadth"],
        },
    )

    assert response.status_code == 422
    assert "latest-only" in response.json()["detail"]


def test_collection_poll_recovers_task_after_expired_lease(monkeypatch, tmp_path) -> None:
    coordinator = collection_coordinator(tmp_path)
    started = coordinator.start_run(AS_OF, ["breadth"])
    task = started.tasks[0]
    coordinator.store.release_lease("breadth", AS_OF, task.task_id)

    response = TestClient(
        build_test_app(
            collection_queries=coordinator,
            effective_date=AS_OF,
        )
    ).get(
        f"/api/market-environment/collection-runs/{started.run.run_id}"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["tasks"][0]["status"] == "failed-missing"
