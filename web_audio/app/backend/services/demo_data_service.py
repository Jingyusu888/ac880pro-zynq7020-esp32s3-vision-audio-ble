r"""演示数据播种：只建当前用户 + 一只宠物（社交层已裁剪）。

迁移改造：原版播种 8 张社交表 + 20+ 用户/帖子/消息（298 行），
雏形只需要"当前用户 + 宠物"让识别/时间线/候选池闭环可演示。
"""
from __future__ import annotations

import hashlib

from ..config import CURRENT_USER_ID
from ..database import execute, fetch_one, init_database
from .current_user_service import set_current_user_id
from .storage_service import make_id, now_iso

DEMO_PASSWORD = "123456"


def _hash_password(password: str = DEMO_PASSWORD) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _ensure_user(user_id: str, username: str, display_name: str) -> None:
    existing = fetch_one("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if existing is None:
        execute(
            """
            INSERT INTO users (user_id, username, display_name, password_hash, avatar, bio, created_at)
            VALUES (?, ?, ?, ?, '', '', ?)
            """,
            (user_id, username, display_name, _hash_password(), now_iso()),
        )


def _ensure_pet(pet_id: str, owner_user_id: str, name: str) -> None:
    existing = fetch_one("SELECT pet_id FROM pets WHERE pet_id = ?", (pet_id,))
    if existing is None:
        execute(
            """
            INSERT INTO pets (pet_id, owner_user_id, name, species, breed, age, avatar, bio, created_at)
            VALUES (?, ?, ?, 'cat', '', '', '', '', ?)
            """,
            (pet_id, owner_user_id, name, now_iso()),
        )


def seed_demo_data() -> None:
    init_database()
    _ensure_user(CURRENT_USER_ID, "local_owner", "本地主人")
    set_current_user_id(CURRENT_USER_ID)
    existing_pet = fetch_one("SELECT pet_id FROM pets WHERE owner_user_id = ? LIMIT 1", (CURRENT_USER_ID,))
    if existing_pet is None:
        _ensure_pet(make_id("pet"), CURRENT_USER_ID, "小猫")
