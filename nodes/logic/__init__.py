"""Node-RED-style logic nodes: Function, Expression, Switch, Delay, Counter."""
from __future__ import annotations

import textwrap
from bpy.props import StringProperty, FloatProperty, IntProperty, EnumProperty

try:
    import bpy
except Exception:  # pragma: no cover - headless tests
    bpy = None

from ...core.base import FxLogicNode
from ...core.registry import register_node
from ...core.signal import Signal
from ...core import expr


@register_node
class FunctionNode(FxLogicNode):
    """Full Python Function node, Node-RED style.

    The code runs inside a generated Python function and may import modules.
    Available names: msg, context, flow, global_context, node, engine, bpy.

    Return semantics:
      * return msg/dict  -> send downstream
      * return None      -> stop/drop
      * return [msg,...] -> send multiple messages through the same output
    """
    bl_idname = "FxFunction"
    bl_label = "Function"
    bl_icon = "SCRIPT"

    code: StringProperty(
        name="Python Code",
        default="# msg is a dict. You may import modules.\nmsg['payload'] = msg.get('payload')\nreturn msg",
        description="Legacy inline code / fallback. For multi-line editing use a Text datablock.",
    )
    code_text_name: StringProperty(
        name="Code Text",
        default="",
        description="Optional Blender Text datablock used as the multi-line source for this Function node.",
    )
    last_result: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def _code_text(self):
        if bpy is None or not self.code_text_name:
            return None
        return bpy.data.texts.get(self.code_text_name)

    def get_code(self):
        txt = self._code_text()
        if txt is not None:
            try:
                return txt.as_string()
            except Exception:
                pass
        return self.code or "return msg"

    def draw_body(self, context, layout):
        row = layout.row(align=True)
        if bpy is not None:
            row.prop_search(self, "code_text_name", bpy.data, "texts", text="Code")
        else:
            row.prop(self, "code_text_name", text="Code")
        op = row.operator("fx_nodes.function_new_text", text="", icon="ADD")
        op.node_name = self.name
        op.tree_name = self.id_data.name
        op = row.operator("fx_nodes.open_text_editor", text="", icon="TEXT")
        op.text_name = self.code_text_name

        code = self.get_code()
        preview = [ln.rstrip() for ln in code.splitlines()[:4]]
        if preview:
            box = layout.box(); box.scale_y = 0.72
            for ln in preview:
                box.label(text=(ln or " ")[:80], icon="SCRIPT")
            extra = len(code.splitlines()) - len(preview)
            if extra > 0:
                box.label(text=f"… +{extra} more lines")
        if not self.code_text_name:
            layout.prop(self, "code", text="Fallback")
        if self.last_result:
            layout.label(text=self.last_result[:60], icon="CHECKMARK")

    def _call_user_code(self, signal, engine):
        code = self.get_code()
        body = textwrap.indent(code or "return msg", "    ")
        src = "def _fx_user_function(msg, context, flow, global_context, node, engine):\n" + body
        ns = {}
        try:
            import bpy as _bpy  # type: ignore
            ns["bpy"] = _bpy
        except Exception:
            pass
        exec(src, ns, ns)  # noqa: S102 - intentionally full Python Function node
        return ns["_fx_user_function"](
            signal.msg,
            self.node_context(engine),
            self.flow_context(engine),
            self.global_context(engine),
            self,
            engine,
        )

    def process(self, signal, engine):
        try:
            result = self._call_user_code(signal, engine)
        except Exception as e:
            self._error = f"{type(e).__name__}: {e}"
            return []
        self._error = ""
        if result is None:
            self.last_result = "dropped"
            return []
        if isinstance(result, list):
            out = []
            for item in result:
                if item is None:
                    continue
                if not isinstance(item, dict):
                    raise TypeError("Function list items must be msg dict or None")
                out.append(("▶", Signal(payload=item, context=signal.context, source=signal.source,
                                         ts=signal.ts, hops=signal.hops)))
            self.last_result = f"sent {len(out)} msg(s)"
            return out
        if not isinstance(result, dict):
            raise TypeError("Function must return msg dict, list of msg dicts, or None")
        signal.payload = result
        self.last_result = "sent msg"
        return self.flow_out(signal)


@register_node
class ExpressionNode(FxLogicNode):
    """Evaluate a sandboxed expression and store it into a msg path."""
    bl_idname = "FxExpression"
    bl_label = "Expression"
    bl_icon = "DRIVER"

    expression: StringProperty(
        name="Expr",
        default="payload",
        description="安全表达式；可用 msg/payload/topic/flow/G/global_context/frame/time",
    )
    out_path: StringProperty(name="Target", default="payload")
    live_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "expression", text="")
        layout.prop(self, "out_path")
        if self.live_value:
            layout.label(text=f"{self.out_path} = {self.live_value}", icon="CHECKMARK")

    def process(self, signal, engine):
        from ...core import msgpath
        try:
            val = expr.evaluate(self.expression, self.expr_vars(signal, engine))
            msgpath.set(self.out_path, val, signal.msg, self.flow_context(engine), self.global_context(engine))
        except (expr.ExprError, msgpath.MsgPathError) as e:
            self._error = str(e)
            return []
        self.live_value = repr(val)[:32]
        self._error = ""
        return self.flow_out(signal)


@register_node
class SwitchNode(FxLogicNode):
    """Node-RED-like Switch node with a Python expression condition."""
    bl_idname = "FxSwitch"
    bl_label = "Switch"
    bl_icon = "TRIA_RIGHT"

    condition: StringProperty(name="If", default="bool(payload)")

    def init_sockets(self):
        self.add_in_flow()
        self.add_out_flow("True")
        self.add_out_flow("False")

    def draw_body(self, context, layout):
        layout.prop(self, "condition", text="if")

    def process(self, signal, engine):
        try:
            ok = bool(expr.evaluate(self.condition, self.expr_vars(signal, engine)))
        except expr.ExprError as e:
            self._error = str(e)
            return []
        self._error = ""
        return [("True" if ok else "False", signal)]


@register_node
class GateNode(FxLogicNode):
    """Once / throttle / every-N control gate."""
    bl_idname = "FxGate"
    bl_label = "Gate"
    bl_icon = "FILTER"

    mode: EnumProperty(name="Mode", items=[
        ("ONCE", "Once", "只通过一次"),
        ("THROTTLE", "Throttle", "最小间隔秒数内只通过一次"),
        ("EVERY_N", "Every N", "每 N 次通过一次"),
    ], default="THROTTLE")
    seconds: FloatProperty(name="Min Interval", default=0.5, min=0.0)
    n: IntProperty(name="N", default=2, min=1)

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "mode")
        if self.mode == "THROTTLE":
            layout.prop(self, "seconds")
        elif self.mode == "EVERY_N":
            layout.prop(self, "n")

    def process(self, signal, engine):
        st = engine.__dict__.setdefault("_gate_state", {}).setdefault(
            self.node_uid, {"last": -1e18, "count": 0, "fired": False})
        if self.mode == "ONCE":
            if st["fired"]:
                return []
            st["fired"] = True
        elif self.mode == "THROTTLE":
            now = signal.context.get("wall", signal.context.get("time", signal.ts))
            if now - st["last"] < self.seconds:
                return []
            st["last"] = now
        elif self.mode == "EVERY_N":
            st["count"] += 1
            if st["count"] % self.n != 0:
                return []
        return self.flow_out(signal)


@register_node
class CounterNode(FxLogicNode):
    """Stateful counter that writes to a msg path."""
    bl_idname = "FxCounter"
    bl_label = "Counter"
    bl_icon = "LINENUMBERS_ON"

    path: StringProperty(name="Target", default="payload")
    step: FloatProperty(name="Step", default=1.0)
    reset_at: FloatProperty(name="Wrap At (0=off)", default=0.0)

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "path"); layout.prop(self, "step"); layout.prop(self, "reset_at")

    def _state(self, engine):
        return engine.__dict__.setdefault("_counter_state", {})

    def process(self, signal, engine):
        from ...core import msgpath
        state = self._state(engine)
        val = state.get(self.node_uid, 0.0) + self.step
        if self.reset_at and val >= self.reset_at:
            val = 0.0
        state[self.node_uid] = val
        try:
            msgpath.set(self.path, val, signal.msg, self.flow_context(engine), self.global_context(engine))
        except msgpath.MsgPathError as e:
            self._error = str(e); return []
        return self.flow_out(signal)


@register_node
class DelayNode(FxLogicNode):
    """Continue downstream after N seconds without blocking Blender UI."""
    bl_idname = "FxDelay"
    bl_label = "Delay"
    bl_icon = "PREVIEW_RANGE"

    seconds: FloatProperty(name="Seconds", default=1.0, min=0.0)

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "seconds")

    def process(self, signal, engine):
        sched = getattr(engine, "schedule", None)
        if sched:
            sched(self.seconds, self.node_uid, signal.child())
            return []
        return self.flow_out(signal)
