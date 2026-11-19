r"""层级训练（coarse → positive_fine / negative_fine），与 hierarchical_debug_v2 逐参数对齐。

用法：
  .venv/Scripts/python.exe -m petlink.training.train_hierarchical \
      --feature-table analysis/feature_table_v3_8k_4s.csv \
      --out models/hierarchical_v3 --preset v3_8k [--class-weight balanced]

模型规格（与旧 train_hierarchical_debug_v2.py 一致）：
  SimpleImputer(median) → StandardScaler → LogisticRegression(class_weight, max_iter=5000, lbfgs, seed=42)
差异（有意）：train 行允许窗口扩展（window_index>0），val/test 评估只取 window_index==0；
  模型输入列由特征表导出（v3/tiny 不含 duration；v2_16k 含 duration 以复现旧口径）。
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from petlink.features.extractor import PRESETS
from petlink.training.bundle import verify_bundle, write_bundle

COARSE_MAP = {
    "affiliative_relaxed": "positive_or_request",
    "request_seeking": "positive_or_request",
    "threat_discomfort": "negative_or_distress",
    "pain_distress": "negative_or_distress",
}
META_COLUMNS = {
    "audio_path", "label", "source_id", "split", "sample_type", "dataset_id",
    "duration_sec", "window_index", "read_status", "read_error",
}
POSITIVE_CLASSES = ["affiliative_relaxed", "request_seeking"]
NEGATIVE_CLASSES = ["threat_discomfort", "pain_distress"]
COARSE_CLASSES = ["negative_or_distress", "positive_or_request"]

DEFAULT_THRESHOLDS_UNTUNED = {
    "coarse_confidence_threshold": 0.70,
    "coarse_margin_threshold": 0.15,
    "default_fine_confidence_threshold": 0.75,
    "default_fine_margin_threshold": 0.20,
    "request_seeking_confidence_threshold": 0.80,
    "request_seeking_margin_threshold": 0.20,
    "pain_distress_confidence_threshold": 0.75,
    "pain_distress_margin_threshold": 0.20,
    "tuned": False,
    "selection_split": "pending",
}


def wilson_ci(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return float("nan"), float("nan")
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return center - half, center + half


def load_rows(path: Path) -> tuple[list[dict], list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    feature_columns = [c for c in columns if c not in META_COLUMNS]
    return rows, feature_columns


def to_float_matrix(rows: list[dict], columns: list[str]) -> tuple[np.ndarray, np.ndarray]:
    matrix = np.full((len(rows), len(columns)), np.nan, dtype=np.float64)
    for i, row in enumerate(rows):
        for j, column in enumerate(columns):
            try:
                matrix[i, j] = float(row.get(column, ""))
            except (TypeError, ValueError):
                pass
    labels = np.array([row.get("label", "") for row in rows])
    return matrix, labels


def make_pipeline(class_weight: str | None) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(class_weight=class_weight, max_iter=5000, solver="lbfgs", random_state=42)),
        ]
    )


def per_task_report(y_true: list[str], y_pred: list[str], classes: list[str]) -> tuple[dict[str, dict], float]:
    precision, recall, f1, support = precision_recall_fscore_support(y_true, y_pred, labels=classes, zero_division=0)
    report = {
        class_name: {
            "precision": round(float(precision[index]), 4),
            "recall": round(float(recall[index]), 4),
            "f1": round(float(f1[index]), 4),
            "support": int(support[index]),
        }
        for index, class_name in enumerate(classes)
    }
    macro_f1 = round(sum(item["f1"] for item in report.values()) / max(len(classes), 1), 4)
    return report, macro_f1


def eval_task(model: Pipeline, x: np.ndarray, y_true: np.ndarray, classes: list[str], binary_mask: np.ndarray | None = None) -> dict:
    if binary_mask is not None:
        x, y_true = x[binary_mask], y_true[binary_mask]
    if len(y_true) == 0:
        return {"macro_f1": None, "per_class": {}, "note": "no rows"}
    y_pred = model.predict(x)
    report, macro_f1 = per_task_report([str(v) for v in y_true], [str(v) for v in y_pred], classes)
    return {"macro_f1": macro_f1, "per_class": report}


def main() -> int:
    parser = argparse.ArgumentParser(description="层级 LR 训练")
    parser.add_argument("--feature-table", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preset", default="v3_8k", help="决定模型列是否含 duration 与 bundle 元数据")
    parser.add_argument("--class-weight", default="balanced", choices=["balanced", "none"])
    parser.add_argument("--single-four-class", action="store_true", help="B3t 臂：单个 multinomial 四分类 LR（无层级）")
    args = parser.parse_args()

    rows, feature_columns = load_rows(args.feature_table)
    includes_duration = "duration_sec" in feature_columns
    model_columns = list(feature_columns)
    if args.preset != "v2_16k" and includes_duration:
        model_columns = [c for c in feature_columns if c != "duration_sec"]

    def select(split: str) -> list[dict]:
        subset = [row for row in rows if row.get("read_status") == "ok"]
        if split == "val":
            subset = [row for row in subset if row.get("split") in ("val", "valid")]
        else:
            subset = [row for row in subset if row.get("split") == split]
        if split != "train":
            subset = [row for row in subset if row.get("window_index", "0") == "0"]
        return subset

    train_rows, val_rows, test_rows = select("train"), select("val"), select("test")
    print(f"rows: train={len(train_rows)} val={len(val_rows)} test={len(test_rows)} | features={len(model_columns)}")
    if not train_rows or not val_rows:
        raise SystemExit("train/val 为空，无法训练")

    x_train, y_train = to_float_matrix(train_rows, model_columns)
    x_val, y_val = to_float_matrix(val_rows, model_columns)
    x_test, y_test = to_float_matrix(test_rows, model_columns)
    if not args.single_four_class:
        coarse_train = np.array([COARSE_MAP[label] for label in y_train])
        coarse_val = np.array([COARSE_MAP[label] for label in y_val])
        coarse_test = np.array([COARSE_MAP[label] for label in y_test])

    weight = None if args.class_weight == "none" else "balanced"
    models: dict[str, Pipeline] = {}

    if args.single_four_class:
        four_model = make_pipeline(weight)
        four_model.fit(x_train, y_train)
        models["four_class"] = four_model
        metrics: dict[str, dict] = {}
        all_classes = sorted(set(y_train) | set(y_val) | set(y_test))
        for split, x_eval, y_eval in (("val", x_val, y_val), ("test", x_test, y_test)):
            if len(y_eval) == 0:
                continue
            metrics[f"{split}_four_class"] = eval_task(four_model, x_eval, y_eval, all_classes)
            entry = metrics[f"{split}_four_class"]
            per_class = " ".join(f"{c}:{r['f1']}" for c, r in entry["per_class"].items())
            print(f"{split}_four_class: macro_f1={entry['macro_f1']} {per_class}")
        label_maps = {
            "four_class": all_classes,
            "coarse": COARSE_MAP,
            "single_four_class": True,
        }
        config = PRESETS[args.preset]
        thresholds = dict(DEFAULT_THRESHOLDS_UNTUNED)
        meta = {
            "bundle_version": args.out.name,
            "frontend_preset": config.name,
            "window_seconds": config.window_seconds,
            "class_weight": args.class_weight,
            "includes_duration": False,
            "training": {
                "feature_table": str(args.feature_table),
                "rows": {"train": len(train_rows), "val": len(val_rows), "test": len(test_rows)},
                "metrics": metrics,
            },
        }
        write_bundle(args.out, models, model_columns, label_maps, thresholds, meta)
        failures = verify_bundle(args.out)
        if failures:
            print("BUNDLE VERIFY FAIL:", failures)
            return 1
        print(f"bundle written (single-four-class): {args.out}")
        return 0

    coarse_model = make_pipeline(weight)
    coarse_model.fit(x_train, coarse_train)
    models["coarse"] = coarse_model

    positive_model = make_pipeline(weight)
    positive_model.fit(x_train[np.isin(y_train, POSITIVE_CLASSES)], y_train[np.isin(y_train, POSITIVE_CLASSES)])
    models["positive_fine"] = positive_model

    negative_model = make_pipeline(weight)
    negative_model.fit(x_train[np.isin(y_train, NEGATIVE_CLASSES)], y_train[np.isin(y_train, NEGATIVE_CLASSES)])
    models["negative_fine"] = negative_model

    metrics: dict[str, dict] = {}
    for split, x_eval, y_eval, coarse_eval in (("val", x_val, y_val, coarse_val), ("test", x_test, y_test, coarse_test)):
        if len(y_eval) == 0:
            continue
        metrics[f"{split}_coarse"] = eval_task(coarse_model, x_eval, coarse_eval, COARSE_CLASSES)
        metrics[f"{split}_positive_fine"] = eval_task(positive_model, x_eval, y_eval, POSITIVE_CLASSES, np.isin(y_eval, POSITIVE_CLASSES))
        metrics[f"{split}_negative_fine"] = eval_task(negative_model, x_eval, y_eval, NEGATIVE_CLASSES, np.isin(y_eval, NEGATIVE_CLASSES))
        for name in (f"{split}_coarse", f"{split}_positive_fine", f"{split}_negative_fine"):
            entry = metrics[name]
            if entry["macro_f1"] is not None:
                per_class = " ".join(f"{c}:{r['f1']}" for c, r in entry["per_class"].items())
                print(f"{name}: macro_f1={entry['macro_f1']} {per_class}")

    label_maps = {
        "four_class": ["affiliative_relaxed", "request_seeking", "threat_discomfort", "pain_distress"],
        "coarse": COARSE_MAP,
    }
    config = PRESETS[args.preset]
    thresholds = {
        "coarse_confidence_threshold": 0.70,
        "coarse_margin_threshold": 0.15,
        "default_fine_confidence_threshold": 0.75,
        "default_fine_margin_threshold": 0.20,
        "request_seeking_confidence_threshold": 0.80,
        "request_seeking_margin_threshold": 0.20,
        "pain_distress_confidence_threshold": 0.75,
        "pain_distress_margin_threshold": 0.20,
        "tuned": False,
        "selection_split": "pending",  # tune_thresholds 在 val 上调优后改写为 "val"
    }
    meta = {
        "bundle_version": args.out.name,
        "frontend_preset": config.name,
        "window_seconds": config.window_seconds,
        "class_weight": args.class_weight,
        "includes_duration": includes_duration and args.preset == "v2_16k",
        "training": {
            "feature_table": str(args.feature_table),
            "rows": {"train": len(train_rows), "val": len(val_rows), "test": len(test_rows)},
            "metrics": metrics,
        },
    }
    write_bundle(args.out, models, model_columns, label_maps, thresholds, meta)
    failures = verify_bundle(args.out)
    if failures:
        print("BUNDLE VERIFY FAIL:", failures)
        return 1
    print(f"bundle written: {args.out}（7 件套校验通过；阈值待 tune）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
