from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.market_environment.limit_facts import normalize_limit_pools


FIXTURE_PATH = Path(__file__).parent / "fixtures/market-environment/limit-pools-matrix.json"
AS_OF = date(2026, 9, 4)
FETCHED = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def matrix() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("case_name", "expected_complete", "expected_min_excluded"),
    [
        ("complete", True, 0),
        ("empty", True, 0),
        ("partial", False, 1),
        ("allFail", False, 3),
        ("nonMappingPartial", False, 1),
        ("nonMappingAllFail", False, 3),
        ("duplicate", False, 1),
        ("identityExchangeEvidence", False, 1),
        ("regimeAndEligibilityExclusions", False, 4),
        ("dateMismatch", False, 1),
    ],
)
def test_fixed_limit_pool_matrix_is_deterministic_and_network_free(
    matrix: dict, case_name: str, expected_complete: bool, expected_min_excluded: int
) -> None:
    case = matrix["cases"][case_name]
    kwargs = {
        "as_of": AS_OF,
        "actual_as_of": date.fromisoformat(case["actualAsOf"]),
        "source": matrix["source"],
        "fetched_at": FETCHED,
        "source_revision": "matrix-v1",
        "rule_version": "limits-promotion-v1",
    }
    first = normalize_limit_pools(case["pools"], **kwargs)
    second = normalize_limit_pools(case["pools"], **kwargs)

    assert first.complete is expected_complete
    assert first.excluded >= expected_min_excluded
    assert first.dataset_checksum == second.dataset_checksum
    assert tuple(row.row_checksum for row in first.rows) == tuple(row.row_checksum for row in second.rows)
    assert all(row.fetched_at == FETCHED for row in first.rows)


def test_fixed_matrix_keeps_board_and_exclusion_reasons_explicit(matrix: dict) -> None:
    result = normalize_limit_pools(
        matrix["cases"]["complete"]["pools"],
        as_of=AS_OF,
        actual_as_of=AS_OF,
        source=matrix["source"],
        fetched_at=FETCHED,
    )
    eligible = {row.security_id: row for row in result.rows if row.eligible}
    assert {eligible["SSE:600000"].board, eligible["SZSE:300000"].board, eligible["SSE:688000"].board} == {
        "main",
        "chi_next",
        "star",
    }
    assert {
        eligible["SSE:600000"].limit_regime,
        eligible["SZSE:300000"].limit_regime,
        eligible["SSE:688000"].limit_regime,
    } == {"main", "chi_next", "star"}

    excluded = normalize_limit_pools(
        matrix["cases"]["regimeAndEligibilityExclusions"]["pools"],
        as_of=AS_OF,
        actual_as_of=AS_OF,
        source=matrix["source"],
        fetched_at=FETCHED,
    )
    assert {row.invalid_reason for row in excluded.rows} >= {
        "st-security",
        "st-regime-identity-mismatch",
        "ipo-window",
        "intraday-touch-not-closed",
    }
    st_conflict = next(row for row in excluded.rows if row.code == "600031")
    assert (st_conflict.is_st, st_conflict.limit_regime) == (False, "st")
    assert st_conflict.eligible is False
    assert excluded.complete is False


def test_fixed_matrix_preserves_identity_exchange_conflict_evidence(matrix: dict) -> None:
    result = normalize_limit_pools(
        matrix["cases"]["identityExchangeEvidence"]["pools"],
        as_of=AS_OF,
        actual_as_of=AS_OF,
        source=matrix["source"],
        fetched_at=FETCHED,
    )
    by_code = {row.code: row for row in result.rows}

    conflict = by_code["600050"]
    assert (conflict.security_id, conflict.exchange) == ("SSE:600050", "SZSE")
    assert conflict.eligible is False
    assert conflict.invalid_reason == "identity-exchange-mismatch"
    assert result.complete is False

    consistent = by_code["600051"]
    assert (consistent.security_id, consistent.exchange, consistent.eligible) == ("SSE:600051", "SSE", True)
    missing_explicit_exchange = by_code["600052"]
    assert (
        missing_explicit_exchange.security_id,
        missing_explicit_exchange.exchange,
        missing_explicit_exchange.eligible,
    ) == ("SSE:600052", "SSE", True)


def test_fixed_matrix_preserves_non_mapping_reasons_and_checksums(matrix: dict) -> None:
    case = matrix["cases"]["nonMappingAllFail"]
    kwargs = {
        "as_of": AS_OF,
        "actual_as_of": AS_OF,
        "source": matrix["source"],
        "fetched_at": FETCHED,
        "source_revision": "matrix-v1",
        "rule_version": "limits-promotion-v1",
    }
    first = normalize_limit_pools(case["pools"], **kwargs)
    second = normalize_limit_pools(case["pools"], **kwargs)
    corrected = normalize_limit_pools(
        {"limit_up": [], "failed_limit_up": [], "limit_down": []},
        **kwargs,
    )

    assert first.complete is False
    assert first.excluded == 3
    assert {row.invalid_reason for row in first.rows} == {"malformed-row"}
    assert len({row.security_id for row in first.rows}) == 3
    assert sum("malformed-row" in warning for warning in first.warnings) == 3
    assert first.dataset_checksum == second.dataset_checksum
    assert tuple(row.row_checksum for row in first.rows) == tuple(row.row_checksum for row in second.rows)
    assert first.dataset_checksum != corrected.dataset_checksum
