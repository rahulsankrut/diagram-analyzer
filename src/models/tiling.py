"""Tiling data models — tile levels, tiles, and the tile pyramid."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.models.ocr import BoundingBox

# Raised from 0.20 to 0.50 per Stürmer et al. (arXiv:2411.13929) empirical finding:
# symbol fragmentation at patch boundaries costs ~10% detection accuracy even at
# 50% overlap, making 50% the recommended minimum for P&ID-class diagrams.
MIN_OVERLAP_FRACTION = 0.50


class TileLevel(BaseModel):
    """Configuration for one zoom level of the tiling pyramid.

    Attributes:
        level: Zoom level index (0 = overview, 1 = 2×2, 2 = 4×4).
        grid_cols: Number of tile columns at this level.
        grid_rows: Number of tile rows at this level.
        overlap_fraction: Fractional overlap between adjacent tiles.
            Must be >= 0.50 per Stürmer et al. (arXiv:2411.13929) — 50% overlap
            is the empirically validated minimum to avoid symbol fragmentation at
            patch boundaries.
    """

    level: int = Field(ge=0, le=2)
    grid_cols: int = Field(ge=1)
    grid_rows: int = Field(ge=1)
    overlap_fraction: float = Field(default=MIN_OVERLAP_FRACTION, ge=MIN_OVERLAP_FRACTION)

    @field_validator("overlap_fraction")
    @classmethod
    def validate_min_overlap(cls, v: float) -> float:
        """Enforce the ≥50% overlap floor (Stürmer et al. 2024)."""
        if v < MIN_OVERLAP_FRACTION:
            raise ValueError(
                f"overlap_fraction must be >= {MIN_OVERLAP_FRACTION}, got {v}"
            )
        return v

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return self.model_dump(mode="json")


class Tile(BaseModel):
    """One image tile within the multi-resolution pyramid.

    The ``bbox`` field uses *normalized* (0.0–1.0) coordinates that describe
    where this tile sits within the original full-resolution diagram image.
    The ``image_path`` field holds either a local filesystem path (during
    processing) or a GCS URI (after upload).

    Attributes:
        tile_id: Unique ID following the pattern
            ``{diagram_id}_L{level}_R{row}_C{col}``.
        level: Zoom level this tile belongs to (0, 1, or 2).
        row: Zero-indexed row position within the tile grid.
        col: Zero-indexed column position within the tile grid.
        bbox: Normalized (0.0–1.0) region of the original image covered by
            this tile, including overlap margins.
        image_path: Local path or GCS URI of the tile image file.
            Empty string before the tile has been written to disk or uploaded.
        component_ids: IDs of components whose centroid falls within this tile.
        text_label_ids: IDs of text labels overlapping this tile.
    """

    tile_id: str
    level: int = Field(ge=0, le=2)
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    bbox: BoundingBox
    image_path: str = ""
    component_ids: list[str] = Field(default_factory=list)
    text_label_ids: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return self.model_dump(mode="json")


class TilePyramid(BaseModel):
    """Multi-resolution tile pyramid for one diagram.

    Stores all tile metadata in a flat list.  Query methods slice the list
    by level, row, and column.  The full pyramid for three levels has
    1 + 4 + 16 = 21 tiles.

    Attributes:
        diagram_id: ID of the diagram this pyramid belongs to.
        tiles: All tiles across all levels, in insertion order.
    """

    diagram_id: str
    tiles: list[Tile] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def tiles_at_level(self, level: int) -> list[Tile]:
        """Return all tiles belonging to a specific zoom level.

        Args:
            level: Zoom level index (0, 1, or 2).

        Returns:
            List of tiles at the requested level (empty if none exist).
        """
        return [t for t in self.tiles if t.level == level]

    def tile_at(self, level: int, row: int, col: int) -> Tile | None:
        """Look up a specific tile by its grid position.

        Args:
            level: Zoom level index.
            row: Row index within the grid.
            col: Column index within the grid.

        Returns:
            The matching :class:`Tile`, or ``None`` if not found.
        """
        for tile in self.tiles:
            if tile.level == level and tile.row == row and tile.col == col:
                return tile
        return None

    def available_levels(self) -> list[int]:
        """Return sorted list of zoom levels present in this pyramid.

        Returns:
            Sorted list of distinct level integers (e.g. ``[0, 1, 2]``).
        """
        return sorted({t.level for t in self.tiles})

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation of the full pyramid.

        Returns:
            Dict containing ``diagram_id`` and a ``tiles`` list.
        """
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Backward-compatible alias kept for code that already imports TilingManifest
# ---------------------------------------------------------------------------

class TilingManifest(BaseModel):
    """Backward-compatible manifest model.

    New code should prefer :class:`TilePyramid`.  This model is retained so
    that Phase 3 tiling engine code written against the Phase 1 scaffold
    continues to import without modification.

    Attributes:
        diagram_id: ID of the parent diagram.
        levels: Ordered list of TileLevel configs.
        tiles: All tiles across all levels.
    """

    diagram_id: str
    levels: list[TileLevel] = Field(default_factory=list)
    tiles: list[Tile] = Field(default_factory=list)

    def tiles_at_level(self, level: int) -> list[Tile]:
        """Return all tiles belonging to a specific zoom level.

        Args:
            level: Zoom level index (0, 1, or 2).

        Returns:
            Filtered list of tiles at the requested level.
        """
        return [t for t in self.tiles if t.level == level]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return self.model_dump(mode="json")
