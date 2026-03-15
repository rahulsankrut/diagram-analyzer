"""Tests for BoundingBox — normalized coordinates, conversions, and spatial ops."""

import pytest
from pydantic import ValidationError

from src.models.ocr import BoundingBox


class TestCreation:
    def test_valid_normalized_coords(self) -> None:
        bbox = BoundingBox(x_min=0.1, y_min=0.2, x_max=0.5, y_max=0.8)
        assert bbox.x_min == pytest.approx(0.1)
        assert bbox.y_max == pytest.approx(0.8)

    def test_full_image_bbox_is_valid(self) -> None:
        bbox = BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0)
        assert bbox.area() == pytest.approx(1.0)

    def test_negative_x_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BoundingBox(x_min=-0.1, y_min=0.0, x_max=0.5, y_max=0.5)

    def test_x_max_greater_than_1_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BoundingBox(x_min=0.0, y_min=0.0, x_max=1.5, y_max=0.5)

    def test_pixel_coords_rejected(self) -> None:
        # Values > 1.0 are pixel coords — BoundingBox must be normalized
        with pytest.raises(ValidationError):
            BoundingBox(x_min=0, y_min=0, x_max=800, y_max=600)

    def test_x_max_equal_to_x_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BoundingBox(x_min=0.3, y_min=0.0, x_max=0.3, y_max=0.5)

    def test_x_max_less_than_x_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BoundingBox(x_min=0.6, y_min=0.0, x_max=0.2, y_max=0.5)

    def test_y_max_equal_to_y_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BoundingBox(x_min=0.0, y_min=0.4, x_max=0.5, y_max=0.4)

    def test_y_max_less_than_y_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BoundingBox(x_min=0.0, y_min=0.8, x_max=0.5, y_max=0.2)


class TestFromPixelCoords:
    def test_basic_conversion(self) -> None:
        bbox = BoundingBox.from_pixel_coords(100, 150, 400, 450, width=800, height=600)
        assert bbox.x_min == pytest.approx(0.125)
        assert bbox.y_min == pytest.approx(0.25)
        assert bbox.x_max == pytest.approx(0.5)
        assert bbox.y_max == pytest.approx(0.75)

    def test_full_image(self) -> None:
        bbox = BoundingBox.from_pixel_coords(0, 0, 1920, 1080, width=1920, height=1080)
        assert bbox.x_min == pytest.approx(0.0)
        assert bbox.y_min == pytest.approx(0.0)
        assert bbox.x_max == pytest.approx(1.0)
        assert bbox.y_max == pytest.approx(1.0)

    def test_zero_dimension_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            BoundingBox.from_pixel_coords(0, 0, 100, 100, width=0, height=100)

    def test_roundtrip_with_to_pixel_coords(self) -> None:
        original = BoundingBox(x_min=0.125, y_min=0.25, x_max=0.5, y_max=0.75)
        px = original.to_pixel_coords(800, 600)
        restored = BoundingBox.from_pixel_coords(*px, width=800, height=600)
        assert restored.x_min == pytest.approx(original.x_min)
        assert restored.y_min == pytest.approx(original.y_min)
        assert restored.x_max == pytest.approx(original.x_max)
        assert restored.y_max == pytest.approx(original.y_max)


class TestToPixelCoords:
    def test_square_image(self) -> None:
        bbox = BoundingBox(x_min=0.1, y_min=0.2, x_max=0.5, y_max=0.8)
        assert bbox.to_pixel_coords(1000, 1000) == (100, 200, 500, 800)

    def test_non_square_image(self) -> None:
        bbox = BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0)
        assert bbox.to_pixel_coords(800, 600) == (0, 0, 800, 600)

    def test_returns_integers(self) -> None:
        bbox = BoundingBox(x_min=0.1, y_min=0.1, x_max=0.9, y_max=0.9)
        result = bbox.to_pixel_coords(100, 100)
        assert all(isinstance(v, int) for v in result)


class TestCenter:
    def test_center_of_full_image(self) -> None:
        bbox = BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0)
        assert bbox.center() == pytest.approx((0.5, 0.5))

    def test_center_of_small_box(self) -> None:
        bbox = BoundingBox(x_min=0.2, y_min=0.3, x_max=0.6, y_max=0.7)
        cx, cy = bbox.center()
        assert cx == pytest.approx(0.4)
        assert cy == pytest.approx(0.5)


class TestArea:
    def test_unit_square(self) -> None:
        bbox = BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0)
        assert bbox.area() == pytest.approx(1.0)

    def test_half_width_half_height(self) -> None:
        bbox = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.5, y_max=0.5)
        assert bbox.area() == pytest.approx(0.25)

    def test_thin_horizontal_strip(self) -> None:
        bbox = BoundingBox(x_min=0.0, y_min=0.4, x_max=1.0, y_max=0.6)
        assert bbox.area() == pytest.approx(0.2)


class TestOverlaps:
    def test_clearly_overlapping(self) -> None:
        a = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.6, y_max=0.6)
        b = BoundingBox(x_min=0.4, y_min=0.4, x_max=1.0, y_max=1.0)
        assert a.overlaps(b) is True

    def test_clearly_separate(self) -> None:
        a = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.3, y_max=0.3)
        b = BoundingBox(x_min=0.7, y_min=0.7, x_max=1.0, y_max=1.0)
        assert a.overlaps(b) is False

    def test_edge_touch_not_overlap(self) -> None:
        # Boxes share x_max==x_min boundary — not considered overlap
        a = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.5, y_max=1.0)
        b = BoundingBox(x_min=0.5, y_min=0.0, x_max=1.0, y_max=1.0)
        assert a.overlaps(b) is False

    def test_containment_is_overlap(self) -> None:
        outer = BoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0)
        inner = BoundingBox(x_min=0.3, y_min=0.3, x_max=0.7, y_max=0.7)
        assert outer.overlaps(inner) is True
        assert inner.overlaps(outer) is True


class TestIoU:
    def test_identical_boxes(self) -> None:
        bbox = BoundingBox(x_min=0.1, y_min=0.1, x_max=0.5, y_max=0.5)
        assert bbox.iou(bbox) == pytest.approx(1.0)

    def test_no_overlap(self) -> None:
        a = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.3, y_max=0.3)
        b = BoundingBox(x_min=0.7, y_min=0.7, x_max=1.0, y_max=1.0)
        assert a.iou(b) == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        # Two 0.4×0.4 boxes overlapping in a 0.2×0.2 region
        a = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.4, y_max=0.4)
        b = BoundingBox(x_min=0.2, y_min=0.2, x_max=0.6, y_max=0.6)
        # intersection=0.04, union=0.32-0.04=0.28? let me compute:
        # area_a=0.16, area_b=0.16, inter=(0.4-0.2)*(0.4-0.2)=0.04
        # union=0.16+0.16-0.04=0.28, iou=0.04/0.28≈0.1429
        assert 0.0 < a.iou(b) < 1.0


class TestToDict:
    def test_has_expected_keys(self) -> None:
        bbox = BoundingBox(x_min=0.1, y_min=0.2, x_max=0.5, y_max=0.8)
        d = bbox.to_dict()
        assert set(d.keys()) == {"x_min", "y_min", "x_max", "y_max"}

    def test_values_match(self) -> None:
        bbox = BoundingBox(x_min=0.1, y_min=0.2, x_max=0.5, y_max=0.8)
        d = bbox.to_dict()
        assert d["x_min"] == pytest.approx(0.1)
        assert d["y_min"] == pytest.approx(0.2)
        assert d["x_max"] == pytest.approx(0.5)
        assert d["y_max"] == pytest.approx(0.8)


class TestSerializationRoundtrip:
    def test_json_roundtrip(self) -> None:
        original = BoundingBox(x_min=0.1, y_min=0.2, x_max=0.5, y_max=0.8)
        json_str = original.model_dump_json()
        restored = BoundingBox.model_validate_json(json_str)
        assert restored == original

    def test_dict_roundtrip(self) -> None:
        original = BoundingBox(x_min=0.1, y_min=0.2, x_max=0.5, y_max=0.8)
        restored = BoundingBox.model_validate(original.to_dict())
        assert restored == original
