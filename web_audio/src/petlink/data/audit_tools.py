r"""回填数据集审计与目检工具（通用，所有外部数据集共用）。

- ffprobe 音频元数据；SHA256（文件级）与 PCM16k（内容级）双哈希
- 频谱图网格（mel，用与训练一致的 mel_filterbank），CatMeows 类 8k 源用 fmax 上限显示
- 查重：对 metadata/hash_baseline_old_project.csv（旧项目基线）+ 数据集内部
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from petlink.features.extractor import mel_filterbank, resample_linear  # noqa: E402

FFPROBE = shutil.which("ffprobe") or "ffprobe"
EPS = 1e-12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe_info(path: Path) -> dict:
    cmd = [
        FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path),
    ]
    try:
        payload = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
        stream = next(s for s in payload.get("streams", []) if s.get("codec_type") == "audio")
        return {
            "sample_rate": int(stream.get("sample_rate", 0)),
            "channels": int(stream.get("channels", 0)),
            "codec": stream.get("codec_name", ""),
            "duration_sec": round(float(payload.get("format", {}).get("duration", 0.0)), 3),
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def pcm_16k_sha(path: Path, target_sr: int = 16000) -> str:
    """内容级哈希：解码→单声道→16k 重采样（与训练预处理同口径）→float32 字节哈希。"""
    import soundfile as sf

    samples, sr = sf.read(path, dtype="float32", always_2d=True)
    y = samples.mean(axis=1) if samples.shape[1] > 1 else samples[:, 0]
    if sr != target_sr:
        y = resample_linear(y, orig_sr=int(sr), target_sr=target_sr)
    return hashlib.sha256(np.asarray(y, dtype=np.float32).tobytes()).hexdigest()


def load_pcm(path: Path, target_sr: int | None = None) -> tuple[np.ndarray, int]:
    import soundfile as sf

    samples, sr = sf.read(path, dtype="float32", always_2d=True)
    y = samples.mean(axis=1) if samples.shape[1] > 1 else samples[:, 0]
    if target_sr is not None and sr != target_sr:
        y = resample_linear(y, orig_sr=int(sr), target_sr=target_sr)
        sr = target_sr
    return np.asarray(y, dtype=np.float32), int(sr)


def render_spectrogram_grid(
    paths: list[Path],
    out_png: Path,
    fmax_hz: float,
    title: str = "",
    cols: int = 6,
    n_mels: int = 48,
    cell_seconds: float | None = None,
) -> None:
    """每格一个 mel 频谱（含波形包络），fmax_hz 限制显示带宽（8k 源用 4000）。"""
    rows_count = int(np.ceil(len(paths) / cols))
    fig, axes = plt.subplots(rows_count, cols, figsize=(cols * 2.1, rows_count * 1.8), squeeze=False)
    for index, path in enumerate(paths):
        ax = axes[index // cols][index % cols]
        try:
            y, sr = load_pcm(path)
            if cell_seconds is not None and len(y) > int(sr * cell_seconds):
                y = y[: int(sr * cell_seconds)]
            frame_length = 512 if sr <= 8000 else 1024
            hop = 128 if sr <= 8000 else 256
            if len(y) < frame_length:
                y = np.pad(y, (0, frame_length - len(y)))
            frames = np.lib.stride_tricks.sliding_window_view(y, frame_length)[::hop]
            window = np.hanning(frame_length)
            power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
            freqs = np.fft.rfftfreq(frame_length, d=1.0 / sr)
            valid = freqs <= fmax_hz
            mel = mel_filterbank(sr, frame_length, n_mels, fmax=fmax_hz) @ power.T
            mel_db = 10.0 * np.log10(np.maximum(mel, EPS))
            mel_db -= float(np.max(mel_db))
            ax.imshow(mel_db, aspect="auto", origin="lower", cmap="magma", extent=[0, len(y) / sr, 0, n_mels])
            ax.set_title(f"{path.name[:28]}", fontsize=5)
        except Exception as exc:
            ax.text(0.5, 0.5, f"ERR {type(exc).__name__}", fontsize=6)
            ax.set_title(f"{path.name[:28]}", fontsize=5)
        ax.set_xticks([])
        ax.set_yticks([])
    for index in range(len(paths), rows_count * cols):
        axes[index // cols][index % cols].axis("off")
    fig.suptitle(title, fontsize=9)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
