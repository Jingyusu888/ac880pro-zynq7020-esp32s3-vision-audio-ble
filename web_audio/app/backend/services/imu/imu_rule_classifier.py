from __future__ import annotations

from collections import Counter
from typing import Any


"""
Rule-based IMU motion classifier for the no-hardware IMU stage.

These thresholds are based on C3 engineering-assumption simulated data. They
are not real hardware accuracy claims, and the output is a motion state only,
not an emotion label or medical/health diagnosis.
"""


THRESHOLDS = {
    "still_acc_std_max": 0.06,
    "still_gyro_mean_max": 5.0,
    "still_jerk_mean_max": 1.5,
    "flick_gyro_p95_min": 80.0,
    "flick_gyro_max_min": 120.0,
    "flick_jerk_max_min": 5.0,
    "flick_peak_count_min": 2,
    "tail_sway_freq_min": 0.5,
    "tail_sway_freq_max": 3.0,
    "tail_sway_gyro_std_min": 5.0,
    "tail_sway_gyro_max_max": 120.0,
    "tail_sway_peak_count_max": 8,
    "body_intense_acc_std_min": 0.12,
    "body_intense_gyro_std_min": 35.0,
    "body_intense_jerk_max_min": 8.0,
    "body_intense_peak_count_min": 6,
    "body_active_acc_std_min": 0.035,
    "body_active_gyro_mean_min": 5.0,
}

UNKNOWN_RESULT = {
    "rule_motion_label": "unknown",
    "rule_motion_confidence": 0.35,
    "rule_notes": "features are missing or too short; rule classifier cannot assign a stable motion state",
}


def classify_window_rule(features: dict) -> dict:
    if not features or features.get("feature_status") != "ok":
        return dict(UNKNOWN_RESULT)

    acc_std = _num(features.get("acc_std"))
    gyro_mean = _num(features.get("gyro_mean"))
    gyro_std = _num(features.get("gyro_std"))
    gyro_max = _num(features.get("gyro_max"))
    gyro_p95 = _num(features.get("gyro_p95"))
    jerk_mean = _num(features.get("jerk_mean"))
    jerk_max = _num(features.get("jerk_max"))
    peak_count = int(_num(features.get("peak_count")))
    dominant_freq = _optional_num(features.get("dominant_freq"))

    flick_signal = (
        gyro_p95 > THRESHOLDS["flick_gyro_p95_min"]
        or gyro_max > THRESHOLDS["flick_gyro_max_min"]
    ) and (
        jerk_max > THRESHOLDS["flick_jerk_max_min"]
        or peak_count >= THRESHOLDS["flick_peak_count_min"]
    )
    if flick_signal:
        confidence = 0.68
        if gyro_max > 180 or gyro_p95 > 110:
            confidence += 0.08
        if jerk_max > 10:
            confidence += 0.05
        if peak_count >= 4:
            confidence += 0.04
        return {
            "rule_motion_label": "tail_flick_or_agitation",
            "rule_motion_confidence": _clamp(confidence, 0.65, 0.85),
            "rule_notes": "high gyro spike and jerk pattern match tail_flick_or_agitation engineering assumption",
        }

    if (
        acc_std < THRESHOLDS["still_acc_std_max"]
        and gyro_mean < THRESHOLDS["still_gyro_mean_max"]
        and jerk_mean < THRESHOLDS["still_jerk_mean_max"]
    ):
        confidence = 0.72
        confidence += max(0.0, (THRESHOLDS["still_acc_std_max"] - acc_std) / 0.12)
        confidence += max(0.0, (THRESHOLDS["still_gyro_mean_max"] - gyro_mean) / 25.0)
        return {
            "rule_motion_label": "still",
            "rule_motion_confidence": _clamp(confidence, 0.70, 0.90),
            "rule_notes": "low acceleration variance, gyro mean, and jerk match still engineering assumption",
        }

    tail_sway_signal = (
        dominant_freq is not None
        and THRESHOLDS["tail_sway_freq_min"] <= dominant_freq <= THRESHOLDS["tail_sway_freq_max"]
        and gyro_std > THRESHOLDS["tail_sway_gyro_std_min"]
        and gyro_max < THRESHOLDS["tail_sway_gyro_max_max"]
        and peak_count <= THRESHOLDS["tail_sway_peak_count_max"]
    )
    if tail_sway_signal:
        confidence = 0.62
        confidence += min(0.10, gyro_std / 250.0)
        if 0.8 <= dominant_freq <= 1.8:
            confidence += 0.06
        return {
            "rule_motion_label": "tail_sway",
            "rule_motion_confidence": _clamp(confidence, 0.60, 0.80),
            "rule_notes": "dominant frequency and moderate gyro periodic pattern match tail_sway assumption",
        }

    body_intense_signal = (
        acc_std > THRESHOLDS["body_intense_acc_std_min"]
        or gyro_std > THRESHOLDS["body_intense_gyro_std_min"]
        or jerk_max > THRESHOLDS["body_intense_jerk_max_min"]
        or (
            peak_count >= THRESHOLDS["body_intense_peak_count_min"]
            and gyro_mean > 30.0
            and jerk_max > 6.0
        )
    )
    if body_intense_signal:
        confidence = 0.62
        if acc_std > 0.25:
            confidence += 0.06
        if gyro_std > 50:
            confidence += 0.05
        if peak_count >= 5:
            confidence += 0.04
        return {
            "rule_motion_label": "body_intense",
            "rule_motion_confidence": _clamp(confidence, 0.60, 0.80),
            "rule_notes": "high variation, jerk, or peak count match body_intense engineering assumption",
        }

    if acc_std >= THRESHOLDS["body_active_acc_std_min"] and gyro_mean >= THRESHOLDS["body_active_gyro_mean_min"]:
        confidence = 0.57 + min(0.14, (gyro_mean - THRESHOLDS["body_active_gyro_mean_min"]) / 160.0)
        return {
            "rule_motion_label": "body_active",
            "rule_motion_confidence": _clamp(confidence, 0.55, 0.75),
            "rule_notes": "medium acceleration and gyro activity match body_active engineering assumption",
        }

    return dict(UNKNOWN_RESULT)


def summarize_session_motion(window_results: list[dict]) -> dict:
    if not window_results:
        return {
            "dominant_motion_label": "unknown",
            "motion_confidence": 0.0,
            "window_count": 0,
            "label_counts": {},
        }

    labels = [str(row.get("rule_motion_label") or "unknown") for row in window_results]
    counts = Counter(labels)
    average_confidence_by_label: dict[str, float] = {}
    for label in counts:
        confidences = [
            _num(row.get("rule_motion_confidence"))
            for row in window_results
            if str(row.get("rule_motion_label") or "unknown") == label
        ]
        average_confidence_by_label[label] = sum(confidences) / len(confidences) if confidences else 0.0

    dominant_label = max(
        counts,
        key=lambda label: (counts[label], average_confidence_by_label.get(label, 0.0), label != "unknown"),
    )
    return {
        "dominant_motion_label": dominant_label,
        "motion_confidence": round(average_confidence_by_label.get(dominant_label, 0.0), 3),
        "window_count": len(window_results),
        "label_counts": dict(counts),
    }


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return round(max(lower, min(upper, value)), 3)
