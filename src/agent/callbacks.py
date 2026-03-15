"""ADK callback hooks for the CAD analysis agent.

Callbacks intercept tool calls before and after execution, enabling
validation, logging, and graceful error recovery without cluttering
the tool implementations themselves.

Also provides :class:`ToolCallTracker`, a lightweight singleton that
accumulates per-call metadata (name, args, duration, success) so the
server can surface tool-usage telemetry in the API response.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Tools that require a diagram_id argument.
_DIAGRAM_TOOLS = frozenset(
    {"get_overview", "inspect_zone", "inspect_component", "search_text", "trace_net"}
)


# ---------------------------------------------------------------------------
# Tool call recording
# ---------------------------------------------------------------------------


@dataclass
class ToolCallRecord:
    """Metadata for a single tool invocation."""

    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0
    duration_ms: float = 0.0
    success: bool = True
    error: str | None = None
    result_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        d = asdict(self)
        # Remove internal timestamp — not useful for the frontend.
        d.pop("start_time", None)
        return d


class ToolCallTracker:
    """Accumulates tool-call metadata across a single analysis run.

    Usage::

        tracker.reset()          # before agent run
        tracker.record_start()   # inside before_tool callback
        tracker.record_end()     # inside after_tool callback
        records = tracker.get_records()  # after agent run
    """

    def __init__(self) -> None:
        self._records: list[ToolCallRecord] = []
        self._pending: dict[str, ToolCallRecord] = {}

    def reset(self) -> None:
        """Clear all records for a new analysis run."""
        self._records.clear()
        self._pending.clear()

    def record_start(self, tool_name: str, args: dict[str, Any]) -> None:
        """Called from ``before_tool`` — stores start timestamp."""
        sanitized = _sanitize_args(tool_name, args)
        record = ToolCallRecord(
            tool_name=tool_name,
            args=sanitized,
            start_time=time.monotonic(),
        )
        self._pending[tool_name] = record

    def record_end(
        self,
        tool_name: str,
        *,
        success: bool = True,
        result_summary: str = "",
        error: str | None = None,
    ) -> None:
        """Called from ``after_tool`` — computes duration and finalises record."""
        record = self._pending.pop(tool_name, None)
        if record is None:
            # Fallback: tool wasn't tracked via record_start (shouldn't happen).
            record = ToolCallRecord(tool_name=tool_name)

        elapsed = time.monotonic() - record.start_time if record.start_time else 0
        record.duration_ms = round(elapsed * 1000, 1)
        record.success = success
        record.result_summary = result_summary
        record.error = error
        self._records.append(record)

    def get_records(self) -> list[dict[str, Any]]:
        """Return a JSON-serializable list of all recorded tool calls."""
        return [r.to_dict() for r in self._records]


# Module-level singleton — imported by cad_agent.py.
tracker = ToolCallTracker()


def _sanitize_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *args* safe for JSON serialization and display.

    Strips large or sensitive values (e.g. base64 image data) while keeping
    identifiers and small parameters.
    """
    safe: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 200:
            safe[k] = v[:80] + "…"
        else:
            safe[k] = v
    return safe


def _summarise_result(tool_name: str, response: dict[str, Any]) -> str:
    """Produce a human-friendly one-liner summarising the tool response."""
    if "error" in response:
        return f"Error: {str(response['error'])[:100]}"

    match tool_name:
        case "get_overview":
            comps = response.get("component_count", "?")
            labels = response.get("text_label_count", "?")
            return f"{comps} components, {labels} text labels"
        case "inspect_zone":
            tiles = len(response.get("tiles", []))
            comps = response.get("component_count", "?")
            labels = response.get("text_label_count", "?")
            return f"{tiles} tiles, {comps} components, {labels} labels"
        case "inspect_component":
            comp = response.get("component", {})
            ctype = comp.get("component_type", "?") if isinstance(comp, dict) else "?"
            nearby = len(response.get("nearby_components", []))
            return f"Type: {ctype}, {nearby} nearby"
        case "search_text":
            matches = response.get("match_count", "?")
            return f"{matches} matches found"
        case "trace_net":
            conns = response.get("connection_count", len(response.get("connections", [])))
            return f"{conns} connections found"
        case _:
            keys = list(response.keys())[:4]
            return f"Keys: {', '.join(keys)}"


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

    # Track tool call start for the activity timeline.
    tracker.record_start(tool_name, dict(args))

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
    has_error = "error" in tool_response

    # Finalise the tracker record with timing + summary.
    tracker.record_end(
        tool_name,
        success=not has_error,
        result_summary=_summarise_result(tool_name, tool_response),
        error=str(tool_response["error"]) if has_error else None,
    )

    if has_error:
        logger.warning("← tool %s error: %s", tool_name, tool_response["error"])
    else:
        logger.debug("← tool %s ok (keys=%s)", tool_name, list(tool_response.keys()))

    return None
