"""Format normalizer — detects input format and rasterizes to PNG."""

from pathlib import Path
from typing import Literal

from PIL import Image

DiagramFormat = Literal["png", "tiff", "pdf", "dwg", "dxf"]

_EXTENSION_MAP: dict[str, DiagramFormat] = {
    ".png": "png",
    ".tif": "tiff",
    ".tiff": "tiff",
    ".pdf": "pdf",
    ".dwg": "dwg",
    ".dxf": "dxf",
}

# Maximum pixel dimension before we resize (avoids OOM on giant scans)
MAX_RASTER_DIMENSION_PX = 7000


class UnsupportedFormatError(Exception):
    """Raised when the input file format is not supported."""


class FormatNormalizer:
    """Detects the format of a CAD input file and rasterizes it to PNG.

    Supported for MVP:
        - PNG  — returned as-is (or optionally resized)
        - TIFF — converted via Pillow
        - PDF  — rasterized via ``pdf2image`` (first page only)

    Out-of-scope for MVP (raises ``UnsupportedFormatError``):
        - DWG — requires ODA File Converter or commercial library
        - DXF — experimental; planned for a future iteration

    Args:
        max_dimension_px: Maximum pixel size along the longest edge.
            Images larger than this are resized while preserving aspect ratio.
    """

    def __init__(self, max_dimension_px: int = MAX_RASTER_DIMENSION_PX) -> None:
        self._max_dimension_px = max_dimension_px

    def detect_format(self, source_path: Path) -> DiagramFormat:
        """Detect the diagram format from file extension.

        Args:
            source_path: Path to the input file.

        Returns:
            The detected DiagramFormat literal.

        Raises:
            UnsupportedFormatError: If the extension is not recognised.
        """
        ext = source_path.suffix.lower()
        if ext not in _EXTENSION_MAP:
            raise UnsupportedFormatError(
                f"Unsupported file extension: '{ext}'. "
                f"Supported: {sorted(_EXTENSION_MAP.keys())}"
            )
        return _EXTENSION_MAP[ext]

    async def normalize(self, source_path: Path) -> tuple[Path, DiagramFormat]:
        """Rasterize ``source_path`` to a PNG and return the output path.

        For PNG/TIFF inputs the file is opened with Pillow and saved as PNG
        (applying any resize). For PDF the first page is rasterized. DWG/DXF
        are not supported and raise ``UnsupportedFormatError``.

        Args:
            source_path: Path to the source diagram file.

        Returns:
            Tuple of (raster_png_path, detected_format).

        Raises:
            UnsupportedFormatError: If the format cannot be rasterized.
            FileNotFoundError: If ``source_path`` does not exist.
        """
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        fmt = self.detect_format(source_path)

        if fmt in ("dwg", "dxf"):
            raise UnsupportedFormatError(
                f"Format '{fmt}' is not supported in the current MVP. "
                "DWG requires ODA File Converter; DXF support is planned."
            )

        output_path = source_path.with_suffix(".normalized.png")

        if fmt == "pdf":
            image = self._rasterize_pdf(source_path)
        else:
            image = Image.open(source_path).convert("RGB")

        image = self._resize_if_needed(image)
        image.save(output_path, format="PNG")
        return output_path, fmt

    def _rasterize_pdf(self, pdf_path: Path) -> Image.Image:
        """Rasterize the first page of a PDF to a PIL Image.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            First-page raster as a PIL Image.

        Raises:
            ImportError: If ``pdf2image`` is not installed.
        """
        try:
            from pdf2image import convert_from_path  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "pdf2image is required for PDF rasterization. "
                "Install it with: uv add pdf2image"
            ) from exc

        pages = convert_from_path(pdf_path, dpi=300, first_page=1, last_page=1)
        return pages[0].convert("RGB")

    def _resize_if_needed(self, image: Image.Image) -> Image.Image:
        """Resize image if the longest side exceeds ``max_dimension_px``.

        Args:
            image: Input PIL Image.

        Returns:
            Resized (or unchanged) PIL Image.
        """
        w, h = image.size
        longest = max(w, h)
        if longest <= self._max_dimension_px:
            return image
        scale = self._max_dimension_px / longest
        new_size = (int(w * scale), int(h * scale))
        return image.resize(new_size, Image.LANCZOS)
