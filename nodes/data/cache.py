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
class CacheNode(FxBaseNode):
    """Persist one-shot or per-frame upstream msg data, defaulting to payload → payload like Node-RED."""
    bl_idname = "FxCache"
    bl_label = "Cache"
    bl_icon = "FILE_CACHE"
    category = "Data"
    fx_color = (0.15, 0.36, 0.40)

    source_path: StringProperty(
        name="Source",
        default="payload",
        description="Message/context property to cache. Default is payload; you may also use payload / flow.xxx / Global.xxx when needed.",
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

    def draw_previews(self, context, layout):
        raw = self.get("_preview", "{}")
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        lines = self._preview_lines(data)
        box = layout.box()
        header = box.row(align=True)
        header.label(text=f"Cache Preview ({len(lines)} lines):", icon="FILE_CACHE")
        if lines:
            for line in lines[:self.max_rows]:
                box.label(text=line[:120])
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
