"""``sectors-sina-html`` adapter.

The adapter reads one static page from ``finance.sina.com.cn`` per request,
holds the page through the Scrapling static engine, and emits typed
``SectorRow`` data. The ``fixture`` ``HostFixture`` value injected at
composition time supplies the synthetic HTML the adapter parses.
"""

from __future__ import annotations

import re

from ..html_common.base_adapter import (
    HtmlAdapterRow,
    StaticHtmlSectorAdapter,
    ensure_leader_text,
    normalize_money_to_yuan,
    normalize_pct,
)
from ..html_common.fixture_loader import HostFixture
from ..html_common.selectors import find_attr, parse_cards
from ..html_common.text_normalize import strip_leader_label

_CODE_RE = re.compile(r"\b(BK\d{4,6})\b")
_INDUSTRY_PREFIX = re.compile(r"^\s*(?:行业|板块)[:：\s]*")
_FALLBACK_NAME = "(未知行业)"


def _looks_like_amount(token: str, name: str) -> bool:
    if "%" in token:
        return False
    if any(unit in token for unit in ("亿", "万", "元")):
        return True
    cleaned = token.replace(",", "").replace(".", "").replace("-", "")
    return bool(cleaned.isdigit()) and token != name


class SinaHtmlSectorAdapter(StaticHtmlSectorAdapter):
    HOST_ID = "sina"
    HOST_LABEL = "finance.sina.com.cn"
    CAPABILITY_REVISION = "crawl-html-sina-v1"

    def extract_rows(
        self, page_html: str, *, fixture: HostFixture
    ) -> list[HtmlAdapterRow]:
        rows = parse_cards(page_html)
        out: list[HtmlAdapterRow] = []
        seen_codes: set[str] = set()
        for row in rows:
            raw_code = find_attr(row, key="data-symbol")
            if not raw_code:
                anchor = find_attr(row, key="id")
                if anchor:
                    match = _CODE_RE.search(anchor)
                    if match:
                        raw_code = match.group(1)
            if not raw_code or raw_code in seen_codes:
                continue
            seen_codes.add(raw_code)

            text_tokens = [value for attr, value in row if attr == "@text"]
            if not text_tokens:
                continue

            name = _FALLBACK_NAME
            for token in text_tokens:
                if "行业" in token or "板块" in token:
                    candidate = _INDUSTRY_PREFIX.sub("", token).strip()
                    if candidate:
                        name = candidate
                        break

            change_pct_text = next(
                (token for token in text_tokens if "%" in token), None
            )
            amount_text = next(
                (
                    token
                    for token in text_tokens
                    if _looks_like_amount(token, name)
                    and not token.startswith(("行业", "板块", "龙头", "领涨"))
                ),
                None,
            )

            leader_token = next(
                (
                    token
                    for token in text_tokens
                    if "龙头" in token or "领涨" in token
                ),
                None,
            )
            stripped_leader = strip_leader_label(leader_token)
            leader = ensure_leader_text(stripped_leader)
            leader_identifier_dropped = (
                leader_token is not None
                and stripped_leader is not None
                and leader is None
            )

            change_pct = (
                normalize_pct(change_pct_text) if change_pct_text else 0.0
            )
            amount = (
                normalize_money_to_yuan(amount_text) if amount_text else 0.0
            )

            out.append(
                HtmlAdapterRow(
                    code=raw_code,
                    name=name,
                    change_pct=change_pct,
                    amount=amount,
                    leader=leader,
                    provenance_attrs={
                        "host": self.HOST_ID,
                        "page-source": "finance.sina.com.cn",
                        "extraction-strategy": "static-card-text",
                        "leader-identifier-not-name": (
                            "leader-token-was-not-a-name"
                            if leader_identifier_dropped
                            else None
                        ),
                    },
                )
            )
        if not out:
            raise ValueError("sina parser found no industry rows on the page")
        return out


__all__ = ["SinaHtmlSectorAdapter"]
