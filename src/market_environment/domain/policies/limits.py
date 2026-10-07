"""Pure quality-layering policies for the limit ecosystem."""

from __future__ import annotations

from typing import Any


def apply_promotion_quality_layer(value: dict[str, Any]) -> dict[str, Any]:
    promotion_quality = value.get("promotionQuality")
    if not isinstance(promotion_quality, dict):
        return value
    if promotion_quality.get("status") != "degraded":
        return value
    quality = value.get("quality")
    if not isinstance(quality, dict):
        return value
    quality["status"] = "degraded"
    warnings = list(
        dict.fromkeys(
            [
                *(quality.get("warnings") or []),
                *(promotion_quality.get("warnings") or []),
            ]
        )
    )
    quality["warnings"] = warnings
    quality["warning"] = "；".join(warnings) if warnings else quality.get("warning")
    return value


__all__ = ["apply_promotion_quality_layer"]
