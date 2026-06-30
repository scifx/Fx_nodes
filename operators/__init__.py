"""Operators: engine start/stop, manual fire, modal input listener, AI ops."""
from __future__ import annotations

import json
import bpy
from bpy.types import Operator
from bpy.props import StringProperty

from ..core.runtime import RUNTIME


class NEXUS_OT_start(Operator):
    bl_idname = "nexus.start_engine"
    bl_label = "Start NEXUS Engine"
    bl_description = "启动事件引擎：定时/帧/按键/点击等触发器开始工作"

    def execute(self, context):
        RUNTIME.start()
        self.report({'INFO'}, "NEXUS engine started")
        return {'FINISHED'}


class NEXUS_OT_stop(Operator):
    bl_idname = "nexus.stop_engine"
    bl_label = "Stop NEXUS Engine"

    def execute(self, context):
        RUNTIME.stop()
        self.report({'INFO'}, "NEXUS engine stopped")
        return {'FINISHED'}


class NEXUS_OT_fire_node(Operator):
    bl_idname = "nexus.fire_node"
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


class NEXUS_OT_input_listener(Operator):
    """Modal operator capturing keyboard/mouse for Key/Click triggers."""
    bl_idname = "nexus.input_listener"
    bl_label = "NEXUS Input Listener"

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


class NEXUS_OT_test_ai(Operator):
    bl_idname = "nexus.test_ai"
    bl_label = "Test AI Connection"

    def execute(self, context):
        from ..nodes.ai.provider import make_provider
        p = context.preferences.addons["nexus_nodes"].preferences
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


class NEXUS_OT_ai_generate_expr(Operator):
    bl_idname = "nexus.ai_generate_expr"
    bl_label = "AI Generate Expression"
    node_name: StringProperty()

    def execute(self, context):
        node = context.space_data.edit_tree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}
        from ..nodes.ai.provider import make_provider
        p = context.preferences.addons["nexus_nodes"].preferences
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


class NEXUS_OT_ai_scene_plan(Operator):
    bl_idname = "nexus.ai_scene_plan"
    bl_label = "AI Scene Plan"
    node_name: StringProperty()

    def execute(self, context):
        node = context.space_data.edit_tree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}
        from ..nodes.ai.provider import make_provider
        p = context.preferences.addons["nexus_nodes"].preferences
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
    NEXUS_OT_start, NEXUS_OT_stop, NEXUS_OT_fire_node, NEXUS_OT_input_listener,
    NEXUS_OT_test_ai, NEXUS_OT_ai_generate_expr, NEXUS_OT_ai_scene_plan,
]
