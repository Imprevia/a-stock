"""Tests for the ``sectors-html real-probe`` CLI subcommand.

Dry-run MUST refuse to issue any HTTP request. The probe output MUST never
contain a raw response body, a token, a cookie, or an authorization header.
The capability promotion is intentionally out of scope for this test and
remains a manually authorized operational step.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.market_environment.cli import build_parser


def _invoke_probe_cli(argv, monkeypatch=None):
    """Invoke the CLI parser without running main(); this avoids the live network path."""
    parser = build_parser()
    return parser.parse_args(argv)


def test_dry_run_parser_accepts_sina_html_source(tmp_path: Path) -> None:
    args = _invoke_probe_cli(
        [
            "sectors-html",
            "real-probe",
            "--source",
            "sina-html",
            "--as-of",
            "2026-10-09",
            "--output",
            str(tmp_path / "probe.json"),
        ]
    )
    assert args.command == "sectors-html"
    assert args.sectors_html_command == "real-probe"
    assert args.source == "sina-html"


def test_dry_run_parser_accepts_xueqiu_html_source(tmp_path: Path) -> None:
    args = _invoke_probe_cli(
        [
            "sectors-html",
            "real-probe",
            "--source",
            "xueqiu-html",
            "--as-of",
            "2026-10-09",
            "--output",
            str(tmp_path / "probe.json"),
        ]
    )
    assert args.source == "xueqiu-html"


def test_parser_rejects_unknown_source(tmp_path: Path) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "sectors-html",
                "real-probe",
                "--source",
                "tencent-html",
                "--as-of",
                "2026-10-09",
                "--output",
                str(tmp_path / "probe.json"),
            ]
        )


def _run_dry_run_probe(source: str, output: Path) -> dict:
    from src.market_environment.cli import _run_sectors_html_real_probe

    return _run_sectors_html_real_probe(
        as_of=__import__("datetime").date(2026, 10, 9),
        source=source,
        allow_real=False,
    )


def test_dry_run_payload_status(tmp_path: Path) -> None:
    payload = _run_dry_run_probe("sina-html", tmp_path / "probe.json")
    assert payload["status"] == "dry-run"
    assert any("dry-run" in warning for warning in payload["warnings"])


def test_dry_run_payload_never_contains_credentials(tmp_path: Path) -> None:
    payload = _run_dry_run_probe("sina-html", tmp_path / "probe.json")
    raw = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in (
        "token",
        "cookie",
        "authorization",
        "secret",
        "password",
        "html body",
    ):
        assert forbidden not in raw or "fixtureFootprint" in payload and forbidden == "fixtureFootprint", (
            f"dry-run probe MUST NOT include {forbidden!r}; got payload: {payload}"
        )


def test_dry_run_records_zero_transports(tmp_path: Path) -> None:
    payload = _run_dry_run_probe("sina-html", tmp_path / "probe.json")
    assert payload["transports"] == []
    assert payload["rateLimitEvidence"]["transports"] == 0
