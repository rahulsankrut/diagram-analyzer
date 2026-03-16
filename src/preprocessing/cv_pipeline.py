"""Computer-vision detection pipeline for CAD diagram images.

Wraps OpenCV contour detection (symbols) and probabilistic Hough-line
transform (traces) behind a single :class:`CVPipeline` class.  The OpenCV
and NumPy packages are imported lazily so that the module can be imported —
and the pipeline mocked out in tests — without OpenCV being installed.

OCR text regions (when provided) are masked to white before detection so that
character strokes are not mistaken for symbols or pipe segments — this is the
dominant source of CV false positives on dense P&IDs (Stürmer et al. 2024,
arXiv:2411.13929).

Returns raw :class:`~src.models.CVResult` geometry; semantic interpretation
(Symbol → Component, DetectedLine → Trace) is a later pipeline stage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PIL import Image

from src.models import BoundingBox, CVResult, DetectedLine, Junction, JunctionType, Symbol

if TYPE_CHECKING:
    from src.models import TextLabel

logger = logging.getLogger(__name__)


def _seg_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> tuple[float, float, float, float] | None:
    """Return ``(t, u, ix, iy)`` if segments ``(p1, p2)`` and ``(p3, p4)`` intersect.

    Uses the standard parametric intersection formula.  ``t`` and ``u`` are the
    fractional positions along each segment (both in ``[0, 1]`` when the segments
    cross).  ``ix``, ``iy`` are the intersection coordinates.

    Args:
        p1: Start of first segment (normalized x, y).
        p2: End of first segment.
        p3: Start of second segment.
        p4: End of second segment.

    Returns:
        ``(t, u, ix, iy)`` if the segments intersect, otherwise ``None``.
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-10:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return t, u, x1 + t * (x2 - x1), y1 + t * (y2 - y1)
    return None


class CVPipeline:
    """Detect symbols and line traces in a CAD diagram image via OpenCV.

    Symbols are detected as closed contours that exceed a minimum area
    threshold.  Traces are detected via the probabilistic Hough-line
    transform on a Canny edge map.  Junctions between detected lines are
    classified as CONNECTED (lines genuinely meet) or CROSSING (lines pass
    through each other without connecting).

    If ``opencv-python-headless`` is not installed the pipeline logs a
    warning and returns an empty :class:`~src.models.CVResult` rather than
    raising, so the broader preprocessing pipeline can continue with OCR
    results only.
    """

    # Minimum contour area (pixels²) to be treated as a symbol candidate
    _MIN_SYMBOL_AREA: int = 200
    # Hough-line accumulator vote threshold
    _HOUGH_THRESHOLD: int = 80
    # Parametric distance from an endpoint considered "at the endpoint"
    _ENDPOINT_TOL: float = 0.15
    # Half-size of a junction bounding box in normalized image coordinates
    _JUNCTION_HALF: float = 0.005
    # Padding (pixels) added around each OCR text bbox when masking
    _TEXT_MASK_PAD: int = 2

    def run(
        self,
        image: Image.Image,
        text_labels: list[TextLabel] | None = None,
    ) -> CVResult:
        """Run symbol and line detection on *image*.

        When *text_labels* are supplied (from a preceding OCR pass), their
        bounding boxes are painted white on the grayscale image before any CV
        detection runs.  This suppresses character strokes that would otherwise
        register as false-positive symbols or spurious Hough line segments —
        a key source of noise on dense P&IDs (Stürmer et al. 2024).

        Args:
            image: Full-resolution CAD diagram as a PIL Image.
            text_labels: Optional OCR output from the preprocessing pipeline.
                When provided, text regions are masked before CV runs.

        Returns:
            :class:`~src.models.CVResult` with detected symbols, lines, and
            classified junctions.  Returns an empty result when OpenCV is not
            installed.
        """
        try:
            import cv2  # noqa: PLC0415
            import numpy as np  # noqa: PLC0415
        except ImportError:
            logger.warning(
                "OpenCV / NumPy not available; CV pipeline returning empty CVResult"
            )
            return CVResult()

        rgb = np.array(image.convert("RGB"))
        h, w = rgb.shape[:2]
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)

        # Mask OCR text regions to suppress false-positive detections
        if text_labels:
            blurred = self._mask_text_regions(blurred, text_labels, w, h)
            logger.debug("CV pipeline: masked %d OCR text regions", len(text_labels))

        symbols = self._detect_symbols(blurred, w, h)
        lines = self._detect_lines(blurred, w, h)
        junctions = self._classify_junctions(lines)

        logger.debug(
            "CV pipeline: %d symbols, %d lines, %d junctions (%d connected, %d crossing)",
            len(symbols),
            len(lines),
            len(junctions),
            sum(1 for j in junctions if j.junction_type == JunctionType.CONNECTED),
            sum(1 for j in junctions if j.junction_type == JunctionType.CROSSING),
        )
        return CVResult(symbols=symbols, detected_lines=lines, junctions=junctions)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _mask_text_regions(
        self,
        gray: Any,
        text_labels: list[TextLabel],
        w: int,
        h: int,
    ) -> Any:
        """Paint OCR text bounding boxes white on the grayscale image.

        Removing text-stroke pixels prevents character strokes from being
        detected as symbol contours or pipe segments by the Hough transform.
        A small border pad catches ascenders/descenders outside the tight OCR
        box.

        Args:
            gray: Grayscale NumPy array to mask (modified copy is returned).
            text_labels: OCR-extracted labels whose bboxes define masked regions.
            w: Image width in pixels.
            h: Image height in pixels.

        Returns:
            New NumPy array with text regions filled to 255 (white/background).
        """
        import numpy as np  # noqa: PLC0415

        masked = gray.copy()
        pad = self._TEXT_MASK_PAD
        for label in text_labels:
            x1, y1, x2, y2 = label.bbox.to_pixel_coords(w, h)
            masked[
                max(0, y1 - pad) : min(h, y2 + pad),
                max(0, x1 - pad) : min(w, x2 + pad),
            ] = 255
        return masked

    def _classify_junctions(self, lines: list[DetectedLine]) -> list[Junction]:
        """Classify intersection points between detected Hough line segments.

        For each pair of lines that intersect, the parametric position of the
        intersection determines its topology:

        * **CONNECTED** — the intersection is near the endpoint of at least one
          segment (T-junction or L-corner): the lines genuinely meet and share
          a node.
        * **CROSSING** — the intersection is in the interior of *both* segments
          (X-crossing): the lines pass through each other and are NOT connected.

        The 15% endpoint tolerance follows standard Hough-junction classification
        practice (Stürmer et al. 2024, arXiv:2411.13929).

        Args:
            lines: All detected line segments in normalized coordinates.

        Returns:
            List of classified :class:`~src.models.Junction` objects.
        """
        junctions: list[Junction] = []
        tol = self._ENDPOINT_TOL
        half = self._JUNCTION_HALF

        for i, la in enumerate(lines):
            for lb in lines[i + 1 :]:
                result = _seg_intersect(
                    la.start_point, la.end_point,
                    lb.start_point, lb.end_point,
                )
                if result is None:
                    continue
                t, u, ix, iy = result
                at_endpoint = (
                    t < tol or t > 1.0 - tol
                    or u < tol or u > 1.0 - tol
                )
                jtype = JunctionType.CONNECTED if at_endpoint else JunctionType.CROSSING
                try:
                    bbox = BoundingBox(
                        x_min=max(0.0, ix - half),
                        y_min=max(0.0, iy - half),
                        x_max=min(1.0, ix + half),
                        y_max=min(1.0, iy + half),
                    )
                except ValueError:
                    continue
                junctions.append(Junction(bbox=bbox, junction_type=jtype))

        return junctions

    def _detect_symbols(self, gray: Any, w: int, h: int) -> list[Symbol]:
        """Find closed-contour symbols via Otsu threshold + contour detection.

        Args:
            gray: Grayscale NumPy image array (already blurred).
            w: Image width in pixels.
            h: Image height in pixels.

        Returns:
            List of :class:`~src.models.Symbol` objects with normalized bboxes.
        """
        import cv2  # noqa: PLC0415

        _, thresh = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        symbols: list[Symbol] = []
        for contour in contours:
            if cv2.contourArea(contour) < self._MIN_SYMBOL_AREA:
                continue
            x, y, cw, ch = cv2.boundingRect(contour)
            try:
                bbox = BoundingBox(
                    x_min=x / w,
                    y_min=y / h,
                    x_max=min(1.0, (x + cw) / w),
                    y_max=min(1.0, (y + ch) / h),
                )
            except ValueError:
                continue
            symbols.append(Symbol(bbox=bbox, confidence=0.5))
        return symbols

    def _detect_lines(self, gray: Any, w: int, h: int) -> list[DetectedLine]:
        """Detect line segments via probabilistic Hough transform on Canny edges.

        Args:
            gray: Grayscale NumPy image array (already blurred).
            w: Image width in pixels.
            h: Image height in pixels.

        Returns:
            List of :class:`~src.models.DetectedLine` with normalized endpoints.
        """
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        raw_lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=self._HOUGH_THRESHOLD,
            minLineLength=20,
            maxLineGap=5,
        )
        if raw_lines is None:
            return []
        return [
            DetectedLine(
                start_point=(float(x1) / w, float(y1) / h),
                end_point=(float(x2) / w, float(y2) / h),
            )
            for x1, y1, x2, y2 in (seg[0] for seg in raw_lines)
        ]
