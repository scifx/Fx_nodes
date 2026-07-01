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
class KeyTriggerNode(FxTriggerNode):
    """按键触发：监听键盘按键。"""
    bl_idname = "FxKeyTrigger"
    bl_label = "Key Trigger"
    bl_icon = "EVENT_A"

    key: EnumProperty(
        name="Key",
        items=[(k, k, "") for k in (
            "SPACE", "RET", "TAB", "ESC",
            "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
            "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
            "ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
            "UP_ARROW", "DOWN_ARROW", "LEFT_ARROW", "RIGHT_ARROW",
            "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
        )],
        default="SPACE",
    )
    value: EnumProperty(name="On", items=[("PRESS", "Press", ""), ("RELEASE", "Release", "")], default="PRESS")
    ctrl: BoolProperty(name="Ctrl", default=False)
    shift: BoolProperty(name="Shift", default=False)
    alt: BoolProperty(name="Alt", default=False)
    swallow: BoolProperty(
        name="Swallow Key",
        default=True,
        description="绑定后屏蔽 Blender 原有按键行为，防止冲突 (例如 SPACE 不再播放动画)"
    )
    block_repeats: BoolProperty(
        name="Block Repeats",
        default=False,
        description="开启后忽略长按重复事件，只响应首次 PRESS；关闭则允许重复触发（默认允许重复）"
    )

    def draw_body(self, context, layout):
        layout.prop(self, "key")
        layout.prop(self, "value")
        row = layout.row(align=True)
        row.prop(self, "ctrl", toggle=True)
        row.prop(self, "shift", toggle=True)
        row.prop(self, "alt", toggle=True)
        col = layout.column(align=True)
        col.prop(self, "swallow", toggle=True, icon='HAND')
        col.prop(self, "block_repeats")

    def event_source(self):
        return {"kind": "key", "key": self.key, "value": self.value,
                "ctrl": self.ctrl, "shift": self.shift, "alt": self.alt,
                "swallow": self.swallow, "block_repeats": self.block_repeats}
