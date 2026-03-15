"""Shared pytest fixtures for the CAD Diagram Analyzer test suite."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image, ImageDraw

from src.models import (
    BoundingBox,
    Component,
    CVResult,
    DiagramMetadata,
    OCRElement,
    OCRResult,
    Pin,
    Symbol,
    TextLabel,
    TitleBlock,
    Trace,
)


# ---------------------------------------------------------------------------
# Synthetic image fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sample_electrical_image(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a synthetic electrical schematic PNG for unit tests.

    Draws two labelled rectangles (components) connected by a horizontal line
    (trace), with a title block in the bottom-right corner.

    Returns:
        Path to the generated PNG file.
    """
    img = Image.new("RGB", (800, 600), color="white")
    draw = ImageDraw.Draw(img)

    # Component 1 — left
    draw.rectangle([100, 150, 220, 220], outline="black", width=3)
    draw.text((130, 170), "R1", fill="black")

    # Component 2 — right
    draw.rectangle([500, 150, 620, 220], outline="black", width=3)
    draw.text((530, 170), "R2", fill="black")

    # Trace connecting components
    draw.line([220, 185, 500, 185], fill="black", width=2)

    # Title block
    draw.rectangle([550, 480, 790, 590], outline="black", width=2)
    draw.text((560, 490), "DWG: TEST-001", fill="black")
    draw.text((560, 510), "REV: A", fill="black")
    draw.text((560, 530), "SCALE: 1:1", fill="black")

    tmp_dir = tmp_path_factory.mktemp("fixtures")
    img_path = tmp_dir / "sample_electrical.png"
    img.save(img_path, format="PNG")
    return img_path


@pytest.fixture
def small_white_image(tmp_path: Path) -> Path:
    """Return a path to a plain white 200×200 PNG."""
    img = Image.new("RGB", (200, 200), color="white")
    img_path = tmp_path / "white.png"
    img.save(img_path)
    return img_path


# ---------------------------------------------------------------------------
# BoundingBox fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_bbox() -> BoundingBox:
    """A normalized bounding box covering the centre of an image."""
    return BoundingBox(x_min=0.1, y_min=0.2, x_max=0.5, y_max=0.8)


# ---------------------------------------------------------------------------
# Component / Pin fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_pin() -> Pin:
    """A pin at the right edge of a component."""
    return Pin(pin_id="pin-1", name="OUT", position=(0.275, 0.308))


@pytest.fixture
def sample_component(sample_pin: Pin) -> Component:
    """A resistor component with one pin."""
    return Component(
        component_type="resistor",
        value="100Ω",
        package="0603",
        bbox=BoundingBox(x_min=0.125, y_min=0.25, x_max=0.275, y_max=0.367),
        pins=[sample_pin],
        confidence=0.9,
    )


# ---------------------------------------------------------------------------
# TextLabel fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_text_label() -> TextLabel:
    """A text label with high confidence."""
    return TextLabel(
        text="R1",
        bbox=BoundingBox(x_min=0.16, y_min=0.28, x_max=0.28, y_max=0.37),
        confidence=0.95,
    )


# ---------------------------------------------------------------------------
# Trace fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_trace() -> Trace:
    """A trace connecting two component pins with waypoints."""
    return Trace(
        from_component="comp-a",
        from_pin="pin-out",
        to_component="comp-b",
        to_pin="pin-in",
        path=[(0.275, 0.308), (0.400, 0.308), (0.625, 0.308)],
    )


# ---------------------------------------------------------------------------
# TitleBlock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_title_block() -> TitleBlock:
    """A populated title block."""
    return TitleBlock(
        drawing_id="TEST-001",
        title="Sample Electrical Schematic",
        sheet_number="1",
        sheet_total="1",
        revision="A",
        date="2026-02-23",
        author="Test Engineer",
        scale="1:1",
        zone_grid={"A1": "Power supply", "B2": "Control logic"},
        bbox=BoundingBox(x_min=0.688, y_min=0.80, x_max=0.988, y_max=0.983),
    )


# ---------------------------------------------------------------------------
# DiagramMetadata fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_diagram_metadata(
    sample_component: Component,
    sample_text_label: TextLabel,
    sample_trace: Trace,
    sample_title_block: TitleBlock,
) -> DiagramMetadata:
    """A DiagramMetadata with one component, one label, one trace, and a title block."""
    return DiagramMetadata(
        source_filename="test_schematic.png",
        format="png",
        width_px=800,
        height_px=600,
        dpi=300,
        components=[sample_component],
        text_labels=[sample_text_label],
        traces=[sample_trace],
        title_block=sample_title_block,
    )


# ---------------------------------------------------------------------------
# OCR / CV raw model fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_ocr_result() -> OCRResult:
    """OCR result with two text elements at known positions."""
    return OCRResult(
        elements=[
            OCRElement(
                text="R1",
                confidence=0.95,
                bbox=BoundingBox(x_min=0.16, y_min=0.28, x_max=0.28, y_max=0.37),
                page=0,
            ),
            OCRElement(
                text="R2",
                confidence=0.93,
                bbox=BoundingBox(x_min=0.66, y_min=0.28, x_max=0.78, y_max=0.37),
                page=0,
            ),
        ]
    )


@pytest.fixture
def sample_cv_result() -> CVResult:
    """CV result with two detected symbols and no lines."""
    return CVResult(
        symbols=[
            Symbol(
                symbol_type="resistor",
                bbox=BoundingBox(x_min=0.125, y_min=0.25, x_max=0.275, y_max=0.367),
                confidence=0.82,
            ),
            Symbol(
                symbol_type="resistor",
                bbox=BoundingBox(x_min=0.625, y_min=0.25, x_max=0.775, y_max=0.367),
                confidence=0.80,
            ),
        ]
    )


# ---------------------------------------------------------------------------
# GCP mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gcs_client() -> MagicMock:
    """A MagicMock standing in for ``google.cloud.storage.Client``."""
    client = MagicMock()
    blob = MagicMock()
    blob.upload_from_string = MagicMock()
    blob.download_as_bytes = MagicMock(return_value=b"fake-image-bytes")
    bucket = MagicMock()
    bucket.blob.return_value = blob
    client.bucket.return_value = bucket
    return client


@pytest.fixture
def mock_firestore_client() -> AsyncMock:
    """An AsyncMock standing in for ``google.cloud.firestore.AsyncClient``."""
    client = AsyncMock()
    doc_ref = AsyncMock()
    snapshot = MagicMock()
    snapshot.exists = True
    snapshot.to_dict.return_value = {"status": "complete"}
    doc_ref.get = AsyncMock(return_value=snapshot)
    doc_ref.set = AsyncMock()
    doc_ref.update = AsyncMock()
    collection = MagicMock()
    collection.document.return_value = doc_ref
    client.collection.return_value = collection
    return client
