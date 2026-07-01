"""AI nodes package; modules are auto-loaded from files."""
from .chat import AIChatNode, _inject_reference_context, _template
from .expression import AIExpressionNode
from .scene_script import AISceneCommandNode

__all__ = ["AIChatNode", "AIExpressionNode", "AISceneCommandNode", "_inject_reference_context", "_template"]
