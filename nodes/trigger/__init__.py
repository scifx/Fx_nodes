"""Trigger nodes package; modules are auto-loaded from files."""
from .timer import TimerTriggerNode
from .frame import FrameTriggerNode
from .key import KeyTriggerNode
from .click import ClickTriggerNode
from .scene_event import SceneEventTriggerNode
from .start import StartTriggerNode
from .manual import ManualTriggerNode

__all__ = [
    "TimerTriggerNode", "FrameTriggerNode", "KeyTriggerNode", "ClickTriggerNode",
    "SceneEventTriggerNode", "StartTriggerNode", "ManualTriggerNode",
]
