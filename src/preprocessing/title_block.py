"""Title block extraction from CAD drawing OCR labels.

Identifies the standard title block region (bottom-right corner of the drawing),
filters OCR text labels into that region, and uses regex pattern matching to
populate a structured :class:`~src.models.TitleBlock` model.

Drawing standards covered: ANSI Y14.1, ISO 5457, IEC 61082.
"""

from __future__ import annotations

import logging
import re

from PIL import Image

from src.models import BoundingBox, TextLabel, TitleBlock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Region definition — normalized coordinates of the typical title block area
# ---------------------------------------------------------------------------

# Title blocks conventionally occupy the bottom-right corner of the sheet.
_REGION_X_MIN: float = 0.60   # right 40 % of the drawing
_REGION_Y_MIN: float = 0.75   # bottom 25 % of the drawing

# ---------------------------------------------------------------------------
# Inline patterns — self-contained labels that include both keyword and value
# ---------------------------------------------------------------------------

# "DWG: TEST-001", "DWG NO: DWG-001-A", "DRAWING NO: XYZ", "DOC: 2024-A"
_RE_DWG_INLINE = re.compile(
    r"(?:"
    r"DWG(?:\s+(?:NO|NUM(?:BER)?|#))?"           # DWG / DWG NO
    r"|DOC(?:UMENT)?(?:\s+(?:NO|NUM(?:BER)?|#))?" # DOC / DOCUMENT NO
    r"|DRG(?:\s+(?:NO|NUM(?:BER)?|#))?"           # DRG / DRG NO
    r"|DRAWING\s+(?:NO|NUM(?:BER)?|#)"            # DRAWING NO (explicit keyword required)
    r")[\s.:]+([A-Z0-9][A-Z0-9\-_./]{0,29})",
    re.IGNORECASE,
)

# "REV: A", "REV B", "REVISION: 3", "Rev. C"
_RE_REV_INLINE = re.compile(
    r"\bREV(?:ISION)?[.:\s]+([A-Z0-9]{1,5})\b",
    re.IGNORECASE,
)

# "SHEET 2 OF 5", "2/5", "2 OF 5", "SHT 1 OF 3", "1 OF 3"
_RE_SHEET = re.compile(
    r"(?:SH(?:EE)?T\s+)?(\d+)\s*(?:OF|/)\s*(\d+)",
    re.IGNORECASE,
)

# "2024-01-15", "15/01/2024", "01/15/24", "15-JAN-2024"
_RE_DATE = re.compile(
    r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}"       # YYYY-MM-DD
    r"|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"        # DD/MM/YY or MM/DD/YYYY
    r"|\d{1,2}-[A-Z]{3}-\d{2,4})\b",         # DD-MON-YYYY
    re.IGNORECASE,
)

# "1:100", "1 : 50", "NTS", "NOT TO SCALE"
_RE_SCALE = re.compile(
    r"\b(1\s*:\s*\d+|NTS|NOT\s+TO\s+SCALE)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Header patterns — labels that name a field and set context for the next label
# ---------------------------------------------------------------------------

# Each entry: (compiled_pattern, field_name)
# Patterns are anchored (^…$) and allow trailing colons/dots/spaces.
_HEADER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Drawing-number headers
    (re.compile(r"^DWG\s*(?:NO|NUM(?:BER)?|#)?\.?[\s.:]*$", re.IGNORECASE), "drawing_id"),
    (re.compile(r"^DRG\s*(?:NO|NUM(?:BER)?)?\.?[\s.:]*$", re.IGNORECASE), "drawing_id"),
    (re.compile(r"^DOC(?:UMENT)?\s*(?:NO|NUM(?:BER)?)?\.?[\s.:]*$", re.IGNORECASE), "drawing_id"),
    (re.compile(r"^DRAWING\s+(?:NO|NUMBER)[\s.:]*$", re.IGNORECASE), "drawing_id"),
    # Revision
    (re.compile(r"^REV(?:ISION)?\.?[\s.:]*$", re.IGNORECASE), "revision"),
    # Date
    (re.compile(r"^DATE[\s.:]*$", re.IGNORECASE), "date"),
    # Scale
    (re.compile(r"^SCALE[\s.:]*$", re.IGNORECASE), "scale"),
    # Title
    (re.compile(r"^(?:DRAWING\s+)?TITLE[\s.:]*$", re.IGNORECASE), "title"),
    (re.compile(r"^DESCRIPTION[\s.:]*$", re.IGNORECASE), "title"),
    # Author / drafter
    (re.compile(r"^DRAWN\s+BY[\s.:]*$", re.IGNORECASE), "author"),
    (re.compile(r"^(?:AUTHOR|DRAFTER|DESIGNER)[\s.:]*$", re.IGNORECASE), "author"),
    # Sheet
    (re.compile(r"^SH(?:EE)?T(?:\s+NO)?\.?[\s.:]*$", re.IGNORECASE), "sheet"),
]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _label_in_region(label: TextLabel) -> bool:
    """Return True if the label's centre falls within the title block region."""
    cx, cy = label.bbox.center()
    return cx >= _REGION_X_MIN and cy >= _REGION_Y_MIN


def _detect_header(text: str) -> str | None:
    """Return the field name if *text* is a standalone field header, else None."""
    for pattern, field in _HEADER_PATTERNS:
        if pattern.match(text):
            return field
    return None


def _apply_inline_patterns(text: str, tb: dict[str, str]) -> None:
    """Apply inline regex patterns and populate *tb* with any new matches.

    Already-populated fields are not overwritten (first match wins).
    """
    if "sheet_number" not in tb:
        m = _RE_SHEET.search(text)
        if m:
            tb["sheet_number"] = m.group(1)
            tb["sheet_total"] = m.group(2)

    if "date" not in tb:
        m = _RE_DATE.search(text)
        if m:
            tb["date"] = m.group(1)

    if "scale" not in tb:
        m = _RE_SCALE.search(text)
        if m:
            tb["scale"] = m.group(1)

    if "revision" not in tb:
        m = _RE_REV_INLINE.search(text)
        if m:
            tb["revision"] = m.group(1).upper()

    if "drawing_id" not in tb:
        m = _RE_DWG_INLINE.search(text)
        if m:
            tb["drawing_id"] = m.group(1).strip()


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class TitleBlockExtractor:
    """Extract structured title block metadata from a CAD diagram.

    Title blocks are the bordered information panel at the bottom-right corner
    of engineering drawings.  The extractor:

    1. Filters :class:`~src.models.TextLabel` objects to the expected region
       (right 40 %, bottom 25 % of the image).
    2. Applies inline regex patterns to self-contained labels
       (e.g. ``"REV: B"``, ``"1:100"``).
    3. Uses a header-context state machine for labels split across two tokens
       (e.g. ``"DRAWN BY:"`` followed by ``"J. Smith"``).

    Unrecognised fields are left at their :class:`~src.models.TitleBlock`
    default values (empty strings / ``"1"`` for sheet counts).
    """

    def extract(
        self,
        image: Image.Image,
        labels: list[TextLabel],
    ) -> TitleBlock:
        """Extract title block fields from OCR labels.

        Args:
            image: Full diagram PIL image (accepted for API consistency;
                the extractor uses normalised coordinates internally).
            labels: OCR text labels returned by
                :class:`~src.preprocessing.ocr.DocumentAIOCRExtractor`.

        Returns:
            :class:`~src.models.TitleBlock` populated with matched fields.
            The ``bbox`` is always set to the detected region rectangle.
            Unrecognised fields remain at their model defaults.
        """
        region_labels = [lbl for lbl in labels if _label_in_region(lbl)]
        region_labels.sort(key=lambda lbl: (lbl.bbox.y_min, lbl.bbox.x_min))
        logger.debug("Title block region contains %d labels", len(region_labels))

        tb: dict[str, str] = {}
        current_header: str | None = None

        for label in region_labels:
            text = label.text.strip()
            if not text:
                continue

            # Detect pure field headers FIRST — they carry no field value and
            # must not be fed to inline patterns (which might capture keyword
            # fragments like "NO" from "DWG NO:").
            header = _detect_header(text)
            if header is not None:
                current_header = header
                continue

            # Inline patterns run on all non-header labels (first match wins)
            _apply_inline_patterns(text, tb)

            # If following a header, try to capture this label as the value
            if current_header is not None:
                field = current_header
                current_header = None
                if field == "sheet":
                    # Inline already handled "1 OF 3"; only act if not yet set
                    if "sheet_number" not in tb:
                        m = _RE_SHEET.search(text)
                        if m:
                            tb["sheet_number"] = m.group(1)
                            tb["sheet_total"] = m.group(2)
                        else:
                            tb["sheet_number"] = text
                else:
                    tb.setdefault(field, text)

        title_block_bbox = BoundingBox(
            x_min=_REGION_X_MIN, y_min=_REGION_Y_MIN, x_max=1.0, y_max=1.0
        )
        return TitleBlock(
            drawing_id=tb.get("drawing_id", ""),
            title=tb.get("title", ""),
            sheet_number=tb.get("sheet_number", "1"),
            sheet_total=tb.get("sheet_total", "1"),
            revision=tb.get("revision", ""),
            date=tb.get("date", ""),
            author=tb.get("author", ""),
            scale=tb.get("scale", ""),
            bbox=title_block_bbox,
        )
