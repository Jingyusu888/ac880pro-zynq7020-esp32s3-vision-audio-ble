r"""final_manifest_v4：v3 + CatMeows B 情境 127 条 → affiliative_relaxed。

依据（用户 2026-10-01 授权"结合来源判断，无误直接使用"）：
- CatMeows 文件名编码就是数据集自己的情境标注（B=brushing 梳毛互动）——来源可靠；
- 文献（Ntalampiras 2019）将 brushing 视为亲和情境 → 映射 affiliative_relaxed（context_derived/medium）；
- B 情境频谱 QC 已过（review_grid_B.png 17 猫全检）；
- B/F 同麦克风同猫的对照使 positive_fine 边界无法靠录音链作弊（方法学优势）；
- I（isolation）不入场：四标签无"分离焦虑"归属，错误映射会污染 pain/threat（记录于 DECISIONS）。
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V3 = ROOT / "metadata" / "final_manifest_v3.csv"
CATMEOWS_MATRIX = ROOT / "data" / "external" / "catmeows_zenodo_4008297" / "label_mapping_matrix.csv"
OUT = ROOT / "metadata" / "final_manifest_v4.csv"

FIELDS = ["audio_path", "label", "source_id", "original_file_path", "sample_type", "duration_sec", "dataset_id", "review_status", "label_origin", "split"]


def main() -> int:
    rows = list(csv.DictReader(open(V3, encoding="utf-8-sig")))
    existing_audio = {row["audio_path"] for row in rows}
    added = 0
    for matrix_row in csv.DictReader(open(CATMEOWS_MATRIX, encoding="utf-8-sig")):
        if matrix_row["parsed_context_raw"] != "B":
            continue
        relative = f"data/external/catmeows_zenodo_4008297/{matrix_row['original_relpath']}"
        if relative in existing_audio:
            continue
        if not (ROOT / relative).exists():
            raise FileNotFoundError(relative)
        rows.append(
            {
                "audio_path": relative,
                "label": "affiliative_relaxed",
                "source_id": matrix_row["source_id_proposed"],
                "original_file_path": matrix_row["original_relpath"],
                "sample_type": "context_derived_b",
                "duration_sec": matrix_row["duration_sec"],
                "dataset_id": "catmeows_zenodo_4008297",
                "review_status": "spectrogram_ok",
                "label_origin": "context_derived",
                "split": "",
            }
        )
        added += 1

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    labels = Counter(row["label"] for row in rows)
    sources = len({row["source_id"] for row in rows})
    print(f"v4: rows={len(rows)} (+{added} B→affiliative) labels={dict(labels)} sources={sources}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
