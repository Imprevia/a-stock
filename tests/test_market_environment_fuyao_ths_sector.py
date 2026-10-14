from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.market_environment.domain.models.capability import ProviderCapabilityReport
from src.market_environment.infrastructure.providers.fuyao.market import FuyaoMarketContractError
from src.market_environment.infrastructure.providers.fuyao.ths_sector import (
    FuyaoThsCapabilityError,
    FuyaoThsCapabilityPolicy,
    FuyaoThsSectorAdapter,
    THS_CATALOG_CAPABILITY,
    THS_HISTORY_CAPABILITY,
    THS_MEMBERSHIP_CAPABILITY,
)


AS_OF = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ths-sector" / "catalog-snapshot.json"


class FakeClient:
    configured = True
    request_budget = 80

    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    @property
    def request_count(self) -> int:
        return len(self.calls)

    def request(self, path, *, params=None, requested_date=None):
        self.calls.append((path, dict(params or {})))
        if not self.responses:
            raise AssertionError("unexpected provider request")
        return SimpleNamespace(data=self.responses.pop(0))


class Reports:
    def __init__(self, report=None):
        self.report = report

    def get_capability_report(self, provider, dataset, revision=None):
        if self.report and (provider, dataset, revision) == (
            self.report.provider,
            self.report.dataset,
            self.report.revision,
        ):
            return self.report
        return None


def _eligible_report(dataset: str, revision: str) -> ProviderCapabilityReport:
    return ProviderCapabilityReport(
        provider="fuyao",
        dataset=dataset,
        revision=revision,
        status="eligible",
        endpoint="https://fuyao.aicubes.cn/api/redacted",
        field_coverage={"complete": True},
        date_evidence={"exact": True},
        permission_evidence={"approved": True},
        rate_limit_evidence={"requestBudget": 80},
        sample_count=1,
        checked_at=NOW,
    ).normalized()


def _fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _catalog_payloads(fixture):
    return {
        tag: {"timestamp": fixture["providerTimestamp"], "item": rows}
        for tag, rows in fixture["catalogs"].items()
    }


def _adapter(client=None):
    return FuyaoThsSectorAdapter(
        client or FakeClient([]),
        capability_revision="fixture-ths-catalog-v1",
        history_revision="fixture-ths-history-v1",
        now=lambda: NOW,
    )


def test_capability_policy_fails_before_adapter_construction() -> None:
    constructed = False

    def factory():
        nonlocal constructed
        constructed = True
        return _adapter()

    policy = FuyaoThsCapabilityPolicy(Reports(), enabled={THS_CATALOG_CAPABILITY: True})
    with pytest.raises(FuyaoThsCapabilityError, match="missing eligible"):
        policy.require(THS_CATALOG_CAPABILITY, "fixture-ths-catalog-v1")
    assert constructed is False
    factory  # keep the construction seam explicit for the zero-I/O assertion


def test_capability_policy_requires_exact_enabled_redacted_revision() -> None:
    report = _eligible_report(THS_HISTORY_CAPABILITY, "history-v1")
    policy = FuyaoThsCapabilityPolicy(
        Reports(report),
        enabled={THS_HISTORY_CAPABILITY: True},
    )
    assert policy.require(THS_HISTORY_CAPABILITY, "history-v1") == report
    with pytest.raises(FuyaoThsCapabilityError, match="disabled"):
        FuyaoThsCapabilityPolicy(Reports(report)).require(
            THS_HISTORY_CAPABILITY, "history-v1"
        )
    with pytest.raises(FuyaoThsCapabilityError, match="not eligible"):
        FuyaoThsCapabilityPolicy(
            Reports(replace(report, status="unverified")),
            enabled={THS_HISTORY_CAPABILITY: True},
        ).require(THS_HISTORY_CAPABILITY, "history-v1")

    membership_report = _eligible_report(THS_MEMBERSHIP_CAPABILITY, "membership-v1")
    membership_policy = FuyaoThsCapabilityPolicy(
        Reports(membership_report),
        enabled={THS_MEMBERSHIP_CAPABILITY: True},
    )
    assert membership_policy.require(
        THS_MEMBERSHIP_CAPABILITY,
        "membership-v1",
    ) == membership_report


def test_normalize_four_catalogs_complete_snapshot_and_cross_tag_identity() -> None:
    fixture = _fixture()
    bundle = _adapter().normalize_catalog_snapshot(
        _catalog_payloads(fixture),
        [{"timestamp": fixture["providerTimestamp"], "item": fixture["snapshot"]}],
        as_of=AS_OF,
        fetched_at=NOW,
    )
    assert bundle.revision.tag_counts == {
        "industry": 2,
        "cn_concept": 2,
        "region": 1,
        "tszs": 1,
    }
    assert len(bundle.snapshots) == 5
    assert bundle.revision.capability_revision == "fixture-ths-catalog-v1"
    assert bundle.revision.revision_id.startswith(
        "fuyao:fixture-ths-catalog-v1:2026-10-12:sha256:"
    )
    assert bundle.revision.revision_id != bundle.revision.capability_revision
    assert {row.revision_id for row in bundle.relations} == {
        bundle.revision.revision_id
    }
    assert bundle.missing_live_codes == ()
    assert bundle.missing_ranking_codes == ()
    assert len([row for row in bundle.relations if row.thscode == "000005.TI"]) == 2
    assert len([row for row in bundle.rankings if row.thscode == "000005.TI"]) == 2


@pytest.mark.parametrize(
    "case",
    [
        "duplicate",
        "missing",
        "extra",
        "snapshot-duplicate",
        "date-drift",
        "row-date-drift",
        "catalog-timestamp-missing",
        "snapshot-timestamp-missing",
        "name-conflict",
        "snapshot-name-conflict",
    ],
)
def test_catalog_snapshot_rejects_contract_drift(case) -> None:
    fixture = _fixture()
    catalogs = _catalog_payloads(fixture)
    snapshots = [{"timestamp": fixture["providerTimestamp"], "item": list(fixture["snapshot"])}]
    if case == "duplicate":
        catalogs["industry"] = {
            "timestamp": fixture["providerTimestamp"],
            "item": fixture["invalidCases"]["duplicateCatalog"],
        }
    elif case == "missing":
        snapshots[0]["item"] = snapshots[0]["item"][:-1]
    elif case == "extra":
        snapshots[0]["item"].append(
            {
                **snapshots[0]["item"][0],
                "thscode": "999999.TI",
                "name": "目录外代码",
            }
        )
    elif case == "snapshot-duplicate":
        snapshots[0]["item"].append(dict(snapshots[0]["item"][0]))
    elif case == "date-drift":
        snapshots[0]["timestamp"] = fixture["invalidCases"]["snapshotDateDrift"]
    elif case == "row-date-drift":
        snapshots[0]["item"][0] = {
            **snapshots[0]["item"][0],
            "date": "2026-10-11",
        }
    elif case == "catalog-timestamp-missing":
        catalogs["industry"] = {"item": catalogs["industry"]["item"]}
    elif case == "snapshot-timestamp-missing":
        snapshots[0].pop("timestamp")
    elif case == "snapshot-name-conflict":
        snapshots[0]["item"][0] = {
            **snapshots[0]["item"][0],
            "name": "冲突快照名称",
        }
    else:
        catalogs["cn_concept"] = {
            "timestamp": fixture["providerTimestamp"],
            "item": [
                {"thscode": "000002.TI", "name": "合成概念乙"},
                {"thscode": "000005.TI", "name": "冲突共享板块"},
            ],
        }
    with pytest.raises((FuyaoMarketContractError, ValueError)):
        _adapter().normalize_catalog_snapshot(catalogs, snapshots, as_of=AS_OF)


def test_fetch_catalog_snapshot_requests_four_tags_and_unique_code_batches() -> None:
    fixture = _fixture()
    responses = [*_catalog_payloads(fixture).values()]
    responses.extend(
        [
            {"timestamp": fixture["providerTimestamp"], "item": fixture["snapshot"][:3]},
            {"timestamp": fixture["providerTimestamp"], "item": fixture["snapshot"][3:]},
        ]
    )
    client = FakeClient(responses)
    bundle = _adapter(client).fetch_catalog_snapshot(AS_OF, batch_size=3)
    assert len(bundle.snapshots) == 5
    assert [params["tag"] for _, params in client.calls[:4]] == [
        "industry", "cn_concept", "region", "tszs"
    ]
    requested_codes = ",".join(params["thscodes"] for _, params in client.calls[4:]).split(",")
    assert len(requested_codes) == len(set(requested_codes)) == 5


def test_memberships_require_exact_date_unique_members_and_identity() -> None:
    adapter = _adapter()
    payload = {
        "timestamp": "2026-10-12T16:00:00+08:00",
        "index_thscode": "000001.TI",
        "item": [
            {"thscode": "000002.SZ", "ticker": "000002", "name": "合成成员乙"},
            {"thscode": "600001.SH", "ticker": "600001", "name": "合成成员甲"},
        ],
    }
    rows = adapter.normalize_memberships(
        "000001.TI",
        payload,
        as_of=AS_OF,
        fetched_at=NOW,
    )
    assert [row.member_security_id for row in rows] == ["000002.SZ", "600001.SH"]
    assert {row.as_of for row in rows} == {AS_OF}
    assert {row.source_revision for row in rows} == {"fixture-ths-catalog-v1"}

    with pytest.raises(FuyaoMarketContractError, match="duplicate member"):
        adapter.normalize_memberships(
            "000001.TI",
            {**payload, "item": [payload["item"][0], payload["item"][0]]},
            as_of=AS_OF,
        )
    with pytest.raises(FuyaoMarketContractError, match="date mismatch"):
        adapter.normalize_memberships(
            "000001.TI",
            {**payload, "timestamp": "2026-10-11T16:00:00+08:00"},
            as_of=AS_OF,
        )
    with pytest.raises(FuyaoMarketContractError, match="identity mismatch"):
        adapter.normalize_memberships(
            "000001.TI",
            {**payload, "index_thscode": "000002.TI"},
            as_of=AS_OF,
        )


def test_history_keeps_ohlc_volume_turnover_and_field_level_partial() -> None:
    fixture = _fixture()
    bars = _adapter().normalize_history(
        fixture["history"]["thscode"],
        fixture["history"]["bars"],
        start_date=date(2026, 10, 1),
        end_date=AS_OF,
        fetched_at=NOW,
    )
    assert [bar.trading_date for bar in bars] == [date(2026, 10, 10), AS_OF]
    assert bars[-1].volume == 1010
    assert bars[-1].turnover == 10010
    partial_raw = [dict(fixture["history"]["bars"][-1], volume=None)]
    partial = _adapter().normalize_history(
        "000001.TI", partial_raw,
        start_date=AS_OF, end_date=AS_OF, fetched_at=NOW,
    )
    assert partial[0].quality == "partial"
    assert partial[0].volume is None
    assert partial[0].turnover == 10010


def test_history_rejects_duplicate_identity_drift_missing_ohlc_and_five_year_overflow() -> None:
    fixture = _fixture()
    adapter = _adapter()
    duplicate = [fixture["history"]["bars"][0], fixture["history"]["bars"][0]]
    with pytest.raises(FuyaoMarketContractError, match="duplicate date"):
        adapter.normalize_history(
            "000001.TI", duplicate,
            start_date=date(2026, 10, 1), end_date=AS_OF,
        )
    with pytest.raises(FuyaoMarketContractError, match="lacks"):
        adapter.normalize_history(
            "000001.TI", [fixture["invalidCases"]["historyMissingFields"]],
            start_date=AS_OF, end_date=AS_OF,
        )
    with pytest.raises(FuyaoMarketContractError, match="identity mismatch"):
        adapter.normalize_history(
            "000001.TI", [dict(fixture["history"]["bars"][-1], thscode="000002.TI")],
            start_date=AS_OF, end_date=AS_OF,
        )
    with pytest.raises(ValueError, match="five years"):
        adapter.normalize_history(
            "000001.TI", [],
            start_date=date(2020, 1, 1), end_date=AS_OF,
        )


def test_normalize_catalog_snapshot_tolerates_missing_change_pct_and_emits_warning() -> None:
    fixture = _fixture()
    catalogs = _catalog_payloads(fixture)
    raw_snapshots = list(fixture["snapshot"])
    patched = []
    for row in raw_snapshots:
        row = dict(row)
        if row["thscode"] == "000005.TI":
            # Real provider gap on 883401.TI analog code: drop every alias.
            for alias in ("price_change_ratio_pct", "change_pct", "changePct", "f3"):
                row.pop(alias, None)
        patched.append(row)

    bundle = _adapter().normalize_catalog_snapshot(
        catalogs,
        [{"timestamp": fixture["providerTimestamp"], "item": patched}],
        as_of=AS_OF,
        fetched_at=NOW,
    )

    by_code = {row.thscode: row for row in bundle.snapshots}
    assert by_code["000005.TI"].change_pct is None
    missing_warning = next(
        warning for warning in bundle.warnings if warning.startswith("000005.TI changePct missing")
    )
    assert missing_warning in bundle.warnings
    # Rankings must still be produced with changePct None passthrough.
    matching_rank = next(
        ranking for ranking in bundle.rankings if ranking.thscode == "000005.TI"
    )
    assert matching_rank.change_pct is None
    assert matching_rank.quality == "insufficient"
    assert bundle.missing_live_codes == ()
    assert bundle.missing_ranking_codes == ("000005.TI",)


def test_normalize_catalog_snapshot_retains_rows_without_live_market_values() -> None:
    fixture = _fixture()
    catalogs = _catalog_payloads(fixture)
    raw_snapshots = list(fixture["snapshot"])

    # Inject three extra codes that the provider exposes in the catalog but does not
    # supply any live market data for (mirrors the real "883401.TI / 883422.TI /
    # 883998.TI" provider gap observed on 2026-10-12).
    sparse_codes = [("883401.TI", "稀疏板块A"), ("883422.TI", "稀疏板块B"), ("883998.TI", "稀疏板块C")]
    industries = list(catalogs["industry"]["item"])
    for thscode, name in sparse_codes:
        industries.append({"thscode": thscode, "name": name})
    catalogs["industry"] = {
        "timestamp": catalogs["industry"]["timestamp"],
        "item": industries,
    }
    for thscode, name in sparse_codes:
        raw_snapshots.append(
            {
                "thscode": thscode,
                "name": name,
                "ticker": thscode.split(".", 1)[0],
                "volume": None,
                "turnover": None,
                "last_price": None,
                "price_change": None,
                "price_change_ratio_pct": None,
                "open_price": None,
                "high_price": None,
                "low_price": None,
                "prev_price": 1.0,
            }
        )

    bundle = _adapter().normalize_catalog_snapshot(
        catalogs,
        [{"timestamp": fixture["providerTimestamp"], "item": raw_snapshots}],
        as_of=AS_OF,
        fetched_at=NOW,
    )

    snapshot_codes = {row.thscode for row in bundle.snapshots}
    relation_codes = {row.thscode for row in bundle.relations}
    assert relation_codes == snapshot_codes
    for thscode, _name in sparse_codes:
        assert thscode in snapshot_codes, f"sparse {thscode} must remain explicit"
    retained_warnings = [
        warning for warning in bundle.warnings
        if "no live market values" in warning
    ]
    assert len(retained_warnings) == len(sparse_codes)
    assert bundle.missing_live_codes == tuple(code for code, _name in sparse_codes)
    assert bundle.missing_ranking_codes == tuple(code for code, _name in sparse_codes)
    assert len(bundle.relations) == 9
    assert len(bundle.rankings) == 9
    assert all(
        row.quality == "insufficient"
        for row in bundle.rankings
        if row.thscode in bundle.missing_ranking_codes
    )
    # Counts and checksum describe the complete catalog, not daily value availability.
    assert bundle.revision.tag_counts == {
        "industry": 5,
        "cn_concept": 2,
        "region": 1,
        "tszs": 1,
    }
    filled_rows = [dict(row) for row in raw_snapshots]
    for row in filled_rows:
        if row["thscode"] in bundle.missing_live_codes:
            row.update(
                {
                    "price_change_ratio_pct": 0.5,
                    "open_price": 10.0,
                    "high_price": 10.5,
                    "low_price": 9.8,
                    "last_price": 10.2,
                    "volume": 1000.0,
                    "turnover": 10000.0,
                }
            )
    filled = _adapter().normalize_catalog_snapshot(
        catalogs,
        [{"timestamp": fixture["providerTimestamp"], "item": filled_rows}],
        as_of=AS_OF,
        fetched_at=NOW,
    )
    assert filled.missing_live_codes == ()
    assert filled.revision.tag_counts == bundle.revision.tag_counts
    assert filled.revision.checksum == bundle.revision.checksum
    assert filled.revision.revision_id == bundle.revision.revision_id


def test_catalog_observation_identity_ignores_order_and_timestamp_drift() -> None:
    fixture = _fixture()
    catalogs = _catalog_payloads(fixture)
    snapshot = [{"timestamp": fixture["providerTimestamp"], "item": fixture["snapshot"]}]
    first = _adapter().normalize_catalog_snapshot(
        catalogs,
        snapshot,
        as_of=AS_OF,
        fetched_at=NOW,
    )

    reordered = {
        tag: {
            "timestamp": "2026-10-12T17:00:00+08:00",
            "item": list(reversed(payload["item"])),
        }
        for tag, payload in catalogs.items()
    }
    retry = _adapter().normalize_catalog_snapshot(
        reordered,
        [{"timestamp": "2026-10-12T17:01:00+08:00", "item": list(reversed(fixture["snapshot"]))}],
        as_of=AS_OF,
        fetched_at=datetime(2026, 10, 12, 9, 5, tzinfo=timezone.utc),
    )
    assert retry.revision.checksum == first.revision.checksum
    assert retry.revision.revision_id == first.revision.revision_id
    assert retry.revision.provider_timestamp != first.revision.provider_timestamp
    assert retry.revision.fetched_at != first.revision.fetched_at


def test_change_pct_without_bar_is_rankable_but_declares_live_gap() -> None:
    fixture = _fixture()
    catalogs = _catalog_payloads(fixture)
    rows = [dict(row) for row in fixture["snapshot"]]
    target = next(row for row in rows if row["thscode"] == "000004.TI")
    for field_name in ("open", "high", "low", "close", "volume", "turnover"):
        target[field_name] = None

    bundle = _adapter().normalize_catalog_snapshot(
        catalogs,
        [{"timestamp": fixture["providerTimestamp"], "item": rows}],
        as_of=AS_OF,
        fetched_at=NOW,
    )
    assert bundle.missing_live_codes == ("000004.TI",)
    assert bundle.missing_ranking_codes == ()
    ranking = next(row for row in bundle.rankings if row.thscode == "000004.TI")
    assert ranking.change_pct == 0.0
    assert ranking.quality == "partial"
