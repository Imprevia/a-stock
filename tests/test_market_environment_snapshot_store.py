import ast
from datetime import date, datetime, timedelta, timezone
import inspect
import sqlite3

import pytest

from src.market_environment.domain.models import (
    CollectionFailureCategory,
    StructuredTaskFailure,
)
from src.market_environment.snapshot_store import (
    SNAPSHOT_SCHEMA_VERSION,
    CoreIndexResultRecord,
    MaterializedAggregateRecord,
    SnapshotIntegrityError,
    SnapshotRecord,
    SnapshotStore,
    cache_state,
    payload_checksum,
)
from src.market_environment.infrastructure.persistence.sqlite_import import (
    LegacySqliteSnapshotStore,
)


AS_OF = date(2026, 9, 2)
NOW = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)


def test_snapshot_store_public_facade_is_delegation_only() -> None:
    class FakeBackend:
        def get(self, dataset, as_of):
            return dataset, as_of

    facade = SnapshotStore.from_backend(FakeBackend())
    assert facade.get("core", AS_OF) == ("core", AS_OF)

    class_node = next(
        node
        for node in ast.parse(inspect.getsource(SnapshotStore)).body
        if isinstance(node, ast.ClassDef)
    )
    literals = {
        node.value.lower()
        for node in ast.walk(class_node)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not any(
        keyword in value
        for value in literals
        for keyword in ("select ", "insert ", "update ", "delete ")
    )


def test_sqlite_requires_explicit_legacy_adapter(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MARKET_ENVIRONMENT_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="requires PostgreSQL configuration"):
        SnapshotStore()

    path = tmp_path / "legacy.sqlite3"
    store = LegacySqliteSnapshotStore(path)
    store.put(record())
    assert LegacySqliteSnapshotStore(path).get("breadth", AS_OF) is not None


def record(*, dataset: str = "breadth", as_of: date = AS_OF, settled: bool = False) -> SnapshotRecord:
    payload = {"value": 3, "nested": {"b": 2, "a": 1}}
    return SnapshotRecord(
        dataset=dataset,
        as_of=as_of,
        payload=payload,
        source="fixture",
        status="ok",
        observations=3,
        warnings=(),
        fetched_at=NOW,
        settled=settled,
    )


def test_store_initializes_upserts_and_reopens_exact_date(tmp_path) -> None:
    path = tmp_path / "snapshots.sqlite3"
    first = SnapshotStore(path)
    stored = first.put(record())

    assert stored.schema_version == SNAPSHOT_SCHEMA_VERSION
    assert stored.checksum == payload_checksum(stored.payload)
    assert first.get("breadth", AS_OF) == stored
    assert first.get("breadth", date(2026, 9, 1)) is None

    replacement = SnapshotRecord(
        **{**record().__dict__, "payload": {"value": 4}, "observations": 4, "checksum": ""}
    )
    second = SnapshotStore(path)
    second.put(replacement)
    assert SnapshotStore(path).get("breadth", AS_OF).payload == {"value": 4}


def test_wal_mode_reopen_allows_collection_run_write(tmp_path) -> None:
    """Scheduled refreshes must write after reopening a persistent WAL DB."""
    path = tmp_path / "snapshots.sqlite3"
    SnapshotStore(path).create_collection_run("run-1", AS_OF, ("core",))

    reopened = SnapshotStore(path)
    reopened.create_collection_run("run-2", AS_OF, ("core",))

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("SELECT count(*) FROM collection_runs").fetchone()[0] == 2


def test_store_rejects_unsupported_schema_and_detects_tampering(tmp_path) -> None:
    path = tmp_path / "snapshots.sqlite3"
    store = SnapshotStore(path)
    with pytest.raises(ValueError, match="unsupported snapshot schema"):
        store.put(SnapshotRecord(**{**record().__dict__, "schema_version": 99}))

    store.put(record())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE snapshot_entries SET payload_json = ? WHERE dataset = ? AND as_of = ?",
            ('{"value":999}', "breadth", AS_OF.isoformat()),
        )
    with pytest.raises(SnapshotIntegrityError, match="checksum mismatch"):
        store.get("breadth", AS_OF)

    aggregate = store.put_materialized_aggregate(
        MaterializedAggregateRecord(
            as_of=AS_OF,
            payload={"asOf": AS_OF.isoformat(), "version": 1},
            generated_at=NOW,
        )
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE materialized_market_environment SET payload_json = ? WHERE as_of = ?",
            ('{"asOf":"2026-09-02","version":999}', AS_OF.isoformat()),
        )
    with pytest.raises(SnapshotIntegrityError, match="materialized aggregate checksum mismatch"):
        store.get_materialized_aggregate(aggregate.as_of)


def test_store_rejects_cross_date_core_snapshot_without_replacing_valid_row(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "strict-core.sqlite3")
    valid_payload = {
        "asOf": AS_OF.isoformat(),
        "indices": [
            {
                "code": "sh000001",
                "history": [{"date": AS_OF.isoformat(), "close": 3200}],
            }
        ],
    }
    valid = store.put(
        SnapshotRecord(
            dataset="core",
            as_of=AS_OF,
            payload=valid_payload,
            source="fixture",
            status="partial",
            observations=1,
            warnings=(),
            fetched_at=NOW,
        )
    )
    invalid = SnapshotRecord(
        **{
            **valid.__dict__,
            "payload": {
                "asOf": "2026-09-01",
                "indices": [
                    {
                        "code": "sh000001",
                        "history": [{"date": "2026-09-01", "close": 3190}],
                    }
                ],
            },
            "checksum": "",
        }
    )

    with pytest.raises(SnapshotIntegrityError, match="exact-date mismatch"):
        store.put(invalid)

    assert store.get("core", AS_OF) == valid


def test_store_rejects_cross_date_aggregate_without_replacing_valid_row(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "strict-aggregate.sqlite3")
    valid = store.put_materialized_aggregate(
        MaterializedAggregateRecord(
            as_of=AS_OF,
            payload={
                "asOf": AS_OF.isoformat(),
                "indices": [
                    {
                        "code": "sh000001",
                        "history": [{"date": AS_OF.isoformat(), "close": 3200}],
                    }
                ],
                "chapter01": {},
            },
            generated_at=NOW,
        )
    )

    with pytest.raises(SnapshotIntegrityError, match="exact-date mismatch"):
        store.put_materialized_aggregate(
            MaterializedAggregateRecord(
                as_of=AS_OF,
                payload={
                    "asOf": AS_OF.isoformat(),
                    "indices": [
                        {
                            "code": "sh000001",
                            "history": [{"date": "2026-09-01", "close": 3190}],
                        }
                    ],
                    "chapter01": {},
                },
                generated_at=NOW,
            )
        )

    assert store.get_materialized_aggregate(AS_OF) == valid


def test_leases_are_shared_across_store_instances_and_expire(tmp_path) -> None:
    path = tmp_path / "snapshots.sqlite3"
    first = SnapshotStore(path)
    second = SnapshotStore(path)

    assert first.acquire_lease("breadth", AS_OF, "worker-1", lease_seconds=10, now=NOW)
    assert not second.acquire_lease("breadth", AS_OF, "worker-2", lease_seconds=10, now=NOW)
    assert second.acquire_lease(
        "breadth",
        AS_OF,
        "worker-2",
        lease_seconds=10,
        now=NOW + timedelta(seconds=11),
    )
    assert not first.release_lease("breadth", AS_OF, "worker-1")
    assert second.release_lease("breadth", AS_OF, "worker-2")


def test_active_lease_datasets_returns_only_unexpired_leases(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.acquire_lease("breadth", AS_OF, "breadth-worker", lease_seconds=10, now=NOW)
    store.acquire_lease("activeDirection", AS_OF, "active-worker", lease_seconds=10, now=NOW)
    store.acquire_lease(
        "sectors",
        AS_OF,
        "expired-worker",
        lease_seconds=1,
        now=NOW - timedelta(seconds=10),
    )

    assert store.active_lease_datasets(AS_OF, now=NOW) == {"breadth", "activeDirection"}


def test_cache_state_distinguishes_missing_fresh_stale_and_settled() -> None:
    assert cache_state(None, now=NOW) == "missing"
    assert cache_state(record(), now=NOW + timedelta(seconds=29), soft_ttl_seconds=30) == "fresh"
    assert cache_state(record(), now=NOW + timedelta(seconds=30), soft_ttl_seconds=30) == "stale"
    assert cache_state(record(settled=True), now=NOW + timedelta(days=365), soft_ttl_seconds=30) == "fresh"


def test_prune_preserves_entries_with_active_lease(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    old_date = date(2026, 8, 1)
    protected_date = date(2026, 8, 2)
    keep_date = date(2026, 9, 1)
    store.put(record(as_of=old_date))
    store.put(record(dataset="activeDirection", as_of=protected_date))
    store.put(record(as_of=keep_date))
    store.acquire_lease("activeDirection", protected_date, "worker", lease_seconds=60, now=NOW)

    assert store.prune(date(2026, 8, 31), now=NOW) == 1
    assert store.get("breadth", old_date) is None
    assert store.get("activeDirection", protected_date) is not None
    assert store.get("breadth", keep_date) is not None


def test_collection_schema_migration_preserves_existing_snapshots(tmp_path) -> None:
    path = tmp_path / "snapshots.sqlite3"
    store = SnapshotStore(path)
    store.put(record())

    reopened = SnapshotStore(path)
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert reopened.get("breadth", AS_OF) is not None
    assert {
        "collection_runs",
        "collection_tasks",
        "core_index_results",
        "materialized_market_environment",
    } <= tables


def test_collection_run_and_task_state_transitions_are_typed_and_auditable(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    run = store.create_collection_run("run-1", AS_OF, ("breadth", "limits"), created_at=NOW)
    task = store.create_collection_task("task-1", run.run_id, "breadth", AS_OF, queued_at=NOW)

    collecting = store.transition_collection_task(
        task.task_id,
        "collecting",
        expected_statuses=("queued",),
        started_at=NOW + timedelta(seconds=1),
    )
    completed = store.transition_collection_task(
        task.task_id,
        "success",
        expected_statuses=("collecting",),
        source="fixture",
        observations=3,
        timings={"providerCollectionMs": 4.5},
        completed_at=NOW + timedelta(seconds=2),
        duration_ms=1000,
        settled=True,
    )
    updated_run = store.update_collection_run(
        run.run_id,
        "success",
        started_at=NOW + timedelta(seconds=1),
        completed_at=NOW + timedelta(seconds=2),
    )

    assert collecting.status == "collecting"
    assert completed.status == "success"
    assert completed.timings == {"providerCollectionMs": 4.5}
    assert updated_run.requested_datasets == ("breadth", "limits")
    assert store.list_collection_tasks(run.run_id) == (completed,)
    with pytest.raises(ValueError, match="transition rejected"):
        store.transition_collection_task(task.task_id, "collecting", expected_statuses=("queued",))


def test_latest_attempt_and_retained_snapshot_are_isolated_by_exact_date(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    previous_date = AS_OF - timedelta(days=1)
    store.put(record(as_of=previous_date))
    store.create_collection_run("run-old", previous_date, ("breadth",), created_at=NOW)
    store.create_collection_task("task-old", "run-old", "breadth", previous_date, queued_at=NOW)
    store.transition_collection_task(
        "task-old",
        "success",
        source="fixture",
        completed_at=NOW,
    )
    store.create_collection_run("run-new", AS_OF, ("breadth",), created_at=NOW + timedelta(seconds=1))
    store.create_collection_task(
        "task-new",
        "run-new",
        "breadth",
        AS_OF,
        queued_at=NOW + timedelta(seconds=1),
    )
    store.transition_collection_task(
        "task-new",
        "failed-missing",
        warning="provider unavailable",
        completed_at=NOW + timedelta(seconds=2),
    )

    assert store.get("breadth", AS_OF) is None
    assert store.get("breadth", previous_date) is not None
    assert store.latest_collection_attempt("breadth", AS_OF).status == "failed-missing"
    assert store.latest_collection_attempt("breadth", previous_date).status == "success"


def test_expired_active_task_becomes_retryable_and_retains_same_date_success(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(record())
    store.create_collection_run("run-1", AS_OF, ("breadth",), created_at=NOW)
    store.create_collection_task("task-1", "run-1", "breadth", AS_OF, queued_at=NOW)
    store.transition_collection_task("task-1", "collecting", started_at=NOW)
    store.acquire_lease("breadth", AS_OF, "worker", lease_seconds=5, now=NOW)

    assert store.active_collection_task("breadth", AS_OF, now=NOW) is not None
    assert store.expire_inactive_collection_tasks(now=NOW + timedelta(seconds=6)) == 1
    assert store.active_collection_task("breadth", AS_OF, now=NOW + timedelta(seconds=6)) is None
    assert store.get_collection_task("task-1").status == "failed-retained"
    assert store.get_collection_run("run-1").status == "failed"
    assert store.get("breadth", AS_OF) is not None


def test_collection_task_failures_round_trip_after_store_restart(tmp_path) -> None:
    path = tmp_path / "collection-failures.sqlite3"
    store = SnapshotStore(path)
    datasets = (
        "core",
        "breadth",
        "limits",
        "industry-ranking",
        "sector-turnover",
        "sector-breadth",
        "activeDirection",
    )
    store.create_collection_run("run-failures", AS_OF, datasets, created_at=NOW)
    for dataset in datasets:
        store.create_collection_task(
            f"task-{dataset}",
            "run-failures",
            dataset,
            AS_OF,
            queued_at=NOW,
        )

    store.transition_collection_task(
        "task-core",
        "success",
        source="fixture-core",
        observations=3,
        warning="successful compatibility warning",
        timings={"providerCollectionMs": 1.5},
        completed_at=NOW,
    )
    store.transition_collection_task(
        "task-breadth",
        "partial",
        source="fixture-breadth",
        observations=2,
        warning="partial candidate warning",
        timings={"providerCollectionMs": 2.5},
        completed_at=NOW,
    )
    store.put(record(dataset="limits", settled=True))
    store.transition_collection_task(
        "task-limits",
        "failed-retained",
        warning="rate limited; same-date snapshot retained",
        failure=StructuredTaskFailure(
            category=CollectionFailureCategory.RATE_LIMIT,
            message="provider rate limited the request",
            retryable=True,
            retained=True,
            source="fixture-provider",
            stage="acquisition",
        ),
        completed_at=NOW,
    )
    store.transition_collection_task(
        "task-industry-ranking",
        "failed-missing",
        warning="provider response was insufficient",
        failure=StructuredTaskFailure(
            category=CollectionFailureCategory.INSUFFICIENT,
            message="provider response was insufficient",
            retryable=True,
            retained=False,
            stage="acquisition",
        ),
        completed_at=NOW,
    )
    store.transition_collection_task(
        "task-sector-turnover",
        "blocked",
        warning='{"reasonCode":"THS_DEPENDENCY_INSUFFICIENT"}',
        failure=StructuredTaskFailure(
            category=CollectionFailureCategory.DEPENDENCY,
            message="blocked by industry-ranking",
            retryable=True,
            retained=False,
            stage="dependency-coordination",
            blocked_by=("industry-ranking",),
        ),
        completed_at=NOW,
    )
    store.transition_collection_task(
        "task-sector-breadth",
        "busy",
        warning="another task owns the lease",
        failure=StructuredTaskFailure(
            category=CollectionFailureCategory.CONCURRENCY,
            message="another task owns the dataset/date lease",
            retryable=True,
            retained=False,
            stage="lease-acquisition",
        ),
        completed_at=NOW,
    )
    store.transition_collection_task(
        "task-activeDirection",
        "collecting",
        started_at=NOW,
    )
    assert store.expire_inactive_collection_tasks(now=NOW + timedelta(seconds=1)) == 1
    assert store.get_collection_run("run-failures").status == "partial"

    before_restart = {
        task.dataset: task for task in store.list_collection_tasks("run-failures")
    }
    reopened = SnapshotStore(path)
    after_restart = {
        task.dataset: task for task in reopened.list_collection_tasks("run-failures")
    }

    assert set(after_restart) == set(datasets)
    for dataset in datasets:
        before = before_restart[dataset]
        after = after_restart[dataset]
        assert after.status == before.status
        assert after.source == before.source
        assert after.observations == before.observations
        assert after.warning == before.warning
        assert after.timings == before.timings
        assert (
            after.failure.to_dict() if after.failure is not None else None
        ) == (
            before.failure.to_dict() if before.failure is not None else None
        )

    assert after_restart["core"].failure is None
    assert after_restart["breadth"].failure is None
    assert after_restart["limits"].failure.retained is True
    assert after_restart["industry-ranking"].failure.retained is False
    assert after_restart["sector-turnover"].failure.blocked_by == (
        "industry-ranking",
    )
    assert (
        after_restart["activeDirection"].failure.category
        is CollectionFailureCategory.WORKER_INTERRUPTED
    )


def test_core_index_results_and_materialized_aggregate_replace_atomically(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.create_collection_run("run-1", AS_OF, ("core",), created_at=NOW)
    store.create_collection_task("task-1", "run-1", "core", AS_OF, queued_at=NOW)
    index_result = CoreIndexResultRecord(
        task_id="task-1",
        code="sh000001",
        name="上证指数",
        status="success",
        source="fixture",
        observations=60,
        duration_ms=4.5,
        payload={"code": "sh000001", "close": 3800.0},
    )
    store.put_core_index_result(index_result)
    first = store.put_materialized_aggregate(
        MaterializedAggregateRecord(
            as_of=AS_OF,
            payload={"asOf": AS_OF.isoformat(), "version": 1},
            generated_at=NOW,
        )
    )
    replacement = store.put_materialized_aggregate(
        MaterializedAggregateRecord(
            as_of=AS_OF,
            payload={"asOf": AS_OF.isoformat(), "version": 2},
            generated_at=NOW + timedelta(seconds=1),
        )
    )

    assert store.list_core_index_results("task-1") == (index_result,)
    assert first.checksum != replacement.checksum
    assert store.get_materialized_aggregate(AS_OF) == replacement
