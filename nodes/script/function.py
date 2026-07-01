"""Node-RED-style logic nodes: Function, Expression, Switch, Delay, Counter."""
from __future__ import annotations

import textwrap
from bpy.props import StringProperty, FloatProperty, IntProperty, EnumProperty

try:
    import bpy
except Exception:  # pragma: no cover - headless tests
    bpy = None

from ...core.base import FxNodes
from ...core.registry import register_node
from ...core.signal import Signal
from ...core import expr

@register_node
class FunctionNode(FxNodes):
    """Full Python Function node, Node-RED style.

    The code runs inside a generated Python function and may import modules.
    Available names: msg, context, flow, global_context, node, engine, bpy.

    Return semantics:
      * return msg/dict  -> send downstream
      * return None      -> stop/drop
      * return [msg,...] -> send multiple messages through the same output
    """
    bl_idname = "FxFunction"
    bl_label = "Function"
    bl_icon = "SCRIPT"
    category = "Script"
    fx_color = (0.22, 0.35, 0.52)

    code: StringProperty(
        name="Python Code",
        default="# msg is a dict. You may import modules.\nmsg['payload'] = msg.get('payload')\nreturn msg",
        description="Legacy inline code / fallback. For multi-line editing use a Text datablock.",
    )
    code_text_name: StringProperty(
        name="Code Text",
        default="",
        description="Optional Blender Text datablock used as the multi-line source for this Function node.",
    )
    last_result: StringProperty(name="Last", default="")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def warn(self, msg):
        self["_warn"] = str(msg)

    def error(self, msg):
        self._error = str(msg)

    def status(self, msg):
        self.last_result = str(msg)

    def _code_text(self):
        if bpy is None or not self.code_text_name:
            return None
        return bpy.data.texts.get(self.code_text_name)

    def get_code(self):
        txt = self._code_text()
        if txt is not None:
            try:
                code = txt.as_string()
                if code and code.strip():
                    return code
            except Exception:
                pass
        return self.code or "return msg"

    def draw_body(self, context, layout):
        from ...prefs import get_preferences
        try:
            prefs = get_preferences(context)
            allowed = prefs.allow_full_python if prefs else True
        except Exception:
            allowed = True
        if not allowed:
            box = layout.box()
            box.alert = True
            box.label(text="Full Python Disabled in Prefs", icon="LOCKED")
        self.draw_text_row(layout, "code_text_name", "code", label="Code", prefix="Fx Function")

    def draw_previews(self, context, layout):
        code = self.get_code()
        preview = [ln.rstrip() for ln in code.splitlines()[:4]]
        if preview:
            box = layout.box(); box.scale_y = 0.8
            box.label(text="Code Preview:", icon="SCRIPT")
            for ln in preview:
                box.label(text=(ln or " ")[:80])
            extra = len(code.splitlines()) - len(preview)
            if extra > 0:
                box.label(text=f"… +{extra} more lines")
        if self.last_result:
            box = layout.box(); box.scale_y = 0.8
            box.label(text=f"Status: {self.last_result[:60]}", icon="CHECKMARK")

    def _call_user_code(self, signal, engine):
        from ...prefs import get_preferences
        try:
            prefs = get_preferences()
            if prefs and not prefs.allow_full_python:
                raise PermissionError("Full Python Execution is disabled in preferences (Safety).")
        except KeyError:
            pass
        code = self.get_code()
        body = textwrap.indent(code or "return msg", "    ")
        src = "def _fx_user_function(msg, context, flow, global_context, node, engine):\n" + body
        ns = {}
        try:
            import bpy as _bpy  # type: ignore
            ns["bpy"] = _bpy
        except Exception:
            pass
        exec(src, ns, ns)  # noqa: S102 - intentionally full Python Function node
        return ns["_fx_user_function"](
            signal.msg,
            self.node_context(engine),
            self.flow_context(engine),
            self.global_context(engine),
            self,
            engine,
        )

    def process(self, signal, engine):
        try:
            result = self._call_user_code(signal, engine)
        except Exception as e:
            import traceback
            tb_list = traceback.extract_tb(e.__traceback__)
            line_str = ""
            for frame in reversed(tb_list):
                if frame.name == "_fx_user_function" or "<string>" in frame.filename:
                    line_str = f"Line {max(1, frame.lineno - 1)}: "
                    break
            self._error = f"{line_str}{type(e).__name__}: {e}"
            return []
        self._error = ""
        if result is None:
            self.last_result = "dropped"
            return []
        if isinstance(result, list):
            out = []
            for item in result:
                if item is None:
                    continue
                if not isinstance(item, dict):
                    raise TypeError("Function list items must be msg dict or None")
                out.append(("▶", Signal(payload=item, context=signal.context, source=signal.source,
                                         ts=signal.ts, hops=signal.hops)))
            self.last_result = f"sent {len(out)} msg(s)"
            return out
        if not isinstance(result, dict):
            raise TypeError("Function must return msg dict, list of msg dicts, or None")
        signal.payload = result
        self.last_result = "sent msg"
        return self.flow_out(signal)
