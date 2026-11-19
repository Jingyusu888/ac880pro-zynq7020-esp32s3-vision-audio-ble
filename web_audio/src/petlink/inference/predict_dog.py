r"""狗版推理：门控（dog/non_dog）→ 状态（active/alert/rest）决策链。

与猫版 predict_clip 的关键差异：
1. 特征 preset 必须显式 v3_8k_2s（2s 窗，64 帧）——狗片段 p50=0.96s。
2. 无层级，无置信拒识（数据已否决）：gate argmax → dog 则 state argmax。
3. 标签 3 类（active/alert/rest）+ not_dog，不是猫版四标签。

用法：
  .venv/Scripts/python.exe -m petlink.inference.predict_dog \
      --audio path.wav --gate-dir models/dog_gate_v1 --state-dir models/b0_dog_v1
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from petlink.features import FeatureConfig, extract_features_from_samples, load_audio_mono, preset_v3_8k_2s, to_window

DOG_STATE_LABELS = ["active", "alert", "rest"]
GATE_LABELS = ["dog", "non_dog"]


def _to_matrix(features: dict, columns: list[str]) -> np.ndarray:
    x = np.full((1, len(columns)), np.nan, dtype=np.float64)
    for j, col in enumerate(columns):
        v = features.get(col, float("nan"))
        try:
            x[0, j] = float(v)
        except (TypeError, ValueError):
            pass
    return np.where(np.isinf(x), np.nan, x)


def run_dog_prediction(
    audio_path: Path,
    gate_model: Any,
    state_model: Any,
    gate_columns: list[str],
    state_columns: list[str],
    config: FeatureConfig | None = None,
) -> dict[str, Any]:
    if not audio_path.exists():
        raise FileNotFoundError(f"Missing audio file: {audio_path}")
    config = config or preset_v3_8k_2s()

    y, sr = load_audio_mono(audio_path, config)
    y = to_window(y, config.window_seconds, sr)
    features = extract_features_from_samples(y, sr, config)

    # 门控
    x_gate = _to_matrix(features, gate_columns)
    gate_proba = gate_model.predict_proba(x_gate)[0]
    gate_classes = list(gate_model.classes_)
    gate_idx = int(np.argmax(gate_proba))
    gate_label = str(gate_classes[gate_idx])
    gate_conf = float(gate_proba[gate_idx])

    if gate_label == "non_dog":
        return {
            "final_prediction": "not_dog",
            "species": "not_dog",
            "confidence": gate_conf,
            "state": None,
            "state_probabilities": None,
            "gate": {"label": gate_label, "confidence": gate_conf, "probabilities": {str(c): float(p) for c, p in zip(gate_classes, gate_proba)}},
            "warning": "not_dog 表示未听出狗叫，不输出状态；不是「狗没叫=没问题」的检测。",
        }

    # 状态（dog 分支，argmax 无拒识）
    x_state = _to_matrix(features, state_columns)
    state_proba = state_model.predict_proba(x_state)[0]
    state_classes = list(state_model.classes_)
    state_idx = int(np.argmax(state_proba))
    state_label = str(state_classes[state_idx])
    state_conf = float(state_proba[state_idx])

    return {
        "final_prediction": state_label,
        "species": "dog",
        "confidence": state_conf,
        "state": state_label,
        "state_probabilities": {str(c): float(p) for c, p in zip(state_classes, state_proba)},
        "gate": {"label": gate_label, "confidence": gate_conf, "probabilities": {str(c): float(p) for c, p in zip(gate_classes, gate_proba)}},
        "warning": "",
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, required=True)
    ap.add_argument("--gate-dir", type=Path, required=True)
    ap.add_argument("--state-dir", type=Path, required=True)
    args = ap.parse_args()

    gate_model = joblib.load(args.gate_dir / "saved_models" / "gate_classifier.joblib")
    state_model = joblib.load(args.state_dir / "saved_models" / "four_class_classifier.joblib")
    gate_meta = json.loads((args.gate_dir / "gate_meta.json").read_text(encoding="utf-8"))
    state_columns = json.loads((args.state_dir / "feature_columns.json").read_text(encoding="utf-8"))

    result = run_dog_prediction(
        args.audio.resolve(), gate_model, state_model, gate_meta["feature_columns"], state_columns
    )
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
