"""Bounded in-process implementation of the application task executor port."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from typing import Any, TypeVar


ResultT = TypeVar("ResultT")


class BoundedTaskExecutor:
    """Limit running and queued work without blocking an HTTP request thread."""

    def __init__(
        self,
        *,
        max_workers: int,
        max_pending_tasks: int | None = None,
        thread_name_prefix: str = "market-task",
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        pending = max_workers if max_pending_tasks is None else max_pending_tasks
        if pending < 0:
            raise ValueError("max_pending_tasks must be non-negative")
        self._capacity = BoundedSemaphore(max_workers + pending)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._lock = Lock()
        self._closed = False

    def submit(
        self,
        function: Callable[..., ResultT],
        *args: Any,
        **kwargs: Any,
    ) -> Future[ResultT]:
        with self._lock:
            if self._closed:
                raise RuntimeError("task executor is shut down")
            acquired = self._capacity.acquire(blocking=False)
            if not acquired:
                raise RuntimeError("task executor capacity is exhausted")
            try:
                future = self._executor.submit(function, *args, **kwargs)
            except BaseException:
                self._capacity.release()
                raise
            future.add_done_callback(lambda _future: self._capacity.release())
            return future

    def shutdown(
        self,
        *,
        wait: bool = True,
        cancel_futures: bool = False,
    ) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)


__all__ = ["BoundedTaskExecutor"]
