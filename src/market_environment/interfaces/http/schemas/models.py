"""API response schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from ....timezone_preferences import validate_timezone

CollectionDataset = Literal[
    "core",
    "breadth",
    "limits",
    "industry-ranking",
    "sector-turnover",
    "sector-breadth",
    "activeDirection",
]
CollectionRunState = Literal["queued", "collecting", "success", "partial", "failed"]
CollectionTaskState = Literal[
    "queued",
    "collecting",
    "success",
    "partial",
    "failed-retained",
    "failed-missing",
    "busy",
    "blocked",
]
CollectionFailureCategory = Literal[
    "configuration",
    "engine-unavailable",
    "network",
    "rate-limit",
    "permission",
    "challenge",
    "contract",
    "date-mismatch",
    "insufficient",
    "internal",
    "dependency",
    "concurrency",
    "worker-interrupted",
]
EvidenceQualityStatus = Literal[
    "ok",
    "partial",
    "fallback",
    "fallback-derived",
    "failed",
    "missing",
    "degraded",
    "insufficient",
]
CacheState = Literal["fresh", "stale", "missing"]
MetricQualityStatus = Literal["ok", "insufficient", "degraded", "failed"]
SectorMetricQualityStatus = Literal[
    "ok",
    "partial",
    "insufficient",
    "degraded",
    "reduced-confidence",
    "failed",
    "missing",
]
LimitMetricField = Literal["todayPromoted", "yesterdayLimitUpEligible", "promotionRatio"]
PromotionSampleRule = Literal[
    "previous eligible close-limit-up -> current close-limit-up",
    "previous complete limit-up membership -> current complete limit-up membership",
]
PromotionRuleVersion = Literal["limits-promotion-v1", "limits-promotion-v2"]
PROMOTION_SAMPLE_RULE = (
    "previous complete limit-up membership -> current complete limit-up membership"
)
PROMOTION_RULE_VERSION = "limits-promotion-v2"
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
ThsReasonCode = Literal[
    "THS_LIVE_VALUES_MISSING",
    "THS_DAILY_SNAPSHOT_INSUFFICIENT",
    "THS_CATALOG_REVISION_COLLISION",
    "THS_DEPENDENCY_INSUFFICIENT",
    "THS_DEPENDENCY_REVISION_MISMATCH",
]


class ThsBlockedByDiagnostic(BaseModel):
    dataset: str
    status: str
    reasonCode: ThsReasonCode | None = None
    exactDate: date | None = None
    catalogRevisionId: str | None = None


class ThsDiagnosticResponse(BaseModel):
    reasonCode: ThsReasonCode
    message: str
    failureStage: str
    exactDate: date
    retryable: bool
    capabilityRevision: str | None = None
    catalogRevisionId: str | None = None
    expectedCount: int | None = Field(default=None, ge=0)
    observedCount: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("observedCount", "observedCodes"),
    )
    usableCount: int | None = Field(default=None, ge=0)
    rankableCount: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("rankableCount", "rankableCodes"),
    )
    barCount: int | None = Field(default=None, ge=0)
    missingLiveCount: int | None = Field(default=None, ge=0)
    missingLiveCodes: list[str] = Field(default_factory=list, max_length=20)
    missingRankingCount: int | None = Field(default=None, ge=0)
    missingRankingCodes: list[str] = Field(default_factory=list, max_length=20)
    existingChecksum: str | None = None
    observedChecksum: str | None = None
    blockedBy: list[ThsBlockedByDiagnostic] = Field(default_factory=list, max_length=8)


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


class SectorEnrichmentDateEvidence(BaseModel):
    """Date gate evidence for the undated same-vendor sector enrichment."""

    requestedAsOf: str = Field(validation_alias=AliasChoices("requestedAsOf", "requested"))
    latestOnly: bool = True
    eligible: bool
    reason: str
    currentAsOf: str | None = Field(
        default=None,
        validation_alias=AliasChoices("currentAsOf", "current"),
    )
    settled: bool | None = None

    @field_validator("requestedAsOf", "currentAsOf")
    @classmethod
    def validate_enrichment_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class SectorEnrichmentQuality(BaseModel):
    """Auditable metadata for optional Eastmoney sector field enrichment.

    The model is additive to ``EvidenceQuality``.  It deliberately carries
    lineage and coverage rather than treating same-vendor dataapi evidence as
    an independent provider or changing the canonical Fuyao row identity.
    """

    status: Literal["disabled", "skipped", "enriched", "partial", "complete", "failed"]
    source: str = "eastmoney-dataapi"
    provider: str = "eastmoney"
    sameVendor: bool = True
    endpoint: str | None = None
    requestedFields: list[str] = Field(default_factory=list)
    mappingRevision: str | None = None
    matchMethod: str | None = None
    sourceRows: int = Field(default=0, ge=0)
    baseRows: int = Field(default=0, ge=0)
    matchedRows: int = Field(default=0, ge=0)
    unmatchedRows: int = Field(default=0, ge=0)
    identityCoverage: float | None = Field(default=None, ge=0, le=1)
    fieldCoverage: dict[str, float] = Field(default_factory=dict)
    fieldMatched: dict[str, int] = Field(default_factory=dict)
    fieldFilled: dict[str, int] = Field(default_factory=dict)
    percentageScale: float | None = None
    dateEvidence: SectorEnrichmentDateEvidence | None = None
    warnings: list[str] = Field(default_factory=list)


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
    marketEvidence: dict[str, Any] | None = None
    reviewSentence: dict[str, Any] | None = None
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
    derived: bool | None = None
    rankingMethod: str | None = None
    sourceRevision: str | None = None
    catalogRevisionId: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "catalogRevisionId",
            "catalogRevision",
            "revisionId",
        ),
    )
    expectedCount: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("expectedCount", "expectedCodes"),
    )
    observedCount: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("observedCount", "observedCodes"),
    )
    usableCount: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("usableCount", "storedCodes"),
    )
    rankableCount: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("rankableCount", "rankableCodes"),
    )
    barCount: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("barCount", "barCodes"),
    )
    missingLiveCount: int | None = Field(default=None, ge=0)
    missingLiveCodes: list[str] = Field(default_factory=list)
    missingRankingCount: int | None = Field(default=None, ge=0)
    missingRankingCodes: list[str] = Field(default_factory=list)
    diagnostics: ThsDiagnosticResponse | None = None
    industryMappingRevision: str | None = None
    industryMappingCoverage: float | None = Field(default=None, ge=0, le=1)
    industryMappingCovered: int | None = Field(default=None, ge=0)
    industryMappingTotal: int | None = Field(default=None, ge=0)
    stockUniversePolicyVersion: str | None = None
    stockUniverseRawCount: int | None = Field(default=None, ge=0)
    stockUniverseRetainedCount: int | None = Field(default=None, ge=0)
    stockUniverseExcludedCount: int | None = Field(default=None, ge=0)
    stockUniverseUnclassifiedCount: int | None = Field(default=None, ge=0)
    stockUniverseRetainedByMarket: dict[str, int] | None = None
    stockUniverseExcludedByReason: dict[str, int] | None = None
    stockUniverseUnclassifiedByReason: dict[str, int] | None = None
    sectorEnrichment: SectorEnrichmentQuality | None = None

    @model_validator(mode="before")
    @classmethod
    def retain_ths_missing_totals_before_sampling(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for codes_name, count_name in (
            ("missingLiveCodes", "missingLiveCount"),
            ("missingRankingCodes", "missingRankingCount"),
        ):
            codes = normalized.get(codes_name)
            if count_name not in normalized and isinstance(
                codes, (list, tuple, set, frozenset)
            ):
                normalized[count_name] = len(
                    {str(item) for item in codes if item is not None}
                )
        return normalized

    @field_validator("missingLiveCodes", "missingRankingCodes", mode="before")
    @classmethod
    def bound_ths_code_samples(cls, value: Any) -> list[str]:
        if not isinstance(value, (list, tuple, set, frozenset)):
            return []
        return sorted({str(item) for item in value if item is not None})[:20]

    @model_validator(mode="after")
    def infer_ths_missing_counts(self) -> "EvidenceQuality":
        if self.missingLiveCount is None and self.missingLiveCodes:
            self.missingLiveCount = len(self.missingLiveCodes)
        if self.missingRankingCount is None and self.missingRankingCodes:
            self.missingRankingCount = len(self.missingRankingCodes)
        return self


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


class SectorMetricQuality(MetricQuality):
    """Sector-analysis metric quality without widening legacy limit contracts."""

    status: SectorMetricQualityStatus


class LimitSecurityDetailRow(BaseModel):
    securityId: str
    thscode: str | None = None
    code: str
    exchange: str
    name: str | None = None
    poolType: Literal["limit_up", "failed_limit_up", "limit_down"]
    isSt: bool | None = None
    isNew: bool | None = None
    listingDate: str | None = None
    closePrice: float | None = None
    changePct: float | None = None
    streakDays: int | None = Field(default=None, ge=0)
    limitUpTime: str | None = None
    limitUpReason: str | None = None
    sealMoney: float | None = None
    maxSealMoney: float | None = None
    firstLimitTime: str | None = None
    lastLimitTime: str | None = None
    openTimes: int | None = Field(default=None, ge=0)
    turnoverRatioPct: float | None = None
    turnover: float | None = None
    source: str
    rowQuality: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("listingDate")
    @classmethod
    def validate_listing_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class LimitSecurityDetailGroup(BaseModel):
    total: int | None = Field(default=None, ge=0)
    rows: list[LimitSecurityDetailRow] = Field(default_factory=list)
    quality: MetricQuality


class LimitSecurityDetails(BaseModel):
    limitUp: LimitSecurityDetailGroup
    limitDown: LimitSecurityDetailGroup
    failedLimitUp: LimitSecurityDetailGroup
    promoted: LimitSecurityDetailGroup


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


class BreadthHistoryPoint(BaseModel):
    """One trading day's breadth snapshot used in the 02-page history table."""

    asOf: str
    advanceCount: int | None = Field(default=None, ge=0)
    declineCount: int | None = Field(default=None, ge=0)
    flatCount: int | None = Field(default=None, ge=0)
    validCount: int | None = Field(default=None, ge=0)
    advanceRatio: float | None = Field(default=None, ge=0, le=1)
    declineRatio: float | None = Field(default=None, ge=0, le=1)
    advanceDeclineSpread: float | None = Field(default=None, ge=-1, le=1)
    medianReturn: float | None = None
    momentum: float | None = None
    widthLabel: str | None = None
    indexConsistent: bool | None = None
    quality: EvidenceQuality

    @field_validator("asOf")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return _validate_iso_date(value) or value


class BreadthHistoryEvidence(BaseModel):
    """Rolling 250-day window plus the last five exact trading-day observations."""

    points: list[BreadthHistoryPoint] = Field(default_factory=list)
    validObservations: int = Field(default=0, ge=0)
    requiredObservations: int = Field(default=60, ge=0)
    windowDays: int = Field(default=250, ge=0)
    coverage: float | None = Field(default=None, ge=0, le=1)
    percentile250: dict[str, float | None] = Field(default_factory=dict)
    quality: MetricQuality | None = None


class BreadthEvidence(BaseModel):
    advanceCount: int | None
    declineCount: int | None
    flatCount: int | None
    validCount: int | None
    advanceRatio: float | None
    medianReturn: float | None
    state: str
    quality: EvidenceQuality
    # Rollout fields for the 02-page rework; all optional, null when not derivable.
    declineRatio: float | None = Field(default=None, ge=0, le=1)
    advanceDeclineSpread: float | None = Field(default=None, ge=-1, le=1)
    advanceRatioPercentile: float | None = Field(default=None, ge=0, le=1)
    medianReturnPercentile: float | None = Field(default=None, ge=0, le=1)
    spreadPercentile: float | None = Field(default=None, ge=0, le=1)
    momentum: float | None = None
    momentumPercentile: float | None = Field(default=None, ge=0, le=1)
    indexConsistent: bool | None = None
    widthLabel: str | None = None
    widthLabelReason: str | None = None
    history: BreadthHistoryEvidence | None = None


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
    membershipQuality: MetricQuality | None = None
    streakQuality: MetricQuality | None = None
    poolQuality: dict[str, MetricQuality] | None = None
    securityDetails: LimitSecurityDetails | None = None
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
            if not (self.quality.status in {"partial", "fallback", "degraded"}
                    or self.quality.cacheState == "stale"
                    or self.quality.refreshWarning is not None):
                raise ValueError("degraded promotion quality requires fallback or retained evidence")
        return self


class SectorIdentityAssociation(BaseModel):
    providerId: str
    providerName: str | None = None
    shenwanIndustryId: str
    shenwanIndustryName: str
    mappingRevision: str
    validFrom: str
    validTo: str | None = None

    @field_validator("validFrom", "validTo")
    @classmethod
    def validate_mapping_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


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
    exactDateAssociation: SectorIdentityAssociation | None = None


class SectorAnalysisQuality(BaseModel):
    status: Literal["ok", "partial", "degraded", "reduced-confidence", "insufficient", "missing", "failed"]
    confidence: Literal["high", "medium", "low", "insufficient"]
    coverage: float | None = Field(default=None, ge=0, le=1)
    asOf: str
    requiredObservations: int = Field(default=60, ge=0)
    availableObservations: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    missingInputs: list[str] = Field(default_factory=list)

    @field_validator("asOf")
    @classmethod
    def validate_analysis_date(cls, value: str) -> str:
        return _validate_iso_date(value) or value


class SectorHistory(BaseModel):
    requiredObservations: int = Field(default=60, ge=0)
    windowDays: int = Field(default=250, ge=1)
    validObservations: int = Field(default=0, ge=0)
    actualDateRange: list[str] | None = None
    gaps: list[str] = Field(default_factory=list)
    quality: SectorMetricQuality | None = None


class SectorMetricTrace(BaseModel):
    ruleId: str
    value: float | int | None = None
    percentile: float | None = Field(default=None, ge=0, le=1)
    score: float | int | None = None
    status: SectorMetricQualityStatus
    weight: float = Field(ge=0)
    originalWeight: float = Field(ge=0)
    normalizedWeight: float | None = Field(default=None, ge=0)
    observations: int = Field(default=0, ge=0)
    requiredObservations: int = Field(default=60, ge=0)
    windowDays: int = Field(default=250, ge=1)
    missingReason: str | None = None
    sampleDates: list[str] = Field(default_factory=list)
    actualDateRange: list[str] | None = None
    gaps: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class SectorInternalStructure(BaseModel):
    effectiveMemberCount: int = Field(ge=0)
    advancingCount: int | None = Field(default=None, ge=0)
    decliningCount: int | None = Field(default=None, ge=0)
    flatCount: int | None = Field(default=None, ge=0)
    limitUpCount: int | None = Field(default=None, ge=0)
    limitDownCount: int | None = Field(default=None, ge=0)
    topByTurnover: list[dict[str, Any]] = Field(default_factory=list)
    topByReturn: list[dict[str, Any]] = Field(default_factory=list)
    topSecurityTurnoverContribution: float | None = Field(default=None, ge=0, le=1)
    diffusionRatio: float | None = Field(default=None, ge=0, le=1)


class SectorCandidate(BaseModel):
    industryId: str
    displayName: str
    stage: Literal[
        "insufficient", "high-level-crowding", "mainline-confirmed",
        "mainline-candidate", "one-day-pulse", "rotation-or-ebb",
    ]
    totalScore: float | None = None
    coreScores: dict[str, float | None] = Field(default_factory=dict)
    ruleTraces: list[SectorMetricTrace] = Field(default_factory=list)
    crowdingRisk: bool | None = None
    vetoes: list[str] = Field(default_factory=list)
    internalStructure: SectorInternalStructure | None = None
    confirmationStreak: int = Field(default=0, ge=0)


class SectorUniqueValidation(BaseModel):
    candidateIndustry: str | None = None
    candidateName: str | None = None
    stage: Literal[
        "insufficient", "high-level-crowding", "mainline-confirmed",
        "mainline-candidate", "one-day-pulse", "rotation-or-ebb",
    ]
    persistenceEvidence: str
    breadthEvidence: str
    turnoverEvidence: str
    internalStructure: str
    target: str
    confirmationCondition: str
    invalidationCondition: str


class SectorAnalysisAttempt(BaseModel):
    runId: str | None = None
    status: Literal["success", "partial", "failed-retained", "failed-missing", "insufficient"]
    retryEligible: bool = True
    warning: str | None = None
    compatibleResultChecksum: str | None = None


class SectorAnalysis(BaseModel):
    asOf: str
    status: Literal["ok", "partial", "degraded", "reduced-confidence", "insufficient", "missing", "failed"]
    quality: SectorAnalysisQuality
    history: SectorHistory | None = None
    metricTraces: list[SectorMetricTrace] = Field(default_factory=list)
    candidates: list[SectorCandidate] = Field(default_factory=list, max_length=3)
    validation: SectorUniqueValidation
    risk: dict[str, Any] = Field(default_factory=dict)
    lineage: dict[str, Any] = Field(default_factory=dict)
    latestAttempt: SectorAnalysisAttempt | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("asOf")
    @classmethod
    def validate_analysis_as_of(cls, value: str) -> str:
        return _validate_iso_date(value) or value

    @model_validator(mode="after")
    def validate_single_validation(self) -> "SectorAnalysis":
        if self.validation.candidateIndustry is not None:
            if not self.candidates or self.candidates[0].industryId != self.validation.candidateIndustry:
                raise ValueError("validation must target first candidate")
        if self.validation.candidateIndustry is None and self.validation.stage != "insufficient":
            raise ValueError("null candidate requires insufficient validation stage")
        return self


class SectorEvidence(BaseModel):
    rows: list[SectorRow]
    state: str
    quality: EvidenceQuality
    analysis: SectorAnalysis | None = None


class ThsDatasetEvidence(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    state: str
    quality: EvidenceQuality
    catalogRevisionId: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "catalogRevisionId",
            "catalogRevision",
            "revisionId",
        ),
    )
    diagnostics: ThsDiagnosticResponse | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_catalog_revision_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        rows: list[Any] = []
        for raw in normalized.get("rows") or []:
            if not isinstance(raw, dict):
                rows.append(raw)
                continue
            row = dict(raw)
            revision = row.get("catalogRevisionId", row.get("catalogRevision"))
            row.pop("catalogRevision", None)
            if revision is not None:
                row["catalogRevisionId"] = revision
            rows.append(row)
        normalized["rows"] = rows
        return normalized


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


ReviewSegmentStatus = Literal["available", "degraded", "insufficient", "unverified"]
NextSessionStatus = Literal["available", "pending", "insufficient"]


class MarketReviewEvidence(BaseModel):
    """Seven market-level facts used by the review sentence and comparison."""

    directionPattern: str | None = None
    directionLabel: str | None = None
    advancingIndexCount: int | None = Field(default=None, ge=0)
    decliningIndexCount: int | None = Field(default=None, ge=0)
    validIndexCount: int | None = Field(default=None, ge=0)
    aboveMa20Count: int | None = Field(default=None, ge=0)
    ma20ValidCount: int | None = Field(default=None, ge=0)
    medianAmountRatio5: float | None = None
    volumeBackedAdvanceCount: int | None = Field(default=None, ge=0)
    volumeBackedDeclineCount: int | None = Field(default=None, ge=0)
    advanceRatio: float | None = Field(default=None, ge=0, le=1)
    medianReturn: float | None = None
    status: ReviewSegmentStatus = "available"
    warnings: list[str] = Field(default_factory=list)
    dataGaps: list[DataGap] = Field(default_factory=list)


class ReviewSentenceSegment(BaseModel):
    """One auditable slot in the generated sentence."""

    key: str
    label: str
    value: str
    status: ReviewSegmentStatus
    reason: str | None = None


class ReviewSentence(BaseModel):
    """Market-level sentence with explicit missing-data semantics."""

    status: ReviewSegmentStatus
    template: str
    segments: list[ReviewSentenceSegment]
    fullSentence: str
    warnings: list[str] = Field(default_factory=list)


class NextSessionDeltas(BaseModel):
    directionPattern: str | None = None
    advancingIndexCount: int | None = None
    decliningIndexCount: int | None = None
    aboveMa20Count: int | None = None
    medianAmountRatio5: float | None = None
    volumeBackedAdvanceCount: int | None = None
    volumeBackedDeclineCount: int | None = None
    advanceRatio: float | None = None
    medianReturn: float | None = None


class NextSessionComparison(BaseModel):
    """Exact-date, read-only posterior comparison for the next real session."""

    status: NextSessionStatus
    requestedAsOf: str
    currentAsOf: str | None = None
    nextAsOf: str | None = None
    current: MarketReviewEvidence | None = None
    next: MarketReviewEvidence | None = None
    deltas: NextSessionDeltas = Field(default_factory=NextSessionDeltas)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("requestedAsOf", "currentAsOf", "nextAsOf")
    @classmethod
    def validate_comparison_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)

    @model_validator(mode="after")
    def validate_comparison_dates(self) -> "NextSessionComparison":
        if self.currentAsOf is not None and self.currentAsOf != self.requestedAsOf:
            raise ValueError("currentAsOf must match requestedAsOf for an exact comparison")
        if self.currentAsOf is not None and self.nextAsOf is not None:
            if date.fromisoformat(self.nextAsOf) <= date.fromisoformat(self.currentAsOf):
                raise ValueError("nextAsOf must be strictly later than currentAsOf")
        return self


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
    industryRanking: ThsDatasetEvidence
    sectorTurnover: ThsDatasetEvidence
    sectorBreadth: ThsDatasetEvidence
    sectorAnalysis: SectorAnalysis | None = None
    activeDirection: ActiveDirectionEvidence
    events: EventEvidence
    combinationOverview: CombinationOverview
    assessment: ChapterAssessment
    summarySentence: str | None = None
    marketEvidence: MarketReviewEvidence | None = None
    reviewSentence: ReviewSentence | None = None
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


class NextSessionComparisonResponse(NextSessionComparison):
    """Named response model kept for API discoverability."""

    pass


class CollectionRunRequest(BaseModel):
    asOf: date
    datasets: list[str] | None = None

    @field_validator("datasets")
    @classmethod
    def validate_datasets(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        supported = {
            "core",
            "breadth",
            "limits",
            "industry-ranking",
            "sector-turnover",
            "sector-breadth",
            "activeDirection",
        }
        if "sectors" in value:
            raise ValueError(
                "sectors 已退役；请使用 industry-ranking、sector-turnover 或 sector-breadth"
            )
        unknown = sorted(set(value) - supported)
        if unknown:
            raise ValueError("不支持的数据集：" + "、".join(unknown))
        if not value:
            raise ValueError("至少选择一个数据集")
        return value


class CoreIndexCollectionResult(BaseModel):
    code: str
    name: str
    status: CollectionTaskState
    source: str
    observations: int
    warning: str | None
    durationMs: float | None


class CollectionTaskFailureResponse(BaseModel):
    category: CollectionFailureCategory
    message: str
    retryable: bool
    retained: bool
    source: str | None = None
    stage: str | None = None
    code: str | None = None
    blockedBy: list[str] = Field(default_factory=list)


class CollectionTaskResponse(BaseModel):
    taskId: str
    dataset: CollectionDataset
    asOf: date
    status: CollectionTaskState
    source: str
    observations: int
    warning: str | None
    failure: CollectionTaskFailureResponse | None = None
    diagnostics: ThsDiagnosticResponse | None = None
    catalogRevisionId: str | None = None
    # Provider fallback evidence includes both numeric durations and
    # structured source/revision/failure metadata.
    timings: dict[str, Any]
    queuedAt: datetime | None
    startedAt: datetime | None
    completedAt: datetime | None
    durationMs: float | None
    settled: bool
    coreIndices: list[CoreIndexCollectionResult] = Field(default_factory=list)
    detail: LimitsCollectionDetail | None = None

    @model_validator(mode="after")
    def validate_success_has_no_failure(self) -> "CollectionTaskResponse":
        if self.status in {"success", "partial"} and self.failure is not None:
            raise ValueError("success and partial collection tasks must have null failure")
        return self


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


class FullCollectionRunResponse(CollectionRunResponse):
    outcome: Literal["run"] = "run"
    targetDate: date
    statusUrl: str

    @model_validator(mode="after")
    def validate_target_date(self) -> "FullCollectionRunResponse":
        if self.targetDate != self.asOf:
            raise ValueError("targetDate must match the collection run asOf date")
        return self


class FullCollectionSkippedResponse(BaseModel):
    outcome: Literal["skipped"] = "skipped"
    targetDate: date
    status: Literal["skipped"] = "skipped"
    reason: str
    runId: None = None
    statusUrl: None = None
    tasks: list[CollectionTaskResponse] = Field(default_factory=list, max_length=0)


FullCollectionResponse = Annotated[
    FullCollectionRunResponse | FullCollectionSkippedResponse,
    Field(discriminator="outcome"),
]


class CollectionAttemptSummary(BaseModel):
    taskId: str
    runId: str
    status: CollectionTaskState
    source: str
    observations: int
    warning: str | None
    failure: CollectionTaskFailureResponse | None = None
    diagnostics: ThsDiagnosticResponse | None = None
    catalogRevisionId: str | None = None
    queuedAt: datetime | None
    startedAt: datetime | None
    completedAt: datetime | None
    durationMs: float | None
    settled: bool
    timings: dict[str, Any] = Field(default_factory=dict)
    sampleAsOf: date | None = None
    previousAsOf: date | None = None
    excludedCount: int | None = Field(default=None, ge=0)
    promotionQuality: str | None = None
    promotionDependency: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_success_has_no_failure(self) -> "CollectionAttemptSummary":
        if self.status in {"success", "partial"} and self.failure is not None:
            raise ValueError("success and partial collection attempts must have null failure")
        return self


class DatasetCollectionStatus(BaseModel):
    dataset: CollectionDataset
    available: bool
    source: str
    observations: int
    lastSuccessAt: datetime | None
    settled: bool
    refreshWarning: str | None
    quality: dict[str, Any] | None = None
    catalogRevisionId: str | None = None
    latestAttempt: CollectionAttemptSummary | None
    activeTaskId: str | None
    collectionAllowed: bool
    restriction: str | None
    coreIndices: list[CoreIndexCollectionResult]
    detail: LimitsCollectionDetail | None = None


class SectorBackfillProgress(BaseModel):
    runId: str | None = None
    status: Literal["queued", "running", "success", "partial", "failed"] | None = None
    completedSessions: int = Field(default=0, ge=0)
    totalSessions: int = Field(default=0, ge=0)
    failedSessions: int = Field(default=0, ge=0)


class SectorAnalysisReadiness(BaseModel):
    asOf: date
    status: Literal["ok", "partial", "insufficient", "failed", "missing"]
    requiredHistory: int = Field(ge=0)
    availableHistory: int = Field(ge=0)
    missingSessions: list[date] = Field(default_factory=list)
    coverage: float = Field(ge=0, le=1)
    versions: dict[str, str] = Field(default_factory=dict)
    latestAttempt: SectorAnalysisAttempt | None = None
    backfill: SectorBackfillProgress | None = None
    warnings: list[str] = Field(default_factory=list)
    retryEligible: bool = True


class CollectionStatusResponse(BaseModel):
    asOf: date
    manualRefreshEnabled: bool
    datasets: list[DatasetCollectionStatus]
    sectorAnalysis: SectorAnalysisReadiness | None = None


ThsTag = Literal["industry", "cn_concept", "region", "tszs"]
ThsOperationStatus = Literal[
    "queued",
    "running",
    "success",
    "partial",
    "failed",
    "conflict",
]


class ThsCatalogRevisionResponse(BaseModel):
    catalogRevisionId: str = Field(
        validation_alias=AliasChoices("catalogRevisionId", "revisionId")
    )
    capabilityRevision: str
    providerTimestamp: datetime
    fetchedAt: datetime
    tagCounts: dict[ThsTag, int]
    checksum: str


class ThsCatalogItemResponse(BaseModel):
    tag: ThsTag
    thscode: str
    name: str


class ThsCatalogResponse(BaseModel):
    revision: ThsCatalogRevisionResponse | None
    items: list[ThsCatalogItemResponse]
    page: int = Field(ge=1)
    pageSize: int = Field(ge=1, le=500)
    total: int = Field(ge=0)


class ThsBarCoverageResponse(BaseModel):
    firstDate: date | None
    lastDate: date | None
    storedRows: int = Field(ge=0)
    gaps: list[str] = Field(default_factory=list)


class ThsSectorBarResponse(BaseModel):
    tradingDate: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    turnover: float | None
    quality: str
    source: str
    sourceRevision: str
    warnings: list[str] = Field(default_factory=list)


class ThsSectorBarsResponse(BaseModel):
    thscode: str
    requestedStart: date | None
    requestedEnd: date | None
    coverage: ThsBarCoverageResponse
    items: list[ThsSectorBarResponse]
    page: int = Field(ge=1)
    pageSize: int = Field(ge=1, le=1000)
    total: int = Field(ge=0)


class ThsOperationProgressCounts(BaseModel):
    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    failed: int = Field(ge=0)
    conflicts: int = Field(ge=0)


class ThsOperationCheckpointResponse(BaseModel):
    thscode: str | None = None
    windowStart: date | None = None
    windowEnd: date | None = None
    status: str
    rowsWritten: int | None = Field(default=None, ge=0)
    rowsSkipped: int | None = Field(default=None, ge=0)
    conflicts: int | None = Field(default=None, ge=0)
    warning: str | None = None


class ThsOperationResponse(BaseModel):
    runId: str
    kind: str
    status: ThsOperationStatus
    progress: ThsOperationProgressCounts
    warning: str | None = None
    checkpoints: list[ThsOperationCheckpointResponse] = Field(default_factory=list)


class QueuedThsOperationResponse(BaseModel):
    runId: str
    status: Literal["queued"] = "queued"


class ThsCatalogSyncRequest(BaseModel):
    asOf: date | None = None
    capabilityRevision: str | None = Field(default=None, min_length=1)
    membershipCapabilityRevision: str | None = Field(default=None, min_length=1)
    membershipThscodes: list[str] = Field(default_factory=list, max_length=60)
    requestBudget: int | None = Field(default=None, ge=1)


class ThsTurnoverBackfillRequest(BaseModel):
    thscodes: list[str] = Field(min_length=1, max_length=60)
    startDate: date
    endDate: date
    capabilityRevision: str | None = Field(default=None, min_length=1)
    requestBudget: int | None = Field(default=None, ge=1)


class ThsDumpFileRequest(BaseModel):
    path: str = Field(min_length=1)
    dumpId: str = Field(min_length=1)
    schemaRevision: str = Field(min_length=1)
    capabilityRevision: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    startDate: date
    endDate: date


class ThsMemberFactsImportRequest(BaseModel):
    asOf: date
    sourceRevision: str = Field(min_length=1)
    requestBudget: int | None = Field(default=None, ge=1)
    daily: ThsDumpFileRequest
    adjustment: ThsDumpFileRequest
    incremental: ThsDumpFileRequest | None = None


def schema_extra(value: Any) -> Any:
    return value
