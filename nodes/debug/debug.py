"""Node-RED-style data nodes: Debug, Change, Context, Get Property, Cache."""
from __future__ import annotations

import json
from bpy.props import StringProperty, IntProperty, EnumProperty, BoolProperty

try:
    import bpy
except Exception:  # pragma: no cover - headless tests
    bpy = None

from ...core.base import FxBaseNode
from ...core.registry import register_node
from ...core import expr, msgpath
from ...core import path as blender_path

@register_node
class DebugNode(FxBaseNode):
    """Node-RED-like Debug node.

    It previews a path from msg/flow/global. Examples: ``msg``, ``payload``,
    ``msg["payload"]``, ``topic``, ``flow.count``, ``Global.seed``.
    """
    bl_idname = "FxDebug"
    bl_label = "Debug"
    bl_icon = "VIEWZOOM"
    category = "Debug"
    fx_color = (0.45, 0.32, 0.14)

    path: StringProperty(name="Path", default="msg")
    max_rows: IntProperty(name="Max Rows", default=8, min=1, max=64)
    fire_count: IntProperty(name="Fires", default=0)
    show_context: BoolProperty(name="Show Runtime Context", default=False)
    log_to_text: BoolProperty(
        name="Log To Text",
        default=True,
        description="Append full multi-line debug output to a Blender Text datablock.",
    )
    debug_text_name: StringProperty(
        name="Debug Text",
        default="",
        description="Blender Text datablock that stores the full multi-line debug log.",
    )

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "path")
        layout.prop(self, "show_context")
        layout.prop(self, "log_to_text")
        if self.log_to_text:
            row = layout.row(align=True)
            if bpy is not None:
                row.prop_search(self, "debug_text_name", bpy.data, "texts", text="Log")
            else:
                row.prop(self, "debug_text_name", text="Log")
            op = row.operator("fx_nodes.open_text_editor", text="", icon="TEXT")
            op.text_name = self.debug_text_name

        row = layout.row(align=True)
        row.label(text=f"Fires: {self.fire_count}", icon="DRIVER")
        row.prop(self, "max_rows", text="Rows")

        row = layout.row(align=True)
        op = row.operator("fx_nodes.debug_clear_node", text="Clear", icon="TRASH")
        op.tree_name = self.id_data.name
        op.node_name = self.name
        op = row.operator("fx_nodes.debug_copy_json", text="Copy JSON", icon="COPYDOWN")
        op.tree_name = self.id_data.name
        op.node_name = self.name

    def draw_previews(self, context, layout):
        raw = self.get("_preview", "{}")
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        lines = self._preview_lines(data)
        box = layout.box()
        header = box.row(align=True)
        # Show which path is being debugged
        path_label = self.path or "msg"
        type_str = type(data).__name__
        if isinstance(data, dict):
            # show_context mode: data contains "msg", "payload", etc.
            if "msg" in data and "_extracted" in data:
                # show extracted value type
                v = data.get("_extracted")
                vt = type(v).__name__
                if isinstance(v, dict):
                    vt = f"dict[{len(v)}]"
                elif isinstance(v, list):
                    vt = f"list[{len(v)}]"
                type_str = f"{path_label} → {vt}"
            elif "msg" in data and "payload" in data:
                # full context view
                m = data.get("msg")
                if isinstance(m, dict):
                    type_str = f"msg dict[{len(m)}]"
            else:
                type_str = f"dict [{len(data)} keys]"
        elif isinstance(data, list):
            type_str = f"list [{len(data)} items]"
        header.label(text=f"{path_label}: {type_str}", icon="VIEWZOOM")
        if lines:
            for line in lines[:self.max_rows]:
                box.label(text=line[:120])
            if len(lines) > self.max_rows:
                box.label(text=f"… +{len(lines) - self.max_rows} more lines")
        else:
            box.label(text="(no data yet)", icon="INFO")

    def _pretty(self, value):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        except Exception:
            return repr(value)

    def _preview_lines(self, data):
        if data in ({}, None, ""):
            return []
        return self._pretty(data).splitlines()

    def _ensure_debug_text(self):
        if bpy is None:
            return None
        name = self.debug_text_name or f"Fx Debug - {self.name}"
        txt = bpy.data.texts.get(name) or bpy.data.texts.new(name)
        if self.debug_text_name != txt.name:
            self.debug_text_name = txt.name
        return txt

    def _append_log(self, data):
        if not self.log_to_text:
            return
        txt = self._ensure_debug_text()
        if txt is None:
            return
        txt.write(f"\n--- fire #{self.fire_count} · {self.path} ---\n")
        txt.write(self._pretty(data))
        txt.write("\n")

    def _json_safe(self, value):
        def safe(v):
            try:
                # primitives
                if isinstance(v, (int, float, str, bool)) or v is None:
                    return v
                # list / tuple
                if isinstance(v, (list, tuple)):
                    return [safe(x) for x in v][:128]
                # set / frozenset / dict_keys / dict_values / dict_items -> list
                if isinstance(v, (set, frozenset)):
                    return [safe(x) for x in list(v)][:128]
                # dict-like with .keys()/.items()
                tname = type(v).__name__
                if tname in ("dict_keys", "dict_values", "dict_items", "KeysView", "ValuesView", "ItemsView"):
                    try:
                        return [safe(x) for x in list(v)][:128]
                    except Exception:
                        pass
                if isinstance(v, dict):
                    return {str(k): safe(x) for k, x in list(v.items())[:128]}
                # try to iterate mapping-like objects
                if hasattr(v, "items") and callable(v.items):
                    try:
                        return {str(k): safe(x) for k, x in list(v.items())[:128]}
                    except Exception:
                        pass
                # fallback: try json round-trip via str
                return f"{tname}({str(v)!r})"[:200]
            except Exception:
                return "<unrepr>"
        return safe(value)

    def process(self, signal, engine):
        self.fire_count += 1
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        missing = object()
        path = (self.path or "msg").strip()
        # Fast-path for common roots – guarantees msg returns full dict
        try:
            pl = path.lower()
            if pl in ("msg", "message"):
                value = signal.msg
            elif pl == "payload":
                value = signal.msg.get("payload", missing)
            elif pl == "topic":
                value = signal.msg.get("topic", missing)
            else:
                value = msgpath.get(path, signal.msg, flow, glob, default=missing)
        except msgpath.MsgPathError as e:
            self._error = str(e)
            return []
        if value is missing:
            self._error = f"path not found: {self.path}"
            return []
        data = self._json_safe(value)
        if self.show_context:
            # No "value" backward-compat key – user explicitly requested removal.
            # Pure Node-RED style: top-level is msg, plus runtime contexts.
            output = {
                "msg": self._json_safe(signal.msg),
                "payload": self._json_safe(signal.msg.get("payload")),
                "topic": self._json_safe(signal.msg.get("topic")),
                "path": path,
                "_extracted": data,  # internal, prefixed to avoid confusion with msg keys
                "context": self._json_safe(signal.context),
                "flow": self._json_safe(flow),
                "global": self._json_safe(glob),
                "Global": self._json_safe(glob),  # keep capital alias for legacy UI
            }
            data = output
        try:
            self["_preview"] = json.dumps(data, ensure_ascii=False)
        except Exception:
            try:
                self["_preview"] = json.dumps(self._json_safe(data), ensure_ascii=False)
            except Exception:
                self["_preview"] = json.dumps(str(value)[:500], ensure_ascii=False)
        self._append_log(data)
        self._error = ""
        return self.flow_out(signal)
