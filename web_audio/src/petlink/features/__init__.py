"""特征前端：唯一特征实现（训练/推理/板端对齐共用）。"""

from .extractor import (
    FeatureConfig,
    V2_16K,
    build_feature_table,
    extract_features,
    extract_features_from_samples,
    feature_columns_for,
    load_audio_mono,
    preset_from_name,
    preset_tiny_8k_2s,
    preset_v3_8k,
    preset_v3_8k_1s,
    preset_v3_8k_2s,
    resample_linear,
    to_window,
)

__all__ = [
    "FeatureConfig",
    "V2_16K",
    "build_feature_table",
    "extract_features",
    "extract_features_from_samples",
    "feature_columns_for",
    "load_audio_mono",
    "preset_from_name",
    "preset_tiny_8k_2s",
    "preset_v3_8k",
    "preset_v3_8k_1s",
    "preset_v3_8k_2s",
    "resample_linear",
    "to_window",
]
