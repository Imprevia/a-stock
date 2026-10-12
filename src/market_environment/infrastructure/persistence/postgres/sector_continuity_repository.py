"""PostgreSQL persistence for point-in-time sector continuity evidence.

The adapter is intentionally boring: domain objects are validated before they
cross this boundary, JSON is canonicalized for deterministic checksums, and
all writes are additive/idempotent.  A source revision or checksum change is
never silently overwritten.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Connection, text

from ....application.ports.repositories import SectorContinuityRepository
from ....domain.models import (
    BackfillDateAttempt,
    BackfillRun,
    BenchmarkFact,
    CandidateIndustry,
    IndustryAggregate,
    IndustryIdentity,
    InternalStructure,
    Lineage,
    MembershipInterval,
    MetricTrace,
    SectorContinuityResult,
    SecurityDailyFact,
    TaxonomyRevision,
    UniqueValidation,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _lineage_dict(value: Lineage) -> dict[str, Any]:
    return {
        "requested_as_of": value.requested_as_of.isoformat(),
        "actual_as_of": value.actual_as_of.isoformat() if value.actual_as_of else None,
        "source": value.source,
        "source_revision": value.source_revision,
        "schema_version": value.schema_version,
        "checksum": value.checksum,
        "data_version": value.data_version,
        "classification_version": value.classification_version,
        "membership_version": value.membership_version,
        "universe_version": value.universe_version,
        "adjustment_version": value.adjustment_version,
        "benchmark_version": value.benchmark_version,
        "calculation_version": value.calculation_version,
        "fetched_at": value.fetched_at.isoformat() if value.fetched_at else None,
        "warnings": list(value.warnings),
    }


def _lineage(row: Mapping[str, Any]) -> Lineage:
    return Lineage(
        requested_as_of=_date(row["requested_as_of"]),  # type: ignore[arg-type]
        actual_as_of=_date(row.get("actual_as_of")),
        source=str(row["source"]),
        source_revision=str(row["source_revision"]),
        schema_version=int(row["schema_version"]),
        checksum=str(row["checksum"]),
        data_version=row.get("data_version"),
        classification_version=row.get("classification_version"),
        membership_version=row.get("membership_version"),
        universe_version=row.get("universe_version"),
        adjustment_version=row.get("adjustment_version"),
        benchmark_version=row.get("benchmark_version"),
        calculation_version=row.get("calculation_version"),
        fetched_at=_datetime(row.get("fetched_at")),
        warnings=tuple(str(item) for item in _load(row.get("warnings_json"), [])),
        quality_status=str(row.get("quality_status") or "ok"),
        observation_count=int(row.get("observation_count") or 0),
        field_availability=dict(_load(row.get("field_availability_json"), {})),
        evidence_references=tuple(
            str(item) for item in _load(row.get("evidence_references_json"), [])
        ),
    )


def _taxonomy(value: TaxonomyRevision) -> dict[str, Any]:
    return {
        "taxonomy_version": value.taxonomy_version,
        "taxonomy_family": value.taxonomy_family,
        "taxonomy_level": value.taxonomy_level,
        "source_revision": value.source_revision,
        "effective_from": value.effective_from,
        "effective_to": value.effective_to,
        "checksum": value.checksum,
        "imported_at": value.imported_at,
    }


def _taxonomy_from(row: Mapping[str, Any]) -> TaxonomyRevision:
    return TaxonomyRevision(
        taxonomy_version=str(row["taxonomy_version"]),
        taxonomy_family="shenwan",
        taxonomy_level=int(row["taxonomy_level"]),
        source_revision=str(row["source_revision"]),
        effective_from=_date(row["effective_from"]),  # type: ignore[arg-type]
        effective_to=_date(row.get("effective_to")),
        checksum=str(row["checksum"]),
        imported_at=_datetime(row.get("imported_at")),
    )


def _metric(value: MetricTrace) -> dict[str, Any]:
    return {
        "rule_id": value.rule_id,
        "value": value.value,
        "percentile": value.percentile,
        "score": value.score,
        "status": value.status,
        "weight": value.weight,
        "original_weight": value.original_weight,
        "normalized_weight": value.normalized_weight,
        "observations": value.observations,
        "required_observations": value.required_observations,
        "window_days": value.window_days,
        "missing_reason": value.missing_reason,
        "sample_dates": [item.isoformat() for item in value.sample_dates],
        "raw": value.raw,
    }


def _metric_from(value: Mapping[str, Any]) -> MetricTrace:
    return MetricTrace(
        rule_id=str(value["rule_id"]),
        value=value.get("value"), percentile=value.get("percentile"), score=value.get("score"),
        status=str(value["status"]), weight=float(value["weight"]),
        original_weight=float(value["original_weight"]),
        normalized_weight=value.get("normalized_weight"), observations=int(value["observations"]),
        required_observations=int(value.get("required_observations", 60)),
        window_days=int(value.get("window_days", 250)), missing_reason=value.get("missing_reason"),
        sample_dates=tuple(date.fromisoformat(str(item)) for item in value.get("sample_dates", [])),
        raw=value.get("raw", {}),
    )


def _internal(value: InternalStructure | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "effective_member_count": value.effective_member_count,
        "advancing_count": value.advancing_count,
        "declining_count": value.declining_count,
        "flat_count": value.flat_count,
        "limit_up_count": value.limit_up_count,
        "limit_down_count": value.limit_down_count,
        "top_by_turnover": list(value.top_by_turnover),
        "top_by_return": list(value.top_by_return),
        "top_security_turnover_contribution": value.top_security_turnover_contribution,
        "diffusion_ratio": value.diffusion_ratio,
    }


def _internal_from(value: Mapping[str, Any] | None) -> InternalStructure | None:
    if value is None:
        return None
    return InternalStructure(
        effective_member_count=int(value["effective_member_count"]),
        advancing_count=value.get("advancing_count"), declining_count=value.get("declining_count"),
        flat_count=value.get("flat_count"), limit_up_count=value.get("limit_up_count"),
        limit_down_count=value.get("limit_down_count"),
        top_by_turnover=tuple(value.get("top_by_turnover", [])),
        top_by_return=tuple(value.get("top_by_return", [])),
        top_security_turnover_contribution=value.get("top_security_turnover_contribution"),
        diffusion_ratio=value.get("diffusion_ratio"),
    )


def _candidate(value: CandidateIndustry) -> dict[str, Any]:
    return {
        "industry_id": value.industry_id, "display_name": value.display_name,
        "stage": value.stage, "total_score": value.total_score,
        "core_scores": dict(value.core_scores), "rule_traces": [_metric(item) for item in value.rule_traces],
        "crowding_risk": value.crowding_risk, "vetoes": list(value.vetoes),
        "internal_structure": _internal(value.internal_structure),
        "confirmation_streak": value.confirmation_streak,
    }


def _candidate_from(value: Mapping[str, Any]) -> CandidateIndustry:
    return CandidateIndustry(
        industry_id=str(value["industry_id"]), display_name=str(value["display_name"]),
        stage=str(value["stage"]), total_score=value.get("total_score"),
        core_scores=value.get("core_scores", {}),
        rule_traces=tuple(_metric(item) for item in value.get("rule_traces", [])),
        crowding_risk=value.get("crowding_risk"), vetoes=tuple(str(item) for item in value.get("vetoes", [])),
        internal_structure=_internal_from(value.get("internal_structure")),
        confirmation_streak=int(value.get("confirmation_streak", 0)),
    )


def _validation(value: UniqueValidation) -> dict[str, Any]:
    return {
        "candidate_industry": value.candidate_industry, "candidate_name": value.candidate_name,
        "stage": value.stage, "persistence_evidence": value.persistence_evidence,
        "breadth_evidence": value.breadth_evidence, "turnover_evidence": value.turnover_evidence,
        "internal_structure": value.internal_structure, "target": value.target,
        "confirmation_condition": value.confirmation_condition,
        "invalidation_condition": value.invalidation_condition,
    }


def _validation_from(value: Mapping[str, Any]) -> UniqueValidation:
    return UniqueValidation(
        candidate_industry=value.get("candidate_industry"), candidate_name=value.get("candidate_name"),
        stage=str(value["stage"]), persistence_evidence=str(value["persistence_evidence"]),
        breadth_evidence=str(value["breadth_evidence"]), turnover_evidence=str(value["turnover_evidence"]),
        internal_structure=str(value["internal_structure"]), target=str(value["target"]),
        confirmation_condition=str(value["confirmation_condition"]),
        invalidation_condition=str(value["invalidation_condition"]),
    )


def _result_payload(value: SectorContinuityResult) -> dict[str, Any]:
    return {
        "as_of": value.as_of.isoformat(), "status": value.status, "confidence": value.confidence,
        "coverage": value.coverage, "metrics": [_metric(item) for item in value.metrics],
        "candidates": [_candidate(item) for item in value.candidates],
        "validation": _validation(value.validation), "missing_inputs": list(value.missing_inputs),
        "warnings": list(value.warnings),
    }


def _result_from(row: Mapping[str, Any]) -> SectorContinuityResult:
    payload = _load(row["result_json"], {})
    return SectorContinuityResult(
        as_of=_date(row["as_of"]), status=str(row["status"]), confidence=str(row["confidence"]),
        coverage=row.get("coverage"), metrics=tuple(_metric_from(item) for item in payload.get("metrics", [])),
        candidates=tuple(_candidate_from(item) for item in payload.get("candidates", [])),
        validation=_validation_from(payload["validation"]),
        lineage=_lineage(row), missing_inputs=tuple(str(item) for item in payload.get("missing_inputs", [])),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
    )


class PostgresSectorContinuityRepository(SectorContinuityRepository):
    """Single UoW repository for taxonomy, facts, aggregates and analysis."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def put_taxonomy(self, revision: TaxonomyRevision) -> TaxonomyRevision:
        existing = self.connection.execute(
            text("SELECT * FROM sector_taxonomy_revisions WHERE taxonomy_version=:v AND source_revision=:r"),
            {"v": revision.taxonomy_version, "r": revision.source_revision},
        ).mappings().all()
        if existing and any(str(row["checksum"]) != revision.checksum for row in existing):
            raise ValueError("conflicting taxonomy evidence checksum")
        self.connection.execute(
            text("""INSERT INTO sector_taxonomy_revisions
                (taxonomy_version,taxonomy_family,taxonomy_level,source_revision,effective_from,effective_to,checksum,imported_at)
                VALUES (:taxonomy_version,:taxonomy_family,:taxonomy_level,:source_revision,:effective_from,:effective_to,:checksum,:imported_at)
                ON CONFLICT DO NOTHING"""), _taxonomy(revision),
        )
        return revision

    put_taxonomy_revision = put_taxonomy

    def get_taxonomy_revision(
        self, taxonomy_version: str, source_revision: str
    ) -> TaxonomyRevision | None:
        row = self.connection.execute(
            text("""SELECT * FROM sector_taxonomy_revisions
                WHERE taxonomy_version=:taxonomy_version AND source_revision=:source_revision
                ORDER BY imported_at DESC LIMIT 1"""),
            {"taxonomy_version": taxonomy_version, "source_revision": source_revision},
        ).mappings().first()
        return _taxonomy_from(row) if row is not None else None

    def put_industry(self, identity: IndustryIdentity) -> IndustryIdentity:
        self.put_taxonomy(identity.taxonomy)
        params = {
            "industry_id": identity.industry_id, "display_name": identity.display_name,
            "taxonomy_version": identity.taxonomy.taxonomy_version,
            "source_revision": identity.taxonomy.source_revision,
            "taxonomy_checksum": identity.taxonomy.checksum,
        }
        existing = self.connection.execute(
            text("""SELECT display_name FROM sector_industries
                WHERE industry_id=:industry_id AND taxonomy_version=:taxonomy_version
                  AND source_revision=:source_revision AND taxonomy_checksum=:taxonomy_checksum"""),
            params,
        ).scalar_one_or_none()
        if existing is not None and str(existing) != identity.display_name:
            raise ValueError("conflicting industry identity evidence")
        self.connection.execute(
            text("""INSERT INTO sector_industries
                (industry_id,display_name,taxonomy_version,source_revision,taxonomy_checksum)
                VALUES (:industry_id,:display_name,:taxonomy_version,:source_revision,:taxonomy_checksum)
                ON CONFLICT DO NOTHING"""), params,
        )
        return identity

    def list_industries(self, taxonomy_version: str) -> Sequence[IndustryIdentity]:
        rows = self.connection.execute(
            text("""SELECT i.*, t.taxonomy_family, t.taxonomy_level, t.effective_from,
                t.effective_to, t.imported_at, t.checksum AS checksum
                FROM sector_industries i JOIN sector_taxonomy_revisions t
                ON t.taxonomy_version=i.taxonomy_version
                  AND t.source_revision=i.source_revision AND t.checksum=i.taxonomy_checksum
                WHERE i.taxonomy_version=:taxonomy_version ORDER BY i.industry_id"""),
            {"taxonomy_version": taxonomy_version},
        ).mappings()
        return tuple(
            IndustryIdentity(
                industry_id=str(row["industry_id"]), display_name=str(row["display_name"]),
                taxonomy=_taxonomy_from(row),
            )
            for row in rows
        )

    def put_membership(self, interval: MembershipInterval) -> MembershipInterval:
        rows = self.connection.execute(
            text("""SELECT * FROM sector_membership_intervals
                WHERE security_id=:security_id AND taxonomy_version=:taxonomy_version"""),
            {"security_id": interval.security_id, "taxonomy_version": interval.taxonomy_version},
        ).mappings().all()
        for row in rows:
            same = (
                str(row["industry_id"]) == interval.industry_id
                and _date(row["valid_from"]) == interval.valid_from
                and str(row["source_revision"]) == interval.source_revision
                and str(row["evidence_checksum"]) == interval.evidence_checksum
            )
            if same:
                return interval
            left = _date(row["valid_from"])
            right = _date(row.get("valid_to"))
            overlaps = interval.valid_from < (right or date.max) and (interval.valid_to or date.max) > left
            if overlaps:
                raise ValueError("conflicting overlapping membership interval")
        self.connection.execute(
            text("""INSERT INTO sector_membership_intervals
                (security_id,industry_id,taxonomy_version,valid_from,valid_to,source_revision,evidence_checksum)
                VALUES (:security_id,:industry_id,:taxonomy_version,:valid_from,:valid_to,:source_revision,:evidence_checksum)
                ON CONFLICT DO NOTHING"""),
            {
                "security_id": interval.security_id, "industry_id": interval.industry_id,
                "taxonomy_version": interval.taxonomy_version, "valid_from": interval.valid_from,
                "valid_to": interval.valid_to, "source_revision": interval.source_revision,
                "evidence_checksum": interval.evidence_checksum,
            },
        )
        return interval

    def list_memberships(self, as_of: date, *, industry_id: str | None = None) -> Sequence[MembershipInterval]:
        where = "valid_from <= :as_of AND (valid_to IS NULL OR valid_to > :as_of)"
        params: dict[str, Any] = {"as_of": as_of}
        if industry_id is not None:
            where += " AND industry_id = :industry_id"
            params["industry_id"] = industry_id
        rows = self.connection.execute(
            text(f"SELECT * FROM sector_membership_intervals WHERE {where} ORDER BY security_id, industry_id"), params
        ).mappings()
        return tuple(
            MembershipInterval(
                security_id=str(row["security_id"]), industry_id=str(row["industry_id"]),
                taxonomy_version=str(row["taxonomy_version"]), valid_from=_date(row["valid_from"]),
                valid_to=_date(row.get("valid_to")), source_revision=str(row["source_revision"]),
                evidence_checksum=str(row["evidence_checksum"]),
            ) for row in rows
        )

    def put_security_fact(self, fact: SecurityDailyFact) -> SecurityDailyFact:
        existing = self.connection.execute(
            text("SELECT checksum, adjustment_version FROM sector_security_daily_facts WHERE security_id=:security_id AND as_of=:as_of AND source_revision=:source_revision"),
            {"security_id": fact.security_id, "as_of": fact.as_of, "source_revision": fact.lineage.source_revision},
        ).mappings().all()
        matching_revision = [
            row for row in existing
            if row.get("adjustment_version") == fact.lineage.adjustment_version
        ]
        if matching_revision and any(
            str(row["checksum"]) != fact.lineage.checksum for row in matching_revision
        ):
            raise ValueError("conflicting security daily fact checksum")
        p = {"security_id": fact.security_id, "as_of": fact.as_of, "market": fact.market,
             "original_close": fact.original_close, "original_open": fact.original_open,
             "original_high": fact.original_high, "original_low": fact.original_low,
             "previous_close": fact.previous_close, "adjusted_close": fact.adjusted_close,
             "adjusted_previous_close": fact.adjusted_previous_close,
             "amount": fact.amount, "volume": fact.volume,
             "change_pct": fact.change_pct, "eligible": int(fact.eligible), "exclusion_reason": fact.exclusion_reason}
        p.update(_lineage_db_params(fact.lineage))
        self.connection.execute(text("""INSERT INTO sector_security_daily_facts
            (security_id,as_of,market,original_close,original_open,original_high,original_low,previous_close,adjusted_close,adjusted_previous_close,amount,volume,change_pct,eligible,exclusion_reason,
             requested_as_of,actual_as_of,source,source_revision,schema_version,checksum,data_version,classification_version,membership_version,
             universe_version,adjustment_version,benchmark_version,calculation_version,fetched_at,warnings_json,quality_status,observation_count,field_availability_json,evidence_references_json)
            VALUES (:security_id,:as_of,:market,:original_close,:original_open,:original_high,:original_low,:previous_close,:adjusted_close,:adjusted_previous_close,:amount,:volume,:change_pct,:eligible,:exclusion_reason,
             :requested_as_of,:actual_as_of,:source,:source_revision,:schema_version,:checksum,:data_version,:classification_version,:membership_version,
             :universe_version,:adjustment_version,:benchmark_version,:calculation_version,:fetched_at,:warnings_json,:quality_status,:observation_count,:field_availability_json,:evidence_references_json)
            ON CONFLICT DO NOTHING"""), {**p, "warnings_json": _json(list(fact.lineage.warnings))})
        return fact

    def list_security_facts(self, as_of: date) -> Sequence[SecurityDailyFact]:
        rows = self.connection.execute(text("SELECT * FROM sector_security_daily_facts WHERE as_of=:as_of ORDER BY security_id"), {"as_of": as_of}).mappings()
        return tuple(self._security_from(row) for row in rows)

    def get_security_fact(self, security_id: str, as_of: date) -> SecurityDailyFact | None:
        row = self.connection.execute(
            text("""SELECT * FROM sector_security_daily_facts
                WHERE security_id=:security_id AND as_of=:as_of
                ORDER BY fetched_at DESC LIMIT 1"""),
            {"security_id": security_id, "as_of": as_of},
        ).mappings().first()
        return self._security_from(row) if row is not None else None

    def _security_from(self, row: Mapping[str, Any]) -> SecurityDailyFact:
        return SecurityDailyFact(
            security_id=str(row["security_id"]), as_of=_date(row["as_of"]), market=str(row["market"]),
            original_close=row.get("original_close"), previous_close=row.get("previous_close"),
            adjusted_close=row.get("adjusted_close"), amount=row.get("amount"), volume=row.get("volume"),
            change_pct=row.get("change_pct"), eligible=bool(row["eligible"]), lineage=_lineage(row),
            exclusion_reason=row.get("exclusion_reason"),
            original_open=row.get("original_open"), original_high=row.get("original_high"),
            original_low=row.get("original_low"),
            adjusted_previous_close=row.get("adjusted_previous_close"),
        )

    def put_benchmark_fact(self, fact: BenchmarkFact) -> BenchmarkFact:
        existing = self.connection.execute(
            text("""SELECT checksum FROM sector_benchmark_facts
                WHERE benchmark_id=:benchmark_id AND as_of=:as_of
                  AND source_revision=:source_revision"""),
            {"benchmark_id": fact.benchmark_id, "as_of": fact.as_of,
             "source_revision": fact.lineage.source_revision},
        ).scalars().all()
        if existing and any(str(item) != fact.lineage.checksum for item in existing):
            raise ValueError("conflicting benchmark fact checksum")
        p = {"benchmark_id": fact.benchmark_id, "as_of": fact.as_of, "return_value": fact.return_value,
             "eligible_count": fact.eligible_count, "excluded_count": fact.excluded_count,
             "session_dates_json": _json([item.isoformat() for item in fact.session_dates])}
        p.update(_lineage_db_params(fact.lineage))
        self.connection.execute(text("""INSERT INTO sector_benchmark_facts
            (benchmark_id,as_of,return_value,eligible_count,excluded_count,session_dates_json,requested_as_of,actual_as_of,source,source_revision,
             schema_version,checksum,data_version,classification_version,membership_version,universe_version,adjustment_version,benchmark_version,
             calculation_version,fetched_at,warnings_json,quality_status,observation_count,field_availability_json,evidence_references_json)
            VALUES (:benchmark_id,:as_of,:return_value,:eligible_count,:excluded_count,:session_dates_json,:requested_as_of,:actual_as_of,:source,:source_revision,
             :schema_version,:checksum,:data_version,:classification_version,:membership_version,:universe_version,:adjustment_version,:benchmark_version,
             :calculation_version,:fetched_at,:warnings_json,:quality_status,:observation_count,:field_availability_json,:evidence_references_json) ON CONFLICT DO NOTHING"""), {**p, "warnings_json": _json(list(fact.lineage.warnings))})
        return fact

    def get_benchmark_fact(self, as_of: date, benchmark_id: str = "ordinary-a-share-equal-weight-v1") -> BenchmarkFact | None:
        row = self.connection.execute(text("SELECT * FROM sector_benchmark_facts WHERE as_of=:as_of AND benchmark_id=:benchmark_id ORDER BY fetched_at DESC LIMIT 1"), {"as_of": as_of, "benchmark_id": benchmark_id}).mappings().first()
        if row is None:
            return None
        return BenchmarkFact(benchmark_id=str(row["benchmark_id"]), as_of=_date(row["as_of"]), return_value=row.get("return_value"), eligible_count=int(row["eligible_count"]), excluded_count=int(row["excluded_count"]), session_dates=tuple(date.fromisoformat(str(item)) for item in _load(row["session_dates_json"], [])), lineage=_lineage(row))

    def put_industry_aggregate(self, aggregate: IndustryAggregate) -> IndustryAggregate:
        if not aggregate.lineage.calculation_version:
            raise ValueError("industry aggregate requires calculation_version")
        existing = self.connection.execute(
            text("""SELECT checksum FROM sector_industry_aggregates
                WHERE industry_id=:industry_id AND as_of=:as_of
                  AND source_revision=:source_revision
                  AND calculation_version=:calculation_version"""),
            {"industry_id": aggregate.industry_id, "as_of": aggregate.as_of,
             "source_revision": aggregate.lineage.source_revision,
             "calculation_version": aggregate.lineage.calculation_version},
        ).scalars().all()
        if existing and any(str(item) != aggregate.lineage.checksum for item in existing):
            raise ValueError("conflicting industry aggregate checksum")
        p = {"industry_id": aggregate.industry_id, "as_of": aggregate.as_of, "member_count": aggregate.member_count,
             "eligible_return_count": aggregate.eligible_return_count, "eligible_amount_count": aggregate.eligible_amount_count,
             "eligible_ma20_count": aggregate.eligible_ma20_count, "industry_return": aggregate.industry_return,
             "original_amount": aggregate.original_amount, "breadth_ratio": aggregate.breadth_ratio,
             "advance_count": aggregate.advance_count, "decline_count": aggregate.decline_count, "flat_count": aggregate.flat_count,
             "limit_up_count": aggregate.limit_up_count, "limit_down_count": aggregate.limit_down_count,
             "excluded_reasons_json": _json(dict(aggregate.excluded_reasons)),
             "input_checksum": aggregate.input_checksum or aggregate.lineage.checksum}
        p.update(_lineage_db_params(aggregate.lineage))
        self.connection.execute(text("""INSERT INTO sector_industry_aggregates
          (industry_id,as_of,member_count,eligible_return_count,eligible_amount_count,eligible_ma20_count,industry_return,original_amount,breadth_ratio,
           advance_count,decline_count,flat_count,limit_up_count,limit_down_count,excluded_reasons_json,input_checksum,requested_as_of,actual_as_of,source,source_revision,
           schema_version,checksum,data_version,classification_version,membership_version,universe_version,adjustment_version,benchmark_version,calculation_version,fetched_at,warnings_json,quality_status,observation_count,field_availability_json,evidence_references_json)
          VALUES (:industry_id,:as_of,:member_count,:eligible_return_count,:eligible_amount_count,:eligible_ma20_count,:industry_return,:original_amount,:breadth_ratio,
           :advance_count,:decline_count,:flat_count,:limit_up_count,:limit_down_count,:excluded_reasons_json,:input_checksum,:requested_as_of,:actual_as_of,:source,:source_revision,
           :schema_version,:checksum,:data_version,:classification_version,:membership_version,:universe_version,:adjustment_version,:benchmark_version,:calculation_version,:fetched_at,:warnings_json,:quality_status,:observation_count,:field_availability_json,:evidence_references_json)
          ON CONFLICT DO NOTHING"""), {**p, "warnings_json": _json(list(aggregate.lineage.warnings))})
        return aggregate

    def list_industry_aggregates(self, as_of: date) -> Sequence[IndustryAggregate]:
        rows = self.connection.execute(text("SELECT * FROM sector_industry_aggregates WHERE as_of=:as_of ORDER BY industry_id"), {"as_of": as_of}).mappings()
        return tuple(IndustryAggregate(industry_id=str(row["industry_id"]), as_of=_date(row["as_of"]), member_count=int(row["member_count"]), eligible_return_count=int(row["eligible_return_count"]), eligible_amount_count=int(row["eligible_amount_count"]), eligible_ma20_count=int(row["eligible_ma20_count"]), industry_return=row.get("industry_return"), original_amount=row.get("original_amount"), breadth_ratio=row.get("breadth_ratio"), advance_count=row.get("advance_count"), decline_count=row.get("decline_count"), flat_count=row.get("flat_count"), limit_up_count=row.get("limit_up_count"), limit_down_count=row.get("limit_down_count"), excluded_reasons=_load(row["excluded_reasons_json"], {}), lineage=_lineage(row), input_checksum=row.get("input_checksum")) for row in rows)

    def get_industry_aggregate(self, industry_id: str, as_of: date) -> IndustryAggregate | None:
        return next(
            (item for item in self.list_industry_aggregates(as_of) if item.industry_id == industry_id),
            None,
        )

    def put_result(self, result: SectorContinuityResult) -> SectorContinuityResult:
        if not result.lineage.calculation_version:
            raise ValueError("continuity result requires calculation_version")
        existing = self.connection.execute(
            text("""SELECT checksum FROM sector_continuity_results
                WHERE as_of=:as_of AND source_revision=:source_revision
                  AND calculation_version=:calculation_version"""),
            {"as_of": result.as_of, "source_revision": result.lineage.source_revision,
             "calculation_version": result.lineage.calculation_version},
        ).scalars().all()
        if existing and any(str(item) != result.lineage.checksum for item in existing):
            raise ValueError("conflicting continuity result checksum")
        p = {"as_of": result.as_of, "status": result.status, "confidence": result.confidence, "coverage": result.coverage, "result_json": _json(_result_payload(result))}
        p.update(_lineage_db_params(result.lineage))
        self.connection.execute(text("""INSERT INTO sector_continuity_results
          (as_of,status,confidence,coverage,result_json,requested_as_of,actual_as_of,source,source_revision,schema_version,checksum,data_version,
           classification_version,membership_version,universe_version,adjustment_version,benchmark_version,calculation_version,fetched_at,warnings_json,quality_status,observation_count,field_availability_json,evidence_references_json)
          VALUES (:as_of,:status,:confidence,:coverage,:result_json,:requested_as_of,:actual_as_of,:source,:source_revision,:schema_version,:checksum,:data_version,
           :classification_version,:membership_version,:universe_version,:adjustment_version,:benchmark_version,:calculation_version,:fetched_at,:warnings_json,:quality_status,:observation_count,:field_availability_json,:evidence_references_json)
          ON CONFLICT DO NOTHING"""), {**p, "warnings_json": _json(list(result.lineage.warnings))})
        return result

    def get_result(self, as_of: date, calculation_version: str | None = None) -> SectorContinuityResult | None:
        where = "as_of=:as_of"; params: dict[str, Any] = {"as_of": as_of}
        if calculation_version is not None:
            where += " AND calculation_version=:calculation_version"; params["calculation_version"] = calculation_version
        row = self.connection.execute(text(f"SELECT * FROM sector_continuity_results WHERE {where} ORDER BY fetched_at DESC LIMIT 1"), params).mappings().first()
        return _result_from(row) if row is not None else None

    def put_backfill_run(self, run: BackfillRun) -> BackfillRun:
        existing = self.connection.execute(text("SELECT calculation_version,status,session_dates_json FROM sector_backfill_runs WHERE run_id=:run_id"), {"run_id": run.run_id}).mappings().first()
        if existing is not None and (str(existing["calculation_version"]) != run.calculation_version or _load(existing["session_dates_json"], []) != [item.isoformat() for item in run.session_dates]):
            raise ValueError("conflicting backfill run identity")
        self.connection.execute(text("""INSERT INTO sector_backfill_runs
          (run_id,as_of,session_dates_json,source_revisions_json,calculation_version,status,requested_at,completed_at,warnings_json)
          VALUES (:run_id,:as_of,:session_dates_json,:source_revisions_json,:calculation_version,:status,:requested_at,:completed_at,:warnings_json)
          ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, completed_at=excluded.completed_at, warnings_json=excluded.warnings_json"""), {
            "run_id": run.run_id, "as_of": run.as_of, "session_dates_json": _json([item.isoformat() for item in run.session_dates]), "source_revisions_json": _json(dict(run.source_revisions)), "calculation_version": run.calculation_version, "status": run.status, "requested_at": datetime.now(timezone.utc), "completed_at": None, "warnings_json": "[]",
        })
        return run

    def put_backfill_attempt(self, attempt: BackfillDateAttempt) -> BackfillDateAttempt:
        self.connection.execute(text("""INSERT INTO sector_backfill_attempts
          (run_id,as_of,status,requested_at,completed_at,retry_eligible,warning,compatible_result_checksum)
          VALUES (:run_id,:as_of,:status,:requested_at,:completed_at,:retry_eligible,:warning,:compatible_result_checksum)
          ON CONFLICT(run_id,as_of) DO UPDATE SET status=excluded.status,completed_at=excluded.completed_at,retry_eligible=excluded.retry_eligible,warning=excluded.warning,compatible_result_checksum=excluded.compatible_result_checksum"""), {
              "run_id": attempt.run_id, "as_of": attempt.as_of, "status": attempt.status, "requested_at": attempt.requested_at, "completed_at": attempt.completed_at, "retry_eligible": int(attempt.retry_eligible), "warning": attempt.warning, "compatible_result_checksum": attempt.compatible_result_checksum,
          })
        return attempt

    def list_backfill_attempts(self, run_id: str) -> Sequence[BackfillDateAttempt]:
        rows = self.connection.execute(text("SELECT * FROM sector_backfill_attempts WHERE run_id=:run_id ORDER BY as_of"), {"run_id": run_id}).mappings()
        return tuple(BackfillDateAttempt(run_id=str(row["run_id"]), as_of=_date(row["as_of"]), status=str(row["status"]), requested_at=_datetime(row["requested_at"]), completed_at=_datetime(row.get("completed_at")), retry_eligible=bool(row["retry_eligible"]), warning=row.get("warning"), compatible_result_checksum=row.get("compatible_result_checksum")) for row in rows)


def _lineage_db_params(value: Lineage) -> dict[str, Any]:
    return {
        "requested_as_of": value.requested_as_of, "actual_as_of": value.actual_as_of,
        "source": value.source, "source_revision": value.source_revision,
        "schema_version": value.schema_version, "checksum": value.checksum,
        "data_version": value.data_version, "classification_version": value.classification_version,
        "membership_version": value.membership_version, "universe_version": value.universe_version,
        "adjustment_version": value.adjustment_version, "benchmark_version": value.benchmark_version,
        "calculation_version": value.calculation_version, "fetched_at": value.fetched_at,
        "quality_status": value.quality_status,
        "observation_count": value.observation_count,
        "field_availability_json": _json(dict(value.field_availability)),
        "evidence_references_json": _json(list(value.evidence_references)),
    }


__all__ = ["PostgresSectorContinuityRepository"]
