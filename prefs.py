"""Addon preferences: AI credentials (kept out of .blend) + safety toggles."""
from __future__ import annotations

import bpy
from bpy.types import AddonPreferences
from bpy.props import StringProperty, BoolProperty

from .config import get_ai_default

# In legacy add-on installs this is usually "Fx_nodes".  In Blender 4.x
# extension installs it can be a fully-qualified package name such as
# "bl_ext.user_default.fx_nodes".  Using __package__ keeps preferences bound to
# the actual add-on module instead of a hard-coded legacy id.
ADDON_ID = __package__ or "Fx_nodes"


def get_preferences(context=None):
    """Return this add-on's preferences, tolerant of legacy/extension ids."""
    context = context or bpy.context
    addons = getattr(getattr(context, "preferences", None), "addons", {})
    candidates = [ADDON_ID, "Fx_nodes", "fx_nodes"]
    for key in candidates:
        try:
            return addons[key].preferences
        except Exception:
            pass
    # last resort: find by preference RNA/class name, useful during development reloads
    try:
        for addon in addons.values():
            prefs = getattr(addon, "preferences", None)
            if prefs and prefs.__class__.__name__ == "FxPreferences":
                return prefs
    except Exception:
        pass
    raise KeyError("Fx_nodes add-on preferences not found")


class FxPreferences(AddonPreferences):
    bl_idname = ADDON_ID

    ai_base_url: StringProperty(
        name="AI Base URL",
        default=get_ai_default("base_url", "https://api.openai.com/v1"),
        description="OpenAI 兼容端点。可填 Ollama (http://localhost:11434/v1) 等。",
    )
    ai_api_key: StringProperty(name="API Key", default="", subtype="PASSWORD")
    ai_model: StringProperty(name="Default Model", default="gpt-4o-mini")

    allow_ai: BoolProperty(name="Enable AI Nodes", default=True)
    allow_full_python: BoolProperty(
        name="Allow Full Python Function",
        default=True,
        description="允许 Function 节点执行任意 Python 代码 (如关掉则跳过执行)",
    )
    confirm_ai_scene: BoolProperty(name="Confirm before AI scene edits", default=True)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="AI Provider (OpenAI-compatible)", icon="OUTLINER_OB_LIGHT")
        box.prop(self, "ai_base_url")
        box.prop(self, "ai_api_key")
        box.prop(self, "ai_model")
        row = box.row()
        row.operator("fx_nodes.test_ai", icon="PLUGIN")
        box2 = layout.box()
        box2.label(text="Safety Controls", icon="LOCKED")
        box2.prop(self, "allow_ai")
        box2.prop(self, "allow_full_python")
        box2.prop(self, "confirm_ai_scene")
