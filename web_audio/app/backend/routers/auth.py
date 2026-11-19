from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, HTTPException, Request, Response

from ..database import execute, fetch_one
from ..schemas import AuthLogin, AuthRegister
from ..services.current_user_service import (
    SESSION_COOKIE_NAME,
    clear_session,
    create_session,
    get_current_user_from_request,
)
from ..services.storage_service import make_id, now_iso


router = APIRouter()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def public_user(row: dict | None) -> dict | None:
    if not row:
        return None
    return {key: value for key, value in row.items() if key != "password_hash"}


def _normalize_username(username: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_\-]", "_", username.strip())
    return normalized.lower()


@router.post("/register")
def register(payload: AuthRegister, request: Request, response: Response) -> dict:
    username = _normalize_username(payload.username)
    display_name = payload.display_name.strip()
    password = payload.password.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if not display_name:
        raise HTTPException(status_code=400, detail="Display name is required")
    if not password:
        raise HTTPException(status_code=400, detail="Password is required")
    if fetch_one("SELECT user_id FROM users WHERE username = ?", (username,)):
        raise HTTPException(status_code=400, detail="Username already exists")

    user_id = make_id("user")
    execute(
        """
        INSERT INTO users (user_id, username, display_name, password_hash, avatar, bio, created_at)
        VALUES (?, ?, ?, ?, '', ?, ?)
        """,
        (user_id, username, display_name, hash_password(password), "PetLink local test user", now_iso()),
    )
    session_id = create_session(user_id, request, client_label="register")
    response.set_cookie(SESSION_COOKIE_NAME, session_id, httponly=True, samesite="lax", secure=False, max_age=7 * 24 * 60 * 60)
    return {
        "ok": True,
        "authenticated": True,
        "user": public_user(fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))),
    }


@router.post("/login")
def login(payload: AuthLogin, request: Request, response: Response) -> dict:
    username = _normalize_username(payload.username)
    row = fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if row is None or row.get("password_hash") != hash_password(payload.password.strip()):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    session_id = create_session(row["user_id"], request, client_label="login")
    response.set_cookie(SESSION_COOKIE_NAME, session_id, httponly=True, samesite="lax", secure=False, max_age=7 * 24 * 60 * 60)
    return {"ok": True, "authenticated": True, "user": public_user(row)}


@router.post("/demo-login")
def demo_login(request: Request, response: Response) -> dict:
    username = "demo_user"
    display_name = "PetLink Demo User"
    password_hash = hash_password("DemoUser123!")
    row = fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if row is None:
        user_id = make_id("user")
        execute(
            """
            INSERT INTO users (user_id, username, display_name, password_hash, avatar, bio, created_at)
            VALUES (?, ?, ?, ?, '', ?, ?)
            """,
            (user_id, username, display_name, password_hash, "R8.5 demo user; safe to reuse.", now_iso()),
        )
        row = fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    elif row.get("password_hash") != password_hash:
        execute(
            "UPDATE users SET display_name = ?, password_hash = ?, bio = ? WHERE user_id = ?",
            (display_name, password_hash, "R8.5 demo user; safe to reuse.", row["user_id"]),
        )
        row = fetch_one("SELECT * FROM users WHERE user_id = ?", (row["user_id"],))
    session_id = create_session(row["user_id"], request, client_label="demo_login")
    response.set_cookie(SESSION_COOKIE_NAME, session_id, httponly=True, samesite="lax", secure=False, max_age=7 * 24 * 60 * 60)
    return {
        "ok": True,
        "authenticated": True,
        "demo_mode": True,
        "user": public_user(row),
    }


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    clear_session(request.cookies.get(SESSION_COOKIE_NAME, ""))
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    user = get_current_user_from_request(request)
    return {"authenticated": bool(user), "user": public_user(user)}
