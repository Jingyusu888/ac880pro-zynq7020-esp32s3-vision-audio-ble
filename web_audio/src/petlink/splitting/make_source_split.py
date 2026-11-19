r"""source 级切分（AGENTS.md 红线 4/5 的机器实现）。

用法：
  .venv/Scripts/python.exe src/petlink/splitting/make_source_split.py \
      --manifest metadata/final_manifest_v2.csv --out metadata/split_v3_dryrun.csv \
      [--config configs/dataset.yaml] [--allow-incomplete]

规则：
  1. source_id 是切分原子：同一 source 的所有行进同一 split（零泄漏）。
  2. fixed_source_assignment 显式指定的 source 优先。
  3. 其余 source 按类需求贪心补足 val/test 下限（seed 固定可复现），剩余全进 train。
  4. 每类 val/test source 数与样本数下限校验；strict 模式不满足即 fail-fast，
     --allow-incomplete 模式（仅限存量 dry-run）降级为警告并在报告中标明。
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

SPLITS = ("train", "val", "test")


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["split"]


def read_manifest(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def source_label_matrix(rows: list[dict]) -> dict[str, Counter]:
    matrix: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        matrix[row["source_id"]][row["label"]] += 1
    return dict(matrix)


def assign(rows: list[dict], cfg: dict, allow_incomplete: bool) -> tuple[dict[str, str], list[str], list[str]]:
    matrix = source_label_matrix(rows)
    sources = sorted(matrix)
    assignment: dict[str, str] = {}
    warnings: list[str] = []

    fixed = cfg.get("fixed_source_assignment", {})
    unknown_fixed = [name for name in fixed if name not in matrix]
    for name in unknown_fixed:
        warnings.append(f"fixed_source_assignment 中 {name!r} 不在清单中（忽略）")
    for name, split in fixed.items():
        if name in matrix:
            assignment[name] = split

    labels = sorted({row["label"] for row in rows})
    rng = random.Random(cfg.get("seed", 42))

    # 每类 val/test 需求：source 数下限（request_seeking 有专属下限）
    def min_sources(label: str, split: str) -> int:
        specific = cfg.get(f"min_{split}_sources_{label}")
        if specific is not None:
            return int(specific)
        return int(cfg.get(f"min_{split}_sources_per_class", 1))

    def min_samples(label: str, split: str) -> int:
        specific = cfg.get(f"min_{split}_samples_{label}")
        if specific is not None:
            return int(specific)
        return int(cfg.get(f"min_{split}_samples_per_class", 2))

    def split_stats(label: str, split: str) -> tuple[int, int]:
        srcs = [s for s, sp in assignment.items() if sp == split]
        return sum(1 for s in srcs if label in matrix[s]), sum(matrix[s][label] for s in srcs)

    for label in labels:
        for split in SPLITS[1:]:  # val, test
            need_sources = min_sources(label, split)
            need_samples = min_samples(label, split)
            have_sources, have_samples = split_stats(label, split)
            # 先补样本量缺口：优先挑该类样本多的 source
            candidates = [s for s in sources if s not in assignment and label in matrix[s]]
            candidates.sort(key=lambda s: (-matrix[s][label], s))
            while have_samples < need_samples and candidates:
                pick = candidates.pop(0)
                assignment[pick] = split
                have_samples += matrix[pick][label]
                have_sources += 1
            # 再补 source 数缺口：挑该类样本中等的 source
            candidates = [s for s in sources if s not in assignment and label in matrix[s]]
            rng.shuffle(candidates)
            while have_sources < need_sources and candidates:
                pick = candidates.pop(0)
                assignment[pick] = split
                have_samples += matrix[pick][label]
                have_sources += 1
            if have_sources < need_sources or have_samples < need_samples:
                message = (
                    f"{label}/{split}: sources={have_sources}(<{need_sources})? samples={have_samples}(<{need_samples})? "
                    f"——旧源不足以支撑该类 val/test，等待回填（CatMeows 猫）"
                )
                if allow_incomplete:
                    warnings.append(f"INCOMPLETE {message}")
                else:
                    raise SystemExit(f"FAIL-FAST {message}（strict 模式；存量 dry-run 请加 --allow-incomplete）")

    # 剩余全部进 train
    for source in sources:
        assignment.setdefault(source, "train")
    return assignment, warnings, []


def validate(rows: list[dict], assignment: dict[str, str], allow_incomplete: bool = False) -> tuple[list[str], list[str]]:
    """核心断言：泄漏永远硬失败；类覆盖在 allow-incomplete 模式降级为软失败。"""
    by_source: dict[str, set[str]] = defaultdict(set)
    per_class: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        by_source[row["source_id"]].add(assignment[row["source_id"]])
        per_class[row["label"]][assignment[row["source_id"]]] += 1
    hard: list[str] = []
    soft: list[str] = []
    leaked = {s: sp for s, sp in by_source.items() if len(sp) > 1}
    if leaked:
        hard.append(f"LEAKAGE: {len(leaked)} 个 source 跨 split: {list(leaked)[:5]}")
    for label, counter in sorted(per_class.items()):
        missing = [s for s in SPLITS if counter[s] == 0]
        if missing:
            (soft if allow_incomplete else hard).append(f"{label} 在 {missing} 无覆盖（等待回填）")
    return hard, soft


def main() -> int:
    parser = argparse.ArgumentParser(description="source 级切分")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/dataset.yaml"))
    parser.add_argument("--allow-incomplete", action="store_true", help="存量 dry-run：下限不满足降级为警告")
    args = parser.parse_args()

    cfg = load_config(args.config)
    rows = read_manifest(args.manifest)
    assignment, warnings, _ = assign(rows, cfg, args.allow_incomplete)
    hard_failures, soft_failures = validate(rows, assignment, args.allow_incomplete)

    for line in warnings:
        print(f"WARN {line}")
    for line in soft_failures:
        print(f"SOFT {line}")
    if hard_failures:
        print(f"\nVALIDATION FAIL ({len(hard_failures)}):")
        for line in hard_failures:
            print("  " + line)
        return 1

    # 落盘：manifest + split 列
    fieldnames = list(rows[0].keys())
    if "split" not in fieldnames:
        fieldnames.append("split")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row["split"] = assignment[row["source_id"]]
            writer.writerow(row)

    # 报告
    stats: dict[str, Counter] = defaultdict(Counter)
    src_stats: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        stats[row["split"]][row["label"]] += 1
        src_stats[row["split"]][row["label"]] += 0
    print(f"\nwrote {args.out}")
    print(f"{'split':8s} " + " ".join(f"{label:>22s}" for label in sorted(stats["train"])))
    for split in SPLITS:
        cells = " ".join(f"{stats[split][label]:>22d}" for label in sorted(stats["train"]))
        print(f"{split:8s} {cells}")
    source_counts = Counter(assignment.values())
    print(f"sources: train={source_counts['train']} val={source_counts['val']} test={source_counts['test']} | 泄漏=0 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
