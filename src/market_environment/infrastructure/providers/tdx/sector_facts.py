"""Convert the audited TDX daily package into immutable sector input facts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from ....domain.models import Lineage, SecurityDailyFact
from ....domain.analysis.point_in_time_industry import canonical_security_id
from .daily_package import (
    TDXDailyPackageRow,
    TDXStockUniverseClassification,
    classify_tdx_stock_universe,
    normalize_tdx_rows,
    validate_tdx_stock_universe,
)


def _checksum(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_tdx_security_facts(
    rows: Iterable[TDXDailyPackageRow | Mapping[str, Any]],
    *,
    as_of: date,
    source_revision: str,
    package_checksum: str,
    fetched_at: datetime,
    require_complete_universe: bool = True,
    validation_options: Mapping[str, Any] | None = None,
) -> tuple[tuple[SecurityDailyFact, ...], TDXStockUniverseClassification]:
    """Reuse the existing exact-date normalizer and universe auditor.

    Missing amount remains ``None`` and never falls back to volume.  Adjusted
    prices are intentionally absent because they are persisted only through a
    separately approved adjustment revision.
    """

    normalized = normalize_tdx_rows(rows, as_of)
    classification = classify_tdx_stock_universe(normalized, as_of)
    if require_complete_universe:
        validate_tdx_stock_universe(classification, **dict(validation_options or {}))
    warnings = tuple(
        f"{kind}:{reason}={count}"
        for kind, values in (
            ("excluded", classification.excluded_by_reason),
            ("unclassified", classification.unclassified_by_reason),
        )
        for reason, count in sorted(values.items())
    )
    facts: list[SecurityDailyFact] = []
    for row in classification.rows:
        assert row.market is not None
        security_id = canonical_security_id(row.code, row.market)
        row_checksum = _checksum(
            {
                "packageChecksum": package_checksum,
                "sourceRevision": source_revision,
                "securityId": security_id,
                "asOf": as_of.isoformat(),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "previousClose": row.previous_close,
                "volume": row.volume,
                "amount": row.amount,
            }
        )
        availability = {
            "originalOpen": row.open is not None,
            "originalHigh": row.high is not None,
            "originalLow": row.low is not None,
            "originalClose": row.close is not None,
            "previousClose": row.previous_close is not None,
            "volume": row.volume is not None,
            "amount": row.amount is not None,
        }
        lineage = Lineage(
            requested_as_of=as_of,
            actual_as_of=as_of,
            source="tdx-daily-package",
            source_revision=source_revision,
            schema_version=1,
            checksum=row_checksum,
            data_version=package_checksum,
            universe_version=classification.policy_version,
            fetched_at=fetched_at,
            warnings=warnings,
            quality_status="ok" if all(availability.values()) else "partial",
            observation_count=classification.retained_count,
            field_availability=availability,
            evidence_references=(package_checksum,),
        )
        facts.append(
            SecurityDailyFact(
                security_id=security_id,
                as_of=as_of,
                market=row.market,  # type: ignore[arg-type]
                original_close=row.close,
                previous_close=row.previous_close,
                adjusted_close=None,
                amount=row.amount,
                volume=row.volume,
                change_pct=row.change_pct,
                eligible=True,
                exclusion_reason=None,
                lineage=lineage,
                original_open=row.open,
                original_high=row.high,
                original_low=row.low,
                adjusted_previous_close=None,
            )
        )
    return tuple(facts), classification


def attach_adjusted_prices(
    facts: Iterable[SecurityDailyFact],
    adjusted_prices: Mapping[str, tuple[float | None, float | None]],
    *,
    adjustment_revision: str,
    evidence_checksum: str,
) -> tuple[SecurityDailyFact, ...]:
    """Create a new fact revision while leaving original amount untouched."""

    revised: list[SecurityDailyFact] = []
    for fact in facts:
        adjusted_close, adjusted_previous = adjusted_prices.get(
            fact.security_id, (None, None)
        )
        available = adjusted_close is not None and adjusted_previous is not None
        lineage = replace(
            fact.lineage,
            checksum=_checksum(
                {
                    "originalChecksum": fact.lineage.checksum,
                    "adjustmentRevision": adjustment_revision,
                    "adjustmentEvidence": evidence_checksum,
                    "adjustedClose": adjusted_close,
                    "adjustedPreviousClose": adjusted_previous,
                }
            ),
            adjustment_version=adjustment_revision,
            quality_status=fact.lineage.quality_status if available else "partial",
            field_availability={
                **fact.lineage.field_availability,
                "adjustedClose": adjusted_close is not None,
                "adjustedPreviousClose": adjusted_previous is not None,
            },
            evidence_references=tuple(
                dict.fromkeys((*fact.lineage.evidence_references, evidence_checksum))
            ),
        )
        revised.append(
            replace(
                fact,
                adjusted_close=adjusted_close,
                adjusted_previous_close=adjusted_previous,
                lineage=lineage,
            )
        )
    return tuple(revised)


__all__ = ["attach_adjusted_prices", "build_tdx_security_facts"]
