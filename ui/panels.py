"""N-panel UI in the Fx Nodes node editor: engine control + inspector + AI."""
from __future__ import annotations

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

        tree = context.space_data.edit_tree
        if tree and tree.name in RUNTIME.engines:
            eng = RUNTIME.engines[tree.name]
            box = layout.box()
            s = eng.stats.as_dict()
            box.label(text=f"Fires: {s['fires']}  Nodes: {s['total_nodes']}")
            box.label(text=f"Last: {s['last_ms']}ms  Avg: {s['avg_ms']}ms")
            if s["errors"]:
                box.alert = True
                box.label(text=f"Errors: {s['errors']}", icon="ERROR")


class FXNODES_PT_inspector(FxPanelBase, Panel):
    bl_label = "Data Inspector"
    bl_idname = "FXNODES_PT_inspector"

    def draw(self, context):
        layout = self.layout
        tree = context.space_data.edit_tree
        if not tree:
            return
        previews = [n for n in tree.nodes if n.bl_idname == "FxDebug"]
        if not previews:
            layout.label(text="Add a Debug node", icon="INFO")
            return
        for n in previews:
            box = layout.box()
            box.label(text=n.name, icon="VIEWZOOM")
            box.label(text=f"Fires: {n.fire_count}")
            import json
            try:
                data = json.loads(n.get("_preview", "{}"))
            except Exception:
                data = {}
            for k, v in list(data.items())[:6]:
                row = box.row()
                row.label(text=str(k))
                row.label(text=str(v)[:24])


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


CLASSES = [FXNODES_PT_engine, FXNODES_PT_inspector, FXNODES_PT_ai]
