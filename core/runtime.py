"""Runtime: wires triggers to real Blender events, owns async + scheduling.

This is the ONLY place that registers bpy handlers/timers, so unregister is
always clean (no leaked handlers across reloads). It also gives the engine
three capabilities triggers/AI/delay need:

    engine.schedule(secs, uid, signal)   -> deferred flow continuation
    engine.continue_from(uid, sock, sig) -> resume flow after async
    engine.run_async(work, on_done, uid) -> offload network to a thread
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Dict, List, Optional, Tuple

try:
    import bpy
    _HAS_BPY = True
except Exception:  # pragma: no cover
    _HAS_BPY = False

from .engine import ExecutionEngine
from .signal import Signal


class NexusRuntime:
    """One runtime per Blender session; manages all active trees' engines."""
    def __init__(self):
        self.engines: Dict[str, ExecutionEngine] = {}      # tree name -> engine
        self.adapters: Dict[str, object] = {}
        self._timer_fns: List[object] = []
        self._handlers: List[Tuple[object, object]] = []   # (handler_list, fn)
        self._modal_running = False
        self._async_results: "queue.Queue[tuple]" = queue.Queue()
        self._delayed: List[Tuple[float, str, str, Signal]] = []   # (fire_time, tree, sock_owner, signal)
        self.running = False

    # ---- engine context ---------------------------------------------------
    def _context_provider(self):
        if not _HAS_BPY:
            return {}
        sc = bpy.context.scene
        fps = sc.render.fps or 24
        return {"frame": sc.frame_current, "time": sc.frame_current / fps,
                "fps": fps, "dt": 1.0 / fps, "wall": time.time()}

    def get_engine(self, tree) -> ExecutionEngine:
        from ..ui.node_tree import BpyGraphAdapter
        name = tree.name
        if name not in self.engines:
            adapter = BpyGraphAdapter(tree)
            eng = ExecutionEngine(adapter, context_provider=self._context_provider)
            self._augment_engine(eng, tree)
            self.engines[name] = eng
            self.adapters[name] = adapter
        return self.engines[name]

    def _augment_engine(self, eng: ExecutionEngine, tree):
        rt = self

        def schedule(secs, uid, signal):
            rt._delayed.append((time.time() + secs, tree.name, uid, signal))

        def continue_from(uid, out_sock, signal):
            # re-enter propagation from uid's output socket
            adapter = rt.adapters.get(tree.name)
            if adapter is None:
                return
            for tgt_uid, _ in adapter.downstream(uid, out_sock):
                eng.fire(tgt_uid, signal.child())

        def run_async(work, on_done, uid):
            def thread_body():
                try:
                    res = work()
                    rt._async_results.put((uid, tree.name, res, None, on_done))
                except Exception as e:  # noqa
                    rt._async_results.put((uid, tree.name, None, str(e), on_done))
            threading.Thread(target=thread_body, daemon=True).start()

        eng.schedule = schedule          # type: ignore[attr-defined]
        eng.continue_from = continue_from  # type: ignore[attr-defined]
        eng.run_async = run_async        # type: ignore[attr-defined]

    # ---- trigger discovery -------------------------------------------------
    def _iter_trigger_nodes(self):
        for tree in bpy.data.node_groups:
            if getattr(tree, "bl_idname", "") != "NexusNodeTree":
                continue
            for node in tree.nodes:
                if hasattr(node, "event_source"):
                    yield tree, node

    def fire_node(self, tree, node, extra_context=None, payload=None):
        eng = self.get_engine(tree)
        self.adapters[tree.name].reindex()
        sig = Signal(payload=dict(payload or {}), source=node.node_uid)
        eng.fire(node.node_uid, sig, extra_context=extra_context)

    # ---- start / stop ------------------------------------------------------
    def start(self):
        if self.running or not _HAS_BPY:
            return
        self.running = True
        self._install_frame_handler()
        self._install_timer_triggers()
        self._install_scene_handlers()
        self._install_main_tick()
        self._fire_start_triggers()
        self._ensure_modal()

    def stop(self):
        self.running = False
        # remove handlers
        for hlist, fn in self._handlers:
            try:
                if fn in hlist:
                    hlist.remove(fn)
            except Exception:
                pass
        self._handlers.clear()
        for fn in self._timer_fns:
            try:
                if bpy.app.timers.is_registered(fn):
                    bpy.app.timers.unregister(fn)
            except Exception:
                pass
        self._timer_fns.clear()
        self._delayed.clear()

    # ---- handler installers ------------------------------------------------
    def _install_frame_handler(self):
        from bpy.app.handlers import frame_change_post

        def on_frame(scene, depsgraph=None):
            if not self.running:
                return
            for tree, node in self._iter_trigger_nodes():
                src = node.event_source()
                if src.get("kind") != "frame":
                    continue
                if src.get("only_playing") and not getattr(bpy.context.screen, "is_animation_playing", False):
                    continue
                if scene.frame_current % max(1, src.get("every_n", 1)) == 0:
                    self.fire_node(tree, node)

        frame_change_post.append(on_frame)
        self._handlers.append((frame_change_post, on_frame))

    def _install_scene_handlers(self):
        from bpy.app import handlers

        def make(event_name, hlist):
            def cb(*args):
                if not self.running:
                    return
                for tree, node in self._iter_trigger_nodes():
                    src = node.event_source()
                    if src.get("kind") == "scene" and src.get("event") == event_name:
                        self.fire_node(tree, node)
            hlist.append(cb)
            self._handlers.append((hlist, cb))

        make("depsgraph", handlers.depsgraph_update_post)
        make("render_pre", handlers.render_pre)
        make("render_post", handlers.render_post)
        make("save_post", handlers.save_post)
        make("load_post", handlers.load_post)

    def _install_timer_triggers(self):
        # one bpy timer per distinct interval, simplest correct approach
        seen = set()
        for tree, node in self._iter_trigger_nodes():
            src = node.event_source()
            if src.get("kind") != "timer" or not src.get("enabled", True):
                continue
            interval = max(0.01, float(src.get("interval", 1.0)))
            key = round(interval, 3)
            if key in seen:
                continue
            seen.add(key)
            self._register_timer(interval)

    def _register_timer(self, interval):
        def tick():
            if not self.running:
                return None
            for tree, node in self._iter_trigger_nodes():
                src = node.event_source()
                if src.get("kind") == "timer" and src.get("enabled", True):
                    if abs(float(src.get("interval", 1.0)) - interval) < 1e-3:
                        self.fire_node(tree, node)
            return interval
        bpy.app.timers.register(tick, first_interval=interval)
        self._timer_fns.append(tick)

    def _install_main_tick(self):
        """A fast housekeeping timer: drains async results + fires delayed flows."""
        def housekeep():
            if not self.running:
                return None
            # async AI results
            drained = 0
            while not self._async_results.empty() and drained < 8:
                uid, tree_name, res, err, on_done = self._async_results.get()
                try:
                    on_done(res, err)
                except Exception:
                    pass
                drained += 1
            # delayed continuations
            now = time.time()
            due = [d for d in self._delayed if d[0] <= now]
            for d in due:
                self._delayed.remove(d)
                _, tree_name, uid, sig = d
                tree = bpy.data.node_groups.get(tree_name)
                if tree:
                    eng = self.get_engine(tree)
                    eng.continue_from(uid, "▶", sig)
            return 0.05
        bpy.app.timers.register(housekeep, first_interval=0.05)
        self._timer_fns.append(housekeep)

    def _fire_start_triggers(self):
        for tree, node in self._iter_trigger_nodes():
            if node.event_source().get("kind") == "start":
                self.fire_node(tree, node)

    def _ensure_modal(self):
        """Start the modal operator that captures key/click triggers."""
        has_input = any(node.event_source().get("kind") in ("key", "click")
                        for _, node in self._iter_trigger_nodes())
        if has_input and not self._modal_running:
            try:
                bpy.ops.nexus.input_listener('INVOKE_DEFAULT')
            except Exception:
                pass

    # ---- modal callback from operator -------------------------------------
    def handle_input_event(self, event):
        """Called by the input modal operator for each window event."""
        if not self.running:
            return
        for tree, node in self._iter_trigger_nodes():
            src = node.event_source()
            kind = src.get("kind")
            if kind == "key":
                if (event.type == src.get("key") and event.value == src.get("value")
                        and event.ctrl == src.get("ctrl") and event.shift == src.get("shift")
                        and event.alt == src.get("alt")):
                    self.fire_node(tree, node, payload={"key": event.type})
            elif kind == "click":
                if event.type == src.get("button") and event.value == "PRESS":
                    payload = {"mouse_x": event.mouse_x, "mouse_y": event.mouse_y}
                    if src.get("require_hit"):
                        obj = self._raycast(event)
                        if obj is None:
                            continue
                        payload["object"] = obj
                    self.fire_node(tree, node, payload=payload)

    def _raycast(self, event):  # best-effort viewport pick
        try:
            import bpy_extras
            region = bpy.context.region
            rv3d = bpy.context.space_data.region_3d
            coord = (event.mouse_region_x, event.mouse_region_y)
            from bpy_extras import view3d_utils
            view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            result, loc, normal, idx, obj, mat = bpy.context.scene.ray_cast(
                depsgraph, ray_origin, view_vector)
            return obj if result else None
        except Exception:
            return None


# module-level singleton
RUNTIME = NexusRuntime()
