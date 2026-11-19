"""Contract identity for the active-industry scan Skill.

Pure functions only: no I/O except reading the clock, which is injectable so
tests stay deterministic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

SCHEMA_VERSION = "1.0"
RULE_VERSION = "active-industry-scan-v1"
REPORT_ID_PREFIX = "ais"


def _effective(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(tz=SHANGHAI)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=SHANGHAI)
    return moment.astimezone(SHANGHAI)


def make_report_id(moment: datetime, *, nonce: str = "") -> str:
    """Build a stable identifier for one run.

    The id is derived from the run instant down to the second plus an optional
    caller-supplied nonce.  Two runs started in the same second differ only if
    the caller distinguishes them, which is the intended trade-off: the id is
    meant to correlate a JSON file with its Markdown render, not to be a UUID.
    """

    stamp = _effective(moment).strftime("%Y%m%dT%H%M%S")
    digest = hashlib.sha256(f"{stamp}|{nonce}".encode("utf-8")).hexdigest()[:8]
    return f"{REPORT_ID_PREFIX}-{stamp}-{digest}"


@dataclass(frozen=True)
class Contract:
    """The identity block every result carries."""

    schema_version: str
    rule_version: str
    report_id: str
    generated_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "schemaVersion": self.schema_version,
            "ruleVersion": self.rule_version,
            "reportId": self.report_id,
            "generatedAt": self.generated_at,
        }


def build_contract(
    moment: datetime | None = None,
    *,
    nonce: str = "",
) -> Contract:
    """Assemble the identity block for one run."""

    effective = _effective(moment)
    return Contract(
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        report_id=make_report_id(effective, nonce=nonce),
        generated_at=effective.isoformat(timespec="seconds"),
    )