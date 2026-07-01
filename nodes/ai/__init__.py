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
        description="Optional extra AI reference property. Default is payload; change when you explicitly want msg.xxx / flow.xxx / Global.xxx scene context.",
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


@register_node
class AIExpressionNode(_AIBase):
    """AI expression node in the current msg/flow/global paradigm.

    On flow input it ensures a safe sandbox expression exists, evaluates it
    against the current signal variables, stores the result through msgpath,
    then continues the flow. Manual Generate is the recommended default;
    runtime generation is optional and disabled by default.
    """
    bl_idname = "FxAIExpression"
    bl_label = "AI → Expression"
    bl_icon = "SCRIPTPLUGINS"

    ask: StringProperty(
        name="Describe",
        default="double the current payload",
        description="Natural-language description. May use {payload}, {topic}, or other msg/context template keys.",
    )
    ask_text_name: StringProperty(
        name="Describe Text",
        default="",
        description="Optional Blender Text datablock for natural-language request.",
    )
    generated: StringProperty(name="Expression", default="")
    out_key: StringProperty(
        name="Target",
        default="payload",
        description="Where the evaluated result is written. Default is payload; change only when you explicitly want another property.",
    )
    auto_generate: BoolProperty(
        name="Generate On Flow",
        default=False,
        description="If no valid expression exists, allow runtime AI generation during flow execution. Disabled by default because it is slow and network-dependent.",
    )

    SYS = (
        "You convert a user's request into exactly ONE safe Python expression for Fx Nodes. "
        "Return ONLY the expression: no markdown, no assignment, no return statement, no explanation. "
        "This is an expression sandbox, not full Python. "
        "Available variables follow the Node-RED message model: "
        "msg is a dict, payload is msg.get('payload'), topic is msg.get('topic'), "
        "flow is the flow context dict, Global, global_context and G are the global context dict. "
        "Top-level msg keys are also available as variables. Runtime variables include frame, time, dt, fps, wall, tick. "
        "You may use either dot or item access for dict-like values, for example msg.count, msg['count'], flow.seed or Global.seed. "
        "Allowed literals: numbers, strings, booleans, None, lists, tuples, dicts. "
        "Allowed operators: arithmetic, comparisons, boolean and/or/not, conditional expression. "
        "Allowed functions: sin cos tan asin acos atan atan2 sqrt pow exp log floor ceil abs round "
        "radians degrees hypot min max sum len int float str bool clamp lerp mix map_range noise rand randint uniform range sign. "
        "Forbidden: imports, def, assignment statements, loops as statements, dunder/private attribute access. "
        "Examples: payload * 2; clamp(payload, 0, 1); {'x': payload, 'frame': frame}; "
        "msg['items'][0]['name'] if len(msg['items']) else None"
    )

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def get_ask(self):
        return self.get_text_content("ask_text_name", "ask")

    def draw_body(self, context, layout):
        self.draw_text_row(layout, "ask_text_name", "ask", label="Ask", prefix="Fx AI Ask")
        row = layout.row(align=True)
        row.operator("fx_nodes.ai_generate_expr", text="Generate", icon="SHADERFX").node_name = self.name
        row.prop(self, "auto_generate", text="On Flow")
        layout.prop(self, "out_key")
        self.draw_reference_ui(layout)
        col = layout.column(align=True)
        col.prop(self, "model_override", text="model")
        col.prop(self, "temperature")

    def draw_previews(self, context, layout):
        if self.generated:
            box = layout.box(); box.scale_y = 0.8
            box.label(text="Generated Expr:", icon="SCRIPT")
            for ln in self.generated.splitlines()[:4]:
                box.label(text=ln[:100])

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
        # If Auto Generate is ON, always generate via AI (so reference data is fresh).
        # This matches AIChatNode behavior and allows chaining AI nodes with Cache.
        # If Auto Generate is OFF, use cached expression for fast local evaluation.
        if self.auto_generate:
            user_prompt = _inject_reference_context(self, engine, signal, _template(self.get_ask(), signal))
            msgs = [
                {"role": "system", "content": self.SYS},
                {"role": "user", "content": user_prompt},
            ]
            self["_last_messages"] = json.dumps(msgs, ensure_ascii=False)
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

        # Auto_generate OFF: use cached expression
        if self.generated:
            try:
                self._evaluate_to_signal(signal, engine)
            except (expr.ExprError, msgpath.MsgPathError) as e:
                self._error = str(e); return []
            return self.flow_out(signal)

        self._error = "没有表达式；点击 Generate 或开启 Auto Generate"
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
    ask_text_name: StringProperty(
        name="Instruction Text",
        default="",
        description="Optional Blender Text datablock for multi-line instruction prompt.",
    )
    # Backwards-compatible fallback storage.  Older files used ``plan``.
    plan: StringProperty(default="")
    script_text_name: StringProperty(
        name="Script Text",
        default="",
        description="Blender Text datablock containing the generated Python script.",
    )
    out_key: StringProperty(
        name="Script Target",
        default="msg.script",
        description="Where the generated script text is written. Kept separate by default so payload can remain the runtime result.",
    )
    result_key: StringProperty(
        name="Result Property",
        default="payload",
        description="Where execution result metadata is written. Default is payload so downstream nodes/cache receive the scene result directly.",
    )
    execute_script: BoolProperty(
        name="Execute Script",
        default=True,
        description="Run the current Blender Python script when a flow reaches this node.",
    )
    auto_generate_on_flow: BoolProperty(
        name="Generate On Flow",
        default=False,
        description="Allow runtime AI generation when a flow reaches this node. Disabled by default because it is slow, network-dependent, and potentially risky.",
    )

    SYS = (
        "You generate Blender Python scripts for an Fx Nodes AI Scene Script node. "
        "Return ONLY executable Python code, no markdown fences, no prose. "
        "The code runs inside Blender with bpy, math, random already available. "
        "Runtime variables are also available: msg dict, payload, context dict, flow dict, global_context dict, node, engine. "
        "You may create, delete, transform, animate objects, create materials, modifiers, constraints, collections, cameras, lights, drivers, and keyframes. "
        "Prefer clear deterministic bpy.data API (bpy.data.objects.new, mesh.from_pydata, etc.) over bpy.ops, "
        "because bpy.ops requires a VIEW_3D context and may fail in background/node execution. "
        "If you must use bpy.ops, guard with try/except. "
        "Use object names and reusable helper functions when useful. "
        "For results, set a variable named result to a JSON-like dict, for example result = {'created': [obj.name]}. "
        "Do not call external network APIs, do not access files, and do not run subprocesses unless the user explicitly requested it. "
        "If modifying existing objects, handle missing objects gracefully. "
        "Return code only."
    )

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def get_ask(self):
        return self.get_text_content("ask_text_name", "ask")

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
                script = txt.as_string()
                # If the Text datablock exists but is empty/whitespace,
                # fall back to the stored plan – this prevents a stale
                # empty Text block from masking a valid script, which was
                # causing "script doesn't execute" reports.
                if script and script.strip():
                    return script
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
        self.draw_text_row(layout, "ask_text_name", "ask", label="Instruction", prefix="Fx Scene Ask")
        # Generate + Run row
        row = layout.row(align=True)
        op = row.operator("fx_nodes.ai_scene_plan", text="Generate", icon="FILE_REFRESH")
        op.node_name = self.name
        # Manual fire / run button – executes the current script immediately
        tree = getattr(context.space_data, "edit_tree", None)
        if tree is not None:
            run_op = row.operator("fx_nodes.fire_node", text="Run", icon="PLAY")
            run_op.tree_name = tree.name
            run_op.node_name = self.name
        # Text datablock picker for script output
        row2 = layout.row(align=True)
        if bpy is not None:
            row2.prop_search(self, "script_text_name", bpy.data, "texts", text="Script Out")
        else:
            row2.prop(self, "script_text_name", text="Script Out")
        op = row2.operator("fx_nodes.open_text_editor", text="", icon="TEXT")
        op.text_name = self.script_text_name

        layout.prop(self, "auto_generate_on_flow")
        layout.prop(self, "execute_script")
        layout.prop(self, "out_key")
        layout.prop(self, "result_key")
        self.draw_reference_ui(layout)
        col = layout.column(align=True)
        col.prop(self, "model_override", text="model")
        col.prop(self, "temperature")

    def draw_previews(self, context, layout):
        script = self.get_script()
        if script:
            box = layout.box(); box.scale_y = 0.8
            lines = script.splitlines()
            try:
                compile(script, f"<Fx AI Scene Script {self.name}>", "exec")
                box.label(text=f"Script Preview ({len(lines)} lines):", icon="CHECKMARK")
            except SyntaxError as e:
                box.alert = True
                box.label(text=f"Syntax line {e.lineno}: {e.msg}"[:96], icon="ERROR")
            for line in lines[:7]:
                box.label(text=(line or " ")[:110], icon="SCRIPT")
            if len(lines) > 7:
                box.label(text=f"… +{len(lines) - 7} more lines")

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
        code = compile(script, f"<Fx AI Scene Script {self.name}>", "exec")
        # Blender operators (bpy.ops.*) need a proper window/area context,
        # otherwise poll() fails when running from a timer / background.
        # Try to provide a temp_override with a VIEW_3D area if available.
        try:
            ctx = bpy.context
            window = ctx.window
            screen = window.screen if window else None
            area = None
            region = None
            if screen:
                for a in screen.areas:
                    if a.type == 'VIEW_3D':
                        area = a
                        for r in a.regions:
                            if r.type == 'WINDOW':
                                region = r
                                break
                        break
            if area and region and hasattr(ctx, "temp_override"):
                with ctx.temp_override(window=window, area=area, region=region, screen=screen):
                    exec(code, ns, ns)
            else:
                exec(code, ns, ns)
        except Exception:
            # Fall back to plain exec – script may not need ops context
            exec(code, ns, ns)
        return ns.get("result", result)

    def _run_script_with_result(self, script, signal, engine):
        compile(script, f"<Fx AI Scene Script {self.name}>", "exec")
        # Manual Run (signal.source == self.node_uid) should execute even if
        # execute_script is False – this matches user expectation of the Run button.
        force_execute = (getattr(signal, "source", None) == self.node_uid)
        should_execute = self.execute_script or force_execute
        exec_result = {"executed": False}
        if should_execute:
            exec_result = self._execute_script(script, signal, engine)
            if exec_result is None:
                exec_result = {"executed": True}
            elif isinstance(exec_result, dict):
                exec_result.setdefault("executed", True)
        msgpath.set(self.result_key, exec_result, signal.msg, self.flow_context(engine), self.global_context(engine))
        if self.result_key != "payload":
            signal.msg["payload"] = exec_result
        msgpath.set(self.out_key, script, signal.msg, self.flow_context(engine), self.global_context(engine))
        self.last_result = msgpath.compact(exec_result, 80)
        self._error = ""
        return exec_result

    def process(self, signal, engine):
        # If Auto Generate is ON, always generate via AI so reference data is fresh.
        # This allows chaining: Cache(payload=previous_result) -> AI Scene Script
        # will see the cached payload and generate a new script each flow.
        if self.auto_generate_on_flow:
            user_prompt = _inject_reference_context(self, engine, signal, _template(self.ask, signal))
            msgs = [
                {"role": "system", "content": self.SYS},
                {"role": "user", "content": user_prompt},
            ]
            self["_last_messages"] = json.dumps(msgs, ensure_ascii=False)
            cont = signal.child()

            def done(text, err):
                if err:
                    self._error = err
                    return
                try:
                    script_text = self.set_script_text(text or "")
                    self._run_script_with_result(script_text, cont, engine)
                except Exception as e:
                    self._error = str(e)
                    return
                if hasattr(engine, "continue_from"):
                    engine.continue_from(self.node_uid, "▶", cont)

            self._run_async(engine, msgs, done, max_tokens=1024)
            return []

        # Auto_generate OFF: use cached script
        script = self.get_script()
        if not script:
            self._error = "没有场景脚本；请先点击 Generate，或开启 Generate On Flow"
            return []

        try:
            self._run_script_with_result(script, signal, engine)
        except Exception as e:
            tb = traceback.format_exc(limit=3)
            self._error = f"{type(e).__name__}: {e}"
            try:
                err_result = {"executed": False, "error": str(e), "traceback": tb}
                msgpath.set(self.result_key, err_result,
                            signal.msg, self.flow_context(engine), self.global_context(engine))
                if self.result_key != "payload":
                    signal.msg["payload"] = err_result
            except Exception:
                pass
            return []
        return self.flow_out(signal)

