from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DATA_DIR, DATABASE_PATH, EXPORTS_DIR, UPLOADS_DIR
from .models import TABLE_SQL


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "training" / "manifests").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "training" / "runs").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "imu" / "simulated_sessions").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "imu" / "training_candidates").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "imu" / "models").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "imu" / "reports").mkdir(parents=True, exist_ok=True)
    for name in ("images", "videos", "audio"):
        (UPLOADS_DIR / name).mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_data_dirs()
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_database() -> None:
    ensure_data_dirs()
    with get_connection() as connection:
        cursor = connection.cursor()
        for statement in TABLE_SQL:
            cursor.execute(statement)
        _apply_compatible_migrations(cursor)
        connection.commit()


def _column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def _apply_compatible_migrations(cursor: sqlite3.Cursor) -> None:
    if not _column_exists(cursor, "users", "password_hash"):
        cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
    recognition_columns = {
        "user_id": "TEXT DEFAULT ''",
        "original_filename": "TEXT DEFAULT ''",
        "display_label": "TEXT DEFAULT ''",
        "warning": "TEXT DEFAULT ''",
        "user_notes": "TEXT DEFAULT ''",
        "saved_to_timeline": "INTEGER DEFAULT 0",
        "created_post_id": "TEXT DEFAULT ''",
        "added_to_training_candidates": "INTEGER DEFAULT 0",
    }
    for column_name, column_type in recognition_columns.items():
        if not _column_exists(cursor, "recognition_records", column_name):
            cursor.execute(f"ALTER TABLE recognition_records ADD COLUMN {column_name} {column_type}")
    candidate_columns = {
        "standard_label": "TEXT DEFAULT ''",
        "review_status": "TEXT DEFAULT 'candidate'",
        "reviewed_at": "TEXT DEFAULT ''",
        "promoted_at": "TEXT DEFAULT ''",
    }
    for column_name, column_type in candidate_columns.items():
        if not _column_exists(cursor, "training_candidates_web", column_name):
            cursor.execute(f"ALTER TABLE training_candidates_web ADD COLUMN {column_name} {column_type}")
    imu_session_columns = {
        "device_id": "TEXT DEFAULT ''",
        "sample_rate_hz": "REAL DEFAULT 0",
        "scenario": "TEXT DEFAULT ''",
        "sensor_position": "TEXT DEFAULT ''",
        "duration_s": "REAL DEFAULT 0",
        "created_at": "TEXT DEFAULT ''",
        "notes": "TEXT DEFAULT ''",
    }
    for column_name, column_type in imu_session_columns.items():
        if not _column_exists(cursor, "imu_sessions", column_name):
            cursor.execute(f"ALTER TABLE imu_sessions ADD COLUMN {column_name} {column_type}")
    imu_sample_columns = {
        "seq": "INTEGER DEFAULT NULL",
        "tail_angle_deg": "REAL DEFAULT NULL",
        "battery": "INTEGER DEFAULT NULL",
        "rssi": "INTEGER DEFAULT NULL",
    }
    for column_name, column_type in imu_sample_columns.items():
        if not _column_exists(cursor, "imu_samples", column_name):
            cursor.execute(f"ALTER TABLE imu_samples ADD COLUMN {column_name} {column_type}")
    multimodal_columns = {
        "audio_label": "TEXT DEFAULT ''",
        "audio_confidence": "REAL DEFAULT 0",
        "imu_motion_confidence": "REAL DEFAULT 0",
        "fusion_method": "TEXT DEFAULT ''",
        "confidence_type": "TEXT DEFAULT ''",
        "safety_message": "TEXT DEFAULT ''",
    }
    for column_name, column_type in multimodal_columns.items():
        if not _column_exists(cursor, "multimodal_emotion_records", column_name):
            cursor.execute(f"ALTER TABLE multimodal_emotion_records ADD COLUMN {column_name} {column_type}")
    imu_annotation_columns = {
        "record_id": "TEXT DEFAULT ''",
    }
    for column_name, column_type in imu_annotation_columns.items():
        if not _column_exists(cursor, "imu_annotations", column_name):
            cursor.execute(f"ALTER TABLE imu_annotations ADD COLUMN {column_name} {column_type}")
    index_statements = (
        "CREATE INDEX IF NOT EXISTS idx_imu_samples_session_id ON imu_samples (imu_session_id)",
        "CREATE INDEX IF NOT EXISTS idx_imu_samples_timestamp_ms ON imu_samples (timestamp_ms)",
        "CREATE INDEX IF NOT EXISTS idx_imu_samples_seq ON imu_samples (seq)",
        "CREATE INDEX IF NOT EXISTS idx_imu_windows_session_id ON imu_windows (imu_session_id)",
        "CREATE INDEX IF NOT EXISTS idx_imu_windows_rule_label ON imu_windows (rule_motion_label)",
        "CREATE INDEX IF NOT EXISTS idx_imu_windows_model_label ON imu_windows (model_motion_label)",
        "CREATE INDEX IF NOT EXISTS idx_multimodal_pet_id ON multimodal_emotion_records (pet_id)",
        "CREATE INDEX IF NOT EXISTS idx_multimodal_user_id ON multimodal_emotion_records (user_id)",
        "CREATE INDEX IF NOT EXISTS idx_multimodal_recognition_id ON multimodal_emotion_records (recognition_id)",
        "CREATE INDEX IF NOT EXISTS idx_multimodal_imu_session_id ON multimodal_emotion_records (imu_session_id)",
        "CREATE INDEX IF NOT EXISTS idx_imu_annotations_user_id ON imu_annotations (user_id)",
        "CREATE INDEX IF NOT EXISTS idx_imu_annotations_session_id ON imu_annotations (imu_session_id)",
        "CREATE INDEX IF NOT EXISTS idx_imu_annotations_window_id ON imu_annotations (window_id)",
        "CREATE INDEX IF NOT EXISTS idx_imu_annotations_record_id ON imu_annotations (record_id)",
        "CREATE INDEX IF NOT EXISTS idx_imu_training_candidates_user_id ON imu_training_candidates (user_id)",
        "CREATE INDEX IF NOT EXISTS idx_imu_training_candidates_annotation_id ON imu_training_candidates (annotation_id)",
        "CREATE INDEX IF NOT EXISTS idx_imu_training_candidates_window_id ON imu_training_candidates (window_id)",
    )
    for statement in index_statements:
        cursor.execute(statement)


def fetch_all(query: str, params: tuple | list = ()) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def fetch_one(query: str, params: tuple | list = ()) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(query, params).fetchone()
    return dict(row) if row is not None else None


def execute(query: str, params: tuple | list = ()) -> None:
    with get_connection() as connection:
        connection.execute(query, params)
        connection.commit()


def database_exists() -> bool:
    return Path(DATABASE_PATH).exists()
