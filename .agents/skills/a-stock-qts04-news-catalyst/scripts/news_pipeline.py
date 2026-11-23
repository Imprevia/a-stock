"""QTS-04 STEP 2.5 news layer: acquisition, attribution, polarity and risk."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import AbstractSet, Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

SKILL_DIR = Path(__file__).resolve().parent.parent
_CORE = SKILL_DIR.parent / "qts04-core" / "scripts"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from qts04.client import (  # noqa: E402
    FuyaoClient,
    FuyaoDegraded,
    FuyaoError,
    FuyaoInsufficient,
)
from qts04.contract import attach_identity, require_schema_version  # noqa: E402

import news  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
SETTLEMENT = clock_time(15, 10)

SCHEMA_VERSION = news.SCHEMA_VERSION
STEP = news.STEP
RULE_VERSION = news.RULE_VERSION

DEFAULT_LOOKBACK_DAYS = 10
MAX_LOOKBACK_DAYS = 30
DEFAULT_MAX_TIMELINE_CODES = 10
DEFAULT_TIMELINE_PAGES = 2
DEFAULT_CACHE_DIR = SKILL_DIR / ".cache" / "qts04" / "news"

DISCLAIMER = (
    "本报告由公开资讯的厂商摘要与涨停原因机械归类生成，只表达文本方向与风险提示，"
    "不构成投资建议，不预测收益；规则状态 needs-backtest，未覆盖不等于无利空。"
)

REPORT_ID_FIELDS = (
    "schemaVersion",
    "step",
    "ruleVersion",
    "asOf",
    "config",
    "input",
    "units",
    "stocks",
    "lexicon",
)

_REASON_SPLIT = re.compile(r"[+＋/、,，;；|\s]+")
_BRACKET = re.compile(r"[（(][^）)]*[）)]")
_DATE_PREFIX = re.compile(r"(\d{4}-\d{2}-\d{2})")

UPSTREAM_SCHEMA = "1.0"


def resolve_as_of(value: str, *, now: datetime | None = None) -> date:
    """Reject future days and same-day runs before the 15:10 settlement."""

    try:
        target = date.fromisoformat(str(value).strip())
    except (TypeError, ValueError) as error:
        raise FuyaoInsufficient(f"--as-of 不是合法日期：{value}") from error
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    current = current.astimezone(SHANGHAI)
    if target > current.date():
        raise FuyaoInsufficient(f"目标日 {target} 在未来，拒绝运行")
    if target == current.date() and current.time() < SETTLEMENT:
        raise FuyaoInsufficient(f"目标日 {target} 尚未收盘（15:10 前），拒绝运行")
    return target


def split_reason_tokens(text: Any) -> list[str]:
    value = _BRACKET.sub("", str(text or "").replace("＋", "+")).strip()
    tokens = [token.strip() for token in _REASON_SPLIT.split(value) if token.strip()]
    return list(dict.fromkeys(tokens))


def _normalize_calendar(rows: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    for raw in rows:
        value = str(raw or "").strip()
        if len(value) == 8 and value.isdigit():
            value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
        if value:
            normalized.append(value)
    return normalized


def _cache_dir(base: Path | None, as_of: date) -> Path:
    return (Path(base) if base else DEFAULT_CACHE_DIR) / as_of.isoformat()


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_upstream(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise FuyaoInsufficient(f"{label} 文件不可读：{path}：{error}") from error
    except json.JSONDecodeError as error:
        raise FuyaoInsufficient(f"{label} 不是合法 JSON：{path}：{error}") from error
    if not isinstance(payload, Mapping):
        raise FuyaoInsufficient(f"{label} 顶层必须是对象：{path}")
    try:
        require_schema_version(payload, supported=UPSTREAM_SCHEMA)
    except ValueError as error:
        raise FuyaoInsufficient(f"{label} 版本不兼容：{error}") from error
    return dict(payload)


def build_config(
    *,
    lookback_days: int,
    max_timeline_codes: int,
    lexicon: news.Lexicon,
) -> dict[str, Any]:
    return {
        "lookbackDays": lookback_days,
        "maxLookbackDays": MAX_LOOKBACK_DAYS,
        "halfLifeTradingDays": news.HALF_LIFE_TRADING_DAYS,
        "mixedShare": news.MIXED_SHARE,
        "netThreshold": news.NET_THRESHOLD,
        "negationWindow": news.NEGATION_WINDOW,
        "uncertaintyWindow": news.UNCERTAINTY_WINDOW,
        "keywordSourceFactor": news.KEYWORD_SOURCE_FACTOR,
        "textSourceFactor": news.TEXT_SOURCE_FACTOR,
        "certaintyFactor": dict(news.CERTAINTY_FACTOR),
        "minEvidence": 2,
        "minMembers": 2,
        "maxTimelineCodes": max_timeline_codes,
        "timelinePages": DEFAULT_TIMELINE_PAGES,
        "maxTextChars": news.MAX_TEXT_CHARS,
        "lexiconVersion": lexicon.version,
        "lexiconSha256": lexicon.sha256,
    }


def _decay_for(
    evidence_date: date,
    as_of: date,
    calendar: Sequence[str],
) -> tuple[float, int, str]:
    days = news.trading_day_distance(calendar, evidence_date, as_of)
    basis = "trading"
    if days is None:
        days = max(0, (as_of - evidence_date).days)
        basis = "calendar"
    return news.recency_decay(days), days, basis


def _finalize_events(
    events: Iterable[Mapping[str, Any]],
    *,
    evidence_date: date,
    as_of: date,
    calendar: Sequence[str],
) -> list[dict[str, Any]]:
    decay, days, basis = _decay_for(evidence_date, as_of, calendar)
    finalized: list[dict[str, Any]] = []
    for event in events:
        item = dict(event)
        item["contribution"] = round(news.event_contribution(item, decay), 4)
        item["daysAgo"] = days
        item["decayBasis"] = basis
        finalized.append(item)
    return finalized


def _build_evidence(
    *,
    thscode: str,
    source: str,
    content: str,
    keywords: Sequence[str],
    evidence_date: date,
    date_inferred: bool,
    as_of: date,
    calendar: Sequence[str],
    lexicon: news.Lexicon,
    tag_name: str = "",
    url: str = "",
    name: str = "",
) -> dict[str, Any]:
    routed = news.classify_keywords(keywords, lexicon)
    text_events = news.match_text(content, lexicon)
    events = news.merge_events(routed["events"], text_events)
    events = _finalize_events(events, evidence_date=evidence_date, as_of=as_of, calendar=calendar)
    return {
        "thscode": thscode,
        "name": name,
        "source": source,
        "sourceTag": tag_name,
        "date": evidence_date.isoformat(),
        "dateInferred": date_inferred,
        "content": news.normalize_text(content)[: news.MAX_TEXT_CHARS],
        "url": url,
        "keyWords": list(keywords),
        "topics": routed["topics"],
        "contexts": routed["contexts"],
        "unmatchedKeywords": routed["unmatched"],
        "events": events,
    }


def _evidence_id(item: Mapping[str, Any], index: int) -> str:
    return f"{item.get('source')}:{item.get('thscode')}:{item.get('date')}:{index}"


def _dedupe_evidence(items: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    """Drop duplicate texts; count unattributable rows separately."""

    kept: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    duplicates = 0
    unattributed = 0
    for item in items:
        code = str(item.get("thscode") or "")
        if not code:
            unattributed += 1
            continue
        key = f"{code}|{news.dedupe_key(item.get('content'), fallback=str(item.get('url') or code))}"
        if key in seen:
            duplicates += 1
            continue
        seen[key] = item["evidenceId"]
        kept.append(item)
    return kept, duplicates, unattributed


def _anomaly_items(payload: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in payload if isinstance(row, Mapping)]


def _timeline_items(payload: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in payload if isinstance(row, Mapping)]


def _top_events(events: Sequence[Mapping[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for event in events:
        key = (
            str(event.get("ruleId")),
            str(event.get("eventType")),
            str(event.get("polarity")),
            str(event.get("severity")),
        )
        if key not in unique:
            unique[key] = {
                "ruleId": event.get("ruleId"),
                "eventType": event.get("eventType"),
                "polarity": event.get("polarity"),
                "severity": event.get("severity"),
                "matchedText": event.get("matchedText"),
                "source": event.get("source"),
                "count": 0,
            }
        unique[key]["count"] += 1
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            -news.SEVERITY_ORDER.get(str(item.get("severity")), 0),
            str(item.get("eventType")),
        ),
    )
    return ordered[:limit]


def _active(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(event) for event in events if event.get("active", True)]


def _build_units(
    *,
    step1: Mapping[str, Any] | None,
    step2: Mapping[str, Any] | None,
    evidence: Sequence[Mapping[str, Any]],
    constituents: Mapping[str, Sequence[Mapping[str, Any]]],
    warnings: list[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    units: list[dict[str, Any]] = []
    all_members: set[str] = set()
    if step2:
        for theme in step2.get("themes") or []:
            if not isinstance(theme, Mapping):
                continue
            members_block = theme.get("members")
            member_codes = members_block.get("codes") if isinstance(members_block, Mapping) else []
            members = [
                news.normalize_code(code)
                for code in member_codes or []
                if news.normalize_code(code)
            ]
            units.append(
                {
                    "unitId": f"theme:{theme.get('themeId')}",
                    "unitType": "theme",
                    "name": str(theme.get("name") or ""),
                    "thscode": (
                        (theme.get("concept") or {}).get("thscode")
                        if isinstance(theme.get("concept"), Mapping)
                        else None
                    ),
                    "tier": theme.get("tier"),
                    "members": {"count": len(members), "pointInTime": False},
                    "_codes": members,
                }
            )
    if step1:
        for direction in step1.get("directions") or []:
            if not isinstance(direction, Mapping):
                continue
            thscode = str(direction.get("thscode") or "").strip().upper()
            rows = constituents.get(thscode) or []
            members = [
                news.normalize_code(row.get("thscode") if isinstance(row, Mapping) else row)
                for row in rows
            ]
            members = [code for code in members if code]
            if not members:
                warnings.append(f"{thscode} 没有可用成分股，板块单元记为覆盖不足")
            units.append(
                {
                    "unitId": f"sector:{thscode}",
                    "unitType": "sector",
                    "name": str(direction.get("name") or ""),
                    "thscode": thscode,
                    "tier": direction.get("pool"),
                    "members": {"count": len(members), "pointInTime": False},
                    "_codes": members,
                }
            )
    by_code: dict[str, list[Mapping[str, Any]]] = {}
    for item in evidence:
        by_code.setdefault(str(item.get("thscode")), []).append(item)

    result: list[dict[str, Any]] = []
    for unit in units:
        codes = unit.pop("_codes")
        member_set = set(codes)
        all_members.update(member_set)
        unit_evidence = [
            item
            for code in member_set
            for item in by_code.get(code, [])
        ]
        covered = len({str(item.get("thscode")) for item in unit_evidence})
        events: list[dict[str, Any]] = []
        for item in unit_evidence:
            events.extend(_active(item.get("events") or []))
        polarity = news.aggregate_polarity(
            events,
            evidence_count=len(unit_evidence),
            covered_members=covered,
            member_count=len(member_set),
            unit=True,
        )
        unit.update(
            {
                "evidenceCount": len(unit_evidence),
                "coveredMembers": covered,
                "polarity": polarity,
                "events": _top_events(events),
                "evidenceRefs": [item.get("evidenceId") for item in unit_evidence[:20]],
                "missingReason": polarity.get("missingReason"),
            }
        )
        result.append(unit)
    result.sort(key=lambda item: (str(item.get("unitType")), str(item.get("unitId"))))
    return result, all_members


def _build_stocks(
    *,
    codes: Sequence[str],
    unit_members: AbstractSet[str],
    evidence: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_code: dict[str, list[Mapping[str, Any]]] = {}
    for item in evidence:
        by_code.setdefault(str(item.get("thscode")), []).append(item)

    explicit = {news.normalize_code(code) for code in codes if news.normalize_code(code)}
    # Explicit codes are always shown (even when uncovered); unit members are
    # shown only when they carry evidence, so a theme cannot inflate the list.
    selected = explicit | {code for code in unit_members if code in by_code}

    stocks: list[dict[str, Any]] = []
    for code in sorted(selected):
        items = by_code.get(code, [])
        events: list[dict[str, Any]] = []
        for item in items:
            events.extend(_active(item.get("events") or []))
        risk = news.stock_risk(events, len(items))
        polarity = news.aggregate_polarity(
            events,
            evidence_count=len(items),
            covered_members=1 if items else 0,
            member_count=1,
            unit=False,
        )
        flags = [
            {
                "ruleId": event.get("ruleId"),
                "eventType": event.get("eventType"),
                "severity": event.get("severity"),
                "matchedText": event.get("matchedText"),
                "source": event.get("source"),
            }
            for event in events
            if event.get("polarity") == news.POLARITY_NEGATIVE
        ]
        name = next((str(item.get("name")) for item in items if item.get("name")), "")
        stocks.append(
            {
                "thscode": code,
                "name": name,
                "riskLevel": risk,
                "coverage": "covered" if items else "uncovered",
                "evidenceCount": len(items),
                "polarity": polarity,
                "flags": flags[:20],
                "events": _top_events(events),
                "evidenceRefs": [item.get("evidenceId") for item in items[:20]],
                "missingReason": None
                if items
                else "窗口内没有归属证据或来源不可用；未覆盖不等于无利空",
            }
        )
    return stocks


def _status_for(
    *,
    sources: Mapping[str, Any],
    units: Sequence[Mapping[str, Any]],
    stocks: Sequence[Mapping[str, Any]],
) -> str:
    anomaly = sources.get("anomalyAnalysis") or {}
    limit_up = sources.get("limitUpReason") or {}
    if anomaly.get("status") != "ok" and limit_up.get("status") != "ok":
        return news.STATUS_INSUFFICIENT
    if not units and not stocks:
        return news.STATUS_INSUFFICIENT
    timeline = sources.get("stockTimeline") or {}
    if timeline.get("status") == "unavailable":
        return news.STATUS_DEGRADED
    if anomaly.get("status") != "ok" or limit_up.get("status") != "ok":
        return news.STATUS_DEGRADED
    if any((unit.get("polarity") or {}).get("label") == news.POLARITY_UNKNOWN for unit in units):
        return news.STATUS_DEGRADED
    return news.STATUS_OK


def run_pipeline(
    *,
    as_of: date,
    fixture: Path | Mapping[str, Any] | None = None,
    step1_path: Path | None = None,
    step2_path: Path | None = None,
    codes: Sequence[str] = (),
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    max_timeline_codes: int = DEFAULT_MAX_TIMELINE_CODES,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the layer.  A fixture mapping/path never touches the network."""

    if lookback_days < 1 or lookback_days > MAX_LOOKBACK_DAYS:
        raise FuyaoInsufficient(f"lookbackDays 必须在 1—{MAX_LOOKBACK_DAYS} 之间")
    if not fixture and not step1_path and not step2_path and not codes:
        raise FuyaoInsufficient("没有分析单元：请提供 --step1/--step2/--codes 之一")

    lexicon = news.load_lexicon()
    warnings: list[str] = []
    start = as_of - timedelta(days=lookback_days)
    fixture_payload = fixture
    if isinstance(fixture, Path):
        fixture_payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
    fixture_map = fixture_payload if isinstance(fixture_payload, Mapping) else None

    step1: dict[str, Any] | None = None
    step2: dict[str, Any] | None = None
    if step1_path:
        step1 = _load_upstream(Path(step1_path), "STEP 1 JSON")
    elif fixture_map and isinstance(fixture_map.get("step1"), Mapping):
        step1 = _load_upstream_payload(fixture_map["step1"], "STEP 1 fixture")
    if step2_path:
        step2 = _load_upstream(Path(step2_path), "STEP 2 JSON")
    elif fixture_map and isinstance(fixture_map.get("step2"), Mapping):
        step2 = _load_upstream_payload(fixture_map["step2"], "STEP 2 fixture")

    client: FuyaoClient | None = None
    calendar: list[str] = []
    if fixture_map is not None:
        calendar = _normalize_calendar(fixture_map.get("tradingDays") or [])
    else:
        client = FuyaoClient()
        try:
            client.check_prerequisites()
        except FuyaoError as error:
            raise FuyaoInsufficient(f"前置条件不满足：{error}") from error
        calendar_cache = _cache_dir(cache_dir, as_of) / "calendar.json"
        cached_calendar = _read_json(calendar_cache) if use_cache else None
        if isinstance(cached_calendar, list) and cached_calendar:
            calendar = [str(day) for day in cached_calendar]
        else:
            try:
                calendar = _normalize_calendar(client.market_calendar())
                _write_json(calendar_cache, calendar)
            except FuyaoError as error:
                warnings.append(f"交易日历取数失败，无法证明非交易日：{error}")

    if calendar and as_of.isoformat() not in calendar:
        raise FuyaoInsufficient(f"目标日 {as_of} 不在交易日历中（非交易日或日历窗口不足）")
    if not calendar and as_of.weekday() >= 5:
        raise FuyaoInsufficient(f"交易日历不可用，且目标日 {as_of} 是周末，拒绝运行")

    # ---- anomalies -----------------------------------------------------
    anomaly_cache = _cache_dir(cache_dir, as_of) / f"anomaly-{start.isoformat()}_{as_of.isoformat()}.json"
    anomaly_rows: list[dict[str, Any]] = []
    anomaly_status = "ok"
    if fixture_map is not None:
        anomaly_rows = _anomaly_items(fixture_map.get("anomalies") or [])
        anomaly_status = "ok" if anomaly_rows else "empty"
    else:
        cached = _read_json(anomaly_cache) if use_cache else None
        if isinstance(cached, list):
            anomaly_rows = _anomaly_items(cached)
        else:
            try:
                if client is None:
                    raise FuyaoInsufficient("异动解读需要 FuyaoClient")
                anomaly_rows = client.anomaly_analysis_range(start, as_of)
            except FuyaoError as error:
                anomaly_status = "unavailable"
                warnings.append(f"异动解读取数失败：{error}")
            else:
                _write_json(anomaly_cache, anomaly_rows)
            if not anomaly_rows:
                anomaly_status = anomaly_status if anomaly_status != "ok" else "empty"

    evidence: list[dict[str, Any]] = []
    for index, row in enumerate(anomaly_rows):
        code = news.normalize_code(row.get("thscode"))
        url = str(row.get("url") or "")
        parsed = news.parse_date_from_url(url)
        evidence_date = parsed or as_of
        item = _build_evidence(
            thscode=code,
            source="anomalyAnalysis",
            content=str(row.get("content") or ""),
            keywords=[str(word) for word in row.get("keyWords") or []],
            evidence_date=evidence_date,
            date_inferred=parsed is None,
            as_of=as_of,
            calendar=calendar,
            lexicon=lexicon,
            tag_name=str(row.get("tagName") or ""),
            url=url,
        )
        item["evidenceId"] = _evidence_id(item, index)
        evidence.append(item)

    # ---- limit-up reasons ---------------------------------------------
    limit_cache = _cache_dir(cache_dir, as_of) / "limit-up.json"
    limit_rows: list[dict[str, Any]] = []
    limit_status = "ok"
    if fixture_map is not None:
        limit_rows = [dict(row) for row in fixture_map.get("limitUps") or [] if isinstance(row, Mapping)]
        limit_status = "ok" if limit_rows else "empty"
    else:
        cached = _read_json(limit_cache) if use_cache else None
        if isinstance(cached, list):
            limit_rows = [dict(row) for row in cached if isinstance(row, Mapping)]
        else:
            try:
                if client is None:
                    raise FuyaoInsufficient("涨停池需要 FuyaoClient")
                limit_rows = client.limit_up_pool(as_of)
                _write_json(limit_cache, limit_rows)
            except FuyaoError as error:
                limit_status = "unavailable"
                warnings.append(f"涨停池取数失败：{error}")
            if not limit_rows:
                limit_status = limit_status if limit_status != "ok" else "empty"

    for index, row in enumerate(limit_rows):
        reason = str(row.get("reason") or "")
        if not reason.strip():
            continue
        item = _build_evidence(
            thscode=news.normalize_code(row.get("thscode")),
            source="limitUpReason",
            content=reason,
            keywords=split_reason_tokens(reason),
            evidence_date=as_of,
            date_inferred=False,
            as_of=as_of,
            calendar=calendar,
            lexicon=lexicon,
            tag_name="涨停原因",
            name=str(row.get("name") or ""),
        )
        item["evidenceId"] = _evidence_id(item, index)
        evidence.append(item)

    # ---- optional per-stock timeline ----------------------------------
    timelines = fixture_map.get("timelines") if fixture_map else None
    timeline_status = "ok" if timelines else ("empty" if fixture_map is not None else "disabled")
    timeline_reason = ""
    probed: list[str] = []
    if fixture_map is not None:
        if fixture_map.get("timelineError"):
            timeline_status = "unavailable"
            timeline_reason = str(fixture_map["timelineError"])
    elif max_timeline_codes <= 0:
        timeline_status = "disabled"
    elif max_timeline_codes > 0:
        if client is None:
            raise FuyaoInsufficient("个股新闻需要 FuyaoClient")
        wanted = [news.normalize_code(code) for code in codes if news.normalize_code(code)]
        for code in wanted[:max_timeline_codes]:
            if any(str(item.get("thscode")) == code for item in evidence):
                continue
            probed.append(code)
            timeline_cache = _cache_dir(cache_dir, as_of) / "timeline" / f"{code}.json"
            cached_rows = _read_json(timeline_cache) if use_cache else None
            if isinstance(cached_rows, list):
                timelines = dict(timelines or {})
                timelines[code] = cached_rows
                continue
            try:
                rows = client.stock_timeline(code, size=50, max_pages=DEFAULT_TIMELINE_PAGES)
            except FuyaoInsufficient as error:
                timeline_status = "unavailable"
                timeline_reason = str(error)
                break
            except FuyaoError as error:
                timeline_status = "unavailable"
                timeline_reason = str(error)
                warnings.append(f"{code} 个股新闻取数失败：{error}")
                continue
            timelines = dict(timelines or {})
            timelines[code] = rows
            timeline_status = "ok" if rows else "empty"
            _write_json(timeline_cache, rows)
    for code, rows in (timelines or {}).items():
        normalized = news.normalize_code(code)
        for index, row in enumerate(_timeline_items(rows)):
            content = str(row.get("content") or row.get("title") or "")
            if not content.strip():
                continue
            published = str(row.get("publishedAt") or "")
            match = _DATE_PREFIX.match(published)
            parsed = date.fromisoformat(match.group(1)) if match else None
            item = _build_evidence(
                thscode=normalized,
                source="stockTimeline",
                content=content,
                keywords=[],
                evidence_date=parsed or as_of,
                date_inferred=parsed is None,
                as_of=as_of,
                calendar=calendar,
                lexicon=lexicon,
                tag_name="个股新闻",
                url=str(row.get("url") or ""),
            )
            item["evidenceId"] = _evidence_id(item, index)
            evidence.append(item)

    # ---- attribution ---------------------------------------------------
    evidence, duplicates, unattributed = _dedupe_evidence(evidence)
    evidence.sort(key=lambda item: (str(item.get("date")), str(item.get("thscode")), str(item.get("evidenceId"))))

    constituents: dict[str, Sequence[Mapping[str, Any]]] = {}
    if fixture_map is not None:
        raw = fixture_map.get("constituents") or {}
        if isinstance(raw, Mapping):
            constituents = {str(key): list(value) for key, value in raw.items() if isinstance(value, list)}
    elif step1 and client is not None:
        for direction in step1.get("directions") or []:
            code = str((direction or {}).get("thscode") or "").strip().upper()
            if not code:
                continue
            cached = _read_json(_cache_dir(cache_dir, as_of) / "constituents" / f"{code}.json") if use_cache else None
            if isinstance(cached, list):
                constituents[code] = cached
                continue
            try:
                rows = client.constituents(code)
            except FuyaoError as error:
                warnings.append(f"{code} 成分股取数失败：{error}")
                continue
            constituents[code] = rows
            _write_json(_cache_dir(cache_dir, as_of) / "constituents" / f"{code}.json", rows)

    units, unit_members = _build_units(
        step1=step1,
        step2=step2,
        evidence=evidence,
        constituents=constituents,
        warnings=warnings,
    )
    stocks = _build_stocks(codes=codes, unit_members=unit_members, evidence=evidence)

    sources = {
        "anomalyAnalysis": {
            "status": anomaly_status,
            "count": len(anomaly_rows),
            "window": {"start": start.isoformat(), "end": as_of.isoformat()},
        },
        "limitUpReason": {"status": limit_status, "count": len(limit_rows)},
        "stockTimeline": {
            "status": timeline_status,
            "reason": timeline_reason,
            "probed": probed,
            "count": sum(len(rows) for rows in (timelines or {}).values()),
        },
    }
    status = _status_for(sources=sources, units=units, stocks=stocks)
    if status == news.STATUS_OK and not calendar:
        status = news.STATUS_DEGRADED

    point_in_time = False
    quality = {
        "status": status,
        "sources": sources,
        "coverage": {
            "evidenceItems": len(evidence),
            "duplicates": duplicates,
            "unattributed": unattributed,
            "calendar": "ok" if calendar else "unavailable",
            "calendarDays": len(calendar),
            "pointInTime": point_in_time,
            "backtestGrade": "C",
        },
        "warnings": warnings,
    }
    evidence_block = [
        {
            "evidenceId": item.get("evidenceId"),
            "thscode": item.get("thscode"),
            "name": item.get("name"),
            "source": item.get("source"),
            "date": item.get("date"),
            "dateInferred": item.get("dateInferred"),
            "content": str(item.get("content") or "")[:300],
            "events": _top_events(_active(item.get("events") or [])),
            "suppressedCount": sum(
                1 for event in item.get("events") or [] if not event.get("active", True)
            ),
        }
        for item in evidence
    ]
    normalized_codes = sorted({news.normalize_code(code) for code in codes if news.normalize_code(code)})
    input_block = {
        "step1ReportId": (step1 or {}).get("reportId"),
        "step2ReportId": (step2 or {}).get("reportId"),
        "codes": normalized_codes,
        "lookbackDays": lookback_days,
        "anomalyItems": len(anomaly_rows),
        "limitUpItems": len(limit_rows),
        "evidenceItems": len(evidence),
        "timelineCodes": len(timelines or {}),
    }
    result = {
        "asOf": as_of.isoformat(),
        "step": STEP,
        "ruleVersion": RULE_VERSION,
        "status": status,
        "config": build_config(
            lookback_days=lookback_days,
            max_timeline_codes=max_timeline_codes,
            lexicon=lexicon,
        ),
        "input": input_block,
        "quality": quality,
        "primarySourceAvailable": False,
        "primarySourceReason": "公告/政策主源不可枚举（公告详情需 opaque seq），厂商 AI 摘要最高只能支撑 partial",
        "units": units,
        "stocks": stocks,
        "evidence": evidence_block,
        "lexicon": {
            "version": lexicon.version,
            "sha256": lexicon.sha256,
            "path": news.DEFAULT_LEXICON_NAME,
            "ruleCount": len(lexicon.rules),
            "eventRules": len(lexicon.of_class("event")),
            "topicRules": len(lexicon.of_class("topic")),
            "contextRules": len(lexicon.of_class("context")),
        },
        "unmatchedKeywords": _unmatched_keywords(evidence),
        "disclaimer": DISCLAIMER,
        "calibration": "needs-backtest",
    }
    attach_identity(
        result,
        schema_version=SCHEMA_VERSION,
        fields=REPORT_ID_FIELDS,
        step=STEP,
    )
    return result


def _load_upstream_payload(payload: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise FuyaoInsufficient(f"{label} 顶层必须是对象")
    try:
        require_schema_version(payload, supported=UPSTREAM_SCHEMA)
    except ValueError as error:
        raise FuyaoInsufficient(f"{label} 版本不兼容：{error}") from error
    return dict(payload)


def _unmatched_keywords(evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in evidence:
        for keyword in item.get("unmatchedKeywords") or []:
            counts[str(keyword)] = counts.get(str(keyword), 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:50]
    return [{"keyword": keyword, "count": count} for keyword, count in ranked]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QTS-04 STEP 2.5 消息面极性（利好/利空）")
    parser.add_argument("--as-of", dest="as_of", required=True, help="目标交易日 YYYY-MM-DD")
    parser.add_argument("--fixture", type=Path, default=None, help="离线 fixture JSON")
    parser.add_argument("--step1", type=Path, default=None, help="STEP 1 JSON（可选）")
    parser.add_argument("--step2", type=Path, default=None, help="STEP 2 JSON（可选）")
    parser.add_argument("--codes", default="", help="逗号分隔的股票代码")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--max-timeline-codes", type=int, default=DEFAULT_MAX_TIMELINE_CODES)
    parser.add_argument("--cache-dir", dest="cache_dir", type=Path, default=None)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--format", choices=("json", "markdown", "both"), default="json")
    args = parser.parse_args(argv)

    codes = [code.strip() for code in str(args.codes).split(",") if code.strip()]
    if args.fixture:
        try:
            json.loads(args.fixture.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"fixture 不可读：{error}", file=sys.stderr)
            return 2
    try:
        target = resolve_as_of(args.as_of)
        result = run_pipeline(
            as_of=target,
            fixture=args.fixture,
            step1_path=args.step1,
            step2_path=args.step2,
            codes=codes,
            lookback_days=args.lookback_days,
            max_timeline_codes=args.max_timeline_codes,
            cache_dir=args.cache_dir,
            use_cache=not args.refresh,
        )
    except (FuyaoError, ValueError) as error:
        status = getattr(error, "status", news.STATUS_INSUFFICIENT)
        message = str(error)
        try:
            lexicon = news.load_lexicon()
            config_block = build_config(
                lookback_days=args.lookback_days,
                max_timeline_codes=args.max_timeline_codes,
                lexicon=lexicon,
            )
            lexicon_block = {
                "version": lexicon.version,
                "sha256": lexicon.sha256,
                "path": news.DEFAULT_LEXICON_NAME,
                "ruleCount": len(lexicon.rules),
                "eventRules": len(lexicon.of_class("event")),
                "topicRules": len(lexicon.of_class("topic")),
                "contextRules": len(lexicon.of_class("context")),
            }
        except news.LexiconError:
            config_block = {"lookbackDays": args.lookback_days}
            lexicon_block = {"version": None, "sha256": None, "ruleCount": 0}
        result = {
            "asOf": args.as_of,
            "step": STEP,
            "ruleVersion": RULE_VERSION,
            "status": status,
            "config": config_block,
            "input": {"codes": codes},
            "quality": {"status": status, "warnings": [message], "sources": {}},
            "primarySourceAvailable": False,
            "primarySourceReason": "主源不可枚举",
            "units": [],
            "stocks": [],
            "lexicon": lexicon_block,
            "unmatchedKeywords": [],
            "disclaimer": DISCLAIMER,
            "calibration": "needs-backtest",
        }
        version_match = re.search(r"schemaVersion：([0-9.]+)（当前 ([0-9.]+)）", message)
        if version_match:
            result["upstreamSchemaVersion"] = float(version_match.group(1))
            result["supportedSchemaVersion"] = float(version_match.group(2))
        attach_identity(
            result,
            schema_version=SCHEMA_VERSION,
            fields=REPORT_ID_FIELDS,
            step=STEP,
        )

    from news_report import default_report_path, render_markdown

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
    return 0 if result.get("status") in {news.STATUS_OK, news.STATUS_DEGRADED} else 1


if __name__ == "__main__":
    raise SystemExit(main())
