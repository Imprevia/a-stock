from datetime import date

from src.market_environment.domain.analysis.active_direction_workbench import (
    compose_active_direction_workbench,
)


def _row(code: str, **extra):
    return {
        "rank": 1,
        "code": code,
        "name": f"样本{code}",
        "industry": "算力",
        "amount": 1000000,
        "changePct": 2.0,
        "closePosition": 0.8,
        **extra,
    }


def test_workbench_keeps_valuation_facts_without_promoting_them_to_financial_score():
    payload = {
        "topStocks": [_row("000001", pe=12.4, pb=1.8, marketCap=1000000000, turnoverRatePct=3.2)],
        "quality": {"status": "partial", "source": "eastmoney-clist", "asOf": "2026-10-21"},
    }

    result = compose_active_direction_workbench(payload, date(2026, 10, 21))

    fundamentals = result["fundamentals"]
    assert fundamentals["state"] == "partial"
    assert fundamentals["items"][0]["metrics"]["pe"] == 12.4
    assert fundamentals["items"][0]["score"] is None
    assert "cashFlow" in fundamentals["items"][0]["missingFields"]


def test_workbench_projects_limit_intraday_facts_and_keeps_auction_pending():
    payload = {
        "topStocks": [_row("000001")],
        "quality": {"status": "partial", "source": "fixture", "asOf": "2026-10-21"},
    }
    limits = {
        "securityDetails": {
            "promoted": {
                "rows": [
                    {
                        "securityId": "SZ:000001",
                        "code": "000001",
                        "name": "样本000001",
                        "streakDays": 2,
                        "firstLimitTime": "10:01:00",
                        "lastLimitTime": "14:55:00",
                        "openTimes": 1,
                        "sealMoney": 100000,
                        "source": "fixture",
                        "rowQuality": "ok",
                    }
                ]
            }
        }
    }

    result = compose_active_direction_workbench(payload, date(2026, 10, 21), limits=limits)

    first_to_second = result["candidatePools"]["firstToSecond"]
    assert first_to_second["state"] == "partial"
    assert first_to_second["strictNextSession"][0]["code"] == "000001"
    assert first_to_second["intraday"]["rows"][0]["openTimes"] == 1
    assert first_to_second["auction"]["state"] == "pending"
