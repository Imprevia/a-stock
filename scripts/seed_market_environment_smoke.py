"""Seed an isolated PostgreSQL database for the market-environment API smoke.

This is a local/test fixture helper only.  It intentionally accepts an
explicit PostgreSQL URL (or MARKET_ENVIRONMENT_TEST_DATABASE_URL), creates the
normal schema, and writes a small exact-date evidence set through the domain
snapshot store so checksums and date validation remain identical to runtime.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Allow direct execution from the repository root without requiring callers to
# remember a PYTHONPATH override.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.market_environment.database import DatabaseSettings, create_database_engine
from src.market_environment.infrastructure.legacy.snapshot_store import (
    MaterializedAggregateRecord,
    SnapshotRecord,
    SnapshotStore,
    TradingSessionRecord,
)
from src.market_environment.infrastructure.legacy.service import MarketEnvironmentService
from src.market_environment.postgres_schema import create_schema


SEED_DATES = tuple(date(2026, 9, 1) + timedelta(days=offset) for offset in range(5))
SOURCE = "local-seeded-smoke"


def _quality(as_of: date, *, observations: int, status: str = "ok") -> dict[str, Any]:
    return {
        "status": status,
        "source": SOURCE,
        "asOf": as_of.isoformat(),
        "observations": observations,
        "warnings": [],
    }


def _breadth_payload(as_of: date, index: int) -> dict[str, Any]:
    advance = 100 + index
    decline = 50 - index
    flat = 20
    valid = advance + decline + flat
    return {
        "asOf": as_of.isoformat(),
        "advanceCount": advance,
        "declineCount": decline,
        "flatCount": flat,
        "validCount": valid,
        "advanceRatio": advance / valid,
        "declineRatio": decline / valid,
        "advanceDeclineSpread": (advance - decline) / valid,
        "medianReturn": round(0.12 + index * 0.01, 4),
        "momentum": round(0.2 + index * 0.02, 4),
        "widthLabel": "偏强",
        "indexConsistent": True,
        "quality": _quality(as_of, observations=valid),
    }


def _limits_payload(as_of: date, index: int) -> dict[str, Any]:
    return {
        "asOf": as_of.isoformat(),
        "limitUpCount": 30 + index,
        "limitDownCount": 5,
        "failedLimitUpCount": 8,
        "failedLimitUpRatio": 0.2,
        "promotionRatio": 0.4,
        "maxStreak": 4,
        "quality": _quality(as_of, observations=43),
    }


def _core_payload(as_of: date) -> dict[str, Any]:
    return {
        "asOf": as_of.isoformat(),
        "generatedAt": "2026-09-05T16:30:00+08:00",
        "quality": _quality(as_of, observations=1),
        "summary": {
            "synchronization": "seeded-smoke",
            "dominantTrend": "fixture",
            "warnings": [],
            "syncPattern": {
                "code": "seeded",
                "label": "fixture",
                "score": 1,
                "evidence": [],
            },
        },
        "indices": [
            {
                "code": "000001.SH",
                "name": "上证指数",
                "representative": "上证指数",
                "changePct": 1.0,
                "close": 101.0,
                "movingAverages": {"ma5": 100.0, "ma10": 100.0, "ma20": 100.0, "ma60": 100.0},
                "rangePosition20": 0.5,
                "rangePosition60": 0.5,
                "rangePosition20Label": "中位",
                "rangePosition60Label": "中位",
                "amount": 1000.0,
                "amountRatio5": 1.0,
                "amountRatio20": 1.0,
                "trendState": "up",
                "volumePriceState": "量价齐升",
                "combination": {
                    "key": "seeded",
                    "state": "ok",
                    "matched": True,
                    "tone": "positive",
                    "evidence": [],
                    "tradingMode": "normal",
                },
                "history": [
                    {"date": (as_of - timedelta(days=1)).isoformat(), "open": 99.0, "close": 100.0, "low": 98.0, "high": 101.0, "ma5": 100.0, "ma10": 100.0, "ma20": 100.0, "ma60": 100.0, "amount": 900.0},
                    {"date": as_of.isoformat(), "open": 100.0, "close": 101.0, "low": 99.0, "high": 102.0, "ma5": 100.0, "ma10": 100.0, "ma20": 100.0, "ma60": 100.0, "amount": 1000.0},
                ],
                "dataQuality": {"source": SOURCE, "isStale": False, "warning": None},
                "dataGaps": [],
                "ma20PositionLabel": "站上",
            }
        ],
    }


def _aggregate(store: SnapshotStore, as_of: date, breadth_points: list[dict[str, Any]], limits_points: list[dict[str, Any]]) -> dict[str, Any]:
    breadth = _breadth_payload(as_of, len(breadth_points) - 1)
    limits = _limits_payload(as_of, len(limits_points) - 1)
    breadth["history"] = {"points": breadth_points}
    limits["history"] = {"points": limits_points}
    service = MarketEnvironmentService(
        provider=object(),
        snapshot_store=store,
        persistent_cache=True,
        local_reads_only=True,
        now=lambda: datetime(2026, 9, 5, 8, 30, tzinfo=timezone.utc),
    )
    try:
        core = _core_payload(as_of)
        core["requestedAsOf"] = as_of
        core["effectiveDate"] = as_of
        provider_data = service._missing_chapter_provider_data(as_of, "seeded smoke", status="missing")
        breadth["quality"] = service._quality("market-breadth", SOURCE, "ok", breadth["validCount"], as_of, [])
        limits["quality"] = service._quality("limit-pools", SOURCE, "ok", limits["quality"]["observations"], as_of, [])
        provider_data["breadth"] = breadth
        provider_data["limits"] = limits
        chapter = service._build_chapter01(core, provider_data)
        chapter["breadth"]["state"] = "available"
        chapter["limits"]["state"] = "available"
        chapter["limits"]["history"] = None
        # The legacy model requires complete promotion evidence whenever a
        # ratio is present; leave this optional field null in the seed while
        # the V2 history rows continue to exercise the numeric field.
        chapter["limits"]["promotionRatio"] = None
    finally:
        service.close()
    return {
        "asOf": as_of.isoformat(),
        "generatedAt": "2026-09-05T16:30:00+08:00",
        "summary": _core_payload(as_of)["summary"],
        "indices": _core_payload(as_of)["indices"],
        "chapter01": chapter,
        "_componentRevision": "seeded-smoke-revision",
    }


def seed(database_url: str) -> None:
    settings = DatabaseSettings(url=database_url)
    engine = create_database_engine(settings)
    try:
        create_schema(engine)
        store = SnapshotStore(database_url=database_url, initialize_schema=False)
        fetched_at = datetime(2026, 9, 5, 8, 30, tzinfo=timezone.utc)
        breadth_points: list[dict[str, Any]] = []
        limits_points: list[dict[str, Any]] = []
        for index, as_of in enumerate(SEED_DATES):
            previous = SEED_DATES[index - 1] if index else None
            store.put_trading_session(
                TradingSessionRecord(
                    as_of=as_of,
                    previous_as_of=previous,
                    actual_as_of=as_of,
                    is_session=True,
                    source=SOURCE,
                    fetched_at=fetched_at,
                )
            )
            breadth = _breadth_payload(as_of, index)
            limits = _limits_payload(as_of, index)
            breadth_points.append(breadth)
            limits_points.append(limits)
            store.put(
                SnapshotRecord(
                    dataset="breadth",
                    as_of=as_of,
                    payload=breadth,
                    source=SOURCE,
                    status="ok",
                    observations=breadth["validCount"],
                    warnings=(),
                    fetched_at=fetched_at,
                    settled=True,
                )
            )
            store.put(
                SnapshotRecord(
                    dataset="limits",
                    as_of=as_of,
                    payload=limits,
                    source=SOURCE,
                    status="ok",
                    observations=limits["quality"]["observations"],
                    warnings=(),
                    fetched_at=fetched_at,
                    settled=True,
                )
            )

        current = SEED_DATES[-1]
        core = _core_payload(current)
        store.put(
            SnapshotRecord(
                dataset="core",
                as_of=current,
                payload=core,
                source=SOURCE,
                status="ok",
                observations=1,
                warnings=(),
                fetched_at=fetched_at,
                settled=True,
            )
        )
        aggregate = _aggregate(store, current, breadth_points, limits_points)
        store.put_materialized_aggregate(
            MaterializedAggregateRecord(
                as_of=current,
                payload=aggregate,
                generated_at=datetime(2026, 9, 5, 8, 30, tzinfo=timezone.utc),
            )
        )
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("MARKET_ENVIRONMENT_TEST_DATABASE_URL", ""),
        help="isolated PostgreSQL URL; defaults to MARKET_ENVIRONMENT_TEST_DATABASE_URL",
    )
    args = parser.parse_args()
    database_url = str(args.database_url).strip()
    if not database_url:
        parser.error("--database-url or MARKET_ENVIRONMENT_TEST_DATABASE_URL is required")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        parser.error("seed requires a PostgreSQL/psycopg URL")
    seed(database_url)
    print(f"seeded {len(SEED_DATES)} exact trading days through {SEED_DATES[-1].isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
