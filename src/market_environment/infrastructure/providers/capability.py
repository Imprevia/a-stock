"""Versioned, redacted capability reports for external market providers.

Capability reports are deliberately separate from public market snapshots.  A
report records why a provider may (or may not) be eligible for one dataset and
can therefore be audited without exposing request credentials or raw rows.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal, Mapping


CapabilityStatus = Literal["eligible", "ineligible", "unverified"]
CapabilityDataset = Literal["core", "breadth", "sectors", "activeDirection", "limits"]
CAPABILITY_DATASETS: tuple[str, ...] = ("core", "breadth", "sectors", "activeDirection", "limits")
MIGRATABLE_DATASETS: tuple[str, ...] = ("core", "breadth", "sectors", "activeDirection")
CAPABILITY_SCHEMA_VERSION = 1


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checksum(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


_SECRET_KEY = re.compile(r"(?:api[_-]?key|token|secret|password|authorization|cookie|credential)", re.I)
_SECRET_VALUE = re.compile(r"bearer\s+[A-Za-z0-9_\-]{12,}", re.I)


def redact(value: Any, *, key: str = "") -> Any:
    """Return a JSON-compatible value with likely credentials removed."""

    if _SECRET_KEY.search(key):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, key=key) for item in value]
    if isinstance(value, str) and _SECRET_VALUE.fullmatch(value.strip()):
        return "[redacted]"
    return value


@dataclass(frozen=True)
class ProviderCapabilityReport:
    """Evidence-backed capability result for one provider/dataset revision."""

    provider: str
    dataset: str
    revision: str
    status: CapabilityStatus
    endpoint: str | None = None
    field_coverage: Mapping[str, Any] = field(default_factory=dict)
    date_evidence: Mapping[str, Any] = field(default_factory=dict)
    history_window: Mapping[str, Any] = field(default_factory=dict)
    pagination_evidence: Mapping[str, Any] = field(default_factory=dict)
    permission_evidence: Mapping[str, Any] = field(default_factory=dict)
    rate_limit_evidence: Mapping[str, Any] = field(default_factory=dict)
    sample_count: int = 0
    warnings: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: int = CAPABILITY_SCHEMA_VERSION
    checksum: str = ""

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must not be empty")
        if self.dataset not in CAPABILITY_DATASETS:
            raise ValueError(f"unsupported capability dataset: {self.dataset}")
        if not self.revision.strip():
            raise ValueError("revision must not be empty")
        if self.status not in {"eligible", "ineligible", "unverified"}:
            raise ValueError(f"unsupported capability status: {self.status}")
        if int(self.sample_count) < 0:
            raise ValueError("sample_count must be non-negative")
        if self.schema_version != CAPABILITY_SCHEMA_VERSION:
            raise ValueError(f"unsupported capability schema version: {self.schema_version}")

    def logical_dict(self) -> dict[str, Any]:
        checked_at = _utc(self.checked_at)
        return {
            "provider": self.provider,
            "dataset": self.dataset,
            "revision": self.revision,
            "status": self.status,
            "endpoint": self.endpoint,
            "field_coverage": dict(self.field_coverage),
            "date_evidence": dict(self.date_evidence),
            "history_window": dict(self.history_window),
            "pagination_evidence": dict(self.pagination_evidence),
            "permission_evidence": dict(self.permission_evidence),
            "rate_limit_evidence": dict(self.rate_limit_evidence),
            "sample_count": int(self.sample_count),
            "warnings": list(self.warnings),
            "missing_evidence": list(self.missing_evidence),
            "checked_at": checked_at.isoformat(),
            "schema_version": self.schema_version,
        }

    def normalized(self) -> "ProviderCapabilityReport":
        value = replace(self, checked_at=_utc(self.checked_at))
        return replace(value, checksum=value.checksum or _checksum(value.logical_dict()))

    def to_dict(self, *, redacted: bool = False) -> dict[str, Any]:
        value = self.normalized()
        result = {**value.logical_dict(), "checksum": value.checksum}
        return redact(result) if redacted else result

    def redacted_dict(self) -> dict[str, Any]:
        return self.to_dict(redacted=True)

    @property
    def provider_revision(self) -> str:
        """Compatibility accessor used by collection metadata consumers."""

        return self.revision

    @property
    def evidence(self) -> dict[str, Any]:
        """Return the structured evidence fields as one redaction-ready map."""

        return {
            "endpoint": self.endpoint,
            "field_coverage": dict(self.field_coverage),
            "date_evidence": dict(self.date_evidence),
            "history_window": dict(self.history_window),
            "pagination_evidence": dict(self.pagination_evidence),
            "permission_evidence": dict(self.permission_evidence),
            "rate_limit_evidence": dict(self.rate_limit_evidence),
            "sample_count": self.sample_count,
            "warnings": list(self.warnings),
            "missing_evidence": list(self.missing_evidence),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderCapabilityReport":
        raw_checked_at = value.get("checked_at")
        checked_at = datetime.fromisoformat(str(raw_checked_at)) if raw_checked_at else datetime.now(timezone.utc)
        supplied_checksum = str(value.get("checksum", ""))
        result = cls(
            provider=str(value.get("provider", "")),
            dataset=str(value.get("dataset", "")),
            revision=str(value.get("revision", "")),
            status=value.get("status", "unverified"),  # type: ignore[arg-type]
            endpoint=value.get("endpoint"),
            field_coverage=dict(value.get("field_coverage") or {}),
            date_evidence=dict(value.get("date_evidence") or {}),
            history_window=dict(value.get("history_window") or {}),
            pagination_evidence=dict(value.get("pagination_evidence") or {}),
            permission_evidence=dict(value.get("permission_evidence") or {}),
            rate_limit_evidence=dict(value.get("rate_limit_evidence") or {}),
            sample_count=int(value.get("sample_count", 0)),
            warnings=tuple(str(item) for item in value.get("warnings", ())),
            missing_evidence=tuple(str(item) for item in value.get("missing_evidence", ())),
            checked_at=checked_at,
            schema_version=int(value.get("schema_version", CAPABILITY_SCHEMA_VERSION)),
            checksum="",
        ).normalized()
        if supplied_checksum and result.checksum != supplied_checksum:
            raise ValueError("capability report checksum mismatch")
        return result


# Short aliases keep the model discoverable for callers that use the shorter
# terminology while retaining one canonical serialized representation.
CapabilityReport = ProviderCapabilityReport
FuyaoCapabilityReport = ProviderCapabilityReport


__all__ = [
    "CAPABILITY_DATASETS",
    "CAPABILITY_SCHEMA_VERSION",
    "MIGRATABLE_DATASETS",
    "CapabilityDataset",
    "CapabilityReport",
    "CapabilityStatus",
    "FuyaoCapabilityReport",
    "ProviderCapabilityReport",
    "redact",
]
