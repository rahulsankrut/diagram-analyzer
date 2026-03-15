"""Text label data model — OCR-extracted labels with confidence scores."""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from src.models.ocr import BoundingBox


class TextLabel(BaseModel):
    """A text annotation extracted from a CAD diagram via OCR.

    Distinct from :class:`~src.models.ocr.OCRElement` in that TextLabel is the
    *semantic* output of the pre-processing pipeline: it has been de-duplicated,
    filtered by confidence, and associated with the diagram coordinate space.

    Attributes:
        label_id: UUID string uniquely identifying this label instance.
        text: The extracted text content (whitespace-normalized).
        bbox: Normalized bounding box of the label in the diagram image.
        confidence: OCR confidence score in [0.0, 1.0].
        page: Zero-indexed source page (for multi-page PDFs).
    """

    label_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    bbox: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0)
    page: int = Field(default=0, ge=0)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation.

        Returns:
            Dict with all label fields; ``bbox`` is expanded inline.
        """
        return self.model_dump(mode="json")
