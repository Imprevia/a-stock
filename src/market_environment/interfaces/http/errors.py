"""Central mapping from application failures to stable HTTP errors."""

from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException


def raise_application_error(error: Exception) -> NoReturn:
    if isinstance(error, HTTPException):
        raise error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    if isinstance(error, RuntimeError):
        raise HTTPException(status_code=503, detail=str(error)) from error
    raise error


def raise_forbidden(detail: str) -> NoReturn:
    raise HTTPException(status_code=403, detail=detail)


def raise_not_found(detail: str) -> NoReturn:
    raise HTTPException(status_code=404, detail=detail)


def raise_unprocessable(detail: str) -> NoReturn:
    raise HTTPException(status_code=422, detail=detail)


__all__ = [
    "raise_application_error",
    "raise_forbidden",
    "raise_not_found",
    "raise_unprocessable",
]
