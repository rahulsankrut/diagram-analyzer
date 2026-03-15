# Data Models Reference

All data models are Pydantic v2 `BaseModel` subclasses defined in `src/models/`.
Every model exposes a `.to_dict()` method that returns a JSON-serializable dict
(delegates to `model.model_dump(mode="json")`).

## Model Hierarchy

```
BoundingBox  ◄────────── shared by all spatial models
    │
    ├── OCRElement / OCRResult       (raw Document AI output)
    ├── TextLabel                    (semantic OCR label)
    ├── Pin / Component              (classified CAD component)
    ├── Trace                        (semantic connection)
    ├── Symbol / DetectedLine / CVResult  (raw CV output)
    ├── TitleBlock                   (drawing metadata)
    ├── Tile / TileLevel / TilePyramid   (tiling)
    └── DiagramMetadata              (aggregates everything)
```

---

## Module Index

| Module | Models | Purpose |
|--------|--------|---------|
| `src.models.ocr` | `BoundingBox`, `OCRElement`, `OCRResult` | Core geometry + raw OCR output |
| `src.models.text_label` | `TextLabel` | Semantic OCR label (deduplicated, filtered) |
| `src.models.component` | `Pin`, `Component` | Classified CAD component with pins |
| `src.models.trace` | `Trace` | Semantic connection between component pins |
| `src.models.cv` | `Symbol`, `DetectedLine`, `CVResult` | Raw OpenCV detection output |
| `src.models.title_block` | `TitleBlock` | Structured drawing title block metadata |
| `src.models.tiling` | `TileLevel`, `Tile`, `TilePyramid`, `TilingManifest` | Multi-resolution tile pyramid |
| `src.models.diagram` | `DiagramMetadata`, `IngestionRequest`, `IngestionResult` | Top-level diagram + ingestion |
| `src.models.analysis` | `BOMEntry`, `NetlistEntry`, `AnalysisResult` | Agent output structures |

---

## Core Models

### `BoundingBox` — `src.models.ocr`

Axis-aligned bounding box with normalized (0.0–1.0) coordinates. The fundamental
spatial primitive shared by all other models.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `x_min` | `float` | [0.0, 1.0] | Normalized left edge |
| `y_min` | `float` | [0.0, 1.0] | Normalized top edge |
| `x_max` | `float` | [0.0, 1.0] | Normalized right edge (must be > x_min) |
| `y_max` | `float` | [0.0, 1.0] | Normalized bottom edge (must be > y_min) |

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `from_pixel_coords(x_min, y_min, x_max, y_max, width, height)` | `BoundingBox` | Class method: create from pixel values |
| `to_pixel_coords(width, height)` | `(int, int, int, int)` | Convert to pixel coordinates |
| `to_dict()` | `dict` | JSON-serializable dict |
| `center()` | `(float, float)` | Centroid `(cx, cy)` |
| `area()` | `float` | Normalized area |
| `overlaps(other)` | `bool` | True if interiors intersect |
| `iou(other)` | `float` | Intersection over Union [0.0, 1.0] |

---

### `TextLabel` — `src.models.text_label`

Semantic OCR text label — deduplicated, confidence-filtered, and associated with
diagram coordinate space.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `label_id` | `str` | Auto UUID | Unique identifier |
| `text` | `str` | *required* | Extracted text content (whitespace-normalized) |
| `bbox` | `BoundingBox` | *required* | Normalized bounding box |
| `confidence` | `float` | *required* | OCR confidence [0.0, 1.0] |
| `page` | `int` | `0` | Zero-indexed page number |

---

### `Pin` — `src.models.component`

A connection terminal on a CAD component.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pin_id` | `str` | Auto UUID | Unique identifier |
| `name` | `str` | `""` | Human-readable label (e.g. `"VCC"`, `"1"`, `"IN+"`) |
| `position` | `(float, float)` | *required* | Normalized (x, y) in full diagram space |

**Validation:** `position` must be within [0.0, 1.0] on both axes.

---

### `Component` — `src.models.component`

A detected and classified CAD component. Richer than a raw CV `Symbol`: carries
schematic value, package, and identified pins.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `component_id` | `str` | Auto UUID | Unique identifier |
| `component_type` | `str` | `"unknown"` | Semantic type (e.g. `"resistor"`, `"valve"`, `"ic"`) |
| `value` | `str` | `""` | Schematic value (e.g. `"100Ω"`, `"10µF"`) |
| `package` | `str` | `""` | Physical package (e.g. `"0603"`, `"DIP-8"`) |
| `bbox` | `BoundingBox` | *required* | Normalized bounding box |
| `pins` | `list[Pin]` | `[]` | Identified connection pins |
| `confidence` | `float` | `1.0` | Detection confidence [0.0, 1.0] |

---

### `Trace` — `src.models.trace`

A semantic electrical or fluid connection between two component pins.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `trace_id` | `str` | Auto UUID | Unique identifier |
| `from_component` | `str` | *required* | Source component ID |
| `from_pin` | `str` | *required* | Source pin name/ID |
| `to_component` | `str` | *required* | Destination component ID |
| `to_pin` | `str` | *required* | Destination pin name/ID |
| `path` | `list[(float, float)]` | `[]` | Normalized waypoints along the route |

---

### `TitleBlock` — `src.models.title_block`

Structured metadata extracted from the drawing title block. All string fields
default to `""` because different standards (IEC, ANSI, ISO) include different
fields.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `drawing_id` | `str` | `""` | Drawing number (e.g. `"DWG-001-A"`) |
| `title` | `str` | `""` | Descriptive drawing title |
| `sheet_number` | `str` | `"1"` | Current sheet (e.g. `"1"`, `"1 of 3"`) |
| `sheet_total` | `str` | `"1"` | Total sheet count |
| `revision` | `str` | `""` | Revision letter/number |
| `date` | `str` | `""` | Date string (format as-is from drawing) |
| `author` | `str` | `""` | Drafter / originating engineer |
| `scale` | `str` | `""` | Drawing scale (e.g. `"1:100"`, `"NTS"`) |
| `zone_grid` | `dict[str, str]` | `{}` | Zone code → description mapping |
| `bbox` | `BoundingBox \| None` | `None` | Title block region location |

---

## CV Models (Raw Detection Output)

### `Symbol` — `src.models.cv`

A raw closed-contour detection from the OpenCV pipeline. Mapped to `Component`
objects in `PreprocessingPipeline`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `symbol_id` | `str` | Auto UUID | Detection instance ID |
| `symbol_type` | `str` | `"unknown"` | Best-guess type |
| `bbox` | `BoundingBox` | *required* | Normalized bounding box |
| `confidence` | `float` | `1.0` | Detection confidence [0.0, 1.0] |
| `connections` | `list[str]` | `[]` | IDs of connected symbols |

### `DetectedLine` — `src.models.cv`

A raw line segment from Hough-transform detection. No component association —
that's resolved into `Trace` objects.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `line_id` | `str` | Auto UUID | Detection instance ID |
| `start_point` | `(float, float)` | *required* | Normalized start coordinate |
| `end_point` | `(float, float)` | *required* | Normalized end coordinate |
| `waypoints` | `list[(float, float)]` | `[]` | Intermediate coordinates |
| `thickness` | `float` | `1.0` | Estimated line thickness (pixels) |

### `CVResult` — `src.models.cv`

Aggregated raw CV output for one diagram.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `symbols` | `list[Symbol]` | `[]` | All detected closed-contour symbols |
| `detected_lines` | `list[DetectedLine]` | `[]` | All detected line segments |
| `junctions` | `list[BoundingBox]` | `[]` | Detected T/X trace junctions |

---

## Tiling Models

### `TileLevel` — `src.models.tiling`

Configuration for one zoom level.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `level` | `int` | [0, 2] | Zoom level (0=overview, 1=2×2, 2=4×4) |
| `grid_cols` | `int` | ≥ 1 | Columns at this level |
| `grid_rows` | `int` | ≥ 1 | Rows at this level |
| `overlap_fraction` | `float` | ≥ 0.20 | Overlap between adjacent tiles |

### `Tile` — `src.models.tiling`

One image tile in the pyramid.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tile_id` | `str` | *required* | Pattern: `{diagram_id}_L{level}_R{row}_C{col}` |
| `level` | `int` | *required* | Zoom level [0, 2] |
| `row` | `int` | *required* | Row position (0-indexed) |
| `col` | `int` | *required* | Column position (0-indexed) |
| `bbox` | `BoundingBox` | *required* | Normalized region covered by this tile |
| `image_path` | `str` | `""` | Local path or GCS URI of tile image |
| `component_ids` | `list[str]` | `[]` | Components whose centroid is in this tile |
| `text_label_ids` | `list[str]` | `[]` | Text labels overlapping this tile |

### `TilePyramid` — `src.models.tiling`

Multi-resolution tile pyramid for one diagram (1 + 4 + 16 = 21 tiles).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `diagram_id` | `str` | *required* | Parent diagram ID |
| `tiles` | `list[Tile]` | `[]` | All tiles across all levels |

**Query methods:** `tiles_at_level(level)`, `tile_at(level, row, col)`, `available_levels()`

---

## Top-Level Models

### `DiagramMetadata` — `src.models.diagram`

The central data model — aggregates all extracted artefacts for one diagram.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `diagram_id` | `str` | Auto UUID | Unique diagram identifier |
| `source_filename` | `str` | *required* | Original filename |
| `format` | `Literal[...]` | *required* | `"png"`, `"tiff"`, `"pdf"`, `"dwg"`, `"dxf"` |
| `width_px` | `int` | *required* | Rasterized image width (pixels) |
| `height_px` | `int` | *required* | Rasterized image height (pixels) |
| `dpi` | `int` | `300` | Image resolution |
| `gcs_original_uri` | `str` | `""` | GCS URI of original file |
| `gcs_raster_uri` | `str` | `""` | GCS URI of rasterized PNG |
| `firestore_doc_id` | `str` | `""` | Firestore document ID |
| `created_at` | `datetime` | Auto UTC now | Record creation timestamp |
| `components` | `list[Component]` | `[]` | Detected components |
| `text_labels` | `list[TextLabel]` | `[]` | OCR text labels |
| `traces` | `list[Trace]` | `[]` | Semantic connections |
| `title_block` | `TitleBlock \| None` | `None` | Drawing metadata |

**Query methods:**
- `get_component(component_id)` → `Component | None`
- `components_in_bbox(bbox)` → `list[Component]`
- `text_labels_in_bbox(bbox)` → `list[TextLabel]`

---

## Coordinate Conventions

| Convention | Range | Used by |
|-----------|-------|---------|
| **Normalized** | 0.0–1.0 | `BoundingBox` in all models (OCR, CV, components, tiles) |
| **Pixel** | 0–width/height | `bbox_to_pixel_dict()` output, `to_pixel_coords()` |
| **Percentage** | 0–100 | `inspect_zone()` tool arguments only |

**Conversion helpers:**
- `BoundingBox.to_pixel_coords(width, height)` → `(x_min, y_min, x_max, y_max)` pixels
- `BoundingBox.from_pixel_coords(x_min, y_min, x_max, y_max, width, height)` → normalized
- `bbox_to_pixel_dict(bbox, width_px, height_px)` → `{"x", "y", "w", "h"}` pixels
- `inspect_zone` divides coordinates by 100 to convert percentage → normalized

## JSON Serialization

```python
# Serialize
json_str = model.model_dump_json()
json_dict = model.model_dump(mode="json")  # same as .to_dict()

# Deserialize
model = DiagramMetadata.model_validate(data_dict)
model = DiagramMetadata.model_validate_json(json_string)
```

All models use Pydantic v2. Fields with custom types (`datetime`, `tuple`) are
handled by `mode="json"` serialization automatically.
