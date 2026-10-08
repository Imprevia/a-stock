"""Central redaction and integrity helpers for acquisition evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ...domain.models import RedactedProvenance


_SENSITIVE_NAMES = (
    "authorization",
    "cookie",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "secret",
    "password",
    "proxy",
    "credential",
    "body",
    "challenge",
)


def is_sensitive_name(name: object) -> bool:
    normalized = str(name).strip().lower().replace("-", "_")
    return any(marker in normalized for marker in _SENSITIVE_NAMES)


def redact_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme and not parts.netloc:
        return value
    query = [
        (key, "[REDACTED]" if is_sensitive_name(key) else item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
    ]
    hostname = parts.hostname or ""
    netloc = hostname
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc.lower(), parts.path, urlencode(query), ""))


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key)
        if is_sensitive_name(name):
            redacted[name] = "[REDACTED]"
        elif isinstance(item, Mapping):
            redacted[name] = redact_mapping(item)
        elif isinstance(item, (list, tuple)):
            redacted[name] = [
                redact_mapping(child) if isinstance(child, Mapping) else child
                for child in item
            ]
        elif name.lower() in {"url", "endpoint", "finalurl", "final_url"} and isinstance(item, str):
            redacted[name] = redact_url(item)
        else:
            redacted[name] = item
    return redacted


def redact_provenance(value: RedactedProvenance) -> RedactedProvenance:
    return RedactedProvenance(
        endpoint=redact_url(value.endpoint) if value.endpoint else None,
        engine=value.engine,
        request_id=value.request_id,
        authentication_scope_digest=value.authentication_scope_digest,
        attributes=redact_mapping(value.attributes),
    )


def evidence_fingerprint(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        redact_mapping(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "evidence_fingerprint",
    "is_sensitive_name",
    "redact_mapping",
    "redact_provenance",
    "redact_url",
]
