"""AI nodes: bring LLM intelligence into the node graph.

Three flavors:
  AIChatNode          prompt -> text (templated with msg values)
  AIExpressionNode    natural language -> a SANDBOXED expression (validated!)
  AISceneCommandNode  natural language -> structured, validated action plan

Network is async-offloaded to a worker thread by the runtime so the UI never
blocks; the result is written back on the next timer tick.
"""
from __future__ import annotations

import json
import bpy
from bpy.props import StringProperty, FloatProperty, IntProperty, EnumProperty, BoolProperty

from ...core.base import FxBaseNode
from ...core.registry import register_node
from ...core import expr
from .provider import make_provider
from ...prefs import get_preferences


def _get_prefs():
    try:
        return get_preferences(bpy.context)
    except Exception:
        return None


def _provider_from_prefs(node):
    p = _get_prefs()
    if p is None:
        raise RuntimeError("找不到插件偏好设置")
    base = node.base_url_override or p.ai_base_url
    model = node.model_override or p.ai_model
    return make_provider("openai-compat", base_url=base, api_key=p.ai_api_key, model=model)


def _template(s: str, signal) -> str:
    """Replace {key} in s with msg/context values."""
    v = dict(signal.msg); v.update(signal.context)
    try:
        return s.format(**v)
    except Exception:
        return s


class _AIBase(FxBaseNode):
    category = "AI"
    fx_color = (0.32, 0.12, 0.34)

    base_url_override: StringProperty(name="Base URL", default="")
    model_override: StringProperty(name="Model", default="")
    temperature: FloatProperty(name="Temp", default=0.7, min=0.0, max=2.0)
    last_result: StringProperty(default="")

    def _run_async(self, engine, messages, on_done, **opts):
        """Offload network to runtime worker if present; else call inline."""
        runner = getattr(engine, "run_async", None)

        def work():
            prov = _provider_from_prefs(self)
            return prov.complete(messages, temperature=self.temperature, **opts)

        if runner:
            runner(work, on_done, self.node_uid)
        else:
            try:
                on_done(work(), None)
            except Exception as e:
                on_done(None, str(e))


@register_node
class AIChatNode(_AIBase):
    """AI 对话：prompt 可用 {msg_key} 模板，结果写入 msg[out_key]。"""
    bl_idname = "FxAIChat"
    bl_label = "AI Chat"
    bl_icon = "OUTLINER_OB_LIGHT"

    system: StringProperty(name="System", default="You are a helpful assistant inside Blender.")
    prompt: StringProperty(name="Prompt", default="Describe a procedural city in one sentence.")
    out_key: StringProperty(name="Store As", default="ai_text")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "prompt", text="")
        layout.prop(self, "out_key")
        col = layout.column(align=True)
        col.prop(self, "model_override", text="model")
        col.prop(self, "temperature")
        if self.last_result:
            box = layout.box(); box.scale_y = 0.7
            box.label(text=self.last_result[:50], icon="CHECKMARK")

    def process(self, signal, engine):
        msgs = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": _template(self.prompt, signal)},
        ]
        cont = signal.child()

        def done(text, err):
            if err:
                self._error = err; return
            self._error = ""
            self.last_result = text or ""
            cont.set(self.out_key, text)
            # continue the flow from this node now that we have a result
            cont_engine = engine
            for out_sock, _ in [("▶", None)]:
                cont_engine.continue_from(self.node_uid, out_sock, cont) if hasattr(cont_engine, "continue_from") else None

        self._run_async(engine, msgs, done)
        return []   # downstream fired by callback


@register_node
class AIExpressionNode(_AIBase):
    """AI 表达式：用自然语言描述要的公式 → 生成并**校验**为安全沙箱表达式。"""
    bl_idname = "FxAIExpression"
    bl_label = "AI → Expression"
    bl_icon = "SCRIPTPLUGINS"

    ask: StringProperty(name="Describe", default="a wave that oscillates between 0 and 5 over time")
    generated: StringProperty(name="Generated", default="")
    out_key: StringProperty(name="Store As", default="result")

    SYS = ("You translate a natural-language description into ONE Python "
           "expression usable in a sandbox. Allowed: arithmetic, comparisons, "
           "and functions sin cos tan sqrt abs min max clamp lerp map_range "
           "noise floor ceil round pow; variables: time, frame, dt. "
           "Return ONLY the expression, no code fences, no explanation.")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "ask", text="")
        layout.operator("fx_nodes.ai_generate_expr", text="Generate", icon="SHADERFX").node_name = self.name
        if self.generated:
            box = layout.box()
            box.label(text=self.generated[:48], icon="SCRIPT")
        layout.prop(self, "out_key")

    def validate_and_store(self, text):
        candidate = text.strip().strip("`").splitlines()[0] if text else ""
        try:
            expr.compile_expr(candidate)   # sandbox validation
        except expr.ExprError as e:
            self._error = f"生成的表达式不安全/无效: {e}"
            return False
        self.generated = candidate
        self._error = ""
        return True

    def process(self, signal, engine):
        if not self.generated:
            return self.flow_out(signal)
        try:
            val = expr.evaluate(self.generated, self.expr_vars(signal, engine))
        except expr.ExprError as e:
            self._error = str(e); return []
        signal.set(self.out_key, val)
        return self.flow_out(signal)


@register_node
class AISceneCommandNode(_AIBase):
    """AI 场景指令：自然语言 → 结构化动作计划（JSON），校验后再执行。

    模型只能产出受限的指令集（create/transform/...），由本节点解释执行，
    绝不直接 exec 模型输出 —— 安全可控的'AI 驱动建模'。
    """
    bl_idname = "FxAISceneCommand"
    bl_label = "AI Scene Command"
    bl_icon = "OUTLINER_OB_GROUP_INSTANCE"

    ask: StringProperty(name="Instruction", default="create 5 cubes in a row")
    plan: StringProperty(default="")

    SYS = ("You output a JSON array of scene commands. Allowed command objects: "
           '{"op":"create","primitive":"cube|sphere|cylinder|cone|torus","location":[x,y,z],"size":n}. '
           "Return ONLY valid JSON, no prose, no code fences.")

    ALLOWED_PRIMS = {"cube", "sphere", "cylinder", "cone", "torus"}

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "ask", text="")
        layout.operator("fx_nodes.ai_scene_plan", text="Plan", icon="OUTLINER").node_name = self.name
        if self.plan:
            box = layout.box(); box.scale_y = 0.7
            try:
                n = len(json.loads(self.plan))
                box.label(text=f"{n} commands ready", icon="CHECKMARK")
            except Exception:
                box.label(text="invalid plan", icon="ERROR")

    def _execute_plan(self):
        try:
            cmds = json.loads(self.plan)
        except Exception as e:
            self._error = f"plan JSON 无效: {e}"; return
        prim_map = {"cube": "primitive_cube_add", "sphere": "primitive_uv_sphere_add",
                    "cylinder": "primitive_cylinder_add", "cone": "primitive_cone_add",
                    "torus": "primitive_torus_add"}
        for c in cmds if isinstance(cmds, list) else []:
            if not isinstance(c, dict) or c.get("op") != "create":
                continue
            prim = c.get("primitive")
            if prim not in self.ALLOWED_PRIMS:
                continue
            loc = c.get("location", [0, 0, 0])
            try:
                loc = tuple(float(x) for x in loc)[:3]
            except Exception:
                loc = (0, 0, 0)
            fn = getattr(bpy.ops.mesh, prim_map[prim])
            try:
                fn(location=loc)
            except Exception:
                pass
        self._error = ""

    def process(self, signal, engine):
        if self.plan:
            self._execute_plan()
        return self.flow_out(signal)
