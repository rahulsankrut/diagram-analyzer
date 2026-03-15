"""Shared image utilities for tool functions.

Provides base64 encoding, overview downscaling, and padded crop helpers
so each tool module stays under the 40-line function limit.
"""

from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image

from src.models.ocr import BoundingBox

_MAX_OVERVIEW_PX = 1024
_CROP_PADDING = 0.05


def image_to_base64(image: Image.Image, fmt: str = "PNG") -> str:
    """Encode a PIL Image as a base64 string.

    Args:
        image: Source image.
        fmt: Pillow format string (default ``"PNG"``).

    Returns:
        Base64-encoded UTF-8 string of the image bytes.
    """
    buf = BytesIO()
    image.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()


def downscale_to_fit(image: Image.Image, max_px: int = _MAX_OVERVIEW_PX) -> Image.Image:
    """Downscale *image* to fit within *max_px* × *max_px*, preserving aspect ratio.

    Args:
        image: Source image.
        max_px: Maximum pixel dimension on either axis.

    Returns:
        Resized PIL Image, or a copy if both dimensions are already within limit.
    """
    w, h = image.size
    if w <= max_px and h <= max_px:
        return image.copy()
    scale = min(max_px / w, max_px / h)
    return image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def crop_with_padding(
    image: Image.Image,
    bbox: BoundingBox,
    padding: float = _CROP_PADDING,
) -> tuple[Image.Image, BoundingBox]:
    """Crop *image* to *bbox* with extra normalized padding on each side.

    The returned :class:`BoundingBox` is the actual cropped region after
    clamping to image boundaries.

    Args:
        image: Full-resolution source image.
        bbox: Normalized region to crop (0.0–1.0 coordinates).
        padding: Extra margin added on each side in normalized units (default 0.05).

    Returns:
        Tuple of (cropped PIL Image, actual crop BoundingBox).
    """
    padded = BoundingBox(
        x_min=max(0.001, bbox.x_min - padding),
        y_min=max(0.001, bbox.y_min - padding),
        x_max=min(0.999, bbox.x_max + padding),
        y_max=min(0.999, bbox.y_max + padding),
    )
    w, h = image.size
    x0, y0, x1, y1 = padded.to_pixel_coords(w, h)
    # Guard against zero-size crops after integer rounding
    x1 = max(x1, x0 + 1)
    y1 = max(y1, y0 + 1)
    return image.crop((x0, y0, x1, y1)), padded
