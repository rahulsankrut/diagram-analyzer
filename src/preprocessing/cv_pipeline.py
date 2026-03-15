"""Computer-vision detection pipeline for CAD diagram images.

Wraps OpenCV contour detection (symbols) and probabilistic Hough-line
transform (traces) behind a single :class:`CVPipeline` class.  The OpenCV
and NumPy packages are imported lazily so that the module can be imported —
and the pipeline mocked out in tests — without OpenCV being installed.

Returns raw :class:`~src.models.CVResult` geometry; semantic interpretation
(Symbol → Component, DetectedLine → Trace) is a later pipeline stage.
"""

from __future__ import annotations

import logging
from typing import Any

from PIL import Image

from src.models import BoundingBox, CVResult, DetectedLine, Symbol

logger = logging.getLogger(__name__)


class CVPipeline:
    """Detect symbols and line traces in a CAD diagram image via OpenCV.

    Symbols are detected as closed contours that exceed a minimum area
    threshold.  Traces are detected via the probabilistic Hough-line
    transform on a Canny edge map.

    If ``opencv-python-headless`` is not installed the pipeline logs a
    warning and returns an empty :class:`~src.models.CVResult` rather than
    raising, so the broader preprocessing pipeline can continue with OCR
    results only.
    """

    # Minimum contour area (pixels²) to be treated as a symbol candidate
    _MIN_SYMBOL_AREA: int = 200
    # Hough-line accumulator vote threshold
    _HOUGH_THRESHOLD: int = 80

    def run(self, image: Image.Image) -> CVResult:
        """Run symbol and line detection on *image*.

        Args:
            image: Full-resolution CAD diagram as a PIL Image.

        Returns:
            :class:`~src.models.CVResult` with detected symbols and lines.
            Returns an empty result (no symbols, no lines) when OpenCV is
            not installed.
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

        symbols = self._detect_symbols(blurred, w, h)
        lines = self._detect_lines(blurred, w, h)

        logger.debug("CV pipeline: %d symbols, %d lines detected", len(symbols), len(lines))
        return CVResult(symbols=symbols, detected_lines=lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
