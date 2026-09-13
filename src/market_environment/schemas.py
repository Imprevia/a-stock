"""API response schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .timezone_preferences import validate_timezone

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
EvidenceQualityStatus = Literal[
    "ok", "partial", "fallback", "failed", "missing", "degraded", "insufficient"
]
CacheState = Literal["fresh", "stale", "missing"]
MetricQualityStatus = Literal["ok", "insufficient", "degraded", "failed"]
LimitMetricField = Literal["todayPromoted", "yesterdayLimitUpEligible", "promotionRatio"]
PromotionSampleRule = Literal["previous eligible close-limit-up -> current close-limit-up"]
PromotionRuleVersion = Literal["limits-promotion-v1"]
PROMOTION_SAMPLE_RULE = "previous eligible close-limit-up -> current close-limit-up"
PROMOTION_RULE_VERSION = "limits-promotion-v1"
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
    status: EvidenceQualityStatus
    observations: int
    asOf: str | None = None
    warning: str | None = None
    warnings: list[str]
    cacheState: CacheState | None = None
    snapshotFetchedAt: str | None = None
    refreshing: bool | None = None
    refreshWarning: str | None = None


def _validate_iso_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must use valid YYYY-MM-DD form") from exc
    if parsed.isoformat() != value:
        raise ValueError("date must use valid YYYY-MM-DD form")
    return value


class MetricQuality(BaseModel):
    status: MetricQualityStatus
    reason: str | None
    observations: int | None = Field(default=None, ge=0)
    asOf: str | None
    source: str | None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("asOf")
    @classmethod
    def validate_as_of(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class LimitTierEvidence(BaseModel):
    tier: Literal["first", "second", "third", "four_plus"]
    label: str
    count: int | None = Field(default=None, ge=0)
    observations: int = Field(default=0, ge=0)
    quality: MetricQuality


class LimitStratificationEvidence(BaseModel):
    dimension: Literal["regime", "board", "exchange", "sector", "risk_tier"]
    key: str
    label: str
    count: int | None = Field(default=None, ge=0)
    observations: int = Field(default=0, ge=0)
    quality: MetricQuality


class LimitHistoryPoint(BaseModel):
    asOf: str
    limitUpCount: int | None = Field(default=None, ge=0)
    limitDownCount: int | None = Field(default=None, ge=0)
    failedLimitUpRatio: float | None = Field(default=None, ge=0, le=1)
    promotionRatio: float | None = Field(default=None, ge=0, le=1)
    maxStreak: int | None = Field(default=None, ge=0)
    quality: MetricQuality

    @field_validator("asOf")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return _validate_iso_date(value) or value


class LimitHistoryEvidence(BaseModel):
    points: list[LimitHistoryPoint] = Field(default_factory=list)
    validObservations: int = Field(default=0, ge=0)
    requiredObservations: int = Field(default=60, ge=0)
    windowDays: int = Field(default=250, ge=0)
    coverage: float | None = Field(default=None, ge=0, le=1)
    percentile250: dict[str, float | None] = Field(default_factory=dict)
    quality: MetricQuality


class LimitRuleEvidence(BaseModel):
    ruleId: str
    status: Literal["ok", "insufficient", "degraded", "failed", "needs-backtest"]
    value: float | int | None = None
    score: float | int | None = None
    weight: float | None = Field(default=None, ge=0, le=1)
    thresholdProvenance: str | None = None
    missingInputs: list[str] = Field(default_factory=list)
    vetoes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    calibrationStatus: Literal["needs-backtest", "validated"] | None = None


class LimitRiskEvidence(BaseModel):
    code: str
    label: str
    status: Literal["ok", "insufficient", "degraded", "failed"]
    value: float | int | bool | str | None = None
    asOf: str | None = None
    quality: MetricQuality | None = None
    evidence: list[str] = Field(default_factory=list)

    @field_validator("asOf")
    @classmethod
    def validate_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


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
    todayPromoted: int | None = Field(default=None, ge=0)
    yesterdayLimitUpEligible: int | None = Field(default=None, ge=0)
    promotionRatio: float | None = Field(default=None, ge=0, le=1)
    promotionSampleAsOf: str | None = None
    promotionPreviousAsOf: str | None = None
    promotionSampleRule: PromotionSampleRule | None = None
    promotionRuleVersion: PromotionRuleVersion | None = None
    promotionQuality: MetricQuality | None = None
    fieldQuality: dict[LimitMetricField, MetricQuality] | None = None
    ladder: list[LimitTierEvidence] = Field(default_factory=list)
    stratifications: list[LimitStratificationEvidence] = Field(default_factory=list)
    history: LimitHistoryEvidence | None = None
    ruleEvidence: list[LimitRuleEvidence] = Field(default_factory=list)
    riskEvidence: list[LimitRiskEvidence] = Field(default_factory=list)
    confirmation: str | None = None
    invalidation: str | None = None
    ecosystemCoverage: float | None = Field(default=None, ge=0, le=1)
    confidence: Literal["high", "medium", "low", "insufficient"] | None = None

    @field_validator("promotionSampleAsOf", "promotionPreviousAsOf")
    @classmethod
    def validate_sample_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)

    @model_validator(mode="after")
    def validate_promotion_evidence(self) -> "LimitEvidence":
        numerator = self.todayPromoted
        denominator = self.yesterdayLimitUpEligible
        ratio = self.promotionRatio
        if numerator is not None and denominator is not None and numerator > denominator:
            raise ValueError("todayPromoted cannot exceed yesterdayLimitUpEligible")
        if denominator in (None, 0) and ratio is not None:
            raise ValueError("promotionRatio requires a non-zero denominator")
        if ratio is not None:
            if numerator is None or denominator is None:
                raise ValueError("promotionRatio requires numerator and denominator")
            if abs(ratio - round(numerator / denominator, 4)) > 1e-9:
                raise ValueError("promotionRatio must equal the four-decimal promotion fraction")
        if self.promotionSampleAsOf and self.promotionPreviousAsOf:
            if date.fromisoformat(self.promotionPreviousAsOf) >= date.fromisoformat(self.promotionSampleAsOf):
                raise ValueError("promotionPreviousAsOf must precede promotionSampleAsOf")
        scalar = (numerator, denominator, ratio, self.promotionSampleAsOf,
                  self.promotionPreviousAsOf, self.promotionSampleRule, self.promotionRuleVersion)
        if any(value is not None for value in scalar) and self.promotionQuality is None:
            raise ValueError("promotion metadata requires promotionQuality")
        if self.promotionQuality is None:
            return self
        if self.promotionQuality.status in {"insufficient", "failed"}:
            if ratio is not None:
                raise ValueError("insufficient or failed promotion quality requires a null ratio")
            return self
        if numerator is None or denominator is None or denominator == 0 or ratio is None:
            raise ValueError("ok or degraded promotion quality requires complete non-zero values")
        if not self.promotionSampleAsOf or not self.promotionPreviousAsOf:
            raise ValueError("ok or degraded promotion quality requires both sample dates")
        if self.promotionSampleRule is None or self.promotionRuleVersion is None:
            raise ValueError("ok or degraded promotion quality requires fixed rule metadata")
        if self.promotionQuality.asOf != self.promotionSampleAsOf:
            raise ValueError("promotionQuality.asOf must match promotionSampleAsOf")
        if self.promotionQuality.observations != denominator:
            raise ValueError("promotionQuality.observations must equal the denominator")
        if not self.promotionQuality.reason or not self.promotionQuality.source:
            raise ValueError("ok or degraded promotion quality requires reason and source")
        required = {"todayPromoted", "yesterdayLimitUpEligible", "promotionRatio"}
        if self.fieldQuality is None or set(self.fieldQuality) != required:
            raise ValueError("ok or degraded promotion quality requires all fieldQuality entries")
        expected_dates = {
            "todayPromoted": self.promotionSampleAsOf,
            "yesterdayLimitUpEligible": self.promotionPreviousAsOf,
            "promotionRatio": self.promotionSampleAsOf,
        }
        for field, quality in self.fieldQuality.items():
            if quality.observations != denominator or quality.asOf != expected_dates[field]:
                raise ValueError("fieldQuality sample metadata must match the promotion sample")
            if not quality.reason or not quality.source:
                raise ValueError("ok or degraded field quality requires reason and source")
        statuses = {quality.status for quality in self.fieldQuality.values()}
        if self.promotionQuality.status == "ok" and statuses != {"ok"}:
            raise ValueError("ok promotion quality requires ok field quality")
        if self.promotionQuality.status == "degraded":
            if not statuses <= {"ok", "degraded"} or "degraded" not in statuses:
                raise ValueError("degraded promotion quality requires at least one degraded field")
            if not (self.quality.status in {"fallback", "degraded"}
                    or self.quality.cacheState == "stale"
                    or self.quality.refreshWarning is not None):
                raise ValueError("degraded promotion quality requires fallback or retained evidence")
        return self


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


class LimitsCollectionDetail(BaseModel):
    sampleAsOf: date | None = None
    previousAsOf: date | None = None
    excludedCount: int | None = Field(default=None, ge=0)
    promotionRequired: bool | None = None
    promotionQuality: str | None = None
    promotionDependency: str | None = None
    detailChecksum: str | None = None
    warnings: list[str] = Field(default_factory=list)


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


def _validate_aware_iso8601(value: str) -> str:
    """Require API-generated timestamps to retain an explicit UTC/offset."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be an ISO8601 string with timezone")
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be a valid ISO8601 string with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include Z or an explicit UTC offset")
    return value


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

    @field_validator("generatedAt")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        return _validate_aware_iso8601(value)


class TimezonePreferenceUpdateRequest(BaseModel):
    """Request body for the user/workspace timezone preference endpoint."""

    scope: Literal["personal", "workspace"]
    timezone: str | None = Field(default=None, validation_alias="timezone")

    @field_validator("timezone")
    @classmethod
    def validate_timezone_value(cls, value: str | None) -> str | None:
        try:
            return validate_timezone(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class TimezonePreferencesResponse(BaseModel):
    """Effective timezone plus the two persisted preference scopes."""

    personalTimeZone: str | None = None
    workspaceTimeZone: str | None = None
    effectiveTimeZone: str
    effectiveSource: Literal["personal", "workspace", "browser", "utc-fallback"]
    canManageWorkspaceTimeZone: bool
    # Aliases make the contract easy to consume from non-TypeScript clients,
    # while the camelCase fields above remain the frontend's stable shape.
    timeZone: str
    timezone: str
    updatedAt: datetime | None = None
    warning: str | None = None
    timezoneCapability: dict[str, Any] = Field(default_factory=dict)


class Chapter01Response(BaseModel):
    asOf: str
    generatedAt: str
    summary: Summary | None = None
    chapter01: Chapter01Evidence

    @field_validator("generatedAt")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        return _validate_aware_iso8601(value)


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
    detail: LimitsCollectionDetail | None = None


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
    sampleAsOf: date | None = None
    previousAsOf: date | None = None
    excludedCount: int | None = Field(default=None, ge=0)
    promotionQuality: str | None = None
    promotionDependency: str | None = None
    warnings: list[str] = Field(default_factory=list)


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
    detail: LimitsCollectionDetail | None = None


class CollectionStatusResponse(BaseModel):
    asOf: date
    manualRefreshEnabled: bool
    datasets: list[DatasetCollectionStatus]


def schema_extra(value: Any) -> Any:
    return value
