# docs/architecture.md

## System Architecture Overview

### Phase 1: Ingestion
- Input: CAD files (DWG, DXF, PDF, PNG, TIFF)
- Normalize to high-res rasterized PNG + preserve vector data if available
- Store originals and rasters in GCS bucket

### Phase 2: Pre-Processing (No LLM)
- OCR via Document AI → text elements with bounding boxes
- OpenCV pipeline → line/trace detection, junction identification
- Symbol detection → component identification with bbox coordinates
- Title block extraction → drawing metadata
- Output: Structured JSON (components, text, traces, metadata)

### Phase 3: Multi-Resolution Tiling
- Level 0: Full diagram downscaled to ~1024px (overview)
- Level 1: 2x2 grid with 20% overlap
- Level 2: 4x4 grid with 20% overlap
- Each tile tagged with zone coords + component/text index

### Phase 4: Agentic Reasoning
- LLM receives structured JSON + Level 0 overview
- LLM calls tools to zoom, inspect, trace connections
- LLM reasons over structure, verifies visually when needed

### Phase 5: Output
- Structured extraction (BOM, netlist, component list)
- Natural language summaries
- Annotated images with findings