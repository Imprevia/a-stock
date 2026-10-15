"""Pure values for the durable full-collection automation boundary."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping

from .values import AcquisitionFailure, DATASET_IDS


FULL_COLLECTION_OPERATION_SCOPE = "market-environment.full-collection"
FULL_COLLECTION_OPERATION_VERSION = "v1"
CANONICAL_FULL_COLLECTION_DATASETS = DATASET_IDS
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_URI_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<credentials>[^/@\s]+)@",
    re.IGNORECASE,
)
_AUTHORIZATION = re.compile(
    r"(?i)\b(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*([^\s,;&]+)"
)
_SECRET_QUERY = re.compile(
    r"(?i)([?&](?:api[_-]?key|token|password|secret)=)([^&#\s]+)"
)


def redact_failure_message(value: str) -> str:
    """Return a compact message with common credential forms removed."""

    message = " ".join(str(value).split())
    message = _URI_CREDENTIALS.sub(r"\g<scheme>***@", message)
    message = _AUTHORIZATION.sub(r"\1[REDACTED]", message)
    message = _SECRET_ASSIGNMENT.sub(r"\1=[REDACTED]", message)
    message = _SECRET_QUERY.sub(r"\1[REDACTED]", message)
    return message[:1000]


def _redact_optional_failure_text(value: str | None) -> str | None:
    if value is None:
        return None
    safe_value = redact_failure_message(value)
    return safe_value or None


class CollectionFailureCategory(str, Enum):
    CONFIGURATION = "configuration"
    ENGINE_UNAVAILABLE = "engine-unavailable"
    NETWORK = "network"
    RATE_LIMIT = "rate-limit"
    PERMISSION = "permission"
    CHALLENGE = "challenge"
    CONTRACT = "contract"
    DATE_MISMATCH = "date-mismatch"
    INSUFFICIENT = "insufficient"
    INTERNAL = "internal"
    DEPENDENCY = "dependency"
    CONCURRENCY = "concurrency"
    WORKER_INTERRUPTED = "worker-interrupted"


@dataclass(frozen=True, slots=True)
class StructuredTaskFailure:
    category: CollectionFailureCategory
    message: str
    retryable: bool
    retained: bool
    source: str | None = None
    stage: str | None = None
    code: str | None = None
    blocked_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.category, CollectionFailureCategory):
            raise TypeError("structured failure category must be CollectionFailureCategory")
        safe_message = redact_failure_message(self.message)
        if not safe_message:
            raise ValueError("structured failure message must not be empty")
        object.__setattr__(self, "message", safe_message)
        for field_name in ("source", "stage", "code"):
            object.__setattr__(
                self,
                field_name,
                _redact_optional_failure_text(getattr(self, field_name)),
            )
        object.__setattr__(
            self,
            "blocked_by",
            tuple(
                dict.fromkeys(
                    safe_value
                    for value in self.blocked_by
                    if (safe_value := _redact_optional_failure_text(str(value)))
                    is not None
                )
            ),
        )

    @classmethod
    def from_acquisition(
        cls,
        failure: AcquisitionFailure,
        *,
        retained: bool,
    ) -> "StructuredTaskFailure":
        return cls(
            category=CollectionFailureCategory(failure.category.value),
            message=failure.message,
            retryable=failure.retryable,
            retained=retained,
            source=failure.source,
            stage="acquisition",
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuredTaskFailure":
        return cls(
            category=CollectionFailureCategory(str(value["category"])),
            message=str(value["message"]),
            retryable=bool(value["retryable"]),
            retained=bool(value.get("retained", False)),
            source=str(value["source"]) if value.get("source") is not None else None,
            stage=str(value["stage"]) if value.get("stage") is not None else None,
            code=str(value["code"]) if value.get("code") is not None else None,
            blocked_by=tuple(str(item) for item in value.get("blockedBy", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "message": self.message,
            "retryable": self.retryable,
            "retained": self.retained,
            "source": self.source,
            "stage": self.stage,
            "code": self.code,
            "blockedBy": list(self.blocked_by),
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    value: str

    def __post_init__(self) -> None:
        raw = str(self.value)
        normalized = raw.strip()
        if normalized != raw or not _IDEMPOTENCY_KEY.fullmatch(normalized):
            raise ValueError(
                "idempotency key must be 1-200 ASCII letters, digits, dot, underscore, colon or hyphen"
            )
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class FullCollectionSemantics:
    resolved_as_of: date
    operation_scope: str = FULL_COLLECTION_OPERATION_SCOPE
    operation_version: str = FULL_COLLECTION_OPERATION_VERSION
    datasets: tuple[str, ...] = CANONICAL_FULL_COLLECTION_DATASETS

    def __post_init__(self) -> None:
        if self.operation_scope != FULL_COLLECTION_OPERATION_SCOPE:
            raise ValueError("unsupported full-collection operation scope")
        if not self.operation_version.strip():
            raise ValueError("full-collection operation version is required")
        if tuple(self.datasets) != CANONICAL_FULL_COLLECTION_DATASETS:
            raise ValueError("full collection requires the canonical seven datasets in stable order")

    @classmethod
    def create(
        cls,
        resolved_as_of: date,
        *,
        wait_timeout_seconds: float | None = None,
    ) -> "FullCollectionSemantics":
        if wait_timeout_seconds is not None and not 0 <= wait_timeout_seconds <= 900:
            raise ValueError("wait timeout must be between 0 and 900 seconds")
        # Waiting is a transport preference and is intentionally not stored.
        return cls(resolved_as_of=resolved_as_of)

    def payload(self) -> dict[str, Any]:
        return {
            "operationScope": self.operation_scope,
            "operationVersion": self.operation_version,
            "resolvedAsOf": self.resolved_as_of.isoformat(),
            "datasets": list(self.datasets),
        }

    @property
    def semantic_fingerprint(self) -> str:
        return _sha256(self.payload())

    @property
    def dataset_fingerprint(self) -> str:
        return _sha256({"datasets": list(self.datasets)})


class SubmissionState(str, Enum):
    RESERVED = "reserved"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    SUBMISSION_FAILED = "submission-failed"


@dataclass(frozen=True, slots=True)
class IdempotencyBinding:
    operation_scope: str
    key: IdempotencyKey
    semantic_fingerprint: str
    resolved_as_of: date
    operation_version: str
    dataset_fingerprint: str
    run_id: str
    submission_state: SubmissionState
    submission_attempts: int
    created_at: datetime
    updated_at: datetime
    submission_owner: str | None = None
    submission_lease_expires_at: datetime | None = None
    submission_error: StructuredTaskFailure | None = None
    submitted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.operation_scope.strip() or not self.run_id.strip():
            raise ValueError("idempotency binding scope and run id are required")
        for name, value in (
            ("semantic fingerprint", self.semantic_fingerprint),
            ("dataset fingerprint", self.dataset_fingerprint),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if self.submission_attempts < 0:
            raise ValueError("submission attempts must be non-negative")

    def matches(self, semantics: FullCollectionSemantics) -> bool:
        return (
            self.operation_scope == semantics.operation_scope
            and self.semantic_fingerprint == semantics.semantic_fingerprint
            and self.resolved_as_of == semantics.resolved_as_of
            and self.operation_version == semantics.operation_version
            and self.dataset_fingerprint == semantics.dataset_fingerprint
        )


class IdempotencyClaimDisposition(str, Enum):
    CREATED = "created"
    REPLAY = "replay"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    disposition: IdempotencyClaimDisposition
    binding: IdempotencyBinding


def _sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "CANONICAL_FULL_COLLECTION_DATASETS",
    "CollectionFailureCategory",
    "FULL_COLLECTION_OPERATION_SCOPE",
    "FULL_COLLECTION_OPERATION_VERSION",
    "FullCollectionSemantics",
    "IdempotencyBinding",
    "IdempotencyClaim",
    "IdempotencyClaimDisposition",
    "IdempotencyKey",
    "StructuredTaskFailure",
    "SubmissionState",
    "redact_failure_message",
]
