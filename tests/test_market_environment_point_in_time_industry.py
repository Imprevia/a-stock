from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from src.market_environment.domain.analysis.point_in_time_industry import (
    aggregate_point_in_time_industries,
    build_equal_weight_benchmark,
    build_internal_structure,
    canonical_security_id,
    resolve_memberships,
)
from src.market_environment.domain.models import (
    Lineage,
    MembershipInterval,
    SecurityDailyFact,
)
from src.market_environment.infrastructure.providers.tdx.daily_package import (
    TDXDailyPackageRow,
)
from src.market_environment.infrastructure.providers.tdx.sector_facts import (
    attach_adjusted_prices,
    build_tdx_security_facts,
)


AS_OF = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 8, tzinfo=timezone.utc)


def _lineage(**changes) -> Lineage:
    values = {
        "requested_as_of": AS_OF,
        "actual_as_of": AS_OF,
        "source": "fixture",
        "source_revision": "facts-v1",
        "schema_version": 1,
        "checksum": "a" * 64,
        "data_version": "data-v1",
        "classification_version": "sw-v1",
        "membership_version": "members-v1",
        "universe_version": "ordinary-a-share-v1",
        "adjustment_version": "qfq-v1",
        "benchmark_version": "ordinary-a-share-equal-weight-v1",
        "calculation_version": "calc-v1",
        "fetched_at": NOW,
        "observation_count": 1,
    }
    values.update(changes)
    return Lineage(**values)


def _fact(security_id: str, market: str, adjusted: float, previous: float, amount: float | None):
    return SecurityDailyFact(
        security_id=security_id,
        as_of=AS_OF,
        market=market,
        original_close=10,
        previous_close=9.5,
        adjusted_close=adjusted,
        adjusted_previous_close=previous,
        amount=amount,
        volume=100,
        change_pct=None,
        eligible=True,
        lineage=_lineage(checksum=(security_id[-1] * 64)),
    )


def test_canonical_identity_requires_exchange_and_bj_migration_alias_is_explicit():
    assert canonical_security_id("600000.SH") == "sh.600000"
    assert canonical_security_id("920001", "bj") == "bj.920001"
    assert canonical_security_id(
        "bj.830001", aliases={"bj.830001": "security:stable-1"}
    ) == "security:stable-1"
    with pytest.raises(ValueError, match="explicit"):
        canonical_security_id("830001")


def test_membership_resolution_uses_inclusive_exclusive_boundaries_without_future_fill():
    old = MembershipInterval("sh.600000", "A", "sw-v1", date(2026, 1, 1), AS_OF, "m1", "c1")
    current = MembershipInterval("sh.600000", "B", "sw-v1", AS_OF, None, "m1", "c2")
    future = MembershipInterval("sz.000001", "C", "sw-v1", date(2026, 10, 10), None, "m1", "c3")
    resolved = resolve_memberships(
        ["sh.600000", "sz.000001"], (old, current, future), AS_OF, taxonomy_version="sw-v1"
    )
    assert resolved.assignments["sh.600000"].industry_id == "B"
    assert resolved.unmapped == ("sz.000001",)


def test_duplicate_active_membership_is_conflict_and_not_assigned():
    memberships = (
        MembershipInterval("sh.600000", "A", "sw-v1", date(2026, 1, 1), None, "m1", "c1"),
        MembershipInterval("sh.600000", "B", "sw-v1", date(2026, 2, 1), None, "m1", "c2"),
    )
    result = resolve_memberships(["sh.600000"], memberships, AS_OF, taxonomy_version="sw-v1")
    assert result.assignments == {}
    assert tuple(item.industry_id for item in result.conflicts["sh.600000"]) == ("A", "B")


def test_tdx_facts_keep_raw_amount_and_adjustment_revision_independent():
    raw = TDXDailyPackageRow(
        code="920001", date=AS_OF, close=10.0, amount=1234.0,
        previous_close=9.0, change_pct=11.11, market="bj", open=9.5,
        high=10.2, low=9.4, volume=100,
    )
    facts, audit = build_tdx_security_facts(
        (raw,), as_of=AS_OF, source_revision="tdx-v1",
        package_checksum="package-checksum", fetched_at=NOW,
        require_complete_universe=False,
    )
    assert audit.retained_by_market["bj"] == 1
    assert facts[0].amount == 1234.0
    assert facts[0].adjusted_close is None

    adjusted = attach_adjusted_prices(
        facts, {"bj.920001": (5.0, 4.5)},
        adjustment_revision="qfq-v1", evidence_checksum="adjustment-checksum",
    )
    assert adjusted[0].amount == 1234.0
    assert adjusted[0].volume == 100
    assert adjusted[0].adjusted_close == 5.0
    assert adjusted[0].adjusted_previous_close == 4.5


def test_amount_and_adjusted_price_degrade_independently():
    raw = TDXDailyPackageRow(
        code="600001", date=AS_OF, close=10.0, amount=None,
        previous_close=9.0, market="sh", open=9.5, high=10.2, low=9.4, volume=100,
    )
    facts, _ = build_tdx_security_facts(
        (raw,), as_of=AS_OF, source_revision="tdx-v1",
        package_checksum="package-checksum", fetched_at=NOW,
        require_complete_universe=False,
    )
    adjusted = attach_adjusted_prices(
        facts, {"sh.600001": (10.0, 9.0)},
        adjustment_revision="qfq-v1", evidence_checksum="adj",
    )
    assert adjusted[0].amount is None
    benchmark = build_equal_weight_benchmark(adjusted, as_of=AS_OF, lineage=_lineage())
    assert benchmark.return_value == pytest.approx(1 / 9)

    price_missing = TDXDailyPackageRow(
        code="600002", date=AS_OF, close=None, amount=999.0,
        previous_close=None, market="sh", volume=50,
    )
    amount_only, _ = build_tdx_security_facts(
        (price_missing,), as_of=AS_OF, source_revision="tdx-v1",
        package_checksum="package-checksum", fetched_at=NOW,
        require_complete_universe=False,
    )
    assert amount_only[0].eligible is True
    assert amount_only[0].amount == 999.0
    assert amount_only[0].lineage.quality_status == "partial"


def test_exact_date_aggregation_is_mutually_exclusive_and_ignores_future_facts():
    facts = (
        _fact("sh.600000", "sh", 11, 10, 100),
        _fact("sz.000001", "sz", 9, 10, 200),
        replace(
            _fact("bj.920001", "bj", 20, 10, 999),
            as_of=date(2026, 10, 10),
            lineage=_lineage(
                requested_as_of=date(2026, 10, 10),
                actual_as_of=date(2026, 10, 10),
            ),
        ),
    )
    memberships = (
        MembershipInterval("sh.600000", "A", "sw-v1", date(2026, 1, 1), None, "m1", "c1"),
        MembershipInterval("sz.000001", "B", "sw-v1", date(2026, 1, 1), None, "m1", "c2"),
    )
    aggregates, resolution, market_amount = aggregate_point_in_time_industries(
        facts, memberships, as_of=AS_OF, taxonomy_version="sw-v1",
        lineage_by_industry={"A": _lineage(), "B": _lineage()},
    )
    assert resolution.conflicts == {}
    assert [item.industry_id for item in aggregates] == ["A", "B"]
    assert market_amount == 300
    assert sum(item.original_amount or 0 for item in aggregates) == market_amount
    structure = build_internal_structure(facts[:2], as_of=AS_OF)
    assert structure.top_by_turnover[0]["securityId"] == "sz.000001"
    assert structure.top_security_turnover_contribution == pytest.approx(2 / 3)
    assert structure.diffusion_ratio == 0.5
