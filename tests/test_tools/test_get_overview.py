"""Tests for src/tools/get_overview.py."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from src.tools.get_overview import get_overview
from tests.test_tools.conftest import DIAGRAM_ID


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_returns_diagram_id(mock_store: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    assert result["diagram_id"] == DIAGRAM_ID


def test_returns_correct_dimensions(mock_store: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    assert result["width_px"] == 800
    assert result["height_px"] == 600


def test_component_count(mock_store: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    assert result["component_count"] == 2


def test_component_types_breakdown(mock_store: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    types = result["component_types"]
    assert types["resistor"] == 1
    assert types["capacitor"] == 1


def test_text_label_count(mock_store: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    assert result["text_label_count"] == 2


def test_trace_count(mock_store: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    assert result["trace_count"] == 1


def test_title_block_present(mock_store: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    assert result["title_block"] is not None
    assert result["title_block"]["drawing_id"] == "DWG-001"
    assert result["title_block"]["revision"] == "A"


def test_image_format_is_png(mock_store: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    assert result["image_format"] == "PNG"


def test_image_base64_is_valid(mock_store: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    b64 = result["image_base64"]
    assert b64 is not None
    decoded = base64.b64decode(b64)
    assert decoded[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# Pyramid fallback: use level-0 tile image from pyramid
# ---------------------------------------------------------------------------


def test_uses_level0_tile_when_pyramid_available(mock_store: MagicMock) -> None:
    """Should call load_tile_image with the level-0 tile."""
    get_overview(DIAGRAM_ID)
    mock_store.load_tile_image.assert_called_once()


# ---------------------------------------------------------------------------
# Fallback path: no pyramid → downscale original
# ---------------------------------------------------------------------------


def test_falls_back_to_original_when_no_pyramid(
    store_no_pyramid: MagicMock,
) -> None:
    result = get_overview(DIAGRAM_ID)
    assert result["image_base64"] is not None
    store_no_pyramid.load_original_image.assert_called_once_with(DIAGRAM_ID)


# ---------------------------------------------------------------------------
# No image at all → image_base64 is null
# ---------------------------------------------------------------------------


def test_image_base64_null_when_no_images(store_no_image: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    assert result["image_base64"] is None


# ---------------------------------------------------------------------------
# Diagram not found
# ---------------------------------------------------------------------------


def test_error_when_diagram_not_found(store_unknown_diagram: MagicMock) -> None:
    result = get_overview("nonexistent-id")
    assert "error" in result
    assert "nonexistent-id" in result["error"]


# ---------------------------------------------------------------------------
# Empty diagram (no components, no labels, no traces, no title block)
# ---------------------------------------------------------------------------


def test_empty_diagram(mock_store: MagicMock) -> None:
    from src.models.diagram import DiagramMetadata

    empty = DiagramMetadata(
        diagram_id=DIAGRAM_ID,
        source_filename="empty.png",
        format="png",
        width_px=100,
        height_px=100,
        title_block=None,
    )
    mock_store.get_metadata.return_value = empty

    result = get_overview(DIAGRAM_ID)
    assert result["component_count"] == 0
    assert result["component_types"] == {}
    assert result["text_label_count"] == 0
    assert result["trace_count"] == 0
    assert result["title_block"] is None
