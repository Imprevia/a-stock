from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.market_environment import cli as market_cli
from src.market_environment.cli import _capability_report_from_result
from src.market_environment.application.commands import (
    CapabilityPromotionConflictError,
    CapabilityPromotionRepositoryError,
    CapabilityPromotionValidationError,
    PromoteCapabilityReportCommand,
)
from src.market_environment.domain.models.capability import (
    ProviderCapabilityReport,
)
from src.market_environment.infrastructure.persistence.postgres import (
    PostgresConnectionFactory,
    ProviderCapabilityPromotionUnitOfWork,
)
from src.market_environment.infrastructure.providers.fuyao.market import (
    FuyaoMarketAdapter,
)
from src.market_environment.interfaces.cli import (
    capability_promotion as capability_promotion_cli,
)
from src.market_environment.interfaces.cli.capability_promotion import (
    _masked_backend_identity,
    build_capability_promotion_runtime,
)


AS_OF = date(2026, 10, 8)
IDENTITY = ("fuyao", "sectors", "fuyao-market-v2")
UNSUPPORTED = ("mainNet", "mainNetPct", "upCount", "downCount", "leader")


def _report(**changes) -> ProviderCapabilityReport:
    timestamp = int(
        datetime(2026, 10, 8, 15, 5, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        * 1000
    )
    values = {
        "provider": IDENTITY[0],
        "dataset": IDENTITY[1],
        "revision": IDENTITY[2],
        "status": "eligible",
        "endpoint": "/api/a-share-index/prices/snapshot",
        "field_coverage": {
            "code": 320,
            "name": 320,
            "changePct": 320,
            "amount": 320,
            **{name: 0 for name in UNSUPPORTED},
            "endpoints": {
                "calendar": "/api/a-share/calendar/trading-days",
                "catalog": "/api/a-share-index/catalog/ths-index-list",
                "snapshot": "/api/a-share-index/prices/snapshot",
            },
        },
        "date_evidence": {
            "requested": AS_OF.isoformat(),
            "calendar": AS_OF.isoformat(),
            "snapshot": [AS_OF.isoformat()],
        },
        "history_window": {"proven": False},
        "pagination_evidence": {
            "catalogCount": 320,
            "snapshotCount": 320,
            "catalogIdentityUnique": True,
            "snapshotIdentityUnique": True,
            "snapshotCoverage": 1.0,
            "snapshotBatchCount": 1,
            "snapshotTimestampCount": 1,
            "snapshotTimestamps": [str(timestamp)],
            "snapshotTimestampDateConsistent": True,
        },
        "permission_evidence": {"configured": True},
        "rate_limit_evidence": {"requestBudget": 80, "requestsUsed": 3},
        "sample_count": 10,
        "warnings": ("unsupported sector fields remain null",),
        "missing_evidence": UNSUPPORTED,
        "checked_at": datetime(2026, 10, 8, 8, tzinfo=timezone.utc),
    }
    values.update(changes)
    return ProviderCapabilityReport(**values).normalized()


def _envelope(report: ProviderCapabilityReport | None = None):
    selected = report or _report()
    return {
        "provider": "fuyao",
        "asOf": AS_OF.isoformat(),
        "reports": [selected.to_dict()],
    }


class FakeCapabilityRepository:
    def __init__(self, uow: "FakeUnitOfWork", rows: dict) -> None:
        self.uow = uow
        self.rows = rows
        self.reads = 0
        self.writes = 0
        self.fail_on_put: Exception | None = None

    def get_capability(self, provider, dataset, revision):
        self.reads += 1
        return self.rows.get((provider, dataset, revision))

    def put_capability(self, report):
        self.writes += 1
        if self.fail_on_put:
            raise self.fail_on_put
        key = (report["provider"], report["dataset"], report["revision"])
        existing = self.rows.get(key)
        if existing is not None:
            return (
                "identical"
                if existing.get("checksum") == report.get("checksum")
                else "conflict"
            )
        self.uow.pending = (key, dict(report))
        return "inserted"


class FakeUnitOfWork:
    def __init__(self, rows: dict) -> None:
        self.rows = rows
        self.pending = None
        self.provider_capabilities = FakeCapabilityRepository(self, rows)
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.pending is not None or (exc_type is not None and not self.rollbacks):
            self.rollback()

    def commit(self):
        if self.pending is not None:
            key, value = self.pending
            self.rows[key] = value
        self.pending = None
        self.commits += 1

    def rollback(self):
        self.pending = None
        self.rollbacks += 1


@dataclass
class FakeUowFactory:
    rows: dict

    def __post_init__(self):
        self.instances: list[FakeUnitOfWork] = []

    def __call__(self):
        value = FakeUnitOfWork(self.rows)
        self.instances.append(value)
        return value


class TrackingConnections:
    def __init__(self, events: list[str], validation_error: Exception | None = None):
        self.events = events
        self.validation_error = validation_error

    def validate_runtime(self):
        self.events.append("schema-validation")
        if self.validation_error is not None:
            raise self.validation_error

    def dispose(self):
        self.events.append("dispose")


def _build_tracking_runtime(
    monkeypatch,
    events: list[str],
    *,
    validation_error: Exception | None = None,
):
    connections = TrackingConnections(events, validation_error)
    rows = {}

    def from_settings(settings, *, validate_runtime):
        assert settings.url == "postgresql://operator:secret@db.internal/market"
        assert validate_runtime is False
        events.append("engine-created")
        return connections

    def build_uow(actual_connections):
        assert actual_connections is connections
        events.append("uow-created")
        return FakeUnitOfWork(rows)

    monkeypatch.setattr(
        capability_promotion_cli,
        "DatabaseSettings",
        SimpleNamespace(
            from_environment=lambda *, required: SimpleNamespace(
                url="postgresql://operator:secret@db.internal/market"
            )
        ),
    )
    monkeypatch.setattr(
        capability_promotion_cli,
        "PostgresConnectionFactory",
        SimpleNamespace(from_settings=from_settings),
    )
    monkeypatch.setattr(
        capability_promotion_cli,
        "ProviderCapabilityPromotionUnitOfWork",
        build_uow,
    )
    return build_capability_promotion_runtime(), rows


def _command(rows=None):
    factory = FakeUowFactory(rows if rows is not None else {})
    return PromoteCapabilityReportCommand(factory), factory


def _execute(command, envelope=None, *, apply=False):
    return command.execute(
        envelope or _envelope(),
        provider=IDENTITY[0],
        dataset=IDENTITY[1],
        revision=IDENTITY[2],
        target_backend="postgresql://***@db.internal/market",
        apply=apply,
    )


def _rechecksum(raw: dict) -> dict:
    return ProviderCapabilityReport.from_dict({**raw, "checksum": ""}).to_dict()


def test_dry_run_reads_conflict_state_and_writes_nothing() -> None:
    command, factory = _command()

    result = _execute(command)

    uow = factory.instances[0]
    assert result.mode == "dry-run"
    assert result.result == "validated"
    assert result.conflict_state == "absent"
    assert uow.provider_capabilities.reads == 1
    assert uow.provider_capabilities.writes == 0
    assert uow.commits == 0
    assert uow.rollbacks == 1
    assert factory.rows == {}


def test_apply_is_transactional_idempotent_and_preserves_unrelated_rows() -> None:
    unrelated = _report(provider="other", revision="other-v1").to_dict()
    rows = {("other", "sectors", "other-v1"): unrelated}
    command, factory = _command(rows)

    first = _execute(command, apply=True)
    second = _execute(command, apply=True)

    assert first.result == "applied"
    assert second.result == "idempotent"
    assert len(rows) == 2
    assert rows[("other", "sectors", "other-v1")] == unrelated
    assert sum(uow.provider_capabilities.writes for uow in factory.instances) == 1
    assert factory.instances[0].commits == 1
    assert factory.instances[1].rollbacks == 1


def test_apply_conflict_rolls_back_without_overwrite() -> None:
    existing = _report(sample_count=9).to_dict()
    rows = {IDENTITY: existing}
    command, factory = _command(rows)

    with pytest.raises(CapabilityPromotionConflictError, match="different evidence"):
        _execute(command, apply=True)

    assert rows[IDENTITY] == existing
    assert factory.instances[0].provider_capabilities.writes == 0
    assert factory.instances[0].rollbacks == 1


def test_apply_losing_different_checksum_race_rejects_without_overwrite() -> None:
    rows = {}
    unit_of_work = FakeUnitOfWork(rows)
    competing = _report(sample_count=9).to_dict()
    atomic_put = unit_of_work.provider_capabilities.put_capability

    def put_after_competing_commit(report):
        rows[IDENTITY] = competing
        return atomic_put(report)

    unit_of_work.provider_capabilities.put_capability = put_after_competing_commit
    command = PromoteCapabilityReportCommand(lambda: unit_of_work)

    with pytest.raises(CapabilityPromotionConflictError, match="different evidence"):
        _execute(command, apply=True)

    assert rows[IDENTITY] == competing
    assert unit_of_work.commits == 0
    assert unit_of_work.rollbacks == 1


def test_apply_losing_identical_checksum_race_is_idempotent() -> None:
    rows = {}
    unit_of_work = FakeUnitOfWork(rows)
    competing = _report().to_dict()
    atomic_put = unit_of_work.provider_capabilities.put_capability

    def put_after_competing_commit(report):
        rows[IDENTITY] = competing
        return atomic_put(report)

    unit_of_work.provider_capabilities.put_capability = put_after_competing_commit
    command = PromoteCapabilityReportCommand(lambda: unit_of_work)

    result = _execute(command, apply=True)

    assert result.result == "idempotent"
    assert result.conflict_state == "identical"
    assert rows[IDENTITY] == competing
    assert unit_of_work.commits == 0
    assert unit_of_work.rollbacks == 1


def test_apply_repository_failure_rolls_back() -> None:
    command, factory = _command()
    uow = factory()
    uow.provider_capabilities.fail_on_put = RuntimeError("postgresql://user:secret@db")
    factory.instances.clear()
    factory.__call__ = lambda: uow  # type: ignore[method-assign]

    failing_command = PromoteCapabilityReportCommand(lambda: uow)
    with pytest.raises(
        CapabilityPromotionRepositoryError,
        match="capability repository operation failed",
    ) as exc_info:
        _execute(failing_command, apply=True)

    assert "secret" not in str(exc_info.value)
    assert uow.rollbacks == 1
    assert uow.commits == 0
    assert factory.rows == {}


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda raw: raw.update(checksum="bad"), "checksum or structure"),
        (lambda raw: raw.update(status="ineligible"), "checksum or structure"),
        (lambda raw: raw.update(sample_count=0), "checksum or structure"),
    ],
)
def test_invalid_checksum_is_rejected_before_uow(mutation, message) -> None:
    command, factory = _command()
    envelope = _envelope()
    mutation(envelope["reports"][0])

    with pytest.raises(CapabilityPromotionValidationError, match=message):
        _execute(command, envelope)

    assert factory.instances == []


def test_noneligible_checksum_valid_report_is_rejected_before_uow() -> None:
    command, factory = _command()
    envelope = _envelope(_report(status="ineligible"))
    with pytest.raises(CapabilityPromotionValidationError, match="must be eligible"):
        _execute(command, envelope)
    assert factory.instances == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("endpoint", "/wrong", "endpoint"),
        (
            "date_evidence",
            {"requested": "2026-10-07", "calendar": "2026-10-08", "snapshot": ["2026-10-08"]},
            "exact-date",
        ),
        ("field_coverage", {"code": 319}, "endpoint"),
        ("permission_evidence", {"configured": False}, "permission"),
        ("rate_limit_evidence", {"requestBudget": 3, "requestsUsed": 4}, "rate-limit"),
    ],
)
def test_fuyao_v2_policy_fails_closed(field, value, message) -> None:
    command, factory = _command()
    report = _report(**{field: value})
    with pytest.raises(CapabilityPromotionValidationError, match=message):
        _execute(command, _envelope(report))
    assert factory.instances == []


def test_current_fuyao_v2_probe_evidence_satisfies_promotion_policy() -> None:
    timestamp = int(
        datetime(2026, 10, 8, 15, 5, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        * 1000
    )
    calendar = {
        "timestamp": timestamp,
        "item": [{"date": AS_OF.strftime("%Y%m%d"), "date_ms": timestamp}],
    }
    catalog = {
        "timestamp": timestamp,
        "item": [
            {"thscode": f"{index:06d}.TI", "name": f"行业{index}"}
            for index in range(320)
        ],
    }
    snapshot = {
        "timestamp": timestamp,
        "total": 320,
        "item": [
            {
                "thscode": f"{index:06d}.TI",
                "price_change_ratio_pct": (index % 7) - 3,
                "turnover": 1000 + index,
            }
            for index in range(320)
        ],
    }
    adapter = FuyaoMarketAdapter(
        SimpleNamespace(configured=True, request_budget=80, request_count=3)
    )
    result = adapter.normalize_sector_index_data(
        calendar,
        catalog,
        snapshot,
        AS_OF,
    )
    report = _capability_report_from_result("sectors", result, AS_OF)
    command, factory = _command()

    promoted = _execute(command, _envelope(report))

    assert result.status == "fallback"
    assert report.status == "eligible"
    assert promoted.result == "validated"
    assert factory.instances[0].provider_capabilities.writes == 0


@pytest.mark.parametrize(
    "secret_key",
    ["token", "api_key", "authorization", "cookie", "password", "credential"],
)
def test_sensitive_nested_values_are_rejected_without_echo(secret_key) -> None:
    command, factory = _command()
    envelope = _envelope()
    raw = envelope["reports"][0]
    raw["permission_evidence"][secret_key] = "do-not-echo-this-secret"
    envelope["reports"][0] = _rechecksum(raw)

    with pytest.raises(
        CapabilityPromotionValidationError,
        match="contains sensitive material",
    ) as exc_info:
        _execute(command, envelope)

    assert "do-not-echo" not in str(exc_info.value)
    assert factory.instances == []


def test_url_query_secret_is_rejected_after_original_checksum_validation() -> None:
    command, factory = _command()
    envelope = _envelope()
    raw = envelope["reports"][0]
    raw["endpoint"] = "https://api.example.test/sectors?token=do-not-echo"
    envelope["reports"][0] = _rechecksum(raw)

    with pytest.raises(
        CapabilityPromotionValidationError,
        match="contains sensitive material",
    ) as exc_info:
        _execute(command, envelope)

    assert "do-not-echo" not in str(exc_info.value)
    assert factory.instances == []


def test_nested_endpoint_map_url_query_secret_is_rejected() -> None:
    command, factory = _command()
    envelope = _envelope()
    raw = envelope["reports"][0]
    raw["field_coverage"]["endpoints"]["calendar"] = (
        "https://api.example.test/calendar?api_key=do-not-echo"
    )
    envelope["reports"][0] = _rechecksum(raw)

    with pytest.raises(
        CapabilityPromotionValidationError,
        match="contains sensitive material",
    ) as exc_info:
        _execute(command, envelope)

    assert "do-not-echo" not in str(exc_info.value)
    assert factory.instances == []


def test_relative_endpoint_query_secret_is_rejected() -> None:
    command, factory = _command()
    envelope = _envelope()
    raw = envelope["reports"][0]
    raw["endpoint"] = "/api/a-share-index/prices/snapshot?token=do-not-echo"
    envelope["reports"][0] = _rechecksum(raw)

    with pytest.raises(
        CapabilityPromotionValidationError,
        match="contains sensitive material",
    ) as exc_info:
        _execute(command, envelope)

    assert "do-not-echo" not in str(exc_info.value)
    assert factory.instances == []


def test_redacted_dict_preserves_original_checksum() -> None:
    report = _report(permission_evidence={"configured": True, "token": "sensitive-token"})
    redacted = report.redacted_dict()
    assert redacted["permission_evidence"]["token"] == "[redacted]"
    assert redacted["checksum"] == report.checksum


def test_selector_rejects_zero_duplicate_and_unknown_policy_before_uow() -> None:
    command, factory = _command()
    with pytest.raises(CapabilityPromotionValidationError, match="exactly one"):
        _execute(command, {"provider": "fuyao", "asOf": AS_OF.isoformat(), "reports": []})
    duplicate = _envelope()
    duplicate["reports"].append(dict(duplicate["reports"][0]))
    with pytest.raises(CapabilityPromotionValidationError, match="exactly one"):
        _execute(command, duplicate)
    assert factory.instances == []

    v1 = _report(revision="fuyao-market-v1")
    with pytest.raises(CapabilityPromotionValidationError, match="not registered"):
        command.execute(
            _envelope(v1),
            provider="fuyao",
            dataset="sectors",
            revision="fuyao-market-v1",
            target_backend="masked",
        )
    assert factory.instances == []


@pytest.fixture
def capability_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE provider_capability_reports (
                provider TEXT NOT NULL, dataset TEXT NOT NULL, revision TEXT NOT NULL,
                status TEXT NOT NULL, endpoint TEXT, field_coverage_json TEXT NOT NULL,
                date_evidence_json TEXT NOT NULL, history_window_json TEXT NOT NULL,
                pagination_evidence_json TEXT NOT NULL, permission_evidence_json TEXT NOT NULL,
                rate_limit_evidence_json TEXT NOT NULL, sample_count INTEGER NOT NULL,
                warnings_json TEXT NOT NULL, missing_evidence_json TEXT NOT NULL,
                checked_at TEXT NOT NULL, schema_version INTEGER NOT NULL, checksum TEXT NOT NULL,
                PRIMARY KEY(provider, dataset, revision)
            )
            """
        )
    try:
        yield engine
    finally:
        engine.dispose()


def test_postgres_uow_dry_run_then_apply_commits_one_row(capability_engine) -> None:
    connections = PostgresConnectionFactory(capability_engine)
    command = PromoteCapabilityReportCommand(
        lambda: ProviderCapabilityPromotionUnitOfWork(connections)
    )

    _execute(command)
    with capability_engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM provider_capability_reports")
        ).scalar_one() == 0

    result = _execute(command, apply=True)
    with capability_engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM provider_capability_reports")
        ).scalar_one() == 1
    assert result.result == "applied"


def test_cli_promote_emits_only_redacted_summary_and_closes_runtime(
    monkeypatch, tmp_path, capsys
) -> None:
    command, factory = _command()
    input_path = tmp_path / "report.json"
    input_path.write_text(json.dumps(_envelope()), encoding="utf-8")
    runtime = SimpleNamespace(
        command=command,
        target_backend="postgresql://***@db.internal/market",
        closed=False,
    )
    runtime.close = lambda: setattr(runtime, "closed", True)
    monkeypatch.setattr(
        market_cli,
        "build_cli_container",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("provider container must not be constructed")
        ),
    )

    exit_code = market_cli.main(
        [
            "capabilities",
            "promote",
            "--input",
            str(input_path),
            "--provider",
            "fuyao",
            "--dataset",
            "sectors",
            "--revision",
            "fuyao-market-v2",
        ],
        capability_runtime_factory=lambda: runtime,
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["mode"] == "dry-run"
    assert payload["result"] == "validated"
    assert payload["targetBackend"] == "postgresql://***@db.internal/market"
    assert "field_coverage" not in output
    assert "permission_evidence" not in output
    assert factory.rows == {}
    assert runtime.closed is True


def test_cli_promote_stdin_matches_file_input_without_path_access(
    monkeypatch, tmp_path, capsys
) -> None:
    envelope = _envelope()
    input_path = tmp_path / "report.json"
    input_path.write_text(json.dumps(envelope), encoding="utf-8")

    file_command, file_factory = _command()
    file_runtime = SimpleNamespace(
        command=file_command,
        target_backend="postgresql://***@db.internal/market",
        close=lambda: None,
    )
    file_exit_code = market_cli.main(
        [
            "capabilities",
            "promote",
            "--input",
            str(input_path),
            "--provider",
            "fuyao",
            "--dataset",
            "sectors",
            "--revision",
            "fuyao-market-v2",
        ],
        capability_runtime_factory=lambda: file_runtime,
    )
    file_payload = json.loads(capsys.readouterr().out)

    stdin_command, stdin_factory = _command()
    stdin_runtime = SimpleNamespace(
        command=stdin_command,
        target_backend="postgresql://***@db.internal/market",
        close=lambda: None,
    )
    monkeypatch.setattr(market_cli.sys, "stdin", io.StringIO(json.dumps(envelope)))
    monkeypatch.setattr(
        market_cli,
        "Path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stdin promotion must not access a path")
        ),
    )

    stdin_exit_code = market_cli.main(
        [
            "capabilities",
            "promote",
            "--input",
            "-",
            "--provider",
            "fuyao",
            "--dataset",
            "sectors",
            "--revision",
            "fuyao-market-v2",
        ],
        capability_runtime_factory=lambda: stdin_runtime,
    )
    stdin_payload = json.loads(capsys.readouterr().out)

    assert file_exit_code == stdin_exit_code == 0
    assert stdin_payload == file_payload
    assert stdin_payload["mode"] == "dry-run"
    assert file_factory.rows == stdin_factory.rows == {}


def test_cli_promote_stdin_apply_writes_one_row_and_closes_runtime(
    monkeypatch, capsys
) -> None:
    command, factory = _command()
    runtime = SimpleNamespace(
        command=command,
        target_backend="postgresql://***@db.internal/market",
        closed=False,
    )
    runtime.close = lambda: setattr(runtime, "closed", True)
    monkeypatch.setattr(
        market_cli.sys,
        "stdin",
        io.StringIO(json.dumps(_envelope())),
    )

    exit_code = market_cli.main(
        [
            "capabilities",
            "promote",
            "--input",
            "-",
            "--provider",
            "fuyao",
            "--dataset",
            "sectors",
            "--revision",
            "fuyao-market-v2",
            "--apply",
        ],
        capability_runtime_factory=lambda: runtime,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["mode"] == "apply"
    assert payload["result"] == "applied"
    assert list(factory.rows) == [IDENTITY]
    assert runtime.closed is True


class _InvalidUnicodeInput:
    def read(self):
        raise UnicodeDecodeError(
            "utf-8",
            b"\xff",
            0,
            1,
            "sensitive-database-password",
        )


@pytest.mark.parametrize(
    "stdin_input",
    [
        io.StringIO(""),
        io.StringIO('{"token":"sensitive-token"'),
        io.StringIO('{"first":"sensitive-token"}\n{"second":true}'),
        _InvalidUnicodeInput(),
    ],
    ids=("empty", "malformed", "multiple-documents", "unicode-error"),
)
def test_cli_promote_rejects_invalid_stdin_before_runtime_without_echoing_input(
    monkeypatch, capsys, stdin_input
) -> None:
    runtime_builds = 0

    def build_runtime():
        nonlocal runtime_builds
        runtime_builds += 1
        raise AssertionError("runtime must not be built for unreadable input")

    monkeypatch.setattr(market_cli.sys, "stdin", stdin_input)
    monkeypatch.setattr(
        market_cli,
        "Path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stdin promotion must not access a path")
        ),
    )

    exit_code = market_cli.main(
        [
            "capabilities",
            "promote",
            "--input",
            "-",
            "--provider",
            "fuyao",
            "--dataset",
            "sectors",
            "--revision",
            "fuyao-market-v2",
        ],
        capability_runtime_factory=build_runtime,
    )
    output = capsys.readouterr().out

    assert exit_code == 2
    assert runtime_builds == 0
    assert "sensitive-token" not in output
    assert "sensitive-database-password" not in output
    assert json.loads(output) == {
        "status": "rejected",
        "error": "capability input could not be read",
    }


@pytest.mark.parametrize(
    "invalid_case",
    ("structure", "selector-mismatch", "sensitive-report"),
)
def test_cli_valid_json_rejection_performs_no_database_access(
    monkeypatch, capsys, invalid_case
) -> None:
    events: list[str] = []
    runtime, rows = _build_tracking_runtime(monkeypatch, events)
    envelope = _envelope()
    revision = IDENTITY[2]
    if invalid_case == "structure":
        envelope = {}
    elif invalid_case == "selector-mismatch":
        revision = "fuyao-market-v1"
    else:
        raw_report = envelope["reports"][0]
        raw_report["permission_evidence"]["token"] = "sensitive-token"
        envelope["reports"][0] = _rechecksum(raw_report)
    monkeypatch.setattr(market_cli.sys, "stdin", io.StringIO(json.dumps(envelope)))

    exit_code = market_cli.main(
        [
            "capabilities",
            "promote",
            "--input",
            "-",
            "--provider",
            IDENTITY[0],
            "--dataset",
            IDENTITY[1],
            "--revision",
            revision,
        ],
        capability_runtime_factory=lambda: runtime,
    )
    output = capsys.readouterr().out

    assert exit_code == 2
    assert events == ["engine-created", "dispose"]
    assert rows == {}
    assert "sensitive-token" not in output


def test_runtime_defers_schema_validation_until_after_pure_report_validation(
    monkeypatch,
) -> None:
    events: list[str] = []
    runtime, rows = _build_tracking_runtime(monkeypatch, events)

    assert events == ["engine-created"]

    result = runtime.command.execute(
        _envelope(),
        provider=IDENTITY[0],
        dataset=IDENTITY[1],
        revision=IDENTITY[2],
        target_backend=runtime.target_backend,
    )

    assert result.result == "validated"
    assert events == ["engine-created", "schema-validation", "uow-created"]
    assert rows == {}
    runtime.close()
    assert events[-1] == "dispose"


def test_backend_identity_masks_credentials_and_query_parameters() -> None:
    masked = _masked_backend_identity(
        "postgresql+psycopg://operator:database-password@db.internal:5432/market?sslmode=require"
    )
    assert masked == "postgresql+psycopg://***@db.internal:5432/market"
    assert "operator" not in masked
    assert "database-password" not in masked
    assert "sslmode" not in masked


def test_cli_masks_repository_errors_and_uses_stable_exit_code(
    tmp_path, capsys
) -> None:
    class FailingCommand:
        def execute(self, *args, **kwargs):
            raise RuntimeError(
                "postgresql://operator:database-password@db.internal/market"
            )

    input_path = tmp_path / "report.json"
    input_path.write_text(json.dumps(_envelope()), encoding="utf-8")
    runtime = SimpleNamespace(
        command=FailingCommand(),
        target_backend="postgresql://***@db.internal/market",
        close=lambda: None,
    )

    exit_code = market_cli.main(
        [
            "capabilities",
            "promote",
            "--input",
            str(input_path),
            "--provider",
            "fuyao",
            "--dataset",
            "sectors",
            "--revision",
            "fuyao-market-v2",
            "--apply",
        ],
        capability_runtime_factory=lambda: runtime,
    )
    output = capsys.readouterr().out

    assert exit_code == 3
    assert "database-password" not in output
    assert "operator" not in output
    assert json.loads(output) == {
        "status": "rejected",
        "error": "capability repository operation failed",
    }


def test_cli_masks_schema_validation_errors(monkeypatch, capsys) -> None:
    events: list[str] = []
    runtime, rows = _build_tracking_runtime(
        monkeypatch,
        events,
        validation_error=RuntimeError(
            "postgresql://operator:schema-secret@db.internal/market"
        ),
    )
    monkeypatch.setattr(
        market_cli.sys,
        "stdin",
        io.StringIO(json.dumps(_envelope())),
    )

    exit_code = market_cli.main(
        [
            "capabilities",
            "promote",
            "--input",
            "-",
            "--provider",
            "fuyao",
            "--dataset",
            "sectors",
            "--revision",
            "fuyao-market-v2",
        ],
        capability_runtime_factory=lambda: runtime,
    )
    output = capsys.readouterr().out

    assert exit_code == 3
    assert events == ["engine-created", "schema-validation", "dispose"]
    assert rows == {}
    assert "schema-secret" not in output
    assert "operator" not in output
    assert json.loads(output)["error"] == "capability repository operation failed"


def test_cli_masks_close_error_after_success(monkeypatch, capsys) -> None:
    class SuccessfulCommand:
        def execute(self, *args, **kwargs):
            return SimpleNamespace(to_dict=lambda: {"result": "validated"})

    runtime = SimpleNamespace(
        command=SuccessfulCommand(),
        target_backend="postgresql://***@db.internal/market",
        close=lambda: (_ for _ in ()).throw(
            RuntimeError("postgresql://operator:cleanup-secret@db.internal/market")
        ),
    )
    monkeypatch.setattr(market_cli.sys, "stdin", io.StringIO("{}"))

    exit_code = market_cli.main(
        [
            "capabilities",
            "promote",
            "--input",
            "-",
            "--provider",
            IDENTITY[0],
            "--dataset",
            IDENTITY[1],
            "--revision",
            IDENTITY[2],
        ],
        capability_runtime_factory=lambda: runtime,
    )
    output = capsys.readouterr().out

    assert exit_code == 3
    assert "cleanup-secret" not in output
    assert "operator" not in output
    assert json.loads(output) == {
        "status": "rejected",
        "error": "capability repository operation failed",
    }


def test_cli_close_error_does_not_override_primary_error(monkeypatch, capsys) -> None:
    class RejectingCommand:
        def execute(self, *args, **kwargs):
            raise CapabilityPromotionValidationError("safe validation failure")

    runtime = SimpleNamespace(
        command=RejectingCommand(),
        target_backend="postgresql://***@db.internal/market",
        close=lambda: (_ for _ in ()).throw(
            RuntimeError("postgresql://operator:cleanup-secret@db.internal/market")
        ),
    )
    monkeypatch.setattr(market_cli.sys, "stdin", io.StringIO("{}"))

    exit_code = market_cli.main(
        [
            "capabilities",
            "promote",
            "--input",
            "-",
            "--provider",
            IDENTITY[0],
            "--dataset",
            IDENTITY[1],
            "--revision",
            IDENTITY[2],
        ],
        capability_runtime_factory=lambda: runtime,
    )
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "cleanup-secret" not in output
    assert "operator" not in output
    assert json.loads(output) == {
        "status": "rejected",
        "error": "safe validation failure",
    }
