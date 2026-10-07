"""Process-wide request pacing for Fuyao clients.

The limits and market-data clients are separate for contract reasons, but they
must still share one outbound request gate in production.  Test callers can
inject their own gate to keep deterministic clocks isolated.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class FuyaoRequestGate:
    """Serialize request starts and enforce a minimum interval."""

    def __init__(
        self,
        *,
        min_interval_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._last_started_at: float | None = None

    def wait(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        with self._lock:
            now = self._monotonic()
            if self._last_started_at is not None:
                delay = self.min_interval_seconds - (now - self._last_started_at)
                if delay > 0:
                    self._sleep(delay)
                    now = self._monotonic()
            self._last_started_at = now


GLOBAL_FUYAO_REQUEST_GATE = FuyaoRequestGate()


__all__ = ["FuyaoRequestGate", "GLOBAL_FUYAO_REQUEST_GATE"]
