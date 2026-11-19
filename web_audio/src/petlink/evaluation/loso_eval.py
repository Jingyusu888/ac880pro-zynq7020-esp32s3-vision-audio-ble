r"""LOSO（leave-one-source-out）评估：覆盖全部来源的泛化估计（41 折规模，分钟级）。

用法：
  .venv/Scripts/python.exe -m petlink.evaluation.loso_eval \
      --feature-table analysis/feature_table_v3_8k_4s.csv [--out analysis/loso_report.json]

说明：
  - 每折按 source 整体留出（CatMeows 猫 B/F 样本因共享 catmeows_<catID> 自动同折）；
  - 评估只取留出源的 window_index==0 行（与 headline 评测口径一致）；
  - LOSO 内不做超参搜索（固定阈值口径的纯任务级 macro-F1），如实标注。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from petlink.training.train_hierarchical import (
    COARSE_MAP,
    NEGATIVE_CLASSES,
    POSITIVE_CLASSES,
    load_rows,
    make_pipeline,
    per_task_report,
    to_float_matrix,
)

TASKS = {
    "coarse": (None, ["negative_or_distress", "positive_or_request"]),
    "positive_fine": (POSITIVE_CLASSES, POSITIVE_CLASSES),
    "negative_fine": (NEGATIVE_CLASSES, NEGATIVE_CLASSES),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="LOSO 评估")
    parser.add_argument("--feature-table", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("analysis/loso_report.json"))
    parser.add_argument("--class-weight", default="balanced", choices=["balanced", "none"])
    args = parser.parse_args()

    rows, feature_columns = load_rows(args.feature_table)
    rows = [row for row in rows if row.get("read_status", "ok") == "ok" and row.get("window_index", "0") == "0"]
    x, y = to_float_matrix(rows, feature_columns)
    sources = np.array([row.get("source_id", "") for row in rows])
    unique_sources = sorted(set(sources))
    print(f"rows={len(rows)} sources={len(unique_sources)}")

    weight = None if args.class_weight == "none" else "balanced"
    report: dict[str, dict] = {}
    for task, (subset_classes, model_classes) in TASKS.items():
        fold_f1 = []
        per_class_recall = defaultdict(list)
        for held_source in unique_sources:
            held_mask = sources == held_source
            train_mask = ~held_mask
            if subset_classes is not None:
                train_mask &= np.isin(y, subset_classes)
            eval_mask = held_mask & (np.isin(y, subset_classes) if subset_classes is not None else np.ones(len(y), dtype=bool))
            if eval_mask.sum() == 0 or train_mask.sum() < 10:
                continue
            y_train = np.array([COARSE_MAP[label] if task == "coarse" else label for label in y[train_mask]])
            model = make_pipeline(weight)
            model.fit(x[train_mask], y_train)
            y_pred = model.predict(x[eval_mask])
            y_true_task = np.array([COARSE_MAP[label] if task == "coarse" else label for label in y[eval_mask]])
            per_report, macro_f1 = per_task_report([str(v) for v in y_true_task], [str(v) for v in y_pred], model_classes)
            fold_f1.append(macro_f1)
            for class_name, entry in per_report.items():
                per_class_recall[class_name].append(entry["recall"])
        if fold_f1:
            report[task] = {
                "folds": len(fold_f1),
                "macro_f1_mean": round(float(np.mean(fold_f1)), 4),
                "macro_f1_sd": round(float(np.std(fold_f1)), 4),
                "macro_f1_worst": round(float(np.min(fold_f1)), 4),
                "per_class_recall_mean": {c: round(float(np.mean(v)), 4) for c, v in per_class_recall.items()},
            }
            print(f"{task}: folds={report[task]['folds']} macro_f1={report[task]['macro_f1_mean']}±{report[task]['macro_f1_sd']} worst={report[task]['macro_f1_worst']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
