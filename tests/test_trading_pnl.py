from __future__ import annotations

import io
import os
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError

from src.market_environment.application.queries.trading_pnl import LocalSessions, TradingPnlQueries
from src.market_environment.application.commands.trading_pnl import TradingPnlCommands
from src.market_environment.application.commands.trading_pnl_backfill import TradingPnlBackfill
from src.market_environment.application.ports.trading_pnl import PnlHistory, PnlMarketEvidenceError
from src.market_environment.domain.analysis.trading_pnl import aggregate_executions, project_holdings, simulated_commission
from src.market_environment.domain.models.trading_pnl import EvidenceBatch, Trade, ValuationEvidence
from src.market_environment.infrastructure.persistence.postgres.trading_pnl import trading_pnl_store
from src.market_environment.infrastructure.providers.fuyao.limits_client import FuyaoClient
from src.market_environment.infrastructure.providers.fuyao.market import FuyaoMarketClient
from src.market_environment.infrastructure.providers.fuyao.trading_pnl import FuyaoPnlMarketEvidence
from src.market_environment.infrastructure.trading_pnl_ocr import Screenshot, ScreenshotError, ScreenshotRecognizer, Word, image_digest, parse_trade_rows
from src.market_environment.interfaces.http.routers.trading_pnl import router
from src.market_environment.postgres_schema import create_schema


PREVIOUS = date(2026, 1, 20)
DAY = date(2026, 1, 21)
CODE = "603019.SH"
SYNTHETIC_LABELS = (
    (26, 25, "今日盈亏"), (26, 80, "2026年03月"), (760, 80, "5笔"),
    (26, 140, "2026年02月"), (760, 140, "2笔"), (26, 200, "2026年01月"),
    (26, 285, "模拟买入"), (250, 285, "样本股票"), (560, 285, "100股"), (715, 285, "9,815.00"),
    (26, 330, "01-21"), (250, 330, CODE), (560, 330, "98.15"), (730, 330, "全部成交"),
    (26, 410, "模拟买入"), (250, 410, "样本股票"), (560, 410, "100股"), (715, 410, "9,796.00"),
    (26, 455, "01-21"), (250, 455, CODE), (560, 455, "97.96"), (730, 455, "全部成交"),
    (26, 535, "模拟卖出"), (250, 535, "样本股票"), (555, 535, "40/100股"), (715, 535, "4,000.00"),
    (26, 580, "01-22"), (250, 580, CODE), (560, 580, "100.00"), (730, 580, "部分成交"),
    (26, 660, "模拟卖出"), (250, 660, "样本股票"), (560, 660, "100股"),
    (26, 705, "01-22"), (250, 705, CODE), (730, 705, "已撤单"),
)


def trade(**changes):
    fields = dict(date=DAY, security=CODE, side="buy", status="filled", filled_quantity=100, price="98.15", amount="9815.00")
    return Trade.model_validate({**fields, **changes})


def synthetic_image() -> bytes:
    font_path = Path(os.environ.get("TRADING_PNL_TEST_FONT", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"))
    if not font_path.exists():
        pytest.skip("Chinese font for the synthetic OCR fixture is not installed")
    image = Image.new("RGB", (920, 770), "white")
    canvas = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 31)
    for x, y, label in SYNTHETIC_LABELS:
        canvas.text((x, y), label, font=font, fill="#222222")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_calendar_and_prices_require_exact_date_evidence():
    calendar = LocalSessions({
        PREVIOUS: SimpleNamespace(actual_as_of=PREVIOUS, previous_as_of=None, is_session=True),
        DAY: SimpleNamespace(actual_as_of=DAY, previous_as_of=PREVIOUS, is_session=True),
    })
    assert calendar.resolution(DAY).previous_as_of == PREVIOUS
    assert not LocalSessions({DAY: calendar.sessions[DAY]}).resolution(DAY).sufficient
    with pytest.raises(ValidationError):
        EvidenceBatch.model_validate({"sessions": [{"date": DAY, "is_session": True, "source": "fixture"}]})
    with pytest.raises(ValidationError):
        ValuationEvidence(date=DAY, actual_date=PREVIOUS, security=CODE, close=Decimal(100), price_kind="original-close", source="fixture")
    with pytest.raises(ValidationError):
        ValuationEvidence(date=DAY, actual_date=DAY, security=CODE, source="fixture")
    candidate = ValuationEvidence(date=DAY, actual_date=DAY, security=CODE, close=Decimal(100), price_kind="original-close", source="fixture")
    assert not candidate.actions_confirmed
    repo = SimpleNamespace(
        original_closes=lambda *_: [
            {"as_of": PREVIOUS, "security_id": CODE, "original_close": 99.0, "source": "previous", "source_revision": "one"},
            {"as_of": DAY, "security_id": "000001.SZ", "original_close": 88.0, "source": "wrong-security", "source_revision": "one"},
        ], valuations=lambda *_: {(DAY, CODE): candidate},
    )
    result = TradingPnlQueries._prices(repo, {DAY: {"opening": {}, "previous_date": PREVIOUS.isoformat(), "closing": {CODE: 100}}}, DAY, DAY)
    assert result == {(DAY, CODE): {"close": Decimal(100), "source": "fixture", "price_kind": "original-close"}}


def test_simulation_fees_split_fills_and_cancellation():
    first = trade()
    second = trade(price="97.96", amount="9796.00")
    executions, issues = aggregate_executions([first, second])
    assert issues == []
    assert sum(row.gross for row in executions) == Decimal("19611.00")
    assert sum(row.commission for row in executions) == Decimal("10.00")
    assert simulated_commission(Decimal(40000)) == Decimal("10.00")
    assert project_holdings({}, executions, {})[:2] == ({CODE: 200}, Decimal(0))
    partial = trade(filled_quantity=40, ordered_quantity=100, price="100.00", amount="4000.00",
                    status="partial", side="sell", order_id="order-a", cumulative=True)
    canceled = partial.model_copy(update={"status": "canceled", "commission": Decimal("3.75"), "other_fees": Decimal("2.00")})
    executions, issues = aggregate_executions([partial, canceled])
    assert not issues
    assert len(executions) == 1 and executions[0].quantity == 40
    assert executions[0].gross - executions[0].commission - executions[0].other_fees == Decimal("3994.25")
    separate = [trade(order_id="split", trade_id=str(index)) for index in range(2)]
    assert aggregate_executions(separate)[0][0].commission == Decimal("5.00")
    assert aggregate_executions([trade(fees_pending=True)])[0][0].fees_pending


def test_negative_holdings_and_selling_entire_position():
    action = ValuationEvidence(date=DAY, actual_date=DAY, security=CODE, actions_confirmed=True, source="no company actions")
    sell, _ = aggregate_executions([trade(side="sell")])
    assert project_holdings({CODE: 100}, sell, {CODE: action})[0] == {}
    assert project_holdings({CODE: 50}, sell, {CODE: action})[-1] == [f"negative-position:{CODE}"]
    assert project_holdings({CODE: 100}, sell, {})[-1] == [f"missing-actions:{CODE}"]
    calendar = LocalSessions({
        PREVIOUS: SimpleNamespace(actual_as_of=PREVIOUS, previous_as_of=None, is_session=True),
        DAY: SimpleNamespace(actual_as_of=DAY, previous_as_of=PREVIOUS, is_session=True),
    })
    result = TradingPnlQueries(None, lambda: date(2026, 11, 28))._value(
        DAY, {"opening_date": PREVIOUS}, calendar,
        {"opening": {CODE: 100}, "closing": {}, "previous_date": PREVIOUS.isoformat(), "executions": [],
         "actions": [], "issues": [], "buy_cost": "0", "sell_proceeds": "9810", "commission": "5",
         "other_fees": "0", "cash_adjustment": "0"},
        {(PREVIOUS, CODE): {"close": Decimal(98), "source": "fixture", "price_kind": "original-close"}},
    )
    assert result["pnl"] == "10.00" and not result["issues"]


def test_screenshot_rows_and_missing_context():
    words = [Word(x, y, 30, 31, value) for x, y, value in SYNTHETIC_LABELS]
    rows, hints = parse_trade_rows(words, 920, 770)
    assert len(rows) == 4 and len(hints) == 4
    assert Trade.model_validate(rows[0]["fields"]).amount == Decimal("9815.00")
    assert Trade.model_validate(rows[1]["fields"]).date == DAY
    assert rows[2]["fields"]["filled_quantity"] == 40
    assert rows[2]["fields"]["ordered_quantity"] == 100
    assert rows[3]["fields"]["filled_quantity"] is None
    unreadable = [word for word in words if word.text != "全部成交"]
    rows, _ = parse_trade_rows(unreadable, 920, 770, status_words=[Word(40, 330, 100, 31, "全部交成")])
    assert rows[0]["fields"]["status"] == "filled"
    assert rows[1]["fields"]["status"] == ""
    cropped, _ = parse_trade_rows(words[6:14], 920, 770)
    assert cropped[0]["fields"]["date"] == ""
    with pytest.raises(ValidationError):
        Trade.model_validate({**rows[0]["fields"], "amount": "9999.00"})
    with pytest.raises(ScreenshotError, match="无法解码"):
        ScreenshotRecognizer()(b"not a screenshot")


def test_real_local_ocr_on_synthetic_layout():
    executable = os.environ.get("TRADING_PNL_TEST_TESSERACT")
    if not executable:
        pytest.skip("set TRADING_PNL_TEST_TESSERACT to verify local Chinese OCR")
    parsed = ScreenshotRecognizer(executable)(synthetic_image())
    assert len(parsed.rows) == 4
    assert [row["fields"]["status"] for row in parsed.rows] == ["filled", "filled", "partial", "canceled"]
    assert Trade.model_validate(parsed.rows[0]["fields"]).amount == Decimal("9815.00")
    assert Trade.model_validate(parsed.rows[1]["fields"]).amount == Decimal("9796.00")


def test_ocr_limits_and_timeout(monkeypatch):
    import subprocess

    from src.market_environment.domain.models.trading_pnl import MAX_IMAGE_BYTES

    with pytest.raises(ScreenshotError, match="5 MB"):
        ScreenshotRecognizer()(b"x" * (MAX_IMAGE_BYTES + 1))
    with io.BytesIO() as image:
        Image.new("RGB", (7, 7), "white").save(image, format="PNG")
        raw = image.getvalue()

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("tesseract", 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ScreenshotError, match="识别超时"):
        ScreenshotRecognizer()(raw)


@pytest.fixture
def ledger_db():
    from importlib.util import module_from_spec, spec_from_file_location
    from uuid import uuid4

    url = os.environ.get("MARKET_ENVIRONMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires isolated MARKET_ENVIRONMENT_TEST_DATABASE_URL")
    schema = f"pnl_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        create_schema(engine)
        migration = Path(__file__).resolve().parents[1] / "alembic/versions/0009_trading_pnl.py"
        spec = spec_from_file_location("test_ledger_migration", migration)
        assert spec is not None and spec.loader is not None
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def fake_screenshot(blob: bytes) -> Screenshot:
    fields = trade().model_dump(mode="json")
    rows = [{"fields": fields, "raw": "识别草稿", "region": [0.1, 0.2]}]
    if blob == b"two-records":
        rows.append({"fields": trade(price="97.96", amount="9796.00").model_dump(mode="json"), "raw": "第二笔", "region": [0.3, 0.4]})
    return Screenshot(image_digest(blob), b"preview", "image/jpeg", rows, ["2026年01月2笔"])


def ledger_client(engine, recognizer=fake_screenshot, source=None):
    app = FastAPI()
    app.include_router(router)
    store = trading_pnl_store(engine)
    today = lambda: date(2026, 11, 28)
    queries = TradingPnlQueries(store, today, lambda: date(2026, 11, 27))
    app.state.container = SimpleNamespace(
        reads=SimpleNamespace(trading_pnl=queries),
        commands=SimpleNamespace(
            trading_pnl=TradingPnlCommands(store, today, recognizer, image_digest),
            trading_pnl_backfill=TradingPnlBackfill(store, queries, source) if source else None,
        ),
    )
    return TestClient(app)


def post(client, path, payload, status=200):
    response = client.post(f"/api/trading-pnl{path}", json=payload)
    assert response.status_code == status, response.text
    return response.json()


def get(client, path):
    response = client.get(f"/api/trading-pnl{path}")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def upload(client, blob):
    response = client.post("/api/trading-pnl/drafts", files=[("images", ("fixture.png", blob, "image/png"))])
    assert response.status_code == 200, response.text
    return response.json()


def confirmation(draft, key="confirmation_20260121", decision="add", count=None):
    rows = [row for image in draft["images"] for row in image["rows"]]
    return {"key": key, "revision": draft["revision"], "rows": [
        {"digest": row["digest"], "row_number": row["row_number"], "fields": row["fields"].copy(), "decision": decision}
        for row in rows[:count]
    ]}


def session(day, previous=None, is_session=True):
    return {"date": day, "actual_date": day, "previous_date": previous, "is_session": is_session, "source": "synthetic calendar"}


def valuation(day, close, shares=0, cash="0", kind="original-close"):
    return {"date": day, "actual_date": day, "security": CODE, "close": close,
            "price_kind": kind if close is not None else None, "actions_confirmed": True,
            "share_delta": shares, "cash_adjustment": cash, "source": "synthetic settlement"}


def set_up(client):
    post(client, "/opening", {"date": "2026-01-20", "positions": {}})
    post(client, "/evidence", {"sessions": [session("2026-01-20"), session("2026-01-21", "2026-01-20"),
        session("2026-01-22", "2026-01-21"), session("2026-01-23", "2026-01-22"),
        session("2026-01-26", is_session=False), session("2026-01-27", "2026-01-23")]})


def cover(client, day, revision, kind="complete", end=None):
    return post(client, "/coverage", {"start": day, "end": end or day, "revision": revision, "kind": kind})["revision"]


def test_http_import_value_and_rebuild_with_isolated_postgres(ledger_db):
    executable = os.environ.get("TRADING_PNL_TEST_TESSERACT")
    client = ledger_client(ledger_db, ScreenshotRecognizer(executable) if executable else fake_screenshot)
    set_up(client)
    blob = synthetic_image() if executable else b"two-records"
    draft = upload(client, blob)
    assert upload(client, blob)["id"] == draft["id"]
    assert get(client, "/days/2026-01-21")["trades"] == []
    image = draft["images"][0]
    assert client.get(f'/api/trading-pnl/drafts/{draft["id"]}/images/{image["digest"]}').status_code == 200
    payload = confirmation(draft, count=2)
    confirmed = post(client, f'/drafts/{draft["id"]}/confirm', payload)
    assert len(confirmed["saved"]) == 2
    assert post(client, f'/drafts/{draft["id"]}/confirm', payload) == confirmed
    assert client.get(f'/api/trading-pnl/drafts/{draft["id"]}/images/{image["digest"]}').status_code == 404
    repeat = upload(client, blob)
    assert all(row["blocked"] and row["matches"][0]["kind"] == "same-image" for row in repeat["images"][0]["rows"][:2])
    first = get(client, "/days/2026-01-21")
    assert first["pnl"] is None and len(first["trades"]) == 2
    cover(client, "2026-01-21", first["revision"])
    assert get(client, "/days/2026-01-21")["issues"] == [f"missing-close:2026-01-21:{CODE}"]
    revision = post(client, "/evidence", {"valuations": [valuation("2026-01-21", "100.00"), valuation("2026-01-22", "102.00"),
        valuation("2026-01-23", "52.00", shares=200, cash="10.00"), valuation("2026-01-27", "52.00", kind="suspended-valuation")]})["revision"]
    revision = cover(client, "2026-01-23", revision, "no-trades", end="2026-01-27")
    assert "prior-holdings-unconfirmed" in get(client, "/days/2026-01-23")["issues"]
    cover(client, "2026-01-22", revision, "no-trades")
    statements = []
    listener = lambda connection, cursor, sql, *args: statements.append(sql.lstrip().split()[0].upper())
    event.listen(ledger_db, "before_cursor_execute", listener)
    try:
        month = {item["date"]: item for item in get(client, "/months/2026-01")["days"]}
        first = get(client, "/days/2026-01-21?limit=1")
        second_page = get(client, f'/days/2026-01-21?limit=1&after={first["next_after"]}')
    finally:
        event.remove(ledger_db, "before_cursor_execute", listener)
    assert {"INSERT", "UPDATE", "DELETE", "CREATE"}.isdisjoint(statements)
    assert first["pnl"] == month["2026-01-21"]["pnl"] == "379.00"
    assert first["components"]["buy_cost"] == "19621.00"
    assert first["closing"][0]["quantity"] == 200
    assert len(first["trades"]) == len(second_page["trades"]) == 1
    assert month["2026-01-22"]["pnl"] == "400.00"
    assert month["2026-01-23"]["pnl"] == "410.00"
    assert month["2026-01-26"]["status"] == "closed"
    assert month["2026-01-27"]["pnl"] == "0.00"

    post(client, "/evidence", {"valuations": [{**valuation("2026-01-21", None), "source": "separate company action report"}]})
    assert get(client, "/days/2026-01-21")["closing"][0]["source"] == "synthetic settlement"

    record = first["trades"][0]
    corrected = trade(date="2026-01-22").model_dump(mode="json")
    correction = post(client, f'/trades/{record["id"]}/correction', {"revision": record["revision"], "trade": corrected})
    assert correction["affected_dates"] == ["2026-01-21", "2026-01-22"]
    revision = correction["revision"]
    assert get(client, "/days/2026-01-21")["coverage"] is None
    assert get(client, "/days/2026-01-22")["coverage"] is None
    cover(client, "2026-01-21", revision, end="2026-01-22")
    assert get(client, "/days/2026-01-21")["pnl"] == "199.00"
    assert get(client, "/days/2026-01-22")["pnl"] == "580.00"


class FixtureMarketEvidence:
    def __init__(self, days):
        self.days = tuple(date.fromisoformat(day) for day in days)
        self.prices = {}
        self.calls = []
        self.before_history = lambda: None

    def trading_days(self):
        self.calls.append(("calendar",))
        return self.days

    def closes(self, security, start, end):
        self.calls.append((security, start.isoformat(), end.isoformat()))
        self.before_history()
        return PnlHistory(tuple(ValuationEvidence(
            date=day, actual_date=day, security=security, close=price, price_kind="original-close", source="Fuyao fixture",
        ) for day, price in self.prices.items() if start <= day <= end))


def backfill(client, start, end=None, *, status=200, revision=None):
    if revision is None:
        revision = get(client, f"/days/{start}")["revision"]
    return post(client, "/evidence/fuyao", {"start": start, "end": end or start, "revision": revision}, status=status)


def test_official_fuyao_history_backfills_exact_close_and_keeps_daily_reasons(ledger_db):
    dates = [date(2026, 1, day) for day in (21, 22, 23, 26)]
    first, existing, conflicting, missing = dates
    shanghai = ZoneInfo("Asia/Shanghai")

    def timestamp(day):
        return int(datetime.combine(day, time(), shanghai).timestamp()) * 1000

    requests = []

    def history(url, *, params, **kwargs):
        requests.append((url, params))
        items = [
            {"date_ms": timestamp(first), "close_price": "98.23"},
            {"date_ms": timestamp(existing), "close_price": "1"},
            {"date_ms": timestamp(conflicting), "close_price": "200", "adjust": "forward"},
        ]
        payload = {"code": 0, "data": {"timestamp": timestamp(conflicting), "item": items}}
        return SimpleNamespace(status_code=200, json=lambda: payload)

    market = FuyaoPnlMarketEvidence(
        FuyaoClient("fixture", session=SimpleNamespace()),
        FuyaoMarketClient("fixture", session=SimpleNamespace(get=history), max_retries=0),
    )
    client = ledger_client(ledger_db, source=market)
    post(client, "/opening", {"date": PREVIOUS.isoformat(), "positions": {}})
    post(client, "/evidence", {
        "sessions": [session(PREVIOUS.isoformat(), "2026-01-19"), *(
            session(current.isoformat(), prior.isoformat()) for prior, current in zip([PREVIOUS, *dates[:-1]], dates)
        )],
        "valuations": [
            valuation(existing.isoformat(), "100"),
            valuation(conflicting.isoformat(), None),
            valuation(missing.isoformat(), None),
        ],
    })
    draft = upload(client, b"two-records")
    confirmed = post(client, f'/drafts/{draft["id"]}/confirm', confirmation(draft))
    cover(client, first.isoformat(), confirmed["revision"], end=missing.isoformat())
    before = get(client, f"/days/{first}")
    assert before["coverage"] == "complete"
    assert before["pnl"] is None
    assert not requests

    result = backfill(client, first.isoformat())
    assert result["status"] == "complete" and result["added"] == {"sessions": 0, "valuations": 1}
    detail = get(client, f"/days/{first}")
    month = get(client, "/months/2026-01")
    assert next(day for day in month["days"] if day["date"] == first.isoformat())["pnl"] == detail["pnl"] == "25.00"
    assert detail["trades"] == before["trades"] and detail["coverage"] == "complete"
    assert detail["closing"][0]["source"] == "Fuyao · 个股不复权日线"
    assert Decimal(get(client, f"/days/{existing}")["closing"][0]["close"]) == Decimal("100")
    repeated = backfill(client, first.isoformat())
    assert repeated["revision"] == result["revision"] and repeated["added"] == {"sessions": 0, "valuations": 0}
    assert requests == [("https://fuyao.aicubes.cn/api/a-share/prices/historical", {
        "thscode": CODE, "interval": "1d", "adjust": "none",
        "start": timestamp(first), "end": timestamp(existing) - 1,
    })]

    partial = backfill(client, first.isoformat(), missing.isoformat())
    assert partial["added"]["valuations"] == 0 and len(requests) == 2
    assert partial["missing_closes"] == [
        {"date": conflicting.isoformat(), "security": CODE, "reason": "fuyao-invalid-history"},
        {"date": missing.isoformat(), "security": CODE, "reason": "fuyao-close-missing"},
    ]
    assert get(client, f"/days/{existing}")["closing"][0]["source"] == "synthetic settlement"


def test_fuyao_backfill_persists_calendar_and_recovers_price_in_isolated_postgres(ledger_db):
    market = FixtureMarketEvidence(["2026-01-19", "2026-01-20", "2026-01-21", "2026-01-23", "2026-01-26"])
    client = ledger_client(ledger_db, source=market)
    post(client, "/opening", {"date": "2026-01-20", "positions": {}})
    draft = upload(client, b"two-records")
    confirmed = post(client, f'/drafts/{draft["id"]}/confirm', confirmation(draft))
    cover(client, "2026-01-21", confirmed["revision"])
    assert backfill(client, "2026-11-28", status=422)
    assert backfill(client, "2026-11-29", status=422)
    assert not market.calls
    def unavailable():
        with ledger_db.begin() as conn:
            conn.execute(text("SELECT revision FROM trading_pnl_state FOR UPDATE NOWAIT"))
        raise PnlMarketEvidenceError("fuyao-history-unavailable")
    market.before_history = unavailable
    first = backfill(client, "2026-01-21", "2026-01-22")
    assert first["status"] == "partial" and first["added"] == {"sessions": 3, "valuations": 0}
    assert first["missing_closes"] == [{"date": "2026-01-21", "security": CODE, "reason": "fuyao-history-unavailable"}]
    assert get(client, "/days/2026-01-22")["status"] == "closed"
    assert get(client, "/days/2026-01-21")["coverage"] == "complete"

    market.before_history = lambda: None
    market.prices[DAY] = "98.23"
    assert backfill(client, "2026-01-21", status=409, revision=confirmed["revision"])["detail"]["revision"] == first["revision"]
    second = backfill(client, "2026-01-21", "2026-01-22")
    assert second == {"revision": first["revision"] + 1, "status": "complete", "added": {"sessions": 0, "valuations": 1},
                      "remaining": [], "missing_closes": []}
    assert get(client, "/days/2026-01-21")["pnl"] == "25.00"
    assert get(client, "/days/2026-01-21")["closing"][0]["source"] == "Fuyao fixture"
    month = get(client, "/months/2026-01")
    assert next(day for day in month["days"] if day["date"] == "2026-01-21")["pnl"] == "25.00"
    expected_calls = [("calendar",), (CODE, "2026-01-21", "2026-01-21"), (CODE, "2026-01-21", "2026-01-21")]
    assert market.calls == expected_calls
    repeat = backfill(client, "2026-01-21", "2026-01-22")
    assert repeat["revision"] == second["revision"] and repeat["added"] == {"sessions": 0, "valuations": 0}
    assert market.calls == expected_calls
    outside = backfill(client, "2026-02-03")
    assert outside["status"] == "insufficient"
    assert outside["remaining"] == [{"date": "2026-02-03", "issues": ["calendar-missing", "fuyao-calendar-coverage"]}]


def test_fuyao_backfill_checks_revision_after_network_and_prefers_local_evidence(ledger_db):
    market = FixtureMarketEvidence(["2026-01-20", "2026-01-21", "2026-01-22"])
    client = ledger_client(ledger_db, source=market)
    post(client, "/opening", {"date": "2026-01-20", "positions": {}})
    draft = upload(client, b"one-record")
    confirmed = post(client, f'/drafts/{draft["id"]}/confirm', confirmation(draft))
    cover(client, "2026-01-21", confirmed["revision"])
    market.prices[DAY] = "99.00"
    market.before_history = lambda: post(client, "/evidence", {"valuations": [
        valuation("2026-01-21", "100.00", kind="suspended-valuation"),
    ]})
    result = backfill(client, "2026-01-21", status=409)
    assert result["detail"]["added"] == {"sessions": 2, "valuations": 0}
    assert get(client, "/days/2026-01-21")["closing"][0]["close"] == "100.00"
    retry = backfill(client, "2026-01-21")
    assert retry["status"] == "complete" and retry["added"] == {"sessions": 0, "valuations": 0}
    assert market.calls == [("calendar",), (CODE, "2026-01-21", "2026-01-21")]


def test_fuyao_backfill_selected_range_loads_previous_session_valuation(ledger_db):
    market = FixtureMarketEvidence(["2026-01-19", "2026-01-20", "2026-01-21", "2026-01-22"])
    market.prices = {DAY: "98.23", date(2026, 1, 22): "99.23"}
    client = ledger_client(ledger_db, source=market)
    post(client, "/opening", {"date": "2026-01-20", "positions": {}})
    draft = upload(client, b"one-record")
    confirmed = post(client, f'/drafts/{draft["id"]}/confirm', confirmation(draft))
    cover(client, "2026-01-21", confirmed["revision"])
    result = post(client, "/evidence", {"valuations": [valuation("2026-01-22", None)]})
    cover(client, "2026-01-22", result["revision"], "no-trades")
    result = backfill(client, "2026-01-22")
    assert result["status"] == "complete" and result["added"] == {"sessions": 3, "valuations": 2}
    assert market.calls == [("calendar",), (CODE, "2026-01-21", "2026-01-22")]
    following = get(client, "/days/2026-01-22")
    assert following["opening"][0]["close"] == "98.23"
    assert following["pnl"] == "100.00"


@pytest.mark.parametrize("sold,remaining,after_pnl", [(200, 0, "0.00"), (100, 100, "100.00")])
def test_late_sale_reopens_only_affected_coverage_and_revalues_remaining_holdings(ledger_db, sold, remaining, after_pnl):
    market = FixtureMarketEvidence(["2026-03-18", "2026-03-19", "2026-03-20", "2026-03-23", "2026-03-24"])
    market.prices = {date(2026, 3, 18): "100", date(2026, 3, 19): "101",
                     date(2026, 3, 20): "102", date(2026, 3, 23): "103"}
    client = ledger_client(ledger_db, source=market)
    post(client, "/opening", {"date": "2026-03-18", "positions": {CODE: 200}})
    revision = post(client, "/evidence", {"sessions": [
        session("2026-03-18"), session("2026-03-19", "2026-03-18"), session("2026-03-20", "2026-03-19"),
        session("2026-03-23", "2026-03-20"),
    ], "valuations": [
        valuation("2026-03-19", None), valuation("2026-03-20", None), valuation("2026-03-23", None),
    ]})["revision"]
    cover(client, "2026-03-19", revision, "no-trades", "2026-03-23")

    draft = upload(client, b"late-sale")
    sale = confirmation(draft)
    sale["rows"][0]["fields"] = trade(date="2026-03-20", side="sell", filled_quantity=sold,
                                     price="102", amount=str(sold * 102)).model_dump(mode="json")
    confirmed = post(client, f'/drafts/{draft["id"]}/confirm', sale)
    assert confirmed["saved"][0]["date"] == "2026-03-20"
    assert get(client, "/days/2026-03-19")["coverage"] == "no-trades"
    assert get(client, "/days/2026-03-20")["coverage"] is None
    blocked = get(client, "/days/2026-03-23")
    assert blocked["coverage"] == "no-trades" and blocked["pnl"] is None
    assert blocked["blocking_coverage_date"] == "2026-03-20"

    cover(client, "2026-03-20", confirmed["revision"])
    result = backfill(client, "2026-03-19", "2026-03-23")
    assert result["status"] == "complete"
    assert market.calls == [(CODE, "2026-03-18", "2026-03-23" if remaining else "2026-03-19")]
    later = get(client, "/days/2026-03-23")
    assert sum(row["quantity"] for row in later["closing"]) == remaining
    assert later["pnl"] == after_pnl
    assert post(client, f'/drafts/{draft["id"]}/confirm', sale) == confirmed
    assert get(client, "/days/2026-03-20")["coverage"] == "complete"


def test_concurrent_confirmation_stale_review_and_rollback(ledger_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    client = ledger_client(ledger_db)
    set_up(client)
    first = upload(client, b"first")
    overlap = upload(client, b"different screenshot, same fields")
    payload = confirmation(first)
    barrier = Barrier(2)

    def simultaneous():
        barrier.wait(timeout=5)
        return post(client, f'/drafts/{first["id"]}/confirm', payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(simultaneous) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
    post(client, f'/drafts/{first["id"]}/confirm', {**payload, "revision": 0}, 409)
    stale = confirmation(overlap, key="overlap_confirmation")
    post(client, f'/drafts/{overlap["id"]}/confirm', stale, 409)
    overlap = get(client, f'/drafts/{overlap["id"]}')
    assert overlap["images"][0]["rows"][0]["matches"][0]["kind"] == "possible"
    invalid = confirmation(overlap, key="overlap_confirmation")
    post(client, f'/drafts/{overlap["id"]}/confirm', invalid, 409)
    kept = confirmation(overlap, key="overlap_confirmation", decision="keep-distinct")
    post(client, f'/drafts/{overlap["id"]}/confirm', kept)
    assert len(get(client, "/days/2026-01-21")["trades"]) == 2

    two = upload(client, b"two-records")
    broken = confirmation(two, key="atomic_failure_test", decision="keep-distinct")
    broken["rows"][1]["fields"]["amount"] = "1.00"
    post(client, f'/drafts/{two["id"]}/confirm', broken, 422)
    assert len(get(client, "/days/2026-01-21")["trades"]) == 2
    confirm_two = confirmation(two, key="atomic_failure_test", decision="keep-distinct")
    confirm_two["rows"][0]["fields"]["trade_id"] = "source-1"
    post(client, f'/drafts/{two["id"]}/confirm', confirm_two)
    identified = upload(client, b"new image with a known source id")
    same_fields = confirmation(identified)["rows"][0]
    same_fields["fields"]["trade_id"] = "source-1"
    preview = post(client, f'/drafts/{identified["id"]}/preview', {"rows": [
        {key: value for key, value in same_fields.items() if key != "decision"}
    ]})
    assert preview["images"][0]["rows"][0]["matches"][0]["kind"] == "same-id"
    with trading_pnl_store(ledger_db)(write=True) as repo:
        existing = repo.trades(DAY, DAY)[0]
        assert repo.cached_image(two["images"][0]["digest"]) is None
    with pytest.raises(IntegrityError):
        with trading_pnl_store(ledger_db)(write=True) as repo:
            repo.put_trade(trade(), existing["digest"], existing["row_number"], None, 100)
    assert len(get(client, "/days/2026-01-21")["trades"]) == 4


def test_expired_draft_preview_is_purged(ledger_db):
    client = ledger_client(ledger_db)
    draft = upload(client, b"expires")
    digest = draft["images"][0]["digest"]
    with ledger_db.begin() as connection:
        connection.execute(text("UPDATE trading_pnl_images SET expires_at=CURRENT_TIMESTAMP - interval '1 second'"))
    assert client.get(f'/api/trading-pnl/drafts/{draft["id"]}/images/{digest}').status_code == 404
    store = trading_pnl_store(ledger_db)
    TradingPnlCommands(store, lambda: DAY, fake_screenshot, image_digest).cleanup_previews()
    with ledger_db.connect() as connection:
        stored = connection.execute(text("SELECT preview, rows, hints FROM trading_pnl_images WHERE digest=:digest"),
                                    {"digest": digest}).one()
    assert tuple(stored) == (None, None, None)
