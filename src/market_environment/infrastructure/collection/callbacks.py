"""Compatibility normalization for aggregate rebuild callbacks."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import date, datetime
from typing import Any


RebuildCallback = Callable[[date], Any]
NormalizedRebuildCallback = Callable[..., Any]


def normalize_rebuild_callback(
    callback: Callable[..., Any] | None,
) -> NormalizedRebuildCallback | None:
    if callback is None:
        return None
    parameters = inspect.signature(callback).parameters.values()
    supports_context = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters
    ) or {"lease", "now"} <= {parameter.name for parameter in parameters}
    if supports_context:
        return callback

    def legacy(as_of: date, *, lease: object, now: datetime) -> Any:
        del lease, now
        return callback(as_of)

    return legacy


__all__ = ["normalize_rebuild_callback"]
