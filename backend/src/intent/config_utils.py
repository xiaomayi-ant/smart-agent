from __future__ import annotations

import os
import json
from typing import Any, Callable, Dict, Optional
from dotenv import dotenv_values


def _load_config_json(base_dir: str) -> Dict[str, Any]:
    path = os.path.join(base_dir, "config.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _load_env_file(base_dir: str) -> Dict[str, Any]:
    env_path = os.path.join(base_dir, ".env")
    try:
        return dict(dotenv_values(env_path)) if os.path.exists(env_path) else {}
    except Exception:
        return {}


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    return s in ("1", "true", "yes", "on")


def get_config(
    base_dir: str,
    defaults: Dict[str, Any],
    casters: Optional[Dict[str, Callable[[Any], Any]]] = None,
) -> Dict[str, Any]:
    """Merge defaults <- config.json <- .env, then apply casters.

    - base_dir: directory containing config.json and optional .env
    - defaults: mapping of expected keys to default values
    - casters: optional per-key functions to convert final values to desired types
    """
    cfg_file = _load_config_json(base_dir)
    cfg_env = _load_env_file(base_dir)

    out: Dict[str, Any] = {}
    for key, default_val in defaults.items():
        if key in cfg_env:
            out[key] = cfg_env[key]
        elif key in cfg_file:
            out[key] = cfg_file[key]
        else:
            out[key] = default_val

    if casters:
        for key, caster in casters.items():
            if key in out:
                try:
                    out[key] = caster(out[key])
                except Exception:
                    # Keep original value on cast failure
                    pass

    return out 