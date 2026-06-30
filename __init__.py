"""Fx Nodes — an event-driven scripting/expression node system for Blender.

Registration order matters:
  1. sockets   (nodes reference socket bl_idnames)
  2. node tree (nodes poll against it)
  3. import node modules (populates the registry via @register_node)
  4. node classes
  5. operators, prefs, panels
  6. add-menu categories (built from the now-populated registry)
"""
bl_info = {
    "name": "Fx Nodes",
    "author": "Arena.ai Agent",
    "version": (0, 1, 0),
    "blender": (4, 3, 0),
    "location": "Node Editor > Fx Nodes",
    "description": "Event-driven scripting node system: triggers, expressions, data preview, AI.",
    "category": "Node",
}

import importlib
import sys

import bpy

from . import prefs as _prefs
from .core import registry
from .ui import sockets as _sockets
from .ui import node_tree as _node_tree
from .ui import panels as _panels
from .ui import categories as _categories
from . import operators as _operators

# importing these populates registry.NODE_CLASSES through @register_node
from .nodes import triggers as _t        # noqa: F401
from .nodes import logic as _l           # noqa: F401
from .nodes import actions as _a         # noqa: F401
from .nodes import data as _d            # noqa: F401
from .nodes import ai as _ai             # noqa: F401

_BASE_CLASSES = [
    _prefs.FxPreferences,
    _node_tree.FxNodeTree,
]


def _registered_lists():
    return (
        registry.all_socket_classes(),
        _BASE_CLASSES,
        registry.all_node_classes(),
        _operators.CLASSES,
        _panels.CLASSES,
    )


def register():
    # 1. sockets
    for c in registry.all_socket_classes():
        bpy.utils.register_class(c)
    # 2. prefs + node tree
    for c in _BASE_CLASSES:
        bpy.utils.register_class(c)
    # 3. node classes
    for c in registry.all_node_classes():
        bpy.utils.register_class(c)
    # 4. operators
    for c in _operators.CLASSES:
        bpy.utils.register_class(c)
    # 5. panels
    for c in _panels.CLASSES:
        bpy.utils.register_class(c)
    # 6. add menu + shortcuts
    _categories.register()
    _operators.register_keymaps()


def unregister():
    # stop engine + clean handlers first
    try:
        from .core.runtime import RUNTIME
        RUNTIME.stop()
    except Exception:
        pass

    _operators.unregister_keymaps()
    _categories.unregister()
    for c in reversed(_panels.CLASSES):
        _safe_unreg(c)
    for c in reversed(_operators.CLASSES):
        _safe_unreg(c)
    for c in reversed(registry.all_node_classes()):
        _safe_unreg(c)
    for c in reversed(_BASE_CLASSES):
        _safe_unreg(c)
    for c in reversed(registry.all_socket_classes()):
        _safe_unreg(c)


def _safe_unreg(c):
    try:
        bpy.utils.unregister_class(c)
    except Exception:
        pass


if __name__ == "__main__":
    register()
