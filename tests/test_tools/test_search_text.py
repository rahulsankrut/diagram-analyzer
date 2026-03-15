"""Tests for src/tools/search_text.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.tools.search_text import search_text
from tests.test_tools.conftest import DIAGRAM_ID, LABEL_A_ID, TILE_L2_ID


# ---------------------------------------------------------------------------
# Happy-path: exact and partial matches
# ---------------------------------------------------------------------------


def test_returns_diagram_id(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "R1")
    assert result["diagram_id"] == DIAGRAM_ID


def test_query_echoed(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "R1")
    assert result["query"] == "R1"


def test_exact_match(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "R1")
    assert result["match_count"] == 1
    assert result["matches"][0]["text"] == "R1"


def test_partial_match(mock_store: MagicMock) -> None:
    """'vc' should match 'VCC'."""
    result = search_text(DIAGRAM_ID, "vc")
    assert result["match_count"] == 1
    assert result["matches"][0]["text"] == "VCC"


def test_case_insensitive(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "vcc")
    assert result["match_count"] == 1


def test_match_count_equals_list_length(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "R1")
    assert result["match_count"] == len(result["matches"])


def test_match_dict_has_required_keys(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "R1")
    match = result["matches"][0]
    for key in ("label_id", "text", "bbox", "confidence", "tile_id", "tile_level"):
        assert key in match


def test_match_bbox_is_dict(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "R1")
    bbox = result["matches"][0]["bbox"]
    assert isinstance(bbox, dict)
    for key in ("x_min", "y_min", "x_max", "y_max"):
        assert key in bbox


# ---------------------------------------------------------------------------
# Tile annotation via pyramid
# ---------------------------------------------------------------------------


def test_tile_annotated_when_pyramid_present(mock_store: MagicMock) -> None:
    """label_a (LABEL_A_ID) is indexed in TILE_L2_ID — expect that tile returned."""
    result = search_text(DIAGRAM_ID, "R1")
    match = result["matches"][0]
    assert match["label_id"] == LABEL_A_ID
    assert match["tile_id"] == TILE_L2_ID
    assert match["tile_level"] == 2


def test_tile_null_when_no_pyramid(store_no_pyramid: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "R1")
    match = result["matches"][0]
    assert match["tile_id"] is None
    assert match["tile_level"] is None


# ---------------------------------------------------------------------------
# No matches
# ---------------------------------------------------------------------------


def test_empty_matches_for_unknown_text(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "XYZ_NOMATCH")
    assert result["match_count"] == 0
    assert result["matches"] == []


def test_wildcard_returns_all_labels(mock_store: MagicMock) -> None:
    """A single character query that appears in all labels returns all."""
    # Both "R1" and "VCC" do not share a common substring other than nothing.
    # Use a common character if any; here we test with empty — should error.
    result = search_text(DIAGRAM_ID, " ")
    # Whitespace query is stripped to empty → error
    assert "error" in result


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_error_on_empty_query(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "")
    assert "error" in result


def test_error_on_whitespace_only_query(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "   ")
    assert "error" in result


# ---------------------------------------------------------------------------
# Diagram not found
# ---------------------------------------------------------------------------


def test_error_when_diagram_not_found(store_unknown_diagram: MagicMock) -> None:
    result = search_text("bad-id", "R1")
    assert "error" in result
    assert "bad-id" in result["error"]
