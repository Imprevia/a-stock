"""Typed daily collection components for normalized Fuyao THS datasets.

The collectors in this module are deliberately explicit about their I/O:
``industry-ranking`` consumes one already-gated provider bundle, while the two
dependent collectors read normalized local facts only.  Committers keep each
dataset transaction independent so a late sector failure cannot invalidate a
successful sibling snapshot.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ...application.mappers import quality_to_api
from ...application.ports import MarketEnvironmentUnitOfWork
from ...application.ports.committers import DatasetCommitEvidence, DatasetCommitRequest
from ...domain.analysis.ths_sector import (
    breadth_as_payload,
    calculate_breadth,
    select_breadth_codes,
)
from ...domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
    FieldAvailability,
    QualityMetadata,
    RedactedProvenance,
)
from ...domain.models.ths_sector import (
    THS_TAGS,
    ThsCatalogRelation,
    ThsCatalogRevision,
    ThsMemberDailyFact,
    ThsMemberObservation,
    ThsMemberRanking,
    ThsRankingRow,
    ThsSectorBar,
    ThsSectorBreadth,
)
from .committers import StandardSnapshotCommitter


SOURCE = "fuyao-ths"
PROVIDER = "fuyao"
BREADTH_CALCULATION_REVISION = "ths-breadth-v1"


def _canonical_checksum(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _deduplicated(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _quality(
    *,
    dataset: str,
    status: str,
    observations: int,
    as_of: date,
    warnings: Sequence[str],
    source_revision: str | None,
    fetched_at: datetime | None,
    available_fields: Iterable[str] = (),
    missing_fields: Iterable[str] = (),
    extra: Mapping[str, Any] | None = None,
    source: str = SOURCE,
    provider: str = PROVIDER,
) -> QualityMetadata:
    unique_warnings = _deduplicated(warnings)
    return QualityMetadata(
        dataset=dataset,
        source=source,
        provider=provider,
        status=status,
        observations=observations,
        as_of=as_of,
        warning="; ".join(unique_warnings) if unique_warnings else None,
        warnings=unique_warnings,
        extra=dict(extra or {}),
        source_revision=source_revision,
        fetched_at=fetched_at,
        field_availability=FieldAvailability(
            available=tuple(available_fields),
            missing=tuple(missing_fields),
        ),
        provenance=RedactedProvenance(
            attributes={"storage": "normalized-postgresql"}
            if provider == "local-postgresql"
            else {}
        ),
    )


def _candidate(
    identity: DatasetDate,
    *,
    rows: Sequence[Mapping[str, Any]],
    status: str,
    warnings: Sequence[str],
    source_revision: str | None,
    fetched_at: datetime | None,
    state: str | None = None,
    extra_payload: Mapping[str, Any] | None = None,
    available_fields: Iterable[str] = (),
    missing_fields: Iterable[str] = (),
    quality_extra: Mapping[str, Any] | None = None,
    source: str = SOURCE,
    provider: str = PROVIDER,
) -> CollectionCandidate:
    quality = _quality(
        dataset=identity.dataset,
        status=status,
        observations=len(rows),
        as_of=identity.as_of,
        warnings=warnings,
        source_revision=source_revision,
        fetched_at=fetched_at,
        available_fields=available_fields,
        missing_fields=missing_fields,
        extra=quality_extra,
        source=source,
        provider=provider,
    )
    payload = {
        "asOf": identity.as_of.isoformat(),
        "rows": [dict(row) for row in rows],
        "state": state or status,
        "quality": quality_to_api(quality),
        **dict(extra_payload or {}),
    }
    return CollectionCandidate(
        identity=identity,
        payload=payload,
        source=source,
        status=status,
        observations=len(rows),
        warnings=quality.warnings,
        settled=True,
        actual_as_of=identity.as_of,
        quality=quality,
        source_revision=source_revision,
        fetched_at=fetched_at,
        field_availability=quality.field_availability,
        provenance=quality.provenance,
    )


def _outcome(candidate: CollectionCandidate) -> CollectionOutcome:
    state = (
        CollectionTaskState.SUCCESS
        if candidate.status == "ok"
        else CollectionTaskState.PARTIAL
    )
    warning = "; ".join(candidate.warnings) if candidate.warnings else None
    return CollectionOutcome(candidate.identity, state, candidate=candidate, warning=warning)


def _failure(
    identity: DatasetDate,
    message: str,
    *,
    category: AcquisitionFailureCategory = AcquisitionFailureCategory.INSUFFICIENT,
) -> CollectionOutcome:
    failure = AcquisitionFailure(
        category=category,
        message=message,
        requested_as_of=identity.as_of,
        source=SOURCE,
    )
    return CollectionOutcome(
        identity,
        CollectionTaskState.FAILED_MISSING,
        warning=message,
        failure=failure,
    )


def _validate_identity(identity: DatasetDate, dataset_id: str) -> None:
    if identity.dataset != dataset_id:
        raise ValueError(f"collector {dataset_id} cannot collect {identity.dataset}")


def _is_current_completed_session(
    identity: DatasetDate,
    resolver: Callable[[], date | None],
) -> bool:
    return resolver() == identity.as_of


def _iso_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _row_date(value: Any, field_name: str = "asOf") -> date:
    return (
        value
        if isinstance(value, date) and not isinstance(value, datetime)
        else date.fromisoformat(str(value))
    )


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _rows(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be an array")
    return tuple(_mapping(item, field_name) for item in value)


def _snapshot_bar(snapshot: Any, *, source_revision: str, fetched_at: datetime) -> ThsSectorBar:
    values = {
        name: getattr(snapshot, name)
        for name in ("open", "high", "low", "close", "volume", "turnover")
    }
    warnings = tuple(
        f"{name} is unavailable" for name, value in values.items() if value is None
    )
    logical = {
        "thscode": snapshot.thscode,
        "tradingDate": snapshot.as_of.isoformat(),
        **values,
        "sourceRevision": source_revision,
    }
    return ThsSectorBar(
        thscode=snapshot.thscode,
        trading_date=snapshot.as_of,
        source=PROVIDER,
        source_revision=source_revision,
        checksum=_canonical_checksum(logical),
        fetched_at=fetched_at,
        quality="partial" if warnings else "ok",
        warnings=warnings,
        **values,
    )


def _ranking_payload(row: ThsRankingRow) -> dict[str, Any]:
    return {
        "tag": row.tag,
        "rank": row.rank,
        "thscode": row.thscode,
        "name": row.name,
        "changePct": row.change_pct,
        "volume": row.volume,
        "turnover": row.turnover,
        "catalogRevision": row.catalog_revision,
        "asOf": row.as_of.isoformat(),
    }


def _bar_payload(bar: ThsSectorBar) -> dict[str, Any]:
    return {
        "thscode": bar.thscode,
        "tradingDate": bar.trading_date.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "turnover": bar.turnover,
        "source": bar.source,
        "sourceRevision": bar.source_revision,
        "checksum": bar.checksum,
        "fetchedAt": bar.fetched_at.isoformat(),
        "quality": bar.quality,
        "warnings": list(bar.warnings),
    }


@dataclass(frozen=True, slots=True)
class ThsIndustryRankingCollector:
    """Build the complete four-tag candidate from one gated adapter bundle."""

    bundle_loader: Callable[[date], Any]
    current_completed_session: Callable[[], date | None]
    dataset_id: str = "industry-ranking"

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        _validate_identity(identity, self.dataset_id)
        if not _is_current_completed_session(identity, self.current_completed_session):
            return _failure(
                identity,
                "industry-ranking requires the exact current completed Shanghai session",
                category=AcquisitionFailureCategory.DATE_MISMATCH,
            )
        try:
            bundle = self.bundle_loader(identity.as_of)
            revision: ThsCatalogRevision = bundle.revision
            relations = tuple(bundle.relations)
            snapshots = tuple(bundle.snapshots)
            rankings = tuple(bundle.rankings)
            if set(revision.tag_counts) != set(THS_TAGS):
                raise ValueError("ranking bundle does not contain all four THS tags")
            if any(row.as_of != identity.as_of for row in rankings):
                raise ValueError("ranking bundle date does not match requested session")
            if len(rankings) != len(relations):
                raise ValueError("ranking bundle does not cover every catalog relation")

            bars = tuple(
                _snapshot_bar(
                    snapshot,
                    source_revision=revision.capability_revision,
                    fetched_at=revision.fetched_at,
                )
                for snapshot in snapshots
            )
            warnings = _deduplicated(
                (
                    *tuple(getattr(bundle, "warnings", ())),
                    *(warning for bar in bars for warning in bar.warnings),
                )
            )
            status = "partial" if warnings else "ok"
            missing_market_fields = tuple(
                field_name
                for field_name in ("open", "high", "low", "close", "volume", "turnover")
                if any(getattr(bar, field_name) is None for bar in bars)
            )
            candidate = _candidate(
                identity,
                rows=tuple(_ranking_payload(row) for row in rankings),
                status=status,
                warnings=warnings,
                source_revision=revision.capability_revision,
                fetched_at=revision.fetched_at,
                extra_payload={
                    "catalogRevision": revision.revision_id,
                    "catalog": {
                        "revision": revision.revision_id,
                        "capabilityRevision": revision.capability_revision,
                        "providerTimestamp": revision.provider_timestamp.isoformat(),
                        "fetchedAt": revision.fetched_at.isoformat(),
                        "tagCounts": dict(revision.tag_counts),
                        "checksum": revision.checksum,
                        "source": revision.source,
                        "relations": [
                            {
                                "revision": relation.revision_id,
                                "tag": relation.tag,
                                "thscode": relation.thscode,
                                "name": relation.name,
                            }
                            for relation in relations
                        ],
                    },
                    "marketRows": [_bar_payload(bar) for bar in bars],
                },
                available_fields=(
                    "changePct",
                    *(
                        field_name
                        for field_name in (
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "turnover",
                        )
                        if field_name not in missing_market_fields
                    ),
                ),
                missing_fields=missing_market_fields,
                quality_extra={
                    "catalogRevision": revision.revision_id,
                    "tagCounts": dict(revision.tag_counts),
                    "uniqueCodes": len(bars),
                },
            )
            return _outcome(candidate)
        except Exception as exc:
            return _failure(
                identity,
                f"industry-ranking bundle rejected: {exc}",
                category=AcquisitionFailureCategory.CONTRACT,
            )


class ThsIndustryRankingCommitter:
    """Atomically persist catalog, ranking, shared daily bars, and snapshot."""

    dataset_id = "industry-ranking"

    def __init__(
        self,
        unit_of_work_factory: Callable[[], MarketEnvironmentUnitOfWork],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def commit(self, request: DatasetCommitRequest) -> DatasetCommitEvidence:
        if request.identity.dataset != self.dataset_id:
            raise ValueError("industry-ranking committer identity mismatch")
        if request.outcome.state is CollectionTaskState.FAILED_RETAINED:
            raise ValueError("industry-ranking committer cannot commit retained failures")

        revision, relations, rankings, bars = self._decode(request.candidate)
        with self._unit_of_work_factory() as unit_of_work:
            def write(_connection: object) -> CollectionCandidate:
                repository = unit_of_work.ths_sectors
                repository.put_catalog_revision(revision, relations)
                ranking_counts = repository.put_rankings(rankings)
                bar_counts = repository.put_sector_bars(bars)
                conflicts = int(ranking_counts.get("conflict", 0)) + int(
                    bar_counts.get("conflict", 0)
                )
                if conflicts:
                    raise ValueError(
                        f"industry-ranking immutable fact conflicts: {conflicts}"
                    )
                stored = unit_of_work.snapshots.put(request.candidate)
                if not isinstance(stored, CollectionCandidate):
                    raise TypeError("snapshot repository returned invalid ranking evidence")
                return stored

            stored = unit_of_work.leases.execute_fenced(
                request.lease,
                "ths_industry_ranking_commit",
                write,
                expected_identity=request.identity,
            )
            unit_of_work.commit()
        return DatasetCommitEvidence(
            identity=request.identity,
            outcome_state=request.outcome.state,
            candidate=stored,
            writes=("ths-catalog", "ths-rankings", "ths-sector-bars", "snapshot"),
        )

    @staticmethod
    def _decode(
        candidate: CollectionCandidate,
    ) -> tuple[
        ThsCatalogRevision,
        tuple[ThsCatalogRelation, ...],
        tuple[ThsRankingRow, ...],
        tuple[ThsSectorBar, ...],
    ]:
        payload = candidate.payload
        catalog = _mapping(payload.get("catalog"), "catalog")
        tag_counts = _mapping(catalog.get("tagCounts"), "catalog.tagCounts")
        revision = ThsCatalogRevision(
            revision_id=str(catalog["revision"]),
            capability_revision=str(catalog["capabilityRevision"]),
            provider_timestamp=_iso_datetime(
                catalog["providerTimestamp"], "catalog.providerTimestamp"
            ),
            fetched_at=_iso_datetime(catalog["fetchedAt"], "catalog.fetchedAt"),
            tag_counts={str(key): int(value) for key, value in tag_counts.items()},
            checksum=str(catalog["checksum"]),
            source=str(catalog.get("source") or PROVIDER),
        )
        relations = tuple(
            ThsCatalogRelation(
                revision_id=str(row["revision"]),
                tag=str(row["tag"]),
                thscode=str(row["thscode"]),
                name=str(row["name"]),
            )
            for row in _rows(catalog.get("relations"), "catalog.relations")
        )
        rankings = tuple(
            ThsRankingRow(
                tag=str(row["tag"]),
                rank=int(row["rank"]),
                thscode=str(row["thscode"]),
                name=str(row["name"]),
                change_pct=float(row["changePct"]),
                volume=float(row["volume"]) if row.get("volume") is not None else None,
                turnover=(
                    float(row["turnover"])
                    if row.get("turnover") is not None
                    else None
                ),
                catalog_revision=str(row["catalogRevision"]),
                as_of=_row_date(row["asOf"]),
            )
            for row in _rows(payload.get("rows"), "rows")
        )
        bars = tuple(
            ThsSectorBar(
                thscode=str(row["thscode"]),
                trading_date=_row_date(row["tradingDate"], "tradingDate"),
                open=float(row["open"]) if row.get("open") is not None else None,
                high=float(row["high"]) if row.get("high") is not None else None,
                low=float(row["low"]) if row.get("low") is not None else None,
                close=float(row["close"]) if row.get("close") is not None else None,
                volume=float(row["volume"]) if row.get("volume") is not None else None,
                turnover=(
                    float(row["turnover"])
                    if row.get("turnover") is not None
                    else None
                ),
                source=str(row["source"]),
                source_revision=str(row["sourceRevision"]),
                checksum=str(row["checksum"]),
                fetched_at=_iso_datetime(row["fetchedAt"], "fetchedAt"),
                quality=str(row.get("quality") or "ok"),
                warnings=tuple(str(value) for value in row.get("warnings") or ()),
            )
            for row in _rows(payload.get("marketRows"), "marketRows")
        )
        if len(rankings) != len(relations):
            raise ValueError("ranking commit payload does not cover the catalog")
        relation_keys = {(row.tag, row.thscode) for row in relations}
        ranking_keys = {(row.tag, row.thscode) for row in rankings}
        if len(relation_keys) != len(relations) or relation_keys != ranking_keys:
            raise ValueError("ranking commit relation/rank identities do not reconcile")
        expected_codes = {row.thscode for row in relations}
        bar_codes = {row.thscode for row in bars}
        if len(bar_codes) != len(bars) or bar_codes != expected_codes:
            raise ValueError("ranking commit daily bars do not cover every unique code")
        if any(
            row.catalog_revision != revision.revision_id
            or row.as_of != candidate.identity.as_of
            for row in rankings
        ):
            raise ValueError("ranking commit revision or date mismatch")
        if any(row.trading_date != candidate.identity.as_of for row in bars):
            raise ValueError("ranking commit daily bar date mismatch")
        return revision, relations, rankings, bars


@dataclass(frozen=True, slots=True)
class ThsSectorTurnoverCollector:
    """Project same-day normalized ranking/bar facts without provider I/O."""

    unit_of_work_factory: Callable[[], MarketEnvironmentUnitOfWork]
    current_completed_session: Callable[[], date | None]
    dataset_id: str = "sector-turnover"

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        _validate_identity(identity, self.dataset_id)
        if not _is_current_completed_session(identity, self.current_completed_session):
            return _failure(
                identity,
                "sector-turnover requires the exact current completed Shanghai session",
                category=AcquisitionFailureCategory.DATE_MISMATCH,
            )
        with self.unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.ths_sectors
            rankings = tuple(repository.list_rankings(identity.as_of))
            if not rankings:
                return _failure(identity, "sector-turnover requires same-day normalized rankings")
            if {row.tag for row in rankings} != set(THS_TAGS):
                return _failure(
                    identity,
                    "sector-turnover requires complete four-tag rankings",
                    category=AcquisitionFailureCategory.CONTRACT,
                )
            revisions = {row.catalog_revision for row in rankings}
            if len(revisions) != 1:
                return _failure(
                    identity,
                    "sector-turnover rankings contain incompatible catalog revisions",
                    category=AcquisitionFailureCategory.CONTRACT,
                )
            catalog_revision = next(iter(revisions))
            names: dict[str, str] = {}
            tags: dict[str, set[str]] = defaultdict(set)
            for ranking in rankings:
                previous = names.setdefault(ranking.thscode, ranking.name)
                if previous != ranking.name:
                    return _failure(
                        identity,
                        f"sector-turnover name conflict for {ranking.thscode}",
                        category=AcquisitionFailureCategory.CONTRACT,
                    )
                tags[ranking.thscode].add(ranking.tag)

            selected_bars: dict[str, ThsSectorBar] = {}
            warnings: list[str] = []
            for thscode in sorted(names):
                bars = tuple(
                    repository.list_sector_bars(
                        thscode,
                        start_date=identity.as_of,
                        end_date=identity.as_of,
                        offset=0,
                        limit=2,
                    )
                )
                exact = tuple(bar for bar in bars if bar.trading_date == identity.as_of)
                if len(exact) != 1:
                    warnings.append(f"same-day normalized bar missing for {thscode}")
                    continue
                selected_bars[thscode] = exact[0]
                warnings.extend(
                    f"{thscode}: {warning}" for warning in exact[0].warnings
                )

        rows = tuple(
            {
                **_bar_payload(selected_bars[thscode]),
                "name": names[thscode],
                "tags": sorted(tags[thscode]),
                "catalogRevision": catalog_revision,
            }
            for thscode in sorted(selected_bars)
        )
        missing_fields = tuple(
            field_name
            for field_name in ("open", "high", "low", "close", "volume", "turnover")
            if any(row.get(field_name) is None for row in rows)
        )
        if not rows:
            status = "insufficient"
        elif len(rows) != len(names) or missing_fields or warnings:
            status = "partial"
        else:
            status = "ok"
        fetched_at = max(
            (bar.fetched_at for bar in selected_bars.values()),
            default=datetime.now(timezone.utc),
        )
        candidate = _candidate(
            identity,
            rows=rows,
            status=status,
            warnings=warnings,
            source_revision=catalog_revision,
            fetched_at=fetched_at,
            state=status,
            extra_payload={"catalogRevision": catalog_revision},
            available_fields=tuple(
                field_name
                for field_name in ("open", "high", "low", "close", "volume", "turnover")
                if field_name not in missing_fields
            ),
            missing_fields=missing_fields,
            quality_extra={
                "catalogRevision": catalog_revision,
                "expectedCodes": len(names),
                "storedCodes": len(rows),
            },
            source="local-ths-normalized",
            provider="local-postgresql",
        )
        return _outcome(candidate)


class ThsSectorTurnoverCommitter(StandardSnapshotCommitter):
    def __init__(
        self,
        unit_of_work_factory: Callable[[], MarketEnvironmentUnitOfWork],
    ) -> None:
        super().__init__("sector-turnover", unit_of_work_factory)


def _fact_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _fact_priority(value: ThsMemberDailyFact) -> tuple[int, str]:
    priorities = {"ok": 4, "degraded": 3, "partial": 2, "insufficient": 1}
    return priorities.get(value.quality, 0), value.source_revision


def _member_facts_by_security(
    repository: Any,
    *,
    as_of: date,
    calendar_days: int,
) -> dict[str, tuple[ThsMemberDailyFact, ...]]:
    selected: dict[tuple[str, date], ThsMemberDailyFact] = {}
    for offset in range(calendar_days - 1, -1, -1):
        trading_date = as_of - timedelta(days=offset)
        for fact in repository.list_member_facts(trading_date):
            key = (fact.security_id, fact.trading_date)
            previous = selected.get(key)
            if previous is None or _fact_priority(fact) > _fact_priority(previous):
                selected[key] = fact
    grouped: dict[str, list[ThsMemberDailyFact]] = defaultdict(list)
    for fact in selected.values():
        grouped[fact.security_id].append(fact)
    return {
        security_id: tuple(sorted(values, key=lambda item: item.trading_date))
        for security_id, values in grouped.items()
    }


def _current_memberships(values: Sequence[Any]) -> tuple[Any, ...]:
    selected: dict[str, Any] = {}
    for membership in values:
        previous = selected.get(membership.member_security_id)
        if previous is None or (
            membership.fetched_at,
            membership.source_revision,
        ) > (
            previous.fetched_at,
            previous.source_revision,
        ):
            selected[membership.member_security_id] = membership
    return tuple(selected[key] for key in sorted(selected))


def _persisted_user_selected_codes(repository: Any, as_of: date) -> tuple[str, ...]:
    """Read the latest completed catalog-sync selection for this exact date."""

    list_operations = getattr(repository, "list_operations", None)
    if not callable(list_operations):
        return ()
    for operation in list_operations(kind="catalog-sync", limit=100):
        if operation.status not in {"success", "partial"}:
            continue
        if operation.request_metadata.get("asOf") != as_of.isoformat():
            continue
        requested = operation.request_metadata.get("membershipThscodes")
        if not isinstance(requested, (list, tuple)):
            return ()
        outcomes = operation.progress.get("membershipCodes")
        if not isinstance(outcomes, Mapping):
            return ()
        return tuple(
            sorted(
                {
                    str(code).strip().upper()
                    for code in requested
                    if isinstance(outcomes.get(str(code).strip().upper()), Mapping)
                    and outcomes[str(code).strip().upper()].get("status") == "success"
                }
            )
        )
    return ()


def _limits_membership(
    detail: Mapping[str, Any] | None,
    *,
    as_of: date,
) -> tuple[bool, set[str], set[str], str | None]:
    if detail is None:
        return False, set(), set(), None
    actual_as_of = detail.get("actual_as_of", detail.get("actualAsOf", detail.get("as_of")))
    if isinstance(actual_as_of, str):
        actual_as_of = date.fromisoformat(actual_as_of)
    if actual_as_of != as_of or detail.get("complete") is not True:
        return False, set(), set(), None
    limit_up: set[str] = set()
    limit_down: set[str] = set()
    for fact in detail.get("facts") or ():
        security_id = str(
            _fact_value(fact, "security_id", _fact_value(fact, "securityId", ""))
        ).strip()
        if not security_id:
            continue
        if _fact_value(fact, "membership_valid", True) is False:
            continue
        if _fact_value(fact, "eligible", True) is False:
            continue
        pool_type = _fact_value(fact, "pool_type", _fact_value(fact, "poolType"))
        if pool_type == "limit_up" and _fact_value(
            fact,
            "closed_limit_up",
            _fact_value(fact, "closedLimitUp", True),
        ) is True:
            limit_up.add(security_id)
        elif pool_type == "limit_down":
            limit_down.add(security_id)
    revision = detail.get("source_revision", detail.get("sourceRevision"))
    return True, limit_up, limit_down, str(revision) if revision is not None else None


def _member_observation(
    security_id: str,
    facts: Sequence[ThsMemberDailyFact],
    *,
    as_of: date,
    limit_up: set[str],
    limit_down: set[str],
) -> ThsMemberObservation | None:
    current = next((fact for fact in reversed(facts) if fact.trading_date == as_of), None)
    if current is None:
        return None
    adjusted = tuple(
        float(fact.adjusted_close)
        for fact in facts
        if fact.trading_date <= as_of and fact.adjusted_close is not None
    )
    change_pct = None
    if current.adjusted_close is not None and len(adjusted) >= 2 and adjusted[-2] > 0:
        change_pct = (adjusted[-1] / adjusted[-2] - 1) * 100
    lineage: dict[str, str] = {}
    for fact in facts[-20:]:
        for key, value in fact.field_lineage.items():
            if str(value).strip():
                lineage[f"{fact.trading_date.isoformat()}:{key}"] = str(value)
    return ThsMemberObservation(
        security_id=security_id,
        change_pct=change_pct,
        close=float(current.adjusted_close) if current.adjusted_close is not None else None,
        adjusted_closes=adjusted[-20:],
        turnover=float(current.turnover) if current.turnover is not None else None,
        limit_up=security_id in limit_up,
        limit_down=security_id in limit_down,
        lineage=lineage,
    )


@dataclass(frozen=True, slots=True)
class ThsSectorBreadthCollector:
    """Calculate exact-current-session breadth from normalized local facts."""

    unit_of_work_factory: Callable[[], MarketEnvironmentUnitOfWork]
    current_completed_session: Callable[[], date | None]
    user_selected_codes: Callable[[date], Iterable[str]] = lambda _as_of: ()
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    top_per_tag: int = 10
    history_calendar_days: int = 45
    dataset_id: str = "sector-breadth"

    def __post_init__(self) -> None:
        if self.top_per_tag <= 0:
            raise ValueError("top_per_tag must be positive")
        if self.history_calendar_days < 20:
            raise ValueError("history_calendar_days must cover at least 20 days")

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        _validate_identity(identity, self.dataset_id)
        if not _is_current_completed_session(identity, self.current_completed_session):
            return _failure(
                identity,
                "sector-breadth requires the exact current completed Shanghai session",
                category=AcquisitionFailureCategory.DATE_MISMATCH,
            )
        with self.unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.ths_sectors
            rankings = tuple(repository.list_rankings(identity.as_of))
            if not rankings:
                return _failure(identity, "sector-breadth requires same-day normalized rankings")
            if {row.tag for row in rankings} != set(THS_TAGS):
                return _failure(
                    identity,
                    "sector-breadth requires complete four-tag rankings",
                    category=AcquisitionFailureCategory.CONTRACT,
                )
            revisions = {row.catalog_revision for row in rankings}
            if len(revisions) != 1:
                return _failure(
                    identity,
                    "sector-breadth rankings contain incompatible catalog revisions",
                    category=AcquisitionFailureCategory.CONTRACT,
                )
            catalog_revision = next(iter(revisions))
            try:
                user_selected = tuple(
                    dict.fromkeys(
                        (
                            *_persisted_user_selected_codes(repository, identity.as_of),
                            *self.user_selected_codes(identity.as_of),
                        )
                    )
                )
                selections = select_breadth_codes(
                    rankings,
                    user_selected,
                    per_tag=self.top_per_tag,
                )
            except ValueError as exc:
                return _failure(
                    identity,
                    f"sector-breadth selection rejected: {exc}",
                    category=AcquisitionFailureCategory.CONTRACT,
                )
            facts_by_security = _member_facts_by_security(
                repository,
                as_of=identity.as_of,
                calendar_days=self.history_calendar_days,
            )
            limit_detail = unit_of_work.limit_details.get_limit_detail(identity.as_of)
            limits_available, limit_up, limit_down, limits_revision = _limits_membership(
                limit_detail,
                as_of=identity.as_of,
            )

            breadth_rows: list[ThsSectorBreadth] = []
            for thscode, reasons in selections.items():
                memberships = _current_memberships(
                    tuple(
                        repository.list_sector_memberships(
                            thscode,
                            as_of=identity.as_of,
                        )
                    )
                )
                observations = tuple(
                    observation
                    for membership in memberships
                    if (
                        observation := _member_observation(
                            membership.member_security_id,
                            facts_by_security.get(membership.member_security_id, ()),
                            as_of=identity.as_of,
                            limit_up=limit_up,
                            limit_down=limit_down,
                        )
                    )
                    is not None
                )
                breadth = calculate_breadth(
                    thscode=thscode,
                    as_of=identity.as_of,
                    selection_reasons=reasons,
                    members=observations,
                    total_member_count=len(memberships),
                    limits_available=limits_available,
                )
                if not memberships:
                    breadth = replace(
                        breadth,
                        warnings=(*breadth.warnings, "current membership unavailable"),
                    )
                membership_revisions = sorted(
                    {membership.source_revision for membership in memberships}
                )
                lineage = {
                    **dict(breadth.lineage),
                    "catalogRevision": catalog_revision,
                    "calculationRevision": BREADTH_CALCULATION_REVISION,
                }
                if membership_revisions:
                    lineage["membershipRevisions"] = ",".join(membership_revisions)
                if limits_revision is not None:
                    lineage["limitsRevision"] = limits_revision
                breadth_rows.append(replace(breadth, lineage=lineage))

        statuses = {row.quality for row in breadth_rows}
        warnings = _deduplicated(
            warning for row in breadth_rows for warning in row.warnings
        )
        if statuses == {"ok"}:
            status = "ok"
        elif statuses & {"ok", "partial", "degraded"}:
            status = "partial"
        else:
            status = "insufficient"
        candidate = _candidate(
            identity,
            rows=tuple(breadth_as_payload(row) for row in breadth_rows),
            status=status,
            warnings=warnings,
            source_revision=BREADTH_CALCULATION_REVISION,
            fetched_at=self.clock(),
            state=status,
            extra_payload={"catalogRevision": catalog_revision},
            available_fields=(
                "advanceRatio",
                "advanceDeclineSpreadRatio",
                "medianChangePct",
                "ma20Breadth",
                "maxMemberTurnoverContribution",
                "diffusionRate",
            ),
            missing_fields=("limitUpCount", "limitDownCount")
            if not limits_available
            else (),
            quality_extra={
                "catalogRevision": catalog_revision,
                "selectedCodes": len(breadth_rows),
                "limitsAvailable": limits_available,
                "calculationRevision": BREADTH_CALCULATION_REVISION,
            },
            source="local-ths-breadth",
            provider="local-postgresql",
        )
        return _outcome(candidate)


class ThsSectorBreadthCommitter:
    """Atomically persist breadth evidence and its exact-date snapshot."""

    dataset_id = "sector-breadth"

    def __init__(
        self,
        unit_of_work_factory: Callable[[], MarketEnvironmentUnitOfWork],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def commit(self, request: DatasetCommitRequest) -> DatasetCommitEvidence:
        if request.identity.dataset != self.dataset_id:
            raise ValueError("sector-breadth committer identity mismatch")
        if request.outcome.state is CollectionTaskState.FAILED_RETAINED:
            raise ValueError("sector-breadth committer cannot commit retained failures")
        breadth_rows = tuple(
            self._decode_row(row)
            for row in _rows(request.candidate.payload.get("rows"), "rows")
        )
        identities = [row.thscode for row in breadth_rows]
        if len(identities) != len(set(identities)):
            raise ValueError("sector-breadth snapshot contains duplicate THS codes")
        if any(row.as_of != request.identity.as_of for row in breadth_rows):
            raise ValueError("sector-breadth snapshot date mismatch")
        with self._unit_of_work_factory() as unit_of_work:
            def write(_connection: object) -> CollectionCandidate:
                conflicts = 0
                for breadth in breadth_rows:
                    result = unit_of_work.ths_sectors.put_sector_breadth(breadth)
                    conflicts += result == "conflict"
                if conflicts:
                    raise ValueError(
                        f"sector-breadth immutable fact conflicts: {conflicts}"
                    )
                stored = unit_of_work.snapshots.put(request.candidate)
                if not isinstance(stored, CollectionCandidate):
                    raise TypeError("snapshot repository returned invalid breadth evidence")
                return stored

            stored = unit_of_work.leases.execute_fenced(
                request.lease,
                "ths_sector_breadth_commit",
                write,
                expected_identity=request.identity,
            )
            unit_of_work.commit()
        return DatasetCommitEvidence(
            identity=request.identity,
            outcome_state=request.outcome.state,
            candidate=stored,
            writes=("ths-sector-breadth", "snapshot"),
        )

    @staticmethod
    def _decode_row(row: Mapping[str, Any]) -> ThsSectorBreadth:
        return ThsSectorBreadth(
            thscode=str(row["thscode"]),
            as_of=_row_date(row["asOf"]),
            selection_reasons=tuple(
                str(value) for value in row.get("selectionReasons") or ()
            ),
            member_count=int(row["memberCount"]),
            valid_direction_count=int(row["validDirectionCount"]),
            advance_count=int(row["advanceCount"]),
            decline_count=int(row["declineCount"]),
            flat_count=int(row["flatCount"]),
            advance_ratio=(
                float(row["advanceRatio"])
                if row.get("advanceRatio") is not None
                else None
            ),
            advance_decline_spread_ratio=(
                float(row["advanceDeclineSpreadRatio"])
                if row.get("advanceDeclineSpreadRatio") is not None
                else None
            ),
            median_change_pct=(
                float(row["medianChangePct"])
                if row.get("medianChangePct") is not None
                else None
            ),
            valid_ma20_count=int(row["validMa20Count"]),
            close_above_ma20_count=int(row["closeAboveMa20Count"]),
            ma20_breadth=(
                float(row["ma20Breadth"])
                if row.get("ma20Breadth") is not None
                else None
            ),
            limit_up_count=(
                int(row["limitUpCount"])
                if row.get("limitUpCount") is not None
                else None
            ),
            limit_down_count=(
                int(row["limitDownCount"])
                if row.get("limitDownCount") is not None
                else None
            ),
            top_by_turnover=tuple(
                ThsMemberRanking(str(value["securityId"]), float(value["value"]))
                for value in row.get("topByTurnover") or ()
            ),
            top_by_gain=tuple(
                ThsMemberRanking(str(value["securityId"]), float(value["value"]))
                for value in row.get("topByGain") or ()
            ),
            max_member_turnover_contribution=(
                float(row["maxMemberTurnoverContribution"])
                if row.get("maxMemberTurnoverContribution") is not None
                else None
            ),
            diffusion_rate=(
                float(row["diffusionRate"])
                if row.get("diffusionRate") is not None
                else None
            ),
            quality=str(row["quality"]),
            warnings=tuple(str(value) for value in row.get("warnings") or ()),
            lineage={
                str(key): str(value)
                for key, value in _mapping(
                    row.get("lineage", {}),
                    "lineage",
                ).items()
            },
        )


@dataclass(frozen=True, slots=True)
class _ThsDatasetProjector:
    dataset_id: str

    def project(
        self,
        identity: DatasetDate,
        candidate: CollectionCandidate | None,
    ) -> Mapping[str, Any]:
        if identity.dataset != self.dataset_id:
            raise ValueError(
                f"detail projector {self.dataset_id} cannot project {identity.dataset}"
            )
        if candidate is None:
            return {
                "asOf": identity.as_of.isoformat(),
                "rowCount": 0,
                "state": "missing",
                "catalogRevision": None,
            }
        rows = candidate.payload.get("rows")
        if not isinstance(rows, (list, tuple)):
            rows = ()
        quality = candidate.payload.get("quality")
        status = quality.get("status") if isinstance(quality, Mapping) else candidate.status
        return {
            "asOf": identity.as_of.isoformat(),
            "rowCount": len(rows),
            "state": status,
            "catalogRevision": candidate.payload.get("catalogRevision"),
            **self._extra(candidate, rows),
        }

    def _extra(
        self,
        candidate: CollectionCandidate,
        rows: Sequence[Any],
    ) -> Mapping[str, Any]:
        del candidate, rows
        return {}


@dataclass(frozen=True, slots=True)
class ThsIndustryRankingProjector(_ThsDatasetProjector):
    dataset_id: str = "industry-ranking"

    def _extra(
        self,
        candidate: CollectionCandidate,
        rows: Sequence[Any],
    ) -> Mapping[str, Any]:
        catalog = candidate.payload.get("catalog")
        return {
            "tagCounts": dict(catalog.get("tagCounts") or {})
            if isinstance(catalog, Mapping)
            else {},
            "uniqueCodes": len(
                {
                    str(row.get("thscode"))
                    for row in rows
                    if isinstance(row, Mapping) and row.get("thscode")
                }
            ),
        }


@dataclass(frozen=True, slots=True)
class ThsSectorTurnoverProjector(_ThsDatasetProjector):
    dataset_id: str = "sector-turnover"

    def _extra(
        self,
        candidate: CollectionCandidate,
        rows: Sequence[Any],
    ) -> Mapping[str, Any]:
        incomplete = 0
        for row in rows:
            if not isinstance(row, Mapping) or any(
                row.get(field_name) is None
                for field_name in ("open", "high", "low", "close", "volume", "turnover")
            ):
                incomplete += 1
        return {"incompleteRowCount": incomplete}


@dataclass(frozen=True, slots=True)
class ThsSectorBreadthProjector(_ThsDatasetProjector):
    dataset_id: str = "sector-breadth"

    def _extra(
        self,
        candidate: CollectionCandidate,
        rows: Sequence[Any],
    ) -> Mapping[str, Any]:
        qualities: dict[str, int] = defaultdict(int)
        for row in rows:
            if isinstance(row, Mapping):
                qualities[str(row.get("quality") or "missing")] += 1
        return {"qualityCounts": dict(sorted(qualities.items()))}


__all__ = [
    "BREADTH_CALCULATION_REVISION",
    "ThsIndustryRankingCollector",
    "ThsIndustryRankingCommitter",
    "ThsIndustryRankingProjector",
    "ThsSectorBreadthCollector",
    "ThsSectorBreadthCommitter",
    "ThsSectorBreadthProjector",
    "ThsSectorTurnoverCollector",
    "ThsSectorTurnoverCommitter",
    "ThsSectorTurnoverProjector",
]
