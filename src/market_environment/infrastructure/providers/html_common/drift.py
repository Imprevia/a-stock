"""DriftDetector used by both static-HTML sector adapters.

The detector compares the captured ``footprint`` (a small set of selectors and
expected attribute names) against what the live page actually contains. On any
mismatch the adapter MUST emit a ``dom-drift`` warning and refuse to fabricate
``name`` / ``changePct`` / ``amount`` / ``leader`` from unrelated substrings.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def _row_has_attr(row: Iterable[tuple[str, str]], attr_name: str) -> bool:
    needle = f"@{attr_name}"
    for attr, value in row:
        if attr == needle and value:
            return True
    return False


class DriftDetector:
    """Compare a captured DOM footprint against an actual parse."""

    def __init__(self, footprint: Mapping[str, object]) -> None:
        self._footprint = dict(footprint)

    def drift_signals(self, actual_rows: Iterable[Mapping[str, str]]) -> tuple[str, ...]:
        """Return a tuple of drift signals; ``()`` means the page is in shape."""
        signals: list[str] = []
        rows = list(actual_rows)
        if self._footprint.get("expected_selector") and not rows:
            signals.append("empty-body")
            return tuple(signals)
        attrs = tuple(self._footprint.get("required_attrs", ()))
        for required in attrs:
            if not any(_row_has_attr(row, required) for row in rows):
                signals.append(f"missing-attr:{required}")
        return tuple(signals)

    @property
    def footprint(self) -> Mapping[str, object]:
        return dict(self._footprint)


__all__ = ["DriftDetector"]
