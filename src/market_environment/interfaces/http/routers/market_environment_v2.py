"""Bounded, provider-free market-environment resources for AI clients."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Annotated, Any, Callable, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ....application.ports.v2_market_data import SortKey, V2Page, V2Resource
from ....application.queries.v2_consistency import (
    CursorError,
    StaleCursorRevisionError,
    decode_cursor,
    encode_cursor,
    opaque_snapshot_revision,
)
from ..dependencies import (
    V2MarketEnvironmentQueries,
    get_effective_market_date,
    get_v2_market_queries,
)
from ..schemas.v2 import V2Envelope, V2PaginatedEnvelope
from ..v2_conditional import (
    SnapshotRevisionConflict,
    conditional_not_modified_response,
    format_etag,
    require_snapshot_revision,
    snapshot_revision_conflict_response,
)


router = APIRouter(prefix="/api/v2/market-environment", tags=["AI market data v2"])
PoolType = Literal["limit_up", "limit_down", "failed_limit_up", "promoted"]
SectorTag = Literal["industry", "cn_concept", "region", "tszs"]
EnvelopeModel = V2Envelope[dict[str, Any]]
PageEnvelopeModel = V2PaginatedEnvelope[dict[str, Any]]


def _error(status_code: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, **extra}},
    )


def _validate_as_of(as_of: date, effective_date: date) -> JSONResponse | None:
    if as_of > effective_date:
        return _error(422, "future_date", "as_of 不能晚于当前有效市场日")
    return None


def _public_revision(resource: V2Resource) -> str:
    return opaque_snapshot_revision(resource.component_revision)


def _quality(raw: Mapping[str, Any] | None, *, as_of: date | None) -> dict[str, Any]:
    value = dict(raw or {})
    status = str(value.get("status") or "insufficient")
    status_aliases = {
        "available": "ok",
        "success": "ok",
        "queued": "insufficient",
        "running": "partial",
        "conflict": "degraded",
    }
    status = status_aliases.get(status, status)
    allowed = {
        "ok",
        "partial",
        "fallback",
        "fallback-derived",
        "missing",
        "insufficient",
        "degraded",
        "failed",
        "failed-retained",
        "failed-missing",
        "unverified",
    }
    if status not in allowed:
        status = "insufficient"
    warnings = value.get("warnings")
    if not isinstance(warnings, list):
        warning = value.get("warning")
        warnings = [str(warning)] if warning else []
    refresh_warning = value.get("refreshWarning")
    if refresh_warning and str(refresh_warning) not in warnings:
        warnings = [*warnings, str(refresh_warning)]
    return {
        "status": status,
        "source": value.get("source"),
        "provider": value.get("provider"),
        "actualDate": value.get("actualDate") or value.get("asOf") or as_of,
        "observations": value.get("observations"),
        "cacheState": value.get("cacheState"),
        "isStale": value.get("isStale"),
        "fetchedAt": value.get("fetchedAt") or value.get("snapshotFetchedAt"),
        "evidenceRevision": value.get("evidenceRevision") or value.get("sourceRevision"),
        "checksum": value.get("checksum"),
        "warnings": [str(item) for item in warnings[:50]],
    }


def _as_of(resource: V2Resource) -> date:
    if resource.as_of is not None:
        return resource.as_of
    data = resource.data if isinstance(resource.data, Mapping) else {}
    candidate = data.get("asOf") or data.get("targetDate")
    if candidate:
        return date.fromisoformat(str(candidate))
    return datetime.fromisoformat(resource.generated_at.replace("Z", "+00:00")).date()


def _data(resource: V2Resource) -> dict[str, Any]:
    if isinstance(resource.data, Mapping):
        return dict(resource.data)
    if isinstance(resource.data, Sequence) and not isinstance(
        resource.data, (str, bytes, bytearray)
    ):
        return {"items": [dict(item) for item in resource.data]}
    return {"value": resource.data}


def _precondition(
    resource: V2Resource,
    *,
    revision: str | None,
    if_match: str | None,
    if_none_match: str | None,
) -> tuple[str, Response | None]:
    current = _public_revision(resource)
    try:
        if revision is not None and revision != current:
            raise SnapshotRevisionConflict(revision, current)
        require_snapshot_revision(current, if_match)
    except SnapshotRevisionConflict as conflict:
        return current, snapshot_revision_conflict_response(conflict)
    unchanged = conditional_not_modified_response(current, if_none_match)
    return current, unchanged


def _envelope(
    resource: V2Resource,
    *,
    revision: str,
    links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "asOf": _as_of(resource),
        "generatedAt": resource.generated_at,
        "snapshotRevision": revision,
        "quality": _quality(resource.quality, as_of=resource.as_of),
        "data": _data(resource),
        "links": links or [],
    }


def _resource_response(
    resource: V2Resource | None,
    *,
    revision: str | None,
    if_match: str | None,
    if_none_match: str | None,
    links: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | Response:
    if resource is None:
        return _error(404, "resource_not_found", "所选精确日期或资源没有本地证据")
    current, conditional = _precondition(
        resource,
        revision=revision,
        if_match=if_match,
        if_none_match=if_none_match,
    )
    if conditional is not None:
        return conditional
    payload = _envelope(resource, revision=current, links=links)
    return JSONResponse(jsonable_encoder(payload), headers={"ETag": format_etag(current)})


def _cursor_after(
    cursor: str | None,
    *,
    resource: str,
    scope: Mapping[str, Any],
    filters: Mapping[str, Any],
    revision: str,
) -> SortKey | None:
    if cursor is None:
        return None
    state = decode_cursor(
        cursor,
        expected_resource=resource,
        expected_scope=scope,
        expected_filters=filters,
        current_snapshot_revision=revision,
    )
    return tuple(str(item) for item in state.sort_key)


def _page_response(
    page: V2Page | None,
    *,
    resource_name: str,
    scope: Mapping[str, Any],
    filters: Mapping[str, Any],
    limit: int,
    revision: str | None,
    if_match: str | None,
    if_none_match: str | None,
    links: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | Response:
    if page is None:
        return _error(404, "resource_not_found", "所选精确日期或资源没有本地证据")
    current, conditional = _precondition(
        page.resource,
        revision=revision,
        if_match=if_match,
        if_none_match=if_none_match,
    )
    if conditional is not None:
        return conditional
    payload = _envelope(page.resource, revision=current, links=links)
    items = payload["data"].get("items", [])
    next_cursor = None
    if page.next_sort_key is not None:
        next_cursor = encode_cursor(
            resource=resource_name,
            scope=scope,
            filters=filters,
            sort_key=page.next_sort_key,
            snapshot_revision=current,
        )
    payload["pagination"] = {
        "limit": limit,
        "returned": len(items),
        "hasMore": next_cursor is not None,
        "nextCursor": next_cursor,
    }
    return JSONResponse(jsonable_encoder(payload), headers={"ETag": format_etag(current)})


def _cursor_error(error: CursorError) -> JSONResponse:
    if isinstance(error, StaleCursorRevisionError):
        return _error(
            409,
            error.code,
            str(error),
            requestedSnapshotRevision=error.cursor_revision,
            currentSnapshotRevision=error.current_revision,
        )
    return _error(422, error.code, str(error))


def _links(as_of: date, names: Sequence[str]) -> list[dict[str, Any]]:
    root = f"/api/v2/market-environment/{as_of.isoformat()}"
    return [
        {"relation": "related", "href": f"{root}/{name}", "resource": name}
        for name in names
    ]


@router.get(
    "/operations/{run_id}",
    response_model=EnvelopeModel,
    operation_id="getV2MarketOperationSummary",
)
def operation_summary(
    run_id: str,
    queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)],
    revision: str | None = Query(default=None),
    if_match: str | None = Header(default=None, alias="If-Match"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    return _resource_response(
        queries.operation_summary(run_id),
        revision=revision,
        if_match=if_match,
        if_none_match=if_none_match,
    )


@router.get(
    "/operations/{run_id}/checkpoints",
    response_model=PageEnvelopeModel,
    operation_id="listV2MarketOperationCheckpoints",
)
def operation_checkpoints(
    run_id: str,
    queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)],
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    revision: str | None = Query(default=None),
    if_match: str | None = Header(default=None, alias="If-Match"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    metadata = queries.operation_summary(run_id)
    if metadata is None:
        return _error(404, "resource_not_found", "operation 不存在")
    current = _public_revision(metadata)
    try:
        after = _cursor_after(
            cursor,
            resource="operation_checkpoints",
            scope={"runId": run_id},
            filters={},
            revision=current,
        )
    except CursorError as error:
        return _cursor_error(error)
    return _page_response(
        queries.operation_checkpoints(run_id, after=after, limit=limit),
        resource_name="operation_checkpoints",
        scope={"runId": run_id},
        filters={},
        limit=limit,
        revision=revision,
        if_match=if_match,
        if_none_match=if_none_match,
    )


def _exact_resource(
    as_of: date,
    effective_date: date,
    loader: Callable[[], V2Resource | None],
    *,
    revision: str | None,
    if_match: str | None,
    if_none_match: str | None,
    links: list[dict[str, Any]] | None = None,
):
    invalid = _validate_as_of(as_of, effective_date)
    if invalid is not None:
        return invalid
    try:
        value = loader()
    except ValueError as error:
        return _error(422, "invalid_selector", str(error))
    return _resource_response(
        value,
        revision=revision,
        if_match=if_match,
        if_none_match=if_none_match,
        links=links,
    )


@router.get(
    "/{as_of}/overview",
    response_model=EnvelopeModel,
    operation_id="getV2MarketOverview",
)
def overview(
    as_of: date,
    request: Request,
    queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    revision: str | None = Query(default=None),
    if_match: str | None = Header(default=None, alias="If-Match"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    return _exact_resource(
        as_of,
        effective_date,
        lambda: queries.overview(as_of),
        revision=revision,
        if_match=if_match,
        if_none_match=if_none_match,
        links=_links(
            as_of,
            ("indices", "breadth", "limits", "sectors/rankings", "active-direction", "events", "assessment"),
        ),
    )


@router.get("/{as_of}/indices", response_model=EnvelopeModel, operation_id="listV2MarketIndices")
def indices(
    as_of: date,
    queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    revision: str | None = Query(default=None),
    if_match: str | None = Header(default=None, alias="If-Match"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    return _exact_resource(as_of, effective_date, lambda: queries.indices(as_of), revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/indices/{code}", response_model=EnvelopeModel, operation_id="getV2MarketIndex")
def index_detail(
    as_of: date,
    code: str,
    queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    revision: str | None = Query(default=None),
    if_match: str | None = Header(default=None, alias="If-Match"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    return _exact_resource(as_of, effective_date, lambda: queries.index(as_of, code), revision=revision, if_match=if_match, if_none_match=if_none_match)


def _history_response(
    *,
    as_of: date,
    effective_date: date,
    metadata: V2Resource | None,
    loader: Callable[[SortKey | None], V2Page | None],
    resource_name: str,
    scope: Mapping[str, Any],
    filters: Mapping[str, Any],
    limit: int,
    cursor: str | None,
    revision: str | None,
    if_match: str | None,
    if_none_match: str | None,
):
    invalid = _validate_as_of(as_of, effective_date)
    if invalid is not None:
        return invalid
    if metadata is None:
        return _error(404, "resource_not_found", "所选精确日期或资源没有本地证据")
    current = _public_revision(metadata)
    try:
        after = _cursor_after(cursor, resource=resource_name, scope=scope, filters=filters, revision=current)
        page = loader(after)
    except CursorError as error:
        return _cursor_error(error)
    except ValueError as error:
        return _error(422, "invalid_selector", str(error))
    return _page_response(page, resource_name=resource_name, scope=scope, filters=filters, limit=limit, revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/indices/{code}/history", response_model=PageEnvelopeModel, operation_id="listV2MarketIndexHistory")
def index_history(
    as_of: date,
    code: str,
    queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=60, ge=1, le=250),
    cursor: str | None = Query(default=None),
    revision: str | None = Query(default=None),
    if_match: str | None = Header(default=None, alias="If-Match"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    filters = {"code": code, "startDate": start_date, "endDate": end_date}
    return _history_response(as_of=as_of, effective_date=effective_date, metadata=queries.index(as_of, code), loader=lambda after: queries.index_history(as_of, code, start_date=start_date, end_date=end_date, after=after, limit=limit), resource_name="index_history", scope={"asOf": as_of}, filters=filters, limit=limit, cursor=cursor, revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/breadth", response_model=EnvelopeModel, operation_id="getV2MarketBreadth")
def breadth(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    return _exact_resource(as_of, effective_date, lambda: queries.breadth(as_of), revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/breadth/history", response_model=PageEnvelopeModel, operation_id="listV2MarketBreadthHistory")
def breadth_history(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], start_date: date | None = Query(default=None), end_date: date | None = Query(default=None), limit: int = Query(default=60, ge=1, le=250), cursor: str | None = Query(default=None), revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    filters = {"startDate": start_date, "endDate": end_date}
    return _history_response(as_of=as_of, effective_date=effective_date, metadata=queries.breadth(as_of), loader=lambda after: queries.breadth_history(as_of, start_date=start_date, end_date=end_date, after=after, limit=limit), resource_name="breadth_history", scope={"asOf": as_of}, filters=filters, limit=limit, cursor=cursor, revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/limits", response_model=EnvelopeModel, operation_id="getV2MarketLimits")
def limits(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    return _exact_resource(as_of, effective_date, lambda: queries.limits(as_of), revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/limits/evidence", response_model=EnvelopeModel, operation_id="getV2MarketLimitsEvidence")
def limits_evidence(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    return _exact_resource(as_of, effective_date, lambda: queries.limits_evidence(as_of), revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/limits/history", response_model=PageEnvelopeModel, operation_id="listV2MarketLimitsHistory")
def limits_history(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], start_date: date | None = Query(default=None), end_date: date | None = Query(default=None), limit: int = Query(default=60, ge=1, le=250), cursor: str | None = Query(default=None), revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    filters = {"startDate": start_date, "endDate": end_date}
    return _history_response(as_of=as_of, effective_date=effective_date, metadata=queries.limits(as_of), loader=lambda after: queries.limits_history(as_of, start_date=start_date, end_date=end_date, after=after, limit=limit), resource_name="limits_history", scope={"asOf": as_of}, filters=filters, limit=limit, cursor=cursor, revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/limits/pools/{pool_type}", response_model=PageEnvelopeModel, operation_id="listV2MarketLimitsPool")
def limits_pool(as_of: date, pool_type: PoolType, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None), revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    filters = {"poolType": pool_type}
    return _history_response(as_of=as_of, effective_date=effective_date, metadata=queries.limits(as_of), loader=lambda after: queries.limits_pool(as_of, pool_type, after=after, limit=limit), resource_name="limits_pool", scope={"asOf": as_of}, filters=filters, limit=limit, cursor=cursor, revision=revision, if_match=if_match, if_none_match=if_none_match)


def _sector_page(name: str, as_of: date, effective_date: date, queries: V2MarketEnvironmentQueries, loader: Callable[[SortKey | None], V2Page | None], *, filters: Mapping[str, Any], limit: int, cursor: str | None, revision: str | None, if_match: str | None, if_none_match: str | None):
    links = [
        {"relation": "related", "href": "/api/market-environment/ths/catalog", "resource": "ths-catalog"},
        {"relation": "related", "href": "/api/market-environment/ths/sectors/{thscode}/bars", "resource": "ths-sector-bars", "templated": True},
    ]
    invalid = _validate_as_of(as_of, effective_date)
    if invalid is not None:
        return invalid
    metadata = queries.overview(as_of)
    if metadata is None:
        return _error(404, "resource_not_found", "所选精确日期没有本地证据")
    current = _public_revision(metadata)
    try:
        after = _cursor_after(cursor, resource=name, scope={"asOf": as_of}, filters=filters, revision=current)
        page = loader(after)
    except CursorError as error:
        return _cursor_error(error)
    except ValueError as error:
        return _error(422, "invalid_selector", str(error))
    return _page_response(page, resource_name=name, scope={"asOf": as_of}, filters=filters, limit=limit, revision=revision, if_match=if_match, if_none_match=if_none_match, links=links)


@router.get("/{as_of}/sectors/rankings", response_model=PageEnvelopeModel, operation_id="listV2MarketSectorRankings")
def sector_rankings(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], tag: SectorTag | None = Query(default=None), limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None), revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    filters = {"tag": tag}
    return _sector_page("sector_rankings", as_of, effective_date, queries, lambda after: queries.sector_rankings(as_of, tag=tag, after=after, limit=limit), filters=filters, limit=limit, cursor=cursor, revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/sectors/turnover", response_model=PageEnvelopeModel, operation_id="listV2MarketSectorTurnover")
def sector_turnover(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None), revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    return _sector_page("sector_turnover", as_of, effective_date, queries, lambda after: queries.sector_turnover(as_of, after=after, limit=limit), filters={}, limit=limit, cursor=cursor, revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/sectors/breadth", response_model=PageEnvelopeModel, operation_id="listV2MarketSectorBreadth")
def sector_breadth(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None), revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    return _sector_page("sector_breadth", as_of, effective_date, queries, lambda after: queries.sector_breadth(as_of, after=after, limit=limit), filters={}, limit=limit, cursor=cursor, revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/sectors/analysis", response_model=EnvelopeModel, operation_id="getV2MarketSectorAnalysis")
def sector_analysis(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    return _exact_resource(as_of, effective_date, lambda: queries.sector_analysis(as_of), revision=revision, if_match=if_match, if_none_match=if_none_match, links=_links(as_of, ("sectors/rankings", "sectors/turnover", "sectors/breadth")))


@router.get("/{as_of}/active-direction", response_model=PageEnvelopeModel, operation_id="listV2MarketActiveDirection")
def active_direction(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None), revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    invalid = _validate_as_of(as_of, effective_date)
    if invalid is not None:
        return invalid
    metadata = queries.overview(as_of)
    if metadata is None:
        return _error(404, "resource_not_found", "所选精确日期没有本地证据")
    current = _public_revision(metadata)
    try:
        after = _cursor_after(cursor, resource="active_direction", scope={"asOf": as_of}, filters={}, revision=current)
        page = queries.active_direction(as_of, after=after, limit=limit)
    except CursorError as error:
        return _cursor_error(error)
    return _page_response(page, resource_name="active_direction", scope={"asOf": as_of}, filters={}, limit=limit, revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/events", response_model=PageEnvelopeModel, operation_id="listV2MarketEvents")
def events(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], limit: int = Query(default=20, ge=1, le=100), cursor: str | None = Query(default=None), revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    invalid = _validate_as_of(as_of, effective_date)
    if invalid is not None:
        return invalid
    metadata = queries.overview(as_of)
    if metadata is None:
        return _error(404, "resource_not_found", "所选精确日期没有本地证据")
    current = _public_revision(metadata)
    try:
        after = _cursor_after(cursor, resource="events", scope={"asOf": as_of}, filters={}, revision=current)
        page = queries.events(as_of, after=after, limit=limit)
    except CursorError as error:
        return _cursor_error(error)
    return _page_response(page, resource_name="events", scope={"asOf": as_of}, filters={}, limit=limit, revision=revision, if_match=if_match, if_none_match=if_none_match)


@router.get("/{as_of}/assessment", response_model=EnvelopeModel, operation_id="getV2MarketAssessment")
def assessment(as_of: date, queries: Annotated[V2MarketEnvironmentQueries, Depends(get_v2_market_queries)], effective_date: Annotated[date, Depends(get_effective_market_date)], revision: str | None = Query(default=None), if_match: str | None = Header(default=None, alias="If-Match"), if_none_match: str | None = Header(default=None, alias="If-None-Match")):
    return _exact_resource(as_of, effective_date, lambda: queries.assessment(as_of), revision=revision, if_match=if_match, if_none_match=if_none_match)


__all__ = ["router"]
