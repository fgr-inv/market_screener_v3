
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "model" / "model_registry.json"
REGISTRY.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_MODEL = {
    "name": "Opportunity Model",
    "version": "8.0.0",
    "effective_date": "2026-08-24",
    "status": "production",
    "description": "Missing-aware multi-factor opportunity model",
    "weights": {
        "quality": 0.18,
        "trend": 0.16,
        "entry": 0.22,
        "relative_strength": 0.12,
        "sector": 0.08,
        "macro": 0.08,
        "revisions": 0.10,
        "valuation": 0.06,
    },
    "notes": "V8 production hardening.",
}

def _ensure():
    if not REGISTRY.exists():
        REGISTRY.write_text(json.dumps({"models": [DEFAULT_MODEL]}, indent=2), encoding="utf-8")

def load_registry():
    _ensure()
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        models = data.get("models", [])
        if not models:
            models = [DEFAULT_MODEL]
        return {"models": models}
    except Exception:
        return {"models": [DEFAULT_MODEL]}

def save_registry(reg):
    REGISTRY.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")

def active_model():
    reg = load_registry()
    return reg["models"][-1]

def register_model(version, status, description, weights, notes=""):
    reg = load_registry()
    reg["models"].append({
        "name": "Opportunity Model",
        "version": str(version),
        "effective_date": datetime.now(timezone.utc).date().isoformat(),
        "status": status,
        "description": description,
        "weights": weights,
        "notes": notes,
    })
    save_registry(reg)

def registry_frame():
    reg = load_registry()
    rows = []
    for m in reg["models"]:
        rows.append({
            "Model": m.get("name", "Opportunity Model"),
            "Version": m.get("version", "N/A"),
            "Status": m.get("status", "production"),
            "Updated": m.get("effective_date", "N/A"),
            "Description": m.get("description") or m.get("notes") or "",
        })
    return pd.DataFrame(rows)

def weight_frame(model=None):
    m = model or active_model()
    weights = m.get("weights", {})
    return pd.DataFrame([
        {
            "Factor": str(k).replace("_", " ").title(),
            "Weight": float(v),
            "Weight %": f"{float(v)*100:.0f}%",
        }
        for k, v in weights.items()
    ])

def validate_weights(weights):
    total = sum(float(v) for v in weights.values())
    return {
        "total": total,
        "valid": abs(total - 1.0) < 1e-6,
    }
