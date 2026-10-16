"""PostgreSQL-only bounded reads for the v2 market-data application port."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Callable

from sqlalchemy import Connection, text

from ....application.ports.v2_market_data import SortKey, V2Page, V2Resource
from .aggregate_repository import PostgresMaterializedAggregateRepository
from .repositories import _json_load


_PRIVATE_KEYS = frozenset(
    {"_storageSchemaVersion", "_limitsSnapshotState", "_componentRevision"}
)
_LIMIT_POOL_FILTERS = {
    "limit_up": "current.pool_type = 'limit_up'",
    "limit_down": "current.pool_type = 'limit_down'",
    "failed_limit_up": "current.pool_type = 'failed_limit_up'",
    "promoted": (
        "current.pool_type = 'limit_up' AND current.closed_limit_up = TRUE "
        "AND EXISTS (SELECT 1 FROM trading_sessions session "
        "JOIN limit_security_facts previous "
        "ON previous.as_of = session.previous_as_of "
        "AND previous.security_id = current.security_id "
        "AND previous.pool_type = 'limit_up' "
        "AND previous.closed_limit_up = TRUE "
        "WHERE session.as_of = current.as_of)"
    ),
}
_LIMIT_POOL_GROUPS = {
    "limit_up": "limitUp",
    "limit_down": "limitDown",
    "failed_limit_up": "failedLimitUp",
    "promoted": "promoted",
}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    return {}


def _sequence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [_mapping(item) for item in value if isinstance(item, Mapping)]


def _quality(value: Any, *, dataset: str, as_of: date | None) -> dict[str, Any]:
    result = _mapping(value)
    result.setdefault("dataset", dataset)
    result.setdefault("status", "missing")
    result.setdefault("asOf", as_of.isoformat() if as_of is not None else None)
    result.setdefault("warnings", [])
    return result


def _without(value: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    for key in keys:
        result.pop(key, None)
    return result


def _page(
    metadata: V2Resource,
    rows: Sequence[dict[str, Any]],
    *,
    limit: int,
    sort_key,
    total: int | None = None,
) -> V2Page:
    has_more = len(rows) > limit
    items = list(rows[:limit])
    return V2Page(
        resource=V2Resource(
            as_of=metadata.as_of,
            generated_at=metadata.generated_at,
            component_revision=metadata.component_revision,
            quality=metadata.quality,
            data=items,
        ),
        next_sort_key=sort_key(items[-1]) if has_more and items else None,
        total=total,
    )


def _insufficient_if_empty(
    resource: V2Resource,
    rows: Sequence[dict[str, Any]],
    after: SortKey | None,
) -> V2Resource:
    """Do not present an empty first history page as successful evidence."""

    if rows or after is not None:
        return resource
    return V2Resource(
        resource.as_of,
        resource.generated_at,
        resource.component_revision,
        {**dict(resource.quality), "status": "insufficient"},
        resource.data,
    )


class PostgresV2MarketDataReadAdapter:
    """Connection-scoped adapter; construction and reads perform no writes."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.aggregates = PostgresMaterializedAggregateRepository(connection)

    def _aggregate(self, as_of: date) -> dict[str, Any] | None:
        payload = self.aggregates.get_aggregate(as_of)
        if payload is None:
            return None
        result = copy.deepcopy(dict(payload))
        for key in _PRIVATE_KEYS:
            result.pop(key, None)
        return result

    def _resource(
        self,
        as_of: date,
        *,
        dataset: str,
        data: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
        quality: Mapping[str, Any] | None = None,
        aggregate: Mapping[str, Any] | None = None,
    ) -> V2Resource:
        payload = dict(aggregate) if aggregate is not None else self._aggregate(as_of) or {}
        generated_at = str(payload.get("generatedAt") or "")
        revision = self.aggregates.revision(as_of).value
        return V2Resource(
            as_of=as_of,
            generated_at=generated_at,
            component_revision=revision,
            quality=_quality(quality, dataset=dataset, as_of=as_of),
            data=(
                copy.deepcopy(dict(data))
                if isinstance(data, Mapping)
                else tuple(copy.deepcopy(dict(item)) for item in data)
                if data is not None
                else None
            ),
        )

    def _list_metadata(
        self,
        as_of: date,
        *,
        snapshot_dataset: str,
        public_dataset: str,
    ) -> V2Resource | None:
        aggregate = self.connection.execute(
            text(
                "SELECT generated_at FROM materialized_market_environment "
                "WHERE as_of=:as_of"
            ),
            {"as_of": as_of},
        ).mappings().first()
        if aggregate is None:
            return None
        snapshot = self.connection.execute(
            text(
                """SELECT source,status,observations,warnings_json,fetched_at,refresh_warning
                FROM snapshot_entries WHERE dataset=:dataset AND as_of=:as_of"""
            ),
            {"dataset": snapshot_dataset, "as_of": as_of},
        ).mappings().first()
        quality = {
            "dataset": public_dataset,
            "source": snapshot.get("source") if snapshot else None,
            "status": snapshot.get("status") if snapshot else "missing",
            "observations": snapshot.get("observations") if snapshot else 0,
            "asOf": as_of.isoformat(),
            "warnings": list(_json_load(snapshot.get("warnings_json"), [])) if snapshot else [],
            "snapshotFetchedAt": snapshot.get("fetched_at") if snapshot else None,
            "refreshWarning": snapshot.get("refresh_warning") if snapshot else None,
        }
        return V2Resource(
            as_of,
            str(aggregate["generated_at"]),
            self.aggregates.revision(as_of).value,
            quality,
            {},
        )

    def _limits_pool_metadata(
        self,
        as_of: date,
        pool_type: str,
    ) -> V2Resource | None:
        pool_key = _LIMIT_POOL_GROUPS[pool_type]
        row = self.connection.execute(
            text(
                f"""SELECT aggregate.generated_at,
                           aggregate.payload_json->'chapter01'->'limits'
                             ->'securityDetails'->'{pool_key}'->'quality' AS pool_quality_json,
                           snapshot.source,snapshot.status,snapshot.observations,
                           snapshot.warnings_json,snapshot.fetched_at,snapshot.refresh_warning
                    FROM materialized_market_environment aggregate
                    LEFT JOIN snapshot_entries snapshot
                      ON snapshot.dataset='limits' AND snapshot.as_of=aggregate.as_of
                    WHERE aggregate.as_of=:as_of"""
            ),
            {"as_of": as_of},
        ).mappings().first()
        if row is None:
            return None

        snapshot_warnings = list(_json_load(row.get("warnings_json"), []))
        refresh_warning = row.get("refresh_warning")
        if refresh_warning and refresh_warning not in snapshot_warnings:
            snapshot_warnings.append(str(refresh_warning))
        snapshot_quality = {
            "dataset": "market-limits-pool",
            "source": row.get("source"),
            "status": row.get("status") or "missing",
            "observations": row.get("observations") or 0,
            "asOf": as_of.isoformat(),
            "warnings": snapshot_warnings,
            "snapshotFetchedAt": row.get("fetched_at"),
            "refreshWarning": refresh_warning,
        }
        pool_quality = _mapping(_json_load(row.get("pool_quality_json"), {}))
        quality = {**snapshot_quality, **pool_quality}
        snapshot_status = str(snapshot_quality["status"])
        if snapshot_status in {"failed-retained", "failed-missing"}:
            quality["status"] = snapshot_status
        quality["warnings"] = list(
            dict.fromkeys(
                [
                    *[str(item) for item in pool_quality.get("warnings", [])],
                    *[str(item) for item in snapshot_warnings],
                ]
            )
        )
        quality["refreshWarning"] = refresh_warning
        return V2Resource(
            as_of,
            str(row["generated_at"]),
            self.aggregates.revision(as_of).value,
            quality,
            {},
        )

    def overview(self, as_of: date) -> V2Resource | None:
        aggregate = self._aggregate(as_of)
        if aggregate is None:
            return None
        chapter = _mapping(aggregate.get("chapter01"))
        resource_quality = {
            key: _mapping(value.get("quality"))
            for key, value in chapter.items()
            if isinstance(value, Mapping) and isinstance(value.get("quality"), Mapping)
        }
        data = {
            "summary": _mapping(aggregate.get("summary")),
            "status": chapter.get("status"),
            "coverage": chapter.get("coverage"),
            "summarySentence": chapter.get("summarySentence"),
            "marketEvidence": copy.deepcopy(chapter.get("marketEvidence")),
            "reviewSentence": copy.deepcopy(chapter.get("reviewSentence")),
            "resources": resource_quality,
        }
        return self._resource(
            as_of,
            dataset="market-environment-overview",
            data=data,
            quality={"status": chapter.get("status") or "insufficient"},
            aggregate=aggregate,
        )

    def indices(self, as_of: date) -> V2Resource | None:
        aggregate = self._aggregate(as_of)
        if aggregate is None:
            return None
        rows = [_without(item, "history") for item in _sequence(aggregate.get("indices"))]
        statuses = [item.get("dataQuality", {}).get("warning") for item in rows]
        return self._resource(
            as_of,
            dataset="core-indices",
            data=rows,
            quality={"status": "degraded" if any(statuses) else "ok", "observations": len(rows)},
            aggregate=aggregate,
        )

    def index(self, as_of: date, code: str) -> V2Resource | None:
        collection = self.indices(as_of)
        if collection is None:
            return None
        selected = next(
            (item for item in collection.data or () if str(item.get("code", "")).lower() == code.lower()),
            None,
        )
        if selected is None:
            return None
        return V2Resource(
            collection.as_of,
            collection.generated_at,
            collection.component_revision,
            _quality(selected.get("dataQuality"), dataset="core-index", as_of=as_of),
            selected,
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
        metadata = self._list_metadata(
            as_of,
            snapshot_dataset="core",
            public_dataset="core-index-history",
        )
        if metadata is None:
            return None
        params: dict[str, Any] = {
            "as_of": as_of,
            "code": code.lower(),
            "start_date": start_date,
            "end_date": end_date,
            "after_date": after[0] if after else None,
            "limit": limit + 1,
        }
        rows = self.connection.execute(
            text(
                """WITH selected_index AS (
                    SELECT index_value
                    FROM snapshot_entries snapshot
                    CROSS JOIN LATERAL jsonb_array_elements(snapshot.payload_json->'indices') index_value
                    WHERE snapshot.dataset='core' AND snapshot.as_of=:as_of
                      AND lower(index_value->>'code')=:code
                    LIMIT 1
                )
                SELECT point.value AS payload
                FROM selected_index
                CROSS JOIN LATERAL jsonb_array_elements(index_value->'history') point(value)
                WHERE (:start_date IS NULL OR (point.value->>'date')::date>=:start_date)
                  AND (:end_date IS NULL OR (point.value->>'date')::date<=:end_date)
                  AND (:after_date IS NULL OR point.value->>'date'>:after_date)
                ORDER BY point.value->>'date'
                LIMIT :limit"""
            ),
            params,
        ).mappings()
        values = [_mapping(_json_load(row["payload"], {})) for row in rows]
        metadata = _insufficient_if_empty(metadata, values, after)
        return _page(metadata, values, limit=limit, sort_key=lambda row: (str(row["date"]),))

    def _chapter_resource(self, as_of: date, key: str, dataset: str) -> V2Resource | None:
        aggregate = self._aggregate(as_of)
        if aggregate is None:
            return None
        value = _mapping(_mapping(aggregate.get("chapter01")).get(key))
        return self._resource(
            as_of,
            dataset=dataset,
            data=value,
            quality=_mapping(value.get("quality")),
            aggregate=aggregate,
        )

    def breadth(self, as_of: date) -> V2Resource | None:
        value = self._chapter_resource(as_of, "breadth", "market-breadth")
        if value is None or not isinstance(value.data, Mapping):
            return value
        return V2Resource(
            value.as_of,
            value.generated_at,
            value.component_revision,
            value.quality,
            _without(value.data, "history"),
        )

    def _snapshot_history(
        self,
        as_of: date,
        *,
        dataset: str,
        start_date: date | None,
        end_date: date | None,
        after: SortKey | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """SELECT as_of,payload_json
                FROM snapshot_entries
                WHERE dataset=:dataset AND as_of<=:as_of
                  AND (:start_date IS NULL OR as_of>=:start_date)
                  AND (:end_date IS NULL OR as_of<=:end_date)
                  AND (:after_date IS NULL OR as_of>:after_date)
                ORDER BY as_of
                LIMIT :limit"""
            ),
            {
                "dataset": dataset,
                "as_of": as_of,
                "start_date": start_date,
                "end_date": end_date,
                "after_date": after[0] if after else None,
                "limit": limit + 1,
            },
        ).mappings()
        values: list[dict[str, Any]] = []
        for row in rows:
            payload = _mapping(_json_load(row["payload_json"], {}))
            payload.setdefault("asOf", row["as_of"].isoformat() if hasattr(row["as_of"], "isoformat") else str(row["as_of"]))
            values.append(payload)
        return values

    def breadth_history(
        self,
        as_of: date,
        *,
        start_date: date | None,
        end_date: date | None,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        metadata = self._list_metadata(
            as_of,
            snapshot_dataset="breadth",
            public_dataset="market-breadth-history",
        )
        if metadata is None:
            return None
        values = self._snapshot_history(
            as_of,
            dataset="breadth",
            start_date=start_date,
            end_date=end_date,
            after=after,
            limit=limit,
        )
        metadata = _insufficient_if_empty(metadata, values, after)
        return _page(metadata, values, limit=limit, sort_key=lambda row: (str(row["asOf"]),))

    def limits(self, as_of: date) -> V2Resource | None:
        value = self._chapter_resource(as_of, "limits", "market-limits")
        if value is None or not isinstance(value.data, Mapping):
            return value
        return V2Resource(
            value.as_of,
            value.generated_at,
            value.component_revision,
            value.quality,
            _without(value.data, "securityDetails", "history", "ruleEvidence", "riskEvidence"),
        )

    def limits_pool(
        self,
        as_of: date,
        pool_type: str,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        metadata = self._limits_pool_metadata(as_of, pool_type)
        if metadata is None:
            return None
        predicate = _LIMIT_POOL_FILTERS[pool_type]
        rows = self.connection.execute(
            text(
                f"""SELECT current.* FROM limit_security_facts current
                WHERE current.as_of=:as_of AND {predicate}
                  AND current.actual_as_of=current.as_of
                  AND current.invalid_reason IS NULL
                  AND (:after_exchange IS NULL OR
                       (current.exchange,current.code,current.security_id)>
                       (:after_exchange,:after_code,:after_security_id))
                ORDER BY current.exchange,current.code,current.security_id
                LIMIT :limit"""
            ),
            {
                "as_of": as_of,
                "after_exchange": after[0] if after else None,
                "after_code": after[1] if after else None,
                "after_security_id": after[2] if after else None,
                "limit": limit + 1,
            },
        ).mappings()
        values = [self._limit_row(row) for row in rows]
        return _page(
            metadata,
            values,
            limit=limit,
            sort_key=lambda row: (str(row["exchange"]), str(row["code"]), str(row["securityId"])),
        )

    @staticmethod
    def _limit_row(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "securityId": row["security_id"],
            "code": row["code"],
            "exchange": row["exchange"],
            "name": row.get("name"),
            "poolType": row["pool_type"],
            "isSt": row.get("is_st"),
            "isNew": row.get("is_new"),
            "listingDate": row.get("listing_date"),
            "closePrice": row.get("close_price"),
            "changePct": row.get("change_pct"),
            "streakDays": row.get("streak_days"),
            "limitUpTime": row.get("limit_up_time"),
            "limitUpReason": row.get("limit_up_reason"),
            "sealMoney": row.get("seal_money"),
            "maxSealMoney": row.get("max_seal_money"),
            "firstLimitTime": row.get("first_limit_time"),
            "lastLimitTime": row.get("last_limit_time"),
            "openTimes": row.get("open_times"),
            "turnoverRatioPct": row.get("turnover_ratio_pct"),
            "turnover": row.get("turnover"),
            "source": row.get("source"),
            "rowQuality": row.get("row_quality"),
            "warnings": list(_json_load(row.get("row_warnings_json"), [])),
        }

    def limits_history(
        self,
        as_of: date,
        *,
        start_date: date | None,
        end_date: date | None,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        metadata = self._list_metadata(
            as_of,
            snapshot_dataset="limits",
            public_dataset="market-limits-history",
        )
        if metadata is None:
            return None
        rows = self.connection.execute(
            text(
                """SELECT snapshot.as_of,snapshot.payload_json
                FROM snapshot_entries snapshot
                JOIN trading_sessions session
                  ON session.as_of=snapshot.as_of AND session.is_session=TRUE
                WHERE snapshot.dataset='limits' AND snapshot.as_of<=:as_of
                  AND (:start_date IS NULL OR snapshot.as_of>=:start_date)
                  AND (:end_date IS NULL OR snapshot.as_of<=:end_date)
                  AND (:after_date IS NULL OR snapshot.as_of>:after_date)
                ORDER BY snapshot.as_of
                LIMIT :limit"""
            ),
            {
                "as_of": as_of,
                "start_date": start_date,
                "end_date": end_date,
                "after_date": after[0] if after else None,
                "limit": limit + 1,
            },
        ).mappings()
        values = []
        for row in rows:
            payload = _mapping(_json_load(row["payload_json"], {}))
            payload.setdefault(
                "asOf",
                row["as_of"].isoformat()
                if hasattr(row["as_of"], "isoformat")
                else str(row["as_of"]),
            )
            values.append(payload)
        points = [
            {
                "asOf": value.get("asOf"),
                "limitUpCount": value.get("limitUpCount"),
                "limitDownCount": value.get("limitDownCount"),
                "failedLimitUpRatio": value.get("failedLimitUpRatio"),
                "promotionRatio": value.get("promotionRatio"),
                "maxStreak": value.get("maxStreak"),
                "quality": value.get("quality"),
            }
            for value in values
        ]
        metadata = _insufficient_if_empty(metadata, points, after)
        return _page(metadata, points, limit=limit, sort_key=lambda row: (str(row["asOf"]),))

    def limits_evidence(self, as_of: date) -> V2Resource | None:
        value = self._chapter_resource(as_of, "limits", "market-limits-evidence")
        if value is None or not isinstance(value.data, Mapping):
            return value
        return V2Resource(
            value.as_of,
            value.generated_at,
            value.component_revision,
            value.quality,
            {
                "ruleEvidence": copy.deepcopy(value.data.get("ruleEvidence") or []),
                "riskEvidence": copy.deepcopy(value.data.get("riskEvidence") or []),
            },
        )

    def sector_rankings(
        self,
        as_of: date,
        *,
        tag: str | None,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        metadata = self._list_metadata(
            as_of,
            snapshot_dataset="industry-ranking",
            public_dataset="industry-ranking",
        )
        if metadata is None:
            return None
        rows = self.connection.execute(
            text(
                """SELECT tag,rank,thscode,display_name,change_pct,volume,turnover,
                          catalog_revision_id,quality_status,warnings_json
                FROM ths_industry_rankings
                WHERE provider='fuyao' AND as_of=:as_of
                  AND (:tag IS NULL OR tag=:tag)
                  AND (:after_tag IS NULL OR (tag,rank,thscode)>(:after_tag,:after_rank,:after_code))
                ORDER BY tag,rank,thscode
                LIMIT :limit"""
            ),
            {
                "as_of": as_of,
                "tag": tag,
                "after_tag": after[0] if after else None,
                "after_rank": int(after[1]) if after else None,
                "after_code": after[2] if after else None,
                "limit": limit + 1,
            },
        ).mappings()
        values = [
            {
                "tag": row["tag"],
                "rank": row["rank"],
                "thscode": row["thscode"],
                "name": row["display_name"],
                "changePct": row.get("change_pct"),
                "volume": row.get("volume"),
                "turnover": row.get("turnover"),
                "catalogRevisionId": row["catalog_revision_id"],
                "quality": row.get("quality_status"),
                "warnings": list(_json_load(row.get("warnings_json"), [])),
            }
            for row in rows
        ]
        return _page(
            metadata,
            values,
            limit=limit,
            sort_key=lambda row: (str(row["tag"]), str(row["rank"]), str(row["thscode"])),
        )

    def sector_turnover(
        self,
        as_of: date,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        metadata = self._list_metadata(
            as_of,
            snapshot_dataset="sector-turnover",
            public_dataset="sector-turnover",
        )
        if metadata is None:
            return None
        rows = self.connection.execute(
            text(
                """SELECT * FROM (
                    SELECT bar.*,ROW_NUMBER() OVER (
                        PARTITION BY thscode ORDER BY fetched_at DESC,source_revision DESC
                    ) revision_rank
                    FROM ths_sector_daily_bars bar
                    WHERE provider='fuyao' AND trading_date=:as_of
                      AND (:after_code IS NULL OR thscode>:after_code)
                ) selected
                WHERE revision_rank=1
                ORDER BY thscode
                LIMIT :limit"""
            ),
            {"as_of": as_of, "after_code": after[0] if after else None, "limit": limit + 1},
        ).mappings()
        values = [dict(row) for row in rows]
        return _page(metadata, values, limit=limit, sort_key=lambda row: (str(row["thscode"]),))

    def sector_breadth(
        self,
        as_of: date,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        metadata = self._list_metadata(
            as_of,
            snapshot_dataset="sector-breadth",
            public_dataset="sector-breadth",
        )
        if metadata is None:
            return None
        rows = self.connection.execute(
            text(
                """SELECT * FROM ths_sector_breadth_evidence
                WHERE as_of=:as_of AND (:after_code IS NULL OR thscode>:after_code)
                ORDER BY thscode,catalog_revision_id,calculation_revision
                LIMIT :limit"""
            ),
            {"as_of": as_of, "after_code": after[0] if after else None, "limit": limit + 1},
        ).mappings()
        values = [dict(row) for row in rows]
        return _page(metadata, values, limit=limit, sort_key=lambda row: (str(row["thscode"]),))

    def sector_analysis(self, as_of: date) -> V2Resource | None:
        return self._chapter_resource(as_of, "sectorAnalysis", "sector-analysis")

    def active_direction(
        self,
        as_of: date,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        metadata = self._list_metadata(
            as_of,
            snapshot_dataset="activeDirection",
            public_dataset="active-direction",
        )
        if metadata is None:
            return None
        rows = self.connection.execute(
            text(
                """WITH snapshot AS (
                    SELECT payload_json FROM snapshot_entries
                    WHERE dataset='activeDirection' AND as_of=:as_of
                )
                SELECT item.value AS payload,item.ordinality
                FROM snapshot
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(snapshot.payload_json->'topStocks',snapshot.payload_json->'rows','[]'::jsonb)
                ) WITH ORDINALITY item(value,ordinality)
                WHERE (:after_ordinal IS NULL OR item.ordinality>:after_ordinal)
                ORDER BY item.ordinality
                LIMIT :limit"""
            ),
            {
                "as_of": as_of,
                "after_ordinal": int(after[0]) if after else None,
                "limit": limit + 1,
            },
        ).mappings()
        values = [
            {**_mapping(_json_load(row["payload"], {})), "_sortOrdinal": int(row["ordinality"])}
            for row in rows
        ]
        page = _page(metadata, values, limit=limit, sort_key=lambda row: (str(row["_sortOrdinal"]),))
        cleaned = [_without(item, "_sortOrdinal") for item in page.resource.data or ()]
        return V2Page(
            V2Resource(
                page.resource.as_of,
                page.resource.generated_at,
                page.resource.component_revision,
                page.resource.quality,
                cleaned,
            ),
            page.next_sort_key,
            page.total,
        )

    def events(
        self,
        as_of: date,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        metadata = self._chapter_resource(as_of, "events", "market-events")
        if metadata is None:
            return None
        rows = self.connection.execute(
            text(
                """WITH aggregate AS (
                    SELECT payload_json FROM materialized_market_environment
                    WHERE as_of=:as_of
                )
                SELECT item.value AS payload,item.ordinality
                FROM aggregate
                CROSS JOIN LATERAL jsonb_array_elements(
                    COALESCE(aggregate.payload_json->'chapter01'->'events'->'items','[]'::jsonb)
                ) WITH ORDINALITY item(value,ordinality)
                WHERE (:after_ordinal IS NULL OR item.ordinality>:after_ordinal)
                ORDER BY item.ordinality
                LIMIT :limit"""
            ),
            {
                "as_of": as_of,
                "after_ordinal": int(after[0]) if after else None,
                "limit": limit + 1,
            },
        ).mappings()
        values = [
            {**_mapping(_json_load(row["payload"], {})), "_sortOrdinal": int(row["ordinality"])}
            for row in rows
        ]
        page = _page(metadata, values, limit=limit, sort_key=lambda row: (str(row["_sortOrdinal"]),))
        return V2Page(
            V2Resource(
                page.resource.as_of,
                page.resource.generated_at,
                page.resource.component_revision,
                page.resource.quality,
                [_without(item, "_sortOrdinal") for item in page.resource.data or ()],
            ),
            page.next_sort_key,
            page.total,
        )

    def assessment(self, as_of: date) -> V2Resource | None:
        return self._chapter_resource(as_of, "assessment", "market-assessment")

    def operation_summary(self, run_id: str) -> V2Resource | None:
        row = self.connection.execute(
            text("SELECT * FROM ths_operations WHERE run_id=:run_id"),
            {"run_id": run_id},
        ).mappings().first()
        if row is None:
            return None
        data = {
            "runId": row["run_id"],
            "kind": row["kind"],
            "status": row["status"],
            "progress": {
                "completed": row["completed_items"],
                "total": row["total_items"],
                "failed": row["failed_items"],
                "conflicts": row["conflict_items"],
            },
            "requestBudget": row.get("request_budget"),
            "requestsUsed": row.get("requests_used"),
            "warning": row.get("warning"),
            "requestedAt": row.get("requested_at"),
            "startedAt": row.get("started_at"),
            "completedAt": row.get("completed_at"),
        }
        generated_at = str(row.get("completed_at") or row.get("started_at") or row["requested_at"])
        revision = f"operation:{row['request_checksum']}:{row['status']}:{row['completed_items']}:{row['failed_items']}:{row['conflict_items']}"
        return V2Resource(
            as_of=None,
            generated_at=generated_at,
            component_revision=revision,
            quality={"dataset": "ths-operation", "status": row["status"], "warnings": []},
            data=data,
        )

    def operation_checkpoints(
        self,
        run_id: str,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None:
        metadata = self.operation_summary(run_id)
        if metadata is None:
            return None
        rows = self.connection.execute(
            text(
                """SELECT * FROM ths_backfill_checkpoints
                WHERE run_id=:run_id
                  AND (:after_code IS NULL OR
                       (thscode,window_start,window_end)>
                       (:after_code,:after_start,:after_end))
                ORDER BY thscode,window_start,window_end
                LIMIT :limit"""
            ),
            {
                "run_id": run_id,
                "after_code": after[0] if after else None,
                "after_start": date.fromisoformat(after[1]) if after else None,
                "after_end": date.fromisoformat(after[2]) if after else None,
                "limit": limit + 1,
            },
        ).mappings()
        values = [
            {
                "thscode": row["thscode"],
                "windowStart": row["window_start"],
                "windowEnd": row["window_end"],
                "status": row["status"],
                "sourceRevision": row.get("source_revision"),
                "rowsWritten": row.get("rows_written"),
                "rowsSkipped": row.get("rows_skipped"),
                "conflicts": row.get("conflicts"),
                "warning": row.get("warning"),
            }
            for row in rows
        ]
        return _page(
            metadata,
            values,
            limit=limit,
            sort_key=lambda row: (
                str(row["thscode"]),
                row["windowStart"].isoformat(),
                row["windowEnd"].isoformat(),
            ),
        )


class PostgresV2MarketDataReadService:
    """Port implementation that owns short-lived PostgreSQL read connections."""

    def __init__(self, connection_factory: Callable[[], Connection]) -> None:
        self.connection_factory = connection_factory

    def _call(self, method: str, *args, **kwargs):
        with self.connection_factory() as connection:
            return getattr(PostgresV2MarketDataReadAdapter(connection), method)(
                *args,
                **kwargs,
            )

    def overview(self, as_of): return self._call("overview", as_of)
    def indices(self, as_of): return self._call("indices", as_of)
    def index(self, as_of, code): return self._call("index", as_of, code)
    def index_history(self, as_of, code, **kwargs): return self._call("index_history", as_of, code, **kwargs)
    def breadth(self, as_of): return self._call("breadth", as_of)
    def breadth_history(self, as_of, **kwargs): return self._call("breadth_history", as_of, **kwargs)
    def limits(self, as_of): return self._call("limits", as_of)
    def limits_pool(self, as_of, pool_type, **kwargs): return self._call("limits_pool", as_of, pool_type, **kwargs)
    def limits_history(self, as_of, **kwargs): return self._call("limits_history", as_of, **kwargs)
    def limits_evidence(self, as_of): return self._call("limits_evidence", as_of)
    def sector_rankings(self, as_of, **kwargs): return self._call("sector_rankings", as_of, **kwargs)
    def sector_turnover(self, as_of, **kwargs): return self._call("sector_turnover", as_of, **kwargs)
    def sector_breadth(self, as_of, **kwargs): return self._call("sector_breadth", as_of, **kwargs)
    def sector_analysis(self, as_of): return self._call("sector_analysis", as_of)
    def active_direction(self, as_of, **kwargs): return self._call("active_direction", as_of, **kwargs)
    def events(self, as_of, **kwargs): return self._call("events", as_of, **kwargs)
    def assessment(self, as_of): return self._call("assessment", as_of)
    def operation_summary(self, run_id): return self._call("operation_summary", run_id)
    def operation_checkpoints(self, run_id, **kwargs): return self._call("operation_checkpoints", run_id, **kwargs)


__all__ = [
    "PostgresV2MarketDataReadAdapter",
    "PostgresV2MarketDataReadService",
]
