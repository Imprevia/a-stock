"""CLI composition that reuses application factories without FastAPI."""

from __future__ import annotations

from dataclasses import dataclass

from ...bootstrap.container import (
    ApplicationContainer,
    ContainerAdapters,
    build_container,
)
from ...bootstrap.settings import MarketEnvironmentSettings


@dataclass(frozen=True, slots=True)
class CliContainer:
    application: ApplicationContainer

    @property
    def settings(self) -> MarketEnvironmentSettings:
        return self.application.settings

    @property
    def coordinator(self):
        return self.application.commands.collection

    def close(self) -> None:
        self.application.close()


def build_cli_container(
    settings: MarketEnvironmentSettings | None = None,
    *,
    adapters: ContainerAdapters | None = None,
) -> CliContainer:
    """Build CLI dependencies without importing or constructing FastAPI."""

    return CliContainer(build_container(settings, adapters=adapters))


__all__ = ["CliContainer", "build_cli_container"]
