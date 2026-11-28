"""PostgreSQL storage for the personal trading ledger."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

from sqlalchemy import Connection, text
from sqlalchemy.exc import ProgrammingError

from ....domain.models.trading_pnl import LedgerUnavailable, Opening, Trade, ValuationEvidence
from .repositories import PostgresTradingSessionRepository


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def trading_pnl_store(engine):
    @contextmanager
    def store(*, write: bool = False):
        try:
            with engine.connect() as connection:
                if not write:
                    connection = connection.execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True)
                with connection.begin():
                    yield PostgresTradingPnl(connection)
        except ProgrammingError as exc:
            if getattr(exc.orig, "sqlstate", None) == "42P01" and "trading_pnl_" in str(exc.orig):
                raise LedgerUnavailable("请先为个人台账运行数据库迁移") from exc
            raise
    return store


class PostgresTradingPnl:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def _one(self, query: str, **values):
        return self.connection.execute(text(query), values).mappings().first()

    def _all(self, query: str, **values):
        return self.connection.execute(text(query), values).mappings().all()

    def _write(self, query: str, **values):
        return self.connection.execute(text(query), values)

    def state(self, *, lock: bool = False):
        suffix = " FOR UPDATE" if lock else ""
        return self._one(f"SELECT revision, opening_date, opening_positions FROM trading_pnl_state WHERE singleton{suffix}")

    def set_opening(self, opening: Opening) -> None:
        self._write("""UPDATE trading_pnl_state SET opening_date=:day,
                    opening_positions=CAST(:positions AS jsonb) WHERE singleton""",
                    day=opening.date, positions=_json(opening.positions))

    def set_revision(self, revision: int) -> None:
        self._write("UPDATE trading_pnl_state SET revision=:revision WHERE singleton", revision=revision)

    def operation(self, key: str):
        return self._one("SELECT kind, input_hash, result FROM trading_pnl_operations WHERE id=:key", key=key)

    def record_operation(self, key: str, kind: str, fingerprint: str, result: dict) -> None:
        self._write("""INSERT INTO trading_pnl_operations(id, kind, input_hash, result)
                    VALUES (:key, :kind, :fingerprint, CAST(:result AS jsonb))""",
                    key=key, kind=kind, fingerprint=fingerprint, result=_json(result))

    def audit(self, revision: int, data: dict) -> None:
        self._write("INSERT INTO trading_pnl_audit(revision, data) VALUES (:revision, CAST(:data AS jsonb))",
                    revision=revision, data=_json(data))

    def cached_image(self, digest: str):
        return self._one("""SELECT digest, preview, rows, hints FROM trading_pnl_images
                         WHERE digest=:digest AND preview IS NOT NULL AND expires_at > CURRENT_TIMESTAMP""", digest=digest)

    def put_image(self, image) -> None:
        self._write("""INSERT INTO trading_pnl_images(digest, preview, rows, hints, expires_at)
                    VALUES (:digest, :preview, CAST(:rows AS jsonb), CAST(:hints AS jsonb), CURRENT_TIMESTAMP + interval '1 day')
                    ON CONFLICT(digest) DO UPDATE SET preview=EXCLUDED.preview, rows=EXCLUDED.rows,
                    hints=EXCLUDED.hints, expires_at=EXCLUDED.expires_at
                    WHERE trading_pnl_images.preview IS NULL OR trading_pnl_images.expires_at <= CURRENT_TIMESTAMP""",
                    digest=image.digest, preview=image.image, rows=_json(image.rows), hints=_json(image.hints))

    def put_draft(self, identifier: str, images: list[str]) -> str:
        self._write("""UPDATE trading_pnl_images SET expires_at=CURRENT_TIMESTAMP + interval '1 day'
                    WHERE digest=ANY(:images)""", images=images)
        existing = self._one("""SELECT id FROM trading_pnl_drafts WHERE images=CAST(:images AS jsonb)
                             AND NOT finished AND expires_at > CURRENT_TIMESTAMP LIMIT 1""", images=_json(images))
        if existing:
            return existing["id"]
        self._write("""INSERT INTO trading_pnl_drafts(id, images, expires_at)
                    VALUES (:id, CAST(:images AS jsonb), CURRENT_TIMESTAMP + interval '1 day')""",
                    id=identifier, images=_json(images))
        return identifier

    def draft(self, identifier: str):
        return self._one("""SELECT id, images FROM trading_pnl_drafts WHERE id=:id
                         AND NOT finished AND expires_at > CURRENT_TIMESTAMP""", id=identifier)

    def finish_draft(self, identifier: str) -> None:
        self._write("UPDATE trading_pnl_drafts SET finished=TRUE WHERE id=:id", id=identifier)
        self.cleanup_images()

    def cleanup_images(self) -> None:
        self._write("""UPDATE trading_pnl_images AS image SET preview=NULL, rows=NULL, hints=NULL
                    WHERE preview IS NOT NULL AND (expires_at <= CURRENT_TIMESTAMP OR NOT EXISTS (
                        SELECT 1 FROM trading_pnl_drafts AS draft
                        WHERE NOT draft.finished AND draft.expires_at > CURRENT_TIMESTAMP
                        AND draft.images @> jsonb_build_array(image.digest)))""")

    def from_image(self, digest: str, number: int):
        return self._one("SELECT id, data FROM trading_pnl_trades WHERE digest=:digest AND row_number=:n", digest=digest, n=number)

    def strong_match(self, strong_id: str):
        return self._one("SELECT id, data FROM trading_pnl_trades WHERE strong_id=:identity", identity=strong_id)

    def candidates(self, trade: Trade):
        return self._all("""SELECT id, data FROM trading_pnl_trades
                         WHERE trade_date=:day AND security=:security AND side=:side
                         AND data->>'status'=:status AND CAST(data->>'filled_quantity' AS integer)=:quantity
                         AND CAST(data->>'price' AS numeric) IS NOT DISTINCT FROM CAST(:price AS numeric)
                         AND CAST(data->>'amount' AS numeric) IS NOT DISTINCT FROM CAST(:amount AS numeric)
                         AND (CAST(:trade_id AS text) IS NULL OR data->>'trade_id' IS NULL OR data->>'trade_id'=:trade_id)
                         AND (CAST(:event_id AS text) IS NULL OR data->>'event_id' IS NULL OR data->>'event_id'=:event_id)
                         AND (CAST(:order_id AS text) IS NULL OR data->>'order_id' IS NULL OR data->>'order_id'=:order_id)
                         AND (CAST(:time AS time) IS NULL OR data->>'time' IS NULL OR CAST(data->>'time' AS time)=:time)
                         ORDER BY id LIMIT 50""",
                         day=trade.date, security=trade.security, side=trade.side, status=trade.status,
                         quantity=trade.filled_quantity, price=trade.price, amount=trade.amount, trade_id=trade.trade_id,
                         event_id=trade.event_id, order_id=trade.order_id, time=trade.time)

    def put_trade(self, trade: Trade, digest: str, number: int, strong_id: str | None, revision: int) -> int:
        return self._write("""INSERT INTO trading_pnl_trades(trade_date, security, side, data, digest, row_number, strong_id, revision)
                           VALUES (:day, :security, :side, CAST(:data AS jsonb), :digest, :number, :identity, :revision)
                           RETURNING id""", day=trade.date, security=trade.security, side=trade.side,
                           data=trade.model_dump_json(), digest=digest, number=number, identity=strong_id,
                           revision=revision).scalar_one()

    def trade(self, identifier: int):
        return self._one("SELECT id, data, revision FROM trading_pnl_trades WHERE id=:id", id=identifier)

    def correct_trade(self, identifier: int, trade: Trade, strong_id: str | None, revision: int) -> None:
        self._write("""UPDATE trading_pnl_trades SET trade_date=:day, security=:security, side=:side,
                    data=CAST(:data AS jsonb), strong_id=:identity, revision=:revision WHERE id=:id""",
                    id=identifier, day=trade.date, security=trade.security, side=trade.side,
                    data=trade.model_dump_json(), identity=strong_id, revision=revision)

    def trades(self, start: date, end: date, limit: int | None = None, after: int = 0):
        return self._all("""SELECT id, data, revision, digest, row_number FROM trading_pnl_trades
                         WHERE trade_date BETWEEN :start AND :end AND id > :after
                         ORDER BY trade_date, id LIMIT :limit""",
                         start=start, end=end, after=after, limit=limit)

    def coverage(self, start: date, end: date) -> dict[date, str]:
        return {row["as_of"]: row["kind"] for row in self._all(
            "SELECT as_of, kind FROM trading_pnl_coverage WHERE as_of BETWEEN :start AND :end", start=start, end=end)}

    def put_coverage(self, days: list[date], kind: str) -> None:
        self._write("""INSERT INTO trading_pnl_coverage(as_of, kind) SELECT unnest(CAST(:days AS date[])), :kind
                    ON CONFLICT(as_of) DO UPDATE SET kind=EXCLUDED.kind""", days=days, kind=kind)

    def clear_coverage(self, days: set[date]) -> None:
        self._write("DELETE FROM trading_pnl_coverage WHERE as_of=ANY(:days)", days=sorted(days))

    def sessions(self, start: date, end: date):
        existing = PostgresTradingSessionRepository(self.connection).list_between(start, end)
        days = {session.as_of: session for session in existing}
        imported = self._all("SELECT * FROM trading_pnl_sessions WHERE as_of BETWEEN :start AND :end", start=start, end=end)
        for row in imported:
            current = days.get(row["as_of"])
            if current is None or current.actual_as_of is None or (current.is_session and current.previous_as_of is None):
                days[row["as_of"]] = SimpleNamespace(**row)
        return days

    def import_evidence(self, batch) -> None:
        for session in batch.sessions:
            self._write("""INSERT INTO trading_pnl_sessions(as_of, actual_as_of, previous_as_of, is_session, source)
                        VALUES (:day, :actual, :previous, :session, :source) ON CONFLICT(as_of) DO UPDATE
                        SET previous_as_of=EXCLUDED.previous_as_of, is_session=EXCLUDED.is_session, source=EXCLUDED.source""",
                        day=session.date, actual=session.actual_date, previous=session.previous_date,
                        session=session.is_session, source=session.source)
        for value in batch.valuations:
            stored = self._one("SELECT data FROM trading_pnl_valuations WHERE as_of=:day AND security=:security",
                               day=value.date, security=value.security)
            previous = ValuationEvidence.model_validate(stored["data"]) if stored else value
            price = value if value.close is not None else previous
            action = value if value.actions_confirmed else previous
            merged = value.model_copy(update={
                "close": price.close, "price_kind": price.price_kind,
                "price_source": (price.price_source or price.source) if price.close is not None else None,
                "actions_confirmed": action.actions_confirmed, "share_delta": action.share_delta,
                "cash_adjustment": action.cash_adjustment,
                "action_source": (action.action_source or action.source) if action.actions_confirmed else None,
            })
            self._write("""INSERT INTO trading_pnl_valuations(as_of, security, data)
                        VALUES (:day, :security, CAST(:data AS jsonb)) ON CONFLICT(as_of, security) DO UPDATE SET data=EXCLUDED.data""",
                        day=value.date, security=value.security, data=merged.model_dump_json())

    def valuations(self, start: date, end: date) -> dict[tuple[date, str], ValuationEvidence]:
        rows = self._all("SELECT data FROM trading_pnl_valuations WHERE as_of BETWEEN :start AND :end", start=start, end=end)
        values = [ValuationEvidence.model_validate(row["data"]) for row in rows]
        return {(value.date, value.security): value for value in values}

    def original_closes(self, start: date, end: date, securities: list[str]):
        return self._all("""SELECT as_of, security_id, original_close, source, source_revision, checksum
                         FROM sector_security_daily_facts
                         WHERE as_of BETWEEN :start AND :end AND security_id=ANY(:securities)
                         AND requested_as_of=as_of AND actual_as_of=as_of AND original_close > 0
                         AND quality_status IN ('ok', 'partial', 'degraded', 'fallback-derived')
                         ORDER BY as_of, security_id, fetched_at DESC NULLS LAST, source_revision, checksum""",
                         start=start, end=end, securities=securities)

    def last_covered_date(self) -> date | None:
        return self._one("""SELECT greatest((SELECT max(as_of) FROM trading_pnl_coverage),
                    (SELECT max(trade_date) FROM trading_pnl_trades)) AS date""")["date"]

    def days(self, start: date, end: date):
        return self._all("SELECT as_of, revision, data FROM trading_pnl_days WHERE as_of BETWEEN :start AND :end ORDER BY as_of",
                         start=start, end=end)

    def first_coverage_gap(self, before: date) -> date | None:
        return self._one("""SELECT min(as_of) AS day FROM trading_pnl_days WHERE as_of < :before
                            AND (data->'issues') @> '["coverage-unconfirmed"]'::jsonb""", before=before)["day"]

    def latest_day(self, before: date):
        return self._one("SELECT as_of, data FROM trading_pnl_days WHERE as_of < :before ORDER BY as_of DESC LIMIT 1",
                         before=before)

    def reset_days(self, start: date) -> None:
        self._write("DELETE FROM trading_pnl_days WHERE as_of >= :start", start=start)

    def put_day(self, day: date, revision: int, data: dict) -> None:
        self._write("INSERT INTO trading_pnl_days(as_of, revision, data) VALUES (:day, :revision, CAST(:data AS jsonb))",
                    day=day, revision=revision, data=_json(data))
