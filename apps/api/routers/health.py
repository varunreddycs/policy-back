from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Health")
def health() -> dict:
    return {"status": "ok"}
