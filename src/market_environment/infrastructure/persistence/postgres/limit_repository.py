"""PostgreSQL limit membership manifest and fact repository."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from ....limit_facts import (
    LIMIT_FACT_SCHEMA_VERSION,
    LimitSecurityFactRecord,
    fact_row_checksum,
    limit_dataset_checksum,
)
from ....snapshot_store import SnapshotIntegrityError
from .repositories import _as_date, _as_datetime, _canonical_json, _json_load


class PostgresLimitDetailRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def get_limit_detail(self, as_of: date) -> Mapping[str, Any] | None:
        manifest = self.get_manifest(as_of)
        if manifest is None:
            return None
        facts = self.get_facts(as_of)
        self._validate_manifest(as_of, manifest, facts)
        return {**manifest, "facts": facts}

    def get_manifest(self, as_of: date) -> dict[str, Any] | None:
        row = self.connection.execute(
            text("SELECT * FROM limit_security_datasets WHERE as_of = :as_of"),
            {"as_of": as_of},
        ).mappings().first()
        if row is None:
            return None
        return {
            "as_of": _as_date(row["as_of"]),
            "actual_as_of": _as_date(row["actual_as_of"]),
            "source": row["source"],
            "source_revision": row["source_revision"],
            "rule_version": row["rule_version"],
            "schema_version": int(row["schema_version"]),
            "complete": bool(row["complete"]),
            "membership_complete": (
                bool(row["membership_complete"])
                if row["membership_complete"] is not None
                else None
            ),
            "streak_complete": (
                bool(row["streak_complete"])
                if row["streak_complete"] is not None
                else None
            ),
            "pool_quality": _json_load(row["pool_quality_json"], None),
            "excluded": int(row["excluded"]),
            "warnings": tuple(
                str(value) for value in _json_load(row["warnings_json"], [])
            ),
            "dataset_checksum": str(row["dataset_checksum"]),
            "fetched_at": _as_datetime(row["fetched_at"]),
        }

    def get_facts(self, as_of: date) -> Sequence[LimitSecurityFactRecord]:
        rows = self.connection.execute(
            text(
                "SELECT * FROM limit_security_facts WHERE as_of = :as_of "
                "ORDER BY security_id, pool_type"
            ),
            {"as_of": as_of},
        ).mappings()
        facts = tuple(self._fact_from_row(row) for row in rows)
        for fact in facts:
            if fact.schema_version != LIMIT_FACT_SCHEMA_VERSION:
                raise SnapshotIntegrityError(
                    "unsupported limit fact schema version: "
                    f"{as_of.isoformat()}/{fact.security_id}/{fact.pool_type}"
                )
            if fact_row_checksum(fact) != fact.row_checksum:
                raise SnapshotIntegrityError(
                    "limit fact checksum mismatch: "
                    f"{as_of.isoformat()}/{fact.security_id}/{fact.pool_type}"
                )
        return facts

    def put_limit_detail(
        self,
        as_of: date,
        manifest: Mapping[str, Any],
        facts: Iterable[object],
    ) -> None:
        values = tuple(self._normalized_fact(value) for value in facts)
        normalized_manifest = self._normalized_manifest(as_of, manifest, values)
        checksum = normalized_manifest["dataset_checksum"]
        values = tuple(replace(value, dataset_checksum=checksum) for value in values)
        self.connection.execute(
            text("DELETE FROM limit_security_facts WHERE as_of = :as_of"),
            {"as_of": as_of},
        )
        for value in values:
            self._upsert_fact(value)
        self._upsert_manifest(normalized_manifest)

    def _normalized_manifest(
        self,
        as_of: date,
        manifest: Mapping[str, Any],
        facts: Sequence[LimitSecurityFactRecord],
    ) -> dict[str, Any]:
        actual_as_of = manifest.get("actual_as_of")
        if isinstance(actual_as_of, str):
            actual_as_of = date.fromisoformat(actual_as_of)
        if actual_as_of not in (None, as_of):
            raise ValueError("limit manifest actual_as_of must match as_of")
        for fact in facts:
            if fact.as_of != as_of or fact.actual_as_of != actual_as_of:
                raise ValueError("all limit facts must use the manifest exact date")
            if fact.schema_version != LIMIT_FACT_SCHEMA_VERSION:
                raise ValueError(
                    f"unsupported limit fact schema version: {fact.schema_version}"
                )
            if fact.row_checksum != fact_row_checksum(fact):
                raise ValueError(
                    f"invalid row checksum: {fact.security_id}/{fact.pool_type}"
                )
        warnings = tuple(str(value) for value in manifest.get("warnings") or ())
        excluded = sum(not fact.eligible for fact in facts)
        if int(manifest.get("excluded", excluded)) != excluded:
            raise ValueError("limit manifest excluded count does not match facts")
        value = {
            "as_of": as_of,
            "actual_as_of": actual_as_of,
            "source": str(manifest.get("source") or "unknown"),
            "source_revision": manifest.get("source_revision"),
            "rule_version": manifest.get("rule_version"),
            "schema_version": int(
                manifest.get("schema_version", LIMIT_FACT_SCHEMA_VERSION)
            ),
            "complete": bool(manifest.get("complete", False)),
            "membership_complete": manifest.get("membership_complete"),
            "streak_complete": manifest.get("streak_complete"),
            "pool_quality": (
                dict(manifest["pool_quality"])
                if manifest.get("pool_quality") is not None
                else None
            ),
            "excluded": excluded,
            "warnings": warnings,
            "fetched_at": _as_datetime(manifest["fetched_at"]),
        }
        if value["schema_version"] != LIMIT_FACT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported limit dataset schema version: {value['schema_version']}"
            )
        checksum = limit_dataset_checksum(
            facts,
            as_of=as_of,
            actual_as_of=actual_as_of,
            source=value["source"],
            complete=value["complete"],
            warnings=warnings,
            source_revision=value["source_revision"],
            rule_version=value["rule_version"],
            excluded=excluded,
            membership_complete=value["membership_complete"],
            streak_complete=value["streak_complete"],
            pool_quality=value["pool_quality"],
        )
        supplied = manifest.get("dataset_checksum")
        if supplied not in (None, "", checksum):
            raise ValueError("limit manifest checksum does not match facts")
        value["dataset_checksum"] = checksum
        return value

    def _upsert_manifest(self, value: Mapping[str, Any]) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO limit_security_datasets(
                    as_of, actual_as_of, source, source_revision, rule_version,
                    schema_version, complete, membership_complete, streak_complete,
                    pool_quality_json, excluded, warnings_json, dataset_checksum,
                    fetched_at
                ) VALUES (
                    :as_of, :actual_as_of, :source, :source_revision, :rule_version,
                    :schema_version, :complete, :membership_complete, :streak_complete,
                    :pool_quality_json, :excluded, :warnings_json, :dataset_checksum,
                    :fetched_at
                )
                ON CONFLICT(as_of) DO UPDATE SET
                    actual_as_of = excluded.actual_as_of,
                    source = excluded.source,
                    source_revision = excluded.source_revision,
                    rule_version = excluded.rule_version,
                    schema_version = excluded.schema_version,
                    complete = excluded.complete,
                    membership_complete = excluded.membership_complete,
                    streak_complete = excluded.streak_complete,
                    pool_quality_json = excluded.pool_quality_json,
                    excluded = excluded.excluded,
                    warnings_json = excluded.warnings_json,
                    dataset_checksum = excluded.dataset_checksum,
                    fetched_at = excluded.fetched_at
                """
            ),
            {
                **value,
                "complete": int(bool(value["complete"])),
                "membership_complete": (
                    int(bool(value["membership_complete"]))
                    if value["membership_complete"] is not None
                    else None
                ),
                "streak_complete": (
                    int(bool(value["streak_complete"]))
                    if value["streak_complete"] is not None
                    else None
                ),
                "pool_quality_json": (
                    _canonical_json(value["pool_quality"])
                    if value["pool_quality"] is not None
                    else None
                ),
                "warnings_json": _canonical_json(list(value["warnings"])),
            },
        )

    def _upsert_fact(self, value: LimitSecurityFactRecord) -> None:
        self.connection.execute(
            text(
                """
                INSERT INTO limit_security_facts(
                    as_of, actual_as_of, security_id, pool_type, code, exchange,
                    name, board, is_st, is_new, listing_date, listing_days,
                    limit_regime, close_price, previous_close, change_pct,
                    touched_limit_up, closed_limit_up, failed_limit_up, streak_days,
                    limit_up_time, limit_up_reason, seal_money, max_seal_money,
                    first_limit_time, last_limit_time, open_times, turnover_ratio_pct,
                    turnover, row_quality, row_warnings_json, eligible,
                    invalid_reason, source, fetched_at, schema_version,
                    row_checksum, dataset_checksum
                ) VALUES (
                    :as_of, :actual_as_of, :security_id, :pool_type, :code, :exchange,
                    :name, :board, :is_st, :is_new, :listing_date, :listing_days,
                    :limit_regime, :close_price, :previous_close, :change_pct,
                    :touched_limit_up, :closed_limit_up, :failed_limit_up, :streak_days,
                    :limit_up_time, :limit_up_reason, :seal_money, :max_seal_money,
                    :first_limit_time, :last_limit_time, :open_times,
                    :turnover_ratio_pct, :turnover, :row_quality, :row_warnings_json,
                    :eligible, :invalid_reason, :source, :fetched_at, :schema_version,
                    :row_checksum, :dataset_checksum
                )
                ON CONFLICT(as_of, security_id, pool_type) DO UPDATE SET
                    actual_as_of = excluded.actual_as_of,
                    code = excluded.code,
                    exchange = excluded.exchange,
                    name = excluded.name,
                    board = excluded.board,
                    is_st = excluded.is_st,
                    is_new = excluded.is_new,
                    listing_date = excluded.listing_date,
                    listing_days = excluded.listing_days,
                    limit_regime = excluded.limit_regime,
                    close_price = excluded.close_price,
                    previous_close = excluded.previous_close,
                    change_pct = excluded.change_pct,
                    touched_limit_up = excluded.touched_limit_up,
                    closed_limit_up = excluded.closed_limit_up,
                    failed_limit_up = excluded.failed_limit_up,
                    streak_days = excluded.streak_days,
                    limit_up_time = excluded.limit_up_time,
                    limit_up_reason = excluded.limit_up_reason,
                    seal_money = excluded.seal_money,
                    max_seal_money = excluded.max_seal_money,
                    first_limit_time = excluded.first_limit_time,
                    last_limit_time = excluded.last_limit_time,
                    open_times = excluded.open_times,
                    turnover_ratio_pct = excluded.turnover_ratio_pct,
                    turnover = excluded.turnover,
                    row_quality = excluded.row_quality,
                    row_warnings_json = excluded.row_warnings_json,
                    eligible = excluded.eligible,
                    invalid_reason = excluded.invalid_reason,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at,
                    schema_version = excluded.schema_version,
                    row_checksum = excluded.row_checksum,
                    dataset_checksum = excluded.dataset_checksum
                """
            ),
            {
                **value.as_dict(),
                "is_st": int(value.is_st) if value.is_st is not None else None,
                "is_new": int(value.is_new) if value.is_new is not None else None,
                "limit_up_time": value.limit_up_time,
                "limit_up_reason": value.limit_up_reason,
                "seal_money": value.seal_money,
                "max_seal_money": value.max_seal_money,
                "first_limit_time": value.first_limit_time,
                "last_limit_time": value.last_limit_time,
                "open_times": value.open_times,
                "turnover_ratio_pct": value.turnover_ratio_pct,
                "turnover": value.turnover,
                "row_quality": value.row_quality,
                "touched_limit_up": (
                    int(value.touched_limit_up)
                    if value.touched_limit_up is not None
                    else None
                ),
                "closed_limit_up": (
                    int(value.closed_limit_up)
                    if value.closed_limit_up is not None
                    else None
                ),
                "failed_limit_up": (
                    int(value.failed_limit_up)
                    if value.failed_limit_up is not None
                    else None
                ),
                "row_warnings_json": _canonical_json(list(value.row_warnings)),
                "eligible": int(value.eligible),
            },
        )

    @staticmethod
    def _normalized_fact(value: object) -> LimitSecurityFactRecord:
        if not isinstance(value, LimitSecurityFactRecord):
            raise TypeError("limit detail repository requires LimitSecurityFactRecord")
        return value.normalized()

    @staticmethod
    def _fact_from_row(row: Mapping[str, Any]) -> LimitSecurityFactRecord:
        return LimitSecurityFactRecord(
            as_of=_as_date(row["as_of"]),  # type: ignore[arg-type]
            actual_as_of=_as_date(row["actual_as_of"]),
            security_id=str(row["security_id"]),
            pool_type=str(row["pool_type"]),
            code=str(row["code"]),
            exchange=str(row["exchange"]),
            name=row["name"],
            board=row["board"],
            is_st=bool(row["is_st"]) if row["is_st"] is not None else None,
            is_new=bool(row["is_new"]) if row["is_new"] is not None else None,
            listing_date=_as_date(row["listing_date"]),
            listing_days=(
                int(row["listing_days"]) if row["listing_days"] is not None else None
            ),
            limit_regime=row["limit_regime"],
            close_price=(
                float(row["close_price"]) if row["close_price"] is not None else None
            ),
            previous_close=(
                float(row["previous_close"])
                if row["previous_close"] is not None
                else None
            ),
            change_pct=(
                float(row["change_pct"]) if row["change_pct"] is not None else None
            ),
            touched_limit_up=(
                bool(row["touched_limit_up"])
                if row["touched_limit_up"] is not None
                else None
            ),
            closed_limit_up=(
                bool(row["closed_limit_up"])
                if row["closed_limit_up"] is not None
                else None
            ),
            failed_limit_up=(
                bool(row["failed_limit_up"])
                if row["failed_limit_up"] is not None
                else None
            ),
            streak_days=(
                int(row["streak_days"]) if row["streak_days"] is not None else None
            ),
            limit_up_time=row["limit_up_time"],
            limit_up_reason=row["limit_up_reason"],
            seal_money=(
                float(row["seal_money"]) if row["seal_money"] is not None else None
            ),
            max_seal_money=(
                float(row["max_seal_money"])
                if row["max_seal_money"] is not None
                else None
            ),
            first_limit_time=row["first_limit_time"],
            last_limit_time=row["last_limit_time"],
            open_times=(int(row["open_times"]) if row["open_times"] is not None else None),
            turnover_ratio_pct=(
                float(row["turnover_ratio_pct"])
                if row["turnover_ratio_pct"] is not None
                else None
            ),
            turnover=(float(row["turnover"]) if row["turnover"] is not None else None),
            row_quality=row["row_quality"],
            row_warnings=tuple(
                str(value) for value in _json_load(row["row_warnings_json"], [])
            ),
            eligible=bool(row["eligible"]),
            invalid_reason=row["invalid_reason"],
            source=str(row["source"]),
            fetched_at=_as_datetime(row["fetched_at"]),
            schema_version=int(row["schema_version"]),
            row_checksum=str(row["row_checksum"]),
            dataset_checksum=row["dataset_checksum"],
        ).normalized()

    @staticmethod
    def _validate_manifest(
        as_of: date,
        manifest: Mapping[str, Any],
        facts: Sequence[LimitSecurityFactRecord],
    ) -> None:
        if manifest["schema_version"] != LIMIT_FACT_SCHEMA_VERSION:
            raise SnapshotIntegrityError(
                f"unsupported limit dataset schema version: {as_of.isoformat()}"
            )
        if any(
            fact.dataset_checksum != manifest["dataset_checksum"] for fact in facts
        ):
            raise SnapshotIntegrityError(
                f"limit fact dataset checksum mismatch: {as_of.isoformat()}"
            )
        if manifest["excluded"] != sum(not fact.eligible for fact in facts):
            raise SnapshotIntegrityError(
                f"limit dataset exclusion count mismatch: {as_of.isoformat()}"
            )
        expected = limit_dataset_checksum(
            facts,
            as_of=as_of,
            actual_as_of=manifest["actual_as_of"],
            source=manifest["source"],
            complete=manifest["complete"],
            warnings=manifest["warnings"],
            source_revision=manifest["source_revision"],
            rule_version=manifest["rule_version"],
            excluded=manifest["excluded"],
            membership_complete=manifest["membership_complete"],
            streak_complete=manifest["streak_complete"],
            pool_quality=manifest["pool_quality"],
        )
        if expected != manifest["dataset_checksum"]:
            raise SnapshotIntegrityError(
                f"limit dataset checksum mismatch: {as_of.isoformat()}"
            )


__all__ = ["PostgresLimitDetailRepository"]
