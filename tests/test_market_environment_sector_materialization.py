from datetime import date, datetime, timezone

from src.market_environment.domain.analysis.sector_continuity import analyze_candidates, build_continuity_result
from src.market_environment.domain.models.sector_continuity import Lineage, MetricTrace
from src.market_environment.infrastructure.materialization_support import MaterializationSupport
from src.market_environment.interfaces.http.schemas.models import (
    Chapter01Evidence,
    SectorAnalysis,
)


AS_OF = date(2026, 10, 9)


class ContinuityRepository:
    def get_result(self, as_of):
        trace = MetricTrace(
            "QTS-01-05-05", 0.6, 0.7, 75, "ok", 0.15, 0.15, 1.0, 250
        )
        return build_continuity_result(
            as_of=as_of,
            traces=(trace,),
            candidates=(),
            validation=analyze_candidates({})[1],
            lineage=Lineage(
                as_of, as_of, "fixture", "v1", 1, "abc",
                data_version="d1", classification_version="c1",
                membership_version="m1", universe_version="u1",
                adjustment_version="a1", benchmark_version="b1",
                calculation_version="calc1",
            ),
        )


class EmptySnapshotRepository:
    sector_continuity = ContinuityRepository()

    def list_snapshot_dates(self, _dataset, *, through=None):
        return ()

    def get(self, _dataset, _as_of):
        return None


def test_materialization_projects_domain_result_to_http_analysis_contract():
    support = MaterializationSupport(
        object(), now=lambda: __import__("datetime").datetime.now(),
        snapshot_ttl_seconds=30, continuity_repository=ContinuityRepository(),
    )
    payload = support._continuity_analysis(AS_OF)
    analysis = SectorAnalysis.model_validate(payload)
    assert analysis.asOf == AS_OF.isoformat()
    assert analysis.metricTraces[0].ruleId == "QTS-01-05-05"
    assert analysis.quality.asOf == AS_OF.isoformat()
    assert analysis.validation.candidateIndustry is None


def test_chapter01_separates_ths_observations_from_shenwan_analysis():
    support = MaterializationSupport(
        EmptySnapshotRepository(),
        now=lambda: datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc),
        snapshot_ttl_seconds=30,
    )
    provider_data = support.missing_chapter_provider_data(
        AS_OF,
        "fixture evidence is incomplete",
        status="missing",
    )
    chapter = support.build_chapter01(
        {
            "effectiveDate": AS_OF,
            "indices": [],
            "summary": {
                "synchronization": "数据不足",
                "dominantTrend": "数据不足",
                "warnings": [],
            },
        },
        provider_data,
    )

    validated = Chapter01Evidence.model_validate(chapter).model_dump()

    assert "sectors" not in validated
    assert validated["industryRanking"]["quality"]["dataset"] == "industry-ranking"
    assert validated["sectorTurnover"]["quality"]["dataset"] == "sector-turnover"
    assert validated["sectorBreadth"]["quality"]["dataset"] == "sector-breadth"
    assert validated["sectorAnalysis"]["asOf"] == AS_OF.isoformat()


def test_chapter01_openapi_schema_has_no_legacy_sectors_field():
    properties = Chapter01Evidence.model_json_schema()["properties"]

    assert "sectors" not in properties
    assert {
        "industryRanking",
        "sectorTurnover",
        "sectorBreadth",
        "sectorAnalysis",
    }.issubset(properties)
