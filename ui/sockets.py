"""Custom socket family.

Flow sockets carry the signal pulse (no data, just topology). Value sockets
carry typed data and are pull-evaluated. Colors follow Blender conventions.
"""
from __future__ import annotations

import bpy
from bpy.types import NodeSocket
from bpy.props import FloatProperty, FloatVectorProperty, StringProperty, BoolProperty, IntProperty, PointerProperty

from ..core.registry import register_socket

FLOW_COLOR = (0.9, 0.55, 0.1, 1.0)


@register_socket
class NexusFlowSocket(NodeSocket):
    bl_idname = "NexusFlowSocket"
    bl_label = "Flow"

    def draw(self, context, layout, node, text):
        layout.label(text=text)

    def draw_color(self, context, node):
        return FLOW_COLOR


@register_socket
class NexusNumberSocket(NodeSocket):
    bl_idname = "NexusNumberSocket"
    bl_label = "Number"
    default_value: FloatProperty(name="Value", default=0.0)

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.6, 0.6, 0.6, 1.0)


@register_socket
class NexusIntSocket(NodeSocket):
    bl_idname = "NexusIntSocket"
    bl_label = "Integer"
    default_value: IntProperty(name="Value", default=0)

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.0, 0.6, 0.45, 1.0)


@register_socket
class NexusBoolSocket(NodeSocket):
    bl_idname = "NexusBoolSocket"
    bl_label = "Boolean"
    default_value: BoolProperty(name="Value", default=False)

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.8, 0.6, 0.9, 1.0)


@register_socket
class NexusVectorSocket(NodeSocket):
    bl_idname = "NexusVectorSocket"
    bl_label = "Vector"
    default_value: FloatVectorProperty(name="Vector", size=3, default=(0.0, 0.0, 0.0))

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            col = layout.column()
            col.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.4, 0.4, 0.9, 1.0)


@register_socket
class NexusStringSocket(NodeSocket):
    bl_idname = "NexusStringSocket"
    bl_label = "String"
    default_value: StringProperty(name="Text", default="")

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.2, 0.7, 0.3, 1.0)


@register_socket
class NexusObjectSocket(NodeSocket):
    bl_idname = "NexusObjectSocket"
    bl_label = "Object"
    default_value: PointerProperty(name="Object", type=bpy.types.Object)

    def draw(self, context, layout, node, text):
        if self.is_output:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.9, 0.5, 0.2, 1.0)


@register_socket
class NexusDataSocket(NodeSocket):
    """Generic data carrier (dict/list/any). Drawn as label only."""
    bl_idname = "NexusDataSocket"
    bl_label = "Data"

    def draw(self, context, layout, node, text):
        layout.label(text=text)

    def draw_color(self, context, node):
        return (0.55, 0.55, 0.2, 1.0)
