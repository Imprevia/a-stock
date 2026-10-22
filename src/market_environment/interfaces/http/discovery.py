"""Pure in-memory AI discovery rendering and deterministic OpenAPI checks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


V2_PREFIX = "/api/v2/market-environment"
V2_TAG = "AI market data v2"
RESOURCE_RESPONSE = "#/components/schemas/V2Envelope_dict_str__Any__"
PAGE_RESPONSE = "#/components/schemas/V2PaginatedEnvelope_dict_str__Any__"

_CONDITIONAL_PARAMETERS = ("revision", "If-Match", "If-None-Match")
_HISTORY_PARAMETERS = ("start_date", "end_date", "limit", "cursor")
_PAGE_PARAMETERS = ("limit", "cursor")


@dataclass(frozen=True, slots=True)
class DiscoveryOperationContract:
    operation_id: str
    parameters: tuple[str, ...]
    response_ref: str
    limit: tuple[int, int] | None = None


def _resource(operation_id: str, *parameters: str) -> DiscoveryOperationContract:
    return DiscoveryOperationContract(
        operation_id=operation_id,
        parameters=tuple(parameters) + _CONDITIONAL_PARAMETERS,
        response_ref=RESOURCE_RESPONSE,
    )


def _page(
    operation_id: str,
    *parameters: str,
    limit: tuple[int, int],
) -> DiscoveryOperationContract:
    return DiscoveryOperationContract(
        operation_id=operation_id,
        parameters=tuple(parameters) + _CONDITIONAL_PARAMETERS,
        response_ref=PAGE_RESPONSE,
        limit=limit,
    )


# Curated public contract shared by rendering and the drift gate. It contains
# no live values, credentials, provider headers, or persistence details.
DISCOVERY_CONTRACTS: Mapping[str, DiscoveryOperationContract] = {
    f"{V2_PREFIX}/{{as_of}}/overview": _resource("getV2MarketOverview", "as_of"),
    f"{V2_PREFIX}/{{as_of}}/indices": _resource("listV2MarketIndices", "as_of"),
    f"{V2_PREFIX}/{{as_of}}/indices/{{code}}": _resource(
        "getV2MarketIndex", "as_of", "code"
    ),
    f"{V2_PREFIX}/{{as_of}}/indices/{{code}}/history": _page(
        "listV2MarketIndexHistory", "as_of", "code", *_HISTORY_PARAMETERS, limit=(60, 250)
    ),
    f"{V2_PREFIX}/{{as_of}}/breadth": _resource("getV2MarketBreadth", "as_of"),
    f"{V2_PREFIX}/{{as_of}}/breadth/history": _page(
        "listV2MarketBreadthHistory", "as_of", *_HISTORY_PARAMETERS, limit=(60, 250)
    ),
    f"{V2_PREFIX}/{{as_of}}/limits": _resource("getV2MarketLimits", "as_of"),
    f"{V2_PREFIX}/{{as_of}}/limits/evidence": _resource(
        "getV2MarketLimitsEvidence", "as_of"
    ),
    f"{V2_PREFIX}/{{as_of}}/limits/history": _page(
        "listV2MarketLimitsHistory", "as_of", *_HISTORY_PARAMETERS, limit=(60, 250)
    ),
    f"{V2_PREFIX}/{{as_of}}/limits/pools/{{pool_type}}": _page(
        "listV2MarketLimitsPool", "as_of", "pool_type", *_PAGE_PARAMETERS, limit=(20, 100)
    ),
    f"{V2_PREFIX}/{{as_of}}/sectors/rankings": _page(
        "listV2MarketSectorRankings", "as_of", "tag", *_PAGE_PARAMETERS, limit=(20, 100)
    ),
    f"{V2_PREFIX}/{{as_of}}/sectors/turnover": _page(
        "listV2MarketSectorTurnover", "as_of", *_PAGE_PARAMETERS, limit=(20, 100)
    ),
    f"{V2_PREFIX}/{{as_of}}/sectors/breadth": _page(
        "listV2MarketSectorBreadth", "as_of", *_PAGE_PARAMETERS, limit=(20, 100)
    ),
    f"{V2_PREFIX}/{{as_of}}/sectors/analysis": _resource(
        "getV2MarketSectorAnalysis", "as_of"
    ),
    f"{V2_PREFIX}/{{as_of}}/active-direction": _page(
        "listV2MarketActiveDirection", "as_of", *_PAGE_PARAMETERS, limit=(20, 100)
    ),
    f"{V2_PREFIX}/{{as_of}}/active-direction/workbench": _resource(
        "getV2MarketActiveDirectionWorkbench", "as_of"
    ),
    f"{V2_PREFIX}/{{as_of}}/events": _page(
        "listV2MarketEvents", "as_of", *_PAGE_PARAMETERS, limit=(20, 100)
    ),
    f"{V2_PREFIX}/{{as_of}}/assessment": _resource("getV2MarketAssessment", "as_of"),
    f"{V2_PREFIX}/operations/{{run_id}}": _resource(
        "getV2MarketOperationSummary", "run_id"
    ),
    f"{V2_PREFIX}/operations/{{run_id}}/checkpoints": _page(
        "listV2MarketOperationCheckpoints", "run_id", *_PAGE_PARAMETERS, limit=(50, 200)
    ),
}


class DiscoveryContractError(ValueError):
    """Raised when discovery semantics no longer match canonical OpenAPI."""


class UnsafeDiscoveryContentError(ValueError):
    """Raised before unsafe or live-row-like content can be published."""


def _operation(openapi: Mapping[str, Any], path: str) -> Mapping[str, Any] | None:
    paths = openapi.get("paths")
    if not isinstance(paths, Mapping):
        return None
    methods = paths.get(path)
    if not isinstance(methods, Mapping):
        return None
    value = methods.get("get")
    return value if isinstance(value, Mapping) else None


def _parameter_names(operation: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        parameter["name"]
        for parameter in operation.get("parameters") or ()
        if isinstance(parameter, Mapping) and isinstance(parameter.get("name"), str)
    )


def _response_ref(operation: Mapping[str, Any]) -> str | None:
    try:
        schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    except (KeyError, TypeError):
        return None
    return schema.get("$ref") if isinstance(schema, Mapping) else None


def _limit_contract(operation: Mapping[str, Any]) -> tuple[int, int] | None:
    for parameter in operation.get("parameters") or ():
        if not isinstance(parameter, Mapping) or parameter.get("name") != "limit":
            continue
        schema = parameter.get("schema")
        if not isinstance(schema, Mapping):
            return None
        default = schema.get("default")
        maximum = schema.get("maximum")
        if isinstance(default, int) and isinstance(maximum, int):
            return default, maximum
    return None


def validate_discovery_contract(openapi: Mapping[str, Any]) -> None:
    """Fail deterministically on path/id/parameter/model/limit drift."""

    errors: list[str] = []
    paths = openapi.get("paths") if isinstance(openapi.get("paths"), Mapping) else {}
    tagged_paths = {
        path
        for path, methods in paths.items()
        if isinstance(path, str)
        and path.startswith(V2_PREFIX)
        and isinstance(methods, Mapping)
        and isinstance(methods.get("get"), Mapping)
        and V2_TAG in (methods["get"].get("tags") or ())
    }
    expected_paths = set(DISCOVERY_CONTRACTS)
    for path in sorted(expected_paths - tagged_paths):
        errors.append(f"missing tagged GET path: {path}")
    for path in sorted(tagged_paths - expected_paths):
        errors.append(f"undocumented tagged GET path: {path}")

    for path, expected in DISCOVERY_CONTRACTS.items():
        operation = _operation(openapi, path)
        if operation is None:
            continue
        if operation.get("operationId") != expected.operation_id:
            errors.append(
                f"{path}: operationId {operation.get('operationId')!r} != {expected.operation_id!r}"
            )
        parameters = _parameter_names(operation)
        if parameters != expected.parameters:
            errors.append(f"{path}: parameters {parameters!r} != {expected.parameters!r}")
        response_ref = _response_ref(operation)
        if response_ref != expected.response_ref:
            errors.append(
                f"{path}: response model {response_ref!r} != {expected.response_ref!r}"
            )
        limit = _limit_contract(operation)
        if limit != expected.limit:
            errors.append(f"{path}: limit {limit!r} != {expected.limit!r}")

    if errors:
        raise DiscoveryContractError("discovery/OpenAPI drift:\n- " + "\n- ".join(errors))


_UNSAFE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("authorization header", re.compile(r"(?i)authorization\s*:")),
    ("bearer credential", re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{8,}")),
    ("API key", re.compile(r"(?i)(?:x-api-key|api[_-]?key)\s*[:=]\s*\S+")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("presigned URL", re.compile(r"(?i)[?&](?:x-amz-signature|signature|access_token)=")),
    ("embedded security row", re.compile(r'(?i)["\'](?:code|symbol|thscode)["\']\s*:\s*["\']?\d{6}')),
    ("embedded live-row field", re.compile(r'(?i)["\'](?:close|amount|changePct)["\']\s*:')),
)


def validate_discovery_content(text: str) -> None:
    for label, pattern in _UNSAFE_PATTERNS:
        if pattern.search(text):
            raise UnsafeDiscoveryContentError(f"discovery contains forbidden {label}")


def _validated_operations(
    openapi: Mapping[str, Any],
) -> Sequence[tuple[str, DiscoveryOperationContract]]:
    validate_discovery_contract(openapi)
    return tuple(DISCOVERY_CONTRACTS.items())


def _finish(lines: Sequence[str]) -> str:
    text = "\n".join(lines) + "\n"
    validate_discovery_content(text)
    return text


def render_llms_txt(openapi: Mapping[str, Any]) -> str:
    operations = _validated_operations(openapi)
    lines = [
        "# a-stock Market Environment API",
        "",
        "AI-friendly, read-only, provider-free, exact-date market evidence.",
        "Start with GET /api/v2/market-environment/{as_of}/overview.",
        "Use returned links and snapshotRevision to request only the resource you need.",
        "",
        "- Full guide: /llms-full.txt",
        "- Canonical OpenAPI: /openapi.json",
        "",
        "## Resources",
    ]
    lines.extend(f"- GET {path} ({contract.operation_id})" for path, contract in operations)
    return _finish(lines)


def render_llms_full_txt(openapi: Mapping[str, Any]) -> str:
    operations = _validated_operations(openapi)
    lines = [
        "# a-stock Market Environment API — Full AI Guide",
        "",
        "Canonical structural contract: /openapi.json",
        "Compact index: /llms.txt",
        "",
        "## Recommended workflow",
        "",
        "1. Replace {as_of} with an explicit YYYY-MM-DD and request GET /api/v2/market-environment/{as_of}/overview.",
        "2. Preserve asOf, snapshotRevision, quality and links.",
        "3. Pass revision=<snapshotRevision> or If-Match on follow-up reads.",
        "4. Follow pagination.nextCursor until null; restart from overview on HTTP 409.",
        "5. Treat missing, insufficient, degraded and failed-retained as evidence states; never replace null with zero or another date.",
        "",
        "## Exact-date and quality semantics",
        "",
        "All GETs are provider-free and read local exact-date materialized evidence only.",
        "An unknown exact date returns 404; future dates and closed selector violations return 422.",
        "If-None-Match with the current ETag returns 304. A stale revision or cursor returns 409.",
        "Discovery documents contain contracts and examples, not live market rows or provider credentials.",
        "",
        "## Pagination limits",
        "",
        "- Index, breadth and limits histories: default 60, maximum 250.",
        "- Limits pools, sector lists, active direction and events: default 20, maximum 100.",
        "- Operation checkpoints: default 50, maximum 200.",
        "",
        "## Endpoints",
    ]
    for path, contract in operations:
        lines.extend(
            [
                "",
                f"### GET {path}",
                "",
                f"operationId: {contract.operation_id}",
                f"parameters: {', '.join(contract.parameters)}",
                f"responseModel: {contract.response_ref.rsplit('/', 1)[-1]}",
            ]
        )
        if contract.limit is not None:
            lines.append(
                f"paginationLimit: default {contract.limit[0]}, maximum {contract.limit[1]}"
            )
    lines.extend(
        [
            "",
            "## Existing linked resources",
            "",
            "Sector responses may link to the existing bounded THS catalog and single-code bars APIs. Their contracts remain in /openapi.json and are not duplicated here.",
        ]
    )
    return _finish(lines)


__all__ = [
    "DISCOVERY_CONTRACTS",
    "DiscoveryContractError",
    "UnsafeDiscoveryContentError",
    "render_llms_full_txt",
    "render_llms_txt",
    "validate_discovery_content",
    "validate_discovery_contract",
]
