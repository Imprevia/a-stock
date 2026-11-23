"""Deterministic QTS-04 STEP 2.5 news-catalyst scoring.

The unit of analysis is an evidence item attached to a stock code.  Text is
matched against a versioned lexicon; polarity, severity and confidence are pure
functions of the matches plus a recency decay.  No model calls, no network.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "1.0"
STEP = "STEP 2.5"
RULE_VERSION = "QTS-04-09"

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_INSUFFICIENT = "insufficient"

POLARITY_POSITIVE = "positive"
POLARITY_NEGATIVE = "negative"
POLARITY_MIXED = "mixed"
POLARITY_NEUTRAL = "neutral"
POLARITY_UNKNOWN = "unknown"

RISK_BLOCK = "block"
RISK_DOWNGRADE = "downgrade"
RISK_WATCH = "watch"
RISK_NONE = "none"
RISK_UNCOVERED = "uncovered"

CERTAINTY_PARTIAL = "partial"
CERTAINTY_SPECULATIVE = "speculative"
CERTAINTY_UNKNOWN = "unknown"

SEVERITY_ORDER = {"weak": 1, "medium": 2, "hard": 3}
SEVERITY_NAMES = {1: "weak", 2: "medium", 3: "hard"}

CERTAINTY_FACTOR = {
    CERTAINTY_PARTIAL: 1.0,
    CERTAINTY_SPECULATIVE: 0.6,
    CERTAINTY_UNKNOWN: 0.3,
}

RULE_IDS = frozenset(
    {
        "QTS-04-09-01",
        "QTS-04-09-02",
        "QTS-04-09-03",
        "QTS-04-09-04",
        "QTS-04-09-05",
    }
)

HALF_LIFE_TRADING_DAYS = 3.0
KEYWORD_SOURCE_FACTOR = 1.0
TEXT_SOURCE_FACTOR = 0.8
MIXED_SHARE = 0.30
NET_THRESHOLD = 0.25
NEGATION_WINDOW = 8
UNCERTAINTY_WINDOW = 8
MAX_MATCHES_PER_PATTERN = 3
MAX_TEXT_CHARS = 4000

NEGATION_TOKENS = (
    "不存在",
    "未实施",
    "并未",
    "没有",
    "终止",
    "取消",
    "未能",
    "不及预期",
    "低于预期",
    "不",
    "未",
    "无",
    "否认",
    "并非",
)
UNCERTAINTY_TOKENS = (
    "拟",
    "计划",
    "预计",
    "有望",
    "或将",
    "传闻",
    "媒体报道",
    "据悉",
    "可能存在",
)
SENTENCE_BREAKS = "。；;！!"

POLARITY_LABELS = {
    POLARITY_POSITIVE: "利好",
    POLARITY_NEGATIVE: "利空",
    POLARITY_MIXED: "多空交织",
    POLARITY_NEUTRAL: "中性",
    POLARITY_UNKNOWN: "无法判定",
}
RISK_LABELS = {
    RISK_BLOCK: "硬否决",
    RISK_DOWNGRADE: "降级",
    RISK_WATCH: "观察",
    RISK_NONE: "未见利空",
    RISK_UNCOVERED: "未覆盖",
}
STATUS_LABELS = {
    STATUS_OK: "数据完整",
    STATUS_DEGRADED: "数据降级",
    STATUS_INSUFFICIENT: "数据不足",
}

DEFAULT_LEXICON_NAME = "lexicon.v1.json"

_DATE_IN_URL = re.compile(r"[?&]date=(\d{4}-\d{2}-\d{2})")
_WHITESPACE = re.compile(r"\s+")
_DEDUPE_STRIP = re.compile(r"[\s，。、；;：:!！?？\"'“”‘’（）()\[\]【】]+")


class LexiconError(ValueError):
    """The lexicon file is incomplete or violates the frozen rule mapping."""


@dataclass(frozen=True)
class Rule:
    id: str
    rule_id: str
    cls: str
    event_type: str
    polarity: str
    severity: str
    weight: float
    patterns: tuple[str, ...]
    negation: str
    uncertainty_sensitive: bool


@dataclass(frozen=True)
class Lexicon:
    version: str
    sha256: str
    rules: tuple[Rule, ...]
    by_id: Mapping[str, Rule] = field(default_factory=dict)

    def of_class(self, cls: str) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.cls == cls)


def default_lexicon_path() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / DEFAULT_LEXICON_NAME


def _normalize_pattern(text: Any) -> str:
    return str(text or "").strip()


def load_lexicon(path: Path | None = None) -> Lexicon:
    """Load, validate and hash a lexicon file.

    Hash is computed over the normalized rule set sorted by ``id`` so key
    order, formatting and unrelated JSON fields cannot change the report id.
    """

    target = Path(path) if path is not None else default_lexicon_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as error:
        raise LexiconError(f"词表不可读：{target}：{error}") from error
    except json.JSONDecodeError as error:
        raise LexiconError(f"词表不是合法 JSON：{target}：{error}") from error
    if not isinstance(payload, Mapping):
        raise LexiconError("词表顶层必须是对象")

    version = str(payload.get("version") or "").strip()
    if not version:
        raise LexiconError("词表缺少 version")
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise LexiconError("词表缺少 rules")

    rules: list[Rule] = []
    seen: set[str] = set()
    for item in raw_rules:
        if not isinstance(item, Mapping):
            raise LexiconError("词表规则必须是对象")
        rid = str(item.get("id") or "").strip()
        if not rid:
            raise LexiconError("词表规则缺少 id")
        if rid in seen:
            raise LexiconError(f"词表规则 id 重复：{rid}")
        seen.add(rid)
        rule_id = str(item.get("ruleId") or "").strip()
        if rule_id not in RULE_IDS:
            raise LexiconError(f"{rid}: ruleId 必须是 {sorted(RULE_IDS)} 之一")
        cls = str(item.get("class") or "").strip()
        if cls not in {"event", "topic", "context"}:
            raise LexiconError(f"{rid}: class 必须是 event/topic/context")
        polarity = str(item.get("polarity") or "").strip()
        if polarity not in {
            POLARITY_POSITIVE,
            POLARITY_NEGATIVE,
            POLARITY_MIXED,
            POLARITY_NEUTRAL,
            POLARITY_UNKNOWN,
            "ambiguous",
        }:
            raise LexiconError(f"{rid}: 非法 polarity {polarity}")
        severity = str(item.get("severity") or "weak").strip()
        if severity not in SEVERITY_ORDER:
            raise LexiconError(f"{rid}: 非法 severity {severity}")
        try:
            weight = float(item.get("weight") or 0.0)
        except (TypeError, ValueError) as error:
            raise LexiconError(f"{rid}: weight 必须是数字") from error
        patterns = tuple(
            dict.fromkeys(
                _normalize_pattern(pattern)
                for pattern in item.get("patterns") or []
                if _normalize_pattern(pattern)
            )
        )
        if not patterns:
            raise LexiconError(f"{rid}: patterns 不能为空")
        negation = str(item.get("negation") or "drop").strip()
        if negation not in {"drop", "downgrade", "flip"}:
            raise LexiconError(f"{rid}: 非法 negation {negation}")
        rules.append(
            Rule(
                id=rid,
                rule_id=rule_id,
                cls=cls,
                event_type=str(item.get("eventType") or rid).strip(),
                polarity=polarity,
                severity=severity,
                weight=weight,
                patterns=patterns,
                negation=negation,
                uncertainty_sensitive=bool(item.get("uncertaintySensitive", True)),
            )
        )

    rules.sort(key=lambda rule: rule.id)
    canonical = {
        "version": version,
        "rules": [
            {
                "id": rule.id,
                "ruleId": rule.rule_id,
                "class": rule.cls,
                "eventType": rule.event_type,
                "polarity": rule.polarity,
                "severity": rule.severity,
                "weight": rule.weight,
                "patterns": list(rule.patterns),
                "negation": rule.negation,
                "uncertaintySensitive": rule.uncertainty_sensitive,
            }
            for rule in rules
        ],
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return Lexicon(
        version=version,
        sha256=digest,
        rules=tuple(rules),
        by_id={rule.id: rule for rule in rules},
    )


# ---------------------------------------------------------------------------
# evidence normalization
# ---------------------------------------------------------------------------


def normalize_text(text: Any) -> str:
    return _WHITESPACE.sub(" ", str(text or "")).strip()


def dedupe_key(text: Any, fallback: str = "") -> str:
    normalized = _DEDUPE_STRIP.sub("", normalize_text(text)).casefold()
    if not normalized:
        normalized = normalize_text(fallback).casefold()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def parse_date_from_url(url: Any) -> date | None:
    match = _DATE_IN_URL.search(str(url or ""))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def normalize_code(code: Any) -> str:
    value = str(code or "").strip().upper()
    if not value:
        return ""
    if "." in value:
        return value
    if len(value) == 6 and value.isdigit():
        if value.startswith("6"):
            return f"{value}.SH"
        if value.startswith(("0", "3")):
            return f"{value}.SZ"
        if value.startswith(("4", "8")):
            return f"{value}.BJ"
        if value.startswith("9"):
            return f"{value}.SH"
    return value


def trading_day_distance(calendar: Sequence[str], earlier: date, later: date) -> int | None:
    """Trading days from ``earlier`` to ``later`` when both are in the calendar."""

    try:
        start = list(calendar).index(earlier.isoformat())
        end = list(calendar).index(later.isoformat())
    except ValueError:
        return None
    return max(0, end - start)


def recency_decay(days_ago: int | None, half_life: float = HALF_LIFE_TRADING_DAYS) -> float:
    if days_ago is None or days_ago <= 0:
        return 1.0
    return 0.5 ** (float(days_ago) / float(half_life))


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------


def _left_window(text: str, start: int, size: int) -> str:
    return text[max(0, start - size) : start]


def _has_break(window: str) -> bool:
    return any(character in window for character in SENTENCE_BREAKS)


def is_negated(text: str, start: int) -> bool:
    window = _left_window(text, start, NEGATION_WINDOW)
    if not window or _has_break(window):
        return False
    return any(token in window for token in NEGATION_TOKENS)


def is_uncertain(text: str, start: int) -> bool:
    window = _left_window(text, start, UNCERTAINTY_WINDOW)
    if not window or _has_break(window):
        return False
    return any(token in window for token in UNCERTAINTY_TOKENS)


def _downgrade(severity: str) -> str:
    return SEVERITY_NAMES[max(1, SEVERITY_ORDER.get(severity, 1) - 1)]


def _make_match(
    rule: Rule,
    matched: str,
    *,
    source: str,
    start: int | None = None,
    end: int | None = None,
    negated: bool = False,
    uncertain: bool = False,
) -> dict[str, Any]:
    severity = rule.severity
    certainty = CERTAINTY_PARTIAL
    polarity = rule.polarity
    active = True
    if negated:
        if rule.negation == "drop":
            active = False
        elif rule.negation == "downgrade":
            severity = _downgrade(severity)
            certainty = CERTAINTY_SPECULATIVE
        else:  # flip
            if polarity == POLARITY_POSITIVE:
                polarity = POLARITY_NEGATIVE
            elif polarity == POLARITY_NEGATIVE:
                polarity = POLARITY_POSITIVE
    if uncertain and rule.uncertainty_sensitive and active:
        severity = _downgrade(severity)
        certainty = CERTAINTY_SPECULATIVE
    return {
        "id": rule.id,
        "ruleId": rule.rule_id,
        "eventType": rule.event_type,
        "polarity": polarity,
        "severity": severity,
        "baseWeight": rule.weight,
        "matchedText": matched,
        "source": source,
        "start": start,
        "end": end,
        "negated": negated,
        "uncertain": uncertain,
        "certainty": certainty,
        "active": active,
    }


def classify_keywords(
    keywords: Iterable[str], lexicon: Lexicon
) -> dict[str, list[Any]]:
    """Route vendor keywords into event / topic / context / unmatched buckets."""

    index: dict[str, Rule] = {}
    for rule in lexicon.rules:
        for pattern in rule.patterns:
            index.setdefault(pattern.casefold(), rule)
    events: list[dict[str, Any]] = []
    topics: list[str] = []
    contexts: list[str] = []
    unmatched: list[str] = []
    for raw in keywords:
        keyword = normalize_text(raw)
        if not keyword:
            continue
        rule = index.get(keyword.casefold())
        if rule is None:
            unmatched.append(keyword)
            continue
        if rule.cls == "event":
            events.append(_make_match(rule, keyword, source="keyword"))
        elif rule.cls == "topic":
            topics.append(keyword)
        else:
            contexts.append(keyword)
    return {
        "events": events,
        "topics": list(dict.fromkeys(topics)),
        "contexts": list(dict.fromkeys(contexts)),
        "unmatched": list(dict.fromkeys(unmatched)),
    }


def match_text(text: Any, lexicon: Lexicon) -> list[dict[str, Any]]:
    """Match event rules against the body text, preferring longer patterns."""

    body = normalize_text(text)[:MAX_TEXT_CHARS]
    if not body:
        return []
    raw_matches: list[dict[str, Any]] = []
    for rule in lexicon.rules:
        if rule.cls != "event":
            continue
        for pattern in rule.patterns:
            start = body.find(pattern)
            found = 0
            while start != -1 and found < MAX_MATCHES_PER_PATTERN:
                raw_matches.append(
                    _make_match(
                        rule,
                        pattern,
                        source="text",
                        start=start,
                        end=start + len(pattern),
                        negated=is_negated(body, start),
                        uncertain=is_uncertain(body, start),
                    )
                )
                found += 1
                start = body.find(pattern, start + len(pattern))
    raw_matches.sort(key=lambda item: (item["start"], -(item["end"] - item["start"]), item["id"]))
    selected: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for match in raw_matches:
        span = (int(match["start"]), int(match["end"]))
        if any(not (span[1] <= a or span[0] >= b) for a, b in occupied):
            continue
        occupied.append(span)
        selected.append(match)
    return selected


def merge_events(
    keyword_events: Sequence[Mapping[str, Any]],
    text_events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Reconcile vendor keywords with the body text.

    A keyword is a vendor label without context, so the body wins when it
    explicitly negates the same rule (otherwise ``终止减持`` would still score
    as a reduction).  An active-but-uncertain text match downgrades the
    keyword's severity and certainty instead of discarding it.
    """

    text_by_rule: dict[str, list[Mapping[str, Any]]] = {}
    for item in text_events:
        text_by_rule.setdefault(str(item.get("id")), []).append(item)

    merged: list[dict[str, Any]] = []
    for raw in keyword_events:
        item = dict(raw)
        matches = text_by_rule.get(str(item.get("id"))) or []
        if matches:
            active = [match for match in matches if match.get("active", True)]
            if not active:
                item["active"] = False
                item["negated"] = True
                item["certainty"] = CERTAINTY_UNKNOWN
            else:
                uncertain = [match for match in active if match.get("uncertain")]
                if uncertain:
                    item["severity"] = uncertain[0].get("severity")
                    item["certainty"] = uncertain[0].get("certainty")
                    item["uncertain"] = True
        merged.append(item)

    seen = {str(item.get("id")) for item in merged}
    for item in text_events:
        rid = str(item.get("id"))
        if rid in seen:
            continue
        seen.add(rid)
        merged.append(dict(item))
    return merged


def event_contribution(event: Mapping[str, Any], decay: float) -> float:
    if not event.get("active", True):
        return 0.0
    base = float(event.get("baseWeight") or 0.0)
    factor = KEYWORD_SOURCE_FACTOR if event.get("source") == "keyword" else TEXT_SOURCE_FACTOR
    certainty = CERTAINTY_FACTOR.get(str(event.get("certainty")), CERTAINTY_FACTOR[CERTAINTY_UNKNOWN])
    return base * factor * float(decay) * certainty


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def _empty_polarity(reason: str) -> dict[str, Any]:
    return {
        "label": POLARITY_UNKNOWN,
        "score": 0.0,
        "positiveScore": 0.0,
        "negativeScore": 0.0,
        "positiveShare": 0.0,
        "negativeShare": 0.0,
        "confidence": "insufficient",
        "evidenceCount": 0,
        "coveredMembers": 0,
        "memberCoverage": 0.0,
        "missingReason": reason,
    }


def aggregate_polarity(
    events: Sequence[Mapping[str, Any]],
    *,
    evidence_count: int,
    covered_members: int,
    member_count: int,
    unit: bool,
) -> dict[str, Any]:
    """Aggregate scored events into one of the five polarity labels."""

    positive = sum(
        float(event.get("contribution") or 0.0)
        for event in events
        if event.get("polarity") == POLARITY_POSITIVE
    )
    negative = sum(
        float(event.get("contribution") or 0.0)
        for event in events
        if event.get("polarity") == POLARITY_NEGATIVE
    )
    total = positive + negative

    if unit and (evidence_count < 2 or covered_members < 2):
        result = _empty_polarity(
            f"未过覆盖率闸门：证据 {evidence_count} 条、覆盖 {covered_members} 只成员"
        )
        result.update(
            {
                "evidenceCount": evidence_count,
                "coveredMembers": covered_members,
                "memberCoverage": (covered_members / member_count) if member_count else 0.0,
                "positiveScore": round(positive, 4),
                "negativeScore": round(negative, 4),
            }
        )
        return result
    if evidence_count == 0:
        return _empty_polarity("窗口内没有归属证据")

    positive_share = positive / total if total else 0.0
    negative_share = negative / total if total else 0.0
    score = positive_share - negative_share

    if positive_share >= MIXED_SHARE and negative_share >= MIXED_SHARE:
        label = POLARITY_MIXED
    elif score >= NET_THRESHOLD:
        label = POLARITY_POSITIVE
    elif score <= -NET_THRESHOLD:
        label = POLARITY_NEGATIVE
    elif total > 0:
        label = POLARITY_NEUTRAL
    else:
        label = POLARITY_NEUTRAL if evidence_count else POLARITY_UNKNOWN

    dominant = max(positive_share, negative_share)
    opposite_strong = any(
        event.get("polarity") in {POLARITY_POSITIVE, POLARITY_NEGATIVE}
        and event.get("severity") in {"hard", "medium"}
        and event.get("polarity") != (POLARITY_POSITIVE if score >= 0 else POLARITY_NEGATIVE)
        for event in events
    )
    if evidence_count >= 3 and covered_members >= 2 and dominant >= 0.70 and not opposite_strong:
        confidence = "high"
    elif evidence_count >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "label": label,
        "score": round(score, 4),
        "positiveScore": round(positive, 4),
        "negativeScore": round(negative, 4),
        "positiveShare": round(positive_share, 4),
        "negativeShare": round(negative_share, 4),
        "confidence": confidence,
        "evidenceCount": evidence_count,
        "coveredMembers": covered_members,
        "memberCoverage": round((covered_members / member_count) if member_count else 0.0, 4),
        "missingReason": None,
    }


def stock_risk(events: Sequence[Mapping[str, Any]], evidence_count: int) -> str:
    if evidence_count <= 0:
        return RISK_UNCOVERED
    severities = {
        SEVERITY_ORDER.get(str(event.get("severity")), 0)
        for event in events
        if event.get("polarity") == POLARITY_NEGATIVE and event.get("active", True)
    }
    if not severities:
        return RISK_NONE
    highest = max(severities)
    if highest >= SEVERITY_ORDER["hard"]:
        return RISK_BLOCK
    if highest >= SEVERITY_ORDER["medium"]:
        return RISK_DOWNGRADE
    return RISK_WATCH
