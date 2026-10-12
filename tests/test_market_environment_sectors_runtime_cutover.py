from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from src.market_environment.bootstrap.app import create_app
from src.market_environment.bootstrap.container import ContainerAdapters, build_container
from src.market_environment.bootstrap.settings import MarketEnvironmentSettings
from src.market_environment.domain.models import DATASET_IDS
from src.market_environment.infrastructure.collection import (
    ThsIndustryRankingCollector,
    ThsIndustryRankingCommitter,
    ThsIndustryRankingProjector,
    ThsSectorBreadthCollector,
    ThsSectorBreadthCommitter,
    ThsSectorBreadthProjector,
    ThsSectorTurnoverCollector,
    ThsSectorTurnoverCommitter,
    ThsSectorTurnoverProjector,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 9, 18)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=MARKET_TIME_ZONE)
THS_DATASETS = ("industry-ranking", "sector-turnover", "sector-breadth")


class RuntimeProvider:
    def __init__(self) -> None:
        self.calls = 0

    def __getattr__(self, _name: str):
        def unexpected_provider_call(*_args, **_kwargs):
            self.calls += 1
            raise AssertionError("provider I/O is forbidden in runtime cutover checks")

        return unexpected_provider_call

    def close(self) -> None:
        pass

    def shutdown(self, *, wait=True, cancel_futures=False) -> None:
        pass


class FuyaoClient:
    def close(self) -> None:
        pass


class TimezoneRepository:
    def get(self, *_args, **_kwargs):
        return None

    def set(self, *_args, **_kwargs):
        return None

    def close(self) -> None:
        pass


class Executor:
    def submit(self, function, *args):
        return function(*args)

    def shutdown(self, *, wait=True, cancel_futures=False) -> None:
        pass


class UnusedUnitOfWorkFactory:
    def __call__(self):
        raise AssertionError("unit of work must not open during composition or local polling")


def _legacy_sector_snapshot() -> SnapshotRecord:
    return SnapshotRecord(
        dataset="sectors",
        as_of=AS_OF,
        payload={
            "rows": [{"code": "BK001", "name": "legacy fixture"}],
            "quality": {
                "dataset": "sectors",
                "source": "legacy-fixture",
                "status": "ok",
                "observations": 1,
                "asOf": AS_OF.isoformat(),
                "warnings": [],
            },
        },
        source="legacy-fixture",
        status="ok",
        observations=1,
        warnings=(),
        fetched_at=NOW,
        settled=True,
    )


def _runtime_container(tmp_path):
    store = SnapshotStore(tmp_path / "ths-runtime-cutover.sqlite3")
    legacy_snapshot = store.put(_legacy_sector_snapshot())
    provider = RuntimeProvider()
    container = build_container(
        MarketEnvironmentSettings.from_environment(
            {"MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0"}
        ),
        adapters=ContainerAdapters(
            repository=store,
            collector=provider,
            clock=lambda: NOW,
            task_executor=Executor(),
            refresh_executor=Executor(),
            timezone_repository=TimezoneRepository(),
            fuyao_adapter=FuyaoClient(),
            unit_of_work_factory=UnusedUnitOfWorkFactory(),
        ),
    )
    return container, store, provider, legacy_snapshot


def test_default_runtime_exposes_three_typed_ths_dataset_boundaries(tmp_path) -> None:
    container, _store, provider, _legacy_snapshot = _runtime_container(tmp_path)
    coordinator = container.reads.collection.coordinator

    assert DATASET_IDS == (
        "core",
        "breadth",
        "limits",
        "industry-ranking",
        "sector-turnover",
        "sector-breadth",
        "activeDirection",
    )
    assert coordinator.typed_cutover_datasets == frozenset(DATASET_IDS)
    assert [
        type(container.registries.collectors.get(dataset)) for dataset in THS_DATASETS
    ] == [
        ThsIndustryRankingCollector,
        ThsSectorTurnoverCollector,
        ThsSectorBreadthCollector,
    ]
    assert [
        type(container.registries.committers.get(dataset)) for dataset in THS_DATASETS
    ] == [
        ThsIndustryRankingCommitter,
        ThsSectorTurnoverCommitter,
        ThsSectorBreadthCommitter,
    ]
    assert [
        type(container.registries.detail_projectors.get(dataset))
        for dataset in THS_DATASETS
    ] == [
        ThsIndustryRankingProjector,
        ThsSectorTurnoverProjector,
        ThsSectorBreadthProjector,
    ]
    assert provider.calls == 0
    container.close()


def test_runtime_rejects_public_sectors_and_retains_legacy_snapshot(tmp_path) -> None:
    container, store, provider, legacy_snapshot = _runtime_container(tmp_path)
    coordinator = container.reads.collection.coordinator

    with pytest.raises(
        ValueError,
        match=(
            "unsupported collection dataset: sectors; use industry-ranking, "
            "sector-turnover, or sector-breadth"
        ),
    ):
        coordinator.collect(AS_OF, ("sectors",))

    with TestClient(create_app(overrides=container)) as client:
        rejected = client.post(
            "/api/market-environment/collection-runs",
            json={"asOf": AS_OF.isoformat(), "datasets": ["sectors"]},
        )
        status = client.get(
            f"/api/market-environment/data-collection?as_of={AS_OF.isoformat()}"
        )

    assert rejected.status_code == 422
    assert "sectors" in rejected.text
    assert status.status_code == 200
    assert [item["dataset"] for item in status.json()["datasets"]] == list(DATASET_IDS)
    assert store.get("sectors", AS_OF) == legacy_snapshot
    assert provider.calls == 0
    container.close()
