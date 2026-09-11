"""Market data providers with a mootdx-first, HTTP fallback strategy."""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
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


@dataclass(frozen=True)
class LimitProviderDatasetResult:
    payload: dict[str, Any]
    normalization: Any
    pool_evidence: dict[str, dict[str, Any]] | None = None


class LimitPoolRows(list):
    """List-compatible pool rows carrying the provider's group date evidence."""

    def __init__(
        self,
        rows: list[Any],
        *,
        actual_as_of: date | None,
        date_warning: str | None = None,
    ) -> None:
        super().__init__(rows)
        self.actual_as_of = actual_as_of
        self.date_warning = date_warning


class MarketDataProvider:
    _STOCK_SNAPSHOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    _BREADTH_FALLBACK_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
    _STOCK_UNIVERSE_FILTER = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
    _BREADTH_PAGE_SIZE = 100
    _ACTIVE_DIRECTION_FALLBACK_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
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
        limit: int = 280,
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
            rows, source, status, warnings = self._fetch_eastmoney_active_direction()
            return self._build_active_direction(
                rows,
                as_of,
                source=source,
                status=status,
                warnings=warnings,
            )
        except Exception as exc:
            return self._missing_active_direction(as_of, f"东方财富容量方向不可用：{exc}", status="failed")

    def fetch_chapter01_limits(self, as_of: date) -> dict[str, Any]:
        return self.fetch_chapter01_limit_dataset(as_of).payload

    def fetch_chapter01_limit_dataset(self, as_of: date) -> LimitProviderDatasetResult:
        """Return the aggregate and normalized rows from one provider call chain."""

        return self._fetch_chapter01_limit_dataset(as_of, strict=False)

    def fetch_chapter01_limit_dataset_strict(
        self,
        as_of: date,
        *,
        on_pool: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> LimitProviderDatasetResult:
        """Fetch one exact session and stop before another wire call on any pool failure."""

        return self._fetch_chapter01_limit_dataset(as_of, strict=True, on_pool=on_pool)

    def _fetch_chapter01_limit_dataset(
        self,
        as_of: date,
        *,
        strict: bool,
        on_pool: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> LimitProviderDatasetResult:

        definitions = {
            "limit_up": ("getTopicZTPool", "fbt:asc"),
            "failed_limit_up": ("getTopicZBPool", "fbt:asc"),
            "limit_down": ("getTopicDTPool", "fund:asc"),
        }
        pools: dict[str, list[Any] | None] = {}
        pool_evidence: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        for key, (endpoint, sort) in definitions.items():
            try:
                rows = self._fetch_limit_pool(endpoint, sort, as_of)
                evidence = {
                    "source": "eastmoney-push2ex",
                    "status": "ok",
                    "actualAsOf": rows.actual_as_of.isoformat() if rows.actual_as_of else None,
                    "rawCount": len(rows),
                    "warnings": [rows.date_warning] if rows.date_warning else [],
                }
                if strict and (rows.date_warning is not None or rows.actual_as_of != as_of):
                    evidence["status"] = "failed"
                    pool_evidence[key] = evidence
                    if on_pool is not None:
                        on_pool(key, dict(evidence))
                    detail = rows.date_warning or (
                        "limits provider date mismatch: "
                        f"requested {as_of.isoformat()}, "
                        f"actual {rows.actual_as_of.isoformat() if rows.actual_as_of else 'missing'}"
                    )
                    raise RuntimeError(detail)
                pools[key] = rows
                pool_evidence[key] = evidence
                if on_pool is not None:
                    on_pool(key, dict(evidence))
            except Exception as exc:
                if key not in pool_evidence:
                    evidence = {
                        "source": "eastmoney-push2ex",
                        "status": "failed",
                        "actualAsOf": None,
                        "rawCount": None,
                        "warnings": [str(exc)],
                    }
                    pool_evidence[key] = evidence
                    if on_pool is not None:
                        on_pool(key, dict(evidence))
                if strict:
                    raise RuntimeError(f"{key} pool failed: {exc}") from exc
                pools[key] = None
                warnings.append(f"{key}: {exc}")
        actual_as_of, date_warnings = self._limit_pool_date_evidence(pools)
        warnings.extend(date_warnings)
        date_validation_warnings = list(date_warnings)
        if actual_as_of is not None and actual_as_of != as_of:
            mismatch_warning = (
                "limits provider date mismatch: "
                f"requested {as_of.isoformat()}, actual {actual_as_of.isoformat()}"
            )
            warnings.append(mismatch_warning)
            date_validation_warnings.append(mismatch_warning)
        payload = self._limit_payload(as_of, pools, warnings)
        normalization = self.normalize_limit_pools(
            pools,
            as_of,
            actual_as_of=actual_as_of,
            source="eastmoney-push2ex",
            source_revision="eastmoney-limit-pools-v1",
            rule_version="limits-promotion-v1",
        )
        if date_validation_warnings:
            normalization = replace(
                normalization,
                warnings=tuple(dict.fromkeys((*normalization.warnings, *date_validation_warnings))),
            ).normalized()
        for pool_name, evidence in pool_evidence.items():
            raw_count = evidence.get("rawCount")
            facts = [row for row in normalization.rows if row.pool_type == pool_name]
            validation_reasons = Counter(
                row.invalid_reason
                for row in facts
                if row.invalid_reason not in {None, "not-v1-pool"}
            )
            v1_reasons = Counter(row.invalid_reason for row in facts if row.invalid_reason is not None)
            collapsed = max(int(raw_count) - len(facts), 0) if raw_count is not None else 0
            if collapsed:
                validation_reasons["duplicate-security-removed"] += collapsed
                v1_reasons["duplicate-security-removed"] += collapsed
            excluded_count = sum(validation_reasons.values())
            evidence.update(
                {
                    "normalizedCount": len(facts),
                    "validCount": int(raw_count) - excluded_count if raw_count is not None else None,
                    "excludedCount": excluded_count,
                    "eligibleCount": sum(row.eligible for row in facts),
                    "excludedByReason": dict(sorted(validation_reasons.items())),
                    "v1ExcludedByReason": dict(sorted(v1_reasons.items())),
                }
            )
        return LimitProviderDatasetResult(
            payload=payload,
            normalization=normalization,
            pool_evidence=pool_evidence,
        )

    @staticmethod
    def normalize_limit_rows(
        rows: list[Any],
        as_of: date,
        pool_type: str,
        *,
        actual_as_of: date | None = None,
        source: str = "eastmoney-push2ex",
        source_revision: str | None = None,
        rule_version: str | None = None,
    ):
        """Normalize provider rows without inferring missing security facts."""

        from .limit_facts import normalize_limit_rows

        return normalize_limit_rows(
            rows,
            as_of=as_of,
            actual_as_of=actual_as_of,
            pool_type=pool_type,
            source=source,
            source_revision=source_revision,
            rule_version=rule_version,
        )

    @staticmethod
    def normalize_limit_pools(
        pools: dict[str, list[Any] | None],
        as_of: date,
        *,
        actual_as_of: date | None = None,
        source: str = "eastmoney-push2ex",
        source_revision: str | None = None,
        rule_version: str | None = None,
    ):
        from .limit_facts import normalize_limit_pools

        return normalize_limit_pools(
            pools,
            as_of=as_of,
            actual_as_of=actual_as_of,
            source=source,
            source_revision=source_revision,
            rule_version=rule_version,
        )

    def fetch_chapter01_sectors(self, as_of: date, *, allow_current_snapshot: bool) -> dict[str, Any]:
        if not allow_current_snapshot:
            warning = "该数据源仅提供最新市场快照，历史日期不使用当前数据回填"
            return self._missing_sectors(as_of, warning)
        try:
            rows, source, status, warnings = self._fetch_eastmoney_industries()
            return self._build_sectors(rows, as_of, source=source, status=status, warnings=warnings)
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

    def _fetch_eastmoney_active_direction(self) -> tuple[list[dict[str, Any]], str, str, list[str]]:
        try:
            rows = self._fetch_eastmoney_active_direction_rows(self._STOCK_SNAPSHOT_URL)
            return rows, "eastmoney-clist", "partial", []
        except Exception as primary_error:
            try:
                rows = self._fetch_eastmoney_active_direction_rows(self._ACTIVE_DIRECTION_FALLBACK_URL)
            except Exception as delayed_error:
                raise RuntimeError(f"主域失败：{primary_error}；延迟域失败：{delayed_error}") from delayed_error
            return (
                rows,
                "eastmoney-clist-delay",
                "fallback",
                [f"东方财富容量方向主域不可用：{primary_error}", "已降级到东方财富延迟容量方向"],
            )

    def _fetch_eastmoney_active_direction_rows(self, url: str) -> list[dict[str, Any]]:
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
        payload = self.eastmoney.get_json(url, params)
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
        all_values: list[float] = []
        for page_number in range(1, page_count + 1):
            values, observed_total = fetch_page(page_number)
            if observed_total != total:
                raise RuntimeError("延迟行情分页期间总样本数发生变化")
            all_values.extend(value for value in values if value is not None and math.isfinite(value))
        if not all_values:
            raise RuntimeError("延迟行情缺少有效涨跌幅")
        advance_count = sum(value > 0 for value in all_values)
        decline_count = sum(value < 0 for value in all_values)
        flat_count = sum(value == 0 for value in all_values)
        valid_count = len(all_values)
        middle = median(all_values)
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

    def _fetch_eastmoney_industries(self) -> tuple[list[dict[str, Any]], str, str, list[str]]:
        primary_url = "https://push2.eastmoney.com/api/qt/clist/get"
        delayed_url = "https://push2delay.eastmoney.com/api/qt/clist/get"
        try:
            rows = self._fetch_eastmoney_industries_from(primary_url)
            return rows, "eastmoney-clist", "partial", []
        except Exception as primary_error:
            try:
                rows = self._fetch_eastmoney_industries_from(delayed_url)
            except Exception as delayed_error:
                raise RuntimeError(f"主域失败：{primary_error}；延迟域失败：{delayed_error}") from delayed_error
            return (
                rows,
                "eastmoney-clist-delay",
                "fallback",
                [f"东方财富行业主域不可用：{primary_error}", "已降级到东方财富延迟行业排名"],
            )

    def _fetch_eastmoney_industries_from(self, url: str) -> list[dict[str, Any]]:
        params = {
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:90+t:2",
            "fields": "f3,f6,f12,f14,f62,f104,f105,f128,f136,f140,f141,f184",
        }
        payload = self.eastmoney.get_json(url, params)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("行业排名响应缺少 data")
        rows = data.get("diff")
        if isinstance(rows, Mapping):
            rows = list(rows.values())
        if not isinstance(rows, list):
            raise RuntimeError("行业排名返回格式无效")
        valid_rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and self._optional_text(row.get("f12")) is not None
            and self._optional_text(row.get("f14")) is not None
            and self._optional_float(row.get("f3")) is not None
        ]
        if not valid_rows:
            raise RuntimeError("行业排名未返回有效板块")
        return valid_rows

    def _fetch_limit_pool(self, endpoint: str, sort: str, as_of: date) -> LimitPoolRows:
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
        raw_date = data.get("date")
        actual_as_of = self._parse_limit_date(raw_date)
        if raw_date in (None, "", "-"):
            date_warning = "provider response missing top-level session date"
        elif actual_as_of is None:
            date_warning = f"provider response has invalid top-level session date: {raw_date!r}"
        else:
            date_warning = None
        return LimitPoolRows(rows, actual_as_of=actual_as_of, date_warning=date_warning)

    def _fetch_limit_evidence(self, as_of: date) -> dict[str, Any]:
        return self.fetch_chapter01_limit_dataset(as_of).payload

    def _limit_payload(
        self,
        as_of: date,
        pools: Mapping[str, list[Any] | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        malformed_by_pool = {
            pool_name: sum(not isinstance(item, Mapping) for item in rows)
            for pool_name, rows in pools.items()
            if rows is not None
        }

        def exact_count(pool_name: str) -> int | None:
            rows = pools[pool_name]
            if rows is None or malformed_by_pool.get(pool_name, 0):
                return None
            return len(rows)

        limit_up_count = exact_count("limit_up")
        failed_count = exact_count("failed_limit_up")
        limit_down_count = exact_count("limit_down")
        failed_ratio = None
        if limit_up_count is not None and failed_count is not None and limit_up_count + failed_count > 0:
            failed_ratio = failed_count / (limit_up_count + failed_count)
        streaks = (
            [
                value
                for item in pools["limit_up"] or []
                if isinstance(item, Mapping) and (value := self._optional_int(item.get("lbc"))) is not None
            ]
            if limit_up_count is not None
            else []
        )
        max_streak = max(streaks) if streaks else None
        observed = sum(
            isinstance(item, Mapping)
            for rows in pools.values()
            if rows is not None
            for item in rows
        )
        malformed_count = sum(malformed_by_pool.values())
        if malformed_count:
            details = ", ".join(
                f"{pool_name}={count}" for pool_name, count in malformed_by_pool.items() if count
            )
            warnings.append(f"malformed-row limit pool entries excluded: {malformed_count} ({details})")
        date_evidence_failed = any(
            "top-level session date" in warning
            or "provider pools disagree on top-level dates" in warning
            or "provider date mismatch" in warning
            or "provider row date" in warning
            for warning in warnings
        )
        usable_pool_count = sum(
            rows is not None and malformed_by_pool.get(pool_name, 0) == 0
            for pool_name, rows in pools.items()
        )
        if date_evidence_failed:
            status, state = "failed", "insufficient"
        elif usable_pool_count == 0:
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

    @staticmethod
    def _parse_limit_date(value: Any) -> date | None:
        if isinstance(value, datetime):
            return None
        if isinstance(value, date):
            return value
        if value in (None, "", "-"):
            return None
        text = str(value).strip().replace("/", "-")
        try:
            if len(text) == 8 and text.isdigit():
                return datetime.strptime(text, "%Y%m%d").date()
            return date.fromisoformat(text)
        except (TypeError, ValueError):
            return None
    @classmethod
    def _limit_pool_date_evidence(
        cls,
        pools: Mapping[str, list[Any] | None],
    ) -> tuple[date | None, list[str]]:
        """Resolve group dates first, then validate any explicit row dates."""

        warnings: list[str] = []
        wrapped = [rows for rows in pools.values() if isinstance(rows, LimitPoolRows)]
        if wrapped:
            dates: list[date] = []
            missing_group_date = False
            for pool_name, rows in pools.items():
                if rows is None:
                    continue
                if not isinstance(rows, LimitPoolRows):
                    warnings.append(f"{pool_name}: provider response missing top-level session date")
                    missing_group_date = True
                    continue
                if rows.date_warning:
                    warnings.append(f"{pool_name}: {rows.date_warning}")
                    missing_group_date = True
                if rows.actual_as_of is not None:
                    dates.append(rows.actual_as_of)
            unique_dates = set(dates)
            if len(unique_dates) > 1:
                rendered = ", ".join(sorted(value.isoformat() for value in unique_dates))
                warnings.append(f"provider pools disagree on top-level dates: {rendered}")
                return None, warnings
            actual_as_of = next(iter(unique_dates), None)
            if actual_as_of is None and all(
                isinstance(rows, LimitPoolRows)
                and rows.date_warning == "provider response missing top-level session date"
                for rows in pools.values()
                if rows is not None
            ):
                # Preserve the older explicit row-date path when a provider
                # omits the group date but every row still carries one.
                row_dates: set[date] = set()
                complete_row_dates = True
                for rows in pools.values():
                    if rows is None:
                        continue
                    for row in rows:
                        if not isinstance(row, Mapping):
                            continue
                        raw = next(
                            (
                                row[key]
                                for key in (
                                    "actual_as_of",
                                    "actualAsOf",
                                    "trade_date",
                                    "tradeDate",
                                    "as_of",
                                    "asOf",
                                    "date",
                                )
                                if row.get(key) not in (None, "", "-")
                            ),
                            None,
                        )
                        value = cls._parse_limit_date(raw)
                        if value is None:
                            complete_row_dates = False
                            break
                        row_dates.add(value)
                    if not complete_row_dates:
                        break
                if complete_row_dates and len(row_dates) == 1:
                    warnings = [
                        warning
                        for warning in warnings
                        if "provider response missing top-level session date" not in warning
                    ]
                    warnings.append("top-level pool date missing; explicit row dates used")
                    return next(iter(row_dates)), warnings
            row_date_issue = False
            if actual_as_of is not None:
                for pool_name, rows in pools.items():
                    if rows is None:
                        continue
                    for index, row in enumerate(rows):
                        if not isinstance(row, Mapping):
                            continue
                        raw = next(
                            (
                                row[key]
                                for key in (
                                    "actual_as_of",
                                    "actualAsOf",
                                    "trade_date",
                                    "tradeDate",
                                    "as_of",
                                    "asOf",
                                    "date",
                                )
                                if row.get(key) not in (None, "", "-")
                            ),
                            None,
                        )
                        if raw is None:
                            continue
                        row_date = cls._parse_limit_date(raw)
                        if row_date is None:
                            row_date_issue = True
                            warnings.append(f"{pool_name}[{index}]: invalid provider row date")
                        elif row_date != actual_as_of:
                            row_date_issue = True
                            warnings.append(
                                f"provider row date mismatch: {pool_name}[{index}] "
                                f"actual {row_date.isoformat()} vs top-level {actual_as_of.isoformat()}"
                            )
            if missing_group_date or row_date_issue:
                return None, warnings
            return actual_as_of, warnings

        # Backward-compatible fallback for callers that provide row dates but no
        # response wrapper. Missing row dates remain insufficient in this path.
        observed_dates: set[date] = set()
        observed_rows = 0
        for rows in pools.values():
            if rows is None:
                return None, warnings
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                observed_rows += 1
                raw = next(
                    (
                        row[key]
                        for key in ("actual_as_of", "actualAsOf", "trade_date", "tradeDate", "as_of", "asOf", "date")
                        if row.get(key) not in (None, "", "-")
                    ),
                    None,
                )
                value = cls._parse_limit_date(raw)
                if value is None:
                    return None, warnings
                observed_dates.add(value)
        if observed_rows == 0 or len(observed_dates) != 1:
            return None, warnings
        return next(iter(observed_dates)), warnings

    @classmethod
    def _limit_pool_actual_as_of(
        cls,
        pools: Mapping[str, list[Any] | None],
    ) -> date | None:
        """Return the single explicit date shared by all limit pools."""

        actual_as_of, _warnings = cls._limit_pool_date_evidence(pools)
        return actual_as_of

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

    def _build_sectors(
        self,
        rows: list[dict[str, Any]],
        as_of: date,
        *,
        source: str,
        status: str,
        warnings: list[str],
    ) -> dict[str, Any]:
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
                    "leader": self._optional_text(item.get("f128")),
                }
            )
        quality_warnings = [
            *warnings,
            "仅反映当日行业排名和资金流，5日持续性、板块宽度与分歧承接尚未接入",
        ]
        return {
            "rows": result,
            "state": "当日排名已观测",
            "quality": self._quality("industry-ranking", source, status, len(rows), as_of, quality_warnings),
        }

    def _build_active_direction(
        self,
        rows: list[dict[str, Any]],
        as_of: date,
        *,
        source: str,
        status: str,
        warnings: list[str],
    ) -> dict[str, Any]:
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
        quality_warnings = [
            *warnings,
            "仅有当日成交额、涨跌幅和收盘位置；20日成交放大、超额收益与连续2日确认尚未接入",
        ]
        return {
            "state": state,
            "summary": summary,
            "topStocks": stocks,
            "quality": self._quality("active-direction", source, status, len(top30), as_of, quality_warnings),
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
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)[-max(limit, 280):]

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
            "lmt": str(max(limit, 280)),
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
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)[-max(limit, 280):]

    def _fetch_sina_kline(self, spec: IndexSpec, limit: int, quote: dict[str, Any]) -> list[Bar]:
        """Fetch index history from Sina and calibrate turnover units.

        Sina exposes index volume in a different unit from currency. The latest
        Tencent real-time amount and same-day Sina volume provide a scale factor,
        so historical amounts remain comparable without presenting raw volume
        as currency.
        """
        url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{spec.code}_klines=/CN_MarketData.getKLineData"
        params = {"symbol": spec.code, "scale": "240", "ma": "no", "datalen": str(max(limit, 280))}
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
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)[-max(limit, 280):]

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
