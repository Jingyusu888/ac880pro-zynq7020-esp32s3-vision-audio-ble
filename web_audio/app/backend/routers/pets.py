from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..database import execute, fetch_all, fetch_one
from ..schemas import PetCreate, PetUpdate
from ..services.current_user_service import require_current_user_id
from ..services.storage_service import make_id, now_iso


router = APIRouter(prefix="/pets", tags=["pets"])


@router.get("")
def list_pets(request: Request, owner_user_id: str = "") -> list[dict]:
    current_user_id = require_current_user_id(request, allow_legacy_fallback=False)
    if owner_user_id and owner_user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Cannot view another user's private pet list")
    owner_user_id = current_user_id
    return fetch_all(
        """
        SELECT
            p.*,
            COALESCE(u.display_name, p.owner_user_id) AS owner_name,
            COALESCE(u.bio, '') AS owner_bio,
            COALESCE(stats.recognition_count, 0) AS recognition_count
        FROM pets p
        LEFT JOIN users u ON u.user_id = p.owner_user_id
        LEFT JOIN (
            SELECT pet_id, COUNT(*) AS recognition_count
            FROM recognition_records
            GROUP BY pet_id
        ) stats ON stats.pet_id = p.pet_id
        WHERE p.owner_user_id = ?
        ORDER BY p.created_at ASC
        """,
        (owner_user_id,),
    )


def _get_owned_pet_for_request(pet_id: str, request: Request) -> dict:
    current_user_id = require_current_user_id(request, allow_legacy_fallback=False)
    pet = fetch_one("SELECT * FROM pets WHERE pet_id = ?", (pet_id,))
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    if pet.get("owner_user_id") != current_user_id:
        raise HTTPException(status_code=403, detail="Cannot view another user's pet timeline")
    return pet


@router.get("/{pet_id}/timeline")
def list_pet_timeline(pet_id: str, request: Request, limit: int = 50) -> list[dict]:
    pet = _get_owned_pet_for_request(pet_id, request)
    bounded_limit = min(max(limit, 1), 100)
    rows = fetch_all(
        """
        SELECT
            t.*,
            r.user_id AS recognition_user_id,
            r.audio_path,
            r.original_filename,
            r.prediction_label,
            r.display_label AS recognition_display_label,
            r.confidence,
            r.margin,
            r.trigger,
            r.warning,
            r.user_label,
            r.user_notes
        FROM pet_timeline t
        LEFT JOIN recognition_records r ON r.recognition_id = t.related_recognition_id
        WHERE t.pet_id = ?
        ORDER BY t.created_at DESC
        LIMIT ?
        """,
        (pet_id, bounded_limit),
    )
    for row in rows:
        row["pet_name"] = pet.get("name", "")
        row["effective_label"] = row.get("user_label") or row.get("prediction_label") or ""
        row["debug_notice"] = "b0_v5 为雏形级模型，不是正式泛化模型。"
        row["safety_message"] = row.get("warning") or "识别结果仅供行为观察参考，不能替代兽医判断。"
    return rows


@router.get("/{pet_id}")
def get_pet(pet_id: str) -> dict:
    row = fetch_one(
        """
        SELECT
            p.*,
            COALESCE(u.display_name, p.owner_user_id) AS owner_name,
            COALESCE(u.bio, '') AS owner_bio,
            COALESCE(stats.recognition_count, 0) AS recognition_count
        FROM pets p
        LEFT JOIN users u ON u.user_id = p.owner_user_id
        LEFT JOIN (
            SELECT pet_id, COUNT(*) AS recognition_count
            FROM recognition_records
            GROUP BY pet_id
        ) stats ON stats.pet_id = p.pet_id
        WHERE p.pet_id = ?
        """,
        (pet_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    return row


@router.post("")
def create_pet(payload: PetCreate, request: Request) -> dict:
    owner_user_id = require_current_user_id(request, allow_legacy_fallback=False)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Pet name is required")
    pet_id = make_id("pet")
    execute(
        """
        INSERT INTO pets (pet_id, owner_user_id, name, species, breed, age, avatar, bio, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pet_id,
            owner_user_id,
            payload.name.strip(),
            payload.species or "cat",
            payload.breed,
            payload.age,
            payload.avatar,
            payload.bio,
            now_iso(),
        ),
    )
    return fetch_one("SELECT * FROM pets WHERE pet_id = ?", (pet_id,)) or {"pet_id": pet_id}


@router.put("/{pet_id}")
def update_pet(pet_id: str, payload: PetUpdate, request: Request) -> dict:
    current_user_id = require_current_user_id(request, allow_legacy_fallback=False)
    pet = fetch_one("SELECT * FROM pets WHERE pet_id = ?", (pet_id,))
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    if pet["owner_user_id"] != current_user_id:
        raise HTTPException(status_code=403, detail="Cannot edit another user's pet")
    execute(
        """
        UPDATE pets
        SET name = ?, species = ?, breed = ?, age = ?, avatar = ?, bio = ?
        WHERE pet_id = ?
        """,
        (
            payload.name.strip() or pet["name"],
            payload.species or pet["species"],
            payload.breed if payload.breed != "" else pet["breed"],
            payload.age if payload.age != "" else pet["age"],
            payload.avatar if payload.avatar != "" else pet["avatar"],
            payload.bio if payload.bio != "" else pet["bio"],
            pet_id,
        ),
    )
    return fetch_one("SELECT * FROM pets WHERE pet_id = ?", (pet_id,)) or {"pet_id": pet_id}
