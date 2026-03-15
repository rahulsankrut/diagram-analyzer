"""Shared image utilities for tool functions.

Provides base64 encoding, overview downscaling, padded crop helpers,
and Set-of-Marks (SOM) tile annotation so each tool module stays under
the 40-line function limit.
"""

from __future__ import annotations

import base64
import re
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from src.models.ocr import BoundingBox

_MAX_OVERVIEW_PX = 1024
_CROP_PADDING = 0.05
_SOM_OUTLINE_COLOR = (255, 40, 40)  # red
_SOM_LABEL_COLOR = (255, 255, 255)  # white text
_SOM_LABEL_BG = (200, 30, 30)  # dark red background for label


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


# ---------------------------------------------------------------------------
# Set-of-Marks (SOM) annotation
# ---------------------------------------------------------------------------


def annotate_tile(
    image: Image.Image,
    markers: list[dict],
    tile_bbox: BoundingBox,
) -> Image.Image:
    """Draw numbered markers on a tile image for Set-of-Marks grounding.

    Each marker is rendered as a red bounding box with a numbered label tag
    so the VLM can reference elements by ``[1]``, ``[2]``, etc. instead of
    correlating raw coordinate tuples.

    Args:
        image: Tile image to annotate (will not be mutated).
        markers: List of dicts with ``id`` (str) and ``bbox``
            (:class:`BoundingBox`) in diagram-normalised coordinates.
        tile_bbox: The tile's own bounding box in diagram-normalised space.

    Returns:
        Annotated copy of the image.
    """
    annotated = image.copy().convert("RGB")
    draw = ImageDraw.Draw(annotated)
    w, h = annotated.size
    font = _get_marker_font(h)

    tw = tile_bbox.x_max - tile_bbox.x_min
    th = tile_bbox.y_max - tile_bbox.y_min
    if tw <= 0 or th <= 0:
        return annotated

    for m in markers:
        bx: BoundingBox = m["bbox"]
        x0 = int((bx.x_min - tile_bbox.x_min) / tw * w)
        y0 = int((bx.y_min - tile_bbox.y_min) / th * h)
        x1 = int((bx.x_max - tile_bbox.x_min) / tw * w)
        y1 = int((bx.y_max - tile_bbox.y_min) / th * h)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        draw.rectangle([x0, y0, x1, y1], outline=_SOM_OUTLINE_COLOR, width=2)
        _draw_label_tag(draw, m["id"], x0, y0, font)

    return annotated


def _draw_label_tag(
    draw: ImageDraw.ImageDraw,
    label: str,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """Draw a small ``[N]`` tag above-left of the bounding box."""
    tag = f"[{label}]"
    bbox = draw.textbbox((0, 0), tag, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tag_y = max(y - th - 4, 0)
    draw.rectangle([x, tag_y, x + tw + 4, tag_y + th + 2], fill=_SOM_LABEL_BG)
    draw.text((x + 2, tag_y), tag, fill=_SOM_LABEL_COLOR, font=font)


def _get_marker_font(image_height: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return a font sized proportionally to the image height."""
    size = max(10, image_height // 30)
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except (OSError, IOError):
        try:
            return ImageFont.truetype("Arial Bold.ttf", size)
        except (OSError, IOError):
            return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Pixel-coordinate enrichment
# ---------------------------------------------------------------------------


def bbox_to_pixel_dict(
    bbox: BoundingBox,
    width_px: int,
    height_px: int,
) -> dict[str, int]:
    """Convert a normalised BoundingBox to a pixel-coordinate dict.

    Args:
        bbox: Normalised bounding box (0.0–1.0).
        width_px: Full diagram width in pixels.
        height_px: Full diagram height in pixels.

    Returns:
        Dict with ``x``, ``y``, ``w``, ``h`` in pixels.
    """
    x0, y0, x1, y1 = bbox.to_pixel_coords(width_px, height_px)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


# ---------------------------------------------------------------------------
# JSON fence stripping
# ---------------------------------------------------------------------------


def strip_json_markdown_fence(text: str) -> str:
    """Remove markdown code-fence wrappers from JSON strings.

    Gemini sometimes wraps JSON responses in triple-backtick fences::

        ```json
        {"key": "value"}
        ```

    This utility strips them so ``json.loads`` succeeds.

    Args:
        text: Raw text that may contain a code fence.

    Returns:
        The unwrapped content.
    """
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", stripped)
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()
