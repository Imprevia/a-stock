"""Tiny HTML selector helpers used by the static-HTML sector adapters.

The adapters must not depend on ``lxml`` / ``parsel`` / ``selectolax`` because
the runtime image only guarantees the standard library. A no-dependency
HTML parser walker is enough to extract the four web-visible facts each card
exposes.
"""

from __future__ import annotations

from html.parser import HTMLParser

from .text_normalize import normalize_text


class _CardExtractor(HTMLParser):
    """Walk the page and surface per-row attribute and text tokens.

    Each ``<tr>`` boundary opens a new row; every opening tag's attributes
    are added as ``("@name", value)`` tokens; text nodes are added as
    ``("@text", text)``. The empty row at index 0 (the start of the
    document before the first ``<tr>``) is dropped by ``parse_cards``.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._rows: list[list[tuple[str, str]]] = [[]]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._rows.append([])
        for name, value in attrs:
            self._rows[-1].append((f"@{name}", value or ""))

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        for name, value in attrs:
            self._rows[-1].append((f"@{name}", value or ""))

    def handle_data(self, data: str) -> None:
        text = normalize_text(data)
        if text:
            self._rows[-1].append(("@text", text))

    @property
    def rows(self) -> list[list[tuple[str, str]]]:
        return [row for row in self._rows if row]


def parse_cards(html: str) -> list[list[tuple[str, str]]]:
    """Parse the page into a list of card rows (each row is attribute tokens)."""
    extractor = _CardExtractor()
    extractor.feed(html)
    extractor.close()
    return extractor.rows


def find_attr(row: list[tuple[str, str]], *, key: str) -> str | None:
    """Return the first attribute token matching ``@key`` from one row."""
    needle = f"@{key}"
    for attr, value in row:
        if attr == needle:
            return value
    return None


def find_text_after(
    row: list[tuple[str, str]],
    *,
    contains: str | None = None,
    skip_first: int = 0,
) -> str | None:
    """Return the first ``@text`` token whose value contains the substring."""
    seen = 0
    needle = contains.lower() if isinstance(contains, str) else None
    for attr, value in row:
        if attr != "@text":
            continue
        if needle is not None and needle not in value.lower():
            continue
        if seen < skip_first:
            seen += 1
            continue
        return value
    return None


__all__ = ["parse_cards", "find_attr", "find_text_after"]
