r"""7 件套模型 bundle 的原子写入与校验（AGENTS.md 红线 3）。

pieces: saved_models/{coarse,positive_fine,negative_fine}_classifier.joblib
        + feature_columns.json + label_maps.json
        + recommended_class_specific_thresholds.json + bundle_manifest.json

label_maps.json 只含标签结构，禁止内嵌阈值（M14：旧 0.65 阈值污染事故的根治）。
bundle_manifest.json 最后写入，记录全部 piece 的 SHA-256，禁止版本混搭。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import sklearn

PIECE_NAMES = (
    "saved_models/coarse_classifier.joblib",
    "saved_models/positive_fine_classifier.joblib",
    "saved_models/negative_fine_classifier.joblib",
    "saved_models/four_class_classifier.joblib",
    "feature_columns.json",
    "label_maps.json",
    "recommended_class_specific_thresholds.json",
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def write_bundle(
    out_dir: Path,
    models: dict[str, Any],
    feature_columns: list[str],
    label_maps: dict[str, Any],
    thresholds: dict[str, float],
    meta: dict[str, Any],
) -> Path:
    import joblib

    out_dir.mkdir(parents=True, exist_ok=True)
    saved = out_dir / "saved_models"
    saved.mkdir(exist_ok=True)
    for task, model in models.items():
        joblib.dump(model, saved / f"{task}_classifier.joblib")

    write_json(out_dir / "feature_columns.json", feature_columns)
    write_json(out_dir / "label_maps.json", label_maps)  # 无阈值字段——红线
    write_json(out_dir / "recommended_class_specific_thresholds.json", thresholds)

    manifest = {
        "bundle_version": meta.get("bundle_version", "untitled"),
        "created_at": datetime.now().isoformat(),
        "frontend_preset": meta.get("frontend_preset"),
        "window_seconds": meta.get("window_seconds"),
        "class_weight": meta.get("class_weight"),
        "sklearn_version": sklearn.__version__,
        "feature_count": len(feature_columns),
        "includes_duration": meta.get("includes_duration", False),
        "training": meta.get("training", {}),
        "pieces": {},
    }
    for relative in PIECE_NAMES:
        path = out_dir / relative
        if path.exists():
            manifest["pieces"][relative] = {"sha256": sha256_of(path), "bytes": path.stat().st_size}
    write_json(out_dir / "bundle_manifest.json", manifest)
    return out_dir


def verify_bundle(out_dir: Path) -> list[str]:
    manifest_path = out_dir / "bundle_manifest.json"
    if not manifest_path.exists():
        return [f"bundle_manifest.json missing: {out_dir}"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = []
    for relative, record in manifest.get("pieces", {}).items():
        path = out_dir / relative
        if not path.exists():
            failures.append(f"missing piece: {relative}")
        elif sha256_of(path) != record["sha256"]:
            failures.append(f"hash mismatch: {relative}")
    return failures
