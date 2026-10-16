"""Central mapping from application failures to stable HTTP errors."""

from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException

from ...application.commands import (
    CollectionSubmissionRejected,
    FullCollectionBeforeSettlementError,
    FullCollectionIdempotencyConflictError,
)


def raise_application_error(error: Exception) -> NoReturn:
    if isinstance(error, HTTPException):
        raise error
    if isinstance(error, FullCollectionIdempotencyConflictError):
        binding = error.binding
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "message": str(error),
                "runId": binding.run_id,
                "targetDate": binding.resolved_as_of.isoformat(),
                "statusUrl": (
                    "/api/market-environment/collection-runs/"
                    f"{binding.run_id}"
                ),
            },
        ) from error
    if isinstance(error, FullCollectionBeforeSettlementError):
        raise HTTPException(
            status_code=422,
            detail={
                "code": error.code,
                "message": str(error),
                "targetDate": error.resolved_as_of.isoformat(),
            },
        ) from error
    if isinstance(error, CollectionSubmissionRejected):
        binding = error.binding
        raise HTTPException(
            status_code=503,
            detail={
                "code": "executor-submission-rejected",
                "message": str(error),
                "runId": binding.run_id,
                "statusUrl": (
                    "/api/market-environment/collection-runs/"
                    f"{binding.run_id}"
                ),
            },
        ) from error
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
