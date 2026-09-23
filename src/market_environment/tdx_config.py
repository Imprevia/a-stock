"""Fail-closed configuration for the TDX daily-package fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass


TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV = (
    "MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED"
)


class TDXConfigurationError(ValueError):
    """Raised when the TDX fallback switch is malformed."""


def _parse_bool(raw: str, *, name: str) -> bool:
    if not isinstance(raw, str):
        raise TDXConfigurationError(f"{name} must be a boolean")
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise TDXConfigurationError(f"{name} must be a boolean")


@dataclass(frozen=True)
class TDXDailyPackageConfig:
    """Runtime switch; no credentials or provider routing live in this config."""

    fallback_enabled: bool = False

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> "TDXDailyPackageConfig":
        env = os.environ if environ is None else environ
        return cls(
            fallback_enabled=_parse_bool(
                env.get(TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV, "0"),
                name=TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV,
            )
        )


__all__ = [
    "TDX_DAILY_PACKAGE_FALLBACK_ENABLED_ENV",
    "TDXConfigurationError",
    "TDXDailyPackageConfig",
]
