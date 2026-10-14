from __future__ import annotations

import importlib.util
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.market_environment.domain.models.ths_sector import (
    ThsBackfillCheckpoint,
    ThsBackfillRun,
    ThsCatalogRelation,
    ThsCatalogRevision,
    ThsOperation,
    ThsRankingRow,
    ThsSectorBar,
    ThsSectorMembership,
)
from src.market_environment.infrastructure.persistence.postgres.ths_sector_repository import (
    PostgresThsSectorRepository,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)


def _migration_statements() -> tuple[str, ...]:
    path = ROOT / "alembic" / "versions" / "0005_ths_sector_datasets.py"
    spec = importlib.util.spec_from_file_location("ths_repo_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The repository fixture represents the post-0006 schema. SQLite cannot
    # execute PostgreSQL's ALTER COLUMN DROP NOT NULL, so model the final
    # nullable declaration directly while the migration test covers the DDL.
    return tuple(
        statement.replace(
            "change_pct DOUBLE PRECISION NOT NULL",
            "change_pct DOUBLE PRECISION",
        )
        for statement in module.UPGRADE_STATEMENTS[:-1]
    )


def _sqlite_sql(statement: str) -> str:
    value = re.sub(r"::jsonb\b", "", statement, flags=re.IGNORECASE)
    value = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", value, flags=re.IGNORECASE)
    return re.sub(r"\bJSONB\b", "TEXT", value, flags=re.IGNORECASE)


@pytest.fixture
def repository():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in _migration_statements():
            connection.exec_driver_sql(_sqlite_sql(statement))
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield PostgresThsSectorRepository(connection, now=lambda: NOW), connection
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def _revision(revision_id: str, checksum: str) -> ThsCatalogRevision:
    return ThsCatalogRevision(
        revision_id=revision_id,
        capability_revision=f"cap-{revision_id}",
        provider_timestamp=NOW,
        fetched_at=NOW,
        tag_counts={"industry": 1, "cn_concept": 1, "region": 1, "tszs": 1},
        checksum=checksum,
    )


def _relations(revision_id: str) -> tuple[ThsCatalogRelation, ...]:
    return (
        ThsCatalogRelation(revision_id, "industry", "885001.TI", "共享板块"),
        ThsCatalogRelation(revision_id, "cn_concept", "885001.TI", "共享概念"),
        ThsCatalogRelation(revision_id, "region", "885002.TI", "区域板块"),
        ThsCatalogRelation(revision_id, "tszs", "885003.TI", "特色指数"),
    )


def _bar(*, source_revision: str = "history-r1", checksum: str = "bar-checksum") -> ThsSectorBar:
    return ThsSectorBar(
        thscode="885001.TI",
        trading_date=date(2026, 10, 10),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        volume=1000.0,
        turnover=2000.0,
        source="fuyao",
        source_revision=source_revision,
        checksum=checksum,
        fetched_at=NOW,
    )


def test_catalog_idempotency_revision_coexistence_and_shared_code_identity(repository) -> None:
    repo, connection = repository
    r1 = _revision("catalog-r1", "checksum-r1")
    repo.put_catalog_revision(r1, _relations(r1.revision_id))
    repo.put_catalog_revision(r1, _relations(r1.revision_id))
    r2 = _revision("catalog-r2", "checksum-r2")
    repo.put_catalog_revision(r2, _relations(r2.revision_id))

    assert repo.count_catalog(revision_id="catalog-r1") == 4
    assert repo.count_catalog(revision_id="catalog-r2") == 4
    assert connection.execute(text("SELECT COUNT(*) FROM ths_sector_identities")).scalar_one() == 3
    with pytest.raises(ValueError, match="conflicting THS catalog revision checksum"):
        repo.put_catalog_revision(_revision("catalog-r1", "different"), _relations("catalog-r1"))


def test_catalog_revision_retries_ignore_observation_timestamp_drift(repository) -> None:
    repo, connection = repository
    original = _revision("catalog-r1", "checksum-r1")
    repo.put_catalog_revision(original, _relations(original.revision_id))

    retry = ThsCatalogRevision(
        revision_id=original.revision_id,
        capability_revision=original.capability_revision,
        provider_timestamp=original.provider_timestamp + timedelta(minutes=5),
        fetched_at=original.fetched_at + timedelta(minutes=6),
        tag_counts=original.tag_counts,
        checksum=original.checksum,
        source=original.source,
    )
    repo.put_catalog_revision(retry, _relations(retry.revision_id))

    assert connection.execute(
        text("SELECT COUNT(*) FROM ths_catalog_revisions WHERE revision_id='catalog-r1'")
    ).scalar_one() == 1


class _MappingResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self._rows


class _ReadOnlyConnection:
    def __init__(self, row):
        self.row = row

    def execute(self, *_args, **_kwargs):
        return _MappingResult([self.row])


def test_list_rankings_round_trips_nullable_provider_values() -> None:
    connection = _ReadOnlyConnection(
        {
            "tag": "industry",
            "rank": 1,
            "thscode": "885001.TI",
            "display_name": "共享板块",
            "change_pct": None,
            "volume": None,
            "turnover": None,
            "catalog_revision_id": "catalog-r1",
            "as_of": date(2026, 10, 10),
        }
    )
    repo = PostgresThsSectorRepository(connection, now=lambda: NOW)

    assert repo.list_rankings(date(2026, 10, 10), tag="industry") == (
        ThsRankingRow(
            tag="industry",
            rank=1,
            thscode="885001.TI",
            name="共享板块",
            change_pct=None,
            volume=None,
            turnover=None,
            catalog_revision="catalog-r1",
            as_of=date(2026, 10, 10),
        ),
    )


def test_bar_same_checksum_is_idempotent_conflict_does_not_overwrite_and_revisions_coexist(repository) -> None:
    repo, connection = repository
    revision = _revision("catalog-r1", "checksum-r1")
    repo.put_catalog_revision(revision, _relations(revision.revision_id))

    assert repo.put_sector_bar(_bar()) == "inserted"
    assert repo.put_sector_bar(_bar()) == "identical"
    assert repo.put_sector_bar(_bar(checksum="conflicting")) == "conflict"
    assert repo.put_sector_bar(_bar(source_revision="history-r2", checksum="bar-r2")) == "inserted"

    stored = connection.execute(
        text("SELECT source_revision,checksum FROM ths_sector_daily_bars ORDER BY source_revision")
    ).all()
    assert stored == [("history-r1", "bar-checksum"), ("history-r2", "bar-r2")]
    assert repo.count_sector_bars("885001.TI") == 1
    assert len(repo.list_sector_bars("885001.TI")) == 1


def test_daily_catalog_observation_bars_can_be_read_explicitly_without_merging(
    repository,
) -> None:
    repo, _connection = repository
    first = _bar(source_revision="catalog-r1", checksum="bar-r1")
    second = _bar(source_revision="catalog-r2", checksum="bar-r2")
    assert repo.put_sector_bar(first) == "inserted"
    assert repo.put_sector_bar(second) == "inserted"
    assert repo.list_sector_bars("885001.TI")[0].source_revision == "catalog-r2"
    assert repo.list_sector_bars("885001.TI", source_revision="catalog-r1") == (first,)
    assert repo.list_sector_bars("885001.TI", source_revision="catalog-r2") == (second,)


def test_rankings_memberships_and_generic_operation_round_trip(repository) -> None:
    repo, _connection = repository
    revision = _revision("catalog-r1", "checksum-r1")
    repo.put_catalog_revision(revision, _relations(revision.revision_id))
    rankings = (
        ThsRankingRow(
            tag="industry", rank=1, thscode="885001.TI", name="共享板块",
            change_pct=1.2, volume=100.0, turnover=200.0,
            catalog_revision="catalog-r1", as_of=date(2026, 10, 10),
        ),
    )
    assert repo.put_rankings(rankings) == {"inserted": 1, "identical": 0, "conflict": 0}
    assert repo.put_rankings(rankings) == {"inserted": 0, "identical": 1, "conflict": 0}
    assert repo.list_rankings(date(2026, 10, 10), tag="industry") == rankings

    memberships = (
        ThsSectorMembership(
            thscode="885001.TI", member_security_id="600000.SH", member_name="浦发银行",
            as_of=date(2026, 10, 10), provider_timestamp=NOW, fetched_at=NOW,
            source_revision="members-r1", checksum="member-checksum",
        ),
    )
    assert repo.put_sector_memberships(memberships)["inserted"] == 1
    assert repo.put_sector_memberships(memberships)["identical"] == 1
    assert repo.list_sector_memberships("885001.TI", as_of=date(2026, 10, 10)) == memberships

    operation = ThsOperation(
        run_id="catalog-run-1",
        kind="catalog-sync",
        status="success",
        capability_revision="catalog-cap-r1",
        request_checksum="request-checksum",
        request_metadata={"tags": ["industry", "cn_concept", "region", "tszs"]},
        progress={"phase": "complete"},
        result={"relations": 4},
        total_items=4,
        completed_items=4,
        request_budget=1,
        requests_used=1,
        requested_at=NOW,
        started_at=NOW,
        completed_at=NOW,
    )
    repo.put_operation(operation)
    assert repo.get_operation("catalog-run-1") == operation
    assert repo.list_operations(kind="catalog-sync", status="success") == (operation,)


def test_rankings_with_missing_change_pct_write_and_read_back(repository) -> None:
    repo, _connection = repository
    revision = _revision("catalog-r1", "checksum-r1")
    repo.put_catalog_revision(revision, _relations(revision.revision_id))
    ranking = ThsRankingRow(
        tag="industry",
        rank=1,
        thscode="885001.TI",
        name="共享板块",
        change_pct=None,
        volume=None,
        turnover=None,
        catalog_revision="catalog-r1",
        as_of=date(2026, 10, 10),
        quality="insufficient",
        warnings=("changePct is unavailable",),
    )

    assert repo.put_rankings((ranking,)) == {
        "inserted": 1,
        "identical": 0,
        "conflict": 0,
    }
    assert repo.list_rankings(date(2026, 10, 10), tag="industry") == (ranking,)


def test_rankings_select_one_latest_revision_and_explicit_revision_never_merges(
    repository,
) -> None:
    repo, _connection = repository
    older = _revision("catalog-r1", "checksum-r1")
    newer = _revision("catalog-r2", "checksum-r2")
    repo.put_catalog_revision(older, _relations(older.revision_id))
    repo.put_catalog_revision(newer, _relations(newer.revision_id))
    as_of = date(2026, 10, 10)
    old_row = ThsRankingRow(
        tag="industry",
        rank=1,
        thscode="885001.TI",
        name="共享板块",
        change_pct=1.0,
        volume=100.0,
        turnover=200.0,
        catalog_revision=older.revision_id,
        as_of=as_of,
    )
    new_row = ThsRankingRow(
        tag="industry",
        rank=1,
        thscode="885001.TI",
        name="共享板块",
        change_pct=2.0,
        volume=100.0,
        turnover=200.0,
        catalog_revision=newer.revision_id,
        as_of=as_of,
    )
    repo.put_rankings((old_row, new_row))

    assert repo.latest_catalog_revision(as_of) == newer
    assert repo.list_rankings(as_of) == (new_row,)
    assert repo.list_rankings(as_of, revision_id=older.revision_id) == (old_row,)


def test_backfill_run_and_checkpoints_use_generic_operation_state(repository) -> None:
    repo, _connection = repository
    revision = _revision("catalog-r1", "checksum-r1")
    repo.put_catalog_revision(revision, _relations(revision.revision_id))
    run = ThsBackfillRun(
        run_id="backfill-run-1",
        thscodes=("885001.TI",),
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 10),
        capability_revision="history-cap-r1",
        request_budget=2,
        status="running",
        requests_used=1,
    )
    repo.put_backfill_run(run)

    assert repo.get_backfill_run(run.run_id) == run
    operation = repo.get_operation(run.run_id)
    assert operation is not None
    assert operation.kind == "turnover-backfill"
    assert operation.request_metadata["thscodes"] == ["885001.TI"]

    checkpoint = ThsBackfillCheckpoint(
        run_id=run.run_id,
        thscode="885001.TI",
        window_start=date(2026, 10, 1),
        window_end=date(2026, 10, 10),
        status="success",
        source_revision="history-r1",
        rows_written=6,
    )
    repo.put_backfill_checkpoint(checkpoint)
    assert repo.list_backfill_checkpoints(run.run_id) == (checkpoint,)
    with pytest.raises(ValueError, match="source revision"):
        repo.put_backfill_checkpoint(
            ThsBackfillCheckpoint(
                run_id=run.run_id,
                thscode="885001.TI",
                window_start=date(2026, 10, 1),
                window_end=date(2026, 10, 10),
                status="success",
                source_revision="history-r2",
            )
        )


def test_repository_writes_roll_back_with_shared_transaction() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in _migration_statements():
            connection.exec_driver_sql(_sqlite_sql(statement))
    with engine.connect() as connection:
        transaction = connection.begin()
        repo = PostgresThsSectorRepository(connection, now=lambda: NOW)
        revision = _revision("catalog-r1", "checksum-r1")
        repo.put_catalog_revision(revision, _relations(revision.revision_id))
        transaction.rollback()
        assert connection.execute(text("SELECT COUNT(*) FROM ths_catalog_revisions")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM ths_catalog_relations")).scalar_one() == 0
    engine.dispose()
