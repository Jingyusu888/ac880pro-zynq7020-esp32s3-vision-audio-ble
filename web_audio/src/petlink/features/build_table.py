r"""特征表构建 CLI（B 系列实验共用）。

用法：
  .venv/Scripts/python.exe -m petlink.features.build_table \
      --manifest metadata/split_v3.csv --out analysis/feature_table_v3_8k_4s.csv \
      --preset v3_8k [--train-expand-k 3] [--limit N]

行为：
  - v2_16k   ：全长度提取（与旧 feature_table_v2.csv 口径一致，回归对照用）。
  - v3_8k/tiny：定窗提取（train 长音频多点采 K 窗扩展行、val/test 单窗居中），
               模型列不含 duration_sec（定窗后恒定）。
输出列：meta(audio_path,label,source_id,split,sample_type,dataset_id,duration_sec,window_index,read_status,read_error) + 特征列。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from petlink.features.extractor import (
    PRESETS,
    V2_16K,
    extract_features_from_samples,
    feature_columns_for,
    load_audio_mono,
    to_window,
)

META_COLUMNS = [
    "audio_path",
    "label",
    "source_id",
    "split",
    "sample_type",
    "dataset_id",
    "duration_sec",
    "window_index",
    "read_status",
    "read_error",
]


def resolve_path(raw: str):
    """v3 清单用相对路径；v2 封存清单是绝对路径，两者都兼容。"""
    path = Path(raw)
    if path.is_absolute() and path.exists():
        return path
    relative = Path(__file__).resolve().parents[3] / raw
    return relative if relative.exists() else path


def iter_rows(manifest_path: Path, limit: int | None):
    with open(manifest_path, encoding="utf-8-sig", newline="") as f:
        for index, row in enumerate(csv.DictReader(f)):
            if limit is not None and index >= limit:
                break
            yield row


def window_starts(total: int, window_samples: int, k: int) -> list[int]:
    """长音频取 K 个均匀起点（首/中/尾对齐），去重。"""
    if total <= window_samples:
        return [0]
    if k <= 1:
        return [(total - window_samples) // 2]
    positions = sorted({int(i * (total - window_samples) / (k - 1)) for i in range(k)})
    return positions or [(total - window_samples) // 2]


def build_rows(manifest_path: Path, config: FeatureConfig, expand_k: int, limit: int | None, log_every: int):
    windowed = config.name != "v2_16k"
    window_len_default = int(config.target_sample_rate * config.window_seconds)
    rows = []
    total_samples = 0
    for index, row in enumerate(iter_rows(manifest_path, limit)):
        meta = {
            column: row.get(column, "")
            for column in META_COLUMNS
            if column not in ("duration_sec", "window_index", "read_status", "read_error")
        }
        audio_path = resolve_path(row["audio_path"])
        try:
            y, sr = load_audio_mono(audio_path, config)
            if windowed:
                window_len = int(sr * config.window_seconds)
                k = expand_k if row.get("split", "train") == "train" else 1
                starts = window_starts(len(y), window_len, k)
            else:
                starts = [0]
            for window_index, start in enumerate(starts):
                if windowed:
                    segment = to_window(y[start:], config.window_seconds, sr)
                else:
                    segment = y
                features = extract_features_from_samples(segment, sr, config)
                output = dict(meta)
                output["duration_sec"] = round(float(len(y) / sr), 6)
                output["window_index"] = window_index if windowed else 0
                output["read_status"] = "ok"
                output["read_error"] = ""
                output.update(features)
                rows.append(output)
            total_samples += 1
        except Exception as exc:
            output = dict(meta)
            output["duration_sec"] = row.get("duration_sec", "")
            output["window_index"] = 0
            output["read_status"] = "failed"
            output["read_error"] = f"{type(exc).__name__}: {exc}"
            output.update({name: float("nan") for name in feature_columns_for(config, include_duration=False)})
            rows.append(output)
        if (index + 1) % log_every == 0:
            print(f"processed={index + 1} rows={len(rows)}", flush=True)
    assert window_len_default > 0
    return rows, total_samples


def main() -> int:
    parser = argparse.ArgumentParser(description="构建特征表")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preset", choices=sorted(PRESETS), default="v3_8k")
    parser.add_argument("--train-expand-k", type=int, default=1, help="train 长音频采 K 窗（v3/tiny 生效）")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    config = PRESETS[args.preset]
    rows, total_samples = build_rows(args.manifest, config, args.train_expand_k, args.limit, log_every=50)
    columns = META_COLUMNS + feature_columns_for(config, include_duration=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    failed = sum(1 for row in rows if row["read_status"] != "ok")
    print(f"wrote {args.out}: samples={total_samples} rows={len(rows)} failed={failed} preset={config.name}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
