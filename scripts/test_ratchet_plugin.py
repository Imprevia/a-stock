"""Opt-in pytest plugin for recording real FastAPI dispatches."""
from __future__ import annotations

import contextvars
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute

try:
    from .test_ratchet import collect_operations
except ImportError:
    from scripts.test_ratchet import collect_operations

_current_node: contextvars.ContextVar[str | None] = contextvars.ContextVar("test_ratchet_node", default=None)


def _report_path() -> Path | None:
    value = os.environ.get("TEST_RATCHET_REPORT")
    return Path(value) if value else None


class TestRatchetPlugin:
    def __init__(self) -> None:
        self.inventory: set[str] = set()
        self.outcomes: dict[str, dict[str, Any]] = {}
        self.skips: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []
        self.required_database_tests: list[str] = []
        self.declared: list[str] = []
        self._original_handle = None
        self._run_id = os.environ.get("TEST_RATCHET_RUN_ID")
        self._root_pid = os.environ.setdefault("TEST_RATCHET_ROOT_PID", str(os.getpid()))

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            self.inventory.add(item.nodeid)
            self.outcomes[item.nodeid] = {"outcome": "not_run", "markers": sorted(marker.name for marker in item.iter_markers())}
            if item.get_closest_marker("integration") is not None:
                self.required_database_tests.append(item.nodeid)

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self._original_handle = APIRoute.handle
        plugin = self
        original = self._original_handle

        async def wrapped(route_self: APIRoute, scope: Any, receive: Any, send: Any) -> Any:
            nodeid = _current_node.get()
            method = scope.get("method", "").upper()
            path = getattr(route_self, "path_format", getattr(route_self, "path", ""))
            async def recording_send(message: Any) -> None:
                if message.get("type") == "http.response.start":
                    status = int(message["status"])
                    plugin.observations.append({
                        "nodeid": nodeid, "method": method, "path": path,
                        "operation": f"{method} {path}", "status": status,
                        "success": 200 <= status < 400,
                    })
                await send(message)
            return await original(route_self, scope, receive, recording_send)

        APIRoute.handle = wrapped

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item: pytest.Item):
        token = _current_node.set(item.nodeid)
        try:
            yield
        finally:
            _current_node.reset(token)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        markers = self.outcomes.get(report.nodeid, {}).get("markers", [])
        if report.failed or report.skipped or report.when == "call":
            outcome = "failed" if report.failed else "skipped" if report.skipped else "passed"
            row = {"outcome": outcome, "markers": markers}
            if report.skipped:
                reason = str(getattr(report, "longrepr", "skipped"))
                row["reason"] = reason
                self.skips.append({"nodeid": report.nodeid, "reason": reason})
            self.outcomes[report.nodeid] = row

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self._original_handle is not None:
            APIRoute.handle = self._original_handle
        if str(os.getpid()) != self._root_pid:
            return
        try:
            from src.market_environment.bootstrap.app import create_app
            self.declared = collect_operations(create_app())
        except Exception as exc:
            self.declared = []
            self._declaration_error = str(exc)
        passing = {node for node, row in self.outcomes.items() if row.get("outcome") == "passed"}
        success_ops = sorted({observation["operation"] for observation in self.observations if observation.get("nodeid") in passing and observation.get("success")})
        errors = sorted({observation["operation"] for observation in self.observations if observation.get("nodeid") in passing and not observation.get("success")} - set(success_ops))
        report = {
            "run_id": self._run_id,
            "inventory": sorted(self.inventory),
            "operations": success_ops,
            "declared_operations": self.declared,
            "outcomes": self.outcomes,
            "skips": self.skips,
            "required_database_tests": sorted(set(self.required_database_tests)),
            "observations": self.observations,
            "error_only_operations": errors,
            "exitstatus": int(exitstatus),
        }
        if hasattr(self, "_declaration_error"):
            report["declaration_error"] = self._declaration_error
        path = _report_path()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.{os.getpid()}.", dir=str(path.parent))
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
                    stream.write("\n")
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)


_active_plugin: TestRatchetPlugin | None = None


@pytest.hookimpl
def pytest_configure(config: pytest.Config) -> None:
    global _active_plugin
    if _active_plugin is not None:
        return
    _active_plugin = TestRatchetPlugin()
    config.pluginmanager.register(_active_plugin, "test-ratchet-plugin")


def pytest_unconfigure(config: pytest.Config) -> None:
    global _active_plugin
    owner = config.pluginmanager.get_plugin("test-ratchet-plugin")
    if owner is _active_plugin:
        if owner is not None and owner._original_handle is not None:
            APIRoute.handle = owner._original_handle
        _active_plugin = None
