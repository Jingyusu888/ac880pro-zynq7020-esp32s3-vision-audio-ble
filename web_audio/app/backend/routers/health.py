from __future__ import annotations

from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
def get_health() -> dict:
    return {"status": "ok", "app": "petlink_web_app", "mode": "local_test"}
