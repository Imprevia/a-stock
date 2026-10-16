import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pytest

from src.market_environment.application.collection import (
    DatasetCollectorRegistry,
    DatasetCommitterRegistry,
)
from src.market_environment.application.ports import DatasetCommitEvidence
from src.market_environment.calculations import Bar
from src.market_environment.cli import main as cli_main
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    CollectionCandidate,
    CollectionFailureCategory,
    CollectionOutcome,
    CollectionTaskState,
    DATASET_IDS,
    DatasetDate,
)
from src.market_environment.fuyao_config import FuyaoCollectionConfig
from src.market_environment.providers import INDEX_SPECS, MarketDataProvider, ProviderResult
from src.market_environment.refresh import MARKET_TIME_ZONE, effective_market_date
from src.market_environment.snapshot_store import (
    CollectionTaskRecord,
    SnapshotIntegrityError,
    SnapshotRecord,
    SnapshotStore,
)


AS_OF = date(2026, 9, 3)
AFTER_MARKET = datetime(2026, 9, 3, 15, 20, tzinfo=MARKET_TIME_ZONE)


def test_collection_rejects_current_calendar_date_before_open_and_accepts_previous_session(tmp_path) -> None:
    pre_open = datetime(2026, 9, 15, 9, 0, tzinfo=MARKET_TIME_ZONE)
    provider = CollectionProvider()
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    coordinator = CollectionCoordinator(provider, store, now=lambda: pre_open)

    assert effective_market_date(pre_open) == date(2026, 9, 14)
    with pytest.raises(ValueError, match="collection date cannot be later"):
        coordinator.start_run(date(2026, 9, 15), ["breadth"])

    result = coordinator.collect(date(2026, 9, 14), ["breadth"])
    assert result.run.status == "success"
    assert store.get("breadth", date(2026, 9, 14)) is not None
    assert store.get("breadth", date(2026, 9, 15)) is None


def test_integrity_exception_is_persisted_as_terminal_failure(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "integrity-task.sqlite3")
    store.create_collection_run("run-integrity", AS_OF, ("core",), created_at=AFTER_MARKET)
    task = store.create_collection_task(
        "task-integrity",
        "run-integrity",
        "core",
        AS_OF,
        queued_at=AFTER_MARKET,
    )
    task = store.transition_collection_task(
        task.task_id,
        "collecting",
        expected_statuses=("queued",),
        started_at=AFTER_MARKET,
    )
    coordinator = CollectionCoordinator(CollectionProvider(), store, now=lambda: AFTER_MARKET)

    result = coordinator._integrity_task_result(
        task,
        SnapshotIntegrityError("snapshot exact-date mismatch: core/2026-09-03"),
        0.0,
    )

    assert result.status == "failed-retained"
    assert result.failure is not None
    assert result.failure.code == "SNAPSHOT_INTEGRITY_ERROR"
    assert store.get_collection_task(task.task_id).status == "failed-retained"
    assert store.get_collection_run("run-integrity").status == "failed"


def quality(dataset: str, as_of: date, status: str = "ok") -> dict:
    return {
        "dataset": dataset,
        "source": "fixture",
        "provider": "fixture",
        "status": status,
        "observations": 3,
        "asOf": as_of.isoformat(),
        "warning": None if status == "ok" else "fixture warning",
        "warnings": [] if status == "ok" else ["fixture warning"],
    }


def chapter_payload(dataset: str, as_of: date) -> dict:
    if dataset == "breadth":
        return {
            "advanceCount": 2,
            "declineCount": 1,
            "flatCount": 0,
            "validCount": 3,
            "advanceRatio": 0.6667,
            "medianReturn": 1.0,
            "state": "多数上涨",
            "quality": quality("market-breadth", as_of),
        }
    if dataset == "limits":
        return {
            "limitUpCount": 10,
            "limitDownCount": 2,
            "failedLimitUpCount": 3,
            "failedLimitUpRatio": 0.23,
            "maxStreak": 4,
            "state": "已观测",
            "quality": quality("limit-pools", as_of),
        }
    if dataset == "sectors":
        return {"rows": [], "state": "已观测", "quality": quality("industry-ranking", as_of)}
    return {
        "state": "candidate",
        "summary": "fixture",
        "topStocks": [],
        "quality": quality("active-direction", as_of),
    }


class CollectionProvider:
    def __init__(self, *, failing_datasets: set[str] | None = None, failing_indices: set[str] | None = None):
        self.failing_datasets = failing_datasets or set()
        self.failing_indices = failing_indices or set()
        self.calls: list[str] = []

    def fetch_quotes(self, specs):
        return {}

    def fetch(self, spec, limit=160, expected_price=None, quote=None):
        self.calls.append(spec.code)
        if spec.code in self.failing_indices:
            raise RuntimeError(f"{spec.code} unavailable")
        bars = []
        for offset in range(80):
            current = AS_OF - timedelta(days=79 - offset)
            close = 3000 + offset
            bars.append(
                Bar(
                    date=current,
                    open=close - 1,
                    high=close + 2,
                    low=close - 2,
                    close=close,
                    amount=1000000 + offset,
                )
            )
        return ProviderResult(bars=bars, source="fixture")

    def _chapter(self, dataset: str, as_of: date) -> dict:
        self.calls.append(dataset)
        if dataset in self.failing_datasets:
            raise RuntimeError(f"{dataset} unavailable")
        return chapter_payload(dataset, as_of)

    def fetch_chapter01_breadth(self, as_of, *, allow_current_snapshot):
        return self._chapter("breadth", as_of)

    def fetch_chapter01_limits(self, as_of):
        return self._chapter("limits", as_of)

    def fetch_chapter01_sectors(self, as_of, *, allow_current_snapshot):
        return self._chapter("sectors", as_of)

    def fetch_chapter01_active_direction(self, as_of, *, allow_current_snapshot):
        return self._chapter("activeDirection", as_of)


class QuoteAwareProvider(CollectionProvider):
    def __init__(self):
        super().__init__()
        self.quote_calls = []

    def fetch_quotes(self, specs):
        self.quote_calls.append(tuple(spec.code for spec in specs))
        return {spec.code: {"price": 3000.0} for spec in specs}


class QuoteAwareCoreAdapter:
    def __init__(self):
        self.calls = []

    def fetch_core(self, as_of, *, quotes_by_code=None):
        self.calls.append((as_of, quotes_by_code))
        # Return no shadow rows; the established provider supplies the formal
        # result while this test verifies the Fuyao call contract and routing.
        return {}


class ForbiddenActiveDirectionAdapter:
    def fetch_active_direction(self, as_of):
        raise AssertionError("activeDirection must stay on the Eastmoney/TDX chain")


@dataclass
class ClaimedRunStore:
    """Model the PostgreSQL idempotency guard for queued claimed tasks."""

    delegate: SnapshotStore

    def expire_inactive_collection_tasks(self, *, now=None) -> int:
        del now
        return 0

    def __getattr__(self, name):
        return getattr(self.delegate, name)


@dataclass(frozen=True)
class RejectingFuyaoPolicy:
    rejected: frozenset[str]

    def preflight_error(self, dataset: str) -> str | None:
        if dataset in self.rejected:
            return f"{dataset} Fuyao configuration is unavailable"
        return None


@dataclass
class FixtureDatasetCollector:
    dataset_id: str
    failing_datasets: frozenset[str] = frozenset()
    calls: list[DatasetDate] = field(default_factory=list)

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        self.calls.append(identity)
        if identity.dataset in self.failing_datasets:
            return CollectionOutcome(
                identity,
                CollectionTaskState.FAILED_MISSING,
                warning=f"{identity.dataset} unavailable",
                failure=AcquisitionFailure(
                    category=AcquisitionFailureCategory.NETWORK,
                    message=f"{identity.dataset} unavailable",
                    retryable=True,
                    source="fixture-provider",
                ),
            )
        payload = {
            "asOf": identity.as_of.isoformat(),
            "quality": quality(identity.dataset, identity.as_of),
        }
        if identity.dataset == "core":
            payload["indices"] = [
                {
                    "code": "sh000001",
                    "history": [
                        {"date": identity.as_of.isoformat(), "close": 3200}
                    ],
                }
            ]
        candidate = CollectionCandidate(
            identity=identity,
            payload=payload,
            source="fixture",
            status="ok",
            observations=1,
            warnings=(),
            settled=True,
            actual_as_of=identity.as_of,
            fetched_at=AFTER_MARKET,
        )
        return CollectionOutcome(
            identity,
            CollectionTaskState.SUCCESS,
            candidate=candidate,
        )


@dataclass
class FixtureDatasetCommitter:
    dataset_id: str
    store: SnapshotStore

    def commit(self, request) -> DatasetCommitEvidence:
        candidate = request.candidate
        self.store.put(
            SnapshotRecord(
                dataset=candidate.identity.dataset,
                as_of=candidate.identity.as_of,
                payload=dict(candidate.payload),
                source=candidate.source,
                status=candidate.status,
                observations=candidate.observations,
                warnings=candidate.warnings,
                fetched_at=candidate.fetched_at or AFTER_MARKET,
                settled=candidate.settled,
            ),
            lease=request.lease,
            now=AFTER_MARKET,
        )
        return DatasetCommitEvidence(
            identity=request.identity,
            outcome_state=request.outcome.state,
            candidate=candidate,
            writes=("snapshot",),
        )


def fixture_dataset_coordinator(
    store: SnapshotStore,
    *,
    failing_datasets: frozenset[str] = frozenset(),
    rebuild_aggregate=None,
) -> tuple[CollectionCoordinator, tuple[FixtureDatasetCollector, ...]]:
    collectors = tuple(
        FixtureDatasetCollector(dataset, failing_datasets) for dataset in DATASET_IDS
    )
    committers = tuple(FixtureDatasetCommitter(dataset, store) for dataset in DATASET_IDS)
    return (
        CollectionCoordinator(
            None,
            store,
            now=lambda: AFTER_MARKET,
            rebuild_aggregate=rebuild_aggregate,
            collector_registry=DatasetCollectorRegistry.complete(collectors),
            committer_registry=DatasetCommitterRegistry.complete(committers),
            typed_cutover_datasets=DATASET_IDS,
        ),
        collectors,
    )


def claimed_run_coordinator(
    store: SnapshotStore,
    *,
    fuyao_policy=None,
) -> CollectionCoordinator:
    collectors = tuple(FixtureDatasetCollector(dataset) for dataset in DATASET_IDS)
    return CollectionCoordinator(
        None,
        ClaimedRunStore(store),
        now=lambda: AFTER_MARKET,
        collector_registry=DatasetCollectorRegistry.complete(collectors),
        fuyao_policy=fuyao_policy,
    )


def seed_claimed_run(
    store: SnapshotStore,
    run_id: str,
    datasets: tuple[str, ...],
) -> dict[str, str]:
    store.create_collection_run(run_id, AS_OF, datasets, created_at=AFTER_MARKET)
    task_ids = {dataset: f"{run_id}-{dataset}" for dataset in datasets}
    for dataset, task_id in task_ids.items():
        store.create_collection_task(
            task_id,
            run_id,
            dataset,
            AS_OF,
            queued_at=AFTER_MARKET,
        )
    return task_ids


def test_prepare_run_submission_reacquires_expired_owned_lease_with_new_generation(
    tmp_path,
) -> None:
    store = SnapshotStore(tmp_path / "prepare-expired-lease.sqlite3")
    task_id = seed_claimed_run(store, "claimed-expired", ("breadth",))["breadth"]
    expired = store.acquire_lease(
        "breadth",
        AS_OF,
        task_id,
        lease_seconds=30,
        now=AFTER_MARKET - timedelta(minutes=5),
    )
    assert expired is not None and expired.expires_at < AFTER_MARKET
    coordinator = claimed_run_coordinator(store)

    tasks = coordinator.prepare_run_submission(
        "claimed-expired",
        lease_seconds=600,
    )

    renewed = store.get_lease_token("breadth", AS_OF, owner=task_id)
    assert tasks[0].status == "queued"
    assert renewed is not None
    assert renewed.owner == task_id
    assert renewed.generation > expired.generation
    assert renewed.token != expired.token
    assert renewed.expires_at > AFTER_MARKET


def test_prepare_run_submission_persists_fuyao_preflight_failures_without_leases(
    tmp_path,
) -> None:
    store = SnapshotStore(tmp_path / "prepare-preflight.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=AS_OF,
            payload=chapter_payload("breadth", AS_OF),
            source="retained",
            status="ok",
            observations=3,
            warnings=(),
            fetched_at=AFTER_MARKET - timedelta(minutes=5),
            settled=True,
        )
    )
    task_ids = seed_claimed_run(
        store,
        "claimed-preflight",
        ("core", "breadth"),
    )
    coordinator = claimed_run_coordinator(
        store,
        fuyao_policy=RejectingFuyaoPolicy(frozenset({"core", "breadth"})),
    )

    tasks = {
        task.dataset: task
        for task in coordinator.prepare_run_submission(
            "claimed-preflight",
            lease_seconds=600,
        )
    }

    assert tasks["core"].status == "failed-missing"
    assert tasks["breadth"].status == "failed-retained"
    for dataset, retained in (("core", False), ("breadth", True)):
        failure = tasks[dataset].failure
        assert failure is not None
        assert failure.category is CollectionFailureCategory.CONFIGURATION
        assert failure.retryable is False
        assert failure.retained is retained
        assert failure.stage == "preflight"
        assert failure.code == "FUYAO_PREFLIGHT_REJECTED"
        assert store.get_lease_token(
            dataset,
            AS_OF,
            owner=task_ids[dataset],
        ) is None


def test_execute_run_recovers_interrupted_task_and_waits_for_all_tasks_to_finish(
    tmp_path,
) -> None:
    store = SnapshotStore(tmp_path / "execute-recovery.sqlite3")
    run_id = "recover-run"
    store.create_collection_run(
        run_id,
        AS_OF,
        ("core", "breadth"),
        created_at=AFTER_MARKET - timedelta(minutes=10),
    )
    store.update_collection_run(
        run_id,
        "collecting",
        started_at=AFTER_MARKET - timedelta(minutes=10),
    )
    for dataset in ("core", "breadth"):
        store.create_collection_task(
            f"recover-{dataset}",
            run_id,
            dataset,
            AS_OF,
            queued_at=AFTER_MARKET - timedelta(minutes=10),
        )
        store.transition_collection_task(
            f"recover-{dataset}",
            "collecting",
            expected_statuses=("queued",),
            started_at=AFTER_MARKET - timedelta(minutes=10),
        )
    active_lease = store.acquire_lease(
        "breadth",
        AS_OF,
        "recover-breadth",
        lease_seconds=600,
        now=AFTER_MARKET,
    )
    assert active_lease is not None
    coordinator, _ = fixture_dataset_coordinator(store)

    still_collecting = coordinator.execute_run(run_id)
    recovered = store.get_collection_task("recover-core")

    assert recovered is not None
    assert recovered.status == "failed-missing"
    assert recovered.failure is not None
    assert (
        recovered.failure.category
        is CollectionFailureCategory.WORKER_INTERRUPTED
    )
    assert still_collecting.status == "collecting"
    assert still_collecting.completed_at is None

    store.transition_collection_task(
        "recover-breadth",
        "success",
        expected_statuses=("collecting",),
        source="fixture",
        observations=1,
        completed_at=AFTER_MARKET,
    )
    terminal = coordinator.execute_run(run_id)

    assert terminal.status == "partial"
    assert terminal.completed_at == AFTER_MARKET


def test_full_collection_continues_after_dataset_failure(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    rebuilt: list[date] = []
    coordinator, collectors = fixture_dataset_coordinator(
        store,
        failing_datasets=frozenset({"sector-turnover"}),
        rebuild_aggregate=rebuilt.append,
    )
    result = coordinator.collect(AS_OF)

    tasks = {task.dataset: task for task in result.tasks}
    assert result.run.status == "partial"
    assert tasks["sector-turnover"].status == "failed-missing"
    assert tasks["sector-breadth"].status == "blocked"
    assert (
        tasks["sector-turnover"].failure.category
        is CollectionFailureCategory.NETWORK
    )
    assert tasks["sector-turnover"].failure.source == "fixture-provider"
    assert (
        tasks["sector-breadth"].failure.category
        is CollectionFailureCategory.DEPENDENCY
    )
    assert tasks["sector-breadth"].failure.blocked_by == ("sector-turnover",)
    assert all(
        tasks[name].status == "success"
        for name in ("core", "breadth", "limits", "industry-ranking", "activeDirection")
    )
    assert all(
        tasks[name].failure is None
        for name in ("core", "breadth", "limits", "industry-ranking", "activeDirection")
    )
    assert store.get("sector-turnover", AS_OF) is None
    assert store.get("sector-breadth", AS_OF) is None
    assert all(
        store.get(name, AS_OF) is not None
        for name in ("core", "breadth", "limits", "industry-ranking", "activeDirection")
    )
    calls = {collector.dataset_id: collector.calls for collector in collectors}
    assert calls["sector-turnover"] == [DatasetDate("sector-turnover", AS_OF)]
    assert calls["sector-breadth"] == []
    assert rebuilt == [AS_OF] * 5


def test_core_fuyao_receives_current_quote_but_history_is_quote_free(tmp_path) -> None:
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_CORE_SHADOW_ENABLED": "1",
        }
    )

    current_provider = QuoteAwareProvider()
    current_adapter = QuoteAwareCoreAdapter()
    current = CollectionCoordinator(
        current_provider,
        SnapshotStore(tmp_path / "current-core.sqlite3"),
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
        fuyao_config=config,
        fuyao_adapter=current_adapter,
    ).collect(AS_OF, ["core"])

    assert current.run.status == "success"
    assert current_provider.quote_calls == [tuple(spec.code for spec in INDEX_SPECS)]
    assert current_adapter.calls[0][0] == AS_OF
    assert set(current_adapter.calls[0][1]) == {spec.code for spec in INDEX_SPECS}

    historical_provider = QuoteAwareProvider()
    historical_adapter = QuoteAwareCoreAdapter()
    historical_date = AS_OF - timedelta(days=1)
    historical = CollectionCoordinator(
        historical_provider,
        SnapshotStore(tmp_path / "historical-core.sqlite3"),
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
        fuyao_config=config,
        fuyao_adapter=historical_adapter,
    ).collect(historical_date, ["core"])

    assert historical.run.status == "success"
    assert historical_provider.quote_calls == []
    assert historical_adapter.calls == [(historical_date, {})]


def test_active_direction_never_routes_through_fuyao_even_when_flag_is_enabled(tmp_path) -> None:
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_ACTIVE_DIRECTION_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_ACTIVE_DIRECTION_APPROVED_REVISION": "legacy-r1",
        }
    )
    provider = CollectionProvider()
    result = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "active-direction.sqlite3"),
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
        fuyao_config=config,
        fuyao_adapter=ForbiddenActiveDirectionAdapter(),
    ).collect(AS_OF, ["activeDirection"])

    assert result.run.status == "success"
    assert result.tasks[0].source == "fixture"
    assert provider.calls == ["activeDirection"]


def test_retired_sectors_request_preserves_same_date_legacy_evidence(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="sectors",
            as_of=AS_OF,
            payload=chapter_payload("sectors", AS_OF),
            source="old",
            status="ok",
            observations=3,
            warnings=(),
            fetched_at=AFTER_MARKET - timedelta(days=1),
            settled=True,
        )
    )
    before = store.get("sectors", AS_OF)
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(provider, store, now=lambda: AFTER_MARKET)

    with pytest.raises(
        ValueError,
        match="unsupported collection dataset: sectors; use industry-ranking, sector-turnover, or sector-breadth",
    ):
        coordinator.collect(AS_OF, ["sectors"])

    assert store.get("sectors", AS_OF) == before
    assert provider.calls == []


def test_retired_sectors_request_preserves_other_date_legacy_evidence(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    previous_date = AS_OF - timedelta(days=1)
    store.put(
        SnapshotRecord(
            dataset="sectors",
            as_of=previous_date,
            payload=chapter_payload("sectors", previous_date),
            source="old",
            status="ok",
            observations=3,
            warnings=(),
            fetched_at=AFTER_MARKET - timedelta(days=1),
            settled=True,
        )
    )
    before = store.get("sectors", previous_date)
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(provider, store, now=lambda: AFTER_MARKET)

    with pytest.raises(
        ValueError,
        match="unsupported collection dataset: sectors; use industry-ranking, sector-turnover, or sector-breadth",
    ):
        coordinator.collect(AS_OF, ["sectors"])

    assert store.get("sectors", AS_OF) is None
    assert store.get("sectors", previous_date) == before
    assert provider.calls == []


def test_failed_active_direction_fallback_retains_same_date_success(tmp_path, monkeypatch) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="activeDirection",
            as_of=AS_OF,
            payload=chapter_payload("activeDirection", AS_OF),
            source="old",
            status="partial",
            observations=3,
            warnings=(),
            fetched_at=AFTER_MARKET - timedelta(days=1),
            settled=True,
        )
    )
    provider = MarketDataProvider()
    calls = []

    def fail(url, _params):
        calls.append(url)
        if url == provider._STOCK_SNAPSHOT_URL:
            raise RuntimeError("primary disconnected")
        raise RuntimeError("delayed unavailable")

    monkeypatch.setattr(provider.eastmoney, "get_json", fail)
    result = CollectionCoordinator(provider, store, now=lambda: AFTER_MARKET).collect(AS_OF, ["activeDirection"])
    retained = store.get("activeDirection", AS_OF)

    assert calls == [provider._STOCK_SNAPSHOT_URL, provider._ACTIVE_DIRECTION_FALLBACK_URL]
    assert result.run.status == "failed"
    assert result.tasks[0].status == "failed-retained"
    assert result.tasks[0].failure.retained is True
    assert retained.source == "old"
    assert "主域失败：primary disconnected" in retained.refresh_warning
    assert "延迟域失败：delayed unavailable" in retained.refresh_warning


def test_failed_active_direction_fallback_does_not_retain_another_date(tmp_path, monkeypatch) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    previous_date = AS_OF - timedelta(days=1)
    store.put(
        SnapshotRecord(
            dataset="activeDirection",
            as_of=previous_date,
            payload=chapter_payload("activeDirection", previous_date),
            source="old",
            status="partial",
            observations=3,
            warnings=(),
            fetched_at=AFTER_MARKET - timedelta(days=1),
            settled=True,
        )
    )
    provider = MarketDataProvider()

    def fail(url, _params):
        if url == provider._STOCK_SNAPSHOT_URL:
            raise RuntimeError("primary disconnected")
        raise RuntimeError("delayed unavailable")

    monkeypatch.setattr(provider.eastmoney, "get_json", fail)
    result = CollectionCoordinator(provider, store, now=lambda: AFTER_MARKET).collect(AS_OF, ["activeDirection"])

    assert result.tasks[0].status == "failed-missing"
    assert result.tasks[0].failure.retained is False
    assert "主域失败：primary disconnected" in result.tasks[0].warning
    assert "延迟域失败：delayed unavailable" in result.tasks[0].warning
    assert store.get("activeDirection", AS_OF) is None
    assert store.get("activeDirection", previous_date).source == "old"


def test_duplicate_task_reuses_active_lease_without_provider_call(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(provider, store, now=lambda: AFTER_MARKET)
    first = coordinator.start_run(AS_OF, ["breadth"])
    second = coordinator.start_run(AS_OF, ["breadth"])

    assert first.tasks[0].status == "queued"
    assert second.tasks[0].status == "busy"
    assert (
        second.tasks[0].failure.category
        is CollectionFailureCategory.CONCURRENCY
    )
    coordinator.execute_run(second.run.run_id)
    assert provider.calls == []
    coordinator.execute_run(first.run.run_id)
    assert provider.calls == ["breadth"]


def test_core_index_failure_is_isolated_and_retained(tmp_path) -> None:
    failed_code = INDEX_SPECS[0].code
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    seed = CollectionCoordinator(CollectionProvider(), store, now=lambda: AFTER_MARKET).collect(AS_OF, ["core"])
    assert seed.run.status == "success"

    result = CollectionCoordinator(
        CollectionProvider(failing_indices={failed_code}),
        store,
        now=lambda: AFTER_MARKET,
    ).collect(AS_OF, ["core"])
    task = result.tasks[0]
    index_results = {item.code: item for item in store.list_core_index_results(task.task_id)}

    assert result.run.status == "partial"
    assert task.status == "partial"
    assert index_results[failed_code].status == "failed-retained"
    assert len(store.get("core", AS_OF).payload["indices"]) == len(INDEX_SPECS)


def test_all_core_failures_do_not_overwrite_retained_success(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    CollectionCoordinator(CollectionProvider(), store, now=lambda: AFTER_MARKET).collect(AS_OF, ["core"])
    retained = store.get("core", AS_OF)

    result = CollectionCoordinator(
        CollectionProvider(failing_indices={spec.code for spec in INDEX_SPECS}),
        store,
        now=lambda: AFTER_MARKET + timedelta(minutes=5),
    ).collect(AS_OF, ["core"])
    after_failure = store.get("core", AS_OF)

    assert result.run.status == "failed"
    assert result.tasks[0].status == "failed-retained"
    assert result.tasks[0].failure.retained is True
    assert after_failure.payload == retained.payload
    assert after_failure.fetched_at == retained.fetched_at
    assert "unavailable" in after_failure.refresh_warning


def test_latest_only_historical_collection_is_rejected_before_provider_calls(tmp_path) -> None:
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(provider, SnapshotStore(tmp_path / "snapshots.sqlite3"), now=lambda: AFTER_MARKET)

    with pytest.raises(ValueError, match="latest-only"):
        coordinator.start_run(AS_OF - timedelta(days=1), ["breadth"])

    historical = coordinator.collect(AS_OF - timedelta(days=1), ["limits"])
    assert historical.run.status == "success"
    assert historical.tasks[0].settled is True
    assert provider.calls == ["limits"]


def test_forced_cli_refresh_allows_historical_latest_only_exact_date(tmp_path, capsys) -> None:
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "snapshots.sqlite3"),
        now=lambda: AFTER_MARKET,
    )

    exit_code = cli_main(
        [
            "snapshots",
            "refresh",
            "--as-of",
            (AS_OF - timedelta(days=1)).isoformat(),
            "--dataset",
            "breadth",
            "--force",
        ],
        coordinator=coordinator,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["forced"] is True
    assert payload["status"] == "success"
    assert provider.calls == ["breadth"]
    assert coordinator.store.get("breadth", AS_OF - timedelta(days=1)) is not None


@pytest.mark.parametrize(
    "extra",
    [
        ["--repair-integrity"],
        ["--force", "--repair-integrity", "--dataset", "breadth"],
        ["--force", "--repair-integrity", "--dataset", "core", "--history-sessions", "2"],
    ],
)
def test_integrity_repair_cli_is_fail_closed(tmp_path, capsys, extra) -> None:
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "integrity-repair.sqlite3"),
        now=lambda: AFTER_MARKET,
    )

    exit_code = cli_main(
        [
            "snapshots",
            "refresh",
            "--as-of",
            AS_OF.isoformat(),
            *extra,
        ],
        coordinator=coordinator,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["status"] == "rejected"
    assert "--repair-integrity requires" in payload["error"]
    assert provider.calls == []


def test_snapshot_refresh_output_remains_backward_compatible(tmp_path, capsys) -> None:
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "snapshots.sqlite3"),
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
    )

    exit_code = cli_main(
        ["snapshots", "refresh", "--as-of", AS_OF.isoformat(), "--dataset", "breadth", "--force"],
        coordinator=coordinator,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["asOf"] == AS_OF.isoformat()
    assert payload["forced"] is True
    assert payload["status"] == "success"
    assert "trigger" not in payload
    assert [item["dataset"] for item in payload["datasets"]] == ["breadth"]


def test_limit_history_refresh_collects_six_calendar_sessions_in_ascending_order(
    tmp_path,
    capsys,
) -> None:
    sessions = (
        date(2026, 8, 27),
        date(2026, 8, 28),
        date(2026, 8, 31),
        date(2026, 9, 1),
        date(2026, 9, 2),
        AS_OF,
    )
    provider = CollectionProvider()
    provider.fetch_trading_days = lambda: sessions
    store = SnapshotStore(tmp_path / "history.sqlite3")
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
        limits_v1_enabled=False,
    )

    exit_code = cli_main(
        [
            "snapshots",
            "refresh",
            "--as-of",
            AS_OF.isoformat(),
            "--dataset",
            "limits",
            "--history-sessions",
            "6",
        ],
        coordinator=coordinator,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["historySessions"] == 6
    assert [item["asOf"] for item in payload["sessions"]] == [
        item.isoformat() for item in sessions
    ]
    assert provider.calls == ["limits"] * 6
    assert all(store.get("limits", item) is not None for item in sessions)
    assert store.get_trading_session(AS_OF).previous_as_of == date(2026, 9, 2)


def test_limit_history_refresh_continues_after_one_session_failure(tmp_path, capsys) -> None:
    sessions = (
        date(2026, 8, 28),
        date(2026, 8, 31),
        date(2026, 9, 1),
        date(2026, 9, 2),
        AS_OF,
    )

    class DatedFailureProvider(CollectionProvider):
        def fetch_trading_days(self):
            return sessions

        def fetch_chapter01_limits(self, as_of):
            self.calls.append(as_of.isoformat())
            if as_of == date(2026, 9, 1):
                raise RuntimeError("fixture dated failure")
            return chapter_payload("limits", as_of)

    provider = DatedFailureProvider()
    store = SnapshotStore(tmp_path / "partial-history.sqlite3")
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
        limits_v1_enabled=False,
    )

    exit_code = cli_main(
        [
            "snapshots",
            "refresh",
            "--as-of",
            AS_OF.isoformat(),
            "--dataset",
            "limits",
            "--history-sessions",
            "5",
        ],
        coordinator=coordinator,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["status"] == "partial"
    assert [item["status"] for item in payload["sessions"]].count("failed") == 1
    assert provider.calls == [item.isoformat() for item in sessions]
    assert store.get("limits", date(2026, 9, 1)) is None
    assert store.get("limits", AS_OF) is not None


@pytest.mark.parametrize(
    "datasets",
    [[], ["--dataset", "breadth"], ["--dataset", "limits", "--dataset", "breadth"]],
)
def test_limit_history_refresh_requires_explicit_limits_only(tmp_path, capsys, datasets) -> None:
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "invalid-history.sqlite3"),
        now=lambda: AFTER_MARKET,
    )
    argv = [
        "snapshots",
        "refresh",
        "--as-of",
        AS_OF.isoformat(),
        *datasets,
        "--history-sessions",
        "6",
    ]

    assert cli_main(argv, coordinator=coordinator) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "rejected"
    assert "exactly --dataset limits" in payload["error"]
    assert provider.calls == []
