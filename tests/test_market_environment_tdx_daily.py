from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.market_environment.tdx_config import (
    TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV,
    TDX_DERIVED_ACTIVE_DIRECTION_ENABLED_ENV,
    TDXConfigurationError,
    TDXDailyPackageConfig,
)
from src.market_environment.tdx_daily import (
    TDXDailyPackage,
    TDXDailyPackageClient,
    TDXDailyPackageError,
    TDXDailyPackageRow,
    TDXDailyPackageUnavailable,
    TDXStockUniverseError,
    classify_tdx_stock_universe,
    normalize_tdx_rows,
    parse_tdx_daily_package,
    validate_tdx_stock_universe,
)
from tests.fixtures.tdx_daily import make_tdx_package
from src.market_environment.providers import MarketDataProvider
from src.market_environment.industry_mapping import VersionedIndustryMapper
from src.market_environment.collection import CollectionCoordinator
from src.market_environment import cli as market_cli
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.schemas import ActiveDirectionEvidence, BreadthEvidence
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
    assert default.derived_active_direction_enabled is False
    assert TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV not in {}

    enabled = TDXDailyPackageConfig.from_environment({TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV: "true"})
    assert enabled.fallback_enabled is True
    assert enabled.derived_active_direction_enabled is False

    derived = TDXDailyPackageConfig.from_environment(
        {TDX_DERIVED_ACTIVE_DIRECTION_ENABLED_ENV: "ON"}
    )
    assert derived.derived_active_direction_enabled is True

    with pytest.raises(TDXConfigurationError):
        TDXDailyPackageConfig.from_environment({TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV: "maybe"})
    with pytest.raises(TDXConfigurationError):
        TDXDailyPackageConfig.from_environment({TDX_DERIVED_ACTIVE_DIRECTION_ENABLED_ENV: "maybe"})


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


def _universe_row(code: str, market: str, *, session: date = AS_OF) -> TDXDailyPackageRow:
    return TDXDailyPackageRow(
        code=code,
        date=session,
        close=10.0,
        amount=1000.0,
        previous_close=9.0,
        change_pct=11.1111,
        name=f"样本{code}",
        market=market,
    )


def test_tdx_stock_universe_filters_mixed_securities_and_records_reasons():
    rows = (
        _universe_row("600000", "sh"),
        _universe_row("688001", "sh"),
        _universe_row("000001", "sz"),
        _universe_row("300001", "sz"),
        _universe_row("430001", "bj"),
        _universe_row("920001", "bj"),
        _universe_row("510000", "sh"),
        _universe_row("110000", "sh"),
        _universe_row("399001", "sz"),
        _universe_row("030001", "sz"),
        _universe_row("200001", "sz"),
        _universe_row("450001", "sz"),
    )

    result = classify_tdx_stock_universe(rows, AS_OF)

    assert [row.code for row in result.rows] == [
        "600000",
        "688001",
        "000001",
        "300001",
        "430001",
        "920001",
    ]
    assert result.raw_count == 12
    assert result.retained_count == 6
    assert result.excluded_count == 5
    assert result.unclassified_count == 1
    assert result.retained_by_market == {"sh": 2, "sz": 2, "bj": 2}
    assert result.excluded_by_reason == {
        "fund": 1,
        "bond": 1,
        "index": 1,
        "warrant": 1,
        "b-share": 1,
    }
    assert result.unclassified_by_reason == {"unrecognized-code-range": 1}
    assert result.metadata()["stockUniversePolicyVersion"] == "tdx-stock-universe-v1"
    assert classify_tdx_stock_universe(rows, AS_OF).metadata() == result.metadata()


def test_tdx_stock_universe_applies_bj_920_effective_date():
    before = date(2025, 10, 8)
    after = date(2025, 10, 9)

    before_result = classify_tdx_stock_universe(
        (_universe_row("430001", "bj", session=before), _universe_row("920001", "bj", session=before)),
        before,
    )
    after_result = classify_tdx_stock_universe(
        (_universe_row("430001", "bj", session=after), _universe_row("920001", "bj", session=after)),
        after,
    )

    assert [row.code for row in before_result.rows] == ["430001"]
    assert before_result.unclassified_by_reason == {"bj-920-before-effective-date": 1}
    assert [row.code for row in after_result.rows] == ["430001", "920001"]


def test_tdx_stock_universe_validation_is_fail_closed_for_unknown_or_small_samples():
    classification = classify_tdx_stock_universe(
        (_universe_row("300001", "sz"), _universe_row("450001", "sz")),
        AS_OF,
    )

    with pytest.raises(TDXStockUniverseError, match="unclassified"):
        validate_tdx_stock_universe(
            classification,
            minimum_market_rows={"sh": 0, "sz": 0, "bj": 0},
            minimum_total=1,
            required_markets=(),
        )

    clean = classify_tdx_stock_universe((_universe_row("300001", "sz"),), AS_OF)
    with pytest.raises(TDXStockUniverseError, match="only 1 rows"):
        validate_tdx_stock_universe(
            clean,
            minimum_market_rows={"sh": 0, "sz": 0, "bj": 0},
            minimum_total=2,
            required_markets=(),
        )


def test_tdx_stock_universe_covers_real_package_non_stock_code_families():
    rows = (
        _universe_row("233000", "sh"),
        _universe_row("101000", "sh"),
        _universe_row("245000", "sh"),
        _universe_row("880001", "sh"),
        _universe_row("888880", "sh"),
        _universe_row("566000", "sz"),
        _universe_row("524000", "sz"),
        _universe_row("520000", "sz"),
        _universe_row("199000", "sz"),
        _universe_row("302132", "sz"),
        _universe_row("821001", "bj"),
        _universe_row("910000", "bj"),
        _universe_row("899050", "bj"),
    )

    result = classify_tdx_stock_universe(rows, AS_OF)

    assert result.retained_count == 0
    assert result.excluded_count == len(rows)
    assert result.unclassified_count == 0
    assert result.unclassified_by_reason == {}


def test_structural_package_can_parse_but_filtered_universe_can_fail():
    package = parse_tdx_daily_package(
        make_tdx_package(
            AS_OF,
            codes_by_market={
                "sh": ("600000", "510000"),
                "sz": ("300001", "399001"),
                "bj": ("430001", "899001"),
            },
        ),
        AS_OF,
        minimum_market_rows=MINIMUMS,
    )
    classification = classify_tdx_stock_universe(package.rows, AS_OF)

    assert package.metadata["recordCount"] == 6
    assert classification.raw_count == 6
    assert classification.retained_count == 3
    assert classification.excluded_count == 3
    with pytest.raises(TDXStockUniverseError, match="only 3 rows"):
        validate_tdx_stock_universe(
            classification,
            minimum_market_rows={"sh": 0, "sz": 0, "bj": 0},
            minimum_total=4,
            required_markets=("sh", "sz", "bj"),
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
        self.stock_universe_minimums = {"sh": 0, "sz": 0, "bj": 0}
        self.stock_universe_minimum_total = 0
        self.stock_universe_required_markets = ()
        self.stock_universe_max_unclassified_ratio = 0.0

    def fetch(self, requested_date):
        self.calls.append(requested_date)
        return self.package


def _active_package_rows(names=True, count=30, unsorted=False):
    rows = [
        TDXDailyPackageRow(
            code=f"300{index:03d}",
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
        tdx_active_direction_derived_enabled=True,
    )

    def fail(url, _params):
        if url == provider._STOCK_SNAPSHOT_URL:
            raise RuntimeError("primary disconnected")
        raise RuntimeError("delayed unavailable")

    monkeypatch.setattr(provider.eastmoney, "get_json", fail)
    result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)

    assert package_client.calls == [AS_OF]
    assert result["quality"]["source"] == "tdx-daily-package-derived"
    assert result["quality"]["status"] == "fallback-derived"
    assert result["quality"]["derived"] is True
    assert result["quality"]["rankingMethod"] == "local-turnover-desc-identity-asc"
    assert result["quality"]["sourceRevision"]
    assert result["quality"]["industryMappingCoverage"] == 0.0
    assert result["quality"]["observations"] == 30
    assert result["quality"]["stockUniversePolicyVersion"] == "tdx-stock-universe-v1"
    assert result["quality"]["stockUniverseRawCount"] == 30
    assert result["quality"]["stockUniverseRetainedCount"] == 30
    assert result["quality"]["stockUniverseExcludedCount"] == 0
    assert "primary disconnected" in result["quality"]["warning"]
    assert "delayed unavailable" in result["quality"]["warning"]
    assert [item["code"] for item in result["topStocks"]] == [f"300{i:03d}" for i in range(10)]


def test_provider_does_not_call_tdx_when_eastmoney_succeeds(monkeypatch):
    package_client = PackageClient(_package(_active_package_rows()))
    provider = MarketDataProvider(
        tdx_daily_package=package_client,
        tdx_active_direction_derived_enabled=True,
    )
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (
            [
                {"f12": row.code, "f14": row.name, "f6": row.amount, "f2": row.close}
                for row in _active_package_rows()
            ],
            "eastmoney-clist",
            "partial",
            [],
        ),
    )

    result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)

    assert package_client.calls == []
    assert result["quality"]["source"] == "eastmoney-clist"
    assert result["quality"]["status"] == "partial"


def _replace_row(row, **changes):
    return TDXDailyPackageRow(**{**row.__dict__, **changes})


def test_provider_locally_ranks_unsorted_tdx_rows_and_breaks_amount_ties_by_identity(monkeypatch):
    rows = _active_package_rows()
    rows[0] = _replace_row(rows[0], amount=50_000)
    rows[1] = _replace_row(rows[1], amount=50_000)
    rows[2] = _replace_row(rows[2], amount=60_000)
    package_client = PackageClient(_package(list(reversed(rows))))
    provider = MarketDataProvider(
        tdx_daily_package=package_client,
        tdx_active_direction_derived_enabled=True,
    )
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(RuntimeError("eastmoney unavailable")),
    )

    first = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)
    second = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)

    assert first["quality"]["status"] == "fallback-derived"
    assert [item["code"] for item in first["topStocks"][:3]] == ["300002", "300000", "300001"]
    assert first["topStocks"] == second["topStocks"]


def test_provider_uses_tdx_for_breadth_only_after_eastmoney_failure():
    rows = [
        TDXDailyPackageRow(
            code=f"300{index:03d}",
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
    assert result["quality"]["stockUniverseRetainedCount"] == 4
    assert result["quality"]["stockUniverseRawCount"] == 4


def test_provider_breadth_excludes_non_stock_rows_from_mixed_tdx_package():
    rows = [
        _replace_row(_universe_row("600000", "sh"), change_pct=1.0),
        _replace_row(_universe_row("300001", "sz"), change_pct=-1.0),
        _replace_row(_universe_row("430001", "bj"), change_pct=0.0),
        _replace_row(_universe_row("510000", "sh"), change_pct=-99.0),
    ]
    package_client = PackageClient(_package(rows))
    provider = MarketDataProvider(tdx_daily_package=package_client, tdx_fallback_enabled=True)
    provider._fetch_eastmoney_breadth_fallback = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("eastmoney unavailable")
    )

    result = provider.fetch_chapter01_breadth(AS_OF, allow_current_snapshot=True)

    assert result["advanceCount"] == 1
    assert result["declineCount"] == 1
    assert result["flatCount"] == 1
    assert result["validCount"] == 3
    assert result["quality"]["stockUniverseRawCount"] == 4
    assert result["quality"]["stockUniverseRetainedCount"] == 3
    assert result["quality"]["stockUniverseExcludedByReason"] == {"fund": 1}


def test_provider_active_direction_excludes_high_turnover_non_stock_rows():
    stock_rows = _active_package_rows()
    fund = _replace_row(_universe_row("510000", "sh"), amount=999_999_999.0)
    package_client = PackageClient(_package([*stock_rows, fund]))
    provider = MarketDataProvider(
        tdx_daily_package=package_client,
        tdx_active_direction_derived_enabled=True,
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(RuntimeError("eastmoney unavailable")),
    )
    try:
        result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)
    finally:
        monkeypatch.undo()

    assert result["quality"]["status"] == "fallback-derived"
    assert result["quality"]["stockUniverseRawCount"] == 31
    assert result["quality"]["stockUniverseRetainedCount"] == 30
    assert result["quality"]["stockUniverseExcludedByReason"] == {"fund": 1}
    assert all(item["code"] != "510000" for item in result["topStocks"])


def test_provider_rejects_incomplete_filtered_market_coverage():
    rows = [
        _universe_row("600000", "sh"),
        _universe_row("430001", "bj"),
    ]
    package = TDXDailyPackage(
        rows=tuple(rows),
        source_url="https://tdx.invalid/fixture.zip",
        requested_date=AS_OF,
        source_date=AS_OF,
        fetched_at=datetime(2026, 9, 18, 8, tzinfo=timezone.utc),
        metadata={"marketCounts": {"sh": 1, "sz": 0, "bj": 1}},
    )
    package_client = PackageClient(package)
    provider = MarketDataProvider(tdx_daily_package=package_client, tdx_fallback_enabled=True)
    provider._fetch_eastmoney_breadth_fallback = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("eastmoney unavailable")
    )

    result = provider.fetch_chapter01_breadth(AS_OF, allow_current_snapshot=True)

    assert result["state"] == "insufficient"
    assert result["validCount"] is None
    assert result["quality"]["source"] == "tdx-daily-package"
    assert result["quality"]["status"] == "failed"
    assert "market coverage" in result["quality"]["warning"] or "universe" in result["quality"]["warning"]


def test_provider_rejects_tdx_package_date_mismatch_before_counting():
    previous = date(2026, 9, 17)
    package = TDXDailyPackage(
        rows=tuple(_universe_row("300001", "sz", session=previous) for _ in range(3)),
        source_url="https://tdx.invalid/fixture.zip",
        requested_date=previous,
        source_date=previous,
        fetched_at=datetime(2026, 9, 18, 8, tzinfo=timezone.utc),
        metadata={"marketCounts": {"sh": 1, "sz": 1, "bj": 1}},
    )
    package_client = PackageClient(package)
    provider = MarketDataProvider(tdx_daily_package=package_client, tdx_fallback_enabled=True)
    provider._fetch_eastmoney_breadth_fallback = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("eastmoney unavailable")
    )

    result = provider.fetch_chapter01_breadth(AS_OF, allow_current_snapshot=True)

    assert result["state"] == "insufficient"
    assert result["validCount"] is None
    assert result["quality"]["source"] == "tdx-daily-package"
    assert "date evidence" in result["quality"]["warning"]


@pytest.mark.parametrize(
    "rows, expected",
    [
        (_active_package_rows(count=29), "at least 30"),
        (_active_package_rows(names=False), "name is unresolved"),
    ],
)
def test_provider_rejects_invalid_tdx_active_direction_candidates(monkeypatch, rows, expected):
    package_client = PackageClient(_package(rows))
    provider = MarketDataProvider(
        tdx_daily_package=package_client,
        tdx_active_direction_derived_enabled=True,
    )
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


def test_provider_maps_complete_industry_coverage_and_derives_cluster(monkeypatch):
    rows = _active_package_rows()
    mapper = VersionedIndustryMapper(
        {f"{row.code}.SZ": "算力" for row in rows},
        revision="industry-map-fixture-v1",
    )
    package_client = PackageClient(_package(rows))
    provider = MarketDataProvider(
        tdx_daily_package=package_client,
        tdx_active_direction_derived_enabled=True,
        tdx_industry_mapper=mapper,
    )
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(RuntimeError("eastmoney unavailable")),
    )

    result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)

    assert result["state"] == "candidate"
    assert result["quality"]["industryMappingRevision"] == "industry-map-fixture-v1"
    assert result["quality"]["industryMappingCoverage"] == 1.0
    assert result["topStocks"][0]["industry"] == "算力"


def test_provider_keeps_top_stocks_but_marks_incomplete_industry_mapping_unverified(monkeypatch):
    package_client = PackageClient(_package(_active_package_rows()))
    provider = MarketDataProvider(
        tdx_daily_package=package_client,
        tdx_active_direction_derived_enabled=True,
        tdx_industry_mapper=VersionedIndustryMapper(
            {"300000.SZ": "算力"}, revision="industry-map-partial-v1"
        ),
    )
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(RuntimeError("eastmoney unavailable")),
    )

    result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)

    assert len(result["topStocks"]) == 10
    assert result["state"] == "unverified"
    assert result["quality"]["industryMappingCoverage"] < 1.0
    assert "行业映射覆盖不足" in result["quality"]["warning"]


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


def test_provider_rejects_historical_active_direction_before_provider_calls(monkeypatch):
    package_client = PackageClient(_package(_active_package_rows()))
    provider = MarketDataProvider(
        tdx_daily_package=package_client,
        tdx_active_direction_derived_enabled=True,
    )
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(AssertionError("historical request called provider")),
    )

    result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=False)

    assert package_client.calls == []
    assert result["quality"]["status"] == "missing"
    assert "历史日期" in result["quality"]["warning"]


def test_tdx_real_probe_requires_explicit_authorization(capsys, tmp_path):
    output = tmp_path / "probe.json"

    exit_code = market_cli.main(
        [
            "tdx",
            "real-probe",
            "--as-of",
            AS_OF.isoformat(),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 2
    assert "requires --allow-real" in capsys.readouterr().out
    assert not output.exists()


def test_tdx_real_probe_reports_derived_fields_without_snapshot_write(monkeypatch, tmp_path):
    class ProbePackageClient:
        stock_universe_minimums = {"sh": 0, "sz": 0, "bj": 0}
        stock_universe_minimum_total = 0
        stock_universe_required_markets = ()
        stock_universe_max_unclassified_ratio = 0.0

        def fetch(self, requested_date):
            return _package(_active_package_rows())

    monkeypatch.setattr(market_cli, "TDXDailyPackageClient", ProbePackageClient)
    output = tmp_path / "probe.json"

    exit_code = market_cli.main(
        [
            "tdx",
            "real-probe",
            "--as-of",
            AS_OF.isoformat(),
            "--output",
            str(output),
            "--allow-real",
        ]
    )

    assert exit_code == 0
    report = output.read_text(encoding="utf-8")
    assert '"requestedDate": "2026-09-18"' in report
    assert '"sourceDate": "2026-09-18"' in report
    assert '"derivedTopRows": 30' in report
    assert '"rankingMethod": "local-turnover-desc-identity-asc"' in report
    assert '"industryMappingCoverage": 0.0' in report
    assert '"stockUniversePolicyVersion": "tdx-stock-universe-v1"' in report
    assert '"stockUniverseRetainedCount": 30' in report
    assert '"quality": "fallback-derived"' in report


def test_quality_metadata_survives_public_evidence_schema():
    breadth = BreadthEvidence.model_validate(
        {
            "advanceCount": 2,
            "declineCount": 1,
            "flatCount": 1,
            "validCount": 4,
            "advanceRatio": 0.5,
            "medianReturn": 0.0,
            "state": "涨跌分化",
            "quality": {
                "dataset": "market-breadth",
                "source": "tdx-daily-package",
                "provider": "tdx-daily-package",
                "status": "fallback",
                "observations": 4,
                "asOf": AS_OF.isoformat(),
                "warning": None,
                "warnings": [],
                "stockUniversePolicyVersion": "tdx-stock-universe-v1",
                "stockUniverseRawCount": 8,
                "stockUniverseRetainedCount": 4,
                "stockUniverseExcludedCount": 4,
                "stockUniverseUnclassifiedCount": 0,
                "stockUniverseRetainedByMarket": {"sh": 1, "sz": 2, "bj": 1},
            },
        }
    )
    active = ActiveDirectionEvidence.model_validate(
        {
            "state": "unverified",
            "summary": "仅展示股票榜",
            "topStocks": [],
            "quality": {
                "dataset": "active-direction",
                "source": "tdx-daily-package-derived",
                "provider": "tdx-daily-package-derived",
                "status": "fallback-derived",
                "observations": 0,
                "asOf": AS_OF.isoformat(),
                "warning": None,
                "warnings": [],
                "derived": True,
                "rankingMethod": "local-turnover-desc-identity-asc",
                "stockUniversePolicyVersion": "tdx-stock-universe-v1",
            },
        }
    )

    assert breadth.quality.stockUniverseRetainedCount == 4
    assert breadth.quality.stockUniverseRetainedByMarket == {"sh": 1, "sz": 2, "bj": 1}
    assert active.quality.derived is True
    assert active.quality.rankingMethod == "local-turnover-desc-identity-asc"


def test_provider_resolves_only_names_from_batched_tencent_lookup(monkeypatch):
    rows = _active_package_rows(names=False)
    package_client = PackageClient(_package(rows))
    provider = MarketDataProvider(
        tdx_daily_package=package_client,
        tdx_active_direction_derived_enabled=True,
    )
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (_ for _ in ()).throw(RuntimeError("eastmoney unavailable")),
    )
    monkeypatch.setattr(provider, "_fetch_tencent_names", lambda _rows: {row.code: f"腾讯名{row.code}" for row in rows})

    result = provider.fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)

    assert result["quality"]["source"] == "tdx-daily-package-derived"
    assert result["topStocks"][0]["name"] == "腾讯名300000"
    assert result["topStocks"][0]["amount"] == 30_000
    assert result["topStocks"][0]["changePct"] == pytest.approx(11.1111)


def test_breadth_uses_only_exact_previous_session_when_package_lacks_change_fields():
    current_rows = [
        TDXDailyPackageRow(
            code=f"300{index:03d}",
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
            code=f"300{index:03d}",
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
            self.stock_universe_minimums = {"sh": 0, "sz": 0, "bj": 0}
            self.stock_universe_minimum_total = 0
            self.stock_universe_required_markets = ()
            self.stock_universe_max_unclassified_ratio = 0.0

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
    provider = MarketDataProvider(
        tdx_daily_package=package_client,
        tdx_active_direction_derived_enabled=True,
        tdx_fallback_enabled=True,
    )
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

    assert result.run.status == "partial"
    assert {task.dataset for task in result.tasks} == {"breadth", "activeDirection"}
    assert store.get("breadth", AS_OF).source == "tdx-daily-package"
    assert store.get("activeDirection", AS_OF).source == "tdx-daily-package-derived"
    assert store.get("activeDirection", AS_OF).status == "fallback-derived"
    tasks = {task.dataset: task for task in result.tasks}
    assert tasks["activeDirection"].status == "partial"
    assert package_client.calls == [AS_OF, AS_OF]


def test_collection_replaces_bad_same_date_breadth_snapshot_after_filtered_tdx_success(tmp_path):
    old_payload = {
        "advanceCount": 1976,
        "declineCount": 8221,
        "flatCount": 41694,
        "validCount": 51891,
        "advanceRatio": 0.0381,
        "medianReturn": 0.0,
        "state": "涨跌分化",
        "quality": {
            "dataset": "market-breadth",
            "source": "tdx-daily-package",
            "provider": "tdx-daily-package",
            "status": "fallback",
            "observations": 51891,
            "asOf": AS_OF.isoformat(),
            "warning": "old all-security universe",
            "warnings": ["old all-security universe"],
        },
    }
    rows = [
        _replace_row(_universe_row("300001", "sz"), change_pct=1.0),
        _replace_row(_universe_row("300002", "sz"), change_pct=-1.0),
        _replace_row(_universe_row("300003", "sz"), change_pct=0.0),
    ]
    package_client = PackageClient(_package(rows))
    provider = MarketDataProvider(tdx_daily_package=package_client, tdx_fallback_enabled=True)
    provider._fetch_eastmoney_breadth_fallback = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("breadth eastmoney unavailable")
    )
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    old_record = store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=AS_OF,
            payload=old_payload,
            source="tdx-daily-package",
            status="fallback",
            observations=51891,
            warnings=("old all-security universe",),
            fetched_at=datetime(2026, 9, 17, 15, 20, tzinfo=MARKET_TIME_ZONE),
            settled=True,
        )
    )

    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: datetime(2026, 9, 18, 15, 20, tzinfo=MARKET_TIME_ZONE),
        rebuild_aggregate=lambda *_args, **_kwargs: None,
    ).collect(AS_OF, ["breadth"])

    snapshot = store.get("breadth", AS_OF)
    assert result.tasks[0].status == "success"
    assert snapshot.checksum != old_record.checksum
    assert snapshot.payload["validCount"] == 3
    assert snapshot.observations == 3
    assert snapshot.payload["quality"]["stockUniverseRetainedCount"] == 3
    assert snapshot.payload["quality"]["stockUniverseRawCount"] == 3


def test_collection_retains_bad_same_date_breadth_snapshot_when_universe_filter_fails(tmp_path):
    old_payload = {
        "advanceCount": 1976,
        "declineCount": 8221,
        "flatCount": 41694,
        "validCount": 51891,
        "advanceRatio": 0.0381,
        "medianReturn": 0.0,
        "state": "涨跌分化",
        "quality": {
            "dataset": "market-breadth",
            "source": "tdx-daily-package",
            "provider": "tdx-daily-package",
            "status": "fallback",
            "observations": 51891,
            "asOf": AS_OF.isoformat(),
            "warning": "old all-security universe",
            "warnings": ["old all-security universe"],
        },
    }
    package_client = PackageClient(_package([_universe_row("999999", "sz")]))
    provider = MarketDataProvider(tdx_daily_package=package_client, tdx_fallback_enabled=True)
    provider._fetch_eastmoney_breadth_fallback = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("breadth eastmoney unavailable")
    )
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    old_record = store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=AS_OF,
            payload=old_payload,
            source="tdx-daily-package",
            status="fallback",
            observations=51891,
            warnings=("old all-security universe",),
            fetched_at=datetime(2026, 9, 17, 15, 20, tzinfo=MARKET_TIME_ZONE),
            settled=True,
        )
    )

    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: datetime(2026, 9, 18, 15, 20, tzinfo=MARKET_TIME_ZONE),
        rebuild_aggregate=lambda *_args, **_kwargs: None,
    ).collect(AS_OF, ["breadth"])

    snapshot = store.get("breadth", AS_OF)
    assert result.tasks[0].status == "failed-retained"
    assert snapshot.checksum == old_record.checksum
    assert snapshot.payload["validCount"] == 51891
    assert "普通 A 股 universe" in snapshot.refresh_warning


def test_collection_status_reads_universe_metadata_without_provider_call(tmp_path):
    class RaisingProvider:
        def fetch_chapter01_breadth(self, *_args, **_kwargs):
            raise AssertionError("status must not call provider")

    payload = {
        "advanceCount": 2,
        "declineCount": 1,
        "flatCount": 0,
        "validCount": 3,
        "advanceRatio": 0.6667,
        "medianReturn": 1.0,
        "state": "多数上涨",
        "quality": {
            "dataset": "market-breadth",
            "source": "tdx-daily-package",
            "provider": "tdx-daily-package",
            "status": "fallback",
            "observations": 3,
            "asOf": AS_OF.isoformat(),
            "warning": None,
            "warnings": [],
            "stockUniversePolicyVersion": "tdx-stock-universe-v1",
            "stockUniverseRetainedCount": 3,
        },
    }
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=AS_OF,
            payload=payload,
            source="tdx-daily-package",
            status="fallback",
            observations=3,
            warnings=(),
            fetched_at=datetime(2026, 9, 18, 15, 20, tzinfo=MARKET_TIME_ZONE),
            settled=True,
        )
    )

    status = CollectionCoordinator(
        RaisingProvider(),
        store,
        now=lambda: datetime(2026, 9, 18, 15, 20, tzinfo=MARKET_TIME_ZONE),
    ).collection_status(AS_OF)

    breadth = next(item for item in status["datasets"] if item["dataset"] == "breadth")
    assert breadth["available"] is True
    assert breadth["quality"]["stockUniversePolicyVersion"] == "tdx-stock-universe-v1"
    assert breadth["quality"]["stockUniverseRetainedCount"] == 3


def test_collection_retains_same_date_snapshot_when_tdx_fallback_fails(tmp_path, monkeypatch):
    class FailingClient:
        def fetch(self, requested_date):
            raise TDXDailyPackageUnavailable("not published")

    provider = MarketDataProvider(
        tdx_daily_package=FailingClient(),
        tdx_active_direction_derived_enabled=True,
    )
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
