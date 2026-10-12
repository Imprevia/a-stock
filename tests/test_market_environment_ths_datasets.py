from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.market_environment.application.ports.committers import DatasetCommitRequest
from src.market_environment.domain.analysis.ths_sector import (
    build_rankings,
    catalog_checksum,
)
from src.market_environment.domain.models import (
    CollectionCandidate,
    CollectionTaskState,
    DatasetDate,
)
from src.market_environment.domain.models.ths_sector import (
    THS_TAGS,
    ThsCatalogRelation,
    ThsCatalogRevision,
    ThsMemberDailyFact,
    ThsOperation,
    ThsRankingRow,
    ThsSectorBar,
    ThsSectorMembership,
    ThsSnapshotFact,
)
from src.market_environment.infrastructure.collection.ths_datasets import (
    ThsIndustryRankingCollector,
    ThsIndustryRankingCommitter,
    ThsIndustryRankingProjector,
    ThsSectorBreadthCollector,
    ThsSectorBreadthCommitter,
    ThsSectorBreadthProjector,
    ThsSectorTurnoverCollector,
    ThsSectorTurnoverCommitter,
    ThsSectorTurnoverProjector,
)


AS_OF = date(2026, 10, 12)
FETCHED_AT = datetime(2026, 10, 12, 15, 20, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakeLease:
    dataset: str
    as_of: date
    owner: str = "worker-1"
    generation: int = 1
    token: str = "lease-1"


@dataclass
class FakeState:
    revision: ThsCatalogRevision | None = None
    relations: tuple[ThsCatalogRelation, ...] = ()
    rankings: tuple[ThsRankingRow, ...] = ()
    bars: dict[tuple[str, date], ThsSectorBar] = field(default_factory=dict)
    memberships: dict[tuple[str, date], tuple[ThsSectorMembership, ...]] = field(
        default_factory=dict
    )
    member_facts: dict[date, tuple[ThsMemberDailyFact, ...]] = field(
        default_factory=dict
    )
    breadth: list[object] = field(default_factory=list)
    operations: tuple[ThsOperation, ...] = ()
    snapshots: dict[tuple[str, date], CollectionCandidate] = field(default_factory=dict)
    limits: dict[date, dict] = field(default_factory=dict)
    bar_conflict: bool = False
    breadth_conflict: bool = False


class FakeThsRepository:
    def __init__(self, state: FakeState) -> None:
        self.state = state

    def put_catalog_revision(self, revision, relations):
        self.state.revision = revision
        self.state.relations = tuple(relations)
        return revision

    def put_rankings(self, rankings):
        values = tuple(rankings)
        self.state.rankings = values
        return {"inserted": len(values), "identical": 0, "conflict": 0}

    def list_rankings(self, as_of, **_kwargs):
        return tuple(row for row in self.state.rankings if row.as_of == as_of)

    def put_sector_bars(self, bars):
        values = tuple(bars)
        if self.state.bar_conflict:
            return {"inserted": 0, "identical": 0, "conflict": len(values)}
        for bar in values:
            self.state.bars[(bar.thscode, bar.trading_date)] = bar
        return {"inserted": len(values), "identical": 0, "conflict": 0}

    def list_sector_bars(
        self,
        thscode,
        *,
        start_date=None,
        end_date=None,
        offset=0,
        limit=500,
    ):
        values = [
            bar
            for (code, trading_date), bar in self.state.bars.items()
            if code == thscode
            and (start_date is None or trading_date >= start_date)
            and (end_date is None or trading_date <= end_date)
        ]
        return tuple(sorted(values, key=lambda item: item.trading_date)[offset : offset + limit])

    def list_sector_memberships(self, thscode, *, as_of=None, **_kwargs):
        return self.state.memberships.get((thscode, as_of), ())

    def list_member_facts(self, trading_date):
        return self.state.member_facts.get(trading_date, ())

    def list_operations(self, **_kwargs):
        return self.state.operations

    def put_sector_breadth(self, breadth):
        if self.state.breadth_conflict:
            return "conflict"
        self.state.breadth.append(breadth)
        return "inserted"


class FakeSnapshots:
    def __init__(self, state: FakeState) -> None:
        self.state = state

    def put(self, candidate):
        self.state.snapshots[(candidate.identity.dataset, candidate.identity.as_of)] = candidate
        return candidate


class FakeLeases:
    @staticmethod
    def execute_fenced(lease, operation, writer, *, expected_identity=None):
        assert operation
        assert expected_identity == DatasetDate(lease.dataset, lease.as_of)
        return writer(object())


class FakeLimits:
    def __init__(self, state: FakeState) -> None:
        self.state = state

    def get_limit_detail(self, as_of):
        return self.state.limits.get(as_of)


class FakeUow:
    def __init__(self, shared: FakeState) -> None:
        self.shared = shared
        self.working = copy.deepcopy(shared)
        self.ths_sectors = FakeThsRepository(self.working)
        self.snapshots = FakeSnapshots(self.working)
        self.leases = FakeLeases()
        self.limit_details = FakeLimits(self.working)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def commit(self):
        self.shared.__dict__.update(copy.deepcopy(self.working.__dict__))
        self.committed = True

    def rollback(self):
        return None


@dataclass
class FakeUowFactory:
    state: FakeState
    calls: int = 0

    def __call__(self):
        self.calls += 1
        return FakeUow(self.state)


def _bundle():
    relations = (
        ThsCatalogRelation("catalog-r1", "industry", "885001.TI", "共享板块"),
        ThsCatalogRelation("catalog-r1", "cn_concept", "885001.TI", "共享板块"),
        ThsCatalogRelation("catalog-r1", "region", "885002.TI", "区域板块"),
        ThsCatalogRelation("catalog-r1", "tszs", "885003.TI", "特色指数"),
    )
    revision = ThsCatalogRevision(
        revision_id="catalog-r1",
        capability_revision="fuyao-catalog-v1",
        provider_timestamp=FETCHED_AT,
        fetched_at=FETCHED_AT,
        tag_counts={tag: 1 for tag in THS_TAGS},
        checksum=catalog_checksum(relations),
    )
    snapshots = tuple(
        ThsSnapshotFact(
            thscode=code,
            name=name,
            as_of=AS_OF,
            provider_timestamp=FETCHED_AT,
            change_pct=change,
            open=10 + change,
            high=12 + change,
            low=9 + change,
            close=11 + change,
            volume=1000 + change,
            turnover=5000 + change,
        )
        for code, name, change in (
            ("885001.TI", "共享板块", 3.0),
            ("885002.TI", "区域板块", 2.0),
            ("885003.TI", "特色指数", 1.0),
        )
    )
    rankings = build_rankings(
        relations,
        snapshots,
        catalog_revision=revision.revision_id,
        as_of=AS_OF,
    )
    return SimpleNamespace(
        revision=revision,
        relations=relations,
        snapshots=snapshots,
        rankings=rankings,
        warnings=(),
    )


def _commit_request(outcome):
    return DatasetCommitRequest(
        identity=outcome.identity,
        outcome=outcome,
        lease=FakeLease(outcome.identity.dataset, outcome.identity.as_of),
    )


def test_ranking_committer_writes_four_catalogs_and_shared_bars_atomically() -> None:
    calls: list[date] = []

    def load_bundle(as_of):
        calls.append(as_of)
        return _bundle()

    collector = ThsIndustryRankingCollector(load_bundle, lambda: AS_OF)
    outcome = collector.collect(DatasetDate("industry-ranking", AS_OF))

    assert outcome.state is CollectionTaskState.SUCCESS
    assert calls == [AS_OF]
    assert len(outcome.candidate.payload["rows"]) == 4
    assert len(outcome.candidate.payload["marketRows"]) == 3
    assert outcome.candidate.payload["catalog"]["tagCounts"] == {
        tag: 1 for tag in THS_TAGS
    }

    state = FakeState()
    evidence = ThsIndustryRankingCommitter(FakeUowFactory(state)).commit(
        _commit_request(outcome)
    )

    assert evidence.writes == (
        "ths-catalog",
        "ths-rankings",
        "ths-sector-bars",
        "snapshot",
    )
    assert len(state.relations) == 4
    assert len(state.rankings) == 4
    assert len(state.bars) == 3
    assert ("industry-ranking", AS_OF) in state.snapshots


def test_ranking_conflict_rolls_back_without_removing_successful_sibling() -> None:
    outcome = ThsIndustryRankingCollector(lambda _as_of: _bundle(), lambda: AS_OF).collect(
        DatasetDate("industry-ranking", AS_OF)
    )
    sibling = CollectionCandidate(
        identity=DatasetDate("sector-turnover", AS_OF),
        payload={"asOf": AS_OF.isoformat(), "rows": [], "quality": {}},
        source="fixture",
        status="ok",
        observations=0,
        warnings=(),
        settled=True,
        actual_as_of=AS_OF,
    )
    state = FakeState(
        snapshots={("sector-turnover", AS_OF): sibling},
        bar_conflict=True,
    )

    with pytest.raises(ValueError, match="immutable fact conflicts"):
        ThsIndustryRankingCommitter(FakeUowFactory(state)).commit(
            _commit_request(outcome)
        )

    assert state.revision is None
    assert state.rankings == ()
    assert state.snapshots == {("sector-turnover", AS_OF): sibling}


def test_turnover_reads_normalized_same_day_bars_and_keeps_volume_separate() -> None:
    bundle = _bundle()
    state = FakeState(
        revision=bundle.revision,
        relations=bundle.relations,
        rankings=bundle.rankings,
    )
    for snapshot in bundle.snapshots:
        state.bars[(snapshot.thscode, AS_OF)] = ThsSectorBar(
            thscode=snapshot.thscode,
            trading_date=AS_OF,
            open=snapshot.open,
            high=snapshot.high,
            low=snapshot.low,
            close=snapshot.close,
            volume=snapshot.volume,
            turnover=snapshot.turnover,
            source="fuyao",
            source_revision="fuyao-catalog-v1",
            checksum=f"bar-{snapshot.thscode}",
            fetched_at=FETCHED_AT,
        )
    factory = FakeUowFactory(state)
    outcome = ThsSectorTurnoverCollector(factory, lambda: AS_OF).collect(
        DatasetDate("sector-turnover", AS_OF)
    )

    assert outcome.state is CollectionTaskState.SUCCESS
    assert len(outcome.candidate.payload["rows"]) == 3
    shared = next(
        row
        for row in outcome.candidate.payload["rows"]
        if row["thscode"] == "885001.TI"
    )
    assert shared["tags"] == ["cn_concept", "industry"]
    assert shared["volume"] == 1003.0
    assert shared["turnover"] == 5003.0

    evidence = ThsSectorTurnoverCommitter(factory).commit(_commit_request(outcome))
    assert evidence.writes == ("snapshot",)
    assert (
        state.snapshots[("sector-turnover", AS_OF)].payload["rows"]
        == outcome.candidate.payload["rows"]
    )


def _membership(thscode: str, security_id: str) -> ThsSectorMembership:
    return ThsSectorMembership(
        thscode=thscode,
        member_security_id=security_id,
        member_name=security_id,
        as_of=AS_OF,
        provider_timestamp=FETCHED_AT,
        fetched_at=FETCHED_AT,
        source_revision="membership-v1",
        checksum=f"membership-{security_id}",
    )


def _member_fact(
    security_id: str,
    trading_date: date,
    adjusted_close: float,
    turnover: float,
) -> ThsMemberDailyFact:
    return ThsMemberDailyFact(
        security_id=security_id,
        trading_date=trading_date,
        original_open=adjusted_close,
        original_high=adjusted_close,
        original_low=adjusted_close,
        original_close=adjusted_close,
        adjusted_close=adjusted_close,
        adjustment_factor=1.0,
        volume=100.0,
        turnover=turnover,
        quality="ok",
        source_revision="member-v1",
        checksum=f"{security_id}-{trading_date.isoformat()}",
        field_lineage={
            "adjusted_close": "fuyao",
            "turnover": "fuyao",
        },
    )


def test_breadth_uses_top10_user_selection_members_facts_and_limits() -> None:
    rankings = tuple(
        ThsRankingRow(
            tag=tag,
            rank=1,
            thscode="885001.TI",
            name="共享板块",
            change_pct=3.0,
            volume=1000.0,
            turnover=5000.0,
            catalog_revision="catalog-r1",
            as_of=AS_OF,
        )
        for tag in THS_TAGS
    )
    state = FakeState(rankings=rankings)
    state.operations = (
        ThsOperation(
            run_id="catalog-sync-selected",
            kind="catalog-sync",
            status="success",
            capability_revision="catalog-r1",
            request_checksum="selection-checksum",
            requested_at=FETCHED_AT,
            request_metadata={
                "asOf": AS_OF.isoformat(),
                "membershipThscodes": ["885001.TI"],
            },
            progress={
                "membershipCodes": {"885001.TI": {"status": "success", "rows": 2}}
            },
            total_items=5,
            completed_items=5,
        ),
    )
    state.memberships[("885001.TI", AS_OF)] = (
        _membership("885001.TI", "SSE:600001"),
        _membership("885001.TI", "SSE:600002"),
    )
    for index in range(20):
        trading_date = AS_OF - timedelta(days=19 - index)
        state.member_facts[trading_date] = (
            _member_fact("SSE:600001", trading_date, 10.0 + index, 100.0),
            _member_fact("SSE:600002", trading_date, 30.0 - index, 50.0),
        )
    state.limits[AS_OF] = {
        "as_of": AS_OF,
        "actual_as_of": AS_OF,
        "complete": True,
        "source_revision": "limits-v1",
        "facts": (
            {
                "security_id": "SSE:600001",
                "pool_type": "limit_up",
                "eligible": True,
                "membership_valid": True,
                "closed_limit_up": True,
            },
            {
                "security_id": "SSE:600002",
                "pool_type": "limit_down",
                "eligible": True,
                "membership_valid": True,
            },
        ),
    }
    factory = FakeUowFactory(state)
    outcome = ThsSectorBreadthCollector(
        factory,
        lambda: AS_OF,
        clock=lambda: FETCHED_AT,
    ).collect(DatasetDate("sector-breadth", AS_OF))

    assert outcome.state is CollectionTaskState.SUCCESS
    assert len(outcome.candidate.payload["rows"]) == 1
    row = outcome.candidate.payload["rows"][0]
    assert set(row["selectionReasons"]) == {
        "top-10:industry",
        "top-10:cn_concept",
        "top-10:region",
        "top-10:tszs",
        "user-selected",
    }
    assert row["memberCount"] == 2
    assert row["validDirectionCount"] == 2
    assert row["advanceRatio"] == pytest.approx(0.5)
    assert row["ma20Breadth"] == pytest.approx(0.5)
    assert row["limitUpCount"] == 1
    assert row["limitDownCount"] == 1
    assert row["maxMemberTurnoverContribution"] == pytest.approx(2 / 3)
    assert row["diffusionRate"] == pytest.approx(1 / 3)
    assert row["lineage"]["catalogRevision"] == "catalog-r1"

    evidence = ThsSectorBreadthCommitter(factory).commit(_commit_request(outcome))
    assert evidence.writes == ("ths-sector-breadth", "snapshot")
    assert len(state.breadth) == 1
    assert ("sector-breadth", AS_OF) in state.snapshots


def test_historical_sector_collectors_fail_before_provider_or_repository_io() -> None:
    historical = AS_OF - timedelta(days=1)
    calls: list[date] = []
    ranking = ThsIndustryRankingCollector(
        lambda as_of: calls.append(as_of),
        lambda: AS_OF,
    ).collect(DatasetDate("industry-ranking", historical))

    factory = FakeUowFactory(FakeState())
    turnover = ThsSectorTurnoverCollector(factory, lambda: AS_OF).collect(
        DatasetDate("sector-turnover", historical)
    )
    breadth = ThsSectorBreadthCollector(factory, lambda: AS_OF).collect(
        DatasetDate("sector-breadth", historical)
    )

    assert ranking.state is CollectionTaskState.FAILED_MISSING
    assert turnover.state is CollectionTaskState.FAILED_MISSING
    assert breadth.state is CollectionTaskState.FAILED_MISSING
    assert calls == []
    assert factory.calls == 0


def test_ths_detail_projectors_are_provider_free_and_shape_stable() -> None:
    outcome = ThsIndustryRankingCollector(lambda _as_of: _bundle(), lambda: AS_OF).collect(
        DatasetDate("industry-ranking", AS_OF)
    )
    ranking = ThsIndustryRankingProjector().project(outcome.identity, outcome.candidate)
    assert ranking["rowCount"] == 4
    assert ranking["uniqueCodes"] == 3
    assert ranking["tagCounts"] == {tag: 1 for tag in THS_TAGS}

    missing_turnover = ThsSectorTurnoverProjector().project(
        DatasetDate("sector-turnover", AS_OF), None
    )
    missing_breadth = ThsSectorBreadthProjector().project(
        DatasetDate("sector-breadth", AS_OF), None
    )
    assert missing_turnover["state"] == "missing"
    assert missing_breadth["rowCount"] == 0
