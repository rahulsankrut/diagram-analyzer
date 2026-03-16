"""Preprocessing orchestrator — ties OCR, CV, and title block extraction together.

:class:`PreprocessingPipeline` is the single entry point for Phase 2.  It
accepts a raw image (path or PIL Image), runs OCR and CV detection
concurrently, then extracts the title block from the OCR labels and assembles
a :class:`~src.models.DiagramMetadata` object ready for downstream stages.

Typical usage::

    client = DocumentAIClient(project_id=..., location=..., processor_id=...)
    extractor = DocumentAIOCRExtractor(client)
    pipeline = PreprocessingPipeline(ocr_extractor=extractor)
    metadata = await pipeline.run(Path("schematic.png"))
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from PIL import Image

from src.models import DetectedLine, DiagramMetadata, TextLabel, Trace
from src.models.component import Component
from src.preprocessing.cv_pipeline import CVPipeline
from src.preprocessing.ocr import DocumentAIOCRExtractor
from src.preprocessing.title_block import TitleBlockExtractor

if TYPE_CHECKING:
    from src.models import CVResult

logger = logging.getLogger(__name__)

# Mapping from file-extension → DiagramMetadata format literal
_FORMAT_BY_SUFFIX: dict[str, Literal["png", "tiff", "pdf", "dwg", "dxf"]] = {
    ".png": "png",
    ".tiff": "tiff",
    ".tif": "tiff",
    ".pdf": "pdf",
    ".dwg": "dwg",
    ".dxf": "dxf",
}


def _detect_format(
    image: Image.Image | Path,
) -> Literal["png", "tiff", "pdf", "dwg", "dxf"]:
    """Infer the diagram format from a file extension or PIL Image metadata.

    Args:
        image: Source image — a filesystem :class:`~pathlib.Path` or an
            in-memory :class:`~PIL.Image.Image`.

    Returns:
        One of ``"png"``, ``"tiff"``, ``"pdf"``, ``"dwg"``, ``"dxf"``.
        Defaults to ``"png"`` when the format cannot be determined.
    """
    if isinstance(image, Path):
        return _FORMAT_BY_SUFFIX.get(image.suffix.lower(), "png")
    pil_fmt = getattr(image, "format", None)
    if pil_fmt:
        return _FORMAT_BY_SUFFIX.get(f".{pil_fmt.lower()}", "png")
    return "png"


def _nearest_component(
    point: tuple[float, float],
    components: list[Component],
    padding: float = 0.02,
) -> Component | None:
    """Return the component whose bbox (with padding) contains *point*.

    Checks whether *point* lies within or near a component's bounding box.
    When multiple components are candidates, returns the one whose centre is
    closest to *point* (Euclidean distance).

    Args:
        point: Normalised (x, y) coordinate to check.
        components: Candidate components to test against.
        padding: Expansion applied to every edge of each component bbox before
            the containment test.  Defaults to 2% of image width/height —
            enough to catch Hough-line endpoints that slightly miss the visible
            component boundary.

    Returns:
        The best-matching :class:`~src.models.Component`, or ``None`` when no
        component's padded bbox contains *point*.
    """
    px, py = point
    best: Component | None = None
    best_dist = float("inf")
    for comp in components:
        b = comp.bbox
        if (
            b.x_min - padding <= px <= b.x_max + padding
            and b.y_min - padding <= py <= b.y_max + padding
        ):
            cx, cy = b.center()
            dist = (cx - px) ** 2 + (cy - py) ** 2
            if dist < best_dist:
                best_dist = dist
                best = comp
    return best


def _build_traces(
    lines: list[DetectedLine],
    components: list[Component],
    padding: float = 0.02,
) -> list[Trace]:
    """Build semantic Trace objects by matching line endpoints to component bboxes.

    For each detected Hough line, both endpoints are matched to the nearest
    component whose bounding box (expanded by *padding*) contains that point.
    When the start point maps to one component and the end point to a
    *different* component, a :class:`~src.models.Trace` is emitted.
    Duplicate component pairs (A→B when B→A already exists) are suppressed so
    the result has at most one edge per unordered component pair.

    Pin names are left empty because the CV pipeline does not resolve pin
    assignments — semantic pin inference is a later stage.  The ``path`` is
    the direct ``[start, end]`` line segment from the Hough detector.

    Args:
        lines: Detected line segments from the CV Hough pipeline.
        components: Extracted components whose bboxes serve as connection
            anchors.
        padding: Bbox expansion applied when matching endpoints to components.
            Defaults to 2% of image dimensions.

    Returns:
        List of :class:`~src.models.Trace` objects (may be empty when no
        lines connect two distinct components).
    """
    if not components or not lines:
        return []

    traces: list[Trace] = []
    seen_pairs: set[frozenset[str]] = set()

    for line in lines:
        start_comp = _nearest_component(line.start_point, components, padding)
        end_comp = _nearest_component(line.end_point, components, padding)

        if start_comp is None or end_comp is None:
            continue
        if start_comp.component_id == end_comp.component_id:
            continue

        pair: frozenset[str] = frozenset({start_comp.component_id, end_comp.component_id})
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        traces.append(
            Trace(
                from_component=start_comp.component_id,
                from_pin="",
                to_component=end_comp.component_id,
                to_pin="",
                path=[line.start_point, line.end_point],
            )
        )

    return traces


class PreprocessingPipeline:
    """Orchestrate OCR, CV detection, and title block extraction.

    The pipeline accepts injected collaborators so that tests can supply
    mocks for the OCR extractor and CV pipeline without touching the real
    Google Cloud or OpenCV APIs.

    Args:
        ocr_extractor: Configured :class:`~src.preprocessing.ocr.DocumentAIOCRExtractor`
            (or any compatible mock implementing ``async extract(image)``).
        cv_pipeline: Optional :class:`~src.preprocessing.cv_pipeline.CVPipeline`
            instance.  Defaults to a freshly constructed :class:`CVPipeline`
            when omitted.
    """

    def __init__(
        self,
        ocr_extractor: DocumentAIOCRExtractor,
        cv_pipeline: CVPipeline | None = None,
    ) -> None:
        self._ocr = ocr_extractor
        self._cv = cv_pipeline if cv_pipeline is not None else CVPipeline()
        self._title_block = TitleBlockExtractor()

    async def run(self, image: Image.Image | Path) -> DiagramMetadata:
        """Run the full preprocessing pipeline on a single diagram image.

        OCR and CV detection run concurrently via :func:`asyncio.gather`.
        Title block extraction is synchronous and runs after OCR completes.

        Args:
            image: The diagram as a filesystem :class:`~pathlib.Path` or an
                in-memory :class:`~PIL.Image.Image`.

        Returns:
            :class:`~src.models.DiagramMetadata` populated with
            ``text_labels`` (from OCR), ``components`` (from CV symbol
            detection), and ``title_block`` (from pattern matching).

        Raises:
            FileNotFoundError: If *image* is a :class:`~pathlib.Path` that
                does not exist on disk.
            Exception: Any exception raised by the OCR extractor is
                propagated unchanged so the caller can log and handle it.
        """
        if isinstance(image, Path):
            pil_image = Image.open(image).convert("RGB")
            source_filename = image.name
        else:
            pil_image = image.convert("RGB")
            source_filename = "<PIL Image>"

        fmt = _detect_format(image)
        width, height = pil_image.size

        # Run OCR first so its text bounding boxes can mask CV false positives.
        # Per Stürmer et al. (arXiv:2411.13929), masking text strokes before
        # Hough-line and contour detection is the primary way to reduce
        # false-positive symbols and spurious line segments on dense P&IDs.
        labels: list[TextLabel] = await self._ocr.extract(pil_image)

        # Run CV in a thread (blocking NumPy/OpenCV ops) with the OCR mask applied.
        cv_result: CVResult = await asyncio.to_thread(
            self._cv.run, pil_image, labels
        )

        title_block = self._title_block.extract(pil_image, labels)

        components = [
            Component(
                component_id=sym.symbol_id,
                component_type=sym.symbol_type,
                bbox=sym.bbox,
                confidence=sym.confidence,
            )
            for sym in cv_result.symbols
        ]

        # Build semantic traces by matching Hough line endpoints to components.
        # Lines whose endpoints fall within (or very near) two distinct component
        # bboxes produce a Trace — the first pass at connectivity resolution.
        traces = _build_traces(cv_result.detected_lines, components)

        connected = sum(
            1 for j in cv_result.junctions if j.junction_type.value == "connected"
        )
        crossings = sum(
            1 for j in cv_result.junctions if j.junction_type.value == "crossing"
        )
        logger.info(
            "Preprocessing complete — %d text labels, %d symbols, %d lines, "
            "%d junctions (%d connected, %d crossing), %d traces (source: %s)",
            len(labels),
            len(components),
            len(cv_result.detected_lines),
            len(cv_result.junctions),
            connected,
            crossings,
            len(traces),
            source_filename,
        )

        return DiagramMetadata(
            source_filename=source_filename,
            format=fmt,
            width_px=width,
            height_px=height,
            text_labels=labels,
            components=components,
            traces=traces,
            title_block=title_block,
            junctions=[j.to_dict() for j in cv_result.junctions],
        )
