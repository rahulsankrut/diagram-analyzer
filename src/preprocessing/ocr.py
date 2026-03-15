"""OCR extraction using Google Cloud Document AI.

Provides :class:`DocumentAIOCRExtractor`, which accepts a PIL image (or a
path to one), calls Document AI via :class:`~src.preprocessing.docai_client.DocumentAIClient`,
converts the normalized-vertex bounding polygons to axis-aligned
:class:`~src.models.BoundingBox` objects, and returns a list of
:class:`~src.models.TextLabel` objects ready for downstream use.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

from PIL import Image

from src.models import BoundingBox, TextLabel
from src.preprocessing.docai_client import DocumentAIClient

logger = logging.getLogger(__name__)


class DocumentAIOCRExtractor:
    """Extract text labels from a CAD diagram image via Google Document AI.

    The extractor is decoupled from the Document AI SDK through the
    :class:`~src.preprocessing.docai_client.DocumentAIClient` interface,
    making it straightforward to inject a mock client in tests.

    Args:
        client: A :class:`~src.preprocessing.docai_client.DocumentAIClient`
            instance (or any compatible mock that implements
            ``async process_image(bytes) -> dict``).
    """

    def __init__(self, client: DocumentAIClient) -> None:
        self._client = client

    async def extract(self, image: Image.Image | Path) -> list[TextLabel]:
        """Run OCR on *image* and return structured text labels.

        Args:
            image: A PIL ``Image`` object or a filesystem ``Path`` to a
                PNG / JPEG / TIFF file.

        Returns:
            List of :class:`~src.models.TextLabel` with normalized bounding
            boxes and confidence scores.  Returns an empty list when the
            Document AI response contains no text or pages.

        Raises:
            FileNotFoundError: If *image* is a ``Path`` that does not exist.
            google.api_core.exceptions.GoogleAPICallError: Propagated on API
                failure (callers should handle and log accordingly).
        """
        pil_image, image_bytes = _load_image(image)
        width, height = pil_image.size

        try:
            response = await self._client.process_image(image_bytes)
        except Exception:
            logger.error(
                "Document AI API call failed for image %s",
                image if isinstance(image, Path) else "<PIL Image>",
            )
            raise

        return _parse_response(response, width, height)


# ---------------------------------------------------------------------------
# Module-level helpers (also exported for unit testing)
# ---------------------------------------------------------------------------


def _load_image(image: Image.Image | Path) -> tuple[Image.Image, bytes]:
    """Open (if needed) the image and encode it as PNG bytes.

    Args:
        image: PIL ``Image`` or filesystem ``Path``.

    Returns:
        Tuple of ``(PIL Image, PNG-encoded bytes)``.

    Raises:
        FileNotFoundError: If *image* is a ``Path`` that does not exist.
    """
    if isinstance(image, Path):
        pil_image = Image.open(image).convert("RGB")
    else:
        pil_image = image.convert("RGB")

    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return pil_image, buf.getvalue()


def _parse_response(
    response: dict[str, Any],
    width: int,
    height: int,
) -> list[TextLabel]:
    """Convert a raw Document AI response dict to :class:`~src.models.TextLabel` objects.

    Iterates over every token on every page.  For each token, extracts the
    text string via the ``text_anchor`` offsets into the document-level
    ``text`` field, then converts the ``bounding_poly.normalized_vertices``
    to an axis-aligned :class:`~src.models.BoundingBox`.

    Args:
        response: Plain dict returned by
            :meth:`~src.preprocessing.docai_client.DocumentAIClient.process_image`.
        width: Image width in pixels (retained for future pixel-coord use).
        height: Image height in pixels.

    Returns:
        List of :class:`~src.models.TextLabel` objects.
    """
    full_text: str = response.get("text", "")
    pages: list[dict[str, Any]] = response.get("pages", [])

    if not pages:
        logger.debug("Document AI returned no pages; result is empty")
        return []

    labels: list[TextLabel] = []
    for page_index, page in enumerate(pages):
        for token in page.get("tokens", []):
            label = _token_to_text_label(token, full_text, page_index)
            if label is not None:
                labels.append(label)

    logger.debug("Extracted %d text labels from Document AI response", len(labels))
    return labels


def _token_to_text_label(
    token: dict[str, Any],
    full_text: str,
    page_index: int,
) -> TextLabel | None:
    """Convert a single Document AI token dict to a :class:`~src.models.TextLabel`.

    Args:
        token: Token entry from ``pages[i].tokens``.
        full_text: Full document text string (from the ``"text"`` root key).
        page_index: Zero-indexed page number.

    Returns:
        :class:`~src.models.TextLabel`, or ``None`` when required fields are
        absent, the text is empty, or the bounding box is degenerate.
    """
    layout = token.get("layout", {})

    # Extract text via text_anchor offsets into the document-level text string
    text_anchor = layout.get("text_anchor", {})
    segments = text_anchor.get("text_segments", [])
    if not segments:
        return None

    seg = segments[0]
    start = int(seg.get("start_index", 0) or 0)
    end = int(seg.get("end_index", 0) or 0)
    text = full_text[start:end].strip()
    if not text:
        return None

    confidence: float = float(layout.get("confidence", 1.0))

    # Build BoundingBox from normalized polygon vertices
    bounding_poly = layout.get("bounding_poly", {})
    vertices: list[dict[str, float]] = bounding_poly.get("normalized_vertices", [])
    bbox = _bbox_from_normalized_vertices(vertices)
    if bbox is None:
        return None

    return TextLabel(
        text=text,
        bbox=bbox,
        confidence=confidence,
        page=page_index,
    )


def _bbox_from_normalized_vertices(
    vertices: list[dict[str, float]],
) -> BoundingBox | None:
    """Build an axis-aligned :class:`~src.models.BoundingBox` from Document AI vertices.

    Document AI returns bounding polygons as four corner vertices
    (clockwise from top-left) in normalized image coordinates (0.0–1.0).
    This function takes the min/max of all vertex coordinates to produce
    a standard axis-aligned bounding box, so non-rectangular quads are
    handled correctly.

    Args:
        vertices: List of ``{"x": float, "y": float}`` dicts from the API
            response.  Typically four entries; fewer or more are tolerated.

    Returns:
        :class:`~src.models.BoundingBox`, or ``None`` if the list is empty,
        has too few distinct points to form a box, or results in a
        zero-area (degenerate) rectangle.
    """
    if not vertices:
        return None

    xs = [float(v.get("x", 0.0)) for v in vertices]
    ys = [float(v.get("y", 0.0)) for v in vertices]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    # Degenerate box: zero width or height
    if x_max <= x_min or y_max <= y_min:
        return None

    # Clamp to [0, 1] to absorb minor floating-point noise
    x_min = max(0.0, min(1.0, x_min))
    y_min = max(0.0, min(1.0, y_min))
    x_max = max(0.0, min(1.0, x_max))
    y_max = max(0.0, min(1.0, y_max))

    try:
        return BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)
    except ValueError:
        return None
