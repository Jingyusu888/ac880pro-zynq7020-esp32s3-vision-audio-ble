r"""猫叫识别模型服务（web 后端 → petlink.inference 直连）。

迁移改造记录（相对 pet_link 版）：
- 删除 PROJECT_ROOT="D:\\pet_link" 硬编码与 importlib 动态加载 predict_clip（原每请求 exec_module）；
  改为直接 import petlink.inference.predict_clip，模型经 lru_cache 预载。
- 模型目录改为项目内 bundle：models/b0_mixed8k4s（S5 选型，配置可覆盖）。
- 阈值严格单源由 petlink.inference 保证（缺 JSON 拒绝服务）。
"""
from __future__ import annotations

import json
import math
import re
import shutil
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from ..config import UPLOADS_DIR

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = PROJECT_ROOT / "models" / "b0_v5"
MODEL_NAME = "b0_v5"
MODEL_TYPE = "hierarchical_logistic_regression_v3_8k"
DEBUG_MODEL_NOTICE = "b0_v5 为雏形级模型（source 隔离评测，request 域内限定），非正式泛化模型。"
GENERAL_SAFETY_MESSAGE = "识别结果仅供行为观察参考，不能替代兽医判断。"
MAX_AUDIO_BYTES = 50 * 1024 * 1024
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".webm"}

MODEL_LABEL_DISPLAY = {
    "affiliative_relaxed": "亲近 / 撒娇 / 想互动",
    "request_seeking": "明确诉求 / 想要东西",
    "threat_discomfort": "抗拒 / 紧张 / 不舒服",
    "pain_distress": "强烈异常 / distress 倾向",
    "unknown": "听不出来 / 无法判断",
    "uncertain": "不确定 / 不触发",
    "positive_or_request_uncertain": "不确定 / 不触发",
    "negative_or_distress_uncertain": "不确定 / 不触发",
}

PAIN_DISTRESS_WARNING = "distress 倾向，仅供行为观察参考，不能替代兽医判断。"
UNCERTAIN_WARNING = "当前无法可靠判断，不触发语音反馈。"


@lru_cache(maxsize=1)
def _load_bundle_cached(model_dir_str: str):
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from petlink.inference.predict_clip import load_models  # 延迟导入，避免 venv 未装 petlink 时拖垮服务启动

    return load_models(Path(model_dir_str))


@lru_cache(maxsize=1)
def _frontend_config_cached(model_dir_str: str):
    """从 bundle manifest 读 frontend_preset → FeatureConfig（P0 修复：不再默认 V2_16K）。"""
    from petlink.features import preset_from_name

    manifest_path = Path(model_dir_str) / "bundle_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing bundle_manifest.json: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    preset_name = manifest.get("frontend_preset")
    if not preset_name:
        raise ValueError(f"bundle_manifest.json missing frontend_preset: {manifest_path}")
    return preset_from_name(str(preset_name))


def model_files() -> list[Path]:
    return [
        MODEL_DIR / "saved_models" / "coarse_classifier.joblib",
        MODEL_DIR / "saved_models" / "positive_fine_classifier.joblib",
        MODEL_DIR / "saved_models" / "negative_fine_classifier.joblib",
        MODEL_DIR / "feature_columns.json",
        MODEL_DIR / "label_maps.json",
        MODEL_DIR / "recommended_class_specific_thresholds.json",
    ]


def model_available() -> bool:
    return all(path.exists() for path in model_files())


def get_model_status() -> dict[str, Any]:
    missing = [str(path) for path in model_files() if not path.exists()]
    return {
        "mode": "real_model",
        "model_name": MODEL_NAME,
        "model_type": MODEL_TYPE,
        "model_version": MODEL_TYPE,
        "model_path": str(MODEL_DIR),
        "model_dir": str(MODEL_DIR),
        "available": not missing,
        "adapter_status": "petlink_inference_direct",
        "is_mock": False,
        "missing_files": missing,
        "debug_notice": DEBUG_MODEL_NOTICE,
        "safety_message": GENERAL_SAFETY_MESSAGE,
    }


def is_uncertain_label(label: str) -> bool:
    normalized = (label or "").strip().lower()
    return normalized in {"unknown", "uncertain"} or normalized.endswith("_uncertain")


def display_label_for(label: str) -> str:
    if is_uncertain_label(label):
        return MODEL_LABEL_DISPLAY.get(label, "不确定 / 不触发")
    return MODEL_LABEL_DISPLAY.get(label or "", label or "")


def safe_warning(label: str, raw_warning: str = "") -> str:
    if label == "pain_distress":
        return PAIN_DISTRESS_WARNING
    if is_uncertain_label(label):
        return UNCERTAIN_WARNING
    return raw_warning or ""


def predict_cat_voice(audio_path: str) -> dict[str, Any]:
    if not model_available():
        return {
            "ok": False,
            "mode": "real_model_unavailable",
            "model_name": MODEL_NAME,
            "model_type": MODEL_TYPE,
            "model_version": MODEL_TYPE,
            "model_dir": str(MODEL_DIR),
            "error": "model_files_missing",
            "status": get_model_status(),
            "debug_notice": DEBUG_MODEL_NOTICE,
            "safety_message": GENERAL_SAFETY_MESSAGE,
        }
    try:
        from petlink.inference.predict_clip import json_safe, run_prediction

        cached = _load_bundle_cached(str(MODEL_DIR))
        config = _frontend_config_cached(str(MODEL_DIR))
        raw_result = run_prediction(Path(audio_path), MODEL_DIR, config=config, models=cached)
        raw_result = json_safe(raw_result)
        prediction_label = str(raw_result.get("final_prediction") or "unknown")
        trigger = bool(raw_result.get("trigger", False))
        if is_uncertain_label(prediction_label):
            trigger = False
        warning = safe_warning(prediction_label, str(raw_result.get("warning") or ""))
        return {
            "ok": True,
            "mode": "real_model",
            "model_name": MODEL_NAME,
            "model_type": MODEL_TYPE,
            "model_version": MODEL_TYPE,
            "model_dir": str(MODEL_DIR),
            "adapter_status": "petlink_inference_direct",
            "is_mock": False,
            "prediction_label": prediction_label,
            "predicted_label": prediction_label,
            "label": prediction_label,
            "display_label": display_label_for(prediction_label),
            "confidence": _safe_float(raw_result.get("confidence")),
            "margin": _safe_float(raw_result.get("margin")),
            "trigger": trigger,
            "warning": warning,
            "debug_notice": DEBUG_MODEL_NOTICE,
            "safety_message": warning or GENERAL_SAFETY_MESSAGE,
            "raw_result": raw_result,
        }
    except Exception as error:  # noqa: BLE001
        return {
            "ok": False,
            "mode": "real_model_unavailable",
            "model_name": MODEL_NAME,
            "model_type": MODEL_TYPE,
            "model_version": MODEL_TYPE,
            "model_dir": str(MODEL_DIR),
            "error": str(error),
            "debug_notice": DEBUG_MODEL_NOTICE,
            "safety_message": GENERAL_SAFETY_MESSAGE,
        }


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def safe_audio_filename(original_filename: str) -> str:
    source = Path(original_filename or "audio.wav")
    suffix = source.suffix.lower() or ".wav"
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported audio file type")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source.stem).strip("._-") or "audio"
    timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f")
    return f"{timestamp}_{uuid4().hex[:8]}_{stem[:80]}{suffix}"


def save_uploaded_audio(audio_file: UploadFile) -> Path:
    target_dir = UPLOADS_DIR / "audio"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_audio_filename(audio_file.filename or "audio.wav")
    total = 0
    with target_path.open("wb") as output:
        while True:
            chunk = audio_file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_AUDIO_BYTES:
                output.close()
                target_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="Audio file is too large")
            output.write(chunk)
    if total == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Audio file is empty")
    try:
        audio_file.file.seek(0)
    except Exception:
        pass
    return target_path


def copy_audio_for_test(source_path: Path) -> Path:
    target_dir = UPLOADS_DIR / "audio"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_audio_filename(source_path.name)
    shutil.copy2(source_path, target_path)
    return target_path
