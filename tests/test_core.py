"""Unit tests for the bpy-free core: expr sandbox + engine propagation."""
import os
import sys
import unittest

import importlib.util

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")


def _load(modname, filename):
    """Load a core module by path, bypassing the package __init__ (which needs bpy)."""
    spec = importlib.util.spec_from_file_location(f"_nx_{modname}", os.path.join(CORE, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


expr = _load("expr", "expr.py")
path_mod = _load("path", "path.py")
msgpath = _load("msgpath", "msgpath.py")
signal_mod = _load("signal", "signal.py")
# engine imports ".signal" relatively; provide it under the expected name
sys.modules["_nx_engine_signal"] = signal_mod
engine_spec = importlib.util.spec_from_file_location("_nx_engine", os.path.join(CORE, "engine.py"))


def _load_engine():
    # engine.py uses `from .signal import Signal`; emulate package context
    import types as _types
    pkg = _types.ModuleType("_nxpkg")
    pkg.__path__ = [CORE]
    sys.modules["_nxpkg"] = pkg
    sig_spec = importlib.util.spec_from_file_location("_nxpkg.signal", os.path.join(CORE, "signal.py"))
    sig = importlib.util.module_from_spec(sig_spec); sys.modules["_nxpkg.signal"] = sig
    sig_spec.loader.exec_module(sig)
    eng_spec = importlib.util.spec_from_file_location("_nxpkg.engine", os.path.join(CORE, "engine.py"))
    eng = importlib.util.module_from_spec(eng_spec); sys.modules["_nxpkg.engine"] = eng
    eng_spec.loader.exec_module(eng)
    return sig, eng


signal_mod, engine_mod = _load_engine()
Signal = signal_mod.Signal
ExecutionEngine = engine_mod.ExecutionEngine


class FakeNode:
    def __init__(self, uid, fn):
        self.node_uid = uid; self._fn = fn; self._error = ""
    def process(self, signal, engine):
        return self._fn(signal, engine)


class FakeGraph:
    def __init__(self):
        self.nodes = {}; self.edges = {}
    def add(self, node):
        self.nodes[node.node_uid] = node; return node
    def link(self, s, o, t, i="in"):
        self.edges.setdefault((s, o), []).append((t, i))
    def get_node(self, uid):
        return self.nodes.get(uid)
    def downstream(self, uid, out_socket):
        return self.edges.get((uid, out_socket), [])


class TestExpr(unittest.TestCase):
    def test_basic_math(self):
        self.assertAlmostEqual(expr.evaluate("2 + 3 * 4"), 14)
        self.assertAlmostEqual(expr.evaluate("clamp(5, 0, 1)"), 1)
        self.assertAlmostEqual(expr.evaluate("lerp(0, 10, 0.5)"), 5)
        self.assertAlmostEqual(expr.evaluate("map_range(5,0,10,0,100)"), 50)

    def test_variables(self):
        self.assertAlmostEqual(expr.evaluate("amp * 2", {"amp": 3}), 6)
        self.assertEqual(expr.evaluate("'on' if f%2==0 else 'off'", {"f": 4}), "on")

    def test_plain_dict_expression_api(self):
        vars = {
            "msg": {"payload": {"x": 2}, "topic": "t"},
            "payload": {"x": 2},
            "flow": {"count": 3},
            "global_context": {"seed": 4},
            "Global": {"seed": 4},
            "context": {"frame": 10},
        }
        self.assertTrue(expr.evaluate("msg['payload']['x'] == 2 and topic == 't'", {**vars, "topic": "t"}))
        self.assertEqual(expr.evaluate("flow['count'] + Global['seed']", vars), 7)
        self.assertEqual(expr.evaluate("context['frame'] + flow['count']", vars), 13)
        self.assertEqual(expr.evaluate("'Global.seed'"), "Global.seed")
        with self.assertRaises(expr.ExprError):
            expr.evaluate("msg.payload", vars)
        with self.assertRaises(expr.ExprError):
            expr.evaluate("global.seed", vars)

    def test_missing_payload_is_falsy_for_switch_conditions(self):
        self.assertFalse(expr.evaluate("payload > 0", {"payload": expr.MISSING}))

    def test_ternary_and_collections(self):
        self.assertEqual(expr.evaluate("[i for i in range(3)]"), [0, 1, 2])
        self.assertEqual(expr.evaluate("{'x': 1, 'y': 2}")["y"], 2)

    def test_python_eval_methods_and_msg_keys(self):
        vars = {"msg": {"name": "cube", "items": [1, 2, 3]}, "name": "cube", "items": [1, 2, 3]}
        self.assertEqual(expr.evaluate("name.upper()", vars), "CUBE")
        self.assertEqual(expr.evaluate("msg['name'].upper()", vars), "CUBE")
        self.assertEqual(expr.evaluate("sum(msg['items'])", vars), 6)

    def test_rejects_import(self):
        with self.assertRaises(expr.ExprError):
            expr.evaluate("__import__('os')")

    def test_rejects_dunder(self):
        with self.assertRaises(expr.ExprError):
            expr.evaluate("(1).__class__")

    def test_rejects_unknown_func(self):
        with self.assertRaises(expr.ExprError):
            expr.evaluate("open('x')")

    def test_rejects_bad_attr(self):
        with self.assertRaises(expr.ExprError):
            expr.evaluate("x.evil", {"x": 1})


class TestMsgPath(unittest.TestCase):
    def test_msg_flow_global_get_set_delete(self):
        msg = {"payload": {"x": 1}, "topic": "t"}
        flow = {}
        glob = {}
        self.assertEqual(msgpath.get("payload.x", msg), 1)
        self.assertEqual(msgpath.get("msg['payload'].x", msg), 1)
        msgpath.set("payload.x", 2, msg, flow, glob)
        msgpath.set("flow.count", 3, msg, flow, glob)
        msgpath.set("Global.seed", 4, msg, flow, glob)
        self.assertEqual(msg["payload"]["x"], 2)
        self.assertEqual(flow["count"], 3)
        self.assertEqual(glob["seed"], 4)
        msgpath.delete("payload.x", msg, flow, glob)
        self.assertNotIn("x", msg["payload"])

    def test_set_creates_intermediate_lists(self):
        msg = {}
        msgpath.set("payload.items[0].name", "A", msg)
        msgpath.set("payload.items[1].name", "B", msg)
        self.assertEqual(msgpath.get("payload.items[0].name", msg), "A")
        self.assertEqual(msgpath.get("payload.items[1].name", msg), "B")


class TestPath(unittest.TestCase):
    def setUp(self):
        import types
        cube = types.SimpleNamespace(location=[1.0, 2.0, 3.0], name="Cube")
        bpy = types.SimpleNamespace(data=types.SimpleNamespace(objects={"Cube": cube}))
        sys.modules["bpy"] = bpy
        self.cube = cube

    def test_resolve_and_set_full_data_path(self):
        self.assertEqual(path_mod.get_path('bpy.data.objects["Cube"].location[0]'), 1.0)
        path_mod.set_path('bpy.data.objects["Cube"].location[0]', 9.0)
        self.assertEqual(self.cube.location[0], 9.0)
        path_mod.set_path('bpy.data.objects["Cube"].name', "Box")
        self.assertEqual(self.cube.name, "Box")

    def test_rejects_unsafe_path(self):
        with self.assertRaises(path_mod.PathError):
            path_mod.validate_path('__import__("os").system("echo bad")')
        with self.assertRaises(path_mod.PathError):
            path_mod.validate_path('bpy.data.__class__')


class TestSignal(unittest.TestCase):
    def test_node_red_msg_payload_topic(self):
        sig = Signal(payload={"payload": 1, "topic": "a"})
        self.assertEqual(sig.msg_payload, 1)
        self.assertEqual(sig.topic, "a")
        sig.msg_payload = 2
        sig.topic = "b"
        child = sig.child(extra=True)
        self.assertEqual(child.msg, {"payload": 2, "topic": "b", "extra": True})
        child.msg["payload"] = 3
        self.assertEqual(sig.msg["payload"], 2)


class TestEngine(unittest.TestCase):
    def test_linear_propagation(self):
        g = FakeGraph()
        log = []

        def mk(name):
            def fn(sig, eng):
                log.append(name)
                return [("out", sig)]
            return fn

        g.add(FakeNode("A", mk("A")))
        g.add(FakeNode("B", mk("B")))
        g.add(FakeNode("C", mk("C")))
        g.link("A", "out", "B")
        g.link("B", "out", "C")

        eng = ExecutionEngine(g)
        processed = eng.fire("A")
        self.assertEqual(log, ["A", "B", "C"])
        self.assertEqual(processed, 3)

    def test_payload_flows_and_enriches(self):
        g = FakeGraph()

        def producer(sig, eng):
            sig.set("value", 10)
            return [("out", sig)]

        def doubler(sig, eng):
            sig.set("value", sig.get("value") * 2)
            return [("out", sig)]

        seen = {}

        def sink(sig, eng):
            seen["value"] = sig.get("value")
            return []

        g.add(FakeNode("P", producer)); g.add(FakeNode("D", doubler)); g.add(FakeNode("S", sink))
        g.link("P", "out", "D"); g.link("D", "out", "S")
        ExecutionEngine(g).fire("P")
        self.assertEqual(seen["value"], 20)

    def test_same_attribute_overwrites_in_flow_order(self):
        g = FakeGraph()
        seen = {}

        def first(sig, eng):
            sig.set("x", 1)
            return [("out", sig)]

        def second(sig, eng):
            sig.set("x", sig.get("x") + 1)
            return [("out", sig)]

        def sink(sig, eng):
            seen["x"] = sig.get("x")
            return []

        g.add(FakeNode("A", first)); g.add(FakeNode("B", second)); g.add(FakeNode("C", sink))
        g.link("A", "out", "B"); g.link("B", "out", "C")
        ExecutionEngine(g).fire("A")
        self.assertEqual(seen["x"], 2)

    def test_process_reported_error_is_not_swallowed(self):
        g = FakeGraph()

        def bad_expr(sig, eng):
            node._error = "bad expression"
            return []

        node = g.add(FakeNode("N", bad_expr))
        eng = ExecutionEngine(g)
        eng.fire("N")
        self.assertEqual(node._error, "bad expression")
        self.assertEqual(eng.stats.errors.get("N"), "bad expression")

    def test_error_isolation(self):
        g = FakeGraph()
        reached = []

        def boom(sig, eng):
            raise ValueError("kaboom")

        def after(sig, eng):
            reached.append(True)
            return []

        # boom is a leaf; a parallel branch must still run
        def root(sig, eng):
            return [("out", sig)]

        g.add(FakeNode("R", root)); g.add(FakeNode("X", boom)); g.add(FakeNode("Y", after))
        g.link("R", "out", "X"); g.link("R", "out", "Y")
        eng = ExecutionEngine(g)
        eng.fire("R")
        self.assertTrue(reached)            # Y ran despite X failing
        self.assertIn("X", eng.stats.errors)

    def test_loop_guard(self):
        g = FakeGraph()
        count = {"n": 0}

        def spin(sig, eng):
            count["n"] += 1
            return [("out", sig)]

        g.add(FakeNode("L", spin))
        g.link("L", "out", "L")           # self loop
        eng = ExecutionEngine(g)
        eng.fire("L")
        # visited-edge set stops re-traversal of identical edge for same signal,
        # hops cap is the absolute backstop. Must terminate.
        self.assertLess(count["n"], 1000)

    def test_global_attribute_table(self):
        g = FakeGraph()

        def writer(sig, eng):
            eng.set_global("seed", 42)
            sig.set("local", eng.get_global("seed"))
            return [("out", sig)]

        seen = {}
        def sink(sig, eng):
            seen["local"] = sig.get("local")
            seen["global"] = eng.global_attrs["seed"]
            return []

        g.add(FakeNode("W", writer)); g.add(FakeNode("S", sink))
        g.link("W", "out", "S")
        ExecutionEngine(g).fire("W")
        self.assertEqual(seen, {"local": 42, "global": 42})

    def test_context_provider(self):
        g = FakeGraph()
        grabbed = {}

        def n(sig, eng):
            grabbed["frame"] = sig.context.get("frame")
            return []

        g.add(FakeNode("N", n))
        eng = ExecutionEngine(g, context_provider=lambda: {"frame": 42})
        eng.fire("N")
        self.assertEqual(grabbed["frame"], 42)


if __name__ == "__main__":
    unittest.main(verbosity=2)
