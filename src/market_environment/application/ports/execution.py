"""Bounded task execution port."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar, runtime_checkable


ResultT = TypeVar("ResultT")


@runtime_checkable
class SubmittedTask(Protocol[ResultT]):
    def result(self, timeout: float | None = None) -> ResultT: ...


@runtime_checkable
class TaskExecutor(Protocol):
    def submit(
        self,
        function: Callable[..., ResultT],
        *args: Any,
        **kwargs: Any,
    ) -> SubmittedTask[ResultT]: ...

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None: ...


__all__ = ["SubmittedTask", "TaskExecutor"]
