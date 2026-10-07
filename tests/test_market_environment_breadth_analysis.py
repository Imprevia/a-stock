from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from src.market_environment.application.queries.breadth_analysis import (
    BreadthHistoryReader,
)
from src.market_environment.domain.analysis import analyze_breadth
from src.market_environment.domain.analysis import breadth as breadth_analysis


class FixtureIntegrityError(RuntimeError):
    pass


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []
        self.records = {
            date(2026, 9, 1): SimpleNamespace(
                payload={"advanceRatio": 0.5, "quality": {}}
            )
        }

    def get(self, dataset: str, as_of: date):
        self.calls.append((dataset, as_of))
        return self.records.get(as_of)


def test_breadth_analysis_module_has_no_repository_or_provider_imports() -> None:
    source = Path(breadth_analysis.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.update(node.module.split("."))
    assert imported.isdisjoint(
        {
            "application",
            "fastapi",
            "infrastructure",
            "providers",
            "requests",
            "service",
            "snapshot_store",
            "sqlalchemy",
        }
    )


def test_previous_breadth_reads_only_the_exact_previous_session() -> None:
    repository = RecordingRepository()
    reader = BreadthHistoryReader(
        repository,
        integrity_error=FixtureIntegrityError,
    )
    core = {
        "effectiveDate": date(2026, 9, 3),
        "indices": [
            {
                "history": [
                    {"date": "2026-09-01"},
                    {"date": "2026-09-02"},
                    {"date": "2026-09-03"},
                ]
            }
        ],
    }

    assert reader.previous_for_core(core) is None
    assert repository.calls == [("breadth", date(2026, 9, 2))]


def test_breadth_analysis_preserves_insufficient_history_semantics() -> None:
    payload = {
        "advanceCount": 2,
        "declineCount": 1,
        "validCount": 3,
        "advanceRatio": 2 / 3,
        "medianReturn": 0.5,
        "quality": {"source": "fixture"},
    }

    result = analyze_breadth(
        payload,
        date(2026, 9, 3),
        [],
        recent_history=[],
        percentile_history=[],
    )

    assert result.history_quality_status == "insufficient"
    assert result.history_observations == 1
    assert result.payload["momentum"] is None
    assert result.payload["advanceRatioPercentile"] is None
    assert result.payload["indexConsistent"] is None
