"""Cross-Skill report interface for QTS-04 STEP 1.

Identity rules are shared through ``qts04-core``; the STEP 1 specific part is
``build_config``, which freezes the industry weights and thresholds that
actually participated in the decision.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

_HERE = Path(__file__).resolve().parent
_CORE = _HERE.parents[1] / "qts04-core" / "scripts"
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from qts04.contract import (  # noqa: E402
    canonical_payload as _canonical_payload,
    compute_report_id as _compute_report_id,
    require_schema_version as _require_schema_version,
)
from predicate import (  # noqa: E402
    CONFIRMATION_CLOSE_MULTIPLIER,
    CONFIRMATION_HORIZON_DAYS,
    CONFIRMATION_TURNOVER_MULTIPLIER,
    INVALIDATION_CLOSE_MULTIPLIER,
    INVALIDATION_HORIZON_DAYS,
    INVALIDATION_TURNOVER_MULTIPLIER,
)
from scoring import (  # noqa: E402
    BROAD_ADVANCE_RATIO,
    CONFIDENCE_HIGH_COVERAGE,
    CONFIDENCE_LOW_COVERAGE,
    CONFIDENCE_MEDIUM_COVERAGE,
    FOCUS_PERSISTENCE_SCORE,
    FOCUS_TOTAL_SCORE,
    FULL_WINDOW,
    MIN_BREADTH_COVERAGE,
    MIN_OBSERVATIONS,
    RELATIVE_STRENGTH_20_WINDOW,
    RELATIVE_STRENGTH_5_WINDOW,
    RULE_WEIGHTS,
    STRENGTH_TURNOVER_RATIO,
    TURNOVER_WINDOW,
    WATCH_TOTAL_SCORE,
)

SCHEMA_VERSION = "1.0"
REPORT_ID_LENGTH = 16
REPORT_ID_FIELDS = ("schemaVersion", "asOf", "benchmark", "config", "directions")
VOLATILE_FIELDS = ("generatedAt", "providerCalls", "cacheState", "credentialSource")


def _multiplier_change(multiplier: float) -> float:
    return round(float(multiplier) - 1.0, 6)


def build_config(breadth_universe: int) -> dict[str, Any]:
    """Freeze every threshold used for this run."""

    return {
        "weights": {rule_id: weight for rule_id, _name, weight in RULE_WEIGHTS},
        "percentileTiers": {
            "boundaries": [0.20, 0.40, 0.60, 0.80],
            "scores": [0, 25, 50, 75, 100],
        },
        "minObservations": MIN_OBSERVATIONS,
        "fullWindow": FULL_WINDOW,
        "ruleWindows": {
            "relativeStrength5": RELATIVE_STRENGTH_5_WINDOW,
            "relativeStrength20": RELATIVE_STRENGTH_20_WINDOW,
            "turnover": TURNOVER_WINDOW,
        },
        "minBreadthCoverage": MIN_BREADTH_COVERAGE,
        "breadthUniverse": int(breadth_universe),
        "quadrant": {
            "strengthTurnoverRatio": STRENGTH_TURNOVER_RATIO,
            "broadAdvanceRatio": BROAD_ADVANCE_RATIO,
        },
        "pool": {
            "focusTotalScore": FOCUS_TOTAL_SCORE,
            "focusPersistenceScore": FOCUS_PERSISTENCE_SCORE,
            "watchTotalScore": WATCH_TOTAL_SCORE,
        },
        "confidenceCoverage": {
            "high": CONFIDENCE_HIGH_COVERAGE,
            "medium": CONFIDENCE_MEDIUM_COVERAGE,
            "low": CONFIDENCE_LOW_COVERAGE,
        },
        "confirmation": {
            "horizonDays": CONFIRMATION_HORIZON_DAYS,
            "closeMultiplier": CONFIRMATION_CLOSE_MULTIPLIER,
            "closeChange": _multiplier_change(CONFIRMATION_CLOSE_MULTIPLIER),
            "turnoverMultiplier": CONFIRMATION_TURNOVER_MULTIPLIER,
        },
        "invalidation": {
            "horizonDays": INVALIDATION_HORIZON_DAYS,
            "closeMultiplier": INVALIDATION_CLOSE_MULTIPLIER,
            "closeChange": _multiplier_change(INVALIDATION_CLOSE_MULTIPLIER),
            "turnoverMultiplier": INVALIDATION_TURNOVER_MULTIPLIER,
        },
    }


def canonical_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    return _canonical_payload(result, REPORT_ID_FIELDS)


def compute_report_id(result: Mapping[str, Any]) -> str:
    return _compute_report_id(result, REPORT_ID_FIELDS)


def attach_interface(result: dict[str, Any], breadth_universe: int) -> dict[str, Any]:
    result["schemaVersion"] = SCHEMA_VERSION
    result["config"] = build_config(breadth_universe)
    result["reportId"] = compute_report_id(result)
    return result


def require_schema_version(payload: Mapping[str, Any]) -> str:
    return _require_schema_version(payload, supported=SCHEMA_VERSION)
