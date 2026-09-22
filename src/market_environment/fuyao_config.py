"""Fail-closed runtime switches for dataset-level Fuyao cutover."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .provider_capability import MIGRATABLE_DATASETS


class FuyaoConfigurationError(ValueError):
    """Raised when a cutover switch is malformed or unsafe."""


_ENV_DATASET_NAMES = {
    "core": "CORE",
    "breadth": "BREADTH",
    "sectors": "SECTORS",
    "activeDirection": "ACTIVE_DIRECTION",
}


def _parse_bool(raw: str, *, name: str) -> bool:
    if not isinstance(raw, str):
        raise FuyaoConfigurationError(f"{name} must be a boolean")
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise FuyaoConfigurationError(f"{name} must be a boolean")


@dataclass(frozen=True)
class FuyaoDatasetConfig:
    dataset: str
    enabled: bool = False
    approved_revision: str | None = None
    shadow_enabled: bool = False

    def __post_init__(self) -> None:
        if self.dataset not in MIGRATABLE_DATASETS:
            raise FuyaoConfigurationError(f"unsupported Fuyao cutover dataset: {self.dataset}")
        if self.enabled and not self.approved_revision:
            raise FuyaoConfigurationError(
                f"{self.dataset} requires an approved capability revision when enabled"
            )

    @property
    def can_cutover(self) -> bool:
        return self.enabled and bool(self.approved_revision)


@dataclass(frozen=True)
class FuyaoCollectionConfig:
    """All new dataset switches; limits remains governed by its existing flag."""

    datasets: dict[str, FuyaoDatasetConfig]

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> "FuyaoCollectionConfig":
        env = os.environ if environ is None else environ
        values: dict[str, FuyaoDatasetConfig] = {}
        for dataset, env_name in _ENV_DATASET_NAMES.items():
            enabled_key = f"MARKET_ENVIRONMENT_FUYAO_{env_name}_ENABLED"
            revision_key = f"MARKET_ENVIRONMENT_FUYAO_{env_name}_APPROVED_REVISION"
            shadow_key = f"MARKET_ENVIRONMENT_FUYAO_{env_name}_SHADOW_ENABLED"
            enabled = _parse_bool(env.get(enabled_key, "0"), name=enabled_key)
            shadow_enabled = _parse_bool(env.get(shadow_key, "0"), name=shadow_key)
            raw_revision = env.get(revision_key, "")
            if not isinstance(raw_revision, str):
                raise FuyaoConfigurationError(f"{revision_key} must be a string")
            revision = raw_revision.strip() or None
            values[dataset] = FuyaoDatasetConfig(
                dataset=dataset,
                enabled=enabled,
                approved_revision=revision,
                shadow_enabled=shadow_enabled,
            )
        return cls(datasets=values)

    def for_dataset(self, dataset: str) -> FuyaoDatasetConfig:
        try:
            return self.datasets[dataset]
        except KeyError as exc:
            raise FuyaoConfigurationError(f"unsupported Fuyao cutover dataset: {dataset}") from exc

    def can_cutover(self, dataset: str, *, capability_status: str, revision: str | None) -> bool:
        config = self.for_dataset(dataset)
        return bool(
            config.can_cutover
            and capability_status == "eligible"
            and revision is not None
            and revision == config.approved_revision
        )


# Compatibility names for callers that prefer provider-oriented terminology.
FuyaoDatasetSettings = FuyaoDatasetConfig
FuyaoProviderConfig = FuyaoCollectionConfig


__all__ = [
    "FuyaoCollectionConfig",
    "FuyaoConfigurationError",
    "FuyaoDatasetConfig",
    "FuyaoDatasetSettings",
    "FuyaoProviderConfig",
]
