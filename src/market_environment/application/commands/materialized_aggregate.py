"""Materialized aggregate composition and conflict-safe rebuild services."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from time import perf_counter
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MaterializedAggregateComposer:
    repository: Any
    market_now: Callable[[], Any]
    snapshot_ttl_seconds: int
    chapter_group_keys: Mapping[str, tuple[str, ...]]
    local_core_context: Callable[[date, dict[str, Any]], dict[str, Any]]
    missing_chapter_provider_data: Callable[..., dict[str, Any]]
    snapshot_payload: Callable[..., dict[str, Any]]
    cache_state: Callable[..., str]
    limit_payload_for_response: Callable[[date, dict[str, Any]], dict[str, Any]]
    build_chapter01: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    core_payload: Callable[[dict[str, Any]], dict[str, Any]]
    validate_response: Callable[[dict[str, Any]], dict[str, Any]]
    limits_snapshot_state: Callable[[Any], Any]
    record_factory: Callable[[date, dict[str, Any], Any], Any]
    storage_schema_version: int
    schema_version_key: str
    limits_state_key: str
    component_revision_key: str

    def compose(
        self,
        as_of: date,
        revision: str,
    ) -> tuple[dict[str, Any], Any] | None:
        if self.repository is None:
            raise RuntimeError("persistent snapshot store is disabled")
        core_record = self.repository.get("core", as_of)
        if core_record is None:
            return None
        core_payload = copy.deepcopy(core_record.payload)
        core = self.local_core_context(as_of, core_payload)
        provider_data = self.missing_chapter_provider_data(
            core["effectiveDate"],
            "该日期尚未采集对应数据集",
            status="missing",
        )
        limits_record = None
        for group in self.chapter_group_keys:
            record = self.repository.get(group, as_of)
            if record is None:
                continue
            if group == "limits":
                limits_record = record
            provider_data[group] = self.snapshot_payload(
                record,
                self.cache_state(
                    record,
                    now=self.market_now(),
                    soft_ttl_seconds=self.snapshot_ttl_seconds,
                ),
                refreshing=False,
            )
        provider_data["limits"] = self.limit_payload_for_response(
            as_of,
            provider_data["limits"],
        )
        chapter = self.build_chapter01(core, provider_data)
        payload = self.core_payload(core)
        payload["chapter01"] = chapter
        validated = self.validate_response(payload)
        stored_payload = {
            **validated,
            self.schema_version_key: self.storage_schema_version,
            self.limits_state_key: self.limits_snapshot_state(limits_record),
            self.component_revision_key: revision,
        }
        record = self.record_factory(
            as_of,
            stored_payload,
            self.market_now(),
        )
        return validated, record


@dataclass(frozen=True, slots=True)
class MaterializedAggregateRebuilder:
    repository: Any
    composer: MaterializedAggregateComposer
    market_now: Callable[[], Any]
    utc_now_factory: Callable[[], Any]
    limits_v1_enabled: Callable[[], bool]
    conflict_error: type[Exception]
    attempts: int = 3

    def rebuild(
        self,
        as_of: date,
        *,
        lease: Any | None = None,
        now: Any | None = None,
    ) -> dict[str, Any] | None:
        del now
        rebuild_started = perf_counter()
        if self.repository is None:
            raise RuntimeError("persistent snapshot store is disabled")
        for _attempt in range(self.attempts):
            revision = self.repository.materialization_revision(as_of)
            composed = self.composer.compose(as_of, revision)
            if composed is None:
                return None
            validated, record = composed
            if lease is None:
                if self.repository.materialization_revision(as_of) != revision:
                    continue
                stored_record = record
                persisted = False
            else:
                try:
                    stored_record = self.repository.put_materialized_aggregate(
                        record,
                        lease=lease,
                        expected_revision=revision,
                        now=self.utc_now_factory,
                    )
                except self.conflict_error:
                    continue
                persisted = True
            logger.info(
                "market aggregate rebuild",
                extra={
                    "event": "market_aggregate_rebuild",
                    "requested_as_of": as_of.isoformat(),
                    "actual_as_of": validated["asOf"],
                    "limits_v1_enabled": self.limits_v1_enabled(),
                    "aggregate_checksum": stored_record.checksum,
                    "component_revision": revision,
                    "persisted": persisted,
                    "rebuild_ms": round(
                        (perf_counter() - rebuild_started) * 1000,
                        3,
                    ),
                },
            )
            return validated
        raise self.conflict_error(
            f"materialized aggregate inputs kept changing: {as_of.isoformat()}"
        )


__all__ = [
    "MaterializedAggregateComposer",
    "MaterializedAggregateRebuilder",
]
