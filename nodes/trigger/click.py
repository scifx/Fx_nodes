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
class ClickTriggerNode(FxTriggerNode):
    """点击触发：监听视口鼠标点击（可选只在点中物体时）。"""
    bl_idname = "FxClickTrigger"
    bl_label = "Click Trigger"
    bl_icon = "RESTRICT_SELECT_OFF"

    button: EnumProperty(name="Button",
                         items=[("LEFTMOUSE", "Left", ""), ("RIGHTMOUSE", "Right", ""), ("MIDDLEMOUSE", "Middle", "")],
                         default="LEFTMOUSE")
    require_hit: BoolProperty(name="Only On Object Hit", default=False,
                              description="仅当射线击中物体时点火，命中物体写入 msg['object']")
    swallow: BoolProperty(
        name="Swallow Click",
        default=False,
        description="绑定后屏蔽 Blender 原有鼠标行为（谨慎使用，可能影响选择）"
    )

    def draw_body(self, context, layout):
        layout.prop(self, "button")
        layout.prop(self, "require_hit")
        layout.prop(self, "swallow", toggle=True, icon='HAND')

    def event_source(self):
        return {"kind": "click", "button": self.button, "require_hit": self.require_hit, "swallow": self.swallow}
