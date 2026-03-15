"""Tool: inspect_component — deep-dive into a single component.

Crops a tight region around the component from the full-resolution image
and returns nearby components for connectivity context.
"""

from __future__ import annotations

import math
from typing import Any

from src.models.component import Component
from src.tools._image_utils import crop_with_padding, image_to_base64
from src.tools._store import get_store

_NEARBY_THRESHOLD = 0.20  # normalized distance between component centers


def inspect_component(diagram_id: str, component_id: str) -> dict[str, Any]:
    """Return a detail crop and metadata for a single component.

    Crops a tight region around the component from the full-resolution source
    image (with 5% padding on each side) so the LLM can read fine labels or
    verify component type.  Also lists components whose centres are within
    ~20% of the image width/height for connectivity context.

    Args:
        diagram_id: UUID of the diagram containing the component.
        component_id: ``component_id`` of the component to inspect.

    Returns:
        Dict with keys ``diagram_id``, ``component`` (full component dict),
        ``crop_image_base64`` (PNG base64 or null), ``crop_bbox`` (dict or null),
        ``nearby_components`` (list of component dicts).
        Contains ``error`` key instead when diagram or component is not found.
    """
    store = get_store()
    metadata = store.get_metadata(diagram_id)
    if metadata is None:
        return {"error": f"Diagram not found: {diagram_id}"}

    component = metadata.get_component(component_id)
    if component is None:
        return {"error": f"Component not found: {component_id}"}

    crop_b64, crop_bbox_dict = _crop_component(diagram_id, component, store)
    nearby = _nearby_components(component, metadata.components)

    return {
        "diagram_id": diagram_id,
        "component": component.to_dict(),
        "crop_image_base64": crop_b64,
        "crop_bbox": crop_bbox_dict,
        "nearby_components": [c.to_dict() for c in nearby],
    }


def _crop_component(
    diagram_id: str,
    component: Component,
    store: object,
) -> tuple[str | None, dict[str, float] | None]:
    """Load original image and crop around the component with padding.

    Args:
        diagram_id: Diagram UUID.
        component: Component to crop.
        store: Active DiagramStore.

    Returns:
        Tuple of (base64 PNG string or None, crop bbox dict or None).
    """
    from src.tools._store import DiagramStore

    assert isinstance(store, DiagramStore)
    original = store.load_original_image(diagram_id)
    if original is None:
        return None, None

    crop, padded_bbox = crop_with_padding(original, component.bbox)
    return image_to_base64(crop), padded_bbox.to_dict()


def _nearby_components(target: Component, all_components: list[Component]) -> list[Component]:
    """Return components whose centre is within *_NEARBY_THRESHOLD* of *target*.

    Args:
        target: The reference component.
        all_components: All components in the diagram.

    Returns:
        Sorted list of nearby components (excluding *target* itself).
    """
    tx, ty = target.bbox.center()
    nearby: list[tuple[float, Component]] = []
    for comp in all_components:
        if comp.component_id == target.component_id:
            continue
        cx, cy = comp.bbox.center()
        dist = math.hypot(cx - tx, cy - ty)
        if dist <= _NEARBY_THRESHOLD:
            nearby.append((dist, comp))
    nearby.sort(key=lambda pair: pair[0])
    return [comp for _, comp in nearby]
