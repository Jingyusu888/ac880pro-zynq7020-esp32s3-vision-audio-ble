r"""S5-C：狗版参数导出（门控二分类 + 状态三分类 + 物种门控二分类）。

与 export_lr_parameters_v3.py 的差异：支持多分类（状态模型 coef 3×238）。
产物：edge/export/dog_v1/cat_model_params.h（单文件，含三个分类器参数）。

模型结构：
- species_gate: 二分类 cat/dog（1×238 coef + 1 bias）
- dog_gate:     二分类 dog/non_dog（1×238 coef + 1 bias）
- dog_state:    三分类 active/alert/rest（3×238 coef + 3 bias）

用法：
  .venv/Scripts/python.exe tools/export_dog_parameters.py \
      --species-dir models/species_gate_v1 \
      --gate-dir models/dog_gate_v1 \
      --state-dir models/b0_dog_v1 \
      --out edge/export/dog_v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import sklearn


def c_array(name: str, values: np.ndarray) -> str:
    flat = np.asarray(values, dtype=np.float32).ravel()
    if not np.isfinite(flat).all():
        raise ValueError(f"Non-finite float32 parameter: {name}")
    lines = [f"static const float {name}[{len(flat)}] = {{"]
    for start in range(0, len(flat), 6):
        lines.append("    " + ", ".join(f"{float(x):.9e}f" for x in flat[start : start + 6]) + ",")
    return "\n".join(lines + ["};", ""])


def export_pipeline(header: list[str], pipe, prefix: str, n_features: int) -> dict:
    """导出一个 pipeline 的参数数组 + 类名。支持二分类（1×n）和多分类（C×n）。"""
    steps = list(pipe.named_steps)
    if steps != ["imputer", "scaler", "clf"] and steps != ["imputer", "scaler", "model"]:
        raise ValueError(f"Unexpected pipeline steps: {steps}")
    imputer = pipe.named_steps["imputer"]
    scaler = pipe.named_steps["scaler"]
    model = pipe.named_steps.get("clf") or pipe.named_steps.get("model")
    if imputer.strategy != "median" or imputer.add_indicator:
        raise ValueError(f"Unsupported imputer: {prefix}")
    if not scaler.with_mean or not scaler.with_std:
        raise ValueError(f"Unexpected scaler mode: {prefix}")
    coef = np.asarray(model.coef_)
    bias = np.asarray(model.intercept_)
    n_logits = coef.shape[0]
    n_classes = len(model.classes_)
    if coef.shape != (n_logits, n_features) or bias.shape != (n_logits,):
        raise ValueError(f"Unexpected parameter shape: {prefix} coef={coef.shape} bias={bias.shape}")
    if n_logits == 1 and n_classes != 2:
        raise ValueError(f"Binary logit but {n_classes} classes: {prefix}")
    if n_logits > 1 and n_logits != n_classes:
        raise ValueError(f"Multinomial logits {n_logits} != classes {n_classes}: {prefix}")

    arrays = {
        "median": np.asarray(imputer.statistics_),
        "mean": np.asarray(scaler.mean_),
        "scale": np.asarray(scaler.scale_),
        "weight": coef,          # (n_classes, n_features)
        "bias": bias,            # (n_classes,)
    }
    for key, arr in arrays.items():
        if not np.isfinite(arr).all():
            raise ValueError(f"Non-finite parameter: {prefix}/{key}")
        header.append(c_array(f"{prefix}_{key}", arr))
    if not (arrays["scale"] > 0).all():
        raise ValueError(f"Invalid scaler scale: {prefix}")

    classes = [str(v) for v in model.classes_]
    quoted = ", ".join(json.dumps(v) for v in classes)
    header.append(f"static const char *const {prefix}_classes[{n_classes}] = {{{quoted}}};\n")
    header.append(f"#define {prefix.upper()}_CLASS_COUNT {n_classes}\n")
    header.append(f"#define {prefix.upper()}_LOGIT_COUNT {n_logits}\n")
    return {"classes": classes, "n_classes": n_classes, "n_logits": n_logits}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--species-dir", type=Path, required=True)
    ap.add_argument("--gate-dir", type=Path, required=True)
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if sklearn.__version__ != "1.8.0":
        raise SystemExit(f"Expected scikit-learn 1.8.0, found {sklearn.__version__}")

    state_columns = json.loads((args.state_dir / "feature_columns.json").read_text(encoding="utf-8"))
    n_features = len(state_columns)
    if n_features != 238:
        raise ValueError(f"Expected 238 features, got {n_features}")

    header = ["#pragma once", "", f"#define DOG_FEATURE_COUNT {n_features}", ""]

    species_pipe = joblib.load(args.species_dir / "saved_models" / "gate_classifier.joblib")
    gate_pipe = joblib.load(args.gate_dir / "saved_models" / "gate_classifier.joblib")
    state_pipe = joblib.load(args.state_dir / "saved_models" / "four_class_classifier.joblib")

    exported = {
        "species_gate": export_pipeline(header, species_pipe, "species", n_features),
        "dog_gate": export_pipeline(header, gate_pipe, "gate", n_features),
        "dog_state": export_pipeline(header, state_pipe, "state", n_features),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / "dog_model_params.h"
    out_file.write_text("\n".join(header) + "\n", encoding="utf-8")

    hashes = {}
    for name, pipe, path in [
        ("species_gate", species_pipe, args.species_dir / "saved_models" / "gate_classifier.joblib"),
        ("dog_gate", gate_pipe, args.gate_dir / "saved_models" / "gate_classifier.joblib"),
        ("dog_state", state_pipe, args.state_dir / "saved_models" / "four_class_classifier.joblib"),
    ]:
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {
        "source_models": {"species_gate": args.species_dir.name, "dog_gate": args.gate_dir.name, "dog_state": args.state_dir.name},
        "sklearn_version": sklearn.__version__,
        "feature_columns": state_columns,
        "models": exported,
        "source_sha256": hashes,
        "validation_status": "structural_checks_only; audio_and_board_parity_not_tested",
    }
    (args.out / "export_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"exported to {out_file}")
    for k, v in exported.items():
        print(f"  {k}: classes={v['classes']} (logits={v['n_logits']}, classes={v['n_classes']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
