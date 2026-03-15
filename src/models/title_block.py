"""Title block data model — structured drawing metadata from the title block."""

from typing import Any

from pydantic import BaseModel, Field

from src.models.ocr import BoundingBox


class TitleBlock(BaseModel):
    """Structured metadata extracted from a CAD drawing's title block.

    Title blocks appear at the border of engineering drawings and carry
    administrative information: drawing number, revision history, scale, etc.

    All fields default to empty strings because not every drawing standard
    (IEC, ANSI, ISO) includes the same fields; absent fields are left empty
    rather than None to simplify downstream string formatting.

    Attributes:
        drawing_id: Drawing number or document identifier (e.g. ``"DWG-001-A"``).
        title: Descriptive drawing title.
        sheet_number: Current sheet number, e.g. ``"1"`` or ``"1 of 3"``.
        sheet_total: Total sheet count, e.g. ``"3"``.
        revision: Revision letter or number (e.g. ``"B"``, ``"Rev 3"``).
        date: Date string in whatever format appears on the drawing (e.g.
            ``"2026-02-23"`` or ``"23/02/26"``).
        author: Name of the drafter or originating engineer.
        scale: Drawing scale annotation (e.g. ``"1:100"``, ``"NTS"``).
        zone_grid: Optional mapping of zone codes to descriptions extracted
            from a revision or zone table (e.g. ``{"A1": "Added motor M-201"}``).
        bbox: Normalized bounding box of the title block region in the diagram.
            ``None`` when the title block location was not detected.
    """

    drawing_id: str = ""
    title: str = ""
    sheet_number: str = "1"
    sheet_total: str = "1"
    revision: str = ""
    date: str = ""
    author: str = ""
    scale: str = ""
    zone_grid: dict[str, str] = Field(default_factory=dict)
    bbox: BoundingBox | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation.

        Returns:
            Dict with all title block fields.  ``bbox`` is ``None`` or an
            expanded coordinate dict.  ``zone_grid`` is a plain string→string
            mapping.
        """
        return self.model_dump(mode="json")
