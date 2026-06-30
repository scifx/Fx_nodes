"""Central registry for node classes, sockets and add-menu categories.

Every node uses ``@register_node`` so the rest of the system (add menu,
inspector, examples) discovers it automatically. This is what makes the
addon "extend with zero core changes": drop a subclass, decorate it, done.

The registry itself is bpy-free; the actual ``bpy.utils.register_class`` call
is done by the package ``register()`` using the lists collected here.
"""
from __future__ import annotations

from typing import Dict, List, Type

# bl_idname -> class
NODE_CLASSES: Dict[str, type] = {}
SOCKET_CLASSES: Dict[str, type] = {}
# category label -> list of bl_idname (insertion order preserved)
CATEGORIES: Dict[str, List[str]] = {}

# fixed display order of categories in the add menu
CATEGORY_ORDER = ["Trigger", "Logic", "Action", "Data", "AI", "Utility"]


def register_node(cls: Type) -> Type:
    """Class decorator: collect a node class into the registry."""
    idname = getattr(cls, "bl_idname", None)
    if not idname:
        raise ValueError(f"{cls.__name__} 缺少 bl_idname")
    # During Blender script reloads modules may be imported more than once.
    # Keep the registry idempotent so add menus don't accumulate duplicates.
    old = NODE_CLASSES.get(idname)
    NODE_CLASSES[idname] = cls
    cat = getattr(cls, "category", "Utility")
    items = CATEGORIES.setdefault(cat, [])
    if old is None and idname not in items:
        items.append(idname)
    elif idname not in items:
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


def ordered_categories() -> List[str]:
    cats = list(CATEGORIES.keys())
    cats.sort(key=lambda c: (CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99, c))
    return cats


def clear() -> None:
    """Used by tests to reset state between runs."""
    NODE_CLASSES.clear()
    SOCKET_CLASSES.clear()
    CATEGORIES.clear()
