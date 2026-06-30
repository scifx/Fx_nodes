"""Logic nodes: expressions, branching, gates, math, counters, delay."""
from __future__ import annotations

import bpy
from bpy.props import StringProperty, FloatProperty, IntProperty, EnumProperty, BoolProperty

from ...core.base import NexusLogicNode
from ...core.registry import register_node
from ...core import expr


@register_node
class ExpressionNode(NexusLogicNode):
    """脚本表达式节点 —— 系统的灵魂。

    在沙箱里求值一个表达式。可用变量：上游 payload 的所有键 + frame/time/dt。
    结果写入 payload[out_key] 并继续向下流。表达式输出也可被 pull-读取。
    """
    bl_idname = "NexusExpression"
    bl_label = "Expression"
    bl_icon = "SCRIPT"

    expression: StringProperty(name="Expr", default="sin(time) * 2",
                               description="安全沙箱表达式，例如 sin(time)*amp")
    out_key: StringProperty(name="Store As", default="result")
    live_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow()
        self.add_in("NexusNumberSocket", "amp", 1.0)
        self.add_out_flow()
        self.add_out("NexusDataSocket", "result")

    def draw_body(self, context, layout):
        layout.prop(self, "expression", text="")
        layout.prop(self, "out_key")
        if self.live_value:
            layout.label(text=f"= {self.live_value}", icon="CHECKMARK")

    def _vars(self, signal, engine):
        v = dict(signal.payload)
        v.update(signal.context)
        # expose connected value sockets by socket name
        for s in self.inputs:
            if s.bl_idname != "NexusFlowSocket":
                try:
                    v[s.name] = self.input_value(engine, s.name, signal)
                except Exception:
                    pass
        return v

    def _eval(self, signal, engine):
        return expr.evaluate(self.expression, self._vars(signal, engine))

    def process(self, signal, engine):
        try:
            val = self._eval(signal, engine)
            self.live_value = str(val)[:24]
            self._error = ""
        except expr.ExprError as e:
            self._error = str(e)
            return []
        return self.flow_out(signal, **{self.out_key: val})

    def compute(self, socket_name, signal, engine):
        try:
            return self._eval(signal, engine)
        except expr.ExprError as e:
            self._error = str(e)
            return None


@register_node
class BranchNode(NexusLogicNode):
    """分支：表达式为真走 True 口，否则走 False 口。"""
    bl_idname = "NexusBranch"
    bl_label = "Branch (If)"
    bl_icon = "TRIA_RIGHT"

    condition: StringProperty(name="If", default="result > 0")

    def init_sockets(self):
        self.add_in_flow()
        self.add_out_flow("True")
        self.add_out_flow("False")

    def draw_body(self, context, layout):
        layout.prop(self, "condition", text="if")

    def process(self, signal, engine):
        v = dict(signal.payload); v.update(signal.context)
        try:
            ok = bool(expr.evaluate(self.condition, v))
            self._error = ""
        except expr.ExprError as e:
            self._error = str(e)
            return []
        return [("True" if ok else "False", signal.child())]


@register_node
class GateNode(NexusLogicNode):
    """门：throttle/debounce/once，控制信号通过的节奏。"""
    bl_idname = "NexusGate"
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
        st = engine.__dict__.setdefault("_gate_state", {}).setdefault(self.node_uid, {"last": -1e9, "count": 0, "fired": False})
        if self.mode == "ONCE":
            if st["fired"]:
                return []
            st["fired"] = True
        elif self.mode == "THROTTLE":
            now = signal.context.get("time", signal.ts)
            if now - st["last"] < self.seconds:
                return []
            st["last"] = now
        elif self.mode == "EVERY_N":
            st["count"] += 1
            if st["count"] % self.n != 0:
                return []
        return self.flow_out(signal)


@register_node
class CounterNode(NexusLogicNode):
    """计数器：每次点火 +step，写入 payload[key]。"""
    bl_idname = "NexusCounter"
    bl_label = "Counter"
    bl_icon = "LINENUMBERS_ON"

    step: FloatProperty(name="Step", default=1.0)
    key: StringProperty(name="Key", default="count")
    reset_at: FloatProperty(name="Wrap At (0=off)", default=0.0)

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()
        self.add_out("NexusNumberSocket", "count")

    def draw_body(self, context, layout):
        layout.prop(self, "key"); layout.prop(self, "step"); layout.prop(self, "reset_at")

    def _state(self, engine):
        return engine.__dict__.setdefault("_counter_state", {})

    def process(self, signal, engine):
        s = self._state(engine)
        val = s.get(self.node_uid, 0.0) + self.step
        if self.reset_at and val >= self.reset_at:
            val = 0.0
        s[self.node_uid] = val
        return self.flow_out(signal, **{self.key: val})

    def compute(self, socket_name, signal, engine):
        return self._state(engine).get(self.node_uid, 0.0)


@register_node
class MathNode(NexusLogicNode):
    """数学：对两个数做运算，结果入 payload。"""
    bl_idname = "NexusMath"
    bl_label = "Math"
    bl_icon = "PLUS"

    op: EnumProperty(name="Op", items=[
        ("ADD", "Add", ""), ("SUB", "Subtract", ""), ("MUL", "Multiply", ""),
        ("DIV", "Divide", ""), ("MOD", "Modulo", ""), ("POW", "Power", ""),
        ("MIN", "Min", ""), ("MAX", "Max", ""),
    ], default="ADD")
    out_key: StringProperty(name="Store As", default="value")

    def init_sockets(self):
        self.add_in_flow()
        self.add_in("NexusNumberSocket", "A", 0.0)
        self.add_in("NexusNumberSocket", "B", 0.0)
        self.add_out_flow()
        self.add_out("NexusNumberSocket", "value")

    def draw_body(self, context, layout):
        layout.prop(self, "op", text=""); layout.prop(self, "out_key")

    def _calc(self, signal, engine):
        a = self.input_value(engine, "A", signal) or 0.0
        b = self.input_value(engine, "B", signal) or 0.0
        ops = {"ADD": a + b, "SUB": a - b, "MUL": a * b,
               "DIV": a / b if b else 0.0, "MOD": a % b if b else 0.0,
               "POW": a ** b, "MIN": min(a, b), "MAX": max(a, b)}
        return ops[self.op]

    def process(self, signal, engine):
        return self.flow_out(signal, **{self.out_key: self._calc(signal, engine)})

    def compute(self, socket_name, signal, engine):
        return self._calc(signal, engine)


@register_node
class DelayNode(NexusLogicNode):
    """延迟：N 秒后再继续向下游（用 timer 实现，不阻塞 UI）。"""
    bl_idname = "NexusDelay"
    bl_label = "Delay"
    bl_icon = "PREVIEW_RANGE"

    seconds: FloatProperty(name="Seconds", default=1.0, min=0.0)

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "seconds")

    def process(self, signal, engine):
        # schedule a deferred continuation; runtime provides engine.schedule
        sched = getattr(engine, "schedule", None)
        cont = signal.child()
        if sched:
            sched(self.seconds, self.node_uid, cont)
            return []   # downstream is fired later by the scheduler
        return self.flow_out(signal)
