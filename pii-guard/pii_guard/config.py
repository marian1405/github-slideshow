"""Salvarea si incarcarea setarilor (cheie API, model, termeni protejati).

Setarile stau in ~/.pii-guard/config.json, doar pe calculatorul local.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".pii-guard"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "api_key": "",
    "model": "claude-opus-5",
    "confirm_before_send": True,
    "custom_terms": [],
}


def load() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def save(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)  # doar utilizatorul curent poate citi cheia
    except OSError:
        pass  # pe Windows chmod e limitat; fisierul ramane in profilul userului
