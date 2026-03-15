"""Tests for TitleBlock model."""

import pytest
from pydantic import ValidationError

from src.models.ocr import BoundingBox
from src.models.title_block import TitleBlock


class TestTitleBlock:
    def test_minimal_creation_all_defaults(self) -> None:
        tb = TitleBlock()
        assert tb.drawing_id == ""
        assert tb.title == ""
        assert tb.sheet_number == "1"
        assert tb.sheet_total == "1"
        assert tb.revision == ""
        assert tb.date == ""
        assert tb.author == ""
        assert tb.scale == ""
        assert tb.zone_grid == {}
        assert tb.bbox is None

    def test_full_creation(self) -> None:
        bbox = BoundingBox(x_min=0.7, y_min=0.85, x_max=0.99, y_max=0.99)
        tb = TitleBlock(
            drawing_id="P-001",
            title="Process Flow Diagram",
            sheet_number="2",
            sheet_total="5",
            revision="C",
            date="2026-02-23",
            author="Jane Doe",
            scale="1:50",
            zone_grid={"A1": "Feed section", "B2": "Reaction loop"},
            bbox=bbox,
        )
        assert tb.drawing_id == "P-001"
        assert tb.revision == "C"
        assert tb.scale == "1:50"
        assert tb.zone_grid["A1"] == "Feed section"
        assert tb.bbox is not None

    def test_zone_grid_is_string_mapping(self) -> None:
        tb = TitleBlock(zone_grid={"Z1": "Boiler", "Z2": "Condenser"})
        assert isinstance(tb.zone_grid, dict)
        assert tb.zone_grid["Z1"] == "Boiler"

    def test_empty_zone_grid_by_default(self) -> None:
        tb = TitleBlock()
        assert tb.zone_grid == {}

    def test_optional_bbox_none_by_default(self) -> None:
        tb = TitleBlock(drawing_id="DWG-002")
        assert tb.bbox is None

    def test_bbox_validated_as_normalized(self) -> None:
        # pixel coords should be rejected by BoundingBox validation
        with pytest.raises(ValidationError):
            TitleBlock(
                bbox=BoundingBox(  # type: ignore[arg-type]
                    x_min=500,  # type: ignore[arg-type]
                    y_min=400,
                    x_max=800,
                    y_max=600,
                )
            )

    def test_to_dict_structure(self) -> None:
        tb = TitleBlock(drawing_id="X-001", revision="B")
        d = tb.to_dict()
        assert d["drawing_id"] == "X-001"
        assert d["revision"] == "B"
        assert "zone_grid" in d
        assert d["bbox"] is None

    def test_to_dict_bbox_expanded(self) -> None:
        bbox = BoundingBox(x_min=0.7, y_min=0.8, x_max=0.99, y_max=0.99)
        tb = TitleBlock(bbox=bbox)
        d = tb.to_dict()
        assert isinstance(d["bbox"], dict)
        assert "x_min" in d["bbox"]

    def test_serialization_roundtrip_without_bbox(self) -> None:
        original = TitleBlock(
            drawing_id="D-100",
            title="Motor Control Panel",
            revision="A",
            date="2026-01-15",
        )
        restored = TitleBlock.model_validate_json(original.model_dump_json())
        assert restored == original

    def test_serialization_roundtrip_with_bbox(self) -> None:
        original = TitleBlock(
            drawing_id="D-200",
            zone_grid={"R1": "Pump station"},
            bbox=BoundingBox(x_min=0.75, y_min=0.88, x_max=0.99, y_max=0.99),
        )
        restored = TitleBlock.model_validate_json(original.model_dump_json())
        assert restored == original
