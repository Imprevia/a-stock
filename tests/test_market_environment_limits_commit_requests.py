from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from src.market_environment.application.ports import LimitHistoryPreparationRequest
from src.market_environment.domain.models import (
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
)
from src.market_environment.domain.policies import LimitNormalizationResult
from src.market_environment.infrastructure.collection import (
    LimitsCommitRequestFactory,
    LimitsPreviousSessionEvidenceReader,
    ProviderLimitHistoryPreparer,
)
from src.market_environment.infrastructure.providers.limits_acquisition import (
    LIMITS_RULE_VERSION,
    LimitsCollectionCandidate,
)


CURRENT = date(2026, 9, 18)
PREVIOUS = date(2026, 9, 17)
EARLIER = date(2026, 9, 16)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)


class LocalEvidenceStore:
    def __init__(self, *, previous_complete: bool = True) -> None:
        self.sessions = {
            CURRENT: SimpleNamespace(
                is_session=True,
                actual_as_of=CURRENT,
                previous_as_of=PREVIOUS,
            ),
            PREVIOUS: SimpleNamespace(
                is_session=True,
                actual_as_of=PREVIOUS,
                previous_as_of=EARLIER,
            ),
        }
        self.previous_complete = previous_complete
        self.provider_calls = 0

    def get_trading_session(self, as_of):
        return self.sessions.get(as_of)

    def get_limit_security_dataset(self, as_of):
        assert as_of == PREVIOUS
        return {
            "actual_as_of": PREVIOUS,
            "membership_complete": self.previous_complete,
            "rule_version": LIMITS_RULE_VERSION,
        }


def _outcome(*, previous_as_of: date | None = PREVIOUS) -> CollectionOutcome:
    identity = DatasetDate("limits", CURRENT)
    normalization = LimitNormalizationResult(
        rows=(),
        as_of=CURRENT,
        actual_as_of=CURRENT,
        source="fixture",
        complete=False,
        source_revision="fixture-v1",
        rule_version=LIMITS_RULE_VERSION,
        membership_complete=False,
        streak_complete=False,
    ).normalized()
    candidate = LimitsCollectionCandidate(
        identity=identity,
        payload={
            "limitUpCount": 1,
            "quality": {
                "dataset": "limit-pools",
                "source": "fixture",
                "provider": "fixture",
                "status": "ok",
                "observations": 1,
                "asOf": CURRENT.isoformat(),
                "warnings": [],
            },
        },
        source="fixture",
        status="ok",
        observations=1,
        warnings=(),
        settled=True,
        actual_as_of=CURRENT,
        fetched_at=NOW,
        normalization=normalization,
        previous_as_of=previous_as_of,
    )
    return CollectionOutcome(
        identity=identity,
        state=CollectionTaskState.SUCCESS,
        candidate=candidate,
    )


def test_limits_commit_request_factory_injects_local_previous_detail_evidence() -> None:
    store = LocalEvidenceStore()
    factory = LimitsCommitRequestFactory(
        LimitsPreviousSessionEvidenceReader(store)
    )
    task = SimpleNamespace(dataset="limits", as_of=CURRENT)
    lease = SimpleNamespace(
        dataset="limits",
        as_of=CURRENT,
        owner="task-limits",
        generation=1,
        token="lease-token",
    )

    request = factory(task, _outcome(previous_as_of=None), lease)

    assert request.normalization.dataset_checksum
    assert request.previous_as_of == PREVIOUS
    assert request.previous_detail_available is True
    assert request.lease is lease
    assert store.provider_calls == 0


def test_limits_commit_request_factory_marks_missing_previous_detail() -> None:
    store = LocalEvidenceStore(previous_complete=False)

    request = LimitsCommitRequestFactory(
        LimitsPreviousSessionEvidenceReader(store)
    )(
        SimpleNamespace(
            dataset="limits",
            as_of=CURRENT,
            owner="task-limits",
            generation=1,
            token="lease-token",
        ),
        _outcome(),
        SimpleNamespace(
            dataset="limits",
            as_of=CURRENT,
            owner="task-limits",
            generation=1,
            token="lease-token",
        ),
    )

    assert request.previous_as_of == PREVIOUS
    assert request.previous_detail_available is False


def test_limits_commit_request_factory_rejects_untyped_candidate() -> None:
    identity = DatasetDate("limits", CURRENT)
    candidate = CollectionCandidate(
        identity=identity,
        payload={},
        source="fixture",
        status="ok",
        observations=0,
        warnings=(),
        settled=True,
        actual_as_of=CURRENT,
    )
    outcome = CollectionOutcome(
        identity=identity,
        state=CollectionTaskState.SUCCESS,
        candidate=candidate,
    )

    with pytest.raises(TypeError, match="typed limits candidate"):
        LimitsCommitRequestFactory(
            LimitsPreviousSessionEvidenceReader(LocalEvidenceStore())
        )(
            SimpleNamespace(
                dataset="limits",
                as_of=CURRENT,
                owner="task-limits",
                generation=1,
                token="lease-token",
            ),
            outcome,
            SimpleNamespace(dataset="limits", as_of=CURRENT),
        )


class CalendarProvider:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_trading_days(self):
        self.calls += 1
        return (EARLIER, PREVIOUS, CURRENT)


class SessionStore:
    def __init__(self) -> None:
        self.records = []

    def put_trading_session(self, record) -> None:
        self.records.append(record)


def test_explicit_history_preparer_preserves_calendar_backfill_without_startup_io() -> None:
    provider = CalendarProvider()
    store = SessionStore()
    preparer = ProviderLimitHistoryPreparer(provider, store, now=lambda: NOW)

    assert provider.calls == 0
    selected = preparer.prepare(LimitHistoryPreparationRequest(CURRENT, 2))

    assert selected == (PREVIOUS, CURRENT)
    assert provider.calls == 1
    assert [(record.as_of, record.previous_as_of) for record in store.records] == [
        (PREVIOUS, EARLIER),
        (CURRENT, PREVIOUS),
    ]
    assert all(record.source == "fuyao-calendar" for record in store.records)
