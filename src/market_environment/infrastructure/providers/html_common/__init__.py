"""Shared helpers for static-HTML sectors adapters.

Two adjacent adapters (``sectors-sina-html`` and ``sectors-xueqiu-html``) read a
single static page per request through the Scrapling static engine and emit
typed ``SectorRow`` data. This package owns the cross-adapter pieces:

* text normalisation (``text_normalize``);
* a no-dependency HTML selector walker (``selectors``);
* offline fixture loading (``fixture_loader``);
* the DriftDetector used by both adapters (``drift``);
* the shared SourceAdapter scaffolding (``base_adapter``).
"""

from .base_adapter import (
    HtmlAdapterRow,
    StaticHtmlSectorAdapter,
    StaticHtmlTransportError,
    ensure_leader_text,
    normalize_money_to_yuan,
    normalize_pct,
)
from .drift import DriftDetector
from .fixture_loader import HostFixture, iter_fixtures, load_host_fixture
from .selectors import find_attr, find_text_after, parse_cards
from .text_normalize import decode_entities, is_leader_text, normalize_text

__all__ = [
    "DriftDetector",
    "HostFixture",
    "HtmlAdapterRow",
    "StaticHtmlSectorAdapter",
    "StaticHtmlTransportError",
    "decode_entities",
    "ensure_leader_text",
    "find_attr",
    "find_text_after",
    "is_leader_text",
    "iter_fixtures",
    "load_host_fixture",
    "normalize_money_to_yuan",
    "normalize_pct",
    "normalize_text",
    "parse_cards",
]
