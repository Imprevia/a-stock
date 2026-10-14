from __future__ import annotations

from datetime import date

import pytest

from src.market_environment.application.ths_diagnostics import (
    THS_DIAGNOSTIC_PREFIX,
    THS_DIAGNOSTIC_SAMPLE_LIMIT,
    ThsBlockedBy,
    ThsDiagnostic,
    encode_ths_diagnostic,
    parse_ths_diagnostic,
    ths_warning_response,
)


AS_OF = date(2026, 10, 14)


def test_ths_diagnostic_round_trip_preserves_bounded_typed_evidence() -> None:
    missing_codes = tuple(f"{index:06d}.TI" for index in range(30, -1, -1))
    diagnostic = ThsDiagnostic(
        reason_code="THS_LIVE_VALUES_MISSING",
        message="31 个目录编号缺少当日行情",
        failure_stage="snapshot-value-classification",
        exact_date=AS_OF,
        retryable=True,
        capability_revision="fuyao-ths-catalog-v1",
        catalog_revision_id="fuyao:cap-v1:2026-10-14:sha256:abc123",
        expected_count=846,
        observed_count=846,
        usable_count=815,
        rankable_count=815,
        bar_count=815,
        missing_live_codes=missing_codes,
        missing_ranking_count=31,
        missing_ranking_codes=missing_codes,
    )

    warning = encode_ths_diagnostic(diagnostic)
    decoded = parse_ths_diagnostic(warning)

    assert warning.startswith(THS_DIAGNOSTIC_PREFIX)
    assert decoded is not None
    assert decoded.reason_code == "THS_LIVE_VALUES_MISSING"
    assert decoded.retryable is True
    assert decoded.missing_live_count == 31
    assert decoded.missing_live_codes == tuple(
        f"{index:06d}.TI" for index in range(THS_DIAGNOSTIC_SAMPLE_LIMIT)
    )
    assert len(decoded.missing_ranking_codes) == THS_DIAGNOSTIC_SAMPLE_LIMIT
    message, response = ths_warning_response(warning)
    assert message == "31 个目录编号缺少当日行情"
    assert response is not None
    assert response["expectedCount"] == 846
    assert len(response["missingLiveCodes"]) == THS_DIAGNOSTIC_SAMPLE_LIMIT


def test_ths_diagnostic_round_trip_preserves_bounded_dependency_summary() -> None:
    diagnostic = ThsDiagnostic(
        reason_code="THS_DEPENDENCY_REVISION_MISMATCH",
        message="上游目录观察版本不一致",
        failure_stage="dependency-validation",
        exact_date=AS_OF,
        retryable=False,
        catalog_revision_id="catalog-current",
        blocked_by=(
            ThsBlockedBy(
                dataset="industry-ranking",
                status="partial",
                reason_code="THS_LIVE_VALUES_MISSING",
                exact_date=AS_OF,
                catalog_revision_id="catalog-upstream",
            ),
        ),
    )

    decoded = parse_ths_diagnostic(encode_ths_diagnostic(diagnostic))

    assert decoded is not None
    assert decoded.retryable is False
    assert decoded.blocked_by[0].dataset == "industry-ranking"
    assert decoded.blocked_by[0].catalog_revision_id == "catalog-upstream"


@pytest.mark.parametrize(
    "warning",
    [
        "旧版纯文本 warning",
        THS_DIAGNOSTIC_PREFIX + "not-json",
        THS_DIAGNOSTIC_PREFIX + "{}",
        THS_DIAGNOSTIC_PREFIX
        + '{"reasonCode":"UNKNOWN","message":"x","failureStage":"x",'
        '"exactDate":"2026-10-14","retryable":true}',
        THS_DIAGNOSTIC_PREFIX
        + '{"reasonCode":"THS_LIVE_VALUES_MISSING","reasonCode":'
        '"THS_DEPENDENCY_INSUFFICIENT","message":"x","failureStage":"x",'
        '"exactDate":"2026-10-14","retryable":true}',
    ],
)
def test_legacy_or_malformed_diagnostic_falls_back_to_original_warning(
    warning: str,
) -> None:
    assert parse_ths_diagnostic(warning) is None
    assert ths_warning_response(warning) == (warning, None)


def test_ths_diagnostic_redacts_urls_credentials_and_rejects_raw_fields() -> None:
    diagnostic = ThsDiagnostic(
        reason_code="THS_DAILY_SNAPSHOT_INSUFFICIENT",
        message=(
            "provider https://signed.example/data?token=top-secret failed; "
            "Authorization=Bearer-never-persist"
        ),
        failure_stage="snapshot-identity-validation",
        exact_date=AS_OF,
        retryable=True,
    )

    warning = encode_ths_diagnostic(diagnostic)

    assert "signed.example" not in warning
    assert "top-secret" not in warning
    assert "Bearer-never-persist" not in warning
    assert "[redacted-url]" in warning
    raw_payload_envelope = (
        THS_DIAGNOSTIC_PREFIX
        + '{"reasonCode":"THS_DAILY_SNAPSHOT_INSUFFICIENT","message":"safe",'
        '"failureStage":"snapshot","exactDate":"2026-10-14",'
        '"retryable":true,"rawResponse":{"token":"secret"}}'
    )
    assert parse_ths_diagnostic(raw_payload_envelope) is None


def test_ths_diagnostic_rejects_inconsistent_sample_counts() -> None:
    with pytest.raises(ValueError, match="smaller than its sample"):
        ThsDiagnostic(
            reason_code="THS_LIVE_VALUES_MISSING",
            message="missing",
            failure_stage="snapshot",
            exact_date=AS_OF,
            retryable=True,
            missing_live_count=1,
            missing_live_codes=("000001.TI", "000002.TI"),
        )
