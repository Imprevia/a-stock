"""Market-data provider adapters."""

from .active_direction import ActiveDirectionCollector
from .breadth import BreadthCollector
from .core import CoreCollector
from .sectors import SectorsCollector

__all__ = [
    "ActiveDirectionCollector",
    "BreadthCollector",
    "CoreCollector",
    "SectorsCollector",
]
