"""Stable compatibility exports for the collector provider runtime.

Normal bootstrap owns the implementation through
``infrastructure.providers.runtime.CollectorProviderRuntime``.  This module
retains the historical names only; it must not gain provider logic.
"""

from ..providers.runtime import (
    INDEX_SPECS,
    PRICE_GUARDED_CODES,
    CollectorProviderRuntime,
    IndexSpec,
    LimitPoolRows,
    LimitProviderDatasetResult,
    ProviderResult,
)

MarketDataProvider = CollectorProviderRuntime

__all__ = [
    "CollectorProviderRuntime",
    "INDEX_SPECS",
    "IndexSpec",
    "LimitPoolRows",
    "LimitProviderDatasetResult",
    "MarketDataProvider",
    "PRICE_GUARDED_CODES",
    "ProviderResult",
]
