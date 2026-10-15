from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from types import SimpleNamespace

import pytest

from src.market_environment.application.commands import (
    FullCollectionBeforeSettlementError,
    FullCollectionCommand,
    FullCollectionIdempotencyConflictError,
    FullCollectionRunResult,
    FullCollectionSkippedResult,
)
from src.market_environment.domain.models import (
    CANONICAL_FULL_COLLECTION_DATASETS,
    FullCollectionSemantics,
    IdempotencyBinding,
    IdempotencyClaim,
    IdempotencyClaimDisposition,
    IdempotencyKey,
    SubmissionState,
)


KEY = IdempotencyKey("hermes-market-collection-2026-10-15-1630")
BOUNDARY = time(15, 10)


def _run(status: str, run_id: str = "run-original"):
    return SimpleNamespace(run=SimpleNamespace(run_id=run_id, status=status))


def _binding(
    semantics: FullCollectionSemantics,
    *,
    run_id: str = "run-original",
    state: SubmissionState = SubmissionState.RESERVED,
) -> IdempotencyBinding:
    now = datetime(2026, 10, 15, 7, 10, tzinfo=timezone.utc)
    return IdempotencyBinding(
        operation_scope=semantics.operation_scope,
        key=KEY,
        semantic_fingerprint=semantics.semantic_fingerprint,
        resolved_as_of=semantics.resolved_as_of,
        operation_version=semantics.operation_version,
        dataset_fingerprint=semantics.dataset_fingerprint,
        run_id=run_id,
        submission_state=state,
        submission_attempts=1 if state is SubmissionState.SUBMITTED else 0,
        created_at=now,
        updated_at=now,
    )


class _ClaimRepository:
    def __init__(
        self,
        disposition: IdempotencyClaimDisposition,
        *,
        binding: IdempotencyBinding | None = None,
    ) -> None:
        self.disposition = disposition
        self.binding = binding
        self.calls: list[dict] = []

    def claim(self, key, semantics, *, run_id, task_ids, now):
        self.calls.append(
            {
                "key": key,
                "semantics": semantics,
                "run_id": run_id,
                "task_ids": task_ids,
                "now": now,
            }
        )
        binding = self.binding or _binding(semantics, run_id=run_id)
        return IdempotencyClaim(self.disposition, binding)


class _UnitOfWork:
    def __init__(self, repository: _ClaimRepository) -> None:
        self.collection_idempotency = repository
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


class _UnitOfWorkFactory:
    def __init__(self, repository: _ClaimRepository) -> None:
        self.unit_of_work = _UnitOfWork(repository)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.unit_of_work


class _Queries:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    def get_run(self, run_id: str):
        self.calls.append(run_id)
        if not self.results:
            raise AssertionError("unexpected persisted run read")
        if len(self.results) == 1:
            return self.results[0]
        return self.results.pop(0)


class _SubmissionService:
    def __init__(self, repository: _ClaimRepository) -> None:
        self.repository = repository
        self.calls: list[tuple[str, IdempotencyKey, str]] = []

    def submit(self, operation_scope: str, key: IdempotencyKey, run_id: str):
        self.calls.append((operation_scope, key, run_id))
        call = self.repository.calls[-1]
        current = self.repository.binding or _binding(
            call["semantics"],
            run_id=run_id,
        )
        submitted = IdempotencyBinding(
            operation_scope=current.operation_scope,
            key=current.key,
            semantic_fingerprint=current.semantic_fingerprint,
            resolved_as_of=current.resolved_as_of,
            operation_version=current.operation_version,
            dataset_fingerprint=current.dataset_fingerprint,
            run_id=current.run_id,
            submission_state=SubmissionState.SUBMITTED,
            submission_attempts=current.submission_attempts + 1,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        return SimpleNamespace(disposition="submitted", binding=submitted)


@dataclass
class _Fixture:
    command: FullCollectionCommand
    repository: _ClaimRepository
    unit_of_work_factory: _UnitOfWorkFactory
    queries: _Queries
    submissions: _SubmissionService


def _command_fixture(
    now: datetime,
    *,
    disposition: IdempotencyClaimDisposition = IdempotencyClaimDisposition.CREATED,
    binding: IdempotencyBinding | None = None,
    query_results=(_run("queued"), _run("collecting")),
    identifiers: tuple[str, ...] = (
        "run-new",
        "task-core",
        "task-breadth",
        "task-limits",
        "task-industry-ranking",
        "task-sector-turnover",
        "task-sector-breadth",
        "task-active-direction",
    ),
) -> _Fixture:
    repository = _ClaimRepository(disposition, binding=binding)
    unit_of_work_factory = _UnitOfWorkFactory(repository)
    queries = _Queries(query_results)
    submissions = _SubmissionService(repository)
    generated = iter(identifiers)
    command = FullCollectionCommand(
        unit_of_work_factory=unit_of_work_factory,
        submission_service=submissions,  # type: ignore[arg-type]
        queries=queries,  # type: ignore[arg-type]
        clock=lambda: now,
        settlement_boundary=BOUNDARY,
        identifier_factory=lambda: next(generated),
    )
    return _Fixture(
        command,
        repository,
        unit_of_work_factory,
        queries,
        submissions,
    )


@pytest.mark.parametrize(
    "now, expected_date",
    (
        (datetime(2026, 10, 15, 7, 10, tzinfo=timezone.utc), date(2026, 10, 15)),
        (datetime(2026, 10, 15, 15, 10), date(2026, 10, 15)),
    ),
)
def test_settlement_boundary_resolves_shanghai_date_and_claims_canonical_tuple(
    now: datetime,
    expected_date: date,
) -> None:
    fixture = _command_fixture(now)

    result = fixture.command.execute(KEY)

    assert isinstance(result, FullCollectionRunResult)
    assert result.resolved_as_of == expected_date
    assert result.datasets == CANONICAL_FULL_COLLECTION_DATASETS
    assert result.claim_disposition is IdempotencyClaimDisposition.CREATED
    assert result.binding.submission_state is SubmissionState.SUBMITTED
    assert fixture.unit_of_work_factory.calls == 1
    assert fixture.unit_of_work_factory.unit_of_work.commits == 1
    assert len(fixture.repository.calls) == 1
    claim = fixture.repository.calls[0]
    assert claim["semantics"].resolved_as_of == expected_date
    assert claim["semantics"].datasets == CANONICAL_FULL_COLLECTION_DATASETS
    assert tuple(claim["task_ids"]) == CANONICAL_FULL_COLLECTION_DATASETS
    assert tuple(claim["task_ids"].values()) == (
        "task-core",
        "task-breadth",
        "task-limits",
        "task-industry-ranking",
        "task-sector-turnover",
        "task-sector-breadth",
        "task-active-direction",
    )
    assert fixture.submissions.calls == [
        (claim["semantics"].operation_scope, KEY, result.run_id)
    ]


@pytest.mark.parametrize(
    "now, expected_date",
    (
        (datetime(2026, 10, 17, 8, 0), date(2026, 10, 17)),
        (
            datetime(2026, 10, 16, 16, 30, tzinfo=timezone.utc),
            date(2026, 10, 17),
        ),
        (
            datetime(2026, 10, 18, 1, 0, tzinfo=timezone.utc),
            date(2026, 10, 18),
        ),
    ),
)
def test_weekend_returns_structured_skip_before_any_io(
    now: datetime,
    expected_date: date,
) -> None:
    fixture = _command_fixture(now, query_results=())

    result = fixture.command.execute(KEY)

    assert result == FullCollectionSkippedResult(resolved_as_of=expected_date)
    assert result.status == "skipped"
    assert result.reason == "weekend"
    assert result.run_id is None
    assert result.datasets == CANONICAL_FULL_COLLECTION_DATASETS
    assert fixture.unit_of_work_factory.calls == 0
    assert fixture.repository.calls == []
    assert fixture.queries.calls == []
    assert fixture.submissions.calls == []


def test_weekday_before_settlement_is_typed_rejection_before_any_io() -> None:
    fixture = _command_fixture(datetime(2026, 10, 15, 15, 9, 59), query_results=())

    with pytest.raises(FullCollectionBeforeSettlementError) as rejected:
        fixture.command.execute(KEY)

    assert rejected.value.code == "before-settlement"
    assert rejected.value.resolved_as_of == date(2026, 10, 15)
    assert rejected.value.settlement_boundary == BOUNDARY
    assert fixture.unit_of_work_factory.calls == 0
    assert fixture.repository.calls == []
    assert fixture.queries.calls == []
    assert fixture.submissions.calls == []


def test_matching_replay_submits_only_the_original_recoverable_run() -> None:
    semantics = FullCollectionSemantics.create(date(2026, 10, 15))
    existing = _binding(
        semantics,
        run_id="run-original",
        state=SubmissionState.SUBMISSION_FAILED,
    )
    fixture = _command_fixture(
        datetime(2026, 10, 15, 15, 10),
        disposition=IdempotencyClaimDisposition.REPLAY,
        binding=existing,
    )

    result = fixture.command.execute(KEY)

    assert isinstance(result, FullCollectionRunResult)
    assert result.run_id == "run-original"
    assert result.claim_disposition is IdempotencyClaimDisposition.REPLAY
    assert fixture.repository.calls[0]["run_id"] == "run-new"
    assert fixture.submissions.calls == [
        (semantics.operation_scope, KEY, "run-original")
    ]


def test_conflicting_key_raises_typed_error_without_submission_or_run_read() -> None:
    original_semantics = FullCollectionSemantics.create(date(2026, 10, 14))
    existing = _binding(original_semantics, run_id="run-original")
    fixture = _command_fixture(
        datetime(2026, 10, 15, 15, 10),
        disposition=IdempotencyClaimDisposition.CONFLICT,
        binding=existing,
        query_results=(),
    )

    with pytest.raises(FullCollectionIdempotencyConflictError) as conflict:
        fixture.command.execute(KEY)

    assert conflict.value.code == "idempotency-key-conflict"
    assert conflict.value.binding.run_id == "run-original"
    assert conflict.value.requested.resolved_as_of == date(2026, 10, 15)
    assert fixture.unit_of_work_factory.calls == 1
    assert fixture.unit_of_work_factory.unit_of_work.commits == 1
    assert fixture.queries.calls == []
    assert fixture.submissions.calls == []


def test_terminal_submitted_replay_returns_persisted_run_without_recollection() -> None:
    semantics = FullCollectionSemantics.create(date(2026, 10, 15))
    existing = _binding(
        semantics,
        run_id="run-original",
        state=SubmissionState.SUBMITTED,
    )
    terminal = _run("partial")
    fixture = _command_fixture(
        datetime(2026, 10, 15, 15, 10),
        disposition=IdempotencyClaimDisposition.REPLAY,
        binding=existing,
        query_results=(terminal,),
    )

    result = fixture.command.execute(KEY)

    assert isinstance(result, FullCollectionRunResult)
    assert result.run is terminal
    assert result.submission is None
    assert fixture.queries.calls == ["run-original"]
    assert fixture.submissions.calls == []


def test_zero_second_wait_reads_persisted_run_once_without_submission() -> None:
    current = _run("collecting")
    fixture = _command_fixture(
        datetime(2026, 10, 15, 15, 10),
        query_results=(current,),
    )

    observed = fixture.command.wait("run-original", 0)

    assert observed is current
    assert fixture.queries.calls == ["run-original"]
    assert fixture.submissions.calls == []
    assert fixture.unit_of_work_factory.calls == 0


def test_wait_returns_terminal_first_read_without_touching_any_timer() -> None:
    terminal = _run("failed")
    fixture = _command_fixture(
        datetime(2026, 10, 15, 15, 10),
        query_results=(terminal,),
    )
    fixture.command = FullCollectionCommand(
        unit_of_work_factory=fixture.unit_of_work_factory,
        submission_service=fixture.submissions,  # type: ignore[arg-type]
        queries=fixture.queries,  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 10, 15, 15, 10),
        settlement_boundary=BOUNDARY,
        monotonic_clock=lambda: (_ for _ in ()).throw(
            AssertionError("terminal wait must not read monotonic time")
        ),
        sleeper=lambda _seconds: (_ for _ in ()).throw(
            AssertionError("terminal wait must not sleep")
        ),
    )

    observed = fixture.command.wait("run-original", 900)

    assert observed is terminal
    assert fixture.queries.calls == ["run-original"]
    assert fixture.submissions.calls == []
    assert fixture.unit_of_work_factory.calls == 0


def test_wait_uses_fake_monotonic_clock_until_persisted_terminal_state() -> None:
    ticks = [0.0]
    sleeps: list[float] = []
    queries = _Queries((_run("collecting"), _run("collecting"), _run("success")))
    fixture = _command_fixture(
        datetime(2026, 10, 15, 15, 10),
        query_results=(),
    )

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        ticks[0] += seconds

    fixture.command = FullCollectionCommand(
        unit_of_work_factory=fixture.unit_of_work_factory,
        submission_service=fixture.submissions,  # type: ignore[arg-type]
        queries=queries,  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 10, 15, 15, 10),
        settlement_boundary=BOUNDARY,
        monotonic_clock=lambda: ticks[0],
        sleeper=fake_sleep,
        poll_interval_seconds=1,
    )

    observed = fixture.command.wait("run-original", 5)

    assert observed.run.status == "success"
    assert sleeps == [1, 1]
    assert queries.calls == ["run-original"] * 3
    assert fixture.submissions.calls == []
    assert fixture.unit_of_work_factory.calls == 0


def test_wait_timeout_returns_latest_persisted_state_without_cancelling_work() -> None:
    ticks = [10.0]
    sleeps: list[float] = []
    first = _run("queued")
    latest = _run("collecting")
    queries = _Queries((first, latest, latest))
    fixture = _command_fixture(
        datetime(2026, 10, 15, 15, 10),
        query_results=(),
    )

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        ticks[0] += seconds

    fixture.command = FullCollectionCommand(
        unit_of_work_factory=fixture.unit_of_work_factory,
        submission_service=fixture.submissions,  # type: ignore[arg-type]
        queries=queries,  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 10, 15, 15, 10),
        settlement_boundary=BOUNDARY,
        monotonic_clock=lambda: ticks[0],
        sleeper=fake_sleep,
        poll_interval_seconds=1,
    )

    observed = fixture.command.wait("run-original", 2)

    assert observed is latest
    assert sleeps == [1, 1]
    assert fixture.submissions.calls == []
    assert fixture.unit_of_work_factory.calls == 0


@pytest.mark.parametrize("timeout_seconds", (-0.1, 900.1))
def test_wait_rejects_unbounded_timeout_without_io(timeout_seconds: float) -> None:
    fixture = _command_fixture(
        datetime(2026, 10, 15, 15, 10),
        query_results=(),
    )

    with pytest.raises(ValueError, match="between 0 and 900"):
        fixture.command.wait("run-original", timeout_seconds)

    assert fixture.queries.calls == []
    assert fixture.submissions.calls == []
    assert fixture.unit_of_work_factory.calls == 0
