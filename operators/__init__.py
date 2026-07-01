"""Operators: engine start/stop, manual fire, modal input listener, AI ops."""
from __future__ import annotations

import json
from types import SimpleNamespace
import bpy
from bpy.types import Operator
from bpy.props import StringProperty, EnumProperty

from ..core.runtime import RUNTIME
from ..core import path as path_utils
from ..core.signal import Signal
from ..prefs import get_preferences


def _build_signal_from_upstream(tree, node, engine):
    """Build a Signal with msg.payload populated from upstream Cache/Debug nodes.

    Manual Generate operators run outside a flow, so signal.msg is normally empty,
    causing reference injection (which defaults to payload) to fail.  This helper
    walks the input Flow links backwards (max 2 hops) looking for nodes that store
    a recent message value:
      - FxCache : node.get("_cache_data")
      - FxDebug : node.get("_preview")
    If found, the value is used as payload, so Use Reference Data actually works
    when clicking Generate in the node UI.
    """
    msg = {}
    # try to find upstream cache/debug data
    try:
        visited = set()
        frontier = [(node, 0)]
        while frontier:
            n, depth = frontier.pop(0)
            if n.name in visited or depth > 2:
                continue
            visited.add(n.name)
            # try to extract a payload-like value from this node
            payload = None
            bl_id = getattr(n, "bl_idname", "")
            if bl_id == "FxCache":
                raw = n.get("_cache_data", "")
                if raw:
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        pass
            elif bl_id == "FxDebug":
                raw = n.get("_preview", "")
                if raw:
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        pass
            if payload is not None:
                msg["payload"] = payload
                break
            # walk upstream flow inputs
            try:
                for inp in n.inputs:
                    if not inp.is_linked:
                        continue
                    for link in inp.links:
                        from_node = link.from_node
                        if from_node:
                            frontier.append((from_node, depth + 1))
            except Exception:
                pass
    except Exception:
        pass
    return Signal(payload=msg, context={})


class FXNODES_OT_start(Operator):
    bl_idname = "fx_nodes.start_engine"
    bl_label = "Start Fx Nodes Engine"
    bl_description = "启动事件引擎：定时/帧/按键/点击等触发器开始工作"

    def execute(self, context):
        RUNTIME.start()
        self.report({'INFO'}, "Fx Nodes engine started")
        return {'FINISHED'}


class FXNODES_OT_stop(Operator):
    bl_idname = "fx_nodes.stop_engine"
    bl_label = "Stop Fx Nodes Engine"

    def execute(self, context):
        RUNTIME.stop()
        self.report({'INFO'}, "Fx Nodes engine stopped")
        return {'FINISHED'}


class FXNODES_OT_fire_node(Operator):
    bl_idname = "fx_nodes.fire_node"
    bl_label = "Fire Node"
    tree_name: StringProperty()
    node_name: StringProperty()

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        if not tree:
            self.report({'ERROR'}, "tree not found"); return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if not node:
            self.report({'ERROR'}, "node not found"); return {'CANCELLED'}
        try:
            RUNTIME.fire_node(tree, node)
        except ReferenceError as e:
            self.report({'ERROR'}, f"Fx node tree was removed/stale; reopen/select the live tree and try again: {e}")
            return {'CANCELLED'}
        except Exception as e:
            try:
                node._error = f"{type(e).__name__}: {e}"
            except Exception:
                pass
            self.report({'ERROR'}, f"Fx node run failed: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


class FXNODES_OT_input_listener(Operator):
    """Modal operator capturing keyboard/mouse for Key/Click triggers."""
    bl_idname = "fx_nodes.input_listener"
    bl_label = "Fx Nodes Input Listener"

    def modal(self, context, event):
        if not RUNTIME.running:
            RUNTIME._modal_running = False
            return {'CANCELLED'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TIMER'}:
            return {'PASS_THROUGH'}
        try:
            RUNTIME.handle_input_event(event)
        except Exception:
            pass
        return {'PASS_THROUGH'}     # never swallow events

    def invoke(self, context, event):
        RUNTIME._modal_running = True
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class FXNODES_OT_paste_property_menu(Operator):
    """Popup menu for Shift+V: choose Get or Set Property."""
    bl_idname = "fx_nodes.paste_property_menu"
    bl_label = "Paste Property Node"
    bl_description = "Shift+V：选择把剪贴板里的 Copy Full Data Path 创建为 Get 或 Set Property 节点"

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return (getattr(space, "tree_type", "") == "FxNodeTree"
                and getattr(space, "edit_tree", None) is not None)

    def _clipboard_path(self, context):
        wm = getattr(context, "window_manager", None)
        return (getattr(wm, "clipboard", "") if wm else "").strip()

    def execute(self, context):
        data_path = self._clipboard_path(context)
        try:
            path_utils.validate_path(data_path)
        except path_utils.PathError as e:
            self.report({'ERROR'}, f"剪贴板不是有效的 Blender 完整路径: {e}")
            return {'CANCELLED'}

        def draw_menu(menu, _context):
            layout = menu.layout
            layout.operator_context = 'EXEC_DEFAULT'
            layout.label(text=path_utils.compact_path_label(data_path, 72), icon="RNA")
            layout.separator()
            op = layout.operator("fx_nodes.paste_property_node", text="Get Property", icon="RNA")
            op.mode = "GET"; op.data_path = data_path
            op = layout.operator("fx_nodes.paste_property_node", text="Set Property", icon="RNA")
            op.mode = "SET"; op.data_path = data_path

        context.window_manager.popup_menu(draw_menu, title="Paste Full Data Path", icon="RNA")
        return {'FINISHED'}

    def invoke(self, context, event):
        return self.execute(context)


class FXNODES_OT_paste_property_node(Operator):
    """Create one Property node from Blender's copied full data path."""
    bl_idname = "fx_nodes.paste_property_node"
    bl_label = "Paste Property Node"
    bl_description = "Shift+V：把剪贴板里的 Copy Full Data Path 解析为 Get 或 Set Property 节点"
    # Do not use REGISTER here: Blender's redo panel can re-run the operator
    # after the user edited the generated node, creating/resetting nodes from
    # the current clipboard.  The node itself is undoable; redo is not useful.
    bl_options = {'UNDO'}

    data_path: StringProperty(
        name="Full Data Path",
        default="",
        options={'HIDDEN'},
    )

    mode: EnumProperty(
        name="Node Type",
        items=[
            ("GET", "Get Property", "读取完整路径，并输出到 msg 路径"),
            ("SET", "Set Property", "设置完整路径，使用输入值或 Value Expr"),
        ],
        default="GET",
    )

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return (getattr(space, "tree_type", "") == "FxNodeTree"
                and getattr(space, "edit_tree", None) is not None)

    def _clipboard_path(self, context):
        wm = getattr(context, "window_manager", None)
        return (getattr(wm, "clipboard", "") if wm else "").strip()

    def invoke(self, context, event):
        data_path = self.data_path or self._clipboard_path(context)
        try:
            path_utils.validate_path(data_path)
        except path_utils.PathError as e:
            self.report({'ERROR'}, f"剪贴板不是有效的 Blender 完整路径: {e}")
            return {'CANCELLED'}
        self.data_path = data_path
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        data_path = self.data_path or self._clipboard_path(context)
        layout.label(text="Create node from copied full data path:")
        box = layout.box()
        box.label(text=path_utils.compact_path_label(data_path, 64), icon="RNA")
        layout.prop(self, "mode", expand=True)

    def execute(self, context):
        data_path = self.data_path or self._clipboard_path(context)
        try:
            path_utils.validate_path(data_path)
        except path_utils.PathError as e:
            self.report({'ERROR'}, f"剪贴板不是有效的 Blender 完整路径: {e}")
            return {'CANCELLED'}
        self.data_path = data_path

        tree = context.space_data.edit_tree
        nodes = tree.nodes
        node_type = "FxPropertyGet" if self.mode == "GET" else "FxPropertySet"
        node = nodes.new(node_type)
        node.path = data_path
        if self.mode == "GET":
            node.out_path = "payload"
        else:
            node.value_expr = "payload"

        base = getattr(context.space_data, "cursor_location", None)
        try:
            x, y = float(base.x), float(base.y)
        except Exception:
            try:
                x, y = float(base[0]), float(base[1])
            except Exception:
                x, y = 0.0, 0.0
        node.location = (x, y)

        try:
            for n in nodes:
                n.select = False
            node.select = True
            nodes.active = node
        except Exception:
            pass

        label = "Get" if self.mode == "GET" else "Set"
        self.report({'INFO'}, f"已创建 {label} Property: {path_utils.compact_path_label(data_path)}")
        return {'FINISHED'}


class FXNODES_OT_open_text_editor(Operator):
    bl_idname = "fx_nodes.open_text_editor"
    bl_label = "Open Text Editor"
    bl_description = "Open the associated Text datablock in a Blender Text Editor area"

    text_name: StringProperty(default="")

    def execute(self, context):
        if not self.text_name:
            self.report({'ERROR'}, "No Text datablock selected")
            return {'CANCELLED'}
        text = bpy.data.texts.get(self.text_name)
        if text is None:
            self.report({'ERROR'}, f"Text not found: {self.text_name}")
            return {'CANCELLED'}
        area = next((a for a in context.window.screen.areas if a.type == 'TEXT_EDITOR'), None)
        if area is None:
            self.report({'INFO'}, f"Text created: {text.name}. Open a Text Editor area to edit it.")
            return {'FINISHED'}
        space = next((s for s in area.spaces if s.type == 'TEXT_EDITOR'), area.spaces.active)
        space.text = text
        self.report({'INFO'}, f"Opened Text: {text.name}")
        return {'FINISHED'}


class FXNODES_OT_function_new_text(Operator):
    bl_idname = "fx_nodes.function_new_text"
    bl_label = "Create Function Text"
    bl_description = "Create or open a multi-line Text datablock for this Function node"
    bl_options = {'REGISTER', 'UNDO'}

    tree_name: StringProperty()
    node_name: StringProperty()

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        node = tree.nodes.get(self.node_name) if tree else None
        if node is None:
            self.report({'ERROR'}, "Function node not found")
            return {'CANCELLED'}
        if getattr(node, "code_text_name", "") and bpy.data.texts.get(node.code_text_name):
            text = bpy.data.texts[node.code_text_name]
        else:
            base = f"Fx Function - {node.name}"
            name = base
            i = 1
            while bpy.data.texts.get(name):
                i += 1
                name = f"{base}.{i:03d}"
            text = bpy.data.texts.new(name)
            text.write(node.code or "# msg is a dict. You may import modules.\nmsg['payload'] = msg.get('payload')\nreturn msg")
            node.code_text_name = text.name
        self.report({'INFO'}, f"Function Text ready: {text.name}")
        return {'FINISHED'}


class FXNODES_OT_node_new_text(Operator):
    bl_idname = "fx_nodes.node_new_text"
    bl_label = "Create Node Text"
    bl_description = "Create or link a multi-line Text datablock for this node property"
    bl_options = {'REGISTER', 'UNDO'}

    tree_name: StringProperty()
    node_name: StringProperty()
    prop_name: StringProperty(default="code_text_name")
    fallback_prop: StringProperty(default="code")
    prefix: StringProperty(default="Fx Text")

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        node = tree.nodes.get(self.node_name) if tree else None
        if node is None:
            self.report({'ERROR'}, "Node not found")
            return {'CANCELLED'}
        current_name = getattr(node, self.prop_name, "")
        if current_name and bpy.data.texts.get(current_name):
            text = bpy.data.texts[current_name]
        else:
            base = f"{self.prefix} - {node.name}"
            name = base
            i = 1
            while bpy.data.texts.get(name):
                i += 1
                name = f"{base}.{i:03d}"
            text = bpy.data.texts.new(name)
            fallback_content = getattr(node, self.fallback_prop, "") or ""
            if fallback_content:
                text.write(fallback_content)
            setattr(node, self.prop_name, text.name)
        self.report({'INFO'}, f"Text ready: {text.name}")
        return {'FINISHED'}


class FXNODES_OT_debug_copy_json(Operator):
    bl_idname = "fx_nodes.debug_copy_json"
    bl_label = "Copy JSON"
    bl_description = "Copy this Debug node's preview data to system clipboard"

    tree_name: StringProperty()
    node_name: StringProperty()

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        node = tree.nodes.get(self.node_name) if tree else None
        if node is None:
            return {'CANCELLED'}
        raw = node.get("_preview", "{}")
        try:
            formatted = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except Exception:
            formatted = raw
        context.window_manager.clipboard = formatted
        self.report({'INFO'}, f"Copied {len(formatted)} chars to clipboard")
        return {'FINISHED'}


class FXNODES_OT_debug_clear_node(Operator):
    bl_idname = "fx_nodes.debug_clear_node"
    bl_label = "Clear Debug Node"
    bl_description = "Clear one Debug node preview and its Text log"
    bl_options = {'REGISTER', 'UNDO'}

    tree_name: StringProperty()
    node_name: StringProperty()

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        node = tree.nodes.get(self.node_name) if tree else None
        if node is None or getattr(node, "bl_idname", "") != "FxDebug":
            self.report({'ERROR'}, "Debug node not found")
            return {'CANCELLED'}
        try:
            node["_preview"] = "{}"
            node.fire_count = 0
            if getattr(node, "debug_text_name", ""):
                txt = bpy.data.texts.get(node.debug_text_name)
                if txt:
                    txt.clear()
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class FXNODES_OT_debug_clear_all(Operator):
    bl_idname = "fx_nodes.debug_clear_all"
    bl_label = "Clear All Debug"
    bl_description = "Clear all Debug previews and Text logs in the current Fx node tree"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None)
        if tree is None:
            return {'CANCELLED'}
        count = 0
        for node in tree.nodes:
            if getattr(node, "bl_idname", "") != "FxDebug":
                continue
            node["_preview"] = "{}"
            node.fire_count = 0
            if getattr(node, "debug_text_name", ""):
                txt = bpy.data.texts.get(node.debug_text_name)
                if txt:
                    txt.clear()
            count += 1
        self.report({'INFO'}, f"Cleared {count} Debug node(s)")
        return {'FINISHED'}


class FXNODES_OT_debug_clear_errors(Operator):
    bl_idname = "fx_nodes.debug_clear_errors"
    bl_label = "Clear Debug Errors"
    bl_description = "Clear Fx node runtime errors shown in the Debug panel"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None)
        if tree is None:
            return {'CANCELLED'}
        count = 0
        for node in tree.nodes:
            if getattr(node, "_error", ""):
                node._error = ""
                count += 1
        eng = RUNTIME.engines.get(tree.name)
        if eng is not None:
            count += len(getattr(eng.stats, "errors", {}) or {})
            eng.stats.errors.clear()
        self.report({'INFO'}, f"Cleared {count} error(s)")
        return {'FINISHED'}


class FXNODES_OT_cache_clear_node(Operator):
    bl_idname = "fx_nodes.cache_clear_node"
    bl_label = "Clear Cache Node"
    bl_description = "Clear one Cache node preview and stored cache"
    bl_options = {'REGISTER', 'UNDO'}

    tree_name: StringProperty()
    node_name: StringProperty()

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        node = tree.nodes.get(self.node_name) if tree else None
        if node is None or getattr(node, "bl_idname", "") != "FxCache":
            self.report({'ERROR'}, "Cache node not found")
            return {'CANCELLED'}
        try:
            if hasattr(node, "clear_cache"):
                node.clear_cache()
            else:
                node["_cache_data"] = ""
                node["_preview"] = "{}"
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class FXNODES_OT_test_ai(Operator):
    bl_idname = "fx_nodes.test_ai"
    bl_label = "Test AI Connection"

    def execute(self, context):
        from ..nodes.ai.provider import make_provider
        p = get_preferences(context)
        prov = make_provider("openai-compat", base_url=p.ai_base_url,
                             api_key=p.ai_api_key, model=p.ai_model)
        try:
            out = prov.complete([{"role": "user", "content": "Reply with the single word: OK"}],
                                max_tokens=5)
            self.report({'INFO'}, f"AI OK: {out[:40]}")
        except Exception as e:
            self.report({'ERROR'}, f"AI failed: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


class FXNODES_OT_ai_generate_expr(Operator):
    bl_idname = "fx_nodes.ai_generate_expr"
    bl_label = "AI Generate Expression"
    node_name: StringProperty()

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None)
        if not tree:
            self.report({'ERROR'}, "No active Fx Node Tree")
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}
        from ..nodes.ai.provider import make_provider
        p = get_preferences(context)
        if not p.allow_ai:
            self.report({'ERROR'}, "AI disabled in prefs"); return {'CANCELLED'}
        prov = make_provider("openai-compat", base_url=node.base_url_override or p.ai_base_url,
                             api_key=p.ai_api_key, model=node.model_override or p.ai_model)
        try:
            from ..nodes.ai import _inject_reference_context, _template
            # Get a real engine so flow/global context can be read for reference injection.
            engine = RUNTIME.get_engine(tree)
            # Build a signal with payload populated from upstream Cache/Debug nodes
            # if available – this fixes "reference message cannot be injected"
            # when clicking Generate manually.
            signal = _build_signal_from_upstream(tree, node, engine)
            # Template the ask string the same way runtime does, then inject reference.
            ask_val = getattr(node, "get_ask", lambda: node.ask)()
            ask_templated = _template(ask_val, signal)
            user_text = _inject_reference_context(node, engine, signal, ask_templated)
            msgs = [{"role": "system", "content": node.SYS},
                    {"role": "user", "content": user_text}]
            node["_last_messages"] = json.dumps(msgs, ensure_ascii=False)
            text = prov.complete(msgs, temperature=0.2, max_tokens=128)
        except Exception as e:
            self.report({'ERROR'}, str(e)); return {'CANCELLED'}
        if node.validate_and_store(text):
            # report reference status if any
            ref_info = getattr(node, "last_result", "")
            if ref_info.startswith("ref "):
                self.report({'INFO'}, f"OK: {node.generated} | {ref_info}")
            else:
                self.report({'INFO'}, f"OK: {node.generated}")
        else:
            self.report({'ERROR'}, node._error)
        return {'FINISHED'}


class FXNODES_OT_ai_scene_plan(Operator):
    bl_idname = "fx_nodes.ai_scene_plan"
    bl_label = "AI Scene Plan"
    node_name: StringProperty()

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None)
        if not tree:
            self.report({'ERROR'}, "No active Fx Node Tree")
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}
        from ..nodes.ai.provider import make_provider
        p = get_preferences(context)
        if not p.allow_ai:
            self.report({'ERROR'}, "AI disabled in prefs"); return {'CANCELLED'}
        prov = make_provider("openai-compat", base_url=node.base_url_override or p.ai_base_url,
                             api_key=p.ai_api_key, model=node.model_override or p.ai_model)
        try:
            from ..nodes.ai import _inject_reference_context, _template
            engine = RUNTIME.get_engine(tree)
            signal = _build_signal_from_upstream(tree, node, engine)
            ask_val = getattr(node, "get_ask", lambda: node.ask)()
            ask_templated = _template(ask_val, signal)
            user_text = _inject_reference_context(node, engine, signal, ask_templated)
            msgs = [{"role": "system", "content": node.SYS},
                    {"role": "user", "content": user_text}]
            node["_last_messages"] = json.dumps(msgs, ensure_ascii=False)
            text = prov.complete(msgs, temperature=0.1, max_tokens=1024)
            if hasattr(node, "set_plan_text"):
                node.set_plan_text(text)
            else:
                text = text.strip().strip("`")
                if text.startswith("json"):
                    text = text[4:]
                json.loads(text)   # validate
                node.plan = text
            ref_info = getattr(node, "last_result", "")
            if ref_info.startswith("ref "):
                self.report({'INFO'}, f"Script generated | {ref_info}")
            else:
                self.report({'INFO'}, "Script generated. Click Run to execute.")
        except Exception as e:
            self.report({'ERROR'}, f"plan failed: {e}"); return {'CANCELLED'}
        return {'FINISHED'}


class FXNODES_OT_ai_chat_generate(Operator):
    bl_idname = "fx_nodes.ai_chat_generate"
    bl_label = "AI Chat Generate"
    bl_description = "Manually generate a chat response (for testing reference injection, etc.)"
    node_name: StringProperty()

    def execute(self, context):
        tree = getattr(context.space_data, "edit_tree", None)
        if not tree:
            self.report({'ERROR'}, "No active Fx Node Tree")
            return {'CANCELLED'}
        node = tree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}
        from ..nodes.ai.provider import make_provider
        p = get_preferences(context)
        if not p.allow_ai:
            self.report({'ERROR'}, "AI disabled in prefs"); return {'CANCELLED'}
        prov = make_provider("openai-compat",
                             base_url=node.base_url_override or p.ai_base_url,
                             api_key=p.ai_api_key,
                             model=node.model_override or p.ai_model)
        try:
            from ..nodes.ai import _inject_reference_context, _template
            from ..core import msgpath
            engine = RUNTIME.get_engine(tree)
            signal = _build_signal_from_upstream(tree, node, engine)
            prompt_val = getattr(node, "get_prompt", lambda: node.prompt)()
            system_val = getattr(node, "get_system", lambda: node.system)()
            prompt_templated = _template(prompt_val, signal)
            user_text = _inject_reference_context(node, engine, signal, prompt_templated)
            msgs = [
                {"role": "system", "content": system_val},
                {"role": "user", "content": user_text},
            ]
            node["_last_messages"] = json.dumps(msgs, ensure_ascii=False)
            text = prov.complete(msgs, temperature=node.temperature, max_tokens=512)
            # Store result like runtime does
            node._error = ""
            node.last_result = text or ""
            try:
                msgpath.set(node.out_key, text, signal.msg,
                            node.flow_context(engine), node.global_context(engine))
            except Exception as e:
                node._error = str(e)
                self.report({'ERROR'}, node._error)
                return {'CANCELLED'}
            ref_info = getattr(node, "last_result", "")
            self.report({'INFO'}, f"Chat OK ({len(text)} chars)" + (f" | {ref_info}" if ref_info.startswith("ref ") else ""))
        except Exception as e:
            node._error = str(e)
            self.report({'ERROR'}, f"chat failed: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


CLASSES = [
    FXNODES_OT_start, FXNODES_OT_stop, FXNODES_OT_fire_node, FXNODES_OT_input_listener,
    FXNODES_OT_paste_property_menu, FXNODES_OT_paste_property_node,
    FXNODES_OT_open_text_editor, FXNODES_OT_function_new_text, FXNODES_OT_node_new_text,
    FXNODES_OT_debug_clear_node, FXNODES_OT_debug_copy_json, FXNODES_OT_debug_clear_all, FXNODES_OT_debug_clear_errors,
    FXNODES_OT_cache_clear_node,
    FXNODES_OT_test_ai, FXNODES_OT_ai_generate_expr, FXNODES_OT_ai_scene_plan,
    FXNODES_OT_ai_chat_generate,
]


_ADDON_KEYMAPS = []


def register_keymaps():
    """Register Shift+V in the Node Editor for full data path paste."""
    try:
        wm = bpy.context.window_manager
        kc = wm.keyconfigs.addon
        if kc is None:
            return
        km = kc.keymaps.new(name="Node Editor", space_type='NODE_EDITOR')
        kmi = km.keymap_items.new("fx_nodes.paste_property_menu", type='V', value='PRESS', shift=True)
        _ADDON_KEYMAPS.append((km, kmi))
    except Exception:
        # Headless tests / restricted contexts.
        pass


def unregister_keymaps():
    for km, kmi in _ADDON_KEYMAPS:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _ADDON_KEYMAPS.clear()
