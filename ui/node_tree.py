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


class BpyGraphAdapter(GraphAdapter):
    """Bridges the engine to a live FxNodeTree.

    uid format: "<node.name>" within a single tree (the adapter is per-tree).
    """
    def __init__(self, tree: FxNodeTree):
        self.tree = tree
        self._uid_to_node = {}
        self.reindex()

    def reindex(self):
        self._uid_to_node = {n.node_uid: n for n in self.tree.nodes if hasattr(n, "node_uid")}

    def get_node(self, uid):
        node = self._uid_to_node.get(uid)
        if node is None:
            self.reindex()
            node = self._uid_to_node.get(uid)
        return node

    def downstream(self, uid, out_socket):
        node = self.get_node(uid)
        if node is None:
            return
        sock = node.outputs.get(out_socket)
        if sock is None:
            return
        for link in sock.links:
            if not link.is_valid:
                continue
            tgt = link.to_node
            if hasattr(tgt, "node_uid"):
                yield (tgt.node_uid, link.to_socket.name)
