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
class ChangeNode(FxBaseNode):
    """Node-RED-like Change node for msg/flow/global paths."""
    bl_idname = "FxChange"
    bl_label = "Change"
    bl_icon = "RNA"
    category = "Data"
    fx_color = (0.15, 0.36, 0.40)

    mode: EnumProperty(name="Mode", items=[
        ("SET", "Set", "Set a msg/flow/global property"),
        ("DELETE", "Delete", "Delete a msg/flow/global property"),
        ("MOVE", "Move", "Move a property to another path"),
    ], default="SET")
    path: StringProperty(name="Property", default="payload")
    value_expr: StringProperty(name="Value Expr", default="payload")
    value_text_name: StringProperty(
        name="Value Text",
        default="",
        description="Optional Blender Text datablock for multiline Value Expr.",
    )
    to_path: StringProperty(name="To", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def get_value_expr(self):
        return self.get_text_content("value_text_name", "value_expr")

    def draw_body(self, context, layout):
        layout.prop(self, "mode", text="")
        layout.prop(self, "path")
        if self.mode == "SET":
            self.draw_text_row(layout, "value_text_name", "value_expr", label="Expr", prefix="Fx Change Value")
        elif self.mode == "MOVE":
            layout.prop(self, "to_path")

    def draw_previews(self, context, layout):
        if self.mode == "SET" and getattr(self, "value_text_name", ""):
            expr_str = self.get_value_expr()
            if expr_str:
                box = layout.box(); box.scale_y = 0.8
                box.label(text="Value Expr Preview:", icon="DRIVER")
                for ln in expr_str.splitlines()[:3]:
                    box.label(text=(ln or " ")[:80])
        if self.last_value:
            box = layout.box(); box.scale_y = 0.8
            box.label(text=self.last_value[:60], icon="CHECKMARK")

    def process(self, signal, engine):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            if self.mode == "SET":
                val = expr.evaluate(self.get_value_expr(), self.expr_vars(signal, engine))
                msgpath.set(self.path, val, signal.msg, flow, glob)
                self.last_value = f"{self.path} = {msgpath.compact(val, 40)}"
            elif self.mode == "DELETE":
                msgpath.delete(self.path, signal.msg, flow, glob)
                self.last_value = f"deleted {self.path}"
            elif self.mode == "MOVE":
                val = msgpath.get(self.path, signal.msg, flow, glob)
                msgpath.set(self.to_path, val, signal.msg, flow, glob)
                msgpath.delete(self.path, signal.msg, flow, glob)
                self.last_value = f"{self.path} → {self.to_path}"
        except (expr.ExprError, msgpath.MsgPathError) as e:
            self._error = str(e)
            return []
        self._error = ""
        return self.flow_out(signal)
