# CAD Diagram Analyzer — Pilot

## What This Project Is
An agentic application that ingests complex CAD diagrams (electrical schematics,
P&IDs, etc.) and makes them comprehensible to a multimodal LLM through a
multi-resolution tiling + tool-augmented reasoning pipeline.

## Tech Stack
- Language: Python 3.11+
- LLM: Google Gemini 2.5 Flash via Vertex AI (primary), configurable for others
- Agent Framework: Google Agent Development Kit (ADK)
- Pre-processing: Google Cloud Document AI (OCR), OpenCV (CV pipeline)
- Image manipulation: Pillow, OpenCV
- Storage: Google Cloud Storage (diagrams + tiles), Firestore (structured metadata)
- Hosting: Cloud Run
- Package management: uv (preferred) or pip
- Testing: pytest with fixtures for sample diagrams

## Project Structure
cad-diagram-analyzer/
├── CLAUDE.md
├── pyproject.toml
├── src/
│   ├── ingestion/        # Format normalization, upload handling
│   ├── preprocessing/    # OCR, symbol detection, CV pipeline
│   ├── tiling/           # Multi-resolution tile generation
│   ├── agent/            # ADK agent, tool definitions, orchestration
│   ├── tools/            # Individual tools the LLM can call
│   └── models/           # Pydantic data models
├── tests/
│   ├── fixtures/         # Sample CAD images for testing
│   ├── test_preprocessing/
│   ├── test_tiling/
│   └── test_agent/
├── docs/                 # Architecture decisions, API specs
│   ├── architecture.md
│   ├── tool-specs.md
│   └── data-models.md
└── scripts/              # One-off utilities, local dev helpers

## Key Commands
## Key Commands
- Run all tests: `pytest`
- Run single test: `pytest tests/test_preprocessing/test_ocr.py -v`
- Type check: `mypy src/`
- Lint: `ruff check src/`
- Format: `ruff format src/`
- Local dev server: `python -m src.agent.server`

## Coding Conventions
- Type hints on all function signatures
- Pydantic models for all data structures (not raw dicts)
- Google-style docstrings
- Async where I/O is involved (GCS, Vertex AI, Document AI calls)
- Keep functions under 40 lines; extract helpers
- All GCP service calls wrapped in thin adapter classes for testability

## Domain Context
- CAD diagrams are spatially dense: a D-size schematic at 300 DPI is ~7000x5000 px
- LLMs downsample to ~1024x1024 internally — fine text and thin traces are lost
- The core insight: separate PERCEPTION (deterministic CV/OCR) from REASONING (LLM)
- The LLM should reason over structured data and use vision to verify, not as primary perception

## Important Gotchas
- Tile overlaps must be ≥20% to avoid splitting components at boundaries
- OpenCV contour detection needs careful thresholding per diagram type
- Document AI OCR returns bbox in normalized vertices (0-1), convert to pixel coords
- Gemini function calling requires strict JSON schema for tool definitions
- ADK tool functions must return serializable outputs



