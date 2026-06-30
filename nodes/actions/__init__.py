"""Action nodes: Blender property side effects, Node-RED style."""
from __future__ import annotations

from bpy.props import StringProperty

from ...core.base import FxActionNode
from ...core.registry import register_node
from ...core import expr
from ...core import path as blender_path


@register_node
class PropertySetNode(FxActionNode):
    """Set a safe Blender full data path from a Python-style expression.

    Expressions can read Node-RED names: msg, payload, topic, flow,
    global_context/G, context values, plus current/old property value.
    """
    bl_idname = "FxPropertySet"
    bl_label = "Set Property"
    bl_icon = "RNA"
    category = "Action"
    fx_color = (0.18, 0.34, 0.24)

    path: StringProperty(name="Blender Full Path", default="")
    value_expr: StringProperty(name="Value Expr", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "path", text="")
        layout.prop(self, "value_expr")
        if self.last_value:
            layout.label(text=f"← {self.last_value}", icon="CHECKMARK")

    def process(self, signal, engine):
        try:
            current = blender_path.get_path(self.path)
            variables = self.expr_vars(signal, engine)
            variables["current"] = current
            variables["old"] = current
            value = expr.evaluate(self.value_expr, variables)
            blender_path.set_path(self.path, value)
        except (blender_path.PathError, expr.ExprError) as e:
            self._error = str(e)
            return []
        except Exception as e:
            self._error = f"设置失败: {e}"
            return []
        signal.msg["payload"] = value
        self.last_value = repr(value)[:48]
        self._error = ""
        return self.flow_out(signal)
