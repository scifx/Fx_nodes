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

    def test_ternary_and_collections(self):
        self.assertEqual(expr.evaluate("[i for i in range(3)]") if False else expr.evaluate("range(3)"), [0, 1, 2])
        self.assertEqual(expr.evaluate("{'x': 1, 'y': 2}")["y"], 2)

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
            return [("out", sig.child(value=10))]

        def doubler(sig, eng):
            return [("out", sig.child(value=sig.get("value") * 2))]

        seen = {}

        def sink(sig, eng):
            seen["value"] = sig.get("value")
            return []

        g.add(FakeNode("P", producer)); g.add(FakeNode("D", doubler)); g.add(FakeNode("S", sink))
        g.link("P", "out", "D"); g.link("D", "out", "S")
        ExecutionEngine(g).fire("P")
        self.assertEqual(seen["value"], 20)

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
