"""Xueqiu static-HTML sector adapter.

The ``sectors-xueqiu-html`` adapter is the last tier of the sectors fallback
chain. It mirrors the contract documented in
``openspec/changes/add-static-html-sector-fallback/specs`` exactly.
"""
from .adapter import XueqiuHtmlSectorAdapter

__all__ = ["XueqiuHtmlSectorAdapter"]
