from __future__ import annotations

import ast
import importlib.util
import inspect
import socket
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path

import pytest

from src.market_environment.application.queries import (
    GetChapter01Query,
    GetCoreQuery,
    GetMarketEnvironmentQuery,
    GetNextSessionComparisonQuery,
)
from src.market_environment.calculations import build_market_review_evidence
from src.market_environment.domain.models import CollectionCandidate, DatasetDate


CURRENT = date(2026, 9, 11)
NEXT_SESSION = date(2026, 9, 14)
QUERY_ROOT = Path("src/market_environment/application/queries")
FORBIDDEN_IMPORTS = {
    "requests",
    "src.market_environment.application.collection",
    "src.market_environment.application.commands",
    "src.market_environment.collection",
    "src.market_environment.infrastructure",
    "src.market_environment.providers",
}


class ForbiddenProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        self.calls.append(name)
        raise AssertionError(f"provider access is forbidden in query use cases: {name}")


class FakeSnapshots:
    def __init__(
        self,
        candidates: tuple[CollectionCandidate, ...] = (),
        *,
        provider: ForbiddenProvider | None = None,
    ) -> None:
        self._candidates = {candidate.identity: candidate for candidate in candidates}
        self.provider = provider
        self.requested: list[DatasetDate] = []

    def get(self, identity: DatasetDate) -> CollectionCandidate | None:
        self.requested.append(identity)
        return self._candidates.get(identity)

    def list_dates(self, dataset: str):
        return tuple(
            identity.as_of
            for identity in self._candidates
            if identity.dataset == dataset
        )


class FakeAggregates:
    def __init__(
        self,
        values: dict[date, dict] | None = None,
        *,
        provider: ForbiddenProvider | None = None,
    ) -> None:
        self._values = values or {}
        self.provider = provider
        self.requested: list[date] = []

    def get_aggregate(self, as_of: date):
        self.requested.append(as_of)
        return self._values.get(as_of)


@dataclass(frozen=True)
class FakeTradingSession:
    as_of: date
    is_session: bool = True


class FakeTradingSessions:
    def __init__(
        self,
        sessions: tuple[FakeTradingSession, ...] = (),
        *,
        provider: ForbiddenProvider | None = None,
    ) -> None:
        self._sessions = sessions
        self.provider = provider
        self.requested_after: list[date | None] = []

    def get_session(self, as_of: date):
        return next((item for item in self._sessions if item.as_of == as_of), None)

    def list_sessions(self, *, after: date | None = None):
        self.requested_after.append(after)
        return tuple(
            item for item in self._sessions if after is None or item.as_of > after
        )


def _core_payload(as_of: date, change: float) -> dict:
    return {
        "asOf": as_of.isoformat(),
        "generatedAt": "2026-09-14T16:30:00+08:00",
        "indices": [
            {
                "name": "上证指数",
                "changePct": change,
                "close": 101 + change,
                "movingAverages": {"ma20": 100},
                "amountRatio5": 1.1,
                "volumePriceState": "上涨放量" if change > 0 else "放量下跌",
                "dataGaps": [],
                "dataQuality": {"warning": None},
            }
        ],
        "summary": {
            "syncPattern": {
                "code": "synchronized_rally",
                "label": "同步上涨",
            }
        },
    }


def _breadth_payload(as_of: date, ratio: float, median_return: float) -> dict:
    return {
        "advanceCount": 60,
        "declineCount": 40,
        "flatCount": 0,
        "validCount": 100,
        "advanceRatio": ratio,
        "medianReturn": median_return,
        "state": "多数上涨",
        "quality": {"asOf": as_of.isoformat(), "warnings": []},
    }


def _candidate(dataset: str, as_of: date, payload: dict) -> CollectionCandidate:
    return CollectionCandidate(
        identity=DatasetDate(dataset, as_of),
        payload=payload,
        source="fixture",
        status="ok",
        observations=1,
        warnings=(),
        settled=True,
        actual_as_of=as_of,
    )


def _aggregate(as_of: date, change: float, ratio: float) -> dict:
    core = _core_payload(as_of, change)
    breadth = _breadth_payload(as_of, ratio, change)
    evidence = build_market_review_evidence(
        core["indices"], breadth, core["summary"]["syncPattern"]
    )
    return {
        **core,
        "chapter01": {
            "status": "ok",
            "breadth": breadth,
            "limits": {"quality": {"status": "missing"}},
            "sectors": {"quality": {"status": "missing"}},
            "activeDirection": {"quality": {"status": "missing"}},
            "marketEvidence": evidence,
        },
        "_storageSchemaVersion": 1,
        "_limitsSnapshotState": {"checksum": "fixture"},
        "_componentRevision": "fixture-revision",
    }


def _query_set(
    *,
    snapshots: FakeSnapshots | None = None,
    aggregates: FakeAggregates | None = None,
    sessions: FakeTradingSessions | None = None,
):
    snapshots = snapshots or FakeSnapshots()
    aggregates = aggregates or FakeAggregates()
    sessions = sessions or FakeTradingSessions()
    return (
        GetMarketEnvironmentQuery(aggregates),
        GetCoreQuery(snapshots),
        GetChapter01Query(aggregates),
        GetNextSessionComparisonQuery(
            snapshots,
            aggregates,
            sessions,
            build_market_review_evidence,
        ),
    )


def _module_name(path: Path) -> str:
    parts = path.with_suffix("").parts
    return ".".join(parts[:-1] if path.name == "__init__.py" else parts)


def _imports(path: Path) -> set[str]:
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imports.add(
                    importlib.util.resolve_name(
                        "." * node.level + (node.module or ""),
                        package,
                    )
                )
            elif node.module:
                imports.add(node.module)
    return imports


def test_aggregate_core_and_chapter_queries_return_exact_local_payloads() -> None:
    aggregate = _aggregate(CURRENT, 0.5, 0.55)
    snapshots = FakeSnapshots(
        (_candidate("core", CURRENT, _core_payload(CURRENT, 0.5)),)
    )
    queries = _query_set(
        snapshots=snapshots,
        aggregates=FakeAggregates({CURRENT: aggregate}),
    )

    market = queries[0].execute(CURRENT)
    core = queries[1].execute(CURRENT)
    chapter = queries[2].execute(CURRENT, "breadth")

    assert market["asOf"] == CURRENT.isoformat()
    assert core == _core_payload(CURRENT, 0.5)
    assert chapter["chapter01"]["breadth"]["advanceRatio"] == 0.55
    assert set(market).isdisjoint(
        {"_storageSchemaVersion", "_limitsSnapshotState", "_componentRevision"}
    )
    assert "_componentRevision" in aggregate


def test_queries_reject_cross_date_payloads_and_unknown_chapter_section() -> None:
    wrong_date = date(2026, 9, 10)
    core_query = GetCoreQuery(
        FakeSnapshots(
            (_candidate("core", CURRENT, _core_payload(wrong_date, 0.5)),)
        )
    )
    chapter_query = GetChapter01Query(FakeAggregates({CURRENT: _aggregate(CURRENT, 0.5, 0.55)}))

    with pytest.raises(RuntimeError, match="does not match requested date"):
        core_query.execute(CURRENT)
    with pytest.raises(ValueError, match="未知第 01 章 section"):
        chapter_query.execute(CURRENT, "unknown")


def test_full_aggregate_missing_does_not_rebuild_or_write() -> None:
    aggregates = FakeAggregates()

    with pytest.raises(RuntimeError, match="没有已物化"):
        GetMarketEnvironmentQuery(aggregates).execute(CURRENT)

    assert aggregates.requested == [CURRENT]


def test_next_session_available_uses_strict_real_session_and_exact_local_reads() -> None:
    snapshots = FakeSnapshots(
        (
            _candidate("core", CURRENT, _core_payload(CURRENT, 0.5)),
            _candidate("breadth", CURRENT, _breadth_payload(CURRENT, 0.55, 0.5)),
            _candidate("core", NEXT_SESSION, _core_payload(NEXT_SESSION, 1.0)),
            _candidate(
                "breadth",
                NEXT_SESSION,
                _breadth_payload(NEXT_SESSION, 0.70, 1.0),
            ),
        )
    )
    sessions = FakeTradingSessions(
        (
            FakeTradingSession(date(2026, 9, 12), is_session=False),
            FakeTradingSession(NEXT_SESSION),
            FakeTradingSession(date(2026, 9, 15)),
        )
    )
    query = _query_set(snapshots=snapshots, sessions=sessions)[3]

    result = query.execute(CURRENT)

    assert result["status"] == "available"
    assert result["currentAsOf"] == CURRENT.isoformat()
    assert result["nextAsOf"] == NEXT_SESSION.isoformat()
    assert result["deltas"]["advanceRatio"] == 0.15
    assert sessions.requested_after == [CURRENT]


def test_next_session_pending_and_missing_results_never_fall_back_dates() -> None:
    current_snapshots = FakeSnapshots(
        (
            _candidate("core", CURRENT, _core_payload(CURRENT, 0.5)),
            _candidate("breadth", CURRENT, _breadth_payload(CURRENT, 0.55, 0.5)),
        )
    )
    pending = _query_set(
        snapshots=current_snapshots,
        sessions=FakeTradingSessions((FakeTradingSession(NEXT_SESSION),)),
    )[3].execute(CURRENT)
    missing = _query_set(
        snapshots=current_snapshots,
        sessions=FakeTradingSessions(),
    )[3].execute(CURRENT)

    assert pending["status"] == "pending"
    assert pending["nextAsOf"] == NEXT_SESSION.isoformat()
    assert pending["current"]["advanceRatio"] == 0.55
    assert missing["status"] == "insufficient"
    assert missing["nextAsOf"] is None
    assert "严格晚于" in missing["warnings"][0]


def test_query_constructors_and_execution_have_no_provider_or_network_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ForbiddenProvider()
    snapshots = FakeSnapshots(
        (
            _candidate("core", CURRENT, _core_payload(CURRENT, 0.5)),
            _candidate("breadth", CURRENT, _breadth_payload(CURRENT, 0.55, 0.5)),
            _candidate("core", NEXT_SESSION, _core_payload(NEXT_SESSION, 1.0)),
            _candidate(
                "breadth",
                NEXT_SESSION,
                _breadth_payload(NEXT_SESSION, 0.70, 1.0),
            ),
        ),
        provider=provider,
    )
    aggregates = FakeAggregates(
        {CURRENT: _aggregate(CURRENT, 0.5, 0.55)}, provider=provider
    )
    sessions = FakeTradingSessions(
        (FakeTradingSession(NEXT_SESSION),), provider=provider
    )

    def fail_network(*_args, **_kwargs):
        raise AssertionError("network access is forbidden in query use cases")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    market, core, chapter, next_session = _query_set(
        snapshots=snapshots,
        aggregates=aggregates,
        sessions=sessions,
    )

    market.execute(CURRENT)
    core.execute(CURRENT)
    chapter.execute(CURRENT, "summary")
    next_session.execute(CURRENT)

    assert provider.calls == []
    for query_type in (
        GetMarketEnvironmentQuery,
        GetCoreQuery,
        GetChapter01Query,
        GetNextSessionComparisonQuery,
    ):
        constructor_names = {field.name.lower() for field in fields(query_type)}
        assert not constructor_names & {"provider", "collector", "coordinator", "executor"}
        assert "provider" not in inspect.signature(query_type).parameters


def test_query_package_has_no_provider_collector_or_infrastructure_imports() -> None:
    violations = []
    for path in sorted(QUERY_ROOT.glob("*.py")):
        for imported in sorted(_imports(path)):
            if any(
                imported == forbidden or imported.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_IMPORTS
            ):
                violations.append(f"{path}:{imported}")

    assert violations == []
