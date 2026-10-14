from __future__ import annotations

from datetime import date

from src.market_environment.bootstrap.registries import (
    build_committer_registry,
    build_detail_projector_registry,
)
from src.market_environment.domain.models import DATASET_IDS, DatasetDate
from src.market_environment.infrastructure.collection import (
    EmptyDatasetDetailProjector,
    StandardSnapshotCommitter,
    ThsIndustryRankingCommitter,
    ThsIndustryRankingProjector,
    ThsSectorBreadthCommitter,
    ThsSectorBreadthProjector,
    ThsSectorTurnoverCommitter,
    ThsSectorTurnoverProjector,
)


AS_OF = date(2026, 10, 12)


def _unused_uow():
    raise AssertionError("registry construction must not open a unit of work")


def test_committer_registry_routes_ths_datasets_to_specialized_committers() -> None:
    registry = build_committer_registry(_unused_uow)

    assert registry.dataset_ids == DATASET_IDS
    assert isinstance(
        registry.get("industry-ranking"),
        ThsIndustryRankingCommitter,
    )
    assert isinstance(
        registry.get("sector-turnover"),
        ThsSectorTurnoverCommitter,
    )
    assert isinstance(
        registry.get("sector-breadth"),
        ThsSectorBreadthCommitter,
    )
    assert isinstance(registry.get("breadth"), StandardSnapshotCommitter)
    assert isinstance(registry.get("activeDirection"), StandardSnapshotCommitter)


def test_detail_projector_registry_overrides_only_the_three_ths_datasets() -> None:
    registry = build_detail_projector_registry(object(), limits_enabled=False)

    assert registry.dataset_ids == DATASET_IDS
    assert isinstance(
        registry.get("industry-ranking"),
        ThsIndustryRankingProjector,
    )
    assert isinstance(
        registry.get("sector-turnover"),
        ThsSectorTurnoverProjector,
    )
    assert isinstance(
        registry.get("sector-breadth"),
        ThsSectorBreadthProjector,
    )
    assert isinstance(registry.get("breadth"), EmptyDatasetDetailProjector)
    assert isinstance(registry.get("activeDirection"), EmptyDatasetDetailProjector)

    missing = registry.project(
        DatasetDate("industry-ranking", AS_OF),
        None,
    )
    assert missing == {
        "asOf": AS_OF.isoformat(),
        "rowCount": 0,
        "state": "missing",
        "catalogRevisionId": None,
        "catalogRevision": None,
    }
