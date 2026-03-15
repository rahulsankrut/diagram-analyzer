# Data Models Reference

This document will be expanded during Phase 1 with auto-generated field
documentation for each Pydantic model.

## Models

| Module | Models |
|--------|--------|
| `src.models.ocr` | `BoundingBox`, `OCRElement`, `OCRResult` |
| `src.models.diagram` | `DiagramMetadata`, `IngestionRequest`, `IngestionResult` |
| `src.models.cv` | `Symbol`, `Trace`, `CVResult` |
| `src.models.tiling` | `TileLevel`, `Tile`, `TilingManifest` |
| `src.models.analysis` | `BOMEntry`, `NetlistEntry`, `AnalysisResult` |

## Coordinate conventions

- **Normalized coordinates** (0.0–1.0): used in `BoundingBox` when stored in
  OCR results, CV results, and BOM entries.
- **Pixel coordinates**: used in `Tile.bbox_px` — same `BoundingBox` type
  but the `_px` suffix signals pixel space.

## JSON serialization

All models are Pydantic v2 `BaseModel` subclasses. Use `model.model_dump_json()`
to serialize and `Model.model_validate(data)` to deserialize.
