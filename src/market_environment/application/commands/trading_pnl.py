"""Explicit writes for screenshot drafts, confirmed trades and coverage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, timedelta
from uuid import uuid4

from pydantic import ValidationError

from ...domain.models.trading_pnl import EvidenceBatch, Opening, Trade
from ..ports.trading_pnl import RecognizedScreenshot, TradingPnlRepository, TradingPnlStore
from ..queries.trading_pnl import LocalSessions, day_range
from .trading_pnl_projection import rebuild


class PnlCommandError(ValueError):
    def __init__(self, message: str, status: int = 422, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = message if detail is None else {"message": message, **detail}


def save_evidence(repo: TradingPnlRepository, batch: EvidenceBatch, revision: int, kind: str) -> int:
    revision += 1
    first_day = min(row.date for row in (*batch.sessions, *batch.valuations))
    repo.import_evidence(batch)
    rebuild(repo, first_day, revision)
    repo.audit(revision, {"kind": kind, **batch.model_dump(mode="json")})
    repo.set_revision(revision)
    return revision


def _strong_identity(trade: Trade) -> str | None:
    if trade.trade_id:
        return f"trade:{trade.date}:{trade.security}:{trade.trade_id}"
    if trade.event_id:
        return f"event:{trade.date}:{trade.security}:{trade.event_id}"
    return None


def _possible_duplicate(trade: Trade, known: Trade) -> bool:
    if trade.trade_id and known.trade_id and trade.trade_id != known.trade_id:
        return False
    if trade.event_id and known.event_id and trade.event_id != known.event_id:
        return False
    if trade.time is not None and known.time is not None and trade.time != known.time:
        return False
    if trade.order_id and known.order_id and trade.order_id != known.order_id:
        return False
    return all(getattr(trade, field) == getattr(known, field) for field in (
        "date", "security", "side", "status", "filled_quantity", "price", "amount",
    ))


class TradingPnlCommands:
    def __init__(self, store: TradingPnlStore, today: Callable[[], date],
                 recognize: Callable[[bytes], RecognizedScreenshot], digest: Callable[[bytes], str]) -> None:
        self.store = store
        self.today = today
        self.recognize = recognize
        self.digest = digest

    def upload(self, files: list[bytes]) -> dict:
        inputs = {self.digest(raw): raw for raw in files}
        with self.store() as repo:
            missing = [raw for key, raw in inputs.items() if repo.cached_image(key) is None]
        recognized = [self.recognize(raw) for raw in missing]
        with self.store(write=True) as repo:
            repo.state(lock=True)
            repo.cleanup_images()
            for image in recognized:
                repo.put_image(image)
            if any(repo.cached_image(key) is None for key in inputs):
                raise PnlCommandError("草稿已到期，请重新上传截图", 409)
            identifier = repo.put_draft(uuid4().hex, sorted(inputs))
            return self._draft(repo, identifier, [])

    def cleanup_previews(self) -> None:
        with self.store(write=True) as repo:
            repo.state(lock=True)
            repo.cleanup_images()

    def preview(self, identifier: str, edits: list[dict]) -> dict:
        with self.store() as repo:
            return self._draft(repo, identifier, edits)

    def preview_image(self, identifier: str, digest: str) -> bytes:
        with self.store() as repo:
            draft = repo.draft(identifier)
            if not draft or digest not in draft["images"]:
                raise PnlCommandError("截图草稿不存在或已到期", 404)
            image = repo.cached_image(digest)
            if image is None:
                raise PnlCommandError("截图已到期", 404)
            return bytes(image["preview"])

    @staticmethod
    def _check_trade(raw: dict) -> tuple[Trade | None, list[str]]:
        try:
            return Trade.model_validate(raw), []
        except ValidationError as exc:
            return None, [f'{".".join(map(str, item["loc"])) or "记录"} · {item["msg"].removeprefix("Value error, ")}'
                          for item in exc.errors(include_url=False, include_input=False)]

    @staticmethod
    def _matches(repo: TradingPnlRepository, digest: str, number: int, trade: Trade | None) -> tuple[list[dict], bool]:
        exact = repo.from_image(digest, number)
        if exact is not None:
            return [{"kind": "same-image", "id": exact["id"], "fields": exact["data"]}], True
        if trade is None:
            return [], False
        identity = _strong_identity(trade)
        known = repo.strong_match(identity) if identity else None
        if known is not None:
            kind = "same-id" if Trade.model_validate(known["data"]) == trade else "id-conflict"
            return [{"kind": kind, "id": known["id"], "fields": known["data"]}], True
        matches = [
            {"kind": "possible", "id": candidate["id"], "fields": candidate["data"]}
            for candidate in repo.candidates(trade) if _possible_duplicate(trade, Trade.model_validate(candidate["data"]))
        ]
        return matches, False

    def _draft(self, repo: TradingPnlRepository, identifier: str, edits: list[dict]) -> dict:
        draft = repo.draft(identifier)
        if draft is None:
            raise PnlCommandError("导入草稿不存在、已提交或已到期", 404)
        changes = {(entry["digest"], entry["row_number"]): entry["fields"] for entry in edits}
        if len(changes) != len(edits):
            raise PnlCommandError("同一行出现多次")
        images = []
        previous: list[tuple[str, int, Trade]] = []
        state = repo.state()
        for digest in draft["images"]:
            image = repo.cached_image(digest)
            if image is None:
                raise PnlCommandError("截图草稿已到期，请重新上传", 404)
            rows = []
            for number, entry in enumerate(image["rows"]):
                values = changes.pop((digest, number), entry["fields"])
                trade, issues = self._check_trade(values)
                if trade is not None and (trade.date > self.today() or (state["opening_date"] and trade.date <= state["opening_date"])):
                    issues.append("交易日超出当前台账区间")
                matches, blocked = self._matches(repo, digest, number, trade)
                if trade is not None and not blocked:
                    for other_digest, other_number, other in previous:
                        same_id = _strong_identity(trade) and _strong_identity(trade) == _strong_identity(other)
                        if same_id or _possible_duplicate(trade, other):
                            matches.append({"kind": "batch-id" if same_id else "batch-possible", "digest": other_digest,
                                            "row_number": other_number, "fields": other.model_dump(mode="json")})
                    previous.append((digest, number, trade))
                rows.append({**entry, "fields": values, "digest": digest, "row_number": number,
                             "issues": issues, "matches": matches, "blocked": blocked})
            images.append({"digest": digest, "hints": image["hints"], "rows": rows})
        if changes:
            raise PnlCommandError("提交包含草稿之外的记录")
        return {"id": identifier, "revision": state["revision"], "images": images}

    def confirm(self, identifier: str, key: str, revision: int, entries: list[dict]) -> dict:
        fingerprint = hashlib.sha256(json.dumps([identifier, revision, entries], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.store(write=True) as repo:
            state = repo.state(lock=True)
            if existing := repo.operation(key):
                if existing["kind"] != "confirm" or existing["input_hash"] != fingerprint:
                    raise PnlCommandError("确认操作键已用于其他内容", 409)
                return existing["result"]
            if state["opening_date"] is None:
                raise PnlCommandError("请先确认台账期初", 409)
            if state["revision"] != revision:
                raise PnlCommandError("台账已更新，请重新核对截图及重复记录", 409)
            view = self._draft(repo, identifier, entries)
            row_by_key = {(row["digest"], row["row_number"]): row for image in view["images"] for row in image["rows"]}
            revision += 1
            saved = []
            skipped = []
            affected: set[date] = set()
            accepted: list[Trade] = []
            audit_decisions = []
            for entry in sorted(entries, key=lambda row: (row["digest"], row["row_number"])):
                digest, number, decision = entry["digest"], entry["row_number"], entry["decision"]
                row = row_by_key[digest, number]
                action = {"image_hash": digest, "row_number": number, "decision": decision}
                if decision == "skip":
                    skipped.append(action)
                    audit_decisions.append(action)
                    continue
                trade, _ = self._check_trade(row["fields"])
                if not trade or row["issues"]:
                    raise PnlCommandError("请先修正待核记录")
                matches, blocked = self._matches(repo, digest, number, trade)
                if blocked:
                    raise PnlCommandError("发现已入账行或编号冲突，请重新核对", 409)
                # Other selected rows may match after being added in this transaction.
                if (matches or any(_possible_duplicate(trade, known) for known in accepted)) and decision != "keep-distinct":
                    raise PnlCommandError("请逐条处理疑似重复后再提交", 409)
                calendar = LocalSessions(repo.sessions(trade.date - timedelta(days=32), trade.date + timedelta(days=32)))
                if calendar.closed(trade.date):
                    raise PnlCommandError("休市日期不能登记交易，请核对截图日期")
                new_id = repo.put_trade(trade, digest, number, _strong_identity(trade), revision)
                accepted.append(trade)
                affected.add(trade.date)
                saved.append({"id": new_id, "date": trade.date.isoformat()})
                audit_decisions.append({**action, "trade_id": new_id, "fields": trade.model_dump(mode="json")})
            if affected:
                repo.clear_coverage(affected)
                rebuild(repo, min(affected), revision)
                repo.set_revision(revision)
            else:
                revision = state["revision"]
            batch_id = identifier if affected else None
            if batch_id:
                repo.record_calculation_batch(batch_id, min(affected))
            imported = [
                {"id": row["id"], "date": row["date"], "security": trade.security,
                 "name": trade.name, "side": trade.side, "quantity": trade.filled_quantity,
                 "price": str(trade.price) if trade.price is not None else None}
                for row, trade in zip(saved, accepted, strict=True)
            ]
            result = {"saved": saved, "skipped": skipped, "revision": revision,
                      "batch_id": batch_id, "imported": imported}
            repo.audit(revision, {"kind": "confirm", "draft_id": identifier, "batch_id": batch_id,
                                  "decisions": audit_decisions})
            repo.record_operation(key, "confirm", fingerprint, result)
            repo.finish_draft(identifier)
            return result

    def opening(self, opening: Opening) -> dict:
        if opening.date >= self.today() or opening.date.weekday() >= 5:
            raise PnlCommandError("期初应为已结束的交易日")
        with self.store(write=True) as repo:
            state = repo.state(lock=True)
            if state["opening_date"] == opening.date and state["opening_positions"] == opening.positions:
                return {"revision": state["revision"]}
            if repo.last_covered_date() is not None:
                raise PnlCommandError("已有交易或覆盖确认，期初需先核对现有台账", 409)
            revision = state["revision"] + 1
            repo.set_opening(opening)
            repo.audit(revision, {"kind": "opening", "opening": opening.model_dump(mode="json")})
            repo.set_revision(revision)
            return {"revision": revision}

    def cover(self, start: date, end: date, kind: str, expected: int) -> dict:
        if end < start or (end - start).days > 365 or end > self.today():
            raise PnlCommandError("确认范围应在已发生的 366 个自然日以内")
        with self.store(write=True) as repo:
            state = repo.state(lock=True)
            if state["revision"] != expected:
                raise PnlCommandError("台账已更新，请检查后重新确认覆盖", 409)
            if state["opening_date"] is None or start <= state["opening_date"]:
                raise PnlCommandError("请先确认期初，覆盖范围应在期初之后")
            calendar = LocalSessions(repo.sessions(start - timedelta(days=32), end + timedelta(days=32)))
            days = [day for day in day_range(start, end) if not calendar.closed(day)]
            if not days:
                raise PnlCommandError("选定范围没有可确认的交易日")
            if kind == "no-trades" and any(row["data"]["filled_quantity"] for row in repo.trades(start, end)):
                raise PnlCommandError("范围内已有成交，请使用完整流水确认")
            revision = state["revision"] + 1
            repo.put_coverage(days, kind)
            rebuild(repo, min(days), revision)
            repo.audit(revision, {"kind": kind, "start": start.isoformat(), "end": end.isoformat()})
            repo.set_revision(revision)
            return {"revision": revision, "confirmed_days": len(days)}

    def correct(self, identifier: int, trade: Trade, expected: int, keep_distinct: bool) -> dict:
        with self.store(write=True) as repo:
            state = repo.state(lock=True)
            original = repo.trade(identifier)
            if original is None:
                raise PnlCommandError("未找到该交易记录", 404)
            if original["revision"] != expected:
                raise PnlCommandError("记录已更新，请刷新后重新核对", 409)
            if not state["opening_date"] or not state["opening_date"] < trade.date <= self.today():
                raise PnlCommandError("交易日超出当前台账区间")
            calendar = LocalSessions(repo.sessions(trade.date - timedelta(days=32), trade.date + timedelta(days=32)))
            if calendar.closed(trade.date):
                raise PnlCommandError("休市日期不能登记交易")
            identity = _strong_identity(trade)
            if identity and (existing := repo.strong_match(identity)) and existing["id"] != identifier:
                raise PnlCommandError("已存在相同交易编号", 409)
            if not keep_distinct and any(_possible_duplicate(trade, Trade.model_validate(row["data"]))
                                         for row in repo.candidates(trade) if row["id"] != identifier):
                raise PnlCommandError("发现相似记录，请确认它们是两笔独立交易", 409)
            revision = state["revision"] + 1
            affected = {trade.date, date.fromisoformat(original["data"]["date"])}
            repo.correct_trade(identifier, trade, identity, revision)
            repo.clear_coverage(affected)
            rebuild(repo, min(affected), revision)
            repo.audit(revision, {"kind": "correct", "id": identifier, "before": original["data"], "after": trade.model_dump(mode="json")})
            repo.set_revision(revision)
            return {"revision": revision, "affected_dates": [day.isoformat() for day in sorted(affected)]}

    def import_evidence(self, batch: EvidenceBatch) -> dict:
        days = [record.date for record in [*batch.sessions, *batch.valuations]]
        if max(days) > self.today():
            raise PnlCommandError("证据日期不能晚于今天")
        with self.store(write=True) as repo:
            state = repo.state(lock=True)
            return {"revision": save_evidence(repo, batch, state["revision"], "evidence")}
