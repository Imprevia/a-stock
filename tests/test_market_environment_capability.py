from datetime import datetime, timezone

import pytest

from src.market_environment.fuyao_config import (
    FuyaoCollectionConfig,
    FuyaoConfigurationError,
)
from src.market_environment.provider_capability import ProviderCapabilityReport
from src.market_environment.snapshot_store import SnapshotStore


def report() -> ProviderCapabilityReport:
    return ProviderCapabilityReport(
        provider="fuyao",
        dataset="core",
        revision="r1",
        status="eligible",
        endpoint="/api/a-share/index/quote",
        field_coverage={"close": True, "amount": True},
        date_evidence={"requested": "2026-09-22", "response": "2026-09-22"},
        sample_count=5,
        checked_at=datetime(2026, 9, 22, 8, tzinfo=timezone.utc),
    )


def test_capability_report_round_trip_and_redaction() -> None:
    value = report().normalized()
    restored = ProviderCapabilityReport.from_dict(value.to_dict())
    assert restored == value
    redacted = value.to_dict(redacted=True)
    assert redacted["checksum"] == value.checksum
    assert "api_key" not in str(redacted).lower()


def test_capability_report_sqlite_round_trip_and_idempotency(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "capability.sqlite3")
    value = report()
    assert store.put_capability_report(value) == value.normalized()
    assert store.put_capability_report(value) == value.normalized()
    assert store.get_capability_report("fuyao", "core", "r1") == value.normalized()
    assert len(store.list_capability_reports(provider="fuyao")) == 1
    with pytest.raises(ValueError, match="different checksum"):
        store.put_capability_report(
            ProviderCapabilityReport(**{**value.__dict__, "status": "ineligible", "checksum": ""})
        )


def test_fuyao_switches_default_closed_and_require_approved_revision() -> None:
    config = FuyaoCollectionConfig.from_environment({})
    assert all(not item.enabled and not item.shadow_enabled for item in config.datasets.values())
    with pytest.raises(FuyaoConfigurationError):
        FuyaoCollectionConfig.from_environment({"MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED": "true"})
    with pytest.raises(FuyaoConfigurationError):
        FuyaoCollectionConfig.from_environment({"MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED": "maybe"})
    enabled = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED": "true",
            "MARKET_ENVIRONMENT_FUYAO_CORE_APPROVED_REVISION": "r1",
            "MARKET_ENVIRONMENT_FUYAO_CORE_SHADOW_ENABLED": "true",
        }
    )
    assert enabled.can_cutover("core", capability_status="eligible", revision="r1")
    assert not enabled.can_cutover("core", capability_status="unverified", revision="r1")


def test_limits_existing_flag_is_not_part_of_cutover_switches() -> None:
    config = FuyaoCollectionConfig.from_environment(
        {"MARKET_ENVIRONMENT_LIMITS_V1_ENABLED": "1"}
    )
    assert "limits" not in config.datasets
