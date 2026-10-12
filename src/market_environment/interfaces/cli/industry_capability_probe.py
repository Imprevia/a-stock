"""Isolated, fail-closed CLI helpers for industry capability probes."""

from __future__ import annotations

import os
import json
from collections.abc import Callable, Mapping
from datetime import date, datetime, time as clock_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ...domain.models import IndustryCapabilityReport


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PROBE_ENV = "MARKET_ENVIRONMENT_INDUSTRY_PROBE_ALLOW_REAL"


class IndustryProbeError(RuntimeError):
    """A real probe was not authorized or its evidence was unsafe."""


def is_after_market(now: datetime | None = None) -> bool:
    current = now or datetime.now(_SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_SHANGHAI)
    current = current.astimezone(_SHANGHAI)
    return current.weekday() < 5 and current.time() >= clock_time(15, 30)


def run_industry_capability_probe(
    *,
    dataset: str,
    source: str,
    revision: str,
    as_of: date,
    output: str | Path,
    allow_real: bool,
    probe: Callable[[date], Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Write a redacted report; do zero I/O unless every real-probe gate passes."""

    values = environ if environ is not None else os.environ
    if not allow_real:
        payload = {
            "status": "dry-run",
            "dataset": dataset,
            "source": source,
            "revision": revision,
            "asOf": as_of.isoformat(),
            "networkCalls": 0,
            "formalWrites": 0,
            "warning": "pass --allow-real and the explicit environment gate after market close",
        }
        Path(output).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return payload
    if values.get(_PROBE_ENV) != "1":
        raise IndustryProbeError(f"real-probe environment gate requires {_PROBE_ENV}=1")
    if not is_after_market(now):
        raise IndustryProbeError("industry capability real probe is allowed only after market close")
    if probe is None:
        raise IndustryProbeError("no provider-neutral probe adapter is configured")

    raw = probe(as_of)
    report = IndustryCapabilityReport.from_dict(raw)
    if (report.dataset, report.source, report.revision) != (dataset, source, revision):
        raise IndustryProbeError("probe report identity does not match the requested capability")
    payload = {
        "status": report.status,
        "asOf": as_of.isoformat(),
        "networkCalls": 1,
        "formalWrites": 0,
        "report": report.redacted_dict(),
    }
    Path(output).write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return payload


__all__ = ["IndustryProbeError", "is_after_market", "run_industry_capability_probe"]
