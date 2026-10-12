"""Pure normalization and breadth calculations for THS sector observations."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from statistics import median
from typing import Any

from ..models.ths_sector import (
    THS_TAGS,
    ThsCatalogRelation,
    ThsMemberObservation,
    ThsMemberRanking,
    ThsRankingRow,
    ThsSectorBreadth,
    ThsSnapshotFact,
)


def catalog_checksum(relations: Iterable[ThsCatalogRelation]) -> str:
    """Return a stable checksum independent of provider row order."""

    rows = sorted(
        (
            {"tag": item.tag, "thscode": item.thscode, "name": item.name}
            for item in relations
        ),
        key=lambda item: (item["tag"], item["thscode"], item["name"]),
    )
    encoded = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_rankings(
    relations: Sequence[ThsCatalogRelation],
    snapshots: Sequence[ThsSnapshotFact],
    *,
    catalog_revision: str,
    as_of: date,
) -> tuple[ThsRankingRow, ...]:
    """Validate full catalog coverage and rank every classification."""

    if not catalog_revision.strip():
        raise ValueError("catalog_revision is required")
    relation_keys: set[tuple[str, str]] = set()
    relations_by_code: dict[str, list[ThsCatalogRelation]] = defaultdict(list)
    for relation in relations:
        key = (relation.tag, relation.thscode)
        if key in relation_keys:
            raise ValueError(f"duplicate catalog relation: {relation.tag}/{relation.thscode}")
        relation_keys.add(key)
        relations_by_code[relation.thscode].append(relation)
    observed_tags = {item.tag for item in relations}
    if observed_tags != set(THS_TAGS):
        raise ValueError("ranking requires all four THS classifications")

    snapshot_by_code: dict[str, ThsSnapshotFact] = {}
    for snapshot in snapshots:
        if snapshot.as_of != as_of:
            raise ValueError(f"snapshot date mismatch for {snapshot.thscode}")
        if snapshot.thscode in snapshot_by_code:
            raise ValueError(f"duplicate snapshot identity: {snapshot.thscode}")
        snapshot_by_code[snapshot.thscode] = snapshot
    expected = set(relations_by_code)
    actual = set(snapshot_by_code)
    if expected != actual:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"snapshot coverage mismatch; missing={missing}, extra={extra}")

    rows: list[ThsRankingRow] = []
    grouped: dict[str, list[tuple[ThsCatalogRelation, ThsSnapshotFact]]] = defaultdict(list)
    for code, code_relations in relations_by_code.items():
        snapshot = snapshot_by_code[code]
        for relation in code_relations:
            if relation.name != snapshot.name:
                raise ValueError(f"catalog/snapshot name mismatch for {code}")
            grouped[relation.tag].append((relation, snapshot))
    for tag in THS_TAGS:
        ranked = sorted(
            grouped[tag],
            key=lambda pair: (-pair[1].change_pct, pair[0].thscode),
        )
        for index, (relation, snapshot) in enumerate(ranked, start=1):
            rows.append(
                ThsRankingRow(
                    tag=relation.tag,
                    rank=index,
                    thscode=relation.thscode,
                    name=relation.name,
                    change_pct=snapshot.change_pct,
                    volume=snapshot.volume,
                    turnover=snapshot.turnover,
                    catalog_revision=catalog_revision,
                    as_of=as_of,
                )
            )
    return tuple(rows)


def select_breadth_codes(
    rankings: Sequence[ThsRankingRow],
    user_selected: Iterable[str] = (),
    *,
    per_tag: int = 10,
) -> Mapping[str, tuple[str, ...]]:
    """Union stable per-tag leaders and user selections with traceable reasons."""

    if per_tag <= 0:
        raise ValueError("per_tag must be positive")
    reasons: dict[str, set[str]] = defaultdict(set)
    for tag in THS_TAGS:
        tag_rows = sorted(
            (row for row in rankings if row.tag == tag),
            key=lambda row: (row.rank, row.thscode),
        )[:per_tag]
        for row in tag_rows:
            reasons[row.thscode].add(f"top-{per_tag}:{tag}")
    known_codes = {row.thscode for row in rankings}
    for raw_code in user_selected:
        code = str(raw_code).strip().upper()
        if code not in known_codes:
            raise ValueError(f"user-selected THS code is absent from ranking revision: {code}")
        reasons[code].add("user-selected")
    return {code: tuple(sorted(value)) for code, value in sorted(reasons.items())}


def calculate_breadth(
    *,
    thscode: str,
    as_of: date,
    selection_reasons: Sequence[str],
    members: Sequence[ThsMemberObservation],
    total_member_count: int | None = None,
    limits_available: bool = True,
    top_n: int = 10,
) -> ThsSectorBreadth:
    """Calculate the complete current-day breadth contract for one THS code."""

    if top_n <= 0:
        raise ValueError("top_n must be positive")
    identities = [member.security_id for member in members]
    if len(identities) != len(set(identities)):
        raise ValueError("breadth members must have unique security identities")
    member_count = len(members) if total_member_count is None else total_member_count
    if member_count < len(members):
        raise ValueError("total_member_count cannot be below observed members")

    direction_values = [member.change_pct for member in members if member.change_pct is not None]
    advance_count = sum(value > 0 for value in direction_values)
    decline_count = sum(value < 0 for value in direction_values)
    flat_count = sum(value == 0 for value in direction_values)
    valid_direction_count = len(direction_values)
    advance_ratio = advance_count / valid_direction_count if valid_direction_count else None
    spread_ratio = (
        (advance_count - decline_count) / valid_direction_count
        if valid_direction_count
        else None
    )
    median_change_pct = median(direction_values) if direction_values else None

    valid_ma20_count = 0
    close_above_ma20_count = 0
    for member in members:
        if member.close is None or len(member.adjusted_closes) < 20:
            continue
        window = member.adjusted_closes[-20:]
        valid_ma20_count += 1
        if member.close > sum(window) / len(window):
            close_above_ma20_count += 1
    ma20_breadth = (
        close_above_ma20_count / valid_ma20_count if valid_ma20_count else None
    )

    limit_up_count = (
        sum(member.limit_up is True for member in members) if limits_available else None
    )
    limit_down_count = (
        sum(member.limit_down is True for member in members) if limits_available else None
    )

    turnover_members = [member for member in members if member.turnover is not None]
    turnover_members.sort(key=lambda member: (-float(member.turnover), member.security_id))
    gain_members = [member for member in members if member.change_pct is not None]
    gain_members.sort(key=lambda member: (-float(member.change_pct), member.security_id))
    top_by_turnover = tuple(
        ThsMemberRanking(member.security_id, float(member.turnover))
        for member in turnover_members[:top_n]
    )
    top_by_gain = tuple(
        ThsMemberRanking(member.security_id, float(member.change_pct))
        for member in gain_members[:top_n]
    )
    total_turnover = sum(float(member.turnover) for member in turnover_members)
    contribution = (
        float(turnover_members[0].turnover) / total_turnover
        if turnover_members and total_turnover > 0
        else None
    )
    diffusion = 1 - contribution if contribution is not None else None

    warnings: list[str] = []
    if len(members) < member_count:
        warnings.append(
            f"member coverage partial: observed {len(members)} of {member_count}"
        )
    if valid_direction_count < member_count:
        warnings.append(
            f"direction coverage partial: {valid_direction_count} of {member_count}"
        )
    if valid_ma20_count < member_count:
        warnings.append(f"MA20 coverage partial: {valid_ma20_count} of {member_count}")
    if not limits_available:
        warnings.append("same-day limits facts unavailable")
    lineage_sources = sorted(
        {
            value
            for member in members
            for value in member.lineage.values()
            if str(value).strip()
        }
    )
    if len(lineage_sources) > 1:
        warnings.append("member facts use mixed source lineage")
    if member_count == 0 or valid_direction_count == 0:
        quality = "insufficient"
    elif warnings:
        quality = "partial"
    else:
        quality = "ok"
    lineage: dict[str, str] = {}
    if lineage_sources:
        lineage["sources"] = ",".join(lineage_sources)

    return ThsSectorBreadth(
        thscode=thscode,
        as_of=as_of,
        selection_reasons=tuple(sorted(set(selection_reasons))),
        member_count=member_count,
        valid_direction_count=valid_direction_count,
        advance_count=advance_count,
        decline_count=decline_count,
        flat_count=flat_count,
        advance_ratio=advance_ratio,
        advance_decline_spread_ratio=spread_ratio,
        median_change_pct=median_change_pct,
        valid_ma20_count=valid_ma20_count,
        close_above_ma20_count=close_above_ma20_count,
        ma20_breadth=ma20_breadth,
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
        top_by_turnover=top_by_turnover,
        top_by_gain=top_by_gain,
        max_member_turnover_contribution=contribution,
        diffusion_rate=diffusion,
        quality=quality,
        warnings=tuple(warnings),
        lineage=lineage,
    )


def breadth_as_payload(value: ThsSectorBreadth) -> dict[str, Any]:
    """Project the immutable model to the public camelCase payload."""

    return {
        "thscode": value.thscode,
        "asOf": value.as_of.isoformat(),
        "selectionReasons": list(value.selection_reasons),
        "memberCount": value.member_count,
        "validDirectionCount": value.valid_direction_count,
        "advanceCount": value.advance_count,
        "declineCount": value.decline_count,
        "flatCount": value.flat_count,
        "advanceRatio": value.advance_ratio,
        "advanceDeclineSpreadRatio": value.advance_decline_spread_ratio,
        "medianChangePct": value.median_change_pct,
        "validMa20Count": value.valid_ma20_count,
        "closeAboveMa20Count": value.close_above_ma20_count,
        "ma20Breadth": value.ma20_breadth,
        "limitUpCount": value.limit_up_count,
        "limitDownCount": value.limit_down_count,
        "topByTurnover": [
            {"securityId": item.security_id, "value": item.value}
            for item in value.top_by_turnover
        ],
        "topByGain": [
            {"securityId": item.security_id, "value": item.value}
            for item in value.top_by_gain
        ],
        "maxMemberTurnoverContribution": value.max_member_turnover_contribution,
        "diffusionRate": value.diffusion_rate,
        "quality": value.quality,
        "warnings": list(value.warnings),
        "lineage": dict(value.lineage),
    }


__all__ = [
    "breadth_as_payload",
    "build_rankings",
    "calculate_breadth",
    "catalog_checksum",
    "select_breadth_codes",
]
