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
class ManualTriggerNode(FxTriggerNode):
    """手动触发：在节点上点按钮即可点火，调试神器。"""
    bl_idname = "FxManualTrigger"
    bl_label = "Manual Trigger"
    bl_icon = "HAND"

    def draw_body(self, context, layout):
        from ...core.runtime import RUNTIME
        row = layout.row()
        row.enabled = bool(RUNTIME.running)
        op = row.operator("fx_nodes.fire_node", text="Fire ▶", icon="PLAY")
        op.node_name = self.name
        op.tree_name = self.id_data.name
        if not RUNTIME.running:
            layout.label(text="Engine stopped — press Start in N-panel", icon="RADIOBUT_OFF")

    def event_source(self):
        return {"kind": "manual"}
