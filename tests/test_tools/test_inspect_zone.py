"""Tests for src/tools/inspect_zone.py."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from src.tools.inspect_zone import inspect_zone
from tests.test_tools.conftest import DIAGRAM_ID, COMP_A_ID


# ---------------------------------------------------------------------------
# Happy-path: normal zone covering most of the diagram
# ---------------------------------------------------------------------------


def test_returns_diagram_id(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 0, 0, 100, 100)
    assert result["diagram_id"] == DIAGRAM_ID


def test_query_region_echoed(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 10, 20, 80, 70)
    assert result["query_region"] == {"x1": 10, "y1": 20, "x2": 80, "y2": 70}


def test_tiles_returned(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 0, 0, 100, 100)
    assert len(result["tiles"]) >= 1


def test_tile_has_required_keys(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 0, 0, 100, 100)
    tile = result["tiles"][0]
    for key in ("tile_id", "level", "row", "col", "bbox", "image_base64"):
        assert key in tile


def test_tile_image_is_valid_base64(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 0, 0, 100, 100)
    b64 = result["tiles"][0]["image_base64"]
    assert b64 is not None
    decoded = base64.b64decode(b64)
    assert decoded[:4] == b"\x89PNG"


def test_uses_most_detailed_level(mock_store: MagicMock) -> None:
    """Level-2 tile overlaps the query so level 2 should be selected."""
    result = inspect_zone(DIAGRAM_ID, 0, 0, 40, 40)
    assert any(t["level"] == 2 for t in result["tiles"])


def test_components_filtered_by_region(mock_store: MagicMock) -> None:
    # comp_a centre is at ~(0.20, 0.31), x1=0..30%, y1=0..50%
    result = inspect_zone(DIAGRAM_ID, 0, 0, 30, 50)
    comp_ids = [c["component_id"] for c in result["components"]]
    assert COMP_A_ID in comp_ids


def test_component_count_matches_list(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 0, 0, 100, 100)
    assert result["component_count"] == len(result["components"])


def test_text_label_count_matches_list(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 0, 0, 100, 100)
    assert result["text_label_count"] == len(result["text_labels"])


# ---------------------------------------------------------------------------
# Coordinate order normalization
# ---------------------------------------------------------------------------


def test_reversed_x_coords_normalized(mock_store: MagicMock) -> None:
    """x1 > x2 should be silently swapped."""
    result = inspect_zone(DIAGRAM_ID, 80, 0, 20, 100)
    assert result["query_region"]["x1"] < result["query_region"]["x2"]


def test_reversed_y_coords_normalized(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 0, 90, 100, 10)
    assert result["query_region"]["y1"] < result["query_region"]["y2"]


# ---------------------------------------------------------------------------
# Fallback: no pyramid → original image crop
# ---------------------------------------------------------------------------


def test_fallback_crop_when_no_pyramid(store_no_pyramid: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 0, 0, 50, 50)
    assert len(result["tiles"]) == 1
    tile = result["tiles"][0]
    assert tile["level"] == -1  # sentinel for "raw crop"
    assert tile["image_base64"] is not None


def test_empty_tiles_when_no_pyramid_and_no_image(store_no_image: MagicMock) -> None:
    store_no_image.get_pyramid.return_value = None
    result = inspect_zone(DIAGRAM_ID, 0, 0, 50, 50)
    assert result["tiles"] == []


# ---------------------------------------------------------------------------
# Diagram not found
# ---------------------------------------------------------------------------


def test_error_when_diagram_not_found(store_unknown_diagram: MagicMock) -> None:
    result = inspect_zone("bad-id", 0, 0, 100, 100)
    assert "error" in result


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_error_on_out_of_range_coord(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, -5, 0, 100, 100)
    assert "error" in result


def test_error_on_coord_above_100(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 0, 0, 150, 100)
    assert "error" in result


def test_error_on_zero_area_region(mock_store: MagicMock) -> None:
    result = inspect_zone(DIAGRAM_ID, 50, 0, 50, 100)
    assert "error" in result
