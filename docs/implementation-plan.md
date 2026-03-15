# CAD Diagram Analyzer — Implementation Plan

**Generated:** 2026-02-23
**Updated:** 2026-03-14
**Status:** Implementation complete — all 5 phases delivered and operational
**Reference docs:** `CLAUDE.md`, `docs/architecture.md`

> **Note:** This document was written as a pre-implementation plan. All phases
> have been implemented. Acceptance criteria checkboxes below reflect the
> original plan targets. See the [Implementation Status](#implementation-status)
> section at the bottom for what was actually delivered and what evolved.

---

## Table of Contents

1. [Phase 1 — Data Models + Project Skeleton](#phase-1)
2. [Phase 2 — Pre-processing Pipeline (OCR + CV)](#phase-2)
3. [Phase 3 — Multi-resolution Tiling Engine](#phase-3)
4. [Phase 4 — Agent Tools + ADK Integration](#phase-4)
5. [Phase 5 — End-to-end Orchestration + Cloud Run Deployment](#phase-5)
6. [Technical Risks](#technical-risks)
7. [Open Questions](#open-questions)
8. [Dependency Graph](#dependency-graph)

---

## Phase 1 — Data Models + Project Skeleton {#phase-1}

**Goal:** A fully importable, type-safe codebase skeleton where every module exists,
every data contract is defined, and tests can run (even if they mostly skip on missing
GCP credentials). No business logic yet.

### Files to Create

```
pyproject.toml                        # project metadata, all deps, tool config
.env.example                          # template for local secrets
.gitignore
src/
  __init__.py
  models/
    __init__.py
    diagram.py      # DiagramMetadata, IngestionRequest, IngestionResult
    ocr.py          # BoundingBox, OCRElement, TextBlock, OCRResult
    cv.py           # Symbol, Trace, Junction, CVResult
    tiling.py       # Tile, TileLevel, TileZone, TilingManifest
    analysis.py     # BOMEntry, NetlistEntry, ComponentRef, AnalysisResult
  ingestion/
    __init__.py
    normalizer.py   # stub: format detection + rasterization interface
    gcs_adapter.py  # thin wrapper: upload_file, download_file, get_signed_url
    firestore_adapter.py  # thin wrapper: save_document, get_document
tests/
  conftest.py             # shared fixtures, GCP mock setup
  fixtures/
    README.md             # how to add sample diagrams
    sample_electrical.png # small synthetic CAD image for unit tests
  test_preprocessing/
    __init__.py
  test_tiling/
    __init__.py
  test_agent/
    __init__.py
docs/
  tool-specs.md     # stub: ADK tool JSON schema reference
  data-models.md    # stub: Pydantic model field reference
scripts/
  README.md
```

### Key Model Definitions

**`src/models/diagram.py`**
```
DiagramMetadata:
  diagram_id: str (UUID)
  source_filename: str
  format: Literal["png","tiff","pdf","dwg","dxf"]
  width_px: int
  height_px: int
  dpi: int
  gcs_original_uri: str
  gcs_raster_uri: str
  firestore_doc_id: str
  created_at: datetime

IngestionRequest:
  source_uri: str          # GCS URI or local path
  diagram_type: Literal["electrical","pid","mechanical","unknown"]
  requester_id: str

IngestionResult:
  metadata: DiagramMetadata
  success: bool
  error_message: str | None
```

**`src/models/ocr.py`**
```
BoundingBox:
  x_min: float   # normalized 0-1
  y_min: float
  x_max: float
  y_max: float
  # methods: to_pixel_coords(width, height), area(), overlaps(other)

OCRElement:
  text: str
  confidence: float
  bbox: BoundingBox
  page: int

OCRResult:
  elements: list[OCRElement]
  raw_document_ai_response: dict  # preserved for debugging
```

**`src/models/cv.py`**
```
Symbol:
  symbol_id: str
  symbol_type: str           # "resistor","valve","junction","unknown"
  bbox: BoundingBox
  confidence: float
  connections: list[str]     # IDs of connected symbols

Trace:
  trace_id: str
  start_bbox: BoundingBox
  end_bbox: BoundingBox
  waypoints: list[tuple[float,float]]

CVResult:
  symbols: list[Symbol]
  traces: list[Trace]
  junctions: list[BoundingBox]
```

**`src/models/tiling.py`**
```
TileLevel:
  level: int               # 0=overview, 1=2x2, 2=4x4
  grid_cols: int
  grid_rows: int
  overlap_fraction: float  # must be >= 0.20

Tile:
  tile_id: str             # "{diagram_id}_L{level}_R{row}_C{col}"
  level: int
  row: int
  col: int
  bbox_px: BoundingBox     # pixel coords in original image
  gcs_uri: str
  symbol_ids: list[str]    # symbols whose centroid falls in this tile
  ocr_element_ids: list[str]

TilingManifest:
  diagram_id: str
  levels: list[TileLevel]
  tiles: list[Tile]
```

**`src/models/analysis.py`**
```
BOMEntry:
  component_id: str
  reference_designator: str    # e.g. "R12", "V-101"
  description: str
  quantity: int
  bbox: BoundingBox

NetlistEntry:
  net_id: str
  connected_component_ids: list[str]
  signal_name: str | None

AnalysisResult:
  diagram_id: str
  bom: list[BOMEntry]
  netlist: list[NetlistEntry]
  summary: str
  confidence: float
```

### External Dependencies (Phase 1)

```toml
[project]
requires-python = ">=3.11"
dependencies = [
  "pydantic>=2.10",
  "google-cloud-storage>=2.18",
  "google-cloud-firestore>=2.19",
  "Pillow>=10.4",
  "python-dotenv>=1.0",
]

[dependency-groups]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.23",
  "mypy>=1.15",
  "ruff>=0.4",
]
```

### Test Cases (Phase 1)

| Test file | Test | What it checks |
|-----------|------|----------------|
| `tests/test_models.py` | `test_bounding_box_to_pixel_coords` | `BoundingBox(0.1, 0.2, 0.5, 0.8).to_pixel_coords(1000, 1000)` → `(100, 200, 500, 800)` |
| `tests/test_models.py` | `test_bounding_box_overlap` | Two overlapping boxes return `True`, non-overlapping return `False` |
| `tests/test_models.py` | `test_tile_id_format` | Tile ID conforms to `{uuid}_L{n}_R{n}_C{n}` |
| `tests/test_models.py` | `test_pydantic_serialization_roundtrip` | All models serialize to JSON and back with no loss |
| `tests/test_ingestion/test_gcs_adapter.py` | `test_upload_calls_gcs_client` | Adapter calls `client.bucket().blob().upload_from_file()` (mocked) |

### Acceptance Criteria (Phase 1) — **COMPLETED**

- [x] `mypy src/` passes with zero errors
- [x] `ruff check src/` passes with zero errors
- [x] `pytest tests/test_models.py` — all model tests pass without GCP credentials
- [x] All `__init__.py` files export the key symbols (importable as `from src.models.diagram import DiagramMetadata`)
- [x] `pyproject.toml` installs cleanly via `uv sync`

---

## Phase 2 — Pre-processing Pipeline (OCR + CV) {#phase-2}

**Goal:** Given a rasterized PNG on disk, produce a structured `CVResult` + `OCRResult`
object. The pipeline runs deterministically, never calls an LLM, and is fully unit-testable
with mocked GCP clients.

### Files to Create / Modify

```
src/
  preprocessing/
    __init__.py
    document_ai_adapter.py   # DocumentAIAdapter class: thin wrapper around google-cloud-documentai
    ocr_processor.py         # OCRProcessor: calls adapter, normalizes bboxes, deduplicates
    cv_pipeline.py           # CVPipeline: orchestrates OpenCV steps
    line_detector.py         # detect_lines(image: np.ndarray) -> list[Trace]
    symbol_detector.py       # SymbolDetector: contour-based + template-based detection
    title_block.py           # TitleBlockExtractor: find and parse drawing title block
    pipeline.py              # PreprocessingPipeline: composes all steps, returns PreprocessingOutput

tests/
  test_preprocessing/
    test_ocr_processor.py
    test_cv_pipeline.py
    test_symbol_detector.py
    test_title_block.py
    test_pipeline.py
```

### Component Responsibilities

**`document_ai_adapter.py` — `DocumentAIAdapter`**
- Constructor receives `project_id`, `location`, `processor_id` (injected, not hardcoded)
- `async def process_image(image_bytes: bytes) -> dict`: calls Document AI `process_document`
- Returns raw response dict; no parsing here (adapter stays thin)
- All network I/O is async

**`ocr_processor.py` — `OCRProcessor`**
- `async def run(image_path: Path) -> OCRResult`
- Reads image → calls `DocumentAIAdapter.process_image`
- Parses Document AI response: normalized vertex bboxes → `BoundingBox` objects
- Deduplicates overlapping elements (IoU threshold: 0.85)
- Filters low-confidence elements (threshold: 0.60)
- Key gotcha handled: Document AI returns vertices in `(x, y)` pairs on a 0-1 scale;
  convert using `BoundingBox.to_pixel_coords(width, height)`

**`line_detector.py` — `detect_lines()`**
- Grayscale → Gaussian blur → adaptive thresholding → Canny → HoughLinesP
- Returns list of `Trace` objects
- Parameters encapsulated in a `LineDetectionConfig` dataclass (not magic numbers)
- Per CLAUDE.md: thresholding must be configurable per diagram type

**`symbol_detector.py` — `SymbolDetector`**
- Stage 1: Contour-based detection — find closed regions of appropriate area
- Stage 2: Classify contours by shape ratio and aspect ratio into known types
- Stage 3 (optional): Template matching against a small library of standard symbols
- Returns `list[Symbol]` with `symbol_type` and `confidence`
- Note: symbol library path is configurable; no hardcoded paths

**`title_block.py` — `TitleBlockExtractor`**
- Locates title block by finding largest rectangular region near image corners
- Extracts OCR elements within the title block bbox
- Parses into structured fields: drawing number, revision, scale, date, author

**`pipeline.py` — `PreprocessingPipeline`**
- Composes: `OCRProcessor` → `SymbolDetector` → `TitleBlockExtractor`
- Populates `Symbol.connections` by checking each symbol's bbox against detected traces
- Returns `PreprocessingOutput(ocr: OCRResult, cv: CVResult, title_block: dict)`
- Saves output JSON to Firestore via `FirestoreAdapter`

### External Dependencies (Phase 2, additive)

```toml
"google-cloud-documentai>=2.29",
"opencv-python-headless>=4.10",
"numpy>=1.26",
```

> Use `opencv-python-headless` (not `opencv-python`) — no GUI deps, safer in containers.

### Test Cases (Phase 2)

| Test file | Test | What it checks |
|-----------|------|----------------|
| `test_ocr_processor.py` | `test_bbox_normalization` | Document AI vertex `(0.1, 0.2, 0.5, 0.8)` → correct `BoundingBox` |
| `test_ocr_processor.py` | `test_deduplication` | Two overlapping elements (IoU=0.9) → deduplicated to one |
| `test_ocr_processor.py` | `test_low_confidence_filter` | Element with `confidence=0.4` → excluded from result |
| `test_cv_pipeline.py` | `test_line_detector_on_synthetic` | Synthetic image with 3 horizontal lines → 3 `Trace` objects ± tolerance |
| `test_cv_pipeline.py` | `test_empty_image` | All-white image → no symbols, no traces, no error |
| `test_symbol_detector.py` | `test_contour_detection_finds_rectangles` | Image with 2 rectangles → 2 symbols detected |
| `test_symbol_detector.py` | `test_min_area_filter` | Tiny contour (< 10px²) → excluded |
| `test_title_block.py` | `test_title_block_found_at_corner` | Fixture image → title block bbox in bottom-right quadrant |
| `test_pipeline.py` | `test_full_pipeline_returns_expected_types` | `sample_electrical.png` → `PreprocessingOutput` with all fields populated |
| `test_pipeline.py` | `test_pipeline_saves_to_firestore` | Firestore adapter `save_document` called once with correct doc ID |

### Acceptance Criteria (Phase 2) — **COMPLETED**

- [x] On `sample_electrical.png` fixture: OCR extracts ≥ 1 text element with `confidence > 0.6`
- [x] On `sample_electrical.png` fixture: CV pipeline detects ≥ 1 symbol and ≥ 1 trace
- [x] All tests pass without live GCP credentials (Document AI and Firestore mocked)
- [x] `PreprocessingPipeline` completes in < 30 s on a MacBook with a 3000×2000 px image
- [x] No hardcoded project IDs, processor IDs, or file paths anywhere

---

## Phase 3 — Multi-resolution Tiling Engine {#phase-3}

**Goal:** Given a high-res PNG and its `TilingManifest` spec, produce correctly-sized,
correctly-overlapping tile images and upload them to GCS.

### Files to Create / Modify

```
src/
  tiling/
    __init__.py
    engine.py       # TilingEngine: core tile generation
    indexer.py      # TileIndexer: spatial queries against a TilingManifest
    uploader.py     # TileUploader: uploads tiles to GCS, updates manifest

tests/
  test_tiling/
    test_engine.py
    test_indexer.py
    test_uploader.py
```

### Component Responsibilities

**`engine.py` — `TilingEngine`**

```
def generate_manifest(diagram: DiagramMetadata) -> TilingManifest
```
- Creates `TileLevel` entries for levels 0, 1, 2 per the architecture spec
- Level 0: single tile, full image downscaled to max 1024px on longest side
- Level 1: 2×2 grid, each tile covers 50% of image width/height + 20% overlap on each edge
- Level 2: 4×4 grid, each tile covers 25% width/height + 20% overlap on each edge
- Computes each tile's `bbox_px` in original image pixel space

```
def generate_tiles(image: Image.Image, manifest: TilingManifest) -> list[tuple[Tile, bytes]]
```
- For each tile in manifest: crops `bbox_px` region from original, resizes to ≤ 1024px
- Returns `(Tile, jpeg_bytes)` pairs (JPEG at quality=90 for storage efficiency)
- Overlap implementation: for a 1000×1000 image with 2×2 grid and 20% overlap:
  - Cell width = 500px, overlap = 100px → each tile is 600px wide, centered on its cell
  - Edge tiles are clamped (no padding beyond image boundary)

**`indexer.py` — `TileIndexer`**
```
def tiles_for_bbox(manifest: TilingManifest, bbox: BoundingBox, level: int) -> list[Tile]
def tiles_for_symbol(manifest: TilingManifest, symbol: Symbol, level: int) -> list[Tile]
def symbols_in_tile(manifest: TilingManifest, tile: Tile, cv_result: CVResult) -> list[Symbol]
```
- Pure spatial math — no I/O, fast, easily unit-tested
- Used by agent tools to answer "what tile shows symbol X at zoom level Y?"

**`uploader.py` — `TileUploader`**
```
async def upload_all(tiles: list[tuple[Tile, bytes]], diagram_id: str) -> TilingManifest
```
- Uploads each tile to `gs://{bucket}/{diagram_id}/tiles/L{level}/R{row}_C{col}.jpg`
- Populates `tile.gcs_uri` for each tile
- Updates manifest in Firestore after all uploads complete
- Uses `asyncio.gather` for concurrent uploads (respect GCS rate limits: ≤ 50 concurrent)

### External Dependencies (Phase 3, additive)

No new top-level dependencies. Pillow (Phase 1) and GCS adapter (Phase 1) cover everything.

Optional: `numpy` (Phase 2) for any array-based image math.

### Test Cases (Phase 3)

| Test file | Test | What it checks |
|-----------|------|----------------|
| `test_engine.py` | `test_level0_tile_fits_1024px` | 7000×5000 image → level-0 tile is ≤ 1024px on each side |
| `test_engine.py` | `test_level1_tile_count` | 2×2 grid → manifest has exactly 4 level-1 tiles |
| `test_engine.py` | `test_level2_tile_count` | 4×4 grid → manifest has exactly 16 level-2 tiles |
| `test_engine.py` | `test_overlap_fraction_met` | For a 1000×1000 image, each level-1 tile bbox covers ≥ 600px wide (500 base + 20% each side) |
| `test_engine.py` | `test_no_tile_exceeds_image_bounds` | All tile `bbox_px` values are within `[0, width] × [0, height]` |
| `test_engine.py` | `test_full_coverage` | Union of all level-2 tile bboxes covers entire original image |
| `test_indexer.py` | `test_tiles_for_symbol_returns_containing_tile` | Symbol at center of image → level-1 tile containing center returned |
| `test_indexer.py` | `test_symbol_at_boundary_appears_in_two_tiles` | Symbol at 50% x (overlap boundary) → appears in both adjacent tiles |
| `test_uploader.py` | `test_upload_sets_gcs_uri` | After upload, all tiles in manifest have non-empty `gcs_uri` |
| `test_uploader.py` | `test_upload_calls_gcs_adapter_n_times` | For 21 tiles (1+4+16), GCS adapter called exactly 21 times |

### Acceptance Criteria (Phase 3) — **COMPLETED**

- [x] All tile tests pass without GCS credentials (uploader mocked)
- [x] For any image ≥ 1000×1000 px, all 21 tiles are generated within 10 s on local machine
- [x] No tile pixel data crosses image boundaries (no padding artifacts)
- [x] Overlap fraction is ≥ 0.20 on every non-edge tile boundary (verified programmatically in tests)
- [x] `TilingManifest` is fully serializable to JSON (for Firestore storage)

---

## Phase 4 — Agent Tools + ADK Integration {#phase-4}

**Goal:** Define the LLM-callable tool layer and wire up a working ADK `LlmAgent` that
can answer questions about a pre-processed diagram. No HTTP server yet.

### Files to Create / Modify

```
src/
  tools/
    __init__.py
    zoom_tile.py          # get_tile_image(diagram_id, level, row, col) -> ImageContent
    lookup_component.py   # lookup_component(diagram_id, component_id) -> dict
    trace_connection.py   # trace_connection(diagram_id, start_id, end_id) -> dict
    get_text_region.py    # get_text_in_region(diagram_id, x_min, y_min, x_max, y_max) -> list[str]
    get_overview.py       # get_overview(diagram_id) -> ImageContent
    extract_bom.py        # extract_bom(diagram_id) -> list[dict]
  agent/
    __init__.py
    prompt.py             # SYSTEM_PROMPT constant
    agent.py              # root_agent: LlmAgent definition
    session.py            # DiagramSession: per-request state holder
    context.py            # load_diagram_context(diagram_id) -> session state

docs/
  tool-specs.md           # filled in: JSON schema for each tool, examples

tests/
  test_agent/
    test_tools.py
    test_agent.py
```

### Tool Specifications

All tools must:
- Accept only JSON-serializable primitive arguments (str, int, float — no complex objects)
- Return only JSON-serializable values (dicts, lists, strings)
- Be `async def` functions
- Have Google-style docstrings with `Args:` and `Returns:` sections

**`zoom_tile`**
```python
async def get_tile_image(
    diagram_id: str,
    level: int,          # 0, 1, or 2
    row: int,
    col: int,
) -> dict:
    """Retrieve a specific tile image at the given zoom level and grid position.

    Returns:
        dict with keys:
          "image_base64": str   — JPEG encoded as base64
          "tile_id": str
          "bbox_normalized": dict  — {x_min, y_min, x_max, y_max} in 0-1 coords
          "symbol_ids": list[str]  — symbols visible in this tile
    """
```

**`lookup_component`**
```python
async def lookup_component(
    diagram_id: str,
    component_id: str,
) -> dict:
    """Look up a component by its ID and return its properties.

    Returns:
        dict with keys: "component_id", "symbol_type", "bbox_normalized",
        "connected_to": list[str], "nearby_text": list[str]
    """
```

**`trace_connection`**
```python
async def trace_connection(
    diagram_id: str,
    start_component_id: str,
    end_component_id: str,
) -> dict:
    """Trace the electrical/fluid connection path between two components.

    Returns:
        dict with keys:
          "path_exists": bool
          "intermediate_components": list[str]
          "trace_ids": list[str]
          "confidence": float
    """
```

**`get_text_in_region`**
```python
async def get_text_in_region(
    diagram_id: str,
    x_min: float,   # normalized 0-1
    y_min: float,
    x_max: float,
    y_max: float,
) -> dict:
    """Get all OCR-extracted text within a normalized bounding box region.

    Returns:
        dict with keys:
          "elements": list[{"text": str, "confidence": float, "bbox": dict}]
          "combined_text": str   — all text joined with spaces
    """
```

**`get_overview`**
```python
async def get_overview(diagram_id: str) -> dict:
    """Get the Level-0 overview tile showing the full diagram at low resolution.

    Returns:
        dict with keys: "image_base64": str, "width_px": int, "height_px": int,
        "symbol_count": int, "text_element_count": int
    """
```

**`extract_bom`**
```python
async def extract_bom(diagram_id: str) -> dict:
    """Extract the bill of materials from the pre-processed diagram structure.

    Returns:
        dict with keys:
          "entries": list[{"component_id": str, "reference_designator": str,
                           "description": str, "quantity": int}]
          "total_components": int
    """
```

### ADK Agent Definition (`agent.py`)

```python
from google.adk.agents import LlmAgent
from src.tools import (
    get_tile_image, lookup_component, trace_connection,
    get_text_in_region, get_overview, extract_bom,
)

MODEL = "gemini-2.0-flash"

root_agent = LlmAgent(
    name="cad_diagram_analyzer",
    model=MODEL,
    description="Analyzes CAD diagrams using structured perception data and multimodal vision",
    instruction=SYSTEM_PROMPT,
    tools=[
        get_overview, get_tile_image, lookup_component,
        trace_connection, get_text_in_region, extract_bom,
    ],
)
```

### System Prompt Strategy (`prompt.py`)

The prompt must establish:
1. Role: expert CAD diagram analyst
2. Workflow: always call `get_overview` first → inspect structure → zoom in as needed
3. Data contract: structured JSON is ground truth; vision confirms, not contradicts
4. Output format: structured JSON (BOM, netlist) + plain-language summary
5. Uncertainty: acknowledge when confidence is low; do not hallucinate component IDs

### External Dependencies (Phase 4, additive)

```toml
"google-adk>=1.0.0",
"google-cloud-aiplatform[adk,agent-engines]>=1.93.0",
"google-genai>=1.9.0",
```

### Test Cases (Phase 4)

| Test file | Test | What it checks |
|-----------|------|----------------|
| `test_tools.py` | `test_get_tile_image_returns_base64` | Tool returns valid base64-encoded JPEG string |
| `test_tools.py` | `test_lookup_nonexistent_component` | Returns `{"error": "not found"}`, does not raise |
| `test_tools.py` | `test_get_text_in_region_filters_by_bbox` | Elements outside bbox are excluded |
| `test_tools.py` | `test_trace_connection_no_path` | Two unconnected components → `"path_exists": false` |
| `test_tools.py` | `test_all_tools_return_serializable` | `json.dumps(result)` succeeds for every tool |
| `test_agent.py` | `test_agent_instantiates` | `root_agent` is not None, has correct name and model |
| `test_agent.py` | `test_agent_calls_get_overview_first` | Mock runner confirms `get_overview` is called at start |
| `test_agent.py` | `test_agent_produces_bom` | End-to-end with fixture diagram → response contains BOM-shaped JSON |

### Acceptance Criteria (Phase 4) — **COMPLETED**

- [x] All 5 tools return valid JSON-serializable dicts in all code paths (no exceptions unhandled)
- [x] `CADAnalysisAgent` loads without error in a clean Python environment with ADK installed
- [x] `pytest tests/test_tools/` passes with tools mocked (no Vertex AI calls in CI)
- [x] Tool JSON schemas pass Gemini strict schema validation
- [x] Prompt instructs agent to call `get_overview` before any other tool

> **Evolution note:** The original plan specified 6 tools. The actual
> implementation uses 5 tools with different names: `get_overview`,
> `inspect_zone` (replaces `get_tile_image` + `get_text_in_region`),
> `inspect_component` (replaces `lookup_component`), `search_text`,
> `trace_net` (replaces `trace_connection`). `extract_bom` was deferred.

---

## Phase 5 — End-to-end Orchestration + Cloud Run Deployment {#phase-5}

**Goal:** A single HTTP endpoint that accepts a CAD diagram, runs the full pipeline
(ingest → preprocess → tile → analyze), and returns a structured result. Deployable to
Cloud Run via a one-command script.

### Files to Create / Modify

```
src/
  ingestion/
    handler.py         # IngestionHandler: orchestrates full pipeline for one diagram
  agent/
    server.py          # FastAPI app, /analyze endpoint, health check

Dockerfile
.dockerignore
cloudbuild.yaml        # Cloud Build config for automated deploy
scripts/
  deploy.sh            # local: gcloud run deploy one-liner with all flags
  local_dev.sh         # runs FastAPI dev server with .env loaded
  seed_fixtures.sh     # uploads test fixtures to GCS bucket
```

### API Design

**`POST /analyze`**
```json
Request:
{
  "gcs_uri": "gs://my-bucket/diagrams/schematic.png",
  "diagram_type": "electrical",
  "requester_id": "user-abc"
}

Response (200):
{
  "diagram_id": "uuid",
  "status": "complete",
  "bom": [...],
  "netlist": [...],
  "summary": "This is a 3-phase motor control circuit with...",
  "confidence": 0.87,
  "processing_time_ms": 12430
}

Response (422): validation error
Response (500): {"error": "...", "diagram_id": "uuid"}
```

**`GET /health`**
```json
{"status": "ok", "version": "0.1.0"}
```

**`GET /diagram/{diagram_id}`**
Returns cached `AnalysisResult` from Firestore if already processed.

### `IngestionHandler` Orchestration (`ingestion/handler.py`)

```
async def handle(request: IngestionRequest) -> IngestionResult:
  1. Normalize format → rasterized PNG
  2. Upload original + raster to GCS
  3. Save DiagramMetadata to Firestore
  4. Run PreprocessingPipeline → OCRResult + CVResult
  5. Save OCRResult + CVResult to Firestore
  6. Run TilingEngine.generate_manifest()
  7. Run TilingEngine.generate_tiles()
  8. Run TileUploader.upload_all()
  9. Run root_agent with diagram context loaded
  10. Parse agent response → AnalysisResult
  11. Save AnalysisResult to Firestore
  12. Return IngestionResult
```

Each step is logged with structured logging (`structlog` or Python `logging.getLogger`).
Failures in steps 4-11 do not corrupt Firestore metadata (step 3); they update
`status` field to `"failed"` with error details.

### Dockerfile

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app
ENV UV_LINK_MODE=copy
ENV PYTHONUNBUFFERED=1

# OpenCV system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libsm6 libxext6 libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

ADD . /app
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080

CMD ["uv", "run", "uvicorn", "src.agent.server:app", "--host", "0.0.0.0", "--port", "8080"]
```

> Note: `opencv-python-headless` still requires `libglib2.0-0` on Debian slim images.

### Cloud Run Configuration (`deploy.sh`)

```bash
gcloud run deploy cad-diagram-analyzer \
  --image gcr.io/${PROJECT_ID}/cad-diagram-analyzer:${IMAGE_TAG} \
  --region us-central1 \
  --platform managed \
  --memory 4Gi \
  --cpu 2 \
  --timeout 300 \
  --concurrency 10 \
  --service-account ${SA_EMAIL} \
  --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID},GCS_BUCKET=${BUCKET},FIRESTORE_DB=${DB}"
```

Memory: 4 GiB — OpenCV and Pillow for large images can peak at ~2 GiB.
Timeout: 300 s — a D-size schematic may take 2-3 minutes end-to-end.

### External Dependencies (Phase 5, additive)

```toml
"fastapi>=0.115",
"uvicorn[standard]>=0.30",
"structlog>=24.0",
```

### Test Cases (Phase 5)

| Test file | Test | What it checks |
|-----------|------|----------------|
| `test_server.py` | `test_health_endpoint` | `GET /health` → `{"status": "ok"}` |
| `test_server.py` | `test_analyze_missing_field` | Request without `gcs_uri` → 422 |
| `test_server.py` | `test_analyze_full_pipeline_mocked` | All downstream services mocked; endpoint returns 200 with BOM |
| `test_server.py` | `test_get_diagram_cached` | Firestore returns cached result; agent not invoked again |
| `test_server.py` | `test_analyze_preprocessing_failure` | Document AI mock raises; response is 500 with error field |
| `test_ingestion/test_handler.py` | `test_handler_orchestration_order` | Steps called in correct sequence via mock call order |
| `test_ingestion/test_handler.py` | `test_handler_saves_error_on_agent_failure` | Agent failure → Firestore `status="failed"` written |

### Acceptance Criteria (Phase 5) — **COMPLETED** (partial — Cloud Run not yet deployed)

- [x] `POST /analyze` returns 200 with agent response on real diagrams (end-to-end, live GCP)
- [ ] `docker build` succeeds on `linux/amd64` (Cloud Run target arch) — *deferred*
- [ ] Container starts in < 5 s cold start — *deferred*
- [ ] Deployed Cloud Run service returns HTTP 200 on `GET /health` — *deferred*
- [ ] Deployed service processes diagrams end-to-end in < 5 minutes — *deferred*
- [x] `pytest` full suite passes with all GCP calls mocked

> **Evolution note:** Phase 5 was completed for local development. The FastAPI
> server runs with `POST /ingest`, `POST /analyze`, `GET /visualization/{id}`,
> and a built-in web UI. Cloud Run deployment is deferred to production readiness.

---

## Technical Risks {#technical-risks}

### Risk 1 — Document AI OCR Quality on Scanned CAD (HIGH)
**Problem:** CAD diagrams are often scanned at low quality or exported from DWG at
non-standard DPI. Document AI's general OCR processor may miss small labels
(tag numbers, wire designators) that are critical for netlist extraction.
**Mitigation:**
- Pre-process with OpenCV: deskew, denoise, sharpen before sending to Document AI
- Experiment with Document AI `FORM_PARSER_PROCESSOR` vs `OCR_PROCESSOR`; the former
  handles tabular data (title blocks) better
- Fallback: `pytesseract` for local OCR of specific regions if Document AI confidence < 0.5
- **Decision needed:** What minimum OCR quality is acceptable for MVP?

### Risk 2 — Symbol Detection Without Training Data (HIGH)
**Problem:** Contour-based symbol detection will have low precision on real CAD diagrams
that use non-standard or custom symbol libraries. False positives (noise mistaken for
symbols) and false negatives (complex symbols missed) are both likely.
**Mitigation:**
- Start with conservative contour thresholds and rely on OCR for component identification
- Use `symbol_type = "unknown"` rather than guessing; let the LLM reason about unknown shapes
- Plan a labeling sprint after pilot: collect 50-100 annotated symbols for a future
  fine-tuned detector (YOLOv8 or similar)
- **Decision needed:** Is "unknown symbol, LLM classifies by vision" acceptable for V1?

### Risk 3 — ADK Tool Schema Strictness (MEDIUM)
**Problem:** Gemini function calling requires strict JSON schemas. Any Python type that
doesn't map cleanly to JSON Schema (e.g., `tuple`, `Path`, `datetime`) will cause
silent failures or validation errors at runtime.
**Mitigation:**
- All tool signatures use only `str`, `int`, `float`, `bool`, `list`, `dict`
- Return types always `dict` (never custom Pydantic models directly)
- Add a schema validation test in Phase 4 using `google.genai` schema checker
- Document the exact JSON schema for each tool in `docs/tool-specs.md`

### Risk 4 — Token Budget for Large Diagram Structured JSON (MEDIUM)
**Problem:** A D-size schematic may have 500+ components, 1000+ text elements, and
200+ traces. Serializing the full `PreprocessingOutput` into the agent context will
consume 10k-50k tokens, leaving little budget for reasoning and responses.
**Mitigation:**
- Do not pass full preprocessing JSON in the system prompt; store in Firestore and
  retrieve on demand via tools
- `get_overview` returns a summary count (not full component list)
- `lookup_component` and `get_text_in_region` are lazy — fetch only what's needed
- If token pressure remains: implement a RAG-style component index with embeddings

### Risk 5 — OpenCV Performance on Large Images in Cloud Run (MEDIUM)
**Problem:** OpenCV operations on a 7000×5000 px image (a standard D-size at 300 DPI)
can take 30-60 s and require significant memory. Cloud Run's default 512 MiB is insufficient.
**Mitigation:**
- Cloud Run spec calls for 4 GiB (see Phase 5 deploy config)
- Resize to max 4000px on longest side before CV pipeline (preserve enough detail)
- Profile with `cProfile` during Phase 2 and optimize bottlenecks before deployment
- Consider Cloud Run `--cpu 2` for parallel Hough transform

### Risk 6 — DWG/DXF Format Support (LOW for MVP)
**Problem:** The architecture lists DWG and DXF as input formats, but open-source
DWG parsing is poor (DWG is proprietary). `ezdxf` handles DXF reasonably but not DWG.
**Mitigation:**
- MVP scope: support only PNG, TIFF, PDF (rasterized via `pdf2image`)
- DWG: document as out-of-scope for pilot; requires ODA File Converter or paid library
- DXF: implement in Phase 1 normalizer using `ezdxf` but flag as experimental
- **Decision needed:** Confirm accepted input formats for the pilot.

### Risk 7 — Tile Overlap at Image Edges (LOW)
**Problem:** Edge tiles (touching image boundary) cannot extend beyond the image. If
overlap is asymmetric (only inward), components near the edge may appear in fewer
tiles than expected, potentially being missed.
**Mitigation:**
- Per CLAUDE.md: overlap ≥ 20%; this is a floor, not a target
- Edge tiles: clamp to image boundary; do not pad with black (padding confuses CV)
- Ensure Level 0 overview always captures the full image; edge components visible there

---

## Open Questions {#open-questions}

| # | Question | Owner | Impact if unresolved |
|---|----------|-------|----------------------|
| 1 | **Input format scope:** Are DWG files in scope for the pilot, or PNG/TIFF/PDF only? | Product | Affects Phase 1 normalizer complexity and timeline |
| 2 | **Document AI provisioning:** Is a Document AI processor already created in the GCP project? What processor type (OCR vs Form Parser)? | Infra | Blocks Phase 2 start |
| 3 | **Symbol library:** Do we have a set of standard CAD symbols to use as templates? What diagram standards are in scope (IEC 60617, ANSI Y32, ISO 10628)? | Domain | Affects symbol detection precision in Phase 2 |
| 4 | **Latency SLA:** Is a 2-5 minute end-to-end processing time acceptable, or is near-realtime (<30 s) required? | Product | Drives architecture (sync vs async job queue) |
| 5 | **Multi-page PDFs:** A P&ID PDF may have 20+ pages. Should each page be analyzed independently or cross-page connections traced? | Product | Significant scope change if cross-page required |
| 6 | **GCS bucket and Firestore DB names:** What are the GCP project ID, bucket name, and Firestore database ID for the pilot? | Infra | Needed for `.env.example` and deploy scripts |
| 7 | **Authentication:** Should the `/analyze` endpoint be publicly accessible or require GCP identity token (IAP or service account auth)? | Security | Affects Cloud Run `--allow-unauthenticated` flag |
| 8 | **Output consumers:** Will the `AnalysisResult` be consumed by a downstream system (e.g., CMMS, BIM tool), or is human review via summary the end goal for the pilot? | Product | Influences BOM/netlist schema precision requirements |
| 9 | **Gemini model version:** `gemini-2.0-flash` is the default; is there a preference for `gemini-2.5-pro` for better reasoning, or is `flash` sufficient given the structured data pre-processing? | Arch | Cost and latency trade-off |
| 10 | **Concurrent diagram processing:** Should multiple diagrams be processed in parallel, or is this a single-user pilot with sequential processing? | Arch | Affects Cloud Run concurrency setting and Firestore write patterns |

---

## Dependency Graph {#dependency-graph}

```
Phase 1 (Models + Skeleton)
    │
    ├──► Phase 2 (OCR + CV)           — depends on: models/ocr.py, models/cv.py, gcs_adapter
    │         │
    │         └──► Phase 3 (Tiling)   — depends on: models/tiling.py, gcs_adapter, Phase 2 output schema
    │                   │
    └─────────────────► Phase 4 (Agent + Tools)   — depends on: all models, all Phase 2/3 outputs
                              │
                              └──► Phase 5 (Server + Deploy)  — depends on: all prior phases
```

Phases 2 and 3 can be developed in parallel once Phase 1 is complete.
Phase 4 tool stubs can be written before Phase 2/3 are fully implemented (using mocked data).

---

## Phase Summary Table

| Phase | Output | Key Risk | Completion Signal | Status |
|-------|--------|----------|-------------------|--------|
| 1 | All models + pyproject.toml | None significant | `mypy` + `pytest test_models.py` green | **Done** |
| 2 | `DiagramMetadata` from real image | OCR quality | Pipeline produces ≥1 symbol + text from fixture | **Done** |
| 3 | 21 tiles with manifest | Edge tile clamping | All 21 tiles generated, overlap verified by test | **Done** |
| 4 | Working `LlmAgent` with 5 tools | Schema strictness | Agent answers fixture question without tool errors | **Done** |
| 5 | Local server + web UI returning analysis | Token budget | `POST /analyze` returns 200 on real diagrams | **Done** (local) |

---

## Implementation Status {#implementation-status}

**Last updated:** 2026-03-14

### What Was Built

All five phases were implemented and are operational in local development mode:

1. **14 Pydantic data models** across 8 modules — `BoundingBox`, `Component`,
   `Pin`, `TextLabel`, `Trace`, `TitleBlock`, `Symbol`, `DetectedLine`,
   `CVResult`, `DiagramMetadata`, `Tile`, `TileLevel`, `TilePyramid`, plus
   analysis models
2. **Full preprocessing pipeline** — Document AI OCR + OpenCV CV pipeline +
   title block extraction, with no-op stubs for offline development
3. **3-level tile pyramid** (21 tiles) with 20%+ overlap, component/label
   spatial indexing
4. **5 agent tools** — `get_overview`, `inspect_zone`, `inspect_component`,
   `search_text`, `trace_net`
5. **FastAPI server** with `POST /ingest`, `POST /analyze`,
   `GET /visualization/{id}`, built-in web UI, and Swagger docs

### Beyond the Original Plan

The implementation included several enhancements not in the original plan:

| Enhancement | Description |
|-------------|-------------|
| **Set-of-Marks (SOM) annotation** | Tile images annotated with numbered red bounding boxes for precise LLM grounding |
| **Pixel coordinates** | All tool responses include pixel-coordinate bounding boxes alongside normalized coords |
| **Interactive HTML visualization** | Self-contained HTML with SVG overlays, searchable sidebar, hover-to-highlight |
| **Retry with exponential backoff** | Transient Gemini errors (429, 503) retried up to 3× with 2s→4s→8s backoff |
| **Dual-model support** | `GEMINI_MODEL` for orchestration, optional `TOOL_MODEL` for vision tasks |
| **Token budget management** | JPEG encoding, tile caps (3), label caps (50), match caps (100) |
| **Graceful tool fallbacks** | `trace_net` returns structured "unavailable" when no data; `inspect_zone` falls back to crop |
| **`strip_json_markdown_fence`** | Utility to clean code-fence-wrapped JSON from Gemini responses |

### What Was Deferred

| Item | Reason |
|------|--------|
| `extract_bom` tool | Not needed for MVP; agent can reason about BOM from other tools |
| Cloud Run deployment | Dockerfile and deploy scripts exist but haven't been tested in CI |
| GCS + Firestore storage backend | Using `InMemoryDiagramStore` + `LocalStorage` for now |
| DWG/DXF format support | Out of scope for pilot; only raster formats accepted |
| BigQuery integration | Reviewed from colleague's implementation; deferred for V2 |

### Open Questions Resolved

| # | Question | Resolution |
|---|----------|-----------|
| 1 | Input format scope | PNG, JPEG, TIFF only for pilot |
| 2 | Document AI provisioning | OCR processor `fc558a9dcb62447` created in `vertex-ai-demos-468803` |
| 6 | GCS bucket and Firestore DB | `cad-diagram-bucket` and `cad-diagram-db` in `vertex-ai-demos-468803` |
| 9 | Gemini model version | `gemini-2.5-flash` default, `gemini-2.5-pro` available via `TOOL_MODEL` |
