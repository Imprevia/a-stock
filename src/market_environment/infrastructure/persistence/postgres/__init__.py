"""PostgreSQL runtime persistence adapters with side-effect-free exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "DatabaseSchemaCompatibilityError": ".connection",
    "MINIMUM_SCHEMA_VERSION": ".connection",
    "PostgresConnectionFactory": ".connection",
    "REQUIRED_RUNTIME_TABLES": ".connection",
    "RuntimeSchemaReport": ".connection",
    "MarketEnvironmentUnitOfWork": ".unit_of_work",
    "PostgresCollectionRunRepository": ".collection_repositories",
    "PostgresCollectionTaskRepository": ".collection_repositories",
    "PostgresCoreIndexResultRepository": ".collection_repositories",
    "PostgresLeaseRepository": ".lease_repository",
    "PostgresMaterializedAggregateRepository": ".aggregate_repository",
    "PostgresLimitDetailRepository": ".limit_repository",
    "PostgresProviderCapabilityRepository": ".repositories",
    "PostgresSnapshotRepository": ".repositories",
    "PostgresTradingSessionRepository": ".repositories",
    "PostgresTimezonePreferenceRepository": ".timezone_repository",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name, __name__), name)


__all__ = list(_EXPORTS)
