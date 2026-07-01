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
    category = "Property"
    fx_color = (0.16, 0.40, 0.26)

    path: StringProperty(name="Blender Full Path", default="")
    value_expr: StringProperty(name="Value Expr", default="payload")
    value_text_name: StringProperty(
        name="Value Text",
        default="",
        description="Optional Blender Text datablock for multiline Value Expr.",
    )
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def get_value_expr(self):
        return self.get_text_content("value_text_name", "value_expr")

    def draw_body(self, context, layout):
        layout.prop(self, "path", text="")
        self.draw_text_row(layout, "value_text_name", "value_expr", label="Expr", prefix="Fx Set Value")

    def draw_previews(self, context, layout):
        if self.last_value:
            box = layout.box(); box.scale_y = 0.8
            box.label(text=f"← {self.last_value}", icon="CHECKMARK")

    def process(self, signal, engine):
        try:
            current = blender_path.get_path(self.path)
            variables = self.expr_vars(signal, engine)
            variables["current"] = current
            variables["old"] = current
            value = expr.evaluate(self.get_value_expr(), variables)
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
