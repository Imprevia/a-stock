from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, text

from src.market_environment.application.ports.v2_market_data import V2Resource
from src.market_environment.infrastructure.persistence.postgres.v2_market_data import (
    PostgresV2MarketDataReadAdapter,
)
from src.market_environment.snapshot_store import SnapshotIntegrityError, payload_checksum


AS_OF = date(2026, 9, 5)
DATES = tuple(date(2026, 9, day) for day in range(1, 6))


class _HistoryAdapter(PostgresV2MarketDataReadAdapter):
    def _list_metadata(
        self,
        as_of: date,
        *,
        snapshot_dataset: str,
        public_dataset: str,
    ) -> V2Resource:
        return V2Resource(
            as_of,
            "2026-09-05T16:00:00+08:00",
            "postgres-history-r1",
            {"dataset": public_dataset, "status": "ok"},
            {},
        )


@pytest.fixture
def postgres_history_adapter():
    url = os.getenv("MARKET_ENVIRONMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "set MARKET_ENVIRONMENT_TEST_DATABASE_URL to an isolated PostgreSQL database"
        )
    engine = create_engine(url, future=True)
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text(
                """CREATE TEMP TABLE snapshot_entries (
                    dataset TEXT NOT NULL,
                    as_of DATE NOT NULL,
                    payload_json JSONB NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    observations INTEGER NOT NULL,
                    warnings_json JSONB NOT NULL,
                    fetched_at TIMESTAMPTZ NOT NULL,
                    settled INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    refresh_warning TEXT,
                    PRIMARY KEY(dataset, as_of)
                ) ON COMMIT DROP"""
            )
        )
        connection.execute(
            text(
                """CREATE TEMP TABLE trading_sessions (
                    as_of DATE PRIMARY KEY,
                    is_session INTEGER NOT NULL
                ) ON COMMIT DROP"""
            )
        )
        for index, as_of in enumerate(DATES, start=1):
            breadth_payload = {
                "asOf": as_of.isoformat(),
                "advanceCount": index,
                "declineCount": 10 - index,
            }
            connection.execute(
                text(
                    """INSERT INTO snapshot_entries(
                        dataset,as_of,payload_json,source,status,observations,
                        warnings_json,fetched_at,settled,schema_version,checksum,refresh_warning
                    ) VALUES (
                        :dataset,:as_of,CAST(:payload AS JSONB),'fixture','success',1,
                        '[]'::jsonb,:fetched_at,1,1,:checksum,NULL
                    )"""
                ),
                {
                    "dataset": "breadth",
                    "as_of": as_of,
                    "payload": json.dumps(breadth_payload),
                    "fetched_at": datetime.now(timezone.utc),
                    "checksum": payload_checksum(breadth_payload),
                },
            )
            limits_payload = {
                "asOf": as_of.isoformat(),
                "limitUpCount": index,
                "limitDownCount": index - 1,
            }
            connection.execute(
                text(
                    """INSERT INTO snapshot_entries(
                        dataset,as_of,payload_json,source,status,observations,
                        warnings_json,fetched_at,settled,schema_version,checksum,refresh_warning
                    ) VALUES (
                        :dataset,:as_of,CAST(:payload AS JSONB),'fixture','success',1,
                        '[]'::jsonb,:fetched_at,1,1,:checksum,NULL
                    )"""
                ),
                {
                    "dataset": "limits",
                    "as_of": as_of,
                    "payload": json.dumps(limits_payload),
                    "fetched_at": datetime.now(timezone.utc),
                    "checksum": payload_checksum(limits_payload),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO trading_sessions(as_of,is_session) VALUES (:as_of,1)"
                ),
                {"as_of": as_of},
            )
        yield _HistoryAdapter(connection)
        transaction.rollback()
    engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize("resource", ["breadth", "limits"])
@pytest.mark.parametrize(
    ("start_date", "end_date", "expected"),
    [
        (None, None, DATES),
        (DATES[2], None, DATES[2:]),
        (None, DATES[2], DATES[:3]),
        (DATES[1], DATES[3], DATES[1:4]),
        (date(2026, 8, 1), date(2026, 8, 31), ()),
    ],
)
def test_real_postgres_history_date_filters_are_stable(
    postgres_history_adapter,
    resource: str,
    start_date: date | None,
    end_date: date | None,
    expected: tuple[date, ...],
) -> None:
    method = getattr(postgres_history_adapter, f"{resource}_history")

    page = method(
        AS_OF,
        start_date=start_date,
        end_date=end_date,
        after=None,
        limit=20,
    )

    assert page is not None
    assert tuple(date.fromisoformat(row["asOf"]) for row in page.resource.data) == expected
    assert page.next_sort_key is None
    if not expected:
        assert page.resource.quality["status"] == "insufficient"


@pytest.mark.integration
@pytest.mark.parametrize("resource", ["breadth", "limits"])
def test_real_postgres_history_continuation_is_bounded_ordered_and_duplicate_free(
    postgres_history_adapter,
    resource: str,
) -> None:
    method = getattr(postgres_history_adapter, f"{resource}_history")
    seen: list[str] = []
    after = None

    while True:
        page = method(
            AS_OF,
            start_date=None,
            end_date=None,
            after=after,
            limit=2,
        )
        assert page is not None
        values = [str(row["asOf"]) for row in page.resource.data]
        assert len(values) <= 2
        assert values == sorted(values)
        assert not set(values).intersection(seen)
        seen.extend(values)
        if page.next_sort_key is None:
            break
        after = page.next_sort_key

    assert seen == [value.isoformat() for value in DATES]


@pytest.mark.integration
@pytest.mark.parametrize("resource", ["breadth", "limits"])
def test_real_postgres_history_fails_closed_on_invalid_stored_evidence(
    postgres_history_adapter,
    resource: str,
) -> None:
    postgres_history_adapter.connection.execute(
        text(
            "UPDATE snapshot_entries SET checksum='invalid' "
            "WHERE dataset=:dataset AND as_of=:as_of"
        ),
        {"dataset": resource, "as_of": DATES[2]},
    )
    method = getattr(postgres_history_adapter, f"{resource}_history")

    with pytest.raises(SnapshotIntegrityError, match="snapshot checksum mismatch"):
        method(
            AS_OF,
            start_date=None,
            end_date=None,
            after=None,
            limit=20,
        )
