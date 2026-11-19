r"""final_manifest_v5：v4 + CatMeows I 情境 221 条 → threat_discomfort。

依据（2026-10-20 T1 裁决，见 analysis/catmeows_i_relabel_review/ADJUDICATION.md）：
- 用户决策：I（isolation）221 条重新裁决入 threat_discomfort（context_derived/low/ai_spectrogram_ok）。
- 红线 4 source 级切分：I 与 B/F 同猫同源必须同侧 → 继承 v4 已确定的该猫 split（零泄漏）。
- CLE01 仅 I=20 条（无 B/F，v4 中不存在）→ 新 source 入 train（仅加训练信号，不动 eval 集，保 T5 消融干净）。

只生成新版本 v5，禁止改动 v4。CLE01 决策记录于 docs/DECISIONS.md。
"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V4 = ROOT / "metadata" / "final_manifest_v4.csv"
CATMEOWS_MATRIX = ROOT / "data" / "external" / "catmeows_zenodo_4008297" / "label_mapping_matrix.csv"
OUT = ROOT / "metadata" / "final_manifest_v5.csv"

FIELDS = ["audio_path", "label", "source_id", "original_file_path", "sample_type", "duration_sec", "dataset_id", "review_status", "label_origin", "split"]


def main() -> int:
    v4 = list(csv.DictReader(open(V4, encoding="utf-8-sig")))
    source_split = {r["source_id"]: r["split"] for r in v4}
    existing_audio = {r["audio_path"] for r in v4}

    new_source_assignments: dict[str, str] = {}

    added = 0
    cle01_train = 0
    for row in csv.DictReader(open(CATMEOWS_MATRIX, encoding="utf-8-sig")):
        if row["parsed_context_raw"] != "I":
            continue
        assert row["proposed_label"] == "threat_discomfort", row["original_filename"]
        assert row["review_status"] == "ai_spectrogram_ok", row["original_filename"]
        relative = f"data/external/catmeows_zenodo_4008297/{row['original_relpath']}"
        if relative in existing_audio:
            raise SystemExit(f"DUPLICATE audio_path in v4: {relative}")
        if not (ROOT / relative).exists():
            raise FileNotFoundError(relative)
        src = row["source_id_proposed"]
        if src in source_split:
            split = source_split[src]
        else:
            # 新 source（仅 CLE01）：入 train，仅加训练信号，不动 eval 集
            split = new_source_assignments.setdefault(src, "train")
            cle01_train += 1
        v4.append(
            {
                "audio_path": relative,
                "label": "threat_discomfort",
                "source_id": src,
                "original_file_path": row["original_relpath"],
                "sample_type": "context_derived_i",
                "duration_sec": row["duration_sec"],
                "dataset_id": "catmeows_zenodo_4008297",
                "review_status": "ai_spectrogram_ok",
                "label_origin": "context_derived",
                "split": split,
            }
        )
        added += 1

    # 零泄漏硬校验：每个 source 只能落一个 split
    by_source: dict[str, set[str]] = defaultdict(set)
    for r in v4:
        by_source[r["source_id"]].add(r["split"])
    leaked = {s: sp for s, sp in by_source.items() if len(sp) > 1}
    if leaked:
        for s, sp in leaked.items():
            print(f"LEAKAGE: {s} -> {sp}")
        return 1

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(v4)

    labels = Counter(r["label"] for r in v4)
    sources = len({r["source_id"] for r in v4})
    print(f"v5: rows={len(v4)} (+{added} I→threat; 新源入train={cle01_train}) labels={dict(labels)} sources={sources}")
    print(f"新 source 分配: {new_source_assignments or '无'}")
    print("泄漏=0 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
