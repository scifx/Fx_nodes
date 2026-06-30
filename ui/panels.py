"""N-panel UI in the Fx Nodes node editor: engine control + inspector + AI."""
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


class FXNODES_PT_debug(FxPanelBase, Panel):
    bl_label = "Debug"
    bl_idname = "FXNODES_PT_debug"

    def _pretty_lines(self, data):
        if data in ({}, None, ""):
            return []
        try:
            return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
        except Exception:
            return repr(data).splitlines()

    def _match(self, node, raw, flt):
        if not flt:
            return True
        haystack = f"{node.name} {getattr(node, 'path', '')} {raw}".lower()
        return flt.lower() in haystack

    def draw(self, context):
        layout = self.layout
        tree = context.space_data.edit_tree
        if not tree:
            return

        row = layout.row(align=True)
        row.prop(tree, "debug_filter", text="", icon="VIEWZOOM")
        row.operator("fx_nodes.debug_clear_all", text="", icon="TRASH")
        row = layout.row(align=True)
        row.prop(tree, "debug_rows")
        row.prop(tree, "debug_show_empty", text="Empty")

        debug_nodes = [n for n in tree.nodes if n.bl_idname == "FxDebug"]
        if not debug_nodes:
            layout.label(text="Add a Debug node", icon="INFO")
            return

        shown = 0
        for n in debug_nodes:
            raw = n.get("_preview", "{}")
            if not self._match(n, raw, tree.debug_filter):
                continue
            try:
                data = json.loads(raw)
            except Exception:
                data = raw
            lines = self._pretty_lines(data)
            if not lines and not tree.debug_show_empty:
                continue

            box = layout.box()
            header = box.row(align=True)
            header.label(text=f"{n.name} · {getattr(n, 'path', 'msg')} · {n.fire_count}", icon="VIEWZOOM")
            op = header.operator("fx_nodes.debug_clear_node", text="", icon="X")
            op.tree_name = tree.name
            op.node_name = n.name
            op = header.operator("fx_nodes.open_text_editor", text="", icon="TEXT")
            op.text_name = getattr(n, "debug_text_name", "")

            if lines:
                for line in lines[:tree.debug_rows]:
                    box.label(text=line[:120])
                if len(lines) > tree.debug_rows:
                    box.label(text=f"… +{len(lines) - tree.debug_rows} more lines")
            else:
                box.label(text="(no data yet)", icon="INFO")
            shown += 1

        if shown == 0:
            layout.label(text="No Debug output matches the filter", icon="INFO")


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


CLASSES = [FXNODES_PT_engine, FXNODES_PT_debug, FXNODES_PT_ai]
