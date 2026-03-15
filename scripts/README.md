# Scripts

One-off utilities and local development helpers.

| Script | Purpose |
|--------|---------|
| `create_test_fixtures.py` | Generate synthetic test images in `tests/fixtures/` |
| `local_dev.sh` | Start the FastAPI dev server with `.env` loaded (Phase 5) |
| `deploy.sh` | Deploy to Cloud Run via `gcloud run deploy` (Phase 5) |
| `seed_fixtures.sh` | Upload test fixtures to the GCS bucket (Phase 5) |

## Usage

```bash
# Generate synthetic test fixtures
python scripts/create_test_fixtures.py

# Start local dev server (requires Phase 5 implementation)
bash scripts/local_dev.sh
```
