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
class CounterNode(FxNodes):
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
