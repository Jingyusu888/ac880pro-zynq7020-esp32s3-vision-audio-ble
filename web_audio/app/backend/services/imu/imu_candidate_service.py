from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ...config import DATA_DIR
from ...database import fetch_all, fetch_one, get_connection
from ..storage_service import make_id, now_iso
from .imu_annotation_service import map_quality_to_candidate_status
from .imu_schema import TRAINING_QUALITY_STATUS_VALUES, TRAINING_REVIEW_STATUS_VALUES
from .imu_storage_service import get_imu_session_with_ownership


FEATURE_FIELDS = [
    "acc_mean",
    "acc_std",
    "acc_max",
    "acc_rms",
    "gyro_mean",
    "gyro_std",
    "gyro_max",
    "gyro_p95",
    "jerk_mean",
    "jerk_max",
    "peak_count",
    "dominant_freq",
]

EXPORT_FIELDS = [
    "candidate_id",
    "imu_session_id",
    "window_id",
    "annotation_id",
    "user_id",
    "pet_id",
    "source",
    "label",
    *FEATURE_FIELDS,
    "quality_status",
    "review_status",
    "created_at",
]


def add_annotation_to_training_candidates(user_id: str, annotation_id: str) -> dict:
    annotation = _get_owned_annotation(user_id, annotation_id)
    if not annotation.get("motion_label_user"):
        raise HTTPException(status_code=400, detail="motion_label_user is required to create IMU candidates")

    windows = _resolve_windows_for_annotation(user_id, annotation)
    if not windows:
        return {
            "status": "no_windows",
            "added_count": 0,
            "candidate_ids": [],
            "message": "No analyzed IMU windows are available for this annotation.",
            "hardware_connected": False,
        }

    candidate_status = map_quality_to_candidate_status(annotation["quality_label"])
    candidate_ids = []
    added_count = 0
    for window in windows:
        existing = fetch_one(
            """
            SELECT * FROM imu_training_candidates
            WHERE user_id = ? AND annotation_id = ? AND window_id = ?
            """,
            (user_id, annotation["annotation_id"], window["window_id"]),
        )
        if existing:
            candidate_ids.append(existing["candidate_id"])
            continue
        candidate_id = make_id("imu_candidate")
        feature_json = build_feature_json_from_window(window)
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO imu_training_candidates (
                    candidate_id, imu_session_id, window_id, annotation_id,
                    user_id, pet_id, feature_json, label, quality_status,
                    review_status, source, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    window["imu_session_id"],
                    window["window_id"],
                    annotation["annotation_id"],
                    user_id,
                    annotation["pet_id"],
                    json.dumps(feature_json, ensure_ascii=False, sort_keys=True),
                    annotation["motion_label_user"],
                    candidate_status["quality_status"],
                    candidate_status["review_status"],
                    _candidate_source(annotation, window),
                    now_iso(),
                ),
            )
            connection.commit()
        candidate_ids.append(candidate_id)
        added_count += 1

    return {
        "status": "ok",
        "added_count": added_count,
        "candidate_ids": candidate_ids,
        "candidates": _get_candidates_by_ids(user_id, candidate_ids),
        "quality_status": candidate_status["quality_status"],
        "review_status": candidate_status["review_status"],
        "training_status": _training_status(candidate_status["quality_status"], candidate_status["review_status"]),
        "message": _candidate_message(annotation["quality_label"], len(candidate_ids), added_count),
        "hardware_connected": False,
    }


def list_training_candidates(
    user_id: str,
    pet_id: str | None = None,
    quality_status: str | None = None,
) -> list[dict]:
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if pet_id:
        _require_owned_pet(user_id, str(pet_id))
        clauses.append("pet_id = ?")
        params.append(str(pet_id))
    if quality_status:
        if quality_status not in TRAINING_QUALITY_STATUS_VALUES:
            raise HTTPException(status_code=400, detail="Unsupported quality_status")
        clauses.append("quality_status = ?")
        params.append(str(quality_status))
    query = f"SELECT * FROM imu_training_candidates WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, candidate_id DESC"
    return [_enrich_candidate_row(row) for row in fetch_all(query, tuple(params))]


def export_training_candidates(user_id: str, export_name: str = "imu_training_ready_v1") -> dict:
    safe_name = _safe_export_name(export_name)
    rows = fetch_all(
        """
        SELECT * FROM imu_training_candidates
        WHERE user_id = ?
          AND quality_status = 'accepted'
          AND review_status IN ('reviewed', 'pending', 'exported')
        ORDER BY created_at ASC, candidate_id ASC
        """,
        (user_id,),
    )
    export_dir = DATA_DIR / "imu" / "training_candidates"
    export_dir.mkdir(parents=True, exist_ok=True)
    csv_path = export_dir / f"{safe_name}.csv"
    jsonl_path = export_dir / f"{safe_name}.jsonl"

    export_rows = [_candidate_export_row(row) for row in rows]
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        for row in export_rows:
            writer.writerow(row)
    with jsonl_path.open("w", encoding="utf-8") as file:
        for row in rows:
            payload = dict(row)
            payload["feature_json"] = _loads_feature_json(row.get("feature_json", ""))
            file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    if rows:
        candidate_ids = [row["candidate_id"] for row in rows]
        placeholders = ",".join(["?"] * len(candidate_ids))
        with get_connection() as connection:
            connection.execute(
                f"UPDATE imu_training_candidates SET review_status = 'exported' WHERE user_id = ? AND candidate_id IN ({placeholders})",
                tuple([user_id, *candidate_ids]),
            )
            connection.commit()

    return {
        "status": "ok",
        "exported_count": len(rows),
        "csv_path": _relative_data_path(csv_path),
        "jsonl_path": _relative_data_path(jsonl_path),
        "message": "Only accepted IMU candidates were exported.",
        "hardware_connected": False,
    }


def build_feature_json_from_window(window_row: dict) -> dict:
    return {
        "window_id": window_row.get("window_id", ""),
        "imu_session_id": window_row.get("imu_session_id", ""),
        "window_start_ms": window_row.get("window_start_ms"),
        "window_end_ms": window_row.get("window_end_ms"),
        **{field: window_row.get(field) for field in FEATURE_FIELDS},
        "rule_motion_label": window_row.get("rule_motion_label", ""),
        "rule_motion_confidence": window_row.get("rule_motion_confidence"),
    }


def _get_owned_annotation(user_id: str, annotation_id: str) -> dict:
    annotation = fetch_one("SELECT * FROM imu_annotations WHERE annotation_id = ?", (str(annotation_id),))
    if annotation is None:
        raise HTTPException(status_code=404, detail="IMU annotation not found")
    if annotation.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Cannot access another user's IMU annotation")
    return annotation


def _resolve_windows_for_annotation(user_id: str, annotation: dict) -> list[dict]:
    window_id = str(annotation.get("window_id") or "")
    session_id = str(annotation.get("imu_session_id") or "")
    if window_id:
        window = _get_owned_window(user_id, window_id)
        return [window]
    if session_id:
        get_imu_session_with_ownership(user_id, session_id)
        return _get_owned_windows_for_session(user_id, session_id)
    record_id = str(annotation.get("record_id") or "")
    if record_id:
        record = fetch_one("SELECT * FROM multimodal_emotion_records WHERE record_id = ?", (record_id,))
        if record is None:
            raise HTTPException(status_code=404, detail="Multimodal record not found")
        if record.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Cannot access another user's multimodal record")
        record_session_id = str(record.get("imu_session_id") or "")
        if record_session_id:
            get_imu_session_with_ownership(user_id, record_session_id)
            return _get_owned_windows_for_session(user_id, record_session_id)
    return []


def _get_owned_window(user_id: str, window_id: str) -> dict:
    window = fetch_one("SELECT * FROM imu_windows WHERE window_id = ?", (str(window_id),))
    if window is None:
        raise HTTPException(status_code=404, detail="IMU window not found")
    get_imu_session_with_ownership(user_id, window["imu_session_id"])
    return window


def _get_owned_windows_for_session(user_id: str, session_id: str) -> list[dict]:
    get_imu_session_with_ownership(user_id, session_id)
    return fetch_all(
        "SELECT * FROM imu_windows WHERE imu_session_id = ? ORDER BY window_start_ms ASC, window_id ASC",
        (str(session_id),),
    )


def _candidate_source(annotation: dict, window: dict) -> str:
    session = fetch_one("SELECT * FROM imu_sessions WHERE imu_session_id = ?", (window["imu_session_id"],)) or {}
    source = str(session.get("source") or "")
    if source in {"simulated", "engineering_assumption"}:
        return source
    if source == "tail_imu_auto_future":
        return "future_tail_imu_auto"
    return "human_annotated_simulated"


def _candidate_message(quality_label: str, total_count: int, added_count: int) -> str:
    if quality_label == "accepted":
        return "Accepted annotation converted to IMU candidates with pending_review and not_training_ready defaults."
    if quality_label == "uncertain":
        return "Uncertain annotation retained in IMU candidates but excluded from training-ready export."
    return "Rejected annotation retained for audit but excluded from training-ready export."


def _get_candidates_by_ids(user_id: str, candidate_ids: list[str]) -> list[dict]:
    if not candidate_ids:
        return []
    placeholders = ",".join(["?"] * len(candidate_ids))
    rows = fetch_all(
        f"""
        SELECT * FROM imu_training_candidates
        WHERE user_id = ? AND candidate_id IN ({placeholders})
        ORDER BY created_at DESC, candidate_id DESC
        """,
        tuple([user_id, *candidate_ids]),
    )
    return [_enrich_candidate_row(row) for row in rows]


def _enrich_candidate_row(row: dict) -> dict:
    annotation = fetch_one("SELECT * FROM imu_annotations WHERE annotation_id = ?", (row.get("annotation_id", ""),)) or {}
    quality_status = str(row.get("quality_status") or "")
    review_status = str(row.get("review_status") or "")
    return {
        **row,
        "training_status": _training_status(quality_status, review_status),
        "audio_recognition_id": "",
        "audio_label": "",
        "imu_motion_label": row.get("label", ""),
        "fused_label": "",
        "user_feedback": annotation.get("comment", ""),
    }


def _training_status(quality_status: str, review_status: str) -> str:
    if quality_status == "accepted" and review_status in {"reviewed", "exported"}:
        return "training_ready"
    return "not_training_ready"


def _candidate_export_row(row: dict) -> dict:
    features = _loads_feature_json(row.get("feature_json", ""))
    return {
        "candidate_id": row.get("candidate_id", ""),
        "imu_session_id": row.get("imu_session_id", ""),
        "window_id": row.get("window_id", ""),
        "annotation_id": row.get("annotation_id", ""),
        "user_id": row.get("user_id", ""),
        "pet_id": row.get("pet_id", ""),
        "source": row.get("source", ""),
        "label": row.get("label", ""),
        **{field: features.get(field) for field in FEATURE_FIELDS},
        "quality_status": row.get("quality_status", ""),
        "review_status": row.get("review_status", ""),
        "created_at": row.get("created_at", ""),
    }


def _loads_feature_json(raw: str) -> dict:
    try:
        payload = json.loads(raw or "{}")
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def _safe_export_name(export_name: str) -> str:
    cleaned = "".join(char for char in str(export_name or "imu_training_ready_v1") if char.isalnum() or char in {"_", "-"})
    return cleaned or "imu_training_ready_v1"


def _relative_data_path(path: Path) -> str:
    try:
        return str(path.relative_to(DATA_DIR.parent)).replace("\\", "/")
    except ValueError:
        return str(path)


def _require_owned_pet(user_id: str, pet_id: str) -> dict:
    pet = fetch_one("SELECT * FROM pets WHERE pet_id = ?", (str(pet_id),))
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    if pet.get("owner_user_id") != user_id:
        raise HTTPException(status_code=403, detail="Cannot use another user's pet")
    return pet
