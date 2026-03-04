from __future__ import annotations

from fastapi import HTTPException, status

from packages.core.errors import DomainError, NotImplementedFeature


def map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotImplementedFeature):
        return HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": exc.code, "message": exc.message, "detail": exc.detail or {}},
        )
    if isinstance(exc, DomainError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message, "detail": exc.detail or {}},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "INTERNAL_ERROR", "message": "Unexpected error"},
    )
