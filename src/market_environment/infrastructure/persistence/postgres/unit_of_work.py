"""Shared PostgreSQL transaction boundary for split repositories."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .connection import PostgresConnectionFactory


_REPOSITORY_NAMES = (
    "snapshots",
    "collection_runs",
    "collection_tasks",
    "core_index_results",
    "leases",
    "trading_sessions",
    "aggregates",
    "provider_capabilities",
    "limit_details",
    "timezone_preferences",
)


class MarketEnvironmentUnitOfWork:
    """Create all repositories over one explicit SQLAlchemy transaction."""

    def __init__(
        self,
        connections: PostgresConnectionFactory,
        repository_factory: Callable[[Any], Any],
        *,
        isolation_level: str = "READ COMMITTED",
    ) -> None:
        self._connections = connections
        self._repository_factory = repository_factory
        self._isolation_level = isolation_level
        self._connection = None
        self._transaction = None
        self._finished = False
        for name in _REPOSITORY_NAMES:
            setattr(self, name, None)

    def __enter__(self) -> "MarketEnvironmentUnitOfWork":
        if self._connection is not None:
            raise RuntimeError("unit of work is already active")
        connection = self._connections.connect()
        try:
            connection = connection.execution_options(
                isolation_level=self._isolation_level
            )
            transaction = connection.begin()
            repositories = self._repository_factory(connection)
            for name in _REPOSITORY_NAMES:
                setattr(self, name, getattr(repositories, name))
        except BaseException:
            rollback = locals().get("transaction")
            if rollback is not None:
                rollback.rollback()
            connection.close()
            raise
        self._connection = connection
        self._transaction = transaction
        self._finished = False
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if not self._finished:
                self.rollback()
        finally:
            connection = self._connection
            self._connection = None
            self._transaction = None
            if connection is not None:
                connection.close()

    def commit(self) -> None:
        transaction = self._active_transaction()
        transaction.commit()
        self._finished = True

    def rollback(self) -> None:
        transaction = self._active_transaction()
        transaction.rollback()
        self._finished = True

    def _active_transaction(self):
        if self._transaction is None or self._finished:
            raise RuntimeError("unit of work has no active transaction")
        return self._transaction


__all__ = ["MarketEnvironmentUnitOfWork"]
