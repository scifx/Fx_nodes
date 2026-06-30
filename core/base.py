"""Base node classes (bpy layer).

These wrap bpy ``Node`` and bridge to the bpy-free engine. They expose the
ergonomic helpers (add_in_flow / add_out / flow_out ...) so a new node is a
~15-line subclass — the core never changes.

Subclass map:
    NexusBaseNode      common drawing, error display, preview snapshot
      NexusTriggerNode   has a Flow OUT, hooks an event source via eventbus
      NexusLogicNode     pure-ish transform of the signal
      NexusActionNode    side effects on the scene
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

FLOW_SOCKET = "NexusFlowSocket"


class NexusBaseNode(Node):
    """Common base for all Nexus nodes."""
    # subclasses set these
    category = "Utility"
    nexus_color = (0.3, 0.3, 0.35)

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
        return getattr(ntree, "bl_idname", "") == "NexusNodeTree"

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

    # ---- helpers for process() ------------------------------------------
    def flow_out(self, signal: Signal, socket="▶", **payload):
        """Standard 'continue down the flow' return."""
        sig = signal.child(**payload) if payload else signal
        return [(socket, sig)]

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
            self.color = self.nexus_color
        except Exception:
            pass
        self.init_sockets()

    def init_sockets(self):
        """Override: create inputs/outputs."""
        pass

    def process(self, signal: Signal, engine):
        """Override: handle a flow signal, return [(out_socket, signal), ...]."""
        return []

    # ---- drawing ---------------------------------------------------------
    def draw_buttons(self, context, layout):
        self.draw_body(context, layout)
        err = getattr(self, "_error", "")
        if err:
            box = layout.box()
            box.alert = True
            box.label(text=err[:60], icon="ERROR")

    def draw_body(self, context, layout):
        pass


class NexusTriggerNode(NexusBaseNode):
    category = "Trigger"
    nexus_color = (0.35, 0.18, 0.18)

    def init_sockets(self):
        self.add_out_flow()

    def process(self, signal, engine):
        # triggers simply forward; the event source calls engine.fire on them
        return self.flow_out(signal)


class NexusLogicNode(NexusBaseNode):
    category = "Logic"
    nexus_color = (0.18, 0.28, 0.35)


class NexusActionNode(NexusBaseNode):
    category = "Action"
    nexus_color = (0.18, 0.32, 0.2)
