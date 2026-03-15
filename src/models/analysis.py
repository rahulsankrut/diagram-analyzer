"""Analysis output models — BOM, netlist, and final AnalysisResult."""

import uuid

from pydantic import BaseModel, Field

from src.models.ocr import BoundingBox


class BOMEntry(BaseModel):
    """One line item in the bill of materials.

    Attributes:
        component_id: ID matching the corresponding Symbol.symbol_id.
        reference_designator: Drawing reference, e.g. ``"R12"``, ``"V-101"``.
        description: Human-readable component description.
        quantity: Count of identical components (always ≥ 1).
        bbox: Normalized bounding box of the component in the diagram.
    """

    component_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    reference_designator: str
    description: str
    quantity: int = Field(default=1, ge=1)
    bbox: BoundingBox


class NetlistEntry(BaseModel):
    """One electrical or fluid net connecting a set of components.

    Attributes:
        net_id: Unique net identifier.
        connected_component_ids: IDs of all components on this net.
        signal_name: Optional net label extracted from the diagram (e.g. ``"+24V"``).
    """

    net_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    connected_component_ids: list[str] = Field(default_factory=list)
    signal_name: str | None = None


class AnalysisResult(BaseModel):
    """Final structured output produced by the agentic reasoning pipeline.

    Attributes:
        diagram_id: ID of the analyzed diagram.
        bom: Bill of materials — one entry per distinct component type/instance.
        netlist: Extracted nets / connections between components.
        summary: Plain-language natural language summary of the diagram.
        confidence: Aggregate confidence score in [0.0, 1.0].
    """

    diagram_id: str
    bom: list[BOMEntry] = Field(default_factory=list)
    netlist: list[NetlistEntry] = Field(default_factory=list)
    summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
