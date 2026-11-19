r"""S9：板端前端 C 查找表生成器（B01–B08 的对齐基底）。

用法：.venv/Scripts/python.exe tools/generate_frontend_tables.py

从 petlink.features.extractor 的**同一实现**生成 edge/c/frontend_tables.h：
hann_1024 / mel_64 稀疏表（513 bins）/ dct_20x64 / 8k 常量。
Python 与板端共享同一张表 = 消除"两张表各自算"的漂移风险（M 系列教训）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from petlink.features.extractor import dct_type_ii_basis, mel_filterbank  # noqa: E402

OUT = ROOT / "edge" / "c" / "frontend_tables.h"

SR = 8000
FRAME_LENGTH = 1024
HOP_LENGTH = 256
N_MELS = 64
N_MFCC = 20


def fmt(value: float) -> str:
    return f"{value:.9e}f"


def main() -> int:
    hann = np.hanning(FRAME_LENGTH)
    mel = mel_filterbank(SR, FRAME_LENGTH, N_MELS)  # fmax=None → sr/2 = 4000Hz
    dct = dct_type_ii_basis(N_MFCC, N_MELS)

    lines = [
        "/* 自动生成：tools/generate_frontend_tables.py（勿手改）",
        " * 来源实现：petlink.features.extractor（与训练/PC 推理同源）",
        " * 采样率 8kHz、窗长 4s（32000 样本）——8k/4s 契约见 docs/ESP32_DEPLOYMENT_V2.md",
        " */",
        "#ifndef PETLINK_FRONTEND_TABLES_H",
        "#define PETLINK_FRONTEND_TABLES_H",
        "",
        f"#define PL_SAMPLE_RATE {SR}",
        f"#define PL_WINDOW_SECONDS 4.0f",
        f"#define PL_WINDOW_SAMPLES 32000",
        f"#define PL_FRAME_LENGTH {FRAME_LENGTH}",
        f"#define PL_HOP_LENGTH {HOP_LENGTH}",
        f"#define PL_FRAME_COUNT (1 + (PL_WINDOW_SAMPLES + PL_FRAME_LENGTH - PL_FRAME_LENGTH + PL_HOP_LENGTH - 1) / PL_HOP_LENGTH)  /* =126 */",
        f"#define PL_F0_FRAME_LENGTH {FRAME_LENGTH}",
        f"#define PL_F0_HOP_LENGTH {FRAME_LENGTH}",
        "/* F0 帧数 = 1 + ceil(32000/1024) = 33（center padding 后） */",
        "#define PL_F0_FRAME_COUNT 33",
        "/* F0 lag 范围（8k）：min=int(8000/2000)=4, max=int(8000/80)=100 → 80–2000Hz */",
        "#define PL_F0_MIN_LAG 4",
        "#define PL_F0_MAX_LAG 100",
        "#define PL_N_MELS 64",
        "#define PL_N_MFCC 20",
        "#define PL_FFT_BINS 513",
        "#define PL_EPS 1e-12f",
        "/* 谱对比度带边缘（8k 适配，末带闭合）；频段能量 4 段（band_energy_4000_8000 已删） */",
        "#define PL_CONTRAST_EDGES {0, 250, 500, 1000, 2000, 4000}",
        "#define PL_CONTRAST_EDGE_COUNT 6",
        "#define PL_BAND_EDGES {0, 500, 1000, 2000, 4000}",
        "#define PL_BAND_COUNT 4",
        "",
        f"static const float pl_hann[{FRAME_LENGTH}] = {{",
        "  " + ", ".join(fmt(v) for v in hann[:64]) + ",",
    ]
    for start in range(64, FRAME_LENGTH, 64):
        lines.append("  " + ", ".join(fmt(v) for v in hann[start : start + 64]) + ",")
    lines += [
        "};",
        "",
        "/* Mel 稀疏表：每滤波器 {first_bin, count, weights[]}；面积归一化已应用 */",
        f"#define PL_MEL_FILTERS {N_MELS}",
        f"static const int pl_mel_first_bin[{N_MELS}] = {{",
    ]
    rows = []
    for mel_index in range(N_MELS):
        nonzero = np.nonzero(mel[mel_index])[0]
        rows.append((mel_index, nonzero))
        lines.append(f"  {int(nonzero[0])},")
    lines.append("};")
    lines.append(f"static const int pl_mel_count[{N_MELS}] = {{")
    for _, nonzero in rows:
        lines.append(f"  {len(nonzero)},")
    lines.append("};")
    lines.append("static const float pl_mel_weights[] = {")
    for mel_index, nonzero in rows:
        lines.append(f"  /* mel {mel_index} */ " + ", ".join(fmt(v) for v in mel[mel_index][nonzero]) + ",")
    lines.append("};")
    lines += [
        "",
        f"static const float pl_dct[{N_MFCC} * {N_MELS}] = {{",
    ]
    flat = dct.ravel()
    for start in range(0, len(flat), 64):
        lines.append("  " + ", ".join(fmt(v) for v in flat[start : start + 64]) + ",")
    lines += ["};", "", "#endif /* PETLINK_FRONTEND_TABLES_H */"]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    total_weights = sum(len(nonzero) for _, nonzero in rows)
    print(f"wrote {OUT}")
    print(f"hann {FRAME_LENGTH} floats; mel {N_MELS} filters / {total_weights} nonzero weights; dct {N_MFCC}x{N_MELS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
