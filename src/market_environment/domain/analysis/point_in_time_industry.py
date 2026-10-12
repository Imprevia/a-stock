"""Exact-date identity, membership, benchmark and industry aggregation helpers."""

from __future__ import annotations

import math
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from ..models import (
    BenchmarkFact,
    IndustryAggregate,
    InternalStructure,
    Lineage,
    MembershipInterval,
    SecurityDailyFact,
)


_CODE = re.compile(r"^[0-9]{6}$")
_MARKETS = {"sh", "sz", "bj"}


def canonical_security_id(
    code: str,
    market: str | None = None,
    *,
    aliases: Mapping[str, str] | None = None,
) -> str:
    """Normalize an exchange-qualified A-share identity without guessing aliases.

    Beijing code migrations (for example an old ``83xxxx`` code moving to a
    ``920xxx`` code) require an explicit, versioned alias map.  This prevents a
    code-pattern heuristic from merging distinct historical securities.
    """

    raw = str(code).strip().lower()
    aliases = aliases or {}
    if raw in aliases:
        value = str(aliases[raw]).strip().lower()
        if not value:
            raise ValueError("canonical security alias must not be empty")
        return value
    parsed_market = str(market or "").strip().lower()
    digits = raw
    if "." in raw:
        left, right = raw.split(".", 1)
        if left in _MARKETS:
            parsed_market, digits = left, right
        elif right in _MARKETS:
            parsed_market, digits = right, left
    elif len(raw) == 8 and raw[:2] in _MARKETS:
        parsed_market, digits = raw[:2], raw[2:]
    if parsed_market not in _MARKETS or not _CODE.fullmatch(digits):
        raise ValueError("security identity requires an explicit sh/sz/bj market and six-digit code")
    candidate = f"{parsed_market}.{digits}"
    return str(aliases.get(candidate, candidate)).strip().lower()


@dataclass(frozen=True, slots=True)
class MembershipResolution:
    assignments: Mapping[str, MembershipInterval]
    unmapped: tuple[str, ...]
    conflicts: Mapping[str, tuple[MembershipInterval, ...]]


def resolve_memberships(
    security_ids: Sequence[str],
    intervals: Sequence[MembershipInterval],
    as_of: date,
    *,
    taxonomy_version: str,
) -> MembershipResolution:
    """Resolve inclusive/exclusive intervals for one exact date.

    Later intervals are ignored rather than used as current-membership
    substitutes.  Multiple active assignments remain explicit conflicts.
    """

    active: dict[str, list[MembershipInterval]] = defaultdict(list)
    for interval in intervals:
        if interval.taxonomy_version == taxonomy_version and interval.covers(as_of):
            active[interval.security_id].append(interval)
    assignments: dict[str, MembershipInterval] = {}
    unmapped: list[str] = []
    conflicts: dict[str, tuple[MembershipInterval, ...]] = {}
    for security_id in sorted(set(security_ids)):
        matches = sorted(
            active.get(security_id, ()),
            key=lambda item: (item.industry_id, item.valid_from, item.source_revision, item.evidence_checksum),
        )
        if not matches:
            unmapped.append(security_id)
        elif len(matches) == 1:
            assignments[security_id] = matches[0]
        else:
            conflicts[security_id] = tuple(matches)
    return MembershipResolution(assignments, tuple(unmapped), conflicts)


def _valid_return(fact: SecurityDailyFact) -> float | None:
    if (
        not fact.eligible
        or fact.adjusted_close is None
        or fact.adjusted_previous_close is None
    ):
        return None
    if fact.adjusted_previous_close <= 0:
        return None
    value = fact.adjusted_close / fact.adjusted_previous_close - 1.0
    return value if math.isfinite(value) else None


def build_equal_weight_benchmark(
    facts: Sequence[SecurityDailyFact],
    *,
    as_of: date,
    lineage: Lineage,
) -> BenchmarkFact:
    exact = [fact for fact in facts if fact.as_of == as_of and fact.lineage.actual_as_of == as_of]
    returns = [value for fact in exact if (value := _valid_return(fact)) is not None]
    return BenchmarkFact(
        benchmark_id="ordinary-a-share-equal-weight-v1",
        as_of=as_of,
        return_value=sum(returns) / len(returns) if returns else None,
        eligible_count=len(returns),
        excluded_count=len(exact) - len(returns),
        session_dates=(as_of,),
        lineage=lineage,
    )


def build_internal_structure(
    facts: Sequence[SecurityDailyFact], *, as_of: date, limit: int = 5
) -> InternalStructure:
    """Build exact-date measurable structure facts without assigning roles."""

    exact = [
        fact
        for fact in facts
        if fact.as_of == as_of and fact.lineage.actual_as_of == as_of and fact.eligible
    ]
    returns = [(fact, _valid_return(fact)) for fact in exact]
    valid_returns = [(fact, value) for fact, value in returns if value is not None]
    advancing = sum(value > 0 for _, value in valid_returns)
    declining = sum(value < 0 for _, value in valid_returns)
    flat = sum(value == 0 for _, value in valid_returns)
    by_turnover = sorted(
        ((fact, fact.amount) for fact in exact if fact.amount is not None),
        key=lambda item: (-float(item[1]), item[0].security_id),
    )
    by_return = sorted(
        valid_returns, key=lambda item: (-float(item[1]), item[0].security_id)
    )
    total_amount = sum(float(value) for _, value in by_turnover)
    top_contribution = (
        float(by_turnover[0][1]) / total_amount if by_turnover and total_amount > 0 else None
    )
    return InternalStructure(
        effective_member_count=len(exact),
        advancing_count=advancing,
        declining_count=declining,
        flat_count=flat,
        limit_up_count=None,
        limit_down_count=None,
        top_by_turnover=tuple(
            {"securityId": fact.security_id, "amount": amount}
            for fact, amount in by_turnover[:limit]
        ),
        top_by_return=tuple(
            {"securityId": fact.security_id, "return": value}
            for fact, value in by_return[:limit]
        ),
        top_security_turnover_contribution=top_contribution,
        diffusion_ratio=advancing / len(valid_returns) if valid_returns else None,
    )


def aggregate_point_in_time_industries(
    facts: Sequence[SecurityDailyFact],
    intervals: Sequence[MembershipInterval],
    *,
    as_of: date,
    taxonomy_version: str,
    lineage_by_industry: Mapping[str, Lineage],
    ma20_by_security: Mapping[str, float | None] | None = None,
) -> tuple[tuple[IndustryAggregate, ...], MembershipResolution, float | None]:
    """Aggregate mutually exclusive exact-date facts and reconcile market amount."""

    exact = [fact for fact in facts if fact.as_of == as_of and fact.lineage.actual_as_of == as_of]
    resolution = resolve_memberships(
        [fact.security_id for fact in exact], intervals, as_of, taxonomy_version=taxonomy_version
    )
    grouped: dict[str, list[SecurityDailyFact]] = defaultdict(list)
    for fact in exact:
        membership = resolution.assignments.get(fact.security_id)
        if membership is not None:
            grouped[membership.industry_id].append(fact)
    ma20_by_security = ma20_by_security or {}
    results: list[IndustryAggregate] = []
    for industry_id in sorted(grouped):
        industry_facts = grouped[industry_id]
        returns = [_valid_return(fact) for fact in industry_facts]
        valid_returns = [value for value in returns if value is not None]
        amounts = [fact.amount for fact in industry_facts if fact.eligible and fact.amount is not None]
        eligible_ma = above_ma = 0
        advance = decline = flat = 0
        excluded: dict[str, int] = defaultdict(int)
        for fact, security_return in zip(industry_facts, returns, strict=True):
            if security_return is None:
                excluded["adjusted-return-missing"] += 1
            elif security_return > 0:
                advance += 1
            elif security_return < 0:
                decline += 1
            else:
                flat += 1
            if fact.amount is None:
                excluded["amount-missing"] += 1
            ma20 = ma20_by_security.get(fact.security_id)
            if fact.adjusted_close is not None and ma20 is not None and math.isfinite(float(ma20)):
                eligible_ma += 1
                above_ma += fact.adjusted_close > float(ma20)
            else:
                excluded["ma20-missing"] += 1
        input_checksum = hashlib.sha256(
            json.dumps(
                [
                    {
                        "securityId": fact.security_id,
                        "amount": fact.amount,
                        "adjustedClose": fact.adjusted_close,
                        "adjustedPreviousClose": fact.adjusted_previous_close,
                        "lineage": fact.lineage.checksum,
                    }
                    for fact in sorted(industry_facts, key=lambda item: item.security_id)
                ],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        results.append(
            IndustryAggregate(
                industry_id=industry_id,
                as_of=as_of,
                member_count=len(industry_facts),
                eligible_return_count=len(valid_returns),
                eligible_amount_count=len(amounts),
                eligible_ma20_count=eligible_ma,
                industry_return=sum(valid_returns) / len(valid_returns) if valid_returns else None,
                original_amount=sum(amounts) if amounts else None,
                breadth_ratio=above_ma / eligible_ma if eligible_ma else None,
                advance_count=advance,
                decline_count=decline,
                flat_count=flat,
                limit_up_count=None,
                limit_down_count=None,
                excluded_reasons=dict(excluded),
                lineage=lineage_by_industry[industry_id],
                input_checksum=input_checksum,
            )
        )
    market_amounts = [fact.amount for fact in exact if fact.eligible and fact.amount is not None]
    market_amount = sum(market_amounts) if market_amounts else None
    return tuple(results), resolution, market_amount


__all__ = [
    "MembershipResolution",
    "aggregate_point_in_time_industries",
    "build_equal_weight_benchmark",
    "build_internal_structure",
    "canonical_security_id",
    "resolve_memberships",
]
