# Testing the CAD Diagram Analyzer

## 1. Testing Philosophy

### Why Mock at Dependency Boundaries

The CAD Diagram Analyzer depends on three external cloud services: Vertex AI (for
Gemini inference), Google Cloud Document AI (for OCR), and Google Cloud Storage /
Firestore (for diagram storage). Running the real services in CI would require
provisioned GCP credentials, incur API costs, and introduce non-determinism from
network latency and model responses. More importantly, those services are not the
things being tested — the business logic is.

The strategy is to mock at the narrowest useful boundary:

- **Storage**: `DiagramStore` is an abstract base class. Tests inject a
  `MagicMock(spec=DiagramStore)` via `configure_store()`, pre-loaded with
  deterministic `DiagramMetadata`, `TilePyramid`, and `PIL.Image` objects. Every
  tool test then exercises real tool logic against predictable data.
- **ADK / Gemini**: `LlmAgent` and `InMemoryRunner` are injected through the
  `_agent_cls`, `_runner_cls`, and `_types_mod` constructor parameters on
  `CADAnalysisAgent`. Tests replace these with `MagicMock` instances or custom
  async runner classes so the agent wiring, response extraction, and tool
  invocation paths are exercised without touching the Gemini API.
- **OCR / CV**: `DocumentAIOCRExtractor` and `CVPipeline` are injected into
  `PreprocessingPipeline` as constructor arguments. Tests supply async mocks
  that return synthetic `TextLabel` lists, keeping OpenCV and Document AI out
  of the unit test boundary entirely.
- **GCS / Firestore**: The `GCSAdapter` and `FirestoreAdapter` thin wrappers
  are tested with `MagicMock` / `AsyncMock` clients, confirming call signatures
  without making real HTTP calls.

### Why No Real GCP Credentials Are Needed

All tests pass the `asyncio_mode = "auto"` flag (configured in `pyproject.toml`)
and use `unittest.mock`. The `pytest` process never touches any GCP endpoint,
which means:

- Tests run offline and in any CI environment.
- Tests are deterministic: the same mocked data produces the same assertions
  on every run.
- Token costs and quota limits cannot be hit by running tests.
- Failures are always reproducible and do not require ADC (`gcloud auth
  application-default login`) to debug.

The only exception is the `scripts/test_local.py` smoke script, which is a
manual integration check that intentionally requires live credentials.

### Why `asyncio_mode = "auto"`

Many pipeline functions (`PreprocessingPipeline.run`, OCR extraction, GCS
upload/download) are `async def`. With `asyncio_mode = "auto"` in
`pyproject.toml`, pytest-asyncio automatically wraps every `async def test_*`
function in its own event loop without requiring explicit `@pytest.mark.asyncio`
decorators. This keeps test code clean and consistent.

---

## 2. Test Suite Structure

```
tests/
├── conftest.py                        # Session-scoped and shared fixtures
├── fixtures/
│   └── README.md                      # Notes on sample CAD PNG images
├── test_models/
│   ├── __init__.py
│   ├── test_bounding_box.py           # BoundingBox: validation, conversions, spatial ops
│   ├── test_component.py              # Component and Pin models
│   ├── test_diagram_metadata.py       # DiagramMetadata construction and helpers
│   ├── test_text_label.py             # TextLabel model
│   ├── test_tile_pyramid.py           # TilePyramid queries (tiles_at_level, tile_at)
│   ├── test_title_block.py            # TitleBlock parsing helpers
│   └── test_trace.py                  # Trace model
├── test_tiling/
│   ├── __init__.py
│   ├── test_tile_generator.py         # TileGenerator: tile count, overlap, bbox, crop
│   └── test_tile_storage.py           # LocalTileStorage read/write round-trips
├── test_tools/
│   ├── __init__.py
│   ├── conftest.py                    # Mock DiagramStore with rich fixture data
│   ├── test_get_overview.py           # get_overview: structure, image encoding, fallbacks
│   ├── test_inspect_component.py      # inspect_component: crop, nearby, error handling
│   ├── test_inspect_zone.py           # inspect_zone: tile selection, SOM annotation
│   ├── test_search_text.py            # search_text: matching, tile annotation, validation
│   └── test_trace_net.py              # trace_net: direction, path, orphan handling
├── test_preprocessing/
│   ├── __init__.py
│   ├── test_ocr.py                    # DocumentAIOCRExtractor with mocked Document AI
│   ├── test_pipeline.py               # PreprocessingPipeline async flow
│   └── test_title_block.py            # TitleBlockExtractor spatial logic
├── test_ingestion/
│   ├── __init__.py
│   └── test_gcs_adapter.py            # GCSAdapter upload/download with mock GCS client
├── test_agent/
│   ├── __init__.py
│   └── test_cad_agent.py              # CADAnalysisAgent: wiring, response, tool tracking
└── test_orchestrator.py               # Top-level ingest pipeline integration
```

### What Each Directory Tests

| Directory | Primary Concern | Mocks Used |
|-----------|----------------|------------|
| `test_models/` | Pydantic v2 validation, computed properties, serialization | None — pure Python |
| `test_tiling/` | Tile geometry math (overlap ≥ 20%, bbox correctness), image crop | PIL in-memory images |
| `test_tools/` | Tool return shape, error paths, image encoding, tile annotation | `DiagramStore` via `configure_store()` |
| `test_preprocessing/` | Pipeline async flow, OCR/CV integration, title block extraction | `AsyncMock` OCR extractor, stub CV |
| `test_ingestion/` | GCS/Firestore adapter method calls and data serialization | `MagicMock` GCS and Firestore clients |
| `test_agent/` | ADK wiring, event stream parsing, `ToolCallTracker`, tool DI seam | `LlmAgent`, `InMemoryRunner`, `google.genai.types` |

---

## 3. Quick Start

```bash
# Install project + dev dependencies (uv preferred, pip also works)
uv sync --group dev
# or: pip install -e ".[dev]"

# Run the full test suite
pytest

# Run with verbose output and live log capture
pytest -v -s

# Run a specific test directory
pytest tests/test_agent/ -v
pytest tests/test_tools/ -v
pytest tests/test_models/ -v
pytest tests/test_tiling/ -v
pytest tests/test_preprocessing/ -v

# Run a single test file
pytest tests/test_tools/test_get_overview.py -v

# Run a single test function
pytest tests/test_agent/test_cad_agent.py::test_agent_registers_all_five_tools -v

# Show stdout/stderr during tests (useful for debug logging)
pytest -s tests/test_agent/ -v
```

No `.env` file, no GCP credentials, no running server are required to run any
test in this suite.

---

## 4. Environment Setup

### Python Version

Python 3.11 or later is required. The `pyproject.toml` declares
`requires-python = ">=3.11"` and uses structural pattern matching (`match`
statements) in callbacks.

### Install Dependencies

```bash
# Using uv (preferred — handles virtual environment automatically)
uv sync --group dev

# Using pip
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

The `[dev]` extra installs pytest, pytest-asyncio, mypy, and ruff.

### pytest Configuration (`pyproject.toml`)

```toml
[tool.pytest.ini_options]
pythonpath = ["."]      # lets tests import from src/ without PYTHONPATH tricks
testpaths = ["tests"]
asyncio_mode = "auto"   # all async def test_* functions run automatically
```

`asyncio_mode = "auto"` is the critical setting. Without it every async test
would need `@pytest.mark.asyncio`. With it, pytest-asyncio handles event loop
management transparently for the entire suite.

### Environment Variables for Tests

Tests do not read any `.env` file. All external dependencies are mocked. The
only environment variable that affects test behavior is `GEMINI_MODEL`, which
controls the `DEFAULT_MODEL` string checked in `test_model_default`. The
default in code is `"gemini-2.5-flash"`, so no override is needed.

For running the real server (not required for tests):

```env
GCP_PROJECT_ID=your-gcp-project
GCS_BUCKET=your-bucket
FIRESTORE_DB=your-db
DOCUMENT_AI_PROCESSOR_ID=your-processor-id
DOCUMENT_AI_LOCATION=us
VERTEX_AI_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash
GOOGLE_GENAI_USE_VERTEXAI=1
```

---

## 5. Understanding the Mocking Architecture

### The DiagramStore Seam

All five agent tools (`get_overview`, `inspect_zone`, `inspect_component`,
`search_text`, `trace_net`) read diagram data through the `DiagramStore` abstract
interface defined in `src/tools/_store.py`. The module holds a module-level
singleton `_instance`. The `configure_store(store)` function replaces it:

```python
# src/tools/_store.py (simplified)
_instance: DiagramStore | None = None

def configure_store(store: DiagramStore) -> None:
    global _instance
    _instance = store

def get_store() -> DiagramStore:
    if _instance is None:
        raise RuntimeError("DiagramStore not configured")
    return _instance
```

Every tool calls `get_store()` internally. Tests inject a pre-loaded mock:

```python
# tests/test_tools/conftest.py
@pytest.fixture()
def mock_store(request: pytest.FixtureRequest) -> MagicMock:
    store = MagicMock(spec=DiagramStore)
    store.get_metadata.return_value = _make_metadata()
    store.get_pyramid.return_value = _make_pyramid(metadata)
    store.load_tile_image.return_value = _white_image(256, 256)
    store.load_original_image.return_value = _white_image(800, 600)
    configure_store(store)
    yield store
    _store_module._instance = None  # isolation: reset after each test
```

The `yield` + teardown pattern (`_store_module._instance = None`) ensures that
tests never bleed state into each other, even when run in parallel. Each test
file in `test_tools/` declares `mock_store` (or a variant) in its function
signature to activate the fixture automatically.

### Mock Store Variants

`tests/test_tools/conftest.py` defines additional fixture variants for edge cases:

```python
@pytest.fixture()
def store_no_pyramid(mock_store: MagicMock) -> MagicMock:
    """Simulates a diagram that has not been tiled yet."""
    mock_store.get_pyramid.return_value = None
    return mock_store

@pytest.fixture()
def store_no_image(mock_store: MagicMock) -> MagicMock:
    """Simulates a diagram whose image file is missing from storage."""
    mock_store.load_tile_image.return_value = None
    mock_store.load_original_image.return_value = None
    return mock_store

@pytest.fixture()
def store_unknown_diagram() -> MagicMock:
    """Simulates a diagram_id that does not exist in the store."""
    store = MagicMock(spec=DiagramStore)
    store.get_metadata.return_value = None
    store.get_pyramid.return_value = None
    configure_store(store)
    yield store
    _store_module._instance = None
```

These drive the error-handling tests in every tool suite. A well-designed tool
must return `{"error": "..."}` rather than raising an exception in all three
scenarios.

### Mocking the ADK Agent Framework

`CADAnalysisAgent.__init__` accepts three private constructor parameters:

```python
class CADAnalysisAgent:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        _agent_cls: Any = None,   # replaces google.adk.agents.LlmAgent
        _runner_cls: Any = None,  # replaces google.adk.runners.InMemoryRunner
        _types_mod: Any = None,   # replaces google.genai.types
    ) -> None:
```

In production, all three default to the real SDK objects. In tests, they are
replaced by mocks. This pattern (often called "dependency injection via private
kwargs") keeps the production call site clean (`CADAnalysisAgent()`) while
allowing tests to swap every ADK dependency without monkey-patching modules.

The runner mock must be an async generator (because `runner.run_async()` yields
events). The test suite defines a small `_MockRunner` class:

```python
class _MockRunner:
    auto_create_session: bool = False

    def __init__(self, *, agent: Any) -> None:
        self.agent = agent

    async def run_async(
        self, *, user_id: str, session_id: str, new_message: Any
    ):
        async for e in _async_iter([event]):
            yield e
```

`_async_iter` converts a plain Python list into an async iterable:

```python
async def _async_iter(events: list[Any]):
    for event in events:
        yield event
```

ADK events expose `is_final_response()` and `content.parts`. The test fixture
creates mock events with `MagicMock`:

```python
def _make_final_event(text: str = "Agent analysis complete.") -> MagicMock:
    event = MagicMock()
    event.is_final_response.return_value = True
    event.content.parts = [MagicMock(text=text)]
    return event
```

The full wired `agent` fixture brings all three mocks together:

```python
@pytest.fixture()
def agent(
    mock_agent_cls: MagicMock,
    mock_runner_cls: MagicMock,
    mock_types: MagicMock,
) -> CADAnalysisAgent:
    return CADAnalysisAgent(
        _agent_cls=mock_agent_cls,
        _runner_cls=mock_runner_cls,
        _types_mod=mock_types,
    )
```

### Mocking the OCR / CV Pipeline

`PreprocessingPipeline` takes its dependencies as constructor arguments, making
them easy to substitute:

```python
class _StubCV:
    def run(self, image: Image.Image) -> CVResult:
        return CVResult()  # empty — no symbols detected

def _mock_extractor(labels: list[TextLabel] | None = None):
    extractor = MagicMock(spec=DocumentAIOCRExtractor)
    extractor.extract = AsyncMock(return_value=labels or [])
    return extractor

pipeline = PreprocessingPipeline(
    ocr_extractor=_mock_extractor(labels),
    cv_pipeline=_StubCV(),
)
```

`AsyncMock` is used for `extract` because `DocumentAIOCRExtractor.extract` is
`async def`. It integrates seamlessly with `asyncio_mode = "auto"` — no explicit
`await` ceremony in the test body.

---

## 6. Test Suites Explained

### 6.1 Model Tests (`tests/test_models/`)

The model tests are pure unit tests with no mocking. They exercise Pydantic v2
validation rules, computed properties, and serialization round-trips.

**BoundingBox** (`test_bounding_box.py`) is the most extensively tested model
because it underlies every spatial operation in the system. Tests are organized
into classes by feature:

```python
class TestCreation:
    def test_negative_x_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BoundingBox(x_min=-0.1, y_min=0.0, x_max=0.5, y_max=0.5)

    def test_pixel_coords_rejected(self) -> None:
        # Values > 1.0 are pixel coords — BoundingBox must be normalized
        with pytest.raises(ValidationError):
            BoundingBox(x_min=0, y_min=0, x_max=800, y_max=600)

class TestFromPixelCoords:
    def test_roundtrip_with_to_pixel_coords(self) -> None:
        original = BoundingBox(x_min=0.125, y_min=0.25, x_max=0.5, y_max=0.75)
        px = original.to_pixel_coords(800, 600)
        restored = BoundingBox.from_pixel_coords(*px, width=800, height=600)
        assert restored.x_min == pytest.approx(original.x_min)

class TestOverlaps:
    def test_edge_touch_not_overlap(self) -> None:
        a = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.5, y_max=1.0)
        b = BoundingBox(x_min=0.5, y_min=0.0, x_max=1.0, y_max=1.0)
        assert a.overlaps(b) is False  # shared edge, not interior overlap
```

The `TestIoU` class verifies the intersection-over-union calculation used by
the CV pipeline to deduplicate detected symbols. The `TestSerializationRoundtrip`
class confirms `model_dump_json()` / `model_validate_json()` fidelity, important
because tool results are JSON-serialized before being sent to Gemini.

### 6.2 Tiling Tests (`tests/test_tiling/`)

The tiling tests verify the mathematical correctness of the three-level tile
pyramid. The core requirements are:

1. Level 0: 1 tile (full image overview)
2. Level 1: 4 tiles (2×2 grid)
3. Level 2: 16 tiles (4×4 grid)
4. Adjacent tiles must overlap by at least 20% to avoid splitting components
   at boundaries

```python
class TestTileStructure:
    def test_total_tile_count(self) -> None:
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        assert len(pyramid.tiles) == 21  # 1 + 4 + 16

class TestOverlap:
    def test_overlap_exactly_20pct_with_default_config(self) -> None:
        pyramid = TileGenerator(_make_image(), _make_metadata()).generate()
        left = pyramid.tile_at(1, 0, 0)
        right = pyramid.tile_at(1, 0, 1)
        tile_width = left.bbox.x_max - left.bbox.x_min
        overlap_frac = (left.bbox.x_max - right.bbox.x_min) / tile_width
        assert overlap_frac == pytest.approx(0.20, abs=1e-6)
```

The `TestComponentFiltering` class verifies that a component straddling a tile
boundary appears in both adjacent tiles' `component_ids` lists, which is
essential for the agent to not miss components when querying a partial zone.

```python
def test_component_at_boundary_in_both_tiles(self) -> None:
    comp = Component(
        component_type="resistor",
        bbox=BoundingBox(x_min=0.45, y_min=0.1, x_max=0.55, y_max=0.2),
    )
    pyramid = TileGenerator(_make_image(), _make_metadata(components=[comp])).generate()
    left = pyramid.tile_at(1, 0, 0)
    right = pyramid.tile_at(1, 0, 1)
    assert comp.component_id in left.component_ids
    assert comp.component_id in right.component_ids
```

### 6.3 Tool Tests (`tests/test_tools/`)

Each of the five tools has a dedicated test file. All tool tests use the
`mock_store` fixture from `tests/test_tools/conftest.py`, which is activated
by simply declaring it as a function parameter.

**get_overview** tests verify: diagram ID echoed, dimensions correct, component
type breakdown dict populated, base64-encoded PNG image embedded, graceful
fallback when pyramid is unavailable (falls back to original image), and
`image_base64: null` when both image sources return `None`.

```python
def test_image_base64_is_valid(mock_store: MagicMock) -> None:
    result = get_overview(DIAGRAM_ID)
    b64 = result["image_base64"]
    decoded = base64.b64decode(b64)
    assert decoded[:4] == b"\x89PNG"  # PNG magic bytes

def test_error_when_diagram_not_found(store_unknown_diagram: MagicMock) -> None:
    result = get_overview("nonexistent-id")
    assert "error" in result
    assert "nonexistent-id" in result["error"]
```

**search_text** tests verify: case-insensitive partial matching (`"vc"` matches
`"VCC"`), tile ID annotation from the pyramid, `tile_id: null` fallback when no
pyramid exists, empty-string and whitespace-only query rejection, and max-100
match truncation.

```python
def test_partial_match(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "vc")
    assert result["match_count"] == 1
    assert result["matches"][0]["text"] == "VCC"

def test_error_on_whitespace_only_query(mock_store: MagicMock) -> None:
    result = search_text(DIAGRAM_ID, "   ")
    assert "error" in result
```

**trace_net** tests cover: connection direction (`"from"` vs `"to"` depending on
which side of the trace the queried component is on), empty-pin wildcard (returns
all connections for that component), `trace_data_unavailable: true` flag when the
metadata has no traces (graceful fallback instead of an error), and orphan trace
handling (a trace pointing to a component ID not in the metadata produces
`connected_component_type: "unknown"` rather than a crash).

```python
def test_trace_data_unavailable_flag(mock_store: MagicMock) -> None:
    metadata = mock_store.get_metadata.return_value
    metadata.traces = []
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    assert result["trace_data_unavailable"] is True
    assert result["connections"] == []

def test_unknown_peer_type_is_unknown(mock_store: MagicMock) -> None:
    for trace in mock_store.get_metadata.return_value.traces:
        trace.to_component = "orphan-comp-id"
    result = trace_net(DIAGRAM_ID, COMP_A_ID, PIN_A_ID)
    assert result["connections"][0]["connected_component_type"] == "unknown"
```

### 6.4 Preprocessing Tests (`tests/test_preprocessing/`)

Preprocessing tests use `asyncio_mode = "auto"` and test the full async pipeline
without any real GCP calls. The integration test at the bottom of
`test_pipeline.py` exercises the entire ingest path against the synthetic fixture
image defined in `tests/conftest.py`:

```python
async def test_integration_full_pipeline(sample_electrical_image: Path) -> None:
    labels = [
        _make_label("DWG: TEST-001", cx=0.72, cy=0.84),
        _make_label("REV: A", cx=0.88, cy=0.84),
        _make_label("SCALE: 1:1", cx=0.72, cy=0.90),
        _make_label("R1", cx=0.18, cy=0.29),
        _make_label("R2", cx=0.68, cy=0.29),
    ]
    pipeline = PreprocessingPipeline(
        ocr_extractor=_mock_extractor(labels),
        cv_pipeline=_StubCV(),
    )
    result = await pipeline.run(sample_electrical_image)

    assert result.source_filename == "sample_electrical.png"
    assert len(result.text_labels) == 5
    assert result.title_block.drawing_id == "TEST-001"
    assert result.title_block.revision == "A"
```

The `sample_electrical_image` fixture (defined in `tests/conftest.py`) generates
a synthetic 800×600 PNG at test-session startup. It draws two labeled rectangles
connected by a trace and a title block in the bottom-right corner — mimicking
the spatial structure of a real electrical schematic.

### 6.5 Agent Tests (`tests/test_agent/`)

The agent test file is the most architecturally interesting. It validates six
distinct concerns without any ADK or Gemini installation.

**Initialisation tests** confirm that `LlmAgent` receives exactly the right
constructor arguments:

```python
def test_agent_registers_all_five_tools(
    agent: CADAnalysisAgent,
    mock_agent_cls: MagicMock,
) -> None:
    _, kwargs = mock_agent_cls.call_args
    tools = kwargs["tools"]
    assert len(tools) == 5

def test_agent_tool_names(agent: CADAnalysisAgent) -> None:
    names = {fn.__name__ for fn in agent.tools}
    assert names == {
        "get_overview", "inspect_zone", "inspect_component",
        "search_text", "trace_net",
    }
```

**`analyze()` wiring tests** verify that the runner is instantiated, `run_async`
is called, the diagram ID is embedded in the Content object, and the return type
is `dict[str, Any]` with both `"text"` and `"tool_calls"` keys:

```python
def test_analyze_returns_dict_with_text_and_tool_calls(
    agent: CADAnalysisAgent,
    configured_store: MagicMock,
) -> None:
    result = agent.analyze(DIAGRAM_ID, "Summarise this schematic.")
    assert isinstance(result, dict)
    assert "text" in result
    assert "tool_calls" in result
    assert result["text"] == "Agent analysis complete."
    assert isinstance(result["tool_calls"], list)
```

**`_collect_final_text` unit tests** test the event-stream parsing helper in
isolation, covering the multi-event "last-text-wins" rule, `None`-content events
being skipped, and an empty stream returning `""`.

**`ToolCallTracker` tests** validate the singleton's lifecycle:

```python
def test_tracker_records_are_returned(configured_store: MagicMock) -> None:
    from src.agent.callbacks import tracker
    tracker.reset()
    tracker.record_start("get_overview", {"diagram_id": DIAGRAM_ID})
    tracker.record_end("get_overview", success=True, result_summary="2 components")
    records = tracker.get_records()
    assert len(records) == 1
    assert records[0]["tool_name"] == "get_overview"
    assert records[0]["success"] is True
    assert "duration_ms" in records[0]

def test_tracker_reset_clears_records() -> None:
    from src.agent.callbacks import tracker
    tracker.reset()
    tracker.record_start("test_tool", {})
    tracker.record_end("test_tool", success=True)
    assert len(tracker.get_records()) == 1
    tracker.reset()
    assert len(tracker.get_records()) == 0
```

**The mock tool-call flow integration test** is the most comprehensive: it wires
a custom `_SimulatedRunner` that actually calls `get_overview()` against the
configured mock store and packages the result into a final event. This confirms
that the dependency injection seam (store → tool function → runner → `analyze()`)
is fully connected end-to-end, with real tool logic executing against mock data:

```python
def test_mock_tool_call_flows_through(configured_store: MagicMock) -> None:
    from src.tools.get_overview import get_overview

    captured: dict = {}

    class _SimulatedRunner:
        auto_create_session: bool = False

        def __init__(self, *, agent: object) -> None:
            pass

        async def run_async(self, *, user_id, session_id, new_message):
            tool_result = get_overview(DIAGRAM_ID)   # calls real tool
            captured.update(tool_result)
            count = tool_result.get("component_count", 0)
            event = _make_final_event(f"Diagram has {count} components.")
            async for e in _async_iter([event]):
                yield e

    agent = CADAnalysisAgent(
        _agent_cls=MagicMock(),
        _runner_cls=_SimulatedRunner,
        _types_mod=MagicMock(),
    )
    result = agent.analyze(DIAGRAM_ID, "How many components?")
    assert captured["component_count"] == 2
    assert "2" in result["text"]
```

---

## 7. Writing New Tests

### Adding a Tool Test

1. Add a new `test_*.py` file inside `tests/test_tools/`.
2. Import the tool function and `DIAGRAM_ID` from `tests.test_tools.conftest`.
3. Declare `mock_store: MagicMock` as a parameter on each test function.
4. Assert that the returned dict contains the expected keys and values.

```python
# tests/test_tools/test_my_new_tool.py
from unittest.mock import MagicMock
from src.tools.my_new_tool import my_new_tool
from tests.test_tools.conftest import DIAGRAM_ID


def test_returns_diagram_id(mock_store: MagicMock) -> None:
    result = my_new_tool(DIAGRAM_ID)
    assert result["diagram_id"] == DIAGRAM_ID


def test_error_when_diagram_not_found(store_unknown_diagram: MagicMock) -> None:
    result = my_new_tool("bad-id")
    assert "error" in result


def test_handles_missing_data_gracefully(store_no_pyramid: MagicMock) -> None:
    result = my_new_tool(DIAGRAM_ID)
    # Should return a valid (possibly empty) result, not raise
    assert isinstance(result, dict)
    assert "error" not in result
```

### Adding a Model Test

Model tests need no fixtures — just import the model and use `pytest.raises` for
negative cases:

```python
# tests/test_models/test_my_model.py
import pytest
from pydantic import ValidationError
from src.models.my_model import MyModel


def test_valid_construction() -> None:
    m = MyModel(field="value")
    assert m.field == "value"


def test_invalid_field_rejected() -> None:
    with pytest.raises(ValidationError):
        MyModel(field=None)  # type: ignore


def test_json_roundtrip() -> None:
    original = MyModel(field="value")
    restored = MyModel.model_validate_json(original.model_dump_json())
    assert restored == original
```

### Adding an Async Preprocessing Test

Because `asyncio_mode = "auto"` is active, async tests just need the `async def`
signature:

```python
async def test_my_pipeline_step() -> None:
    extractor = MagicMock(spec=DocumentAIOCRExtractor)
    extractor.extract = AsyncMock(return_value=[])
    pipeline = PreprocessingPipeline(ocr_extractor=extractor, cv_pipeline=_StubCV())
    result = await pipeline.run(Image.new("RGB", (100, 100)))
    assert result.width_px == 100
```

### Adding an Agent Test

Use the existing `agent` fixture for standard wiring tests. For custom runner
behavior, define an inline `_CustomRunner` class inside the test:

```python
def test_custom_behavior(configured_store: MagicMock) -> None:
    class _CustomRunner:
        auto_create_session: bool = False

        def __init__(self, *, agent: Any) -> None:
            pass

        async def run_async(self, **kw: Any):
            async for e in _async_iter([_make_final_event("Custom response")]):
                yield e

    custom_agent = CADAnalysisAgent(
        _agent_cls=MagicMock(),
        _runner_cls=_CustomRunner,
        _types_mod=MagicMock(),
    )
    result = custom_agent.analyze(DIAGRAM_ID, "query")
    assert result["text"] == "Custom response"
```

### Fixture Data IDs

The `tests/test_tools/conftest.py` defines stable IDs used as constants across
all tool tests. Reference these in new tests rather than hardcoding strings:

```python
from tests.test_tools.conftest import (
    DIAGRAM_ID,    # "diag-0001"
    COMP_A_ID,     # "comp-aaa"   (resistor, 100Ω)
    COMP_B_ID,     # "comp-bbb"   (capacitor, 10µF)
    PIN_A_ID,      # "pin-a-out"
    PIN_B_ID,      # "pin-b-in"
    LABEL_A_ID,    # "lbl-r1"     (text: "R1")
    LABEL_B_ID,    # "lbl-vcc"    (text: "VCC")
    TRACE_ID,      # "trace-001"  (A→B connection)
    TILE_L0_ID,    # "diag-0001_L0_R0_C0"
    TILE_L2_ID,    # "diag-0001_L2_R0_C0"
)
```

---

## 8. API Endpoint Testing

For manual integration testing against a running server, the following `curl`
examples show the full request/response cycle including the new `tool_calls`
field.

### Start the Server

```bash
source venv/bin/activate
python -m src.agent.server
# Output: INFO:     Uvicorn running on http://0.0.0.0:8080
```

### Step 1 — Ingest a Diagram

```bash
curl -X POST http://localhost:8080/ingest \
  -F "file=@/path/to/your/schematic.png"
```

Response:
```json
{
  "diagram_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "error_message": null
}
```

### Step 2 — Analyze the Diagram (with `tool_calls` in response)

```bash
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "diagram_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "What components are present in this diagram?"
  }'
```

Response (`AnalyzeResponse` schema):
```json
{
  "diagram_id": "550e8400-e29b-41d4-a716-446655440000",
  "query": "What components are present in this diagram?",
  "response": "The diagram contains the following components: ...",
  "tool_calls": [
    {
      "tool_name": "get_overview",
      "args": { "diagram_id": "550e8400-e29b-41d4-a716-446655440000" },
      "duration_ms": 12.4,
      "success": true,
      "result_summary": "4 components, 12 text labels",
      "error": null
    },
    {
      "tool_name": "inspect_zone",
      "args": { "diagram_id": "550e8400-...", "x1": 0, "y1": 0, "x2": 50, "y2": 50 },
      "duration_ms": 38.1,
      "success": true,
      "result_summary": "2 tiles, 2 components, 5 labels",
      "error": null
    }
  ]
}
```

The `tool_calls` list is `null` when the agent does not invoke any tools (rare
but valid if the question is answered from context alone). Each record contains:

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | `str` | One of the five tool function names |
| `args` | `dict` | Arguments passed by the LLM (base64 images truncated to 80 chars) |
| `duration_ms` | `float` | Wall-clock time for the tool execution in milliseconds |
| `success` | `bool` | `false` when the tool returned an `"error"` key |
| `result_summary` | `str` | Human-readable one-liner produced by `_summarise_result()` |
| `error` | `str \| null` | Error message when `success` is `false` |

### Step 3 — View the Interactive Visualization

```bash
# Open in browser
open http://localhost:8080/visualization/550e8400-e29b-41d4-a716-446655440000

# Or fetch the raw HTML
curl http://localhost:8080/visualization/550e8400-e29b-41d4-a716-446655440000 \
  -o visualization.html
```

The `GET /visualization/{diagram_id}` endpoint returns a self-contained HTML
page with SVG bounding-box overlays, hover-to-highlight interaction, and a
searchable sidebar listing all detected components and labels.

### Step 4 — Swagger UI

```
http://localhost:8080/docs
```

FastAPI auto-generates interactive Swagger UI from the Pydantic request/response
models. All endpoint schemas, including `tool_calls: list[dict] | null`, are
visible and testable here.

### API Reference

| Method | Path | Request | Response |
|--------|------|---------|----------|
| `POST` | `/ingest` | `multipart/form-data` with `file` field | `IngestResponse` |
| `POST` | `/analyze` | `AnalyzeRequest` JSON | `AnalyzeResponse` with `tool_calls` |
| `GET` | `/visualization/{id}` | — | Self-contained HTML |
| `GET` | `/docs` | — | Swagger UI |
| `GET` | `/` | — | Web UI frontend |

---

## 9. Code Quality Commands

```bash
# Static type checking — all src/ must pass mypy strict mode
mypy src/

# Lint — catches unused imports, style violations, common bugs
ruff check src/

# Auto-format — enforces line length 100, import ordering
ruff format src/

# Lint + format in one pass (useful in CI)
ruff check src/ --fix && ruff format src/

# Run tests with coverage (requires pytest-cov)
pytest --cov=src --cov-report=term-missing
```

### mypy Configuration

`pyproject.toml` enables strict mypy with the Pydantic v2 plugin:

```toml
[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = true
explicit_package_bases = true
plugins = ["pydantic.mypy"]
```

`strict = true` enables `--disallow-untyped-defs`, `--no-implicit-optional`,
`--warn-return-any`, and similar flags. All tool functions and model methods must
have fully annotated signatures.

### ruff Configuration

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
ignore = ["E501"]  # line length handled by formatter
```

The `B` (bugbear) and `SIM` (simplify) rule sets catch common Python antipatterns
beyond the standard pyflakes/pycodestyle checks.

---

## 10. Troubleshooting Common Test Failures

### `ModuleNotFoundError: No module named 'src'`

The `pythonpath = ["."]` setting in `pyproject.toml` should handle this. If it
does not, ensure you are running `pytest` from the project root:

```bash
cd /path/to/cad-diagram-analyzer
pytest
```

Or activate the virtual environment first so `pip install -e .` has placed
`src` on the path.

### `RuntimeError: DiagramStore not configured`

A tool test is running without the `mock_store` fixture. Either declare
`mock_store: MagicMock` as a parameter, or check that the test file is in
`tests/test_tools/` (where `conftest.py` lives). The `conftest.py` fixtures are
only auto-discovered for tests in the same directory or below.

### `AssertionError: store._instance is not None` after a test

One test configured the store but teardown did not run (perhaps due to an
unhandled exception earlier in the test). Reset manually:

```python
import src.tools._store as _store_module
_store_module._instance = None
```

Or run the full suite again — each `mock_store` fixture restores `_instance =
None` in its teardown.

### `SyntaxError` or `ImportError` in test_cad_agent.py

The agent test file imports `CADAnalysisAgent`, `_collect_final_text`, and
`SYSTEM_INSTRUCTION` from `src.agent.cad_agent`. If `google-adk` is not
installed, the module still imports cleanly because ADK imports are in a
`try/except ImportError` block. However, `google-genai` must be importable for
the `google.genai.types` mock to work correctly. Run `pip install -e .` to
install all dependencies.

### `pytest.PytestUnraisableExceptionWarning: RuntimeWarning: coroutine was never awaited`

This usually means an `async def` test function is missing the `async` keyword in
its definition, or the test file is not covered by `asyncio_mode = "auto"`. Check
that `pyproject.toml` has `asyncio_mode = "auto"` under `[tool.pytest.ini_options]`
and that `pytest-asyncio` is installed.

### `AssertionError` in tracker tests: `len(records) != expected`

The `ToolCallTracker` is a module-level singleton (`tracker = ToolCallTracker()`
in `src/agent/callbacks.py`). If a previous test called `tracker.record_start`
without calling `tracker.reset()`, records accumulate. Always call
`tracker.reset()` at the start of any test that examines tracker state:

```python
def test_tracker_records_are_returned(...) -> None:
    from src.agent.callbacks import tracker
    tracker.reset()  # mandatory — singleton persists across tests
    tracker.record_start("get_overview", {"diagram_id": DIAGRAM_ID})
    tracker.record_end("get_overview", success=True)
    assert len(tracker.get_records()) == 1
```

### `AssertionError: overlap fraction < 0.20`

If you have modified `TilingConfig` defaults or the `TileGenerator` geometry
logic, this test catches regressions. The 20% overlap requirement is a hard
domain constraint: tiles with less overlap risk splitting fine-detail components
(resistors, labels) at the boundary, making them invisible in any single tile.

### `400 Bad Request / token count exceeds limit` (running the real server)

This is not a unit test failure but occurs during manual API testing. The token
budget controls already in place are:

| Control | Default |
|---------|---------|
| Initial image encoding | JPEG 768px, quality=85 |
| `inspect_zone` max tiles | 3 |
| `inspect_zone` max tile size | 512×512 px |
| `inspect_zone` max labels per zone | 50 |
| `search_text` max matches | 100 |

If the error persists, try querying a smaller spatial region with `inspect_zone`
or switching to `GEMINI_MODEL=gemini-2.5-pro` which has a larger context window.

### `429 RESOURCE_EXHAUSTED` (running the real server)

The agent automatically retries transient 429/503 errors with exponential
backoff (2 s → 4 s → 8 s, up to 3 retries). If errors persist beyond the
retry window, check your Vertex AI quota in the GCP console and consider
using the `TOOL_MODEL=gemini-2.5-pro` environment variable to route
vision-heavy tool calls to a model with a higher quota.

### Test Isolation: Running a Single Failing Test

When a single test fails in a shared-state scenario (e.g., tracker records
leaking between tests), run the file in isolation to confirm:

```bash
pytest tests/test_agent/test_cad_agent.py::test_tracker_reset_clears_records -v -s
```

If it passes in isolation but fails in the full suite, the issue is test ordering
and shared singleton state. Add `tracker.reset()` at the start of the affected
test.
