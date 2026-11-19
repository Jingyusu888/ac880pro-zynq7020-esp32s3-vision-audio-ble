r"""域探针（泄漏检测门禁 D）：用特征预测 dataset_id，分组 AUC ≤0.90 为过门。

用法：
  .venv/Scripts/python.exe -m petlink.evaluation.probe_domain \
      --feature-table analysis/feature_table_v3_8k_4s.csv [--label-column dataset_id]

若 dataset_id 列缺失则按 source_id 前缀推断（catmeows_/kaggle_/其余→main）。
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from petlink.training.train_hierarchical import META_COLUMNS, load_rows, to_float_matrix


def derive_domain(row: dict) -> str:
    source = row.get("source_id", "")
    if source.startswith("catmeows"):
        return "catmeows"
    if source.startswith("kaggle"):
        return "kaggle"
    return "main"


def probe_auc(rows: list[dict], feature_columns: list[str], groups: list[str], folds: int = 3, target_domain: str = "catmeows_zenodo_4008297") -> float:
    """可复用二分类域探针（消融研究用）：返回 target-vs-rest 分组 AUC 均值。"""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    x, _ = to_float_matrix(rows, feature_columns)
    y = np.array(["target" if (row.get("dataset_id") or derive_domain(row)) == target_domain else "other" for row in rows])
    group_array = np.array(groups)
    aucs = []
    for train_index, test_index in GroupKFold(n_splits=folds).split(x, y, group_array):
        if len(np.unique(y[test_index])) < 2:
            continue
        model = Pipeline(
            [("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=2000))]
        )
        model.fit(x[train_index], y[train_index])
        prob = model.predict_proba(x[test_index])[:, list(model.classes_).index("target")]
        aucs.append(roc_auc_score(y[test_index], prob))
    return float(np.mean(aucs)) if aucs else float("nan")


def main() -> int:
    parser = argparse.ArgumentParser(description="域探针：特征能否预测数据来源（二分类：目标域 vs 其余）")
    parser.add_argument("--feature-table", type=Path, required=True)
    parser.add_argument("--target-domain", default="catmeows_zenodo_4008297", help="二分类探针的目标域")
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--gate", type=float, default=0.90)
    args = parser.parse_args()

    rows, feature_columns = load_rows(args.feature_table)
    rows = [row for row in rows if row.get("read_status", "ok") == "ok"]
    for row in rows:
        domain = row.get("dataset_id") or derive_domain(row)
        row["probe_domain"] = "target" if domain == args.target_domain else "other"
    x, _ = to_float_matrix(rows, feature_columns)
    y = np.array([row["probe_domain"] for row in rows])
    groups = np.array([row.get("source_id", "") for row in rows])
    print(f"rows={len(rows)} domains={dict(zip(*np.unique(y, return_counts=True)))} sources={len(set(groups))}")

    aucs = []
    splitter = GroupKFold(n_splits=args.folds)
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    for fold, (train_index, test_index) in enumerate(splitter.split(x, y, groups), start=1):
        if len(np.unique(y[test_index])) < 2:
            print(f"fold{fold}: skipped（测试域只有一类）")
            continue
        model = Pipeline(
            [("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=2000))]
        )
        model.fit(x[train_index], y[train_index])
        prob = model.predict_proba(x[test_index])[:, list(model.classes_).index("target")]
        auc = roc_auc_score(y[test_index], prob)
        aucs.append(auc)
        print(f"fold{fold}: target-vs-rest AUC={auc:.4f}")

    mean_auc = float(np.nanmean(aucs)) if aucs else float("nan")
    verdict = "PASS" if mean_auc <= args.gate else "FAIL"
    print(f"\n域探针分组 macro-AUC = {mean_auc:.4f}（门禁 ≤{args.gate}）→ {verdict}")
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
