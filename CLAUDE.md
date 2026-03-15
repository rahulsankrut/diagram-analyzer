# CAD Diagram Analyzer — Pilot

## What This Project Is
An agentic application that ingests complex CAD diagrams (electrical schematics,
P&IDs, etc.) and makes them comprehensible to a multimodal LLM through a
multi-resolution tiling + tool-augmented reasoning pipeline.

The system separates PERCEPTION (deterministic CV/OCR) from REASONING (LLM).
The LLM reasons over structured data and uses vision to verify, not as primary
perception.

## Tech Stack
- Language: Python 3.11+
- LLM: Google Gemini 2.5 Flash via Vertex AI (primary), configurable via `GEMINI_MODEL` env var
- Agent Framework: Google Agent Development Kit (ADK) — `LlmAgent`, `InMemoryRunner`
- Pre-processing: Google Cloud Document AI (OCR), OpenCV (CV pipeline)
- Image manipulation: Pillow, OpenCV
- Storage: InMemoryDiagramStore + LocalStorage (local dev); GCS + Firestore (production)
- Web server: FastAPI + Uvicorn
- Hosting: Cloud Run (planned)
- Package management: uv (preferred) or pip
- Testing: pytest with fixtures for sample diagrams

## Project Structure
```
cad-diagram-analyzer/
├── CLAUDE.md
├── pyproject.toml
├── src/
│   ├── agent/              # ADK agent, prompts, server, callbacks
│   │   ├── cad_agent.py    # CADAnalysisAgent with retry logic
│   │   ├── prompts.py      # System prompts (SOM + spatial reasoning)
│   │   ├── callbacks.py    # ADK tool callbacks
│   │   └── server.py       # FastAPI server (ingest, analyze, visualization)
│   ├── models/             # Pydantic v2 data models (14 models, 8 modules)
│   ├── tools/              # 5 agent tools + visualization + utilities
│   │   ├── get_overview.py
│   │   ├── inspect_zone.py       # SOM-annotated tile images
│   │   ├── inspect_component.py  # Component deep-dive crop
│   │   ├── search_text.py
│   │   ├── trace_net.py
│   │   ├── export_visualization.py  # Interactive HTML generation
│   │   ├── _image_utils.py       # SOM annotation, base64, crop helpers
│   │   └── _store.py             # DiagramStore ABC + singleton
│   ├── preprocessing/      # OCR, symbol detection, CV pipeline, title block
│   ├── tiling/             # Multi-resolution tile generation (3-level pyramid)
│   ├── orchestrator.py     # Top-level ingest → preprocess → tile pipeline
│   └── static/
│       └── index.html      # Web UI frontend
├── tests/
│   ├── fixtures/           # Sample CAD images for testing
│   ├── test_models/
│   ├── test_tiling/
│   ├── test_tools/
│   └── test_preprocessing/
├── docs/
│   ├── architecture.md     # System architecture
│   ├── tool-specs.md       # Tool API specifications
│   ├── data-models.md      # Pydantic model reference
│   ├── testing.md          # Testing guide
│   └── implementation-plan.md  # Phased build plan (all phases complete)
└── scripts/                # One-off utilities, local dev helpers
```

## Key Commands
- Run all tests: `pytest`
- Run single test: `pytest tests/test_tools/test_inspect_zone.py -v`
- Type check: `mypy src/`
- Lint: `ruff check src/`
- Format: `ruff format src/`
- Local dev server: `python -m src.agent.server`

## Agent Tools (5 tools)
| Tool | Purpose | Key Limits |
|------|---------|------------|
| `get_overview` | Diagram dimensions, counts, title block | No image (structured only) |
| `inspect_zone` | Zoom into region with SOM-annotated tiles | Max 3 tiles, 512px, 50 labels |
| `inspect_component` | Deep-dive crop + nearby components | 5% padding crop |
| `search_text` | Case-insensitive text label search | Max 100 matches |
| `trace_net` | Follow connections from component pin | Graceful fallback when no data |

## Server Endpoints
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest` | Upload image → pipeline → `diagram_id` |
| `POST` | `/analyze` | Run agent on pre-ingested diagram |
| `GET` | `/visualization/{id}` | Interactive HTML visualization |
| `GET` | `/docs` | Swagger UI (auto-generated) |
| `GET` | `/` | Web UI frontend |

## Coding Conventions
- Type hints on all function signatures
- Pydantic v2 models for all data structures (not raw dicts)
- Google-style docstrings with Args/Returns/Raises
- Async where I/O is involved (GCS, Vertex AI, Document AI calls)
- Keep functions under 40 lines; extract helpers
- All GCP service calls wrapped in thin adapter classes for testability
- Tools return `{"error": "..."}` instead of raising exceptions
- Tools return JSON-serializable dicts (never Pydantic models directly)

## Domain Context
- CAD diagrams are spatially dense: a D-size schematic at 300 DPI is ~7000x5000 px
- LLMs downsample to ~1024x1024 internally — fine text and thin traces are lost
- The core insight: separate PERCEPTION (deterministic CV/OCR) from REASONING (LLM)
- The LLM should reason over structured data and use vision to verify, not as primary perception
- Set-of-Marks (SOM) visual grounding: tile images annotated with numbered markers
  so the agent can reference elements by [1], [2], etc.

## Important Gotchas
- Tile overlaps must be ≥20% to avoid splitting components at boundaries
- OpenCV contour detection needs careful thresholding per diagram type
- Document AI OCR returns bbox in normalized vertices (0-1), convert to pixel coords
- Gemini function calling requires strict JSON schema for tool definitions
- ADK tool functions must return serializable outputs (str, int, float, list, dict)
- Token budget: Gemini 2.5 Flash has 1M token context limit. Controls in place:
  - Initial image: JPEG at 768px (not PNG at 1024px) saves ~100-300K tokens/turn
  - `inspect_zone`: max 3 tiles at 512px, 50 labels, JPEG encoding
  - `search_text`: max 100 matches
  - `get_overview`: returns structured data only (no image)
- Retry logic: transient Gemini errors (429, 503) retried up to 3× with exponential backoff
- CV symbols must be mapped to Component objects in pipeline.py (not left as raw Symbols)

## Environment Variables
```env
GCP_PROJECT_ID=...              # Google Cloud project ID
GCS_BUCKET=...                  # GCS bucket for diagrams
FIRESTORE_DB=...                # Firestore database name
DOCUMENT_AI_PROCESSOR_ID=...    # Document AI OCR processor ID
DOCUMENT_AI_LOCATION=us         # Document AI location
VERTEX_AI_LOCATION=us-central1  # Vertex AI location
GEMINI_MODEL=gemini-2.5-flash   # Agent model (default)
TOOL_MODEL=gemini-2.5-pro       # Optional: vision-heavy tool model
GOOGLE_GENAI_USE_VERTEXAI=1     # Route through Vertex AI (not API key)
```
