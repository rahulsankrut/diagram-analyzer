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

Supported formats: `*.png`, `*.tiff`, `*.pdf`

| File | Description | Source |
|------|-------------|--------|
| _(none yet)_ | | |

## Generating the synthetic fixture manually

```bash
python scripts/create_test_fixtures.py
```

This writes `tests/fixtures/sample_electrical.png` — a 800×600 synthetic
schematic suitable for smoke-testing the preprocessing pipeline.
