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


@register_node
class KeyTriggerNode(FxTriggerNode):
    """按键触发：监听键盘按键。"""
    bl_idname = "FxKeyTrigger"
    bl_label = "Key Trigger"
    bl_icon = "EVENT_A"

    key: EnumProperty(
        name="Key",
        items=[(k, k, "") for k in (
            "SPACE", "RET", "A", "B", "C", "D", "E", "F", "G", "S", "W", "Q", "X",
            "ONE", "TWO", "THREE", "FOUR", "FIVE",
            "UP_ARROW", "DOWN_ARROW", "LEFT_ARROW", "RIGHT_ARROW", "ESC",
        )],
        default="SPACE",
    )
    value: EnumProperty(name="On", items=[("PRESS", "Press", ""), ("RELEASE", "Release", "")], default="PRESS")
    ctrl: BoolProperty(name="Ctrl", default=False)
    shift: BoolProperty(name="Shift", default=False)
    alt: BoolProperty(name="Alt", default=False)

    def draw_body(self, context, layout):
        layout.prop(self, "key")
        layout.prop(self, "value")
        row = layout.row(align=True)
        row.prop(self, "ctrl", toggle=True)
        row.prop(self, "shift", toggle=True)
        row.prop(self, "alt", toggle=True)

    def event_source(self):
        return {"kind": "key", "key": self.key, "value": self.value,
                "ctrl": self.ctrl, "shift": self.shift, "alt": self.alt}


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

    def draw_body(self, context, layout):
        layout.prop(self, "button")
        layout.prop(self, "require_hit")

    def event_source(self):
        return {"kind": "click", "button": self.button, "require_hit": self.require_hit}


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


@register_node
class StartTriggerNode(FxTriggerNode):
    """启动触发：引擎启动时点火一次（用于初始化）。"""
    bl_idname = "FxStartTrigger"
    bl_label = "On Start"
    bl_icon = "PLAY"

    def event_source(self):
        return {"kind": "start"}


@register_node
class ManualTriggerNode(FxTriggerNode):
    """手动触发：在节点上点按钮即可点火，调试神器。"""
    bl_idname = "FxManualTrigger"
    bl_label = "Manual Trigger"
    bl_icon = "HAND"

    def draw_body(self, context, layout):
        op = layout.operator("fx_nodes.fire_node", text="Fire ▶", icon="PLAY")
        op.node_name = self.name
        op.tree_name = self.id_data.name

    def event_source(self):
        return {"kind": "manual"}
