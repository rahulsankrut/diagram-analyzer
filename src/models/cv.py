"""Computer-vision data models — raw CV detection output.

These models represent the *geometric* output of the OpenCV pipeline before
semantic interpretation.  A :class:`Symbol` is a detected closed contour; a
:class:`DetectedLine` is a raw line segment from Hough-transform detection.
Semantic interpretation (Component, Trace) lives in the domain models.
"""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from src.models.ocr import BoundingBox


class Symbol(BaseModel):
    """A raw closed-contour detection from the CV pipeline.

    Attributes:
        symbol_id: Unique ID for this detection instance.
        symbol_type: Best-guess type string (``"resistor"``, ``"valve"``,
            ``"junction"``, ``"unknown"``).
        bbox: Normalized bounding box of the detected contour.
        confidence: Detection/classification confidence in [0.0, 1.0].
        connections: IDs of other symbols connected via detected lines.
    """

    symbol_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol_type: str = "unknown"
    bbox: BoundingBox
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    connections: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return self.model_dump(mode="json")


class DetectedLine(BaseModel):
    """A raw line segment detected by the OpenCV Hough-transform pipeline.

    Unlike the semantic :class:`~src.models.trace.Trace`, a DetectedLine
    carries no information about which components it connects.  That
    association is resolved in the pre-processing pipeline and recorded as a
    :class:`~src.models.trace.Trace` in :class:`~src.models.diagram.DiagramMetadata`.

    Attributes:
        line_id: Unique ID for this line detection.
        start_point: Normalized (x, y) coordinate of the line's start point.
        end_point: Normalized (x, y) coordinate of the line's end point.
        waypoints: Intermediate normalized (x, y) coordinates for curved or
            segmented lines.
        thickness: Estimated line thickness in pixels (useful for filtering
            thin annotation lines from thick bus traces).
    """

    line_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    start_point: tuple[float, float]
    end_point: tuple[float, float]
    waypoints: list[tuple[float, float]] = Field(default_factory=list)
    thickness: float = Field(default=1.0, gt=0.0)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return self.model_dump(mode="json")


class CVResult(BaseModel):
    """Aggregated raw computer-vision output for one diagram image.

    This is the direct output of the OpenCV pipeline before semantic
    interpretation.  Higher-level models (:class:`~src.models.diagram.DiagramMetadata`)
    aggregate the interpreted results.

    Attributes:
        symbols: All detected closed-contour symbols.
        detected_lines: All detected line segments.
        junctions: Bounding boxes of detected T/X trace junctions.
    """

    symbols: list[Symbol] = Field(default_factory=list)
    detected_lines: list[DetectedLine] = Field(default_factory=list)
    junctions: list[BoundingBox] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return self.model_dump(mode="json")
