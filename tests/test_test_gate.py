"""Offline dispatcher/hook contract tests using disposable Git repositories."""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def gate():
    return load_script("test_dispatcher_under_test", "check-test-gate.py")


@pytest.fixture
def installer():
    return load_script("test_installer_under_test", "install-hooks.py")


def git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def put(repo, name, text="pass\n"):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Gate Fixture")
    git(tmp_path, "config", "user.email", "gate@example.invalid")
    put(tmp_path, "src/module.py")
    put(tmp_path, "tests/test_module.py")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "initial fixture")
    return tmp_path


def test_staged_tree_rejects_partial_staging_without_mutating_index(gate, repo):
    put(repo, "src/module.py", "staged = 1\n")
    git(repo, "add", "src/module.py")
    staged = git(repo, "write-tree")
    put(repo, "src/module.py", "unstaged = 2\n")
    before = git(repo, "status", "--porcelain")
    with pytest.raises(gate.GateError, match="未暂存"):
        gate.assert_index_matches(repo)
    assert git(repo, "write-tree") == staged
    assert git(repo, "status", "--porcelain") == before
    assert git(repo, "stash", "list") == ""
    git(repo, "checkout", "--", "src/module.py")
    markdown = put(repo, "docs/fixture.md", "unstaged documentation fixture\n")
    for tracked in (False, True):
        if tracked:
            git(repo, "add", "docs/fixture.md")
            markdown.write_text("unstaged tracked documentation change\n", encoding="utf-8")
        staged_tree = git(repo, "write-tree")
        status = git(repo, "status", "--porcelain")
        with pytest.raises(gate.GateError, match="未暂存"):
            gate.assert_index_matches(repo)
        assert git(repo, "write-tree") == staged_tree
        assert git(repo, "status", "--porcelain") == status
        assert git(repo, "stash", "list") == ""


def test_staged_rename_delete_and_untracked_protection(gate, repo):
    git(repo, "mv", "src/module.py", "src/renamed.py")
    git(repo, "rm", "tests/test_module.py")
    paths = gate.changed_paths(repo, "commit")
    assert {"src/renamed.py", "tests/test_module.py"} <= set(paths)
    gate.assert_index_matches(repo)
    put(repo, "src/untracked.py")
    with pytest.raises(gate.GateError):
        gate.assert_index_matches(repo)


def test_push_refs_handle_multiple_new_branch_deletion_and_invalid_input(gate, repo, monkeypatch):
    old = git(repo, "rev-parse", "HEAD")
    put(repo, "src/module.py", "changed = 1\n")
    put(repo, "docs/note.md", "fixture\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "next fixture")
    head = git(repo, "rev-parse", "HEAD")
    zero = "0" * 40
    refs = f"refs/heads/a {head} refs/heads/a {old}\nrefs/heads/b {head} refs/heads/b {zero}\nrefs/heads/gone {zero} refs/heads/gone {old}\n"
    assert set(gate.changed_paths(repo, "push", refs)) == {"src/module.py", "tests/test_module.py", "docs/note.md"}
    with pytest.raises(gate.GateError, match="refs"):
        gate.changed_paths(repo, "push", "invalid input")
    with pytest.raises(gate.GateError, match="HEAD"):
        gate.changed_paths(repo, "push", f"refs/heads/a {old} refs/heads/a {zero}")
    docs = load_script("test_docs_contract_under_test", "check-docs-contract.py")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(docs, "MODE", "full")
    monkeypatch.setenv("DOCS_CONTRACT_DIFFS", json.dumps([[old, head], [old, head]]))
    assert docs.changed_files() == ["docs/note.md", "src/module.py"]
    assert docs.changed_line_count(["src/module.py"]) == 4
    monkeypatch.setenv("DOCS_CONTRACT_DIFFS", json.dumps([[None, head]]))
    assert docs.changed_files() == ["docs/note.md", "src/module.py", "tests/test_module.py"]
    assert docs.changed_line_count(["src/module.py"]) >= docs.SMALL_CHANGE_LINES
    git(repo, "rm", "docs/note.md")
    git(repo, "commit", "-qm", "delete fixture doc")
    deleted_head = git(repo, "rev-parse", "HEAD")
    monkeypatch.setenv("DOCS_CONTRACT_DIFFS", json.dumps([[head, deleted_head]]))
    assert docs.changed_files() == ["docs/note.md"]
    assert docs.changed_line_count(["docs/note.md"]) == 1
    monkeypatch.setenv("DOCS_CONTRACT_DIFFS", "[]")
    assert docs.changed_files() == []
    assert docs.changed_line_count([]) == 0
    for invalid in ("invalid-json", "{}", "[[null, null]]", json.dumps([["HEAD", head]]),
                    json.dumps([[None, "f" * 40]])):
        monkeypatch.setenv("DOCS_CONTRACT_DIFFS", invalid)
        assert docs.main() == 1
    monkeypatch.setenv("DOCS_CONTRACT_DIFFS", json.dumps([[old, head]]))
    monkeypatch.setattr(docs, "MODE", "fast")
    assert docs.main() == 1


def test_backend_nested_module_changed_tests_and_docs_mapping(gate, tmp_path):
    put(tmp_path, "tests/test_market_environment_queries.py")
    assert gate.select_tests(tmp_path, ["src/market_environment/application/queries.py"]) == (["tests/test_market_environment_queries.py"], [], False)
    assert gate.select_tests(tmp_path, ["tests/test_market_environment_queries.py"]) == (["tests/test_market_environment_queries.py"], [], False)
    assert gate.select_tests(tmp_path, ["docs/guide.md", "openspec/changes/x/tasks.md"]) == ([], [], False)


def test_backend_fallback_shared_helpers_broad_changes_and_missing_fallback(gate, tmp_path):
    put(tmp_path, gate.SMOKE[0])
    put(tmp_path, "tests/test_market_environment_new_contract.py")
    backend, frontend, fallback = gate.select_tests(tmp_path, ["scripts/shared_helper.py"], expanded=True)
    assert fallback and not frontend
    assert gate.SMOKE[0] in backend
    assert "tests/test_market_environment_new_contract.py" in backend
    assert gate.select_tests(tmp_path, [f"src/module{index}.py" for index in range(9)])[2]
    with pytest.raises(gate.GateError, match="空验证"):
        gate.select_tests(tmp_path / "missing", ["src/unknown.py"])


def test_frontend_mapping_fallback_and_mixed_selection(gate, tmp_path):
    frontend_test = f"{gate.FRONTEND}/src/components/panel.test.ts"
    put(tmp_path, frontend_test)
    put(tmp_path, gate.SMOKE[0])
    backend, frontend, fallback = gate.select_tests(tmp_path, [f"{gate.FRONTEND}/src/components/panel.ts"])
    assert backend == [] and frontend == ["src/components/panel.test.ts"] and not fallback
    backend, frontend, fallback = gate.select_tests(tmp_path, [f"{gate.FRONTEND}/src/missing.ts"])
    assert backend == [] and frontend == ["*"] and fallback
    backend, frontend, fallback = gate.select_tests(tmp_path, ["scripts/shared.py", frontend_test])
    assert gate.SMOKE[0] in backend and frontend == ["src/components/panel.test.ts"]


def test_missing_database_fails_closed_without_connecting(gate):
    with pytest.raises(gate.GateError, match="PostgreSQL"):
        gate.environment_profile({})


def test_ci_ignores_local_bypass_and_propagates_failure(gate, monkeypatch):
    monkeypatch.setenv("SKIP_TEST_GATE", "1")
    monkeypatch.setenv("TEST_GATE_SKIP_REASON", "fixture emergency")
    monkeypatch.setenv("SKIP_DOCS_CONTRACT", "1")
    observed = []
    def authoritative(root, args, env):
        observed.append(env)
        raise gate.GateError("fixture failure")
    monkeypatch.setattr(gate, "authoritative", authoritative)
    monkeypatch.setattr(gate, "run", lambda *args: pytest.fail("CI must not use bypass"))
    assert gate.main(["--mode=ci"]) == 1
    assert len(observed) == 1
    assert not any(key in observed[0] for key in gate.BYPASS_KEYS)


def test_precommit_never_authorizes_from_stale_commit_editmsg(gate, repo, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("SKIP_TEST_GATE", raising=False)
    monkeypatch.delenv("TEST_GATE_SKIP_REASON", raising=False)
    put(repo, ".git/COMMIT_EDITMSG", "[skip-tests] old unrelated emergency\n")
    monkeypatch.setattr(gate, "ROOT", repo)
    calls = []
    def failing(command, root, env):
        calls.append(command)
        raise gate.GateError("docs failed")
    monkeypatch.setattr(gate, "run", failing)
    assert gate.main(["--mode=commit"]) == 1
    assert "check-docs-contract.py" in calls[0][1]


@pytest.mark.parametrize("message,reason,valid", [
    ("fix: fixture\n[skip-tests] outage recovery\n", "outage recovery", True),
    ("[skip-tests]\n", "outage", False),
    ("[skip-tests] different\n", "outage", False),
    ("[skip-tests] outage recovery\n", "outage", False),
])
def test_message_audit_matches_complete_reason(gate, tmp_path, message, reason, valid):
    path = put(tmp_path, "message.txt", message)
    if valid:
        gate.audit_message(path, {"SKIP_TEST_GATE": "1", "TEST_GATE_SKIP_REASON": reason})
    else:
        with pytest.raises(gate.GateError):
            gate.audit_message(path, {"SKIP_TEST_GATE": "1", "TEST_GATE_SKIP_REASON": reason})


def test_installer_check_is_readonly_and_validates_missing_executable_hooks(installer, repo, monkeypatch):
    monkeypatch.chdir(repo)
    config = repo / ".git/config"
    before = config.read_bytes()
    assert installer.main(["--check"]) == 1
    assert config.read_bytes() == before
    for hook in installer.HOOKS:
        put(repo, f".githooks/{hook}", "#!/bin/sh\nexit 0\n").chmod(0o755)
    git(repo, "config", "core.hooksPath", ".githooks")
    before = config.read_bytes()
    assert installer.main(["--check"]) == 0
    assert config.read_bytes() == before
    (repo / ".githooks/pre-push").chmod(0o644)
    if os.name != "nt":
        assert installer.main(["--check"]) == 1
    (repo / ".githooks/pre-push").unlink()
    assert installer.main(["--check"]) == 1
    assert config.read_bytes() == before


def test_authoritative_missing_baseline_never_launches_suite(gate, tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "environment_profile", lambda env: {"backend_profile": "postgres-test"})
    monkeypatch.setattr(gate, "run", lambda *args: pytest.fail("missing baseline must block before suite"))
    args = argparse.Namespace(mode="ci", baseline="tests/baselines/missing.json")
    with pytest.raises(gate.GateError, match="基线"):
        gate.authoritative(tmp_path, args, {})


def test_push_mode_preserves_all_stdin_refs(gate, repo, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("SKIP_TEST_GATE", raising=False)
    monkeypatch.setattr(gate, "ROOT", repo)
    head = git(repo, "rev-parse", "HEAD")
    refs = f"refs/heads/a {head} refs/heads/a {'0' * 40}\nrefs/heads/b {head} refs/heads/b {head}\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(refs))
    docs_environments = []
    def capture_run(command, root, env):
        if "scripts/check-docs-contract.py" in command:
            docs_environments.append(dict(env))
    monkeypatch.setattr(gate, "run", capture_run)
    received = []
    def changed(root, mode, value):
        received.append(value)
        return []
    monkeypatch.setattr(gate, "changed_paths", changed)
    assert gate.main(["--mode=push"]) == 0
    assert received == [refs]
    assert json.loads(docs_environments[0]["DOCS_CONTRACT_DIFFS"]) == [[None, head], [head, head]]


def test_pre_push_shell_retains_stdin_and_exit_status(tmp_path):
    if os.name == "nt" or not shutil.which("sh"):
        pytest.skip("POSIX shell fixture")
    interpreter = put(tmp_path, ".venv/bin/python", "#!/bin/sh\ncat > received-refs\nprintf '%s\\n' \"$@\" > received-args\nexit 7\n")
    interpreter.chmod(0o755)
    refs = "refs/heads/a " + "a" * 40 + " refs/heads/a " + "b" * 40 + "\n"
    run = subprocess.run([shutil.which("sh"), str(ROOT / ".githooks/pre-push")], cwd=tmp_path, input=refs, text=True, capture_output=True)
    assert run.returncode == 7
    assert (tmp_path / "received-refs").read_text() == refs
    assert "--mode=push" in (tmp_path / "received-args").read_text()


def test_hook_missing_interpreter_fails_closed(tmp_path):
    if os.name == "nt" or not shutil.which("sh"):
        pytest.skip("POSIX shell fixture")
    run = subprocess.run([shutil.which("sh"), str(ROOT / ".githooks/pre-push")], cwd=tmp_path,
                         env={"PATH": str(tmp_path / "no-tools")}, text=True, capture_output=True)
    assert run.returncode != 0
    assert "Python" in run.stderr


@pytest.mark.parametrize("db_outcome", ["passed", "skipped"])
def test_authoritative_consumes_one_measured_run_and_is_readonly(gate, tmp_path, monkeypatch, db_outcome):
    from scripts.test_ratchet import coverage_to_baseline
    profile = {"python_minor": "3.12", "coverage_major": 7, "backend_profile": "postgres-test"}
    report = {
        "inventory": ["tests/test_db.py::test_db"], "operations": ["GET /api/health"],
        "declared_operations": ["GET /api/health"],
        "outcomes": {"tests/test_db.py::test_db": {"outcome": db_outcome, "markers": ["integration"]}},
        "required_database_tests": ["tests/test_db.py::test_db"], "skips": [], "exitstatus": 0,
    }
    coverage = {"files": {"src/a.py": {"summary": {"missing_lines": 2}}}}
    old = coverage_to_baseline(coverage, report["inventory"], report["operations"],
                               {"tests/test_db.py::test_db": {"outcome": "passed"}}, profile)
    path = put(tmp_path, gate.BASELINE, json.dumps(old))
    before = path.read_bytes()
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(gate, "environment_profile", lambda env: profile)
    calls = []
    def measured_run(command, root, env):
        calls.append(command)
        report_dir.mkdir(exist_ok=True)
        report["run_id"] = env["TEST_RATCHET_RUN_ID"]
        (report_dir / "pytest.json").write_text(json.dumps(report), encoding="utf-8")
        (report_dir / "coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
    monkeypatch.setattr(gate, "run", measured_run)
    args = argparse.Namespace(mode="ci", baseline=gate.BASELINE, trusted_ref=None,
                              report_dir=str(report_dir), reason="")
    if db_outcome == "passed":
        gate.authoritative(tmp_path, args, {})
    else:
        with pytest.raises(gate.GateError, match="数据库"):
            gate.authoritative(tmp_path, args, {})
    assert path.read_bytes() == before
    assert len(calls) == 2
    assert sum("pytest" in command for command in calls) == 1
    assert "scripts.test_ratchet_plugin" in calls[0]
    assert calls[0].count("tests") == 1
    if db_outcome == "passed":
        def stale_run(command, root, env):
            report["run_id"] = "stale-previous-measurement"
            (report_dir / "pytest.json").write_text(json.dumps(report), encoding="utf-8")
            (report_dir / "coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
        monkeypatch.setattr(gate, "run", stale_run)
        with pytest.raises(gate.GateError):
            gate.authoritative(tmp_path, args, {})
        assert path.read_bytes() == before


@pytest.mark.parametrize("interpreter_path,expected_args", [
    (".venv/Scripts/python.exe", ["scripts/check-test-gate.py", "--mode=push"]),
    ("tools/py", ["-3", "scripts/check-test-gate.py", "--mode=push"]),
])
def test_hook_windows_interpreter_and_py_launcher_propagate_exit(tmp_path, interpreter_path, expected_args):
    shell = shutil.which("sh")
    if os.name == "nt" or not shell:
        pytest.skip("POSIX shell simulation fixture")
    interpreter = put(tmp_path, interpreter_path,
                      "#!/bin/sh\nprintf '%s\\n' \"$@\" > launcher-args\nexit 23\n")
    interpreter.chmod(0o755)
    process = subprocess.run([shell, str(ROOT / ".githooks/pre-push")], cwd=tmp_path,
                             env={"PATH": str(tmp_path / "tools")}, text=True, capture_output=True)
    assert process.returncode == 23
    assert (tmp_path / "launcher-args").read_text().splitlines() == expected_args


def local_mode_fixture(gate, repo, monkeypatch):
    for key in ("CI", "SKIP_TEST_GATE", "TEST_GATE_SKIP_REASON"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(gate, "ROOT", repo)


def test_docs_only_staged_commit_executes_docs_without_pytest(gate, repo, monkeypatch):
    local_mode_fixture(gate, repo, monkeypatch)
    put(repo, "docs/new-guide.md", "documentation fixture\n")
    git(repo, "add", "docs/new-guide.md")
    commands = []
    monkeypatch.setattr(gate, "run", lambda command, root, env: commands.append(command))
    assert gate.main(["--mode=commit"]) == 0
    assert len(commands) == 1
    assert commands[0][1:] == ["scripts/check-docs-contract.py", "--mode=fast"]


def test_selected_commit_test_failure_is_propagated(gate, repo, monkeypatch):
    local_mode_fixture(gate, repo, monkeypatch)
    put(repo, "src/module.py", "staged_change = 1\n")
    git(repo, "add", "src/module.py")
    commands = []
    def record(command, root, env):
        commands.append(command)
        if "pytest" in command:
            raise gate.GateError("selected test failed")
    monkeypatch.setattr(gate, "run", record)
    assert gate.main(["--mode=commit"]) == 1
    assert len(commands) == 2
    assert commands[1][1:] == ["-m", "pytest", "tests/test_module.py", "-q"]


@pytest.mark.parametrize("failure_stage", ["docs", "architecture", "validate", "coverage", "pytest", None])
def test_push_failure_chain_propagates_without_full_suite(gate, repo, monkeypatch, failure_stage):
    local_mode_fixture(gate, repo, monkeypatch)
    old = git(repo, "rev-parse", "HEAD")
    put(repo, "src/module.py", "pushed_change = 1\n")
    git(repo, "add", "src/module.py")
    git(repo, "commit", "-qm", "push fixture")
    head = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"refs/heads/a {head} refs/heads/a {old}\n"))
    stages = []
    commands = []
    def run_stage(command, root, env):
        commands.append(command)
        if "scripts/check-docs-contract.py" in command:
            stage = "docs"
            assert "--mode=full" in command
        elif "scripts/check_market_environment_architecture.py" in command:
            stage = "architecture"
        elif "src.trading_system.cli" in command:
            stage = command[-1]
        else:
            stage = "pytest"
        stages.append(stage)
        if stage == failure_stage:
            raise gate.GateError("fixture " + stage + " failure")
    monkeypatch.setattr(gate, "run", run_stage)
    assert gate.main(["--mode=push"]) == (0 if failure_stage is None else 1)
    expected = ["docs", "architecture", "validate", "coverage", "pytest"]
    assert stages == (expected if failure_stage is None else expected[:expected.index(failure_stage) + 1])
    assert not any("pytest" in command and "tests" in command for command in commands)
    if "pytest" in stages:
        assert "tests/test_module.py" in commands[-1]


@pytest.mark.parametrize("changed_path", [
    "trading-rules/registry.yaml", "pytest.ini", "requirements.txt", "alembic.ini",
    ".coveragerc", "pyproject.toml", "setup.cfg", "tox.ini",
])
def test_rule_and_test_configuration_changes_are_never_docs_only(gate, tmp_path, changed_path):
    put(tmp_path, gate.SMOKE[0])
    backend, frontend, fallback = gate.select_tests(tmp_path, [changed_path])
    assert backend or frontend
    assert fallback


def test_new_source_requires_explicit_baseline_admission_and_ci_is_readonly(gate, tmp_path, monkeypatch):
    from scripts.test_ratchet import coverage_to_baseline
    profile = {"backend_profile": "postgres-test"}
    report = {
        "inventory": ["tests/test_db.py::test_db"], "operations": ["GET /api/health"],
        "declared_operations": ["GET /api/health"],
        "outcomes": {"tests/test_db.py::test_db": {"outcome": "passed", "markers": ["integration"]}},
        "required_database_tests": ["tests/test_db.py::test_db"], "skips": [], "exitstatus": 0,
    }
    coverage_data = {"files": {"src/a.py": {"summary": {"missing_lines": 2}}}}
    old = coverage_to_baseline(coverage_data, report["inventory"], report["operations"], report["outcomes"], profile)
    baseline_path = put(tmp_path, gate.BASELINE, json.dumps(old))
    original = baseline_path.read_bytes()
    coverage_data["files"]["src/new.py"] = {"summary": {"missing_lines": 5}}
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(gate, "environment_profile", lambda env: profile)
    def measured_run(command, root, env):
        report_dir.mkdir(exist_ok=True)
        report["run_id"] = env["TEST_RATCHET_RUN_ID"]
        (report_dir / "pytest.json").write_text(json.dumps(report), encoding="utf-8")
        (report_dir / "coverage.json").write_text(json.dumps(coverage_data), encoding="utf-8")
    monkeypatch.setattr(gate, "run", measured_run)
    args = argparse.Namespace(mode="ci", baseline=gate.BASELINE, trusted_ref=None,
                              report_dir=str(report_dir), reason="", reconciliation_file=None)
    with pytest.raises(gate.GateError, match="candidate"):
        gate.authoritative(tmp_path, args, {})
    assert baseline_path.read_bytes() == original
    args.mode = "baseline"
    with pytest.raises(gate.GateError):
        gate.authoritative(tmp_path, args, {})
    assert baseline_path.read_bytes() == original
    args.reason = "reviewed new source coverage candidate"
    gate.authoritative(tmp_path, args, {})
    admitted = json.loads(baseline_path.read_text())
    assert admitted["coverage"]["src/new.py"] == 5
    assert admitted["update_reason"] == args.reason
    persisted = baseline_path.read_bytes()
    args.mode = "ci"
    gate.authoritative(tmp_path, args, {})
    assert baseline_path.read_bytes() == persisted


def test_documentation_and_rule_changes_select_their_declared_layers(gate, tmp_path):
    put(tmp_path, gate.SMOKE[0])
    put(tmp_path, "tests/test_trading_rule_platform.py")
    put(tmp_path, "tests/test_trading_rule_golden_replay.py")
    assert gate.select_tests(tmp_path, ["docs/README.md", "src/trading_system/README.md"]) == ([], [], False)
    for changed_path in ("trading-rules/registry.yaml", "src/trading_system/rules/evaluator.py"):
        backend, frontend, fallback = gate.select_tests(tmp_path, [changed_path])
        assert "tests/test_trading_rule_platform.py" in backend
        assert gate.SMOKE[0] not in backend
        assert not frontend
        expanded, frontend, fallback = gate.select_tests(tmp_path, [changed_path], expanded=True)
        assert "tests/test_trading_rule_platform.py" in expanded
        assert "tests/test_trading_rule_golden_replay.py" in expanded


def test_incomparable_baseline_environment_blocks_before_measured_run(gate, tmp_path, monkeypatch):
    put(tmp_path, gate.BASELINE, json.dumps({"environment": {"backend_profile": "postgres-old"}}))
    monkeypatch.setattr(gate, "environment_profile", lambda env: {"backend_profile": "postgres-new"})
    monkeypatch.setattr(gate, "run", lambda *args: pytest.fail("incomparable environment must block before suite"))
    args = argparse.Namespace(mode="ci", baseline=gate.BASELINE, trusted_ref=None, report_dir=None, reason="")
    with pytest.raises(gate.GateError, match="environment mismatch"):
        gate.authoritative(tmp_path, args, {})


def test_command_failure_propagates(gate, tmp_path):
    with pytest.raises(gate.GateError, match="exit=9"):
        gate.run([sys.executable, "-c", "raise SystemExit(9)"], tmp_path, os.environ.copy())
