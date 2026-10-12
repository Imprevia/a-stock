"""Offline fixture loading for the static-HTML sectors adapters.

Fixtures are NEVER pulled from a live site during CI. They are hand-authored
synthetic HTML pages captured or synthesised by an operator and stored under
``tests/fixtures/{host}_html/``. Each fixture exposes:

* ``<host>.html``        — synthetic HTML
* ``expected_rows.json`` — the typed rows the adapter should emit
* ``page_meta.json``     — selectors / footprint for the DriftDetector
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_FIXTURE_ROOT = Path(__file__).resolve().parents[5] / "tests" / "fixtures"


@dataclass(frozen=True, slots=True)
class HostFixture:
    host_id: str
    page_html: str
    expected_rows: list[Mapping[str, object]]
    meta: Mapping[str, object]

    @property
    def footprint(self) -> Mapping[str, object]:
        return self.meta.get("footprint", {})


def load_host_fixture(host_id: str) -> HostFixture:
    """Load the synthetic fixture for the given host id (e.g. ``sina``)."""
    if not host_id.replace("_", "").isalnum():
        raise ValueError(f"invalid host id: {host_id!r}")
    base = _FIXTURE_ROOT / f"{host_id}_html"
    html_path = base / "page.html"
    rows_path = base / "expected_rows.json"
    meta_path = base / "page_meta.json"
    if not html_path.exists() or not rows_path.exists() or not meta_path.exists():
        raise FileNotFoundError(
            f"missing fixture for {host_id!r}; expected {html_path} / {rows_path} / {meta_path}"
        )
    return HostFixture(
        host_id=host_id,
        page_html=html_path.read_text(encoding="utf-8"),
        expected_rows=json.loads(rows_path.read_text(encoding="utf-8")),
        meta=json.loads(meta_path.read_text(encoding="utf-8")),
    )


def iter_fixtures() -> tuple[HostFixture, ...]:
    """Iterate over every static-HTML fixture installed under tests/fixtures."""
    if not _FIXTURE_ROOT.exists():
        return ()
    fixtures: list[HostFixture] = []
    for child in sorted(_FIXTURE_ROOT.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if not name.endswith("_html"):
            continue
        fixtures.append(load_host_fixture(name.removesuffix("_html")))
    return tuple(fixtures)


__all__ = ["load_host_fixture", "iter_fixtures", "HostFixture"]
