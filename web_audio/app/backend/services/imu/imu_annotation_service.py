from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...database import fetch_all, fetch_one, get_connection
from ..storage_service import make_id, now_iso
from .imu_schema import ANNOTATION_SOURCES, EMOTION_CONTEXT_LABELS, MOTION_LABELS, QUALITY_LABELS
from .imu_storage_service import get_imu_session_with_ownership, get_multimodal_emotion_record


def create_imu_annotation(user_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid annotation payload")

    imu_session_id = str(payload.get("imu_session_id") or "")
    window_id = str(payload.get("window_id") or "")
    record_id = str(payload.get("record_id") or "")
    pet_id = str(payload.get("pet_id") or "")
    if not any((imu_session_id, window_id, record_id)):
        raise HTTPException(status_code=400, detail="imu_session_id, window_id, or record_id is required")

    resolved = _resolve_annotation_scope(user_id, imu_session_id, window_id, record_id, pet_id)
    motion_label_user = str(payload.get("motion_label_user") or "")
    emotion_context_label_user = str(payload.get("emotion_context_label_user") or "")
    quality_label = str(payload.get("quality_label") or "")
    annotation_source = str(payload.get("annotation_source") or "user_manual")

    if motion_label_user and motion_label_user not in MOTION_LABELS:
        raise HTTPException(status_code=400, detail="Unsupported motion_label_user")
    if emotion_context_label_user and emotion_context_label_user not in EMOTION_CONTEXT_LABELS:
        raise HTTPException(status_code=400, detail="Unsupported emotion_context_label_user")
    if quality_label not in QUALITY_LABELS:
        raise HTTPException(status_code=400, detail="Unsupported quality_label")
    if annotation_source not in ANNOTATION_SOURCES:
        raise HTTPException(status_code=400, detail="Unsupported annotation_source")

    annotation_id = make_id("imu_annotation")
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO imu_annotations (
                annotation_id, imu_session_id, window_id, record_id,
                user_id, pet_id, motion_label_user, emotion_context_label_user,
                quality_label, annotation_source, comment, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                annotation_id,
                resolved["imu_session_id"],
                resolved["window_id"],
                resolved["record_id"],
                user_id,
                resolved["pet_id"],
                motion_label_user,
                emotion_context_label_user,
                quality_label,
                annotation_source,
                str(payload.get("comment") or ""),
                now_iso(),
            ),
        )
        connection.commit()
    return fetch_one("SELECT * FROM imu_annotations WHERE annotation_id = ?", (annotation_id,)) or {"annotation_id": annotation_id}


def list_imu_annotations(user_id: str, pet_id: str | None = None, imu_session_id: str | None = None) -> list[dict]:
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if pet_id:
        _require_owned_pet(user_id, str(pet_id))
        clauses.append("pet_id = ?")
        params.append(str(pet_id))
    if imu_session_id:
        get_imu_session_with_ownership(user_id, str(imu_session_id))
        clauses.append("imu_session_id = ?")
        params.append(str(imu_session_id))
    query = f"SELECT * FROM imu_annotations WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, annotation_id DESC"
    return fetch_all(query, tuple(params))


def map_quality_to_candidate_status(quality_label: str) -> dict:
    if quality_label == "accepted":
        return {"quality_status": "accepted", "review_status": "pending_review"}
    if quality_label == "uncertain":
        return {"quality_status": "uncertain", "review_status": "pending_review"}
    if quality_label == "rejected" or str(quality_label or "").startswith("reject_"):
        return {"quality_status": "rejected", "review_status": "rejected"}
    raise HTTPException(status_code=400, detail="Unsupported quality_label")


def _resolve_annotation_scope(
    user_id: str,
    imu_session_id: str,
    window_id: str,
    record_id: str,
    pet_id: str,
) -> dict:
    resolved = {
        "imu_session_id": "",
        "window_id": "",
        "record_id": "",
        "pet_id": "",
    }

    if window_id:
        window = _get_owned_window(user_id, window_id)
        session = get_imu_session_with_ownership(user_id, window["imu_session_id"])
        resolved["window_id"] = window["window_id"]
        resolved["imu_session_id"] = session["imu_session_id"]
        resolved["pet_id"] = session["pet_id"]

    if imu_session_id:
        session = get_imu_session_with_ownership(user_id, imu_session_id)
        if resolved["imu_session_id"] and resolved["imu_session_id"] != session["imu_session_id"]:
            raise HTTPException(status_code=400, detail="window_id and imu_session_id do not match")
        resolved["imu_session_id"] = session["imu_session_id"]
        if resolved["pet_id"] and resolved["pet_id"] != session["pet_id"]:
            raise HTTPException(status_code=400, detail="session pet_id mismatch")
        resolved["pet_id"] = session["pet_id"]

    if record_id:
        record = get_multimodal_emotion_record(user_id, record_id)
        resolved["record_id"] = record["record_id"]
        record_session_id = str(record.get("imu_session_id") or "")
        if record_session_id:
            session = get_imu_session_with_ownership(user_id, record_session_id)
            if resolved["imu_session_id"] and resolved["imu_session_id"] != session["imu_session_id"]:
                raise HTTPException(status_code=400, detail="record_id and imu_session_id do not match")
            resolved["imu_session_id"] = session["imu_session_id"]
        if resolved["pet_id"] and resolved["pet_id"] != record["pet_id"]:
            raise HTTPException(status_code=400, detail="record pet_id mismatch")
        resolved["pet_id"] = record["pet_id"]

    if pet_id:
        _require_owned_pet(user_id, pet_id)
        if resolved["pet_id"] and resolved["pet_id"] != str(pet_id):
            raise HTTPException(status_code=400, detail="provided pet_id does not match annotation object")
        resolved["pet_id"] = str(pet_id)

    if not resolved["pet_id"]:
        raise HTTPException(status_code=400, detail="Could not resolve pet_id for annotation")
    return resolved


def _get_owned_window(user_id: str, window_id: str) -> dict:
    window = fetch_one("SELECT * FROM imu_windows WHERE window_id = ?", (str(window_id),))
    if window is None:
        raise HTTPException(status_code=404, detail="IMU window not found")
    get_imu_session_with_ownership(user_id, window.get("imu_session_id", ""))
    return window


def _require_owned_pet(user_id: str, pet_id: str) -> dict:
    pet = fetch_one("SELECT * FROM pets WHERE pet_id = ?", (str(pet_id),))
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    if pet.get("owner_user_id") != user_id:
        raise HTTPException(status_code=403, detail="Cannot use another user's pet")
    return pet
