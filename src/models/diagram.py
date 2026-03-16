"""Diagram-level data models — aggregated content and ingestion request/result."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.models.component import Component
from src.models.ocr import BoundingBox
from src.models.text_label import TextLabel
from src.models.title_block import TitleBlock
from src.models.trace import Trace


class DiagramMetadata(BaseModel):
    """Complete structured representation of one analysed CAD diagram.

    Aggregates every extracted artefact — components, text labels, traces,
    and the title block — alongside provenance metadata (GCS URIs, timestamps).
    This is the primary document model persisted to Firestore and passed to
    the agent as structured context.

    Attributes:
        diagram_id: UUID string assigned at ingestion time.
        source_filename: Original filename as provided by the caller.
        format: Detected or declared file format.
        width_px: Width of the rasterized image in pixels.
        height_px: Height of the rasterized image in pixels.
        dpi: Dots-per-inch of the rasterized image.
        gcs_original_uri: GCS URI of the original uploaded file.
        gcs_raster_uri: GCS URI of the normalized rasterized PNG.
        firestore_doc_id: Firestore document ID (typically == diagram_id).
        created_at: UTC timestamp when this record was created.
        components: All detected and classified components.
        text_labels: All OCR-extracted text labels.
        traces: All resolved semantic connections between component pins.
        title_block: Structured drawing metadata from the title block, or
            ``None`` if no title block was found.
        junctions: Classified line-intersection points from the CV pipeline.
            Each entry has ``junction_type`` of ``"connected"`` (lines genuinely
            meet) or ``"crossing"`` (lines pass through without connecting).
            Crossings must NOT be interpreted as electrical/fluid connections.
    """

    diagram_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_filename: str
    format: Literal["png", "tiff", "pdf", "dwg", "dxf"]
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    dpi: int = Field(default=300, gt=0)
    gcs_original_uri: str = ""
    gcs_raster_uri: str = ""
    firestore_doc_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Aggregated content (populated after preprocessing pipeline)
    components: list[Component] = Field(default_factory=list)
    text_labels: list[TextLabel] = Field(default_factory=list)
    traces: list[Trace] = Field(default_factory=list)
    title_block: TitleBlock | None = None
    # Classified line-intersection points from CV pipeline.
    # Each dict has keys: junction_id, bbox, junction_type ("connected"|"crossing"),
    # confidence.  CROSSING junctions are pass-through — NOT electrical/fluid
    # connections even though they share a spatial point on the diagram.
    junctions: list[dict[str, Any]] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_component(self, component_id: str) -> Component | None:
        """Look up a component by its ID.

        Args:
            component_id: The ``component_id`` to search for.

        Returns:
            The matching :class:`Component`, or ``None`` if not found.
        """
        for comp in self.components:
            if comp.component_id == component_id:
                return comp
        return None

    def components_in_bbox(self, bbox: BoundingBox) -> list[Component]:
        """Return components whose centroid falls within the given bbox.

        Args:
            bbox: Query region in normalized (0.0–1.0) coordinates.

        Returns:
            List of components whose center point is inside ``bbox``.
        """
        result: list[Component] = []
        for comp in self.components:
            cx, cy = comp.bbox.center()
            if bbox.x_min <= cx <= bbox.x_max and bbox.y_min <= cy <= bbox.y_max:
                result.append(comp)
        return result

    def text_labels_in_bbox(self, bbox: BoundingBox) -> list[TextLabel]:
        """Return text labels whose centroid falls within the given bbox.

        Args:
            bbox: Query region in normalized (0.0–1.0) coordinates.

        Returns:
            List of text labels whose center point is inside ``bbox``.
        """
        result: list[TextLabel] = []
        for label in self.text_labels:
            cx, cy = label.bbox.center()
            if bbox.x_min <= cx <= bbox.x_max and bbox.y_min <= cy <= bbox.y_max:
                result.append(label)
        return result

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation of the full diagram.

        Returns:
            Dict with all fields; nested models and datetimes are serialized
            to JSON-compatible Python types.
        """
        return self.model_dump(mode="json")


class IngestionRequest(BaseModel):
    """Request payload to start a diagram ingestion + analysis job.

    Attributes:
        source_uri: GCS URI (``gs://…``) or local file path of the diagram.
        diagram_type: Semantic category of the diagram.
        requester_id: Opaque caller identifier for audit logging.
    """

    source_uri: str
    diagram_type: Literal["electrical", "pid", "mechanical", "unknown"] = "unknown"
    requester_id: str


class IngestionResult(BaseModel):
    """Result returned after completing the ingestion + analysis pipeline.

    Attributes:
        metadata: Persisted metadata for the processed diagram.
        success: True if all pipeline stages completed without error.
        error_message: Human-readable error detail when success is False.
    """

    metadata: DiagramMetadata
    success: bool
    error_message: str | None = None
