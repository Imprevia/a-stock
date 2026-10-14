"""Storage-envelope codec for safe, bounded THS diagnostics.

The domain owns the provider-neutral diagnostic values.  This application
boundary owns the compatibility protocol used to persist them in the existing
``collection_tasks.warning`` text column.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, cast

from ..domain.ths_diagnostics import (
    THS_DIAGNOSTIC_BLOCKED_BY_LIMIT,
    THS_DIAGNOSTIC_SAMPLE_LIMIT,
    THS_REASON_CODES,
    ThsBlockedBy,
    ThsDiagnostic,
    ThsReasonCode,
)


THS_DIAGNOSTIC_PREFIX = "THS_DIAGNOSTIC_V1 "
THS_DIAGNOSTIC_MAX_BYTES = 4096


def _count(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _exact_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("exactDate must use YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("exactDate must use YYYY-MM-DD")
    return parsed


def encode_ths_diagnostic(diagnostic: ThsDiagnostic) -> str:
    """Encode one canonical warning envelope within the persisted size bound."""

    if not isinstance(diagnostic, ThsDiagnostic):
        raise TypeError("diagnostic must be a ThsDiagnostic")
    body = json.dumps(
        diagnostic.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded = THS_DIAGNOSTIC_PREFIX + body
    if len(encoded.encode("utf-8")) > THS_DIAGNOSTIC_MAX_BYTES:
        raise ValueError("THS diagnostic exceeds the encoded size limit")
    return encoded


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate diagnostic field: {key}")
        result[key] = value
    return result


def _blocked_by_from_mapping(value: object) -> tuple[ThsBlockedBy, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > THS_DIAGNOSTIC_BLOCKED_BY_LIMIT:
        raise ValueError("blockedBy must be a bounded array")
    values: list[ThsBlockedBy] = []
    allowed = {"dataset", "status", "reasonCode", "exactDate", "catalogRevisionId"}
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) - allowed:
            raise ValueError("blockedBy contains unsupported fields")
        reason = raw.get("reasonCode")
        if reason is not None and reason not in THS_REASON_CODES:
            raise ValueError("blockedBy.reasonCode is unsupported")
        values.append(
            ThsBlockedBy(
                dataset=cast(str, raw.get("dataset")),
                status=cast(str, raw.get("status")),
                reason_code=cast(ThsReasonCode | None, reason),
                exact_date=(
                    _exact_date(raw["exactDate"])
                    if raw.get("exactDate") is not None
                    else None
                ),
                catalog_revision_id=cast(str | None, raw.get("catalogRevisionId")),
            )
        )
    return tuple(values)


def _diagnostic_from_mapping(raw: Mapping[str, Any]) -> ThsDiagnostic:
    allowed = {
        "reasonCode",
        "message",
        "failureStage",
        "exactDate",
        "retryable",
        "capabilityRevision",
        "catalogRevisionId",
        "expectedCount",
        "observedCount",
        "usableCount",
        "rankableCount",
        "barCount",
        "missingLiveCount",
        "missingLiveCodes",
        "missingRankingCount",
        "missingRankingCodes",
        "existingChecksum",
        "observedChecksum",
        "blockedBy",
    }
    if set(raw) - allowed:
        raise ValueError("diagnostic contains unsupported fields")
    reason = raw.get("reasonCode")
    if reason not in THS_REASON_CODES:
        raise ValueError("reasonCode is unsupported")
    retryable = raw.get("retryable")
    if not isinstance(retryable, bool):
        raise ValueError("retryable must be boolean")
    live_codes = raw.get("missingLiveCodes", [])
    ranking_codes = raw.get("missingRankingCodes", [])
    if not isinstance(live_codes, list) or not isinstance(ranking_codes, list):
        raise ValueError("missing code samples must be arrays")
    if (
        len(live_codes) > THS_DIAGNOSTIC_SAMPLE_LIMIT
        or len(ranking_codes) > THS_DIAGNOSTIC_SAMPLE_LIMIT
    ):
        raise ValueError("missing code sample exceeds the bound")
    return ThsDiagnostic(
        reason_code=cast(ThsReasonCode, reason),
        message=cast(str, raw.get("message")),
        failure_stage=cast(str, raw.get("failureStage")),
        exact_date=_exact_date(raw.get("exactDate")),
        retryable=retryable,
        capability_revision=cast(str | None, raw.get("capabilityRevision")),
        catalog_revision_id=cast(str | None, raw.get("catalogRevisionId")),
        expected_count=_count(raw.get("expectedCount"), field_name="expectedCount"),
        observed_count=_count(raw.get("observedCount"), field_name="observedCount"),
        usable_count=_count(raw.get("usableCount"), field_name="usableCount"),
        rankable_count=_count(raw.get("rankableCount"), field_name="rankableCount"),
        bar_count=_count(raw.get("barCount"), field_name="barCount"),
        missing_live_count=_count(
            raw.get("missingLiveCount"), field_name="missingLiveCount"
        ),
        missing_live_codes=tuple(live_codes),
        missing_ranking_count=_count(
            raw.get("missingRankingCount"), field_name="missingRankingCount"
        ),
        missing_ranking_codes=tuple(ranking_codes),
        existing_checksum=cast(str | None, raw.get("existingChecksum")),
        observed_checksum=cast(str | None, raw.get("observedChecksum")),
        blocked_by=_blocked_by_from_mapping(raw.get("blockedBy")),
    )


def parse_ths_diagnostic(warning: str | None) -> ThsDiagnostic | None:
    """Parse a valid V1 envelope or return ``None`` for legacy/malformed text."""

    if not isinstance(warning, str) or not warning.startswith(THS_DIAGNOSTIC_PREFIX):
        return None
    if len(warning.encode("utf-8")) > THS_DIAGNOSTIC_MAX_BYTES:
        return None
    try:
        raw = json.loads(
            warning[len(THS_DIAGNOSTIC_PREFIX) :],
            object_pairs_hook=_object_without_duplicates,
        )
        if not isinstance(raw, Mapping):
            return None
        return _diagnostic_from_mapping(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def ths_warning_response(
    warning: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Return the legacy message field and optional typed diagnostics for HTTP."""

    diagnostic = parse_ths_diagnostic(warning)
    if diagnostic is None:
        return warning, None
    return diagnostic.message, diagnostic.as_dict()


__all__ = [
    "THS_DIAGNOSTIC_BLOCKED_BY_LIMIT",
    "THS_DIAGNOSTIC_MAX_BYTES",
    "THS_DIAGNOSTIC_PREFIX",
    "THS_DIAGNOSTIC_SAMPLE_LIMIT",
    "THS_REASON_CODES",
    "ThsBlockedBy",
    "ThsDiagnostic",
    "ThsReasonCode",
    "encode_ths_diagnostic",
    "parse_ths_diagnostic",
    "ths_warning_response",
]
