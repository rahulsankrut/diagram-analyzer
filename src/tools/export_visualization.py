"""Tool: export_visualization — generate a self-contained interactive HTML.

Renders the diagram image with SVG bounding-box overlays in a two-panel layout:
- Left panel: zoomable/pannable diagram image with SVG overlays
- Right panel: tabbed interface (Components, Graph, Details)

Features: confidence color-coding, type filter chips, Mermaid.js connectivity
graph, bidirectional click-to-highlight, component detail panel.

The only external dependency is Mermaid.js loaded via CDN for the graph tab.
"""

from __future__ import annotations

import html
import json
from typing import Any

from src.tools._image_utils import bbox_to_pixel_dict, downscale_to_fit, image_to_base64
from src.tools._store import get_store


def export_visualization(diagram_id: str) -> dict[str, Any]:
    """Generate an interactive HTML visualization of the analysed diagram.

    The HTML includes:
    - Two-panel layout: diagram viewer + tabbed sidebar.
    - Zoomable/pannable diagram image with SVG bounding-box overlays.
    - Confidence color-coded component list with type filter chips.
    - Mermaid.js connectivity graph from trace data.
    - Click-to-inspect component detail panel.

    Args:
        diagram_id: UUID of the diagram to visualize.

    Returns:
        Dict with ``diagram_id``, ``html`` (self-contained HTML string),
        ``component_count``, ``text_label_count``.
        Contains ``error`` key when the diagram is not found.
    """
    store = get_store()
    metadata = store.get_metadata(diagram_id)
    if metadata is None:
        return {"error": f"Diagram not found: {diagram_id}"}

    # Load and encode diagram image
    original = store.load_original_image(diagram_id)
    if original is None:
        return {"error": "Original image not available for visualization."}

    img = downscale_to_fit(original, max_px=1400)
    img_w, img_h = img.size
    img_b64 = image_to_base64(img, fmt="JPEG")

    # Build element data for overlays
    elements: list[dict[str, Any]] = []
    for i, comp in enumerate(metadata.components, start=1):
        px = bbox_to_pixel_dict(comp.bbox, img_w, img_h)
        elements.append({
            "id": f"c{i}",
            "kind": "component",
            "type": comp.component_type,
            "label": comp.value or comp.component_type,
            "conf": comp.confidence,
            "conf_str": f"{comp.confidence:.0%}",
            "component_id": comp.component_id,
            "value": comp.value,
            "package": comp.package,
            "pins": len(comp.pins),
            **px,
        })
    for i, lbl in enumerate(metadata.text_labels[:200], start=1):
        px = bbox_to_pixel_dict(lbl.bbox, img_w, img_h)
        elements.append({
            "id": f"t{i}",
            "kind": "text_label",
            "type": "text",
            "label": lbl.text,
            "conf": lbl.confidence,
            "conf_str": f"{lbl.confidence:.0%}",
            **px,
        })

    # Build trace data for Mermaid graph
    traces: list[dict[str, str]] = []
    comp_id_to_label: dict[str, str] = {}
    for comp in metadata.components:
        short = comp.value or comp.component_type
        comp_id_to_label[comp.component_id] = short[:20]
    for trace in metadata.traces[:100]:
        src_label = comp_id_to_label.get(trace.from_component, trace.from_component[:8])
        dst_label = comp_id_to_label.get(trace.to_component, trace.to_component[:8])
        traces.append({
            "from": src_label,
            "to": dst_label,
            "from_pin": trace.from_pin,
            "to_pin": trace.to_pin,
        })

    # Build Mermaid graph: real connectivity if traces exist, else component topology
    mermaid_def, graph_mode = _build_mermaid(traces, metadata.components)

    # Collect unique component types for filter chips
    comp_types = sorted({el["type"] for el in elements if el["kind"] == "component"})

    html_content = _render_html(
        img_b64, img_w, img_h, elements, mermaid_def, graph_mode, comp_types, diagram_id,
    )

    return {
        "diagram_id": diagram_id,
        "html": html_content,
        "component_count": len(metadata.components),
        "text_label_count": len(metadata.text_labels),
    }


def _conf_color(conf: float) -> str:
    """Return a CSS color string based on confidence level."""
    if conf >= 0.8:
        return "#00b894"
    elif conf >= 0.5:
        return "#fdcb6e"
    return "#e17055"


def _render_html(
    img_b64: str,
    img_w: int,
    img_h: int,
    elements: list[dict[str, Any]],
    mermaid_def: str,
    graph_mode: str,
    comp_types: list[str],
    diagram_id: str,
) -> str:
    """Render the self-contained HTML visualization with two-panel layout."""
    # Build SVG overlay rects
    svg_rects: list[str] = []
    for el in elements:
        color = "#e63946" if el["kind"] == "component" else "#457b9d"
        esc_label = html.escape(el["label"][:40], quote=True)
        svg_rects.append(
            f'<rect class="overlay" data-id="{el["id"]}" '
            f'data-kind="{el["kind"]}" data-type="{html.escape(el["type"])}" '
            f'x="{el["x"]}" y="{el["y"]}" '
            f'width="{el["w"]}" height="{el["h"]}" '
            f'stroke="{color}" fill="{color}" fill-opacity="0.08" '
            f'stroke-width="2" rx="2">'
            f'<title>[{el["id"]}] {esc_label}</title></rect>'
        )

    # Build sidebar list items with confidence colors
    sidebar_items: list[str] = []
    for el in elements:
        esc = html.escape(el["label"][:60])
        kind_cls = "comp" if el["kind"] == "component" else "text"
        conf_col = _conf_color(el["conf"])
        data_attrs = f'data-id="{el["id"]}" data-kind="{el["kind"]}" '
        data_attrs += f'data-type="{html.escape(el["type"])}" '
        data_attrs += f'data-search="{html.escape(el["label"].lower(), quote=True)}"'
        sidebar_items.append(
            f'<li class="item {kind_cls}" {data_attrs}>'
            f'<span class="tag">{html.escape(el["type"])}</span> '
            f'<span class="lbl">{esc}</span> '
            f'<span class="conf" style="color:{conf_col}">{el["conf_str"]}</span>'
            f'</li>'
        )

    # Build type filter chips HTML
    chips_html = ""
    for t in comp_types:
        chips_html += (
            f'<button class="chip active" data-filter="{html.escape(t)}" '
            f'onclick="toggleFilter(this)">{html.escape(t)}</button>'
        )

    # JSON data for the detail panel
    elements_json = json.dumps(elements, default=str)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CAD Visualization — {html.escape(diagram_id[:12])}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background:#0b0c10; color:#e0e0e0; display:flex; height:100vh; overflow:hidden; }}

/* Left Panel — Diagram Viewer */
#viewer {{ flex:1; overflow:hidden; position:relative; background:#0b0c10; }}
#canvas-wrap {{ width:100%; height:100%; overflow:hidden; cursor:grab; }}
#canvas-wrap:active {{ cursor:grabbing; }}
#canvas {{ position:relative; transform-origin:0 0; transition:transform 0.1s ease-out; }}
#canvas img {{ display:block; user-select:none; -webkit-user-drag:none; }}
#canvas svg {{ position:absolute; top:0; left:0; pointer-events:all; }}
.overlay {{ cursor:pointer; transition: fill-opacity .15s, stroke-width .15s; }}
.overlay:hover, .overlay.highlight {{ fill-opacity:0.25 !important; stroke-width:3; }}
.overlay.dim {{ opacity:0.15; }}

/* Zoom controls */
.zoom-controls {{ position:absolute; bottom:16px; left:16px; display:flex; gap:6px; z-index:20; }}
.zoom-btn {{ width:36px; height:36px; border-radius:8px; border:1px solid #32364a; background:rgba(18,20,28,0.9); color:#e0e0e0; font-size:18px; cursor:pointer; display:flex; align-items:center; justify-content:center; backdrop-filter:blur(8px); }}
.zoom-btn:hover {{ background:rgba(108,92,231,0.3); border-color:#6c5ce7; }}
.zoom-level {{ position:absolute; bottom:16px; left:140px; font-size:12px; color:#888; background:rgba(18,20,28,0.8); padding:4px 10px; border-radius:6px; z-index:20; }}

/* Right Panel — Tabbed Sidebar */
#sidebar {{ width:380px; background:#12141c; display:flex; flex-direction:column; border-left:2px solid #242735; flex-shrink:0; }}

/* Tabs */
.tabs {{ display:flex; border-bottom:2px solid #242735; flex-shrink:0; }}
.tab {{ flex:1; padding:12px 8px; text-align:center; font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; color:#a4b0be; cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-2px; transition:all 0.2s; }}
.tab:hover {{ color:#fff; background:rgba(255,255,255,0.03); }}
.tab.active {{ color:#6c5ce7; border-bottom-color:#6c5ce7; }}
.tab-body {{ display:none; flex:1; overflow-y:auto; }}
.tab-body.active {{ display:flex; flex-direction:column; }}

/* Components Tab */
#tab-components {{ padding:12px; }}
.search-bar {{ width:100%; padding:8px 12px; background:#1c1e29; border:1px solid #32364a; color:#fff; border-radius:8px; margin-bottom:10px; font-size:13px; outline:none; }}
.search-bar:focus {{ border-color:#6c5ce7; box-shadow:0 0 0 2px rgba(108,92,231,0.3); }}
.filter-chips {{ display:flex; flex-wrap:wrap; gap:4px; margin-bottom:10px; }}
.chip {{ padding:3px 10px; border-radius:100px; font-size:10px; font-weight:600; text-transform:uppercase; border:1px solid #32364a; background:rgba(108,92,231,0.1); color:#a29bfe; cursor:pointer; transition:all 0.2s; }}
.chip.active {{ background:#6c5ce7; color:#fff; border-color:#6c5ce7; }}
.chip:hover {{ border-color:#6c5ce7; }}
#count {{ font-size:11px; color:#888; margin-bottom:6px; }}
#elements {{ list-style:none; flex:1; }}
.item {{ padding:6px 8px; cursor:pointer; border-radius:6px; font-size:12px; margin-bottom:2px; display:flex; align-items:center; gap:6px; transition:background 0.15s; }}
.item:hover, .item.active {{ background:#1c1e29; }}
.tag {{ background:#457b9d; color:#fff; padding:1px 6px; border-radius:3px; font-size:10px; text-transform:uppercase; flex-shrink:0; }}
.comp .tag {{ background:#e63946; }}
.conf {{ margin-left:auto; font-size:10px; flex-shrink:0; font-weight:600; }}
.lbl {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }}
.hidden {{ display:none !important; }}

/* Graph Tab */
#tab-graph {{ padding:12px; align-items:center; }}
#tab-graph .no-data {{ color:#888; font-size:14px; text-align:center; padding:40px 20px; line-height:1.6; }}
#mermaid-container {{ width:100%; overflow:auto; }}
#mermaid-container svg {{ max-width:100%; }}
.graph-note {{ display:flex; align-items:flex-start; gap:8px; background:rgba(108,92,231,0.1); border:1px solid rgba(108,92,231,0.3); border-radius:8px; padding:10px 12px; font-size:12px; color:#a29bfe; line-height:1.5; margin-bottom:12px; }}
.graph-note svg {{ flex-shrink:0; margin-top:1px; }}

/* Details Tab */
#tab-details {{ padding:16px; }}
.detail-placeholder {{ color:#888; font-size:14px; text-align:center; padding:40px 20px; }}
.detail-card {{ background:#1c1e29; border-radius:10px; padding:16px; border:1px solid #32364a; }}
.detail-card h3 {{ font-size:16px; color:#fff; margin-bottom:12px; display:flex; align-items:center; gap:8px; }}
.detail-card .detail-type {{ font-size:11px; text-transform:uppercase; background:#6c5ce7; color:#fff; padding:2px 8px; border-radius:4px; }}
.detail-row {{ display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #242735; font-size:13px; }}
.detail-row:last-child {{ border-bottom:none; }}
.detail-key {{ color:#a4b0be; }}
.detail-val {{ color:#fff; font-weight:500; }}
.conf-bar {{ height:6px; border-radius:3px; margin-top:8px; }}
</style>
</head>
<body>

<!-- Left Panel: Diagram Viewer -->
<div id="viewer">
  <div id="canvas-wrap">
    <div id="canvas">
      <img src="data:image/jpeg;base64,{img_b64}" width="{img_w}" height="{img_h}" alt="CAD Diagram" draggable="false">
      <svg xmlns="http://www.w3.org/2000/svg" width="{img_w}" height="{img_h}" viewBox="0 0 {img_w} {img_h}">
        {"".join(svg_rects)}
      </svg>
    </div>
  </div>
  <div class="zoom-controls">
    <button class="zoom-btn" onclick="zoomIn()" title="Zoom in">+</button>
    <button class="zoom-btn" onclick="zoomOut()" title="Zoom out">&minus;</button>
    <button class="zoom-btn" onclick="zoomReset()" title="Reset zoom">&#8634;</button>
  </div>
  <div class="zoom-level" id="zoom-level">100%</div>
</div>

<!-- Right Panel: Tabbed Sidebar -->
<div id="sidebar">
  <div class="tabs">
    <div class="tab active" data-tab="components">Components</div>
    <div class="tab" data-tab="graph">Graph</div>
    <div class="tab" data-tab="details">Details</div>
  </div>

  <!-- Components Tab -->
  <div id="tab-components" class="tab-body active">
    <input class="search-bar" id="search" type="text" placeholder="Search labels...">
    <div class="filter-chips" id="filter-chips">{chips_html}</div>
    <div id="count">{len(elements)} elements</div>
    <ul id="elements">{"".join(sidebar_items)}</ul>
  </div>

  <!-- Graph Tab -->
  <div id="tab-graph" class="tab-body">
    {_render_graph_tab(mermaid_def, graph_mode)}
  </div>

  <!-- Details Tab -->
  <div id="tab-details" class="tab-body">
    <div class="detail-placeholder" id="detail-placeholder">Click a component on the diagram or in the list to see its details.</div>
    <div class="detail-card hidden" id="detail-card"></div>
  </div>
</div>

{'<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>' if mermaid_def else '<!-- no mermaid -->'}
<script>
// ---- Data ----
const ELEMENTS = {elements_json};

// ---- DOM ----
const items = document.querySelectorAll('.item');
const rects = document.querySelectorAll('.overlay');
const searchInput = document.getElementById('search');
const countEl = document.getElementById('count');
const canvas = document.getElementById('canvas');
const canvasWrap = document.getElementById('canvas-wrap');
const zoomLabel = document.getElementById('zoom-level');

// ---- Tabs ----
document.querySelectorAll('.tab').forEach(tab => {{
  tab.addEventListener('click', () => {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-body').forEach(b => b.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  }});
}});

// ---- Zoom / Pan ----
let scale = 1, panX = 0, panY = 0, isPanning = false, startX = 0, startY = 0;

function applyTransform() {{
  canvas.style.transform = `translate(${{panX}}px, ${{panY}}px) scale(${{scale}})`;
  zoomLabel.textContent = Math.round(scale * 100) + '%';
}}

function zoomIn()  {{ scale = Math.min(scale * 1.25, 5); applyTransform(); }}
function zoomOut() {{ scale = Math.max(scale / 1.25, 0.2); applyTransform(); }}
function zoomReset() {{ scale = 1; panX = 0; panY = 0; applyTransform(); }}

canvasWrap.addEventListener('wheel', (e) => {{
  e.preventDefault();
  const delta = e.deltaY > 0 ? 0.9 : 1.1;
  scale = Math.max(0.2, Math.min(5, scale * delta));
  applyTransform();
}}, {{ passive: false }});

canvasWrap.addEventListener('mousedown', (e) => {{
  if (e.target.classList.contains('overlay')) return;
  isPanning = true; startX = e.clientX - panX; startY = e.clientY - panY;
}});
canvasWrap.addEventListener('mousemove', (e) => {{
  if (!isPanning) return;
  panX = e.clientX - startX; panY = e.clientY - startY;
  canvas.style.transition = 'none';
  applyTransform();
  canvas.style.transition = '';
}});
canvasWrap.addEventListener('mouseup',   () => {{ isPanning = false; }});
canvasWrap.addEventListener('mouseleave', () => {{ isPanning = false; }});

// ---- Highlight / Select ----
let activeId = null;

function highlight(id) {{
  activeId = id;
  rects.forEach(r => r.classList.toggle('highlight', r.dataset.id === id));
  items.forEach(i => i.classList.toggle('active', i.dataset.id === id));

  // Scroll sidebar item into view
  const activeItem = document.querySelector(`.item[data-id="${{id}}"]`);
  if (activeItem) activeItem.scrollIntoView({{ behavior:'smooth', block:'center' }});

  // Show detail panel
  showDetail(id);

  // Switch to details tab
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-body').forEach(b => b.classList.remove('active'));
  document.querySelector('[data-tab="details"]').classList.add('active');
  document.getElementById('tab-details').classList.add('active');
}}

items.forEach(i => i.addEventListener('click', () => highlight(i.dataset.id)));
rects.forEach(r => r.addEventListener('click', (e) => {{
  e.stopPropagation();
  highlight(r.dataset.id);
}}));

// ---- Detail Panel ----
function showDetail(id) {{
  const el = ELEMENTS.find(e => e.id === id);
  const card = document.getElementById('detail-card');
  const placeholder = document.getElementById('detail-placeholder');
  if (!el) {{ card.classList.add('hidden'); placeholder.classList.remove('hidden'); return; }}

  placeholder.classList.add('hidden');
  card.classList.remove('hidden');

  const confColor = el.conf >= 0.8 ? '#00b894' : (el.conf >= 0.5 ? '#fdcb6e' : '#e17055');
  const confPct = Math.round(el.conf * 100);

  let rows = `
    <div class="detail-row"><span class="detail-key">ID</span><span class="detail-val">${{el.id}}</span></div>
    <div class="detail-row"><span class="detail-key">Kind</span><span class="detail-val">${{el.kind}}</span></div>
    <div class="detail-row"><span class="detail-key">Type</span><span class="detail-val">${{el.type}}</span></div>
    <div class="detail-row"><span class="detail-key">Label</span><span class="detail-val">${{el.label}}</span></div>
    <div class="detail-row"><span class="detail-key">Confidence</span><span class="detail-val" style="color:${{confColor}}">${{confPct}}%</span></div>
    <div class="conf-bar" style="background:${{confColor}}33;"><div style="width:${{confPct}}%;height:100%;background:${{confColor}};border-radius:3px;"></div></div>
  `;

  if (el.value) rows += `<div class="detail-row"><span class="detail-key">Value</span><span class="detail-val">${{el.value}}</span></div>`;
  if (el.package) rows += `<div class="detail-row"><span class="detail-key">Package</span><span class="detail-val">${{el.package}}</span></div>`;
  if (el.pins !== undefined) rows += `<div class="detail-row"><span class="detail-key">Pins</span><span class="detail-val">${{el.pins}}</span></div>`;
  rows += `
    <div class="detail-row"><span class="detail-key">Position</span><span class="detail-val">(${{el.x}}, ${{el.y}})</span></div>
    <div class="detail-row"><span class="detail-key">Size</span><span class="detail-val">${{el.w}} x ${{el.h}} px</span></div>
  `;

  card.innerHTML = `
    <h3>${{el.kind === 'component' ? '<span class="detail-type" style="background:#e63946">' + el.type + '</span>' : '<span class="detail-type">text</span>'}}&nbsp;${{el.label.substring(0, 30)}}</h3>
    ${{rows}}
  `;
}}

// ---- Search ----
searchInput.addEventListener('input', () => {{
  const q = searchInput.value.toLowerCase();
  let visible = 0;
  items.forEach(i => {{
    const show = i.dataset.search.includes(q);
    i.classList.toggle('hidden', !show);
    const rid = i.dataset.id;
    rects.forEach(r => {{ if (r.dataset.id === rid) r.style.display = show ? '' : 'none'; }});
    if (show) visible++;
  }});
  countEl.textContent = visible + ' / ' + items.length + ' elements';
}});

// ---- Type Filter Chips ----
const activeFilters = new Set({json.dumps(comp_types)});

function toggleFilter(btn) {{
  const type = btn.dataset.filter;
  if (activeFilters.has(type)) {{
    activeFilters.delete(type);
    btn.classList.remove('active');
  }} else {{
    activeFilters.add(type);
    btn.classList.add('active');
  }}
  applyFilters();
}}

function applyFilters() {{
  items.forEach(i => {{
    if (i.dataset.kind !== 'component') return;
    const show = activeFilters.has(i.dataset.type);
    i.classList.toggle('hidden', !show);
    const rid = i.dataset.id;
    rects.forEach(r => {{
      if (r.dataset.id === rid) {{
        r.style.display = show ? '' : 'none';
        r.classList.toggle('dim', !show);
      }}
    }});
  }});
}}

// ---- Mermaid Init ----
{"if (typeof mermaid !== 'undefined') { mermaid.initialize({ startOnLoad: true, theme: 'dark', themeVariables: { primaryColor: '#6c5ce7', primaryTextColor: '#fff', primaryBorderColor: '#a29bfe', lineColor: '#457b9d', secondaryColor: '#16213e', tertiaryColor: '#1c1e29' } }); }" if mermaid_def else "// mermaid not loaded"}
</script>
</body>
</html>"""


def _build_mermaid(
    traces: list[dict[str, str]],
    components: list[Any] | None = None,
) -> tuple[str, str]:
    """Build a Mermaid graph from traces, or a component topology fallback.

    When trace data is available, renders a directed connectivity graph with
    pin labels.  When no traces exist but components were detected, renders a
    grouped topology diagram (nodes only, no fabricated edges) with a clear
    note that connection data is absent.

    Args:
        traces: List of dicts with ``from``, ``to``, ``from_pin``, ``to_pin``.
        components: Optional list of ``Component`` objects used for the
            topology fallback when traces is empty.

    Returns:
        Tuple of ``(mermaid_definition, graph_mode)`` where ``graph_mode`` is
        one of ``"connectivity"``, ``"topology"``, or ``""`` (no graph).
    """
    if traces:
        lines = ["graph LR"]
        seen_edges: set[str] = set()
        for t in traces:
            src = _mermaid_safe(t["from"])
            dst = _mermaid_safe(t["to"])
            edge_key = f"{src}-->{dst}"
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            pin_label = ""
            if t.get("from_pin") or t.get("to_pin"):
                pin_label = f"|{t.get('from_pin', '')} → {t.get('to_pin', '')}|"
            lines.append(f"  {src} -->{pin_label} {dst}")
        if len(lines) > 1:
            return "\n".join(lines), "connectivity"

    # No traces — fall back to component topology grouped by type
    if not components:
        return "", ""

    limited = components[:60]  # cap to avoid Mermaid overflow

    # Group by component type
    by_type: dict[str, list[Any]] = {}
    for comp in limited:
        ctype = comp.component_type or "unknown"
        by_type.setdefault(ctype, []).append(comp)

    lines = ["graph LR"]
    for ctype, comps in by_type.items():
        safe_type = _mermaid_safe(ctype.replace(" ", "_"))
        lines.append(f"  subgraph {safe_type}")
        for comp in comps:
            node_id = _mermaid_safe(comp.component_id.replace("-", "_"))[:16]
            display = _mermaid_safe(comp.value or ctype)[:22]
            lines.append(f'    {node_id}["{display}"]')
        lines.append("  end")

    return ("\n".join(lines), "topology") if len(lines) > 1 else ("", "")


def _render_graph_tab(mermaid_def: str, graph_mode: str) -> str:
    """Return the inner HTML for the Graph tab panel.

    Args:
        mermaid_def: Mermaid graph definition string (may be empty).
        graph_mode: ``"connectivity"``, ``"topology"``, or ``""`` for no data.

    Returns:
        HTML string for the graph tab body.
    """
    if not mermaid_def:
        return (
            '<div class="no-data">'
            "No components or connectivity data available.<br>"
            "Run the preprocessing pipeline to generate diagram structure."
            "</div>"
        )

    if graph_mode == "topology":
        note = (
            '<div class="graph-note">'
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2">'
            '<circle cx="12" cy="12" r="10"/>'
            '<line x1="12" y1="8" x2="12" y2="12"/>'
            '<line x1="12" y1="16" x2="12.01" y2="16"/>'
            "</svg>"
            " Component topology — no electrical trace data available. "
            "Nodes are detected components grouped by type; edges are not shown."
            "</div>"
        )
    else:
        note = ""

    return (
        f'{note}<div id="mermaid-container">'
        f'<pre class="mermaid">{html.escape(mermaid_def)}</pre>'
        f"</div>"
    )


def _mermaid_safe(label: str) -> str:
    """Sanitize a label for use as a Mermaid node identifier."""
    safe = label.replace('"', "'").replace("(", "[").replace(")", "]")
    safe = safe.replace("<", "").replace(">", "").replace("{", "").replace("}", "")
    return safe or "unknown"
