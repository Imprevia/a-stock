"""Stable core-index identities shared by runtime and acquisition plans."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndexSpec:
    code: str
    digits: str
    name: str
    representative: str


INDEX_SPECS = (
    IndexSpec("sh000001", "000001", "上证指数", "沪市大盘股、金融和周期权重"),
    IndexSpec("sz399001", "399001", "深证成指", "深市成长、制造和消费"),
    IndexSpec("sz399006", "399006", "创业板指", "高弹性成长股风险偏好"),
    IndexSpec("sh000300", "000300", "沪深300", "两市核心大盘蓝筹"),
    IndexSpec("sh000905", "000905", "中证500", "中盘股和题材扩散"),
)

# Baidu and mootdx can interpret these Shanghai index codes as stocks when no
# independent quote is available, so both paths require quote evidence.
PRICE_GUARDED_CODES = frozenset({"sh000001", "sh000905"})


__all__ = ["INDEX_SPECS", "PRICE_GUARDED_CODES", "IndexSpec"]
