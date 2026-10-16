"""Pure consistency primitives for the versioned market-data read surface.

The values produced here are transport-neutral.  HTTP ETag and response
handling live in ``interfaces.http.v2_conditional`` so application queries do
not depend on FastAPI.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from ...domain.models import MaterializationRevision


_REVISION_DOMAIN = b"a-stock/snapshot-revision/v1\0"
_CURSOR_DOMAIN = b"a-stock/market-data-cursor/v1\0"
_CURSOR_VERSION = 1


def _json_value(value: Any) -> Any:
    if isinstance(value, MaterializationRevision):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported consistency value: {type(value).__name__}")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def opaque_snapshot_revision(
    component_revision: MaterializationRevision | str | Mapping[str, Any] | Sequence[Any],
) -> str:
    """Return a stable public digest without exposing private revision input."""

    if isinstance(component_revision, str) and not component_revision.strip():
        raise ValueError("component revision must not be empty")
    digest = hashlib.sha256(_REVISION_DOMAIN + _canonical_json(component_revision)).digest()
    token = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sr1_{token}"


@dataclass(frozen=True, slots=True)
class CollectionLimit:
    default: int
    maximum: int

    def __post_init__(self) -> None:
        if self.default < 1 or self.maximum < self.default:
            raise ValueError("collection limits require 1 <= default <= maximum")


COLLECTION_LIMITS: Mapping[str, CollectionLimit] = {
    "limits_pool": CollectionLimit(default=20, maximum=100),
    "sector_rankings": CollectionLimit(default=20, maximum=100),
    "sector_turnover": CollectionLimit(default=20, maximum=100),
    "sector_breadth": CollectionLimit(default=20, maximum=100),
    "active_direction": CollectionLimit(default=20, maximum=100),
    "index_history": CollectionLimit(default=60, maximum=250),
    "breadth_history": CollectionLimit(default=60, maximum=250),
    "limits_history": CollectionLimit(default=60, maximum=250),
    "operation_checkpoints": CollectionLimit(default=50, maximum=200),
}


class CollectionLimitError(ValueError):
    def __init__(self, resource: str, value: int, maximum: int) -> None:
        self.resource = resource
        self.value = value
        self.maximum = maximum
        super().__init__(
            f"limit for {resource} must be between 1 and {maximum}, got {value}"
        )


def resolve_collection_limit(resource: str, requested: int | None) -> int:
    try:
        boundary = COLLECTION_LIMITS[resource]
    except KeyError as exc:
        raise ValueError(f"unknown bounded collection: {resource}") from exc
    value = boundary.default if requested is None else requested
    if isinstance(value, bool) or value < 1 or value > boundary.maximum:
        raise CollectionLimitError(resource, value, boundary.maximum)
    return value


class CursorError(ValueError):
    code = "cursor_invalid"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class MalformedCursorError(CursorError):
    code = "cursor_malformed"


class CursorBindingError(CursorError):
    code = "cursor_binding_mismatch"


class StaleCursorRevisionError(CursorError):
    code = "snapshot_revision_conflict"

    def __init__(self, cursor_revision: str, current_revision: str) -> None:
        self.cursor_revision = cursor_revision
        self.current_revision = current_revision
        super().__init__("cursor snapshot revision no longer matches current evidence")


@dataclass(frozen=True, slots=True)
class CursorState:
    resource: str
    scope: Mapping[str, Any]
    filters: Mapping[str, Any]
    sort_key: Sequence[Any]
    snapshot_revision: str


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def encode_cursor(
    *,
    resource: str,
    scope: Mapping[str, Any],
    filters: Mapping[str, Any] | None,
    sort_key: Sequence[Any],
    snapshot_revision: str,
) -> str:
    if not resource.strip():
        raise ValueError("cursor resource must not be empty")
    if not snapshot_revision.strip():
        raise ValueError("cursor snapshot revision must not be empty")
    if isinstance(sort_key, (str, bytes)) or not sort_key:
        raise ValueError("cursor sort key must be a non-empty sequence")
    payload = _canonical_json(
        {
            "v": _CURSOR_VERSION,
            "resource": resource,
            "scope": dict(scope),
            "filters": dict(filters or {}),
            "sortKey": list(sort_key),
            "snapshotRevision": snapshot_revision,
        }
    )
    signature = hashlib.sha256(_CURSOR_DOMAIN + payload).digest()
    return f"c1.{_b64encode(payload)}.{_b64encode(signature)}"


def decode_cursor(
    token: str,
    *,
    expected_resource: str,
    expected_scope: Mapping[str, Any],
    expected_filters: Mapping[str, Any] | None,
    current_snapshot_revision: str,
) -> CursorState:
    try:
        prefix, encoded_payload, encoded_signature = token.split(".")
        if prefix != "c1":
            raise ValueError("unsupported cursor prefix")
        payload = _b64decode(encoded_payload)
        signature = _b64decode(encoded_signature)
        expected_signature = hashlib.sha256(_CURSOR_DOMAIN + payload).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("cursor signature mismatch")
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict) or decoded.get("v") != _CURSOR_VERSION:
            raise ValueError("unsupported cursor payload")
        resource = decoded["resource"]
        scope = decoded["scope"]
        filters = decoded["filters"]
        sort_key = decoded["sortKey"]
        revision = decoded["snapshotRevision"]
        if (
            not isinstance(resource, str)
            or not isinstance(scope, dict)
            or not isinstance(filters, dict)
            or not isinstance(sort_key, list)
            or not sort_key
            or not isinstance(revision, str)
        ):
            raise ValueError("invalid cursor payload types")
    except (KeyError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise MalformedCursorError("cursor is malformed or has been altered") from exc

    if resource != expected_resource:
        raise CursorBindingError("cursor belongs to a different resource")
    if _canonical_json(scope) != _canonical_json(dict(expected_scope)):
        raise CursorBindingError("cursor belongs to a different date or operation")
    if _canonical_json(filters) != _canonical_json(dict(expected_filters or {})):
        raise CursorBindingError("cursor filters do not match the request")
    if revision != current_snapshot_revision:
        raise StaleCursorRevisionError(revision, current_snapshot_revision)
    return CursorState(
        resource=resource,
        scope=scope,
        filters=filters,
        sort_key=tuple(sort_key),
        snapshot_revision=revision,
    )


__all__ = [
    "COLLECTION_LIMITS",
    "CollectionLimit",
    "CollectionLimitError",
    "CursorBindingError",
    "CursorError",
    "CursorState",
    "MalformedCursorError",
    "StaleCursorRevisionError",
    "decode_cursor",
    "encode_cursor",
    "opaque_snapshot_revision",
    "resolve_collection_limit",
]
