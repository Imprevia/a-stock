"""Explicit, staged acquisition of historical ledger market evidence."""

from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta
from time import monotonic

from ...domain.models.trading_pnl import EvidenceBatch, SessionEvidence
from ...trading_sessions import validate_actual_session_date
from ..ports.trading_pnl import PnlMarketEvidenceError, PnlMarketEvidenceSource, TradingPnlStore
from ..queries.trading_pnl import LocalSessions, TradingPnlQueries, day_range
from .trading_pnl import PnlCommandError, save_evidence


MAX_VALUATIONS = 1000
HISTORY_PHASE_SECONDS = 20
CALENDAR_SOURCE = "Fuyao · A 股交易日历"


def _missing_sessions(local, start: date, end: date, opening: date) -> bool:
    calendar = LocalSessions(local)
    for day in day_range(start, end):
        if calendar.closed(day):
            continue
        resolution = calendar.resolution(day)
        if not resolution.sufficient:
            return True
        previous = resolution.previous_as_of
        if previous and opening < previous < start and not calendar.resolution(previous).sufficient:
            return True
    return False


def _new_sessions(local, remote: tuple[date, ...], start: date, end: date, opening: date) -> list[SessionEvidence]:
    if not remote or remote[-1] < start or remote[0] > end:
        return []
    first = max(bisect_left(remote, opening), bisect_left(remote, start) - 2)
    previous_by_day = {
        day: remote[index - 1] if index else None
        for index, day in enumerate(remote)
        if index >= first and day <= end
    }
    dates = set(previous_by_day) | {
        day for day in day_range(max(start, remote[0]), min(end, remote[-1]))
        if day.weekday() < 5
    }
    result = []
    for day in sorted(dates):
        is_session = day in previous_by_day
        previous = previous_by_day.get(day)
        existing = local.get(day)
        if existing is not None and validate_actual_session_date(day, existing.actual_as_of).valid:
            can_extend = is_session and existing.is_session and existing.previous_as_of is None and previous is not None
            if not can_extend:
                continue
        result.append(SessionEvidence(
            date=day, actual_date=day, previous_date=previous, is_session=is_session, source=CALENDAR_SOURCE,
        ))
    return result


class TradingPnlBackfill:
    def __init__(self, store: TradingPnlStore, queries: TradingPnlQueries,
                 source: PnlMarketEvidenceSource) -> None:
        self.store = store
        self.queries = queries
        self.source = source

    def run(self, start: date, end: date, expected: int) -> dict:
        if end < start or (end - start).days > 365 or end > self.queries.settled_through():
            raise PnlCommandError("补齐范围应在已结算的 366 个自然日以内")
        counts = {"sessions": 0, "valuations": 0}
        with self.store() as repo:
            state = repo.state()
            self._check_revision(state, expected, counts)
            opening = state["opening_date"]
            if opening is None or start <= opening:
                raise PnlCommandError("请先确认期初，补齐范围应在期初之后")
            local = self._local_calendar(repo, start, end)
        revision = expected
        calendar_error = None
        if _missing_sessions(local, start, end, opening):
            try:
                remote = self.source.trading_days()
            except PnlMarketEvidenceError as exc:
                calendar_error = exc.reason
            else:
                if _new_sessions(local, remote, start, end, opening):
                    with self.store(write=True) as repo:
                        state = repo.state(lock=True)
                        self._check_revision(state, revision, counts)
                        sessions = _new_sessions(self._local_calendar(repo, start, end), remote, start, end, opening)
                        if sessions:
                            revision = save_evidence(repo, EvidenceBatch(sessions=sessions), revision, "fuyao-calendar")
                            counts["sessions"] = len(sessions)

        with self.store() as repo:
            self._check_revision(repo.state(), revision, counts)
            missing = self.queries.missing_prices(repo, start, end)
        pending, failures = self._fetch_prices(missing)
        if pending:
            with self.store(write=True) as repo:
                self._check_revision(repo.state(lock=True), revision, counts)
                still_missing = self.queries.missing_prices(repo, start, end)
                values = [row for row in pending if (row.date, row.security) in still_missing]
                if values:
                    revision = save_evidence(repo, EvidenceBatch(valuations=values), revision, "fuyao-closes")
                    counts["valuations"] = len(values)

        with self.store() as repo:
            state = repo.state()
            self._check_revision(state, revision, counts)
            days = self.queries.range_summary(repo, state, start, end)
            missing = self.queries.missing_prices(repo, start, end)
            calendar = LocalSessions(self._local_calendar(repo, start, end))
            earlier_coverage_gap = (repo.first_coverage_gap(start)
                                    if any("prior-holdings-unconfirmed" in day["issues"] for day in days) else None)
        for day in days:
            if "calendar-missing" in day["issues"]:
                resolution = calendar.resolution(day["date"])
                if resolution.sufficient:
                    day["issues"].append(f"calendar-chain-gap:{resolution.previous_as_of}")
                else:
                    day["issues"].append(calendar_error or "fuyao-calendar-coverage")
            if earlier_coverage_gap and "prior-holdings-unconfirmed" in day["issues"]:
                day["issues"].append(f"coverage-blocked:{earlier_coverage_gap}")
        missing_closes = [
            {"date": day, "security": security, "reason": failures.get(security, "fuyao-close-missing")}
            for day, security in sorted(missing)
        ]
        remaining = [{"date": day["date"], "issues": day["issues"]} for day in days if day["issues"]]
        if not remaining and not missing_closes:
            status = "complete"
        elif any(counts.values()) or any(day["status"] == "ok" for day in days):
            status = "partial"
        else:
            status = "insufficient"
        return {"revision": revision, "status": status, "added": counts,
                "remaining": remaining, "missing_closes": missing_closes}

    def _fetch_prices(self, missing):
        dates_by_security = defaultdict(list)
        for day, security in sorted(missing):
            dates_by_security[security].append(day)
        pending = []
        failures = {}
        deadline = monotonic() + HISTORY_PHASE_SECONDS
        for security, dates in dates_by_security.items():
            if len(pending) == MAX_VALUATIONS or monotonic() >= deadline:
                failures[security] = "fuyao-batch-limit"
                continue
            try:
                found = self.source.closes(security, dates[0], dates[-1])
            except PnlMarketEvidenceError as exc:
                failures[security] = exc.reason
                continue
            eligible = [row for row in found if (row.date, row.security) in missing and row.security == security]
            room = MAX_VALUATIONS - len(pending)
            if len(eligible) > room:
                failures[security] = "fuyao-batch-limit"
            pending.extend(eligible[:room])
        return pending, failures

    @staticmethod
    def _local_calendar(repo, start: date, end: date):
        return repo.sessions(start - timedelta(days=32), end + timedelta(days=32))

    @staticmethod
    def _check_revision(state, expected: int, counts: dict) -> None:
        if state["revision"] != expected:
            raise PnlCommandError("台账已更新，请刷新后补齐剩余数据", 409,
                                  detail={"revision": state["revision"], "added": counts})
