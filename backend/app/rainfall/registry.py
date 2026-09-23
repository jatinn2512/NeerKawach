"""Central rainfall-source registry; JSON keeps configuration dependency-free."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "config" / "rainfall_sources.json"


def load_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload.get("sources"), dict) or not isinstance(payload.get("default_quantitative_priority"), list):
        raise ValueError("rainfall source registry has an invalid schema")
    return payload


def source_config(source_id: str) -> dict[str, Any]:
    source = load_registry()["sources"].get(source_id)
    if not isinstance(source, dict):
        raise KeyError(source_id)
    return {"source_id": source_id, **source}
