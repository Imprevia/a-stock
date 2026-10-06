from __future__ import annotations

import ast
import importlib.util
from dataclasses import dataclass, fields
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.market_environment.application.commands import (
    UpdateTimezonePreferenceCommand,
)
from src.market_environment.application.ports import (
    CollectionStatusReader,
    TimezonePreferenceReader,
    TimezonePreferenceWriter,
)
from src.market_environment.application.queries import (
    GetCollectionRunStatusQuery,
    GetCollectionStatusQuery,
    GetTimezonePreferenceQuery,
)


AS_OF = date(2026, 9, 14)
APPLICATION_ROOTS = (
    Path("src/market_environment/application/queries"),
    Path("src/market_environment/application/commands"),
)
FORBIDDEN_IMPORTS = {
    "requests",
    "src.market_environment.application.collection",
    "src.market_environment.collection",
    "src.market_environment.infrastructure",
    "src.market_environment.providers",
}


class ForbiddenProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        self.calls.append(name)
        raise AssertionError(f"provider access is forbidden in status queries: {name}")


@dataclass(frozen=True)
class FakeRun:
    run_id: str
    status: str


class FakeCollectionStatusReader:
    def __init__(self, provider: ForbiddenProvider) -> None:
        self.provider = provider
        self.status_calls: list[date] = []
        self.run_calls: list[str] = []

    def collection_status(self, as_of: date):
        self.status_calls.append(as_of)
        return {
            "asOf": as_of,
            "datasets": [
                {
                    "dataset": "core",
                    "available": True,
                    "latestAttempt": None,
                }
            ],
        }

    def get_run(self, run_id: str):
        self.run_calls.append(run_id)
        return FakeRun(run_id, "success") if run_id == "run-1" else None


@dataclass(frozen=True)
class FakePreference:
    scope: str
    subject_id: str
    workspace_id: str
    timezone: str | None
    updated_at: datetime | None


class FakeTimezonePreferences:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str, str], FakePreference] = {}
        self.reads: list[tuple[str, str, str]] = []
        self.writes: list[tuple[str, str, str, str | None, str]] = []

    def get(self, scope: str, *, subject_id: str, workspace_id: str):
        key = (scope, subject_id, workspace_id)
        self.reads.append(key)
        return self.values.get(
            key,
            FakePreference(scope, subject_id, workspace_id, None, None),
        )

    def set(
        self,
        scope: str,
        *,
        subject_id: str,
        workspace_id: str,
        timezone_value: str | None,
        actor_id: str,
    ):
        self.writes.append(
            (scope, subject_id, workspace_id, timezone_value, actor_id)
        )
        preference = FakePreference(
            scope,
            subject_id,
            workspace_id,
            timezone_value,
            datetime(2026, 9, 14, 8, tzinfo=timezone.utc),
        )
        self.values[(scope, subject_id, workspace_id)] = preference
        return preference


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


def test_collection_status_and_run_queries_are_provider_free() -> None:
    provider = ForbiddenProvider()
    reader = FakeCollectionStatusReader(provider)

    status = GetCollectionStatusQuery(reader).execute(AS_OF)
    run = GetCollectionRunStatusQuery(reader).execute("run-1")
    missing = GetCollectionRunStatusQuery(reader).execute("missing")

    assert status["asOf"] == AS_OF
    assert status["datasets"][0]["available"] is True
    assert run == FakeRun("run-1", "success")
    assert missing is None
    assert provider.calls == []
    assert reader.status_calls == [AS_OF]
    assert reader.run_calls == ["run-1", "missing"]
    assert isinstance(reader, CollectionStatusReader)


def test_collection_status_rejects_cross_date_repository_result() -> None:
    class WrongDateReader(FakeCollectionStatusReader):
        def collection_status(self, as_of: date):
            return {"asOf": date(2026, 9, 13), "datasets": []}

    with pytest.raises(RuntimeError, match="does not match requested date"):
        GetCollectionStatusQuery(WrongDateReader(ForbiddenProvider())).execute(AS_OF)


def test_timezone_query_and_update_use_separate_read_write_ports() -> None:
    preferences = FakeTimezonePreferences()
    query = GetTimezonePreferenceQuery(preferences)
    command = UpdateTimezonePreferenceCommand(preferences)

    before = query.execute(
        "personal",
        subject_id="user-1",
        workspace_id="workspace-1",
    )
    updated = command.execute(
        "personal",
        subject_id="user-1",
        workspace_id="workspace-1",
        timezone_value="Asia/Shanghai",
        actor_id="user-1",
    )
    after = query.execute(
        "personal",
        subject_id="user-1",
        workspace_id="workspace-1",
    )

    assert before.timezone is None
    assert updated.timezone == "Asia/Shanghai"
    assert after == updated
    assert isinstance(preferences, TimezonePreferenceReader)
    assert isinstance(preferences, TimezonePreferenceWriter)
    assert preferences.writes == [
        ("personal", "user-1", "workspace-1", "Asia/Shanghai", "user-1")
    ]


def test_status_and_timezone_use_case_constructors_expose_no_provider_dependency() -> None:
    for use_case in (
        GetCollectionStatusQuery,
        GetCollectionRunStatusQuery,
        GetTimezonePreferenceQuery,
        UpdateTimezonePreferenceCommand,
    ):
        constructor_names = {field.name.lower() for field in fields(use_case)}
        assert not constructor_names & {"provider", "collector", "coordinator", "executor"}


def test_status_query_and_timezone_command_packages_have_no_provider_imports() -> None:
    violations = []
    for root in APPLICATION_ROOTS:
        for path in sorted(root.glob("*.py")):
            for imported in sorted(_imports(path)):
                if any(
                    imported == forbidden or imported.startswith(f"{forbidden}.")
                    for forbidden in FORBIDDEN_IMPORTS
                ):
                    violations.append(f"{path}:{imported}")

    assert violations == []
