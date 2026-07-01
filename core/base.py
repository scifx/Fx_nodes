"""Base node classes (bpy layer).

These wrap bpy ``Node`` and bridge to the bpy-free engine. They expose the
ergonomic helpers (add_in_flow / add_out / flow_out ...) so a new node is a
~15-line subclass — the core never changes.

Subclass map:
    FxBaseNode      common drawing, error display, preview snapshot
      FxTriggerNode   has a Flow OUT, hooks an event source via eventbus
      FxLogicNode     pure-ish transform of the signal
      FxActionNode    side effects on the scene
"""
from __future__ import annotations

try:
    import bpy
    from bpy.types import Node
    _HAS_BPY = True
except Exception:  # pragma: no cover - allows import in headless tests
    _HAS_BPY = False
    class Node:  # type: ignore
        pass

from .signal import Signal

FLOW_SOCKET = "FxFlowSocket"


class FxBaseNode(Node):
    """Common base for all Fx nodes."""
    # subclasses set these
    category = "Utility"
    fx_color = (0.25, 0.25, 0.28)

    # runtime fields (not bpy props): set on instances
    @property
    def node_uid(self) -> str:
        # name is unique within a tree; combine with tree for global-ish uid
        try:
            return f"{self.id_data.name}/{self.name}"
        except Exception:
            return self.name

    @classmethod
    def poll(cls, ntree):
        return getattr(ntree, "bl_idname", "") == "FxNodeTree"

    # ---- socket helpers --------------------------------------------------
    def add_in_flow(self, name="▶"):
        return self.inputs.new(FLOW_SOCKET, name)

    def add_out_flow(self, name="▶"):
        return self.outputs.new(FLOW_SOCKET, name)

    def add_in(self, idname, name, default=None):
        s = self.inputs.new(idname, name)
        if default is not None and hasattr(s, "default_value"):
            try:
                s.default_value = default
            except Exception:
                pass
        return s

    def add_out(self, idname, name):
        return self.outputs.new(idname, name)

    def _move_flow_sockets_to_top(self, sockets):
        """Keep control-flow sockets as the first/top sockets in the node UI.

        Blender's node API exposes sockets on the left/right side, not literal
        top-edge ports.  The practical way to keep long node bodies from making
        flow wiring painful is to keep all FxFlowSocket entries before any data
        sockets.  This also repairs older saved nodes if socket order drifted.
        """
        try:
            flow_sockets = [s for s in sockets if getattr(s, "bl_idname", "") == FLOW_SOCKET]
            for target_index, sock in enumerate(flow_sockets):
                current_index = next((i for i, s in enumerate(sockets) if s == sock), target_index)
                if current_index != target_index and hasattr(sockets, "move"):
                    sockets.move(current_index, target_index)
        except Exception:
            pass

    def ensure_flow_sockets_top(self):
        self._move_flow_sockets_to_top(getattr(self, "inputs", []))
        self._move_flow_sockets_to_top(getattr(self, "outputs", []))

    # ---- helpers for process() ------------------------------------------
    def flow_out(self, signal: Signal, socket="▶", **msg_updates):
        """Continue down the control wire with the same Node-RED msg.

        ``msg_updates`` are convenience updates applied to ``signal.msg`` before
        forwarding.  Most custom nodes are simply dictionary operations on
        ``signal.msg`` and then ``return self.flow_out(signal)``.
        """
        if msg_updates:
            signal.msg.update(msg_updates)
        return [(socket, signal)]

    # ---- ultra-simple Node-RED msg/context API ---------------------------
    def msg(self, signal: Signal):
        return signal.msg

    def payload(self, signal: Signal, default=None):
        return signal.msg.get("payload", default)

    def set_payload(self, signal: Signal, value):
        signal.msg["payload"] = value
        return value

    def topic(self, signal: Signal, default=None):
        return signal.msg.get("topic", default)

    def set_topic(self, signal: Signal, value):
        signal.msg["topic"] = value
        return value

    # Compatibility helpers from the attribute-table iteration.
    def attrs(self, signal: Signal):
        return signal.msg

    def attr(self, signal: Signal, key, default=None):
        return signal.msg.get(key, default)

    def set_attr(self, signal: Signal, key, value):
        signal.msg[key] = value
        return value

    def del_attr(self, signal: Signal, key):
        signal.msg.pop(key, None)

    def node_context(self, engine):
        return engine.node_context(self.node_uid) if hasattr(engine, "node_context") else {}

    def flow_context(self, engine):
        return getattr(engine, "flow_context", {})

    def global_context(self, engine):
        """Return the engine-wide global context store.

        Older iterations exposed ``global_attrs`` while the Node-RED-style API
        uses ``global_context``.  In normal ExecutionEngine instances these are
        aliases, but after reloads/tests/old files they may diverge.  Merge and
        re-alias them so nodes reading Global see the same data Debug/legacy
        writers show.
        """
        glob = getattr(engine, "global_context", None)
        attrs = getattr(engine, "global_attrs", None)
        if glob is None:
            glob = attrs if attrs is not None else {}
            try:
                engine.global_context = glob
            except Exception:
                pass
        if attrs is not None and attrs is not glob and isinstance(glob, dict) and isinstance(attrs, dict):
            for k, v in attrs.items():
                glob.setdefault(k, v)
            try:
                engine.global_attrs = glob
            except Exception:
                pass
        return glob

    def globals(self, engine):
        return self.global_context(engine)

    def expr_vars(self, signal: Signal, engine):
        """Variables visible to expressions.

        Node-RED conventions are first-class: ``msg``, ``payload``, ``topic``,
        ``flow`` and ``Global`` (uppercase, because lowercase ``global`` is a
        Python keyword).  For convenience, top-level msg keys are also exposed
        as variables, so ``payload + 1`` works.
        """
        msg = signal.msg
        flow = self.flow_context(engine)
        glob = self.global_context(engine)
        try:
            from . import expr as _expr
            missing = _expr.MISSING
        except Exception:
            missing = None
        v = dict(signal.context)
        v.update(msg)  # top-level msg keys have highest convenience precedence
        v["msg"] = msg
        v["payload"] = msg["payload"] if "payload" in msg else missing
        v["topic"] = msg["topic"] if "topic" in msg else missing
        v["context"] = signal.context
        v["flow"] = flow
        v["Global"] = glob
        v["global_context"] = glob
        # Backwards-compatible/convenience names.  Lowercase "global" is not
        # usable in Python eval source, but keeping it in the env is harmless
        # for callers that inspect expr_vars() directly.
        v["global"] = glob
        v["attrs"] = msg
        v["G"] = glob
        return v

    def input_value(self, engine, socket_name, signal):
        """Read a value socket: from incoming link (evaluated) or its default."""
        sock = self.inputs.get(socket_name)
        if sock is None:
            return None
        if sock.is_linked and sock.links:
            from_node = sock.links[0].from_node
            from_sock = sock.links[0].from_socket
            if hasattr(from_node, "evaluate_output"):
                return from_node.evaluate_output(from_sock.name, signal, engine)
        return getattr(sock, "default_value", None)

    def evaluate_output(self, socket_name, signal, engine):
        """Pull-evaluate a data output (with per-tick memo). Override in data/logic nodes."""
        cached = engine.memo_get(self.node_uid + "::" + socket_name)
        from .engine import _MISS
        if cached is not _MISS:
            return cached
        val = self.compute(socket_name, signal, engine)
        return engine.memo_set(self.node_uid + "::" + socket_name, val)

    def compute(self, socket_name, signal, engine):
        """Override for pull-style data outputs."""
        return None

    # ---- bpy lifecycle ---------------------------------------------------
    def init(self, context):
        self._error = ""
        try:
            self.use_custom_color = True
            self.color = self.fx_color
        except Exception:
            pass
        self.init_sockets()
        self.ensure_flow_sockets_top()

    def init_sockets(self):
        """Override: create inputs/outputs."""
        pass

    def process(self, signal: Signal, engine):
        """Override: handle a flow signal, return [(out_socket, signal), ...]."""
        return []

    # ---- drawing & text datablock helpers --------------------------------
    def draw_text_row(self, layout, text_prop_name, fallback_prop_name, label="Text", prefix="Fx Text"):
        """Draw an Animation Nodes style Text datablock picker row with create and edit buttons."""
        row = layout.row(align=True)
        if _HAS_BPY and hasattr(bpy, "data"):
            row.prop_search(self, text_prop_name, bpy.data, "texts", text=label)
        else:
            row.prop(self, text_prop_name, text=label)
        op = row.operator("fx_nodes.node_new_text", text="", icon="ADD")
        op.node_name = self.name
        op.tree_name = self.id_data.name
        op.prop_name = text_prop_name
        op.fallback_prop = fallback_prop_name
        op.prefix = prefix
        text_val = getattr(self, text_prop_name, "")
        op = row.operator("fx_nodes.open_text_editor", text="", icon="TEXT")
        op.text_name = text_val
        if not text_val and hasattr(self, fallback_prop_name):
            layout.prop(self, fallback_prop_name, text=label if label != "Text" else "Inline")

    def get_text_content(self, text_prop_name, fallback_prop_name):
        """Retrieve multi-line code/prompt from Text datablock or fallback string property."""
        text_name = getattr(self, text_prop_name, "")
        if _HAS_BPY and hasattr(bpy, "data") and text_name:
            txt = bpy.data.texts.get(text_name)
            if txt is not None:
                try:
                    content = txt.as_string()
                    if content and content.strip():
                        return content
                except Exception:
                    pass
        return getattr(self, fallback_prop_name, "") or ""

    def draw_buttons(self, context, layout):
        self.ensure_flow_sockets_top()
        # 1. Controls section (inputs, buttons, toggles, selectors)
        self.draw_body(context, layout)
        # 2. Previews section (all preview/status output strictly AFTER buttons)
        self.draw_previews(context, layout)
        # 3. Error / Warning display
        err = getattr(self, "_error", "")
        if err:
            box = layout.box()
            box.alert = True
            header = box.row(align=True)
            header.label(text="Error Summary", icon="ERROR")
            lines = str(err).splitlines()
            for line in lines[:6]:
                box.label(text=line[:120])
            if len(lines) > 6:
                box.label(text=f"… +{len(lines) - 6} more line(s)")

    def draw_body(self, context, layout):
        pass

    def draw_previews(self, context, layout):
        pass


class FxTriggerNode(FxBaseNode):
    category = "Trigger"
    fx_color = (0.48, 0.18, 0.18)

    def init_sockets(self):
        self.add_out_flow()

    def process(self, signal, engine):
        # triggers simply forward; the event source calls engine.fire on them
        return self.flow_out(signal)


class FxLogicNode(FxBaseNode):
    category = "Logic"
    fx_color = (0.16, 0.30, 0.48)


class FxActionNode(FxBaseNode):
    category = "Property"
    fx_color = (0.16, 0.40, 0.26)
