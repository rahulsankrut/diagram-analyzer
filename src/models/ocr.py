"""OCR data models — bounding boxes, text elements, and OCR results."""

from typing import Any

from pydantic import BaseModel, Field, model_validator


class BoundingBox(BaseModel):
    """Axis-aligned bounding box with normalized (0.0–1.0) coordinates.

    All four coordinates must lie in [0.0, 1.0] and satisfy x_max > x_min
    and y_max > y_min.  Use :meth:`from_pixel_coords` to construct from pixel
    values, and :meth:`to_pixel_coords` to convert back.

    Attributes:
        x_min: Normalized left edge in [0.0, 1.0].
        y_min: Normalized top edge in [0.0, 1.0].
        x_max: Normalized right edge in [0.0, 1.0].
        y_max: Normalized bottom edge in [0.0, 1.0].
    """

    x_min: float = Field(ge=0.0, le=1.0)
    y_min: float = Field(ge=0.0, le=1.0)
    x_max: float = Field(ge=0.0, le=1.0)
    y_max: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_coordinate_order(self) -> "BoundingBox":
        """Ensure max coordinates are strictly greater than min coordinates."""
        if self.x_max <= self.x_min:
            raise ValueError(
                f"x_max ({self.x_max}) must be greater than x_min ({self.x_min})"
            )
        if self.y_max <= self.y_min:
            raise ValueError(
                f"y_max ({self.y_max}) must be greater than y_min ({self.y_min})"
            )
        return self

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_pixel_coords(
        cls,
        x_min: int,
        y_min: int,
        x_max: int,
        y_max: int,
        width: int,
        height: int,
    ) -> "BoundingBox":
        """Create a normalized BoundingBox from pixel coordinates.

        Args:
            x_min: Left edge in pixels.
            y_min: Top edge in pixels.
            x_max: Right edge in pixels.
            y_max: Bottom edge in pixels.
            width: Image width in pixels (denominator for x normalization).
            height: Image height in pixels (denominator for y normalization).

        Returns:
            BoundingBox with all coordinates in [0.0, 1.0].

        Raises:
            ValueError: If the resulting normalized coordinates are out of range
                or if width/height are non-positive.
        """
        if width <= 0 or height <= 0:
            raise ValueError(f"width and height must be positive, got {width}×{height}")
        return cls(
            x_min=x_min / width,
            y_min=y_min / height,
            x_max=x_max / width,
            y_max=y_max / height,
        )

    # ------------------------------------------------------------------
    # Conversions
    # ------------------------------------------------------------------

    def to_pixel_coords(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Convert normalized bbox to integer pixel coordinates.

        Args:
            width: Image width in pixels.
            height: Image height in pixels.

        Returns:
            Tuple of (x_min_px, y_min_px, x_max_px, y_max_px).
        """
        return (
            int(self.x_min * width),
            int(self.y_min * height),
            int(self.x_max * width),
            int(self.y_max * height),
        )

    def to_dict(self) -> dict[str, float]:
        """Return a plain dict with float values suitable for JSON serialization.

        Returns:
            Dict with keys ``x_min``, ``y_min``, ``x_max``, ``y_max``.
        """
        return {
            "x_min": self.x_min,
            "y_min": self.y_min,
            "x_max": self.x_max,
            "y_max": self.y_max,
        }

    # ------------------------------------------------------------------
    # Spatial queries
    # ------------------------------------------------------------------

    def center(self) -> tuple[float, float]:
        """Return the centroid of the bounding box.

        Returns:
            Tuple of (center_x, center_y) in normalized coordinates.
        """
        return ((self.x_min + self.x_max) / 2, (self.y_min + self.y_max) / 2)

    def area(self) -> float:
        """Return the normalized area of this bounding box.

        Returns:
            Non-negative float area in [0.0, 1.0].
        """
        return (self.x_max - self.x_min) * (self.y_max - self.y_min)

    def overlaps(self, other: "BoundingBox") -> bool:
        """Check whether this bbox overlaps with another.

        Boxes that share only an edge are *not* considered overlapping.

        Args:
            other: The other BoundingBox to compare against.

        Returns:
            True if the interiors of the two bboxes intersect.
        """
        return not (
            self.x_max <= other.x_min
            or other.x_max <= self.x_min
            or self.y_max <= other.y_min
            or other.y_max <= self.y_min
        )

    def iou(self, other: "BoundingBox") -> float:
        """Compute Intersection over Union with another bbox.

        Args:
            other: The other BoundingBox.

        Returns:
            IoU score in [0.0, 1.0].  Returns 0.0 when both boxes have zero area.
        """
        inter_x_min = max(self.x_min, other.x_min)
        inter_y_min = max(self.y_min, other.y_min)
        inter_x_max = min(self.x_max, other.x_max)
        inter_y_max = min(self.y_max, other.y_max)

        inter_area = max(0.0, inter_x_max - inter_x_min) * max(
            0.0, inter_y_max - inter_y_min
        )
        union_area = self.area() + other.area() - inter_area

        if union_area <= 0.0:
            return 0.0
        return inter_area / union_area


class OCRElement(BaseModel):
    """A single text element extracted by OCR.

    Attributes:
        text: The extracted text string.
        confidence: Model confidence score in [0.0, 1.0].
        bbox: Normalized bounding box of the text in the source image.
        page: Zero-indexed page number (for multi-page documents).
    """

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BoundingBox
    page: int = Field(default=0, ge=0)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation.

        Returns:
            Dict with all fields; ``bbox`` is expanded inline.
        """
        return self.model_dump(mode="json")


class OCRResult(BaseModel):
    """Aggregated OCR output for one diagram image.

    Attributes:
        elements: Filtered, deduplicated OCRElement list.
        raw_document_ai_response: Preserved raw API response for debugging.
    """

    elements: list[OCRElement] = Field(default_factory=list)
    raw_document_ai_response: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation.

        Returns:
            Dict containing the element list and raw response.
        """
        return self.model_dump(mode="json")
