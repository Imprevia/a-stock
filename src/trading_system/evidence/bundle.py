"""Create immutable evidence bundles and detect tampering."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker

from ..data.canonical import canonical_json_bytes, sha256_value, validate_snapshot
from ..rules.models import RuleSetDefinition, RuleValidationError
from ..rules.registry import repository_root


def _git_sha(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _write_canonical(path: Path, value: Any) -> dict[str, Any]:
    content = canonical_json_bytes(value)
    path.write_bytes(content)
    return {"path": path.name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}


def create_evidence_bundle(
    output_dir: Path,
    snapshot: dict[str, Any],
    result: dict[str, Any],
    rule_set: RuleSetDefinition,
    *,
    root: Path | None = None,
    created_at: str | None = None,
    git_sha: str | None = None,
) -> Path:
    repo = root or repository_root()
    validate_snapshot(snapshot, repo)
    output_dir.mkdir(parents=True, exist_ok=True)
    created = created_at or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    evidence_id = f"{snapshot['asOf']}-{rule_set.name}-{result['snapshotHash'][:12]}"
    traces = result["traces"]
    summary = {key: value for key, value in result.items() if key != "traces"}
    files = [
        _write_canonical(output_dir / "snapshot.json", snapshot),
        _write_canonical(output_dir / "traces.json", traces),
        _write_canonical(output_dir / "result.json", summary),
    ]
    manifest = {
        "schemaVersion": 1,
        "evidenceId": evidence_id,
        "createdAt": created,
        "asOf": snapshot["asOf"],
        "status": snapshot["status"] if snapshot["status"] != "ok" else "ok",
        "ruleSet": rule_set.name,
        "ruleSetVersion": rule_set.version,
        "gitSha": git_sha or _git_sha(repo),
        "providerStatus": snapshot["providerQuality"],
        "warnings": snapshot["warnings"],
        "files": files,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    return manifest_path


def verify_evidence_bundle(bundle_dir: Path, root: Path | None = None) -> dict[str, Any]:
    repo = root or repository_root()
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        raise RuleValidationError(f"missing evidence manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads((repo / "trading-rules" / "schemas" / "evidence.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(manifest)

    loaded: dict[str, Any] = {}
    for item in manifest["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuleValidationError(f"unsafe evidence path: {item['path']}")
        path = bundle_dir / relative
        if not path.is_file():
            raise RuleValidationError(f"missing evidence file: {item['path']}")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != item["sha256"] or len(content) != item["bytes"]:
            raise RuleValidationError(f"evidence hash mismatch: {item['path']}")
        loaded[item["path"]] = json.loads(content)

    snapshot = loaded.get("snapshot.json")
    result = loaded.get("result.json")
    traces = loaded.get("traces.json")
    if snapshot is None or result is None or traces is None:
        raise RuleValidationError("evidence bundle must contain snapshot.json, traces.json, and result.json")
    validate_snapshot(snapshot, repo)
    if result.get("snapshotHash") != sha256_value(snapshot):
        raise RuleValidationError("result snapshotHash does not match snapshot.json")
    if manifest["ruleSet"] != result.get("ruleSet") or manifest["ruleSetVersion"] != result.get("ruleSetVersion"):
        raise RuleValidationError("manifest rule-set identity does not match result.json")
    if len(traces) == 0:
        raise RuleValidationError("evidence trace is empty")
    return {"evidenceId": manifest["evidenceId"], "status": manifest["status"], "files": len(manifest["files"])}
