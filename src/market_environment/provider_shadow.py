"""Non-destructive, dataset-aware provider shadow comparisons.

The shadow path compares two already-normalized provider results.  It never
mutates either input and deliberately returns a small JSON-compatible report;
raw provider rows, request arguments and credentials are not copied into the
report.  Collection code can store the returned mapping in ``timings_json``
without changing the snapshot schema.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


SHADOW_STATUSES = frozenset({"match", "mismatch", "degraded", "insufficient"})
_FAILED_QUALITY = frozenset({"failed", "missing", "insufficient", "ineligible"})
_DEGRADED_QUALITY = frozenset({"partial", "fallback", "degraded"})
_DEFAULT_TOLERANCES: dict[str, dict[str, float]] = {
    "core": {"close": 0.01, "open": 0.01, "high": 0.01, "low": 0.01, "amount": 1.0, "changePct": 0.01},
    "breadth": {"count": 0.0, "advanceRatio": 0.0001, "medianReturn": 0.01},
    "activeDirection": {"amount": 1.0, "changePct": 0.01, "closePosition": 0.0001},
    "sectors": {"changePct": 0.01, "amount": 1.0, "mainNet": 1.0, "mainNetPct": 0.01},
    "limits": {"count": 0.0},
}
_MAX_IDENTITIES = 100
_MAX_DIFFERENCES = 100
_SENSITIVE_TEXT = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|authorization|cookie|credential)\s*[:=]\s*[^; ,]+")


@dataclass(frozen=True)
class ShadowComparator:
    """Compare two provider payloads while retaining no provider state."""

    tolerances: Mapping[str, float] | None = None
    max_differences: int = _MAX_DIFFERENCES

    def compare(
        self,
        dataset: str,
        formal: Any,
        shadow: Any,
        *,
        formal_revision: str | None = None,
        shadow_revision: str | None = None,
        as_of: date | datetime | str | None = None,
    ) -> dict[str, Any]:
        return _compare(
            dataset,
            formal,
            shadow,
            formal_revision=formal_revision,
            shadow_revision=shadow_revision,
            as_of=as_of,
            tolerances=self.tolerances,
            max_differences=max(1, int(self.max_differences)),
        )


def compare_shadow(
    dataset: str,
    formal: Any,
    shadow: Any,
    *,
    formal_revision: str | None = None,
    shadow_revision: str | None = None,
    as_of: date | datetime | str | None = None,
    tolerances: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Return a redacted comparison report for one market dataset.

    ``formal`` and ``shadow`` may be existing payload dictionaries, a
    ``FuyaoMarketResult``-like object, or (for core) the mapping returned by
    ``FuyaoMarketAdapter.normalize_core``.  The function is intentionally
    side-effect free so a mismatch cannot alter a formal snapshot.
    """

    return ShadowComparator(tolerances=tolerances).compare(
        dataset,
        formal,
        shadow,
        formal_revision=formal_revision,
        shadow_revision=shadow_revision,
        as_of=as_of,
    )


# Descriptive alias for callers that prefer an explicit provider-oriented name.
compare_provider_payloads = compare_shadow
compare_dataset = compare_shadow


def _compare(
    dataset: str,
    formal: Any,
    shadow: Any,
    *,
    formal_revision: str | None,
    shadow_revision: str | None,
    as_of: date | datetime | str | None,
    tolerances: Mapping[str, float] | None,
    max_differences: int,
) -> dict[str, Any]:
    dataset = str(dataset)
    normalized_formal = _unwrap(formal)
    normalized_shadow = _unwrap(shadow)
    formal_quality = _quality(normalized_formal)
    shadow_quality = _quality(normalized_shadow)
    warnings: list[str] = []
    warnings.extend(_quality_warnings("formal", formal_quality))
    warnings.extend(_quality_warnings("shadow", shadow_quality))
    if formal_quality.get("warning"):
        warnings.append(f"formal: {formal_quality['warning']}")
    if shadow_quality.get("warning"):
        warnings.append(f"shadow: {shadow_quality['warning']}")

    inferred_as_of = _date_text(as_of) or _date_text(formal_quality.get("asOf")) or _date_text(shadow_quality.get("asOf"))
    report: dict[str, Any] = {
        "dataset": dataset,
        "asOf": inferred_as_of,
        "formalProviderRevision": _revision(formal, formal_revision),
        "shadowProviderRevision": _revision(shadow, shadow_revision),
        "status": "insufficient",
        "match": None,
        "formalCount": 0,
        "shadowCount": 0,
        "comparedCount": 0,
        "identityMissing": {"formal": [], "shadow": []},
        "orderingDifferences": [],
        "differences": [],
        "tolerances": dict(_DEFAULT_TOLERANCES.get(dataset, {})),
        "warnings": _unique(warnings),
    }
    if tolerances:
        report["tolerances"].update({str(key): _number(value) or 0.0 for key, value in tolerances.items()})
    if formal_quality.get("status") in _FAILED_QUALITY or shadow_quality.get("status") in _FAILED_QUALITY:
        # A provider result marked missing/failed is not a zero-valued result.
        report["status"] = "insufficient" if not _has_comparable_content(normalized_formal, dataset) or not _has_comparable_content(normalized_shadow, dataset) else "degraded"
        report["warnings"] = _unique([*report["warnings"], "one provider result is not comparable"])
        return report

    formal_date = _date_text(formal_quality.get("asOf"))
    shadow_date = _date_text(shadow_quality.get("asOf"))
    if formal_date and shadow_date and formal_date != shadow_date:
        report["differences"].append(
            {
                "identity": "dataset",
                "field": "asOf",
                "formal": formal_date,
                "shadow": shadow_date,
                "delta": None,
                "tolerance": 0,
            }
        )
        report["warnings"] = _unique([*report["warnings"], "provider results report different asOf dates"])

    if dataset == "breadth":
        _compare_breadth(report, normalized_formal, normalized_shadow)
    else:
        formal_items = _items(dataset, normalized_formal)
        shadow_items = _items(dataset, normalized_shadow)
        _compare_items(report, dataset, formal_items, shadow_items, max_differences=max_differences)

    report["warnings"] = _unique(report["warnings"])
    has_degraded_quality = formal_quality.get("status") in _DEGRADED_QUALITY or shadow_quality.get("status") in _DEGRADED_QUALITY
    if report["differences"] and report["status"] == "match":
        report["status"] = "mismatch"
        report["match"] = False
    if report["status"] == "match" and has_degraded_quality:
        report["status"] = "degraded"
        report["match"] = False
        report["warnings"] = _unique([*report["warnings"], "provider quality is degraded despite comparable values"])
    return report


def _compare_breadth(report: dict[str, Any], formal: Any, shadow: Any) -> None:
    fields = ("advanceCount", "declineCount", "flatCount", "validCount")
    numeric = ("advanceRatio", "medianReturn")
    formal_count = _metric(formal, "validCount")
    shadow_count = _metric(shadow, "validCount")
    report["formalCount"] = _integer_or_zero(formal_count)
    report["shadowCount"] = _integer_or_zero(shadow_count)
    report["comparedCount"] = 1 if formal_count is not None and shadow_count is not None else 0
    for field in fields:
        left, right = _metric(formal, field), _metric(shadow, field)
        if left is None or right is None:
            continue
        _add_difference(report, "market", field, left, right, report["tolerances"].get("count", 0.0))
    for field in numeric:
        left, right = _metric(formal, field), _metric(shadow, field)
        if left is None or right is None:
            continue
        _add_difference(report, "market", field, left, right, report["tolerances"].get(field, 0.0))
    if report["comparedCount"] == 0:
        report["status"] = "insufficient"
        report["match"] = None
    else:
        report["status"] = "mismatch" if report["differences"] else "match"
        report["match"] = report["status"] == "match"


def _compare_items(report: dict[str, Any], dataset: str, formal: list[dict[str, Any]], shadow: list[dict[str, Any]], *, max_differences: int) -> None:
    report["formalCount"] = len(formal)
    report["shadowCount"] = len(shadow)
    formal_map = {item["identity"]: item for item in formal if item.get("identity")}
    shadow_map = {item["identity"]: item for item in shadow if item.get("identity")}
    formal_ids, shadow_ids = set(formal_map), set(shadow_map)
    missing_formal = sorted(shadow_ids - formal_ids)[:_MAX_IDENTITIES]
    missing_shadow = sorted(formal_ids - shadow_ids)[:_MAX_IDENTITIES]
    report["identityMissing"] = {"formal": missing_formal, "shadow": missing_shadow}
    report["comparedCount"] = len(formal_ids & shadow_ids)
    formal_order = [item["identity"] for item in formal if item.get("identity")]
    shadow_order = [item["identity"] for item in shadow if item.get("identity")]
    if dataset in {"core", "activeDirection", "sectors"}:
        for identity in sorted(formal_ids & shadow_ids):
            left_rank = formal_order.index(identity) + 1
            right_rank = shadow_order.index(identity) + 1
            if left_rank != right_rank:
                report["orderingDifferences"].append({"identity": identity, "formalRank": left_rank, "shadowRank": right_rank})
                if len(report["orderingDifferences"]) >= max_differences:
                    break
    for identity in sorted(formal_ids & shadow_ids):
        left, right = formal_map[identity], shadow_map[identity]
        fields = _fields_for(dataset, left, right)
        for field in fields:
            left_value, right_value = left.get(field), right.get(field)
            if left_value is None or right_value is None:
                if left_value != right_value:
                    _add_difference(report, identity, field, left_value, right_value, report["tolerances"].get(field, 0.0), max_differences=max_differences)
                continue
            tolerance = report["tolerances"].get(field, 0.0)
            _add_difference(report, identity, field, left_value, right_value, tolerance, max_differences=max_differences)
    if missing_formal or missing_shadow or report["orderingDifferences"] or report["differences"]:
        report["status"] = "mismatch"
        report["match"] = False
    elif report["comparedCount"] == 0:
        report["status"] = "insufficient"
        report["match"] = None
    else:
        report["status"] = "match"
        report["match"] = True


def _fields_for(dataset: str, left: Mapping[str, Any], right: Mapping[str, Any]) -> tuple[str, ...]:
    if dataset == "core":
        return ("close", "open", "high", "low", "amount", "changePct")
    if dataset == "activeDirection":
        return ("amount", "changePct", "closePosition", "industry")
    if dataset == "sectors":
        return ("name", "changePct", "amount", "mainNet", "mainNetPct", "upCount", "downCount", "leader")
    keys = tuple(sorted((set(left) | set(right)) - {"identity", "rank"}))
    return keys


def _items(dataset: str, payload: Any) -> list[dict[str, Any]]:
    payload = _unwrap(payload)
    if dataset == "core":
        raw = payload.get("indices") if isinstance(payload, Mapping) else None
        if raw is None and isinstance(payload, Mapping):
            raw = [
                {"code": key, "_adapterResult": value}
                for key, value in payload.items()
                if str(key).lower() in {"sh000001", "sz399001", "sz399006", "sh000300", "sh000905"}
            ]
        rows = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else []
        result: list[dict[str, Any]] = []
        for row in rows:
            item = _unwrap(row)
            if not isinstance(item, Mapping):
                continue
            adapter_result = item.get("_adapterResult")
            adapter_payload = _unwrap(adapter_result)
            if isinstance(adapter_payload, Mapping) and adapter_payload:
                item = {**item, **adapter_payload}
            history = item.get("history") or item.get("bars") or []
            latest_raw = history[-1] if isinstance(history, Sequence) and not isinstance(history, (str, bytes)) and history else item
            latest = _unwrap(latest_raw)
            if not isinstance(latest, Mapping) or not latest:
                latest = {
                    key: getattr(latest_raw, key, None)
                    for key in ("date", "close", "open", "high", "low", "amount")
                }
            latest = latest if isinstance(latest, Mapping) else item
            identity = _canonical_core_identity(item.get("code") or item.get("identity"))
            result.append({"identity": identity, **{key: _safe_value(latest.get(key)) for key in ("close", "open", "high", "low", "amount")}, "changePct": _safe_value(item.get("changePct"))})
        return result
    key = "topStocks" if dataset == "activeDirection" else "rows"
    raw = payload.get(key) if isinstance(payload, Mapping) else None
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    result = []
    for index, row in enumerate(raw):
        item = _unwrap(row)
        if not isinstance(item, Mapping):
            continue
        raw_identity = item.get("code") or item.get("identity") or item.get("ticker") or item.get("symbol")
        identity = _canonical_identity(raw_identity)
        if not identity:
            continue
        normalized = {"identity": identity, "rank": _safe_value(item.get("rank", index + 1))}
        for field in ("name", "changePct", "amount", "closePosition", "industry", "mainNet", "mainNetPct", "upCount", "downCount", "leader"):
            normalized[field] = _safe_value(item.get(field))
        result.append(normalized)
    return result


def _unwrap(value: Any) -> Any:
    if hasattr(value, "as_dict") and callable(value.as_dict):
        try:
            return value.as_dict()
        except Exception:
            return {}
    if hasattr(value, "payload") and isinstance(value.payload, Mapping):
        return dict(value.payload)
    if isinstance(value, Mapping):
        return value
    return {}


def _quality(value: Any) -> dict[str, Any]:
    value = _unwrap(value)
    quality = value.get("quality") if isinstance(value, Mapping) else None
    if isinstance(quality, Mapping):
        return dict(quality)
    if hasattr(value, "quality") and isinstance(value.quality, Mapping):
        return dict(value.quality)
    return {}


def _revision(value: Any, override: str | None) -> str | None:
    if override is not None:
        return _redact_text(str(override))
    quality = _quality(value)
    for key in ("providerRevision", "provider_revision", "sourceRevision", "source_revision", "revision", "source", "provider"):
        if quality.get(key):
            return _redact_text(str(quality[key]))
    return None


def _quality_warnings(label: str, quality: Mapping[str, Any]) -> list[str]:
    status = str(quality.get("status") or "")
    if status in _FAILED_QUALITY:
        return [f"{label} provider quality status is {status}"]
    return []


def _has_comparable_content(value: Any, dataset: str) -> bool:
    return bool(_items(dataset, value)) if dataset != "breadth" else _metric(value, "validCount") is not None


def _metric(value: Any, field: str) -> float | int | None:
    value = _unwrap(value)
    if not isinstance(value, Mapping):
        return None
    quality = value.get("quality")
    candidate = value.get(field)
    if candidate is None and isinstance(quality, Mapping):
        candidate = quality.get(field)
    return _number(candidate)


def _canonical_identity(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if "." in text:
        text = text.split(".", 1)[0]
    if len(text) == 8 and text[:2] in {"SH", "SZ", "BJ"} and text[2:].isdigit():
        text = text[2:]
    if text.isdigit() and len(text) < 6:
        text = text.zfill(6)
    return text


def _canonical_core_identity(value: Any) -> str | None:
    """Normalize index code spellings without confusing SH/SZ namespaces."""

    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if "." in text:
        ticker, exchange = text.split(".", 1)
        if ticker.isdigit() and exchange[:2] in {"SH", "SZ", "BJ"}:
            return f"{exchange[:2].lower()}{ticker.zfill(6)}"
    if len(text) == 8 and text[:2] in {"SH", "SZ", "BJ"} and text[2:].isdigit():
        return text.lower()
    return text.lower()


def _date_text(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if text else None


def _number(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _safe_number(value: Any) -> float | int | None:
    return _number(value)


def _safe_value(value: Any) -> Any:
    number = _number(value)
    if number is not None:
        return int(number) if number.is_integer() else round(number, 8)
    if value is None or isinstance(value, (str, bool)):
        return _redact_text(value) if isinstance(value, str) else value
    return str(value)


def _integer_or_zero(value: Any) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _add_difference(report: dict[str, Any], identity: str, field: str, formal: Any, shadow: Any, tolerance: float, *, max_differences: int = _MAX_DIFFERENCES) -> None:
    left_number, right_number = _number(formal), _number(shadow)
    if left_number is not None and right_number is not None:
        delta = abs(left_number - right_number)
        if delta <= max(0.0, float(tolerance)):
            return
        difference = {"identity": identity, "field": field, "formal": _safe_value(left_number), "shadow": _safe_value(right_number), "delta": _safe_value(delta), "tolerance": _safe_value(tolerance)}
    elif formal == shadow:
        return
    else:
        difference = {"identity": identity, "field": field, "formal": _safe_value(formal), "shadow": _safe_value(shadow), "delta": None, "tolerance": _safe_value(tolerance)}
    if len(report["differences"]) < max_differences:
        report["differences"].append(difference)


def _unique(values: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(_redact_text(str(value)) for value in values if value))


def _redact_text(value: str) -> str:
    return _SENSITIVE_TEXT.sub(lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=[redacted]", value)


__all__ = ["SHADOW_STATUSES", "ShadowComparator", "compare_dataset", "compare_provider_payloads", "compare_shadow"]
