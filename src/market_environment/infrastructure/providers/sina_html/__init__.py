"""Sina static-HTML sector adapter.

The ``sectors-sina-html`` adapter reads a single static card page from
``finance.sina.com.cn`` through the Scrapling static engine and emits
typed ``SectorRow`` data. It is intended strictly as a last-tier fallback:
it carries four web-visible facts (``name`` / ``changePct`` / ``amount`` /
``leader``) and always leaves ``mainNet`` / ``mainNetPct`` / ``upCount`` /
``downCount`` as ``None`` with structured warnings.
"""
from .adapter import SinaHtmlSectorAdapter

__all__ = ["SinaHtmlSectorAdapter"]
