from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any

from fastapi import HTTPException

from .imu_schema import CONFIDENCE_TYPE_RULE_SCORE
from .imu_rule_classifier import classify_window_rule, summarize_session_motion
from .imu_storage_service import (
    delete_imu_windows_for_session,
    get_imu_samples,
    get_imu_session_with_ownership,
    insert_imu_window_features,
)

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency guard
    np = None


REQUIRED_SAMPLE_FIELDS = ("timestamp_ms", "ax", "ay", "az", "gx", "gy", "gz")


def analyze_imu_session(
    user_id: str,
    imu_session_id: str,
    window_size_s: float = 2.0,
    step_size_s: float = 1.0,
    replace_existing: bool = True,
) -> dict:
    session = get_imu_session_with_ownership(user_id, imu_session_id)
    samples = get_imu_samples(user_id, imu_session_id)
    sample_count = len(samples)
    if sample_count < 3:
        if replace_existing:
            delete_imu_windows_for_session(imu_session_id)
        return {
            "imu_session_id": imu_session_id,
            "status": "too_short",
            "sample_count": sample_count,
            "window_count": 0,
            "dominant_motion_label": "unknown",
            "motion_confidence": 0.0,
            "confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
            "motion_confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
            "label_counts": {},
            "hardware_connected": False,
            "warning": "simulated_or_engineering_assumption_not_hardware_validation",
        }

    sample_rate_hz = _positive_float(session.get("sample_rate_hz")) or estimate_sample_rate(samples)
    windows = slice_samples_into_windows(samples, window_size_s, step_size_s, sample_rate_hz)
    if replace_existing:
        delete_imu_windows_for_session(imu_session_id)
    if not windows:
        return {
            "imu_session_id": imu_session_id,
            "status": "too_short",
            "sample_count": sample_count,
            "window_count": 0,
            "dominant_motion_label": "unknown",
            "motion_confidence": 0.0,
            "confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
            "motion_confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
            "label_counts": {},
            "hardware_connected": False,
            "warning": "simulated_or_engineering_assumption_not_hardware_validation",
        }

    feature_rows = []
    for window in windows:
        features = compute_window_features(window, sample_rate_hz)
        rule_result = classify_window_rule(features)
        feature_rows.append({**features, **rule_result})

    inserted_count = insert_imu_windows(imu_session_id, feature_rows)
    motion_summary = summarize_session_motion(feature_rows)
    return {
        "imu_session_id": imu_session_id,
        "status": "analyzed",
        "sample_count": sample_count,
        "inserted_window_count": inserted_count,
        "hardware_connected": False,
        "confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
        "motion_confidence_type": CONFIDENCE_TYPE_RULE_SCORE,
        "warning": "simulated_or_engineering_assumption_not_hardware_validation",
        **motion_summary,
    }


def compute_window_features(samples: list[dict], sample_rate_hz: float | None = None) -> dict:
    if len(samples) < 3:
        return {
            "feature_status": "too_short",
            "window_start_ms": _safe_int(samples[0].get("timestamp_ms")) if samples else None,
            "window_end_ms": _safe_int(samples[-1].get("timestamp_ms")) if samples else None,
        }
    sorted_samples = _sorted_samples(samples)
    _validate_samples(sorted_samples)
    estimated_rate = sample_rate_hz or estimate_sample_rate(sorted_samples)
    if estimated_rate <= 0:
        raise HTTPException(status_code=400, detail="Cannot estimate IMU sample rate")

    acc_mag = []
    gyro_mag = []
    gyro_axes = {"gx": [], "gy": [], "gz": []}
    for sample in sorted_samples:
        ax = _num(sample.get("ax"))
        ay = _num(sample.get("ay"))
        az = _num(sample.get("az"))
        gx = _num(sample.get("gx"))
        gy = _num(sample.get("gy"))
        gz = _num(sample.get("gz"))
        acc_mag.append(math.sqrt(ax * ax + ay * ay + az * az))
        gyro_mag.append(math.sqrt(gx * gx + gy * gy + gz * gz))
        gyro_axes["gx"].append(gx)
        gyro_axes["gy"].append(gy)
        gyro_axes["gz"].append(gz)

    dt = 1.0 / estimated_rate
    jerk = [0.0]
    for index in range(1, len(acc_mag)):
        jerk.append(abs(acc_mag[index] - acc_mag[index - 1]) / dt)

    dominant_freq = _dominant_frequency(gyro_axes, estimated_rate)
    return {
        "feature_status": "ok",
        "window_start_ms": _safe_int(sorted_samples[0].get("timestamp_ms")),
        "window_end_ms": _safe_int(sorted_samples[-1].get("timestamp_ms")),
        "acc_mean": _round(mean(acc_mag)),
        "acc_std": _round(pstdev(acc_mag)),
        "acc_max": _round(max(acc_mag)),
        "acc_rms": _round(math.sqrt(mean([value * value for value in acc_mag]))),
        "gyro_mean": _round(mean(gyro_mag)),
        "gyro_std": _round(pstdev(gyro_mag)),
        "gyro_max": _round(max(gyro_mag)),
        "gyro_p95": _round(_percentile(gyro_mag, 95)),
        "jerk_mean": _round(mean(jerk)),
        "jerk_max": _round(max(jerk)),
        "peak_count": _count_peaks(acc_mag, gyro_mag),
        "dominant_freq": None if dominant_freq is None else _round(dominant_freq),
    }


def slice_samples_into_windows(
    samples: list[dict],
    window_size_s: float,
    step_size_s: float,
    sample_rate_hz: float | None = None,
) -> list[list[dict]]:
    if not samples:
        return []
    sorted_samples = _sorted_samples(samples)
    _validate_samples(sorted_samples)
    rate = sample_rate_hz or estimate_sample_rate(sorted_samples)
    if rate <= 0:
        return []

    window_ms = int(round(float(window_size_s) * 1000))
    step_ms = int(round(float(step_size_s) * 1000))
    if window_ms <= 0 or step_ms <= 0:
        raise HTTPException(status_code=400, detail="window_size_s and step_size_s must be positive")

    min_samples = max(3, int(round(rate * float(window_size_s) * 0.6)))
    first_ms = _safe_int(sorted_samples[0].get("timestamp_ms"))
    last_ms = _safe_int(sorted_samples[-1].get("timestamp_ms"))
    interval_ms = 1000.0 / rate
    windows: list[list[dict]] = []
    start_ms = first_ms
    while start_ms + window_ms <= last_ms + interval_ms:
        end_ms = start_ms + window_ms
        window = [
            sample
            for sample in sorted_samples
            if start_ms <= _safe_int(sample.get("timestamp_ms")) < end_ms
        ]
        if len(window) >= min_samples:
            windows.append(window)
        start_ms += step_ms
    return windows


def estimate_sample_rate(samples: list[dict]) -> float:
    sorted_samples = _sorted_samples(samples)
    if len(sorted_samples) < 2:
        return 0.0
    deltas = []
    previous = _safe_int(sorted_samples[0].get("timestamp_ms"))
    for sample in sorted_samples[1:]:
        current = _safe_int(sample.get("timestamp_ms"))
        delta = current - previous
        if delta > 0:
            deltas.append(delta)
        previous = current
    if not deltas:
        return 0.0
    median_delta = _percentile(deltas, 50)
    return round(1000.0 / median_delta, 3) if median_delta > 0 else 0.0


def insert_imu_windows(imu_session_id: str, windows_features: list[dict]) -> int:
    return insert_imu_window_features(imu_session_id, windows_features)


def _validate_samples(samples: list[dict]) -> None:
    for index, sample in enumerate(samples):
        missing = [field for field in REQUIRED_SAMPLE_FIELDS if sample.get(field) is None]
        if missing:
            raise HTTPException(status_code=400, detail=f"IMU sample {index} missing fields: {missing}")
        for field in REQUIRED_SAMPLE_FIELDS:
            _num(sample.get(field), field_name=field, sample_index=index)


def _sorted_samples(samples: list[dict]) -> list[dict]:
    return sorted(samples, key=lambda sample: (_safe_int(sample.get("timestamp_ms")), _safe_int(sample.get("seq"))))


def _dominant_frequency(gyro_axes: dict[str, list[float]], sample_rate_hz: float) -> float | None:
    if np is None:
        return None
    axis_name = max(gyro_axes, key=lambda key: pstdev(gyro_axes[key]) if len(gyro_axes[key]) > 1 else 0.0)
    values = gyro_axes[axis_name]
    if len(values) < 4:
        return None
    series = np.array(values, dtype=float)
    series = series - np.mean(series)
    if not np.any(series):
        return None
    spectrum = np.abs(np.fft.rfft(series))
    freqs = np.fft.rfftfreq(len(series), d=1.0 / sample_rate_hz)
    if len(freqs) <= 1:
        return None
    spectrum[0] = 0
    peak_index = int(np.argmax(spectrum))
    peak_freq = float(freqs[peak_index])
    return peak_freq if peak_freq > 0 else None


def _count_peaks(acc_mag: list[float], gyro_mag: list[float]) -> int:
    return max(_local_peak_count(acc_mag), _local_peak_count(gyro_mag))


def _local_peak_count(values: list[float]) -> int:
    if len(values) < 3:
        return 0
    threshold = mean(values) + 1.5 * pstdev(values)
    count = 0
    for index in range(1, len(values) - 1):
        if values[index] > threshold and values[index] > values[index - 1] and values[index] >= values[index + 1]:
            count += 1
    return count


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * (percentile / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(sorted_values[int(rank)])
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return float(lower_value + (upper_value - lower_value) * (rank - lower))


def _num(value: Any, field_name: str = "", sample_index: int = -1) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        if field_name:
            raise HTTPException(status_code=400, detail=f"IMU sample {sample_index} field {field_name} is not numeric")
        return 0.0


def _positive_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _round(value: float) -> float:
    return round(float(value), 5)
