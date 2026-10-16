"""UTF-8 plain-text discovery routes for AI clients."""

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from ..discovery import render_llms_full_txt, render_llms_txt


router = APIRouter(tags=["AI discovery"])


@router.get("/llms.txt", response_class=PlainTextResponse, operation_id="getLlmsIndex")
def llms_index(request: Request) -> PlainTextResponse:
    return PlainTextResponse(render_llms_txt(request.app.openapi()), media_type="text/plain; charset=utf-8")


@router.get("/llms-full.txt", response_class=PlainTextResponse, operation_id="getLlmsFullGuide")
def llms_full(request: Request) -> PlainTextResponse:
    return PlainTextResponse(render_llms_full_txt(request.app.openapi()), media_type="text/plain; charset=utf-8")


__all__ = ["router"]
