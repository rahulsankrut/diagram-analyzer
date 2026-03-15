# CAD Diagram Analyzer

An agentic application that ingests complex CAD diagrams (electrical schematics, P&IDs, mechanical drawings) and makes them comprehensible to a multimodal LLM through a multi-resolution tiling and tool-augmented reasoning pipeline.

Built on **Google Vertex AI** (Gemini 2.5 Flash), **Google Agent Development Kit (ADK)**, **Document AI** for OCR, and **OpenCV** for computer vision — the system separates *perception* (deterministic CV/OCR) from *reasoning* (LLM), so the LLM reasons over structured data and uses vision only to verify.

## Key Features

- **Multi-resolution tiling** — 3-level pyramid (1×1, 2×2, 4×4) with 20% overlap so no component is split at tile boundaries
- **Set-of-Marks (SOM) visual grounding** — tile images are annotated with numbered markers ([1], [2], …) so the agent can reference elements by marker ID
- **5 agent tools** — `get_overview`, `inspect_zone`, `inspect_component`, `search_text`, `trace_net`
- **Interactive HTML visualization** — self-contained HTML with SVG bounding-box overlays, hover-to-highlight, and searchable sidebar
- **Dual-model support** — use Gemini Flash for orchestration and Gemini Pro for vision-heavy tool calls
- **Retry with exponential backoff** — handles transient Vertex AI errors (429, 503) gracefully
- **Token-aware context management** — JPEG encoding, tile caps, and match limits keep context under Gemini's 1M token budget

## Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌───────────────┐    ┌──────────────┐
│   Ingest    │───▶│  Pre-processing  │───▶│    Tiling      │───▶│   Agent +    │
│  (upload)   │    │  OCR + CV + TB   │    │  3-level       │    │   Tools      │
│             │    │                  │    │  pyramid       │    │              │
└─────────────┘    └──────────────────┘    └───────────────┘    └──────────────┘
      │                    │                       │                    │
      ▼                    ▼                       ▼                    ▼
  PIL Image         DiagramMetadata          TilePyramid         Agent Response
                  (components, labels,      (21 tiles with       + Interactive
                   traces, title block)      SOM annotations)     Visualization
```

## Quick Start

### Prerequisites

- Python 3.11+
- Google Cloud project with:
  - Vertex AI API enabled
  - Document AI processor (OCR type)
  - Application Default Credentials configured

### Setup

```bash
# Clone and install
git clone https://github.com/rahulsankrut/diagram-analyzer.git
cd diagram-analyzer
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your GCP project details (see Configuration below)

# Authenticate with GCP
gcloud auth application-default login

# Start the server
python -m src.agent.server
```

The server starts at `http://localhost:8080` with a built-in web UI.

### Configuration

Create a `.env` file in the project root:

```env
GCP_PROJECT_ID=your-project-id
GCP_REGION=us-central1
GCS_BUCKET=your-bucket-name
FIRESTORE_DB=your-firestore-db
DOCUMENT_AI_PROCESSOR_ID=your-processor-id
DOCUMENT_AI_LOCATION=us
VERTEX_AI_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash

# Optional: use a stronger model for vision-heavy tool calls
# TOOL_MODEL=gemini-2.5-pro

# These are set automatically by the server but can be overridden
GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
```

## Usage

### Web UI

Open `http://localhost:8080` in your browser:

1. Drag and drop (or browse for) a CAD diagram image (PNG, JPEG, TIFF)
2. Type a question (e.g., "What components are present?", "Trace the power supply connections")
3. Click **Analyze Diagram**
4. View the agent's analysis and click **Open Interactive Visualization** to explore the detected elements

### REST API

**Ingest a diagram:**
```bash
curl -X POST http://localhost:8080/ingest \
  -F "file=@schematic.png"
```

**Analyze an ingested diagram:**
```bash
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "diagram_id": "<id-from-ingest>",
    "query": "What components are present in this diagram?"
  }'
```

**View interactive visualization:**
```
GET http://localhost:8080/visualization/{diagram_id}
```

**Interactive API docs (Swagger UI):**
```
http://localhost:8080/docs
```

## Project Structure

```
cad-diagram-analyzer/
├── CLAUDE.md                    # AI assistant instructions
├── pyproject.toml               # Dependencies and tool config
├── src/
│   ├── agent/
│   │   ├── cad_agent.py         # ADK LlmAgent with retry logic
│   │   ├── prompts.py           # System prompts (SOM + spatial reasoning)
│   │   ├── callbacks.py         # ADK tool callbacks
│   │   └── server.py            # FastAPI server (ingest, analyze, visualization)
│   ├── models/
│   │   ├── ocr.py               # BoundingBox, OCRElement, OCRResult
│   │   ├── diagram.py           # DiagramMetadata (central data model)
│   │   ├── component.py         # Component (detected symbols)
│   │   ├── text_label.py        # TextLabel (OCR text)
│   │   ├── trace.py             # Trace (electrical/fluid connections)
│   │   ├── cv.py                # Symbol, CVResult (CV pipeline output)
│   │   └── tiling.py            # Tile, TilePyramid, TilingConfig
│   ├── tools/
│   │   ├── get_overview.py      # High-level diagram summary
│   │   ├── inspect_zone.py      # Zoom into region with SOM-annotated tiles
│   │   ├── inspect_component.py # Deep-dive on a single component
│   │   ├── search_text.py       # Search OCR text labels
│   │   ├── trace_net.py         # Follow electrical connections
│   │   ├── export_visualization.py  # Interactive HTML generation
│   │   ├── _image_utils.py      # SOM annotation, base64, crop helpers
│   │   └── _store.py            # DiagramStore ABC + singleton
│   ├── preprocessing/
│   │   ├── pipeline.py          # Orchestrates OCR + CV + title block
│   │   ├── ocr.py               # Document AI OCR extractor
│   │   ├── cv_pipeline.py       # OpenCV symbol/line detection
│   │   ├── docai_client.py      # Document AI client wrapper
│   │   └── title_block.py       # Title block extraction
│   ├── tiling/
│   │   ├── tile_generator.py    # Multi-resolution tile pyramid creation
│   │   └── tile_storage.py      # Local filesystem tile storage
│   ├── orchestrator.py          # Top-level ingest → preprocess → tile pipeline
│   └── static/
│       └── index.html           # Web UI frontend
├── tests/
│   ├── fixtures/                # Sample CAD images
│   ├── test_models/             # Data model tests
│   ├── test_tiling/             # Tiling engine tests
│   ├── test_tools/              # Tool function tests
│   └── test_preprocessing/      # Pipeline tests
├── docs/
│   ├── architecture.md          # System architecture
│   ├── tool-specs.md            # Tool API specifications
│   ├── data-models.md           # Pydantic model reference
│   ├── testing.md               # Testing guide
│   └── implementation-plan.md   # Phased build plan
└── scripts/                     # Dev utilities
```

## Agent Tools

The LLM agent has access to 5 tools for analyzing diagrams:

| Tool | Purpose | Key Limits |
|------|---------|------------|
| `get_overview` | Diagram dimensions, component/label counts, title block | Always called first |
| `inspect_zone` | Zoom into a region (0–100% coords) with SOM-annotated tile images | Max 3 tiles, 512px, 50 labels |
| `inspect_component` | Deep-dive crop + nearby components for a single component | 5% padding crop |
| `search_text` | Case-insensitive partial match on OCR text labels | Max 100 matches |
| `trace_net` | Follow electrical/fluid connections from a component pin | Graceful fallback when no data |

## Development

```bash
# Run all tests (uses mocks — no GCP credentials needed)
pytest

# Type checking
mypy src/

# Lint and format
ruff check src/
ruff format src/

# Run specific test suites
pytest tests/test_models/ -v
pytest tests/test_tools/ -v
pytest tests/test_tiling/ -v
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| LLM | Google Gemini 2.5 Flash (via Vertex AI) |
| Agent Framework | Google Agent Development Kit (ADK) |
| OCR | Google Cloud Document AI |
| Computer Vision | OpenCV (headless) |
| Image Processing | Pillow |
| Data Models | Pydantic v2 |
| Web Server | FastAPI + Uvicorn |
| Deployment | Google Cloud Run |

## License

This project is proprietary. See LICENSE file for details.
