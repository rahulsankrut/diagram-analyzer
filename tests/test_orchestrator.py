"""Tests for src/orchestrator.py.

Covers:
- InMemoryDiagramStore CRUD operations and the DiagramStore read interface.
- Orchestrator.ingest() — pipeline invoked, tiles generated and stored,
  metadata / pyramid / original image persisted.
- Orchestrator.ingest_and_analyze() — delegates to agent.analyze() with the
  correct diagram_id; raises RuntimeError when no agent is configured.
- Orchestrator.analyze() sync wrapper — calls asyncio.run internally.
- Orchestrator.create_local() — builds a fully wired instance; handles missing
  ADK gracefully.
- configure_store() integration — after Orchestrator construction, tool
  functions can resolve the store via get_store().
"""

from __future__ import annotations

import asyncio
import io
import src.tools._store as _store_module

import pytest
from PIL import Image
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.component import Component, Pin
from src.models.diagram import DiagramMetadata
from src.models.ocr import BoundingBox
from src.models.text_label import TextLabel
from src.models.tiling import Tile, TilePyramid
from src.models.title_block import TitleBlock
from src.models.trace import Trace
from src.orchestrator import InMemoryDiagramStore, Orchestrator, _load_image
from src.tiling.tile_storage import TileStorage
from src.tools._store import get_store

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DIAGRAM_ID = "orch-test-0001"


def _make_image_bytes(w: int = 100, h: int = 100, color: str = "white") -> bytes:
    """Return valid PNG bytes for a small synthetic image."""
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color=color).save(buf, format="PNG")
    return buf.getvalue()


def _make_metadata() -> DiagramMetadata:
    """Return a fresh DiagramMetadata with a stable diagram_id."""
    return DiagramMetadata(
        diagram_id=DIAGRAM_ID,
        source_filename="initial.png",
        format="png",
        width_px=100,
        height_px=100,
        components=[
            Component(
                component_id="comp-1",
                component_type="resistor",
                bbox=BoundingBox(x_min=0.1, y_min=0.1, x_max=0.3, y_max=0.3),
            )
        ],
        text_labels=[
            TextLabel(
                text="R1",
                bbox=BoundingBox(x_min=0.1, y_min=0.1, x_max=0.25, y_max=0.25),
                confidence=0.95,
            )
        ],
        title_block=TitleBlock(drawing_id="DWG-TEST"),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_store():
    """Reset the global DiagramStore singleton after every test."""
    yield
    _store_module._instance = None


@pytest.fixture()
def mock_pipeline() -> MagicMock:
    """Mock PreprocessingPipeline that returns a fresh metadata on each call."""
    pipeline = MagicMock()
    pipeline.run = AsyncMock(side_effect=lambda _img: _make_metadata())
    return pipeline


@pytest.fixture()
def mock_tile_storage() -> MagicMock:
    """Mock TileStorage that records save() calls and returns a fake path."""
    storage = MagicMock(spec=TileStorage)
    storage.save.return_value = "/tmp/fake-tile.png"
    return storage


@pytest.fixture()
def store() -> InMemoryDiagramStore:
    return InMemoryDiagramStore()


@pytest.fixture()
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.analyze.return_value = "Diagram has 1 resistor."
    return agent


@pytest.fixture()
def orchestrator(
    mock_pipeline: MagicMock,
    mock_tile_storage: MagicMock,
    store: InMemoryDiagramStore,
    mock_agent: MagicMock,
) -> Orchestrator:
    return Orchestrator(
        preprocessing_pipeline=mock_pipeline,
        tile_storage=mock_tile_storage,
        store=store,
        agent=mock_agent,
    )


# ---------------------------------------------------------------------------
# InMemoryDiagramStore: read / write interface
# ---------------------------------------------------------------------------


class TestInMemoryDiagramStore:
    def test_get_metadata_returns_none_when_absent(self) -> None:
        assert InMemoryDiagramStore().get_metadata("missing") is None

    def test_put_and_get_metadata(self) -> None:
        store = InMemoryDiagramStore()
        md = _make_metadata()
        store.put_metadata(md)
        assert store.get_metadata(DIAGRAM_ID) is md

    def test_get_pyramid_returns_none_when_absent(self) -> None:
        assert InMemoryDiagramStore().get_pyramid("missing") is None

    def test_put_and_get_pyramid(self) -> None:
        store = InMemoryDiagramStore()
        pyramid = TilePyramid(diagram_id=DIAGRAM_ID)
        store.put_pyramid(pyramid)
        assert store.get_pyramid(DIAGRAM_ID) is pyramid

    def test_load_tile_image_returns_none_when_absent(self) -> None:
        tile = Tile(
            tile_id="t1",
            level=0,
            row=0,
            col=0,
            bbox=BoundingBox(x_min=0.01, y_min=0.01, x_max=0.99, y_max=0.99),
        )
        assert InMemoryDiagramStore().load_tile_image(tile) is None

    def test_put_and_load_tile_image(self) -> None:
        store = InMemoryDiagramStore()
        tile = Tile(
            tile_id="t1",
            level=0,
            row=0,
            col=0,
            bbox=BoundingBox(x_min=0.01, y_min=0.01, x_max=0.99, y_max=0.99),
        )
        img = Image.new("RGB", (64, 64))
        store.put_tile_image("t1", img)
        assert store.load_tile_image(tile) is img

    def test_load_original_image_returns_none_when_absent(self) -> None:
        assert InMemoryDiagramStore().load_original_image("missing") is None

    def test_put_and_load_original_image(self) -> None:
        store = InMemoryDiagramStore()
        img = Image.new("RGB", (100, 100))
        store.put_original_image(DIAGRAM_ID, img)
        assert store.load_original_image(DIAGRAM_ID) is img

    def test_diagram_count(self) -> None:
        store = InMemoryDiagramStore()
        store.put_metadata(_make_metadata())
        assert store.diagram_count == 1

    def test_overwrite_metadata(self) -> None:
        store = InMemoryDiagramStore()
        md1 = _make_metadata()
        md2 = md1.model_copy(update={"source_filename": "updated.png"})
        store.put_metadata(md1)
        store.put_metadata(md2)
        assert store.get_metadata(DIAGRAM_ID).source_filename == "updated.png"


# ---------------------------------------------------------------------------
# _load_image helper
# ---------------------------------------------------------------------------


def test_load_image_from_bytes() -> None:
    raw = _make_image_bytes()
    img, name = _load_image(raw, "my-diagram.png")
    assert img.size == (100, 100)
    assert name == "my-diagram.png"


def test_load_image_from_path(tmp_path: pytest.TempPathFactory) -> None:
    p = tmp_path / "schematic.png"
    Image.new("RGB", (50, 50)).save(p)
    img, name = _load_image(p, "ignored.png")
    assert img.size == (50, 50)
    assert name == "schematic.png"  # inferred from path, not fallback


def test_load_image_converts_to_rgb(tmp_path: pytest.TempPathFactory) -> None:
    p = tmp_path / "gray.png"
    Image.new("L", (20, 20)).save(p)
    img, _ = _load_image(p, "gray.png")
    assert img.mode == "RGB"


# ---------------------------------------------------------------------------
# Orchestrator.ingest()
# ---------------------------------------------------------------------------


async def test_ingest_returns_diagram_id(orchestrator: Orchestrator) -> None:
    diagram_id = await orchestrator.ingest(_make_image_bytes())
    assert diagram_id == DIAGRAM_ID


async def test_ingest_calls_pipeline_once(
    orchestrator: Orchestrator,
    mock_pipeline: MagicMock,
) -> None:
    await orchestrator.ingest(_make_image_bytes())
    mock_pipeline.run.assert_awaited_once()


async def test_ingest_stores_metadata(
    orchestrator: Orchestrator,
    store: InMemoryDiagramStore,
) -> None:
    diagram_id = await orchestrator.ingest(_make_image_bytes())
    assert store.get_metadata(diagram_id) is not None


async def test_ingest_stores_pyramid(
    orchestrator: Orchestrator,
    store: InMemoryDiagramStore,
) -> None:
    diagram_id = await orchestrator.ingest(_make_image_bytes())
    pyramid = store.get_pyramid(diagram_id)
    assert pyramid is not None
    assert len(pyramid.tiles) > 0


async def test_ingest_stores_original_image(
    orchestrator: Orchestrator,
    store: InMemoryDiagramStore,
) -> None:
    diagram_id = await orchestrator.ingest(_make_image_bytes())
    assert store.load_original_image(diagram_id) is not None


async def test_ingest_saves_tiles_via_storage(
    orchestrator: Orchestrator,
    mock_tile_storage: MagicMock,
) -> None:
    """TileGenerator builds 1+4+16=21 tiles for three levels."""
    await orchestrator.ingest(_make_image_bytes())
    assert mock_tile_storage.save.call_count == 21


async def test_ingest_tile_images_cached_in_store(
    orchestrator: Orchestrator,
    store: InMemoryDiagramStore,
) -> None:
    diagram_id = await orchestrator.ingest(_make_image_bytes())
    pyramid = store.get_pyramid(diagram_id)
    assert pyramid is not None
    # Every tile should have a cached image in the store
    for tile in pyramid.tiles:
        assert store.load_tile_image(tile) is not None


async def test_ingest_updates_tile_image_path(
    orchestrator: Orchestrator,
    store: InMemoryDiagramStore,
    mock_tile_storage: MagicMock,
) -> None:
    """Each tile's image_path is set to the value returned by tile_storage.save()."""
    mock_tile_storage.save.return_value = "/data/tiles/t.png"
    diagram_id = await orchestrator.ingest(_make_image_bytes())
    pyramid = store.get_pyramid(diagram_id)
    assert pyramid is not None
    for tile in pyramid.tiles:
        assert tile.image_path == "/data/tiles/t.png"


async def test_ingest_sets_source_filename_from_bytes(
    orchestrator: Orchestrator,
    store: InMemoryDiagramStore,
) -> None:
    diagram_id = await orchestrator.ingest(_make_image_bytes(), filename="upload.png")
    md = store.get_metadata(diagram_id)
    assert md is not None
    assert md.source_filename == "upload.png"


async def test_ingest_sets_source_filename_from_path(
    orchestrator: Orchestrator,
    store: InMemoryDiagramStore,
    tmp_path: pytest.TempPathFactory,
) -> None:
    p = tmp_path / "my_schematic.png"
    Image.new("RGB", (100, 100)).save(p)
    diagram_id = await orchestrator.ingest(p)
    md = store.get_metadata(diagram_id)
    assert md is not None
    assert md.source_filename == "my_schematic.png"


async def test_ingest_does_not_mutate_pipeline_return_value(
    orchestrator: Orchestrator,
    mock_pipeline: MagicMock,
) -> None:
    """ingest() must not mutate the object returned by pipeline.run()."""
    captured: list[DiagramMetadata] = []
    original_side_effect = mock_pipeline.run.side_effect

    async def capturing_side_effect(img: object) -> DiagramMetadata:
        md = original_side_effect(img)
        captured.append(md)
        return md

    mock_pipeline.run.side_effect = capturing_side_effect
    await orchestrator.ingest(_make_image_bytes(), filename="new_name.png")

    # The object returned by pipeline.run still has the original filename
    assert captured[0].source_filename == "initial.png"


async def test_ingest_configures_global_store(
    orchestrator: Orchestrator,
) -> None:
    """After ingest(), get_store() returns the orchestrator's store."""
    await orchestrator.ingest(_make_image_bytes())
    assert get_store() is orchestrator._store


# ---------------------------------------------------------------------------
# Orchestrator.ingest_and_analyze()
# ---------------------------------------------------------------------------


async def test_ingest_and_analyze_returns_agent_response(
    orchestrator: Orchestrator,
) -> None:
    response = await orchestrator.ingest_and_analyze(
        _make_image_bytes(), "How many components?"
    )
    assert response == "Diagram has 1 resistor."


async def test_ingest_and_analyze_passes_diagram_id_to_agent(
    orchestrator: Orchestrator,
    mock_agent: MagicMock,
) -> None:
    await orchestrator.ingest_and_analyze(_make_image_bytes(), "query")
    diagram_id_arg = mock_agent.analyze.call_args[0][0]
    assert diagram_id_arg == DIAGRAM_ID


async def test_ingest_and_analyze_passes_query_to_agent(
    orchestrator: Orchestrator,
    mock_agent: MagicMock,
) -> None:
    await orchestrator.ingest_and_analyze(_make_image_bytes(), "List all valves.")
    query_arg = mock_agent.analyze.call_args[0][1]
    assert query_arg == "List all valves."


async def test_ingest_and_analyze_raises_without_agent(
    mock_pipeline: MagicMock,
    mock_tile_storage: MagicMock,
    store: InMemoryDiagramStore,
) -> None:
    orch = Orchestrator(
        preprocessing_pipeline=mock_pipeline,
        tile_storage=mock_tile_storage,
        store=store,
        agent=None,
    )
    with pytest.raises(RuntimeError, match="No agent configured"):
        await orch.ingest_and_analyze(_make_image_bytes(), "query")


# ---------------------------------------------------------------------------
# Orchestrator.analyze() — synchronous wrapper
# ---------------------------------------------------------------------------


def test_analyze_returns_agent_response(
    orchestrator: Orchestrator,
    tmp_path: pytest.TempPathFactory,
) -> None:
    p = tmp_path / "diagram.png"
    Image.new("RGB", (100, 100)).save(p)
    result = orchestrator.analyze(p, "What is here?")
    assert result == "Diagram has 1 resistor."


def test_analyze_accepts_string_path(
    orchestrator: Orchestrator,
    tmp_path: pytest.TempPathFactory,
) -> None:
    p = tmp_path / "diagram.png"
    Image.new("RGB", (100, 100)).save(p)
    result = orchestrator.analyze(str(p), "query")
    assert result == "Diagram has 1 resistor."


def test_analyze_infers_filename_from_path(
    orchestrator: Orchestrator,
    store: InMemoryDiagramStore,
    tmp_path: pytest.TempPathFactory,
) -> None:
    p = tmp_path / "power_supply.png"
    Image.new("RGB", (100, 100)).save(p)
    orchestrator.analyze(p, "query")
    md = store.get_metadata(DIAGRAM_ID)
    assert md is not None
    assert md.source_filename == "power_supply.png"


# ---------------------------------------------------------------------------
# Orchestrator.create_local()
# ---------------------------------------------------------------------------


def test_create_local_returns_orchestrator() -> None:
    orch = Orchestrator.create_local()
    assert isinstance(orch, Orchestrator)


def test_create_local_with_mock_adk_has_agent() -> None:
    """When ADK mocks are injected, create_local() wires a live agent."""
    orch = Orchestrator.create_local(
        _agent_cls=MagicMock(),
        _runner_cls=MagicMock(),
        _types_mod=MagicMock(),
    )
    assert orch._agent is not None


def test_create_local_without_adk_agent_is_none() -> None:
    """When ADK is absent (no _agent_cls injected), agent defaults to None."""
    orch = Orchestrator.create_local()
    # No real google-adk installed → agent is None
    assert orch._agent is None


def test_create_local_configures_global_store() -> None:
    Orchestrator.create_local()
    assert get_store() is not None


def test_create_local_custom_tile_dir(tmp_path: pytest.TempPathFactory) -> None:
    orch = Orchestrator.create_local(tile_dir=tmp_path)
    assert isinstance(orch, Orchestrator)


def test_create_local_pipeline_accepts_image() -> None:
    """The no-op OCR/CV pipeline returned by create_local() can run."""
    orch = Orchestrator.create_local()
    img = Image.new("RGB", (100, 100))
    # run() is async — use asyncio.run in a sync test
    import asyncio

    metadata = asyncio.run(orch._pipeline.run(img))
    assert isinstance(metadata, DiagramMetadata)
    assert metadata.text_labels == []


# ---------------------------------------------------------------------------
# configure_store() integration: tools see the orchestrator's store
# ---------------------------------------------------------------------------


async def test_tools_see_orchestrator_store_after_ingest(
    orchestrator: Orchestrator,
) -> None:
    """After ingest(), the tool functions read data from the orchestrator store."""
    from src.tools.get_overview import get_overview

    diagram_id = await orchestrator.ingest(_make_image_bytes())
    result = get_overview(diagram_id)

    assert result["diagram_id"] == diagram_id
    assert result["component_count"] == 1
    assert "resistor" in result["component_types"]


async def test_tool_search_text_after_ingest(
    orchestrator: Orchestrator,
) -> None:
    """search_text() finds labels stored during ingest()."""
    from src.tools.search_text import search_text

    diagram_id = await orchestrator.ingest(_make_image_bytes())
    result = search_text(diagram_id, "R1")

    assert result["match_count"] == 1
    assert result["matches"][0]["text"] == "R1"
