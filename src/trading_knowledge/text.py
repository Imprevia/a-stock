"""Deterministic text normalization helpers for multilingual FTS queries."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from typing import Any

RULE_ID_RE = re.compile(r"\bQTS-\d{2}-\d{2}-\d{2}\b", re.IGNORECASE)
ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_.:-]+")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\u3000", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[ \t]+", " ", normalized).strip().lower()


def extract_rule_ids(value: str) -> tuple[str, ...]:
    return tuple(sorted({match.upper() for match in RULE_ID_RE.findall(value)}))


def is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def cjk_bigrams(value: str) -> str:
    chars = [char for char in normalize_text(value) if is_cjk(char)]
    if not chars:
        return ""
    if len(chars) == 1:
        return chars[0]
    return " ".join("".join(chars[index : index + 2]) for index in range(len(chars) - 1))


def fts_token(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def query_terms(value: str) -> tuple[list[str], list[str]]:
    normalized = normalize_text(value)
    ascii_terms = [token for token in ASCII_TOKEN_RE.findall(normalized) if token]
    cjk_terms = []
    cjk_chars = [char for char in normalized if is_cjk(char)]
    if len(cjk_chars) == 1:
        cjk_terms = cjk_chars
    elif cjk_chars:
        cjk_terms = ["".join(cjk_chars[index : index + 2]) for index in range(len(cjk_chars) - 1)]
    return sorted(set(ascii_terms)), sorted(set(cjk_terms))


def fts_match_expression(value: str) -> str | None:
    ascii_terms, cjk_terms = query_terms(value)
    clauses: list[str] = []
    if ascii_terms:
        clauses.append("body:(" + " OR ".join(fts_token(term) for term in ascii_terms) + ")")
    if cjk_terms:
        clauses.append("cjk:(" + " OR ".join(fts_token(term) for term in cjk_terms) + ")")
    if not clauses:
        return None
    return " OR ".join(clauses)


def worst_evidence_status(statuses: list[str]) -> str:
    """Conservatively combine evidence states without upgrading any result."""

    if not statuses:
        return "unverified"
    order = {
        "failed": 5,
        "insufficient": 4,
        "degraded": 3,
        "unverified": 2,
        "none": 2,
        "ok": 1,
    }
    return max(statuses, key=lambda value: order.get(value, 4))
