"""Common scaffolding for static-HTML sectors adapters.

Two adapters (``sectors-sina-html`` and ``sectors-xueqiu-html``) share:

* the SourceAdapter protocol shape (``source_id``, ``capability``, ``acquire``),
* the DriftDetector contract that decides whether the page is in shape,
* the forbid-promotion-to-supplementary-fields rule: ``mainNet``,
  ``mainNetPct``, ``upCount`` and ``downCount`` always emit ``None`` with a
  structured ``dom-source-unsupported:<field>`` warning,
* the field-authority rule that the ``leader`` field MUST be a display
  string and MUST NOT be a numeric badge or an identifier.

The subclasses declare the host, the capability revision, and the DOM
mapping; the base class owns gate checks, the transport-bound fetch, the
fallback normalization, and the structured failure shape used by every
other sector adapter in ``sectors_acquisition``.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

from ....application.ports import SourceAdapter, SourceCapability, SourceRequest
from ....domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    AcquisitionTimings,
    CollectionCandidate,
    RedactedProvenance,
)
from ..provenance import redact_provenance
from ..sectors_acquisition import _normalize_payload
from .drift import DriftDetector
from .fixture_loader import HostFixture
from .selectors import parse_cards
from .text_normalize import is_leader_text, normalize_text


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _timings_ms(started: float) -> AcquisitionTimings:
    return AcquisitionTimings(
        total_ms=round((time.perf_counter() - started) * 1000, 3)
    )


def _replace_attrs(
    provenance: RedactedProvenance, attrs: Mapping[str, object]
) -> RedactedProvenance:
    merged: dict[str, object] = dict(provenance.attributes)
    merged.update(dict(attrs))
    return RedactedProvenance(
        endpoint=provenance.endpoint,
        engine=provenance.engine,
        attributes=merged,
    )


@dataclass(frozen=True, slots=True)
class HtmlAdapterRow:
    code: str
    name: str
    change_pct: float
    amount: float
    leader: str | None
    provenance_attrs: Mapping[str, object] = field(default_factory=dict)


class StaticHtmlTransportError(Exception):
    """Raised when the engine classifies a request as a non-retryable failure."""

    def __init__(
        self,
        *,
        category: AcquisitionFailureCategory,
        signal: str,
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.category = category
        self.signal = signal
        self.reason = reason


class StaticHtmlSectorAdapter(SourceAdapter):
    """Common scaffolding for static-HTML sectors adapters.

    Plain class (not a ``@dataclass``) so subclasses can override
    ``source_id`` and ``capability`` safely through ``__init_subclass__``.
    """

    HOST_ID: ClassVar[str] = ""
    HOST_LABEL: ClassVar[str] = ""
    CAPABILITY_REVISION: ClassVar[str] = ""
    SUPPORTED_FIELDS: ClassVar[tuple[str, ...]] = (
        "code",
        "name",
        "changePct",
        "amount",
        "leader",
    )
    FORBIDDEN_FIELDS: ClassVar[tuple[str, ...]] = (
        "mainNet",
        "mainNetPct",
        "upCount",
        "downCount",
    )

    source_id: ClassVar[str] = ""
    capability: ClassVar[SourceCapability]
    _fetch_override: Any = None
    _gate_predicate: Any = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for required in ("HOST_ID", "CAPABILITY_REVISION"):
            if not getattr(cls, required, None):
                raise TypeError(f"{cls.__name__} must declare {required}")
        source_id = f"sectors-{cls.HOST_ID}-html"
        cls.source_id = source_id
        cls.capability = SourceCapability(
            source_id=source_id,
            provider=cls.HOST_ID,
            revision=cls.CAPABILITY_REVISION,
            supports_historical=False,
            latest_only=True,
            supported_fields=cls.SUPPORTED_FIELDS,
            available=True,
        )

    def __init__(self) -> None:
        self._fetch_override = None
        self._gate_predicate = lambda _req: False

    # Subclass hooks
    def extract_rows(
        self, page_html: str, *, fixture: HostFixture
    ) -> list[HtmlAdapterRow]:
        raise NotImplementedError

    def expected_endpoint(self) -> str:
        return f"https://{self.HOST_LABEL}/"

    # Test seams
    def set_fetch_override(self, fn: Any) -> None:
        self._fetch_override = fn

    def set_gate_predicate(self, fn: Any) -> None:
        self._gate_predicate = fn

    # Capability-gate decision: policy lives in
    # ``provider_capability.CapabilityPolicy``; this is the runtime check.
    def gate_open(self, request: SourceRequest) -> bool:
        if self._gate_predicate is None:
            return False
        return bool(self._gate_predicate(request))

    def fetch_page(self, request: SourceRequest) -> str:
        if self._fetch_override is None:
            raise RuntimeError(
                "static HTML adapter requires a transport override"
            )
        return self._fetch_override(request)

    def acquire(
        self, request: SourceRequest
    ) -> CollectionCandidate | AcquisitionFailure:
        started = time.perf_counter()
        fetched_at = _utc_now()
        base_provenance = RedactedProvenance(
            endpoint=self.expected_endpoint(),
            engine="scrapling",
            attributes={"dateEvidenceKind": "latest-only"},
        )

        if request.identity.dataset != "sectors":
            return self._fail(
                request,
                base_provenance,
                AcquisitionFailureCategory.CONFIGURATION,
                f"{self.source_id} cannot collect {request.identity.dataset}",
                fetched_at=fetched_at,
                timings=_timings_ms(started),
            )
        if request.source_id != self.source_id:
            return self._fail(
                request,
                base_provenance,
                AcquisitionFailureCategory.CONFIGURATION,
                f"source request {request.source_id} does not match adapter {self.source_id}",
                fetched_at=fetched_at,
                timings=_timings_ms(started),
            )
        if (
            self.capability.latest_only
            and request.current_market_date != request.identity.as_of
        ):
            return self._fail(
                request,
                _replace_attrs(base_provenance, {"dateEvidenceKind": "latest-only"}),
                AcquisitionFailureCategory.DATE_MISMATCH,
                "该数据源仅提供最新市场快照，历史日期不使用当前数据回填",
                fetched_at=fetched_at,
                timings=_timings_ms(started),
            )
        if not self.gate_open(request):
            return self._fail(
                request,
                _replace_attrs(
                    base_provenance, {"report-missing-or-not-eligible": True}
                ),
                AcquisitionFailureCategory.CONFIGURATION,
                f"{self.source_id} capability gate is not satisfied",
                fetched_at=fetched_at,
                timings=_timings_ms(started),
            )

        try:
            page_html = self.fetch_page(request)
        except StaticHtmlTransportError as exc:
            return self._fail(
                request,
                _replace_attrs(
                    base_provenance, {"host-classification": exc.signal}
                ),
                exc.category,
                exc.reason,
                fetched_at=fetched_at,
                timings=_timings_ms(started),
            )
        except Exception as exc:  # pragma: no cover - defensive
            return self._fail(
                request,
                base_provenance,
                AcquisitionFailureCategory.NETWORK,
                str(exc) or type(exc).__name__,
                fetched_at=fetched_at,
                timings=_timings_ms(started),
            )

        fixture_payload = request.params.get("fixture")
        if not isinstance(fixture_payload, HostFixture):
            return self._fail(
                request,
                base_provenance,
                AcquisitionFailureCategory.CONFIGURATION,
                "static HTML adapter requires an injected fixture",
                fetched_at=fetched_at,
                timings=_timings_ms(started),
            )

        parsed_rows = parse_cards(page_html)
        detector = DriftDetector(fixture_payload.footprint)
        signals = detector.drift_signals(parsed_rows)
        if signals:
            return self._fail(
                request,
                _replace_attrs(base_provenance, {"drift-signals": list(signals)}),
                AcquisitionFailureCategory.CONTRACT,
                f"dom-drift: {', '.join(signals)}",
                fetched_at=fetched_at,
                timings=_timings_ms(started),
            )

        try:
            typed_rows = self.extract_rows(page_html, fixture=fixture_payload)
        except ValueError as exc:
            return self._fail(
                request,
                base_provenance,
                AcquisitionFailureCategory.CONTRACT,
                f"row-extraction-error: {exc}",
                fetched_at=fetched_at,
                timings=_timings_ms(started),
            )

        return self._emit_candidate(
            request,
            typed_rows,
            base_provenance=base_provenance,
            fetched_at=fetched_at,
            timings=_timings_ms(started),
        )

    def _emit_candidate(
        self,
        request: SourceRequest,
        rows: list[HtmlAdapterRow],
        *,
        base_provenance: RedactedProvenance,
        fetched_at: datetime,
        timings: AcquisitionTimings,
    ) -> CollectionCandidate | AcquisitionFailure:
        payload_rows: list[dict[str, object]] = []
        warnings: list[str] = []
        identifier_drops = 0
        for index, row in enumerate(rows, start=1):
            if row.provenance_attrs.get("leader-identifier-not-name"):
                identifier_drops += 1
            payload_rows.append(
                {
                    "rank": index,
                    "code": row.code,
                    "name": row.name,
                    "changePct": row.change_pct,
                    "amount": row.amount,
                    "mainNet": None,
                    "mainNetPct": None,
                    "upCount": None,
                    "downCount": None,
                    "leader": row.leader,
                }
            )
        for field_name in self.FORBIDDEN_FIELDS:
            warnings.append(f"dom-source-unsupported:{field_name}")
        if identifier_drops:
            warnings.append("leader-identifier-not-name")
        payload = {
            "rows": payload_rows,
            "quality": {
                "status": "fallback",
                "dataset": "industry-ranking",
                "source": self.HOST_ID,
                "asOf": request.identity.as_of.isoformat(),
                "warning": "，".join(warnings),
                "warnings": tuple(warnings),
            },
        }
        return _normalize_payload(
            payload,
            request,
            self.capability,
            fetched_at=fetched_at,
            timings=timings,
            provenance=base_provenance,
            source_override=self.HOST_ID,
            provider_override=self.HOST_ID,
            revision_override=self.capability.revision,
        )

    def _fail(
        self,
        request: SourceRequest,
        provenance: RedactedProvenance,
        category: AcquisitionFailureCategory,
        message: str,
        *,
        fetched_at: datetime,
        timings: AcquisitionTimings,
    ) -> AcquisitionFailure:
        return AcquisitionFailure(
            category=category,
            message=message,
            retryable=False,
            source=self.source_id,
            source_revision=self.capability.revision,
            requested_as_of=request.identity.as_of,
            fetched_at=fetched_at,
            timings=timings,
            provenance=redact_provenance(provenance),
        )


def normalize_pct(text: str | None) -> float:
    """Parse a percentage cell; accepts ``+`` / ``%`` / ``-`` decorations."""
    if text is None:
        raise ValueError("empty percentage")
    candidate = normalize_text(text).replace("%", "").replace("+", "")
    candidate = candidate.replace(",", "")
    return float(candidate)


def normalize_money_to_yuan(text: str | None) -> float:
    """Parse a turnover cell.

    Operators capturing live fixtures rewrite the unit at capture time. The
    adapter intentionally refuses any unit inference here; tests assert that
    pages exposing ``元`` vs ``万元`` are returned verbatim and that the
    provider-side unit normalisation is the responsibility of the fixture
    capture step.
    """
    if text is None:
        raise ValueError("empty amount")
    import re as _re
    candidate = normalize_text(text).replace(",", "")
    match = _re.search(r"-?\d+(?:\.\d+)?", candidate)
    if not match:
        raise ValueError(f"no numeric amount in: {text!r}")
    return float(match.group(0))


def ensure_leader_text(value: str | None) -> str | None:
    """Return the leader display string or None if the value is not a name."""
    if not is_leader_text(value):
        return None
    return normalize_text(value)


__all__ = [
    "HtmlAdapterRow",
    "StaticHtmlSectorAdapter",
    "StaticHtmlTransportError",
    "ensure_leader_text",
    "normalize_money_to_yuan",
    "normalize_pct",
]
