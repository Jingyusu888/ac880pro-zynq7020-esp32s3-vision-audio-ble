from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..services.vision_bridge_service import vision_bridge


router = APIRouter(prefix="/vision", tags=["vision"])


@router.get("/latest")
def get_latest_vision() -> dict[str, Any]:
    return vision_bridge.get_status()


@router.get("/history")
def get_vision_history(limit: int = 50) -> dict[str, Any]:
    return {"items": vision_bridge.get_history(limit=limit)}


@router.post("/ingest")
def ingest_vision_frame(payload: dict[str, Any]) -> dict[str, Any]:
    frame = vision_bridge.ingest_frame(payload, source="http")
    return {"ok": True, "frame": frame}


@router.post("/bridge/connect")
def connect_esp32_bridge(payload: dict[str, Any]) -> dict[str, Any]:
    port = str(payload.get("port") or "").strip()
    baud = int(payload.get("baud", 115200))
    return vision_bridge.connect_esp32(port=port, baud=baud)


@router.get("/multimodal")
def get_multimodal() -> dict[str, Any]:
    return vision_bridge.get_multimodal_summary()
