"""Component data models — pins and CAD components."""

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.models.ocr import BoundingBox


class Pin(BaseModel):
    """A single connection pin (terminal) on a CAD component.

    Positions are expressed as normalized (0.0–1.0) coordinates in the full
    diagram image space, *not* relative to the parent component's bbox.

    Attributes:
        pin_id: Unique identifier for this pin, e.g. ``"pin-1"``.
        name: Human-readable pin label as shown on the diagram (e.g. ``"1"``,
            ``"VCC"``, ``"IN+"``, ``"A"``).  Empty string when unlabelled.
        position: Normalized (x, y) coordinate of the pin's connection point.
    """

    pin_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    position: tuple[float, float]

    @field_validator("position")
    @classmethod
    def validate_normalized_position(cls, v: tuple[float, float]) -> tuple[float, float]:
        """Ensure pin position is within the normalized [0, 1] image space.

        Args:
            v: (x, y) coordinate pair.

        Returns:
            The validated coordinate pair.

        Raises:
            ValueError: If either coordinate is outside [0.0, 1.0].
        """
        x, y = v
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError(
                f"Pin position must be normalized coordinates in [0, 1], got ({x}, {y})"
            )
        return v

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation.

        Returns:
            Dict with ``pin_id``, ``name``, and ``position`` (as a list).
        """
        return self.model_dump(mode="json")


class Component(BaseModel):
    """A detected and classified CAD component.

    Richer than a raw CV symbol: carries the schematic value, physical package,
    and the list of identified pins so the agent can reason about connections.

    Attributes:
        component_id: UUID string uniquely identifying this component instance.
        component_type: Semantic type string, e.g. ``"resistor"``, ``"valve"``,
            ``"capacitor"``, ``"motor"``.  Defaults to ``"unknown"`` when
            classification confidence is below threshold.
        value: Schematic value annotation, e.g. ``"100Ω"``, ``"10µF"``,
            ``"24V DC"``.  Empty string when not annotated on the diagram.
        package: Physical package or form factor, e.g. ``"0603"``, ``"DIP-8"``,
            ``"NEMA 14"``.  Empty string when not specified.
        bbox: Normalized bounding box of the component in the diagram image.
        pins: List of identified connection pins on this component.
        confidence: Detection and classification confidence in [0.0, 1.0].
    """

    component_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    component_type: str = "unknown"
    value: str = ""
    package: str = ""
    bbox: BoundingBox
    pins: list[Pin] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation.

        Returns:
            Dict with all component fields; nested models are expanded.
        """
        return self.model_dump(mode="json")
