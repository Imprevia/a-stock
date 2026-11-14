"""QTS-04 STEP 2 theme layer: data acquisition, theme construction, JSON."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

SKILL_DIR = Path(__file__).resolve().parent.parent
_CORE = SKILL_DIR.parent / "qts04-core" / "scripts"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from qts04.cache import BarCache  # noqa: E402
from qts04.client import (  # noqa: E402
    FuyaoClient,
    FuyaoDegraded,
    FuyaoError,
    FuyaoInsufficient,
)
from qts04.contract import attach_identity, require_schema_version  # noqa: E402
from qts04.model import Bar, normalize_bars  # noqa: E402
from qts04.predicate import (  # noqa: E402
    CONFIRMATION_CLOSE_MULTIPLIER,
    CONFIRMATION_HORIZON_DAYS,
    CONFIRMATION_TURNOVER_MULTIPLIER,
    INVALIDATION_CLOSE_MULTIPLIER,
    INVALIDATION_HORIZON_DAYS,
    INVALIDATION_TURNOVER_MULTIPLIER,
)

from theming import (  # noqa: E402
    CORE_LIFT,
    CORE_OBSERVED_FLOOR,
    CORE_TOTAL_SCORE,
    DIFFUSE_LIFT,
    DIFFUSE_TOTAL_SCORE,
    METRIC_WEIGHTS,
    SCHEMA_VERSION,
    SHARED_TOKEN_MIN,
    STATUS_DEGRADED,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    STEP,
    STOP_TOKENS,
    TIER_CORE,
    build_shared_tokens,
    build_theme,
    build_token_concepts,
    confirmed_policy,
    detect_attribute_tokens,
    jaccard,
    no_core_reasons,
    rank_key,
    is_theme_concept,
    split_reason,
    tokenize_limit_ups,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
SETTLEMENT = clock_time(15, 10)
BENCHMARK = "000001.SH"
DEFAULT_MARKET_STOCK_COUNT = 5400
DEFAULT_MAX_CANDIDATES = 24
DEFAULT_MAX_SCORED = 12
DEFAULT_MAX_THEMES = 5
MEMBER_SAMPLE_LIMIT = 60
CONCEPT_HISTORY_DAYS = 365 * 5
STOCK_HISTORY_DAYS = 45

DEFAULT_CACHE_DIR = SKILL_DIR / ".cache" / "qts04"
POINT_IN_TIME_DIR = DEFAULT_CACHE_DIR / "point-in-time"

REPORT_ID_FIELDS = ("schemaVersion", "step", "asOf", "config", "input", "themes")
DISCLAIMER = (
    "以上为盘后题材观察与剧本，不是买点，不构成投资建议；"
    "分级与 lift 均为 needs-backtest 的规则输出。"
)


def now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


def resolve_as_of(raw: str | None, *, now: datetime | None = None) -> date:
    current = now or now_shanghai()
    if not raw:
        target = current.date()
    else:
        try:
            target = date.fromisoformat(raw)
        except ValueError as error:
            raise FuyaoInsufficient(f"--as-of 不是合法日期：{raw}") from error
    if target > current.date():
        raise FuyaoInsufficient(f"目标日期 {target} 晚于今天 {current.date()}，无法取数")
    if target == current.date() and current.time() < SETTLEMENT:
        raise FuyaoInsufficient(f"目标日期 {target} 尚未收盘结算（15:10 之前）")
    return target


def build_config(
    *,
    market_stock_count: int,
    max_candidates: int,
    max_themes: int,
    member_sample_limit: int,
) -> dict[str, Any]:
    return {
        "benchmark": BENCHMARK,
        "weights": {name: weight for name, weight in METRIC_WEIGHTS},
        "lift": {
            "formula": "observed / (memberCount * marketLimitUpRate)",
            "marketLimitUpRate": "limitUpCount / marketStockCount",
            "coreThreshold": CORE_LIFT,
            "diffuseThreshold": DIFFUSE_LIFT,
        },
        "sharedTokenMin": SHARED_TOKEN_MIN,
        "tiers": {
            "core": {
                "totalScore": CORE_TOTAL_SCORE,
                "lift": CORE_LIFT,
                "sharedTokenMin": SHARED_TOKEN_MIN,
                "ladderDepth": 2,
                "observedFloor": CORE_OBSERVED_FLOOR,
            },
            "diffuse": {
                "totalScore": DIFFUSE_TOTAL_SCORE,
                "lift": DIFFUSE_LIFT,
                "observedFloor": 2,
            },
        },
        "windows": {
            "relativeStrength": [5, 20],
            "turnover": 20,
            "conceptHistoryDays": CONCEPT_HISTORY_DAYS,
            "stockHistoryDays": STOCK_HISTORY_DAYS,
        },
        "confirmation": {
            "horizonDays": CONFIRMATION_HORIZON_DAYS,
            "closeMultiplier": CONFIRMATION_CLOSE_MULTIPLIER,
            "closeChange": round(CONFIRMATION_CLOSE_MULTIPLIER - 1.0, 6),
            "turnoverMultiplier": CONFIRMATION_TURNOVER_MULTIPLIER,
        },
        "invalidation": {
            "horizonDays": INVALIDATION_HORIZON_DAYS,
            "closeMultiplier": INVALIDATION_CLOSE_MULTIPLIER,
            "closeChange": round(INVALIDATION_CLOSE_MULTIPLIER - 1.0, 6),
            "turnoverMultiplier": INVALIDATION_TURNOVER_MULTIPLIER,
        },
        "marketStockCount": int(market_stock_count),
        "candidateLimit": int(max_candidates),
        "maxThemes": int(max_themes),
        "memberSampleLimit": int(member_sample_limit),
        "attributeConceptThreshold": 4,
        "stopTokens": sorted(STOP_TOKENS),
    }


# ----------------------------------------------------------------------
# small JSON cache for non-bar payloads
# ----------------------------------------------------------------------
class JsonCache:
    def __init__(self, root: Path, *, enabled: bool = True) -> None:
        self.root = Path(root)
        self.enabled = enabled

    def _path(self, key: str) -> Path:
        return self.root / key

    def load(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        path = self._path(key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, key: str, payload: Any) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _chunks(values: Sequence[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def _fixture_bars(rows: Any) -> list[Bar]:
    if not isinstance(rows, list):
        return []
    if any(isinstance(row, Mapping) and "date_ms" in row for row in rows):
        return normalize_bars(row for row in rows if isinstance(row, Mapping))
    result: list[Bar] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw = str(row.get("date") or "")
        try:
            trading_date = date.fromisoformat(raw)
            close = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        result.append(
            Bar(
                trading_date=trading_date,
                close=close,
                turnover=_float(row.get("turnover")),
                open=_float(row.get("open")),
                high=_float(row.get("high")),
                low=_float(row.get("low")),
            )
        )
    result.sort(key=lambda bar: bar.trading_date)
    return result


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_limit_up(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "thscode": str(row.get("thscode") or "").strip().upper(),
        "name": str(row.get("name") or "").strip(),
        "reason": str(row.get("reason") or row.get("limit_up_reason") or "").strip(),
        "continueDay": int(row.get("continueDay") or row.get("continue_day_cnt") or 1),
        "continueText": str(row.get("continueText") or row.get("continue_day_text") or "").strip(),
        "sealMoney": _float(row.get("sealMoney") or row.get("seal_money")),
        "openTimes": _float(row.get("openTimes") or row.get("open_times")),
        "limitUpTime": str(row.get("limitUpTime") or row.get("limit_up_time") or "").strip(),
        "isSt": bool(row.get("isSt") or row.get("is_st")),
        "isNew": bool(row.get("isNew") or row.get("is_new")),
        "priceChangePct": _float(row.get("priceChangePct") or row.get("price_change_ratio_pct")),
    }


@dataclass
class ConceptData:
    thscode: str
    name: str
    members: list[str] = field(default_factory=list)
    bars: list[Bar] = field(default_factory=list)
    snapshot: dict[str, Any] | None = None
    member_changes: dict[str, float] = field(default_factory=dict)


@dataclass
class Inputs:
    concepts: list[ConceptData]
    limit_ups: list[dict[str, Any]]
    benchmark: list[Bar]
    statistics: dict[str, Any]
    anomalies: list[dict[str, Any]]
    market_stock_count: int
    trading_days: list[date] | None
    warnings: list[str] = field(default_factory=list)
    candidate_basis: str = "fixture"
    catalog: list[dict[str, str]] = field(default_factory=list)
    snapshot_expected: int = 0
    snapshot_missing: int = 0


def _load_fixture(path: Path, as_of: date) -> Inputs:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise FuyaoInsufficient("fixture 顶层必须是对象")
    declared = payload.get("asOf")
    if declared and str(declared) != as_of.isoformat():
        raise FuyaoInsufficient(f"fixture asOf={declared} 与 --as-of={as_of} 不一致")
    concepts: list[ConceptData] = []
    for row in payload.get("concepts") or []:
        if not isinstance(row, Mapping):
            continue
        code = str(row.get("thscode") or "").strip().upper()
        name = str(row.get("name") or "").strip()
        if not code:
            continue
        members = [
            str(member).strip().upper()
            for member in row.get("members") or []
            if str(member).strip()
        ]
        changes = {
            str(code).strip().upper(): float(value)
            for code, value in (row.get("memberChanges") or {}).items()
            if _float(value) is not None
        }
        concepts.append(
            ConceptData(
                thscode=code,
                name=name,
                members=members,
                bars=[bar for bar in _fixture_bars(row.get("bars")) if bar.trading_date <= as_of],
                snapshot=row.get("snapshot") if isinstance(row.get("snapshot"), Mapping) else None,
                member_changes=changes,
            )
        )
    benchmark = [
        bar
        for bar in _fixture_bars(payload.get("benchmark"))
        if bar.trading_date <= as_of
    ]
    trading_days = None
    if isinstance(payload.get("tradingDays"), list):
        trading_days = []
        for raw in payload["tradingDays"]:
            try:
                trading_days.append(date.fromisoformat(str(raw)))
            except ValueError:
                continue
    return Inputs(
        concepts=concepts,
        limit_ups=[
            _normalize_limit_up(row)
            for row in payload.get("limitUps") or []
            if isinstance(row, Mapping)
        ],
        benchmark=benchmark,
        statistics=dict(payload.get("statistics") or {}),
        anomalies=[
            dict(row)
            for row in payload.get("anomalies") or []
            if isinstance(row, Mapping)
        ],
        market_stock_count=int(payload.get("marketStockCount") or DEFAULT_MARKET_STOCK_COUNT),
        trading_days=trading_days,
        candidate_basis="fixture",
        catalog=[{"thscode": concept.thscode, "name": concept.name} for concept in concepts],
    )


# ----------------------------------------------------------------------
# live acquisition
# ----------------------------------------------------------------------
def _read_cached(cache: JsonCache, key: str) -> Any | None:
    return cache.load(key)


def _load_catalog(client: FuyaoClient, cache: JsonCache, warnings: list[str]) -> list[dict[str, str]]:
    cached = _read_cached(cache, "catalog.json")
    if isinstance(cached, Mapping) and isinstance(cached.get("items"), list):
        return [
            {"thscode": str(row.get("thscode")), "name": str(row.get("name"))}
            for row in cached["items"]
            if isinstance(row, Mapping) and row.get("thscode")
        ]
    items = client.list_concepts()
    cache.save("catalog.json", {"items": items})
    return items


def _load_snapshot(
    client: FuyaoClient,
    cache: JsonCache,
    concepts: Sequence[Mapping[str, str]],
    as_of: date,
    *,
    today: date,
    warnings: list[str],
) -> tuple[list[dict[str, Any]] | None, int]:
    if as_of != today:
        warnings.append("历史日期没有概念快照（接口只提供最新快照），候选生成只用涨停原因词")
        return None, 0
    key = f"snapshots/{as_of.isoformat()}.json"
    cached = _read_cached(cache, key)
    if isinstance(cached, Mapping) and isinstance(cached.get("items"), list):
        rows = [dict(row) for row in cached["items"] if isinstance(row, Mapping)]
    else:
        try:
            rows = client.index_snapshot([row["thscode"] for row in concepts])
        except FuyaoDegraded as error:
            warnings.append(f"概念快照不可用：{error}")
            return [], len(concepts)
        cache.save(key, {"asOf": as_of.isoformat(), "items": rows})
    expected = {str(row["thscode"]).upper() for row in concepts}
    observed = {str(row.get("thscode") or "").upper() for row in rows}
    missing = len(expected - observed)
    if missing:
        warnings.append(f"概念快照缺行：{missing}/{len(expected)}")
    return rows, missing


def _load_limit_ups(
    client: FuyaoClient, cache: JsonCache, as_of: date
) -> list[dict[str, Any]]:
    key = f"limit-up/{as_of.isoformat()}.json"
    cached = _read_cached(cache, key)
    if isinstance(cached, Mapping) and isinstance(cached.get("items"), list):
        return [_normalize_limit_up(row) for row in cached["items"] if isinstance(row, Mapping)]
    rows = client.limit_up_pool(as_of)
    cache.save(key, {"asOf": as_of.isoformat(), "items": rows})
    return rows


def _load_statistics(
    client: FuyaoClient, cache: JsonCache, as_of: date, warnings: list[str]
) -> dict[str, Any]:
    key = f"limit-up-stats/{as_of.isoformat()}.json"
    cached = _read_cached(cache, key)
    if isinstance(cached, Mapping):
        return dict(cached)
    try:
        stats = client.limit_up_statistics(as_of)
    except FuyaoDegraded as error:
        warnings.append(f"涨停统计不可用：{error}")
        return {}
    cache.save(key, stats)
    return stats


def _normalize_anomaly(row: Mapping[str, Any]) -> dict[str, Any]:
    """Anomaly rows carry a bare 6-digit code; attach the exchange suffix."""

    payload = dict(row)
    code = str(payload.get("thscode") or "").strip().upper()
    if len(code) == 6 and code.isdigit():
        url = str(payload.get("url") or "")
        if "marketId=17" in url:
            code += ".SH"
        elif "marketId=33" in url:
            code += ".SZ"
    payload["thscode"] = code
    return payload


def _load_anomalies(
    client: FuyaoClient, cache: JsonCache, as_of: date, warnings: list[str]
) -> list[dict[str, Any]]:
    key = f"anomalies/{as_of.isoformat()}.json"
    cached = _read_cached(cache, key)
    if isinstance(cached, Mapping) and isinstance(cached.get("items"), list):
        return [
            _normalize_anomaly(row)
            for row in cached["items"]
            if isinstance(row, Mapping)
        ]
    try:
        rows = client.anomaly_analysis(as_of)
    except FuyaoDegraded as error:
        warnings.append(f"异动解读不可用：{error}")
        return []
    rows = [_normalize_anomaly(row) for row in rows]
    cache.save(key, {"asOf": as_of.isoformat(), "items": rows})
    return rows


def _select_candidates(
    catalog: Sequence[Mapping[str, str]],
    snapshot: Sequence[Mapping[str, Any]] | None,
    limit_ups: Sequence[Mapping[str, Any]],
    max_candidates: int,
) -> tuple[list[dict[str, str]], str]:
    by_code = {str(row.get("thscode")): dict(row) for row in catalog}
    tokens = {
        token
        for row in limit_ups
        for token in split_reason(row.get("reason"))
        if len(token) >= 2
    }
    token_counts = Counter(
        token
        for row in limit_ups
        for token in split_reason(row.get("reason"))
        if len(token) >= 2
    )
    hit_scores: dict[str, float] = {}
    for row in catalog:
        name = str(row.get("name") or "")
        code = str(row.get("thscode") or "")
        if not name or not code or not is_theme_concept(name):
            continue
        score = 0.0
        for token in tokens:
            if token == name:
                score += 100.0 + token_counts[token]
            elif token in name:
                score += 10.0 + token_counts[token]
            elif name in token:
                score += 5.0 + token_counts[token]
        if score > 0:
            hit_scores[code] = score
    hit_codes = sorted(hit_scores, key=lambda code: (-hit_scores[code], code))

    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for code in hit_codes:
        if code in by_code and code not in seen:
            selected.append(by_code[code])
            seen.add(code)

    name_limit = max(1, (max_candidates * 2) // 3)
    selected = selected[:name_limit]
    seen = {row["thscode"] for row in selected}
    if snapshot:
        ranked = sorted(
            snapshot,
            key=lambda row: (
                -abs(_float(row.get("priceChangePct")) or 0.0),
                -(_float(row.get("turnover")) or 0.0),
                str(row.get("thscode") or ""),
            ),
        )
        for row in ranked:
            code = str(row.get("thscode") or "")
            if code in by_code and code not in seen:
                selected.append(by_code[code])
                seen.add(code)

    if not selected:
        selected = [dict(row) for row in catalog]
    basis = "reason-token+snapshot" if snapshot else "reason-token"
    return selected[:max_candidates], basis


def _load_constituents(
    client: FuyaoClient, cache: JsonCache, code: str, warnings: list[str]
) -> list[str]:
    key = f"constituents/{code}.json"
    cached = _read_cached(cache, key)
    if isinstance(cached, Mapping) and isinstance(cached.get("items"), list):
        return [
            str(row.get("thscode")).strip().upper()
            for row in cached["items"]
            if isinstance(row, Mapping) and row.get("thscode")
        ]
    try:
        rows = client.constituents(code)
    except FuyaoDegraded as error:
        warnings.append(f"{code} 成分股不可用：{error}")
        return []
    cache.save(key, {"thscode": code, "items": rows})
    return [row["thscode"] for row in rows]


def _load_bars(
    client: FuyaoClient,
    cache: BarCache,
    *,
    kind: str,
    code: str,
    as_of: date,
    start: date,
    warnings: list[str],
) -> list[Bar]:
    bars = [bar for bar in cache.load(kind, code) if bar.trading_date <= as_of]
    if bars and bars[-1].trading_date == as_of:
        return bars
    try:
        if kind == "benchmark":
            fetched = client.index_history_batch([code], start, as_of).get(code, [])
        elif kind == "concept":
            fetched = client.index_history_batch([code], start, as_of).get(code, [])
        else:
            fetched = client.stock_history_batch([code], start, as_of).get(code, [])
    except FuyaoDegraded as error:
        warnings.append(f"{code} 日线不可用：{error}")
        return bars
    if fetched:
        cache.save(kind, code, fetched)
    return [bar for bar in fetched if bar.trading_date <= as_of] or bars


def _member_changes(
    client: FuyaoClient,
    cache: BarCache,
    members: Sequence[str],
    as_of: date,
    sample_limit: int,
    warnings: list[str],
) -> dict[str, float]:
    sample = sorted({str(code).strip().upper() for code in members if str(code).strip()})[:sample_limit]
    missing = [code for code in sample if not any(
        bar.trading_date == as_of for bar in cache.load("stock", code)
    )]
    for batch in _chunks(missing, 10):
        try:
            fetched = client.stock_history_batch(
                batch,
                as_of - timedelta(days=STOCK_HISTORY_DAYS),
                as_of,
            )
        except FuyaoDegraded as error:
            warnings.append(f"成员日线不可用（{len(batch)} 只）：{error}")
            continue
        for code, bars in fetched.items():
            if bars:
                cache.save("stock", code, bars)
    changes: dict[str, float] = {}
    for code in sample:
        bars = [bar for bar in cache.load("stock", code) if bar.trading_date <= as_of]
        if len(bars) >= 2 and bars[-1].trading_date == as_of:
            previous = bars[-2].close
            if previous:
                changes[code] = (bars[-1].close - previous) / previous
    return changes


def _load_live(
    client: FuyaoClient,
    as_of: date,
    *,
    cache_dir: Path,
    max_candidates: int,
    member_sample_limit: int,
    use_cache: bool,
    today: date | None = None,
) -> Inputs:
    warnings: list[str] = []
    json_cache = JsonCache(cache_dir, enabled=use_cache)
    bar_cache = BarCache(cache_dir / "bars")
    today = today or now_shanghai().date()

    catalog = _load_catalog(client, json_cache, warnings)
    snapshot, snapshot_missing = _load_snapshot(
        client, json_cache, catalog, as_of, today=today, warnings=warnings
    )
    limit_ups = _load_limit_ups(client, json_cache, as_of)
    statistics = _load_statistics(client, json_cache, as_of, warnings)
    anomalies = _load_anomalies(client, json_cache, as_of, warnings)
    reported = int(statistics.get("limitUpStockCount") or 0) if statistics else 0
    if reported and reported != len(limit_ups):
        warnings.append(
            f"涨停池 {len(limit_ups)} 行与涨停统计 {reported} 只不一致（可能含 ST/新股口径差）"
        )
    history_start = max(
        as_of - timedelta(days=CONCEPT_HISTORY_DAYS),
        today - timedelta(days=CONCEPT_HISTORY_DAYS) + timedelta(days=1),
    )
    benchmark = _load_bars(
        client,
        bar_cache,
        kind="benchmark",
        code=BENCHMARK,
        as_of=as_of,
        start=history_start,
        warnings=warnings,
    )

    candidates, basis = _select_candidates(catalog, snapshot, limit_ups, max_candidates)
    concepts: list[ConceptData] = []
    for row in candidates:
        code = str(row["thscode"])
        members = _load_constituents(client, json_cache, code, warnings)
        concepts.append(ConceptData(thscode=code, name=str(row.get("name") or ""), members=members))

    limit_up_codes = {str(row.get("thscode")) for row in limit_ups}
    for concept in concepts:
        if not is_theme_concept(concept.name):
            continue
        if not (set(concept.members) & limit_up_codes):
            continue
        concept.bars = _load_bars(
            client,
            bar_cache,
            kind="concept",
            code=concept.thscode,
            as_of=as_of,
            start=history_start,
            warnings=warnings,
        )
        concept.member_changes = _member_changes(
            client,
            bar_cache,
            concept.members,
            as_of,
            member_sample_limit,
            warnings,
        )

    return Inputs(
        concepts=concepts,
        limit_ups=limit_ups,
        benchmark=benchmark,
        statistics=statistics,
        anomalies=anomalies,
        market_stock_count=DEFAULT_MARKET_STOCK_COUNT,
        trading_days=None,
        warnings=warnings,
        candidate_basis=basis,
        catalog=[{"thscode": row["thscode"], "name": row["name"]} for row in catalog],
        snapshot_expected=len(catalog),
        snapshot_missing=snapshot_missing,
    )


def _load_step1(path: Path | None, client: FuyaoClient | None, warnings: list[str]) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("STEP 1 JSON 顶层必须是对象")
    require_schema_version(payload, supported=("1.0",))
    if not payload.get("reportId"):
        raise ValueError("STEP 1 JSON 缺少 reportId")
    return dict(payload)


def _direction_members(
    direction: Mapping[str, Any],
    client: FuyaoClient | None,
    warnings: list[str],
) -> list[str]:
    raw = direction.get("members")
    if isinstance(raw, list) and raw:
        result: list[str] = []
        for item in raw:
            if isinstance(item, Mapping):
                code = item.get("thscode")
            else:
                code = item
            if code:
                result.append(str(code).strip().upper())
        return result
    if client is None:
        return []
    code = str(direction.get("thscode") or "").strip().upper()
    if not code:
        return []
    try:
        return [row["thscode"] for row in client.constituents(code)]
    except FuyaoDegraded as error:
        warnings.append(f"STEP 1 方向 {code} 成分股不可用：{error}")
        return []


def _attach_directions(
    themes: list[dict[str, Any]],
    step1: Mapping[str, Any] | None,
    client: FuyaoClient | None,
    warnings: list[str],
) -> None:
    if not step1:
        return
    directions = [row for row in step1.get("directions") or [] if isinstance(row, Mapping)]
    if not directions:
        return
    members = {
        str(row.get("thscode")): _direction_members(row, client, warnings)
        for row in directions
    }
    for theme in themes:
        theme_members = theme.get("members", {}).get("codes") or []
        best: dict[str, Any] | None = None
        for direction in directions:
            code = str(direction.get("thscode") or "")
            overlap = jaccard(theme_members, members.get(code, []))
            if overlap is None:
                continue
            candidate = {
                "thscode": code,
                "name": direction.get("name"),
                "overlapJaccard": round(overlap, 6),
                "reportId": step1.get("reportId"),
            }
            if best is None or candidate["overlapJaccard"] > best["overlapJaccard"]:
                best = candidate
        theme["direction"] = best


def _unmapped_tokens(
    catalog: Sequence[Mapping[str, str]],
    limit_ups: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    counts: Counter[str] = Counter()
    for row in limit_ups:
        for token in split_reason(row.get("reason")):
            if token:
                counts[token] += 1
    mapped: set[str] = set()
    for token in counts:
        if any(token in str(row.get("name") or "") or str(row.get("name") or "") in token for row in catalog):
            mapped.add(token)
    rows = [
        {"token": token, "occurrences": count}
        for token, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if token not in mapped and token not in STOP_TOKENS
    ]
    return rows[:20], len(mapped)


def _quality(
    *,
    as_of: date,
    inputs: Inputs,
    themes: Sequence[Mapping[str, Any]],
    catalog_count: int,
    unmapped: Sequence[Mapping[str, Any]],
    mapped_count: int,
    catalog_as_of: date,
) -> dict[str, Any]:
    per_theme = [
        {
            "themeId": theme.get("themeId"),
            "name": theme.get("name"),
            **dict(theme.get("members", {}).get("membershipGap") or {}),
        }
        for theme in themes
    ]
    return {
        "pointInTime": False,
        "catalogAsOf": catalog_as_of.isoformat(),
        "catalogBasis": "current-snapshot",
        "membershipAsOf": as_of.isoformat(),
        "membershipBasis": "current-snapshot-only",
        "backtestGrade": "D",
        "gradeReasons": [
            "概念成分股只有当前快照，无法还原历史成员",
            "涨停池接口窗口约 1 年",
            "异动解读是 AI 汇总文本，只能支持 partial",
        ],
        "dataWindows": {
            "conceptBars": f"{CONCEPT_HISTORY_DAYS} days (rebuildable cache)",
            "limitUpPool": "~1 year",
            "anomalyAnalysis": ">=2 years",
            "membership": "current snapshot only",
        },
        "conceptCatalogCount": catalog_count,
        "limitUpCrossCheck": {
            "poolRows": len(inputs.limit_ups),
            "statisticsCount": inputs.statistics.get("limitUpStockCount"),
            "consistent": inputs.statistics.get("limitUpStockCount") == len(inputs.limit_ups),
        },
        "candidateConcepts": len(inputs.concepts),
        "conceptsWithLimitUps": sum(1 for theme in themes if int(theme.get("observed") or 0) > 0),
        "limitUpCount": len(inputs.limit_ups),
        "mappedTokens": mapped_count,
        "unmappedTokens": len(unmapped),
        "membershipGap": per_theme,
        "warnings": list(inputs.warnings),
    }


def _status(themes: Sequence[Mapping[str, Any]], inputs: Inputs, catalog_count: int) -> str:
    if catalog_count <= 0 or not inputs.limit_ups or not inputs.benchmark:
        return STATUS_INSUFFICIENT
    if inputs.snapshot_expected and inputs.snapshot_missing > max(
        5, int(inputs.snapshot_expected * 0.05)
    ):
        return STATUS_INSUFFICIENT
    if not themes:
        return STATUS_OK
    if any(theme.get("status") == STATUS_INSUFFICIENT for theme in themes):
        if all(theme.get("status") == STATUS_INSUFFICIENT for theme in themes):
            return STATUS_INSUFFICIENT
        return STATUS_DEGRADED
    if inputs.warnings:
        return STATUS_DEGRADED
    return STATUS_OK


def run_pipeline(
    *,
    as_of: date,
    fixture: Path | None = None,
    step1: Path | None = None,
    cache_dir: Path | None = None,
    client: FuyaoClient | None = None,
    now: datetime | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_themes: int = DEFAULT_MAX_THEMES,
    member_sample_limit: int = MEMBER_SAMPLE_LIMIT,
    market_stock_count: int = DEFAULT_MARKET_STOCK_COUNT,
    use_cache: bool = True,
    calendar: Sequence[str] | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    calls_before = 0
    if fixture is not None:
        inputs = _load_fixture(fixture, as_of)
        effective_client = None
        catalog = [{"thscode": concept.thscode, "name": concept.name} for concept in inputs.concepts]
        if inputs.trading_days is not None and as_of not in inputs.trading_days:
            raise FuyaoInsufficient(f"{as_of} 不是 fixture 声明的交易日")
    else:
        effective_client = client or FuyaoClient()
        calls_before = len(effective_client.calls)
        effective_client.check_prerequisites()
        calendar_rows = list(calendar) if calendar is not None else effective_client.market_calendar()
        normalized = {
            date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}") if len(raw) == 8 and "-" not in raw else date.fromisoformat(raw)
            for raw in calendar_rows
        }
        if normalized and as_of not in normalized:
            raise FuyaoInsufficient(f"{as_of} 不是交易日")
        inputs = _load_live(
            effective_client,
            as_of,
            cache_dir=cache_dir or DEFAULT_CACHE_DIR,
            max_candidates=max_candidates,
            member_sample_limit=member_sample_limit,
            use_cache=use_cache,
            today=(now or now_shanghai()).date(),
        )
        catalog = inputs.catalog

    universe = int(inputs.market_stock_count or market_stock_count)
    if universe <= 0:
        universe = market_stock_count

    step1_payload = _load_step1(step1, effective_client, warnings)
    limit_up_tokens = tokenize_limit_ups(inputs.limit_ups)
    candidate_concepts = [concept for concept in inputs.concepts if concept.members]
    token_concepts = build_token_concepts(
        [{"thscode": concept.thscode, "members": concept.members} for concept in candidate_concepts],
        limit_up_tokens,
    )
    attribute_tokens = detect_attribute_tokens(token_concepts)

    built: list[dict[str, Any]] = []
    for concept in candidate_concepts:
        if not concept.members or not is_theme_concept(concept.name):
            continue
        if not any(str(row.get("thscode")) in set(concept.members) for row in inputs.limit_ups):
            continue
        theme = build_theme(
            as_of=as_of,
            concept={
                "thscode": concept.thscode,
                "name": concept.name,
                "members": concept.members,
                "bars": concept.bars,
            },
            limit_ups=inputs.limit_ups,
            limit_up_tokens=limit_up_tokens,
            benchmark_bars=inputs.benchmark,
            member_changes=concept.member_changes,
            anomalies=inputs.anomalies,
            limit_up_count=len(inputs.limit_ups),
            universe=universe,
            attribute_tokens=attribute_tokens,
        )
        built.append(theme)

    built.sort(key=rank_key)
    themes = built[:max_themes]
    for theme in themes:
        theme["attributeTokens"] = [
            token for token in attribute_tokens if token in str(theme.get("name") or "")
        ]
    _attach_directions(themes, step1_payload, effective_client, warnings)

    unmapped, mapped_count = _unmapped_tokens(catalog, inputs.limit_ups)
    quality = _quality(
        as_of=as_of,
        inputs=inputs,
        themes=themes,
        catalog_count=len(catalog),
        unmapped=unmapped,
        mapped_count=mapped_count,
        catalog_as_of=(now or now_shanghai()).date() if fixture is None else as_of,
    )
    quality["warnings"] = list(warnings) + list(quality.get("warnings") or [])
    quality["candidateBasis"] = inputs.candidate_basis
    quality["attributeTokenCount"] = len(attribute_tokens)
    if effective_client is not None:
        quality["providerCalls"] = len(effective_client.calls) - calls_before
        quality["credentialSource"] = effective_client.credential_source

    result: dict[str, Any] = {
        "asOf": as_of.isoformat(),
        "step": STEP,
        "ruleVersion": "QTS-04-02",
        "status": _status(themes, inputs, len(catalog)),
        "source": "hithink-finance" if fixture is None else "fixture",
        "generatedAt": (now or now_shanghai()).isoformat(),
        "input": {
            "conceptCatalogCount": len(catalog),
            "limitUpCount": len(inputs.limit_ups),
            "anomalyRows": len(inputs.anomalies),
            "marketStockCount": universe,
            "candidateBasis": inputs.candidate_basis,
            "statistics": inputs.statistics,
            "step1ReportId": step1_payload.get("reportId") if step1_payload else None,
            "step1": (
                {
                    "reportId": step1_payload.get("reportId"),
                    "asOf": step1_payload.get("asOf"),
                    "directions": [
                        {"thscode": row.get("thscode"), "name": row.get("name")}
                        for row in step1_payload.get("directions") or []
                        if isinstance(row, Mapping)
                    ],
                }
                if step1_payload
                else None
            ),
        },
        "config": build_config(
            market_stock_count=universe,
            max_candidates=max_candidates,
            max_themes=max_themes,
            member_sample_limit=member_sample_limit,
        ),
        "quality": quality,
        "catalystPolicy": confirmed_policy(),
        "noCoreTheme": not any(theme.get("tier") == TIER_CORE for theme in themes),
        "noCoreReasons": no_core_reasons(
            themes,
            limit_up_count=len(inputs.limit_ups),
            observed_concepts=len(built),
        ),
        "themes": themes,
        "unmappedTokens": unmapped,
        "disclaimer": DISCLAIMER,
        "calibration": "needs-backtest",
    }
    attach_identity(
        result,
        schema_version=SCHEMA_VERSION,
        fields=REPORT_ID_FIELDS,
        step=STEP,
    )
    if use_cache:
        _write_point_in_time(as_of, themes, cache_dir or DEFAULT_CACHE_DIR)
    return result


def _write_point_in_time(
    as_of: date, themes: Sequence[Mapping[str, Any]], cache_dir: Path
) -> Path:
    path = Path(cache_dir) / "point-in-time" / f"{as_of.isoformat()}.json"
    payload = {
        "asOf": as_of.isoformat(),
        "step": STEP,
        "themes": [
            {
                "themeId": theme.get("themeId"),
                "name": theme.get("name"),
                "tier": theme.get("tier"),
                "lift": theme.get("lift"),
                "members": sorted(theme.get("members", {}).get("codes") or []),
                "tokens": [
                    item.get("token")
                    for item in theme.get("members", {}).get("sharedTokens") or []
                ],
            }
            for theme in sorted(themes, key=lambda item: str(item.get("themeId") or ""))
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QTS-04 STEP 2 题材层（概念成员 ∩ 涨停池）")
    parser.add_argument("--as-of", dest="as_of", required=True, help="目标交易日 YYYY-MM-DD")
    parser.add_argument("--fixture", type=Path, default=None, help="离线 fixture JSON")
    parser.add_argument("--step1", type=Path, default=None, help="STEP 1 的 JSON（可选）")
    parser.add_argument("--cache-dir", dest="cache_dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None, help="JSON 结果写入路径")
    parser.add_argument("--report", type=Path, default=None, help="事实骨架 Markdown 写入路径")
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--max-themes", type=int, default=DEFAULT_MAX_THEMES)
    parser.add_argument("--member-sample-limit", type=int, default=MEMBER_SAMPLE_LIMIT)
    parser.add_argument("--market-stock-count", type=int, default=DEFAULT_MARKET_STOCK_COUNT)
    parser.add_argument("--refresh", action="store_true", help="忽略本地缓存，重新取数")
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "both"),
        default="json",
        help="stdout 输出格式",
    )
    args = parser.parse_args(argv)

    try:
        target = resolve_as_of(args.as_of)
        result = run_pipeline(
            as_of=target,
            fixture=args.fixture,
            step1=args.step1,
            cache_dir=args.cache_dir,
            max_candidates=args.max_candidates,
            max_themes=args.max_themes,
            member_sample_limit=args.member_sample_limit,
            market_stock_count=args.market_stock_count,
            use_cache=not args.refresh,
        )
    except (FuyaoError, ValueError) as error:
        status = getattr(error, "status", STATUS_INSUFFICIENT)
        result = {
            "asOf": args.as_of,
            "step": STEP,
            "status": status,
            "quality": {"status": status, "warnings": [str(error)]},
            "catalystPolicy": confirmed_policy(),
            "noCoreTheme": True,
            "themes": [],
            "unmappedTokens": [],
            "disclaimer": DISCLAIMER,
            "calibration": "needs-backtest",
        }
        attach_identity(
            result,
            schema_version=SCHEMA_VERSION,
            fields=REPORT_ID_FIELDS,
            step=STEP,
        )

    from theme_report import default_report_path, render_markdown

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    markdown = render_markdown(result)
    written: dict[str, Any] = {"status": result.get("status"), "reportId": result.get("reportId")}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        written["output"] = str(args.output)
    report_path = args.report or (default_report_path(args.output) if args.output else None)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(markdown if markdown.endswith("\n") else markdown + "\n", encoding="utf-8")
        written["report"] = str(report_path)

    if args.format == "json":
        print(json.dumps(written, ensure_ascii=False, sort_keys=True) if args.output else text)
    elif args.format == "markdown":
        print(markdown)
    else:
        print(text)
        print()
        print(markdown)
    return 0 if result.get("status") in {STATUS_OK, STATUS_DEGRADED} else 1


if __name__ == "__main__":
    raise SystemExit(main())
