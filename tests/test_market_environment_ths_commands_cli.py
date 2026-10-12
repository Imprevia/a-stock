from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

from src.market_environment.application.commands import ThsOperationGateError
from src.market_environment.cli import main
from src.market_environment.infrastructure.compatibility import ThsSectorCommandAdapter
from src.market_environment.infrastructure.providers.fuyao.ths_sector import (
    FuyaoThsCapabilityError,
)


AS_OF = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)


class Gates:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls = 0

    def require(self, as_of):
        self.calls += 1
        if not self.allowed:
            raise ThsOperationGateError("THS write permission is not authorized")


class Policy:
    def __init__(self, *, available: bool = True, budget: int = 10) -> None:
        self.available = available
        self.budget = budget
        self.calls = []

    def require(self, dataset, revision):
        self.calls.append((dataset, revision))
        if not self.available:
            raise FuyaoThsCapabilityError("missing eligible Fuyao THS capability report")
        if dataset == "industry-ranking":
            return SimpleNamespace(
                rate_limit_evidence={"requestBudget": self.budget},
                field_coverage={
                    "uniqueCodes": 4,
                    "tagCounts": {
                        "industry": 1,
                        "cn_concept": 1,
                        "region": 1,
                        "tszs": 1,
                    },
                },
            )
        return SimpleNamespace(rate_limit_evidence={"requestBudget": self.budget})


class CapturingExecutor:
    def __init__(self) -> None:
        self.calls = []

    def submit(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return SimpleNamespace()


class Repository:
    def __init__(self) -> None:
        self.operations = []
        self.runs = []

    def put_operation(self, operation):
        self.operations.append(operation)

    def put_backfill_run(self, run):
        self.runs.append(run)


class UnitOfWork:
    def __init__(self, repository) -> None:
        self.ths_sectors = repository

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def commit(self):
        return None


def _adapter(
    *,
    gates=None,
    policy=None,
    executor=None,
    factory=None,
    repository=None,
    effective_date=None,
):
    repository = repository or Repository()
    return ThsSectorCommandAdapter(
        unit_of_work_factory=lambda: UnitOfWork(repository),
        executor=executor or CapturingExecutor(),
        adapter_factory=factory or (lambda *_: (_ for _ in ()).throw(AssertionError("provider constructed"))),
        dump_reader=object(),
        fact_merger=lambda *_args, **_kwargs: (),
        capability_policy=policy or Policy(),
        gates=gates or Gates(),
        default_revisions={
            "industry-ranking": "catalog-r1",
            "sector-membership": "membership-r1",
            "sector-turnover-history": "history-r1",
        },
        clock=lambda: NOW,
        effective_date=effective_date,
    )


def test_command_adapter_fails_closed_before_provider_or_executor() -> None:
    constructed = 0

    def factory(*_args):
        nonlocal constructed
        constructed += 1
        return object()

    executor = CapturingExecutor()
    gates = Gates(allowed=False)
    adapter = _adapter(gates=gates, executor=executor, factory=factory)
    try:
        adapter.start_catalog_sync(as_of=AS_OF)
    except ThsOperationGateError:
        pass
    else:
        raise AssertionError("authorization gate should reject")
    assert constructed == 0
    assert executor.calls == []

    adapter = _adapter(
        executor=executor,
        factory=factory,
        effective_date=lambda: AS_OF,
    )
    try:
        adapter.start_catalog_sync(as_of=date(2026, 10, 10))
    except ThsOperationGateError as error:
        assert "current effective" in str(error)
    else:
        raise AssertionError("catalog date gate should reject")
    assert constructed == 0
    assert executor.calls == []

    policy = Policy(available=False)
    adapter = _adapter(gates=Gates(), policy=policy, executor=executor, factory=factory)
    try:
        adapter.start_turnover_backfill(
            thscodes=("885001.TI",),
            start_date=AS_OF,
            end_date=AS_OF,
        )
    except ThsOperationGateError as error:
        assert "missing eligible" in str(error)
    else:
        raise AssertionError("capability gate should reject")
    assert constructed == 0
    assert executor.calls == []


def test_command_adapter_only_queues_after_all_preflight_gates() -> None:
    executor = CapturingExecutor()
    policy = Policy(budget=10)
    repository = Repository()
    adapter = _adapter(policy=policy, executor=executor, repository=repository)

    result = adapter.start_catalog_sync(as_of=AS_OF, request_budget=9)

    assert result["status"] == "queued"
    assert result["runId"]
    assert policy.calls == [
        ("industry-ranking", "catalog-r1"),
        ("sector-membership", "membership-r1"),
    ]
    assert len(executor.calls) == 1
    assert repository.operations[0].status == "queued"


def test_ths_cli_dry_run_never_constructs_runtime(capsys) -> None:
    constructed = False

    def factory():
        nonlocal constructed
        constructed = True
        raise AssertionError("runtime must not be constructed")

    code = main(
        ["ths", "catalog-sync", "--as-of", "2026-10-12"],
        ths_runtime_factory=factory,
    )

    assert code == 0
    assert constructed is False
    payload = json.loads(capsys.readouterr().out)
    assert payload["formalWrites"] == 0
    assert payload["providerCalls"] == 0


def test_ths_cli_apply_uses_explicit_runtime_and_returns_redacted_result(capsys) -> None:
    class Commands:
        def start_turnover_backfill(self, **kwargs):
            assert kwargs["thscodes"] == ["885001.TI"]
            return {"runId": "run-1", "status": "queued"}

    runtime = SimpleNamespace(
        commands=SimpleNamespace(ths_sectors=Commands()),
        close=lambda: None,
    )
    code = main(
        [
            "ths",
            "turnover-backfill",
            "--thscode",
            "885001.TI",
            "--start-date",
            "2026-10-01",
            "--end-date",
            "2026-10-12",
            "--apply",
        ],
        ths_runtime_factory=lambda: runtime,
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"runId": "run-1", "status": "queued"}


def test_ths_cli_does_not_echo_runtime_secrets(capsys) -> None:
    class Commands:
        def start_catalog_sync(self, **_kwargs):
            raise RuntimeError("https://signed.example/file?api_key=super-secret")

    runtime = SimpleNamespace(
        commands=SimpleNamespace(ths_sectors=Commands()),
        close=lambda: None,
    )
    code = main(
        ["ths", "catalog-sync", "--as-of", "2026-10-12", "--apply"],
        ths_runtime_factory=lambda: runtime,
    )

    assert code == 2
    output = capsys.readouterr().out
    assert "signed.example" not in output
    assert "super-secret" not in output
    assert json.loads(output)["error"] == "THS operation runtime is unavailable"
