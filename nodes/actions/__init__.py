"""Action nodes: side effects on the scene. Modeling + animation.

These are deliberately small and composable. Add new actions by subclassing
NexusActionNode and implementing process(). This is where 'build models &
animation' lives.
"""
from __future__ import annotations

import bpy
import math
from bpy.props import StringProperty, FloatProperty, EnumProperty, BoolProperty, FloatVectorProperty, IntProperty

from ...core.base import NexusActionNode
from ...core.registry import register_node
from ...core import expr


def _resolve_object(node, engine, signal):
    """Object from the socket, else payload['object'], else active."""
    sock = node.inputs.get("Object")
    if sock and getattr(sock, "default_value", None):
        return sock.default_value
    if signal.get("object") is not None:
        return signal.get("object")
    return bpy.context.view_layer.objects.active


@register_node
class TransformNode(NexusActionNode):
    """变换：用表达式驱动物体的位移/旋转/缩放。表达式可用 frame/time/payload。"""
    bl_idname = "NexusTransform"
    bl_label = "Transform Object"
    bl_icon = "OBJECT_ORIGIN"

    channel: EnumProperty(name="Channel", items=[
        ("location", "Location", ""), ("rotation_euler", "Rotation", ""), ("scale", "Scale", ""),
    ], default="location")
    mode: EnumProperty(name="Mode", items=[("SET", "Set", ""), ("ADD", "Add", "")], default="SET")
    expr_x: StringProperty(name="X", default="")
    expr_y: StringProperty(name="Y", default="")
    expr_z: StringProperty(name="Z", default="sin(time)")

    def init_sockets(self):
        self.add_in_flow()
        self.add_in("NexusObjectSocket", "Object")
        self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "channel", text=""); layout.prop(self, "mode", text="")
        layout.prop(self, "expr_x"); layout.prop(self, "expr_y"); layout.prop(self, "expr_z")

    def process(self, signal, engine):
        obj = _resolve_object(self, engine, signal)
        if obj is None:
            self._error = "no object"; return []
        v = dict(signal.payload); v.update(signal.context)
        vec = list(getattr(obj, self.channel))
        for i, e in enumerate((self.expr_x, self.expr_y, self.expr_z)):
            if e.strip() == "":
                continue
            try:
                val = float(expr.evaluate(e, v))
            except expr.ExprError as err:
                self._error = str(err); return []
            vec[i] = vec[i] + val if self.mode == "ADD" else val
        setattr(obj, self.channel, vec)
        self._error = ""
        return self.flow_out(signal)


@register_node
class KeyframeNode(NexusActionNode):
    """关键帧：在当前帧给物体某通道打关键帧（做动画）。"""
    bl_idname = "NexusKeyframe"
    bl_label = "Insert Keyframe"
    bl_icon = "KEYFRAME_HLT"

    data_path: EnumProperty(name="Channel", items=[
        ("location", "Location", ""), ("rotation_euler", "Rotation", ""), ("scale", "Scale", ""),
    ], default="location")
    frame_offset: IntProperty(name="Frame Offset", default=0)

    def init_sockets(self):
        self.add_in_flow(); self.add_in("NexusObjectSocket", "Object"); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "data_path", text=""); layout.prop(self, "frame_offset")

    def process(self, signal, engine):
        obj = _resolve_object(self, engine, signal)
        if obj is None:
            self._error = "no object"; return []
        frame = bpy.context.scene.frame_current + self.frame_offset
        obj.keyframe_insert(data_path=self.data_path, frame=frame)
        return self.flow_out(signal)


@register_node
class CreateMeshNode(NexusActionNode):
    """生成网格：在指定位置生成基本体（建模）。位置/参数可来自 payload。"""
    bl_idname = "NexusCreateMesh"
    bl_label = "Create Primitive"
    bl_icon = "MESH_CUBE"

    primitive: EnumProperty(name="Type", items=[
        ("cube", "Cube", ""), ("uv_sphere", "Sphere", ""), ("cylinder", "Cylinder", ""),
        ("cone", "Cone", ""), ("torus", "Torus", ""), ("ico_sphere", "Ico Sphere", ""),
    ], default="cube")
    size: FloatProperty(name="Size", default=1.0, min=0.0)
    loc_expr: StringProperty(name="Location", default="(0, 0, count)",
                             description="表达式返回 (x,y,z)，可用 payload 变量")
    collect_key: StringProperty(name="Output Object Key", default="object")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow(); self.add_out("NexusObjectSocket", "Object")

    def draw_body(self, context, layout):
        layout.prop(self, "primitive", text=""); layout.prop(self, "size"); layout.prop(self, "loc_expr")

    def process(self, signal, engine):
        v = dict(signal.payload); v.update(signal.context)
        try:
            loc = expr.evaluate(self.loc_expr, v) if self.loc_expr.strip() else (0, 0, 0)
            loc = tuple(float(x) for x in loc)[:3]
        except Exception as e:
            self._error = f"loc expr: {e}"; loc = (0, 0, 0)
        fn = getattr(bpy.ops.mesh, f"primitive_{self.primitive}_add", None)
        if fn is None:
            self._error = "bad primitive"; return []
        kwargs = {"location": loc}
        try:
            fn(size=self.size, **kwargs)
        except TypeError:
            try: fn(radius=self.size, **kwargs)
            except TypeError: fn(**kwargs)
        obj = bpy.context.view_layer.objects.active
        self._error = ""
        return self.flow_out(signal, **{self.collect_key: obj})


@register_node
class ModifierNode(NexusActionNode):
    """修改器：给物体加/调修改器（程序化建模）。"""
    bl_idname = "NexusModifier"
    bl_label = "Add Modifier"
    bl_icon = "MODIFIER"

    mod_type: EnumProperty(name="Type", items=[
        ("SUBSURF", "Subdivision", ""), ("ARRAY", "Array", ""),
        ("BEVEL", "Bevel", ""), ("SOLIDIFY", "Solidify", ""), ("WIREFRAME", "Wireframe", ""),
    ], default="SUBSURF")
    amount: FloatProperty(name="Amount", default=2.0)

    def init_sockets(self):
        self.add_in_flow(); self.add_in("NexusObjectSocket", "Object"); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "mod_type", text=""); layout.prop(self, "amount")

    def process(self, signal, engine):
        obj = _resolve_object(self, engine, signal)
        if obj is None:
            self._error = "no object"; return []
        m = obj.modifiers.new(name=self.mod_type.title(), type=self.mod_type)
        if self.mod_type == "SUBSURF":
            m.levels = int(self.amount); m.render_levels = int(self.amount)
        elif self.mod_type == "ARRAY":
            m.count = int(self.amount)
        elif self.mod_type in ("BEVEL", "SOLIDIFY"):
            m.width = self.amount if self.mod_type == "BEVEL" else None
            if self.mod_type == "SOLIDIFY":
                m.thickness = self.amount
        return self.flow_out(signal)


@register_node
class VisibilityNode(NexusActionNode):
    """可见性：根据表达式显示/隐藏物体。"""
    bl_idname = "NexusVisibility"
    bl_label = "Set Visibility"
    bl_icon = "HIDE_OFF"

    visible_expr: StringProperty(name="Visible If", default="True")

    def init_sockets(self):
        self.add_in_flow(); self.add_in("NexusObjectSocket", "Object"); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "visible_expr")

    def process(self, signal, engine):
        obj = _resolve_object(self, engine, signal)
        if obj is None:
            self._error = "no object"; return []
        v = dict(signal.payload); v.update(signal.context)
        try:
            vis = bool(expr.evaluate(self.visible_expr, v))
        except expr.ExprError as e:
            self._error = str(e); return []
        obj.hide_viewport = not vis; obj.hide_render = not vis
        return self.flow_out(signal)


@register_node
class PrintNode(NexusActionNode):
    """打印：把 payload 打到系统控制台，最朴素的副作用 / 调试。"""
    bl_idname = "NexusPrint"
    bl_label = "Print"
    bl_icon = "CONSOLE"

    prefix: StringProperty(name="Prefix", default="NEXUS")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.prop(self, "prefix")

    def process(self, signal, engine):
        print(f"[{self.prefix}] {signal.snapshot()}")
        return self.flow_out(signal)
