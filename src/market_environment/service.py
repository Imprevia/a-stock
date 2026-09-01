"""Application service for loading and calculating market environment data."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from threading import Lock
from zoneinfo import ZoneInfo

from .calculations import (
    Bar,
    amount_ratio,
    classify_trend,
    classify_volume_price,
    moving_average,
    position_label,
    range_position,
)
from .providers import INDEX_SPECS, MarketDataProvider, ProviderResult


class MarketEnvironmentService:
    def __init__(self, provider: MarketDataProvider | None = None, ttl_seconds: int = 30) -> None:
        self.provider = provider or MarketDataProvider()
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = Lock()

    def get(self, as_of: date) -> dict:
        cache_key = as_of.isoformat()
        now = datetime.now().timestamp()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self.ttl_seconds:
                return cached[1]

        warnings: list[str] = []
        try:
            quotes = self.provider.fetch_quotes(INDEX_SPECS)
        except Exception as exc:
            quotes = {}
            warnings.append(f"腾讯实时报价不可用：{exc}")

        results: list[tuple[object, ProviderResult | None, str | None]] = []
        for spec in INDEX_SPECS:
            try:
                expected_price = quotes.get(spec.code, {}).get("price")
                result = self.provider.fetch(spec, expected_price=expected_price, quote=quotes.get(spec.code, {}))
                results.append((spec, result, None))
            except Exception as exc:
                results.append((spec, None, str(exc)))

        if not any(result for _, result, _ in results):
            raise RuntimeError("全部指数数据源不可用")

        analyses = []
        effective_dates: list[date] = []
        for spec, result, error in results:
            if result is None:
                warnings.append(f"{spec.name}：{error or '无数据'}")
                continue
            bars = [bar for bar in result.bars if bar.date <= as_of]
            if not bars:
                warnings.append(f"{spec.name}：所选日期前无历史数据")
                continue
            effective_dates.append(bars[-1].date)
            quote = quotes.get(spec.code, {})
            analysis = self._analyse(spec, bars, result, quote)
            analyses.append(analysis)
            if result.warning:
                warnings.append(f"{spec.name}：{result.warning}")
            if analysis["dataQuality"]["warning"] and not result.warning:
                warnings.append(f"{spec.name}：{analysis['dataQuality']['warning']}")

        if not analyses:
            raise RuntimeError("所选日期前没有可用指数数据")
        effective_date = min(effective_dates)
        for item in analyses:
            if item["dataQuality"]["warning"] is None and effective_date < as_of:
                item["dataQuality"]["warning"] = f"非交易日，已回退到 {effective_date.isoformat()}"

        trends = Counter(item["trendState"] for item in analyses)
        sync = self._synchronization(analyses)
        dominant = trends.most_common(1)[0][0] if trends else "数据不足"
        payload = {
            "asOf": effective_date.isoformat(),
            "generatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "indices": analyses,
            "summary": {"synchronization": sync, "dominantTrend": dominant, "warnings": warnings},
        }
        payload["chapter01"] = self._chapter01(
            effective_date,
            allow_current_snapshot=as_of == date.today(),
            analyses=analyses,
            synchronization=sync,
            dominant_trend=dominant,
        )
        if payload["chapter01"]["status"] != "ok":
            warnings.append("第 01 章扩展证据未完整覆盖，结论保持低置信度或数据不足")
        with self._lock:
            self._cache[cache_key] = (now, payload)
        return payload

    def _chapter01(
        self,
        as_of: date,
        *,
        allow_current_snapshot: bool,
        analyses: list[dict],
        synchronization: str,
        dominant_trend: str,
    ) -> dict:
        fetch = getattr(self.provider, "fetch_chapter01", None)
        if fetch is None:
            provider_data = self._missing_chapter_provider_data(as_of, "provider 未实现第 01 章扩展接口")
        else:
            try:
                provider_data = fetch(as_of, allow_current_snapshot=allow_current_snapshot)
            except Exception as exc:
                provider_data = self._missing_chapter_provider_data(as_of, f"第 01 章扩展接口失败：{exc}")

        breadth = provider_data["breadth"]
        limits = provider_data["limits"]
        sectors = provider_data["sectors"]
        active_direction = provider_data["activeDirection"]
        events = {
            "state": "unverified",
            "items": [],
            "quality": self._quality(
                "traceable-events",
                "not-connected",
                "missing",
                0,
                as_of,
                ["未提供带来源、发布时间、有效期和失效条件的结构化事件输入"],
            ),
        }
        documents = self._chapter_documents(breadth, limits, sectors, active_direction)
        qualities = [breadth["quality"], limits["quality"], sectors["quality"], active_direction["quality"], events["quality"]]
        status_weight = {"ok": 1.0, "fallback": 0.75, "partial": 0.5, "missing": 0.0, "failed": 0.0}
        coverage = round((1.0 + sum(status_weight.get(item["status"], 0.0) for item in qualities)) / 6.0, 4)
        status = "partial" if coverage >= 0.5 else "insufficient"

        evidence = [f"指数：{synchronization}，主导趋势 {dominant_trend}，有效指数 {len(analyses)} 个"]
        if breadth.get("validCount") is not None:
            evidence.append(
                f"广度：涨 {breadth['advanceCount']} / 跌 {breadth['declineCount']} / 平 {breadth['flatCount']}，中位涨跌幅 {breadth['medianReturn']:.2f}%"
            )
        if limits.get("limitUpCount") is not None:
            evidence.append(
                f"涨跌停：涨停 {limits['limitUpCount']}，跌停 {limits['limitDownCount']}，炸板 {limits['failedLimitUpCount']}"
            )
        if sectors.get("rows"):
            names = "、".join(item.get("name") or "未知" for item in sectors["rows"][:3])
            evidence.append(f"行业当日排名：{names}")
        if active_direction.get("summary"):
            evidence.append(f"容量方向：{active_direction['summary']}")

        risks = [
            "高位股、中位股和低位股亏钱效应尚未接入",
            "事件、政策和突发信息未提供可追溯结构化输入",
            "滚动分位和历史阈值尚未校准，不输出验证分数",
        ]
        confidence = "low" if coverage >= 0.5 else "insufficient"
        return {
            "status": status,
            "coverage": coverage,
            "documents": documents,
            "breadth": breadth,
            "limits": limits,
            "sectors": sectors,
            "activeDirection": active_direction,
            "events": events,
            "assessment": {
                "state": "证据不完整" if confidence == "low" else "insufficient",
                "confidence": confidence,
                "evidence": evidence,
                "risks": risks,
                "nextConfirmation": "补齐分层亏钱效应、主线连续性和可追溯事件后再确认环境分类",
                "invalidation": "任一证据日期不一致、provider 失败或风险证据显著恶化时，不使用候选判断",
            },
        }

    @classmethod
    def _missing_chapter_provider_data(cls, as_of: date, warning: str) -> dict:
        quality = cls._quality("chapter-01-extended", "none", "failed", 0, as_of, [warning])
        return {
            "breadth": {
                "advanceCount": None,
                "declineCount": None,
                "flatCount": None,
                "validCount": None,
                "advanceRatio": None,
                "medianReturn": None,
                "state": "insufficient",
                "quality": {**quality, "dataset": "market-breadth"},
            },
            "limits": {
                "limitUpCount": None,
                "limitDownCount": None,
                "failedLimitUpCount": None,
                "failedLimitUpRatio": None,
                "maxStreak": None,
                "state": "insufficient",
                "quality": {**quality, "dataset": "limit-pools"},
            },
            "sectors": {
                "rows": [],
                "state": "insufficient",
                "quality": {**quality, "dataset": "industry-ranking"},
            },
            "activeDirection": {
                "state": "insufficient",
                "summary": None,
                "topStocks": [],
                "quality": {**quality, "dataset": "active-direction"},
            },
        }

    @staticmethod
    def _quality(dataset: str, provider: str, status: str, observations: int, as_of: date, warnings: list[str]) -> dict:
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
    def _chapter_documents(breadth: dict, limits: dict, sectors: dict, active_direction: dict) -> list[dict]:
        def evidence_status(quality: dict) -> str:
            return "partial" if quality["status"] in {"ok", "fallback", "partial"} else "insufficient"

        definitions = (
            ("01", "指数、趋势位置和成交额", "partial"),
            ("02", "上涨家数、下跌家数和涨跌幅中位数", evidence_status(breadth["quality"])),
            ("03", "涨停、跌停、炸板和连板晋级", evidence_status(limits["quality"])),
            ("04", "高位股、中位股和低位股的亏钱效应", "insufficient"),
            ("05", "主线持续性和成交额集中度", evidence_status(sectors["quality"])),
            ("06", "大成交额个股中是否出现主动进攻方向", evidence_status(active_direction["quality"])),
            ("07", "公告、政策、外围和突发事件", "unverified"),
            ("08", "如何归类市场环境", "insufficient"),
            ("09", "如何综合判断市场环境", "insufficient"),
        )
        return [
            {
                "id": doc_id,
                "title": title,
                "document": f"01-如何判断市场环境/{doc_id}.{title}.md",
                "status": status,
                "ruleVersion": "0.1",
            }
            for doc_id, title, status in definitions
        ]

    @staticmethod
    def _analyse(spec, bars: list[Bar], result: ProviderResult, quote: dict) -> dict:
        ma = {f"ma{window}": moving_average(bars, window) for window in (5, 10, 20, 60)}
        ratio5 = amount_ratio(bars, 5)
        ratio20 = amount_ratio(bars, 20)
        close = bars[-1].close
        change_pct = quote.get("change_pct")
        if change_pct is None or quote.get("is_stale"):
            change_pct = ((close / bars[-2].close) - 1) * 100 if len(bars) > 1 and bars[-2].close else 0
        warning = result.warning
        quality_warnings: list[str] = []
        if not quote:
            quality_warnings.append("腾讯实时行情不可用，涨跌幅使用历史 K 线计算")
        if len(bars) >= 20 and range_position(bars, 20) is None:
            quality_warnings.append("20 日最高价与最低价相同，区间位置不可计算")
        if len(bars) >= 60 and range_position(bars, 60) is None:
            quality_warnings.append("60 日最高价与最低价相同，区间位置不可计算")
        if quote.get("is_stale"):
            quality_warnings.insert(0, "腾讯报价疑似停牌或过期，涨跌幅已使用历史 K 线计算")
        if quality_warnings:
            warning = "；".join(filter(None, [warning, *quality_warnings]))
        history = []
        for index in range(max(0, len(bars) - 60), len(bars)):
            sample = bars[: index + 1]
            history.append(
                {
                    "date": bars[index].date.isoformat(),
                    "close": bars[index].close,
                    "ma5": moving_average(sample, 5),
                    "ma10": moving_average(sample, 10),
                    "ma20": moving_average(sample, 20),
                    "ma60": moving_average(sample, 60),
                    "amount": bars[index].amount,
                }
            )
        return {
            "code": spec.code,
            "name": quote.get("name") or spec.name,
            "representative": spec.representative,
            "changePct": round(float(change_pct or 0), 2),
            "close": round(close, 2),
            "movingAverages": {key: round(value, 2) if value is not None else None for key, value in ma.items()},
            "rangePosition20": range_position(bars, 20),
            "rangePosition60": range_position(bars, 60),
            "rangePosition20Label": position_label(range_position(bars, 20)),
            "rangePosition60Label": position_label(range_position(bars, 60)),
            "amount": round(bars[-1].amount, 2),
            "amountRatio5": round(ratio5, 2) if ratio5 is not None else None,
            "amountRatio20": round(ratio20, 2) if ratio20 is not None else None,
            "trendState": classify_trend(bars, ratio20),
            "volumePriceState": classify_volume_price(bars, ratio5),
            "history": history,
            "dataQuality": {"source": result.source, "isStale": bool(quote.get("is_stale")), "warning": warning},
        }

    @staticmethod
    def _synchronization(analyses: list[dict]) -> str:
        changes = [item["changePct"] for item in analyses]
        if not changes:
            return "无可用数据"
        positive = sum(value >= 0.5 for value in changes)
        negative = sum(value <= -0.5 for value in changes)
        if positive >= max(3, len(changes) - 1):
            return "同步上涨"
        if negative >= max(3, len(changes) - 1):
            return "普遍走弱"
        return "指数分化"
