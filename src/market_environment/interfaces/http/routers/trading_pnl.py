"""Explicit personal ledger operations and local read endpoints."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import Field, StringConstraints
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from ....application.commands.trading_pnl import PnlCommandError
from ....domain.models.trading_pnl import (
    MAX_IMAGE_BYTES, MAX_IMAGES, EvidenceBatch, LedgerDate, LedgerInput, LedgerUnavailable, Opening, ScreenshotError, Trade,
)
from ..dependencies import _request_container


DraftId = Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class DraftEdit(LedgerInput):
    digest: Digest
    row_number: Annotated[int, Field(ge=0, lt=120)]
    fields: Annotated[dict, Field(max_length=30)]


class Decision(DraftEdit):
    decision: Literal["add", "skip", "keep-distinct"]


class Review(LedgerInput):
    rows: Annotated[list[DraftEdit], Field(max_length=MAX_IMAGES * 120)]


class Confirm(LedgerInput):
    revision: Annotated[int, Field(ge=0)]
    key: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{16,100}$")]
    rows: Annotated[list[Decision], Field(min_length=1, max_length=MAX_IMAGES * 120)]


class LedgerDateRange(LedgerInput):
    start: LedgerDate
    end: LedgerDate
    revision: Annotated[int, Field(ge=0)]


class Coverage(LedgerDateRange):
    kind: Literal["complete", "no-trades"]


class Correction(LedgerInput):
    trade: Trade
    revision: Annotated[int, Field(ge=0)]
    keep_distinct: bool = False


def _no_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/trading-pnl", tags=["Personal trading ledger"], dependencies=[Depends(_no_cache)])


def _service(request: Request, *, write: bool = False):
    container = _request_container(request)
    service = container.commands.trading_pnl if write else container.reads.trading_pnl
    if service is None:
        raise HTTPException(503, "个人台账需要 PostgreSQL 环境")
    return service


def _call(operation, *args):
    try:
        return operation(*args)
    except PnlCommandError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    except ScreenshotError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LedgerUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


async def _bounded_upload(request: Request):
    maximum = (MAX_IMAGE_BYTES + 8192) * MAX_IMAGES
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > maximum:
            raise MultiPartException("截图批次超过上传限制")
        yield chunk


@router.get("/months/{month}")
def month_summary(request: Request, month: Annotated[str, Path(pattern=r"^20[0-9]{2}-(0[1-9]|1[0-2])$")]):
    year, number = (int(part) for part in month.split("-"))
    return _call(_service(request).month, year, number)


@router.get("/days/{day}")
def day_details(request: Request, day: date, after: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    if not date(2000, 1, 1) <= day <= date(2099, 12, 31):
        raise HTTPException(422, "交易日期超出支持范围")
    return _call(_service(request).day, day, after, limit)


@router.post("/drafts")
async def upload_screenshots(request: Request):
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise HTTPException(415, "请上传截图文件")
    service = _service(request, write=True)
    try:
        form = await MultiPartParser(request.headers, _bounded_upload(request), max_files=MAX_IMAGES, max_fields=0).parse()
    except MultiPartException as exc:
        raise HTTPException(422, "请上传最多 6 张、每张不超过 5 MB 的截图") from exc
    try:
        files = [item for key, item in form.multi_items() if key == "images" and isinstance(item, UploadFile)]
        if not files or len(files) != len(form.multi_items()):
            raise HTTPException(422, "请用 images 字段上传截图")
        blobs = [await item.read(MAX_IMAGE_BYTES + 1) for item in files]
        if any(not blob or len(blob) > MAX_IMAGE_BYTES for blob in blobs):
            raise HTTPException(422, "每张截图限 5 MB")
    finally:
        await form.close()
    return await run_in_threadpool(_call, service.upload, blobs)


@router.get("/drafts/{identifier}")
def get_draft(request: Request, identifier: DraftId):
    return _call(_service(request, write=True).preview, identifier, [])


@router.get("/drafts/{identifier}/images/{digest}")
def get_preview_image(request: Request, identifier: DraftId, digest: Digest):
    content = _call(_service(request, write=True).preview_image, identifier, digest)
    return Response(content, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/drafts/{identifier}/preview")
def preview_edits(request: Request, identifier: DraftId, data: Review):
    return _call(_service(request, write=True).preview, identifier, [row.model_dump() for row in data.rows])


@router.post("/drafts/{identifier}/confirm")
def confirm_draft(request: Request, identifier: DraftId, data: Confirm):
    return _call(_service(request, write=True).confirm, identifier, data.key, data.revision, [row.model_dump() for row in data.rows])


@router.post("/opening")
def configure_opening(request: Request, data: Opening):
    return _call(_service(request, write=True).opening, data)


@router.post("/coverage")
def confirm_coverage(request: Request, data: Coverage):
    return _call(_service(request, write=True).cover, data.start, data.end, data.kind, data.revision)


@router.post("/trades/{identifier}/correction")
def correct_trade(request: Request, identifier: Annotated[int, Path(gt=0)], data: Correction):
    return _call(_service(request, write=True).correct, identifier, data.trade, data.revision, data.keep_distinct)


@router.post("/evidence")
def import_local_evidence(request: Request, data: EvidenceBatch):
    return _call(_service(request, write=True).import_evidence, data)


@router.post("/evidence/fuyao")
def backfill_fuyao_evidence(request: Request, data: LedgerDateRange):
    service = _request_container(request).commands.trading_pnl_backfill
    if service is None:
        raise HTTPException(503, "个人台账需要 PostgreSQL 环境")
    return _call(service.run, data.start, data.end, data.revision)
