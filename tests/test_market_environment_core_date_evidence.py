from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.market_environment.domain.policies.core_date_evidence import (
    CoreDateEvidenceError,
    validate_core_index_date,
    validate_core_payload_dates,
)


AS_OF = date(2026, 10, 16)


def _index(value=AS_OF):
    return {"code": "sh000001", "history": [{"date": value.isoformat(), "close": 3200}]}


def test_core_date_evidence_accepts_one_exact_identity() -> None:
    evidence = validate_core_payload_dates(
        {"asOf": AS_OF.isoformat(), "indices": [_index()]},
        AS_OF,
        actual_as_of=AS_OF,
        quality_as_of=AS_OF,
        effective_as_of=AS_OF,
    )
    assert evidence.actual_as_of == AS_OF
    assert evidence.index_dates == (("sh000001", AS_OF),)


@pytest.mark.parametrize(
    ("index", "match"),
    [
        ({"code": "sh000001"}, "missing"),
        ({"code": "sh000001", "history": []}, "missing"),
        ({"code": "sh000001", "history": [{"date": "bad"}]}, "malformed"),
        (_index(AS_OF - timedelta(days=1)), "does not match"),
        (_index(AS_OF + timedelta(days=1)), "does not match"),
    ],
)
def test_core_index_date_evidence_rejects_missing_malformed_prior_and_future(
    index,
    match,
) -> None:
    with pytest.raises(CoreDateEvidenceError, match=match):
        validate_core_index_date(index, AS_OF)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asOf", "2026-10-15"),
        ("quality", {"asOf": "2026-10-15"}),
        ("quality", {"effectiveAsOf": "2026-10-15"}),
    ],
)
def test_core_payload_rejects_conflicting_public_date_evidence(field, value) -> None:
    payload = {"asOf": AS_OF.isoformat(), "indices": [_index()]}
    payload[field] = value
    with pytest.raises(CoreDateEvidenceError, match="exact-date mismatch"):
        validate_core_payload_dates(payload, AS_OF, actual_as_of=AS_OF)
