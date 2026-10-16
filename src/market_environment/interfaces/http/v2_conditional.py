"""HTTP conditional request helpers for v2 market-data resources."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Response
from fastapi.responses import JSONResponse


def format_etag(snapshot_revision: str) -> str:
    if not snapshot_revision or any(char in snapshot_revision for char in ('"', "\r", "\n")):
        raise ValueError("snapshot revision cannot be represented as an ETag")
    return f'"{snapshot_revision}"'


def _etag_values(header: str | None, *, weak_ok: bool) -> set[str]:
    if header is None:
        return set()
    values: set[str] = set()
    for item in header.split(","):
        value = item.strip()
        if value == "*":
            values.add(value)
            continue
        if value.startswith("W/"):
            if not weak_ok:
                continue
            value = value[2:].strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            values.add(value[1:-1])
    return values


@dataclass(frozen=True, slots=True)
class SnapshotRevisionConflict(Exception):
    requested_revision: str | None
    current_revision: str
    code: str = "snapshot_revision_conflict"

    def __str__(self) -> str:
        return "requested snapshot revision does not match current evidence"


def require_snapshot_revision(current_revision: str, if_match: str | None) -> None:
    if if_match is None:
        return
    candidates = _etag_values(if_match, weak_ok=False)
    if "*" in candidates or current_revision in candidates:
        return
    requested = next(iter(candidates), None)
    raise SnapshotRevisionConflict(requested, current_revision)


def not_modified(current_revision: str, if_none_match: str | None) -> bool:
    candidates = _etag_values(if_none_match, weak_ok=True)
    return "*" in candidates or current_revision in candidates


def conditional_not_modified_response(
    current_revision: str,
    if_none_match: str | None,
) -> Response | None:
    if not not_modified(current_revision, if_none_match):
        return None
    return Response(status_code=304, headers={"ETag": format_etag(current_revision)})


def snapshot_revision_conflict_response(
    conflict: SnapshotRevisionConflict,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": conflict.code,
                "message": str(conflict),
                "requestedSnapshotRevision": conflict.requested_revision,
                "currentSnapshotRevision": conflict.current_revision,
            }
        },
        headers={"ETag": format_etag(conflict.current_revision)},
    )


__all__ = [
    "SnapshotRevisionConflict",
    "conditional_not_modified_response",
    "format_etag",
    "not_modified",
    "require_snapshot_revision",
    "snapshot_revision_conflict_response",
]
