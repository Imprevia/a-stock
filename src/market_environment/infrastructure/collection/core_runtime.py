"""Runtime bridges between normalized core acquisition and typed persistence."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ...application.ports import (
    CoreCommitRequest,
    CoreIndexCommitEvidence,
    CoreTradingSessionEvidence,
)
from ...domain.models import CollectionOutcome, CollectionTaskState, DatasetDate
from ..legacy.snapshot_store import CollectionTaskRecord, LeaseToken


@dataclass(frozen=True, slots=True)
class CoreRetainedIndexReader:
    """Read only exact-date core index payloads eligible for retention."""

    repository: Any

    def __call__(self, identity: DatasetDate) -> Mapping[str, Mapping[str, Any]]:
        if identity.dataset != "core":
            raise ValueError("core retained-index reader requires the core dataset")
        snapshot = self.repository.get(identity.dataset, identity.as_of)
        if snapshot is None:
            return {}
        if snapshot.as_of != identity.as_of:
            raise ValueError("core retained-index snapshot date mismatch")
        indices = snapshot.payload.get("indices")
        if not isinstance(indices, Sequence) or isinstance(indices, (str, bytes)):
            return {}
        retained: dict[str, Mapping[str, Any]] = {}
        for value in indices:
            if not isinstance(value, Mapping):
                continue
            code = str(value.get("code") or "").strip()
            if not code:
                continue
            retained[code] = copy.deepcopy(dict(value))
        return retained


@dataclass(frozen=True, slots=True)
class CoreCommitRequestFactory:
    """Map one normalized core outcome into its atomic typed write set."""

    now: Callable[[], datetime]

    def __call__(
        self,
        task: CollectionTaskRecord,
        outcome: CollectionOutcome,
        lease: LeaseToken,
        _preparation: Any = None,
    ) -> CoreCommitRequest:
        identity = DatasetDate(task.dataset, task.as_of)
        if identity.dataset != "core" or outcome.identity != identity:
            raise ValueError("core commit factory received a mismatched outcome")
        candidate = outcome.candidate
        if candidate is None or candidate.quality is None:
            raise ValueError("core commit factory requires normalized quality evidence")
        extra = candidate.quality.extra
        raw_results = extra.get("indexResults")
        if not isinstance(raw_results, Sequence) or isinstance(
            raw_results,
            (str, bytes),
        ):
            raise ValueError("core quality evidence is missing indexResults")

        payloads = self._payloads_by_code(candidate.payload.get("indices"))
        index_results = tuple(
            self._index_result(value, payloads)
            for value in raw_results
            if isinstance(value, Mapping)
        )
        if len(index_results) != len(raw_results):
            raise ValueError("core indexResults must contain only objects")

        raw_session = extra.get("tradingSession")
        session = (
            self._session(raw_session)
            if isinstance(raw_session, Mapping)
            else None
        )
        previous_session = self._previous_session(session, candidate.payload)
        session_warning = _optional_text(extra.get("sessionWarning"))
        completed_at = self.now()
        if completed_at.tzinfo is None:
            raise ValueError("core commit clock must be timezone-aware")
        duration_ms = _elapsed_ms(task.started_at, completed_at)
        timings = dict(task.timings or {})
        timings.update(candidate.timings.phases_ms)
        timings["providerCollectionMs"] = (
            candidate.timings.total_ms
            if candidate.timings.total_ms is not None
            else duration_ms
        )
        return CoreCommitRequest(
            identity=identity,
            outcome=outcome,
            lease=lease,
            task_id=task.task_id,
            index_results=index_results,
            session=session,
            previous_session=previous_session,
            session_warning=session_warning,
            completed_at=completed_at,
            task_timings=timings,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _payloads_by_code(raw: Any) -> dict[str, Mapping[str, Any]]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError("core candidate is missing indices")
        values: dict[str, Mapping[str, Any]] = {}
        for value in raw:
            if not isinstance(value, Mapping):
                raise ValueError("core candidate indices must contain only objects")
            code = str(value.get("code") or "").strip()
            if not code or code in values:
                raise ValueError("core candidate indices require unique stable codes")
            values[code] = value
        return values

    @staticmethod
    def _index_result(
        raw: Mapping[str, Any],
        payloads: Mapping[str, Mapping[str, Any]],
    ) -> CoreIndexCommitEvidence:
        code = str(raw.get("code") or "").strip()
        try:
            state = CollectionTaskState(str(raw.get("status") or ""))
        except ValueError as exc:
            raise ValueError(f"invalid core index state for {code or 'unknown'}") from exc
        payload = None if state is CollectionTaskState.FAILED_MISSING else payloads.get(code)
        return CoreIndexCommitEvidence(
            code=code,
            name=str(raw.get("name") or "").strip(),
            state=state,
            source=str(raw.get("source") or "none").strip(),
            observations=int(raw.get("observations") or 0),
            payload=copy.deepcopy(dict(payload)) if payload is not None else None,
            warning=_optional_text(raw.get("warning")),
            duration_ms=_optional_float(raw.get("durationMs")),
            retained=bool(raw.get("retained", False)),
        )

    @staticmethod
    def _session(raw: Mapping[str, Any]) -> CoreTradingSessionEvidence:
        is_session = raw.get("isSession")
        if not isinstance(is_session, bool):
            raise ValueError("core tradingSession isSession must be boolean")
        warnings = raw.get("warnings") or ()
        if not isinstance(warnings, Sequence) or isinstance(warnings, (str, bytes)):
            raise ValueError("core tradingSession warnings must be a sequence")
        return CoreTradingSessionEvidence(
            as_of=_date(raw.get("asOf"), "asOf"),
            previous_as_of=_optional_date(raw.get("previousAsOf"), "previousAsOf"),
            is_session=is_session,
            source=str(raw.get("source") or "").strip(),
            actual_as_of=_date(raw.get("actualAsOf"), "actualAsOf"),
            fetched_at=_datetime(raw.get("fetchedAt"), "fetchedAt"),
            warnings=tuple(str(value) for value in warnings),
        )

    @staticmethod
    def _previous_session(
        session: CoreTradingSessionEvidence | None,
        payload: Mapping[str, Any],
    ) -> CoreTradingSessionEvidence | None:
        if session is None or session.previous_as_of is None:
            return None
        indices = payload.get("indices")
        if not isinstance(indices, Sequence) or isinstance(indices, (str, bytes)):
            raise ValueError("core candidate is missing histories for previous session")
        prior_dates: set[date] = set()
        for value in indices:
            if not isinstance(value, Mapping):
                raise ValueError("core candidate contains malformed index history")
            history = value.get("history")
            if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
                raise ValueError("core candidate contains malformed index history")
            dates: list[date] = []
            for point in history:
                if not isinstance(point, Mapping) or point.get("date") in (None, ""):
                    continue
                dates.append(_date(point["date"], "history date"))
            if (
                len(dates) < 2
                or dates[-1] != session.as_of
                or dates[-2] != session.previous_as_of
            ):
                raise ValueError("core histories do not match trading-session evidence")
            if len(dates) >= 3:
                prior_dates.add(dates[-3])
        prior_as_of = next(iter(prior_dates)) if len(prior_dates) == 1 else None
        return CoreTradingSessionEvidence(
            as_of=session.previous_as_of,
            previous_as_of=prior_as_of,
            is_session=True,
            source=session.source,
            actual_as_of=session.previous_as_of,
            fetched_at=session.fetched_at,
            warnings=session.warnings,
        )


def _date(value: Any, field_name: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"core tradingSession {field_name} must be an ISO date") from exc


def _optional_date(value: Any, field_name: str) -> date | None:
    return None if value in (None, "") else _date(value, field_name)


def _datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError(
                f"core tradingSession {field_name} must be an ISO datetime"
            ) from exc
    if parsed.tzinfo is None:
        raise ValueError(f"core tradingSession {field_name} must be timezone-aware")
    return parsed


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if parsed < 0:
        raise ValueError("core duration must be non-negative")
    return parsed


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _elapsed_ms(started_at: datetime | None, completed_at: datetime) -> float:
    if started_at is None:
        return 0.0
    if started_at.tzinfo is None:
        raise ValueError("core collection task start time must be timezone-aware")
    return round(max(0.0, (completed_at - started_at).total_seconds() * 1000), 3)


__all__ = ["CoreCommitRequestFactory", "CoreRetainedIndexReader"]
