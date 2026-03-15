"""Tool: trace_net — follow electrical/fluid connections from a component pin.

Uses the CV-extracted trace topology stored in DiagramMetadata to walk
connectivity from a given component pin and return all directly connected
components and the path geometry.
"""

from __future__ import annotations

from typing import Any

from src.models.component import Component
from src.models.trace import Trace
from src.tools._store import get_store


def trace_net(diagram_id: str, component_id: str, pin: str) -> dict[str, Any]:
    """Follow all connections from a component pin and return connected components.

    Searches both directions of every trace: if the component is the source
    (``from_component``) the counterpart is the destination, and vice versa.
    An empty *pin* matches all pins on the component.

    Args:
        diagram_id: UUID of the diagram to search.
        component_id: ``component_id`` of the starting component.
        pin: Pin name or ``pin_id`` to trace from.  Pass ``""`` to return all
            connections for the component regardless of pin.

    Returns:
        Dict with keys ``diagram_id``, ``component_id``, ``pin``,
        ``connections`` (list of connection dicts each containing ``trace_id``,
        ``connected_component_id``, ``connected_component_type``,
        ``connected_pin``, ``direction`` (``"from"`` or ``"to"``), ``path``),
        ``connection_count``.
        Returns a graceful ``trace_data_unavailable`` flag when no components
        or traces exist.
        Contains ``error`` key when the diagram or component is not found.
    """
    store = get_store()
    metadata = store.get_metadata(diagram_id)
    if metadata is None:
        return {"error": f"Diagram not found: {diagram_id}"}

    if not metadata.components:
        return {
            "diagram_id": diagram_id,
            "component_id": component_id,
            "pin": pin,
            "trace_data_unavailable": True,
            "message": "No components have been extracted for this diagram. "
                       "Use inspect_zone() to visually identify connections.",
            "connections": [],
            "connection_count": 0,
        }

    component = metadata.get_component(component_id)
    if component is None:
        return {"error": f"Component not found: {component_id}"}

    if not metadata.traces:
        return {
            "diagram_id": diagram_id,
            "component_id": component_id,
            "pin": pin,
            "trace_data_unavailable": True,
            "connections": [],
            "connection_count": 0,
        }

    connections = _collect_connections(component_id, pin, metadata.traces, metadata.components)

    return {
        "diagram_id": diagram_id,
        "component_id": component_id,
        "pin": pin,
        "trace_data_unavailable": False,
        "connections": connections,
        "connection_count": len(connections),
    }


def _pin_matches(trace_pin: str, query_pin: str) -> bool:
    """Return True when *trace_pin* matches the query or query is empty.

    Args:
        trace_pin: Pin field stored in the trace record.
        query_pin: Pin provided by the caller; empty string means match-all.

    Returns:
        Boolean match result.
    """
    return query_pin == "" or trace_pin == query_pin


def _collect_connections(
    component_id: str,
    pin: str,
    traces: list[Trace],
    all_components: list[Component],
) -> list[dict[str, Any]]:
    """Build the connections list from all matching traces.

    Args:
        component_id: Starting component.
        pin: Pin to match (empty = all pins).
        traces: All traces in the diagram.
        all_components: All components for type look-up.

    Returns:
        List of connection dicts.
    """
    comp_index: dict[str, Component] = {c.component_id: c for c in all_components}
    connections: list[dict[str, Any]] = []

    for trace in traces:
        if trace.from_component == component_id and _pin_matches(trace.from_pin, pin):
            peer = comp_index.get(trace.to_component)
            connections.append(_connection_dict(trace, "from", trace.to_component, trace.to_pin, peer))
        elif trace.to_component == component_id and _pin_matches(trace.to_pin, pin):
            peer = comp_index.get(trace.from_component)
            connections.append(
                _connection_dict(trace, "to", trace.from_component, trace.from_pin, peer)
            )

    return connections


def _connection_dict(
    trace: Trace,
    direction: str,
    peer_id: str,
    peer_pin: str,
    peer_component: Component | None,
) -> dict[str, Any]:
    """Serialize one connection record.

    Args:
        trace: The trace that establishes this connection.
        direction: ``"from"`` if the queried component is the source, ``"to"`` if destination.
        peer_id: ``component_id`` of the connected component.
        peer_pin: Pin name/ID on the connected component.
        peer_component: Connected :class:`Component` model, or ``None`` if not found.

    Returns:
        Dict with connection fields.
    """
    return {
        "trace_id": trace.trace_id,
        "connected_component_id": peer_id,
        "connected_component_type": peer_component.component_type if peer_component else "unknown",
        "connected_pin": peer_pin,
        "direction": direction,
        "path": [list(pt) for pt in trace.path],
    }
