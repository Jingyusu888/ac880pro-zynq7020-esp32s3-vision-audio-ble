from __future__ import annotations


IMU_SOURCE_ALLOWED_CURRENT = ["simulated", "engineering_assumption"]
IMU_SOURCE_FUTURE_RESERVED = ["user_uploaded_future", "tail_imu_auto_future", "body_imu_auto_future"]
SENSOR_POSITION_ALLOWED_CURRENT = ["simulated_tail", "simulated_body"]
SENSOR_POSITION_FUTURE_RESERVED = ["tail_base_future", "collar_future", "body_back_future"]

MOTION_LABELS = ["still", "body_active", "body_intense", "tail_sway", "tail_flick_or_agitation", "unknown"]
EMOTION_CONTEXT_LABELS = [
    "relaxed_possible",
    "seeking_possible",
    "alert_discomfort_possible",
    "distress_possible",
    "playful_possible",
    "unknown",
]
QUALITY_LABELS = [
    "accepted",
    "uncertain",
    "reject_wrong_context",
    "reject_noise",
    "reject_simulated_only",
    "rejected",
    "reject_bad_simulation",
    "reject_low_quality_data",
    "reject_not_cat_related",
]
ANNOTATION_SOURCES = ["user_manual", "developer_review", "demo_review", "future_auto_prompt"]
FUSION_LABELS = [
    "relaxed_or_affiliative",
    "active_request",
    "alert_or_discomfort",
    "distress_attention_needed",
    "motion_alert_uncertain_audio",
    "active_play_or_excitement",
    "audio_only_uncertain_motion",
    "unknown_multimodal",
]

SESSION_STATUS_VALUES = ["created", "simulated_pending", "ready", "failed", "archived"]
TRAINING_QUALITY_STATUS_VALUES = ["accepted", "uncertain", "rejected"]
TRAINING_REVIEW_STATUS_VALUES = ["pending_review", "pending", "reviewed", "exported", "rejected"]
TRAINING_SOURCES = ["simulated", "engineering_assumption", "human_annotated_simulated", "future_tail_imu_auto"]
FUSION_METHOD_PLACEHOLDER = "fusion_method_placeholder"
FUSION_METHOD_RULE_V1 = "rule_based_audio_imu_v1"
CONFIDENCE_TYPE_RULE_SCORE = "rule_score_not_probability"
