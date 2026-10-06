"""Provider-free market-environment read use cases."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..ports import (
    MaterializedAggregateReader,
    SnapshotReader,
    TradingSessionReader,
)
from ...domain.models import CollectionCandidate, DatasetDate


CHAPTER_SECTIONS = frozenset(
    {"breadth", "limits", "sectors", "activeDirection", "summary"}
)
_MATERIALIZED_METADATA_KEYS = frozenset(
    {"_storageSchemaVersion", "_limitsSnapshotState", "_componentRevision"}
)
ReviewEvidenceBuilder = Callable[[list[dict], dict, Any], dict[str, Any]]


def _exact_payload(payload: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    value = copy.deepcopy(dict(payload))
    actual = value.get("asOf")
    if actual not in (None, as_of.isoformat()):
        raise RuntimeError(
            f"stored payload date {actual} does not match requested date {as_of.isoformat()}"
        )
    value.setdefault("asOf", as_of.isoformat())
    return value


def _public_aggregate(payload: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    value = _exact_payload(payload, as_of)
    for key in _MATERIALIZED_METADATA_KEYS:
        value.pop(key, None)
    return value


def _candidate_payload(
    candidate: CollectionCandidate,
    identity: DatasetDate,
) -> dict[str, Any]:
    if candidate.identity != identity:
        raise RuntimeError(
            "snapshot repository returned "
            f"{candidate.identity.dataset}/{candidate.identity.as_of.isoformat()} "
            f"for {identity.dataset}/{identity.as_of.isoformat()}"
        )
    if candidate.actual_as_of not in (None, identity.as_of):
        raise RuntimeError(
            f"stored {identity.dataset} snapshot actual date "
            f"{candidate.actual_as_of.isoformat()} does not match requested date "
            f"{identity.as_of.isoformat()}"
        )
    return _exact_payload(candidate.payload, identity.as_of)


@dataclass(frozen=True, slots=True)
class GetMarketEnvironmentQuery:
    aggregates: MaterializedAggregateReader

    def execute(self, as_of: date) -> dict[str, Any]:
        payload = self.aggregates.get_aggregate(as_of)
        if payload is None:
            raise RuntimeError("所选日期没有已物化的市场环境聚合")
        return _public_aggregate(payload, as_of)


@dataclass(frozen=True, slots=True)
class GetCoreQuery:
    snapshots: SnapshotReader

    def execute(self, as_of: date) -> dict[str, Any]:
        identity = DatasetDate("core", as_of)
        candidate = self.snapshots.get(identity)
        if candidate is None:
            raise RuntimeError("所选日期没有已采集的核心指数快照")
        return _candidate_payload(candidate, identity)


@dataclass(frozen=True, slots=True)
class GetChapter01Query:
    aggregates: MaterializedAggregateReader

    def execute(self, as_of: date, section: str) -> dict[str, Any]:
        if section not in CHAPTER_SECTIONS:
            raise ValueError(f"未知第 01 章 section：{section}")
        aggregate = GetMarketEnvironmentQuery(self.aggregates).execute(as_of)
        chapter = aggregate.get("chapter01")
        if not isinstance(chapter, dict):
            raise RuntimeError("所选日期没有已物化的第 01 章聚合")
        return {
            "asOf": aggregate["asOf"],
            "generatedAt": aggregate.get("generatedAt"),
            "summary": copy.deepcopy(aggregate.get("summary") or {}),
            "chapter01": copy.deepcopy(chapter),
        }


@dataclass(frozen=True, slots=True)
class GetNextSessionComparisonQuery:
    snapshots: SnapshotReader
    aggregates: MaterializedAggregateReader
    trading_sessions: TradingSessionReader
    review_evidence_builder: ReviewEvidenceBuilder

    def execute(self, as_of: date) -> dict[str, Any]:
        base: dict[str, Any] = {
            "status": "insufficient",
            "requestedAsOf": as_of.isoformat(),
            "currentAsOf": None,
            "nextAsOf": None,
            "current": None,
            "next": None,
            "deltas": {},
            "warnings": [],
        }
        sessions = tuple(
            item
            for item in self.trading_sessions.list_sessions(after=as_of)
            if getattr(item, "is_session", False) and getattr(item, "as_of", as_of) > as_of
        )
        if not sessions:
            base["warnings"] = ["本地没有严格晚于当前日期的真实交易日"]
            return base
        next_date = min(item.as_of for item in sessions)
        base["nextAsOf"] = next_date.isoformat()
        current, current_warnings = self._review_context(as_of)
        next_value, next_warnings = self._review_context(next_date)
        base["warnings"] = list(dict.fromkeys([*current_warnings, *next_warnings]))
        if current is None:
            base["warnings"].append("当前日期缺少精确核心指数或市场广度快照")
            return base
        base["currentAsOf"] = as_of.isoformat()
        base["current"] = current
        if next_value is None:
            base["status"] = "pending"
            base["warnings"].append(
                f"下一真实交易日 {next_date.isoformat()} 的核心或广度聚合尚未就绪"
            )
            return base
        base["next"] = next_value
        base["status"] = "available"
        base["deltas"] = _review_evidence_deltas(current, next_value)
        return base

    def _review_context(
        self,
        as_of: date,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        warnings: list[str] = []
        aggregate = self.aggregates.get_aggregate(as_of)
        if aggregate is not None:
            payload = _public_aggregate(aggregate, as_of)
        else:
            core_identity = DatasetDate("core", as_of)
            core = self.snapshots.get(core_identity)
            if core is None:
                return None, [f"{as_of.isoformat()} 缺少精确核心指数快照"]
            payload = _candidate_payload(core, core_identity)
            breadth_identity = DatasetDate("breadth", as_of)
            breadth_candidate = self.snapshots.get(breadth_identity)
            if breadth_candidate is not None:
                payload.setdefault("chapter01", {})["breadth"] = copy.deepcopy(
                    _candidate_payload(breadth_candidate, breadth_identity)
                )
            else:
                warnings.append(f"{as_of.isoformat()} 缺少精确市场广度快照")

        indices = payload.get("indices")
        summary = payload.get("summary")
        chapter = payload.get("chapter01")
        breadth = chapter.get("breadth") if isinstance(chapter, dict) else None
        if not isinstance(breadth, dict):
            breadth_identity = DatasetDate("breadth", as_of)
            breadth_candidate = self.snapshots.get(breadth_identity)
            if breadth_candidate is not None:
                breadth = _candidate_payload(breadth_candidate, breadth_identity)
        if not isinstance(indices, list) or not isinstance(summary, dict) or not isinstance(breadth, dict):
            return None, [*warnings, f"{as_of.isoformat()} 缺少核心指数或市场广度聚合"]
        quality = breadth.get("quality")
        if isinstance(quality, dict) and quality.get("asOf") not in (
            None,
            as_of.isoformat(),
        ):
            return None, [*warnings, f"{as_of.isoformat()} 市场广度实际日期与请求日期不一致"]
        evidence = chapter.get("marketEvidence") if isinstance(chapter, dict) else None
        if not isinstance(evidence, dict):
            evidence = self.review_evidence_builder(
                indices,
                breadth,
                summary.get("syncPattern"),
            )
        return evidence, warnings


def _review_evidence_deltas(
    current: Mapping[str, Any],
    next_value: Mapping[str, Any],
) -> dict[str, Any]:
    numeric_fields = (
        "advancingIndexCount",
        "decliningIndexCount",
        "aboveMa20Count",
        "medianAmountRatio5",
        "volumeBackedAdvanceCount",
        "volumeBackedDeclineCount",
        "advanceRatio",
        "medianReturn",
    )
    result: dict[str, Any] = {}
    for field in numeric_fields:
        before, after = current.get(field), next_value.get(field)
        result[field] = (
            round(float(after) - float(before), 4)
            if before is not None and after is not None
            else None
        )
    result["directionPattern"] = (
        f"{current.get('directionLabel') or current.get('directionPattern')} → "
        f"{next_value.get('directionLabel') or next_value.get('directionPattern')}"
        if current.get("directionPattern") != next_value.get("directionPattern")
        else None
    )
    return result


__all__ = [
    "GetChapter01Query",
    "GetCoreQuery",
    "GetMarketEnvironmentQuery",
    "GetNextSessionComparisonQuery",
]
