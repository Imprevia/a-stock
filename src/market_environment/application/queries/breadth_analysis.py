"""Explicit repository reads for breadth history analysis."""

from __future__ import annotations

import copy
import logging
from datetime import date
from typing import Any

from ...domain.analysis import previous_trading_date


logger = logging.getLogger(__name__)


class BreadthHistoryReader:
    def __init__(self, repository: Any, *, integrity_error: type[Exception]) -> None:
        self.repository = repository
        self.integrity_error = integrity_error

    def list_payloads(self, as_of: date, *, exclude_today: bool, limit: int) -> list[dict[str, Any]]:
        if self.repository is None:
            return []
        try:
            dates = self.repository.list_snapshot_dates("breadth", through=as_of)
        except self.integrity_error as exc:
            logger.warning("breadth history lookup rejected", extra={"event": "breadth_history_invalid", "as_of": as_of.isoformat(), "error": str(exc)})
            return []
        ordered: list[dict[str, Any]] = []
        for snapshot_date in dates:
            if exclude_today and snapshot_date == as_of:
                continue
            try:
                record = self.repository.get("breadth", snapshot_date)
            except self.integrity_error as exc:
                logger.warning("breadth history snapshot rejected", extra={"event": "breadth_history_snapshot_invalid", "as_of": snapshot_date.isoformat(), "error": str(exc)})
                continue
            if record is None:
                continue
            payload = copy.deepcopy(record.payload)
            payload.setdefault("asOf", snapshot_date.isoformat())
            ordered.append(payload)
            if len(ordered) >= limit:
                break
        ordered.sort(key=lambda item: item.get("asOf", ""))
        return ordered

    def previous_for_core(self, core: dict[str, Any]) -> dict[str, Any] | None:
        if self.repository is None:
            return None
        previous_date = previous_trading_date(core)
        if previous_date is None:
            return None
        try:
            record = self.repository.get("breadth", previous_date)
        except self.integrity_error as exc:
            logger.warning("previous breadth snapshot rejected", extra={"event": "previous_breadth_snapshot_invalid", "as_of": previous_date.isoformat(), "error": str(exc)})
            return None
        if record is None:
            return None
        payload = copy.deepcopy(record.payload)
        payload.setdefault("quality", {})["asOf"] = previous_date.isoformat()
        return payload


__all__ = ["BreadthHistoryReader"]
