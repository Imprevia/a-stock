"""Application-facing protocols implemented by infrastructure adapters."""

from .collectors import DatasetCollector
from .collection_inputs import (
    CollectionRefreshRequest,
    LimitHistoryPreparationRequest,
    LimitHistoryPreparer,
)
from .committers import (
    DatasetCommitEvidence,
    DatasetCommitFence,
    DatasetCommitRequest,
    DatasetCommitter,
)
from .core_committers import (
    CoreCommitEvidence,
    CoreCommitRequest,
    CoreIndexCommitEvidence,
    CoreTradingSessionEvidence,
)
from .limits_committers import (
    LimitsCommitEvidence,
    LimitsCommitRequest,
    LimitsManifestEvidence,
)
from .acquisition import (
    AcquisitionPlan,
    AcquisitionPlanStep,
    SourceAdapter,
    SourceCapability,
    SourceRequest,
    SourceResult,
)
from .execution import SubmittedTask, TaskExecutor
from .projectors import DatasetDetailProjector
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
    "AcquisitionPlan",
    "AcquisitionPlanStep",
    "CollectionRunRepository",
    "CollectionRefreshRequest",
    "CollectionStatusReader",
    "CollectionTaskRepository",
    "CoreIndexResultRepository",
    "CollectionCommandPort",
    "CollectionQueryPort",
    "CoreCommitEvidence",
    "CoreCommitRequest",
    "CoreIndexCommitEvidence",
    "DatasetCollector",
    "DatasetCommitEvidence",
    "DatasetCommitFence",
    "DatasetCommitRequest",
    "DatasetCommitter",
    "DatasetDetailProjector",
    "CoreTradingSessionEvidence",
    "LeaseRepository",
    "LimitDetailRepository",
    "LimitsCommitEvidence",
    "LimitsCommitRequest",
    "LimitsManifestEvidence",
    "LimitHistoryPreparationRequest",
    "LimitHistoryPreparer",
    "MarketEnvironmentUnitOfWork",
    "SourceAdapter",
    "SourceCapability",
    "SourceRequest",
    "SourceResult",
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
