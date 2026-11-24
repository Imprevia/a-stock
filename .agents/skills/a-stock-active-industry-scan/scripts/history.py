"""Per-trading-day scan history for the active-industry scan Skill.

The Skill talks to snapshot-only providers, so the only way to describe how a
session evolved is to remember what earlier runs of the same day saw.  This
module stores a compact projection of each result next to the run — not the
full document — so the trajectory section stays small and cannot drift into a
second, competing copy of the report.

Pure helpers are separated from the two file operations so the projection and
the diffing stay testable without touching disk.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

HISTORY_SUBDIR = Path("history")
#: One row per run; older rows are dropped rather than kept forever.  A day has
#: at most ~50 intraday runs, so this keeps a full day plus slack.
MAX_ROWS = 40
MAX_SNAPSHOTS = 12

#: A move smaller than this is noise, not a turning point.
MEDIAN_EPSILON = 0.5
COUNT_RATIO_EPSILON = 0.05
HIT_EPSILON = 2


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def snapshot(document: Mapping[str, Any]) -> dict[str, Any]:
    """Project one result document onto the fields a trajectory needs."""

    market = (document.get("direction") or {}).get("market") or {}
    summary = document.get("directionSummary") or {}
    intersection = document.get("intersection") or []
    handoff = document.get("handoff") or {}
    return {
        "reportId": str(document.get("reportId") or ""),
        "asOf": str(document.get("asOf") or ""),
        "dataCutoff": str(document.get("dataCutoff") or ""),
        "sessionState": str(document.get("sessionState") or ""),
        "elapsedBars": document.get("elapsedBars"),
        "qualityStatus": str((document.get("quality") or {}).get("status") or ""),
        "market": {
            "medianChangePct": _float(market.get("medianChangePct")),
            "upCount": _int(market.get("upCount")),
            "downCount": _int(market.get("downCount")),
            "flatCount": _int(market.get("flatCount")),
            "suspendedCount": _int(market.get("suspendedCount")),
        },
        "byAmount": {
            "up": _int((summary.get("byAmount") or {}).get("up")),
            "down": _int((summary.get("byAmount") or {}).get("down")),
        },
        "byTurnover": {
            "up": _int((summary.get("byTurnover") or {}).get("up")),
            "down": _int((summary.get("byTurnover") or {}).get("down")),
        },
        "industries": [
            {
                "code": str(item.get("code") or ""),
                "name": str(item.get("name") or ""),
                "amountTopCount": _int(item.get("amountTopCount")),
                "turnoverTopCount": _int(item.get("turnoverTopCount")),
                "hitCount": _int(item.get("hitCount")),
                "boardChangePct": _float(item.get("boardChangePct")),
                "relativeToMarketPct": _float(item.get("relativeToMarketPct")),
                "tag": str(item.get("tag") or ""),
            }
            for item in document.get("industries") or []
            if isinstance(item, Mapping)
        ],
        "intersection": {
            "count": len(intersection),
            "names": [str(i.get("name")) for i in intersection if i.get("name")],
            "codes": [str(i.get("code")) for i in intersection if i.get("code")],
        },
        "candidates": [str(code) for code in handoff.get("candidateThscodes") or []],
    }


def history_path(root: Path, day: date) -> Path:
    """One file per trading day inside the store root.

    ``root`` is the store itself (``.../active-industry-scan/history``), so the
    subdirectory name is used only to build that default, never twice.
    """

    return root / f"{day.isoformat()}.jsonl"


def append_run(root: Path, document: Mapping[str, Any]) -> Path | None:
    """Append one run to its day file, replacing an identical report id.

    Re-running the renderer for the *same* run must not add a duplicate row,
    otherwise a stray retry would look like a second scan on the timeline.
    """

    row = snapshot(document)
    as_of = row["asOf"]
    if len(as_of) < 10:
        return None
    try:
        day = date.fromisoformat(as_of[:10])
    except ValueError:
        return None

    target = history_path(root, day)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if target.is_file():
        for line in target.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(existing, Mapping):
                continue
            if row["reportId"] and existing.get("reportId") == row["reportId"]:
                continue
            rows.append(dict(existing))
    rows.append(row)
    rows = rows[-MAX_ROWS:]
    target.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n",
        encoding="utf-8",
    )
    return target


def load_recent(
    root: Path,
    as_of: Mapping[str, Any] | str,
    *,
    exclude_report_id: str = "",
    limit: int = MAX_SNAPSHOTS,
) -> list[dict[str, Any]]:
    """Earlier runs of the same trading day, oldest first.

    The current run is excluded by report id so a caller can render before it
    persists the row and still see only *previous* scans.
    """

    raw = as_of.get("asOf") if isinstance(as_of, Mapping) else as_of
    text = str(raw or "")
    if len(text) < 10:
        return []
    try:
        day = date.fromisoformat(text[:10])
    except ValueError:
        return []
    target = history_path(root, day)
    if not target.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, Mapping):
            continue
        if exclude_report_id and item.get("reportId") == exclude_report_id:
            continue
        rows.append(dict(item))
    return rows[-limit:]


# --------------------------------------------------------------------------
# diffing (pure)
# --------------------------------------------------------------------------


def _delta(current: Any, previous: Any) -> float | None:
    a = _float(current)
    b = _float(previous)
    if a is None or b is None:
        return None
    return a - b


def _pct_change(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    return (current - previous) / previous


def _industry_index(row: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for item in row.get("industries") or []:
        if isinstance(item, Mapping) and item.get("code"):
            out[str(item["code"])] = item
    return out


def highlight_changes(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    top_codes: Sequence[str] = (),
) -> list[str]:
    """Describe what actually moved between two runs.

    Only changes above the stated thresholds are reported; otherwise the
    section would restate the whole table.  An empty list means "nothing above
    threshold", which the renderer states explicitly rather than hiding.
    """

    if previous is None:
        return []
    lines: list[str] = []

    median_delta = _delta(
        (current.get("market") or {}).get("medianChangePct"),
        (previous.get("market") or {}).get("medianChangePct"),
    )
    if median_delta is not None and abs(median_delta) >= MEDIAN_EPSILON:
        lines.append(
            f"全市场中位 {_signed((previous.get('market') or {}).get('medianChangePct'))}"
            f" → {_signed((current.get('market') or {}).get('medianChangePct'))}"
            f"（{median_delta:+.2f}pp）"
        )

    up_delta = _delta(
        (current.get("market") or {}).get("upCount"),
        (previous.get("market") or {}).get("upCount"),
    )
    down_delta = _delta(
        (current.get("market") or {}).get("downCount"),
        (previous.get("market") or {}).get("downCount"),
    )
    previous_up = _int((previous.get("market") or {}).get("upCount"))
    ratio = _pct_change(_int((current.get("market") or {}).get("upCount")), previous_up)
    if ratio is not None and abs(ratio) >= COUNT_RATIO_EPSILON:
        lines.append(
            f"上涨家数 {previous_up} → {_int((current.get('market') or {}).get('upCount'))}"
            f"（{ratio * 100:+.1f}%），下跌家数 "
            f"{_int((previous.get('market') or {}).get('downCount'))}"
            f" → {_int((current.get('market') or {}).get('downCount'))}"
        )

    turnover_before = _int((previous.get("byTurnover") or {}).get("down"))
    turnover_now = _int((current.get("byTurnover") or {}).get("down"))
    if abs(turnover_now - turnover_before) >= 2:
        lines.append(
            f"换手率榜下跌家数 {turnover_before} → {turnover_now}"
            f"（换手榜分歧{'放大' if turnover_now > turnover_before else '收敛'}）"
        )

    now_ix = _industry_index(current)
    before_ix = _industry_index(previous)
    for code in top_codes:
        item = now_ix.get(code)
        if item is None:
            continue
        before = before_ix.get(code)
        if before is None:
            lines.append(f"{item.get('name')} 新进入行业表")
            continue
        hit_delta = _int(item.get("amountTopCount")) - _int(before.get("amountTopCount"))
        board_delta = _delta(item.get("boardChangePct"), before.get("boardChangePct"))
        if abs(hit_delta) >= HIT_EPSILON:
            lines.append(
                f"{item.get('name')} 成交额榜命中 {before.get('amountTopCount')}"
                f" → {item.get('amountTopCount')}"
            )
        if board_delta is not None and abs(board_delta) >= MEDIAN_EPSILON:
            lines.append(
                f"{item.get('name')} 板块 {_signed(before.get('boardChangePct'))}"
                f" → {_signed(item.get('boardChangePct'))}"
                f"（{board_delta:+.2f}pp）"
            )

    before_codes = set((previous.get("intersection") or {}).get("codes") or [])
    now_codes = set((current.get("intersection") or {}).get("codes") or [])
    before_names = dict(
        zip(
            (previous.get("intersection") or {}).get("codes") or [],
            (previous.get("intersection") or {}).get("names") or [],
        )
    )
    now_names = dict(
        zip(
            (current.get("intersection") or {}).get("codes") or [],
            (current.get("intersection") or {}).get("names") or [],
        )
    )
    entered = [now_names.get(code, code) for code in sorted(now_codes - before_codes)]
    left = [before_names.get(code, code) for code in sorted(before_codes - now_codes)]
    if entered or left:
        parts = []
        if entered:
            parts.append("新增 " + "、".join(entered))
        if left:
            parts.append("掉出 " + "、".join(left))
        lines.append(f"双榜交集 {len(before_codes)} → {len(now_codes)} 只（{'；'.join(parts)}）")

    before_candidates = set(previous.get("candidates") or [])
    now_candidates = set(current.get("candidates") or [])
    if before_candidates != now_candidates:
        added = sorted(now_candidates - before_candidates)
        removed = sorted(before_candidates - now_candidates)
        parts = []
        if added:
            parts.append("新增 " + "、".join(added))
        if removed:
            parts.append("移除 " + "、".join(removed))
        lines.append(f"候选行业 {len(before_candidates)} → {len(now_candidates)} 个（{'；'.join(parts)}）")

    return lines


def _signed(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "—"
    return f"{number:+.2f}%"
