r"""Headline 评估：bundle 阈值下 test 一次性评测（红队协议 A）。

用法：.venv/Scripts/python.exe -m petlink.evaluation.evaluate_headline \
        --bundle models/b0_mixed8k4s --feature-table analysis/feature_table_v3_8k_4s.csv \
        --out analysis/headline_v3.json

产出：选择性精度/覆盖率、每类 P/R/F1 + Wilson CI、误触发计数、
      分域行（main vs catmeows）、补零子集行（duration<窗长）。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from petlink.training.train_hierarchical import META_COLUMNS, load_rows, to_float_matrix
from petlink.training.tune_thresholds import fine_threshold_for, load_bundle

LABELS = ["affiliative_relaxed", "request_seeking", "threat_discomfort", "pain_distress"]


def wilson(successes: int, total: int, z: float = 1.96) -> list[float]:
    if total == 0:
        return [float("nan"), float("nan")]
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [round(center - half, 4), round(center + half, 4)]


def run_headline(bundle: Path, rows: list[dict], feature_columns: list[str]) -> dict:
    import joblib

    coarse_model, positive_model, negative_model = (joblib.load(bundle / "saved_models" / f"{n}_classifier.joblib") for n in ("coarse", "positive_fine", "negative_fine"))
    thresholds = json.loads((bundle / "recommended_class_specific_thresholds.json").read_text(encoding="utf-8"))
    x, y_true = to_float_matrix(rows, feature_columns)

    coarse_probs = coarse_model.predict_proba(x)
    positive_probs = positive_model.predict_proba(x)
    negative_probs = negative_model.predict_proba(x)

    records = []
    for i, label in enumerate(y_true):
        ci = int(np.argmax(coarse_probs[i]))
        coarse_pred = str(coarse_model.classes_[ci])
        coarse_conf = float(coarse_probs[i][ci])
        order = np.argsort(-coarse_probs[i])
        coarse_margin = float(coarse_probs[i][order[0]] - (coarse_probs[i][order[1]] if len(order) > 1 else 0.0))
        final, fine_pred, conf, margin, triggered = "unknown", None, coarse_conf, coarse_margin, False
        if coarse_conf >= thresholds["coarse_confidence_threshold"] and coarse_margin >= thresholds["coarse_margin_threshold"]:
            if coarse_pred == "positive_or_request":
                fi = int(np.argmax(positive_probs[i]))
                fine_pred = str(positive_model.classes_[fi])
                conf = float(positive_probs[i][fi])
            else:
                fi = int(np.argmax(negative_probs[i]))
                fine_pred = str(negative_model.classes_[fi])
                conf = float(negative_probs[i][fi])
            second = float(np.sort((positive_probs[i] if coarse_pred == "positive_or_request" else negative_probs[i]))[-2])
            margin = conf - second
            ct, mt = fine_threshold_for(fine_pred, thresholds)
            if conf >= ct and margin >= mt:
                final, triggered = fine_pred, True
            else:
                final = f"{coarse_pred}_uncertain"
        records.append({"label": label, "final": final, "triggered": triggered, "fine_pred": fine_pred, "confidence": conf, "margin": margin})

    stats: dict[str, dict] = {}
    for scope_name, scope_rows in (
        ("all", records),
        ("main_domain", [r for r, row in zip(records, rows) if not row.get("source_id", "").startswith("catmeows")]),
        ("catmeows_domain", [r for r, row in zip(records, rows) if row.get("source_id", "").startswith("catmeows")]),
    ):
        n = len(scope_rows)
        covered = sum(1 for r in scope_rows if r["triggered"])
        correct = sum(1 for r in scope_rows if r["triggered"] and r["final"] == r["label"])
        false_triggers = Counter(r["final"] for r in scope_rows if r["triggered"] and r["final"] != r["label"])
        per_class = {}
        for label in LABELS:
            support = sum(1 for r in scope_rows if r["label"] == label)
            tp = sum(1 for r in scope_rows if r["triggered"] and r["final"] == label and r["label"] == label)
            fp = sum(1 for r in scope_rows if r["triggered"] and r["final"] == label and r["label"] != label)
            fn = support - tp
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / support if support else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            per_class[label] = {
                "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
                "support": support, "recall_ci95": wilson(tp, support),
            }
        stats[scope_name] = {
            "rows": n,
            "coverage": round(covered / max(n, 1), 4),
            "selective_accuracy": round(correct / max(covered, 1), 4),
            "false_trigger_counts": dict(false_triggers),
            "per_class": per_class,
        }
    return {"thresholds_used": {k: v for k, v in thresholds.items() if k.endswith("threshold")}, "splits": stats}


def main() -> int:
    parser = argparse.ArgumentParser(description="headline 评估（test 一次性）")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--feature-table", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows, feature_columns = load_rows(args.feature_table)
    test_rows = [row for row in rows if row.get("split") == "test" and row.get("read_status", "ok") == "ok" and row.get("window_index", "0") == "0"]
    print(f"test rows={len(test_rows)}")
    result = run_headline(args.bundle, test_rows, feature_columns)

    # 补零子集行（duration < 窗长 → 推理时尾部补零）
    window_seconds = 4.0
    padded = [row for row in test_rows if row.get("duration_sec") and float(row["duration_sec"]) < window_seconds]
    if padded:
        result["splits"]["padded_subset"] = run_headline(args.bundle, padded, feature_columns)["splits"]["all"]
        result["splits"]["padded_subset"]["note"] = f"duration<4s 的补零子集（n={len(padded)}）"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for scope, entry in result["splits"].items():
        per_class = " ".join(f"{c}:{v['f1']}" for c, v in entry["per_class"].items())
        print(f"{scope}: cov={entry['coverage']} sel_acc={entry['selective_accuracy']} false={entry['false_trigger_counts']} | {per_class}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
