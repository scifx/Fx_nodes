"""Addon preferences: AI credentials (kept out of .blend) + safety toggles."""
from __future__ import annotations

import bpy
from bpy.types import AddonPreferences
from bpy.props import StringProperty, BoolProperty, FloatProperty


class NexusPreferences(AddonPreferences):
    bl_idname = "nexus_nodes"

    ai_base_url: StringProperty(
        name="AI Base URL",
        default="https://api.openai.com/v1",
        description="OpenAI 兼容端点。可填 Ollama (http://localhost:11434/v1) 等。",
    )
    ai_api_key: StringProperty(name="API Key", default="", subtype="PASSWORD")
    ai_model: StringProperty(name="Default Model", default="gpt-4o-mini")

    allow_ai: BoolProperty(name="Enable AI Nodes", default=True)
    confirm_ai_scene: BoolProperty(name="Confirm before AI scene edits", default=True)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="AI Provider (OpenAI-compatible)", icon="OUTLINER_OB_LIGHT")
        box.prop(self, "ai_base_url")
        box.prop(self, "ai_api_key")
        box.prop(self, "ai_model")
        row = box.row()
        row.operator("nexus.test_ai", icon="PLUGIN")
        box2 = layout.box()
        box2.label(text="Safety", icon="LOCKED")
        box2.prop(self, "allow_ai")
        box2.prop(self, "confirm_ai_scene")
