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

try:
    import bpy  # type: ignore
except Exception:  # pragma: no cover - enables headless unit tests/imports
    import types as _types

    bpy = _types.ModuleType("bpy")

    class _Prop:
        def __init__(self, **kw):
            self.kw = kw

    def _prop_factory(name):
        return lambda **kw: _Prop(name=name, **kw)

    _props = _types.ModuleType("bpy.props")
    for _p in [
        "FloatProperty", "IntProperty", "StringProperty", "BoolProperty",
        "EnumProperty", "FloatVectorProperty", "PointerProperty",
    ]:
        setattr(_props, _p, _prop_factory(_p))

    class _Base:
        def __init_subclass__(cls, **kw):
            super().__init_subclass__(**kw)

    _types_mod = _types.ModuleType("bpy.types")
    for _t in [
        "Node", "NodeSocket", "NodeTree", "Operator", "Panel", "Menu",
        "AddonPreferences", "Object",
    ]:
        setattr(_types_mod, _t, type(_t, (_Base,), {}))
    _types_mod.NODE_MT_add = _types.SimpleNamespace(append=lambda f: None, remove=lambda f: None)

    _app = _types.ModuleType("bpy.app")
    _handlers = _types.ModuleType("bpy.app.handlers")
    for _h in [
        "frame_change_post", "depsgraph_update_post", "render_pre",
        "render_post", "save_post", "load_post",
    ]:
        setattr(_handlers, _h, [])
    _app.handlers = _handlers
    _app.timers = _types.SimpleNamespace(
        register=lambda *a, **k: None,
        unregister=lambda *a, **k: None,
        is_registered=lambda *a, **k: False,
    )

    bpy.props = _props
    bpy.types = _types_mod
    bpy.app = _app
    bpy.utils = _types.SimpleNamespace(register_class=lambda c: None, unregister_class=lambda c: None)
    bpy.data = _types.SimpleNamespace(node_groups=[], texts={})
    bpy.context = _types.SimpleNamespace()
    bpy.ops = _types.SimpleNamespace()
    sys.modules.setdefault("bpy", bpy)
    sys.modules.setdefault("bpy.props", _props)
    sys.modules.setdefault("bpy.types", _types_mod)
    sys.modules.setdefault("bpy.app", _app)
    sys.modules.setdefault("bpy.app.handlers", _handlers)

from . import prefs as _prefs
from .core import registry
from .ui import sockets as _sockets
from .ui import node_tree as _node_tree
from .ui import panels as _panels
from .ui import categories as _categories
from . import operators as _operators

# importing .nodes recursively loads every node module under nodes/ and
# populates registry.NODE_CLASSES through @register_node.
from . import nodes as _nodes            # noqa: F401

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
    # Default UX: the engine starts ON.  The N-panel Start/Stop button remains
    # the global master switch; when stopped, Runtime.fire_node refuses all flow.
    try:
        from .core.runtime import RUNTIME
        RUNTIME.start()
    except Exception:
        pass


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
