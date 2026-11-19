"""Deterministic QTS-04 STEP 2 theme-layer scoring.

The unit of analysis is a theme, not a concept: a concept qualifies only when
its *current members* intersect the limit-up pool.  Every number here is a
pure function of its inputs so a fixture run and a live run follow the same
path.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "1.0"
STEP = "STEP 2"
RULE_VERSION = "QTS-04-02"

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_INSUFFICIENT = "insufficient"

TIER_CORE = "core"
TIER_DIFFUSE = "diffuse"
TIER_EVENT = "event"
TIER_PSEUDO = "pseudo"
TIER_ORDER = (TIER_CORE, TIER_DIFFUSE, TIER_EVENT, TIER_PSEUDO)

CATALYST_CONFIRMED = "confirmed"
CATALYST_PARTIAL = "partial"
CATALYST_SPECULATIVE = "speculative"
CATALYST_UNKNOWN = "unknown"

# (metric name, weight) in render order.
METRIC_WEIGHTS = (
    ("relative_strength_5", 0.20),
    ("relative_strength_20", 0.10),
    ("turnover_ratio", 0.15),
    ("member_breadth", 0.15),
    ("limit_up_ladder", 0.20),
    ("shared_token_coverage", 0.20),
)

CORE_TOTAL_SCORE = 50.0
CORE_LIFT = 3.0
CORE_LADDER_DEPTH = 2
CORE_OBSERVED_FLOOR = 4
DIFFUSE_TOTAL_SCORE = 35.0
DIFFUSE_LIFT = 1.5
DIFFUSE_OBSERVED_FLOOR = 2
SHARED_TOKEN_MIN = 2

CONFIDENCE_HIGH_COVERAGE = 0.85
CONFIDENCE_MEDIUM_COVERAGE = 0.65
CONFIDENCE_LOW_COVERAGE = 0.50

# Tokens that describe an event or an accounting fact, not a theme.  Kept
# short on purpose: the cross-concept detector is the second line of defence.
STOP_TOKENS = frozenset(
    {
        "股份回购", "回购", "增持", "减持", "员工持股", "股权激励", "股权转让",
        "控制权变更", "举牌", "并购重组", "资产重组", "重整", "预重整", "重组",
        "三季报", "三季报增长", "中报", "中报增长", "年报", "年报增长", "业绩增长",
        "业绩预增", "业绩扭亏", "扭亏", "预盈", "高送转", "分红", "派息",
        "解禁", "限售", "定增", "融资", "可转债", "配股",
        "中标", "订单", "合同", "战略合作", "签约", "框架协议",
        "公告", "消息", "利好", "政策", "规划", "意见", "方案", "试点",
        "涨停", "跌停", "连板", "首板", "二板", "三板", "一字板", "封板", "炸板",
        "ST", "摘帽", "新股", "次新股", "低价股", "小盘股", "微盘股", "超跌", "反弹",
        "国企改革", "央企改革", "地方国企改革",
        "高股息", "破净", "低市净率", "市值管理", "回购增持",
    }
)

NON_THEME_CONCEPTS = frozenset(
    {
        "摘帽", "新股与次新股", "注册制次新股", "科创次新股", "次新股",
        "破净", "高股息", "低价股", "小盘股", "微盘股", "ST板块",
    }
)


def is_theme_concept(name: str) -> bool:
    return name.strip() not in NON_THEME_CONCEPTS


GENERIC_SUFFIXES = ("概念", "板块", "方向", "题材", "产业链")
_SPLIT_RE = re.compile(r"[+＋/、,，;；|\s]+")
_BRACKET_RE = re.compile(r"[（(][^）)]*[）)]")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-]*")


def normalize_reason(text: Any) -> str:
    value = str(text or "").replace("＋", "+")
    value = _BRACKET_RE.sub("", value)
    return value.strip()


def split_reason(text: Any) -> list[str]:
    """Split one limit-up reason into ordered, de-duplicated tokens."""

    tokens: list[str] = []
    seen: set[str] = set()
    for raw in _SPLIT_RE.split(normalize_reason(text)):
        token = raw.strip().strip("。.：:;；")
        for suffix in GENERIC_SUFFIXES:
            if token.endswith(suffix) and len(token) > len(suffix) + 1:
                token = token[: -len(suffix)]
        token = token.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def tokenize_limit_ups(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Map each limit-up code to its ordered reason tokens."""

    result: dict[str, list[str]] = {}
    for row in rows:
        code = str(row.get("thscode") or "").strip().upper()
        if not code:
            continue
        result[code] = split_reason(row.get("reason"))
    return result


def is_stop_token(token: str) -> bool:
    return token in STOP_TOKENS or token.upper() in STOP_TOKENS


def detect_attribute_tokens(
    token_concepts: Mapping[str, Iterable[str]],
    *,
    concept_threshold: int = 4,
) -> set[str]:
    """Tokens shared by many unrelated concepts are attributes, not catalysts."""

    return {
        token
        for token, concepts in token_concepts.items()
        if len(set(concepts)) >= concept_threshold
    }


def build_shared_tokens(
    observed_rows: Sequence[Mapping[str, Any]],
    *,
    attribute_tokens: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Shared tokens counted *inside* one concept's limit-up members.

    A token held by a single stock never qualifies: ``count >= 2`` is the
    membership-co-occurrence rule.
    """

    blocked = set(attribute_tokens)
    holders: dict[str, set[str]] = {}
    for row in observed_rows:
        code = str(row.get("thscode") or "").strip().upper()
        if not code:
            continue
        for token in split_reason(row.get("reason")):
            if is_stop_token(token) or token in blocked:
                continue
            holders.setdefault(token, set()).add(code)
    shared = [
        {"token": token, "holders": sorted(codes), "count": len(codes)}
        for token, codes in holders.items()
        if len(codes) >= SHARED_TOKEN_MIN
    ]
    shared.sort(key=lambda item: (-item["count"], item["token"]))
    return shared


def build_token_concepts(
    concepts: Sequence[Mapping[str, Any]],
    limit_up_tokens: Mapping[str, Sequence[str]],
) -> dict[str, set[str]]:
    """For each token, the concepts whose limit-up members carry it."""

    result: dict[str, set[str]] = {}
    for concept in concepts:
        code = str(concept.get("thscode") or "").strip().upper()
        members = {str(member).strip().upper() for member in concept.get("members") or []}
        for member in members & set(limit_up_tokens):
            for token in limit_up_tokens.get(member, ()):  # type: ignore[arg-type]
                result.setdefault(token, set()).add(code)
    return result


def compute_market_limit_up_rate(limit_up_count: int, universe: int) -> float | None:
    if limit_up_count <= 0 or universe <= 0:
        return None
    return limit_up_count / universe


def compute_lift(
    observed: int,
    member_count: int,
    limit_up_count: int,
    universe: int,
) -> float | None:
    """``observed / (memberCount × marketLimitUpRate)``; ``None`` if undefined."""

    rate = compute_market_limit_up_rate(limit_up_count, universe)
    if rate is None or member_count <= 0:
        return None
    expected = member_count * rate
    if expected <= 0:
        return None
    return observed / expected


def tier_score(value: float | None, cuts: Sequence[float]) -> float | None:
    """Five-band score: below c0=0, c0–c1=25, c1–c2=50, c2–c3=75, ≥c3=100."""

    if value is None or not math.isfinite(float(value)):
        return None
    current = float(value)
    if current < cuts[0]:
        return 0.0
    if current < cuts[1]:
        return 25.0
    if current < cuts[2]:
        return 50.0
    if current < cuts[3]:
        return 75.0
    return 100.0


def period_return(bars: Sequence[Any], window: int) -> float | None:
    if window < 1 or len(bars) < window + 1:
        return None
    start = float(bars[-(window + 1)].close)
    end = float(bars[-1].close)
    if start == 0:
        return None
    return (end - start) / start


def mean_turnover(bars: Sequence[Any], window: int = 20) -> float | None:
    values = [float(bar.turnover) for bar in bars[-window:] if bar.turnover is not None]
    if not values:
        return None
    return sum(values) / len(values)


def median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


@dataclass
class Metric:
    name: str
    value: float | None
    score: float | None
    weight: float
    status: str
    missing_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": None if self.value is None else round(float(self.value), 6),
            "score": None if self.score is None else round(float(self.score), 2),
            "weight": self.weight,
            "status": self.status,
            "missingReason": self.missing_reason,
            "calibration": "needs-backtest",
        }


def _metric(name: str, value: float | None, cuts: Sequence[float], reason: str) -> Metric:
    weight = dict(METRIC_WEIGHTS)[name]
    score = tier_score(value, cuts)
    return Metric(
        name=name,
        value=value,
        score=score,
        weight=weight,
        status="ok" if score is not None else "insufficient",
        missing_reason=None if score is not None else reason,
    )


def build_metrics(
    *,
    concept_bars: Sequence[Any],
    benchmark_bars: Sequence[Any],
    turnover_mean: float | None,
    member_changes: Mapping[str, float] | None,
    ladder_depth: int | None,
    shared_holder_count: int | None,
    observed: int,
) -> list[Metric]:
    """All six metrics; a missing input stays ``None`` and is never zero-filled."""

    rs5 = None
    rs20 = None
    if concept_bars and benchmark_bars:
        concept_5 = period_return(concept_bars, 5)
        benchmark_5 = period_return(benchmark_bars, 5)
        if concept_5 is not None and benchmark_5 is not None:
            rs5 = concept_5 - benchmark_5
        concept_20 = period_return(concept_bars, 20)
        benchmark_20 = period_return(benchmark_bars, 20)
        if concept_20 is not None and benchmark_20 is not None:
            rs20 = concept_20 - benchmark_20

    last_turnover = concept_bars[-1].turnover if concept_bars else None
    turnover_ratio = None
    if last_turnover is not None and turnover_mean not in (None, 0):
        turnover_ratio = float(last_turnover) / float(turnover_mean)

    breadth = None
    if member_changes:
        valid = [float(value) for value in member_changes.values() if value is not None]
        if valid:
            breadth = sum(1 for value in valid if value > 0) / len(valid)

    coverage = None
    if shared_holder_count is not None and observed > 0:
        coverage = shared_holder_count / observed

    return [
        _metric("relative_strength_5", rs5, (0.0, 0.02, 0.05, 0.10), "概念或基准 5 日收益不足"),
        _metric("relative_strength_20", rs20, (0.0, 0.05, 0.10, 0.20), "概念或基准 20 日收益不足"),
        _metric("turnover_ratio", turnover_ratio, (0.8, 1.0, 1.2, 1.5), "缺少概念成交额或 20 日均额"),
        _metric("member_breadth", breadth, (0.30, 0.50, 0.60, 0.80), "缺少成员涨跌样本"),
        _metric(
            "limit_up_ladder",
            None if ladder_depth is None else float(ladder_depth),
            (1.0, 2.0, 3.0, 4.0),
            "缺少涨停梯队深度",
        ),
        _metric(
            "shared_token_coverage",
            coverage,
            (0.0, 0.20, 0.30, 0.50),
            "没有共享 token",
        ),
    ]


def total_score(metrics: Sequence[Metric]) -> tuple[float | None, float]:
    """Weighted average over available metrics plus the observed coverage."""

    available = [metric for metric in metrics if metric.score is not None]
    total_weight = sum(metric.weight for metric in metrics)
    if not available or total_weight <= 0:
        return None, 0.0
    used = sum(metric.weight for metric in available)
    coverage = used / total_weight
    if coverage < CONFIDENCE_LOW_COVERAGE:
        return None, coverage
    score = sum(float(metric.score) * metric.weight for metric in available) / used
    return score, coverage


def confidence_from_coverage(coverage: float) -> str:
    if coverage >= CONFIDENCE_HIGH_COVERAGE:
        return "high"
    if coverage >= CONFIDENCE_MEDIUM_COVERAGE:
        return "medium"
    if coverage >= CONFIDENCE_LOW_COVERAGE:
        return "low"
    return STATUS_INSUFFICIENT


def classify_tier(
    *,
    score: float | None,
    lift: float | None,
    shared_count: int,
    ladder_depth: int | None,
    observed: int,
) -> tuple[str, list[str]]:
    """Core / diffuse / event / pseudo, with every failed gate recorded."""

    reasons: list[str] = []
    if score is None:
        reasons.append("分数不足：可用指标覆盖率低于 50%")
        return TIER_EVENT, reasons
    if lift is None:
        reasons.append("lift 不足：全市场涨停率或成员数缺失")
        return TIER_EVENT, reasons
    if lift < DIFFUSE_LIFT:
        reasons.append(f"lift 不足：{lift:.2f} < {DIFFUSE_LIFT}")
        return TIER_PSEUDO, reasons
    if shared_count <= 0:
        reasons.append("共享 token 不足：交集内没有 ≥2 只成员共享的 token")
        return TIER_EVENT, reasons
    if score < DIFFUSE_TOTAL_SCORE:
        reasons.append(f"分数不足：{score:.1f} < {DIFFUSE_TOTAL_SCORE}")
        return TIER_EVENT, reasons

    core_ok = True
    if score < CORE_TOTAL_SCORE:
        core_ok = False
        reasons.append(f"分数不足：{score:.1f} < {CORE_TOTAL_SCORE}")
    if lift < CORE_LIFT:
        core_ok = False
        reasons.append(f"lift 不足：{lift:.2f} < {CORE_LIFT}")
    if shared_count < SHARED_TOKEN_MIN:
        core_ok = False
        reasons.append("共享 token 不足")
    ladder_ok = (ladder_depth or 0) >= CORE_LADDER_DEPTH
    breadth_ok = observed >= CORE_OBSERVED_FLOOR
    if not ladder_ok and not breadth_ok:
        core_ok = False
        reasons.append(
            f"梯队不足：最高连板 {ladder_depth or 0} < {CORE_LADDER_DEPTH} 且涨停成员 {observed} < {CORE_OBSERVED_FLOOR}"
        )
    if core_ok:
        return TIER_CORE, reasons

    if score >= DIFFUSE_TOTAL_SCORE and lift >= DIFFUSE_LIFT and observed >= DIFFUSE_OBSERVED_FLOOR:
        return TIER_DIFFUSE, reasons
    return TIER_EVENT, reasons


def catalyst_matches(token: str, anomaly: Mapping[str, Any]) -> bool:
    haystack = " ".join(
        [
            str(anomaly.get("content") or ""),
            " ".join(str(word) for word in anomaly.get("keyWords") or []),
        ]
    )
    if not haystack:
        return False
    if token.isascii():
        return token.lower() in haystack.lower()
    return token in haystack


def build_catalyst(
    *,
    shared_tokens: Sequence[Mapping[str, Any]],
    anomalies: Sequence[Mapping[str, Any]],
    member_codes: Iterable[str],
    as_of: date,
) -> dict[str, Any]:
    """Four-level label; ``confirmed`` is deliberately unreachable."""

    if not shared_tokens:
        return {
            "label": CATALYST_UNKNOWN,
            "primaryToken": None,
            "sources": [],
            "reason": "交集内没有共享 token，无法给出催化",
            "confirmedAvailable": False,
        }
    primary = shared_tokens[0]
    token = str(primary.get("token") or "")
    members = {str(code).strip().upper().split(".", 1)[0] for code in member_codes}
    hits = [
        anomaly
        for anomaly in anomalies
        if str(anomaly.get("thscode") or "").strip().upper().split(".", 1)[0] in members
        and catalyst_matches(token, anomaly)
    ]
    sources: list[dict[str, Any]] = [
        {
            "type": "limitUpReason",
            "provider": "hithink-finance",
            "asOf": as_of.isoformat(),
            "ref": "special limit-up-pool",
            "token": token,
            "holderCount": primary.get("count"),
        }
    ]
    for hit in hits:
        sources.append(
            {
                "type": "anomalyAnalysis",
                "provider": "hithink-finance",
                "asOf": as_of.isoformat(),
                "ref": "news anomaly-analysis",
                "thscode": hit.get("thscode"),
                "tagName": hit.get("tagName"),
            }
        )
    if len({str(hit.get("thscode") or "") for hit in hits}) >= 1 and primary.get("count", 0) >= SHARED_TOKEN_MIN:
        label = CATALYST_PARTIAL
        reason = f"共享 token「{token}」有涨停原因与异动解读两类来源，但仅为 AI 汇总文本，未达到交叉证实"
    else:
        label = CATALYST_SPECULATIVE
        reason = f"共享 token「{token}」只有涨停原因单一来源"
    return {
        "label": label,
        "primaryToken": token,
        "sources": sources,
        "reason": reason,
        "confirmedAvailable": False,
    }


def confirmed_policy() -> dict[str, Any]:
    return {
        "confirmedAvailable": False,
        "confirmedLabel": CATALYST_CONFIRMED,
        "reason": "公开接口只提供涨停原因与 AI 汇总异动解读，主源不可枚举，无法达到 confirmed",
        "reachableLabels": [
            CATALYST_PARTIAL,
            CATALYST_SPECULATIVE,
            CATALYST_UNKNOWN,
        ],
    }


def no_core_reasons(
    themes: Sequence[Mapping[str, Any]],
    *,
    limit_up_count: int,
    observed_concepts: int,
) -> list[str]:
    if any(theme.get("tier") == TIER_CORE for theme in themes):
        return []
    if not themes:
        if limit_up_count <= 0:
            return ["当日涨停池为空，题材层不产出"]
        return ["当日没有概念成员命中涨停池"]
    reasons: list[str] = []
    for theme in themes:
        for reason in theme.get("tierReasons") or []:
            if reason not in reasons:
                reasons.append(str(reason))
    if observed_concepts and not reasons:
        reasons.append("没有题材同时满足核心题材的分数、lift、共享 token 与梯队闸门")
    return reasons


def jaccard(left: Iterable[str], right: Iterable[str]) -> float | None:
    a = {str(item).strip().upper() for item in left if str(item).strip()}
    b = {str(item).strip().upper() for item in right if str(item).strip()}
    if not a or not b:
        return None
    return len(a & b) / len(a | b)


def theme_id(as_of: date, concept_code: str, shared_tokens: Sequence[Mapping[str, Any]]) -> str:
    tokens = ",".join(sorted(str(item.get("token") or "") for item in shared_tokens))
    raw = f"{as_of.isoformat()}|{concept_code}|{tokens}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def membership_gap(
    member_count: int,
    *,
    sampled: int,
    active: int,
) -> dict[str, Any]:
    """Estimate how many listed members were not active on the session."""

    if member_count <= 0 or sampled <= 0:
        return {
            "value": None,
            "memberCount": member_count,
            "sampled": sampled,
            "active": active,
            "basis": "unavailable",
        }
    if sampled >= member_count:
        gap = max(member_count - active, 0)
        basis = "exact"
    else:
        estimated_active = round(active / sampled * member_count)
        gap = max(member_count - estimated_active, 0)
        basis = "estimated-from-sample"
    return {
        "value": gap,
        "memberCount": member_count,
        "sampled": sampled,
        "active": active,
        "basis": basis,
    }


def build_theme(
    *,
    as_of: date,
    concept: Mapping[str, Any],
    limit_ups: Sequence[Mapping[str, Any]],
    limit_up_tokens: Mapping[str, Sequence[str]],
    benchmark_bars: Sequence[Any],
    member_changes: Mapping[str, float] | None,
    anomalies: Sequence[Mapping[str, Any]],
    limit_up_count: int,
    universe: int,
    attribute_tokens: Iterable[str] = (),
) -> dict[str, Any]:
    code = str(concept.get("thscode") or "").strip().upper()
    name = str(concept.get("name") or "").strip()
    members = sorted({str(item).strip().upper() for item in concept.get("members") or [] if str(item).strip()})
    observed_rows = [
        row for row in limit_ups if str(row.get("thscode") or "").strip().upper() in set(members)
    ]
    observed = len(observed_rows)
    lift = compute_lift(observed, len(members), limit_up_count, universe)
    # A token that *is* the concept name is the theme's own label, never an
    # attribute: with 4+ concepts in one chain (算力租赁 / 东数西算 / 数据中心 ...)
    # the cross-concept detector would otherwise block the defining token and
    # report a false noCoreTheme.
    own_tokens = {name} | set(split_reason(name))
    blocked_tokens = {token for token in attribute_tokens if token not in own_tokens}
    shared_tokens = build_shared_tokens(observed_rows, attribute_tokens=blocked_tokens)
    ladder_candidates = [
        int(row.get("continueDay") or 0)
        for row in observed_rows
        if row.get("continueDay") is not None
    ]
    ladder_depth = max(ladder_candidates) if ladder_candidates else None

    concept_bars = list(concept.get("bars") or [])
    turnover_mean = mean_turnover(concept_bars, 20)
    metrics = build_metrics(
        concept_bars=concept_bars,
        benchmark_bars=benchmark_bars,
        turnover_mean=turnover_mean,
        member_changes=member_changes,
        ladder_depth=ladder_depth,
        shared_holder_count=(shared_tokens[0]["count"] if shared_tokens else None),
        observed=observed,
    )
    score, coverage = total_score(metrics)
    tier, tier_reasons = classify_tier(
        score=score,
        lift=lift,
        shared_count=(shared_tokens[0]["count"] if shared_tokens else 0),
        ladder_depth=ladder_depth,
        observed=observed,
    )
    catalyst = build_catalyst(
        shared_tokens=shared_tokens,
        anomalies=anomalies,
        member_codes=members,
        as_of=as_of,
    )

    last_bar = concept_bars[-1] if concept_bars else None
    close = float(last_bar.close) if last_bar is not None else None
    confirmation = _build_predicate(close, turnover_mean, kind="confirmation")
    invalidation = _build_predicate(close, turnover_mean, kind="invalidation")

    active = len(member_changes or {})
    change_values = sorted(
        float(value)
        for value in (member_changes or {}).values()
        if value is not None
    )
    median_change = (
        change_values[len(change_values) // 2] if change_values else None
    )
    advance_ratio = (
        sum(1 for value in change_values if value > 0) / len(change_values)
        if change_values
        else None
    )
    return {
        "themeId": theme_id(as_of, code, shared_tokens),
        "name": name,
        "type": "concept",
        "concept": {
            "thscode": code,
            "name": name,
            "memberCount": len(members),
            "barsObservations": len(concept_bars),
            "barsStart": concept_bars[0].trading_date.isoformat() if concept_bars else None,
            "barsEnd": concept_bars[-1].trading_date.isoformat() if concept_bars else None,
        },
        "direction": None,
        "tier": tier,
        "tierReasons": tier_reasons,
        "score": None if score is None else round(score, 2),
        "confidence": confidence_from_coverage(coverage),
        "status": "ok" if score is not None else STATUS_INSUFFICIENT,
        "lift": None if lift is None else round(lift, 4),
        "observed": observed,
        "expected": (
            None
            if lift is None or lift == 0
            else round(observed / lift, 4)
        ),
        "metrics": [metric.to_dict() for metric in metrics],
        "catalyst": catalyst,
        "members": {
            "codes": members,
            "sampled": active,
            "medianChange": round(median_change, 6) if median_change is not None else None,
            "advanceRatio": round(advance_ratio, 6) if advance_ratio is not None else None,
            "membershipGap": membership_gap(
                len(members),
                sampled=active,
                active=active,
            ),
            "limitUp": [
                {
                    "thscode": str(row.get("thscode") or ""),
                    "name": str(row.get("name") or ""),
                    "reason": str(row.get("reason") or ""),
                    "continueDay": int(row.get("continueDay") or 1),
                }
                for row in sorted(
                    observed_rows,
                    key=lambda item: (
                        -int(item.get("continueDay") or 0),
                        str(item.get("thscode") or ""),
                    ),
                )
            ],
            "sharedTokens": shared_tokens,
        },
        "confirmation": confirmation,
        "invalidation": invalidation,
        "calibration": "needs-backtest",
    }


def _build_predicate(close: float | None, turnover_mean: float | None, *, kind: str) -> dict[str, Any] | None:
    if close is None:
        return None
    # Local import keeps theming importable without the core on sys.path in
    # pure unit tests; the pipeline adds core before calling.
    from qts04.predicate import build_confirmation, build_invalidation

    if kind == "confirmation":
        return build_confirmation(close, turnover_mean)
    return build_invalidation(close, turnover_mean)


def rank_key(theme: Mapping[str, Any]) -> tuple[int, float, float, int, str]:
    tier = str(theme.get("tier") or TIER_EVENT)
    rank = TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER)
    score = float(theme.get("score") or -1)
    lift = float(theme.get("lift") or -1)
    observed = int(theme.get("observed") or 0)
    return (rank, -score, -lift, -observed, str(theme.get("name") or ""))
