#!/usr/bin/env python3
"""Offline layered test dispatcher; local bypasses never authorize CI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "tests/baselines/test-ratchet.json"
FRONTEND = "apps/market-environment-dashboard"
SMOKE = (
    "tests/test_market_environment_api.py",
    "tests/test_market_environment_v2_contract.py",
    "tests/test_market_environment_discovery.py",
    "tests/test_market_environment_http_coverage.py",
)
BYPASS_KEYS = ("SKIP_TEST_GATE", "TEST_GATE_SKIP_REASON", "SKIP_DOCS_CONTRACT", "SKIP_PLAN_GATE", "DOCS_CONTRACT_DIFFS")


class GateError(Exception):
    pass


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode:
        raise GateError("Git 检查失败：" + " ".join(args[:2]))
    return result.stdout


def testable(path: str) -> bool:
    if Path(path).suffix.lower() in {".md", ".rst"}:
        return False
    return path.startswith(("src/", "tests/", "scripts/", "apps/", ".githooks/", ".github/", "trading-rules/", "evidence/")) or path in {
        "requirements.txt", "pytest.ini", "alembic.ini", "conftest.py", ".coveragerc", "pyproject.toml", "setup.cfg", "tox.ini",
    }


def assert_index_matches(root: Path) -> None:
    changed = git(root, "diff", "--name-only", "-z").split("\0")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    dirty = sorted(path for path in changed + untracked if path)
    if dirty:
        raise GateError("工作树存在未暂存内容（含文档/fixture）；请先整理暂存区（不会自动 stash/index）：" + ", ".join(dirty[:8]))


def changed_paths(root: Path, mode: str, refs: str = "") -> list[str]:
    if mode == "commit":
        return sorted(filter(None, git(root, "diff", "--cached", "--name-only", "-z").split("\0")))
    changed: set[str] = set()
    for line in refs.splitlines():
        fields = line.split()
        if len(fields) != 4 or any(not re.fullmatch(r"[0-9a-fA-F]{40,64}", fields[index]) for index in (1, 3)):
            raise GateError("pre-push refs 格式无效")
        local_ref, local_sha, remote_ref, remote_sha = fields
        if set(local_sha) == {"0"}:
            continue
        if git(root, "rev-parse", "HEAD").strip() != local_sha:
            raise GateError("推送对象不是当前已验证 HEAD；请 checkout 对应提交后再验证")
        if set(remote_sha) == {"0"}:
            paths = git(root, "ls-tree", "-r", "--name-only", "-z", local_sha)
        else:
            paths = git(root, "diff", "--name-only", "-z", remote_sha, local_sha)
        changed.update(filter(None, paths.split("\0")))
    return sorted(changed)


def docs_push_ranges(refs: str) -> list[list[str | None]]:
    ranges = []
    for line in refs.splitlines():
        fields = line.split()
        if len(fields) != 4 or any(not re.fullmatch(r"[0-9a-fA-F]{40,64}", fields[index]) for index in (1, 3)):
            raise GateError("pre-push refs 格式无效")
        local_sha, remote_sha = fields[1], fields[3]
        if set(local_sha) != {"0"}:
            ranges.append([None if set(remote_sha) == {"0"} else remote_sha, local_sha])
    return ranges


def docs_ci_environment(root: Path, args: argparse.Namespace, env: dict[str, str]) -> dict[str, str]:
    reference = args.trusted_ref or ("origin/" + env["GITHUB_BASE_REF"] if env.get("GITHUB_BASE_REF") else env.get("TEST_GATE_BASE_REF"))
    docs_env = dict(env)
    if reference:
        base = None if set(reference) == {"0"} else git(root, "rev-parse", "--verify", reference + "^{commit}").strip()
        head = git(root, "rev-parse", "HEAD").strip()
        docs_env["DOCS_CONTRACT_DIFFS"] = json.dumps([[base, head]])
    return docs_env


def select_tests(root: Path, paths: list[str], expanded: bool = False) -> tuple[list[str], list[str], bool]:
    relevant = [path for path in paths if testable(path)]
    backend: set[str] = set()
    frontend: set[str] = set()
    fallback_backend = False
    fallback_frontend = False
    broad = len(relevant) > 8 or len({path.split("/")[0] for path in relevant}) > 2
    for path in relevant:
        source = Path(path)
        if path.startswith(FRONTEND + "/"):
            if source.name.endswith(".test.ts") and (root / path).is_file():
                frontend.add(str(source.relative_to(FRONTEND)).replace("\\", "/"))
            else:
                matches = list((root / FRONTEND / "src").rglob(source.stem + ".test.ts"))
                if matches and not broad:
                    frontend.update(match.relative_to(root / FRONTEND).as_posix() for match in matches)
                else:
                    fallback_frontend = True
            continue
        if path.startswith(("trading-rules/", "src/trading_system/")):
            rule_tests = ["tests/test_trading_rule_platform.py"]
            if expanded:
                rule_tests.extend(match.relative_to(root).as_posix() for match in (root / "tests").glob("test_*golden*.py"))
            backend.update(name for name in rule_tests if (root / name).is_file())
            if backend:
                continue
        if path.startswith("tests/") and source.name.startswith("test_") and (root / path).is_file() and not broad:
            backend.add(path)
            continue
        if path.startswith("src/") and source.suffix == ".py" and not broad:
            candidates = list((root / "tests").glob("test_*" + source.stem + "*.py"))
            if candidates:
                backend.update(match.relative_to(root).as_posix() for match in candidates)
                continue
        fallback_backend = True
    if fallback_backend:
        backend.update(path for path in SMOKE if (root / path).is_file())
        backend.update(path.relative_to(root).as_posix() for path in (root / "tests").glob("test_test_*.py"))
        if expanded:
            backend.update(path.relative_to(root).as_posix() for path in (root / "tests").glob("test_market_environment_*contract*.py"))
        if not backend:
            raise GateError("无法找到范围测试或回退测试；拒绝空验证")
    if fallback_frontend:
        frontend = {"*"}
    return sorted(backend), sorted(frontend), fallback_backend or fallback_frontend


def run(command: list[str], root: Path, env: dict[str, str]) -> None:
    print("[test-gate] " + " ".join(command), flush=True)
    result = subprocess.run(command, cwd=root, env=env, check=False)
    if result.returncode:
        raise GateError("检查失败（exit=" + str(result.returncode) + "）：" + " ".join(command[:3]))


def audit_message(path: Path, env: dict[str, str]) -> None:
    message = path.read_text(encoding="utf-8")
    marker = re.search(r"\[skip-tests\][ \t]+([^\r\n]+)", message)
    if "[skip-tests]" in message and not marker:
        raise GateError("[skip-tests] 必须在同一行说明理由")
    if env.get("SKIP_TEST_GATE") == "1":
        reason = env.get("TEST_GATE_SKIP_REASON", "").strip()
        if not reason or not marker or reason != marker.group(1).strip():
            raise GateError("应急跳过需 TEST_GATE_SKIP_REASON，并在提交说明写 [skip-tests] 相同理由")
        print("[test-gate] unverified：已审核应急理由")


def environment_profile(env: dict[str, str]) -> dict:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    import coverage

    value = env.get("MARKET_ENVIRONMENT_TEST_DATABASE_URL")
    if not value:
        raise GateError("权威验证缺少隔离 PostgreSQL；未验证，不能放行")
    dashboard = ROOT / FRONTEND / "dist"
    if not (dashboard / "index.html").is_file() or not (dashboard / "assets").is_dir():
        raise GateError("权威 profile 需要已构建 dashboard；请先 npm ci / npm run build，且不要与后端测试并发")
    try:
        url = make_url(value)
        if url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("not isolated")
        if not url.database or not (url.database == "market" or url.database.startswith(("test", "ratchet"))):
            raise ValueError("not test database")
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                major = int(connection.execute(text("SHOW server_version_num")).scalar_one()) // 10000
        finally:
            engine.dispose()
    except Exception:
        raise GateError("隔离测试 PostgreSQL 不可用或不符合本地测试 profile（URL 已隐藏）") from None
    return {"python_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
            "coverage_major": int(coverage.__version__.split(".")[0]),
            "database_backend": "postgresql", "backend_profile": f"postgresql-{major}-test",
            "schema_profile": "repository-tests-v1", "test_profile": "full-offline-v1", "database_configured": True}


def authoritative(root: Path, args: argparse.Namespace, env: dict[str, str]) -> None:
    sys.path.insert(0, str(root))
    from scripts.test_ratchet import coverage_to_baseline, compare_baselines

    profile = environment_profile(env)
    baseline_path = root / args.baseline
    if args.mode == "ci" and not baseline_path.is_file():
        raise GateError("缺少正式棘轮基线；先显式执行 --mode=baseline")
    if args.mode == "baseline" and not args.reason.strip():
        raise GateError("显式基线更新需要 --reason")
    old = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else None
    if old and old.get("environment") != profile:
        raise GateError("environment mismatch：测量环境与基线不可比，未验证")
    report_root = Path(args.report_dir).resolve() if args.report_dir else Path(tempfile.mkdtemp(prefix="a-stock-ratchet-"))
    report_root.mkdir(parents=True, exist_ok=True)
    report_path = report_root / "pytest.json"
    coverage_path = report_root / "coverage.json"
    child_env = dict(env, TEST_RATCHET_REPORT=str(report_path), COVERAGE_FILE=str(report_root / ".coverage"),
                     TEST_RATCHET_RUN_ID=uuid.uuid4().hex)
    child_env.pop("TEST_RATCHET_ROOT_PID", None)
    run([sys.executable, "-m", "coverage", "run", "--source=src", "-m", "pytest", "-p", "scripts.test_ratchet_plugin", "tests", "-q", "-ra"], root, child_env)
    run([sys.executable, "-m", "coverage", "json", "-o", str(coverage_path)], root, child_env)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("run_id") != child_env["TEST_RATCHET_RUN_ID"]:
        raise GateError("测量报告不属于当前测试运行；拒绝旧报告")
    coverage_data = json.loads(coverage_path.read_text(encoding="utf-8"))
    if report.get("exitstatus") != 0 or report.get("declaration_error") or not report.get("declared_operations"):
        raise GateError("测试或操作声明测量不完整")
    current = coverage_to_baseline(coverage_data, report["inventory"], report["operations"], report["outcomes"],
                                   environment=profile, declared=report["declared_operations"], skips=report.get("skips", []))
    current["required_database_tests"] = sorted(report.get("required_database_tests", []))
    missing = set(report["declared_operations"]) - set(report["operations"])
    if missing:
        raise GateError("缺少 passing-test 成功 HTTP 调用：" + ", ".join(sorted(missing)))
    required = set(report.get("required_database_tests", []))
    if not required or any(report["outcomes"].get(node, {}).get("outcome") != "passed" for node in required):
        raise GateError("数据库必跑测试未全部通过；拒绝意外 skip")
    trusted = None
    trusted_ref = args.trusted_ref or ("origin/" + env["GITHUB_BASE_REF"] if env.get("GITHUB_BASE_REF") else env.get("TEST_GATE_BASE_REF"))
    if trusted_ref and set(trusted_ref) != {"0"}:
        resolved = git(root, "rev-parse", "--verify", trusted_ref + "^{commit}").strip()
        result = subprocess.run(["git", "show", resolved + ":" + args.baseline], cwd=root, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            trusted = json.loads(result.stdout)
        elif "does not exist" not in result.stderr and "exists on disk, but not in" not in result.stderr:
            raise GateError("无法读取可信基线；拒绝跳过 parent 检查")
    reconciliation = None
    reconciliation_file = getattr(args, "reconciliation_file", None)
    if reconciliation_file:
        reconciliation = json.loads(Path(reconciliation_file).read_text(encoding="utf-8"))
    elif old:
        reconciliation = old.get("reconciliation")
    errors = compare_baselines(current, old or current, trusted_baseline=trusted, reconciliation=reconciliation)
    if args.mode == "baseline" and args.reason.strip():
        errors = [error for error in errors if not error.startswith("new coverage file candidate")]
    if errors:
        raise GateError("棘轮失败：\n" + "\n".join(errors))
    totals = coverage_data.get("totals", {})
    print(f"[test-gate] inventory={len(current['inventory'])}, operations={len(current['operations'])}, "
          f"files={len(current['coverage'])}, line coverage={totals.get('percent_covered', 'unknown')}% (informational)")
    if args.mode == "baseline":
        if not args.reason.strip():
            raise GateError("显式基线更新需要 --reason")
        current["update_reason"] = args.reason.strip()
        if reconciliation:
            current["reconciliation"] = reconciliation
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("[test-gate] 显式写入审核基线：" + args.baseline)
    print("[test-gate] reports: " + str(report_root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("commit", "push", "ci", "baseline", "message"), required=True)
    parser.add_argument("--message-file", type=Path)
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--trusted-ref")
    parser.add_argument("--reason", default="")
    parser.add_argument("--reconciliation-file")
    parser.add_argument("--report-dir")
    args = parser.parse_args(argv)
    start = time.monotonic()
    env = dict(os.environ, TRADING_RULES_OFFLINE="1", PYTHONHASHSEED="0")
    try:
        if args.mode == "message":
            if not args.message_file:
                raise GateError("message mode 需要 --message-file")
            audit_message(args.message_file, env)
            return 0
        authoritative_mode = args.mode in {"ci", "baseline"} or bool(env.get("CI"))
        if authoritative_mode:
            for key in BYPASS_KEYS:
                env.pop(key, None)
        paths = None
        if args.mode == "push":
            push_refs = sys.stdin.read()
            paths = changed_paths(ROOT, args.mode, push_refs)
            env["DOCS_CONTRACT_DIFFS"] = json.dumps(docs_push_ranges(push_refs))
        if not authoritative_mode:
            run([sys.executable, "scripts/check-docs-contract.py", "--mode=" + ("fast" if args.mode == "commit" else "full")], ROOT, env)
            if env.get("SKIP_TEST_GATE") == "1":
                if not env.get("TEST_GATE_SKIP_REASON", "").strip():
                    raise GateError("应急跳过必须提供 TEST_GATE_SKIP_REASON")
                print("[test-gate] unverified：" + env["TEST_GATE_SKIP_REASON"])
                return 0
        if args.mode in {"ci", "baseline"}:
            authoritative(ROOT, args, env)
            run([sys.executable, "scripts/check-docs-contract.py", "--mode=full"], ROOT, docs_ci_environment(ROOT, args, env))
        else:
            assert_index_matches(ROOT)
            if args.mode == "push" and git(ROOT, "diff", "--cached", "--name-only").strip():
                raise GateError("push 验证要求工作树与 HEAD 一致；存在暂存改动")
            if paths is None:
                paths = changed_paths(ROOT, args.mode)
            if args.mode == "push":
                run([sys.executable, "scripts/check_market_environment_architecture.py"], ROOT, env)
                for command in ("validate", "coverage"):
                    run([sys.executable, "-m", "src.trading_system.cli", "rules", command], ROOT, env)
            backend, frontend, fallback = select_tests(ROOT, paths, args.mode == "push")
            print(f"[test-gate] selection fallback={fallback}; backend={backend}; frontend={frontend}")
            if backend:
                run([sys.executable, "-m", "pytest", *backend, "-q"], ROOT, env)
            if frontend:
                npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
                if not npm:
                    raise GateError("缺少 npm，无法验证前端")
                run([npm, "run", "test", "--", *([] if frontend == ["*"] else frontend)], ROOT / FRONTEND, env)
            if not backend and not frontend:
                print("[test-gate] 无测试相关改动；仅 docs contract 已验证")
        print("[test-gate] 通过")
        return 0
    except (GateError, ImportError, OSError, ValueError, KeyError) as error:
        print("[test-gate] " + str(error), file=sys.stderr)
        return 1
    finally:
        elapsed = time.monotonic() - start
        budget = {"commit": 30, "push": 180}.get(args.mode)
        print(f"[test-gate] elapsed={elapsed:.2f}s" + (f" budget={budget}s" if budget else ""))
        if budget and elapsed > budget:
            print("[test-gate] 建议预算超出；只告警，不覆盖测试结果")


if __name__ == "__main__":
    raise SystemExit(main())
