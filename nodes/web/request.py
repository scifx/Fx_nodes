"""Example custom node.

Copy this file or drop your own modules under nodes/custom (or any folder under
nodes). The auto-loader imports it; @register_node adds it to Blender's Add menu
based on this folder path: Custom / Echo.
"""
from __future__ import annotations

from bpy.props import StringProperty

from ...core.base import FxNodes
from ...core.registry import register_node
import requests as req

@register_node
class CustomEchoNode(FxNodes):
    bl_idname = "FxRequest"
    bl_label = "Request"
    bl_icon = "CONSOLE"
    fx_color = (0.28, 0.28, 0.36)

    message: StringProperty(name="url", default="https://scifx.github.io")

    def init_sockets(self):
        self.add_in_flow()
        self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "message")

    def process(self, signal, engine):
        # Unified API: msg is a plain dict. Use msg["payload"], not msg.payload.
        
        signal.msg["payload"] = req.get(self.message).text
        return self.flow_out(signal)
