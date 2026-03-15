"""Tool: get_overview — return a high-level diagram summary.

This is always the first tool the agent calls for a new diagram.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from src.tools._store import get_store


def get_overview(diagram_id: str) -> dict[str, Any]:
    """Return a high-level diagram summary.

    Always call this first for any new diagram.  It provides counts and
    type breakdowns for every extracted artefact so the agent can orient
    itself.  The diagram image is already provided to the agent directly;
    this tool does not repeat it.

    Args:
        diagram_id: UUID of the diagram to inspect.

    Returns:
        Dict with keys ``diagram_id``, ``width_px``, ``height_px``,
        ``component_count``, ``component_types`` (type→count dict),
        ``text_label_count``, ``trace_count``, ``title_block`` (dict or null).
        Contains ``error`` key instead when the diagram is not found.
    """
    store = get_store()
    metadata = store.get_metadata(diagram_id)
    if metadata is None:
        return {"error": f"Diagram not found: {diagram_id}"}

    type_counts: dict[str, int] = dict(
        Counter(c.component_type for c in metadata.components)
    )

    return {
        "diagram_id": diagram_id,
        "width_px": metadata.width_px,
        "height_px": metadata.height_px,
        "component_count": len(metadata.components),
        "component_types": type_counts,
        "text_label_count": len(metadata.text_labels),
        "trace_count": len(metadata.traces),
        "title_block": metadata.title_block.to_dict() if metadata.title_block else None,
    }
