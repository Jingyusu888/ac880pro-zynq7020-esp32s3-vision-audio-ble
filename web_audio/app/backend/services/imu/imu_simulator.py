from __future__ import annotations

import math
import random
import time
from typing import Callable


SIMULATION_SCENARIOS = [
    "still",
    "body_active",
    "body_intense",
    "tail_sway",
    "tail_flick_or_agitation",
    "unknown",
    "mixed",
]

SCENARIO_NOTES = {
    "still": "still means low activity only; it does not imply relaxed, happy, ill, or painful.",
    "body_active": "body_active is an engineering assumption for walking, turning, or light activity.",
    "body_intense": "body_intense is an engineering assumption for running, jumping, or fast movement.",
    "tail_sway": "tail_sway is periodic local motion only; it does not directly mean happy or relaxed.",
    "tail_flick_or_agitation": (
        "tail_flick_or_agitation is rapid motion evidence only; alert or discomfort requires audio/context fusion."
    ),
    "unknown": "unknown is an intentionally ambiguous engineering-assumption signal for rule-boundary testing.",
    "mixed": "mixed combines several simulated states to exercise future windowing and unknown handling.",
}


def generate_imu_samples(
    scenario: str,
    sample_rate_hz: int = 50,
    duration_s: float = 10.0,
    sensor_position: str = "simulated_tail",
    noise_level: float = 0.03,
    intensity: float = 1.0,
    random_seed: int | None = None,
) -> list[dict]:
    scenario = str(scenario or "").strip()
    if scenario == "still":
        return generate_still_samples(sample_rate_hz, duration_s, sensor_position, noise_level, intensity, random_seed)
    if scenario == "body_active":
        return generate_body_active_samples(sample_rate_hz, duration_s, sensor_position, noise_level, intensity, random_seed)
    if scenario == "body_intense":
        return generate_body_intense_samples(sample_rate_hz, duration_s, sensor_position, noise_level, intensity, random_seed)
    if scenario == "tail_sway":
        return generate_tail_sway_samples(sample_rate_hz, duration_s, sensor_position, noise_level, intensity, random_seed)
    if scenario == "tail_flick_or_agitation":
        return generate_tail_flick_or_agitation_samples(
            sample_rate_hz, duration_s, sensor_position, noise_level, intensity, random_seed
        )
    if scenario == "unknown":
        return generate_unknown_samples(sample_rate_hz, duration_s, sensor_position, noise_level, intensity, random_seed)
    if scenario == "mixed":
        return generate_mixed_samples(sample_rate_hz, duration_s, sensor_position, noise_level, intensity, random_seed)
    raise ValueError(f"Unsupported IMU simulation scenario: {scenario}")


def get_simulation_note(scenario: str) -> str:
    return SCENARIO_NOTES.get(str(scenario or ""), "engineering-assumption IMU simulation; not real hardware data.")


def generate_still_samples(
    sample_rate_hz: int = 50,
    duration_s: float = 10.0,
    sensor_position: str = "simulated_tail",
    noise_level: float = 0.03,
    intensity: float = 1.0,
    random_seed: int | None = None,
    *,
    start_timestamp_ms: int | None = None,
    seq_start: int = 0,
    sample_count: int | None = None,
) -> list[dict]:
    rng = random.Random(random_seed)
    context = _make_context(rng, sample_rate_hz, duration_s, start_timestamp_ms, seq_start, sample_count)
    noise = max(0.001, noise_level * 0.35)
    gyro_noise = max(0.02, noise_level * 3.0)
    samples = []
    for index in range(context["sample_count"]):
        samples.append(
            _sample(
                context,
                index,
                ax=rng.gauss(0.0, noise),
                ay=rng.gauss(0.0, noise),
                az=1.0 + rng.gauss(0.0, noise),
                gx=rng.gauss(0.0, gyro_noise),
                gy=rng.gauss(0.0, gyro_noise),
                gz=rng.gauss(0.0, gyro_noise),
                tail_angle_deg=None,
            )
        )
    return samples


def generate_body_active_samples(
    sample_rate_hz: int = 50,
    duration_s: float = 10.0,
    sensor_position: str = "simulated_tail",
    noise_level: float = 0.03,
    intensity: float = 1.0,
    random_seed: int | None = None,
    *,
    start_timestamp_ms: int | None = None,
    seq_start: int = 0,
    sample_count: int | None = None,
) -> list[dict]:
    rng = random.Random(random_seed)
    context = _make_context(rng, sample_rate_hz, duration_s, start_timestamp_ms, seq_start, sample_count)
    freq = rng.uniform(0.8, 2.0)
    phase = rng.uniform(0.0, math.tau)
    acc_amp = 0.10 * _safe_intensity(intensity)
    gyro_amp = 22.0 * _safe_intensity(intensity)
    samples = []
    for index in range(context["sample_count"]):
        t = index / sample_rate_hz
        wave = math.sin(math.tau * freq * t + phase)
        wave2 = math.sin(math.tau * (freq * 0.55) * t + phase / 2.0)
        samples.append(
            _sample(
                context,
                index,
                ax=acc_amp * wave + rng.gauss(0.0, noise_level),
                ay=acc_amp * 0.65 * wave2 + rng.gauss(0.0, noise_level),
                az=1.0 + acc_amp * 0.45 * math.sin(math.tau * freq * t) + rng.gauss(0.0, noise_level),
                gx=gyro_amp * wave2 + rng.gauss(0.0, noise_level * 12.0),
                gy=gyro_amp * 0.75 * wave + rng.gauss(0.0, noise_level * 12.0),
                gz=gyro_amp * 0.40 * math.sin(math.tau * freq * t + phase * 0.2)
                + rng.gauss(0.0, noise_level * 12.0),
                tail_angle_deg=None,
            )
        )
    return samples


def generate_body_intense_samples(
    sample_rate_hz: int = 50,
    duration_s: float = 10.0,
    sensor_position: str = "simulated_tail",
    noise_level: float = 0.03,
    intensity: float = 1.0,
    random_seed: int | None = None,
    *,
    start_timestamp_ms: int | None = None,
    seq_start: int = 0,
    sample_count: int | None = None,
) -> list[dict]:
    rng = random.Random(random_seed)
    context = _make_context(rng, sample_rate_hz, duration_s, start_timestamp_ms, seq_start, sample_count)
    base = generate_body_active_samples(
        sample_rate_hz,
        duration_s,
        sensor_position,
        noise_level * 1.4,
        intensity * 1.9,
        random_seed,
        start_timestamp_ms=start_timestamp_ms,
        seq_start=seq_start,
        sample_count=context["sample_count"],
    )
    burst_count = max(2, int(math.ceil(duration_s * 1.4)))
    burst_starts = [rng.randrange(0, max(1, context["sample_count"])) for _ in range(burst_count)]
    for start in burst_starts:
        width = rng.randint(2, max(3, int(sample_rate_hz * 0.16)))
        sign = rng.choice([-1.0, 1.0])
        for index in range(start, min(context["sample_count"], start + width)):
            decay = 1.0 - ((index - start) / max(1, width))
            acc_pulse = sign * rng.uniform(0.18, 0.50) * _safe_intensity(intensity) * decay
            gyro_pulse = sign * rng.uniform(45.0, 130.0) * _safe_intensity(intensity) * decay
            base[index]["ax"] = _round_acc(base[index]["ax"] + acc_pulse * rng.uniform(0.4, 1.0))
            base[index]["ay"] = _round_acc(base[index]["ay"] - acc_pulse * rng.uniform(0.2, 0.8))
            base[index]["az"] = _round_acc(base[index]["az"] + abs(acc_pulse) * rng.uniform(0.1, 0.7))
            base[index]["gx"] = _round_gyro(base[index]["gx"] + gyro_pulse * rng.uniform(0.3, 1.0))
            base[index]["gy"] = _round_gyro(base[index]["gy"] - gyro_pulse * rng.uniform(0.2, 0.8))
            base[index]["gz"] = _round_gyro(base[index]["gz"] + gyro_pulse * rng.uniform(0.2, 0.9))
    return base


def generate_tail_sway_samples(
    sample_rate_hz: int = 50,
    duration_s: float = 10.0,
    sensor_position: str = "simulated_tail",
    noise_level: float = 0.03,
    intensity: float = 1.0,
    random_seed: int | None = None,
    *,
    start_timestamp_ms: int | None = None,
    seq_start: int = 0,
    sample_count: int | None = None,
) -> list[dict]:
    rng = random.Random(random_seed)
    context = _make_context(rng, sample_rate_hz, duration_s, start_timestamp_ms, seq_start, sample_count)
    freq = rng.uniform(0.8, 1.8)
    phase = rng.uniform(0.0, math.tau)
    gyro_amp = rng.uniform(20.0, 80.0) * _safe_intensity(intensity)
    angle_amp = rng.uniform(8.0, 28.0) * _safe_intensity(intensity)
    acc_amp = 0.035 * _safe_intensity(intensity)
    samples = []
    for index in range(context["sample_count"]):
        t = index / sample_rate_hz
        wave = math.sin(math.tau * freq * t + phase)
        samples.append(
            _sample(
                context,
                index,
                ax=acc_amp * math.sin(math.tau * freq * t + phase / 3.0) + rng.gauss(0.0, noise_level * 0.5),
                ay=acc_amp * 0.8 * wave + rng.gauss(0.0, noise_level * 0.5),
                az=1.0 + acc_amp * 0.45 * wave + rng.gauss(0.0, noise_level * 0.5),
                gx=rng.gauss(0.0, noise_level * 8.0),
                gy=gyro_amp * 0.22 * math.sin(math.tau * freq * t + phase * 0.5)
                + rng.gauss(0.0, noise_level * 8.0),
                gz=gyro_amp * wave + rng.gauss(0.0, noise_level * 8.0),
                tail_angle_deg=angle_amp * wave,
            )
        )
    return samples


def generate_tail_flick_or_agitation_samples(
    sample_rate_hz: int = 50,
    duration_s: float = 10.0,
    sensor_position: str = "simulated_tail",
    noise_level: float = 0.03,
    intensity: float = 1.0,
    random_seed: int | None = None,
    *,
    start_timestamp_ms: int | None = None,
    seq_start: int = 0,
    sample_count: int | None = None,
) -> list[dict]:
    rng = random.Random(random_seed)
    context = _make_context(rng, sample_rate_hz, duration_s, start_timestamp_ms, seq_start, sample_count)
    samples = generate_still_samples(
        sample_rate_hz,
        duration_s,
        sensor_position,
        noise_level * 1.2,
        intensity,
        random_seed,
        start_timestamp_ms=start_timestamp_ms,
        seq_start=seq_start,
        sample_count=context["sample_count"],
    )
    pulse_count = max(2, int(math.ceil(duration_s * 0.9 * _safe_intensity(intensity))))
    for _ in range(pulse_count):
        start = rng.randrange(0, max(1, context["sample_count"]))
        width = rng.randint(2, 8)
        axis_weights = [rng.uniform(0.1, 1.0) for _ in range(3)]
        sign = rng.choice([-1.0, 1.0])
        for index in range(start, min(context["sample_count"], start + width)):
            offset = index - start
            decay = 1.0 - (offset / max(1, width))
            gyro_pulse = sign * rng.uniform(120.0, 260.0) * _safe_intensity(intensity) * decay
            acc_pulse = sign * rng.uniform(0.06, 0.22) * _safe_intensity(intensity) * decay
            samples[index]["gx"] = _round_gyro(samples[index]["gx"] + gyro_pulse * axis_weights[0])
            samples[index]["gy"] = _round_gyro(samples[index]["gy"] - gyro_pulse * axis_weights[1])
            samples[index]["gz"] = _round_gyro(samples[index]["gz"] + gyro_pulse * axis_weights[2])
            samples[index]["ax"] = _round_acc(samples[index]["ax"] + acc_pulse * rng.uniform(0.2, 1.0))
            samples[index]["ay"] = _round_acc(samples[index]["ay"] - acc_pulse * rng.uniform(0.2, 0.8))
            samples[index]["az"] = _round_acc(samples[index]["az"] + abs(acc_pulse) * rng.uniform(0.1, 0.6))
            if sensor_position == "simulated_tail":
                current_angle = samples[index]["tail_angle_deg"] or 0.0
                samples[index]["tail_angle_deg"] = round(current_angle + sign * rng.uniform(12.0, 35.0) * decay, 2)
    return samples


def generate_unknown_samples(
    sample_rate_hz: int = 50,
    duration_s: float = 10.0,
    sensor_position: str = "simulated_tail",
    noise_level: float = 0.03,
    intensity: float = 1.0,
    random_seed: int | None = None,
    *,
    start_timestamp_ms: int | None = None,
    seq_start: int = 0,
    sample_count: int | None = None,
) -> list[dict]:
    rng = random.Random(random_seed)
    context = _make_context(rng, sample_rate_hz, duration_s, start_timestamp_ms, seq_start, sample_count)
    acc_noise = max(0.055, noise_level * 1.8) * _safe_intensity(intensity)
    gyro_noise = max(1.5, noise_level * 65.0) * _safe_intensity(intensity)
    samples = []
    for index in range(context["sample_count"]):
        drift = math.sin(math.tau * 0.17 * (index / sample_rate_hz) + rng.random()) * 0.018
        samples.append(
            _sample(
                context,
                index,
                ax=rng.gauss(0.0, acc_noise) + drift,
                ay=rng.gauss(0.0, acc_noise * 0.8) - drift,
                az=1.0 + rng.gauss(0.0, acc_noise * 0.75),
                gx=rng.gauss(0.0, gyro_noise),
                gy=rng.gauss(0.0, gyro_noise * 0.7),
                gz=rng.gauss(0.0, gyro_noise * 0.6),
                tail_angle_deg=None,
            )
        )
    return samples


def generate_mixed_samples(
    sample_rate_hz: int = 50,
    duration_s: float = 10.0,
    sensor_position: str = "simulated_tail",
    noise_level: float = 0.03,
    intensity: float = 1.0,
    random_seed: int | None = None,
    *,
    start_timestamp_ms: int | None = None,
    seq_start: int = 0,
    sample_count: int | None = None,
) -> list[dict]:
    rng = random.Random(random_seed)
    total = _sample_count(sample_rate_hz, duration_s, sample_count)
    start_ms = int(time.time() * 1000) if start_timestamp_ms is None else int(start_timestamp_ms)
    segment_count = min(5, max(3, int(round(duration_s / 3.0)) or 3))
    segment_count = min(segment_count, total)
    base_size = total // segment_count
    sizes = [base_size for _ in range(segment_count)]
    for index in range(total - sum(sizes)):
        sizes[index % len(sizes)] += 1
    scenario_pool = ["still", "body_active", "tail_sway", "tail_flick_or_agitation", "body_intense", "unknown"]
    rng.shuffle(scenario_pool)
    generators: dict[str, Callable[..., list[dict]]] = {
        "still": generate_still_samples,
        "body_active": generate_body_active_samples,
        "body_intense": generate_body_intense_samples,
        "tail_sway": generate_tail_sway_samples,
        "tail_flick_or_agitation": generate_tail_flick_or_agitation_samples,
        "unknown": generate_unknown_samples,
    }
    samples: list[dict] = []
    seq = int(seq_start)
    interval_ms = 1000.0 / sample_rate_hz
    for segment_index, size in enumerate(sizes):
        scenario = scenario_pool[segment_index % len(scenario_pool)]
        segment_start_ms = int(round(start_ms + (seq - seq_start) * interval_ms))
        segment_duration = size / sample_rate_hz
        segment = generators[scenario](
            sample_rate_hz,
            segment_duration,
            sensor_position,
            noise_level,
            intensity,
            rng.randrange(1, 2**31),
            start_timestamp_ms=segment_start_ms,
            seq_start=seq,
            sample_count=size,
        )
        samples.extend(segment)
        seq += size
    return samples


def _make_context(
    rng: random.Random,
    sample_rate_hz: int,
    duration_s: float,
    start_timestamp_ms: int | None,
    seq_start: int,
    sample_count: int | None,
) -> dict:
    battery = rng.randint(85, 100)
    rssi = rng.randint(-72, -48)
    return {
        "sample_rate_hz": int(sample_rate_hz),
        "sample_count": _sample_count(sample_rate_hz, duration_s, sample_count),
        "start_timestamp_ms": int(time.time() * 1000) if start_timestamp_ms is None else int(start_timestamp_ms),
        "seq_start": int(seq_start),
        "battery": battery,
        "rssi": rssi,
        "rng": rng,
    }


def _sample_count(sample_rate_hz: int, duration_s: float, override: int | None = None) -> int:
    if override is not None:
        return max(0, int(override))
    return max(1, int(round(int(sample_rate_hz) * float(duration_s))))


def _sample(
    context: dict,
    index: int,
    *,
    ax: float,
    ay: float,
    az: float,
    gx: float,
    gy: float,
    gz: float,
    tail_angle_deg: float | None,
) -> dict:
    rng: random.Random = context["rng"]
    interval_ms = 1000.0 / context["sample_rate_hz"]
    timestamp_ms = int(round(context["start_timestamp_ms"] + index * interval_ms))
    return {
        "timestamp_ms": timestamp_ms,
        "seq": context["seq_start"] + index,
        "ax": _round_acc(ax),
        "ay": _round_acc(ay),
        "az": _round_acc(az),
        "gx": _round_gyro(gx),
        "gy": _round_gyro(gy),
        "gz": _round_gyro(gz),
        "tail_angle_deg": None if tail_angle_deg is None else round(float(tail_angle_deg), 2),
        "battery": max(0, min(100, int(context["battery"]))),
        "rssi": max(-100, min(-20, int(context["rssi"] + rng.randint(-2, 2)))),
    }


def _safe_intensity(intensity: float) -> float:
    try:
        value = float(intensity)
    except (TypeError, ValueError):
        value = 1.0
    return max(0.1, min(3.0, value))


def _round_acc(value: float) -> float:
    return round(float(value), 5)


def _round_gyro(value: float) -> float:
    return round(float(value), 3)
