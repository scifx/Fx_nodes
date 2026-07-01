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
class SceneEventTriggerNode(FxTriggerNode):
    """场景事件触发：depsgraph 更新 / 文件加载 / 渲染前后 / 物体选择。"""
    bl_idname = "FxSceneEventTrigger"
    bl_label = "Scene Event Trigger"
    bl_icon = "SCENE_DATA"

    event: EnumProperty(
        name="Event",
        items=[
            ("depsgraph", "Depsgraph Update", "场景数据变化"),
            ("load_post", "File Loaded", ""),
            ("render_pre", "Before Render", ""),
            ("render_post", "After Render", ""),
            ("save_post", "After Save", ""),
        ],
        default="depsgraph",
    )

    def draw_body(self, context, layout):
        layout.prop(self, "event")

    def event_source(self):
        return {"kind": "scene", "event": self.event}
