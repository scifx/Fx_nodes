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
class DelayNode(FxNodes):
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
