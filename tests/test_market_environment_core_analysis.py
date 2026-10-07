from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

from src.market_environment.domain.analysis import (
    build_core_summary,
    previous_trading_date,
    sync_pattern,
)
from src.market_environment.domain.analysis import core as core_analysis


def test_core_analysis_module_has_no_repository_or_provider_imports() -> None:
    source = Path(core_analysis.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "application",
        "collection",
        "fastapi",
        "infrastructure",
        "providers",
        "requests",
        "service",
        "snapshot_store",
        "sqlalchemy",
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.update(node.module.split("."))
    assert imported.isdisjoint(forbidden)


def test_core_summary_and_previous_session_are_pure_and_deterministic() -> None:
    names = ["上证指数", "沪深300", "创业板指", "中证500", "深证成指"]
    analyses = [
        {
            "name": name,
            "changePct": 0.8,
            "trendState": "多头趋势",
            "history": [
                {"date": "2026-09-02"},
                {"date": "2026-09-03"},
            ],
        }
        for name in names
    ]

    summary = build_core_summary(analyses, [], [])
    previous = previous_trading_date(
        {
            "effectiveDate": date(2026, 9, 3),
            "indices": analyses,
        }
    )

    assert sync_pattern(analyses)["code"] == "synchronized_rally"
    assert summary["synchronization"] == "同步上涨"
    assert summary["dominantTrend"] == "多头趋势"
    assert previous == date(2026, 9, 2)
