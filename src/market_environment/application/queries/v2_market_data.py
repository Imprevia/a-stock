"""Closed, bounded query facade for provider-free v2 market-data reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..ports.v2_market_data import SortKey, V2MarketDataReadPort, V2Page, V2Resource


HISTORY_DEFAULT = 60
HISTORY_MAXIMUM = 250
POOL_DEFAULT = 20
POOL_MAXIMUM = 100
SECTOR_DEFAULT = 20
SECTOR_MAXIMUM = 100
ACTIVE_DIRECTION_DEFAULT = 20
ACTIVE_DIRECTION_MAXIMUM = 100
EVENTS_DEFAULT = 20
EVENTS_MAXIMUM = 100
CHECKPOINT_DEFAULT = 50
CHECKPOINT_MAXIMUM = 200

LIMIT_POOL_TYPES = frozenset(
    {"limit_up", "limit_down", "failed_limit_up", "promoted"}
)
SECTOR_TAGS = frozenset({"industry", "cn_concept", "region", "tszs"})


def _bounded_limit(value: int | None, *, default: int, maximum: int) -> int:
    selected = default if value is None else value
    if selected <= 0 or selected > maximum:
        raise ValueError(f"limit must be within 1..{maximum}")
    return selected


def _date_window(
    start_date: date | None,
    end_date: date | None,
) -> tuple[date | None, date | None]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    return start_date, end_date


def _required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


@dataclass(frozen=True, slots=True)
class V2MarketDataQueries:
    """Application-owned facade; all I/O is delegated to one local read port."""

    reads: V2MarketDataReadPort

    def overview(self, as_of: date) -> V2Resource | None:
        return self.reads.overview(as_of)

    def indices(self, as_of: date) -> V2Resource | None:
        return self.reads.indices(as_of)

    def index(self, as_of: date, code: str) -> V2Resource | None:
        return self.reads.index(as_of, _required_text(code, "code"))

    def index_history(
        self,
        as_of: date,
        code: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        after: SortKey | None = None,
        limit: int | None = None,
    ) -> V2Page | None:
        start_date, end_date = _date_window(start_date, end_date)
        return self.reads.index_history(
            as_of,
            _required_text(code, "code"),
            start_date=start_date,
            end_date=end_date,
            after=after,
            limit=_bounded_limit(limit, default=HISTORY_DEFAULT, maximum=HISTORY_MAXIMUM),
        )

    def breadth(self, as_of: date) -> V2Resource | None:
        return self.reads.breadth(as_of)

    def breadth_history(
        self,
        as_of: date,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        after: SortKey | None = None,
        limit: int | None = None,
    ) -> V2Page | None:
        start_date, end_date = _date_window(start_date, end_date)
        return self.reads.breadth_history(
            as_of,
            start_date=start_date,
            end_date=end_date,
            after=after,
            limit=_bounded_limit(limit, default=HISTORY_DEFAULT, maximum=HISTORY_MAXIMUM),
        )

    def limits(self, as_of: date) -> V2Resource | None:
        return self.reads.limits(as_of)

    def limits_pool(
        self,
        as_of: date,
        pool_type: str,
        *,
        after: SortKey | None = None,
        limit: int | None = None,
    ) -> V2Page | None:
        if pool_type not in LIMIT_POOL_TYPES:
            raise ValueError(f"unsupported limits pool: {pool_type}")
        return self.reads.limits_pool(
            as_of,
            pool_type,
            after=after,
            limit=_bounded_limit(limit, default=POOL_DEFAULT, maximum=POOL_MAXIMUM),
        )

    def limits_history(
        self,
        as_of: date,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        after: SortKey | None = None,
        limit: int | None = None,
    ) -> V2Page | None:
        start_date, end_date = _date_window(start_date, end_date)
        return self.reads.limits_history(
            as_of,
            start_date=start_date,
            end_date=end_date,
            after=after,
            limit=_bounded_limit(limit, default=HISTORY_DEFAULT, maximum=HISTORY_MAXIMUM),
        )

    def limits_evidence(self, as_of: date) -> V2Resource | None:
        return self.reads.limits_evidence(as_of)

    def sector_rankings(
        self,
        as_of: date,
        *,
        tag: str | None = None,
        after: SortKey | None = None,
        limit: int | None = None,
    ) -> V2Page | None:
        if tag is not None and tag not in SECTOR_TAGS:
            raise ValueError(f"unsupported sector tag: {tag}")
        return self.reads.sector_rankings(
            as_of,
            tag=tag,
            after=after,
            limit=_bounded_limit(limit, default=SECTOR_DEFAULT, maximum=SECTOR_MAXIMUM),
        )

    def sector_turnover(
        self,
        as_of: date,
        *,
        after: SortKey | None = None,
        limit: int | None = None,
    ) -> V2Page | None:
        return self.reads.sector_turnover(
            as_of,
            after=after,
            limit=_bounded_limit(limit, default=SECTOR_DEFAULT, maximum=SECTOR_MAXIMUM),
        )

    def sector_breadth(
        self,
        as_of: date,
        *,
        after: SortKey | None = None,
        limit: int | None = None,
    ) -> V2Page | None:
        return self.reads.sector_breadth(
            as_of,
            after=after,
            limit=_bounded_limit(limit, default=SECTOR_DEFAULT, maximum=SECTOR_MAXIMUM),
        )

    def sector_analysis(self, as_of: date) -> V2Resource | None:
        return self.reads.sector_analysis(as_of)

    def active_direction(
        self,
        as_of: date,
        *,
        after: SortKey | None = None,
        limit: int | None = None,
    ) -> V2Page | None:
        return self.reads.active_direction(
            as_of,
            after=after,
            limit=_bounded_limit(
                limit,
                default=ACTIVE_DIRECTION_DEFAULT,
                maximum=ACTIVE_DIRECTION_MAXIMUM,
            ),
        )

    def active_direction_workbench(self, as_of: date) -> V2Resource | None:
        reader = getattr(self.reads, "active_direction_workbench", None)
        return reader(as_of) if callable(reader) else None

    def events(
        self,
        as_of: date,
        *,
        after: SortKey | None = None,
        limit: int | None = None,
    ) -> V2Page | None:
        return self.reads.events(
            as_of,
            after=after,
            limit=_bounded_limit(limit, default=EVENTS_DEFAULT, maximum=EVENTS_MAXIMUM),
        )

    def assessment(self, as_of: date) -> V2Resource | None:
        return self.reads.assessment(as_of)

    def operation_summary(self, run_id: str) -> V2Resource | None:
        return self.reads.operation_summary(_required_text(run_id, "run_id"))

    def operation_checkpoints(
        self,
        run_id: str,
        *,
        after: SortKey | None = None,
        limit: int | None = None,
    ) -> V2Page | None:
        return self.reads.operation_checkpoints(
            _required_text(run_id, "run_id"),
            after=after,
            limit=_bounded_limit(
                limit,
                default=CHECKPOINT_DEFAULT,
                maximum=CHECKPOINT_MAXIMUM,
            ),
        )


__all__ = [
    "ACTIVE_DIRECTION_DEFAULT",
    "ACTIVE_DIRECTION_MAXIMUM",
    "CHECKPOINT_DEFAULT",
    "CHECKPOINT_MAXIMUM",
    "EVENTS_DEFAULT",
    "EVENTS_MAXIMUM",
    "HISTORY_DEFAULT",
    "HISTORY_MAXIMUM",
    "LIMIT_POOL_TYPES",
    "POOL_DEFAULT",
    "POOL_MAXIMUM",
    "SECTOR_DEFAULT",
    "SECTOR_MAXIMUM",
    "SECTOR_TAGS",
    "V2MarketDataQueries",
]
