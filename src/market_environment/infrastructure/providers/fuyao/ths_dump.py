"""Explicit Parquet import boundary for Fuyao member facts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from ....domain.models.ths_sector import ThsMemberDailyFact


DumpKind = Literal["daily", "incremental", "adjustment"]
_SECURITY_PATTERN = re.compile(r"^(?:(?P<exchange>SH|SZ|BJ)[._-]?)?(?P<code>\d{6})(?:[._-]?(?P<suffix>SH|SZ|BJ))?$", re.I)
_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class ThsDumpManifest:
    dump_id: str
    kind: DumpKind
    schema_revision: str
    capability_revision: str
    checksum: str
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        for field_name in ("dump_id", "schema_revision", "capability_revision", "checksum"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if self.kind not in {"daily", "incremental", "adjustment"}:
            raise ValueError(f"unsupported dump kind: {self.kind}")
        if self.start_date > self.end_date:
            raise ValueError("dump date range must be ordered")


class ThsDumpContractError(ValueError):
    pass


class FuyaoThsDumpReader:
    SYNTHETIC_COLUMNS = {
        "daily": frozenset({"security_id", "date", "open", "high", "low", "close", "volume", "turnover"}),
        "incremental": frozenset({"security_id", "date", "open", "high", "low", "close", "volume", "turnover"}),
        "adjustment": frozenset({"security_id", "date", "adjustment_factor"}),
    }
    OFFICIAL_COLUMNS = {
        "daily": frozenset(
            {
                "thscode",
                "currency",
                "interval",
                "adjusted",
                "date_ms",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "volume",
                "turnover",
            }
        ),
        "incremental": frozenset(
            {
                "thscode",
                "currency",
                "interval",
                "adjusted",
                "date_ms",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "volume",
                "turnover",
            }
        ),
        "adjustment": frozenset(
            {
                "thscode",
                "ticker",
                "ex_date_ms",
                "dividend_per_share",
                "per_share_bonus",
                "allotment_ratio",
                "allotment_price",
                "currency",
            }
        ),
    }

    def read(self, path: str | Path, manifest: ThsDumpManifest) -> tuple[dict[str, Any], ...]:
        file_path = Path(path)
        if file_path.suffix.lower() not in {".parquet", ".pq"}:
            raise ThsDumpContractError("Fuyao dump import requires a Parquet file")
        if not file_path.is_file():
            raise ThsDumpContractError("Fuyao dump file does not exist")
        checksum = _file_checksum(file_path)
        if checksum != manifest.checksum:
            raise ThsDumpContractError("Fuyao dump checksum mismatch")
        try:
            import pyarrow.parquet as pq

            parquet = pq.ParquetFile(file_path)
        except Exception as exc:
            raise ThsDumpContractError("Fuyao dump Parquet schema cannot be read") from exc
        columns = {str(column) for column in parquet.schema_arrow.names}
        official = self.OFFICIAL_COLUMNS[manifest.kind]
        synthetic = self.SYNTHETIC_COLUMNS[manifest.kind]
        if official <= columns:
            schema = "official"
            selected_columns = tuple(sorted(official))
        elif synthetic <= columns:
            schema = "synthetic"
            selected_columns = tuple(sorted(synthetic))
        else:
            missing = min(
                (official - columns, synthetic - columns),
                key=lambda values: (len(values), sorted(values)),
            )
            raise ThsDumpContractError(
                "Fuyao dump schema is missing columns: " + ", ".join(sorted(missing))
            )
        seen: set[tuple[str, date]] = set()
        normalized: list[dict[str, Any]] = []
        try:
            for batch in parquet.iter_batches(
                columns=list(selected_columns),
                batch_size=65536,
            ):
                for raw in batch.to_pylist():
                    row = self._normalize_row(raw, manifest.kind, schema=schema)
                    security_id = row["security_id"]
                    trading_date = row["date"]
                    if not manifest.start_date <= trading_date <= manifest.end_date:
                        raise ThsDumpContractError(
                            "Fuyao dump row date is outside manifest range"
                        )
                    key = (security_id, trading_date)
                    if key in seen:
                        raise ThsDumpContractError(
                            f"Fuyao dump contains duplicate key {security_id}/{trading_date}"
                        )
                    seen.add(key)
                    normalized.append(row)
        except ThsDumpContractError:
            raise
        except Exception as exc:
            raise ThsDumpContractError(
                "Fuyao dump Parquet rows cannot be read"
            ) from exc
        normalized.sort(key=lambda item: (item["security_id"], item["date"]))
        return tuple(normalized)

    @staticmethod
    def _normalize_row(
        raw: Mapping[str, Any],
        kind: DumpKind,
        *,
        schema: str,
    ) -> dict[str, Any]:
        if schema == "official":
            if str(raw.get("currency") or "").strip().upper() != "CNY":
                raise ThsDumpContractError("Fuyao dump currency must be CNY")
            security_id = normalize_security_id(raw.get("thscode"))
            if kind == "adjustment":
                row = {
                    "security_id": security_id,
                    "date": normalize_millisecond_date(raw.get("ex_date_ms")),
                    "ticker": str(raw.get("ticker") or "").strip(),
                }
                for field_name in (
                    "dividend_per_share",
                    "per_share_bonus",
                    "allotment_ratio",
                    "allotment_price",
                ):
                    row[field_name] = non_negative_number(raw.get(field_name), field_name)
                return row
            if str(raw.get("interval") or "").strip().lower() != "1d":
                raise ThsDumpContractError("Fuyao daily dump interval must be 1d")
            if str(raw.get("adjusted") or "").strip().lower() != "none":
                raise ThsDumpContractError("Fuyao daily dump must be unadjusted")
            row = {
                "security_id": security_id,
                "date": normalize_millisecond_date(raw.get("date_ms")),
                "open": non_negative_number(raw.get("open_price"), "open"),
                "high": non_negative_number(raw.get("high_price"), "high"),
                "low": non_negative_number(raw.get("low_price"), "low"),
                "close": non_negative_number(raw.get("close_price"), "close"),
                "volume": non_negative_number(raw.get("volume"), "volume"),
                "turnover": non_negative_number(raw.get("turnover"), "turnover"),
            }
            _validate_ohlc(row)
            return row

        security_id = normalize_security_id(raw.get("security_id"))
        trading_date = normalize_date(raw.get("date"))
        if kind == "adjustment":
            factor = non_negative_number(raw.get("adjustment_factor"), "adjustment_factor")
            if factor is None or factor <= 0:
                raise ThsDumpContractError("adjustment_factor must be positive")
            return {
                "security_id": security_id,
                "date": trading_date,
                "adjustment_factor": factor,
            }
        row = {
            "security_id": security_id,
            "date": trading_date,
            "open": non_negative_number(raw.get("open"), "open"),
            "high": non_negative_number(raw.get("high"), "high"),
            "low": non_negative_number(raw.get("low"), "low"),
            "close": non_negative_number(raw.get("close"), "close"),
            "volume": non_negative_number(raw.get("volume"), "volume"),
            "turnover": non_negative_number(raw.get("turnover"), "turnover"),
        }
        _validate_ohlc(row)
        return row


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_ohlc(row: Mapping[str, Any]) -> None:
    high = row["high"]
    low = row["low"]
    if None in {row["open"], high, low, row["close"]}:
        raise ThsDumpContractError("Fuyao daily dump requires complete OHLC")
    if high < max(row["open"], low, row["close"]) or low > min(
        row["open"], high, row["close"]
    ):
        raise ThsDumpContractError("Fuyao daily dump contains invalid OHLC bounds")


def normalize_security_id(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = _SECURITY_PATTERN.fullmatch(text)
    if not match:
        raise ThsDumpContractError(f"invalid security identity: {text or 'missing'}")
    code = match.group("code")
    exchange = match.group("suffix") or match.group("exchange")
    if not exchange:
        if code.startswith(("4", "8", "92")):
            exchange = "BJ"
        elif code.startswith(("5", "6", "9")):
            exchange = "SH"
        else:
            exchange = "SZ"
    return f"{code}.{exchange.upper()}"


def normalize_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    text = str(value or "").strip().replace("/", "-")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ThsDumpContractError(f"invalid dump date: {value}") from exc


def normalize_millisecond_date(value: Any) -> date:
    try:
        number = float(value)
        if not math.isfinite(number) or not number.is_integer() or abs(number) < 10_000_000_000:
            raise ValueError
        return datetime.fromtimestamp(number / 1000, _SHANGHAI).date()
    except (TypeError, ValueError, OSError, OverflowError) as exc:
        raise ThsDumpContractError(f"invalid dump millisecond date: {value}") from exc


def non_negative_number(value: Any, field_name: str) -> float | None:
    if value is None or str(value).strip().lower() in {"", "nan", "none", "null"}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ThsDumpContractError(f"invalid {field_name}") from exc
    if not math.isfinite(result) or result < 0:
        raise ThsDumpContractError(f"invalid {field_name}")
    return result


def merge_member_facts(
    daily_rows: Sequence[Mapping[str, Any]],
    adjustment_rows: Sequence[Mapping[str, Any]],
    *,
    source_revision: str,
    tdx_rows: Sequence[Mapping[str, Any]] = (),
) -> tuple[ThsMemberDailyFact, ...]:
    """Combine Fuyao prices/factors with exact-date TDX original-field fallback."""

    factors: dict[tuple[str, date], float] = {}
    for raw in adjustment_rows:
        key = (normalize_security_id(raw.get("security_id")), normalize_date(raw.get("date")))
        if key in factors:
            raise ThsDumpContractError(f"duplicate adjustment key {key[0]}/{key[1]}")
        factor = non_negative_number(raw.get("adjustment_factor"), "adjustment_factor")
        if factor is None or factor <= 0:
            raise ThsDumpContractError("adjustment_factor must be positive")
        factors[key] = factor

    tdx: dict[tuple[str, date], Mapping[str, Any]] = {}
    for raw in tdx_rows:
        key = (normalize_security_id(raw.get("security_id")), normalize_date(raw.get("date")))
        if key in tdx:
            raise ThsDumpContractError(f"duplicate TDX key {key[0]}/{key[1]}")
        tdx[key] = raw

    facts: list[ThsMemberDailyFact] = []
    seen: set[tuple[str, date]] = set()
    for raw in daily_rows:
        security_id = normalize_security_id(raw.get("security_id"))
        trading_date = normalize_date(raw.get("date"))
        key = (security_id, trading_date)
        if key in seen:
            raise ThsDumpContractError(f"duplicate daily key {security_id}/{trading_date}")
        seen.add(key)
        fallback = tdx.get(key, {})
        values: dict[str, float | None] = {}
        lineage: dict[str, str] = {}
        for target, aliases in {
            "original_open": ("open", "original_open"),
            "original_high": ("high", "original_high"),
            "original_low": ("low", "original_low"),
            "original_close": ("close", "original_close"),
            "volume": ("volume",),
            "turnover": ("turnover", "amount"),
        }.items():
            raw_value = next((raw.get(name) for name in aliases if raw.get(name) is not None), None)
            source = "fuyao"
            if raw_value is None:
                raw_value = next(
                    (fallback.get(name) for name in aliases if fallback.get(name) is not None),
                    None,
                )
                source = "tdx" if raw_value is not None else "missing"
            values[target] = non_negative_number(raw_value, target)
            lineage[target] = source
        factor = factors.get(key)
        adjusted_close = (
            values["original_close"] * factor
            if values["original_close"] is not None and factor is not None
            else None
        )
        lineage["adjusted_close"] = "fuyao-adjustment" if adjusted_close is not None else "missing"
        warnings: list[str] = []
        if factor is None:
            warnings.append("adjustment factor unavailable")
        if "tdx" in lineage.values():
            warnings.append("same-day original facts include TDX fallback")
        missing = sorted(field for field, value in values.items() if value is None)
        if missing:
            warnings.append("missing original fields: " + ", ".join(missing))
        if values["original_close"] is None:
            quality = "insufficient"
        elif warnings:
            quality = "partial"
        else:
            quality = "ok"
        logical = {
            "securityId": security_id,
            "tradingDate": trading_date.isoformat(),
            **values,
            "adjustmentFactor": factor,
            "adjustedClose": adjusted_close,
            "sourceRevision": source_revision,
            "fieldLineage": lineage,
        }
        checksum = hashlib.sha256(
            json.dumps(logical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        facts.append(
            ThsMemberDailyFact(
                security_id=security_id,
                trading_date=trading_date,
                original_open=values["original_open"],
                original_high=values["original_high"],
                original_low=values["original_low"],
                original_close=values["original_close"],
                adjusted_close=adjusted_close,
                adjustment_factor=factor,
                volume=values["volume"],
                turnover=values["turnover"],
                quality=quality,
                source_revision=source_revision,
                checksum=checksum,
                field_lineage=lineage,
                warnings=tuple(warnings),
            )
        )
    facts.sort(key=lambda item: (item.security_id, item.trading_date))
    return tuple(facts)


__all__ = [
    "DumpKind",
    "FuyaoThsDumpReader",
    "ThsDumpContractError",
    "ThsDumpManifest",
    "merge_member_facts",
    "normalize_date",
    "normalize_millisecond_date",
    "normalize_security_id",
]
