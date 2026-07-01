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
class StartTriggerNode(FxTriggerNode):
    """启动触发：引擎启动时点火一次（用于初始化）。"""
    bl_idname = "FxStartTrigger"
    bl_label = "On Start"
    bl_icon = "PLAY"

    def event_source(self):
        return {"kind": "start"}
