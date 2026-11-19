"""One-command launcher for AC880 -> ESP32-S3 BLE -> Mobile App (headless relay by default).

Usage:
    python scripts/run_integrated_demo.py --esp32-port COM8 --sudo-pass root
    python scripts/run_integrated_demo.py --esp32-port COM8 --with-web
"""
from __future__ import annotations

import argparse
import getpass
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import serial


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_AUDIO_DIR = REPO_ROOT / "web_audio"


def detect_link_local_pc_ip(prefix: str = "169.254.") -> str:
    """Return local IPv4 address matching the Ethernet direct-link subnet."""
    hostname = socket.gethostname()
    for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
        ip = info[4][0]
        if ip.startswith(prefix):
            return ip
    return "169.254.239.33"


def default_python() -> str:
    candidates = [
        WEB_AUDIO_DIR / ".venv" / "Scripts" / "python.exe",
        Path(r"E:\python\pet_link_venv\Scripts\python.exe"),
        Path(sys.executable),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable


def setup_ac880_network(ssh_key: Path, target: str, ac880_ip: str, sudo_pass: str) -> None:
    remote_cmd = (
        f"sudo -S ip addr add {ac880_ip}/16 dev eth0 2>/dev/null || true; "
        "ip -4 -brief addr show eth0"
    )
    res = subprocess.run(
        [
            "ssh",
            "-i",
            str(ssh_key),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=5",
            target,
            remote_cmd,
        ],
        input=f"{sudo_pass}\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"Failed to configure AC880 SSH/eth0: {res.stderr.strip()}")
    print(f"[AC880] {res.stdout.strip()}")


class HeadlessUdpToSerialRelay:
    """Lightweight UDP:9000 -> ESP32-S3 Serial relay (no Web UI)."""

    def __init__(self, udp_port: int, serial_port: str, baud: int = 115200) -> None:
        self.udp_port = udp_port
        self.serial_port = serial_port
        self.baud = baud
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._ser: serial.Serial | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        conn = serial.Serial()
        conn.port = self.serial_port
        conn.baudrate = self.baud
        conn.timeout = 0.2
        conn.write_timeout = 0.5
        conn.dtr = False
        conn.rts = False
        conn.open()
        self._ser = conn

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.udp_port))
        sock.settimeout(0.5)
        self._sock = sock

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[Relay] UDP:{self.udp_port} -> {self.serial_port} -> BLE (Petlink-ESP32S3) ready")

    def _loop(self) -> None:
        assert self._sock is not None and self._ser is not None
        while not self._stop.is_set():
            if self._ser.in_waiting:
                rx = self._ser.read(self._ser.in_waiting).decode("utf-8", errors="ignore")
                for msg in rx.splitlines():
                    if msg.startswith(("TOUCH", "BLE_", "TJC_")):
                        print(f"[ESP32] {msg}")
            try:
                data, _addr = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            line = data.decode("utf-8", errors="ignore").strip()
            if line.startswith("{"):
                self._ser.write((line + "\n").encode("utf-8"))

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._ser is not None and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run AC880 -> ESP32-S3 BLE -> Mobile App pipeline (headless relay by default)"
    )
    parser.add_argument("--ac880-host", default="fe80::20a:35ff:fe00:1e53%19")
    parser.add_argument("--ac880-user", default="zynq")
    parser.add_argument("--ac880-ip", default="169.254.3.140")
    parser.add_argument("--pc-ip", default=detect_link_local_pc_ip())
    parser.add_argument("--udp-port", type=int, default=9000)
    parser.add_argument("--web-port", type=int, default=8765)
    parser.add_argument("--esp32-port", default="COM8")
    parser.add_argument("--ssh-key", default=str(Path.home() / ".ssh" / "ac880_petlink_ed25519"))
    parser.add_argument("--sudo-pass", default=os.getenv("PETLINK_AC880_SUDO_PASS", ""))
    parser.add_argument("--max-iters", type=int, default=0, help="0 = continuous")
    parser.add_argument("--kpt-thr", type=float, default=0.72)
    parser.add_argument("--with-web", action="store_true", help="Also start optional PC Web UI")
    args = parser.parse_args()

    sudo_pass = args.sudo_pass or getpass.getpass("AC880 sudo password: ")
    ssh_key = Path(args.ssh_key)
    target = f"{args.ac880_user}@{args.ac880_host}"

    setup_ac880_network(ssh_key, target, args.ac880_ip, sudo_pass)

    web_proc: subprocess.Popen[str] | None = None
    relay: HeadlessUdpToSerialRelay | None = None

    if args.with_web:
        py = default_python()
        env = os.environ.copy()
        env["PETLINK_VISION_UDP_PORT"] = str(args.udp_port)
        env["PETLINK_ESP32_PORT"] = args.esp32_port
        print(f"[Web] Starting optional PC Web UI on http://127.0.0.1:{args.web_port}")
        web_proc = subprocess.Popen(
            [py, "-m", "uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", str(args.web_port)],
            cwd=str(WEB_AUDIO_DIR),
            env=env,
        )
        time.sleep(2.0)
    else:
        relay = HeadlessUdpToSerialRelay(args.udp_port, args.esp32_port)
        relay.start()

    remote_run = (
        f"cd ~/petlink && sudo -S pkill -x detect_pet_pose_live 2>/dev/null || true; "
        f"sudo -S ./detect_pet_pose_live {args.max_iters} {args.kpt_thr} "
        f"--udp {args.pc_ip}:{args.udp_port}"
    )
    print(f"[AC880] Launching detect_pet_pose_live -> {args.pc_ip}:{args.udp_port}")
    ac880_proc = subprocess.Popen(
        ["ssh", "-i", str(ssh_key), "-o", "StrictHostKeyChecking=no", target, remote_run],
        stdin=subprocess.PIPE,
        text=True,
    )
    if ac880_proc.stdin is not None:
        ac880_proc.stdin.write(f"{sudo_pass}\n")
        ac880_proc.stdin.flush()

    def shutdown(_signum, _frame):
        print("\nStopping PetLink pipeline...")
        ac880_proc.terminate()
        if web_proc is not None:
            web_proc.terminate()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        return ac880_proc.wait()
    finally:
        if ac880_proc.poll() is None:
            ac880_proc.terminate()
        if relay is not None:
            relay.stop()
        if web_proc is not None and web_proc.poll() is None:
            web_proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
