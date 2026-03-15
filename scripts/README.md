# Scripts

One-off utilities and local development helpers.

| Script | Purpose | Status |
|--------|---------|--------|
| `create_test_fixtures.py` | Generate synthetic test images in `tests/fixtures/` | Available |
| `local_dev.sh` | Start the FastAPI dev server with `.env` loaded | Available |
| `deploy.sh` | Deploy to Cloud Run via `gcloud run deploy` | Planned |
| `seed_fixtures.sh` | Upload test fixtures to the GCS bucket | Planned |
| `test_local.py` | Quick smoke test (ingest + analyze via API) | Available |

## Usage

```bash
# Generate synthetic test fixtures
python scripts/create_test_fixtures.py

# Start local dev server (preferred method)
python -m src.agent.server

# Alternative with script
bash scripts/local_dev.sh

# Quick smoke test (server must be running)
python3 scripts/test_local.py
```

## Server Startup

The recommended way to start the server is directly:

```bash
python -m src.agent.server
```

This starts the FastAPI server on `http://0.0.0.0:8080` with:
- Web UI at `/`
- API endpoints at `/ingest`, `/analyze`, `/visualization/{id}`
- Swagger docs at `/docs`
