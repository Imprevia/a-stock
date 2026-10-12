from __future__ import annotations

import hashlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.market_environment.infrastructure.providers.fuyao.ths_dump import (
    FuyaoThsDumpReader,
    ThsDumpContractError,
    ThsDumpManifest,
    merge_member_facts,
)
from src.market_environment.infrastructure.providers.fuyao.ths_probe import (
    FuyaoThsDumpDownloader,
    FuyaoThsProbeError,
)


AS_OF = date(2026, 10, 12)


def _manifest(path, *, kind="daily", checksum=None):
    return ThsDumpManifest(
        dump_id={
            "daily": "daily-k",
            "incremental": "daily-k-10d",
            "adjustment": "adjustment-factors",
        }[kind],
        kind=kind,
        schema_revision="fuyao-official-v1",
        capability_revision=f"sector-member-{kind}-dump-v1",
        checksum=checksum or hashlib.sha256(path.read_bytes()).hexdigest(),
        start_date=AS_OF,
        end_date=AS_OF,
    )


def test_parquet_reader_verifies_checksum_schema_date_and_duplicate_key(tmp_path, monkeypatch) -> None:
    path = tmp_path / "daily.parquet"
    row = {
        "thscode": "000001.SZ",
        "currency": "CNY",
        "interval": "1d",
        "adjusted": "none",
        "date_ms": int(
            datetime(2026, 10, 12, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
            * 1000
        ),
        "open_price": 10,
        "high_price": 12,
        "low_price": 9,
        "close_price": 11,
        "volume": 100,
        "turnover": 1000,
    }
    pd.DataFrame([row]).to_parquet(path, index=False)
    imported = FuyaoThsDumpReader().read(path, _manifest(path))
    assert imported[0]["security_id"] == "000001.SZ"
    assert imported[0]["volume"] == 100
    assert imported[0]["turnover"] == 1000

    with pytest.raises(ThsDumpContractError, match="checksum mismatch"):
        FuyaoThsDumpReader().read(path, _manifest(path, checksum="wrong"))
    missing_path = tmp_path / "missing.parquet"
    pd.DataFrame([{key: value for key, value in row.items() if key != "turnover"}]).to_parquet(
        missing_path,
        index=False,
    )
    with pytest.raises(ThsDumpContractError, match="missing columns"):
        FuyaoThsDumpReader().read(missing_path, _manifest(missing_path))
    duplicate_path = tmp_path / "duplicate.parquet"
    pd.DataFrame([row, row]).to_parquet(duplicate_path, index=False)
    with pytest.raises(ThsDumpContractError, match="duplicate key"):
        FuyaoThsDumpReader().read(duplicate_path, _manifest(duplicate_path))


def test_official_adjustment_dump_stays_as_corporate_action_evidence(tmp_path) -> None:
    path = tmp_path / "adjustment.parquet"
    pd.DataFrame(
        [
            {
                "thscode": "000001.SZ",
                "ticker": "000001",
                "ex_date_ms": int(
                    datetime(
                        2026,
                        10,
                        12,
                        tzinfo=ZoneInfo("Asia/Shanghai"),
                    ).timestamp()
                    * 1000
                ),
                "dividend_per_share": 0.1,
                "per_share_bonus": 0.0,
                "allotment_ratio": 0.0,
                "allotment_price": 0.0,
                "currency": "CNY",
            }
        ]
    ).to_parquet(path, index=False)

    imported = FuyaoThsDumpReader().read(path, _manifest(path, kind="adjustment"))

    assert imported[0]["security_id"] == "000001.SZ"
    assert imported[0]["dividend_per_share"] == pytest.approx(0.1)
    assert "adjustment_factor" not in imported[0]


def test_adjustment_applies_only_to_price_and_tdx_fills_original_fields() -> None:
    facts = merge_member_facts(
        [
            {
                "security_id": "000001.SZ",
                "date": AS_OF,
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "volume": None,
                "turnover": None,
            }
        ],
        [{"security_id": "000001.SZ", "date": AS_OF, "adjustment_factor": 1.1}],
        source_revision="fuyao-dump-v1",
        tdx_rows=[
            {
                "security_id": "000001.SZ",
                "date": AS_OF,
                "volume": 123,
                "amount": 456,
            }
        ],
    )
    fact = facts[0]
    assert fact.adjusted_close == pytest.approx(12.1)
    assert fact.original_close == 11
    assert fact.volume == 123
    assert fact.turnover == 456
    assert fact.quality == "partial"
    assert fact.field_lineage["volume"] == "tdx"
    assert fact.field_lineage["turnover"] == "tdx"
    assert fact.field_lineage["adjusted_close"] == "fuyao-adjustment"


def test_missing_adjustment_or_original_close_is_partial_or_insufficient() -> None:
    partial = merge_member_facts(
        [{"security_id": "600001.SH", "date": AS_OF, "close": 11}],
        [],
        source_revision="fuyao-dump-v1",
    )[0]
    assert partial.adjusted_close is None
    assert partial.quality == "partial"
    assert "adjustment factor unavailable" in partial.warnings

    insufficient = merge_member_facts(
        [{"security_id": "600002.SH", "date": AS_OF, "turnover": 100}],
        [],
        source_revision="fuyao-dump-v1",
    )[0]
    assert insufficient.quality == "insufficient"
    assert insufficient.original_close is None


@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1/dump.parquet",
        "https://127.0.0.1/dump.parquet",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/dump.parquet",
        "https://metadata.google.internal/dump.parquet",
    ),
)
def test_dump_downloader_rejects_local_or_metadata_targets_before_request(
    tmp_path, url
) -> None:
    class Session:
        def get(self, *_args, **_kwargs):
            raise AssertionError("unsafe target must not start a request")

    with pytest.raises(FuyaoThsProbeError, match="invalid download target"):
        FuyaoThsDumpDownloader(session=Session()).download(
            url,
            tmp_path / "dump.parquet",
            max_bytes=1024,
        )
