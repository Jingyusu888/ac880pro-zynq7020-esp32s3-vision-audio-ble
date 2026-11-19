from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...database import fetch_all, fetch_one, get_connection, init_database
from ..storage_service import make_id, now_iso
from .imu_schema import (
    CONFIDENCE_TYPE_RULE_SCORE,
    EMOTION_CONTEXT_LABELS,
    FUSION_METHOD_PLACEHOLDER,
    IMU_SOURCE_ALLOWED_CURRENT,
    IMU_SOURCE_FUTURE_RESERVED,
    MOTION_LABELS,
    QUALITY_LABELS,
    SENSOR_POSITION_ALLOWED_CURRENT,
    SENSOR_POSITION_FUTURE_RESERVED,
)
from .imu_rule_classifier import summarize_session_motion
from .imu_simulator import SIMULATION_SCENARIOS, generate_imu_samples, get_simulation_note


def ensure_imu_tables() -> None:
    init_database()


def get_imu_status() -> dict[str, Any]:
    return {
        "hardware_connected": False,
        "mode": "simulated_and_self_improve_only",
        "status": "no_hardware_algorithm_stage",
        "available_sources_current": IMU_SOURCE_ALLOWED_CURRENT,
        "future_sources_reserved": IMU_SOURCE_FUTURE_RESERVED,
        "available_sensor_positions_current": SENSOR_POSITION_ALLOWED_CURRENT,
        "future_sensor_positions_reserved": SENSOR_POSITION_FUTURE_RESERVED,
        "message": "当前 IMU 为无硬件模拟、人工标注与自我改进算法阶段，尚未接入真实硬件。",
    }


def _require_owned_pet(user_id: str, pet_id: str) -> dict:
    pet = fetch_one("SELECT * FROM pets WHERE pet_id = ?", (str(pet_id),))
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    if pet.get("owner_user_id") != user_id:
        raise HTTPException(status_code=403, detail="Cannot use another user's pet")
    return pet


def _require_owned_session(user_id: str, session_id: str) -> dict:
    session = fetch_one("SELECT * FROM imu_sessions WHERE imu_session_id = ?", (str(session_id),))
    if session is None:
        raise HTTPException(status_code=404, detail="IMU session not found")
    if session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Cannot access another user's IMU session")
    return session


def _require_owned_window(user_id: str, window_id: str) -> dict:
    window = fetch_one("SELECT * FROM imu_windows WHERE window_id = ?", (str(window_id),))
    if window is None:
        raise HTTPException(status_code=404, detail="IMU window not found")
    _require_owned_session(user_id, window.get("imu_session_id", ""))
    return window


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _nullable_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nullable_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _validate_simulation_inputs(
    source: str,
    scenario: str,
    sensor_position: str,
    sample_rate_hz: Any,
    duration_s: Any,
    noise_level: Any,
    intensity: Any,
) -> dict[str, Any]:
    source = str(source or "simulated")
    scenario = str(scenario or "").strip()
    sensor_position = str(sensor_position or "simulated_tail")
    if source not in IMU_SOURCE_ALLOWED_CURRENT:
        raise HTTPException(status_code=400, detail="Unsupported source for current IMU stage")
    if sensor_position not in SENSOR_POSITION_ALLOWED_CURRENT:
        raise HTTPException(status_code=400, detail="Unsupported sensor_position for current IMU stage")
    if scenario not in SIMULATION_SCENARIOS:
        raise HTTPException(status_code=400, detail="Unsupported simulation scenario")

    sample_rate_float = _safe_float(sample_rate_hz, 50)
    if sample_rate_float not in (25, 50):
        raise HTTPException(status_code=400, detail="sample_rate_hz must be 25 or 50 in C3")
    sample_rate = int(sample_rate_float)

    duration = _safe_float(duration_s, 10.0)
    if duration < 2 or duration > 60:
        raise HTTPException(status_code=400, detail="duration_s must be between 2 and 60 seconds")

    noise = _safe_float(noise_level, 0.03)
    if noise < 0 or noise > 0.5:
        raise HTTPException(status_code=400, detail="noise_level must be between 0 and 0.5")

    safe_intensity = _safe_float(intensity, 1.0)
    if safe_intensity <= 0 or safe_intensity > 3:
        raise HTTPException(status_code=400, detail="intensity must be between 0 and 3")

    return {
        "source": source,
        "scenario": scenario,
        "sensor_position": sensor_position,
        "sample_rate_hz": sample_rate,
        "duration_s": duration,
        "noise_level": noise,
        "intensity": safe_intensity,
    }


def create_imu_session_placeholder(
    user_id: str,
    pet_id: str,
    source: str,
    scenario: str = "",
    sensor_position: str = "simulated_tail",
    sample_rate_hz: float = 50,
    duration_s: float = 0,
    notes: str = "",
) -> dict:
    _require_owned_pet(user_id, pet_id)
    if source not in IMU_SOURCE_ALLOWED_CURRENT:
        raise HTTPException(status_code=400, detail="Unsupported source for current IMU stage")
    if sensor_position not in SENSOR_POSITION_ALLOWED_CURRENT:
        raise HTTPException(status_code=400, detail="Unsupported sensor_position for current IMU stage")
    sample_rate_hz = _safe_float(sample_rate_hz, 50)
    duration_s = _safe_float(duration_s, 0)
    if sample_rate_hz <= 0 or sample_rate_hz > 400:
        raise HTTPException(status_code=400, detail="sample_rate_hz is abnormal")
    if duration_s < 0:
        raise HTTPException(status_code=400, detail="duration_s cannot be negative")

    imu_session_id = make_id("imu_session")
    created_at = now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO imu_sessions (
                imu_session_id, pet_id, user_id, device_id, source, scenario,
                sensor_position, sample_rate_hz, duration_s, created_at,
                started_at, ended_at, status, notes
            )
            VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, '', '', 'simulated_pending', ?)
            """,
            (
                imu_session_id,
                str(pet_id),
                user_id,
                source,
                scenario or "",
                sensor_position,
                sample_rate_hz,
                duration_s,
                created_at,
                notes or "C2 placeholder only; samples will be generated in C3.",
            ),
        )
        connection.commit()
    return get_imu_session(user_id, imu_session_id)


def insert_imu_samples(imu_session_id: str, samples: list[dict]) -> int:
    if not samples:
        return 0
    created_at = now_iso()
    rows = []
    for sample in samples:
        timestamp_ms = _nullable_int(sample.get("timestamp_ms"))
        if timestamp_ms is None:
            raise HTTPException(status_code=400, detail="IMU sample timestamp_ms is required")
        rows.append(
            (
                make_id("imu_sample"),
                str(imu_session_id),
                timestamp_ms,
                _nullable_int(sample.get("seq")),
                _safe_float(sample.get("ax"), 0.0),
                _safe_float(sample.get("ay"), 0.0),
                _safe_float(sample.get("az"), 0.0),
                _safe_float(sample.get("gx"), 0.0),
                _safe_float(sample.get("gy"), 0.0),
                _safe_float(sample.get("gz"), 0.0),
                _nullable_float(sample.get("tail_angle_deg")),
                _nullable_int(sample.get("battery")),
                _nullable_int(sample.get("rssi")),
                created_at,
            )
        )
    with get_connection() as connection:
        connection.executemany(
            """
            INSERT INTO imu_samples (
                sample_id, imu_session_id, timestamp_ms, seq,
                ax, ay, az, gx, gy, gz, tail_angle_deg, battery, rssi, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
    return len(rows)


def count_imu_samples(imu_session_id: str) -> int:
    row = fetch_one(
        "SELECT COUNT(*) AS sample_count FROM imu_samples WHERE imu_session_id = ?",
        (str(imu_session_id),),
    )
    return int(row.get("sample_count", 0)) if row else 0


def get_imu_session_with_ownership(user_id: str, session_id: str) -> dict:
    return _require_owned_session(user_id, session_id)


def get_imu_session_sample_count(user_id: str, session_id: str) -> int:
    _require_owned_session(user_id, session_id)
    return count_imu_samples(session_id)


def get_imu_samples(user_id: str, session_id: str, limit: int | None = None) -> list[dict]:
    _require_owned_session(user_id, session_id)
    if limit is None:
        return fetch_all(
            "SELECT * FROM imu_samples WHERE imu_session_id = ? ORDER BY seq ASC, timestamp_ms ASC, sample_id ASC",
            (str(session_id),),
        )
    safe_limit = max(0, int(limit))
    return fetch_all(
        """
        SELECT * FROM imu_samples
        WHERE imu_session_id = ?
        ORDER BY seq ASC, timestamp_ms ASC, sample_id ASC
        LIMIT ?
        """,
        (str(session_id), safe_limit),
    )


def delete_imu_windows_for_session(imu_session_id: str) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM imu_windows WHERE imu_session_id = ?",
            (str(imu_session_id),),
        )
        connection.commit()
        return int(cursor.rowcount if cursor.rowcount is not None else 0)


def insert_imu_window_features(imu_session_id: str, features_list: list[dict]) -> int:
    if not features_list:
        return 0
    created_at = now_iso()
    rows = []
    for features in features_list:
        rows.append(
            (
                make_id("imu_window"),
                str(imu_session_id),
                _nullable_int(features.get("window_start_ms")),
                _nullable_int(features.get("window_end_ms")),
                _nullable_float(features.get("acc_mean")),
                _nullable_float(features.get("acc_std")),
                _nullable_float(features.get("acc_max")),
                _nullable_float(features.get("acc_rms")),
                _nullable_float(features.get("gyro_mean")),
                _nullable_float(features.get("gyro_std")),
                _nullable_float(features.get("gyro_max")),
                _nullable_float(features.get("gyro_p95")),
                _nullable_float(features.get("jerk_mean")),
                _nullable_float(features.get("jerk_max")),
                _nullable_int(features.get("peak_count")),
                _nullable_float(features.get("dominant_freq")),
                str(features.get("rule_motion_label") or "unknown"),
                _nullable_float(features.get("rule_motion_confidence")),
                "",
                None,
                created_at,
            )
        )
    with get_connection() as connection:
        connection.executemany(
            """
            INSERT INTO imu_windows (
                window_id, imu_session_id, window_start_ms, window_end_ms,
                acc_mean, acc_std, acc_max, acc_rms,
                gyro_mean, gyro_std, gyro_max, gyro_p95,
                jerk_mean, jerk_max, peak_count, dominant_freq,
                rule_motion_label, rule_motion_confidence,
                model_motion_label, model_motion_confidence, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
    return len(rows)


def get_imu_windows(user_id: str, session_id: str) -> list[dict]:
    _require_owned_session(user_id, session_id)
    return fetch_all(
        """
        SELECT
            window_id, imu_session_id, window_start_ms, window_end_ms,
            acc_mean, acc_std, acc_max, acc_rms,
            gyro_mean, gyro_std, gyro_max, gyro_p95,
            jerk_mean, jerk_max, peak_count, dominant_freq,
            rule_motion_label, rule_motion_confidence,
            model_motion_label, model_motion_confidence, created_at
        FROM imu_windows
        WHERE imu_session_id = ?
        ORDER BY window_start_ms ASC, window_id ASC
        """,
        (str(session_id),),
    )


def update_imu_session_status(imu_session_id: str, status: str, notes: str | None = None) -> None:
    with get_connection() as connection:
        if notes is None:
            connection.execute(
                "UPDATE imu_sessions SET status = ? WHERE imu_session_id = ?",
                (status, str(imu_session_id)),
            )
        else:
            connection.execute(
                "UPDATE imu_sessions SET status = ?, notes = ? WHERE imu_session_id = ?",
                (status, notes, str(imu_session_id)),
            )
        connection.commit()


def create_simulated_imu_session_with_samples(
    user_id: str,
    pet_id: str,
    source: str = "simulated",
    scenario: str = "still",
    sensor_position: str = "simulated_tail",
    sample_rate_hz: Any = 50,
    duration_s: Any = 10.0,
    noise_level: Any = 0.03,
    intensity: Any = 1.0,
    random_seed: int | None = None,
    notes: str = "",
) -> dict[str, Any]:
    _require_owned_pet(user_id, pet_id)
    validated = _validate_simulation_inputs(
        source,
        scenario,
        sensor_position,
        sample_rate_hz,
        duration_s,
        noise_level,
        intensity,
    )
    samples = generate_imu_samples(
        scenario=validated["scenario"],
        sample_rate_hz=validated["sample_rate_hz"],
        duration_s=validated["duration_s"],
        sensor_position=validated["sensor_position"],
        noise_level=validated["noise_level"],
        intensity=validated["intensity"],
        random_seed=random_seed,
    )
    safety_note = "simulated engineering assumption; not real hardware data; not hardware validation."
    session_notes = f"{safety_note} {get_simulation_note(validated['scenario'])}"
    if notes:
        session_notes = f"{session_notes} User note: {notes}"
    session = create_imu_session_placeholder(
        user_id=user_id,
        pet_id=str(pet_id),
        source=validated["source"],
        scenario=validated["scenario"],
        sensor_position=validated["sensor_position"],
        sample_rate_hz=validated["sample_rate_hz"],
        duration_s=validated["duration_s"],
        notes=session_notes,
    )
    sample_count = insert_imu_samples(session["imu_session_id"], samples)
    update_imu_session_status(session["imu_session_id"], "ready", session_notes)
    return {
        "session": get_imu_session(user_id, session["imu_session_id"]),
        "sample_count": sample_count,
        "first_timestamp_ms": samples[0]["timestamp_ms"] if samples else None,
        "last_timestamp_ms": samples[-1]["timestamp_ms"] if samples else None,
    }


def get_imu_session(user_id: str, session_id: str) -> dict:
    return _require_owned_session(user_id, session_id)


def list_imu_windows(user_id: str, session_id: str) -> list[dict]:
    return get_imu_windows(user_id, session_id)


def get_imu_session_summary(user_id: str, session_id: str) -> dict:
    session = _require_owned_session(user_id, session_id)
    sample_row = fetch_one(
        """
        SELECT
            COUNT(*) AS sample_count,
            MIN(timestamp_ms) AS first_timestamp_ms,
            MAX(timestamp_ms) AS last_timestamp_ms
        FROM imu_samples
        WHERE imu_session_id = ?
        """,
        (str(session_id),),
    )
    sample_count = int(sample_row.get("sample_count", 0)) if sample_row else 0
    windows = get_imu_windows(user_id, session_id)
    if windows:
        motion_summary = summarize_session_motion(windows)
        return {
            "imu_session_id": session_id,
            "scenario": session.get("scenario", ""),
            "source": session.get("source", ""),
            "sensor_position": session.get("sensor_position", ""),
            "sample_rate_hz": session.get("sample_rate_hz", 0),
            "duration_s": session.get("duration_s", 0),
            "sample_count": sample_count,
            "window_count": motion_summary["window_count"],
            "first_timestamp_ms": sample_row.get("first_timestamp_ms"),
            "last_timestamp_ms": sample_row.get("last_timestamp_ms"),
            "status": session.get("status", ""),
            "hardware_connected": False,
            "feature_status": "analyzed",
            "dominant_motion_label": motion_summary["dominant_motion_label"],
            "motion_confidence": motion_summary["motion_confidence"],
            "confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
            "motion_confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
            "label_counts": motion_summary["label_counts"],
            "warning": "simulated_or_engineering_assumption_not_hardware_validation",
        }

    if sample_count > 0:
        return {
            "imu_session_id": session_id,
            "scenario": session.get("scenario", ""),
            "source": session.get("source", ""),
            "sensor_position": session.get("sensor_position", ""),
            "sample_rate_hz": session.get("sample_rate_hz", 0),
            "duration_s": session.get("duration_s", 0),
            "sample_count": sample_count,
            "window_count": 0,
            "first_timestamp_ms": sample_row.get("first_timestamp_ms"),
            "last_timestamp_ms": sample_row.get("last_timestamp_ms"),
            "status": session.get("status", ""),
            "hardware_connected": False,
            "feature_status": "not_analyzed",
            "motion_label": None,
            "confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
            "motion_confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
            "message": f"请先调用 POST /api/imu/sessions/{session_id}/analyze 进行特征提取与规则分类。",
            "warning": "simulated_or_engineering_assumption_not_hardware_validation",
        }

    return {
        "imu_session_id": session_id,
        "scenario": session.get("scenario", ""),
        "source": session.get("source", ""),
        "sensor_position": session.get("sensor_position", ""),
        "sample_rate_hz": session.get("sample_rate_hz", 0),
        "duration_s": session.get("duration_s", 0),
        "sample_count": sample_count,
        "window_count": 0,
        "status": "not_ready",
        "feature_status": "not_analyzed",
        "motion_label": None,
        "confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
        "motion_confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
        "message": "当前 IMU session 尚无样本，无法进行特征提取与规则分类。",
        "hardware_connected": False,
        "warning": "simulated_or_engineering_assumption_not_hardware_validation",
    }


def get_imu_session_summary_placeholder(user_id: str, session_id: str) -> dict:
    return get_imu_session_summary(user_id, session_id)


def get_recognition_record_for_fusion(user_id: str, recognition_id: str) -> dict:
    record = fetch_one("SELECT * FROM recognition_records WHERE recognition_id = ?", (str(recognition_id),))
    if record is None:
        raise HTTPException(status_code=404, detail="Recognition record not found")
    if record.get("user_id") == user_id:
        return record
    pet_id = str(record.get("pet_id") or "")
    if pet_id:
        pet = fetch_one("SELECT * FROM pets WHERE pet_id = ?", (pet_id,))
        if pet and pet.get("owner_user_id") == user_id:
            return record
    raise HTTPException(status_code=403, detail="Cannot access another user's recognition record")


def save_multimodal_emotion_record(user_id: str, record_payload: dict) -> dict:
    if not isinstance(record_payload, dict):
        raise HTTPException(status_code=400, detail="Invalid multimodal record payload")
    pet_id = str(record_payload.get("pet_id") or "")
    if not pet_id:
        raise HTTPException(status_code=400, detail="pet_id is required")
    _require_owned_pet(user_id, pet_id)

    imu_session_id = str(record_payload.get("imu_session_id") or "")
    if imu_session_id:
        session = _require_owned_session(user_id, imu_session_id)
        if str(session.get("pet_id") or "") != pet_id:
            raise HTTPException(status_code=400, detail="IMU session pet_id does not match fusion pet_id")

    recognition_id = str(record_payload.get("recognition_id") or "")
    if recognition_id:
        recognition = get_recognition_record_for_fusion(user_id, recognition_id)
        if str(recognition.get("pet_id") or "") and str(recognition.get("pet_id") or "") != pet_id:
            raise HTTPException(status_code=400, detail="Recognition pet_id does not match fusion pet_id")

    record_id = make_id("multimodal")
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO multimodal_emotion_records (
                record_id, pet_id, user_id, recognition_id, imu_session_id,
                audio_label, audio_confidence, audio_prediction_label,
                imu_motion_label, imu_motion_confidence,
                fused_label, fused_confidence, fusion_method, confidence_type,
                fusion_notes, safety_message, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                pet_id,
                user_id,
                recognition_id,
                imu_session_id,
                str(record_payload.get("audio_label") or ""),
                _safe_float(record_payload.get("audio_confidence"), 0.0),
                str(record_payload.get("audio_label") or ""),
                str(record_payload.get("imu_motion_label") or ""),
                _safe_float(record_payload.get("imu_motion_confidence"), 0.0),
                str(record_payload.get("fused_label") or ""),
                _safe_float(record_payload.get("fused_confidence"), 0.0),
                str(record_payload.get("fusion_method") or ""),
                str(record_payload.get("confidence_type") or ""),
                str(record_payload.get("fusion_notes") or ""),
                str(record_payload.get("safety_message") or ""),
                now_iso(),
            ),
        )
        connection.commit()
    return get_multimodal_emotion_record(user_id, record_id)


def get_multimodal_emotion_record(user_id: str, record_id: str) -> dict:
    record = fetch_one("SELECT * FROM multimodal_emotion_records WHERE record_id = ?", (str(record_id),))
    if record is None:
        raise HTTPException(status_code=404, detail="Multimodal emotion record not found")
    if record.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Cannot access another user's multimodal record")
    return record


def list_multimodal_emotion_records(user_id: str, pet_id: str | None = None) -> list[dict]:
    if pet_id:
        _require_owned_pet(user_id, str(pet_id))
        return fetch_all(
            """
            SELECT * FROM multimodal_emotion_records
            WHERE user_id = ? AND pet_id = ?
            ORDER BY created_at DESC, record_id DESC
            """,
            (user_id, str(pet_id)),
        )
    return fetch_all(
        """
        SELECT * FROM multimodal_emotion_records
        WHERE user_id = ?
        ORDER BY created_at DESC, record_id DESC
        """,
        (user_id,),
    )


def create_imu_annotation(user_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid annotation payload")
    imu_session_id = str(payload.get("imu_session_id") or "")
    window_id = str(payload.get("window_id") or "")
    pet_id = str(payload.get("pet_id") or "")

    if window_id:
        window = _require_owned_window(user_id, window_id)
        session = _require_owned_session(user_id, window.get("imu_session_id", ""))
        imu_session_id = session["imu_session_id"]
        pet_id = session["pet_id"]
    elif imu_session_id:
        session = _require_owned_session(user_id, imu_session_id)
        pet_id = session["pet_id"]
    elif pet_id:
        _require_owned_pet(user_id, pet_id)
    else:
        raise HTTPException(status_code=400, detail="imu_session_id, window_id, or pet_id is required")

    motion_label_user = str(payload.get("motion_label_user") or "")
    emotion_context_label_user = str(payload.get("emotion_context_label_user") or "")
    quality_label = str(payload.get("quality_label") or "")
    if motion_label_user and motion_label_user not in MOTION_LABELS:
        raise HTTPException(status_code=400, detail="Unsupported motion_label_user")
    if emotion_context_label_user and emotion_context_label_user not in EMOTION_CONTEXT_LABELS:
        raise HTTPException(status_code=400, detail="Unsupported emotion_context_label_user")
    if quality_label not in QUALITY_LABELS:
        raise HTTPException(status_code=400, detail="Unsupported quality_label")

    annotation_id = make_id("imu_annotation")
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO imu_annotations (
                annotation_id, imu_session_id, window_id, user_id, pet_id,
                motion_label_user, emotion_context_label_user, quality_label,
                annotation_source, comment, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                annotation_id,
                imu_session_id,
                window_id,
                user_id,
                pet_id,
                motion_label_user,
                emotion_context_label_user,
                quality_label,
                str(payload.get("annotation_source") or "manual_c2_placeholder"),
                str(payload.get("comment") or ""),
                now_iso(),
            ),
        )
        connection.commit()
    return fetch_one("SELECT * FROM imu_annotations WHERE annotation_id = ?", (annotation_id,)) or {"annotation_id": annotation_id}


def export_training_candidates_placeholder(user_id: str) -> dict:
    return {
        "status": "not_implemented",
        "user_id": user_id,
        "message": "C2 仅建立 API 骨架；训练候选导出将在 C6 实现。",
        "hardware_connected": False,
    }


def save_multimodal_record_placeholder(user_id: str, payload: dict) -> dict:
    return {
        "status": "not_implemented",
        "user_id": user_id,
        "message": "C2 仅建立 API 骨架；fusion save 将在 C5/C6 之后接入安全保存流程。",
        "fusion_method": FUSION_METHOD_PLACEHOLDER,
        "confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
        "hardware_connected": False,
    }
