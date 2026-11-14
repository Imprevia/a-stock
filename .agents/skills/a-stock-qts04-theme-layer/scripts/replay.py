"""One-year statistical replay for the QTS-04 STEP 2 theme layer.

This is a *statistics* replay: it records status, no-core rate, tier
distribution and lift, not forward returns.  Per-day JSON is intentionally not
written; the summary is the deliverable.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

SKILL_DIR = Path(__file__).resolve().parent.parent
_CORE = SKILL_DIR.parent / "qts04-core" / "scripts"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from qts04.client import FuyaoClient, FuyaoError  # noqa: E402

from theme_pipeline import (  # noqa: E402
    DEFAULT_CACHE_DIR,
    DEFAULT_MARKET_STOCK_COUNT,
    run_pipeline,
)


def _calendar_dates(rows: Sequence[str]) -> list[date]:
    dates: list[date] = []
    for raw in rows:
        text = str(raw)
        try:
            if len(text) == 8 and "-" not in text:
                dates.append(date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:]}"))
            else:
                dates.append(date.fromisoformat(text))
        except ValueError:
            continue
    return sorted(set(dates))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QTS-04 STEP 2 一年窗口统计回放（不做收益回测）")
    parser.add_argument("--start", required=True, help="起始交易日 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束交易日 YYYY-MM-DD")
    parser.add_argument("--step", type=int, default=1, help="每 N 个交易日采样一次")
    parser.add_argument("--max-days", type=int, default=0, help="最多回放多少天（0=全部）")
    parser.add_argument("--max-candidates", type=int, default=24, help="每日最多候选概念数")
    parser.add_argument("--max-themes", type=int, default=5, help="每日最多输出题材数")
    parser.add_argument(
        "--member-sample-limit",
        type=int,
        default=60,
        help="成员涨跌采样上限；统计回放可调小以控制取数成本",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    args = parser.parse_args(argv)

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False))
        return 2

    client = FuyaoClient()
    try:
        client.check_prerequisites()
        calendar_rows = client.market_calendar()
    except FuyaoError as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False))
        return 2
    calendar = [day for day in _calendar_dates(calendar_rows) if start <= day <= end]
    if args.step > 1:
        calendar = calendar[:: args.step]
    if args.max_days > 0:
        calendar = calendar[: args.max_days]
    if not calendar:
        print(json.dumps({"status": "ERROR", "error": "窗口内没有交易日"}, ensure_ascii=False))
        return 2

    rows: list[dict[str, Any]] = []
    for index, day in enumerate(calendar, 1):
        try:
            result = run_pipeline(
                as_of=day,
                client=client,
                cache_dir=args.cache_dir,
                use_cache=True,
                calendar=calendar_rows,
                market_stock_count=DEFAULT_MARKET_STOCK_COUNT,
                max_candidates=args.max_candidates,
                max_themes=args.max_themes,
                member_sample_limit=args.member_sample_limit,
            )
            rows.append(
                {
                    "asOf": day.isoformat(),
                    "status": result.get("status"),
                    "noCoreTheme": bool(result.get("noCoreTheme")),
                    "reportId": result.get("reportId"),
                    "themes": [
                        {
                            "name": theme.get("name"),
                            "tier": theme.get("tier"),
                            "lift": theme.get("lift"),
                            "observed": theme.get("observed"),
                        }
                        for theme in result.get("themes") or []
                    ],
                    "warnings": list((result.get("quality") or {}).get("warnings") or []),
                }
            )
        except (FuyaoError, ValueError) as error:
            rows.append(
                {
                    "asOf": day.isoformat(),
                    "status": getattr(error, "status", "insufficient"),
                    "noCoreTheme": True,
                    "themes": [],
                    "warnings": [str(error)],
                }
            )
        print(
            f"[{index}/{len(calendar)}] {day} {rows[-1]['status']} "
            f"noCore={rows[-1]['noCoreTheme']} themes={len(rows[-1]['themes'])}",
            file=sys.stderr,
        )

    statuses = [row["status"] for row in rows]
    tier_counts: dict[str, int] = {}
    for row in rows:
        for theme in row["themes"]:
            tier = str(theme.get("tier") or "unknown")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
    summary = {
        "window": {"start": start.isoformat(), "end": end.isoformat(), "sampledEvery": args.step},
        "sampling": {
            "maxCandidates": args.max_candidates,
            "maxThemes": args.max_themes,
            "memberSampleLimit": args.member_sample_limit,
        },
        "days": len(rows),
        "statusCounts": {status: statuses.count(status) for status in sorted(set(statuses))},
        "noCoreDays": sum(1 for row in rows if row["noCoreTheme"]),
        "coreDays": sum(1 for row in rows if any(t.get("tier") == "core" for t in row["themes"])),
        "tierCounts": dict(sorted(tier_counts.items())),
        "backtestGrade": "D",
        "gradeReason": "成分股只有当前快照、涨停池约 1 年、异动解读为 AI 汇总文本",
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("window", "days", "statusCounts", "noCoreDays", "coreDays", "tierCounts")}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
