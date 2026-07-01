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
import math
import random
import traceback
import bpy
from bpy.props import StringProperty, FloatProperty, IntProperty, EnumProperty, BoolProperty

from ...core.base import FxBaseNode
from ...core.registry import register_node
from ...core import expr, msgpath
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


def _inject_reference_context(node, engine, signal, text: str) -> str:
    """Append optional cached/reference context for AI nodes.

    Users can point an AI node at any msg/flow/global path. By Node-RED
    convention the main message still lives in ``payload``; this is only an
    optional extra reference source.
    """
    if not getattr(node, "use_reference_data", False):
        return text
    ref_path = (getattr(node, "reference_path", "") or "").strip()
    if not ref_path:
        return text

    # Validate path syntax first – msgpath.get swallows errors which makes
    # debugging reference injection very hard.
    try:
        msgpath.parse(ref_path)
    except Exception as e:
        node._error = f"Reference path invalid: {ref_path} – {e}"
        node.last_result = f"ref bad path: {ref_path}"
        return text

    # Use a sentinel to distinguish "key missing / read error" from an
    # actual stored None / empty value.
    _MISS = object()
    msg = getattr(signal, "msg", {}) if signal is not None else {}
    flow_ctx = node.flow_context(engine) if engine is not None else {}
    global_ctx = node.global_context(engine) if engine is not None else {}
    try:
        ref = msgpath.get(ref_path, msg, flow_ctx, global_ctx, default=_MISS)
    except Exception as e:
        node._error = f"Reference read failed: {e}"
        ref = _MISS

    if ref is _MISS:
        node.last_result = f"ref missing: {ref_path}"
        # Don't treat missing as fatal – just skip injection so the AI
        # still runs with the base prompt.
        return text

    if ref in (None, "", {}, []):
        node.last_result = f"ref empty: {ref_path}"
        return text
    try:
        ref_text = json.dumps(ref, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        ref_text = repr(ref)
    node.last_result = f"ref ok: {ref_path} ({len(ref_text)} chars)"
    return f"{text}\n\nReference data ({ref_path}):\n{ref_text}"


def _strip_code_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t.strip().strip("`").strip()


def _extract_expression(text: str) -> str:
    """Extract one sandbox expression from occasionally chatty model output.

    The AI expression node must store an expression, not Python statements.
    Models often return fences, ``return ...``, ``payload = ...`` or a short
    explanation.  This helper accepts those common forms, then validates each
    candidate with the sandbox compiler.
    """
    raw = _strip_code_fence(text)
    if not raw:
        raise expr.ExprError("AI 没有返回表达式")

    candidates = []
    candidates.append(raw)
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith(("expression:", "expr:", "表达式:")):
            line = line.split(":", 1)[1].strip()
        if line.startswith("return "):
            line = line[7:].strip()
        # Accept common mistaken assignment formats, but only use the RHS.
        if "=" in line and not any(op in line for op in ("==", "!=", "<=", ">=")):
            lhs, rhs = line.split("=", 1)
            if lhs.strip().replace(".", "").replace("_", "").isalnum():
                line = rhs.strip()
        candidates.append(line.rstrip(";"))

    errors = []
    seen = set()
    for cand in candidates:
        cand = cand.strip()
        if not cand or cand in seen:
            continue
        seen.add(cand)
        try:
            expr.compile_expr(cand)
            return cand
        except expr.ExprError as e:
            errors.append(f"{cand[:48]} -> {e}")
    raise expr.ExprError("无法从 AI 输出中提取安全表达式: " + "; ".join(errors[:3]))


class _AIBase(FxBaseNode):
    category = "AI"
    fx_color = (0.40, 0.18, 0.46)

    base_url_override: StringProperty(name="Base URL", default="")
    model_override: StringProperty(name="Model", default="")
    temperature: FloatProperty(name="Temp", default=0.7, min=0.0, max=2.0)
    last_result: StringProperty(default="")
    use_reference_data: BoolProperty(
        name="Use Reference Data",
        default=False,
        description="从 msg/flow/global 路径读取缓存/前置信息，并追加给 AI 作为参考",
    )
    reference_path: StringProperty(
        name="Reference",
        default="payload",
        description="Optional extra AI reference property. Default is payload; change when you explicitly want payload / flow.xxx / Global.xxx scene context.",
    )

    def draw_reference_ui(self, layout):
        layout.prop(self, "use_reference_data")
        if self.use_reference_data:
            layout.prop(self, "reference_path")

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
    """AI chat: prompt templates msg/context values and stores through msgpath."""
    bl_idname = "FxAIChat"
    bl_label = "AI Chat"
    bl_icon = "OUTLINER_OB_LIGHT"

    system: StringProperty(name="System", default="You are a helpful assistant inside Blender.")
    system_text_name: StringProperty(
        name="System Text",
        default="",
        description="Optional Blender Text datablock for multi-line system prompt.",
    )
    prompt: StringProperty(name="Prompt", default="Describe a procedural city in one sentence.")
    prompt_text_name: StringProperty(
        name="Prompt Text",
        default="",
        description="Optional Blender Text datablock for multi-line user prompt.",
    )
    out_key: StringProperty(
        name="Target",
        default="payload",
        description="Where the generated message value is written. Default is payload; change only when you explicitly want another property.",
    )
    generate_on_flow: BoolProperty(
        name="Generate On Flow",
        default=False,
        description="Allow runtime AI generation when a flow reaches this node. Disabled by default because it is slow and network-dependent.",
    )

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def get_system(self):
        return self.get_text_content("system_text_name", "system")

    def get_prompt(self):
        return self.get_text_content("prompt_text_name", "prompt")

    def draw_body(self, context, layout):
        self.draw_text_row(layout, "system_text_name", "system", label="Sys", prefix="Fx AI System")
        self.draw_text_row(layout, "prompt_text_name", "prompt", label="Prompt", prefix="Fx AI Prompt")
        row = layout.row(align=True)
        op = row.operator("fx_nodes.ai_chat_generate", text="Generate", icon="FILE_REFRESH")
        op.node_name = self.name
        tree = getattr(context.space_data, "edit_tree", None)
        if tree is not None:
            run_op = row.operator("fx_nodes.fire_node", text="Run", icon="PLAY")
            run_op.tree_name = tree.name
            run_op.node_name = self.name
        layout.prop(self, "out_key")
        layout.prop(self, "generate_on_flow")
        self.draw_reference_ui(layout)
        col = layout.column(align=True)
        col.prop(self, "model_override", text="model")
        col.prop(self, "temperature")

    def draw_previews(self, context, layout):
        if self.last_result:
            box = layout.box(); box.scale_y = 0.8
            box.label(text="AI Response Preview:", icon="CHECKMARK")
            for line in self.last_result.splitlines()[:6]:
                box.label(text=line[:120])

    def process(self, signal, engine):
        if not self.generate_on_flow:
            self._error = "运行时 AI 生成默认关闭；如需流程触发，请开启 Generate On Flow"
            return []
        user_prompt = _inject_reference_context(self, engine, signal, _template(self.get_prompt(), signal))
        msgs = [
            {"role": "system", "content": self.get_system()},
            {"role": "user", "content": user_prompt},
        ]
        self["_last_messages"] = json.dumps(msgs, ensure_ascii=False)
        cont = signal.child()

        def done(text, err):
            if err:
                self._error = err; return
            self._error = ""
            self.last_result = text or ""
            try:
                msgpath.set(self.out_key, text, cont.msg, self.flow_context(engine), self.global_context(engine))
            except msgpath.MsgPathError as e:
                self._error = str(e); return
            cont_engine = engine
            for out_sock, _ in [("▶", None)]:
                cont_engine.continue_from(self.node_uid, out_sock, cont) if hasattr(cont_engine, "continue_from") else None

        self._run_async(engine, msgs, done)
        return []   # downstream fired by callback
