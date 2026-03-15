"""Tests for src/preprocessing/title_block.py — TitleBlockExtractor.

All tests use mock TextLabel objects built from fabricated bounding boxes.
No real images or OCR API calls are made.
"""

from __future__ import annotations

from PIL import Image

from src.models import BoundingBox, TextLabel, TitleBlock
from src.preprocessing.title_block import (
    TitleBlockExtractor,
    _REGION_X_MIN,
    _REGION_Y_MIN,
    _apply_inline_patterns,
    _detect_header,
    _label_in_region,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_EXTRACTOR = TitleBlockExtractor()


def _label(
    text: str,
    cx: float = 0.80,
    cy: float = 0.85,
    *,
    page: int = 0,
) -> TextLabel:
    """Create a TextLabel centred at (cx, cy) with a narrow bounding box."""
    hw, hh = 0.05, 0.02  # half-width, half-height
    return TextLabel(
        text=text,
        bbox=BoundingBox(
            x_min=max(0.01, cx - hw),
            y_min=max(0.01, cy - hh),
            x_max=min(0.99, cx + hw),
            y_max=min(0.99, cy + hh),
        ),
        confidence=0.95,
        page=page,
    )


def _image(w: int = 800, h: int = 600) -> Image.Image:
    return Image.new("RGB", (w, h), color="white")


# ---------------------------------------------------------------------------
# Tests: region filtering (_label_in_region)
# ---------------------------------------------------------------------------


def test_label_inside_region_passes() -> None:
    """Label whose centre is inside the title block region passes the filter."""
    lbl = _label("X", cx=0.75, cy=0.85)
    assert _label_in_region(lbl) is True


def test_label_left_of_region_fails() -> None:
    """Label to the left of the x boundary is excluded."""
    lbl = _label("X", cx=0.30, cy=0.85)
    assert _label_in_region(lbl) is False


def test_label_above_region_fails() -> None:
    """Label above the y boundary is excluded."""
    lbl = _label("X", cx=0.80, cy=0.50)
    assert _label_in_region(lbl) is False


def test_labels_outside_region_ignored_by_extractor() -> None:
    """Labels with centres outside the title block region are silently ignored."""
    labels = [
        _label("DWG-001", cx=0.30, cy=0.50),  # body of drawing
        _label("R1", cx=0.10, cy=0.10),        # top-left corner
    ]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.drawing_id == ""


def test_labels_inside_region_are_processed() -> None:
    """At least one in-region label contributes to the TitleBlock."""
    labels = [_label("REV B", cx=0.75, cy=0.85)]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.revision == "B"


# ---------------------------------------------------------------------------
# Tests: _detect_header
# ---------------------------------------------------------------------------


def test_detect_header_dwg_no() -> None:
    assert _detect_header("DWG NO:") == "drawing_id"


def test_detect_header_dwg_no_no_colon() -> None:
    assert _detect_header("DWG NO") == "drawing_id"


def test_detect_header_revision() -> None:
    assert _detect_header("REV:") == "revision"


def test_detect_header_revision_full() -> None:
    assert _detect_header("REVISION:") == "revision"


def test_detect_header_date() -> None:
    assert _detect_header("DATE:") == "date"


def test_detect_header_scale() -> None:
    assert _detect_header("SCALE:") == "scale"


def test_detect_header_title() -> None:
    assert _detect_header("TITLE:") == "title"


def test_detect_header_drawing_title() -> None:
    assert _detect_header("DRAWING TITLE:") == "title"


def test_detect_header_drawn_by() -> None:
    assert _detect_header("DRAWN BY:") == "author"


def test_detect_header_sheet() -> None:
    assert _detect_header("SHEET:") == "sheet"


def test_detect_header_non_header_returns_none() -> None:
    assert _detect_header("DWG-001-A") is None


def test_detect_header_inline_label_returns_none() -> None:
    """A label containing both header and value is NOT a pure header."""
    assert _detect_header("DWG NO: DWG-001-A") is None


# ---------------------------------------------------------------------------
# Tests: _apply_inline_patterns
# ---------------------------------------------------------------------------


def test_inline_sheet_x_of_y() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("1 OF 3", tb)
    assert tb["sheet_number"] == "1"
    assert tb["sheet_total"] == "3"


def test_inline_sheet_slash() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("2/5", tb)
    assert tb["sheet_number"] == "2"
    assert tb["sheet_total"] == "5"


def test_inline_sheet_with_keyword() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("SHEET 3 OF 4", tb)
    assert tb["sheet_number"] == "3"
    assert tb["sheet_total"] == "4"


def test_inline_date_iso() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("2024-01-15", tb)
    assert tb["date"] == "2024-01-15"


def test_inline_date_slash() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("15/01/2024", tb)
    assert tb["date"] == "15/01/2024"


def test_inline_scale_ratio() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("1:100", tb)
    assert tb["scale"] == "1:100"


def test_inline_scale_nts() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("NTS", tb)
    assert tb["scale"] == "NTS"


def test_inline_revision_rev_letter() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("REV B", tb)
    assert tb["revision"] == "B"


def test_inline_revision_with_colon() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("REV: A", tb)
    assert tb["revision"] == "A"


def test_inline_drawing_id_dwg_colon() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("DWG: TEST-001", tb)
    assert tb["drawing_id"] == "TEST-001"


def test_inline_drawing_id_dwg_no() -> None:
    tb: dict[str, str] = {}
    _apply_inline_patterns("DWG NO: DWG-001-A", tb)
    assert tb["drawing_id"] == "DWG-001-A"


def test_inline_first_match_wins() -> None:
    """Once a field is populated, subsequent matches are ignored."""
    tb: dict[str, str] = {"scale": "1:50"}
    _apply_inline_patterns("1:100", tb)
    assert tb["scale"] == "1:50"  # not overwritten


# ---------------------------------------------------------------------------
# Tests: inline patterns via extractor
# ---------------------------------------------------------------------------


def test_extractor_sheet_inline() -> None:
    labels = [_label("1 OF 3")]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.sheet_number == "1"
    assert tb.sheet_total == "3"


def test_extractor_sheet_slash_format() -> None:
    labels = [_label("2/5")]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.sheet_number == "2"
    assert tb.sheet_total == "5"


def test_extractor_date_iso() -> None:
    labels = [_label("2024-01-15")]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.date == "2024-01-15"


def test_extractor_date_slash_format() -> None:
    labels = [_label("15/01/2024")]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.date == "15/01/2024"


def test_extractor_scale_ratio() -> None:
    labels = [_label("1:100")]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.scale == "1:100"


def test_extractor_scale_nts() -> None:
    labels = [_label("NTS")]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.scale == "NTS"


def test_extractor_revision_inline() -> None:
    labels = [_label("REV B")]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.revision == "B"


def test_extractor_drawing_id_inline() -> None:
    labels = [_label("DWG: TEST-001")]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.drawing_id == "TEST-001"


# ---------------------------------------------------------------------------
# Tests: header-based extraction via extractor
# ---------------------------------------------------------------------------


def test_header_drawing_id_bare_value() -> None:
    """'DWG NO:' header followed by a bare identifier captures drawing_id."""
    labels = [
        _label("DWG NO:", cy=0.80),
        _label("DWG-001-A", cy=0.83),
    ]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.drawing_id == "DWG-001-A"


def test_header_revision_single_letter() -> None:
    """'REV:' header followed by a single letter captures revision."""
    labels = [
        _label("REV:", cy=0.80),
        _label("C", cy=0.83),
    ]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.revision == "C"


def test_header_title_multiword() -> None:
    """'TITLE:' header followed by a description captures title."""
    labels = [
        _label("TITLE:", cy=0.78),
        _label("Main Power Distribution", cy=0.81),
    ]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.title == "Main Power Distribution"


def test_header_author_drawn_by() -> None:
    """'DRAWN BY:' header followed by a name captures author."""
    labels = [
        _label("DRAWN BY:", cy=0.80),
        _label("J. Smith", cy=0.83),
    ]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.author == "J. Smith"


def test_header_date_fallback() -> None:
    """'DATE:' header captures the next label as date when no inline match."""
    labels = [
        _label("DATE:", cy=0.80),
        _label("FEB 2026", cy=0.83),
    ]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.date == "FEB 2026"


# ---------------------------------------------------------------------------
# Tests: edge cases and defaults
# ---------------------------------------------------------------------------


def test_empty_labels_returns_model_defaults() -> None:
    """With no labels, TitleBlock uses its model-level default values."""
    tb = _EXTRACTOR.extract(_image(), [])
    assert tb.drawing_id == ""
    assert tb.revision == ""
    assert tb.sheet_number == "1"
    assert tb.sheet_total == "1"
    assert tb.title == ""
    assert tb.author == ""
    assert tb.scale == ""
    assert tb.date == ""


def test_bbox_always_set() -> None:
    """Returned TitleBlock.bbox is never None."""
    tb = _EXTRACTOR.extract(_image(), [])
    assert tb.bbox is not None


def test_bbox_covers_region() -> None:
    """The returned bbox matches the expected title block region bounds."""
    tb = _EXTRACTOR.extract(_image(), [])
    assert tb.bbox is not None
    assert tb.bbox.x_min == _REGION_X_MIN
    assert tb.bbox.y_min == _REGION_Y_MIN
    assert tb.bbox.x_max == 1.0
    assert tb.bbox.y_max == 1.0


def test_first_match_wins_scale() -> None:
    """When two labels both look like scales, only the first (by position) is kept."""
    labels = [
        _label("1:50", cy=0.78),
        _label("SCALE:", cy=0.83),
        _label("1:100", cy=0.86),
    ]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.scale == "1:50"


def test_first_match_wins_date() -> None:
    """When two labels both look like dates, only the first is kept."""
    labels = [
        _label("2024-01-15", cy=0.78),
        _label("2023-06-01", cy=0.82),
    ]
    tb = _EXTRACTOR.extract(_image(), labels)
    assert tb.date == "2024-01-15"


def test_returns_title_block_instance() -> None:
    """The return value is always a TitleBlock Pydantic model."""
    tb = _EXTRACTOR.extract(_image(), [])
    assert isinstance(tb, TitleBlock)


# ---------------------------------------------------------------------------
# Tests: realistic full title block
# ---------------------------------------------------------------------------


def test_full_title_block() -> None:
    """A realistic title block with inline and header-based labels is parsed fully."""
    labels = [
        # Title — two-token: header then value
        _label("TITLE:", cy=0.76),
        _label("Main Power Distribution", cy=0.79),
        # Drawing number — inline
        _label("DWG NO: DWG-001-A", cy=0.82, cx=0.70),
        # Revision — inline
        _label("REV: B", cy=0.82, cx=0.90),
        # Sheet — inline
        _label("1 OF 3", cy=0.85, cx=0.70),
        # Date — inline
        _label("2024-01-15", cy=0.85, cx=0.90),
        # Scale — inline
        _label("1:100", cy=0.88, cx=0.70),
        # Author — two-token: header then value
        _label("DRAWN BY:", cy=0.88, cx=0.90),
        _label("J. Smith", cy=0.91, cx=0.90),
    ]
    tb = _EXTRACTOR.extract(_image(), labels)

    assert tb.drawing_id == "DWG-001-A"
    assert tb.revision == "B"
    assert tb.sheet_number == "1"
    assert tb.sheet_total == "3"
    assert tb.date == "2024-01-15"
    assert tb.scale == "1:100"
    assert tb.author == "J. Smith"
    assert tb.title == "Main Power Distribution"
    assert tb.bbox is not None
