from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ..database import execute, fetch_all, fetch_one
from ..schemas import CatVoiceAnnotation, TrainingCandidateReview
from ..services.cat_voice_model_service import (
    DEBUG_MODEL_NOTICE,
    GENERAL_SAFETY_MESSAGE,
    copy_audio_for_test,
    display_label_for,
    get_model_status,
    predict_cat_voice,
    save_uploaded_audio,
)
from ..services.current_user_service import require_current_user_id
from ..services.imu_service import imu_status
from ..services.storage_service import make_id, now_iso
from ..services.training_label_service import normalize_user_label


router = APIRouter(prefix="/smart-tools", tags=["smart-tools"])


@router.get("/status")
def smart_tool_status() -> dict:
    cat_voice = get_model_status()
    return {
        "backend": "real_model" if cat_voice["available"] else "unavailable",
        "model_connected": cat_voice["available"],
        "cat_voice": cat_voice,
        "browser_recording": {
            "available": True,
            "status": "frontend_media_recorder",
        },
        "imu": imu_status(),
    }


def _find_demo_audio_sample() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    sample_dir = project_root / "data" / "processed" / "mono_16k_ref"
    if not sample_dir.exists():
        raise HTTPException(status_code=404, detail="Demo sample audio directory not found")
    samples = sorted(path for path in sample_dir.rglob("*.wav") if path.is_file())
    if not samples:
        raise HTTPException(status_code=404, detail="Demo sample audio not found")
    return samples[0]


def _get_owned_pet(pet_id: str, user_id: str) -> dict:
    pet = fetch_one("SELECT * FROM pets WHERE pet_id = ?", (pet_id,))
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    if pet.get("owner_user_id") != user_id:
        raise HTTPException(status_code=403, detail="Cannot use another user's pet")
    return pet


def _get_owned_recognition(recognition_id: str, user_id: str) -> dict:
    row = fetch_one("SELECT * FROM recognition_records WHERE recognition_id = ?", (recognition_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Recognition record not found")
    if row.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Cannot access another user's recognition record")
    return row


def _format_training_candidate(candidate: dict | None, recognition: dict | None = None) -> dict | None:
    if candidate is None:
        return None
    output = dict(candidate)
    output.setdefault("uploaded_audio_path", output.get("audio_path", ""))
    output.setdefault("model_predicted_label", output.get("prediction_label", ""))
    output.setdefault("user_feedback", output.get("user_notes", ""))
    output.setdefault("training_status", "training_ready" if output.get("review_status") == "training_ready" else "not_promoted")
    output.setdefault("review_required", output.get("review_status") != "training_ready")
    if recognition is not None:
        output.setdefault("model_confidence", float(recognition.get("confidence") or 0.0))
    return output


@router.post("/cat-voice/predict")
def cat_voice_predict(
    request: Request,
    pet_id: str = Form(...),
    audio_file: UploadFile = File(...),
) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    _get_owned_pet(pet_id, user_id)

    upload_path = save_uploaded_audio(audio_file)
    result = predict_cat_voice(str(upload_path))
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error") or "Cat voice prediction failed")

    recognition_id = make_id("recognition")
    execute(
        """
        INSERT INTO recognition_records (
            recognition_id, pet_id, user_id, audio_path, original_filename,
            prediction_label, display_label, confidence, margin, trigger,
            warning, user_label, user_notes, notes, saved_to_timeline,
            created_post_id, added_to_training_candidates, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '', 0, '', 0, ?)
        """,
        (
            recognition_id,
            pet_id,
            user_id,
            str(upload_path),
            audio_file.filename or "",
            result.get("prediction_label", ""),
            result.get("display_label", ""),
            float(result.get("confidence", 0.0)),
            float(result.get("margin", 0.0)),
            1 if result.get("trigger") else 0,
            result.get("warning", ""),
            now_iso(),
        ),
    )
    model_status = get_model_status()
    safety_message = result.get("safety_message") or result.get("warning") or GENERAL_SAFETY_MESSAGE
    return {
        "recognition_id": recognition_id,
        "pet_id": pet_id,
        "audio_path": str(upload_path),
        "upload_path": str(upload_path),
        "predicted_label": result.get("prediction_label", ""),
        "label": result.get("prediction_label", ""),
        "model_version": result.get("model_version") or result.get("model_type", ""),
        "model_dir": model_status.get("model_dir") or model_status.get("model_path", ""),
        "debug_notice": result.get("debug_notice") or DEBUG_MODEL_NOTICE,
        "safety_message": safety_message,
        **result,
    }


@router.post("/cat-voice/demo-sample-predict")
def cat_voice_demo_sample_predict(payload: dict, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    pet_id = str(payload.get("pet_id") or "").strip()
    if not pet_id:
        raise HTTPException(status_code=400, detail="pet_id is required")
    _get_owned_pet(pet_id, user_id)

    source_path = _find_demo_audio_sample()
    upload_path = copy_audio_for_test(source_path)
    result = predict_cat_voice(str(upload_path))
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error") or "Cat voice demo prediction failed")

    recognition_id = make_id("recognition")
    notes = f"source=round8_5_demo; readonly_sample={source_path.name}"
    execute(
        """
        INSERT INTO recognition_records (
            recognition_id, pet_id, user_id, audio_path, original_filename,
            prediction_label, display_label, confidence, margin, trigger,
            warning, user_label, user_notes, notes, saved_to_timeline,
            created_post_id, added_to_training_candidates, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, 0, '', 0, ?)
        """,
        (
            recognition_id,
            pet_id,
            user_id,
            str(upload_path),
            source_path.name,
            result.get("prediction_label", ""),
            result.get("display_label", ""),
            float(result.get("confidence", 0.0)),
            float(result.get("margin", 0.0)),
            1 if result.get("trigger") else 0,
            result.get("warning", ""),
            notes,
            now_iso(),
        ),
    )
    model_status = get_model_status()
    safety_message = result.get("safety_message") or result.get("warning") or GENERAL_SAFETY_MESSAGE
    return {
        "recognition_id": recognition_id,
        "pet_id": pet_id,
        "audio_path": str(upload_path),
        "upload_path": str(upload_path),
        "sample_source_path": str(source_path),
        "source": "round8_5_demo",
        "predicted_label": result.get("prediction_label", ""),
        "label": result.get("prediction_label", ""),
        "model_version": result.get("model_version") or result.get("model_type", ""),
        "model_dir": model_status.get("model_dir") or model_status.get("model_path", ""),
        "debug_notice": result.get("debug_notice") or DEBUG_MODEL_NOTICE,
        "safety_message": safety_message,
        **result,
    }


@router.post("/cat-voice/{recognition_id}/annotate")
def annotate_cat_voice(recognition_id: str, payload: CatVoiceAnnotation, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    _get_owned_recognition(recognition_id, user_id)
    user_label = payload.user_label.strip()
    if not user_label:
        raise HTTPException(status_code=400, detail="User label is required")
    standard_label = normalize_user_label(user_label)
    if not standard_label:
        raise HTTPException(status_code=400, detail="Unsupported user label")
    execute(
        "UPDATE recognition_records SET user_label = ?, user_notes = ?, notes = ? WHERE recognition_id = ?",
        (user_label, payload.user_notes.strip(), payload.user_notes.strip(), recognition_id),
    )
    execute(
        """
        UPDATE training_candidates_web
        SET user_label = ?, standard_label = ?, user_notes = ?
        WHERE recognition_id = ? AND user_id = ?
        """,
        (user_label, standard_label, payload.user_notes.strip(), recognition_id, user_id),
    )
    return fetch_one("SELECT * FROM recognition_records WHERE recognition_id = ?", (recognition_id,)) or {"recognition_id": recognition_id}


@router.post("/cat-voice/{recognition_id}/save-to-timeline")
def save_cat_voice_to_timeline(recognition_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    row = _get_owned_recognition(recognition_id, user_id)
    existing = fetch_one(
        """
        SELECT * FROM pet_timeline
        WHERE pet_id = ? AND related_recognition_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (row.get("pet_id", ""), recognition_id),
    )
    if existing is not None:
        execute("UPDATE recognition_records SET saved_to_timeline = 1 WHERE recognition_id = ?", (recognition_id,))
        return {
            "ok": True,
            "timeline_id": existing["timeline_id"],
            "recognition_id": recognition_id,
            "saved_to_timeline": True,
            "already_saved": True,
        }
    timeline_id = make_id("timeline")
    label = row.get("display_label") or display_label_for(row.get("prediction_label", ""))
    user_label = (row.get("user_label") or "").strip()
    warning = row.get("warning") or ""
    title = "猫叫识别记录"
    review_note = f"；用户标注：{user_label}" if user_label else ""
    safety = warning or GENERAL_SAFETY_MESSAGE
    content = (
        f"本次音频状态倾向：{label}；置信度 {float(row.get('confidence') or 0):.2f}{review_note}。"
        f"{safety} {DEBUG_MODEL_NOTICE}"
    ).strip()
    execute(
        """
        INSERT INTO pet_timeline (timeline_id, pet_id, event_type, title, content, related_post_id, related_recognition_id, created_at)
        VALUES (?, ?, 'cat_voice_recognition', ?, ?, '', ?, ?)
        """,
        (timeline_id, row.get("pet_id", ""), title, content, recognition_id, now_iso()),
    )
    execute("UPDATE recognition_records SET saved_to_timeline = 1 WHERE recognition_id = ?", (recognition_id,))
    return {
        "ok": True,
        "timeline_id": timeline_id,
        "recognition_id": recognition_id,
        "saved_to_timeline": True,
    }


@router.post("/cat-voice/{recognition_id}/add-to-training-candidates")
def add_cat_voice_to_training_candidates(recognition_id: str, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    row = _get_owned_recognition(recognition_id, user_id)
    user_label = (row.get("user_label") or "").strip()
    if not user_label:
        raise HTTPException(status_code=400, detail="User label is required before adding a training candidate")
    standard_label = normalize_user_label(user_label)
    if not standard_label:
        raise HTTPException(status_code=400, detail="Unsupported user label")
    existing = fetch_one(
        "SELECT * FROM training_candidates_web WHERE recognition_id = ? AND user_id = ?",
        (recognition_id, user_id),
    )
    if existing is None:
        candidate_id = make_id("candidate")
        execute(
            """
            INSERT INTO training_candidates_web (
                candidate_id, recognition_id, pet_id, user_id, audio_path,
                prediction_label, user_label, standard_label, user_notes, quality_status,
                review_status, source, reviewed_at, promoted_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'candidate', 'web_user_annotation', '', '', ?)
            """,
            (
                candidate_id,
                recognition_id,
                row.get("pet_id", ""),
                user_id,
                row.get("audio_path", ""),
                row.get("prediction_label", ""),
                user_label,
                standard_label,
                row.get("user_notes", "") or row.get("notes", ""),
                now_iso(),
            ),
        )
        candidate = fetch_one("SELECT * FROM training_candidates_web WHERE candidate_id = ?", (candidate_id,))
    else:
        execute(
            """
            UPDATE training_candidates_web
            SET user_label = ?, standard_label = ?, user_notes = ?
            WHERE candidate_id = ?
            """,
            (user_label, standard_label, row.get("user_notes", "") or row.get("notes", ""), existing["candidate_id"]),
        )
        candidate = fetch_one("SELECT * FROM training_candidates_web WHERE candidate_id = ?", (existing["candidate_id"],))
    execute("UPDATE recognition_records SET added_to_training_candidates = 1 WHERE recognition_id = ?", (recognition_id,))
    return {
        "ok": True,
        "recognition_id": recognition_id,
        "added_to_training_candidates": True,
        "candidate": _format_training_candidate(candidate, row),
    }


@router.get("/cat-voice/records")
def list_cat_voice_records(request: Request, pet_id: str = "") -> list[dict]:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    if pet_id:
        _get_owned_pet(pet_id, user_id)
        return fetch_all(
            "SELECT * FROM recognition_records WHERE user_id = ? AND pet_id = ? ORDER BY created_at DESC",
            (user_id, pet_id),
        )
    return fetch_all(
        "SELECT * FROM recognition_records WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    )


@router.get("/cat-voice/training-candidates")
def list_cat_voice_training_candidates(
    request: Request,
    pet_id: str = "",
    review_status: str = "",
    quality_status: str = "",
    standard_label: str = "",
) -> list[dict]:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    clauses = ["user_id = ?"]
    params: list[str] = [user_id]
    if pet_id:
        _get_owned_pet(pet_id, user_id)
        clauses.append("pet_id = ?")
        params.append(pet_id)
    if review_status:
        clauses.append("review_status = ?")
        params.append(review_status)
    if quality_status:
        clauses.append("quality_status = ?")
        params.append(quality_status)
    if standard_label:
        clauses.append("standard_label = ?")
        params.append(standard_label)
    query = f"SELECT * FROM training_candidates_web WHERE {' AND '.join(clauses)} ORDER BY created_at DESC"
    candidates = fetch_all(query, tuple(params))
    return [_format_training_candidate(candidate) or candidate for candidate in candidates]


@router.post("/cat-voice/training-candidates/{candidate_id}/review")
def review_cat_voice_training_candidate(candidate_id: str, payload: TrainingCandidateReview, request: Request) -> dict:
    user_id = require_current_user_id(request, allow_legacy_fallback=False)
    quality_status = payload.quality_status.strip()
    review_status = payload.review_status.strip()
    if quality_status not in {"accepted", "rejected", "needs_review", "pending"}:
        raise HTTPException(status_code=400, detail="Unsupported quality_status")
    if review_status not in {"training_ready", "excluded", "candidate"}:
        raise HTTPException(status_code=400, detail="Unsupported review_status")
    candidate = fetch_one("SELECT * FROM training_candidates_web WHERE candidate_id = ?", (candidate_id,))
    if candidate is None:
        raise HTTPException(status_code=404, detail="Training candidate not found")
    if candidate.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Cannot review another user's training candidate")
    reviewed_at = now_iso()
    promoted_at = reviewed_at if quality_status == "accepted" and review_status == "training_ready" else (candidate.get("promoted_at") or "")
    execute(
        """
        UPDATE training_candidates_web
        SET quality_status = ?, review_status = ?, reviewed_at = ?, promoted_at = ?
        WHERE candidate_id = ?
        """,
        (quality_status, review_status, reviewed_at, promoted_at, candidate_id),
    )
    return fetch_one("SELECT * FROM training_candidates_web WHERE candidate_id = ?", (candidate_id,)) or {"candidate_id": candidate_id}
