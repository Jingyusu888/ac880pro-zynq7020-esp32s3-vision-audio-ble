from __future__ import annotations


TABLE_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        password_hash TEXT DEFAULT '',
        avatar TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pets (
        pet_id TEXT PRIMARY KEY,
        owner_user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        species TEXT NOT NULL,
        breed TEXT DEFAULT '',
        age TEXT DEFAULT '',
        avatar TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pet_timeline (
        timeline_id TEXT PRIMARY KEY,
        pet_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT DEFAULT '',
        related_post_id TEXT DEFAULT '',
        related_recognition_id TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recognition_records (
        recognition_id TEXT PRIMARY KEY,
        pet_id TEXT DEFAULT '',
        user_id TEXT DEFAULT '',
        audio_path TEXT DEFAULT '',
        original_filename TEXT DEFAULT '',
        prediction_label TEXT DEFAULT '',
        display_label TEXT DEFAULT '',
        confidence REAL DEFAULT 0,
        margin REAL DEFAULT 0,
        trigger INTEGER DEFAULT 0,
        warning TEXT DEFAULT '',
        user_label TEXT DEFAULT '',
        user_notes TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        saved_to_timeline INTEGER DEFAULT 0,
        created_post_id TEXT DEFAULT '',
        added_to_training_candidates INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS training_candidates_web (
        candidate_id TEXT PRIMARY KEY,
        recognition_id TEXT NOT NULL,
        pet_id TEXT DEFAULT '',
        user_id TEXT DEFAULT '',
        audio_path TEXT DEFAULT '',
        prediction_label TEXT DEFAULT '',
        user_label TEXT DEFAULT '',
        standard_label TEXT DEFAULT '',
        user_notes TEXT DEFAULT '',
        quality_status TEXT DEFAULT 'pending',
        review_status TEXT DEFAULT 'candidate',
        source TEXT DEFAULT 'web_user_annotation',
        reviewed_at TEXT DEFAULT '',
        promoted_at TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE(recognition_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT '',
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS posts (
        post_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        pet_id TEXT DEFAULT '',
        content TEXT NOT NULL,
        visibility TEXT NOT NULL DEFAULT 'public',
        post_type TEXT NOT NULL DEFAULT 'note',
        image_url TEXT DEFAULT '',
        source_recognition_id TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS post_likes (
        like_id TEXT PRIMARY KEY,
        post_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(post_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS post_comments (
        comment_id TEXT PRIMARY KEY,
        post_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        user_agent TEXT DEFAULT '',
        client_label TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS imu_sessions (
        imu_session_id TEXT PRIMARY KEY,
        pet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        device_id TEXT DEFAULT '',
        source TEXT NOT NULL,
        scenario TEXT DEFAULT '',
        sensor_position TEXT DEFAULT '',
        sample_rate_hz REAL DEFAULT 0,
        duration_s REAL DEFAULT 0,
        created_at TEXT DEFAULT '',
        started_at TEXT DEFAULT '',
        ended_at TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'created',
        notes TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS imu_samples (
        sample_id TEXT PRIMARY KEY,
        imu_session_id TEXT NOT NULL,
        timestamp_ms INTEGER NOT NULL,
        seq INTEGER DEFAULT NULL,
        ax REAL DEFAULT 0,
        ay REAL DEFAULT 0,
        az REAL DEFAULT 0,
        gx REAL DEFAULT 0,
        gy REAL DEFAULT 0,
        gz REAL DEFAULT 0,
        tail_angle REAL DEFAULT NULL,
        tail_angle_deg REAL DEFAULT NULL,
        battery INTEGER DEFAULT NULL,
        rssi INTEGER DEFAULT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS multimodal_emotion_records (
        record_id TEXT PRIMARY KEY,
        pet_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        recognition_id TEXT DEFAULT '',
        imu_session_id TEXT DEFAULT '',
        audio_label TEXT DEFAULT '',
        audio_confidence REAL DEFAULT 0,
        audio_prediction_label TEXT DEFAULT '',
        imu_motion_label TEXT DEFAULT '',
        imu_motion_confidence REAL DEFAULT 0,
        fused_label TEXT DEFAULT '',
        fused_confidence REAL DEFAULT 0,
        fusion_method TEXT DEFAULT '',
        confidence_type TEXT DEFAULT '',
        fusion_notes TEXT DEFAULT '',
        safety_message TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS imu_windows (
        window_id TEXT PRIMARY KEY,
        imu_session_id TEXT NOT NULL,
        window_start_ms INTEGER DEFAULT NULL,
        window_end_ms INTEGER DEFAULT NULL,
        acc_mean REAL DEFAULT NULL,
        acc_std REAL DEFAULT NULL,
        acc_max REAL DEFAULT NULL,
        acc_rms REAL DEFAULT NULL,
        gyro_mean REAL DEFAULT NULL,
        gyro_std REAL DEFAULT NULL,
        gyro_max REAL DEFAULT NULL,
        gyro_p95 REAL DEFAULT NULL,
        jerk_mean REAL DEFAULT NULL,
        jerk_max REAL DEFAULT NULL,
        peak_count INTEGER DEFAULT NULL,
        dominant_freq REAL DEFAULT NULL,
        rule_motion_label TEXT DEFAULT '',
        rule_motion_confidence REAL DEFAULT NULL,
        model_motion_label TEXT DEFAULT '',
        model_motion_confidence REAL DEFAULT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS imu_annotations (
        annotation_id TEXT PRIMARY KEY,
        imu_session_id TEXT DEFAULT '',
        window_id TEXT DEFAULT '',
        record_id TEXT DEFAULT '',
        user_id TEXT NOT NULL,
        pet_id TEXT NOT NULL,
        motion_label_user TEXT DEFAULT '',
        emotion_context_label_user TEXT DEFAULT '',
        quality_label TEXT NOT NULL,
        annotation_source TEXT DEFAULT '',
        comment TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS imu_training_candidates (
        candidate_id TEXT PRIMARY KEY,
        imu_session_id TEXT DEFAULT '',
        window_id TEXT DEFAULT '',
        annotation_id TEXT DEFAULT '',
        user_id TEXT NOT NULL,
        pet_id TEXT NOT NULL,
        feature_json TEXT DEFAULT '',
        label TEXT DEFAULT '',
        quality_status TEXT NOT NULL,
        review_status TEXT NOT NULL,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
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
    "CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_posts_user_id ON posts (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_posts_pet_id ON posts (pet_id)",
    "CREATE INDEX IF NOT EXISTS idx_post_likes_post_id ON post_likes (post_id)",
    "CREATE INDEX IF NOT EXISTS idx_post_comments_post_id ON post_comments (post_id)",
)
