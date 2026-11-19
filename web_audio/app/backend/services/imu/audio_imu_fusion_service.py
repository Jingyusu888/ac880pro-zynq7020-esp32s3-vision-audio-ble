from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .imu_schema import CONFIDENCE_TYPE_RULE_SCORE, FUSION_METHOD_RULE_V1
from .imu_storage_service import (
    get_imu_session_summary,
    get_imu_session_with_ownership,
    get_recognition_record_for_fusion,
    save_multimodal_emotion_record,
)


AUDIO_LABELS = {
    "affiliative_relaxed",
    "request_seeking",
    "threat_discomfort",
    "pain_distress",
    "uncertain",
}

IMU_MOTION_LABELS = {
    "still",
    "body_active",
    "body_intense",
    "tail_sway",
    "tail_flick_or_agitation",
    "unknown",
}

DEFAULT_SAFETY_MESSAGE = (
    "Audio + simulated IMU fusion is rule-based observation support only; "
    "it is not a clinical conclusion or real-hardware validation."
)
DISTRESS_SAFETY_MESSAGE = (
    "distress_attention_needed means distress attention reminder only. "
    "Observe context and consult a veterinarian if abnormal signs continue."
)
SIMULATED_IMU_SAFETY_MESSAGE = "Current IMU data is simulated or engineering_assumption, not real hardware collection."


def get_audio_result_for_fusion(user_id: str, recognition_id: str) -> dict:
    record = get_recognition_record_for_fusion(user_id, recognition_id)
    return {
        "recognition_id": record.get("recognition_id", ""),
        "pet_id": record.get("pet_id", ""),
        "user_id": record.get("user_id", "") or user_id,
        "audio_label": record.get("prediction_label") or "uncertain",
        "audio_confidence": _confidence(record.get("confidence"), 0.5),
        "audio_source": "recognition_records",
    }


def get_imu_result_for_fusion(user_id: str, imu_session_id: str) -> dict:
    session = get_imu_session_with_ownership(user_id, imu_session_id)
    summary = get_imu_session_summary(user_id, imu_session_id)
    dominant_label = summary.get("dominant_motion_label")
    if not dominant_label:
        return {
            "status": "need_analyze",
            "message": f"该 IMU session 尚未完成 C4 特征提取与规则动作分类，请先调用 /api/imu/sessions/{imu_session_id}/analyze。",
            "hardware_connected": False,
        }
    return {
        "status": "ok",
        "imu_session_id": session.get("imu_session_id", ""),
        "pet_id": session.get("pet_id", ""),
        "user_id": session.get("user_id", ""),
        "source": session.get("source", ""),
        "scenario": session.get("scenario", ""),
        "imu_motion_label": dominant_label,
        "imu_motion_confidence": _confidence(summary.get("motion_confidence"), 0.5),
        "label_counts": summary.get("label_counts", {}),
        "window_count": summary.get("window_count", 0),
    }


def fuse_audio_imu(audio_result: dict, imu_result: dict) -> dict:
    audio_label = str(audio_result.get("audio_label") or "uncertain")
    imu_label = str(imu_result.get("imu_motion_label") or "unknown")
    audio_confidence = _confidence(audio_result.get("audio_confidence"), 0.5)
    imu_confidence = _confidence(imu_result.get("imu_motion_confidence"), 0.5)

    fused_label, notes = _fusion_label_and_notes(audio_label, imu_label)
    fused_confidence = 0.65 * audio_confidence + 0.35 * imu_confidence
    fused_confidence += _support_adjustment(audio_label, imu_label)
    fused_confidence -= _weak_evidence_penalty(audio_label, imu_label)
    fused_confidence = round(max(0.0, min(1.0, fused_confidence)), 3)

    safety_message = _safety_message(audio_label, fused_label, str(imu_result.get("source") or ""))
    return {
        "audio_label": audio_label,
        "audio_confidence": audio_confidence,
        "imu_motion_label": imu_label,
        "imu_motion_confidence": imu_confidence,
        "fused_label": fused_label,
        "fused_confidence": fused_confidence,
        "fusion_notes": notes,
        "safety_message": safety_message,
        "fusion_method": FUSION_METHOD_RULE_V1,
        "confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
    }


def preview_fusion(user_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid fusion payload")
    imu_session_id = str(payload.get("imu_session_id") or "")
    if not imu_session_id:
        raise HTTPException(status_code=400, detail="imu_session_id is required")

    imu_result = get_imu_result_for_fusion(user_id, imu_session_id)
    if imu_result.get("status") == "need_analyze":
        return imu_result

    recognition_id = str(payload.get("recognition_id") or "")
    if recognition_id:
        audio_result = get_audio_result_for_fusion(user_id, recognition_id)
    else:
        audio_result = {
            "recognition_id": "",
            "pet_id": imu_result.get("pet_id", ""),
            "user_id": user_id,
            "audio_label": str(payload.get("audio_label") or "uncertain"),
            "audio_confidence": _confidence(payload.get("audio_confidence"), 0.5),
            "audio_source": "direct_input_for_test",
        }

    audio_pet_id = str(audio_result.get("pet_id") or "")
    imu_pet_id = str(imu_result.get("pet_id") or "")
    if audio_pet_id and imu_pet_id and audio_pet_id != imu_pet_id:
        raise HTTPException(status_code=400, detail="recognition_id and imu_session_id belong to different pets")

    fusion = fuse_audio_imu(audio_result, imu_result)
    return {
        "status": "ok",
        "recognition_id": audio_result.get("recognition_id", ""),
        "imu_session_id": imu_result.get("imu_session_id", ""),
        "pet_id": imu_pet_id or audio_pet_id,
        "user_id": user_id,
        "audio_source": audio_result.get("audio_source", ""),
        "label_counts": imu_result.get("label_counts", {}),
        "window_count": imu_result.get("window_count", 0),
        "hardware_connected": False,
        **fusion,
    }


def save_fusion_record(user_id: str, payload: dict) -> dict:
    preview = preview_fusion(user_id, payload)
    if preview.get("status") != "ok":
        return preview
    record = save_multimodal_emotion_record(user_id, preview)
    return {
        **preview,
        "status": "saved",
        "record_id": record["record_id"],
        "record": record,
        "hardware_connected": False,
    }


def _fusion_label_and_notes(audio_label: str, imu_label: str) -> tuple[str, str]:
    if audio_label not in AUDIO_LABELS or imu_label not in IMU_MOTION_LABELS:
        return "unknown_multimodal", "音频或 IMU 动作标签不在当前规则表内，因此返回 unknown_multimodal。"
    if audio_label == "affiliative_relaxed" and imu_label in {"still", "tail_sway"}:
        return "relaxed_or_affiliative", "声音偏亲和/放松，IMU 显示静止或规律摆动，因此输出亲和或放松倾向。"
    if audio_label == "affiliative_relaxed" and imu_label in {"body_active", "body_intense"}:
        return "active_play_or_excitement", "声音偏亲和，但 IMU 显示活动或剧烈活动，因此输出活跃玩耍或兴奋倾向。"
    if audio_label == "request_seeking" and imu_label in {"body_active", "tail_sway"}:
        return "active_request", "请求类叫声 + 主动活动或摆动，可能表示索取、靠近、求关注。"
    if audio_label == "request_seeking" and imu_label in {"still", "unknown"}:
        return "audio_only_uncertain_motion", "音频有请求倾向，但 IMU 运动证据弱或未知。"
    if audio_label == "threat_discomfort" and imu_label in {"tail_flick_or_agitation", "body_intense"}:
        return "alert_or_discomfort", "音频显示威胁/不适倾向，同时 IMU 动作摘要显示快速甩动或躁动，因此输出警觉或不适倾向增强。"
    if audio_label == "threat_discomfort":
        return "alert_or_discomfort", "音频显示威胁/不适倾向；IMU 证据较弱或不强支持，但不能否定该倾向。"
    if audio_label == "pain_distress":
        return "distress_attention_needed", "音频存在 distress 倾向，无论 IMU 是否强支持，都建议用户结合现场情况关注。"
    if audio_label == "uncertain" and imu_label in {"tail_flick_or_agitation", "body_intense"}:
        return "motion_alert_uncertain_audio", "音频不确定，但 IMU 显示强烈运动或躁动，因此提示运动异常或可能受刺激。"
    if audio_label == "uncertain" and imu_label in {"body_active", "tail_sway"}:
        return "active_play_or_excitement", "音频证据不足，但 IMU 显示活动或规律摆动，因此仅输出活跃/玩耍/兴奋倾向。"
    if audio_label == "uncertain" and imu_label in {"still", "unknown"}:
        return "unknown_multimodal", "音频和 IMU 都不足以判断。"
    return "unknown_multimodal", "当前组合未命中明确规则，因此返回 unknown_multimodal。"


def _support_adjustment(audio_label: str, imu_label: str) -> float:
    if audio_label == "affiliative_relaxed" and imu_label in {"still", "tail_sway"}:
        return 0.10
    if audio_label == "request_seeking" and imu_label in {"body_active", "tail_sway"}:
        return 0.10
    if audio_label == "threat_discomfort" and imu_label in {"tail_flick_or_agitation", "body_intense"}:
        return 0.10
    if audio_label == "pain_distress" and imu_label in {"body_intense", "tail_flick_or_agitation", "still"}:
        return 0.10
    if audio_label == "uncertain" and imu_label in {"tail_flick_or_agitation", "body_intense"}:
        return 0.05
    return 0.0


def _weak_evidence_penalty(audio_label: str, imu_label: str) -> float:
    if audio_label != "uncertain" and imu_label == "unknown":
        return 0.10
    if audio_label == "request_seeking" and imu_label == "still":
        return 0.10
    if audio_label == "affiliative_relaxed" and imu_label == "tail_flick_or_agitation":
        return 0.10
    return 0.0


def _safety_message(audio_label: str, fused_label: str, imu_source: str) -> str:
    messages = [DEFAULT_SAFETY_MESSAGE]
    if audio_label == "pain_distress" or fused_label == "distress_attention_needed":
        messages.append(DISTRESS_SAFETY_MESSAGE)
    if imu_source in {"simulated", "engineering_assumption"}:
        messages.append(SIMULATED_IMU_SAFETY_MESSAGE)
    return " ".join(messages)


def _confidence(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    return round(max(0.0, min(1.0, result)), 3)
