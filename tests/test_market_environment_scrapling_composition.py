from __future__ import annotations

import sys
from typing import Any

import pytest

from src.market_environment.bootstrap.container import ContainerAdapters, build_container
from src.market_environment.bootstrap.settings import (
    MarketEnvironmentSettings,
    SettingsConfigurationError,
)
from src.trading_system.data.provider_transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportRequest,
    reset_process_transport_gateway_for_testing,
)


class _Resource:
    path = None

    def close(self) -> None:
        pass


class _Executor:
    def submit(self, function, *args: Any):
        return function(*args)

    def close(self) -> None:
        pass


class _TimezoneRepository(_Resource):
    def get(self, *_args: Any, **_kwargs: Any):
        return None

    def set(self, *_args: Any, **_kwargs: Any):
        return None


def _build(settings: MarketEnvironmentSettings):
    return build_container(
        settings,
        adapters=ContainerAdapters(
            repository=_Resource(),
            task_executor=_Executor(),
            refresh_executor=_Executor(),
            timezone_repository=_TimezoneRepository(),
            fuyao_adapter=_Resource(),
        ),
    )


def test_settings_parse_exact_scrapling_host_source_allowlist() -> None:
    settings = MarketEnvironmentSettings.from_environment(
        {
            "MARKET_ENVIRONMENT_SCRAPLING_ENABLED": "1",
            "MARKET_ENVIRONMENT_SCRAPLING_ALLOWLIST": (
                '[{"host":"quotes.example.test","sourceId":"quotes-v1"}]'
            ),
        }
    )

    assert settings.scrapling.enabled is True
    assert settings.scrapling.allowlist == frozenset(
        {("quotes.example.test", "quotes-v1")}
    )


@pytest.mark.parametrize(
    "value",
    (
        "not-json",
        "{}",
        '[{"host":"example.test"}]',
        '[{"host":"*","sourceId":"quotes-v1"}]',
    ),
)
def test_settings_reject_malformed_scrapling_allowlist(value: str) -> None:
    with pytest.raises(SettingsConfigurationError):
        MarketEnvironmentSettings.from_environment(
            {"MARKET_ENVIRONMENT_SCRAPLING_ALLOWLIST": value}
        )


def test_disabled_profile_composes_requests_only_without_optional_import() -> None:
    reset_process_transport_gateway_for_testing()
    try:
        settings = MarketEnvironmentSettings.from_environment({})
        container = _build(settings)

        assert settings.scrapling.enabled is False
        assert settings.scrapling.allowlist == frozenset()
        assert container.registries.transport_engines.names == ("requests",)
        assert "scrapling.fetchers" not in sys.modules
        container.close()
    finally:
        reset_process_transport_gateway_for_testing()


def test_enabled_empty_profile_registers_lazy_fail_closed_engine() -> None:
    reset_process_transport_gateway_for_testing()
    try:
        settings = MarketEnvironmentSettings.from_environment(
            {"MARKET_ENVIRONMENT_SCRAPLING_ENABLED": "1"}
        )
        container = _build(settings)
        registry = container.registries.transport_engines

        assert registry.names == ("requests", "scrapling")
        assert "scrapling.fetchers" not in sys.modules
        engine = registry.resolve("scrapling")
        with pytest.raises(TransportFailure) as caught:
            engine.send(
                TransportRequest(
                    "GET",
                    "https://quotes.example.test/api",
                    engine="scrapling",
                    source_id="quotes-v1",
                )
            )
        assert caught.value.category is TransportFailureCategory.CONFIGURATION
        assert "scrapling.fetchers" not in sys.modules
        container.close()
    finally:
        reset_process_transport_gateway_for_testing()


def test_process_profile_mismatch_fails_closed() -> None:
    reset_process_transport_gateway_for_testing()
    first = None
    try:
        first = _build(MarketEnvironmentSettings.from_environment({}))
        with pytest.raises(SettingsConfigurationError, match="do not match"):
            _build(
                MarketEnvironmentSettings.from_environment(
                    {"MARKET_ENVIRONMENT_SCRAPLING_ENABLED": "1"}
                )
            )
    finally:
        if first is not None:
            first.close()
        reset_process_transport_gateway_for_testing()
