"""AC880 视觉姿态 UDP 接入 + ESP32-S3 串口/BLE 桥接 + 视听多模态融合服务。

数据链路：
  AC880 (`detect_pet_pose_live --udp <PC_IP>:9000`)
    ─(UDP:9000 JSON)─▶ VisionBridgeService
                          ├─▶ Web 状态 & 历史缓存 (/api/vision/*)
                          └─▶ ESP32-S3 USB 串口 (COMx, 115200) ─(BLE NUS Notify)─▶ 手机 App
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any

from ..database import fetch_one

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover - optional runtime dependency
    serial = None


POSE_ZH = {
    "STD": "站立",
    "SIT": "坐姿",
    "LIE": "趴卧",
    "UNK": "待确认 / 局部遮挡",
}

SPECIES_ZH = {
    "CAT": "猫",
    "DOG": "狗",
    "NONE": "未检测到宠物",
}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class VisionBridgeService:
    """Thread-safe UDP:9000 receiver and optional ESP32-S3 serial forwarder."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._udp_thread: threading.Thread | None = None
        self._udp_sock: socket.socket | None = None
        self._serial_conn: Any = None

        self._udp_port: int = int(os.getenv("PETLINK_VISION_UDP_PORT", "9000"))
        self._esp32_port: str = os.getenv("PETLINK_ESP32_PORT", "").strip()
        self._esp32_baud: int = int(os.getenv("PETLINK_ESP32_BAUD", "115200"))

        self._udp_listening = False
        self._udp_error = ""
        self._esp32_error = ""
        self._udp_rx_count = 0
        self._esp32_tx_count = 0
        self._latest_frame: dict[str, Any] | None = None
        self._latest_valid_frame: dict[str, Any] | None = None
        self._history: deque[dict[str, Any]] = deque(maxlen=200)
        self._last_hist_ts = 0.0
        self._last_hist_pose = ""

    def start(self) -> None:
        """Start UDP listener (unless disabled) and connect ESP32 serial if configured."""
        if os.getenv("PETLINK_DISABLE_VISION_UDP", "0") == "1":
            return
        if self._udp_thread is None or not self._udp_thread.is_alive():
            self._stop_event.clear()
            self._udp_thread = threading.Thread(
                target=self._udp_loop, name="ac880-udp-rx", daemon=True
            )
            self._udp_thread.start()
        if self._esp32_port:
            self.connect_esp32(self._esp32_port, self._esp32_baud)

    def stop(self) -> None:
        self._stop_event.set()
        if self._udp_sock is not None:
            try:
                self._udp_sock.close()
            except OSError:
                pass
            self._udp_sock = None
        self._udp_listening = False
        self.disconnect_esp32()

    def connect_esp32(self, port: str, baud: int = 115200) -> dict[str, Any]:
        """Open serial port to ESP32-S3 bridge without resetting the chip."""
        with self._lock:
            self._esp32_port = port.strip()
            self._esp32_baud = baud
            if self._serial_conn is not None:
                try:
                    self._serial_conn.close()
                except Exception:
                    pass
                self._serial_conn = None
            if serial is None:
                self._esp32_error = "pyserial_not_installed"
                return self.get_status()
            if not self._esp32_port:
                self._esp32_error = ""
                return self.get_status()
            try:
                conn = serial.Serial()
                conn.port = self._esp32_port
                conn.baudrate = self._esp32_baud
                conn.timeout = 0.2
                conn.write_timeout = 0.5
                conn.dtr = False
                conn.rts = False
                conn.open()
                self._serial_conn = conn
                self._esp32_error = ""
            except Exception as exc:  # noqa: BLE001
                self._esp32_error = str(exc)
        return self.get_status()

    def disconnect_esp32(self) -> None:
        with self._lock:
            if self._serial_conn is not None:
                try:
                    self._serial_conn.close()
                except Exception:
                    pass
                self._serial_conn = None

    def _udp_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", self._udp_port))
            sock.settimeout(0.5)
        except OSError as exc:
            with self._lock:
                self._udp_listening = False
                self._udp_error = str(exc)
            sock.close()
            return

        with self._lock:
            self._udp_sock = sock
            self._udp_listening = True
            self._udp_error = ""

        while not self._stop_event.is_set():
            try:
                raw_bytes, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            text = raw_bytes.decode("utf-8", errors="ignore").strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                self.ingest_frame(payload, source=f"udp:{addr[0]}")

    def ingest_frame(self, payload: dict[str, Any], source: str = "http") -> dict[str, Any]:
        """Validate, store, throttle-record, and forward one AC880 JSON frame."""
        now_s = time.time()
        valid = bool(int(payload.get("valid", 0)))
        cls_code = str(payload.get("cls") or "NONE").upper()
        pose_code = str(payload.get("pose") or "UNK").upper()
        raw_pose = str(payload.get("raw") or pose_code).upper()
        frame = {
            "seq": int(payload.get("seq", 0)),
            "valid": 1 if valid else 0,
            "cls": cls_code,
            "species_zh": SPECIES_ZH.get(cls_code, cls_code),
            "score": round(float(payload.get("score", 0.0)), 4),
            "pose": pose_code,
            "pose_zh": POSE_ZH.get(pose_code, pose_code),
            "raw": raw_pose,
            "kpt_cnt": int(payload.get("kpt_cnt", 0)),
            "box": payload.get("box") if isinstance(payload.get("box"), list) else [0, 0, 0, 0],
            "ms": round(float(payload.get("ms", 0.0)), 1),
            "source": source,
            "received_at": _now_iso(),
            "received_epoch": now_s,
        }

        wire_obj = {
            "seq": frame["seq"],
            "valid": frame["valid"],
            "cls": frame["cls"],
            "score": round(frame["score"], 2),
            "pose": frame["pose"],
            "raw": frame["raw"],
            "kpt_cnt": frame["kpt_cnt"],
            "box": frame["box"],
            "ms": frame["ms"],
        }
        wire_line = (json.dumps(wire_obj, separators=(",", ":")) + "\n").encode("utf-8")

        with self._lock:
            self._udp_rx_count += 1
            self._latest_frame = frame
            if valid:
                self._latest_valid_frame = frame
                if pose_code != self._last_hist_pose or (now_s - self._last_hist_ts) >= 5.0:
                    self._history.appendleft(frame)
                    self._last_hist_pose = pose_code
                    self._last_hist_ts = now_s

            if self._serial_conn is not None and self._serial_conn.is_open:
                try:
                    self._serial_conn.write(wire_line)
                    self._esp32_tx_count += 1
                    self._esp32_error = ""
                except Exception as exc:  # noqa: BLE001
                    self._esp32_error = str(exc)

        return frame

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            latest = dict(self._latest_frame) if self._latest_frame else None
            esp32_open = bool(self._serial_conn is not None and self._serial_conn.is_open)
            stale = True
            if latest is not None:
                stale = (time.time() - float(latest.get("received_epoch", 0.0))) > 6.0
            return {
                "udp_listening": self._udp_listening,
                "udp_port": self._udp_port,
                "udp_error": self._udp_error,
                "udp_rx_count": self._udp_rx_count,
                "esp32_port": self._esp32_port,
                "esp32_connected": esp32_open,
                "esp32_tx_count": self._esp32_tx_count,
                "esp32_error": self._esp32_error,
                "stream_stale": stale,
                "latest": latest,
            }

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)[: max(1, min(limit, 200))]

    def get_multimodal_summary(self) -> dict[str, Any]:
        """Fuse latest AC880 visual posture with latest stored audio recognition."""
        status = self.get_status()
        vision = status["latest"]
        audio_row = fetch_one(
            """
            SELECT recognition_id, pet_id, prediction_label, display_label,
                   confidence, trigger, created_at
            FROM recognition_records
            ORDER BY created_at DESC
            LIMIT 1
            """
        )

        vision_active = bool(vision and vision.get("valid") == 1 and not status["stream_stale"])
        audio_summary = dict(audio_row) if audio_row else None

        hint = "等待 AC880 视觉流或音频识别记录。"
        if vision_active and audio_summary:
            v_desc = f"{vision['species_zh']}·{vision['pose_zh']}"
            a_desc = audio_summary.get("display_label") or audio_summary.get("prediction_label") or "未知"
            hint = f"视觉检测到「{v_desc}」，最近一次声音倾向为「{a_desc}」。"
        elif vision_active:
            hint = f"AC880 实时视觉：{vision['species_zh']} · {vision['pose_zh']}（关键点 {vision['kpt_cnt']}/17）。"
        elif audio_summary:
            a_desc = audio_summary.get("display_label") or audio_summary.get("prediction_label") or "未知"
            hint = f"最近音频识别：{a_desc}（AC880 视觉流暂无最新目标）。"

        return {
            "vision_active": vision_active,
            "vision": vision,
            "audio": audio_summary,
            "summary": hint,
            "safety_message": "视觉姿态与声音融合结果仅供行为观察参考，非医疗诊断判断。",
        }


vision_bridge = VisionBridgeService()
