from __future__ import annotations

from fastapi import APIRouter, Request

from ..services.current_user_service import require_current_user_id
from ..services.training_export_service import export_training_manifest


router = APIRouter(prefix="/training", tags=["training"])


@router.post("/export-manifest")
def export_manifest(request: Request) -> dict:
    require_current_user_id(request, allow_legacy_fallback=False)
    return export_training_manifest()
