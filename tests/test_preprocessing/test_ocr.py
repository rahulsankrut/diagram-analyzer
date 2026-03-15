"""Tests for src/preprocessing/ocr.py — DocumentAIOCRExtractor.

All tests use a mock DocumentAIClient; the real Google Cloud API is never called.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from src.models import BoundingBox, TextLabel
from src.preprocessing.docai_client import DocumentAIClient
from src.preprocessing.ocr import (
    DocumentAIOCRExtractor,
    _bbox_from_normalized_vertices,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_QUAD_VERTICES = [
    {"x": 0.1, "y": 0.2},
    {"x": 0.3, "y": 0.2},
    {"x": 0.3, "y": 0.4},
    {"x": 0.1, "y": 0.4},
]


def _mock_client(response: dict) -> DocumentAIClient:
    """Build a DocumentAIClient mock that resolves to *response*."""
    client = MagicMock(spec=DocumentAIClient)
    client.process_image = AsyncMock(return_value=response)
    return client


def _token(
    start: int,
    end: int,
    vertices: list[dict],
    confidence: float = 0.95,
) -> dict:
    """Build a Document AI token dict."""
    return {
        "layout": {
            "text_anchor": {
                "text_segments": [
                    {"start_index": str(start), "end_index": str(end)}
                ]
            },
            "confidence": confidence,
            "bounding_poly": {"normalized_vertices": vertices},
        }
    }


def _response(full_text: str, tokens_per_page: list[list[dict]]) -> dict:
    """Build a minimal Document AI response dict."""
    pages = [
        {"page_number": i + 1, "tokens": tokens}
        for i, tokens in enumerate(tokens_per_page)
    ]
    return {"text": full_text, "pages": pages}


def _white_image(w: int = 200, h: int = 200) -> Image.Image:
    return Image.new("RGB", (w, h), color="white")


# ---------------------------------------------------------------------------
# Test: extracts text labels correctly from mock response
# ---------------------------------------------------------------------------


async def test_extracts_two_labels_text_and_confidence() -> None:
    """Extractor returns correctly populated TextLabel objects for each token."""
    full_text = "R1\nR2\n"
    tokens = [
        _token(0, 2, _QUAD_VERTICES, confidence=0.95),
        _token(
            3,
            5,
            [
                {"x": 0.6, "y": 0.2},
                {"x": 0.8, "y": 0.2},
                {"x": 0.8, "y": 0.4},
                {"x": 0.6, "y": 0.4},
            ],
            confidence=0.90,
        ),
    ]
    extractor = DocumentAIOCRExtractor(_mock_client(_response(full_text, [tokens])))
    labels = await extractor.extract(_white_image(800, 600))

    assert len(labels) == 2
    assert labels[0].text == "R1"
    assert labels[0].confidence == pytest.approx(0.95)
    assert labels[1].text == "R2"
    assert labels[1].confidence == pytest.approx(0.90)


async def test_extracts_labels_from_path(sample_electrical_image: Path) -> None:
    """Extractor accepts a filesystem Path and reads the image automatically."""
    full_text = "TEST\n"
    extractor = DocumentAIOCRExtractor(
        _mock_client(_response(full_text, [[_token(0, 4, _QUAD_VERTICES)]]))
    )
    labels = await extractor.extract(sample_electrical_image)

    assert len(labels) == 1
    assert labels[0].text == "TEST"


async def test_returns_text_label_instances() -> None:
    """Every item in the returned list is a TextLabel Pydantic model."""
    full_text = "X\n"
    extractor = DocumentAIOCRExtractor(
        _mock_client(_response(full_text, [[_token(0, 1, _QUAD_VERTICES)]]))
    )
    labels = await extractor.extract(_white_image())

    assert all(isinstance(lbl, TextLabel) for lbl in labels)


async def test_label_page_index_matches_page() -> None:
    """Labels from page 0 have page=0; labels from page 1 have page=1."""
    full_text = "A\nB\n"
    page1_verts = [
        {"x": 0.5, "y": 0.5},
        {"x": 0.7, "y": 0.5},
        {"x": 0.7, "y": 0.7},
        {"x": 0.5, "y": 0.7},
    ]
    extractor = DocumentAIOCRExtractor(
        _mock_client(
            _response(
                full_text,
                [[_token(0, 1, _QUAD_VERTICES)], [_token(2, 3, page1_verts)]],
            )
        )
    )
    labels = await extractor.extract(_white_image())

    assert labels[0].page == 0
    assert labels[1].page == 1


async def test_strips_whitespace_from_token_text() -> None:
    """Leading/trailing whitespace in a token's text slice is stripped."""
    full_text = " R1 \n"
    extractor = DocumentAIOCRExtractor(
        _mock_client(_response(full_text, [[_token(0, 5, _QUAD_VERTICES)]]))
    )
    labels = await extractor.extract(_white_image())

    assert labels[0].text == "R1"


# ---------------------------------------------------------------------------
# Test: converts normalized vertices to pixel coords
# ---------------------------------------------------------------------------


def test_bbox_from_normalized_vertices_basic() -> None:
    """Standard quad → correct min/max BoundingBox coordinates."""
    vertices = [
        {"x": 0.1, "y": 0.25},
        {"x": 0.5, "y": 0.25},
        {"x": 0.5, "y": 0.75},
        {"x": 0.1, "y": 0.75},
    ]
    bbox = _bbox_from_normalized_vertices(vertices)
    assert bbox is not None
    assert bbox.x_min == pytest.approx(0.1)
    assert bbox.y_min == pytest.approx(0.25)
    assert bbox.x_max == pytest.approx(0.5)
    assert bbox.y_max == pytest.approx(0.75)


def test_bbox_to_pixel_coords() -> None:
    """BoundingBox.to_pixel_coords produces correct integer pixel values."""
    vertices = [
        {"x": 0.1, "y": 0.2},
        {"x": 0.5, "y": 0.2},
        {"x": 0.5, "y": 0.8},
        {"x": 0.1, "y": 0.8},
    ]
    bbox = _bbox_from_normalized_vertices(vertices)
    assert bbox is not None
    assert bbox.to_pixel_coords(1000, 1000) == (100, 200, 500, 800)


def test_bbox_non_axis_aligned_quad() -> None:
    """Non-rectangular quad still produces a valid axis-aligned bbox."""
    vertices = [
        {"x": 0.2, "y": 0.1},
        {"x": 0.8, "y": 0.15},
        {"x": 0.75, "y": 0.9},
        {"x": 0.15, "y": 0.85},
    ]
    bbox = _bbox_from_normalized_vertices(vertices)
    assert bbox is not None
    assert bbox.x_min == pytest.approx(0.15)
    assert bbox.x_max == pytest.approx(0.8)
    assert bbox.y_min == pytest.approx(0.1)
    assert bbox.y_max == pytest.approx(0.9)


def test_bbox_from_normalized_vertices_empty_returns_none() -> None:
    """Empty vertex list returns None without raising."""
    assert _bbox_from_normalized_vertices([]) is None


def test_bbox_degenerate_point_returns_none() -> None:
    """Vertices that collapse to a single point (zero area) return None."""
    assert _bbox_from_normalized_vertices([{"x": 0.5, "y": 0.5}]) is None


def test_bbox_degenerate_horizontal_line_returns_none() -> None:
    """Vertices that form a horizontal line (zero height) return None."""
    vertices = [{"x": 0.1, "y": 0.5}, {"x": 0.9, "y": 0.5}]
    assert _bbox_from_normalized_vertices(vertices) is None


async def test_label_bbox_is_normalized() -> None:
    """All BoundingBox coordinates on returned labels are in [0, 1]."""
    full_text = "X\n"
    extractor = DocumentAIOCRExtractor(
        _mock_client(_response(full_text, [[_token(0, 1, _QUAD_VERTICES)]]))
    )
    labels = await extractor.extract(_white_image(1024, 768))

    bbox = labels[0].bbox
    assert 0.0 <= bbox.x_min <= 1.0
    assert 0.0 <= bbox.y_min <= 1.0
    assert 0.0 <= bbox.x_max <= 1.0
    assert 0.0 <= bbox.y_max <= 1.0
    assert bbox.x_max > bbox.x_min
    assert bbox.y_max > bbox.y_min


# ---------------------------------------------------------------------------
# Test: handles empty document response
# ---------------------------------------------------------------------------


async def test_empty_pages_list_returns_empty() -> None:
    """Returns empty list when Document AI reports no pages."""
    extractor = DocumentAIOCRExtractor(
        _mock_client({"text": "", "pages": []})
    )
    assert await extractor.extract(_white_image()) == []


async def test_missing_pages_key_returns_empty() -> None:
    """Returns empty list when the 'pages' key is absent from the response."""
    extractor = DocumentAIOCRExtractor(_mock_client({"text": "hello"}))
    assert await extractor.extract(_white_image()) == []


async def test_page_with_no_tokens_returns_empty() -> None:
    """Returns empty list when a page exists but has zero tokens."""
    response = {"text": "hello", "pages": [{"page_number": 1, "tokens": []}]}
    extractor = DocumentAIOCRExtractor(_mock_client(response))
    assert await extractor.extract(_white_image()) == []


async def test_token_with_empty_text_slice_is_skipped() -> None:
    """Tokens whose text_anchor resolves to only whitespace are silently skipped."""
    full_text = "   "
    # start=0, end=3 → slice is "   " → stripped = "" → skipped
    tokens = [_token(0, 3, _QUAD_VERTICES)]
    extractor = DocumentAIOCRExtractor(
        _mock_client(_response(full_text, [tokens]))
    )
    assert await extractor.extract(_white_image()) == []


async def test_token_without_text_anchor_is_skipped() -> None:
    """Tokens with no text_anchor are silently skipped."""
    token_no_anchor = {
        "layout": {
            "confidence": 0.9,
            "bounding_poly": {"normalized_vertices": _QUAD_VERTICES},
        }
    }
    response = {"text": "ABC", "pages": [{"page_number": 1, "tokens": [token_no_anchor]}]}
    extractor = DocumentAIOCRExtractor(_mock_client(response))
    assert await extractor.extract(_white_image()) == []


async def test_token_without_bounding_poly_is_skipped() -> None:
    """Tokens missing a bounding_poly are silently skipped."""
    full_text = "HI\n"
    token_no_poly = {
        "layout": {
            "text_anchor": {"text_segments": [{"start_index": "0", "end_index": "2"}]},
            "confidence": 0.9,
        }
    }
    response = {"text": full_text, "pages": [{"page_number": 1, "tokens": [token_no_poly]}]}
    extractor = DocumentAIOCRExtractor(_mock_client(response))
    assert await extractor.extract(_white_image()) == []


# ---------------------------------------------------------------------------
# Test: handles API error gracefully
# ---------------------------------------------------------------------------


async def test_propagates_google_api_error() -> None:
    """API error from DocumentAIClient is re-raised (not swallowed).

    We simulate a ``google.api_core.exceptions.ServiceUnavailable``-style error
    using a local subclass so the test doesn't require the GCP SDK to be
    installed in the test environment.
    """

    class _ServiceUnavailable(OSError):
        """Stand-in for google.api_core.exceptions.ServiceUnavailable."""

    client = MagicMock(spec=DocumentAIClient)
    client.process_image = AsyncMock(
        side_effect=_ServiceUnavailable("Document AI unavailable")
    )
    extractor = DocumentAIOCRExtractor(client)

    with pytest.raises(_ServiceUnavailable):
        await extractor.extract(_white_image())


async def test_propagates_generic_runtime_error() -> None:
    """Generic runtime errors from the client are propagated unchanged."""
    client = MagicMock(spec=DocumentAIClient)
    client.process_image = AsyncMock(side_effect=RuntimeError("connection timeout"))
    extractor = DocumentAIOCRExtractor(client)

    with pytest.raises(RuntimeError, match="connection timeout"):
        await extractor.extract(_white_image())


async def test_error_does_not_corrupt_state_on_retry() -> None:
    """After an API error, a subsequent call with a working client succeeds."""
    full_text = "OK\n"
    good_response = _response(full_text, [[_token(0, 2, _QUAD_VERTICES)]])

    failing_client = MagicMock(spec=DocumentAIClient)
    failing_client.process_image = AsyncMock(side_effect=RuntimeError("boom"))
    extractor_bad = DocumentAIOCRExtractor(failing_client)
    with pytest.raises(RuntimeError):
        await extractor_bad.extract(_white_image())

    # A fresh extractor with a good client still works correctly
    extractor_good = DocumentAIOCRExtractor(_mock_client(good_response))
    labels = await extractor_good.extract(_white_image())
    assert len(labels) == 1
    assert labels[0].text == "OK"
