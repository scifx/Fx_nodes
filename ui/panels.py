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


class FxDebugPanelBase(FxPanelBase):
    """Dedicated Node-RED-style debug sidebar tab.

    Keep Debug output away from Engine/AI controls so the side bar can be used as
    a scrolling message console: filter, clear, inspect errors, open full logs.
    """
    bl_category = "Fx Debug"


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
                box.label(text=f"Errors: {s['errors']} — see Fx Debug tab", icon="ERROR")


class FXNODES_PT_debug_console(FxDebugPanelBase, Panel):
    bl_label = "Debug Console"
    bl_idname = "FXNODES_PT_debug_console"

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
        err = getattr(node, "_error", "") or ""
        haystack = f"{node.name} {getattr(node, 'path', '')} {raw} {err}".lower()
        return flt.lower() in haystack

    def _collect_errors(self, tree):
        errors = []
        eng = RUNTIME.engines.get(tree.name)
        if eng is not None:
            for uid, msg in getattr(eng.stats, "errors", {}).items():
                errors.append((uid.split("/", 1)[-1], msg))
        seen = {name for name, _ in errors}
        for node in tree.nodes:
            err = getattr(node, "_error", "") or ""
            if err and node.name not in seen:
                errors.append((node.name, err))
        return errors

    def draw(self, context):
        layout = self.layout
        tree = context.space_data.edit_tree
        if not tree:
            return

        # Toolbar: filter, clear messages, clear errors.
        row = layout.row(align=True)
        row.prop(tree, "debug_filter", text="", icon="VIEWZOOM")
        row.operator("fx_nodes.debug_clear_all", text="", icon="TRASH")
        row.operator("fx_nodes.debug_clear_errors", text="", icon="ERROR")

        row = layout.row(align=True)
        row.prop(tree, "debug_rows", text="Rows")
        row.prop(tree, "debug_show_empty", text="Empty")
        row.prop(tree, "debug_show_errors", text="Errors")
        row = layout.row(align=True)
        row.prop(tree, "debug_show_context", text="Context Preview")

        debug_nodes = [n for n in tree.nodes if getattr(n, "bl_idname", "") == "FxDebug"]
        errors = self._collect_errors(tree) if getattr(tree, "debug_show_errors", True) else []

        if errors:
            err_box = layout.box()
            err_box.alert = True
            header = err_box.row(align=True)
            header.label(text=f"Errors ({len(errors)})", icon="ERROR")
            header.operator("fx_nodes.debug_clear_errors", text="Clear", icon="X")
            for name, msg in errors[: max(1, tree.debug_rows)]:
                err_box.label(text=f"{name}: {msg}"[:140], icon="ERROR")
            if len(errors) > tree.debug_rows:
                err_box.label(text=f"… +{len(errors) - tree.debug_rows} more error(s)")

        if not debug_nodes:
            layout.label(text="Add a Debug node to collect messages", icon="INFO")
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

            # Optional console-side context preview.  This is separate from the
            # Debug node's own Show Runtime Context toggle so users can inspect
            # Flow/Global state from the console without editing individual nodes.
            if tree.debug_show_context:
                eng = RUNTIME.engines.get(tree.name)
                data = {
                    "value": data,
                    "flow": getattr(eng, "flow_context", {}) if eng else {},
                    "Global": getattr(eng, "global_context", {}) if eng else {},
                }

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

            node_err = getattr(n, "_error", "") or ""
            if node_err:
                box.alert = True
                box.label(text=node_err[:140], icon="ERROR")

            if lines:
                for line in lines[:tree.debug_rows]:
                    box.label(text=line[:140])
                if len(lines) > tree.debug_rows:
                    box.label(text=f"… +{len(lines) - tree.debug_rows} more line(s). Open Text log for scrolling.")
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


CLASSES = [FXNODES_PT_engine, FXNODES_PT_debug_console, FXNODES_PT_ai]
