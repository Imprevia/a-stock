"""Optional, versioned stock-to-industry mapping boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def normalized_identity(market: str | None, code: str) -> str:
    exchange = str(market or "").strip().upper()
    exchange = {"SH": "SH", "SZ": "SZ", "BJ": "BJ"}.get(exchange, exchange)
    return f"{str(code).strip().zfill(6)}.{exchange}" if exchange else str(code).strip().zfill(6)


@dataclass(frozen=True)
class IndustryMappingResult:
    revision: str
    mapped: Mapping[str, str]
    total: int

    @property
    def covered(self) -> int:
        return sum(1 for value in self.mapped.values() if value)

    @property
    def coverage(self) -> float:
        return self.covered / self.total if self.total else 0.0


class VersionedIndustryMapper:
    """Resolve identities without silently inventing a historical industry."""

    def __init__(self, mapping: Mapping[str, str] | None = None, *, revision: str = "industry-map-unavailable-v1"):
        self.revision = str(revision)
        self.mapping = {
            str(key).strip().upper(): str(value).strip()
            for key, value in (mapping or {}).items()
            if str(key).strip() and str(value).strip()
        }

    def resolve(self, rows: list[Mapping[str, Any]]) -> IndustryMappingResult:
        mapped: dict[str, str] = {}
        for row in rows:
            code = str(row.get("code") or "").strip()
            identity = normalized_identity(row.get("market"), code)
            industry = self.mapping.get(identity) or self.mapping.get(code.zfill(6))
            if industry:
                mapped[identity] = industry
        return IndustryMappingResult(self.revision, mapped, len(rows))


__all__ = ["IndustryMappingResult", "VersionedIndustryMapper", "normalized_identity"]
