"""Computer-vision data models — raw CV detection output.

These models represent the *geometric* output of the OpenCV pipeline before
semantic interpretation.  A :class:`Symbol` is a detected closed contour; a
:class:`DetectedLine` is a raw line segment from Hough-transform detection.
A :class:`Junction` is a classified line-intersection point: CONNECTED when
lines genuinely meet (T/L junction) or CROSSING when they pass through each
other without connecting (X-crossing).

Distinguishing CONNECTED from CROSSING junctions is critical for correct net
tracing — two pipes that cross on a P&ID at an X-crossing are NOT electrically
or fluidically connected (Stürmer et al. 2024, arXiv:2411.13929).

Semantic interpretation (Component, Trace) lives in the domain models.
"""

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.models.ocr import BoundingBox


class JunctionType(str, Enum):
    """Topology class of a line-intersection point.

    Attributes:
        CONNECTED: A T- or L-junction where lines genuinely meet and share a
            node.  The pipes/wires are electrically or fluidically connected.
        CROSSING: An X-junction where two lines pass through each other without
            connecting.  The pipes cross spatially but are NOT joined.
    """

    CONNECTED = "connected"
    CROSSING = "crossing"


class Junction(BaseModel):
    """A classified line-intersection point detected by the CV pipeline.

    Attributes:
        junction_id: Unique ID for this detection instance.
        bbox: Small bounding box centred on the intersection point (normalized).
        junction_type: Whether the lines genuinely meet (:attr:`JunctionType.CONNECTED`)
            or merely cross (:attr:`JunctionType.CROSSING`).
        confidence: Classification confidence in [0.0, 1.0].
    """

    junction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bbox: BoundingBox
    junction_type: JunctionType = JunctionType.CONNECTED
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return self.model_dump(mode="json")


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
        junctions: Classified intersection points between detected lines.
            Each junction is typed as CONNECTED (lines genuinely meet) or
            CROSSING (lines pass through without connecting).
    """

    symbols: list[Symbol] = Field(default_factory=list)
    detected_lines: list[DetectedLine] = Field(default_factory=list)
    junctions: list[Junction] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return self.model_dump(mode="json")
