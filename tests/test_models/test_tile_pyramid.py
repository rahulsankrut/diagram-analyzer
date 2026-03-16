"""Tests for Tile, TilePyramid, and TileLevel models."""

import pytest
from pydantic import ValidationError

from src.models.ocr import BoundingBox
from src.models.tiling import MIN_OVERLAP_FRACTION, Tile, TileLevel, TilePyramid


def _bbox() -> BoundingBox:
    return BoundingBox(x_min=0.0, y_min=0.0, x_max=0.5, y_max=0.5)


def _make_tile(level: int, row: int, col: int, diagram_id: str = "diag-1") -> Tile:
    return Tile(
        tile_id=f"{diagram_id}_L{level}_R{row}_C{col}",
        level=level,
        row=row,
        col=col,
        bbox=BoundingBox(
            x_min=col * 0.25,
            y_min=row * 0.25,
            x_max=col * 0.25 + 0.5,
            y_max=row * 0.25 + 0.5,
        ),
    )


# ---------------------------------------------------------------------------
# TileLevel
# ---------------------------------------------------------------------------


class TestTileLevel:
    def test_valid_level_0(self) -> None:
        tl = TileLevel(level=0, grid_cols=1, grid_rows=1)
        assert tl.overlap_fraction == pytest.approx(MIN_OVERLAP_FRACTION)

    def test_valid_level_2(self) -> None:
        tl = TileLevel(level=2, grid_cols=4, grid_rows=4, overlap_fraction=0.60)
        assert tl.grid_cols == 4

    def test_overlap_below_minimum_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TileLevel(level=1, grid_cols=2, grid_rows=2, overlap_fraction=0.10)

    def test_level_above_2_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TileLevel(level=3, grid_cols=8, grid_rows=8)

    def test_negative_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TileLevel(level=-1, grid_cols=1, grid_rows=1)

    def test_zero_grid_cols_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TileLevel(level=0, grid_cols=0, grid_rows=1)

    def test_to_dict(self) -> None:
        tl = TileLevel(level=1, grid_cols=2, grid_rows=2)
        d = tl.to_dict()
        assert d["level"] == 1
        assert d["grid_cols"] == 2
        assert d["overlap_fraction"] == pytest.approx(MIN_OVERLAP_FRACTION)


# ---------------------------------------------------------------------------
# Tile
# ---------------------------------------------------------------------------


class TestTile:
    def test_valid_creation(self) -> None:
        tile = Tile(
            tile_id="diag_L0_R0_C0",
            level=0,
            row=0,
            col=0,
            bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0),
        )
        assert tile.tile_id == "diag_L0_R0_C0"
        assert tile.image_path == ""
        assert tile.component_ids == []
        assert tile.text_label_ids == []

    def test_with_image_path(self) -> None:
        tile = Tile(
            tile_id="t1",
            level=0,
            row=0,
            col=0,
            bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0),
            image_path="gs://bucket/tiles/L0_R0_C0.jpg",
        )
        assert tile.image_path == "gs://bucket/tiles/L0_R0_C0.jpg"

    def test_with_component_ids(self) -> None:
        tile = Tile(
            tile_id="t1",
            level=1,
            row=0,
            col=0,
            bbox=_bbox(),
            component_ids=["comp-1", "comp-2"],
        )
        assert len(tile.component_ids) == 2

    def test_bbox_must_be_normalized(self) -> None:
        with pytest.raises(ValidationError):
            Tile(
                tile_id="t1",
                level=0,
                row=0,
                col=0,
                bbox=BoundingBox(  # type: ignore[arg-type]
                    x_min=0,
                    y_min=0,
                    x_max=800,  # pixel value — rejected
                    y_max=600,
                ),
            )

    def test_negative_row_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Tile(tile_id="t1", level=0, row=-1, col=0, bbox=_bbox())

    def test_level_above_2_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Tile(tile_id="t1", level=3, row=0, col=0, bbox=_bbox())

    def test_to_dict(self) -> None:
        tile = Tile(
            tile_id="diag_L1_R0_C1",
            level=1,
            row=0,
            col=1,
            bbox=_bbox(),
            image_path="gs://b/t.jpg",
            component_ids=["c1"],
        )
        d = tile.to_dict()
        assert d["tile_id"] == "diag_L1_R0_C1"
        assert d["level"] == 1
        assert d["image_path"] == "gs://b/t.jpg"
        assert d["component_ids"] == ["c1"]
        assert isinstance(d["bbox"], dict)

    def test_serialization_roundtrip(self) -> None:
        original = Tile(
            tile_id="t-1",
            level=2,
            row=3,
            col=3,
            bbox=BoundingBox(x_min=0.5, y_min=0.5, x_max=0.9, y_max=0.9),
            image_path="gs://bucket/tiles/L2_R3_C3.jpg",
            component_ids=["comp-x"],
            text_label_ids=["lbl-y"],
        )
        restored = Tile.model_validate_json(original.model_dump_json())
        assert restored == original


# ---------------------------------------------------------------------------
# TilePyramid
# ---------------------------------------------------------------------------


class TestTilePyramid:
    def _full_pyramid(self) -> TilePyramid:
        """Build a 1+4+16 pyramid with non-overlapping tile bboxes."""
        tiles: list[Tile] = []
        # Level 0: 1 tile
        tiles.append(
            Tile(
                tile_id="d_L0_R0_C0",
                level=0,
                row=0,
                col=0,
                bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0),
            )
        )
        # Level 1: 2×2
        for r in range(2):
            for c in range(2):
                tiles.append(
                    Tile(
                        tile_id=f"d_L1_R{r}_C{c}",
                        level=1,
                        row=r,
                        col=c,
                        bbox=BoundingBox(
                            x_min=c * 0.5,
                            y_min=r * 0.5,
                            x_max=c * 0.5 + 0.5,
                            y_max=r * 0.5 + 0.5,
                        ),
                    )
                )
        # Level 2: 4×4
        for r in range(4):
            for c in range(4):
                tiles.append(
                    Tile(
                        tile_id=f"d_L2_R{r}_C{c}",
                        level=2,
                        row=r,
                        col=c,
                        bbox=BoundingBox(
                            x_min=c * 0.25,
                            y_min=r * 0.25,
                            x_max=c * 0.25 + 0.25,
                            y_max=r * 0.25 + 0.25,
                        ),
                    )
                )
        return TilePyramid(diagram_id="diag-1", tiles=tiles)

    def test_empty_pyramid(self) -> None:
        pyramid = TilePyramid(diagram_id="diag-x")
        assert pyramid.tiles == []
        assert pyramid.available_levels() == []

    def test_total_tile_count(self) -> None:
        pyramid = self._full_pyramid()
        assert len(pyramid.tiles) == 21  # 1 + 4 + 16

    def test_tiles_at_level_0(self) -> None:
        pyramid = self._full_pyramid()
        assert len(pyramid.tiles_at_level(0)) == 1

    def test_tiles_at_level_1(self) -> None:
        pyramid = self._full_pyramid()
        assert len(pyramid.tiles_at_level(1)) == 4

    def test_tiles_at_level_2(self) -> None:
        pyramid = self._full_pyramid()
        assert len(pyramid.tiles_at_level(2)) == 16

    def test_tiles_at_nonexistent_level(self) -> None:
        pyramid = self._full_pyramid()
        assert pyramid.tiles_at_level(5) == []

    def test_tile_at_found(self) -> None:
        pyramid = self._full_pyramid()
        tile = pyramid.tile_at(level=1, row=1, col=0)
        assert tile is not None
        assert tile.tile_id == "d_L1_R1_C0"

    def test_tile_at_not_found(self) -> None:
        pyramid = self._full_pyramid()
        tile = pyramid.tile_at(level=1, row=5, col=5)
        assert tile is None

    def test_tile_at_level_0(self) -> None:
        pyramid = self._full_pyramid()
        tile = pyramid.tile_at(level=0, row=0, col=0)
        assert tile is not None
        assert tile.level == 0

    def test_available_levels_sorted(self) -> None:
        pyramid = self._full_pyramid()
        assert pyramid.available_levels() == [0, 1, 2]

    def test_available_levels_partial(self) -> None:
        tiles = [
            Tile(
                tile_id="d_L0_R0_C0",
                level=0,
                row=0,
                col=0,
                bbox=BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0),
            )
        ]
        pyramid = TilePyramid(diagram_id="partial", tiles=tiles)
        assert pyramid.available_levels() == [0]

    def test_to_dict_structure(self) -> None:
        pyramid = self._full_pyramid()
        d = pyramid.to_dict()
        assert d["diagram_id"] == "diag-1"
        assert isinstance(d["tiles"], list)
        assert len(d["tiles"]) == 21
        assert isinstance(d["tiles"][0], dict)

    def test_serialization_roundtrip(self) -> None:
        pyramid = self._full_pyramid()
        json_str = pyramid.model_dump_json()
        restored = TilePyramid.model_validate_json(json_str)
        assert restored.diagram_id == pyramid.diagram_id
        assert len(restored.tiles) == len(pyramid.tiles)
        assert restored.available_levels() == pyramid.available_levels()
        # spot-check a specific tile
        original_tile = pyramid.tile_at(level=2, row=3, col=3)
        restored_tile = restored.tile_at(level=2, row=3, col=3)
        assert original_tile is not None
        assert restored_tile is not None
        assert original_tile.tile_id == restored_tile.tile_id
