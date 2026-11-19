from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any


SUPPORTED_SOURCES = ["simulated", "future_file_upload", "future_serial", "future_ble"]
MOTION_LABELS = {
    "still",
    "walking",
    "running",
    "tail_sway_slow",
    "tail_sway_fast",
    "tail_flick",
    "agitation_possible",
    "unknown",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _is_number(value: Any) -> bool:
    try:
        number = float(value)
        return math.isfinite(number)
    except (TypeError, ValueError):
        return False


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def _normalize_sample(sample: dict) -> dict:
    return {
        "device_id": str(sample.get("device_id") or ""),
        "pet_id": str(sample.get("pet_id") or ""),
        "timestamp_ms": int(_safe_float(sample.get("timestamp_ms"), 0)),
        "seq": _coerce_optional_int(sample.get("seq")),
        "ax": _safe_float(sample.get("ax")),
        "ay": _safe_float(sample.get("ay")),
        "az": _safe_float(sample.get("az")),
        "gx": _safe_float(sample.get("gx")),
        "gy": _safe_float(sample.get("gy")),
        "gz": _safe_float(sample.get("gz")),
        "tail_angle": None if sample.get("tail_angle") in (None, "") else _safe_float(sample.get("tail_angle")),
        "battery": None if sample.get("battery") in (None, "") else _coerce_optional_int(sample.get("battery")),
        "rssi": None if sample.get("rssi") in (None, "") else _coerce_optional_int(sample.get("rssi")),
    }


def validate_imu_sample(sample: dict) -> bool:
    if not isinstance(sample, dict):
        return False
    if sample.get("timestamp_ms") in (None, ""):
        return False
    if not _is_number(sample.get("timestamp_ms")):
        return False
    for field in ("ax", "ay", "az", "gx", "gy", "gz"):
        if not _is_number(sample.get(field)):
            return False
    if sample.get("seq") not in (None, "") and _coerce_optional_int(sample.get("seq")) is None:
        return False
    return True


def parse_imu_packet(packet: dict) -> dict:
    if not isinstance(packet, dict):
        packet = {}
    raw_samples = packet.get("samples")
    if raw_samples is None and isinstance(packet.get("sample"), dict):
        raw_samples = [packet["sample"]]
    if raw_samples is None and any(key in packet for key in ("timestamp_ms", "ax", "ay", "az", "gx", "gy", "gz")):
        raw_samples = [packet]
    if not isinstance(raw_samples, list):
        raw_samples = []

    device_id = str(packet.get("device_id") or "")
    pet_id = str(packet.get("pet_id") or "")
    samples = []
    invalid_count = 0
    for raw_sample in raw_samples:
        if not isinstance(raw_sample, dict) or not validate_imu_sample(raw_sample):
            invalid_count += 1
            continue
        normalized = _normalize_sample(raw_sample)
        if not normalized["device_id"]:
            normalized["device_id"] = device_id
        if not normalized["pet_id"]:
            normalized["pet_id"] = pet_id
        samples.append(normalized)

    return {
        "session_id": str(packet.get("session_id") or packet.get("imu_session_id") or ""),
        "device_id": device_id,
        "pet_id": pet_id,
        "sample_rate_hz": _safe_float(packet.get("sample_rate_hz"), 0),
        "samples": samples,
        "invalid_sample_count": invalid_count,
        "mode": "mock_or_file_upload_only",
        "hardware_connected": False,
    }


def _magnitude(sample: dict, fields: tuple[str, str, str]) -> float:
    return math.sqrt(sum(_safe_float(sample.get(field)) ** 2 for field in fields))


def _count_peaks(values: list[float]) -> int:
    if len(values) < 3:
        return 0
    center = mean(values)
    spread = pstdev(values) if len(values) > 1 else 0.0
    threshold = center + max(spread * 1.15, 0.08)
    peaks = 0
    for index in range(1, len(values) - 1):
        if values[index] > threshold and values[index] > values[index - 1] and values[index] >= values[index + 1]:
            peaks += 1
    return peaks


def _duration_ms(samples: list[dict]) -> int:
    timestamps = [int(_safe_float(sample.get("timestamp_ms"), 0)) for sample in samples if sample.get("timestamp_ms") not in (None, "")]
    if len(timestamps) < 2:
        return 0
    return max(timestamps) - min(timestamps)


def summarize_tail_motion(samples: list) -> dict:
    valid_samples = [sample for sample in samples if isinstance(sample, dict) and validate_imu_sample(sample)]
    if not valid_samples:
        return {
            "sample_count": 0,
            "duration_ms": 0,
            "accel_mean": 0.0,
            "accel_std": 0.0,
            "gyro_mean": 0.0,
            "gyro_std": 0.0,
            "peak_count": 0,
            "estimated_motion_intensity": "unknown",
            "data_quality": "too_short",
        }

    accel_values = [_magnitude(sample, ("ax", "ay", "az")) for sample in valid_samples]
    gyro_values = [_magnitude(sample, ("gx", "gy", "gz")) for sample in valid_samples]
    accel_std = pstdev(accel_values) if len(accel_values) > 1 else 0.0
    gyro_std = pstdev(gyro_values) if len(gyro_values) > 1 else 0.0
    peak_count = _count_peaks(gyro_values)
    duration_ms = _duration_ms(valid_samples)
    sample_count = len(valid_samples)

    if sample_count < 8 or duration_ms < 150:
        data_quality = "too_short"
    else:
        data_quality = "ok"

    activity_score = accel_std * 2.5 + gyro_std / 90.0 + peak_count / max(sample_count, 1)
    if data_quality != "ok":
        intensity = "unknown"
    elif activity_score < 0.08:
        intensity = "low"
    elif activity_score < 0.35:
        intensity = "medium"
    else:
        intensity = "high"

    return {
        "sample_count": sample_count,
        "duration_ms": duration_ms,
        "accel_mean": round(mean(accel_values), 6),
        "accel_std": round(accel_std, 6),
        "gyro_mean": round(mean(gyro_values), 6),
        "gyro_std": round(gyro_std, 6),
        "peak_count": peak_count,
        "estimated_motion_intensity": intensity,
        "data_quality": data_quality,
    }


def classify_motion_summary(summary: dict) -> dict:
    if not isinstance(summary, dict) or summary.get("data_quality") != "ok":
        return {
            "imu_motion_label": "unknown",
            "confidence": 0.0,
            "notes": "IMU data is too short or invalid for rule-based placeholder analysis.",
            "mode": "rule_based_placeholder",
        }

    accel_std = _safe_float(summary.get("accel_std"))
    gyro_mean = _safe_float(summary.get("gyro_mean"))
    gyro_std = _safe_float(summary.get("gyro_std"))
    peak_count = int(_safe_float(summary.get("peak_count"), 0))
    duration_seconds = max(_safe_float(summary.get("duration_ms"), 0) / 1000.0, 0.001)
    peak_rate = peak_count / duration_seconds

    label = "unknown"
    confidence = 0.35
    notes = "Rule-based placeholder could not identify a strong motion pattern."

    if accel_std < 0.025 and gyro_std < 3.0 and gyro_mean < 2.0:
        label = "still"
        confidence = 0.72
        notes = "Low acceleration and gyro variance suggests stillness."
    elif (accel_std >= 0.18 and gyro_mean >= 50.0) or gyro_std >= 80.0 or (peak_rate >= 8.0 and gyro_mean >= 50.0):
        label = "agitation_possible"
        confidence = 0.62
        notes = "High-frequency or high-amplitude motion suggests possible agitation."
    elif peak_count >= 1 and gyro_std >= 25.0 and peak_count <= 4:
        label = "tail_flick"
        confidence = 0.66
        notes = "Short sharp gyro spikes suggest a tail flick."
    elif peak_count >= 3 and gyro_std < 8.0 and peak_rate < 3.0:
        label = "tail_sway_slow"
        confidence = 0.58
        notes = "Repeated low-intensity gyro peaks suggest slow tail sway."
    elif peak_count >= 5 and gyro_std < 55.0 and peak_rate >= 1.8:
        label = "tail_sway_fast"
        confidence = 0.64
        notes = "Frequent moderate gyro peaks suggest fast tail sway."
    elif accel_std >= 0.12 or gyro_std >= 25.0:
        label = "walking"
        confidence = 0.52
        notes = "Moderate body motion suggests walking or active movement."

    return {
        "imu_motion_label": label,
        "confidence": round(confidence, 3),
        "notes": notes,
        "mode": "rule_based_placeholder",
    }


def fuse_audio_imu_emotion(audio_result: dict, imu_summary: dict) -> dict:
    audio_result = audio_result if isinstance(audio_result, dict) else {}
    imu_summary = imu_summary if isinstance(imu_summary, dict) else {}
    audio_label = str(
        audio_result.get("prediction_label")
        or audio_result.get("final_prediction")
        or audio_result.get("audio_label")
        or audio_result.get("label")
        or "unknown"
    )

    motion = (
        imu_summary.get("imu_motion_label")
        or imu_summary.get("motion_label")
        or imu_summary.get("tail_motion_label")
    )
    if not motion:
        motion = classify_motion_summary(imu_summary).get("imu_motion_label", "unknown")
    motion = str(motion)
    audio_confidence = _safe_float(audio_result.get("confidence"), 0.45)
    imu_confidence = _safe_float(imu_summary.get("confidence") or imu_summary.get("motion_confidence"), 0.45)

    fused_label = "multimodal_uncertain"
    notes = "Rule-based placeholder fusion does not have a strong matching rule."
    confidence = min(0.55, max(audio_confidence, imu_confidence, 0.35))

    if audio_label == "affiliative_relaxed" and motion in {"still", "tail_sway_slow"}:
        fused_label = "relaxed_or_affiliative"
        confidence = 0.68
        notes = "Relaxed audio plus still or slow tail motion supports an affiliative state."
    elif audio_label == "request_seeking" and motion in {"walking", "tail_sway_fast", "running"}:
        fused_label = "active_request"
        confidence = 0.64
        notes = "Request-like audio with active motion suggests an active request."
    elif audio_label == "threat_discomfort" and motion in {"agitation_possible", "tail_flick"}:
        fused_label = "discomfort_or_alert"
        confidence = 0.7
        notes = "Discomfort audio plus sharp or agitated motion suggests alert or discomfort."
    elif audio_label == "pain_distress" and motion in {"still", "abnormal_low_motion"}:
        fused_label = "distress_attention_needed"
        confidence = 0.66
        notes = "Distress audio with low motion should be reviewed carefully; this is not a medical diagnosis."
    elif audio_label in {"uncertain", "unknown"} and motion == "agitation_possible":
        fused_label = "motion_alert_uncertain_audio"
        confidence = 0.56
        notes = "Audio is uncertain, but IMU motion looks unusually active."
    elif audio_label and audio_label not in {"unknown", "uncertain"}:
        fused_label = f"audio_{audio_label}_imu_{motion}"
        confidence = min(0.6, max(audio_confidence * 0.75, 0.4))
        notes = "No strong multimodal rule matched; returning a transparent placeholder combination."

    return {
        "audio_label": audio_label,
        "audio_prediction_label": audio_label,
        "imu_motion_label": motion if motion in MOTION_LABELS or motion == "abnormal_low_motion" else "unknown",
        "fused_label": fused_label,
        "fused_confidence": round(confidence, 3),
        "fusion_notes": f"{notes} Current mode is a rule-based placeholder, not a formal multimodal model.",
        "mode": "rule_based_placeholder",
    }


def imu_status() -> dict[str, Any]:
    return {
        "available": False,
        "status": "interface_reserved",
        "mode": "mock_or_file_upload_only",
        "supported_sources": SUPPORTED_SOURCES,
        "fusion_mode": "rule_based_placeholder",
    }
