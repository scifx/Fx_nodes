"""Data nodes: preview/inspect signals, store variables, read scene props."""
from __future__ import annotations

import json
import bpy
from bpy.props import StringProperty, IntProperty, FloatProperty, EnumProperty, BoolProperty

from ...core.base import NexusBaseNode
from ...core.registry import register_node


@register_node
class DataPreviewNode(NexusBaseNode):
    """数据预览器：把流经的 signal payload 实时快照，画在节点体里。

    它是透明的——信号原样继续向下流；同时把最新快照存到 self['_preview'] 供
    节点体绘制和全局 Inspector 面板读取。
    """
    bl_idname = "NexusDataPreview"
    bl_label = "Data Preview"
    bl_icon = "VIEWZOOM"
    category = "Data"
    nexus_color = (0.32, 0.28, 0.12)

    max_rows: IntProperty(name="Max Rows", default=8, min=1, max=32)
    fire_count: IntProperty(name="Fires", default=0)
    show_context: BoolProperty(name="Show Context", default=False)

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow()

    def draw_body(self, context, layout):
        layout.label(text=f"Fires: {self.fire_count}", icon="DRIVER")
        raw = self.get("_preview", "{}")
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        box = layout.box()
        if not data:
            box.label(text="(no data yet)", icon="INFO")
        for i, (k, val) in enumerate(data.items()):
            if i >= self.max_rows:
                box.label(text=f"… +{len(data) - self.max_rows} more")
                break
            row = box.row()
            row.label(text=str(k))
            row.label(text=str(val)[:28])
        layout.prop(self, "show_context", text="Context")

    def process(self, signal, engine):
        self.fire_count += 1
        snap = signal.snapshot()
        if self.show_context:
            snap = {**snap, **{f"@{k}": v for k, v in signal.context.items()}}
        try:
            self["_preview"] = json.dumps(snap, ensure_ascii=False)
        except Exception:
            self["_preview"] = "{}"
        return self.flow_out(signal)


@register_node
class VariableNode(NexusBaseNode):
    """变量存储：写/读跨点火持久的变量（存在引擎运行时字典）。"""
    bl_idname = "NexusVariable"
    bl_label = "Variable"
    bl_icon = "RNA"
    category = "Data"
    nexus_color = (0.3, 0.28, 0.14)

    var_name: StringProperty(name="Name", default="myVar")
    mode: EnumProperty(name="Mode", items=[
        ("WRITE", "Write from payload", ""),
        ("READ", "Read into payload", ""),
    ], default="READ")
    source_key: StringProperty(name="Key", default="result")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow(); self.add_out("NexusDataSocket", "value")

    def draw_body(self, context, layout):
        layout.prop(self, "var_name"); layout.prop(self, "mode", text=""); layout.prop(self, "source_key")

    def _store(self, engine):
        return engine.__dict__.setdefault("_variables", {})

    def process(self, signal, engine):
        store = self._store(engine)
        if self.mode == "WRITE":
            store[self.var_name] = signal.get(self.source_key)
            return self.flow_out(signal)
        else:
            return self.flow_out(signal, **{self.source_key: store.get(self.var_name)})

    def compute(self, socket_name, signal, engine):
        return self._store(engine).get(self.var_name)


@register_node
class ScenePropertyNode(NexusBaseNode):
    """场景属性读取：读取 frame_current / fps / 选中数等到 payload。"""
    bl_idname = "NexusSceneProperty"
    bl_label = "Scene Property"
    bl_icon = "SCENE_DATA"
    category = "Data"
    nexus_color = (0.3, 0.28, 0.14)

    prop: EnumProperty(name="Property", items=[
        ("frame", "Current Frame", ""), ("fps", "FPS", ""),
        ("selected", "Selected Count", ""), ("objects", "Object Count", ""),
        ("time", "Time (s)", ""),
    ], default="frame")
    key: StringProperty(name="Key", default="frame")

    def init_sockets(self):
        self.add_in_flow(); self.add_out_flow(); self.add_out("NexusNumberSocket", "value")

    def draw_body(self, context, layout):
        layout.prop(self, "prop", text=""); layout.prop(self, "key")

    def _read(self):
        sc = bpy.context.scene
        if self.prop == "frame": return sc.frame_current
        if self.prop == "fps": return sc.render.fps
        if self.prop == "selected": return len(bpy.context.selected_objects)
        if self.prop == "objects": return len(sc.objects)
        if self.prop == "time": return sc.frame_current / sc.render.fps
        return 0

    def process(self, signal, engine):
        return self.flow_out(signal, **{self.key: self._read()})

    def compute(self, socket_name, signal, engine):
        return self._read()
