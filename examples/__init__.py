"""Example graph builders. Run inside Blender's text editor or via operator.

Each function builds a ready-to-run NexusNodeTree demonstrating the system.
Call build_all() then Start the engine from the N-panel.
"""
from __future__ import annotations

import bpy


def _new_tree(name):
    tree = bpy.data.node_groups.new(name, "NexusNodeTree")
    return tree


def _link(tree, a, aout, b, bin="▶"):
    tree.links.new(a.outputs[aout], b.inputs[bin])


def example_pulsing_cube():
    """Timer -> Expression(sin) -> Transform -> Data Preview.
    A cube pulses up/down on a timer. Classic 'hello world' of the system."""
    tree = _new_tree("NEXUS · Pulsing Cube")
    n = tree.nodes
    trig = n.new("NexusTimerTrigger"); trig.location = (-600, 0); trig.interval = 0.1
    expr = n.new("NexusExpression"); expr.location = (-380, 0)
    expr.expression = "sin(wall * 3) * 1.5"; expr.out_key = "z"
    tr = n.new("NexusTransform"); tr.location = (-120, 0)
    tr.channel = "location"; tr.expr_z = "z"
    prev = n.new("NexusDataPreview"); prev.location = (160, 0)
    _link(tree, trig, "▶", expr); _link(tree, expr, "▶", tr); _link(tree, tr, "▶", prev)
    return tree


def example_key_spawner():
    """Key(SPACE) -> Counter -> CreateMesh(at row) -> Preview.
    Press SPACE to spawn cubes in a growing row."""
    tree = _new_tree("NEXUS · Key Spawner")
    n = tree.nodes
    trig = n.new("NexusKeyTrigger"); trig.location = (-600, 0); trig.key = "SPACE"
    cnt = n.new("NexusCounter"); cnt.location = (-380, 0); cnt.key = "count"; cnt.step = 1
    mk = n.new("NexusCreateMesh"); mk.location = (-120, 0)
    mk.primitive = "cube"; mk.loc_expr = "(count*2, 0, 0)"
    prev = n.new("NexusDataPreview"); prev.location = (180, 0)
    _link(tree, trig, "▶", cnt); _link(tree, cnt, "▶", mk); _link(tree, mk, "▶", prev)
    return tree


def example_frame_keyframer():
    """Frame -> Expression -> Transform -> Keyframe.
    Bakes procedural motion into keyframes as the timeline plays."""
    tree = _new_tree("NEXUS · Frame Keyframer")
    n = tree.nodes
    trig = n.new("NexusFrameTrigger"); trig.location = (-620, 0)
    ex = n.new("NexusExpression"); ex.location = (-400, 0)
    ex.expression = "sin(frame * 0.2) * 3"; ex.out_key = "x"
    tr = n.new("NexusTransform"); tr.location = (-150, 0); tr.expr_x = "x"; tr.expr_z = ""
    kf = n.new("NexusKeyframe"); kf.location = (110, 0); kf.data_path = "location"
    _link(tree, trig, "▶", ex); _link(tree, ex, "▶", tr); _link(tree, tr, "▶", kf)
    return tree


def example_ai_modeling():
    """Manual -> AI Scene Command -> Preview.
    Type an instruction, click Plan, then Fire to let the AI build geometry."""
    tree = _new_tree("NEXUS · AI Modeling")
    n = tree.nodes
    trig = n.new("NexusManualTrigger"); trig.location = (-500, 0)
    ai = n.new("NexusAISceneCommand"); ai.location = (-250, 0)
    ai.ask = "create 6 spheres arranged in a circle of radius 4"
    prev = n.new("NexusDataPreview"); prev.location = (60, 0)
    _link(tree, trig, "▶", ai); _link(tree, ai, "▶", prev)
    return tree


def build_all():
    trees = [example_pulsing_cube(), example_key_spawner(),
             example_frame_keyframer(), example_ai_modeling()]
    print("[NEXUS] built examples:", [t.name for t in trees])
    return trees


if __name__ == "__main__":
    build_all()
