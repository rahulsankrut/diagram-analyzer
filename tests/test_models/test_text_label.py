"""Tests for TextLabel model."""

import pytest
from pydantic import ValidationError

from src.models.ocr import BoundingBox
from src.models.text_label import TextLabel


class TestTextLabel:
    def _bbox(self) -> BoundingBox:
        return BoundingBox(x_min=0.1, y_min=0.1, x_max=0.3, y_max=0.2)

    def test_valid_creation(self) -> None:
        label = TextLabel(text="R1", bbox=self._bbox(), confidence=0.95)
        assert label.text == "R1"
        assert label.confidence == pytest.approx(0.95)
        assert label.page == 0

    def test_auto_uuid_label_id(self) -> None:
        l1 = TextLabel(text="A", bbox=self._bbox(), confidence=0.9)
        l2 = TextLabel(text="B", bbox=self._bbox(), confidence=0.9)
        assert l1.label_id != l2.label_id
        assert len(l1.label_id) == 36

    def test_default_page_is_zero(self) -> None:
        label = TextLabel(text="X", bbox=self._bbox(), confidence=0.8)
        assert label.page == 0

    def test_explicit_page(self) -> None:
        label = TextLabel(text="X", bbox=self._bbox(), confidence=0.8, page=2)
        assert label.page == 2

    def test_negative_page_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TextLabel(text="X", bbox=self._bbox(), confidence=0.8, page=-1)

    def test_confidence_above_1_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TextLabel(text="X", bbox=self._bbox(), confidence=1.1)

    def test_confidence_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TextLabel(text="X", bbox=self._bbox(), confidence=-0.01)

    def test_confidence_boundary_values_accepted(self) -> None:
        TextLabel(text="X", bbox=self._bbox(), confidence=0.0)
        TextLabel(text="X", bbox=self._bbox(), confidence=1.0)

    def test_to_dict_structure(self) -> None:
        label = TextLabel(text="VCC", bbox=self._bbox(), confidence=0.97)
        d = label.to_dict()
        assert "label_id" in d
        assert "text" in d
        assert d["text"] == "VCC"
        assert "bbox" in d
        assert "confidence" in d
        assert "page" in d

    def test_to_dict_bbox_is_nested_dict(self) -> None:
        label = TextLabel(text="GND", bbox=self._bbox(), confidence=0.9)
        d = label.to_dict()
        assert isinstance(d["bbox"], dict)
        assert "x_min" in d["bbox"]

    def test_serialization_roundtrip(self) -> None:
        original = TextLabel(
            text="Motor M-201",
            bbox=BoundingBox(x_min=0.5, y_min=0.5, x_max=0.8, y_max=0.6),
            confidence=0.88,
            page=0,
        )
        restored = TextLabel.model_validate_json(original.model_dump_json())
        assert restored == original
