"""Explicit compatibility adapter for limits history preparation."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from ...application.ports import LimitHistoryPreparationRequest
from ...snapshot_store import TradingSessionRecord


@dataclass(frozen=True, slots=True)
class CollectorLimitHistoryPreparer:
    collector: Any

    def prepare(
        self,
        request: LimitHistoryPreparationRequest,
    ) -> tuple[date, ...]:
        return tuple(
            self.collector.prepare_history_sessions(request.as_of, request.count)
        )


@dataclass(frozen=True, slots=True)
class ProviderLimitHistoryPreparer:
    """Explicit maintenance path for dated Fuyao calendar preparation."""

    provider: Any
    store: Any
    now: Callable[[], datetime]

    def prepare(
        self,
        request: LimitHistoryPreparationRequest,
    ) -> tuple[date, ...]:
        fetch_calendar = getattr(self.provider, "fetch_trading_days", None)
        if not callable(fetch_calendar):
            raise ValueError("limits provider does not expose a trading calendar")
        calendar = tuple(fetch_calendar())
        if request.as_of not in calendar:
            raise ValueError(
                f"{request.as_of.isoformat()} is not a confirmed trading session"
            )
        target_index = calendar.index(request.as_of)
        if target_index + 1 < request.count:
            raise ValueError(
                f"trading calendar has only {target_index + 1} sessions through "
                f"{request.as_of.isoformat()}"
            )
        selected = calendar[target_index - request.count + 1 : target_index + 1]
        fetched_at = self.now()
        for session in selected:
            calendar_index = calendar.index(session)
            previous = calendar[calendar_index - 1] if calendar_index else None
            self.store.put_trading_session(
                TradingSessionRecord(
                    as_of=session,
                    previous_as_of=previous,
                    is_session=True,
                    source="fuyao-calendar",
                    actual_as_of=session,
                    fetched_at=fetched_at,
                )
            )
        return selected


__all__ = ["CollectorLimitHistoryPreparer", "ProviderLimitHistoryPreparer"]
