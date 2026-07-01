"""Central registry for node classes, sockets and add-menu paths.

Every node uses ``@register_node`` so the rest of the system (Blender class
registration, add menu, inspector, examples) discovers it automatically.  Drop a
Python module under ``nodes/`` and decorate a subclass: no core/UI edits needed.

Folder paths are the default UI menu paths.  For example:

    nodes/property/set_property.py  ->  Property / Set Property
    nodes/custom/demo/echo.py       ->  Custom / Demo / Echo

A node may override that by setting ``menu_path = ("Some", "Path")``.
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Type

# bl_idname -> class
NODE_CLASSES: Dict[str, type] = {}
SOCKET_CLASSES: Dict[str, type] = {}
# Legacy/simple category label -> list of bl_idname (in insertion order)
CATEGORIES: Dict[str, List[str]] = {}
# bl_idname -> tuple of submenu labels, derived from nodes/<folders>/module.py
NODE_MENU_PATHS: Dict[str, Tuple[str, ...]] = {}

# Default top-level display order.  Custom/unknown folders follow alphabetically.
CATEGORY_ORDER = ["Trigger", "Property", "Logic", "Script", "Data", "Debug", "AI", "Utility", "Custom"]
_SEGMENT_LABELS = {
    "ai": "AI",
    "llm": "LLM",
    "ui": "UI",
    "trigger": "Trigger",
    "triggers": "Trigger",
    "property": "Property",
    "properties": "Property",
    "logic": "Logic",
    "script": "Script",
    "data": "Data",
    "debug": "Debug",
    "utility": "Utility",
    "custom": "Custom",
}


def _label_from_segment(seg: str) -> str:
    seg = (seg or "").strip("_")
    if not seg:
        return "Utility"
    low = seg.lower()
    if low in _SEGMENT_LABELS:
        return _SEGMENT_LABELS[low]
    return " ".join(part.capitalize() for part in low.replace("-", "_").split("_") if part)


def _derive_menu_path(cls: Type) -> Tuple[str, ...]:
    explicit = getattr(cls, "menu_path", None)
    if explicit:
        if isinstance(explicit, str):
            return tuple(p.strip() for p in explicit.replace("/", ".").split(".") if p.strip())
        return tuple(str(p).strip() for p in explicit if str(p).strip())

    module = getattr(cls, "__module__", "")
    parts = module.split(".")
    if "nodes" in parts:
        i = parts.index("nodes")
        # Use folders after nodes and before the final module filename.
        folders = parts[i + 1:-1]
        if folders:
            return tuple(_label_from_segment(p) for p in folders)

    cat = getattr(cls, "category", "Utility") or "Utility"
    return (str(cat),)


def register_node(cls: Type) -> Type:
    """Class decorator: collect a node class into the registry."""
    idname = getattr(cls, "bl_idname", None)
    if not idname:
        raise ValueError(f"{cls.__name__} 缺少 bl_idname")

    NODE_CLASSES[idname] = cls

    menu_path = _derive_menu_path(cls) or (getattr(cls, "category", "Utility") or "Utility",)
    NODE_MENU_PATHS[idname] = menu_path

    # Keep category on the class consistent with the folder-derived root.  This
    # lets panels/tests that still read cls.category follow the generated menu.
    try:
        cls.category = menu_path[0]
    except Exception:
        pass

    items = CATEGORIES.setdefault(menu_path[0], [])
    if idname not in items:
        items.append(idname)
    return cls


def register_socket(cls: Type) -> Type:
    idname = getattr(cls, "bl_idname", None)
    if not idname:
        raise ValueError(f"{cls.__name__} 缺少 bl_idname")
    SOCKET_CLASSES[idname] = cls
    return cls


def all_node_classes() -> List[type]:
    return list(NODE_CLASSES.values())


def all_socket_classes() -> List[type]:
    return list(SOCKET_CLASSES.values())


def _path_sort_key(path: Tuple[str, ...]):
    root = path[0] if path else "Utility"
    return (CATEGORY_ORDER.index(root) if root in CATEGORY_ORDER else 99, path)


def ordered_categories() -> List[str]:
    cats = list(CATEGORIES.keys())
    cats.sort(key=lambda c: (CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99, c))
    return cats


def ordered_menu_paths() -> List[Tuple[str, ...]]:
    paths = sorted(set(NODE_MENU_PATHS.values()), key=_path_sort_key)
    return paths


def clear() -> None:
    """Used by tests to reset state between runs."""
    NODE_CLASSES.clear()
    SOCKET_CLASSES.clear()
    CATEGORIES.clear()
    NODE_MENU_PATHS.clear()
