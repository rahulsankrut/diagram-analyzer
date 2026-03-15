# Testing the CAD Diagram Analyzer

## Prerequisites

- Python 3.11+
- Virtual environment created and activated
- Dependencies installed (`pip install -e .`)
- `.env` file populated (see below)
- Google Application Default Credentials configured

### Verify your `.env`

```
GCP_PROJECT_ID=vertex-ai-demos-468803
GCP_REGION=us-central1
GCS_BUCKET=cad-diagram-bucket
FIRESTORE_DB=cad-diagram-db
DOCUMENT_AI_PROCESSOR_ID=fc558a9dcb62447
DOCUMENT_AI_LOCATION=us
VERTEX_AI_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash
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
cd /Users/rahulkasanagottu/Desktop/cad-diagram-analyzer
source venv/bin/activate
python -m src.agent.server
```

Expected output:
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8080
```

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

### Interactive API docs (Swagger UI)

FastAPI auto-generates interactive docs at:

```
http://localhost:8080/docs
```

---

## 4. Run the Unit Tests

```bash
cd /Users/rahulkasanagottu/Desktop/cad-diagram-analyzer
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

## 5. Quick Smoke Test (No Browser)

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

### Change the server port

```bash
python -c "from src.agent.server import run_server; run_server(port=9000)"
```

And update the `API` constant in `src/static/index.html`:
```js
const API = 'http://localhost:9000';
```
