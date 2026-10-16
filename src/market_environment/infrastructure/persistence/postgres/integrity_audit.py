"""Provider-free, read-only audit of persisted exact-date evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text


def _json_object(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _index_tails(payload: Mapping[str, Any]) -> tuple[dict[str, str | None], ...]:
    indices = payload.get("indices")
    if not isinstance(indices, Sequence) or isinstance(indices, (str, bytes)):
        return ()
    tails: list[dict[str, str | None]] = []
    for value in indices:
        if not isinstance(value, Mapping):
            continue
        history = value.get("history")
        tail = (
            history[-1]
            if isinstance(history, Sequence)
            and not isinstance(history, (str, bytes))
            and history
            else None
        )
        tails.append(
            {
                "code": str(value.get("code") or "unknown"),
                "historyTail": (
                    _iso(tail.get("date")) if isinstance(tail, Mapping) else None
                ),
            }
        )
    return tuple(tails)


def audit_core_date_integrity(connection: Connection) -> tuple[dict[str, Any], ...]:
    """Return bounded date/checksum references without mutating or exposing payloads."""

    findings: list[dict[str, Any]] = []
    snapshot_rows = connection.execute(
        text(
            "SELECT dataset, as_of, payload_json, checksum "
            "FROM snapshot_entries WHERE dataset = 'core' ORDER BY as_of"
        )
    ).mappings()
    for row in snapshot_rows:
        payload = _json_object(row["payload_json"])
        quality = payload.get("quality")
        quality = quality if isinstance(quality, Mapping) else {}
        findings.append(
            {
                "kind": "snapshot",
                "dataset": str(row["dataset"]),
                "keyAsOf": _iso(row["as_of"]),
                "payloadAsOf": _iso(payload.get("asOf")),
                "qualityAsOf": _iso(quality.get("asOf")),
                "effectiveAsOf": _iso(quality.get("effectiveAsOf")),
                "checksum": str(row["checksum"]),
                "componentRevision": None,
                "indices": _index_tails(payload),
            }
        )
    aggregate_rows = connection.execute(
        text(
            "SELECT as_of, payload_json, checksum "
            "FROM materialized_market_environment ORDER BY as_of"
        )
    ).mappings()
    for row in aggregate_rows:
        payload = _json_object(row["payload_json"])
        findings.append(
            {
                "kind": "aggregate",
                "dataset": None,
                "keyAsOf": _iso(row["as_of"]),
                "payloadAsOf": _iso(payload.get("asOf")),
                "qualityAsOf": None,
                "effectiveAsOf": None,
                "checksum": str(row["checksum"]),
                "componentRevision": _iso(payload.get("_componentRevision")),
                "indices": _index_tails(payload),
            }
        )
    return tuple(findings)


__all__ = ["audit_core_date_integrity"]
