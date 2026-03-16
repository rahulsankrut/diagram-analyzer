# Tool Specifications

This document describes the five agent tools available to the ADK `LlmAgent`. Each entry covers both the **API contract** (arguments, returns, error cases) and the **theory** behind key design choices.

All tools are synchronous Python functions that return JSON-serializable `dict` values. They are defined in `src/tools/` and registered in `src/agent/cad_agent.py`.

## Architecture: How Tools Connect to Data

```
LLM (Gemini) calls tool with JSON args (e.g. {"diagram_id": "abc", "query": "R47"})
         │
         ▼
Tool function (e.g. search_text.py)
         │
         ├── get_store()  ←  DiagramStore singleton (injected via configure_store())
         │        │
         │        ├── store.get_metadata(diagram_id)  →  DiagramMetadata
         │        ├── store.get_pyramid(diagram_id)    →  TilePyramid
         │        └── store.load_tile_image(tile_id)   →  PIL.Image
         │
         └── Returns dict[str, Any]  →  JSON-serialised → LLM sees as FunctionResponse
```

The `diagram_id` string is the only connection between the LLM's stateless world and the rich structured data held by the server. Tools use it as a key to look up everything from `DiagramMetadata` (component list, text labels, traces) to the tile pyramid images.

## Design Principles

- **JSON-only arguments** — all parameters are `str`, `int`, or `float`. This is a hard Gemini function-calling requirement: the LLM can only pass JSON primitive types as tool arguments. Complex types (PIL Images, Pydantic models) are retrieved by the tool via `get_store()` using the `diagram_id` key.
- **JSON-serializable returns** — every tool returns `dict[str, Any]`; no Pydantic models in return values. Pydantic's `.model_dump(mode="json")` (a.k.a. `.to_dict()`) is used where needed.
- **Error handling** — tools return `{"error": "..."}` instead of raising exceptions. The LLM sees the error as a FunctionResponse and can retry with corrected arguments or explain the problem to the user. Exceptions would crash the tool call and terminate the agent run.
- **Token-aware** — each tool caps its output. Large tool responses cost tokens (a 512 px JPEG tile ≈ 60K tokens). Caps are enforced in the tool code, not the LLM prompt. See limits per tool below.
- **Graceful fallback** — when data is absent or incomplete, tools return `data_unavailable: true` plus a human-readable message directing the agent to alternative tools. They never return empty responses without explanation.
- **Singleton store access** — tools call `get_store()` to access `DiagramMetadata`. Tests inject a mock store via `configure_store(mock)` before running tool tests (see `tests/test_tools/conftest.py`).

## Agent Workflow: Recommended Tool Call Sequence

The agent's system prompt encodes this recommended workflow:

```
1. get_overview(diagram_id)           → understand scope, counts, title block
2. inspect_zone(diagram_id, x1,y1,x2,y2)  → zoom into regions of interest, read SOM markers
3. inspect_component(diagram_id, component_id)  → deep-dive on specific components
4. search_text(diagram_id, query)     → look up labels / reference designators by text
5. trace_net(diagram_id, comp_id, pin)  → verify connections structurally
```

The agent is not required to call all tools — it selects based on the user's query. `get_overview` is always called first to orient itself.

---

## 1. `get_overview`

**File:** `src/tools/get_overview.py`

Returns a high-level summary of the diagram. **Always called first** by the
agent to orient itself.

### Signature

```python
def get_overview(diagram_id: str) -> dict[str, Any]
```

### Arguments

| Name | Type | Description |
|------|------|-------------|
| `diagram_id` | `str` | UUID of the diagram to inspect |

### Returns

```json
{
  "diagram_id": "550e8400-...",
  "width_px": 7000,
  "height_px": 5000,
  "component_count": 42,
  "component_types": {"resistor": 15, "capacitor": 8, "ic": 5, "unknown": 14},
  "text_label_count": 230,
  "trace_count": 0,
  "title_block": {
    "drawing_number": "SCH-2024-001",
    "revision": "B",
    "date": "2024-03-15",
    "author": "J. Smith"
  }
}
```

### Notes

- Does **not** return an image — the diagram image is already provided to the
  agent as an `inline_data` Part at the start of the conversation
- `component_types` is a `{type: count}` dict for quick orientation
- `title_block` is `null` when no title block was detected
- Returns `{"error": "Diagram not found: ..."}` for invalid `diagram_id`

---

## 2. `inspect_zone`

**File:** `src/tools/inspect_zone.py`

Zooms into a rectangular region of the diagram and returns SOM-annotated tile
images with component and text label markers.

### Signature

```python
def inspect_zone(
    diagram_id: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> dict[str, Any]
```

### Arguments

| Name | Type | Description |
|------|------|-------------|
| `diagram_id` | `str` | UUID of the diagram |
| `x1` | `float` | Left edge of query region (0–100, percentage of width) |
| `y1` | `float` | Top edge of query region (0–100, percentage of height) |
| `x2` | `float` | Right edge of query region (0–100) |
| `y2` | `float` | Bottom edge of query region (0–100) |

### Returns

```json
{
  "diagram_id": "550e8400-...",
  "query_region": {"x1": 0, "y1": 0, "x2": 50, "y2": 50},
  "tiles": [
    {
      "tile_id": "550e8400-..._L2_R0_C0",
      "level": 2,
      "row": 0,
      "col": 0,
      "bbox": {"x_min": 0.0, "y_min": 0.0, "x_max": 0.35, "y_max": 0.35},
      "image_base64": "<JPEG base64>"
    }
  ],
  "markers": [
    {"id": "1", "type": "resistor", "text": "", "bbox_px": {"x": 120, "y": 340, "w": 60, "h": 30}},
    {"id": "2", "type": "text_label", "text": "R47", "bbox_px": {"x": 125, "y": 315, "w": 40, "h": 15}}
  ],
  "component_count": 5,
  "text_label_count": 12
}
```

### SOM Annotation

Tile images are annotated with **Set-of-Marks** numbered markers:

- **Red bounding boxes** drawn around each detected component and text label
- **Numbered tags** `[1]`, `[2]`, `[3]`, … rendered above each bounding box
- The `markers` list maps each number to its type, text content, and pixel bbox
- The agent references elements by marker: *"Marker [3] shows resistor 'R47'"*

### Limits

| Limit | Value | Purpose |
|-------|-------|---------|
| Max tiles per call | 3 | Prevent context overflow |
| Max tile resolution | 512×512 px | Keep image tokens reasonable |
| Max text labels | 50 | Cap marker count |
| Image encoding | JPEG | ~3× smaller than PNG |

### Notes

- Coordinates are **percentage-based** (0–100), not normalized (0–1)
- If `x1 > x2` or `y1 > y2`, coordinates are auto-swapped
- When `text_labels_truncated: true`, the zone contains more than 50 labels
- Falls back to cropping the original image when no tile pyramid exists
- Selects the most detailed pyramid level (2 → 1 → 0) whose tiles cover the region

---

## 3. `inspect_component`

**File:** `src/tools/inspect_component.py`

Returns a detail crop and metadata for a single component, plus nearby
components for connectivity context.

### Signature

```python
def inspect_component(
    diagram_id: str,
    component_id: str,
) -> dict[str, Any]
```

### Arguments

| Name | Type | Description |
|------|------|-------------|
| `diagram_id` | `str` | UUID of the diagram |
| `component_id` | `str` | `component_id` of the component to inspect |

### Returns

```json
{
  "diagram_id": "550e8400-...",
  "component": {
    "component_id": "sym_001",
    "component_type": "resistor",
    "value": null,
    "package": null,
    "bbox": {"x_min": 0.15, "y_min": 0.30, "x_max": 0.20, "y_max": 0.35},
    "pins": [],
    "confidence": 0.85
  },
  "crop_image_base64": "<PNG base64>",
  "crop_bbox": {"x_min": 0.10, "y_min": 0.25, "x_max": 0.25, "y_max": 0.40},
  "nearby_components": [
    {"component_id": "sym_002", "component_type": "capacitor", ...}
  ]
}
```

### Notes

- Crop includes 5% padding on each side for context
- `nearby_components` includes components whose center is within 20% of the
  target (normalized Euclidean distance)
- Returns `{"error": "Component not found: ..."}` for invalid `component_id`

---

## 4. `search_text`

**File:** `src/tools/search_text.py`

Performs case-insensitive partial-match search over all OCR text labels.

### Signature

```python
def search_text(
    diagram_id: str,
    query: str,
) -> dict[str, Any]
```

### Arguments

| Name | Type | Description |
|------|------|-------------|
| `diagram_id` | `str` | UUID of the diagram |
| `query` | `str` | Substring to search for (case-insensitive) |

### Returns

```json
{
  "diagram_id": "550e8400-...",
  "query": "R47",
  "matches": [
    {
      "label_id": "lbl_042",
      "text": "R47 10kΩ",
      "bbox": {"x_min": 0.15, "y_min": 0.30, "x_max": 0.20, "y_max": 0.32},
      "confidence": 0.92,
      "tile_id": "..._L2_R1_C0",
      "tile_level": 2,
      "tile_row": 1,
      "tile_col": 0
    }
  ],
  "match_count": 1
}
```

### Limits

| Limit | Value | Purpose |
|-------|-------|---------|
| Max matches returned | 100 | Prevent context overflow on broad queries |

When `match_count > 100`, the response includes:
```json
{
  "matches_truncated": true,
  "matches_shown": 100
}
```

### Notes

- `match_count` always reflects the **total** matches found, even when truncated
- Each match is annotated with the most-detailed tile containing it
- `tile_id` / `tile_level` / `tile_row` / `tile_col` are `null` when no pyramid exists
- Returns `{"error": "query must be a non-empty string"}` for empty queries

---

## 5. `trace_net`

**File:** `src/tools/trace_net.py`

Follows electrical/fluid connections from a component pin using the CV-extracted
trace topology.

### Signature

```python
def trace_net(
    diagram_id: str,
    component_id: str,
    pin: str,
) -> dict[str, Any]
```

### Arguments

| Name | Type | Description |
|------|------|-------------|
| `diagram_id` | `str` | UUID of the diagram |
| `component_id` | `str` | Starting component ID |
| `pin` | `str` | Pin name/ID to trace from; `""` matches all pins |

### Returns

```json
{
  "diagram_id": "550e8400-...",
  "component_id": "sym_001",
  "pin": "",
  "trace_data_unavailable": false,
  "connections": [
    {
      "trace_id": "trace_001",
      "connected_component_id": "sym_002",
      "connected_component_type": "capacitor",
      "connected_pin": "pin_1",
      "direction": "from",
      "path": [[0.15, 0.30], [0.25, 0.30], [0.35, 0.45]]
    }
  ],
  "connection_count": 1
}
```

### Graceful Fallbacks

The tool handles missing data gracefully instead of returning errors:

| Condition | Response |
|-----------|----------|
| No components extracted | `trace_data_unavailable: true` + message directing agent to `inspect_zone()` |
| Component found but no traces | `trace_data_unavailable: true` + empty connections |
| Component not found | `{"error": "Component not found: ..."}` |

### Notes

- `direction` is `"from"` when the queried component is the trace source, `"to"` when destination
- `path` is a list of `[x, y]` normalized coordinate pairs
- Pin matching: pass `""` (empty string) to return all connections regardless of pin

---

## 6. `export_visualization` (Internal — not agent-callable)

**File:** `src/tools/export_visualization.py`

Generates a self-contained interactive HTML visualization. Not registered as an
agent tool — called by the server's `GET /visualization/{diagram_id}` endpoint.

### Features

- Diagram image with SVG bounding-box overlays
- Red overlays for components, blue for text labels
- Hover-to-highlight and click-to-pin interaction
- Searchable sidebar listing all detected elements
- Dark theme matching the main web UI
- Image downscaled to max 1400px for browser performance
- Text labels capped at 200 in the visualization

---

## Tool Registration

Tools are registered in `src/agent/cad_agent.py`:

```python
self._tools = [get_overview, inspect_zone, inspect_component, search_text, trace_net]

self._agent = LlmAgent(
    model=model,
    tools=self._tools,
    before_tool_callback=before_tool,
    after_tool_callback=after_tool,
    ...
)
```

---

## Tool Callbacks & ToolCallTracker

**Code:** `src/agent/callbacks.py`

ADK supports two lifecycle callbacks on every tool call:

### `before_tool(tool, args, tool_context) -> dict | None`

Called before the tool function executes. Returns:
- `None` → proceed with the call normally
- `dict` → short-circuit: the dict is used as the tool result (the actual function is NOT called)

Used for:
1. **Argument validation** — if `diagram_id` is missing or empty, returns `{"error": "diagram_id is required"}` immediately
2. **Timing start** — calls `tracker.record_start(tool_name, args)`
3. **Logging** — logs the tool name and argument keys at DEBUG level

```python
def before_tool(tool, args, tool_context) -> dict | None:
    tool_name = getattr(tool, "name", str(tool))

    if tool_name in _DIAGRAM_TOOLS:
        diagram_id = args.get("diagram_id", "")
        if not diagram_id or not isinstance(diagram_id, str):
            return {"error": "diagram_id is required and must be a non-empty string."}

    tracker.record_start(tool_name, dict(args))
    return None   # proceed normally
```

### `after_tool(tool, args, tool_context, tool_response) -> dict | None`

Called after the tool function returns. Returns:
- `None` → pass `tool_response` unchanged to the LLM
- `dict` → override the tool response with this dict

Used for:
1. **Timing end** — calls `tracker.record_end(tool_name, success=..., result_summary=...)`
2. **Error logging** — logs errors at WARNING level when `"error"` key present in response
3. **Result summarisation** — `_summarise_result()` generates a one-line summary per tool type

### ToolCallTracker

A module-level singleton accumulating per-tool records across a single `analyze_async()` run. After the agent completes, `tracker.get_records()` returns:

```json
[
  {
    "tool_name": "get_overview",
    "args": {"diagram_id": "550e8400-..."},
    "duration_ms": 142.3,
    "success": true,
    "result_summary": "42 components, 230 text labels",
    "error": null
  },
  {
    "tool_name": "inspect_zone",
    "args": {"x1": 0, "y1": 0, "x2": 50, "y2": 50},
    "duration_ms": 2341.0,
    "success": true,
    "result_summary": "3 tiles, 12 components, 45 labels",
    "error": null
  }
]
```

This list is included in the `/analyze` response as `tool_calls` and rendered by the frontend as the "Agent Activity" collapsible timeline.

The `_sanitize_args()` helper strips large string values (> 200 characters) before recording them, preventing base64 image data from bloating the tracker records.

---

## Adding a New Tool

1. Create `src/tools/my_new_tool.py` with a function `def my_new_tool(diagram_id: str, ...) -> dict[str, Any]`
2. Add the function to the `self._tools` list in `src/agent/cad_agent.py`
3. Add `"my_new_tool"` to `_DIAGRAM_TOOLS` in `callbacks.py` if it takes `diagram_id`
4. Add a `case "my_new_tool"` branch in `_summarise_result()` for the Activity timeline
5. Add tests in `tests/test_tools/test_my_new_tool.py` using the `configured_store` fixture
6. Update the system prompt in `src/agent/prompts.py` to describe when to call the new tool
