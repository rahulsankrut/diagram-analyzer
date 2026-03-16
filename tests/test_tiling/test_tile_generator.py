"""Tests for TileGenerator — tile counts, overlap, component filtering."""

import pytest
from PIL import Image

from src.models.component import Component
from src.models.diagram import DiagramMetadata
from src.models.ocr import BoundingBox
from src.models.text_label import TextLabel
from src.tiling.tile_generator import TileGenerator, TilingConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_image(width: int = 1000, height: int = 1000) -> Image.Image:
    return Image.new("RGB", (width, height), color="white")


def _make_metadata(
    components: list[Component] | None = None,
    text_labels: list[TextLabel] | None = None,
    width_px: int = 1000,
    height_px: int = 1000,
) -> DiagramMetadata:
    return DiagramMetadata(
        source_filename="test.png",
        format="png",
        width_px=width_px,
        height_px=height_px,
        components=components or [],
        text_labels=text_labels or [],
    )


# ---------------------------------------------------------------------------
# Tile count and structure
# ---------------------------------------------------------------------------


class TestTileStructure:
    def test_total_tile_count(self) -> None:
        """Pyramid should have 1 + 4 + 16 = 21 tiles across three levels."""
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        assert len(pyramid.tiles) == 21

    def test_level_0_single_tile(self) -> None:
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        assert len(pyramid.tiles_at_level(0)) == 1

    def test_level_1_four_tiles(self) -> None:
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        assert len(pyramid.tiles_at_level(1)) == 4

    def test_level_2_sixteen_tiles(self) -> None:
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        assert len(pyramid.tiles_at_level(2)) == 16

    def test_level_0_bbox_covers_full_image(self) -> None:
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        tile = pyramid.tile_at(0, 0, 0)
        assert tile is not None
        assert tile.bbox.x_min == pytest.approx(0.0)
        assert tile.bbox.y_min == pytest.approx(0.0)
        assert tile.bbox.x_max == pytest.approx(1.0)
        assert tile.bbox.y_max == pytest.approx(1.0)

    def test_tile_id_format(self) -> None:
        """Tile IDs should follow the {diagram_id}_L{level}_R{row}_C{col} pattern."""
        metadata = _make_metadata()
        pyramid = TileGenerator(_make_image(), metadata).generate()
        tile = pyramid.tile_at(1, 0, 1)
        assert tile is not None
        assert tile.tile_id == f"{metadata.diagram_id}_L1_R0_C1"

    def test_all_levels_present(self) -> None:
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        assert pyramid.available_levels() == [0, 1, 2]

    def test_level1_tiles_cover_full_image(self) -> None:
        """The union of all level-1 tile bboxes must cover the full [0,1]×[0,1] space."""
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        tiles = pyramid.tiles_at_level(1)
        # Every row/col combination must be present
        positions = {(t.row, t.col) for t in tiles}
        assert positions == {(0, 0), (0, 1), (1, 0), (1, 1)}

    def test_level1_rightmost_tile_reaches_edge(self) -> None:
        """The rightmost column tile at level 1 must reach x_max == 1.0."""
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        tile = pyramid.tile_at(1, 0, 1)
        assert tile is not None
        assert tile.bbox.x_max == pytest.approx(1.0)

    def test_level1_bottom_tile_reaches_edge(self) -> None:
        """The bottom row tile at level 1 must reach y_max == 1.0."""
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        tile = pyramid.tile_at(1, 1, 0)
        assert tile is not None
        assert tile.bbox.y_max == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Overlap correctness
# ---------------------------------------------------------------------------


class TestOverlap:
    def _overlap_fraction(self, a_max: float, b_min: float, tile_size: float) -> float:
        """Compute the overlap as a fraction of *tile_size*."""
        return (a_max - b_min) / tile_size

    def test_level1_horizontal_overlap_at_least_50pct(self) -> None:
        """Horizontally adjacent level-1 tiles must overlap by >= 50% of tile width.

        50% is the empirically validated minimum from Stürmer et al.
        (arXiv:2411.13929) — symbol fragmentation at boundaries costs ~10%
        detection mAP even at this threshold.
        """
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        left = pyramid.tile_at(1, 0, 0)
        right = pyramid.tile_at(1, 0, 1)
        assert left is not None and right is not None
        tile_width = left.bbox.x_max - left.bbox.x_min
        frac = self._overlap_fraction(left.bbox.x_max, right.bbox.x_min, tile_width)
        assert frac >= 0.50 - 1e-9

    def test_level1_vertical_overlap_at_least_50pct(self) -> None:
        """Vertically adjacent level-1 tiles must overlap by >= 50% of tile height."""
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        top = pyramid.tile_at(1, 0, 0)
        bottom = pyramid.tile_at(1, 1, 0)
        assert top is not None and bottom is not None
        tile_height = top.bbox.y_max - top.bbox.y_min
        frac = self._overlap_fraction(top.bbox.y_max, bottom.bbox.y_min, tile_height)
        assert frac >= 0.50 - 1e-9

    def test_level2_horizontal_overlap_at_least_50pct(self) -> None:
        """Horizontally adjacent level-2 tiles must overlap by >= 50% of tile width."""
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        left = pyramid.tile_at(2, 0, 0)
        right = pyramid.tile_at(2, 0, 1)
        assert left is not None and right is not None
        tile_width = left.bbox.x_max - left.bbox.x_min
        frac = self._overlap_fraction(left.bbox.x_max, right.bbox.x_min, tile_width)
        assert frac >= 0.50 - 1e-9

    def test_overlap_exactly_50pct_with_default_config(self) -> None:
        """With the default config, overlap should equal exactly 50%."""
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        left = pyramid.tile_at(1, 0, 0)
        right = pyramid.tile_at(1, 0, 1)
        assert left is not None and right is not None
        tile_width = left.bbox.x_max - left.bbox.x_min
        frac = self._overlap_fraction(left.bbox.x_max, right.bbox.x_min, tile_width)
        assert frac == pytest.approx(0.50, abs=1e-6)

    def test_custom_overlap_fraction_respected(self) -> None:
        """A custom overlap_fraction of 60% should produce ~60% tile overlap."""
        config = TilingConfig(overlap_fraction=0.60)
        pyramid = TileGenerator(_make_image(), _make_metadata(), config).generate()
        left = pyramid.tile_at(1, 0, 0)
        right = pyramid.tile_at(1, 0, 1)
        assert left is not None and right is not None
        tile_width = left.bbox.x_max - left.bbox.x_min
        frac = self._overlap_fraction(left.bbox.x_max, right.bbox.x_min, tile_width)
        assert frac == pytest.approx(0.60, abs=1e-6)


# ---------------------------------------------------------------------------
# Component and label filtering
# ---------------------------------------------------------------------------


class TestComponentFiltering:
    def test_component_at_boundary_in_both_tiles(self) -> None:
        """A component straddling the tile boundary should appear in both tiles."""
        # Place a component around x≈0.5, which straddles the overlap zone of
        # the level-1 grid tiles (left tile ends ~0.556, right tile starts ~0.444).
        comp = Component(
            component_type="resistor",
            bbox=BoundingBox(x_min=0.45, y_min=0.1, x_max=0.55, y_max=0.2),
        )
        pyramid = TileGenerator(_make_image(), _make_metadata(components=[comp])).generate()

        left = pyramid.tile_at(1, 0, 0)
        right = pyramid.tile_at(1, 0, 1)
        assert left is not None and right is not None
        assert comp.component_id in left.component_ids
        assert comp.component_id in right.component_ids

    def test_level0_contains_all_components(self) -> None:
        """Level-0 tile must include every component in the diagram."""
        comps = [
            Component(
                component_type="resistor",
                bbox=BoundingBox(x_min=0.05, y_min=0.05, x_max=0.15, y_max=0.15),
            ),
            Component(
                component_type="capacitor",
                bbox=BoundingBox(x_min=0.80, y_min=0.80, x_max=0.90, y_max=0.90),
            ),
        ]
        pyramid = TileGenerator(_make_image(), _make_metadata(components=comps)).generate()
        tile = pyramid.tile_at(0, 0, 0)
        assert tile is not None
        for comp in comps:
            assert comp.component_id in tile.component_ids

    def test_component_fully_left_not_in_right_tile(self) -> None:
        """A component fully in the left half must not appear in the rightmost tile."""
        comp = Component(
            component_type="resistor",
            bbox=BoundingBox(x_min=0.05, y_min=0.1, x_max=0.15, y_max=0.2),
        )
        pyramid = TileGenerator(_make_image(), _make_metadata(components=[comp])).generate()
        right = pyramid.tile_at(1, 0, 1)
        assert right is not None
        assert comp.component_id not in right.component_ids

    def test_component_fully_right_not_in_left_tile(self) -> None:
        """A component fully in the right half must not appear in the leftmost tile."""
        comp = Component(
            component_type="capacitor",
            bbox=BoundingBox(x_min=0.85, y_min=0.1, x_max=0.95, y_max=0.2),
        )
        pyramid = TileGenerator(_make_image(), _make_metadata(components=[comp])).generate()
        left = pyramid.tile_at(1, 0, 0)
        assert left is not None
        assert comp.component_id not in left.component_ids

    def test_text_label_at_boundary_in_both_tiles(self) -> None:
        """A text label straddling the tile boundary should appear in both tiles."""
        label = TextLabel(
            text="NET1",
            bbox=BoundingBox(x_min=0.46, y_min=0.3, x_max=0.54, y_max=0.4),
            confidence=0.9,
        )
        pyramid = TileGenerator(
            _make_image(), _make_metadata(text_labels=[label])
        ).generate()

        left = pyramid.tile_at(1, 0, 0)
        right = pyramid.tile_at(1, 0, 1)
        assert left is not None and right is not None
        assert label.label_id in left.text_label_ids
        assert label.label_id in right.text_label_ids

    def test_empty_diagram_produces_empty_component_ids(self) -> None:
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        for tile in pyramid.tiles:
            assert tile.component_ids == []
            assert tile.text_label_ids == []


# ---------------------------------------------------------------------------
# get_tile_image
# ---------------------------------------------------------------------------


class TestGetTileImage:
    def test_level0_downscales_large_image(self) -> None:
        """Level-0 tile image must fit within max_size."""
        image = _make_image(2000, 1500)
        gen = TileGenerator(image, _make_metadata(), TilingConfig(max_size=1024))
        pyramid = gen.generate()
        tile = pyramid.tile_at(0, 0, 0)
        assert tile is not None
        img = gen.get_tile_image(tile)
        assert img.width <= 1024
        assert img.height <= 1024

    def test_level0_preserves_aspect_ratio(self) -> None:
        """Downscaled level-0 image should preserve aspect ratio."""
        image = _make_image(2000, 1000)
        gen = TileGenerator(image, _make_metadata(), TilingConfig(max_size=1024))
        pyramid = gen.generate()
        tile = pyramid.tile_at(0, 0, 0)
        assert tile is not None
        img = gen.get_tile_image(tile)
        # Original is 2:1; downscaled should maintain ratio (approx)
        assert img.width / img.height == pytest.approx(2.0, abs=0.01)

    def test_level0_small_image_not_upscaled(self) -> None:
        """Images already within max_size must not be upscaled."""
        image = _make_image(800, 600)
        gen = TileGenerator(image, _make_metadata(), TilingConfig(max_size=1024))
        pyramid = gen.generate()
        tile = pyramid.tile_at(0, 0, 0)
        assert tile is not None
        img = gen.get_tile_image(tile)
        assert img.size == (800, 600)

    def test_level1_crop_dimensions_match_bbox(self) -> None:
        """Level-1 tile crop size must match the pixel dimensions of the tile bbox."""
        width, height = 1000, 1000
        image = _make_image(width, height)
        gen = TileGenerator(image, _make_metadata(width_px=width, height_px=height))
        pyramid = gen.generate()
        tile = pyramid.tile_at(1, 0, 0)
        assert tile is not None
        img = gen.get_tile_image(tile)
        expected_w = int(tile.bbox.x_max * width) - int(tile.bbox.x_min * width)
        expected_h = int(tile.bbox.y_max * height) - int(tile.bbox.y_min * height)
        assert img.width == expected_w
        assert img.height == expected_h

    def test_level2_crop_dimensions_match_bbox(self) -> None:
        """Level-2 tile crop size must match the pixel dimensions of the tile bbox."""
        width, height = 1000, 1000
        image = _make_image(width, height)
        gen = TileGenerator(image, _make_metadata(width_px=width, height_px=height))
        pyramid = gen.generate()
        tile = pyramid.tile_at(2, 0, 0)
        assert tile is not None
        img = gen.get_tile_image(tile)
        expected_w = int(tile.bbox.x_max * width) - int(tile.bbox.x_min * width)
        expected_h = int(tile.bbox.y_max * height) - int(tile.bbox.y_min * height)
        assert img.width == expected_w
        assert img.height == expected_h
