# System Architecture — Deep Dive

This document explains both the **theory** behind key design decisions and the **code implementation** of each pipeline phase. Start here to understand *why* the system is built the way it is.

---

## Table of Contents

1. [The Core Problem: Why CAD Diagrams Are Hard](#the-core-problem)
2. [Design Philosophy: Perception vs. Reasoning](#design-philosophy)
3. [System Overview](#system-overview)
4. [Phase 1: Ingestion](#phase-1-ingestion)
5. [Phase 2: Pre-Processing (OCR + CV)](#phase-2-pre-processing)
6. [Phase 3: Multi-Resolution Tiling](#phase-3-multi-resolution-tiling)
7. [Phase 4: Agentic Reasoning (ADK + Gemini)](#phase-4-agentic-reasoning)
8. [Phase 5: Output & Visualization](#phase-5-output--visualization)
9. [Web UI Frontend](#web-ui-frontend)
10. [Cross-Cutting Concerns](#cross-cutting-concerns)
10. [Storage Architecture](#storage-architecture)
11. [Token Budget Management](#token-budget-management)

---

## The Core Problem

### Spatial Resolution Loss

A production electrical schematic on a D-size sheet at 300 DPI is **7000×5000 pixels**. It packs:
- 200–500 component symbols (resistors, ICs, valves, sensors)
- 500–2000 text labels (reference designators, values, net names)
- 1–3 pixel-wide connector traces that route between components

**The critical LLM limitation:** Gemini internally downsamples all images to ~1024×1024 px. For a 7000×5000 image, each pixel in the LLM's view corresponds to **~35 original pixels**. A 10-pixel-tall text label becomes sub-pixel — invisible. A 2-pixel-wide trace disappears entirely.

No amount of prompt engineering overcomes this physical constraint. The answer is to extract information from pixels *before* the LLM sees them.

### The Hallucination Problem

When an LLM can't clearly see a label, it doesn't say "I can't tell" — it *invents* a plausible answer. In a schematic with 20 resistors labeled R1–R20, a blurry R17 may be confidently reported as "R17" when the label is actually "RT7" (a thermistor reference). For engineering applications this is unacceptable.

### The Density Problem

CAD diagrams pack information more densely than natural images. A 100×100 pixel region might contain 3 overlapping component symbols with 6 attached text labels. Standard object-detection models (YOLO, Faster-RCNN) trained on natural images fail here. Domain-specific CV is required.

---

## Design Philosophy

The fundamental insight: **separate what should be deterministic from what should be probabilistic**.

```
┌───────────────────────────────────────────────────────────────────┐
│  PERCEPTION — deterministic, repeatable, no hallucination          │
│                                                                     │
│  Document AI OCR    → structured text + bounding boxes             │
│  OpenCV contour     → component symbols with type classification    │
│  Hough transform    → connection lines + junctions                  │
│  Rule-based parser  → title block fields (drawing number, rev …)   │
└───────────────────────────────┬───────────────────────────────────┘
                                │ Pydantic v2 models
                                │ (validated, typed, JSON-serializable)
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│  REASONING — probabilistic, flexible, natural-language             │
│                                                                     │
│  "What type of valve is this symbol?"                              │
│  "Which components are in the power supply section?"               │
│  "Summarise the main signal flow from sensor to controller"        │
└───────────────────────────────────────────────────────────────────┘
```

**The LLM never reads raw pixels to extract data.** It reads structured `DiagramMetadata` returned by tool functions. It uses its vision capability only to *verify* or *classify* — tasks where probabilistic reasoning adds value (e.g., "given this symbol shape and the label 'XV-101', is this a ball valve or globe valve?").

---

## System Overview

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

**Code:** `src/orchestrator.py` → `Orchestrator.ingest()`

**HTTP endpoint:** `POST /ingest` in `src/agent/server.py`

```python
async def ingest(self, raw_bytes: bytes, filename: str) -> str:
    # 1. Decode to RGB PIL Image — normalises all input formats
    image = Image.open(BytesIO(raw_bytes)).convert("RGB")
    diagram_id = str(uuid.uuid4())

    # 2. Run pipeline stages
    metadata = await self.preprocessing_pipeline.run(image, diagram_id, filename)
    pyramid   = self.tile_generator.generate(image, metadata)

    # 3. Persist to store
    self.tile_storage.save_pyramid(pyramid, image)
    self.store.save_metadata(metadata)
    self.store.save_pyramid(pyramid)
    self.store.save_original_image(diagram_id, image)

    return diagram_id
```

**Key decisions:**
- Format normalisation happens here: PNG, JPEG, TIFF → RGB PIL Image. All downstream code sees only PIL Images.
- A UUID is assigned as the stable `diagram_id`. All subsequent API calls reference this ID.
- Ingestion is intentionally separated from analysis: one ingest, many analyses.

---

## Phase 2: Pre-Processing

**Code:** `src/preprocessing/pipeline.py` → `PreprocessingPipeline.run()`

### Theory: Why OCR Must Run Before CV (Not Concurrent)

Earlier versions ran OCR and CV concurrently with `asyncio.gather`.  This was
changed following Stürmer et al. (arXiv:2411.13929), which showed that **text
strokes are the dominant source of false-positive CV detections** on dense
engineering diagrams.  Character strokes register as closed contours (false
symbols) and short Hough segments (spurious traces).

The fix: paint every OCR bounding box white on the grayscale image *before*
any CV algorithm sees it.  This requires OCR results to be available first.

```python
async def run(self, image, filename) -> DiagramMetadata:
    # STEP 1: OCR (network call, ~2–4 s)
    labels: list[TextLabel] = await self._ocr.extract(pil_image)

    # STEP 2: CV (CPU-bound, ~0.5–1 s) with OCR text regions masked
    # _mask_text_regions() paints each text bbox white before
    # contour detection and Hough-line detection run.
    cv_result: CVResult = await asyncio.to_thread(
        self._cv.run, pil_image, labels
    )

    # Symbol → Component (geometry only; agent classifies type)
    components = [Component(...) for sym in cv_result.symbols]

    # DetectedLine → Trace (first-pass: match line endpoints to component bboxes)
    traces = _build_traces(cv_result.detected_lines, components)

    return DiagramMetadata(
        text_labels=labels, components=components, traces=traces,
        junctions=[j.to_dict() for j in cv_result.junctions], ...
    )
```

The concurrency loss (CV no longer overlaps with OCR) is negligible: CV adds
<1 s to a pipeline already dominated by the 2–4 s OCR API roundtrip.

### OCR: Document AI

**Code:** `src/preprocessing/ocr.py` → `DocumentAIOCRExtractor`

Google Cloud Document AI returns bounding polygons (4 vertices, normalized 0–1) plus a confidence score per text element. Post-processing:

1. **Confidence filter** — elements with confidence < 0.6 discarded
2. **Polygon → BoundingBox** — 4-vertex polygon → axis-aligned `BoundingBox(x_min, y_min, x_max, y_max)` using vertex envelope
3. **Deduplication** — overlapping labels with IoU ≥ 0.85 merged (keep highest confidence)
4. **Whitespace normalisation** — multi-part OCR fragments joined into single `TextLabel`

### Computer Vision: OpenCV Pipeline

**Code:** `src/preprocessing/cv_pipeline.py` → `CVPipeline`

**Text masking (new — applied before all CV):**
```
OCR text bboxes → paint each region white (255) on grayscale image
→ 2 px border pad added (catches ascenders/descenders)
→ Masked grayscale fed to all CV steps below
```
Eliminates character-stroke false positives before any detection runs.

**Symbol detection:**
```
Masked grayscale → Gaussian blur (3×3) → Otsu threshold (THRESH_BINARY_INV)
→ Find contours (RETR_EXTERNAL) → Filter area < 200 px²
→ Symbol(bbox, confidence=0.5)   [type = "unknown"; agent classifies]
```

**Line detection:**
```
Masked grayscale → Canny edge (50, 150)
→ HoughLinesP (rho=1, θ=π/180, threshold=80, minLen=20, maxGap=5)
→ DetectedLine objects with normalised coordinates
```

**Junction classification (new — Stürmer et al. 2024):**
```
For every pair of DetectedLine objects:
  _seg_intersect(A, B) → (t, u, ix, iy) or None
  if t < 0.15 or t > 0.85 or u < 0.15 or u > 0.85:
    → Junction(CONNECTED)   ← T- or L-junction; lines genuinely meet
  else:
    → Junction(CROSSING)    ← X-crossing; lines pass through, NOT connected
```

`JunctionType.CROSSING` junctions must never be treated as electrical or fluid
connections.  The `trace_net` tool's `topology_hint` and the graph visualization
both honour this distinction.

### Title Block Extraction

**Code:** `src/preprocessing/title_block.py`

Title blocks are typically large bordered rectangles in image corners (bottom-right is most common per ANSI/IEC standards). The extractor:
1. Scans the 4 corners of the image for large rectangular OCR regions
2. Collects all `TextLabel` objects whose centroid falls within the candidate region
3. Applies regex pattern matching to identify structured fields (drawing number, revision, date, author)
4. Returns a `TitleBlock` Pydantic model (or `None` when not detected)

### Fallback Behaviour

When Document AI credentials or the processor ID are not configured, the server falls back to **no-op OCR/CV stubs** (defined in `server.py`):

```python
class _NoOpOCR:
    async def extract(self, image) -> list:
        return []   # empty text labels

class _NoOpCV:
    def run(self, image) -> CVResult:
        return CVResult()  # empty symbols, lines
```

The agent still functions — it receives visual analysis of the diagram image via `inline_data`. Structured data is empty but the agent can still reason visually. This is the "offline" mode.

---

## Phase 3: Multi-Resolution Tiling

**Code:** `src/tiling/tile_generator.py` → `TileGenerator.generate()`

### Theory: The Zoom Problem

The fundamental constraint: the LLM sees all images at ~1024×1024 px. A tile covering 25% of the diagram's area and rendered at 512 px gives the agent **2× better effective resolution** compared to seeing the full diagram at 1024 px.

| Level | Grid | Tiles | Coverage per tile (50% overlap) | Effective resolution vs. full-image |
|-------|------|-------|----------------------------------|-------------------------------------|
| L0    | 1×1  | 1     | 100%                             | 1× (baseline orientation) |
| L1    | 2×2  | 4     | ~70%                             | ~1.5× |
| L2    | 4×4  | 16    | ~40%                             | ~2–3× |

**Total: 21 tiles per diagram.** When the agent calls `inspect_zone`, the tool selects the most-detailed tiles whose bounding boxes intersect the queried region.

### The 50% Overlap Design (Stürmer et al. 2024)

```python
# src/tiling/tile_generator.py
DEFAULT_OVERLAP = 0.50    # raised from 0.20 — see Stürmer et al. arXiv:2411.13929

def _tile_coords(self, n: int, overlap_fraction: float) -> list[tuple[float, float]]:
    if n == 1:
        return [(0.0, 1.0)]
    tile_width = 1.0 / (1.0 + (n - 1) * (1.0 - overlap_fraction))
    step = tile_width * (1.0 - overlap_fraction)
    return [(max(0.0, i * step), min(1.0, i * step + tile_width)) for i in range(n)]
```

For n=4, overlap=0.50: `tile_width = 0.40`, `step = 0.20`.

**Why 50% not 20%?** Stürmer et al. measured that symbol fragmentation at tile
boundaries costs **>10 mAP points** at any overlap below 50%.  The 15%
improvement in detection accuracy justifies the ~2× storage cost.  A
`MIN_OVERLAP_FRACTION = 0.50` validator in `TileLevel` rejects lower values
at construction time to prevent accidental regression.

**Trade-off:** 50% overlap at level 2 means each of the 16 tiles contains
content from a 40%×40% region (not 25%×25%).  Adjacent tiles share half their
content.  Total unique pixel coverage is the same; the duplication is the cost.

### Set-of-Marks (SOM) Visual Grounding

Inspired by the ["Set-of-Marks"](https://arxiv.org/abs/2310.11441) visual grounding technique. When `inspect_zone()` retrieves tiles it calls `annotate_tile_with_som()` in `src/tools/_image_utils.py`:

```python
def annotate_tile_with_som(tile_image, components, text_labels, tile_bbox):
    draw = ImageDraw.Draw(tile_image.copy())
    markers = []

    for i, comp in enumerate(components_in_tile, start=1):
        px = comp.bbox.to_pixel_coords(tile_w, tile_h)
        draw.rectangle(px, outline="red", width=2)
        draw.text((px[0], px[1] - 15), f"[{i}]", fill="red", font=font)
        markers.append({"id": str(i), "type": comp.component_type, "text": "", ...})

    # Similar for text_labels (blue rectangles)
    return annotated_image, markers
```

The agent receives both the annotated image (base64 JPEG) and the `markers` list mapping each `[N]` number to component type, text, and pixel bbox. The agent then says *"Marker [3] is a gate valve labeled XV-101"* — a precise, verifiable reference to a specific element.

**Why this works:** Without SOM markers, the agent must reference elements by describing their visual appearance or approximate pixel location — both error-prone. With numbered markers, the reference is unambiguous.

---

## Phase 4: Agentic Reasoning (ADK + Gemini)

### Theory: How ADK Function Calling Works

Google ADK wraps Gemini's native function calling capability into a Python framework. The multi-turn loop:

```
1. Agent receives: user query + diagram image + diagram_id → Content object
2. Gemini decides to call a tool (e.g., get_overview)
3. ADK intercepts the FunctionCall, routes to before_tool callback
4. before_tool validates args, starts ToolCallTracker timing
5. The actual Python function executes, reads from DiagramStore
6. Tool result (dict) returned → after_tool callback (end timing, log)
7. Tool result sent back to Gemini as FunctionResponse
8. Gemini may call another tool OR produce a final text response
9. Loop until final response
```

The LLM never directly calls Python. ADK manages the message loop: it serialises Gemini's `FunctionCall` requests into Python function invocations, executes the registered tool, and returns the JSON-serialised result as a `FunctionResponse` message.

### CADAnalysisAgent Class

**Code:** `src/agent/cad_agent.py`

```python
class CADAnalysisAgent:
    def __init__(self, model=DEFAULT_MODEL, *, _agent_cls=None, _runner_cls=None, _types_mod=None):
        # Dependency injection: real ADK in production, mocks in tests
        agent_cls = _agent_cls or _LlmAgent
        if agent_cls is None:
            raise RuntimeError("google-adk is not installed")

        self._agent = agent_cls(
            model=model,
            name="cad_analysis_agent",
            tools=[get_overview, inspect_zone, inspect_component, search_text, trace_net],
            global_instruction=GLOBAL_INSTRUCTION,
            instruction=AGENT_INSTRUCTION,
            before_tool_callback=before_tool,
            after_tool_callback=after_tool,
        )

    async def analyze_async(self, diagram_id, query) -> dict[str, Any]:
        from .callbacks import tracker
        tracker.reset()   # clear previous run's records

        # Build Content: text query + diagram image as inline_data
        full_query = f"Diagram ID: {diagram_id}\n\n{query}"
        parts = [types.Part(text=full_query)]
        image_part = _load_image_part(diagram_id, self._types_mod)  # 768px JPEG
        if image_part:
            parts.append(image_part)

        content = types.Content(role="user", parts=parts)

        text = await _run_with_retry(
            runner_cls=self._runner_cls, agent=self._agent,
            user_id=user_id, session_id=sid, content=content
        )

        return {"text": text, "tool_calls": tracker.get_records()}
```

**The DI seam (`_agent_cls`, `_runner_cls`, `_types_mod`):** All tests inject mock classes instead of real ADK/genai dependencies. No real API calls in tests. This is the standard pattern for testing framework-dependent code.

### ToolCallTracker

**Code:** `src/agent/callbacks.py`

A module-level singleton that accumulates per-tool timing and result summaries across a single `analyze_async()` run:

```python
class ToolCallTracker:
    def record_start(self, tool_name: str, args: dict) -> None:
        record = ToolCallRecord(
            tool_name=tool_name,
            args=_sanitize_args(tool_name, args),   # strips large base64 values
            start_time=time.monotonic(),
        )
        self._pending[tool_name] = record

    def record_end(self, tool_name: str, *, success: bool, result_summary: str) -> None:
        record = self._pending.pop(tool_name)
        record.duration_ms = round((time.monotonic() - record.start_time) * 1000, 1)
        record.success = success
        record.result_summary = result_summary
        self._records.append(record)

tracker = ToolCallTracker()  # module-level singleton
```

The tracker is wired via `before_tool_callback` and `after_tool_callback` on the `LlmAgent`. After the run completes, `tracker.get_records()` returns the list of dicts that populates the `tool_calls` field in the API response and the frontend's "Agent Activity" timeline.

### System Prompt Design

**Code:** `src/agent/prompts.py`

Two levels of instruction are registered on the `LlmAgent`:

- **`GLOBAL_INSTRUCTION`** — sets the agent's role and general capabilities (applies to all conversations)
- **`AGENT_INSTRUCTION`** — the step-by-step workflow the agent must follow for every analysis

The workflow prompt encodes the expert heuristic:
1. Always call `get_overview` first — orient, confirm component/label counts, read title block
2. Use `inspect_zone` with percentage-based coordinates to zoom into regions of interest
3. Reference elements by SOM marker numbers (`[N]`) not by visual description or pixel coords
4. Use `search_text` to look up specific labels or reference designators by value
5. Use `trace_net` to verify connections structurally (not by visual inspection)
6. State confidence levels explicitly; distinguish "detected by OCR" from "inferred visually"

### Retry with Exponential Backoff

**Code:** `src/agent/cad_agent.py` → `_run_with_retry()`

Vertex AI has transient failure modes: 429 (rate limit), 503 (service unavailable), quota exceeded. The retry logic:

```python
async def _run_with_retry(runner_cls, agent, user_id, session_id, content):
    backoff = 2.0
    for attempt in range(4):   # up to 3 retries
        try:
            runner = runner_cls(agent=agent)
            runner.auto_create_session = True
            # Use unique session ID on retries to avoid stale ADK state
            retry_sid = session_id if attempt == 0 else f"{session_id}-r{attempt}"

            last_text = ""
            async for event in runner.run_async(
                user_id=user_id, session_id=retry_sid, new_message=content
            ):
                if _is_final_response(event):
                    text = _extract_text(event)
                    if text:
                        last_text = text
            return last_text

        except Exception as exc:
            is_transient = any(kw in str(exc).lower()
                               for kw in ("429", "503", "rate", "quota", "unavailable"))
            if not is_transient or attempt >= 3:
                raise
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)   # cap at 30 seconds
```

---

## Phase 5: Output & Visualization

### Analysis Response

The `/analyze` endpoint returns a `dict` with two keys:

```json
{
  "text": "The diagram contains 42 components including...",
  "tool_calls": [
    {
      "tool_name": "get_overview",
      "args": {"diagram_id": "550e8400-..."},
      "duration_ms": 142.3,
      "success": true,
      "result_summary": "42 components, 230 text labels"
    },
    {
      "tool_name": "inspect_zone",
      "args": {"x1": 0, "y1": 0, "x2": 50, "y2": 50},
      "duration_ms": 2341.0,
      "success": true,
      "result_summary": "3 tiles, 12 components, 45 labels"
    }
  ]
}
```

The `tool_calls` list lets you see exactly what the agent did — which tools it called, what arguments it used, how long each took, and whether it succeeded. The frontend's "Agent Activity" timeline renders this as collapsible cards.

### Interactive HTML Visualization

**Code:** `src/tools/export_visualization.py`

The visualization is a **self-contained HTML file** (no server needed after download, except Mermaid.js loaded from CDN for the connectivity graph). It includes:

- **Left panel:** Zoomable/pannable diagram image (CSS transform + mouse wheel) with SVG bounding-box overlays (red=components, blue=text labels). Click an overlay → highlights corresponding sidebar entry.
- **Right panel (3 tabs):**
  - **Components:** Searchable list with confidence colour-coding (green ≥80%, yellow 50–79%, red <50%). Type filter chips toggle visibility by component type. Click → highlights SVG overlay.
  - **Graph:** Mermaid.js diagram with a three-way fallback driven by `_build_mermaid(traces, components) → (definition, mode)`:
    - `mode = "connectivity"` — traces exist → directed `graph LR` with pin labels
    - `mode = "topology"` — no traces but components detected → component nodes
      grouped by type in Mermaid subgraphs; no edges; info banner shown
    - `mode = ""` — no data → empty-state message
  - **Details:** Component detail panel shown on click: type, value, confidence, bbox, pin count.

#### Mermaid Node ID Sanitization

The Graph tab uses Mermaid.js, which has strict node ID constraints: no spaces, no leading digits, no special characters. Real component data commonly violates all three (e.g. "NPN Transistor", "2N3904", "10K"). The `_mermaid_safe()` / `_mermaid_display()` helper pair separates identifier concerns from display concerns:

```python
def _mermaid_safe(raw: str) -> str:
    """Produce a valid Mermaid node identifier (alphanumeric + underscore, no leading digit)."""
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", raw.replace("-", "_").replace(" ", "_"))
    safe = re.sub(r"_+", "_", safe).strip("_")
    if safe and safe[0].isdigit():
        safe = "n" + safe
    return safe or "unknown"

def _mermaid_display(text: str) -> str:
    """Produce a display label (truncated, quotes escaped)."""
    return text.replace('"', "'")[:30]
```

Connectivity traces use component UUIDs (not display labels) as Mermaid node identifiers (`from_id` / `to_id` fields), so two resistors both labeled "10K" remain separate nodes in the graph rather than collapsing into one.

### Web UI Frontend

**Code:** `frontend/index.html`, `frontend/css/styles.css`, `frontend/js/app.js`

The web UI at `GET /` provides a single-page application covering the full user workflow.

#### Upload & Pipeline Phases

The 4-phase pipeline is visualised as a horizontal progress bar: **Upload → Preprocess → AI Analysis → Results**. Each phase shows:
- A spinner while active
- A green checkmark + elapsed time badge on completion
- Sub-step messages (e.g. "Extracting text labels…", "Building tile pyramid…")

Accepted upload formats: **PNG, JPEG, TIFF, WebP** — validated client-side by MIME type and file extension before the upload is sent to the server.

#### Split Workspace Layout

After the first analysis completes, the UI activates a **split workspace** via a CSS grid:

```css
#workspace.workspace-active {
    display: grid;
    grid-template-columns: minmax(280px, 1fr) minmax(340px, 1.15fr);
}
```

The diagram image is pinned in the left panel (sticky, `fitImage()` scales it to viewport height) while the chat thread and results appear in the right panel. The image remains visible throughout all follow-up questions — no more losing the diagram when scrolling through answers.

#### Conversation Thread

Each Q&A exchange is rendered as a `.conv-turn` block appended to `#chat-history`:
- User question: right-aligned bubble (`.conv-question-bubble`)
- Agent answer: full-width block below (`.conv-answer`) with the Agent Activity timeline

A `.thinking-placeholder` with a spinner is inserted **immediately on submit** (before the server responds) so the UI feels responsive. When the response arrives, `updateConversationTurn()` replaces the placeholder in-place.

#### Follow-up Request Flow

```
User types follow-up → appendConversationTurnPlaceholder()
        │
        ▼
runAnalysis(queryText, isFollowup=true)
        │
        ├── Phases 1+2 shown as "skipped" (diagram already ingested)
        ├── POST /analyze  {diagram_id: currentDiagramId, query: queryText}
        │
        ▼
updateConversationTurn(turnId, responseData)
        └── Replaces placeholder with real answer + tool timeline
```

Follow-up queries skip the ingest pipeline entirely — they call `POST /analyze` with the cached `diagram_id`. Only Phase 3 (tiling) and Phase 4 (agent) indicators update; Phases 1 and 2 display a "skipped" badge.

---

## Cross-Cutting Concerns

### The DiagramStore Singleton

**Code:** `src/tools/_store.py`

All five tool functions need access to `DiagramMetadata` and `TilePyramid` but can only receive JSON-serializable arguments from the LLM (a string `diagram_id`). The store singleton bridges this gap:

```python
_instance: DiagramStore | None = None

def get_store() -> DiagramStore:
    if _instance is None:
        raise RuntimeError("Store not configured. Call configure_store() first.")
    return _instance

def configure_store(store: DiagramStore) -> None:
    global _instance
    _instance = store
```

Production startup calls `configure_store(InMemoryDiagramStore())`. Tests call `configure_store(MagicMock(spec=DiagramStore))` to inject controlled mock data. Tool functions are completely decoupled from storage implementation — they call `get_store()` and never reference concrete storage classes.

### Coordinate System Conventions

Three coordinate systems co-exist in the codebase:

| System | Range | Used by |
|--------|-------|---------|
| **Normalised** | 0.0–1.0 | All Pydantic models (`BoundingBox` fields) |
| **Pixel** | 0–width / 0–height | SOM annotation drawing, crop operations |
| **Percentage** | 0–100 | `inspect_zone` tool arguments (LLM-facing) |

The percentage convention for `inspect_zone` was chosen deliberately: LLMs reason more naturally about "the top-left 25% of the diagram" than "normalised coordinates 0.0 to 0.25". The tool divides by 100 internally before passing to normalised-coordinate functions.

Conversion helpers in `BoundingBox`:
- `.to_pixel_coords(width, height)` → `(x_min_px, y_min_px, x_max_px, y_max_px)`
- `.from_pixel_coords(x_min, y_min, x_max, y_max, width, height)` → normalised `BoundingBox`
- `bbox_to_pixel_dict(bbox, width_px, height_px)` → `{"x", "y", "w", "h"}` dict (for SOM drawing)

### Graceful Degradation

The system degrades gracefully at every layer:

| Missing component | Fallback |
|-------------------|----------|
| Document AI credentials | No-op OCR stub → empty text labels |
| OpenCV detection failures | Empty component/trace lists |
| No tile pyramid | `inspect_zone` crops original image directly |
| No traces in metadata | `trace_net` returns `trace_data_unavailable: true` + `topology_hint` with nearby junction counts |
| Vertex AI transient error | Exponential backoff retry (3 attempts, 2s→4s→8s→30s cap) |
| `google-adk` not installed | `_agent = None`, server returns 503 with clear error message |
| Image not available | `_load_image_part()` returns `None`, no inline_data in Content |

---

## Storage Architecture

### Local Development (current)

```
InMemoryDiagramStore  — Python dicts in src/orchestrator.py
                         holds: metadata (DiagramMetadata), pyramids (TilePyramid),
                                tile images (PIL.Image), original images (PIL.Image)
                         lost on server restart

LocalStorage          — tiles written to /tmp/cad-diagram-analyzer/tiles/{diagram_id}/
                         as JPEG files
```

### Production (planned)

```
Cloud Firestore  — DiagramMetadata + TilePyramid JSON documents
GCS Bucket       — original images + tile JPEG files
```

**The storage swap requires only one change:** replace `InMemoryDiagramStore()` with a Firestore-backed implementation in `server.py`'s `_build_orchestrator()`. All tool code calls `get_store()` — it is completely storage-agnostic.

---

## Token Budget Management

Gemini 2.5 Flash has a 1M token context window. Approximate token cost for a typical 5-tool analysis:

| Content | Est. Tokens |
|---------|------------|
| Initial image (768 px JPEG, quality=85) | 40,000–80,000 |
| System prompts (global + agent instruction) | 2,000–4,000 |
| `get_overview` response (JSON) | 200–500 |
| 3× `inspect_zone` calls (3 tiles × 512 px each) | 180,000–360,000 |
| `search_text` + `trace_net` responses | 2,000–10,000 |
| ADK session messages + function call metadata | 5,000–15,000 |
| **Total** | **~230,000–470,000** |

This leaves 530K–770K tokens of headroom. Controls that keep usage within budget:

| Control | Default | Saves |
|---------|---------|-------|
| JPEG@768px for initial image (not PNG@1024px) | `quality=85` | ~100–300K tokens/turn |
| Max 3 tiles per `inspect_zone` call | Hard cap in `inspect_zone.py` | ~200K tokens |
| Max 512 px per tile (not full resolution) | `downscale_to_fit(tile, 512)` | ~50K per tile |
| Max 50 text labels per zone | `labels[:50]` + `truncated` flag | ~20K per call |
| Max 100 `search_text` matches | `matches[:100]` + `truncated` flag | ~50K per call |
| `get_overview` returns no image | Structured JSON only | ~400K saved |

If token issues arise, switch to `TOOL_MODEL=gemini-3.1-pro-preview` which has a larger effective context for complex visual reasoning.

---

## Server Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest` | Upload image → run pipeline → return `diagram_id` |
| `POST` | `/analyze` | Run ADK agent on a pre-ingested diagram |
| `GET`  | `/visualization/{id}` | Self-contained interactive HTML visualization |
| `GET`  | `/docs` | Swagger UI (auto-generated by FastAPI) |
| `GET`  | `/` | Static web UI frontend |
