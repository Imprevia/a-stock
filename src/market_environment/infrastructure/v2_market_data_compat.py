"""Fixture/legacy-store adapter for the v2 application read contract.

This adapter intentionally projects already materialized in-memory payloads.
Production composition must use ``PostgresV2MarketDataReadAdapter`` so list
filters and bounds are applied by PostgreSQL before rows are materialized.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from ..application.ports.v2_market_data import SortKey, V2Page, V2Resource


_POOL_KEYS = {
    "limit_up": "limitUp",
    "limit_down": "limitDown",
    "failed_limit_up": "failedLimitUp",
    "promoted": "promoted",
}


def _dict(value: Any) -> dict[str, Any]:
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [_dict(item) for item in value if isinstance(item, Mapping)]


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CompatibilityV2MarketDataReadAdapter:
    """In-memory adapter used by legacy SnapshotStore and deterministic tests."""

    def __init__(
        self,
        source: Mapping[date, Mapping[str, Any]] | Any,
        *,
        operations: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.source = source
        self.operations = dict(operations or {})

    def _aggregate(self, as_of: date) -> dict[str, Any] | None:
        if isinstance(self.source, Mapping):
            value = self.source.get(as_of)
            return _dict(value) if value is not None else None
        getter = getattr(self.source, "get_materialized_aggregate", None)
        if not callable(getter):
            return None
        record = getter(as_of)
        return _dict(getattr(record, "payload", None)) if record is not None else None

    def _revision(self, as_of: date, aggregate: Mapping[str, Any]) -> str:
        revision = getattr(self.source, "materialization_revision", None)
        return str(revision(as_of)) if callable(revision) else _stable_digest(aggregate)

    def _resource(
        self,
        as_of: date,
        dataset: str,
        data: Any,
        *,
        quality: Mapping[str, Any] | None = None,
        aggregate: Mapping[str, Any] | None = None,
    ) -> V2Resource:
        payload = dict(aggregate) if aggregate is not None else self._aggregate(as_of) or {}
        selected_quality = _dict(quality)
        selected_quality.setdefault("dataset", dataset)
        selected_quality.setdefault("status", "missing")
        selected_quality.setdefault("asOf", as_of.isoformat())
        selected_quality.setdefault("warnings", [])
        return V2Resource(
            as_of,
            str(payload.get("generatedAt") or ""),
            self._revision(as_of, payload),
            selected_quality,
            copy.deepcopy(data),
        )

    def _chapter(self, as_of: date, key: str, dataset: str) -> V2Resource | None:
        aggregate = self._aggregate(as_of)
        if aggregate is None:
            return None
        value = _dict(_dict(aggregate.get("chapter01")).get(key))
        return self._resource(
            as_of,
            dataset,
            value,
            quality=_dict(value.get("quality")),
            aggregate=aggregate,
        )

    @staticmethod
    def _page(
        resource: V2Resource,
        rows: list[dict[str, Any]],
        *,
        limit: int,
        key,
    ) -> V2Page:
        ordered = sorted(rows, key=key)
        page = ordered[: limit + 1]
        items = page[:limit]
        return V2Page(
            V2Resource(
                resource.as_of,
                resource.generated_at,
                resource.component_revision,
                resource.quality,
                items,
            ),
            tuple(str(item) for item in key(items[-1])) if len(page) > limit and items else None,
            len(ordered),
        )

    def overview(self, as_of: date) -> V2Resource | None:
        aggregate = self._aggregate(as_of)
        if aggregate is None:
            return None
        chapter = _dict(aggregate.get("chapter01"))
        return self._resource(
            as_of,
            "market-environment-overview",
            {
                "summary": _dict(aggregate.get("summary")),
                "status": chapter.get("status"),
                "coverage": chapter.get("coverage"),
                "summarySentence": chapter.get("summarySentence"),
                "marketEvidence": chapter.get("marketEvidence"),
                "reviewSentence": chapter.get("reviewSentence"),
            },
            quality={"status": chapter.get("status") or "insufficient"},
            aggregate=aggregate,
        )

    def indices(self, as_of: date) -> V2Resource | None:
        aggregate = self._aggregate(as_of)
        if aggregate is None:
            return None
        values = []
        for item in _rows(aggregate.get("indices")):
            item.pop("history", None)
            values.append(item)
        return self._resource(
            as_of,
            "core-indices",
            values,
            quality={"status": "ok" if values else "missing", "observations": len(values)},
            aggregate=aggregate,
        )

    def index(self, as_of: date, code: str) -> V2Resource | None:
        values = self.indices(as_of)
        if values is None:
            return None
        item = next(
            (row for row in values.data or () if str(row.get("code", "")).lower() == code.lower()),
            None,
        )
        if item is None:
            return None
        return V2Resource(
            values.as_of,
            values.generated_at,
            values.component_revision,
            _dict(item.get("dataQuality")),
            item,
        )

    def index_history(
        self,
        as_of: date,
        code: str,
        *,
        start_date: date | None,
        end_date: date | None,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        aggregate = self._aggregate(as_of)
        metadata = self.index(as_of, code)
        if aggregate is None or metadata is None:
            return None
        index = next(
            item for item in _rows(aggregate.get("indices"))
            if str(item.get("code", "")).lower() == code.lower()
        )
        values = [
            item for item in _rows(index.get("history"))
            if (start_date is None or date.fromisoformat(str(item["date"])) >= start_date)
            and (end_date is None or date.fromisoformat(str(item["date"])) <= end_date)
            and (after is None or str(item["date"]) > after[0])
        ]
        if not values and after is None:
            metadata = V2Resource(
                metadata.as_of,
                metadata.generated_at,
                metadata.component_revision,
                {**_dict(metadata.quality), "status": "insufficient"},
                metadata.data,
            )
        return self._page(metadata, values, limit=limit, key=lambda item: (str(item["date"]),))

    def breadth(self, as_of: date) -> V2Resource | None:
        value = self._chapter(as_of, "breadth", "market-breadth")
        if value and isinstance(value.data, Mapping):
            data = _dict(value.data)
            data.pop("history", None)
            return V2Resource(value.as_of, value.generated_at, value.component_revision, value.quality, data)
        return value

    def _embedded_history(
        self,
        resource: V2Resource | None,
        original: Mapping[str, Any],
        *,
        start_date: date | None,
        end_date: date | None,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        if resource is None:
            return None
        points = _rows(_dict(original.get("history")).get("points"))
        values = [
            item for item in points
            if (start_date is None or date.fromisoformat(str(item["asOf"])) >= start_date)
            and (end_date is None or date.fromisoformat(str(item["asOf"])) <= end_date)
            and (after is None or str(item["asOf"]) > after[0])
        ]
        if not values and after is None:
            resource = V2Resource(
                resource.as_of,
                resource.generated_at,
                resource.component_revision,
                {**_dict(resource.quality), "status": "insufficient"},
                resource.data,
            )
        return self._page(resource, values, limit=limit, key=lambda item: (str(item["asOf"]),))

    def breadth_history(self, as_of: date, *, start_date=None, end_date=None, after=None, limit: int) -> V2Page | None:
        aggregate = self._aggregate(as_of) or {}
        original = _dict(_dict(aggregate.get("chapter01")).get("breadth"))
        return self._embedded_history(self.breadth(as_of), original, start_date=start_date, end_date=end_date, after=after, limit=limit)

    def limits(self, as_of: date) -> V2Resource | None:
        value = self._chapter(as_of, "limits", "market-limits")
        if value and isinstance(value.data, Mapping):
            data = _dict(value.data)
            for key in ("securityDetails", "history", "ruleEvidence", "riskEvidence"):
                data.pop(key, None)
            return V2Resource(value.as_of, value.generated_at, value.component_revision, value.quality, data)
        return value

    def limits_pool(self, as_of: date, pool_type: str, *, after=None, limit: int) -> V2Page | None:
        aggregate = self._aggregate(as_of) or {}
        raw = _dict(_dict(_dict(aggregate.get("chapter01")).get("limits")).get("securityDetails"))
        group = _dict(raw.get(_POOL_KEYS[pool_type]))
        rows = _rows(group.get("rows"))
        if after:
            rows = [row for row in rows if (str(row.get("exchange")), str(row.get("code")), str(row.get("securityId"))) > after]
        metadata = self.limits(as_of)
        if metadata is not None:
            parent_quality = _dict(metadata.quality)
            group_quality = _dict(group.get("quality"))
            quality = {**parent_quality, **group_quality}
            if parent_quality.get("status") in {"failed-retained", "failed-missing"}:
                quality["status"] = parent_quality["status"]
            warnings = [
                *[str(item) for item in group_quality.get("warnings", [])],
                *[str(item) for item in parent_quality.get("warnings", [])],
            ]
            refresh_warning = parent_quality.get("refreshWarning")
            if refresh_warning:
                warnings.append(str(refresh_warning))
            quality["warnings"] = list(dict.fromkeys(warnings))
            metadata = V2Resource(
                metadata.as_of,
                metadata.generated_at,
                metadata.component_revision,
                quality,
                metadata.data,
            )
        return self._page(
            metadata,
            rows,
            limit=limit,
            key=lambda row: (str(row.get("exchange")), str(row.get("code")), str(row.get("securityId"))),
        ) if metadata is not None else None

    def limits_history(self, as_of: date, *, start_date=None, end_date=None, after=None, limit: int) -> V2Page | None:
        aggregate = self._aggregate(as_of) or {}
        original = _dict(_dict(aggregate.get("chapter01")).get("limits"))
        return self._embedded_history(self.limits(as_of), original, start_date=start_date, end_date=end_date, after=after, limit=limit)

    def limits_evidence(self, as_of: date) -> V2Resource | None:
        original = self._chapter(as_of, "limits", "market-limits-evidence")
        if original is None or not isinstance(original.data, Mapping):
            return original
        return V2Resource(
            original.as_of,
            original.generated_at,
            original.component_revision,
            original.quality,
            {"ruleEvidence": list(original.data.get("ruleEvidence") or []), "riskEvidence": list(original.data.get("riskEvidence") or [])},
        )

    def _chapter_page(self, as_of: date, key: str, dataset: str, *, after, limit: int, sort_key) -> V2Page | None:
        resource = self._chapter(as_of, key, dataset)
        if resource is None or not isinstance(resource.data, Mapping):
            return None
        rows = _rows(resource.data.get("rows"))
        if after:
            rows = [row for row in rows if tuple(str(v) for v in sort_key(row)) > after]
        return self._page(resource, rows, limit=limit, key=sort_key)

    def sector_rankings(self, as_of: date, *, tag=None, after=None, limit: int) -> V2Page | None:
        resource = self._chapter(as_of, "industryRanking", "industry-ranking")
        if resource is None or not isinstance(resource.data, Mapping):
            return None
        rows = [row for row in _rows(resource.data.get("rows")) if tag is None or row.get("tag") == tag]
        if after:
            rows = [row for row in rows if (str(row.get("tag")), str(row.get("rank")), str(row.get("thscode"))) > after]
        return self._page(resource, rows, limit=limit, key=lambda row: (str(row.get("tag")), str(row.get("rank")), str(row.get("thscode"))))

    def sector_turnover(self, as_of: date, *, after=None, limit: int) -> V2Page | None:
        return self._chapter_page(as_of, "sectorTurnover", "sector-turnover", after=after, limit=limit, sort_key=lambda row: (str(row.get("thscode") or row.get("code")),))

    def sector_breadth(self, as_of: date, *, after=None, limit: int) -> V2Page | None:
        return self._chapter_page(as_of, "sectorBreadth", "sector-breadth", after=after, limit=limit, sort_key=lambda row: (str(row.get("thscode") or row.get("code")),))

    def sector_analysis(self, as_of: date) -> V2Resource | None:
        return self._chapter(as_of, "sectorAnalysis", "sector-analysis")

    def active_direction(self, as_of: date, *, after=None, limit: int) -> V2Page | None:
        resource = self._chapter(as_of, "activeDirection", "active-direction")
        if resource is None or not isinstance(resource.data, Mapping):
            return None
        rows = _rows(resource.data.get("topStocks"))
        if after:
            rows = [row for row in rows if (str(row.get("amount") or ""), str(row.get("code") or "")) > after]
        return self._page(resource, rows, limit=limit, key=lambda row: (str(row.get("amount") or ""), str(row.get("code") or "")))

    def events(self, as_of: date, *, after=None, limit: int) -> V2Page | None:
        resource = self._chapter(as_of, "events", "market-events")
        if resource is None or not isinstance(resource.data, Mapping):
            return None
        rows = _rows(resource.data.get("items"))
        indexed = [{**row, "_sortOrdinal": index} for index, row in enumerate(rows, start=1)]
        if after:
            indexed = [row for row in indexed if int(row["_sortOrdinal"]) > int(after[0])]
        page = self._page(
            resource,
            indexed,
            limit=limit,
            key=lambda row: (int(row["_sortOrdinal"]),),
        )
        return V2Page(
            V2Resource(
                page.resource.as_of,
                page.resource.generated_at,
                page.resource.component_revision,
                page.resource.quality,
                [_dict({key: value for key, value in row.items() if key != "_sortOrdinal"}) for row in page.resource.data or ()],
            ),
            page.next_sort_key,
            page.total,
        )

    def assessment(self, as_of: date) -> V2Resource | None:
        return self._chapter(as_of, "assessment", "market-assessment")

    def operation_summary(self, run_id: str) -> V2Resource | None:
        raw = self.operations.get(run_id)
        if raw is None:
            return None
        value = _dict(raw)
        value.pop("checkpoints", None)
        generated_at = str(value.get("completedAt") or value.get("startedAt") or value.get("requestedAt") or "")
        return V2Resource(None, generated_at, _stable_digest(value), {"dataset": "ths-operation", "status": value.get("status", "missing"), "warnings": []}, value)

    def operation_checkpoints(self, run_id: str, *, after=None, limit: int) -> V2Page | None:
        summary = self.operation_summary(run_id)
        raw = self.operations.get(run_id)
        if summary is None or raw is None:
            return None
        rows = _rows(raw.get("checkpoints"))
        key = lambda row: (str(row.get("thscode")), str(row.get("windowStart")), str(row.get("windowEnd")))
        if after:
            rows = [row for row in rows if key(row) > after]
        return self._page(summary, rows, limit=limit, key=key)


__all__ = ["CompatibilityV2MarketDataReadAdapter"]
