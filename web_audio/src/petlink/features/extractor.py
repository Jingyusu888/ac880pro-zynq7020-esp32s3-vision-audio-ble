r"""PetLink 特征提取统一实现（训练/推理/未来板端对齐的唯一特征源）。

合并自 D:\pet_link 的两份重复实现（src/feature_analysis.py 的 extract_features 主体
与 desktop_app/app/predict_clip.py 的 extract_features_from_samples），行为默认与
16k/4s/240 维时代逐位一致（tests/golden 回归 A 层保证）。

v3（8kHz）与 Tiny（60 维）通过 FeatureConfig 预设切换，禁止在调用侧散落常量。
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf

EPS = 1e-12


@dataclass(frozen=True)
class FeatureConfig:
    """特征前端契约。默认值 = 当前生产模型（16k/4s 时代）的精确常数。"""

    name: str = "v2_16k"
    target_sample_rate: int = 16000
    window_seconds: float = 4.0
    frame_length: int = 1024
    hop_length: int = 256
    f0_frame_length: int = 1024
    f0_hop_length: int = 1024
    n_mfcc: int = 20
    n_mels: int = 64
    silence_rms_db: float = -50.0
    f0_min_hz: float = 80.0
    f0_max_hz: float = 2000.0
    f0_peak_ratio_min: float = 0.2
    bands: tuple[tuple[str, float, float], ...] = (
        ("band_energy_0_500", 0.0, 500.0),
        ("band_energy_500_1000", 500.0, 1000.0),
        ("band_energy_1000_2000", 1000.0, 2000.0),
        ("band_energy_2000_4000", 2000.0, 4000.0),
        ("band_energy_4000_8000", 4000.0, 8000.0),
    )
    contrast_edges: tuple[int, ...] | None = (0, 250, 500, 1000, 2000, 4000, 8000)
    # (输出名, 百分位, 统计元组)——v2 只有 mean；Tiny 规格的 rolloff_85_mean/std 是新增特征，由此显式声明
    rolloffs: tuple[tuple[str, float, tuple[str, ...]], ...] = (
        ("spectral_rolloff_85_mean", 0.85, ("mean",)),
        ("spectral_rolloff_95_mean", 0.95, ("mean",)),
    )
    mfcc_stats: tuple[str, ...] = ("mean", "std")
    delta_mfcc_stats: tuple[str, ...] = ("mean", "std")
    include_logmel: bool = True
    include_f0: bool = True
    include_duration: bool = False  # v2 时代 duration 走 META 列；训练输入由训练脚本自行并入


V2_16K = FeatureConfig()

# 预设注册表：CLI 与训练共用的唯一入口（build_table / train_hierarchical 均从这里取）
PRESETS: dict[str, FeatureConfig] = {
    "v2_16k": V2_16K,
    "v3_8k": None,  # 由 preset_v3_8k() 填充（见下方函数定义后）
    "tiny_8k_2s": None,
}


def preset_v3_8k() -> FeatureConfig:
    """8kHz 统一管线：删 band_energy_4000_8000、contrast 边缘适配 8k、duration 不再入模。"""
    return FeatureConfig(
        name="v3_8k",
        target_sample_rate=8000,
        bands=tuple(b for b in V2_16K.bands if b[0] != "band_energy_4000_8000"),
        contrast_edges=(0, 250, 500, 1000, 2000, 4000),
    )


def preset_tiny_8k_2s() -> FeatureConfig:
    """Tiny-LR 候选前端（8k/2s/60 维）：无 F0/contrast/logmel；rolloff_85 带 std（新特征）。"""
    return FeatureConfig(
        name="tiny_8k_2s",
        target_sample_rate=8000,
        window_seconds=2.0,
        n_mfcc=13,
        bands=tuple(b for b in V2_16K.bands if b[0] != "band_energy_4000_8000"),
        contrast_edges=None,
        rolloffs=(("spectral_rolloff_85_mean", 0.85, ("mean", "std")),),
        mfcc_stats=("mean", "std"),
        delta_mfcc_stats=("std",),
        include_logmel=False,
        include_f0=False,
    )


PRESETS["v3_8k"] = preset_v3_8k()
PRESETS["tiny_8k_2s"] = preset_tiny_8k_2s()


def preset_v3_8k_2s() -> FeatureConfig:
    """B1w 隔离臂：v3 全特征（238 维）但 2s 窗——单独隔离"窗长"变量的代价。"""
    base = preset_v3_8k()
    return FeatureConfig(
        name="v3_8k_2s",
        target_sample_rate=base.target_sample_rate,
        window_seconds=2.0,
        frame_length=base.frame_length,
        hop_length=base.hop_length,
        f0_frame_length=base.f0_frame_length,
        f0_hop_length=base.f0_hop_length,
        n_mfcc=base.n_mfcc,
        n_mels=base.n_mels,
        silence_rms_db=base.silence_rms_db,
        f0_min_hz=base.f0_min_hz,
        f0_max_hz=base.f0_max_hz,
        bands=base.bands,
        contrast_edges=base.contrast_edges,
        rolloffs=base.rolloffs,
        mfcc_stats=base.mfcc_stats,
        delta_mfcc_stats=base.delta_mfcc_stats,
        include_logmel=True,
        include_f0=True,
    )


PRESETS["v3_8k_2s"] = preset_v3_8k_2s()


def preset_v3_8k_1s() -> FeatureConfig:
    """狗版对照臂：v3 全特征（238 维）但 1s 窗——Act_Env 片段中位时长 0.96s。"""
    base = preset_v3_8k()
    return FeatureConfig(
        name="v3_8k_1s",
        target_sample_rate=base.target_sample_rate,
        window_seconds=1.0,
        frame_length=base.frame_length,
        hop_length=base.hop_length,
        f0_frame_length=base.f0_frame_length,
        f0_hop_length=base.f0_hop_length,
        n_mfcc=base.n_mfcc,
        n_mels=base.n_mels,
        silence_rms_db=base.silence_rms_db,
        f0_min_hz=base.f0_min_hz,
        f0_max_hz=base.f0_max_hz,
        bands=base.bands,
        contrast_edges=base.contrast_edges,
        rolloffs=base.rolloffs,
        mfcc_stats=base.mfcc_stats,
        delta_mfcc_stats=base.delta_mfcc_stats,
        include_logmel=True,
        include_f0=True,
    )


PRESETS["v3_8k_1s"] = preset_v3_8k_1s()


def preset_from_name(name: str) -> FeatureConfig:
    """按 bundle manifest 的 frontend_preset 字符串取 FeatureConfig。

    未知名字抛 ValueError（fail-fast，禁止静默回退到 V2_16K——那正是 Web preset bug 的根因）。
    """
    if name not in PRESETS:
        raise ValueError(f"unknown frontend_preset {name!r}; known={sorted(PRESETS)}")
    return PRESETS[name]


# ---------------------------------------------------------------- 音频装载


def resample_linear(y: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr == target_sr:
        return y
    duration = len(y) / float(orig_sr)
    target_len = max(1, int(round(duration * target_sr)))
    old_x = np.linspace(0.0, duration, num=len(y), endpoint=False)
    new_x = np.linspace(0.0, duration, num=target_len, endpoint=False)
    return np.interp(new_x, old_x, y).astype(np.float32)


def _decode_with_ffmpeg(audio_path: Path, target_sr: int) -> tuple[np.ndarray, int]:
    """soundfile 读不了的非 WAV 容器（m4a/webm/aac…）走 ffmpeg 解码。

    契约：输出 float32 单声道 target_sr。此路径替代旧实现的 librosa 懒加载 fallback。
    """
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError(
            "ffmpeg executable not found in PATH; install ffmpeg to decode non-WAV audio"
        )
    cmd = [ffmpeg, "-v", "error", "-i", str(audio_path), "-f", "f32le", "-ac", "1", "-ar", str(target_sr), "pipe:1"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    y = np.frombuffer(raw, dtype=np.float32).copy()
    if y.size == 0:
        raise ValueError("empty_audio")
    return y, target_sr


def load_audio_mono(audio_path: Path, config: FeatureConfig = V2_16K) -> tuple[np.ndarray, int]:
    """读文件→单声道→重采样到 config.target_sample_rate。WAV 用 soundfile，其余 ffmpeg。"""
    try:
        samples, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        if samples.size == 0:
            raise ValueError("empty_audio")
        y = samples.mean(axis=1) if samples.shape[1] > 1 else samples[:, 0]
        sr = int(sr)
    except Exception:
        y, sr = _decode_with_ffmpeg(audio_path, config.target_sample_rate)
    if sr != config.target_sample_rate:
        y = resample_linear(y, orig_sr=sr, target_sr=config.target_sample_rate)
        sr = config.target_sample_rate
    return np.asarray(y, dtype=np.float32), int(sr)


def to_window(y: np.ndarray, window_seconds: float, sr: int) -> np.ndarray:
    """推理/训练共用的定窗：短补零、长居中裁剪。"""
    window_samples = int(sr * window_seconds)
    if y.size == 0:
        raise ValueError("empty_audio")
    if y.size < window_samples:
        return np.pad(y, (0, window_samples - y.size), mode="constant").astype(np.float32)
    if y.size > window_samples:
        start = int((y.size - window_samples) // 2)
        return y[start : start + window_samples].astype(np.float32)
    return y.astype(np.float32)


# ---------------------------------------------------------------- DSP 基元（与原实现逐行等价）


def frame_audio(y: np.ndarray, frame_length: int, hop_length: int, center: bool = True) -> np.ndarray:
    if center:
        pad = frame_length // 2
        y = np.pad(y, (pad, pad), mode="constant")
    if len(y) < frame_length:
        y = np.pad(y, (0, frame_length - len(y)), mode="constant")
    frame_count = 1 + int(math.ceil((len(y) - frame_length) / hop_length))
    target_len = (frame_count - 1) * hop_length + frame_length
    if len(y) < target_len:
        y = np.pad(y, (0, target_len - len(y)), mode="constant")
    shape = (frame_count, frame_length)
    strides = (y.strides[0] * hop_length, y.strides[0])
    return np.lib.stride_tricks.as_strided(y, shape=shape, strides=strides)


def mean_std(values: np.ndarray) -> tuple[float, float]:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan"), float("nan")
    return float(np.mean(values)), float(np.std(values))


def finite_stats(values: np.ndarray) -> tuple[float, float, float, float, float, float]:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return (float("nan"),) * 6
    return (
        float(np.mean(values)),
        float(np.median(values)),
        float(np.std(values)),
        float(np.min(values)),
        float(np.max(values)),
        float(np.max(values) - np.min(values)),
    )


def hz_to_mel(hz: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def mel_to_hz(mel: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def mel_filterbank(sr: int, n_fft: int, n_mels: int, fmin: float = 0.0, fmax: float | None = None) -> np.ndarray:
    if fmax is None:
        fmax = sr / 2.0
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    mel_points = np.linspace(hz_to_mel(np.array([fmin]))[0], hz_to_mel(np.array([fmax]))[0], n_mels + 2)
    hz_points = mel_to_hz(mel_points)
    filters = np.zeros((n_mels, len(freqs)), dtype=np.float64)
    for mel_index in range(n_mels):
        left, center, right = hz_points[mel_index : mel_index + 3]
        left_slope = (freqs - left) / max(center - left, EPS)
        right_slope = (right - freqs) / max(right - center, EPS)
        filters[mel_index] = np.maximum(0.0, np.minimum(left_slope, right_slope))
        norm = np.sum(filters[mel_index])
        if norm > 0:
            filters[mel_index] /= norm
    return filters


def dct_type_ii_basis(n_coeffs: int, n_filters: int) -> np.ndarray:
    basis = np.zeros((n_coeffs, n_filters), dtype=np.float64)
    scale0 = math.sqrt(1.0 / n_filters)
    scale = math.sqrt(2.0 / n_filters)
    n = np.arange(n_filters)
    for k in range(n_coeffs):
        basis[k, :] = np.cos(math.pi / n_filters * (n + 0.5) * k)
        basis[k, :] *= scale0 if k == 0 else scale
    return basis


def rolloff_frequency(power: np.ndarray, freqs: np.ndarray, percent: float) -> np.ndarray:
    cumulative = np.cumsum(power, axis=1)
    thresholds = cumulative[:, -1:] * percent
    indices = np.argmax(cumulative >= thresholds, axis=1)
    return freqs[indices]


def spectral_contrast(power: np.ndarray, freqs: np.ndarray, band_edges: tuple[int, ...], nyquist: float) -> np.ndarray:
    contrasts = []
    db_power = 10.0 * np.log10(np.maximum(power, EPS))
    for low, high in zip(band_edges[:-1], band_edges[1:]):
        if high >= nyquist:
            mask = (freqs >= low) & (freqs <= high)
        else:
            mask = (freqs >= low) & (freqs < high)
        if not np.any(mask):
            continue
        band = db_power[:, mask]
        contrasts.append(np.percentile(band, 90, axis=1) - np.percentile(band, 10, axis=1))
    if not contrasts:
        return np.array([], dtype=np.float64)
    return np.vstack(contrasts).T.ravel()


def band_energy_ratios(
    power: np.ndarray, freqs: np.ndarray, bands: tuple[tuple[str, float, float], ...], nyquist: float
) -> dict[str, float]:
    total = float(np.sum(power))
    ratios = {}
    for name, low, high in bands:
        if high >= nyquist:
            mask = (freqs >= low) & (freqs <= high)
        else:
            mask = (freqs >= low) & (freqs < high)
        ratios[name] = float(np.sum(power[:, mask])) / max(total, EPS) if np.any(mask) else 0.0
    return ratios


def zero_crossing_rate(frames: np.ndarray) -> np.ndarray:
    signs = np.signbit(frames)
    return np.mean(signs[:, 1:] != signs[:, :-1], axis=1)


def estimate_f0_autocorr(
    y: np.ndarray,
    sr: int,
    voiced_rms_threshold_db: float,
    frame_length: int = 1024,
    hop_length: int = 1024,
    f0_min_hz: float = 80.0,
    f0_max_hz: float = 2000.0,
    peak_ratio_min: float = 0.2,
) -> tuple[np.ndarray, float]:
    frames = frame_audio(y, frame_length, hop_length, center=True).astype(np.float64, copy=False)
    window = np.hanning(frame_length)
    min_lag = max(1, int(sr / f0_max_hz))
    max_lag = min(frame_length - 1, int(sr / f0_min_hz))
    f0_values = []
    voiced_count = 0
    for frame in frames:
        frame = (frame - np.mean(frame)) * window
        rms = math.sqrt(float(np.mean(frame * frame)))
        rms_db = 20.0 * math.log10(max(rms, EPS))
        if rms_db <= voiced_rms_threshold_db:
            continue
        corr = np.correlate(frame, frame, mode="full")[frame_length - 1 :]
        if corr[0] <= EPS:
            continue
        search = corr[min_lag : max_lag + 1]
        if search.size == 0:
            continue
        best_offset = int(np.argmax(search))
        best_lag = min_lag + best_offset
        peak_ratio = float(search[best_offset] / corr[0])
        if peak_ratio < peak_ratio_min:
            continue
        voiced_count += 1
        f0_values.append(float(sr / best_lag))
    voiced_fraction = voiced_count / max(len(frames), 1)
    return np.asarray(f0_values, dtype=np.float64), float(voiced_fraction)


# ---------------------------------------------------------------- 特征名契约


def mfcc_feature_names(config: FeatureConfig) -> list[str]:
    names = [f"mfcc_{index}_{stat}" for stat in config.mfcc_stats for index in range(1, config.n_mfcc + 1)]
    if config.delta_mfcc_stats:
        names += [f"delta_mfcc_{index}_{stat}" for stat in config.delta_mfcc_stats for index in range(1, config.n_mfcc + 1)]
    return names


def logmel_feature_names(config: FeatureConfig) -> list[str]:
    if not config.include_logmel:
        return []
    return [f"logmel_{index}_{stat}" for stat in ["mean", "std"] for index in range(1, config.n_mels + 1)]


def feature_columns_for(config: FeatureConfig, include_duration: bool | None = None) -> list[str]:
    """按 config 生成特征列名（顺序即契约）。include_duration 默认取 config.include_duration。"""
    use_duration = config.include_duration if include_duration is None else include_duration
    columns: list[str] = []
    if use_duration:
        columns.append("duration_sec")
    columns += [
        "rms_mean",
        "rms_std",
        "rms_max",
        "rms_db_mean",
        "peak_amplitude",
        "crest_factor",
        "zero_crossing_rate_mean",
        "zero_crossing_rate_std",
        "silence_ratio",
        "spectral_centroid_mean",
        "spectral_centroid_std",
        "spectral_bandwidth_mean",
        "spectral_bandwidth_std",
    ]
    columns += []
    for rolloff_name, _percent, rolloff_stats in config.rolloffs:
        for stat in rolloff_stats:
            columns.append(rolloff_name if stat == "mean" else rolloff_name.replace("_mean", "_std"))
    if config.contrast_edges:
        columns += ["spectral_flatness_mean", "spectral_flatness_std", "spectral_contrast_mean", "spectral_contrast_std"]
    else:
        columns += ["spectral_flatness_mean", "spectral_flatness_std"]
    columns += [name for name, _, _ in config.bands]
    columns += mfcc_feature_names(config)
    columns += logmel_feature_names(config)
    if config.include_f0:
        columns += ["f0_mean", "f0_median", "f0_std", "f0_min", "f0_max", "f0_range", "voiced_fraction"]
    return columns


# ---------------------------------------------------------------- 主提取


def extract_features_from_samples(y: np.ndarray, sr: int, config: FeatureConfig = V2_16K) -> dict[str, float]:
    """样本级特征提取。训练/推理/板端对齐共用此函数；特征定义变更只允许改 FeatureConfig。"""
    if y.size == 0:
        raise ValueError("empty_audio")
    nyquist = sr / 2.0
    duration = float(len(y) / sr)
    frames = frame_audio(y, config.frame_length, config.hop_length, center=True).astype(np.float64, copy=False)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    rms_db = 20.0 * np.log10(np.maximum(rms, EPS))
    zcr = zero_crossing_rate(frames)
    peak = float(np.max(np.abs(y)))
    rms_mean, rms_std = mean_std(rms)

    window = np.hanning(config.frame_length)
    spectrum = np.fft.rfft(frames * window, axis=1)
    magnitude = np.abs(spectrum)
    power = magnitude * magnitude
    freqs = np.fft.rfftfreq(config.frame_length, d=1.0 / sr)
    mag_sum = np.sum(magnitude, axis=1) + EPS

    centroid = np.sum(magnitude * freqs[None, :], axis=1) / mag_sum
    bandwidth = np.sqrt(np.sum(magnitude * (freqs[None, :] - centroid[:, None]) ** 2, axis=1) / mag_sum)
    flatness = np.exp(np.mean(np.log(np.maximum(power, EPS)), axis=1)) / np.maximum(np.mean(power, axis=1), EPS)

    features: dict[str, float] = {}
    if config.include_duration:
        features["duration_sec"] = duration
    features.update(
        {
            "rms_mean": rms_mean,
            "rms_std": rms_std,
            "rms_max": float(np.max(rms)) if rms.size else float("nan"),
            "rms_db_mean": float(np.mean(rms_db)) if rms_db.size else float("nan"),
            "peak_amplitude": peak,
            "crest_factor": peak / max(rms_mean, EPS),
            "zero_crossing_rate_mean": mean_std(zcr)[0],
            "zero_crossing_rate_std": mean_std(zcr)[1],
            "silence_ratio": float(np.mean(rms_db < config.silence_rms_db)) if rms_db.size else float("nan"),
            "spectral_centroid_mean": mean_std(centroid)[0],
            "spectral_centroid_std": mean_std(centroid)[1],
            "spectral_bandwidth_mean": mean_std(bandwidth)[0],
            "spectral_bandwidth_std": mean_std(bandwidth)[1],
        }
    )

    for name, percent, stats in config.rolloffs:
        values = rolloff_frequency(power, freqs, percent)
        stats_values = {"mean": mean_std(values)[0], "std": mean_std(values)[1]}
        for stat in stats:
            features[name if stat == "mean" else name.replace("_mean", "_std")] = stats_values[stat]

    features["spectral_flatness_mean"] = mean_std(flatness)[0]
    features["spectral_flatness_std"] = mean_std(flatness)[1]
    if config.contrast_edges:
        contrast_values = spectral_contrast(power, freqs, config.contrast_edges, nyquist)
        features["spectral_contrast_mean"] = mean_std(contrast_values)[0]
        features["spectral_contrast_std"] = mean_std(contrast_values)[1]

    features.update(band_energy_ratios(power, freqs, config.bands, nyquist))

    mfcc = None
    delta = None
    logmel = None
    if config.include_logmel or config.mfcc_stats or config.delta_mfcc_stats:
        mel_power = mel_filterbank(sr, config.frame_length, config.n_mels) @ power.T
        logmel = 10.0 * np.log10(np.maximum(mel_power, EPS))
        logmel = logmel - float(np.max(logmel))
        mfcc = dct_type_ii_basis(config.n_mfcc, config.n_mels) @ logmel
        delta = np.gradient(mfcc, axis=1) if mfcc.shape[1] > 1 else np.zeros_like(mfcc)

    for stat in config.mfcc_stats:
        for index in range(config.n_mfcc):
            features[f"mfcc_{index + 1}_{stat}"] = float(np.mean(mfcc[index, :]) if stat == "mean" else np.std(mfcc[index, :]))
    for stat in config.delta_mfcc_stats:
        for index in range(config.n_mfcc):
            features[f"delta_mfcc_{index + 1}_{stat}"] = float(
                np.mean(delta[index, :]) if stat == "mean" else np.std(delta[index, :])
            )

    if config.include_logmel:
        for index in range(config.n_mels):
            features[f"logmel_{index + 1}_mean"] = float(np.mean(logmel[index, :]))
            features[f"logmel_{index + 1}_std"] = float(np.std(logmel[index, :]))

    if config.include_f0:
        f0_values, voiced_fraction = estimate_f0_autocorr(
            y,
            sr,
            config.silence_rms_db,
            frame_length=config.f0_frame_length,
            hop_length=config.f0_hop_length,
            f0_min_hz=config.f0_min_hz,
            f0_max_hz=config.f0_max_hz,
            peak_ratio_min=config.f0_peak_ratio_min,
        )
        f0_mean, f0_median, f0_std, f0_min, f0_max, f0_range = finite_stats(f0_values)
        features.update(
            {
                "f0_mean": f0_mean,
                "f0_median": f0_median,
                "f0_std": f0_std,
                "f0_min": f0_min,
                "f0_max": f0_max,
                "f0_range": f0_range,
                "voiced_fraction": voiced_fraction,
            }
        )

    return features


def extract_features(audio_path: Path, config: FeatureConfig = V2_16K) -> tuple[dict[str, float], str, str]:
    """文件级提取（含全长度 duration_sec，供特征表 META 使用）。返回 (features, read_status, read_error)。"""
    try:
        y, sr = load_audio_mono(audio_path, config)
        features = extract_features_from_samples(y, sr, config)
        features["duration_sec"] = float(len(y) / sr)
        return features, "ok", ""
    except Exception as exc:
        return {}, "failed", f"{type(exc).__name__}: {exc}"


def build_feature_table(
    manifest: pd.DataFrame,
    config: FeatureConfig = V2_16K,
    meta_columns: tuple[str, ...] = ("audio_path", "label", "source_id", "split", "sample_type", "duration_sec"),
    path_resolver=None,
    log_every: int = 50,
) -> pd.DataFrame:
    """清单→特征表。path_resolver(audio_path_str)->Path 用于 v3 相对路径清单。"""
    columns = feature_columns_for(config, include_duration=False)
    rows = []
    total = len(manifest)
    for index, row in manifest.iterrows():
        output = {column: row[column] for column in meta_columns if column in row}
        audio_path = Path(str(row["audio_path"]))
        if path_resolver is not None:
            audio_path = path_resolver(str(row["audio_path"]))
        features, read_status, read_error = extract_features(audio_path, config)
        duration = features.pop("duration_sec", None)
        if read_status == "ok" and duration is not None:
            output["duration_sec"] = duration
        output["read_status"] = read_status
        output["read_error"] = read_error
        missing = {name: float("nan") for name in columns if name not in features}
        output.update(features)
        output.update(missing)
        rows.append(output)
        if (index + 1) % log_every == 0 or index + 1 == total:
            print(f"processed_features={index + 1}/{total}", flush=True)
    return pd.DataFrame(rows, columns=list(meta_columns) + ["read_status", "read_error"] + columns)
