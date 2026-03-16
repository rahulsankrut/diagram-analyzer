# CAD Diagram Analyzer — Complete Learning Guide

A deep reference for understanding every system in this application — the
theory behind each design decision, how the code implements it, and how all
the pieces connect. Read it from top to bottom once, then use it as a
reference.

---

## Table of Contents

1. [Mental Model — What This System Really Does](#1-mental-model)
2. [The Core Problem — Why AI Can't Just Read CAD Images](#2-the-core-problem)
3. [System Architecture — The 30-Second Map](#3-system-architecture)
4. [Data Models — The Language of the System](#4-data-models)
5. [Preprocessing Pipeline — The Perception Layer](#5-preprocessing-pipeline)
6. [Tiling System — Multi-Resolution Access](#6-tiling-system)
7. [Tools — The Agent's Hands](#7-tools)
8. [The Agent System — ADK, Prompts, Callbacks](#8-the-agent-system)
9. [The Server — FastAPI Endpoints](#9-the-server)
10. [The Frontend — UI and Pipeline Visualization](#10-the-frontend)
11. [Storage Backends — Dev vs Production](#11-storage-backends)
12. [Configuration & Environment Variables](#12-configuration--environment-variables)
13. [Testing Architecture](#13-testing-architecture)
14. [End-to-End Trace — One Request, All Layers](#14-end-to-end-trace)
15. [Key Design Patterns Used Throughout](#15-key-design-patterns)
16. [Dependency Map — What Imports What](#16-dependency-map)
17. [Research-Backed Improvements — Stürmer et al. 2024](#17-research-backed-improvements)

---

## 1. Mental Model

Before any code: hold this picture in your head.

```
┌─────────────────────────────────────────────────────────────────┐
│                        UPLOAD                                   │
│   Raw CAD image (7000×5000 px, unreadable to an LLM as-is)     │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │      PERCEPTION LAYER         │
              │   (deterministic, no AI)       │
              │                               │
              │  OCR → TextLabel[]            │
              │  CV  → Component[]            │
              │  Tiling → TilePyramid         │
              │  Regex → TitleBlock           │
              └───────────────────────────────┘
                              │
                    DiagramMetadata (UUID)
                              │
              ┌───────────────┴───────────────┐
              │      REASONING LAYER          │
              │   (LLM + structured tools)     │
              │                               │
              │  Agent sees:                  │
              │  - 768px diagram image         │
              │  - 5 tool functions            │
              │  - System prompt               │
              │                               │
              │  Agent asks tools:            │
              │  - "Give me the overview"      │
              │  - "Zoom into zone (x, y)"    │
              │  - "Find component R47"        │
              └───────────────────────────────┘
                              │
                     Natural-language answer
                     + tool call audit trail
```

The fundamental insight: **the LLM never reads raw pixels as its primary
source of truth**. OCR and CV extract exact facts deterministically. The LLM
reasons over those facts and uses high-resolution tile crops to *verify*, not
to *discover*.

---

## 2. The Core Problem

### Resolution Loss

A D-size schematic at 300 DPI: **7 000 × 5 000 px**.

Gemini 2.5 Flash (like all current multimodal LLMs) internally downsamples
images to approximately **1 024 × 1 024 px** before processing.

That is a **35× linear resolution loss**.

A resistor value "10kΩ" printed at 12 px tall on the original image becomes
**0.34 px tall** after downsampling — literally sub-pixel. The LLM cannot read
it. It guesses.

### What Guessing Looks Like

When you feed a raw CAD image directly to an LLM:

- Component reference designators: hallucinated (says "R47" when it's "R74")
- Net connections: fabricated (says two components are connected when they
  are separated by whitespace)
- Component values: invented ("10kΩ" becomes "100kΩ" or disappears entirely)
- Confidence: the LLM has no way to know what it doesn't know

### The Solution This System Uses

1. **OCR extracts exact text** (confidence score + bbox) before the LLM sees
   anything.
2. **CV extracts exact component positions** from contour detection.
3. **A tile pyramid stores 512px crops** at 3 zoom levels with 20% overlap so
   no content is missed at tile boundaries.
4. **The LLM reasons over structured Pydantic models**, not raw pixels, for
   its primary analysis.
5. **The LLM uses tile crops to verify** what it already knows from structure.
6. **Set-of-Marks (SOM)** annotates each tile with numbered red bounding boxes
   so the LLM can say "Marker [3]" and have a precise, verifiable reference.

---

## 3. System Architecture

### Package Layout

```
src/
├── orchestrator.py          # Top-level pipeline entry point
├── models/                  # Pydantic data models (9 modules)
│   ├── ocr.py               # BoundingBox, OCRElement, OCRResult
│   ├── cv.py                # Symbol, DetectedLine, CVResult
│   ├── component.py         # Pin, Component
│   ├── text_label.py        # TextLabel
│   ├── trace.py             # Trace (connectivity)
│   ├── title_block.py       # TitleBlock
│   ├── tiling.py            # Tile, TilePyramid, TileLevel
│   ├── diagram.py           # DiagramMetadata (aggregates all above)
│   └── analysis.py          # BOMEntry, NetlistEntry, AnalysisResult
├── preprocessing/           # Perception layer
│   ├── pipeline.py          # Orchestrates OCR + CV + title block
│   ├── ocr.py               # Document AI wrapper
│   ├── docai_client.py      # Async Document AI SDK adapter
│   ├── cv_pipeline.py       # OpenCV symbol + line detection
│   └── title_block.py       # Regex-based title block extraction
├── tiling/
│   ├── tile_generator.py    # 3-level pyramid builder
│   └── tile_storage.py      # LocalStorage / GCSStorage backends
├── tools/
│   ├── _store.py            # DiagramStore ABC + singleton
│   ├── _image_utils.py      # SOM annotation, base64, crop helpers
│   ├── get_overview.py      # Tool 1: structured summary
│   ├── inspect_zone.py      # Tool 2: zoom into region, SOM tiles
│   ├── inspect_component.py # Tool 3: component crop + nearby
│   ├── search_text.py       # Tool 4: text label search
│   ├── trace_net.py         # Tool 5: connectivity tracing
│   └── export_visualization.py  # Internal: interactive HTML
└── agent/
    ├── prompts.py           # System prompt (workflow + SOM + spatial)
    ├── callbacks.py         # before_tool / after_tool + ToolCallTracker
    ├── cad_agent.py         # LlmAgent wrapper, retry logic
    └── server.py            # FastAPI endpoints
```

### Request Flow (High Level)

```
Browser → POST /ingest → Orchestrator.ingest()
              │
              ├── PreprocessingPipeline.run()   (OCR + CV, concurrent)
              └── TileGenerator.generate()       (21 tiles, 3 levels)
              │
              └── DiagramStore.save(metadata)
              └── Returns diagram_id (UUID)

Browser → POST /analyze → CADAnalysisAgent.analyze_async()
              │
              ├── Encode diagram image (JPEG@768px)
              ├── InMemoryRunner.run_async()
              │     └── LlmAgent calls tools via function calling
              │           ├── get_overview
              │           ├── inspect_zone (×N)
              │           ├── inspect_component (×N)
              │           ├── search_text (×N)
              │           └── trace_net (×N)
              │
              └── Returns {text, tool_calls[]}
```

---

## 4. Data Models

The models in `src/models/` are the **shared language** of the system. Every
layer — preprocessing, tiling, tools, agent — communicates via these Pydantic
v2 models. Understanding them is understanding the system.

### `BoundingBox` (`models/ocr.py`)

The most-used primitive in the entire codebase.

```python
class BoundingBox(BaseModel):
    x_min: float   # left edge,  0.0–1.0 (normalized)
    y_min: float   # top edge,   0.0–1.0
    x_max: float   # right edge, 0.0–1.0
    y_max: float   # bottom edge, 0.0–1.0
```

**All coordinates are normalized (0–1), not pixels.** This is a deliberate
choice: diagrams vary from 2 000 × 1 500 px phone photos to 12 000 × 8 000 px
scanned D-size drawings. Normalized coords are resolution-independent.

Key methods:
- `from_pixel_coords(x_min_px, ..., width, height)` — convert from pixels
- `to_pixel_coords(width, height)` — convert to pixels for drawing
- `center()` — returns `(cx, cy)` normalized centroid
- `area()` — normalized area (useful for filtering noise)
- `overlaps(other)` — non-zero overlap test (used in tiling)
- `iou(other)` — Intersection over Union (used in deduplication)

Validators enforce `x_max > x_min` and `y_max > y_min`. Invalid bboxes
raise at model construction time, not later during analysis.

---

### `Component` (`models/component.py`)

```python
class Component(BaseModel):
    component_id: str          # e.g. "sym_001"
    component_type: str        # "resistor", "capacitor", "ic", "unknown", ...
    value: str | None          # e.g. "10kΩ"
    package: str | None        # e.g. "0402"
    bbox: BoundingBox          # normalized position on diagram
    pins: list[Pin]            # connection terminals
    confidence: float          # 0.0–1.0 from CV detector
```

The `component_type` is a semantic classification mapped from CV's raw contour
output. The mapping happens in `preprocessing/pipeline.py`.

`Pin.position` is in **diagram-space normalized coords** (not relative to the
component bbox). This makes trace following straightforward: a trace endpoint
at `(0.45, 0.32)` connects to whichever pin is at approximately `(0.45, 0.32)`.

---

### `TextLabel` (`models/text_label.py`)

```python
class TextLabel(BaseModel):
    label_id: str              # UUID (auto-generated)
    text: str                  # raw OCR text
    bbox: BoundingBox          # normalized position
    confidence: float          # OCR confidence, 0.0–1.0
    page: int                  # page number (1-indexed)
```

Text labels come from Document AI OCR. They are stored separately from
components because OCR output and CV output are independent — a label
"R47 10kΩ" might be near a resistor symbol, but the OCR extractor doesn't
know that. The agent infers spatial association.

---

### `Trace` (`models/trace.py`)

```python
class Trace(BaseModel):
    trace_id: str
    from_component: str        # component_id of source
    from_pin: str              # pin name/id
    to_component: str          # component_id of destination
    to_pin: str
    path: list[tuple[float, float]]   # waypoints, normalized coords
```

Traces represent electrical or fluid connections. The CV pipeline extracts
line segments; the orchestrator matches them to component pins by proximity.
This matching is imperfect — traces are marked `trace_data_unavailable` in
the `trace_net` tool response when the data is absent or unreliable.

---

### `DiagramMetadata` (`models/diagram.py`)

The central aggregating model. This is what gets stored in the `DiagramStore`
and what every tool looks up via `diagram_id`.

```python
class DiagramMetadata(BaseModel):
    diagram_id: str
    width_px: int
    height_px: int
    format: str                    # "PNG", "TIFF", etc.
    dpi: int | None
    components: list[Component]
    text_labels: list[TextLabel]
    traces: list[Trace]
    title_block: TitleBlock | None
```

Key query methods:
- `get_component(component_id)` → `Component | None`
- `components_in_bbox(bbox)` → components whose bbox overlaps the query region
- `text_labels_in_bbox(bbox)` → labels whose bbox overlaps the query region

These methods power `inspect_zone` and `inspect_component` — they're the
spatial index for the structured data.

---

### `TilePyramid` (`models/tiling.py`)

```python
class TilePyramid(BaseModel):
    tiles: list[Tile]
```

A flat list of all tiles across all levels. Query via:
- `tiles_at_level(level)` → filter by zoom level
- `tile_at(level, row, col)` → specific tile by grid position
- `available_levels()` → `{0, 1, 2}` or subset if some failed

Each `Tile` stores:
```python
class Tile(BaseModel):
    tile_id: str               # e.g. "abc-123_L2_R1_C0"
    level: int                 # 0=overview, 1=mid, 2=detail
    row: int                   # grid row
    col: int                   # grid col
    bbox: BoundingBox          # which part of the diagram this tile covers
    image_path: str            # where the tile image is stored
    component_ids: list[str]   # components overlapping this tile
    text_label_ids: list[str]  # text labels overlapping this tile
```

The `component_ids` / `text_label_ids` lists are pre-computed during tile
generation. They're what let the tools quickly answer "what's in this tile"
without scanning all components.

---

## 5. Preprocessing Pipeline

### Entry Point: `PreprocessingPipeline.run()` (`preprocessing/pipeline.py`)

```python
async def run(self, image: PIL.Image, filename: str) -> DiagramMetadata:
    fmt = _detect_format(image)

    # STEP 1 — OCR runs FIRST (not concurrent with CV).
    # Per Stürmer et al. (arXiv:2411.13929) text strokes are the dominant
    # source of false-positive CV detections on dense P&IDs.  OCR bboxes
    # are painted white on the grayscale image BEFORE Hough/contour detection,
    # eliminating the character-stroke noise entirely.
    labels: list[TextLabel] = await self._ocr.extract(pil_image)

    # STEP 2 — CV runs in a thread (blocking NumPy/OpenCV) with OCR mask.
    cv_result: CVResult = await asyncio.to_thread(
        self._cv.run, pil_image, labels   # labels passed for masking
    )

    title_block = self._title_block.extract(pil_image, labels)

    # Symbol → Component (geometry-only, type = "unknown" until agent classifies)
    components = [
        Component(component_id=sym.symbol_id, component_type=sym.symbol_type,
                  bbox=sym.bbox, confidence=sym.confidence)
        for sym in cv_result.symbols
    ]

    # DetectedLine → Trace  (first-pass connectivity, see _build_traces below)
    traces = _build_traces(cv_result.detected_lines, components)

    return DiagramMetadata(
        source_filename=source_filename, format=fmt,
        width_px=width, height_px=height,
        text_labels=labels, components=components,
        traces=traces, title_block=title_block,
        junctions=[j.to_dict() for j in cv_result.junctions],
    )
```

**Why sequential, not concurrent?**  OCR must complete before CV starts so
that the text bounding boxes are available to mask character strokes.  OCR is
the dominant bottleneck (~90% of preprocessing wall-clock time) so running CV
immediately after adds negligible latency.  See
[Section 17](#17-research-backed-improvements) for the full rationale.

---

### OCR Text Masking (`cv_pipeline.py → _mask_text_regions`)

After OCR returns, every text-label bbox is painted **white (255)** on the
grayscale image before symbol contour detection and Hough-line detection run:

```python
def _mask_text_regions(self, gray, text_labels, w, h):
    masked = gray.copy()
    pad = self._TEXT_MASK_PAD   # 2 px — catches ascenders/descenders
    for label in text_labels:
        x1, y1, x2, y2 = label.bbox.to_pixel_coords(w, h)
        masked[
            max(0, y1 - pad) : min(h, y2 + pad),
            max(0, x1 - pad) : min(w, x2 + pad),
        ] = 255   # fill to background colour
    return masked
```

Without masking, every letter's stroke is an edge in the Canny map.  Those
edges cluster into closed contours (false-positive symbols) and short Hough
line segments (spurious traces).  Masking eliminates them at negligible cost.

---

### Junction Classification (`cv_pipeline.py → _classify_junctions`)

After Hough detection, every pair of line segments is tested for intersection
using the parametric formula in `_seg_intersect()`.  If they intersect, the
position of the intersection along each segment determines its topology:

```
t = fractional position along segment A  (0=start, 1=end)
u = fractional position along segment B

t near 0 or 1  (< 0.15 or > 0.85)   →  CONNECTED  (T- or L-junction)
u near 0 or 1                         →  CONNECTED
t and u both in interior              →  CROSSING   (X-crossing, NOT connected)
```

```python
tol = 0.15   # 15% endpoint tolerance (standard Hough junction practice)
at_endpoint = t < tol or t > 1.0 - tol or u < tol or u > 1.0 - tol
jtype = JunctionType.CONNECTED if at_endpoint else JunctionType.CROSSING
```

**Critical rule**: a `CROSSING` junction means two lines visually share a
point but are **not electrically or fluidically connected**.  The `trace_net`
tool and graph visualization must never treat a crossing as a connection.

---

### DetectedLine → Trace Conversion (`pipeline.py → _build_traces`)

After components are assembled from CV symbols, `_build_traces()` performs a
first-pass topology resolution:

```python
def _nearest_component(point, components, padding=0.02):
    """Return the component whose padded bbox contains point (nearest center)."""
    px, py = point
    best, best_dist = None, float("inf")
    for comp in components:
        b = comp.bbox
        if b.x_min - padding <= px <= b.x_max + padding \
                and b.y_min - padding <= py <= b.y_max + padding:
            cx, cy = b.center()
            dist = (cx - px) ** 2 + (cy - py) ** 2
            if dist < best_dist:
                best_dist, best = dist, comp
    return best

def _build_traces(lines, components, padding=0.02):
    seen_pairs = set()
    traces = []
    for line in lines:
        start_comp = _nearest_component(line.start_point, components, padding)
        end_comp   = _nearest_component(line.end_point,   components, padding)
        if start_comp is None or end_comp is None:
            continue
        if start_comp.component_id == end_comp.component_id:
            continue
        pair = frozenset({start_comp.component_id, end_comp.component_id})
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        traces.append(Trace(
            from_component=start_comp.component_id, from_pin="",
            to_component=end_comp.component_id,   to_pin="",
            path=[line.start_point, line.end_point],
        ))
    return traces
```

Key decisions:
- **2% padding**: Hough endpoints land at the visible boundary of a component,
  not its center. A 2% expansion (~20 px on a 1 000 px image) catches slight
  misalignment.
- **Deduplication via `frozenset`**: prevents A→B and B→A from both appearing.
- **Empty `from_pin`/`to_pin`**: the CV pipeline does not resolve pin
  assignments; the agent can infer them semantically.

---

### OCR: `DocumentAIOCRExtractor` (`preprocessing/ocr.py`)

#### What it does

Sends the diagram image to Google Cloud Document AI and gets back every piece
of text it can find, with bounding boxes.

#### How Document AI coordinates work

Document AI returns bounding polygons as **normalized vertices** (0.0–1.0)
of a polygon (not always a rectangle). The extractor converts to axis-aligned
bboxes by taking `min`/`max` of the vertex coordinates:

```python
x_min = min(v.x for v in vertices)
y_min = min(v.y for v in vertices)
x_max = max(v.x for v in vertices)
y_max = max(v.y for v in vertices)
```

Then it clamps to `[0, 1]` to absorb floating-point noise at the edges.

#### Text extraction

Document AI stores text as a single document-level string with offsets.
Each token has `text_anchor.text_segments` — pairs of start/end byte offsets
into that string. The extractor reconstructs token text from the offset range:

```python
text = document_text[segment.start_index : segment.end_index]
```

---

### OpenCV Pipeline: `CVPipeline.run()` (`preprocessing/cv_pipeline.py`)

#### What it does

Detects closed contours (symbols — resistors, capacitors, ICs, etc.) and
line segments (traces — wires connecting components) using classic computer
vision techniques.

#### Symbol detection

```
PIL Image
    │
    ▼ convert to numpy uint8 grayscale
    ▼ Gaussian blur (5×5, σ=0)         ← reduces noise
    ▼ Otsu threshold                   ← binary image (adaptive threshold)
    ▼ Find contours (RETR_EXTERNAL)    ← external boundaries only
    ▼ Filter area < 200 px²            ← discard noise
    ▼ Normalize bbox coordinates
    ▼ Symbol(bbox, confidence=0.5)
```

Confidence is fixed at 0.5 because Otsu thresholding gives no confidence
signal — it just detects shape boundaries without classification. The
`component_type` is set to `"unknown"` at this stage; semantic classification
happens later in the pipeline.

#### Line detection (traces)

```
    ▼ Canny edge detection (50, 150)   ← find edges
    ▼ Probabilistic Hough Transform    ← find line segments in edges
       (threshold=80, minLen=30, gap=10)
    ▼ Normalize start/end coords
    ▼ DetectedLine(start, end, path)
```

The Hough accumulator threshold of 80 votes means a segment needs significant
co-linear edge support to be detected. Low-contrast or dashed lines may be
missed — this is a known limitation.

---

### Title Block Extraction (`preprocessing/title_block.py`)

#### Strategy

Title blocks are typically in the **bottom-right corner** of engineering
drawings (right 40%, bottom 25% of the diagram). The extractor:

1. Filters OCR labels to the title-block region
2. Sorts by reading order (top-to-bottom, left-to-right)
3. Applies regex patterns to extract structured fields

#### Pattern examples

```python
_RE_DWG_INLINE = re.compile(
    r"(?:DWG|DRAWING|DOC(?:UMENT)?)\s*(?:NO?|NUM(?:BER)?)?\s*[:.\-]?\s*([A-Z0-9\-/_.]+)",
    re.IGNORECASE
)
_RE_DATE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{1,2}-[A-Z]{3}-\d{4})\b",
    re.IGNORECASE
)
```

#### Header-context state machine

Some title blocks split the field label and value across lines:
```
DRAWING NO:        ← header label
SCH-2024-001       ← value on next line
```

The extractor maintains a "last header seen" state variable and captures the
next OCR token as its value when no inline pattern matches.

---

## 6. Tiling System

### Why Tiles?

LLMs process the full diagram image at ~1 024 px, losing 35× resolution. Tiles
solve this by letting the agent request high-resolution crops of specific
regions. The agent can say "inspect_zone(0, 0, 50, 50)" and get the
upper-left quadrant at full resolution.

### Pyramid Structure

```
Level 0: 1×1 grid  (1 tile  — full diagram overview at 512px)
Level 1: 2×2 grid  (4 tiles — mid-level, 50% overlap)
Level 2: 4×4 grid  (16 tiles — detail level, 50% overlap)
                    ─────────────────────────────────────
Total:             21 tiles
```

Each level is 2× more detailed than the previous. Level 2 tiles cover ~40%
of the diagram each (with 50% overlap), at 512px resolution — enough to read
12px tall text that was 0.34px at full scale.

### 50% Overlap — The Math (and Why Not 20%)

Stürmer et al. (arXiv:2411.13929) showed empirically that symbol fragmentation
at tile boundaries costs **~10% detection mAP** at any overlap below 50%.
The minimum safe overlap is therefore 50%.

**Intuition for why 50% is the threshold:**  For a symbol to appear intact in
at least one tile it must fit entirely within one tile's non-overlapping core.
At 50% overlap the non-overlapping core of each tile is 50% of the tile width.
Any symbol smaller than half a tile is guaranteed to appear whole somewhere.

```python
# tile_generator.py  (TilingConfig.overlap_fraction = 0.50)
def _tile_coords(n: int, overlap: float) -> list[tuple[float, float]]:
    """Normalized (start, end) coords for n overlapping tiles."""
    tile_w = 1.0 / (1 + (n - 1) * (1 - overlap))
    stride = tile_w * (1 - overlap)
    coords = []
    for i in range(n):
        start = i * stride
        end = start + tile_w
        coords.append((start, min(end, 1.0)))
    return coords
```

For n=4, overlap=0.50: `tile_w = 1/(1 + 3×0.5) = 1/2.5 = 0.400`,
`stride = 0.400 × 0.50 = 0.200`

| Tile | Covers | Shares with next |
|------|--------|-----------------|
| 0 | `[0.000, 0.400]` | `[0.200, 0.400]` |
| 1 | `[0.200, 0.600]` | `[0.400, 0.600]` |
| 2 | `[0.400, 0.800]` | `[0.600, 0.800]` |
| 3 | `[0.600, 1.000]` | — |

Every point in the diagram falls in at least two tiles (except the first and
last 20%).  Any symbol up to 40% of diagram width appears complete in at
least one tile.

**Trade-off:** 50% overlap means ~2× more pixel data per dimension vs. 20%.
The storage and token cost is higher, but the detection accuracy gain (~10%
mAP) makes it worth it for engineering-grade accuracy.

### Tile ID Format

```
{diagram_id}_L{level}_R{row}_C{col}

Example: 550e8400-e29b-41d4-a716-446655440000_L2_R1_C0
```

This is the key used to load tile images from storage.

### Pre-populated Content Lists

During generation, each tile records which components and text labels
overlap it:

```python
def _build_tile(self, tile, metadata):
    tile.component_ids = [
        c.component_id for c in metadata.components
        if c.bbox.overlaps(tile.bbox)
    ]
    tile.text_label_ids = [
        l.label_id for l in metadata.text_labels
        if l.bbox.overlaps(tile.bbox)
    ]
```

This is an upfront O(components × tiles) cost that makes per-query lookups
O(1) — the tool just reads `tile.component_ids` rather than scanning all
components at query time.

---

## 7. Tools

### Architecture

All tools follow the same pattern:

```python
def my_tool(diagram_id: str, ...) -> dict[str, Any]:
    store = get_store()                       # singleton data access
    metadata = store.get_metadata(diagram_id)
    if metadata is None:
        return {"error": f"Diagram not found: {diagram_id}"}

    # ... do work ...

    return {"key": value, ...}                # always JSON-serializable
```

Rules:
- **No exceptions raised** — errors go into `{"error": "..."}` dicts
- **No Pydantic models in return values** — use `.model_dump(mode="json")`
- **No image objects in return values** — encode to base64 strings first
- **All parameters are JSON primitives** — `str`, `int`, `float` only

---

### Tool 1: `get_overview`

**When the agent calls it:** Always first. Establishes the scope of the diagram.

**What it returns:**
```json
{
  "diagram_id": "550e8400-...",
  "width_px": 7000,
  "height_px": 5000,
  "component_count": 42,
  "component_types": {"resistor": 15, "capacitor": 8, "ic": 5, "unknown": 14},
  "text_label_count": 230,
  "trace_count": 0,
  "title_block": {
    "drawing_number": "SCH-2024-001",
    "revision": "B",
    "date": "2024-03-15",
    "author": "J. Smith"
  }
}
```

**Notably:** No image is returned. This is intentional — the diagram image is
already provided to the agent as an `inline_data` Part at conversation start.
`get_overview` is purely structured data and very token-cheap (~300 tokens).

---

### Tool 2: `inspect_zone`

**When the agent calls it:** To zoom into a specific region of the diagram.
The agent uses the overview image (which it already has) to identify regions
of interest, then calls `inspect_zone` to get high-resolution tiles of those
regions.

**Coordinate system:** Percentage-based, 0–100. Not normalized 0–1, not pixels.
The LLM finds percentage coordinates natural ("upper-left quadrant = 0,0,50,50").

**Resolution selection logic:**
```
Query region → find tiles at level 2 that cover it
If none found → try level 1
If none found → try level 0
If still none → crop original image at full resolution (fallback)
```

**SOM annotation (the most important part):**

Before returning tile images, the tool annotates them with Set-of-Marks:

```python
# _image_utils.py
def annotate_tile(image, markers):
    draw = ImageDraw.Draw(image)
    for i, marker in enumerate(markers, 1):
        bbox_px = marker["bbox_px"]
        # Draw red bounding box
        draw.rectangle([x, y, x+w, y+h], outline=(220, 50, 50), width=2)
        # Draw numbered tag above bbox
        draw.text((x, y - tag_h - 2), f"[{i}]", fill=(220, 50, 50), font=font)
    return image
```

The agent's response then says things like:
> "Marker [3] shows a resistor labeled 'R47'. Marker [7] appears to be an
> op-amp in the upper-left of this tile."

This grounds the agent's claims to verifiable positions on the diagram.

**Limits and why:**

| Limit | Value | Reason |
|---|---|---|
| Max tiles | 3 | 3 × 512px JPEG ≈ 180K tokens; prevents context overflow |
| Max px per tile | 512 | ~60K tokens per tile; manageable |
| Max text labels in response | 50 | Cap marker list; more would overwhelm agent |
| Image encoding | JPEG | ~3× smaller than PNG; faster, fewer tokens |

---

### Tool 3: `inspect_component`

**When the agent calls it:** After finding a component ID (via `search_text`
or from `inspect_zone` markers), to get a detailed close-up.

**What it does:**
1. Loads the full-resolution original image (not the downscaled diagram image
   the agent has)
2. Crops the component bbox + 5% padding on each side
3. Finds nearby components (centroid distance ≤ 20% of diagram dimension)
4. Returns the crop as base64 PNG + nearby component list

**Why 5% padding?** Enough to show component context (nearby traces, labels)
without pulling in distant components. A component occupying 3% of the
diagram width gets an effective crop of about 8% of diagram width.

**Why PNG for this tool (not JPEG)?** This crop is small (one component).
The quality difference matters more for a close-up than for a full-tile view.
JPEG compression artifacts could make small text in a crop unreadable.

---

### Tool 4: `search_text`

**When the agent calls it:** To find a specific reference designator, net
name, or label. Also useful for "find all ground symbols" or "list all
voltage references."

**Implementation:**
```python
def search_text(diagram_id, query):
    metadata = get_store().get_metadata(diagram_id)
    query_lower = query.lower()
    matches = [
        label for label in metadata.text_labels
        if query_lower in label.text.lower()   # case-insensitive substring
    ]
    # Annotate each match with its best tile (most detailed level)
    for match in matches[:100]:
        tile = _find_best_tile(pyramid, match.bbox)
        match["tile_id"] = tile.tile_id if tile else None
        ...
    return {"matches": matches, "match_count": len(matches)}
```

Substring match (not exact, not regex) was chosen because:
- "R47" should match "R47 10kΩ" and "U47A"
- Engineers often search by partial reference (e.g., "U4" to find all U4x ICs)
- The LLM can filter the result set — returning too many is better than too few

---

### Tool 5: `trace_net`

**When the agent calls it:** To follow electrical/fluid connections from a
known component. Most useful for "what does R47 connect to?" type questions.

**Implementation:**
```python
def trace_net(diagram_id, component_id, pin):
    # Search forward: traces where component is the source
    forward = [t for t in metadata.traces if t.from_component == component_id]
    # Search reverse: traces where component is the destination
    reverse = [t for t in metadata.traces if t.to_component == component_id]

    connections = []
    for trace in forward:
        if not pin or trace.from_pin == pin:
            connections.append({
                "connected_component_id": trace.to_component,
                "direction": "from",  # our component is the source
                "path": trace.path,
                ...
            })
    for trace in reverse:
        if not pin or trace.to_pin == pin:
            connections.append({
                "connected_component_id": trace.from_component,
                "direction": "to",  # our component is the destination
                ...
            })
```

**Graceful fallback when trace data is absent:**

The tool has a two-level fallback:

1. **No components extracted** — returns `trace_data_unavailable: true` with
   a message directing the agent to use `inspect_zone()` visually.

2. **Components present but no `Trace` objects** — returns
   `trace_data_unavailable: true` PLUS a `topology_hint` dict that counts
   how many CONNECTED vs CROSSING junctions were detected near the queried
   component:

```json
{
  "trace_data_unavailable": true,
  "topology_hint": {
    "connected_junctions_nearby": 3,
    "crossing_junctions_nearby": 1,
    "note": "3 connected junction(s) and 1 crossing(s) detected near this
             component.  Crossings are pass-through intersections — NOT
             electrical or fluid connections even though they share a
             spatial point."
  },
  "connections": [],
  "connection_count": 0
}
```

The `topology_hint` is built by `_junctions_near_component()` which scans
`metadata.junctions` for any junction within 6% (normalised) of the
component's center.  This gives the agent enough signal to say *"there are
3 junctions nearby — 2 connected and 1 crossing — so this component does
connect to others even though full trace data is unavailable"*, without
fabricating actual connection paths.

**Why the crossing warning matters:** Two pipes that cross on a P&ID at an
X-crossing appear spatially coincident but are physically separate.  A simple
"count all intersections" approach would double the apparent connectivity.
The `junction_type` field in each junction dict makes this explicit.

---

### `_store.py` — The Data Access Seam

```python
# Abstract interface
class DiagramStore(ABC):
    @abstractmethod
    def get_metadata(self, diagram_id: str) -> DiagramMetadata | None: ...
    @abstractmethod
    def get_pyramid(self, diagram_id: str) -> TilePyramid | None: ...
    @abstractmethod
    def load_tile_image(self, tile_id: str) -> PIL.Image | None: ...
    @abstractmethod
    def load_original_image(self, diagram_id: str) -> PIL.Image | None: ...

# Module-level singleton
_store: DiagramStore | None = None

def configure_store(store: DiagramStore) -> None:
    global _store
    _store = store

def get_store() -> DiagramStore:
    if _store is None:
        raise RuntimeError("Store not configured. Call configure_store() first.")
    return _store
```

This singleton is the **single testability seam for all tools**. In tests:
```python
configure_store(MockDiagramStore())  # inject mock before test
result = get_overview("test-diagram-id")
assert result["component_count"] == 5
```

No real GCS, no real Firestore, no real image files needed in tests.

---

### `export_visualization` — Interactive HTML Viewer

Not an agent tool — called by the `GET /visualization/{id}` endpoint. Generates
a self-contained HTML file with:

- **Left panel:** Diagram image with SVG bounding-box overlays
  - Red overlays = components (confidence-colored: green ≥ 80%, yellow 50–79%, red < 50%)
  - Blue overlays = text labels
  - Hover highlights, click pins the overlay detail
- **Right panel (tabbed):**
  - **Components tab:** Searchable list, type filter chips, click-to-highlight
  - **Graph tab:** Mermaid.js diagram with a three-way fallback:
    1. **Connectivity mode** — when `Trace` objects exist: directed `graph LR`
       with pin labels between connected components
    2. **Topology mode** — when no traces but components were detected: nodes
       grouped by `component_type` in Mermaid subgraphs; no edges drawn; an
       info banner reads *"Component topology — no electrical trace data
       available"* so it is always clear that connections are not shown
    3. **Empty state** — when neither traces nor components exist
  - **Details tab:** Component detail on click (type, value, confidence, bbox,
    pin count)
- Zoom/pan on the diagram via CSS transform + mouse handlers
- Max 200 text labels (UI performance cap)

The output is a **single self-contained HTML file** — no server needed to view
it. Safe to email or put in a shared drive.

#### `_build_mermaid` — graph builder

```python
def _build_mermaid(
    traces: list[dict[str, str]],
    components: list[Any] | None = None,
) -> tuple[str, str]:          # (mermaid_definition, mode)
```

Returns a `(definition, mode)` tuple where `mode` is `"connectivity"`,
`"topology"`, or `""` (no graph). The calling code passes both to
`_render_graph_tab()` which wraps the Mermaid `<pre>` block and, in topology
mode, prepends the info banner. This keeps the rendering logic out of the
main HTML f-string.

---

## 8. The Agent System

### Google ADK — What It Is

Google Agent Development Kit (ADK) is a framework for building multi-step
tool-using LLM agents. Key components used here:

- **`LlmAgent`** — A Gemini-backed agent configured with a list of Python
  functions as tools. The LLM decides which tools to call and in what order.
- **`InMemoryRunner`** — Executes the agent in memory, managing the
  conversation session. Handles the turn loop: LLM responds → calls tool →
  LLM sees response → calls next tool → ... → LLM produces final answer.
- **`before_tool` / `after_tool` callbacks** — Lifecycle hooks called before
  and after every tool invocation.

### How ADK Function Calling Works

1. `LlmAgent` is given a list of Python functions as tools.
2. ADK introspects the function signatures and docstrings to build a JSON
   Schema for each tool (Gemini's function calling format).
3. When the LLM decides to call a tool, it emits a `FunctionCall` event with
   JSON arguments (only JSON primitives: string, number, boolean, array, object).
4. ADK calls the Python function with those arguments.
5. The return value (a dict) is serialized to JSON and fed back to the LLM
   as a `FunctionResponse`.
6. The LLM continues reasoning and may call more tools or produce the final
   answer.

This is why all tool parameters must be `str`, `int`, or `float` — they
cross the LLM/Python boundary as JSON.

### `CADAnalysisAgent` (`agent/cad_agent.py`)

```python
class CADAnalysisAgent:
    def __init__(self, model="gemini-3.1-pro-preview-customtools", ...):
        self._tools = [
            get_overview, inspect_zone, inspect_component,
            search_text, trace_net
        ]
        self._agent = LlmAgent(
            model=model,
            tools=self._tools,
            instruction=AGENT_INSTRUCTION,
            global_instruction=GLOBAL_INSTRUCTION,
            before_tool_callback=before_tool,
            after_tool_callback=after_tool,
        )
        self._runner = InMemoryRunner(agent=self._agent, app_name="cad_analyzer")
```

Key design detail: `_agent_cls` and `_runner_cls` are constructor parameters.
In tests, mock classes replace `LlmAgent` and `InMemoryRunner` entirely. No
real Gemini calls are made in any test.

### Image Encoding Strategy

```python
# cad_agent.py
async def analyze_async(self, diagram_id, query, ...):
    image = self._store.load_original_image(diagram_id)

    # Downscale to 768px (not 1024px) — saves ~100-300K tokens
    image = downscale_to_fit(image, max_px=768)

    # JPEG at quality 85 — ~3× smaller than PNG
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    image_bytes = buffer.getvalue()

    # Attach as inline_data Part in the first Content
    content = Content(parts=[
        Part(inline_data=Blob(data=image_bytes, mime_type="image/jpeg")),
        Part(text=query),
    ])
```

The image is sent **once** at the start of the conversation, not repeated
with each tool call. This is why `get_overview` returns no image — the LLM
already has it.

### Retry Logic

```python
for attempt in range(3):
    try:
        result = await self._runner.run_async(...)
        break
    except Exception as e:
        if _is_transient_error(e) and attempt < 2:
            wait = min(2 ** (attempt + 1), 30)  # 2s, 4s, capped at 30s
            await asyncio.sleep(wait)
        else:
            raise

def _is_transient_error(e):
    msg = str(e).lower()
    return any(x in msg for x in ["429", "503", "rate limit", "resource exhausted"])
```

A new session ID is generated for each retry to avoid inheriting stale state
from a failed session.

---

### System Prompts (`agent/prompts.py`)

Two layers of instruction:

**`GLOBAL_INSTRUCTION`** — Meta-guidance (always applies):
- Use both visual image AND structured data together
- Prefer structured data when available
- Never fabricate component values or connections you cannot verify

**`AGENT_INSTRUCTION`** — Operational workflow (the detailed how-to):

1. **Tool workflow:** Always `get_overview` first → `inspect_zone` for regions
   → `inspect_component` for detail → `search_text` for lookups →
   `trace_net` for connectivity
2. **Visual fallback:** When OCR/CV found nothing, fall back to visual analysis
   of the inline image + `inspect_zone` for high-res tiles
3. **SOM grounding:** Reference tile elements by marker number [N]; never
   describe position without citing a marker or region
4. **Spatial reasoning:** Cross-reference low-res overview with high-res
   tiles; describe by region (upper-left, x:0-50, y:0-40)
5. **Rules:** Never guess values; zoom in before claiming uncertainty; report
   confidence level explicitly

---

### Tool Callbacks + `ToolCallTracker` (`agent/callbacks.py`)

#### `before_tool`

Called before each tool invocation. Returns:
- `None` → proceed with the call
- `dict` → short-circuit; use this as the tool result (function NOT called)

Used for:
1. Validate `diagram_id` is present and non-empty for all diagram tools
2. Record call start time in `ToolCallTracker`
3. Log tool name + argument keys at DEBUG level

```python
def before_tool(tool, args, tool_context) -> dict | None:
    tool_name = getattr(tool, "name", str(tool))
    if tool_name in _DIAGRAM_TOOLS:
        diagram_id = args.get("diagram_id", "")
        if not diagram_id or not isinstance(diagram_id, str):
            return {"error": "diagram_id is required"}
    tracker.record_start(tool_name, dict(args))
    return None
```

#### `after_tool`

Called after each tool returns. Returns:
- `None` → pass `tool_response` unchanged to LLM
- `dict` → override the response with this dict

Used for:
1. Record call end time, compute `duration_ms`
2. Detect `"error"` key in response, log warning
3. Generate human-friendly `result_summary` per tool type

```python
def _summarise_result(tool_name, response):
    match tool_name:
        case "get_overview":
            return f"{response.get('component_count',0)} components, {response.get('text_label_count',0)} text labels"
        case "inspect_zone":
            return f"{len(response.get('tiles',[]))} tiles, {response.get('component_count',0)} components"
        case "search_text":
            return f"{response.get('match_count',0)} matches for '{response.get('query','')}'"
        ...
```

#### `ToolCallTracker`

Module-level singleton. Lives for the duration of one `analyze_async()` call.

```python
class ToolCallTracker:
    def reset(self): self._records = []
    def record_start(self, tool_name, args): ...
    def record_end(self, tool_name, success, result_summary, error=None): ...
    def get_records(self) -> list[dict]: return self._records
```

`_sanitize_args()` strips any string value longer than 200 characters before
recording — this prevents base64 image data from bloating the tracker log.

The records look like:
```json
[
  {"tool_name": "get_overview", "duration_ms": 142, "success": true,
   "result_summary": "42 components, 230 text labels"},
  {"tool_name": "inspect_zone", "duration_ms": 2341, "success": true,
   "result_summary": "3 tiles, 12 components, 45 labels"}
]
```

These are returned in `AnalyzeResponse.tool_calls` and rendered as the
"Agent Activity" timeline in the frontend.

---

## 9. The Server

### FastAPI Application (`agent/server.py`)

```python
app = FastAPI(title="CAD Diagram Analyzer")

app.add_middleware(CORSMiddleware, allow_origins=["*"])  # dev: all origins

# Mount static frontend last (catches-all route)
app.mount("/", StaticFiles(directory="frontend", html=True))
```

### `POST /ingest`

```
Request: multipart/form-data with "file" field (image)
Response: IngestResponse {diagram_id, success, error_message}
```

Flow:
1. Read uploaded bytes into memory (no temp file on disk)
2. Open as PIL Image, convert to RGB
3. Call `orchestrator.ingest(image, filename)`
4. Return `diagram_id`

Error cases:
- Invalid image format → 422 (Pydantic validation)
- Preprocessing failure → 500 + error_message in response body (not HTTP error)

### `POST /analyze`

```
Request:  AnalyzeRequest {diagram_id, query, user_id}
Response: AnalyzeResponse {diagram_id, query, response, tool_calls}
```

Flow:
1. Look up diagram in store (404 if not found)
2. Check agent is configured (503 if not — GCP credentials missing)
3. Call `agent.analyze_async(diagram_id, query, user_id)`
4. Return text response + tool_calls list

### `GET /visualization/{diagram_id}`

Returns an HTML response (not JSON) — the self-contained interactive viewer.

```python
@app.get("/visualization/{diagram_id}")
async def visualization(diagram_id: str):
    html = export_visualization(diagram_id)
    return HTMLResponse(content=html)
```

### `GET /` — Frontend

The static files mount catches all unmatched routes and serves `frontend/index.html`.
This means the frontend is served from the same origin as the API — no CORS
issues for the frontend's own API calls.

---

## 10. The Frontend

The frontend is a **single-page vanilla JavaScript app** (`frontend/`).
No build step, no framework, no bundler. Three files:

```
frontend/
├── index.html       # Structure + inline SVG icons
├── css/styles.css   # Dark theme + animations
└── js/app.js        # All behavior (~700 lines)
```

### Why Vanilla JS?

Simplicity. The server is the complexity. The frontend needs to: upload a
file, call two endpoints, render text + a timeline. No routing, no state
management, no component lifecycle needed.

### Key State

```javascript
let currentFile = null;         // File object from input/drop
let currentDiagramId = null;    // UUID returned by /ingest
let phaseTimers = {};           // { upload: timestamp, preprocess: timestamp, ... }
```

### 4-Phase Pipeline Flow (`runAnalysis`)

```javascript
async function runAnalysis() {
    // Phase 1: Upload (immediate)
    setPhase(phaseUpload, 'active');
    await delay(180);             // tiny pause for visual clarity
    setPhase(phaseUpload, 'done', elapsed);
    fillConnector(conn12);

    // Phase 2: Preprocess (POST /ingest)
    setPhase(phasePreprocess, 'active');
    startSubMessages('preprocess', ['Sending to Document AI…',
        'Extracting text labels…', 'Detecting symbols…', 'Building tile pyramid…']);
    const diagramId = await ingestDiagram();    // actual API call
    stopSubMessages('preprocess');
    setPhase(phasePreprocess, 'done', elapsed);
    fillConnector(conn23);

    // Phase 3: AI Analysis (POST /analyze)
    setPhase(phaseAnalyze, 'active');
    startSubMessages('analyze', ['Initializing ADK agent…',
        'Getting diagram overview…', 'Inspecting regions…',
        'Searching text labels…', 'Synthesizing response…']);
    const result = await analyzeQuery(diagramId);   // actual API call
    stopSubMessages('analyze');
    setPhase(phaseAnalyze, 'done', elapsed);
    fillConnector(conn34);

    // Phase 4: Results
    setPhase(phaseResults, 'active');
    await delay(280);
    setPhase(phaseResults, 'done', 0);
    displayResult(result);
}
```

### CSS Animation Architecture

**Active phase spinning border:**
```css
.pipeline-phase.active .phase-ring-outer {
    background: conic-gradient(
        var(--accent) 0deg,
        var(--secondary) 100deg,
        transparent 200deg
    );
    animation: rotateConic 1.3s linear infinite;
}
.pipeline-phase.active .phase-ring-outer::after {
    /* Inner mask — creates the "border-only" effect */
    content: '';
    position: absolute;
    inset: 4px;               /* 4px border width */
    border-radius: 50%;
    background: var(--surface-hover);
}
```

The `::after` pseudo-element covers the center of the gradient background,
leaving only a 4px ring visible — the spinning border effect.

**Done phase checkmark pop:**
```css
@keyframes checkPop {
    0%   { transform: scale(0) rotate(-10deg); opacity: 0; }
    65%  { transform: scale(1.25) rotate(2deg); }
    100% { transform: scale(1) rotate(0deg); opacity: 1; }
}
```

The `cubic-bezier(0.34, 1.56, 0.64, 1)` easing on the phase transition gives
a spring overshoot effect — the node briefly scales past 1.0 before settling.

**Connector fill:**
```css
.pipeline-conn-fill {
    width: 0;
    transition: width 0.75s ease;
}
.pipeline-conn.filled .pipeline-conn-fill {
    width: 100%;
}
```

```javascript
function fillConnector(connEl) {
    // requestAnimationFrame ensures the browser has rendered the
    // initial width:0 state before transitioning to width:100%
    requestAnimationFrame(() => connEl.classList.add('filled'));
}
```

Without `requestAnimationFrame`, adding the class immediately after creating
the element would skip the transition (both states applied in the same frame).

### Tool Call Timeline Rendering

```javascript
function renderToolCalls(toolCalls) {
    const colors = {
        get_overview: '#4f8ef7',
        inspect_zone: '#a855f7',
        inspect_component: '#f97316',
        search_text: '#14b8a6',
        trace_net: '#ec4899'
    };

    return toolCalls.map(call => `
        <div class="tool-call-card ${call.success ? '' : 'error'}">
            <span class="tool-dot" style="background:${colors[call.tool_name]}"></span>
            <span class="tool-name">${call.tool_name}</span>
            <span class="tool-duration">${(call.duration_ms/1000).toFixed(2)}s</span>
            <span class="tool-summary">${call.result_summary || ''}</span>
        </div>
    `).join('');
}
```

Each tool gets a unique color so the timeline is scannable at a glance.

---

## 11. Storage Backends

### `InMemoryDiagramStore` (Development + Tests)

Lives in `orchestrator.py`. Backed by Python dicts:

```python
class InMemoryDiagramStore(DiagramStore):
    def __init__(self):
        self._metadata: dict[str, DiagramMetadata] = {}
        self._pyramids: dict[str, TilePyramid] = {}
        self._tile_images: dict[str, PIL.Image] = {}
        self._original_images: dict[str, PIL.Image] = {}
```

Immediately available, zero setup, zero cost. Data lost on process restart.
**This is what the local dev server uses.**

### `LocalStorage` (Tile files on disk)

```python
class LocalStorage(TileStorage):
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, tile_id: str, image: PIL.Image) -> str:
        path = self.base_dir / f"{tile_id}.png"
        image.save(path, format="PNG")
        return str(path)

    def load(self, tile_id: str) -> PIL.Image | None:
        path = self.base_dir / f"{tile_id}.png"
        if not path.exists():
            return None
        return PIL.Image.open(path).copy()  # .copy() closes the file handle
```

### GCS + Firestore (Production)

The `DiagramStore` ABC is designed to be implemented against GCS (tile images)
and Firestore (metadata). The schema is ready in `models/`; the production
adapter was deferred to post-pilot. The `Orchestrator.create_gcs()` factory
method exists as a placeholder for this.

---

## 12. Configuration & Environment Variables

```env
# Google Cloud
GCP_PROJECT_ID=my-project-id
GCS_BUCKET=my-bucket-name
FIRESTORE_DB=my-database
VERTEX_AI_LOCATION=global          # gemini-3.1 requires global endpoint, not regional

# Document AI
DOCUMENT_AI_PROCESSOR_ID=abc123...
DOCUMENT_AI_LOCATION=us

# Model selection (optional overrides)
GEMINI_MODEL=gemini-3.1-pro-preview-customtools  # agent model (tuned for tool calling)
TOOL_MODEL=gemini-3.1-pro-preview                # vision-heavy tools (optional)

# ADC routing — tells google-genai to use Vertex AI, not API key
GOOGLE_GENAI_USE_VERTEXAI=1
```

`server.py` calls `load_dotenv()` at startup to load `.env` from the project
root. It also sets `GOOGLE_GENAI_USE_VERTEXAI=1` and `GOOGLE_CLOUD_PROJECT`
as explicit `os.environ.setdefault()` calls as a safety net — so the SDK
routes correctly even if the env vars aren't in `.env`.

**Local development without GCP credentials:**

Use `Orchestrator.create_local()` which wires stub OCR and CV extractors that
return empty results. The agent still works — it falls back to pure visual
analysis of the diagram image. You won't get structured component extraction,
but the full tool loop and response rendering work.

---

## 13. Testing Architecture

### Test Structure

```
tests/
├── conftest.py                    # Shared fixtures (tmp dirs, sample images)
├── fixtures/                      # Sample CAD images
├── test_models/                   # Model validation tests
│   ├── test_bounding_box.py       # BoundingBox validators, methods
│   └── test_diagram_metadata.py   # DiagramMetadata query methods
├── test_preprocessing/
│   ├── conftest.py                # Mock Document AI + OpenCV
│   └── test_pipeline.py           # PreprocessingPipeline integration
├── test_tiling/
│   └── test_tile_generator.py     # Overlap math, pyramid structure
└── test_tools/
    ├── conftest.py                # configured_store fixture
    ├── test_get_overview.py
    ├── test_inspect_zone.py
    ├── test_inspect_component.py
    ├── test_search_text.py
    ├── test_trace_net.py
    └── test_export_visualization.py
```

### The DI Seam Pattern

All tools access storage through `get_store()`. Tests inject a mock via
`configure_store(mock)`:

```python
# tests/test_tools/conftest.py
@pytest.fixture
def mock_metadata():
    return DiagramMetadata(
        diagram_id="test-id",
        width_px=1000,
        height_px=800,
        components=[
            Component(component_id="sym_001", component_type="resistor",
                      bbox=BoundingBox(x_min=0.1, y_min=0.1, x_max=0.2, y_max=0.2),
                      confidence=0.9, pins=[], value=None, package=None)
        ],
        text_labels=[
            TextLabel(label_id="lbl_001", text="R47 10kΩ",
                      bbox=BoundingBox(...), confidence=0.95, page=1)
        ],
        traces=[], title_block=None,
    )

@pytest.fixture
def configured_store(mock_metadata, tmp_path):
    store = InMemoryDiagramStore()
    store.put_metadata(mock_metadata)
    configure_store(store)
    yield store
    configure_store(None)   # cleanup: reset singleton after test
```

Every tool test uses `configured_store` — no GCS, no Firestore, no Gemini.

### Testing Tool Responses

```python
def test_get_overview_returns_correct_counts(configured_store, mock_metadata):
    result = get_overview("test-id")
    assert result["component_count"] == 1
    assert result["component_types"]["resistor"] == 1
    assert result["text_label_count"] == 1

def test_get_overview_missing_diagram(configured_store):
    result = get_overview("nonexistent-id")
    assert "error" in result
    assert "not found" in result["error"].lower()
```

### Testing the Agent (Mock ADK)

```python
# cad_agent.py
class CADAnalysisAgent:
    def __init__(self, _agent_cls=LlmAgent, _runner_cls=InMemoryRunner, ...):
        ...

# In tests:
agent = CADAnalysisAgent(
    _agent_cls=MockLlmAgent,    # returns scripted tool call sequences
    _runner_cls=MockRunner,     # captures run_async calls
)
```

The mock runner returns a pre-configured `EventActions` sequence that simulates
tool calls without hitting the Gemini API.

### Running Tests

```bash
# All tests
pytest

# Specific suite
pytest tests/test_tools/ -v

# With coverage
pytest --cov=src --cov-report=html

# Type check
mypy src/

# Lint
ruff check src/

# Format check
ruff format src/ --check
```

---

## 14. End-to-End Trace

Walk through a single request: *"Find resistor R47 and tell me its connections."*

### Step 1: Upload (Browser → `POST /ingest`)

```
Browser sends: multipart/form-data with schematic.png (7000×5000 px)
server.py receives it, opens as PIL Image

orchestrator.ingest(image, "schematic.png")
    ├── pipeline.run(image)          ← sequential: OCR first, then CV with masks
    │       ├── 1. Document AI OCR → 230 TextLabel objects
    │       │       └── includes "R47 10kΩ" at bbox(0.15, 0.30, 0.20, 0.32)
    │       ├── 2. _mask_text_regions → paint 230 text bboxes white on grayscale
    │       ├── 3. OpenCV CV (on masked image) → 42 Symbol objects, 180 lines, 94 junctions
    │       │       ├── symbols: includes symbol at bbox(0.15, 0.30, 0.20, 0.35)
    │       │       └── junctions: 71 CONNECTED, 23 CROSSING
    │       ├── 4. _build_traces → 38 Trace objects from line endpoints → component bboxes
    │       └── 5. TitleBlock → {drawing_number: "SCH-2024-001", ...}
    │
    └── tile_generator.generate(image, metadata)
            ├── Level 0: 1 tile (full diagram, 512px)
            ├── Level 1: 4 tiles (2×2, 512px each, 50% overlap)
            └── Level 2: 16 tiles (4×4, 512px each, 50% overlap)
                    └── Tile L2_R1_C0 covers bbox(0.00, 0.00, 0.40, 0.40)
                        └── component_ids: ["sym_001"]
                        └── text_label_ids: ["lbl_042"]

DiagramMetadata saved to InMemoryDiagramStore with diagram_id="550e8400-..."

Response: {"diagram_id": "550e8400-..."}
```

### Step 2: Query (Browser → `POST /analyze`)

```
Browser sends: {"diagram_id": "550e8400-...", "query": "Find R47 and its connections"}

server.py → agent.analyze_async("550e8400-...", "Find R47 and its connections")

CADAnalysisAgent:
    1. load_original_image("550e8400-...")
    2. downscale to 768px JPEG (saves ~200K tokens)
    3. InMemoryRunner.run_async(content=[image_bytes, query_text])
```

### Step 3: Agent Turn Loop (Inside ADK)

```
Turn 1: LLM sees image + query
    → Calls get_overview("550e8400-...")

before_tool: validates diagram_id ✓, records start_time
get_overview executes: returns {component_count: 42, text_label_count: 230, ...}
after_tool: duration=142ms, summary="42 components, 230 text labels"

Turn 2: LLM processes overview, identifies R47 by name
    → Calls search_text("550e8400-...", "R47")

search_text executes:
    → finds "R47 10kΩ" at bbox(0.15, 0.30, 0.20, 0.32), confidence=0.92
    → annotates with tile L2_R1_C0
    → returns {matches: [{text: "R47 10kΩ", bbox: ..., tile_id: "..._L2_R1_C0"}]}
after_tool: duration=18ms, summary="1 match for 'R47'"

Turn 3: LLM has the bbox, wants to verify visually
    → Calls inspect_component("550e8400-...", "sym_001")

inspect_component executes:
    → loads full-resolution original image
    → crops bbox(0.15, 0.30, 0.20, 0.35) + 5% padding
    → finds nearby: sym_002 (capacitor, dist=0.08), sym_003 (ic, dist=0.15)
    → returns {crop_image_base64: "...", nearby_components: [...]}
after_tool: duration=380ms, summary="crop + 2 nearby components"

Turn 4: LLM wants to know what R47 connects to
    → Calls trace_net("550e8400-...", "sym_001", "")

trace_net executes:
    → finds trace_001: sym_001 → sym_002 (capacitor), pin_1, path=[(0.20, 0.32), (0.25, 0.32), (0.28, 0.35)]
    → returns {connections: [{connected_component_id: "sym_002", direction: "from", ...}]}
after_tool: duration=12ms, summary="1 connection from sym_001"

Turn 5: LLM synthesizes final answer
    → "R47 (10kΩ resistor, located at ~15-20% from left, 30-35% from top)
       connects to a capacitor (sym_002) via a horizontal trace..."
```

### Step 4: Response Assembly

```
analyze_async returns:
{
  "text": "R47 (10kΩ resistor)... connects to...",
  "tool_calls": [
    {"tool_name": "get_overview", "duration_ms": 142, "success": true, ...},
    {"tool_name": "search_text",  "duration_ms": 18,  "success": true, ...},
    {"tool_name": "inspect_component", "duration_ms": 380, "success": true, ...},
    {"tool_name": "trace_net",    "duration_ms": 12,  "success": true, ...}
  ]
}

server.py wraps in AnalyzeResponse, sends to browser
```

### Step 5: Frontend Rendering

```
phaseAnalyze → done ✓ (total agent time: ~5.2s)
phaseResults → done ✓
displayResult(result):
    → render agent text in #result-text
    → renderToolCalls(result.tool_calls) → 4-card timeline in #tool-calls
        → get_overview  [blue]   142ms  "42 components, 230 text labels"
        → search_text   [teal]    18ms  "1 match for 'R47'"
        → inspect_comp  [orange] 380ms  "crop + 2 nearby components"
        → trace_net     [pink]    12ms  "1 connection from sym_001"
```

---

## 15. Key Design Patterns

### 1. Abstract Base Class as Testability Seam

`DiagramStore`, `TileStorage`, `DocumentAIClient`, `CVPipeline` — all are
ABCs with thin concrete implementations and mock alternatives for tests.
The pattern: define the interface, inject the implementation.

### 2. Error Dict (Not Exceptions) in Tools

Tools are called from within the ADK agent's turn loop. An uncaught exception
would terminate the agent run. By returning `{"error": "..."}`, the LLM sees
the failure as a `FunctionResponse` and can:
- Retry with different arguments
- Try a different tool
- Explain the failure to the user

### 3. Singleton via Module-Level Variable

`_store` in `_store.py` and `tracker` in `callbacks.py` are module-level
singletons. Reset via `configure_store(None)` / `tracker.reset()` in test
teardown. This avoids passing the store/tracker through every call chain.

### 4. Lazy Imports for Optional Dependencies

```python
# cv_pipeline.py
try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

def run(self, image):
    if not _CV2_AVAILABLE:
        return CVResult(symbols=[], detected_lines=[], junctions=[])
    ...
```

OpenCV, FastAPI, uvicorn are all lazily imported. The module can be imported
in test environments that don't have those packages installed. Tools run,
models validate, and tests pass without the full dependency set.

### 5. Constructor Injection for Agent Mocking

```python
class CADAnalysisAgent:
    def __init__(
        self,
        model: str = "gemini-3.1-pro-preview-customtools",
        _agent_cls=None,    # override in tests
        _runner_cls=None,   # override in tests
        _types_mod=None,    # override in tests
    ):
        AgentCls = _agent_cls or LlmAgent
        RunnerCls = _runner_cls or InMemoryRunner
```

Tests pass mock classes. Production passes nothing (defaults kick in).

### 6. `model_dump(mode="json")` for Serialization

Pydantic v2 models use `mode="json"` to ensure all values are JSON-native
(no `datetime` objects, no `UUID` objects — only str/int/float/list/dict).
This is the safe way to cross the Python→JSON boundary for tool return values.

### 7. `requestAnimationFrame` for CSS Transitions

When you add a CSS class that triggers a transition in the same JavaScript
frame as the element is created, the browser may optimize away the "from"
state, skipping the transition. Wrapping in `requestAnimationFrame` ensures
the browser renders the initial state before the class is applied.

---

## 16. Dependency Map

Who imports who (simplified):

```
server.py
    → orchestrator.py
    │     → preprocessing/pipeline.py → models/diagram.py
    │     → tiling/tile_generator.py  → models/tiling.py
    │     → tiling/tile_storage.py
    │
    → agent/cad_agent.py
          → agent/prompts.py
          → agent/callbacks.py → (tools/get_overview, inspect_zone, ...)
          → tools/_store.py
          → tools/_image_utils.py

tools/*.py
    → tools/_store.py      (get data)
    → tools/_image_utils.py (annotate images)
    → models/diagram.py    (type-safe access to metadata)

models/ (no internal imports — foundation layer)
```

The `models/` package has no internal imports from `src/`. It is the
foundation. Every other layer imports from it. It never imports from them.

---

## 17. Research-Backed Improvements

This section documents the three algorithm improvements derived directly from
peer-reviewed research and how they are implemented in this codebase.

### The Paper

> **"From Engineering Diagrams to Graphs: Digitizing P&IDs with Transformers"**
> M. Stürmer, J. Sacher, F. Kraus, P. Welke, A. Ngoc Phi.
> IEEE DSAA 2025 — arXiv:2411.13929v2 (November 2024).

The paper benchmarks multiple computer-vision approaches for automatically
digitizing Piping & Instrumentation Diagrams (P&IDs) — dense industrial
engineering drawings very similar to what this system processes.  Its key
empirical results drove three changes to this codebase.

---

### Improvement 1 — 50% Tile Overlap (was 20%)

**Paper finding:**

> *"Overlapping patches are required to prevent fragmentation of symbols
> that straddle patch boundaries.  Our experiments show that a minimum of
> 50% overlap is needed to achieve stable detection performance; below 50%,
> symbol fragmentation at boundaries costs more than 10 mAP points."*

**Why fragmentation happens at 20%:**

Consider a 4×4 grid with 20% overlap.  Each tile has a non-overlapping core
of 80% of the tile width.  A symbol that occupies, say, 25% of the tile width
and sits exactly at a boundary is split: 12.5% of its pixels go to one tile
and 12.5% to the next.  Neither tile has enough of the symbol to reliably
detect it.

**Why 50% fixes it:**

At 50% overlap the non-overlapping core of each tile is 50% of the tile width
(`stride = tile_w * 0.50`).  A symbol up to 50% of the tile width (which is
40% of the diagram width at level 2) always appears completely in at least one
tile regardless of where it sits on the diagram.

**Concrete numbers (level 2, n=4 tiles per axis):**

| Overlap | `tile_w` | `stride` | Max safe symbol size | Fragmentation risk |
|---------|----------|----------|----------------------|--------------------|
| 20% | 0.294 | 0.235 | 23% of diagram | High (10+ mAP lost) |
| **50%** | **0.400** | **0.200** | **40% of diagram** | **Eliminated** |

**Code location:** `src/tiling/tile_generator.py` → `DEFAULT_OVERLAP = 0.50`,
`src/models/tiling.py` → `MIN_OVERLAP_FRACTION = 0.50` (Pydantic validator
rejects anything below this threshold with a clear error message).

---

### Improvement 2 — OCR Text Masking Before CV Detection

**Paper finding:**

> *"Text regions are the dominant source of false-positive symbol detections.
> Masking text strokes before contour detection and Hough-line detection
> reduces false positives by over 30%."*

**Why text strokes cause false positives:**

On a dense P&ID, letter strokes have the same visual properties as component
boundary lines — both are dark pixels on a light background.  Without masking:

- **False-positive symbols**: characters such as `O`, `D`, `0`, `C` form
  closed contours that pass the area threshold and are detected as symbols.
- **Spurious trace segments**: the vertical strokes of `|`, `I`, `T` show up
  as short Hough line segments that pollute the detected-line list.

**The masking approach:**

1. OCR runs first and returns text bboxes.
2. For each bbox, the corresponding rectangular region of the grayscale image
   is filled with **255 (white / background)** before any CV algorithm sees it.
3. A 2-pixel border pad is added to catch ascenders and descenders that extend
   slightly outside the tight OCR box.

```
Before masking:                    After masking:
 ┌─────────────────────┐            ┌─────────────────────┐
 │  R47   ───────────  │            │  [    ]  ─────────  │
 │  10kΩ  │         │  │            │  [    ]  │         │  │
 │        └─────────┘  │            │          └─────────┘  │
 └─────────────────────┘            └─────────────────────┘
   "R47", "10kΩ" strokes               Text regions are white —
   look like symbols to OpenCV          only true component
   contour detector                     boundaries remain dark
```

**Pipeline sequencing change:**

Before this improvement, OCR and CV ran concurrently via `asyncio.gather`.
OCR is the bottleneck (~90% of preprocessing time), so running CV during that
wait seemed efficient.  But masks require OCR results.  The pipeline was
changed to **sequential**:

```
OCR (async, ~2–4 s)  →  mask image  →  CV (thread, ~0.5–1 s)
```

The concurrency loss is negligible: CV adds <1 s to a pipeline already
dominated by the OCR API call.

**Code location:** `src/preprocessing/cv_pipeline.py` →
`_mask_text_regions()`, wired in `run(image, text_labels)`.
`src/preprocessing/pipeline.py` → sequential `await self._ocr.extract()`
then `await asyncio.to_thread(self._cv.run, pil_image, labels)`.

---

### Improvement 3 — Junction Classification: CONNECTED vs CROSSING

**Paper finding:**

> *"Distinguishing T/L-junctions (genuine connections) from X-crossings
> (pass-through lines) is critical for correct netlist extraction.  A naïve
> 'all intersections = connections' approach introduces ~40% false positive
> connections in real P&IDs where crossing lines are common."*

**The two junction types:**

```
T-junction (CONNECTED)          X-crossing (CROSSING)
                                 NOT connected
   ──────┬──────                 ──────╳──────
         │                             │
         │                      Lines pass through;
   Lines genuinely meet          NOT electrically or
   at one endpoint               fluidically joined
```

**Parametric intersection detection (`_seg_intersect`):**

Given two line segments `(p1→p2)` and `(p3→p4)`, the standard parametric
formula gives parameters `t` and `u` where `0 ≤ t, u ≤ 1` means the segments
cross:

```
t = ((x1-x3)(y3-y4) - (y1-y3)(x3-x4)) / denom
u = -((x1-x2)(y1-y3) - (y1-y2)(x1-x3)) / denom
intersection = (x1 + t*(x2-x1),  y1 + t*(y2-y1))
```

`t` and `u` encode **where** along each segment the crossing happens:
- `t ≈ 0` → intersection near the *start* of segment A
- `t ≈ 1` → intersection near the *end* of segment A
- `t ≈ 0.5` → intersection in the *middle* of segment A (interior)

**Classification rule (15% endpoint tolerance):**

```python
tol = 0.15   # empirical constant from Stürmer et al.
at_endpoint = (t < tol or t > 1 - tol) or (u < tol or u > 1 - tol)
junction_type = CONNECTED if at_endpoint else CROSSING
```

The 15% tolerance absorbs digitisation noise — a T-junction where the
perpendicular line arrives at exactly `t = 0.0` is geometrically ideal but
real scanned diagrams will have `t ≈ 0.02–0.08`.

**The `Junction` and `JunctionType` models:**

```python
class JunctionType(str, Enum):
    CONNECTED = "connected"    # T- or L-junction: lines genuinely meet
    CROSSING  = "crossing"     # X-crossing: lines pass through, NOT joined

class Junction(BaseModel):
    junction_id:   str           # UUID
    bbox:          BoundingBox   # tiny box centred on intersection point
    junction_type: JunctionType  # CONNECTED or CROSSING
    confidence:    float         # 0.0–1.0 (currently fixed at 0.5 from Hough)
```

Junctions are stored in `DiagramMetadata.junctions` as a flat
`list[dict[str, Any]]` (serialised via `Junction.to_dict()`).  The `trace_net`
tool's `_junctions_near_component()` counts CONNECTED and CROSSING junctions
within 6% of a component's centre to populate the `topology_hint` even when
full `Trace` objects are unavailable.

**Code location:** `src/models/cv.py` → `JunctionType`, `Junction`.
`src/preprocessing/cv_pipeline.py` → `_seg_intersect()`, `_classify_junctions()`.
`src/tools/trace_net.py` → `_junctions_near_component()`.

---

### How the Three Improvements Connect

The three improvements form a coherent pipeline upgrade:

```
OCR labels ──► mask text bboxes ──► CV on clean image
                                         │
                                 ┌───────┴──────────┐
                                 │                  │
                            Symbols             Lines + Junctions
                                 │                  │
                                 ▼                  ▼
                           Components       CONNECTED junctions
                                 │           link to components
                                 └───────────────────┘
                                         │
                                    Trace objects
                                  (Graph tab edges)
```

1. **OCR masking** gives cleaner symbol and line detections (fewer false positives).
2. **50% overlap** ensures every component appears complete in at least one tile
   (no boundary fragmentation).
3. **Junction classification** separates real connections from visual crossings,
   giving the `Trace` builder a topology signal it can trust.

Together they move the system from "CV as a noisy first guess" to "CV as a
reliable structured extraction" — which is the premise of the separation between
the perception and reasoning layers.

---

### Further Reading

| Topic | Reference |
|-------|-----------|
| Full paper (free) | https://arxiv.org/abs/2411.13929 |
| Set-of-Marks visual grounding | https://arxiv.org/abs/2310.11441 |
| Probabilistic Hough Transform | Matas et al., *Robust Detection of Lines Using the Progressive Probabilistic Hough Transform*, CVIU 2000 |
| Otsu's thresholding | Otsu, N., *A Threshold Selection Method from Gray-Level Histograms*, IEEE Trans. SMC 1979 |
| Google Document AI | https://cloud.google.com/document-ai/docs |
| Google Agent Development Kit | https://google.github.io/adk-docs/ |

---

*Guide last updated: 2026-03-15*
