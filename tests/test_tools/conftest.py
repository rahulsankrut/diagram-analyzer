"""Shared fixtures for tests/test_tools/.

Provides a pre-configured mock DiagramStore injected via
src.tools._store.configure_store() so every tool test has a consistent,
isolated data layer without touching real I/O.
"""

from __future__ import annotations

import src.tools._store as _store_module
import pytest
from PIL import Image
from unittest.mock import MagicMock

from src.models.component import Component, Pin
from src.models.diagram import DiagramMetadata
from src.models.ocr import BoundingBox
from src.models.text_label import TextLabel
from src.models.tiling import Tile, TilePyramid
from src.models.title_block import TitleBlock
from src.models.trace import Trace
from src.tools._store import DiagramStore, configure_store

# ---------------------------------------------------------------------------
# Stable IDs used across all tool tests
# ---------------------------------------------------------------------------

DIAGRAM_ID = "diag-0001"
COMP_A_ID = "comp-aaa"
COMP_B_ID = "comp-bbb"
PIN_A_ID = "pin-a-out"
PIN_B_ID = "pin-b-in"
LABEL_A_ID = "lbl-r1"
LABEL_B_ID = "lbl-vcc"
TRACE_ID = "trace-001"
TILE_L0_ID = f"{DIAGRAM_ID}_L0_R0_C0"
TILE_L2_ID = f"{DIAGRAM_ID}_L2_R0_C0"


# ---------------------------------------------------------------------------
# Diagram data helpers
# ---------------------------------------------------------------------------


def _make_metadata() -> DiagramMetadata:
    pin_a = Pin(pin_id=PIN_A_ID, name="OUT", position=(0.28, 0.31))
    pin_b = Pin(pin_id=PIN_B_ID, name="IN", position=(0.62, 0.31))

    comp_a = Component(
        component_id=COMP_A_ID,
        component_type="resistor",
        value="100Ω",
        package="0603",
        bbox=BoundingBox(x_min=0.12, y_min=0.25, x_max=0.28, y_max=0.37),
        pins=[pin_a],
        confidence=0.9,
    )
    comp_b = Component(
        component_id=COMP_B_ID,
        component_type="capacitor",
        value="10µF",
        bbox=BoundingBox(x_min=0.62, y_min=0.25, x_max=0.78, y_max=0.37),
        pins=[pin_b],
        confidence=0.88,
    )

    label_a = TextLabel(
        label_id=LABEL_A_ID,
        text="R1",
        bbox=BoundingBox(x_min=0.16, y_min=0.28, x_max=0.24, y_max=0.34),
        confidence=0.95,
    )
    label_b = TextLabel(
        label_id=LABEL_B_ID,
        text="VCC",
        bbox=BoundingBox(x_min=0.66, y_min=0.28, x_max=0.74, y_max=0.34),
        confidence=0.92,
    )

    trace = Trace(
        trace_id=TRACE_ID,
        from_component=COMP_A_ID,
        from_pin=PIN_A_ID,
        to_component=COMP_B_ID,
        to_pin=PIN_B_ID,
        path=[(0.28, 0.31), (0.45, 0.31), (0.62, 0.31)],
    )

    title_block = TitleBlock(
        drawing_id="DWG-001",
        title="Test Schematic",
        revision="A",
        scale="1:1",
        bbox=BoundingBox(x_min=0.69, y_min=0.80, x_max=0.99, y_max=0.99),
    )

    return DiagramMetadata(
        diagram_id=DIAGRAM_ID,
        source_filename="test_schematic.png",
        format="png",
        width_px=800,
        height_px=600,
        dpi=300,
        components=[comp_a, comp_b],
        text_labels=[label_a, label_b],
        traces=[trace],
        title_block=title_block,
    )


def _make_pyramid(metadata: DiagramMetadata) -> TilePyramid:
    pyramid = TilePyramid(diagram_id=DIAGRAM_ID)
    pyramid.tiles.append(
        Tile(
            tile_id=TILE_L0_ID,
            level=0,
            row=0,
            col=0,
            bbox=BoundingBox(x_min=0.001, y_min=0.001, x_max=0.999, y_max=0.999),
            component_ids=[COMP_A_ID, COMP_B_ID],
            text_label_ids=[LABEL_A_ID, LABEL_B_ID],
        )
    )
    pyramid.tiles.append(
        Tile(
            tile_id=TILE_L2_ID,
            level=2,
            row=0,
            col=0,
            bbox=BoundingBox(x_min=0.001, y_min=0.001, x_max=0.55, y_max=0.55),
            component_ids=[COMP_A_ID],
            text_label_ids=[LABEL_A_ID],
        )
    )
    return pyramid


def _white_image(w: int = 800, h: int = 600) -> Image.Image:
    return Image.new("RGB", (w, h), color="white")


# ---------------------------------------------------------------------------
# Mock store fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_store(request: pytest.FixtureRequest) -> MagicMock:
    """Return a MagicMock DiagramStore pre-wired with sample data."""
    metadata = _make_metadata()
    pyramid = _make_pyramid(metadata)
    tile_image = _white_image(256, 256)
    original_image = _white_image(800, 600)

    store = MagicMock(spec=DiagramStore)
    store.get_metadata.return_value = metadata
    store.get_pyramid.return_value = pyramid
    store.load_tile_image.return_value = tile_image
    store.load_original_image.return_value = original_image

    configure_store(store)
    yield store

    # Reset module-level store so tests don't bleed into each other.
    _store_module._instance = None


@pytest.fixture()
def store_no_pyramid(mock_store: MagicMock) -> MagicMock:
    """Store variant with no pyramid available."""
    mock_store.get_pyramid.return_value = None
    return mock_store


@pytest.fixture()
def store_no_image(mock_store: MagicMock) -> MagicMock:
    """Store variant with no original image available."""
    mock_store.load_tile_image.return_value = None
    mock_store.load_original_image.return_value = None
    return mock_store


@pytest.fixture()
def store_unknown_diagram() -> MagicMock:
    """Store that returns None for all get_metadata calls."""
    store = MagicMock(spec=DiagramStore)
    store.get_metadata.return_value = None
    store.get_pyramid.return_value = None
    store.load_tile_image.return_value = None
    store.load_original_image.return_value = None
    configure_store(store)
    yield store
    _store_module._instance = None
