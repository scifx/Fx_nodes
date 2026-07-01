"""Add-menu categories generated from ``nodes/`` folder paths.

Inside an FxNodeTree the Add menu exposes category submenus directly.  Node menu
paths come from ``core.registry.NODE_MENU_PATHS``; those are derived by
``@register_node`` from the node module's folder path unless the class sets an
explicit ``menu_path``.
"""
from __future__ import annotations

import bpy
from bpy.types import Menu

from ..core.registry import NODE_CLASSES, NODE_MENU_PATHS, CATEGORY_ORDER
from ..config import get_category_icon

_submenu_classes = []
_MENU_TREE = {}


def _sort_key(label: str):
    return (CATEGORY_ORDER.index(label) if label in CATEGORY_ORDER else 99, label)


def _safe_id(parts):
    raw = "_".join(parts).lower()
    return "".join(ch if ch.isalnum() else "_" for ch in raw)


def _build_tree():
    tree = {}
    for bl_idname, cls in NODE_CLASSES.items():
        path = NODE_MENU_PATHS.get(bl_idname) or (getattr(cls, "category", "Utility"),)
        children = tree
        entry = None
        for part in path:
            entry = children.setdefault(part, {"_nodes": {}, "_children": {}})
            children = entry["_children"]
        if entry is not None:
            entry["_nodes"][bl_idname] = cls.bl_label
    return tree


def _node_at_path(tree, path):
    cur = tree
    for part in path:
        cur = cur[part]
        if part != path[-1]:
            cur = cur["_children"]
    return cur


def _make_submenu(path):
    idname = f"FXNODES_MT_add_{_safe_id(path)}"
    label = path[-1]

    def draw(self, context):
        layout = self.layout
        entry = _node_at_path(_MENU_TREE, path)
        children = entry["_children"]
        for child_label in sorted(children.keys(), key=_sort_key):
            child_path = (*path, child_label)
            layout.menu(f"FXNODES_MT_add_{_safe_id(child_path)}", icon=get_category_icon(child_label))
        if children and entry["_nodes"]:
            layout.separator()
        for bl_idname in sorted(entry["_nodes"].keys(), key=lambda bid: NODE_CLASSES[bid].bl_label):
            cls = NODE_CLASSES[bl_idname]
            op = layout.operator("node.add_node", text=cls.bl_label, icon=getattr(cls, "bl_icon", "NONE"))
            op.type = bl_idname
            op.use_transform = True

    return type(idname, (Menu,), {
        "bl_idname": idname,
        "bl_label": label,
        "draw": draw,
    })


def _walk_paths(tree, prefix=()):
    for label in sorted(tree.keys(), key=_sort_key):
        path = (*prefix, label)
        yield path
        yield from _walk_paths(tree[label]["_children"], path)


def _add_menu_entry(self, context):
    if getattr(context.space_data, "tree_type", "") != "FxNodeTree":
        return
    layout = self.layout
    layout.separator()
    for label in sorted(_MENU_TREE.keys(), key=_sort_key):
        layout.menu(f"FXNODES_MT_add_{_safe_id((label,))}", icon=get_category_icon(label))


def register():
    global _submenu_classes, _MENU_TREE
    _MENU_TREE = _build_tree()
    _submenu_classes = [_make_submenu(path) for path in _walk_paths(_MENU_TREE)]
    for c in _submenu_classes:
        bpy.utils.register_class(c)
    bpy.types.NODE_MT_add.append(_add_menu_entry)


def unregister():
    try:
        bpy.types.NODE_MT_add.remove(_add_menu_entry)
    except Exception:
        pass
    for c in reversed(_submenu_classes):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass
    _submenu_classes.clear()
    _MENU_TREE.clear()
