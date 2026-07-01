"""Integration test using a mock 'bpy' so we can import the WHOLE addon
headless and verify: all modules import, registry populates, every node
class is well-formed, and the AI expression validator rejects unsafe output.
"""
import json
import os
import sys
import types
import unittest

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PKG_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)
if os.path.basename(PKG_DIR) != "Fx_nodes":
    import importlib.util
    spec = importlib.util.spec_from_file_location("Fx_nodes", os.path.join(PKG_DIR, "__init__.py"), submodule_search_locations=[PKG_DIR])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["Fx_nodes"] = mod
    spec.loader.exec_module(mod)


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
        for c in ["Trigger", "Property", "Logic", "Script", "Data", "Debug", "AI"]:
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

    def test_switch_requires_boolean_eval_result(self):
        from Fx_nodes.nodes.logic import SwitchNode
        from Fx_nodes.core.signal import Signal
        node = SwitchNode.__new__(SwitchNode)
        node.name = "Switch"
        node._error = ""
        engine = types.SimpleNamespace(flow_context={}, global_context={}, node_context=lambda uid: {})

        node.condition = "msg.value > 1"
        out = node.process(Signal(payload={"value": 2}), engine)
        self.assertEqual(out[0][0], "True")

        node.condition = "msg.value"
        out = node.process(Signal(payload={"value": 2}), engine)
        self.assertEqual(out, [])
        self.assertIn("必须返回 True 或 False", node._error)

    def test_context_global_roundtrip_and_nested_paths(self):
        from Fx_nodes.nodes.data import ContextNode
        from Fx_nodes.core.signal import Signal
        engine = types.SimpleNamespace(flow_context={}, global_context={}, node_context=lambda uid: {})

        writer = ContextNode.__new__(ContextNode)
        writer._error = ""; writer.mode = "MSG_TO_GLOBAL"
        writer.context_key = "settings.seed"
        writer.msg_path = "payload"
        writer.value_expr = "payload + 1"
        writer.last_value = ""
        sig = Signal(payload={"payload": 41})
        self.assertTrue(writer.process(sig, engine))
        self.assertEqual(engine.global_context, {"settings": {"seed": 42}})

        reader = ContextNode.__new__(ContextNode)
        reader._error = ""; reader.mode = "GLOBAL_TO_MSG"
        reader.context_key = "Global.settings.seed"
        reader.msg_path = "answer"
        reader.value_expr = "payload"
        reader.last_value = ""
        out = reader.process(sig, engine)
        self.assertTrue(out)
        self.assertEqual(sig.msg["answer"], 42)
        self.assertEqual(reader._error, "")

    def test_context_global_legacy_alias_and_capital_root(self):
        from Fx_nodes.nodes.data import ContextNode
        from Fx_nodes.core.signal import Signal
        # Simulate an old/reloaded engine where Debug/legacy code populated
        # global_attrs but global_context is a distinct empty dict.
        engine = types.SimpleNamespace(flow_context={}, global_context={}, global_attrs={"test": 10}, node_context=lambda uid: {})
        node = ContextNode.__new__(ContextNode)
        node._error = ""; node.mode = "GLOBAL_TO_MSG"
        node.context_key = "test"
        node.msg_path = "payload"
        node.value_expr = "payload"
        node.last_value = ""
        sig = Signal(payload={})
        self.assertTrue(node.process(sig, engine))
        self.assertEqual(sig.msg["payload"], 10)
        self.assertIs(engine.global_attrs, engine.global_context)

        sig2 = Signal(payload={})
        node.context_key = 'Global["test"]'
        self.assertTrue(node.process(sig2, engine))
        self.assertEqual(sig2.msg["payload"], 10)

    def test_context_global_missing_key_reports_error(self):
        from Fx_nodes.nodes.data import ContextNode
        from Fx_nodes.core.signal import Signal
        engine = types.SimpleNamespace(flow_context={}, global_context={}, node_context=lambda uid: {})
        node = ContextNode.__new__(ContextNode)
        node._error = ""; node.mode = "GLOBAL_TO_MSG"
        node.context_key = "missing"
        node.msg_path = "payload"
        node.value_expr = "payload"
        node.last_value = ""
        self.assertEqual(node.process(Signal(payload={}), engine), [])
        self.assertIn("global context key not found", node._error)

    def test_debug_reads_global_and_show_context_includes_global(self):
        from Fx_nodes.nodes.data import DebugNode
        from Fx_nodes.core.signal import Signal

        class DebugHarness(DebugNode, dict):
            pass

        engine = types.SimpleNamespace(flow_context={"f": 1}, global_context={}, global_attrs={"test": 10}, node_context=lambda uid: {})
        node = DebugHarness()
        node._error = ""; node.path = "Global"; node.fire_count = 0
        node.show_context = False; node.log_to_text = False; node.debug_text_name = ""; node.max_rows = 8
        self.assertTrue(node.process(Signal(payload={}), engine))
        self.assertEqual(json.loads(node["_preview"]), {"test": 10})

        node.show_context = True
        self.assertTrue(node.process(Signal(payload={}, context={"frame": 7}), engine))
        preview = json.loads(node["_preview"])
        self.assertEqual(preview["Global"], {"test": 10})
        self.assertEqual(preview["flow"], {"f": 1})
        self.assertEqual(preview["context"], {"frame": 7})

    def test_debug_missing_path_reports_error_instead_of_null(self):
        from Fx_nodes.nodes.data import DebugNode
        from Fx_nodes.core.signal import Signal

        class DebugHarness(DebugNode, dict):
            pass

        engine = types.SimpleNamespace(flow_context={}, global_context={}, node_context=lambda uid: {})
        node = DebugHarness()
        node._error = ""; node.path = "Global.missing"; node.fire_count = 0
        node.show_context = False; node.log_to_text = False; node.debug_text_name = ""; node.max_rows = 8
        self.assertEqual(node.process(Signal(payload={}), engine), [])
        self.assertIn("path not found: Global.missing", node._error)

    def test_runtime_rebinds_stale_adapter_for_same_tree_name(self):
        from Fx_nodes.core.engine import ExecutionEngine
        from Fx_nodes.core.runtime import FxRuntime

        class StaleAdapter:
            def rebind(self, tree):
                raise ReferenceError("StructRNA of type FxNodeTree has been removed")
            def get_node(self, uid):
                return None
            def downstream(self, uid, out_socket):
                return []

        rt = FxRuntime()
        stale = StaleAdapter()
        eng = ExecutionEngine(stale)
        eng.global_context["kept"] = 1
        rt.adapters["Tree"] = stale
        rt.engines["Tree"] = eng

        live_tree = types.SimpleNamespace(name="Tree", nodes=[])
        repaired = rt.get_engine(live_tree)
        self.assertIs(repaired, eng)
        self.assertIs(repaired.graph, rt.adapters["Tree"])
        self.assertIs(rt.adapters["Tree"].tree, live_tree)
        self.assertEqual(repaired.global_context["kept"], 1)

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

    def test_ui_panels_registered(self):
        from Fx_nodes.ui.panels import CLASSES, FXNODES_PT_engine, FXNODES_PT_ai
        self.assertIn(FXNODES_PT_engine, CLASSES)
        self.assertIn(FXNODES_PT_ai, CLASSES)

    def test_register_unregister_runs(self):
        # should not raise with mocked bpy.utils
        self.addon.register()
        self.addon.unregister()

    def test_multiline_text_datablocks_and_previews(self):
        from Fx_nodes.nodes.logic import ExpressionNode
        node = ExpressionNode.__new__(ExpressionNode)
        node.expression = "10 + 20"
        node.expr_text_name = ""
        self.assertEqual(node.get_expression(), "10 + 20")
        # test that draw_body and draw_previews exist separately
        self.assertTrue(hasattr(node, "draw_body"))
        self.assertTrue(hasattr(node, "draw_previews"))

    def test_dynamic_timer_trigger_updates(self):
        from Fx_nodes.core.runtime import RUNTIME
        from Fx_nodes.nodes.triggers import TimerTriggerNode
        node = TimerTriggerNode.__new__(TimerTriggerNode)
        node.interval = 0.5
        node.enabled = True
        self.assertEqual(node.event_source(), {"kind": "timer", "interval": 0.5, "enabled": True})
        self.assertTrue(hasattr(RUNTIME, "_timer_last_fire"))
        self.assertTrue(hasattr(RUNTIME, "_tag_redraw_ui"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
