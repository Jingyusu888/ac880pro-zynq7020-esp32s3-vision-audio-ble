from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from ..config import DATA_DIR
from ..database import fetch_all
from .training_label_service import TRAINABLE_STANDARD_LABELS


TRAINING_DIR = DATA_DIR / "training"
MANIFEST_DIR = TRAINING_DIR / "manifests"
MANIFEST_PATH = MANIFEST_DIR / "web_training_ready.csv"
SUMMARY_PATH = MANIFEST_DIR / "web_training_ready_summary.md"


def export_training_manifest() -> dict[str, Any]:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    rows = fetch_all(
        """
        SELECT candidate_id, recognition_id, pet_id, user_id, audio_path,
               prediction_label, user_label, standard_label, user_notes,
               quality_status, review_status, source, created_at
        FROM training_candidates_web
        WHERE quality_status = 'accepted'
          AND review_status = 'training_ready'
          AND standard_label IN ('affiliative_relaxed', 'request_seeking', 'threat_discomfort', 'pain_distress')
        ORDER BY created_at ASC
        """
    )
    excluded_rows = fetch_all(
        """
        SELECT standard_label
        FROM training_candidates_web
        WHERE standard_label IN ('uncertain', 'noncat_noise')
        """
    )

    manifest_rows: list[dict[str, Any]] = []
    missing_audio = 0
    for row in rows:
        audio_path = Path(row.get("audio_path") or "")
        if not audio_path.exists():
            missing_audio += 1
            continue
        manifest_rows.append(
            {
                "sample_id": row["candidate_id"],
                "audio_path": str(audio_path),
                "standard_label": row["standard_label"],
                "user_label": row.get("user_label", ""),
                "recognition_id": row["recognition_id"],
                "candidate_id": row["candidate_id"],
                "pet_id": row.get("pet_id", ""),
                "user_id": row.get("user_id", ""),
                "source": row.get("source", ""),
                "created_at": row.get("created_at", ""),
            }
        )

    with MANIFEST_PATH.open("w", encoding="utf-8", newline="") as output:
        fieldnames = [
            "sample_id",
            "audio_path",
            "standard_label",
            "user_label",
            "recognition_id",
            "candidate_id",
            "pet_id",
            "user_id",
            "source",
            "created_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    counts = Counter(row["standard_label"] for row in manifest_rows)
    enough_total = len(manifest_rows) >= 8
    enough_classes = len(counts) >= 2
    min_class_count = min(counts.values()) if counts else 0
    enough_training = enough_total and enough_classes and min_class_count >= 2

    excluded_count = len(excluded_rows)
    summary_lines = [
        "# Web Training Ready Summary",
        "",
        f"- Manifest: `{MANIFEST_PATH}`",
        f"- Total exported samples: {len(manifest_rows)}",
        f"- Missing audio rows skipped: {missing_audio}",
        f"- uncertain/noncat_noise excluded rows: {excluded_count}",
        f"- Enough to train baseline candidate: {'yes' if enough_training else 'no'}",
        "",
        "## Class Counts",
        "",
    ]
    for label in sorted(TRAINABLE_STANDARD_LABELS):
        summary_lines.append(f"- {label}: {counts.get(label, 0)}")
    if counts and (len(counts) < 4 or min_class_count < 5):
        summary_lines.extend(
            [
                "",
                "## Imbalance Note",
                "",
                "Class coverage is still small or imbalanced. Treat any model trained from this manifest as an internal candidate only.",
            ]
        )
    SUMMARY_PATH.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "manifest_path": str(MANIFEST_PATH),
        "summary_path": str(SUMMARY_PATH),
        "sample_count": len(manifest_rows),
        "class_counts": dict(counts),
        "missing_audio_count": missing_audio,
        "excluded_uncertain_noncat_count": excluded_count,
        "enough_to_train": enough_training,
    }
