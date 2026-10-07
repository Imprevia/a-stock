"""Explicit collector dependency bundle for normal runtime composition."""

from __future__ import annotations

from ...providers import MarketDataProvider


class CollectorProviderRuntime(MarketDataProvider):
    """Vendor transports shared by dataset collectors, not a query service."""


__all__ = ["CollectorProviderRuntime"]
