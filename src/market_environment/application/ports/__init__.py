"""Application-facing protocols implemented by infrastructure adapters."""

from .collectors import DatasetCollector
from .execution import SubmittedTask, TaskExecutor
from .repositories import (
    CollectionRunRepository,
    CollectionStatusReader,
    CollectionTaskRepository,
    CoreIndexResultRepository,
    LeaseRepository,
    LimitDetailRepository,
    MaterializedAggregateReader,
    MaterializedAggregateRepository,
    ProviderCapabilityRepository,
    SnapshotReader,
    SnapshotRepository,
    TimezonePreferenceReader,
    TimezonePreferenceRepository,
    TimezonePreferenceWriter,
    TradingSessionReader,
    TradingSessionRepository,
)
from .services import (
    AggregateCommandPort,
    CollectionCommandPort,
    CollectionQueryPort,
    MarketEnvironmentQueryPort,
)
from .unit_of_work import MarketEnvironmentUnitOfWork

__all__ = [
    "AggregateCommandPort",
    "CollectionRunRepository",
    "CollectionStatusReader",
    "CollectionTaskRepository",
    "CoreIndexResultRepository",
    "CollectionCommandPort",
    "CollectionQueryPort",
    "DatasetCollector",
    "LeaseRepository",
    "LimitDetailRepository",
    "MarketEnvironmentUnitOfWork",
    "MaterializedAggregateReader",
    "MaterializedAggregateRepository",
    "MarketEnvironmentQueryPort",
    "ProviderCapabilityRepository",
    "SnapshotReader",
    "SnapshotRepository",
    "SubmittedTask",
    "TaskExecutor",
    "TimezonePreferenceReader",
    "TimezonePreferenceRepository",
    "TimezonePreferenceWriter",
    "TradingSessionReader",
    "TradingSessionRepository",
]
