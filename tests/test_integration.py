"""Integration test using a mock 'bpy' so we can import the WHOLE addon
headless and verify: all modules import, registry populates, every node
class is well-formed, and the AI expression validator rejects unsafe output.
"""
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def install_bpy_mock():
    """A minimal bpy good enough to import the package & populate registry."""
    bpy = types.ModuleType("bpy")

    class _Prop:
        def __init__(self, **kw): self.kw = kw
    def prop_factory(name):
        return lambda **kw: _Prop(name=name, **kw)

    props = types.ModuleType("bpy.props")
    for p in ["FloatProperty", "IntProperty", "StringProperty", "BoolProperty",
              "EnumProperty", "FloatVectorProperty", "PointerProperty"]:
        setattr(props, p, prop_factory(p))

    # base classes are just markers
    class _Base:
        def __init_subclass__(cls, **kw): super().__init_subclass__(**kw)
    types_mod = types.ModuleType("bpy.types")
    for t in ["Node", "NodeSocket", "NodeTree", "Operator", "Panel", "Menu",
              "AddonPreferences", "Object"]:
        setattr(types_mod, t, type(t, (_Base,), {}))
    # the real add-menu Blender exposes; give it append/remove
    types_mod.NODE_MT_add = types.SimpleNamespace(append=lambda f: None,
                                                  remove=lambda f: None)

    # handlers/timers/ops stubs
    app = types.ModuleType("bpy.app")
    handlers = types.ModuleType("bpy.app.handlers")
    for h in ["frame_change_post", "depsgraph_update_post", "render_pre",
              "render_post", "save_post", "load_post"]:
        setattr(handlers, h, [])
    timers = types.SimpleNamespace(register=lambda *a, **k: None,
                                   unregister=lambda *a: None,
                                   is_registered=lambda *a: False)
    app.handlers = handlers
    app.timers = timers

    bpy.props = props
    bpy.types = types_mod
    bpy.app = app
    bpy.utils = types.SimpleNamespace(register_class=lambda c: None,
                                      unregister_class=lambda c: None)
    bpy.data = types.SimpleNamespace(node_groups=[])
    bpy.context = types.SimpleNamespace()
    bpy.ops = types.SimpleNamespace()

    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = props
    sys.modules["bpy.types"] = types_mod
    sys.modules["bpy.app"] = app
    sys.modules["bpy.app.handlers"] = handlers


class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_bpy_mock()
        import Fx_nodes
        cls.addon = Fx_nodes
        from Fx_nodes.core import registry
        cls.registry = registry

    def test_registry_populated(self):
        nodes = self.registry.NODE_CLASSES
        # spot-check key nodes exist
        for idn in ["FxTimerTrigger", "FxKeyTrigger", "FxClickTrigger",
                    "FxFrameTrigger", "FxFunction", "FxExpression", "FxSwitch", "FxCounter",
                    "FxDebug", "FxChange", "FxContext",
                    "FxPropertyGet", "FxPropertySet",
                    "FxAIChat", "FxAIExpression", "FxAISceneCommand"]:
            self.assertIn(idn, nodes, f"missing node {idn}")
        self.assertGreaterEqual(len(nodes), 20)

    def test_every_node_has_required_attrs(self):
        for idn, cls in self.registry.NODE_CLASSES.items():
            self.assertTrue(hasattr(cls, "bl_label"), idn)
            self.assertTrue(hasattr(cls, "category"), idn)

    def test_categories_complete(self):
        cats = self.registry.ordered_categories()
        for c in ["Trigger", "Logic", "Action", "Data", "AI"]:
            self.assertIn(c, cats)

    def test_action_layer_is_property_first(self):
        nodes = self.registry.NODE_CLASSES
        self.assertIn("FxPropertySet", nodes)
        for removed in ["FxTransform", "FxKeyframe", "FxCreateMesh", "FxModifier", "FxVisibility", "FxPrint", "FxMath", "FxVariable", "FxSceneProperty", "FxDataPreview", "FxAttribute", "FxGlobalAttribute", "FxBranch"]:
            self.assertNotIn(removed, nodes)

    def test_socket_classes(self):
        socks = self.registry.SOCKET_CLASSES
        for s in ["FxFlowSocket", "FxNumberSocket", "FxVectorSocket",
                  "FxStringSocket", "FxObjectSocket", "FxDataSocket"]:
            self.assertIn(s, socks)

    def test_ai_expr_validator_rejects_unsafe(self):
        from Fx_nodes.nodes.ai import AIExpressionNode
        node = AIExpressionNode.__new__(AIExpressionNode)
        node._error = ""
        # safe one should validate
        self.assertTrue(node.validate_and_store("sin(time) * 5"))
        node._error = ""
        # unsafe must be rejected
        self.assertFalse(node.validate_and_store("__import__('os').system('rm -rf /')"))

    def test_provider_constructs(self):
        from Fx_nodes.nodes.ai.provider import make_provider
        p = make_provider("openai-compat", base_url="http://x/v1", api_key="k", model="m")
        self.assertEqual(p.model, "m")

    def test_register_unregister_runs(self):
        # should not raise with mocked bpy.utils
        self.addon.register()
        self.addon.unregister()


if __name__ == "__main__":
    unittest.main(verbosity=2)
