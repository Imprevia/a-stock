"""Auditable, reversible exact-date relabeling for snapshot storage.

This module deliberately does not discover or open a production volume. A
caller supplies a :class:`~.snapshot_store.SnapshotStore` (backed by an
explicitly selected isolated SQLite copy or PostgreSQL URL), and writes are
opt-in via ``apply=True``.
The migration changes the date key and date evidence together, verifies every
checksum before touching a row, and records a complete before-image for
rollback.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .limit_facts import LimitSecurityFactRecord, fact_row_checksum, limit_dataset_checksum
from .snapshot_store import (
    LIMIT_DETAIL_CHECKSUM_KEY,
    MATERIALIZED_COMPONENT_REVISION_KEY,
    SNAPSHOT_SCHEMA_VERSION,
    TRADING_SESSION_SCHEMA_VERSION,
    SnapshotIntegrityError,
    SnapshotStore,
    TradingSessionRecord,
    canonical_json,
    payload_checksum,
    _as_date,
    _as_datetime,
    _json_value as _decode_json,
)

ConflictPolicy = Literal["reject", "skip", "overwrite"]


class DateRelabelError(RuntimeError):
    """Base error for a rejected or invalid date relabel operation."""


class DateRelabelConflict(DateRelabelError):
    """The destination already contains a different exact-date record."""


@dataclass(frozen=True)
class DateRelabelEntry:
    table: str
    rows: int
    datasets: tuple[str, ...] = ()
    old_checksums: tuple[str, ...] = ()
    new_checksums: tuple[str, ...] = ()
    action: str = "move"

    def as_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "rows": self.rows,
            "datasets": list(self.datasets),
            "oldChecksums": list(self.old_checksums),
            "newChecksums": list(self.new_checksums),
            "action": self.action,
        }


@dataclass(frozen=True)
class DateRelabelPlan:
    source_as_of: date
    target_as_of: date
    conflict_policy: ConflictPolicy
    entries: tuple[DateRelabelEntry, ...] = ()
    conflicts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    audit_id: str = ""

    @property
    def can_apply(self) -> bool:
        return not self.conflicts

    def as_dict(self) -> dict[str, Any]:
        return {
            "sourceAsOf": self.source_as_of.isoformat(),
            "targetAsOf": self.target_as_of.isoformat(),
            "conflictPolicy": self.conflict_policy,
            "entries": [entry.as_dict() for entry in self.entries],
            "conflicts": list(self.conflicts),
            "warnings": list(self.warnings),
            "auditId": self.audit_id or None,
            "canApply": self.can_apply,
        }


@dataclass(frozen=True)
class DateRelabelResult:
    audit_id: str
    source_as_of: date
    target_as_of: date
    status: Literal["dry-run", "applied", "rejected", "rolled-back"]
    entries: tuple[DateRelabelEntry, ...] = ()
    conflicts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "auditId": self.audit_id,
            "sourceAsOf": self.source_as_of.isoformat(),
            "targetAsOf": self.target_as_of.isoformat(),
            "status": self.status,
            "entries": [entry.as_dict() for entry in self.entries],
            "conflicts": list(self.conflicts),
            "warnings": list(self.warnings),
            "error": self.error,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _row_dict(row: Any) -> dict[str, Any]:
    """Convert SQLite and PostgreSQL values to a JSON-safe before-image."""

    result: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if isinstance(value, bytes):
            result[key] = {"__bytes__": value.hex()}
        elif isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def _json_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _parse_date(value: Any, *, field_name: str) -> date:
    if not isinstance(value, str):
        raise DateRelabelError(f"{field_name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DateRelabelError(f"{field_name} has invalid date {value!r}") from exc


def _is_date_key(key: str) -> bool:
    normalized = key.replace("-", "").replace("_", "").lower()
    return normalized in {
        "asof",
        "actualasof",
        "effectivedate",
        "sessiondate",
        "tradingdate",
        "requestedasof",
        "actualdate",
        "sampleasof",
        "promotionsampleasof",
        "promotionpreviousasof",
        "previousasof",
    }


def _rewrite_payload_dates(value: Any, source: date, target: date, *, key: str = "") -> Any:
    """Rewrite explicit date evidence, never timestamp fields or free text."""

    if isinstance(value, dict):
        return {
            item_key: _rewrite_payload_dates(item, source, target, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_payload_dates(item, source, target, key=key) for item in value]
    if isinstance(value, str) and _is_date_key(key) and value == source.isoformat():
        return target.isoformat()
    return value


def _validate_payload_dates(payload: dict[str, Any], source: date, target: date) -> None:
    """Reject explicit evidence for a third date before a relabel.

    A payload may already have been partially corrected to the target date;
    source and target are therefore both accepted.  ``previousAsOf`` fields
    are historical references and are not treated as the payload's actual
    session date.
    """

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for item_key, item in value.items():
                visit(item, str(item_key))
            return
        if isinstance(value, list):
            for item in value:
                visit(item, key)
            return
        if not (_is_date_key(key) and isinstance(value, str)):
            return
        normalized = key.replace("-", "").replace("_", "").lower()
        if "previous" in normalized or "prior" in normalized:
            return
        try:
            observed = date.fromisoformat(value)
        except ValueError:
            # Date-like warning or label strings are not evidence fields.
            return
        if observed not in {source, target}:
            raise DateRelabelError(
                f"payload date evidence {key}={value} does not match source {source.isoformat()} "
                f"or target {target.isoformat()}"
            )

    visit(payload)


def _rewrite_core_index_payload(payload: dict[str, Any], source: date, target: date) -> dict[str, Any]:
    """Rewrite only the latest bar date in a core-index history.

    Core index payloads intentionally carry a multi-day ``history`` array;
    those historical dates are valid evidence and must not be mistaken for a
    third session date.  We therefore validate the latest bar separately and
    leave older bars untouched, changing only entries equal to the relabeled
    source date.
    """

    _validate_payload_dates(payload, source, target)
    rewritten = _rewrite_payload_dates(payload, source, target)
    history = rewritten.get("history")
    if not isinstance(history, list) or not history:
        return rewritten
    latest = history[-1]
    if not isinstance(latest, dict) or not isinstance(latest.get("date"), str):
        raise DateRelabelError("core index history is missing latest date evidence")
    try:
        latest_date = date.fromisoformat(latest["date"])
    except ValueError as exc:
        raise DateRelabelError(f"core index history has invalid latest date: {latest['date']!r}") from exc
    if latest_date not in {source, target}:
        raise DateRelabelError(
            f"core index latest date {latest_date.isoformat()} does not match source "
            f"{source.isoformat()} or target {target.isoformat()}"
        )
    for point in history:
        if isinstance(point, dict) and point.get("date") == source.isoformat():
            point["date"] = target.isoformat()
    return rewritten


def _rewrite_core_histories_in_payload(
    payload: dict[str, Any], source: date, target: date
) -> dict[str, Any]:
    """Rewrite core-index histories only under the response ``indices`` key."""

    rewritten = _rewrite_payload_dates(payload, source, target)
    indices = rewritten.get("indices")
    if not isinstance(indices, list):
        return rewritten
    rewritten["indices"] = [
        _rewrite_core_index_payload(item, source, target)
        if isinstance(item, dict) and isinstance(item.get("history"), list)
        else item
        for item in indices
    ]
    return rewritten


def _validate_snapshot_row(row: Any, source: date, target: date) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _decode_json(row["payload_json"], {})
    if not isinstance(payload, dict):
        raise DateRelabelError(f"snapshot payload is not an object: {row['dataset']}/{source}")
    if int(row["schema_version"]) != SNAPSHOT_SCHEMA_VERSION:
        raise DateRelabelError(f"unsupported snapshot schema: {row['dataset']}/{source}")
    if payload_checksum(payload) != row["checksum"]:
        raise SnapshotIntegrityError(f"snapshot checksum mismatch: {row['dataset']}/{source}")
    _validate_payload_dates(payload, source, target)
    rewritten = _rewrite_core_histories_in_payload(payload, source, target)
    new_row = dict(_row_dict(row))
    new_row["as_of"] = target.isoformat()
    # A source row captured before today's open is provisional.  Once it is
    # explicitly relabeled to the previous session, the historical target is
    # settled by definition, so readers do not treat it as a live session.
    if target < source:
        new_row["settled"] = 1
    new_row["payload_json"] = canonical_json(rewritten)
    new_row["checksum"] = payload_checksum(rewritten)
    return _row_dict(row), new_row


def _fact_from_row(row: Any) -> LimitSecurityFactRecord:
    return LimitSecurityFactRecord(
        as_of=_as_date(row["as_of"]),
        actual_as_of=_as_date(row["actual_as_of"]),
        security_id=row["security_id"],
        pool_type=row["pool_type"],
        code=row["code"],
        exchange=row["exchange"],
        name=row["name"],
        board=row["board"],
        is_st=bool(row["is_st"]) if row["is_st"] is not None else None,
        is_new=bool(row["is_new"]) if row["is_new"] is not None else None,
        listing_date=_as_date(row["listing_date"]),
        listing_days=int(row["listing_days"]) if row["listing_days"] is not None else None,
        limit_regime=row["limit_regime"],
        close_price=float(row["close_price"]) if row["close_price"] is not None else None,
        previous_close=float(row["previous_close"]) if row["previous_close"] is not None else None,
        change_pct=float(row["change_pct"]) if row["change_pct"] is not None else None,
        touched_limit_up=bool(row["touched_limit_up"]) if row["touched_limit_up"] is not None else None,
        closed_limit_up=bool(row["closed_limit_up"]) if row["closed_limit_up"] is not None else None,
        failed_limit_up=bool(row["failed_limit_up"]) if row["failed_limit_up"] is not None else None,
        streak_days=int(row["streak_days"]) if row["streak_days"] is not None else None,
        limit_up_time=row["limit_up_time"],
        limit_up_reason=row["limit_up_reason"],
        seal_money=float(row["seal_money"]) if row["seal_money"] is not None else None,
        max_seal_money=(
            float(row["max_seal_money"]) if row["max_seal_money"] is not None else None
        ),
        first_limit_time=row["first_limit_time"],
        last_limit_time=row["last_limit_time"],
        open_times=int(row["open_times"]) if row["open_times"] is not None else None,
        turnover_ratio_pct=(
            float(row["turnover_ratio_pct"])
            if row["turnover_ratio_pct"] is not None
            else None
        ),
        turnover=float(row["turnover"]) if row["turnover"] is not None else None,
        row_quality=row["row_quality"],
        row_warnings=tuple(_decode_json(row["row_warnings_json"], [])),
        eligible=bool(row["eligible"]),
        invalid_reason=row["invalid_reason"],
        source=row["source"],
        fetched_at=_as_datetime(row["fetched_at"]),
        schema_version=int(row["schema_version"]),
        row_checksum=row["row_checksum"],
        dataset_checksum=row["dataset_checksum"],
    ).normalized()


def _entry(table: str, old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]], *, datasets: set[str] | None = None, action: str = "move") -> DateRelabelEntry:
    return DateRelabelEntry(
        table=table,
        rows=len(old_rows),
        datasets=tuple(sorted(datasets or set())),
        old_checksums=tuple(str(row.get("checksum", row.get("dataset_checksum", ""))) for row in old_rows),
        new_checksums=tuple(str(row.get("checksum", row.get("dataset_checksum", ""))) for row in new_rows),
        action=action,
    )


def _query_rows(connection: Any, table: str, source: date) -> list[Any]:
    if table == "snapshot_entries":
        return connection.execute("SELECT * FROM snapshot_entries WHERE as_of = ? ORDER BY dataset", (source.isoformat(),)).fetchall()
    if table == "trading_sessions":
        return connection.execute("SELECT * FROM trading_sessions WHERE as_of = ?", (source.isoformat(),)).fetchall()
    if table == "limit_security_datasets":
        return connection.execute("SELECT * FROM limit_security_datasets WHERE as_of = ?", (source.isoformat(),)).fetchall()
    if table == "limit_security_facts":
        return connection.execute("SELECT * FROM limit_security_facts WHERE as_of = ? ORDER BY security_id, pool_type", (source.isoformat(),)).fetchall()
    if table == "materialized_market_environment":
        return connection.execute("SELECT * FROM materialized_market_environment WHERE as_of = ?", (source.isoformat(),)).fetchall()
    if table == "collection_runs":
        return connection.execute("SELECT * FROM collection_runs WHERE as_of = ?", (source.isoformat(),)).fetchall()
    if table == "collection_tasks":
        return connection.execute("SELECT * FROM collection_tasks WHERE as_of = ? ORDER BY task_id", (source.isoformat(),)).fetchall()
    if table == "refresh_runs":
        return connection.execute("SELECT * FROM refresh_runs WHERE as_of = ? ORDER BY run_id, dataset", (source.isoformat(),)).fetchall()
    if table == "refresh_leases":
        return connection.execute("SELECT * FROM refresh_leases WHERE as_of = ?", (source.isoformat(),)).fetchall()
    if table == "materialization_component_versions":
        return connection.execute("SELECT * FROM materialization_component_versions WHERE as_of = ? ORDER BY component_kind, dataset", (source.isoformat(),)).fetchall()
    raise AssertionError(table)


def _query_core_rows(connection: Any, task_ids: list[str]) -> list[Any]:
    if not task_ids:
        return []
    placeholders = ", ".join("?" for _ in task_ids)
    return connection.execute(
        f"SELECT * FROM core_index_results WHERE task_id IN ({placeholders}) ORDER BY task_id, code",
        task_ids,
    ).fetchall()


def _build_plan(store: SnapshotStore, source: date, target: date, policy: ConflictPolicy) -> tuple[DateRelabelPlan, dict[str, Any]]:
    if source == target:
        raise DateRelabelError("source and target dates must differ")
    if policy not in {"reject", "skip", "overwrite"}:
        raise DateRelabelError(f"unsupported conflict policy: {policy}")

    entries: list[DateRelabelEntry] = []
    conflicts: list[str] = []
    warnings: list[str] = []
    before: dict[str, list[dict[str, Any]]] = {}
    target_before: dict[str, list[dict[str, Any]]] = {}
    transformed: dict[str, list[dict[str, Any]]] = {}
    aggregate_had_revision = False
    source_rows: dict[str, list[Any]] = {}

    with store._connect() as connection:  # type: ignore[attr-defined]
        # Leases are operational state, not historical evidence.  Refuse to
        # move while either side is leased so a worker cannot write the old key.
        now_utc = _utc_now()
        lease_rows = [
            row
            for row in [*_query_rows(connection, "refresh_leases", source), *_query_rows(connection, "refresh_leases", target)]
            if (_as_datetime(row["expires_at"]) or datetime.min.replace(tzinfo=timezone.utc)) > now_utc
        ]
        if lease_rows:
            conflicts.append("source or target date has an active refresh lease")

        for table in (
            "snapshot_entries",
            "trading_sessions",
            "limit_security_datasets",
            "limit_security_facts",
            "materialized_market_environment",
            "collection_runs",
            "collection_tasks",
            "refresh_runs",
            "materialization_component_versions",
        ):
            rows = _query_rows(connection, table, source)
            source_rows[table] = rows
            before[table] = [_row_dict(row) for row in rows]

        core_task_ids = [str(row["task_id"]) for row in source_rows["collection_tasks"]]
        source_rows["core_index_results"] = _query_core_rows(connection, core_task_ids)
        before["core_index_results"] = [_row_dict(row) for row in source_rows["core_index_results"]]

        # Validate all source rows and build their target image before checking
        # destination conflicts.  Thus a dry-run catches corruption even when
        # the target happens to contain a conflicting row.
        snapshot_new: list[dict[str, Any]] = []
        for row in source_rows["snapshot_entries"]:
            _old, new = _validate_snapshot_row(row, source, target)
            snapshot_new.append(new)
        transformed["snapshot_entries"] = snapshot_new

        session_new: list[dict[str, Any]] = []
        for row in source_rows["trading_sessions"]:
            value = TradingSessionRecord(
                as_of=_as_date(row["as_of"]),
                previous_as_of=_as_date(row["previous_as_of"]),
                actual_as_of=_as_date(row["actual_as_of"]),
                is_session=bool(row["is_session"]),
                source=row["source"],
                schema_version=int(row["schema_version"]),
                checksum=row["checksum"],
                fetched_at=_as_datetime(row["fetched_at"]),
                warnings=tuple(_decode_json(row["warnings_json"], [])),
            )
            if value.schema_version != TRADING_SESSION_SCHEMA_VERSION:
                raise DateRelabelError(f"unsupported trading session schema: {source}")
            if payload_checksum(value.logical_dict()) != value.checksum:
                raise SnapshotIntegrityError(f"trading session checksum mismatch: {source}")
            previous = value.previous_as_of
            if previous == target:
                target_session = connection.execute(
                    "SELECT previous_as_of FROM trading_sessions WHERE as_of = ?",
                    (target.isoformat(),),
                ).fetchone()
                previous = _as_date(target_session["previous_as_of"]) if target_session and target_session["previous_as_of"] else None
                if previous is None:
                    predecessor = connection.execute(
                        "SELECT as_of FROM trading_sessions WHERE as_of < ? ORDER BY as_of DESC LIMIT 1",
                        (target.isoformat(),),
                    ).fetchone()
                    previous = _as_date(predecessor[0]) if predecessor else None
            elif previous == source:
                previous = target
            actual = value.actual_as_of
            if actual not in {None, source, target}:
                raise DateRelabelError(f"trading session actual_as_of mismatch: {actual}")
            if actual == source:
                actual = target
            rewritten = _row_dict(row)
            rewritten.update(
                as_of=target.isoformat(),
                previous_as_of=previous.isoformat() if previous else None,
                actual_as_of=actual.isoformat() if actual else None,
            )
            logical = {
                "as_of": target.isoformat(),
                "previous_as_of": previous.isoformat() if previous else None,
                "actual_as_of": actual.isoformat() if actual else None,
                "is_session": bool(row["is_session"]),
                "source": row["source"],
                "schema_version": int(row["schema_version"]),
                "warnings": list(_decode_json(row["warnings_json"], [])),
            }
            rewritten["checksum"] = payload_checksum(logical)
            session_new.append(rewritten)
        transformed["trading_sessions"] = session_new

        # Limit facts and manifest are a coupled checksum domain.  Validate the
        # original domain, then recalculate row and dataset checksums for target.
        manifest_rows = source_rows["limit_security_datasets"]
        fact_rows = source_rows["limit_security_facts"]
        limit_new: list[dict[str, Any]] = []
        manifest_new: list[dict[str, Any]] = []
        if fact_rows and not manifest_rows:
            raise DateRelabelError(
                f"limit security facts have no manifest for source date {source.isoformat()}"
            )
        if manifest_rows:
            manifest = manifest_rows[0]
            facts = tuple(_fact_from_row(row) for row in fact_rows)
            if any(fact_row_checksum(fact) != row["row_checksum"] for fact, row in zip(facts, fact_rows)):
                raise SnapshotIntegrityError(f"limit fact checksum mismatch: {source}")
            if any(fact.dataset_checksum != manifest["dataset_checksum"] for fact in facts):
                raise SnapshotIntegrityError(f"limit fact dataset checksum mismatch: {source}")
            actual = _as_date(manifest["actual_as_of"])
            if actual not in {None, source, target}:
                raise DateRelabelError(f"limit dataset actual_as_of mismatch: {actual}")
            if (
                bool(manifest["complete"])
                or bool(manifest["membership_complete"])
            ) and actual != source:
                raise DateRelabelError("complete limit dataset is missing source actual_as_of evidence")
            warnings_json = _decode_json(manifest["warnings_json"], [])
            pool_quality = _decode_json(manifest["pool_quality_json"], None)
            expected_source_checksum = limit_dataset_checksum(
                facts,
                as_of=source,
                actual_as_of=actual,
                source=manifest["source"],
                complete=bool(manifest["complete"]),
                warnings=tuple(warnings_json),
                source_revision=manifest["source_revision"],
                rule_version=manifest["rule_version"],
                excluded=int(manifest["excluded"]),
                membership_complete=(
                    bool(manifest["membership_complete"])
                    if manifest["membership_complete"] is not None
                    else None
                ),
                streak_complete=(
                    bool(manifest["streak_complete"])
                    if manifest["streak_complete"] is not None
                    else None
                ),
                pool_quality=pool_quality,
            )
            if expected_source_checksum != manifest["dataset_checksum"]:
                raise SnapshotIntegrityError(f"limit dataset checksum mismatch: {source}")
            for snapshot_item in snapshot_new:
                if snapshot_item.get("dataset") != "limits":
                    continue
                snapshot_payload = json.loads(snapshot_item["payload_json"])
                embedded = (snapshot_payload.get("quality") or {}).get(LIMIT_DETAIL_CHECKSUM_KEY)
                if embedded is not None and embedded != manifest["dataset_checksum"]:
                    raise SnapshotIntegrityError(f"limits snapshot detail checksum mismatch: {source}")
            rewritten_facts: list[LimitSecurityFactRecord] = []
            for fact in facts:
                fact_actual = fact.actual_as_of
                if fact_actual not in {None, source, target}:
                    raise DateRelabelError(f"limit fact actual_as_of mismatch: {fact_actual}")
                rewritten_facts.append(
                    fact.__class__(**{**fact.__dict__, "as_of": target, "actual_as_of": target if fact_actual == source else fact_actual, "row_checksum": "", "dataset_checksum": None}).normalized()
                )
            actual_target = target if actual == source else actual
            dataset_checksum = limit_dataset_checksum(
                tuple(rewritten_facts),
                as_of=target,
                actual_as_of=actual_target,
                source=manifest["source"],
                complete=bool(manifest["complete"]),
                warnings=tuple(warnings_json),
                source_revision=manifest["source_revision"],
                rule_version=manifest["rule_version"],
                excluded=int(manifest["excluded"]),
                membership_complete=(
                    bool(manifest["membership_complete"])
                    if manifest["membership_complete"] is not None
                    else None
                ),
                streak_complete=(
                    bool(manifest["streak_complete"])
                    if manifest["streak_complete"] is not None
                    else None
                ),
                pool_quality=pool_quality,
            )
            for row, fact in zip(fact_rows, rewritten_facts):
                item = _row_dict(row)
                item.update(
                    as_of=target.isoformat(),
                    actual_as_of=fact.actual_as_of.isoformat() if fact.actual_as_of else None,
                    row_checksum=fact.row_checksum,
                    dataset_checksum=dataset_checksum,
                )
                limit_new.append(item)
            manifest_item = _row_dict(manifest)
            manifest_item.update(
                as_of=target.isoformat(),
                actual_as_of=actual_target.isoformat() if actual_target else None,
                dataset_checksum=dataset_checksum,
            )
            manifest_new.append(manifest_item)
            # The limits snapshot embeds the normalized-facts checksum in its
            # quality metadata.  Keep that contract in sync with the newly
            # calculated target-date manifest checksum.
            for snapshot_item in snapshot_new:
                if snapshot_item.get("dataset") != "limits":
                    continue
                snapshot_payload = json.loads(snapshot_item["payload_json"])
                quality = snapshot_payload.get("quality")
                if isinstance(quality, dict):
                    quality[LIMIT_DETAIL_CHECKSUM_KEY] = dataset_checksum
                    snapshot_item["payload_json"] = canonical_json(snapshot_payload)
                    snapshot_item["checksum"] = payload_checksum(snapshot_payload)
            transformed["limit_security_facts"] = limit_new
            transformed["limit_security_datasets"] = manifest_new
        else:
            transformed["limit_security_facts"] = []
            transformed["limit_security_datasets"] = []

        aggregate_new: list[dict[str, Any]] = []
        for row in source_rows["materialized_market_environment"]:
            payload = _decode_json(row["payload_json"], {})
            if not isinstance(payload, dict) or payload_checksum(payload) != row["checksum"]:
                raise SnapshotIntegrityError(f"materialized aggregate checksum mismatch: {source}")
            _validate_payload_dates(payload, source, target)
            rewritten_payload = _rewrite_core_histories_in_payload(payload, source, target)
            aggregate_item = _row_dict(row)
            aggregate_item["as_of"] = target.isoformat()
            if MATERIALIZED_COMPONENT_REVISION_KEY in rewritten_payload:
                # Inputs' component revisions change when keys move.  The
                # exact post-migration revision is filled during apply.
                aggregate_had_revision = True
                rewritten_payload.pop(MATERIALIZED_COMPONENT_REVISION_KEY, None)
            aggregate_item["payload_json"] = canonical_json(rewritten_payload)
            aggregate_item["checksum"] = payload_checksum(rewritten_payload)
            aggregate_new.append(aggregate_item)
        transformed["materialized_market_environment"] = aggregate_new

        for table in ("collection_runs", "collection_tasks", "refresh_runs"):
            transformed[table] = []
            for row in source_rows[table]:
                item = _row_dict(row)
                item["as_of"] = target.isoformat()
                if table == "collection_tasks" and target < source:
                    item["settled"] = 1
                if table == "collection_runs":
                    # ``requested_datasets_json`` is not date evidence.
                    pass
                elif table == "refresh_runs" and item.get("result_json"):
                    try:
                        result_payload = json.loads(item["result_json"])
                    except (TypeError, ValueError) as exc:
                        raise DateRelabelError(f"refresh run result is invalid JSON: {row['run_id']}/{row['dataset']}") from exc
                    if isinstance(result_payload, dict):
                        _validate_payload_dates(result_payload, source, target)
                        item["result_json"] = canonical_json(_rewrite_payload_dates(result_payload, source, target))
                transformed[table].append(item)
        transformed["core_index_results"] = []
        for row in source_rows["core_index_results"]:
            item = _row_dict(row)
            if item.get("payload_json"):
                try:
                    payload = json.loads(item["payload_json"])
                except (TypeError, ValueError) as exc:
                    raise DateRelabelError(f"core index result payload is invalid JSON: {row['task_id']}/{row['code']}") from exc
                if isinstance(payload, dict):
                    item["payload_json"] = canonical_json(_rewrite_core_index_payload(payload, source, target))
            transformed["core_index_results"].append(item)
        # Component revisions are maintained by SQLite triggers as the source
        # rows move.  Their old-date entries are explicitly cleaned up below;
        # target entries are generated by those triggers and included in the
        # post-apply before-image for rollback fencing.
        transformed["materialization_component_versions"] = []

        # Destination conflicts are checked by each primary key domain.  A
        # reject policy is the safe default; skip/overwrite are explicit local
        # diagnostic options and still retain the complete before-image.
        conflict_queries = {
            "snapshot_entries": ("SELECT * FROM snapshot_entries WHERE as_of = ?", (target.isoformat(),)),
            "trading_sessions": ("SELECT * FROM trading_sessions WHERE as_of = ?", (target.isoformat(),)),
            "limit_security_datasets": ("SELECT * FROM limit_security_datasets WHERE as_of = ?", (target.isoformat(),)),
            "limit_security_facts": ("SELECT * FROM limit_security_facts WHERE as_of = ?", (target.isoformat(),)),
            "materialized_market_environment": ("SELECT * FROM materialized_market_environment WHERE as_of = ?", (target.isoformat(),)),
            "materialization_component_versions": ("SELECT * FROM materialization_component_versions WHERE as_of = ?", (target.isoformat(),)),
        }
        for table, (query, values) in conflict_queries.items():
            # Snapshot/session/limit moves fire triggers that create a
            # materialization-component revision at the target key.  Treat an
            # existing target revision as a conflict even when the source
            # revision table is empty (for example, a legacy database created
            # before those triggers were introduced).
            if table == "materialization_component_versions":
                affected = any(
                    source_rows[name]
                    for name in (
                        "snapshot_entries",
                        "trading_sessions",
                        "limit_security_datasets",
                        "limit_security_facts",
                    )
                )
            else:
                affected = bool(source_rows[table])
            if not affected:
                continue
            rows = connection.execute(query, values).fetchall()
            target_before[table] = [_row_dict(row) for row in rows]
            if rows:
                conflicts.append(f"target {table} already contains {len(rows)} row(s)")
        for table, rows in source_rows.items():
            if rows:
                datasets = {str(row["dataset"]) for row in rows if "dataset" in row.keys()}
                entries.append(_entry(table, before[table], transformed.get(table, []), datasets=datasets, action="cleanup" if table == "materialization_component_versions" else "move"))
        if policy != "reject" and conflicts:
            warnings.append(f"conflicts will be handled with policy={policy}")
        plan = DateRelabelPlan(source, target, policy, tuple(entries), tuple(conflicts), tuple(warnings))
        return plan, {
            "before": before,
            "target_before": target_before,
            "transformed": transformed,
            "aggregate_had_revision": aggregate_had_revision,
        }


def plan_date_relabel(
    store: SnapshotStore,
    source_as_of: date,
    target_as_of: date,
    *,
    conflict_policy: ConflictPolicy = "reject",
    conflict: ConflictPolicy | None = None,
) -> DateRelabelPlan:
    """Build a read-only migration plan and validate source integrity."""

    plan, _ = _build_plan(store, source_as_of, target_as_of, conflict or conflict_policy)
    return plan


def _is_postgresql(store: SnapshotStore) -> bool:
    return bool(getattr(store, "_postgres", False))


def _lock_relabel_tables(store: SnapshotStore, connection: Any) -> None:
    """Block concurrent writers while a PostgreSQL date rewrite is in flight."""
    if not _is_postgresql(store):
        return
    connection.execute(
        "LOCK TABLE snapshot_entries, trading_sessions, limit_security_datasets, "
        "limit_security_facts, materialized_market_environment, collection_runs, "
        "collection_tasks, core_index_results, refresh_runs, "
        # Keep the fencing-table order aligned with acquire_lease(), which
        # upserts refresh_lease_fences before refresh_leases; this avoids a
        # lock-order inversion during a concurrent relabel/startup race.
        "materialization_component_versions, refresh_lease_fences, refresh_leases "
        "IN SHARE ROW EXCLUSIVE MODE"
    )


def _assert_no_active_relabel_leases(connection: Any, source: date, target: date) -> None:
    """Recheck lease state after taking the relabel write locks.

    Planning happens in a separate read transaction. A worker can acquire a
    lease between that plan and the apply transaction, so the initial check is
    not sufficient. PostgreSQL table locks make this recheck stable; any
    active lease causes a fail-closed rollback before the first row is moved.
    """

    now = _utc_now()
    rows = [
        *connection.execute(
            "SELECT expires_at FROM refresh_leases WHERE as_of = ?",
            (source.isoformat(),),
        ).fetchall(),
        *connection.execute(
            "SELECT expires_at FROM refresh_leases WHERE as_of = ?",
            (target.isoformat(),),
        ).fetchall(),
    ]
    if any(
        (_as_datetime(row["expires_at"]) or datetime.min.replace(tzinfo=timezone.utc)) > now
        for row in rows
    ):
        raise DateRelabelError("source or target date has an active refresh lease")


def _insert_row(
    connection: Any,
    table: str,
    row: dict[str, Any],
    *,
    overwrite: bool,
    postgresql: bool = False,
) -> None:
    values = dict(row)
    values.pop("rowid", None)
    columns = list(values)
    placeholders = ", ".join("?" for _ in columns)
    # PostgreSQL requires an explicit conflict target for ``DO UPDATE``.  The
    # SQLite implementation historically used ``INSERT OR REPLACE`` which
    # inferred the table's primary key (and also replaced rows that matched a
    # secondary unique constraint).  Date relabel rollback only touches the
    # known primary-key domains below, so spell those keys out explicitly and
    # preserve the same deterministic replacement semantics on PostgreSQL.
    conflict_targets = {
        "snapshot_entries": "dataset, as_of",
        "trading_sessions": "as_of",
        "limit_security_datasets": "as_of",
        "limit_security_facts": "as_of, security_id, pool_type",
        "materialized_market_environment": "as_of",
        "collection_runs": "run_id",
        "collection_tasks": "task_id",
        "core_index_results": "task_id, code",
        "refresh_runs": "run_id, dataset",
        "materialization_component_versions": "component_kind, dataset, as_of",
    }
    if postgresql and overwrite:
        assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns)
        target = conflict_targets.get(table)
        if target is None:
            raise DateRelabelError(f"unsupported PostgreSQL rollback table: {table}")
        conflict = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT ({target}) DO UPDATE SET {assignments}"
    else:
        conflict = "INSERT OR REPLACE" if overwrite else "INSERT"
    connection.execute(
        conflict if postgresql and overwrite else f"{conflict} INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [values[column] for column in columns],
    )


def _delete_source_rows(connection: Any, table: str, source: date) -> None:
    if table in {"snapshot_entries", "trading_sessions", "limit_security_datasets", "limit_security_facts", "materialized_market_environment", "collection_runs", "collection_tasks", "refresh_runs"}:
        connection.execute(f"DELETE FROM {table} WHERE as_of = ?", (source.isoformat(),))


def _record_rejected_audit(
    store: SnapshotStore,
    audit_id: str,
    source: date,
    target: date,
    policy: ConflictPolicy,
    plan: DateRelabelPlan,
    images: dict[str, Any],
    result: DateRelabelResult,
    operator: str,
) -> None:
    """Persist a conflict attempt without mutating historical rows."""

    with store._connect() as connection:  # type: ignore[attr-defined]
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO date_relabel_audits(audit_id, source_as_of, target_as_of, status, operator, conflict_policy, plan_json, before_image_json, created_at, result_json) VALUES (?, ?, ?, 'rejected', ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                source.isoformat(),
                target.isoformat(),
                operator,
                policy,
                canonical_json(plan.as_dict()),
                canonical_json(
                    {
                        "before": images.get("before", {}),
                        "targetBefore": images.get("target_before", {}),
                        "after": {},
                    }
                ),
                _utc_now().isoformat(),
                canonical_json(result.as_dict()),
            ),
        )


def relabel_date(
    store: SnapshotStore,
    source_as_of: date,
    target_as_of: date,
    *,
    apply: bool = False,
    conflict_policy: ConflictPolicy = "reject",
    operator: str = "local",
    dry_run: bool | None = None,
    conflict: ConflictPolicy | None = None,
) -> DateRelabelResult:
    """Plan or apply a date relabel.  ``apply`` defaults to ``False``."""

    if dry_run is not None:
        apply = not dry_run
    if conflict is not None:
        conflict_policy = conflict
    plan, images = _build_plan(store, source_as_of, target_as_of, conflict_policy)
    audit_id = uuid.uuid4().hex
    if not apply:
        return DateRelabelResult(
            audit_id=audit_id,
            source_as_of=source_as_of,
            target_as_of=target_as_of,
            status="dry-run",
            entries=plan.entries,
            conflicts=plan.conflicts,
            warnings=plan.warnings,
            error="conflict detected; use an explicit conflict policy" if plan.conflicts and conflict_policy == "reject" else None,
        )
    # ``reject``/``skip`` never mutate a conflicting destination.  Explicit
    # ``overwrite`` is allowed only after the caller has opted into replacing
    # the target image; that image is retained in the audit for rollback.
    lease_conflicts = tuple(item for item in plan.conflicts if "active refresh lease" in item)
    if plan.conflicts and (conflict_policy != "overwrite" or lease_conflicts):
        result = DateRelabelResult(
            audit_id=audit_id,
            source_as_of=source_as_of,
            target_as_of=target_as_of,
            status="rejected",
            entries=plan.entries,
            conflicts=plan.conflicts,
            warnings=plan.warnings,
            error="conflict detected; no rows were changed; resolve destination rows before apply",
        )
        _record_rejected_audit(store, audit_id, source_as_of, target_as_of, conflict_policy, plan, images, result, operator)
        return result
    created = _utc_now().isoformat()
    plan_json = canonical_json(plan.as_dict())
    try:
        with store._connect() as connection:  # type: ignore[attr-defined]
            connection.execute("BEGIN IMMEDIATE")
            _lock_relabel_tables(store, connection)
            if _is_postgresql(store):
                _assert_no_active_relabel_leases(connection, source_as_of, target_as_of)
            # Re-read every source image under the write lock.  A collector
            # may have completed between planning and apply; never overwrite
            # or delete such a concurrent update using stale transformed rows.
            for table, expected_rows in images["before"].items():
                current_rows = (
                    _query_core_rows(connection, [str(item["task_id"]) for item in expected_rows])
                    if table == "core_index_results"
                    else _query_rows(connection, table, source_as_of)
                )
                expected_images = [
                    {key: value for key, value in item.items() if key != "rowid"}
                    for item in expected_rows
                ]
                current_images = [
                    {key: value for key, value in _row_dict(item).items() if key != "rowid"}
                    for item in current_rows
                ]
                if sorted(current_images, key=canonical_json) != sorted(expected_images, key=canonical_json):
                    raise DateRelabelError(f"source {table} changed after dry-run; re-plan before apply")
            connection.execute(
                "INSERT INTO date_relabel_audits(audit_id, source_as_of, target_as_of, status, operator, conflict_policy, plan_json, before_image_json, created_at) VALUES (?, ?, ?, 'applying', ?, ?, ?, ?, ?)",
                (
                    audit_id,
                    source_as_of.isoformat(),
                    target_as_of.isoformat(),
                    operator,
                    conflict_policy,
                    plan_json,
                    canonical_json(
                        {
                            "before": images["before"],
                            "targetBefore": images.get("target_before", {}),
                            "after": images["transformed"],
                        }
                    ),
                    created,
                ),
            )
            # Foreign-key-safe ordering: child detail rows first, then parent
            # task/run rows.  Source keys are removed only after destination
            # inserts have succeeded inside the same transaction.
            order = ("snapshot_entries", "trading_sessions", "limit_security_datasets", "limit_security_facts", "materialized_market_environment", "collection_runs", "collection_tasks", "core_index_results", "refresh_runs", "materialization_component_versions")
            if conflict_policy == "overwrite":
                for table in (
                    "snapshot_entries",
                    "trading_sessions",
                    "limit_security_datasets",
                    "limit_security_facts",
                    "materialized_market_environment",
                    "materialization_component_versions",
                ):
                    if images.get("target_before", {}).get(table):
                        connection.execute(
                            f"DELETE FROM {table} WHERE as_of = ?",
                            (target_as_of.isoformat(),),
                        )
            for table in order:
                rows = images["transformed"].get(table, [])
                if not rows:
                    continue
                if table in {"collection_runs", "collection_tasks", "core_index_results", "refresh_runs"}:
                    # These tables have stable run/task primary keys.  Move
                    # their date column in place rather than inserting a
                    # second row with the same identifier.
                    for row in rows:
                        if table == "collection_runs":
                            connection.execute("UPDATE collection_runs SET as_of = ? WHERE run_id = ?", (target_as_of.isoformat(), row["run_id"]))
                        elif table == "collection_tasks":
                            connection.execute("UPDATE collection_tasks SET as_of = ?, settled = ? WHERE task_id = ?", (target_as_of.isoformat(), int(row.get("settled", 0)), row["task_id"]))
                        elif table == "core_index_results":
                            connection.execute("UPDATE core_index_results SET payload_json = ? WHERE task_id = ? AND code = ?", (row["payload_json"], row["task_id"], row["code"]))
                        else:
                            connection.execute("UPDATE refresh_runs SET as_of = ? WHERE run_id = ? AND dataset = ?", (target_as_of.isoformat(), row["run_id"], row["dataset"]))
                else:
                    for row in rows:
                        _insert_row(
                            connection,
                            table,
                            row,
                            overwrite=conflict_policy == "overwrite",
                            postgresql=_is_postgresql(store),
                        )
            for table in ("snapshot_entries", "trading_sessions", "limit_security_datasets", "limit_security_facts", "materialized_market_environment"):
                if images["before"].get(table):
                    _delete_source_rows(connection, table, source_as_of)
            # Remove stale source-date revision rows; trigger writes above
            # created/updated the target-date revisions as needed.
            if images["before"].get("materialization_component_versions"):
                connection.execute(
                    "DELETE FROM materialization_component_versions WHERE as_of = ?",
                    (source_as_of.isoformat(),),
                )
            # Recompute the aggregate revision after component triggers have
            # run, preserving the CAS invariant for future collection writes.
            aggregate = images["transformed"].get("materialized_market_environment", [])
            if aggregate and images.get("aggregate_had_revision"):
                revision = store._materialization_revision(connection, target_as_of)  # type: ignore[attr-defined]
                item = aggregate[0]
                payload = json.loads(item["payload_json"])
                if revision:
                    payload[MATERIALIZED_COMPONENT_REVISION_KEY] = revision
                    connection.execute(
                        "UPDATE materialized_market_environment SET payload_json = ?, checksum = ? WHERE as_of = ?",
                        (canonical_json(payload), payload_checksum(payload), target_as_of.isoformat()),
                    )
            # Capture the exact post-commit image (including the aggregate's
            # newly assigned component revision) for rollback fencing.
            after_image: dict[str, list[dict[str, Any]]] = {}
            for table in order:
                if table == "core_index_results":
                    rows = _query_core_rows(connection, [str(item["task_id"]) for item in images["transformed"].get(table, [])])
                elif table in {"collection_runs", "collection_tasks", "refresh_runs"}:
                    rows = connection.execute(
                        f"SELECT * FROM {table} WHERE as_of = ? ORDER BY 1", (target_as_of.isoformat(),)
                    ).fetchall()
                else:
                    rows = connection.execute(
                        f"SELECT * FROM {table} WHERE as_of = ? ORDER BY 1", (target_as_of.isoformat(),)
                    ).fetchall()
                if rows or images["before"].get(table):
                    after_image[table] = [_row_dict(item) for item in rows]
            connection.execute(
                "UPDATE date_relabel_audits SET before_image_json = ? WHERE audit_id = ?",
                (
                    canonical_json(
                        {
                            "before": images["before"],
                            "targetBefore": images.get("target_before", {}),
                            "after": after_image,
                        }
                    ),
                    audit_id,
                ),
            )
            result = DateRelabelResult(audit_id, source_as_of, target_as_of, "applied", plan.entries, plan.conflicts, plan.warnings)
            connection.execute(
                "UPDATE date_relabel_audits SET status = 'applied', applied_at = ?, result_json = ? WHERE audit_id = ?",
                (_utc_now().isoformat(), canonical_json(result.as_dict()), audit_id),
            )
            return result
    except Exception:
        # The transaction context rolls back all data.  Keep a rejected audit
        # row only when the insert itself committed (normally it does not).
        raise


def rollback_date_relabel(
    store: SnapshotStore,
    audit_id: str,
    *,
    apply: bool = False,
) -> DateRelabelResult:
    """Restore the before-image for an applied audit (dry-run by default)."""

    with store._connect() as connection:  # type: ignore[attr-defined]
        row = connection.execute("SELECT * FROM date_relabel_audits WHERE audit_id = ?", (audit_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown date relabel audit: {audit_id}")
        source = _as_date(row["source_as_of"])
        target = _as_date(row["target_as_of"])
        image = _decode_json(row["before_image_json"], {})
        # Audits created by this implementation carry both before and after
        # images.  Accept the original plain mapping shape for forward
        # compatibility with an early development fixture.
        if isinstance(image, dict) and "before" in image:
            before = image.get("before") or {}
            target_before = image.get("targetBefore") or {}
            after = image.get("after") or {}
        else:
            before = image
            target_before = {}
            after = {}
        if row["status"] == "rolled-back":
            return DateRelabelResult(audit_id, source, target, "rolled-back")
        if row["status"] != "applied":
            raise DateRelabelError(f"rollback refused: audit {audit_id} status is {row['status']}")
        if not apply:
            entries = tuple(DateRelabelEntry(table, len(rows), action="restore") for table, rows in before.items() if rows)
            return DateRelabelResult(audit_id, source, target, "dry-run", entries=entries, warnings=("rollback requires explicit apply",))
        connection.execute("BEGIN IMMEDIATE")
        _lock_relabel_tables(store, connection)
        # Never delete a destination that may have been refreshed after this
        # migration.  Compare each target row to the audit after-image first.
        for table, expected_rows in after.items():
            if table == "core_index_results":
                current_rows = _query_core_rows(connection, [str(item["task_id"]) for item in expected_rows])
            else:
                current_rows = connection.execute(
                    f"SELECT * FROM {table} WHERE as_of = ? ORDER BY 1", (target.isoformat(),)
                ).fetchall()
            expected_images = [
                {key: value for key, value in item.items() if key != "rowid"}
                for item in expected_rows
            ]
            current_images = [
                {key: value for key, value in _row_dict(item).items() if key != "rowid"}
                for item in current_rows
            ]
            # Compare complete row sets (including cardinality).  Any later
            # write, insertion or deletion makes rollback unsafe.
            if sorted(current_images, key=canonical_json) != sorted(expected_images, key=canonical_json):
                raise DateRelabelError(f"rollback refused: {table} target rows changed after audit {audit_id}")
        # Remove target rows first, then restore every source before-image.
        # Core index results reference collection_tasks, so remove those child
        # rows before deleting the moved task/run rows. SQLite's historical
        # fixtures did not exercise this rollback path, but PostgreSQL enforces
        # the foreign key in production.
        for item in after.get("core_index_results", []):
            connection.execute(
                "DELETE FROM core_index_results WHERE task_id = ? AND code = ?",
                (item["task_id"], item["code"]),
            )
        for table in ("snapshot_entries", "trading_sessions", "limit_security_datasets", "limit_security_facts", "materialized_market_environment", "materialization_component_versions", "refresh_runs", "collection_tasks", "collection_runs"):
            # Triggers can create a target component-revision row even when a
            # legacy source database had no corresponding before-image.  Use
            # either image to decide whether the target key belongs to this
            # audit, so rollback cannot leave a ghost revision behind.
            if before.get(table) or target_before.get(table) or after.get(table):
                connection.execute(f"DELETE FROM {table} WHERE as_of = ?", (target.isoformat(),))
        for table, rows in before.items():
            for item in rows:
                _insert_row(connection, table, item, overwrite=True, postgresql=_is_postgresql(store))
        for table, rows in target_before.items():
            for item in rows:
                _insert_row(connection, table, item, overwrite=True, postgresql=_is_postgresql(store))
        # INSERT OR REPLACE fires the component-revision triggers and can
        # increment a restored revision.  Re-apply the audited revision value
        # directly after all row restores so rollback is deterministic.
        for item in before.get("materialization_component_versions", []):
            connection.execute(
                "UPDATE materialization_component_versions SET revision = ? WHERE component_kind = ? AND dataset = ? AND as_of = ?",
                (item["revision"], item["component_kind"], item["dataset"], item["as_of"]),
            )
        for item in target_before.get("materialization_component_versions", []):
            connection.execute(
                "UPDATE materialization_component_versions SET revision = ? WHERE component_kind = ? AND dataset = ? AND as_of = ?",
                (item["revision"], item["component_kind"], item["dataset"], item["as_of"]),
            )
        # Restore component revision rows captured by future schema versions if
        # present; current audits do not include them and triggers remain valid.
        connection.execute(
            "UPDATE date_relabel_audits SET status = 'rolled-back', rolled_back_at = ?, result_json = ? WHERE audit_id = ?",
            (_utc_now().isoformat(), canonical_json({"auditId": audit_id, "status": "rolled-back"}), audit_id),
        )
        return DateRelabelResult(audit_id, source, target, "rolled-back")


def get_date_relabel_audit(store: SnapshotStore, audit_id: str) -> dict[str, Any] | None:
    """Return one audit row as JSON-safe data for operator readback."""

    with store._connect() as connection:  # type: ignore[attr-defined]
        row = connection.execute("SELECT * FROM date_relabel_audits WHERE audit_id = ?", (audit_id,)).fetchone()
    if row is None:
        return None
    result = _row_dict(row)
    for key in ("plan_json", "before_image_json", "result_json"):
        if result.get(key):
            try:
                result[key] = json.loads(result[key])
            except (TypeError, ValueError):
                pass
    return result


def list_date_relabel_audits(store: SnapshotStore) -> tuple[dict[str, Any], ...]:
    with store._connect() as connection:  # type: ignore[attr-defined]
        rows = connection.execute("SELECT audit_id FROM date_relabel_audits ORDER BY created_at, audit_id").fetchall()
    return tuple(item for item in (get_date_relabel_audit(store, row["audit_id"]) for row in rows) if item is not None)


class DateRelabeler:
    """Small object-oriented facade for callers running several migrations."""

    def __init__(self, store: SnapshotStore | str | Path) -> None:
        self.store = store if isinstance(store, SnapshotStore) else SnapshotStore(store)

    def plan(self, source_as_of: date, target_as_of: date, *, conflict_policy: ConflictPolicy = "reject") -> DateRelabelPlan:
        return plan_date_relabel(self.store, source_as_of, target_as_of, conflict_policy=conflict_policy)

    def relabel(self, source_as_of: date, target_as_of: date, **kwargs: Any) -> DateRelabelResult:
        return relabel_date(self.store, source_as_of, target_as_of, **kwargs)

    def rollback(self, audit_id: str, *, apply: bool = False) -> DateRelabelResult:
        return rollback_date_relabel(self.store, audit_id, apply=apply)


# Friendly alias used by scripts that call this a snapshot migration.
snapshot_date_relabel = relabel_date


def migrate_snapshot_date(
    store: SnapshotStore,
    source_as_of: date | None = None,
    target_as_of: date | None = None,
    *,
    source: date | None = None,
    target: date | None = None,
    dry_run: bool = True,
    apply: bool | None = None,
    conflict_policy: ConflictPolicy = "reject",
    operator: str = "local",
) -> DateRelabelResult:
    """Compatibility wrapper with explicit ``dry_run``/``apply`` controls."""

    resolved_source = source_as_of or source
    resolved_target = target_as_of or target
    if resolved_source is None or resolved_target is None:
        raise TypeError("source_as_of and target_as_of are required")
    effective_apply = (not dry_run) if apply is None else bool(apply)
    return relabel_date(
        store,
        resolved_source,
        resolved_target,
        apply=effective_apply,
        conflict_policy=conflict_policy,
        operator=operator,
    )


relabel_snapshots = migrate_snapshot_date
migrate_date = migrate_snapshot_date
relabel_snapshot_dates = migrate_snapshot_date
