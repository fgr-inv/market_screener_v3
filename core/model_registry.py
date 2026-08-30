from pathlib import Path
from datetime import datetime, timezone
import json

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / 'data' / 'model'
MODEL_DIR.mkdir(parents=True, exist_ok=True)
REGISTRY = MODEL_DIR / 'model_registry.json'

DEFAULT_MODEL = {
    'name': 'Opportunity Model',
    'version': '8.0.0',
    'effective_date': '2026-08-24',
    'weights': {
        'quality': 0.18,
        'trend': 0.16,
        'entry': 0.22,
        'relative_strength': 0.12,
        'sector': 0.08,
        'macro': 0.08,
        'revisions': 0.10,
        'valuation': 0.06,
    },
    'notes': 'V8 production hardening: missing-aware scoring, coverage gating, persistent alert state and portfolio risk contribution.'
}


def ensure_registry():
    if not REGISTRY.exists():
        REGISTRY.write_text(json.dumps({'models': [DEFAULT_MODEL]}, indent=2), encoding='utf-8')
    return REGISTRY


def get_active_model():
    ensure_registry()
    data = json.loads(REGISTRY.read_text(encoding='utf-8'))
    models = data.get('models') or [DEFAULT_MODEL]
    return models[-1]


def register_model(version, weights, notes=''):
    ensure_registry()
    data = json.loads(REGISTRY.read_text(encoding='utf-8'))
    models = data.setdefault('models', [])
    models.append({
        'name': 'Opportunity Model',
        'version': str(version),
        'effective_date': datetime.now(timezone.utc).date().isoformat(),
        'weights': weights,
        'notes': notes,
    })
    REGISTRY.write_text(json.dumps(data, indent=2), encoding='utf-8')


def model_label():
    m = get_active_model()
    return f"{m.get('name','Model')} v{m.get('version','?')}"
