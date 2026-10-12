"""Tests for the static-HTML sector adapters.

The adapters are end-of-chain fallbacks: they MUST emit only the four
web-visible ``SectorRow`` fields (code/name/changePct/amount/leader) and
MUST keep ``mainNet``/``mainNetPct``/``upCount``/``downCount`` as ``None``
with a structured warning. They also MUST refuse to classify a leader
identifier or a numeric badge as a leader name. These tests fail loudly
the moment any field authority slips.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from src.market_environment.application.ports.acquisition import (
    SourceRequest,
)
from src.market_environment.domain.models import (
    AcquisitionFailureCategory,
)
from src.market_environment.infrastructure.providers.html_common.base_adapter import (
    HtmlAdapterRow,
    StaticHtmlTransportError,
)
from src.market_environment.infrastructure.providers.html_common.drift import (
    DriftDetector,
)
from src.market_environment.infrastructure.providers.html_common.fixture_loader import (
    HostFixture,
    iter_fixtures,
    load_host_fixture,
)
from src.market_environment.infrastructure.providers.html_common.base_adapter import ensure_leader_text, normalize_money_to_yuan, normalize_pct
from src.market_environment.infrastructure.providers.html_common.text_normalize import is_leader_text, normalize_text, strip_leader_label
from src.market_environment.infrastructure.providers.sina_html import (
    SinaHtmlSectorAdapter,
)
from src.market_environment.infrastructure.providers.xueqiu_html import (
    XueqiuHtmlSectorAdapter,
)


@dataclass(frozen=True)
class _LegacyDatasetDate:
    """Retired adapter identity kept outside the public dataset enum."""

    dataset: str
    as_of: date


def _request(adapter, fixture):
    return SourceRequest(
        identity=_LegacyDatasetDate(dataset="sectors", as_of=date(2026, 10, 9)),
        source_id=adapter.source_id,
        current_market_date=date(2026, 10, 9),
        settled=False,
        params={"fixture": fixture},
    )


def _gate_open(_req):
    return True


def _gate_closed(_req):
    return False


def test_text_normalize_decodes_html_entities() -> None:
    assert normalize_text("A&amp;B&nbsp;C") == "A&B C"


def test_strip_leader_label_handles_dotted_and_undotted_prefixes() -> None:
    assert strip_leader_label("龙头：中芯国际") == "中芯国际"
    assert strip_leader_label("龙头立讯精密") == "立讯精密"
    assert strip_leader_label("龙头：   招商银行") == "招商银行"
    assert strip_leader_label("领涨：宁德时代") == "宁德时代"


def test_is_leader_text_rejects_identifiers_and_bare_numbers() -> None:
    assert is_leader_text(None) is False
    assert is_leader_text("600519") is False
    assert is_leader_text("123456") is False
    assert is_leader_text("中芯国际") is True
    assert is_leader_text("招商银行") is True


def test_ensure_leader_text_strips_and_validates() -> None:
    assert ensure_leader_text("600519") is None
    assert ensure_leader_text("中芯国际") == "中芯国际"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("+2.34%", 2.34),
        ("-1.20%", -1.20),
        ("0.45%", 0.45),
        ("1,234.5%", 1234.5),
    ],
)
def test_normalize_pct_accepts_signs_and_thousands_separator(text, expected) -> None:
    assert normalize_pct(text) == expected


def test_normalize_money_to_yuan_extracts_first_numeric_token() -> None:
    assert normalize_money_to_yuan("成交额123456789元") == 123456789.0
    assert normalize_money_to_yuan("成交额98,765,432元") == 98765432.0


def test_iter_fixtures_discovers_each_html_directory(tmp_path: Path) -> None:
    fixtures = iter_fixtures()
    assert {f.host_id for f in fixtures} == {"sina", "xueqiu"}


def test_load_host_fixture_returns_synthetic_html() -> None:
    sina = load_host_fixture("sina")
    assert sina.host_id == "sina"
    assert "BK0421" in sina.page_html
    assert sina.expected_rows


def test_drift_detector_missing_attr_signals_only_when_attr_absent() -> None:
    detector = DriftDetector(
        {
            "expected_selector": "tr[data-symbol]",
            "required_attrs": ["data-symbol"],
        }
    )
    rows = [[("@data-symbol", "BK0421")], [("@data-symbol", "BK0475")]]
    assert detector.drift_signals(rows) == ()
    bad = [[("@id", "block_1")]]
    assert detector.drift_signals(bad) == ("missing-attr:data-symbol",)


def test_sina_adapter_emits_only_web_visible_fields() -> None:
    fixture = load_host_fixture("sina")
    adapter = SinaHtmlSectorAdapter()
    adapter.set_gate_predicate(_gate_open)
    adapter.set_fetch_override(lambda _req: fixture.page_html)
    result = adapter.acquire(_request(adapter, fixture))
    assert not isinstance(result, Exception)
    rows = result.payload["rows"]
    assert [row["code"] for row in rows] == ["BK0421", "BK0475", "BK0420"]
    for row in rows:
        for forbidden in ("mainNet", "mainNetPct", "upCount", "downCount"):
            assert row[forbidden] is None
    warning_codes = {
        warning.split(":")[1]
        for warning in result.quality.warnings
        if warning.startswith("dom-source-unsupported")
    }
    assert warning_codes == {"mainNet", "mainNetPct", "upCount", "downCount"}


def test_xueqiu_adapter_emits_only_web_visible_fields() -> None:
    fixture = load_host_fixture("xueqiu")
    adapter = XueqiuHtmlSectorAdapter()
    adapter.set_gate_predicate(_gate_open)
    adapter.set_fetch_override(lambda _req: fixture.page_html)
    result = adapter.acquire(_request(adapter, fixture))
    rows = result.payload["rows"]
    assert [row["code"] for row in rows] == ["S123456", "S789012"]
    for row in rows:
        for forbidden in ("mainNet", "mainNetPct", "upCount", "downCount"):
            assert row[forbidden] is None


def test_adapter_returns_gate_failure_when_capability_not_eligible() -> None:
    fixture = load_host_fixture("sina")
    adapter = SinaHtmlSectorAdapter()
    adapter.set_gate_predicate(_gate_closed)
    adapter.set_fetch_override(lambda _req: fixture.page_html)
    result = adapter.acquire(_request(adapter, fixture))
    assert result.category == AcquisitionFailureCategory.CONFIGURATION
    assert "capability gate is not satisfied" in result.message


def test_adapter_classifies_permission_failure_as_non_retryable() -> None:
    fixture = load_host_fixture("sina")
    adapter = SinaHtmlSectorAdapter()
    adapter.set_gate_predicate(_gate_open)

    def _raise(_req):
        raise StaticHtmlTransportError(
            category=AcquisitionFailureCategory.NETWORK,
            signal="host-permission-denied",
            reason="HTTP 403",
        )

    adapter.set_fetch_override(_raise)
    result = adapter.acquire(_request(adapter, fixture))
    assert result.category == AcquisitionFailureCategory.NETWORK
    assert "403" in result.message


def test_adapter_classifies_challenge_interstitial_as_non_retryable() -> None:
    fixture = load_host_fixture("xueqiu")
    adapter = XueqiuHtmlSectorAdapter()
    adapter.set_gate_predicate(_gate_open)

    def _raise(_req):
        raise StaticHtmlTransportError(
            category=AcquisitionFailureCategory.NETWORK,
            signal="host-challenge-detected",
            reason="login wall",
        )

    adapter.set_fetch_override(_raise)
    result = adapter.acquire(_request(adapter, fixture))
    assert result.category == AcquisitionFailureCategory.NETWORK
    assert "login wall" in result.message


def test_adapter_records_drift_signal_when_attr_missing() -> None:
    fixture = load_host_fixture("sina")
    drifted_html = (
        '<html><body><table><tr><td><a>行业：半导体</a>'
        '<span>+2.34%</span><span>成交额123456789元</span>'
        '<span>龙头：中芯国际</span></td></tr></table></body></html>'
    )
    adapter = SinaHtmlSectorAdapter()
    adapter.set_gate_predicate(_gate_open)
    adapter.set_fetch_override(lambda _req: drifted_html)
    result = adapter.acquire(_request(adapter, fixture))
    assert result.category == AcquisitionFailureCategory.CONTRACT
    assert "dom-drift" in result.message


def test_sina_adapter_does_not_promote_identifier_to_leader() -> None:
    fixture = load_host_fixture("sina")
    identifier_html = (
        '<html><body><table>'
        '<tr id="bk_block_1"><td data-symbol="BK0421">'
        '<a>行业：半导体</a><span>+2.34%</span>'
        '<span>成交额123456789元</span><span>龙头：600519</span>'
        '</td></tr></table></body></html>'
    )
    adapter = SinaHtmlSectorAdapter()
    adapter.set_gate_predicate(_gate_open)
    adapter.set_fetch_override(lambda _req: identifier_html)
    result = adapter.acquire(_request(adapter, fixture))
    rows = result.payload["rows"]
    assert rows[0]["leader"] is None
    assert "leader-identifier-not-name" in result.quality.warnings


def test_html_common_adapters_have_distinct_revisions() -> None:
    sina = SinaHtmlSectorAdapter()
    xueqiu = XueqiuHtmlSectorAdapter()
    assert sina.capability.revision != xueqiu.capability.revision
    assert sina.capability.latest_only is True
    assert xueqiu.capability.latest_only is True
    assert sina.source_id != xueqiu.source_id
