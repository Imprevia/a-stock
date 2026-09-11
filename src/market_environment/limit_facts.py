"""Strict normalization of dated limit-pool rows.

The provider payloads used by the dashboard are deliberately treated as
untrusted input.  A row is eligible for the V1 denominator only when its
exchange-qualified identity, security classification, applicable limit
regime, and end-of-session close status are explicit and internally coherent.
No display name or default percentage is used to fill missing evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

LIMIT_FACT_SCHEMA_VERSION = 2
POOL_TYPES = frozenset({"limit_up", "failed_limit_up", "limit_down"})
VALID_REGIMES = frozenset(
    {
        "main",
        "chi_next",
        "star",
        "st",
        "ipo",
        "no_limit",
        "pct:5",
        "pct:10",
        "pct:20",
        "pct:30",
    }
)

_EXCHANGE_ALIASES = {
    "0": "SZSE",
    "1": "SSE",
    "2": "BSE",
    "SH": "SSE",
    "SS": "SSE",
    "SSE": "SSE",
    "上交所": "SSE",
    "上海": "SSE",
    "SZ": "SZSE",
    "SZSE": "SZSE",
    "深交所": "SZSE",
    "深圳": "SZSE",
}
_BOARD_ALIASES = {
    "主板": "main",
    "main": "main",
    "main-board": "main",
    "a": "main",
    "创业板": "chi_next",
    "创业": "chi_next",
    "chinext": "chi_next",
    "chi_next": "chi_next",
    "chi-next": "chi_next",
    "gem": "chi_next",
    "科创板": "star",
    "科创": "star",
    "star": "star",
    "science": "star",
}
_SECURITY_ID_RE = re.compile(r"^(?P<exchange>[A-Za-z0-9一-鿿]+)[.:/_-]?(?P<code>\d{6})$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


@dataclass(frozen=True)
class LimitSecurityFactRecord:
    """A normalized, auditable row persisted by :class:`SnapshotStore`."""

    as_of: date
    security_id: str
    pool_type: str
    code: str
    exchange: str
    name: str | None = None
    board: str | None = None
    is_st: bool | None = None
    listing_date: date | None = None
    listing_days: int | None = None
    limit_regime: str | None = None
    close_price: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    touched_limit_up: bool | None = None
    closed_limit_up: bool | None = None
    failed_limit_up: bool | None = None
    streak_days: int | None = None
    eligible: bool = False
    invalid_reason: str | None = None
    source: str = "unknown"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: int = LIMIT_FACT_SCHEMA_VERSION
    row_checksum: str = ""
    dataset_checksum: str | None = None
    actual_as_of: date | None = None

    def logical_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "actual_as_of": self.actual_as_of.isoformat() if self.actual_as_of else None,
            "security_id": self.security_id,
            "pool_type": self.pool_type,
            "code": self.code,
            "exchange": self.exchange,
            "name": self.name,
            "board": self.board,
            "is_st": self.is_st,
            "listing_date": self.listing_date.isoformat() if self.listing_date else None,
            "listing_days": self.listing_days,
            "limit_regime": self.limit_regime,
            "close_price": self.close_price,
            "previous_close": self.previous_close,
            "change_pct": self.change_pct,
            "touched_limit_up": self.touched_limit_up,
            "closed_limit_up": self.closed_limit_up,
            "failed_limit_up": self.failed_limit_up,
            "streak_days": self.streak_days,
            "eligible": self.eligible,
            "invalid_reason": self.invalid_reason,
            "source": self.source,
            "fetched_at": _utc(self.fetched_at).isoformat(),
            "schema_version": self.schema_version,
        }

    def normalized(self) -> "LimitSecurityFactRecord":
        normalized = replace(
            self,
            fetched_at=_utc(self.fetched_at),
            close_price=float(self.close_price) if self.close_price is not None else None,
            previous_close=float(self.previous_close) if self.previous_close is not None else None,
            change_pct=float(self.change_pct) if self.change_pct is not None else None,
            listing_days=int(self.listing_days) if self.listing_days is not None else None,
            streak_days=int(self.streak_days) if self.streak_days is not None else None,
            is_st=bool(self.is_st) if self.is_st is not None else None,
            touched_limit_up=bool(self.touched_limit_up) if self.touched_limit_up is not None else None,
            closed_limit_up=bool(self.closed_limit_up) if self.closed_limit_up is not None else None,
            failed_limit_up=bool(self.failed_limit_up) if self.failed_limit_up is not None else None,
            eligible=bool(self.eligible),
        )
        checksum = normalized.row_checksum or fact_row_checksum(normalized)
        return replace(normalized, row_checksum=checksum)

    def as_dict(self) -> dict[str, Any]:
        value = self.normalized()
        return {
            **value.logical_dict(),
            "row_checksum": value.row_checksum,
            "dataset_checksum": value.dataset_checksum,
        }


# Short aliases make the boundary convenient for provider and test callers.
NormalizedLimitSecurityFact = LimitSecurityFactRecord
LimitSecurityFact = LimitSecurityFactRecord


@dataclass(frozen=True)
class LimitNormalizationResult:
    rows: tuple[LimitSecurityFactRecord, ...]
    as_of: date
    actual_as_of: date | None
    source: str
    complete: bool
    warnings: tuple[str, ...] = ()
    excluded: int = 0
    duplicate_count: int = 0
    dataset_checksum: str = ""
    source_revision: str | None = None
    rule_version: str | None = None

    @property
    def eligible_rows(self) -> tuple[LimitSecurityFactRecord, ...]:
        return tuple(row for row in self.rows if row.eligible)

    def normalized(self) -> "LimitNormalizationResult":
        rows = tuple(row.normalized() for row in self.rows)
        checksum = self.dataset_checksum or limit_dataset_checksum(
            rows,
            as_of=self.as_of,
            actual_as_of=self.actual_as_of,
            source=self.source,
            complete=self.complete,
            warnings=self.warnings,
            source_revision=self.source_revision,
            rule_version=self.rule_version,
            excluded=self.excluded,
        )
        rows = tuple(replace(row, dataset_checksum=checksum) for row in rows)
        return replace(self, rows=rows, dataset_checksum=checksum)


def fact_row_checksum(row: LimitSecurityFactRecord | Mapping[str, Any]) -> str:
    logical = row.logical_dict() if isinstance(row, LimitSecurityFactRecord) else dict(row)
    logical.pop("row_checksum", None)
    logical.pop("dataset_checksum", None)
    # Fetch time is audit metadata, not logical evidence; excluding it keeps
    # deterministic fixture checksums stable across repeated normalizations.
    logical.pop("fetched_at", None)
    for key in ("as_of", "actual_as_of", "listing_date"):
        value = logical.get(key)
        if isinstance(value, (date, datetime)):
            logical[key] = value.isoformat()
    if isinstance(logical.get("fetched_at"), datetime):
        logical["fetched_at"] = _utc(logical["fetched_at"]).isoformat()
    return hashlib.sha256(canonical_json(logical).encode("utf-8")).hexdigest()


def limit_dataset_checksum(
    rows: Iterable[LimitSecurityFactRecord | Mapping[str, Any]],
    *,
    as_of: date,
    actual_as_of: date | None,
    source: str,
    complete: bool,
    warnings: Iterable[str] = (),
    source_revision: str | None = None,
    rule_version: str | None = None,
    schema_version: int = LIMIT_FACT_SCHEMA_VERSION,
    excluded: int = 0,
) -> str:
    canonical_rows = []
    for row in rows:
        value = row.as_dict() if isinstance(row, LimitSecurityFactRecord) else dict(row)
        value.pop("row_checksum", None)
        value.pop("dataset_checksum", None)
        value.pop("fetched_at", None)
        canonical_rows.append(value)
    canonical_rows.sort(key=lambda item: (str(item.get("security_id", "")), str(item.get("pool_type", ""))))
    envelope = {
        "as_of": as_of.isoformat(),
        "actual_as_of": actual_as_of.isoformat() if actual_as_of else None,
        "source": source,
        "source_revision": source_revision,
        "rule_version": rule_version,
        "schema_version": schema_version,
        "complete": bool(complete),
        "excluded": int(excluded),
        "warnings": list(warnings),
        "rows": canonical_rows,
    }
    return hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, "", "-"):
            return row[key]
    return None


def _text(value: Any) -> str | None:
    if value in (None, "", "-"):
        return None
    text = str(value).strip()
    return text or None


def _float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _float(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    text = str(value).strip().lower() if value is not None else ""
    if text in {"true", "yes", "y", "是", "1"}:
        return True
    if text in {"false", "no", "n", "否", "0"}:
        return False
    return None


def _date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    normalized = text.replace("/", "-")
    try:
        if len(normalized) == 8 and normalized.isdigit():
            return datetime.strptime(normalized, "%Y%m%d").date()
        parsed = date.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed


def _session_date(value: Any) -> date | None:
    """Accept an explicit ISO session date, never a datetime or inferred date."""

    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    return _date(value)


def _identity(row: Mapping[str, Any]) -> tuple[str | None, str | None, str | None, str | None]:
    raw_identity = _text(
        _first(row, "security_id", "securityId", "secid", "exchange_qualified_code", "qualified_code")
    )
    code = _text(_first(row, "code", "symbol", "c", "f12"))
    exchange = _text(_first(row, "exchange", "market", "exchange_code", "market_id", "mkt", "f13", "m"))
    if raw_identity:
        match = _SECURITY_ID_RE.match(raw_identity)
        if match:
            embedded_exchange = match.group("exchange")
            embedded_code = match.group("code")
            parsed_code = _extract_code(code)
            if code is not None and parsed_code != embedded_code:
                return None, None, None, "identity-code-mismatch"
            canonical_embedded_exchange = _EXCHANGE_ALIASES.get(embedded_exchange.strip().upper())
            canonical_explicit_exchange = _EXCHANGE_ALIASES.get((exchange or "").strip().upper())
            if (
                exchange is not None
                and canonical_embedded_exchange is not None
                and canonical_explicit_exchange is not None
                and canonical_explicit_exchange != canonical_embedded_exchange
            ):
                return (
                    f"{canonical_embedded_exchange}:{embedded_code}",
                    embedded_code,
                    canonical_explicit_exchange,
                    "identity-exchange-mismatch",
                )
            exchange = exchange or embedded_exchange
            code = code or match.group("code")
        elif raw_identity.isdigit() and len(raw_identity) == 6:
            code = code or raw_identity
        else:
            return None, None, None, "malformed-identity"
    code = _extract_code(code)
    if not code or not re.fullmatch(r"\d{6}", code):
        return None, None, None, "malformed-identity"
    canonical_exchange = _EXCHANGE_ALIASES.get((exchange or "").strip().upper())
    if canonical_exchange is None:
        return None, code, None, "ambiguous-identity"
    return f"{canonical_exchange}:{code}", code, canonical_exchange, None


def _extract_code(value: Any) -> str | None:
    """Extract a six-digit code from a conventional qualified symbol."""

    text = _text(value)
    if text is None:
        return None
    if re.fullmatch(r"\d{6}", text):
        return text
    qualified = re.fullmatch(
        r"(?:[A-Za-z]{1,8}[.:/_-])?(\d{6})|(?:[A-Za-z]{1,8})(\d{6})|(?:(\d{6})[.:/_-][A-Za-z]{1,8})",
        text,
    )
    if qualified:
        return next((group for group in qualified.groups() if group), None)
    return None


def _board(value: Any) -> str | None:
    text = _text(value)
    return _BOARD_ALIASES.get(text.lower()) if text else None


def _regime(row: Mapping[str, Any]) -> str | None:
    value = _first(row, "limit_regime", "limitRegime", "price_limit_regime", "regime")
    text = _text(value)
    if text:
        lowered = text.lower().replace(" ", "-").replace("%", "")
        aliases = {
            "main-10": "main",
            "main10": "main",
            "chi-next-20": "chi_next",
            "chinext-20": "chi_next",
            "star-20": "star",
            "st-5": "st",
            "no-limit": "no_limit",
            "unlimited": "no_limit",
        }
        if lowered in aliases:
            return aliases[lowered]
        if lowered in VALID_REGIMES:
            return lowered
        numeric = _float(lowered)
        if numeric is not None and numeric in {5.0, 10.0, 20.0, 30.0}:
            return f"pct:{int(numeric)}"
        return None
    explicit_pct = _float(_first(row, "limit_pct", "limitPercent", "limit_percentage"))
    if explicit_pct is not None and explicit_pct > 0:
        return f"pct:{int(explicit_pct) if explicit_pct.is_integer() else explicit_pct:g}"
    return None


def _regime_limit_pct(regime: str | None) -> float | None:
    if regime in {"main", "pct:10"}:
        return 10.0
    if regime == "st" or regime == "pct:5":
        return 5.0
    if regime in {"chi_next", "star", "pct:20"}:
        return 20.0
    if regime == "pct:30":
        return 30.0
    return None


def _rounded_limit_price(previous_close: float, regime: str | None) -> float | None:
    """Calculate a declared regime's tick-rounded limit for close validation."""

    limit_pct = _regime_limit_pct(regime)
    if limit_pct is None or previous_close <= 0:
        return None
    # Decimal avoids binary float drift at the one-cent tick boundary.
    from decimal import Decimal, ROUND_HALF_UP

    value = Decimal(str(previous_close)) * (Decimal("1") + Decimal(str(limit_pct)) / Decimal("100"))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _on_price_tick(value: float) -> bool:
    return math.isclose(value, round(value, 2), rel_tol=0.0, abs_tol=1e-9)


def _normalize_row(
    raw: Mapping[str, Any],
    *,
    as_of: date,
    actual_as_of: date | None,
    pool_type: str,
    source: str,
    fetched_at: datetime | None,
) -> LimitSecurityFactRecord:
    identity, code, exchange, identity_error = _identity(raw)
    row_date_value = _first(
        raw,
        "actual_as_of",
        "actualAsOf",
        "trade_date",
        "tradeDate",
        "as_of",
        "asOf",
        "date",
    )
    row_actual_as_of = _session_date(row_date_value)
    row_date_error = row_date_value is not None and row_actual_as_of is None
    board = _board(_first(raw, "board", "board_name", "security_board", "market_board"))
    is_st = _bool(_first(raw, "is_st", "isST", "st", "st_flag"))
    listing_date_value = _first(raw, "listing_date", "listingDate", "ipo_date")
    listing_date = _date(listing_date_value)
    listing_date_error = listing_date_value is not None and listing_date is None
    listing_days = _int(_first(raw, "listing_days", "listingDays", "listed_days"))
    if listing_days is None and listing_date is not None:
        listing_days = (as_of - listing_date).days
    ipo_window = _bool(_first(raw, "ipo_window", "ipoWindow", "is_ipo_window"))
    regime = _regime(raw)
    close_value = _first(raw, "close_price", "closePrice", "close", "price", "f2")
    close_price = _float(close_value)
    # Eastmoney limit-pool ``p`` is an integer price in thousandths; only
    # apply this conversion to that explicitly named provider field.
    if close_price is None and _first(raw, "p") is not None:
        raw_price = _float(_first(raw, "p"))
        close_price = raw_price / 1000 if raw_price is not None else None
    previous_close = _float(_first(raw, "previous_close", "previousClose", "pre_close", "last_close", "f18"))
    change_pct = _float(_first(raw, "change_pct", "changePct", "pct", "f3", "zdp"))
    touched = _bool(_first(raw, "touched_limit_up", "touchedLimitUp", "touch_limit_up"))
    closed = _bool(_first(raw, "closed_limit_up", "closedLimitUp", "close_limit_up", "is_limit_up"))
    if closed is None:
        limit_price = _float(_first(raw, "limit_price", "limitPrice"))
        if limit_price is not None and close_price is not None:
            # A close must land on the declared tick-rounded limit, not merely
            # exceed it.  This does not infer a limit from a board or a name.
            closed = (
                _on_price_tick(close_price)
                and _on_price_tick(limit_price)
                and math.isclose(close_price, limit_price, rel_tol=0.0, abs_tol=1e-9)
                and close_price > 0
            )
        elif close_price is not None and previous_close is not None and _on_price_tick(previous_close):
            declared_limit = _rounded_limit_price(previous_close, regime)
            if declared_limit is not None:
                closed = (
                    _on_price_tick(close_price)
                    and math.isclose(close_price, declared_limit, rel_tol=0.0, abs_tol=1e-9)
                    and close_price > 0
                )
    failed = _bool(_first(raw, "failed_limit_up", "failedLimitUp", "is_failed_limit_up"))
    streak = _int(_first(raw, "streak_days", "streakDays", "lbc"))

    reason: str | None = identity_error
    if reason is None and row_date_error:
        reason = "invalid-provider-row-date"
    if reason is None and row_actual_as_of is not None and actual_as_of is not None and row_actual_as_of != actual_as_of:
        reason = "provider-row-date-mismatch"
    if reason is None and actual_as_of is None:
        reason = "missing-actual-session-date"
    if reason is None and actual_as_of != as_of:
        reason = "provider-date-mismatch"
    if reason is None and board is None:
        reason = "missing-board"
    if reason is None and is_st is None:
        reason = "missing-st-status"
    if reason is None and regime == "st" and is_st is False:
        reason = "st-regime-identity-mismatch"
    if reason is None and listing_date_error:
        reason = "invalid-listing-date"
    if reason is None and (listing_days is None or listing_days < 0):
        reason = "missing-listing-window"
    if reason is None and (ipo_window or listing_days is not None and listing_days < 5):
        reason = "ipo-window"
    if reason is None and regime is None:
        reason = "missing-limit-regime"
    if reason is None and (close_price is None or close_price <= 0):
        reason = "missing-close"
    if reason is None and pool_type in {"limit_up", "failed_limit_up"} and closed is None:
        reason = "missing-close-limit-status"
    if reason is None and pool_type == "limit_up" and closed is False:
        reason = "intraday-touch-not-closed"
    if reason is None and pool_type == "failed_limit_up" and closed is True:
        reason = "contradictory-pool"
    if reason is None and pool_type == "limit_up" and touched is True and closed is False:
        reason = "intraday-touch-not-closed"
    if reason is None and is_st is True:
        reason = "st-security"
    if reason is None and pool_type != "limit_up":
        reason = "not-v1-pool"

    return LimitSecurityFactRecord(
        as_of=as_of,
        actual_as_of=actual_as_of,
        security_id=identity or "",
        pool_type=pool_type,
        code=code or "",
        exchange=exchange or "",
        name=_text(_first(raw, "name", "security_name", "f14", "n")),
        board=board,
        is_st=is_st,
        listing_date=listing_date,
        listing_days=listing_days,
        limit_regime=regime,
        close_price=close_price,
        previous_close=previous_close,
        change_pct=change_pct,
        touched_limit_up=touched,
        closed_limit_up=closed,
        failed_limit_up=failed if failed is not None else pool_type == "failed_limit_up",
        streak_days=streak,
        eligible=reason is None,
        invalid_reason=reason,
        source=source,
        fetched_at=_utc(fetched_at),
    ).normalized()


def normalize_limit_rows(
    rows: Iterable[Any],
    *,
    as_of: date,
    pool_type: str,
    actual_as_of: date | None = None,
    source: str = "provider",
    fetched_at: datetime | None = None,
    source_revision: str | None = None,
    rule_version: str | None = None,
) -> LimitNormalizationResult:
    """Normalize one dated pool and reject ambiguous/duplicate evidence."""

    if pool_type not in POOL_TYPES:
        raise ValueError(f"unsupported limit pool type: {pool_type}")
    actual_as_of = _session_date(actual_as_of)
    normalized: list[LimitSecurityFactRecord] = []
    warnings: list[str] = []
    seen: dict[str, list[int]] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            normalized.append(
                LimitSecurityFactRecord(
                    as_of=as_of,
                    actual_as_of=actual_as_of,
                    security_id=f"invalid:{pool_type}:{index}",
                    pool_type=pool_type,
                    code="",
                    exchange="",
                    eligible=False,
                    invalid_reason="malformed-row",
                    source=source,
                    fetched_at=_utc(fetched_at),
                ).normalized()
            )
            continue
        row = _normalize_row(
            raw,
            as_of=as_of,
            actual_as_of=actual_as_of,
            pool_type=pool_type,
            source=source,
            fetched_at=fetched_at,
        )
        normalized.append(row)
        if row.security_id:
            seen.setdefault(row.security_id, []).append(index)

    duplicate_count = 0
    duplicate_ids = {security_id for security_id, indexes in seen.items() if len(indexes) > 1}
    if duplicate_ids:
        duplicate_count = len(duplicate_ids)
        rewritten = []
        retained_duplicate_ids: set[str] = set()
        for row in normalized:
            if row.security_id in duplicate_ids:
                if row.security_id in retained_duplicate_ids:
                    continue
                retained_duplicate_ids.add(row.security_id)
                rewritten.append(
                    replace(row, eligible=False, invalid_reason="duplicate-security", row_checksum="").normalized()
                )
            else:
                rewritten.append(row)
        normalized = rewritten
        warnings.append(f"duplicate security identities excluded: {len(duplicate_ids)}")

    excluded = sum(not row.eligible for row in normalized)
    if not normalized:
        warnings.append("empty limit pool")
    if excluded:
        warnings.append(f"excluded {excluded} invalid limit rows")
    malformed_rows = sum(row.invalid_reason == "malformed-row" for row in normalized)
    if malformed_rows:
        warnings.append(f"malformed-row excluded: {malformed_rows} row(s)")
    row_date_mismatches = sum(row.invalid_reason == "provider-row-date-mismatch" for row in normalized)
    invalid_row_dates = sum(row.invalid_reason == "invalid-provider-row-date" for row in normalized)
    if row_date_mismatches:
        warnings.append(f"provider row date mismatch: {row_date_mismatches} row(s)")
    if invalid_row_dates:
        warnings.append(f"invalid provider row date: {invalid_row_dates} row(s)")
    non_v1_reasons = {"not-v1-pool"}
    complete = (actual_as_of is not None and actual_as_of == as_of) and all(
        row.invalid_reason in {None, *non_v1_reasons} for row in normalized
    )
    result = LimitNormalizationResult(
        rows=tuple(normalized),
        as_of=as_of,
        actual_as_of=actual_as_of,
        source=source,
        complete=complete,
        warnings=tuple(warnings),
        excluded=excluded,
        duplicate_count=duplicate_count,
        source_revision=source_revision,
        rule_version=rule_version,
    )
    return result.normalized()


def normalize_limit_pools(
    pools: Mapping[str, Iterable[Any]],
    *,
    as_of: date,
    actual_as_of: date | None = None,
    source: str = "provider",
    fetched_at: datetime | None = None,
    source_revision: str | None = None,
    rule_version: str | None = None,
) -> LimitNormalizationResult:
    """Normalize all pools as one dataset while keeping pool membership distinct."""

    actual_as_of = _session_date(actual_as_of)
    rows: list[LimitSecurityFactRecord] = []
    warnings: list[str] = []
    complete = True
    duplicate_count = 0
    for pool_type in ("limit_up", "failed_limit_up", "limit_down"):
        pool = pools.get(pool_type)
        if pool is None:
            complete = False
            warnings.append(f"missing {pool_type} pool")
            continue
        result = normalize_limit_rows(
            pool,
            as_of=as_of,
            actual_as_of=actual_as_of,
            pool_type=pool_type,
            source=source,
            fetched_at=fetched_at,
            source_revision=source_revision,
            rule_version=rule_version,
        )
        rows.extend(result.rows)
        warnings.extend(result.warnings)
        complete = complete and result.complete
        duplicate_count += result.duplicate_count
    by_identity: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        if row.security_id:
            by_identity.setdefault(row.security_id, []).append(index)
    conflicting_ids = {
        security_id
        for security_id, indexes in by_identity.items()
        if len({rows[index].pool_type for index in indexes}) > 1
    }
    if conflicting_ids:
        rewritten = []
        for row in rows:
            if row.security_id in conflicting_ids:
                rewritten.append(
                    replace(
                        row,
                        eligible=False,
                        invalid_reason="conflicting-pool-membership",
                        row_checksum="",
                    ).normalized()
                )
            else:
                rewritten.append(row)
        rows = rewritten
        complete = False
        warnings.append(f"conflicting pool memberships excluded: {len(conflicting_ids)}")
    result = LimitNormalizationResult(
        rows=tuple(rows),
        as_of=as_of,
        actual_as_of=actual_as_of,
        source=source,
        complete=complete,
        warnings=tuple(warnings),
        excluded=sum(not row.eligible for row in rows),
        duplicate_count=duplicate_count,
        source_revision=source_revision,
        rule_version=rule_version,
    )
    return result.normalized()


__all__ = [
    "LIMIT_FACT_SCHEMA_VERSION",
    "LimitSecurityFactRecord",
    "LimitSecurityFact",
    "NormalizedLimitSecurityFact",
    "LimitNormalizationResult",
    "normalize_limit_rows",
    "normalize_limit_pools",
    "fact_row_checksum",
    "limit_dataset_checksum",
]
