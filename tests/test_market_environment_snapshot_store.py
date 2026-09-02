from datetime import date, datetime, timedelta, timezone
import sqlite3

import pytest

from src.market_environment.snapshot_store import (
    SNAPSHOT_SCHEMA_VERSION,
    SnapshotIntegrityError,
    SnapshotRecord,
    SnapshotStore,
    cache_state,
    payload_checksum,
)


AS_OF = date(2026, 9, 2)
NOW = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)


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

