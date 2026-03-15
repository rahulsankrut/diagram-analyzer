"""Multi-resolution tile generator for CAD diagram images."""

from dataclasses import dataclass
from pathlib import Path  # noqa: F401 — kept for type-hint clarity in docstrings

from PIL import Image

from src.models.diagram import DiagramMetadata
from src.models.ocr import BoundingBox
from src.models.tiling import Tile, TilePyramid

DEFAULT_MAX_SIZE = 1024
DEFAULT_OVERLAP = 0.20

# Grid dimensions (cols, rows) for each pyramid level.
_LEVEL_GRIDS: dict[int, tuple[int, int]] = {
    0: (1, 1),
    1: (2, 2),
    2: (4, 4),
}


@dataclass
class TilingConfig:
    """Configuration for :class:`TileGenerator`.

    Attributes:
        num_levels: Number of pyramid levels to generate.  Levels 0, 1, and 2
            correspond to 1×1, 2×2, and 4×4 grids respectively.
        overlap_fraction: Fractional overlap shared by adjacent tiles.  Must be
            >= 0.20 per project spec so that components are never split at a tile
            boundary without appearing in both neighbours.
        max_size: Maximum pixel dimension (width or height) for the level-0
            overview tile.  The image is downscaled proportionally if either
            dimension exceeds this value.
    """

    num_levels: int = 3
    overlap_fraction: float = DEFAULT_OVERLAP
    max_size: int = DEFAULT_MAX_SIZE


class TileGenerator:
    """Generates a multi-resolution tile pyramid from a high-resolution diagram image.

    Level 0 is a single overview tile of the full image downscaled to fit within
    ``config.max_size``.  Level 1 is a 2×2 grid and level 2 is a 4×4 grid, both
    with configurable overlap so that components near tile edges appear in every
    tile they visually straddle.

    Args:
        image: High-resolution source image (PIL Image).
        metadata: DiagramMetadata produced by the preprocessing pipeline.
        config: Optional tiling configuration.  Defaults to :class:`TilingConfig`.
    """

    def __init__(
        self,
        image: Image.Image,
        metadata: DiagramMetadata,
        config: TilingConfig | None = None,
    ) -> None:
        self._image = image
        self._metadata = metadata
        self._config = config or TilingConfig()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate(self) -> TilePyramid:
        """Generate all tiles for the configured number of pyramid levels.

        Returns:
            :class:`TilePyramid` containing metadata for all generated tiles.
        """
        pyramid = TilePyramid(diagram_id=self._metadata.diagram_id)
        for level in range(self._config.num_levels):
            pyramid.tiles.extend(self._generate_level(level))
        return pyramid

    def get_tile_image(self, tile: Tile) -> Image.Image:
        """Return the cropped (and for level 0, downscaled) PIL Image for a tile.

        Level-0 tiles return the full image downscaled to fit within
        ``config.max_size``.  All other levels return a crop of the source image
        at the tile's normalized bbox.

        Args:
            tile: Tile whose image region should be returned.

        Returns:
            PIL Image for this tile.
        """
        if tile.level == 0:
            return self._downscale(self._image)
        w, h = self._image.size
        x_min_px, y_min_px, x_max_px, y_max_px = tile.bbox.to_pixel_coords(w, h)
        return self._image.crop((x_min_px, y_min_px, x_max_px, y_max_px))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_level(self, level: int) -> list[Tile]:
        """Build all tiles for one pyramid level.

        Args:
            level: Zoom level index (0, 1, or 2).

        Returns:
            Flat list of :class:`Tile` objects for this level.
        """
        grid_cols, grid_rows = _LEVEL_GRIDS[level]
        overlap = self._config.overlap_fraction
        col_ranges = self._tile_coords(grid_cols, overlap)
        row_ranges = self._tile_coords(grid_rows, overlap)

        tiles: list[Tile] = []
        for row, (y_min, y_max) in enumerate(row_ranges):
            for col, (x_min, x_max) in enumerate(col_ranges):
                bbox = BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)
                tiles.append(self._build_tile(level, row, col, bbox))
        return tiles

    def _tile_coords(self, n: int, overlap_fraction: float) -> list[tuple[float, float]]:
        """Compute start/end normalized coordinates for *n* overlapping tiles.

        Adjacent tiles share exactly ``overlap_fraction`` of a tile's extent.
        For a single tile the result is simply ``[(0.0, 1.0)]``.

        Derivation::

            tile_width * (1 + (n - 1) * (1 - f)) = 1.0
            tile_width = 1.0 / (1 + (n - 1) * (1 - f))
            step       = tile_width * (1 - f)

        Floating-point endpoints are clamped to ``[0.0, 1.0]`` so that
        :class:`BoundingBox` validation never trips on rounding errors.

        Args:
            n: Number of tiles in this dimension.
            overlap_fraction: Fraction of tile width shared with each neighbour.

        Returns:
            List of ``(start, end)`` pairs in normalized coordinates, one per tile.
        """
        if n == 1:
            return [(0.0, 1.0)]

        tile_width = 1.0 / (1.0 + (n - 1) * (1.0 - overlap_fraction))
        step = tile_width * (1.0 - overlap_fraction)

        coords: list[tuple[float, float]] = []
        for i in range(n):
            start = max(0.0, i * step)
            end = min(1.0, start + tile_width)
            coords.append((start, end))
        return coords

    def _build_tile(self, level: int, row: int, col: int, bbox: BoundingBox) -> Tile:
        """Construct a :class:`Tile` and populate it with overlapping content.

        A component or text label is included in the tile if its bounding box
        has a non-empty interior intersection with the tile's bbox.  This means
        elements that straddle a tile boundary appear in *every* tile they touch.

        Args:
            level: Zoom level.
            row: Row index within the level's grid.
            col: Column index within the level's grid.
            bbox: Normalized region of the source image covered by this tile.

        Returns:
            Populated :class:`Tile` instance.
        """
        diagram_id = self._metadata.diagram_id
        tile_id = f"{diagram_id}_L{level}_R{row}_C{col}"

        component_ids = [
            comp.component_id
            for comp in self._metadata.components
            if comp.bbox.overlaps(bbox)
        ]
        text_label_ids = [
            label.label_id
            for label in self._metadata.text_labels
            if label.bbox.overlaps(bbox)
        ]

        return Tile(
            tile_id=tile_id,
            level=level,
            row=row,
            col=col,
            bbox=bbox,
            component_ids=component_ids,
            text_label_ids=text_label_ids,
        )

    def _downscale(self, image: Image.Image) -> Image.Image:
        """Downscale an image to fit within ``max_size``, preserving aspect ratio.

        Returns a copy of the original image if both dimensions are already
        within the limit.

        Args:
            image: Source image.

        Returns:
            Resized (or copied) PIL Image.
        """
        w, h = image.size
        max_size = self._config.max_size
        if w <= max_size and h <= max_size:
            return image.copy()
        scale = min(max_size / w, max_size / h)
        return image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
