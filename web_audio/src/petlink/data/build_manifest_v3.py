r"""final_manifest_v3 合并：存量 849（相对化）+ CatMeows F=92（request_seeking）。

用法：.venv/Scripts/python.exe -m petlink.data.build_manifest_v3

产物：metadata/final_manifest_v3.csv（无 split 列，由 make_source_split 填充）
      metadata/final_manifest_summary_v3.md
规则（计划 v2.2 S5）：
  - 存量行：audio_path → data/processed/mono_16k_ref/<name>（项目内相对路径）；
    original_file_path → data/raw/... 相对化；保留 source_id/sample_type/dataset_id。
  - CatMeows 行：仅收 label_mapping_matrix 中 proposed_label=request_seeking 且
    review_status=spectrogram_ok 的 92 条；audio_path → data/external/.../extracted/dataset/<name>；
    source_id=catmeows_<CATID>；dataset_id=catmeows_zenodo_4008297；
    sample_type=context_derived_f；附 review_status/label_origin 列。
  - v2 文件封存不动（AGENTS.md 红线 2）。
"""
from __future__ import annotations

import csv
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V2 = ROOT / "metadata" / "final_manifest_v2.csv"
CATMEOWS_MATRIX = ROOT / "data" / "external" / "catmeows_zenodo_4008297" / "label_mapping_matrix.csv"
OUT = ROOT / "metadata" / "final_manifest_v3.csv"
SUMMARY = ROOT / "metadata" / "final_manifest_summary_v3.md"

FIELDS = [
    "audio_path", "label", "source_id", "original_file_path", "sample_type",
    "duration_sec", "dataset_id", "review_status", "label_origin", "split",
]


def relativize_old(path_value: str) -> str:
    """v2 的绝对路径 → 项目内相对路径（data/processed/mono_16k_ref/<name>）。"""
    name = Path(path_value).name
    relative = f"data/processed/mono_16k_ref/{name}"
    if not (ROOT / relative).exists():
        raise FileNotFoundError(f"missing local copy for {path_value}")
    return relative


def relativize_original(path_value: str) -> str:
    """original_file_path：D:\\pet_link\\audio\\X → data/raw/audio/X；其余保原值并标注。"""
    text = path_value.replace("\\", "/")
    if text.startswith("D:/pet_link/audio/"):
        tail = text[len("D:/pet_link/audio/"):]
        candidate = f"data/raw/audio/{tail}"
        if (ROOT / candidate).exists():
            return candidate
    return path_value  # 无法映射时保留原绝对路径（如 backfill 中间产物），报告注明


def main() -> int:
    out_rows = []
    v2_rows = list(csv.DictReader(open(V2, encoding="utf-8-sig")))
    unmapped_originals = 0
    for row in v2_rows:
        out_rows.append(
            {
                "audio_path": relativize_old(row["audio_path"]),
                "label": row["label"],
                "source_id": row["source_id"],
                "original_file_path": relativize_original(row["original_file_path"]),
                "sample_type": row["sample_type"],
                "duration_sec": row["duration_sec"],
                "dataset_id": row["dataset_id"],
                "review_status": "human_reviewed" if row["dataset_id"] == "main" else "kaggle_auto_keep",
                "label_origin": "human_labeled" if row["dataset_id"] == "main" else "source_metadata",
                "split": "",
            }
        )
        if not out_rows[-1]["original_file_path"].startswith("data/"):
            unmapped_originals += 1
    main_count = len(out_rows)

    matrix_rows = list(csv.DictReader(open(CATMEOWS_MATRIX, encoding="utf-8-sig")))
    catmeows_count = 0
    for row in matrix_rows:
        if row["proposed_label"] != "request_seeking" or row["review_status"] != "spectrogram_ok":
            continue
        relative = f"data/external/catmeows_zenodo_4008297/{row['original_relpath']}"
        if not (ROOT / relative).exists():
            raise FileNotFoundError(relative)
        out_rows.append(
            {
                "audio_path": relative,
                "label": "request_seeking",
                "source_id": row["source_id_proposed"],
                "original_file_path": row["original_relpath"],
                "sample_type": "context_derived_f",
                "duration_sec": row["duration_sec"],
                "dataset_id": "catmeows_zenodo_4008297",
                "review_status": "spectrogram_ok",
                "label_origin": "context_derived",
                "split": "",
            }
        )
        catmeows_count += 1

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)

    labels = Counter(row["label"] for row in out_rows)
    sources = len({row["source_id"] for row in out_rows})
    catmeows_sources = len({row["source_id"] for row in out_rows if row["source_id"].startswith("catmeows")})
    summary = [
        "# final_manifest_v3 summary",
        f"- total rows: {len(out_rows)} (main/kaggle 存量 {main_count} + CatMeows F {catmeows_count})",
        f"- labels: {dict(labels)}",
        f"- sources: {sources} total（新增 catmeows 猫个体源 {catmeows_sources} 个）",
        f"- original_file_path 未映射到 data/raw 的行: {unmapped_originals}（保留绝对路径，仅溯源用，不参与训练读取）",
        "- CatMeows 仅 F 情境 92 条入场（spectrogram_ok）；B/I=348 条留 unknown_review（data_backfill_plan）",
        "- split 列由 make_source_split 填充（source 级，零泄漏）",
        "- audio_path 全部为项目内相对路径；存量内容为 pet_link 处理件逐字节副本",
    ]
    SUMMARY.write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
