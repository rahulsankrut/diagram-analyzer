"""Tool: search_text — search OCR text labels by content.

Performs a case-insensitive partial-match search over all text labels
extracted from a diagram and annotates each result with its pyramid tile.
"""

from __future__ import annotations

from typing import Any

from src.models.text_label import TextLabel
from src.models.tiling import TilePyramid
from src.tools._store import get_store

# Pyramid levels to search for tile annotation, most-detailed first.
_SEARCH_LEVELS = [2, 1, 0]


def search_text(diagram_id: str, query: str) -> dict[str, Any]:
    """Search OCR text labels for partial case-insensitive matches.

    Useful for locating a component by reference designator, finding a
    specific net name, or verifying that a particular annotation exists on
    the diagram.

    Args:
        diagram_id: UUID of the diagram to search.
        query: Substring to look for (case-insensitive).  Must be non-empty.

    Returns:
        Dict with keys ``diagram_id``, ``query``, ``matches`` (list of match
        dicts each containing ``label_id``, ``text``, ``bbox``, ``confidence``,
        ``tile_id``, ``tile_level``, ``tile_row``, ``tile_col``),
        ``match_count``.
        Contains ``error`` key instead when the query is empty or the diagram
        is not found.
    """
    if not query.strip():
        return {"error": "query must be a non-empty string"}

    store = get_store()
    metadata = store.get_metadata(diagram_id)
    if metadata is None:
        return {"error": f"Diagram not found: {diagram_id}"}

    needle = query.strip().lower()
    matches = [lbl for lbl in metadata.text_labels if needle in lbl.text.lower()]

    pyramid = store.get_pyramid(diagram_id)
    match_dicts = [_label_to_dict(lbl, pyramid) for lbl in matches]

    return {
        "diagram_id": diagram_id,
        "query": query,
        "matches": match_dicts,
        "match_count": len(match_dicts),
    }


def _label_to_dict(label: TextLabel, pyramid: TilePyramid | None) -> dict[str, Any]:
    """Serialize a text label with its best-matching tile annotation.

    Args:
        label: The matched text label.
        pyramid: Tile pyramid used to locate the tile; may be ``None``.

    Returns:
        Dict with label fields plus tile annotation keys.
    """
    tile_info = _find_label_tile(label.label_id, pyramid)
    return {
        "label_id": label.label_id,
        "text": label.text,
        "bbox": label.bbox.to_dict(),
        "confidence": label.confidence,
        "tile_id": tile_info.get("tile_id") if tile_info else None,
        "tile_level": tile_info.get("level") if tile_info else None,
        "tile_row": tile_info.get("row") if tile_info else None,
        "tile_col": tile_info.get("col") if tile_info else None,
    }


def _find_label_tile(
    label_id: str,
    pyramid: TilePyramid | None,
) -> dict[str, Any] | None:
    """Find the most detailed tile that contains *label_id*.

    Args:
        label_id: UUID of the text label to locate.
        pyramid: Tile pyramid to search; may be ``None``.

    Returns:
        Dict with ``tile_id``, ``level``, ``row``, ``col``, or ``None``.
    """
    if pyramid is None:
        return None
    for level in _SEARCH_LEVELS:
        for tile in pyramid.tiles_at_level(level):
            if label_id in tile.text_label_ids:
                return {
                    "tile_id": tile.tile_id,
                    "level": tile.level,
                    "row": tile.row,
                    "col": tile.col,
                }
    return None
