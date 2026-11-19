"""Smoke test for AC880 vision bridge & multimodal API endpoints."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _bootstrap(tmp_root: Path):
    os.environ["PETLINK_DISABLE_VISION_UDP"] = "1"
    from app.backend import config as cfg

    cfg.DATA_DIR = tmp_root / "data"
    cfg.UPLOADS_DIR = cfg.DATA_DIR / "uploads"
    cfg.EXPORTS_DIR = cfg.DATA_DIR / "exports"
    cfg.DATABASE_PATH = cfg.DATA_DIR / "petlink_web.sqlite"

    import app.backend.database as database

    database.DATA_DIR = cfg.DATA_DIR
    database.UPLOADS_DIR = cfg.UPLOADS_DIR
    database.EXPORTS_DIR = cfg.EXPORTS_DIR
    database.DATABASE_PATH = cfg.DATABASE_PATH

    from app.backend.main import app

    database.init_database()
    return app


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="petlink_vision_"))
    app = _bootstrap(tmp)

    from fastapi.testclient import TestClient

    client = TestClient(app)

    r = client.post(
        "/api/vision/ingest",
        json={
            "seq": 42,
            "valid": 1,
            "cls": "CAT",
            "score": 0.88,
            "pose": "SIT",
            "raw": "SIT",
            "kpt_cnt": 15,
            "box": [120, 80, 640, 520],
            "ms": 2150.5,
        },
    )
    assert r.status_code == 200, r.text
    frame = r.json()["frame"]
    assert frame["species_zh"] == "猫"
    assert frame["pose_zh"] == "坐姿"

    latest = client.get("/api/vision/latest").json()
    assert latest["udp_rx_count"] >= 1
    assert latest["latest"]["seq"] == 42

    hist = client.get("/api/vision/history").json()
    assert len(hist["items"]) >= 1
    assert hist["items"][0]["pose"] == "SIT"

    mm = client.get("/api/vision/multimodal").json()
    assert mm["vision_active"] is True
    assert "猫" in mm["summary"] and "坐姿" in mm["summary"]
    print("VISION_BRIDGE_SMOKE_PASS (4/4 assertions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
