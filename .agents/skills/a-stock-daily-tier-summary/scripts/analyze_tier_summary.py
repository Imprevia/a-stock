#!/usr/bin/env python3
"""Deterministic high/middle/low tier post-close analysis.

The default mode consumes caller-provided JSON. Local and Eastmoney adapters
are read-only GET clients; neither adapter starts collection or writes state.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from statistics import median
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


POOL_TYPES = ("limit_up", "failed_limit_up", "limit_down")
TIERS = ("high", "middle", "low")
TIER_CN = {"high": "高位", "middle": "中位", "low": "低位"}
QUALITY_ORDER = {
    "ok": 0,
    "fallback": 1,
    "fallback-derived": 1,
    "degraded": 1,
    "partial": 1,
    "unverified": 1,
    "missing": 2,
    "failed": 2,
    "failed-retained": 2,
    "failed-missing": 2,
    "insufficient": 2,
}
SHANGHAI = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = "1.0"
EXPECTED_INDICES = (
    ("上证指数", "000001.SH"),
    ("深证成指", "399001.SZ"),
    ("创业板指", "399006.SZ"),
    ("沪深300", "000300.SH"),
    ("中证500", "000905.SH"),
)
INDEX_NAMES = tuple(name for name, _code in EXPECTED_INDICES)
INDEX_NAME_BY_CODE = {code: name for name, code in EXPECTED_INDICES}
SYNC_PATTERN_LABELS = {
    "synchronized_rally": "同步上涨",
    "broad_weakness": "普遍走弱",
    "weight_shelter": "权重护盘",
    "growth_lead": "成长占优",
    "undetermined_divergence": "分化未定型",
}


class TierSummaryError(ValueError):
    """Base error for input that cannot support a deterministic result."""


class DateEvidenceError(TierSummaryError):
    """Raised when explicit source dates contradict the requested session."""


class ConflictingRowsError(TierSummaryError):
    """Raised when one exchange-qualified identity has conflicting facts."""


class ReadError(TierSummaryError):
    """Raised for malformed or inconsistent read responses."""


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _unique_strings(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value).strip()))


@dataclass(frozen=True, slots=True)
class Quality:
    status: str = "ok"
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "warnings": list(self.warnings)}


def _quality(value: Any, *extra_warnings: str, floor: str | None = None) -> Quality:
    raw = value if isinstance(value, Mapping) else {}
    status = str(raw.get("status") or "ok")
    if status not in QUALITY_ORDER:
        status = "degraded"
    if floor is not None and QUALITY_ORDER[status] < QUALITY_ORDER[floor]:
        status = floor
    warnings_value = raw.get("warnings") or []
    if isinstance(warnings_value, str):
        warnings_value = [warnings_value]
    return Quality(status, _unique_strings([*warnings_value, *extra_warnings]))


def merge_quality(*values: Quality, warnings: Sequence[str] = ()) -> Quality:
    if not values:
        return Quality("ok", _unique_strings(warnings))
    status = max(values, key=lambda item: QUALITY_ORDER.get(item.status, 1)).status
    combined = [warning for value in values for warning in value.warnings]
    return Quality(status, _unique_strings([*combined, *warnings]))


@dataclass(frozen=True, order=True, slots=True)
class SecurityIdentity:
    exchange: str
    code: str

    @property
    def security_id(self) -> str:
        return f"{self.exchange}:{self.code}"

    def to_dict(self) -> dict[str, str]:
        return {"exchange": self.exchange, "code": self.code, "securityId": self.security_id}


EXCHANGE_ALIASES = {
    "SH": "SH",
    "SSE": "SH",
    "XSHG": "SH",
    "1": "SH",
    "SZ": "SZ",
    "SZSE": "SZ",
    "XSHE": "SZ",
    "0": "SZ",
    "BJ": "BJ",
    "BSE": "BJ",
    "XBEI": "BJ",
}


def _infer_exchange(code: str) -> str | None:
    if code.startswith(("4", "8", "92")):
        return "BJ"
    if code.startswith(("5", "6", "9")):
        return "SH"
    if code.startswith(("0", "1", "2", "3")):
        return "SZ"
    return None


def normalize_identity(row: Mapping[str, Any]) -> SecurityIdentity:
    security_id = row.get("securityId") or row.get("security_id") or row.get("secid")
    raw_exchange = row.get("exchange") or row.get("market") or row.get("m")
    raw_code = row.get("code") or row.get("ticker") or row.get("c") or row.get("f12")
    if security_id and isinstance(security_id, str):
        text = security_id.strip().upper()
        if ":" in text:
            prefix, suffix = text.split(":", 1)
            raw_exchange = raw_exchange or prefix
            raw_code = raw_code or suffix
        elif "." in text:
            prefix, suffix = text.split(".", 1)
            if prefix.isdigit():
                raw_code = raw_code or prefix
                raw_exchange = raw_exchange or suffix
    if isinstance(raw_code, str) and "." in raw_code:
        prefix, suffix = raw_code.upper().split(".", 1)
        raw_code = prefix
        raw_exchange = raw_exchange or suffix
    code = str(raw_code or "").strip()
    if not code.isdigit() or len(code) > 6:
        raise TierSummaryError(f"invalid security code: {raw_code!r}")
    code = code.zfill(6)
    exchange = EXCHANGE_ALIASES.get(str(raw_exchange).strip().upper()) if raw_exchange is not None else None
    exchange = exchange or _infer_exchange(code)
    if exchange is None:
        raise TierSummaryError(f"cannot determine exchange for code {code}")
    return SecurityIdentity(exchange, code)


@dataclass(frozen=True, slots=True)
class PoolMember:
    identity: SecurityIdentity
    name: str | None = None
    streak_days: int | None = None
    pattern_days: int | None = None

    def signature(self) -> tuple[Any, ...]:
        return (self.name or None, self.streak_days, self.pattern_days)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity.to_dict(),
            "name": self.name,
            "streakDays": self.streak_days,
            "patternDays": self.pattern_days,
        }


@dataclass(frozen=True, slots=True)
class Pool:
    pool_type: str
    members: tuple[PoolMember, ...]
    quality: Quality

    @property
    def identities(self) -> set[SecurityIdentity]:
        return {member.identity for member in self.members}

    def to_evidence(self) -> dict[str, Any]:
        return {
            "poolType": self.pool_type,
            "count": len(self.members),
            "quality": self.quality.to_dict(),
        }


def _row_streak(row: Mapping[str, Any], source_kind: str) -> int | None:
    keys = ("lbc",) if source_kind == "eastmoney" else ("streak_days", "streakDays")
    for key in keys:
        if key in row:
            value = _as_int(row.get(key))
            return value if value is not None and value >= 1 else None
    return None


def _pattern_days(row: Mapping[str, Any]) -> int | None:
    zttj = row.get("zttj")
    return _as_int(zttj.get("days")) if isinstance(zttj, Mapping) else None


def normalize_pool(pool_type: str, value: Any, *, source_kind: str) -> Pool:
    if pool_type not in POOL_TYPES:
        raise TierSummaryError(f"unsupported pool: {pool_type}")
    payload = value if isinstance(value, Mapping) else {"rows": value}
    rows = payload.get("rows", payload.get("items", []))
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise TierSummaryError(f"{pool_type} rows must be an array")
    normalized: dict[SecurityIdentity, PoolMember] = {}
    warnings: list[str] = []
    missing_streak = 0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            warnings.append(f"{pool_type} row {index} is not an object and was excluded")
            continue
        try:
            identity = normalize_identity(row)
        except TierSummaryError as exc:
            warnings.append(f"{pool_type} row {index} excluded: {exc}")
            continue
        streak = _row_streak(row, source_kind) if pool_type == "limit_up" else None
        if pool_type == "limit_up" and streak is None:
            missing_streak += 1
        member = PoolMember(
            identity=identity,
            name=str(row.get("name") or row.get("n") or "").strip() or None,
            streak_days=streak,
            pattern_days=_pattern_days(row),
        )
        existing = normalized.get(identity)
        if existing is None:
            normalized[identity] = member
            continue
        if existing.signature() != member.signature():
            raise ConflictingRowsError(
                f"conflicting duplicate in {pool_type}: {identity.security_id}"
            )
        warnings.append(f"duplicate {identity.security_id} in {pool_type} counted once")
    if missing_streak:
        warnings.append(f"{missing_streak} limit-up members lack a valid consecutive-board field")
    floor = "degraded" if warnings else None
    quality = _quality(payload.get("quality"), *warnings, floor=floor)
    return Pool(pool_type, tuple(normalized[key] for key in sorted(normalized)), quality)


@dataclass(frozen=True, slots=True)
class SourceDateEvidence:
    requested_date: date
    actual_date: date | None
    request_date: date | None = None
    qdate: date | None = None
    revision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requestedDate": self.requested_date.isoformat(),
            "actualDate": self.actual_date.isoformat() if self.actual_date else None,
            "requestDate": self.request_date.isoformat() if self.request_date else None,
            "qdate": self.qdate.isoformat() if self.qdate else None,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class Session:
    requested_date: date
    source: str
    source_kind: str
    date_evidence: SourceDateEvidence
    previous_session: date | None
    pools: Mapping[str, Pool]
    quality: Quality

    def source_evidence(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "sourceKind": self.source_kind,
            "dateEvidence": self.date_evidence.to_dict(),
            "quality": self.quality.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class EnvironmentIndex:
    name: str
    code: str
    change_pct: float | None
    close: float | None
    ma20: float | None
    amount_ratio5: float | None
    volume_price_state: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "code": self.code,
            "changePct": self.change_pct,
            "close": self.close,
            "ma20": self.ma20,
            "amountRatio5": self.amount_ratio5,
            "volumePriceState": self.volume_price_state,
        }


@dataclass(frozen=True, slots=True)
class MarketEnvironmentInput:
    as_of: date
    revision: str
    indices: tuple[EnvironmentIndex, ...]
    breadth: Mapping[str, Any]
    assessment: Mapping[str, Any] | None
    market_evidence: Mapping[str, Any] | None
    quality: Quality

    def source_evidence(self) -> dict[str, Any]:
        return {
            "asOf": self.as_of.isoformat(),
            "revision": self.revision,
            "quality": self.quality.to_dict(),
        }


def session_from_dict(value: Mapping[str, Any]) -> Session:
    requested = _as_date(value.get("requestedDate") or value.get("asOf"))
    if requested is None:
        raise DateEvidenceError("session requestedDate is missing or invalid")
    source = str(value.get("source") or "fixture")
    source_kind = str(value.get("sourceKind") or ("eastmoney" if "eastmoney" in source.lower() else "local"))
    actual_raw = value.get("actualDate") or value.get("actualAsOf")
    qdate = _as_date(value.get("qdate"))
    actual = _as_date(actual_raw) or qdate
    request_date = _as_date(value.get("requestDate"))
    if actual_raw is not None and actual is None:
        raise DateEvidenceError(f"invalid actual date evidence for {requested.isoformat()}")
    if value.get("qdate") is not None and qdate is None:
        raise DateEvidenceError(f"invalid qdate evidence for {requested.isoformat()}")
    if actual is not None and actual != requested:
        raise DateEvidenceError(
            f"source date contradiction: requested {requested.isoformat()}, actual {actual.isoformat()}"
        )
    date_warnings: list[str] = []
    date_floor = None
    if source_kind == "eastmoney" and actual is None:
        date_warnings.append("external source has request-date-only evidence")
        date_floor = "degraded"
    elif source_kind != "eastmoney" and actual is None:
        raise DateEvidenceError(f"local exact-date evidence is missing for {requested.isoformat()}")
    pools_value = value.get("pools")
    if not isinstance(pools_value, Mapping):
        raise TierSummaryError("session pools must be an object")
    pools: dict[str, Pool] = {}
    for pool_type in POOL_TYPES:
        if pool_type not in pools_value:
            raise TierSummaryError(f"session is missing required pool {pool_type}")
        pools[pool_type] = normalize_pool(pool_type, pools_value[pool_type], source_kind=source_kind)
    session_quality = merge_quality(
        _quality(value.get("quality"), *date_warnings, floor=date_floor),
        *(pool.quality for pool in pools.values()),
    )
    return Session(
        requested_date=requested,
        source=source,
        source_kind=source_kind,
        date_evidence=SourceDateEvidence(
            requested_date=requested,
            actual_date=actual,
            request_date=request_date,
            qdate=qdate,
            revision=str(value.get("revision")) if value.get("revision") else None,
        ),
        previous_session=_as_date(value.get("previousSession") or value.get("previousAsOf")),
        pools=pools,
        quality=session_quality,
    )


def _environment_index_name(row: Mapping[str, Any]) -> str | None:
    raw_name = str(row.get("name") or "").strip()
    raw_code = str(row.get("code") or row.get("securityId") or "").strip().upper()
    by_name = raw_name if raw_name in INDEX_NAMES else None
    by_code = INDEX_NAME_BY_CODE.get(raw_code)
    if by_name and by_code and by_name != by_code:
        raise ReadError(f"index identity conflict: name {raw_name}, code {raw_code}")
    return by_name or by_code


def _normalized_environment_indices(value: Any) -> tuple[EnvironmentIndex, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ReadError("market environment indices must be an array")
    rows: dict[str, EnvironmentIndex] = {}
    for row in value:
        if not isinstance(row, Mapping):
            continue
        name = _environment_index_name(row)
        if name is None:
            continue
        if name in rows:
            raise ReadError(f"duplicate expected index identity: {name}")
        canonical_code = next(code for expected_name, code in EXPECTED_INDICES if expected_name == name)
        averages = row.get("movingAverages")
        ma20 = _as_float(averages.get("ma20")) if isinstance(averages, Mapping) else None
        rows[name] = EnvironmentIndex(
            name=name,
            code=canonical_code,
            change_pct=_as_float(row.get("changePct")),
            close=_as_float(row.get("close")),
            ma20=ma20,
            amount_ratio5=_as_float(row.get("amountRatio5")),
            volume_price_state=str(row.get("volumePriceState") or "").strip() or None,
        )
    missing = [name for name in INDEX_NAMES if name not in rows]
    if missing:
        raise ReadError(f"missing expected index identities: {', '.join(missing)}")
    return tuple(rows[name] for name in INDEX_NAMES)


def _raw_environment_facts(indices: Sequence[EnvironmentIndex], breadth: Mapping[str, Any]) -> dict[str, Any]:
    valid_changes = [item.change_pct for item in indices if item.change_pct is not None]
    ma20_positions = [
        item.close >= item.ma20
        for item in indices
        if item.close is not None and item.ma20 is not None
    ]
    amount_ratios = [item.amount_ratio5 for item in indices if item.amount_ratio5 is not None]
    volume_advance = sum(
        item.volume_price_state == "上涨放量"
        or (
            item.change_pct is not None
            and item.change_pct >= 0.5
            and item.amount_ratio5 is not None
            and item.amount_ratio5 >= 1.2
        )
        for item in indices
    )
    volume_decline = sum(
        item.volume_price_state == "放量下跌"
        or (
            item.change_pct is not None
            and item.change_pct <= -0.5
            and item.amount_ratio5 is not None
            and item.amount_ratio5 >= 1.2
        )
        for item in indices
    )
    return {
        "advancingIndexCount": sum(value > 0 for value in valid_changes),
        "decliningIndexCount": sum(value < 0 for value in valid_changes),
        "validIndexCount": len(valid_changes),
        "aboveMa20Count": sum(ma20_positions),
        "ma20ValidCount": len(ma20_positions),
        "medianAmountRatio5": round(float(median(amount_ratios)), 4) if amount_ratios else None,
        "volumeBackedAdvanceCount": volume_advance if amount_ratios else None,
        "volumeBackedDeclineCount": volume_decline if amount_ratios else None,
        "advanceRatio": _as_float(breadth.get("advanceRatio")),
        "medianReturn": _as_float(breadth.get("medianReturn")),
    }


def _assert_canonical_evidence_consistent(
    indices: Sequence[EnvironmentIndex],
    breadth: Mapping[str, Any],
    assessment: Mapping[str, Any] | None,
    market_evidence: Mapping[str, Any] | None,
) -> None:
    if assessment and market_evidence:
        assessment_pattern = assessment.get("patternCode")
        evidence_pattern = market_evidence.get("directionPattern")
        if assessment_pattern is not None and evidence_pattern is not None and assessment_pattern != evidence_pattern:
            raise ReadError(
                "conflicting canonical direction pattern: "
                f"assessment={assessment_pattern}, marketEvidence={evidence_pattern}"
            )
    if not market_evidence:
        return
    observed = _raw_environment_facts(indices, breadth)
    integer_fields = (
        "advancingIndexCount",
        "decliningIndexCount",
        "validIndexCount",
        "aboveMa20Count",
        "ma20ValidCount",
        "volumeBackedAdvanceCount",
        "volumeBackedDeclineCount",
    )
    for field_name in integer_fields:
        canonical = _as_int(market_evidence.get(field_name))
        if canonical is not None and observed[field_name] is not None and canonical != observed[field_name]:
            raise ReadError(
                f"conflicting canonical environment evidence for {field_name}: "
                f"expected {observed[field_name]}, got {canonical}"
            )
    for field_name in ("medianAmountRatio5", "advanceRatio", "medianReturn"):
        canonical = _as_float(market_evidence.get(field_name))
        actual = observed[field_name]
        if canonical is not None and actual is not None and not math.isclose(canonical, actual, abs_tol=1e-4):
            raise ReadError(
                f"conflicting canonical environment evidence for {field_name}: "
                f"expected {actual}, got {canonical}"
            )


def market_environment_from_dict(
    value: Mapping[str, Any], current: Session
) -> MarketEnvironmentInput:
    as_of = _as_date(value.get("asOf") or value.get("requestedDate"))
    if as_of is None:
        raise DateEvidenceError("market environment asOf is missing or invalid")
    if as_of != current.requested_date:
        raise DateEvidenceError(
            f"market environment date {as_of.isoformat()} does not match current session "
            f"{current.requested_date.isoformat()}"
        )
    revision = str(value.get("revision") or value.get("snapshotRevision") or "")
    current_revision = current.date_evidence.revision
    if not revision:
        raise ReadError("market environment revision is missing")
    if not current_revision:
        raise ReadError("current session revision is missing for combined review")
    if revision != current_revision:
        raise ReadError(
            f"market environment revision {revision} does not match current session revision {current_revision}"
        )
    indices = _normalized_environment_indices(value.get("indices"))
    breadth = value.get("breadth")
    if not isinstance(breadth, Mapping):
        raise ReadError("market environment breadth must be an object")
    summary = value.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    assessment = summary.get("synchronizationAssessment")
    if assessment is not None and not isinstance(assessment, Mapping):
        raise ReadError("synchronizationAssessment must be an object or null")
    market_evidence = summary.get("marketEvidence", value.get("marketEvidence"))
    if market_evidence is not None and not isinstance(market_evidence, Mapping):
        raise ReadError("marketEvidence must be an object or null")
    _assert_canonical_evidence_consistent(indices, breadth, assessment, market_evidence)
    breadth_quality = _quality(breadth.get("quality"))
    return MarketEnvironmentInput(
        as_of=as_of,
        revision=revision,
        indices=indices,
        breadth=dict(breadth),
        assessment=dict(assessment) if assessment else None,
        market_evidence=dict(market_evidence) if market_evidence else None,
        quality=merge_quality(_quality(value.get("quality")), breadth_quality),
    )


@dataclass(frozen=True, slots=True)
class ResolvedRequest:
    relative: str
    literal_date: date
    session_date: date
    literal_date_closed: bool
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative": self.relative,
            "literalDate": self.literal_date.isoformat(),
            "sessionDate": self.session_date.isoformat(),
            "literalDateClosed": self.literal_date_closed,
            "note": self.note,
        }


def resolve_relative_session(
    relative: str,
    *,
    now: datetime,
    trading_sessions: Sequence[date],
    close_time: time = time(15, 0),
) -> ResolvedRequest:
    if relative not in {"today", "yesterday"}:
        raise DateEvidenceError("relative date must be today or yesterday")
    local_now = now.astimezone(SHANGHAI) if now.tzinfo else now.replace(tzinfo=SHANGHAI)
    literal = local_now.date()
    if relative == "yesterday":
        literal = date.fromordinal(literal.toordinal() - 1)
    completed = sorted(set(trading_sessions))
    if relative == "today" and local_now.time() < close_time:
        candidates = [item for item in completed if item < literal]
    else:
        candidates = [item for item in completed if item <= literal]
    if not candidates:
        raise DateEvidenceError("trusted calendar cannot prove a completed target session")
    resolved = candidates[-1]
    closed = resolved != literal
    note = None
    if closed:
        reason = "尚未收盘" if relative == "today" and local_now.time() < close_time else "休市"
        note = f"{literal.isoformat()} {reason}，使用最近已完成交易日 {resolved.isoformat()}"
    return ResolvedRequest(relative, literal, resolved, closed, note)


class JsonGetTransport(Protocol):
    def get_json(self, url: str, *, timeout: float, headers: Mapping[str, str] | None = None) -> Mapping[str, Any]: ...


class UrllibJsonTransport:
    def get_json(
        self,
        url: str,
        *,
        timeout: float,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        request = Request(url, headers=dict(headers or {}), method="GET")
        with urlopen(request, timeout=timeout) as response:  # nosec B310 - explicit read-only URL
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ReadError("JSON response must be an object")
        return payload


def _url(base: str, path: str, params: Mapping[str, Any] | None = None) -> str:
    result = f"{base.rstrip('/')}/{path.lstrip('/')}"
    filtered = {key: value for key, value in (params or {}).items() if value is not None}
    return f"{result}?{urlencode(filtered)}" if filtered else result


def _validate_local_envelope(
    body: Mapping[str, Any], as_of: date, revision: str | None, resource: str
) -> str:
    response_date = _as_date(body.get("asOf"))
    if response_date != as_of:
        raise DateEvidenceError(
            f"local v2 {resource} date mismatch: requested {as_of.isoformat()}, "
            f"got {body.get('asOf')!r}"
        )
    response_revision = str(body.get("snapshotRevision") or "")
    if not response_revision:
        raise ReadError(f"local v2 {resource} response is missing snapshotRevision")
    if revision is not None and response_revision != revision:
        raise ReadError(f"local v2 {resource} changed snapshotRevision")
    return response_revision


def _fetch_local_pool_rows(
    base_url: str,
    root: str,
    as_of: date,
    revision: str,
    pool_type: str,
    transport: JsonGetTransport,
    timeout: float,
) -> dict[str, Any]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    rows: list[Mapping[str, Any]] = []
    page_qualities: list[Quality] = []
    for _page_number in range(1000):
        params = {"limit": 100, "revision": revision, "cursor": cursor}
        body = transport.get_json(
            _url(base_url, f"{root}/pools/{pool_type}", params),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        _validate_local_envelope(body, as_of, revision, f"{pool_type} page")
        data = body.get("data")
        items = data.get("items") if isinstance(data, Mapping) else None
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            raise ReadError(f"local {pool_type} page has invalid data.items")
        rows.extend(item for item in items if isinstance(item, Mapping))
        page_qualities.append(_quality(body.get("quality")))
        pagination = body.get("pagination")
        if not isinstance(pagination, Mapping):
            raise ReadError(f"local {pool_type} page is missing pagination")
        has_more = bool(pagination.get("hasMore"))
        next_cursor = pagination.get("nextCursor")
        if not has_more:
            if next_cursor is not None:
                raise ReadError(f"local {pool_type} final page has an unexpected cursor")
            break
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
            raise ReadError(f"local {pool_type} pagination cursor is missing or repeated")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    else:
        raise ReadError(f"local {pool_type} pagination exceeded 1000 pages")
    return {"rows": rows, "quality": merge_quality(*page_qualities).to_dict()}


def _session_from_local_limits(
    *,
    base_url: str,
    as_of: date,
    previous_session: date | None,
    summary: Mapping[str, Any],
    revision: str,
    transport: JsonGetTransport,
    timeout: float,
) -> Session:
    root = f"api/v2/market-environment/{as_of.isoformat()}/limits"
    summary_data = summary.get("data") if isinstance(summary.get("data"), Mapping) else {}
    inferred_previous = _as_date(summary_data.get("previousSession") or summary_data.get("previousAsOf"))
    previous = previous_session or inferred_previous
    pools = {
        pool_type: _fetch_local_pool_rows(
            base_url, root, as_of, revision, pool_type, transport, timeout
        )
        for pool_type in POOL_TYPES
    }
    return session_from_dict(
        {
            "requestedDate": as_of.isoformat(),
            "actualDate": as_of.isoformat(),
            "previousSession": previous.isoformat() if previous else None,
            "source": "local-v2",
            "sourceKind": "local",
            "revision": revision,
            "quality": summary.get("quality"),
            "pools": pools,
        }
    )


def fetch_local_session(
    base_url: str,
    as_of: date,
    *,
    previous_session: date | None,
    transport: JsonGetTransport | None = None,
    timeout: float = 5.0,
) -> Session:
    transport = transport or UrllibJsonTransport()
    root = f"api/v2/market-environment/{as_of.isoformat()}/limits"
    summary = transport.get_json(
        _url(base_url, root), timeout=timeout, headers={"Accept": "application/json"}
    )
    revision = _validate_local_envelope(summary, as_of, None, "limits")
    return _session_from_local_limits(
        base_url=base_url,
        as_of=as_of,
        previous_session=previous_session,
        summary=summary,
        revision=revision,
        transport=transport,
        timeout=timeout,
    )


def fetch_local_current_review(
    base_url: str,
    as_of: date,
    *,
    previous_session: date,
    transport: JsonGetTransport | None = None,
    timeout: float = 5.0,
) -> tuple[Session, MarketEnvironmentInput]:
    transport = transport or UrllibJsonTransport()
    root = f"api/v2/market-environment/{as_of.isoformat()}"
    headers = {"Accept": "application/json"}
    overview = transport.get_json(_url(base_url, f"{root}/overview"), timeout=timeout, headers=headers)
    revision = _validate_local_envelope(overview, as_of, None, "overview")

    resources: dict[str, Mapping[str, Any]] = {}
    for resource in ("indices", "breadth", "limits"):
        body = transport.get_json(
            _url(base_url, f"{root}/{resource}", {"revision": revision}),
            timeout=timeout,
            headers=headers,
        )
        _validate_local_envelope(body, as_of, revision, resource)
        resources[resource] = body

    current = _session_from_local_limits(
        base_url=base_url,
        as_of=as_of,
        previous_session=previous_session,
        summary=resources["limits"],
        revision=revision,
        transport=transport,
        timeout=timeout,
    )
    overview_data = overview.get("data")
    indices_data = resources["indices"].get("data")
    breadth_data = resources["breadth"].get("data")
    if not isinstance(overview_data, Mapping):
        raise ReadError("local overview data must be an object")
    if not isinstance(indices_data, Mapping) or not isinstance(indices_data.get("items"), Sequence):
        raise ReadError("local indices data.items must be an array")
    if not isinstance(breadth_data, Mapping):
        raise ReadError("local breadth data must be an object")
    environment = market_environment_from_dict(
        {
            "asOf": as_of.isoformat(),
            "revision": revision,
            "quality": merge_quality(
                _quality(overview.get("quality")),
                _quality(resources["indices"].get("quality")),
                _quality(resources["breadth"].get("quality")),
            ).to_dict(),
            "summary": overview_data.get("summary"),
            "indices": indices_data.get("items"),
            "breadth": breadth_data,
        },
        current,
    )
    return current, environment


EASTMONEY_ENDPOINTS = {
    "limit_up": ("getTopicZTPool", "fbt:asc"),
    "failed_limit_up": ("getTopicZBPool", "fbt:asc"),
    "limit_down": ("getTopicDTPool", "fund:asc"),
}


def fetch_eastmoney_session(
    as_of: date,
    *,
    previous_session: date | None,
    transport: JsonGetTransport | None = None,
    timeout: float = 8.0,
    endpoint_root: str = "https://push2ex.eastmoney.com",
) -> Session:
    transport = transport or UrllibJsonTransport()
    pools: dict[str, dict[str, Any]] = {}
    all_qdates: list[date] = []
    request_only_pool = False
    for pool_type, (endpoint, sort) in EASTMONEY_ENDPOINTS.items():
        rows: list[Mapping[str, Any]] = []
        page_index = 0
        total: int | None = None
        pool_qdates: list[date] = []
        while True:
            params = {
                "dpt": "wz.ztzt",
                "Pageindex": page_index,
                "pagesize": 100,
                "sort": sort,
                "date": as_of.strftime("%Y%m%d"),
            }
            body = transport.get_json(
                _url(endpoint_root, endpoint, params),
                timeout=timeout,
                headers={"Accept": "application/json", "User-Agent": "a-stock-daily-tier-summary/1.0"},
            )
            data = body.get("data")
            if not isinstance(data, Mapping):
                raise ReadError(f"Eastmoney {pool_type} response is missing data")
            page_rows = data.get("pool") or []
            if not isinstance(page_rows, Sequence) or isinstance(page_rows, (str, bytes)):
                raise ReadError(f"Eastmoney {pool_type} pool must be an array")
            rows.extend(item for item in page_rows if isinstance(item, Mapping))
            qdate_raw = data.get("qdate") or data.get("date") or body.get("qdate") or body.get("date")
            if qdate_raw is not None:
                qdate = _as_date(qdate_raw)
                if qdate is None:
                    raise DateEvidenceError(f"Eastmoney {pool_type} returned invalid qdate")
                pool_qdates.append(qdate)
                all_qdates.append(qdate)
            total = _as_int(data.get("tc") or data.get("total")) if total is None else total
            if not page_rows or total is None or len(rows) >= total or len(page_rows) < 100:
                break
            page_index += 1
            if page_index >= 100:
                raise ReadError(f"Eastmoney {pool_type} pagination exceeded 100 pages")
        if not pool_qdates:
            request_only_pool = True
        if any(qdate != as_of for qdate in pool_qdates):
            actual = next(qdate for qdate in pool_qdates if qdate != as_of)
            raise DateEvidenceError(
                f"Eastmoney {pool_type} date contradiction: requested {as_of.isoformat()}, qdate {actual.isoformat()}"
            )
        pools[pool_type] = {
            "rows": rows,
            "total": total,
            "quality": {
                "status": "degraded" if not pool_qdates else "fallback",
                "warnings": ["request-date-only evidence"] if not pool_qdates else [],
            },
        }
    qdate = all_qdates[0] if all_qdates else None
    if any(item != qdate for item in all_qdates):
        raise DateEvidenceError("Eastmoney pools returned conflicting qdate values")
    return session_from_dict(
        {
            "requestedDate": as_of.isoformat(),
            "requestDate": as_of.isoformat(),
            "actualDate": qdate.isoformat() if qdate else None,
            "qdate": qdate.isoformat() if qdate else None,
            "previousSession": previous_session.isoformat() if previous_session else None,
            "source": "eastmoney-push2ex",
            "sourceKind": "eastmoney",
            "quality": {
                "status": "degraded" if request_only_pool else "fallback",
                "warnings": ["one or more pools have request-date-only evidence"] if request_only_pool else [],
            },
            "pools": pools,
        }
    )


def tier_for_streak(streak_days: int | None) -> str | None:
    if streak_days is None:
        return None
    if streak_days >= 4:
        return "high"
    if streak_days >= 2:
        return "middle"
    if streak_days == 1:
        return "low"
    return None


def _tier_members(pool: Pool) -> dict[str, set[SecurityIdentity]]:
    result = {tier: set() for tier in TIERS}
    for member in pool.members:
        tier = tier_for_streak(member.streak_days)
        if tier is not None:
            result[tier].add(member.identity)
    return result


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _tier_outcomes(previous: Session, current: Session) -> dict[str, dict[str, Any]]:
    previous_tiers = _tier_members(previous.pools["limit_up"])
    current_sets = {pool_type: current.pools[pool_type].identities for pool_type in POOL_TYPES}
    dependency_quality = merge_quality(
        previous.pools["limit_up"].quality,
        *(current.pools[pool_type].quality for pool_type in POOL_TYPES),
    )
    overlap = (
        current_sets["limit_up"] & current_sets["failed_limit_up"]
        | current_sets["limit_up"] & current_sets["limit_down"]
        | current_sets["failed_limit_up"] & current_sets["limit_down"]
    )
    if overlap:
        names = ", ".join(sorted(identity.security_id for identity in overlap))
        raise ConflictingRowsError(f"current pools overlap for identities: {names}")
    result: dict[str, dict[str, Any]] = {}
    for tier, members in previous_tiers.items():
        continued = len(members & current_sets["limit_up"])
        failed = len(members & current_sets["failed_limit_up"])
        down = len(members & current_sets["limit_down"])
        outside = len(members) - continued - failed - down
        sample_size = len(members)
        tier_quality = dependency_quality
        if not sample_size:
            tier_quality = merge_quality(
                dependency_quality,
                Quality("insufficient", (f"previous {tier} tier sample is empty",)),
            )
        result[tier] = {
            "sampleSize": sample_size,
            "continuedLimitUp": continued,
            "failedLimitUp": failed,
            "limitDown": down,
            "outsideObservedPools": outside,
            "continuedRatio": _ratio(continued, sample_size),
            "quality": tier_quality.to_dict(),
        }
    return result


def _flat_metrics(result: Mapping[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for tier in TIERS:
        outcome = result["tierOutcomes"][tier]
        for key, value in outcome.items():
            if key != "quality":
                metrics[f"tierOutcomes.{tier}.{key}"] = value
        metrics[f"currentTiers.{tier}.count"] = result["currentTiers"][tier]["count"]
    repair = result["failedSampleRepair"]
    for key in ("numerator", "denominator", "ratio"):
        metrics[f"failedSampleRepair.{key}"] = repair[key]
    for pool_type, value in result["poolChanges"].items():
        metrics[f"poolChanges.{pool_type}.delta"] = value["delta"]
        metrics[f"poolChanges.{pool_type}.current"] = value["current"]
        metrics[f"poolChanges.{pool_type}.previous"] = value["previous"]
    return metrics


OPERATORS = {
    ">=": lambda observed, expected: observed >= expected,
    ">": lambda observed, expected: observed > expected,
    "<=": lambda observed, expected: observed <= expected,
    "<": lambda observed, expected: observed < expected,
    "==": lambda observed, expected: observed == expected,
    "!=": lambda observed, expected: observed != expected,
}


def evaluate_previous_plan(plan: Any, metrics: Mapping[str, Any]) -> dict[str, Any]:
    if plan is None:
        return {
            "status": "unavailable",
            "layer": None,
            "originalText": None,
            "confirmation": [],
            "invalidation": [],
            "summary": "未找到可追溯的上一交易日验证条件",
        }
    if not isinstance(plan, Mapping):
        raise TierSummaryError("previousPlan must be an object or null")

    def evaluate_group(name: str, *, match_any: bool) -> tuple[list[dict[str, Any]], bool | None]:
        raw_conditions = plan.get(name) or []
        if not isinstance(raw_conditions, Sequence) or isinstance(raw_conditions, (str, bytes)):
            raise TierSummaryError(f"previousPlan.{name} must be an array")
        evaluated: list[dict[str, Any]] = []
        values: list[bool | None] = []
        for raw in raw_conditions:
            if not isinstance(raw, Mapping):
                raise TierSummaryError(f"previousPlan.{name} condition must be an object")
            metric = str(raw.get("metric") or "")
            operator = str(raw.get("operator") or "")
            if operator not in OPERATORS:
                raise TierSummaryError(f"unsupported previous-plan operator: {operator!r}")
            expected = raw.get("value")
            observed = metrics.get(metric)
            passed = None if observed is None or expected is None else bool(OPERATORS[operator](observed, expected))
            values.append(passed)
            evaluated.append(
                {
                    "text": str(raw.get("text") or f"{metric} {operator} {expected}"),
                    "metric": metric,
                    "operator": operator,
                    "expected": expected,
                    "observed": observed,
                    "passed": passed,
                }
            )
        if not evaluated:
            return evaluated, None
        if match_any and any(value is True for value in values):
            return evaluated, True
        if any(value is None for value in values):
            return evaluated, None
        return evaluated, any(bool(value) for value in values) if match_any else all(bool(value) for value in values)

    confirmation, confirmation_passed = evaluate_group("confirmation", match_any=False)
    invalidation, invalidation_passed = evaluate_group("invalidation", match_any=True)
    if confirmation_passed is True and invalidation_passed is True:
        status = "conflicting"
    elif confirmation_passed is True and invalidation_passed is not True:
        status = "confirmed"
    elif invalidation_passed is True and confirmation_passed is not True:
        status = "invalidated"
    else:
        status = "inconclusive"
    return {
        "status": status,
        "layer": plan.get("layer"),
        "originalText": plan.get("originalText"),
        "confirmation": confirmation,
        "invalidation": invalidation,
        "summary": {
            "confirmed": "上一交易日确认条件兑现",
            "invalidated": "上一交易日失效条件触发",
            "conflicting": "上一交易日确认与失效条件同时触发",
            "inconclusive": "上一交易日验证条件未形成明确结果",
        }[status],
    }


def _weak(outcome: Mapping[str, Any]) -> bool:
    sample = int(outcome["sampleSize"])
    return sample > 0 and (
        float(outcome["continuedRatio"]) < 0.5
        or int(outcome["failedLimitUp"]) + int(outcome["limitDown"]) > int(outcome["continuedLimitUp"])
    )


def _strong(outcome: Mapping[str, Any]) -> bool:
    return int(outcome["sampleSize"]) > 0 and float(outcome["continuedRatio"]) >= 0.6


def _structure_label(
    outcomes: Mapping[str, Mapping[str, Any]],
    current_tiers: Mapping[str, Mapping[str, Any]],
    previous_tiers: Mapping[str, set[SecurityIdentity]],
    pool_changes: Mapping[str, Mapping[str, int]],
    repair: Mapping[str, Any],
) -> tuple[str, list[str]]:
    weak = {tier for tier in TIERS if _weak(outcomes[tier])}
    strong = {tier for tier in TIERS if _strong(outcomes[tier])}
    evidence = [
        f"{TIER_CN[tier]} {outcomes[tier]['continuedLimitUp']}/{outcomes[tier]['sampleSize']} 继续涨停"
        for tier in TIERS
    ]
    low_expands = int(current_tiers["low"]["count"]) > len(previous_tiers["low"])
    pressure_contracts = (
        int(pool_changes["failed_limit_up"]["delta"]) + int(pool_changes["limit_down"]["delta"]) < 0
    )
    if {"high", "middle"}.issubset(weak) and low_expands:
        return "低位试错", [*evidence, "高、中位偏弱且今日低位涨停样本扩张"]
    if "high" in weak and len(weak) >= 2:
        return "扩散", [*evidence, f"偏弱层数 {len(weak)}，包含高位"]
    if "high" in strong and ({"middle", "low"} & weak):
        return "抱团", [*evidence, "高位继续率明显强于偏弱的中低位"]
    if repair["ratio"] is not None and repair["ratio"] >= 0.2 and pressure_contracts:
        return "修复", [
            *evidence,
            f"失败样本修复 {repair['numerator']}/{repair['denominator']}，炸板与跌停压力收缩",
        ]
    return "混合", [*evidence, "可观察信号未共同支持更强的单一结构描述"]


def _risk_layer(outcomes: Mapping[str, Mapping[str, Any]]) -> str | None:
    scores: dict[str, int] = {}
    for tier in TIERS:
        outcome = outcomes[tier]
        if int(outcome["sampleSize"]) > 0:
            scores[tier] = (
                int(outcome["limitDown"]) * 3
                + int(outcome["failedLimitUp"]) * 2
                + int(outcome["outsideObservedPools"])
                - int(outcome["continuedLimitUp"])
            )
    if not scores:
        return None
    return max(TIERS, key=lambda tier: (scores.get(tier, -10**9), -TIERS.index(tier)))


def _next_verification(
    risk_layer: str | None, current_tiers: Mapping[str, Mapping[str, Any]], current_date: date
) -> dict[str, Any]:
    counts = {tier: int(current_tiers[tier]["count"]) for tier in TIERS}
    layer = risk_layer if risk_layer and counts[risk_layer] > 0 else None
    if layer is None and any(counts.values()):
        layer = max(TIERS, key=lambda tier: (counts[tier], -TIERS.index(tier)))
    if layer is None:
        return {
            "layer": None,
            "sampleDate": current_date.isoformat(),
            "sampleSize": 0,
            "confirmation": None,
            "invalidation": None,
            "status": "insufficient",
        }
    sample = counts[layer]
    threshold = math.ceil(sample / 2)
    return {
        "layer": layer,
        "sampleDate": current_date.isoformat(),
        "sampleSize": sample,
        "confirmation": {
            "text": f"今日{TIER_CN[layer]}{sample}只中至少{threshold}只继续涨停，且跌停为0只",
            "conditions": [
                {"metric": f"tierOutcomes.{layer}.continuedLimitUp", "operator": ">=", "value": threshold},
                {"metric": f"tierOutcomes.{layer}.limitDown", "operator": "==", "value": 0},
            ],
        },
        "invalidation": {
            "text": f"今日{TIER_CN[layer]}{sample}只中继续涨停为0只，或跌停至少1只",
            "conditions": [
                {"metric": f"tierOutcomes.{layer}.continuedLimitUp", "operator": "==", "value": 0},
                {"metric": f"tierOutcomes.{layer}.limitDown", "operator": ">=", "value": 1},
            ],
            "join": "or",
        },
        "status": "needs-backtest",
    }


def _sync_pattern_from_indices(indices: Sequence[EnvironmentIndex]) -> tuple[str, str]:
    changes = {item.name: item.change_pct for item in indices if item.change_pct is not None}
    if not changes:
        code = "undetermined_divergence"
    else:
        advancing = sum(value >= 0.5 for value in changes.values())
        declining = sum(value <= -0.5 for value in changes.values())
        if advancing >= 4 and len(changes) >= 4:
            code = "synchronized_rally"
        elif declining >= 4 and len(changes) >= 4:
            code = "broad_weakness"
        elif all(changes.get(name, 0) >= 0.5 for name in ("上证指数", "沪深300")) and all(
            changes.get(name, 0) < 0 for name in ("创业板指", "中证500")
        ):
            code = "weight_shelter"
        elif all(changes.get(name, 0) >= 0.5 for name in ("创业板指", "中证500")) and all(
            changes.get(name, 0) < 0 for name in ("上证指数", "沪深300")
        ):
            code = "growth_lead"
        else:
            code = "undetermined_divergence"
    return code, SYNC_PATTERN_LABELS[code]


def _breadth_state(advance_ratio: float | None, median_return: float | None) -> str:
    if advance_ratio is None or median_return is None:
        return "insufficient"
    if advance_ratio >= 0.55 and median_return > 0:
        return "positive"
    if advance_ratio <= 0.45 and median_return < 0:
        return "negative"
    return "mixed"


def _trend_state(above: int, below: int, valid: int) -> str:
    if valid < 3:
        return "insufficient"
    if above >= 3:
        return "positive"
    if below >= 3:
        return "negative"
    return "mixed"


def _turnover_state(advance: int | None, decline: int | None, valid: int) -> str:
    if advance is None or decline is None or valid < 3:
        return "insufficient"
    if advance >= 3:
        return "positive"
    if decline >= 3:
        return "negative"
    return "mixed"


def _group_environment_indices(
    indices: Sequence[EnvironmentIndex],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    directions = {"rising": [], "falling": [], "flat": [], "insufficient": []}
    positions = {"above": [], "below": [], "insufficient": []}
    for item in indices:
        if item.change_pct is None:
            directions["insufficient"].append(item.name)
        elif item.change_pct > 0:
            directions["rising"].append(item.name)
        elif item.change_pct < 0:
            directions["falling"].append(item.name)
        else:
            directions["flat"].append(item.name)
        if item.close is None or item.ma20 is None:
            positions["insufficient"].append(item.name)
        elif item.close >= item.ma20:
            positions["above"].append(item.name)
        else:
            positions["below"].append(item.name)
    return directions, positions


def _relation_state(
    canonical: Any,
    breadth_state: str,
    directions: Mapping[str, Sequence[str]],
) -> tuple[str, str]:
    if isinstance(canonical, bool):
        return ("consistent" if canonical else "divergent"), "canonical"
    rising = len(directions["rising"])
    falling = len(directions["falling"])
    if breadth_state == "positive" and rising > falling:
        return "consistent", "derived"
    if breadth_state == "negative" and falling > rising:
        return "consistent", "derived"
    if breadth_state == "positive" and falling > rising:
        return "divergent", "derived"
    if breadth_state == "negative" and rising > falling:
        return "divergent", "derived"
    return "insufficient", "derived"


def _environment_verification(
    *,
    pattern_code: str,
    breadth_state: str,
    trend_state: str,
    turnover_state: str,
    relation: str,
    gaps: Sequence[str],
    indices: Sequence[EnvironmentIndex],
    dimension_statuses: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if gaps:
        return {
            "concept": "data-recovery",
            "status": "insufficient",
            "text": f"{gaps[0]}是否恢复为可用数据；恢复前不验证环境方向",
        }
    expected = None
    if pattern_code in {"synchronized_rally", "growth_lead"}:
        expected = "positive"
    elif pattern_code in {"broad_weakness", "weight_shelter"}:
        expected = "negative"
    elif relation == "consistent":
        if breadth_state in {"positive", "negative"}:
            expected = breadth_state

    states = {"breadth": breadth_state, "trend": trend_state, "turnover": turnover_state}
    canonical_statuses = dict(dimension_statuses or {})
    if not canonical_statuses and pattern_code == "undetermined_divergence":
        canonical_statuses = {
            concept: "insufficient" if state == "insufficient" else "neutral"
            for concept, state in states.items()
        }
    for concept in ("breadth", "trend", "turnover"):
        contradicting = canonical_statuses.get(concept) == "contradicting"
        if contradicting or (expected and states[concept] not in {expected, "mixed"}):
            if concept == "breadth":
                threshold = "上涨占比是否回到 ≥55% 且全 A 中位涨幅 >0" if expected == "positive" else "上涨占比是否回到 ≤45% 且全 A 中位涨幅 <0"
            elif concept == "trend":
                threshold = "五指数中是否至少3个位于MA20上方" if expected == "positive" else "五指数中是否至少3个位于MA20下方"
            else:
                threshold = "放量上涨指数是否达到至少3个" if expected == "positive" else "放量下跌指数是否达到至少3个"
            return {"concept": concept, "status": "needs-backtest", "text": f"{threshold}；若达到，反向证据得到修复"}

    if pattern_code == "growth_lead" and breadth_state == "positive":
        growth_ratios = [
            item.amount_ratio5
            for item in indices
            if item.name in {"创业板指", "中证500"} and item.amount_ratio5 is not None
        ]
        if len(growth_ratios) == 2 and median(growth_ratios) < 1.0:
            return {
                "concept": "growth-turnover",
                "status": "needs-backtest",
                "text": "创业板指与中证500的5日成交额比值中位数是否达到 ≥1.0；若达到，成长成交确认补齐",
            }

    for concept in ("breadth", "trend", "turnover"):
        if canonical_statuses.get(concept) == "neutral" or states[concept] == "mixed":
            preferred = expected or ("negative" if len([item for item in indices if item.change_pct is not None and item.change_pct < 0]) > len([item for item in indices if item.change_pct is not None and item.change_pct > 0]) else "positive")
            if concept == "breadth":
                if states[concept] == preferred:
                    text = (
                        "上涨占比是否继续 ≥55% 且全 A 中位涨幅 >0；若持续，则强势得到进一步确认"
                        if preferred == "positive"
                        else "上涨占比是否继续 ≤45% 且全 A 中位涨幅 <0；若持续，则弱势得到进一步确认"
                    )
                    return {"concept": concept, "status": "needs-backtest", "text": text}
                threshold = "上涨占比是否达到 ≥55% 且全 A 中位涨幅 >0" if preferred == "positive" else "上涨占比是否达到 ≤45% 且全 A 中位涨幅 <0"
            elif concept == "trend":
                threshold = "五指数中是否至少3个位于MA20上方" if preferred == "positive" else "五指数中是否至少3个位于MA20下方"
            else:
                threshold = "放量上涨指数是否达到至少3个" if preferred == "positive" else "放量下跌指数是否达到至少3个"
            return {"concept": concept, "status": "needs-backtest", "text": f"{threshold}；若达到，环境方向得到确认"}

    if breadth_state == "positive":
        text = "上涨占比是否继续 ≥55% 且全 A 中位涨幅 >0；若持续，则强势得到进一步确认"
    else:
        text = "上涨占比是否继续 ≤45% 且全 A 中位涨幅 <0；若持续，则弱势得到进一步确认"
    return {"concept": "breadth", "status": "needs-backtest", "text": text}


def analyze_market_environment(
    environment: MarketEnvironmentInput | None, current: Session
) -> dict[str, Any]:
    if environment is None:
        return {
            "date": current.requested_date.isoformat(),
            "revision": current.date_evidence.revision,
            "quality": {"status": "insufficient", "warnings": ["market environment input is missing"]},
            "directionGroups": {"rising": [], "falling": [], "flat": [], "insufficient": list(INDEX_NAMES)},
            "ma20Groups": {"above": [], "below": [], "insufficient": list(INDEX_NAMES)},
            "breadth": {
                "advanceRatio": None,
                "medianReturn": None,
                "widthLabel": None,
                "widthLabelReason": None,
                "state": "insufficient",
            },
            "turnover": {
                "medianAmountRatio5": None,
                "volumeBackedAdvanceCount": None,
                "volumeBackedDeclineCount": None,
                "validCount": 0,
                "state": "insufficient",
            },
            "canonical": {
                "patternCode": None,
                "patternLabel": None,
                "assessmentStatus": None,
                "conclusionCode": None,
                "conclusion": None,
                "source": "missing",
            },
            "breadthIndexRelation": {"state": "insufficient", "source": "missing"},
            "conclusion": {"category": "数据不足", "status": "insufficient"},
            "confidence": "insufficient",
            "gaps": ["市场环境输入"],
            "nextSessionVerification": {
                "concept": "data-recovery",
                "status": "insufficient",
                "text": "市场环境输入是否恢复为可用数据；恢复前不验证环境方向",
            },
        }

    directions, positions = _group_environment_indices(environment.indices)
    raw = _raw_environment_facts(environment.indices, environment.breadth)
    evidence = environment.market_evidence or {}
    assessment = environment.assessment or {}
    pattern_code = str(assessment.get("patternCode") or "")
    pattern_label = str(assessment.get("patternLabel") or "")
    pattern_source = "assessment"
    if not pattern_code:
        pattern_code, pattern_label = _sync_pattern_from_indices(environment.indices)
        pattern_source = "derived-indices"
    if not pattern_label:
        pattern_label = SYNC_PATTERN_LABELS.get(pattern_code, "数据不足")

    advance_ratio = _as_float(environment.breadth.get("advanceRatio"))
    median_return = _as_float(environment.breadth.get("medianReturn"))
    breadth_state = _breadth_state(advance_ratio, median_return)
    above = len(positions["above"])
    below = len(positions["below"])
    trend_state = _trend_state(above, below, above + below)
    median_ratio = _as_float(evidence.get("medianAmountRatio5"))
    if median_ratio is None:
        median_ratio = raw["medianAmountRatio5"]
    volume_advance = _as_int(evidence.get("volumeBackedAdvanceCount"))
    if volume_advance is None:
        volume_advance = raw["volumeBackedAdvanceCount"]
    volume_decline = _as_int(evidence.get("volumeBackedDeclineCount"))
    if volume_decline is None:
        volume_decline = raw["volumeBackedDeclineCount"]
    turnover_valid = sum(item.amount_ratio5 is not None for item in environment.indices)
    turnover_state = _turnover_state(volume_advance, volume_decline, turnover_valid)
    relation, relation_source = _relation_state(
        environment.breadth.get("indexConsistent"), breadth_state, directions
    )

    gaps: list[str] = []
    if directions["insufficient"]:
        gaps.append(f"指数涨跌幅（{','.join(directions['insufficient'])}）")
    if positions["insufficient"]:
        gaps.append(f"MA20位置（{','.join(positions['insufficient'])}）")
    if advance_ratio is None:
        gaps.append("上涨占比")
    if median_return is None:
        gaps.append("全A涨跌幅中位数")
    if environment.breadth.get("widthLabel") is None:
        gaps.append("宽度标签")
    if median_ratio is None:
        gaps.append("五指数5日成交额比值中位数")
    if volume_advance is None or volume_decline is None:
        gaps.append("放量上涨/下跌计数")

    changes = [item.change_pct for item in environment.indices if item.change_pct is not None]
    positive_gate = len(changes) >= 4 and sum(value >= 0.5 for value in changes) >= 4
    negative_gate = len(changes) >= 4 and sum(value <= -0.5 for value in changes) >= 4
    if len(changes) < 4 or breadth_state == "insufficient" or trend_state == "insufficient":
        category = "数据不足"
        category_status = "insufficient"
    elif positive_gate and breadth_state == "positive" and trend_state == "positive":
        category = "普遍偏强候选"
        category_status = "needs-backtest"
    elif relation == "divergent":
        category = "指数与个股分化"
        category_status = "needs-backtest"
    elif negative_gate and breadth_state == "negative" and trend_state == "negative":
        category = "普遍偏弱候选"
        category_status = "needs-backtest"
    elif pattern_code == "undetermined_divergence" and breadth_state == "negative" and trend_state == "negative":
        category = "弱势分化、保持观察"
        category_status = "needs-backtest"
    else:
        category = "未定型或轮动"
        category_status = "needs-backtest"

    confidence = str(assessment.get("confidence") or "low")
    if confidence not in {"high", "medium", "low", "insufficient"}:
        confidence = "low"
    required_gaps = [gap for gap in gaps if not gap.startswith(("宽度标签", "五指数5日成交额", "放量上涨"))]
    if required_gaps:
        confidence = "insufficient"
    verification = _environment_verification(
        pattern_code=pattern_code,
        breadth_state=breadth_state,
        trend_state=trend_state,
        turnover_state=turnover_state,
        relation=relation,
        gaps=gaps,
        indices=environment.indices,
        dimension_statuses={
            concept: str(value.get("status"))
            for concept, value in (
                assessment.get("dimensions")
                if isinstance(assessment.get("dimensions"), Mapping)
                else {}
            ).items()
            if isinstance(value, Mapping) and value.get("status")
        },
    )
    return {
        "date": environment.as_of.isoformat(),
        "revision": environment.revision,
        "quality": environment.quality.to_dict(),
        "indices": [item.to_dict() for item in environment.indices],
        "directionGroups": directions,
        "ma20Groups": positions,
        "breadth": {
            "advanceRatio": advance_ratio,
            "medianReturn": median_return,
            "widthLabel": environment.breadth.get("widthLabel"),
            "widthLabelReason": environment.breadth.get("widthLabelReason"),
            "state": breadth_state,
        },
        "turnover": {
            "medianAmountRatio5": median_ratio,
            "volumeBackedAdvanceCount": volume_advance,
            "volumeBackedDeclineCount": volume_decline,
            "validCount": turnover_valid,
            "state": turnover_state,
        },
        "canonical": {
            "patternCode": pattern_code,
            "patternLabel": pattern_label,
            "assessmentStatus": assessment.get("status"),
            "conclusionCode": assessment.get("conclusionCode"),
            "conclusion": assessment.get("conclusion"),
            "source": pattern_source,
        },
        "breadthIndexRelation": {"state": relation, "source": relation_source},
        "conclusion": {"category": category, "status": category_status},
        "confidence": confidence,
        "gaps": gaps,
        "nextSessionVerification": verification,
    }


def analyze_sessions(
    previous: Session,
    current: Session,
    *,
    previous_plan: Any = None,
    market_environment: MarketEnvironmentInput | None = None,
    request: ResolvedRequest | None = None,
) -> dict[str, Any]:
    if current.previous_session is not None and current.previous_session != previous.requested_date:
        raise DateEvidenceError(
            f"current previousSession {current.previous_session.isoformat()} does not match supplied previous session {previous.requested_date.isoformat()}"
        )
    if previous.requested_date >= current.requested_date:
        raise DateEvidenceError("previous session must precede current session")
    outcomes = _tier_outcomes(previous, current)
    previous_tiers = _tier_members(previous.pools["limit_up"])
    current_tier_sets = _tier_members(current.pools["limit_up"])
    current_tiers = {
        tier: {
            "count": len(current_tier_sets[tier]),
            "quality": current.pools["limit_up"].quality.to_dict(),
        }
        for tier in TIERS
    }
    pool_changes = {
        pool_type: {
            "previous": len(previous.pools[pool_type].members),
            "current": len(current.pools[pool_type].members),
            "delta": len(current.pools[pool_type].members) - len(previous.pools[pool_type].members),
        }
        for pool_type in POOL_TYPES
    }
    repair_denominator = len(previous.pools["failed_limit_up"].members)
    repair_numerator = len(
        previous.pools["failed_limit_up"].identities & current.pools["limit_up"].identities
    )
    repair = {
        "numerator": repair_numerator,
        "denominator": repair_denominator,
        "ratio": _ratio(repair_numerator, repair_denominator),
        "status": "ok" if repair_denominator else "insufficient",
        "warning": None if repair_denominator else "previous failed-limit-up sample is empty",
    }
    base: dict[str, Any] = {
        "tierOutcomes": outcomes,
        "currentTiers": current_tiers,
        "poolChanges": pool_changes,
        "failedSampleRepair": repair,
    }
    verification = evaluate_previous_plan(previous_plan, _flat_metrics(base))
    quality = merge_quality(previous.quality, current.quality)
    if QUALITY_ORDER[quality.status] >= QUALITY_ORDER["insufficient"]:
        label = "数据不足"
        label_status = "insufficient"
        label_evidence = ["必需的相邻交易日 pool 未达到可判断质量"]
    else:
        label, label_evidence = _structure_label(
            outcomes, current_tiers, previous_tiers, pool_changes, repair
        )
        label_status = "needs-backtest"
    risk_layer = _risk_layer(outcomes)
    next_verification = _next_verification(risk_layer, current_tiers, current.requested_date)
    environment_result = analyze_market_environment(market_environment, current)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "request": request.to_dict() if request else None,
        "dates": {
            "previousSession": previous.requested_date.isoformat(),
            "currentSession": current.requested_date.isoformat(),
        },
        "sources": {
            "previous": previous.source_evidence(),
            "current": current.source_evidence(),
        },
        "quality": quality.to_dict(),
        **base,
        "previousVerification": verification,
        "riskLayer": risk_layer,
        "structure": {
            "label": label,
            "status": label_status,
            "evidence": label_evidence,
        },
        "nextSessionVerification": next_verification,
        "marketEnvironment": environment_result,
    }
    return result


def analyze_fixture(payload: Mapping[str, Any]) -> dict[str, Any]:
    request_value = payload.get("request")
    request: ResolvedRequest | None = None
    if isinstance(payload.get("sessions"), Mapping):
        sessions_value = payload["sessions"]
        if not isinstance(request_value, Mapping):
            raise TierSummaryError("fixture with sessions requires request")
        relative = str(request_value.get("relative") or "")
        now_raw = request_value.get("now")
        try:
            now = datetime.fromisoformat(str(now_raw))
        except ValueError as exc:
            raise DateEvidenceError("request.now must be ISO-8601") from exc
        calendar_raw = request_value.get("tradingSessions") or []
        calendar = [_as_date(item) for item in calendar_raw]
        if any(item is None for item in calendar):
            raise DateEvidenceError("request.tradingSessions contains an invalid date")
        request = resolve_relative_session(
            relative, now=now, trading_sessions=[item for item in calendar if item is not None]
        )
        current_value = sessions_value.get(request.session_date.isoformat())
        if not isinstance(current_value, Mapping):
            raise DateEvidenceError("fixture lacks the resolved current session")
        current = session_from_dict(current_value)
        previous_date = current.previous_session
        if previous_date is None:
            prior = sorted(item for item in calendar if item is not None and item < current.requested_date)
            previous_date = prior[-1] if prior else None
        previous_value = sessions_value.get(previous_date.isoformat()) if previous_date else None
        if not isinstance(previous_value, Mapping):
            raise DateEvidenceError("fixture lacks the exact previous session")
        previous = session_from_dict(previous_value)
    else:
        previous_value = payload.get("previous")
        current_value = payload.get("current")
        if not isinstance(previous_value, Mapping) or not isinstance(current_value, Mapping):
            raise TierSummaryError("fixture requires previous and current session objects")
        previous = session_from_dict(previous_value)
        current = session_from_dict(current_value)
    environment_value = payload.get("marketEnvironment")
    if environment_value is not None and not isinstance(environment_value, Mapping):
        raise TierSummaryError("fixture marketEnvironment must be an object or null")
    environment = (
        market_environment_from_dict(environment_value, current)
        if isinstance(environment_value, Mapping)
        else None
    )
    return analyze_sessions(
        previous,
        current,
        previous_plan=payload.get("previousPlan"),
        market_environment=environment,
        request=request,
    )


def _format_ratio(value: float | None) -> str:
    return "数据不足" if value is None else f"{value * 100:.1f}%"


def _format_percent(value: Any, *, ratio: bool = False) -> str:
    number = _as_float(value)
    if number is None:
        return "数据不足"
    if ratio:
        number *= 100
    return f"{number:.2f}".rstrip("0").rstrip(".") + "%"


def _named_direction_line(groups: Mapping[str, Sequence[str]]) -> str:
    parts: list[str] = []
    for key, suffix in (
        ("rising", "上涨"),
        ("falling", "下跌"),
        ("flat", "平盘"),
        ("insufficient", "涨跌数据不足"),
    ):
        names = groups.get(key) or []
        if names:
            parts.append(f"{'、'.join(names)}{suffix}")
    return "；".join(parts) if parts else "五指数涨跌数据不足"


def _named_ma20_line(groups: Mapping[str, Sequence[str]]) -> str:
    parts: list[str] = []
    for key, label in (
        ("above", "MA20上方"),
        ("below", "MA20下方"),
        ("insufficient", "MA20位置数据不足"),
    ):
        names = groups.get(key) or []
        if names:
            parts.append(f"{label}：{'、'.join(names)}")
    return "；".join(parts) if parts else "MA20位置数据不足"


def render_summary(result: Mapping[str, Any]) -> str:
    verification = result["previousVerification"]
    verification_text = str(verification["summary"])
    observed: list[str] = []
    for group in ("confirmation", "invalidation"):
        for condition in verification.get(group, []):
            observed.append(f"{condition['text']}（观测值 {condition['observed']}）")
    if observed:
        verification_text = f"{verification_text}：{'；'.join(observed)}"
    tier_parts: list[str] = []
    for tier in TIERS:
        value = result["tierOutcomes"][tier]
        if value["sampleSize"] == 0:
            tier_parts.append(f"{TIER_CN[tier]}样本0只，数据不足")
        else:
            tier_parts.append(
                f"{TIER_CN[tier]}样本{value['sampleSize']}只，继续涨停{value['continuedLimitUp']}、"
                f"炸板{value['failedLimitUp']}、跌停{value['limitDown']}、脱离三池{value['outsideObservedPools']}"
            )
    repair = result["failedSampleRepair"]
    repair_text = (
        f"{repair['numerator']}/{repair['denominator']}={_format_ratio(repair['ratio'])}"
        if repair["denominator"]
        else "昨日炸板样本为0，修复率数据不足"
    )
    risk_layer = result.get("riskLayer")
    risk_text = TIER_CN.get(risk_layer, "数据不足")
    next_value = result["nextSessionVerification"]
    if next_value["layer"] is None:
        next_line = "下一交易日只验证待数据充分后确定。"
    else:
        next_line = (
            f"下一交易日只验证{TIER_CN[next_value['layer']]}层："
            f"确认条件{next_value['confirmation']['text']}，"
            f"失效条件{next_value['invalidation']['text']}。"
        )
    prefix = ""
    request = result.get("request")
    if isinstance(request, Mapping) and request.get("note"):
        prefix = f"日期说明：{request['note']}。\n"
    environment = result["marketEnvironment"]
    breadth = environment["breadth"]
    turnover = environment["turnover"]
    relation = environment["breadthIndexRelation"]["state"]
    relation_text = {
        "consistent": "与指数一致",
        "divergent": "与指数背离",
        "insufficient": "与指数关系数据不足",
    }.get(relation, "与指数关系数据不足")
    confidence_text = {
        "high": "高",
        "medium": "中",
        "low": "低",
        "insufficient": "数据不足",
    }.get(environment.get("confidence"), "数据不足")
    environment_verification = environment["nextSessionVerification"]["text"]
    median_ratio_text = (
        "数据不足"
        if turnover["medianAmountRatio5"] is None
        else f"{turnover['medianAmountRatio5']:.2f}"
    )
    volume_counts_text = (
        "数据不足/数据不足"
        if turnover["volumeBackedAdvanceCount"] is None
        or turnover["volumeBackedDeclineCount"] is None
        else f"{turnover['volumeBackedAdvanceCount']}/{turnover['volumeBackedDeclineCount']}"
    )
    pool_changes = result["poolChanges"]
    pool_change_text = (
        f"涨停{pool_changes['limit_up']['previous']}→{pool_changes['limit_up']['current']}只、"
        f"跌停{pool_changes['limit_down']['previous']}→{pool_changes['limit_down']['current']}只、"
        f"炸板{pool_changes['failed_limit_up']['previous']}→{pool_changes['failed_limit_up']['current']}只"
    )
    return (
        f"{prefix}{_named_direction_line(environment['directionGroups'])}\n"
        f"{_named_ma20_line(environment['ma20Groups'])}\n"
        f"上涨占比{_format_percent(breadth['advanceRatio'], ratio=True)}\n"
        f"全A涨跌幅中位数{_format_percent(breadth['medianReturn'])}\n"
        f"五指数5日成交额比值中位数{median_ratio_text}\n"
        f"放量上涨/下跌为{volume_counts_text}\n"
        f"今日宽度标签：{breadth['widthLabel'] or '数据不足'}。\n"
        f"核心证据：{relation_text}。\n"
        f"昨日验证结果：{verification_text}。\n"
        f"今日分层结论：{tier_parts[0]}，{tier_parts[1]}，{tier_parts[2]}，失败样本修复{repair_text}。\n"
        f"风险主要位于{risk_text}层，当前属于{result['structure']['label']}（{pool_change_text}）。\n"
        f"{next_line}\n"
        f"因此今天属于{environment['conclusion']['category']}。\n"
        f"置信度{confidence_text}。\n"
        f"下一交易日只验证：{environment_verification}。"
    )


def _load_json(path: str) -> Mapping[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TierSummaryError("input JSON must be an object")
    return payload


def _error_result(error: Exception) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "quality": {"status": "insufficient", "warnings": [str(error)]},
        "error": {"type": error.__class__.__name__, "message": str(error)},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="fixture or caller-provided JSON")
    source.add_argument("--base-url", help="local provider-free v2 API base URL")
    parser.add_argument("--date", help="current completed session, YYYY-MM-DD")
    parser.add_argument("--previous-date", help="exact previous session, YYYY-MM-DD")
    parser.add_argument("--allow-eastmoney", action="store_true", help="explicit read-only fallback")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--render", action="store_true", help="render the fixed Chinese review card")
    args = parser.parse_args(argv)
    try:
        if args.input:
            result = analyze_fixture(_load_json(args.input))
        else:
            current_date = _as_date(args.date)
            previous_date = _as_date(args.previous_date)
            if current_date is None or previous_date is None:
                raise DateEvidenceError("--base-url requires --date and --previous-date")
            try:
                previous = fetch_local_session(
                    args.base_url,
                    previous_date,
                    previous_session=None,
                    timeout=args.timeout,
                )
                current, environment = fetch_local_current_review(
                    args.base_url,
                    current_date,
                    previous_session=previous_date,
                    timeout=args.timeout,
                )
            except (OSError, ReadError, DateEvidenceError) as local_error:
                if not args.allow_eastmoney:
                    raise local_error
                previous = fetch_eastmoney_session(
                    previous_date, previous_session=None, timeout=min(max(args.timeout, 1.0), 15.0)
                )
                current = fetch_eastmoney_session(
                    current_date,
                    previous_session=previous_date,
                    timeout=min(max(args.timeout, 1.0), 15.0),
                )
                environment = None
            result = analyze_sessions(previous, current, market_environment=environment)
        if args.render:
            print(render_summary(result))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
        return 0
    except (TierSummaryError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps(_error_result(exc), ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
