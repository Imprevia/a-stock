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


def test_chapter01_materializes_partial_ths_quality_and_row_lineage():
    support = MaterializationSupport(
        EmptySnapshotRepository(),
        now=lambda: datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc),
        snapshot_ttl_seconds=30,
    )
    provider_data = support.missing_chapter_provider_data(
        AS_OF,
        "partial THS fixture",
        status="partial",
    )
    provider_data["industry-ranking"] = {
        "rows": [
            {
                "tag": "industry",
                "rank": 1,
                "thscode": "883001.TI",
                "name": "样本行业",
                "changePct": None,
                "catalogRevision": "catalog-fixture-r1",
                "asOf": AS_OF.isoformat(),
                "quality": "insufficient",
                "warnings": ["当日行情缺失"],
            }
        ],
        "state": "partial",
        "catalogRevisionId": "catalog-fixture-r1",
        "quality": {
            "dataset": "industry-ranking",
            "source": "fuyao-ths",
            "provider": "fuyao",
            "status": "partial",
            "observations": 1,
            "asOf": AS_OF.isoformat(),
            "warnings": ["当日行情缺失"],
            "catalogRevisionId": "catalog-fixture-r1",
            "expectedCount": 4,
            "observedCount": 4,
            "rankableCount": 3,
            "barCount": 2,
            "missingLiveCount": 2,
            "missingLiveCodes": ["883001.TI", "883002.TI"],
            "missingRankingCount": 1,
            "missingRankingCodes": ["883001.TI"],
        },
    }
    provider_data["sector-turnover"] = {
        "rows": [],
        "state": "partial",
        "catalogRevisionId": "catalog-fixture-r1",
        "quality": {
            "dataset": "sector-turnover",
            "source": "local-ths-normalized",
            "provider": "local-postgresql",
            "status": "partial",
            "observations": 0,
            "asOf": AS_OF.isoformat(),
            "warnings": ["部分行情缺失"],
            "catalogRevisionId": "catalog-fixture-r1",
            "expectedCount": 4,
            "observedCount": 2,
            "rankableCount": 3,
            "barCount": 2,
            "missingLiveCount": 2,
            "missingLiveCodes": ["883001.TI", "883002.TI"],
            "missingRankingCount": 1,
            "missingRankingCodes": ["883001.TI"],
        },
    }

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

    ranking = validated["industryRanking"]
    assert ranking["catalogRevisionId"] == "catalog-fixture-r1"
    assert ranking["quality"]["catalogRevisionId"] == "catalog-fixture-r1"
    assert ranking["quality"]["expectedCount"] == 4
    assert ranking["quality"]["observedCount"] == 4
    assert ranking["quality"]["rankableCount"] == 3
    assert ranking["quality"]["barCount"] == 2
    assert ranking["quality"]["missingLiveCount"] == 2
    assert ranking["quality"]["missingRankingCount"] == 1
    assert ranking["quality"]["missingLiveCodes"] == ["883001.TI", "883002.TI"]
    assert ranking["rows"][0]["catalogRevisionId"] == "catalog-fixture-r1"
    assert ranking["rows"][0]["changePct"] is None
    assert ranking["rows"][0]["quality"] == "insufficient"
    assert ranking["rows"][0]["warnings"] == ["当日行情缺失"]

    turnover = validated["sectorTurnover"]
    assert turnover["catalogRevisionId"] == "catalog-fixture-r1"
    assert turnover["quality"]["expectedCount"] == 4
    assert turnover["quality"]["barCount"] == 2
    assert turnover["quality"]["missingLiveCount"] == 2
    assert turnover["quality"]["missingLiveCodes"] == ["883001.TI", "883002.TI"]


def test_chapter01_openapi_schema_has_no_legacy_sectors_field():
    properties = Chapter01Evidence.model_json_schema()["properties"]

    assert "sectors" not in properties
    assert {
        "industryRanking",
        "sectorTurnover",
        "sectorBreadth",
        "sectorAnalysis",
    }.issubset(properties)
