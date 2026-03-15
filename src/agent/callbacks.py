"""ADK callback hooks for the CAD analysis agent.

Callbacks intercept tool calls before and after execution, enabling
validation, logging, and graceful error recovery without cluttering
the tool implementations themselves.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Tools that require a diagram_id argument.
_DIAGRAM_TOOLS = frozenset(
    {"get_overview", "inspect_zone", "inspect_component", "search_text", "trace_net"}
)


def before_tool(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
) -> dict[str, Any] | None:
    """Validate tool arguments before the tool executes.

    Returns a dict to short-circuit the tool call (the dict becomes the tool
    result), or ``None`` to let the call proceed normally.

    Args:
        tool: The ADK tool object about to be called.
        args: Arguments the LLM is passing to the tool.
        tool_context: ADK callback context (carries session state, etc.).

    Returns:
        Error dict if validation fails, else ``None``.
    """
    tool_name = getattr(tool, "name", str(tool))

    if tool_name in _DIAGRAM_TOOLS:
        diagram_id = args.get("diagram_id", "")
        if not diagram_id or not isinstance(diagram_id, str):
            logger.warning("Tool %s called without a valid diagram_id", tool_name)
            return {"error": "diagram_id is required and must be a non-empty string."}

    logger.debug("→ tool %s args=%s", tool_name, list(args.keys()))
    return None


def after_tool(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
    tool_response: dict[str, Any],
) -> dict[str, Any] | None:
    """Log tool results and surface errors clearly to the agent.

    Returns ``None`` to leave the response unchanged, or a replacement dict
    to override what the agent sees.

    Args:
        tool: The ADK tool object that just executed.
        args: Arguments that were passed to the tool.
        tool_context: ADK callback context.
        tool_response: The dict returned by the tool function.

    Returns:
        ``None`` to pass through, or a replacement response dict.
    """
    tool_name = getattr(tool, "name", str(tool))

    if "error" in tool_response:
        logger.warning("← tool %s error: %s", tool_name, tool_response["error"])
    else:
        logger.debug("← tool %s ok (keys=%s)", tool_name, list(tool_response.keys()))

    return None
