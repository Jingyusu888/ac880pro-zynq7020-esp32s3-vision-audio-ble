from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ...config import DATA_DIR


REGISTRY_SCHEMA_VERSION = "imu_model_registry_v1"
RULE_BASED_MODEL_ID = "rule_based_v1"
RF_CANDIDATE_MODEL_ID = "imu_rf_candidate_v1"


def get_registry_path() -> Path:
    return DATA_DIR / "imu" / "models" / "imu_model_registry.json"


def ensure_model_registry() -> dict[str, Any]:
    path = get_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        registry = _default_registry()
        save_model_registry(registry)
        return registry
    registry = load_model_registry()
    changed = _ensure_default_model(registry)
    warnings = validate_registry_safety(registry)
    registry["safety_warnings"] = warnings
    if changed:
        save_model_registry(registry)
    return registry


def load_model_registry() -> dict[str, Any]:
    path = get_registry_path()
    if not path.exists():
        return ensure_model_registry()
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail=f"IMU model registry is invalid JSON: {error}") from error
    if not isinstance(registry, dict):
        raise HTTPException(status_code=500, detail="IMU model registry must be a JSON object")
    _ensure_default_model(registry)
    registry["safety_warnings"] = validate_registry_safety(registry)
    return registry


def save_model_registry(registry: dict[str, Any]) -> dict[str, Any]:
    registry = dict(registry)
    registry["schema_version"] = REGISTRY_SCHEMA_VERSION
    registry["active_model"] = RULE_BASED_MODEL_ID
    registry["updated_at"] = _now_iso()
    _ensure_default_model(registry)
    warnings = validate_registry_safety(registry)
    registry["safety_warnings"] = warnings
    path = get_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return registry


def get_active_imu_model() -> dict[str, Any]:
    registry = ensure_model_registry()
    active_model_id = registry.get("active_model") or RULE_BASED_MODEL_ID
    active = _find_model(registry, active_model_id)
    if active is None:
        raise HTTPException(status_code=500, detail="Active IMU model is missing from registry")
    return {
        "status": "ok",
        "active_model": active,
        "active_model_id": active_model_id,
        "hardware_connected": False,
        "safety_warnings": validate_registry_safety(registry),
    }


def list_imu_models() -> dict[str, Any]:
    registry = ensure_model_registry()
    return {
        "status": "ok",
        "schema_version": registry.get("schema_version", REGISTRY_SCHEMA_VERSION),
        "active_model": registry.get("active_model", RULE_BASED_MODEL_ID),
        "models": registry.get("models", []),
        "hardware_connected": False,
        "safety_warnings": validate_registry_safety(registry),
    }


def register_candidate_from_report(
    model_id: str,
    model_path: str,
    report_path: str,
    feature_schema_path: str,
    notes: str | None = None,
) -> dict[str, Any]:
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")
    if model_id == RULE_BASED_MODEL_ID:
        raise HTTPException(status_code=400, detail="Cannot register rule_based_v1 as a candidate")
    if not report_path:
        raise HTTPException(status_code=400, detail="report_path is required")
    if not feature_schema_path:
        raise HTTPException(status_code=400, detail="feature_schema_path is required")

    registry = ensure_model_registry()
    report_abs = _resolve_web_app_path(report_path)
    feature_schema_abs = _resolve_web_app_path(feature_schema_path)
    model_abs = _resolve_web_app_path(model_path) if model_path else None

    if not report_abs.exists():
        raise HTTPException(status_code=400, detail="Candidate report file does not exist")
    if not feature_schema_abs.exists():
        raise HTTPException(status_code=400, detail="Candidate feature schema file does not exist")

    report = _load_json(report_abs, "Candidate report")
    deployability = report.get("deployability") if isinstance(report.get("deployability"), dict) else {}
    insufficient = bool(report.get("insufficient_training_data") or deployability.get("insufficient_training_data"))
    data_scope = str(report.get("data_scope") or deployability.get("data_scope") or "unknown")
    accuracy = _metric_value(report.get("accuracy"), report.get("candidate_metrics", {}).get("accuracy") if isinstance(report.get("candidate_metrics"), dict) else None)
    macro_f1 = _metric_value(report.get("macro_f1"), report.get("candidate_metrics", {}).get("macro_f1") if isinstance(report.get("candidate_metrics"), dict) else None)
    model_exists = bool(model_abs and model_abs.exists())

    status = "candidate"
    if insufficient:
        status = "not_available_insufficient_data"
    elif not model_exists:
        status = "not_available_missing_model"

    deployable_for_demo = bool(deployability.get("deployable_for_demo")) and status == "candidate"
    if insufficient or accuracy is None or macro_f1 is None or accuracy < 0.70 or macro_f1 < 0.70:
        deployable_for_demo = False

    deployable_for_real_hardware = False
    candidate = {
        "model_id": model_id,
        "type": "random_forest" if "rf" in model_id or "forest" in model_id else "candidate_model",
        "status": status,
        "source": data_scope,
        "path": _normalize_relative_path(model_path) if model_path else None,
        "report_path": _normalize_relative_path(report_path),
        "feature_schema_path": _normalize_relative_path(feature_schema_path),
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "data_scope": data_scope,
        "insufficient_training_data": insufficient,
        "deployable_for_demo": deployable_for_demo,
        "deployable_for_real_hardware": deployable_for_real_hardware,
        "candidate_model_only": True,
        "hardware_connected": False,
        "trained_on_simulated_data": data_scope in {
            "simulated_only",
            "engineering_assumption_only",
            "human_annotated_simulated",
            "mixed_simulated_and_human_annotated",
            "engineering_assumption",
            "simulated",
        },
        "auto_activate": False,
        "registered_at": _now_iso(),
        "notes": notes or _candidate_default_notes(status),
    }

    models = [model for model in registry.get("models", []) if model.get("model_id") != model_id]
    models.append(candidate)
    registry["models"] = models
    registry["active_model"] = RULE_BASED_MODEL_ID
    registry = save_model_registry(registry)

    registered = _find_model(registry, model_id) or candidate
    return {
        "status": "registered" if registered["status"] == "candidate" else "registered_not_deployable",
        "model": registered,
        "active_model": registry.get("active_model", RULE_BASED_MODEL_ID),
        "hardware_connected": False,
        "safety_warnings": validate_registry_safety(registry),
        "message": _candidate_default_notes(registered["status"]),
    }


def validate_registry_safety(registry: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    models = registry.get("models", [])
    if not isinstance(models, list):
        return ["registry models must be a list"]

    model_ids = [str(model.get("model_id") or "") for model in models]
    active_model = str(registry.get("active_model") or "")
    if active_model not in model_ids:
        warnings.append("active_model is missing from registry models")
    if RULE_BASED_MODEL_ID not in model_ids:
        warnings.append("rule_based_v1 is missing from registry models")

    active_status_models = [model for model in models if model.get("status") == "active"]
    if len(active_status_models) != 1:
        warnings.append("registry should contain exactly one model with status=active")
    if active_model != RULE_BASED_MODEL_ID:
        warnings.append("active_model is not rule_based_v1; C8 should not switch active models")

    for model in models:
        model_id = str(model.get("model_id") or "")
        status = str(model.get("status") or "")
        data_scope = str(model.get("data_scope") or model.get("source") or "")
        if data_scope in {"simulated_only", "engineering_assumption_only", "human_annotated_simulated", "mixed_simulated_and_human_annotated", "engineering_assumption"}:
            if model.get("deployable_for_real_hardware") is True:
                warnings.append(f"{model_id} must not be deployable for real hardware")
        if status == "candidate" and model.get("candidate_model_only") is not True:
            warnings.append(f"{model_id} candidate must set candidate_model_only=true")
        if status == "candidate" and model_id == active_model:
            warnings.append(f"{model_id} is a candidate but is also active")
        if status == "candidate" and model.get("auto_activate") is True:
            warnings.append(f"{model_id} candidate must not auto-activate")
        if model.get("insufficient_training_data") and model.get("deployable_for_demo"):
            warnings.append(f"{model_id} has insufficient data but deployable_for_demo=true")
    return warnings


def _default_registry() -> dict[str, Any]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "active_model": RULE_BASED_MODEL_ID,
        "updated_at": _now_iso(),
        "models": [_default_rule_model()],
        "safety_warnings": [],
    }


def _default_rule_model() -> dict[str, Any]:
    return {
        "model_id": RULE_BASED_MODEL_ID,
        "type": "rule_based",
        "status": "active",
        "source": "engineering_assumption",
        "path": None,
        "report_path": None,
        "feature_schema_path": None,
        "deployable_for_demo": True,
        "deployable_for_real_hardware": False,
        "candidate_model_only": False,
        "notes": "Default rule-based IMU motion classifier. Does not require trained model file.",
    }


def _ensure_default_model(registry: dict[str, Any]) -> bool:
    changed = False
    registry.setdefault("schema_version", REGISTRY_SCHEMA_VERSION)
    if registry.get("active_model") != RULE_BASED_MODEL_ID:
        registry["active_model"] = RULE_BASED_MODEL_ID
        changed = True
    models = registry.setdefault("models", [])
    if not isinstance(models, list):
        registry["models"] = []
        models = registry["models"]
        changed = True
    default = _find_model(registry, RULE_BASED_MODEL_ID)
    if default is None:
        models.insert(0, _default_rule_model())
        changed = True
    else:
        for key, value in _default_rule_model().items():
            if default.get(key) != value:
                default[key] = value
                changed = True
    for model in models:
        if model.get("model_id") != RULE_BASED_MODEL_ID and model.get("status") == "active":
            model["status"] = "candidate"
            model["candidate_model_only"] = True
            changed = True
    return changed


def _find_model(registry: dict[str, Any], model_id: str) -> dict[str, Any] | None:
    for model in registry.get("models", []):
        if model.get("model_id") == model_id:
            return model
    return None


def _resolve_web_app_path(path_value: str) -> Path:
    path = Path(str(path_value or ""))
    if path.is_absolute():
        return path
    return DATA_DIR.parent / str(path_value).replace("/", "\\")


def _normalize_relative_path(path_value: str) -> str:
    path = Path(str(path_value or ""))
    if path.is_absolute():
        try:
            return str(path.relative_to(DATA_DIR.parent)).replace("\\", "/")
        except ValueError:
            return str(path)
    return str(path_value).replace("\\", "/")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail=f"{label} is invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=f"{label} must be a JSON object")
    return payload


def _metric_value(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            continue
    return None


def _candidate_default_notes(status: str) -> str:
    if status == "candidate":
        return "Candidate model registered for review only. It is not active and is not real-hardware validated."
    if status == "not_available_insufficient_data":
        return "C7 report marked insufficient_training_data=true; candidate model is not available or deployable."
    if status == "not_available_missing_model":
        return "Model file is missing; candidate cannot be used for inference."
    return "Candidate model metadata recorded without active model switching."


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
