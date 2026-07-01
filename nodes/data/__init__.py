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
    ``msg.payload``, ``topic``, ``flow.count``, ``Global.seed``.
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


@register_node
class ChangeNode(FxBaseNode):
    """Node-RED-like Change node for msg/flow/global paths."""
    bl_idname = "FxChange"
    bl_label = "Change"
    bl_icon = "RNA"
    category = "Data"
    fx_color = (0.15, 0.36, 0.40)

    mode: EnumProperty(name="Mode", items=[
        ("SET", "Set", "Set a msg/flow/global property"),
        ("DELETE", "Delete", "Delete a msg/flow/global property"),
        ("MOVE", "Move", "Move a property to another path"),
    ], default="SET")
    path: StringProperty(name="Property", default="payload")
    value_expr: StringProperty(name="Value Expr", default="payload")
    value_text_name: StringProperty(
        name="Value Text",
        default="",
        description="Optional Blender Text datablock for multiline Value Expr.",
    )
    to_path: StringProperty(name="To", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def get_value_expr(self):
        return self.get_text_content("value_text_name", "value_expr")

    def draw_body(self, context, layout):
        layout.prop(self, "mode", text="")
        layout.prop(self, "path")
        if self.mode == "SET":
            self.draw_text_row(layout, "value_text_name", "value_expr", label="Expr", prefix="Fx Change Value")
        elif self.mode == "MOVE":
            layout.prop(self, "to_path")

    def draw_previews(self, context, layout):
        if self.mode == "SET" and getattr(self, "value_text_name", ""):
            expr_str = self.get_value_expr()
            if expr_str:
                box = layout.box(); box.scale_y = 0.8
                box.label(text="Value Expr Preview:", icon="DRIVER")
                for ln in expr_str.splitlines()[:3]:
                    box.label(text=(ln or " ")[:80])
        if self.last_value:
            box = layout.box(); box.scale_y = 0.8
            box.label(text=self.last_value[:60], icon="CHECKMARK")

    def process(self, signal, engine):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            if self.mode == "SET":
                val = expr.evaluate(self.get_value_expr(), self.expr_vars(signal, engine))
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
    fx_color = (0.15, 0.36, 0.40)

    mode: EnumProperty(name="Mode", items=[
        ("FLOW_TO_MSG", "Flow → Msg", "Read flow context into msg"),
        ("MSG_TO_FLOW", "Msg → Flow", "Write msg/expression into flow context"),
        ("GLOBAL_TO_MSG", "Global → Msg", "Read global context into msg"),
        ("MSG_TO_GLOBAL", "Msg → Global", "Write msg/expression into global context"),
        ("RUNTIME_TO_MSG", "Runtime → Msg", "Read runtime signal.context value, such as frame/time/fps/wall, into msg"),
        ("MSG_TO_RUNTIME", "Msg → Runtime", "Write expression result into signal.context for downstream nodes"),
    ], default="GLOBAL_TO_MSG")
    context_key: StringProperty(name="Context Key", default="value")
    msg_path: StringProperty(name="Message Property", default="payload")
    value_expr: StringProperty(name="Value Expr", default="payload")
    value_text_name: StringProperty(
        name="Value Text",
        default="",
        description="Optional Blender Text datablock for multiline Value Expr.",
    )
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def get_value_expr(self):
        return self.get_text_content("value_text_name", "value_expr")

    def draw_body(self, context, layout):
        layout.prop(self, "mode", text="")
        layout.prop(self, "context_key")
        layout.prop(self, "msg_path")
        if self.mode in {"MSG_TO_FLOW", "MSG_TO_GLOBAL", "MSG_TO_RUNTIME"}:
            self.draw_text_row(layout, "value_text_name", "value_expr", label="Expr", prefix="Fx Context")

    def draw_previews(self, context, layout):
        if self.last_value:
            box = layout.box(); box.scale_y = 0.8
            box.label(text=self.last_value[:60], icon="CHECKMARK")

    def _ctx_path(self, root, key):
        """Return a msgpath-compatible path for a context key.

        Users often type either ``foo`` or ``Global.foo``/``flow.foo``.  Treat
        simple keys as belonging to the selected context root, but preserve an
        explicit root when provided.  This also enables nested paths such as
        ``settings.seed`` instead of only top-level ``dict.get`` keys.
        """
        k = (key or "").strip()
        if not k:
            raise msgpath.MsgPathError("context key is empty")
        kl = k.lower()
        if root == "global":
            if kl == "global" or kl.startswith("global.") or kl.startswith("global[") or k == "G" or k.startswith("G.") or k.startswith("G["):
                return k
        elif root == "flow":
            if kl == "flow" or kl.startswith("flow.") or kl.startswith("flow["):
                return k
        return f"{root}.{k}"

    def _runtime_path(self, key):
        k = (key or "").strip()
        if not k:
            raise msgpath.MsgPathError("runtime context key is empty")
        if k == "context":
            raise msgpath.MsgPathError("cannot replace runtime context root")
        if k.startswith("context."):
            k = k[len("context."):]
        elif k.startswith("context["):
            k = k[len("context"):]
        return k

    def _runtime_get(self, signal, key):
        sentinel = object()
        path = self._runtime_path(key)
        val = msgpath.get(path, signal.context, default=sentinel)
        if val is sentinel:
            raise msgpath.MsgPathError(f"runtime context key not found: {key}")
        return val

    def _runtime_set(self, signal, key, value):
        path = self._runtime_path(key)
        return msgpath.set(path, value, signal.context)

    def _context_get(self, root, key, signal, flow, glob):
        sentinel = object()
        path = self._ctx_path(root, key)
        val = msgpath.get(path, signal.msg, flow, glob, default=sentinel)
        if val is sentinel:
            raise msgpath.MsgPathError(f"{root} context key not found: {key}")
        return val

    def _context_set(self, root, key, value, signal, flow, glob):
        return msgpath.set(self._ctx_path(root, key), value, signal.msg, flow, glob)

    def process(self, signal, engine):
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            if self.mode == "FLOW_TO_MSG":
                val = self._context_get("flow", self.context_key, signal, flow, glob)
                msgpath.set(self.msg_path, val, signal.msg, flow, glob)
            elif self.mode == "GLOBAL_TO_MSG":
                val = self._context_get("global", self.context_key, signal, flow, glob)
                msgpath.set(self.msg_path, val, signal.msg, flow, glob)
            elif self.mode == "RUNTIME_TO_MSG":
                val = self._runtime_get(signal, self.context_key)
                msgpath.set(self.msg_path, val, signal.msg, flow, glob)
            elif self.mode == "MSG_TO_FLOW":
                val = expr.evaluate(self.get_value_expr(), self.expr_vars(signal, engine))
                self._context_set("flow", self.context_key, val, signal, flow, glob)
            elif self.mode == "MSG_TO_GLOBAL":
                val = expr.evaluate(self.get_value_expr(), self.expr_vars(signal, engine))
                self._context_set("global", self.context_key, val, signal, flow, glob)
            elif self.mode == "MSG_TO_RUNTIME":
                val = expr.evaluate(self.get_value_expr(), self.expr_vars(signal, engine))
                self._runtime_set(signal, self.context_key, val)
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
    fx_color = (0.15, 0.36, 0.40)

    source_path: StringProperty(
        name="Source",
        default="payload",
        description="Message/context property to cache. Default is payload; you may also use msg.xxx / flow.xxx / Global.xxx when needed.",
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


@register_node
class PropertyGetNode(FxBaseNode):
    """Read a safe Blender full data path into a msg path."""
    bl_idname = "FxPropertyGet"
    bl_label = "Get Property"
    bl_icon = "RNA"
    category = "Property"
    fx_color = (0.16, 0.40, 0.26)

    path: StringProperty(name="Blender Full Path", default="")
    out_path: StringProperty(name="Target", default="payload")
    last_value: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "path", text="")
        layout.prop(self, "out_path")

    def draw_previews(self, context, layout):
        if self.last_value:
            box = layout.box(); box.scale_y = 0.8
            box.label(text=f"→ {self.last_value}", icon="CHECKMARK")

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
