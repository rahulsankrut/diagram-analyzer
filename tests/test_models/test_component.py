"""Tests for Pin and Component models."""

import pytest
from pydantic import ValidationError

from src.models.component import Component, Pin
from src.models.ocr import BoundingBox


class TestPin:
    def test_valid_creation(self) -> None:
        pin = Pin(pin_id="p1", name="VCC", position=(0.5, 0.5))
        assert pin.pin_id == "p1"
        assert pin.name == "VCC"
        assert pin.position == (0.5, 0.5)

    def test_default_name_empty(self) -> None:
        pin = Pin(position=(0.1, 0.9))
        assert pin.name == ""

    def test_auto_uuid_pin_id(self) -> None:
        p1 = Pin(position=(0.1, 0.1))
        p2 = Pin(position=(0.2, 0.2))
        assert p1.pin_id != p2.pin_id
        assert len(p1.pin_id) == 36  # UUID string length

    def test_position_at_edges_valid(self) -> None:
        # Corners of the image are valid pin positions
        for pos in [(0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0)]:
            pin = Pin(position=pos)
            assert pin.position == pos

    def test_position_x_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Pin(position=(-0.1, 0.5))

    def test_position_y_greater_than_1_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Pin(position=(0.5, 1.5))

    def test_to_dict_has_required_keys(self) -> None:
        pin = Pin(pin_id="p1", name="OUT", position=(0.3, 0.4))
        d = pin.to_dict()
        assert "pin_id" in d
        assert "name" in d
        assert "position" in d

    def test_to_dict_position_is_list(self) -> None:
        # model_dump(mode='json') converts tuples to lists
        pin = Pin(position=(0.3, 0.4))
        d = pin.to_dict()
        assert d["position"] == [0.3, 0.4]

    def test_serialization_roundtrip(self) -> None:
        original = Pin(pin_id="p1", name="GND", position=(0.25, 0.75))
        restored = Pin.model_validate_json(original.model_dump_json())
        assert restored == original


class TestComponent:
    def _bbox(self) -> BoundingBox:
        return BoundingBox(x_min=0.1, y_min=0.2, x_max=0.4, y_max=0.5)

    def test_minimal_creation(self) -> None:
        comp = Component(bbox=self._bbox())
        assert comp.component_type == "unknown"
        assert comp.value == ""
        assert comp.package == ""
        assert comp.pins == []
        assert comp.confidence == pytest.approx(1.0)

    def test_full_creation(self) -> None:
        pin = Pin(pin_id="p1", name="1", position=(0.1, 0.35))
        comp = Component(
            component_type="resistor",
            value="100Ω",
            package="0603",
            bbox=self._bbox(),
            pins=[pin],
            confidence=0.92,
        )
        assert comp.component_type == "resistor"
        assert comp.value == "100Ω"
        assert comp.package == "0603"
        assert len(comp.pins) == 1
        assert comp.confidence == pytest.approx(0.92)

    def test_auto_uuid_component_id(self) -> None:
        c1 = Component(bbox=self._bbox())
        c2 = Component(bbox=self._bbox())
        assert c1.component_id != c2.component_id
        assert len(c1.component_id) == 36

    def test_confidence_above_1_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Component(bbox=self._bbox(), confidence=1.1)

    def test_confidence_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Component(bbox=self._bbox(), confidence=-0.1)

    def test_confidence_boundary_values_accepted(self) -> None:
        Component(bbox=self._bbox(), confidence=0.0)
        Component(bbox=self._bbox(), confidence=1.0)

    def test_to_dict_structure(self) -> None:
        comp = Component(
            component_type="valve",
            value="2-inch gate valve",
            bbox=self._bbox(),
        )
        d = comp.to_dict()
        assert "component_id" in d
        assert "component_type" in d
        assert d["component_type"] == "valve"
        assert "bbox" in d
        assert "pins" in d

    def test_to_dict_bbox_is_nested_dict(self) -> None:
        comp = Component(bbox=self._bbox())
        d = comp.to_dict()
        assert isinstance(d["bbox"], dict)
        assert "x_min" in d["bbox"]

    def test_to_dict_pins_are_list_of_dicts(self) -> None:
        pin = Pin(pin_id="p1", name="A", position=(0.1, 0.3))
        comp = Component(bbox=self._bbox(), pins=[pin])
        d = comp.to_dict()
        assert isinstance(d["pins"], list)
        assert isinstance(d["pins"][0], dict)
        assert d["pins"][0]["pin_id"] == "p1"

    def test_serialization_roundtrip(self) -> None:
        pin = Pin(pin_id="p1", name="GND", position=(0.1, 0.3))
        original = Component(
            component_type="capacitor",
            value="10µF",
            package="0805",
            bbox=self._bbox(),
            pins=[pin],
            confidence=0.85,
        )
        restored = Component.model_validate_json(original.model_dump_json())
        assert restored == original
