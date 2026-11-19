r"""CatMeows（Zenodo 4008297）入库流水线。

用法：.venv/Scripts/python.exe -m petlink.data.ingest_catmeows

产出（data/external/catmeows_zenodo_4008297/）：
  extracted/dataset/*.wav（原始，只读）
  audit_report.md        440 条 ffprobe + 哈希 + 查重结果
  spectrograms/review_grid_{B,F,I}.png   分情境目检网格（0–4kHz 显示窗）
  label_mapping_matrix.csv               19 列映射矩阵（source_id=catmeows_<catID>）
  SOURCE.md                              九字段来源登记
许可：CC BY-NC 4.0（Zenodo 页面字段，红队核实）；仅限研究用途。
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

from petlink.data.audit_tools import (
    ffprobe_info,
    load_pcm,
    pcm_16k_sha,
    render_spectrogram_grid,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[3]
DS = ROOT / "data" / "external" / "catmeows_zenodo_4008297"
WAV_DIR = DS / "extracted" / "dataset"
BASELINE = ROOT / "metadata" / "hash_baseline_old_project.csv"

FILENAME_RE = re.compile(r"^([BFI])_([A-Z0-9]+?)_(MC|EU)_(FI|FN|MI|MN)_([A-Z0-9]+?)_R?(\d)(\d{2})\.wav$", re.IGNORECASE)
CONTEXT_NAMES = {"B": "brushing", "F": "waiting_for_food", "I": "isolation"}
SEX_NAMES = {"FI": "female_intact", "FN": "female_neutered", "MI": "male_intact", "MN": "male_neutered"}

# 红队审查 + 新旧两份文档分歧后的裁决（记录于 SOURCE.md / DECISIONS.md）：
LABEL_MAP = {
    "F": ("request_seeking", "context_derived", "high"),
    "B": ("unknown_review", "context_derived", "low"),   # 两文档分歧（affiliative 候选 vs threat 复核）→ 人工听审定
    "I": ("unknown_review", "context_derived", "low"),
}


def main() -> int:
    wavs = sorted(WAV_DIR.glob("*.wav"))
    print(f"found {len(wavs)} wavs")
    if len(wavs) != 440:
        print(f"WARN: expected 440, got {len(wavs)}")

    baseline_hashes = set()
    if BASELINE.exists():
        with open(BASELINE, encoding="utf-8") as f:
            baseline_hashes = {row["sha256"] for row in csv.DictReader(f)}
        print(f"baseline hashes loaded: {len(baseline_hashes)}")

    matrix_rows = []
    parse_failed = []
    seen_pcm: dict[str, str] = {}
    audit_failures = 0
    for path in wavs:
        match = FILENAME_RE.match(path.name)
        if not match:
            parse_failed.append(path.name)
            continue
        context, cat_id, breed, sex, owner, session, counter = match.groups()
        info = ffprobe_info(path)
        if "error" in info:
            audit_failures += 1
        file_hash = sha256_file(path)
        pcm_hash = pcm_16k_sha(path, target_sr=8000)  # 原生 8k，内容哈希按原速率
        duplicate_of = ""
        if pcm_hash in seen_pcm:
            duplicate_of = seen_pcm[pcm_hash]
        elif file_hash in baseline_hashes:
            duplicate_of = "old_project(hash)"
        seen_pcm.setdefault(pcm_hash, path.name)
        proposed_label, label_origin, label_confidence = LABEL_MAP[context.upper()]
        matrix_rows.append(
            {
                "dataset_id": "catmeows_zenodo_4008297",
                "original_relpath": str(path.relative_to(DS)).replace("\\", "/"),
                "original_filename": path.name,
                "parsed_context_raw": context,
                "parsed_context_name": CONTEXT_NAMES[context.upper()],
                "parsed_cat_id": cat_id,
                "parsed_breed": breed,
                "parsed_sex": SEX_NAMES[sex.upper()],
                "parsed_owner_id": owner,
                "parsed_session_id": f"R{session}",
                "source_id_proposed": f"catmeows_{cat_id}",
                "proposed_label": proposed_label,
                "label_origin": label_origin,
                "label_confidence": label_confidence,
                "review_status": "needs_human_listen",
                "original_sample_rate_hz": info.get("sample_rate", ""),
                "channels": info.get("channels", ""),
                "duration_sec": info.get("duration_sec", ""),
                "effective_bandwidth_hz": 4000,
                "sha256_file": file_hash,
                "sha256_pcm": pcm_hash,
                "duplicate_of": duplicate_of,
                "license": "CC BY-NC 4.0",
                "nc_flag": "yes",
                "attribution_required": "yes",
                "notes": "",
            }
        )

    # 频谱图目检网格：每情境一网格，每猫抽 1 条（21 猫 → ~21 格）
    for context_key, context_name in CONTEXT_NAMES.items():
        by_cat: dict[str, Path] = {}
        for row in matrix_rows:
            if row["parsed_context_raw"] == context_key and row["parsed_cat_id"] not in by_cat:
                by_cat[row["parsed_cat_id"]] = WAV_DIR / row["original_filename"]
        paths = sorted(by_cat.values(), key=lambda p: p.name)
        render_spectrogram_grid(
            paths,
            DS / "spectrograms" / f"review_grid_{context_key}.png",
            fmax_hz=4000,
            title=f"CatMeows context={context_name} ({context_key}) — one clip per cat (n={len(paths)}) — 0-4kHz window",
            cols=6,
        )
        print(f"grid written: {context_key} ({len(paths)} cats)")

    # audit 报告
    durations = [float(r["duration_sec"]) for r in matrix_rows if r["duration_sec"]]
    srs = Counter(r["original_sample_rate_hz"] for r in matrix_rows)
    dup_within = sum(1 for r in matrix_rows if r["duplicate_of"].startswith("kaggle") or ("." in r["duplicate_of"] and "old_project" not in r["duplicate_of"]))
    dup_old = sum(1 for r in matrix_rows if r["duplicate_of"] == "old_project(hash)")
    context_counts = Counter(r["parsed_context_raw"] for r in matrix_rows)
    cats = sorted({r["parsed_cat_id"] for r in matrix_rows})
    report = [
        "# CatMeows audit report",
        f"- files: {len(matrix_rows)} parsed, {len(parse_failed)} parse_failed",
        f"- contexts: {dict(context_counts)}",
        f"- cats: {len(cats)} ({cats[:5]}...)",
        f"- sample_rate distribution: {dict(srs)} (native 8kHz a-law 系)",
        f"- duration: min={min(durations):.2f}s max={max(durations):.2f}s mean={sum(durations)/len(durations):.2f}s" if durations else "no durations",
        f"- duplicates: within-dataset={dup_within}, vs-old-project={dup_old}",
        f"- audit failures: {audit_failures}",
        "- mapping: F→request_seeking(context_derived/high); B→unknown_review(两文档分歧); I→unknown_review",
        "- extras.zip 排除（非 meow/未切分素材）",
    ]
    (DS / "audit_report.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))

    # 映射矩阵
    fields = list(matrix_rows[0].keys())
    with open(DS / "label_mapping_matrix.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(matrix_rows)
    print(f"mapping matrix: {DS / 'label_mapping_matrix.csv'} ({len(matrix_rows)} rows)")

    if parse_failed:
        print("PARSE FAILED:", parse_failed[:10])
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
