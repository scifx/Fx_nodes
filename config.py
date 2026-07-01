"""Small JSON configuration layer for Fx Nodes.

Users can copy ``config.default.json`` to ``config.local.json`` and edit colors
or AI defaults without changing Python code.  Blender Add-on Preferences still
win at runtime, so API keys can stay outside version-controlled files.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_DEFAULT = _ROOT / "config.default.json"
_LOCAL = _ROOT / "config.local.json"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        data = json.loads(_DEFAULT.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    try:
        if _LOCAL.exists():
            data = _deep_merge(data, json.loads(_LOCAL.read_text(encoding="utf-8")))
    except Exception:
        # Config errors should not prevent the add-on from loading.
        pass
    return data


def reload_config() -> dict[str, Any]:
    get_config.cache_clear()
    return get_config()


def _get(path: str, default=None):
    cur: Any = get_config()
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def get_ai_default(key: str, default: str = "") -> str:
    value = _get(f"ai.{key}", default)
    return value if isinstance(value, str) else default


def _as_color(value, fallback):
    try:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return tuple(float(x) for x in value[:3])
    except Exception:
        pass
    return fallback


def get_node_color(node_or_cls, fallback=(0.25, 0.25, 0.28)):
    cls = node_or_cls if isinstance(node_or_cls, type) else node_or_cls.__class__
    bl_idname = getattr(cls, "bl_idname", "")
    category = getattr(cls, "category", "Utility")
    by_node = _get(f"ui.node_colors.{bl_idname}")
    if by_node is not None:
        return _as_color(by_node, fallback)
    by_cat = _get(f"ui.category_colors.{category}")
    return _as_color(by_cat, fallback)


def get_category_icon(label: str) -> str:
    return _get(f"ui.category_icons.{label}", "DOT")
