"""Example graph builders for the Node-RED-style Fx Nodes model."""
from __future__ import annotations

import bpy


def _new_tree(name):
    return bpy.data.node_groups.new(name, "FxNodeTree")


def _link(tree, a, aout, b, bin="▶"):
    tree.links.new(a.outputs[aout], b.inputs[bin])


def example_pulsing_active_object():
    """Timer -> Expression -> Set Property -> Debug."""
    tree = _new_tree("Fx Nodes · Pulsing Active Object")
    n = tree.nodes
    trig = n.new("FxTimerTrigger"); trig.location = (-650, 0); trig.interval = 0.1
    ex = n.new("FxExpression"); ex.location = (-420, 0)
    ex.expression = "sin(wall * 3) * 1.5"; ex.out_path = "payload"
    setp = n.new("FxPropertySet"); setp.location = (-140, 0)
    setp.path = 'bpy.context.object.location[2]'; setp.value_expr = "payload"
    dbg = n.new("FxDebug"); dbg.location = (140, 0); dbg.path = "msg"
    _link(tree, trig, "▶", ex); _link(tree, ex, "▶", setp); _link(tree, setp, "▶", dbg)
    return tree


def example_read_scene_frame():
    """Frame Trigger -> Get Property -> Debug."""
    tree = _new_tree("Fx Nodes · Read Scene Frame")
    n = tree.nodes
    trig = n.new("FxFrameTrigger"); trig.location = (-500, 0)
    getp = n.new("FxPropertyGet"); getp.location = (-240, 0)
    getp.path = 'bpy.context.scene.frame_current'; getp.out_path = "payload"
    dbg = n.new("FxDebug"); dbg.location = (40, 0); dbg.path = "payload"
    _link(tree, trig, "▶", getp); _link(tree, getp, "▶", dbg)
    return tree


def example_key_sets_scale():
    """Key(SPACE) -> Counter -> Expression -> Set Property x/y/z -> Debug."""
    tree = _new_tree("Fx Nodes · Key Sets Scale")
    n = tree.nodes
    trig = n.new("FxKeyTrigger"); trig.location = (-720, 0); trig.key = "SPACE"
    cnt = n.new("FxCounter"); cnt.location = (-500, 0); cnt.path = "count"; cnt.step = 1; cnt.reset_at = 6
    ex = n.new("FxExpression"); ex.location = (-280, 0)
    ex.expression = "1 + count * 0.15"; ex.out_path = "payload"
    sx = n.new("FxPropertySet"); sx.location = (0, 80); sx.path = 'bpy.context.object.scale[0]'; sx.value_expr = "payload"
    sy = n.new("FxPropertySet"); sy.location = (0, -40); sy.path = 'bpy.context.object.scale[1]'; sy.value_expr = "payload"
    sz = n.new("FxPropertySet"); sz.location = (0, -160); sz.path = 'bpy.context.object.scale[2]'; sz.value_expr = "payload"
    dbg = n.new("FxDebug"); dbg.location = (280, 0); dbg.path = "msg"
    _link(tree, trig, "▶", cnt); _link(tree, cnt, "▶", ex)
    _link(tree, ex, "▶", sx); _link(tree, sx, "▶", sy); _link(tree, sy, "▶", sz); _link(tree, sz, "▶", dbg)
    return tree


def example_function_node():
    """Manual -> Function -> Debug."""
    tree = _new_tree("Fx Nodes · Function")
    n = tree.nodes
    trig = n.new("FxManualTrigger"); trig.location = (-500, 0)
    fn = n.new("FxFunction"); fn.location = (-250, 0)
    fn.code = "import math\nmsg['payload'] = math.sqrt(msg.get('payload', 9))\nmsg['topic'] = 'sqrt'\nreturn msg"
    dbg = n.new("FxDebug"); dbg.location = (60, 0); dbg.path = "msg"
    _link(tree, trig, "▶", fn); _link(tree, fn, "▶", dbg)
    return tree


def build_all():
    trees = [example_pulsing_active_object(), example_read_scene_frame(),
             example_key_sets_scale(), example_function_node()]
    print("[Fx Nodes] built examples:", [t.name for t in trees])
    return trees


if __name__ == "__main__":
    build_all()
