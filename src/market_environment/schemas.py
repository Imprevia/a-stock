"""API response schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CollectionDataset = Literal["core", "breadth", "limits", "sectors", "activeDirection"]
CollectionRunState = Literal["queued", "collecting", "success", "partial", "failed"]
CollectionTaskState = Literal[
    "queued",
    "collecting",
    "success",
    "partial",
    "failed-retained",
    "failed-missing",
    "busy",
]
SynchronizationAssessmentStatus = Literal["confirmed", "unconfirmed", "contradicted", "insufficient"]
SynchronizationDimensionStatus = Literal["confirming", "neutral", "contradicting", "insufficient"]
SynchronizationConclusionCode = Literal[
    "broad-strength-confirmed",
    "index-strength-breadth-divergence",
    "synchronized-rally-unconfirmed",
    "synchronized-rally-insufficient",
    "weight-shelter-confirmed",
    "weight-lead-contradicted",
    "weight-lead-unconfirmed",
    "weight-lead-insufficient",
    "growth-lead-confirmed",
    "growth-lead-contradicted",
    "growth-lead-unconfirmed",
    "growth-lead-insufficient",
    "systemic-decline-confirmed",
    "broad-weakness-contradicted",
    "broad-weakness-unconfirmed",
    "broad-weakness-insufficient",
    "undetermined-divergence",
    "undetermined-insufficient",
]


class MovingAverages(BaseModel):
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None


class DataQuality(BaseModel):
    source: str
    isStale: bool
    warning: str | None


class DataGap(BaseModel):
    field: str
    reason: Literal["insufficient-history", "missing-today", "provider-failed", "not-computable"]


class SyncPattern(BaseModel):
    code: str
    label: str
    score: int
    evidence: list[str] = Field(default_factory=list)


class SynchronizationBreadthDimension(BaseModel):
    status: SynchronizationDimensionStatus
    currentAsOf: str | None = None
    previousAsOf: str | None = None
    advanceRatio: float | None = None
    medianReturn: float | None = None
    advanceRatioDelta: float | None = None
    medianReturnDelta: float | None = None
    comparisonStatus: Literal["available", "insufficient"]
    reason: str | None = None
    comparisonReason: str | None = None
    evidence: list[str] = Field(default_factory=list)


class SynchronizationTrendDimension(BaseModel):
    status: SynchronizationDimensionStatus
    aboveMa20Count: int
    belowMa20Count: int
    validCount: int
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)


class SynchronizationTurnoverDimension(BaseModel):
    status: SynchronizationDimensionStatus
    medianAmountRatio5: float | None = None
    growthMedianAmountRatio5: float | None = None
    volumeBackedAdvanceCount: int
    volumeBackedDeclineCount: int
    validCount: int
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)


class SynchronizationDimensions(BaseModel):
    breadth: SynchronizationBreadthDimension
    trend: SynchronizationTrendDimension
    turnover: SynchronizationTurnoverDimension


class SynchronizationAssessment(BaseModel):
    patternCode: str
    patternLabel: str
    status: SynchronizationAssessmentStatus
    conclusionCode: SynchronizationConclusionCode
    conclusion: str
    confidence: Literal["high", "medium", "low", "insufficient"]
    allFiveWeak: bool
    dimensions: SynchronizationDimensions
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class HistoryPoint(BaseModel):
    date: str
    open: float
    close: float
    low: float
    high: float
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None
    amount: float


class IndexCombination(BaseModel):
    key: str
    state: str | None
    matched: bool
    tone: str
    evidence: list[str]
    tradingMode: str


class IndexAnalysis(BaseModel):
    code: str
    name: str
    representative: str
    changePct: float
    close: float
    movingAverages: MovingAverages
    rangePosition20: float | None
    rangePosition60: float | None
    rangePosition20Label: str
    rangePosition60Label: str
    amount: float
    amountRatio5: float | None
    amountRatio20: float | None
    ma20SlopePercentile: float | None = None
    advanceEfficiencyPercentile: float | None = None
    ma20SlopeConfidence: str | None = None
    advanceEfficiencyConfidence: str | None = None
    ma20PositionLabel: str | None = None
    trendState: str
    volumePriceState: str | None
    combination: IndexCombination
    history: list[HistoryPoint]
    dataQuality: DataQuality
    dataGaps: list[DataGap] = Field(default_factory=list)


class Summary(BaseModel):
    synchronization: str
    dominantTrend: str
    warnings: list[str]
    syncPattern: SyncPattern | None = None
    synchronizationAssessment: SynchronizationAssessment | None = None
    bullishAlignmentRatio: float | None = None
    dataGaps: list[DataGap] = Field(default_factory=list)


class EvidenceQuality(BaseModel):
    dataset: str
    source: str
    provider: str
    status: str
    observations: int
    asOf: str | None = None
    warning: str | None = None
    warnings: list[str]
    cacheState: str | None = None
    snapshotFetchedAt: str | None = None
    refreshing: bool | None = None
    refreshWarning: str | None = None


class ChapterDocument(BaseModel):
    id: str
    title: str
    document: str
    status: str
    ruleVersion: str


class BreadthEvidence(BaseModel):
    advanceCount: int | None
    declineCount: int | None
    flatCount: int | None
    validCount: int | None
    advanceRatio: float | None
    medianReturn: float | None
    state: str
    quality: EvidenceQuality


class LimitEvidence(BaseModel):
    limitUpCount: int | None
    limitDownCount: int | None
    failedLimitUpCount: int | None
    failedLimitUpRatio: float | None
    maxStreak: int | None
    state: str
    quality: EvidenceQuality


class SectorRow(BaseModel):
    rank: int
    code: str | None
    name: str | None
    changePct: float | None
    amount: float | None
    mainNet: float | None
    mainNetPct: float | None
    upCount: int | None
    downCount: int | None
    leader: str | None


class SectorEvidence(BaseModel):
    rows: list[SectorRow]
    state: str
    quality: EvidenceQuality


class ActiveStock(BaseModel):
    code: str | None
    name: str | None
    industry: str | None
    changePct: float | None
    amount: float | None
    closePosition: float | None


class ActiveDirectionEvidence(BaseModel):
    state: str
    summary: str | None
    topStocks: list[ActiveStock]
    quality: EvidenceQuality


class EventEvidence(BaseModel):
    state: str
    items: list[dict[str, Any]]
    quality: EvidenceQuality


class ChapterAssessment(BaseModel):
    state: str
    confidence: str
    evidence: list[str]
    risks: list[str]
    nextConfirmation: str
    invalidation: str


class CombinationOverview(BaseModel):
    strength: str
    stage: str
    capitalAcceptance: str
    tradingMode: str
    confidence: str
    evidence: list[str]


class Chapter01Evidence(BaseModel):
    status: str
    coverage: float
    documents: list[ChapterDocument]
    breadth: BreadthEvidence
    limits: LimitEvidence
    sectors: SectorEvidence
    activeDirection: ActiveDirectionEvidence
    events: EventEvidence
    combinationOverview: CombinationOverview
    assessment: ChapterAssessment
    summarySentence: str | None = None
    dataGaps: list[DataGap] = Field(default_factory=list)


class MarketEnvironmentResponse(BaseModel):
    asOf: str
    generatedAt: str
    indices: list[IndexAnalysis]
    summary: Summary
    chapter01: Chapter01Evidence | None = None


class Chapter01Response(BaseModel):
    asOf: str
    generatedAt: str
    summary: Summary | None = None
    chapter01: Chapter01Evidence


class CollectionRunRequest(BaseModel):
    asOf: date
    datasets: list[CollectionDataset] | None = None


class CoreIndexCollectionResult(BaseModel):
    code: str
    name: str
    status: CollectionTaskState
    source: str
    observations: int
    warning: str | None
    durationMs: float | None


class CollectionTaskResponse(BaseModel):
    taskId: str
    dataset: CollectionDataset
    asOf: date
    status: CollectionTaskState
    source: str
    observations: int
    warning: str | None
    timings: dict[str, float]
    queuedAt: datetime | None
    startedAt: datetime | None
    completedAt: datetime | None
    durationMs: float | None
    settled: bool
    coreIndices: list[CoreIndexCollectionResult] = Field(default_factory=list)


class CollectionRunResponse(BaseModel):
    runId: str
    asOf: date
    status: CollectionRunState
    requestedDatasets: list[CollectionDataset]
    completedTasks: int
    totalTasks: int
    createdAt: datetime
    startedAt: datetime | None
    completedAt: datetime | None
    tasks: list[CollectionTaskResponse]


class CollectionAttemptSummary(BaseModel):
    taskId: str
    runId: str
    status: CollectionTaskState
    source: str
    observations: int
    warning: str | None
    queuedAt: datetime | None
    startedAt: datetime | None
    completedAt: datetime | None
    durationMs: float | None
    settled: bool


class DatasetCollectionStatus(BaseModel):
    dataset: CollectionDataset
    available: bool
    source: str
    observations: int
    lastSuccessAt: datetime | None
    settled: bool
    refreshWarning: str | None
    latestAttempt: CollectionAttemptSummary | None
    activeTaskId: str | None
    collectionAllowed: bool
    restriction: str | None
    coreIndices: list[CoreIndexCollectionResult]


class CollectionStatusResponse(BaseModel):
    asOf: date
    manualRefreshEnabled: bool
    datasets: list[DatasetCollectionStatus]


def schema_extra(value: Any) -> Any:
    return value
