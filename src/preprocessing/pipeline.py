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

from src.models import DiagramMetadata, TextLabel
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
            ``text_labels`` (from OCR) and ``title_block`` (from pattern
            matching).  ``components`` and ``traces`` are empty lists pending
            the semantic-interpretation stage (Phase 3).

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

        # Run OCR (async) and CV (sync in a thread) concurrently
        labels: list[TextLabel]
        cv_result: CVResult
        labels, cv_result = await asyncio.gather(  # type: ignore[assignment]
            self._ocr.extract(pil_image),
            asyncio.to_thread(self._cv.run, pil_image),
        )

        title_block = self._title_block.extract(pil_image, labels)

        logger.info(
            "Preprocessing complete — %d text labels, %d symbols, %d lines "
            "(source: %s)",
            len(labels),
            len(cv_result.symbols),
            len(cv_result.detected_lines),
            source_filename,
        )

        return DiagramMetadata(
            source_filename=source_filename,
            format=fmt,
            width_px=width,
            height_px=height,
            text_labels=labels,
            title_block=title_block,
        )
