"""Tool: inspect_zone — zoom into a rectangular region of the diagram.

Finds the most detailed tile(s) that cover the requested zone and returns
their images (annotated with Set-of-Marks numbered markers) alongside the
components and text labels within that region.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from src.models.ocr import BoundingBox
from src.models.tiling import Tile, TilePyramid
from src.tools._image_utils import (
    annotate_tile,
    bbox_to_pixel_dict,
    downscale_to_fit,
    image_to_base64,
)
from src.tools._store import DiagramStore, get_store

# Tile levels to try, most-detailed first.
_SEARCH_LEVELS = [2, 1, 0]
# Limits to keep context size under control
_MAX_TILE_PX = 512
_MAX_TEXT_LABELS = 50
_MAX_TILES = 3


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
    level whose tiles cover the requested region.  Tile images are annotated
    with Set-of-Marks numbered markers ([1], [2], …) so the agent can
    reference elements by marker number.

    Args:
        diagram_id: UUID of the diagram to inspect.
        x1: Left edge of the query region (0–100).
        y1: Top edge of the query region (0–100).
        x2: Right edge of the query region (0–100).
        y2: Bottom edge of the query region (0–100).

    Returns:
        Dict with ``diagram_id``, ``query_region``, ``tiles`` (annotated),
        ``markers`` (list of ``{id, type, text, bbox_px}``),
        ``component_count``, ``text_label_count``.
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
    query_bbox = BoundingBox(
        x_min=x1 / 100, y_min=y1 / 100, x_max=x2 / 100, y_max=y2 / 100,
    )

    w_px, h_px = metadata.width_px, metadata.height_px

    # --- Build SOM markers from components + labels in this zone ---
    components = metadata.components_in_bbox(query_bbox)
    all_labels = metadata.text_labels_in_bbox(query_bbox)
    shown_labels = all_labels[:_MAX_TEXT_LABELS]
    truncated_labels = len(all_labels) > _MAX_TEXT_LABELS

    markers = _build_markers(components, shown_labels, w_px, h_px)

    # --- Select tiles and annotate with SOM markers ---
    pyramid = store.get_pyramid(diagram_id)
    tiles_data = _build_tile_list(query_bbox, pyramid, store, markers)

    if not tiles_data:
        tiles_data = _fallback_crop(diagram_id, query_bbox, store, markers)

    # Compact marker list for the agent (no bbox objects)
    marker_refs = [
        {"id": m["id"], "type": m["type"], "text": m["text"], "bbox_px": m["bbox_px"]}
        for m in markers
    ]

    result: dict[str, Any] = {
        "diagram_id": diagram_id,
        "query_region": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        "tiles": tiles_data,
        "markers": marker_refs,
        "component_count": len(components),
        "text_label_count": len(all_labels),
    }
    if truncated_labels:
        result["text_labels_truncated"] = True
        result["text_labels_shown"] = _MAX_TEXT_LABELS
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_markers(
    components: list,
    labels: list,
    w_px: int,
    h_px: int,
) -> list[dict[str, Any]]:
    """Build SOM marker dicts from components and text labels."""
    markers: list[dict[str, Any]] = []
    marker_id = 1
    for comp in components:
        markers.append({
            "id": str(marker_id),
            "bbox": comp.bbox,
            "type": comp.component_type,
            "text": "",
            "bbox_px": bbox_to_pixel_dict(comp.bbox, w_px, h_px),
        })
        marker_id += 1
    for lbl in labels:
        markers.append({
            "id": str(marker_id),
            "bbox": lbl.bbox,
            "type": "text_label",
            "text": lbl.text,
            "bbox_px": bbox_to_pixel_dict(lbl.bbox, w_px, h_px),
        })
        marker_id += 1
    return markers


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
    markers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find the best pyramid tiles covering *query_bbox* and load their images."""
    if pyramid is None:
        return []
    for level in _SEARCH_LEVELS:
        matching: list[Tile] = [
            t for t in pyramid.tiles_at_level(level) if t.bbox.overlaps(query_bbox)
        ]
        if matching:
            return [_tile_to_dict(t, store, markers) for t in matching[:_MAX_TILES]]
    return []


def _tile_to_dict(
    tile: Tile,
    store: DiagramStore,
    markers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Serialize a tile to a dict with SOM-annotated base64-encoded image."""
    img: Image.Image | None = store.load_tile_image(tile)
    if img is not None:
        img = downscale_to_fit(img, _MAX_TILE_PX)
        img = annotate_tile(img, markers, tile.bbox)
    return {
        "tile_id": tile.tile_id,
        "level": tile.level,
        "row": tile.row,
        "col": tile.col,
        "bbox": tile.bbox.to_dict(),
        "image_base64": image_to_base64(img, fmt="JPEG") if img is not None else None,
    }


def _fallback_crop(
    diagram_id: str,
    query_bbox: BoundingBox,
    store: DiagramStore,
    markers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Crop the original image to *query_bbox* when no pyramid is available."""
    from src.tools._image_utils import crop_with_padding

    original = store.load_original_image(diagram_id)
    if original is None:
        return []
    crop, actual_bbox = crop_with_padding(original, query_bbox, padding=0.0)
    crop = downscale_to_fit(crop, _MAX_TILE_PX)
    crop = annotate_tile(crop, markers, actual_bbox)
    return [
        {
            "tile_id": f"{diagram_id}_zone_crop",
            "level": -1,
            "row": 0,
            "col": 0,
            "bbox": actual_bbox.to_dict(),
            "image_base64": image_to_base64(crop, fmt="JPEG"),
        }
    ]
