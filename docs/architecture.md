# System Architecture

## Overview

The CAD Diagram Analyzer separates **perception** (deterministic OCR + computer
vision) from **reasoning** (multimodal LLM). The pipeline runs in five phases,
with each phase producing well-defined artefacts that feed the next.

```
                                ┌──────────────────────────────┐
                                │         Web UI / API          │
                                │    POST /ingest, /analyze     │
                                │    GET /visualization/{id}    │
                                └─────────────┬────────────────┘
                                              │
                                              ▼
┌────────────┐   ┌──────────────────┐   ┌───────────────┐   ┌───────────────┐
│  Phase 1   │──▶│    Phase 2       │──▶│   Phase 3     │──▶│   Phase 4     │
│ Ingestion  │   │ Pre-processing   │   │   Tiling      │   │ Agent + Tools │
│            │   │ OCR + CV + TB    │   │               │   │               │
└────────────┘   └──────────────────┘   └───────────────┘   └───────────────┘
      │                  │                     │                     │
      ▼                  ▼                     ▼                     ▼
  PIL Image       DiagramMetadata        TilePyramid           Agent Response
 (RGB, any      (components, labels,    (21 tiles with       + Interactive HTML
  format)        traces, title block)    SOM annotations)      Visualization
```

---

## Phase 1: Ingestion

- **Input:** Raw image upload (PNG, JPEG, TIFF) via HTTP multipart or local path
- **Processing:** Decode to RGB PIL Image, assign UUID `diagram_id`
- **Output:** In-memory PIL Image ready for preprocessing
- **Entry point:** `Orchestrator.ingest()` in `src/orchestrator.py`
- **HTTP endpoint:** `POST /ingest` → returns `{ diagram_id, success }`

> DWG/DXF support is out of scope for the pilot. Only raster formats are accepted.

---

## Phase 2: Pre-Processing (No LLM)

All perception runs deterministically without LLM involvement.

### OCR — Document AI
- Google Cloud Document AI `OCR_PROCESSOR` extracts text with bounding boxes
- Bounding boxes are returned in normalized 0–1 coordinates
- Low-confidence elements (< 0.6) are filtered; duplicates deduplicated by IoU ≥ 0.85
- **Output:** `list[TextLabel]` — each with `text`, `confidence`, `bbox`

### Computer Vision — OpenCV
- **Line detection:** Grayscale → Gaussian blur → adaptive threshold → Canny → HoughLinesP
- **Symbol detection:** Contour-based detection → classify by shape ratio and aspect ratio
- **Output:** `CVResult` with `symbols` (list of `Symbol`), `detected_lines`, `junctions`
- CV symbols are mapped to `Component` objects in the pipeline (`pipeline.py`)

### Title Block Extraction
- Locates the title block by scanning image corners for large rectangular regions
- Parses OCR elements within the title block bbox into structured fields
- **Output:** `TitleBlock` or `None`

### Pipeline Orchestration
- OCR (async) and CV (sync via `asyncio.to_thread`) run concurrently
- Title block extraction runs after OCR completes (needs text labels)
- **Entry point:** `PreprocessingPipeline.run()` in `src/preprocessing/pipeline.py`
- **Output:** `DiagramMetadata` with all extracted artefacts

### Fallback Behaviour
When Document AI credentials or processor ID are not configured, the server
falls back to no-op OCR/CV stubs. The agent still functions using visual
analysis of the diagram image but without structured data support.

---

## Phase 3: Multi-Resolution Tiling

Generates a 3-level tile pyramid so the agent can zoom from overview to detail:

| Level | Grid | Tiles | Coverage per tile | Overlap |
|-------|------|-------|-------------------|---------|
| 0 | 1×1 | 1 | Full diagram | N/A |
| 1 | 2×2 | 4 | ~60% of dimension | 20% |
| 2 | 4×4 | 16 | ~35% of dimension | 20% |

**Total: 21 tiles per diagram.**

### Key Design Decisions

- **20% overlap** ensures no component is split at tile boundaries (per CLAUDE.md)
- **Edge tiles** are clamped to image boundary — no black padding (confuses CV)
- Each tile records which `component_ids` and `text_label_ids` fall within it
- Tiles are stored via `TileStorage` (local filesystem for dev, GCS for production)
- **Entry point:** `TileGenerator.generate()` in `src/tiling/tile_generator.py`

---

## Phase 4: Agentic Reasoning

### Agent Architecture

The agent is a Google ADK `LlmAgent` backed by Gemini 2.5 Flash (configurable).

```python
# src/agent/cad_agent.py
LlmAgent(
    model="gemini-2.5-flash",
    name="cad_analysis_agent",
    tools=[get_overview, inspect_zone, inspect_component, search_text, trace_net],
    global_instruction=GLOBAL_INSTRUCTION,
    instruction=AGENT_INSTRUCTION,
    before_tool_callback=before_tool,
    after_tool_callback=after_tool,
)
```

### Agent Workflow

1. The agent receives the diagram image (JPEG, 768px, quality=85) as an `inline_data` Part
   alongside the user's natural-language query and the diagram ID.
2. **Always calls `get_overview()` first** — confirms dimensions, component/label counts,
   title block. Even when structured data is empty, this orients the agent.
3. Uses `inspect_zone()` to zoom into regions of interest with SOM-annotated tile images.
4. Uses `inspect_component()` for deep-dives on specific components.
5. Uses `search_text()` to locate specific labels, values, or reference designators.
6. Uses `trace_net()` to follow electrical/fluid connections between components.

### Set-of-Marks (SOM) Visual Grounding

Inspired by the research paper ["Towards Understanding Visual Grounding in
Vision-Language Models"](https://arxiv.org/abs/2509.10345):

- Tile images from `inspect_zone()` are annotated with **numbered red bounding boxes**
  labeled [1], [2], [3], etc.
- Each marker maps to a component or text label with its type, text, and pixel-coordinate
  bounding box.
- The agent references elements by marker number: *"Marker [3] shows a resistor labeled 'R47'"*
- This provides precise, verifiable grounding and reduces hallucination.

### Dual-Model Support

- **`GEMINI_MODEL`** (default `gemini-2.5-flash`) — orchestration, tool calling, reasoning
- **`TOOL_MODEL`** (optional, e.g. `gemini-2.5-pro`) — reserved for vision-heavy tool calls
  that need higher visual acuity

### Retry with Exponential Backoff

Transient Vertex AI errors (429 rate limit, 503 unavailable, quota exceeded) are retried
up to 3 times with exponential backoff: 2s → 4s → 8s (capped at 30s). Each retry uses
a unique session ID to avoid stale ADK state.

### Token Budget Management

CAD diagrams can produce large tool responses. Several controls prevent exceeding
Gemini's 1M token context limit:

| Control | Value | Saves |
|---------|-------|-------|
| Initial image format | JPEG at 768px (not PNG at 1024px) | ~100–300K tokens/turn |
| `inspect_zone` tile cap | Max 3 tiles per call | ~200K tokens/call |
| `inspect_zone` tile resolution | Max 512px per tile | ~50K tokens/tile |
| `inspect_zone` label cap | Max 50 text labels per zone | ~20K tokens/call |
| `search_text` match cap | Max 100 matches per search | ~50K tokens/call |
| `get_overview` | No image — structured data only | ~400K tokens saved |

---

## Phase 5: Output

### Analysis Response
- Natural-language textual analysis from the agent
- Spatially-grounded findings citing marker numbers and regions
- Confidence levels for each observation

### Interactive Visualization
- Self-contained HTML with the diagram image and SVG bounding-box overlays
- Red overlays for components, blue for text labels
- Searchable sidebar listing all detected elements
- Hover-to-highlight and click-to-pin interaction
- **Endpoint:** `GET /visualization/{diagram_id}`
- **Frontend integration:** Link appears after analysis in the web UI

---

## Data Flow

```
User Upload (PNG/JPEG/TIFF)
    │
    ▼
Orchestrator.ingest()
    ├── Decode to PIL Image (RGB)
    ├── PreprocessingPipeline.run()
    │       ├── DocumentAIOCRExtractor.extract()  →  list[TextLabel]
    │       ├── CVPipeline.run()                  →  CVResult (symbols, lines)
    │       ├── Map CV symbols → Component objects
    │       └── TitleBlockExtractor.extract()      →  TitleBlock | None
    ├── TileGenerator.generate()                   →  TilePyramid (21 tiles)
    └── Store: metadata + pyramid + images         →  InMemoryDiagramStore
    │
    ▼
Orchestrator returns diagram_id
    │
    ▼
CADAnalysisAgent.analyze_async()
    ├── Load diagram image as JPEG inline_data Part (768px)
    ├── Create ADK InMemoryRunner + session
    ├── Agent calls tools: get_overview → inspect_zone → ...
    │       └── Tools read from DiagramStore singleton
    └── Return final text response (with retry on transient errors)
    │
    ▼
export_visualization()  (optional)
    └── Self-contained HTML with SVG overlays
```

---

## Storage Architecture

### Local Development (current)
- **`InMemoryDiagramStore`** — Python dicts holding metadata, pyramids, tile images, originals
- **`LocalStorage`** — tiles written to `/tmp/cad-diagram-analyzer/tiles/`
- All data is lost on server restart

### Production (planned)
- **Google Cloud Storage** — original images + tile pyramid JPEGs
- **Cloud Firestore** — DiagramMetadata, TilePyramid manifests, analysis results
- Swap `InMemoryDiagramStore` for Firestore-backed implementation; no tool code changes

---

## Server Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest` | Upload image → run pipeline → return `diagram_id` |
| `POST` | `/analyze` | Run ADK agent on a pre-ingested diagram |
| `GET` | `/visualization/{id}` | Interactive HTML visualization |
| `GET` | `/docs` | Swagger UI (auto-generated by FastAPI) |
| `GET` | `/` | Static web UI frontend |
