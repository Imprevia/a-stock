"""Database-only CLI composition for capability report promotion."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from ...application.commands import PromoteCapabilityReportCommand
from ...database import DatabaseSettings
from ...infrastructure.persistence.postgres import (
    PostgresConnectionFactory,
    ProviderCapabilityPromotionUnitOfWork,
)


@dataclass(frozen=True, slots=True)
class CapabilityPromotionRuntime:
    command: PromoteCapabilityReportCommand
    target_backend: str
    connections: PostgresConnectionFactory

    def close(self) -> None:
        self.connections.dispose()


def build_capability_promotion_runtime() -> CapabilityPromotionRuntime:
    settings = DatabaseSettings.from_environment(required=True)
    assert settings is not None
    connections = PostgresConnectionFactory.from_settings(
        settings,
        validate_runtime=False,
    )
    command = PromoteCapabilityReportCommand(
        lambda: _validated_unit_of_work(connections)
    )
    return CapabilityPromotionRuntime(
        command=command,
        target_backend=_masked_backend_identity(settings.url),
        connections=connections,
    )


def _validated_unit_of_work(
    connections: PostgresConnectionFactory,
) -> ProviderCapabilityPromotionUnitOfWork:
    # This factory is invoked only after the command's pure report validation.
    connections.validate_runtime()
    return ProviderCapabilityPromotionUnitOfWork(connections)


def _masked_backend_identity(database_url: str) -> str:
    parsed = urlsplit(database_url)
    host = parsed.hostname or "unknown-host"
    authority = host if parsed.port is None else f"{host}:{parsed.port}"
    database = parsed.path.lstrip("/") or "unknown-database"
    scheme = parsed.scheme.lower()
    return f"{scheme}://***@{authority}/{database}"


__all__ = [
    "CapabilityPromotionRuntime",
    "build_capability_promotion_runtime",
]
