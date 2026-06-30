"""Signal: a Node-RED-style message moving through the flow.

Fx Nodes now follows the Node-RED mental model inside Blender:

    control link == execution order
    Signal.msg   == the message object passed downstream

``msg`` is a plain dict.  By convention it contains ``payload`` and ``topic``,
but nodes may add any other keys.  When a flow branches, ``child()`` shallow
copies the msg so branches can evolve independently.
"""
from __future__ import annotations

import time
import itertools
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

_id_counter = itertools.count(1)


@dataclass
class Signal:
    # Kept as ``payload`` at dataclass level for backwards compatibility with
    # older engine/tests.  Public API is ``msg``.
    payload: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None
    ts: float = field(default_factory=time.time)
    hops: int = 0
    sid: int = field(default_factory=lambda: next(_id_counter))

    @property
    def msg(self) -> Dict[str, Any]:
        """The Node-RED-style message object."""
        return self.payload

    @property
    def attrs(self) -> Dict[str, Any]:
        """Compatibility alias from the temporary attribute-table model."""
        return self.msg

    def child(self, **msg_updates: Any) -> "Signal":
        """Create a downstream signal with a shallow-copied msg.

        Same-name keys intentionally overwrite earlier values.  This gives
        straightforward Node-RED sequential semantics: downstream nodes always
        see the latest value.
        """
        new_msg = dict(self.msg)
        new_msg.update(msg_updates)
        return Signal(
            payload=new_msg,
            context=self.context,
            source=self.source,
            ts=self.ts,
            hops=self.hops + 1,
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self.msg.get(key, default)

    def set(self, key: str, value: Any) -> "Signal":
        self.msg[key] = value
        return self

    @property
    def topic(self) -> Any:
        return self.msg.get("topic")

    @topic.setter
    def topic(self, value: Any) -> None:
        self.msg["topic"] = value

    @property
    def msg_payload(self) -> Any:
        return self.msg.get("payload")

    @msg_payload.setter
    def msg_payload(self, value: Any) -> None:
        self.msg["payload"] = value

    def delete(self, key: str) -> "Signal":
        self.msg.pop(key, None)
        return self

    def clear_msg(self) -> "Signal":
        self.msg.clear()
        return self

    # Backwards compatibility with previous attribute table naming.
    def clear_attrs(self) -> "Signal":
        return self.clear_msg()

    def snapshot(self) -> Dict[str, Any]:
        """A JSON-ish snapshot for Debug / inspector."""
        def safe(v: Any) -> Any:
            try:
                if isinstance(v, (int, float, str, bool)) or v is None:
                    return v
                if isinstance(v, (list, tuple)):
                    return [safe(x) for x in v][:64]
                if isinstance(v, dict):
                    return {str(k): safe(x) for k, x in list(v.items())[:64]}
                return f"{type(v).__name__}({v!r})"[:160]
            except Exception:
                return "<unrepr>"
        return {k: safe(v) for k, v in self.msg.items()}

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Signal(#{self.sid} src={self.source} hops={self.hops} msg={self.snapshot()})"
