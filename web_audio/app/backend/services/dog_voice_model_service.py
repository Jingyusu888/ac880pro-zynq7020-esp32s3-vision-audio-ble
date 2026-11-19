r"""狗叫识别模型服务（web 后端 → petlink.inference.predict_dog 直连）。

关键纪律（猫版 preset bug 教训）：
- 特征 preset **显式 v3_8k_2s**（2s 窗 / 64 帧），绝不依赖默认 V2_16K。
- 决策链：门控（dog/non_dog）→ 状态（active/alert/rest），argmax 无拒识。
- 标签 schema=dog_v1_state3，basis=behavior_state_inferred，免责后缀。
"""
from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
from fastapi import HTTPException, UploadFile

from ..config import UPLOADS_DIR

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GATE_DIR = PROJECT_ROOT / "models" / "dog_gate_v1"
STATE_DIR = PROJECT_ROOT / "models" / "b0_dog_v1"
MODEL_NAME = "b0_dog_v1"
MODEL_TYPE = "dog_state3_lr_v3_8k_2s"
DEBUG_MODEL_NOTICE = "b0_dog_v1 为雏形级模型（行为状态推断，非情绪识别），非正式泛化模型。"
GENERAL_SAFETY_MESSAGE = "由叫声推断的行为状态，仅供行为观察参考，不能替代兽医判断。"
MAX_AUDIO_BYTES = 50 * 1024 * 1024

STATE_LABEL_DISPLAY = {
    "active": "活跃 / 想互动",
    "alert": "警觉 / 留意",
    "rest": "放松 / 休息",
    "not_dog": "未听出狗叫",
}

SAFETY_SUFFIX = "（由叫声推断的行为状态，非生理测量，不能替代兽医判断）"


@lru_cache(maxsize=1)
def _load_models_cached() -> tuple[Any, Any, list[str], list[str]]:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    gate_model = joblib.load(GATE_DIR / "saved_models" / "gate_classifier.joblib")
    state_model = joblib.load(STATE_DIR / "saved_models" / "four_class_classifier.joblib")
    gate_meta = json.loads((GATE_DIR / "gate_meta.json").read_text(encoding="utf-8"))
    state_columns = json.loads((STATE_DIR / "feature_columns.json").read_text(encoding="utf-8"))
    return gate_model, state_model, gate_meta["feature_columns"], state_columns


def model_available() -> bool:
    return (
        (GATE_DIR / "saved_models" / "gate_classifier.joblib").exists()
        and (STATE_DIR / "saved_models" / "four_class_classifier.joblib").exists()
    )


def predict_dog_voice(audio_path: str) -> dict[str, Any]:
    if not model_available():
        return {"ok": False, "mode": "real_model_unavailable", "error": "model_files_missing"}
    try:
        from petlink.inference.predict_dog import json_safe, run_dog_prediction

        gate_model, state_model, gate_columns, state_columns = _load_models_cached()
        raw_result = run_dog_prediction(Path(audio_path), gate_model, state_model, gate_columns, state_columns)
        raw_result = json_safe(raw_result)
        prediction_label = str(raw_result.get("final_prediction") or "not_dog")
        return {
            "ok": True,
            "mode": "real_model",
            "model_name": MODEL_NAME,
            "model_type": MODEL_TYPE,
            "label_schema": "dog_v1_state3",
            "basis": "behavior_state_inferred",
            "prediction_label": prediction_label,
            "label": prediction_label,
            "display_label": STATE_LABEL_DISPLAY.get(prediction_label, prediction_label),
            "confidence": _safe_float(raw_result.get("confidence")),
            "warning": SAFETY_SUFFIX,
            "debug_notice": DEBUG_MODEL_NOTICE,
            "safety_message": SAFETY_SUFFIX,
            "raw_result": raw_result,
        }
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "mode": "real_model_unavailable", "error": str(error), "debug_notice": DEBUG_MODEL_NOTICE}


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0
