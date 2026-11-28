"""Validated inputs for the personal trading ledger."""

from __future__ import annotations

from datetime import date, time as TradeTime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ...trading_sessions import validate_actual_session_date


Security = Annotated[str, StringConstraints(to_upper=True, strip_whitespace=True, pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Money = Annotated[Decimal, Field(ge=0, max_digits=15, decimal_places=2)]
Price = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=6)]
Shares = Annotated[int, Field(ge=0, le=1_000_000_000)]
LedgerDate = Annotated[date, Field(ge=date(2000, 1, 1), le=date(2099, 12, 31))]
MAX_IMAGES = 6
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class ScreenshotError(ValueError):
    pass


class LedgerUnavailable(RuntimeError):
    pass


class LedgerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Trade(LedgerInput):
    date: LedgerDate
    security: Security
    name: Annotated[str, Field(max_length=60)] = ""
    side: Literal["buy", "sell"]
    status: Literal["filled", "partial", "pending", "canceled"]
    filled_quantity: Shares
    ordered_quantity: Shares | None = None
    price: Price | None = None
    amount: Money | None = None
    commission: Money | None = None
    other_fees: Money | None = None
    fees_pending: bool = False
    time: TradeTime | None = None
    order_id: Reference | None = None
    trade_id: Reference | None = None
    event_id: Reference | None = None
    cumulative: bool = False

    @model_validator(mode="after")
    def check_consistency(self) -> Trade:
        if self.time is not None and self.time.tzinfo is not None:
            raise ValueError("交易时间应为上海本地时刻")
        if self.ordered_quantity is not None and self.filled_quantity > self.ordered_quantity:
            raise ValueError("实际成交量不能超过委托量")
        if self.status in {"filled", "partial"} and not self.filled_quantity:
            raise ValueError("请核对实际成交股数")
        if self.status == "pending" and self.filled_quantity:
            raise ValueError("未成交委托的实际成交量应为零")
        if self.status == "filled" and self.ordered_quantity not in (None, self.filled_quantity):
            raise ValueError("全部成交时委托量与实际成交量应一致")
        if self.status == "partial" and self.ordered_quantity == self.filled_quantity:
            raise ValueError("部分成交的实际成交量应小于委托量")
        if self.cumulative and (not self.order_id or self.trade_id):
            raise ValueError("累计成交需要同一委托的关联编号")
        if self.status in {"partial", "canceled"} and self.filled_quantity and not (self.order_id or self.trade_id):
            raise ValueError("请提供委托关联编号或独立成交编号")
        if self.filled_quantity:
            if self.price is None or not self.amount:
                raise ValueError("请核对成交价和成交额")
            # An order summary can show a rounded average instead of each fill price.
            tolerance = Decimal("0.01") if not self.cumulative else Decimal("0.005") * self.filled_quantity
            if abs(self.price * self.filled_quantity - self.amount) > tolerance:
                raise ValueError("请核对成交额、价格和实际成交股数")
        elif any((self.amount, self.commission, self.other_fees)):
            raise ValueError("未成交委托的成交额和成交费用应为零")
        return self


class Opening(LedgerInput):
    date: LedgerDate
    positions: Annotated[dict[Security, Shares], Field(max_length=200)] = Field(default_factory=dict)


class SessionEvidence(LedgerInput):
    date: LedgerDate
    actual_date: LedgerDate
    previous_date: LedgerDate | None = None
    is_session: bool
    source: Reference

    @model_validator(mode="after")
    def check_dates(self) -> SessionEvidence:
        if not validate_actual_session_date(self.date, self.actual_date).valid:
            raise ValueError("会话日期与实际日期不一致")
        if self.is_session and (self.date.weekday() >= 5 or self.previous_date is not None and self.previous_date >= self.date):
            raise ValueError("交易日或上一交易日无效")
        if not self.is_session and self.previous_date is not None:
            raise ValueError("休市日无需提供上一交易日")
        return self


class ValuationEvidence(LedgerInput):
    date: LedgerDate
    actual_date: LedgerDate
    security: Security
    close: Price | None = None
    price_kind: Literal["original-close", "suspended-valuation"] | None = None
    actions_confirmed: bool = False
    share_delta: Annotated[int, Field(ge=-1_000_000_000, le=1_000_000_000)] = 0
    cash_adjustment: Annotated[Decimal, Field(max_digits=15, decimal_places=2)] = Decimal(0)
    source: Reference
    price_source: Reference | None = None
    action_source: Reference | None = None

    @model_validator(mode="after")
    def check_evidence(self) -> ValuationEvidence:
        if not validate_actual_session_date(self.date, self.actual_date).valid:
            raise ValueError("估值日期与实际日期不一致")
        if (self.close is None) != (self.price_kind is None):
            raise ValueError("收盘价与估值口径须同时提供")
        if not self.actions_confirmed and (self.share_delta or self.cash_adjustment or self.close is None):
            raise ValueError("请提供可验证的收盘或公司行动证据")
        return self


class EvidenceBatch(LedgerInput):
    sessions: Annotated[list[SessionEvidence], Field(max_length=366)] = Field(default_factory=list)
    valuations: Annotated[list[ValuationEvidence], Field(max_length=1000)] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_batch(self) -> EvidenceBatch:
        days = {row.date for row in self.sessions}
        securities = {(row.date, row.security) for row in self.valuations}
        if not (days or securities) or len(days) != len(self.sessions) or len(securities) != len(self.valuations):
            raise ValueError("证据批次须包含数据且每个日期和证券只出现一次")
        return self
