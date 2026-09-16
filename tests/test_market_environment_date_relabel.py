from datetime import date, datetime, timezone
import json
import sqlite3

import pytest

from src.market_environment.cli import main as cli_main
from src.market_environment.date_relabel import DateRelabelError, relabel_date, rollback_date_relabel
from src.market_environment.snapshot_store import CoreIndexResultRecord, MaterializedAggregateRecord, SnapshotRecord, SnapshotStore


SOURCE = date(2026, 9, 15)
TARGET = date(2026, 9, 14)
NOW = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)


def _store(path):
    store = SnapshotStore(path)
    store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=SOURCE,
            payload={"asOf": SOURCE.isoformat(), "quality": {"asOf": SOURCE.isoformat(), "status": "ok"}, "value": 1},
            source="fixture",
            status="ok",
            observations=1,
            warnings=(),
            fetched_at=NOW,
        )
    )
    store.put_materialized_aggregate(
        MaterializedAggregateRecord(
            as_of=SOURCE,
            payload={"asOf": SOURCE.isoformat(), "value": 1},
            generated_at=NOW,
        )
    )
    return store


def test_date_relabel_defaults_to_dry_run_and_rewrites_date_metadata(tmp_path):
    store = _store(tmp_path / "isolated.sqlite3")
    result = relabel_date(store, SOURCE, TARGET)

    assert result.status == "dry-run"
    assert store.get("breadth", SOURCE) is not None
    assert store.get("breadth", TARGET) is None

    applied = relabel_date(store, SOURCE, TARGET, apply=True)
    assert applied.status == "applied"
    moved = store.get("breadth", TARGET)
    assert moved is not None
    assert moved.payload["asOf"] == TARGET.isoformat()
    assert moved.payload["quality"]["asOf"] == TARGET.isoformat()
    assert moved.settled is True
    aggregate = store.get_materialized_aggregate(TARGET)
    assert aggregate is not None
    assert aggregate.payload["asOf"] == TARGET.isoformat()
    audit = store.get_date_relabel_audit(applied.audit_id)
    assert audit is not None
    assert audit["status"] == "applied"
    assert audit["before_image_json"]["before"]["snapshot_entries"]


def test_date_relabel_rejects_checksum_or_third_date_and_preserves_source(tmp_path):
    store = _store(tmp_path / "isolated.sqlite3")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE snapshot_entries SET payload_json = ? WHERE dataset = 'breadth' AND as_of = ?",
            (json.dumps({"asOf": "2026-09-13", "quality": {"asOf": "2026-09-13"}}), SOURCE.isoformat()),
        )
    with pytest.raises(Exception, match="checksum mismatch"):
        relabel_date(store, SOURCE, TARGET)
    assert store.get("breadth", TARGET) is None


def test_date_relabel_detects_destination_conflict_without_overwrite(tmp_path):
    store = _store(tmp_path / "isolated.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=TARGET,
            payload={"asOf": TARGET.isoformat(), "quality": {"asOf": TARGET.isoformat()}, "value": 9},
            source="fixture",
            status="ok",
            observations=1,
            warnings=(),
            fetched_at=NOW,
        )
    )
    result = relabel_date(store, SOURCE, TARGET, apply=True)
    assert result.status == "rejected"
    assert result.conflicts
    assert store.get("breadth", SOURCE) is not None


def test_date_relabel_rejects_legacy_target_component_revision(tmp_path):
    store = _store(tmp_path / "isolated.sqlite3")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "DELETE FROM materialization_component_versions WHERE as_of = ?",
            (SOURCE.isoformat(),),
        )
        connection.execute(
            "INSERT INTO materialization_component_versions"
            "(component_kind, dataset, as_of, revision) VALUES ('snapshot', 'legacy', ?, 7)",
            (TARGET.isoformat(),),
        )

    result = relabel_date(store, SOURCE, TARGET, apply=True)

    assert result.status == "rejected"
    assert any("materialization_component_versions" in item for item in result.conflicts)
    assert store.get("breadth", SOURCE) is not None


def test_date_relabel_explicit_overwrite_restores_target_on_rollback(tmp_path):
    store = _store(tmp_path / "isolated.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=TARGET,
            payload={"asOf": TARGET.isoformat(), "quality": {"asOf": TARGET.isoformat()}, "value": 9},
            source="old",
            status="ok",
            observations=1,
            warnings=(),
            fetched_at=NOW,
        )
    )
    store.put_materialized_aggregate(
        MaterializedAggregateRecord(
            as_of=TARGET,
            payload={"asOf": TARGET.isoformat(), "value": 9},
            generated_at=NOW,
        )
    )

    applied = relabel_date(store, SOURCE, TARGET, apply=True, conflict_policy="overwrite")

    assert applied.status == "applied"
    assert store.get("breadth", TARGET).payload["value"] == 1
    rollback_date_relabel(store, applied.audit_id, apply=True)
    assert store.get("breadth", TARGET).payload["value"] == 9
    assert store.get("breadth", SOURCE).payload["value"] == 1


def test_date_relabel_rollback_is_audited_and_fenced(tmp_path):
    store = _store(tmp_path / "isolated.sqlite3")
    applied = relabel_date(store, SOURCE, TARGET, apply=True)
    # A subsequent write must make rollback refuse to remove the new row.
    store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=TARGET,
            payload={"asOf": TARGET.isoformat(), "quality": {"asOf": TARGET.isoformat()}, "value": 2},
            source="fixture",
            status="ok",
            observations=1,
            warnings=(),
            fetched_at=NOW,
        )
    )
    with pytest.raises(DateRelabelError, match="rollback refused"):
        rollback_date_relabel(store, applied.audit_id, apply=True)


def test_date_relabel_updates_task_and_core_index_payload_dates(tmp_path):
    store = SnapshotStore(tmp_path / "isolated.sqlite3")
    run = store.create_collection_run("run-1", SOURCE, ("core",), created_at=NOW)
    store.create_collection_task("task-1", run.run_id, "core", SOURCE, queued_at=NOW)
    store.put(
        SnapshotRecord(
            dataset="core",
            as_of=SOURCE,
            payload={
                "asOf": SOURCE.isoformat(),
                "indices": [
                    {
                        "history": [
                            {"date": "2026-09-12", "close": 0.9},
                            {"date": SOURCE.isoformat(), "close": 1.0},
                        ]
                    }
                ],
            },
            source="fixture",
            status="ok",
            observations=1,
            warnings=(),
            fetched_at=NOW,
        )
    )
    store.put_core_index_result(
        CoreIndexResultRecord(
            task_id="task-1",
            code="000001",
            name="fixture",
            status="success",
            payload={
                "history": [
                    {"date": "2026-09-12", "close": 0.9},
                    {"date": SOURCE.isoformat(), "close": 1.0},
                ]
            },
        )
    )
    result = relabel_date(store, SOURCE, TARGET, apply=True)
    assert result.status == "applied"
    assert store.get_collection_task("task-1").as_of == TARGET
    assert store.get_collection_task("task-1").settled is True
    history = store.list_core_index_results("task-1")[0].payload["history"]
    assert history[0]["date"] == "2026-09-12"
    assert history[1]["date"] == TARGET.isoformat()
    core_history = store.get("core", TARGET).payload["indices"][0]["history"]
    assert core_history[0]["date"] == "2026-09-12"
    assert core_history[1]["date"] == TARGET.isoformat()


def test_relabel_cli_requires_isolated_path_and_apply_flag(tmp_path, capsys):
    path = tmp_path / "isolated.sqlite3"
    _store(path)
    code = cli_main(["snapshots", "relabel-date", "--from", SOURCE.isoformat(), "--to", TARGET.isoformat(), "--path", str(path)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] == "dry-run"
    assert SnapshotStore(path).get("breadth", TARGET) is None
