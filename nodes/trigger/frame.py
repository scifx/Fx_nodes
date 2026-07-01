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
class FrameTriggerNode(FxTriggerNode):
    """帧触发：随时间线帧变化点火（可设步长/范围）。"""
    bl_idname = "FxFrameTrigger"
    bl_label = "Frame Trigger"
    bl_icon = "KEYFRAME"

    every_n: IntProperty(name="Every N frames", default=1, min=1)
    only_playing: BoolProperty(name="Only While Playing", default=False)

    def draw_body(self, context, layout):
        layout.prop(self, "every_n")
        layout.prop(self, "only_playing")

    def event_source(self):
        return {"kind": "frame", "every_n": self.every_n, "only_playing": self.only_playing}
