# Test Fixtures

This directory holds sample CAD diagram images used as pytest fixtures.

## Synthetic fixtures (auto-generated)

The `conftest.py` at the `tests/` root dynamically generates lightweight
synthetic diagrams using Pillow at test-session start. These live in a
`tmp_path_factory` temp directory and are **not** committed to the repo.

## Adding real CAD samples

For integration/acceptance tests you can place real diagram files here.
They are excluded from git by the root `.gitignore` to avoid storing large
binaries in the repository.

Supported formats: `*.png`, `*.jpeg`, `*.tiff`, `*.pdf`

| File | Description | Source |
|------|-------------|--------|
| _(none committed)_ | Real CAD samples should be placed here manually | — |

> **Note:** Real test images (e.g. Boeing schematics) have been tested locally
> but are not committed to the repo due to size and licensing.

## Generating the synthetic fixture manually

```bash
python scripts/create_test_fixtures.py
```

This writes `tests/fixtures/sample_electrical.png` — a 800×600 synthetic
schematic suitable for smoke-testing the preprocessing pipeline.

## Using fixtures in tests

Tests in `tests/test_tools/` and `tests/test_tiling/` use mocked data stores
rather than loading real images. This keeps tests fast and independent of GCP
credentials.

For end-to-end testing with real images, use the web UI or API:
```bash
python -m src.agent.server
# Then upload an image at http://localhost:8080
```
