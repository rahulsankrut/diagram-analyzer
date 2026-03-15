"""Semantic trace model — a resolved connection between two component pins."""

import uuid
from typing import Any

from pydantic import BaseModel, Field


class Trace(BaseModel):
    """A semantic electrical or fluid connection between two component pins.

    A Trace is the *interpreted* form of a detected line: it references source
    and target components and pins by their IDs rather than storing raw geometry.
    Path points provide the route for visualization, but the component/pin
    references are the authoritative representation.

    Attributes:
        trace_id: UUID string uniquely identifying this trace.
        from_component: ``component_id`` of the source component.
        from_pin: ``pin_id`` (or pin name) of the source connection point.
        to_component: ``component_id`` of the destination component.
        to_pin: ``pin_id`` (or pin name) of the destination connection point.
        path: Ordered list of normalized (x, y) waypoints along the trace route,
            including the start and end points.  May be empty when only the
            topology (from/to) is known without geometric detail.
    """

    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_component: str
    from_pin: str
    to_component: str
    to_pin: str
    path: list[tuple[float, float]] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation.

        Returns:
            Dict with all trace fields; ``path`` is a list of [x, y] pairs.
        """
        return self.model_dump(mode="json")
