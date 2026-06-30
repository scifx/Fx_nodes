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
    ``msg.payload``, ``topic``, ``flow.count``, ``global.seed``.
    """
    bl_idname = "FxDebug"
    bl_label = "Debug"
    bl_icon = "VIEWZOOM"
    category = "Data"
    fx_color = (0.32, 0.28, 0.12)

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
        row = layout.row(align=True)
        row.label(text=f"Fires: {self.fire_count}", icon="DRIVER")
        row.prop(self, "max_rows", text="Rows")

        raw = self.get("_preview", "{}")
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        lines = self._preview_lines(data)
        box = layout.box()
        if lines:
            for line in lines[:self.max_rows]:
                box.label(text=line[:120])
            if len(lines) > self.max_rows:
                box.label(text=f"… +{len(lines) - self.max_rows} more lines")
        else:
            box.label(text="(no data yet)", icon="INFO")

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
                if isinstance(v, (int, float, str, bool)) or v is None:
                    return v
                if isinstance(v, (list, tuple)):
                    return [safe(x) for x in v][:64]
                if isinstance(v, dict):
                    return {str(k): safe(x) for k, x in list(v.items())[:64]}
                return f"{type(v).__name__}({v!r})"[:160]
            except Exception:
                return "<unrepr>"
        return safe(value)

    def process(self, signal, engine):
        self.fire_count += 1
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            value = msgpath.get(self.path, signal.msg, flow, glob)
        except msgpath.MsgPathError as e:
            self._error = str(e)
            return []
        data = self._json_safe(value)
        if self.show_context:
            data = {"value": data, "context": self._json_safe(signal.context)}
        try:
            self["_preview"] = json.dumps(data, ensure_ascii=False)
        except Exception:
            self["_preview"] = json.dumps(repr(value)[:160], ensure_ascii=False)
        self._append_log(data)
        self._error = ""
        return self.flow_out(signal)


@register_node
class ChangeNode(FxBaseNode):
    """Node-RED-like Change node for msg/flow/global paths."""
    bl_idname = "FxChange"
    bl_label = "Change"
    bl_icon = "RNA"
    category = "Data"
    fx_color = (0.24, 0.30, 0.16)

    mode: EnumProperty(name="Mode", items=[
        ("SET", "Set", "Set a msg/flow/global property"),
        ("DELETE", "Delete", "Delete a msg/flow/global property"),
        ("MOVE", "Move", "Move a property to another path"),
    ], default="SET")
    path: StringProperty(name="Property", default="payload")
    value_expr: StringProperty(name="Value Expr", default="payload")
    to_path: StringProperty(name="To", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "mode", text="")
        layout.prop(self, "path")
        if self.mode == "SET":
            layout.prop(self, "value_expr")
        elif self.mode == "MOVE":
            layout.prop(self, "to_path")
        if self.last_value:
            layout.label(text=self.last_value[:60], icon="CHECKMARK")

    def process(self, signal, engine):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            if self.mode == "SET":
                val = expr.evaluate(self.value_expr, self.expr_vars(signal, engine))
                msgpath.set(self.path, val, signal.msg, flow, glob)
                self.last_value = f"{self.path} = {msgpath.compact(val, 40)}"
            elif self.mode == "DELETE":
                msgpath.delete(self.path, signal.msg, flow, glob)
                self.last_value = f"deleted {self.path}"
            elif self.mode == "MOVE":
                val = msgpath.get(self.path, signal.msg, flow, glob)
                msgpath.set(self.to_path, val, signal.msg, flow, glob)
                msgpath.delete(self.path, signal.msg, flow, glob)
                self.last_value = f"{self.path} → {self.to_path}"
        except (expr.ExprError, msgpath.MsgPathError) as e:
            self._error = str(e)
            return []
        self._error = ""
        return self.flow_out(signal)


@register_node
class ContextNode(FxBaseNode):
    """Explicit Node-RED context helper.

    Change can already operate on flow/global paths.  This node is a more
    discoverable shorthand for common context operations.
    """
    bl_idname = "FxContext"
    bl_label = "Context"
    bl_icon = "WORLD"
    category = "Data"
    fx_color = (0.22, 0.24, 0.34)

    mode: EnumProperty(name="Mode", items=[
        ("FLOW_TO_MSG", "Flow → Msg", "Read flow context into msg"),
        ("MSG_TO_FLOW", "Msg → Flow", "Write msg/expression into flow context"),
        ("GLOBAL_TO_MSG", "Global → Msg", "Read global context into msg"),
        ("MSG_TO_GLOBAL", "Msg → Global", "Write msg/expression into global context"),
    ], default="GLOBAL_TO_MSG")
    context_key: StringProperty(name="Context Key", default="value")
    msg_path: StringProperty(name="Message Property", default="payload")
    value_expr: StringProperty(name="Value Expr", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "mode", text="")
        layout.prop(self, "context_key")
        layout.prop(self, "msg_path")
        if self.mode in {"MSG_TO_FLOW", "MSG_TO_GLOBAL"}:
            layout.prop(self, "value_expr")
        if self.last_value:
            layout.label(text=self.last_value[:60], icon="CHECKMARK")

    def process(self, signal, engine):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            if self.mode == "FLOW_TO_MSG":
                val = flow.get(self.context_key)
                msgpath.set(self.msg_path, val, signal.msg, flow, glob)
            elif self.mode == "GLOBAL_TO_MSG":
                val = glob.get(self.context_key)
                msgpath.set(self.msg_path, val, signal.msg, flow, glob)
            elif self.mode == "MSG_TO_FLOW":
                val = expr.evaluate(self.value_expr, self.expr_vars(signal, engine))
                flow[self.context_key] = val
            elif self.mode == "MSG_TO_GLOBAL":
                val = expr.evaluate(self.value_expr, self.expr_vars(signal, engine))
                glob[self.context_key] = val
            self.last_value = msgpath.compact(val, 50)
        except (expr.ExprError, msgpath.MsgPathError) as e:
            self._error = str(e)
            return []
        self._error = ""
        return self.flow_out(signal)


@register_node
class CacheNode(FxBaseNode):
    """Persist one-shot or per-frame upstream msg data, defaulting to payload → payload like Node-RED."""
    bl_idname = "FxCache"
    bl_label = "Cache"
    bl_icon = "FILE_CACHE"
    category = "Data"
    fx_color = (0.20, 0.30, 0.34)

    source_path: StringProperty(
        name="Source",
        default="payload",
        description="Message/context property to cache. Default is payload; you may also use msg.xxx / flow.xxx / global.xxx when needed.",
    )
    store_path: StringProperty(
        name="Target",
        default="payload",
        description="Where the cached result is written. Default is payload; change only when you explicitly want another msg/flow/global property.",
    )
    mode: EnumProperty(
        name="Mode",
        items=[
            ("ONCE", "Cache Once", "收到第一条数据后缓存，直到手动清理前都不更新"),
            ("ALWAYS", "Always Update", "每次触发都更新缓存"),
            ("PER_FRAME", "Per Frame", "每帧追加一次缓存，结果是数组"),
        ],
        default="ONCE",
    )
    write_to_msg: BoolProperty(
        name="Mirror To msg.cache",
        default=False,
        description="Optional extra mirror. Off by default to keep payload as the primary Node-RED message path.",
    )
    fire_count: IntProperty(name="Fires", default=0)
    cache_hits: IntProperty(name="Cache Hits", default=0)
    max_rows: IntProperty(name="Preview Rows", default=8, min=1, max=32)

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def _json_safe(self, value):
        def safe(v):
            try:
                if isinstance(v, (int, float, str, bool)) or v is None:
                    return v
                if isinstance(v, (list, tuple)):
                    return [safe(x) for x in v][:128]
                if isinstance(v, dict):
                    return {str(k): safe(x) for k, x in list(v.items())[:128]}
                return f"{type(v).__name__}({v!r})"[:200]
            except Exception:
                return "<unrepr>"
        return safe(value)

    def _pretty(self, value):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        except Exception:
            return repr(value)

    def _preview_lines(self, data):
        if data in ({}, None, ""):
            return []
        return self._pretty(data).splitlines()

    def _get_cache_data(self):
        raw = self.get("_cache_data", "")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _set_cache_data(self, data):
        safe = self._json_safe(data)
        self["_cache_data"] = json.dumps(safe, ensure_ascii=False)
        self["_preview"] = json.dumps(safe, ensure_ascii=False)
        return safe

    def clear_cache(self):
        self["_cache_data"] = ""
        self["_preview"] = "{}"
        self["_cache_meta"] = json.dumps({}, ensure_ascii=False)
        self.cache_hits = 0
        self._error = ""

    def _cache_exists(self):
        raw = self.get("_cache_data", "")
        return bool(raw)

    def _store_into_contexts(self, signal, engine, value):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        msgpath.set(self.store_path, value, signal.msg, flow, glob)
        if self.write_to_msg:
            msgpath.set(f"msg.cache.{self.name}", value, signal.msg, flow, glob)
        return value

    def draw_body(self, context, layout):
        layout.prop(self, "source_path")
        layout.prop(self, "store_path")
        row = layout.row(align=True)
        row.prop(self, "mode", text="")
        row.prop(self, "write_to_msg", text="Mirror")

        row = layout.row(align=True)
        row.label(text=f"Fires: {self.fire_count}", icon="DRIVER")
        row.label(text=f"Hits: {self.cache_hits}", icon="FILE_CACHE")
        row.prop(self, "max_rows", text="Rows")

        op = layout.operator("fx_nodes.cache_clear_node", text="Clear Cache", icon="TRASH")
        op.tree_name = self.id_data.name
        op.node_name = self.name

        raw = self.get("_preview", "{}")
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        lines = self._preview_lines(data)
        box = layout.box()
        if lines:
            for line in lines[:self.max_rows]:
                box.label(text=line[:120], icon="FILE_CACHE")
            if len(lines) > self.max_rows:
                box.label(text=f"… +{len(lines) - self.max_rows} more lines")
        else:
            box.label(text="(cache empty)", icon="INFO")

    def process(self, signal, engine):
        self.fire_count += 1
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        frame = signal.context.get("frame")
        try:
            incoming = msgpath.get(self.source_path, signal.msg, flow, glob)
        except msgpath.MsgPathError as e:
            self._error = str(e)
            return []

        cached = self._get_cache_data()
        meta = {"mode": self.mode, "source_path": self.source_path, "store_path": self.store_path, "frame": frame}

        if self.mode == "ONCE":
            if not self._cache_exists():
                cached = self._set_cache_data(incoming)
            else:
                self.cache_hits += 1
        elif self.mode == "ALWAYS":
            cached = self._set_cache_data(incoming)
        elif self.mode == "PER_FRAME":
            if not isinstance(cached, list):
                cached = []
            cached.append({"frame": frame, "value": self._json_safe(incoming)})
            cached = self._set_cache_data(cached)

        self["_cache_meta"] = json.dumps(meta, ensure_ascii=False)
        try:
            self._store_into_contexts(signal, engine, cached)
        except msgpath.MsgPathError as e:
            self._error = str(e)
            return []
        self._error = ""
        return self.flow_out(signal)


@register_node
class PropertyGetNode(FxBaseNode):
    """Read a safe Blender full data path into a msg path."""
    bl_idname = "FxPropertyGet"
    bl_label = "Get Property"
    bl_icon = "RNA"
    category = "Data"
    fx_color = (0.24, 0.30, 0.16)

    path: StringProperty(name="Blender Full Path", default="")
    out_path: StringProperty(name="Target", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "path", text="")
        layout.prop(self, "out_path")
        if self.last_value:
            layout.label(text=f"→ {self.last_value}", icon="CHECKMARK")

    def process(self, signal, engine):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            val = blender_path.get_path(self.path)
            msgpath.set(self.out_path, val, signal.msg, flow, glob)
        except (blender_path.PathError, msgpath.MsgPathError) as e:
            self._error = str(e)
            return []
        self.last_value = msgpath.compact(val, 48)
        self._error = ""
        return self.flow_out(signal)
