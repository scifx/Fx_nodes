"""Add-menu categories, built dynamically from the registry.

Uses the modern extend_menu approach (4.x) instead of the deprecated
nodeitems_utils, so new nodes appear automatically by category.
"""
from __future__ import annotations

import bpy
from bpy.types import Menu

from ..core.registry import CATEGORIES, NODE_CLASSES, ordered_categories

_CAT_ICON = {
    "Trigger": "PLAY", "Logic": "SCRIPT", "Action": "MODIFIER",
    "Data": "VIEWZOOM", "AI": "OUTLINER_OB_LIGHT", "Utility": "DOT",
}

_submenu_classes = []


def _make_submenu(cat):
    idname = f"NEXUS_MT_add_{cat.lower()}"

    def draw(self, context):
        layout = self.layout
        for bl_idname in CATEGORIES.get(cat, []):
            cls = NODE_CLASSES[bl_idname]
            op = layout.operator("node.add_node", text=cls.bl_label)
            op.type = bl_idname
            op.use_transform = True

    return type(idname, (Menu,), {
        "bl_idname": idname,
        "bl_label": cat,
        "draw": draw,
    })


class NEXUS_MT_add_root(Menu):
    bl_idname = "NEXUS_MT_add_root"
    bl_label = "NEXUS"

    def draw(self, context):
        layout = self.layout
        for cat in ordered_categories():
            layout.menu(f"NEXUS_MT_add_{cat.lower()}", icon=_CAT_ICON.get(cat, "DOT"))


def _add_menu_entry(self, context):
    if getattr(context.space_data, "tree_type", "") == "NexusNodeTree":
        self.layout.menu("NEXUS_MT_add_root", icon="NODETREE")


def register():
    global _submenu_classes
    _submenu_classes = [_make_submenu(cat) for cat in ordered_categories()]
    for c in _submenu_classes:
        bpy.utils.register_class(c)
    bpy.utils.register_class(NEXUS_MT_add_root)
    bpy.types.NODE_MT_add.append(_add_menu_entry)


def unregister():
    try:
        bpy.types.NODE_MT_add.remove(_add_menu_entry)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(NEXUS_MT_add_root)
    except Exception:
        pass
    for c in reversed(_submenu_classes):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass
    _submenu_classes.clear()
