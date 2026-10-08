"""Immutable top-level configuration assembled without opening resources."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time

from src.trading_system.data.provider_scrapling import ScraplingStaticEngineConfig

from ..database import DatabaseSettings
from ..infrastructure.providers.fuyao.config import FuyaoCollectionConfig
from ..infrastructure.providers.tdx.config import TDXDailyPackageConfig


class SettingsConfigurationError(ValueError):
    """Raised when a top-level runtime setting is malformed."""


@dataclass(frozen=True, slots=True)
class MarketEnvironmentSettings:
    """Validated values used by HTTP and CLI composition roots.

    Constructing this value is deliberately side-effect free: it parses only
    the supplied environment mapping and does not create engines, providers or
    executors.
    """

    database: DatabaseSettings | None
    fuyao: FuyaoCollectionConfig
    tdx: TDXDailyPackageConfig
    scrapling: ScraplingStaticEngineConfig
    market_timezone: str = "Asia/Shanghai"
    settlement_time: time = time(15, 10)
    open_time: time = time(9, 30)
    manual_refresh_enabled: bool = True
    persistent_cache_enabled: bool = True
    limits_v1_enabled: bool = False
    sector_enrichment_enabled: bool = False
    collection_workers: int = 2

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        require_database: bool = False,
    ) -> "MarketEnvironmentSettings":
        env = os.environ if environ is None else environ
        specialized_env = dict(env)
        return cls(
            database=DatabaseSettings.from_environment(
                required=require_database,
                environ=env,
            ),
            fuyao=FuyaoCollectionConfig.from_environment(specialized_env),
            tdx=TDXDailyPackageConfig.from_environment(specialized_env),
            scrapling=_scrapling_config(env),
            market_timezone=_text(
                env,
                "MARKET_ENVIRONMENT_TIMEZONE",
                "Asia/Shanghai",
            ),
            settlement_time=_clock_time(
                env,
                "MARKET_ENVIRONMENT_SETTLEMENT_TIME",
                time(15, 10),
            ),
            open_time=_clock_time(
                env,
                "MARKET_ENVIRONMENT_OPEN_TIME",
                time(9, 30),
            ),
            manual_refresh_enabled=_boolean(
                env,
                "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED",
                True,
            ),
            persistent_cache_enabled=_boolean(
                env,
                "MARKET_ENVIRONMENT_PERSISTENT_CACHE",
                True,
            ),
            limits_v1_enabled=_boolean(
                env,
                "MARKET_ENVIRONMENT_LIMITS_V1_ENABLED",
                False,
            ),
            sector_enrichment_enabled=_boolean(
                env,
                "MARKET_ENVIRONMENT_EASTMONEY_SECTOR_ENRICHMENT_ENABLED",
                False,
            ),
            collection_workers=_positive_integer(
                env,
                "MARKET_ENVIRONMENT_COLLECTION_WORKERS",
                2,
            ),
        )


def _text(env: Mapping[str, str], name: str, default: str) -> str:
    raw = env.get(name, default)
    if not isinstance(raw, str) or not raw.strip():
        raise SettingsConfigurationError(f"{name} must be a non-empty string")
    return raw.strip()


def _boolean(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "1" if default else "0")
    if not isinstance(raw, str):
        raise SettingsConfigurationError(f"{name} must be a boolean")
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise SettingsConfigurationError(f"{name} must be a boolean")


def _clock_time(env: Mapping[str, str], name: str, default: time) -> time:
    raw = env.get(name, default.strftime("%H:%M"))
    if not isinstance(raw, str):
        raise SettingsConfigurationError(f"{name} must use HH:MM")
    try:
        return time.fromisoformat(raw.strip())
    except ValueError as exc:
        raise SettingsConfigurationError(f"{name} must use HH:MM") from exc


def _positive_integer(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    if not isinstance(raw, str):
        raise SettingsConfigurationError(f"{name} must be an integer")
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise SettingsConfigurationError(f"{name} must be an integer") from exc
    if value < 1:
        raise SettingsConfigurationError(f"{name} must be >= 1")
    return value


def _scrapling_allowlist(
    env: Mapping[str, str],
) -> frozenset[tuple[str, str]]:
    name = "MARKET_ENVIRONMENT_SCRAPLING_ALLOWLIST"
    raw = env.get(name, "[]")
    if not isinstance(raw, str):
        raise SettingsConfigurationError(f"{name} must be a JSON array")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SettingsConfigurationError(f"{name} must be a JSON array") from exc
    if not isinstance(payload, list):
        raise SettingsConfigurationError(f"{name} must be a JSON array")
    entries: set[tuple[str, str]] = set()
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"host", "sourceId"}:
            raise SettingsConfigurationError(
                f"{name} entries must contain only host and sourceId"
            )
        host = item["host"]
        source_id = item["sourceId"]
        if not isinstance(host, str) or not isinstance(source_id, str):
            raise SettingsConfigurationError(
                f"{name} host and sourceId must be strings"
            )
        entries.add((host, source_id))
    return frozenset(entries)


def _scrapling_config(env: Mapping[str, str]) -> ScraplingStaticEngineConfig:
    enabled = _boolean(
        env,
        "MARKET_ENVIRONMENT_SCRAPLING_ENABLED",
        False,
    )
    allowlist = _scrapling_allowlist(env)
    try:
        return ScraplingStaticEngineConfig(
            enabled=enabled,
            allowlist=allowlist,
        )
    except ValueError as exc:
        raise SettingsConfigurationError(
            "MARKET_ENVIRONMENT_SCRAPLING_ALLOWLIST contains an invalid host/source pair"
        ) from exc


__all__ = ["MarketEnvironmentSettings", "SettingsConfigurationError"]
