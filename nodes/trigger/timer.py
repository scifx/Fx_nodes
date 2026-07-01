"""Trigger nodes: they decide WHEN the graph fires.

Each trigger registers itself with the runtime when the engine starts, via an
event source descriptor. The runtime (core/runtime.py) wires the actual bpy
handlers/timers/modal operators and calls engine.fire(trigger_uid, ...).
"""
from __future__ import annotations

import bpy
from bpy.props import FloatProperty, IntProperty, EnumProperty, StringProperty, BoolProperty

from ...core.base import FxTriggerNode
from ...core.registry import register_node

@register_node
class TimerTriggerNode(FxTriggerNode):
    """定时触发：每 interval 秒点火一次。"""
    bl_idname = "FxTimerTrigger"
    bl_label = "Timer Trigger"
    bl_icon = "TIME"

    interval: FloatProperty(name="Interval (s)", default=1.0, min=0.01, soft_max=60.0)
    enabled: BoolProperty(name="Enabled", default=True)

    def draw_body(self, context, layout):
        layout.prop(self, "enabled")
        layout.prop(self, "interval")

    def event_source(self):
        return {"kind": "timer", "interval": self.interval, "enabled": self.enabled}
