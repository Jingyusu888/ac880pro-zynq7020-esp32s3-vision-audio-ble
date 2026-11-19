r"""类别专属阈值调参（只在 val 上选，test 一次性评估——红队 P1-5/P1-6 修复）。

用法：
  .venv/Scripts/python.exe -m petlink.training.tune_thresholds \
      --bundle models/hierarchical_v3 --feature-table analysis/feature_table_v3_8k_4s.csv

规则：
  1. coarse 网格选优：最大化 val selective_accuracy（coverage≥0.5 为约束），平手取误触发更少者。
  2. 细分类只调 --tune-labels（默认 affiliative_relaxed,request_seeking）；
     threat/pain 保持默认阈值并在 JSON 标注 not_tuned（val 支撑不足，调了就是噪声拟合）。
  3. request_seeking 支撑量门槛：val support < min-request-support 时不调，沿用旧值并标注。
  4. 产出键名与旧 recommended_class_specific_thresholds.json 完全兼容，并改写 bundle manifest 哈希。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

from petlink.features.extractor import PRESETS
from petlink.training.bundle import sha256_of, verify_bundle, write_json
from petlink.training.train_hierarchical import META_COLUMNS, load_rows, to_float_matrix

DEFAULTS = {
    "coarse_confidence_threshold": 0.70,
    "coarse_margin_threshold": 0.15,
    "default_fine_confidence_threshold": 0.75,
    "default_fine_margin_threshold": 0.20,
    "request_seeking_confidence_threshold": 0.80,
    "request_seeking_margin_threshold": 0.20,
    "pain_distress_confidence_threshold": 0.75,
    "pain_distress_margin_threshold": 0.20,
}


def load_bundle(bundle: Path):
    import joblib

    saved = bundle / "saved_models"
    return tuple(joblib.load(saved / f"{name}_classifier.joblib") for name in ("coarse", "positive_fine", "negative_fine"))


def fine_threshold_for(label: str, thresholds: dict) -> tuple[float, float]:
    if label == "request_seeking":
        return thresholds["request_seeking_confidence_threshold"], thresholds["request_seeking_margin_threshold"]
    if label == "pain_distress":
        return thresholds["pain_distress_confidence_threshold"], thresholds["pain_distress_margin_threshold"]
    return thresholds["default_fine_confidence_threshold"], thresholds["default_fine_margin_threshold"]


def hierarchical_outcome(rows, coarse_model, positive_model, negative_model, x, y_true, thresholds):
    """返回 (selective_correct, selective_total, covered, false_trigger Counter, support Counter)。"""
    from collections import Counter

    coarse_probs = coarse_model.predict_proba(x)
    positive_probs = positive_model.predict_proba(x)
    negative_probs = negative_model.predict_proba(x)

    def top(probs_row):
        index = int(np.argmax(probs_row))
        second = int(np.argsort(-probs_row)[1]) if len(probs_row) > 1 else index
        return index, float(probs_row[index]), float(probs_row[index] - probs_row[second])

    stats = {"selective_correct": 0, "selective_total": 0, "covered": 0, "false_trigger": Counter(), "support": Counter()}
    for i, label in enumerate(y_true):
        stats["support"][label] += 1
        coarse_index, coarse_conf, coarse_margin = top(coarse_probs[i])
        coarse_pred = coarse_model.classes_[coarse_index]
        if not (coarse_conf >= thresholds["coarse_confidence_threshold"] and coarse_margin >= thresholds["coarse_margin_threshold"]):
            continue
        if coarse_pred == "positive_or_request":
            fine_index, fine_conf, fine_margin = top(positive_probs[i])
            fine_pred = positive_model.classes_[fine_index]
        else:
            fine_index, fine_conf, fine_margin = top(negative_probs[i])
            fine_pred = negative_model.classes_[fine_index]
        confidence_threshold, margin_threshold = fine_threshold_for(fine_pred, thresholds)
        if fine_conf >= confidence_threshold and fine_margin >= margin_threshold:
            stats["covered"] += 1
            stats["selective_total"] += 1
            if fine_pred == label:
                stats["selective_correct"] += 1
            else:
                stats["false_trigger"][fine_pred] += 1
        # 否则拒识，不计入
    return stats


def grid(steps):
    values = [round(0.50 + 0.05 * i, 2) for i in range(10)]
    return [(c, m) for c in values for m in values]


def main() -> int:
    global BUNDLE_DIR
    parser = argparse.ArgumentParser(description="类别专属阈值调参（val only）")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--feature-table", type=Path, required=True)
    parser.add_argument("--tune-labels", default="affiliative_relaxed,request_seeking")
    parser.add_argument("--min-request-support", type=int, default=20)
    parser.add_argument("--min-coverage", type=float, default=0.5)
    args = parser.parse_args()
    BUNDLE_DIR = args.bundle

    import joblib

    coarse_model, positive_model, negative_model = load_bundle(args.bundle)
    feature_columns = json.loads((args.bundle / "feature_columns.json").read_text(encoding="utf-8"))
    rows_all, _ = load_rows(args.feature_table)
    val_rows = [row for row in rows_all if row.get("split") == "val" and row.get("read_status") == "ok" and row.get("window_index", "0") == "0"]
    x_val = np.full((len(val_rows), len(feature_columns)), np.nan)
    for i, row in enumerate(val_rows):
        for j, column in enumerate(feature_columns):
            try:
                x_val[i, j] = float(row.get(column, ""))
            except (TypeError, ValueError):
                pass
    y_val = np.array([row.get("label", "") for row in val_rows])
    print(f"val rows={len(val_rows)} support={dict(zip(*np.unique(y_val, return_counts=True)))}")

    thresholds = dict(DEFAULTS)
    notes: dict[str, object] = {"tuned": True, "selection_split": "val", "selection_rule": "max selective_accuracy @ coverage>=0.5; tie-break fewer false triggers; request gated by support floor"}

    # 1) coarse 网格（fine 用当前默认）。候选集 = 网格 + 现行默认；
    #    选择规则（v2 纪律 + 红队 P1-6 + 支配性要求）：
    #    request 误触发=0 优先 → selective_acc → 总误触发少 → coverage 高；
    #    默认阈值参与竞选——调优结果必须支配默认才被采纳（防小 val 过拟合）。
    candidates = [(c, m) for c, m in grid(0.05)]
    default_coarse = (DEFAULTS["coarse_confidence_threshold"], DEFAULTS["coarse_margin_threshold"])
    if default_coarse not in candidates:
        candidates.append(default_coarse)
    best = None
    request_support = int((y_val == "request_seeking").sum())
    for conf, margin in candidates:
        candidate = dict(thresholds, coarse_confidence_threshold=conf, coarse_margin_threshold=margin)
        stats = hierarchical_outcome(val_rows, coarse_model, positive_model, negative_model, x_val, y_val, candidate)
        coverage = stats["covered"] / max(len(y_val), 1)
        selective_acc = stats["selective_correct"] / max(stats["selective_total"], 1)
        total_false = sum(stats["false_trigger"].values())
        request_false = stats["false_trigger"].get("request_seeking", 0)
        request_gate_ok = request_false == 0 if request_support >= args.min_request_support else True
        key = (0 if request_gate_ok else 1, selective_acc, -total_false, coverage)
        if best is None or key > best[0]:
            best = (key, conf, margin, selective_acc, coverage, total_false, request_false, (conf, margin) == default_coarse)
    if best is None:
        print("FAIL: coarse 网格无有效候选")
        return 1
    _, conf, margin, selective_acc, coverage, total_false, request_false, is_default = best
    request_support_ok = request_support >= args.min_request_support
    # 终极纪律：request 支撑足够但无候选实现 request 误触发=0 → 调优失败，整体保留默认并记录。
    if request_support_ok and request_false > 0 and not is_default:
        thresholds["tuned"] = False
        thresholds["selection_split"] = "val"
        thresholds["tuning_verdict"] = (
            f"NO_DOMINATING_CANDIDATE: val 上无任何阈值组合在 coverage 约束内实现 request_false=0"
            f"（最佳 request_false={request_false}）；保留默认阈值。val={len(y_val)} 行、跨域，调参结论性不足。"
        )
        write_json(args.bundle / "recommended_class_specific_thresholds.json", thresholds)
        manifest_path = args.bundle / "bundle_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        relative = "recommended_class_specific_thresholds.json"
        manifest["pieces"][relative] = {"sha256": sha256_of(args.bundle / relative), "bytes": (args.bundle / relative).stat().st_size}
        manifest["threshold_tuning"] = thresholds.get("tuning_verdict", "")
        write_json(manifest_path, manifest)
        print(f"tuning VERDICT: 保留默认阈值（{thresholds['tuning_verdict']}）")
        return 0
    thresholds["coarse_confidence_threshold"] = conf
    thresholds["coarse_margin_threshold"] = margin
    origin = "kept_default（无候选支配默认）" if is_default else "tuned"
    thresholds["coarse_selection"] = origin
    print(f"coarse {origin}: {conf}/{margin} selective_acc={selective_acc:.4f} coverage={coverage:.4f} false={total_false} request_false={request_false}")

    # 2) 细分类逐标签调优（贪心：固定 coarse，逐标签扫 fine 阈值）
    tuned_labels = {}
    for label in [s for s in args.tune_labels.split(",") if s]:
        support = int((y_val == label).sum())
        if label == "request_seeking" and support < args.min_request_support:
            notes[f"{label}_not_tuned_reason"] = f"val support={support} < {args.min_request_support}（红队 P1-6 支撑量门槛）"
            print(f"{label}: 不调（support={support} < {args.min_request_support}），沿用默认")
            continue
        label_best = None
        for conf, margin in grid(0.05):
            candidate = dict(thresholds)
            if label == "request_seeking":
                candidate["request_seeking_confidence_threshold"] = conf
                candidate["request_seeking_margin_threshold"] = margin
            else:
                candidate["default_fine_confidence_threshold"] = conf
                candidate["default_fine_margin_threshold"] = margin
            stats = hierarchical_outcome(val_rows, coarse_model, positive_model, negative_model, x_val, y_val, candidate)
            coverage = stats["covered"] / max(len(y_val), 1)
            if coverage < args.min_coverage:
                continue
            selective_acc = stats["selective_correct"] / max(stats["selective_total"], 1)
            false_of_label = stats["false_trigger"].get(label, 0)
            # 该标签若达到支撑量：误触发=0 优先，其次 selective_acc，其次 coverage
            gate_ok = false_of_label == 0 if support >= args.min_request_support else True
            key = (0 if gate_ok else 1, selective_acc, -false_of_label, coverage)
            if label_best is None or key > label_best[0]:
                label_best = (key, conf, margin, selective_acc, false_of_label)
        if label_best:
            _, conf, margin, selective_acc, false_count = label_best
            if label == "request_seeking":
                thresholds["request_seeking_confidence_threshold"] = conf
                thresholds["request_seeking_margin_threshold"] = margin
            else:
                thresholds["default_fine_confidence_threshold"] = conf
                thresholds["default_fine_margin_threshold"] = margin
            tuned_labels[label] = {"confidence": conf, "margin": margin, "val_selective_acc": selective_acc, "val_false_trigger": false_count}
            print(f"{label} tuned: {conf}/{margin} (val false={false_count})")

    thresholds.update(notes)
    thresholds["tuned_labels"] = tuned_labels
    thresholds["not_tuned_labels"] = ["threat_discomfort", "pain_distress"]
    write_json(args.bundle / "recommended_class_specific_thresholds.json", thresholds)

    # 刷新 bundle manifest 中该 piece 的哈希
    manifest_path = args.bundle / "bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative = "recommended_class_specific_thresholds.json"
    manifest["pieces"][relative] = {"sha256": sha256_of(args.bundle / relative), "bytes": (args.bundle / relative).stat().st_size}
    manifest["threshold_tuning"] = {k: v for k, v in notes.items()}
    write_json(manifest_path, manifest)
    failures = verify_bundle(args.bundle)
    print("bundle verify:", "OK" if not failures else failures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
