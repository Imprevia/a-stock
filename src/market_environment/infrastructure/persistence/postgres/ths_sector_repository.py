"""Normalized PostgreSQL persistence for provider-observed THS sector facts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Connection, text

from ....application.ports.repositories import ThsSectorRepository
from ....domain.models.ths_sector import (
    THS_TAGS,
    ThsBackfillCheckpoint,
    ThsBackfillRun,
    ThsCatalogRelation,
    ThsCatalogRevision,
    ThsMemberDailyFact,
    ThsMemberRanking,
    ThsOperation,
    ThsRankingRow,
    ThsSectorBar,
    ThsSectorBreadth,
    ThsSectorMembership,
    normalize_thscode,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def _checksum(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _catalog_revision(row: Mapping[str, Any]) -> ThsCatalogRevision:
    return ThsCatalogRevision(
        revision_id=str(row["revision_id"]),
        capability_revision=str(row["capability_revision"]),
        provider_timestamp=_datetime(row["provider_timestamp"]),
        fetched_at=_datetime(row["fetched_at"]),
        tag_counts={str(key): int(value) for key, value in _load(row["tag_counts_json"], {}).items()},
        checksum=str(row["checksum"]),
        source=str(row["provider"]),
    )


def _bar(row: Mapping[str, Any]) -> ThsSectorBar:
    return ThsSectorBar(
        thscode=str(row["thscode"]),
        trading_date=_date(row["trading_date"]),  # type: ignore[arg-type]
        open=row.get("open"),
        high=row.get("high"),
        low=row.get("low"),
        close=row.get("close"),
        volume=row.get("volume"),
        turnover=row.get("turnover"),
        source=str(row["provider"]),
        source_revision=str(row["source_revision"]),
        checksum=str(row["checksum"]),
        fetched_at=_datetime(row["fetched_at"]),
        quality=str(row["quality_status"]),
        warnings=tuple(str(item) for item in _load(row.get("warnings_json"), [])),
    )


def _checkpoint(row: Mapping[str, Any]) -> ThsBackfillCheckpoint:
    return ThsBackfillCheckpoint(
        run_id=str(row["run_id"]),
        thscode=str(row["thscode"]),
        window_start=_date(row["window_start"]),  # type: ignore[arg-type]
        window_end=_date(row["window_end"]),  # type: ignore[arg-type]
        status=str(row["status"]),
        source_revision=str(row["source_revision"]),
        rows_written=int(row["rows_written"]),
        rows_skipped=int(row["rows_skipped"]),
        conflicts=int(row["conflicts"]),
        warning=row.get("warning"),
    )


class PostgresThsSectorRepository(ThsSectorRepository):
    """One transaction-scoped repository for all normalized THS facts."""

    def __init__(self, connection: Connection, *, now=_now) -> None:
        self.connection = connection
        self.now = now

    def put_catalog_revision(
        self,
        revision: ThsCatalogRevision,
        relations: Sequence[ThsCatalogRelation],
    ) -> ThsCatalogRevision:
        relation_keys = [(item.tag, item.thscode) for item in relations]
        if len(relation_keys) != len(set(relation_keys)):
            raise ValueError("catalog relations contain duplicate tag/code keys")
        if any(item.revision_id != revision.revision_id for item in relations):
            raise ValueError("catalog relation revision does not match envelope")
        actual_counts = Counter(item.tag for item in relations)
        if dict(actual_counts) != dict(revision.tag_counts):
            raise ValueError("catalog relation counts do not match revision envelope")

        existing = self.connection.execute(
            text("SELECT * FROM ths_catalog_revisions WHERE revision_id=:revision_id"),
            {"revision_id": revision.revision_id},
        ).mappings().first()
        if existing is not None:
            if (
                str(existing["checksum"]) != revision.checksum
                or str(existing["provider"]) != revision.source
                or str(existing["capability_revision"]) != revision.capability_revision
                or _datetime(existing["provider_timestamp"]) != revision.provider_timestamp.astimezone(timezone.utc)
                or _datetime(existing["fetched_at"]) != revision.fetched_at.astimezone(timezone.utc)
                or dict(_load(existing["tag_counts_json"], {})) != dict(revision.tag_counts)
            ):
                raise ValueError("conflicting THS catalog revision checksum")
            stored_relations = self.count_catalog(revision_id=revision.revision_id)
            if stored_relations not in (0, len(relations)):
                raise ValueError("stored THS catalog revision is incomplete")

        tag_checksums = {
            tag: _checksum(
                sorted(
                    ({"thscode": item.thscode, "name": item.name} for item in relations if item.tag == tag),
                    key=lambda item: (item["thscode"], item["name"]),
                )
            )
            for tag in THS_TAGS
        }
        self.connection.execute(
            text(
                """INSERT INTO ths_catalog_revisions
                (revision_id,provider,capability_revision,provider_timestamp,fetched_at,
                 row_count,tag_counts_json,tag_checksums_json,checksum)
                VALUES (:revision_id,:provider,:capability_revision,:provider_timestamp,:fetched_at,
                 :row_count,:tag_counts_json,:tag_checksums_json,:checksum)
                ON CONFLICT DO NOTHING"""
            ),
            {
                "revision_id": revision.revision_id,
                "provider": revision.source,
                "capability_revision": revision.capability_revision,
                "provider_timestamp": revision.provider_timestamp,
                "fetched_at": revision.fetched_at,
                "row_count": revision.row_count,
                "tag_counts_json": _json(dict(revision.tag_counts)),
                "tag_checksums_json": _json(tag_checksums),
                "checksum": revision.checksum,
            },
        )
        for relation in relations:
            self.connection.execute(
                text(
                    """INSERT INTO ths_sector_identities
                    (provider,thscode,first_seen_revision_id,created_at)
                    VALUES (:provider,:thscode,:revision_id,:created_at)
                    ON CONFLICT DO NOTHING"""
                ),
                {
                    "provider": revision.source,
                    "thscode": relation.thscode,
                    "revision_id": revision.revision_id,
                    "created_at": revision.fetched_at,
                },
            )
            relation_checksum = _checksum(
                {"tag": relation.tag, "thscode": relation.thscode, "name": relation.name}
            )
            conflict = self.connection.execute(
                text(
                    """SELECT display_name,relation_checksum FROM ths_catalog_relations
                    WHERE catalog_revision_id=:revision_id AND tag=:tag AND thscode=:thscode"""
                ),
                {
                    "revision_id": revision.revision_id,
                    "tag": relation.tag,
                    "thscode": relation.thscode,
                },
            ).mappings().first()
            if conflict is not None and (
                str(conflict["display_name"]) != relation.name
                or str(conflict["relation_checksum"]) != relation_checksum
            ):
                raise ValueError("conflicting THS catalog relation")
            self.connection.execute(
                text(
                    """INSERT INTO ths_catalog_relations
                    (catalog_revision_id,provider,tag,thscode,display_name,relation_checksum)
                    VALUES (:revision_id,:provider,:tag,:thscode,:display_name,:relation_checksum)
                    ON CONFLICT DO NOTHING"""
                ),
                {
                    "revision_id": revision.revision_id,
                    "provider": revision.source,
                    "tag": relation.tag,
                    "thscode": relation.thscode,
                    "display_name": relation.name,
                    "relation_checksum": relation_checksum,
                },
            )
        return revision

    def get_catalog_revision(self, revision_id: str) -> ThsCatalogRevision | None:
        row = self.connection.execute(
            text("SELECT * FROM ths_catalog_revisions WHERE revision_id=:revision_id"),
            {"revision_id": revision_id},
        ).mappings().first()
        return _catalog_revision(row) if row is not None else None

    def latest_catalog_revision(self) -> ThsCatalogRevision | None:
        row = self.connection.execute(
            text(
                """SELECT * FROM ths_catalog_revisions
                ORDER BY provider_timestamp DESC,fetched_at DESC,revision_id DESC LIMIT 1"""
            )
        ).mappings().first()
        return _catalog_revision(row) if row is not None else None

    def _catalog_filter(
        self,
        *,
        tag: str | None,
        search: str | None,
        revision_id: str | None,
    ) -> tuple[str, dict[str, Any]]:
        selected_revision = revision_id
        if selected_revision is None:
            latest = self.latest_catalog_revision()
            if latest is None:
                return "1=0", {}
            selected_revision = latest.revision_id
        where = ["catalog_revision_id=:revision_id"]
        params: dict[str, Any] = {"revision_id": selected_revision}
        if tag is not None:
            where.append("tag=:tag")
            params["tag"] = tag
        if search:
            where.append("(LOWER(thscode) LIKE :search OR LOWER(display_name) LIKE :search)")
            params["search"] = f"%{search.lower()}%"
        return " AND ".join(where), params

    def list_catalog(
        self,
        *,
        tag: str | None = None,
        search: str | None = None,
        revision_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[ThsCatalogRelation]:
        where, params = self._catalog_filter(tag=tag, search=search, revision_id=revision_id)
        rows = self.connection.execute(
            text(
                f"""SELECT * FROM ths_catalog_relations WHERE {where}
                ORDER BY tag,thscode LIMIT :limit OFFSET :offset"""
            ),
            {**params, "limit": limit, "offset": offset},
        ).mappings()
        return tuple(
            ThsCatalogRelation(
                revision_id=str(row["catalog_revision_id"]),
                tag=str(row["tag"]),
                thscode=str(row["thscode"]),
                name=str(row["display_name"]),
            )
            for row in rows
        )

    def count_catalog(
        self,
        *,
        tag: str | None = None,
        search: str | None = None,
        revision_id: str | None = None,
    ) -> int:
        where, params = self._catalog_filter(tag=tag, search=search, revision_id=revision_id)
        return int(
            self.connection.execute(
                text(f"SELECT COUNT(*) FROM ths_catalog_relations WHERE {where}"), params
            ).scalar_one()
        )

    def put_rankings(self, rankings: Iterable[ThsRankingRow]) -> Mapping[str, int]:
        counts: Counter[str] = Counter()
        for ranking in rankings:
            payload = {
                "tag": ranking.tag,
                "rank": ranking.rank,
                "thscode": ranking.thscode,
                "name": ranking.name,
                "change_pct": ranking.change_pct,
                "volume": ranking.volume,
                "turnover": ranking.turnover,
                "catalog_revision": ranking.catalog_revision,
                "as_of": ranking.as_of.isoformat(),
            }
            checksum = _checksum(payload)
            key = {
                "provider": "fuyao",
                "as_of": ranking.as_of,
                "catalog_revision_id": ranking.catalog_revision,
                "tag": ranking.tag,
                "thscode": ranking.thscode,
            }
            existing = self.connection.execute(
                text(
                    """SELECT checksum FROM ths_industry_rankings
                    WHERE provider=:provider AND as_of=:as_of
                      AND catalog_revision_id=:catalog_revision_id AND tag=:tag
                      AND thscode=:thscode"""
                ),
                key,
            ).scalar_one_or_none()
            if existing is not None:
                counts["identical" if str(existing) == checksum else "conflict"] += 1
                continue
            revision = self.get_catalog_revision(ranking.catalog_revision)
            if revision is None:
                raise ValueError(f"unknown THS catalog revision: {ranking.catalog_revision}")
            self.connection.execute(
                text(
                    """INSERT INTO ths_industry_rankings
                    (provider,as_of,catalog_revision_id,tag,thscode,rank,display_name,
                     change_pct,volume,turnover,source_revision,provider_timestamp,
                     fetched_at,checksum,quality_status,warnings_json)
                    VALUES (:provider,:as_of,:catalog_revision_id,:tag,:thscode,:rank,:display_name,
                     :change_pct,:volume,:turnover,:source_revision,:provider_timestamp,
                     :fetched_at,:checksum,'ok','[]')"""
                ),
                {
                    **key,
                    "rank": ranking.rank,
                    "display_name": ranking.name,
                    "change_pct": ranking.change_pct,
                    "volume": ranking.volume,
                    "turnover": ranking.turnover,
                    "source_revision": revision.capability_revision,
                    "provider_timestamp": revision.provider_timestamp,
                    "fetched_at": revision.fetched_at,
                    "checksum": checksum,
                },
            )
            counts["inserted"] += 1
        return {key: int(counts.get(key, 0)) for key in ("inserted", "identical", "conflict")}

    def list_rankings(
        self,
        as_of: date,
        *,
        tag: str | None = None,
        revision_id: str | None = None,
    ) -> Sequence[ThsRankingRow]:
        where = ["provider='fuyao'", "as_of=:as_of"]
        params: dict[str, Any] = {"as_of": as_of}
        if tag is not None:
            where.append("tag=:tag")
            params["tag"] = tag
        if revision_id is not None:
            where.append("catalog_revision_id=:revision_id")
            params["revision_id"] = revision_id
        rows = self.connection.execute(
            text(
                f"""SELECT * FROM ths_industry_rankings WHERE {' AND '.join(where)}
                ORDER BY tag,rank,thscode"""
            ),
            params,
        ).mappings()
        return tuple(
            ThsRankingRow(
                tag=str(row["tag"]),
                rank=int(row["rank"]),
                thscode=str(row["thscode"]),
                name=str(row["display_name"]),
                change_pct=float(row["change_pct"]),
                volume=row.get("volume"),
                turnover=row.get("turnover"),
                catalog_revision=str(row["catalog_revision_id"]),
                as_of=_date(row["as_of"]),  # type: ignore[arg-type]
            )
            for row in rows
        )

    def put_sector_bar(self, bar: ThsSectorBar) -> str:
        existing = self.connection.execute(
            text(
                """SELECT checksum FROM ths_sector_daily_bars
                WHERE provider=:provider AND thscode=:thscode AND trading_date=:trading_date
                  AND source_revision=:source_revision"""
            ),
            {
                "provider": bar.source,
                "thscode": bar.thscode,
                "trading_date": bar.trading_date,
                "source_revision": bar.source_revision,
            },
        ).scalar_one_or_none()
        if existing is not None:
            return "identical" if str(existing) == bar.checksum else "conflict"
        field_quality = {
            field: "ok" if getattr(bar, field) is not None else "missing"
            for field in ("open", "high", "low", "close", "volume", "turnover")
        }
        self.connection.execute(
            text(
                """INSERT INTO ths_sector_daily_bars
                (provider,thscode,trading_date,open,high,low,close,volume,turnover,
                 source_revision,checksum,provider_timestamp,fetched_at,quality_status,
                 field_quality_json,warnings_json)
                VALUES (:provider,:thscode,:trading_date,:open,:high,:low,:close,:volume,:turnover,
                 :source_revision,:checksum,:provider_timestamp,:fetched_at,:quality_status,
                 :field_quality_json,:warnings_json)"""
            ),
            {
                "provider": bar.source,
                "thscode": bar.thscode,
                "trading_date": bar.trading_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "turnover": bar.turnover,
                "source_revision": bar.source_revision,
                "checksum": bar.checksum,
                "provider_timestamp": None,
                "fetched_at": bar.fetched_at,
                "quality_status": bar.quality,
                "field_quality_json": _json(field_quality),
                "warnings_json": _json(list(bar.warnings)),
            },
        )
        return "inserted"

    def put_sector_bars(self, bars: Iterable[ThsSectorBar]) -> Mapping[str, int]:
        counts = Counter(self.put_sector_bar(bar) for bar in bars)
        return {key: int(counts.get(key, 0)) for key in ("inserted", "identical", "conflict")}

    def _bars_filter(
        self,
        thscode: str,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[str, dict[str, Any]]:
        where = ["provider='fuyao'", "thscode=:thscode"]
        params: dict[str, Any] = {"thscode": normalize_thscode(thscode)}
        if start_date is not None:
            where.append("trading_date>=:start_date")
            params["start_date"] = start_date
        if end_date is not None:
            where.append("trading_date<=:end_date")
            params["end_date"] = end_date
        return " AND ".join(where), params

    def list_sector_bars(
        self,
        thscode: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> Sequence[ThsSectorBar]:
        where, params = self._bars_filter(thscode, start_date=start_date, end_date=end_date)
        rows = self.connection.execute(
            text(
                f"""SELECT * FROM (
                    SELECT b.*,ROW_NUMBER() OVER (
                        PARTITION BY trading_date ORDER BY fetched_at DESC,source_revision DESC
                    ) AS revision_rank
                    FROM ths_sector_daily_bars b WHERE {where}
                ) selected WHERE revision_rank=1
                ORDER BY trading_date LIMIT :limit OFFSET :offset"""
            ),
            {**params, "limit": limit, "offset": offset},
        ).mappings()
        return tuple(_bar(row) for row in rows)

    def count_sector_bars(
        self,
        thscode: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        where, params = self._bars_filter(thscode, start_date=start_date, end_date=end_date)
        return int(
            self.connection.execute(
                text(f"SELECT COUNT(DISTINCT trading_date) FROM ths_sector_daily_bars WHERE {where}"),
                params,
            ).scalar_one()
        )

    def sector_bar_coverage(
        self,
        thscode: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Mapping[str, Any]:
        where, params = self._bars_filter(thscode, start_date=start_date, end_date=end_date)
        row = self.connection.execute(
            text(
                f"""SELECT MIN(trading_date) AS first_date,MAX(trading_date) AS last_date,
                COUNT(DISTINCT trading_date) AS stored_rows,
                COUNT(DISTINCT CASE WHEN quality_status='ok' THEN trading_date END) AS ok_rows
                FROM ths_sector_daily_bars WHERE {where}"""
            ),
            params,
        ).mappings().one()
        return {
            "first_date": _date(row["first_date"]),
            "last_date": _date(row["last_date"]),
            "stored_rows": int(row["stored_rows"] or 0),
            "ok_rows": int(row["ok_rows"] or 0),
        }

    def put_operation(self, operation: ThsOperation) -> ThsOperation:
        existing = self.connection.execute(
            text(
                """SELECT request_checksum,request_json,kind,capability_revision,request_budget
                FROM ths_operations WHERE run_id=:run_id"""
            ),
            {"run_id": operation.run_id},
        ).mappings().first()
        if existing is not None and (
            str(existing["request_checksum"]) != operation.request_checksum
            or str(existing["kind"]) != operation.kind
            or str(existing["capability_revision"]) != operation.capability_revision
            or dict(_load(existing["request_json"], {})) != dict(operation.request_metadata)
            or int(existing["request_budget"]) != (operation.request_budget or 0)
        ):
            raise ValueError("conflicting THS operation identity")
        self.connection.execute(
            text(
                """INSERT INTO ths_operations
                (run_id,kind,status,capability_revision,request_checksum,request_json,
                 progress_json,result_json,total_items,completed_items,failed_items,
                 conflict_items,request_budget,requests_used,warning,requested_at,
                 started_at,completed_at)
                VALUES (:run_id,:kind,:status,:capability_revision,:request_checksum,:request_json,
                 :progress_json,:result_json,:total_items,:completed_items,:failed_items,
                 :conflict_items,:request_budget,:requests_used,:warning,:requested_at,
                 :started_at,:completed_at)
                ON CONFLICT(run_id) DO UPDATE SET status=excluded.status,
                 progress_json=excluded.progress_json,result_json=excluded.result_json,
                 total_items=excluded.total_items,completed_items=excluded.completed_items,
                 failed_items=excluded.failed_items,conflict_items=excluded.conflict_items,
                 request_budget=excluded.request_budget,requests_used=excluded.requests_used,
                 warning=excluded.warning,started_at=excluded.started_at,
                 completed_at=excluded.completed_at"""
            ),
            {
                "run_id": operation.run_id,
                "kind": operation.kind,
                "status": operation.status,
                "capability_revision": operation.capability_revision,
                "request_checksum": operation.request_checksum,
                "request_json": _json(dict(operation.request_metadata)),
                "progress_json": _json(dict(operation.progress)),
                "result_json": _json(dict(operation.result)),
                "total_items": operation.total_items,
                "completed_items": operation.completed_items,
                "failed_items": operation.failed_items,
                "conflict_items": operation.conflict_items,
                "request_budget": operation.request_budget or 0,
                "requests_used": operation.requests_used,
                "warning": operation.warning,
                "requested_at": operation.requested_at,
                "started_at": operation.started_at,
                "completed_at": operation.completed_at,
            },
        )
        return operation

    update_operation = put_operation

    def get_operation(self, run_id: str) -> ThsOperation | None:
        row = self.connection.execute(
            text("SELECT * FROM ths_operations WHERE run_id=:run_id"), {"run_id": run_id}
        ).mappings().first()
        return self._operation(row) if row is not None else None

    def list_operations(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[ThsOperation]:
        where = ["1=1"]
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if kind is not None:
            where.append("kind=:kind")
            params["kind"] = kind
        if status is not None:
            where.append("status=:status")
            params["status"] = status
        rows = self.connection.execute(
            text(
                f"""SELECT * FROM ths_operations WHERE {' AND '.join(where)}
                ORDER BY requested_at DESC,run_id LIMIT :limit OFFSET :offset"""
            ),
            params,
        ).mappings()
        return tuple(self._operation(row) for row in rows)

    @staticmethod
    def _operation(row: Mapping[str, Any]) -> ThsOperation:
        return ThsOperation(
            run_id=str(row["run_id"]),
            kind=str(row["kind"]),
            status=str(row["status"]),
            capability_revision=str(row["capability_revision"]),
            request_checksum=str(row["request_checksum"]),
            request_metadata=dict(_load(row["request_json"], {})),
            progress=dict(_load(row["progress_json"], {})),
            result=dict(_load(row["result_json"], {})),
            total_items=int(row["total_items"]),
            completed_items=int(row["completed_items"]),
            failed_items=int(row["failed_items"]),
            conflict_items=int(row["conflict_items"]),
            request_budget=(int(row["request_budget"]) or None),
            requests_used=int(row["requests_used"]),
            warning=row.get("warning"),
            requested_at=_datetime(row["requested_at"]),
            started_at=_datetime(row["started_at"]) if row.get("started_at") is not None else None,
            completed_at=_datetime(row["completed_at"]) if row.get("completed_at") is not None else None,
        )

    def put_backfill_run(self, run: ThsBackfillRun) -> ThsBackfillRun:
        request_payload = {
            "thscodes": list(run.thscodes),
            "start_date": run.start_date.isoformat(),
            "end_date": run.end_date.isoformat(),
            "request_budget": run.request_budget,
        }
        request_checksum = _checksum({**request_payload, "capability_revision": run.capability_revision})
        existing_operation = self.get_operation(run.run_id)
        requested_at = existing_operation.requested_at if existing_operation else self.now()
        started_at = existing_operation.started_at if existing_operation else None
        if started_at is None and run.status != "queued":
            started_at = self.now()
        completed_at = existing_operation.completed_at if existing_operation else None
        if run.status in {"success", "partial", "failed", "conflict"}:
            completed_at = completed_at or self.now()
        self.put_operation(
            ThsOperation(
                run_id=run.run_id,
                kind="turnover-backfill",
                status=run.status,
                capability_revision=run.capability_revision,
                request_checksum=request_checksum,
                request_metadata=request_payload,
                total_items=len(run.thscodes),
                request_budget=run.request_budget,
                requests_used=run.requests_used,
                warning=run.warning,
                requested_at=requested_at,
                started_at=started_at,
                completed_at=completed_at,
            )
        )
        existing = self.connection.execute(
            text("SELECT requested_codes_json,start_date,end_date FROM ths_backfill_runs WHERE run_id=:run_id"),
            {"run_id": run.run_id},
        ).mappings().first()
        if existing is not None and (
            tuple(_load(existing["requested_codes_json"], [])) != run.thscodes
            or _date(existing["start_date"]) != run.start_date
            or _date(existing["end_date"]) != run.end_date
        ):
            raise ValueError("conflicting THS backfill run identity")
        self.connection.execute(
            text(
                """INSERT INTO ths_backfill_runs
                (run_id,provider,requested_codes_json,start_date,end_date)
                VALUES (:run_id,'fuyao',:requested_codes_json,:start_date,:end_date)
                ON CONFLICT DO NOTHING"""
            ),
            {
                "run_id": run.run_id,
                "requested_codes_json": _json(list(run.thscodes)),
                "start_date": run.start_date,
                "end_date": run.end_date,
            },
        )
        return run

    def get_backfill_run(self, run_id: str) -> ThsBackfillRun | None:
        row = self.connection.execute(
            text(
                """SELECT b.*,o.capability_revision,o.request_budget,o.requests_used,
                o.status,o.warning,o.requested_at FROM ths_backfill_runs b
                JOIN ths_operations o ON o.run_id=b.run_id WHERE b.run_id=:run_id"""
            ),
            {"run_id": run_id},
        ).mappings().first()
        return self._run(row) if row is not None else None

    def list_backfill_runs(self, *, offset: int = 0, limit: int = 100) -> Sequence[ThsBackfillRun]:
        rows = self.connection.execute(
            text(
                """SELECT b.*,o.capability_revision,o.request_budget,o.requests_used,
                o.status,o.warning,o.requested_at FROM ths_backfill_runs b
                JOIN ths_operations o ON o.run_id=b.run_id
                ORDER BY o.requested_at DESC,b.run_id LIMIT :limit OFFSET :offset"""
            ),
            {"limit": limit, "offset": offset},
        ).mappings()
        return tuple(self._run(row) for row in rows)

    @staticmethod
    def _run(row: Mapping[str, Any]) -> ThsBackfillRun:
        return ThsBackfillRun(
            run_id=str(row["run_id"]),
            thscodes=tuple(str(item) for item in _load(row["requested_codes_json"], [])),
            start_date=_date(row["start_date"]),  # type: ignore[arg-type]
            end_date=_date(row["end_date"]),  # type: ignore[arg-type]
            capability_revision=str(row["capability_revision"]),
            request_budget=int(row["request_budget"]),
            status=str(row["status"]),
            requests_used=int(row["requests_used"]),
            warning=row.get("warning"),
        )

    def put_backfill_checkpoint(self, checkpoint: ThsBackfillCheckpoint) -> ThsBackfillCheckpoint:
        result_checksum = _checksum(
            {
                "source_revision": checkpoint.source_revision,
                "rows_written": checkpoint.rows_written,
                "rows_skipped": checkpoint.rows_skipped,
                "conflicts": checkpoint.conflicts,
            }
        )
        now = self.now()
        existing = self.connection.execute(
            text(
                """SELECT source_revision FROM ths_backfill_checkpoints
                WHERE run_id=:run_id AND thscode=:thscode
                  AND window_start=:window_start AND window_end=:window_end"""
            ),
            {
                "run_id": checkpoint.run_id,
                "thscode": checkpoint.thscode,
                "window_start": checkpoint.window_start,
                "window_end": checkpoint.window_end,
            },
        ).scalar_one_or_none()
        if existing is not None and str(existing) != checkpoint.source_revision:
            raise ValueError("conflicting THS backfill checkpoint source revision")
        self.connection.execute(
            text(
                """INSERT INTO ths_backfill_checkpoints
                (run_id,provider,thscode,window_start,window_end,status,source_revision,
                 rows_written,rows_skipped,conflicts,result_checksum,started_at,completed_at,warning)
                VALUES (:run_id,'fuyao',:thscode,:window_start,:window_end,:status,:source_revision,
                 :rows_written,:rows_skipped,:conflicts,:result_checksum,:started_at,:completed_at,:warning)
                ON CONFLICT(run_id,thscode,window_start,window_end) DO UPDATE SET
                 status=excluded.status,source_revision=excluded.source_revision,
                 rows_written=excluded.rows_written,rows_skipped=excluded.rows_skipped,
                 conflicts=excluded.conflicts,result_checksum=excluded.result_checksum,
                 started_at=COALESCE(ths_backfill_checkpoints.started_at,excluded.started_at),
                 completed_at=excluded.completed_at,warning=excluded.warning"""
            ),
            {
                "run_id": checkpoint.run_id,
                "thscode": checkpoint.thscode,
                "window_start": checkpoint.window_start,
                "window_end": checkpoint.window_end,
                "status": checkpoint.status,
                "source_revision": checkpoint.source_revision,
                "rows_written": checkpoint.rows_written,
                "rows_skipped": checkpoint.rows_skipped,
                "conflicts": checkpoint.conflicts,
                "result_checksum": result_checksum,
                "started_at": now,
                "completed_at": now if checkpoint.status in {"success", "partial", "failed", "conflict"} else None,
                "warning": checkpoint.warning,
            },
        )
        return checkpoint

    def list_backfill_checkpoints(self, run_id: str) -> Sequence[ThsBackfillCheckpoint]:
        rows = self.connection.execute(
            text(
                """SELECT * FROM ths_backfill_checkpoints WHERE run_id=:run_id
                ORDER BY thscode,window_start,window_end"""
            ),
            {"run_id": run_id},
        ).mappings()
        return tuple(_checkpoint(row) for row in rows)

    def put_member_fact(self, fact: ThsMemberDailyFact) -> str:
        existing = self.connection.execute(
            text(
                """SELECT checksum FROM ths_member_daily_facts
                WHERE security_id=:security_id AND trading_date=:trading_date
                  AND source_revision=:source_revision"""
            ),
            {
                "security_id": fact.security_id,
                "trading_date": fact.trading_date,
                "source_revision": fact.source_revision,
            },
        ).scalar_one_or_none()
        if existing is not None:
            return "identical" if str(existing) == fact.checksum else "conflict"
        sources = sorted({str(value) for value in fact.field_lineage.values() if str(value).strip()})
        source = sources[0] if len(sources) == 1 else "mixed"
        self.connection.execute(
            text(
                """INSERT INTO ths_member_daily_facts
                (security_id,trading_date,original_open,original_high,original_low,original_close,
                 adjusted_close,adjustment_factor,volume,turnover,source,source_revision,checksum,
                 quality_status,field_lineage_json,warnings_json,fetched_at)
                VALUES (:security_id,:trading_date,:original_open,:original_high,:original_low,:original_close,
                 :adjusted_close,:adjustment_factor,:volume,:turnover,:source,:source_revision,:checksum,
                 :quality_status,:field_lineage_json,:warnings_json,:fetched_at)"""
            ),
            {
                "security_id": fact.security_id,
                "trading_date": fact.trading_date,
                "original_open": fact.original_open,
                "original_high": fact.original_high,
                "original_low": fact.original_low,
                "original_close": fact.original_close,
                "adjusted_close": fact.adjusted_close,
                "adjustment_factor": fact.adjustment_factor,
                "volume": fact.volume,
                "turnover": fact.turnover,
                "source": source,
                "source_revision": fact.source_revision,
                "checksum": fact.checksum,
                "quality_status": fact.quality,
                "field_lineage_json": _json(dict(fact.field_lineage)),
                "warnings_json": _json(list(fact.warnings)),
                "fetched_at": self.now(),
            },
        )
        return "inserted"

    def list_member_facts(self, trading_date: date) -> Sequence[ThsMemberDailyFact]:
        rows = self.connection.execute(
            text(
                """SELECT * FROM ths_member_daily_facts WHERE trading_date=:trading_date
                ORDER BY security_id,source_revision"""
            ),
            {"trading_date": trading_date},
        ).mappings()
        return tuple(
            ThsMemberDailyFact(
                security_id=str(row["security_id"]),
                trading_date=_date(row["trading_date"]),  # type: ignore[arg-type]
                original_open=row.get("original_open"),
                original_high=row.get("original_high"),
                original_low=row.get("original_low"),
                original_close=row.get("original_close"),
                adjusted_close=row.get("adjusted_close"),
                adjustment_factor=row.get("adjustment_factor"),
                volume=row.get("volume"),
                turnover=row.get("turnover"),
                quality=str(row["quality_status"]),
                source_revision=str(row["source_revision"]),
                checksum=str(row["checksum"]),
                field_lineage=dict(_load(row["field_lineage_json"], {})),
                warnings=tuple(str(item) for item in _load(row.get("warnings_json"), [])),
            )
            for row in rows
        )

    def put_sector_memberships(
        self,
        memberships: Iterable[ThsSectorMembership],
    ) -> Mapping[str, int]:
        counts: Counter[str] = Counter()
        for membership in memberships:
            key = {
                "provider": "fuyao",
                "thscode": membership.thscode,
                "member_security_id": membership.member_security_id,
                "membership_as_of": membership.as_of,
                "source_revision": membership.source_revision,
            }
            existing = self.connection.execute(
                text(
                    """SELECT checksum FROM ths_sector_memberships
                    WHERE provider=:provider AND thscode=:thscode
                      AND member_security_id=:member_security_id
                      AND membership_as_of=:membership_as_of
                      AND source_revision=:source_revision"""
                ),
                key,
            ).scalar_one_or_none()
            if existing is not None:
                counts["identical" if str(existing) == membership.checksum else "conflict"] += 1
                continue
            self.connection.execute(
                text(
                    """INSERT INTO ths_sector_memberships
                    (provider,thscode,member_security_id,membership_as_of,source_revision,
                     member_name,provider_timestamp,fetched_at,checksum,quality_status,warnings_json)
                    VALUES (:provider,:thscode,:member_security_id,:membership_as_of,:source_revision,
                     :member_name,:provider_timestamp,:fetched_at,:checksum,:quality_status,:warnings_json)"""
                ),
                {
                    **key,
                    "member_name": membership.member_name,
                    "provider_timestamp": membership.provider_timestamp,
                    "fetched_at": membership.fetched_at,
                    "checksum": membership.checksum,
                    "quality_status": membership.quality,
                    "warnings_json": _json(list(membership.warnings)),
                },
            )
            counts["inserted"] += 1
        return {key: int(counts.get(key, 0)) for key in ("inserted", "identical", "conflict")}

    def list_sector_memberships(
        self,
        thscode: str,
        *,
        as_of: date | None = None,
        source_revision: str | None = None,
    ) -> Sequence[ThsSectorMembership]:
        where = ["provider='fuyao'", "thscode=:thscode"]
        params: dict[str, Any] = {"thscode": normalize_thscode(thscode)}
        if as_of is not None:
            where.append("membership_as_of=:as_of")
            params["as_of"] = as_of
        if source_revision is not None:
            where.append("source_revision=:source_revision")
            params["source_revision"] = source_revision
        rows = self.connection.execute(
            text(
                f"""SELECT * FROM ths_sector_memberships WHERE {' AND '.join(where)}
                ORDER BY membership_as_of DESC,member_security_id,source_revision"""
            ),
            params,
        ).mappings()
        return tuple(
            ThsSectorMembership(
                thscode=str(row["thscode"]),
                member_security_id=str(row["member_security_id"]),
                member_name=str(row.get("member_name") or row["member_security_id"]),
                as_of=_date(row["membership_as_of"]),  # type: ignore[arg-type]
                provider_timestamp=_datetime(row["provider_timestamp"]),
                fetched_at=_datetime(row["fetched_at"]),
                source_revision=str(row["source_revision"]),
                checksum=str(row["checksum"]),
                quality=str(row["quality_status"]),
                warnings=tuple(str(item) for item in _load(row["warnings_json"], [])),
            )
            for row in rows
        )

    def put_sector_breadth(self, breadth: ThsSectorBreadth) -> str:
        latest = self.latest_catalog_revision()
        catalog_revision = breadth.lineage.get("catalogRevision") or (
            latest.revision_id if latest is not None else None
        )
        if catalog_revision is None:
            raise ValueError("sector breadth requires a catalog revision")
        calculation_revision = breadth.lineage.get("calculationRevision", "ths-breadth-v1")
        payload = self._breadth_payload(breadth)
        checksum = _checksum(payload)
        key = {
            "provider": "fuyao",
            "thscode": breadth.thscode,
            "as_of": breadth.as_of,
            "catalog_revision_id": catalog_revision,
            "calculation_revision": calculation_revision,
        }
        existing = self.connection.execute(
            text(
                """SELECT checksum FROM ths_sector_breadth_evidence
                WHERE provider=:provider AND thscode=:thscode AND as_of=:as_of
                  AND catalog_revision_id=:catalog_revision_id
                  AND calculation_revision=:calculation_revision"""
            ),
            key,
        ).scalar_one_or_none()
        if existing is not None:
            return "identical" if str(existing) == checksum else "conflict"
        self.connection.execute(
            text(
                """INSERT INTO ths_sector_breadth_evidence
                (provider,thscode,as_of,catalog_revision_id,calculation_revision,
                 selection_reasons_json,member_count,valid_direction_count,advance_count,
                 decline_count,flat_count,advance_ratio,advance_decline_spread_ratio,
                 median_change_pct,valid_ma20_count,close_above_ma20_count,ma20_breadth,
                 limit_up_count,limit_down_count,top_by_turnover_json,top_by_gain_json,
                 max_member_turnover_contribution,diffusion_rate,quality_status,lineage_json,
                 warnings_json,checksum,fetched_at)
                VALUES (:provider,:thscode,:as_of,:catalog_revision_id,:calculation_revision,
                 :selection_reasons_json,:member_count,:valid_direction_count,:advance_count,
                 :decline_count,:flat_count,:advance_ratio,:advance_decline_spread_ratio,
                 :median_change_pct,:valid_ma20_count,:close_above_ma20_count,:ma20_breadth,
                 :limit_up_count,:limit_down_count,:top_by_turnover_json,:top_by_gain_json,
                 :max_member_turnover_contribution,:diffusion_rate,:quality_status,:lineage_json,
                 :warnings_json,:checksum,:fetched_at)"""
            ),
            {
                **key,
                "selection_reasons_json": _json(list(breadth.selection_reasons)),
                "member_count": breadth.member_count,
                "valid_direction_count": breadth.valid_direction_count,
                "advance_count": breadth.advance_count,
                "decline_count": breadth.decline_count,
                "flat_count": breadth.flat_count,
                "advance_ratio": breadth.advance_ratio,
                "advance_decline_spread_ratio": breadth.advance_decline_spread_ratio,
                "median_change_pct": breadth.median_change_pct,
                "valid_ma20_count": breadth.valid_ma20_count,
                "close_above_ma20_count": breadth.close_above_ma20_count,
                "ma20_breadth": breadth.ma20_breadth,
                "limit_up_count": breadth.limit_up_count,
                "limit_down_count": breadth.limit_down_count,
                "top_by_turnover_json": _json(payload["top_by_turnover"]),
                "top_by_gain_json": _json(payload["top_by_gain"]),
                "max_member_turnover_contribution": breadth.max_member_turnover_contribution,
                "diffusion_rate": breadth.diffusion_rate,
                "quality_status": breadth.quality,
                "lineage_json": _json(dict(breadth.lineage)),
                "warnings_json": _json(list(breadth.warnings)),
                "checksum": checksum,
                "fetched_at": self.now(),
            },
        )
        return "inserted"

    def list_sector_breadth(self, as_of: date) -> Sequence[ThsSectorBreadth]:
        rows = self.connection.execute(
            text(
                """SELECT * FROM ths_sector_breadth_evidence WHERE as_of=:as_of
                ORDER BY thscode,catalog_revision_id,calculation_revision"""
            ),
            {"as_of": as_of},
        ).mappings()
        return tuple(self._breadth(row) for row in rows)

    @staticmethod
    def _breadth_payload(value: ThsSectorBreadth) -> dict[str, Any]:
        return {
            "thscode": value.thscode,
            "as_of": value.as_of.isoformat(),
            "selection_reasons": list(value.selection_reasons),
            "member_count": value.member_count,
            "valid_direction_count": value.valid_direction_count,
            "advance_count": value.advance_count,
            "decline_count": value.decline_count,
            "flat_count": value.flat_count,
            "advance_ratio": value.advance_ratio,
            "advance_decline_spread_ratio": value.advance_decline_spread_ratio,
            "median_change_pct": value.median_change_pct,
            "valid_ma20_count": value.valid_ma20_count,
            "close_above_ma20_count": value.close_above_ma20_count,
            "ma20_breadth": value.ma20_breadth,
            "limit_up_count": value.limit_up_count,
            "limit_down_count": value.limit_down_count,
            "top_by_turnover": [
                {"security_id": item.security_id, "value": item.value}
                for item in value.top_by_turnover
            ],
            "top_by_gain": [
                {"security_id": item.security_id, "value": item.value}
                for item in value.top_by_gain
            ],
            "max_member_turnover_contribution": value.max_member_turnover_contribution,
            "diffusion_rate": value.diffusion_rate,
            "quality": value.quality,
            "warnings": list(value.warnings),
            "lineage": dict(value.lineage),
        }

    @staticmethod
    def _breadth(row: Mapping[str, Any]) -> ThsSectorBreadth:
        return ThsSectorBreadth(
            thscode=str(row["thscode"]),
            as_of=_date(row["as_of"]),  # type: ignore[arg-type]
            selection_reasons=tuple(str(item) for item in _load(row["selection_reasons_json"], [])),
            member_count=int(row["member_count"]),
            valid_direction_count=int(row["valid_direction_count"]),
            advance_count=int(row["advance_count"]),
            decline_count=int(row["decline_count"]),
            flat_count=int(row["flat_count"]),
            advance_ratio=row.get("advance_ratio"),
            advance_decline_spread_ratio=row.get("advance_decline_spread_ratio"),
            median_change_pct=row.get("median_change_pct"),
            valid_ma20_count=int(row["valid_ma20_count"]),
            close_above_ma20_count=int(row["close_above_ma20_count"]),
            ma20_breadth=row.get("ma20_breadth"),
            limit_up_count=row.get("limit_up_count"),
            limit_down_count=row.get("limit_down_count"),
            top_by_turnover=tuple(
                ThsMemberRanking(str(item["security_id"]), float(item["value"]))
                for item in _load(row["top_by_turnover_json"], [])
            ),
            top_by_gain=tuple(
                ThsMemberRanking(str(item["security_id"]), float(item["value"]))
                for item in _load(row["top_by_gain_json"], [])
            ),
            max_member_turnover_contribution=row.get("max_member_turnover_contribution"),
            diffusion_rate=row.get("diffusion_rate"),
            quality=str(row["quality_status"]),
            warnings=tuple(str(item) for item in _load(row["warnings_json"], [])),
            lineage=dict(_load(row["lineage_json"], {})),
        )


__all__ = ["PostgresThsSectorRepository"]
