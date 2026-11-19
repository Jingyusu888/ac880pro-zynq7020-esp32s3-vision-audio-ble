"""Export the existing PetLink binary sklearn pipelines without changing them.

Run in the model's original scikit-learn 1.8.0 environment. This exports
parameters; it does not port the audio frontend or validate ESP32 firmware.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import sklearn


MODEL_NAMES = ("coarse", "positive_fine", "negative_fine")
THRESHOLD_KEYS = (
    "coarse_confidence_threshold", "coarse_margin_threshold",
    "default_fine_confidence_threshold", "default_fine_margin_threshold",
    "request_seeking_confidence_threshold", "request_seeking_margin_threshold",
    "pain_distress_confidence_threshold", "pain_distress_margin_threshold",
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def c_array(name: str, values: np.ndarray) -> str:
    flat = np.asarray(values, dtype=np.float32).ravel()
    if not np.isfinite(flat).all():
        raise ValueError(f"Non-finite float32 parameter: {name}")
    lines = [f"static const float {name}[{len(flat)}] = {{"]
    for start in range(0, len(flat), 6):
        lines.append("    " + ", ".join(f"{float(x):.9e}f" for x in flat[start:start + 6]) + ",")
    return "\n".join(lines + ["};", ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path,
                        help="A new output directory; existing directories are rejected.")
    args = parser.parse_args()
    if sklearn.__version__ != "1.8.0":
        raise SystemExit(
            f"Expected scikit-learn 1.8.0, found {sklearn.__version__}. "
            "Use a separate environment matching the saved model."
        )
    source, output = args.model_dir.resolve(), args.out.resolve()
    if output == source or source in output.parents:
        raise SystemExit("Output must be outside the source model directory.")
    if output.exists():
        raise SystemExit("Output already exists. Choose a new export directory.")
    columns = read_json(source / "feature_columns.json")
    if len(columns) == 0 or len(set(columns)) != len(columns):
        raise ValueError("feature_columns.json must be non-empty and unique.")
    n_features = len(columns)
    thresholds_all = read_json(source / "recommended_class_specific_thresholds.json")
    thresholds = {key: float(thresholds_all[key]) for key in THRESHOLD_KEYS}
    if not all(np.isfinite(value) and 0 <= value <= 1 for value in thresholds.values()):
        raise ValueError("Invalid confidence/margin thresholds.")

    header = ["#pragma once", "", f"#define CAT_FEATURE_COUNT {n_features}", ""]
    exported = {}
    hashes = {}
    parameter_bytes = 0
    for name in MODEL_NAMES:
        path = source / "saved_models" / f"{name}_classifier.joblib"
        pipe = joblib.load(path)
        steps = list(pipe.named_steps)
        if steps != ["imputer", "scaler", "model"] and steps != ["imputer", "scaler", "clf"]:
            raise ValueError(f"Unexpected pipeline steps in {name}: {steps}")
        imputer = pipe.named_steps["imputer"]
        scaler = pipe.named_steps["scaler"]
        model = pipe.named_steps["model"] if "model" in pipe.named_steps else pipe.named_steps["clf"]
        feature_names = getattr(pipe, "feature_names_in_", None)
        if feature_names is not None and list(feature_names) != columns:
            raise ValueError(f"Feature order mismatch: {name}")
        if model.coef_.shape != (1, n_features) or model.intercept_.shape != (1,):
            raise ValueError(f"Expected single-logit binary logistic regression: {name}")
        if len(model.classes_) != 2:
            raise ValueError(f"Expected two classes: {name}")
        if imputer.strategy != "median" or imputer.add_indicator:
            raise ValueError(f"Unsupported imputer: {name}")
        if not scaler.with_mean or not scaler.with_std:
            raise ValueError(f"Unexpected scaler mode: {name}")
        arrays = {
            "median": np.asarray(imputer.statistics_),
            "mean": np.asarray(scaler.mean_),
            "scale": np.asarray(scaler.scale_),
            "weight": np.asarray(model.coef_[0]),
            "bias": np.asarray(model.intercept_),
        }
        for key, array in arrays.items():
            if array.shape != ((1,) if key == "bias" else (n_features,)):
                raise ValueError(f"Unexpected parameter shape: {name}/{key}")
            if not np.isfinite(array).all():
                raise ValueError(f"Non-finite parameter: {name}/{key}")
            header.append(c_array(f"{name}_{key}", array))
            parameter_bytes += array.size * 4
        if not (arrays["scale"] > 0).all():
            raise ValueError(f"Invalid scaler scale: {name}")
        classes = [str(value) for value in model.classes_]
        quoted = ", ".join(json.dumps(value) for value in classes)
        header.append(f"static const char *const {name}_classes[2] = {{{quoted}}};\n")
        exported[name] = {
            "classes": classes,
            "parameters_float64": {key: value.tolist() for key, value in arrays.items()},
        }
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

    for key, value in thresholds.items():
        header.append(f"static const float {key} = {value:.9e}f;")
    output.mkdir(parents=True, exist_ok=False)
    (output / "cat_model_params.h").write_text("\n".join(header) + "\n", encoding="utf-8")
    manifest = {
        "source_model": "hierarchical_debug_v2", "sklearn_version": sklearn.__version__,
        "feature_columns": columns, "thresholds": thresholds, "models": exported,
        "source_sha256": hashes, "model_parameter_float32_bytes": parameter_bytes,
        "validation_status": "structural_checks_only; audio_and_board_parity_not_tested",
    }
    (output / "export_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(f"Exported {parameter_bytes} float32 parameter bytes to {output}")
    print("Next: verify PC reference probabilities, C classifier parity, and audio frontend parity.")


if __name__ == "__main__":
    main()
