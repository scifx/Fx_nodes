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


class FxRuntime:
    """One runtime per Blender session; manages all active trees' engines."""
    def __init__(self):
        self.engines: Dict[str, ExecutionEngine] = {}      # tree name -> engine
        self.adapters: Dict[str, object] = {}
        self._timer_fns: List[object] = []
        self._handlers: List[Tuple[object, object]] = []   # (handler_list, fn)
        self._modal_running = False
        self._async_results: "queue.Queue[tuple]" = queue.Queue()
        self._delayed: List[Tuple[float, str, str, Signal]] = []   # (fire_time, tree, sock_owner, signal)
        self._timer_last_fire: Dict[str, float] = {}               # node_uid -> last fire time
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
        """Return an engine bound to the *current* live tree object.

        Engines/adapters are cached by tree name, but Blender can invalidate the
        underlying RNA object while leaving a new node group with the same name
        (addon reload, file reload, delete/recreate).  Always rebind the cached
        adapter to the live tree passed by the operator/handler before firing.
        """
        from ..ui.node_tree import BpyGraphAdapter
        name = tree.name
        adapter = self.adapters.get(name)
        eng = self.engines.get(name)

        if adapter is None:
            adapter = BpyGraphAdapter(tree)
            self.adapters[name] = adapter
        else:
            try:
                adapter.rebind(tree)
            except ReferenceError:
                adapter = BpyGraphAdapter(tree)
                self.adapters[name] = adapter

        if eng is None:
            eng = ExecutionEngine(adapter, context_provider=self._context_provider)
            self.engines[name] = eng
        else:
            # Keep existing flow/global/node contexts, but make graph live again.
            eng.graph = adapter

        # Reinstall helpers so their closures capture the current tree name, not
        # an old StructRNA object that may later be removed.
        self._augment_engine(eng, tree)
        return eng

    def _record_error(self, tree_name: str, uid: str, msg: str):
        """Best-effort bridge for runtime/async errors into node UI + stats."""
        eng = self.engines.get(tree_name)
        if eng is not None:
            eng.stats.node_error(uid, msg)
            try:
                eng._emit("error", node=uid, msg=msg)
            except Exception:
                pass
        if not _HAS_BPY:
            return
        try:
            tree = bpy.data.node_groups.get(tree_name)
            if tree:
                for node in tree.nodes:
                    if getattr(node, "node_uid", "") == uid:
                        node._error = msg
                        break
        except Exception:
            pass

    def _augment_engine(self, eng: ExecutionEngine, tree):
        rt = self
        tree_name = tree.name

        def schedule(secs, uid, signal):
            rt._delayed.append((time.time() + secs, tree_name, uid, signal))

        def continue_from(uid, out_sock, signal):
            # re-enter propagation from uid's output socket
            adapter = rt.adapters.get(tree_name)
            if adapter is None:
                return
            try:
                downstream = list(adapter.downstream(uid, out_sock))
            except ReferenceError:
                rt._record_error(tree_name, uid, "node tree was removed; please run again")
                return
            for tgt_uid, _ in downstream:
                eng.fire(tgt_uid, signal.child())

        def run_async(work, on_done, uid):
            def thread_body():
                try:
                    res = work()
                    rt._async_results.put((uid, tree_name, res, None, on_done))
                except Exception as e:  # noqa
                    rt._async_results.put((uid, tree_name, None, str(e), on_done))
            threading.Thread(target=thread_body, daemon=True).start()

        eng.schedule = schedule          # type: ignore[attr-defined]
        eng.continue_from = continue_from  # type: ignore[attr-defined]
        eng.run_async = run_async        # type: ignore[attr-defined]

    # ---- trigger discovery -------------------------------------------------
    def _iter_trigger_nodes(self):
        for tree in bpy.data.node_groups:
            if getattr(tree, "bl_idname", "") != "FxNodeTree":
                continue
            for node in tree.nodes:
                if hasattr(node, "event_source"):
                    yield tree, node

    def fire_node(self, tree, node, extra_context=None, msg=None):
        eng = self.get_engine(tree)
        adapter = self.adapters.get(tree.name)
        if adapter is not None:
            try:
                adapter.rebind(tree)
            except ReferenceError:
                # The tree passed by Blender is already invalid; report on the
                # node if possible and let the operator cancel gracefully.
                try:
                    node._error = "node tree was removed; please select the live tree and run again"
                except Exception:
                    pass
                raise
        sig = Signal(payload=dict(msg or {}), source=node.node_uid)
        return eng.fire(node.node_uid, sig, extra_context=extra_context)

    # ---- start / stop ------------------------------------------------------
    def start(self):
        if self.running or not _HAS_BPY:
            return
        self.running = True
        self._timer_last_fire.clear()
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
        self._timer_last_fire.clear()
        self._modal_running = False

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
        pass

    def _register_timer(self, interval):
        pass

    def _tag_redraw_ui(self):
        if not _HAS_BPY or not hasattr(bpy, "context") or not bpy.context:
            return
        try:
            wm = getattr(bpy.context, "window_manager", None)
            if wm:
                for window in wm.windows:
                    screen = getattr(window, "screen", None)
                    if screen:
                        for area in screen.areas:
                            if area.type in {'NODE_EDITOR', 'VIEW_3D', 'PROPERTIES'}:
                                area.tag_redraw()
        except Exception:
            pass

    def _install_main_tick(self):
        """Master dynamic clock: runs timer triggers in real-time, drains async results, and updates viewport live."""
        def housekeep():
            if not self.running:
                return None
            fired_any = False
            now = time.time()

            # 1. Dynamic real-time Timer Triggers (works even when UI/timeline is idle)
            for tree, node in self._iter_trigger_nodes():
                src = node.event_source()
                if src.get("kind") == "timer" and src.get("enabled", True):
                    interval = max(0.01, float(src.get("interval", 1.0)))
                    last = self._timer_last_fire.get(node.node_uid, 0.0)
                    if now - last >= interval:
                        self._timer_last_fire[node.node_uid] = now
                        self.fire_node(tree, node)
                        fired_any = True

            # 2. Async AI results
            drained = 0
            while not self._async_results.empty() and drained < 8:
                uid, tree_name, res, err, on_done = self._async_results.get()
                try:
                    on_done(res, err)
                    fired_any = True
                except Exception as e:
                    self._record_error(tree_name, uid, f"async callback failed: {type(e).__name__}: {e}")
                drained += 1

            # 3. Delayed continuations
            due = [d for d in self._delayed if d[0] <= now]
            for d in due:
                self._delayed.remove(d)
                _, tree_name, uid, sig = d
                tree = bpy.data.node_groups.get(tree_name)
                if tree:
                    eng = self.get_engine(tree)
                    if hasattr(eng, "continue_from"):
                        eng.continue_from(uid, "▶", sig)
                        fired_any = True

            # 4. Tag live UI & viewport redraw if any node fired
            if fired_any:
                self._tag_redraw_ui()

            return 0.02
        bpy.app.timers.register(housekeep, first_interval=0.02)
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
                bpy.ops.fx_nodes.input_listener('INVOKE_DEFAULT')
            except Exception:
                pass

    # ---- modal callback from operator -------------------------------------
    def handle_input_event(self, event):
        """Called by the input modal operator for each window event.
        
        Returns True if the event was consumed by a trigger with swallow=True,
        so the modal operator can return RUNNING_MODAL to block Blender's
        default behavior.
        """
        if not self.running:
            return False
        consumed = False
        # For key repeat blocking
        is_repeat = getattr(event, "is_repeat", False)
        # event.is_repeat is not always present in older Blender; fallback
        if not hasattr(event, "is_repeat"):
            is_repeat = (event.value == "PRESS" and getattr(event, "repeat", False))

        for tree, node in self._iter_trigger_nodes():
            src = node.event_source()
            kind = src.get("kind")
            if kind == "key":
                # Block repeats if node requests it
                if src.get("block_repeats", True) and is_repeat:
                    # Still swallow repeats if swallow is on, to fully block key
                    if (event.type == src.get("key")
                            and event.ctrl == src.get("ctrl", False)
                            and event.shift == src.get("shift", False)
                            and event.alt == src.get("alt", False)
                            and src.get("swallow", True)):
                        consumed = True
                    continue
                if (event.type == src.get("key") and event.value == src.get("value")
                        and event.ctrl == src.get("ctrl", False)
                        and event.shift == src.get("shift", False)
                        and event.alt == src.get("alt", False)):
                    # Node-RED style msg: put primary data in payload
                    msg = {
                        "payload": event.type,
                        "key": event.type,
                        "value": event.value,
                        "ctrl": event.ctrl,
                        "shift": event.shift,
                        "alt": event.alt,
                        "oskey": getattr(event, "oskey", False),
                        "type": event.type,
                    }
                    # Also enrich signal context via extra_context
                    extra = {
                        "event_type": event.type,
                        "event_value": event.value,
                    }
                    try:
                        self.fire_node(tree, node, msg=msg, extra_context=extra)
                    except ReferenceError:
                        # stale tree, ignore, will be cleaned on next start
                        pass
                    if src.get("swallow", True):
                        consumed = True
            elif kind == "click":
                if event.type == src.get("button") and event.value == "PRESS":
                    msg = {
                        "payload": {
                            "x": event.mouse_x,
                            "y": event.mouse_y,
                            "button": event.type,
                        },
                        "mouse_x": event.mouse_x,
                        "mouse_y": event.mouse_y,
                        "button": event.type,
                    }
                    if src.get("require_hit"):
                        obj = self._raycast(event)
                        if obj is None:
                            continue
                        # Store object name safely, not the RNA object itself
                        try:
                            msg["object"] = obj.name
                            msg["payload"]["object"] = obj.name
                        except Exception:
                            msg["object"] = str(obj)
                    try:
                        self.fire_node(tree, node, msg=msg)
                    except ReferenceError:
                        pass
                    if src.get("swallow", False):
                        consumed = True
        return consumed

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
RUNTIME = FxRuntime()
