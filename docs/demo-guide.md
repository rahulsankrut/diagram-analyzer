# CAD Diagram Analyzer — Demo Guide

**Two audiences. One system. Tailored presentations.**

This guide gives you everything you need to run a compelling, accurate demo
for both non-technical stakeholders and engineering teams. Each section is
self-contained — run only the one you need.

---

## Contents

- [Pre-Demo Checklist](#pre-demo-checklist)
- [Part A — Non-Technical Audience](#part-a--non-technical-audience)
- [Part B — Technical Audience](#part-b--technical-audience)
- [Sample Queries (both audiences)](#sample-queries)
- [Troubleshooting During the Demo](#troubleshooting-during-the-demo)

---

## Pre-Demo Checklist

Complete these steps **before** the audience arrives.

### 1. Start the server

```bash
cd /path/to/cad-diagram-analyzer
python -m src.agent.server
```

Confirm it is running:

```
INFO:     Uvicorn running on http://0.0.0.0:8080
```

Open **http://localhost:8080** in your browser. You should see the dark-themed
UI with tech pills (Google ADK · Gemini 2.5 · Document AI OCR · OpenCV ·
Multi-Resolution Tiling) in the header.

### 2. Have a diagram ready

| Diagram Type | What it Shows Off |
|---|---|
| Electrical schematic (≥ A2 size) | Component detection, text search, trace following |
| P&ID (piping & instrumentation) | Dense symbol detection, zone inspection |
| Any multi-page engineering drawing | Title block extraction, spatial reasoning |

> **Tip:** Run a "warm-up" query 5 minutes before the demo starts. The first
> call to Vertex AI can take 3–5 seconds to cold-start. Subsequent calls are
> fast.

### 3. Know these three talking points

1. The core problem: **LLMs cannot reliably read dense engineering diagrams**
   because they downsample images from 7 000 × 5 000 px to ~1 024 px
   internally — a 35× resolution loss that wipes out fine text and thin traces.
2. The solution: **separate perception from reasoning** — CV/OCR extracts
   exact facts deterministically; the LLM reasons over structured data and
   verifies with high-resolution tile crops.
3. The result: **verifiable, grounded answers** — every claim the agent makes
   can be traced back to a numbered marker on a specific tile.

---

## Part A — Non-Technical Audience

**Tone:** Business value, analogy-driven, visual.
**Time:** 15–20 minutes.
**Goal:** Audience understands *what* the system does and *why it matters*,
not *how* it works internally.

---

### Opening (2 min)

Start with a relatable problem statement before touching the app:

> *"Imagine you have a thousand-page electrical manual and you need to find
> every component connected to a specific power rail. A junior engineer might
> take half a day. A senior engineer might take an hour. And if they miss one
> connection, the consequences can be costly.*
>
> *Now imagine you can upload the drawing and just ask: 'What connects to VCC?'
> and get a precise, cited answer in under 30 seconds."*

Then open the app.

---

### Act 1 — The Upload (3 min)

**What to say:**

> *"The first thing we do is upload the diagram. This is just a standard image
> file — a scan, a PDF export, anything. The system doesn't need special
> formats."*

**What to do:**

1. Drag-and-drop (or click to select) your CAD diagram into the upload area.
2. Point out the **4-phase pipeline** that appears immediately:

```
[UPLOAD] ──── [PREPROCESS] ──── [AI ANALYSIS] ──── [RESULTS]
```

> *"You can see the system working in real time. The first phase, Upload,
> happens immediately — the file is ready."*

**Key message:**
The pipeline makes the system transparent. The audience can see where their
data is at every moment.

---

### Act 2 — Pre-processing (3 min)

Watch the **PREPROCESS** phase activate (spinning ring, "Extracting text
labels…" sub-message cycling).

**What to say:**

> *"Before the AI even looks at the diagram, our system does the hard
> perceptual work automatically.*
>
> *Think of it like a very thorough assistant who reads the whole document
> first, highlights every component, writes down every label, and organises
> it all into a structured list — so that when the AI asks a question, it can
> look things up rather than squinting at a blurry image.*
>
> *This takes about 2–5 seconds."*

When PREPROCESS shows the green ✓ and timing badge:

> *"Done. It's found the components, read the text, and built an internal map
> of the diagram."*

**Key message:**
The system is deterministic at this stage — no hallucination possible because
nothing is being inferred yet, just extracted.

---

### Act 3 — Asking a Question (5 min)

Type a question in the **Ask the Agent** box. Good starter queries for
non-technical demos:

| Query | Why it's good |
|---|---|
| `What is this diagram of? Give me an overview.` | Shows title block extraction and structural understanding |
| `How many components are in this diagram?` | Concrete number, verifiable |
| `What does the top-right section of the diagram show?` | Demonstrates spatial reasoning |
| `Find all labels that contain a voltage reference` | Demonstrates text search |

**What to say while AI ANALYSIS phase spins:**

> *"Now the AI agent is running. Notice the sub-messages — it's telling you
> exactly what it's doing: getting an overview, zooming into regions,
> searching for labels.*
>
> *This isn't a black box. You can see every step."*

---

### Act 4 — The Results (5 min)

When the fourth phase turns green and the result appears:

**Point out the Agent Activity section** (collapsible timeline of tool calls):

> *"See this section — Agent Activity? This shows every tool the AI used to
> arrive at its answer. Not just the answer, but the reasoning path.*
>
> *For compliance, audit, or just peace of mind — you can always trace exactly
> how the system reached its conclusion."*

**Read the response out loud** and highlight any specific references the agent
makes (e.g., "In the upper-left quadrant, component R47...").

> *"The agent isn't guessing. It's telling us exactly where on the diagram it
> found this information."*

---

### Closing — Non-Technical (2 min)

**Key takeaways to summarise:**

1. **Speed:** A query that takes an engineer hours takes the system seconds.
2. **Accuracy:** Structured extraction + AI reasoning, not pure AI guessing.
3. **Transparency:** Full audit trail of every tool call.
4. **Flexibility:** Any engineering diagram format, any question.

**Anticipated questions:**

| Question | Answer |
|---|---|
| *"Can it be wrong?"* | It can — AI is probabilistic. But it cites sources. If it says "Marker [3], tile L2-R1-C0", you can verify. The system is designed to show its work, not hide uncertainty. |
| *"What types of diagrams does it handle?"* | Electrical schematics, P&IDs, mechanical drawings, any dense technical diagram at high resolution. |
| *"Is our diagram data secure?"* | The system runs entirely on your own Google Cloud project. Diagrams never leave your infrastructure. |
| *"How long does it take per diagram?"* | Upload + pre-processing: 2–10 seconds. Each query: 5–30 seconds depending on complexity. |
| *"Can it be integrated into our tools?"* | Yes — it exposes a standard REST API. Any tool that can make an HTTP POST request can query it. |

---

## Part B — Technical Audience

**Tone:** Architecture-first, code-honest, invite challenge.
**Time:** 30–45 minutes (20 min demo + 10–15 min Q&A).
**Goal:** Engineers understand the design decisions deeply enough to evaluate,
extend, or integrate the system.

---

### Opening — The Core Problem (5 min)

Start with the math before the demo:

> *"A D-size schematic at 300 DPI is roughly 7 000 × 5 000 pixels. Gemini
> and GPT-4V internally downsample multimodal input to around 1 024 × 1 024.
> That's a 35× linear resolution loss — fine text like '10kΩ' that's 12 px
> tall at original resolution becomes 0.34 px after downsampling. It's
> literally sub-pixel.*
>
> *If you feed raw CAD images to an LLM, you get hallucinated component values,
> missed connections, and no way to verify claims. This system is designed to
> make that problem go away."*

Draw (or show) this separation:

```
PERCEPTION LAYER                REASONING LAYER
─────────────────               ─────────────────
Document AI OCR  ──┐            LLM (Gemini 2.5)
OpenCV detection ──┼──► Pydantic models ──► ADK agent
Tile pyramid     ──┘    (components,          │
(3-level, 21 tiles)      text labels,         ▼
                         traces)          Tool calls
                                          + SOM tiles
```

> *"The LLM never sees raw pixels as its primary source of truth. It reasons
> over structured Pydantic models and uses vision only to verify."*

---

### Architecture Walkthrough (10 min)

#### The Ingest Pipeline

```
POST /ingest (image upload)
        │
        ▼
orchestrator.py ──► run concurrently:
        ├── Document AI OCR  →  TextLabel[]  (bbox, confidence, text)
        └── OpenCV CV        →  Component[]  (type, bbox, confidence)
        │
        ▼
TileGenerator (tiling/)
        ├── Level 0: 1×1  (full image, 512px)
        ├── Level 1: 2×2  (4 tiles, 20% overlap)
        └── Level 2: 4×4  (16 tiles, 20% overlap)
        │
        ▼
DiagramStore.save(DiagramMetadata)
        └── Returns diagram_id (UUID)
```

**Key design decision — 20% tile overlap:**

> *"Tiles at each level overlap by 20% of the tile width. This prevents
> components that straddle tile boundaries from being split across two tiles,
> which would make them invisible to both. The formula is simple:*

```python
# tiling/tile_generator.py
stride_x = tile_w * (1 - overlap)   # 0.80 × tile_w
stride_y = tile_h * (1 - overlap)
```

> *21 tiles total at 512×512 px. At ~60K tokens per JPEG tile, we cap
> inspect_zone at 3 tiles per call to stay within the 1M token context limit."*

#### The Agent

```
POST /analyze
        │
        ▼
CADAnalysisAgent.analyze_async(diagram_id, query)
        │
        ├── tracker.reset()
        ├── Encode diagram image as JPEG@768px → inline_data Part
        ├── InMemoryRunner.run_async()
        │       │
        │       └── LlmAgent (Gemini 2.5 Flash)
        │               ├── before_tool() → validate diagram_id, record_start()
        │               ├── Tool call (get_overview / inspect_zone / ...)
        │               └── after_tool() → record_end(), result_summary
        │
        ├── tracker.get_records() → tool_calls[]
        └── Returns {"text": "...", "tool_calls": [...]}
```

**Show the callbacks code:**

```python
# src/agent/callbacks.py

def before_tool(tool, args, tool_context) -> dict | None:
    tool_name = getattr(tool, "name", str(tool))
    if tool_name in _DIAGRAM_TOOLS:
        diagram_id = args.get("diagram_id", "")
        if not diagram_id or not isinstance(diagram_id, str):
            return {"error": "diagram_id is required"}   # short-circuit, no exception
    tracker.record_start(tool_name, dict(args))
    return None   # proceed normally

def after_tool(tool, args, tool_context, tool_response) -> dict | None:
    success = "error" not in tool_response
    summary = _summarise_result(tool_name, tool_response)
    tracker.record_end(tool_name, success=success, result_summary=summary)
    return None   # pass response unchanged to LLM
```

> *"Tools return `{'error': '...'}` instead of raising exceptions. If a tool
> raised, it would crash the ADK runner and terminate the agent run. Error
> dicts let the LLM see the failure as a FunctionResponse and retry with
> corrected arguments."*

---

### Live Demo — Technical Queries (10 min)

With the diagram already ingested, run these in order to show different tool
invocations:

#### Query 1 — Overview (get_overview only)
```
Give me a structural summary of this diagram including component counts,
types, and the title block.
```
**What to watch:** Agent Activity should show a single `get_overview` call,
~50–200ms. Point out that no images are returned — this is structured data
only, which is why it's fast and token-cheap.

#### Query 2 — Zone Inspection (get_overview + inspect_zone)
```
Zoom into the upper-left quadrant and describe what you see in detail,
referencing specific marker numbers.
```
**What to watch:** Two tool calls. The `inspect_zone` call will take 1–3s
(tile loading + SOM annotation). Show the `result_summary`: "3 tiles, N
components, M labels". Point out the SOM grounding in the response text
("Marker [2] shows...").

#### Query 3 — Text Search (search_text)
```
Search for all labels containing "GND" and tell me where they appear
on the diagram.
```
**What to watch:** `search_text` returns bbox + tile coordinates for every
match. The agent converts these to spatial descriptions ("In the lower-right
region...").

#### Query 4 — Multi-Tool (full workflow)
```
Find resistor R47, inspect it in detail, and tell me what it connects to.
```
**What to watch:** This triggers the full 5-tool workflow:
`get_overview` → `search_text("R47")` → `inspect_component(sym_xxx)` →
`trace_net(sym_xxx, "")`. Show the tool timeline with per-call durations.

---

### Architecture Deep-Dive — Key Design Decisions (5 min)

For the technical Q&A section, be ready to explain these:

#### Why ADK instead of LangChain / bare function calling?

> *"ADK gives us `before_tool` and `after_tool` lifecycle hooks on every
> function call. That's how we get timing, argument sanitisation, and the
> ToolCallTracker — all outside the tool functions themselves, which stay
> clean. LangChain callbacks exist but are more complex to wire. Bare function
> calling has no lifecycle hooks at all."*

#### Why Pydantic v2 models for internal data?

> *"Type safety at the boundary. Document AI returns raw JSON; OpenCV returns
> numpy arrays. Both get normalised into Pydantic models before the agent ever
> sees them. `.model_dump(mode='json')` gives us clean JSON-serialisable dicts
> for tool return values. If a field is missing or malformed, Pydantic raises
> at ingest time — not at query time when the LLM is mid-reasoning."*

#### Why percentage coordinates (0–100) for inspect_zone, not pixels?

> *"Diagrams vary from 2 000 × 1 500 px thumbnails to 12 000 × 8 000 px
> D-size scans. Percentage coordinates are resolution-independent — the LLM
> can reason 'upper-left quadrant' as `x1=0, y1=0, x2=50, y2=50` regardless
> of the actual pixel dimensions. The tool converts to pixels internally.*
>
> *Internally everything is stored as normalised 0–1 floats (Pydantic models)
> to match Document AI's output format. The 0–100 API is just a friendlier
> interface for the LLM prompt."*

#### What happens when CV/OCR finds nothing?

> *"Graceful degradation. The agent's system prompt has an explicit branch:
> 'If component_count=0 and text_label_count=0, fall back to visual analysis
> of the diagram image you received directly.' The image is always sent as an
> inline_data Part at conversation start — structured data enriches it but
> isn't required. The agent can still answer questions purely visually, it
> just loses the precision and citeability of structured data."*

#### Token budget numbers

| Source | Tokens (approx) | Notes |
|---|---|---|
| Initial diagram image (JPEG@768px) | 500K–800K | Sent once at conversation start |
| `get_overview` response | ~300 | Structured JSON only |
| `inspect_zone` response (3 tiles) | ~180K | 3 × 512px JPEG ≈ 60K each |
| `search_text` response (100 matches) | ~5K | Text only |
| `inspect_component` response | ~20K | 1 crop PNG |
| `trace_net` response | ~1K | JSON path data |

> *"Gemini 2.5 Flash has a 1M token context window. A heavy multi-tool query
> with 2 zone inspections consumes roughly 850K tokens. The caps (3 tiles, 50
> labels, 100 text matches) are safety valves, not arbitrary limits."*

---

### Showing the Visualization Endpoint (3 min)

Navigate to:
```
http://localhost:8080/visualization/{diagram_id}
```

(Replace `{diagram_id}` with the UUID returned by `/ingest`.)

**What to show:**
- Left panel: diagram image with colour-coded SVG overlays
  - Red = detected components
  - Blue = text labels
- Right panel:
  - **Components tab**: searchable list, confidence colour-coding
    (green ≥ 80%, yellow 50–79%, red < 50%)
  - **Graph tab**: Mermaid.js connectivity diagram
  - **Details tab**: click any component for bbox, type, confidence, nearby
    components
- Bidirectional highlighting: click a sidebar item → overlay highlights;
  click an overlay rect → sidebar scrolls

> *"This is a self-contained HTML file generated server-side. No external
> dependencies except Mermaid.js from CDN. You can email it or drop it in
> a shared drive — it works offline."*

---

### Extending the System (2 min)

For engineering teams evaluating adoption, walk through **how to add a tool**
in 6 steps:

```
1. src/tools/my_new_tool.py   — def my_new_tool(diagram_id: str, ...) -> dict
2. src/agent/cad_agent.py     — add to self._tools list
3. src/agent/callbacks.py     — add to _DIAGRAM_TOOLS set
4. src/agent/callbacks.py     — add case in _summarise_result()
5. tests/test_tools/           — test file with configured_store fixture
6. src/agent/prompts.py        — describe when to call it in system prompt
```

> *"The test infrastructure uses a DI seam — `configure_store(mock_store)`
> injects a mock `DiagramStore` before each test. No real OCR, no Gemini
> calls, no GCS. The whole tool logic is testable in isolation in
> milliseconds."*

---

### Closing — Technical (2 min)

**Honest limitations to acknowledge proactively:**

| Limitation | Current state | Roadmap |
|---|---|---|
| Trace extraction accuracy | CV-based, works best on clean digital schematics | Planned: transformer-based graph extraction |
| Concurrent users | In-memory store, single-process | Production: GCS + Firestore backend (schema ready) |
| Diagram types | Best on electrical schematics and P&IDs | P-graph, BOM, isometric: extending symbol library |
| Max diagram size | ~15 000 × 10 000 px before tiling overhead dominates | Streaming tile loading planned |

**Anticipated technical questions:**

| Question | Answer |
|---|---|
| *"Why Gemini over GPT-4o?"* | Vertex AI gives us ADC auth (no API key management), 1M token context, and ADK framework support. GPT-4o would require a separate tool framework. Model is configurable via `GEMINI_MODEL` env var. |
| *"How do you handle multi-page diagrams?"* | Each page is ingested as a separate `diagram_id`. The agent can be given multiple IDs and a meta-query to correlate across pages. |
| *"What's the SOM annotation doing under the hood?"* | Pillow draws red `ImageDraw.rectangle` boxes on tile JPEG crops and renders number tags above each box. It's pure CPU image manipulation — no ML. The LLM uses the numbers as a shared reference frame with the structured marker list. |
| *"Is this production-ready?"* | The architecture is production-ready (GCS/Firestore backend, Cloud Run deploy config exists). The CV pipeline is pilot-grade — it works well for clean schematics, degrades on hand-drawn or low-contrast diagrams. |
| *"How do you test the agent itself?"* | ADK provides `_agent_cls` and `_runner_cls` DI parameters. Tests inject mock classes that return scripted tool response sequences. No Gemini API calls in tests. |
| *"Can we run it on-premises?"* | The core logic is pure Python. Replace `VertexAILlmAgent` with any ADK-compatible LLM backend. Document AI can be swapped for Tesseract/PaddleOCR. |

---

## Sample Queries

Use these tested queries for a reliable demo regardless of the diagram type.

### Safe "always works" queries

```
Give me a high-level overview of this diagram.
```
```
How many components were detected? Break them down by type.
```
```
What does the title block say about this drawing?
```
```
Describe what you see in the centre of the diagram.
```

### Intermediate queries (good for most electrical schematics)

```
Find all ground symbols and tell me where they are.
```
```
What components are in the top-right quadrant?
```
```
Are there any IC chips? List them with their reference designators.
```
```
What is the overall signal flow in this schematic?
```

### Advanced queries (best with rich CV/OCR extraction)

```
Find resistor R47 and trace what it connects to on both pins.
```
```
Which components have confidence scores below 70%?
```
```
List all power supply components and their voltage ratings.
```
```
Are there any unconnected nets in this diagram?
```

---

## Troubleshooting During the Demo

| Symptom | Fix |
|---|---|
| Server not running | `python -m src.agent.server` from project root |
| "Module not found" error | Run from project root with venv: `source venv/bin/activate` |
| Preprocess phase hangs > 30s | Document AI cold-start; retry. Or pre-ingest before demo. |
| Agent returns "I cannot see any components" | OCR/CV found nothing; diagram may be low contrast. Demo the visual fallback: ask it to describe what it *sees* in a specific zone. |
| `diagram_id` not found error | Session was reset; re-upload the diagram to get a new UUID. |
| Gemini 429 error | Rate limit hit; wait 10s (retry logic will handle it automatically up to 3×). |
| Visualization page blank | Check browser console; `diagram_id` in URL may be wrong. |
| Tool call timeline not appearing | Backend returned no `tool_calls`; check server logs for agent errors. |

---

*Guide last updated: 2026-03-15*
