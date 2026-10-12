"""HTML text normalisation shared between the static-HTML sectors adapters."""

from __future__ import annotations

import html as _html
import re

_MULTISPACE = re.compile(r"\s+")
_LEADING_TRAILING = re.compile(r"^[\s\u00a0]+|[\s\u00a0]+$")


def decode_entities(text: str | None) -> str:
    """Decode HTML entities and collapse whitespace."""
    if text is None:
        return ""
    decoded = _html.unescape(str(text))
    return _LEADING_TRAILING.sub("", decoded)


def normalize_text(text: str | None) -> str:
    """Decode entities and collapse inner whitespace to single spaces."""
    decoded = decode_entities(text)
    return _MULTISPACE.sub(" ", decoded).strip()


_LEADER_LABEL_RE = __import__("re").compile(
    r"^[\s\u00a0]*(?:龙头|领涨|领跌|领先股)[:：\s\u00a0]*"
)


def strip_leader_label(value: str | None) -> str | None:
    """Remove the leading ``龙头`` / ``领涨`` / ``领先股`` label, if present.

    The static HTML pages consistently prefix the leader text with one of
    these labels; the field-authority contract requires the ``SectorRow``
    ``leader`` value to be the name only.
    """
    if value is None:
        return None
    return _LEADER_LABEL_RE.sub("", normalize_text(value)).strip() or None


_LEADER_LABEL_RE = __import__("re").compile(
    r"^[\s\u00a0]*(?:龙头|领涨|领跌|领先股)[:：\s\u00a0]*"
)


def strip_leader_label(value: str | None) -> str | None:
    """Remove the leading ``龙头`` / ``领涨`` / ``领先股`` label, if present.

    The static HTML pages consistently prefix the leader text with one of
    these labels; the field-authority contract requires the ``SectorRow``
    ``leader`` value to be the name only.
    """
    if value is None:
        return None
    return _LEADER_LABEL_RE.sub("", normalize_text(value)).strip() or None


def is_leader_text(value: str | None) -> bool:
    """Return True iff the value looks like a leader display string.

    A leader is a name; identifiers (digits / 6-digit codes) and short numeric
    badges are explicitly rejected so the adapter never writes a code or a
    number into the ``leader`` ``SectorRow`` field.
    """
    if value is None:
        return False
    candidate = normalize_text(value)
    if not candidate:
        return False
    if len(candidate) > 40:
        return False
    if re.fullmatch(r"[\d.\-+%,%]+", candidate):
        return False
    if re.fullmatch(r"\d{6}", candidate):
        return False
    # Any CJK ideograph or Han character qualifies as a name-ish leader.
    if any("\u4e00" <= ch <= "\u9fff" for ch in candidate):
        return True
    return bool(re.search(r"[A-Za-z]{2,}", candidate))


__all__ = ["decode_entities", "is_leader_text", "normalize_text", "strip_leader_label"]
