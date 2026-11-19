from __future__ import annotations

from fastapi import APIRouter, Request

from ..services.current_user_service import require_current_user_id
from ..services.imu.audio_imu_fusion_service import preview_fusion, save_fusion_record
from ..services.imu.imu_annotation_service import create_imu_annotation, list_imu_annotations
from ..services.imu.imu_candidate_service import (
    add_annotation_to_training_candidates,
    export_training_candidates,
    list_training_candidates,
)
from ..services.imu.imu_feature_service import analyze_imu_session
from ..services.imu.imu_model_registry import (
    get_active_imu_model,
    list_imu_models,
    register_candidate_from_report,
)
from ..services.imu.imu_storage_service import (
    create_simulated_imu_session_with_samples,
    get_imu_session,
    get_imu_session_summary,
    get_imu_windows,
    get_imu_status,
)


router = APIRouter(prefix="/imu", tags=["imu"])


@router.get("/status")
def imu_status() -> dict:
    return get_imu_status()


@router.post("/sessions/simulate")
def create_simulated_session(payload: dict, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    result = create_simulated_imu_session_with_samples(
        user_id=user_id,
        pet_id=str(payload.get("pet_id") or ""),
        source=str(payload.get("source") or "simulated"),
        scenario=str(payload.get("scenario") or "still"),
        sensor_position=str(payload.get("sensor_position") or "simulated_tail"),
        sample_rate_hz=payload.get("sample_rate_hz", 50),
        duration_s=payload.get("duration_s", 10),
        noise_level=payload.get("noise_level") if payload.get("noise_level") is not None else 0.03,
        intensity=payload.get("intensity") if payload.get("intensity") is not None else 1.0,
        random_seed=payload.get("random_seed"),
        notes=str(payload.get("notes") or ""),
    )
    session = result["session"]
    return {
        "imu_session_id": session["imu_session_id"],
        "status": session.get("status", "ready"),
        "source": session.get("source", ""),
        "scenario": session.get("scenario", ""),
        "sensor_position": session.get("sensor_position", ""),
        "sample_rate_hz": session.get("sample_rate_hz", 0),
        "duration_s": session.get("duration_s", 0),
        "sample_count": result["sample_count"],
        "hardware_connected": False,
        "message": "已生成工程假设 IMU 模拟数据；该数据不是真实硬件采集。",
        "session": session,
    }


@router.post("/sessions")
def create_session_legacy_placeholder(payload: dict, request: Request) -> dict:
    return create_simulated_session(payload, request)


@router.post("/sessions/{session_id}/analyze")
def analyze_session(session_id: str, request: Request, payload: dict | None = None) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    payload = payload or {}
    return analyze_imu_session(
        user_id=user_id,
        imu_session_id=session_id,
        window_size_s=payload.get("window_size_s", 2.0),
        step_size_s=payload.get("step_size_s", 1.0),
        replace_existing=payload.get("replace_existing", True),
    )


@router.get("/sessions/{session_id}/summary")
def get_session_summary(session_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    return get_imu_session_summary(user_id, session_id)


@router.get("/sessions/{session_id}/windows")
def get_session_windows(session_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    return {
        "imu_session_id": session_id,
        "windows": get_imu_windows(user_id, session_id),
        "hardware_connected": False,
        "warning": "simulated_or_engineering_assumption_not_hardware_validation",
    }


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    return {
        "session": get_imu_session(user_id, session_id),
        "hardware_connected": False,
    }


@router.post("/annotations")
def post_annotation(payload: dict, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    annotation = create_imu_annotation(user_id, payload)
    return {
        "status": "ok",
        "annotation_id": annotation["annotation_id"],
        "quality_label": annotation["quality_label"],
        "message": "IMU annotation saved.",
        "annotation": annotation,
        "hardware_connected": False,
    }


@router.get("/annotations")
def get_annotations(request: Request, pet_id: str = "", imu_session_id: str = "") -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    return {
        "annotations": list_imu_annotations(user_id, pet_id or None, imu_session_id or None),
        "hardware_connected": False,
    }


@router.post("/training-candidates/add")
def add_training_candidates(payload: dict, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    annotation_id = str(payload.get("annotation_id") or "")
    return add_annotation_to_training_candidates(user_id, annotation_id)


@router.get("/training-candidates")
def get_training_candidates(request: Request, pet_id: str = "", quality_status: str = "") -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    return {
        "candidates": list_training_candidates(user_id, pet_id or None, quality_status or None),
        "hardware_connected": False,
    }


@router.post("/training-candidates/export")
def export_training_candidates_endpoint(request: Request, payload: dict | None = None) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    payload = payload or {}
    return export_training_candidates(user_id, str(payload.get("export_name") or "imu_training_ready_v1"))


@router.get("/models")
def get_models() -> dict:
    return list_imu_models()


@router.get("/models/active")
def get_active_model() -> dict:
    return get_active_imu_model()


@router.post("/models/register-candidate")
def register_candidate_model(payload: dict, request: Request) -> dict:
    require_current_user_id(request, allow_legacy_fallback=False)
    return register_candidate_from_report(
        model_id=str(payload.get("model_id") or ""),
        model_path=str(payload.get("model_path") or ""),
        report_path=str(payload.get("report_path") or ""),
        feature_schema_path=str(payload.get("feature_schema_path") or ""),
        notes=str(payload.get("notes") or "") or None,
    )


@router.post("/fusion/preview")
def preview_fusion_endpoint(payload: dict, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    return preview_fusion(user_id, payload)


@router.post("/fusion/save")
def save_fusion_endpoint(payload: dict, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    return save_fusion_record(user_id, payload)
