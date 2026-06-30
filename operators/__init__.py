"""Operators: engine start/stop, manual fire, modal input listener, AI ops."""
from __future__ import annotations

import json
import bpy
from bpy.types import Operator
from bpy.props import StringProperty, EnumProperty

from ..core.runtime import RUNTIME
from ..core import path as path_utils
from ..prefs import get_preferences


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
        RUNTIME.fire_node(tree, node)
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
            op.mode = "GET"
            op = layout.operator("fx_nodes.paste_property_node", text="Set Property", icon="RNA")
            op.mode = "SET"

        context.window_manager.popup_menu(draw_menu, title="Paste Full Data Path", icon="RNA")
        return {'FINISHED'}

    def invoke(self, context, event):
        return self.execute(context)


class FXNODES_OT_paste_property_node(Operator):
    """Create one Property node from Blender's copied full data path."""
    bl_idname = "fx_nodes.paste_property_node"
    bl_label = "Paste Property Node"
    bl_description = "Shift+V：把剪贴板里的 Copy Full Data Path 解析为 Get 或 Set Property 节点"
    bl_options = {'REGISTER', 'UNDO'}

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
        data_path = self._clipboard_path(context)
        try:
            path_utils.validate_path(data_path)
        except path_utils.PathError as e:
            self.report({'ERROR'}, f"剪贴板不是有效的 Blender 完整路径: {e}")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        data_path = self._clipboard_path(context)
        layout.label(text="Create node from copied full data path:")
        box = layout.box()
        box.label(text=path_utils.compact_path_label(data_path, 64), icon="RNA")
        layout.prop(self, "mode", expand=True)

    def execute(self, context):
        data_path = self._clipboard_path(context)
        try:
            path_utils.validate_path(data_path)
        except path_utils.PathError as e:
            self.report({'ERROR'}, f"剪贴板不是有效的 Blender 完整路径: {e}")
            return {'CANCELLED'}

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
        node = context.space_data.edit_tree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}
        from ..nodes.ai.provider import make_provider
        p = get_preferences(context)
        if not p.allow_ai:
            self.report({'ERROR'}, "AI disabled in prefs"); return {'CANCELLED'}
        prov = make_provider("openai-compat", base_url=node.base_url_override or p.ai_base_url,
                             api_key=p.ai_api_key, model=node.model_override or p.ai_model)
        try:
            text = prov.complete(
                [{"role": "system", "content": node.SYS},
                 {"role": "user", "content": node.ask}], temperature=0.2, max_tokens=64)
        except Exception as e:
            self.report({'ERROR'}, str(e)); return {'CANCELLED'}
        if node.validate_and_store(text):
            self.report({'INFO'}, f"OK: {node.generated}")
        else:
            self.report({'ERROR'}, node._error)
        return {'FINISHED'}


class FXNODES_OT_ai_scene_plan(Operator):
    bl_idname = "fx_nodes.ai_scene_plan"
    bl_label = "AI Scene Plan"
    node_name: StringProperty()

    def execute(self, context):
        node = context.space_data.edit_tree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}
        from ..nodes.ai.provider import make_provider
        p = get_preferences(context)
        if not p.allow_ai:
            self.report({'ERROR'}, "AI disabled in prefs"); return {'CANCELLED'}
        prov = make_provider("openai-compat", base_url=node.base_url_override or p.ai_base_url,
                             api_key=p.ai_api_key, model=node.model_override or p.ai_model)
        try:
            text = prov.complete(
                [{"role": "system", "content": node.SYS},
                 {"role": "user", "content": node.ask}], temperature=0.1, max_tokens=512)
            text = text.strip().strip("`")
            if text.startswith("json"):
                text = text[4:]
            json.loads(text)   # validate
            node.plan = text
            self.report({'INFO'}, "Plan generated. Run engine to execute.")
        except Exception as e:
            self.report({'ERROR'}, f"plan failed: {e}"); return {'CANCELLED'}
        return {'FINISHED'}


CLASSES = [
    FXNODES_OT_start, FXNODES_OT_stop, FXNODES_OT_fire_node, FXNODES_OT_input_listener,
    FXNODES_OT_paste_property_menu, FXNODES_OT_paste_property_node,
    FXNODES_OT_test_ai, FXNODES_OT_ai_generate_expr, FXNODES_OT_ai_scene_plan,
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
