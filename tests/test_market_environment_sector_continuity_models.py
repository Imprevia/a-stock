from datetime import date

import pytest

from src.market_environment.domain.models.sector_continuity import (
    BackfillRun,
    Lineage,
    MembershipInterval,
    SecurityDailyFact,
    TaxonomyRevision,
)


AS_OF = date(2026, 10, 9)


def test_only_shenwan_level_one_taxonomy_is_accepted():
    with pytest.raises(ValueError, match="Shenwan level 1"):
        TaxonomyRevision("concept-v1", "shenwan", 2, "r1", AS_OF, None, "abc")


def test_membership_interval_is_inclusive_exclusive_and_rejects_reverse_range():
    membership = MembershipInterval("920001.BJ", "801080", "sw-v1", AS_OF, date(2026, 10, 10), "r1", "abc")
    assert membership.covers(AS_OF)
    assert not membership.covers(date(2026, 10, 10))
    with pytest.raises(ValueError, match="ordered"):
        MembershipInterval("600001.SH", "801080", "sw-v1", AS_OF, AS_OF, "r1", "abc")


def test_lineage_requires_exact_date_and_daily_fact_rejects_non_finite_values():
    with pytest.raises(ValueError, match="match requested"):
        Lineage(AS_OF, date(2026, 10, 8), "fixture", "v1", 1, "abc")
    lineage = Lineage(AS_OF, AS_OF, "fixture", "v1", 1, "abc")
    with pytest.raises(ValueError, match="finite"):
        SecurityDailyFact("600001.SH", AS_OF, "sh", float("nan"), 1, 1, 1, 1, 0, True, lineage)


def test_backfill_range_is_finite_ordered_and_ends_at_as_of():
    with pytest.raises(ValueError, match="non-empty"):
        BackfillRun("run", AS_OF, (), {}, "calc-v1", "queued")
    with pytest.raises(ValueError, match="last requested"):
        BackfillRun("run", AS_OF, (date(2026, 10, 8),), {}, "calc-v1", "queued")
