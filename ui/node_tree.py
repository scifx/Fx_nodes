"""The custom node editor type and the bpy-backed GraphAdapter."""
from __future__ import annotations

import bpy
from bpy.types import NodeTree
from bpy.props import StringProperty, IntProperty, BoolProperty

from ..core.engine import GraphAdapter


class FxNodeTree(NodeTree):
    bl_idname = "FxNodeTree"
    bl_label = "Fx Nodes"
    bl_icon = "NODETREE"

    debug_filter: StringProperty(
        name="Filter",
        default="",
        description="Filter Debug panel by node name, path, key, or value text.",
    )
    debug_rows: IntProperty(name="Rows", default=8, min=1, max=64)
    debug_show_empty: BoolProperty(name="Show Empty", default=False)
    debug_show_errors: BoolProperty(name="Show Errors", default=True)
    debug_show_context: BoolProperty(name="Show Context", default=False)


class BpyGraphAdapter(GraphAdapter):
    """Bridges the engine to a live FxNodeTree.

    Blender RNA objects can become invalid after file reloads, addon reloads, or
    deleting/recreating a node tree with the same name.  Keep the adapter
    re-bindable and make stale-RNA failures explicit so Runtime can recreate or
    repair its cache instead of crashing with ``StructRNA ... has been removed``.
    """
    def __init__(self, tree: FxNodeTree):
        self.tree = tree
        self._uid_to_node = {}
        self.reindex()

    def rebind(self, tree: FxNodeTree):
        self.tree = tree
        self.reindex()
        return self

    def reindex(self):
        try:
            nodes = list(self.tree.nodes)
        except ReferenceError:
            self._uid_to_node = {}
            raise
        except Exception:
            self._uid_to_node = {}
            return

        indexed = {}
        for n in nodes:
            try:
                uid = getattr(n, "node_uid", None)
            except ReferenceError:
                continue
            if uid:
                indexed[uid] = n
        self._uid_to_node = indexed

    def get_node(self, uid):
        node = self._uid_to_node.get(uid)
        if node is None:
            try:
                self.reindex()
            except ReferenceError:
                return None
            node = self._uid_to_node.get(uid)
        return node

    def downstream(self, uid, out_socket):
        node = self.get_node(uid)
        if node is None:
            return
        try:
            sock = node.outputs.get(out_socket)
        except ReferenceError:
            return
        if sock is None:
            return
        try:
            links = list(sock.links)
        except ReferenceError:
            return
        for link in links:
            try:
                if not link.is_valid:
                    continue
                tgt = link.to_node
                if hasattr(tgt, "node_uid"):
                    yield (tgt.node_uid, link.to_socket.name)
            except ReferenceError:
                continue
