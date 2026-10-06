from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.market_environment.application.ports import LimitDetailRepository
from src.market_environment.infrastructure.persistence.postgres import (
    PostgresLimitDetailRepository,
)
from src.market_environment.limit_facts import (
    LimitSecurityFactRecord,
    limit_dataset_checksum,
)
from src.market_environment.snapshot_store import SnapshotIntegrityError


AS_OF = date(2026, 9, 14)
FETCHED_AT = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


@pytest.fixture
def limit_connection():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    connection = engine.connect()
    connection.exec_driver_sql(
        """
        CREATE TABLE limit_security_datasets (
            as_of DATE PRIMARY KEY, actual_as_of DATE, source TEXT NOT NULL,
            source_revision TEXT, rule_version TEXT, schema_version INTEGER NOT NULL,
            complete INTEGER NOT NULL, membership_complete INTEGER,
            streak_complete INTEGER, pool_quality_json TEXT, excluded INTEGER NOT NULL,
            warnings_json TEXT NOT NULL, dataset_checksum TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE limit_security_facts (
            as_of DATE NOT NULL, actual_as_of DATE, security_id TEXT NOT NULL,
            pool_type TEXT NOT NULL, code TEXT NOT NULL, exchange TEXT NOT NULL,
            name TEXT, board TEXT, is_st INTEGER, is_new INTEGER, listing_date DATE,
            listing_days INTEGER, limit_regime TEXT, close_price REAL,
            previous_close REAL, change_pct REAL, touched_limit_up INTEGER,
            closed_limit_up INTEGER, failed_limit_up INTEGER, streak_days INTEGER,
            limit_up_time TEXT, limit_up_reason TEXT, seal_money REAL,
            max_seal_money REAL, first_limit_time TEXT, last_limit_time TEXT,
            open_times INTEGER, turnover_ratio_pct REAL, turnover REAL,
            row_quality TEXT, row_warnings_json TEXT NOT NULL, eligible INTEGER NOT NULL,
            invalid_reason TEXT, source TEXT NOT NULL, fetched_at TEXT NOT NULL,
            schema_version INTEGER NOT NULL, row_checksum TEXT NOT NULL,
            dataset_checksum TEXT, PRIMARY KEY(as_of, security_id, pool_type)
        )
        """
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()
        engine.dispose()


def _fact(*, name: str = "示例股份") -> LimitSecurityFactRecord:
    return LimitSecurityFactRecord(
        as_of=AS_OF,
        actual_as_of=AS_OF,
        security_id="SSE:600000",
        pool_type="limit_up",
        code="600000",
        exchange="SSE",
        name=name,
        closed_limit_up=True,
        streak_days=2,
        eligible=True,
        source="fixture",
        fetched_at=FETCHED_AT,
    ).normalized()


def _manifest(facts, *, source_revision: str = "fixture-v1") -> dict:
    checksum = limit_dataset_checksum(
        facts,
        as_of=AS_OF,
        actual_as_of=AS_OF,
        source="fixture",
        complete=True,
        warnings=(),
        source_revision=source_revision,
        rule_version="rules-v1",
        excluded=0,
        membership_complete=True,
        streak_complete=True,
        pool_quality={"status": "ok"},
    )
    return {
        "as_of": AS_OF,
        "actual_as_of": AS_OF,
        "source": "fixture",
        "source_revision": source_revision,
        "rule_version": "rules-v1",
        "complete": True,
        "membership_complete": True,
        "streak_complete": True,
        "pool_quality": {"status": "ok"},
        "excluded": 0,
        "warnings": (),
        "dataset_checksum": checksum,
        "fetched_at": FETCHED_AT,
    }


def test_limit_repository_writes_manifest_and_facts_in_one_contract(
    limit_connection,
) -> None:
    repository = PostgresLimitDetailRepository(limit_connection)
    facts = (_fact(),)
    manifest = _manifest(facts)

    repository.put_limit_detail(AS_OF, manifest, facts)
    detail = repository.get_limit_detail(AS_OF)

    assert isinstance(repository, LimitDetailRepository)
    assert detail is not None
    assert detail["dataset_checksum"] == manifest["dataset_checksum"]
    assert detail["membership_complete"] is True
    assert detail["facts"] == (
        replace(facts[0], dataset_checksum=manifest["dataset_checksum"]),
    )


def test_limit_repository_rolls_back_fact_and_manifest_replacement_together(
    limit_connection,
) -> None:
    repository = PostgresLimitDetailRepository(limit_connection)
    original = (_fact(),)
    repository.put_limit_detail(AS_OF, _manifest(original), original)
    limit_connection.commit()

    class FailingRepository(PostgresLimitDetailRepository):
        def _upsert_manifest(self, value):
            raise RuntimeError("manifest write failed")

    changed = (_fact(name="变更名称"),)
    with pytest.raises(RuntimeError, match="manifest write failed"):
        with limit_connection.begin():
            FailingRepository(limit_connection).put_limit_detail(
                AS_OF,
                _manifest(changed),
                changed,
            )

    detail = repository.get_limit_detail(AS_OF)
    assert detail["facts"][0].name == "示例股份"


def test_limit_repository_detects_row_and_dataset_checksum_tampering(
    limit_connection,
) -> None:
    repository = PostgresLimitDetailRepository(limit_connection)
    facts = (_fact(),)
    repository.put_limit_detail(AS_OF, _manifest(facts), facts)
    limit_connection.execute(
        text(
            "UPDATE limit_security_facts SET row_checksum = 'broken' "
            "WHERE as_of = :as_of"
        ),
        {"as_of": AS_OF},
    )
    with pytest.raises(SnapshotIntegrityError, match="fact checksum mismatch"):
        repository.get_limit_detail(AS_OF)
