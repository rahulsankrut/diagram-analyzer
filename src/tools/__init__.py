"""Tools package — ADK-compatible tool functions callable by the LLM agent.

Each tool is a standalone function that accepts JSON-serializable arguments
and returns a JSON-serializable dict.  Register them with the ADK agent in
``src/agent/``.

Usage::

    from src.tools._store import configure_store
    from src.tools.get_overview import get_overview
    from src.tools.inspect_zone import inspect_zone
    from src.tools.inspect_component import inspect_component
    from src.tools.search_text import search_text
    from src.tools.trace_net import trace_net

    configure_store(my_store)  # call once at startup
"""

from src.tools.get_overview import get_overview
from src.tools.inspect_component import inspect_component
from src.tools.inspect_zone import inspect_zone
from src.tools.search_text import search_text
from src.tools.trace_net import trace_net

__all__ = [
    "get_overview",
    "inspect_zone",
    "inspect_component",
    "search_text",
    "trace_net",
]
