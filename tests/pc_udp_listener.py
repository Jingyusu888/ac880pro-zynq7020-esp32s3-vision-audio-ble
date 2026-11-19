#!/usr/bin/env python3
"""Listen on UDP port 9000 (default) and print AC880 Petlink JSON telemetry."""
import argparse
import json
import socket
import time


def main():
    parser = argparse.ArgumentParser(description="AC880 Petlink PC UDP Listener")
    parser.add_argument("--host", default="0.0.0.0", help="Bind IPv4 address (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=9000, help="UDP port (default 9000)")
    parser.add_argument("--count", type=int, default=0, help="Exit after N packets (0=infinite)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))
    print(f"[Petlink UDP Listener] Listening on {args.host}:{args.port} ...", flush=True)

    n = 0
    try:
        while args.count <= 0 or n < args.count:
            data, addr = sock.recvfrom(1024)
            text = data.decode("utf-8", errors="replace").strip()
            ts = time.strftime("%H:%M:%S")
            try:
                obj = json.loads(text)
                cls = obj.get("cls", "?")
                pose = obj.get("pose", "?")
                raw = obj.get("raw", "?")
                score = obj.get("score", 0.0)
                kpts = obj.get("kpt_cnt", 0)
                ms = obj.get("ms", 0.0)
                seq = obj.get("seq", -1)
                print(
                    f"[{ts}] from={addr[0]}:{addr[1]} seq={seq} "
                    f"{cls}-{pose} (raw={raw}) score={score:.2f} kpts={kpts}/17 "
                    f"box={obj.get('box')} ms={ms}",
                    flush=True,
                )
            except Exception:
                print(f"[{ts}] from={addr[0]}:{addr[1]} RAW={text}", flush=True)
            n += 1
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        sock.close()


if __name__ == "__main__":
    main()
