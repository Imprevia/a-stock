from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.market_environment import cli as market_cli
from src.market_environment.domain.models import (
    INDUSTRY_CAPABILITY_DATASETS,
    IndustryCapabilityError,
    IndustryCapabilityReport,
)
from src.market_environment.infrastructure.providers.industry_capability import (
    BaostockAdjustedPriceAdapter,
    BenchmarkHistoryAdapter,
    CapabilityGateError,
    IndustryCapabilityGate,
    IndustryImportError,
    MootdxAdjustedPriceAdapter,
    ShenwanOperatorImportAdapter,
)
from src.market_environment.interfaces.cli.industry_capability_probe import (
    IndustryProbeError,
    run_industry_capability_probe,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "sector-continuity"
AS_OF = date(2026, 8, 28)
AFTER_MARKET = datetime(2026, 8, 28, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
DURING_MARKET = datetime(2026, 8, 28, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _report(dataset: str, *, source: str = "fixture", revision: str = "fixture-v1", **changes) -> IndustryCapabilityReport:
    values = {
        "dataset": dataset,
        "source": source,
        "revision": revision,
        "status": "eligible",
        "requested_dates": (AS_OF,),
        "actual_dates": (AS_OF,),
        "market_coverage": {"sh": True, "sz": True, "bj": True},
        "field_semantics": {"identity": "canonical-security-id"},
        "pagination": {"complete": True, "duplicates": 0},
        "permission": {"approved": True, "configured": True},
        "rate_limit": {"bounded": True, "requestBudget": 1},
        "data_rights": {
            "reviewed": True,
            "clientLicense": "fixture-only",
            "underlyingDataTerms": "synthetic-fixture-only",
            "automationAllowed": True,
            "storageAllowed": True,
            "derivedDisplayAllowed": True,
        },
        "negative_cases": ("permission-denied", "mixed-date", "duplicate-identity"),
        "sample_count": 3,
        "checked_at": AFTER_MARKET,
    }
    values.update(changes)
    return IndustryCapabilityReport(**values).normalized()


def _adjusted_report(*, source: str, revision: str, market_coverage=None) -> IndustryCapabilityReport:
    return _report(
        "stock-adjusted-price",
        source=source,
        revision=revision,
        market_coverage=market_coverage or {"sh": True, "sz": True, "bj": True},
        field_semantics={
            "adjustedClose": "front-adjusted-close",
            "originalAmount": "original-yuan",
            "corporateActions": "fixture-proven",
        },
    )


def _benchmark_report() -> IndustryCapabilityReport:
    return _report(
        "benchmark-history",
        source="derived",
        revision="ordinary-a-share-equal-weight-v1",
        field_semantics={
            "benchmark": "ordinary-a-share-equal-weight-v1",
            "aggregation": "equal-weight-valid-front-adjusted-returns",
        },
    )


def test_all_five_industry_capability_contracts_round_trip() -> None:
    assert set(INDUSTRY_CAPABILITY_DATASETS) == {
        "shenwan-taxonomy",
        "shenwan-point-in-time-membership",
        "stock-adjusted-price",
        "tdx-original-daily-facts",
        "benchmark-history",
    }
    for dataset in INDUSTRY_CAPABILITY_DATASETS:
        report = _report(dataset)
        assert IndustryCapabilityReport.from_dict(report.to_dict()) == report
        assert report.checksum


@pytest.mark.parametrize("status", ["ineligible", "unverified"])
def test_noneligible_report_may_record_incomplete_evidence(status: str) -> None:
    report = IndustryCapabilityReport(
        dataset="stock-adjusted-price",
        source="candidate",
        revision="candidate-v1",
        status=status,
        warnings=("Beijing coverage is unproven",),
    )
    assert report.status == status


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"actual_dates": (date(2026, 8, 27),)}, "date evidence"),
        ({"pagination": {"complete": False}}, "pagination"),
        ({"permission": {"approved": False}}, "permission"),
        ({"rate_limit": {"bounded": False}}, "rate-limit"),
        ({"data_rights": {"reviewed": False}}, "data-rights"),
        ({"negative_cases": ()}, "negative-case"),
    ],
)
def test_eligible_report_fails_closed_on_missing_evidence(changes, message: str) -> None:
    with pytest.raises(IndustryCapabilityError, match=message):
        _report("stock-adjusted-price", **changes)


def test_report_rejects_sensitive_material_without_echo() -> None:
    raw = _report("stock-adjusted-price").to_dict()
    raw["permission"]["token"] = "do-not-echo"
    raw["checksum"] = ""
    with pytest.raises(IndustryCapabilityError, match="sensitive") as exc:
        IndustryCapabilityReport.from_dict(raw)
    assert "do-not-echo" not in str(exc.value)


def test_fixture_covers_identity_history_corporate_action_and_negative_cases() -> None:
    fixture = json.loads((FIXTURES / "capability-inputs.json").read_text(encoding="utf-8"))
    assert fixture["membershipHistory"][0]["validTo"] == fixture["membershipHistory"][1]["validFrom"]
    assert any(row["securityId"].startswith("bj.920") for row in fixture["membershipHistory"])
    assert any(row.get("state") == "delisted" for row in fixture["membershipHistory"])
    assert any(row.get("state") == "suspended" for row in fixture["adjustedPrices"])
    assert fixture["adjustedPrices"][0]["adjustedClose"] != fixture["adjustedPrices"][0]["originalClose"]
    assert fixture["benchmarkNegativeCases"]["missingSession"]
    assert fixture["benchmarkNegativeCases"]["mixedDateRow"]["asOf"] != fixture["asOf"]


def test_capability_gate_is_exact_identity_and_date_scoped() -> None:
    report = _adjusted_report(source="baostock", revision="baostock-adjusted-v1")
    gate = IndustryCapabilityGate((report,))
    assert gate.require(report.dataset, report.source, report.revision, as_of=AS_OF) == report
    with pytest.raises(CapabilityGateError, match="missing"):
        gate.require(report.dataset, "mootdx", report.revision, as_of=AS_OF)
    with pytest.raises(CapabilityGateError, match="exact date"):
        gate.require(report.dataset, report.source, report.revision, as_of=date(2026, 8, 27))


def test_shenwan_operator_import_is_checksum_bound_idempotent_and_point_in_time() -> None:
    adapter = ShenwanOperatorImportAdapter()
    first = adapter.import_file(FIXTURES / "shenwan-operator-import.json")
    second = adapter.import_file(FIXTURES / "shenwan-operator-import.json")
    assert first == second
    assert first.status == "validated"
    assert first.memberships[0].covers(date(2026, 6, 30))
    assert not first.memberships[0].covers(date(2026, 7, 1))
    assert first.memberships[1].covers(date(2026, 7, 1))
    assert any(item.security_id == "bj.920001" for item in first.memberships)


@pytest.mark.parametrize("mutation", ["missing-checksum", "concept", "overlap", "missing-rights"])
def test_shenwan_operator_import_rejects_unsafe_input(mutation: str) -> None:
    raw = json.loads((FIXTURES / "shenwan-operator-import.json").read_text(encoding="utf-8"))
    if mutation == "missing-checksum":
        raw.pop("checksum")
    elif mutation == "concept":
        raw["taxonomyFamily"] = "concept"
        raw["checksum"] = ""
    elif mutation == "overlap":
        raw["memberships"][1]["validFrom"] = "2026-06-30"
        raw["checksum"] = ""
    else:
        raw["dataRights"]["storageAllowed"] = False
        raw["checksum"] = ""
    with pytest.raises(IndustryImportError):
        ShenwanOperatorImportAdapter().import_payload(raw)


def test_shenwan_operator_import_rejects_missing_membership_lineage() -> None:
    raw = json.loads((FIXTURES / "shenwan-operator-import.json").read_text(encoding="utf-8"))
    raw["memberships"][0].pop("validFrom")
    raw["checksum"] = ""
    with pytest.raises(IndustryImportError):
        ShenwanOperatorImportAdapter().import_payload(raw)


def test_adjusted_price_adapters_are_capability_gated_and_preserve_raw_amount() -> None:
    fixture = json.loads((FIXTURES / "capability-inputs.json").read_text(encoding="utf-8"))
    report = _adjusted_report(source="baostock", revision="baostock-adjusted-v1")
    result = BaostockAdjustedPriceAdapter(gate=IndustryCapabilityGate((report,))).normalize(
        fixture["adjustedPrices"], as_of=AS_OF
    )
    assert result.status == "ok"
    assert result.rows[0].adjusted_close == 10.5
    assert result.rows[0].original_amount == 100000000
    assert result.rows[0].original_close == 5.25


def test_adjusted_price_market_gap_and_mixed_date_fail_closed() -> None:
    fixture = json.loads((FIXTURES / "capability-inputs.json").read_text(encoding="utf-8"))
    partial = _adjusted_report(
        source="baostock",
        revision="baostock-adjusted-v1",
        market_coverage={"sh": True, "sz": True, "bj": False},
    )
    adapter = BaostockAdjustedPriceAdapter(gate=IndustryCapabilityGate((partial,)))
    with pytest.raises(IndustryImportError, match="bj coverage"):
        adapter.normalize(fixture["adjustedPrices"], as_of=AS_OF)

    mootdx = _adjusted_report(source="mootdx", revision="mootdx-adjusted-v1")
    bad_rows = [dict(fixture["adjustedPrices"][0], asOf="2026-08-27")]
    with pytest.raises(IndustryImportError, match="date mismatch"):
        MootdxAdjustedPriceAdapter(gate=IndustryCapabilityGate((mootdx,))).normalize(bad_rows, as_of=AS_OF)

    duplicate = [dict(fixture["adjustedPrices"][0]), dict(fixture["adjustedPrices"][0])]
    with pytest.raises(IndustryImportError, match="duplicate"):
        BaostockAdjustedPriceAdapter(gate=IndustryCapabilityGate((_adjusted_report(source="baostock", revision="baostock-adjusted-v1"),))).normalize(
            duplicate,
            as_of=AS_OF,
        )


def test_fixed_benchmark_is_same_date_equal_weight_and_excludes_missing_price() -> None:
    rows = json.loads((FIXTURES / "capability-inputs.json").read_text(encoding="utf-8"))["adjustedPrices"]
    result = BenchmarkHistoryAdapter(gate=IndustryCapabilityGate((_benchmark_report(),))).aggregate(rows, as_of=AS_OF)
    assert result.benchmark_id == "ordinary-a-share-equal-weight-v1"
    assert result.return_value == pytest.approx(0.05)
    assert result.eligible_count == 2
    assert result.excluded_count == 1


def test_benchmark_rejects_mixed_date_and_unapproved_identity() -> None:
    rows = json.loads((FIXTURES / "capability-inputs.json").read_text(encoding="utf-8"))["adjustedPrices"]
    mixed = [dict(rows[0], asOf="2026-08-27")]
    with pytest.raises(IndustryImportError, match="date mismatch"):
        BenchmarkHistoryAdapter(gate=IndustryCapabilityGate((_benchmark_report(),))).aggregate(mixed, as_of=AS_OF)
    with pytest.raises(CapabilityGateError, match="missing"):
        BenchmarkHistoryAdapter(gate=IndustryCapabilityGate()).aggregate(rows, as_of=AS_OF)


def test_probe_dry_run_has_zero_network_and_writes_only_redacted_plan(tmp_path: Path) -> None:
    calls = []
    output = tmp_path / "probe.json"
    payload = run_industry_capability_probe(
        dataset="stock-adjusted-price",
        source="baostock",
        revision="baostock-adjusted-v1",
        as_of=AS_OF,
        output=output,
        allow_real=False,
        probe=lambda value: calls.append(value),  # type: ignore[arg-type]
    )
    assert payload["networkCalls"] == 0
    assert payload["formalWrites"] == 0
    assert calls == []
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "dry-run"


def test_probe_requires_flag_environment_after_market_and_configured_adapter(tmp_path: Path) -> None:
    common = {
        "dataset": "stock-adjusted-price",
        "source": "baostock",
        "revision": "baostock-adjusted-v1",
        "as_of": AS_OF,
        "output": tmp_path / "probe.json",
        "allow_real": True,
    }
    with pytest.raises(IndustryProbeError, match="environment gate"):
        run_industry_capability_probe(**common, now=AFTER_MARKET, environ={})
    with pytest.raises(IndustryProbeError, match="after market"):
        run_industry_capability_probe(**common, now=DURING_MARKET, environ={"MARKET_ENVIRONMENT_INDUSTRY_PROBE_ALLOW_REAL": "1"})
    with pytest.raises(IndustryProbeError, match="no provider-neutral"):
        run_industry_capability_probe(**common, now=AFTER_MARKET, environ={"MARKET_ENVIRONMENT_INDUSTRY_PROBE_ALLOW_REAL": "1"})


def test_authorized_probe_calls_adapter_once_and_never_formally_writes(tmp_path: Path) -> None:
    calls: list[date] = []
    report = _adjusted_report(source="baostock", revision="baostock-adjusted-v1")
    payload = run_industry_capability_probe(
        dataset=report.dataset,
        source=report.source,
        revision=report.revision,
        as_of=AS_OF,
        output=tmp_path / "probe.json",
        allow_real=True,
        probe=lambda value: calls.append(value) or report.to_dict(),
        now=AFTER_MARKET,
        environ={"MARKET_ENVIRONMENT_INDUSTRY_PROBE_ALLOW_REAL": "1"},
    )
    assert calls == [AS_OF]
    assert payload["networkCalls"] == 1
    assert payload["formalWrites"] == 0
    assert payload["report"]["checksum"] == report.checksum


def test_cli_industry_probe_is_dry_run_by_default(tmp_path: Path, capsys) -> None:
    output = tmp_path / "probe.json"
    code = market_cli.main(
        [
            "industry-capability-probe",
            "--dataset", "stock-adjusted-price",
            "--source", "baostock",
            "--revision", "baostock-adjusted-v1",
            "--as-of", AS_OF.isoformat(),
            "--output", str(output),
        ]
    )
    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["networkCalls"] == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry-run"
