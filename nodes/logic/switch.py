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
class SwitchNode(FxNodes):
    """Node-RED-like Switch node with a Python expression condition."""
    bl_idname = "FxSwitch"
    bl_label = "Switch"
    bl_icon = "TRIA_RIGHT"

    condition: StringProperty(
        name="If",
        default="bool(payload)",
        description="Python eval expression. Must return True or False, not just a truthy/falsy value.",
    )

    def init_sockets(self):
        self.add_in_flow()
        self.add_out_flow("True")
        self.add_out_flow("False")

    def draw_body(self, context, layout):
        layout.prop(self, "condition", text="if")

    def process(self, signal, engine):
        try:
            result = expr.evaluate(self.condition, self.expr_vars(signal, engine))
            if not isinstance(result, bool):
                raise expr.ExprError(
                    f"Switch 表达式必须返回 True 或 False；当前返回 "
                    f"{type(result).__name__}: {result!r}"
                )
        except expr.ExprError as e:
            self._error = str(e)
            return []
        self._error = ""
        return [("True" if result else "False", signal)]
