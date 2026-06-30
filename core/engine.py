"""ExecutionEngine: pushes Signals through the reactive graph.

Design:
  * Push / event-driven (opposite of geometry nodes' pull model).
  * Breadth-first propagation along Flow links from a trigger node.
  * Per-tick memoization for pure data nodes.
  * Loop protection via per-propagation visited set + global hops cap.
  * Per-node error isolation: one node raising does not kill the graph.

The engine talks to the graph through a tiny abstraction (``GraphAdapter``)
so it can be unit-tested with a fake graph and reused with a real bpy
NodeTree. ``nodes/`` and ``ui/`` provide the bpy-backed adapter.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from .signal import Signal

MAX_HOPS = 512          # absolute ceiling against infinite loops
MAX_QUEUE = 100_000     # safety on fan-out explosions


class NodeLike(Protocol):
    """Minimal interface the engine needs from a node."""
    node_uid: str
    def process(self, signal: Signal, engine: "ExecutionEngine") -> List[Tuple[str, Signal]]:
        ...


class GraphAdapter(Protocol):
    """How the engine reaches into a node graph. Implemented for bpy + tests."""
    def get_node(self, uid: str) -> NodeLike: ...
    def downstream(self, uid: str, out_socket: str) -> Iterable[Tuple[str, str]]:
        """Yield (target_node_uid, target_in_socket) connected to (uid,out_socket)."""
        ...


class ExecutionEngine:
    def __init__(self, graph: GraphAdapter, *, context_provider: Optional[Callable[[], Dict[str, Any]]] = None):
        self.graph = graph
        self._context_provider = context_provider or (lambda: {})
        self.tick = 0
        self.running = False
        self._memo: Dict[Tuple[str, int], Any] = {}     # (node_uid, tick) -> cached output
        self.stats = EngineStats()
        self._on_event: List[Callable[[str, dict], None]] = []  # observers (UI)

    # -- observability ------------------------------------------------------
    def subscribe(self, cb: Callable[[str, dict], None]) -> None:
        self._on_event.append(cb)

    def _emit(self, kind: str, **data: Any) -> None:
        for cb in self._on_event:
            try:
                cb(kind, data)
            except Exception:
                pass

    # -- context ------------------------------------------------------------
    def make_context(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ctx = dict(self._context_provider())
        ctx.setdefault("tick", self.tick)
        if extra:
            ctx.update(extra)
        return ctx

    def next_tick(self) -> None:
        self.tick += 1
        self._memo.clear()

    # -- firing -------------------------------------------------------------
    def fire(self, start_uid: str, signal: Optional[Signal] = None,
             extra_context: Optional[Dict[str, Any]] = None) -> int:
        """Fire propagation from ``start_uid``. Returns nodes processed count."""
        self.next_tick()
        if signal is None:
            signal = Signal(context=self.make_context(extra_context), source=start_uid)
        else:
            signal.context = {**self.make_context(extra_context), **signal.context}
            signal.source = start_uid

        queue: deque[Tuple[str, Signal]] = deque()
        queue.append((start_uid, signal))
        visited_edges: set[Tuple[str, str, int]] = set()
        processed = 0
        t0 = time.perf_counter()

        while queue:
            if len(queue) > MAX_QUEUE:
                self._emit("error", node=start_uid, msg="队列溢出，可能存在指数级扇出")
                break
            uid, sig = queue.popleft()
            if sig.hops > MAX_HOPS:
                self._emit("loop_guard", node=uid, hops=sig.hops)
                continue
            node = self.graph.get_node(uid)
            if node is None:
                continue

            outputs = self._run_node(node, sig)
            processed += 1

            for out_socket, out_sig in outputs:
                for tgt_uid, tgt_in in self.graph.downstream(uid, out_socket):
                    edge_key = (uid + "/" + out_socket, tgt_uid + "/" + tgt_in, out_sig.sid % 100000)
                    if edge_key in visited_edges:
                        continue
                    visited_edges.add(edge_key)
                    queue.append((tgt_uid, out_sig.child()))

        dt = time.perf_counter() - t0
        self.stats.record_fire(processed, dt)
        self._emit("fired", start=start_uid, processed=processed, ms=dt * 1000.0)
        return processed

    def _run_node(self, node: NodeLike, signal: Signal) -> List[Tuple[str, Signal]]:
        try:
            result = node.process(signal, self) or []
            if hasattr(node, "_error"):
                node._error = ""
            self.stats.node_fired(node.node_uid)
            return list(result)
        except Exception as e:  # isolate
            msg = f"{type(e).__name__}: {e}"
            if hasattr(node, "_error"):
                node._error = msg
            self.stats.node_error(node.node_uid, msg)
            self._emit("error", node=node.node_uid, msg=msg)
            return []

    # -- memo for pure data nodes ------------------------------------------
    def memo_get(self, node_uid: str):
        return self._memo.get((node_uid, self.tick), _MISS)

    def memo_set(self, node_uid: str, value: Any) -> Any:
        self._memo[(node_uid, self.tick)] = value
        return value


class _Miss:
    __slots__ = ()


_MISS = _Miss()


class EngineStats:
    def __init__(self) -> None:
        self.fires = 0
        self.total_nodes = 0
        self.last_ms = 0.0
        self.avg_ms = 0.0
        self.per_node_fires: Dict[str, int] = {}
        self.errors: Dict[str, str] = {}

    def record_fire(self, processed: int, dt: float) -> None:
        self.fires += 1
        self.total_nodes += processed
        self.last_ms = dt * 1000.0
        self.avg_ms = self.avg_ms * 0.9 + self.last_ms * 0.1

    def node_fired(self, uid: str) -> None:
        self.per_node_fires[uid] = self.per_node_fires.get(uid, 0) + 1

    def node_error(self, uid: str, msg: str) -> None:
        self.errors[uid] = msg

    def as_dict(self) -> Dict[str, Any]:
        return {
            "fires": self.fires,
            "total_nodes": self.total_nodes,
            "last_ms": round(self.last_ms, 3),
            "avg_ms": round(self.avg_ms, 3),
            "errors": len(self.errors),
        }
