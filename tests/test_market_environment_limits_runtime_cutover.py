from __future__ import annotations

import copy
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from src.market_environment.application.mappers import candidate_to_snapshot_fields
from src.market_environment.application.ports import LimitHistoryPreparationRequest
from src.market_environment.bootstrap.app import create_app
from src.market_environment.bootstrap.container import ContainerAdapters, build_container
from src.market_environment.bootstrap.settings import MarketEnvironmentSettings
from src.market_environment.domain.policies import LimitNormalizationResult
from src.market_environment.infrastructure.collection import (
    AcquisitionPlanCollector,
    LimitsDatasetCommitter,
    ProviderLimitHistoryPreparer,
)
from src.market_environment.infrastructure.legacy.providers import MarketDataProvider
from src.market_environment.infrastructure.providers.fuyao.limits_client import (
    FuyaoConfigurationError,
    FuyaoLimitDataset,
    FuyaoPoolResult,
)
from src.market_environment.infrastructure.providers.limits_acquisition import (
    LIMITS_RULE_VERSION,
    LimitsAcquisitionPlan,
)
from src.market_environment.limit_facts import LimitSecurityFactRecord
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import (
    LIMIT_DETAIL_CHECKSUM_KEY,
    SnapshotRecord,
    SnapshotStore,
    TradingSessionRecord,
)


AS_OF = date(2026, 9, 18)
PREVIOUS = date(2026, 9, 17)
EARLIER = date(2026, 9, 16)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=MARKET_TIME_ZONE)
UTC_NOW = NOW.astimezone(timezone.utc)


class StubFuyao:
    configured = True

    def __init__(
        self,
        dataset: FuyaoLimitDataset | dict[date, FuyaoLimitDataset] | None = None,
    ) -> None:
        self.dataset = dataset
        self.calls: list[str] = []

    def require_configured(self) -> None:
        if not self.configured:
            raise FuyaoConfigurationError(
                "MARKET_ENVIRONMENT_FUYAO_API_KEY is required"
            )

    def fetch_trading_days(self) -> tuple[date, ...]:
        self.calls.append("calendar")
        return (EARLIER, PREVIOUS, AS_OF)

    def fetch_limit_dataset(self, as_of: date, *, trading_days=None):
        self.calls.append(f"dataset:{as_of.isoformat()}")
        assert trading_days == (EARLIER, PREVIOUS, AS_OF)
        assert self.dataset is not None
        if isinstance(self.dataset, dict):
            return self.dataset[as_of]
        assert as_of == AS_OF
        return self.dataset


class MissingKeyFuyao(StubFuyao):
    configured = False


class FuyaoMarketFixture:
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


class DetailRepository:
    def __init__(self) -> None:
        self.values = []

    def put_limit_detail(self, as_of, manifest, facts) -> None:
        self.values.append((as_of, dict(manifest), tuple(facts)))


class SnapshotRepository:
    def __init__(self) -> None:
        self.candidates = []

    def put(self, candidate):
        self.candidates.append(candidate)
        return candidate


class LeaseRepository:
    def __init__(self, unit) -> None:
        self.unit = unit
        self.writer_calls = 0

    def execute_fenced(self, lease, _operation, writer, *, expected_identity=None):
        assert expected_identity.dataset == lease.dataset == "limits"
        assert expected_identity.as_of == lease.as_of
        self.writer_calls += 1
        return writer(object())


class AtomicUnitOfWork:
    def __init__(self, store: SnapshotStore) -> None:
        self.store = store
        self.limit_details = DetailRepository()
        self.snapshots = SnapshotRepository()
        self.leases = LeaseRepository(self)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        pass

    def commit(self) -> None:
        assert self.limit_details.values
        assert self.snapshots.candidates
        details = {
            as_of: (manifest, facts)
            for as_of, manifest, facts in self.limit_details.values
        }
        for candidate in self.snapshots.candidates:
            as_of = candidate.identity.as_of
            manifest, facts = details[as_of]
            normalization = LimitNormalizationResult(
                rows=facts,
                as_of=as_of,
                actual_as_of=manifest["actual_as_of"],
                source=manifest["source"],
                complete=manifest["complete"],
                warnings=manifest["warnings"],
                source_revision=manifest["source_revision"],
                rule_version=manifest["rule_version"],
                excluded=manifest["excluded"],
                membership_complete=manifest["membership_complete"],
                streak_complete=manifest["streak_complete"],
                pool_quality=manifest["pool_quality"],
                dataset_checksum=manifest["dataset_checksum"],
            ).normalized()
            snapshot = SnapshotRecord(
                **candidate_to_snapshot_fields(candidate, fetched_at=UTC_NOW)
            )
            self.store.put_limit_collection(snapshot, normalization, now=UTC_NOW)
        self.committed = True


class UnitOfWorkFactory:
    def __init__(self, store: SnapshotStore) -> None:
        self.store = store
        self.units: list[AtomicUnitOfWork] = []

    def __call__(self) -> AtomicUnitOfWork:
        unit = AtomicUnitOfWork(self.store)
        self.units.append(unit)
        return unit


def _summary_payload() -> dict:
    return {
        "limitUpCount": 2,
        "limitDownCount": 1,
        "failedLimitUpCount": 1,
        "failedLimitUpRatio": 0.3333,
        "maxStreak": 2,
        "state": "已观测",
        "quality": {
            "dataset": "limit-pools",
            "source": "fixture-summary",
            "provider": "fixture-summary",
            "status": "ok",
            "observations": 4,
            "asOf": AS_OF.isoformat(),
            "warning": None,
            "warnings": [],
        },
    }


def _fuyao_dataset(as_of: date = AS_OF) -> FuyaoLimitDataset:
    code = "600001"
    return FuyaoLimitDataset(
        as_of=as_of,
        pools={
            "limit_up": FuyaoPoolResult(
                (
                    {
                        "thscode": f"{code}.SH",
                        "ticker": code,
                        "name": "样本股份",
                        "is_st": False,
                        "is_new": False,
                        "last_price": 11,
                        "price_change_ratio_pct": 10,
                        "limit_up_time": "09:35",
                        "limit_up_reason": "fixture",
                        "continue_day_cnt": 2,
                        "seal_money": 1_000_000,
                        "max_seal_money": 2_000_000,
                    },
                ),
                1,
                1,
            ),
            "failed_limit_up": FuyaoPoolResult((), 0, 0),
            "limit_down": FuyaoPoolResult((), 0, 0),
        },
        tickers={
            f"{code}.SH": {
                "thscode": f"{code}.SH",
                "ticker": code,
                "name": "样本股份",
                "exchange": "SH",
                "list_date": "2020-01-02",
            }
        },
    )


def _install_eastmoney_pools(provider: MarketDataProvider) -> None:
    pools = {
        "getTopicZTPool": [
            {
                "m": "1",
                "c": "600001",
                "n": "样本股份",
                "board": "main",
                "is_st": False,
                "listing_days": 1000,
                "limit_regime": "pct:10",
                "close_price": 11,
                "previous_close": 10,
                "touched_limit_up": True,
                "closed_limit_up": True,
                "streak_days": 2,
            }
        ],
        "getTopicZBPool": [],
        "getTopicDTPool": [],
    }
    provider.eastmoney.get_json = lambda url, _params, **_kwargs: {
        "data": {"pool": copy.deepcopy(pools[url.rsplit("/", 1)[-1]])}
    }


def _previous_fact() -> LimitSecurityFactRecord:
    return LimitSecurityFactRecord(
        as_of=PREVIOUS,
        actual_as_of=PREVIOUS,
        security_id="SSE:600000",
        pool_type="limit_up",
        code="600000",
        exchange="SSE",
        name="前日样本",
        closed_limit_up=True,
        streak_days=1,
        eligible=True,
        source="previous-fixture",
        fetched_at=UTC_NOW,
    ).normalized()


def _seed_previous(store: SnapshotStore) -> str:
    _seed_current_session(store)
    return store.put_limit_security_facts(
        PREVIOUS,
        (_previous_fact(),),
        actual_as_of=PREVIOUS,
        source="previous-fixture",
        source_revision="previous-v1",
        rule_version=LIMITS_RULE_VERSION,
        complete=True,
        membership_complete=True,
        streak_complete=True,
        fetched_at=UTC_NOW,
    )


def _seed_current_session(store: SnapshotStore) -> None:
    store.put_trading_session(
        TradingSessionRecord(
            as_of=PREVIOUS,
            previous_as_of=EARLIER,
            is_session=True,
            source="fixture-calendar",
            actual_as_of=PREVIOUS,
            fetched_at=UTC_NOW,
        )
    )
    store.put_trading_session(
        TradingSessionRecord(
            as_of=AS_OF,
            previous_as_of=PREVIOUS,
            is_session=True,
            source="fixture-calendar",
            actual_as_of=AS_OF,
            fetched_at=UTC_NOW,
        )
    )


def _runtime_container(tmp_path, provider, *, limits_v1: bool):
    store = SnapshotStore(tmp_path / "limits-runtime.sqlite3")
    factory = UnitOfWorkFactory(store)
    settings = MarketEnvironmentSettings.from_environment(
        {
            "MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0",
            "MARKET_ENVIRONMENT_LIMITS_V1_ENABLED": "1" if limits_v1 else "0",
        }
    )
    container = build_container(
        settings,
        adapters=ContainerAdapters(
            repository=store,
            collector=provider,
            clock=lambda: NOW,
            task_executor=Executor(),
            refresh_executor=Executor(),
            timezone_repository=TimezoneRepository(),
            fuyao_adapter=FuyaoMarketFixture(),
            unit_of_work_factory=factory,
        ),
    )
    container.reads.collection.coordinator.rebuild_aggregate = (
        lambda _as_of, **_kwargs: None
    )
    return container, store, factory


def test_default_runtime_uses_limits_plan_typed_committer_and_history_preparer(
    monkeypatch,
    tmp_path,
) -> None:
    from src.market_environment.bootstrap import container as container_module

    monkeypatch.setattr(
        container_module,
        "LimitsCollector",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy LimitsCollector was constructed")
        ),
    )
    fuyao = StubFuyao(_fuyao_dataset())
    provider = MarketDataProvider(fuyao=fuyao)
    provider.fetch_chapter01_limits = lambda _as_of: copy.deepcopy(_summary_payload())

    container, store, _factory = _runtime_container(
        tmp_path,
        provider,
        limits_v1=False,
    )
    coordinator = container.reads.collection.coordinator

    assert isinstance(
        container.registries.acquisition_plans.get("limits"), LimitsAcquisitionPlan
    )
    assert isinstance(
        container.registries.collectors.get("limits"), AcquisitionPlanCollector
    )
    assert isinstance(
        container.registries.committers.get("limits"), LimitsDatasetCommitter
    )
    assert isinstance(coordinator.limit_history_preparer, ProviderLimitHistoryPreparer)
    assert fuyao.calls == []

    sessions = coordinator.prepare_limit_history(
        LimitHistoryPreparationRequest(as_of=AS_OF, count=2)
    )

    assert sessions == (PREVIOUS, AS_OF)
    assert fuyao.calls == ["calendar"]
    assert store.get_trading_session(AS_OF).previous_as_of == PREVIOUS
    container.close()


def test_legacy_summary_runtime_keeps_public_payload_and_commits_incomplete_manifest(
    tmp_path,
) -> None:
    provider = MarketDataProvider(fuyao=MissingKeyFuyao())
    calls: list[date] = []

    def summary(as_of: date) -> dict:
        calls.append(as_of)
        return copy.deepcopy(_summary_payload())

    provider.fetch_chapter01_limits = summary
    container, store, factory = _runtime_container(
        tmp_path,
        provider,
        limits_v1=False,
    )

    result = container.reads.collection.coordinator.collect(AS_OF, ("limits",))

    assert result.tasks[0].status == "success"
    assert calls == [AS_OF]
    snapshot = store.get("limits", AS_OF)
    assert snapshot is not None
    assert all(
        field not in snapshot.payload
        for field in ("securityDetails", "membershipQuality", "streakQuality", "poolQuality")
    )
    manifest = store.get_limit_security_dataset(AS_OF)
    assert manifest is not None
    assert manifest["membership_complete"] is False
    assert manifest["dataset_checksum"] == snapshot.payload["quality"][
        LIMIT_DETAIL_CHECKSUM_KEY
    ]
    assert len(factory.units) == 1
    assert factory.units[0].leases.writer_calls == 1
    assert factory.units[0].committed is True
    container.close()


def test_v1_runtime_commits_current_bundle_without_overwriting_previous_and_reads_are_provider_free(
    tmp_path,
) -> None:
    fuyao = StubFuyao(_fuyao_dataset())
    provider = MarketDataProvider(fuyao=fuyao)
    _install_eastmoney_pools(provider)
    container, store, factory = _runtime_container(
        tmp_path,
        provider,
        limits_v1=True,
    )
    previous_checksum = _seed_previous(store)
    previous_facts = store.get_limit_security_facts(PREVIOUS)

    result = container.reads.collection.coordinator.collect(AS_OF, ("limits",))

    assert result.tasks[0].status == "success"
    current_manifest = store.get_limit_security_dataset(AS_OF)
    current_facts = store.get_limit_security_facts(AS_OF)
    snapshot = store.get("limits", AS_OF)
    assert current_manifest is not None
    assert snapshot is not None
    assert len(current_facts) == 1
    assert current_manifest["dataset_checksum"] == snapshot.payload["quality"][
        LIMIT_DETAIL_CHECKSUM_KEY
    ]
    assert store.get_limit_security_dataset(PREVIOUS)["dataset_checksum"] == previous_checksum
    assert store.get_limit_security_facts(PREVIOUS) == previous_facts
    assert len(factory.units) == 1
    assert factory.units[0].leases.writer_calls == 1
    assert factory.units[0].committed is True

    def provider_call_is_forbidden(*_args, **_kwargs):
        raise AssertionError("provider called while polling local limits state")

    provider.fetch_chapter01_limits = provider_call_is_forbidden
    provider._fetch_eastmoney_limit_dataset = provider_call_is_forbidden
    provider.fuyao.fetch_trading_days = provider_call_is_forbidden
    with TestClient(create_app(overrides=container)) as client:
        run_response = client.get(
            f"/api/market-environment/collection-runs/{result.run.run_id}"
        )
        status_response = client.get(
            f"/api/market-environment/data-collection?as_of={AS_OF.isoformat()}"
        )

    assert run_response.status_code == 200
    assert run_response.json()["tasks"][0]["status"] == "success"
    assert status_response.status_code == 200
    container.close()


def test_v1_runtime_fetches_previous_before_current_and_commits_both_bundles(
    tmp_path,
) -> None:
    fuyao = StubFuyao(
        {
            PREVIOUS: _fuyao_dataset(PREVIOUS),
            AS_OF: _fuyao_dataset(AS_OF),
        }
    )
    provider = MarketDataProvider(fuyao=fuyao)
    _install_eastmoney_pools(provider)
    container, store, factory = _runtime_container(
        tmp_path,
        provider,
        limits_v1=True,
    )
    _seed_current_session(store)

    result = container.reads.collection.coordinator.collect(AS_OF, ("limits",))

    assert result.tasks[0].status == "success"
    assert fuyao.calls == [
        "calendar",
        f"dataset:{PREVIOUS.isoformat()}",
        "calendar",
        f"dataset:{AS_OF.isoformat()}",
    ]
    assert store.get_limit_security_dataset(PREVIOUS) is not None
    assert store.get_limit_security_facts(PREVIOUS)
    assert store.get("limits", PREVIOUS) is not None
    assert store.get_limit_security_dataset(AS_OF) is not None
    assert store.get_limit_security_facts(AS_OF)
    assert store.get("limits", AS_OF) is not None
    assert len(factory.units) == 1
    assert factory.units[0].leases.writer_calls == 2
    assert factory.units[0].committed is True
    container.close()


def test_v1_runtime_can_skip_previous_detail_fetch_with_typed_refresh_option(
    tmp_path,
) -> None:
    fuyao = StubFuyao(
        {
            PREVIOUS: _fuyao_dataset(PREVIOUS),
            AS_OF: _fuyao_dataset(AS_OF),
        }
    )
    provider = MarketDataProvider(fuyao=fuyao)
    _install_eastmoney_pools(provider)
    container, store, factory = _runtime_container(
        tmp_path,
        provider,
        limits_v1=True,
    )
    _seed_current_session(store)

    result = container.reads.collection.coordinator.collect(
        AS_OF,
        ("limits",),
        fetch_previous_limit_details=False,
    )

    assert result.tasks[0].status == "success"
    assert fuyao.calls == [
        "calendar",
        f"dataset:{AS_OF.isoformat()}",
    ]
    assert store.get_limit_security_dataset(PREVIOUS) is None
    assert store.get("limits", PREVIOUS) is None
    assert store.get_limit_security_dataset(AS_OF) is not None
    assert len(factory.units) == 1
    assert factory.units[0].leases.writer_calls == 1
    container.close()


def test_missing_fuyao_key_fails_before_fallback_or_unit_of_work(tmp_path) -> None:
    provider = MarketDataProvider(
        fuyao=MissingKeyFuyao(),
        require_fuyao_for_limits=True,
    )
    eastmoney_calls: list[str] = []
    provider.eastmoney.get_json = (
        lambda url, _params, **_kwargs: eastmoney_calls.append(url)
    )
    container, store, factory = _runtime_container(
        tmp_path,
        provider,
        limits_v1=True,
    )

    result = container.reads.collection.coordinator.collect(AS_OF, ("limits",))

    assert result.tasks[0].status == "failed-missing"
    assert "API_KEY" in result.tasks[0].warning
    assert eastmoney_calls == []
    assert factory.units == []
    assert store.get("limits", AS_OF) is None
    assert store.get_limit_security_dataset(AS_OF) is None
    container.close()
