from __future__ import annotations


TRAINABLE_STANDARD_LABELS = {
    "affiliative_relaxed",
    "request_seeking",
    "threat_discomfort",
    "pain_distress",
}

EXCLUDED_STANDARD_LABELS = {
    "uncertain",
    "noncat_noise",
}

USER_LABEL_TO_STANDARD = {
    "亲近 / 撒娇 / 想互动": "affiliative_relaxed",
    "affiliative_social_v2": "affiliative_relaxed",
    "affiliative_relaxed": "affiliative_relaxed",
    "明确诉求 / 想要东西": "request_seeking",
    "clear_request_v2": "request_seeking",
    "request_seeking": "request_seeking",
    "抗拒 / 紧张 / 不舒服": "threat_discomfort",
    "resist_tense_uncomfortable_v2": "threat_discomfort",
    "threat_discomfort": "threat_discomfort",
    "强烈异常 / distress 倾向": "pain_distress",
    "strong_distress_tendency_v2": "pain_distress",
    "pain_distress": "pain_distress",
    "听不出来 / 不确定": "uncertain",
    "unclear_uncertain_v2": "uncertain",
    "uncertain": "uncertain",
    "unknown": "uncertain",
    "不是猫叫 / 噪声": "noncat_noise",
    "not_cat_noise_v2": "noncat_noise",
    "noncat_noise": "noncat_noise",
}

STANDARD_LABEL_DISPLAY = {
    "affiliative_relaxed": "亲近 / 撒娇 / 想互动",
    "request_seeking": "明确诉求 / 想要东西",
    "threat_discomfort": "抗拒 / 紧张 / 不舒服",
    "pain_distress": "强烈异常 / distress 倾向",
    "uncertain": "听不出来 / 不确定",
    "noncat_noise": "不是猫叫 / 噪声",
}


def normalize_user_label(user_label: str) -> str:
    normalized = (user_label or "").strip()
    return USER_LABEL_TO_STANDARD.get(normalized, "")


def is_trainable_label(standard_label: str) -> bool:
    return (standard_label or "").strip() in TRAINABLE_STANDARD_LABELS


def display_label_for_standard(standard_label: str) -> str:
    return STANDARD_LABEL_DISPLAY.get((standard_label or "").strip(), standard_label or "")
