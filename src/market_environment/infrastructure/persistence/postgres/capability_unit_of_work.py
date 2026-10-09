"""Narrow PostgreSQL transaction for provider capability promotion."""

from __future__ import annotations

from .connection import PostgresConnectionFactory
from .repositories import PostgresProviderCapabilityRepository


class ProviderCapabilityPromotionUnitOfWork:
    """Expose only the repository that capability promotion may mutate."""

    def __init__(self, connections: PostgresConnectionFactory) -> None:
        self._connections = connections
        self._connection = None
        self._transaction = None
        self._finished = False
        self.provider_capabilities = None

    def __enter__(self) -> "ProviderCapabilityPromotionUnitOfWork":
        if self._connection is not None:
            raise RuntimeError("unit of work is already active")
        connection = self._connections.connect()
        try:
            transaction = connection.begin()
            repository = PostgresProviderCapabilityRepository(connection)
        except BaseException:
            rollback = locals().get("transaction")
            if rollback is not None:
                rollback.rollback()
            connection.close()
            raise
        self._connection = connection
        self._transaction = transaction
        self._finished = False
        self.provider_capabilities = repository
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if not self._finished:
                self.rollback()
        finally:
            connection = self._connection
            self._connection = None
            self._transaction = None
            self.provider_capabilities = None
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


__all__ = ["ProviderCapabilityPromotionUnitOfWork"]
