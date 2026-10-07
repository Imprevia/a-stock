"""Market-data provider adapters."""

from __future__ import annotations

from importlib import import_module


_EXPORT_MODULES = {
    "ActiveDirectionCollector": ".active_direction",
    "BreadthCollector": ".breadth",
    "CoreCollector": ".core",
    "FuyaoCollectionPolicy": ".fuyao_policy",
    "LimitsCollector": ".limits",
    "SectorsCollector": ".sectors",
}


def __getattr__(name: str):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value

__all__ = [
    "ActiveDirectionCollector",
    "BreadthCollector",
    "CoreCollector",
    "FuyaoCollectionPolicy",
    "LimitsCollector",
    "SectorsCollector",
]
