"""Tool: inspect_zone — zoom into a rectangular region of the diagram.

Finds the most detailed tile(s) that cover the requested zone and returns
their images alongside the components and text labels within that region.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from src.models.ocr import BoundingBox
from src.models.tiling import Tile, TilePyramid
from src.tools._image_utils import image_to_base64
from src.tools._store import DiagramStore, get_store

# Tile levels to try, most-detailed first.
_SEARCH_LEVELS = [2, 1, 0]


def inspect_zone(
    diagram_id: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> dict[str, Any]:
    """Return tile images and content for a rectangular region of the diagram.

    Coordinates are expressed as percentages (0–100) of the diagram's width
    and height respectively.  The tool selects the most detailed pyramid
    level whose tiles cover the requested region.

    Args:
        diagram_id: UUID of the diagram to inspect.
        x1: Left edge of the query region (0–100).
        y1: Top edge of the query region (0–100).
        x2: Right edge of the query region (0–100).
        y2: Bottom edge of the query region (0–100).

    Returns:
        Dict with keys ``diagram_id``, ``query_region``, ``tiles`` (list of
        tile dicts each containing ``tile_id``, ``level``, ``row``, ``col``,
        ``bbox``, ``image_base64``), ``components`` (list), ``text_labels``
        (list), ``component_count``, ``text_label_count``.
        Contains ``error`` key instead when validation fails or diagram is
        not found.
    """
    validation_error = _validate_coords(x1, y1, x2, y2)
    if validation_error:
        return {"error": validation_error}

    store = get_store()
    metadata = store.get_metadata(diagram_id)
    if metadata is None:
        return {"error": f"Diagram not found: {diagram_id}"}

    # Swap coordinates if caller provided them in reversed order.
    x1, x2 = (x1, x2) if x1 < x2 else (x2, x1)
    y1, y2 = (y1, y2) if y1 < y2 else (y2, y1)
    query_bbox = BoundingBox(x_min=x1 / 100, y_min=y1 / 100, x_max=x2 / 100, y_max=y2 / 100)

    components = [c.to_dict() for c in metadata.components_in_bbox(query_bbox)]
    text_labels = [lbl.to_dict() for lbl in metadata.text_labels_in_bbox(query_bbox)]

    pyramid = store.get_pyramid(diagram_id)
    tiles_data = _build_tile_list(query_bbox, pyramid, store)

    if not tiles_data:
        tiles_data = _fallback_crop(diagram_id, query_bbox, store)

    return {
        "diagram_id": diagram_id,
        "query_region": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        "tiles": tiles_data,
        "components": components,
        "text_labels": text_labels,
        "component_count": len(components),
        "text_label_count": len(text_labels),
    }


def _validate_coords(x1: float, y1: float, x2: float, y2: float) -> str | None:
    """Return an error message if any coordinate is out of 0–100 range."""
    for name, val in (("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2)):
        if not (0.0 <= val <= 100.0):
            return f"{name} must be in 0–100, got {val}"
    if x1 == x2 or y1 == y2:
        return "Query region has zero area"
    return None


def _build_tile_list(
    query_bbox: BoundingBox,
    pyramid: TilePyramid | None,
    store: DiagramStore,
) -> list[dict[str, Any]]:
    """Find the best pyramid tiles covering *query_bbox* and load their images."""
    if pyramid is None:
        return []
    for level in _SEARCH_LEVELS:
        matching: list[Tile] = [
            t for t in pyramid.tiles_at_level(level) if t.bbox.overlaps(query_bbox)
        ]
        if matching:
            return [_tile_to_dict(t, store) for t in matching]
    return []


def _tile_to_dict(tile: Tile, store: DiagramStore) -> dict[str, Any]:
    """Serialize a tile to a dict, including its base64-encoded image."""
    img: Image.Image | None = store.load_tile_image(tile)
    return {
        "tile_id": tile.tile_id,
        "level": tile.level,
        "row": tile.row,
        "col": tile.col,
        "bbox": tile.bbox.to_dict(),
        "image_base64": image_to_base64(img) if img is not None else None,
    }


def _fallback_crop(
    diagram_id: str,
    query_bbox: BoundingBox,
    store: DiagramStore,
) -> list[dict[str, Any]]:
    """Crop the original image to *query_bbox* when no pyramid is available."""
    from src.tools._image_utils import crop_with_padding

    original = store.load_original_image(diagram_id)
    if original is None:
        return []
    crop, actual_bbox = crop_with_padding(original, query_bbox, padding=0.0)
    return [
        {
            "tile_id": f"{diagram_id}_zone_crop",
            "level": -1,
            "row": 0,
            "col": 0,
            "bbox": actual_bbox.to_dict(),
            "image_base64": image_to_base64(crop),
        }
    ]
