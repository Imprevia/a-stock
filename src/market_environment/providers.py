"""Market data providers with a mootdx-first, HTTP fallback strategy."""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Any

import requests

from src.trading_system.data.providers import EastmoneyClient

from .calculations import Bar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
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

# Baidu and mootdx can interpret these six-digit Shanghai index codes as stocks
# when no independent quote is available. Require a quote cross-check before
# accepting either provider for those symbols.
PRICE_GUARDED_CODES = frozenset({"sh000001", "sh000905"})


@dataclass
class ProviderResult:
    bars: list[Bar]
    source: str
    warning: str | None = None
    is_stale: bool = False


class MarketDataProvider:
    _STOCK_SNAPSHOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    _BREADTH_FALLBACK_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
    _STOCK_UNIVERSE_FILTER = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
    _BREADTH_PAGE_SIZE = 100
    _ACTIVE_DIRECTION_PAGE_SIZE = 100
    _ACTIVE_DIRECTION_MIN_ROWS = 30

    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self.eastmoney = EastmoneyClient(timeout=timeout, session=self.session)

    def fetch(
        self,
        spec: IndexSpec,
        limit: int = 160,
        expected_price: float | None = None,
        quote: dict[str, Any] | None = None,
    ) -> ProviderResult:
        errors: list[str] = []
        try:
            bars = self._fetch_mootdx(spec, limit)
            if len(bars) >= 60 and self._is_accepted(spec, bars, expected_price):
                return ProviderResult(bars=bars, source="mootdx")
            errors.append("mootdx 返回历史数据不足或与实时指数价格不匹配")
        except Exception as exc:  # provider boundary: fallback must remain available
            logger.warning("mootdx failed for %s: %s", spec.code, exc)
            errors.append(f"mootdx: {exc}")

        try:
            bars = self._fetch_baidu_kline(spec, limit)
            if len(bars) >= 60 and self._is_accepted(spec, bars, expected_price):
                return ProviderResult(
                    bars=bars,
                    source="baidu-kline",
                    warning="通达信不可用，已降级到百度历史 K 线",
                )
            errors.append("百度历史 K 线数据不足")
        except Exception as exc:
            logger.warning("Baidu kline failed for %s: %s", spec.code, exc)
            errors.append(f"百度 K 线: {exc}")

        try:
            bars = self._fetch_sina_kline(spec, limit, quote or {})
            if len(bars) >= 60 and self._price_matches(bars, expected_price):
                return ProviderResult(
                    bars=bars,
                    source="sina-kline",
                    warning="通达信和百度不可用，已降级到新浪指数 K 线；成交额按腾讯实时成交额校准估算",
                )
            errors.append("新浪指数 K 线数据不足")
        except Exception as exc:
            logger.warning("Sina kline failed for %s: %s", spec.code, exc)
            errors.append(f"新浪 K 线: {exc}")

        try:
            bars = self._fetch_eastmoney_kline(spec, limit)
            if len(bars) >= 60 and self._price_matches(bars, expected_price):
                return ProviderResult(
                    bars=bars,
                    source="eastmoney-kline",
                    warning="通达信和百度不可用，已降级到东方财富历史 K 线",
                )
            errors.append("东方财富历史 K 线数据不足")
        except Exception as exc:
            logger.warning("Eastmoney kline failed for %s: %s", spec.code, exc)
            errors.append(f"东方财富 K 线: {exc}")

        try:
            bars = self._fetch_tencent_kline(spec, limit)
            if len(bars) >= 60 and self._price_matches(bars, expected_price):
                return ProviderResult(
                    bars=bars,
                    source="tencent-kline",
                    warning="通达信和百度不可用，已降级到腾讯历史 K 线；历史成交额可能不可用",
                )
            errors.append("腾讯历史 K 线数据不足")
        except Exception as exc:
            logger.warning("Tencent kline failed for %s: %s", spec.code, exc)
            errors.append(f"腾讯 K 线: {exc}")

        raise RuntimeError("；".join(errors))

    def fetch_quotes(self, specs: tuple[IndexSpec, ...]) -> dict[str, dict[str, Any]]:
        query = ",".join(spec.code for spec in specs)
        url = f"https://qt.gtimg.cn/q={query}"
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        text = response.content.decode("gbk", errors="replace")
        result: dict[str, dict[str, Any]] = {}
        for line in text.split(";"):
            if "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            values = line.split('"')[1].split("~")
            if len(values) < 50:
                continue
            code = key.lower()
            price = self._number(values, 3)
            last_close = self._number(values, 4)
            amount_wan = self._number(values, 37)
            result[code] = {
                "name": values[1],
                "price": price,
                "last_close": last_close,
                "change_pct": self._number(values, 32),
                "amount": amount_wan * 10000,
                "volume": self._number(values, 36),
                "is_stale": bool(amount_wan == 0 and price == last_close and price > 0),
            }
        return result

    def fetch_chapter01(self, as_of: date, *, allow_current_snapshot: bool) -> dict[str, Any]:
        """Fetch additive Chapter 01 evidence without time-shifting snapshots.

        Eastmoney's stock and industry ranking endpoints expose only the latest
        market snapshot, so they are deliberately skipped for historical
        requests. The limit pools accept a trading date and remain available.
        """
        return {
            "breadth": self.fetch_chapter01_breadth(as_of, allow_current_snapshot=allow_current_snapshot),
            "activeDirection": self.fetch_chapter01_active_direction(
                as_of,
                allow_current_snapshot=allow_current_snapshot,
            ),
            "limits": self.fetch_chapter01_limits(as_of),
            "sectors": self.fetch_chapter01_sectors(as_of, allow_current_snapshot=allow_current_snapshot),
        }

    def fetch_chapter01_stock(self, as_of: date, *, allow_current_snapshot: bool) -> dict[str, Any]:
        """Compatibility wrapper for callers that still request both stock datasets."""
        return {
            "breadth": self.fetch_chapter01_breadth(as_of, allow_current_snapshot=allow_current_snapshot),
            "activeDirection": self.fetch_chapter01_active_direction(
                as_of,
                allow_current_snapshot=allow_current_snapshot,
            ),
        }

    def fetch_chapter01_breadth(self, as_of: date, *, allow_current_snapshot: bool) -> dict[str, Any]:
        if not allow_current_snapshot:
            return self._missing_breadth(as_of, "该数据源仅提供最新市场快照，历史日期不使用当前数据回填")
        try:
            return self._fetch_eastmoney_breadth_fallback(
                as_of,
                "市场广度直接使用涨跌幅排序分页统计，未请求名义全 A 主快照",
            )
        except Exception as exc:
            return self._missing_breadth(as_of, f"东方财富市场广度不可用：{exc}", status="failed")

    def fetch_chapter01_active_direction(
        self,
        as_of: date,
        *,
        allow_current_snapshot: bool,
    ) -> dict[str, Any]:
        if not allow_current_snapshot:
            return self._missing_active_direction(
                as_of,
                "该数据源仅提供最新市场快照，历史日期不使用当前数据回填",
            )
        try:
            return self._build_active_direction(self._fetch_eastmoney_active_direction_rows(), as_of)
        except Exception as exc:
            return self._missing_active_direction(as_of, f"东方财富容量方向不可用：{exc}", status="failed")

    def fetch_chapter01_limits(self, as_of: date) -> dict[str, Any]:
        return self._fetch_limit_evidence(as_of)

    def fetch_chapter01_sectors(self, as_of: date, *, allow_current_snapshot: bool) -> dict[str, Any]:
        if not allow_current_snapshot:
            warning = "该数据源仅提供最新市场快照，历史日期不使用当前数据回填"
            return self._missing_sectors(as_of, warning)
        try:
            return self._build_sectors(self._fetch_eastmoney_industries(), as_of)
        except Exception as exc:
            return self._missing_sectors(as_of, f"东方财富行业排名不可用：{exc}", status="failed")

    def _fetch_eastmoney_stock_snapshot(self) -> list[dict[str, Any]]:
        params = {
            "pn": "1",
            "pz": "6000",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f6",
            "fs": self._STOCK_UNIVERSE_FILTER,
            "fields": "f2,f3,f6,f12,f13,f14,f15,f16,f100",
        }
        payload = self.eastmoney.get_json(self._STOCK_SNAPSHOT_URL, params)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("全 A 快照响应缺少 data")
        rows = data.get("diff")
        if isinstance(rows, Mapping):
            rows = list(rows.values())
        if not isinstance(rows, list):
            raise RuntimeError("全 A 快照返回格式无效")
        rows = [row for row in rows if isinstance(row, dict)]
        if not rows:
            raise RuntimeError("全 A 快照未返回有效股票")
        total = self._optional_int(data.get("total"))
        if total is not None and len(rows) < total:
            raise RuntimeError(f"全 A 快照仅返回 {len(rows)} / {total} 行，拒绝按不完整样本计算")
        return rows

    def _fetch_eastmoney_active_direction_rows(self) -> list[dict[str, Any]]:
        params = {
            "pn": "1",
            "pz": str(self._ACTIVE_DIRECTION_PAGE_SIZE),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f6",
            "fs": self._STOCK_UNIVERSE_FILTER,
            "fields": "f2,f3,f6,f12,f13,f14,f15,f16,f100",
        }
        payload = self.eastmoney.get_json(self._STOCK_SNAPSHOT_URL, params)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("容量方向响应缺少 data")
        rows = data.get("diff")
        if isinstance(rows, Mapping):
            rows = list(rows.values())
        if not isinstance(rows, list):
            raise RuntimeError("容量方向返回格式无效")
        valid_rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and self._optional_text(row.get("f12")) is not None
            and self._optional_text(row.get("f14")) is not None
            and self._optional_float(row.get("f6")) is not None
        ]
        if len(valid_rows) < self._ACTIVE_DIRECTION_MIN_ROWS:
            raise RuntimeError(
                f"容量方向仅返回 {len(valid_rows)} 个有效样本，至少需要 {self._ACTIVE_DIRECTION_MIN_ROWS} 个"
            )
        amounts = [self._optional_float(row.get("f6")) or 0.0 for row in valid_rows]
        if any(left < right for left, right in zip(amounts, amounts[1:])):
            raise RuntimeError("容量方向响应未按成交额降序排列")
        return valid_rows

    def _fetch_eastmoney_breadth_fallback(self, as_of: date, primary_warning: str) -> dict[str, Any]:
        """Derive exact breadth statistics from a capped, sorted fallback endpoint.

        The delay host caps each response at 100 rows. Binary-searching the
        positive and negative boundaries avoids downloading the whole market
        while preserving exact counts and the median over valid returns.
        """
        page_size = self._BREADTH_PAGE_SIZE
        page_cache: dict[int, tuple[list[float | None], int]] = {}

        def fetch_page(page_number: int) -> tuple[list[float | None], int]:
            cached = page_cache.get(page_number)
            if cached is not None:
                return cached
            params = {
                "pn": str(page_number),
                "pz": str(page_size),
                "po": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fid": "f3",
                "fs": self._STOCK_UNIVERSE_FILTER,
                "fields": "f3",
            }
            payload = self.eastmoney.get_json(self._BREADTH_FALLBACK_URL, params)
            data = payload.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("延迟行情响应缺少 data")
            rows = data.get("diff")
            if isinstance(rows, Mapping):
                rows = list(rows.values())
            if not isinstance(rows, list):
                raise RuntimeError("延迟行情返回格式无效")
            total = self._optional_int(data.get("total"))
            if total is None or total <= 0:
                raise RuntimeError("延迟行情缺少有效总样本数")
            values = [self._optional_float(row.get("f3")) for row in rows if isinstance(row, dict)]
            if not values:
                raise RuntimeError(f"延迟行情第 {page_number} 页没有有效行")
            result = (values, total)
            page_cache[page_number] = result
            return result

        _, total = fetch_page(1)
        page_count = math.ceil(total / page_size)

        def last_page_with_positive() -> int | None:
            low, high, result = 1, page_count, None
            while low <= high:
                middle_page = (low + high) // 2
                values, observed_total = fetch_page(middle_page)
                if observed_total != total:
                    raise RuntimeError("延迟行情分页期间总样本数发生变化")
                if any(value is not None and value > 0 for value in values):
                    result = middle_page
                    low = middle_page + 1
                else:
                    high = middle_page - 1
            return result

        def first_page_with_negative() -> int | None:
            low, high, result = 1, page_count, None
            while low <= high:
                middle_page = (low + high) // 2
                values, observed_total = fetch_page(middle_page)
                if observed_total != total:
                    raise RuntimeError("延迟行情分页期间总样本数发生变化")
                if any(value is not None and value < 0 for value in values):
                    result = middle_page
                    high = middle_page - 1
                else:
                    low = middle_page + 1
            return result

        positive_page = last_page_with_positive()
        negative_page = first_page_with_negative()
        if positive_page is None or negative_page is None or positive_page > negative_page:
            raise RuntimeError("延迟行情无法定位涨跌分界")

        positive_values, _ = fetch_page(positive_page)
        advance_count = (positive_page - 1) * page_size + sum(
            value is not None and value > 0 for value in positive_values
        )
        negative_values, _ = fetch_page(negative_page)
        first_negative_offset = next(
            (index for index, value in enumerate(negative_values) if value is not None and value < 0),
            None,
        )
        if first_negative_offset is None:
            raise RuntimeError("延迟行情跌幅边界页缺少负值")
        negative_start = (negative_page - 1) * page_size + first_negative_offset
        decline_count = total - negative_start

        boundary_values: list[float | None] = []
        for page_number in range(positive_page, negative_page + 1):
            values, _ = fetch_page(page_number)
            boundary_values.extend(values)
        flat_count = sum(value == 0 for value in boundary_values if value is not None)
        invalid_count = sum(value is None for value in boundary_values)
        valid_count = advance_count + flat_count + decline_count
        if valid_count + invalid_count != total:
            raise RuntimeError("延迟行情排序边界不连续，无法保证统计口径")

        def value_at_valid_rank(rank: int) -> float:
            if rank < advance_count:
                raw_index = rank
            elif rank < advance_count + flat_count:
                return 0.0
            else:
                raw_index = negative_start + rank - advance_count - flat_count
            values, _ = fetch_page(raw_index // page_size + 1)
            value = values[raw_index % page_size]
            if value is None:
                raise RuntimeError("延迟行情中位数位置缺少有效涨跌幅")
            return value

        lower_rank = (valid_count - 1) // 2
        upper_rank = valid_count // 2
        middle = (value_at_valid_rank(lower_rank) + value_at_valid_rank(upper_rank)) / 2
        return self._breadth_result(
            advance_count,
            decline_count,
            flat_count,
            middle,
            as_of,
            source="eastmoney-clist-delay",
            status="fallback",
            warnings=[primary_warning, "已按涨跌幅排序分页定位全 A 有效样本"],
        )

    def _fetch_eastmoney_industries(self) -> list[dict[str, Any]]:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:90+t:2",
            "fields": "f3,f6,f12,f14,f62,f104,f105,f140,f184",
        }
        payload = self.eastmoney.get_json(url, params)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("行业排名响应缺少 data")
        rows = data.get("diff")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("行业排名未返回有效板块")
        return rows

    def _fetch_limit_pool(self, endpoint: str, sort: str, as_of: date) -> list[dict[str, Any]]:
        url = f"https://push2ex.eastmoney.com/{endpoint}"
        params = {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt",
            "Pageindex": "0",
            "pagesize": "10000",
            "sort": sort,
            "date": as_of.strftime("%Y%m%d"),
        }
        payload = self.eastmoney.get_json(url, params)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("响应没有该交易日的数据")
        rows = data.get("pool")
        if not isinstance(rows, list):
            raise RuntimeError("响应缺少 pool")
        return rows

    def _fetch_limit_evidence(self, as_of: date) -> dict[str, Any]:
        definitions = {
            "limit_up": ("getTopicZTPool", "fbt:asc"),
            "failed_limit_up": ("getTopicZBPool", "fbt:asc"),
            "limit_down": ("getTopicDTPool", "fund:asc"),
        }
        pools: dict[str, list[dict[str, Any]] | None] = {}
        warnings: list[str] = []
        for key, (endpoint, sort) in definitions.items():
            try:
                pools[key] = self._fetch_limit_pool(endpoint, sort, as_of)
            except Exception as exc:
                pools[key] = None
                warnings.append(f"{key}: {exc}")

        limit_up_count = len(pools["limit_up"]) if pools["limit_up"] is not None else None
        failed_count = len(pools["failed_limit_up"]) if pools["failed_limit_up"] is not None else None
        limit_down_count = len(pools["limit_down"]) if pools["limit_down"] is not None else None
        failed_ratio = None
        if limit_up_count is not None and failed_count is not None and limit_up_count + failed_count > 0:
            failed_ratio = failed_count / (limit_up_count + failed_count)
        streaks = [
            value
            for item in pools["limit_up"] or []
            if (value := self._optional_int(item.get("lbc"))) is not None
        ]
        max_streak = max(streaks) if streaks else None
        observed = sum(len(rows) for rows in pools.values() if rows is not None)
        if len(warnings) == len(definitions):
            status, state = "failed", "insufficient"
        elif warnings:
            status, state = "partial", "partial"
        elif limit_up_count == failed_count == limit_down_count == 0:
            status, state = "ok", "无触板样本"
        else:
            status, state = "ok", "已观测"
        return {
            "limitUpCount": limit_up_count,
            "limitDownCount": limit_down_count,
            "failedLimitUpCount": failed_count,
            "failedLimitUpRatio": round(failed_ratio, 4) if failed_ratio is not None else None,
            "maxStreak": max_streak,
            "state": state,
            "quality": self._quality("limit-pools", "eastmoney-push2ex", status, observed, as_of, warnings),
        }

    def _build_breadth(self, rows: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
        returns = [value for row in rows if (value := self._optional_float(row.get("f3"))) is not None]
        if not returns:
            return self._missing_breadth(as_of, "全 A 快照缺少有效涨跌幅", status="failed")
        advance_count = sum(value > 0 for value in returns)
        decline_count = sum(value < 0 for value in returns)
        flat_count = len(returns) - advance_count - decline_count
        middle = median(returns)
        return self._breadth_result(
            advance_count,
            decline_count,
            flat_count,
            middle,
            as_of,
            source="eastmoney-clist",
            status="partial",
            warnings=["当前快照按可返回涨跌幅的股票计数，板块/ST/上市时长分层尚未接入"],
        )

    def _breadth_result(
        self,
        advance_count: int,
        decline_count: int,
        flat_count: int,
        middle: float,
        as_of: date,
        *,
        source: str,
        status: str,
        warnings: list[str],
    ) -> dict[str, Any]:
        valid_count = advance_count + decline_count + flat_count
        if valid_count <= 0:
            return self._missing_breadth(as_of, "全 A 快照缺少有效涨跌幅", status="failed")
        advance_ratio = advance_count / valid_count
        if advance_ratio > 0.5 and middle > 0:
            state = "多数上涨"
        elif advance_ratio < 0.5 and middle < 0:
            state = "多数下跌"
        else:
            state = "涨跌分化"
        return {
            "advanceCount": advance_count,
            "declineCount": decline_count,
            "flatCount": flat_count,
            "validCount": valid_count,
            "advanceRatio": round(advance_ratio, 4),
            "medianReturn": round(float(middle), 4),
            "state": state,
            "quality": self._quality("market-breadth", source, status, valid_count, as_of, warnings),
        }

    def _build_sectors(self, rows: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
        result = []
        for rank, item in enumerate(rows[:10], start=1):
            result.append(
                {
                    "rank": rank,
                    "code": self._optional_text(item.get("f12")),
                    "name": self._optional_text(item.get("f14")),
                    "changePct": self._optional_float(item.get("f3")),
                    "amount": self._optional_float(item.get("f6")),
                    "mainNet": self._optional_float(item.get("f62")),
                    "mainNetPct": self._optional_float(item.get("f184")),
                    "upCount": self._optional_int(item.get("f104")),
                    "downCount": self._optional_int(item.get("f105")),
                    "leader": self._optional_text(item.get("f140")),
                }
            )
        warnings = ["仅反映当日行业排名和资金流，5日持续性、板块宽度与分歧承接尚未接入"]
        return {
            "rows": result,
            "state": "当日排名已观测",
            "quality": self._quality("industry-ranking", "eastmoney-clist", "partial", len(rows), as_of, warnings),
        }

    def _build_active_direction(self, rows: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
        ranked = sorted(
            (row for row in rows if self._optional_float(row.get("f6")) is not None),
            key=lambda row: self._optional_float(row.get("f6")) or 0,
            reverse=True,
        )
        top30 = ranked[:30]
        industries = Counter(
            industry for row in top30 if (industry := self._optional_text(row.get("f100"))) is not None
        )
        cluster_name, cluster_count = industries.most_common(1)[0] if industries else (None, 0)
        if cluster_name and cluster_count >= 3:
            state = "candidate"
            summary = f"成交额前30中 {cluster_name} 有 {cluster_count} 只，形成方向聚集线索，尚未完成连续性确认"
        else:
            state = "unverified"
            summary = "成交额前30未形成至少3只同一行业的聚集线索"
        stocks = []
        for row in top30[:10]:
            close = self._optional_float(row.get("f2"))
            high = self._optional_float(row.get("f15"))
            low = self._optional_float(row.get("f16"))
            close_position = None
            if close is not None and high is not None and low is not None and high > low:
                close_position = max(0.0, min(1.0, (close - low) / (high - low)))
            stocks.append(
                {
                    "code": self._optional_text(row.get("f12")),
                    "name": self._optional_text(row.get("f14")),
                    "industry": self._optional_text(row.get("f100")),
                    "changePct": self._optional_float(row.get("f3")),
                    "amount": self._optional_float(row.get("f6")),
                    "closePosition": round(close_position, 4) if close_position is not None else None,
                }
            )
        warnings = ["仅有当日成交额、涨跌幅和收盘位置；20日成交放大、超额收益与连续2日确认尚未接入"]
        return {
            "state": state,
            "summary": summary,
            "topStocks": stocks,
            "quality": self._quality("active-direction", "eastmoney-clist", "partial", len(top30), as_of, warnings),
        }

    @classmethod
    def _missing_breadth(cls, cls_as_of: date, warning: str, status: str = "missing") -> dict[str, Any]:
        return {
            "advanceCount": None,
            "declineCount": None,
            "flatCount": None,
            "validCount": None,
            "advanceRatio": None,
            "medianReturn": None,
            "state": "insufficient",
            "quality": cls._quality("market-breadth", "eastmoney-clist", status, 0, cls_as_of, [warning]),
        }

    @classmethod
    def _missing_sectors(cls, cls_as_of: date, warning: str, status: str = "missing") -> dict[str, Any]:
        return {
            "rows": [],
            "state": "insufficient",
            "quality": cls._quality("industry-ranking", "eastmoney-clist", status, 0, cls_as_of, [warning]),
        }

    @classmethod
    def _missing_active_direction(cls, cls_as_of: date, warning: str, status: str = "missing") -> dict[str, Any]:
        return {
            "state": "insufficient",
            "summary": None,
            "topStocks": [],
            "quality": cls._quality("active-direction", "eastmoney-clist", status, 0, cls_as_of, [warning]),
        }

    @staticmethod
    def _quality(
        dataset: str,
        provider: str,
        status: str,
        observations: int,
        as_of: date,
        warnings: list[str],
    ) -> dict[str, Any]:
        return {
            "dataset": dataset,
            "source": provider,
            "provider": provider,
            "status": status,
            "observations": observations,
            "asOf": as_of.isoformat(),
            "warning": "；".join(warnings) if warnings else None,
            "warnings": warnings,
        }

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value in (None, "", "-"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _optional_int(cls, value: Any) -> int | None:
        number = cls._optional_float(value)
        return int(number) if number is not None else None

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        text = str(value or "").strip()
        return text if text and text != "-" else None

    def _fetch_mootdx(self, spec: IndexSpec, limit: int) -> list[Bar]:
        from mootdx.quotes import Quotes

        client = Quotes.factory(market="std", multithread=False)
        market = 1 if spec.code.startswith("sh") else 0
        frame = client.bars(symbol=spec.digits, frequency=9, offset=limit, market=market)
        if frame is None or len(frame) == 0:
            return []
        rows: list[Bar] = []
        for item in frame.to_dict("records"):
            raw_date = item.get("datetime") or item.get("date")
            parsed_date = self._parse_date(raw_date)
            if parsed_date is None:
                continue
            rows.append(
                Bar(
                    date=parsed_date,
                    open=float(item.get("open", 0) or 0),
                    close=float(item.get("close", 0) or 0),
                    high=float(item.get("high", 0) or 0),
                    low=float(item.get("low", 0) or 0),
                    amount=float(item.get("amount", 0) or 0),
                )
            )
        return sorted((bar for bar in rows if bar.close > 0), key=lambda bar: bar.date)

    def _fetch_baidu_kline(self, spec: IndexSpec, limit: int) -> list[Bar]:
        url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
        params = {
            "all": "1",
            "isIndex": "true",
            "isBk": "false",
            "isBlock": "false",
            "isFutures": "false",
            "isStock": "false",
            "newFormat": "1",
            "group": "quotation_kline_ab",
            "finClientType": "pc",
            "code": spec.digits,
            "market": "sh" if spec.code.startswith("sh") else "sz",
            "ktype": "1",
        }
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        market_data = payload.get("Result", {}).get("newMarketData", {})
        keys = market_data.get("keys", [])
        rows = market_data.get("marketData", "").split(";")
        positions = {key: index for index, key in enumerate(keys)}
        result: list[Bar] = []
        for row in rows:
            values = row.split(",")
            if len(values) < len(keys):
                continue
            parsed_date = self._parse_date(values[positions.get("time", 1)])
            if parsed_date is None:
                continue
            result.append(
                Bar(
                    date=parsed_date,
                    open=float(values[positions["open"]]),
                    close=float(values[positions["close"]]),
                    high=float(values[positions["high"]]),
                    low=float(values[positions["low"]]),
                    amount=float(values[positions["amount"]]),
                )
            )
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)[-160:]

    def _fetch_eastmoney_kline(self, spec: IndexSpec, limit: int) -> list[Bar]:
        """Fetch index K-lines with an explicit Eastmoney market secid.

        Unlike the six-digit Baidu/mootdx routes, ``1.000001`` and
        ``1.000905`` are unambiguous Shanghai index identifiers and include
        historical turnover amounts needed for volume-price analysis.
        """
        market = "1" if spec.code.startswith("sh") else "0"
        secid = f"{market}.{spec.digits}"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "klt": "101",
            "fqt": "1",
            "beg": "19900101",
            "end": (date.today() + timedelta(days=1)).strftime("%Y%m%d"),
            "lmt": str(max(limit, 160)),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
        payload = self.eastmoney.get_json(url, params)
        if payload.get("rc") not in (0, None):
            raise RuntimeError(f"返回错误码 {payload.get('rc')}")
        rows = payload.get("data", {}).get("klines", [])
        result: list[Bar] = []
        for row in rows:
            values = str(row).split(",")
            if len(values) < 7:
                continue
            parsed_date = self._parse_date(values[0])
            if parsed_date is None:
                continue
            try:
                result.append(
                    Bar(
                        date=parsed_date,
                        open=float(values[1]),
                        close=float(values[2]),
                        high=float(values[3]),
                        low=float(values[4]),
                        amount=float(values[6]),
                    )
                )
            except (TypeError, ValueError):
                continue
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)[-160:]

    def _fetch_sina_kline(self, spec: IndexSpec, limit: int, quote: dict[str, Any]) -> list[Bar]:
        """Fetch index history from Sina and calibrate turnover units.

        Sina exposes index volume in a different unit from currency. The latest
        Tencent real-time amount and same-day Sina volume provide a scale factor,
        so historical amounts remain comparable without presenting raw volume
        as currency.
        """
        url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{spec.code}_klines=/CN_MarketData.getKLineData"
        params = {"symbol": spec.code, "scale": "240", "ma": "no", "datalen": str(max(limit, 160))}
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        text = response.text
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            raise RuntimeError("新浪响应不含 K 线数组")
        rows = json.loads(text[start : end + 1])
        if not rows:
            return []
        latest_volume = float(rows[-1].get("volume") or 0)
        quote_amount = float(quote.get("amount") or 0)
        if latest_volume <= 0 or quote_amount <= 0:
            raise RuntimeError("缺少腾讯实时成交额或新浪最新成交量，无法校准新浪成交量")
        scale = quote_amount / latest_volume
        result: list[Bar] = []
        for row in rows:
            parsed_date = self._parse_date(row.get("day"))
            if parsed_date is None:
                continue
            try:
                volume = float(row.get("volume") or 0)
                result.append(
                    Bar(
                        date=parsed_date,
                        open=float(row["open"]),
                        close=float(row["close"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        amount=volume * scale,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)[-160:]

    def _fetch_tencent_kline(self, spec: IndexSpec, limit: int) -> list[Bar]:
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={spec.code},day,,,{limit},qfq"
        )
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {}).get(spec.code, {})
        rows = data.get("qfqday") or data.get("day") or []
        result: list[Bar] = []
        for row in rows:
            if len(row) < 6:
                continue
            parsed_date = self._parse_date(row[0])
            if parsed_date is None:
                continue
            result.append(
                Bar(
                    date=parsed_date,
                    open=float(row[1]),
                    close=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    # Tencent's public day endpoint exposes volume but not amount.
                    amount=float(row[6]) if len(row) > 6 and row[6] not in (None, "") else 0,
                )
            )
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)

    @staticmethod
    def _number(values: list[str], index: int) -> float:
        try:
            return float(values[index]) if values[index] else 0.0
        except (ValueError, IndexError):
            return 0.0

    @staticmethod
    def _price_matches(bars: list[Bar], expected_price: float | None) -> bool:
        if expected_price in (None, 0) or not bars:
            return True
        return abs(bars[-1].close - expected_price) / expected_price <= 0.2

    @classmethod
    def _is_accepted(cls, spec: IndexSpec, bars: list[Bar], expected_price: float | None) -> bool:
        if spec.code in PRICE_GUARDED_CODES and expected_price in (None, 0):
            return False
        return cls._price_matches(bars, expected_price)

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        text = str(value or "")[:10]
        try:
            return date.fromisoformat(text.replace("/", "-"))
        except ValueError:
            return None
