"""CAD diagram analysis agent wired with Google ADK.

Wraps five tool functions into an LlmAgent and exposes both an async
``analyze_async()`` and a sync ``analyze()`` interface.

ADK and google-genai are imported lazily so the module remains importable
(and testable) in environments where those SDKs are not installed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from io import BytesIO
from typing import Any, AsyncIterator, Iterable

from .prompts import AGENT_INSTRUCTION, GLOBAL_INSTRUCTION

# Backward-compatible alias used by existing tests.
SYSTEM_INSTRUCTION = AGENT_INSTRUCTION

_log = logging.getLogger(__name__)

# Retry settings for transient Gemini / Vertex AI failures (429, 503, etc.)
_MAX_RETRIES = 3
_INITIAL_BACKOFF_S = 2.0
_MAX_BACKOFF_S = 30.0

# ---------------------------------------------------------------------------
# Lazy ADK / genai imports
# ---------------------------------------------------------------------------

try:
    from google.adk.agents import LlmAgent as _LlmAgent
    from google.adk.runners import InMemoryRunner as _InMemoryRunner
    from google.genai import types as _genai_types

    _ADK_AVAILABLE = True
except ImportError:  # pragma: no cover
    _LlmAgent = None  # type: ignore[assignment,misc]
    _InMemoryRunner = None  # type: ignore[assignment,misc]
    _genai_types = None  # type: ignore[assignment]
    _ADK_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

import os as _os

DEFAULT_MODEL = _os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
# TOOL_MODEL is reserved for vision-heavy tool calls (e.g. inspect_component
# crop verification). Falls back to the agent model when not set.
TOOL_MODEL = _os.environ.get("TOOL_MODEL", DEFAULT_MODEL)

# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class CADAnalysisAgent:
    """Google ADK ``LlmAgent`` wired with all five CAD analysis tools.

    Args:
        model: Gemini model identifier forwarded to LlmAgent.
        _agent_cls: ``LlmAgent`` class (or mock) to instantiate.
        _runner_cls: ``InMemoryRunner`` class (or mock) to instantiate.
        _types_mod: ``google.genai.types`` module (or mock).

    Raises:
        RuntimeError: When ``google-adk`` is not installed.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        _agent_cls: Any = None,
        _runner_cls: Any = None,
        _types_mod: Any = None,
    ) -> None:
        agent_cls = _agent_cls or _LlmAgent
        if agent_cls is None:
            raise RuntimeError(
                "google-adk is not installed. "
                "Run: pip install 'google-cloud-aiplatform[adk,agent-engines]'"
            )

        self._runner_cls = _runner_cls or _InMemoryRunner
        self._types_mod = _types_mod or _genai_types

        from src.tools.get_overview import get_overview
        from src.tools.inspect_component import inspect_component
        from src.tools.inspect_zone import inspect_zone
        from src.tools.search_text import search_text
        from src.tools.trace_net import trace_net
        from .callbacks import after_tool, before_tool

        self._tools = [get_overview, inspect_zone, inspect_component, search_text, trace_net]

        self._agent = agent_cls(
            model=model,
            name="cad_analysis_agent",
            description=(
                "Analyzes complex CAD diagrams — electrical schematics, P&IDs, "
                "and mechanical drawings — using multi-resolution tiling and OCR."
            ),
            global_instruction=GLOBAL_INSTRUCTION,
            instruction=AGENT_INSTRUCTION,
            tools=self._tools,
            before_tool_callback=before_tool,
            after_tool_callback=after_tool,
        )

    # ------------------------------------------------------------------
    # Async interface (preferred)
    # ------------------------------------------------------------------

    async def analyze_async(
        self,
        diagram_id: str,
        query: str,
        *,
        user_id: str = "default-user",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Run the agent asynchronously and return analysis + tool-call metadata.

        Args:
            diagram_id: UUID of the pre-processed diagram to analyse.
            query: Natural-language question or task for the agent.
            user_id: Opaque caller identifier used by the ADK session service.
            session_id: Explicit session ID; a unique value is generated when
                ``None`` so each call starts a fresh conversation by default.

        Returns:
            Dict with ``text`` (final agent response) and ``tool_calls``
            (list of tool invocation records with name, args, duration, etc.).
        """
        from .callbacks import tracker

        sid = session_id or f"{diagram_id}-{uuid.uuid4().hex[:8]}"
        full_query = f"Diagram ID: {diagram_id}\n\n{query}"

        parts: list[Any] = [self._types_mod.Part(text=full_query)]

        # Attach the diagram image directly so Gemini can visually analyse it
        # in addition to the structured data returned by tools.
        image_part = _load_image_part(diagram_id, self._types_mod)
        if image_part is not None:
            parts.append(image_part)

        content = self._types_mod.Content(role="user", parts=parts)

        # Reset the tracker so we only capture tool calls from this run.
        tracker.reset()

        text = await _run_with_retry(
            runner_cls=self._runner_cls,
            agent=self._agent,
            user_id=user_id,
            session_id=sid,
            content=content,
        )

        return {
            "text": text,
            "tool_calls": tracker.get_records(),
        }

    # ------------------------------------------------------------------
    # Sync convenience wrapper
    # ------------------------------------------------------------------

    def analyze(
        self,
        diagram_id: str,
        query: str,
        *,
        user_id: str = "default-user",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Synchronous wrapper around :meth:`analyze_async`.

        Suitable for scripts and CLI use.  Must not be called from inside
        an already-running event loop (use ``analyze_async`` instead).

        Args:
            diagram_id: UUID of the pre-processed diagram to analyse.
            query: Natural-language question or task for the agent.
            user_id: Opaque caller identifier.
            session_id: Explicit session ID; auto-generated when ``None``.

        Returns:
            Dict with ``text`` (final agent response) and ``tool_calls``
            (list of tool invocation records).
        """
        return asyncio.run(
            self.analyze_async(
                diagram_id,
                query,
                user_id=user_id,
                session_id=session_id,
            )
        )

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------

    @property
    def tools(self) -> list[Any]:
        """Return the list of tool functions registered on this agent."""
        return list(self._tools)

    @property
    def system_instruction(self) -> str:
        """Return the agent instruction string."""
        return AGENT_INSTRUCTION


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _is_final_response(event: Any) -> bool:
    """Return True when *event* represents the agent's final text response."""
    checker = getattr(event, "is_final_response", None)
    return bool(checker and checker())


def _extract_text(event: Any) -> str:
    """Extract the text string from an ADK event's content parts."""
    content = getattr(event, "content", None)
    if content is None:
        return ""
    parts = getattr(content, "parts", None) or []
    texts = [p.text for p in parts if getattr(p, "text", None)]
    return texts[-1] if texts else ""


# ---------------------------------------------------------------------------
def _load_image_part(diagram_id: str, types_mod: Any) -> Any | None:
    """Return a ``Part`` with the diagram image as inline JPEG data.

    Downscales the original image to ≤768 px and encodes as JPEG to keep
    the base context token cost low (~40–80 KB vs ~400 KB for PNG at 1024 px).
    Returns ``None`` when the image is unavailable.

    Args:
        diagram_id: UUID of the diagram whose image should be loaded.
        types_mod: ``google.genai.types`` module (or mock).

    Returns:
        A ``types.Part`` with ``inline_data`` set, or ``None``.
    """
    try:
        from src.tools._store import get_store
        from src.tools._image_utils import downscale_to_fit

        image = get_store().load_original_image(diagram_id)
        if image is None:
            return None

        # 768 px JPEG keeps the overview small (~40–80 KB vs ~400 KB PNG at 1024 px)
        # which saves ~100–300 K tokens from the base context every turn.
        image = downscale_to_fit(image, max_px=768)
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=85)
        return types_mod.Part(
            inline_data=types_mod.Blob(
                mime_type="image/jpeg",
                data=buf.getvalue(),
            )
        )
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Retry logic with exponential backoff
# ---------------------------------------------------------------------------


async def _run_with_retry(
    runner_cls: Any,
    agent: Any,
    user_id: str,
    session_id: str,
    content: Any,
) -> str:
    """Run the ADK agent with exponential backoff on transient errors.

    Retries on common transient errors (HTTP 429, 503, connection resets)
    with exponential backoff: 2 s → 4 s → 8 s … capped at 30 s.

    Args:
        runner_cls: The runner class to instantiate (InMemoryRunner).
        agent: The configured LlmAgent.
        user_id: User identifier for the session.
        session_id: Session identifier.
        content: The Content object to send.

    Returns:
        Final text response from the agent.

    Raises:
        Exception: Re-raised after exhausting all retries.
    """
    backoff = _INITIAL_BACKOFF_S
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            runner = runner_cls(agent=agent)
            runner.auto_create_session = True
            # Use a unique session on each retry to avoid stale state.
            retry_sid = session_id if attempt == 0 else f"{session_id}-r{attempt}"

            last_text = ""
            async for event in runner.run_async(
                user_id=user_id,
                session_id=retry_sid,
                new_message=content,
            ):
                if _is_final_response(event):
                    text = _extract_text(event)
                    if text:
                        last_text = text
            return last_text

        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            err_str = str(exc).lower()
            is_transient = any(
                kw in err_str
                for kw in ("429", "503", "rate", "quota", "resource_exhausted", "unavailable")
            )
            if not is_transient or attempt >= _MAX_RETRIES:
                raise
            _log.warning(
                "Transient error (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1, _MAX_RETRIES, backoff, exc,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF_S)

    # Should not reach here but satisfies type checker.
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Legacy helper kept for backward compatibility with existing tests
# ---------------------------------------------------------------------------


def _collect_final_text(events: Iterable[Any]) -> str:
    """Extract the last agent text from a synchronous ADK event stream.

    Prefer :func:`_is_final_response` + :func:`_extract_text` for new code.
    """
    last_text = ""
    for event in events:
        if _is_final_response(event):
            text = _extract_text(event)
            if text:
                last_text = text
    return last_text
