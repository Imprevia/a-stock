"""Conservative Fuyao THS to Eastmoney BK sector enrichment helpers.

The supplemental endpoint uses a different industry taxonomy and identity
space.  This module deliberately keeps matching deterministic and fail-closed:
an explicit reviewed mapping or one exact normalized-name candidate is required
before any supplemental value is copied into a Fuyao row.
"""

from __future__ import annotations

import math
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


ENRICHMENT_MAPPING_REVISION = "fuyao-eastmoney-sector-map-v1"
ENRICHMENT_MATCH_METHOD = "explicit-code-or-normalized-name"
SUPPLEMENTAL_FIELDS = ("mainNet", "mainNetPct", "upCount", "downCount", "leader")


def normalize_sector_name(value: Any) -> str:
    """Normalize only presentation noise; never remove semantic words."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return "".join(char for char in text if not char.isspace() and not unicodedata.category(char).startswith("P"))


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text and text not in {"-", "--"} else None


def _finite(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        number = float(str(value).replace(",", "").strip()) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass(frozen=True)
class SectorMatch:
    base_index: int
    source_index: int
    method: str


@dataclass(frozen=True)
class SectorMatchResult:
    matches: tuple[SectorMatch, ...]
    unmatched_base: tuple[int, ...]
    unmatched_source: tuple[int, ...]
    conflicts: tuple[str, ...]
    warnings: tuple[str, ...]
    mapping_revision: str

    @property
    def matched_rows(self) -> int:
        return len(self.matches)


class SectorIdentityMatcher:
    """Match accepted Fuyao rows to supplemental Eastmoney rows."""

    def __init__(
        self,
        mapping: Mapping[str, str] | None = None,
        *,
        revision: str = ENRICHMENT_MAPPING_REVISION,
        change_tolerance: float = 1.0,
        amount_tolerance_ratio: float = 0.5,
    ) -> None:
        self.revision = str(revision)
        self.mapping = {
            str(key).strip().upper(): str(value).strip().upper()
            for key, value in (mapping or {}).items()
            if str(key).strip() and str(value).strip()
        }
        self.change_tolerance = max(0.0, float(change_tolerance))
        self.amount_tolerance_ratio = max(0.0, float(amount_tolerance_ratio))

    def match(
        self,
        base_rows: Sequence[Mapping[str, Any]],
        source_rows: Sequence[Mapping[str, Any]],
    ) -> SectorMatchResult:
        by_code: dict[str, list[int]] = defaultdict(list)
        by_name: dict[str, list[int]] = defaultdict(list)
        for index, row in enumerate(source_rows):
            code = _text(row.get("f12") or row.get("code") or row.get("bkCode"))
            name = normalize_sector_name(row.get("f14") or row.get("name"))
            if code:
                by_code[code.upper()].append(index)
            if name:
                by_name[name].append(index)

        matches: list[SectorMatch] = []
        conflicts: list[str] = []
        used_source: set[int] = set()
        unmatched_base: list[int] = []
        for base_index, base in enumerate(base_rows):
            ths_code = _text(base.get("code") or base.get("thscode"))
            base_name = normalize_sector_name(base.get("name"))
            candidates: list[tuple[int, str]] = []
            mapped_code = self.mapping.get((ths_code or "").upper())
            if mapped_code:
                candidates = [(index, "explicit-code") for index in by_code.get(mapped_code, ())]
                if len(candidates) > 1:
                    conflicts.append(f"base row {base_index} explicit mapping has duplicate source code")
                    candidates = []
            if not candidates and base_name:
                candidates = [(index, "normalized-name") for index in by_name.get(base_name, ())]
                if len(candidates) > 1:
                    conflicts.append(f"base row {base_index} normalized name has {len(candidates)} candidates")
                    candidates = []
            if not candidates:
                unmatched_base.append(base_index)
                continue
            source_index, method = candidates[0]
            if source_index in used_source:
                conflicts.append(f"source row {source_index} matched more than one base row")
                unmatched_base.append(base_index)
                continue
            source = source_rows[source_index]
            source_name = normalize_sector_name(source.get("f14") or source.get("name"))
            if base_name and source_name and base_name != source_name:
                conflicts.append(f"base row {base_index} taxonomy/name conflict")
                unmatched_base.append(base_index)
                continue
            if not self._sanity_check(base, source):
                conflicts.append(f"base row {base_index} change/amount sanity conflict")
                unmatched_base.append(base_index)
                continue
            matches.append(SectorMatch(base_index, source_index, method))
            used_source.add(source_index)

        unmatched_source = tuple(index for index in range(len(source_rows)) if index not in used_source)
        warnings = [
            f"sector enrichment mapping coverage {len(matches)}/{len(base_rows)}",
        ]
        warnings.extend(conflicts)
        return SectorMatchResult(
            matches=tuple(matches),
            unmatched_base=tuple(unmatched_base),
            unmatched_source=unmatched_source,
            conflicts=tuple(conflicts),
            warnings=tuple(warnings),
            mapping_revision=self.revision,
        )

    def _sanity_check(self, base: Mapping[str, Any], source: Mapping[str, Any]) -> bool:
        base_change = _finite(base.get("changePct"))
        source_change = _finite(source.get("f3"))
        if base_change is not None and source_change is not None:
            # Accept either canonical or integerized source scale here; the
            # adapter's global scale check determines which value is usable.
            candidates = (source_change, source_change / 100.0)
            if not any(abs(candidate - base_change) <= self.change_tolerance for candidate in candidates):
                return False
        base_amount = _finite(base.get("amount"))
        source_amount = _finite(source.get("f6"))
        if base_amount is not None and source_amount is not None:
            denominator = max(abs(base_amount), abs(source_amount), 1.0)
            if abs(base_amount - source_amount) / denominator > self.amount_tolerance_ratio:
                return False
        return True


__all__ = [
    "ENRICHMENT_MAPPING_REVISION",
    "ENRICHMENT_MATCH_METHOD",
    "SUPPLEMENTAL_FIELDS",
    "SectorIdentityMatcher",
    "SectorMatch",
    "SectorMatchResult",
    "normalize_sector_name",
]
