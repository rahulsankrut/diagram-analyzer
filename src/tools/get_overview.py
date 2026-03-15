"""Tool: get_overview — return the Level-0 overview tile and a diagram summary.

This is always the first tool the agent calls for a new diagram.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from PIL import Image

from src.models.tiling import TilePyramid
from src.tools._image_utils import downscale_to_fit, image_to_base64
from src.tools._store import DiagramStore, get_store


def get_overview(diagram_id: str) -> dict[str, Any]:
    """Return the Level-0 overview image and a high-level diagram summary.

    Always call this first for any new diagram.  It provides the full
    schematic downscaled to ~1024 px so the agent can orient itself, plus
    counts and type breakdowns for every extracted artefact.

    Args:
        diagram_id: UUID of the diagram to inspect.

    Returns:
        Dict with keys ``diagram_id``, ``image_base64`` (PNG base64),
        ``image_format``, ``width_px``, ``height_px``, ``component_count``,
        ``component_types`` (type→count dict), ``text_label_count``,
        ``trace_count``, ``title_block`` (dict or null).
        Contains ``error`` key instead when the diagram is not found.
    """
    store = get_store()
    metadata = store.get_metadata(diagram_id)
    if metadata is None:
        return {"error": f"Diagram not found: {diagram_id}"}

    image = _load_overview_image(diagram_id, store)
    image_b64 = image_to_base64(image) if image is not None else None

    type_counts: dict[str, int] = dict(
        Counter(c.component_type for c in metadata.components)
    )

    return {
        "diagram_id": diagram_id,
        "image_base64": image_b64,
        "image_format": "PNG",
        "width_px": metadata.width_px,
        "height_px": metadata.height_px,
        "component_count": len(metadata.components),
        "component_types": type_counts,
        "text_label_count": len(metadata.text_labels),
        "trace_count": len(metadata.traces),
        "title_block": metadata.title_block.to_dict() if metadata.title_block else None,
    }


def _load_overview_image(diagram_id: str, store: DiagramStore) -> Image.Image | None:
    """Load the Level-0 tile image, falling back to a downscaled original.

    Args:
        diagram_id: Diagram UUID.
        store: Active :class:`DiagramStore`.

    Returns:
        PIL Image for the overview, or ``None`` if no source is available.
    """
    pyramid: TilePyramid | None = store.get_pyramid(diagram_id)
    if pyramid is not None:
        l0_tiles = pyramid.tiles_at_level(0)
        if l0_tiles:
            img = store.load_tile_image(l0_tiles[0])
            if img is not None:
                return img

    original = store.load_original_image(diagram_id)
    if original is not None:
        return downscale_to_fit(original)

    return None
