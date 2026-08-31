"""Cross-platform canonical JSON and snapshot validation."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("canonical JSON rejects NaN and infinite values")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    normalized = _normalize(value)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _load_schema(name: str, root: Path | None = None) -> dict[str, Any]:
    repo = root or repository_root()
    return json.loads((repo / "trading-rules" / "schemas" / name).read_text(encoding="utf-8"))


def validate_event(event: dict[str, Any], root: Path | None = None) -> None:
    validator = Draft202012Validator(_load_schema("event.schema.json", root), format_checker=FormatChecker())
    validator.validate(event)


def validate_snapshot(snapshot: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    schema = _load_schema("snapshot.schema.json", root)
    schema["properties"]["events"]["items"] = {"type": "object"}
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(snapshot)
    for event in snapshot["events"]:
        validate_event(event, root)
    canonical_json_bytes(snapshot)
    return snapshot


def load_snapshot(path: Path, root: Path | None = None) -> dict[str, Any]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    return validate_snapshot(snapshot, root)
