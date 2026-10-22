from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest

from src.market_environment import cli
from src.market_environment.application.commands import (
    BreadthHistoryMaintenanceRequest,
    BreadthHistoryMaintenanceService,
    MAX_BREADTH_HISTORY_DATES,
)
from src.market_environment.domain.models import CollectionFailureCategory, StructuredTaskFailure


DATES = (date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16))


@dataclass(frozen=True)
class Session:
    as_of: date
    is_session: bool = True


class FakeSessions:
    def __init__(self, values):
        self.values = tuple(values)

    def list_sessions(self, *, after=None):
        return self.values


class FakeSnapshots:
    def __init__(self, dates):
        self.dates = tuple(dates)

    def list_dates(self, dataset):
        assert dataset == "breadth"
        return self.dates


class FakeAggregates:
    def __init__(self, dates):
        self.dates = tuple(dates)

    def list_dates(self):
        return self.dates


class FakeCollection:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def refresh_request(self, request):
        self.calls.append(request)
        return next(self.outcomes)


class FakeAggregate:
    def __init__(self, failures=()):
        self.calls = []
        self.failures = set(failures)

    def rebuild(self, as_of):
        self.calls.append(as_of)
        if as_of in self.failures:
            raise RuntimeError("aggregate fixture failure")
        return {"asOf": as_of.isoformat()}


def _result(as_of: date, status: str, *, category=None):
    task = SimpleNamespace(
        dataset="breadth",
        as_of=as_of,
        task_id=f"task-{as_of.day}",
        status=status,
        warning="fixture failure" if status not in {"success", "partial"} else None,
        failure=(
            StructuredTaskFailure(
                category=category or CollectionFailureCategory.INTERNAL,
                message="fixture failure",
                retryable=True,
                retained=status == "failed-retained",
                stage="acquisition",
            )
            if status not in {"success", "partial"}
            else None
        ),
    )
    return SimpleNamespace(
        run=SimpleNamespace(run_id=f"run-{as_of.day}"),
        tasks=(task,),
    )


def _service(collection, aggregate=None):
    return BreadthHistoryMaintenanceService(
        trading_sessions=FakeSessions(Session(item) for item in DATES),
        snapshots=FakeSnapshots(DATES),
        aggregates=FakeAggregates(
            (date(2026, 9, 10), date(2026, 9, 16), date(2026, 9, 17))
        ),
        collection=collection,
        aggregate=aggregate or FakeAggregate(),
    )


def test_request_contract_rejects_mixed_range_and_dates_or_unsafe_apply():
    with pytest.raises(ValueError, match="either"):
        BreadthHistoryMaintenanceRequest(
            dates=(DATES[0],), start_date=DATES[0], end_date=DATES[1]
        )
    with pytest.raises(ValueError, match="allow-real-provider"):
        BreadthHistoryMaintenanceRequest(dates=(DATES[0],), apply=True)


def test_request_contract_rejects_budget_and_non_session_before_provider():
    with pytest.raises(ValueError, match=str(MAX_BREADTH_HISTORY_DATES)):
        BreadthHistoryMaintenanceRequest(
            dates=tuple(date(2026, 1, index + 1) for index in range(MAX_BREADTH_HISTORY_DATES + 1))
        )
    collection = FakeCollection(())
    service = BreadthHistoryMaintenanceService(
        trading_sessions=FakeSessions((Session(DATES[0]),)),
        snapshots=FakeSnapshots(()),
        aggregates=FakeAggregates(()),
        collection=collection,
        aggregate=FakeAggregate(),
    )
    with pytest.raises(ValueError, match="trading session"):
        service.execute(BreadthHistoryMaintenanceRequest(dates=(DATES[1],)))
    assert collection.calls == []


def test_dry_run_resolves_exact_sessions_without_provider_or_formal_writes():
    collection = FakeCollection(())
    result = _service(collection).execute(
        BreadthHistoryMaintenanceRequest(start_date=DATES[0], end_date=DATES[2])
    )
    assert result.mode == "dry-run"
    assert result.eligible == DATES
    assert result.provider_calls == 0
    assert result.formal_writes == 0
    assert collection.calls == []


def test_apply_keeps_dates_independent_and_rebuilds_only_affected_aggregates():
    collection = FakeCollection(
        (
            _result(DATES[0], "success"),
            _result(DATES[1], "failed-retained"),
            _result(
                DATES[2],
                "failed-missing",
                category=CollectionFailureCategory.NETWORK,
            ),
        )
    )
    aggregate = FakeAggregate()
    service = _service(collection, aggregate)
    result = service.execute(
        BreadthHistoryMaintenanceRequest(
            dates=DATES,
            apply=True,
            allow_real_provider=True,
            allow_snapshot_writes=True,
        )
    )
    assert result.succeeded == (DATES[0],)
    assert result.retained == (DATES[1],)
    assert result.unavailable == (DATES[2],)
    assert result.failed == ()
    assert aggregate.calls == [date(2026, 9, 16), date(2026, 9, 17)]
    assert [item.as_of for item in result.failures] == [DATES[1], DATES[2]]


def test_cli_rejects_unsafe_apply_without_constructing_runtime(capsys, monkeypatch):
    def forbidden():
        raise AssertionError("runtime must not be constructed")

    monkeypatch.setattr(cli, "build_cli_container", forbidden)
    exit_code = cli.main(
        [
            "snapshots",
            "breadth-history",
            "--date",
            DATES[0].isoformat(),
            "--apply",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["providerCalls"] == 0
    assert payload["formalWrites"] == 0
