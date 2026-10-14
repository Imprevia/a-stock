from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from src.market_environment.application.commands.ths_sector_operations import (
    CatalogSyncRequest,
    MemberImportRequest,
    ThsCatalogSyncService,
    ThsMemberImportService,
    ThsOperationGates,
    ThsOperationGateError,
    ThsTurnoverBackfillService,
    TurnoverBackfillRequest,
)
from src.market_environment.domain.models.ths_sector import (
    ThsBackfillCheckpoint,
    ThsBackfillRun,
    ThsCatalogRelation,
    ThsCatalogRevision,
    ThsOperation,
    ThsRankingRow,
    ThsSectorBar,
    ThsSnapshotFact,
)
from src.market_environment.domain.analysis.ths_sector import (
    catalog_checksum,
    catalog_observation_revision_id,
)
from src.market_environment.infrastructure.providers.fuyao.ths_dump import (
    ThsDumpContractError,
    ThsDumpManifest,
    merge_member_facts,
)
from src.market_environment.infrastructure.providers.fuyao.ths_sector import (
    ThsCatalogSnapshotBundle,
)


AS_OF = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)


class _Store:
    def __init__(self) -> None:
        self.operations: dict[str, ThsOperation] = {}
        self.runs: dict[str, ThsBackfillRun] = {}
        self.checkpoints: dict[tuple[object, ...], ThsBackfillCheckpoint] = {}
        self.catalog_revision: ThsCatalogRevision | None = None
        self.catalog_relations: tuple[ThsCatalogRelation, ...] = ()
        self.rankings: list[ThsRankingRow] = []
        self.bars: list[ThsSectorBar] = []
        self.member_facts: list[object] = []
        self.bar_modes: dict[str, str] = {}
        self.member_modes: dict[str, str] = {}
        self.fail_normalized_commit = False
        self.normalized_commits = 0


class _FakeRepository:
    def __init__(self, store: _Store, unit_of_work: "_FakeUnitOfWork") -> None:
        self._store = store
        self._uow = unit_of_work

    def put_operation(self, operation: ThsOperation) -> ThsOperation:
        self._uow.stage(lambda: self._store.operations.__setitem__(operation.run_id, operation))
        return operation

    update_operation = put_operation

    def get_operation(self, run_id: str) -> ThsOperation | None:
        return self._store.operations.get(run_id)

    def put_catalog_revision(self, revision, relations):
        rows = tuple(relations)
        self._uow.normalized = True

        def apply() -> None:
            self._store.catalog_revision = revision
            self._store.catalog_relations = rows

        self._uow.stage(apply)
        return revision

    def put_rankings(self, rankings):
        rows = tuple(rankings)
        self._uow.normalized = True
        self._uow.stage(lambda: self._store.rankings.extend(rows))
        return {"inserted": len(rows), "identical": 0, "conflict": 0}

    def put_sector_bars(self, bars):
        rows = tuple(bars)
        self._uow.normalized = True
        inserted = tuple(
            row for row in rows if self._store.bar_modes.get(row.thscode, "inserted") == "inserted"
        )
        identical = sum(
            self._store.bar_modes.get(row.thscode) == "identical" for row in rows
        )
        conflicts = sum(
            self._store.bar_modes.get(row.thscode) == "conflict" for row in rows
        )
        self._uow.stage(lambda: self._store.bars.extend(inserted))
        return {
            "inserted": len(inserted),
            "identical": identical,
            "conflict": conflicts,
        }

    def put_backfill_run(self, run: ThsBackfillRun) -> ThsBackfillRun:
        existing = self._store.operations.get(run.run_id)
        operation = ThsOperation(
            run_id=run.run_id,
            kind="turnover-backfill",
            status=run.status,
            capability_revision=run.capability_revision,
            request_checksum=(existing.request_checksum if existing else f"request-{run.run_id}"),
            requested_at=existing.requested_at if existing else NOW,
            started_at=existing.started_at if existing else NOW,
            completed_at=existing.completed_at if existing else None,
            request_metadata={
                "thscodes": list(run.thscodes),
                "startDate": run.start_date.isoformat(),
                "endDate": run.end_date.isoformat(),
            },
            total_items=len(run.thscodes),
            request_budget=run.request_budget,
            requests_used=run.requests_used,
            warning=run.warning,
        )
        self._uow.stage(lambda: self._store.runs.__setitem__(run.run_id, run))
        self._uow.stage(lambda: self._store.operations.__setitem__(run.run_id, operation))
        return run

    def get_backfill_run(self, run_id: str) -> ThsBackfillRun | None:
        return self._store.runs.get(run_id)

    def put_backfill_checkpoint(self, checkpoint: ThsBackfillCheckpoint):
        key = (
            checkpoint.run_id,
            checkpoint.thscode,
            checkpoint.window_start,
            checkpoint.window_end,
        )
        self._uow.stage(lambda: self._store.checkpoints.__setitem__(key, checkpoint))
        return checkpoint

    def list_backfill_checkpoints(self, run_id: str):
        return tuple(
            sorted(
                (
                    item
                    for item in self._store.checkpoints.values()
                    if item.run_id == run_id
                ),
                key=lambda item: (item.thscode, item.window_start, item.window_end),
            )
        )

    def put_member_fact(self, fact):
        mode = self._store.member_modes.get(fact.security_id, "inserted")
        if mode == "inserted":
            self._uow.normalized = True
            self._uow.stage(lambda: self._store.member_facts.append(fact))
        return mode


class _FakeUnitOfWork:
    def __init__(self, store: _Store) -> None:
        self._store = store
        self._actions: list[object] = []
        self.normalized = False
        self.ths_sectors = _FakeRepository(store, self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._actions.clear()

    def stage(self, action) -> None:
        self._actions.append(action)

    def commit(self) -> None:
        if self.normalized and self._store.fail_normalized_commit:
            raise RuntimeError("normalized transaction failed")
        for action in self._actions:
            action()
        if self.normalized:
            self._store.normalized_commits += 1
        self._actions.clear()


class _Policy:
    def __init__(self, *, budget: int = 100, error: Exception | None = None) -> None:
        self.budget = budget
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def require(self, dataset: str, revision: str):
        self.calls.append((dataset, revision))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(rate_limit_evidence={"requestBudget": self.budget})


class _Client:
    def __init__(self) -> None:
        self.request_count = 0
        self.request_budget = 100


class _CatalogAdapter:
    def __init__(self, bundle: ThsCatalogSnapshotBundle, *, request_count: int = 5) -> None:
        self.bundle = bundle
        self.requests = request_count
        self.client = _Client()

    def fetch_catalog_snapshot(self, as_of: date):
        assert as_of == AS_OF
        self.client.request_count += self.requests
        return self.bundle


class _HistoryAdapter:
    def __init__(self, behavior: dict[str, str] | None = None) -> None:
        self.behavior = behavior or {}
        self.client = _Client()
        self.calls: list[str] = []

    def fetch_history(self, thscode: str, *, start_date: date, end_date: date):
        self.calls.append(thscode)
        behavior = self.behavior.get(thscode, "success")
        if behavior == "pre-io-failure":
            raise RuntimeError(f"provider rejected {thscode} before I/O")
        self.client.request_count += 1
        if behavior == "post-io-failure":
            raise RuntimeError(f"provider failed {thscode} after I/O")
        return (_bar(thscode, start_date),)


class _DumpReader:
    def __init__(self, *, fail_kind: str | None = None) -> None:
        self.fail_kind = fail_kind
        self.calls: list[str] = []

    def read(self, path, manifest: ThsDumpManifest):
        self.calls.append(manifest.kind)
        if manifest.kind == self.fail_kind:
            raise ThsDumpContractError(f"{manifest.kind} dump schema/checksum invalid")
        if manifest.kind == "adjustment":
            return (
                {
                    "security_id": "000001.SZ",
                    "date": AS_OF,
                    "adjustment_factor": 1.1,
                },
            )
        return (
            {
                "security_id": "000001.SZ",
                "date": AS_OF,
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 100.0,
                "turnover": 1000.0,
            },
        )


def _factory(store: _Store):
    return lambda: _FakeUnitOfWork(store)


def _gates(*, enabled: bool = True) -> ThsOperationGates:
    return ThsOperationGates(enabled, True, lambda _date: True)


def _catalog_bundle() -> ThsCatalogSnapshotBundle:
    tags = ("industry", "cn_concept", "region", "tszs")
    relations = tuple(
        ThsCatalogRelation("catalog-r1", tag, f"{index:06d}.TI", f"Sector {index}")
        for index, tag in enumerate(tags, start=1)
    )
    snapshots = tuple(
        ThsSnapshotFact(
            thscode=relation.thscode,
            name=relation.name,
            as_of=AS_OF,
            provider_timestamp=NOW,
            change_pct=float(index),
            open=10.0,
            high=12.0,
            low=9.0,
            close=11.0,
            volume=100.0 * index,
            turnover=1000.0 * index,
        )
        for index, relation in enumerate(relations, start=1)
    )
    checksum = catalog_checksum(relations)
    revision_id = catalog_observation_revision_id(
        provider="fuyao",
        capability_revision="catalog-cap-r1",
        as_of=AS_OF,
        checksum=checksum,
    )
    relations = tuple(replace(relation, revision_id=revision_id) for relation in relations)
    rankings = tuple(
        ThsRankingRow(
            tag=relation.tag,
            rank=1,
            thscode=relation.thscode,
            name=relation.name,
            change_pct=snapshot.change_pct,
            volume=snapshot.volume,
            turnover=snapshot.turnover,
            catalog_revision=revision_id,
            as_of=AS_OF,
        )
        for relation, snapshot in zip(relations, snapshots, strict=True)
    )
    revision = ThsCatalogRevision(
        revision_id=revision_id,
        capability_revision="catalog-cap-r1",
        provider_timestamp=NOW,
        fetched_at=NOW,
        tag_counts={tag: 1 for tag in tags},
        checksum=checksum,
    )
    return ThsCatalogSnapshotBundle(revision, relations, snapshots, rankings)


def _bar(thscode: str, trading_date: date) -> ThsSectorBar:
    return ThsSectorBar(
        thscode=thscode,
        trading_date=trading_date,
        open=10.0,
        high=12.0,
        low=9.0,
        close=11.0,
        volume=100.0,
        turnover=1000.0,
        source="fuyao",
        source_revision="history-cap-r1",
        checksum=f"bar-{thscode}-{trading_date.isoformat()}",
        fetched_at=NOW,
    )


def _manifest(kind: str) -> ThsDumpManifest:
    return ThsDumpManifest(
        dump_id=f"{kind}-dump-r1",
        kind=kind,
        schema_revision=f"{kind}-schema-r1",
        capability_revision=f"sector-member-{kind}-dump-r1",
        checksum=f"{kind}-checksum-r1",
        start_date=AS_OF,
        end_date=AS_OF,
    )


def _assert_operation_totals(operation: ThsOperation) -> None:
    assert (
        operation.completed_items + operation.failed_items + operation.conflict_items
        <= operation.total_items
    )


def test_catalog_sync_commits_complete_normalized_bundle_once() -> None:
    store = _Store()
    adapter = _CatalogAdapter(_catalog_bundle())
    service = ThsCatalogSyncService(
        _factory(store),
        adapter_factory=lambda: adapter,
        capability_policy=_Policy(budget=5),
        gates=_gates(),
        clock=lambda: NOW,
    )

    bundle, operation = service.run(
        CatalogSyncRequest(AS_OF, "catalog-cap-r1", 5, run_id="catalog-run")
    )

    assert store.normalized_commits == 1
    assert store.catalog_revision == bundle.revision
    assert store.catalog_relations == bundle.relations
    assert store.rankings == list(bundle.rankings)
    assert len(store.bars) == len(bundle.snapshots)
    assert operation.status == "success"
    assert operation.requests_used == 5
    assert operation.completed_items == operation.total_items == 4
    _assert_operation_totals(operation)


def test_catalog_sync_persists_failure_after_normalized_transaction_rolls_back() -> None:
    store = _Store()
    store.fail_normalized_commit = True
    adapter = _CatalogAdapter(_catalog_bundle())
    service = ThsCatalogSyncService(
        _factory(store),
        adapter_factory=lambda: adapter,
        capability_policy=_Policy(budget=5),
        gates=_gates(),
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="normalized transaction failed"):
        service.run(CatalogSyncRequest(AS_OF, "catalog-cap-r1", 5, run_id="catalog-failed"))

    assert store.catalog_revision is None
    assert store.catalog_relations == ()
    assert store.rankings == []
    assert store.bars == []
    operation = store.operations["catalog-failed"]
    assert operation.status == "failed"
    assert operation.failed_items == operation.total_items == 4
    assert operation.requests_used == 5
    _assert_operation_totals(operation)


@pytest.mark.parametrize("failure", ["gate", "capability", "budget"])
def test_catalog_preflight_failure_constructs_no_adapter_or_operation(failure: str) -> None:
    store = _Store()
    adapter_calls = 0

    def adapter_factory():
        nonlocal adapter_calls
        adapter_calls += 1
        return _CatalogAdapter(_catalog_bundle())

    gates = _gates(enabled=failure != "gate")
    policy = _Policy(
        budget=4 if failure == "budget" else 5,
        error=RuntimeError("capability unavailable") if failure == "capability" else None,
    )
    service = ThsCatalogSyncService(
        _factory(store),
        adapter_factory=adapter_factory,
        capability_policy=policy,
        gates=gates,
        clock=lambda: NOW,
    )

    with pytest.raises((RuntimeError, ThsOperationGateError)):
        service.run(CatalogSyncRequest(AS_OF, "catalog-cap-r1", 5, run_id="preflight"))

    assert adapter_calls == 0
    assert store.operations == {}


def test_backfill_isolates_one_code_failure_and_counts_only_actual_io() -> None:
    store = _Store()
    adapter = _HistoryAdapter({"000002.TI": "pre-io-failure"})
    service = ThsTurnoverBackfillService(
        _factory(store),
        adapter_factory=lambda: adapter,
        capability_policy=_Policy(budget=2),
        gates=_gates(),
        clock=lambda: NOW,
    )

    result = service.run(
        TurnoverBackfillRequest(
            ("000001.TI", "000002.TI"),
            AS_OF,
            AS_OF,
            "history-cap-r1",
            2,
            run_id="backfill-partial",
        )
    )

    assert result.status == "partial"
    assert result.requests_used == adapter.client.request_count == 1
    assert [bar.thscode for bar in store.bars] == ["000001.TI"]
    statuses = {item.thscode: item.status for item in store.checkpoints.values()}
    assert statuses == {"000001.TI": "success", "000002.TI": "failed"}
    operation = store.operations["backfill-partial"]
    assert (operation.total_items, operation.completed_items, operation.failed_items) == (2, 1, 1)
    _assert_operation_totals(operation)


def test_backfill_resume_skips_successful_checkpoint() -> None:
    store = _Store()
    run_id = "backfill-resume"
    store.runs[run_id] = ThsBackfillRun(
        run_id,
        ("000001.TI", "000002.TI"),
        AS_OF,
        AS_OF,
        "history-cap-r1",
        2,
        status="partial",
        requests_used=1,
    )
    checkpoint = ThsBackfillCheckpoint(
        run_id,
        "000001.TI",
        AS_OF,
        AS_OF,
        "success",
        "history-cap-r1",
        rows_written=1,
    )
    store.checkpoints[(run_id, "000001.TI", AS_OF, AS_OF)] = checkpoint
    adapter = _HistoryAdapter()
    service = ThsTurnoverBackfillService(
        _factory(store),
        adapter_factory=lambda: adapter,
        capability_policy=_Policy(budget=2),
        gates=_gates(),
        clock=lambda: NOW,
    )

    result = service.run(
        TurnoverBackfillRequest(
            ("000001.TI", "000002.TI"),
            AS_OF,
            AS_OF,
            "history-cap-r1",
            2,
            run_id=run_id,
        )
    )

    assert result.status == "success"
    assert result.requests_used == 2
    assert adapter.calls == ["000002.TI"]
    operation = store.operations[run_id]
    assert operation.completed_items == operation.total_items == 2
    _assert_operation_totals(operation)


def test_backfill_exhausted_budget_performs_no_new_provider_io() -> None:
    store = _Store()
    run_id = "backfill-exhausted"
    store.runs[run_id] = ThsBackfillRun(
        run_id,
        ("000001.TI",),
        AS_OF,
        AS_OF,
        "history-cap-r1",
        1,
        status="partial",
        requests_used=1,
    )
    adapter_calls = 0

    def adapter_factory():
        nonlocal adapter_calls
        adapter_calls += 1
        return _HistoryAdapter()

    service = ThsTurnoverBackfillService(
        _factory(store),
        adapter_factory=adapter_factory,
        capability_policy=_Policy(budget=1),
        gates=_gates(),
        clock=lambda: NOW,
    )

    result = service.run(
        TurnoverBackfillRequest(
            ("000001.TI",),
            AS_OF,
            AS_OF,
            "history-cap-r1",
            1,
            run_id=run_id,
        )
    )

    assert adapter_calls == 0
    assert result.requests_used == 1
    assert result.status == "failed"
    operation = store.operations[run_id]
    assert operation.requests_used == 1
    assert operation.failed_items == operation.total_items == 1
    _assert_operation_totals(operation)


def test_backfill_preflight_budget_failure_performs_no_provider_io() -> None:
    store = _Store()
    adapter_calls = 0

    def adapter_factory():
        nonlocal adapter_calls
        adapter_calls += 1
        return _HistoryAdapter()

    service = ThsTurnoverBackfillService(
        _factory(store),
        adapter_factory=adapter_factory,
        capability_policy=_Policy(budget=1),
        gates=_gates(),
        clock=lambda: NOW,
    )

    with pytest.raises(ThsOperationGateError, match="exceeds capability evidence"):
        service.run(
            TurnoverBackfillRequest(
                ("000001.TI",),
                AS_OF,
                AS_OF,
                "history-cap-r1",
                2,
                run_id="backfill-preflight",
            )
        )

    assert adapter_calls == 0
    assert store.operations == {}


def test_backfill_identical_rows_are_skipped_idempotently() -> None:
    store = _Store()
    store.bar_modes["000001.TI"] = "identical"
    adapter = _HistoryAdapter()
    service = ThsTurnoverBackfillService(
        _factory(store),
        adapter_factory=lambda: adapter,
        capability_policy=_Policy(budget=1),
        gates=_gates(),
        clock=lambda: NOW,
    )

    result = service.run(
        TurnoverBackfillRequest(
            ("000001.TI",),
            AS_OF,
            AS_OF,
            "history-cap-r1",
            1,
            run_id="backfill-identical",
        )
    )

    assert result.status == "success"
    assert store.bars == []
    checkpoint = next(iter(store.checkpoints.values()))
    assert checkpoint.status == "success"
    assert checkpoint.rows_written == 0
    assert checkpoint.rows_skipped == 1


def test_backfill_conflict_is_retained_and_counted() -> None:
    store = _Store()
    store.bar_modes["000001.TI"] = "conflict"
    adapter = _HistoryAdapter()
    service = ThsTurnoverBackfillService(
        _factory(store),
        adapter_factory=lambda: adapter,
        capability_policy=_Policy(budget=1),
        gates=_gates(),
        clock=lambda: NOW,
    )

    result = service.run(
        TurnoverBackfillRequest(
            ("000001.TI",),
            AS_OF,
            AS_OF,
            "history-cap-r1",
            1,
            run_id="backfill-conflict",
        )
    )

    assert result.status == "conflict"
    assert store.bars == []
    checkpoint = next(iter(store.checkpoints.values()))
    assert checkpoint.status == "conflict"
    assert checkpoint.conflicts == 1
    operation = store.operations["backfill-conflict"]
    assert operation.conflict_items == operation.total_items == 1
    _assert_operation_totals(operation)


def test_member_import_capability_failure_reads_and_writes_nothing() -> None:
    store = _Store()
    reader = _DumpReader()
    service = ThsMemberImportService(
        _factory(store),
        reader=reader,
        fact_merger=merge_member_facts,
        capability_policy=_Policy(error=RuntimeError("capability unavailable")),
        gates=_gates(),
        clock=lambda: NOW,
    )
    request = MemberImportRequest(
        as_of=AS_OF,
        daily_path="daily.parquet",
        daily_manifest=_manifest("daily"),
        adjustment_path="adjustment.parquet",
        adjustment_manifest=_manifest("adjustment"),
        source_revision="member-import-r1",
        run_id="member-capability-failed",
    )

    with pytest.raises(RuntimeError, match="capability unavailable"):
        service.run(request)

    assert reader.calls == []
    assert store.operations == {}
    assert store.member_facts == []


def test_member_import_uses_no_request_budget_and_persists_no_sensitive_paths() -> None:
    store = _Store()
    reader = _DumpReader()
    service = ThsMemberImportService(
        _factory(store),
        reader=reader,
        fact_merger=merge_member_facts,
        capability_policy=_Policy(),
        gates=_gates(),
        clock=lambda: NOW,
    )
    request = MemberImportRequest(
        as_of=AS_OF,
        daily_path="https://download.example/daily.parquet?token=top-secret",
        daily_manifest=_manifest("daily"),
        adjustment_path="/private/operator/adjustment.parquet",
        adjustment_manifest=_manifest("adjustment"),
        source_revision="member-import-r1",
        run_id="member-import",
    )

    operation = service.run(request)

    assert operation.status == "success"
    assert operation.request_budget is None
    assert operation.requests_used == 0
    assert len(store.member_facts) == 1
    persisted = json.dumps(operation.request_metadata, sort_keys=True)
    for sensitive in (
        "download.example",
        "top-secret",
        "/private/operator",
        "raw_response",
    ):
        assert sensitive not in persisted
    assert operation.completed_items == operation.total_items == 2
    _assert_operation_totals(operation)


@pytest.mark.parametrize("fail_kind", ["daily", "adjustment"])
def test_member_import_bad_schema_or_checksum_writes_no_facts(fail_kind: str) -> None:
    store = _Store()
    reader = _DumpReader(fail_kind=fail_kind)
    service = ThsMemberImportService(
        _factory(store),
        reader=reader,
        fact_merger=merge_member_facts,
        capability_policy=_Policy(),
        gates=_gates(),
        clock=lambda: NOW,
    )
    request = MemberImportRequest(
        as_of=AS_OF,
        daily_path="daily.parquet",
        daily_manifest=_manifest("daily"),
        adjustment_path="adjustment.parquet",
        adjustment_manifest=_manifest("adjustment"),
        source_revision="member-import-r1",
        run_id=f"member-import-{fail_kind}",
    )

    with pytest.raises(ThsDumpContractError, match="schema/checksum invalid"):
        service.run(request)

    assert store.member_facts == []
    operation = store.operations[request.run_id]
    assert operation.status == "failed"
    assert operation.request_budget is None
    assert operation.failed_items == operation.total_items == 2
    _assert_operation_totals(operation)
