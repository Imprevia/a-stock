"""Explicit, replayable post-import P&L calculation."""

from collections import defaultdict
from datetime import date, timedelta
from time import monotonic
from uuid import uuid4

from ...domain.models.trading_pnl import EvidenceBatch
from ..ports.trading_pnl import PnlMarketEvidenceError
from ..queries.trading_pnl import LocalSessions, day_range
from .trading_pnl import PnlCommandError, save_evidence
from .trading_pnl_backfill import HISTORY_PHASE_SECONDS, TradingPnlBackfill, _missing_sessions, _new_sessions
from .trading_pnl_projection import missing_actions, rebuild, replay_start


def _result(status: str, start: date, end: date | None, revision: int, missing=()) -> dict:
    return {"status": status, "start": start.isoformat(), "end": end.isoformat() if end else None,
            "revision": revision, "missing": list(missing)}


def _issues(days, extra=()) -> list[dict]:
    missing = {(row["date"], row.get("security"), row["reason"]) for row in extra}
    for row in days:
        for issue in row["issues"]:
            if row["status"] == "estimated" and issue.startswith("coverage-unconfirmed"):
                continue
            reason, _, detail = issue.partition(":")
            evidence_date, _, security = detail.rpartition(":")
            if security.endswith((".SH", ".SZ", ".BJ")):
                label = f"{reason}:{evidence_date}" if evidence_date else reason
                missing.add((row["date"].isoformat(), security, label))
            else:
                missing.add((row["date"].isoformat(), None, issue))
        blocker = row.get("blocking_holdings_date")
        if blocker and str(blocker) != row["date"].isoformat():
            for issue in row.get("blocking_holdings_issues", ()):
                reason, _, security = issue.partition(":")
                missing.add((row["date"].isoformat(), security or None, f"{reason}:{blocker}"))
    return [{"date": day, "reason": reason, **({"security": security} if security else {})}
            for day, security, reason in sorted(missing, key=lambda item: (item[0], item[1] or "", item[2]))]


class TradingPnlCalculation:
    def __init__(self, backfill: TradingPnlBackfill) -> None:
        self.backfill = backfill
        self.store = backfill.store
        self.source = backfill.source
        self.queries = backfill.queries

    def status(self, batch_id: str) -> dict:
        with self.store() as repo:
            run = repo.calculation(batch_id)
            if not run or run["result"] is None:
                raise PnlCommandError("该批次尚未开始计算", 404)
            result = run["result"]
            state = repo.state()
            if result["status"] == "running" and not run["active"]:
                return _result("retry", run["start_date"], run["horizon"], state["revision"])
            if result["status"] in {"complete", "partial"} and result["revision"] != state["revision"] and result["end"]:
                end = date.fromisoformat(result["end"])
                days = self.queries.range_summary(repo, state, run["start_date"], end)
                tail = [item for item in result["missing"] if item["date"] > result["end"]]
                missing = _issues(days, tail)
                return _result("partial" if missing else "complete", run["start_date"], end, state["revision"], missing)
            return result

    def run(self, batch_id: str) -> dict:
        cutoff = self.queries.settled_through()
        token = uuid4().hex
        with self.store(write=True) as repo:
            state = repo.state(lock=True)
            run = repo.calculation(batch_id)
            if not run:
                raise PnlCommandError("找不到有新增记录的入账批次", 404)
            if run["active"]:
                return run["result"]
            start = run["start_date"]
            revision = state["revision"]
            if start > cutoff:
                result = _result("waiting-settlement", start, None, revision)
                repo.finish_calculation(batch_id, result)
                return result
            repo.claim_calculation(batch_id, token, _result("running", start, None, revision))
        try:
            return self._calculate(batch_id, token, start, cutoff, revision)
        except PnlCommandError as exc:
            if exc.status != 409:
                raise
            with self.store(write=True) as repo:
                state = repo.state(lock=True)
                run = repo.calculation(batch_id)
                if run["token"] != token:
                    return run["result"]
                result = _result("retry", start, run["horizon"], state["revision"])
                repo.finish_calculation(batch_id, result)
                return result

    @staticmethod
    def _check(repo, batch_id: str, token: str, revision: int):
        state = repo.state(lock=True)
        run = repo.calculation(batch_id)
        if state["revision"] != revision or run["token"] != token or not run["active"]:
            raise PnlCommandError("台账或计算状态已更新，请重试", 409)
        return state

    def _calculate(self, batch_id: str, token: str, start: date, cutoff: date, revision: int) -> dict:
        with self.store() as repo:
            opening = repo.state()["opening_date"]
            evidence_start = replay_start(repo, start)
            if opening is None or evidence_start is None:
                raise PnlCommandError("请先确认期初", 409)
            local = self.backfill._local_calendar(repo, evidence_start, cutoff)
        calendar_error = "fuyao-calendar-coverage"
        remote = ()
        if _missing_sessions(local, evidence_start, cutoff, opening):
            try:
                remote = self.source.trading_days()
            except PnlMarketEvidenceError as exc:
                calendar_error = exc.reason
        with self.store(write=True) as repo:
            state = self._check(repo, batch_id, token, revision)
            if remote:
                sessions = _new_sessions(local, remote, evidence_start, cutoff, opening)
                for offset in range(0, len(sessions), 366):
                    batch = EvidenceBatch(sessions=sessions[offset:offset + 366])
                    revision = save_evidence(repo, batch, revision, "fuyao-calendar")
            local = self.backfill._local_calendar(repo, evidence_start, cutoff)
            calendar = LocalSessions(local)
            end = max((day for day in local if start <= day <= cutoff and calendar.resolution(day).sufficient
                       and local[day].is_session), default=None)
            unverified = [{"date": day.isoformat(), "reason": calendar_error}
                          for day in day_range(evidence_start, cutoff)
                          if (end is None or day > end) and not calendar.closed(day)
                          and not calendar.resolution(day).sufficient]
            if end is None:
                result = _result("partial" if unverified else "waiting-settlement", start, None, revision, unverified)
                repo.finish_calculation(batch_id, result)
                return result
            current = repo.calculation(batch_id)["horizon"]
            if current is None or end > current:
                repo.set_calculation_horizon(batch_id, end)
                revision += 1
                rebuild(repo, evidence_start, revision)
                repo.set_revision(revision)
            start_state = _result("running", start, end, revision)
            repo.claim_calculation(batch_id, token, start_state)
            action_dates = defaultdict(list)
            for day, security in sorted(missing_actions(repo, evidence_start, end)):
                action_dates[security].append(day)
            cached = {
                security: {day: repo.action_issue(day, security) for day in dates}
                for security, dates in action_dates.items()
                if repo.cached_action_window(security, dates[0], dates[-1])
            }
        actions, action_failures = self._fetch_actions(action_dates, cached)
        with self.store(write=True) as repo:
            self._check(repo, batch_id, token, revision)
            for window in actions:
                repo.save_action_events(window)
            missing_prices = self.queries.missing_prices(repo, evidence_start, end, include_unverified=False)
        pending, price_failures = self.backfill._fetch_prices(missing_prices)
        with self.store(write=True) as repo:
            state = self._check(repo, batch_id, token, revision)
            if pending:
                revision = save_evidence(repo, EvidenceBatch(valuations=pending), revision, "fuyao-closes")
            days = self.queries.range_summary(repo, state, start, end)
            remaining_prices = self.queries.missing_prices(repo, evidence_start, end, include_unverified=False)
            missing = _issues(days, [*unverified, *action_failures, *(
                {"date": day.isoformat(), "security": security,
                 "reason": price_failures.get((day, security), "fuyao-close-missing")}
                for day, security in remaining_prices
            )])
            result = _result("partial" if missing else "complete", start, end, revision, missing)
            repo.finish_calculation(batch_id, result)
            return result

    def _fetch_actions(self, dates_by_security, cached):
        actions = []
        missing = []
        deadline = monotonic() + HISTORY_PHASE_SECONDS
        for security, dates in dates_by_security.items():
            if security in cached:
                missing.extend({"date": day.isoformat(), "security": security,
                                "reason": cached[security][day] or "fuyao-action-coverage-unknown"} for day in dates)
                continue
            window = None
            reason = "fuyao-actions-batch-limit"
            if monotonic() < deadline:
                try:
                    window = self.source.corporate_actions(security, dates[0], dates[-1])
                except PnlMarketEvidenceError as exc:
                    reason = exc.reason
            if window is not None:
                actions.append(window)
            missing.extend({"date": day.isoformat(), "security": security,
                            "reason": window.missing_reason(day) if window else reason} for day in dates)
        return actions, missing
