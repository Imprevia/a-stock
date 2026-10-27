"""Pure helpers for the test ratchet baseline and comparison."""
from __future__ import annotations

import copy
import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Any, Mapping

_EXCLUDED = ("/docs", "/redoc", "/openapi.json", "/assets")


def _operation_key(method: str, path: str) -> str:
    return f"{method.upper()} {path}"


def declared_operations(openapi: Mapping[str, Any]) -> list[str]:
    """Return the exact method/path operation set from an OpenAPI document."""
    result: set[str] = set()
    for path, item in (openapi.get("paths") or {}).items():
        if any(path == prefix or path.startswith(prefix + "/") for prefix in _EXCLUDED):
            continue
        if path in {"/{path}", "/{path:path}"} or "{path:path}" in path or path.startswith("/static"):
            continue
        if not isinstance(item, Mapping):
            continue
        for method, operation in item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}:
                continue
            result.add(_operation_key(method, path))
    return sorted(result)


def collect_operations(app: Any) -> list[str]:
    """Extract declared operations, allowing FastAPI's lazy router inclusion."""
    return declared_operations(app.openapi())


def sanitized_environment(extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return comparison-relevant, credential-free environment facts."""
    data: dict[str, Any] = {
        "python_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": platform.system().lower(),
        "coverage_major": None,
        "backend_profile": "configured" if os.environ.get("MARKET_ENVIRONMENT_TEST_DATABASE_URL") else "unconfigured",
    }
    try:
        import coverage
        data["coverage_major"] = int(str(coverage.__version__).split(".", 1)[0])
    except Exception:
        pass
    if extra is not None:
        data = {}
        allowed = {"python_minor", "coverage_major", "backend_profile", "database_backend", "schema_profile", "test_profile", "platform", "database_configured"}
        for key, value in extra.items():
            if key not in allowed or not isinstance(value, (str, int, bool, type(None))):
                continue
            if isinstance(value, str) and not re.fullmatch(r"[A-Za-z0-9_. -]{0,100}", value):
                continue
            data[key] = value
    return data


def coverage_to_baseline(
    coverage_json: Mapping[str, Any] | str | Path,
    inventory: list[str],
    operations: list[str],
    outcomes: Mapping[str, Any] | list[Mapping[str, Any]],
    environment: Mapping[str, Any] | None = None,
    *,
    declared: list[str] | None = None,
    skips: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert coverage.py JSON into a curated baseline without writing files."""
    if isinstance(coverage_json, (str, Path)):
        coverage_json = json.loads(Path(coverage_json).read_text(encoding="utf-8"))
    if not isinstance(coverage_json, Mapping):
        raise ValueError("coverage report must be an object")
    files = coverage_json.get("files")
    if not isinstance(files, Mapping) or not files:
        raise ValueError("coverage report has no source files")
    coverage: dict[str, int] = {}
    for name, value in files.items():
        normalized = str(name).replace("\\", "/")
        if not normalized.startswith("src/") or ".." in normalized.split("/"):
            continue
        summary = value.get("summary") if isinstance(value, Mapping) else None
        if not isinstance(summary, Mapping):
            raise ValueError(f"coverage source file has no valid summary: {normalized}")
        missing = summary.get("missing_lines", summary.get("num_missing"))
        if isinstance(missing, bool) or not isinstance(missing, int) or missing < 0:
            raise ValueError(f"coverage source file has no valid uncovered count: {normalized}")
        coverage[normalized] = missing
    if not coverage:
        raise ValueError("coverage report has no valid src/ source files")
    return {
        "inventory": sorted(str(entry) for entry in inventory),
        "operations": sorted(str(entry) for entry in operations),
        "declared_operations": sorted(str(entry) for entry in (declared if declared is not None else operations)),
        "coverage": dict(sorted(coverage.items())),
        "coverage_summary": copy.deepcopy(coverage_json.get("totals", {})),
        "environment": sanitized_environment(environment),
        "outcomes": copy.deepcopy(outcomes),
        "skips": copy.deepcopy(skips or []),
    }


def _as_statuses(value: Any) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {
            str(nodeid): str(outcome.get("outcome", outcome) if isinstance(outcome, Mapping) else outcome)
            for nodeid, outcome in value.items()
        }
    result: dict[str, str] = {}
    for row in value or []:
        if isinstance(row, Mapping) and row.get("nodeid"):
            result[str(row["nodeid"])] = str(row.get("outcome", ""))
    return result


def _mapping(reconciliation: Mapping[str, Any] | None) -> tuple[dict[str, str], list[str]]:
    if not reconciliation:
        return {}, []
    reason = reconciliation.get("reason")
    errors: list[str] = []
    if not isinstance(reason, str) or not reason.strip():
        errors.append("reconciliation requires a non-empty reason")
    mapping = reconciliation.get("mapping", {})
    if not isinstance(mapping, Mapping):
        errors.append("reconciliation mapping must be an object")
        return {}, errors
    forward: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for old, new in mapping.items():
        if not isinstance(old, str) or not isinstance(new, str):
            errors.append("reconciliation mapping keys and values must be strings")
            continue
        if old in forward and forward[old] != new:
            errors.append(f"reconciliation maps {old} more than once")
        if new in reverse and reverse[new] != old:
            errors.append(f"reconciliation target {new} has multiple parents")
        forward[old] = new
        reverse[new] = old
    if reconciliation.get("reverse_mapping") != reverse:
        errors.append("reconciliation requires an exact reverse_mapping")
    return forward, errors


def compare_baselines(
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
    trusted_baseline: Mapping[str, Any] | None = None,
    reconciliation: Mapping[str, Any] | None = None,
) -> list[str]:
    """Pure monotonic comparison; returns all errors and never mutates inputs."""
    errors: list[str] = []
    mapping, rec_errors = _mapping(reconciliation)
    errors.extend(rec_errors)
    inv = set(current.get("inventory", [])); old_inv = set(baseline.get("inventory", []))
    old_facts = old_inv | set(baseline.get("operations", [])) | set(baseline.get("coverage", {}))
    new_facts = inv | set(current.get("operations", [])) | set(current.get("coverage", {}))
    for old, new in mapping.items():
        if old not in old_facts and (trusted_baseline is not None or (new in old_facts and new in new_facts)):
            continue
        if old not in old_facts or old in new_facts or new not in new_facts or new in old_facts:
            errors.append(f"invalid reconciliation: {old}->{new}")
    if not inv:
        errors.append("empty test inventory: measurement incomplete")
    declared = set(current.get("declared_operations", []))
    current_ops = set(current.get("operations", []))
    if not current_ops:
        errors.append("no successful HTTP operation instrumentation: measurement incomplete")
    if declared - current_ops:
        errors.append("declared operations lack successful dispatch: " + ", ".join(sorted(declared - current_ops)))
    statuses = _as_statuses(current.get("outcomes", {}))
    for node in sorted(inv):
        if statuses.get(node) not in {"passed", "skipped", "xfailed"}:
            errors.append(f"test did not pass or explicitly skip: {node} ({statuses.get(node, 'not_run')})")
    required_db = set(current.get("required_database_tests", []))
    for node in sorted(required_db):
        if statuses.get(node) != "passed":
            errors.append(f"database test did not execute successfully: {node}")
    for node, status in statuses.items():
        if status == "failed":
            errors.append(f"failed test: {node}")
    inv_missing = old_inv - inv
    inv_missing -= set(mapping)
    if inv_missing:
        errors.append("removed test node IDs: " + ", ".join(sorted(inv_missing)))
    old_ops = set(baseline.get("operations", [])); cur_ops = set(current.get("operations", []))
    op_missing = {op for op in old_ops if mapping.get(op, op) not in cur_ops}
    if op_missing:
        errors.append("missing exercised operations: " + ", ".join(sorted(op_missing)))
    old_status = _as_statuses(baseline.get("outcomes", {})); cur_status = _as_statuses(current.get("outcomes", {}))
    for node, status in old_status.items():
        if status == "passed" and cur_status.get(mapping.get(node, node)) in {"skipped", "xfailed"}:
            errors.append(f"passing test became {cur_status[mapping.get(node, node)]}: {node}")
    base_cov = {str(path): int(count) for path, count in (baseline.get("coverage") or {}).items()}
    cur_cov = {str(path): int(count) for path, count in (current.get("coverage") or {}).items()}
    if not base_cov or not cur_cov:
        errors.append("empty coverage facts: measurement incomplete")
    for path, old_count in base_cov.items():
        target = mapping.get(path, path)
        if target not in cur_cov:
            errors.append(f"coverage file removed: {path}")
        elif cur_cov[target] > old_count:
            errors.append(f"uncovered statements increased: {path} {old_count}->{cur_cov[target]}")
    renamed_files = {mapping[path] for path in base_cov if path in mapping}
    for path in sorted(set(cur_cov) - set(base_cov) - renamed_files):
        errors.append(f"new coverage file candidate requires explicit baseline review: {path} (uncovered={cur_cov[path]})")
    base_env = baseline.get("environment") or {}; cur_env = current.get("environment") or {}
    for key in sorted(set(base_env) | set(cur_env)):
        if base_env.get(key) != cur_env.get(key):
            errors.append(f"environment mismatch: {key} {base_env.get(key)!r}!={cur_env.get(key)!r}")
    if trusted_baseline is not None:
        errors.extend("trusted parent: " + error for error in compare_baselines(
            baseline, trusted_baseline, reconciliation=reconciliation
        ) if not error.startswith("new coverage file candidate"))
    return errors

__all__ = ["collect_operations", "declared_operations", "sanitized_environment", "coverage_to_baseline", "compare_baselines"]
