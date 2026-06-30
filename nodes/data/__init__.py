"""Node-RED-style data nodes: Debug, Change, Context, Get Property."""
from __future__ import annotations

import json
from bpy.props import StringProperty, IntProperty, EnumProperty, BoolProperty

from ...core.base import FxBaseNode
from ...core.registry import register_node
from ...core import expr, msgpath
from ...core import path as blender_path


@register_node
class DebugNode(FxBaseNode):
    """Node-RED-like Debug node.

    It previews a path from msg/flow/global. Examples: ``msg``, ``payload``,
    ``msg.payload``, ``topic``, ``flow.count``, ``global.seed``.
    """
    bl_idname = "FxDebug"
    bl_label = "Debug"
    bl_icon = "VIEWZOOM"
    category = "Data"
    fx_color = (0.32, 0.28, 0.12)

    path: StringProperty(name="Path", default="msg")
    max_rows: IntProperty(name="Max Rows", default=8, min=1, max=32)
    fire_count: IntProperty(name="Fires", default=0)
    show_context: BoolProperty(name="Show Runtime Context", default=False)

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "path")
        layout.label(text=f"Fires: {self.fire_count}", icon="DRIVER")
        raw = self.get("_preview", "{}")
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        box = layout.box()
        if isinstance(data, dict):
            if not data:
                box.label(text="(no data yet)", icon="INFO")
            for i, (k, val) in enumerate(data.items()):
                if i >= self.max_rows:
                    box.label(text=f"… +{len(data) - self.max_rows} more")
                    break
                row = box.row()
                row.label(text=str(k))
                row.label(text=str(val)[:30])
        else:
            box.label(text=str(data)[:80])
        layout.prop(self, "show_context")

    def _json_safe(self, value):
        def safe(v):
            try:
                if isinstance(v, (int, float, str, bool)) or v is None:
                    return v
                if isinstance(v, (list, tuple)):
                    return [safe(x) for x in v][:64]
                if isinstance(v, dict):
                    return {str(k): safe(x) for k, x in list(v.items())[:64]}
                return f"{type(v).__name__}({v!r})"[:160]
            except Exception:
                return "<unrepr>"
        return safe(value)

    def process(self, signal, engine):
        self.fire_count += 1
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            value = msgpath.get(self.path, signal.msg, flow, glob)
        except msgpath.MsgPathError as e:
            self._error = str(e)
            return []
        data = self._json_safe(value)
        if self.show_context:
            data = {"value": data, "context": self._json_safe(signal.context)}
        try:
            self["_preview"] = json.dumps(data, ensure_ascii=False)
        except Exception:
            self["_preview"] = json.dumps(repr(value)[:160], ensure_ascii=False)
        self._error = ""
        return self.flow_out(signal)


@register_node
class ChangeNode(FxBaseNode):
    """Node-RED-like Change node for msg/flow/global paths."""
    bl_idname = "FxChange"
    bl_label = "Change"
    bl_icon = "RNA"
    category = "Data"
    fx_color = (0.24, 0.30, 0.16)

    mode: EnumProperty(name="Mode", items=[
        ("SET", "Set", "Set a msg/flow/global property"),
        ("DELETE", "Delete", "Delete a msg/flow/global property"),
        ("MOVE", "Move", "Move a property to another path"),
    ], default="SET")
    path: StringProperty(name="Path", default="payload")
    value_expr: StringProperty(name="Value Expr", default="payload")
    to_path: StringProperty(name="To Path", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "mode", text="")
        layout.prop(self, "path")
        if self.mode == "SET":
            layout.prop(self, "value_expr")
        elif self.mode == "MOVE":
            layout.prop(self, "to_path")
        if self.last_value:
            layout.label(text=self.last_value[:60], icon="CHECKMARK")

    def process(self, signal, engine):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            if self.mode == "SET":
                val = expr.evaluate(self.value_expr, self.expr_vars(signal, engine))
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


@register_node
class ContextNode(FxBaseNode):
    """Explicit Node-RED context helper.

    Change can already operate on flow/global paths.  This node is a more
    discoverable shorthand for common context operations.
    """
    bl_idname = "FxContext"
    bl_label = "Context"
    bl_icon = "WORLD"
    category = "Data"
    fx_color = (0.22, 0.24, 0.34)

    mode: EnumProperty(name="Mode", items=[
        ("FLOW_TO_MSG", "Flow → Msg", "Read flow context into msg"),
        ("MSG_TO_FLOW", "Msg → Flow", "Write msg/expression into flow context"),
        ("GLOBAL_TO_MSG", "Global → Msg", "Read global context into msg"),
        ("MSG_TO_GLOBAL", "Msg → Global", "Write msg/expression into global context"),
    ], default="GLOBAL_TO_MSG")
    context_key: StringProperty(name="Context Key", default="value")
    msg_path: StringProperty(name="Msg Path", default="payload")
    value_expr: StringProperty(name="Value Expr", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "mode", text="")
        layout.prop(self, "context_key")
        layout.prop(self, "msg_path")
        if self.mode in {"MSG_TO_FLOW", "MSG_TO_GLOBAL"}:
            layout.prop(self, "value_expr")
        if self.last_value:
            layout.label(text=self.last_value[:60], icon="CHECKMARK")

    def process(self, signal, engine):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            if self.mode == "FLOW_TO_MSG":
                val = flow.get(self.context_key)
                msgpath.set(self.msg_path, val, signal.msg, flow, glob)
            elif self.mode == "GLOBAL_TO_MSG":
                val = glob.get(self.context_key)
                msgpath.set(self.msg_path, val, signal.msg, flow, glob)
            elif self.mode == "MSG_TO_FLOW":
                val = expr.evaluate(self.value_expr, self.expr_vars(signal, engine))
                flow[self.context_key] = val
            elif self.mode == "MSG_TO_GLOBAL":
                val = expr.evaluate(self.value_expr, self.expr_vars(signal, engine))
                glob[self.context_key] = val
            self.last_value = msgpath.compact(val, 50)
        except (expr.ExprError, msgpath.MsgPathError) as e:
            self._error = str(e)
            return []
        self._error = ""
        return self.flow_out(signal)


@register_node
class PropertyGetNode(FxBaseNode):
    """Read a safe Blender full data path into a msg path."""
    bl_idname = "FxPropertyGet"
    bl_label = "Get Property"
    bl_icon = "RNA"
    category = "Data"
    fx_color = (0.24, 0.30, 0.16)

    path: StringProperty(name="Blender Full Path", default="")
    out_path: StringProperty(name="Store To", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "path", text="")
        layout.prop(self, "out_path")
        if self.last_value:
            layout.label(text=f"{self.out_path} = {self.last_value}", icon="CHECKMARK")

    def process(self, signal, engine):
        try:
            value = blender_path.get_path(self.path)
            msgpath.set(self.out_path, value, signal.msg, self.flow_context(engine), self.global_context(engine))
        except (blender_path.PathError, msgpath.MsgPathError) as e:
            self._error = str(e)
            return []
        self.last_value = repr(value)[:48]
        self._error = ""
        return self.flow_out(signal)
