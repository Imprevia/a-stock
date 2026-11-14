"""Generic cross-skill report identity helpers.

Each QTS-04 step owns its own ``config`` and decision payload, but the identity
rule is shared: a canonical subset, SHA-256, first 16 hex characters.  Keeping
the rule in one place means two steps cannot drift on what "same report" means.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "1.0"
REPORT_ID_LENGTH = 16


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def canonical_payload(result: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    """The decision-bearing subset named by ``fields``."""

    return {field: result.get(field) for field in fields}


def compute_report_id(
    result: Mapping[str, Any],
    fields: Sequence[str],
    *,
    length: int = REPORT_ID_LENGTH,
) -> str:
    """SHA-256 of the canonical subset, truncated to ``length`` hex chars."""

    encoded = _canonical_json(canonical_payload(result, fields)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def attach_identity(
    result: dict[str, Any],
    *,
    schema_version: str,
    fields: Sequence[str],
    step: str | None = None,
) -> dict[str, Any]:
    """Add ``schemaVersion`` / optional ``step`` / ``reportId`` in place."""

    result["schemaVersion"] = schema_version
    if step is not None:
        result["step"] = step
    result["reportId"] = compute_report_id(result, fields)
    return result


def require_schema_version(
    payload: Mapping[str, Any],
    *,
    supported: str | Sequence[str] = SCHEMA_VERSION,
) -> str:
    """Reject payloads that do not declare a supported schema version."""

    version = payload.get("schemaVersion") if isinstance(payload, Mapping) else None
    if not version:
        raise ValueError("缺少 schemaVersion，拒绝按当前版本解析")
    allowed = (supported,) if isinstance(supported, str) else tuple(supported)
    if str(version) not in allowed:
        raise ValueError(f"不支持的 schemaVersion：{version}（当前 {'/'.join(allowed)}）")
    return str(version)
