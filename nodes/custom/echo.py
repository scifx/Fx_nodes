"""Example custom node.

Copy this file or drop your own modules under nodes/custom (or any folder under
nodes). The auto-loader imports it; @register_node adds it to Blender's Add menu
based on this folder path: Custom / Echo.
"""
from __future__ import annotations

from bpy.props import StringProperty

from ...core.base import FxNodes
from ...core.registry import register_node


@register_node
class CustomEchoNode(FxNodes):
    bl_idname = "FxCustomEcho"
    bl_label = "Custom Echo"
    bl_icon = "CONSOLE"
    fx_color = (0.28, 0.28, 0.36)

    message: StringProperty(name="Message", default="hello from custom node")

    def init_sockets(self):
        self.add_in_flow()
        self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "message")

    def process(self, signal, engine):
        # Unified API: msg is a plain dict. Use msg["payload"], not msg.payload.
        signal.msg["payload"] = self.message
        return self.flow_out(signal)
