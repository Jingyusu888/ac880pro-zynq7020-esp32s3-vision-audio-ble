from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_TITLE, APP_VERSION, FRONTEND_DIR
from .database import init_database
from .routers import auth, community, health, imu, pets, smart_tools, training, vision
from .services.demo_data_service import seed_demo_data
from .services.vision_bridge_service import vision_bridge


app = FastAPI(title=APP_TITLE, version=APP_VERSION)


@app.on_event("startup")
def startup() -> None:
    init_database()
    seed_demo_data()
    vision_bridge.start()


@app.on_event("shutdown")
def shutdown() -> None:
    vision_bridge.stop()


app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(pets.router, prefix="/api")
app.include_router(community.router, prefix="/api")
app.include_router(smart_tools.router, prefix="/api")
app.include_router(training.router, prefix="/api")
app.include_router(imu.router, prefix="/api")
app.include_router(vision.router, prefix="/api")

if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:

    @app.get("/")
    def root_status() -> dict[str, str]:
        return {
            "service": APP_TITLE,
            "version": APP_VERSION,
            "frontend": "not_built (run npm run build in web_audio/app/frontend-web)",
            "docs": "/docs",
        }
