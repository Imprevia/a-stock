from datetime import date, datetime, timezone
import sqlite3

import pytest

from src.market_environment.limit_facts import normalize_limit_pools, normalize_limit_rows
from src.market_environment.snapshot_store import (
    SnapshotIntegrityError,
    SnapshotStore,
    TradingSessionRecord,
    payload_checksum,
)
from src.market_environment.trading_sessions import TradingDayResolver


AS_OF = date(2026, 9, 4)
PREVIOUS = date(2026, 9, 3)
FETCHED = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)


def valid_row(code: str = "600000", market: str = "1") -> dict:
    return {
        "m": market,
        "c": code,
        "n": "样本",
        "board": "main",
        "is_st": False,
        "listing_days": 1000,
        "limit_regime": "pct:10",
        "close_price": 11.0,
        "previous_close": 10.0,
        "touched_limit_up": True,
        "closed_limit_up": True,
        "streak_days": 2,
    }


def test_normalization_requires_explicit_identity_regime_and_close_evidence() -> None:
    result = normalize_limit_rows(
        [valid_row(), {"c": "600001", "n": "ST不用于身份判断"}, {"c": "bad"}],
        as_of=AS_OF,
        actual_as_of=AS_OF,
        pool_type="limit_up",
        source="fixture",
        fetched_at=FETCHED,
    )

    assert result.complete is False
    assert result.rows[0].security_id == "SSE:600000"
    assert result.rows[0].eligible is True
    assert result.rows[1].invalid_reason == "ambiguous-identity"
    assert result.rows[2].invalid_reason == "malformed-identity"
    assert result.rows[0].row_checksum
    assert result.dataset_checksum


@pytest.mark.parametrize(
    ("identity", "exchange", "expected_identity", "expected_exchange", "expected_reason"),
    [
        ("SSE:600000", "SZSE", "SSE:600000", "SZSE", "identity-exchange-mismatch"),
        ("SH:600000", "1", "SSE:600000", "SSE", None),
        ("SSE:600000", None, "SSE:600000", "SSE", None),
    ],
)
def test_identity_exchange_evidence_must_be_consistent(
    identity: str,
    exchange: str | None,
    expected_identity: str,
    expected_exchange: str,
    expected_reason: str | None,
) -> None:
    row = valid_row()
    row.update({"security_id": identity, "exchange": exchange})
    result = normalize_limit_rows(
        [row], as_of=AS_OF, actual_as_of=AS_OF, pool_type="limit_up", source="fixture", fetched_at=FETCHED
    )

    assert result.rows[0].security_id == expected_identity
    assert result.rows[0].exchange == expected_exchange
    assert result.rows[0].eligible is (expected_reason is None)
    assert result.rows[0].invalid_reason == expected_reason
    assert result.complete is (expected_reason is None)


def test_normalization_can_verify_declared_regime_limit_without_defaulting_to_ten_percent() -> None:
    row = valid_row()
    row.pop("closed_limit_up")
    result = normalize_limit_rows(
        [row],
        as_of=AS_OF,
        actual_as_of=AS_OF.isoformat(),
        pool_type="limit_up",
        source="fixture",
        fetched_at=FETCHED,
    )
    assert result.rows[0].closed_limit_up is True
    assert result.rows[0].eligible is True

    row["limit_regime"] = "chi_next"
    result = normalize_limit_rows(
        [row], as_of=AS_OF, actual_as_of=AS_OF, pool_type="limit_up", source="fixture", fetched_at=FETCHED
    )
    assert result.rows[0].invalid_reason == "intraday-touch-not-closed"


@pytest.mark.parametrize(
    ("is_st", "declared_regime", "expected_regime", "close_price", "expected_reason"),
    [
        (False, "st", "st", 10.5, "st-regime-identity-mismatch"),
        (False, "st-5", "st", 10.5, "st-regime-identity-mismatch"),
        (True, "st", "st", 10.5, "st-security"),
        (False, "pct:5", "pct:5", 10.5, None),
    ],
)
def test_st_regime_requires_consistent_explicit_st_identity(
    is_st: bool,
    declared_regime: str,
    expected_regime: str,
    close_price: float,
    expected_reason: str | None,
) -> None:
    row = valid_row("600003")
    row.update({"is_st": is_st, "limit_regime": declared_regime, "close_price": close_price})
    kwargs = {
        "as_of": AS_OF,
        "actual_as_of": AS_OF,
        "pool_type": "limit_up",
        "source": "fixture",
        "fetched_at": FETCHED,
    }

    first = normalize_limit_rows([row], **kwargs)
    second = normalize_limit_rows([row], **kwargs)
    fact = first.rows[0]

    assert (fact.is_st, fact.limit_regime) == (is_st, expected_regime)
    assert fact.invalid_reason == expected_reason
    assert fact.eligible is (expected_reason is None)
    assert first.complete is (expected_reason is None)
    assert first.excluded == int(expected_reason is not None)
    assert fact.row_checksum == second.rows[0].row_checksum
    assert first.dataset_checksum == second.dataset_checksum
    if expected_reason == "st-regime-identity-mismatch":
        consistent = normalize_limit_rows([{**row, "is_st": True}], **kwargs)
        assert fact.row_checksum != consistent.rows[0].row_checksum
        assert first.dataset_checksum != consistent.dataset_checksum


@pytest.mark.parametrize(
    ("mutations", "reason"),
    [
        ({"is_st": True, "limit_regime": "pct:5"}, "st-security"),
        ({"listing_days": 3}, "ipo-window"),
        ({"limit_regime": "main", "closed_limit_up": None, "previous_close": None}, "missing-close-limit-status"),
        ({"closed_limit_up": False, "touched_limit_up": True}, "intraday-touch-not-closed"),
        ({"close_price": None}, "missing-close"),
        ({"board": "unknown"}, "missing-board"),
    ],
)
def test_invalid_limit_rows_are_quarantined_with_stable_reasons(mutations, reason) -> None:
    row = valid_row()
    row.update(mutations)
    result = normalize_limit_rows(
        [row], as_of=AS_OF, actual_as_of=AS_OF, pool_type="limit_up", source="fixture", fetched_at=FETCHED
    )
    assert result.complete is False
    assert result.rows[0].eligible is False
    assert result.rows[0].invalid_reason == reason


def test_duplicate_and_cross_pool_membership_are_not_merged() -> None:
    duplicate = normalize_limit_rows(
        [valid_row(), valid_row()],
        as_of=AS_OF,
        actual_as_of=AS_OF,
        pool_type="limit_up",
        source="fixture",
        fetched_at=FETCHED,
    )
    assert duplicate.duplicate_count == 1
    assert len(duplicate.rows) == 1
    assert all(row.invalid_reason == "duplicate-security" for row in duplicate.rows)
    pools = normalize_limit_pools(
        {"limit_up": [valid_row()], "failed_limit_up": [{**valid_row(), "closed_limit_up": False}] , "limit_down": []},
        as_of=AS_OF,
        actual_as_of=AS_OF,
        source="fixture",
        fetched_at=FETCHED,
    )
    assert pools.complete is False
    assert {row.invalid_reason for row in pools.rows if row.security_id == "SSE:600000"} == {
        "conflicting-pool-membership"
    }


def test_normalized_duplicate_dataset_is_persistable_without_duplicate_members(tmp_path) -> None:
    result = normalize_limit_rows(
        [valid_row(), valid_row()],
        as_of=AS_OF,
        actual_as_of=AS_OF,
        pool_type="limit_up",
        source="fixture",
        fetched_at=FETCHED,
    )
    store = SnapshotStore(tmp_path / "duplicate.sqlite3")
    store.put_limit_security_facts(
        AS_OF,
        list(result.rows),
        actual_as_of=AS_OF,
        source="fixture",
        complete=result.complete,
        warnings=result.warnings,
        dataset_checksum=result.dataset_checksum,
    )
    assert len(store.get_limit_security_facts(AS_OF)) == 1


def test_storage_migration_is_additive_idempotent_and_preserves_v1(tmp_path) -> None:
    path = tmp_path / "v1.sqlite3"
    payload = '{"value":3}'
    import hashlib

    checksum = hashlib.sha256(payload.encode()).hexdigest()
    aggregate_payload = {"asOf": AS_OF.isoformat(), "legacy": True}
    aggregate_json = '{"asOf":"2026-09-04","legacy":true}'
    aggregate_checksum = payload_checksum(aggregate_payload)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE snapshot_entries (
                dataset TEXT NOT NULL, as_of TEXT NOT NULL, payload_json TEXT NOT NULL,
                source TEXT NOT NULL, status TEXT NOT NULL, observations INTEGER NOT NULL,
                warnings_json TEXT NOT NULL, fetched_at TEXT NOT NULL, settled INTEGER NOT NULL,
                schema_version INTEGER NOT NULL, checksum TEXT NOT NULL, refresh_warning TEXT,
                PRIMARY KEY(dataset, as_of)
            );
            CREATE TABLE materialized_market_environment (
                as_of TEXT PRIMARY KEY, payload_json TEXT NOT NULL, generated_at TEXT NOT NULL, checksum TEXT NOT NULL
            );
            PRAGMA user_version = 1;
            """
        )
        connection.execute(
            "INSERT INTO snapshot_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("limits", AS_OF.isoformat(), payload, "fixture", "ok", 1, "[]", FETCHED.isoformat(), 1, 1, checksum, None),
        )
        connection.execute(
            "INSERT INTO materialized_market_environment VALUES (?, ?, ?, ?)",
            (AS_OF.isoformat(), aggregate_json, FETCHED.isoformat(), aggregate_checksum),
        )
    first = SnapshotStore(path)
    before = first.get("limits", AS_OF)
    before_aggregate = first.get_materialized_aggregate(AS_OF)
    assert before_aggregate is not None
    assert before_aggregate.payload == aggregate_payload
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute("SELECT count(*) FROM snapshot_entries").fetchone()[0] == 1
    second = SnapshotStore(path)
    assert second.migration_versions() == (1, 2, 3, 4)
    assert second.get("limits", AS_OF) == before
    assert second.get_materialized_aggregate(AS_OF) == before_aggregate
    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"schema_migrations", "trading_sessions", "limit_security_facts", "limit_security_datasets"} <= tables
    assert "limit_security_facts_eligible_idx" in indexes


def test_session_resolver_uses_only_exact_persisted_pointer(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "sessions.sqlite3")
    store.put_trading_session(TradingSessionRecord(AS_OF, PREVIOUS, True, "fixture", actual_as_of=AS_OF, fetched_at=FETCHED))
    store.put_trading_session(TradingSessionRecord(PREVIOUS, None, True, "fixture", actual_as_of=PREVIOUS, fetched_at=FETCHED))
    resolved = TradingDayResolver(store).resolve(AS_OF)
    assert (resolved.status, resolved.previous_as_of) == ("ok", PREVIOUS)
    assert TradingDayResolver(store).resolve(date(2026, 9, 5)).reason == "requested-date-is-weekend"
    missing = TradingDayResolver(store).resolve(date(2026, 9, 8))
    assert missing.status == "insufficient"
    assert missing.reason == "missing-session-evidence"

    missing_previous = date(2026, 9, 7)
    store.put_trading_session(TradingSessionRecord(date(2026, 9, 8), missing_previous, True, "fixture", actual_as_of=date(2026, 9, 8), fetched_at=FETCHED))
    assert TradingDayResolver(store).resolve(date(2026, 9, 8)).reason == "previous-session-unavailable"


def test_session_resolver_rejects_missing_or_mismatched_actual_dates(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "date-evidence.sqlite3")
    store.put_trading_session(
        TradingSessionRecord(AS_OF, PREVIOUS, True, "fixture", actual_as_of=AS_OF, fetched_at=FETCHED)
    )
    assert (
        TradingDayResolver(store).resolve(AS_OF, actual_as_of=date(2026, 9, 3)).reason
        == "provider-date-mismatch"
    )
    assert (
        TradingDayResolver(store).resolve(AS_OF, actual_as_of="not-a-date").reason
        == "missing-or-invalid-actual-session-date"
    )

    class MissingActualStore:
        def get_trading_session(self, as_of):
            return TradingSessionRecord(as_of, None, True, "fixture", actual_as_of=None, fetched_at=FETCHED)

    assert TradingDayResolver(MissingActualStore()).resolve(AS_OF).reason == "missing-or-invalid-actual-session-date"


def test_limit_fact_row_and_dataset_checksums_round_trip(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "facts.sqlite3")
    result = normalize_limit_rows(
        [valid_row()],
        as_of=AS_OF,
        actual_as_of=AS_OF,
        pool_type="limit_up",
        source="fixture",
        source_revision="fixture-v1",
        rule_version="limits-promotion-v1",
        fetched_at=FETCHED,
    )
    expected_checksum = result.dataset_checksum
    checksum = store.put_limit_security_facts(
        AS_OF,
        list(result.rows),
        actual_as_of=AS_OF,
        source="fixture",
        source_revision="fixture-v1",
        rule_version="limits-promotion-v1",
        complete=result.complete,
        warnings=result.warnings,
        dataset_checksum=result.dataset_checksum,
    )
    assert checksum == expected_checksum
    assert len(store.get_limit_security_facts(AS_OF)) == 1
    # Same logical write is idempotent and keeps one composite-key row.
    assert store.put_limit_security_facts(
        AS_OF,
        list(result.rows),
        actual_as_of=AS_OF,
        source="fixture",
        source_revision="fixture-v1",
        rule_version="limits-promotion-v1",
        complete=result.complete,
        warnings=result.warnings,
    ) == checksum
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT count(*) FROM limit_security_facts").fetchone()[0] == 1
        connection.execute("UPDATE limit_security_facts SET close_price = 99")
    with pytest.raises(SnapshotIntegrityError, match="checksum mismatch"):
        store.get_limit_security_facts(AS_OF)
