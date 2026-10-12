"""Narrow persistence protocols owned by application use cases."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any, Literal, Protocol, runtime_checkable

from ...domain.models import (
    CollectionCandidate,
    DatasetDate,
    MaterializationRevision,
)
from ...domain.models.sector_continuity import (
    BackfillDateAttempt,
    BackfillRun,
    BenchmarkFact,
    IndustryAggregate,
    IndustryIdentity,
    MembershipInterval,
    SecurityDailyFact,
    SectorContinuityResult,
    TaxonomyRevision,
)
from ...domain.models.ths_sector import (
    ThsBackfillCheckpoint,
    ThsBackfillRun,
    ThsCatalogRelation,
    ThsCatalogRevision,
    ThsMemberDailyFact,
    ThsOperation,
    ThsRankingRow,
    ThsSectorBar,
    ThsSectorBreadth,
    ThsSectorMembership,
)


@runtime_checkable
class SnapshotReader(Protocol):
    def get(self, identity: DatasetDate) -> CollectionCandidate | None: ...

    def list_dates(self, dataset: str) -> Sequence[date]: ...


@runtime_checkable
class SnapshotRepository(SnapshotReader, Protocol):
    def put(self, candidate: CollectionCandidate) -> CollectionCandidate: ...


@runtime_checkable
class CollectionRunRepository(Protocol):
    def get_run(self, run_id: str) -> object | None: ...

    def save_run(self, run: object) -> object: ...


@runtime_checkable
class CollectionTaskRepository(Protocol):
    def get_task(self, task_id: str) -> object | None: ...

    def list_tasks(self, run_id: str) -> Sequence[object]: ...

    def save_task(self, task: object) -> object: ...


@runtime_checkable
class CoreIndexResultRepository(Protocol):
    def list_results(self, task_id: str) -> Sequence[object]: ...

    def put_result(self, result: object) -> object: ...


@runtime_checkable
class CollectionStatusReader(Protocol):
    def collection_status(self, as_of: date) -> Mapping[str, Any]: ...

    def get_run(self, run_id: str) -> object | None: ...


@runtime_checkable
class LeaseRepository(Protocol):
    def acquire(self, identity: DatasetDate, owner: str, *, lease_seconds: float) -> object | None: ...

    def renew(self, lease: object, *, lease_seconds: float) -> object | None: ...

    def release(self, lease: object) -> bool: ...

    def execute_fenced(
        self,
        lease: object,
        operation: str,
        writer: object,
        *,
        expected_identity: DatasetDate | None = None,
    ) -> object: ...

    def list_fence_events(
        self,
        *,
        identity: DatasetDate | None = None,
    ) -> Sequence[Mapping[str, Any]]: ...


@runtime_checkable
class TradingSessionReader(Protocol):
    def get_session(self, as_of: date) -> object | None: ...

    def list_sessions(self, *, after: date | None = None) -> Sequence[object]: ...


@runtime_checkable
class TradingSessionRepository(TradingSessionReader, Protocol):
    def put_session(self, session: object) -> object: ...

    def put_session_if_absent(self, session: object) -> object: ...


@runtime_checkable
class MaterializedAggregateReader(Protocol):
    def get_aggregate(self, as_of: date) -> Mapping[str, Any] | None: ...


@runtime_checkable
class MaterializedAggregateRepository(MaterializedAggregateReader, Protocol):
    def revision(self, as_of: date) -> MaterializationRevision: ...

    def compare_and_swap(
        self,
        as_of: date,
        expected: MaterializationRevision,
        payload: Mapping[str, Any],
    ) -> MaterializationRevision: ...


@runtime_checkable
class ProviderCapabilityRepository(Protocol):
    def get_capability(
        self,
        provider: str,
        dataset: str,
        revision: str,
    ) -> Mapping[str, Any] | None: ...

    def put_capability(
        self,
        report: Mapping[str, Any],
    ) -> Literal["inserted", "identical", "conflict"]: ...

    def list_capabilities(
        self,
        *,
        provider: str | None = None,
        dataset: str | None = None,
        status: str | None = None,
    ) -> Sequence[Mapping[str, Any]]: ...


@runtime_checkable
class LimitDetailRepository(Protocol):
    def get_limit_detail(self, as_of: date) -> Mapping[str, Any] | None: ...

    def put_limit_detail(
        self,
        as_of: date,
        manifest: Mapping[str, Any],
        facts: Iterable[object],
    ) -> None: ...


@runtime_checkable
class TimezonePreferenceReader(Protocol):
    def get(
        self,
        scope: str,
        *,
        subject_id: str,
        workspace_id: str,
    ) -> object: ...


@runtime_checkable
class TimezonePreferenceWriter(Protocol):
    def set(
        self,
        scope: str,
        *,
        subject_id: str,
        workspace_id: str,
        timezone_value: str | None,
        actor_id: str,
    ) -> object: ...


@runtime_checkable
class TimezonePreferenceRepository(
    TimezonePreferenceReader,
    TimezonePreferenceWriter,
    Protocol,
):
    pass


@runtime_checkable
class SectorContinuityRepository(Protocol):
    """Application port for immutable point-in-time continuity evidence."""

    def put_taxonomy(self, revision: TaxonomyRevision) -> TaxonomyRevision: ...
    def put_taxonomy_revision(self, revision: TaxonomyRevision) -> TaxonomyRevision: ...
    def get_taxonomy_revision(self, taxonomy_version: str, source_revision: str) -> TaxonomyRevision | None: ...
    def put_industry(self, identity: IndustryIdentity) -> IndustryIdentity: ...
    def list_industries(self, taxonomy_version: str) -> Sequence[IndustryIdentity]: ...
    def put_membership(self, interval: MembershipInterval) -> MembershipInterval: ...
    def list_memberships(self, as_of: date, *, industry_id: str | None = None) -> Sequence[MembershipInterval]: ...
    def put_security_fact(self, fact: SecurityDailyFact) -> SecurityDailyFact: ...
    def get_security_fact(self, security_id: str, as_of: date) -> SecurityDailyFact | None: ...
    def list_security_facts(self, as_of: date) -> Sequence[SecurityDailyFact]: ...
    def put_benchmark_fact(self, fact: BenchmarkFact) -> BenchmarkFact: ...
    def get_benchmark_fact(self, as_of: date, benchmark_id: str = "ordinary-a-share-equal-weight-v1") -> BenchmarkFact | None: ...
    def put_industry_aggregate(self, aggregate: IndustryAggregate) -> IndustryAggregate: ...
    def get_industry_aggregate(self, industry_id: str, as_of: date) -> IndustryAggregate | None: ...
    def list_industry_aggregates(self, as_of: date) -> Sequence[IndustryAggregate]: ...
    def put_result(self, result: SectorContinuityResult) -> SectorContinuityResult: ...
    def get_result(self, as_of: date, calculation_version: str | None = None) -> SectorContinuityResult | None: ...
    def put_backfill_run(self, run: BackfillRun) -> BackfillRun: ...
    def put_backfill_attempt(self, attempt: BackfillDateAttempt) -> BackfillDateAttempt: ...
    def list_backfill_attempts(self, run_id: str) -> Sequence[BackfillDateAttempt]: ...


@runtime_checkable
class ThsSectorRepository(Protocol):
    """Normalized local persistence for provider-observed THS sector facts."""

    def put_catalog_revision(
        self,
        revision: ThsCatalogRevision,
        relations: Sequence[ThsCatalogRelation],
    ) -> ThsCatalogRevision: ...
    def get_catalog_revision(self, revision_id: str) -> ThsCatalogRevision | None: ...
    def latest_catalog_revision(self) -> ThsCatalogRevision | None: ...
    def list_catalog(
        self,
        *,
        tag: str | None = None,
        search: str | None = None,
        revision_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[ThsCatalogRelation]: ...
    def count_catalog(
        self,
        *,
        tag: str | None = None,
        search: str | None = None,
        revision_id: str | None = None,
    ) -> int: ...
    def put_rankings(self, rankings: Iterable[ThsRankingRow]) -> Mapping[str, int]: ...
    def list_rankings(
        self,
        as_of: date,
        *,
        tag: str | None = None,
        revision_id: str | None = None,
    ) -> Sequence[ThsRankingRow]: ...

    def put_sector_bar(self, bar: ThsSectorBar) -> Literal["inserted", "identical", "conflict"]: ...
    def put_sector_bars(self, bars: Iterable[ThsSectorBar]) -> Mapping[str, int]: ...
    def list_sector_bars(
        self,
        thscode: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> Sequence[ThsSectorBar]: ...
    def count_sector_bars(
        self,
        thscode: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int: ...
    def sector_bar_coverage(
        self,
        thscode: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Mapping[str, Any]: ...

    def put_backfill_run(self, run: ThsBackfillRun) -> ThsBackfillRun: ...
    def get_backfill_run(self, run_id: str) -> ThsBackfillRun | None: ...
    def list_backfill_runs(self, *, offset: int = 0, limit: int = 100) -> Sequence[ThsBackfillRun]: ...
    def put_backfill_checkpoint(self, checkpoint: ThsBackfillCheckpoint) -> ThsBackfillCheckpoint: ...
    def list_backfill_checkpoints(self, run_id: str) -> Sequence[ThsBackfillCheckpoint]: ...

    def put_member_fact(self, fact: ThsMemberDailyFact) -> Literal["inserted", "identical", "conflict"]: ...
    def list_member_facts(self, trading_date: date) -> Sequence[ThsMemberDailyFact]: ...
    def put_sector_memberships(
        self,
        memberships: Iterable[ThsSectorMembership],
    ) -> Mapping[str, int]: ...
    def list_sector_memberships(
        self,
        thscode: str,
        *,
        as_of: date | None = None,
        source_revision: str | None = None,
    ) -> Sequence[ThsSectorMembership]: ...
    def put_sector_breadth(self, breadth: ThsSectorBreadth) -> Literal["inserted", "identical", "conflict"]: ...
    def list_sector_breadth(self, as_of: date) -> Sequence[ThsSectorBreadth]: ...

    def put_operation(self, operation: ThsOperation) -> ThsOperation: ...
    def update_operation(self, operation: ThsOperation) -> ThsOperation: ...
    def get_operation(self, run_id: str) -> ThsOperation | None: ...
    def list_operations(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[ThsOperation]: ...


__all__ = [
    "CollectionRunRepository",
    "CollectionStatusReader",
    "CollectionTaskRepository",
    "CoreIndexResultRepository",
    "LeaseRepository",
    "LimitDetailRepository",
    "MaterializedAggregateReader",
    "MaterializedAggregateRepository",
    "ProviderCapabilityRepository",
    "SnapshotReader",
    "SnapshotRepository",
    "TimezonePreferenceReader",
    "TimezonePreferenceRepository",
    "TimezonePreferenceWriter",
    "ThsSectorRepository",
    "TradingSessionReader",
    "TradingSessionRepository",
    "SectorContinuityRepository",
]
