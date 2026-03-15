"""Tests for DiagramMetadata — aggregation model and helper methods."""

import pytest
from pydantic import ValidationError

from src.models.component import Component
from src.models.diagram import DiagramMetadata, IngestionRequest, IngestionResult
from src.models.ocr import BoundingBox
from src.models.text_label import TextLabel
from src.models.title_block import TitleBlock
from src.models.trace import Trace


def _bbox(x_min: float, y_min: float, x_max: float, y_max: float) -> BoundingBox:
    return BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)


class TestDiagramMetadataCreation:
    def test_minimal_creation(self) -> None:
        meta = DiagramMetadata(
            source_filename="schematic.png",
            format="png",
            width_px=800,
            height_px=600,
        )
        assert meta.source_filename == "schematic.png"
        assert meta.format == "png"
        assert meta.dpi == 300  # default
        assert meta.components == []
        assert meta.text_labels == []
        assert meta.traces == []
        assert meta.title_block is None

    def test_auto_uuid_diagram_id(self) -> None:
        a = DiagramMetadata(source_filename="a.png", format="png", width_px=100, height_px=100)
        b = DiagramMetadata(source_filename="b.png", format="png", width_px=100, height_px=100)
        assert a.diagram_id != b.diagram_id
        assert len(a.diagram_id) == 36

    def test_invalid_format_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiagramMetadata(
                source_filename="x.bmp",
                format="bmp",  # type: ignore[arg-type]
                width_px=100,
                height_px=100,
            )

    def test_zero_width_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiagramMetadata(
                source_filename="x.png", format="png", width_px=0, height_px=100
            )

    def test_negative_height_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiagramMetadata(
                source_filename="x.png", format="png", width_px=100, height_px=-1
            )

    def test_created_at_is_utc(self) -> None:
        import datetime

        meta = DiagramMetadata(
            source_filename="x.png", format="png", width_px=100, height_px=100
        )
        assert meta.created_at.tzinfo is not None
        assert meta.created_at.tzinfo == datetime.UTC

    def test_with_all_content(
        self,
        sample_diagram_metadata: DiagramMetadata,
    ) -> None:
        assert len(sample_diagram_metadata.components) == 1
        assert len(sample_diagram_metadata.text_labels) == 1
        assert len(sample_diagram_metadata.traces) == 1
        assert sample_diagram_metadata.title_block is not None


class TestGetComponent:
    def test_found(self, sample_diagram_metadata: DiagramMetadata) -> None:
        comp = sample_diagram_metadata.components[0]
        result = sample_diagram_metadata.get_component(comp.component_id)
        assert result is not None
        assert result.component_id == comp.component_id

    def test_not_found(self, sample_diagram_metadata: DiagramMetadata) -> None:
        result = sample_diagram_metadata.get_component("nonexistent-id")
        assert result is None

    def test_empty_components_returns_none(self) -> None:
        meta = DiagramMetadata(
            source_filename="x.png", format="png", width_px=100, height_px=100
        )
        assert meta.get_component("any-id") is None


class TestComponentsInBBox:
    def _meta_with_two_components(self) -> DiagramMetadata:
        left = Component(
            bbox=_bbox(0.10, 0.10, 0.30, 0.30),
            component_type="resistor",
        )
        right = Component(
            bbox=_bbox(0.70, 0.70, 0.90, 0.90),
            component_type="resistor",
        )
        return DiagramMetadata(
            source_filename="t.png",
            format="png",
            width_px=100,
            height_px=100,
            components=[left, right],
        )

    def test_query_captures_left_only(self) -> None:
        meta = self._meta_with_two_components()
        query = _bbox(0.0, 0.0, 0.5, 0.5)
        results = meta.components_in_bbox(query)
        assert len(results) == 1
        # centroid of left is (0.20, 0.20) → inside [0,0.5]×[0,0.5]
        assert results[0].component_type == "resistor"

    def test_query_captures_both(self) -> None:
        meta = self._meta_with_two_components()
        query = _bbox(0.0, 0.0, 1.0, 1.0)  # full image
        assert len(meta.components_in_bbox(query)) == 2

    def test_query_captures_none(self) -> None:
        meta = self._meta_with_two_components()
        # narrow strip in the middle — neither centroid is there
        query = _bbox(0.45, 0.45, 0.55, 0.55)
        assert meta.components_in_bbox(query) == []

    def test_empty_diagram_returns_empty(self) -> None:
        meta = DiagramMetadata(
            source_filename="x.png", format="png", width_px=100, height_px=100
        )
        assert meta.components_in_bbox(_bbox(0.0, 0.0, 1.0, 1.0)) == []


class TestTextLabelsInBBox:
    def test_finds_label_in_region(self) -> None:
        label = TextLabel(
            text="V-101",
            bbox=_bbox(0.20, 0.20, 0.40, 0.30),
            confidence=0.9,
        )
        meta = DiagramMetadata(
            source_filename="x.png",
            format="png",
            width_px=100,
            height_px=100,
            text_labels=[label],
        )
        # centroid is (0.30, 0.25)
        results = meta.text_labels_in_bbox(_bbox(0.0, 0.0, 0.5, 0.5))
        assert len(results) == 1
        assert results[0].text == "V-101"

    def test_returns_empty_when_outside(self) -> None:
        label = TextLabel(
            text="V-101",
            bbox=_bbox(0.70, 0.70, 0.90, 0.90),
            confidence=0.9,
        )
        meta = DiagramMetadata(
            source_filename="x.png",
            format="png",
            width_px=100,
            height_px=100,
            text_labels=[label],
        )
        results = meta.text_labels_in_bbox(_bbox(0.0, 0.0, 0.5, 0.5))
        assert results == []


class TestToDict:
    def test_has_top_level_keys(self, sample_diagram_metadata: DiagramMetadata) -> None:
        d = sample_diagram_metadata.to_dict()
        for key in ("diagram_id", "source_filename", "format", "width_px", "height_px",
                    "components", "text_labels", "traces", "title_block", "created_at"):
            assert key in d

    def test_components_is_list_of_dicts(self, sample_diagram_metadata: DiagramMetadata) -> None:
        d = sample_diagram_metadata.to_dict()
        assert isinstance(d["components"], list)
        assert isinstance(d["components"][0], dict)

    def test_created_at_is_string(self, sample_diagram_metadata: DiagramMetadata) -> None:
        # model_dump(mode='json') serializes datetime as ISO string
        d = sample_diagram_metadata.to_dict()
        assert isinstance(d["created_at"], str)


class TestSerializationRoundtrip:
    def test_minimal_roundtrip(self) -> None:
        original = DiagramMetadata(
            source_filename="schema.png",
            format="pdf",
            width_px=2480,
            height_px=3508,
        )
        restored = DiagramMetadata.model_validate_json(original.model_dump_json())
        assert restored.diagram_id == original.diagram_id
        assert restored.format == original.format

    def test_full_roundtrip(self, sample_diagram_metadata: DiagramMetadata) -> None:
        json_str = sample_diagram_metadata.model_dump_json()
        restored = DiagramMetadata.model_validate_json(json_str)
        assert restored.diagram_id == sample_diagram_metadata.diagram_id
        assert len(restored.components) == len(sample_diagram_metadata.components)
        assert len(restored.traces) == len(sample_diagram_metadata.traces)
        assert restored.title_block is not None
        assert restored.title_block.drawing_id == sample_diagram_metadata.title_block.drawing_id  # type: ignore[union-attr]


class TestIngestionModels:
    def test_request_default_diagram_type(self) -> None:
        req = IngestionRequest(source_uri="gs://bucket/file.png", requester_id="user-1")
        assert req.diagram_type == "unknown"

    def test_request_explicit_type(self) -> None:
        req = IngestionRequest(
            source_uri="gs://bucket/pid.pdf",
            diagram_type="pid",
            requester_id="user-2",
        )
        assert req.diagram_type == "pid"

    def test_result_no_error(self) -> None:
        meta = DiagramMetadata(
            source_filename="f.png", format="png", width_px=100, height_px=100
        )
        result = IngestionResult(metadata=meta, success=True)
        assert result.error_message is None

    def test_result_with_error(self) -> None:
        meta = DiagramMetadata(
            source_filename="f.png", format="png", width_px=100, height_px=100
        )
        result = IngestionResult(
            metadata=meta, success=False, error_message="OCR failed"
        )
        assert result.success is False
        assert result.error_message == "OCR failed"
