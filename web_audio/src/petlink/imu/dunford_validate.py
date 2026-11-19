r"""Dunford 2024 项圈 IMU 数据 → IMU_PROTOCOL_V1 转换 + 仅加速度行为验证。

用法：.venv/Scripts/python.exe -m petlink.imu.dunford_validate

产出：
  data/external/dryad_dunford_q2bvq83sx/converted/imu_protocol_v1_dunford.csv
      （协议字段：schema_version/device_id/pet_id/timestamp_ms/seq/ax,ay,az/gx,gy,gz(null)/
        sensor_position=collar_future/source=public_dataset_real/behaviour_label）
  analysis/imu_dunford_validation.json
      猫级留出验证（仅加速度特征 → 7 行为混淆表），H1"首次真实数据"机械验证。

边界（AGENTS.md 红线/计划裁决）：仅验证加速度通道的机械特征-行为可分性；
  tail_sway/tail_flick 规则本次不可验证（无陀螺仪）；不宣称情绪识别能力。
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "external" / "dryad_dunford_q2bvq83sx" / "raw" / "Dunford_et_al._Cats_calibrated_data.csv"
CONVERTED = ROOT / "data" / "external" / "dryad_dunford_q2bvq83sx" / "converted" / "imu_protocol_v1_dunford.csv"
REPORT = ROOT / "analysis" / "imu_dunford_validation.json"

SAMPLE_RATE = 40
WINDOW_SEC = 2.0
STEP_SEC = 1.0
WINDOW = int(SAMPLE_RATE * WINDOW_SEC)
STEP = int(SAMPLE_RATE * STEP_SEC)


def window_features(acc: np.ndarray) -> dict[str, float]:
    """C4 风格仅加速度特征（无陀螺仪通道）：量值 + 三轴。"""
    magnitude = np.linalg.norm(acc, axis=1)
    jerk = float(np.mean(np.abs(np.diff(magnitude, axis=0)))) if len(magnitude) > 1 else 0.0
    # dominant freq：对去均值量值信号做 rFFT 取主峰频率
    centered = magnitude - magnitude.mean()
    spectrum = np.abs(np.fft.rfft(centered * np.hanning(len(centered))))
    freqs = np.fft.rfftfreq(len(centered), d=1.0 / SAMPLE_RATE)
    dominant = float(freqs[int(np.argmax(spectrum[1:]) + 1)]) if len(spectrum) > 1 else 0.0
    features = {
        "acc_mag_mean": float(magnitude.mean()),
        "acc_mag_std": float(magnitude.std()),
        "acc_mag_max": float(magnitude.max()),
        "acc_mag_rms": float(np.sqrt(np.mean(magnitude**2))),
        "acc_jerk_mean": jerk,
        "acc_dominant_freq_hz": dominant,
    }
    for axis_index, axis_name in enumerate("xyz"):
        channel = acc[:, axis_index]
        features[f"acc_{axis_name}_mean"] = float(channel.mean())
        features[f"acc_{axis_name}_std"] = float(channel.std())
    return features


def main() -> int:
    rows = list(csv.DictReader(open(RAW, encoding="utf-8")))
    print(f"raw rows: {len(rows)}")

    # 1) 协议 V1 转换（流式写，130k 行）
    CONVERTED.parent.mkdir(parents=True, exist_ok=True)
    protocol_fields = [
        "schema_version", "device_id", "pet_id", "timestamp_ms", "seq",
        "ax", "ay", "az", "gx", "gy", "gz", "sensor_position", "source", "behaviour_label",
    ]
    with open(CONVERTED, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=protocol_fields)
        writer.writeheader()
        for seq, row in enumerate(rows):
            writer.writerow(
                {
                    "schema_version": "1.1-patch1",
                    "device_id": "dryad_dunford_dailydiary",
                    "pet_id": f"dunford_{row['ID']}",
                    "timestamp_ms": "",  # 原数据仅每日内时间，无绝对时间戳——协议允许空（记录在 patch 文档）
                    "seq": seq,
                    "ax": row["AccX"],
                    "ay": row["AccY"],
                    "az": row["AccZ"],
                    "gx": "", "gy": "", "gz": "",  # 无陀螺仪：显式 null（协议补丁允许的真实数据例外）
                    "sensor_position": "collar_future",
                    "source": "public_dataset_real",  # 协议补丁新增枚举（docs/IMU_PROTOCOL_V1_PATCH.md）
                    "behaviour_label": row["Behaviour"],
                }
            )
    print(f"converted -> {CONVERTED}")

    # 2) 猫级留出验证（每猫轮流留出，7 行为混淆）
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_cat[row["ID"]].append(row)
    cats = sorted(by_cat)
    labels = sorted({row["Behaviour"] for row in rows})

    confusion = defaultdict(lambda: defaultdict(int))
    fold_metrics = []
    for held in cats:
        train_windows, eval_windows = [], []
        for cat, cat_rows in by_cat.items():
            acc = np.array([[float(r["AccX"]), float(r["AccY"]), float(r["AccZ"])] for r in cat_rows])
            behaviours = [r["Behaviour"] for r in cat_rows]
            windows = []
            for start in range(0, len(acc) - WINDOW + 1, STEP):
                segment = acc[start : start + WINDOW]
                window_labels = behaviours[start : start + WINDOW]
                majority = Counter(window_labels).most_common(1)[0][0]
                windows.append((window_features(segment), majority))
            if cat == held:
                eval_windows.extend(windows)
            else:
                train_windows.extend(windows)
        if not eval_windows:
            continue
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        feature_names = list(train_windows[0][0].keys())
        x_train = np.array([[w[f] for f in feature_names] for w, _ in train_windows])
        y_train = np.array([lab for _, lab in train_windows])
        x_eval = np.array([[w[f] for f in feature_names] for w, _ in eval_windows])
        y_eval = np.array([lab for _, lab in eval_windows])
        model = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(class_weight="balanced", max_iter=2000)),
            ]
        )
        model.fit(x_train, y_train)
        y_pred = model.predict(x_eval)
        accuracy = float((y_pred == y_eval).mean())
        fold_metrics.append({"held_cat": held, "eval_windows": int(len(y_eval)), "accuracy": round(accuracy, 4)})
        for truth, pred in zip(y_eval, y_pred):
            confusion[truth][pred] += 1
        print(f"LOCO fold {held}: acc={accuracy:.4f} (eval windows={len(y_eval)})")

    summary = {
        "scope": "accel-only mechanical feature validation on real collar IMU (Dunford 2024, 40Hz, 9 cats)",
        "windows": {"seconds": WINDOW_SEC, "step_seconds": STEP_SEC, "samples_per_window": WINDOW},
        "labels": labels,
        "loco_folds": fold_metrics,
        "mean_accuracy": round(float(np.mean([f["accuracy"] for f in fold_metrics])), 4),
        "confusion_true_to_pred": {t: dict(p) for t, p in confusion.items()},
        "caveats": [
            "无陀螺仪：tail_sway/tail_flick 规则本次不可验证",
            "仅验证行为级（非情绪）机械可分性；不得宣称情绪识别",
            "source=public_dataset_real 为协议补丁枚举（docs/IMU_PROTOCOL_V1_PATCH.md）",
            "LOSO（LOCO）内不做超参搜索；40Hz 原生未重采样",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"mean LOCO accuracy: {summary['mean_accuracy']}")
    print(f"report -> {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
