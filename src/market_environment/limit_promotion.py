"""Strict, provider-free V1 promotion aggregation."""

from __future__ import annotations

import logging
import os
from datetime import date
from time import perf_counter
from typing import Any

from .schemas import PROMOTION_RULE_VERSION, PROMOTION_SAMPLE_RULE
from .snapshot_store import LIMIT_DETAIL_CHECKSUM_KEY
from .trading_sessions import TradingDayResolver

logger = logging.getLogger(__name__)

PROMOTION_FIELDS = (
    "todayPromoted",
    "yesterdayLimitUpEligible",
    "promotionRatio",
    "promotionSampleAsOf",
    "promotionPreviousAsOf",
    "promotionSampleRule",
    "promotionRuleVersion",
    "promotionQuality",
    "fieldQuality",
)


def limit_v1_enabled() -> bool:
    return os.getenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def without_promotion_fields(payload: dict[str, Any]) -> dict[str, Any]:
    for field in PROMOTION_FIELDS:
        payload.pop(field, None)
    return payload


def _metric_quality(
    status: str,
    reason: str,
    observations: int | None,
    as_of: date | None,
    source: str | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "observations": observations,
        "asOf": as_of.isoformat() if as_of else None,
        "source": source,
        "warnings": list(warnings or []),
    }


def _insufficient(
    as_of: date,
    *,
    reason: str,
    previous_as_of: date | None = None,
    source: str | None = None,
    numerator: int | None = None,
    denominator: int | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    observations = denominator
    current_quality = _metric_quality(
        "insufficient", reason, observations, as_of, source, warnings
    )
    previous_quality = _metric_quality(
        "insufficient", reason, observations, previous_as_of, source, warnings
    )
    return {
        "todayPromoted": numerator,
        "yesterdayLimitUpEligible": denominator,
        "promotionRatio": None,
        "promotionSampleAsOf": as_of.isoformat(),
        "promotionPreviousAsOf": previous_as_of.isoformat() if previous_as_of else None,
        "promotionSampleRule": PROMOTION_SAMPLE_RULE,
        "promotionRuleVersion": PROMOTION_RULE_VERSION,
        "promotionQuality": current_quality,
        "fieldQuality": {
            "todayPromoted": current_quality,
            "yesterdayLimitUpEligible": previous_quality,
            "promotionRatio": current_quality,
        },
    }


def build_limit_promotion(
    store: Any,
    as_of: date,
    *,
    dataset_quality: dict[str, Any] | None = None,
    emit_log: bool = True,
) -> dict[str, Any]:
    """Build V1 solely from two complete, checksummed local datasets."""

    started = perf_counter()
    resolution = TradingDayResolver(store).resolve(as_of)
    previous_as_of = resolution.previous_as_of
    if not resolution.sufficient or previous_as_of is None:
        result = _insufficient(
            as_of,
            reason=resolution.reason or "missing-session-evidence",
            previous_as_of=previous_as_of,
            warnings=list(resolution.warnings),
        )
        if emit_log:
            _log_promotion(as_of, previous_as_of, result, started)
        return result

    try:
        current_manifest = store.get_limit_security_dataset(as_of)
        previous_manifest = store.get_limit_security_dataset(previous_as_of)
        if current_manifest is None or previous_manifest is None:
            result = _insufficient(
                as_of,
                reason="missing-limit-security-dataset",
                previous_as_of=previous_as_of,
            )
            if emit_log:
                _log_promotion(as_of, previous_as_of, result, started)
            return result
        manifests = (previous_manifest, current_manifest)
        if any(
            not manifest["complete"]
            or manifest["actual_as_of"] != expected_date
            or manifest["rule_version"] != PROMOTION_RULE_VERSION
            for manifest, expected_date in zip(manifests, (previous_as_of, as_of), strict=True)
        ):
            warnings = [
                warning
                for manifest in manifests
                for warning in manifest.get("warnings", ())
            ]
            result = _insufficient(
                as_of,
                reason="incomplete-adjacent-session-sample",
                previous_as_of=previous_as_of,
                warnings=warnings,
            )
            if emit_log:
                _log_promotion(as_of, previous_as_of, result, started)
            return result

        current_snapshot = store.get("limits", as_of)
        previous_snapshot = store.get("limits", previous_as_of)
        snapshots = (previous_snapshot, current_snapshot)
        if any(
            snapshot is None
            or not isinstance(snapshot.payload.get("quality"), dict)
            or snapshot.payload["quality"].get(LIMIT_DETAIL_CHECKSUM_KEY)
            != manifest["dataset_checksum"]
            for snapshot, manifest in zip(snapshots, manifests, strict=True)
        ):
            result = _insufficient(
                as_of,
                reason="unbound-limit-aggregate",
                previous_as_of=previous_as_of,
                warnings=["limits aggregate is not bound to the normalized detail checksum"],
            )
            if emit_log:
                _log_promotion(as_of, previous_as_of, result, started)
            return result

        previous_facts = store.get_limit_security_facts(previous_as_of)
        current_facts = store.get_limit_security_facts(as_of)
        previous_eligible = {
            fact.security_id
            for fact in previous_facts
            if fact.pool_type == "limit_up" and fact.eligible and fact.closed_limit_up is True
        }
        current_closed = {
            fact.security_id
            for fact in current_facts
            if fact.pool_type == "limit_up" and fact.eligible and fact.closed_limit_up is True
        }
        denominator = len(previous_eligible)
        numerator = len(previous_eligible & current_closed)
        source = ",".join(
            dict.fromkeys((str(previous_manifest["source"]), str(current_manifest["source"])))
        )
        if denominator == 0:
            warning = "promotion ratio requires a non-zero eligible previous-session sample"
            result = _insufficient(
                as_of,
                reason="zero-denominator",
                previous_as_of=previous_as_of,
                source=source,
                numerator=0,
                denominator=0,
                warnings=[warning],
            )
            result["fieldQuality"]["todayPromoted"] = _metric_quality(
                "ok", "complete-empty-eligible-set", 0, as_of, source
            )
            result["fieldQuality"]["yesterdayLimitUpEligible"] = _metric_quality(
                "ok", "complete-empty-eligible-set", 0, previous_as_of, source
            )
            if emit_log:
                _log_promotion(as_of, previous_as_of, result, started, current_manifest, previous_manifest)
            return result

        degraded_warnings = list((dataset_quality or {}).get("warnings") or [])
        for snapshot_date, snapshot in zip((previous_as_of, as_of), snapshots, strict=True):
            if snapshot is None:
                continue
            if snapshot.status in {"fallback", "degraded"}:
                degraded_warnings.append(
                    f"{snapshot_date.isoformat()} limits snapshot status: {snapshot.status}"
                )
            if snapshot.refresh_warning:
                degraded_warnings.append(
                    f"{snapshot_date.isoformat()} retained snapshot: {snapshot.refresh_warning}"
                )
        degraded_warnings = list(dict.fromkeys(degraded_warnings))
        degraded = bool(
            dataset_quality
            and (
                dataset_quality.get("status") in {"fallback", "degraded"}
                or dataset_quality.get("cacheState") == "stale"
                or dataset_quality.get("refreshWarning")
            )
        ) or any(
            snapshot.status in {"fallback", "degraded"} or snapshot.refresh_warning
            for snapshot in snapshots
            if snapshot is not None
        )
        status = "degraded" if degraded else "ok"
        reason = "retained-or-fallback-adjacent-session-sample" if degraded else "complete-adjacent-session-sample"
        values = {
            "todayPromoted": numerator,
            "yesterdayLimitUpEligible": denominator,
            "promotionRatio": round(numerator / denominator, 4),
            "promotionSampleAsOf": as_of.isoformat(),
            "promotionPreviousAsOf": previous_as_of.isoformat(),
            "promotionSampleRule": PROMOTION_SAMPLE_RULE,
            "promotionRuleVersion": PROMOTION_RULE_VERSION,
            "promotionQuality": _metric_quality(
                status, reason, denominator, as_of, source, degraded_warnings
            ),
            "fieldQuality": {
                "todayPromoted": _metric_quality(
                    status,
                    "matched-close-limit-up-members",
                    denominator,
                    as_of,
                    source,
                    degraded_warnings,
                ),
                "yesterdayLimitUpEligible": _metric_quality(
                    status,
                    "complete-eligible-previous-session-set",
                    denominator,
                    previous_as_of,
                    source,
                    degraded_warnings,
                ),
                "promotionRatio": _metric_quality(
                    status,
                    "non-zero-complete-denominator",
                    denominator,
                    as_of,
                    source,
                    degraded_warnings,
                ),
            },
        }
        if emit_log:
            _log_promotion(as_of, previous_as_of, values, started, current_manifest, previous_manifest)
        return values
    except Exception as exc:
        result = _insufficient(
            as_of,
            reason="promotion-calculation-failed",
            previous_as_of=previous_as_of,
            warnings=[str(exc)],
        )
        result["promotionQuality"]["status"] = "failed"
        for quality in result["fieldQuality"].values():
            quality["status"] = "failed"
        if emit_log:
            _log_promotion(as_of, previous_as_of, result, started)
        return result


def _log_promotion(
    as_of: date,
    previous_as_of: date | None,
    result: dict[str, Any],
    started: float,
    current_manifest: dict[str, Any] | None = None,
    previous_manifest: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "limit promotion aggregation",
        extra={
            "event": "limit_promotion_aggregation",
            "sample_as_of": as_of.isoformat(),
            "previous_as_of": previous_as_of.isoformat() if previous_as_of else None,
            "rule_version": PROMOTION_RULE_VERSION,
            "quality_status": result["promotionQuality"]["status"],
            "quality_reason": result["promotionQuality"]["reason"],
            "eligible_count": result.get("yesterdayLimitUpEligible"),
            "matched_count": result.get("todayPromoted"),
            "current_excluded": current_manifest.get("excluded") if current_manifest else None,
            "previous_excluded": previous_manifest.get("excluded") if previous_manifest else None,
            "current_checksum": current_manifest.get("dataset_checksum") if current_manifest else None,
            "previous_checksum": previous_manifest.get("dataset_checksum") if previous_manifest else None,
            "join_ms": round((perf_counter() - started) * 1000, 3),
        },
    )


__all__ = [
    "PROMOTION_FIELDS",
    "build_limit_promotion",
    "limit_v1_enabled",
    "without_promotion_fields",
]
