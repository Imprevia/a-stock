"""Fuyao THS catalog, index history and capability boundaries."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ....domain.analysis.ths_sector import build_rankings, catalog_checksum
from ....domain.models.capability import ProviderCapabilityReport, redact
from ....domain.models.ths_sector import (
    THS_TAGS,
    ThsCatalogRelation,
    ThsCatalogRevision,
    ThsRankingRow,
    ThsSectorBar,
    ThsSectorMembership,
    ThsSnapshotFact,
    normalize_thscode,
)
from .market import FuyaoMarketClient, FuyaoMarketContractError


SHANGHAI_ZONE = ZoneInfo("Asia/Shanghai")
THS_CATALOG_CAPABILITY = "industry-ranking"
THS_MEMBERSHIP_CAPABILITY = "sector-membership"
THS_HISTORY_CAPABILITY = "sector-turnover-history"
THS_DUMP_CAPABILITIES = (
    "sector-member-daily-dump",
    "sector-member-incremental-dump",
    "sector-member-adjustment-dump",
)
THS_CAPABILITY_DATASETS = (
    THS_CATALOG_CAPABILITY,
    THS_MEMBERSHIP_CAPABILITY,
    THS_HISTORY_CAPABILITY,
    *THS_DUMP_CAPABILITIES,
)


class FuyaoThsCapabilityError(RuntimeError):
    """Raised before provider construction when a capability is not approved."""


class FuyaoThsCapabilityPolicy:
    """Resolve exact operation revisions without exposing report secrets."""

    def __init__(self, reports: Any, *, enabled: Mapping[str, bool] | None = None) -> None:
        self._reports = reports
        self._enabled = dict(enabled or {})

    def require(self, dataset: str, revision: str) -> ProviderCapabilityReport:
        if dataset not in THS_CAPABILITY_DATASETS:
            raise FuyaoThsCapabilityError(f"unsupported THS capability dataset: {dataset}")
        if not self._enabled.get(dataset, False):
            raise FuyaoThsCapabilityError(f"Fuyao THS capability is disabled: {dataset}")
        report = self._reports.get_capability_report("fuyao", dataset, revision)
        if report is None:
            raise FuyaoThsCapabilityError(
                f"missing eligible Fuyao THS capability report: {dataset}/{revision}"
            )
        if report.status != "eligible" or report.revision != revision:
            raise FuyaoThsCapabilityError(
                f"Fuyao THS capability is not eligible: {dataset}/{revision}"
            )
        raw = report.to_dict()
        if redact(raw) != raw:
            raise FuyaoThsCapabilityError("Fuyao THS capability evidence is not redacted")
        if not report.permission_evidence or report.permission_evidence.get("approved") is not True:
            raise FuyaoThsCapabilityError("Fuyao THS capability lacks approved permission evidence")
        budget = report.rate_limit_evidence.get("requestBudget")
        if not isinstance(budget, int) or budget <= 0:
            raise FuyaoThsCapabilityError("Fuyao THS capability lacks a positive request budget")
        return report


@dataclass(frozen=True, slots=True)
class ThsCatalogSnapshotBundle:
    revision: ThsCatalogRevision
    relations: tuple[ThsCatalogRelation, ...]
    snapshots: tuple[ThsSnapshotFact, ...]
    rankings: tuple[ThsRankingRow, ...]
    warnings: tuple[str, ...] = ()
    catalog_timestamps: tuple[datetime, ...] = ()
    snapshot_timestamps: tuple[datetime, ...] = ()


def _canonical_checksum(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class FuyaoThsSectorAdapter:
    CATALOG_ENDPOINT = "/api/a-share-index/catalog/ths-index-list"
    MEMBERSHIP_ENDPOINT = "/api/a-share-index/constituents/ths-stock-list"
    SNAPSHOT_ENDPOINT = "/api/a-share-index/prices/snapshot"
    HISTORY_ENDPOINT = "/api/a-share-index/prices/historical"
    SNAPSHOT_BATCH_SIZE = 80

    def __init__(
        self,
        client: FuyaoMarketClient,
        *,
        catalog_revision: str,
        history_revision: str,
        membership_revision: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.client = client
        self.catalog_revision = str(catalog_revision).strip()
        self.history_revision = str(history_revision).strip()
        self.membership_revision = str(
            membership_revision or catalog_revision
        ).strip()
        if not self.catalog_revision or not self.history_revision or not self.membership_revision:
            raise ValueError("catalog, membership and history revisions are required")
        self._now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _rows(value: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw = value.get("item", value.get("rows", value.get("diff", value.get("klines", []))))
        if isinstance(raw, Mapping):
            raw = list(raw.values())
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, Mapping)]

    @staticmethod
    def _first(value: Mapping[str, Any], *names: str) -> Any:
        for name in names:
            if name in value and value[name] not in (None, "", "-"):
                return value[name]
        return None

    @classmethod
    def _text(cls, value: Mapping[str, Any], *names: str) -> str | None:
        raw = cls._first(value, *names)
        return str(raw).strip() if raw not in (None, "") else None

    @classmethod
    def _number(cls, value: Mapping[str, Any], *names: str) -> float | None:
        raw = cls._first(value, *names)
        if raw is None:
            return None
        try:
            normalized = float(raw)
        except (TypeError, ValueError):
            return None
        return normalized if math.isfinite(normalized) else None

    @classmethod
    def _date(cls, value: Mapping[str, Any]) -> date | None:
        raw = cls._first(value, "date", "trade_date", "tradeDate", "datetime")
        if raw is not None:
            text = str(raw).strip()
            for candidate in (text[:10], text.replace("/", "-")[:10]):
                try:
                    return date.fromisoformat(candidate)
                except ValueError:
                    continue
        timestamp = cls._first(value, "date_ms", "dateMs", "timestamp")
        return cls._timestamp(timestamp).date() if timestamp is not None else None

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=SHANGHAI_ZONE)
        if isinstance(value, str) and "T" in value:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI_ZONE)
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise FuyaoMarketContractError("Fuyao THS response lacks a valid timestamp") from exc
        if abs(number) > 10_000_000_000:
            number /= 1000
        try:
            return datetime.fromtimestamp(number, SHANGHAI_ZONE)
        except (OSError, OverflowError, ValueError) as exc:
            raise FuyaoMarketContractError("Fuyao THS response timestamp is invalid") from exc

    def normalize_catalog_snapshot(
        self,
        catalogs: Mapping[str, Mapping[str, Any]],
        snapshot_batches: Sequence[Mapping[str, Any]],
        *,
        as_of: date,
        fetched_at: datetime | None = None,
    ) -> ThsCatalogSnapshotBundle:
        if set(catalogs) != set(THS_TAGS):
            raise FuyaoMarketContractError("Fuyao THS catalog requires exactly four tags")
        relations: list[ThsCatalogRelation] = []
        provider_times: list[datetime] = []
        tag_counts: dict[str, int] = {}
        for tag in THS_TAGS:
            payload = catalogs[tag]
            timestamp = self._first(payload, "timestamp", "provider_timestamp", "providerTimestamp")
            if timestamp is None:
                raise FuyaoMarketContractError(f"Fuyao THS catalog {tag} lacks provider timestamp")
            provider_time = self._timestamp(timestamp)
            if provider_time.astimezone(SHANGHAI_ZONE).date() != as_of:
                raise FuyaoMarketContractError(f"Fuyao THS catalog {tag} date mismatch")
            provider_times.append(provider_time)
            seen: dict[str, str] = {}
            for row in self._rows(payload):
                code = normalize_thscode(self._text(row, "thscode", "ths_code", "code") or "")
                name = self._text(row, "name", "index_name", "industry_name")
                if not name:
                    raise FuyaoMarketContractError(f"Fuyao THS catalog {tag} row lacks name")
                previous = seen.get(code)
                if previous is not None:
                    raise FuyaoMarketContractError(
                        f"Fuyao THS catalog {tag} contains duplicate identity {code}"
                    )
                seen[code] = name
                relations.append(ThsCatalogRelation(self.catalog_revision, tag, code, name))
            if not seen:
                raise FuyaoMarketContractError(f"Fuyao THS catalog {tag} is empty")
            tag_counts[tag] = len(seen)

        snapshot_rows: dict[str, Mapping[str, Any]] = {}
        snapshot_times: list[datetime] = []
        for batch in snapshot_batches:
            timestamp = self._first(batch, "timestamp", "provider_timestamp", "providerTimestamp")
            if timestamp is None:
                raise FuyaoMarketContractError("Fuyao THS snapshot batch lacks provider timestamp")
            provider_time = self._timestamp(timestamp)
            if provider_time.astimezone(SHANGHAI_ZONE).date() != as_of:
                raise FuyaoMarketContractError("Fuyao THS snapshot batch date mismatch")
            snapshot_times.append(provider_time)
            for row in self._rows(batch):
                code = normalize_thscode(self._text(row, "thscode", "ths_code", "code") or "")
                if code in snapshot_rows:
                    raise FuyaoMarketContractError(
                        f"Fuyao THS snapshot contains duplicate identity {code}"
                    )
                snapshot_rows[code] = row
        # Identify snapshot rows for which the provider dropped every live market
        # field (e.g. suspended / delisted / newly-listed `thscode`s whose day
        # remains empty). Those rows would otherwise fail ThsSnapshotFact validation
        # and abort the whole bundle, so they are demoted to a row-level warning and
        # their catalog relations are dropped to keep the bundle invariant
        # `set(snapshot_rows) == set(relations.thscode) == expected_codes`.
        empty_market_codes: set[str] = set()
        market_value_aliases = (
            ("open", "open_price", "o"),
            ("high", "high_price", "h"),
            ("low", "low_price", "l"),
            ("close", "close_price", "c", "last_price"),
            ("volume", "vol"),
            ("turnover", "amount", "amt", "f6"),
        )
        for code, row in snapshot_rows.items():
            if all(
                self._number(row, *aliases) is None
                for aliases in market_value_aliases
            ):
                empty_market_codes.add(code)
        if empty_market_codes:
            snapshot_rows = {
                code: row for code, row in snapshot_rows.items()
                if code not in empty_market_codes
            }
            relations = tuple(
                relation for relation in relations
                if relation.thscode not in empty_market_codes
            )
            tag_counts = {
                tag: sum(1 for relation in relations if relation.tag == tag)
                for tag in THS_TAGS
            }
        expected_codes = {relation.thscode for relation in relations}
        if set(snapshot_rows) != expected_codes:
            missing = sorted(expected_codes - set(snapshot_rows))
            extra = sorted(set(snapshot_rows) - expected_codes)
            raise FuyaoMarketContractError(
                f"Fuyao THS snapshot coverage mismatch; missing={missing}, extra={extra}"
            )
        names_by_code: dict[str, set[str]] = {}
        for relation in relations:
            names_by_code.setdefault(relation.thscode, set()).add(relation.name)
        conflicting = {code: names for code, names in names_by_code.items() if len(names) != 1}
        if conflicting:
            raise FuyaoMarketContractError(
                f"Fuyao THS cross-tag name conflict: {sorted(conflicting)}"
            )

        snapshots: list[ThsSnapshotFact] = []
        missing_change_pct: list[str] = []
        snapshot_time = max(snapshot_times)
        for code in sorted(snapshot_rows):
            row = snapshot_rows[code]
            change_pct = self._number(row, "price_change_ratio_pct", "change_pct", "changePct", "f3")
            if change_pct is None:
                # Provider gap: the snapshot row omits every alias for the daily
                missing_change_pct.append(code)
            snapshots.append(
                ThsSnapshotFact(
                    thscode=code,
                    name=next(iter(names_by_code[code])),
                    as_of=as_of,
                    provider_timestamp=snapshot_time,
                    change_pct=change_pct,
                    open=self._number(row, "open", "open_price", "o"),
                    high=self._number(row, "high", "high_price", "h"),
                    low=self._number(row, "low", "low_price", "l"),
                    close=self._number(row, "close", "close_price", "c", "last_price"),
                    volume=self._number(row, "volume", "vol"),
                    turnover=self._number(row, "turnover", "amount", "amt", "f6"),
                )
            )
        checksum = catalog_checksum(relations)
        revision = ThsCatalogRevision(
            revision_id=self.catalog_revision,
            capability_revision=self.catalog_revision,
            provider_timestamp=max((*provider_times, *snapshot_times)),
            fetched_at=fetched_at or self._now(),
            tag_counts=tag_counts,
            checksum=checksum,
        )
        rankings = build_rankings(
            relations,
            snapshots,
            catalog_revision=self.catalog_revision,
            as_of=as_of,
        )
        warnings = (
            *tuple(
                f"{code} snapshot row has no live market values for {as_of.isoformat()}; "
                "dropped from snapshot and ranking for this revision"
                for code in sorted(empty_market_codes)
            ),
            *tuple(
                f"{snapshot.thscode} volume is unavailable"
                for snapshot in snapshots
                if snapshot.volume is None
            ),
            *tuple(
                f"{thscode} changePct missing from provider snapshot"
                for thscode in missing_change_pct
            ),
        )
        return ThsCatalogSnapshotBundle(
            revision,
            tuple(relations),
            tuple(snapshots),
            rankings,
            warnings,
            tuple(provider_times),
            tuple(snapshot_times),
        )

    def fetch_catalog_snapshot(
        self,
        as_of: date,
        *,
        batch_size: int | None = None,
    ) -> ThsCatalogSnapshotBundle:
        catalogs = {
            tag: self.client.request(
                self.CATALOG_ENDPOINT,
                params={"tag": tag},
                requested_date=as_of,
            ).data
            for tag in THS_TAGS
        }
        codes = sorted(
            {
                normalize_thscode(self._text(row, "thscode", "ths_code", "code") or "")
                for payload in catalogs.values()
                for row in self._rows(payload)
            }
        )
        selected_batch_size = max(1, int(batch_size or self.SNAPSHOT_BATCH_SIZE))
        snapshots = [
            self.client.request(
                self.SNAPSHOT_ENDPOINT,
                params={"thscodes": ",".join(codes[offset : offset + selected_batch_size])},
                requested_date=as_of,
            ).data
            for offset in range(0, len(codes), selected_batch_size)
        ]
        return self.normalize_catalog_snapshot(catalogs, snapshots, as_of=as_of)

    def normalize_memberships(
        self,
        thscode: str,
        payload: Mapping[str, Any],
        *,
        as_of: date,
        fetched_at: datetime | None = None,
    ) -> tuple[ThsSectorMembership, ...]:
        code = normalize_thscode(thscode)
        timestamp = self._first(
            payload,
            "timestamp",
            "provider_timestamp",
            "providerTimestamp",
        )
        if timestamp is None:
            raise FuyaoMarketContractError(
                f"Fuyao THS membership {code} lacks provider timestamp"
            )
        provider_timestamp = self._timestamp(timestamp)
        if provider_timestamp.astimezone(SHANGHAI_ZONE).date() != as_of:
            raise FuyaoMarketContractError(
                f"Fuyao THS membership {code} date mismatch"
            )
        response_code = self._text(
            payload,
            "index_thscode",
            "indexThscode",
            "identity",
        )
        if response_code and normalize_thscode(response_code) != code:
            raise FuyaoMarketContractError(
                "Fuyao THS membership identity mismatch: "
                f"requested {code}, observed {response_code}"
            )
        rows = self._rows(payload)
        if not rows:
            raise FuyaoMarketContractError(f"Fuyao THS membership {code} is empty")

        fetch_time = fetched_at or self._now()
        seen: set[str] = set()
        memberships: list[ThsSectorMembership] = []
        for row in rows:
            member_code = self._text(row, "thscode", "security_id", "securityId")
            member_name = self._text(row, "name", "security_name", "securityName")
            if not member_code or not member_name:
                raise FuyaoMarketContractError(
                    f"Fuyao THS membership {code} row lacks member identity"
                )
            normalized_member = member_code.strip().upper()
            if normalized_member in seen:
                raise FuyaoMarketContractError(
                    f"Fuyao THS membership {code} contains duplicate member {normalized_member}"
                )
            seen.add(normalized_member)
            logical = {
                "thscode": code,
                "memberSecurityId": normalized_member,
                "memberName": member_name,
                "asOf": as_of.isoformat(),
                "sourceRevision": self.membership_revision,
            }
            memberships.append(
                ThsSectorMembership(
                    thscode=code,
                    member_security_id=normalized_member,
                    member_name=member_name,
                    as_of=as_of,
                    provider_timestamp=provider_timestamp,
                    fetched_at=fetch_time,
                    source_revision=self.membership_revision,
                    checksum=_canonical_checksum(logical),
                )
            )
        memberships.sort(key=lambda item: item.member_security_id)
        return tuple(memberships)

    def fetch_memberships(
        self,
        thscode: str,
        *,
        as_of: date,
    ) -> tuple[ThsSectorMembership, ...]:
        code = normalize_thscode(thscode)
        response = self.client.request(
            self.MEMBERSHIP_ENDPOINT,
            params={"thscode": code},
            requested_date=as_of,
        )
        return self.normalize_memberships(code, response.data, as_of=as_of)

    def normalize_history(
        self,
        thscode: str,
        rows: Sequence[Mapping[str, Any]],
        *,
        start_date: date,
        end_date: date,
        fetched_at: datetime | None = None,
    ) -> tuple[ThsSectorBar, ...]:
        code = normalize_thscode(thscode)
        self._validate_history_range(start_date, end_date)
        normalized: list[ThsSectorBar] = []
        seen_dates: set[date] = set()
        fetch_time = fetched_at or self._now()
        for row in rows:
            response_code = self._text(row, "thscode", "identity", "code")
            if response_code and normalize_thscode(response_code) != code:
                raise FuyaoMarketContractError(
                    f"Fuyao THS history identity mismatch for {code}"
                )
            trading_date = self._date(row)
            if trading_date is None or not start_date <= trading_date <= end_date:
                raise FuyaoMarketContractError(
                    f"Fuyao THS history date outside requested range for {code}"
                )
            if trading_date in seen_dates:
                raise FuyaoMarketContractError(
                    f"Fuyao THS history contains duplicate date {trading_date}"
                )
            seen_dates.add(trading_date)
            values = {
                "open": self._number(row, "open", "open_price", "o"),
                "high": self._number(row, "high", "high_price", "h"),
                "low": self._number(row, "low", "low_price", "l"),
                "close": self._number(row, "close", "close_price", "c", "last_price"),
                "volume": self._number(row, "volume", "vol"),
                "turnover": self._number(row, "turnover", "amount", "amt", "f6"),
            }
            missing_ohlc = [name for name in ("open", "high", "low", "close") if values[name] is None]
            if missing_ohlc:
                raise FuyaoMarketContractError(
                    f"Fuyao THS history {code}/{trading_date} lacks {','.join(missing_ohlc)}"
                )
            warnings = tuple(
                f"{field_name} is unavailable"
                for field_name in ("volume", "turnover")
                if values[field_name] is None
            )
            quality = "partial" if warnings else "ok"
            logical = {
                "thscode": code,
                "tradingDate": trading_date.isoformat(),
                **values,
                "sourceRevision": self.history_revision,
            }
            normalized.append(
                ThsSectorBar(
                    thscode=code,
                    trading_date=trading_date,
                    source="fuyao",
                    source_revision=self.history_revision,
                    checksum=_canonical_checksum(logical),
                    fetched_at=fetch_time,
                    quality=quality,
                    warnings=warnings,
                    **values,
                )
            )
        normalized.sort(key=lambda item: item.trading_date)
        return tuple(normalized)

    def fetch_history(
        self,
        thscode: str,
        *,
        start_date: date,
        end_date: date,
    ) -> tuple[ThsSectorBar, ...]:
        code = normalize_thscode(thscode)
        self._validate_history_range(start_date, end_date)
        start = int(datetime.combine(start_date, time.min, SHANGHAI_ZONE).timestamp() * 1000)
        end = int(datetime.combine(end_date, time.max, SHANGHAI_ZONE).timestamp() * 1000)
        response = self.client.request(
            self.HISTORY_ENDPOINT,
            params={"thscode": code, "interval": "1d", "start": start, "end": end},
            requested_date=end_date,
        )
        response_code = self._text(response.data, "thscode", "identity")
        if response_code and normalize_thscode(response_code) != code:
            raise FuyaoMarketContractError(
                f"Fuyao THS history identity mismatch: requested {code}, observed {response_code}"
            )
        return self.normalize_history(
            code,
            self._rows(response.data),
            start_date=start_date,
            end_date=end_date,
        )

    @staticmethod
    def _validate_history_range(start_date: date, end_date: date) -> None:
        if start_date > end_date:
            raise ValueError("history date range must be ordered")
        if (end_date - start_date).days > 366 * 5 + 2:
            raise ValueError("history date range cannot exceed five years")


__all__ = [
    "FuyaoThsCapabilityError",
    "FuyaoThsCapabilityPolicy",
    "FuyaoThsSectorAdapter",
    "THS_CAPABILITY_DATASETS",
    "THS_CATALOG_CAPABILITY",
    "THS_DUMP_CAPABILITIES",
    "THS_HISTORY_CAPABILITY",
    "THS_MEMBERSHIP_CAPABILITY",
    "ThsCatalogSnapshotBundle",
]
