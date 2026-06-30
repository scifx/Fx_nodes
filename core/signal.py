"""Signal: the unit of propagation in the reactive engine.

A Signal is what flows along Flow connections. It carries a mutable ``payload``
(data that nodes read and enrich) and a read-only ``context`` (frame/time/event
environment). ``hops`` is a safety counter against runaway loops.

This module is pure-Python and dependency-free so it can be unit tested.
"""
from __future__ import annotations

import time
import itertools
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

_id_counter = itertools.count(1)


@dataclass
class Signal:
    payload: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None          # originating node bl identifier / name
    ts: float = field(default_factory=time.time)
    hops: int = 0
    sid: int = field(default_factory=lambda: next(_id_counter))

    def child(self, **payload_updates: Any) -> "Signal":
        """Create a downstream signal: shallow-copies payload, increments hops.

        Using a child keeps each branch independent so two downstream paths
        don't clobber each other's payload.
        """
        new_payload = dict(self.payload)
        new_payload.update(payload_updates)
        return Signal(
            payload=new_payload,
            context=self.context,        # context is shared/read-only
            source=self.source,
            ts=self.ts,
            hops=self.hops + 1,
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    def set(self, key: str, value: Any) -> "Signal":
        self.payload[key] = value
        return self

    def snapshot(self) -> Dict[str, Any]:
        """A JSON-ish snapshot for the data preview / inspector."""
        def safe(v: Any) -> Any:
            try:
                if isinstance(v, (int, float, str, bool)) or v is None:
                    return v
                if isinstance(v, (list, tuple)):
                    return [safe(x) for x in v][:32]
                if isinstance(v, dict):
                    return {str(k): safe(x) for k, x in list(v.items())[:32]}
                return f"{type(v).__name__}({v!r})"[:120]
            except Exception:
                return "<unrepr>"
        return {k: safe(v) for k, v in self.payload.items()}

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Signal(#{self.sid} src={self.source} hops={self.hops} payload={self.snapshot()})"
