from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, Request

from ..config import CURRENT_USER_ID
from ..database import execute, fetch_one
from .storage_service import now_iso


CURRENT_USER_SETTING_KEY = "current_user_id"
SESSION_COOKIE_NAME = "petlink_session"
SESSION_TTL_DAYS = 7


def _public_user_query() -> str:
    return "SELECT user_id, username, display_name, avatar, bio, created_at FROM users WHERE user_id = ?"


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def get_current_user_setting_value() -> str | None:
    row = fetch_one("SELECT value FROM settings WHERE key = ?", (CURRENT_USER_SETTING_KEY,))
    if row is None:
        return None
    return row.get("value") or ""


def get_current_user_id() -> str:
    value = get_current_user_setting_value()
    return value if value is not None else CURRENT_USER_ID


def set_current_user_id(user_id: str) -> str:
    execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (CURRENT_USER_SETTING_KEY, user_id, now_iso()),
    )
    return user_id


def clear_current_user_id() -> None:
    set_current_user_id("")


def create_session(user_id: str, request: Request | None = None, client_label: str = "") -> str:
    if fetch_one("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) is None:
        raise HTTPException(status_code=404, detail="User not found")
    session_id = secrets.token_urlsafe(32)
    created_at = datetime.now().astimezone()
    expires_at = created_at + timedelta(days=SESSION_TTL_DAYS)
    user_agent = request.headers.get("user-agent", "") if request is not None else ""
    execute(
        """
        INSERT INTO sessions (session_id, user_id, created_at, last_seen_at, expires_at, user_agent, client_label)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            user_id,
            created_at.isoformat(timespec="seconds"),
            created_at.isoformat(timespec="seconds"),
            expires_at.isoformat(timespec="seconds"),
            user_agent,
            client_label,
        ),
    )
    return session_id


def clear_session(session_id: str) -> None:
    if session_id:
        execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def get_session_user_id(request: Request | None) -> str:
    if request is None:
        return ""
    session_id = request.cookies.get(SESSION_COOKIE_NAME, "")
    return get_session_user_id_from_session_id(session_id)


def get_session_user_id_from_session_id(session_id: str) -> str:
    if not session_id:
        return ""
    row = fetch_one("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
    if row is None:
        return ""
    expires_at = _parse_dt(row.get("expires_at", ""))
    now = datetime.now().astimezone()
    if expires_at is None or expires_at <= now:
        clear_session(session_id)
        return ""
    execute("UPDATE sessions SET last_seen_at = ? WHERE session_id = ?", (now_iso(), session_id))
    return row["user_id"]


def get_optional_current_user(request: Request | None = None, allow_legacy_fallback: bool = False) -> dict | None:
    user_id = get_session_user_id(request)
    if not user_id and allow_legacy_fallback:
        user_id = get_current_user_setting_value() or ""
    if not user_id:
        return None
    return fetch_one(_public_user_query(), (user_id,))


def get_current_user_from_request(request: Request) -> dict | None:
    return get_optional_current_user(request, allow_legacy_fallback=False)


def get_authenticated_user_id(request: Request | None = None, allow_legacy_fallback: bool = False) -> str:
    user = get_optional_current_user(request, allow_legacy_fallback=allow_legacy_fallback)
    return (user or {}).get("user_id", "")


def require_current_user(request: Request | None = None, allow_legacy_fallback: bool = False) -> dict:
    user = get_optional_current_user(request, allow_legacy_fallback=allow_legacy_fallback)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in")
    return user


def require_current_user_id(request: Request | None = None, allow_legacy_fallback: bool = False) -> str:
    return require_current_user(request, allow_legacy_fallback=allow_legacy_fallback)["user_id"]


def get_current_user() -> dict:
    return get_optional_current_user(None, allow_legacy_fallback=True) or {}
