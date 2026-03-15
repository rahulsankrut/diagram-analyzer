"""Tool: export_visualization — generate a self-contained interactive HTML.

Renders the diagram image with SVG bounding-box overlays for every detected
component and text label, plus a searchable sidebar with component details.
No external dependencies — the output is a single HTML file.
"""

from __future__ import annotations

import html
from typing import Any

from src.tools._image_utils import bbox_to_pixel_dict, downscale_to_fit, image_to_base64
from src.tools._store import get_store


def export_visualization(diagram_id: str) -> dict[str, Any]:
    """Generate an interactive HTML visualization of the analysed diagram.

    The HTML includes:
    - The diagram image with SVG bounding-box overlays.
    - Hover-to-highlight and click-to-pin component/label markers.
    - A searchable sidebar listing all detected elements.

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
            "conf": f"{comp.confidence:.0%}",
            **px,
        })
    for i, lbl in enumerate(metadata.text_labels[:200], start=1):
        px = bbox_to_pixel_dict(lbl.bbox, img_w, img_h)
        elements.append({
            "id": f"t{i}",
            "kind": "text_label",
            "type": "text",
            "label": lbl.text,
            "conf": f"{lbl.confidence:.0%}",
            **px,
        })

    html_content = _render_html(img_b64, img_w, img_h, elements, diagram_id)

    return {
        "diagram_id": diagram_id,
        "html": html_content,
        "component_count": len(metadata.components),
        "text_label_count": len(metadata.text_labels),
    }


def _render_html(
    img_b64: str,
    img_w: int,
    img_h: int,
    elements: list[dict[str, Any]],
    diagram_id: str,
) -> str:
    """Render the self-contained HTML visualization."""
    # Build SVG overlay rects
    svg_rects: list[str] = []
    for el in elements:
        color = "#e63946" if el["kind"] == "component" else "#457b9d"
        esc_label = html.escape(el["label"][:40], quote=True)
        svg_rects.append(
            f'<rect class="overlay" data-id="{el["id"]}" '
            f'x="{el["x"]}" y="{el["y"]}" '
            f'width="{el["w"]}" height="{el["h"]}" '
            f'stroke="{color}" fill="{color}" fill-opacity="0.08" '
            f'stroke-width="2" rx="2">'
            f'<title>[{el["id"]}] {esc_label}</title></rect>'
        )

    # Build sidebar list items
    sidebar_items: list[str] = []
    for el in elements:
        esc = html.escape(el["label"][:60])
        kind_cls = "comp" if el["kind"] == "component" else "text"
        sidebar_items.append(
            f'<li class="item {kind_cls}" data-id="{el["id"]}" '
            f'data-search="{html.escape(el["label"].lower(), quote=True)}">'
            f'<span class="tag">{el["type"]}</span> '
            f'<span class="lbl">{esc}</span> '
            f'<span class="conf">{el["conf"]}</span></li>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CAD Visualization — {html.escape(diagram_id[:12])}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: system-ui, sans-serif; background:#1a1a2e; color:#e0e0e0; display:flex; height:100vh; }}
#sidebar {{ width:340px; background:#16213e; overflow-y:auto; padding:12px; flex-shrink:0; border-right:2px solid #0f3460; }}
#sidebar h2 {{ font-size:14px; color:#a8dadc; margin-bottom:8px; }}
#search {{ width:100%; padding:6px 10px; background:#0f3460; border:1px solid #457b9d; color:#fff; border-radius:4px; margin-bottom:10px; font-size:13px; }}
#elements {{ list-style:none; }}
.item {{ padding:5px 8px; cursor:pointer; border-radius:4px; font-size:12px; margin-bottom:2px; display:flex; align-items:center; gap:6px; }}
.item:hover, .item.active {{ background:#0f3460; }}
.tag {{ background:#457b9d; color:#fff; padding:1px 6px; border-radius:3px; font-size:10px; text-transform:uppercase; flex-shrink:0; }}
.comp .tag {{ background:#e63946; }}
.conf {{ color:#888; margin-left:auto; font-size:10px; flex-shrink:0; }}
.lbl {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.hidden {{ display:none; }}
#viewer {{ flex:1; overflow:auto; position:relative; display:flex; align-items:flex-start; justify-content:center; padding:20px; }}
#canvas {{ position:relative; }}
#canvas img {{ display:block; }}
#canvas svg {{ position:absolute; top:0; left:0; }}
.overlay {{ cursor:pointer; transition: fill-opacity .15s, stroke-width .15s; }}
.overlay:hover, .overlay.highlight {{ fill-opacity:0.25 !important; stroke-width:3; }}
#count {{ font-size:11px; color:#888; margin-bottom:8px; }}
</style>
</head>
<body>
<div id="sidebar">
  <h2>Detected Elements</h2>
  <input id="search" type="text" placeholder="Search labels...">
  <div id="count">{len(elements)} elements</div>
  <ul id="elements">{"".join(sidebar_items)}</ul>
</div>
<div id="viewer">
  <div id="canvas">
    <img src="data:image/jpeg;base64,{img_b64}" width="{img_w}" height="{img_h}" alt="CAD Diagram">
    <svg xmlns="http://www.w3.org/2000/svg" width="{img_w}" height="{img_h}" viewBox="0 0 {img_w} {img_h}">
      {"".join(svg_rects)}
    </svg>
  </div>
</div>
<script>
const items = document.querySelectorAll('.item');
const rects = document.querySelectorAll('.overlay');
const search = document.getElementById('search');
const countEl = document.getElementById('count');

function highlight(id) {{
  rects.forEach(r => r.classList.toggle('highlight', r.dataset.id === id));
  items.forEach(i => i.classList.toggle('active', i.dataset.id === id));
  const rect = document.querySelector(`.overlay[data-id="${{id}}"]`);
  if (rect) rect.scrollIntoView({{ behavior:'smooth', block:'center' }});
}}

items.forEach(i => i.addEventListener('click', () => highlight(i.dataset.id)));
rects.forEach(r => r.addEventListener('click', () => highlight(r.dataset.id)));

search.addEventListener('input', () => {{
  const q = search.value.toLowerCase();
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
</script>
</body>
</html>"""
