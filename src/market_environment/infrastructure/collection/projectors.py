"""Provider-free local detail projectors for collection status."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ...application.collection import DatasetDetailProjectorRegistry
from ...domain.models import DATASET_IDS, CollectionCandidate, DatasetDate
from ...limit_promotion import build_limit_promotion, limit_v1_enabled
from ...trading_sessions import TradingDayResolver


@dataclass(frozen=True, slots=True)
class EmptyDatasetDetailProjector:
    dataset_id: str

    def project(
        self,
        identity: DatasetDate,
        candidate: CollectionCandidate | None,
    ) -> None:
        if identity.dataset != self.dataset_id:
            raise ValueError(
                f"detail projector {self.dataset_id} cannot project {identity.dataset}"
            )
        return None


@dataclass(frozen=True, slots=True)
class LimitsDetailProjector:
    store: Any
    enabled: bool | Callable[[], bool] = limit_v1_enabled
    dataset_id: str = "limits"

    def project(
        self,
        identity: DatasetDate,
        candidate: CollectionCandidate | None,
    ) -> Mapping[str, Any]:
        if identity.dataset != self.dataset_id:
            raise ValueError(
                f"detail projector {self.dataset_id} cannot project {identity.dataset}"
            )
        detail_enabled = self.enabled() if callable(self.enabled) else bool(self.enabled)
        resolution = TradingDayResolver(self.store).resolve(identity.as_of)
        if candidate is None:
            return {
                "sampleAsOf": identity.as_of.isoformat(),
                "previousAsOf": (
                    resolution.previous_as_of.isoformat()
                    if resolution.previous_as_of
                    else None
                ),
                "excludedCount": None,
                "promotionRequired": detail_enabled,
                "promotionDependency": (
                    "前一真实交易日合资格收盘涨停样本 + 当前日同身份收盘涨停状态"
                ),
                "warnings": [resolution.reason] if resolution.reason else [],
            }

        payload = candidate.payload
        quality = payload.get("quality") if isinstance(payload.get("quality"), Mapping) else {}
        manifest = self.store.get_limit_security_dataset(identity.as_of)
        previous_as_of = payload.get("promotionPreviousAsOf") or (
            resolution.previous_as_of.isoformat() if resolution.previous_as_of else None
        )
        promotion_quality = payload.get("promotionQuality")
        promotion_status = (
            promotion_quality.get("status")
            if isinstance(promotion_quality, Mapping)
            else None
        )
        promotion_warnings: list[str] = []
        if detail_enabled and manifest is not None:
            try:
                promotion = build_limit_promotion(
                    self.store,
                    identity.as_of,
                    dataset_quality=quality,
                    emit_log=False,
                )
                calculated = promotion.get("promotionQuality")
                if isinstance(calculated, Mapping):
                    promotion_status = calculated.get("status")
                    promotion_warnings = [str(value) for value in calculated.get("warnings") or ()]
            except Exception as exc:
                promotion_warnings = [str(exc)]
        return {
            "sampleAsOf": payload.get("promotionSampleAsOf") or identity.as_of.isoformat(),
            "previousAsOf": previous_as_of,
            "excludedCount": manifest.get("excluded") if manifest else None,
            "promotionRequired": detail_enabled,
            "promotionDependency": (
                "前一真实交易日合资格收盘涨停样本 + 当前日同身份收盘涨停状态"
            ),
            "promotionQuality": promotion_status,
            "detailChecksum": quality.get("_detailDatasetChecksum"),
            "warnings": list(
                dict.fromkeys(
                    [
                        *(str(value) for value in quality.get("warnings") or ()),
                        *promotion_warnings,
                    ]
                )
            ),
        }


def build_local_detail_projector_registry(
    store: Any,
    *,
    limits_enabled: bool | Callable[[], bool] | None = None,
) -> DatasetDetailProjectorRegistry:
    setting: bool | Callable[[], bool] = (
        limit_v1_enabled if limits_enabled is None else limits_enabled
    )
    return DatasetDetailProjectorRegistry.complete(
        LimitsDetailProjector(store, setting)
        if dataset_id == "limits"
        else EmptyDatasetDetailProjector(dataset_id)
        for dataset_id in DATASET_IDS
    )


__all__ = [
    "EmptyDatasetDetailProjector",
    "LimitsDetailProjector",
    "build_local_detail_projector_registry",
]
