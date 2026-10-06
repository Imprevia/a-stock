from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from src.market_environment.application.ports import (
    DatasetCollector,
    SnapshotRepository,
    TaskExecutor,
)
from src.market_environment.domain.models import (
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
)


PORT_ROOT = Path("src/market_environment/application/ports")
FORBIDDEN_IMPORTS = {
    "fastapi",
    "sqlalchemy",
    "requests",
    "src.market_environment.bootstrap",
    "src.market_environment.interfaces",
    "src.market_environment.infrastructure",
    "src.market_environment.collection",
    "src.market_environment.providers",
    "src.market_environment.service",
    "src.market_environment.snapshot_store",
}


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


def test_application_ports_have_no_framework_or_concrete_adapter_imports() -> None:
    violations = []
    for path in sorted(PORT_ROOT.glob("*.py")):
        for imported in sorted(_imports(path)):
            if any(
                imported == forbidden or imported.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_IMPORTS
            ):
                violations.append(f"{path}:{imported}")

    assert violations == []


def test_importing_ports_loads_no_forbidden_runtime_modules() -> None:
    script = """
import json
import sys

import src.market_environment.application.ports

for forbidden in (
    'fastapi',
    'sqlalchemy',
    'requests',
    'src.market_environment.bootstrap',
    'src.market_environment.interfaces',
    'src.market_environment.infrastructure',
    'src.market_environment.collection',
    'src.market_environment.providers',
    'src.market_environment.service',
    'src.market_environment.snapshot_store',
):
    assert forbidden not in sys.modules, forbidden
print(json.dumps({'forbiddenLoaded': []}))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {"forbiddenLoaded": []}


class FakeSnapshotRepository:
    def __init__(self) -> None:
        self.values = {}

    def get(self, identity):
        return self.values.get(identity)

    def put(self, candidate):
        self.values[candidate.identity] = candidate
        return candidate

    def list_dates(self, dataset):
        return tuple(identity.as_of for identity in self.values if identity.dataset == dataset)


class FakeCollector:
    dataset_id = "breadth"

    def collect(self, identity):
        candidate = CollectionCandidate(
            identity=identity,
            payload={},
            source="fixture",
            status="ok",
            observations=0,
            warnings=(),
            settled=True,
        )
        return CollectionOutcome(
            identity=identity,
            state=CollectionTaskState.SUCCESS,
            candidate=candidate,
        )


class FakeSubmittedTask:
    def __init__(self, value) -> None:
        self.value = value

    def result(self, timeout=None):
        return self.value


class FakeExecutor:
    def submit(self, function, *args, **kwargs):
        return FakeSubmittedTask(function(*args, **kwargs))

    def shutdown(self, *, wait=True, cancel_futures=False) -> None:
        return None


def test_fake_ports_satisfy_narrow_runtime_protocols() -> None:
    identity = DatasetDate("breadth", date(2026, 9, 3))
    repository = FakeSnapshotRepository()
    collector = FakeCollector()
    executor = FakeExecutor()

    assert isinstance(repository, SnapshotRepository)
    assert isinstance(collector, DatasetCollector)
    assert isinstance(executor, TaskExecutor)
    outcome = executor.submit(collector.collect, identity).result()
    repository.put(outcome.candidate)
    assert repository.get(identity) == outcome.candidate
