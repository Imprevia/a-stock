from datetime import date, datetime, timezone

from src.market_environment.service import MarketEnvironmentService
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore, TradingSessionRecord


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_quotes(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("next-session read must not call provider")


def _core_payload(as_of: date, change: float) -> dict:
    return {
        "asOf": as_of.isoformat(),
        "indices": [
            {
                "name": "上证指数",
                "changePct": change,
                "close": 101 + change,
                "movingAverages": {"ma20": 100},
                "amountRatio5": 1.1,
                "volumePriceState": "上涨放量" if change > 0 else "放量下跌",
                "dataGaps": [],
                "dataQuality": {"warning": None},
            },
        ],
        "summary": {"syncPattern": {"code": "synchronized_rally", "label": "同步上涨"}},
    }


def _breadth_payload(as_of: date, ratio: float, median_return: float) -> dict:
    return {
        "advanceCount": 60,
        "declineCount": 40,
        "flatCount": 0,
        "validCount": 100,
        "advanceRatio": ratio,
        "medianReturn": median_return,
        "state": "多数上涨",
        "quality": {"asOf": as_of.isoformat(), "warnings": []},
    }


def _seed(store: SnapshotStore, as_of: date, change: float, ratio: float) -> None:
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    store.put(SnapshotRecord("core", as_of, _core_payload(as_of, change), "fixture", "ok", 1, (), now, settled=True))
    store.put(SnapshotRecord("breadth", as_of, _breadth_payload(as_of, ratio, change), "fixture", "ok", 100, (), now, settled=True))
    store.put_trading_session(TradingSessionRecord(as_of, None, True, "fixture", actual_as_of=as_of, fetched_at=now))


def test_next_session_uses_strict_real_session_and_zero_provider_calls(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "next-session.sqlite3")
    current = date(2026, 9, 11)
    next_session = date(2026, 9, 14)
    _seed(store, current, 0.5, 0.55)
    _seed(store, next_session, 1.0, 0.7)
    provider = CountingProvider()
    service = MarketEnvironmentService(provider=provider, snapshot_store=store, persistent_cache=True, local_reads_only=True)

    result = service.get_next_session_comparison(current)

    assert result["status"] == "available"
    assert result["currentAsOf"] == current.isoformat()
    assert result["nextAsOf"] == next_session.isoformat()
    assert result["deltas"]["advanceRatio"] == 0.15
    assert provider.calls == 0


def test_next_session_missing_payload_is_pending_without_calendar_fallback(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "pending.sqlite3")
    current = date(2026, 9, 11)
    next_session = date(2026, 9, 14)
    _seed(store, current, 0.5, 0.55)
    store.put_trading_session(TradingSessionRecord(next_session, current, True, "fixture", actual_as_of=next_session))
    service = MarketEnvironmentService(provider=CountingProvider(), snapshot_store=store, persistent_cache=True, local_reads_only=True)

    result = service.get_next_session_comparison(current)

    assert result["status"] == "pending"
    assert result["nextAsOf"] == next_session.isoformat()
    assert result["current"]["advanceRatio"] == 0.55
