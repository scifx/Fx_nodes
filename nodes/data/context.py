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
class ContextNode(FxBaseNode):
    """Explicit Node-RED context helper.

    Change can already operate on flow/global paths.  This node is a more
    discoverable shorthand for common context operations.
    """
    bl_idname = "FxContext"
    bl_label = "Context"
    bl_icon = "WORLD"
    category = "Data"
    fx_color = (0.15, 0.36, 0.40)

    mode: EnumProperty(name="Mode", items=[
        ("FLOW_TO_MSG", "Flow → Msg", "Read flow context into msg"),
        ("MSG_TO_FLOW", "Msg → Flow", "Write msg/expression into flow context"),
        ("GLOBAL_TO_MSG", "Global → Msg", "Read global context into msg"),
        ("MSG_TO_GLOBAL", "Msg → Global", "Write msg/expression into global context"),
        ("RUNTIME_TO_MSG", "Runtime → Msg", "Read runtime signal.context value, such as frame/time/fps/wall, into msg"),
        ("MSG_TO_RUNTIME", "Msg → Runtime", "Write expression result into signal.context for downstream nodes"),
    ], default="GLOBAL_TO_MSG")
    context_key: StringProperty(name="Context Key", default="value")
    msg_path: StringProperty(name="Message Property", default="payload")
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
        layout.prop(self, "mode", text="")
        layout.prop(self, "context_key")
        layout.prop(self, "msg_path")
        if self.mode in {"MSG_TO_FLOW", "MSG_TO_GLOBAL", "MSG_TO_RUNTIME"}:
            self.draw_text_row(layout, "value_text_name", "value_expr", label="Expr", prefix="Fx Context")

    def draw_previews(self, context, layout):
        if self.last_value:
            box = layout.box(); box.scale_y = 0.8
            box.label(text=self.last_value[:60], icon="CHECKMARK")

    def _ctx_path(self, root, key):
        """Return a msgpath-compatible path for a context key.

        Users often type either ``foo`` or ``Global.foo``/``flow.foo``.  Treat
        simple keys as belonging to the selected context root, but preserve an
        explicit root when provided.  This also enables nested paths such as
        ``settings.seed`` instead of only top-level ``dict.get`` keys.
        """
        k = (key or "").strip()
        if not k:
            raise msgpath.MsgPathError("context key is empty")
        kl = k.lower()
        if root == "global":
            if kl == "global" or kl.startswith("global.") or kl.startswith("global[") or k == "G" or k.startswith("G.") or k.startswith("G["):
                return k
        elif root == "flow":
            if kl == "flow" or kl.startswith("flow.") or kl.startswith("flow["):
                return k
        return f"{root}.{k}"

    def _runtime_path(self, key):
        k = (key or "").strip()
        if not k:
            raise msgpath.MsgPathError("runtime context key is empty")
        if k == "context":
            raise msgpath.MsgPathError("cannot replace runtime context root")
        if k.startswith("context."):
            k = k[len("context."):]
        elif k.startswith("context["):
            k = k[len("context"):]
        return k

    def _runtime_get(self, signal, key):
        sentinel = object()
        path = self._runtime_path(key)
        val = msgpath.get(path, signal.context, default=sentinel)
        if val is sentinel:
            raise msgpath.MsgPathError(f"runtime context key not found: {key}")
        return val

    def _runtime_set(self, signal, key, value):
        path = self._runtime_path(key)
        return msgpath.set(path, value, signal.context)

    def _context_get(self, root, key, signal, flow, glob):
        sentinel = object()
        path = self._ctx_path(root, key)
        val = msgpath.get(path, signal.msg, flow, glob, default=sentinel)
        if val is sentinel:
            raise msgpath.MsgPathError(f"{root} context key not found: {key}")
        return val

    def _context_set(self, root, key, value, signal, flow, glob):
        return msgpath.set(self._ctx_path(root, key), value, signal.msg, flow, glob)

    def process(self, signal, engine):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            if self.mode == "FLOW_TO_MSG":
                val = self._context_get("flow", self.context_key, signal, flow, glob)
                msgpath.set(self.msg_path, val, signal.msg, flow, glob)
            elif self.mode == "GLOBAL_TO_MSG":
                val = self._context_get("global", self.context_key, signal, flow, glob)
                msgpath.set(self.msg_path, val, signal.msg, flow, glob)
            elif self.mode == "RUNTIME_TO_MSG":
                val = self._runtime_get(signal, self.context_key)
                msgpath.set(self.msg_path, val, signal.msg, flow, glob)
            elif self.mode == "MSG_TO_FLOW":
                val = expr.evaluate(self.get_value_expr(), self.expr_vars(signal, engine))
                self._context_set("flow", self.context_key, val, signal, flow, glob)
            elif self.mode == "MSG_TO_GLOBAL":
                val = expr.evaluate(self.get_value_expr(), self.expr_vars(signal, engine))
                self._context_set("global", self.context_key, val, signal, flow, glob)
            elif self.mode == "MSG_TO_RUNTIME":
                val = expr.evaluate(self.get_value_expr(), self.expr_vars(signal, engine))
                self._runtime_set(signal, self.context_key, val)
            self.last_value = msgpath.compact(val, 50)
        except (expr.ExprError, msgpath.MsgPathError) as e:
            self._error = str(e)
            return []
        self._error = ""
        return self.flow_out(signal)
