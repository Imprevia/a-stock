from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.market_environment.tdx_config import (
    TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV,
    TDXConfigurationError,
    TDXDailyPackageConfig,
)
from src.market_environment.tdx_daily import (
    TDXDailyPackage,
    TDXDailyPackageClient,
    TDXDailyPackageError,
    TDXDailyPackageRow,
    TDXDailyPackageUnavailable,
    normalize_tdx_rows,
    parse_tdx_daily_package,
)
from tests.fixtures.tdx_daily import make_tdx_package
from src.market_environment.providers import MarketDataProvider
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 9, 18)
MINIMUMS = {"sh": 1, "sz": 1, "bj": 1}


class Response:
    def __init__(self, content: bytes = b"", status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        return None


def test_tdx_fallback_config_is_fail_closed_and_has_no_credentials():
    default = TDXDailyPackageConfig.from_environment({})
    assert default.fallback_enabled is False
    assert TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV not in {}

    enabled = TDXDailyPackageConfig.from_environment({TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV: "true"})
    assert enabled.fallback_enabled is True

    with pytest.raises(TDXConfigurationError):
        TDXDailyPackageConfig.from_environment({TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV: "maybe"})


def test_parse_valid_package_retains_date_identity_and_metadata():
    package = parse_tdx_daily_package(
        make_tdx_package(AS_OF),
        AS_OF,
        minimum_market_rows=MINIMUMS,
        fetched_at=datetime(2026, 9, 18, 8, tzinfo=timezone.utc),
    )

    assert len(package.rows) == 3
    assert package.requested_date == AS_OF
    assert package.source_date == AS_OF
    assert package.rows[0].previous_close == 9.0
    assert package.rows[0].change_pct == pytest.approx(11.11111111)
    assert package.metadata["marketCounts"] == {"sh": 1, "sz": 1, "bj": 1}


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"markets": ("sh", "sz", "bj"), "rows_per_market": 0}, "incomplete"),
        ({"truncated": True}, "truncated"),
        ({"duplicate_code": True, "rows_per_market": 2}, "duplicate"),
        ({"invalid_numeric": True}, "non-finite"),
    ],
)
def test_parse_rejects_malformed_packages(kwargs, expected):
    with pytest.raises(TDXDailyPackageError, match=expected):
        parse_tdx_daily_package(
            make_tdx_package(AS_OF, **kwargs),
            AS_OF,
            minimum_market_rows=MINIMUMS,
        )


def test_parse_rejects_date_conflict_and_unsupported_market():
    with pytest.raises(TDXDailyPackageError, match="conflicts"):
        parse_tdx_daily_package(
            make_tdx_package(AS_OF),
            AS_OF,
            package_date=date(2026, 9, 17),
            minimum_market_rows=MINIMUMS,
        )

    with pytest.raises(TDXDailyPackageError, match="missing the sh"):
        parse_tdx_daily_package(
            make_tdx_package(AS_OF, markets=("xx",)),
            AS_OF,
            minimum_market_rows=MINIMUMS,
        )


def test_normalization_preserves_missing_amount_and_rejects_bad_number():
    rows = normalize_tdx_rows(
        [{"code": "600000", "date": AS_OF.isoformat(), "close": 10.0}],
        AS_OF,
    )
    assert rows[0].amount is None
    with pytest.raises(TDXDailyPackageError, match="invalid amount"):
        normalize_tdx_rows(
            [{"code": "600000", "date": AS_OF.isoformat(), "close": 10.0, "amount": "bad"}],
            AS_OF,
        )


def test_client_converts_missing_http_package_to_typed_failure(monkeypatch):
    client = TDXDailyPackageClient(minimum_market_rows=MINIMUMS)
    monkeypatch.setattr(client.session, "get", lambda *_args, **_kwargs: Response(status_code=404))
    with pytest.raises(TDXDailyPackageUnavailable):
        client.fetch(AS_OF)

    monkeypatch.setattr(client.session, "get", lambda *_args, **_kwargs: Response(status_code=503))
    with pytest.raises(TDXDailyPackageError, match="HTTP status 503"):
        client.fetch(AS_OF)


def test_client_applies_download_bound_without_response_body(monkeypatch):
    client = TDXDailyPackageClient(max_bytes=1024, minimum_market_rows=MINIMUMS)
    monkeypatch.setattr(
        client.session,
        "get",
        lambda *_args, **_kwargs: Response(content=b"PK" + b"x" * 1024),
    )
    with pytest.raises(TDXDailyPackageError, match="safety bound"):
        client.fetch(AS_OF)


def _package(rows):
    return TDXDailyPackage(
        rows=tuple(rows),
        source_url="https://tdx.invalid/fixture.zip",
        requested_date=AS_OF,
        source_date=AS_OF,
        fetched_at=datetime(2026, 9, 18, 8, tzinfo=timezone.utc),
        metadata={"marketCounts": {"sh": 1, "sz": 1, "bj": 1}},
    )


class PackageClient:
    def __init__(self, package):
        self.package = package
        self.calls = []

    def fetch(self, requested_date):
        self.calls.append(requested_date)
        return self.package


def _active_package_rows(names=True, count=30, unsorted=False):
    rows = [
        TDXDailyPackageRow(
            code=f"{index:06d}",
            date=AS_OF,
            close=10.0,
            amount=30_000 - index,
            previous_close=9.0,
            change_pct=11.1111,
            name=f"样本{index}" if names else None,
            market="sz",
            high=11.0,
            low=9.0,
        )
        for index in range(count)
    ]
    if unsorted and len(rows) > 1:
        rows[1] = rows[1].__class__(**{**rows[1].__dict__, "amount": 40_000})
    return rows


def test_provider_uses_tdx_after_eastmoney_failure_and_preserves_warning(monkeypatch):
    package_client = PackageClient(_package(_active_package_rows()))
    provider = MarketDataProvider(
        tdx_daily_package=package_client,
        tdx_fallback_enabled=True,
    )

    def fail(url, _params):
        if url == provider._STOCK_SNAPSHOT_URL:
            raise RuntimeError("primary disconnected")
        raise RuntimeError("delayed unavailable")

    monkeypatch.setattr(provider.eastmoney, "get_json", fail)
    result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)

    assert package_client.calls == [AS_OF]
    assert result["quality"]["source"] == "tdx-daily-package"
    assert result["quality"]["status"] == "fallback"
    assert result["quality"]["observations"] == 30
    assert "primary disconnected" in result["quality"]["warning"]
    assert "delayed unavailable" in result["quality"]["warning"]
    assert [item["code"] for item in result["topStocks"]] == [f"{i:06d}" for i in range(10)]


def test_provider_uses_tdx_for_breadth_only_after_eastmoney_failure():
    rows = [
        TDXDailyPackageRow(
            code=f"{index:06d}",
            date=AS_OF,
            close=10.0 + index,
            amount=1000,
            previous_close=10.0,
            change_pct=value,
            name=f"样本{index}",
            market="sz",
        )
        for index, value in enumerate((1.0, -1.0, 0.0, 2.0))
    ]
    package_client = PackageClient(_package(rows))
    provider = MarketDataProvider(tdx_daily_package=package_client, tdx_fallback_enabled=True)
    provider._fetch_eastmoney_breadth_fallback = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("eastmoney unavailable")
    )

    result = provider.fetch_chapter01_breadth(AS_OF, allow_current_snapshot=True)

    assert package_client.calls == [AS_OF]
    assert result["advanceCount"] == 2
    assert result["declineCount"] == 1
    assert result["flatCount"] == 1
    assert result["quality"]["source"] == "tdx-daily-package"
    assert "eastmoney unavailable" in result["quality"]["warning"]


@pytest.mark.parametrize(
    "rows, expected",
    [
        (_active_package_rows(count=29), "at least 30"),
        (_active_package_rows(unsorted=True), "descending amount"),
        (_active_package_rows(names=False), "name is unresolved"),
    ],
)
def test_provider_rejects_invalid_tdx_active_direction_candidates(monkeypatch, rows, expected):
    package_client = PackageClient(_package(rows))
    provider = MarketDataProvider(tdx_daily_package=package_client, tdx_fallback_enabled=True)
    if any(row.name is None for row in rows):
        monkeypatch.setattr(provider, "_fetch_tencent_names", lambda _rows: {})

    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(RuntimeError("eastmoney unavailable")),
    )
    result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)

    assert result["state"] == "insufficient"
    assert result["topStocks"] == []
    assert result["quality"]["status"] == "failed"
    assert expected in result["quality"]["warning"]


def test_provider_does_not_call_tdx_when_feature_is_disabled(monkeypatch):
    package_client = PackageClient(_package(_active_package_rows()))
    provider = MarketDataProvider(tdx_daily_package=package_client, tdx_fallback_enabled=False)
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(RuntimeError("eastmoney unavailable")),
    )

    result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)

    assert package_client.calls == []
    assert result["quality"]["source"] == "eastmoney-clist"


def test_provider_resolves_only_names_from_batched_tencent_lookup(monkeypatch):
    rows = _active_package_rows(names=False)
    package_client = PackageClient(_package(rows))
    provider = MarketDataProvider(tdx_daily_package=package_client, tdx_fallback_enabled=True)
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(RuntimeError("eastmoney unavailable")),
    )
    monkeypatch.setattr(provider, "_fetch_tencent_names", lambda _rows: {row.code: f"腾讯名{row.code}" for row in rows})

    result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)

    assert result["quality"]["source"] == "tdx-daily-package"
    assert result["topStocks"][0]["name"] == "腾讯名000000"
    assert result["topStocks"][0]["amount"] == 30_000
    assert result["topStocks"][0]["changePct"] == pytest.approx(11.1111)


def test_breadth_uses_only_exact_previous_session_when_package_lacks_change_fields():
    current_rows = [
        TDXDailyPackageRow(
            code=f"{index:06d}",
            date=AS_OF,
            close=close,
            amount=1000,
            name=f"样本{index}",
            market="sz",
        )
        for index, close in enumerate((11.0, 9.0, 10.0))
    ]
    previous_date = date(2026, 9, 17)
    previous_rows = [
        TDXDailyPackageRow(
            code=f"{index:06d}",
            date=previous_date,
            close=10.0,
            amount=900,
            name=f"样本{index}",
            market="sz",
        )
        for index in range(3)
    ]

    class TwoDayClient:
        def __init__(self):
            self.calls = []

        def fetch(self, requested_date):
            self.calls.append(requested_date)
            return TDXDailyPackage(
                rows=tuple(current_rows if requested_date == AS_OF else previous_rows),
                source_url="https://tdx.invalid/fixture.zip",
                requested_date=requested_date,
                source_date=requested_date,
                fetched_at=datetime(2026, 9, 18, 8, tzinfo=timezone.utc),
                metadata={"marketCounts": {"sh": 1, "sz": 1, "bj": 1}},
            )

    client = TwoDayClient()
    provider = MarketDataProvider(
        tdx_daily_package=client,
        tdx_fallback_enabled=True,
        tdx_trading_days=lambda: (previous_date, AS_OF),
    )
    provider._fetch_eastmoney_breadth_fallback = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("eastmoney unavailable")
    )

    result = provider.fetch_chapter01_breadth(AS_OF, allow_current_snapshot=True)

    assert client.calls == [AS_OF, previous_date]
    assert result["advanceCount"] == 1
    assert result["declineCount"] == 1
    assert result["flatCount"] == 1
    assert result["medianReturn"] == 0.0


def test_collection_writes_breadth_and_active_direction_independently_from_tdx(tmp_path, monkeypatch):
    package_client = PackageClient(_package(_active_package_rows()))
    provider = MarketDataProvider(tdx_daily_package=package_client, tdx_fallback_enabled=True)
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_breadth_fallback",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("breadth eastmoney unavailable")),
    )
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(RuntimeError("active eastmoney unavailable")),
    )
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: datetime(2026, 9, 18, 15, 20, tzinfo=MARKET_TIME_ZONE),
    ).collect(AS_OF, ["breadth", "activeDirection"])

    assert result.run.status == "success"
    assert {task.dataset for task in result.tasks} == {"breadth", "activeDirection"}
    assert store.get("breadth", AS_OF).source == "tdx-daily-package"
    assert store.get("activeDirection", AS_OF).source == "tdx-daily-package"
    assert package_client.calls == [AS_OF, AS_OF]


def test_collection_retains_same_date_snapshot_when_tdx_fallback_fails(tmp_path, monkeypatch):
    class FailingClient:
        def fetch(self, requested_date):
            raise TDXDailyPackageUnavailable("not published")

    provider = MarketDataProvider(tdx_daily_package=FailingClient(), tdx_fallback_enabled=True)
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(RuntimeError("eastmoney unavailable")),
    )
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="activeDirection",
            as_of=AS_OF,
            payload={"state": "candidate", "summary": "old", "topStocks": [], "quality": {}},
            source="old",
            status="partial",
            observations=30,
            warnings=(),
            fetched_at=datetime(2026, 9, 17, 15, 20, tzinfo=MARKET_TIME_ZONE),
            settled=True,
        )
    )

    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: datetime(2026, 9, 18, 15, 20, tzinfo=MARKET_TIME_ZONE),
    ).collect(AS_OF, ["activeDirection"])

    assert result.tasks[0].status == "failed-retained"
    assert store.get("activeDirection", AS_OF).source == "old"
    assert "通达信盘后包" in store.get("activeDirection", AS_OF).refresh_warning
