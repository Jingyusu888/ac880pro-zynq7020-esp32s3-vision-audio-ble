from __future__ import annotations

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
WEB_APP_DIR = BACKEND_DIR.parent
FRONTEND_DIR = WEB_APP_DIR / "frontend-web" / "dist"
DATA_DIR = WEB_APP_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
EXPORTS_DIR = DATA_DIR / "exports"
DATABASE_PATH = DATA_DIR / "petlink_web.sqlite"

APP_TITLE = "PetLink Web App Local Test"
APP_VERSION = "0.1.0-local"
CURRENT_USER_ID = "local_owner"

