from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.market_environment.application.ports import CoreCommitRequest
from src.market_environment.application.mappers import candidate_to_snapshot_fields
from src.market_environment.bootstrap.app import create_app
from src.market_environment.bootstrap.container import ContainerAdapters, build_container
from src.market_environment.bootstrap.settings import MarketEnvironmentSettings
from src.market_environment.domain.analysis import Bar
from src.market_environment.domain.models import (
    AcquisitionTimings,
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
    QualityMetadata,
)
from src.market_environment.infrastructure.collection import (
    AcquisitionPlanCollector,
    CoreDatasetCommitter,
    CoreCommitRequestFactory,
    CoreRetainedIndexReader,
)
from src.market_environment.providers import INDEX_SPECS
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import (
    CollectionTaskRecord,
    CoreIndexResultRecord,
    LeaseToken,
    SnapshotRecord,
    SnapshotStore,
    TradingSessionRecord,
    payload_checksum,
)
from src.market_environment.trading_sessions import TradingDayResolver


AS_OF = date(2026, 9, 18)
PREVIOUS = date(2026, 9, 17)
NOW = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)
IDENTITY = DatasetDate("core", AS_OF)
MARKET_NOW = datetime(2026, 9, 18, 16, 0, tzinfo=MARKET_TIME_ZONE)


def _index(code: str, source: str) -> dict:
    return {
        "code": code,
        "name": code,
        "history": [
            {"date": PREVIOUS.isoformat(), "close": 100.0},
            {"date": AS_OF.isoformat(), "close": 101.0},
        ],
        "dataQuality": {"source": source},
    }


def _outcome() -> CollectionOutcome:
    fresh = _index("sh000001", "mootdx")
    retained = _index("sz399001", "retained-source")
    extra = {
        "indexResults": (
            {
                "code": "sh000001",
                "name": "上证指数",
                "status": "success",
                "source": "mootdx",
                "observations": 2,
                "warning": None,
                "durationMs": 2.5,
                "retained": False,
            },
            {
                "code": "sz399001",
                "name": "深证成指",
                "status": "failed-retained",
                "source": "retained-source",
                "observations": 2,
                "warning": "provider unavailable",
                "durationMs": 3.5,
                "retained": True,
            },
        ),
        "tradingSession": {
            "asOf": AS_OF.isoformat(),
            "previousAsOf": PREVIOUS.isoformat(),
            "isSession": True,
            "source": "core-index-history:mootdx,retained-source",
            "actualAsOf": AS_OF.isoformat(),
            "fetchedAt": NOW.isoformat(),
            "warnings": (),
        },
        "sessionWarning": None,
    }
    candidate = CollectionCandidate(
        identity=IDENTITY,
        payload={
            "asOf": AS_OF.isoformat(),
            "indices": [fresh, retained],
        },
        source="mootdx",
        status="partial",
        observations=2,
        warnings=("one index retained",),
        settled=True,
        actual_as_of=AS_OF,
        quality=QualityMetadata(
            dataset="core-indices",
            source="mootdx",
            provider="mootdx",
            status="partial",
            observations=2,
            as_of=AS_OF,
            extra=extra,
        ),
        timings=AcquisitionTimings(
            total_ms=12.0,
            phases_ms={"quoteMs": 1.0},
        ),
    )
    return CollectionOutcome(
        identity=IDENTITY,
        state=CollectionTaskState.PARTIAL,
        candidate=candidate,
        warning="one index retained",
    )


def _task() -> CollectionTaskRecord:
    return CollectionTaskRecord(
        task_id="core-task",
        run_id="core-run",
        dataset="core",
        as_of=AS_OF,
        status="collecting",
        timings={"leaseWaitMs": 0.25},
        started_at=NOW - timedelta(seconds=1),
    )


def _lease() -> LeaseToken:
    return LeaseToken(
        dataset="core",
        as_of=AS_OF,
        owner="core-task",
        generation=1,
        token="core-token",
        expires_at=NOW + timedelta(minutes=10),
    )


def test_core_commit_request_factory_maps_normalized_evidence_and_timings() -> None:
    request = CoreCommitRequestFactory(lambda: NOW)(_task(), _outcome(), _lease())

    assert isinstance(request, CoreCommitRequest)
    assert [item.state.value for item in request.index_results] == [
        "success",
        "failed-retained",
    ]
    assert request.index_results[1].retained is True
    assert request.index_results[1].payload["code"] == "sz399001"
    assert request.session is not None
    assert request.session.previous_as_of == PREVIOUS
    assert request.task_timings == {
        "leaseWaitMs": 0.25,
        "quoteMs": 1.0,
        "providerCollectionMs": 12.0,
    }
    assert request.completed_at == NOW
    assert request.duration_ms == 1000.0


def test_core_commit_request_factory_rejects_unmatched_retained_payload() -> None:
    outcome = _outcome()
    candidate = outcome.candidate
    assert candidate is not None
    malformed = CollectionOutcome(
        identity=IDENTITY,
        state=CollectionTaskState.PARTIAL,
        candidate=CollectionCandidate(
            identity=IDENTITY,
            payload={"asOf": AS_OF.isoformat(), "indices": candidate.payload["indices"][:1]},
                source=candidate.source,
                status=candidate.status,
                observations=1,
                warnings=candidate.warnings,
                settled=candidate.settled,
                quality=candidate.quality,
        ),
    )

    with pytest.raises(ValueError, match="requires payload"):
        CoreCommitRequestFactory(lambda: NOW)(_task(), malformed, _lease())


def test_core_commit_request_allows_partial_fallback_with_all_indices_successful() -> None:
    outcome = _outcome()
    candidate = outcome.candidate
    assert candidate is not None and candidate.quality is not None
    raw_results = tuple(
        {
            **dict(value),
            "status": "success",
            "retained": False,
            "warning": "formal source failed; fallback succeeded",
        }
        for value in candidate.quality.extra["indexResults"]
    )
    quality = replace(
        candidate.quality,
        extra={**candidate.quality.extra, "indexResults": raw_results},
    )
    degraded = CollectionOutcome(
        identity=IDENTITY,
        state=CollectionTaskState.PARTIAL,
        candidate=replace(candidate, quality=quality, status="partial"),
        warning="formal source failed; fallback succeeded",
    )

    request = CoreCommitRequestFactory(lambda: NOW)(_task(), degraded, _lease())

    assert all(
        result.state is CollectionTaskState.SUCCESS
        for result in request.index_results
    )
    assert request.outcome.state is CollectionTaskState.PARTIAL


def test_core_retained_index_reader_uses_only_exact_date_snapshot(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "core-retained.sqlite3")
    retained = _index("sh000001", "same-date")
    store.put(
        SnapshotRecord(
            dataset="core",
            as_of=AS_OF,
            payload={"asOf": AS_OF.isoformat(), "indices": [retained]},
            source="same-date",
            status="ok",
            observations=1,
            warnings=(),
            fetched_at=NOW,
        )
    )
    reader = CoreRetainedIndexReader(store)

    exact = reader(IDENTITY)

    assert exact == {"sh000001": retained}
    exact["sh000001"]["dataQuality"]["source"] = "mutated"
    assert store.get("core", AS_OF).payload["indices"][0]["dataQuality"][
        "source"
    ] == "same-date"
    assert reader(DatasetDate("core", PREVIOUS)) == {}


def _bars(count: int = 280) -> list[Bar]:
    return [
        Bar(
            date=AS_OF - timedelta(days=count - index - 1),
            open=2999.0 + index,
            close=3000.0 + index,
            high=3001.0 + index,
            low=2998.0 + index,
            amount=1_000_000.0 + index,
        )
        for index in range(count)
    ]


@dataclass
class RuntimeProvider:
    failing_codes: set[str] = field(default_factory=set)
    quote_calls: int = 0
    history_calls: list[tuple[str, str]] = field(default_factory=list)
    legacy_core_calls: int = 0

    def fetch_quotes(self, specs):
        self.quote_calls += 1
        return {
            spec.code: {
                "name": spec.name,
                "price": 3279.0,
                "last_close": 3278.0,
                "change_pct": 0.03,
                "amount": 1_000_000.0,
                "is_stale": False,
            }
            for spec in specs
        }

    def fetch(self, *_args, **_kwargs):
        self.legacy_core_calls += 1
        raise AssertionError("legacy CoreCollector provider facade was invoked")

    def _history(self, source: str, spec):
        self.history_calls.append((source, spec.code))
        if spec.code in self.failing_codes:
            raise RuntimeError(f"{source} unavailable for {spec.code}")
        return copy.deepcopy(_bars())

    def _fetch_mootdx(self, spec, _limit):
        return self._history("mootdx", spec)

    def _fetch_baidu_kline(self, spec, _limit):
        return self._history("baidu", spec)

    def _fetch_sina_kline(self, spec, _limit, _quote):
        return self._history("sina", spec)

    def _fetch_tencent_kline(self, spec, _limit):
        return self._history("tencent", spec)

    def _fetch_eastmoney_kline(self, spec, _limit):
        return self._history("eastmoney", spec)

    def close(self) -> None:
        pass


class FuyaoClient:
    def fetch_core(self, *_args, **_kwargs):
        raise AssertionError("Fuyao core must remain disabled by its default gate")

    def close(self) -> None:
        pass


class TimezoneRepository:
    def get(self, *_args, **_kwargs):
        return None

    def set(self, *_args, **_kwargs):
        return None

    def close(self) -> None:
        pass


class Executor:
    def submit(self, function, *args):
        return function(*args)

    def shutdown(self, *, wait=True, cancel_futures=False) -> None:
        pass


@dataclass
class _CommitContext:
    lease: LeaseToken | None = None


class _SnapshotRepository:
    def __init__(self, store: SnapshotStore, context: _CommitContext) -> None:
        self.store = store
        self.context = context

    def get(self, identity):
        snapshot = self.store.get(identity.dataset, identity.as_of)
        if snapshot is None:
            return None
        from src.market_environment.application.mappers import snapshot_to_candidate

        return snapshot_to_candidate(snapshot)

    def put(self, candidate):
        self.store.put(
            SnapshotRecord(**candidate_to_snapshot_fields(candidate, fetched_at=MARKET_NOW)),
            lease=self.context.lease,
            now=MARKET_NOW.astimezone(timezone.utc),
        )
        return candidate


class _CollectionTaskRepository:
    def __init__(self, store: SnapshotStore) -> None:
        self.store = store

    def get_task(self, task_id: str):
        return self.store.get_collection_task(task_id)

    def save_task(self, record: CollectionTaskRecord):
        return self.store.transition_collection_task(
            record.task_id,
            record.status,
            expected_statuses=("collecting",),
            source=record.source,
            observations=record.observations,
            warning=record.warning,
            timings=dict(record.timings),
            completed_at=record.completed_at,
            duration_ms=record.duration_ms,
            settled=record.settled,
        )


class _CoreIndexRepository:
    def __init__(self, store: SnapshotStore, context: _CommitContext) -> None:
        self.store = store
        self.context = context

    def put_result(self, record: CoreIndexResultRecord):
        return self.store.put_core_index_result(
            record,
            lease=self.context.lease,
            now=MARKET_NOW.astimezone(timezone.utc),
        )


class _TradingSessionRepository:
    def __init__(self, store: SnapshotStore, context: _CommitContext) -> None:
        self.store = store
        self.context = context

    def put_session(self, record: TradingSessionRecord):
        return self.store.put_trading_session(
            record,
            lease=self.context.lease,
            now=MARKET_NOW.astimezone(timezone.utc),
        )

    def put_session_if_absent(self, record: TradingSessionRecord):
        existing = self.store.get_trading_session(record.as_of)
        if existing is not None:
            return existing
        return self.store.put_trading_session(record)


class _LeaseRepository:
    def __init__(self, context: _CommitContext) -> None:
        self.context = context

    def execute_fenced(
        self,
        lease,
        _operation,
        writer,
        *,
        expected_identity=None,
    ):
        assert expected_identity.dataset == lease.dataset
        assert expected_identity.as_of == lease.as_of
        self.context.lease = lease
        try:
            return writer(object())
        finally:
            self.context.lease = None


class _UnitOfWork:
    def __init__(self, store: SnapshotStore) -> None:
        context = _CommitContext()
        self.snapshots = _SnapshotRepository(store, context)
        self.collection_tasks = _CollectionTaskRepository(store)
        self.core_index_results = _CoreIndexRepository(store, context)
        self.trading_sessions = _TradingSessionRepository(store, context)
        self.leases = _LeaseRepository(context)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        pass

    def commit(self) -> None:
        self.committed = True


class _UnitOfWorkFactory:
    def __init__(self, store: SnapshotStore) -> None:
        self.store = store
        self.units: list[_UnitOfWork] = []

    def __call__(self) -> _UnitOfWork:
        unit = _UnitOfWork(self.store)
        self.units.append(unit)
        return unit


def _runtime_container(tmp_path):
    store = SnapshotStore(tmp_path / "core-runtime.sqlite3")
    provider = RuntimeProvider()
    unit_of_work_factory = _UnitOfWorkFactory(store)
    container = build_container(
        MarketEnvironmentSettings.from_environment(
            {"MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0"}
        ),
        adapters=ContainerAdapters(
            repository=store,
            collector=provider,
            clock=lambda: MARKET_NOW,
            task_executor=Executor(),
            refresh_executor=Executor(),
            timezone_repository=TimezoneRepository(),
            fuyao_adapter=FuyaoClient(),
            unit_of_work_factory=unit_of_work_factory,
        ),
    )
    rebuilds: list[date] = []
    container.reads.collection.coordinator.rebuild_aggregate = (
        lambda as_of, **_kwargs: rebuilds.append(as_of)
    )
    return container, store, provider, unit_of_work_factory, rebuilds


def test_default_runtime_commits_complete_core_and_exposes_local_details(tmp_path) -> None:
    container, store, provider, factory, rebuilds = _runtime_container(tmp_path)
    coordinator = container.reads.collection.coordinator

    result = coordinator.collect(AS_OF, ("core",))

    assert coordinator.typed_cutover_datasets == frozenset(
        {"core", "breadth", "limits", "sectors", "activeDirection"}
    )
    assert isinstance(
        container.registries.collectors.get("core"),
        AcquisitionPlanCollector,
    )
    assert isinstance(
        container.registries.committers.get("core"),
        CoreDatasetCommitter,
    )
    assert result.run.status == "success"
    assert result.tasks[0].status == "success"
    assert result.tasks[0].source == "mootdx"
    assert result.tasks[0].observations == 5
    assert "leaseWaitMs" in result.tasks[0].timings
    assert "providerCollectionMs" in result.tasks[0].timings
    assert provider.quote_calls == 1
    assert provider.legacy_core_calls == 0
    assert provider.history_calls == [("mootdx", spec.code) for spec in INDEX_SPECS]
    assert rebuilds == [AS_OF]
    snapshot = store.get("core", AS_OF)
    assert snapshot is not None
    assert snapshot.checksum == payload_checksum(snapshot.payload)
    assert len(snapshot.payload["indices"]) == 5
    details = store.list_core_index_results(result.tasks[0].task_id)
    assert len(details) == 5
    assert all(item.status == "success" for item in details)
    assert factory.units[0].committed is True
    resolution = TradingDayResolver(store).resolve(AS_OF)
    assert resolution.sufficient is True
    assert resolution.previous_as_of == PREVIOUS

    calls_after_collection = (provider.quote_calls, list(provider.history_calls))
    with TestClient(create_app(overrides=container)) as client:
        run_response = client.get(
            f"/api/market-environment/collection-runs/{result.run.run_id}"
        )
        status_response = client.get(
            f"/api/market-environment/data-collection?as_of={AS_OF.isoformat()}"
        )
    assert run_response.status_code == 200
    assert len(run_response.json()["tasks"][0]["coreIndices"]) == 5
    assert status_response.status_code == 200
    core_status = next(
        item for item in status_response.json()["datasets"] if item["dataset"] == "core"
    )
    assert core_status["available"] is True
    assert len(core_status["coreIndices"]) == 5
    assert (provider.quote_calls, provider.history_calls) == calls_after_collection
    container.close()


def test_runtime_retains_one_same_date_index_inside_partial_atomic_commit(tmp_path) -> None:
    container, store, provider, factory, rebuilds = _runtime_container(tmp_path)
    coordinator = container.reads.collection.coordinator
    first = coordinator.collect(AS_OF, ("core",))
    retained_code = INDEX_SPECS[0].code
    retained_payload = next(
        value
        for value in store.get("core", AS_OF).payload["indices"]
        if value["code"] == retained_code
    )
    provider.failing_codes.add(retained_code)

    second = coordinator.collect(AS_OF, ("core",))

    assert first.tasks[0].status == "success"
    assert second.run.status == "partial"
    assert second.tasks[0].status == "partial"
    assert retained_code in second.tasks[0].warning
    details = {
        item.code: item
        for item in store.list_core_index_results(second.tasks[0].task_id)
    }
    assert details[retained_code].status == "failed-retained"
    assert details[retained_code].payload == retained_payload
    snapshot = store.get("core", AS_OF)
    assert snapshot is not None
    assert snapshot.checksum == payload_checksum(snapshot.payload)
    assert len(snapshot.payload["indices"]) == 5
    assert len(factory.units) == 2
    assert all(unit.committed for unit in factory.units)
    assert rebuilds == [AS_OF, AS_OF]
    assert provider.legacy_core_calls == 0
    container.close()


def test_runtime_all_failed_core_persists_details_without_overwriting_snapshot(
    tmp_path,
) -> None:
    container, store, provider, factory, rebuilds = _runtime_container(tmp_path)
    coordinator = container.reads.collection.coordinator
    first = coordinator.collect(AS_OF, ("core",))
    before = store.get("core", AS_OF)
    assert before is not None
    provider.failing_codes.update(spec.code for spec in INDEX_SPECS)

    second = coordinator.collect(AS_OF, ("core",))

    assert first.tasks[0].status == "success"
    assert second.run.status == "failed"
    assert second.tasks[0].status == "failed-retained"
    details = store.list_core_index_results(second.tasks[0].task_id)
    assert len(details) == len(INDEX_SPECS)
    assert all(item.status == "failed-retained" for item in details)
    assert all(item.payload is not None for item in details)
    after = store.get("core", AS_OF)
    assert after is not None
    assert after.payload == before.payload
    assert after.checksum == before.checksum
    assert after.fetched_at == before.fetched_at
    assert after.refresh_warning is not None
    assert len(factory.units) == 2
    assert all(unit.committed for unit in factory.units)
    assert rebuilds == [AS_OF, AS_OF]
    container.close()


def test_default_runtime_does_not_construct_legacy_core_collector(
    monkeypatch,
    tmp_path,
) -> None:
    from src.market_environment.bootstrap import container as container_module

    def reject_legacy_core(*_args, **_kwargs):
        raise AssertionError("legacy CoreCollector was constructed")

    monkeypatch.setattr(container_module, "CoreCollector", reject_legacy_core)

    container, _store, _provider, _factory, _rebuilds = _runtime_container(tmp_path)

    assert isinstance(
        container.registries.collectors.get("core"),
        AcquisitionPlanCollector,
    )
    container.close()
