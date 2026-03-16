# CAD Diagram Analyzer

> **AI-powered analysis of electrical schematics, P&IDs, and mechanical drawings** — powered by Google Gemini 2.5, Google Agent Development Kit (ADK), Document AI OCR, and OpenCV.

---

## The Problem

Complex CAD diagrams — D-size electrical schematics at 300 DPI can reach **7000×5000 pixels**, densely packed with fine-text labels, thin connector traces, and hundreds of symbols. When you feed such an image directly to a multimodal LLM:

1. **Spatial resolution loss** — Gemini internally downsamples all images to ~1024×1024 px. A 7000×5000 image loses 98% of its pixels. Fine text and thin traces disappear completely.
2. **Hallucination** — LLMs tend to invent component labels and connections they can't clearly see, especially when the image quality degrades under downsampling.
3. **No structured output** — You get a narrative description but no machine-readable list of components, netlist, or searchable data.

## The Solution: Perception + Reasoning Separation

The core architectural insight is to **separate what the LLM does from what deterministic algorithms do better**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PERCEPTION LAYER (deterministic, no LLM)                  │
│                                                                               │
│   Document AI OCR   →   symbol detection   →   multi-resolution tiling       │
│   (text labels,          (OpenCV contour         (21 tiles with               │
│    bounding boxes)        classification)          SOM annotations)           │
└─────────────────────────────────────────────────────────────────────────────┘
                               │  structured data
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      REASONING LAYER (Gemini + ADK)                          │
│                                                                               │
│   LlmAgent reasons over structured data,  calls tools to zoom into regions,  │
│   references elements by SOM marker numbers, answers natural-language queries │
└─────────────────────────────────────────────────────────────────────────────┘
```

**The LLM reasons — it does not perceive.** All pixel-level extraction happens deterministically before the LLM is involved. The LLM receives structured `DiagramMetadata` (Pydantic models) via tool return values, then uses vision only to *verify* what it already knows from structured data.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Google Cloud project with Vertex AI + Document AI enabled
- Application Default Credentials (`gcloud auth application-default login`)

### Setup

```bash
git clone <repo-url>
cd cad-diagram-analyzer
python3 -m venv venv && source venv/bin/activate
pip install -e .

# Configure GCP credentials
cp .env.example .env   # edit with your project details

# Authenticate
gcloud auth application-default login

# Start the server
python3 -m src.agent.server
# → http://localhost:8080
```

### Configuration (`.env`)

```env
GCP_PROJECT_ID=your-project-id
DOCUMENT_AI_PROCESSOR_ID=your-ocr-processor-id
DOCUMENT_AI_LOCATION=us
VERTEX_AI_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash        # default model
# TOOL_MODEL=gemini-2.5-pro          # optional: stronger model for vision tools
GOOGLE_GENAI_USE_VERTEXAI=1
```

> **Offline / No credentials?** The server falls back to no-op OCR/CV stubs. The agent still works via visual analysis but without structured data from OCR.

---

## Architecture Overview

```
User Upload (PNG / JPEG / TIFF)
         │
         ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │ Phase 1: Ingest                                                    │
  │   Orchestrator.ingest() → decode to PIL Image, assign UUID        │
  └────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │ Phase 2: Preprocess  (parallel OCR + CV)                          │
  │   DocumentAIOCRExtractor  → list[TextLabel]                       │
  │   CVPipeline (OpenCV)     → list[Component] + list[Trace]         │
  │   TitleBlockExtractor     → TitleBlock | None                     │
  │   → DiagramMetadata (Pydantic v2)                                 │
  └────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │ Phase 3: Tiling                                                    │
  │   TileGenerator.generate() → TilePyramid (21 tiles: L0, L1, L2)  │
  │   LocalStorage → /tmp/cad-diagram-analyzer/tiles/                 │
  └────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │ Phase 4: Agent Analysis  (ADK + Gemini 2.5 Flash)                 │
  │   CADAnalysisAgent → LlmAgent + InMemoryRunner                    │
  │   Tools: get_overview, inspect_zone, inspect_component,           │
  │           search_text, trace_net                                   │
  │   Callbacks: before_tool, after_tool (ToolCallTracker)            │
  │   → {"text": response, "tool_calls": [{name, args, duration}…]}   │
  └──────────────────────────────────────────────────────────────────┘
```

### Why Multi-Resolution Tiling?

The fundamental constraint: Gemini processes images at ~1024×1024 px internally. A 4×4 tile grid means each tile covers ~25% of the diagram at full source resolution, effectively giving the agent **4× better spatial resolution** when zooming into a specific region.

| Level | Grid | Tiles | Detail vs. overview |
|-------|------|-------|---------------------|
| L0 | 1×1  | 1     | Full diagram (orientation) |
| L1 | 2×2  | 4     | Quadrant-level detail |
| L2 | 4×4  | 16    | Component-level detail |

Tiles at each level overlap by **20%** to ensure no component is split at a boundary.

### Why Set-of-Marks (SOM)?

Inspired by the [Set-of-Marks visual grounding technique](https://arxiv.org/abs/2310.11441): tile images are annotated with **numbered red bounding boxes** before being sent to the LLM. The agent can then say *"Marker [3] is a 10kΩ resistor labeled R47"* rather than trying to describe pixel coordinates — a far more reliable reference mechanism.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/ingest` | Upload image → pipeline → `diagram_id` |
| `POST` | `/analyze` | Run ADK agent on pre-ingested diagram |
| `GET`  | `/visualization/{id}` | Self-contained interactive HTML |
| `GET`  | `/docs` | Swagger UI |
| `GET`  | `/` | Web UI |

### POST /analyze — Response

```json
{
  "diagram_id": "550e8400-...",
  "query": "What components are present?",
  "response": "The diagram contains 42 components including...",
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

The `tool_calls` array lets you see exactly which tools the agent called, with timing and summaries — useful for debugging and demonstrating agent reasoning.

---

## Agent Tools

| Tool | Purpose | Call pattern |
|------|---------|--------------|
| `get_overview` | High-level counts, title block | Always first |
| `inspect_zone` | Zoom into region (SOM tiles) | Spatial investigation |
| `inspect_component` | Single component deep-dive | Detailed component info |
| `search_text` | OCR text search | Find by label/value |
| `trace_net` | Follow connections from a pin | Netlist tracing |

---

## Development

```bash
# Run all tests (no GCP credentials needed — all mocked)
pytest

# Single suite
pytest tests/test_agent/ -v
pytest tests/test_tools/ -v

# Type checking, lint, format
mypy src/
ruff check src/
ruff format src/
```

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| LLM + Reasoning | Gemini 2.5 Flash via Vertex AI | 1M token context, multimodal, function calling |
| Agent Framework | Google ADK (`LlmAgent`, `InMemoryRunner`) | Tool calling, session management, callbacks |
| OCR | Google Cloud Document AI | Production-quality text extraction with bbox |
| Computer Vision | OpenCV (headless) | Symbol detection, line tracing, junction finding |
| Image Processing | Pillow | Tile crop/resize, JPEG encoding, SOM annotation |
| Data Models | Pydantic v2 | Validated data, JSON serialization, field coercion |
| Web Server | FastAPI + Uvicorn | Async I/O, auto-docs, multipart file upload |
| Deployment (prod) | Google Cloud Run | Serverless, scales to zero |

---

## Project Structure

```
cad-diagram-analyzer/
├── src/
│   ├── agent/
│   │   ├── cad_agent.py          # CADAnalysisAgent (LlmAgent wrapper + retry)
│   │   ├── callbacks.py          # before_tool/after_tool + ToolCallTracker
│   │   ├── prompts.py            # AGENT_INSTRUCTION, GLOBAL_INSTRUCTION
│   │   └── server.py             # FastAPI app (ingest, analyze, visualization)
│   ├── models/                   # 14 Pydantic v2 models across 8 modules
│   ├── tools/
│   │   ├── get_overview.py
│   │   ├── inspect_zone.py       # SOM annotation + tile selection
│   │   ├── inspect_component.py
│   │   ├── search_text.py
│   │   ├── trace_net.py
│   │   ├── export_visualization.py   # Two-panel HTML with Mermaid.js
│   │   ├── _image_utils.py       # SOM drawing, base64, downscale helpers
│   │   └── _store.py             # DiagramStore ABC + configure_store() DI
│   ├── preprocessing/
│   │   ├── pipeline.py           # Concurrent OCR + CV + title block extraction
│   │   ├── ocr.py                # DocumentAIOCRExtractor
│   │   ├── cv_pipeline.py        # OpenCV symbol/line detection
│   │   └── title_block.py        # Title block region parsing
│   ├── tiling/
│   │   ├── tile_generator.py     # 3-level pyramid with 20% overlap
│   │   └── tile_storage.py       # LocalStorage (dev) / GCS (prod)
│   └── orchestrator.py           # Ingest → preprocess → tile pipeline
├── frontend/
│   ├── index.html                # 4-phase pipeline UI
│   ├── css/styles.css
│   └── js/app.js
├── tests/
│   ├── test_agent/               # ADK agent + callback tests (all mocked)
│   ├── test_tools/               # Tool function tests
│   ├── test_tiling/              # TileGenerator + TilePyramid tests
│   ├── test_models/              # Pydantic model validation tests
│   └── test_preprocessing/       # Pipeline integration tests
└── docs/
    ├── architecture.md           # Deep-dive system design
    ├── tool-specs.md             # Tool API reference
    ├── data-models.md            # Pydantic model reference
    └── testing.md                # Testing guide
```

---

## License

Proprietary. See `LICENSE` for details.
