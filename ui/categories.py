"""Add-menu categories, built dynamically from the registry.

Inside an FxNodeTree the Add menu should not contain an extra "Fx Nodes" root:
the user is already in the Fx Nodes editor.  We therefore expose category
submenus directly: Trigger / Logic / Action / Data / AI / Utility.
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
    safe = "".join(ch if ch.isalnum() else "_" for ch in cat.lower())
    idname = f"FXNODES_MT_add_{safe}"

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


def _add_menu_entry(self, context):
    if getattr(context.space_data, "tree_type", "") != "FxNodeTree":
        return
    layout = self.layout
    layout.separator()
    for c in _submenu_classes:
        layout.menu(c.bl_idname, icon=_CAT_ICON.get(c.bl_label, "DOT"))


def register():
    global _submenu_classes
    _submenu_classes = [_make_submenu(cat) for cat in ordered_categories()]
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
