from __future__ import annotations

import ast
import importlib.util
from datetime import date
from pathlib import Path

import pytest

from src.market_environment.application.ports.v2_market_data import (
    V2MarketDataReadPort,
    V2Page,
    V2Resource,
)
from src.market_environment.application.queries.v2_market_data import V2MarketDataQueries


AS_OF = date(2026, 9, 23)


class RecordingReads:
    def __init__(self) -> None:
        self.calls = []

    @staticmethod
    def _resource() -> V2Resource:
        return V2Resource(AS_OF, "2026-09-23T16:00:00+08:00", "private-r1", {"status": "ok"}, {})

    def overview(self, as_of): return self._resource()
    def indices(self, as_of): return self._resource()
    def index(self, as_of, code): return self._resource()
    def index_history(self, as_of, code, **kwargs):
        self.calls.append(("index_history", kwargs)); return V2Page(self._resource())
    def breadth(self, as_of): return self._resource()
    def breadth_history(self, as_of, **kwargs):
        self.calls.append(("breadth_history", kwargs)); return V2Page(self._resource())
    def limits(self, as_of): return self._resource()
    def limits_pool(self, as_of, pool_type, **kwargs):
        self.calls.append(("limits_pool", {"pool_type": pool_type, **kwargs})); return V2Page(self._resource())
    def limits_history(self, as_of, **kwargs): return V2Page(self._resource())
    def limits_evidence(self, as_of): return self._resource()
    def sector_rankings(self, as_of, **kwargs):
        self.calls.append(("sector_rankings", kwargs)); return V2Page(self._resource())
    def sector_turnover(self, as_of, **kwargs): return V2Page(self._resource())
    def sector_breadth(self, as_of, **kwargs): return V2Page(self._resource())
    def sector_analysis(self, as_of): return self._resource()
    def active_direction(self, as_of, **kwargs): return V2Page(self._resource())
    def events(self, as_of): return self._resource()
    def assessment(self, as_of): return self._resource()
    def operation_summary(self, run_id): return self._resource()
    def operation_checkpoints(self, run_id, **kwargs):
        self.calls.append(("operation_checkpoints", kwargs)); return V2Page(self._resource())


def test_v2_query_facade_is_typed_and_applies_closed_bounds_before_reads() -> None:
    reads = RecordingReads()
    queries = V2MarketDataQueries(reads)

    assert isinstance(reads, V2MarketDataReadPort)
    queries.index_history(AS_OF, "sh000001")
    queries.breadth_history(AS_OF)
    queries.limits_pool(AS_OF, "limit_up")
    queries.sector_rankings(AS_OF, tag="industry")
    queries.operation_checkpoints("run-1")

    assert reads.calls == [
        ("index_history", {"start_date": None, "end_date": None, "after": None, "limit": 60}),
        ("breadth_history", {"start_date": None, "end_date": None, "after": None, "limit": 60}),
        ("limits_pool", {"pool_type": "limit_up", "after": None, "limit": 20}),
        ("sector_rankings", {"tag": "industry", "after": None, "limit": 20}),
        ("operation_checkpoints", {"after": None, "limit": 50}),
    ]

    with pytest.raises(ValueError, match="1..250"):
        queries.index_history(AS_OF, "sh000001", limit=251)
    with pytest.raises(ValueError, match="unsupported limits pool"):
        queries.limits_pool(AS_OF, "everything")
    with pytest.raises(ValueError, match="unsupported sector tag"):
        queries.sector_rankings(AS_OF, tag="arbitrary")
    assert len(reads.calls) == 5


def test_v2_query_module_imports_no_http_provider_or_infrastructure() -> None:
    path = Path("src/market_environment/application/queries/v2_market_data.py")
    module = "src.market_environment.application.queries.v2_market_data"
    package = module.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imports.add(importlib.util.resolve_name("." * node.level + (node.module or ""), package))
            elif node.module:
                imports.add(node.module)

    forbidden = ("fastapi", "requests", "src.market_environment.infrastructure", "src.market_environment.interfaces", "src.market_environment.providers")
    assert [name for name in imports if name.startswith(forbidden)] == []
