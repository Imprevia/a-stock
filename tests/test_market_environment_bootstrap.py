from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import date, datetime, time, timezone

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from src.market_environment.bootstrap.app import create_app
from src.market_environment.bootstrap.settings import (
    MarketEnvironmentSettings,
    SettingsConfigurationError,
)
from src.market_environment.bootstrap.container import (
    ContainerAdapters,
    build_container,
)
from src.market_environment.domain.models import DATASET_IDS
from src.market_environment.infrastructure.collection import AcquisitionPlanCollector
from src.market_environment.infrastructure.providers.breadth_acquisition import (
    EASTMONEY_BREADTH_SOURCE_ID,
    FUYAO_BREADTH_SOURCE_ID,
    TDX_BREADTH_SOURCE_ID,
)
from src.market_environment.infrastructure.providers.core_acquisition import (
    BAIDU_CORE_HISTORY_SOURCE_ID,
    EASTMONEY_CORE_HISTORY_SOURCE_ID,
    FUYAO_CORE_HISTORY_SOURCE_ID,
    MOOTDX_CORE_HISTORY_SOURCE_ID,
    SINA_CORE_HISTORY_SOURCE_ID,
    TENCENT_CORE_HISTORY_SOURCE_ID,
    TENCENT_CORE_QUOTE_SOURCE_ID,
)
from src.market_environment.infrastructure.providers.limits_acquisition import (
    EASTMONEY_LIMITS_SOURCE_ID,
    FUYAO_LIMITS_SOURCE_ID,
    LEGACY_LIMITS_SUMMARY_SOURCE_ID,
    LimitsAcquisitionPlan,
)
from src.market_environment.infrastructure.providers.fuyao.market import (
    FuyaoMarketAdapter,
)
from src.market_environment.interfaces.cli.container import CliContainer


def test_layer_package_skeleton_imports_without_runtime_construction() -> None:
    script = """
import importlib
import json
import sys

modules = [
    'src.market_environment.bootstrap',
    'src.market_environment.interfaces',
    'src.market_environment.interfaces.http',
    'src.market_environment.interfaces.http.routers',
    'src.market_environment.interfaces.http.schemas',
    'src.market_environment.interfaces.cli',
    'src.market_environment.application',
    'src.market_environment.application.ports',
    'src.market_environment.application.queries',
    'src.market_environment.application.commands',
    'src.market_environment.application.collection',
    'src.market_environment.domain',
    'src.market_environment.domain.models',
    'src.market_environment.domain.analysis',
    'src.market_environment.domain.policies',
    'src.market_environment.infrastructure',
    'src.market_environment.infrastructure.persistence',
    'src.market_environment.infrastructure.persistence.postgres',
    'src.market_environment.infrastructure.persistence.sqlite_import',
    'src.market_environment.infrastructure.providers',
    'src.market_environment.infrastructure.execution',
]
for name in modules:
    importlib.import_module(name)

for forbidden in (
    'src.market_environment.api',
    'src.market_environment.snapshot_store',
    'src.market_environment.providers',
    'src.market_environment.collection',
):
    assert forbidden not in sys.modules, forbidden

print(json.dumps({'imported': len(modules), 'runtime_modules': []}))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {"imported": 21, "runtime_modules": []}


def test_top_level_settings_are_immutable_and_side_effect_free() -> None:
    settings = MarketEnvironmentSettings.from_environment(
        {
            "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED": "0",
            "MARKET_ENVIRONMENT_PERSISTENT_CACHE": "1",
            "MARKET_ENVIRONMENT_LIMITS_V1_ENABLED": "0",
            "MARKET_ENVIRONMENT_SETTLEMENT_TIME": "15:20",
            "MARKET_ENVIRONMENT_OPEN_TIME": "09:31",
            "MARKET_ENVIRONMENT_COLLECTION_WORKERS": "3",
        },
        require_database=False,
    )

    assert settings.database is None
    assert settings.settlement_time == time(15, 20)
    assert settings.open_time == time(9, 31)
    assert settings.manual_refresh_enabled is False
    assert settings.persistent_cache_enabled is True
    assert settings.limits_v1_enabled is False
    assert settings.sector_enrichment_enabled is False
    assert settings.collection_workers == 3
    assert all(not item.enabled for item in settings.fuyao.datasets.values())
    assert settings.tdx.fallback_enabled is False

    with pytest.raises(FrozenInstanceError):
        settings.collection_workers = 4


def test_top_level_settings_require_explicit_sector_enrichment_opt_in() -> None:
    settings = MarketEnvironmentSettings.from_environment(
        {"MARKET_ENVIRONMENT_EASTMONEY_SECTOR_ENRICHMENT_ENABLED": "1"},
        require_database=False,
    )

    assert settings.sector_enrichment_enabled is True


def test_top_level_settings_compose_postgresql_without_connecting() -> None:
    settings = MarketEnvironmentSettings.from_environment(
        {
            "MARKET_ENVIRONMENT_DATABASE_URL": "postgresql+psycopg://user:pass@db/market",
            "MARKET_ENVIRONMENT_DB_POOL_SIZE": "7",
            "MARKET_ENVIRONMENT_DB_MAX_OVERFLOW": "1",
            "MARKET_ENVIRONMENT_DB_POOL_TIMEOUT": "8",
            "MARKET_ENVIRONMENT_DB_STATEMENT_TIMEOUT_MS": "45000",
        },
        require_database=True,
    )

    assert settings.database is not None
    assert settings.database.url == "postgresql+psycopg://user:pass@db/market"
    assert settings.database.pool_size == 7
    assert settings.database.max_overflow == 1
    assert settings.database.pool_timeout == 8
    assert settings.database.statement_timeout_ms == 45000


class _FakeResource:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeRepository(_FakeResource):
    path = None


class _FakeCollector(_FakeResource):
    pass


class _FakeFuyaoAdapter(_FakeResource):
    pass


class _FakeTimezoneRepository(_FakeResource):
    def get(self, *args, **kwargs):
        return (args, kwargs)

    def set(self, *args, **kwargs):
        return (args, kwargs)


class _FakeExecutor:
    def __init__(self) -> None:
        self.submissions = []
        self.closed = False

    def submit(self, function, *args):
        self.submissions.append((function, args))

    def shutdown(self, *, wait=True, cancel_futures=False) -> None:
        self.closed = True


def test_container_builds_from_fake_repository_collector_clock_and_executors() -> None:
    repository = _FakeRepository()
    collector = _FakeCollector()
    fuyao_adapter = _FakeFuyaoAdapter()
    timezone_repository = _FakeTimezoneRepository()
    task_executor = _FakeExecutor()
    refresh_executor = _FakeExecutor()
    current = datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc)
    settings = MarketEnvironmentSettings.from_environment(
        {"MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0"}
    )

    container = build_container(
        settings,
        adapters=ContainerAdapters(
            repository=repository,
            collector=collector,
            clock=lambda: current,
            monotonic_clock=lambda: 123.0,
            task_executor=task_executor,
            refresh_executor=refresh_executor,
            timezone_repository=timezone_repository,
            fuyao_adapter=fuyao_adapter,
        ),
    )

    assert container.reads.clock() == current
    assert container.reads.market_environment.store is repository
    assert container.reads.collection.coordinator.provider is collector
    assert container.commands.collection.executor is task_executor
    assert not hasattr(container.reads, "task_executor")
    assert not hasattr(container.commands, "market_environment")
    assert task_executor.submissions == []
    assert refresh_executor.submissions == []

    container.close()

    assert repository.closed is True
    assert collector.closed is True
    assert fuyao_adapter.closed is True
    assert timezone_repository.closed is True
    assert task_executor.closed is True
    assert refresh_executor.closed is True


def test_container_and_cli_expose_complete_shared_runtime_registries() -> None:
    repository = _FakeRepository()
    timezone_repository = _FakeTimezoneRepository()
    task_executor = _FakeExecutor()
    refresh_executor = _FakeExecutor()
    container = build_container(
        MarketEnvironmentSettings.from_environment(
            {"MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0"}
        ),
        adapters=ContainerAdapters(
            repository=repository,
            task_executor=task_executor,
            refresh_executor=refresh_executor,
            timezone_repository=timezone_repository,
            fuyao_adapter=_FakeFuyaoAdapter(),
        ),
    )
    cli = CliContainer(container)
    coordinator = container.reads.collection.coordinator

    assert container.registries.collectors.dataset_ids == DATASET_IDS
    assert container.registries.acquisition_plans.dataset_ids == DATASET_IDS
    assert container.registries.committers.dataset_ids == DATASET_IDS
    assert container.registries.detail_projectors.dataset_ids == DATASET_IDS
    assert tuple(
        adapter.capability.source_id
        for adapter in container.registries.source_adapters
    ) == (
        TENCENT_CORE_QUOTE_SOURCE_ID,
        FUYAO_CORE_HISTORY_SOURCE_ID,
        MOOTDX_CORE_HISTORY_SOURCE_ID,
        BAIDU_CORE_HISTORY_SOURCE_ID,
        SINA_CORE_HISTORY_SOURCE_ID,
        TENCENT_CORE_HISTORY_SOURCE_ID,
        EASTMONEY_CORE_HISTORY_SOURCE_ID,
        FUYAO_BREADTH_SOURCE_ID,
        TDX_BREADTH_SOURCE_ID,
        EASTMONEY_BREADTH_SOURCE_ID,
        FUYAO_LIMITS_SOURCE_ID,
        EASTMONEY_LIMITS_SOURCE_ID,
        LEGACY_LIMITS_SUMMARY_SOURCE_ID,
        "sectors-eastmoney-clist",
        "sectors-eastmoney-clist-delay",
        "sectors-fuyao",
        "sectors-eastmoney-dataapi-enrichment",
        "active-direction-eastmoney-primary",
        "active-direction-eastmoney-delayed",
        "active-direction-tdx-derived",
    )
    assert container.registries.transport_engines.names == ("requests",)
    assert (
        container.registries.transport_policy_gateway.engine_registry
        is container.registries.transport_engines
    )
    assert (
        container.registries.transport_policy_gateway.policy_for(
            "www.tdx.com.cn"
        ).request_budget
        == 20
    )
    assert (
        container.registries.transport_policy_gateway.policy_for(
            "fuyao.aicubes.cn"
        ).request_budget
        == 120
    )
    assert coordinator.collector_registry is container.registries.collectors
    assert coordinator.detail_projector_registry is container.registries.detail_projectors
    assert coordinator.provider.http.gateway is container.registries.transport_policy_gateway
    assert (
        coordinator.provider.fuyao._transport_gateway
        is container.registries.transport_policy_gateway
    )
    assert coordinator.typed_cutover_datasets == frozenset(DATASET_IDS)
    assert isinstance(
        container.registries.collectors.get("breadth"),
        AcquisitionPlanCollector,
    )
    assert all(
        isinstance(
            container.registries.collectors.get(dataset),
            AcquisitionPlanCollector,
        )
        for dataset in DATASET_IDS
    )
    assert cli.registries is container.registries
    assert isinstance(
        container.registries.acquisition_plans.get("limits"),
        LimitsAcquisitionPlan,
    )

    cli.close()


def test_default_fuyao_clients_share_the_composition_root_gateway() -> None:
    container = build_container(
        MarketEnvironmentSettings.from_environment(
            {"MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0"}
        ),
        adapters=ContainerAdapters(
            repository=_FakeRepository(),
            task_executor=_FakeExecutor(),
            refresh_executor=_FakeExecutor(),
            timezone_repository=_FakeTimezoneRepository(),
        ),
    )
    coordinator = container.reads.collection.coordinator
    fuyao_adapter = next(
        resource
        for resource in container.resources
        if isinstance(resource, FuyaoMarketAdapter)
    )

    assert (
        coordinator.provider.fuyao._transport_gateway
        is container.registries.transport_policy_gateway
    )
    assert (
        fuyao_adapter.client._transport_gateway
        is container.registries.transport_policy_gateway
    )

    container.close()


def test_postgresql_runtime_composition_performs_no_startup_io(monkeypatch) -> None:
    import sqlalchemy.engine

    from src.market_environment.infrastructure.legacy import snapshot_store as store_module
    from src.market_environment import timezone_preferences as timezone_module

    def fail(*_args, **_kwargs):
        raise AssertionError("runtime composition attempted startup I/O")

    monkeypatch.setattr(store_module, "create_schema", fail)
    monkeypatch.setattr(timezone_module, "create_schema", fail)
    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", fail)
    monkeypatch.setattr("requests.sessions.Session.request", fail)

    settings = MarketEnvironmentSettings.from_environment(
        {
            "MARKET_ENVIRONMENT_DATABASE_URL": (
                "postgresql+psycopg://user:pass@db/market"
            ),
            "MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0",
        },
        require_database=True,
    )
    container = build_container(
        settings,
        adapters=ContainerAdapters(
            task_executor=_FakeExecutor(),
            refresh_executor=_FakeExecutor(),
        ),
    )

    assert container.registries.transport_engines.names == ("requests",)
    assert not any(
        name == "scrapling" or name.startswith("scrapling.") for name in sys.modules
    )
    container.close()


def test_normal_runtime_without_postgresql_configuration_fails_closed() -> None:
    settings = MarketEnvironmentSettings.from_environment(
        {"MARKET_ENVIRONMENT_PERSISTENT_CACHE": "1"}
    )

    with pytest.raises(
        SettingsConfigurationError,
        match="MARKET_ENVIRONMENT_DATABASE_URL",
    ):
        build_container(settings)


def test_api_entrypoint_import_performs_no_runtime_construction(tmp_path) -> None:
    snapshot_path = tmp_path / "must-not-exist.sqlite3"
    script = """
import importlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import src.market_environment.bootstrap.container as container_module
import src.market_environment.providers as providers_module
import src.market_environment.service as service_module
import src.market_environment.snapshot_store as store_module

target = Path(os.environ['IMPORT_GUARD_SNAPSHOT'])
with (
    patch.object(container_module, 'build_container', side_effect=AssertionError('container built during import')),
    patch.object(providers_module.MarketDataProvider, '__init__', side_effect=AssertionError('provider built during import')),
    patch.object(store_module.SnapshotStore, '__init__', side_effect=AssertionError('store built during import')),
    patch.object(store_module, 'create_schema', side_effect=AssertionError('schema created during import')),
    patch.object(service_module.ThreadPoolExecutor, '__init__', side_effect=AssertionError('executor built during import')),
    patch.object(container_module.ThreadPoolExecutor, '__init__', side_effect=AssertionError('executor built during import')),
):
    module = importlib.import_module('src.market_environment.api')

assert module.app is not None
assert not target.exists()
print(json.dumps({'app': True, 'snapshotCreated': False}))
"""
    env = dict(os.environ)
    env["IMPORT_GUARD_SNAPSHOT"] = str(snapshot_path)
    env["MARKET_ENVIRONMENT_SNAPSHOT_PATH"] = str(snapshot_path)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert json.loads(completed.stdout) == {
        "app": True,
        "snapshotCreated": False,
    }


def test_documented_uvicorn_target_imports_offline(tmp_path) -> None:
    snapshot_path = tmp_path / "uvicorn-import-must-not-exist.sqlite3"
    script = """
import json
import os
from pathlib import Path
from uvicorn.importer import import_from_string

target = Path(os.environ['IMPORT_GUARD_SNAPSHOT'])
app = import_from_string('src.market_environment.api:app')
assert app is not None
assert not target.exists()
print(json.dumps({'target': 'src.market_environment.api:app', 'snapshotCreated': False}))
"""
    env = dict(os.environ)
    env["IMPORT_GUARD_SNAPSHOT"] = str(snapshot_path)
    env["MARKET_ENVIRONMENT_SNAPSHOT_PATH"] = str(snapshot_path)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert json.loads(completed.stdout) == {
        "target": "src.market_environment.api:app",
        "snapshotCreated": False,
    }


def test_create_app_lifespan_owns_container_shutdown() -> None:
    repository = _FakeRepository()
    collector = _FakeCollector()
    fuyao_adapter = _FakeFuyaoAdapter()
    timezone_repository = _FakeTimezoneRepository()
    task_executor = _FakeExecutor()
    refresh_executor = _FakeExecutor()
    container = build_container(
        MarketEnvironmentSettings.from_environment(
            {"MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0"}
        ),
        adapters=ContainerAdapters(
            repository=repository,
            collector=collector,
            task_executor=task_executor,
            refresh_executor=refresh_executor,
            timezone_repository=timezone_repository,
            fuyao_adapter=fuyao_adapter,
        ),
    )
    app = create_app(overrides=container, router=APIRouter())

    with TestClient(app):
        assert app.state.container is container
        assert task_executor.closed is False
        assert refresh_executor.closed is False

    assert repository.closed is True
    assert collector.closed is True
    assert fuyao_adapter.closed is True
    assert timezone_repository.closed is True
    assert task_executor.closed is True
    assert refresh_executor.closed is True


def test_create_app_shutdown_disposes_database_engine() -> None:
    class FakeEngine:
        def __init__(self) -> None:
            self.disposed = False

        def dispose(self) -> None:
            self.disposed = True

    class FakeDatabaseRepository:
        path = None

        def __init__(self) -> None:
            self.engine = FakeEngine()

    repository = FakeDatabaseRepository()
    task_executor = _FakeExecutor()
    refresh_executor = _FakeExecutor()
    container = build_container(
        MarketEnvironmentSettings.from_environment(
            {"MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0"}
        ),
        adapters=ContainerAdapters(
            repository=repository,
            collector=_FakeCollector(),
            task_executor=task_executor,
            refresh_executor=refresh_executor,
            timezone_repository=_FakeTimezoneRepository(),
            fuyao_adapter=_FakeFuyaoAdapter(),
        ),
    )
    app = create_app(overrides=container, router=APIRouter())

    with TestClient(app):
        assert repository.engine.disposed is False

    assert repository.engine.disposed is True
    assert task_executor.closed is True
    assert refresh_executor.closed is True
