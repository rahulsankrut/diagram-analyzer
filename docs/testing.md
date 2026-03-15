# Testing the CAD Diagram Analyzer

## Prerequisites

- Python 3.11+
- Virtual environment created and activated
- Dependencies installed (`pip install -e .`)
- `.env` file populated (see below)
- Google Application Default Credentials configured

### Environment Configuration

Create a `.env` file in the project root:

```env
GCP_PROJECT_ID=vertex-ai-demos-468803
GCP_REGION=us-central1
GCS_BUCKET=cad-diagram-bucket
FIRESTORE_DB=cad-diagram-db
DOCUMENT_AI_PROCESSOR_ID=fc558a9dcb62447
DOCUMENT_AI_LOCATION=us
VERTEX_AI_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash

# Optional: use a stronger model for vision-heavy tool calls
# TOOL_MODEL=gemini-2.5-pro
```

### Verify ADC (Application Default Credentials)

```bash
gcloud auth application-default login
# Confirm it works:
python3 -c "import google.auth; c,p = google.auth.default(); print('Project:', p)"
```

---

## 1. Start the Server

```bash
cd /path/to/cad-diagram-analyzer
source venv/bin/activate
python -m src.agent.server
```

Expected output:
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8080
```

If Document AI credentials are not configured, you'll see:
```
WARNING:  Falling back to no-op OCR/CV stubs: ...
```
The server still works — the agent uses visual analysis instead of structured data.

---

## 2. Test via the Web UI (Frontend)

Open your browser and go to:

```
http://localhost:8080
```

**Steps:**
1. Drag and drop (or click to browse) a CAD diagram image — PNG, JPEG, or TIFF
2. Type a question in the query box, e.g.:
   - `What components are present in this diagram?`
   - `List all valves and their tag numbers`
   - `Describe the main signal flow`
3. Click **Analyze Diagram**
4. Watch the two-step progress: **Ingest → Analyzed**
5. The agent's response appears in the results panel
6. Click **Open Interactive Visualization →** to view the interactive HTML with
   SVG bounding-box overlays, hover-to-highlight, and searchable sidebar

---

## 3. Test via the API Directly

### Step 1 — Ingest an image

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

### Step 2 — Analyze the ingested diagram

```bash
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "diagram_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "What components are present in this diagram?"
  }'
```

Response:
```json
{
  "diagram_id": "550e8400-e29b-41d4-a716-446655440000",
  "query": "What components are present in this diagram?",
  "response": "The diagram contains the following components: ..."
}
```

### Step 3 — View the interactive visualization

Open in your browser:
```
http://localhost:8080/visualization/550e8400-e29b-41d4-a716-446655440000
```

This returns a self-contained HTML page with:
- Diagram image with SVG bounding-box overlays
- Hover-to-highlight and click-to-pin interaction
- Searchable sidebar listing all detected elements

### Interactive API docs (Swagger UI)

FastAPI auto-generates interactive docs at:

```
http://localhost:8080/docs
```

---

## 4. API Endpoints Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest` | Upload image → pipeline → `diagram_id` |
| `POST` | `/analyze` | Run agent on pre-ingested diagram |
| `GET` | `/visualization/{diagram_id}` | Interactive HTML visualization |
| `GET` | `/docs` | Swagger UI (auto-generated) |
| `GET` | `/` | Web UI frontend |

### Request / Response Models

**POST /ingest** — multipart file upload
- Request: `file` (UploadFile)
- Response: `IngestResponse { diagram_id, success, error_message }`

**POST /analyze** — JSON body
- Request: `AnalyzeRequest { diagram_id, query, user_id? }`
- Response: `AnalyzeResponse { diagram_id, query, response }`

---

## 5. Run the Unit Tests

```bash
cd /path/to/cad-diagram-analyzer
source venv/bin/activate

# Run all tests
pytest

# Run a specific module
pytest tests/test_models/ -v
pytest tests/test_tiling/ -v
pytest tests/test_tools/ -v

# Run with output
pytest -s -v
```

Tests use mocks — no real GCP credentials needed.

---

## 6. Code Quality

```bash
# Type checking
mypy src/

# Lint
ruff check src/

# Format
ruff format src/
```

---

## 7. Quick Smoke Test (No Browser)

```bash
python3 scripts/test_local.py
```

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `503 Agent not configured` | Vertex AI / ADK not reachable | Check ADC credentials and `VERTEX_AI_LOCATION` in `.env` |
| `404 Diagram not found` | `/analyze` called before `/ingest` | Always ingest first, use the returned `diagram_id` |
| `Ingestion failed: ...` | Pipeline error | Check server logs; image format may be unsupported |
| `ModuleNotFoundError` | Missing dependency | Run `pip install -e .` inside the venv |
| Port 8080 already in use | Another process on the port | `lsof -i :8080` then kill the process, or change port |
| `400 INVALID_ARGUMENT token count` | Diagram too large / too many components | The server caps tiles (3), labels (50), and matches (100); try a smaller region with `inspect_zone` |
| `429 RESOURCE_EXHAUSTED` | Gemini rate limit | The agent auto-retries with exponential backoff (2s → 4s → 8s); if persistent, check quota |
| `Falling back to no-op OCR/CV stubs` | Document AI not configured | Set `DOCUMENT_AI_PROCESSOR_ID` in `.env`; agent still works via visual analysis |

### Change the server port

```bash
python -c "from src.agent.server import run_server; run_server(port=9000)"
```

And update the `API` constant in `src/static/index.html`:
```js
const API = 'http://localhost:9000';
```

### Token Budget Issues

If you encounter token limit errors (HTTP 400 with "token count exceeds limit"),
the following controls are already in place:

| Control | Default | Environment Variable |
|---------|---------|---------------------|
| Initial image | JPEG 768px, quality=85 | — |
| Max tiles per `inspect_zone` | 3 | — |
| Max tile resolution | 512×512 px | — |
| Max text labels per zone | 50 | — |
| Max `search_text` matches | 100 | — |
| Agent model | `gemini-2.5-flash` | `GEMINI_MODEL` |
| Vision model | Same as agent | `TOOL_MODEL` |

If issues persist, try using the `TOOL_MODEL=gemini-2.5-pro` setting — Pro has
a larger context window for complex diagrams.
