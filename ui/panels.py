"""N-panel UI in the Fx Nodes node editor: engine/AI plus a dedicated Debug tab."""
from __future__ import annotations

import json
import bpy
from bpy.types import Panel

from ..core.runtime import RUNTIME
from ..prefs import get_preferences


class FxPanelBase:
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Fx Nodes"

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "tree_type", "") == "FxNodeTree"


class FXNODES_PT_engine(FxPanelBase, Panel):
    bl_label = "Engine"
    bl_idname = "FXNODES_PT_engine"

    def draw(self, context):
        layout = self.layout
        running = RUNTIME.running
        row = layout.row(align=True)
        row.scale_y = 1.4
        if running:
            row.operator("fx_nodes.stop_engine", text="Stop", icon="PAUSE", depress=True)
        else:
            row.operator("fx_nodes.start_engine", text="Start", icon="PLAY")
        layout.label(text="Status: " + ("RUNNING" if running else "stopped"),
                     icon="REC" if running else "RADIOBUT_OFF")
        layout.separator()
        layout.operator("fx_nodes.paste_property_menu", text="Paste Property Node (Shift+V)", icon="RNA")

        row = layout.row(align=True)
        row.operator("fx_nodes.debug_clear_all", text="Clear Debugs", icon="TRASH")
        row.operator("fx_nodes.debug_clear_errors", text="Clear Errors", icon="ERROR")

        tree = context.space_data.edit_tree
        if tree and tree.name in RUNTIME.engines:
            eng = RUNTIME.engines[tree.name]
            box = layout.box()
            s = eng.stats.as_dict()
            box.label(text=f"Fires: {s['fires']}  Nodes: {s['total_nodes']}")
            box.label(text=f"Last: {s['last_ms']}ms  Avg: {s['avg_ms']}ms")
            if s["errors"]:
                box.alert = True
                box.label(text=f"Errors: {s['errors']} — check nodes", icon="ERROR")


class FXNODES_PT_ai(FxPanelBase, Panel):
    bl_label = "AI"
    bl_idname = "FXNODES_PT_ai"

    def draw(self, context):
        layout = self.layout
        prefs = get_preferences(context)
        layout.label(text=f"Model: {prefs.ai_model}")
        layout.label(text=f"Endpoint: {prefs.ai_base_url[:28]}")
        layout.operator("fx_nodes.test_ai", icon="PLUGIN")
        layout.prop(prefs, "allow_ai")


CLASSES = [FXNODES_PT_engine, FXNODES_PT_ai]
