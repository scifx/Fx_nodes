"""Node-RED-style logic nodes: Function, Expression, Switch, Delay, Counter."""
from __future__ import annotations

import textwrap
from bpy.props import StringProperty, FloatProperty, IntProperty, EnumProperty

try:
    import bpy
except Exception:  # pragma: no cover - headless tests
    bpy = None

from ...core.base import FxNodes
from ...core.registry import register_node
from ...core.signal import Signal
from ...core import expr

@register_node
class ExpressionNode(FxNodes):
    """Evaluate a sandboxed expression and store it into a msg path."""
    bl_idname = "FxExpression"
    bl_label = "Expression"
    bl_icon = "DRIVER"
    category = "Script"
    fx_color = (0.22, 0.35, 0.52)

    expression: StringProperty(
        name="Expr",
        default="payload",
        description="安全表达式；可用 msg/payload/topic/flow/Global/G/global_context/frame/time",
    )
    expr_text_name: StringProperty(
        name="Expr Text",
        default="",
        description="Optional Blender Text datablock for multi-line expression.",
    )
    out_path: StringProperty(name="Target", default="payload")
    live_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def get_expression(self):
        return self.get_text_content("expr_text_name", "expression")

    def draw_body(self, context, layout):
        self.draw_text_row(layout, "expr_text_name", "expression", label="Expr", prefix="Fx Expr")
        layout.prop(self, "out_path")

    def draw_previews(self, context, layout):
        expr_str = self.get_expression()
        if getattr(self, "expr_text_name", "") and expr_str:
            box = layout.box(); box.scale_y = 0.8
            box.label(text="Expr Preview:", icon="DRIVER")
            for ln in expr_str.splitlines()[:4]:
                box.label(text=(ln or " ")[:80])
            if len(expr_str.splitlines()) > 4:
                box.label(text=f"… +{len(expr_str.splitlines()) - 4} more lines")
        if self.live_value:
            box = layout.box(); box.scale_y = 0.8
            box.label(text=f"→ {self.out_path} = {self.live_value}", icon="CHECKMARK")

    def process(self, signal, engine):
        from ...core import msgpath
        try:
            val = expr.evaluate(self.get_expression(), self.expr_vars(signal, engine))
            msgpath.set(self.out_path, val, signal.msg, self.flow_context(engine), self.global_context(engine))
        except (expr.ExprError, msgpath.MsgPathError) as e:
            self._error = str(e)
            return []
        self.live_value = repr(val)[:32]
        self._error = ""
        return self.flow_out(signal)
