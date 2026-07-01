"""Node-RED-style data nodes: Debug, Change, Context, Get Property, Cache."""
from __future__ import annotations

import json
from bpy.props import StringProperty, IntProperty, EnumProperty, BoolProperty

try:
    import bpy
except Exception:  # pragma: no cover - headless tests
    bpy = None

from ...core.base import FxBaseNode
from ...core.registry import register_node
from ...core import expr, msgpath
from ...core import path as blender_path

@register_node
class PropertyGetNode(FxBaseNode):
    """Read a safe Blender full data path into a msg path."""
    bl_idname = "FxPropertyGet"
    bl_label = "Get Property"
    bl_icon = "RNA"
    category = "Property"
    fx_color = (0.16, 0.40, 0.26)

    path: StringProperty(name="Blender Full Path", default="")
    out_path: StringProperty(name="Target", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "path", text="")
        layout.prop(self, "out_path")

    def draw_previews(self, context, layout):
        if self.last_value:
            box = layout.box(); box.scale_y = 0.8
            box.label(text=f"→ {self.last_value}", icon="CHECKMARK")

    def process(self, signal, engine):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            val = blender_path.get_path(self.path)
            msgpath.set(self.out_path, val, signal.msg, flow, glob)
        except (blender_path.PathError, msgpath.MsgPathError) as e:
            self._error = str(e)
            return []
        self.last_value = msgpath.compact(val, 48)
        self._error = ""
        return self.flow_out(signal)
