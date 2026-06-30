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
    """AI chat: prompt templates msg/context values and stores through msgpath."""
    bl_idname = "FxAIChat"
    bl_label = "AI Chat"
    bl_icon = "OUTLINER_OB_LIGHT"

    system: StringProperty(name="System", default="You are a helpful assistant inside Blender.")
    prompt: StringProperty(name="Prompt", default="Describe a procedural city in one sentence.")
    out_key: StringProperty(
        name="Store To",
        default="ai_text",
        description="Node-RED msg path: ai_text, payload, msg.ai.text, flow.last_ai, global.note",
    )

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
            try:
                msgpath.set(self.out_key, text, cont.msg, self.flow_context(engine), self.global_context(engine))
            except msgpath.MsgPathError as e:
                self._error = str(e); return
            # continue the flow from this node now that we have a result
            cont_engine = engine
            for out_sock, _ in [("▶", None)]:
                cont_engine.continue_from(self.node_uid, out_sock, cont) if hasattr(cont_engine, "continue_from") else None

        self._run_async(engine, msgs, done)
        return []   # downstream fired by callback


@register_node
class AIExpressionNode(_AIBase):
    """AI expression node in the current msg/flow/global paradigm.

    On flow input it ensures a safe sandbox expression exists, evaluates it
    against the current signal variables, stores the result through msgpath,
    then continues the flow.  Generation is async like AI Chat; manual
    Generate still exists for pre-building the expression.
    """
    bl_idname = "FxAIExpression"
    bl_label = "AI → Expression"
    bl_icon = "SCRIPTPLUGINS"

    ask: StringProperty(
        name="Describe",
        default="double the current payload",
        description="Natural-language description. May use {payload}, {topic}, or other msg/context template keys.",
    )
    generated: StringProperty(name="Expression", default="")
    out_key: StringProperty(
        name="Store To",
        default="payload",
        description="Node-RED msg path: payload, msg.foo, flow.foo, global.foo",
    )
    auto_generate: BoolProperty(
        name="Auto Generate",
        default=True,
        description="If no valid expression exists, call the AI during flow execution and continue when it returns.",
    )

    SYS = (
        "You convert a user's request into exactly ONE safe Python expression for Fx Nodes. "
        "Return ONLY the expression: no markdown, no assignment, no return statement, no explanation. "
        "This is an expression sandbox, not full Python. "
        "Available variables follow the Node-RED message model: "
        "msg is a dict, payload is msg.get('payload'), topic is msg.get('topic'), "
        "flow is the flow context dict, global_context and G are the global context dict. "
        "Top-level msg keys are also available as variables. Runtime variables include frame, time, dt, fps, wall, tick. "
        "Use dictionary indexing for dicts, for example msg['count'] or flow['seed']; do not use msg.count. "
        "Allowed literals: numbers, strings, booleans, None, lists, tuples, dicts. "
        "Allowed operators: arithmetic, comparisons, boolean and/or/not, conditional expression. "
        "Allowed functions: sin cos tan asin acos atan atan2 sqrt pow exp log floor ceil abs round "
        "radians degrees hypot min max sum len int float str bool clamp lerp mix map_range noise rand randint uniform range sign. "
        "Forbidden: imports, lambda, def, assignment, comprehensions, loops, attribute access except x y z w r g b a real imag, dunder names. "
        "Examples: payload * 2; clamp(payload, 0, 1); {'x': payload, 'frame': frame}; "
        "msg['items'][0]['name'] if len(msg['items']) else None"
    )

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "ask", text="")
        row = layout.row(align=True)
        row.operator("fx_nodes.ai_generate_expr", text="Generate", icon="SHADERFX").node_name = self.name
        row.prop(self, "auto_generate", text="Auto")
        if self.generated:
            box = layout.box()
            box.label(text=self.generated[:96], icon="SCRIPT")
        layout.prop(self, "out_key")
        col = layout.column(align=True)
        col.prop(self, "model_override", text="model")
        col.prop(self, "temperature")

    def validate_and_store(self, text):
        try:
            candidate = _extract_expression(text)
        except expr.ExprError as e:
            self._error = f"生成的表达式无效: {e}"
            return False
        self.generated = candidate
        self._error = ""
        return True

    def _evaluate_to_signal(self, signal, engine):
        val = expr.evaluate(self.generated, self.expr_vars(signal, engine))
        msgpath.set(self.out_key, val, signal.msg, self.flow_context(engine), self.global_context(engine))
        self.last_result = msgpath.compact(val, 80)
        self._error = ""
        return val

    def process(self, signal, engine):
        if self.generated:
            try:
                self._evaluate_to_signal(signal, engine)
            except (expr.ExprError, msgpath.MsgPathError) as e:
                self._error = str(e); return []
            return self.flow_out(signal)

        if not self.auto_generate:
            self._error = "没有表达式；点击 Generate 或开启 Auto Generate"
            return []

        msgs = [
            {"role": "system", "content": self.SYS},
            {"role": "user", "content": _template(self.ask, signal)},
        ]
        cont = signal.child()

        def done(text, err):
            if err:
                self._error = err; return
            if not self.validate_and_store(text or ""):
                return
            try:
                self._evaluate_to_signal(cont, engine)
            except (expr.ExprError, msgpath.MsgPathError) as e:
                self._error = str(e); return
            if hasattr(engine, "continue_from"):
                engine.continue_from(self.node_uid, "▶", cont)

        self._run_async(engine, msgs, done, max_tokens=96)
        return []


@register_node
class AISceneCommandNode(_AIBase):
    """AI scene script: natural language -> Blender Python script.

    This is the power-user AI scene node.  Unlike the previous restricted JSON
    command-plan node, it generates editable Blender Python and can execute it.
    The script is stored in a Blender Text datablock, shown as a preview on the
    node, and may use the current Node-RED msg/flow/global runtime values.
    """
    bl_idname = "FxAISceneCommand"
    bl_label = "AI Scene Script"
    bl_icon = "OUTLINER_OB_GROUP_INSTANCE"

    ask: StringProperty(name="Instruction", default="create 5 cubes in a row")
    # Backwards-compatible fallback storage.  Older files used ``plan``.
    plan: StringProperty(default="")
    script_text_name: StringProperty(
        name="Script Text",
        default="",
        description="Blender Text datablock containing the generated Python script.",
    )
    out_key: StringProperty(
        name="Store Script To",
        default="ai_scene_script",
        description="Node-RED msg path where the generated script text is written.",
    )
    result_key: StringProperty(
        name="Store Result To",
        default="ai_scene_result",
        description="Node-RED msg path where execution result metadata is written.",
    )
    execute_script: BoolProperty(
        name="Execute Script",
        default=True,
        description="Run the generated Blender Python script when a flow reaches this node. Full Python; review scripts before enabling in untrusted files.",
    )

    SYS = (
        "You generate Blender Python scripts for an Fx Nodes AI Scene Script node. "
        "Return ONLY executable Python code, no markdown fences, no prose. "
        "The code runs inside Blender with bpy, math, random already available. "
        "Runtime variables are also available: msg dict, payload, context dict, flow dict, global_context dict, node, engine. "
        "You may create, delete, transform, animate objects, create materials, modifiers, constraints, collections, cameras, lights, drivers, and keyframes. "
        "Prefer clear deterministic bpy code. Use object names and reusable helper functions when useful. "
        "For results, set a variable named result to a JSON-like dict, for example result = {'created': [obj.name]}. "
        "Do not call external network APIs, do not access files, and do not run subprocesses unless the user explicitly requested it. "
        "If modifying existing objects, handle missing objects gracefully. "
        "Return code only."
    )

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def _strip_script(self, text):
        t = _strip_code_fence(text)
        # Some models return a leading language tag after fence stripping.
        if t.startswith("python\n"):
            t = t[7:].strip()
        elif t.startswith("py\n"):
            t = t[3:].strip()
        return t

    def _script_text(self):
        try:
            return bpy.data.texts.get(self.script_text_name) if self.script_text_name else None
        except Exception:
            return None

    def _ensure_script_text(self):
        try:
            name = self.script_text_name or f"Fx Scene Script - {self.name}"
            txt = bpy.data.texts.get(name) or bpy.data.texts.new(name)
            if self.script_text_name != txt.name:
                self.script_text_name = txt.name
            return txt
        except Exception:
            return None

    def get_script(self):
        txt = self._script_text()
        if txt is not None:
            try:
                return txt.as_string()
            except Exception:
                pass
        return self.plan or ""

    def set_script_text(self, text):
        script = self._strip_script(text)
        if not script:
            raise ValueError("AI 没有返回 Python 脚本")
        try:
            compile(script, f"<Fx AI Scene Script {self.name}>", "exec")
        except SyntaxError as e:
            raise ValueError(f"Python 语法错误: line {e.lineno}: {e.msg}") from e
        self.plan = script
        txt = self._ensure_script_text()
        if txt is not None:
            txt.clear()
            txt.write(script)
        self._error = ""
        return script

    # Compatibility with the previous operator implementation/name.
    def set_plan_text(self, text):
        return self.set_script_text(text)

    def draw_body(self, context, layout):
        layout.prop(self, "ask", text="")
        row = layout.row(align=True)
        row.operator("fx_nodes.ai_scene_plan", text="Generate Script", icon="SCRIPT").node_name = self.name
        if bpy is not None:
            row.prop_search(self, "script_text_name", bpy.data, "texts", text="")
        else:
            row.prop(self, "script_text_name", text="")
        op = row.operator("fx_nodes.open_text_editor", text="", icon="TEXT")
        op.text_name = self.script_text_name

        script = self.get_script()
        if script:
            box = layout.box(); box.scale_y = 0.72
            lines = script.splitlines()
            try:
                compile(script, f"<Fx AI Scene Script {self.name}>", "exec")
                box.label(text=f"Python script · {len(lines)} line(s)", icon="CHECKMARK")
            except SyntaxError as e:
                box.alert = True
                box.label(text=f"Syntax line {e.lineno}: {e.msg}"[:96], icon="ERROR")
            for line in lines[:7]:
                box.label(text=(line or " ")[:110], icon="SCRIPT")
            if len(lines) > 7:
                box.label(text=f"… +{len(lines) - 7} more lines")

        layout.prop(self, "execute_script")
        layout.prop(self, "out_key")
        layout.prop(self, "result_key")
        col = layout.column(align=True)
        col.prop(self, "model_override", text="model")
        col.prop(self, "temperature")

    def _execute_script(self, script, signal, engine):
        msg = signal.msg
        result = {}
        ns = {
            "__builtins__": __builtins__,
            "bpy": bpy,
            "math": math,
            "random": random,
            "msg": msg,
            "payload": msg.get("payload"),
            "context": signal.context,
            "flow": self.flow_context(engine),
            "global_context": self.global_context(engine),
            "G": self.global_context(engine),
            "node": self,
            "engine": engine,
            "result": result,
        }
        exec(compile(script, f"<Fx AI Scene Script {self.name}>", "exec"), ns, ns)  # noqa: S102 - explicit power-user AI script node
        return ns.get("result", result)

    def process(self, signal, engine):
        script = self.get_script()
        if not script:
            self._error = "没有场景脚本；点击 Generate Script 生成 Python 脚本"
            return []
        try:
            compile(script, f"<Fx AI Scene Script {self.name}>", "exec")
            msgpath.set(self.out_key, script, signal.msg, self.flow_context(engine), self.global_context(engine))
            exec_result = {"executed": False}
            if self.execute_script:
                exec_result = self._execute_script(script, signal, engine)
                if exec_result is None:
                    exec_result = {"executed": True}
                elif isinstance(exec_result, dict):
                    exec_result.setdefault("executed", True)
            msgpath.set(self.result_key, exec_result, signal.msg, self.flow_context(engine), self.global_context(engine))
        except Exception as e:
            tb = traceback.format_exc(limit=3)
            self._error = f"{type(e).__name__}: {e}"
            try:
                msgpath.set(self.result_key, {"executed": False, "error": str(e), "traceback": tb},
                            signal.msg, self.flow_context(engine), self.global_context(engine))
            except Exception:
                pass
            return []
        self.last_result = msgpath.compact(exec_result, 80)
        self._error = ""
        return self.flow_out(signal)

