"""Offline capability gates and source-neutral industry imports.

No class in this module performs network I/O.  Real adapters must first prove
the same dataset/source/revision contract with an :class:`IndustryCapabilityGate`.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...domain.models import (
    IndustryCapabilityError,
    IndustryCapabilityReport,
    MembershipInterval,
    TaxonomyRevision,
)
from ...domain.models.sector_continuity import IndustryIdentity


class CapabilityGateError(ValueError):
    """Raised when an input is not covered by an eligible capability report."""


class IndustryImportError(ValueError):
    """Raised when an operator taxonomy/membership import is unsafe."""


def _canonical(value: Any) -> str:
    def default(item: Any) -> str:
        if isinstance(item, date):
            return item.isoformat()
        raise TypeError(f"unsupported canonical value: {type(item).__name__}")

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=default,
    )


def _checksum(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class IndustryCapabilityGate:
    """Require an eligible report for the exact dataset/source/revision tuple."""

    def __init__(self, reports: Sequence[IndustryCapabilityReport] = ()) -> None:
        self._reports = {(item.dataset, item.source, item.revision): item.normalized() for item in reports}

    def require(
        self,
        dataset: str,
        source: str,
        revision: str,
        *,
        as_of: date | None = None,
    ) -> IndustryCapabilityReport:
        report = self._reports.get((dataset, source, revision))
        if report is None:
            raise CapabilityGateError(f"capability report is missing: {dataset}/{source}/{revision}")
        if report.status != "eligible":
            raise CapabilityGateError(f"capability is not eligible: {dataset}/{source}/{revision}")
        if as_of is not None and as_of not in report.actual_dates:
            raise CapabilityGateError(f"capability does not prove exact date: {as_of.isoformat()}")
        return report

    def report(self, dataset: str, source: str, revision: str) -> IndustryCapabilityReport | None:
        return self._reports.get((dataset, source, revision))


@dataclass(frozen=True, slots=True)
class OperatorImportResult:
    dataset: str
    source: str
    revision: str
    checksum: str
    taxonomy: TaxonomyRevision | None
    industries: tuple[IndustryIdentity, ...]
    memberships: tuple[MembershipInterval, ...]
    status: str
    warnings: tuple[str, ...] = ()


class ShenwanOperatorImportAdapter:
    """Validate a versioned operator-controlled Shenwan Level 1 import."""

    def __init__(self, *, gate: IndustryCapabilityGate | None = None) -> None:
        self.gate = gate

    def import_file(self, path: str | Path) -> OperatorImportResult:
        source_path = Path(path)
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IndustryImportError("industry import fixture could not be read") from exc
        if not isinstance(payload, Mapping):
            raise IndustryImportError("industry import must be a JSON object")
        return self.import_payload(payload)

    def import_payload(self, payload: Mapping[str, Any]) -> OperatorImportResult:
        dataset = str(payload.get("dataset", ""))
        source = str(payload.get("source", "operator-import"))
        revision = str(payload.get("revision", ""))
        if dataset not in {"shenwan-taxonomy", "shenwan-point-in-time-membership"}:
            raise IndustryImportError("operator import dataset must be Shenwan taxonomy or membership")
        if self.gate is not None:
            try:
                self.gate.require(dataset, source, revision)
            except CapabilityGateError as exc:
                raise IndustryImportError(str(exc)) from exc
        rights = payload.get("dataRights") or payload.get("data_rights")
        if not isinstance(rights, Mapping) or rights.get("reviewed") is not True or rights.get("storageAllowed") is not True:
            raise IndustryImportError("operator import requires reviewed storage data-rights metadata")
        if rights.get("automationAllowed") is not True:
            raise IndustryImportError("operator import requires explicit automation rights")
        supplied_checksum = str(payload.get("checksum", ""))
        if not supplied_checksum:
            raise IndustryImportError("operator import checksum is required")
        body = {str(k): v for k, v in payload.items() if k != "checksum"}
        checksum = _checksum(body)
        if supplied_checksum and supplied_checksum != checksum:
            raise IndustryImportError("operator import checksum mismatch")

        try:
            taxonomy = self._taxonomy(payload.get("taxonomy"), payload, checksum)
            industries = self._industries(payload.get("industries", ()), taxonomy)
            memberships = self._memberships(payload.get("memberships", ()), taxonomy)
        except IndustryImportError:
            raise
        except (TypeError, ValueError) as exc:
            raise IndustryImportError("operator import contains an invalid taxonomy or membership row") from exc
        if dataset == "shenwan-taxonomy" and not industries:
            raise IndustryImportError("taxonomy import contains no industries")
        if dataset == "shenwan-point-in-time-membership" and not memberships:
            raise IndustryImportError("membership import contains no memberships")
        return OperatorImportResult(
            dataset=dataset,
            source=source,
            revision=revision,
            checksum=checksum,
            taxonomy=taxonomy,
            industries=tuple(industries),
            memberships=tuple(memberships),
            status="validated",
        )

    @staticmethod
    def _taxonomy(raw: Any, payload: Mapping[str, Any], checksum: str) -> TaxonomyRevision:
        value = raw if isinstance(raw, Mapping) else payload
        family = str(value.get("taxonomyFamily", value.get("taxonomy_family", "")))
        level = int(value.get("taxonomyLevel", value.get("taxonomy_level", 0)))
        if family != "shenwan" or level != 1:
            raise IndustryImportError("only Shenwan Level 1 taxonomy is accepted")
        try:
            effective_from = date.fromisoformat(str(value.get("effectiveFrom", value.get("effective_from"))))
            raw_to = value.get("effectiveTo", value.get("effective_to"))
            effective_to = date.fromisoformat(str(raw_to)) if raw_to else None
        except (TypeError, ValueError) as exc:
            raise IndustryImportError("taxonomy effective interval is invalid") from exc
        return TaxonomyRevision(
            taxonomy_version=str(value.get("taxonomyVersion", value.get("taxonomy_version", ""))),
            taxonomy_family="shenwan",
            taxonomy_level=1,
            source_revision=str(value.get("sourceRevision", value.get("source_revision", ""))),
            effective_from=effective_from,
            effective_to=effective_to,
            checksum=str(value.get("checksum", "")) or checksum,
        )

    @staticmethod
    def _industries(raw: Any, taxonomy: TaxonomyRevision) -> list[IndustryIdentity]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise IndustryImportError("industries must be an array")
        result: list[IndustryIdentity] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, Mapping):
                raise IndustryImportError("industry row must be an object")
            industry_id = str(item.get("industryId", item.get("industry_id", "")))
            if industry_id in seen:
                raise IndustryImportError(f"duplicate industry identity: {industry_id}")
            seen.add(industry_id)
            result.append(IndustryIdentity(industry_id=industry_id, display_name=str(item.get("displayName", item.get("display_name", ""))), taxonomy=taxonomy))
        return result

    @staticmethod
    def _memberships(raw: Any, taxonomy: TaxonomyRevision) -> list[MembershipInterval]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise IndustryImportError("memberships must be an array")
        result: list[MembershipInterval] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise IndustryImportError("membership row must be an object")
            try:
                valid_from = date.fromisoformat(str(item.get("validFrom", item.get("valid_from"))))
                raw_to = item.get("validTo", item.get("valid_to"))
                valid_to = date.fromisoformat(str(raw_to)) if raw_to else None
            except (TypeError, ValueError) as exc:
                raise IndustryImportError("membership effective interval is invalid") from exc
            result.append(MembershipInterval(
                security_id=str(item.get("securityId", item.get("security_id", ""))),
                industry_id=str(item.get("industryId", item.get("industry_id", ""))),
                taxonomy_version=taxonomy.taxonomy_version,
                valid_from=valid_from,
                valid_to=valid_to,
                source_revision=str(item.get("sourceRevision", item.get("source_revision", taxonomy.source_revision))),
                evidence_checksum=str(item.get("evidenceChecksum", item.get("evidence_checksum", ""))),
            ))
        # Keep a stable market-first order for callers while checking overlap
        # within each canonical security independently.  This makes the
        # import result deterministic without allowing Beijing ``bj.`` IDs to
        # reorder a Shanghai transition fixture.
        market_order = {"sh": 0, "sz": 1, "bj": 2}
        result.sort(
            key=lambda item: (
                market_order.get(item.security_id.split(".", 1)[0], 99),
                item.security_id,
                item.valid_from,
                item.industry_id,
            )
        )
        grouped: dict[tuple[str, str], list[MembershipInterval]] = {}
        for item in result:
            grouped.setdefault((item.security_id, item.taxonomy_version), []).append(item)
        for group in grouped.values():
            for previous, current in zip(group, group[1:]):
                previous_end = previous.valid_to or date.max
                if current.valid_from < previous_end:
                    raise IndustryImportError(f"overlapping membership intervals: {current.security_id}")
        return result


@dataclass(frozen=True, slots=True)
class NormalizedPriceRow:
    security_id: str
    as_of: date
    market: str
    adjusted_close: float | None
    original_close: float | None
    original_amount: float | None
    adjustment_revision: str


@dataclass(frozen=True, slots=True)
class NormalizedPriceResult:
    rows: tuple[NormalizedPriceRow, ...]
    status: str
    checksum: str
    warnings: tuple[str, ...] = ()


class ProviderNeutralAdjustedPriceAdapter:
    """Normalize adjusted prices without selecting a vendor or mutating facts."""

    source = "provider-neutral"
    revision = "adjusted-price-v1"

    def __init__(self, *, gate: IndustryCapabilityGate, source: str | None = None, revision: str | None = None) -> None:
        self.gate = gate
        self.source = source or self.source
        self.revision = revision or self.revision

    def normalize(self, rows: Sequence[Mapping[str, Any]], *, as_of: date) -> NormalizedPriceResult:
        report = self.gate.require("stock-adjusted-price", self.source, self.revision, as_of=as_of)
        if report.field_semantics.get("adjustedClose") != "front-adjusted-close":
            raise IndustryImportError("adjusted-price capability does not prove front-adjusted close semantics")
        if report.field_semantics.get("originalAmount") != "original-yuan":
            raise IndustryImportError("adjusted-price capability does not preserve original amount semantics")
        normalized: list[NormalizedPriceRow] = []
        seen_security_ids: set[str] = set()
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise IndustryImportError("adjusted-price row must be an object")
            row_date = date.fromisoformat(str(raw.get("asOf", raw.get("as_of", ""))))
            if row_date != as_of:
                raise IndustryImportError("adjusted-price row date mismatch")
            market = str(raw.get("market", ""))
            if market not in {"sh", "sz", "bj"}:
                raise IndustryImportError("adjusted-price row market is unsupported")
            if report.market_coverage.get(market) is not True:
                raise IndustryImportError(f"adjusted-price capability does not prove {market} coverage")
            adjusted = raw.get("adjustedClose", raw.get("adjusted_close"))
            original_amount = raw.get("originalAmount", raw.get("original_amount", raw.get("amount")))
            for name, value in (("adjusted_close", adjusted), ("original_amount", original_amount)):
                if value is not None and not math.isfinite(float(value)):
                    raise IndustryImportError(f"{name} must be finite")
            security_id = str(raw.get("securityId", raw.get("security_id", "")))
            if not security_id:
                raise IndustryImportError("adjusted-price row security identity is required")
            if security_id in seen_security_ids:
                raise IndustryImportError(f"duplicate adjusted-price security identity: {security_id}")
            seen_security_ids.add(security_id)
            normalized.append(NormalizedPriceRow(
                security_id=security_id,
                as_of=row_date,
                market=market,
                adjusted_close=float(adjusted) if adjusted is not None else None,
                original_close=float(raw["originalClose"]) if raw.get("originalClose") is not None else None,
                original_amount=float(original_amount) if original_amount is not None else None,
                adjustment_revision=str(raw.get("adjustmentRevision", raw.get("adjustment_revision", self.revision))),
            ))
        if not normalized:
            raise IndustryImportError("adjusted-price input is empty")
        checksum = _checksum([asdict(row) for row in normalized])
        return NormalizedPriceResult(tuple(normalized), "ok", checksum)


class BaostockAdjustedPriceAdapter(ProviderNeutralAdjustedPriceAdapter):
    source = "baostock"
    revision = "baostock-adjusted-v1"


class MootdxAdjustedPriceAdapter(ProviderNeutralAdjustedPriceAdapter):
    source = "mootdx"
    revision = "mootdx-adjusted-v1"


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    benchmark_id: str
    as_of: date
    return_value: float
    eligible_count: int
    excluded_count: int
    checksum: str


class BenchmarkHistoryAdapter:
    """Build the fixed ordinary-A equal-weight benchmark from normalized rows."""

    benchmark_id = "ordinary-a-share-equal-weight-v1"
    source = "derived"
    revision = "ordinary-a-share-equal-weight-v1"

    def __init__(self, *, gate: IndustryCapabilityGate) -> None:
        self.gate = gate

    def aggregate(self, rows: Sequence[Mapping[str, Any]], *, as_of: date) -> BenchmarkResult:
        report = self.gate.require("benchmark-history", self.source, self.revision, as_of=as_of)
        if report.field_semantics.get("benchmark") != self.benchmark_id:
            raise IndustryImportError("benchmark capability identity is incompatible")
        if report.field_semantics.get("aggregation") != "equal-weight-valid-front-adjusted-returns":
            raise IndustryImportError("benchmark capability aggregation is incompatible")
        values: list[float] = []
        excluded = 0
        seen_security_ids: set[str] = set()
        for row in rows:
            if date.fromisoformat(str(row.get("asOf", row.get("as_of", "")))) != as_of:
                raise IndustryImportError("benchmark row date mismatch")
            security_id = str(row.get("securityId", row.get("security_id", "")))
            if security_id:
                if security_id in seen_security_ids:
                    raise IndustryImportError(f"duplicate benchmark security identity: {security_id}")
                seen_security_ids.add(security_id)
            current = row.get("adjustedClose", row.get("adjusted_close"))
            previous = row.get("previousAdjustedClose", row.get("previous_adjusted_close"))
            if current is None or previous in (None, 0):
                excluded += 1
                continue
            value = float(current) / float(previous) - 1.0
            if not math.isfinite(value):
                excluded += 1
                continue
            values.append(value)
        if not values:
            raise IndustryImportError("benchmark has no valid adjusted returns")
        result = sum(values) / len(values)
        checksum = _checksum({"asOf": as_of.isoformat(), "values": values})
        return BenchmarkResult(self.benchmark_id, as_of, result, len(values), excluded, checksum)


__all__ = [
    "BaostockAdjustedPriceAdapter",
    "BenchmarkHistoryAdapter",
    "BenchmarkResult",
    "CapabilityGateError",
    "IndustryCapabilityGate",
    "IndustryImportError",
    "MootdxAdjustedPriceAdapter",
    "NormalizedPriceResult",
    "NormalizedPriceRow",
    "OperatorImportResult",
    "ProviderNeutralAdjustedPriceAdapter",
    "ShenwanOperatorImportAdapter",
]
