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
class GateNode(FxNodes):
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
