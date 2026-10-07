"""Sector collector with Eastmoney-first and approved Fuyao fallback."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ...fuyao_market import FuyaoMarketAdapter
from ...provider_shadow import compare_shadow
from ...providers import MarketDataProvider
from ...refresh import SUCCESS_STATUSES, effective_market_date
from ...snapshot_store import (
    CollectionTaskRecord,
    LeaseToken,
    SnapshotRecord,
    SnapshotStore,
)


SECTOR_ENRICHMENT_FIELDS = ("f3", "f6", "f62", "f104", "f105", "f128", "f184")


class SectorsCollector:
    """Collect Eastmoney sectors, then capability-gated Fuyao plus enrichment."""

    dataset_id = "sectors"

    def __init__(
        self,
        provider: MarketDataProvider,
        store: SnapshotStore,
        *,
        market_now: Callable[[], datetime],
        is_settled: Callable[[date], bool],
        fuyao_adapter: FuyaoMarketAdapter,
        fuyao_is_enabled: Callable[[str], bool],
        fuyao_gate_warning: Callable[[str], str],
        fuyao_shadow_enabled: Callable[[str], bool],
        fuyao_revision: Callable[[str], str],
    ) -> None:
        self.provider = provider
        self.store = store
        self._market_now = market_now
        self._is_settled = is_settled
        self.fuyao_adapter = fuyao_adapter
        self._fuyao_is_enabled = fuyao_is_enabled
        self._fuyao_gate_warning = fuyao_gate_warning
        self._fuyao_shadow_enabled = fuyao_shadow_enabled
        self._fuyao_revision = fuyao_revision

    def collect_task(
        self,
        task: CollectionTaskRecord,
        started: float,
        lease: LeaseToken,
    ) -> CollectionTaskRecord:
        if task.dataset != self.dataset_id:
            raise ValueError(f"SectorsCollector cannot collect {task.dataset}")
        provider_started = time.perf_counter()
        primary_error: str | None = None
        try:
            payload = copy.deepcopy(self._fetch(task.as_of, use_fuyao=False))
            quality = self._validate_payload(task.as_of, payload)
            if str(quality.get("status")) not in SUCCESS_STATUSES:
                primary_error = str(
                    quality.get("warning")
                    or f"东方财富行业排名质量为 {quality.get('status')}"
                )
        except Exception as exc:
            primary_error = f"东方财富行业排名不可用：{exc}"

        fallback = primary_error is not None
        if fallback:
            if not self._fuyao_is_enabled(self.dataset_id):
                raise RuntimeError(
                    f"{primary_error}；{self._fuyao_gate_warning(self.dataset_id)}"
                )
            try:
                payload = copy.deepcopy(self._fetch(task.as_of, use_fuyao=True))
                quality = self._validate_payload(task.as_of, payload)
                if str(quality.get("status")) not in SUCCESS_STATUSES:
                    raise RuntimeError(
                        str(
                            quality.get("warning")
                            or f"扶摇行业结果质量为 {quality.get('status')}"
                        )
                    )
            except Exception as exc:
                raise RuntimeError(
                    f"{primary_error}；扶摇行业 fallback 不可用：{exc}"
                ) from exc
            warnings = [
                primary_error,
                *(str(value) for value in quality.get("warnings") or []),
                f"扶摇 capability revision: {self._fuyao_revision(self.dataset_id)}",
            ]
            self._merge_quality_warnings(quality, warnings)

            enrichment_eligible = (
                task.as_of == effective_market_date(self._market_now())
                and self._is_settled(task.as_of)
            )
            payload, quality = self._enrich_payload(
                payload,
                quality,
                task.as_of,
                eligible=enrichment_eligible,
            )

        provider_ms = self._milliseconds(provider_started)
        source = str(quality.get("source") or quality.get("provider") or "none")
        observations = int(quality.get("observations") or 0)
        quality_status = str(quality.get("status"))
        warning = str(quality.get("warning")) if quality.get("warning") else None
        if quality_status not in SUCCESS_STATUSES:
            raise RuntimeError(warning or f"sectors collection returned {quality_status}")
        settled = self._is_settled(task.as_of)
        self.store.put(
            SnapshotRecord(
                dataset=self.dataset_id,
                as_of=task.as_of,
                payload=payload,
                source=source,
                status=quality_status,
                observations=observations,
                warnings=tuple(str(value) for value in quality.get("warnings") or []),
                fetched_at=self._market_now(),
                settled=settled,
            ),
            lease=lease,
            now=self._market_now().astimezone(ZoneInfo("UTC")),
        )
        timings: dict[str, Any] = {
            "providerCollectionMs": provider_ms,
            "fuyaoFallback": fallback,
            "sourceRevision": quality.get("providerRevision"),
            "capabilityRevision": (
                self._fuyao_revision(self.dataset_id) if fallback else None
            ),
        }
        if fallback:
            timings["sectorEnrichment"] = copy.deepcopy(
                quality.get("sectorEnrichment") or {}
            )
            timings["eastmoneyFailure"] = primary_error
        shadow_warning: str | None = None
        if (
            not fallback
            and self._fuyao_shadow_enabled(self.dataset_id)
            and self._fuyao_is_enabled(self.dataset_id)
        ):
            try:
                candidate = self._fetch(task.as_of, use_fuyao=True)
                timings["shadow"] = compare_shadow(
                    self.dataset_id,
                    payload,
                    candidate,
                    formal_revision=str(quality.get("providerRevision") or source),
                    shadow_revision=self._fuyao_revision(self.dataset_id),
                    as_of=task.as_of,
                )
                shadow_status = timings["shadow"].get("status")
                if shadow_status not in {"match", "degraded"}:
                    shadow_warning = f"扶摇 shadow: {shadow_status}"
            except Exception as exc:
                timings["shadow"] = {
                    "dataset": self.dataset_id,
                    "status": "insufficient",
                    "warnings": [str(exc)],
                }
                shadow_warning = f"扶摇 shadow 不可用：{exc}"
        if shadow_warning:
            warning = "; ".join(
                value for value in (warning, shadow_warning) if value
            )
        return self.store.transition_collection_task(
            task.task_id,
            (
                "partial"
                if quality_status in {"partial", "fallback", "fallback-derived"}
                else "success"
            ),
            expected_statuses=("collecting",),
            source=source,
            observations=observations,
            warning=warning,
            timings=timings,
            completed_at=self._market_now(),
            duration_ms=self._milliseconds(started),
            settled=settled,
        )

    def _fetch(self, as_of: date, *, use_fuyao: bool) -> dict[str, Any]:
        if use_fuyao:
            return self.fuyao_adapter.fetch_sectors(as_of).as_dict()
        return self.provider.fetch_chapter01_sectors(
            as_of,
            allow_current_snapshot=True,
        )

    def _enrich_payload(
        self,
        payload: dict[str, Any],
        quality: dict[str, Any],
        as_of: date,
        *,
        eligible: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        current_as_of = effective_market_date(self._market_now())
        base_rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        base_quality = copy.deepcopy(quality)
        base_status = str(base_quality.get("status") or "fallback")
        enrich = getattr(self.provider, "enrich_fuyao_sectors", None)
        if not eligible:
            base_quality["sectorEnrichment"] = self._enrichment_summary(
                status="skipped",
                as_of=as_of,
                current_as_of=current_as_of,
                eligible=False,
                base_rows=len(base_rows),
                warning="东方财富 dataapi 行业字段补充仅允许当前上海交易日且结算后调用",
            )
            payload["quality"] = base_quality
            return payload, base_quality
        if not callable(enrich):
            base_quality["sectorEnrichment"] = self._enrichment_summary(
                status="disabled",
                as_of=as_of,
                current_as_of=current_as_of,
                eligible=True,
                base_rows=len(base_rows),
                warning="当前 provider 未启用东方财富 dataapi 行业字段补充",
            )
            payload["quality"] = base_quality
            return payload, base_quality
        try:
            candidate = enrich(
                copy.deepcopy(payload),
                as_of,
                eligible=True,
            )
            if not isinstance(candidate, dict):
                raise ValueError("sector enrichment returned a non-object payload")
            candidate_quality = self._validate_payload(as_of, candidate)
            if str(candidate_quality.get("status")) not in SUCCESS_STATUSES:
                raise ValueError(
                    str(
                        candidate_quality.get("warning")
                        or "sector enrichment returned an unusable quality status"
                    )
                )
            candidate_quality["status"] = base_status
            candidate_quality["source"] = base_quality.get(
                "source", candidate_quality.get("source")
            )
            candidate_quality["provider"] = base_quality.get(
                "provider", candidate_quality.get("provider")
            )
            candidate_quality["warnings"] = list(
                dict.fromkeys(
                    [
                        *(base_quality.get("warnings") or []),
                        *(candidate_quality.get("warnings") or []),
                    ]
                )
            )
            candidate_quality["warning"] = (
                "; ".join(str(value) for value in candidate_quality["warnings"])
                if candidate_quality["warnings"]
                else None
            )
            return candidate, candidate_quality
        except Exception as exc:
            base_quality["sectorEnrichment"] = self._enrichment_summary(
                status="failed",
                as_of=as_of,
                current_as_of=current_as_of,
                eligible=True,
                base_rows=len(base_rows),
                warning=f"东方财富 dataapi 行业字段补充失败：{exc}",
            )
            self._merge_quality_warnings(
                base_quality,
                [base_quality["sectorEnrichment"]["warnings"][0]],
            )
            payload["quality"] = base_quality
            return payload, base_quality

    @staticmethod
    def _enrichment_summary(
        *,
        status: str,
        as_of: date,
        current_as_of: date,
        eligible: bool,
        base_rows: int,
        warning: str | None = None,
    ) -> dict[str, Any]:
        warnings = [warning] if warning else []
        return {
            "status": status,
            "source": "eastmoney-dataapi",
            "provider": "eastmoney",
            "sameVendor": True,
            "endpoint": "https://data.eastmoney.com/dataapi/bkzj/getbkzj",
            "requestedFields": list(SECTOR_ENRICHMENT_FIELDS),
            "mappingRevision": None,
            "matchMethod": None,
            "sourceRows": 0,
            "baseRows": base_rows,
            "matchedRows": 0,
            "unmatchedRows": base_rows,
            "identityCoverage": 0.0 if base_rows else None,
            "fieldCoverage": {},
            "dateEvidence": {
                "requested": as_of.isoformat(),
                "current": current_as_of.isoformat(),
                "eligible": eligible,
                "settled": eligible,
                "reason": warning or "未请求东方财富 dataapi 行业字段补充",
            },
            "warnings": warnings,
        }

    @staticmethod
    def _merge_quality_warnings(
        quality: dict[str, Any],
        warnings: Iterable[str],
    ) -> None:
        merged = list(
            dict.fromkeys(
                [
                    *(quality.get("warnings") or []),
                    *(str(value) for value in warnings if value),
                ]
            )
        )
        quality["warnings"] = merged
        quality["warning"] = "; ".join(merged) if merged else None

    @staticmethod
    def _validate_payload(as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("sectors collection returned a non-object payload")
        quality = payload.get("quality")
        if not isinstance(quality, dict):
            raise ValueError("sectors collection payload is missing quality")
        quality_as_of = quality.get("asOf")
        if quality_as_of is not None and quality_as_of != as_of.isoformat():
            raise ValueError(
                f"sectors collection returned mismatched asOf {quality_as_of}"
            )
        return quality

    @staticmethod
    def _milliseconds(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["SECTOR_ENRICHMENT_FIELDS", "SectorsCollector"]
