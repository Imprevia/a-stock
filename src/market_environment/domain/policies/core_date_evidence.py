"""Pure exact-date validation for core index evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


class CoreDateEvidenceError(ValueError):
    """Raised when core evidence cannot prove the requested exact date."""

    def __init__(
        self,
        message: str,
        *,
        requested_as_of: date,
        actual_as_of: date | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.requested_as_of = requested_as_of
        self.actual_as_of = actual_as_of
        self.field = field


@dataclass(frozen=True, slots=True)
class CoreDateEvidence:
    requested_as_of: date
    actual_as_of: date
    index_dates: tuple[tuple[str, date], ...]


def _date_value(value: Any, *, field: str, requested_as_of: date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if value in (None, ""):
        raise CoreDateEvidenceError(
            f"core date evidence is missing: {field}",
            requested_as_of=requested_as_of,
            field=field,
        )
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise CoreDateEvidenceError(
            f"core date evidence is malformed: {field}",
            requested_as_of=requested_as_of,
            field=field,
        ) from exc


def core_index_history_tail(
    index: Mapping[str, Any],
    requested_as_of: date,
) -> date:
    """Return the latest history date, rejecting missing or malformed evidence."""

    code = str(index.get("code") or "unknown").strip()
    history = index.get("history")
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)) or not history:
        raise CoreDateEvidenceError(
            f"core index history is missing: {code}",
            requested_as_of=requested_as_of,
            field=f"indices[{code}].history",
        )
    tail = history[-1]
    if not isinstance(tail, Mapping):
        raise CoreDateEvidenceError(
            f"core index history tail is malformed: {code}",
            requested_as_of=requested_as_of,
            field=f"indices[{code}].history[-1]",
        )
    return _date_value(
        tail.get("date"),
        field=f"indices[{code}].history[-1].date",
        requested_as_of=requested_as_of,
    )


def validate_core_index_date(
    index: Mapping[str, Any],
    requested_as_of: date,
) -> date:
    """Require one normalized index history to end on the requested date."""

    actual = core_index_history_tail(index, requested_as_of)
    if actual != requested_as_of:
        raise CoreDateEvidenceError(
            "core index history date does not match requested date",
            requested_as_of=requested_as_of,
            actual_as_of=actual,
            field="history-tail",
        )
    return actual


def validate_core_payload_dates(
    payload: Mapping[str, Any],
    requested_as_of: date,
    *,
    actual_as_of: date | None = None,
    quality_as_of: date | str | None = None,
    effective_as_of: date | str | None = None,
) -> CoreDateEvidence:
    """Require every public and per-index core date to match one identity."""

    expected = requested_as_of
    checks: tuple[tuple[str, Any], ...] = (
        ("payload.asOf", payload.get("asOf")),
        ("candidate.actual_as_of", actual_as_of),
        ("quality.asOf", quality_as_of),
        ("quality.effectiveAsOf", effective_as_of),
    )
    for field, raw in checks:
        if raw is None and field != "payload.asOf":
            continue
        actual = _date_value(raw, field=field, requested_as_of=expected)
        if actual != expected:
            raise CoreDateEvidenceError(
                f"core exact-date mismatch: {field}",
                requested_as_of=expected,
                actual_as_of=actual,
                field=field,
            )

    quality = payload.get("quality")
    if isinstance(quality, Mapping):
        for field, raw in (
            ("payload.quality.asOf", quality.get("asOf")),
            ("payload.quality.effectiveAsOf", quality.get("effectiveAsOf")),
        ):
            if raw is None:
                continue
            actual = _date_value(raw, field=field, requested_as_of=expected)
            if actual != expected:
                raise CoreDateEvidenceError(
                    f"core exact-date mismatch: {field}",
                    requested_as_of=expected,
                    actual_as_of=actual,
                    field=field,
                )

    indices = payload.get("indices")
    if not isinstance(indices, Sequence) or isinstance(indices, (str, bytes)) or not indices:
        raise CoreDateEvidenceError(
            "core indices date evidence is missing",
            requested_as_of=expected,
            field="indices",
        )
    index_dates: list[tuple[str, date]] = []
    for index in indices:
        if not isinstance(index, Mapping):
            raise CoreDateEvidenceError(
                "core index evidence is malformed",
                requested_as_of=expected,
                field="indices",
            )
        actual = validate_core_index_date(index, expected)
        index_dates.append((str(index.get("code") or "unknown"), actual))
    return CoreDateEvidence(expected, expected, tuple(index_dates))


def validate_materialized_aggregate_dates(
    payload: Mapping[str, Any],
    requested_as_of: date,
) -> None:
    """Validate public aggregate, core tails, and component quality dates."""

    actual = _date_value(
        payload.get("asOf"),
        field="aggregate.asOf",
        requested_as_of=requested_as_of,
    )
    if actual != requested_as_of:
        raise CoreDateEvidenceError(
            "materialized aggregate exact-date mismatch: aggregate.asOf",
            requested_as_of=requested_as_of,
            actual_as_of=actual,
            field="aggregate.asOf",
        )
    indices = payload.get("indices")
    if isinstance(indices, Sequence) and not isinstance(indices, (str, bytes)) and indices:
        validate_core_payload_dates(payload, requested_as_of)

    chapter = payload.get("chapter01")
    if not isinstance(chapter, Mapping):
        return
    for component, value in chapter.items():
        if not isinstance(value, Mapping):
            continue
        quality = value.get("quality")
        if not isinstance(quality, Mapping):
            continue
        for key in ("asOf", "actualDate"):
            raw = quality.get(key)
            if raw is None:
                continue
            component_date = _date_value(
                raw,
                field=f"chapter01.{component}.quality.{key}",
                requested_as_of=requested_as_of,
            )
            if component_date != requested_as_of:
                raise CoreDateEvidenceError(
                    "materialized aggregate component date mismatch",
                    requested_as_of=requested_as_of,
                    actual_as_of=component_date,
                    field=f"chapter01.{component}.quality.{key}",
                )


__all__ = [
    "CoreDateEvidence",
    "CoreDateEvidenceError",
    "core_index_history_tail",
    "validate_core_index_date",
    "validate_core_payload_dates",
    "validate_materialized_aggregate_dates",
]
