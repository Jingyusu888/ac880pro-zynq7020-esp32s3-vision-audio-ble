"""层级推理：载入 bundle → 定窗 → 特征 → 三分类器 → 阈值门控。

与旧 predict_clip.py 的行为差异（有意为之，均记录于 docs/DECISIONS.md）：
1. 特征实现来自 petlink.features.extractor（单一来源），默认配置与 16k 时代逐位一致。
2. 非 WAV 容器 fallback 由 librosa 懒加载改为 ffmpeg 解码（venv 不再依赖 librosa）。
3. 阈值严格单源：recommended_class_specific_thresholds.json 缺失即抛错（不再静默回退默认）；
   label_maps.json 只做结构校验，其中内嵌的旧阈值（0.65 一代）一律忽略。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from petlink.features import V2_16K, FeatureConfig, extract_features_from_samples, load_audio_mono, to_window

MODEL_FILES = ("coarse_classifier.joblib", "positive_fine_classifier.joblib", "negative_fine_classifier.joblib")

DEFAULT_THRESHOLDS = {
    "coarse_confidence_threshold": 0.70,
    "coarse_margin_threshold": 0.15,
    "default_fine_confidence_threshold": 0.75,
    "default_fine_margin_threshold": 0.20,
    "request_seeking_confidence_threshold": 0.80,
    "request_seeking_margin_threshold": 0.20,
    "pain_distress_confidence_threshold": 0.75,
    "pain_distress_margin_threshold": 0.20,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict one cat-vocal audio clip with a hierarchical LR bundle.")
    parser.add_argument("--audio", type=Path, required=True, help="Input audio file path.")
    parser.add_argument("--model-dir", type=Path, required=True, help="Model bundle directory (7-piece layout).")
    parser.add_argument(
        "--allow-default-thresholds",
        action="store_true",
        help="允许在阈值 JSON 缺失时回退内置默认（仅调试用；生产禁止）。",
    )
    return parser.parse_args()


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_thresholds(path: Path, allow_default: bool = False) -> dict[str, float]:
    """阈值单源。JSON 缺失时默认抛错；显式 allow_default 才回退（M14 修复）。"""
    if not path.exists():
        if allow_default:
            return dict(DEFAULT_THRESHOLDS)
        raise FileNotFoundError(f"Threshold JSON missing (阈值必须单源， refusing silent fallback): {path}")
    loaded = read_json(path)
    if not isinstance(loaded, dict):
        raise ValueError(f"Threshold file must contain a JSON object: {path}")
    thresholds = dict(DEFAULT_THRESHOLDS)
    for key in DEFAULT_THRESHOLDS:
        if key in loaded:
            thresholds[key] = float(loaded[key])
    return thresholds


def validate_label_maps(path: Path) -> dict[str, Any]:
    """label_maps.json 只读校验（其内嵌旧阈值不参与决策）。"""
    label_maps = read_json(path)
    if not isinstance(label_maps, dict):
        raise ValueError(f"label_maps.json must contain a JSON object: {path}")
    return label_maps


def load_models(model_dir: Path) -> tuple[Any, Any, Any]:
    saved_dir = model_dir / "saved_models"
    paths = [saved_dir / name for name in MODEL_FILES]
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Missing saved model: {path}")
    return tuple(joblib.load(path) for path in paths)


def classifier_details(model: Any, x: pd.DataFrame) -> dict[str, Any]:
    probs = model.predict_proba(x)
    classes = list(model.classes_)
    order = np.argsort(-probs, axis=1)
    top_idx = int(order[0, 0])
    second_idx = int(order[0, 1]) if probs.shape[1] > 1 else top_idx
    confidence = float(probs[0, top_idx])
    second_confidence = float(probs[0, second_idx]) if probs.shape[1] > 1 else 0.0
    return {
        "prediction": str(classes[top_idx]),
        "confidence": confidence,
        "margin": confidence - second_confidence,
        "probabilities": {str(class_name): float(probs[0, index]) for index, class_name in enumerate(classes)},
    }


def fine_thresholds(label: str, thresholds: dict[str, float]) -> tuple[float, float]:
    if label == "request_seeking":
        return thresholds["request_seeking_confidence_threshold"], thresholds["request_seeking_margin_threshold"]
    if label == "pain_distress":
        return thresholds["pain_distress_confidence_threshold"], thresholds["pain_distress_margin_threshold"]
    return thresholds["default_fine_confidence_threshold"], thresholds["default_fine_margin_threshold"]


def run_prediction(
    audio_path: Path,
    model_dir: Path,
    config: FeatureConfig = V2_16K,
    window_seconds: float = 4.0,
    allow_default_thresholds: bool = False,
    models: tuple[Any, Any, Any] | None = None,
) -> dict[str, Any]:
    if not audio_path.exists():
        raise FileNotFoundError(f"Missing audio file: {audio_path}")

    feature_columns = read_json(model_dir / "feature_columns.json")
    if not isinstance(feature_columns, list) or not all(isinstance(column, str) for column in feature_columns):
        raise ValueError(f"feature_columns.json must contain a list of strings: {model_dir / 'feature_columns.json'}")

    validate_label_maps(model_dir / "label_maps.json")
    thresholds = load_thresholds(model_dir / "recommended_class_specific_thresholds.json", allow_default_thresholds)
    coarse_model, positive_model, negative_model = models if models is not None else load_models(model_dir)

    y, sr = load_audio_mono(audio_path, config)
    y = to_window(y, window_seconds, sr)
    features = extract_features_from_samples(y, sr, config)
    if "duration_sec" in feature_columns:
        features.setdefault("duration_sec", float(len(y) / sr))
    # 训练拟合于无列名的 numpy 矩阵，推理侧保持同构（避免 feature-name 警告与潜在顺序问题）
    x = np.full((1, len(feature_columns)), np.nan, dtype=np.float64)
    for index, column in enumerate(feature_columns):
        value = features.get(column, float("nan"))
        try:
            x[0, index] = float(value)
        except (TypeError, ValueError):
            pass
    x = np.where(np.isinf(x), np.nan, x)

    coarse = classifier_details(coarse_model, x)
    positive_fine = classifier_details(positive_model, x)
    negative_fine = classifier_details(negative_model, x)

    final_prediction = "unknown"
    fine_prediction: str | None = None
    confidence = float(coarse["confidence"])
    margin = float(coarse["margin"])
    trigger = False

    coarse_ok = confidence >= thresholds["coarse_confidence_threshold"] and margin >= thresholds["coarse_margin_threshold"]

    if coarse_ok:
        if coarse["prediction"] == "positive_or_request":
            fine_prediction = str(positive_fine["prediction"])
            confidence = float(positive_fine["confidence"])
            margin = float(positive_fine["margin"])
            confidence_threshold, margin_threshold = fine_thresholds(fine_prediction, thresholds)
            if confidence >= confidence_threshold and margin >= margin_threshold:
                final_prediction = fine_prediction
                trigger = True
            else:
                final_prediction = "positive_or_request_uncertain"
        elif coarse["prediction"] == "negative_or_distress":
            fine_prediction = str(negative_fine["prediction"])
            confidence = float(negative_fine["confidence"])
            margin = float(negative_fine["margin"])
            confidence_threshold, margin_threshold = fine_thresholds(fine_prediction, thresholds)
            if confidence >= confidence_threshold and margin >= margin_threshold:
                final_prediction = fine_prediction
                trigger = True
            else:
                final_prediction = "negative_or_distress_uncertain"

    if final_prediction == "unknown" or final_prediction.endswith("_uncertain"):
        trigger = False

    warning = ""
    if final_prediction == "pain_distress":
        warning = "仅为数据标签提示，不是医疗或健康诊断。"
    elif not trigger:
        warning = "unknown/uncertain 不触发（置信度拒识，不是猫叫/非猫检测）。"

    return {
        "final_prediction": final_prediction,
        "coarse_prediction": coarse["prediction"],
        "fine_prediction": fine_prediction,
        "confidence": confidence,
        "margin": margin,
        "trigger": trigger,
        "probabilities": {
            "coarse": coarse["probabilities"],
            "positive_fine": positive_fine["probabilities"],
            "negative_fine": negative_fine["probabilities"],
        },
        "warning": warning,
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    return value


def main() -> None:
    args = parse_args()
    result = run_prediction(
        args.audio.resolve(),
        args.model_dir.resolve(),
        allow_default_thresholds=args.allow_default_thresholds,
    )
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
