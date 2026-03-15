"""Tests for src/tools/inspect_component.py."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from src.tools.inspect_component import inspect_component
from tests.test_tools.conftest import DIAGRAM_ID, COMP_A_ID, COMP_B_ID


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


def test_returns_diagram_id(mock_store: MagicMock) -> None:
    result = inspect_component(DIAGRAM_ID, COMP_A_ID)
    assert result["diagram_id"] == DIAGRAM_ID


def test_component_dict_present(mock_store: MagicMock) -> None:
    result = inspect_component(DIAGRAM_ID, COMP_A_ID)
    assert result["component"]["component_id"] == COMP_A_ID
    assert result["component"]["component_type"] == "resistor"
    assert result["component"]["value"] == "100Ω"


def test_crop_image_is_valid_png(mock_store: MagicMock) -> None:
    result = inspect_component(DIAGRAM_ID, COMP_A_ID)
    b64 = result["crop_image_base64"]
    assert b64 is not None
    decoded = base64.b64decode(b64)
    assert decoded[:4] == b"\x89PNG"


def test_crop_bbox_present(mock_store: MagicMock) -> None:
    result = inspect_component(DIAGRAM_ID, COMP_A_ID)
    bbox = result["crop_bbox"]
    assert bbox is not None
    for key in ("x_min", "y_min", "x_max", "y_max"):
        assert key in bbox


def test_crop_bbox_is_padded(mock_store: MagicMock) -> None:
    """Crop bbox should be larger than the original component bbox."""
    result = inspect_component(DIAGRAM_ID, COMP_A_ID)
    comp_bbox = result["component"]["bbox"]
    crop_bbox = result["crop_bbox"]
    assert crop_bbox["x_min"] <= comp_bbox["x_min"]
    assert crop_bbox["y_min"] <= comp_bbox["y_min"]
    assert crop_bbox["x_max"] >= comp_bbox["x_max"]
    assert crop_bbox["y_max"] >= comp_bbox["y_max"]


def test_nearby_components_list(mock_store: MagicMock) -> None:
    result = inspect_component(DIAGRAM_ID, COMP_A_ID)
    nearby = result["nearby_components"]
    assert isinstance(nearby, list)


def test_target_not_in_nearby(mock_store: MagicMock) -> None:
    """The component being inspected should not appear in nearby_components."""
    result = inspect_component(DIAGRAM_ID, COMP_A_ID)
    nearby_ids = [c["component_id"] for c in result["nearby_components"]]
    assert COMP_A_ID not in nearby_ids


def test_nearby_contains_close_component(mock_store: MagicMock) -> None:
    """comp_b centre (0.70, 0.31) is ~0.50 units from comp_a centre (0.20, 0.31).

    They are NOT within the 0.20 threshold, so nearby should be empty.
    (This test validates the distance threshold is respected.)
    """
    result = inspect_component(DIAGRAM_ID, COMP_A_ID)
    # Centres are ~0.50 apart, threshold is 0.20 — expect no nearby
    assert result["nearby_components"] == []


def test_nearby_finds_very_close_component(mock_store: MagicMock) -> None:
    """Inject a third component very close to comp_a and verify it appears."""
    from src.models.component import Component
    from src.models.ocr import BoundingBox

    close_comp = Component(
        component_id="comp-close",
        component_type="inductor",
        bbox=BoundingBox(x_min=0.25, y_min=0.25, x_max=0.35, y_max=0.37),
    )
    metadata = mock_store.get_metadata.return_value
    metadata.components.append(close_comp)

    result = inspect_component(DIAGRAM_ID, COMP_A_ID)
    nearby_ids = [c["component_id"] for c in result["nearby_components"]]
    assert "comp-close" in nearby_ids


# ---------------------------------------------------------------------------
# No original image available
# ---------------------------------------------------------------------------


def test_crop_null_when_no_original_image(store_no_image: MagicMock) -> None:
    result = inspect_component(DIAGRAM_ID, COMP_A_ID)
    assert result["crop_image_base64"] is None
    assert result["crop_bbox"] is None


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_error_diagram_not_found(store_unknown_diagram: MagicMock) -> None:
    result = inspect_component("bad-id", COMP_A_ID)
    assert "error" in result
    assert "bad-id" in result["error"]


def test_error_component_not_found(mock_store: MagicMock) -> None:
    result = inspect_component(DIAGRAM_ID, "nonexistent-comp")
    assert "error" in result
    assert "nonexistent-comp" in result["error"]
