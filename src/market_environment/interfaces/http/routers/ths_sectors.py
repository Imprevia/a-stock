"""Provider-free THS reads and explicitly gated write operations."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from ....application.commands import ThsOperationGateError
from ..dependencies import (
    ThsSectorCommands,
    ThsSectorQueries,
    get_effective_market_date,
    get_manual_write_enabled,
    get_ths_sector_commands,
    get_ths_sector_queries,
)
from ..errors import raise_forbidden, raise_not_found, raise_unprocessable
from ..schemas.models import (
    QueuedThsOperationResponse,
    ThsCatalogResponse,
    ThsCatalogSyncRequest,
    ThsDumpFileRequest,
    ThsMemberFactsImportRequest,
    ThsOperationResponse,
    ThsSectorBarsResponse,
    ThsTurnoverBackfillRequest,
)


router = APIRouter(prefix="/api/market-environment/ths", tags=["THS sectors"])
ThsTag = Literal["industry", "cn_concept", "region", "tszs"]


def _catalog_payload(raw: dict) -> dict:
    revision = raw.get("revision")
    pagination = raw["pagination"]
    return {
        "revision": (
            {
                "catalogRevisionId": revision["id"],
                "capabilityRevision": revision["capabilityRevision"],
                "providerTimestamp": revision["providerTimestamp"],
                "fetchedAt": revision["fetchedAt"],
                "tagCounts": revision["tagCounts"],
                "checksum": revision["checksum"],
            }
            if revision is not None
            else None
        ),
        "items": [
            {"tag": item["tag"], "thscode": item["thscode"], "name": item["name"]}
            for item in raw["items"]
        ],
        "page": pagination["page"],
        "pageSize": pagination["pageSize"],
        "total": pagination["total"],
    }


def _gap_label(gap: dict[str, str]) -> str:
    return f"{gap['start']}~{gap['end']}"


def _bars_payload(raw: dict) -> dict:
    requested = raw["requestedRange"]
    coverage = raw["coverage"]
    pagination = raw["pagination"]
    return {
        "thscode": raw["thscode"],
        "requestedStart": requested["start"],
        "requestedEnd": requested["end"],
        "coverage": {
            "firstDate": coverage["firstDate"],
            "lastDate": coverage["lastDate"],
            "storedRows": coverage["storedRows"],
            "gaps": [_gap_label(item) for item in coverage["gaps"]],
        },
        "items": raw["items"],
        "page": pagination["page"],
        "pageSize": pagination["pageSize"],
        "total": pagination["total"],
    }


def _operation_payload(raw: dict) -> dict:
    summary = raw["summary"]
    return {
        "runId": raw["runId"],
        "kind": raw["operation"],
        "status": raw["status"],
        "progress": {
            "completed": summary["completedItems"],
            "total": summary["totalItems"],
            "failed": summary["failedItems"],
            "conflicts": summary["conflictItems"],
        },
        "warning": raw["warning"],
        "checkpoints": raw["checkpoints"],
    }


def _validate_completed_date(value: date, effective_date: date) -> None:
    if value > effective_date:
        raise_unprocessable("日期不能晚于当前有效市场日")


def _raise_write_error(error: Exception) -> None:
    if isinstance(error, ThsOperationGateError):
        raise_forbidden(str(error))
    if isinstance(error, ValueError):
        raise_unprocessable(str(error))
    raise_forbidden("THS 写操作不可用；请检查授权、capability revision 和请求预算")


@router.get("/catalog", response_model=ThsCatalogResponse)
def list_ths_catalog(
    queries: Annotated[ThsSectorQueries, Depends(get_ths_sector_queries)],
    tag: ThsTag | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    revision: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> dict:
    try:
        return _catalog_payload(
            queries.list_catalog(
                tag=tag,
                search=search,
                revision_id=revision,
                page=page,
                page_size=page_size,
            )
        )
    except LookupError as error:
        raise_not_found(str(error))
    except ValueError as error:
        raise_unprocessable(str(error))


@router.get("/sectors/{thscode}/bars", response_model=ThsSectorBarsResponse)
def get_ths_sector_bars(
    thscode: str,
    queries: Annotated[ThsSectorQueries, Depends(get_ths_sector_queries)],
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=250, ge=1, le=1000),
) -> dict:
    try:
        return _bars_payload(
            queries.get_bars(
                thscode,
                start_date=start_date,
                end_date=end_date,
                page=page,
                page_size=page_size,
            )
        )
    except ValueError as error:
        raise_unprocessable(str(error))


@router.get("/operations/{run_id}", response_model=ThsOperationResponse)
def get_ths_operation(
    run_id: str,
    queries: Annotated[ThsSectorQueries, Depends(get_ths_sector_queries)],
) -> dict:
    try:
        return _operation_payload(queries.get_operation(run_id))
    except LookupError:
        raise_not_found("THS operation 不存在")
    except ValueError as error:
        raise_unprocessable(str(error))


@router.post(
    "/catalog/sync",
    response_model=QueuedThsOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_ths_catalog_sync(
    commands: Annotated[ThsSectorCommands, Depends(get_ths_sector_commands)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    manual_write_enabled: Annotated[bool, Depends(get_manual_write_enabled)],
    body: ThsCatalogSyncRequest | None = None,
) -> dict:
    if not manual_write_enabled:
        raise_forbidden("手工数据写入未启用")
    body = body or ThsCatalogSyncRequest()
    as_of = body.asOf or effective_date
    if as_of != effective_date:
        raise_unprocessable("目录同步仅支持当前已完成上海交易日")
    try:
        return commands.start_catalog_sync(
            as_of=as_of,
            capability_revision=body.capabilityRevision,
            membership_capability_revision=body.membershipCapabilityRevision,
            membership_thscodes=body.membershipThscodes,
            request_budget=body.requestBudget,
        )
    except Exception as error:
        _raise_write_error(error)


@router.post(
    "/turnover/backfills",
    response_model=QueuedThsOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_ths_turnover_backfill(
    body: ThsTurnoverBackfillRequest,
    commands: Annotated[ThsSectorCommands, Depends(get_ths_sector_commands)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    manual_write_enabled: Annotated[bool, Depends(get_manual_write_enabled)],
) -> dict:
    if not manual_write_enabled:
        raise_forbidden("手工数据写入未启用")
    _validate_completed_date(body.endDate, effective_date)
    try:
        return commands.start_turnover_backfill(
            thscodes=body.thscodes,
            start_date=body.startDate,
            end_date=body.endDate,
            capability_revision=body.capabilityRevision,
            request_budget=body.requestBudget,
        )
    except Exception as error:
        _raise_write_error(error)


def _dump_request(value: ThsDumpFileRequest) -> dict:
    return {
        "path": value.path,
        "dump_id": value.dumpId,
        "schema_revision": value.schemaRevision,
        "capability_revision": value.capabilityRevision,
        "checksum": value.checksum,
        "start_date": value.startDate,
        "end_date": value.endDate,
    }


@router.post(
    "/member-facts/imports",
    response_model=QueuedThsOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_ths_member_import(
    body: ThsMemberFactsImportRequest,
    commands: Annotated[ThsSectorCommands, Depends(get_ths_sector_commands)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    manual_write_enabled: Annotated[bool, Depends(get_manual_write_enabled)],
) -> dict:
    if not manual_write_enabled:
        raise_forbidden("手工数据写入未启用")
    _validate_completed_date(body.asOf, effective_date)
    try:
        return commands.start_member_import(
            as_of=body.asOf,
            source_revision=body.sourceRevision,
            request_budget=body.requestBudget,
            daily=_dump_request(body.daily),
            adjustment=_dump_request(body.adjustment),
            incremental=(
                _dump_request(body.incremental)
                if body.incremental is not None
                else None
            ),
        )
    except Exception as error:
        _raise_write_error(error)


__all__ = ["router"]
