from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from src.market_environment.domain.analysis.ths_sector import (
    build_rankings,
    calculate_breadth,
    catalog_checksum,
    select_breadth_codes,
)
from src.market_environment.domain.models.ths_sector import (
    THS_TAGS,
    ThsBackfillRun,
    ThsCatalogRelation,
    ThsCatalogRevision,
    ThsMemberObservation,
    ThsSectorBar,
    ThsSnapshotFact,
)


AS_OF = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ths-sector" / "catalog-snapshot.json"


def _relations() -> tuple[ThsCatalogRelation, ...]:
    rows = []
    for index, tag in enumerate(THS_TAGS, start=1):
        rows.append(ThsCatalogRelation("catalog-r1", tag, f"{index:06d}.TI", f"板块{index}"))
    rows.append(ThsCatalogRelation("catalog-r1", "cn_concept", "000001.TI", "板块1"))
    return tuple(rows)


def _snapshots() -> tuple[ThsSnapshotFact, ...]:
    return tuple(
        ThsSnapshotFact(
            thscode=f"{index:06d}.TI",
            name=f"板块{index}",
            as_of=AS_OF,
            provider_timestamp=NOW,
            change_pct=2.0 if index in {1, 2} else float(index),
            open=10 + index,
            high=12 + index,
            low=9 + index,
            close=11 + index,
            volume=1000 * index,
            turnover=10000 * index,
        )
        for index in range(1, 5)
    )


def test_catalog_revision_requires_all_four_tags_and_checksum_is_stable() -> None:
    relations = _relations()
    assert catalog_checksum(relations) == catalog_checksum(tuple(reversed(relations)))
    revision = ThsCatalogRevision(
        revision_id="catalog-r1",
        capability_revision="fuyao-ths-catalog-v1",
        provider_timestamp=NOW,
        fetched_at=NOW,
        tag_counts={"industry": 1, "cn_concept": 2, "region": 1, "tszs": 1},
        checksum=catalog_checksum(relations),
    )
    assert revision.row_count == 5
    with pytest.raises(ValueError, match="exactly the four"):
        ThsCatalogRevision(
            "bad",
            "r1",
            NOW,
            NOW,
            {"industry": 1},
            "checksum",
        )


def test_cross_tag_identity_shares_one_snapshot_and_stable_rank_tie_break() -> None:
    rows = build_rankings(
        _relations(),
        _snapshots(),
        catalog_revision="catalog-r1",
        as_of=AS_OF,
    )
    concept = [row for row in rows if row.tag == "cn_concept"]
    assert [(row.rank, row.thscode) for row in concept] == [
        (1, "000001.TI"),
        (2, "000002.TI"),
    ]
    shared = [row for row in rows if row.thscode == "000001.TI"]
    assert {row.tag for row in shared} == {"industry", "cn_concept"}
    assert {row.volume for row in shared} == {1000}


def test_rankings_reject_duplicate_or_incomplete_snapshot_coverage() -> None:
    with pytest.raises(ValueError, match="coverage mismatch"):
        build_rankings(
            _relations(),
            _snapshots()[:-1],
            catalog_revision="catalog-r1",
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="duplicate snapshot"):
        build_rankings(
            _relations(),
            (*_snapshots(), _snapshots()[0]),
            catalog_revision="catalog-r1",
            as_of=AS_OF,
        )


def test_sector_bar_keeps_volume_and_turnover_distinct() -> None:
    bar = ThsSectorBar(
        thscode="000001.TI",
        trading_date=AS_OF,
        open=10,
        high=12,
        low=9,
        close=11,
        volume=123,
        turnover=456,
        source="fuyao",
        source_revision="history-v1",
        checksum="abc",
        fetched_at=NOW,
    )
    assert bar.volume == 123
    assert bar.turnover == 456
    with pytest.raises(ValueError, match="non-negative"):
        ThsSectorBar(
            "000001.TI", AS_OF, 10, 12, 9, 11, -1, 456,
            "fuyao", "history-v1", "abc", NOW,
        )


def test_backfill_bounds_codes_dates_and_budget() -> None:
    run = ThsBackfillRun(
        run_id="run-1",
        thscodes=("000002.TI", "000001.TI", "000001.TI"),
        start_date=date(2022, 1, 1),
        end_date=AS_OF,
        capability_revision="history-v1",
        request_budget=60,
    )
    assert run.thscodes == ("000001.TI", "000002.TI")
    with pytest.raises(ValueError, match="at most 60"):
        ThsBackfillRun(
            "run-many",
            tuple(f"{index:06d}.TI" for index in range(1, 62)),
            date(2026, 1, 1),
            AS_OF,
            "history-v1",
            80,
        )


def test_breadth_formulas_top_lists_and_mixed_lineage() -> None:
    members = (
        ThsMemberObservation(
            "000001.SZ", 2.0, 12, tuple(float(value) for value in range(1, 21)), 60,
            limit_up=True, lineage={"price": "fuyao", "turnover": "fuyao"},
        ),
        ThsMemberObservation(
            "000002.SZ", -1.0, 8, tuple(10.0 for _ in range(20)), 30,
            limit_down=True, lineage={"price": "fuyao", "turnover": "tdx"},
        ),
        ThsMemberObservation(
            "000003.SZ", 0.0, 10, tuple(9.0 for _ in range(19)), 10,
            lineage={"price": "fuyao"},
        ),
    )
    result = calculate_breadth(
        thscode="000001.TI",
        as_of=AS_OF,
        selection_reasons=("top-10:industry", "user-selected"),
        members=members,
        total_member_count=4,
        limits_available=True,
        top_n=2,
    )
    assert result.valid_direction_count == 3
    assert result.advance_ratio == pytest.approx(1 / 3)
    assert result.advance_decline_spread_ratio == 0
    assert result.median_change_pct == 0
    assert result.valid_ma20_count == 2
    assert result.close_above_ma20_count == 1
    assert result.ma20_breadth == 0.5
    assert result.limit_up_count == 1
    assert result.limit_down_count == 1
    assert [item.security_id for item in result.top_by_turnover] == ["000001.SZ", "000002.SZ"]
    assert result.max_member_turnover_contribution == 0.6
    assert result.diffusion_rate == 0.4
    assert result.quality == "partial"
    assert any("mixed source" in warning for warning in result.warnings)


def test_breadth_zero_denominators_and_limits_missing_stay_null() -> None:
    result = calculate_breadth(
        thscode="000001.TI",
        as_of=AS_OF,
        selection_reasons=("user-selected",),
        members=(),
        total_member_count=0,
        limits_available=False,
    )
    assert result.advance_ratio is None
    assert result.advance_decline_spread_ratio is None
    assert result.ma20_breadth is None
    assert result.limit_up_count is None
    assert result.max_member_turnover_contribution is None
    assert result.diffusion_rate is None
    assert result.quality == "insufficient"


def test_top_ten_and_user_selections_are_deduplicated() -> None:
    rankings = build_rankings(
        _relations(),
        _snapshots(),
        catalog_revision="catalog-r1",
        as_of=AS_OF,
    )
    selected = select_breadth_codes(rankings, ("000001.TI",), per_tag=10)
    assert selected["000001.TI"] == (
        "top-10:cn_concept",
        "top-10:industry",
        "user-selected",
    )
    with pytest.raises(ValueError, match="absent"):
        select_breadth_codes(rankings, ("999999.TI",))


def test_synthetic_fixture_covers_four_tags_shared_code_history_and_redaction() -> None:
    raw_text = FIXTURE_PATH.read_text(encoding="utf-8")
    fixture = json.loads(raw_text)
    assert set(fixture["catalogs"]) == set(THS_TAGS)
    all_codes = [
        row["thscode"]
        for rows in fixture["catalogs"].values()
        for row in rows
    ]
    assert all_codes.count("000005.TI") == 2
    assert fixture["history"]["bars"][0]["volume"] != fixture["history"]["bars"][0]["turnover"]
    assert fixture["invalidCases"]["duplicateCatalog"][0]["thscode"] == fixture["invalidCases"]["duplicateCatalog"][1]["thscode"]
    assert fixture["invalidCases"]["snapshotDateDrift"].startswith("2026-10-11")
    assert "open" not in fixture["invalidCases"]["historyMissingFields"]
    assert fixture["invalidCases"]["dumpSchemaDrift"] != fixture["dumpManifest"]["schema"]
    lowered = raw_text.lower()
    assert "api_key" not in lowered
    assert "x-api-key" not in lowered
    assert "authorization" not in lowered
    assert "x-amz-signature" not in lowered


def test_snapshot_fact_allows_missing_change_pct_with_warning() -> None:
    fact = ThsSnapshotFact(
        thscode="883401.TI",
        name="缺字段板块",
        as_of=AS_OF,
        provider_timestamp=NOW,
        change_pct=None,
        open=10.0,
        high=10.8,
        low=9.8,
        close=10.5,
        volume=1000.0,
        turnover=10000.0,
    )
    assert fact.change_pct is None
    assert fact.close == 10.5


def test_build_rankings_tolerates_missing_change_pct_by_sorting_to_tail() -> None:
    relations = _relations()
    base_snapshots = _snapshots()
    # Drop change_pct for two THS codes that fall across tags.
    patched = []
    for snapshot in base_snapshots:
        patched.append(
            ThsSnapshotFact(
                thscode=snapshot.thscode,
                name=snapshot.name,
                as_of=snapshot.as_of,
                provider_timestamp=snapshot.provider_timestamp,
                change_pct=None if snapshot.thscode in {"000001.TI", "000003.TI"} else snapshot.change_pct,
                open=snapshot.open,
                high=snapshot.high,
                low=snapshot.low,
                close=snapshot.close,
                volume=snapshot.volume,
                turnover=snapshot.turnover,
            )
        )

    rankings = build_rankings(
        relations,
        tuple(patched),
        catalog_revision="catalog-r1",
        as_of=AS_OF,
    )
    assert rankings, "rankings must still be produced when some changePct are missing"
    by_code = {row.thscode: row for row in rankings}
    assert by_code["000001.TI"].change_pct is None
    assert by_code["000003.TI"].change_pct is None
    # Per-tag leaders with a non-null change_pct must still outrank every None entry.
    for tag in THS_TAGS:
        rows = [row for row in rankings if row.tag == tag]
        leaders = [row for row in rows if row.change_pct is not None]
        trailers = [row for row in rows if row.change_pct is None]
        if leaders and trailers:
            assert max(row.rank for row in leaders) <= min(row.rank for row in trailers), (
                f"per-tag ordering broken for {tag}: leaders={leaders} trailers={trailers}"
            )
