"""Validate and transactionally promote one provider capability report."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from ...domain.models.capability import ProviderCapabilityReport, redact
from ...domain.policies.capability import (
    CapabilityEvidenceError,
    CapabilityEvidencePolicy,
    CapabilityEvidencePolicyKey,
    capability_evidence_policies,
)
from ..ports import MarketEnvironmentUnitOfWork


_REPORT_KEYS = frozenset(
    {
        "provider",
        "dataset",
        "revision",
        "status",
        "endpoint",
        "field_coverage",
        "date_evidence",
        "history_window",
        "pagination_evidence",
        "permission_evidence",
        "rate_limit_evidence",
        "sample_count",
        "warnings",
        "missing_evidence",
        "checked_at",
        "schema_version",
        "checksum",
    }
)


class CapabilityPromotionError(RuntimeError):
    """Base error safe to show in operator-facing promotion output."""


class CapabilityPromotionValidationError(CapabilityPromotionError):
    """The selected input does not satisfy promotion requirements."""


class CapabilityPromotionConflictError(CapabilityPromotionError):
    """The immutable revision already has different evidence."""


class CapabilityPromotionRepositoryError(CapabilityPromotionError):
    """A storage operation failed without exposing backend details."""


@dataclass(frozen=True, slots=True)
class CapabilityPromotionResult:
    provider: str
    dataset: str
    revision: str
    status: str
    checksum: str
    target_backend: str
    mode: str
    conflict_state: str
    result: str

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "dataset": self.dataset,
            "revision": self.revision,
            "status": self.status,
            "checksum": self.checksum,
            "targetBackend": self.target_backend,
            "mode": self.mode,
            "conflictState": self.conflict_state,
            "result": self.result,
        }


@dataclass(frozen=True, slots=True)
class PromoteCapabilityReportCommand:
    unit_of_work_factory: Callable[[], MarketEnvironmentUnitOfWork]
    evidence_policies: Mapping[
        CapabilityEvidencePolicyKey, CapabilityEvidencePolicy
    ] | None = None

    def execute(
        self,
        envelope: Mapping[str, Any],
        *,
        provider: str,
        dataset: str,
        revision: str,
        target_backend: str,
        apply: bool = False,
    ) -> CapabilityPromotionResult:
        report = self._validate_and_select(
            envelope,
            provider=provider,
            dataset=dataset,
            revision=revision,
        )
        try:
            with self.unit_of_work_factory() as unit_of_work:
                existing = unit_of_work.provider_capabilities.get_capability(
                    provider,
                    dataset,
                    revision,
                )
                existing_checksum = (
                    str(existing.get("checksum", ""))
                    if existing is not None
                    else None
                )
                if (
                    existing_checksum is not None
                    and existing_checksum != report.checksum
                ):
                    raise CapabilityPromotionConflictError(
                        "capability revision already exists with different evidence"
                    )
                conflict_state = "identical" if existing_checksum else "absent"
                if not apply:
                    unit_of_work.rollback()
                    result = "validated"
                elif existing_checksum:
                    unit_of_work.rollback()
                    result = "idempotent"
                else:
                    write_result = unit_of_work.provider_capabilities.put_capability(
                        report.to_dict()
                    )
                    if write_result == "conflict":
                        raise CapabilityPromotionConflictError(
                            "capability revision already exists with different evidence"
                        )
                    if write_result == "identical":
                        unit_of_work.rollback()
                        conflict_state = "identical"
                        result = "idempotent"
                    elif write_result == "inserted":
                        unit_of_work.commit()
                        result = "applied"
                    else:
                        raise RuntimeError(
                            "capability repository returned an unsupported write result"
                        )
        except CapabilityPromotionConflictError:
            raise
        except Exception as exc:
            raise CapabilityPromotionRepositoryError(
                "capability repository operation failed"
            ) from exc

        return CapabilityPromotionResult(
            provider=report.provider,
            dataset=report.dataset,
            revision=report.revision,
            status=report.status,
            checksum=report.checksum,
            target_backend=target_backend,
            mode="apply" if apply else "dry-run",
            conflict_state=conflict_state,
            result=result,
        )

    def _validate_and_select(
        self,
        envelope: Mapping[str, Any],
        *,
        provider: str,
        dataset: str,
        revision: str,
    ) -> ProviderCapabilityReport:
        if not all(value.strip() for value in (provider, dataset, revision)):
            raise CapabilityPromotionValidationError(
                "provider, dataset, and revision selectors are required"
            )
        if not isinstance(envelope, Mapping):
            raise CapabilityPromotionValidationError(
                "capability input must be a JSON object"
            )
        if envelope.get("provider") != provider:
            raise CapabilityPromotionValidationError(
                "capability envelope provider does not match selector"
            )
        try:
            envelope_as_of = date.fromisoformat(str(envelope["asOf"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise CapabilityPromotionValidationError(
                "capability envelope asOf must be an ISO date"
            ) from exc

        raw_reports = envelope.get("reports")
        if (
            not isinstance(raw_reports, Sequence)
            or isinstance(raw_reports, (str, bytes))
        ):
            raise CapabilityPromotionValidationError(
                "capability envelope reports must be an array"
            )
        matches = [
            item
            for item in raw_reports
            if isinstance(item, Mapping)
            and item.get("provider") == provider
            and item.get("dataset") == dataset
            and item.get("revision") == revision
        ]
        if len(matches) != 1:
            raise CapabilityPromotionValidationError(
                "capability selector must match exactly one report"
            )
        raw_report = dict(matches[0])
        if set(raw_report) != _REPORT_KEYS:
            raise CapabilityPromotionValidationError(
                "capability report structure is incomplete or unsupported"
            )
        if not isinstance(raw_report.get("checksum"), str) or not raw_report[
            "checksum"
        ].strip():
            raise CapabilityPromotionValidationError(
                "capability report checksum is required"
            )

        # Integrity is checked against the original evidence before any
        # redaction comparison, so a sanitized copy can never acquire a new
        # checksum during promotion.
        try:
            report = ProviderCapabilityReport.from_dict(raw_report)
        except (TypeError, ValueError) as exc:
            raise CapabilityPromotionValidationError(
                "capability report checksum or structure is invalid"
            ) from exc
        if (
            report.provider != provider
            or report.dataset != dataset
            or report.revision != revision
        ):
            raise CapabilityPromotionValidationError(
                "capability report identity does not match selector"
            )
        if redact(raw_report) != raw_report:
            raise CapabilityPromotionValidationError(
                "capability report contains sensitive material"
            )
        if report.status != "eligible":
            raise CapabilityPromotionValidationError(
                "capability report status must be eligible"
            )
        if report.sample_count < 1:
            raise CapabilityPromotionValidationError(
                "capability report must contain observations"
            )
        if not isinstance(report.endpoint, str) or not report.endpoint.strip():
            raise CapabilityPromotionValidationError(
                "capability endpoint evidence is incomplete"
            )
        for name, evidence in (
            ("field", report.field_coverage),
            ("date", report.date_evidence),
            ("permission", report.permission_evidence),
            ("rate-limit", report.rate_limit_evidence),
        ):
            if not isinstance(evidence, Mapping) or not evidence:
                raise CapabilityPromotionValidationError(
                    f"capability {name} evidence is incomplete"
                )

        policies = self.evidence_policies or capability_evidence_policies()
        policy = policies.get((provider, dataset, revision))
        if policy is None:
            raise CapabilityPromotionValidationError(
                "capability evidence policy is not registered"
            )
        try:
            policy(report, envelope_as_of)
        except CapabilityEvidenceError as exc:
            raise CapabilityPromotionValidationError(str(exc)) from exc
        return report


__all__ = [
    "CapabilityPromotionConflictError",
    "CapabilityPromotionError",
    "CapabilityPromotionResult",
    "CapabilityPromotionRepositoryError",
    "CapabilityPromotionValidationError",
    "PromoteCapabilityReportCommand",
]
