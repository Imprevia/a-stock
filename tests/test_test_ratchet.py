"""Focused offline tests for pure ratchet comparison and real ASGI recording."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.test_ratchet import compare_baselines, coverage_to_baseline, declared_operations


def baseline():
    return {"inventory": ["test_a"], "operations": ["GET /api/a"],
            "declared_operations": ["GET /api/a"], "coverage": {"src/a.py": 2},
            "environment": {"backend_profile": "postgres"},
            "outcomes": {"test_a": {"outcome": "passed"}}}


def test_comparison_is_pure_and_covered_code_deletion_is_irrelevant():
    old = baseline(); current = copy.deepcopy(old)
    current["coverage"]["src/a.py"] = 1
    snapshot = copy.deepcopy((current, old))
    assert compare_baselines(current, old) == []
    assert (current, old) == snapshot


@pytest.mark.parametrize("change,expected", [
    (lambda candidate: candidate.update(inventory=[]), "removed test"),
    (lambda candidate: candidate["outcomes"]["test_a"].update(outcome="skipped"), "became skipped"),
    (lambda candidate: candidate.update(operations=[]), "missing exercised"),
    (lambda candidate: candidate["coverage"].update({"src/a.py": 3}), "uncovered statements increased"),
    (lambda candidate: candidate["coverage"].pop("src/a.py"), "coverage file removed"),
    (lambda candidate: candidate["coverage"].update({"src/new.py": 5}), "candidate"),
    (lambda candidate: candidate["environment"].update(backend_profile="unconfigured"), "environment mismatch"),
])
def test_comparison_detects_regressions(change, expected):
    old = baseline(); current = copy.deepcopy(old); change(current)
    assert any(expected in error for error in compare_baselines(current, old))


def test_trusted_parent_prevents_relaxed_baseline():
    old = baseline(); proposed = copy.deepcopy(old)
    proposed["coverage"]["src/a.py"] = 8
    assert any("trusted parent" in error for error in compare_baselines(proposed, proposed, old))


def test_rename_requires_reason_and_bidirectional_mapping():
    old = baseline(); current = copy.deepcopy(old)
    current["inventory"] = ["test_b"]
    current["outcomes"] = {"test_b": {"outcome": "passed"}}
    rec = {"reason": "rename test", "mapping": {"test_a": "test_b"}, "reverse_mapping": {"test_b": "test_a"}}
    assert compare_baselines(current, old, reconciliation=rec) == []
    rec.pop("reverse_mapping")
    assert any("reverse_mapping" in error for error in compare_baselines(current, old, reconciliation=rec))


def test_stored_rename_reconciliation_survives_remeasurement_and_trusted_parent():
    trusted = baseline()
    renamed = copy.deepcopy(trusted)
    renamed["inventory"] = ["test_renamed"]
    renamed["outcomes"] = {"test_renamed": {"outcome": "passed"}}
    renamed["coverage"] = {"src/renamed.py": 2}
    reconciliation = {
        "reason": "rename test and source together",
        "mapping": {"test_a": "test_renamed", "src/a.py": "src/renamed.py"},
        "reverse_mapping": {"test_renamed": "test_a", "src/renamed.py": "src/a.py"},
    }
    renamed["reconciliation"] = reconciliation
    measured = copy.deepcopy(renamed)
    measured.pop("reconciliation")
    assert compare_baselines(measured, renamed, reconciliation=renamed["reconciliation"]) == []
    assert compare_baselines(measured, renamed, trusted, renamed["reconciliation"]) == []
    measured["coverage"]["src/renamed.py"] = 3
    assert any("uncovered statements increased" in error
               for error in compare_baselines(measured, renamed, trusted, reconciliation))


def test_reconciliation_cannot_merge_deleted_test_into_existing_parent_node():
    trusted = baseline()
    trusted["inventory"].append("test_existing")
    trusted["outcomes"]["test_existing"] = {"outcome": "passed"}
    current = copy.deepcopy(trusted)
    current["inventory"].remove("test_a")
    current["outcomes"].pop("test_a")
    reconciliation = {
        "reason": "attempt to call a merge a rename",
        "mapping": {"test_a": "test_existing"},
        "reverse_mapping": {"test_existing": "test_a"},
    }
    assert any("invalid reconciliation" in error for error in
               compare_baselines(current, trusted, reconciliation=reconciliation))
    assert any("trusted parent" in error for error in
               compare_baselines(current, current, trusted, reconciliation))


def test_coverage_json_conversion_and_credentials():
    result = coverage_to_baseline({"files": {"src/a.py": {"summary": {"missing_lines": 3, "num_statements": 10}}}},
        ["b", "a"], ["GET /api/a"], {},
        {"backend_profile": "postgres", "database_url": "postgres://user:secret@host/db", "test_profile": "http://private"})
    assert result["coverage"] == {"src/a.py": 3}
    assert result["inventory"] == ["a", "b"]
    assert "secret" not in json.dumps(result)
    assert result["environment"] == {"backend_profile": "postgres"}
    mixed = {"files": {"src/a.py": {"summary": {"missing_lines": 3}},
                        "tests/test_helper.py": {"summary": {"missing_lines": 99}}}}
    assert coverage_to_baseline(mixed, [], [], {})["coverage"] == {"src/a.py": 3}
    legacy = {"files": {"src/a.py": {"summary": {"num_missing": 2}}}}
    assert coverage_to_baseline(legacy, [], [], {})["coverage"] == {"src/a.py": 2}
    for invalid in ({}, {"files": {}}, {"files": {"tests/test_helper.py": {}}},
                    {"files": {"src/a.py": {}}}, {"files": {"src/a.py": {"summary": {}}}},
                    {"files": {"src/a.py": {"summary": {"missing_lines": []}}}}):
        with pytest.raises(ValueError, match="coverage"):
            coverage_to_baseline(invalid, [], [], {})
    empty = baseline()
    empty["coverage"] = {}
    assert any("empty coverage" in error for error in compare_baselines(empty, empty))


def test_exact_openapi_set_excludes_frontend_and_docs():
    schema = {"paths": {"/api/a": {"get": {}, "put": {}}, "/llms.txt": {"get": {}},
                       "/{path:path}": {"get": {}}, "/docs": {"get": {}}, "/assets/a": {"get": {}}}}
    assert declared_operations(schema) == ["GET /api/a", "GET /llms.txt", "PUT /api/a"]


def test_plugin_records_dispatch_skip_error_and_restores_patch(tmp_path):
    source = tmp_path / "test_dispatch.py"
    source.write_text('''import pytest
from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
app=FastAPI()
router=APIRouter()
@router.get("/api/items/{item_id}")
def get_item(item_id: int): return {"id": item_id}
@router.put("/api/items/{item_id}")
def put_item(item_id: int): raise HTTPException(409)
app.include_router(router)
def test_dispatch():
    client=TestClient(app)
    assert client.get("/api/items/1").status_code == 200
    assert client.put("/api/items/1").status_code == 409
@pytest.mark.integration
@pytest.mark.skip(reason="requires isolated database")
def test_skip(): pass
''', encoding="utf-8")
    report = tmp_path / "report.json"
    env = os.environ.copy()
    env.pop("TEST_RATCHET_ROOT_PID", None)
    env["TEST_RATCHET_REPORT"] = str(report)
    env["TEST_RATCHET_RUN_ID"] = "actual-dispatch-run"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    run = subprocess.run([sys.executable, "-m", "pytest", str(source), "-q", "-p", "scripts.test_ratchet_plugin"], env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads(report.read_text())
    assert data["run_id"] == "actual-dispatch-run"
    assert data["operations"] == ["GET /api/items/{item_id}"]
    assert data["error_only_operations"] == ["PUT /api/items/{item_id}"]
    assert {row["status"] for row in data["observations"]} == {200, 409}
    assert any("requires isolated database" in row["reason"] for row in data["skips"])
    assert len(data["required_database_tests"]) == 1
    assert "GET /llms.txt" in data["declared_operations"]


def test_plugin_patch_restoration_and_absent_instrumentation():
    from scripts.test_ratchet_plugin import TestRatchetPlugin
    from fastapi.routing import APIRoute
    original = APIRoute.handle
    plugin = TestRatchetPlugin()
    plugin.pytest_sessionstart(None)
    assert APIRoute.handle is not original
    plugin._root_pid = "-1"
    plugin.pytest_sessionfinish(None, 0)
    assert APIRoute.handle is original
    empty = baseline(); empty["operations"] = []
    assert any("instrumentation" in error for error in compare_baselines(empty, baseline()))
